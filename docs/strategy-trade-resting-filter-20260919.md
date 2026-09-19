# 成交回测：提前排除未触价的普通限价单

本轮候选优化在 `_match` 中先排除当前成交价未触及的普通限价单，减少后续的延迟资格检查、参与率乘法和订单循环。仍逐笔处理行情、账户、资金费和策略。

IOC 单即使没有成交，也须走首次符合资格后的到期逻辑，因此不排除。STOP_LIMIT 的激活是可观察状态，保留原处理。候选订单保持原顺序，参与率、部分成交、OCO 取消和成交来源规则不变。有成交回调且存在候选订单时，保留完整原订单列表，允许回调修改同一笔行情中的后续订单；只有全部订单均不会触发时才整体跳过。

开关为 `BACKTEST_TRADE_RESTING_FILTER_ENABLED`，默认 `1`；设为 `0` 退回原撮合路径。未提交或部署。

## 最终版本的性能

100,000 笔预先准备的合成成交，五组交替开关对照，计入完整受监督服务执行、检查点与报告持久化，排除归档准备：

| 负载 | 关闭中位数（秒） | 开启中位数（秒） | 耗时减少 |
| --- | ---: | ---: | ---: |
| 持仓＋两个长期挂单 | 4.555 | 4.286 | 5.9% |
| SMA | 4.620 | 4.582 | 0.8% |

长期挂单五组均更快，各组减少约 4.5%–10.6%。SMA 三组更快、两组略慢（约 0.7% 和 0.05%），其收益很小，不宣称有稳定加速。所有对照的完整结果、报告和图表数据一致。

最终性能证据为 [五组执行对照](performance-evidence-20260919/resting-filter-final-execution-paired.json)。先前包含归档的三组对照和首轮执行对照发生于回调兼容性完善前，只保留为探索记录，不作为最终版本的性能验收。未将此前缓存收益与本轮收益简单相加。

## 验证范围

18 项专项等价测试覆盖原成交内核及双时钟内核、两种账户模型、两种执行模型、开关活跃订单索引、混合订单以及快照恢复；另验证未成交 IOC 仍到期、未成交 STOP_LIMIT 仍激活，以及成交回调在同一笔行情中修改后续限价单。完整回归及源文件哈希见 [验证记录](performance-evidence-20260919/resting-filter-validation.json)。

两类配对基准均逐项比较完整 result、report 和 chart cache，交替开关顺序：

- `resting-filter-paired.json`：真实 Parquet 存储的 100,000 笔合成成交，每批包含持仓和两个长期挂单，以及三个 SMA 参数组；行情缓存两侧均开启。
- `resting-filter-execution-paired.json`：预先准备的 100,000 笔合成成交，分别对照持仓挂单与 SMA 的受监督服务执行耗时，排除归档准备耗时。

第一类测量期间，未修改的归档冻结和读取阶段也发生明显波动，因此保留原始计时，不将单组升降归因于本次改动。两类行情都是合成数据，不构成真实市场、队列入口或浏览器验收。

## 复现

```powershell
$env:PYTHONPATH='backend;packages/candlescope-plugin-sdk/src;packages/candlescope-backtest-sdk/src'
python -m scripts.benchmark_prepared_research --events 100000 --trials 3 --pairs 3 --flag BACKTEST_TRADE_RESTING_FILTER_ENABLED --output docs/performance-evidence-20260919/resting-filter-paired.json
python -m scripts.benchmark_resting_filter --events 100000 --pairs 5 --output docs/performance-evidence-20260919/resting-filter-final-execution-paired.json
```
