# Zc Flight Statistics

本仓库用于管理**Zc航空抽卡统计**的各个组件。

## 组件

### 抽卡数据录入客户端

**路径：** `client/data-entry`

Zc航空抽卡统计数据录入客户端。程序会截取指定显示器，使用 ONNX 模型识别抽卡画面和干员，然后将结果提交至统计接口。操作界面由 WebView 显示。

#### 功能

- 指定显示器截图，支持多显示器环境
- 识别单抽和十连画面
- 识别十连结果中的干员
- 通过图形界面选择乘客并记录抽卡次序
- 支持新增、顺延和重命名乘客，并自动同步当前乘客
- 支持单抽、十连全局快捷键，且可按操作单独关闭
- 将识别结果和截图提交至统计接口
- 启动时自动检查、校验并更新识别模型
- 支持在运行时修改活动、切换卡池、显示器、乘客名单和快捷键
- 支持查看所选显示器的截图预览
- 支持通过“统计 → 直播页面设置…”控制直播页面各项目的显示状态
- 通过 `.env` 保存本地认证信息

#### 目录结构

```text
CHANGELOG.md                     # 版本更新记录
client/data-entry/
├── main.py                      # 识别与原有 Tk 界面
├── webview_app.py               # WebView 程序入口及 Python 交互层
├── webview_ui/                  # 页面、控件样式及随客户端提供的主题
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
    ├── image_type.onnx         # 画面类型识别模型
    ├── gacha10.onnx            # 十连干员识别模型
    ├── operators.txt            # 与十连模型配套的有序干员类别表
    └── manifest.json            # 本地模型版本清单
```

`config.json`、`name.csv` 和 `.env` 属于本地用户配置，不会提交至 Git。程序首次启动时会根据对应模板自动创建这些文件。

`models` 目录会被 Git 保留，但其中的模型、干员类别表和本地版本清单不会提交。客户端启动时会从服务器获取模型清单；下载完成并通过文件大小和 SHA-256 校验后，才会替换本地文件。`operators.txt` 与 `gacha10.onnx` 配套，由模型训练项目维护并经服务器分发，不在客户端项目中单独维护。服务器临时不可用时会继续使用已有文件；首次运行且本地没有模型或类别表时，需要能够连接模型服务。

#### 安装

##### Windows 一键安装（推荐）

适用于 Windows 10/11 **Intel/AMD 64 位**电脑，无需预装 Python、Git 或 Conda。

1. 下载并解压本仓库，或取得完整的 `client/data-entry` 文件夹，将它放在固定、可写且路径较短的位置，例如 `C:\ZcFlight\data-entry`。不要直接在压缩包内运行，也不要放在 `Program Files` 下。
2. 双击 `client/data-entry/install.bat`，等待安装完成。安装器通过 GitHub 下载固定版本、经过 SHA-256 校验的 uv，由 uv 下载 Python 3.11，并默认从清华 PyPI 镜像安装 `requirements.txt` 中的依赖。识别使用 CPU 版 ONNX Runtime，界面使用 WebView2，无需安装 TensorFlow。
3. 双击 `start.bat`，或桌面上的 **Zc航空抽卡统计数据录入** 快捷方式。首次启动会打开羽bot个人中心登录页。使用有 `zc.flight_user` 权限的 QQ 或邮箱账号登录。
4. 登录通过后客户端重新启动并下载识别模型；进入“文件 → 设置…”选择当前活动和显示器。

安装器会检查 Microsoft Visual C++ 运行库；缺失时下载并验证微软签名，随后请求 Windows 管理员授权进行安装。还会检查 Microsoft Edge WebView2 Runtime；缺失时先从微软官方页面安装，再重新运行 `install.bat`。如提示重启，请重启系统后再次运行安装器。Python 和应用依赖的安装不需要管理员权限。

**指定软件包源：** 双击安装默认使用清华源，也可以在客户端目录打开终端后指定中科大源或官方 PyPI：

```powershell
.\install.bat -IndexUrl https://mirrors.ustc.edu.cn/pypi/simple
.\install.bat -IndexUrl https://pypi.org/simple
```

