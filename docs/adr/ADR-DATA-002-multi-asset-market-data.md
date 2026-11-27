# ADR-DATA-002：多市场行情——统一数据来源契约，进入系统后数据平等

- 状态：Accepted（2026-11-26 用户确认，§10 的 Q1–Q7 全部按提议执行）
- 日期：2026-11-26
- 基线：`main@1a12541fe`（1.0.1）
- 关联：#572（数据、存储与行情来源）、#455（provider→venue 选择与旧引用映射）、#353（Bybit 与非 CCXT 自定义 provider）、
  #176（账户同步复用 CCXT）、#169（导入 K 线并入 `candlescope.db`）、1.2 插件层合并（16 个 `plugin_*` 包）、
  ADR-DATA-001（#621，按品种回补规划，以 identity 为键）
- 不在本 ADR 内：TradFi 实盘下单、期权、基本面与新闻、行情再分发。

## 1. 背景

### 1.1 目标

支持更多品种：美股、ETF、商品期货、原油、黄金、外汇等。

- 尽量用免费来源。开源项目不提供共享 key，由用户自己注册并填入 API key，数据只存本机。
- 实时和历史都要。
- **除了数据插件本身，进入系统后的数据要平等**：图表、指标、警报、策略（固定历史、FOLLOW、持续）、
  回放和练习账户都能用，不因来源或资产类型被区别对待。

### 1.2 现在有三条数据接入路线

| 路线 | 位置 | 能力 | 限制 |
| --- | --- | --- | --- |
| 内置 Python provider | `backend/app/exchanges/plugins/`（binance、okx、twelvedata）；CCXT 连接器 `exchanges/ccxt_ext/`（固定版本 fork 的 105 个交易所） | 最全：序列身份、交易日历、WS、限流、归档 | key 只能走环境变量（`INGESTION_TWELVE_DATA_API_KEY`，`data_engine/ingestion/config.py:181`），没有界面；内部接口 `ExchangePlugin`（`exchanges/plugin.py`）有十个方法，偏底层，Twelve Data 插件约 2,200 行 |
| Platform v2 公共 provider | `symbol-provider/1` + `market-data-provider/1`，sidecar，`candlescope.stream/1`；宿主侧 `plugin_provider_v2/runtime.py` | 操作层级合适：`symbols.list`、`history.read`、`stream.open/poll/close` | 只有 mock 参考实现；只有 K 线和深度；见 §1.3 第 6 条 |
| 统一 `.cspkg` full-trust 后端入口 | `plugin_lifecycle/` | 有宿主进程全部权限，有安装审核与摘要确认 | 没有注册数据来源的正式接口；startup 目标里没有 exchange registry |

Twelve Data（M1/M2，`docs/TRADITIONAL_MARKET_DATA_M1_zh.md`、`M2`）是传统金融来源的现成样板：
`identity.py`（序列身份）、`calendar.py`（XNYS 日历）、`runtime.py`（共享 WS 连接池）、按 credit 限流。

### 1.3 进入系统后并不平等

以下是读代码的结论，没有用真实 key 把 Twelve Data 的股票序列跑过策略和回放。

1. **序列身份在下游丢失。** 图表、存储、回补、指标都按 `KlineSeriesIdentity`
   （`data_engine/series_identity.py`：provider_id、venue、asset_class、series_variant、price_adjustment、
   session_variant、volume_semantics）区分序列，但下面几处只用 `exchange + market_type + symbol (+ interval)`，
   读不到时回落到默认的加密身份：
   - 策略测试：`ChartContextRequest`（`backtest/chart_context.py:41`）
   - 研究来源：`CurrentChartSource`（`research_data/contracts.py:93`）
   - 回放：`ReplaySeriesIdentity`（`replay/catalog.py:87`）
   - 数据准备：`query_klines(...)` 不传 `series_identity`（`data_preparation/bar_adapter.py:136`）

   前端的 FOLLOW 和持续策略会带 identity（`ChartStrategyTesterCellBridge.tsx`、`ContinuousStrategyPanel.tsx`），
   固定历史测试和回放不带。
