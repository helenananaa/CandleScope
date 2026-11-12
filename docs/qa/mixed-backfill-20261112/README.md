# H127 冷库混合回补接线（2026-11-12）

接线及官方录制验证产品提交：`e2706e167589b4a4e62916cdf17e8dd4df0dadf2`（主要接线 `5edf1b445c34232c12fd466fc4bfed409072ef4f`）；基线 `e38c9b1b57af81818c4f8034ff3639d90560ec68`。关联 #127，消费 #126/D126、#130/K130/B130、#124 归档与 #125 调度。父 issue 保持开放。

本批补上普通大周期闭合查询曾在基础窗口预算处提前延期、未产生回补需求的缺口。默认 DataManager 将真实目标需求交给既有 Coordinator/Scheduler/GapLedger。回补只为合格 Binance USD-M、默认 trade/base 身份、UTC epoch-zero 固定闭合范围提出粗细输入计划，沿用既有下载/归档/额度/规范写入/物化 owner。没有新 writer、额度表或第二个块缓存。

## 验证结果

接线产品 e2706e 完整本地回归 **1128 passed / 47 warnings / 141.01s**；40 项定向绑定/回补回归通过，架构边界与 `git diff --check` 通过。警告为现有 FastAPI lifespan/aiohttp 弃用提示。云端 PR CI 另行核对。

- 默认 facade → scheduler → 回补 → 规范存储 → 目标物化 → GapLedger 的隔离端到端测试通过；10007m 最终 `verified_contiguous=True`、剩余缺口 0、账本 `filled`。禁用提交只检测，不产生下载。规划预算失败不转为行情缺口。
- 实际 TransportLayer / HistoricalFetcher / pinned CCXT / HTTP loopback / normalize / SQLite 链路通过。epoch-zero 合成 10007m 使用 3 次 K 线请求，完整九字段一致，分钟库仅有实际取得的 2 根。元数据共享加载通过现有延期控制流重试。
- 官方 checksum 固定的 2026-10 Binance USD-M 1m/5m/15m/1h CSV 经 REST 类型转换，通过真实 CCXT HTTP socket 回放；8 个全新数据库，没有规范 K 线预置。新旧路线各输出 37 根，共 74 根可信闭合目标，按分钟 Decimal oracle 的 `rel_tol=1e-12 / abs_tol=1e-8` 对照通过。

| 官方录制场景 | 旧路线请求 / 输入 | 新路线请求 / 输入 | 新路线实际分钟持久行 |
| --- | --- | --- | --- |
| 89m × 12 | 2 / 1068 | 2 / 1068 | 1068 |
| 97m × 12 | 2 / 1164 | 2 / 1164 | 1164 |
| 101m × 12 | 2 / 1212 | 2 / 1212 | 1212 |
| 10007m × 1，非零 epoch 起点 | 11 / 10007 | 6 / 177 | 7 |

小周期三组因冷请求 fanout 更高而返回旧路线，诊断保留 `cold_rest_request_cost`。10007m 九字段的 oracle 差值全部为 0；较小周期增强成交额有原有浮点末位差异，完整向量保留在 report 中，未宣称逐位相等。请求计数指真实 loopback `/fapi/v1/klines`，元数据/时钟端点单独存在；不是公网耗时。

组件及故障回归还覆盖：65 个目标跨批恢复、来源/字段/网格边界、已有原生数据无重复下载、未知粗增强字段下一轮局部转细、同 acquisition 额外细输入阻止旧粗计划物化、配额延期后复用已提交来源、在途来源/日历/开关改变、回滚后旧路线重建、完整细输入未知字段保持 None、确认空来源保留耗尽证据。

## 硬边界及剩余关闭条件

- 单次一个 gap、最多 512 个目标/16384 输入行/4096 任务，纯计划每批 32 目标、32768 位置，总探索 131072；分页最多 256 行。提案工作预留 4MiB，搜索另行预留约 16MiB，执行输入按既有共同预算计费；没有提升全局容量。
- 大范围由既有调度器切块；超出资格或成本边界使用旧路线。最细数据未知时保留旧契约；不会把推测成分标为可信最终。
- REST 分页成本是有界启发式，未证明跨目标全局最优或完整归档/出口等待成本。网络粗输入失败目前沿用既有重试，再从规范数据重规划；未声称所有失败都在同一轮局部降级。
- 新 backfill reconciler 对本批有 16384 行硬界，但仍在批次内收集规范行后交给 K130；**不是任意规模端到端流式执行已完成**。
- 本批是源码、真实临时 SQLite、受控 socket 和官方录制源证据。回放 CSV 不等于公网冷下载资格或原生首屏性能。本机回归与回放并行，耗时仅为原始记录，不作为稳定延迟验收。
- 形成中尾部拼接、日历/session/DST 混合、更多 provider、首屏/warmup 公平调度、多图与实时并行性能、原生保存退出重启、跨平台验收，仍按 #127 原始清单继续。#126/#129 的自有验收保持独立。

## 重放与证据

`source-cold.py INPUT_ROOT NEW_OUTPUT_ROOT` 从项目根运行，`PYTHONPATH=backend`，依赖项目 pinned Python/CCXT 环境。输入沿用 `aggregation-core-closeout-20261112/inputs.json` 及四个官方 ZIP，执行前校验 SHA-256；每次全新 SQLite。

`evidence/index.json` 记录压缩原始回执 SHA-256。保留初次 socket 用例的元数据延期（测试最初未模拟 scheduler 重试）以及两次录制脚本错误：CSV 时间/笔数尚未转换 REST JSON 整数、错误调用同步 adapter 不存在的接口。修正测试/脚本后重跑；它们不是已通过的产品结果。没有删除原始失败记录。

综合回归首次临时启动脚本缺少 `__main__` 保护，导致多进程目录加载用例超时；中止时为 967 passed / 1 failed。修正脚本后 1125 项通过，最终围栏修改后 1128 项再次通过。原始失败 XML/log 与误指不存在测试文件的空收集记录均保留。

## 云端分层检查及修正

云端 [43173211327](https://github.com/helenananaa/CandleScope/actions/runs/43173211327) 为 1781 passed / 1 failed：新增 backfill 代码直接导入 DataManager 的 SeriesKey，违反既有分层规则。本地 1128 项命令未包含该方向性测试；单独 architecture 脚本也未覆盖该条规则，不能将其成功当作同一规则已通过。

产品修正 `d9ee7513cdd35abfdc2828d9bc26403edb68acc4` 将唯一 SeriesKey 定义移到中立 `data_engine.series_key`，DataManager 保留同一 class 的导出。backfill 和历史纯计划引用中立定义，没有放宽架构测试。字段、归一化、hash/equality、冻结及公开导出保持；旧导出身份、替换/深拷贝/pickle 往返回归通过。分层/混合/共享/来源身份定向 201 项通过，补充导出用例后的身份/分层 68 项通过。原始云端失败片段及新回执保留。官方录制源数值/网络结果仍明确属于 e2706e，未冒称在类型移动后重新进行公网或原生验收。