直接运行 `install.ps1` 时同样支持 `-IndexUrl`，可以填写其他 HTTPS 软件包索引地址（不支持在 URL 中包含账号密码、查询参数或片段）。安装窗口和日志会显示所选源；该选项仅作用于本次安装，不修改全局 pip/uv 配置，也不混用终端环境变量中的额外索引。如果镜像不可用或尚未同步所需版本，可显式指定官方源后重试。

这里未采用自动测速：索引页面的响应时间不能可靠代表 依赖文件的下载速度。软件包源选项只影响 Python 依赖，uv、Python 本体及微软运行库仍从原下载地址获取；识别模型仍由客户端从模型服务下载。

运行环境保存在 `client/data-entry/.runtime/` 和 `.venv/`，不会修改系统 PATH、系统 Python 或 Conda 环境。`config.json`、`.env`、`name.csv` 和 `models/` 仍保存在客户端目录，可单独备份。安装完成前会检查依赖、ONNX Runtime 和 WebView2 Runtime；此步骤不会连接业务接口或上传数据。

后续更新代码后，先关闭客户端，再运行 `install.bat` 补齐依赖；脚本可重复执行，不会覆盖已有配置、名单或模型。它不负责自动更新客户端代码。不要移动已经安装的目录：虚拟环境和桌面快捷方式依赖原路径。如果需要迁移，先关闭客户端，复制整个目录，删除新位置的 `.venv/` 和 `.runtime/`，再重新安装；保留 `.env`、配置、名单及模型。

安装失败时，窗口会保留错误信息，详细日志位于 `.runtime/install.log`。网络失败可直接重试；环境损坏时，关闭客户端后仅删除 `.venv/` 再安装。路径过长时改用较短路径。启动失败时，`start.bat` 会保留错误窗口。安装器仅为当前 PowerShell 进程设置执行策略，不会修改系统执行策略；若设备受组织策略限制，请联系管理员。

需要在自动化环境中跳过桌面快捷方式时，可运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File client/data-entry/install.ps1 -NoShortcut
```

Windows 安装流程的集成检查可通过 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File client/data-entry/test_windows_install.ps1` 执行。检查会在包含空格和中文的临时目录中真实下载依赖，验证首次安装、重复安装保留数据及并发安装拦截，不会读取真实 token 或连接业务接口。临时目录会保留并在结束时输出位置，检查完成后可自行删除。

##### 手动安装（开发及其他平台）

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

#### 登录与认证

客户端使用与 `https://yubo.run/user/` 相同的页面和登录流程。QQ 登录需按页面提示在群内发送验证码；邮箱登录需填写收到的邮件验证码。只有个人中心账号拥有当前有效的 `zc.flight_user` 额外权限时才会进入数据录入界面。服务端对每次受保护请求重新校验会话和权限；权限被撤销后，已有客户端的后续请求也会被拒绝。

成功登录后，客户端把会话保存在本机用户目录下的受限文件：Windows 为 `%LOCALAPPDATA%\zc-flight-data-entry\session.json`，macOS/Linux 为 `~/.config/zc-flight-data-entry/session.json`。本地最多保留 7 天；服务端会话也最多有效 7 天。使用“文件 → 退出登录”会调用个人中心退出接口并删除本地文件；默认返回登录页面，勾选“同时退出客户端”则关闭程序。网络故障时仍删除本地文件，但服务端撤销须在恢复连接后由管理员核查。

程序首次启动时会根据 `.env.example` 自动创建 `client/data-entry/.env`。该文件只用于可选的接口地址配置，不再填写固定登录 token。也可以在首次启动前手动复制模板：

```bash
cp client/data-entry/.env.example client/data-entry/.env
```

`.env` 已被 Git 忽略。升级时可删除其中旧的 `ZCFLIGHT_LOGIN_TOKEN`；新客户端不会读取它。不要将个人中心会话或其他真实凭据写入配置模板、源码或提交历史。

开发或自托管环境还可以在 `.env` 中覆盖以下接口地址：

