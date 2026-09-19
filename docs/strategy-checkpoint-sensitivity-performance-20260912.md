# 策略回测：检查点编码与多场景遍历

本轮在 `codex/strategy-replay-performance` 的既有未提交改动上继续实现。没有提交、推送或部署。

## 实际结果

同一 Windows 主机、同一基准入口、10 万根合成 K 线、EXECUTION_REALISM_V2 完整运行。包含工作进程启动、策略执行、撮合、检查点、全部成本敏感性场景及报告保存；不含下载、排队和浏览器渲染。测试与基准串行执行。

| 策略 | 修改前本轮样本 | 修改后三次样本 |
|---|---:|---:|
| 图表 SMA 3/5 | 6.498 s | 7.117 / 7.391 / 7.794 s |
| 图表 RSI 14 | 9.849 s | 7.380 / 7.630 / 9.130 s |
| Python 官方 SMA 3/5 | 13.178 s | 12.897 / 13.667 / 15.920 s |

**RSI 有改善；这组数据没有证实 SMA 和 Python 的端到端稳定提速。Python 仍未达到 10 万根低于 10 秒。** 没有把最快单次样本当作稳定指标，也没有将机器波动归因于未经证实的外部原因。

所有完成样本的报告哈希校验通过，成交、权益点及报告大小保持：SMA 795 / 1001 / 3,793,115 bytes；RSI 796 / 1001 / 2,405,915 bytes；Python 797 / 1001 / 2,570,378 bytes。金额、交易解释和报告没有降级。

证据目录 `output/strategy-checkpoint-20260912/`：`before-*.json`、`after-*.json`、`repeat-*-{1,2}.json`。它们是修改前后的完整样本，不是统计显著性或 P95 验收。

## 已实现

### 检查点编码复用

`StrategyProviderSession.snapshot_encoded()` 只捕获一次 provider 状态并执行原有严格编码。相同字节用于 provider 哈希、provider 字节预算和检查点中的嵌入状态。完整检查点也只生成一次 JSON，直接从落库字符串计算其 SHA256，避免再遍历整个对象编码一次。

编码仍使用原来的排序、ASCII 转义、分隔符和数值规则，不将浮点改交给字节表示不同的编码器。BAR、TRADE_TAPE、DUAL_CLOCK 三条保存路径均复用此实现。原有总状态预算、provider 预算、代际保护、身份校验和恢复验证继续执行。

### 图表策略紧凑检查点

只为精确的宿主图表 provider 增加 `chart-pyne-checkpoint/2` 内部标记。保留全部已捕获交易解释、全局决策序号、遗漏计数、指标和目标状态；历史时间点计数字典仅保存最近决策时间及该时间的计数。会话已经保证时间水位不倒退，未来执行不再需要更早时间点的计数。

普通 `snapshot()` 接口保持原有表示；新旧检查点都能恢复，特别测试了恢复后的下一根与检查点末次决策具有相同时间戳的情况。此变更不是追加式数据库检查点，也没有修改顶层 checkpoint/2 或进行数据库迁移。

`BACKTEST_COMPACT_CHART_CHECKPOINT_ENABLED=0` 可关闭紧凑表示；通用编码复用仍生效。

### 成本场景合并遍历

精确 BAR 参考内核的三个重算场景共用一次事件遍历、源时钟与行情 Decimal 解析。每个场景仍有独立账户、订单、可成交容量、保证金、费用及资金费状态，继续调用原撮合、下单、资金费和最终结算方法。

只重算冻结的宿主意图，不再次调用用户脚本。原来的五个场景、BAR 延迟场景的 NOT_APPLICABLE 标记、矩阵和场景哈希均保留。交易带、双时钟和自定义内核仍用原路径。

`BACKTEST_FUSED_BAR_SENSITIVITY_ENABLED=0` 可关闭合并遍历；`fast_bar=False` 仍可与完整参考引擎比较。

### 账户时钟兼容修复

检查发现 LINEAR_PERP_ONE_WAY_V2 会把包含合约辅助事件的源时钟映射为纯行情序号，上一轮图表批次队列的源事件身份检查不适用。现在该账户模型使用标准图表适配路径，并增加实际 spawn 与直接执行的完整报告对照。EXECUTION_REALISM_V2 与账户模型是不同维度，表中的普通账户样本仍使用图表批量路径。

## 验证

- 相关后端回归 **215 项通过、4 条警告**：`regression.xml`。
- 额外双时钟和 provider 一致性 **13 项通过**：`dual-and-provider.xml`；与前组文件不重叠，共 228 项。
- 新增 checkpoint 测试包括 Unicode、DEL、孤立 surrogate、大整数、浮点、元组和假值的字节/哈希对照；原严格错误；一次捕获/编码；新旧表示中断恢复后的完整 result/report；合约源时钟。
- 新增场景对照包括 IOC、部分成交、OCO、STOP_LIMIT、reduce-only、资金费、PAUSE/SKIP 间隙、保留/取消尾单、空输入、独立容量和不可变原始输入。既有历史合约账本对照继续通过。
- 语法编译与 `git diff --check` 通过。没有声明生产、任意第三方脚本或跨平台性能通过。

## 剩余瓶颈

本轮 RSI 轻量阶段计时显示：12 次检查点约 0.746 s，成本敏感性约 0.440 s，最终报告约 0.325 s，整个子进程 5.750 s，端到端 7.276 s。见 `stages-rsi.json`。不能把这些轻量计时与此前带 cProfile 的 5.74 s 检查点直接计算加速倍数。

Python 的本轮 cProfile 显示子进程约 25.31 s（含剖析开销），策略回调约 17.89 s，其中 SDK 对象通道约 12.76 s，用户 SMA 的 step 本体约 1.30 s；检查点约 0.69 s、成本分析约 1.00 s。各项有包含关系，不能相加。见 `profile-python.txt/.json/.pstats`。

因此后续 Python 的重点是观察对象构造、边界校验和逐根调用回执，而不是继续压缩最终报告。本轮没有新增 Python 批量协议，也没有完成原生执行内核迁移。

## 复现

在此 worktree 的 backend 目录：

```powershell
H:/program/CandleScope/.venv/Scripts/python.exe -m scripts.benchmark_strategy_bar_audit --bars 100000 --strategy PYTHON --v2 --output ../output/strategy-checkpoint-20260912/reproduction.json
```

图表样本使用 `--strategy SMA` 或 `--strategy RSI`。用 `--worker-timings` 定位子进程阶段；`--profile-worker` 的输出只用于热点剖析，不能替代常规延迟样本。
