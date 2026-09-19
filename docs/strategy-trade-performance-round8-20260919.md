# 第八轮：成交记录复用已有的安全扁平编码器

继续基于 `172ae4dd` 和前七轮未提交修改；未提交、合并或部署。第七轮 JSON 片段复用仍默认关闭，本轮基准也保持关闭。

## 定位与实现

第七轮的 cProfile 记录中，`dataclasses.asdict` 调用 60,038 次，递归编码与 deepcopy 是可见的热区。这是带剖析开销的诊断，不是实际延迟占比，也不能把嵌套计时相加。

BAR 内核已有 `_flat_record`：只有精确类型 `SimulatedOrder`/`SimulatedFill`，且每个字段均为精确类型的 str/int/bool/None/Decimal 时，直接构造新的字典。子类、自定义记录或含可变字段时回退到原 `asdict` 深复制。复用此已存在的实现，避免额外引入一套快速编码规则。

成交内核现在在完整快照、最终财务结果、成交回报及历史分块中使用该编码器。行情事件仍走原递归转换，订单 wire 字符串格式、快照、分块格式与哈希规则不变。

默认开启，开关为 `BACKTEST_FLAT_TRADE_RECORDS_ENABLED=1`，在内核/历史编码器创建时读取；设为 `0` 回退到原方式。它与第七轮 `BACKTEST_REUSE_HISTORY_JSON_ENABLED` 相互独立。

## 验证范围

- 普通逐成交、双时钟，旧撮合/V2 撮合：比较完整结果、快照、恢复后结果、成交回报、分块内容及精确字节预算。
- 自定义子类与含嵌套可变字段的记录仍深复制，修改返回字典不会修改源对象；小数尾零保留。
- 实际服务从相同排队数据库复制运行，比较每次落库的检查点 JSON、哈希、分块内容，以及完整 result/report。
- 扩展回归覆盖账户 V2、恢复、损坏分块拒绝、成本敏感性与前序优化。

## 配对基准

仅交替本轮开关，前六轮优化保持开启，第七轮候选关闭；保留全部成本分析和周期检查点。每根 K 线 10 条合成成交、SMA 3/5、每 1,000 条保存检查点，分别运行 100k 和 300k 三对。

```powershell
$env:PYTHONPATH='backend;packages/candlescope-plugin-sdk/src;packages/candlescope-backtest-sdk/src'
python -m scripts.benchmark_trade_strategy --round8 --events 100000 --pairs 3 --output docs/performance-evidence-20260919/round8-dual-100k.json
python -m scripts.benchmark_trade_strategy --round8 --events 300000 --pairs 3 --output docs/performance-evidence-20260919/round8-dual-300k.json
```

计时含实际 worker、策略、逐笔撮合、完整成本分析、检查点和报告持久化；与测试串行运行，不包含导入、HTTP 或浏览器。这是本地合成行情测试，不代表真实交易所全量数据或生产性能。

## 完整测量结果

| 行情数 | 配对 | 关闭 | 开启 | 耗时降幅（负值表示变慢） |
|---|---|---:|---:|---:|
| 10k | 1 | 0.762 s | 0.710 s | 6.87% |
| 10k | 2 | 0.760 s | 0.717 s | 5.69% |
| 10k | 3 | 0.758 s | 0.741 s | 2.25% |
| 100k | 1 | 6.679 s | 7.386 s | -10.59% |
| 100k | 2 | 9.063 s | 8.367 s | 7.68% |
| 100k | 3 | 8.353 s | 6.322 s | 24.31% |
| 300k | 1 | 25.569 s | 22.273 s | 12.89% |
| 300k | 2 | 24.795 s | 24.908 s | -0.46% |
| 300k | 3 | 22.343 s | 21.800 s | 2.43% |

中位耗时（不是逐对降幅中位数）：

- 10k: 0.760 -> 0.717 s; median elapsed reduction 5.69%
- 100k: 8.353 -> 7.386 s; median elapsed reduction 11.57%
- 300k: 24.795 -> 22.273 s; median elapsed reduction 10.17%

九对完整 result/report 全部一致，七对变快、两对变慢。短/中/长区间中位数均改善，但整机计时波动明显，不能保证任意策略都获得固定比例收益，也不以跨轮绝对耗时比较来证明提速。

最终回归 **342 passed**，无失败、错误或跳过；4 条已有 FastAPI 弃用警告。Ruff 与 `git diff --check` 通过。证据：`performance-evidence-20260919/round8-regression.xml`、`round8-validation.json`。
