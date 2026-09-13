# 策略回测：四条后续优化

工作树：`H:\program\CandleScope-strategy-replay-performance`，分支 `codex/strategy-replay-performance`。本轮继续在已有未提交修改上工作；未提交、未合并、未推送、未部署。修改前副本在 `output/four-paths-20260913/*-before.*`。

## 改动与适用范围

1. **单次原生入口**：`RowFactory.execute` 连续完成当前 BAR 的 observation 构建、一次用户回调、输出转换与 V1 transcript。保留原来逐根执行顺序。Unicode/定制输出回退时把已经算出的返回值交给 Python 完成，用户回调不会重跑。异常走原来的错误回执。planner、风控和 worker 监督仍在外层，provider 超时范围保持不变。
2. **按配置选择 BAR 循环**：Host 为精确类型的 `SimulationKernel`、`ContractAccount`、零资金费、零内核 warmup 选择专用循环；缓存循环内调用，去掉账户分派、资金费函数和 warmup 分支。出现辅助事件、资金费变化或账户替换时回到通用循环。账户 V2、预热等配置保留通用路径。撮合、决策记录、订单入队、权益采样、暂停和检查点顺序不变。
3. **标准 SDK 输出字段直读**：新增 SDK `NATIVE_OUTPUT_LAYOUT=1`。原生端对标准 `Signal`、`TargetPosition`、`OrderIntent` 读取字段、构造 Host 所需 payload 并封存原有输出字节，省去 Python `to_payload` 调用。检查类、方法和槽描述符的替换；子类、Unicode/DEL 和不符合边界的值走原转换。不是任意 Python 对象或任意 SDK 版本的通用内存布局假设。
4. **增量持久检查点**：已结束订单的连续前缀和不可变成交按每 256 条封存为 SHA256 寻址 JSON 分块。每次只编码新块、尾部与其余当前状态。活动订单所在块保持完整尾部；较早的长期挂单会阻止其后的订单前缀封存，成交历史仍可独立增量保存。事件、决策、权益及 provider 状态没有全部转为增量格式。

原生入口、字段直读、增量检查点默认 `1`。专用 BAR 循环未测出稳定收益，最终默认 `0`，保留为试验项。原生入口还要求字段直读可用，避免旧 SDK 或关闭字段直读时多走一次 C → Python 完成回退：

| 开关 | 设为 0 时 |
|---|---|
| `BACKTEST_NATIVE_ENTRY_ENABLED` | Python 编排现有原生输入/输出调用 |
| `BACKTEST_NATIVE_OUTPUT_FIELDS_ENABLED` | 调用标准 Python 输出转换，并采用 Python 编排入口 |
| `BACKTEST_SPECIALIZED_BAR_ENABLED` | 通用 BAR 循环 |
| `BACKTEST_INCREMENTAL_CHECKPOINT_ENABLED` | 写入完整检查点，仍可读取此前的增量检查点 |

旧扩展缺少可选方法或旧 SDK 缺少布局声明时保留对应旧路径。此前各轮开关独立存在；本轮对照保持它们开启，只切换上述四项。

## 持久化与恢复

数据库 schema **7 → 8**，新增 `backtest_checkpoint_chunks`。新块与 checkpoint 在同一 `BEGIN IMMEDIATE` 事务写入；RUNNING 状态、generation 和最新 sequence 校验在写入之前完成。旧 worker、旧序号不能覆盖新状态或清理其历史。无引用块、完成后的块与显式删除的检查点一并清理。

每个检查点直接引用所需块，不依赖前一个检查点。读取在一致的 SQLite 读快照内完成，先验证 manifest 和所有分块哈希，再展开为原来的完整 checkpoint/2，交给原有身份验证和恢复逻辑。缺块、坏块、manifest 损坏均拒绝恢复。公开 `kernel.snapshot()` 仍返回完整字典，不含分块引用；缓存只用于 Host 的持久化调用。

内存预算仍按**展开后完整状态的精确 JSON 字节数**计算，没有把较小的增量存储字节数当成放宽预算的理由。分块缓存仅保留列表引用、地址、长度和待提交的新块；不能把它理解为不再保留交易历史。

关闭增量开关即可停止写入新格式；这不降低数据库版本。需要回退旧二进制时，先停止该数据库的服务与 worker 并备份，然后在新代码的 backend 下离线执行：

```python
from pathlib import Path
from app.backtest.checkpoint_history import rollback_history

receipt = rollback_history(Path(r"实际离线数据库路径"))
```

它在事务中验证并展开全部增量检查点，删除分块表后把版本恢复为 7。任一分块损坏则整个回滚失败，版本保持 8。既有 Python bundle 回滚也接入了此还原步骤，原有非空 bundle/research context 的拒绝条件保留。本轮只迁移/回滚临时测试数据库。

## 验证与测量口径

Windows x64，Anaconda CPython 3.12.7，MSVC 14.44。原生扩展与 SDK wheel 重新构建后，通过无索引安装到新目录的 `-I` 验证；验证覆盖 `object_output`、`execute`、原有编码与 transcript。该安装目录的 `.pyd` 复制到当前 backend 后运行了原生与生命周期测试。

当前安装验证二进制 SHA256：`9f736bc40dc4b82a26efb0312a854519174358854c454ab7658dc0031cd2f615`。

