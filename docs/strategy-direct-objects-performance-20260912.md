# 策略回测直接对象接口与重复派生工作削减

基线：`daa1be34`。本轮在 `codex/strategy-replay-performance` 工作区实现，未提交、未合并、未部署。

## 完整回测结果

| 合成 BAR / EXECUTION_REALISM_V2 工作负载 | 上轮 | 本轮最终实测 |
|---|---:|---:|
| 图表 SMA，10,000 根 | 3.39 s | 2.27 s |
| 图表 SMA，100,000 根 | 21.34 s | 13.21 s |
| 官方 Python SMA，10,000 根 | 4.88 s | 2.89 s |
| 官方 Python SMA，100,000 根 | 28.34 s | 22.82 s |

**10 万根完整回测低于 10 秒的候选目标仍未达到。** 每项为单次本机测量，不是稳定分位数或生产 SLA。报告 hash 校验全部通过；10 万根的 fills、权益点数与报告字节数均与上轮相同。

计时包括进程启动、脚本计算、撮合、完整成本敏感性分析、检查点和报告保存。未计入历史下载/加载、排队、HTTP 与浏览器绘制。原始结果：`output/strategy-direct-20260912/final-*.json`。

## 高交易频率边界

另将价格变化周期从 40 改为 3，10,000 根生成约 1,060 条 fills。参照代码来自 `git archive daa1be34` 的独立副本，仅复制新版测量入口以使用同一行情生成器，没有改参照业务代码。

| 高频案例 | 参照提交 | 本轮 |
|---|---:|---:|
| 图表 SMA，1,060 fills | 4.76 s | 4.26 s |
| Python SMA，1,062 fills | 5.05 s | 最终样本 19.83 s；轻量阶段计时复测 5.25 s |

不能据此声称高频场景稳定提速。19.83 秒样本未复现且缺少当时的阶段计时，无法可靠归因，予以保留。复测总计 5.25 秒，子进程约 2.82 秒，报告构建/保存约 0.38 秒。初期样本、失败试验、profiler 数据与最终样本分别保存。

## 当前进程内剖析

新增 `scripts/strategy_worker_profile.py`，作为真实 spawn worker 的测量入口，支持 cProfile 和轻量阶段计时。不是用父进程空计数代替子进程计算，也不再用同进程模拟当作实际 worker 剖析。

在 10,000 根 Python 的诊断样本中：

- 改动前约 10,169 次协议调用；改动后约 10,000 次对象调用和 169 次一般协议调用。
- 成本敏感性分析的诊断累计时间从约 0.96 秒降至约 0.32 秒。
- 高频图表策略剖析显示大量时间在交易解释和报告复制，而不是单纯撮合。

Profiler 有额外开销；阶段计时部分嵌套，不能相加，也不能直接换算最终 10 万根的百分比。

## 实现

### 直接对象接口

- 在既有同进程工作路径内，常规 host-created 观察帧直接构造 SDK `Observation` / `Bar`，不进行 JSON 编码、解码再构造对象。
- 快路径只接收固定 schema、小型 ASCII 文本映射和安全整数；保守的尺寸上界低于 64 KiB、深度低于 8、容器小于 32，并检查当前 SDK 的限额是否兼容。Decimal 规范化及非有限值校验仍执行。
- Unicode、大映射、长文本、异常整数或其它不满足条件的数据继续经过原 SDK strict JSON 路径。没有调大消息限制或放宽校验。
- 策略输出仍按 SDK 合同编码/校验；Host 内部将 `StrategyOutput` 对象直接交给支持它的 planner。
- 继续生成原样 transcript 哈希。一般调用路径把交给策略的数据与请求收据分离，防止策略修改嵌套数据后污染收据。
- `BACKTEST_DIRECT_OBJECTS_ENABLED=0` 可以回退对象通道；不撤销其它派生工作优化。沙箱路径保持原隔离。

### 成本敏感性分析只生成实际消费的证据

专用 BAR sensitivity kernel 复用同一 `_run_events` 撮合、账户、资金费、订单生命周期与终结逻辑，只省略矩阵不使用的决策哈希、权益曲线和完整 Run 报告。决策计数、fills、完整 ledger、fill/ledger hash 均保留。

它返回专用结果类型，不能被误当作完整报告或恢复检查点。`fast_bar=False` 保留完整 kernel 参照路径。完整五场景矩阵及其哈希在测试中与参照相等，覆盖部分成交、IOC、订单终结策略、固定资金费和历史标记价/合约账本。

主回测也不再构造按既有采样策略必然丢弃的权益行。逐根账户更新和风险观察照常执行；日收盘和终端样本保留。

### 报告与交易解释去重

- 报告封存仍深拷贝一次以隔离调用者，计算 hash 时仅替换必要的顶层字段；只读验证不再复制整棵报告。
- 交易解释验证用同一次 canonical 编码检查 hash 和字节预算。
- 绑定 tradeId 不再连续做两次深拷贝；enrichment 已负责复制的数据不提前重复复制。
- 验证了嵌套数据隔离、篡改检测、报告/解释 hash、导出与旧 golden。

## 验证与限制

最终相关回归：**153 passed，4 warnings，30.17 秒**，见 `output/strategy-direct-20260912/regression-final.xml`。覆盖对象/JSON 输出与收据对照、回退、数值限制、嵌套修改隔离、成本矩阵等价、采样工作量、报告封存、交易解释、费用/保证金、取消、超时恢复和官方模板。

语法编译及 diff whitespace 检查通过。没有完成全仓测试、跨操作系统/安装包验证，也不能把这些 SDK/图表策略结果推广到任意第三方库或原生 Pine/Pyne 脚本。

剩余时间仍分布在 SDK 对象与数值处理、哈希、逐根执行和复杂报告。这里没有通过异步隐藏敏感性分析时间、降低统计精度或提前计算依赖成交反馈的信号来算达标。

## 复现

在 backend 中：

```powershell
python -m scripts.benchmark_strategy_bar_audit --bars 100000 --strategy PYTHON --v2 --output ../output/strategy-direct-20260912/repeat-python.json
python -m scripts.benchmark_strategy_bar_audit --bars 10000 --strategy SMA --v2 --dense --output ../output/strategy-direct-20260912/repeat-dense.json
python -m scripts.benchmark_strategy_bar_audit --bars 10000 --strategy PYTHON --v2 --profile-worker ../output/strategy-direct-20260912/profile --output ../output/strategy-direct-20260912/profile-run.json
```

用 `--worker-timings` 代替 `--profile-worker` 可记录轻量阶段计时。性能 JSON 与 profiler/诊断 JSON 应分别解释。
