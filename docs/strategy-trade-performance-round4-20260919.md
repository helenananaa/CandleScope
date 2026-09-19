# 成交策略研究：减少冗余计算与按需分析

本轮继续修改 `codex/strategy-replay-performance` 工作树，基于 `172ae4dd` 和前三轮未提交修改。未提交、合并或部署。

## 自动生效的等价优化

- 普通逐成交和双时钟服务在没有故障注入器时，不再为故障测试统计订单、部分成交数量或判断触发点。启用故障注入时保留原检查点及恢复行为。
- 普通逐成交内核先判断权益曲线是否采样，再计算权益、可用余额和字符串记录。采样规则、末尾补点和每日收盘模式保持不变；每日模式仍逐事件更新当天点。双时钟的同类优化已在第二轮完成。

## 显式研究选项

创建回测的 HTTP 请求模型及服务配置支持下列字段。这里接入的是后端 API，未增加前端设置控件。未传字段时保留原行为，也不向旧配置身份中加入默认字段。

| 字段 | 值 | 含义 |
|---|---|---|
| `cost_sensitivity_mode` | `FULL`（默认） | 保留完整成本敏感性分析 |
| `cost_sensitivity_mode` | `SKIP` | 不运行四个附加成本/延迟/参与率场景 |
| `checkpoint_policy` | `INTERVAL`（默认） | 初始、周期及最终检查点 |
| `checkpoint_policy` | `FINAL_ONLY` | 只保存最终检查点 |
| `checkpoint_policy` | `NONE` | 不保存检查点 |
| `checkpoint_interval` | 正整数 | 仅配合 `INTERVAL`；显式配置时将间隔冻结进运行身份 |

原来只有 BAR 可选择检查点策略，现在普通逐成交和双时钟成交回放也支持。成本选项也进入配置身份，不能把不同选项的报告冒充同一个结果。

V2 初筛时可在已有创建请求中加入：

```json
{
  "cost_sensitivity_mode": "SKIP",
  "checkpoint_policy": "FINAL_ONLY"
}
```

`SKIP` 保留主回测的信号、订单、成交、账户、权益曲线和相关结果哈希，但完整报告有意不同：`cost_sensitivity` 为 `{"status":"SKIPPED_BY_REQUEST","scenarios":[]}`，报告哈希也相应变化。没有缓存或后台补算；候选策略需要完整成本分析时，以 `FULL` 再运行。主回测中的费用、滑点、延迟、参与率、资金费及风控照常执行。

`FINAL_ONLY` 和 `NONE` 降低中断恢复能力，短任务初筛可选用；长任务仍可使用 `INTERVAL`。正常完成的金融结果不因检查点策略改变。最终策略状态预算校验仍保留。

## 验证与复现

新增测试覆盖普通逐成交/双时钟、三种检查点策略、跳过分析时确实不调用附加计算、主结果一致、报告标记及报告哈希有效、非法参数、API 请求模型、下单/部分成交故障后的恢复一致。

权益采样测试以 251 条行情、每 100 条采样为例，与逐点计算参考曲线比较，保留点完全一致且减少 247 次权益调用；每日模式仍保持相同调用次数和曲线。

服务端配对基准使用 100,000 条合成聚合成交、内置 SMA 3/5、每根 K 线 10 条成交、默认每 1,000 条保存检查点。对照默认完整运行与显式 `SKIP + FINAL_ONLY`；比较除成本矩阵和报告哈希之外的完整 result。它衡量研究选项组合的收益，不是仅两项等价优化的收益。

```powershell
$env:PYTHONPATH='backend;packages/candlescope-plugin-sdk/src;packages/candlescope-backtest-sdk/src'
python -m scripts.benchmark_trade_research_options --events 100000 --pairs 3 --output docs/performance-evidence-20260919/round4-research-100k.json
```

本地合成数据服务端验证不代表真实交易所全量数据、浏览器性能或生产资格。

## 本轮结果

| 配对 | 默认完整运行 | SKIP + FINAL_ONLY | 耗时降幅 |
|---|---:|---:|---:|
| 1 | 4.563 s | 2.184 s | 52.15% |
| 2 | 4.637 s | 2.264 s | 51.17% |
| 3 | 4.986 s | 2.462 s | 50.61% |

耗时中位数 **4.637 → 2.264 秒**，降低约 **51.2%**。每次均为 2,219 笔策略成交，三对主 result（仅排除成本矩阵和报告哈希）完全相等。仅使用本轮配对比较，不能与上一轮不同机器负载下的绝对耗时相除。证据：`performance-evidence-20260919/round4-research-100k.json`。

最终回归 **283 passed**，无失败、错误或跳过；4 条已有 FastAPI 弃用警告。Ruff 与 `git diff --check` 通过。证据：`performance-evidence-20260919/round4-regression.xml`、`round4-validation.json`。
