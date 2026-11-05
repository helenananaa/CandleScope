# Gate spot native 1m boundary contract

The packaged Gate chart advertised 1m but switching from 1s returned
`native_bar_basis_unknown`. The resolver correctly rejected an undeclared
native basis. This change qualifies only Gate spot 1m for history and realtime.

Gate's [official REST contract](https://www.gate.com/docs/developers/apiv4/en/spot/#market-k-line-chart)
lists 1m and Unix-second opens. The [official WS contract](https://www.gate.com/docs/developers/apiv4/ws/en/#candlesticks-channel)
subscribes to `spot.candlesticks` with `["1m", "BTC_USDT"]`; its example labels
1606292580 as a 1m open, aligned to a UTC minute. The direct public REST
capture in `backend/tests/fixtures/bar_basis/gate-1m-rest.json` independently
preserves twelve successive aligned minute opens, raw OHLCV and row[7]
finality, including the forming last row. It is an observed fixture, not a
proof that future provider responses cannot change.

The admitted schedule is `[open, open + 60000)` with inclusive stored close
`open + 59999`; off-minute rows remain rejected. REST uses its existing path;
unified WS uses the existing successor-observed finality policy. The contract
metadata describes these actual routes. No finality algorithm changes here.

Regression tests reproduce the original history/realtime resolver refusal,
then exercise captured OHLCV through production NormalizeLayer and reject a
shifted boundary. Gate weekly/monthly, derivatives and Upbit 1m remain unknown.
This is not qualification of other Gate periods, replay, Windows or all #131.