2. **默认 24×7、每分钟一根。** 数据准备用 `(end-start)//60_000` 判断完整性（`data_preparation/bar_adapter.py:142`），
   股票收盘、节假日、期货日内休市都会被判成不完整。日历注册表已经存在（`data_engine/history/calendar.py`，
   有 `count_expected`、`expected_opens`、`open_segments`，Twelve Data 已注册 XNYS），只是这些消费方没用。
3. **持续策略写死加密货币。** `backtest/continuous_definition.py:50` 只收原生加密 UTC 1m OHLCV，
   期货只收 binance；前端 `strategy-research/researchSelectedVersion.ts:51` 和
   `backtest/continuous/ContinuousStrategyPanel.tsx:96` 也一样。
4. **功能按交易所名字开关。** 后端 19 处、前端 8 处（不算只读账户和命名）判断 `exchange == "binance"` / `"okx"`（§5 逐条列出）。
5. **模拟账户按加密永续设计。** `simulation/kernel.py` 有 `contract_multiplier`，但没有现金股票账户、
   期货每手保证金、休市不成交、开盘跳空这些规则。
6. **公共 provider 不能接带 key 的来源，产出的序列只能是加密身份。**
   - `secrets.use` 在 `UNAVAILABLE_HIGH_RISK_PERMISSIONS` 里，不可授予（`plugin_security_v2/grants.py:59`）。
   - 网络网关只允许 HTTPS；请求头白名单只有 `accept`、`content-type`、`if-modified-since`、`if-none-match`
     （`plugin_gateway_v2/network.py:31`），没有认证头，也不能开 WebSocket。
   - provider 没有 `supports_history_identity`，`exchanges/history_identity.py` 只接受默认身份，
     所以股票、期货只能被当成 24×7、币本位成交量的加密序列。
7. **凭据。** 只有 OKX 只读账户有 macOS Keychain 存储（`readonly_accounts/credentials.py`），Windows 没有；
   数据来源的 key 只能放环境变量。

### 1.4 已经在门口的 TradFi 数据

2026-11-26 拉取 Binance U 本位公共 `exchangeInfo`（无需 key）：有 249 个 `contractType = TRADIFI_PERPETUAL`
（246 个 TRADING），按 `underlyingType` 分：

| 类别 | 数量 | 例子 |
| --- | --- | --- |
| EQUITY（美股、ETF） | 209 | AAPL、NVDA、TSLA、SPY、QQQ、IWM |
| HK_EQUITY / KR_EQUITY / CN_EQUITY | 17 / 8 / 2 | HK0700、SAMSUNG、CXMT |
| COMMODITY | 8 | XAU、XAG、XPT、XPD、COPPER、CL（WTI）、BZ（Brent）、NATGAS |
| FX / PREMARKET | 1 / 4 | USDBRL；Pre-IPO 合约 |

- 24×7 交易：XAUUSDT、AAPLUSDT、CLUSDT 在 2026-11-21 至 11-23 的 1h K 线里，48 根周末 K 线都有成交量。
- `data.binance.vision` 有月度归档（`XAUUSDT-1m-2026-10.zip` 返回 200）。
- 实际运行的 Binance U 本位目录走 CCXT 通用加载（`ccxt_ext/generic.py` 的 `load_ccxt_symbols`），246 个
  TRADING 合约已经在目录里，只是没有分类，看起来和加密永续一样。原生目录
  （`exchanges/plugins/binance/adapter.py` 的 `_load_futures_symbols`）只放行 `PERPETUAL`，会把它们过滤掉。
  （本节初稿把原生目录当成了实际路径，D0 实测后更正。）
- CCXT 4.5.60 不认识这个合约类型，只是因为交割日是远期占位值 `4133404800000`，才碰巧被归成 swap
  （`binance.parse_market`，249 个里 248 个；SETTLING 的 ANTHROPICUSDT 有真实交割日）。
