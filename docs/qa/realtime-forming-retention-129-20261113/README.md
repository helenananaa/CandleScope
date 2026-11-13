# R129 首个实时前缀、删除权限与当前包证据

基线 main `00be4ce845134b11154633b1f0e258f2bce4ccd4`；首候选 `0a986b723096f481c50da5843c1b6010fc0314e8`；最终产品 `06ffa00f2be647b97e077d60a99b630145fb4b93`。第二候选为8f9089；Intel失败后补足原生提交屏障，重新组装最终产品并复跑。工作在独立 worktree，未修改用户的前端/设计工作区。#126/#127/#129 保持开放，#130 已有的关闭状态不变。

## 产品行为与边界

从空桶开始的纯实时大周期，过去直到目标收盘才会退休全部原组成：活动接缝推进要求已有 H127 prefix，首次 warm-start 不足2048项则从未进入该路径。现在合格的默认 COMPONENT、固定 epoch 目标至少2048、至多65536个源槽，在接纳128条源确认组成后，可建立首个 prefix。沿用原 `HistoryPrefixRuntime`、timeout loop、H127/B130/D126、writer 和预算；没有新增平行源缓存、修订账本、timer 或后台任务。

原 closed 元数据队列扩为单个 `component_jobs`，closed/forming 共用128项容量、每项1KiB，一轮最多一项；运行时诊断和内部入口改为 `component_jobs` / `component_job_inflight` / `drain_components`。`BAR_AGG_COMPACT_FORMING_COMPONENTS=false` 禁用新的首个实时前缀维护；已有 prefix 的接续/修正仍走既有合同。closed 的既有回退开关独立保留。

首批仅取桶起点的128个不可变接纳值，逐条确认已闭合、相邻、完整源网格；缺少第一个槽、不相邻、未知字段、相抵修正、未落库、资格/工作预算失败均不退休原值。原 dispatcher drain 后，在目标锁外 stage 有界 canonical prefix 和逐条读回，随后在原锁内重新检查 D126 与将被退休叶子的对象身份、owner/epoch/配置/策略/存储/预算绑定，核对当前九字段、能力、计数及输入时间投影。同期 forming 尾部可接纳更新；不会因整个 preview version 增加而必然拒绝正确维护。

采用保留状态/最终性、时间、原 acquisition/delete floor 和三种水位，不增加事件或规范写入。dirty 尾部在原 owner 内物化后仍由原 deadline 发布最新版本，不把计算当成成功发布。完整原索引/证明在物理读取与取消排空期间计量；采用时的 probe、快照及剩余 overlay 另预留工作。失败按一批源进度退避；不承诺预算/来源失败下仍具备128条硬上界。

另修复三个完整基线可复现的删除权限错误：形成中旧前缀恢复、已确认接缝推进、再次 warm-prefix 采用，均可能在内容修订前进/最后 raw leaf 退休后忘记原权限 floor，使此前显式删除的7m目标重新落库。保护放在统一 `BarAggregator.adopt_history_prefix` 入口：新 canonical 内容的 acquisition 可以前进，原 `canonical_recovery_delete_floor` 单独保留；原 D126 事务拒绝重新创建已删除目标/基础源。没有新增删除或写入旁路。

## 验证与保留失败

新增29项合同：25项 forming/owner合同纳入四平台host；2项真实 pinned CCXT OKX来源回执，以及2项原持久dispatcher多页/错误合同纳入完整后端集成。

- 生产2048门槛/128接缝/10007m目标：从空桶建立首个128前缀，261次真实默认 DataManager callback/router/bridge/SQLite 接纳后继续推进到256，保留5条尾部；旧首叶减量/极值修正正确。
- 失证、相抵修正、字段能力、缺失、未收盘、预算/开关、重复输入不逐次重试；保留原值和原事件。
- 页读期间同桶尾部更新在1秒限制内完成；退休叶子并发更换、取消、关闭 runtime、解绑/同身份重绑、配置/策略/实例方法/存储更换不能晚采用。取消/解绑等待物理读，预算和载荷可回收。
- 正在读取的 forming 桶关闭时，旧维护不删除后续 closed 待办，下一轮可完成原 closed 维护。
- 原 timer 在没有新输入时自动建立首个前缀；dirty-tail 的原预览 timer 最终发布最新值，保持输入/计算/发布水位与 pending 回收。
- 三个权限回归在完整旧后端 `00be4ce` 均实际观察到被删除目标重新存在于 SQLite；修订后拒绝重建。源删除保留 gap/provisional，不伪装完整。
- 真实 pinned OKX WS/REST 解析、SourceJournal 回执、原持久 dispatcher：首个 prefix 和旧叶修正均等待 native commit；不是仅用 fake storage 证明接线。

最终产品本地完整 CCXT integration：**2247 passed / 66 warnings**，架构检查通过。提交屏障及原确认单项选集18项通过，forming/真实回执/原接缝选集40项通过。较早的2243/2244集合不是最终产品资格。

早期云端 `feb65f08` 的新正向用例未等原 native dispatcher 排空即要求可选维护成功，Linux/ARM失败而生产正确保留raw；夹具补了pending=0。随后 `b3272232` 的后端2244及前端、Linux/ARM/Windows host通过（各386/1 skip/1 warning），但 **Intel失败22项**：21项新用例一次突发128条真实SQLite提交后等5秒排空超时，另有原接缝测试修订冲突。完整原日志保留，未宣称Intel通过，未合入该head。

