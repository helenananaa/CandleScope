# V2 working-order margin repricing

`candlescope.v2-margin-reprice/1` belongs to CandleScope's
`LINEAR_PERP_ONE_WAY_V2` account and matchers. Pine still emits intents and reads
actual Host account feedback. This does not implement TradingView's native
broker-emulator margin model or exchange-specific liquidation/admission rules.

Initial-margin availability and maintenance liquidation are separate states.
A mark change can leave available collateral negative while equity remains above
maintenance. The existing position remains active and a closing/reduce-only order
can execute without reserving opening margin. Account snapshots preserve this
state. A flat account with a negative wallet is insolvent, rejects new trading,
and does not invent a liquidation fill. A negative wallet with an adequately
funded profitable open position does not itself prevent closing that position.

Working opening exposure is checked before matching, at the actual prospective
execution price, on account mark/rule/funding updates, and after booked fills.
Each direction has its own FIFO closing allowance from the actual position;
opposing pending orders cannot net each other's margin. Prior reduce-only orders
consume that closing allowance. Same-direction MARKET orders reserve their own
opening quantities instead of repeatedly reserving the aggregate projected batch.

The reference is the maximum of historical mark, observed execution/path quote,
the relevant validated visible book quote, and that order's limit/stop prices.
It is an explicit conservative CandleScope policy. Historical mark remains the
authority for unrealized PnL and maintenance; repricing does not overwrite it.
Oldest orders receive collateral first, using equity minus position initial
margin. Estimated fees also consume that pass's budget, using the larger absolute
maker/taker rate. The frozen order-margin field contains initial margin, without
charging hypothetical fees to the wallet. Actual fees include the historical
contract multiplier once in BAR, trade and Pine BAR paths.

An opening or reversal order whose entire remainder no longer fits is cancelled
atomically. It is not silently resized or converted to a closing order. Earlier
actual fills, position lots and fees remain booked. Zero-opening closing orders
remain eligible even with negative initial-margin availability. Account journal
entries record `ORDER_MARGIN_REPRICED` or `ORDER_MARGIN_REPRICE_REJECTED`, with
time, policy, reference and amounts; execution-realism V2 also records a cancelled
order lifecycle event with reason `ACCOUNT_MARGIN_REPRICE_REJECTED`. Repeating
the same check does not append redundant journal entries. Cancellation produces
no trading fill or Pine order-fill callback. Real maintenance settlement retains
its separately booked execution receipt and callback.

Book events must validate before their quotes affect margin. Sampled books retain
their separate visibility/staleness and matching constraints; a margin check
cannot create book liquidity or permit an otherwise forbidden fill. The helper
iterates the kernels' active-order index rather than completed order history.
V1 and spot calculations bypass the margin policy. Broader regression also
exposed an existing standalone V1 book entry point that omitted its observed
print mark and fill timestamp. That entry point now sets both before matching,
while V2 keeps historical mark authority.

Snapshots disclose the margin policy and reject unknown policy identifiers.
Raw legacy account snapshots without this field can restore as account state;
that is not a guarantee that an old complete run can replay under changed Host
code. Whole-run source/runtime identity checks still apply. Existing saved
reports are not rewritten.

Regression evidence includes negative-availability restore/close, independent
directional reservations, FIFO/reversal/reduce-only rules, funding, book
validation and quotes, estimated/actual multiplier fees, and flat insolvency.
Installed Pine worker tests cover a partial-fill gap through both Workbench
and chart paths, Workbench replay, chart durable recovery and independent cost
accounts. In the controlled zero-fee Workbench case, a 50-unit entry fills 5 and
5 at 10 with historical mark 8, then cancels its remaining 40 before the next
bar opens at 20. Position stays 10, equity 80, and frozen margin zero; Pine sees
exactly two fill callbacks. This is synthetic-fixture qualification, not a
TradingView oracle, packaged product or historical exchange-data acceptance.

The account still models immediate mark-based maintenance liquidation without
insurance funds, ADL or liquidation fees. A prospective execution can change
actual equity through mark-to-fill divergence and fees; this policy does not
promise an exchange-style pretrade simulation of every possible future fill.
Large-history journal/reconstruction performance remains separately unqualified.
