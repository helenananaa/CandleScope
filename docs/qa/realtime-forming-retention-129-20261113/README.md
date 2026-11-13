# R129 首个实时前缀、删除权限与当前包证据

基线 main `00be4ce845134b11154633b1f0e258f2bce4ccd4`；首候选 `0a986b723096f481c50da5843c1b6010fc0314e8`；最终产品 `8f9089dd803c751cc0b437c430d6603582395980`。后补 dirty-tail 合同和证据归档不改变 app 源码。工作在独立 worktree，未修改用户的前端/设计工作区。#126/#127/#129 保持开放，#130 已有的关闭状态不变。

## 产品行为与边界

从空桶开始的纯实时大周期，过去直到目标收盘才会退休全部原组成：活动接缝推进要求已有 H127 prefix，首次 warm-start 不足2048项则从未进入该路径。现在合格的默认 COMPONENT、固定 epoch 目标至少2048、至多65536个源槽，在接纳128条源确认组成后，可建立首个 prefix。沿用原 `HistoryPrefixRuntime`、timeout loop、H127/B130/D126、writer 和预算；没有新增平行源缓存、修订账本、timer 或后台任务。

原 closed 元数据队列扩为单个 `component_jobs`，closed/forming 共用128项容量、每项1KiB，一轮最多一项；运行时诊断和内部入口改为 `component_jobs` / `component_job_inflight` / `drain_components`。`BAR_AGG_COMPACT_FORMING_COMPONENTS=false` 禁用新的首个实时前缀维护；已有 prefix 的接续/修正仍走既有合同。closed 的既有回退开关独立保留。

首批仅取桶起点的128个不可变接纳值，逐条确认已闭合、相邻、完整源网格；缺少第一个槽、不相邻、未知字段、相抵修正、未落库、资格/工作预算失败均不退休原值。原 dispatcher drain 后，在目标锁外 stage 有界 canonical prefix 和逐条读回，随后在原锁内重新检查 D126 与将被退休叶子的对象身份、owner/epoch/配置/策略/存储/预算绑定，核对当前九字段、能力、计数及输入时间投影。同期 forming 尾部可接纳更新；不会因整个 preview version 增加而必然拒绝正确维护。

采用保留状态/最终性、时间、原 acquisition/delete floor 和三种水位，不增加事件或规范写入。dirty 尾部在原 owner 内物化后仍由原 deadline 发布最新版本，不把计算当成成功发布。完整原索引/证明在物理读取与取消排空期间计量；采用时的 probe、快照及剩余 overlay 另预留工作。失败按一批源进度退避；不承诺预算/来源失败下仍具备128条硬上界。

另修复三个完整基线可复现的删除权限错误：形成中旧前缀恢复、已确认接缝推进、再次 warm-prefix 采用，均可能在内容修订前进/最后 raw leaf 退休后忘记原权限 floor，使此前显式删除的7m目标重新落库。保护放在统一 `BarAggregator.adopt_history_prefix` 入口：新 canonical 内容的 acquisition 可以前进，原 `canonical_recovery_delete_floor` 单独保留；原 D126 事务拒绝重新创建已删除目标/基础源。没有新增删除或写入旁路。

## 验证与保留失败

新增26项合同：25项无需 fork，四平台 host 选集纳入；1项真实 pinned CCXT OKX 来源回执，纳入完整后端集成。

- 生产2048门槛/128接缝/10007m目标：从空桶建立首个128前缀，261次真实默认 DataManager callback/router/bridge/SQLite 接纳后继续推进到256，保留5条尾部；旧首叶减量/极值修正正确。
- 失证、相抵修正、字段能力、缺失、未收盘、预算/开关、重复输入不逐次重试；保留原值和原事件。
- 页读期间同桶尾部更新在1秒限制内完成；退休叶子并发更换、取消、关闭 runtime、解绑/同身份重绑、配置/策略/实例方法/存储更换不能晚采用。取消/解绑等待物理读，预算和载荷可回收。
- 正在读取的 forming 桶关闭时，旧维护不删除后续 closed 待办，下一轮可完成原 closed 维护。
- 原 timer 在没有新输入时自动建立首个前缀；dirty-tail 的原预览 timer 最终发布最新值，保持输入/计算/发布水位与 pending 回收。
- 三个权限回归在完整旧后端 `00be4ce` 均实际观察到被删除目标重新存在于 SQLite；修订后拒绝重建。源删除保留 gap/provisional，不伪装完整。
- 真实 pinned OKX WS/REST 解析、SourceJournal 回执、原持久 dispatcher：首个 prefix 和旧叶修正均等待 native commit；不是仅用 fake storage 证明接线。

