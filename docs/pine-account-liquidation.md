# Host V2 account liquidation execution receipts

The chart Host adapter now reconciles the V2 account's automatic full-position
liquidation with actual Pine entry ownership. The retained pre-repair probe in
`output/pine-host/phase3/risk-stops-v2-liquidation-gap.json` reproduced an account
position of zero while Pine still owned 50 contracts. That explicit rejection
has been replaced by a real, ledger-backed settlement receipt.

## Contract and accounting authority

`candlescope.account-liquidation-execution/1` binds a terminal kernel execution
to the actual V2 `LIQUIDATION` ledger entry hash and ordinal. Mark/index, funding,
instrument-rule changes, and maintenance checks immediately after an ordinary
fill all publish the booked settlement. A fixed funding receipt keeps both its
economic settlement time and the later source event that reveals it.

The settlement follows `MARK_IMMEDIATE_NO_LIQUIDATION_FEE_V1`: it closes the
whole actual net position at the authoritative mark. It never applies a second
account fill, charges another fee, or consumes tape/bar matching capacity.
It cancels all pending orders, closes owned entry lots FIFO, and appears in
fills, allocation evidence, completed trades and equity reports. Its source kind
is `ACCOUNT_LIQUIDATION`, with the original triggering-event trace retained when
execution-realism traces are enabled. The account remains terminal; subsequent
Pine intents cannot reopen it, even after a daily risk reset. Risk-generated
closes and account liquidation do not count as additional script orders for
`max_intraday_filled_orders`.

An ordinary fill can itself cause immediate maintenance liquidation. Its receipt
is published while the account still holds the actual filled position. The
maintenance check then books liquidation, and the next receipt exposes the
actual flat account. For example, opening 50 at 125 against mark 100 produces
two account frames, 0 -> 50 -> 0, and one realized loss of 1250 under a unit
contract multiplier. Completed-trade derivation preserves receipt order for
same-sequence fills, including IDs such as `ord-9` followed by `ord-10`.

## Pine callbacks and recovery

Aggregate-trade `calc_on_order_fills` receives both actual executions. An account
event inside a currently observed forming bar uses only its already observed
trade OHLCV. A mark update does not rewrite the bar's close or volume.

When no forming bar is observable, the account settlement and ownership update
are immediate, while its Pine callback is queued until the next actual trade.
The callback audit records the economic execution time, observation time and
whether delivery was deferred. A pending callback at EOF remains visible in
the ledger instead of inventing a bar. This observation policy is
`OBSERVED_FORMING_BAR_OR_NEXT_TRADE_V1`.

Snapshots persist the execution proof and pending callback queue. Restore checks
the receipt against the account ledger and settlement fill/order; resuming does
not book another liquidation, consume the historical print again or recreate
the closed entry lots. Independent cost scenarios rerun their own Pine worker,
account, risk controller, allocation and settlement path.

## Evidence and limits

Controlled checks cover both BAR and trade kernels, long/short positions,
multiple entries, partial fills, cancellation, all three account-data triggers,
compound fill/liquidation, fixed funding, corrupted checkpoints, callback
deferral and installed-worker recovery. These tests exercise CandleScope's
declared account model. They do not qualify TradingView margin liquidation,
partial margin reduction, native-account broker equivalence, official historical
callback semantics, or packaged-app UI acceptance.

The installed risk-stop candidate remains isolated. This change does not replace
the retained default task runtime or publish a release. See
`pine-host-completion-goal.md` for the remaining Host/core work.

The final frozen production source passed 373 Host cases (41 scoped exclusions),
162 kernel/risk/report cases and 103 accounting/execution/checkpoint cases. The
eight installed-Pine liquidation cases are included in the Host gate. Groups
overlap; these counts are not additive. Lint and `git diff --check` passed.
`output/pine-host/phase3/liquidation-candidate-receipt.json` binds the local commit,
source-freeze hashes, installed binary/package proof and terminal test logs.
The earlier stop candidate's 328-case run remains historical evidence; the new
373-case gate includes its later funding/history regressions and the implemented
liquidation path against the same final production source.
