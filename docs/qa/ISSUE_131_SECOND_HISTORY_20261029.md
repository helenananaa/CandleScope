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
