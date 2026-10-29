# #131：1s 常规历史实施与验证

基线：`origin/main` / `b84b5e3d514e43fca556613fe107e29d12f7a329`。
分支：`codex/issue-131-second-history`；在独立 worktree 实施。

## 已实现的范围

- 1s 权威收盘与修订共用现有 durable delivery journal，写入成功后发布，失败保持可重试和可恢复。
- 普通历史查询和向前分页可以从 SQLite 读取 1s，并通过现有协调器回补缺口。
- 现有手动下载任务可保存 1s，复用下载集合和保护范围；没有新增下载或录制流程。
- 统一 SQLite 清理支持 `seconds` 档；默认值 86,400 **条/序列**，不是固定保存 24 小时。条数清理仍默认关闭，自动 GC 的原有启用条件保持不变。
- 设置预设的秒级条数：紧凑 3,600、标准 86,400、宽裕 604,800、不限 0。旧的不限设置迁移后秒级仍为不限。
- 1s 的独立内存容量继续生效，与持久化分开；冷缓存可以清除并从 SQLite 恢复。
- 交易所能力检查保持生效；原生来源扩展见下文。没有持续采集器或 1s 回放归档；回放目录仍排除 1s。
- 原有订阅所有权保持生效：全量自选订阅和自定义秒周期仍可能需要 1s；最后一个消费者释放后停止上游流。

## 自动验证

后端相关回归：**362 passed**，4 条现有 FastAPI lifespan 弃用提示。
覆盖权威/非权威收盘、修订、写入失败重试、进程退出后的 pending/committed 恢复、
新进程读回、历史分页/缺口、内存容量、统一清理及下载集合保护、最后消费者释放、
手动下载与不启用 1s 回放归档；同时保留 1m 回归。

运行范围：`test_second_history_lifecycle`、`test_interval_resolution`、
`test_bar_delivery_journal`、`test_bar_delivery_bridge`、`test_query_engine_paths`、
`test_replay_catalog`、`test_storage_retention_gc`、`test_data_manager_gc`、
`test_gc_execution_safety`、`test_gc_settings_validation`、`test_settings_api`、
`test_data_engine_phase1_boundaries` 和 `test_manual_history*`。

前端：设置与 API 测试 **37 passed**；`typecheck`、`check:i18n`（30 locales）、
`lint` 和生产 `build` 全部通过。构建仍有原有的大 chunk 提示。

测试使用隔离 SQLite。复用了本机 Python 测试解释器，只在 worktree 的
`output/issue-131/python-deps` 安装测试解释器缺少的两个、与 requirements 同版本的
代理依赖；未修改原 checkout 的环境。前端用 `npm ci --ignore-scripts` 安装独立依赖。

## Binance 现货真实链路

使用隔离配置与数据库，连接公开行情；直接装配生产 `TransportLayer`、
`BackfillEngine`、`BackfillCoordinator`、`ManualHistoryService`、`DataManager`
及 `ExchangeIngestionFactory`，没有替换行情数据、存储或下载执行器。

| 检查 | 结果 |
| --- | --- |
| BTCUSDT 1s，现有手动下载任务 | SUCCEEDED；60 条；连续范围验证通过 |
| 实时订阅写入 | 观察到 1 条 `data_manager_exchange_closed`；journal pending 0；无 delivery failure |
| 最后消费者释放 | stream 已停止；释放后 2 秒观察中行数未增长 |
| 独立新 Python 进程的普通历史查询 | 从 storage 读取 60 条；complete=true |
| SQLite 完整性 | quick_check=ok |

本地原始证据位于 worktree 的 `output/issue-131/`：
`live_smoke.py`、`live-result.json`、`live-smoke.log`、`backend-regression.log`、
`frontend-tests.log`、`typecheck.log`、`i18n.log`、`lint.log`、`build.log`。
这些文件与隔离数据库为本地验证产物，不作为应用数据发布。

## 验证边界

首阶段完成代码、集成回归和 Binance 现货后端链路验证。后续原生来源扩展及其验证见下文。
没有进行打包后的 macOS UI 验收或长时间多币种压力测试；短时样本和两秒停流观察
不代表长期吞吐、磁盘增长或断网稳定性结论。


## 原生 1s 来源扩展（本次追加）

