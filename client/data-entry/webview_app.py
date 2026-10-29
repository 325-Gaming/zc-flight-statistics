"""WebView interface for the existing data-entry service and prediction code."""

import base64
import io
import json
import os
import pathlib
import queue
import signal
import sys
import threading

import httpx
import webview
from mss.exception import ScreenShotError

if __name__ == "__main__":
    from login_window import ensure_login
    ensure_login()

import main as core
from app_updater import (
    check_startup_update,
    check_update,
    fetch_official_version,
    fetch_update_policy,
    read_update_failure,
    recover_incomplete_update,
    start_update,
    version_is_at_least,
)
from event_settings import compose_event_name
from flight_session import get_login_info, has_flight_permission, logout
from gacha_history import format_gacha_position, get_gacha_history
from gacha_upload import GachaMoveTask, GachaStateTask, GachaUploadQueue
from hotkeys import register_hotkeys
from live_page_settings import request_live_page
from result_overlay import result_overlay
from page_display_settings import (
    PAGE_ACTIVITY_ITEM,
    PAGE_DISPLAY_ITEMS,
    PAGE_TEXT_ITEMS,
    POLL_INTERVAL_MAX_SECONDS,
    POLL_INTERVAL_MIN_SECONDS,
    get_page_display_settings,
    set_page_display_settings,
)
from page_pool_settings import (
    get_page_pool_settings,
    select_initial_pool_name,
)
from page_style_settings import (
    DEFAULT_PAGE_STYLE,
    get_available_page_style_list,
    select_available_page_style,
)


UI_PATH = str(core.BASE_DIR / "webview_ui/index.html")
GATE_UI_PATH = str(core.BASE_DIR / "webview_ui/gate.html")
WINDOWS = {
    "main": (f"{core._name} {core._version}", 1024, 800, (860, 680)),
    "import": ("导入乘客名单", 560, 440, (420, 320)),
    "history": ("抽卡记录", 1000, 520, (760, 400)),
    "settings": ("设置", 900, 960, (700, 700)),
    "update": ("检查更新", 560, 330, (460, 280)),
    "gate": ("启动检查", 560, 340, (460, 300)),
    "page": ("直播页面设置", 620, 760, (560, 650)),
    "statistics": ("查看统计", 820, 790, (700, 650)),
    "preview": ("显示器预览", 980, 670, (600, 400)),
}
HOTKEY_KEYS = (
    "hotkey_gacha10", "hotkey_3x", "hotkey_4x", "hotkey_5x", "hotkey_6x",
    "hotkey_previous_user", "hotkey_next_user",
)


def _captain_profile(login_info):
    if not has_flight_permission(login_info):
        return None
    title_adj = login_info.get("title_adj")
    title_title = login_info.get("title_title")
    title = (title_adj if isinstance(title_adj, str) else "") + (
        title_title if isinstance(title_title, str) else ""
    )
    nickname = ""
    selected = login_info.get("nickname")
    if login_info.get("user_id") and isinstance(selected, str) and selected != "null":
        bilibili = login_info.get("bilibili") or {}
        arknights = login_info.get("arknights") or {}
        bilibili_name = bilibili.get("nickname", "") if isinstance(bilibili, dict) else ""
        arknights_name = arknights.get("nickname", "") if isinstance(arknights, dict) else ""
        bilibili_name = bilibili_name if isinstance(bilibili_name, str) else ""
        arknights_name = arknights_name if isinstance(arknights_name, str) else ""
        nickname = {
            "bilibili_nickname": bilibili_name,
            "arknights_nickname": arknights_name,
            "arknights_nickname_clear": arknights_name.split("#")[0],
        }.get(selected, "")
    return {"title": title, "nickname": nickname}


class Bridge:
    def __init__(self, app, view):
        self._app = app
        self._view = view

    def bootstrap(self):
        return self._app.bootstrap(self._view)

    def action(self, name, payload=None):
        try:
            return {"ok": True, "data": self._app.action(self._view, name, payload or {})}
        except (OSError, RuntimeError, ValueError, httpx.HTTPError) as error:
            return {"ok": False, "error": str(error)}


class _MacHotkeyScheduler:
    """Run the Carbon callback pump on one reusable thread."""

    def __init__(self):
        self.pending = queue.Queue()
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._run, name="hotkey-pump", daemon=True)
        self.thread.start()

    def schedule(self, callback, delay):
        if not self.stopped.is_set():
            self.pending.put((callback, delay))

    def _run(self):
        while not self.stopped.is_set():
            callback, delay = self.pending.get()
            if self.stopped.wait(delay / 1000):
                return
            callback()

    def stop(self):
        self.stopped.set()
        self.pending.put((None, 0))
        if self.thread is not threading.current_thread():
            self.thread.join(timeout=2)


class _ScheduledHotkeyListener:
    def __init__(self, listener, scheduler):
        self.listener = listener
        self.scheduler = scheduler

    def stop(self):
        self.listener.stop()
        self.scheduler.stop()


