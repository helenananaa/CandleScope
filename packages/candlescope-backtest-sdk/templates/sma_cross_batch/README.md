# 官方 SMA 批量接口原型

策略代码位于 `strategy.py`。假设是仅依赖已完成行情，不读取账户、成交反馈或外部状态。
signal clock 为 BAR_CLOSE。保留普通 SMA 模板的浮点求和顺序、未满窗口时的除数和相等时的目标方向。
参数为 `fast`、`slow`；宿主首版范围 2..512（manifest 的 slow 下限为 3）。warmup 期间返回空目标。

本目录是独立模板，原 `sma_cross` 及其 V1 golden 保持不变。协议为
`candlescope.python-market-batch/1`，回执为 `candlescope.python-market-batch-receipt/1`。
需要本工作区构建的 SDK；此新增接口尚未发布到包索引。

## 在 CandleScope 中使用

按现有流程导入此目录、冻结 Python revision，并完成可信本地 smoke。创建回测时使用：

```json
{
  "python_execution_protocol": "MARKET_BATCH_V1",
  "python_runtime_mode": "TRUSTED_LOCAL",
  "python_trusted_confirmed": true,
  "fidelity_mode": "BAR_APPROX",
  "account_model": "LINEAR_PERP_ONE_WAY_V1",
  "parameters": {"fast": 3, "slow": 5}
}
```

这是普通 Run 创建负载的附加选项；仍需原来的 revision、dataset、snapshot、时间范围等字段。
不填 `python_execution_protocol` 时继续逐根执行，可作为对照。协议进入 config hash、检查点身份和报告身份。

首版 fidelity 仅 BAR_APPROX、完整 BAR-only 快照和上述账户；不支持 aggTrade、双时钟、沙箱或流式快照。
宿主只接受经过因果性对照、固定源码摘要的此实现。修改策略源码后，不能凭声明继续走批量通道；可使用原逐根接口。

## SDK 调用

在此模板目录中，可从脚本文件导入实现：

```python
from strategy import Strategy
from candlescope_backtest_sdk import MarketBatch, market_batch_hashes

columns = {
    "sequence": [1, 2, 3],
    "event_time_ms": [60_000, 120_000, 180_000],
    "open": ["10", "11", "9"],
    "high": ["10", "11", "9"],
    "low": ["10", "11", "9"],
    "close": ["10", "11", "9"],
    "volume": ["1", "1", "1"],
}
batch = MarketBatch.from_columns(columns)
parameters = {"fast": 2, "slow": 3}
targets = Strategy.calculate_batch(batch, parameters)
receipt = market_batch_hashes(batch, targets, parameters)
```

后续批次在列前附上最多 `max(fast, slow)-1` 根过去行情，并设置 `context_rows`。
返回数组只对应新行。行 i 只能读取截至该行的前缀；批量方法不能使用未来行计算早期目标。

## 回执与恢复

宿主每批最多 256 根新行，在批次入口校验列、时钟、数值和字节预算。输入及规范化后消息均限制为 256 KiB，
单字符串限制为 64 KiB；科学计数法在展开前检查预算。用户计算仍在父进程监督的工作进程中，批次计算受原调用超时约束。

账户与撮合逐根推进。报告的 `pythonBatchReceipt.batches` 给出源快照行偏移、行数、首末序号、输入哈希和输出哈希。
定位决策时，用 `sourceOffset + 批内下标` 找到源快照行；重建 MarketBatch 后可用 `market_batch_hashes` 验证。
若执行在批次中途结束，`partialBatch` 分别标记计划行数与已消费行数，不把剩余信号当成已执行决策。
完整回执还绑定执行反馈。会话先校验 generation，再从语义回执排除这个运维字段，以保证恢复后的哈希一致。

检查点保存已消费位置、批次回执链、已完成批次及尚未消费的目标数组。恢复时重建并核对待消费批次输入哈希。
不能声称新回执与旧 JSONL transcriptHash 相同；二者协议不同。交易、权益、成本矩阵和已有交易解释通过对照验证。

golden/验收覆盖标量输出、不同窗口和批次边界、未来后缀扰动、实际工作进程超时恢复；不代表任意用户 Python 代码已经获得因果性认证。
