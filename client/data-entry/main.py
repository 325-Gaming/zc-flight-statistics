# import tensorflow as tf
from tensorflow.keras import Sequential
from tensorflow.keras.models import load_model
from tensorflow.keras.layers import Softmax

import base64
import datetime
import httpx
import io
import json
import mss
import numpy as np
import os
import pathlib
import requests
import signal
import time

from PIL import Image
from dotenv import load_dotenv

from model_updater import ensure_latest_models
from utils import expand_to_square, process_to_16_9

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from hotkeys import register_hotkeys

_name = 'Zc航空抽卡统计'
_version = 'V0.2.0'
_version_number = _version.lstrip('Vv')
print('{} {} 启动！'.format(_name, _version))

BASE_DIR = pathlib.Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env')

login_token = os.getenv('ZCFLIGHT_LOGIN_TOKEN')
if not login_token:
    raise RuntimeError(
        '缺少 ZCFLIGHT_LOGIN_TOKEN，请复制 .env.example 为 .env 并填入 token'
    )

with open(BASE_DIR / 'config.json', 'r', encoding='utf-8') as config_file:
    config = json.load(config_file)
target_monitor_id = int(config['target_monitor_id'])
event_name = config['event_name']
user_name_list_file = config['user_name_list_file']
hotkey_gacha10 = config['hotkey_gacha10']
hotkey_3x = config['hotkey_3x']
hotkey_4x = config['hotkey_4x']
hotkey_5x = config['hotkey_5x']
hotkey_6x = config['hotkey_6x']

print('当前活动 {}'.format(event_name))



model_image_type_path = BASE_DIR / 'models/image_type.keras'
model_gacha10_path = BASE_DIR / 'models/gacha10.keras'

submit_gacha_log_api_url = 'https://yubo.run/api/gachalog_zc/submit'
model_manifest_api_url = os.getenv(
    'ZCFLIGHT_MODEL_MANIFEST_URL',
    'https://yubo.run/api/gachalog_zc/models/manifest',
)
# submit_gacha_log_api_url = 'http://localhost:11325/gachalog/submit'

zcjpg = 'iVBORw0KGgoAAAANSUhEUgAAABUAAAAUCAIAAADtKeFkAAAEN0lEQVR4nC2TSW/bRgCFZyMpbiIpS7ZpLXZsJ0rdIgHaoAaaBAkQBG0PPRQ99Np/2FOLFggKpLcCadwli1dZsmTLErVxEckhhzOFg373d3gf3oMIISGEruvVanU+n6dpyrmQZcWyyjImSZokaWpYZVXXpiMP5vn+veazz9qLiVeVOEtmRAghy7JhGOPxOMsy+IFSSSZYJImvlkqOXV1bW1+GETf0RRi8fHW0COjuqpNq4PXpnEAIDcMIw5BSCiEEQihE2rDtWw13d6dlmeaKU3HX3dGw//OvL37/e8SFeNMZYMG+++becnRBSqVSURT/hwFQEGzX154/2n+4/2Bzs8EyigSUCdq0cVl5dnTR617PVF13a/b9vbqJHyAIIaVUCCEAQBDev7Pzw/fffv3l052dBkECAAEwKoQAkLQazeePv8AQyowZggwi7OzuoaIosiwDAAjOP9nZfvb4UUTzw+7lcW+8CBlAGlH0uMD/nlz++MtLgaStZp0C+NOrwz/+uUyXISmKol6vM8awEF8/fZJmyZKy6TS8uhhuNZruWs20zLdHx68O/kISGU0m21stO05P+5eHXe+rT7eJZVntdhthrDH20d3bkiJtuA2eZOdnx974KqNhmuWT6ezh5/umbZ10zrrDayfNojSfhFH3fYdgjI0PZFOPURr58/NOr1atzSbjJA7VkhSFoYRRsAzfHJ8kNE1yhomiadrR6bvrTRvFcdLvDxSl5DbqCAgCAWDs4PWf09m01dpst+9uuPVWszmbTKajUdV2BOcFFyzP45T1gwwBAK+uhssoFnlRVjVDLUlQVAytXqvJiLjrN3BWSAC4tapCsG2alCae50lqCbsNghDyfb/b7UpubTqb5ZQqhKzYNsFEkRVdNzVNS8KwrGs3SxEgDsLzszPPGz+5d5dNlzf+0yQ573U1SZwMzB234diOqqs5zXRN8/2A5cyxzJKucoh6/avJZNLtdRzHWt3Z7XgRYYwBCD3PG2iKrcoSltqqipPEn89/e3FANJXzgobBx3t7Jd3wvEmnP/CjZcOxZ4o9bzQJAAAhxDkfjryKaXDGgvm8opXWV1fkEul0zhjn7Tu3s0Kcvj86Ou8NRiPA8XwW9IYeXtWgqupFUQghIBDrK/Ytd2PNMjZWK63mRtWpsGVBcxbQ5XA27vb6R53e2XgqBJIkQjRrfbt94w8AwIpCcB6E0VT3V+xynBUHbw99P0gimiY0LTJ7xaJZPg4ixjnGiAvB4mjaeUcAgAghLAQTBRMgiJeLMCQI9gcX747PMwEAABVTV3Vt5vtBnAAAueBQQFOTHMsgqqokSSIEvzlinkdxMvf9StnYqK6ZRPOjWEBQtspUsOvF4qYngBggWzdsXWOUElnGCKn0hrTgIlrGlyOv1XDLmrzlbGuyPosWndFwmiRhmkIAVVW1DFOFOM9ZIfh/4pV4mHe0FIoAAAAASUVORK5CYII='

