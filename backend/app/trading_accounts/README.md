# Trading accounts

Local trading accounts, practice matching and the trade journal. Persistence is
`DATA_DIR/trading-accounts.sqlite3`; snapshot images live in
`DATA_DIR/trading-snapshots/`. HTTP: `app.api.v1.trading_accounts`.

Control/read adapters enter `DataManagerCore.trading`, which delegates to the
existing service; it does not merge practice, private-account, replay or strategy
ledgers. `/accounts/{id}/events` sends complete NDJSON replacement views after
committed writes or successfully applied valuation observations. Persistent
ledger epoch/sequence rolls back with the ledger; connection epoch/sequence also
orders unflushed valuation observations. Summary, trades and journal share one
read-only WAL snapshot and one temporary trade projection. Journal read failure
is explicit and does not hide valid financial views.

The existing committed-wakeup helper coalesces notifications. The manager limits
subscriptions to 16 and reads at most once per second per subscription, with
read-free 15 s heartbeats. Same-account readers may share a 5 ms batch only before a WAL snapshot starts; late readers acquire a new snapshot. Delivered views are independently copied, and the last reader releases its task. Closing views releases subscriptions, not background
matching. Reconnect always obtains a complete state; the stream is not a
resumable fill log. New practice accounts default to HEDGE for futures. ONE_WAY remains selectable. HEDGE accounts accept an explicit
LONG/SHORT positionSide and open/close positionEffect for futures orders.
The same path matcher processes both legs in price/time order. Gross margin
uses the sum of both marked notionals divided by leverage. Each close and
its bracket are scoped to one position lifecycle. Schema v4 preserves older
orders, fills, trade IDs and journal links with a null position_side.

Each market `(exchange, market_type, symbol)` follows one kline series
(ADR-DATA-002 D1c). An order may name a provider series in an optional
`identity` object, such as Twelve Data's AAPL:NASDAQ regular session. Schema v5
records it as canonical JSON on orders, fills and the practice cursor; NULL is
the exchange's own series, so older rows keep their meaning. The cursor, marks
and excursions read that series. While a market has working orders or open
positions in any account, an order that names another series is refused with
`TRADING_SERIES_MISMATCH`; an order without `identity` follows the current one.
Any market type is accepted. The symbol's catalog row declares its
`accountModel` (ADR-DATA-002 D5b, `account_models.py`): `cash` is fully paid and
long only; `crypto_linear` gets the account's leverage, shorting and hedge mode
on any venue (Gate's `swap.linear` as well as Binance `futures`);
`crypto_inverse` and `futures_margin` open no positions yet
(`TRADING_ACCOUNT_MODEL_UNSUPPORTED`) but close existing ones. A symbol without
a declaration, or one the catalog has not loaded, keeps the earlier rule:
`futures` is linear, anything else is cash. `GET /trading/market-rules` gives
the order ticket the same answer.

- `models.py`: validation, decimal handling, error codes.
- `store.py`: SQLite schema and queries (one lock, one transaction per mutation).
- `trades.py`: pure flat-to-flat grouping of fills into trades; reversals split
  the crossing fill and its fee. Trades are derived, never stored.
- `journal.py`: phases, plan locking at the first fill, field timing for
  hindsight labels, R metrics. Every changed journal save appends an immutable
  revision. Trade detail includes revision save times for causal quick replay.
  Schema v2 preserves old revision bytes and marks their historical coverage
  incomplete because previous autosave coalescing could overwrite versions.
  Saving a legacy note starts complete coverage at that new save, not earlier.
  `expectedRevision` rejects stale edits with HTTP 409; identical retries are
  accepted. An optional `clientEntryId` makes creation retries idempotent.
- `app/simulation/practice_account.py` (moved there in ADR-BACKTEST-015 P6e): the practice account
  model shared with forward strategy runs — pure order matching over a candle price path,
  buying power and margin. This package keeps the practice ledger and calls it.
- `practice_runtime.py`: the loop that drives matching from DataManager 1m
  candles.
- `stats.py`: pure closed-trade statistics for one account (definitions in its
  docstring); `GET /trading/accounts/{id}/stats?fromMs&toMs&tag` filters on
  close time and tags.
- `service.py`: the transport-independent facade.

## Practice matching

Application shutdown stops the practice matcher, then awaits
`DataManagerCore.shutdown_trading()` before closing the ledger. Cancelling
subscriptions signals their storage tasks to stop; physical reads already in a
thread remain owned until completion. Cancelling the shutdown waiter also drains
those reads before propagating cancellation. `close_trading()` only signals stop.

A market on a session calendar (ADR-DATA-002 D2/D5a) does not trade while it is
closed. A market order, or a limit already through the price, placed while it is
closed stays working (`waitsForOpen` in the response) and fills at the next
open. The first candle after a closure starts at its open rather than at the
previous close, so orders the open gapped through fill at the open: a limit at
the open when that is better, a stop at the open plus slippage. Always-open
markets have no session calendar and keep moving from the last close.

A step replays the 1m candles of one instrument with working orders, from its
cursor to now, in one storage-executor job (query, match, persist). Live
matching and catch-up after the app was closed are the same walk. A history gap
pauses the instrument (`catching_up`) rather than guessing.

- Each live 1m update (`BAR_CREATED/UPDATED/CLOSED`) wakes the loop and steps
  that instrument; bursts coalesce into one step per 100 ms.
- A sweep every second syncs streams with working orders and steps every
  instrument that had no event-driven step since the previous sweep.
- The cursor lives in memory. SQLite is written when the candle, its extremes or
  the feed status change, when orders fill, and otherwise every 10 s.
- `account_summary().feeds[]` reports `lagMs` (live update → matched) and
  `timing` (`wakeMs` event loop, `queueMs` storage executor, `queryMs`,
  `applyMs`) for the last event-driven step.

- A new candle moves open → low → high → close when it closes up, otherwise
  open → high → low → close. Updates to a forming candle only add extremes not
  seen before, so prices from before an order existed never fill it.
- Limit orders need price to trade through the limit; stops fill at the trigger
  or the first price beyond it, plus slippage. Marketable limits fill at once.
- Bracket exits are reduce-only OCO children; a flat position cancels the rest.
- Not simulated: funding, liquidation, order-book depth and partial fills.
