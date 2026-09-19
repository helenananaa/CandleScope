# 策略回测：反馈直传、报告分块与检查点策略

工作树：`H:\program\CandleScope-strategy-replay-performance`，分支 `codex/strategy-replay-performance`。在已有未提交优化上继续修改，未提交、推送或部署。这里只迁移了临时验证数据库。

## 实现与边界

1. `LocalPythonRunner` 的标准成交反馈直接传递已分离的对象，避免同一 worker 内 JSON 编码、严格解码、再复制的往返。仍生成原有规范字节和 transcript；回调异常沿用原错误回执，不重复执行用户回调。接受有界 ASCII、精确 JSON 基本类型及按原协议 `default=str` 规则转换的精确 `Decimal`；Unicode、浮点、定制对象或较大结构回到原协议路径。金额的小数位和对象所有权隔离保留。
2. Host 构建报告时只复制借用输入的分支，避免对刚构造好的整份报告再做一次深复制。公开 `build_report`、`seal_report` 默认行为不变。超出单文档上限的报告按明细分块持久化，保留完整报告格式和原始报告哈希。
3. BAR 任务可显式选择检查点策略。原有每 10,000 根保存的默认行为不变；允许调用方指定更大间隔、仅结束保存或不保存。每任务显式策略和 INTERVAL 的实际间隔写入冻结配置及配置哈希。省略新字段的旧调用保留原配置形式。

| 设置 | 默认 | 作用 |
|---|---|---|
| `BACKTEST_DIRECT_FEEDBACK_ENABLED` | `1` | 设为 `0` 恢复完整反馈协议往返 |
| `BACKTEST_OWNED_REPORT_ENABLED` | `1` | 设为 `0` 恢复报告整体二次深复制 |
| `BACKTEST_CHUNKED_REPORT_ENABLED` | `1` | 设为 `0` 恢复报告单文档超限拒绝；仍能读取已有分块报告 |
| `BACKTEST_MAX_REPORT_BYTES` | 16 MiB | 单报告头或单块上限，原有配置上限保留 |
| `BACKTEST_MAX_REPORT_STORAGE_BYTES` | 256 MiB | 分块报告逻辑总字节上限，允许操作者配置，必须覆盖一个块上限 |
| `BACKTEST_CHECKPOINT_EVENT_INTERVAL` | 10,000 | 默认间隔不再硬限制最多 10,000，仍须为正整数 |

本轮没有修改原生扩展或 SDK，也没有开启此前尚未证实收益的专用 BAR 循环。

## 报告存取

数据库 schema **8 → 9**，新增 `backtest_report_parts`。每块至多 256 行，超出字节预算则继续切分；单行仍超限时拒绝。块按 SHA256 去重，但总容量预算按逻辑引用计数，去重不会成为放宽总量的手段。

报告头、分块、最终状态及完成审计在同一事务发布。先检查状态和 generation，过期 worker 不能写入分块。完整读取在一致数据库快照中展开全部块，校验 manifest、各块及原始完整报告哈希；比较读取也保持同一快照。缺块或损坏不会被静默跳过。

原 `GET /api/v1/backtests/runs/{run_id}/report` 和导出继续返回完整报告。新增：

- `GET /api/v1/backtests/runs/{run_id}/report/summary`：摘要和各明细数量。
- `GET /api/v1/backtests/runs/{run_id}/report/details?section=fills&offset=0&limit=100`：明细分页，单页最多 500 行。

可分页明细：`fills`、`orders`、`trades`、`rejected_orders`、`order_events`、`equity_curve`、`ledger.order_events`。返回的 `reportHash` 标识对应完整报告，不能当作裁剪后摘要自身的内容哈希。摘要校验 manifest，分页校验 manifest 和实际读取的块；只有完整读取才核验所有块及完整报告哈希。

小报告仍内联，读取摘要/分页时需要解析并校验整份小报告。大报告分页只读取相交分块。**前端尚未接入新增接口**，现有页面仍走完整读取，因此不宣称浏览器首屏或渲染已经提速。报告构建与完整导出也仍会物化完整内容，本轮没有实现流式生成或消除峰值内存。

## 检查点使用

创建 BAR 任务可增加以下字段之一：

```json
{"checkpoint_policy":"INTERVAL","checkpoint_interval":50000}
```

```json
{"checkpoint_policy":"FINAL_ONLY"}
```

```json
{"checkpoint_policy":"NONE"}
```

`INTERVAL` 保存初始、周期和最终检查点；`FINAL_ONLY` 只保存最终检查点；`NONE` 不写持久检查点。后两种策略在产生最终检查点之前失败，无法续跑，恢复接口明确拒绝。最终 provider 状态预算检查、取消与超时监督、generation、撮合和审计检查继续执行。

