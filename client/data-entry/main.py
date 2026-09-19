# import tensorflow as tf
from tensorflow.keras import Sequential
from tensorflow.keras.models import load_model
from tensorflow.keras.layers import Softmax

import datetime
import httpx
import json
import mss
from mss.exception import ScreenShotError
import numpy as np
import os
import pathlib
import queue
import signal
import sys
import threading
import time

from PIL import Image, ImageTk
from dotenv import load_dotenv

from gacha_history import format_gacha_position, get_gacha_history
from gacha_upload import (
    GachaMoveTask,
    GachaStateTask,
    GachaUploadQueue,
    GachaUploadTask,
)
from model_updater import ensure_latest_models
from utils import expand_to_square, process_to_16_9
from version import __version__

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from hotkeys import register_hotkeys
from page_display_settings import (
    PAGE_DISPLAY_ITEMS,
    POLL_INTERVAL_MAX_SECONDS,
    POLL_INTERVAL_MIN_SECONDS,
    get_page_display_settings,
    set_page_display_settings,
)
from page_style_settings import (
    DEFAULT_PAGE_STYLE,
    get_available_page_styles,
    select_available_page_style,
)

_name = 'Zc航空抽卡统计'
_version = f'V{__version__}'
_version_number = __version__
print('{} {} 启动！'.format(_name, _version))

BASE_DIR = pathlib.Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / 'config.json'
CONFIG_EXAMPLE_PATH = BASE_DIR / 'config.example.json'
ENV_PATH = BASE_DIR / '.env'
ENV_EXAMPLE_PATH = BASE_DIR / '.env.example'

env_was_created = False
if not ENV_PATH.exists():
    try:
        ENV_PATH.write_text(
            ENV_EXAMPLE_PATH.read_text(encoding='utf-8'),
            encoding='utf-8',
        )
        ENV_PATH.chmod(0o600)
        env_was_created = True
    except OSError as error:
        raise RuntimeError(f'无法根据环境变量模板创建 .env：{error}') from error

if not CONFIG_PATH.exists():
    try:
        CONFIG_PATH.write_text(
            CONFIG_EXAMPLE_PATH.read_text(encoding='utf-8'),
            encoding='utf-8',
        )
    except OSError as error:
        raise RuntimeError(f'无法根据配置模板创建 config.json：{error}') from error

load_dotenv(ENV_PATH)
login_token = os.getenv('ZCFLIGHT_LOGIN_TOKEN', '').strip()
if not login_token or login_token == 'replace-me':
    detail = (
        '已根据 .env.example 自动创建 .env，请填写真实 token 后重新启动'
        if env_was_created
        else '请在 .env 中填写真实 token'
    )
    raise RuntimeError(
        f'缺少有效的 ZCFLIGHT_LOGIN_TOKEN，{detail}'
    )

with open(CONFIG_PATH, 'r', encoding='utf-8') as config_file:
    config = json.load(config_file)
target_monitor_id = int(config['target_monitor_id'])
event_name = config['event_name']
user_name_list_file = config['user_name_list_file']
hotkey_gacha10 = config['hotkey_gacha10']
hotkey_3x = config['hotkey_3x']
hotkey_4x = config['hotkey_4x']
hotkey_5x = config['hotkey_5x']
hotkey_6x = config['hotkey_6x']

passenger_list_path = BASE_DIR / user_name_list_file
if user_name_list_file == 'name.csv' and not passenger_list_path.exists():
    passenger_list_example_path = BASE_DIR / 'name.example.csv'
    try:
        passenger_list_path.write_text(
            passenger_list_example_path.read_text(encoding='utf-8'),
            encoding='utf-8',
        )
    except OSError as error:
        raise RuntimeError(
            f'无法根据乘客名单模板创建 name.csv：{error}'
        ) from error

print('当前活动 {}'.format(event_name))



model_image_type_path = BASE_DIR / 'models/image_type.keras'
model_gacha10_path = BASE_DIR / 'models/gacha10.keras'

submit_gacha_log_api_url = 'https://yubo.run/api/gachalog-zc/submit'
set_current_user_api_url = os.getenv(
    'ZCFLIGHT_CURRENT_USER_URL',
    'https://yubo.run/api/gachalog-zc/set-current-user',
)
model_manifest_api_url = os.getenv(
    'ZCFLIGHT_MODEL_MANIFEST_URL',
    'https://yubo.run/api/gachalog-zc/get-model-manifest',
)
get_page_display_api_url = os.getenv(
    'ZCFLIGHT_GET_PAGE_DISPLAY_URL',
    'https://yubo.run/api/gachalog-zc/get-page-display',
)
set_page_display_api_url = os.getenv(
    'ZCFLIGHT_SET_PAGE_DISPLAY_URL',
    'https://yubo.run/api/gachalog-zc/set-page-display',
)
get_page_style_list_api_url = os.getenv(
    'ZCFLIGHT_GET_PAGE_STYLE_LIST_URL',
    'https://yubo.run/api/gachalog-zc/get-page-style-list',
)
gacha_history_api_url = os.getenv(
    'ZCFLIGHT_GACHA_HISTORY_URL',
    'https://yubo.run/api/gachalog-zc/history',
)
move_gacha_log_api_url = os.getenv(
    'ZCFLIGHT_MOVE_GACHA_URL',
    'https://yubo.run/api/gachalog-zc/move-record',
)
revoke_gacha_log_api_url = os.getenv(
    'ZCFLIGHT_REVOKE_GACHA_URL',
    'https://yubo.run/api/gachalog-zc/revoke',
)
restore_gacha_log_api_url = os.getenv(
    'ZCFLIGHT_RESTORE_GACHA_URL',
    'https://yubo.run/api/gachalog-zc/restore',
)
# submit_gacha_log_api_url = 'http://localhost:11325/gachalog/submit'


client = httpx.Client(http2=True, timeout=15.0)

class MultiMonitorCapture:
    def __init__(self):
        self.sct = mss.mss()
        self.monitors = self.sct.monitors

    def get_monitor_info(self):
        """获取显示器信息"""
        return [
            {
                'index': i,
                'description': '所有显示器组合区域' if i == 0 else f'显示器 {i}',
                'position': (monitor['left'], monitor['top']),
                'size': (monitor['width'], monitor['height']),
            }
            for i, monitor in enumerate(self.monitors)
        ]

    def refresh_monitors(self):
        """重新读取当前系统中的显示器。"""
        new_sct = mss.mss()
        old_sct = self.sct
        self.sct = new_sct
        self.monitors = new_sct.monitors
        old_sct.close()
        return self.get_monitor_info()

    def capture_monitor(self, monitor_id=1, is_save=False, save_dir="./screenshots"):
        t0 = time.time()
        """截取指定显示器"""
        if monitor_id < 0 or monitor_id >= len(self.monitors):
            raise ValueError(
                f"显示器编号 {monitor_id} 不存在，可用范围为 0-{len(self.monitors) - 1}"
            )

        # 创建保存目录
        if is_save:
            os.makedirs(save_dir, exist_ok=True)

        # 快捷键回调可能运行在后台线程，每次截图创建独立会话更安全。
        with mss.mss() as sct:
            screenshot = sct.grab(self.monitors[monitor_id])
        img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")

        # 生成文件名
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"monitor_{monitor_id}_{timestamp}.png"
        if is_save:
            save_path = os.path.join(save_dir, filename)

        # 保存
        # print('截图用时: {:.2f}s'.format(time.time() - t0))
        if is_save:
            img.save(save_path)
            print(f"截图已保存: {save_path}")
            return img, save_path
        print('截图用时: {:.2f}s'.format(time.time() - t0))
        return img

    def __del__(self):
        if hasattr(self, 'sct'):
            self.sct.close()

capture = MultiMonitorCapture()


def seperate_image_gacha10(image):
    image = image.convert('RGB')
    img_w, img_h = image.size
    # image_square = expand_to_square(image, (255, 255, 255))
    # x1, y1, x2, y2
    gacha_area = (int(img_w * (42 / 1920)), int(img_h * 0.2), int(img_w * ((1920 - 42) / 1920)), int(img_h * 0.8))
    gacha_splits = [(gacha_area[2] - gacha_area[0]) / 20 * (i * 2 + 1) for i in range(10)]
    crop_width = int(img_w * 180 / 1920)
    crop_height = crop_width * 2
    operator_image_list = []
    for i in range(10):
        img_opr = image.crop((
            gacha_area[0] + gacha_splits[i] - crop_width // 2,
            gacha_area[1],
            gacha_area[0] + gacha_splits[i] + crop_width // 2,
            gacha_area[1] + crop_height,
        )).resize((32, 64))
        operator_image_list.append(img_opr)
    return operator_image_list


im_w = 128
im_h = im_w


print('正在检查模型更新')
model_update_results = ensure_latest_models(
    manifest_url=model_manifest_api_url,
    models_dir=BASE_DIR / 'models',
    client_version=_version_number,
    login_token=login_token,
)
for result in model_update_results.values():
    print(f'模型 {result.name}: {result.version} ({result.status})')