- 其他 CCXT 交易所的 TradFi 合约已经作为普通 swap 混在目录里，没有分类，并按 24×7 处理。
  CCXT 4.5.60 支持 Hyperliquid HIP-3 市场（`xyz:GOLD`、`xyz:CL`、股票，需要 `hip3.dexes` 选项），
  CandleScope 目录是否已加载它们未核实。

这些合约价格不是交易所原始行情：有资金费率和基差，周末价格由该交易所自己撮合。

## 2. 决定

1. **供应商差异只存在于数据来源（provider）内。** 进入系统后，所有消费方只认四样东西：
   序列引用（SeriesRef，§3）、品种规格（InstrumentSpec，§4）、交易日历（§4）、能力声明（§5）。
   不按来源名字分支，也不按资产类型分支。
2. **功能按能力开放。** 数据平等不等于所有功能都能用于所有数据。来源声明了能力就能用；
   没声明就明确提示不支持，绝不静默降级。
3. **统一契约，不统一运行方式。** 一个公共 provider 契约（§7），三种托管方式只决定信任级别，不决定功能。
4. **宿主负责难的部分。** 回补规划（ADR-DATA-001）、限额、重连、缺口账本、聚合、最终性校验和存储都由宿主做；
   provider 只把供应商协议翻译成契约。
5. **凭据由宿主保管（§8）。** key 只存本机，插件看不到明文，不做数据中转。
6. **向后兼容。** 不传 identity 等于现有默认加密身份；不迁移数据；已冻结的策略和回放 hash 不变。

## 3. 序列引用 SeriesRef

```text
SeriesRef = 路由 (exchange, market_type, symbol, interval)
          + KlineSeriesIdentity (provider_id, venue, asset_class, series_variant,
                                 price_adjustment, session_variant, volume_semantics)
```

- 不新增身份维度。现有 7 个维度已经覆盖股票、ETF、外汇、指数、商品（Twelve Data M1）。
- SeriesRef 进入：`ChartContextRequest`、`CurrentChartSource`、`ReplaySeriesIdentity`、数据准备的 requirement、
  练习账户的品种引用、导入数据集（§7.4）。
- 线上格式：在现有字段旁加可选的 `identity` 对象（与 FOLLOW 请求一致）。缺省时解析为
  `KlineSeriesIdentity.for_exchange(exchange)`。
- hash 规则：只有 identity 不是该交易所的默认值时才写进冻结上下文和 hash，所以现有运行、回放和工作区的 hash 不变。
- **期货换月**用 `series_variant` 表达：`contract`（单个到期合约）、`continuous.unadjusted`、
  `continuous.back_adjusted`、`continuous.ratio`。换月规则（按成交量、按持仓、到期前 N 天）记在派生序列定义里，
  复用合成序列（`docs/synthetic-series.md`）。策略在连续合约上成交时，按当时的主力合约记账；回放显示换月标记。

## 4. 品种规格与交易日历

### 4.1 InstrumentSpec

`SymbolInfo`（`exchanges/models.py:509`）已有：price_tick_size、quantity_step、min_quantity、contract_multiplier、
contract_value_model、currency、provider_id、venue、venue_mic、asset_class 等身份字段、underlying_symbol、
entitlement、delay_seconds、redistribution、上市/到期时间。还需要补：

| 字段 | 用途 |
| --- | --- |
| `underlying_class` | equity / commodity / fx / index / crypto。用于分组和关联，不进入序列身份 |
| `calendar_id`（品种级，可覆盖市场级） | 同一个市场里交易时段不同的品种 |
| `account_model` | `crypto_linear` / `crypto_inverse` / `cash_equity` / `futures_margin` |
| `funding` | 有没有资金费率 |
| `margin_per_contract`、`fee_defaults` | 期货保证金和默认手续费；没有就让用户填，不猜 |