本次只接入交易所原生秒 K 线，复用原有图表、下载任务、SQLite、回补和清理。
没有逐笔成交合成秒 K 线，也没有录制、独立下载入口或 1s 回放归档。

| 来源 | 历史 | 实时 | 真实 60 秒窗口下载 / 新进程读取 |
| --- | --- | --- | --- |
| Binance USD-M 永续 | continuousKlines，PERPETUAL | continuousKline_1s，保留原始收盘标记及成交字段 | 60 / 60，complete=true |
| OKX 现货 | 现有原生 1s 历史接口 | 现有原生 candle1s | 60 / 60，complete=true |
| OKX 永续 | 现有原生 1s 历史接口 | 现有原生 candle1s | 60 / 60，complete=true |
| Gate 现货 | spot/candlesticks，保留结束标记 | REST 轮询；实测 WS 拒绝 1s | 60 / 60，complete=true |
| Upbit 现货（韩国端点，BTC/KRW） | 原生 seconds，按最多 200 秒的完整窗口请求 | 原生 candle.1s，适配 CCXT 的单行返回值 | 38 / 38，complete=true |

五条生产后端链路均观察到实时收盘数据经 durable journal 落盘，释放最后消费者后
stream 停止；已接收数据的 journal 收尾完成后，观察两秒行数不再增长。
全部 pending=0、delivery failures=0，独立 Python 进程读取普通历史均完整，SQLite quick_check=ok。
Binance 原有分钟接口保持原路由；Gate 衍生品不因现货能力而开放 1s。
独立 CCXT binanceusdm/binancecoinm 插件没有本次连续合约适配，不再误报 1s；
使用 CandleScope 的 Binance / futures 市场入口。

Upbit 不为没有成交的秒生成 K 线。实现单独持久化经过有界 REST 页证实的空秒范围，
查询、向前分页、缺口扫描、下载封存和补数验证共用这些证据。不插入虚拟 OHLCV。
空页不会提前结束后续窗口；异常/无效页面不会形成空秒证据；删除一根真实 K 线仍会
产生待修复缺口。晚到的真实 K 线会撤销冲突证据，用户删除及条数清理同时清除相关证据。
普通分钟周期的日历行为保持原样。

OKX/Upbit 的 1s 上游历史保留约三个月：历史规划限制上游获取范围，现有下载计划展示
受保留期限制后的有效起点及 provider_retention 原因。保留期边界在运行期间会继续移动；
本次真实下载验证为近期窗口，未验证三个月边界或超大范围下载。

本次相关后端回归 **479 passed**（4 条原有 FastAPI lifespan 提示）；随后对存储、
稀疏证据和分页的修订回归 **151 passed**，最后的删除/保护范围修订回归 **156 passed**。
见本地 `test-final-storage.log`、`test-final-cleanup.log`；这些集合有重叠，不相加计算独立用例。
未改前端代码；首阶段前端检查结果见上文。本次未进行打包后的 macOS UI 验收。

本地证据目录：`output/issue-131/native/`。成功报告为 `binance-result.json`、
`okx-result.json`、`okx-swap-result.json`、`gate2-result.json`、`upbit-final-result.json`；
`live_smoke.py` 为可参数化的生产链路验证脚本。首次失败日志保留用于说明发现的
Upbit 单行适配缺陷与 Gate 已接收 journal 数据需等待收尾的验证修正。

