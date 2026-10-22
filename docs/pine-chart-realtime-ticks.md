# Chart strategies on observed aggregate-trade ticks

Chart `PINE_ENGINE` revisions with `calc_on_every_tick=true` negotiate the
external stream for `AGG_TRADE_EXECUTION` and `ORDER_INTENT`. The actual source
print updates the forming chart tuple and matches prior orders before one Pine
tick observation receives the authoritative account. Newly emitted orders wait
for a later print, including a later print with the same timestamp. Existing
fill reports still update ownership, account allocation and risk bookkeeping;
they do not duplicate that print's tick execution. Confirming a derived bucket
is a separate explicit realtime close observation before the next source event.

The stream opens with the first observed tuple and receives no future history
plan. Requested rows follow actual observation availability, including at an
equal millisecond; historical canonical-close reveal does not apply. The first
print's exact positive quantity identifies the opening observation across
durable continuation. V2 historical rules, marks, funding and liquidation remain
authoritative. Auxiliary account events update the ledger without inventing an
extra market tick. Simulated closing fills retain their explicit context and
account feedback when requested by the declaration.

Checkpoints preserve an open observed bar. Recovery reconstructs and verifies
Pine before restoring the matching ledger, so already recorded fills are not
matched again. Independent cost scenarios use fresh streams and accounts on
the same source clock. Reports distinguish source tick executions from bucket
confirmations and retain the aggregate-trade liquidity assumptions.

Controlled coverage includes V1, spot, V2 liquidation, serial and supervised
whole-run execution, callback opt-in/out, both tick flags, same-timestamp print
ordering, requested-data reveal, repeated closing fills and intrabar recovery.
These are frozen source-stream replays. They do not establish a connected
exchange subscription, arbitrary TradingView feeds or broker-fill equivalence.
Workbench physical ticks have their own [clock and qualification](pine-workbench-print-ticks.md).
Chart book admission, dynamic historical window discovery, total resources and
formal packaged acceptance remain work.