模拟内核只读这些字段，不判断"这是不是股票"。

### 4.2 用交易日历判断完整性

- 所有"是否完整"和"有没有缺口"的判断改用 `calendar.count_expected` / `expected_opens`，
  替换 `(end-start)//60_000`。24×7 只是 `crypto.24x7.utc` 这一种日历。
- 回放跳过休市；策略在休市时不成交；隔休市的挂单在开盘时按开盘价判断成交（跳空）。
- provider 必须为每个市场（可选：每个品种）声明 `calendar_id`。未注册的日历直接拒绝，这是现有行为。
- 第一版只用一个日历：同一序列的盘前盘后作为另一条 `session_variant` 序列，不混进常规时段。

## 5. 用能力声明替换名字判断

能力声明挂在 `ExchangeCapabilities`：通道矩阵（`channels`，schema v3 的 `history_policy` 等）之外，新增具名角色
`roles`（`CapabilityRole(role, market_types, contract)`）。消费方问"这个市场声明了哪个角色、由哪个契约提供"，
不再比较交易所名字。`contract` 写明具体实现，所以只有一种实现的功能仍可以拒绝其他契约。

不能直接用通道代替：OKX、Bybit 等从 CCXT 通道合并得到资金费、持仓量历史，按通道放开会改变 OKX 的现有行为。
所以这些判断都改成显式角色，目前只由原生 Binance 声明；CCXT 的 `binanceusdm` 等场所不声明。
查询走交易所注册表；命令行工具和测试未初始化注册表时，内置的 Binance、OKX 直接读静态能力文档
（`app/exchanges/roles.py`，前端 `features/exchange-support/capabilityRoles.ts`）。

| 现有判断 | 改成 | 阶段 |
| --- | --- | --- |
| `replay/trade_import.py`（2 处）、`replay/remote_trade_archive.py`（2 处）、`replay/official_trade_history.py`、`data_preparation/trade_adapter.py`、`market_data/trade_flow_service.py` 缺口修复、前端 `trade-flow/tradeFlowHistoryApi.ts` | `trades.history.archive`（契约 `binance.public-data.um-agg-trades.daily/1`，Binance futures） | D3a |
| `replay/training/historical_book.py`（2 处）、`replay/training/admission_rules.py` 盘口辅助 | `book.history`（契约即归档来源 `BINANCE_USDM_DIFF_DEPTH_CAPTURE`） | D3b |
| `replay/training/hedge_inputs.py`、`admission_rules.py` 双向持仓、前端 `replay/trainingHubModel.ts` 双向持仓（改看后端计划的拒绝原因） | `hedge.public_history`（契约 `binance.usdm.hedge-public-history/1`：规则、费率、标记价、资金费归档） | D3b |
| `replay/training/display_service.py` 严格原生周期 | `history.native_archive`（契约 `binance-public-kline-v1`，Binance spot） | D3b |
| `data_preparation/replay_origin.py`、`data_preparation/market_random.py` | `history.earliest_page`（契约 `binance.klines.start-time-ascending/1`：按 startTime 升序翻页，能探到最早一根；Binance spot、futures） | D3b |
| 前端 `trainingHubModel.ts` 默认选中 | 优先选声明了 `hedge.public_history` 的市场；拿不到交易所目录时选第一个可用市场 | D3b |
| `backtest/continuous_definition.py` 期货、前端 `strategy-research/researchSelectedVersion.ts`、`ContinuousStrategyPanel.tsx` | `contract_rules`（契约 `BINANCE_USDM_LINEAR_BASE_QUANTITY`：线性、按基础资产数量，Binance futures）；实时和日历已在 D2c3 改完；前端在交易所目录未加载时交给后端判断 | D3c |
| `backtest/pine_risk_stops.py` | 市场声明的日历是 `crypto.24x7.utc`（OKX 由此可用 Pine 日内风控；窗口契约 id `BINANCE_UTC_24_7_V1` 进 hash，保留原名） | D3c |
| `backtest/pine_requested_data.py`、`indicator/pine_host_inputs.py`（2 处）、`backtest/strategy/pine_engine.py` | Pine ticker 命名（`.P` 后缀）移到 symbol normalizer：`pine_ticker()` / `storage_symbol_from_pine()`，默认原样返回，Binance 对 futures/usdm/swap 加减 `.P` | D3c |
| 前端 `advanced-market-data/useAdvancedMarketDataRuntime.ts`（4 处）、`market_data/service.py`（2 处） | `funding.hybrid_history`、`open_interest.native_grid` | D3d |

