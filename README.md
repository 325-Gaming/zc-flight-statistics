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
- 启动时必须联网验证官方最低版本策略；低于门槛或需要恢复更新事务时才检查稳定版 Release
- 通过“文件 → 检查更新…”更新客户端代码并自动重启
- 支持在运行时修改活动、切换卡池、显示器、乘客名单和快捷键
- 支持查看所选显示器的截图预览
- 支持通过“统计 → 直播页面设置…”控制直播页面各项目的显示状态
- 通过羽bot个人中心登录，并在本机受限文件中保存会话

#### 目录结构

```text
CHANGELOG.md                     # 版本更新记录
update-policy.json               # data-entry 官方最低支持版本策略
client/data-entry/
├── main.py                      # 识别与原有 Tk 界面
├── webview_app.py               # WebView 程序入口及 Python 交互层
├── webview_ui/                  # 页面、控件样式、本地门禁深色样式及字体
│   ├── gate.html                # 门禁窗口页面，通过 pywebview 本地服务加载
│   ├── gate.css                 # 仅作用于启动门禁窗口的固定深色样式
│   ├── fonts/                   # Fusion Pixel 字体和字体 CSS
│   └── licenses/OFL.txt         # 字体许可
├── version.py                   # 客户端版本号
├── hotkeys.py                   # 跨平台全局快捷键
├── model_updater.py             # 识别模型更新工具
├── app_updater.py               # 客户端代码更新与重启辅助进程
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

1. 从本仓库的 GitHub Release 下载 `data-entry-vX.Y.Z.zip` 并解压，或下载仓库源码并取出完整的 `client/data-entry` 文件夹。将客户端放在固定、可写且路径较短的位置，例如 `C:\ZcFlight\data-entry`。不要直接在压缩包内运行，也不要放在 `Program Files` 下。
2. 在客户端目录双击 `install.bat`，等待安装完成。安装器通过 GitHub 下载固定版本、经过 SHA-256 校验的 uv，由 uv 下载 Python 3.11，并默认从清华 PyPI 镜像安装 `requirements.txt` 中的依赖。识别使用 CPU 版 ONNX Runtime，界面使用 WebView2，无需安装 TensorFlow。
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

每次启动时，客户端都会先在独立的启动门禁窗口中通过 HTTPS 读取并校验官方最低版本策略；策略检查成功前不会打开数据录入界面、注册快捷键或接受业务操作。策略唯一来源是仓库根目录 [`update-policy.json`](./update-policy.json)，客户端固定读取：

```text
https://raw.githubusercontent.com/325-Gaming/zc-flight-statistics/master/update-policy.json
```

策略格式为 `data-entry.schema_version`、严格的 `MAJOR.MINOR.PATCH` 格式 `minimum_supported_version` 和 1–500 字符的 `message`。客户端不读取本机、Release ZIP、Git remote、fork 或缓存中的策略。如果策略服务或响应校验失败，窗口会显示原因，只能重试或退出；离线时不能使用客户端。

本机版本已达到 `minimum_supported_version` 且策略有效时，门禁会从固定的官方 HTTPS 地址读取 `client/data-entry/version.py`，仅静态解析其中的版本号，不执行远端代码。只有该版本号高于本机版本时，才查询 GitHub Releases 列表以确认是否已有可校验的稳定版更新目标；版本号相同或较低时不请求 Releases API。官方 `version.py` 请求失败或内容无效时，已达标客户端仍可启动，不查询 Releases API；可选 Release 查询失败也不阻止启动。普通新版本仍可通过“文件 → 检查更新…”手动查询和安装。

本机版本低于门槛，或上次更新未完成/依赖安装失败时，客户端不使用 `version.py` 作为跳过依据，仍会在线检查官方稳定版 Release。必须找到满足门槛、标签与包内版本相符且具有有效资产和 SHA-256 校验值的目标；检查失败、目标缺失或校验无效时只能重试或退出。强制更新不会自动下载或安装；点击“立即更新”并在确认对话框中确认后，才会下载、校验、安装并重启。

进入客户端前还会同步当前乘客、创建主窗口并注册快捷键；任一步骤失败都会清理已创建资源，回到带有错误详情、“重试”和“退出”操作的门禁状态。重试会重新在线验证策略及强制更新要求，不会直接跳过门禁。

启动门禁使用本地固定的 dark 样式，不读取或写入 `localStorage`。页面在加载本地样式前即设置 dark 状态；`webview_ui/gate.css` 只匹配门禁页，Fusion Pixel 字体样式和字体文件位于 `webview_ui/fonts/`，不依赖个人中心页面或网络资源。Release 构建会验证门禁 CSS、字体 CSS 及其引用的字体文件均被打包。

Git 普通仓库、Git worktree（`.git` 文件）及 ZIP/Release 安装都使用相同的官方策略和启动门禁。Git 安装的强制更新使用官方稳定 Release 包，不依赖本地分支或 remote 是否更新；普通菜单更新仍保留 Git 快进路径（要求干净工作区、有上游且目标版本不低于策略门槛）。Release 包更新会校验文件清单与 SHA-256，并保留 `.env`、`config.json`、`name.csv`、`models/`、`.runtime/`、`.venv/` 及其他个人文件。逐文件替换期间若进程中断，下次启动会恢复事务备份；若依赖安装中断或失败，则保持门禁并要求重新验证、下载和安装，以修复可能部分变更的虚拟环境。辅助进程日志位于 `.runtime/update.log`；门禁会展示错误和重试入口。Windows 使用现有安装器补装依赖；其他平台使用客户端或仓库 `.venv/`。

#### 最低版本策略维护与发布顺序

直接编辑仓库根目录 `update-policy.json` 中的 `minimum_supported_version` 和提示 `message`。Release 工作流在发布前校验 JSON、schema、字段及语义版本，并拒绝低于当前门槛的 Release 标签；仓库根目录策略不会复制进客户端 Release ZIP。提高门槛时，必须先发布不低于新门槛的稳定版客户端 Release，并确认资产已发布、可下载且通过客户端包校验；之后才能合并/发布提高门槛的策略变更，不能让门槛先于更新包生效。启动时先强制验证策略；仅对已达标且无待恢复更新的客户端，官方 `version.py` 才作为 Releases API 查询提示。该提示请求失败不会放宽策略门槛，也不会阻止已达标客户端启动；低于门槛或需要恢复更新事务时始终强制验证稳定版 Release。发布客户端仍按下节通过 `data-entry/vX.Y.Z` 标签构建。

`install.bat` 可重复执行以补齐依赖，不会覆盖已有配置、名单或模型。不要移动已经安装的目录：虚拟环境和桌面快捷方式依赖原路径。如果需要迁移，先关闭客户端，复制整个目录，删除新位置的 `.venv/` 和 `.runtime/`，再重新安装；保留 `.env`、配置、名单及模型。

安装失败时，窗口会保留错误信息，详细日志位于 `.runtime/install.log`。网络失败可直接重试；环境损坏时，关闭客户端后仅删除 `.venv/` 再安装。路径过长时改用较短路径。启动失败时，`start.bat` 会保留错误窗口。安装器仅为当前 PowerShell 进程设置执行策略，不会修改系统执行策略；若设备受组织策略限制，请联系管理员。

需要在自动化环境中跳过桌面快捷方式时，可运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File client/data-entry/install.ps1 -NoShortcut
```