class WebViewApp:
    def __init__(self):
        self.lock = threading.RLock()
        self.predict_lock = threading.Lock()
        self.windows = {}
        self.closed = False
        self.close_started = False
        self.close_finished = False
        self.logged_out = False
        self.relogin_requested = False
        self.settings_open = False
        self.update_offer = None
        self.update_policy = None
        self.startup_complete = False
        self.gate_lock = threading.RLock()
        self.gate_state = {"phase": "checking", "message": "正在连接官方更新服务…"}
        self.startup_active = False
        self.hotkey_listener = None
        self.hotkey_start_lock = threading.RLock()
        self.user_name_list = list(core.user_name_list)
        if not self.user_name_list:
            self.user_name_list.append("乘客1")
        self.user_id = 0
        self.nickname = self.user_name_list[0]
        self.last_synced_user = None
        self.gacha_index = 1
        self.result = "等待识别结果……"
        self.status = ""
        self.captain_profile = None
        self.history_filter = "current"
        self.history_nickname = None
        self.history_records = {}
        self.history_pending = False
        self.history_status = ""
        self.preview_image = ""
        self.page_style = DEFAULT_PAGE_STYLE
        self.page_is_active = False
        self.available_styles = (DEFAULT_PAGE_STYLE,)
        self.live_id = str(core.config.get("live_id", "")).strip()
        self.upload_queue = GachaUploadQueue(
            core.client, core.submit_gacha_log_api_url, core.login_token,
            move_url=core.move_gacha_log_api_url,
            restore_url=core.restore_gacha_log_api_url,
            revoke_url=core.revoke_gacha_log_api_url,
            on_success=self._upload_done,
            on_failure=self._upload_failed,
            daemon=True,
        )
        core.app = self

    @property
    def full_event_name(self):
        return compose_event_name(core.event_name, core.pool_name)

    def _main_state(self):
        with self.lock:
            return {
                "passengers": list(self.user_name_list),
                "user_id": self.user_id,
                "nickname": self.nickname,
                "gacha_index": self.gacha_index,
                "event": self.full_event_name,
                "event_name": core.event_name,
                "pool_name": core.pool_name,
                "result": self.result,
                "show_result_overlay": core.config.get("show_result_overlay", sys.platform == "win32"),
                "page_is_active": self.page_is_active,
                "status": self.status,
                "captain": self.captain_profile,
                "hotkeys": {key: getattr(core, key) for key in HOTKEY_KEYS},
            }

    def _emit(self, view, data):
        window = self.windows.get(view)
        if window is None or self.closed:
            return
        try:
            window.run_js("window.receiveState(" + json.dumps(data, ensure_ascii=True) + ")")
        except Exception:
            # A view may close while a worker finishes. A new view gets a fresh snapshot.
            pass

    def _emit_main(self):
        self._emit("main", self._main_state())

    def _set_status(self, text):
        with self.lock:
            self.status = text
        self._emit_main()

    def show_result(self, text):
        with self.lock:
            self.result = text
        self._emit_main()

    def enqueue_gacha_result(self, count, character_list):
        with self.lock:
            nickname = self.nickname
            index = self.gacha_index
            if not nickname:
                raise ValueError("当前乘客昵称不能为空")
            self.upload_queue.submit(
                event_name=self.full_event_name,
                nickname=nickname,
                count=count,
                gacha_index=index,
                character_list=character_list,
            )
            self.gacha_index += count
            self.status = f"第 {index} 抽已加入上传队列"
        self._emit_main()

    def _upload_done(self, task, _response):
        with self.lock:
            self.status = "上传或记录操作已完成"
            if isinstance(task, (GachaMoveTask, GachaStateTask)):
                self.history_pending = False
                self.history_status = "记录操作已完成"
        self._emit_main()
        if "history" in self.windows:
            threading.Thread(
                target=self._refresh_history_after_upload,
                name="webview-history-refresh", daemon=True,
            ).start()

    def _refresh_history_after_upload(self):
        try:
            self._emit("history", self._history_state())
        except (httpx.HTTPError, ValueError):
            pass

    def _upload_failed(self, task, error):
        action = "记录操作" if isinstance(task, (GachaMoveTask, GachaStateTask)) else "上传"
        if isinstance(task, (GachaMoveTask, GachaStateTask)):
            self.history_pending = False
            self.history_status = f"{action}失败：{error}"
        self._set_status(f"{action}失败：{error}")
        if "history" in self.windows:
            self._emit("history", {"history_status": self.history_status, "pending": False})

    def _current_user(self, index):
        with self.lock:
            self.user_id = max(0, index)
            self.gacha_index = 1
            self.nickname = (
                self.user_name_list[self.user_id]
                if self.user_id < len(self.user_name_list)
                else f"乘客{self.user_id + 1}"
            )
            nickname = self.nickname
        if nickname != self.last_synced_user and core.request_set_current_user(nickname):
            self.last_synced_user = nickname
        self._emit_main()

    def _new_name(self):
        number = len(self.user_name_list) + 1
        while f"乘客{number}" in self.user_name_list:
            number += 1
        return f"乘客{number}"

    def _next_user(self):
        next_id = self.user_id + 1
        if next_id >= len(self.user_name_list):
            self.user_name_list.append(self._new_name())
        self._current_user(next_id)

    def _register_hotkeys(self, hotkeys):
        bindings = (
            (hotkeys["hotkey_gacha10"], self._predict),
            (hotkeys["hotkey_3x"], lambda: self.enqueue_gacha_result(1, ["三星干员"])),
            (hotkeys["hotkey_4x"], lambda: self.enqueue_gacha_result(1, ["四星干员"])),
            (hotkeys["hotkey_5x"], lambda: self.enqueue_gacha_result(1, ["五星干员"])),
            (hotkeys["hotkey_6x"], lambda: self.enqueue_gacha_result(1, ["六星干员"])),
            (hotkeys["hotkey_previous_user"], lambda: self.action("main", "previous", {})),
            (hotkeys["hotkey_next_user"], lambda: self.action("main", "next", {})),
        )
        active = [(hotkey, callback) for hotkey, callback in bindings if hotkey]
        if len({hotkey for hotkey, _callback in active}) != len(active):
            raise ValueError("快捷键不能重复")
        callbacks = dict(active)
        if not callbacks:
            return None
        scheduler = _MacHotkeyScheduler() if sys.platform == "darwin" else None
        try:
            listener = register_hotkeys(
                callbacks,
                dispatch=lambda callback: threading.Thread(
                    target=callback, name="webview-hotkey", daemon=True,
                ).start(),
                schedule=scheduler.schedule if scheduler is not None else None,
            )
        except Exception:
            if scheduler is not None:
                scheduler.stop()
            raise
        return _ScheduledHotkeyListener(listener, scheduler) if scheduler is not None else listener

    def start_hotkeys(self, raise_on_error=False):
        if self.settings_open or self.closed or not self.update_policy:
            return
        with self.hotkey_start_lock:
            try:
                with self.gate_lock:
                    if self.settings_open or self.closed or not self.update_policy:
                        return
                    if self.hotkey_listener is not None:
                        raise RuntimeError("上次快捷键注册尚未清理，无法重复注册")
                listener = self._register_hotkeys(
                    {key: getattr(core, key) for key in HOTKEY_KEYS}
                )
                if listener is None:
                    return
                with self.gate_lock:
                    self.hotkey_listener = listener
                    should_stop = self.closed or self.settings_open or not self.update_policy
                if should_stop:
                    self._stop_hotkeys()
            except (RuntimeError, ValueError) as error:
                if raise_on_error:
                    raise
                self._set_status(f"全局快捷键不可用：{error}")

    def _stop_hotkeys(self):
        with self.hotkey_start_lock:
            with self.gate_lock:
                listener = self.hotkey_listener
            if listener is not None:
                listener.stop()
                with self.gate_lock:
                    if self.hotkey_listener is listener:
                        self.hotkey_listener = None

    def _predict(self):
        if not self.predict_lock.acquire(blocking=False):
            return
        try:
            core.capture_and_predict()
        except (OSError, ValueError, RuntimeError, ScreenShotError) as error:
            self._set_status(f"截图或识别失败：{error}")
        finally:
            self.predict_lock.release()

    def create_window(self, view):
        if view in self.windows:
            self.windows[view].show()
            return
        if view == "settings":
            self.settings_open = True
            self._stop_hotkeys()
        title, width, height, minimum = WINDOWS[view]
        window = webview.create_window(
            title,
            GATE_UI_PATH if view == "gate" else UI_PATH,
            js_api=Bridge(self, view),
            width=width,
            height=height,
            min_size=minimum,
            resizable=view not in {"statistics"},
            background_color="#050c10" if view == "gate" else "#f2f5fa",
        )
        self.windows[view] = window
        window.events.closed += lambda: self._window_closed(view, window)

    def start_startup_check(self):
        self._begin_startup_check()

    def _begin_startup_check(self):
        with self.gate_lock:
            if self.closed or self.startup_active:
                return False
            self.startup_active = True
            self.gate_state = {"phase": "checking", "message": "正在连接官方更新服务…"}
        threading.Thread(
            target=self._run_startup_check, name="data-entry-startup-check", daemon=True,
        ).start()
        return True

    def _run_startup_check(self):
        try:
            recover_incomplete_update(core.BASE_DIR)
            policy = fetch_update_policy()
            failure = read_update_failure(core.BASE_DIR)
            minimum_version = policy["minimum_supported_version"]
            required = (
                not version_is_at_least(core._version_number, minimum_version)
                or failure is not None
            )
            official_version = None
            if not required:
                try:
                    official_version = fetch_official_version()
                except (OSError, RuntimeError, ValueError, httpx.HTTPError) as error:
                    print(
                        f"官方 version.py 检查失败，不影响已达标客户端启动：{error}",
                        file=sys.stderr,
                    )
            result = check_startup_update(
                core._version_number, minimum_version,
                force_repair=failure is not None,
                official_version=official_version,
            )
            if result.get("check_error"):
                print(
                    f"可选 GitHub Release 检查失败，不影响已达标客户端启动："
                    f"{result['check_error']}",
                    file=sys.stderr,
                )
            offer = result["offer"]
            if result["required"]:
                state = {
                    "phase": "required",
                    "message": failure or policy["message"],
                    "minimum_version": policy["minimum_supported_version"],
                    "version": offer["version"],
                }
            elif offer.get("available"):
                state = {
                    "phase": "optional",
                    "message": "发现可选稳定版更新；也可以稍后通过“文件 → 检查更新…”安装。",
                    "version": offer["version"],
                }
            else:
                state = {"phase": "ready", "message": "检查完成，正在打开客户端…"}
            with self.gate_lock:
                if not self.closed:
                    self.update_policy = policy
                    self.update_offer = offer if offer.get("available") else None
                    self.gate_state = state
        except (OSError, RuntimeError, ValueError, httpx.HTTPError) as error:
            message = str(error)
            with self.gate_lock:
                if not self.closed:
                    self.gate_state = {
                        "phase": "error",
                        "message": message or "无法验证官方更新策略，请检查网络后重试。",
                    }
            print(f"启动联网检查失败：{message}", file=sys.stderr)
        finally:
            with self.gate_lock:
                self.startup_active = False

    def _prepare_gate_update(self):
        offer = self.update_offer
        try:
            if self.closed:
                return
            start_update(
                core.BASE_DIR, offer, os.getpid(), list(sys.argv),
                cancelled=lambda: self.closed,
            )
            with self.gate_lock:
                if not self.closed:
                    self.gate_state = {
                        "phase": "restarting",
                        "message": "更新包已校验，正在关闭客户端并安装…",
                    }
        except (OSError, RuntimeError, ValueError, httpx.HTTPError) as error:
            message = str(error) or "更新准备失败，请重试。"
            with self.gate_lock:
                if not self.closed:
                    self.gate_state = {
                        "phase": "required" if self.gate_state.get("phase") == "installing-required"
                        else "optional",
                        "message": f"更新失败：{message}",
                        "minimum_version": (
                            self.update_policy["minimum_supported_version"]
                            if self.update_policy else None
                        ),
                        "version": offer.get("version") if offer else None,
                    }
            print(f"更新准备失败：{message}", file=sys.stderr)

    def _window_closed(self, view, window):
        with self.gate_lock:
            if self.windows.get(view) is not window:
                return
            del self.windows[view]
            if view == "main" or (view == "gate" and not self.startup_complete):
                self.closed = True
        if view == "settings":
            self.settings_open = False
            self.start_hotkeys()
        if view == "main" or (view == "gate" and not self.startup_complete):
            self.close()

    def close(self):
        with self.gate_lock:
            self.closed = True
            if getattr(self, "close_started", False):
                return
            self.close_started = True
            windows = list(self.windows.values())
            self.windows.clear()
        result_overlay.close()
        self.upload_queue.close(wait=False)
        for window in windows:
            try:
                window.destroy()
            except Exception as error:
                print(f"退出时关闭窗口失败：{error}", file=sys.stderr)

    def _request_gate_close(self):
        with self.gate_lock:
            if self.closed:
                return
            # Stop background results immediately, but leave time for the bridge
            # response before destroying WKWebView. This is not a delivery ACK.
            self.closed = True
            timer = threading.Timer(0.2, self.close)
            timer.daemon = True
            timer.start()

    def _destroy_entered_gate(self, window):
        with self.gate_lock:
            if self.closed or self.windows.get("gate") is not window:
                return
            del self.windows["gate"]
        try:
            window.destroy()
        except Exception as error:
            print(f"进入客户端后关闭门禁窗口失败：{error}", file=sys.stderr)

    def finish_close(self):
        self.close()
        with self.gate_lock:
            if getattr(self, "close_finished", False):
                return
        self._stop_hotkeys()
        drained = self.upload_queue.close(wait=True, timeout=5)
        if not drained:
            print("警告：退出时仍有上传任务未完成，已停止等待。")
        core.capture.sct.close()
        if drained:
            core.client.close()
        with self.gate_lock:
            self.close_finished = True

    def _load_style(self):
        try:
            settings = get_page_display_settings(
                core.client, core.get_page_display_api_url, core.login_token,
                **({"live_id": self.live_id} if getattr(self, "live_id", "") else {}),
            )
        except (httpx.HTTPError, ValueError):
            if getattr(self, "live_id", ""):
                raise
            self.page_style = DEFAULT_PAGE_STYLE
            self.page_is_active = False
            return
        self.page_is_active = settings["is_active"]
        try:
            styles = get_available_page_style_list(
                core.client, core.get_page_style_list_api_url,
            )
            self.available_styles = styles
            self.page_style = select_available_page_style(settings["page_style"], styles)
        except (httpx.HTTPError, ValueError):
            self.page_style = DEFAULT_PAGE_STYLE

    def _load_captain_profile(self):
        try:
            login_info = get_login_info(core.login_token, client=core.client)
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            login_info = None
        self.captain_profile = _captain_profile(login_info)

    def bootstrap(self, view):
        if view == "gate":
            with self.gate_lock:
                data = dict(self.gate_state)
            data["current_version"] = core._version_number
        elif view == "main":
            self._load_style()
            self._load_captain_profile()
            data = self._main_state()
        elif view == "import":
            data = {}
        elif view == "settings":
            data = self._settings_state()
        elif view == "update":
            data = {"current_version": core._version_number}
        elif view == "page":
            data = self._page_state()
        elif view == "history":
            data = self._history_state()
        elif view == "statistics":
            data = self._statistics_state()
        else:
            data = {"image": self.preview_image}
        return {"view": view, "theme": self.page_style, "data": data}

    def _settings_state(self):
        with core.CONFIG_PATH.open(encoding="utf-8") as config_file:
            config = json.load(config_file)
        for key in ("hotkey_previous_user", "hotkey_next_user"):
            config.setdefault(key, getattr(core, key))
        config.setdefault("show_result_overlay", sys.platform == "win32")
        pool = get_page_pool_settings(
            core.client, core.get_pool_list_api_url, core.login_token,
        )
        selected_pool = select_initial_pool_name(
            str(config.get("pool_name", "")).strip(),
            pool["current_pool_name"], pool["pool_name_list"],
        )
        return {
            "config": config,
            "pool_names": pool["pool_name_list"],
            "current_pool": pool["current_pool_name"],
            "selected_pool": selected_pool,
            "monitors": core.capture.get_monitor_info(),
            "pool_message": "此设置仅改变客户端录入活动，不会切换默认直播活动。",
        }

    def _page_state(self):
        settings = get_page_display_settings(
            core.client, core.get_page_display_api_url, core.login_token,
            **({"live_id": self.live_id} if getattr(self, "live_id", "") else {}),
        )
        styles = get_available_page_style_list(core.client, core.get_page_style_list_api_url)
        self.available_styles = styles
        return {
            "settings": settings,
            "styles": styles,
            "activity": PAGE_ACTIVITY_ITEM,
            "display_items": PAGE_DISPLAY_ITEMS,
            "text_items": PAGE_TEXT_ITEMS,
            "live_id": getattr(self, "live_id", ""),
        }

    def _statistics_state(self):
        data = request_live_page(
            core.client, core.set_current_user_api_url, core.login_token, "get-live-list",
        )
        return {
            **data, "url": core.statistics_page_url, "live_id": self.live_id,
            "event_name": self.full_event_name, "pool_name": core.pool_name,
        }

    def _history_state(self):
        nickname = self.nickname if self.history_filter == "current" else self.history_nickname
        records = get_gacha_history(
            core.client, core.gacha_history_api_url, core.login_token,
            self.full_event_name, nickname=nickname,
        )
        self.history_records = {record.record_id: record for record in records}
        positions = {}
        rows = []
        for record in records:
            position = positions.get(record.nickname, 1)
            if record.is_revoked:
                label = "—"
            else:
                label = format_gacha_position(position, record.count)
                positions[record.nickname] = position + record.count
            rows.append({
                "id": record.record_id,
                "nickname": record.nickname,
                "count": record.count,
                "sequence": record.sequence_no,
                "position": label,
                "result": " ".join(record.character_list),
                "created_at": record.created_at.replace("T", " ")[:19],
                "revoked": record.is_revoked,
            })
        if nickname == self.nickname:
            self.gacha_index = positions.get(self.nickname, 1)
            self._emit_main()
        return {
            "rows": rows,
            "passengers": list(self.user_name_list),
            "filter": self.history_filter,
            "nickname": self.history_nickname,
            "current_nickname": self.nickname,
            "pending": self.history_pending,
            "history_status": self.history_status,
        }

    def _save_settings(self, values):
        required = ("event_name", "pool_name", "user_name_list_file")
        if any(not str(values.get(key, "")).strip() for key in required):
            raise ValueError("活动名称、卡池名称和乘客名单文件必须填写")
        compose_event_name(values["event_name"], values["pool_name"])
        monitor_id = int(values["target_monitor_id"])
        if not 0 <= monitor_id < len(core.capture.monitors):
            raise ValueError("显示器编号无效")
        show_overlay = values.get("show_result_overlay", sys.platform == "win32")
        if not isinstance(show_overlay, bool):
            raise ValueError("悬浮窗口显示设置必须为布尔值")
        if show_overlay and sys.platform != "win32":
            raise ValueError("识别结果悬浮窗口目前仅支持 Windows")
        hotkeys = {key: str(values.get(key, "")).strip() for key in HOTKEY_KEYS}
        active_hotkeys = [item for item in hotkeys.values() if item]
        if len(set(active_hotkeys)) != len(active_hotkeys):
            raise ValueError("快捷键不能重复")
        checked_listener = self._register_hotkeys(hotkeys)
        if checked_listener is not None:
            checked_listener.stop()
        replacement_names = None
        if values["user_name_list_file"] != core.user_name_list_file:
            path = core.BASE_DIR / values["user_name_list_file"]
            with path.open(encoding="utf-8-sig") as name_file:
                replacement_names = [line.strip() for line in name_file if line.strip()]
            if not replacement_names:
                raise ValueError("新的乘客名单中没有乘客名字")
        with core.CONFIG_PATH.open(encoding="utf-8") as config_file:
            updated = json.load(config_file)
        updated.update({**values, "target_monitor_id": monitor_id, **hotkeys})
        temporary = core.CONFIG_PATH.with_suffix(".json.tmp")
        with temporary.open("w", encoding="utf-8") as config_file:
            json.dump(updated, config_file, ensure_ascii=False, indent=4)
            config_file.write("\n")
        temporary.replace(core.CONFIG_PATH)
        core.config.clear()
        core.config.update(updated)
        core.event_name = values["event_name"]
        core.pool_name = values["pool_name"]
        self.last_synced_user = None
        core.target_monitor_id = monitor_id
        result_overlay.configure(show_overlay, core.capture.monitors[monitor_id])
        core.user_name_list_file = values["user_name_list_file"]
        for key, value in hotkeys.items():
            setattr(core, key, value)
        if replacement_names is not None:
            self.user_name_list = replacement_names
            self._current_user(0)
        else:
            if not core.request_set_current_user(self.nickname):
                self.status = "运行配置已保存，当前乘客尚未同步；请重新选择当前乘客重试。"
                self._emit_main()
                raise RuntimeError(self.status)
            self.last_synced_user = self.nickname
        self._emit_main()
        return True

    def action(self, view, name, payload):
        if view == "gate":
            if name == "status":
                with self.gate_lock:
                    return dict(self.gate_state)
            if name == "retry":
                self._begin_startup_check()
                return {"started": True}
            if name == "exit":
                self._request_gate_close()
                return {"closing": True}
            if self.closed:
                raise ValueError("启动门禁已关闭")
            if name in {"continue", "enter"}:
                with self.gate_lock:
                    phase = self.gate_state.get("phase")
                    if phase not in {"ready", "optional"}:
                        raise ValueError("启动检查尚未允许进入客户端")
                    if self.closed or self.startup_complete:
                        raise ValueError("启动门禁已关闭或客户端已经启动")
                    self.gate_state = {"phase": "entering", "message": "正在打开客户端…"}
                return self._enter_client()
            if name == "install":
                with self.gate_lock:
                    if self.closed:
                        raise ValueError("启动门禁已关闭")
                    phase = self.gate_state.get("phase")
                    if phase not in {"required", "optional"} or not self.update_offer:
                        raise ValueError("当前没有可验证的更新目标")
                    if phase == "required" and payload.get("confirmed") is not True:
                        raise ValueError("强制更新必须经用户确认后才能开始")
                    self.gate_state["phase"] = (
                        "installing-required" if phase == "required" else "installing-optional"
                    )
                    self.gate_state["message"] = "正在下载并校验更新包…"
                threading.Thread(
                    target=self._prepare_gate_update, name="data-entry-update-prepare",
                    daemon=True,
                ).start()
                return {"started": True}
            if name == "handoff":
                with self.gate_lock:
                    if self.gate_state.get("phase") != "restarting":
                        raise ValueError("更新尚未准备完成")
                self._request_gate_close()
                return {"closing": True}
            raise ValueError("不支持的门禁操作")
        if not getattr(self, "startup_complete", True):
            raise RuntimeError("启动联网检查尚未通过，业务操作已锁定")
        if name == "logout" and view == "main":
            if self.logged_out:
                raise RuntimeError("已退出登录，请关闭客户端")
            if self.upload_queue.pending_count:
                raise RuntimeError("还有上传任务未完成，请稍后再退出登录")
            try:
                result = logout(core.login_token, client=core.client)
                revoked = isinstance(result, dict) and result.get("message") == "退出登录成功"
            except (httpx.HTTPError, ValueError):
                revoked = False
            # flight_session.logout clears the local credential even if the request fails.
            self.logged_out = True
            self._stop_hotkeys()
            result_overlay.close()
            self.upload_queue.close(wait=False)
            return {"revoked": revoked}
        if self.logged_out and name != "close":
            raise RuntimeError("已退出登录，请关闭客户端")
        if name == "open":
            target = payload.get("view")
            if view != "main" or target not in WINDOWS or target == "main":
                raise ValueError("不支持的窗口")
            self.create_window(target)
            return None
        if name == "close":
            window = self.windows.get(view)
            if window is None:
                return None
            if view == "main" and self.logged_out:
                self.relogin_requested = payload.get("relogin") is True
            # pywebview must deliver this bridge call's response before Cocoa
            # tears down the WKWebView, or its JS result thread can hang.
            timer = threading.Timer(0.2, window.destroy)
            timer.daemon = True
            timer.start()
            return None
        if view == "update":
            if name == "check":
                self.update_offer = None
                self.update_offer = check_update(core.BASE_DIR, core._version_number)
                if self.update_offer.get("available") and getattr(self, "update_policy", None):
                    self.update_offer["minimum_version"] = (
                        self.update_policy["minimum_supported_version"]
                    )
                return {key: value for key, value in self.update_offer.items()
                        if key in {"available", "mode", "current_version", "version", "commit"}}
            if name == "install":
                if not self.update_offer or not self.update_offer["available"]:
                    raise ValueError("请先检查更新")
                if not getattr(self, "update_policy", None):
                    raise RuntimeError("尚未验证官方最低版本策略，不能安装更新")
                if self.update_offer.get("version") and not version_is_at_least(
                    self.update_offer["version"],
                    self.update_policy["minimum_supported_version"],
                ):
                    raise ValueError("更新目标低于官方最低支持版本")
                self.update_offer["minimum_version"] = (
                    self.update_policy["minimum_supported_version"]
                )
                if self.upload_queue.pending_count or self.predict_lock.locked():
                    raise RuntimeError("仍有上传或识别任务，请等待完成后再更新")
                start_update(core.BASE_DIR, self.update_offer, os.getpid(), list(sys.argv))
                self.update_offer = None
                timer = threading.Timer(0.3, self.windows["main"].destroy)
                timer.daemon = True
                timer.start()
                return {"restarting": True}
            raise ValueError("不支持的操作")

        if view == "main":
            if name == "overlay":
                enabled = payload.get("enabled")
                if not isinstance(enabled, bool):
                    raise ValueError("悬浮窗口显示设置必须为布尔值")
                if enabled and sys.platform != "win32":
                    raise ValueError("识别结果悬浮窗口目前仅支持 Windows")
                with core.CONFIG_PATH.open(encoding="utf-8") as config_file:
                    updated = json.load(config_file)
                updated["show_result_overlay"] = enabled
                temporary = core.CONFIG_PATH.with_suffix(".json.tmp")
                with temporary.open("w", encoding="utf-8") as config_file:
                    json.dump(updated, config_file, ensure_ascii=False, indent=4)
                    config_file.write("\n")
                temporary.replace(core.CONFIG_PATH)
                core.config["show_result_overlay"] = enabled
                result_overlay.configure(enabled, core.capture.monitors[core.target_monitor_id])
                self._emit_main()
            elif name == "on_air":
                enabled = payload.get("enabled")
                if not isinstance(enabled, bool):
                    raise ValueError("直播页面活跃刷新设置必须为布尔值")
                settings = get_page_display_settings(
                    core.client, core.get_page_display_api_url, core.login_token,
                    **({"live_id": self.live_id} if getattr(self, "live_id", "") else {}),
                )
                settings["is_active"] = enabled
                settings = set_page_display_settings(
                    core.client, core.set_page_display_api_url,
                    core.login_token, settings,
                    **({"live_id": self.live_id} if getattr(self, "live_id", "") else {}),
                )
                self.page_is_active = settings["is_active"]
                self._emit_main()
            elif name == "select":
                index = int(payload["index"])
                if not 0 <= index < len(self.user_name_list):
                    raise ValueError("乘客编号无效")
                self._current_user(index)
            elif name == "previous":
                if self.user_id > 0:
                    self._current_user(self.user_id - 1)
            elif name == "next":
                self._next_user()
            elif name == "insert":
                index = min(self.user_id + 1, len(self.user_name_list))
                self.user_name_list.insert(index, self._new_name())
                self._current_user(index)
            elif name == "rename":
                nickname = str(payload.get("nickname", "")).strip()
                if not nickname:
                    raise ValueError("乘客名字不能为空")
                self.nickname = nickname
                if 0 <= self.user_id < len(self.user_name_list):
                    self.user_name_list[self.user_id] = nickname
                if nickname != self.last_synced_user and core.request_set_current_user(nickname):
                    self.last_synced_user = nickname
                self._emit_main()
            elif name == "sync":
                nickname = str(payload.get("nickname", "")).strip()
                if nickname:
                    self.nickname = nickname
                    if nickname != self.last_synced_user and core.request_set_current_user(nickname):
                        self.last_synced_user = nickname
                    self._emit_main()
            elif name == "single":
                rarity = int(payload["rarity"])
                if rarity not in (3, 4, 5, 6):
                    raise ValueError("抽卡星级无效")
                self.enqueue_gacha_result(1, ["零一二三四五六"[rarity] + "星干员"])
            elif name == "ten":
                self._predict()
            elif name == "purple":
                self.enqueue_gacha_result(10, ["断罪者"] * 10)
            elif name == "undo":
                records = get_gacha_history(
                    core.client, core.gacha_history_api_url, core.login_token,
                    self.full_event_name, nickname=self.nickname,
                )
                record = next((item for item in reversed(records) if not item.is_revoked), None)
                if record is None:
                    raise ValueError(f"{self.nickname} 没有可撤销的抽卡记录")
                if int(payload.get("id", -1)) != record.record_id:
                    raise ValueError("最近记录已变化，请重新确认")
                self.upload_queue.revoke(self.full_event_name, record.record_id)
                self._set_status("撤销操作已加入队列")
            elif name == "undo_preview":
                records = get_gacha_history(
                    core.client, core.gacha_history_api_url, core.login_token,
                    self.full_event_name, nickname=self.nickname,
                )
                record = next((item for item in reversed(records) if not item.is_revoked), None)
                if record is None:
                    raise ValueError(f"{self.nickname} 没有可撤销的抽卡记录")
                return {"id": record.record_id, "nickname": record.nickname, "count": record.count}
            else:
                raise ValueError("不支持的操作")
            return self._main_state()
        if view == "import":
            if name == "open_file":
                paths = self.windows["import"].create_file_dialog(
                    webview.FileDialog.OPEN,
                    file_types=("名单文件 (*.csv;*.txt)", "所有文件 (*.*)"),
                )
                if not paths:
                    return None
                return pathlib.Path(paths[0]).read_text(encoding="utf-8-sig")
            if name == "confirm":
                text = payload.get("text")
                if not isinstance(text, str):
                    raise ValueError("乘客名单内容无效")
                names = [line.strip() for line in text.splitlines() if line.strip()]
                if not names:
                    raise ValueError("乘客名单中没有乘客姓名")
                self.user_name_list = names
                self._current_user(0)
                return True
            raise ValueError("不支持的操作")
        if view == "history":
            if name == "filter":
                mode = payload.get("mode")
                if mode not in {"current", "all", "passenger"}:
                    raise ValueError("记录范围无效")
                nickname = payload.get("nickname") if mode == "passenger" else None
                if mode == "passenger" and nickname not in self.user_name_list:
                    raise ValueError("乘客不在名单中")
                self.history_filter = mode
                self.history_nickname = nickname
            elif name in {"revoke", "restore", "move"}:
                if self.history_pending:
                    raise RuntimeError("上一条记录操作尚未完成")
                record_id = int(payload["id"])
                record = self.history_records.get(record_id)
                if record is None:
                    raise ValueError("记录已变化，请刷新后重试")
                self.history_pending = True
                self.history_status = "记录操作已加入队列…"
                try:
                    if name == "move":
                        self.upload_queue.move(
                            self.full_event_name, record_id, payload["direction"],
                        )
                    elif record.is_revoked == (name == "revoke"):
                        raise ValueError("记录状态已变化，请刷新后重试")
                    else:
                        (self.upload_queue.revoke if name == "revoke" else self.upload_queue.restore)(
                            self.full_event_name, record_id,
                        )
                except Exception:
                    self.history_pending = False
                    self.history_status = ""
                    raise
                return self._history_state()
            elif name != "refresh":
                raise ValueError("不支持的操作")
            return self._history_state()
        if view == "settings":
            if name == "monitors":
                core.capture.refresh_monitors()
                return core.capture.get_monitor_info()
            if name == "preview":
                monitor_id = int(payload["monitor_id"])
                image = core.capture.capture_monitor(monitor_id)
                image.thumbnail((960, 600))
                buffer = io.BytesIO()
                image.save(buffer, format="PNG")
                self.preview_image = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
                self.create_window("preview")
                return None
            if name == "save":
                return self._save_settings(payload)
        if view == "page" and name == "save":
            settings = set_page_display_settings(
                core.client, core.set_page_display_api_url,
                core.login_token, payload,
                **({"live_id": self.live_id} if getattr(self, "live_id", "") else {}),
            )
            self.page_style = settings["page_style"]
            self.page_is_active = settings["is_active"]
            for target in list(self.windows):
                self._emit(target, {"theme": self.page_style})
            self._emit_main()
            return settings
        if view == "statistics":
            if name == "refresh":
                return self._statistics_state()
            if name == "select":
                if "page" in self.windows:
                    raise RuntimeError("请先关闭直播页面设置窗口，再切换直播配置")
                live_id = payload.get("live_id")
                if not isinstance(live_id, str):
                    raise ValueError("直播配置 ID 无效")
                data = self._statistics_state()
                if live_id and live_id not in {row["live_id"] for row in data["live_list"]}:
                    raise ValueError("直播配置不存在或没有管理权限")
                settings = get_page_display_settings(
                    core.client, core.get_page_display_api_url, core.login_token,
                    **({"live_id": live_id} if live_id else {}),
                )
                with core.CONFIG_PATH.open(encoding="utf-8") as config_file:
                    config = json.load(config_file)
                config["live_id"] = live_id
                temporary = core.CONFIG_PATH.with_suffix(".json.tmp")
                with temporary.open("w", encoding="utf-8") as config_file:
                    json.dump(config, config_file, ensure_ascii=False, indent=4)
                    config_file.write("\n")
                temporary.replace(core.CONFIG_PATH)
                self.live_id = live_id
                core.config["live_id"] = live_id
                self.page_style = settings["page_style"]
                self.page_is_active = settings["is_active"]
                for target in list(self.windows):
                    self._emit(target, {"theme": self.page_style})
                self._emit_main()
                return self._statistics_state()
            actions = {"create": "create-live", "save": "set-live", "editors": "set-live-editor", "default": "set-default-live"}
            if name in actions:
                result = request_live_page(
                    core.client, core.set_current_user_api_url, core.login_token, actions[name],
                    live_id=payload.get("live_id", ""), payload=payload["values"],
                )
                try:
                    state = self._statistics_state()
                except (httpx.HTTPError, ValueError) as error:
                    raise RuntimeError(
                        f"直播配置操作已保存（ID：{result.get('live_id', '') or '默认活动'}），"
                        f"但刷新列表失败：{error}。请刷新列表，不要重复创建。"
                    ) from error
                return {"result": result, **state}
        raise ValueError("不支持的操作")

    def _enter_client(self):
        main_window = None
        try:
            nickname = self.nickname
            if nickname != self.last_synced_user:
                if not core.request_set_current_user(nickname):
                    raise RuntimeError(f"同步当前乘客“{nickname}”失败，请检查网络后重试")
                self.last_synced_user = nickname

            with self.gate_lock:
                if self.closed:
                    raise RuntimeError("启动门禁已关闭")
                if "main" in self.windows:
                    raise RuntimeError("主界面已存在，无法安全重试进入")
                self.create_window("main")
                main_window = self.windows.get("main")

            self.start_hotkeys(raise_on_error=True)

            with self.gate_lock:
                if self.closed:
                    raise RuntimeError("启动门禁已关闭")
                self.startup_complete = True
                self.gate_state = {"phase": "entered", "message": "客户端已启动"}

            gate_window = self.windows.get("gate")
            if gate_window is not None:
                timer = threading.Timer(0.3, lambda: self._destroy_entered_gate(gate_window))
                timer.daemon = True
                timer.start()
            return {"entered": True}
        except Exception as error:
            try:
                self._stop_hotkeys()
            except Exception as cleanup_error:
                print(f"启动失败后清理快捷键失败：{cleanup_error}", file=sys.stderr)
            with self.gate_lock:
                self.startup_complete = False
                if main_window is None:
                    main_window = self.windows.pop("main", None)
                elif self.windows.get("main") is main_window:
                    del self.windows["main"]
                else:
                    # close() already claimed this window for destruction.
                    main_window = None
                if not self.closed:
                    self.gate_state = {
                        "phase": "error",
                        "message": f"进入客户端失败：{error or '未知错误'}",
                    }
            if main_window is not None:
                try:
                    main_window.destroy()
                except Exception as cleanup_error:
                    print(f"启动失败后关闭主窗口失败：{cleanup_error}", file=sys.stderr)
            if self.closed:
                return {"failed": True, "error": str(error)}
            print(f"进入客户端失败：{error}", file=sys.stderr)
            return {"failed": True, "error": str(error)}


def main():
    if sys.platform == "win32":
        # Do not silently fall back to the obsolete MSHTML engine.
        gui = "edgechromium"
    else:
        gui = None
    app = WebViewApp()
    app.create_window("gate")
    app.start_startup_check()
    signal.signal(signal.SIGINT, lambda _signum, _frame: app.close())
    icon_name = "favicon.png" if sys.platform == "darwin" else "favicon.ico"
    try:
        webview.start(
            gui=gui,
            private_mode=True,
            icon=str(core.BASE_DIR / icon_name),
        )
    finally:
        app.finish_close()
    if app.relogin_requested:
        os.execv(sys.executable, [sys.executable, *sys.argv])


if __name__ == "__main__":
    main()