测试覆盖原生两条路线的开关组合、bound/unbound transcript、方法替换和子类回退、只执行一次 callback、完整 worker 报告对照、跨服务重开并恢复数百笔成交、开关关闭后的恢复、坏块/缺块、过期 worker、旧序号、完整字节预算与离线回滚。

10 万根每次使用新数据库与新 worker；EXECUTION_REALISM_V2、交易解释开启、检查点间隔 10,000。计时含 worker 启动、策略、撮合、检查点、成本敏感性矩阵和报告持久化；不含数据生成、导入/冻结、先行 smoke、排队、报告读取及浏览器绘制。测量完全串行，不与构建或测试并行。

`backend/scripts/benchmark_four_paths.py` 可复现成对对照；普通组有五类 Python 和图表 SMA/RSI，每类三对，开关顺序交替。单项移除组 `--ablation` 与成交密集组 `--dense` 单独保存，不能跨组比较绝对耗时或把分项收益直接相加。

原始证据目录：`output/four-paths-20260913/`。

## 10 万根完整运行结果

42 次普通负载全部完成，报告哈希检查通过；21 对中 **13 对改善、8 对回退**。这是明确设定四项全开与全关的资格对照，不是最终默认三项开启的延迟结论。性能结果混合，没有把完整运行稳定压到 2–3 秒。最终不默认启用缺乏稳定收益证据的专用 BAR 循环。

下表“配对改善”是每次相邻开关对照的 `1 - on / off` 的中位数。不是跨轮中位耗时之比：本轮整机耗时波动很大，尤其 SMA 的跨轮中位数相除会得到夸大的 37.4%，不能把它当作稳定代码收益。没有定位外部波动来源，也没有据此删掉回退样本。

| 策略 | 开启耗时中位数 | 配对改善中位数 | 改善对数 |
|---|---:|---:|---:|
| Python 空脚本 | 2.569 s | -1.66% | 1/3 |
| Python SMA | 4.430 s | 9.27% | 3/3 |
| Python 状态机 | 3.878 s | 0.41% | 2/3 |
| Python 成交反馈 | 4.652 s | 7.15% | 2/3 |
| Python 直接下单 | 6.535 s | 3.06% | 3/3 |
| 图表 SMA | 6.921 s | -6.70% | 1/3 |
| 图表 RSI | 7.194 s | -1.70% | 1/3 |

证据：`final/samples.json`，三轮相邻顺序交替。适用范围是该合成产品路径，不能替代用户当前策略与浏览器的实际延迟。

## 分项证据与失败边界

- **原生入口 + 字段直读**：`components.json` 的 10 万次有状态 callback/回执组件测试，关闭两项的中位数为 3.005 s，合并开启为 2.864 s。所有组合的 transcript 完全相同。只开入口而字段走 Python 的早期实现反而增加回退开销，最终资格条件已禁止这种组合；旧 SDK 直接采用 Python 编排。该资格调整不改变上述完整运行的全开/全关路线。
- **BAR 专用循环**：组件测试通用空内核中位数 0.634 s，专用 0.643 s；三对中两对较快，一对较慢，没有可靠的总体加速证据。实现与快照等价已验证，但不把微小分支减少说成显著收益。
- **增量检查点**：成交密集 10 万根阶段测量，唯一切换增量检查点开关；两边最后 checkpoint sequence 均为 100000，共 12 次。累计 4.0419 s → 3.4086 s，单对减少 15.67%。证据 `dense-flushed-{0,1}.checkpoints.json`。这是带阶段计时的单对结果，不能推广为完整运行的稳定加速。
- **成交密集完整运行失败**：`--dense` 的 10 万根触发原有 `backtest report exceeds frozen byte ceiling`。基线和开启组均失败；保留 `dense/`、`dense-result-*`、`dense-flushed-result-*` 中的失败记录。没有扩大报告或内存上限，不将其计入完成率。部分早期失败 worker 在父进程清理前未写出最终 profile，因此新增了可选的每检查点阶段落盘，仅用于测量。
- **早期单项移除测试**：`ablation/samples.json` 的 18 次运行均完成，但波动较大，全开中位数 5.682 s、全关 5.432 s，不能支撑逐项收益归因。其中字段关闭组使用的是资格调整前的入口行为，应作为调整前证据保留，不能冒充最终入口条件。

普通负载的显式全开/全关数据与最终资格条件一致；专门开关组合的行为由最终回归覆盖。最终默认配置（专用循环关闭）尚无完整的三轮七策略配对资格数据。已实现四条路线不等于已经完成生产性能资格验证。

最终后端全组回归 **273 项通过**，证据 `final-tests.xml`；其后仅把无稳定收益的循环默认值收紧为关闭，并对该默认值与显式开关路线补做回归。安装产物验证收据见 `installed-receipt.json`。

默认值调整后的补验 **48 项通过**（与全组有重叠，`default-gate-tests.xml`），SDK 测试 **48 项通过**（`sdk-tests.xml`）。`git diff --check` 通过。

最终默认配置另外完成两次 100,000 根实际 worker 验证：Python SMA **4.828 s**、Python 直接下单 **5.420 s**，均 `COMPLETED`、处理 100000 根且报告哈希有效，分别有 797 / 2000 笔成交。证据 `default-SMA.json`、`default-ORDERS.json`。这是各一次完成验证，没有同轮默认配置对照，不能拿它们与早前耗时相除宣称加速比例。