D3d 的角色名是计划，落地时按实际用途定，并更新这张表。错误码保持原样（如 `HEDGE_BINANCE_USDM_REQUIRED`），前端和测试按它们映射提示。

只读账户里的 OKX 判断（前端 `readonly-accounts/*`）属于账户领域，由 #176 处理；`utils/symbolKey.ts:35` 的
Binance 品种键规范化和 `i18n/t.ts` 的显示名属于命名，不是功能开关。数据引擎内部（`ingestion`、`storage` 围栏、
`ccxt_ext`）按场所实现协议，也不在本 ADR 内。
新代码规则：消费方出现 `exchange ==` 一类判断时，评审要求改成能力。

## 6. 实时数据：先临时，后最终修正

免费来源常见的情况是：实时只有部分成交（IEX）或只有 tick，历史才是全市场数据。

- 实时 K 线以 `forming` 进入，`source_quality` 标明来源，例如 `derived_from_iex`、`derived_from_ticks`。
  tick 来源由宿主聚合成 K 线。
- 收盘后，宿主用 REST 拿到全市场 K 线，通过 `bar.amended` 修正为 `final`（`candlescope.stream/1` 已有
  forming/final/corrected 语义）。一条序列里最终只有一种口径；策略 FOLLOW 和回放读 final。
- 延迟用已有的 `SymbolInfo.delay_seconds` 和 `entitlement` 表达：0 为实时，900 为延迟 15 分钟，日终另有标记。
  界面显示延迟；FOLLOW 和持续策略拒绝延迟来源，除非用户明确接受。

## 7. 统一 provider 契约 v2

### 7.1 契约

`market-data-provider/2`（与 `symbol-provider/2` 成对），在 v1 的操作上增加声明：

```jsonc
{
  "kind": "market-data-provider/2",
  "configuration": {
    "exchange": "alpaca",
    "dataPlane": "candlescope.stream/2",
    "markets": [{
      "id": "stock", "assetClass": "stock", "venue": "xnys",
      "calendarId": "xnys.regular", "currency": "USD", "accountModel": "cash_equity"
    }],
    "channels": [
      { "kind": "kline", "marketTypes": ["stock"], "history": true, "realtime": true,
        "intervals": ["1m", "1d"], "finality": "explicit", "corrections": true,
        "realtimeSourceQuality": "derived_from_iex", "delaySeconds": 0 },
      { "kind": "trade", "marketTypes": ["stock"], "realtime": true }
    ],
    "credentials": [
      { "id": "keyId", "label": "API Key ID", "inject": { "header": "APCA-API-KEY-ID" } },
      { "id": "secret", "label": "Secret", "inject": { "header": "APCA-API-SECRET-KEY" } }
    ],
    "quotas": { "ratePerMinute": 200, "wsSymbols": 30 }
  }
}
```

- `symbols.list` 每行返回完整的 SeriesRef 身份和 InstrumentSpec。
- 新增 `trade` / `quote` 实时通道，由宿主聚合成 K 线。
- 宿主校验声明（日历必须已注册、身份维度合法、额度有上限），然后接入同一条
  ingestion → 存储 → 聚合 → 回补管线。v1 manifest 继续有效，按默认加密身份处理。

### 7.2 三种托管方式

