# 策略脚本回测性能检查（2026-09-12）

## 结论

当前简单脚本的完整 BAR 回测，1 万根需要约 14–18 秒；新版撮合模型下，10 万根图表均线策略需要 141 秒。官方 Python 均线模板的大规模运行还存在检查点消息大小失败。以上不是手动 K 线回放测试。

## 范围与方法

- 代码基线：`f9e123d52f7be7dea558d7c8e45f296ddeefeb17`，新 worktree；不包含原 main 工作区未提交改动。
- Windows，本仓库代码复用主工作区 Python 环境。测试顺序执行，每个案例一次；不是稳定分位数或生产 SLA。
- 合成 1 分钟 OHLCV，价格为 `100 + 10*sin(i/40)`，有交易而非空策略。均线参数 3/5，RSI 周期 14。
- 调用 `BacktestService.execute_bar_run`，使用独立临时 SQLite，完成撮合、资金核算、检查点、报告保存。图表策略使用生产 `IsolatedStrategyProvider`；Python 使用仓库官方 `templates/sma_cross`，仅该测量进程启用 TRUSTED_LOCAL，未更改产品配置。
- 耗时包括策略进程启动和完整服务执行，不包括数据下载、历史数据加载、队列等待、编译/smoke、HTTP 与浏览器绘制。所有已完成报告均通过 `verify_report_hash`。
- `EXECUTION_REALISM_V2` 与基础模型分开记录。新版模型权益点按既有规则降采样，因此完整生成报告不等于输出每根权益或无限交易解释。
- 测量进程采用 180 秒运行上限；产品默认配置为 14,400 秒。超时结果只说明没有在本次测量窗口完成。

## 实测

| 路径 | K 线数 | 服务耗时 | 结果 |
|---|---:|---:|---|
| 图表均线，基础模型 | 1,000 | 3.20 s | 完成，7 fills，1,000 权益点 |
| 图表均线，基础模型 | 10,000 | 16.26 s | 完成，79 fills，10,000 权益点 |
| 图表 RSI，基础模型 | 1,000 | 4.37 s | 完成 |
| 图表 RSI，基础模型 | 10,000 | 18.01 s | 完成 |
| 图表 RSI，基础模型 | 100,000 | 180.32 s | 测量超时；处理了 95,232 根 |
| 图表均线，V2 | 10,000 | 15.75 s | 完成，79 fills，101 权益点 |
| 图表均线，V2 | 100,000 | 141.24 s | 完成，795 fills，1,001 权益点，报告 3,793,115 bytes |
| 官方 Python 均线，V2 | 1,000 | 1.65 s | 完成 |
| 官方 Python 均线，V2 | 10,000 | 14.07 s | 完成，81 fills，101 权益点 |
| 官方 Python 均线，V2 | 100,000 | 30.39 s 后失败 | 到 30,000 根检查点时 MESSAGE_TOO_LARGE；不是完成时间 |

另有带 cProfile 的 1,000 根诊断运行，只用于定位调用开销，不与普通样本混算。

## 性能热点与失败机制

1. **逐根线程与跨进程请求。** `strategy/host_adapter.py:observe` 每次新建线程和 Queue，随后 `strategy/isolated.py:_call` 执行 send/poll/recv。服务 `_assert_frame_inputs` 与 `_observation_features` 每根还分别读取 provider 能力；图表独立进程的 `describe` 没有缓存。1,000 根的主线程 cProfile 实际记录了 **2,003 次 describe、3,024 次 _call**；describe 累计约 0.69 s，诊断运行服务总计约 1.65 s（不能当作消除它就必然节省的时间）。Python 入口的 `python_runner.py:call` 还为每次请求创建读取线程。10 万根意味着大量调度、编码与通信；不能把这部分称为指标数学计算。
2. **订单历史扫描。** `simulation/kernel.py:_match` 每根遍历 `self.orders` 筛选活动订单，包含历史已完成订单；交易数量增加时会额外放大成本。属于代码确认的增长路径，本轮未单独归因百分比。
3. **Python 模板快照无界增长。** 官方模板 `step` 持续 append closes，`snapshot` 返回全部 closes。默认每 10,000 根保存检查点，runner 单条消息限制 256 KB。本轮在 30,000 根时实际触发超限。不能推广为所有 Python 策略都在 30,000 根失败，阈值取决于快照内容。
4. **检查点与报告。** 检查点会编码完整 engine/provider/planner 状态。10 万根新版均线样本中，检查点合计约 0.83 s，成本敏感性分析约 7.93 s，报告构建/持久化约 1.02 s，均不是该样本的主要耗时。基础模型保留更多权益和决策，不能套用新版数字。

阶段计时包含嵌套：kernel 包含 provider/checkpoint 回调以及成本敏感性重跑，不能将所有字段相加。`script_step` 包含 IPC 等待，不是纯脚本 CPU 时间。原始 `report_json_seconds` 还包含报告 hash 校验和结果字段组装，不作为纯序列化基准。

## 优先级

1. 修复官方 Python 模板的无界快照，验证大规模运行与恢复等价；不要只把消息限制调大。
2. 会话内缓存不变的 provider 能力，复用执行线程和 IPC 工作循环，保持超时、取消、隔离、逐根订单反馈与下一根撮合语义。
3. 撮合维护活动订单集合，避免扫描全部订单历史。
4. 针对高交易频率、复杂脚本、Pine/native Pyne、AppContainer 模式和真实数据，补充独立基准；本轮数字不能替代这些路径。

本轮只增加测量脚本和报告，没有修改业务实现。脚本语法检查与 diff whitespace 检查通过；环境未安装 Ruff，未完成 Ruff 检查。

## 复现与证据

在 backend 目录使用已安装依赖的 Python：

```powershell
python -m scripts.benchmark_strategy_bar_audit --bars 10000 --strategy SMA --v2 --output ../output/strategy-performance-audit-20260912/repeat-sma.json
python -m scripts.benchmark_strategy_bar_audit --bars 100000 --strategy PYTHON --v2 --output ../output/strategy-performance-audit-20260912/repeat-python.json
```

原始 JSON、环境信息、cProfile 数据位于 `output/strategy-performance-audit-20260912/`（本地测量产物）。最初测量脚本出现未传策略源码以及 smoke 窗口超过 7 天的配置错误；已修正为注册版本、合法的短窗口 smoke 和完整目标运行。它们发生在执行前，不计入表中性能数字。
