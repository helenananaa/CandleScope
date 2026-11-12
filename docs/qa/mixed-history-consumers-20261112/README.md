# #127：默认闭合历史读取采用混合块（2026-11-12）

本次交付 **已存在规范数据的默认读取/物化接线**，不关闭 #127。
普通 `QueryEngine.query` 的闭合固定范围和 `query_before` 在目标物化未命中后，
可以使用 H127 混合组成；保留原 admission、形成中/日历/其他市场路线及原物化 owner。

- 基线：`9487b1c6ec657b726b204e1ab3a973c996ef8ce6`（#366 合入后的 main）。
- 产品：`acc4ddabdec8eef0d5a1f0a45bbf490beb6dffce`。
- 本机：macOS arm64，CPython 3.12.15；完整平台信息见录制数据报告。
- **705 passed，5 个依赖废弃提示**；JUnit 0 failure/error/skip。架构检查及 `git diff --check` 通过。
- 本次没有原生包、实时并行、多图、公网下载延迟或 Windows 验收；不得沿用 #130 的旧原生包证据来声称新 consumer 已验收。

## 来源与一致性

provider capability 的可选 `HistoryCompositionPolicy` 声明字段、网格、默认 trade/base 身份、
UTC 固定边界、可信闭合及证据。首阶段只允许 **Binance USD-M futures 的 1m/5m/15m/1h**，
全部九字段；没有把同一交易所的现货、其他网格或其他交易所自动提升为已合格。
具体官方样本为 2026-10 BTCUSDT 月归档的前 16 天，下载 URL、官方 checksum 和 SHA256
由 [原始来源记录](../aggregation-core-closeout-20261112/evidence/inputs.json) 固定。
这是受测样本和字段口径依据，不保证其他日期或产品的数据质量；在线每次仍检查实际组成。

独立原生粗 K 线的修订号与细 K 线不能比较大小。默认 consumer 对更细的所有原生网格
（包括尚未获准参与混合的 3m 等）做规范数据/删除检查；有任何更细记录就保守转细，
细数据不完整时不以旧粗数据填平。已有 D126 合并删除范围覆盖该 span 时也转细，
因此不能把“细记录已不存在”当作允许重建被删除历史的证据。

整个响应有一个 B130 多来源 view，各 H127 目标回执、当前 D126 修订/删除证据必须匹配。
最终 fence 后才交给既有 materialization registry、D126 writer 和 BarCache。
读取途中 amendment/delete、换存储、换资格/resolver、关闭 rollout 或修订证据不可用均返回 pending，
没有把过期结果改造成新来源缺口。查询没有新下载器、块缓存、永久修订表或旁路 writer。

完整本地单基础输入的一页范围优先走原路线；这次 count 只选择 executor，不证明最终性或覆盖。
10007m 等较大细输入可经 H127 分页，避免原大 base-window 预留导致的预算延期。
`QueryConfig.mixed_custom_history=False` 可回退单基础读取，保留来源/修订和语义有效的目标物化。

## 官方录制数据：默认入口前后对照

`source-default.py` 使用真正默认 `DataManager/QueryEngine`、临时 SQLite、K130/B130/H127 和原 writer。
同一输入、同一边界，基线和产品分别串行运行。89/97/101m 各 12 根、10007m 1 根；
每种「只存所需粗细组成 / 只存完整分钟」运行 3 个独立 DB，再各查一次已物化目标。
**每边 48 次查询**；产品全部完整、可信闭合，与独立 Decimal 分钟参考的九字段相符，
容差固定 `rel=1e-12, abs=1e-8`。1m 持久行数前后不变，目标完成不冒充分钟已覆盖。

