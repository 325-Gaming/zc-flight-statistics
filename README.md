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
- 支持通过“统计 → 直播页面设置…”控制直播页面各项目的显示状态
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
├── test_model_updater.py        # 模型更新测试
├── favicon.ico                  # 窗口图标
└── models/
    ├── image_type.keras         # 画面类型识别模型
    ├── gacha10.keras            # 十连干员识别模型
    ├── operators.txt            # 与十连模型配套的有序干员类别表
    └── manifest.json            # 本地模型版本清单
```

`config.json`、`name.csv` 和 `.env` 属于本地用户配置，不会提交至 Git。程序首次启动时会根据对应模板自动创建这些文件。

`models` 目录会被 Git 保留，但其中的模型、干员类别表和本地版本清单不会提交。客户端启动时会从服务器获取模型清单；下载完成并通过文件大小和 SHA-256 校验后，才会替换本地文件。`operators.txt` 与 `gacha10.keras` 配套，由模型训练项目维护并经服务器分发，不在客户端项目中单独维护。服务器临时不可用时会继续使用已有文件；首次运行且本地没有模型或类别表时，需要能够连接模型服务。

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
ZCFLIGHT_MODEL_MANIFEST_URL=http://localhost:8000/api/gachalog-zc/get-model-manifest
ZCFLIGHT_CURRENT_USER_URL=http://localhost:8000/api/gachalog-zc/set-current-user
ZCFLIGHT_GET_PAGE_DISPLAY_URL=http://localhost:8000/api/gachalog-zc/get-page-display
ZCFLIGHT_SET_PAGE_DISPLAY_URL=http://localhost:8000/api/gachalog-zc/set-page-display
ZCFLIGHT_GET_PAGE_STYLE_LIST_URL=http://localhost:8000/api/gachalog-zc/get-page-style-list
ZCFLIGHT_GACHA_HISTORY_URL=http://localhost:8000/api/gachalog-zc/history
ZCFLIGHT_MOVE_GACHA_URL=http://localhost:8000/api/gachalog-zc/move-record
ZCFLIGHT_REVOKE_GACHA_URL=http://localhost:8000/api/gachalog-zc/revoke
ZCFLIGHT_RESTORE_GACHA_URL=http://localhost:8000/api/gachalog-zc/restore
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
5. 通过“操作 → 抽卡记录…”查看当前活动的上传记录。窗口默认只请求当前乘客的记录；查看范围菜单还可以选择乘客名单中的任意乘客，只有主动切换到“全部乘客（当前活动）”后才会请求当前活动全部记录。
6. 在抽卡记录窗口中可以撤销、恢复记录，或将所选记录移至最前、移至最后、与前一条交换位置、与后一条交换位置；也可以使用“操作 → 撤销上一条”或 `Ctrl+Z`（macOS 可用 `Command+Z`）撤销当前乘客最近的有效记录。

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
operators.txt
```

##### 截图为空白或内容不正确

检查屏幕录制权限，并在“文件 → 设置…”中预览和更换显示器。修改系统权限后，通常需要重启终端和程序。

##### 快捷键无效

确认对应快捷键没有留空或被其他程序占用。快捷键可使用单个字母、数字、功能键，或 `Ctrl`、`Alt`、`Shift`、`Command` 与按键组成的组合，例如 `Ctrl+Alt+3`。

## TODO

- [x] 美化客户端窗口界面
- [x] 实现从服务器获取最新版本模型的服务端与客户端
- [x] 取消全局键盘 Hook，改用操作系统的注册快捷键接口
- [x] 将识别与上传结果拆分执行，并将上传任务放入后台队列
- [x] 客户端添加按钮，用于更新服务端中控制前端页面显示效果的记录
- [x] 客户端增加撤销等操作历史上传的抽卡记录功能
- [ ] 客户端接入 羽bot 本体，实现浏览器回跳登录
- [ ] 客户端允许多用户同时向同一卡池添加记录
- [ ] 抽卡统计展示客户端
- [x] 前端页面支持切换主题样式
- [x] 客户端增加切换前端页面主题样式功能
- [ ] 支持自动热更新同名主题 CSS 文件
- [ ] 完善客户端打包和发布流程
