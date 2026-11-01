# 认证与活动权限

## 服务分工

羽bot后端 kusabot 管理用户、QQ／邮箱登录会话、结构化权限和基础航空活动。`yubo.run/user/` 提供个人中心页面；客户端在 WebView 中打开该页面完成登录。QQ 登录依赖验证码交互，邮箱登录依赖邮件投递；这些属于 kusabot 的登录服务能力，不由 gachabot 另建账号体系。

客户端先调用 kusabot 验证会话及航空权限，随后将同一会话用于 gachabot。gachabot 每次受保护请求都向 kusabot 查询权限，并结合数据库中的活动成员关系进行操作校验，不缓存授权结果。认证上游不可用时不能绕过认证继续写入。

## 相关接口

以下为后端注册路径；默认公网入口加 `/api`。

| 方法 | 路径 | 调用者与用途 |
| --- | --- | --- |
| POST | `/kusa/login` | 个人中心登录流程 |
| POST | `/kusa/get-login-info` | 个人中心与客户端验证会话、获取登录信息与权限 |
| POST | `/kusa/logout` | 撤销会话 |
| POST | `/kusa/get-permission-info` | gachabot 每次受保护请求的认证上游 |
| POST | `/kusa/get-zc-flight-activity-list` | 个人中心活动管理 |
| POST | `/kusa/create-zc-flight-activity` | 创建基础活动 |
| POST | `/kusa/rename-zc-flight-activity` | 修改活动显示名称 |
| POST | `/kusa/set-zc-flight-captain` | 设置活动机长 |
| POST | `/kusa/set-zc-flight-crew` | 设置或更换活动乘务员 |

活动管理接口由个人中心使用；桌面客户端通过 gachabot 的活动列表接口选择自己可操作的活动，不直接创建基础活动。

## 会话契约

kusabot 的会话校验使用 `identifier` 和 `login_token` 字段。客户端访问 gachabot 时通过 `Authorization` 请求头携带 Bearer 会话，并通过 `X-Zc-Flight-Identifier` 携带登录标识。两者都属于需要保护的认证信息，不应进入文档样本、URL、截图、工单或普通访问日志。

客户端将会话保存到本机用户目录的受限文件，最多保留七天；服务端仍独立验证有效性。退出登录会调用撤销接口并删除本地会话；网络故障时本地清理不代表服务端撤销已经完成，需要恢复连接后核查。不得使用旧固定登录 token 作为兼容入口。

权限响应使用 `status` 与 `permission_list`；每个权限项目包含 `permission_code`、`has_global_scope` 和 `scope_value_list`。客户端和 gachabot 均依赖此结构，不能仅凭账号已经登录就认为具有航空权限。

## 权限边界

| 权限或身份 | 作用 |
| --- | --- |
| `zc_flight_captain` | 作用域列表保存活动 UUID，允许操作对应活动；机长有该活动直播配置的管理可见性与移除权 |
| `zc_flight_crew` | 作用域列表保存活动 UUID，允许作为对应活动乘务员进行业务操作 |
| 全局 `superadmin` | 基础活动管理及全局设置；不自动取得任一活动的录入或直播配置编辑权 |
| 配置创建者 | 仍有活动权限时，可编辑、转授权和移除自己创建的配置 |
| 获授权编辑者 | 仍有活动权限时，可编辑对应配置，不能转授权 |

每位机长最多对应一个基础活动；每个活动最多一位乘务员，乘务员可以服务多个活动。机长即使可以查看和移除活动内全部配置，也不能仅凭机长身份编辑他人配置或转授权。

创建者撤权后，保留的创建者编号仅用于历史归属，不继续赋予访问权限。撤权、乘务员更换和会话撤销会影响后续请求；客户端进入界面时的一次检查不能替代服务端逐请求验证。

## 失败语义

gachabot 对无效会话返回 401，对缺少相应权限返回 403，认证上游异常或响应结构无效时返回 503。具体业务还可能返回 404、409 或 422。kusabot 部分认证失败通过响应中的业务错误表达，因此联调时应同时检查 HTTP 状态和响应内容，不能只检查是否收到 HTTP 200。

## 源码定位

kusabot 中的 `plugins/kusa/auth.py`、`permissions.py`、`zc_flight.py` 和 `fastapi_api.py` 分别负责会话、权限、活动管理和接口入口；gachabot 的 `flight_auth.py` 负责认证上游调用。客户端对应入口为 `flight_session.py` 和 `login_window.py`。这里只保留定位信息，不复制实现。
