# 第六轮：去掉最终结果汇总中被覆盖的哈希

继续基于 `172ae4dd` 与前五轮未提交修改工作；未提交、合并或部署。

双时钟内核原先先调用逐成交内核的 `result()`，生成决策、成交、账本和报告哈希，再加入双时钟计数并重新生成决策、账本和报告哈希。前一组中的三个哈希被覆盖，不参与后续计算。

现在对精确类型 `TradeSimulationKernel`，直接取 `_financial_result()` 财务数据并使用原订单编码器，仅计算最终结果需要的哈希。扩展内核子类仍走原来的 `result()`，保留其自定义行为。没有缓存结果，不会在恢复或状态改变后返回过期数据。

默认开关 `BACKTEST_DIRECT_DUAL_RESULT_ENABLED=1`，设为 `0` 可恢复原汇总方式。公开结果字段、快照、撮合规则、全部成本分析与报告哈希均保持一致。一次汇总中本层及内层显式哈希调用从 7 次降至 4 次。

## 证据和收益边界

- 新增测试覆盖空输入、有成交、旧/V2 撮合、流式决策开关、恢复后的结果与快照等价、子类兼容性，以及哈希调用计数。
- 10,000 条合成行情的混合订单负载产生 5,603 笔成交；固定内核状态，每次重复汇总 10 次，交替开关三对。该测试只计结果汇总，完整结果一致。
- 另以 100,000 条合成聚合成交、SMA 3/5、2,219 笔成交跑三对完整服务基准。保持全部前序优化、成本分析和检查点开启，仅交替本轮开关，完整 result/report 全部一致。

| 结果汇总微基准 | 关闭 | 开启 |
|---|---:|---:|
| 配对 1，10 次汇总 | 2.533 s | 1.794 s |
| 配对 2，10 次汇总 | 2.614 s | 1.809 s |
| 配对 3，10 次汇总 | 2.526 s | 1.689 s |

汇总阶段中位耗时降低约 29%。证据：`performance-evidence-20260919/round6-result-micro.json`。这不是完整回测的提速比例。

| 完整服务基准 | 关闭 | 开启 |
|---|---:|---:|
| 配对 1 | 4.854 s | 4.545 s |
| 配对 2 | 4.192 s | 4.436 s |
| 配对 3 | 4.216 s | 4.402 s |

完整服务中位耗时 4.216 → 4.436 秒，三对中两对略慢，没有稳定整体收益。不能仅以第一对样本宣称端到端提速；本轮只确认减少汇总开销。证据：`performance-evidence-20260919/round6-dual-100k.json`。

服务基准复现：

```powershell
$env:PYTHONPATH='backend;packages/candlescope-plugin-sdk/src;packages/candlescope-backtest-sdk/src'
python -m scripts.benchmark_trade_strategy --round6 --events 100000 --pairs 3 --output docs/performance-evidence-20260919/round6-dual-100k.json
```

微基准使用 `DualClockSimulationKernel('1m', execution_model_revision='EXECUTION_REALISM_V2', participation_rate=Decimal('0.03'))`，输入 `events(10000, 2)`，策略为测试夹具 `tests.test_trade_strategy_performance.mixed_orders`。先 `run(..., finalize=True)`，然后每对交替设置上述开关，计时 10 次 `result()`，在计时外验证结果完全相等。

所有测试为本地合成数据，不代表真实交易所全量数据、浏览器或生产环境性能。

最终回归 **302 passed**，无失败、错误或跳过，4 条已有 FastAPI 弃用警告。Ruff 与 `git diff --check` 通过。证据：`performance-evidence-20260919/round6-regression.xml`、`round6-validation.json`。
