# Pine chart orders

The chart strategy runner negotiates `ORDER_INTENT` for newly compiled Pine
strategies. Both direct runs and automatic data preparation carry that mode.
The API also retains `TARGET_POSITION` for the existing one-entry market-order
profile. New order-mode envelopes freeze `candlescope.pine-orders/1`; they need
a matching Host implementation identity before execution or recovery.

The Pine interpreter produces decisions. The Host's existing kernel admits and
matches orders, and its account supplies every subsequent Pine observation.
Cash, fees, profit and the net average-cost position come from that account.
Script entry IDs allocate quantities through
`HOST_NET_AVERAGE_COST_ENTRY_QUANTITY_FIFO_V1`.
For spot accounts, Pine net profit excludes cash exchanged for held inventory;
the adapter derives realized net profit from equity minus initial capital and
unrealized profit, as the workbench account adapter already does.

Supported chart orders include:

- market, limit, stop and stop-limit entries;
- up to 64 pyramiding entries, subject to Host risk and account admission;
- ID-specific quantity/percentage closes and close-all;
- absolute-price or tick-distance OCO exits, including brackets submitted
  before an entry fills;
- cancellation and replacement of pending script order IDs; and
- trailing stops on an ordered trade execution clock, with an explicit tick.

The development `pine-chart/3` and `pine-external/7` adapters negotiate
`external_orders=2` with the core's `EXTERNAL_ORDER_SCHEMA_VERSION`. Generic
`strategy.order` calls transact fixed quantities directly: opposing orders reduce
the existing net position before opening any remainder, without automatic entry
reversal sizing or entry pyramiding. They support market, limit, stop and
stop-limit orders, logical entry IDs, cancellation and subsequent ID-specific
closes/exits. The script's generic pending orders remain independent when another
entry closes.

Both entries and generic orders preserve named OCA groups (`none`, `cancel`,
`reduce`). The allocator applies peer effects immediately after each actual fill,
including partial fills, before Pine receives its fill callback. Names with
different OCA types are independent. Reduced quantities and entry reversal caps
survive checkpoints; cancellations and reductions release corresponding V2 order
margin. Generic/OCA revisions require `ORDER_INTENT`; legacy target-position
mode rejects them at admission.

`BAR_APPROX` keeps the Host's approximate OHLC fill policy. Aggregate-trade
execution evaluates completed signal bars and matches against subsequent trade
prints. It can advance a trailing stop between signal-bar evaluations.
`calc_on_order_fills` additionally negotiates
`candlescope.pine-fill-callbacks/1` with the installed chart adapter.
This profile requires `ORDER_INTENT` and `AGG_TRADE_EXECUTION`; incompatible
BAR or target-position runs are rejected before execution. Each actual fill
updates logical entry ownership before the next Pine observation. The callback
receives the actual account and only OHLCV incorporated from observed prints.
Its newly submitted orders become eligible on the next aggregate-trade event,
including a later event with the same millisecond timestamp.

Fill passes and the confirmed close have separate monotonic observation
sequences. The provider retains each pass's account, clock, confirmed flag and
requested-data prefix. Auxiliary bars closing in the same millisecond as a
fill remain hidden until the close has consumed the full cohort. Foreign symbol
metadata belongs to the outer registry; pass streams contain only symbol,
timeframe and visible bars. Checkpoints can restore an unconfirmed pass group.
`strategy.pineExecution` in the report identifies this causal execution profile
and counts observed bars and fill callbacks.
At a signal boundary, the Host closes the preceding trade-derived bucket before
applying later mark, funding or instrument-rule events. An auxiliary event can
confirm that bucket before the next trade arrives. Checkpoints preserve that
confirmation, while aggregate-trade gap and late-print guards remain active.

