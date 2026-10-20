# V2 historical Pine BAR path

Chart `PINE_ENGINE` strategies with `calc_on_order_fills=true` and
`ORDER_INTENT` can now combine the historical OHLC path with
`EXECUTION_REALISM_V2`, `LINEAR_PERP_ONE_WAY_V2`, or both. Spot and V1 linear
accounts can also use the volume-participation path without changing their
account model. The subsequent [Workbench API integration](pine-workbench-v2-bar.md)
connects this matcher to frozen Workbench account data and durable replay;
settings UI and cost-matrix integration remain separate work.

The Host freezes `candlescope.pine-v2-bar/1`, with fill model
`PINE_OHLC_PATH_V2`. Execution-realism requests use the distinct scenario
`OHLC_NEAREST_EXTREME_PATH_V2`; omitting the scenario derives it from the
compiled callback strategy. Explicitly requesting the old worst-case
scenario is rejected. Ordinary noncallback BAR runs retain their existing
scenario and matcher.

## Source, price and account clocks

The runner buffers auxiliary account events until the canonical historical
bar is known, then merges `INSTRUMENT_RULES`, `MARK_INDEX` and `FUNDING` into
the synthetic OHLC timeline. Events at a path timestamp apply before price
matching at that timestamp. An auxiliary event inside a price leg inserts
an observation there; it is not a new OHLC vertex for market-order matching.
Later marks therefore cannot affect an earlier open fill.
Account events and path observations have stable logical ordinals across
segmented execution. Settlement equity points use that same clock, including
when a fill immediately triggers liquidation.

V2 account mark authority remains the historical `MARK_INDEX` stream. Path
prices set execution prices and never replace that mark. Margin reservations,
realized profit, funding, account liquidation and allocation use the existing
Host account. Ordinary fills publish their actual position before any
immediate maintenance settlement, which then publishes a separate account
execution and callback. Account settlements consume no synthetic market
capacity. Their trace identifies the actual auxiliary event or originating
path bar rather than relabeling it as a physical trade.

## Capacity and money

Each bar owns one `volume * participation_rate` budget shared by all
vertices, price crossings, callback orders and the simulated close. Partial
fills retain their remaining quantities. Capacity rounds down to the current
quantity step; unused dust is not invented as a fractional lot or carried
into another bar. IOC remainder expires and releases its reserved margin.
The account-only V2 mode without execution realism remains uncapped.

The new path's fee calculation and estimated fee reservation include the
actual V2 contract multiplier. This is Host bookkeeping evidence. It does
not qualify arbitrary nonunit Pine symbol metadata, default sizing or other
execution models; those remain separate interpreter/Host work.

For replayable materialized inputs, cost scenarios independently rerun Pine,
ownership and the account. Arbitrary iterators do not publish a sensitivity
matrix under the existing service contract. A fresh
baseline must reproduce the primary hashes, orders, curve and policy. Lower
participation really changes the shared budget. BAR latency remains explicitly
not applicable under the existing BAR API, rather than pretending that the
synthetic timeline is a physical trade clock.

## Recovery and boundaries

Checkpoints commit complete bars, including path/source cursors, account,
capacity and callback delivery receipts. A failed intrabar execution cannot
be snapshotted or reused; recovery reconstructs from its preceding durable
checkpoint. Auxiliary account events after the final observable bar still
settle the ledger, while callbacks remain pending with economic timestamps.
Those receipts survive restore and can be delivered at a subsequent observable
bar without repeating settlement. A newly supplied historical bar cannot
rewind an already consumed account-event horizon; such replacement requires
reconstruction of the frozen input. Auxiliary updates cannot revise a committed
bar, including at the same timestamp. Tail account events retain the last path
quote for order admission rather than manufacturing a quote from a later mark.
Row ceilings count observed bars during recovery, independently of the raw
source ordinal that also includes account events.

The OHLC path and interpolation remain synthetic, with the existing low-first
tie policy. Volume participation is a proxy, not reconstructed exchange
liquidity. This phase does not establish TradingView margin, liquidation,
partial-fill, pixel or live-tick equivalence. Realtime/history-tick scheduling,
magnifier detail, scalable requested-prefix updates and the remaining core
language/metadata gaps remain active goal work.
