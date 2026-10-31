# Subscription continuity: live validation, 2026-10-29

Related to #112. This is a **draft implementation with incomplete provider
coverage**, not acceptance of strict recovery for every exchange/channel.

## Change and consumer contract

K-line subscribers can choose `strict` or `gap_aware`. Strict delivery waits for
verified final bars in a consumer-local bounded queue; gap-aware delivery keeps
current bars flowing and reports source gaps, historical amendments and
resolution. Repair remains shared, while deadlines and cancellation belong to
each subscription. K-line subscriptions default to strict with a 10-second wait
budget; non-K-line continuity remains opt-in.

The same policy type is exposed to market-data services. Recoverable aggregate
trades use verified ID-range replay; books and other state channels resume from
valid current snapshots. Snapshot recovery does not replay every historical
state transition. Ordinary observational trades and sampled liquidations still
reject strict requests in this candidate.

Live validation also exposed and fixed:

1. OKX port 8443 notice `64010` caused reconnect loops. Both raw and unified CCXT
   paths now default to port 443 and preserve pending watches on that advisory,
   while preserving pong and actual-error handling.
2. Shared runtime resets could leave cached-watch consumers unaware of the
   source break. Lifecycle notifications now reach all sessions, and obsolete
   watch results and buffered source state are fenced across interruption.
3. A candle seen before disconnection but missing its final update was excluded
   from repair. Gap detection now includes that candle; the unified projector
   clears interrupted previews instead of promoting them to final bars.

## Live method

Public, real WS/REST data from Binance BTCUSDT perpetual, OKX BTC-USDT-SWAP and
Bybit BTC/USDT:USDT linear perpetual. The probes exercised ingestion, trade/book
services, and the K-line DataManager/BackfillCoordinator/SQLite path. They used
isolated data directories, without credentials, orders or the user's database.

- `markets-5`: close and rebuild actual shared WS clients; inject a reconnect
  gate and a repair gate to expose concurrent-consumer behavior.
- `socket-abort-1`: directly abort four underlying socket transports. All six
  trade/book streams recorded abnormal close code `1006` and resumed.
- `klines-3`: interrupt WS for approximately 120 seconds, covering both an
  interrupted forming candle and a wholly missing minute. Independently reread
  repaired candles through exchange REST and compare their OHLCV to SQLite.

Prices, timestamps, IDs and recovery responses were not synthesized. Scheduling
gates make these fault drills, not normal-network latency benchmarks. Patient
strict budgets were 15 seconds for trades/books and 20 seconds for K-lines;
short-lived strict subscribers used 0.75 seconds.

## Final observations

| Exchange | Closed 1-minute candles | Trades | Books |
| --- | --- | --- | --- |
| Binance | 2 repaired; contiguous final sequence; REST/SQLite OHLCV match | 69 and 28 aggregate-trade events repaired in the two drills; contiguous strict IDs; matching live corrections | Full book becomes valid again; strict delivery holds during invalid state |
| OKX | 2 repaired; contiguous final sequence; REST/SQLite OHLCV match | Ordinary trade stream resumes with an explicit unrecoverable gap; strict rejected | Fresh valid 5-level snapshot; strict delivery holds during invalid state |
| Bybit | 2 repaired; contiguous final sequence; REST/SQLite OHLCV match | Ordinary trade stream resumes with an explicit unrecoverable gap; strict rejected | Fresh valid 5-level snapshot; strict delivery holds during invalid state |

All six repaired candles passed independent REST parity. Each exchange's strict
closed-bar sequence was `[1793254020, 1793254080, 1793254140]`, spaced 60 seconds
apart. Gap-aware consumers continued receiving live updates during repair.
Timeout of each 0.75-second strict consumer did not cancel shared recovery or
terminate the patient strict/gap-aware consumers. No strict book consumer
received an invalid-state record in the final drills.

The three final runs passed all **67 evidence checks**. Rejecting strict ordinary
trades verifies only the current guard, not fulfillment of all-exchange strict
recovery. Earlier failed candidates were retained locally, including the K-line
run that exposed the missing-final-update defect.

## Automated checks and provenance

The latest result for each of **173 distinct tests** passed across two runs:
`fix-regression-2` had 172 passes and one stale test assertion; after correcting
that assertion to check actual delivery, `recheck` passed both tests in the
affected file. This was not one final all-suite invocation. `git diff --check`
passed. Source/test hashes were rechecked before preparing the PR and matched
the live-validation snapshot.

Reproduce the related regression suite from the repository root with an isolated
`CANDLE_DATA_DIR` and temporary pytest directory:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend CANDLE_DATA_DIR="$PWD/.local/continuity-regression-data" \
  .venv/bin/python -m pytest -q \
  backend/tests/test_calendar_gap_integration.py \
  backend/tests/test_ccxt_gap_recovery.py \
  backend/tests/test_ccxt_integrated_soak.py \
  backend/tests/test_ccxt_okx_shadow.py \
  backend/tests/test_ccxt_provider_runtime.py \
  backend/tests/test_ccxt_unified_provider.py \
  backend/tests/test_ccxt_unified_soak.py \
  backend/tests/test_market_subscription_continuity.py \
  backend/tests/test_plugin_provider_v2.py \
  backend/tests/test_recovery_delivery_integration.py \
  backend/tests/test_recovery_kline_consumers.py \
  backend/tests/test_subscription_continuity.py
```

The existing isolated plugin-sidecar test requires pip in the test virtualenv.
Bundled `ensurepip` supplied it locally; no source dependency was changed.

[Machine-readable validation snapshot](evidence/subscription-continuity-live-20261029.json)
contains the per-check results, fault details, regression counts and source/probe
SHA256 hashes. It records the validation state before commit/PR creation. Raw
events, logs, probe scripts and SQLite files remain local under
`.local/issue-112-evidence/live-20261029/` and are not included in the PR.

## Draft blockers and untested boundaries

- Ordinary `TRADE` and `LIQUIDATION` are still rejected wholesale for strict
  delivery. Provider-specific completeness/recovery capabilities and adapters
  must replace this blanket classification before claiming all-exchange support.
- OKX exposes paginated trade history; its live/history correspondence and
  verified replay are not wired into this candidate. Bybit's recent-trade
  endpoint has a bounded window; any short-gap repair must prove coverage, and
  gaps outside that window must fail explicitly rather than claim completeness.
- No UI or browser-protocol selector for gap-aware delivery was added. Consumers
  must explicitly handle the new source controls and correction semantics.
- These are BTC perpetual samples, not every symbol/market or a multi-hour soak.
  Binance's tested sequence is aggregate trades, not every raw matching event.
- No live liquidation, packaged/native UI or default-10-second latency acceptance
  was performed. The K-line probe ended during the current forming candle after
  repair, before its next natural close.
- Strict failure is terminal for that subscription and requires a fresh snapshot
  and subscription; it must not silently downgrade to gap-aware delivery.

Sources: [OKX WS port update](https://www.okx.com/docs-v5/log_en/),
[OKX trade history](https://tr.okx.com/docs-v5/en/#rest-api-market-data-get-trades-history),
[Bybit recent public trades](https://bybit-exchange.github.io/docs/v5/market/recent-trade).
