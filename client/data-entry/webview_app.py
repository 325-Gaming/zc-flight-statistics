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
from event_settings import compose_event_name
from flight_session import logout
from gacha_history import format_gacha_position, get_gacha_history
from gacha_upload import GachaMoveTask, GachaStateTask, GachaUploadQueue
from hotkeys import register_hotkeys
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
    get_pool_sync_message,
    select_initial_pool_name,
    set_current_pool,
)
from page_style_settings import (
    DEFAULT_PAGE_STYLE,
    get_available_page_style_list,
    select_available_page_style,
)


UI_PATH = str(core.BASE_DIR / "webview_ui/index.html")
WINDOWS = {
    "main": (f"{core._name} {core._version}", 920, 600, (860, 600)),
    "history": ("抽卡记录", 1000, 520, (760, 400)),
    "settings": ("设置", 780, 760, (700, 700)),
    "page": ("直播页面设置", 620, 760, (560, 650)),
    "statistics": ("查看统计", 760, 190, (640, 170)),
    "preview": ("显示器预览", 980, 670, (600, 400)),
}
HOTKEY_KEYS = (
    "hotkey_gacha10", "hotkey_3x", "hotkey_4x", "hotkey_5x", "hotkey_6x",
)


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
        self.logged_out = False
        self.relogin_requested = False
        self.settings_open = False
        self.hotkey_listener = None
        self.user_name_list = list(core.user_name_list)
        self.user_id = -1
        self.nickname = ""
        self.last_synced_user = None
        self.gacha_index = 1
        self.result = ""
        self.status = ""
        self.history_filter = "current"
        self.history_nickname = None
        self.history_records = {}
        self.history_pending = False
        self.history_status = ""
        self.preview_image = ""
        self.page_style = DEFAULT_PAGE_STYLE
        self.available_styles = (DEFAULT_PAGE_STYLE,)
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
        self._next_user()

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
                "result": self.result,
                "status": self.status,
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

    def start_hotkeys(self):
        if self.settings_open or self.closed:
            return
        try:
            self.hotkey_listener = self._register_hotkeys(
                {key: getattr(core, key) for key in HOTKEY_KEYS}
            )
        except (RuntimeError, ValueError) as error:
            self._set_status(f"全局快捷键不可用：{error}")

    def _stop_hotkeys(self):
        listener = self.hotkey_listener
        self.hotkey_listener = None
        if listener is not None:
            listener.stop()

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
            UI_PATH,
            js_api=Bridge(self, view),
            width=width,
            height=height,
            min_size=minimum,
            resizable=view not in {"statistics"},
            background_color="#f2f5fa",
        )
        self.windows[view] = window
        window.events.closed += lambda: self._window_closed(view, window)

    def _window_closed(self, view, window):
        if self.windows.get(view) is window:
            del self.windows[view]
        if view == "settings":
            self.settings_open = False
            self.start_hotkeys()
        if view == "main":
            self.close()

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.upload_queue.close(wait=False)
        for window in list(self.windows.values()):
            try:
                window.destroy()
            except Exception:
                pass

    def finish_close(self):
        self.close()
        self._stop_hotkeys()
        drained = self.upload_queue.close(wait=True, timeout=5)
        if not drained:
            print("警告：退出时仍有上传任务未完成，已停止等待。")
        core.capture.sct.close()
        if drained:
            core.client.close()

    def _load_style(self):
        try:
            settings = get_page_display_settings(
                core.client, core.get_page_display_api_url, core.login_token,
            )
            styles = get_available_page_style_list(
                core.client, core.get_page_style_list_api_url,
            )
            self.available_styles = styles
            self.page_style = select_available_page_style(settings["page_style"], styles)
        except (httpx.HTTPError, ValueError):
            self.page_style = DEFAULT_PAGE_STYLE

    def bootstrap(self, view):
        if view == "main":
            self._load_style()
            data = self._main_state()
        elif view == "settings":
            data = self._settings_state()
        elif view == "page":
            data = self._page_state()
        elif view == "history":
            data = self._history_state()
        elif view == "statistics":
            data = {"url": core.statistics_page_url}
        else:
            data = {"image": self.preview_image}
        return {"view": view, "theme": self.page_style, "data": data}

    def _settings_state(self):
        with core.CONFIG_PATH.open(encoding="utf-8") as config_file:
            config = json.load(config_file)
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
            "pool_message": get_pool_sync_message(
                str(config.get("pool_name", "")).strip(),
                pool["current_pool_name"], selected_pool, pool["pool_name_list"],
            ),
        }

    def _page_state(self):
        settings = get_page_display_settings(
            core.client, core.get_page_display_api_url, core.login_token,
        )
        styles = get_available_page_style_list(core.client, core.get_page_style_list_api_url)
        self.available_styles = styles
        return {
            "settings": settings,
            "styles": styles,
            "activity": PAGE_ACTIVITY_ITEM,
            "display_items": PAGE_DISPLAY_ITEMS,
            "text_items": PAGE_TEXT_ITEMS,
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
        previous_pool = core.pool_name
        try:
            set_current_pool(
                core.client, core.set_current_pool_api_url, core.login_token,
                values["pool_name"],
            )
            temporary.replace(core.CONFIG_PATH)
        except Exception:
            temporary.unlink(missing_ok=True)
            if previous_pool != values["pool_name"]:
                try:
                    set_current_pool(
                        core.client, core.set_current_pool_api_url,
                        core.login_token, previous_pool,
                    )
                except (httpx.HTTPError, ValueError):
                    pass
            raise
        core.config.clear()
        core.config.update(updated)
        core.event_name = values["event_name"]
        core.pool_name = values["pool_name"]
        core.target_monitor_id = monitor_id
        core.user_name_list_file = values["user_name_list_file"]
        for key, value in hotkeys.items():
            setattr(core, key, value)
        if replacement_names is not None:
            self.user_name_list = replacement_names
            self._current_user(0)
        self._emit_main()
        return True

    def action(self, view, name, payload):
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
        if view == "main":
            if name == "select":
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
            elif name == "import":
                paths = self.windows["main"].create_file_dialog(
                    webview.FileDialog.OPEN,
                    file_types=("名单文件 (*.csv;*.txt)", "所有文件 (*.*)"),
                )
                if paths:
                    with pathlib.Path(paths[0]).open(encoding="utf-8-sig") as name_file:
                        names = [line.strip() for line in name_file if line.strip()]
                    if not names:
                        raise ValueError("选择的文件中没有乘客姓名")
                    self.user_name_list = names
                    self._current_user(0)
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
            )
            self.page_style = settings["page_style"]
            for target in list(self.windows):
                self._emit(target, {"theme": self.page_style})
            return settings
        raise ValueError("不支持的操作")


def main():
    if sys.platform == "win32":
        # Do not silently fall back to the obsolete MSHTML engine.
        gui = "edgechromium"
    else:
        gui = None
    app = WebViewApp()
    app.create_window("main")
    app.start_hotkeys()
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
