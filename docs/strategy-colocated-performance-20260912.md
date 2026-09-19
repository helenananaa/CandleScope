# 策略回测同进程计算与活动订单索引

## 结果

基线是已提交的 `71d2d220`（P0/P1）。本轮仍在 `codex/strategy-replay-performance` 工作区，未提交、未合并、未部署到用户运行服务。

| 同一合成工作负载，V2 完整服务回测 | 上轮 | 本轮最终复测 |
|---|---:|---:|
| 图表 SMA，10,000 根 | 8.39 s | 3.39 s |
| 图表 SMA，100,000 根 | 67.16 s | 21.34 s |
| 官方 Python SMA，10,000 根 | 9.23 s | 4.88 s |
| 官方 Python SMA，100,000 根 | 76.35 s | 28.34 s |

全部完成并通过报告 hash 校验。10 万根图表 SMA 为 795 fills / 1,001 权益点；Python SMA 为 797 fills / 1,001 权益点。权益采样规则沿用 V2，没有以删减详细报告换取速度。

**仍未达到 10 万根完整回测低于 10 秒的候选目标。** 这些是同一 Windows 主机上的单次、顺序测量，不是 SLA。中间图表 SMA 样本为 16.47 秒，最终复测为 21.34 秒；保留两者，不选最快样本作承诺。

计时包括整个工作进程启动、计算、撮合、成本敏感性分析、检查点和报告保存。不含数据下载、文件历史加载、队列等待、HTTP 与浏览器。最新原始结果位于 `output/strategy-colocated-20260912/verified-*.json`。

## 改动

### 整段 BAR 任务在独立进程内计算

`BacktestService.execute_bar_run` 对尚未启动的内置隔离 provider，以及已授权的 `TRUSTED_LOCAL` Python provider，使用独立的整段任务工作进程。行情、策略、撮合和成交反馈在该进程内逐根按原顺序执行，取消每根行情的跨进程往返。主进程保留任务协调及监控职责。

- 仅处理物化 tuple BAR 输入；流式输入、其它 fidelity、自定义 provider 子类和故障注入测试继续走原路径。
- `SANDBOXED_LOCAL` 从不进入该路径，未放宽沙箱权限。
- 主进程通过共享内存读取 provider 调用截止时间，约每 50 ms 检查取消、generation 和总预算。保留 provider 自身更短的 step 预算；工作进程启动有 15 秒看门狗。
- 工作进程使用独立 SQLite 连接和既有事务/检查点协议；超时或崩溃终止进程，保持可恢复检查点。初始化失败也会把排队任务记为失败。
- Python 保留以 bundle 为工作目录的相对文件访问语义。工作进程使用后端 Python 环境，并在执行返回值中记录实际解释器。实测覆盖官方 SDK 脚本；第三方依赖、原生 Pine/Pyne 及其它主机环境没有在本轮获得性能资格结论。
- 匿名管道捕获普通 print 和原生文件描述符输出，保留 64 KB 输出预算；不创建持续增长的日志文件。

### Python 协议与历史记录

本地 SDK 调用保留原来的 JSON 归一化、53 位整数、非有限数值、深度与消息大小约束。普通 transcript 逐条计算同一份 canonical JSON 数组哈希，close 时补齐数组尾部；不保存全部观察帧。已有 bound-transcript 模式仍使用原链式算法和请求 ID 规则。

两种 transcript 模式均与参考路径做了完整报告和 result 字典对照，包含 provider close hash，不只检查成交数。

### 活动订单索引

BAR kernel 保留完整订单历史供恢复和报告使用；撮合、预计仓位、待开仓保证金和 OCO 查询改用活动订单集合。新增、部分成交、终结、拒单及恢复更新/重建派生索引。

没有 Host policy 的旧 planner 不再构造它完全不用的 PlanningContext；有 policy 时照常逐根观察风险，活动订单计数使用索引。

## 验证

- 扩展回归：**119 passed，4 warnings**，`output/strategy-colocated-20260912/regression.xml`。
- 最终控制与协议测试：见 `lifecycle-final.xml`（11 项），包含同任务数据库副本的整份报告/result 精确比较、两种 transcript、超时后 checkpoint 64 恢复、运行中取消、启动失败、原生输出超限、异常退出、SDK 输入限制和沙箱排除。
- 活动订单测试使用完整历史扫描实现作独立参照，覆盖 IOC 部分成交、OCO、终结和恢复；10,000 条已关闭订单后的连续查询不再扫描该历史列表。
- 保证金、资金、费用、交易解释、运行时以及原有控制路径已纳入回归。
- 语法编译及 diff whitespace 检查通过。没有声称完成全仓测试、其它操作系统验证或安装包发布。

早期试验出现过活动订单拒单分支引用错误、独立 Python 工作进程缺少 SDK 路径，以及取消测试使用了超过现有上限的预算值；均已修复/纠正后重跑。失败产物与诊断 profiler 样本保留，不计为成功耗时。早期父进程计数显示的 0 不是处理了 0 根，已改成读取完成事实并明确子进程阶段未被父计时器覆盖。

## 回退与复现

设置 `BACKTEST_COLOCATED_BAR_ENABLED=0` 可回到原 provider 通信路径；不撤销活动订单索引。没有数据库 schema 迁移，原检查点保持兼容。

在 backend 中：

```powershell
python -m scripts.benchmark_strategy_bar_audit --bars 100000 --strategy SMA --v2 --output ../output/strategy-colocated-20260912/repeat-sma.json
python -m scripts.benchmark_strategy_bar_audit --bars 100000 --strategy PYTHON --v2 --output ../output/strategy-colocated-20260912/repeat-python.json
```

本轮 profiler 用于区分计算与通信，不当作响应时间样本。剩余工作包括 SDK 对象/协议转换与哈希成本、逐根 kernel 计算和成本敏感性重跑。没有通过跳过风险观察、放宽数值校验或提前计算依赖成交反馈的信号来加速。
