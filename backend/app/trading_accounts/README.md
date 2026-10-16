# Trading accounts

Local trading accounts, practice matching and the trade journal. Persistence is
`DATA_DIR/trading-accounts.sqlite3`; snapshot images live in
`DATA_DIR/trading-snapshots/`. HTTP: `app.api.v1.trading_accounts`.

- `models.py`: validation, decimal handling, error codes.
- `store.py`: SQLite schema and queries (one lock, one transaction per mutation).
- `trades.py`: pure flat-to-flat grouping of fills into trades; reversals split
  the crossing fill and its fee. Trades are derived, never stored.
- `journal.py`: phases, revision coalescing (never across a phase boundary),
  plan locking at the first fill, field timing for hindsight labels, R metrics.
- `practice.py`: pure order matching over a candle price path.
- `practice_runtime.py`: the poll loop that drives matching from DataManager 1m
  candles.
- `service.py`: the transport-independent facade.

## Practice matching

Every second the runtime replays the 1m candles of each instrument with working
orders, from its cursor to now. Live matching and catch-up after the app was
closed are the same walk. A history gap pauses the instrument (`catching_up`)
rather than guessing.

- A new candle moves open → low → high → close when it closes up, otherwise
  open → high → low → close. Updates to a forming candle only add extremes not
  seen before, so prices from before an order existed never fill it.
- Limit orders need price to trade through the limit; stops fill at the trigger
  or the first price beyond it, plus slippage. Marketable limits fill at once.
- Bracket exits are reduce-only OCO children; a flat position cancels the rest.
- Not simulated: funding, liquidation, order-book depth and partial fills.
