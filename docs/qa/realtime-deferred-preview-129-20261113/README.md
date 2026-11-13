# R129：接纳之后的延迟预览计算

基线 main `8a85612d107dae02c733b4416241c901e9252735`。首个产品候选 `e9c0a761e865aed6ea2f77f3d7b5d1aa12542a9a`；真实来源接线修订 `b70d7924e`。最终包的全部后端文件与 checkout 逐一校验，后续提交只补文档、脚本和证据。

本批补 #129 的按需计算、水位与有界 deadline，并消费 #126 预算和既有 H127 来源围栏。#129/#126/#127 原始关闭条件保留；#130 已完成的公共数学、共享块、修订账本和持久 writer 不重复建设。

## 生产行为

每个输入仍对紧邻的已接纳值执行 freshness 检查，更新原有不可变组成索引。只有合格固定网格、默认 COMPONENT、同一 forming 尾部的重复累计快照延迟 K130 汇总及投影；不是只在 publisher 丢事件。没有在接纳之前保留最后一条原始帧，也没有第二份来源缓存或累计器。

既有 publisher 的有效刷新时机触发计算；正在进行的发布完成后唤醒后续工作。关闭、修正、新组成、新桶、读取/复制/转换等必要屏障先完成计算。要求逐次更新的消费者继续逐次计算，显式禁用 UPDATED 保留原合同。自定义策略、未启动引擎、不合格来源/身份/网格保持 eager。`BAR_AGG_DEFERRED_COMPONENT_PREVIEWS=false` 可回退。

单个原聚合循环最多 128 个 pending/in-flight 引用、一个 timer、一个 drain task，每轮最多 16 项。每项在原 realtime-state 预算预留 16 KiB；旧尾部和最新快照各有 8 KiB 资格限制。完成的 builder 不跨后续 await 滞留。解绑、取消、停止排空工作和物理读取，原内存 owner 仍计入 detached 在途状态。

真实 CCXT forming 输入携带 native source_ref。延迟发布复用现有 storage owner，在一个事务内检查至多 256 个已接纳组成、当前来源头、规范已闭合行、删除 floor 和目标修订；无回执的 warm-start 组成也要逐值验证。物理读在 history-query 中预留所持 immutable 图全重及 16 KiB，直到工作真正结束。正常来源先推进仅跳过旧预览，不请求修复；规范删除/修正使用原恢复 owner。输入版本、配置/来源/策略绑定和目标代次围栏阻止旧读结果发布或触发旧代恢复。更大的带回执窗口走 eager；不承诺所有长尾都使用此优化。

`preview_input_version / preview_computed_version / preview_published_version` 是 builder 内的接纳、计算和成功 publisher fanout 水位，不是 DB revision、传输 sequence 或消费确认。公开 cache diagnostics 最多列出 128 个活动水位及截断标志，读取诊断不触发计算。架构合同见 `docs/architecture/KLINE_REVISION_CONTRACT.md`。

## 回归与原始失败

最终完整 CCXT integration：**2195 passed / 66 warnings / 247.63s**；架构检查通过。42 个新增测试包括 31 个低层、2 个默认 DataManager、3 个真实 H127/SQLite 和 6 个真实 pinned CCXT OKX source receipt 用例。CI selector 包含全部；stock Pine host 仅添加不要求 fork 的三个文件。

覆盖接纳前合并反例、无后续源帧时的真实 timer、读回最新值、close/amend/new-component/new-bucket、逐次消费及需求移除、共享四周期、显式禁用输出、容量/预算/自定义策略回退、公平排空、在途发布完成唤醒、错误/取消/解绑/重建、配置/策略/来源重绑、回调寿命与内存计量。真实来源用例包括源头抢先推进、删除、外部 SQL 修正、物理读取期间取消和解绑；规范 close 沿原 writer 读回。

保留 initial/initial2/initial3 的 fixture 参数错误、lifetime 的 slots weakref 错误、prefix 的独立预算 harness 错误、sources 的属性名错误，以及 sources2 中未等待异步闭合交付的失败。修正断言与接线后完整选集通过。早期 ci-initial/ci-final 分别 2181/2189 项，不能替代最后来源修订的 2195 项。

## 同输入计算与成本

`cost.py` 使用完整旧/新后端的独立进程：45m/15m、90m/30m 各 2 个种子，10007m/1m 的 10000 个种子，再输入 1024 个 forming 快照、收盘及必要余下组成。输入构造和种子在计时窗外；2 次热身、5 次 process CPU 采样，另一次 tracemalloc。原 router、数学和 publisher 执行；该组没有来源回执、数据库或网络。

| CPU 中位 ms | 旧完整后端 | 新 eager 回退 | 新 deferred |
| --- | ---: | ---: | ---: |
| 45m / 15m | 134.215 | 141.558 | 121.538 |
| 90m / 30m | 131.169 | 140.828 | 122.355 |
| 10007m / 1m | 133.361 | 147.522 | 121.380 |