| 方式 | 谁 | 运行 | 网络与凭据 |
| --- | --- | --- | --- |
| 内置 | Binance、OKX、Twelve Data | 进程内 | 直接访问；凭据从宿主凭据库取 |
| 可信包 | CCXT 连接器、Alpaca、天勤等第一方或用户审核过的包 | 进程内，沿用 `.cspkg` full-trust 后端入口与安装审核 | 同上 |
| 沙箱 sidecar | 社区插件 | 现有 sidecar 隔离 | 宿主代为联网：HTTPS（v2 先做），宿主托管的 WSS（之后）；凭据由网关按声明注入 |

原有的 Binance、OKX、Twelve Data 和 CCXT 不重写，在宿主内部包一层适配器接到契约 v2 上。
`ExchangePlugin` 保留为宿主内部接口；`ProviderExchangePlugin` 已经是"契约 → 内部接口"适配器的雏形。
不另造插件系统（与 #455 的约束一致）。

### 7.3 CCXT 连接器

- **做成边界清楚、版本独立的连接器包，但留在进程内。** 它的每次网络请求都要经过宿主的共享限额、代理池和 WS 租约
  （`ccxt_ext/hooks.py`、`admission.py`、`docs/public-market-admission.md`）。挪到独立进程就得跨进程重建这些机制，
  深度和成交数据的延迟也会变差。
- **版本管理用现成的**：`backend/ccxt-fork.lock.json`（上游与 fork 提交、wheel 摘要、自定义 schema）、
  `backend/scripts/verify_ccxt_runtime.py`（必需方法检查）、插件发布标签 `candlescope-plugin-*`。
  宿主声明能接受的连接器版本范围和必需 schema；不满足就拒绝加载，不回退。
- **它是交易所连接器，不只是数据插件**：行情 + 账户（#176），契约按两个 contribution 设计。
- **独立发版本身不会开放更多品种**：品种来自交易所运行时返回的目录。TradFi 分类按交易所写在
  `exchanges/venue_underlyings.py`（原生目录和 CCXT 目录共用），不依赖升级 CCXT。

### 7.4 用户自己接数据

| 档 | 方式 | 说明 |
| --- | --- | --- |
| 零代码 | 导入 CSV/Parquet | 现在导入的数据走 `local-*` 和 `local_bar`（`replay/local_bar_repository.py`），策略走 `ImportedDatasetSource`，两条路分开。改成一个"本地 provider"，产出同样的 SeriesRef，和 #169 并库一起做 |
| 写脚本 | Python 模板实现 `symbols`、`history`、可选 `stream`，加一份声明清单 | 从文件夹热加载开发；用 `packages/plugin-conformance` 做一致性检查；分页循环、限流、重连、缺口由宿主负责 |
| 填 key | 内置来源在设置页填 key | §8 |

## 8. 凭据

- 把 `readonly_accounts/credentials.py` 的 Keychain 存储泛化成**宿主凭据库**，按 provider 和字段分记录；
  Windows 用凭据管理器（DPAPI）。和 1.1 的 Windows 只读账户（PL-5）共用一份实现。
- 设置页新增「数据源」：填 key、测试连接、显示权限和额度（实时还是延迟、WS 标的上限、剩余 credit）。
  环境变量仍可覆盖，界面显示当前值来自哪里。
- 注入方式按契约声明：请求头、查询参数（只在供应商要求时，例如 Twelve Data WS 握手）、WS 登录帧。
  沙箱插件只拿到凭据句柄，网关注入后再发出；日志和诊断脱敏（沿用 Twelve Data 的做法）。
- 不提供共享 key，不转发数据。免费档一般禁止再分发，`SymbolInfo.redistribution` 保留供应商声明。

## 9. 免费数据来源（2026-11-26 核实，额度会变）

