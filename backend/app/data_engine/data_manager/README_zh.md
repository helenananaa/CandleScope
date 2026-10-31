# Data Manager

[English](README.md)

> CandleScope 行情数据的公共业务门面。API/WS/Indicator 代码应通过 `DataManager` 进行 K 线查询、cache 访问、事件订阅、stream 生命周期、backfill coordination、价格快照和维护任务。

## 在 Data Engine 中的位置

```text
ingestion -> bar_aggregator -> DataManager -> API / WS / Indicator
                         ▲
                         └── backfill -> storage readback
```

`data_manager` 是底层数据管线和应用功能之间的边界。外部模块应使用 [__init__.py](__init__.py) 暴露的 package root API，不要直接依赖 `QueryEngine`、`StreamCoordinator`、`AggregatorBridge` 等内部服务。

## 职责

| 领域 | 组件 | 职责 |
|---|---|---|
| 门面 | `DataManager` | 查询、stream、subscription、maintenance、diagnostics 的公共方法 |
| Cache | `KlineCache` | 带 size/TTL 限制的内存序列缓存 |
| Query | `QueryEngine` | Cache -> Storage -> Backfill 解析，并返回 missing-range metadata |
| Streams | `StreamCoordinator` / `StreamEnsurePlanner` | 启停 ingestion 和 bar aggregator targets；跨 consumer lease 共享 upstream stream |
| Events | `DataEventBus` | callback 和 async-iterator 事件分发 |
| Aggregation Bridge | `AggregatorBridge` | 持久化 bar events、合并 cache、发出 `DataEvent` |
| Backfill | `BackfillCoordinator` | 执行修复、持久化与核验缺口、storage 回读 cache、完成事件 |
| Backfill Scheduling | `BackfillScheduler` | 需求租约、去重合并、分块调度、公平性、限速和取消 |
| Backfill Admission | `BackfillHistoryPlanner` | 可用性和日历规划、闭合 K 线裁剪、无需抓取的结果 |
| Custom Query | `CustomQueryEngine` | 自定义周期一致查询 |
| Warm Start | `AggregatorWarmStartService` | 启动时从 storage seed aggregator state |
| Price | `IngestionPriceSource` / `PriceSnapshotCache` | 轻量实时价格流和快照 |
| Subscription | `SubscriptionService` | watchlist tier：`full`、`price`、`none`；持久化 full 周期和 consumer lease |
| Maintenance | `maintenance.py`、`retention.py` | storage repair、gap scan、retention limits |

## 公共 API

### 每个订阅的源数据连续性策略

`subscribe()`、`subscribe_async()`、`subscribe_iter()` 支持 `continuity`：

```python
from app.data_engine.data_manager import ContinuityPolicy, DataEventType

strict = dm.subscribe(on_closed, symbol="BTCUSDT", interval="1m",
    event_types={DataEventType.BAR_CLOSED}, on_recovery=reload_snapshot,
    continuity=ContinuityPolicy("strict", max_wait_seconds=2.0))
live = dm.subscribe(on_live_or_control, symbol="BTCUSDT", interval="1m",
    continuity="gap_aware")
```

- 默认 `strict`，从发现缺口起最多等待 10 秒，可按订阅配置。等待只阻塞该订阅的工作队列，复用 EventBus 的有界缓冲与回放。已有后台补洞负责共享修复；DM 拥有的 K 线入口不再由 L5.5 统一等待，但保留去重和顺序保护。TradeFlow 也由自己的共享 ID 修复服务负责，避免上游统一等待阻塞实时优先订阅。
- 严格模式必须看到覆盖所有缺失开盘时间的可信已收盘数据，才按顺序交付补回的 `BAR_CLOSED` 和暂存尾部。补回数据及等待期间收到的尾部带 `continuity_replayed=True`，报警据此更新状态，不将追赶数据当作新信号触发。
- `gap_aware` 会继续交付，并在 K 线详情中标注 `source_continuity`；`SOURCE_GAP` / `SOURCE_GAP_RESOLVED` 不受事件类型过滤，以免隐藏缺口。订阅了 `BAR_AMENDED` 的消费者还会收到历史修正；其他消费者可按控制事件的范围重新读取。消费者必须处理这些控制事件，已有浏览器协议不会自动切到此模式。
- 等待超时、补洞失败、源停止、回放耗尽或存储延迟造成收盘交付倒序，callback 通过 `on_recovery`、iterator 通过 `ConsumerRecoveryRequired` 明确要求重新取快照再订阅。缺口期间新加入的严格订阅也需要在补齐后重新取快照，因为它没有收到订阅前的尾部。取消某个订阅不会取消共享修复。
- 保证范围是订阅期间**已检测到的源数据缺口与最终 K 线**，不包含初始历史、每个盘中 tick 或外部副作用的 exactly-once。交易日历决定预期时间；派生周期必须修复对应目标 K 线，不能只凭基础周期补齐就恢复交付。
- 一个 wildcard 订阅共用一个工作队列；需要各序列独立延迟时使用多个订阅。缺口证据最多保留 256 条、合计 10,000 根预期 K 线；若未完成证据被挤出，严格交付会明确失败，需重启 DataManager 并重新建立快照。诊断见 `market_data_control_snapshot().source_continuity`。