# model_image_type = tf.keras.models.load_model(model_image_type_path)
# model_gacha10 = tf.keras.models.load_model(model_gacha10_path)
model_image_type = load_model(model_image_type_path)
model_gacha10 = load_model(model_gacha10_path)
print('load model', model_image_type_path)
print('load model', model_gacha10_path)
# probability_model_image_type = tf.keras.Sequential([model_image_type, tf.keras.layers.Softmax()])
# probability_model_gacha10 = tf.keras.Sequential([model_gacha10, tf.keras.layers.Softmax()])
probability_model_image_type = Sequential([model_image_type, Softmax()])
probability_model_gacha10 = Sequential([model_gacha10, Softmax()])

# Check its architecture
# model_image_type.summary()
# model_gacha10.summary()

type_id_name = [
    ['0', 'other'],
    ['1', 'gacha'],
    ['2', 'gacha10'],
]
type_id_to_name = {}
type_name_to_id = {}
for cls in type_id_name:
    type_id_to_name[cls[0]] = cls[1]
    type_id_to_name[int(cls[0])] = cls[1]
    type_name_to_id[cls[1]] = cls[0]

operator_name_list = []
operator_id_to_name = {}
operator_name_to_id = {}
with open(BASE_DIR / 'models/operators.txt', 'r', encoding='utf-8') as f:
    for line in f.readlines():
        operator_name = line.strip()
        if operator_name:
            operator_name_list.append(operator_name)
if len(operator_name_list) != len(set(operator_name_list)):
    raise RuntimeError('下载的干员类别表存在重复项')
if not operator_name_list:
    raise RuntimeError('下载的干员类别表不能为空')
for idx in range(len(operator_name_list)):
    opr = operator_name_list[idx]
    operator_id_to_name[idx] = opr
    operator_name_to_id[opr] = idx

user_name_list = []
with open(passenger_list_path, 'r', encoding='utf-8') as f:
    for line in f.readlines():
        user_name_list.append(line.strip())
print('从乘客名单中加载到{}位乘客'.format(len(user_name_list)))


def request_set_current_user(nickname):
    try:
        res = client.post(
            set_current_user_api_url,
            headers={"Authorization": f"Bearer {login_token}"},
            json={
                "nickname": nickname,
            },
        )
        res.raise_for_status()
    except httpx.HTTPError as error:
        print(f'更新服务器当前乘客失败: {error}')
        return False

    print(f'服务器当前乘客已更新为: {nickname}')
    return True



def gacha_3x():
    single_gacha(3)
def gacha_4x():
    single_gacha(4)
def gacha_5x():
    single_gacha(5)
def gacha_6x():
    single_gacha(6)
def single_gacha(x):
    if x in (3, 4, 5, 6):
        character_name = '零一二三四五六'[x] + '星干员'
        print(f'单抽{character_name}')
    # elif x == 6:
    #     character_name = str(app.entry_6x_name.get())
    else:
        return
    app.enqueue_gacha_result(
        count=1,
        character_list=[character_name],
    )


def capture_and_predict():
    t0 = time.time()
    image_origin = capture.capture_monitor(target_monitor_id, is_save=False)
    image_16_9 = process_to_16_9(image_origin)
    iw, ih = image_16_9.size
    # scale
    if iw >= im_w or ih >= im_h:
        image_scale = image_16_9.copy()
        image_scale.thumbnail((im_w, im_h), Image.LANCZOS)
    elif iw >= ih:
        image_scale = image_16_9.resize((im_w, int(im_w * ih / iw)))
    else:
        image_scale = image_16_9.resize((int(im_h * iw / ih), im_h))
    # square
    image_square = expand_to_square(image_scale, (255, 255, 255))
    # image_square.show()
    # 转换为numpy数组并添加到列表
    image_array = np.array(image_square)
    val_images = np.stack([image_array], axis=0)
    # print(f"最终数组形状: {val_images.shape}")

    predictions = probability_model_image_type.predict(val_images)
    # print(type_id_to_name[np.argmax(predictions[0])])
    # if type_id_to_name[np.argmax(predictions[0])] == 'other':
    if np.argmax(predictions[0]) == 0:
        print('既不单抽也不十连.jpg')
        return
    if np.argmax(predictions[0]) == 1:
        print('这是单抽.jpg')
    # gacha10 十连
    if np.argmax(predictions[0]) == 2:
        print('这是十连.jpg')
        operator_image_list = seperate_image_gacha10(image_16_9)
        val_images = np.empty([10, 64, 32, 3])
        for i in range(10):
            val_images[i] = operator_image_list[i]
        predictions_gacha10 = probability_model_gacha10.predict(val_images)
        print('截图及识别用时: {:.2f}s'.format(time.time() - t0))
        result = [operator_id_to_name[np.argmax(predictions_gacha10[i])] for i in range(10)]
        print(result)
        with open(BASE_DIR / 'output.txt', 'w', encoding='utf-8') as f:
            f.write(' '.join(result))
        text = ' '.join(result)
        app.label.config(text=text)
        app.enqueue_gacha_result(
            count=10,
            character_list=result,
        )
        # return result