This is a causal Host replay contract. TradingView documents that its historical
`calc_on_order_fills` executions can read a bar's final OHLCV, while realtime
executions see developing values. CandleScope's observed-print callbacks do not
claim equivalence to that historical broker-emulator behavior. See the official
[strategy execution documentation](https://www.tradingview.com/pine-script-docs/concepts/strategies/#calc_on_order_fills).

`process_orders_on_close=true` additionally negotiates
`candlescope.pine-closing-tick/1`. The BAR and aggregate-trade chart runners
attempt execution at the revealed close price after the close decision. These
simulated ticks cannot use earlier high/low prices to trigger newly placed
orders. Closing fills use taker fees and market/stop slippage; explicit Host
latency remains in force. Physical event latency counts source events, while
an intrabar order's ordinary next-tick delay may elapse at the later simulated
close. V2 caps aggregate closing fills at observed bar volume times participation
minus quantity already filled in that bucket; V1 remains uncapped. This is a
liquidity assumption, not measured close-auction liquidity.

In the aggregate-trade profile, `calc_on_order_fills` also recalculates after
closing fills on the same immutable confirmed bar and timestamp. The actual
Host account changes, ordinary variables roll back and `varip` survives.
Callback orders can consume the same closing tick within the existing per-bar
pass/intent budgets. BAR plus fill recalculation remains rejected because its
OHLC matcher does not expose the required intrabar execution phases.

Reports append `_WITH_SIMULATED_CLOSE` to their fidelity label and expose the
closing contract, liquidity assumption and fill count. V2 fill provenance uses
`SCRIPT_BAR_CLOSE`; physical and simulated trace counts remain separate. Kernel
checkpoints freeze this mode, and independent cost scenarios use the same closing
hook. Older adapters and the Workbench external-account path keep rejecting the
declaration unless they explicitly opt into the core closing-tick contract.
The official [closing-order documentation](https://www.tradingview.com/pine-script-docs/concepts/strategies/#process_orders_on_close)
informs this behavior; these tests are not a TradingView output oracle.

`calc_on_every_tick` and `calc_on_every_history_tick`
still require further integration or core capability work. Entry constraints
are described in [pine-entry-risk.md](pine-entry-risk.md); four chart stop rules
use the separate [stop contract](pine-risk-stops.md) with explicit calendar,
capacity, recovery and fidelity boundaries.
Order comments/alert metadata, zero-quantity no-op parity, and non-fixed
default sizing also remain outside the external order profile. The current
runtime rejects unknown declaration options.

The Host validates order batches and rechecks risk when a pending order becomes
executable against the live ledger. Script IDs bind to actual accepted order
receipts using a Host-generated client tag. Rejection of an earlier submission
cannot shift the ownership of a later accepted order.

Checkpoints include the provider's causal history, kernel state, Host policy
state and order ownership/allocation state. Pending submission tags are also
retained for clocks that freeze a decision before order admission. The report's
`pine_orders` section exposes the logical entries and fill allocations.

For `EXECUTION_REALISM_V2`, Pine cost sensitivity independently executes each
scenario with a fresh interpreter, Host allocator, policy and account. It covers
both rich orders and the legacy target-position profile. Warmup, frozen imports,
requested-data references, explicit clocks and causal fill passes follow the
primary run's prepared input plan. Queued execution supports both whole-run and
isolated-provider workers. Shadow scenarios do not create persisted runs.

The Host first reexecutes the original costs and verifies decision, fill, ledger,
kernel-report, order, equity-curve and policy/allocation evidence against the
primary execution. Only then does it calculate the existing five-row robustness
matrix: baseline, +25% costs, +50% costs, one latency tier, and half participation.
The BAR latency row remains explicitly inapplicable. Each scenario records its
own decision/policy hashes, rejections, ending position and callback counts.
The matrix identifies `INDEPENDENT_PINE_HOST_REEXECUTION` as its decision source.

Every scenario retains provider-step deadlines, the original run's time ceiling,
generation/cancellation checks and provider-state limits. A mismatch or execution
failure aborts publication; scenario workers close on success and failure.
`cost_sensitivity_mode=SKIP` remains available. V1 execution has no matrix, matching
the existing generic execution contract. The matrix changes the complete report
seal; it leaves primary decisions, fills, ledger, orders and curves unchanged.

Relative/trailing exits now enter admission using allocated entry costs, or the
observed quote before their entry fills. The matcher subsequently binds the
prices to actual allocated fills. This avoids artificial unit-price tick and
minimum-notional rejections without supplying a future entry price.

Validation uses the actual installed interpreter, HTTP run creation, queued
workers, automatic preparation, a durable interrupted/resumed run and an
aggregate-trade trailing-stop case. The callback cases also cover per-fill
ownership, requested-data boundaries, and interruption after a durable forming
pass. Logs live under `output/pine-host/phase3/chart-fill-*.log` and
`output/pine-host/phase3/rich-chart-*.log`. Cost, policy, deadline and recovery
receipts are in `output/pine-host/phase3/pine-cost-*.log`. These are controlled
fixtures; current
work does not establish arbitrary TradingView broker-fill or live-tick parity.