不同检查点策略改变 snapshot 回调次数及策略 transcript，所以配置身份不同，不能宣称跨策略报告字节相同。财务结果等价检查使用没有 snapshot 副作用的测试策略。调用者需要按策略自身行为选择；其他 fidelity 暂不接受这些每任务字段。

## 离线回退

关闭写入开关不会降低数据库版本。需要使用旧版本代码时，先停止该数据库的服务和 worker、备份数据库，再在本版本 backend 环境执行：

```python
from pathlib import Path
from app.backtest.report_storage import rollback_reports
rollback_reports(Path(r"实际离线数据库路径"))
```

它在一个事务内验证并展开报告、删除报告分块表，然后将 schema 9 恢复为 8。任一分块缺失或损坏会整体回滚，保持版本 9。`checkpoint_history.rollback_history` 同时支持 8/9 → 7；原有 Python bundle 回滚也接入报告和检查点还原，原来非空权威数据的拒绝条件保留。展开后的大报告供旧版本读取，并不使旧版本具备新建超限报告的能力。

## 验证与性能口径

证据目录：`output/policy-optimization-20260913/`。实际 Windows worker、10 万根、EXECUTION_REALISM_V2、交易解释开启、默认检查点间隔 10,000。执行计时包括 worker 启动、计算、检查点与报告持久化，不包括数据准备、报告读取或浏览器。

`backend/scripts/benchmark_policy_optimization.py` 串行运行四类场景各三对，交换开关顺序。只切换反馈直传和报告所有权优化，分块存储在两组均开启，使密集成交对照都能完成。不能将该对照解释为所有新功能关闭与开启的比较，也不能与此前机器负载不同的绝对耗时比较。摘要、分页与完整报告读取单独计时，顺序固定，后续读取可能受数据库缓存影响。

此前密集成交的 10 万根任务因报告超过 16 MiB 失败。本轮首次验证已完成 10,611 笔成交，完整报告 33,186,350 字节，哈希校验通过；该次执行 18.556 秒，属于容量修复证据，不能单独用于证明加速。

回归测试先完成 **312 passed**（`tests.xml`），最终反馈 Decimal 路径及检查点配置修正后，相关定向测试 **74 passed**（`final-targeted-tests.xml`）。两组有重叠，不相加。覆盖 bound/unbound 回执、Unicode/浮点/超界回退、用户修改对象与异常、真实 kernel 成交金额、同一 run 的完整 spawned result/report 开关对照、报告重开/分页/比较、缺块/坏块、过期 generation、容量预算、部分发布事务回滚、schema 离线回退及没有检查点时拒绝续跑。

最后将新增报告/策略测试与可选原生测试的模块级跳过机制解耦，单文件再次 **35 passed**（`policy-final-tests.xml`），防止没有原生扩展的环境把报告存储检查一并跳过。`git diff --check` 通过。

`FINAL_ONLY` 和 `NONE` 另各完成一次 10 万根 SMA，均为 797 笔成交且报告哈希有效；仅用于策略路径可运行的验证，单次耗时不作为稳定加速比例。

## 最终成对结果

最终源码的 24 次实跑在 `paired-final/samples.json`，汇总在 `paired-final/summary.json`。每类各三对；以下是两组分别取中位数，正的下降比例表示用时减少。

| 10 万根场景 | 两项优化关闭 | 两项优化开启 | 中位用时变化 |
|---|---:|---:|---:|
| Python SMA | 5.865 s | 4.965 s | 减少 15.3% |
| Python FEEDBACK | 5.664 s | 5.119 s | 减少 9.6% |
| Python ORDERS | 6.073 s | 5.331 s | 减少 12.2% |
| 密集成交 SMA | 15.173 s | 15.819 s | 增加 4.3% |

SMA 的逐对用时变化为减少 5.1%、减少 17.0%、增加 9.8%；FEEDBACK 和 ORDERS 各三对均减少。密集组成对变化为减少 11.8%、减少 8.8%、增加 4.3%，关闭组范围 14.725–20.487 s，开启组范围 13.434–18.064 s。机器负载波动明显，样本只有三对，**不宣称密集组稳定提速，也不把普通组中位收益当作所有机器的保证**。

初版对照保留在 `paired/`，当时尚未覆盖真实反馈的 Decimal 直传，普通组中位耗时有回退；没有删掉不利样本。上述表格只使用完成 Decimal 路径修正之后重新运行的整组样本。

密集报告展开后仍为 **33,186,350 字节**；存储头为 **1,850,992 字节**、独立分块 **296 个**。开启组中位摘要读取 **53.5 ms**、100 行成交页 **104.4 ms**、完整读取 **1.785 s**。这些是服务层读取，不含 HTTP 传输或浏览器绘制；完整读取发生在摘要和第一页读取之后。

结论：普通策略本轮测到了有限的端到端收益；密集场景主要解决了报告容量和按需读取，速度仍需继续定位。恢复检查点现在是明确的调用策略，尚未把关闭检查点作为默认加速手段。
