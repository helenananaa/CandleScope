# Python 纯行情批量接口原型与性能验收

已在 `codex/strategy-replay-performance` 实现 SDK 列式接口、宿主批量执行、独立协议回执及官方 SMA 接入。改动接续此前未提交工作；未提交、未推送、未部署，也未发布 SDK 包。

## 实测结果

同一 Windows 主机、同一基准入口、10 万根合成 BAR、官方 SMA 3/5、EXECUTION_REALISM_V2、旧版账户和规划器、交易解释开关开启。每次使用新工作进程，不复用策略结果缓存。以下是完整 execute_bar_run 时间，包含工作进程启动、策略、撮合、成本敏感性、检查点和完整报告保存；不包含数据生成、导入/冻结、先行 smoke、排队和浏览器渲染。没有声称清空操作系统文件缓存。

| 成对执行 | 原逐根 Python | MARKET_BATCH_V1 |
|---|---:|---:|
| 1 | 11.668 s | 6.370 s |
| 2 | 11.754 s | 6.131 s |
| 3 | 11.356 s | 6.052 s |
| 中位数 | 11.668 s | 6.131 s |

中位耗时下降 **47.46%**，吞吐约 **1.90 倍**。这三次批量样本均低于 10 秒，不能外推为生产 P95 或任意 Python 脚本承诺。原型中间样本 5.054 s 也保留，最终对照没有挑选该最快值。

两条路径均为 797 笔成交、1001 个权益点；报告哈希全部校验通过。旧报告约 2,570,378 bytes，新报告约 2,675,285 bytes，增加的是批量回执元数据。协议及配置身份不同，因此整体报告哈希和 provider close hash 不应相等；交易、权益、成本矩阵和已有解释内容保持等价。

额外 1 万根密集成交样本（1062 fills）：逐根 2.318 s，批量 1.994 s。成交密集时，撮合及报告占比更高，不能套用普通样本的加速倍数。

### 内存

用 Windows GetProcessMemoryInfo 读取进程生命周期 PeakWorkingSetSize，不使用采样猜测峰值。

- 批量工作进程三次：121.53 / 120.89 / 121.44 MiB。
- 逐根工作进程约 121–122 MiB。
- 两种模式的父进程各约 145 MiB。

父、子进程峰值发生时间可能不同，不能把二者直接相加宣称进程树同时峰值。当前样本未出现明显额外内存增长。

证据位于 `output/python-market-batch-20260912/`：`scalar-1..3.json`、`batch-1..3.json`、对应 `memory-*.json`、`dense-*.json`。

## 接口和身份

SDK 新增 `MarketBatch.from_columns()`，将 sequence、event_time_ms 和 OHLCV 转换为只读元组列。包含过去上下文行数及新行中的 warmup 行数。新增 `market_batch_hashes()`，可从同一源数据和目标数组复算输入/输出哈希。

官方独立模板在 `packages/candlescope-backtest-sdk/templates/sma_cross_batch/strategy.py`，保留逐根方法作为对照，增加静态 `calculate_batch(batch, parameters)`。原 `sma_cross` 模板及其 V1 golden 未修改。

宿主每批 256 根新行，另附最多 max(fast, slow)-1 根过去行情。10 万根时用户计算函数约调用 391 次，宿主账户和规划器仍逐根消费目标；不是把整个引擎改成 391 次事件处理。

Run 创建须显式指定 `python_execution_protocol: MARKET_BATCH_V1`。该字段进入 config hash、检查点身份和报告身份。作者列式协议为 `candlescope.python-market-batch/1`，回执为 `candlescope.python-market-batch-receipt/1`，不冒充旧 JSONL transcript。

首版宿主只接纳固定源码摘要对应的官方 SMA。仅有“纯行情”声明不能证明无未来引用；修改源码会失去此批量资格。SDK 公开类型用于后续扩展，但任意第三方批量函数尚未获准在宿主执行。

## 校验、因果性和回执

- 固定源码经过标量对照、不同周期/分块边界及未来后缀扰动验证。每个目标只使用截至该行的价格前缀；保留旧 float 求和顺序、未满窗口时的除数和相等处理。
- 仅支持 TRUSTED_LOCAL、BAR-only 物化快照、BAR_APPROX、LINEAR_PERP_ONE_WAY_V1 和 TARGET_POSITION。沙箱、流式、合约辅助时钟与任意反馈相关脚本继续用原路径；显式要求批量但条件不满足时拒绝，不悄悄改用另一协议。
- 批次入口统一校验列长度、53 位时钟整数、时序、有限数值、warmup 范围和消息预算。原始与规范化包均受 256 KiB 限制；单字符串 64 KiB，科学计数法在展开前检查预算。坏数据可以在批次入口提前拒绝，失败时点不保证与逐根协议一致。
- 用户批量计算仍受原父进程监督和调用截止时间约束；没有将每批超时简单乘以行数。
- 回执记录批次源行偏移、行数、首末序号、输入与输出哈希，并与执行反馈形成链。逐根定位使用 sourceOffset 加批内下标，再从不可变源快照重建数据验证。中途结束的 partialBatch 分开表示计划行数和已消费行数。
- generation 先由会话验证，再从语义回执中的执行反馈排除；这个运维字段不使同一运行的恢复结果发生漂移。
- 版本化风控规划器仍获得与逐根模式相同的 StrategyOutput 哈希。旧规划器只消费目标值，批量模式不再生成它不会保存的逐根中间回执。

原 Python SMA 不输出完整逐根指标变量日志。本轮保留它原有的交易解释内容/不可用标记；批量回执用于定位和复算，不宣称新增了所有策略变量的详细日志。

## 检查点与恢复

检查点保存已消费偏移、回执链、已完成批次及待消费的目标数组。恢复时重新构造待消费批次输入，核对输入/输出哈希，并重算认证函数核对待消费目标。不会把策略提前计算到批末的状态当作账户已经推进到批末。

通过实际 spawn 工作进程注入延迟并触发父进程超时：从第 279 根检查点、第二批中途恢复，完整 result、完整报告和最终批量回执均与不中断执行相等。另有直接故障注入及多种游标恢复对照。

## 验证记录

- 后端相关回归 237 项通过、4 条警告：`backend-regression.xml`。
- 随后补充/调整协议准入与部分批次元数据，协议专项 10 项复验通过、4 条警告：`final-protocol-tests.xml`。两组包含重叠，不相加。
- SDK 48 项通过：`sdk-regression.xml`，包含新列式接口、不同周期/批次边界和原模板回归；离线安装测试从新构建 wheel 导入并执行 MarketBatch。
- 语法编译及 diff whitespace 检查通过。未做浏览器流程或其他操作系统验收。

## 使用与复现

导入新 `sma_cross_batch` 目录、冻结 revision 并完成现有可信本地 smoke，然后在 Run 创建负载中加入 `python_execution_protocol: MARKET_BATCH_V1`。完整使用说明见模板 README。省略该字段则继续逐根执行；不应修改已冻结 Run 的协议来回退。

在 backend 目录复现：

```powershell
H:/program/CandleScope/.venv/Scripts/python.exe -m scripts.benchmark_strategy_bar_audit --bars 100000 --strategy PYTHON --v2 --python-batch --worker-memory ../output/python-market-batch-20260912/reproduction-memory.json --output ../output/python-market-batch-20260912/reproduction.json
```

去掉 `--python-batch` 获得原逐根官方 SMA 对照。该原型没有修改任意 Python 脚本的默认执行方式，也没有进行原生撮合内核迁移。
