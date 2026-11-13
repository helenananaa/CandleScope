# H127：REST 页面接纳、规范写入与无载荷回执

产品实现 `df098035ba948026eeb6b6621a5b16d14b4eaa02`，基线 main `4520f8f725108a94af9205956572d037d4009464`。后续提交仅补验收、归档回退测试和证据；实际包的全部后端文件与当前 checkout 的哈希逐一核对。

本批补 #127 的下载载荷生命周期及 #126 预算消费，两个 issue 的原始关闭条件继续保留。#130 已关闭；本批不重复实现公共语义、共享块、修订账本或持久 writer。

## 默认接线与范围

- BackfillCoordinator 使用显式 `run_receipt()`。合格 Binance/OKX、默认来源身份、固定 epoch 网格的互不重叠原生任务，每页仍走原 Reconciler/规范 writer，等待完成后释放输入；同一任务取下一页前有背压。并发仍由既有 semaphore 控制，页面工作占用原共同预算。
- 已合格 mixed plan 完成原生输入后，由既有 H127 分页规范读取、K130 归并和 D126 物化接续。本批没有再写一套聚合数学。默认 DataManager/facade/scheduler/GapLedger 冷库 10007m 的完整接线有实际 SQLite 检查。
- 每任务使用有硬界的一位/slot 去重信息，支持倒序和旧空洞回填，保留先到重复的原合同。任务最多 100000 slots；一批最多 128 个任务；页面最多 1000 行。已写范围只合并同完整身份/source/phase 的连续区间，最多 4096 段；错误、失败详情和来源集有界，裁剪有显式诊断。
- 回执的 `bars_count` 是抓取到的唯一范围内记录数，不能冒充成功提交数。成功提交以 `ReconcileResult` 为准。部分取数/预算停止不能报告整次完成；预算停止不冒充来源耗尽。配额让出携带已有提交的标量信息，既有 coordinator 通知采用，重试按规范库剩余缺口继续；没有新增检查点或永久中间索引。
- 外部删除/修正、来源证明、修订/generation、owner/config 重绑和物理取消保护保留。取消会等正在执行的 SQLite 工作排空后释放页面预算；已合法提交的数据可保留，但未确认页面不报告完成。

普通 `run()` / `fetch()` 仍返回完整、可用的 `FetchResult.bars`。已有 report callback、formatter、filter、preview、覆盖实现、自定义 reducer/dedup、未合格身份/网格、重叠任务、Bybit native progress 等使用完整路径。归档任务沿用整对象提交与完整报告合同；一批含归档时整批回退，不让逐页提交破坏优先级或事务边界。

显式 receipt API 在运行开始冻结 payload demand：新的报告 payload consumer 必须在 active receipt runs 之间注册，运行中注册会明确报错。普通 `run()/publish()` 的动态注册合同保留；不会给旧 callback 静默发被清空的数据。运行开始已有 consumer 自动选完整路径，包括 false-valued callable。此生命周期约束见 `run_receipt()` / `receipt_scope()`。

**尚未完成**：归档下载/解码/整对象事务的全链路载荷释放；旧 custom/扩展完整路径；更多来源/日历/资格与成本矩阵；首屏/warmup/深历史调度；长稳态、并行实时和整应用资源验收。原整窗口预测预算保留并叠加页面预留，因此预留值仍随需求增长；不能据此宣称整应用恒定内存或 #127 完成。

## 检查和失败记录

- 最终产品完整 CCXT integration 选集 **2152 passed / 66 warnings / 241.66s**，架构检查通过。随后只增加真实归档回退测试变体，连同页面/engine 测试 **44 passed / 3.74s**；完整 CI 最终 head 结果见 PR。
- 低层 15 项、engine 17 项覆盖页面释放、配额、背压/取消、物理写入排空、部分失败与 sibling 进度、工作/字节/输出预算、重叠去重、完整结果兼容及 owner/config 重绑。真实临时 SQLite 与默认 DataManager 路径通过。
- 真实 pinned CCXT HTTP socket 的 10007m 原生输入：完整/receipt、batch 1000/32 四组，3/8 个 K 线物理页面，九字段一致，实际仅 2 根分钟输入被持久化。另 4 项 OKX 合格 REST 来源回执测试验证倒序、未知增强字段和 own commit digest 推进，以及外部 append/delete/amend；本组用受控 quota 以隔离来源围栏，不能算真实出口或配额性能证据。
- 初期 engine harness 错把单任务失败等同整批停机、把 sibling 成功提交误认为额外写入，已改为现有 gather 合同；OKX harness 先遇到实际 quota 让出，再遇到手工修正被来源投影拒绝，分别改为受控额度和真实外部 SQL 修正。partial 工作预算测试最末任务只有 2 行，断言按实际范围修正。成本脚本两个属性名错误均保留日志。所有失败与最终结果均在 evidence，未删除原始本地 output。

