# 策略回测：成功回执、空决策和历史记录展开

在 `CandleScope-strategy-replay-performance` 的既有未提交工作上继续优化。未提交、未合并、未推送、未部署。本轮修改前的主要文件副本保留在 `output/strategy-loop-20260913/*-before.*`。

本轮完整 10 万根测试的中位数下降约 **3.2%–14.3%**，改善较明显的是直接下单和成交反馈策略。21 组成对样本有 20 组改善、1 组 Python SMA 回退；不能据此声称生产稳定分位数。完整 2–3 秒目标仍未达到。

## 最终结果

Windows x64 / Anaconda CPython 3.12.7 / MSVC 14.44。每次新启动工作进程，以独立数据库运行 100,000 根合成 BAR，EXECUTION_REALISM_V2，交易解释开启，检查点间隔 10,000。包括进程启动、策略、撮合、检查点、成本敏感性矩阵和报告保存；不包括数据生成、导入冻结、先行 smoke、排队、报告读取和浏览器绘制。

仅切换 `BACKTEST_HOST_HOTPATH_ENABLED`，上一轮的通用原生输入、输出合并和紧凑 spawn 均保持开启。每类三轮，顺序为关→开、开→关、关→开，全部串行。五类 Python 与两类图表策略共 42 次运行；编译和回归测试不与最终计时并发。

| 策略 | 关闭中位数 | 开启中位数 | 中位耗时下降 | 开启后三次范围 | 成交数 |
|---|---:|---:|---:|---:|---:|
| Python 空脚本 | 2.576 s | 2.470 s | 4.12% | 2.404–2.796 s | 0 |
| Python 官方 SMA 3/5 | 5.344 s | 4.822 s | 9.76% | 4.679–4.952 s | 797 |
| Python 状态机 | 3.682 s | 3.442 s | 6.52% | 3.255–3.730 s | 796 |
| Python 成交反馈 | 4.927 s | 4.352 s | 11.67% | 4.336–4.678 s | 1563 |
| Python 直接 MARKET 订单 | 5.698 s | 4.884 s | 14.29% | 4.647–4.950 s | 2000 |
| 图表 SMA 3/5 | 4.954 s | 4.738 s | 4.36% | 4.641–4.789 s | 795 |
| 图表 RSI 14 | 4.822 s | 4.668 s | 3.19% | 4.575–4.743 s | 796 |

本轮绝对时间与上一轮存在波动，收益只按本轮相邻开关对照计算，不能拿上一轮更快的绝对样本推导当前代码回退或把跨轮差值全部归因于代码。没有测出或指定外部波动原因，也没有将小样本中位数当作 P95。

42 次均 COMPLETED，报告哈希校验通过，同类两侧成交数、1001 个权益点及报告字节数一致。不同 runId 的报告不能直接比较哈希；完整 result/report 相等由同一初始数据库的独立测试验证。

原始样本 `output/strategy-loop-20260913/final-<CASE>-<TRIAL>-<MODE>.json`；汇总和断言脚本为 `summary.json`、`summarize.py`。

## 实现

### 成功回执直接编码

原生 `RowFactory.record_success()` 将成功结果直接嵌入原 V1 请求/响应记录，以一次最终字节分配完成编码。Python 路径省去请求 ID 的字符串/字节转换、中间 response 字节和空输出的成功字典。warmup、空输出、标准输出以及绑定/未绑定的回执规则均保持原样；失败与不满足快速路径条件的输出继续使用原 `record_v1` 逻辑。用户方法仍动态逐根调用。

该方法是 ABI-1 的可选能力；旧二进制缺少它时自动使用旧路径。没有改协议、请求 ID 规则、配置身份、消息上限或回执哈希内容。

### 空决策原生编码

`empty_decision_hash()` 用原来的字段顺序、ASCII 转义及 SHA256 计算空意图决策链。只接纳有界 ASCII 前置哈希与 53 位整数；Unicode、长字符串、大整数及特殊类型回退到原 Python 编码器。

BAR 服务将可选函数提供给通用 SimulationKernel。simulation 包没有反向导入 backtest 策略适配器，原始 kernel 默认仍能独立运行。加速函数不进入检查点，恢复后继续沿用当前运行的等价实现。