Windows 安装流程的集成检查可通过 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File client/data-entry/test_windows_install.ps1` 执行。检查会在包含空格和中文的临时目录中真实下载依赖，验证首次安装、重复安装保留数据及并发安装拦截，不会读取真实 token 或连接业务接口。临时目录会保留并在结束时输出位置，检查完成后可自行删除。

##### 发布客户端版本

发布前先更新 `client/data-entry/version.py` 和 `CHANGELOG.md`，提交并将目标提交推送到本仓库的 `master`。然后为该提交创建并推送 `data-entry/vX.Y.Z` 标签，其中 `X.Y.Z` 必须与 `version.py` 一致。推送标签不会立即发布。GitHub Actions 在北京时间每天 03:25 检查一次：从高于现有最新 data-entry Release 的标签中，选择版本号最大的未发布 `data-entry/vX.Y.Z` 标签，并从标签对应的已提交文件生成 `data-entry-vX.Y.Z.zip` 和包内的 `release-manifest.json`，校验后创建 GitHub Release。已有 Release（包括草稿）不会重复创建；旧版未发布标签也不会在新版发布后补发。若要按顺序发布多个版本，应按顺序推送标签并等待各自的定时检查。

也可以在 GitHub Actions 的 **Data-entry release → Run workflow** 中填写已推送的标签，立即手动发布；对应命令为 `gh workflow run data-entry-release.yml --ref master -f tag=data-entry/vX.Y.Z`。手动运行仍会检查标签格式、标签提交是否属于 `master`，且标签中的版本号必须与 `version.py` 一致。定时任务可能因 GitHub Actions 繁忙而晚于 03:25 开始。

发布包不包含本地配置、名单、模型、虚拟环境或测试文件。2.2.0 起可从客户端菜单更新后自动重启；2.3.0 起启动时必须在线验证官方策略，策略不可用时不能离线进入客户端。2.3.1 起，已达最低版本的客户端只在官方 `version.py` 高于本机版本时查询 GitHub Releases 列表；提示文件或可选 Release 查询失败不阻止启动。低于门槛或需要恢复更新事务时仍强制在线验证稳定版 Release。普通更新继续通过客户端菜单手动检查。首次安装或从旧版升级时仍需手动下载发布包并运行 `install.bat`。

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
- [x] 建立客户端 GitHub Release 打包与定时、手动发布流程
- [x] 在客户端内检查 Git 或 GitHub Release 更新，并在安装成功后重启

### 从 TensorFlow 客户端升级

先关闭客户端，再运行 `install.bat` 安装 ONNX Runtime。首次启动需要联网下载
`image_type.onnx`、`gacha10.onnx` 及配套 `operators.txt`；旧 `.keras` 文件不能作为离线回退模型。
安装器不会自动卸载旧依赖。需要释放旧 TensorFlow 环境占用时，关闭客户端后删除本客户端
目录下的 `.venv/`，再运行 `install.bat` 重建；保留 `.runtime/`、`.env`、配置、名单和 `models/`。
确认 ONNX 模型工作正常后，可自行删除 `models/` 中不再使用的两个 `.keras` 文件。