client = httpx.Client(http2=True)

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
with open(BASE_DIR / 'operators.txt', 'r', encoding='utf-8') as f:
    for line in f.readlines():
        operator_name_list.append(line.strip())
for idx in range(len(operator_name_list)):
    opr = operator_name_list[idx]
    operator_id_to_name[idx] = opr
    operator_name_to_id[opr] = idx

user_name_list = []
with open(BASE_DIR / user_name_list_file, 'r', encoding='utf-8') as f:
    for line in f.readlines():
        user_name_list.append(line.strip())
print('从乘客名单中加载到{}位乘客'.format(len(user_name_list)))


def pil_to_base64(image, format='PNG'):
    """
    将PIL Image转换为base64字符串

    Args:
        image: PIL Image对象
        format: 图片格式，如'PNG', 'JPEG'等

    Returns:
        base64编码的字符串
    """
    # 创建字节流缓冲区
    buffer = io.BytesIO()

    # 将图像保存到缓冲区
    image.save(buffer, format=format)

    # 获取字节数据并编码为base64
    img_bytes = buffer.getvalue()
    base64_string = base64.b64encode(img_bytes).decode('utf-8')

    return base64_string

def request_submit_gacha_result(event_name, nickname, count, gacha_index, character_list, pil_image):
    t0 = time.time()
    headers = {"Content-Type": "application/json"}
    # with requests.Session() as session:
        # res = session.post(submit_gacha_log_api_url, headers=headers, json={
    res = client.post(submit_gacha_log_api_url, headers=headers, json={
            "login_token": login_token,
            "event_name": event_name,
            "nickname": nickname,
            "count": count,
            "gacha_index": gacha_index,
            "character_json": json.dumps(character_list, ensure_ascii=False),
            "image_b64": pil_to_base64(pil_image),
        })
    print('提交结果用时: {:.2f}s，服务器返回: {}'.format(time.time() - t0, res.text))



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
    image = capture.capture_monitor(target_monitor_id, is_save=False)
    image.thumbnail((im_w, im_h), Image.LANCZOS)
    request_submit_gacha_result(
        event_name=event_name,
        nickname=app.entry_nickname.get(),
        count=1,
        gacha_index=app.gacha_index,
        character_list=[character_name],
        pil_image=image,
    )
    app.gacha_index += 1


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
        request_submit_gacha_result(
            event_name=event_name,
            nickname=app.entry_nickname.get(),
            count=10,
            gacha_index=app.gacha_index,
            character_list=result,
            pil_image=image_16_9.resize((int(iw / 8), int(ih / 8))),
        )
        app.gacha_index += 10
        # return result