最终 app 的本地完整 CCXT integration：2243 passed / 66 warnings，随后仅补 dirty-tail 合同，单项通过。架构检查通过；最后26项会在最终远端 head 全部纳入完整集成。首轮云端 Linux/ARM 的新正向测试在原 native dispatcher 尚未排空时断言必须成功（Linux 为读视图失效，ARM 同一断言 detail 为空）；生产正确保留原组成，Windows 同 head 386项通过。修正测试前置条件：等待原 native canonical 数量和 durable pending=0，再要求可选维护成功；没有删除/放宽断言、重跑失败head或修改生产deadline。修正后26项本地全部通过，原始云端失败日志保留。产品 app 仍完全等于8f9089，无需把测试夹具修正冒充产品或原生重跑。首次较早完整选集2237项通过，不冒充最终完整集合。首候选52项相关合同通过；扩大到全部prefix时95通过/1失败为测试仅取新 acquisition、未取更旧 permission floor，已纠正比较定义，保留实际防复活断言。

所有失败保留：initial 的同步 callback 被 await、原 timer 与手动 drain 抢同一维护任务；controlled 的物理读取启动前原 native dispatcher 尚未处理完受控积压；focused 的未收盘 fixture 却等待128根已收盘规范行（应127），以及形成中原 floor 缺口；首版6m fixture实际默认选3m，改为与输入1m相符的7m。首候选虽修复恢复路径，后补 rollover/warm-refresh 两项仍准确复现 SQLite 重建，最终移到统一采用入口。没有移除断言、提高生产限额或调整生产恢复超时。

## 同输入成本

`cost.py`：完整旧后端、最终禁用、最终启用，各独立进程；2048m/1m 和10007m/1m，构造相同128条已确认输入。前127项直接受控接纳和规范批写在计时窗外，最后一项走默认 DataManager 真实 callback/router/bridge/native writer。暂停原 timeout task 以区分输入返回和同一维护入口；自动 timer 另有测试。每组一次热身、3次 CPU/墙钟采样、一次独立 tracemalloc，所有30个 trial 的事件与规范行九字段/时间/source 哈希跨模式相同，结束 reserved=0。

| 指标 | 旧2048m | 新禁用2048m | 新启用2048m | 旧10007m | 新禁用10007m | 新启用10007m |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 输入回调 CPU 中位 ms | 24.951 | 34.858 | 32.007 | 25.442 | 29.335 | 35.771 |
| 独立维护 CPU 中位 ms | 0.005 | 0.005 | 46.992 | 0.007 | 0.005 | 43.479 |
| 原组成数量 | 128 | 128 | 0 | 128 | 128 | 0 |
| 状态可达图字节 | 154050 | 154050 | 3869 | 154051 | 154051 | 3870 |
| 所有登记 owners 去重可达图字节 | 172512 | 172512 | 31499 | 172513 | 172513 | 31460 |
| B130 entries | 0 | 0 | 8 | 0 | 0 | 8 |
| 分配 peak 字节 | 104315 | 97863 | 612362 | 104323 | 101139 | 612082 |

包含新增公共块、owner 元数据和全部登记根，去重保留图约降82%；维护另付43–47ms CPU，分配峰值约5.9倍。输入回调也有额外开销，未宣称总CPU下降。原状态在 tracemalloc 开始前已驻留，分配peak不含它；也不包括所有SQLite/分配器/plugin进程内存。机器有并行CI/原生/成本进程，未冻结负载，不能据此通过RSS、稳定P95/P99、长稳态或整体性能验收。source hashes 在测量前后冻结；candidate1 成本亦保留。