## 同输入成本

`cost.py` 在完整旧版后端、新版普通 API、新版 receipt API 的独立进程运行，均为新 SQLite；输入构造、数据库初始化、对象图测量不在计时窗。2 次热身后 5 次 process CPU/墙钟采样；另开一次 tracemalloc，不把其 CPU 当普通性能。测试 transport 输入已存在，故分配不含 fixture tape。机器其他工作未冻结，本表是受控采样，不是稳定延迟 P95/P99、进程 RSS 或网络性能资格。

| 指标 | 旧版 1024 行 | 新 receipt 1024 行 | 旧版 8192 行 | 新 receipt 8192 行 |
| --- | ---: | ---: | ---: | ---: |
| CPU 中位 ms | 56.020 | 63.938 | 586.620 | 646.133 |
| 墙钟中位 ms | 56.733 | 64.342 | 593.408 | 656.049 |
| 报告保留字节，首个计时样本 | 685980 | 5873 | 5459472 | 11685 |
| 报告原始 Bar 数 | 1024 | 0 | 8192 | 0 |
| 独立分配样本 peak 字节 | 1186034 | 1892154 | 5798233 | 2143012 |
| 共同预算 peak reserved 字节 | 2097152 | 10322045 | 16777216 | 25002109 |
| 物理请求 / writer 调用 | 2 / 3 | 2 / 3 | 9 / 17 | 9 / 17 |

8192 行报告保留约减少 99.79%，CPU 增加约 10.1%；1024 行 CPU 增加约 14.1%，独立分配 peak 增加约 59.5%。不能以大输入改善掩盖小输入成本。新版普通 API 的 CPU 中位 56.360/585.495ms，完整 payload 和旧版一致。

三组相同窗口的全部规范行含九字段及边界哈希、实际 writer 输入计数相同；最终 release 后 reserved=0。保守整窗口预测没有下降，新增页面上限预留会提高 admission 值。这是后续资源推广必须保留的代价。

## macOS arm64 原生回归

保留前端/runtime/plugins build `ef8f0e0fa6df299a823f4460b701eb1c3c98361f`，覆盖全部 **1001** 个 tracked backend app 文件，前后逐文件哈希、asar 哈希及严格签名通过；是全后端组装包，不是新 release build。

全新 profile、真实公开 OKX REST/WS，无市场库 seed、无响应替换；仅隔离进程使用既有本地 HTTP proxy，未改用户网络配置。45m/90m 首开及显式左翻页 → 1m/5m（每图 500 根）→ 释放/重建 45m/90m → 保存、完整退出、重启恢复。累计 **4483 根已收盘 K 线九字段**与 strict canonical range 比对通过；三个阶段记录实际来源帧，两个完整退出记录分别包含 9/10 个进程。截图已直接检查，图表已绘制；右侧其他行情面板仍有连接/准备状态，未将其计为本批验收。

`native-stream-receipt-path` 从既有 storage health 读取到真实 fetcher `payload_kind=receipt`，证明默认生产路径采用新 API；当时最后任务为 1 行，不把它当作大页内存资格。大页/多页由受控和真实 CCXT loopback 分别证明。

首轮在历史比对后因 QA 脚本查错 cache diagnostics 入口而失败，且包 revision 参数手误；原包文件未变。`ordinary-attempt1` 与说明保留。增加包 manifest/source revision 检查后曾因脚本路径层级错误在启动前失败（driver2.log），随后修正，最终全新 profile 的完整流程通过（driver3.log）。

`archive.py` 只遮蔽临时字符串 contextToken，保留数值 active_read_tokens。`evidence-index.json`、`source-hashes.json`、包 manifest、完整日志/XML/回执可复核；原 profile/app、SQLite 与失败截图继续保留在隔离 worktree 的 output。
