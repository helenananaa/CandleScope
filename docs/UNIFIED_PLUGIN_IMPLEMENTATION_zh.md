# 统一插件体系实施与交付记录

关联：[#182](https://github.com/helenananaa/CandleScope/issues/182)、
[#349](https://github.com/helenananaa/CandleScope/issues/349)、
[#350](https://github.com/helenananaa/CandleScope/issues/350)、
[#351](https://github.com/helenananaa/CandleScope/issues/351)。

盘点基线：`39f8a8ade3c6691d67e1f306f2c7ec3ff2ca726a`，2026-11-18。
原 issue 的关闭标准不变。本文件记录分阶段交付，不以创建子项、合入 PR
或源码测试通过代替实际安装版验收。

## 分批交付边界

第 1 批交付清单、包级激活身份、依赖预检及只读元数据检查。
第 2 批交付归档校验、不可变包存储和可恢复的期望配置事务。
这两个阶段没有执行器；它们的 CLI 回执 `executorsAttached: false` 只描述 CLI 本身，
元数据检查的 `productionInstallable: false` 不代表当前宿主拒绝统一包。

第 3 批将共同 owner 接入 live/offline 启动、受保护管理 API、插件中心、
窗口与 Electron 入口，并执行 Python 后端和新协议 sidecar。
`workbench` 现在包含可构建的前端、后端、桌面和 Python worker 四入口样本。
同一包共用版本、摘要、generation；每个进程/窗口入口另有 instance。
停用、更新或失败先撤销旧结果与资源资格，再清理；宿主代码变更显示待重启，
断联窗口显示不可用，不将期望启用等同于全部入口已运行。

第 4 批接入 #350 的构建前工厂和窗口根布局，同时提供独立的安全启动及按包禁用入口。
各平台的安装版验收单独记录。#351 继续负责 Pine/旧消费者迁移与旧协议删除。旧体系暂留以供这些消费者迁移，新统一包只经过新 owner；
不得把并行状态当作最终架构。Pyne 归档明确拒绝，不恢复或自动转换，保留原始输入。
源码与进程级测试不代替安装版、多窗口 UI、Windows 隔离或完整产品验收。
执行器契约及运行步骤见 [运行指南](../backend/app/plugin_lifecycle/README_zh.md)。

本批在 macOS arm64（Python 3.12、Node 24）通过 SDK 242 项、包存储与执行器 58 项、
桌面 145 项和插件相关前端 71 项测试。进程集成用真实 HTTP、Python 后端模块和 Node 桌面
执行器验证共享身份及撤销，另有真 Python sidecar、离线管理边界、过期资源票据和 Pyne
拒绝用例。前端通过类型、插件架构、30 语言、变更文件 lint 和生产构建检查。

## 1. 统一清单与包身份

以 [workbench 样本](../examples/unified-plugins/workbench/manifest.json) 为准：

| 字段 | 契约 |
| --- | --- |
| `schema` | 必须为 `candlescope.unified-plugin/1`；不推断旧 schema 的含义 |
| `id` / `version` | 一份包身份；version 使用精确 SemVer，依赖版本不使用范围 |
| `name` | 展示名称，不能作为身份或授权依据 |
| `hostApiVersion` | 本轮为整数 1；不接受布尔值或未知版本 |
| `trust` | `restricted` 或 `full-trust`；声明不等于已经获得授权 |
| `entries` | 1–32 个入口，入口 ID 在包内唯一，共用包版本与安装状态 |
| `dependencies` | 其他插件 ID → 精确版本；最多 32 个，不允许自依赖 |
| `permissions` | 最多 64 个唯一的版本化 capability ID；仅为声明，不产生权限句柄 |

入口分别声明 `id`、`kind`、`path`。`kind` 为 `frontend`、`backend`、
`desktop`、`sandbox-view`、`sidecar` 或 `data`。
宿主前端/桌面入口为 `.mjs`，后端为 `.py`，sandbox-view 为 `.html`，
data 为 `.json`。sidecar 必须显式声明受支持的 runtime kind：
`python-module`、`native-executable`、`java-jar`、`node-module` 或 `wasm-component`。
**这些枚举不表示所有平台已经取得运行资格。** 第 3 批为这些类型提供执行接线，
只实测 Python worker；其他运行时必须在宿主可用并完成目标平台验收后发布。

受限模式拒绝 frontend/backend/desktop 宿主代码；sandbox-view、sidecar、
data 在通过各自内容验证和权限/隔离检查后才能使用。未知字段、执行模式、
运行时、重复 JSON key、非有限数、超限输入和不安全跨平台路径一律拒绝。

包继续使用 `.cspkg` 作为用户导入文件后缀；schema 和经过校验的包内容决定
其含义，不能凭后缀选择旧执行路线。第 2 批交付统一 envelope 的全部文件摘要与
归档限制；第 3 批使用宿主现有运行时；运行时制品供应和目标平台资格仍须后续交付。可复用既有安全检查，但新包不经旧包
转换器或旧安装器运行。数据主题与布局的内容验证也必须保留。

### 依赖预检

`activation_order()` 的输入是**变更后的完整拟启用集合**，不是单个新插件。
同一 ID 不能出现两个版本；缺失依赖、精确版本不符、循环和超限集合在启动任何
入口前拒绝。预检覆盖安装/升级，以及仍有消费者时的停用/卸载。独立节点按 ID
确定顺序，依赖先启动、逆序停止。初期单次计划上限为 256 个插件，是有界准入
限制，不是性能或任意规模承诺；未来扩容须另做预算和验收。

预检不获取依赖，不导入插件，不操作注册表，不执行启动 hook。清单排序不等于
服务替换冲突已经解决；#350 仍须在实际构建前验证替换计划。

## 2. 生命周期和状态契约

后续唯一 lifecycle owner 负责包级变更，执行器只消费它发布的激活计划，
不得再各写一份“当前启用版本”。可复用独立执行器和运行时制品缓存，不能保留
独立安装/启停 owner。建议实现顺序：

1. `inspect/stage`：有界校验归档、全部摘要、清单和依赖，不导入代码。
2. `approve`：绑定包摘要与信任模式；旧批准不能自动覆盖新字节或权限提升。
3. `commit desired`：锁内复核预期 registry revision，以可恢复事务发布完整计划。
4. `reconcile`：各执行器校验身份，按依赖顺序启动，报告各入口实际状态。
5. `revoke/stop`：先撤销结果采用资格，再停止与清理；失败有明确回执。

包级 `ActivationIdentity` 包含 ID、版本、完整包 SHA-256 和正安全整数 generation。
generation 由唯一 owner 持久分配；重启中断恢复、重新启用、回滚、卸载重装都不能
复用曾撤销身份。重启恢复是否延续同一激活与新进程 instance 必须明确区分，
不能把全局 generation 和进程启动次数混为一谈。

所有入口共用包激活身份；执行请求/回执另绑定 entry ID 和进程/窗口 instance。
输入只来自受限 API 允许的范围。结果发布同时校验当前激活、入口 instance 和
调用上下文；比较 ID/版本或声明同一个摘要都不足以接纳旧结果。

| 状态维度 | 必须表达的内容 |
| --- | --- |
| 期望配置 | 安装版本、包摘要、期望启停、批准记录、registry revision/generation |
| 实际运行 | 每入口运行版本、instance、启动中/运行/失败/停止中/已停止 |
| 协调状态 | 待重启、待恢复、中断事务、依赖阻塞、实际旧版本仍运行 |

后端/桌面加载后不能宣称任意热卸载。期望升级已提交但旧代码仍在内存时，显示
待重启和实际版本；不能显示全部已更新。某入口启动失败不能把其他仍运行入口
伪装成已回滚；需要停止、补偿或独立恢复启动，并如实报告。

回滚代码必须使用新激活身份；不盲目回滚用户数据或插件外部副作用。新数据的
旧版可读边界须由迁移明确规定；不能读取时停止并解释，禁止静默误读或删除。

## 3. 旧入口、调用者和替代路径

此表是源码盘点，不判定所列旧功能已取得最终资格。目标路径按稳定接口依赖，
不要求 #165/#166/#181 整条先关闭。

| 现有入口/状态 | 主要调用者 | 去向与删除门槛 |
| --- | --- | --- |
| `app/plugin_runtime/bundle.py`：schema-1 `.cspkg`、`candlescope.script-runtime/1` | Pine/Python 的 `scripts/build_bundle.py`，旧 installer CLI | #351 重新打包并原生调用；拒绝旧包执行，保留脚本与历史制品 |
| `app/plugin_runtime/installer.py`、`registry.py`：`runtime-registry.json` | `first_party_plugin_bootstrap.py`、`plugin_core_v2/runtime_install.py`、desktop prepare 脚本 | #349 提供共同安装 owner，#351 迁完消费者后删除旧写入和启动接线 |
| `app/plugin_runtime/service.py`、`supervisor.py`、`app/plugin_host/` | `main.py`、`indicator/runtime_service.py` | 复用必要进程监控/传输组件；删除旧注册表驱动的独立生命周期，不盲删可复用机制 |
| `app/plugin_installer_v2/bundle.py`、`installer.py`、`registry.py`：平台包及 `platform-registry-v2.json` | `plugin_core_v2`、marketplace、import CLI | 复用制品校验、原子存储、供应绑定和回滚机制，收敛到唯一包/激活记录 |
| `app/plugin_core_v2/runtime_install.py`：自动分流旧 runtime bundle | `plugin_core_v2/api.py` 安装/review/confirm | #351 删除分流；旧包返回需更新，不能经旧 installer 偷跑 |
| `app/plugin_compat_v1/bridge.py`：旧运行时目录投影及 import/rollback | `main.py`、core API、前端兼容区 | #351 原生迁移完成后删除桥、相关 API 和可执行 UI，不以统一目录代替统一生命周期 |
| `app/trusted_extensions/store.py`：`.csext`、`candlescope.extension/1`、`trusted-extensions-v1/state.json` | extension API、前端 ExtensionManager、Python/Desktop host | #349 统一身份/安装；复用摘要批准、主题/布局验证、资源身份和恢复机制，最终删除独立 registry |
| `app/trusted_extensions/runtime.py`：prepare/activate、factory wrapper | `main.py` 的 data-engine/replay/alert-delivery/indicator-range 构建 | #350 改用统一激活计划；必须证明所有实际消费者使用替换依赖 |
| `frontend/src/features/extensions/`：运行时、slots、资源/管理 UI | App shell、设置入口 | #349 接共同计划与管理 API；#350 保留根布局接管、冲突检测和替换 UI 外的恢复入口 |
| `frontend/desktop/trusted-extension-host.mjs`、`main.mjs` | Electron 启动、诊断 IPC、safe-mode CLI | #349 读共同计划；#350 统一恢复启动，marker/IPC 身份校验不能回退 |
| `frontend/src/features/plugins/`、`plugin_core_v2/api.py` | 插件中心、能力调用、管理会话 | 统一展示/操作与 entry 诊断；原 loopback/Origin/CSRF、权限和实盘确认边界保留 |
| `app/plugin_market_v2/chart_contexts.py`：当前仅 live | 插件 chart-context API、chart layers/market consumers | #351 消费多图和各回放上下文，输入/结果受可见时间与修订约束 |
| `app/plugin_runtime_registry_v3/` 和 runtime provider 供应缓存 | 平台安装器、Python/Node/Java/WASM provider | 属于执行环境供应，可复用；不能误当成用户插件第二套安装/启停 owner |
| `packages/candlescope-plugin-pine-compat/` | 图表指标、策略和 Pine host inputs | #351 保留引擎与语言语义，改用新生命周期；不把包名中的 compat 当作 Pyne 兼容 |
| Pyne 拒绝规则及 `backend/tests/test_pyne_removal.py` | API、策略编译、旧已安装运行时启动过滤 | 永久保留退役回归；新契约显式拒绝退役身份/运行时，不转换、不删除原始数据 |

最终删除前逐项 `rg` 检查直接/间接调用者、启动环境变量、构建/发布输入、CLI、
文档及工作区恢复。现有历史 QA 只归档引用，不为了“零匹配”删除历史文本。
旧格式文件可以留存供用户导出和查看，但不再构成可执行安装/注册路线。

## 4. 既有实现与证据映射

| 能力 | 可复用实现/历史证据 | 当前不能据此宣称 |
| --- | --- | --- |
| 可信扩展 | PR #71；`docs/trusted-extensions.md`；backend `test_trusted_extensions.py`、frontend extension runtime tests、desktop host tests | 统一包/生命周期已实现；终端样本只注册状态，不证明全部架构替换 |
| 通用包安装/权限/回滚 | `plugin_installer_v2`、`plugin_security_v2` 及相应 tests；`docs/PLUGIN_PLATFORM_ROLLBACK_RUNBOOK_zh.md` | 新多入口包事务和安装版恢复已通过 |
| Pine/Python 现有接线 | #81/#210；`docs/qa/FRONTEND_CLOSEOUT_20261103_zh.md` | 新体系原生适配已完成；旧包数量不构成迁移资格 |
| Pine 会话隔离 | `docs/qa/pine-compatibility-main267-20261107/README.md` / `receipt.json` | 原记录包含并发相同 clientId 隔离失败，不可引用为全部通过；须重查最终候选 |
| macOS 原生源/重启/回滚 | `docs/qa/frontend-architecture-acceptance-20261111/README.md` | 所有结果同一最终提交、统一生命周期或 Windows 合格；原文保留各提交及未测边界 |
| 本批候选清单与预检 | SDK `tests/test_unified_manifest.py`、只读 inspector | 已安装/启动、已实现 generation 围栏、可信替换或原生保存重启 |

历史证据按各自提交/输入/运行时/平台使用；未在本批重跑的旧测试不填写本批通过。
财务一致性、数据正确性、隔离、无未来泄露和保存重启要求不降级。

## 5. 后续 PR 顺序与退出条件

| 批次 | 关联 | 交付与退出条件 | 状态 |
| --- | --- | --- | --- |
| 1 | #349 | 候选清单/依赖/身份、旧入口与证据映射、只读检查和回归 | 本批实现；本地结果见下节 |
| 2 | #349 | 统一 envelope/不可变包存储/期望激活 registry/可恢复变更；真实临时目录故障注入，无半安装执行 | 已在 #476 提交 |
| 3 | #349 | 前后端/桌面/sidecar 接共同 owner，统一 API/UI；同包多入口生命周期真实运行，旧代结果拒绝 | 已在 #478 提交 |
| 4 | #350 | 构建前依赖计划/真实替换/冲突与资源清理；独立恢复启动能救回故意失败插件 | #479 已提交，[macOS 离线验收](qa/unified-plugin-takeover-350-20261118/README.md)通过 |
| 5 | #351 | 图/运行/模式/数据修订/可见时间贯通；跨图/回放/迟到结果和无未来泄露验证 | 统一计算入口已接入，见 [本批验收](qa/unified-plugin-chart-context-351-20261118/README.md) |
| 6 | #351 | Pine 原生打包、发现/调用/发布和状态恢复；固定引擎/输入的指标/策略/图形回归 | 桌面已接入统一包和执行器。验收见 [Pine 迁移记录](qa/unified-pine-351-20261118/README.md) |
| 7 | #351/#182 | Python 指标接统一生命周期，退役产品旧脚本协议及安装/注册入口 | 已接入，见 [脚本迁移记录](qa/unified-script-retirement-351-20261118/README.md) |
| 8 | #351/#182 | 可信扩展接入统一激活与外观选择，停止产品启动旧 .csext，保留数据和恢复 | 已接入，见 [可信扩展迁移记录](qa/unified-extension-migration-351-20261118/README.md) |
| 9 | #351/#182 | 迁移市场供应、权限与运行观察，退役旧平台生命周期；各平台联合验收 | 同一发布者重发的旧包可迁移；[macOS 纯数据市场包安装版验收](qa/unified-marketplace-migration-351-20261118/README.md)通过，Windows 隔离和旧侧车恢复待验 |

不等待整个关联 issue 完成才开发；按稳定接口交付。每批局部检查通过后可继续下一批，
云端 CI 不作为开始下一批的阻塞；合并 main 前检查最终提交 CI 和该批适用验收。
父 #182 保持开放，直到只有一套生命周期、Pine 原生适配、可信接管与独立恢复均合格。

### 统一市场包

市场分发统一 `.cspkg` 时，在签名制品中设置
`packageFormat = "candlescope.unified-bundle/1"`。市场索引 v1 和 v2 均可追加新版；
v2 还验证宿主目标、独立制品签名、运行绑定和许可清单。归档包含
`manifest.json` 和 `sbom/cyclonedx.json`。市场沿用固定信任根、发布者签名、
透明日志、撤销和防回放规则，并校验归档、清单和 SBOM 的签名摘要。
同 ID 更新需要同一市场和发布者、相同主版本以及更高版本。

用户从市场下载、暂存并确认激活。授权绑定到包摘要、清单中的权限和审批时的激活代次。
签名验证不会授予权限。已暂存的市场摘要不能通过本地安装入口激活。当前支持受限数据
入口和宿主具备隔离条件的 sidecar。`chart.compute/1` 仅允许 sidecar 接收当前图表的
已揭示 K 线。v2 签名记录使用 `chart.compute` 和 `{"data":"revealed-chart-bars"}`
表示这一权限。v2 统一包的运行绑定只列 sidecar，纯数据包使用空数组。
可执行入口使用 `python-module` 或 `native-executable`，绑定的 `runtimeId`
等于入口运行时类型，制品路径和摘要指向归档中的入口文件。

试运行与旧激活记录写入同一统一注册表事务。数据入口须通过宿主解析，sidecar 须确认
本次激活身份并在观察窗口内存活。观察失败或进程在观察结束前退出时，回滚到原记录并
为恢复的版本分配新代次。首次安装失败会移除激活记录。撤销或索引过期会阻止相应
版本继续运行，归档和用户数据仍可保留。

本地 [API 回归](../backend/tests/test_unified_marketplace.py) 使用实际 Ed25519 签名、
统一执行器和临时注册表，覆盖篡改拒绝、审批、失败升级、重启恢复和撤销。
### 从 Platform v2 市场包迁移

同一市场和发布者签发的更新统一包可接手同一插件 ID。审批同时绑定旧激活记录、
包摘要和授权记录摘要。宿主先停旧实例、撤销其运行授权，再为新版生成独立私有目录。
新版通过已有的 `storage` 路径读取 `platform-v2/settings.json`、
`platform-v2/host-storage.json`（存在 Host 存储时）和
`platform-v2/sandbox/`（存在沙箱文件时）。新版负责读取和解释这些导出；
旧授权和协议由旧安装保留，新版使用自己的权限合同。

健康失败或中断后，宿主先停止新版并验证旧包和旧授权，才恢复旧激活。健康通过后，
可从市场回滚到签名仍有效的旧版。回滚保留两个版本的私有数据，双方新增数据不合并。
新一侧的目录位于统一插件存储根下的 `marketplace-private/<插件 ID>/<首次接管代次>/`。
禁用或卸载统一包时保留迁移记录及发布者绑定，旧实例仍待用户显式回滚。旧市场包需要
由发布者重发统一包才能迁移。

[迁移回归](../backend/tests/test_platform_marketplace_migration.py) 覆盖已安装旧包、
命名空间内数据复制、失败补偿、重启恢复、手动回滚和旧包撤销。Windows AppContainer、
桌面安装版联合验收和全部旧市场包退役仍需单独验证。

## 6. 检查与最终证据要求

只读检查：

```sh
python3 backend/scripts/inspect_unified_plugin.py \
  examples/unified-plugins/workbench/manifest.json
```

SDK 测试（在 `packages/candlescope-plugin-sdk/` 下运行）：

```sh
python3 -m pytest -q tests/test_unified_manifest.py tests/test_package_architecture.py
```

本批最终源码本地验证：全 SDK **242 项通过**（Python 3.12 / macOS arm64），
覆盖新清单与依赖拒绝、CLI 不执行/不写用户目录、既有 v1/v2/v3 契约和 SDK 架构检查。
变更 Python 文件的 Ruff、样本 ESM 语法、workflow YAML 解析及 diff whitespace 检查通过。
新增 CI 在 Linux Python 3.11/3.12、macOS Python 3.12、Windows Python 3.12 运行全 SDK；
云端结果以 PR 最终提交状态为准，不因配置了矩阵就宣称跨平台已通过。
这些不包含生产后端/前端/desktop 接入或安装版资格，不关闭 #349。

后续故障矩阵至少覆盖归档/依赖/权限拒绝、stage/commit/启动中断、部分入口失败、
升级/回滚/停用/卸载并发、迟到请求及清理失败。#350 须沿真实服务调用链断言替换实例；
#351 须固定数据/引擎参考并检验输入和输出的可见时间边界。

最终每条要求记录产品源码 SHA、包摘要、插件/运行时版本、输入指纹、平台/机器、
场景、原始日志及结论。macOS 与 Windows 安装/更新/保存/完整退出/重启分别验收；
浏览器、组件、源码 replay 不替代安装版证据。性能先固定输入、规模和预算，
报告启动/计算/发布/停用延迟、内存/磁盘与残留进程，不预填未测收益。

## 7. 第 2 批候选存储与事务

`bundle.json` 的 schema 为 `candlescope.unified-bundle/1`，`files` 必须逐一列出
归档中除自身以外全部文件（含 `manifest.json`）的 `sha256` 和整数 `size`。
摘要标识确切字节，不证明发布者身份。未知 envelope、漏列/多列、大小/摘要差异、
入口文件缺失、旧包一律拒绝，不自动分流到旧 installer。

验证先有界解析 ZIP central directory，避免 `ZipFile` 在文件数检查之前分配大量
对象；不接受多卷、ZIP64 end record、archive comment 或尾随字节。实际预算不需要
ZIP64：归档最多 512MiB、1024 项；单文件 256MiB、总展开 1GiB、压缩比最多 100。
路径须跨平台安全，无大小写/文件目录冲突、链接、加密或非普通文件。所有内容流式
校验，不解包、不 import、不执行探针。文件大小预算沿用既有平台，未宣称性能收益。

候选 store 持有唯一 `registry.json` 和单条 `transaction.json`。变更前先复核
调用者的 `expected_revision`、确切摘要/信任批准及完整拟启用集合；先持久写 intent，
原子替换 registry，再清理 intent。原子替换是提交点：

- 提交前进程退出：重开观察到 before，撤销未提交 intent，保留旧配置。
- 提交后进程退出：重开观察到 after，保留新配置并清理 intent。
- 当前状态既不是 before 也不是 after，或 journal 损坏：明确拒绝，保留原文件；
  不覆盖未知更新，不自动清空注册表，不执行代码来“恢复”。

提交返回异常可能已跨过提交点，调用者必须重新读取 revision，不能盲目重放旧命令。
每次成功变更推进全局持久 generation；包记录保存自己的最近代次。回滚/重新启用/
卸载重装均不会恢复旧激活身份。这里证明的是期望配置持久性，实际运行实例、迟到
结果采用和多入口补偿仍需第 3 批接入后验证。

更新/停用/卸载会检查启用中的反向依赖；旧制品继续留存。缓存初期上限 2GiB /
1024 个文件，崩溃留下的 stage 临时文件也计入预算；容量不足时拒绝新 stage，
不自动删除旧包或用户数据。该候选工具无自动 GC/下载/插件执行，也不假称有签名认证。

示例只在显式隔离目录操作：

```sh
python3 backend/scripts/unified_plugin.py build \
  examples/unified-plugins/workbench /tmp/workbench-unified.cspkg
python3 backend/scripts/unified_plugin.py stage \
  --root /tmp/candlescope-unified-demo /tmp/workbench-unified.cspkg
python3 backend/scripts/unified_plugin.py list --root /tmp/candlescope-unified-demo
# review 返回 registryRevision；activate 需显式提供该 revision 和 trust:sha256:<digest>。
# 此处仅修改期望配置，不启动任何入口。
```

构建输出必须位于源目录之外，不覆盖已有文件。根路径、内部目录/registry/journal/
lock 和包文件拒绝符号链接或 Windows reparse point。CLI 的批准字串只是对审阅字节和信任模式的绑定，不是
管理身份验证；生产接入仍须使用原 loopback/Origin/CSRF/会话和权限控制。

第 2 批测试位于 `backend/tests/test_unified_plugin_store.py`，用真实 ZIP/文件系统、
锁竞争、提交前后 `os._exit` 子进程终止及新 owner 重开检验恢复。不是安装版应用
保存重启证据；各平台 CI 与 macOS/Windows 原生资格继续分别记录。

本地最终源码 **41 项通过**（Python 3.12.15 / macOS arm64，含 Windows reparse 元数据模拟）；一次预期的重复 ZIP
文件名警告来自恶意归档测试。变更 Python Ruff、workflow YAML 解析及 diff whitespace
检查通过。CI 矩阵增加同一套存储测试，尚不据此填写其他平台通过。
从 `backend/` 运行：`PYTHONPATH=. python3 -m pytest -q tests/test_unified_plugin_store.py`。
