# 策略回测：合并输出链与紧凑 spawn 传输

在 `CandleScope-strategy-replay-performance` 的既有未提交工作上继续实现。未提交、未合并、未推送、未部署。

本轮五类普通 Python V1 策略的完整 10 万根执行中位数改善约 **3.8%–8.9%**。SMA 中位数 **4.18 秒**，成交反馈策略 **3.82 秒**；整体 2–3 秒目标仍未达到。

## 最终对照

Windows x64、Anaconda CPython 3.12.7、实际安装验证后的 MSVC 原生扩展。每个样本重新启动工作进程、使用独立数据库与 100,000 根合成行情。EXECUTION_REALISM_V2，交易解释开启，检查点间隔 10,000；策略仍逐根调用。

计时包含进程启动、策略、撮合、检查点、成本敏感性矩阵和完整报告保存。不含数据生成、导入/冻结、先行 smoke、排队、报告读取及浏览器绘制。不使用策略结果缓存，没有宣称清空操作系统缓存。

三轮分别按关→开、开→关、关→开的顺序串行执行，每轮覆盖五类策略，共 30 次运行。测试和编译不与最终计时并发。

| 普通 V1 策略 | 两项关闭中位数 | 两项开启中位数 | 耗时下降 | 开启后三次范围 | 成交数 |
|---|---:|---:|---:|---:|---:|
| 空脚本 | 2.437 s | 2.317 s | 4.90% | 2.218–2.348 s | 0 |
| 官方 SMA 3/5 | 4.434 s | 4.181 s | 5.71% | 3.981–4.208 s | 797 |
| 状态机 | 3.210 s | 3.088 s | 3.80% | 2.971–3.122 s | 796 |
| 成交反馈驱动 | 4.198 s | 3.823 s | 8.94% | 3.614–3.973 s | 1563 |
| 定期直接发出 MARKET 订单 | 4.485 s | 4.284 s | 4.49% | 4.122–4.541 s | 2000 |

15 组成对样本均改善，但三轮本机样本不足以声明统计显著性、生产 P95 或任意用户算法性能。所有运行 COMPLETED，报告哈希有效；同类策略两侧成交数、1001 个权益点、报告字节数一致。完整 result/report 与 V1 transcript 的相等另由同一初始数据库的测试验证，不能用不同 runId 的报告哈希互比。

证据：`output/output-pipeline-20260913/final-<CASE>-<TRIAL>-<MODE>.json`、`summary.json`、`summarize.py`。MODE 同时控制本轮两个开关；此前通用原生输入路径保持开启。这里的关闭侧是本轮前的快速实现，不是最早的逐根 IPC 基线。

早期只合并输出链的三组成对 SMA 样本为 6.366→6.135、6.903→5.965、5.780→6.177 秒，存在一次回退。保留在 `sma-*.json`，没有用后续联合优化的成绩宣称输出链单独稳定改善，也没有把不同时段的绝对耗时差全部算成本轮收益。

## 实现

### 输出链合并

`RowFactory.output_parts()` 一次生成原格式的输出回执字节与宿主构造参数。先封存 SDK payload 的回执，再在独立的宿主 payload 中补充 `targetExposure` 或 `qty`，计算与旧路径相同的状态哈希。标准 Signal、TargetPosition、OrderIntent 均可使用。

`LocalPythonRunner` 直接记录这些字节，并在原回执记录之后构造 StrategyOutput，省去 wire 字典、成功 response 字典及 `_to_host_output` 的重复拆装。没有跳过用户回调、改写 SDK 方法、复用可变输出对象或改变 V1 transcript。Unicode、DEL、复杂值、SDK 输出子类等仍使用原转换路径；支持运行中替换用户方法。

`BACKTEST_FUSED_OUTPUT_ENABLED=0` 回退到此前输出链。原生扩展继续使用 ROW_PROTOCOL_ABI=1，`output_parts` 是可选能力；旧 ABI-1 二进制没有该方法时继续走 `output_wire`，不因缺少新方法而失败。

### 紧凑行情传输

`spawn_events.py` 将标准 MarketEvent 的字段元组放入同一 multiprocessing pickle 流，减少 frozen dataclass 的逐对象状态编码/恢复开销。子进程仍收到 tuple[MarketEvent]；没有额外 pickle 文件、内存映射、全局 reducer、常驻策略进程或结果缓存。

只处理精确的 MarketEvent 类型、普通时钟/角色字段和标量字典 payload。重复事件的对象身份、共享 payload 字典、数字类型与拼写均保留；嵌套对象、Decimal、子类、循环图及不兼容构造器继续采用原 pickle 行为，不提前改变数据错误的处理规则。