接口依据：
- [Binance USD-M 连续合约历史](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data#continuous-contract-klinecandlestick-data)
- [OKX 历史 K 线](https://app.okx.com/docs-v5/en/#order-book-trading-market-data-get-candlesticks-history)
- [Gate 现货 K 线](https://www.gate.com/docs/developers/apiv4/en/spot/#market-k-line-chart)、[WS 通道](https://www.gate.com/docs/developers/apiv4/ws/en/#candlesticks-channel)
- [Upbit 秒 K 线](https://global-docs.upbit.com/reference/list-candles-seconds)、[原生实时秒 K 线](https://global-docs.upbit.com/reference/websocket-candle)


## 成交聚合与自定义固定周期扩展

在前述原生 1s 实现之后，新增按交易所和市场明确准入的成交聚合来源。
路由顺序为：原生目标周期 → 可精确拼接的原生小周期 → 已准入的完整成交窗口。
前端自定义周期、历史加载、向左分页、重连补数、自选订阅和请求预算共同使用该能力。
原生周期目录不会因为成交聚合而虚增。周/月周期保留原有对齐语义；成交兜底只接受
以 UTC epoch 对齐的整秒固定周期，且仅用于默认加密市场序列身份。

首个成交来源为 **Kraken 现货**；支持 1s、7s、61s 等无法由其原生分钟线精确拼接的周期。
Binance 等已有可组合原生来源继续优先使用原生 K 线。尚未准入的交易所不会仅因
具备 recent-trades 接口而被宣称支持完整历史。后续来源需实现并验证自己的完整分页契约。

Kraken 使用官方 `since` / `last` 游标遍历，不用时间戳加一跳页。按成交 ID 去重，
用事件时间和 ID 排序，Decimal 汇总 OHLCV；冲突重复、缺少 ID、逆序、游标停滞、
分页耗尽和中途错误均不能发布未验证的该窗口前缀。未闭合桶只作为 forming 更新。
完整闭合窗口使用独立来源 `trade_history_verified`，经现有聚合器和 durable journal 落盘。
实时采用 REST 轮询并复查重叠窗口；最后消费者释放后停止。

无成交桶不生成虚假 K 线。经过完整分页证明的空桶范围单独保存在 SQLite，
供查询、缺口扫描、下载封存共同使用；新到真实 K 线撤销冲突证据，删除与 GC 清理
相应证据并保留保护边界旁的范围。空页只证明请求窗口，不被解释为全局历史耗尽。
普通交互每次最多 100 桶 / 10 分钟（周期大于 10 分钟时允许一桶），手动下载继续分块；
交易所适配器每窗口最多 100 页、每页 1000 笔，超限返回失败而非声称完整。
这属于普通按需历史；未新增录制、常驻采集器或回放归档。

### 真实链路与界面

隔离生产后端连接 Kraken BTC/USD，手动下载 70 秒 / 7s 窗口：8 根真实 K 线，
包含无成交桶，任务 `SUCCEEDED`、连续性验证通过。实时新增 3 根经验证收盘线，
journal pending=0、failures=0；第二个消费者保留时流继续，最后消费者退出后流停止，
收尾后两秒内行数稳定。新 Python 进程从 storage 读取同样 8 根，complete=true，
SQLite quick_check=ok。

浏览器连接 worktree 隔离服务，实际完成创建 7s、首屏出图、服务重启与页面刷新、
7s → 原生 1m → 7s 切换、向左拖动加载更早历史、回到实时。历史范围最终返回
80 根 / expected=80、history_state=ready、complete=true、missing_ranges=[]；
向左加载后界面超过 220 根，加载状态正常结束。
验证中发现并修复前端预算仍拒绝成交来源、缺口扫描缺少周期导致日历解析失败的问题。
Kraken 盘口曾短时显示重同步，随后恢复；盘口链路未在本次改动。

证据：`output/issue-131/trades/kraken-final-result.json`、`restart-final.log`、
`ui-range-final.json`、`kraken-7s-ui.png`、`backend-ui-final.log`。
复现脚本为同目录 `live_smoke.py` 和 `restart_read.py`；所有服务与数据库均为隔离测试环境。

### 验证范围与限制

自动回归覆盖原生优先、市场/身份限制、排序/去重/边界、分页停滞、分页预算、
错误/取消不发布前缀、forming 最终性、空桶持久化与清理、缺口扫描、durable delivery，
以及前端创建/恢复/订阅/各加载阶段的预算。完整结果见下列最终检查记录。

本阶段验证了开发态真实浏览器 UI 和生产后端组件，未打包进行 macOS 桌面验收，
未进行多币种长期压力、长历史及真实断网恢复测试。Kraken 的成交兜底是 REST 轮询，
不承诺逐笔低延迟；高成交密度或很长的单桶可能达到分页上限并保持待修复。
短时成功不代表所有市场与历史范围都已验收。

接口依据：[Kraken Recent Trades](https://docs.kraken.com/api-reference/market-data/get-recent-trades)。


最终自动检查记录：

- 后端相关集合 230 passed，重启子进程用例首次因 20 秒冷导入超时失败；
  将该耐久性用例的子进程启动上限改为 120 秒，保留所有数据断言，单独复跑 1 passed。
  新增 GC 保护用例后成交来源集合 15 passed；去重后本阶段共 232 个相关用例通过。
- 前端相关集合 127 passed；补全新增用例的交易所市场类型字段后，该文件 2 passed。
- 全仓 typecheck（应用源码及测试/配置）通过；生产构建通过，保留既有大 chunk 提示。
- 全仓 lint 完成，0 errors；唯一新增的多余 Hook 依赖警告已修复，并对该文件定向复查。

日志：`backend-final.log`、`backend-recheck.log`、`restart-regression-final.log`、
`frontend-regression.log`、`frontend-fixture-recheck.log`、`typecheck-final.log`、`lint-final.log`、`lint-hook-final.log`、`build.log`。
首次失败日志保留，避免把冷启动超时当作未发生。真实新进程读取另有独立成功证据。


## 多交易所成交聚合扩展

在 Kraken 现货基础上新增 9 个交易所目录来源，共 10 个来源、23 种目录市场选择。
继续按原生目标周期、可精确组合的原生小周期、成交聚合的顺序解析；
1s、7s、61s 等整秒固定周期共用普通图表、历史查询与手动下载。
录制、常驻采集和 1s 回放归档仍不在范围内。

| 目录来源 | 本次准入市场 | 成交历史边界 |
| --- | --- | --- |
| Kraken | 现货 | 既有 since / last 游标；受分页预算约束 |
| Bitfinex | 现货、线性永续 | 有界时间查询，无本地固定保留期声明 |
| Bitvavo | 现货 | 有界时间查询，无本地固定保留期声明 |
| Coinbase Exchange | 现货 | 从最新成交向前翻页，必须实际到达请求起点以前 |
| Crypto.com | 现货 | 保守准入最近 1 天 |
| Bitget | 现货、线性/反向永续、线性/反向交割 | 90 天；历史索引与最新成交衔接需验证 |
| Binance USD-M | 线性永续、线性交割 | 48 小时 aggTrades |
| Binance COIN-M | 反向永续、反向交割 | 48 小时 aggTrades |
| Deribit | 线性/反向永续、线性/反向交割 | 当前 API 保守准入最近 1 天 |
| Kraken Futures | 线性/反向永续、线性/反向交割 | 公共 executions 时间范围，无本地固定保留期声明 |

“无固定保留期声明”不等于任意年代均可用。所有来源都受接口实际可用性、
单窗口 100 次请求预算和市场上市/到期范围约束；交割市场的全部具体合约未逐一实测。
Deribit 六天前和两天前的公开查询实测返回空成功，一天前、12 小时前与近期窗口有成交；
因此没有沿用旧资料中的 7 天假设，也没有把旧空页认证为无成交。
本次不接入其单独的延迟历史服务器。Crypto.com 的一天是保守准入边界，非全历史能力声明。

### 完整性与入口

使用各交易所原始公共响应保留游标、分页标志和纳秒字段；不用统一 fetch_trades 的
截断结果推断完整性。满页递归拆分时间窗口，不能用末笔时间加一跳过同毫秒成交。
同毫秒仍满页、页数超限、无效价格/数量/市场、时间过滤失效、冲突重复、请求错误或取消
均使整个窗口失败，不发布已取得的前缀。Coinbase 游标必须严格前进；Bitget 的历史索引
必须追上与最新成交页的衔接点，不能把索引滞后误当作空历史。

保留纳秒和交易所序号；不按 UUID 字符串排序。反向合约成交量根据各接口的合约张数
或报价币名义金额换算为基础币，不能一律把 size 当基础币。无成交桶仍使用独立空桶证据，
按交易所/市场/商品/周期隔离，晚到数据、删除及清理撤销相关证据。

修通原有手动下载的两处限制：界面交易所/市场选择改用实际历史 K 线能力目录，
规划器接受通用 swap/future 及线性/反向市场；后端继续校验具体交易所的周期能力。
下载计划在估算前裁剪成交保留期，并展示有效起点。仅有 recent-trades 或尚未验证完整
分页契约的来源不因 CCXT fetchTrades=true 自动开放成交历史；已有原生秒线来源继续优先走原生。

### 本次验证

- 最终后端相关集合 **197 passed**，4 条既有 FastAPI lifespan 弃用提示。
  覆盖分页拆分/边界/饱和、取消/失败不发布前缀、排序/去重、合约成交量、
  来源准入、原生优先、保留期、手动下载市场、空桶隔离/撤销及此前秒线生命周期。
- 前端相关集合 **16 passed**；全仓 TypeScript 检查、改动文件 ESLint、生产构建通过。
  构建仍有既有大 chunk 提示。
- 9 个新增来源各使用一组真实公共行情和独立 SQLite，装配生产后端组件：
  Bitfinex/Bitvavo/Coinbase Exchange/Crypto.com 现货，Deribit/Binance COIN-M 反向永续，
  Bitget/Kraken Futures/Binance USD-M 线性永续。70 秒 / 7s 手动任务全部 SUCCEEDED，
  连续性通过；共享消费者保留订阅、最后消费者退出停流、journal 收尾后行数稳定，
  新 Python 进程读取相同条数且 complete=true，SQLite quick_check=ok。
- 原生 1m 对照：Bitfinex、Bitvavo、Coinbase Exchange、Crypto.com 现货，Deribit 线性和
  反向永续、Kraken Futures 线性永续、Binance 两类合约，共 9 组的 OHLC 一致，
  基础币成交量相对误差均小于 1e-6（反向合约存在换算舍入）。
- Bitget 现货和线性永续的同分钟样本，高/低/收盘价及成交量一致，开盘价不同。
  原生分钟线开盘价分别为 80099.02 / 80058.3，等于其上一根收盘价；
  成交聚合开盘价 80099.01 / 80059 与窗口内首笔原始成交一致。
  这两组不计为 OHLC 全相等，不承诺成交生成的所有周期复制交易所原生图表口径。
- 开发态浏览器实际选择 Bitget 线性永续、BTC/USDT:USDT，添加 7s、预览计划并提交任务。
  任务进入 BLOCKED_STORAGE：本机约 22 GiB 可用空间低于既有 10% 磁盘阈值。
  已保存证据并取消测试任务；没有绕过保护或删除用户数据。因此浏览器下载全流程
  **未通过完成态验收**，前述 9 组为独立后端组件链路证据。

首次 Bitget 市场目录请求超时、重复使用测试任务幂等键和原生对照未找到对应分钟等
失败日志保留；最终生命周期运行均使用唯一隔离目录。原生 Bitget 对照改用原始历史
candles 接口后取得对应分钟，并用原始成交与上一根收盘价解释差异。
未做打包 macOS 验收、多商品长期压力、全部交割合约、保留期全边界或真实断网恢复验收。

本地证据：`output/issue-131/trade-expansion/` 中的 `backend-final.log`、
`frontend-tests.log`、`typecheck.log`、`lint.log`、`build.log`、`lifecycle-final.log`、
`lifecycle-*.json`、`compare-*.json`、`bitget-open-control.json`、`deribit-retention.json`、
`ui-job.json`、`manual-download-ui.png`、`manual-download-storage-guard.png`。
`lifecycle_matrix.py`、`compare_native.py`、`compare_bitget.py`、`bitget_open_control.py`
为本地复现脚本；开发服务与浏览器测试页在验收后关闭。

接口依据：
- [Bitfinex 历史成交](https://docs.bitfinex.com/reference/rest-public-trades)
- [Bitvavo 成交](https://docs.bitvavo.com/docs/rest-api/get-trades/)
- [Coinbase Exchange 成交](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-trades)及[分页](https://docs.cdp.coinbase.com/exchange/rest-api/pagination)
- [Bitget 现货](https://www.bitget.com/zh-CN/docs/catalog/classic-spot-market/classic-spot-market)及[合约](https://www.bitget.com/docs/catalog/classic-contract-market/classic-contract-market)
- [Binance USD-M aggTrades](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Compressed-Aggregate-Trades-List)及[COIN-M aggTrades](https://developers.binance.com/docs/derivatives/coin-margined-futures/market-data/rest-api/Compressed-Aggregate-Trades-List)
- [Deribit 当前成交 API](https://docs.deribit.com/api-reference/market-data/public-get_last_trades_by_instrument_and_time)
- [Crypto.com 公共 API](https://exchange-docs.crypto.com/exchange/v1/rest-ws/index-insto-8556ea5c-4dbb-44d4-beb0-20a4d31f63a7.html)
- [CCXT Kraken Futures 适配器](https://github.com/ccxt/ccxt/blob/v4.5.60/python/ccxt/async_support/krakenfutures.py)，同时依据本地固定版本及实际公共 executions 响应验证字段与成交量。