### 跨交易所与其他数据类型

策略没有交易所或商品白名单，沿用已注册插件的市场、通道、交易日历和数据权限。先用 `dm.continuity_contract(key)` 查询该交易所/市场/通道是否可用、支持的策略及恢复能力。插件未提供的实时流或历史数据不会因选择策略而凭空出现；例如当前 Twelve Data K 线仅声明历史能力。CCXT 的细分市场必须使用插件声明的名称，例如 Bybit 的 `swap.linear`。

```python
# K 线默认 strict；其他服务通过参数显式选择，省略时保留原交付接口。
trades = dm.trades.attach(trade_keys, continuity="strict")
book = dm.books.full.attach(book_keys, continuity="gap_aware")
# 部分盘口和 ticker / mark / funding / OI 等最新状态同样支持两种策略。
partial = dm.books.partial.attach(partial_keys, continuity="strict")
state = dm.market_state.subscribe(state_keys, continuity="strict")
liquidations = dm.liquidations.attach(liquidation_keys, continuity="gap_aware")
```

| 数据类型 | strict | gap_aware |
|---|---|---|
| K 线 | 按预期时间补齐可信收盘 K 线 | 实时交付、缺口控制、历史修正 |
| 声明连续 ID 和历史重放能力的成交 | 共享 REST 修复，逐订阅按 ID 补回；队列/保留窗口耗尽则要求重同步 | 继续交付；`batch.detail.source_continuity` 描述缺口，`batch.corrections` 返回补回成交 |
| 完整盘口 | 等待通过序号校验的新快照 | 立即收到失效状态，再收到恢复状态 |
| 部分盘口和其他最新行情状态 | 等待有效的新状态；允许合并中间更新 | 缺口状态不会被最新值合并吞掉 |
| 无连续序号的普通成交、采样清算 | 抛出 `ContinuityUnsupported`，不能承诺完整源事件 | 接受观察/采样语义，标注 `source_exhaustive=False`，断线时通知不可补回 |

盘口与最新状态的严格保证是**当前状态有效**，不承诺重放断线期间每个盘口变化。成交订阅的等待预算从消费者观察到缺号批次起计算，批次内多段缺口共享预算。等待只占用该订阅，关闭或超时不会取消其他消费者的共享修复。成交缓冲受订阅 `max_pending_records` 和引擎保留窗口限制；补齐后 `continuity_replayed=True` 标记追赶批次。实时优先消费者必须处理空记录控制批次和修正字段，不能只遍历 `records`。

最新状态的缺口证据也有容量上限；若共享 hub 丢失未恢复的证据，严格订阅会收到 `source_gap_tracking_exhausted`，需要重建所属服务并获取新快照，单独重新订阅不足以恢复保证。

现有浏览器协议没有自动启用新参数；这些契约首先提供给 DataManager 后端消费者。这里的跨交易所验证使用受控源输入、真实服务与 SQLite，不等同于全交易所实盘验收。

`DataManager` 常用方法：

| 方法 | 用途 |
|---|---|
| `start()` / `shutdown()` | 生命周期 |
| `query()` | 查询范围，可按配置触发 backfill |
| `query_latest()` | 最新 N 根 bars |
| `query_before()` | 按 timestamp 向前分页 |
| `get_bounds()` | 某个序列的 storage metadata |
| `scan_storage_gaps()` | 只扫描连续性，不触发修复 |
| `ensure_stream()` | 确保实时 ingestion + aggregation 正在运行，可注册到 consumer lease |
| `release_stream()` | 释放 consumer lease，不强制停止其他 consumer 仍在使用的流 |
| `subscribe()` / `unsubscribe()` | callback 事件订阅 |
| `subscribe_iter()` | async iterator 事件订阅 |
| `on_bar_event()` | 消费 `BarAggregator` events |
| `on_bars_backfilled()` | storage 回读后合并修复 bars |
| `get_prices_snapshot()` | 当前 watched symbols 价格快照 |
| `get_subscription_service()` | 获取 subscription tier manager |
| `repair_custom_storage()` | 重建自定义周期 rows |
| `scan_and_fill_storage_gaps()` | 手动 gap scan + repair |
| `update_retention_limits()` | 更新 DB/ephemeral retention 设置 |
| `snapshot()` | 完整诊断快照 |
| `market_data_control_snapshot()` | 通道 owner、强类型命名空间、就绪状态和 coverage 边界 |