class SimpleApp:
    def __init__(self, event_name, user_name_list):
        self.root = tk.Tk()
        self.root.title(f'{_name} {_version}')
        self.root.geometry("920x600")
        self.root.minsize(860, 600)
        self._configure_light_theme()
        if sys.platform == 'win32':
            self.root.iconbitmap(BASE_DIR / 'favicon.ico')
        else:
            # macOS uses iconphoto to set the application's Dock icon.
            with Image.open(BASE_DIR / 'favicon.ico') as icon_image:
                self._app_icon = ImageTk.PhotoImage(icon_image, master=self.root)
            self.root.iconphoto(True, self._app_icon)
        self.event_name = event_name
        self.user_name_list = list(user_name_list)
        self.user_id = -1
        self.gacha_index = 1
        self.hotkey_listener = None
        self.is_closing = False
        self.last_synced_user = None
        self.settings_window = None
        self.page_display_settings_window = None
        self.page_display_settings_load_id = 0
        self.history_window = None
        self.history_records = {}
        self.history_load_id = 0
        self.undo_request_in_progress = False
        self.background_results = queue.Queue()
        self.active_popup_menu = None
        self.upload_queue = GachaUploadQueue(
            client,
            submit_gacha_log_api_url,
            login_token,
            move_url=move_gacha_log_api_url,
            restore_url=restore_gacha_log_api_url,
            revoke_url=revoke_gacha_log_api_url,
            on_success=self._queue_task_succeeded,
            on_failure=self._queue_task_failed,
        )

        # 设置窗口关闭事件处理
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(1, weight=1)
        self._create_menu_bar()
        self._create_passenger_sidebar()
        self._create_main_panel()
        self.root.bind_all("<Control-z>", self.undo_last_gacha)
        self.root.bind_all("<Command-z>", self.undo_last_gacha)
        self.root.after(100, self._process_background_results)

        self.new_user()

    def _configure_light_theme(self):
        """固定使用浅色主题，不跟随系统明暗模式变化。"""
        self.root.configure(background="#f2f2f2")
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure(".", background="#f2f2f2", foreground="#1f1f1f")
        style.configure("TFrame", background="#f2f2f2")
        style.configure("TLabel", background="#f2f2f2", foreground="#1f1f1f")
        style.configure("TLabelframe", background="#f2f2f2")
        style.configure(
            "TLabelframe.Label", background="#f2f2f2", foreground="#1f1f1f"
        )
        style.configure(
            "TButton",
            background="#ffffff",
            foreground="#1f1f1f",
            bordercolor="#c8c8c8",
            lightcolor="#ffffff",
            darkcolor="#c8c8c8",
        )
        style.map(
            "TButton",
            background=[("pressed", "#e3e3e3"), ("active", "#f5f5f5")],
            foreground=[("disabled", "#8a8a8a")],
        )
        style.configure(
            "TEntry",
            fieldbackground="#ffffff",
            foreground="#1f1f1f",
            insertcolor="#1f1f1f",
        )

    def _create_menu_bar(self):
        menu_bar = ttk.Frame(self.root, padding=(8, 4))
        menu_bar.grid(row=0, column=0, columnspan=2, sticky="ew")

        if sys.platform == "darwin":
            self._create_popup_menu_button(
                menu_bar,
                "文件",
                (
                    ("导入乘客名单…", self.import_passengers),
                    ("设置…", self.open_settings),
                    None,
                    ("退出", self.on_closing),
                ),
            )
            self._create_popup_menu_button(
                menu_bar,
                "操作",
                (
                    ("撤销上一条", self.undo_last_gacha),
                    ("抽卡记录…", self.open_gacha_history),
                ),
            )
            self._create_popup_menu_button(
                menu_bar,
                "统计",
                (
                    ("直播页面设置…", self.open_page_display_settings),
                    None,
                    ("查看统计", lambda: None),
                ),
            )
            return

        file_button = ttk.Menubutton(menu_bar, text="文件")
        file_button.pack(side=tk.LEFT, padx=(0, 4))
        file_menu = self._create_menu(file_button)
        file_menu.add_command(label="导入乘客名单…", command=self.import_passengers)
        file_menu.add_command(label="设置…", command=self.open_settings)
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self.on_closing)
        file_button.configure(menu=file_menu)

        action_button = ttk.Menubutton(menu_bar, text="操作")
        action_button.pack(side=tk.LEFT, padx=(0, 4))
        action_menu = self._create_menu(action_button)
        action_menu.add_command(
            label="撤销上一条",
            accelerator="Ctrl+Z",
            command=self.undo_last_gacha,
        )
        action_menu.add_command(label="抽卡记录…", command=self.open_gacha_history)
        action_button.configure(menu=action_menu)

        statistics_button = ttk.Menubutton(menu_bar, text="统计")
        statistics_button.pack(side=tk.LEFT)
        statistics_menu = self._create_menu(statistics_button)
        statistics_menu.add_command(
            label="直播页面设置…", command=self.open_page_display_settings
        )
        statistics_menu.add_separator()
        statistics_menu.add_command(label="查看统计", command=lambda: None)
        statistics_button.configure(menu=statistics_menu)

    def _create_popup_menu_button(self, parent, text, items):
        button = ttk.Button(parent, text=text)
        button.pack(side=tk.LEFT, padx=(0, 4))
        button.configure(
            command=lambda: self._toggle_popup_menu(button, items)
        )
        return button

    def _toggle_popup_menu(self, button, items):
        if self.active_popup_menu is not None:
            is_same_menu = self.active_popup_menu.menu_button is button
            self._close_popup_menu()
            if is_same_menu:
                return

        popup = tk.Toplevel(self.root)
        popup.menu_button = button
        self.active_popup_menu = popup
        popup.overrideredirect(True)
        popup.transient(self.root)
        popup.configure(background="#c8c8c8")

        content = ttk.Frame(popup, padding=1)
        content.pack(fill=tk.BOTH, expand=True)
        for item in items:
            if item is None:
                ttk.Separator(content).pack(fill=tk.X, padx=4, pady=2)
                continue
            label, command = item
            ttk.Button(
                content,
                text=label,
                command=lambda action=command: self._run_popup_action(action),
            ).pack(fill=tk.X)

        popup.update_idletasks()
        popup.geometry(
            f"+{button.winfo_rootx()}+"
            f"{button.winfo_rooty() + button.winfo_height()}"
        )
        popup.bind("<Escape>", lambda _event: self._close_popup_menu())
        popup.bind(
            "<FocusOut>",
            lambda _event: self.root.after_idle(self._close_unfocused_popup_menu),
        )
        popup.focus_force()

    def _close_unfocused_popup_menu(self):
        popup = self.active_popup_menu
        if popup is None:
            return
        focused_widget = popup.focus_get()
        if focused_widget is None or not str(focused_widget).startswith(str(popup)):
            self._close_popup_menu()

    def _close_popup_menu(self):
        popup = self.active_popup_menu
        self.active_popup_menu = None
        if popup is not None and popup.winfo_exists():
            popup.destroy()

    def _run_popup_action(self, action):
        self._close_popup_menu()
        self.root.after_idle(action)

    def dispatch_hotkey(self, callback):
        if sys.platform == "darwin":
            self._close_popup_menu()
        self.root.after(0, callback)

    def _create_menu(self, parent):
        return tk.Menu(
            parent,
            tearoff=False,
            background="#ffffff",
            foreground="#1f1f1f",
            activebackground="#d7e9fb",
            activeforeground="#1f1f1f",
        )

    def _create_passenger_sidebar(self):
        sidebar = ttk.Frame(self.root, padding=(16, 16, 12, 16))
        sidebar.grid(row=1, column=0, sticky="nsew")
        sidebar.rowconfigure(1, weight=1)
        sidebar.columnconfigure(0, weight=1)

        ttk.Label(
            sidebar, text="乘客列表", font=("TkDefaultFont", 14, "bold")
        ).grid(row=0, column=0, sticky="w", pady=(0, 10))

        list_frame = ttk.Frame(sidebar)
        list_frame.grid(row=1, column=0, sticky="nsew")
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)
        self.passenger_listbox = tk.Listbox(
            list_frame,
            width=24,
            activestyle="none",
            exportselection=False,
            background="#ffffff",
            foreground="#1f1f1f",
            selectbackground="#a8cff5",
            selectforeground="#1f1f1f",
            highlightbackground="#c8c8c8",
            highlightcolor="#6aa9e9",
        )
        self.passenger_listbox.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(
            list_frame, orient=tk.VERTICAL, command=self.passenger_listbox.yview
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.passenger_listbox.configure(yscrollcommand=scrollbar.set)
        self.passenger_listbox.bind("<<ListboxSelect>>", self.select_passenger)
        self.refresh_passenger_list()

    def open_gacha_history(self):
        window = self.history_window
        if window is not None and window.winfo_exists():
            self._sync_history_current_passenger()
            window.lift()
            window.focus_force()
            return

        current_nickname = self.entry_nickname.get().strip()
        window = tk.Toplevel(self.root)
        self.history_window = window
        self.history_current_nickname = current_nickname
        window.title("抽卡记录")
        window.geometry("1000x520")
        window.minsize(760, 400)
        window.configure(background="#f2f2f2")
        window.transient(self.root)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)

        content = ttk.Frame(window, padding=16)
        content.grid(row=0, column=0, sticky="nsew")
        content.columnconfigure(0, weight=1)
        content.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(content)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(toolbar, text="查看范围：").pack(side=tk.LEFT)
        current_filter_label = f"当前乘客：{current_nickname}"
        self.history_all_filter_label = "全部乘客（当前活动）"
        self.history_filter_var = tk.StringVar(value=current_filter_label)
        self.history_filter_mode = "current"
        self.history_filter_nickname = current_nickname
        selector = ttk.Menubutton(
            toolbar,
            textvariable=self.history_filter_var,
            width=30,
        )
        selector.pack(side=tk.LEFT, padx=(0, 8))
        self.history_filter_selector = selector
        self.history_filter_menu = self._create_menu(selector)
        selector.configure(menu=self.history_filter_menu)
        self._rebuild_history_filter_menu()
        ttk.Button(
            toolbar,
            text="刷新",
            command=self.refresh_gacha_history,
        ).pack(side=tk.LEFT)

        table = ttk.Frame(content)
        table.grid(row=1, column=0, sticky="nsew")
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        columns = (
            "record_id",
            "nickname",
            "sequence_no",
            "position",
            "result",
            "created_at",
            "status",
        )
        self.history_tree = ttk.Treeview(
            table,
            columns=columns,
            show="headings",
            selectmode="browse",
        )
        headings = {
            "record_id": "记录 ID",
            "nickname": "乘客",
            "sequence_no": "记录序号",
            "position": "抽数",
            "result": "抽卡结果",
            "created_at": "上传时间",
            "status": "状态",
        }
        widths = {
            "record_id": 75,
            "nickname": 120,
            "sequence_no": 75,
            "position": 80,
            "result": 315,
            "created_at": 165,
            "status": 75,
        }
        for column in columns:
            self.history_tree.heading(column, text=headings[column])
            self.history_tree.column(
                column,
                width=widths[column],
                minwidth=60,
                stretch=column == "result",
            )
        self.history_tree.grid(row=0, column=0, sticky="nsew")
        self.history_tree.bind(
            "<<TreeviewSelect>>",
            self._update_history_action_buttons,
        )
        scrollbar = ttk.Scrollbar(
            table,
            orient=tk.VERTICAL,
            command=self.history_tree.yview,
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.history_tree.configure(yscrollcommand=scrollbar.set)

        footer = ttk.Frame(content)
        footer.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self.history_status_label = ttk.Label(footer, text="")
        self.history_status_label.grid(
            row=0,
            column=0,
            columnspan=7,
            sticky="w",
            pady=(0, 8),
        )
        ttk.Label(footer, text="将所选记录：").grid(
            row=1,
            column=0,
            sticky="w",
        )
        self.history_revoke_button = ttk.Button(
            footer,
            text="撤销",
            command=lambda: self.change_selected_history_state(True),
            state=tk.DISABLED,
        )
        self.history_revoke_button.grid(row=1, column=1, sticky="ew", padx=(8, 0))
        self.history_restore_button = ttk.Button(
            footer,
            text="恢复",
            command=lambda: self.change_selected_history_state(False),
            state=tk.DISABLED,
        )
        self.history_restore_button.grid(row=1, column=2, sticky="ew", padx=(8, 0))
        self.history_move_first_button = ttk.Button(
            footer,
            text="移至最前",
            command=lambda: self.move_selected_history_record("first"),
            state=tk.DISABLED,
        )
        self.history_move_first_button.grid(
            row=2,
            column=1,
            sticky="ew",
            padx=(8, 0),
            pady=(8, 0),
        )
        self.history_move_previous_button = ttk.Button(
            footer,
            text="与前一条交换位置",
            command=lambda: self.move_selected_history_record("previous"),
            state=tk.DISABLED,
        )
        self.history_move_previous_button.grid(
            row=2,
            column=2,
            sticky="ew",
            padx=(8, 0),
            pady=(8, 0),
        )
        self.history_move_next_button = ttk.Button(
            footer,
            text="与后一条交换位置",
            command=lambda: self.move_selected_history_record("next"),
            state=tk.DISABLED,
        )
        self.history_move_next_button.grid(
            row=2,
            column=3,
            sticky="ew",
            padx=(8, 0),
            pady=(8, 0),
        )
        self.history_move_last_button = ttk.Button(
            footer,
            text="移至最后",
            command=lambda: self.move_selected_history_record("last"),
            state=tk.DISABLED,
        )
        self.history_move_last_button.grid(
            row=2,
            column=4,
            sticky="ew",
            padx=(8, 0),
            pady=(8, 0),
        )
        footer.columnconfigure(5, weight=1)
        ttk.Button(
            footer,
            text="关闭",
            command=self.close_gacha_history,
        ).grid(row=2, column=6, padx=(8, 0), pady=(8, 0))

        window.protocol("WM_DELETE_WINDOW", self.close_gacha_history)
        self.refresh_gacha_history()

    def close_gacha_history(self):
        self.history_load_id += 1
        window = self.history_window
        self.history_window = None
        self.history_records = {}
        if window is not None and window.winfo_exists():
            window.destroy()

    def _select_history_filter(self, mode, nickname=None):
        self.history_filter_mode = mode
        if mode == "current":
            nickname = self.history_current_nickname
            label = f"当前乘客：{nickname}"
        elif mode == "all":
            nickname = None
            label = self.history_all_filter_label
        else:
            label = nickname
        self.history_filter_nickname = nickname
        self.history_filter_var.set(label)
        self.refresh_gacha_history()

    def _rebuild_history_filter_menu(self):
        menu = self.history_filter_menu
        menu.delete(0, tk.END)
        menu.add_command(
            label=f"当前乘客：{self.history_current_nickname}",
            command=lambda: self._select_history_filter("current"),
        )
        menu.add_command(
            label=self.history_all_filter_label,
            command=lambda: self._select_history_filter("all"),
        )
        menu.add_separator()
        for passenger_name in self.user_name_list:
            menu.add_command(
                label=passenger_name,
                command=lambda name=passenger_name: self._select_history_filter(
                    "passenger",
                    name,
                ),
            )

    def _sync_history_current_passenger(self):
        window = self.history_window
        if window is None or not window.winfo_exists():
            return
        self.history_current_nickname = self.entry_nickname.get().strip()
        self._rebuild_history_filter_menu()
        if self.history_filter_mode == "current":
            self.history_filter_nickname = self.history_current_nickname
            self.history_filter_var.set(
                f"当前乘客：{self.history_current_nickname}"
            )
            self.refresh_gacha_history()

    def _selected_history_nickname(self):
        return self.history_filter_nickname

    def refresh_gacha_history(self):
        window = self.history_window
        if window is None or not window.winfo_exists():
            return
        nickname = self._selected_history_nickname()
        self.history_load_id += 1
        load_id = self.history_load_id
        self.history_status_label.configure(text="正在读取抽卡记录…")
        self.history_revoke_button.configure(state=tk.DISABLED)
        self.history_restore_button.configure(state=tk.DISABLED)
        self.history_move_first_button.configure(state=tk.DISABLED)
        self.history_move_previous_button.configure(state=tk.DISABLED)
        self.history_move_next_button.configure(state=tk.DISABLED)
        self.history_move_last_button.configure(state=tk.DISABLED)
        threading.Thread(
            target=self._load_gacha_history,
            args=(load_id, nickname),
            name="gacha-history",
            daemon=True,
        ).start()

    def _load_gacha_history(self, load_id, nickname):
        try:
            records = get_gacha_history(
                client,
                gacha_history_api_url,
                login_token,
                self.event_name,
                nickname=nickname,
            )
        except (httpx.HTTPError, RuntimeError, ValueError) as request_error:
            records = None
        else:
            request_error = None
        self.background_results.put(
            ("history", load_id, nickname, records, request_error)
        )

    def _show_gacha_history_result(self, load_id, nickname, records, error):
        window = self.history_window
        if (
            load_id != self.history_load_id
            or window is None
            or not window.winfo_exists()
        ):
            return
        if error is not None:
            self.history_status_label.configure(text=f"读取失败：{error}")
            return

        self.history_records = {record.record_id: record for record in records}
        self.history_tree.delete(*self.history_tree.get_children())
        if nickname == self.entry_nickname.get().strip():
            self.gacha_index = 1 + sum(
                record.count for record in records if not record.is_revoked
            )
        positions = {}
        record_positions = {}
        for record in records:
            position = positions.get(record.nickname, 1)
            if record.is_revoked:
                record_positions[record.record_id] = "—"
            else:
                record_positions[record.record_id] = format_gacha_position(
                    position,
                    record.count,
                )
                positions[record.nickname] = position + record.count

        for record in records:
            created_at = record.created_at.replace("T", " ")[:19]
            self.history_tree.insert(
                "",
                tk.END,
                iid=str(record.record_id),
                values=(
                    record.record_id,
                    record.nickname,
                    record.sequence_no,
                    record_positions[record.record_id],
                    " ".join(record.character_list),
                    created_at,
                    "已撤销" if record.is_revoked else "有效",
                ),
            )
        if records:
            self.history_tree.see(str(records[-1].record_id))
        range_text = "全部乘客" if nickname is None else nickname
        self.history_status_label.configure(
            text=f"{range_text}：共 {len(records)} 条记录"
        )

    def _update_history_action_buttons(self, _event=None):
        selection = self.history_tree.selection()
        if not selection:
            self.history_revoke_button.configure(state=tk.DISABLED)
            self.history_restore_button.configure(state=tk.DISABLED)
            self.history_move_first_button.configure(state=tk.DISABLED)
            self.history_move_previous_button.configure(state=tk.DISABLED)
            self.history_move_next_button.configure(state=tk.DISABLED)
            self.history_move_last_button.configure(state=tk.DISABLED)
            return
        record = self.history_records.get(int(selection[0]))
        if record is None:
            return
        self.history_revoke_button.configure(
            state=tk.DISABLED if record.is_revoked else tk.NORMAL
        )
        self.history_restore_button.configure(
            state=tk.NORMAL if record.is_revoked else tk.DISABLED
        )
        sibling_records = sorted(
            (
                item
                for item in self.history_records.values()
                if item.nickname == record.nickname
            ),
            key=lambda item: item.sequence_no,
        )
        selected_index = next(
            index
            for index, item in enumerate(sibling_records)
            if item.record_id == record.record_id
        )
        has_previous = selected_index > 0
        has_next = selected_index < len(sibling_records) - 1
        self.history_move_first_button.configure(
            state=tk.NORMAL if has_previous else tk.DISABLED
        )
        self.history_move_previous_button.configure(
            state=tk.NORMAL if has_previous else tk.DISABLED
        )
        self.history_move_next_button.configure(
            state=tk.NORMAL if has_next else tk.DISABLED
        )
        self.history_move_last_button.configure(
            state=tk.NORMAL if has_next else tk.DISABLED
        )

    def change_selected_history_state(self, is_revoked):
        selection = self.history_tree.selection()
        if not selection:
            return
        record = self.history_records.get(int(selection[0]))
        if record is None or record.is_revoked == is_revoked:
            return
        if is_revoked and not messagebox.askyesno(
            "撤销抽卡记录",
            f"确定撤销 {record.nickname} 的这条 {record.count} 抽记录吗？",
            parent=self.history_window,
        ):
            return
        if is_revoked:
            self.upload_queue.revoke(self.event_name, record.record_id)
            action = "撤销"
        else:
            self.upload_queue.restore(self.event_name, record.record_id)
            action = "恢复"
        self.history_status_label.configure(text=f"{action}操作已加入队列…")
        self.history_revoke_button.configure(state=tk.DISABLED)
        self.history_restore_button.configure(state=tk.DISABLED)
        self.history_move_first_button.configure(state=tk.DISABLED)
        self.history_move_previous_button.configure(state=tk.DISABLED)
        self.history_move_next_button.configure(state=tk.DISABLED)
        self.history_move_last_button.configure(state=tk.DISABLED)

    def move_selected_history_record(self, action):
        selection = self.history_tree.selection()
        if not selection:
            return
        record = self.history_records.get(int(selection[0]))
        if record is None:
            return
        self.upload_queue.move(self.event_name, record.record_id, action)
        action_labels = {
            "first": "移至最前",
            "last": "移至最后",
            "previous": "与前一条交换位置",
            "next": "与后一条交换位置",
        }
        self.history_status_label.configure(
            text=f"{action_labels[action]}操作已加入队列…"
        )
        self.history_revoke_button.configure(state=tk.DISABLED)
        self.history_restore_button.configure(state=tk.DISABLED)
        self.history_move_first_button.configure(state=tk.DISABLED)
        self.history_move_previous_button.configure(state=tk.DISABLED)
        self.history_move_next_button.configure(state=tk.DISABLED)
        self.history_move_last_button.configure(state=tk.DISABLED)

    def undo_last_gacha(self, _event=None):
        if _event is not None:
            focused_widget = self.root.focus_get()
            if focused_widget is not None and focused_widget.winfo_class() in {
                "Entry",
                "Text",
                "TEntry",
            }:
                return None
        if self.undo_request_in_progress:
            return "break"
        nickname = self.entry_nickname.get().strip()
        if not nickname:
            messagebox.showwarning("无法撤销", "当前乘客昵称不能为空。")
            return "break"
        self.undo_request_in_progress = True
        threading.Thread(
            target=self._load_last_gacha_for_undo,
            args=(nickname,),
            name="gacha-undo",
            daemon=True,
        ).start()
        return "break"

    def _load_last_gacha_for_undo(self, nickname):
        try:
            records = get_gacha_history(
                client,
                gacha_history_api_url,
                login_token,
                self.event_name,
                nickname=nickname,
            )
        except (httpx.HTTPError, RuntimeError, ValueError) as request_error:
            record = None
        else:
            request_error = None
            record = next(
                (item for item in reversed(records) if not item.is_revoked),
                None,
            )
        self.background_results.put(
            ("undo", nickname, record, request_error)
        )

    def _process_background_results(self):
        while True:
            try:
                result = self.background_results.get_nowait()
            except queue.Empty:
                break
            result_type, *payload = result
            if result_type == "history":
                self._show_gacha_history_result(*payload)
            elif result_type == "undo":
                self._confirm_undo_last_gacha(*payload)
            elif result_type == "page_display_settings":
                self._show_page_display_settings_result(*payload)
            elif result_type == "page_display_settings_saved":
                self._show_page_display_settings_saved(*payload)
            elif result_type == "queue":
                self._after_queue_task_finished(*payload)
        if not self.is_closing:
            self.root.after(100, self._process_background_results)

    def _confirm_undo_last_gacha(self, nickname, record, error):
        self.undo_request_in_progress = False
        if nickname != self.entry_nickname.get().strip():
            return
        if error is not None:
            messagebox.showerror("撤销失败", f"读取抽卡记录失败：\n{error}")
            return
        if record is None:
            messagebox.showinfo("无法撤销", f"{nickname} 没有可撤销的抽卡记录。")
            return
        if not messagebox.askyesno(
            "撤销上一条抽卡记录",
            f"确定撤销 {nickname} 最近上传的 {record.count} 抽记录吗？",
        ):
            return
        self.upload_queue.revoke(self.event_name, record.record_id)

    def open_page_display_settings(self):
        window = self.page_display_settings_window
        if window is not None and window.winfo_exists():
            window.lift()
            window.focus_force()
            return

        window = tk.Toplevel(self.root)
        self.page_display_settings_window = window
        window.title("直播页面设置")
        window.resizable(False, False)
        window.configure(background="#f2f2f2")
        window.transient(self.root)

        content = ttk.Frame(window, padding=18)
        content.grid(row=0, column=0, sticky="nsew")
        ttk.Label(
            content,
            text="正在加载直播页面设置…",
        ).grid(row=0, column=0, sticky="w")
        window.protocol(
            "WM_DELETE_WINDOW",
            lambda: self._close_page_display_settings(window),
        )

        self.page_display_settings_load_id += 1
        load_id = self.page_display_settings_load_id
        threading.Thread(
            target=self._load_page_display_settings,
            args=(load_id,),
            name="page-display-settings",
            daemon=True,
        ).start()

    def _load_page_display_settings(self, load_id):
        request_error = None
        try:
            current_settings = get_page_display_settings(
                client,
                get_page_display_api_url,
                login_token,
            )
            available_page_styles = get_available_page_styles(
                client,
                get_page_style_list_api_url,
            )
        except (httpx.HTTPError, ValueError) as error:
            current_settings = None
            available_page_styles = None
            request_error = error
        self.background_results.put(
            (
                "page_display_settings",
                load_id,
                current_settings,
                available_page_styles,
                request_error,
            )
        )

    def _show_page_display_settings_result(
        self,
        load_id,
        current_settings,
        available_page_styles,
        error,
    ):
        window = self.page_display_settings_window
        if (
            load_id != self.page_display_settings_load_id
            or window is None
            or not window.winfo_exists()
        ):
            return
        if error is not None:
            self._close_page_display_settings(window)
            messagebox.showerror(
                "无法打开直播页面设置",
                f"从服务器读取直播页面设置失败：\n{error}",
                parent=self.root,
            )
            return

        configured_page_style = current_settings["page_style"]
        current_page_style = select_available_page_style(
            configured_page_style,
            available_page_styles,
        )
        unavailable_page_style_message = ""
        if current_page_style != configured_page_style:
            unavailable_page_style_message = (
                f"当前样式“{configured_page_style}”已不可用，"
                f"保存时将改用 {DEFAULT_PAGE_STYLE}。"
            )

        for child in window.winfo_children():
            child.destroy()

        content = ttk.Frame(window, padding=18)
        content.grid(row=0, column=0, sticky="nsew")
        ttk.Label(content, text="页面样式").grid(
            row=0,
            column=0,
            sticky="w",
            padx=(0, 12),
        )
        page_style_variable = tk.StringVar(value=current_page_style)
        ttk.Combobox(
            content,
            textvariable=page_style_variable,
            values=available_page_styles,
            state="readonly",
            width=24,
        ).grid(row=0, column=1, sticky="ew")
        ttk.Label(
            content,
            text="勾选表示显示，不勾选表示隐藏。",
        ).grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(16, 12),
        )

        variables = {}
        for row, (key, label) in enumerate(PAGE_DISPLAY_ITEMS, start=2):
            variable = tk.BooleanVar(value=current_settings[key])
            variables[key] = variable
            ttk.Checkbutton(
                content,
                text=label,
                variable=variable,
            ).grid(
                row=row,
                column=0,
                columnspan=2,
                sticky="w",
                padx=(
                    (24, 0)
                    if key in {
                        "is_bottom_info_left_visible",
                        "is_bottom_info_right_visible",
                    }
                    else 0
                ),
                pady=4,
            )

        poll_interval_row = len(PAGE_DISPLAY_ITEMS) + 2
        ttk.Label(content, text="数据轮询间隔（秒）").grid(
            row=poll_interval_row,
            column=0,
            sticky="w",
            pady=(12, 4),
        )
        poll_interval_variable = tk.StringVar(
            value=str(current_settings["poll_interval_seconds"])
        )
        ttk.Spinbox(
            content,
            textvariable=poll_interval_variable,
            from_=POLL_INTERVAL_MIN_SECONDS,
            to=POLL_INTERVAL_MAX_SECONDS,
            width=8,
        ).grid(
            row=poll_interval_row,
            column=1,
            sticky="w",
            pady=(12, 4),
        )

        status_label = ttk.Label(
            content,
            text=unavailable_page_style_message,
        )
        status_label.grid(
            row=poll_interval_row + 2,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(8, 0),
        )

        actions = ttk.Frame(content)
        actions.grid(
            row=poll_interval_row + 1,
            column=0,
            columnspan=2,
            sticky="e",
            pady=(16, 0),
        )
        cancel_button = ttk.Button(
            actions,
            text="取消",
            command=lambda: self._close_page_display_settings(window),
        )
        cancel_button.pack(side=tk.LEFT, padx=(0, 8))
        save_button = ttk.Button(
            actions,
            text="保存",
        )
        save_button.configure(
            command=lambda: self.save_page_display_settings(
                variables,
                page_style_variable,
                poll_interval_variable,
                save_button,
                cancel_button,
                status_label,
                window,
            )
        )
        save_button.pack(side=tk.LEFT)

    def save_page_display_settings(
        self,
        variables,
        page_style_variable,
        poll_interval_variable,
        save_button,
        cancel_button,
        status_label,
        window,
    ):
        try:
            poll_interval_seconds = int(poll_interval_variable.get())
        except ValueError:
            poll_interval_seconds = 0
        if not (
            POLL_INTERVAL_MIN_SECONDS
            <= poll_interval_seconds
            <= POLL_INTERVAL_MAX_SECONDS
        ):
            messagebox.showerror(
                "无法保存直播页面设置",
                "数据轮询间隔必须是 1 到 60 之间的整数。",
                parent=window,
            )
            return

        settings = {
            key: variable.get()
            for key, variable in variables.items()
        }
        settings["poll_interval_seconds"] = poll_interval_seconds
        settings["page_style"] = page_style_variable.get()
        save_button.configure(state=tk.DISABLED)
        cancel_button.configure(state=tk.DISABLED)
        window.protocol("WM_DELETE_WINDOW", lambda: None)
        status_label.configure(text="正在保存直播页面设置…")
        threading.Thread(
            target=self._save_page_display_settings,
            args=(
                settings,
                window,
                save_button,
                cancel_button,
                status_label,
            ),
            name="page-display-settings-save",
            daemon=True,
        ).start()

    def _save_page_display_settings(
        self,
        settings,
        window,
        save_button,
        cancel_button,
        status_label,
    ):
        request_error = None
        try:
            set_page_display_settings(
                client,
                set_page_display_api_url,
                login_token,
                settings,
            )
        except (httpx.HTTPError, ValueError) as error:
            request_error = error
        self.background_results.put(
            (
                "page_display_settings_saved",
                window,
                save_button,
                cancel_button,
                status_label,
                request_error,
            )
        )

    def _show_page_display_settings_saved(
        self,
        window,
        save_button,
        cancel_button,
        status_label,
        error,
    ):
        if not window.winfo_exists():
            return
        if error is not None:
            save_button.configure(state=tk.NORMAL)
            cancel_button.configure(state=tk.NORMAL)
            window.protocol(
                "WM_DELETE_WINDOW",
                lambda: self._close_page_display_settings(window),
            )
            status_label.configure(text="保存失败")
            messagebox.showerror(
                "保存失败",
                f"更新服务器直播页面设置失败：\n{error}",
                parent=window,
            )
            return

        self._close_page_display_settings(window)

    def _close_page_display_settings(self, window):
        if window.winfo_exists():
            window.destroy()
        if self.page_display_settings_window is window:
            self.page_display_settings_window = None

    def open_settings(self):
        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.lift()
            self.settings_window.focus_force()
            return

        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as config_file:
                current_config = json.load(config_file)
        except (OSError, json.JSONDecodeError) as error:
            messagebox.showerror("无法打开设置", f"读取 config.json 失败：\n{error}")
            return

        if self.hotkey_listener is not None:
            self.hotkey_listener.stop()
            self.hotkey_listener = None

        window = tk.Toplevel(self.root)
        self.settings_window = window
        window.title("设置")
        window.geometry("780x700")
        window.minsize(700, 640)
        window.configure(background="#f2f2f2")
        window.transient(self.root)
        window.columnconfigure(0, weight=1)

        settings = (
            ("event_name", "活动名称", "提交抽卡记录时使用的活动名称。"),
            (
                "target_monitor_id",
                "截图显示器编号",
                "执行识别时需要截取的显示器编号。",
            ),
            (
                "user_name_list_file",
                "乘客名单文件",
                "程序启动时读取的乘客名单文件，相对于程序目录。",
            ),
            ("hotkey_gacha10", "十连快捷键", "触发十连截图和识别，可留空。"),
            ("hotkey_3x", "三星快捷键", "提交一次三星单抽记录，可留空。"),
            ("hotkey_4x", "四星快捷键", "提交一次四星单抽记录，可留空。"),
            ("hotkey_5x", "五星快捷键", "提交一次五星单抽记录，可留空。"),
            ("hotkey_6x", "六星快捷键", "提交一次六星单抽记录，可留空。"),
        )
        content = ttk.Frame(window, padding=18)
        content.grid(row=0, column=0, sticky="nsew")
        content.columnconfigure(1, weight=1)
        entries = {}
        for index, (key, label, description) in enumerate(settings):
            row = index * 2
            ttk.Label(content, text=label).grid(
                row=row, column=0, sticky="w", padx=(0, 12), pady=6
            )
            if key == "target_monitor_id":
                monitor_row = ttk.Frame(content)
                monitor_row.grid(row=row, column=1, sticky="ew", pady=6)
                monitor_row.columnconfigure(0, weight=1)
                monitor_selector = ttk.Combobox(monitor_row, state="readonly")
                monitor_selector.grid(row=0, column=0, sticky="ew", padx=(0, 6))
                self.update_monitor_selector(
                    monitor_selector, current_config.get(key, 0)
                )
                ttk.Button(
                    monitor_row,
                    text="刷新列表",
                    command=lambda selector=monitor_selector: self.refresh_monitor_list(
                        selector, window
                    ),
                ).grid(row=0, column=1, padx=6)
                ttk.Button(
                    monitor_row,
                    text="显示预览",
                    command=lambda selector=monitor_selector: self.show_monitor_preview(
                        selector, window
                    ),
                ).grid(row=0, column=2, padx=(6, 0))
                entries[key] = monitor_selector
            elif key.startswith("hotkey_"):
                hotkey_row = ttk.Frame(content)
                hotkey_row.grid(row=row, column=1, sticky="ew", pady=6)
                hotkey_row.columnconfigure(0, weight=1)
                entry = ttk.Entry(hotkey_row)
                entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
                entry.insert(0, str(current_config.get(key, "")))
                ttk.Button(
                    hotkey_row,
                    text="移除",
                    command=lambda hotkey_entry=entry: hotkey_entry.delete(0, tk.END),
                ).grid(row=0, column=1)
                entries[key] = entry
            else:
                entry = ttk.Entry(content)
                entry.grid(row=row, column=1, sticky="ew", pady=6)
                entry.insert(0, str(current_config.get(key, "")))
                entries[key] = entry
            ttk.Label(content, text=description).grid(
                row=row + 1,
                column=1,
                sticky="w",
                pady=(0, 5),
            )

        ttk.Label(
            content,
            text=(
                "快捷键不区分大小写；Control/Ctrl、Cmd/Command 等写法等效。\n"
                "单个按键会被系统全局占用，建议使用带修饰键的组合键。\n"
                "设置窗口打开期间，全局快捷键无效；保存后立即生效。"
                "更换乘客名单会替换当前列表。"
            ),
            justify=tk.LEFT,
        ).grid(
            row=len(settings) * 2,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(12, 8),
        )
        actions = ttk.Frame(content)
        actions.grid(row=len(settings) * 2 + 1, column=0, columnspan=2, sticky="e")
        ttk.Button(
            actions,
            text="取消",
            command=lambda: self.close_settings(window),
        ).pack(
            side=tk.LEFT, padx=(0, 8)
        )
        ttk.Button(
            actions,
            text="保存",
            command=lambda: self.save_settings(entries, window),
        ).pack(side=tk.LEFT)
        window.protocol("WM_DELETE_WINDOW", lambda: self.close_settings(window))

    def close_settings(self, window):
        if self.hotkey_listener is None:
            self.hotkey_listener = self.restore_hotkey_listener(
                {
                    "hotkey_gacha10": hotkey_gacha10,
                    "hotkey_3x": hotkey_3x,
                    "hotkey_4x": hotkey_4x,
                    "hotkey_5x": hotkey_5x,
                    "hotkey_6x": hotkey_6x,
                }
            )
        self.settings_window = None
        window.destroy()

    def update_monitor_selector(self, selector, selected_monitor_id=None):
        monitor_info = capture.get_monitor_info()
        selector.monitor_ids = [monitor["index"] for monitor in monitor_info]
        selector["values"] = [
            (
                f'{monitor["index"]} — {monitor["description"]} · '
                f'{monitor["size"][0]}×{monitor["size"][1]} · '
                f'位置 {monitor["position"][0]}, {monitor["position"][1]}'
            )
            for monitor in monitor_info
        ]
        try:
            selected_index = selector.monitor_ids.index(int(selected_monitor_id))
        except (TypeError, ValueError):
            selected_index = 0 if selector.monitor_ids else -1
        if selected_index >= 0:
            selector.current(selected_index)
        else:
            selector.set("")

    def get_selected_monitor_id(self, selector):
        selected_index = selector.current()
        if selected_index < 0 or selected_index >= len(selector.monitor_ids):
            return None
        return selector.monitor_ids[selected_index]

    def refresh_monitor_list(self, selector, parent):
        selected_monitor_id = self.get_selected_monitor_id(selector)
        try:
            capture.refresh_monitors()
        except (OSError, ScreenShotError) as error:
            messagebox.showerror(
                "刷新失败", f"无法刷新显示器列表：\n{error}", parent=parent
            )
            return
        self.update_monitor_selector(selector, selected_monitor_id)

    def show_monitor_preview(self, selector, parent):
        monitor_id = self.get_selected_monitor_id(selector)
        if monitor_id is None:
            messagebox.showwarning("无法预览", "请先选择一个显示器。", parent=parent)
            return
        try:
            preview_image = capture.capture_monitor(monitor_id, is_save=False)
        except (OSError, ScreenShotError, ValueError) as error:
            messagebox.showerror(
                "预览失败", f"无法截取所选显示器：\n{error}", parent=parent
            )
            return

        preview_image.thumbnail((960, 600), Image.LANCZOS)
        preview_window = tk.Toplevel(parent)
        preview_window.title(f"显示器 {monitor_id} 预览")
        preview_window.configure(background="#f2f2f2")
        preview_photo = ImageTk.PhotoImage(preview_image)
        preview_label = ttk.Label(preview_window, image=preview_photo)
        preview_label.image = preview_photo
        preview_label.pack(padx=12, pady=12)
        preview_window.transient(parent)

    def save_settings(self, entries, window):
        global event_name
        global hotkey_3x
        global hotkey_4x
        global hotkey_5x
        global hotkey_6x
        global hotkey_gacha10
        global target_monitor_id
        global user_name_list_file

        values = {
            key: (
                self.get_selected_monitor_id(entry)
                if key == "target_monitor_id"
                else entry.get().strip()
            )
            for key, entry in entries.items()
        }
        required_keys = ("event_name", "target_monitor_id", "user_name_list_file")
        if any(values[key] is None or values[key] == "" for key in required_keys):
            messagebox.showwarning(
                "无法保存", "活动名称、显示器和乘客名单文件必须填写。", parent=window
            )
            return
        if not 0 <= values["target_monitor_id"] < len(capture.monitors):
            messagebox.showwarning(
                "无法保存",
                f"显示器编号应在 0 到 {len(capture.monitors) - 1} 之间。",
                parent=window,
            )
            return

        hotkey_keys = (
            "hotkey_gacha10",
            "hotkey_3x",
            "hotkey_4x",
            "hotkey_5x",
            "hotkey_6x",
        )
        new_hotkeys = {key: values[key] for key in hotkey_keys}
        active_hotkeys = [hotkey for hotkey in new_hotkeys.values() if hotkey]
        if len(set(active_hotkeys)) != len(active_hotkeys):
            messagebox.showwarning("无法保存", "快捷键不能重复。", parent=window)
            return

        new_user_name_list = None
        if values["user_name_list_file"] != user_name_list_file:
            passenger_list_path = BASE_DIR / values["user_name_list_file"]
            try:
                with open(passenger_list_path, "r", encoding="utf-8-sig") as list_file:
                    new_user_name_list = [
                        line.strip() for line in list_file if line.strip()
                    ]
            except (OSError, UnicodeError) as error:
                messagebox.showerror(
                    "无法保存", f"读取乘客名单失败：\n{error}", parent=window
                )
                return
            if not new_user_name_list:
                messagebox.showwarning(
                    "无法保存", "新的乘客名单中没有乘客名字。", parent=window
                )
                return
            if not messagebox.askyesno(
                "替换乘客名单",
                "更换乘客名单将替换当前列表，并切换到第一位乘客。是否继续？",
                parent=window,
            ):
                return

        try:
            new_listener = self.create_hotkey_listener(new_hotkeys)
        except (RuntimeError, ValueError) as error:
            messagebox.showerror(
                "无法保存", f"应用新快捷键失败：\n{error}", parent=window
            )
            return

        temporary_config_path = CONFIG_PATH.with_suffix(".json.tmp")
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as config_file:
                updated_config = json.load(config_file)
            updated_config.update(values)
            with open(temporary_config_path, "w", encoding="utf-8") as config_file:
                json.dump(updated_config, config_file, ensure_ascii=False, indent=4)
                config_file.write("\n")
            temporary_config_path.replace(CONFIG_PATH)
        except (OSError, json.JSONDecodeError) as error:
            if temporary_config_path.exists():
                temporary_config_path.unlink()
            if new_listener is not None:
                new_listener.stop()
            messagebox.showerror("保存失败", f"无法更新 config.json：\n{error}", parent=window)
            return

        event_name = values["event_name"]
        target_monitor_id = values["target_monitor_id"]
        user_name_list_file = values["user_name_list_file"]
        hotkey_gacha10 = new_hotkeys["hotkey_gacha10"]
        hotkey_3x = new_hotkeys["hotkey_3x"]
        hotkey_4x = new_hotkeys["hotkey_4x"]
        hotkey_5x = new_hotkeys["hotkey_5x"]
        hotkey_6x = new_hotkeys["hotkey_6x"]
        config.clear()
        config.update(values)
        self.event_name = event_name
        self.hotkey_listener = new_listener
        self.settings_window = None
        self.update_hotkey_labels(new_hotkeys)
        if new_user_name_list is not None:
            self.user_name_list = new_user_name_list
            self.user_id = -1
            self.refresh_passenger_list()
            self.new_user()

        window.destroy()

    def create_hotkey_listener(self, hotkeys):
        hotkey_bindings = (
            (hotkeys["hotkey_gacha10"], capture_and_predict),
            (hotkeys["hotkey_3x"], gacha_3x),
            (hotkeys["hotkey_4x"], gacha_4x),
            (hotkeys["hotkey_5x"], gacha_5x),
            (hotkeys["hotkey_6x"], gacha_6x),
        )
        active_bindings = [
            (hotkey, callback)
            for hotkey, callback in hotkey_bindings
            if hotkey
        ]
        active_hotkeys = [hotkey for hotkey, _callback in active_bindings]
        if len(set(active_hotkeys)) != len(active_hotkeys):
            raise ValueError("快捷键不能重复")
        if not active_bindings:
            return None
        return register_hotkeys(
            dict(active_bindings),
            dispatch=self.dispatch_hotkey,
            schedule=lambda callback, delay: self.root.after(delay, callback),
        )

    def restore_hotkey_listener(self, hotkeys):
        try:
            return self.create_hotkey_listener(hotkeys)
        except (RuntimeError, ValueError) as error:
            print(f"警告：恢复原快捷键失败：{error}")
            return None

    def update_hotkey_labels(self, hotkeys):
        self.button_3.set_shortcut(hotkeys["hotkey_3x"])
        self.button_4.set_shortcut(hotkeys["hotkey_4x"])
        self.button_5.set_shortcut(hotkeys["hotkey_5x"])
        self.button_6.set_shortcut(hotkeys["hotkey_6x"])
        self.button_10.set_shortcut(hotkeys["hotkey_gacha10"])

    def _create_main_panel(self):
        main = ttk.Frame(self.root, padding=(20, 16, 20, 20))
        main.grid(row=1, column=1, sticky="nsew")
        main.columnconfigure(0, weight=1)

        self.label = ttk.Label(main, text="")
        self.label.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        navigation = ttk.Frame(main)
        navigation.grid(row=1, column=0, sticky="ew", pady=(0, 16))
        navigation.columnconfigure((0, 1, 2), weight=1, uniform="navigation")
        self.button_previous_user = ttk.Button(
            navigation, text="上一位乘客", command=self.previous_user
        )
        self.button_previous_user.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.button_insert_user = ttk.Button(
            navigation, text="新乘客", command=self.insert_new_user
        )
        self.button_insert_user.grid(row=0, column=1, sticky="ew", padx=6)
        self.button_new_user = ttk.Button(
            navigation, text="下一位乘客", command=self.new_user
        )
        self.button_new_user.grid(row=0, column=2, sticky="ew", padx=(6, 0))

        ttk.Label(main, text="当前乘客：").grid(row=2, column=0, sticky="w")
        nickname_row = ttk.Frame(main)
        nickname_row.grid(row=3, column=0, sticky="ew", pady=(5, 18))
        nickname_row.columnconfigure(0, weight=1)
        self.entry_nickname = ttk.Entry(nickname_row)
        self.entry_nickname.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.entry_nickname.bind("<FocusOut>", self.sync_current_user)
        self.entry_nickname.bind("<Return>", self.sync_current_user)
        self.button_rename_user = ttk.Button(
            nickname_row, text="重命名", command=self.rename_current_user
        )
        self.button_rename_user.grid(row=0, column=1, padx=(6, 0))

        single_group = ttk.LabelFrame(main, text="单抽", padding=12)
        single_group.grid(row=4, column=0, sticky="ew", pady=(0, 16))
        single_group.columnconfigure(0, weight=1)
        single_row = ttk.Frame(single_group)
        single_row.grid(row=0, column=0)
        single_buttons = (
            ("三星", hotkey_3x, gacha_3x),
            ("四星", hotkey_4x, gacha_4x),
            ("五星", hotkey_5x, gacha_5x),
            ("六星", hotkey_6x, gacha_6x),
        )
        for column, (title, hotkey, command) in enumerate(single_buttons):
            button = self._create_action_button(
                single_row,
                text=title,
                command=command,
                square=True,
                shortcut=hotkey,
                title_font_size=36,
            )
            button.master.grid(row=0, column=column, padx=5)
            setattr(self, f"button_{column + 3}", button)

        ten_group = ttk.LabelFrame(main, text="十连", padding=12)
        ten_group.grid(row=5, column=0, sticky="ew")
        ten_group.columnconfigure(0, weight=1)
        ten_row = ttk.Frame(ten_group)
        ten_row.grid(row=0, column=0)
        self.button_10_purple = self._create_action_button(
            ten_row,
            text="紫光镀彩",
            command=self.purple_to_golden,
            square=True,
        )
        self.button_10_purple.master.grid(row=0, column=0, padx=5)
        self.button_10 = self._create_action_button(
            ten_row,
            text="十连",
            command=capture_and_predict,
            shortcut=hotkey_gacha10,
            title_font_size=36,
            width=410,
        )
        self.button_10.master.grid(row=0, column=1, padx=5)

    def _create_action_button(
        self,
        parent,
        text,
        command,
        square=False,
        shortcut=None,
        title_font_size=24,
        width=None,
    ):
        """创建尺寸可控、使用固定浅色配色的自绘按钮。"""
        button_width = 130 if square else (width or 1)
        holder = ttk.Frame(parent, width=button_width, height=130)
        holder.grid_propagate(False)
        surface_background = "#f2f2f2"
        colors = {
            "normal": "#ffffff",
            "hover": "#f5f5f5",
            "pressed": "#e3e3e3",
            "border": "#c8c8c8",
            "text": "#1f1f1f",
        }
        button = tk.Canvas(
            holder,
            background=surface_background,
            borderwidth=0,
            highlightthickness=0,
            takefocus=True,
        )
        button.place(x=0, y=0, relwidth=1, relheight=1)
        shortcut_value = shortcut

        def draw(state="normal"):
            button.delete("all")
            width = max(button.winfo_width(), 2)
            height = max(button.winfo_height(), 2)
            button.create_rectangle(
                1,
                1,
                width - 1,
                height - 1,
                fill=colors[state],
                outline=colors["border"],
                width=1,
            )
            button.create_text(
                width / 2,
                height * 0.42 if shortcut_value else height / 2,
                text=text,
                fill=colors["text"],
                font=("TkDefaultFont", title_font_size),
                anchor=tk.CENTER,
            )
            if shortcut_value:
                button.create_text(
                    width / 2,
                    height - 16,
                    text=f"快捷键 {shortcut_value}",
                    fill=colors["text"],
                    font=("TkDefaultFont", 9),
                    anchor=tk.S,
                )

        def set_shortcut(value):
            nonlocal shortcut_value
            shortcut_value = value
            draw()

        button.set_shortcut = set_shortcut
        button.bind("<Configure>", lambda _event: draw())
        button.bind("<Enter>", lambda _event: draw("hover"))
        button.bind("<Leave>", lambda _event: draw())
        button.bind("<ButtonPress-1>", lambda _event: draw("pressed"))
        button.bind("<ButtonRelease-1>", lambda _event: (draw("hover"), command()))
        button.bind("<Return>", lambda _event: command())
        button.bind("<space>", lambda _event: command())
        return button

    def refresh_passenger_list(self):
        self.passenger_listbox.delete(0, tk.END)
        for passenger_name in self.user_name_list:
            self.passenger_listbox.insert(tk.END, passenger_name)

    def import_passengers(self):
        file_path = filedialog.askopenfilename(
            title="导入乘客名单",
            filetypes=(("名单文件", "*.csv *.txt"), ("所有文件", "*.*")),
        )
        if not file_path:
            return
        try:
            with open(file_path, "r", encoding="utf-8-sig") as passenger_file:
                imported_names = [
                    line.strip() for line in passenger_file if line.strip()
                ]
        except (OSError, UnicodeError) as error:
            messagebox.showerror("导入失败", f"无法读取乘客名单：\n{error}")
            return
        if not imported_names:
            messagebox.showwarning("导入失败", "选择的文件中没有乘客姓名。")
            return
        self.user_name_list = imported_names
        self.user_id = -1
        self.refresh_passenger_list()
        self.new_user()

    def select_passenger(self, _event=None):
        selection = self.passenger_listbox.curselection()
        if selection:
            self.set_user(selection[0])

    def set_user(self, user_id):
        self.user_id = max(0, user_id)
        self.gacha_index = 1
        self.entry_nickname.delete(0, tk.END)
        current_user_name = (
            self.user_name_list[self.user_id]
            if self.user_id < len(self.user_name_list)
            else f"乘客{self.user_id + 1}"
        )
        self.entry_nickname.insert(0, current_user_name)
        self.passenger_listbox.selection_clear(0, tk.END)
        if self.user_id < len(self.user_name_list):
            self.passenger_listbox.selection_set(self.user_id)
            self.passenger_listbox.see(self.user_id)
        self.button_previous_user.configure(
            state=tk.DISABLED if self.user_id == 0 else tk.NORMAL
        )
        self.sync_current_user()
        self._sync_history_current_passenger()

    def sync_current_user(self, _event=None):
        current_user_name = self.entry_nickname.get().strip()
        if current_user_name and current_user_name != self.last_synced_user:
            if request_set_current_user(current_user_name):
                self.last_synced_user = current_user_name

    def rename_current_user(self):
        new_user_name = self.entry_nickname.get().strip()
        if not new_user_name:
            messagebox.showwarning("重命名失败", "乘客名字不能为空。")
            return
        if not 0 <= self.user_id < len(self.user_name_list):
            return
        self.user_name_list[self.user_id] = new_user_name
        self.passenger_listbox.delete(self.user_id)
        self.passenger_listbox.insert(self.user_id, new_user_name)
        self.passenger_listbox.selection_set(self.user_id)
        self.passenger_listbox.see(self.user_id)
        self.sync_current_user()
        self._sync_history_current_passenger()

    def new_user(self):
        next_user_id = self.user_id + 1
        if next_user_id >= len(self.user_name_list):
            self.user_name_list.append(self.generate_passenger_name())
            self.refresh_passenger_list()
        self.set_user(next_user_id)

    def insert_new_user(self):
        new_user_id = min(self.user_id + 1, len(self.user_name_list))
        self.user_name_list.insert(new_user_id, self.generate_passenger_name())
        self.refresh_passenger_list()
        self.set_user(new_user_id)

    def generate_passenger_name(self):
        passenger_number = len(self.user_name_list) + 1
        passenger_name = f"乘客{passenger_number}"
        while passenger_name in self.user_name_list:
            passenger_number += 1
            passenger_name = f"乘客{passenger_number}"
        return passenger_name

    def previous_user(self):
        if self.user_id > 0:
            self.set_user(self.user_id - 1)

    def run(self):
        self.root.after_idle(self._show_main_window_in_foreground)
        self.root.mainloop()

    def _show_main_window_in_foreground(self):
        if self.is_closing or not self.root.winfo_exists():
            return
        self.root.deiconify()
        self.root.lift()
        try:
            self.root.attributes("-topmost", True)
        except tk.TclError:
            pass
        self.root.focus_force()
        self.root.after(500, self._release_main_window_topmost)

    def _release_main_window_topmost(self):
        if self.is_closing or not self.root.winfo_exists():
            return
        try:
            self.root.attributes("-topmost", False)
        except tk.TclError:
            pass

    def enqueue_gacha_result(self, count, character_list):
        gacha_index = self.gacha_index
        self.upload_queue.submit(
            event_name=self.event_name,
            nickname=self.entry_nickname.get(),
            count=count,
            gacha_index=gacha_index,
            character_list=character_list,
        )
        self.gacha_index += count
        print(f'上传任务已加入队列: 第 {gacha_index} 抽，共 {count} 抽')

    def _queue_task_succeeded(self, task, response):
        if isinstance(task, GachaUploadTask):
            print(
                f'上传成功: 第 {task.gacha_index} 抽，共 {task.count} 抽，'
                f'服务器返回: {response.text}'
            )
        elif isinstance(task, GachaStateTask):
            action = '撤销' if task.is_revoked else '恢复'
            print(f'{action}成功: 记录 {task.record_id}，服务器返回: {response.text}')
        else:
            print(
                f'调整顺序成功: 记录 {task.record_id}，操作 {task.action}，'
                f'服务器返回: {response.text}'
            )
        self.background_results.put(("queue", task, None))

    def _queue_task_failed(self, task, error):
        if isinstance(task, GachaUploadTask):
            print(
                f'上传失败: 第 {task.gacha_index} 抽，共 {task.count} 抽，'
                f'错误: {error}'
            )
        elif isinstance(task, GachaStateTask):
            action = '撤销' if task.is_revoked else '恢复'
            print(f'{action}失败: 记录 {task.record_id}，错误: {error}')
        else:
            print(f'调整顺序失败: 记录 {task.record_id}，错误: {error}')
        self.background_results.put(("queue", task, error))

    def _after_queue_task_finished(self, task, error):
        if error is not None and isinstance(task, GachaStateTask):
            action = '撤销' if task.is_revoked else '恢复'
            messagebox.showerror(f'{action}失败', f'{action}抽卡记录失败：\n{error}')
        elif error is not None and isinstance(task, GachaMoveTask):
            messagebox.showerror("调整顺序失败", f"调整抽卡记录顺序失败：\n{error}")
        window = self.history_window
        if window is not None and window.winfo_exists():
            self.refresh_gacha_history()


    def purple_to_golden(self):
        self.enqueue_gacha_result(
            count=10,
            character_list=['断罪者' for i in range(10)],
        )

    def on_closing(self):
        """窗口关闭时的清理工作"""
        if self.is_closing:
            return
        self.is_closing = True
        print("正在关闭程序...")
        if self.hotkey_listener is not None:
            self.hotkey_listener.stop()
            self.hotkey_listener = None
        pending_count = self.upload_queue.pending_count
        if pending_count:
            print(f'正在等待 {pending_count} 个上传任务完成...')
        self.upload_queue.close(wait=True)
        capture.sct.close()
        client.close()
        self.root.destroy()


