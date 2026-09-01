# import tensorflow as tf
from tensorflow.keras import Sequential
from tensorflow.keras.models import load_model
from tensorflow.keras.layers import Softmax

import base64
import datetime
import httpx
import io
import json
import keyboard
import mss
import numpy as np
import os
import pathlib
import requests
import time

from PIL import Image
from dotenv import load_dotenv

from utils import expand_to_square, process_to_16_9

import tkinter as tk
from tkinter import ttk

_name = 'Zc航空抽卡统计'
_version = 'V0.2.0'
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
        self.root.geometry("600x800")
        self.root.iconbitmap(BASE_DIR / 'favicon.ico')
        self.event_name = event_name
        self.user_name_list = user_name_list
        self.user_id = -1
        self.gacha_index = 1

        # 设置窗口关闭事件处理
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # 创建组件
        # label_text = f"已经抽了{self.gacha_index - 1}抽"
        label_text = ""
        self.label = ttk.Label(self.root, text=label_text)
        self.label.pack(fill=tk.X, padx=20, pady=10)

        self.button_new_user = ttk.Button(self.root, text="下一位乘客~", command=self.new_user)
        self.button_new_user.pack(fill=tk.X, padx=20, pady=10)
        # self.button_new_user.place(x=10, y=25, width=200)
        self.label_user = ttk.Label(self.root, text=f"当前乘客：")
        self.label_user.pack(fill=tk.X, padx=20, pady=10)
        self.entry_nickname = ttk.Entry(self.root)
        self.entry_nickname.pack(fill=tk.X, padx=20, pady=10)
        # self.entry_nickname.place(x=10, y=60, width=200)


        self.button_3 = ttk.Button(self.root, text=f"单抽三星（快捷键 {hotkey_3x}）", command=gacha_3x)
        self.button_3.pack(fill=tk.X, padx=20, pady=10)
        # self.button_3.place(x=10, y=125, width=280)

        self.button_4 = ttk.Button(self.root, text=f"单抽四星（快捷键 {hotkey_4x}）", command=gacha_4x)
        self.button_4.pack(fill=tk.X, padx=20, pady=10)
        # self.button_4.place(x=10, y=225, width=280)

        self.button_5 = ttk.Button(self.root, text=f"单抽五星（快捷键 {hotkey_5x}）", command=gacha_5x)
        self.button_5.pack(fill=tk.X, padx=20, pady=10)
        # self.button_5.place(x=10, y=325, width=280)

        self.button_6 = ttk.Button(self.root, text=f"单抽六星（快捷键 {hotkey_6x}）", command=gacha_6x)
        self.button_6.pack(fill=tk.X, padx=20, pady=10)
        # self.button_6.place(x=10, y=425, width=280)
        # self.entry_6x_name = ttk.Entry(self.root)
        # self.entry_6x_name.pack(pady=10)
        # self.entry_6x_name.place(x=10, y=390, width=200)

        self.button_10_purple = ttk.Button(self.root, text="紫光转彩", command=self.purple_to_golden)
        self.button_10_purple.pack(fill=tk.X, padx=20, pady=10)
        # self.button_10_purple.place(x=500, y=125, width=280)

        self.button_10 = ttk.Button(self.root, text=f"十连（快捷键 {hotkey_gacha10}）", command=capture_and_predict)
        self.button_10.pack(fill=tk.X, padx=20, pady=10)
        # self.button_10.place(x=500, y=325, width=280)

        # self.entry.pack(pady=10)

        self.new_user()


    def new_user(self):
        self.user_id += 1
        self.gacha_index = 1
        self.entry_nickname.delete(0, tk.END)
        current_user_name = self.user_name_list[self.user_id] if self.user_id < len(self.user_name_list) else f'乘客{self.user_id + 1}'
        self.entry_nickname.insert(0, current_user_name)

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
        print("正在关闭程序...")
        capture.sct.close()
        self.root.destroy()


# 使用示例
if __name__ == "__main__":
    print('当前显示器信息：')
    for monitor_info in capture.get_monitor_info():
        print(monitor_info)
    print('将截取显示器 {}'.format(target_monitor_id))

    print('正在启动程序本体')
    app = SimpleApp(event_name, user_name_list)

    keyboard.add_hotkey(hotkey_gacha10, lambda: capture_and_predict())
    keyboard.add_hotkey(hotkey_3x, lambda: gacha_3x())
    keyboard.add_hotkey(hotkey_4x, lambda: gacha_4x())
    keyboard.add_hotkey(hotkey_5x, lambda: gacha_5x())
    keyboard.add_hotkey(hotkey_6x, lambda: gacha_6x())
    print('已绑定快捷键： 十连 [{}]'.format(hotkey_gacha10))
    print('已绑定快捷键： 单抽三星 [{}]'.format(hotkey_3x))
    print('已绑定快捷键： 单抽四星 [{}]'.format(hotkey_4x))
    print('已绑定快捷键： 单抽五星 [{}]'.format(hotkey_5x))
    print('已绑定快捷键： 单抽六星 [{}]'.format(hotkey_6x))
    app.run()
