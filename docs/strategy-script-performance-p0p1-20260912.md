# 策略脚本回测 P0 / P1 优化结果

基线：`f9e123d52f7be7dea558d7c8e45f296ddeefeb17`。修改仅在 `codex/strategy-replay-performance` 工作区；未提交、未推送、未重启用户服务。

## 实现

- 官方 Python SMA 模板只保留 `max(fast, slow)` 个收盘价，warmup 和 step 都有相同上界。restore 接受旧的全历史快照并保留所需尾部。参数 fast 大于 slow 时也保持原决策。只改变此模板，不截断任意用户脚本。
- 更新模板 bundle/report golden 指纹；原 `decision_hash` 保持 `05d9e7de117d4d7da380c4cae70cdd0bfb999bc7ad0eff909dbf780d8d5fd3b1`。
- 独立策略 provider 缓存能力描述，prepare/restore/终止时失效。返回隔离副本，调用方修改不能污染缓存。关闭或异常终止后不偷偷重启旧会话。
- Host adapter 与 Python JSONL runner 各复用一个串行 daemon worker，避免每根创建线程。所有调用仍等待各自结果，撮合、成交反馈和策略调用顺序不变。
- 串行 worker 超时后拒绝后续任务，不将迟到响应交给新调用。Host 超时会中止支持终止的 provider；Python 超时会杀死子进程，读写均在超时边界内。BAR、dual-clock、trade 三条服务路径均显式关闭 adapter。

## 同工作负载前后测量

复用初次审计的脚本、合成行情与参数，顺序执行，每项各一次。均使用 `EXECUTION_REALISM_V2`、SQLite、10,000 根检查点间隔。Python 为仓库官方模板的 TRUSTED_LOCAL 独立进程；图表均线为 IsolatedStrategyProvider。未修改生产环境配置。

| 案例 | 优化前 | 优化后 | 观察结果 |
|---|---:|---:|---|
| 图表 SMA，10,000 根 | 15.75 s | 8.39 s | 约 1.88 倍速度 |
| 图表 SMA，100,000 根 | 141.24 s | 67.16 s | 约 2.10 倍速度 |
| Python SMA，10,000 根 | 14.07 s | 9.23 s | 约 1.52 倍速度 |
| Python SMA，100,000 根 | 30,000 根检查点失败 | 76.35 s 完成 | 消除该模板的消息超限失败 |

所有完成案例的报告 hash 校验通过。10 万根图表 SMA 生成 795 fills、1,001 权益点；Python SMA 生成 797 fills、1,001 权益点。权益点按现有 V2 策略采样，不是逐根输出。

计时包括策略启动、逐根计算、撮合、成本敏感性分析、检查点和报告保存，不包含数据下载/加载、排队、HTTP 或浏览器。阶段计时相互嵌套，不能相加；单次样本不构成稳定百分位或 SLA，也不代表复杂脚本、原生 Pine/Pyne 或 AppContainer 的性能。

## 验证

- 最终相关回归 **66 passed，4 warnings，18.66 s**，XML：`output/strategy-p0p1-20260912/regression.xml`。
- 覆盖官方模板 golden、真实服务运行、交易解释、运行取消不写报告、超时后恢复、进程无限循环终止、协议 EOF/非法 JSON、阻塞管道写入超时、线程复用/关闭、迟到结果隔离、能力缓存隔离和旧快照恢复。
- 另一次扩展测试的真实 AppContainer 文件/网络隔离与临时 ACL 生命周期场景通过。该批结果为 56 passed / 1 failed：失败是测试注入已启动子进程时未初始化通信 worker，已改为按需初始化；定向 7 项以及最终 66 项运行均通过。没有跳过失败或放宽限制。
- 官方模板独立 Host probe 的 decision golden 与旧版相同；新模板运行指纹已更新。
- 语法编译及 `git diff --check` 通过。环境未安装 Ruff，未声称通过 Ruff。

## 剩余范围

P2 活动订单集合、P3 检查点/报告结构优化未实施。未批量提前计算依赖仓位与成交反馈的策略，也未改变交易、资金计算和风险语义。旧的已导入脚本版本是不可变 bundle；它们不会因模板更新自动变更，需要用新模板创建新版本。

证据目录：`output/strategy-p0p1-20260912/`。前测保留在 `output/strategy-performance-audit-20260912/`。复现入口：`backend/scripts/benchmark_strategy_bar_audit.py`。
