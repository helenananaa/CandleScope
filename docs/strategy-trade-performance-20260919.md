# 成交驱动策略测试优化

工作树 `CandleScope-strategy-replay-performance`，基于 `172ae4dd`。本次修改尚未提交、合并或部署。

## 实现范围

- 成交内核以保留插入顺序的活动订单索引进行撮合、预计仓位、预占保证金和 OCO 查询。新增、拒绝、部分成交、完成、过期、取消与恢复均维护该索引。完整订单历史仍供报告和恢复使用。双时钟共享这个成交内核；服务层的部分成交检查和风控上下文也使用活动订单集合。
- `AGG_TRADE_EXECUTION` 接入受监督的整段任务 worker。内置隔离 provider 和明确授权的 `TRUSTED_LOCAL` Python 在同一 worker 内完成策略与撮合。逐笔行情仍按原顺序执行，策略仍在完整 K 线收盘时调用。`SANDBOXED_LOCAL`、自定义 provider、故障注入和非 tuple 输入维持原路径。逐笔策略 `AGG_TRADE_TAPE` 本次不接入整段 worker。
- `TRADE_TAPE` / `AGG_TRADE_TAPE` / 双时钟共享增量检查点存储。每 256 条封存已结束订单前缀和不可变成交；活动订单所在前缀保持完整尾部，其他状态照常保存。新编码名为 `TRADE_HISTORY_CHUNKS_V1`，双时钟定位到 `engine.execution`。公开快照保持原形状。
- 保存仍在原有事务与 generation/sequence 校验下进行；恢复验证 manifest 和每个块的哈希。内存预算按展开后的完整 JSON 字节数核算，不以压缩后的大小放宽预算。不改变价格精度、事件次序、成交容量、费用和账户模型。

## 开关与回退

三项默认开启，可独立设为 `0`：

| 环境变量 | 关闭效果 |
|---|---|
| `BACKTEST_TRADE_ACTIVE_INDEX_ENABLED` | 恢复完整历史订单遍历 |
| `BACKTEST_COLOCATED_DUAL_CLOCK_ENABLED` | 恢复双时钟原 provider 调用路径 |
| `BACKTEST_TRADE_INCREMENTAL_CHECKPOINT_ENABLED` | 新检查点写完整格式，仍可读取已有分块格式 |

关闭写入开关不会自动改写尚存的分块检查点。旧二进制不识别新的成交编码，不能直接把“关闭开关”当作旧二进制回滚。离线停止服务并备份后，可用新代码已有的 `app.backtest.checkpoint_history.rollback_history(database)` 展开报告及检查点、降到 schema 7，再由目标版本执行其迁移。测试只操作临时数据库，没有迁移用户数据。

## 验证

完整结果与报告对照覆盖内置 SMA 和受信任 Python SMA 的双时钟路径。测试覆盖普通/双时钟、基础/V2 撮合、部分成交、IOC、OCO、止损、止损限价、reduce-only、资金费、活动订单恢复、长时间挂单阻止前缀封存、坏块/缺块拒绝、离线回滚、worker 超时终止和恢复、沙箱拒绝走同进程路径。

真实服务检查点测试在 600 条行情处持久化后中断，恢复时关闭增量写入，继续产生新订单并与不中断运行比较完整 result。独立测试证明 10,000 条已完成订单只在构建索引时扫描，后续 100 条成交的撮合与预计仓位查询不再遍历它们。

扩大回归 190 passed，加上风控策略及交易解释报告回归 26 passed，合计 **216 passed**，无失败或跳过；有 4 条既有 FastAPI deprecation warnings。Ruff 和 `git diff --check` 通过。证据为 `performance-evidence-20260919/regression.xml` 与 `policy-report-regression.xml`。

## 测量口径

Windows / CPython 3.12，合成连续聚合成交，固定 SMA 3/5、完整收盘信号、EXECUTION_REALISM_V2；每 10 条成交组成一根 1 分钟 K 线，每 1,000 条行情保存检查点。每对使用同一个 QUEUED 数据库副本、相同 run/config/snapshot 身份、相同时间参数，交替开启/关闭全部三项。对照验证整个 result 和 report 相等，而非只对比收益或成交数。

计时包含整段服务执行、worker 启动、策略、撮合、检查点、成本敏感性和报告持久化；不含合成数据构造、导入/冻结、排队、HTTP 和浏览器绘制。测试、构建不与性能测量并行。原始数据保留所有样本，不从不同轮次挑最快值。

最终三对结果见 `performance-evidence-20260919/final-dual-100k.json`。`dual-10k.json` 和 `dual-100k.json` 是服务层额外历史扫描收敛前的阶段证据，不作为最终版本延迟承诺。

| 配对 | 原路径 | 三项开启 | 完整 result/report |
|---|---:|---:|---|
| 1 | 35.447 s | 14.365 s | 完全一致 |
| 2（先开启后关闭） | 34.145 s | 15.863 s | 完全一致 |
| 3 | 35.034 s | 13.751 s | 完全一致 |

每次 100,000 条聚合成交、2,219 笔策略成交。原路径中位数 **35.034 s**，优化中位数 **14.365 s**；中位数之比约 **2.44 倍**，三对 `1 - on/off` 的中位数为 **59.48%**。这是三项合并收益，不用于推断某一项的独立贡献。前序阶段与最终轮次存在整机耗时差异，不跨轮计算提速比例。

复现（工作树根目录，设置 backend 及两个 SDK 的 PYTHONPATH 后）：

```powershell
python -m scripts.benchmark_trade_strategy --events 100000 --pairs 3 --output output/trade-performance.json
```

这是合成成交数据的本地完整服务证据，不是实际交易所数据、浏览器端延迟或生产 SLA。逐笔策略依然逐笔回调，沙箱策略保持跨进程隔离。事件/权益/provider 状态并未全部改为流式或增量；行情仍物化，未实现区间跳过，也未把逐笔撮合降成 K 线近似。