## 最终原生包

最终 app `8f9089dd803c751cc0b437c430d6603582395980`，保留 frontend/runtime/plugins build `ef8f0e0fa6df299a823f4460b701eb1c3c98361f`，覆盖全部1002个 tracked backend app 文件；源码/asar/前后 strict signature 通过。这是全后端覆盖的 macOS arm64 组装资格，不冒充重新构建前端的 release build。

两独立空profile、真实公开OKX，无seed、响应替换、bootstrap hook或额外消费者；仅隔离进程使用既有本地proxy。45m/90m首开→显式左翻页各至少500→1m/5m各500→释放/重建→保存/完整退出/重启。ordinary 累计4578根闭合九字段，witness累计5739根；后者还捕获真实2m收盘、原timer退休2个组成并独立比较闭合图表/canonical九字段，再恢复45m/90m。四次10/10进程树退出，七张最终截图直接检查。截图中部分实时/盘口仍处连接或等待状态，未计为全行情稳定无断线通过。

首候选 ordinary 通过，witness 首次显式左翻页收到 applied 后仍停129根，120秒门槛失败；截图、traffic/diagnostics、进程日志和完整 profile/app 保留，退出已确认。此仍属 #127 冷历史/翻页与长期稳定待核销范围，未声称统一权限修正解决该翻页问题。随后因另外发现并修复权限 bug，最终产品重新组装，两套全新profile独立复跑通过；没有用失败profile暖库继续算冷启动通过。

原生小周期没有触发2048/128首次 forming 退休，其本体由受控生产接线、真实fork回执、并发和成本层分别证明；不替代长大桶原生/独立forming oracle/指标策略/所有来源与消费者/Windows与Intel桌面/长期资源矩阵。

## 复跑与剩余范围

在已安装固定 fork 和项目依赖的 Python 下：

```sh
python backend/scripts/ccxt_contracts/integration.py --timeout=90
python -B backend/scripts/check_architecture.py
python docs/qa/realtime-forming-retention-129-20261113/cost.py --source /absolute/complete/backend/tree --mode enabled --output /absolute/result.json
python docs/qa/realtime-forming-retention-129-20261113/prepare-native.py
CANDLESCOPE_PLAYWRIGHT_PACKAGE=/absolute/tooling/package.json CANDLESCOPE_QA_HTTP_PROXY=http://127.0.0.1:7897 CANDLESCOPE_AGGREGATION_DEEP_HISTORY=true CANDLESCOPE_AGGREGATION_NATIVE_OUTPUT=/absolute/fresh/output CANDLESCOPE_AGGREGATION_NATIVE_EXECUTABLE=/absolute/CandleScope.app/Contents/MacOS/CandleScope node docs/qa/realtime-forming-retention-129-20261113/native.mjs
```

`prepare-native.py` 的保留底包位置需指向已验证包；witness额外设置 `CANDLESCOPE_CLOSED_RETENTION_WITNESS=true`。输出目录必须是新profile，保留原失败与SQLite。`archive.py`校验最终1002文件/asar/签名，压缩回执与失败，只遮蔽临时字符串contextToken，不删除数值active_read_tokens；evidence-index列出SHA256。

#129 的 builder 已逐出后的有界完整窗口恢复仍未交付，尤其 SourceJournal-only、没有原生canonical的有效输入必须保留；不能拿H127代替该恢复合同。其他来源/网格/消费者、全部语义屏障、独立forming/指标/策略、长期CPU/RSS/延迟及退化/恢复矩阵继续。#126 全writer/read/归档与共同预算覆盖、#127 自动首屏与冷历史/调度/完整资源验收仍按各自原始标准推进。本批不关闭这些issue。

当前产品的独立 SourceJournal-only 冷恢复探针也已通过：2m目标重启后首叶 quote 修正1010→1008，native 1m规范行0、2m行1、quote_volume=2018、source_snapshot_verified。原生canonical不是这项现有恢复合同的必要条件；未来有界化必须保留它。该受控探针无网络，不计新的有界恢复实现完成。
