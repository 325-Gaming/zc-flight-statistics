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
- 支持新增、顺延和重命名乘客，并自动同步当前乘客
- 支持单抽、十连全局快捷键，且可按操作单独关闭
- 将识别结果和截图提交至统计接口
- 启动时自动检查、校验并更新识别模型
- 支持在运行时修改活动、显示器、乘客名单和快捷键
- 支持查看所选显示器的截图预览
- 通过 `.env` 保存本地认证信息

#### 目录结构

```text
CHANGELOG.md                     # 版本更新记录
client/data-entry/
├── main.py                      # 程序入口
├── version.py                   # 客户端版本号
├── hotkeys.py                   # 跨平台全局快捷键
├── model_updater.py             # 识别模型更新工具
├── utils.py                     # 图像处理工具
├── config.example.json          # 运行配置模板
├── name.example.csv             # 乘客名单模板
├── .env.example                 # 环境变量模板
├── requirements.txt             # Python 依赖
├── operators.txt                # 干员名单
├── test_model_updater.py        # 模型更新测试
├── favicon.ico                  # 窗口图标
└── models/
    ├── image_type.keras         # 画面类型识别模型
    ├── gacha10.keras            # 十连干员识别模型
    └── manifest.json            # 本地模型版本清单
```

`config.json`、`name.csv` 和 `.env` 属于本地用户配置，不会提交至 Git。程序首次启动时会根据对应模板自动创建这些文件。

`models` 目录会被 Git 保留，但其中的模型和本地版本清单不会提交。客户端启动时会从服务器获取模型清单；下载完成并通过文件大小和 SHA-256 校验后，才会替换本地模型。服务器临时不可用时会继续使用已有模型；首次运行且本地没有模型时，需要能够连接模型服务。

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

程序首次启动时会根据 `.env.example` 自动创建 `client/data-entry/.env`，随后因为登录令牌仍是占位值而提示用户完成配置。也可以在首次启动前手动复制模板：

```bash
cp client/data-entry/.env.example client/data-entry/.env
```

编辑 `client/data-entry/.env` 并填入真实 token：

```dotenv
ZCFLIGHT_LOGIN_TOKEN=replace-with-your-token
```

`.env` 已被 Git 忽略。不要将真实 token 写入源码、`.env.example` 或提交历史。

开发或自托管环境还可以在 `.env` 中覆盖以下接口地址：

```dotenv
ZCFLIGHT_MODEL_MANIFEST_URL=http://localhost:8000/api/gachalog_zc/models/manifest
ZCFLIGHT_CURRENT_USER_URL=http://localhost:8000/api/gachalog_zc/current_user
```

#### 运行配置

启动程序后，通过菜单栏的“文件 → 设置…”修改运行配置。设置保存后会立即生效，无需重启程序。

首次启动时，程序会根据 `config.example.json` 创建本地 `config.json`。需要时也可以直接编辑该文件：

| 配置项 | 作用 |
| --- | --- |
| `event_name` | 活动名称 |
| `target_monitor_id` | 需要截取的显示器编号 |
| `user_name_list_file` | 乘客名单文件，相对于 `client/data-entry` |
| `hotkey_gacha10` | 十连快捷键，可留空 |
| `hotkey_3x` | 三星单抽快捷键，可留空 |
| `hotkey_4x` | 四星单抽快捷键，可留空 |
| `hotkey_5x` | 五星单抽快捷键，可留空 |
| `hotkey_6x` | 六星单抽快捷键，可留空 |

切换、选择或导入名单后进入新的当前乘客时，客户端会自动将当前乘客信息
同步至统计服务，无需额外操作。

设置窗口会列出显示器的编号、分辨率和位置，并支持预览所选显示器。如果截取内容不正确，可以在预览后直接更换显示器。编号 `0` 通常表示所有显示器的组合区域。

#### 启动

可以从仓库根目录直接启动：

```bash
python3 client/data-entry/main.py
```

启动后：

1. 打开“文件 → 设置…”，选择目标显示器并查看预览。
2. 在界面中确认当前乘客。
3. 使用界面按钮或配置的全局快捷键录入抽卡结果。
4. 每位乘客结束后，点击“下一位乘客”重置抽卡序号；也可以使用“新乘客”和“重命名”维护名单。

#### 系统权限

- macOS 首次运行时，需要为终端或 Python 授予“屏幕与系统录制”权限。
- 全局快捷键在某些系统上可能需要辅助功能权限或管理员权限。
- 程序会将乘客昵称、抽卡结果和截图发送至配置的统计服务，请确保参与者知情。

#### 常见问题

##### 提示缺少 `ZCFLIGHT_LOGIN_TOKEN`

确认 `client/data-entry/.env` 存在，且包含非空的 `ZCFLIGHT_LOGIN_TOKEN`。

##### 提示找不到模型

客户端会在启动时自动下载模型。下载失败时，先检查网络连接以及 `ZCFLIGHT_MODEL_MANIFEST_URL` 是否正确。

如果模型服务暂时不可用，则需要确认 `client/data-entry/models/` 中已有以下文件：

```text
image_type.keras
gacha10.keras
```

##### 截图为空白或内容不正确

检查屏幕录制权限，并在“文件 → 设置…”中预览和更换显示器。修改系统权限后，通常需要重启终端和程序。

##### 快捷键无效

确认对应快捷键没有留空或被其他程序占用，并检查当前用户是否具有监听全局键盘事件的权限。macOS 当前仅支持将单个数字键设为全局快捷键。

## TODO

- [x] 美化客户端窗口界面
- [x] 实现从服务器获取最新版本模型的服务端与客户端
- [ ] 抽卡统计展示客户端
- [ ] 完善客户端打包和发布流程
