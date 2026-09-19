# 第五轮：保留完整成本分析，减少空操作

继续基于 `172ae4dd` 和前四轮未提交修改工作，未提交、合并或部署。

## 改动与适用范围

双时钟成本敏感性分析的四个内部执行账户，现在仅在存在活动订单时进入撮合函数；固定资金费功能未启用时，不再逐事件调用立即返回的资金费入口。

此优化只作用于内部创建、没有外部回调或状态恢复的分析账户。它们仍逐事件更新价格/持仓估值所需状态、验证账户、接收历史资金费和标记价格事件、处理完整行情序列。行情价格和数量即使在没有订单时也由 K 线构建器校验。启用固定资金费时仍按原时钟结算，不会因没有活动订单而跳过持仓资金费。

默认开关 `BACKTEST_PRUNED_DUAL_SENSITIVITY_ENABLED=1`；设为 `0` 恢复上一轮共享时钟路径的调用方式。若已选择 `cost_sensitivity_mode=SKIP`，本轮优化不会额外生效。

所有四个附加成本场景、金融结果、场景哈希和完整报告保留。没有更改检查点策略、默认功能、SDK 或数据库格式。

## 验证

新增测试比较开启/关闭优化的完整成本矩阵，覆盖旧账户/V2 账户、活动订单索引开启/关闭、资金费开启/关闭及混合订单。原有敏感性测试继续覆盖历史资金费、标记价格、延迟、订单结束策略、行情缺口和错误输入。

专门的无订单测试中，100 条行情的四场景合计撮合调用从 400 次减到 0，关闭资金费时对应入口也从 400 次减到 0，完整成本矩阵一致；负价格、负数量仍拒绝执行。

## 完整服务配对基准

保持之前优化开启、完整成本分析和周期检查点开启，仅交替本轮开关。每次 100,000 条合成聚合成交、内置 SMA 3/5；每 1,000 条行情保存检查点。高交易量每根 K 线 10 条行情，低交易量每根 K 线 100 条。每组各 3 对，第二对先运行优化路径。

计时包括 worker、策略、撮合、完整敏感性分析、检查点和报告持久化；不含导入、HTTP 和浏览器。不与测试并行。每对比较完整 result 和 report。

```powershell
$env:PYTHONPATH='backend;packages/candlescope-plugin-sdk/src;packages/candlescope-backtest-sdk/src'
python -m scripts.benchmark_trade_strategy --round5 --events 100000 --pairs 3 --output docs/performance-evidence-20260919/round5-dual-100k.json
python -m scripts.benchmark_trade_strategy --round5 --events 100000 --prints-per-bar 100 --pairs 3 --output docs/performance-evidence-20260919/round5-sparse-dual-100k.json
```

诊断记录 `performance-evidence-20260919/round5-profile-before.json` 是附带测量开销的 spawned-worker 分段耗时，用于定位工作，不作为无测量开销的延迟基准。所有结论限于本地合成数据服务端样本，不代表真实交易所全量数据或浏览器性能资格。

## 测量结果

| 负载 | 配对 | 优化关闭 | 优化开启 | 耗时降幅 |
|---|---|---:|---:|---:|
| 2,219 fills | 1 | 5.017 s | 4.465 s | 10.99% |
| 2,219 fills | 2 | 4.635 s | 4.496 s | 3.00% |
| 2,219 fills | 3 | 4.738 s | 4.199 s | 11.37% |
| 219 fills | 1 | 2.913 s | 2.574 s | 11.66% |
| 219 fills | 2 | 3.032 s | 2.521 s | 16.87% |
| 219 fills | 3 | 2.968 s | 2.818 s | 5.04% |

中位耗时：

- 2,219 fills: 4.738 -> 4.465 s (5.75% lower)
- 219 fills: 2.968 -> 2.574 s (13.28% lower)

六对完整 result/report 全部一致。中位数的降幅与逐对降幅不是同一统计量；只比较本轮数据，不与上一轮绝对耗时相除。

最终回归 **292 passed**，无失败、错误或跳过，4 条已有 FastAPI 弃用警告。Ruff 与 `git diff --check` 通过。证据：`performance-evidence-20260919/round5-regression.xml`、`round5-validation.json`。
