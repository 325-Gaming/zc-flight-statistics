# gachabot 业务服务

gachabot 是 NoneBot 插件，通过宿主提供 HTTP 接口，使用 MySQL 保存业务状态。它不是本仓库内可单独启动的服务；安装、插件加载和宿主依赖应在 `nonebot-plugin-zc-gachabot` 所在部署中维护。

以下路径为后端注册路径；默认外部访问时需加 `/api`。除明确标为公开的接口外，均需要会话认证，并按具体操作校验权限。

## 客户端业务接口

| 方法 | 路径 | 用途与主要约束 |
| --- | --- | --- |
| GET | `/gachalog-zc/get-activity-list` | 返回当前账号可操作的活动 ID、名称和机长／乘务员角色 |
| GET | `/gachalog-zc/get-pool-list` | 读取卡池列表与默认入口的当前卡池 |
| POST | `/gachalog-zc/set-current-user` | 按活动、当前操作员、卡池同步当前乘客 |
| POST | `/gachalog-zc/submit` | 提交识别结果或赠送记录；返回记录 ID、服务端顺序号及去重结果 |
| GET | `/gachalog-zc/history` | 按活动、当前操作员、卡池查询历史，可按乘客筛选 |
| POST | `/gachalog-zc/revoke` | 撤销指定范围内的记录，保留原记录 |
| POST | `/gachalog-zc/restore` | 恢复已撤销记录，并重新校验相关业务约束 |
| POST | `/gachalog-zc/move-record` | 将记录移到最前、最后、前一条或后一条 |
| GET | `/gachalog-zc/get-passenger-state` | 返回各乘客有效抽数、赠送状态及卡池赠送干员 |

提交的主要业务字段包括 `activity_id`、`pool_name`、`nickname`、`count`、`gacha_index`、`character_json`、`request_id`、`is_gift`。`character_json` 是序列化后的干员名称列表。当前上传队列提交结构化结果，不包含截图二进制内容。

`operator_id` 由服务端从认证账号解析，客户端不能指定。活动归属以不可变的 `activity_id` 为准，`event_name` 是服务端生成的显示快照。抽卡顺序按活动、操作员、卡池和乘客隔离；服务端分配 `sequence_no`，不能把客户端的 `gacha_index` 当作数据库最终顺序号。

`request_id` 用于提交去重：重复请求内容一致时返回已有记录，复用同一 ID 提交不同内容时返回冲突。客户端队列默认最多尝试三次，对网络错误和服务端错误进行有界重试；客户端错误不继续自动重试。不能用重新生成 ID 的方式盲目补交状态不明的请求，应先核查历史记录。

赠送记录与普通记录共用顺序、去重、撤销和排序机制；赠送的 `count` 为零且结果仅含一名符合卡池规则的干员，不计入实际抽数和普通抽卡统计。服务端校验赠送对象与重复领取，但不会以航空统计不足 300 抽为由阻止赠送；游戏内活动前的抽数不会补入航空统计。客户端添加时会对统计不足的情况提示确认。

## 直播配置接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/gachalog-zc/get-live-list` | 获取当前账号可见的直播配置及默认配置选择 |
| POST | `/gachalog-zc/create-live` | 创建关联活动、卡池和跟随操作员的配置 |
| POST | `/gachalog-zc/set-live` | 修改指定配置 |
| POST | `/gachalog-zc/set-live-editor` | 创建者替换编辑者列表 |
| POST | `/gachalog-zc/remove-live` | 移除配置 |
| POST | `/gachalog-zc/set-default-live` | 全局管理员设置默认配置 |
| GET | `/gachalog-zc/get-page-display` | 读取指定或默认配置的显示设置 |
| POST | `/gachalog-zc/set-page-display` | 保存显示设置，支持检查读取时的配置 ID |
| POST | `/gachalog-zc/set-current-pool` | 全局管理员修改旧默认入口的卡池 |
| GET | `/gachalog-zc/get-page-style-list` | 公开获取可用主题名称 |
| GET | `/gachalog-zc/get` | 公开获取直播统计 |
| GET | `/gachalog-zc/get-full` | 公开获取完整统计 |

`live_id` 只选择直播配置。配置决定活动、卡池、跟随操作员，以及可选的固定乘客；统计不会合并其他操作员记录。当前乘客按操作员、活动和卡池隔离，多份配置跟随同一组合时会读取同一当前乘客。

未提供或留空 `live_id` 时使用默认入口；非空但不存在或停用的 ID 返回 404，不回退至其他配置。显示设置读取会回显实际配置 ID，保存时的 `expected_live_id` 用于发现编辑期间默认选择变化，冲突时返回 409。

显示设置包括 ON AIR 活跃刷新、1–60 秒轮询间隔、主题、记分板、底栏各区域、滚动条和底栏文案。权限边界见[认证与活动权限](auth-and-activity.md)。

## 模型分发

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/gachalog-zc/get-model-manifest` | 获取需要认证的模型清单 |
| GET | `/gachalog-zc/download-model` | 按模型名称和版本下载需要认证的文件 |

服务端从元数据读取模型清单，并检查文件存在性与大小。清单包含 schema 版本，以及各资源的版本、SHA-256、大小、下载地址和最低客户端版本要求。客户端解析相对下载地址并携带认证信息，下载后校验大小与 SHA-256，再替换本地资源。

资源包括画面分类模型、十连干员模型和与其配套的有序干员类别表。训练、导出和类别顺序由训练项目负责；gachabot 负责分发，不在客户端临时推导类别顺序。服务端模型文件与清单必须配套发布。

## 主要持久化对象

| 表 | 职责 |
| --- | --- |
| `t_gacha_log_zc` | 活动、操作员、卡池、乘客、顺序、抽数、结果和赠送标记 |
| `t_gacha_log_zc_state` | 请求去重 ID 与撤销状态 |
| `t_zc_flight_activity` | kusabot 管理的基础活动和机长／乘务员关系 |
| `t_zc_flight_live` | 直播配置及显示设置 |
| `t_zc_flight_live_grant` | 直播配置编辑授权 |
| `t_zc_flight_operator_state` | 操作员在活动和卡池中的当前乘客 |
| `t_metadata` | 模型清单及相关全局元数据 |

本表为职责摘要，不作为建表或迁移依据。实际约束及升级步骤以服务端模型和经过审核的迁移文件为准。