三组全部计时 trial 的事件及最终投影哈希跨模式相同。forming 尾部实际 index replacement 从 1024 次降至 10 次；10007m 总计算 11031→10017（包含种子及必要屏障），最终三水位相等。10007m 独立 allocation peak 934673→706937 字节，最终原状态图约 11.39 MB，新增标量约 120 字节，最终 reserved=0。没有宣称消除了原全部组成保留。

`source-cost.py` 另测真实 fork OKX 解析结果、来源选择/持久 journal、默认 DataManager/router/bridge/SQLite/消费 bus。6 根可信种子、256 次 forming 累计观察和 close；解析 tape 在窗外，来源选择、原 ingestion callback、原 writer 与既有 source acknowledge 在窗内。受控 IngestionFactory 不建网络；显式 ack 使用原 source API，不是生产新增 owner。1 次热身、3 次计时、另一次分配采样。

| 来源回执突发输入 | 旧完整后端 | 新 eager 回退 | 新 deferred |
| --- | ---: | ---: | ---: |
| CPU 中位 ms | 1842.031 | 1894.007 | 1750.359 |
| 墙钟中位 ms | 1832.628 | 1888.956 | 1715.046 |
| 分配 peak 字节 | 299648 | 300863 | 193175 |
| 目标计算次数 | 未加计数 | 263 | 9 |
| 延迟接纳次数 | 0 | 0 | 255 |

全部正式计时和分配 trial 的消费事件哈希相同；8 根规范行九字段/边界/source 哈希、257 版本来源头一致。热身的异步消费时机差异原样保留，不拿热身当正式样本。虚拟输入时间只推进 256ms，低于该组 1000ms 限流，因此计时窗没有 deadline 来源读取；不能把这组 CPU 当包含定时验证成本的稳态收益。该成本与来源 supersession 在下面真实原生见证中确实发生，仍需单独完整负载测量。

所有成本组都在未冻结的开发机器上采样，有并行 QA，旧/新分时运行；不构成 RSS、P95/P99、全应用 CPU、来源网络或长时资格。eager 回退开销也保留，不用大输入的改善掩盖普通路径成本。早期成本和完整失败记录均归档。

## macOS arm64 原生证据

保留 frontend/runtime/plugins build `ef8f0e0fa6df299a823f4460b701eb1c3c98361f`，覆盖全部 **1002** 个 tracked backend app 文件。前后逐文件及 asar 哈希、严格签名通过。这是完整后端覆盖的组装资格，不是新 release build。

最终两个独立全新 profile，真实公开 OKX REST/WS，无 seed、无响应替换、无 bootstrap hook 或额外观察订阅，仅隔离进程使用既有本地 proxy。45m/90m 首开和显式向左分页至每图至少 500 根 → 1m/5m 各 500 根 → 释放/重建目标 → 保存/完整退出/重启。常规 250ms 配置累计 **4452** 根已闭合九字段通过，独立 10000ms 观察配置累计 **5263** 根通过；三个阶段均记录实际来源帧。四次进程树退出均为 10/10；截图直接查看，双图均已绘制。

10000ms 运行只调整既有进程配置、读取公开 diagnostics。首开、重建、重启都捕获同一个 forming 桶 input>computed 的 dirty 状态，随后 computed/published 至少追上该已观察输入，且 scheduler 的定时 published 计数增加。初始及重建阶段累计 9 次 source read checks，其中 5 次正常 supersession 被跳过、4 次成功 deadline 发布、0 次失败；重启后独立再次通过。这证明真实来源采用新路径，不是独立 forming 数值 oracle、消费确认或每个网络 tick 交付证明。没有新帧的末值发布由真实 timer 单测单独验证。

首个 e9 候选常规闭合流程通过但形成中来源回执不合格，原生 dirty 见证失败。修复生产接线后，首次 b70 观察运行在一次左翻页后只有 246/132 根，未达到 500，完整失败及 10/10 退出保留。最后脚本使用最多 8 次公开 loadMoreLeft 并逐次确认进展，不降低 500 门槛；不冒充自动首屏/一次分页/自动深历史资格。最终流程的短暂 reconnect、准备中盘口和 warmup 工作保留在截图/日志；不计为全行情面板或持续无断线验收。

`archive.py` 归档所有候选/尝试、XML、成本、回执与失败截图，只遮蔽临时字符串 contextToken，保留数值 active_read_tokens。`source-hashes.json` 和 `evidence-index.json` 可复核；原 app/profile/SQLite 均保留在 worktree 的 output。

## 仍需完成的关闭条件

#129 的 closed/no-prefix 状态窗口及窗口外重建、所有语义屏障/消费者与来源资格、完整多目标长时资源/调度矩阵、独立 forming 数值及指标/策略运行资格继续。更大 native receipt 窗口仍明确回退，未证明所有目标有硬内存上界。#126/#127 的其他 writer/read、预算、归档载荷和首屏调度等按原 issue 条件继续。此批足以交付按需预览阶段，尚不足以关闭整个议题。