各类行情通过强类型命名空间分组：

- `dm.bars`：K 线查询、边界和 stream ensure。
- `dm.market_state`：ticker/mark/funding/open-interest/basis 的 latest 与 history。
- `dm.trades` 和 `dm.liquidations`：不同完备性保证的 append-only 事件访问。
- `dm.books.partial` 和 `dm.books.full`：可替换 Top-N 快照与 sequence-gated 全量深度簿。

原有平铺方法继续保留为兼容包装，并统一路由到上述命名空间。

示例：

```python
from app.data_engine.data_manager import DataManager

dm = DataManager()
await dm.start()

await dm.ensure_stream("BTCUSDT", "1m", exchange="binance", market_type="spot")
result = dm.query_latest("BTCUSDT", "1m", 500, "binance", market_type="spot")

handle = dm.subscribe(callback=on_event, symbol="BTCUSDT", interval="1m")
dm.unsubscribe(handle)

await dm.shutdown()
```

## 公共类型

package root 暴露稳定门面和契约：

- Config：`DataManagerConfig`、`CacheConfig`、`QueryConfig`、`EventBusConfig`、`CoordinatorConfig`、`PrewarmTarget`
- Data：`BarData`、`SeriesKey`、`QueryResult`、`MissingRange`、`QuerySource`
- Events：`DataEvent`、`DataEventType`、`SubscriptionHandle`
- Streams：`StreamInfo`、`StreamStatus`
- Storage protocol：`StorageBackend`
- Maintenance/subscription：`MaintenanceBusyError`、`MaintenanceUnavailableError`、`SubscriptionTier`
- Domain facades：`BarDataFacade`、`MarketStateFacade`、`TradeDataFacade`、`LiquidationDataFacade`、`PartialOrderBookFacade`、`FullOrderBookFacade`

## 时间戳和身份规则

- storage 和内部 engine 时间戳使用毫秒。
- `BarData.time` 使用 Unix 秒，面向 `lightweight-charts`。
- `SeriesKey` 会把 symbol 规范成大写，exchange/market type 规范成小写。
- Binance spot topic 保持简短：`BTCUSDT@1m`。
- 非默认 exchange 或 market type 会带前缀：`okx:swap:BTC-USDT@1m`、`futures:BTCUSDT@1m`。

## 查询语义

`QueryEngine` 按以下顺序解析数据：

1. cache 命中时先用 cache。
2. 再查注入的 storage backend。
3. 检测到 missing ranges 且 `auto_backfill` 开启时触发 backfill。

`QueryResult` 包含：

- `bars`：按时间升序排列的 `BarData`
- `source`：`cache`、`storage`、`backfill`、`mixed` 或 `empty`
- `cache_hit`
- `has_more`
- `backfill_triggered`
- `has_tail_gap`
- `missing_ranges`
- `metadata`

API range endpoints 会在这些 metadata 之上额外做可见范围连续性校验。

## Stream 生命周期

`ensure_stream()` 是启动实时数据的公共入口：

```text
ensure_stream(symbol, interval)
        ▼
StreamEnsurePlanner
        ▼
StreamCoordinator
        ├── BarAggregator.add_target()
        └── IngestionFactory.start(on_market_event)
```

planner 会选择需要的 source streams。对于自定义周期，可能会启动合适的 base interval，并在 aggregator 中注册用户请求的 target interval。

## Backfill 协调

组件依赖方向如下：

- [backfill_contracts.py](backfill_contracts.py) 持有请求、结果和需求优先级。
  请求生产者可以只导入契约，不加载调度器或协调器；原协调器入口继续导出相同对象。
- [backfill_history.py](backfill_history.py) 只依赖历史可用性服务和策略解析器，
  负责请求规划，不持有缓存或调度状态。
- [backfill_scheduler.py](backfill_scheduler.py) 独立持有调度状态和需求租约，
  通过显式回调执行修复、持久化最终结果和完成通知，不导入协调器或直接访问存储、缓存。