class SimpleApp:
    def __init__(self, event_name, user_name_list):
        self.root = tk.Tk()
        self.root.title(_name)
        self.root.geometry("920x560")
        self.root.minsize(860, 560)
        self._configure_light_theme()
        self.root.iconbitmap(BASE_DIR / 'favicon.ico')
        self.event_name = event_name
        self.user_name_list = list(user_name_list)
        self.user_id = -1
        self.gacha_index = 1
        self.hotkey_listener = None
        self.is_closing = False

        # 设置窗口关闭事件处理
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)
        self._create_passenger_sidebar()
        self._create_main_panel()

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

    def _create_passenger_sidebar(self):
        sidebar = ttk.Frame(self.root, padding=(16, 16, 12, 16))
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.rowconfigure(1, weight=1)
        sidebar.columnconfigure(0, weight=1)

        header = ttk.Frame(sidebar)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="乘客列表", font=("TkDefaultFont", 14, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        menu_button = ttk.Menubutton(header, text="…", width=3)
        menu_button.grid(row=0, column=1, sticky="e")
        passenger_menu = tk.Menu(
            menu_button,
            tearoff=False,
            background="#ffffff",
            foreground="#1f1f1f",
            activebackground="#d7e9fb",
            activeforeground="#1f1f1f",
        )
        passenger_menu.add_command(label="导入乘客名单…", command=self.import_passengers)
        menu_button.configure(menu=passenger_menu)

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

    def _create_main_panel(self):
        main = ttk.Frame(self.root, padding=(20, 16, 20, 20))
        main.grid(row=0, column=1, sticky="nsew")
        main.columnconfigure(0, weight=1)

        self.label = ttk.Label(main, text="")
        self.label.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        navigation = ttk.Frame(main)
        navigation.grid(row=1, column=0, sticky="ew", pady=(0, 16))
        navigation.columnconfigure((0, 1), weight=1, uniform="navigation")
        self.button_previous_user = ttk.Button(
            navigation, text="上一位乘客", command=self.previous_user
        )
        self.button_previous_user.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.button_new_user = ttk.Button(
            navigation, text="下一位乘客", command=self.new_user
        )
        self.button_new_user.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        ttk.Label(main, text="当前乘客：").grid(row=2, column=0, sticky="w")
        self.entry_nickname = ttk.Entry(main)
        self.entry_nickname.grid(row=3, column=0, sticky="ew", pady=(5, 18))

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
            text="紫光转彩",
            command=self.purple_to_golden,
            square=True,
        )
        self.button_10_purple.master.grid(row=0, column=0, padx=5)
        self.button_10 = self._create_action_button(
            ten_row,
            text="十连",
            command=capture_and_predict,
            shortcut=hotkey_gacha10,
            width=410,
        )
        self.button_10.master.grid(row=0, column=1, padx=5)

    def _create_action_button(
        self, parent, text, command, square=False, shortcut=None, width=None
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
            cursor="pointinghand",
            takefocus=True,
        )
        button.place(x=0, y=0, relwidth=1, relheight=1)

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
                height / 2,
                text=text,
                fill=colors["text"],
                font=("TkDefaultFont", 12),
                anchor=tk.CENTER,
            )
            if shortcut:
                button.create_text(
                    width / 2,
                    height - 16,
                    text=f"快捷键 {shortcut}",
                    fill=colors["text"],
                    font=("TkDefaultFont", 9),
                    anchor=tk.S,
                )

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

    def new_user(self):
        self.set_user(self.user_id + 1)

    def previous_user(self):
        if self.user_id > 0:
            self.set_user(self.user_id - 1)

    def run(self):
        self.root.mainloop()


    def purple_to_golden(self):
        image_data = base64.b64decode(zcjpg)
        image_buffer = io.BytesIO(image_data)
        request_submit_gacha_result(
            event_name=self.event_name,
            nickname=self.entry_nickname.get(),
            count=10,
            gacha_index=self.gacha_index,
            character_list=['断罪者' for i in range(10)],
            pil_image=Image.open(image_buffer),
        )
        self.gacha_index += 10

    def on_closing(self):
        """窗口关闭时的清理工作"""
        if self.is_closing:
            return
        self.is_closing = True
        print("正在关闭程序...")
        if self.hotkey_listener is not None:
            self.hotkey_listener.stop()
            self.hotkey_listener = None
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
        hotkey_listener = register_hotkeys(
            {
                hotkey_gacha10: capture_and_predict,
                hotkey_3x: gacha_3x,
                hotkey_4x: gacha_4x,
                hotkey_5x: gacha_5x,
                hotkey_6x: gacha_6x,
            },
            dispatch=lambda callback: app.root.after(0, callback),
        )
    except RuntimeError as error:
        hotkey_listener = None
        print(f'警告：{error}。仍可点击窗口中的按钮操作。')
    else:
        app.hotkey_listener = hotkey_listener
        print('已绑定快捷键： 十连 [{}]'.format(hotkey_gacha10))
        print('已绑定快捷键： 单抽三星 [{}]'.format(hotkey_3x))
        print('已绑定快捷键： 单抽四星 [{}]'.format(hotkey_4x))
        print('已绑定快捷键： 单抽五星 [{}]'.format(hotkey_5x))
        print('已绑定快捷键： 单抽六星 [{}]'.format(hotkey_6x))
    signal.signal(signal.SIGINT, lambda signum, frame: app.on_closing())
    app.run()
