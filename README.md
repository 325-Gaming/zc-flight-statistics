# Zc Flight Statistics

本仓库用于管理 Zc 航空抽卡统计的各个组件。

## 组件

### 抽卡数据录入客户端

**路径：** `client/data-entry`

Zc 航空抽卡数据录入客户端。程序会截取指定显示器，使用 TensorFlow 模型识别抽卡画面和干员，然后将结果提交至统计接口。

#### 功能

- 指定显示器截图，支持多显示器环境
- 识别单抽和十连画面
- 识别十连结果中的干员
- 通过图形界面选择乘客并记录抽卡次序
- 支持单抽、十连全局快捷键
- 将识别结果和截图提交至统计接口
- 启动时自动检查、校验并更新识别模型
- 通过 `.env` 保存本地认证信息

#### 目录结构

```text
client/data-entry/
├── main.py                 # 程序入口
├── utils.py                # 图像处理工具
├── config.json             # 普通运行配置
├── .env.example            # 环境变量示例
├── requirements.txt        # Python 依赖
├── operators.txt           # 干员名单
├── name.csv                # 乘客名单
├── favicon.ico             # 窗口图标
└── models/
    ├── image_type.keras    # 画面类型识别模型
    └── gacha10.keras       # 十连干员识别模型
```

`models` 目录会被 Git 保留，但其中的模型文件不会被提交。运行前需要通过其他渠道获取两个 `.keras` 文件并放入该目录。

客户端启动时也会从服务器获取模型清单。下载完成并通过文件大小和 SHA-256 校验后，才会替换本地模型；服务器临时不可用时会继续使用已有模型。首次运行且本地没有模型时，需要能够连接模型服务。

#### 安装

建议使用独立的 Python 虚拟环境。

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r client/data-entry/requirements.txt
```

Windows PowerShell 激活虚拟环境：

```powershell
.venv\Scripts\Activate.ps1
```

#### 配置认证信息

复制环境变量示例：

```bash
cp client/data-entry/.env.example client/data-entry/.env
```

编辑 `client/data-entry/.env` 并填入真实 token：

```dotenv
ZCFLIGHT_LOGIN_TOKEN=replace-with-your-token
```

`.env` 已被 Git 忽略。不要将真实 token 写入源码、`.env.example` 或提交历史。

#### 运行配置

编辑 `client/data-entry/config.json`：

| 配置项 | 作用 |
| --- | --- |
| `event_name` | 活动名称 |
| `target_monitor_id` | 需要截取的显示器编号 |
| `user_name_list_file` | 乘客名单文件，相对于 `client/data-entry` |
| `hotkey_gacha10` | 十连快捷键 |
| `hotkey_3x` | 三星单抽快捷键 |
| `hotkey_4x` | 四星单抽快捷键 |
| `hotkey_5x` | 五星单抽快捷键 |
| `hotkey_6x` | 六星单抽快捷键 |

程序启动时会在终端输出当前显示器列表。如果截取的屏幕不正确，请根据输出修改 `target_monitor_id`。编号 `0` 通常表示所有显示器的组合区域。

#### 启动

可以从仓库根目录直接启动：

```bash
python3 client/data-entry/main.py
```

启动后：

1. 确认终端输出的目标显示器正确。
2. 在界面中确认当前乘客。
3. 使用界面按钮或配置的全局快捷键录入抽卡结果。
4. 每位乘客结束后，点击“下一位乘客~”重置抽卡序号。

#### 系统权限

- macOS 首次运行时，需要为终端或 Python 授予“屏幕与系统录制”权限。
- 全局快捷键在某些系统上可能需要辅助功能权限或管理员权限。
- 程序会将乘客昵称、抽卡结果和截图发送至配置的统计服务，请确保参与者知情。

#### 常见问题

##### 提示缺少 `ZCFLIGHT_LOGIN_TOKEN`

确认 `client/data-entry/.env` 存在，且包含非空的 `ZCFLIGHT_LOGIN_TOKEN`。

##### 提示找不到模型

确认以下文件已放入 `client/data-entry/models/`：

```text
image_type.keras
gacha10.keras
```

##### 截图为空白或内容不正确

检查屏幕录制权限和 `target_monitor_id`。修改系统权限后，通常需要重启终端和程序。

##### 快捷键无效

检查快捷键是否被其他程序占用，并确认当前用户具有监听全局键盘事件的权限。

## TODO

- [ ] 美化客户端窗口界面

- [ ] 实现从服务器获取最新版本模型的服务端与客户端