| 输入及目标 | 基线默认查询 | 产品默认查询 | 产品目标未物化，中位数 | 再读物化目标，中位数 |
| --- | --- | --- | ---: | ---: |
| 混合组成，89m × 12 | 不完整 | 完整，117 个组成 | 1002ms | 15.4ms |
| 混合组成，97m × 12 | 不完整 | 完整，119 个组成 | 1021ms | 14.6ms |
| 混合组成，101m × 12 | 不完整 | 完整，112 个组成 | 1041ms | 13.8ms |
| 混合组成，10007m × 1 | 预算延期 | 完整，177 个组成 | 294ms | 13.4ms |
| 完整分钟，10007m × 1 | 预算延期 | 完整，10007 个组成，分页 | 3730ms | 13.4ms |

物化路径保留。小周期完整分钟输入的未物化基线中位数约 90/96/99ms，产品约 118/119/121ms；
产品多一次 count 和资格检查，**本次没有证明这个分支提速**。
89/97/101m 混合未物化分别有 149/163/180 次规范读取（其中 H127 52/55/58，
其余为细来源探测和 count，另含目标 probe）；只有较少输入行，并没有较少 SQL 调用。
批量探测、跨目标读取合并和总请求成本仍是后续必须优化的工作。

这些是新建 consumer/临时 DB、预先写入官方录制行情后的本机读数，**OS 缓存不是冷的**；
tracemalloc 开启、每组 n=3，不能宣称 P95/P99 或公网/原生首屏收益。
两边首个 query 的 provider 初始化/import 最大耗时分别约 13.9/14.5 秒，
最大 traced peak 约 104MB；原始异常值保留，未从回执中删除。
数据 fixture/导入不在查询 traced peak 内，tracemalloc 也不是 RSS。

10007m 完整分钟场景的 B130 最多 669 entries / 2,282,628 estimated bytes，
低于 1024 entries / 16MiB 上限；各次返回时 leases/views/inflight/retired 均为 0，
公共 memory budget reserved 为 0。没有通过提高缓存或页上限获得结果。

## 回归与证据边界

新增默认入口回归覆盖四个质数周期、range/before、物化快路径、九字段、分钟覆盖独立、
完整/部分 finer amendment、删除防复活、未合格 finer 网格、跨代写入禁止、资格/存储切换、
rollout 回退及复开、修订读取错误、10007m 细来源单页 SQL limit ≤257。
合并执行旧 custom query/streaming/materialization、来源修订、共享块、聚合核心、锚点/日历、
实时增量/BarAggregator 和 Pyne removal，合计 705 项。

能力矩阵另发现 main 已存在的 OKX open-interest `period` fixture 漂移：未改产品的基线单测同样失败。
本次只补 fixture 的现有 9 个 period 声明，保留严格矩阵比较；没有放宽产品验证。
原始失败记录一并保留。

最初录制脚本把基线的未闭合、非 trusted 的不完整 fragment 错当完整参考而失败；
核实其 `is_closed=False/trusted_final=False` 后，只对完整可信输出逐字段比较，并单独计数 fragment。
另一次脚本预期基线 10007m 完整分钟必成功，但实际为 memory_budget_deferred；
现将这个产品差异明确记录。最终两侧回执完整保存，没有把这两次试跑当作产品通过证据。
所有试跑 DB 和日志留在本机 output，不覆盖历史输入。

文件和 SHA256 见 [evidence/index.json](evidence/index.json)：最终测试日志/XML、架构检查、
baseline/candidate 原始 48 次回执与受控 fixture 失败。`source-default.py` 可在两个 checkout
分别设置 `PYTHONPATH=<checkout>/backend` 后重放；输入可用此前 QA 的 `download-inputs.py`
下载到全新目录（该脚本固定 checksum），每次输出目录必须不存在。

## #127 仍需完成

- 空库混合计划接入已有 BackfillCoordinator 下载/额度/归档与统一物化，不能让默认读取自己下载。
- 闭合 prefix 与形成中 tail 的首开接续、取消、warmup/深历史调度与公平性。
- 日历/边界来源资格及明确拒绝/降级；更多市场逐个验证。
- 上述 SQL 探测成本、真正冷读/多图/实时并行和原生用户流程；按原清单测尾延迟、RSS/CPU、请求/额度和回滚。

本报告只完成 #127 的一个接线缺口，不能替代以上原关闭条件，也不关闭 #126/#129。
