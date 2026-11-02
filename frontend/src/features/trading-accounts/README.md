# Trading accounts

The live page's "Accounts" rail view: local practice trading, manual fill
entry, the three-stage trade journal and quick replay. The backend owner is
`backend/app/trading_accounts` behind `/api/v1/trading`.

## Accounts

- `practice`: virtual funds on this computer. Orders are matched by the backend
  against live 1m candles (see the backend README). Nothing reaches an exchange.
- `manual`: fills entered by hand, for trades made elsewhere.
- `exchange_readonly` / `exchange_trading` are shown as planned and cannot be
  created until a verified connector exists.

The Accounts view is host-owned (`hostOwned` in `marketRailTypes.ts`): plugin
rail contributions cannot replace it, because it can place orders.

`tradingAccountsStore.ts` holds the selected account's accounts, summary, trades
and journal once per window. The rail panel (`useTradingAccountsRuntime`) and
every live chart cell (`useTradingChartOverlay`) read it and keep it retained;
one per-account NDJSON state stream runs while anything is retained. Practice
accounts use committed replacements instead of the old 2 s / 15 s polling.
The last consumer closes only its view stream; background matching keeps its
own market demand. Manual accounts retain a 15 s snapshot revalidation because
they have no practice valuation lease. Injected read ports without streaming
keep the legacy read interface.

Each connection starts with a complete snapshot and orders replacements by its
own epoch/sequence. The separate persistent ledger cursor covers summary,
trades and journal in one read-only WAL snapshot. Unflushed quote observations
may advance connection sequence without advancing the ledger cursor. The
matcher still flushes a no-fill cursor at its existing 10 s cadence. Heartbeats
perform no database reads; silent connections expire after 30 s and reconnect
to a complete snapshot. Errors, old connection callbacks and mismatched account
or ledger identities cannot replace the current view. This is a current-state
protocol, not an exactly-once financial event log.

## Live chart overlay

Each live chart cell draws the selected account's activity on its own
exchange / market type / symbol, read-only (`liveChartOverlay.ts`):

- fill markers (the quick replay marker source with a `trading-live` id prefix),
  limited to fills whose candle is inside the loaded bars, because the chart
  would otherwise pin them to the first or last bar. A reversal fill is drawn
  once with its full quantity. Same-side fills in one candle share a marker
  (summed quantity, fill count, volume-weighted price), here and in quick
  replay, because the chart stacks markers on a bar.
- native price lines (`chart-adapter/externalPriceLineSource.ts`) for each open
  position's average entry and its working reduce-only stop-loss / take-profit
  orders. Price lines do not widen autoscale, so a distant stop stays off-screen
  instead of squashing the candles.

## Journal

One template document per trade plus timestamped quick notes. The stage is not
chosen: it follows from when a revision was saved relative to the linked trade.
Pre-trade fields first written after the first fill carry a "written after
entry" badge. Entry, stop, target and risk (USDT) are locked at the first fill
and are the only R denominator. `auto` template fields render from the ledger
and are never stored as text.

The editor writes a profile-local draft synchronously on each edit, scoped by
account and journal target. Template saves are serialized and use optimistic
revision checks; close and quick replay wait for the newest edit to be saved.
Failed saves keep the editor open. Reopening the same target restores its draft,
including unsent quick text. A conflicting server revision or another window's
draft is not overwritten automatically; the editor keeps the text available to
copy. Creation retries retain their client identifier across restarts.

## Stats

`TradingStatsView` (the Stats tab) shows the selected account's closed trades
only, so practice and real results never mix. It reloads when a trade closes or
a journal entry changes. R figures use only trades with a risk locked at the
first fill and always show that coverage; breakdowns are by plan timing (when
the pre-trade fields were first written), direction and tag (note tags plus the
strategy tag). Figures from fewer than 20 trades are marked as low sample.
Definitions live in `backend/app/trading_accounts/stats.py`.

## Quick replay

`QuickReplayOverlay` covers the chart cell while the live source is paused. It
loads a bounded candle window once and keeps a `SeriesWindowStore` that only
holds candles closed before the cursor; the forming candle is rebuilt from finer
candles when the step is smaller than the chart interval (`quickReplayModel.ts`).
Fill markers, notes, position and P&L use the same cut. Indicators run through
`useProvidedBarsIndicatorRuntime`, which computes on exactly the bars shown and
resets on rewind. Current drawings are not shown; snapshot images are the
record of what was on the chart at the time.

History reads use the workspace `MarketDataManager`. A complete compatible
cache range avoids another transport read; other ranges retain bounded backend
repair and pagination. The overlay copies the accepted candles, so subsequent
live amendments cannot silently rewrite the captured replay. Exiting releases
only this request observer, leaving sibling consumers and live subscriptions
intact. This is a detached capture, not an atomic provider snapshot across pages;
version persistence, update prompts and a general per-chart replay entry remain
separate work.

Finer candles are bound to the request that loaded them, including their period,
instrument, window and reload generation. A step change hides the old response
immediately; until matching finer candles arrive, only complete chart candles
are exposed. A late response cannot be reinterpreted at an earlier closing time.

Original notes are projected from immutable revisions saved strictly before the
cursor; later review annotations appear separately with their actual save time.
The risk plan is hidden until its saved time. Legacy coalesced or unavailable
history is shown as unavailable instead of substituting the latest text. This
projects the currently linked, undeleted entries; it does not reconstruct past
link/unlink or deletion operations. Snapshot metadata is clipped by capture time;
the replay still does not restore historical drawings.
