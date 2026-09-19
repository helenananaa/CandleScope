# 策略研究：复用成交行情准备结果

## 结果与范围

本轮将有容量上限的成交快照缓存接入实际 `BacktestWorker`。同一 Worker 上重复研究同一冻结数据集时，复用已读取、投影的行情数据；每个回测仍得到独立对象，独立执行策略、撮合、账户和成本敏感性计算。

100,000 笔合成成交通过真实 Parquet 归档运行完整受监督策略回测服务。每批先运行一次持续持仓且保留两个挂单的策略，再运行三个 SMA 参数组合。首次构建缓存的成本计入整批耗时。三组交替开关的对照如下：

| 对照 | 关闭缓存（秒） | 开启缓存（秒） |
| --- | ---: | ---: |
| 1 | 28.151 | 25.073 |
| 2 | 26.382 | 23.152 |
| 3 | 27.489 | 23.375 |
| 中位数 | 27.489 | 23.375 |

整批中位耗时减少约 15.0%。后续参数任务的行情读取和投影阶段中位耗时从 1.612 秒降到 0.351 秒（减少约 78.3%）；首次准备从 1.533 秒增加到 2.109 秒。因此适用于重复试验，不能据此宣称单次回测加速。每次冻结归档的成本依然存在。

三组对照使用相同运行身份，完整 result、report、chart cache 逐项相等。持仓样例结束时仓位为 1，两个挂单仍有效；参数组各有 219 次成交。证据见 [配对基准](performance-evidence-20260919/prepared-research-paired.json)。

数据为合成行情，归档中的来源字段是测试夹具元数据，不是 Binance 实际市场数据或真实来源验证。测试覆盖真实 Parquet、生产行情加载方法及受监督执行服务，未运行完整队列入口，也不构成实际市场、浏览器或部署验收。

## 为什么选择这一改动

[原始分阶段基准](performance-evidence-20260919/structural-baseline.json) 显示：每个任务冻结归档约 1.5–1.7 秒，读取和投影约 1.8–1.9 秒，总计约占端到端耗时的一半。多参数研究重复支付这部分成本，因此先复用行情准备结果。

缓存键使用归档实例及完整冻结数据集身份，包含范围、epoch 和对象身份。运行时仍重新冻结数据集并校验任务身份，每次缓存读取仍通过 pin 验证源文件校验和。资金费率与合约事件仍在加载后按原流程合并。

缓存只保留内部生成的序列化字节，不接收磁盘或网络上的 pickle。恢复出的事件与 payload 不共享可变对象；首次调用者修改对象也不会污染缓存。相同身份的并发请求合并首次读取；失败不进入缓存。容量不足时正常读取但不保留，关闭 Worker 时清空缓存。

每个 Worker 最多缓存两个数据集，字节上限取 64 MiB 和配置 worker_memory_mb 的八分之一中的较小值。本基准保留 8,949,799 字节。该上限约束保留的序列化字节，不代表整个进程或并发反序列化的峰值内存限制。超过容量的数据集不会获得缓存收益。

默认开关为 `BACKTEST_TRADE_SNAPSHOT_CACHE_ENABLED=1`，设为 `0` 可退回原加载路径。仅改动当前本地工作树，未部署。此前 round7 的历史 JSON 复用和 round9 的已完成图表 K 线复用仍默认关闭。

## 下一步热点

新增计时器分别记录策略回调、撮合和资金费处理。[持仓样例诊断](performance-evidence-20260919/structural-cached-diagnostic-held_resting-stages.json) 中，撮合累计约 0.961 秒，成本敏感性约 1.275 秒，检查点约 0.394 秒，策略回调约 0.014 秒。[第一参数组诊断](performance-evidence-20260919/structural-cached-diagnostic-parameter_1-stages.json) 中，检查点约 0.964 秒，策略回调约 0.028 秒。

这些是含子调用的计时，彼此重叠且有计时器开销，不能相加或直接当作无计时器基准。它们说明后续应分别考察长期挂单的撮合扫描、频繁成交下的检查点持久化，以及仍每次发生的归档冻结。不能从这些内置策略样例推断所有用户策略的计算成本，也尚无证据承诺原生内核或其他结构改造的倍数收益。

## 验证与复现

专项测试覆盖对象隔离、源文件复核、事件预算、容量和淘汰、归档身份隔离、并发合并、失败后重试、关闭清理，以及真实 Parquet 文件损坏后的命中拒绝。回归结果及当前源文件哈希见 [验证记录](performance-evidence-20260919/structural-validation.json)。

PowerShell 在工作树根目录运行：

```powershell
$env:PYTHONPATH='backend;packages/candlescope-plugin-sdk/src;packages/candlescope-backtest-sdk/src'
python -m scripts.benchmark_prepared_research --events 100000 --trials 3 --pairs 3 --output docs/performance-evidence-20260919/prepared-research-paired.json
python -m scripts.benchmark_strategy_research --events 100000 --trials 3 --profile --cache --output docs/performance-evidence-20260919/structural-cached-diagnostic.json
```