### 历史记录展开

精确 SimulatedOrder/SimulatedFill 类型且全部字段为不可变原子值时，直接构造独立字典，避免 `dataclasses.asdict` 对每个字段递归分派与 deepcopy。金额仍为原 Decimal，字段顺序、类型、数值和拼写不变。自定义类型、子类和可变字段继续用 asdict 深度分离。

这用于 BAR 主内核的订单/成交检查点、最终成交结果和成交反馈。没有复用可变字典，没有缓存过期订单状态，也没有减少检查点次数或交易解释。

### 故障诊断扫描

未配置 `_fault_injector` 时，不再每根调用空的 before_decision 钩子，也不为 after_partial_fill 诊断扫描全部历史订单。实际故障注入仍保留原触发顺序、订单/成交计数和检查点行为；真实超时、取消、身份校验与预算控制未删除。

## 诊断与限制

最初轻量计时样本出现 **4.806→5.458 秒**的回退，保留为 `probe-{0,1}.json` 和 `stages-{0,1}.json`，没有计入最终三轮中位数。最终 Python SMA 第一组成对样本也为 **4.730→4.822 秒**，同样保留。

同进程小型测量 `micro.py` / `micro.json`：10 万次空决策哈希约 0.161–0.169 秒→0.151–0.156 秒，收益很小；1 万次成交记录展开约 0.065–0.068 秒→0.020 秒。它们不能替代完整服务延迟或相加宣称端到端收益。

因此，本轮解决的是固定编码和历史记录管理开销，没有完成整个逐根执行循环的原生迁移。继续冲击 2–3 秒应重点评估宿主逐根调用和完整结果链，而不能期待继续微调空决策字符串就得到大幅改善。

## 验证与工件

- 扩展回归 **231 项通过、4 条既有 FastAPI 弃用警告**：`regression.xml`。包括 SimulationKernel、架构边界、双时钟、V2 账户、图表批量、Python 批量、实际进程超时/取消、故障注入后的恢复、检查点、成本矩阵与完整报告。
- 独立安装验证后的原生工件复制到活动 backend 后，专项 **48 项通过、4 条警告**：`installed-active-tests.xml`。与前组重叠，不相加。
- 新测试覆盖原始成功 response 与新回执字节相等、绑定/未绑定哈希、全部 ASCII 转义、Unicode/大整数回退、恢复后的空决策链、原生错误与引用计数、可变记录递归分离、旧扩展回退、输出链开关组合、异常位置与反馈。
- 四类普通 Python 脚本分别在绑定/未绑定 V1 模式下，用实际 spawn 比较本轮开关两侧完整 result/report，全部相等。
- 新 native wheel 使用本机 MSVC 构建，独立 target 离线安装；SDK 未改动，复用上一轮相同 SDK wheel。`python -I scripts/verify_native_installation.py <installed>` 验证模块实际来自安装目录，并检查新旧回执、宿主输出与空决策哈希。
- 活动 `.pyd` SHA256 为 `d5b1391ac6e7374b29468a94fff9f01abea910b97b8a891023be295a8b25b4d4`，与安装验证及最终汇总一致。wheel 位于证据目录 `wheels/`，没有发布。
- `git diff --check`、修改文件的 Python 语法编译通过。未宣称真实用户数据、浏览器端、SANDBOXED_LOCAL 性能或其他操作系统本轮性能通过。

## 复现与回退

在工作树 backend 目录先按 `native/README.md` 构建并核对活动扩展具备 `record_success`、`empty_decision_hash`。此前优化保持开启：

```powershell
$env:BACKTEST_HOST_HOTPATH_ENABLED='1'
H:/program/CandleScope/.venv/Scripts/python.exe -m scripts.benchmark_strategy_bar_audit --bars 100000 --strategy PYTHON --python-case SMA --v2 --output ../output/strategy-loop-20260913/reproduction.json
```

设置 `BACKTEST_HOST_HOTPATH_ENABLED=0` 回到本轮前的对应路径。图表策略使用 `--strategy SMA` 或 `--strategy RSI`，移除 `--python-case`。不需要修改脚本模板或冻结 Run 的执行协议。