修订明确分开两个原因：正向维护夹具现在逐项等待原native交付边界，保留5秒单项等待及所有值/事件/状态断言，不把128事务的突发吞吐当维护准入门槛。另以真实pinned回执+原dispatcher gate，在完整旧候选复现**新收盘tail位于前缀外时未等待native commit**；该提交仍会改变前缀依赖的source-series revision并使读回失效。生产现在对已有prefix的任何closed输入先在原1.5秒期限内等待原owner边界。原flush只处理64条，新增的flush_pending复用同一dispatcher循环处理有限页面直至pending=0，错误/重绑明确失败，原持久回执保留；没有新timer、writer、队列或限额上调。130项真实SQLite多页与失败保留分别验证，非吞吐基准；形成中输入不新增该收盘屏障。

本批最终27项forming/回执合同和2项原dispatcher合同共29项；完整2247覆盖它们。直接从repo根运行旧ack子进程用例曾遇import app路径错误，改回其规定backend cwd，18项通过；夹具count_bars调用缺少范围参数的本地错误同样保留。
所有失败保留：initial 的同步 callback 被 await、原 timer 与手动 drain 抢同一维护任务；controlled 的物理读取启动前原 native dispatcher 尚未处理完受控积压；focused 的未收盘 fixture 却等待128根已收盘规范行（应127），以及形成中原 floor 缺口；首版6m fixture实际默认选3m，改为与输入1m相符的7m。首候选虽修复恢复路径，后补 rollover/warm-refresh 两项仍准确复现 SQLite 重建，最终移到统一采用入口。没有移除断言、提高生产限额或调整生产恢复超时。

## 同输入成本

`cost.py`：完整旧后端、最终禁用、最终启用，各独立进程；2048m/1m 和10007m/1m，构造相同128条已确认输入。前127项直接受控接纳和规范批写在计时窗外，最后一项走默认 DataManager 真实 callback/router/bridge/native writer。暂停原 timeout task 以区分输入返回和同一维护入口；自动 timer 另有测试。每组一次热身、3次 CPU/墙钟采样、一次独立 tracemalloc，所有30个 trial 的事件与规范行九字段/时间/source 哈希跨模式相同，结束 reserved=0。

| 指标 | 旧2048m | 新禁用2048m | 新启用2048m | 旧10007m | 新禁用10007m | 新启用10007m |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 输入回调 CPU 中位 ms | 24.951 | 35.365 | 31.158 | 25.442 | 30.546 | 30.487 |
| 独立维护 CPU 中位 ms | 0.005 | 0.006 | 52.766 | 0.007 | 0.005 | 55.751 |
| 原组成数量 | 128 | 128 | 0 | 128 | 128 | 0 |
| 状态可达图字节 | 154050 | 154050 | 3869 | 154051 | 154051 | 3870 |
| 所有登记 owners 去重可达图字节 | 172512 | 172512 | 31499 | 172513 | 172513 | 31460 |
| B130 entries | 0 | 0 | 8 | 0 | 0 | 8 |
| 分配 peak 字节 | 104315 | 104315 | 612530 | 104323 | 104323 | 619158 |

包含新增公共块、owner 元数据和全部登记根，去重保留图约降82%；维护另付53–56ms CPU，分配峰值约5.9倍。输入回调也有额外开销，未宣称总CPU下降。原状态在 tracemalloc 开始前已驻留，分配peak不含它；也不包括所有SQLite/分配器/plugin进程内存。机器有并行CI/原生/成本进程，未冻结负载，不能据此通过RSS、稳定P95/P99、长稳态或整体性能验收。source hashes 在测量前后冻结；candidate1/candidate2 成本亦保留。

## 最终原生包

最终 app `06ffa00f2be647b97e077d60a99b630145fb4b93`，保留 frontend/runtime/plugins build `ef8f0e0fa6df299a823f4460b701eb1c3c98361f`，覆盖全部1002个 tracked backend app 文件；源码/asar/前后 strict signature 通过。这是全后端覆盖的 macOS arm64 组装资格，不冒充重新构建前端的 release build。

两独立空profile、真实公开OKX，无seed、响应替换、bootstrap hook或额外消费者；仅隔离进程使用既有本地proxy。45m/90m首开→显式左翻页各至少500→1m/5m各500→释放/重建→保存/完整退出/重启。ordinary 累计4578根闭合九字段，witness累计5742根；后者还捕获真实2m收盘、原timer退休2个组成并独立比较闭合图表/canonical九字段，再恢复45m/90m。四次10/10进程树退出，七张最终截图直接检查。截图中部分实时/盘口仍处连接或等待状态，未计为全行情稳定无断线通过。

首候选 ordinary 通过，witness 首次显式左翻页收到 applied 后仍停129根，120秒门槛失败；截图、traffic/diagnostics、进程日志和完整 profile/app 保留，退出已确认。此仍属 #127 冷历史/翻页与长期稳定待核销范围，未声称统一权限修正解决该翻页问题。随后权限修正的candidate2两套空profile也通过；Intel暴露问题后新增原提交屏障，最终06ffa再次全量组装、两套全新profile通过。三代包/回执均保留，没有用失败profile暖库继续算冷启动通过。一次driver工具路径日期拼写错误在app启动前失败，修正路径后仍用未创建profile的新运行，原bootstrap日志保留。

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

此前产品的独立 SourceJournal-only 冷恢复探针已通过：2m目标重启后首叶 quote 修正1010→1008，native 1m规范行0、2m行1、quote_volume=2018、source_snapshot_verified。原生canonical不是这项现有恢复合同的必要条件；未来有界化必须保留它。该受控探针无网络，不计新的有界恢复实现完成。