`BACKTEST_COMPACT_SPAWN_ENABLED=0` 单独关闭这项优化。该传输位于既有 COLOCATED_BAR_V1 入口，适用于图表内置策略及 TRUSTED_LOCAL 工作进程；SANDBOXED_LOCAL 未改变。图表和批量协议已跑功能回归，但本轮性能表只覆盖普通 Python V1。

### 启动阶段探针

新增 `--spawn-timings`，在实际进程参数的 pickle 流两侧放置轻量标记，不增加额外 dump/load。记录进程 start、父进程行情序列化及写入、子进程行情反序列化/重建、worker 入口/出口和外围收尾。

最后相邻诊断运行均开启新输出链，仅切换紧凑传输：

| 诊断区间 | 传输关闭 | 传输开启 |
|---|---:|---:|
| 父进程序列化和流写入 | 0.708 s | 0.436 s |
| 子进程反序列化和行情重建 | 0.499 s | 0.267 s |
| start 至 worker 入口 | 0.736 s | 0.608 s |
| worker 内部 | 3.255 s | 3.135 s |
| worker 出口之后 | 0.225 s | 0.070 s |

父子区间可以重叠，序列化计时也可能含管道写入等待，不能相加当作独占 CPU 时间或可节省时间。收尾波动也不能全部归因于紧凑传输。记录在 `spawn-final-{0,1}.json`，不混入最终三轮中位数。

## 内存与验证

独立 SMA 峰值内存样本：两项关闭时父进程约 143.7 MiB、子进程 118.9 MiB；开启时父进程 122.2 MiB、子进程 113.1 MiB。使用生命周期 PeakWorkingSetSize，不是进程树同时峰值，父子值不能直接相加。这里未观察到额外峰值增长；不是长期内存稳定性或所有数据形状的保证。原始记录 `memory-run-{0,1}.json`。

- 扩展回归 **166 项通过、4 条既有 FastAPI 弃用警告**：`regression.xml`。覆盖普通策略、图表批量、Python 批量、完整报告等价、检查点、实际子进程超时/取消/恢复、stdout 限额和成本场景。
- 将独立安装验证的原生二进制复制到活动 backend 后，专项 **63 项通过、4 条警告**：`installed-active-tests.xml`。与上组重叠，不相加。包含后补的全 ASCII 输出字节及已有别名测试。
- 绑定与未绑定 V1 transcript、四类普通脚本实际 spawn 的完整 result/report 相等；输出对象脱离、引用计数、异常位置、动态方法替换、旧扩展回退与紧凑传输对象图验证通过。
- SDK 和 native wheel 已构建，并通过 `python -I scripts/verify_native_installation.py <installed>` 验证来自独立安装目录的输入、输出、宿主参数和 V1 回执。第一次无隔离构建因环境缺少 hatchling 失败，随后使用隔离构建依赖成功；安装阶段 `--no-index --no-deps`，未修改共享环境依赖。
- 活动原生二进制 SHA256：`9ae9d634dd501ccc02d87c76f496dbe53d9a25829154a06eaf27a89fcba62fa8`，与安装验证相同。wheel 位于证据目录的 `wheels/`，尚未发布。
- `git diff --check` 通过。没有浏览器端、生产实例或其他操作系统的本轮性能验收。

## 复现和回退

在本工作树 backend 目录，先按 `native/README.md` 构建并确认活动扩展有 `output_parts`。使用运行后端的 Python：

```powershell
$env:BACKTEST_FUSED_OUTPUT_ENABLED='1'
$env:BACKTEST_COMPACT_SPAWN_ENABLED='1'
H:/program/CandleScope/.venv/Scripts/python.exe -m scripts.benchmark_strategy_bar_audit --bars 100000 --strategy PYTHON --python-case SMA --v2 --output ../output/output-pipeline-20260913/reproduction.json
```

将两个环境变量设为 `0` 得到本轮前路径。只改其中一个可隔离比较对应优化。`--python-case` 还可使用 EMPTY、STATE、FEEDBACK、ORDERS；不添加 `--python-batch`。诊断可另加 `--spawn-timings ../output/spawn.json`，不要把带 cProfile 的结果混入普通延迟样本。

本轮没有把超时、检查点、费用场景、交易解释或报告降级以获取速度。进一步冲击整体 2–3 秒，应继续处理宿主逐根循环和输出回执的 Python 往返；仅靠启动优化不足以实现该目标。
