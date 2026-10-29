# Issue 117: candle boundary contracts

Provider native candle contracts and requested output schedules are separate.
Display timezones never change aggregation. Qualified interval strings are the
identity across cache, subscriptions, layouts, local datasets, snapshots and Pine.

## Output schedules

| Identity | Meaning |
| --- | --- |
| `7m` | Existing epoch-aligned seven minutes |
| `7m~a1~180000` | Seven minutes with a three-minute phase, extending both directions |
| `1d~c1~UTC` | UTC calendar days |
| `1d~c1~Asia/Shanghai` | Shanghai midnight-to-midnight days |
| `1d~c1~America/New_York` | New York days, including 23/25-hour DST days |
| `1w~c1~America/New_York` | Monday midnight to Monday midnight |
| `1M~c1~America/New_York` | Calendar months |
| `12M~c1~America/New_York` | January-to-January calendar years |

Manual anchors accept whole minutes; seconds fail explicitly. Phase is reduced
modulo duration, so equivalent anchors share identity. Calendar c1 supports days
1–366, weeks 1–52, months 1–12; multiples start at January 1970 (weeks at Monday
January 5). Published query range: 1970–2399. Extra edge years support containing
buckets/projection. Only the listed zones and midnight boundaries are exposed.
Ambiguous/nonexistent local times fail rather than silently selecting an offset.

`calendar-v1.json` is an immutable transition table generated from
`tzdata==2026.3`, IANA **2026c**, by `backend/scripts/generate_calendar_basis_rules.py`.
Backend and frontend use identical copies independent of OS/Intl/timezone.
This is a pinned version, not the newest IANA release. Future rule changes
require a new wire version; unavailable versions fail. IANA data is public domain.

`BarBasis` schema 1 includes canonical identity, phase, `[open,end)` windows,
and stored `end-1ms` closes. Calendar definitions include zone, rule version,
tzdb version and range. `GET /api/v1/exchanges/bar-basis?interval=...` returns
the definition. Frozen restores check definition availability and consistency;
older unqualified local datasets retain their original import contract.

Continuous calendar aggregation requires an exactly tiling fixed source at most
one hour and dividing one hour. UTC two-hour bars cannot reconstruct New York
midnights. Capacity uses the longest possible window. Local SQLite composition
streams components and omits incomplete windows. Local calendar-source
coarsening is not advertised; fixed-source composition is the supported path.

## Provider qualification

`NativeBarSpec` declares provider, venue, market, channel, purpose, protocol,
basis and evidence. Opens and inclusive closes are validated before normalized
events reach continuity/storage. CCXT interval availability does not prove UTC
boundaries. Unqualified venues remain visible but their candle intervals fail
closed until an explicit declaration is added.

| Source | Qualification |
| --- | --- |
| OKX spot / swap | UTC REST names, WS channels, matching and caches patched together; CCXT 4.5.60 |
| Binance | Existing UTC native declaration and archive boundary validation |
| Bybit `5m` | Official WS start/end fixture plus public spot REST capture; other intervals unknown |
| Twelve Data stock/ETF/index | Existing provider-date session calendar, history only |
| Twelve Data forex/commodity | Existing weekday 24x5 calendar, history only |
| Other generic providers | Unknown until explicitly declared |

These are scoped declarations/fixtures, not all-market live certification.
Session sources remain native and are excluded from continuous derivation:
a session label does not prove 24-hour coverage. Plugins may declare
`ExchangeCapabilities.native_bar_specs`; absent declarations fail closed.
Platform v2 market-data contributions declare the same contract in each kline
channel's `barBasis`, for example
`{"schemaVersion":1,"intervals":{"1m":"1m","5m":"5m"}}`.
Every advertised interval must map to a canonical basis; the host creates a
per-market, per-purpose NativeBarSpec with the contribution as its evidence.
Optional `calendarId` refers to a registered session calendar. Market timezone
metadata alone does not qualify a provider. The SDK mock provider demonstrates
this declaration and is exercised through normal history and live ingestion.

Protocol evidence: [OKX](https://www.okx.com/docs-v5/en/#rest-api-market-data-get-candlesticks),
[Bybit WS](https://bybit-exchange.github.io/docs/v5/websocket/public/kline),
[Bybit REST](https://bybit-exchange.github.io/docs/v5/market/kline).
The public REST response is `backend/tests/fixtures/bar_basis/bybit-5m-rest.json`.

## Legacy live storage and rollback

First initialization isolates unversioned live rows because timestamps alone
cannot prove the old channel/source rules. All old OHLCV remains verbatim in
`klines_legacy_basis_v1`, grouped as unknown in `legacy_bar_basis_audit`. Active
`klines` starts empty and refills through qualified acquisition. This needs
backup disk space and may cause a substantial one-time download.

Before moving rows, a complete SQLite backup is verified under a reserved
writer lock. The report records its path/count. Failure rolls back the active
table; subsequent startup is idempotent. Local datasets and replay archives are
separate and untouched. The backup precedes basis isolation, after any older
schema migration. No live user database was migrated during development.

Read the audit or restore to a new file:

```sh
PYTHONPATH=backend python backend/scripts/bar_basis_storage.py audit /absolute/path/klines.sqlite
PYTHONPATH=backend python backend/scripts/bar_basis_storage.py restore /absolute/path/backup.sqlite /absolute/path/restored.sqlite
```

Restore refuses an existing destination. Stop the app before selecting a
restored profile. Preserve both current and backup databases; never overwrite
post-migration activity. An older build can use the restored copy. This build
will intentionally isolate its unversioned rows again if reopened.

## Pine dependency and acceptance

Fixed minute anchors work with the qualified existing Pine engine. Calendar
execution requires the host-neutral **host-bar-boundaries/1** extension. The
host freezes actual windows per chart/request context; Pine uses them for
`time`, `time_close`, `timeframe.change`, security alignment, batch and replay.
Aliases share a schedule. Missing cross-timeframe windows and unsupported
custom sessions fail explicitly instead of substituting UTC.

The candidate is built from official v0.3.2 source plus
`packages/candlescope-plugin-pine-compat/engine-patches/host-bar-boundaries-v1.patch`.
It is unpublished, distinct from the official binary. Official release locks
remain unchanged; older installed engines reject calendar execution clearly.
See the patch README for reproduction. Publishing/versioning this dependency
and multi-platform runtime qualification remain release work.

See `docs/qa/ISSUE_117_BAR_BASIS_20261029.md` for results. Actual OKX closes and
forced same-instance reconnect passed for spot/swap 1m. The seven-interval
matrix received data but does not prove month-long real-time closure. Historical
OKX REST times out on this machine and is not marked passed. Desktop packaging
acceptance is explicitly excluded at the user's request.