- [backfill_coordinator.py](backfill_coordinator.py) 将以上组件与引擎、持久化缺口账本、
  缓存回读和事件交付连接起来。持久化最终结果完成后，调度器才释放共享等待者。

`BackfillCoordinator` 和 `BackfillEngine` 分离：

- 去重 in-flight requests。
- 合并兼容 ranges。
- 大修复按 chunk 执行；前台工作 active 时不再启动新的后台 chunk，已经运行的
  一个后台 page 可以执行到下一个调度边界。
- 429/预算延迟中的前台 chunk 仍算作 foreground ownership，不能被误判为空闲窗口。
- 在 `GapLedger` 持久化 gap lifecycle。
- 处理 retry/cancel/shutdown。
- 运行 `BackfillEngine`。
- 按 `RepairReport.written_ranges` 从 storage 回读。
- 调用 `DataManager.on_bars_backfilled()`。
- 发出 `BACKFILL_COMPLETED` 或 `BACKFILL_FAILED`。

API 和 settings 代码应通过 DataManager/coordinator 触发修复，不要直接调用 `BackfillEngine.run()`。

当前 demand priority：

| 来源 | Reason | Priority |
|---|---|---:|
| `/klines/history?intent=viewport`（默认） | `initial_history` | 10 |
| 可见区/向左加载 | `visible_range_gap` / `visible_load_more` | 20 |
| 前台 base seed / tail gap | `visible_seed_gap` / `tail_gap` | 25 |
| 显式 latest refresh | `latest_refresh` | 30 |
| query repair family | `query_*` | 35 |
| price daily open | `price_daily_open` | 70 |
| `/klines/history?intent=active_hydration` | `active_history_hydration` | 90 |
| 同商品相关周期预热 | `related_interval_warmup` | 100 |
| Full subscription 预热 | `full_subscription_warmup` | 110 |
| 启动扫描 | `startup_gap_scan` | 140 |
| 后台审计 | `background_gap_audit` | 160 |

相关周期预热按 demand scope debounce，必须等前台持续安静后才提交；成功接纳的
精确 target range 写入有界的五分钟 TTL registry。新闭合的 target range 不会被旧
TTL 挡住，提交失败或返回 false 也不会污染 TTL。

活跃商品历史补齐同样按 newest-first 执行，但始终属于后台 lane；它不会与 viewport
parent 合并，避免宽范围缓存补齐扩大或继承可见请求的前台所有权。

## Events

`DataEventType` 包括：

- Bar 生命周期：`BAR_CREATED`、`BAR_UPDATED`、`BAR_CLOSED`、`BAR_AMENDED`、`BAR_EXPIRED`
- Stream 生命周期：`STREAM_STARTED`、`STREAM_STOPPED`、`STREAM_ERROR`
- Backfill 生命周期：`BACKFILL_STARTED`、`BACKFILL_COMPLETED`、`BACKFILL_FAILED`
- Cache/price：`CACHE_PREWARM`、`CACHE_EVICTION`、`PRICE_UPDATED`

消费者可使用 callback 或 async iterator：

```python
async for event in dm.subscribe_iter(symbol="BTCUSDT", interval="1m"):
    print(event.to_dict())
```

## 配置

`DataManagerConfig` 分组：

| 分组 | 重要字段 |
|---|---|
| `cache` | `max_bars_per_series`、`max_series`、`prewarm_bars`、`ttl_seconds` |
| `query` | `default_limit`、`max_limit`、`sync_backfill_timeout_seconds`、`auto_backfill` |
| `event_bus` | `subscriber_queue_size`、`emit_bar_updated`、`emit_bar_created` |
| `coordinator` | `auto_start_ingestion`、`idle_stream_timeout_seconds`、`base_interval`、`prewarm_intervals`、`prewarm_symbols`、`prewarm_targets` |

## 维护

`DataManager` 通过门面方法提供 settings API 所需的维护能力：

- `repair_custom_storage()`
- `scan_and_fill_storage_gaps()`
- `scan_storage_gaps()`
- `update_retention_limits()`
- `retention_snapshot()`

维护方法在发生并发冲突时抛出 `MaintenanceBusyError`，缺少必要 runtime dependency 时抛出 `MaintenanceUnavailableError`。

## 测试

```bash
cd backend
python -m pytest -q \
  tests/test_query_engine_paths.py \
  tests/test_backfill_coordinator.py \
  tests/test_data_manager_warm_start_bridge.py \
  tests/test_maintenance_facade.py \
  tests/test_price_subscription_services.py
```
