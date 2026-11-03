# 回放双 Manager：后端入口与消费资源生命周期

本批收尾 #166 的后端入口和订阅生命周期。初始应用源码为 `5c30ed96f6a45ae85fefda740c5f2d769f6a2fe5`，初始成功原生脚本/包内校验提交为 `2da34f11146eb700c99b295253bfe45e44f3ab94`；随后合入 #232 的 main `1890a722`。收尾提交 `cb385b14` 移除指回协调器的类型导入，保持 Manager 中的服务句柄不依赖协调器定义。当前源码重新组装和原生复验后，以 qualification.json 记录最终源码/证据。

## 交付行为

HTTP 控制、能力和训练入口，以及 adapter/run WebSocket，使用 `DataManagerCore.replay` 绑定的现有服务。生产根未绑定、已关闭或运行时失效时拒绝访问，不回退到旧服务别名。Manager 负责入口和消费资源；虚拟时钟、事件顺序、撮合、账户和存储继续由现有 ReplayService/ReplayRuntime 持有。

Manager 跟踪每个消费流，关闭单图/窗口只释放自己的资源。主机关闭时先拒绝新入口，再取消消费流，最后沿用既有回放运行时关闭顺序；不通过消费流取消财务命令。连续取消只向子任务发送一次取消，清理超时仍保留所有权。训练订阅先退订，再等待 sender/receiver 清理，避免第二次取消把订阅遗留在运行中。`/debug/snapshot` 提供管理入口次数、流类型/数量、范围数和关闭状态。

## 验证与真实原生流程

- 前次后端扩展回归 110 项通过，生命周期联合回归 45 项通过；两者有重叠，不相加。收尾重跑 Manager、HTTP、主机生命周期和策略 Manager 的 32 项通过，JUnit 和日志归档。macOS CI 增加 Manager、回放 API 及应用生命周期三份测试文件。
- 后端完整架构检查在 main `1890a722` 上已有 10 条问题，均由现有 indicator.history_worker 反向依赖 HTTP 组合层引出。新增协调器类型导入曾另外引入回放反向依赖，已移除；修复后与主线 10 条完全一致，新增为零。保留完整前后记录，不把架构检查报成全绿。
- 实际候选包内导入路径属于包：研究/账户/Python SDK/Manager 83 项通过；2 项 Windows AppContainer 专用测试在 macOS 跳过，不算通过。980 个 backend/desktop 源文件、164 个 dist 文件、60 个 SDK 文件及 9 个插件资产匹配，无差异。测试使用 `-B`、禁止 pyc 写入。
- `acceptance.json.gz` 共 11 条记录，含两次启动和两次退出。两个实际 Electron app-page 窗口在同一 backend PID 上创建独立运行；Manager 为两个 adapter 和两个 run 维护四条流。推进 A 不改变 B 的时钟、源事件游标和完整 portfolio。
- A 增加 5m 图后拥有独立显示序列，后端仍是四条流；关闭该图只释放显示序列。关闭窗口 A 后后端只剩 B 的两条流，B 仍能推进，A 的权威状态保持。B 返回大厅后流数归零。
- 完全退出重启后分别打开两个原存档，run ID、各自时钟、源事件游标和完整 portfolio 与保存值一致。关闭窗口使流数按 4→2→0 释放。两次正常完整退出为 1787/1731 ms，未捕获渲染错误。测试和全部退出后的 `codesign --verify --deep --strict` 退出 0。

原生使用自有有限合成 BTC/ETH 1m 归档及独立五根聚合的 5m 数据。实际操作的是两份单商品 BTC 运行；不宣称跨商品执行验收。OS 沙箱只允许 loopback，实际子进程探针验证远端建立连接前被拒绝，没有替换后端响应。截图是对应包的真实界面。

## 失败记录与限制

保留两项真实 fail-before：生产根未绑定时曾绕过 Manager 使用旧别名；训练订阅在子任务清理期间连续取消两次会遗留订阅。修复后相关回归通过。另保留 QA 编写中的语法错误及旧启动夹具没有构造真实 DataManagerCore 的两项失败；修正夹具后生命周期通过，不把这些失败当作产品通过。

这是 macOS arm64、有限本地预热 BAR、两个窗口和两个运行的资格，不是在线冷/最新行情、Windows desktop、广泛断线重连、非空持仓交易财务、任意指标数学或大规模性能验收。当前 backend/desktop/frontend 重装；既有 standalone Python 和原生引擎按输入/来源核对后复用，应用 ad-hoc 签名；不是官方 CI 产物或新引擎构建。原始包、数据库和 profile 留在本工作树 output，证据归档不包含用户数据目录。

## 复核与复跑

在本目录执行 `shasum -a 256 -c SHA256SUMS`。`qualification.json` 提供源码、检查及范围摘要；`evidence/native` 保存实际回执、请求、清单、签名、截图，`evidence/checks` 保存检查及失败日志。完整调用链见 [架构说明](../../architecture/REPLAY_DATA_MANAGER_ENTRY.md)。

原生复跑使用 `frontend-followup-20261102/assemble-runtime.py`、当前 frontend 构建和 `repack-runtime.mjs` 组装独立 output 候选；先核对输入/包内源码和插件来源，再以包内 Python 执行 `seed-native.py`（只接受不存在的自有数据库）。`verify-bundled.py <output目录>` 验证真实包内导入/测试。设置 `CANDLESCOPE_PLAYWRIGHT_PACKAGE` 指向独立 playwright-core 的 package.json，`CANDLESCOPE_BATCH1_QA_ROOT` 指向该 output，再运行 `node docs/qa/replay-manager-service-20261103/native-acceptance.mjs`。准备夹具的环境包含 KLINES_DB_PATH、REPLAY_DB_PATH、REPLAY_HISTORY_ARCHIVE_DIR、SYMBOL_CATALOG_SNAPSHOT_PATH 和 CANDLE_DATA_DIR，均必须属于该新 profile；脚本复用的已核对插件资产路径见 verify-bundled.py。不得使用默认用户 profile。

当前 PR 须在最终提交的适用 CI（含 macOS arm64/x64 打包及包内回归）通过后合入。#166 的正式回放笔记、导入 BAR/成交用户流程，以及多商品交易等剩余验收继续开放；本批不关闭整个 issue。