| 品种 | 来源 | key | 实时 | 历史 | 接入方式 |
| --- | --- | --- | --- | --- | --- |
| 金、银、铂、钯、铜、原油、天然气、美股/港股/韩股（合约价格） | Binance TradFi 永续 | 否 | WS | REST + 月度归档 | 现有 Binance 插件，D0 |
| 同上（链上） | Hyperliquid HIP-3 | 否 | 是 | 是 | 现有 CCXT，D0b |
| 美股/ETF（交易所行情） | [Alpaca Basic](https://docs.alpaca.markets/docs/about-market-data-api)：IEX 实时、200 次/分、WS 约 30 个标的（较旧文档的数字） | 免费注册 | 分钟 K 线（IEX） | 2016 年起 SIP，不能查最近 15 分钟 | 可信包，D7 |
| 美股/外汇/商品 | Twelve Data Basic：8 次/分，800 credit/天，WS 最多 8 个标的 | 免费 | 仅价格 tick | 是 | 已接入 |
| 美股/港股（有券商账户） | [长桥 OpenAPI](https://open.longbridge.com/zh-CN/docs/quote/pull/history-candlestick)：账户默认 LV1，有 K 线推送 | 账户 | 是 | 有月度标的配额 | 可信包或社区 |
| 国内期货（au、ag、sc 等） | [天勤 TqSdk](https://doc.shinnytech.com/tqsdk/latest/usage/index.html)，快期账户 | 免费账户 | 是 | 免费版有限（具体额度未核实） | 可信包，D8 |
| 黄金/原油 CFD | [OANDA v20](https://developer.oanda.com/rest-live-v20/development-guide) 模拟账户（品种和地区限制未核实）；[Dukascopy](https://www.dukascopy.com/swiss/en/marketwatch/historical/) 免费历史 tick（XAU 1999 年起，Brent 2010 年起） | 模拟账户 / 否 | OANDA 有 | 是 | 社区 |
| 只适合补充 | [Finnhub](https://finnhub.io/pricing) 免费只有 WS 成交（K 线已收费）；[Massive（原 Polygon）](https://massive.com/pricing) 免费只有 5 次/分、仅日终 | 是 | 部分 | 少 | 社区 |
| CME 交易所级期货 | [Databento](https://databento.com/docs/knowledge-base/new-users/usage-based-pricing-and-data-credits)：送 $125 历史额度，实时订阅约 $179/月 | 付费 | — | — | 用户自带付费 key |

## 10. 需要确认的问题

2026-11-26 用户确认：Q1–Q7 全部按下列提议执行。

- **Q1 TradFi 合约的身份。** 提议：保持现有加密身份（交易所 binance、24×7、合约张数成交量），新增
  `underlying_class` 只用于分组和关联，不进序列身份。理由：数据语义确实是加密交易所的永续合约，不需要迁移存储。
- **Q2 TradFi 合约在品种选择器里的位置。** 提议：默认可见，单独分组（商品 / 美股 / 港股 / 韩股 / 其他），
  图表和策略结果标注"合约价格"。
- **Q3 CCXT 连接器发版方式。** 提议：1.2 先只拆边界，仍随应用打包，版本显示在诊断里；
  确实需要时再开独立更新渠道。
- **Q4 凭据库。** 提议：和 PL-5（Windows 只读账户）共用一份宿主凭据库，Windows 用凭据管理器。
- **Q5 第一个新的真实交易所来源。** 提议：Alpaca（不需要券商账户，是最好的免费美股来源），
  其次天勤（国内期货），长桥、OANDA、Dukascopy 留给社区或按需求再做。
- **Q6 沙箱 provider 的 WebSocket。** 提议：v2 先只开放宿主代理的 HTTPS（轮询）和凭据注入，
  宿主托管的 WSS 作为下一步。
- **Q7 版本归属。** 提议：D0–D5 进 1.1（用户看得到的价值，不重组插件层）；D6 起随 1.2 的插件层合并一起做。

## 11. 分阶段

| 阶段 | 版本 | 内容 | 验收 |
| --- | --- | --- | --- |
| D0 | 1.1 | Binance 原生目录和 CCXT 目录（`binance`、`binanceusdm`）都按 `underlyingType` 分类 `TRADIFI_PERPETUAL`；`underlying_class` 分组和品种搜索里的"合约价格"标注；合约规则沿用 `binance_contract_rules` | XAUUSDT、CLUSDT、AAPLUSDT：图表、Pine/Python 策略、FOLLOW、回放、练习账户、月度归档都跑通 |
| D0c | 1.1 | "合约价格"标注跟到图表标题、策略报告、回放和练习账户（按品种查 `underlying_class`）。资金费率不用改：历史资金费按实际结算时间记账，结算周期从结算记录推断（1/2/4/8 小时），XAU 是 4 小时；界面不提供带非零费率的固定资金费回测，回放"固定资金费"沙盒的周期由用户自己填（默认 8 小时） | 上面三个合约在这四处都看得到标注；XAUUSDT 的资金费记录按 4 小时结算 |
| D0b | 1.1 | 其他 CCXT 交易所的 TradFi 合约按 `venue_underlyings.py` 分类，并逐家核对交易时段；Hyperliquid HIP-3 加载 | 至少一个非 Binance 交易所的黄金、原油合约可用，非 24×7 的品种不报缺口 |
| D1 | 1.1 | SeriesRef 贯穿策略测试、研究来源、回放、数据准备、练习账户；hash 规则按 §3 | 用 Twelve Data AAPL 1m（环境变量 key）跑通图表 → 策略测试 → 回放 → 练习账户；现有运行和回放的 hash 不变 |
| D2 | 1.1 | 完整性改用日历；持续策略去掉加密限定，改看日历和能力 | 美股休市、节假日、半日市不报不完整；Binance 和 OKX 现有结果不变 |
| D3 | 1.1 | §5 的名字判断全部改成能力（D3a 逐笔成交归档；D3b 回放训练；D3c 策略；D3d 高级行情） | 对 Binance/OKX 行为不变；无该能力的来源明确提示不支持 |
| D4 | 1.1 | 宿主凭据库 + 设置页「数据源」；Twelve Data key 迁到界面 | 不设环境变量即可使用 Twelve Data；macOS 和 Windows 都能用 |
| D5 | 1.1 | 模拟账户：现金股票、期货每手保证金、休市不成交和开盘跳空 | 美股和期货品种在练习账户里能开平仓，财务结果有测试 |
| D6 | 1.2 | 契约 v2 + 宿主侧适配；本地 provider（与 #169 合并）；网关凭据注入；CCXT 连接器拆边界并做版本检查 | mock provider v2 产出非加密身份序列，进入策略和回放；v1 manifest 仍可用 |
| D7 | 1.2 | Alpaca provider：IEX 实时分钟 K 线，收盘后用 SIP 历史修正为 final | 美股盘中实时 K 线；修正后序列与 REST 历史一致 |
| D8 | 1.2 之后 | 天勤 provider；单月合约与连续合约（换月规则） | 国内期货 au/sc 主连可用于策略和回放 |

## 12. 风险

- **身份传错会串源。** 例如股票序列被读成默认身份，或反过来。D1 必须测"同一个 symbol、不同 identity"互不干扰，
  以及旧的引用照常解析。
- **日历错误会造成假缺口或漏数据。** 节假日、半日市和夏令时由日历库负责（XNYS 用 `exchange_calendars`），
  provider 不能自己写死时段。
- **免费额度很小。** Alpaca 200 次/分、Twelve Data 8 次/分。回补规划（ADR-DATA-001）必须按来源额度排程，
  界面要显示"额度用完、何时恢复"，不能显示成网络故障。
- **TradFi 合约容易被误当成真实行情。** 标注必须跟到策略报告和回放里。
- **范围膨胀。** D0–D5 不碰插件层结构；契约 v2 和 CCXT 拆边界只在 1.2 和插件层合并一起做。