```dotenv
ZCFLIGHT_LOGIN_INFO_URL=http://localhost:8000/api/kusa/get-login-info
ZCFLIGHT_LOGOUT_URL=http://localhost:8000/api/kusa/logout
ZCFLIGHT_MODEL_MANIFEST_URL=http://localhost:8000/api/gachalog-zc/get-model-manifest
ZCFLIGHT_CURRENT_USER_URL=http://localhost:8000/api/gachalog-zc/set-current-user
ZCFLIGHT_GET_POOL_LIST_URL=http://localhost:8000/api/gachalog-zc/get-pool-list
ZCFLIGHT_SET_CURRENT_POOL_URL=http://localhost:8000/api/gachalog-zc/set-current-pool
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
| `event_name` | 基础活动名称，会与卡池名拼接为完整活动名称 |
| `pool_name` | 卡池名称，由设置窗口从服务器卡池列表中选择 |
| `target_monitor_id` | 需要截取的显示器编号 |
| `user_name_list_file` | 乘客名单文件，相对于 `client/data-entry` |
| `hotkey_gacha10` | 十连快捷键，可留空 |
| `hotkey_3x` | 三星单抽快捷键，可留空 |
| `hotkey_4x` | 四星单抽快捷键，可留空 |
| `hotkey_5x` | 五星单抽快捷键，可留空 |
| `hotkey_6x` | 六星单抽快捷键，可留空 |

`event_name` 和 `pool_name` 均为必填项。旧版将卡池名直接拼入
`event_name` 的配置格式不再受支持，升级时需要手动拆分这两个字段。

切换、选择或导入名单后进入新的当前乘客时，客户端会自动将当前乘客信息
同步至统计服务，无需额外操作。

设置窗口会从服务器加载可用卡池，并实时预览由基础活动名称和卡池名称拼接得到的完整活动名称。保存时会同步切换直播页当前卡池。

设置窗口还会列出显示器的编号、分辨率和位置，并支持预览所选显示器。如果截取内容不正确，可以在预览后直接更换显示器。编号 `0` 通常表示所有显示器的组合区域。

#### 启动

可以从仓库根目录直接启动：

```bash
python3 client/data-entry/webview_app.py
```

客户端只随包提供 `classic.css`；其余主题从服务端加载，并须提供完整的客户端控件变量。同名时仍优先使用随包主题，所以 `classic` 始终使用本地文件。直播页面设置中的主题选择继续使用现有接口；若远程主题缺少客户端控件变量，客户端会回退到 `classic`。旧的 `main.py` 仍可单独启动 Tk 界面，用于迁移期间排查问题。

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

##### 登录后仍无法进入客户端

检查当前账号是否有有效的 `zc.flight_user` 权限，及个人中心接口是否可达。无权限时，`get-login-info` 会省略 `permission_code_list`；客户端会把缺失字段当作空列表，不沿用旧权限。服务端鉴权不可用时会拒绝业务请求，不会放行旧固定 token。

##### 提示找不到模型

客户端会在启动时自动下载模型。下载失败时，先检查网络连接以及 `ZCFLIGHT_MODEL_MANIFEST_URL` 是否正确。

如果模型服务暂时不可用，则需要确认 `client/data-entry/models/` 中已有以下文件：

```text
image_type.onnx
gacha10.onnx
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
- [x] 客户端接入羽bot本体，实现客户端内登录
- [ ] 客户端允许多用户同时向同一卡池添加记录
- [ ] 抽卡统计展示客户端
- [x] 前端页面支持切换主题样式
- [x] 客户端增加切换前端页面主题样式功能
- [ ] 支持自动热更新同名主题 CSS 文件
- [ ] 完善客户端打包和发布流程

### 从 TensorFlow 客户端升级

先关闭客户端，再运行 `install.bat` 安装 ONNX Runtime。首次启动需要联网下载
`image_type.onnx`、`gacha10.onnx` 及配套 `operators.txt`；旧 `.keras` 文件不能作为离线回退模型。
安装器不会自动卸载旧依赖。需要释放旧 TensorFlow 环境占用时，关闭客户端后删除本客户端
目录下的 `.venv/`，再运行 `install.bat` 重建；保留 `.runtime/`、`.env`、配置、名单和 `models/`。
确认 ONNX 模型工作正常后，可自行删除 `models/` 中不再使用的两个 `.keras` 文件。