# 使用示例
if __name__ == "__main__":
    print('当前显示器信息：')
    for monitor_info in capture.get_monitor_info():
        print(monitor_info)
    print('将截取显示器 {}'.format(target_monitor_id))

    print('正在启动程序本体')
    app = SimpleApp(event_name, user_name_list)

    try:
        hotkey_listener = app.create_hotkey_listener(
            {
                "hotkey_gacha10": hotkey_gacha10,
                "hotkey_3x": hotkey_3x,
                "hotkey_4x": hotkey_4x,
                "hotkey_5x": hotkey_5x,
                "hotkey_6x": hotkey_6x,
            }
        )
    except (RuntimeError, ValueError) as error:
        hotkey_listener = None
        print(f'警告：{error}。仍可点击窗口中的按钮操作。')
    else:
        app.hotkey_listener = hotkey_listener
        configured_hotkeys = (
            ("十连", hotkey_gacha10),
            ("单抽三星", hotkey_3x),
            ("单抽四星", hotkey_4x),
            ("单抽五星", hotkey_5x),
            ("单抽六星", hotkey_6x),
        )
        for hotkey_name, hotkey in configured_hotkeys:
            if hotkey:
                print(f"已绑定快捷键： {hotkey_name} [{hotkey}]")
    signal.signal(signal.SIGINT, lambda signum, frame: app.on_closing())
    app.run()
