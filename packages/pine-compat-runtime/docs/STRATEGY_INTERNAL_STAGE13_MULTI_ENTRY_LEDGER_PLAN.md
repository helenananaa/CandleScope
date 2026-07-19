# Strategy Internal Stage 13 Multi-Entry Ledger Plan

Status: closed through Slice 101 on 2026-06-06. Stage 13 now records the
fixture-backed long-only multi-entry ledger and pyramiding subset described in
the compatibility contract below. Support claims still come from
`tests/fixtures/conformance.tsv`, snapshots, host-parity fixtures, and release
verification; this plan does not claim shorts, reversals, `strategy.order()`,
`close_entries_rule`, public pending-order output, or broader multi-entry
reporting.

Stage 12 closed the declaration-property boundary and explicitly warned against
accepting another `strategy()` property as a no-op. Stage 13 designed and
fixture-backed the long-only multi-entry ledger foundation before any short,
reversal, `close_entries_rule`, or generic order work is accepted.

Primary official reference:

- TradingView Pine Script strategies:
  https://www.tradingview.com/pine-script-docs/concepts/strategies/

Relevant official rules:

- `strategy.entry()` can reverse an open opposite-direction position by adding
  the open position size to the new transaction size.
- `pyramiding` limits the number of open trades from `strategy.entry()` in one
  position; the default is `1`.
- Multiple price-based `strategy.entry()` orders triggered on the same tick can
  exceed the pyramiding setting.
- `strategy.order()` ignores most strategy properties such as `pyramiding` and
  changes the net market position directly.
- `strategy.close_all()` exits the open position without linking to a specific
  entry id, which matters once a position contains multiple open trades.
- By default, exits close oldest trades first; `close_entries_rule="ANY"` changes
  id-specific close behavior.

## Starting Point

The live repo currently supports a long-only one-net-position strategy broker:

- `strategy.entry()` accepts only `strategy.long` and supported market, limit,
  stop, and stop-limit entry forms.
- Repeated long entries while long are ignored by the current no-pyramiding
  rule.
- `strategy.close()`, `strategy.close_all()`, `strategy.cancel()`,
  `strategy.cancel_all()`, and the supported `strategy.exit()` subset operate
  against the current long-only position and internal pending-entry/exit books.
- `strategy()` still rejects `pyramiding` and `close_entries_rule`; sema also
  rejects `strategy.short` entries and generic `strategy.order()`.
- `TradeLedger` already stores a vector of `OpenTrade` values and FIFO
  allocation helpers, but normal entry opening still clears the ledger before
  pushing one long trade.
- `BrokerState` still carries singleton mirrors such as `position_size`,
  `avg_price`, `entry_id`, entry timing, and open-trade runup/drawdown fields.
- Public strategy output exposes filled orders, closed trades, aggregate
  position/equity snapshots, and diagnostics. It does not expose pending orders,
  open-trade ledgers, OCA groups, or declaration settings.

## Goal

Design a staged path from the current one-net-long broker to a Pine-compatible
multi-entry foundation without widening compatibility claims prematurely.

The design must answer these internal questions before runtime behavior changes:

- Which broker fields become derived from `TradeLedger`, and which singleton
  fields can remain as public aggregate mirrors?
- How `pyramiding` counts open and pending `strategy.entry()` trades in the
  current historical timing model.
- How repeated same-id entries, same-direction entries, and price-based pending
  entries interact with the pyramiding limit.
- How FIFO close allocation works for `strategy.close()`,
  `strategy.close_all()`, and `strategy.exit()` before
  `close_entries_rule="ANY"` is accepted.
- Which unsupported pieces stay locked: shorts, reversal, `strategy.order()`,
  OCA across order families, public pending-order output, realtime recalculation,
  and strategy order-fill alerts.

## Non-Goals

- No runtime widening in Slice 0.
- No acceptance of `pyramiding`, `close_entries_rule`, short entries,
  reversals, `strategy.order()`, OCA settings, or risk APIs in the design slice.
- No public `StrategyResult` schema expansion.
- No public pending-order or open-trade ledger output.
- No realtime/tick recalculation changes.
- No change to existing no-pyramiding behavior until a behavior slice is
  fixture-backed.

## Compatibility Boundary

The first behavior stage after design should be long-only and aggregate-output
only. It may use `TradeLedger` internally, but public output must remain the
existing aggregate strategy JSON unless a separate schema stage is designed.

Allowed first behavior target after the design and boundary-lock slices:

- `strategy(..., pyramiding=N)` with positive const integer `N`;
- long-only `strategy.entry()` market entries first;
- existing supported explicit/default quantity paths;
- multiple open long trades with aggregate `strategy.position_size`,
  `strategy.position_avg_price`, equity, and profit variables derived from the
  ledger;
- `strategy.close_all()` flattening all open long trades;
- default FIFO allocation for closes and exits.

Still out of scope for the first behavior target:

- short exposure and automatic reversal;
- `strategy.order()` netting behavior;
- `close_entries_rule="ANY"`;
- price-based same-tick pyramiding-limit exceptions;
- multiple pending entry fills that exceed the limit;
- OCA across generic orders;
- public open-trade or pending-order schema expansion;
- strategy order-fill alert delivery.

## Slice Plan

### Slice 0: Design Gate

Status: closed on 2026-06-05. This slice did not change runtime behavior,
conformance, fixtures, snapshots, or public output.

Goal:

- define the Stage 13 multi-entry and pyramiding boundary before code changes.

Acceptance:

- official strategy-entry, pyramiding, close-all, FIFO, and generic-order
  dependencies are recorded;
- the live one-net-long baseline is documented;
- the first behavior target is long-only and public-schema preserving;
- unsupported short/reversal/generic-order/OCA/realtime boundaries are explicit.

### Slice 1: Boundary Lock

Status: closed on 2026-06-05. This slice added test assertions only and did not
change runtime behavior, conformance, fixtures, snapshots, matrix output, or
public JSON.

Goal:

- add or refresh tests proving the current repo still rejects or no-ops the
  pieces Stage 13 has not accepted.

Targets:

- sema diagnostics for `pyramiding`, `close_entries_rule`, `strategy.short`, and
  `strategy.order()` remain stable;
- runtime repeated-long-entry no-pyramiding behavior remains stable;
- conformance stays unchanged except for fixture registration if needed.

Acceptance:

- unsupported boundaries are fixture-backed before any positive behavior route
  changes;
- no public output or matrix support claim widens.

Closed evidence:

- `crates/pine-sema/tests/fixtures.rs` now asserts that unsupported
  `pyramiding` and short-entry diagnostics name the relevant unsupported
  boundary.
- `unsupported_strategy_declaration_properties.pine` still covers
  `close_entries_rule`, and `unsupported_strategy_orders.pine` still covers
  `strategy.order()`.
- `crates/pine-runtime/src/tests/strategy.rs` now verifies repeated long entries
  without accepted pyramiding still emit only the first entry order, keep a
  one-unit position at the first fill price, produce no closed trades, and emit
  no runtime diagnostics.

### Slice 2: Ledger Ownership Audit

Status: closed on 2026-06-05. See
`docs/STRATEGY_INTERNAL_STAGE13_LEDGER_OWNERSHIP_AUDIT.md`. This slice did not
change runtime behavior, conformance, fixtures, snapshots, matrix output, or
public JSON.

Goal:

- document and, if needed, test the internal split between `TradeLedger` and
  singleton aggregate broker fields.

Targets:

- identify every `BrokerState` field that duplicates ledger state;
- define derived aggregate behavior for position size, average price, max held
  contracts, open profit, runup/drawdown, commission, and margin inputs;
- keep current one-open-trade runtime behavior unchanged.

Acceptance:

- internal ledger invariants are covered by unit tests or audit notes;
- no accepted script produces different output.

Closed evidence:

- The ownership audit records current `TradeLedger` responsibilities, legacy
  singleton `BrokerState` mirrors, aggregate accounting owners, and the existing
  unit-test evidence for single-open-trade mirroring, reductions, and FIFO
  allocation helpers.
- The next migration order is locked before any positive `pyramiding` behavior:
  centralize ledger mutation helpers, keep aggregate public mirrors stable,
  convert open-trade namespace reads later, and preserve the current public
  `StrategyResult` schema.

### Slice 3: Entry Fill Ownership Helper

Status: closed on 2026-06-05. This slice introduced a private helper for the
current long-entry fill ownership handoff and did not change runtime behavior,
conformance, fixtures, snapshots, matrix output, or public JSON.

Goal:

- route the existing one-open-long entry fill through one helper that updates
  both legacy singleton mirrors and `TradeLedger`.

Closed evidence:

- `BrokerState::entry_long()` now calls `record_open_long_trade()` after
  constructing the supported `OpenTrade`.
- `record_open_long_trade()` owns the current handoff to
  `record_open_long_legacy_state()` and `trade_ledger.open_long()`.
- Existing single-entry, pending-entry, ledger mirror, and full release gates
  continue to pass with unchanged behavior.

### Slice 4: TradeLedger Append Helper

Status: closed on 2026-06-05. This slice added an internal ledger append helper
and unit test only. Runtime behavior, conformance, fixtures, snapshots, matrix
output, and public JSON are unchanged.

Goal:

- prepare the ledger for later multi-entry work without routing accepted scripts
  into multi-open-trade behavior.

Closed evidence:

- `TradeLedger::open_long()` still clears existing open trades, preserving the
  current one-net-long runtime behavior.
- `TradeLedger::append_long()` appends an open long trade and rebuilds the
  weighted aggregate `NetPosition`.
- `trade_ledger_append_long_rebuilds_weighted_net_position` covers the internal
  append invariant before any public `pyramiding` route uses it.

### Slice 5: Aggregate Position Sync Helper

Status: closed on 2026-06-05. This slice added a private aggregate sync helper
and routed the current one-open-long entry handoff through it. Runtime behavior,
conformance, fixtures, snapshots, matrix output, and public JSON are unchanged.

Goal:

- prepare aggregate `position_size` and `avg_price` ownership for later
  multi-entry work by syncing them from `TradeLedger::net_position()`.

Closed evidence:

- `BrokerState::record_open_long_trade()` now calls
  `sync_aggregate_position_from_ledger()` after updating `TradeLedger`.
- The helper currently updates only aggregate position size and average price;
  entry id, open-trade namespace mirrors, runup/drawdown state, and public
  output remain under the current one-open-trade legacy contract.
- Existing entry, pending-entry, ledger mirror, and full release gates continue
  to pass with unchanged behavior.

### Slice 6: Allocation Sync Helper

Status: closed on 2026-06-05. This slice routed existing long close, exit, and
margin-call allocation updates through a private aggregate sync helper. Runtime
behavior, conformance, fixtures, snapshots, matrix output, and public JSON are
unchanged.

Goal:

- keep aggregate `position_size` and `avg_price` derived from `TradeLedger`
  after existing allocation updates.

Closed evidence:

- Long `strategy.close`, supported `strategy.exit` fills, and long margin-call
  reductions now call `apply_trade_allocations_and_sync_position()` after
  recording the same closed-trade and cash effects.
- Full-close fallback for empty allocation lists still clears the ledger and
  syncs aggregate position to flat.
- Existing partial close, partial exit, margin, strategy entry, and full release
  gates continue to pass with unchanged public output.

### Slice 7: Default Pyramiding Gate Helper

Status: closed on 2026-06-05. This slice added an internal default
`pyramiding_limit` of `1` and routed current long-entry admission checks through
`can_open_long_entry()`. Runtime behavior, conformance, fixtures, snapshots,
matrix output, and public JSON are unchanged.

Goal:

- isolate the current no-pyramiding long-entry gate behind one helper before
  accepting any public `pyramiding` setting.

Closed evidence:

- `BrokerState` now stores `pyramiding_limit: 1` by default.
- Market, limit, stop, and stop-limit long-entry placement/fill paths use
  `can_open_long_entry()` instead of direct aggregate-position checks.
- `default_pyramiding_limit_allows_only_one_long_entry` proves the internal
  default still rejects a second long entry and leaves a single open trade.

### Slice 8: Open-Trade Count Ledger Read

Status: closed on 2026-06-05. This slice changed the internal
`open_trade_count()` source from singleton mirrors to `TradeLedger::open_count()`
and added an internal multi-ledger count test. Runtime behavior, conformance,
fixtures, snapshots, matrix output, and public JSON are unchanged.

Goal:

- make the strategy open-trade count read path ledger-backed before accepting
  public multi-entry behavior.

Closed evidence:

- `BrokerState::open_trade_count()` now returns the ledger open count with
  overflow clamped to `i64::MAX`.
- Existing no-pyramiding runtime behavior still keeps the ledger count at `0` or
  `1`.
- `open_trade_count_reads_trade_ledger_count` proves the internal count path can
  observe two ledger entries before any accepted script can create them.

### Slice 9: Open-Trade Field Ledger Reads

Status: closed on 2026-06-05. This slice changed the internal
`strategy.opentrades.*` field read helpers from singleton mirrors to
ledger-indexed reads and added an internal two-entry field test. Runtime
behavior, conformance, fixtures, snapshots, matrix output, and public JSON are
unchanged.

Goal:

- make open-trade field reads index the ledger directly before accepting public
  multi-entry behavior.

Closed evidence:

- `TradeLedger::open_at()` exposes a bounded internal accessor for open trade
  field reads.
- `BrokerState::open_trade_entry_price()`, `entry_id()`, `entry_bar_index()`,
  `entry_time()`, `size()`, `profit()`, `commission()`, `max_runup()`, and
  `max_drawdown()` now read from the requested ledger entry index.
- `open_trade_fields_read_trade_ledger_entries` proves fields can be read from
  ledger indexes `0` and `1`, with out-of-range and negative indexes returning
  `None`.

### Slice 10: Long Market Pyramiding Entry Foundation

Status: closed on 2026-06-05. This slice accepts the first public
`strategy(..., pyramiding=N)` subset for positive integer const values and
same-direction long market entries. It does not yet claim price-based same-tick
entry exceptions, shorts, reversals, `strategy.order()`, or broader multi-entry
exit/reporting semantics.

Goal:

- implement the first positive multi-entry behavior for long market entries.

Target subset:

- `strategy(..., pyramiding=N)` with positive const integer `N`;
- same-direction long market entries only;
- existing explicit/default quantity paths;
- no short/reversal/price-based entry exception behavior;
- aggregate public strategy JSON only.

Closed evidence:

- `StrategySettings::pyramiding_limit` defaults to `1`, sema accepts positive
  integer const `pyramiding`, and runtime initializes `BrokerState` with that
  limit.
- `record_open_long_trade()` appends open trades when the configured limit is
  above `1`, and keeps the default no-pyramiding path unchanged.
- Aggregate `position_size`, `avg_price`, and `max_contracts_held_long` sync
  from the ledger after accepted long market entries.
- `strategy_pyramiding.pine` covers two long market entries, the third entry
  rejected by the limit, aggregate position state, `strategy.opentrades`, and
  index `0`/`1` open-trade field reads.
- conformance, matrix, docs, release notes, and `scripts/verify.sh` are
  synchronized.

### Slice 11: Multi-Entry `strategy.close(id)` Matching

Status: closed on 2026-06-05. This slice lets `strategy.close(id)` close the
matching open long trade in the accepted multi-entry pyramiding subset. It does
not yet claim `strategy.close_all()`, `strategy.exit`, price-based entry
exceptions, shorts, or reversals.

Goal:

- make `strategy.close(id)` use ledger entry matching instead of the legacy
  singleton `entry_id` gate.

Closed evidence:

- `TradeLedger::open_quantity_for_entry()` reports the currently open quantity
  for a requested entry id.
- `strategy.close(id)`, `strategy.close(id, qty=...)`, and
  `strategy.close(id, qty_percent=...)` now gate and clamp against the matching
  ledger entry quantity.
- `strategy_pyramiding_close.pine` covers closing `L1` while `L2` remains open,
  then closing `L2` to flatten the position.

### Slice 12: Multi-Entry `strategy.close_all()`

Status: closed on 2026-06-05. This slice lets `strategy.close_all()` flatten
all open long trades in the accepted pyramiding subset. It does not yet claim
`strategy.exit`, price-based entry exceptions, shorts, or reversals.

Goal:

- make `strategy.close_all()` allocate across every open long ledger entry and
  record closed trades for each matched entry.

Closed evidence:

- `close_all_long()` now allocates the full aggregate position through
  `TradeLedger::allocate_exit_fifo(None, position_size)`.
- Each allocation records a closed trade using that entry's id, entry price,
  entry bar/time, quantity, and proportional commission share.
- `strategy_pyramiding_close_all.pine` covers two pyramided long entries closed
  by one `strategy.close_all()` call, leaving `strategy.opentrades` and
  `strategy.position_size` at `0`.

### Slice 13: Pending Exit Module Split

Status: closed on 2026-06-05. This is a no-behavior-change structure slice
before widening multi-entry `strategy.exit`. It keeps the next compatibility
slice small by moving pending exit data structures out of the placement logic.

Goal:

- split pending exit types and the pending exit book out of `exits.rs` while
  preserving every existing broker behavior and public fixture claim.

Closed evidence:

- `pending_exits.rs` now owns `PendingExit`, `PendingExitBook`, trailing exit
  state, deferred relative exit state, and quantity helper types.
- `exits.rs` now keeps the broker placement/resolution logic and drops from the
  structure guardrail edge to roughly 1040 lines.
- Broker tests and the structure guardrail pass without changing conformance
  fixtures or snapshots.

### Slice 14: Multi-Entry Absolute `strategy.exit(from_entry)` Matching

Status: closed on 2026-06-05. This slice lets supported absolute
`strategy.exit` forms match an open pyramided long entry by `from_entry`, even
when that entry is not the legacy aggregate `entry_id`. It does not claim
entry-specific profit/loss tick price conversion, trailing price conversion,
brackets, shorts, reversals, or `close_entries_rule`.

Goal:

- route supported absolute stop/limit `strategy.exit` placement and pending fill
  eligibility through the open-trade ledger entry quantity instead of the legacy
  current-entry mirror.

Closed evidence:

- `place_exit()` now resolves the target quantity from
  `TradeLedger::open_quantity_for_entry(from_entry)` for open positions.
- Pending exit evaluation keeps exits whose `from_entry` still has open ledger
  quantity and clears only entries no longer open.
- `strategy_pyramiding_exit_from_entry.pine` covers two pyramided long entries
  where an absolute limit exit targets and closes `L1` while `L2` remains open.

### Slice 15: Multi-Entry Relative `strategy.exit` Tick Price Basis

Status: closed on 2026-06-05. This slice makes supported single-trigger
`profit`/`loss` tick exits use the requested open entry's entry price when
`from_entry` matches a pyramided long entry. It does not claim same-ID multi-entry
fan-out, bracket relative legs, trailing `trail_points`, shorts, reversals, or
`close_entries_rule`.

Goal:

- calculate supported `profit`/`loss` single-trigger exit prices from the matched
  ledger entry price instead of the aggregate position average.

Closed evidence:

- `TradeLedger::first_open_entry_price_for_entry()` exposes the matched open
  entry price for broker-only exit price conversion.
- `place_exit_profit_ticks_quantity()` and `place_exit_loss_ticks_quantity()` now
  use entry-specific price conversion before routing through the existing
  `place_exit()` ledger quantity gate.
- `strategy_pyramiding_exit_profit_from_entry.pine` covers a profit-tick exit
  that closes `L1` at `L1`'s entry-price-derived target while `L2` remains open.

### Slice 16: Same-ID `strategy.exit` Allocation Fan-Out

Status: closed on 2026-06-05. This slice lets a supported `strategy.exit` fill
against multiple open long trades that share the requested `from_entry` id. It
does not claim omitted-`from_entry` persistent all-entry exits, bracket/trailing
same-ID fan-out beyond the existing supported trigger families, shorts,
reversals, or `close_entries_rule`.

Goal:

- record one public `strategy.exit` order event and one closed trade per matched
  ledger allocation when a single pending exit closes multiple open trades with
  the same entry id.

Closed evidence:

- `fill_pending_exit()` now iterates matched ledger allocations, preserving each
  allocation's entry price, entry bar/time, quantity, and proportional commission
  in separate public order/trade records.
- Existing single-allocation exits keep the same public shape.
- `strategy_pyramiding_exit_same_id.pine` covers two pyramided `strategy.entry`
  fills with the same id and one absolute `strategy.exit` that closes both as
  two `strategy.exit` order events and two closed trades.

### Slice 17: Multi-Entry Relative Bracket Price Basis

Status: closed on 2026-06-05. This slice makes supported bracket `profit` and
`loss` relative legs use the requested open entry's entry price when `from_entry`
matches a pyramided long entry. It does not claim trailing `trail_points`,
omitted-`from_entry` persistent all-entry exits, shorts, reversals, or
`close_entries_rule`.

Goal:

- calculate supported bracket relative `profit`/`loss` leg prices from the
  matched ledger entry price instead of the aggregate position average.

Closed evidence:

- Active `stop+profit`, `loss+limit`, and `loss+profit` bracket placement now
  uses the same entry-specific price conversion helpers as single-trigger
  `profit`/`loss` exits.
- Deferred relative bracket resolution uses the matched entry price after the
  pending entry fills.
- `strategy_pyramiding_exit_bracket_from_entry.pine` covers a `profit+loss`
  bracket that closes `L1` at `L1`'s entry-price-derived target while `L2`
  remains open.

Future slices:

- omitted-`from_entry` persistent all-entry exit behavior;
- price-based same-tick pyramiding-limit exceptions;
- host parity coverage for broader public JSON contracts.

### Slice 18: Multi-Entry Trailing `trail_points` Price Basis

Status: closed on 2026-06-06. This slice makes supported trailing
`trail_points` activation use the requested open entry's entry price when
`from_entry` matches a pyramided long entry. It does not claim
omitted-`from_entry` persistent all-entry exits, shorts, reversals,
`close_entries_rule`, or public trailing-state fields.

Goal:

- calculate supported trailing `trail_points` activation prices from the matched
  ledger entry price instead of the aggregate position average.

Closed evidence:

- Active trailing `trail_points + trail_offset` placement now uses the same
  entry-specific price basis as the supported single-trigger and bracket
  relative exits.
- Deferred relative trailing resolution after a matching pending entry fills now
  uses the filled entry price as the activation base.
- `strategy_pyramiding_exit_trail_points_from_entry.pine` covers a trailing exit
  that activates from `L1`'s entry-price-derived threshold, fills on the later
  active stop, closes only `L1`, and leaves `L2` open.

Future slices:

- omitted-`from_entry` persistent future-entry exit behavior;
- price-based same-tick pyramiding-limit exceptions;
- host parity coverage for broader public JSON contracts.

### Slice 19: Omitted `from_entry` Current All-Entry Absolute Exit

Status: closed on 2026-06-06. This slice accepts supported absolute stop-only
and limit-only `strategy.exit` calls that omit `from_entry` for the currently
open pyramided long entries. It does not claim the official persistent behavior
for entries opened after the call, all-entry relative tick conversion, trailing,
brackets, shorts, reversals, or `close_entries_rule`.

Goal:

- route omitted-`from_entry` absolute stop/limit exits through the ledger as an
  all-entry FIFO allocation instead of silently ignoring the runtime call.

Closed evidence:

- Runtime `strategy.exit("XL", limit=price)` now uses an internal all-entry
  pending exit sentinel and fills via `TradeLedger::allocate_exit_fifo(None,
  qty)`.
- `strategy_pyramiding_exit_omitted_from_entry_current.pine` covers two open
  long entries with different ids and one omitted-`from_entry` limit exit that
  records one public exit order and one closed trade per open ledger allocation.

Future slices:

- omitted-`from_entry` all-entry relative tick, bracket, and trailing behavior;
- price-based same-tick pyramiding-limit exceptions;
- host parity coverage for broader public JSON contracts.

### Slice 20: Omitted `from_entry` Persistent Future-Entry Absolute Exit

Status: closed on 2026-06-06. This slice extends the supported omitted-
`from_entry` absolute stop/limit all-entry exit so it also covers later long
entries opened before the position closes. It does not claim all-entry relative
tick conversion, trailing, brackets, shorts, reversals, `close_entries_rule`, or
public pending-order schema.

Goal:

- keep a supported omitted-`from_entry` full absolute stop/limit exit active for
  later pyramided long entries by expanding its reserved quantity after each
  later entry fill.

Closed evidence:

- Broker entry-fill paths expand an existing omitted-`from_entry` full
  stop/limit pending exit to the new aggregate position size and mark it updated
  on the entry fill bar.
- `strategy_pyramiding_exit_omitted_from_entry_persistent.pine` covers an exit
  call placed before the second entry opens; the later `L2` fill is covered by
  the persisted exit and closes alongside `L1`.

Future slices:

- omitted-`from_entry` all-entry `loss`, bracket, and trailing behavior;
- price-based same-tick pyramiding-limit exceptions;
- host parity coverage for broader public JSON contracts.

### Slice 21: Omitted `from_entry` Current All-Entry Profit Tick Exit

Status: closed on 2026-06-06. This slice adds the first omitted-`from_entry`
relative tick all-entry subset for currently open pyramided long entries whose
entry ids are unique. It covers full-quantity `profit` exits and does not claim
duplicate same-id per-trade relative targets, `loss`, future-entry persistence
for relative exits, brackets, trailing exits, shorts, reversals,
`close_entries_rule`, or public pending-order schema.

Goal:

- generate entry-specific pending limit exits for an omitted-`from_entry`
  `strategy.exit(..., profit=ticks)` call instead of using the aggregate average
  entry price or silently ignoring the call.

Closed evidence:

- Broker placement for omitted-`from_entry` profit ticks now reads current open
  ledger entries, rejects the unsupported duplicate-entry-id case by preserving
  the old no-op boundary, and replaces the pending exit book with one
  full-quantity limit exit per unique entry id.
- `strategy_pyramiding_exit_omitted_profit_from_entries.pine` covers two open
  long entries with different ids and one omitted-`from_entry` profit exit that
  closes `L1` at `L1`'s entry-price-derived target and `L2` at `L2`'s later
  entry-price-derived target.

Future slices:

- omitted-`from_entry` all-entry `loss`, bracket, and trailing behavior;
- omitted-`from_entry` relative future-entry persistence;
- duplicate same-id omitted-`from_entry` relative targets;
- price-based same-tick pyramiding-limit exceptions;
- host parity coverage for broader public JSON contracts.

### Slice 22: Omitted `from_entry` Current All-Entry Loss Tick Exit

Status: closed on 2026-06-06. This slice adds the symmetric omitted-
`from_entry` loss-tick all-entry subset for currently open pyramided long
entries whose entry ids are unique. It covers full-quantity `loss` exits and
does not claim duplicate same-id per-trade relative targets, future-entry
persistence for relative exits, brackets, trailing exits, shorts, reversals,
`close_entries_rule`, or public pending-order schema.

Goal:

- generate entry-specific pending stop exits for an omitted-`from_entry`
  `strategy.exit(..., loss=ticks)` call instead of using the aggregate average
  entry price or silently ignoring the call.

Closed evidence:

- Broker placement for omitted-`from_entry` loss ticks now reads current open
  ledger entries, rejects the unsupported duplicate-entry-id case by preserving
  the old no-op boundary, and replaces the pending exit book with one
  full-quantity stop exit per unique entry id.
- `strategy_pyramiding_exit_omitted_loss_from_entries.pine` covers two open long
  entries with different ids and one omitted-`from_entry` loss exit that closes
  `L1` at `L1`'s entry-price-derived stop and `L2` at `L2`'s later
  entry-price-derived stop.

Future slices:

- omitted-`from_entry` all-entry bracket and trailing behavior;
- omitted-`from_entry` relative future-entry persistence;
- duplicate same-id omitted-`from_entry` relative targets;
- price-based same-tick pyramiding-limit exceptions;
- host parity coverage for broader public JSON contracts.

### Slice 23: Omitted `from_entry` Current All-Entry Loss+Profit Bracket

Status: closed on 2026-06-06. This slice adds the first omitted-`from_entry`
bracket all-entry subset for currently open pyramided long entries whose entry
ids are unique. It covers full-quantity `loss+profit` brackets and does not
claim `stop+profit`, `loss+limit`, `stop+limit`, duplicate same-id per-trade
relative targets, future-entry persistence for relative exits, trailing exits,
shorts, reversals, `close_entries_rule`, or public pending-order schema.

Goal:

- generate entry-specific pending bracket exits for an omitted-`from_entry`
  `strategy.exit(..., loss=ticks, profit=ticks)` call instead of using the
  aggregate average entry price or silently ignoring the call.

Closed evidence:

- Broker placement for omitted-`from_entry` loss+profit brackets now reads
  current open ledger entries, rejects the unsupported duplicate-entry-id case
  by preserving the old no-op boundary, and replaces the pending exit book with
  one full-quantity bracket exit per unique entry id.
- `strategy_pyramiding_exit_omitted_loss_profit_bracket_from_entries.pine`
  covers two open long entries with different ids and one omitted-`from_entry`
  loss+profit bracket that closes `L1` on `L1`'s entry-price-derived stop and
  `L2` on `L2`'s later entry-price-derived target.

Future slices:

- omitted-`from_entry` all-entry `stop+profit`, `loss+limit`, `stop+limit`, and
  trailing behavior;
- omitted-`from_entry` relative future-entry persistence;
- duplicate same-id omitted-`from_entry` relative targets;
- price-based same-tick pyramiding-limit exceptions;
- host parity coverage for broader public JSON contracts.

### Slice 24: Omitted `from_entry` Current All-Entry Stop+Profit Bracket

Status: closed on 2026-06-06. This slice adds the omitted-`from_entry`
`stop+profit` bracket all-entry subset for currently open pyramided long entries
whose entry ids are unique. It covers full-quantity `stop+profit` brackets and
does not claim `loss+limit`, `stop+limit`, duplicate same-id per-trade relative
targets, future-entry persistence for relative exits, trailing exits, shorts,
reversals, `close_entries_rule`, or public pending-order schema.

Goal:

- generate entry-specific pending bracket exits for an omitted-`from_entry`
  `strategy.exit(..., stop=price, profit=ticks)` call, preserving the shared
  absolute stop and using each entry's own entry-price-derived profit target.

Closed evidence:

- Broker placement for omitted-`from_entry` stop+profit brackets now reads
  current open ledger entries, rejects the unsupported duplicate-entry-id case
  by preserving the old no-op boundary, and replaces the pending exit book with
  one full-quantity bracket exit per unique entry id.
- `strategy_pyramiding_exit_omitted_stop_profit_bracket_from_entries.pine`
  covers two open long entries with different ids and one omitted-`from_entry`
  stop+profit bracket that closes `L2` on `L2`'s entry-price-derived target and
  later closes `L1` on the shared absolute stop.

Future slices:

- omitted-`from_entry` all-entry `loss+limit`, `stop+limit`, and trailing
  behavior;
- omitted-`from_entry` relative future-entry persistence;
- duplicate same-id omitted-`from_entry` relative targets;
- price-based same-tick pyramiding-limit exceptions;
- host parity coverage for broader public JSON contracts.

### Slice 25: Omitted `from_entry` Current All-Entry Loss+Limit Bracket

Status: closed on 2026-06-06. This slice adds the omitted-`from_entry`
`loss+limit` bracket all-entry subset for currently open pyramided long entries
whose entry ids are unique. It covers full-quantity `loss+limit` brackets and
does not claim `stop+limit`, duplicate same-id per-trade relative targets,
future-entry persistence for relative exits, trailing exits, shorts, reversals,
`close_entries_rule`, or public pending-order schema.

Goal:

- generate entry-specific pending bracket exits for an omitted-`from_entry`
  `strategy.exit(..., loss=ticks, limit=price)` call, using each entry's own
  entry-price-derived loss stop and preserving the shared absolute limit.

Closed evidence:

- Broker placement for omitted-`from_entry` loss+limit brackets now reads
  current open ledger entries, rejects the unsupported duplicate-entry-id case
  by preserving the old no-op boundary, and replaces the pending exit book with
  one full-quantity bracket exit per unique entry id.
- `strategy_pyramiding_exit_omitted_loss_limit_bracket_from_entries.pine`
  covers two open long entries with different ids and one omitted-`from_entry`
  loss+limit bracket that closes `L1` on `L1`'s entry-price-derived stop and
  later closes `L2` on the shared absolute limit.

Future slices:

- omitted-`from_entry` all-entry `stop+limit` and trailing behavior;
- omitted-`from_entry` relative future-entry persistence;
- duplicate same-id omitted-`from_entry` relative targets;
- price-based same-tick pyramiding-limit exceptions;
- host parity coverage for broader public JSON contracts.

### Slice 26: Omitted `from_entry` Current All-Entry Stop+Limit Bracket

Status: closed on 2026-06-06. This slice closes the current-open-entry omitted-
`from_entry` bracket family by adding the full-quantity `stop+limit` absolute
bracket subset. It does not claim trailing exits, relative future-entry
persistence, duplicate same-id per-trade relative targets, shorts, reversals,
`close_entries_rule`, or public pending-order schema.

Goal:

- allow omitted-`from_entry` `strategy.exit(..., stop=price, limit=price)` calls
  to use the existing all-entry FIFO allocation path instead of being blocked by
  the omitted-`from_entry` guard.

Closed evidence:

- The builtin omitted-`from_entry` guard now admits full `stop+limit` brackets,
  which then place one all-entry pending bracket and allocate fills through
  ledger FIFO.
- `strategy_pyramiding_exit_omitted_stop_limit_bracket_from_entries.pine` covers
  two open long entries with different ids and one omitted-`from_entry`
  stop+limit bracket that closes both entries through the shared absolute limit.

Future slices:

- omitted-`from_entry` all-entry trailing behavior;
- omitted-`from_entry` relative future-entry persistence;
- duplicate same-id omitted-`from_entry` relative targets;
- price-based same-tick pyramiding-limit exceptions;
- host parity coverage for broader public JSON contracts.

### Slice 27: Omitted `from_entry` Current All-Entry Trail Price

Status: closed on 2026-06-06. This slice adds the full-quantity omitted-
`from_entry` `trail_price+trail_offset` trailing subset for currently open
pyramided long entries. It covers absolute trailing activation only and does not
claim `trail_points`, relative future-entry persistence, duplicate same-id
per-trade relative targets, shorts, reversals, `close_entries_rule`, or public
pending-order schema.

Goal:

- allow omitted-`from_entry`
  `strategy.exit(..., trail_price=price, trail_offset=ticks)` calls to use the
  existing all-entry trailing pending-exit path instead of being blocked by the
  omitted-`from_entry` guard.

Closed evidence:

- The builtin omitted-`from_entry` guard now admits full `trail_price+trail_offset`
  trailing exits, which then place one all-entry trailing pending exit and
  allocate fills through ledger FIFO after activation and stop touch.
- `strategy_pyramiding_exit_omitted_trail_price_from_entries.pine` covers two
  open long entries with different ids and one omitted-`from_entry` trailing
  exit that closes both entries through the shared active trailing stop.

Future slices:

- omitted-`from_entry` all-entry `trail_points` behavior;
- omitted-`from_entry` relative future-entry persistence;
- duplicate same-id omitted-`from_entry` relative targets;
- price-based same-tick pyramiding-limit exceptions;
- host parity coverage for broader public JSON contracts.

### Slice 28: Omitted `from_entry` Current All-Entry Trail Points

Status: closed on 2026-06-06. This slice adds the full-quantity omitted-
`from_entry` `trail_points+trail_offset` trailing subset for currently open
pyramided long entries whose entry ids are unique. It covers current open entries
only and does not claim relative future-entry persistence, duplicate same-id
per-trade relative targets, shorts, reversals, `close_entries_rule`, or public
pending-order schema.

Goal:

- expand omitted-`from_entry`
  `strategy.exit(..., trail_points=ticks, trail_offset=ticks)` calls into
  entry-specific trailing pending exits using each current open entry's own entry
  price for activation.

Closed evidence:

- Broker placement for omitted-`from_entry` trail-points trailing exits now reads
  current open ledger entries, rejects the unsupported duplicate-entry-id case
  by preserving the old no-op boundary, and replaces the pending exit book with
  one full-quantity trailing exit per unique entry id.
- `strategy_pyramiding_exit_omitted_trail_points_from_entries.pine` covers two
  open long entries with different ids and one omitted-`from_entry`
  trail-points trailing exit that closes both entries through their active
  trailing stops.

Future slices:

- omitted-`from_entry` loss, bracket, and trailing relative future-entry
  persistence;
- duplicate same-id omitted-`from_entry` relative targets;
- price-based same-tick pyramiding-limit exceptions;
- host parity coverage for broader public JSON contracts.

### Slice 29: Omitted `from_entry` Profit Future-Entry Persistence

Status: closed on 2026-06-06. This slice extends the full-quantity omitted-
`from_entry` profit-tick all-entry subset so it also covers later pyramided long
entries with unique entry ids until the position closes. It does not claim loss,
bracket, or trailing relative future-entry persistence, duplicate same-id
per-trade relative targets, shorts, reversals, `close_entries_rule`, or public
pending-order schema.

Goal:

- keep a supported omitted-`from_entry` `strategy.exit(..., profit=ticks)` call
  active for later long entries and derive each later entry's limit from that
  entry's own fill price.

Closed evidence:

- Broker placement for omitted-`from_entry` profit ticks now stores an internal
  all-entry deferred relative template alongside the current open-entry pending
  exits.
- Pending entry fill paths resolve that template for the newly filled entry id
  only when the id is unique among currently open trades, preserving the
  unsupported duplicate same-id relative-target boundary.
- `strategy_pyramiding_exit_omitted_profit_persistent_from_entries.pine` covers
  an exit call placed after `L1` opens and before `L2` opens; `L1` closes at
  `L1`'s entry-price-derived profit target and the later `L2` closes at `L2`'s
  own entry-price-derived profit target.

Future slices:

- omitted-`from_entry` bracket and trailing relative future-entry persistence;
- duplicate same-id omitted-`from_entry` relative targets;
- price-based same-tick pyramiding-limit exceptions;
- host parity coverage for broader public JSON contracts.

### Slice 30: Omitted `from_entry` Loss Future-Entry Persistence

Status: closed on 2026-06-06. This slice extends the full-quantity omitted-
`from_entry` loss-tick all-entry subset so it also covers later pyramided long
entries with unique entry ids until the position closes. It does not claim
bracket or trailing relative future-entry persistence, duplicate same-id
per-trade relative targets, shorts, reversals, `close_entries_rule`, or public
pending-order schema.

Goal:

- keep a supported omitted-`from_entry` `strategy.exit(..., loss=ticks)` call
  active for later long entries and derive each later entry's stop from that
  entry's own fill price.

Closed evidence:

- Broker placement for omitted-`from_entry` loss ticks now stores an internal
  all-entry deferred relative template alongside the current open-entry pending
  exits, replacing any prior omitted all-entry relative template.
- Pending entry fill paths resolve that template for the newly filled entry id
  only when the id is unique among currently open trades, preserving the
  unsupported duplicate same-id relative-target boundary.
- `strategy_pyramiding_exit_omitted_loss_persistent_from_entries.pine` covers an
  exit call placed after `L1` opens and before `L2` opens; `L1` closes at `L1`'s
  entry-price-derived loss stop and the later `L2` closes at `L2`'s own
  entry-price-derived loss stop.

Future slices:

- omitted-`from_entry` `stop+profit`, `loss+limit`, `stop+limit`, and trailing
  relative future-entry persistence;
- duplicate same-id omitted-`from_entry` relative targets;
- price-based same-tick pyramiding-limit exceptions;
- host parity coverage for broader public JSON contracts.

### Slice 31: Omitted `from_entry` Loss+Profit Bracket Future-Entry Persistence

Status: closed on 2026-06-06. This slice extends the full-quantity omitted-
`from_entry` `loss+profit` bracket all-entry subset so it also covers later
pyramided long entries with unique entry ids until the position closes. It does
not claim `stop+profit`, `loss+limit`, `stop+limit`, trailing relative
future-entry persistence, duplicate same-id per-trade relative targets, shorts,
reversals, `close_entries_rule`, or public pending-order schema.

Goal:

- keep a supported omitted-`from_entry`
  `strategy.exit(..., loss=ticks, profit=ticks)` call active for later long
  entries and derive each later entry's bracket legs from that entry's own fill
  price.

Closed evidence:

- Broker placement for omitted-`from_entry` loss+profit brackets now stores an
  internal all-entry deferred relative bracket template alongside the current
  open-entry pending brackets, replacing any prior omitted all-entry relative
  template.
- Pending entry fill paths resolve that template for the newly filled entry id
  only when the id is unique among currently open trades, preserving the
  unsupported duplicate same-id relative-target boundary.
- `strategy_pyramiding_exit_omitted_loss_profit_bracket_persistent_from_entries.pine`
  covers an exit call placed after `L1` opens and before `L2` opens; `L1`
  closes through its entry-price-derived loss leg and the later `L2` closes
  through its own entry-price-derived profit leg.

Future slices:

- omitted-`from_entry` `loss+limit`, `stop+limit`, and trailing relative
  future-entry persistence;
- duplicate same-id omitted-`from_entry` relative targets;
- price-based same-tick pyramiding-limit exceptions;
- host parity coverage for broader public JSON contracts.

### Slice 32: Omitted `from_entry` Stop+Profit Bracket Future-Entry Persistence

Status: closed on 2026-06-06. This slice extends the full-quantity omitted-
`from_entry` `stop+profit` bracket all-entry subset so it also covers later
pyramided long entries with unique entry ids until the position closes. It does
not claim `loss+limit`, `stop+limit`, trailing relative future-entry
persistence, duplicate same-id per-trade relative targets, shorts, reversals,
`close_entries_rule`, or public pending-order schema.

Goal:

- keep a supported omitted-`from_entry`
  `strategy.exit(..., stop=price, profit=ticks)` call active for later long
  entries with the shared absolute stop and each later entry's own
  entry-price-derived profit target.

Closed evidence:

- Broker placement for omitted-`from_entry` stop+profit brackets now stores an
  internal all-entry deferred relative bracket template alongside the current
  open-entry pending brackets, replacing any prior omitted all-entry relative
  template.
- Pending entry fill paths resolve that template for the newly filled entry id
  only when the id is unique among currently open trades, preserving the
  unsupported duplicate same-id relative-target boundary.
- `strategy_pyramiding_exit_omitted_stop_profit_bracket_persistent_from_entries.pine`
  covers an exit call placed after `L1` opens and before `L2` opens; the later
  `L2` closes through its own entry-price-derived profit leg and `L1` later
  closes through the shared absolute stop.

Future slices:

- omitted-`from_entry` `stop+limit` and trailing relative future-entry
  persistence;
- duplicate same-id omitted-`from_entry` relative targets;
- price-based same-tick pyramiding-limit exceptions;
- host parity coverage for broader public JSON contracts.

### Slice 33: Omitted `from_entry` Loss+Limit Bracket Future-Entry Persistence

Status: closed on 2026-06-06. This slice extends the full-quantity omitted-
`from_entry` `loss+limit` bracket all-entry subset so it also covers later
pyramided long entries with unique entry ids until the position closes. It does
not claim `stop+limit`, trailing relative future-entry persistence, duplicate
same-id per-trade relative targets, shorts, reversals, `close_entries_rule`, or
public pending-order schema.

Goal:

- keep a supported omitted-`from_entry`
  `strategy.exit(..., loss=ticks, limit=price)` call active for later long
  entries with each later entry's own entry-price-derived loss stop and the
  shared absolute limit.

Closed evidence:

- Broker placement for omitted-`from_entry` loss+limit brackets now stores an
  internal all-entry deferred relative bracket template alongside the current
  open-entry pending brackets, replacing any prior omitted all-entry relative
  template.
- Pending entry fill paths resolve that template for the newly filled entry id
  only when the id is unique among currently open trades, preserving the
  unsupported duplicate same-id relative-target boundary.
- `strategy_pyramiding_exit_omitted_loss_limit_bracket_persistent_from_entries.pine`
  covers an exit call placed after `L1` opens and before `L2` opens; `L1`
  closes through its own entry-price-derived loss leg and the later `L2` closes
  through the shared absolute limit.

Future slices:

- omitted-`from_entry` trailing relative future-entry persistence;
- duplicate same-id omitted-`from_entry` relative targets;
- price-based same-tick pyramiding-limit exceptions;
- host parity coverage for broader public JSON contracts.

### Slice 34: Omitted `from_entry` Stop+Limit Bracket Future-Entry Persistence

Status: closed on 2026-06-06. This slice extends the full-quantity omitted-
`from_entry` `stop+limit` absolute bracket all-entry subset so it also covers
later pyramided long entries until the position closes. It does not claim
trailing relative future-entry persistence, duplicate same-id per-trade
relative targets, shorts, reversals, `close_entries_rule`, or public
pending-order schema.

Goal:

- keep a supported omitted-`from_entry`
  `strategy.exit(..., stop=price, limit=price)` call active for later long
  entries with the shared absolute stop and limit prices.

Closed evidence:

- Broker maintenance now treats an omitted full-position absolute bracket like
  the existing omitted full-position absolute stop/limit exits when a later
  pyramided long entry opens, expanding its reserved quantity to the refreshed
  aggregate long position.
- The implementation stays on the existing aggregate all-entry absolute exit
  path, so it does not widen relative per-entry target behavior or duplicate
  same-id relative target support.
- `strategy_pyramiding_exit_omitted_stop_limit_bracket_persistent_from_entries.pine`
  covers an exit call placed after `L1` opens and before `L2` opens; the later
  `L2` is included in the same shared absolute bracket when the limit leg
  triggers.

Future slices:

- omitted-`from_entry` `trail_price+trail_offset` absolute trailing
  future-entry persistence;
- omitted-`from_entry` `trail_points+trail_offset` relative trailing
  future-entry persistence;
- duplicate same-id omitted-`from_entry` relative targets;
- price-based same-tick pyramiding-limit exceptions;
- host parity coverage for broader public JSON contracts.

### Slice 35: Omitted `from_entry` Trail-Price Future-Entry Persistence

Status: closed on 2026-06-06. This slice extends the full-quantity omitted-
`from_entry` `trail_price+trail_offset` all-entry subset so it also covers later
pyramided long entries until the position closes. It does not claim
`trail_points+trail_offset` relative future-entry persistence, duplicate same-id
per-trade relative targets, shorts, reversals, `close_entries_rule`, or public
pending-order schema.

Goal:

- keep a supported omitted-`from_entry`
  `strategy.exit(..., trail_price=price, trail_offset=ticks)` call active for
  later long entries with the shared absolute activation price and trailing
  offset.

Closed evidence:

- Broker maintenance now treats an omitted full-position trailing pending exit
  like the existing omitted full-position stop/limit/bracket exits when a later
  pyramided long entry opens, expanding its reserved quantity to the refreshed
  aggregate long position.
- The implementation stays on the existing aggregate all-entry absolute
  trailing path, so it does not widen entry-relative `trail_points` behavior or
  duplicate same-id relative target support.
- `strategy_pyramiding_exit_omitted_trail_price_persistent_from_entries.pine`
  covers an exit call placed after `L1` opens and before `L2` opens; the later
  `L2` is included in the same shared trailing exit after activation.

Future slices:

- duplicate same-id omitted-`from_entry` relative targets;
- price-based same-tick pyramiding-limit exceptions;
- host parity coverage for broader public JSON contracts.

### Slice 36: Omitted `from_entry` Trail-Points Future-Entry Persistence

Status: closed on 2026-06-06. This slice extends the full-quantity omitted-
`from_entry` `trail_points+trail_offset` all-entry subset so it also covers later
pyramided long entries with unique entry ids until the position closes. It does
not claim duplicate same-id per-trade relative targets, shorts, reversals,
`close_entries_rule`, or public pending-order schema.

Goal:

- keep a supported omitted-`from_entry`
  `strategy.exit(..., trail_points=ticks, trail_offset=ticks)` call active for
  later long entries, deriving each later entry's activation price from that
  entry's own fill price.

Closed evidence:

- Broker placement for omitted-`from_entry` `trail_points+trail_offset` now
  keeps the all-entry deferred relative template after expanding current open
  unique entry ids.
- Deferred all-entry resolution now handles `TrailPoints`, generating a
  per-entry pending trailing exit for each later unique long entry using that
  entry's own entry-price-derived activation and the shared trailing offset.
- `strategy_pyramiding_exit_omitted_trail_points_persistent_from_entries.pine`
  covers an exit call placed after `L1` opens and before `L2` opens; the later
  `L2` is included in the same omitted exit family with its own trailing
  activation.

Future slices:

- duplicate same-id omitted-`from_entry` relative targets;
- price-based same-tick pyramiding-limit exceptions;
- host parity coverage for broader public JSON contracts.

### Slice 37: Omitted Trail-Points Persistence WASM Host Parity

Status: closed on 2026-06-06. This slice adds WASM public JSON coverage for
Slice 36's omitted-`from_entry` `trail_points+trail_offset` future-entry
persistence fixture. It does not expand runtime semantics or public schema
shape.

Goal:

- prove that the WASM `runScriptCsv` host path exposes the same public orders,
  trades, position snapshots, plots, diagnostics, and hidden-internal-field
  boundary for the omitted trail-points persistent multi-entry fixture already
  covered by CLI/runtime snapshots.

Closed evidence:

- `runs_strategy_omitted_trail_points_persistent_fixture_from_csv_to_public_strategy_json`
  runs
  `strategy_pyramiding_exit_omitted_trail_points_persistent_from_entries.pine`
  with its dedicated bars CSV through the WASM CSV API.
- The test asserts the public schema version, two `XT` exit events, two closed
  trades, aggregate position snapshots including final flat state, strategy
  diagnostics, and absence of internal pending/reservation/trailing fields.

Future slices:

- duplicate same-id omitted-`from_entry` relative targets;
- price-based same-tick pyramiding-limit exceptions;
- broader Python/WASM host parity coverage for future public JSON contracts.

### Slice 38: Omitted Trail-Points Persistence Python Host Parity

Status: closed on 2026-06-06. This slice adds Python binding public JSON
coverage for Slice 36's omitted-`from_entry` `trail_points+trail_offset`
future-entry persistence fixture. It does not expand runtime semantics or public
schema shape.

Goal:

- prove that the Python `run_script` host path exposes the same public orders,
  trades, position snapshots, plots, diagnostics, and hidden-internal-field
  boundary for the omitted trail-points persistent multi-entry fixture already
  covered by CLI/runtime snapshots and WASM.

Closed evidence:

- `test_run_script_returns_omitted_trail_points_persistent_fixture_contract`
  runs
  `strategy_pyramiding_exit_omitted_trail_points_persistent_from_entries.pine`
  with its dedicated bars CSV through the Python binding.
- The test asserts the public schema version, two `XT` exit events, two closed
  trades, aggregate position snapshots including final flat state, plot values,
  strategy diagnostics, and absence of internal pending/reservation/trailing
  fields.

Future slices:

- duplicate same-id omitted-`from_entry` relative targets;
- price-based same-tick pyramiding-limit exceptions;
- broader host parity coverage for future public JSON contracts.

### Slice 39: Omitted Trail-Price Persistence WASM Host Parity

Status: closed on 2026-06-06. This slice adds WASM public JSON coverage for
Slice 35's omitted-`from_entry` `trail_price+trail_offset` future-entry
persistence fixture. It does not expand runtime semantics or public schema
shape.

Goal:

- prove that the WASM `runScriptCsv` host path exposes the same public orders,
  trades, position snapshots, plots, diagnostics, and hidden-internal-field
  boundary for the omitted trail-price persistent multi-entry fixture already
  covered by CLI/runtime snapshots.

Closed evidence:

- `runs_strategy_omitted_trail_price_persistent_fixture_from_csv_to_public_strategy_json`
  runs
  `strategy_pyramiding_exit_omitted_trail_price_persistent_from_entries.pine`
  with its dedicated bars CSV through the WASM CSV API.
- The test asserts the public schema version, two `XT` exit events at the shared
  absolute trailing price, two closed trades, final flat position state,
  strategy diagnostics, and absence of internal pending/reservation/trailing
  fields.

Future slices:

- duplicate same-id omitted-`from_entry` relative targets;
- price-based same-tick pyramiding-limit exceptions;
- broader host parity coverage for future public JSON contracts.

### Slice 40: Omitted Trail-Price Persistence Python Host Parity

Status: closed on 2026-06-06. This slice adds Python binding public JSON
coverage for Slice 35's omitted-`from_entry` `trail_price+trail_offset`
future-entry persistence fixture. It does not expand runtime semantics or public
schema shape.

Goal:

- prove that the Python `run_script` host path exposes the same public orders,
  trades, position snapshots, plots, diagnostics, and hidden-internal-field
  boundary for the omitted trail-price persistent multi-entry fixture already
  covered by CLI/runtime snapshots and WASM.

Closed evidence:

- `test_run_script_returns_omitted_trail_price_persistent_fixture_contract`
  runs
  `strategy_pyramiding_exit_omitted_trail_price_persistent_from_entries.pine`
  with its dedicated bars CSV through the Python binding.
- The test asserts the public schema version, two `XT` exit events at the shared
  absolute trailing price, two closed trades, final flat position state, plot
  values, strategy diagnostics, and absence of internal
  pending/reservation/trailing fields.

Future slices:

- duplicate same-id omitted-`from_entry` relative targets;
- price-based same-tick pyramiding-limit exceptions;
- broader host parity coverage for future public JSON contracts.

### Slice 41: Omitted Profit Persistence WASM Host Parity

Status: closed on 2026-06-06. This slice adds WASM public JSON coverage for
Slice 29's omitted-`from_entry` profit-tick future-entry persistence fixture. It
does not expand runtime semantics or public schema shape.

Goal:

- prove that the WASM `runScriptCsv` host path exposes the same public orders,
  trades, position snapshots, plots, diagnostics, and hidden-internal-field
  boundary for the omitted profit persistent multi-entry fixture already covered
  by CLI/runtime snapshots.

Closed evidence:

- `runs_strategy_omitted_profit_persistent_fixture_from_csv_to_public_strategy_json`
  runs `strategy_pyramiding_exit_omitted_profit_persistent_from_entries.pine`
  with its dedicated bars CSV through the WASM CSV API.
- The test asserts the public schema version, two `XP` exit events using each
  entry's own profit target, two closed trades, aggregate position snapshots,
  strategy diagnostics, and absence of internal pending/reservation/target
  fields.

Future slices:

- duplicate same-id omitted-`from_entry` relative targets;
- price-based same-tick pyramiding-limit exceptions;
- broader host parity coverage for future public JSON contracts.

### Slice 42: Omitted Profit Persistence Python Host Parity

Status: closed on 2026-06-06. This slice adds Python binding public JSON
coverage for Slice 29's omitted-`from_entry` profit-tick future-entry
persistence fixture. It does not expand runtime semantics or public schema
shape.

Goal:

- prove that the Python `run_script` host path exposes the same public orders,
  trades, position snapshots, plots, diagnostics, and hidden-internal-field
  boundary for the omitted profit persistent multi-entry fixture already covered
  by CLI/runtime snapshots and WASM.

Closed evidence:

- `test_run_script_returns_omitted_profit_persistent_fixture_contract` runs
  `strategy_pyramiding_exit_omitted_profit_persistent_from_entries.pine` with
  its dedicated bars CSV through the Python binding.
- The test asserts the public schema version, two `XP` exit events using each
  entry's own profit target, two closed trades, aggregate position snapshots,
  plot values, strategy diagnostics, and absence of internal
  pending/reservation/target fields.

Future slices:

- duplicate same-id omitted-`from_entry` relative targets;
- price-based same-tick pyramiding-limit exceptions;
- broader host parity coverage for future public JSON contracts.

### Slice 43: Omitted Loss Persistence WASM Host Parity

Status: closed on 2026-06-06. This slice adds WASM public JSON coverage for
Slice 30's omitted-`from_entry` loss-tick future-entry persistence fixture. It
does not expand runtime semantics or public schema shape.

Goal:

- prove that the WASM `run_script_csv` host path exposes the same public orders,
  trades, position snapshots, plots, diagnostics, and hidden-internal-field
  boundary for the omitted loss persistent multi-entry fixture already covered
  by CLI/runtime snapshots.

Closed evidence:

- `runs_strategy_omitted_loss_persistent_fixture_from_csv_to_public_strategy_json`
  runs `strategy_pyramiding_exit_omitted_loss_persistent_from_entries.pine`
  with its dedicated bars CSV through the WASM CSV host path.
- The test asserts the public schema version, two `XL` exit events using each
  entry's own loss target, two closed trades, aggregate position snapshots, plot
  values, strategy diagnostics, and absence of internal pending/reservation/stop
  fields.

Future slices:

- duplicate same-id omitted-`from_entry` relative targets;
- price-based same-tick pyramiding-limit exceptions;
- broader host parity coverage for future public JSON contracts.

### Slice 44: Omitted Loss Persistence Python Host Parity

Status: closed on 2026-06-06. This slice adds Python binding public JSON
coverage for Slice 30's omitted-`from_entry` loss-tick future-entry persistence
fixture. It does not expand runtime semantics or public schema shape.

Goal:

- prove that the Python `run_script` host path exposes the same public orders,
  trades, position snapshots, plots, diagnostics, and hidden-internal-field
  boundary for the omitted loss persistent multi-entry fixture already covered
  by CLI/runtime snapshots and WASM.

Closed evidence:

- `test_run_script_returns_omitted_loss_persistent_fixture_contract` runs
  `strategy_pyramiding_exit_omitted_loss_persistent_from_entries.pine` with its
  dedicated bars CSV through the Python binding.
- The test asserts the public schema version, two `XL` exit events using each
  entry's own loss target, two closed trades, aggregate position snapshots, plot
  values, strategy diagnostics, and absence of internal pending/reservation/stop
  fields.

Future slices:

- duplicate same-id omitted-`from_entry` relative targets;
- price-based same-tick pyramiding-limit exceptions;
- broader host parity coverage for future public JSON contracts.

### Slice 45: Omitted Loss+Profit Bracket Persistence WASM Host Parity

Status: closed on 2026-06-06. This slice adds WASM public JSON coverage for
Slice 31's omitted-`from_entry` `loss+profit` bracket future-entry persistence
fixture. It does not expand runtime semantics or public schema shape.

Goal:

- prove that the WASM `run_script_csv` host path exposes the same public orders,
  trades, position snapshots, plots, diagnostics, and hidden-internal-field
  boundary for the omitted `loss+profit` bracket persistent multi-entry fixture
  already covered by CLI/runtime snapshots.

Closed evidence:

- `runs_strategy_omitted_loss_profit_bracket_persistent_fixture_from_csv_to_public_strategy_json`
  runs
  `strategy_pyramiding_exit_omitted_loss_profit_bracket_persistent_from_entries.pine`
  with its dedicated bars CSV through the WASM CSV host path.
- The test asserts the public schema version, two `XB` exit events using each
  entry's own bracket target, two closed trades, aggregate position snapshots,
  plot values, strategy diagnostics, and absence of internal
  pending/reservation/target/stop fields.

Future slices:

- duplicate same-id omitted-`from_entry` relative targets;
- price-based same-tick pyramiding-limit exceptions;
- broader host parity coverage for future public JSON contracts.

### Slice 46: Omitted Loss+Profit Bracket Persistence Python Host Parity

Status: closed on 2026-06-06. This slice adds Python binding public JSON
coverage for Slice 31's omitted-`from_entry` `loss+profit` bracket future-entry
persistence fixture. It does not expand runtime semantics or public schema
shape.

Goal:

- prove that the Python `run_script` host path exposes the same public orders,
  trades, position snapshots, plots, diagnostics, and hidden-internal-field
  boundary for the omitted `loss+profit` bracket persistent multi-entry fixture
  already covered by CLI/runtime snapshots and WASM.

Closed evidence:

- `test_run_script_returns_omitted_loss_profit_bracket_persistent_fixture_contract`
  runs
  `strategy_pyramiding_exit_omitted_loss_profit_bracket_persistent_from_entries.pine`
  with its dedicated bars CSV through the Python binding.
- The test asserts the public schema version, two `XB` exit events using each
  entry's own bracket target, two closed trades, aggregate position snapshots,
  plot values, strategy diagnostics, and absence of internal
  pending/reservation/target/stop fields.

Future slices:

- duplicate same-id omitted-`from_entry` relative targets;
- price-based same-tick pyramiding-limit exceptions;
- broader host parity coverage for future public JSON contracts.

### Slice 47: Omitted Stop+Profit Bracket Persistence WASM Host Parity

Status: closed on 2026-06-06. This slice adds WASM public JSON coverage for
Slice 32's omitted-`from_entry` `stop+profit` bracket future-entry persistence
fixture. It does not expand runtime semantics or public schema shape.

Goal:

- prove that the WASM `run_script_csv` host path exposes the same public orders,
  trades, position snapshots, plots, diagnostics, and hidden-internal-field
  boundary for the omitted `stop+profit` bracket persistent multi-entry fixture
  already covered by CLI/runtime snapshots.

Closed evidence:

- `runs_strategy_omitted_stop_profit_bracket_persistent_fixture_from_csv_to_public_strategy_json`
  runs
  `strategy_pyramiding_exit_omitted_stop_profit_bracket_persistent_from_entries.pine`
  with its dedicated bars CSV through the WASM CSV host path.
- The test asserts the public schema version, the profit-side `XB` exit for the
  second entry before the stop-side `XB` exit for the first entry, two closed
  trades, aggregate position snapshots, plot values, strategy diagnostics, and
  absence of internal pending/reservation/target/stop fields.

Future slices:

- duplicate same-id omitted-`from_entry` relative targets;
- price-based same-tick pyramiding-limit exceptions;
- broader host parity coverage for future public JSON contracts.

### Slice 48: Omitted Stop+Profit Bracket Persistence Python Host Parity

Status: closed on 2026-06-06. This slice adds Python binding public JSON
coverage for Slice 32's omitted-`from_entry` `stop+profit` bracket future-entry
persistence fixture. It does not expand runtime semantics or public schema
shape.

Goal:

- prove that the Python `run_script` host path exposes the same public orders,
  trades, position snapshots, plots, diagnostics, and hidden-internal-field
  boundary for the omitted `stop+profit` bracket persistent multi-entry fixture
  already covered by CLI/runtime snapshots and WASM.

Closed evidence:

- `test_run_script_returns_omitted_stop_profit_bracket_persistent_fixture_contract`
  runs
  `strategy_pyramiding_exit_omitted_stop_profit_bracket_persistent_from_entries.pine`
  with its dedicated bars CSV through the Python binding.
- The test asserts the public schema version, the profit-side `XB` exit for the
  second entry before the stop-side `XB` exit for the first entry, two closed
  trades, aggregate position snapshots, plot values, strategy diagnostics, and
  absence of internal pending/reservation/target/stop fields.

Future slices:

- duplicate same-id omitted-`from_entry` relative targets;
- price-based same-tick pyramiding-limit exceptions;
- broader host parity coverage for future public JSON contracts.

### Slice 49: Omitted Loss+Limit Bracket Persistence WASM Host Parity

Status: closed on 2026-06-06. This slice adds WASM public JSON coverage for
Slice 33's omitted-`from_entry` `loss+limit` bracket future-entry persistence
fixture. It does not expand runtime semantics or public schema shape.

Goal:

- prove that the WASM `run_script_csv` host path exposes the same public orders,
  trades, position snapshots, plots, diagnostics, and hidden-internal-field
  boundary for the omitted `loss+limit` bracket persistent multi-entry fixture
  already covered by CLI/runtime snapshots.

Closed evidence:

- `runs_strategy_omitted_loss_limit_bracket_persistent_fixture_from_csv_to_public_strategy_json`
  runs
  `strategy_pyramiding_exit_omitted_loss_limit_bracket_persistent_from_entries.pine`
  with its dedicated bars CSV through the WASM CSV host path.
- The test asserts the public schema version, the loss-side `XB` exit for the
  first entry before the limit-side `XB` exit for the second entry, two closed
  trades, aggregate position snapshots, plot values, strategy diagnostics, and
  absence of internal pending/reservation/target/stop fields.

Future slices:

- duplicate same-id omitted-`from_entry` relative targets;
- price-based same-tick pyramiding-limit exceptions;
- broader host parity coverage for future public JSON contracts.

### Slice 50: Omitted Loss+Limit Bracket Persistence Python Host Parity

Status: closed on 2026-06-06. This slice adds Python binding public JSON
coverage for Slice 33's omitted-`from_entry` `loss+limit` bracket future-entry
persistence fixture. It does not expand runtime semantics or public schema
shape.

Goal:

- prove that the Python `run_script` host path exposes the same public orders,
  trades, position snapshots, plots, diagnostics, and hidden-internal-field
  boundary for the omitted `loss+limit` bracket persistent multi-entry fixture
  already covered by CLI/runtime snapshots and WASM.

Closed evidence:

- `test_run_script_returns_omitted_loss_limit_bracket_persistent_fixture_contract`
  runs
  `strategy_pyramiding_exit_omitted_loss_limit_bracket_persistent_from_entries.pine`
  with its dedicated bars CSV through the Python binding.
- The test asserts the public schema version, the loss-side `XB` exit for the
  first entry before the limit-side `XB` exit for the second entry, two closed
  trades, aggregate position snapshots, plot values, strategy diagnostics, and
  absence of internal pending/reservation/target/stop fields.

Future slices:

- duplicate same-id omitted-`from_entry` relative targets;
- price-based same-tick pyramiding-limit exceptions;
- broader host parity coverage for future public JSON contracts.

### Slice 51: Omitted Stop+Limit Bracket Persistence WASM Host Parity

Status: closed on 2026-06-06. This slice adds WASM public JSON coverage for
Slice 34's omitted-`from_entry` `stop+limit` bracket future-entry persistence
fixture. It does not expand runtime semantics or public schema shape.

Goal:

- prove that the WASM `run_script_csv` host path exposes the same public orders,
  trades, position snapshots, plots, diagnostics, and hidden-internal-field
  boundary for the omitted `stop+limit` bracket persistent multi-entry fixture
  already covered by CLI/runtime snapshots.

Closed evidence:

- `runs_strategy_omitted_stop_limit_bracket_persistent_fixture_from_csv_to_public_strategy_json`
  runs
  `strategy_pyramiding_exit_omitted_stop_limit_bracket_persistent_from_entries.pine`
  with its dedicated bars CSV through the WASM CSV host path.
- The test asserts the public schema version, two same-bar `XB` exits at the
  absolute limit price, two closed trades, aggregate position snapshots, plot
  values, strategy diagnostics, and absence of internal
  pending/reservation/target/stop fields.

Future slices:

- duplicate same-id omitted-`from_entry` relative targets;
- price-based same-tick pyramiding-limit exceptions;
- broader host parity coverage for future public JSON contracts.

### Slice 52: Omitted Stop+Limit Bracket Persistence Python Host Parity

Status: closed on 2026-06-06. This slice adds Python binding public JSON
coverage for Slice 34's omitted-`from_entry` `stop+limit` bracket future-entry
persistence fixture. It does not expand runtime semantics or public schema
shape.

Goal:

- prove that the Python `run_script` host path exposes the same public orders,
  trades, position snapshots, plots, diagnostics, and hidden-internal-field
  boundary for the omitted `stop+limit` bracket persistent multi-entry fixture
  already covered by CLI/runtime snapshots and the WASM host path.

Closed evidence:

- `test_run_script_returns_omitted_stop_limit_bracket_persistent_fixture_contract`
  runs
  `strategy_pyramiding_exit_omitted_stop_limit_bracket_persistent_from_entries.pine`
  with its dedicated bars CSV through the Python binding.
- The test asserts the public schema version, two same-bar `XB` exits at the
  absolute limit price, two closed trades, aggregate position snapshots, plot
  values, strategy diagnostics, and absence of internal
  pending/reservation/target/stop fields.

Future slices:

- Python public JSON parity coverage for the Slice 19 omitted current
  all-entry absolute exit fixture;
- duplicate same-id omitted-`from_entry` relative targets;
- price-based same-tick pyramiding-limit exceptions;
- broader host parity coverage for future public JSON contracts.

### Slice 53: Omitted Current All-Entry Absolute Exit WASM Host Parity

Status: closed on 2026-06-06. This slice adds WASM public JSON coverage for
Slice 19's omitted-`from_entry` current all-entry absolute exit fixture. It
does not expand runtime semantics or public schema shape.

Goal:

- prove that the WASM `run_script_csv` host path exposes the same public orders,
  trades, position snapshots, plots, diagnostics, and hidden-internal-field
  boundary for the current open-entry omitted absolute limit exit fixture
  already covered by CLI/runtime snapshots.

Closed evidence:

- `runs_strategy_omitted_current_all_entry_exit_fixture_from_csv_to_public_strategy_json`
  runs `strategy_pyramiding_exit_omitted_from_entry_current.pine` with its
  dedicated bars CSV through the WASM CSV host path.
- The test asserts the public schema version, two same-bar `XL` exit fills for
  the open ledger allocations, two closed trades, aggregate position snapshots,
  plot values, strategy diagnostics, and absence of internal
  pending/reservation/quantity fields.

Future slices:

- duplicate same-id omitted-`from_entry` relative targets;
- price-based same-tick pyramiding-limit exceptions;
- broader host parity coverage for future public JSON contracts.

### Slice 54: Omitted Current All-Entry Absolute Exit Python Host Parity

Status: closed on 2026-06-06. This slice adds Python binding public JSON
coverage for Slice 19's omitted-`from_entry` current all-entry absolute exit
fixture. It does not expand runtime semantics or public schema shape.

Goal:

- prove that the Python `run_script` host path exposes the same public orders,
  trades, position snapshots, plots, diagnostics, and hidden-internal-field
  boundary for the current open-entry omitted absolute limit exit fixture
  already covered by CLI/runtime snapshots and the WASM host path.

Closed evidence:

- `test_run_script_returns_omitted_current_all_entry_exit_fixture_contract`
  runs `strategy_pyramiding_exit_omitted_from_entry_current.pine` with its
  dedicated bars CSV through the Python binding.
- The test asserts the public schema version, two same-bar `XL` exit fills for
  the open ledger allocations, two closed trades, aggregate position snapshots,
  plot values, strategy diagnostics, and absence of internal
  pending/reservation/quantity fields.

Future slices:

- resolve omitted-`from_entry` relative targets against per-open-trade keys;
- duplicate same-id omitted-`from_entry` relative targets;
- price-based same-tick pyramiding-limit exceptions;
- broader host parity coverage for future public JSON contracts.

### Slice 55: Internal Open-Trade Key Foundation

Status: closed on 2026-06-06. This slice adds a broker-owned internal key to
each open trade so future omitted-`from_entry` relative exits can identify a
specific open trade even when multiple open trades share the same entry id. It
does not change runtime behavior, public JSON, conformance claims, or the
current duplicate same-id unsupported boundary.

Goal:

- give the ledger a stable per-open-trade identity that is independent of the
  open-trade vector index and distinct from the user-visible entry id.

Closed evidence:

- `OpenTrade` now carries an internal `key`; `TradeLedger::append_long` assigns
  it from a monotonic `next_trade_key`.
- `TradeAllocation` carries the source `trade_key`, and the ledger exposes
  internal key-based lookup helpers for open quantity and entry price.
- `trade_ledger_assigns_stable_open_trade_keys` proves that same-id open trades
  receive different keys, allocations carry the key, surviving trades remain
  addressable after FIFO removal shifts vector indexes, and later entries
  receive a new key.

Future slices:

- connect pending exits to per-open-trade keys;
- resolve omitted-`from_entry` relative targets against per-open-trade keys;
- duplicate same-id omitted-`from_entry` relative targets;
- price-based same-tick pyramiding-limit exceptions;
- broader host parity coverage for future public JSON contracts.

### Slice 56: Internal Key-Scoped Exit Allocation

Status: closed on 2026-06-06. This slice adds ledger allocation by internal
open-trade key so future pending exits can close a specific open trade even when
multiple trades share the same user-visible entry id. It does not change runtime
behavior, public JSON, conformance claims, or the current duplicate same-id
unsupported boundary.

Goal:

- make the ledger capable of allocating an exit fill against exactly one
  broker-owned open-trade key instead of only FIFO matching by optional entry id.

Closed evidence:

- `TradeLedger::allocate_exit_for_key` returns at most one allocation for the
  requested key, clamps to that open trade's remaining quantity, and carries the
  same entry metadata used by existing FIFO allocations.
- `trade_ledger_allocates_specific_open_trade_key` proves that two same-id open
  trades can be addressed separately, that applying the key-scoped allocation
  reduces only the selected trade, and that aggregate position accounting stays
  consistent.

Future slices:

- resolve omitted-`from_entry` relative targets against per-open-trade keys;
- duplicate same-id omitted-`from_entry` relative targets;
- price-based same-tick pyramiding-limit exceptions;
- broader host parity coverage for future public JSON contracts.

### Slice 57: Internal Pending Exit Trade-Key Scope

Status: closed on 2026-06-06. This slice lets internal pending exits carry an
optional broker-owned open-trade key so a future expanded `strategy.exit` path
can preserve per-open-trade identity after reservation. It does not change
public JSON, conformance claims, or the current duplicate same-id unsupported
boundary.

Goal:

- connect pending exit identity and fill allocation to the internal open-trade
  key introduced by Slices 55-56, while preserving the existing FIFO path for
  unkeyed exits.

Closed evidence:

- `PendingExit` now carries optional `target_trade_key`, and
  `PendingExitBook::replace_or_append` treats the key as part of pending-exit
  identity when it is present.
- Pending exit fills route keyed exits through
  `TradeLedger::allocate_exit_for_key` and keep the prior FIFO allocation for
  unkeyed exits.
- `keyed_pending_exit_closes_only_target_same_id_trade` proves a keyed pending
  exit closes the selected same-id open trade while leaving the earlier same-id
  trade open.

Future slices:

- duplicate same-id omitted-`from_entry` relative targets;
- price-based same-tick pyramiding-limit exceptions;
- broader host parity coverage for future public JSON contracts.

### Slice 58: Keyed Omitted Relative Expansion

Status: closed on 2026-06-06. This slice binds the already-supported
unique-entry-id omitted-`from_entry` relative exit expansion to broker-owned
open-trade keys. It preserves the current duplicate same-id guardrail and does
not widen public JSON, conformance claims, or fixture-backed runtime support.

Goal:

- ensure internally generated pending exits from omitted-`from_entry` relative
  profit/loss/trailing/bracket templates carry the specific open-trade key they
  were priced and reserved against.

Closed evidence:

- Current open-trade all-entry relative expansions now set
  `PendingExit::target_trade_key` from each open trade while retaining the
  existing duplicate same-id early return.
- Deferred all-entry relative template resolution now resolves only a unique
  open trade for the entry id and stores that trade key on the generated
  pending exit.
- `omitted_current_relative_exits_record_open_trade_key_scope` proves current
  unique-entry-id all-entry relative exits carry the expected open-trade keys.
- `omitted_future_relative_exit_resolves_with_open_trade_key_scope` proves a
  flat-time deferred all-entry relative template resolves to a keyed pending
  exit after the later entry fills.

Future slices:

- duplicate same-id omitted-`from_entry` `loss+profit` bracket/trailing
  targets;
- price-based same-tick pyramiding-limit exceptions;
- broader host parity coverage for future public JSON contracts.

### Slice 75: Same-Tick Limit Entry Pyramiding Exception

Status: closed on 2026-06-06. This slice adds the first fixture-backed
price-based same-tick pyramiding-limit exception: multiple long limit entries
that are all eligible during the same historical fill pass can fill even when
the configured pyramiding limit is `1`. It does not claim same-tick stop or
stop-limit entry exceptions, shorts, reversals, `strategy.order()`, realtime
tick recalculation, or host parity additions.

Goal:

- let a single limit-entry fill pass collect all eligible long limit entries,
  then append each resulting open trade even when the batch exceeds the normal
  pyramiding limit.

Closed evidence:

- `pending_limit_entries_triggered_together_can_exceed_pyramiding_limit`
  proves the broker fills two same-pass limit entries with `pyramiding=1`.
- `strategy_entry_limit_orders_triggered_together_can_exceed_pyramiding_limit`
  proves the public runtime emits two long orders and exposes two open trades
  from the same historical bar.
- `tests/fixtures/runtime/strategy_pyramiding_limit_same_tick_limit_entries.pine`
  records the conformance fixture for the narrowed public claim.

Future slices:

- same-tick stop-entry pyramiding-limit exceptions;
- same-tick stop-limit-entry pyramiding-limit exceptions;
- broader host parity coverage for future public JSON contracts.

### Slice 76: Same-Tick Stop Entry Pyramiding Exception

Status: closed on 2026-06-06. This slice extends the fixture-backed
price-based same-tick pyramiding-limit exception to multiple long stop entries
that are all eligible during the same historical fill pass. It does not claim
same-tick stop-limit entry exceptions, shorts, reversals, `strategy.order()`,
realtime tick recalculation, or host parity additions.

Goal:

- let a single stop-entry fill pass collect all eligible long stop entries,
  then append each resulting open trade even when the batch exceeds the normal
  pyramiding limit.

Closed evidence:

- `pending_stop_entries_triggered_together_can_exceed_pyramiding_limit` proves
  the broker fills two same-pass stop entries with `pyramiding=1`.
- `strategy_entry_stop_orders_triggered_together_can_exceed_pyramiding_limit`
  proves the public runtime emits two long orders and exposes two open trades
  from the same historical bar.
- `tests/fixtures/runtime/strategy_pyramiding_limit_same_tick_stop_entries.pine`
  records the conformance fixture for the narrowed public claim.

Future slices:

- broader host parity coverage for future public JSON contracts.

### Slice 77: Same-Tick Stop-Limit Entry Pyramiding Exception

Status: closed on 2026-06-06. This slice extends the fixture-backed
price-based same-tick pyramiding-limit exception to multiple long stop-limit
entries that are already activated and all eligible during the same historical
limit-fill pass. It preserves the existing stop-limit activation-bar delay and
does not claim shorts, reversals, `strategy.order()`, realtime tick
recalculation, or host parity additions.

Goal:

- let a single stop-limit fill pass collect all eligible activated long
  stop-limit entries, then append each resulting open trade even when the batch
  exceeds the normal pyramiding limit.

Closed evidence:

- `pending_stop_limit_entries_triggered_together_can_exceed_pyramiding_limit`
  proves the broker activates two stop-limit entries, skips activation-bar
  fills, then fills both with `pyramiding=1` on the later limit pass.
- `strategy_entry_stop_limit_orders_triggered_together_can_exceed_pyramiding_limit`
  proves the public runtime emits two long orders and exposes two open trades
  from the later historical fill bar.
- `tests/fixtures/runtime/strategy_pyramiding_limit_same_tick_stop_limit_entries.pine`
  records the conformance fixture for the narrowed public claim.

Future slices:

- broader host parity coverage for future public JSON contracts.

### Slice 78: Same-Tick Price-Based Entry WASM Host Parity

Status: closed on 2026-06-06. This slice adds WASM public JSON coverage for the
fixture-backed same-tick long price-based entry exceptions from Slices 75-77. It
does not change runtime behavior, widen the Python binding claim, or claim
shorts, reversals, `strategy.order()`, realtime tick recalculation, or broader
strategy reporting semantics.

Goal:

- prove that the WASM `run_script_csv` host path exposes the same public orders,
  position snapshots, plots, and empty diagnostics for the same-tick long limit,
  stop, and stop-limit entry fixtures already covered by CLI/runtime snapshots.

Closed evidence:

- `runs_strategy_same_tick_limit_entries_from_csv_to_public_strategy_json`
  covers `strategy_pyramiding_limit_same_tick_limit_entries.pine` through the
  WASM CSV host path.
- `runs_strategy_same_tick_stop_entries_from_csv_to_public_strategy_json` covers
  `strategy_pyramiding_limit_same_tick_stop_entries.pine` through the WASM CSV
  host path.
- `runs_strategy_same_tick_stop_limit_entries_from_csv_to_public_strategy_json`
  covers `strategy_pyramiding_limit_same_tick_stop_limit_entries.pine` through
  the WASM CSV host path.

Future slices:

- broader host parity coverage for future public JSON contracts.

### Slice 79: Same-Tick Price-Based Entry Python Host Parity

Status: closed on 2026-06-06. This slice adds Python binding public JSON
coverage for the fixture-backed same-tick long price-based entry exceptions
from Slices 75-77. It does not change runtime behavior, widen the WASM claim,
or claim shorts, reversals, `strategy.order()`, realtime tick recalculation, or
broader strategy reporting semantics.

Goal:

- prove that the Python `run_script` host path exposes the same public orders,
  position snapshots, plots, and empty diagnostics for the same-tick long limit,
  stop, and stop-limit entry fixtures already covered by CLI/runtime snapshots
  and WASM.

Closed evidence:

- `test_run_script_returns_same_tick_limit_entries_contract` covers
  `strategy_pyramiding_limit_same_tick_limit_entries.pine` through the Python
  binding.
- `test_run_script_returns_same_tick_stop_entries_contract` covers
  `strategy_pyramiding_limit_same_tick_stop_entries.pine` through the Python
  binding.
- `test_run_script_returns_same_tick_stop_limit_entries_contract` covers
  `strategy_pyramiding_limit_same_tick_stop_limit_entries.pine` through the
  Python binding.

Future slices:

- broader host parity coverage for future public JSON contracts.

### Slice 80: Base Pyramiding WASM Host Parity

Status: closed on 2026-06-06. This slice adds WASM public JSON coverage for the
base multi-entry ledger fixtures from Slices 10-12: long market pyramiding,
`strategy.close(id)` matching, and `strategy.close_all()` flattening. It does
not change runtime behavior, widen the Python binding claim, or claim shorts,
reversals, `strategy.order()`, price-based entry behavior beyond the existing
fixture-backed subset, or broader strategy reporting semantics.

Goal:

- prove that the WASM `run_script_csv` host path exposes the same public orders,
  trades, position snapshots, plots, and empty diagnostics for the base
  pyramiding, close, and close_all fixtures already covered by CLI/runtime
  snapshots.

Closed evidence:

- `runs_strategy_pyramiding_from_csv_to_public_strategy_json` covers
  `strategy_pyramiding.pine` through the WASM CSV host path.
- `runs_strategy_pyramiding_close_from_csv_to_public_strategy_json` covers
  `strategy_pyramiding_close.pine` through the WASM CSV host path.
- `runs_strategy_pyramiding_close_all_from_csv_to_public_strategy_json` covers
  `strategy_pyramiding_close_all.pine` through the WASM CSV host path.

Future slices:

- broader host parity coverage for future public JSON contracts.

### Slice 81: Base Pyramiding Python Host Parity

Status: closed on 2026-06-06. This slice adds Python binding public JSON
coverage for the base multi-entry ledger fixtures from Slices 10-12: long market
pyramiding, `strategy.close(id)` matching, and `strategy.close_all()` flattening.
It does not change runtime behavior, widen the WASM claim, or claim shorts,
reversals, `strategy.order()`, price-based entry behavior beyond the existing
fixture-backed subset, or broader strategy reporting semantics.

Goal:

- prove that the Python `run_script` host path exposes the same public orders,
  trades, position snapshots, plots, and empty diagnostics for the base
  pyramiding, close, and close_all fixtures already covered by CLI/runtime
  snapshots and WASM.

Closed evidence:

- `test_run_script_returns_strategy_pyramiding_contract` covers
  `strategy_pyramiding.pine` through the Python binding.
- `test_run_script_returns_strategy_pyramiding_close_contract` covers
  `strategy_pyramiding_close.pine` through the Python binding.
- `test_run_script_returns_strategy_pyramiding_close_all_contract` covers
  `strategy_pyramiding_close_all.pine` through the Python binding.

Future slices:

- broader host parity coverage for future public JSON contracts.

### Slice 82: `strategy.exit(from_entry)` WASM Host Parity

Status: closed on 2026-06-06. This slice adds WASM public JSON coverage for the
multi-entry exit fixtures from Slices 14-16: absolute `strategy.exit(from_entry)`
matching, relative profit tick price basis, and same-id allocation fan-out. It
does not change runtime behavior, widen the Python binding claim, or claim
brackets, trailing exits, omitted-`from_entry` behavior, shorts, reversals,
`close_entries_rule`, or broader strategy reporting semantics.

Goal:

- prove that the WASM `run_script_csv` host path exposes the same public orders,
  trades, position snapshots, plots, and empty diagnostics for the fixture-backed
  absolute, relative profit, and same-id multi-entry exit contracts already
  covered by CLI/runtime snapshots.

Closed evidence:

- `runs_strategy_pyramiding_exit_from_entry_from_csv_to_public_strategy_json`
  covers `strategy_pyramiding_exit_from_entry.pine` through the WASM CSV host
  path.
- `runs_strategy_pyramiding_exit_profit_from_entry_from_csv_to_public_strategy_json`
  covers `strategy_pyramiding_exit_profit_from_entry.pine` through the WASM CSV
  host path.
- `runs_strategy_pyramiding_exit_same_id_from_csv_to_public_strategy_json` covers
  `strategy_pyramiding_exit_same_id.pine` through the WASM CSV host path.

Future slices:

- broader host parity coverage for future public JSON contracts.

### Slice 83: `strategy.exit(from_entry)` Python Host Parity

Status: closed on 2026-06-06. This slice adds Python binding public JSON
coverage for the multi-entry exit fixtures from Slices 14-16: absolute
`strategy.exit(from_entry)` matching, relative profit tick price basis, and
same-id allocation fan-out. It does not change runtime behavior, widen the WASM
claim, or claim brackets, trailing exits, omitted-`from_entry` behavior, shorts,
reversals, `close_entries_rule`, or broader strategy reporting semantics.

Goal:

- prove that the Python `run_script` host path exposes the same public orders,
  trades, position snapshots, plots, and empty diagnostics for the fixture-backed
  absolute, relative profit, and same-id multi-entry exit contracts already
  covered by CLI/runtime snapshots and WASM.

Closed evidence:

- `test_run_script_returns_strategy_pyramiding_exit_from_entry_contract` covers
  `strategy_pyramiding_exit_from_entry.pine` through the Python binding.
- `test_run_script_returns_strategy_pyramiding_exit_profit_from_entry_contract`
  covers `strategy_pyramiding_exit_profit_from_entry.pine` through the Python
  binding.
- `test_run_script_returns_strategy_pyramiding_exit_same_id_contract` covers
  `strategy_pyramiding_exit_same_id.pine` through the Python binding.

Future slices:

- broader host parity coverage for future public JSON contracts.

### Slice 84: Bracket and Trailing `strategy.exit(from_entry)` WASM Host Parity

Status: closed on 2026-06-06. This slice adds WASM public JSON coverage for the
multi-entry bracket and trailing `strategy.exit(from_entry)` fixtures from
Slices 17-18. It does not change runtime behavior, widen the Python binding
claim, or claim omitted-`from_entry` behavior, shorts, reversals,
`close_entries_rule`, public trailing-state fields, or broader strategy
reporting semantics.

Goal:

- prove that the WASM `run_script_csv` host path exposes the same public orders,
  trades, position snapshots, plots, and empty diagnostics for the fixture-backed
  bracket and trailing multi-entry exit contracts already covered by CLI/runtime
  snapshots.

Closed evidence:

- `runs_strategy_pyramiding_exit_bracket_from_entry_from_csv_to_public_strategy_json`
  covers `strategy_pyramiding_exit_bracket_from_entry.pine` through the WASM CSV
  host path.
- `runs_strategy_pyramiding_exit_trail_points_from_entry_from_csv_to_public_strategy_json`
  covers `strategy_pyramiding_exit_trail_points_from_entry.pine` through the
  WASM CSV host path.

Future slices:

- broader host parity coverage for future public JSON contracts.

### Slice 85: Bracket and Trailing `strategy.exit(from_entry)` Python Host Parity

Status: closed on 2026-06-06. This slice adds Python binding public JSON
coverage for the multi-entry bracket and trailing `strategy.exit(from_entry)`
fixtures from Slices 17-18. It does not change runtime behavior, widen the WASM
claim, or claim omitted-`from_entry` behavior, shorts, reversals,
`close_entries_rule`, public trailing-state fields, or broader strategy
reporting semantics.

Goal:

- prove that the Python `run_script` host path exposes the same public orders,
  trades, position snapshots, plots, and empty diagnostics for the fixture-backed
  bracket and trailing multi-entry exit contracts already covered by CLI/runtime
  snapshots and WASM.

Closed evidence:

- `test_run_script_returns_strategy_pyramiding_exit_bracket_from_entry_contract`
  covers `strategy_pyramiding_exit_bracket_from_entry.pine` through the Python
  binding.
- `test_run_script_returns_strategy_pyramiding_exit_trail_points_from_entry_contract`
  covers `strategy_pyramiding_exit_trail_points_from_entry.pine` through the
  Python binding.

Future slices:

- broader host parity coverage for future public JSON contracts.

### Slice 86: Current Same-Id Omitted Profit/Loss WASM Host Parity

Status: closed on 2026-06-06. This slice adds WASM public JSON coverage for the
current-open same-entry-id omitted-`from_entry` single-trigger `profit` and
`loss` fixtures from Slices 59-60. It does not change runtime behavior, widen
the Python binding claim, or claim same-id omitted brackets, trailing exits,
future-entry persistence, shorts, reversals, `close_entries_rule`, or broader
strategy reporting semantics.

Goal:

- prove that the WASM `run_script_csv` host path exposes the same public orders,
  trades, position snapshots, plots, and empty diagnostics for the fixture-backed
  current same-id omitted `profit` and `loss` multi-entry exit contracts already
  covered by runtime/broker tests.

Closed evidence:

- `runs_strategy_omitted_profit_same_id_fixture_from_csv_to_public_strategy_json`
  covers `strategy_pyramiding_exit_omitted_profit_same_id.pine` through the WASM
  CSV host path.
- `runs_strategy_omitted_loss_same_id_fixture_from_csv_to_public_strategy_json`
  covers `strategy_pyramiding_exit_omitted_loss_same_id.pine` through the WASM
  CSV host path.

Future slices:

- broader host parity coverage for future public JSON contracts.

### Slice 87: Current Same-Id Omitted Profit/Loss Python Host Parity

Status: closed on 2026-06-06. This slice adds Python binding public JSON
coverage for the current-open same-entry-id omitted-`from_entry` single-trigger
`profit` and `loss` fixtures from Slices 59-60. It does not change runtime
behavior, widen the WASM claim, or claim same-id omitted brackets, trailing
exits, future-entry persistence, shorts, reversals, `close_entries_rule`, or
broader strategy reporting semantics.

Goal:

- prove that the Python `run_script` host path exposes the same public orders,
  trades, position snapshots, plots, and empty diagnostics for the fixture-backed
  current same-id omitted `profit` and `loss` multi-entry exit contracts already
  covered by runtime/broker tests and WASM.

Closed evidence:

- `test_run_script_returns_omitted_profit_same_id_fixture_contract` covers
  `strategy_pyramiding_exit_omitted_profit_same_id.pine` through the Python
  binding.
- `test_run_script_returns_omitted_loss_same_id_fixture_contract` covers
  `strategy_pyramiding_exit_omitted_loss_same_id.pine` through the Python
  binding.

Future slices:

- broader host parity coverage for future public JSON contracts.

### Slice 88: Current Same-Id Omitted Bracket WASM Host Parity

Status: closed on 2026-06-06. This slice adds WASM public JSON coverage for the
current-open same-entry-id omitted-`from_entry` `loss+profit` and `stop+profit`
bracket fixtures from Slices 61-62. It does not change runtime behavior, widen
the Python binding claim, or claim same-id omitted `loss+limit`, `stop+limit`,
trailing exits, future-entry persistence, shorts, reversals,
`close_entries_rule`, or broader strategy reporting semantics.

Goal:

- prove that the WASM `run_script_csv` host path exposes the same public orders,
  trades, position snapshots, plots, and empty diagnostics for the fixture-backed
  current same-id omitted `loss+profit` and `stop+profit` bracket multi-entry
  exit contracts already covered by runtime/broker tests.

Closed evidence:

- `runs_strategy_omitted_loss_profit_bracket_same_id_fixture_from_csv_to_public_strategy_json`
  covers `strategy_pyramiding_exit_omitted_loss_profit_bracket_same_id.pine`
  through the WASM CSV host path.
- `runs_strategy_omitted_stop_profit_bracket_same_id_fixture_from_csv_to_public_strategy_json`
  covers `strategy_pyramiding_exit_omitted_stop_profit_bracket_same_id.pine`
  through the WASM CSV host path.

Future slices:

- matching Python public JSON parity coverage for the same fixtures;
- broader host parity coverage for future public JSON contracts.

### Slice 89: Current Same-Id Omitted Bracket Python Host Parity

Status: closed on 2026-06-06. This slice adds Python binding public JSON
coverage for the current-open same-entry-id omitted-`from_entry` `loss+profit`
and `stop+profit` bracket fixtures from Slices 61-62. It does not change runtime
behavior, widen the WASM claim, or claim same-id omitted `loss+limit`,
`stop+limit`, trailing exits, future-entry persistence, shorts, reversals,
`close_entries_rule`, or broader strategy reporting semantics.

Goal:

- prove that the Python `run_script` host path exposes the same public orders,
  trades, position snapshots, plots, and empty diagnostics for the fixture-backed
  current same-id omitted `loss+profit` and `stop+profit` bracket multi-entry
  exit contracts already covered by runtime/broker tests and WASM.

Closed evidence:

- `test_run_script_returns_omitted_loss_profit_bracket_same_id_fixture_contract`
  covers `strategy_pyramiding_exit_omitted_loss_profit_bracket_same_id.pine`
  through the Python binding.
- `test_run_script_returns_omitted_stop_profit_bracket_same_id_fixture_contract`
  covers `strategy_pyramiding_exit_omitted_stop_profit_bracket_same_id.pine`
  through the Python binding.

Future slices:

- broader host parity coverage for future public JSON contracts.

### Slice 90: Current Same-Id Omitted Loss/Stop Limit Bracket WASM Host Parity

Status: closed on 2026-06-06. This slice adds WASM public JSON coverage for the
current-open same-entry-id omitted-`from_entry` `loss+limit` and `stop+limit`
bracket fixtures from Slices 63-64. It does not change runtime behavior, widen
the Python binding claim, or claim trailing exits, future-entry persistence,
shorts, reversals, `close_entries_rule`, or broader strategy reporting
semantics.

Goal:

- prove that the WASM `run_script_csv` host path exposes the same public orders,
  trades, position snapshots, plots, and empty diagnostics for the fixture-backed
  current same-id omitted `loss+limit` and `stop+limit` bracket multi-entry exit
  contracts already covered by runtime/broker tests.

Closed evidence:

- `runs_strategy_omitted_loss_limit_bracket_same_id_fixture_from_csv_to_public_strategy_json`
  covers `strategy_pyramiding_exit_omitted_loss_limit_bracket_same_id.pine`
  through the WASM CSV host path.
- `runs_strategy_omitted_stop_limit_bracket_same_id_fixture_from_csv_to_public_strategy_json`
  covers `strategy_pyramiding_exit_omitted_stop_limit_bracket_same_id.pine`
  through the WASM CSV host path.

Future slices:

- matching Python public JSON parity coverage for the same fixtures;
- broader host parity coverage for future public JSON contracts.

### Slice 91: Current Same-Id Omitted Loss/Stop Limit Bracket Python Host Parity

Status: closed on 2026-06-06. This slice adds Python binding public JSON
coverage for the current-open same-entry-id omitted-`from_entry` `loss+limit`
and `stop+limit` bracket fixtures from Slices 63-64. It does not change runtime
behavior, widen the WASM claim, or claim trailing exits, future-entry
persistence, shorts, reversals, `close_entries_rule`, or broader strategy
reporting semantics.

Goal:

- prove that the Python `run_script` host path exposes the same public orders,
  trades, position snapshots, plots, and empty diagnostics for the fixture-backed
  current same-id omitted `loss+limit` and `stop+limit` bracket multi-entry exit
  contracts already covered by runtime/broker tests and WASM.

Closed evidence:

- `test_run_script_returns_omitted_loss_limit_bracket_same_id_fixture_contract`
  covers `strategy_pyramiding_exit_omitted_loss_limit_bracket_same_id.pine`
  through the Python binding.
- `test_run_script_returns_omitted_stop_limit_bracket_same_id_fixture_contract`
  covers `strategy_pyramiding_exit_omitted_stop_limit_bracket_same_id.pine`
  through the Python binding.

Future slices:

- broader host parity coverage for future public JSON contracts.

### Slice 92: Current Same-Id Omitted Trailing WASM Host Parity

Status: closed on 2026-06-06. This slice adds WASM public JSON coverage for the
current-open same-entry-id omitted-`from_entry` `trail_points+trail_offset` and
`trail_price+trail_offset` trailing fixtures from Slices 65-66. It does not
change runtime behavior, widen the Python binding claim, or claim future-entry
persistence, shorts, reversals, `close_entries_rule`, or broader strategy
reporting semantics.

Goal:

- prove that the WASM `run_script_csv` host path exposes the same public orders,
  trades, position snapshots, plots, and empty diagnostics for the fixture-backed
  current same-id omitted `trail_points+trail_offset` and
  `trail_price+trail_offset` trailing multi-entry exit contracts already covered
  by runtime/broker tests.

Closed evidence:

- `runs_strategy_omitted_trail_points_same_id_fixture_from_csv_to_public_strategy_json`
  covers `strategy_pyramiding_exit_omitted_trail_points_same_id.pine` through
  the WASM CSV host path.
- `runs_strategy_omitted_trail_price_same_id_fixture_from_csv_to_public_strategy_json`
  covers `strategy_pyramiding_exit_omitted_trail_price_same_id.pine` through the
  WASM CSV host path.

Future slices:

- matching Python public JSON parity coverage for the same fixtures;
- broader host parity coverage for future public JSON contracts.

### Slice 93: Current Same-Id Omitted Trailing Python Host Parity

Status: closed on 2026-06-06. This slice adds Python binding public JSON
coverage for the current-open same-entry-id omitted-`from_entry`
`trail_points+trail_offset` and `trail_price+trail_offset` trailing fixtures
from Slices 65-66. It does not change runtime behavior, widen the WASM claim,
or claim future-entry persistence, shorts, reversals, `close_entries_rule`, or
broader strategy reporting semantics.

Goal:

- prove that the Python `run_script` host path exposes the same public orders,
  trades, position snapshots, plots, and empty diagnostics for the fixture-backed
  current same-id omitted `trail_points+trail_offset` and
  `trail_price+trail_offset` trailing multi-entry exit contracts already covered
  by runtime/broker tests and WASM.

Closed evidence:

- `test_run_script_returns_omitted_trail_points_same_id_fixture_contract`
  covers `strategy_pyramiding_exit_omitted_trail_points_same_id.pine` through
  the Python binding.
- `test_run_script_returns_omitted_trail_price_same_id_fixture_contract` covers
  `strategy_pyramiding_exit_omitted_trail_price_same_id.pine` through the Python
  binding.

Future slices:

- broader host parity coverage for future public JSON contracts.

### Slice 94: Same-Id Omitted Profit/Loss Future WASM Host Parity

Status: closed on 2026-06-06. This slice adds WASM public JSON coverage for the
same-entry-id omitted-`from_entry` `profit` and `loss` future-entry persistence
fixtures from Slices 67-68. It does not change runtime behavior, widen the
Python binding claim, or claim same-id omitted bracket/trailing future-entry
persistence, shorts, reversals, `close_entries_rule`, or broader strategy
reporting semantics.

Goal:

- prove that the WASM `run_script_csv` host path exposes the same public orders,
  trades, position snapshots, plots, and empty diagnostics for the fixture-backed
  same-id omitted `profit` and `loss` future-entry persistence contracts already
  covered by runtime/broker tests.

Closed evidence:

- `runs_strategy_omitted_profit_persistent_same_id_fixture_from_csv_to_public_strategy_json`
  covers `strategy_pyramiding_exit_omitted_profit_persistent_same_id.pine`
  through the WASM CSV host path.
- `runs_strategy_omitted_loss_persistent_same_id_fixture_from_csv_to_public_strategy_json`
  covers `strategy_pyramiding_exit_omitted_loss_persistent_same_id.pine` through
  the WASM CSV host path.

Future slices:

- same-id omitted bracket/trailing future-entry host parity coverage;
- broader host parity coverage for future public JSON contracts.

### Slice 95: Same-Id Omitted Profit/Loss Future Python Host Parity

Status: closed on 2026-06-06. This slice adds Python binding public JSON
coverage for the same-entry-id omitted-`from_entry` `profit` and `loss`
future-entry persistence fixtures from Slices 67-68. It does not change runtime
behavior, widen the WASM claim, or claim same-id omitted bracket/trailing
future-entry persistence, shorts, reversals, `close_entries_rule`, or broader
strategy reporting semantics.

Goal:

- prove that the Python `run_script` host path exposes the same public orders,
  trades, position snapshots, plots, and empty diagnostics for the fixture-backed
  same-id omitted `profit` and `loss` future-entry persistence contracts already
  covered by runtime/broker tests and WASM.

Closed evidence:

- `test_run_script_returns_omitted_profit_persistent_same_id_fixture_contract`
  covers `strategy_pyramiding_exit_omitted_profit_persistent_same_id.pine`
  through the Python binding.
- `test_run_script_returns_omitted_loss_persistent_same_id_fixture_contract`
  covers `strategy_pyramiding_exit_omitted_loss_persistent_same_id.pine` through
  the Python binding.

Future slices:

- matching Python public JSON parity coverage for the same fixtures;
- same-id omitted `loss+limit`/`stop+limit` and trailing future-entry host
  parity coverage;
- broader host parity coverage for future public JSON contracts.

### Slice 96: Same-Id Omitted Loss+Profit/Stop+Profit Future WASM Host Parity

Status: closed on 2026-06-06. This slice adds WASM public JSON coverage for the
same-entry-id omitted-`from_entry` `loss+profit` and `stop+profit` bracket
future-entry persistence fixtures from Slices 69-70. It does not change runtime
behavior, widen the Python binding claim, or claim same-id omitted
`loss+limit`/`stop+limit`, trailing future-entry persistence, shorts, reversals,
`close_entries_rule`, or broader strategy reporting semantics.

Goal:

- prove that the WASM `run_script_csv` host path exposes the same public orders,
  trades, position snapshots, plots, and empty diagnostics for the fixture-backed
  same-id omitted `loss+profit` and `stop+profit` future-entry bracket
  contracts already covered by runtime/broker tests.

Closed evidence:

- `runs_omitted_loss_profit_bracket_persistent_same_id_from_csv_to_json`
  covers
  `strategy_pyramiding_exit_omitted_loss_profit_bracket_persistent_same_id.pine`
  through the WASM CSV host path.
- `runs_omitted_stop_profit_bracket_persistent_same_id_from_csv_to_json`
  covers
  `strategy_pyramiding_exit_omitted_stop_profit_bracket_persistent_same_id.pine`
  through the WASM CSV host path.

Future slices:

- same-id omitted `loss+limit`/`stop+limit` and trailing future-entry host
  parity coverage;
- broader host parity coverage for future public JSON contracts.

### Slice 97: Same-Id Omitted Loss+Profit/Stop+Profit Future Python Host Parity

Status: closed on 2026-06-06. This slice adds Python binding public JSON
coverage for the same-entry-id omitted-`from_entry` `loss+profit` and
`stop+profit` bracket future-entry persistence fixtures from Slices 69-70. It
does not change runtime behavior, widen the WASM claim, or claim same-id
omitted `loss+limit`/`stop+limit`, trailing future-entry persistence, shorts,
reversals, `close_entries_rule`, or broader strategy reporting semantics.

Goal:

- prove that the Python `run_script` host path exposes the same public orders,
  trades, position snapshots, plots, and empty diagnostics for the fixture-backed
  same-id omitted `loss+profit` and `stop+profit` future-entry bracket
  contracts already covered by runtime/broker tests and WASM.

Closed evidence:

- `test_run_script_returns_omitted_loss_profit_bracket_persistent_same_id_fixture_contract`
  covers
  `strategy_pyramiding_exit_omitted_loss_profit_bracket_persistent_same_id.pine`
  through the Python binding.
- `test_run_script_returns_omitted_stop_profit_bracket_persistent_same_id_fixture_contract`
  covers
  `strategy_pyramiding_exit_omitted_stop_profit_bracket_persistent_same_id.pine`
  through the Python binding.

Future slices:

- matching Python public JSON parity coverage for the same fixtures;
- same-id omitted trailing future-entry host parity coverage;
- broader host parity coverage for future public JSON contracts.

### Slice 98: Same-Id Omitted Loss+Limit/Stop+Limit Future WASM Host Parity

Status: closed on 2026-06-06. This slice adds WASM public JSON coverage for the
same-entry-id omitted-`from_entry` `loss+limit` and `stop+limit` bracket
future-entry persistence fixtures from Slices 71-72. It does not change runtime
behavior, widen the Python binding claim, or claim same-id omitted trailing
future-entry persistence, shorts, reversals, `close_entries_rule`, or broader
strategy reporting semantics.

Goal:

- prove that the WASM `run_script_csv` host path exposes the same public orders,
  trades, position snapshots, plots, and empty diagnostics for the fixture-backed
  same-id omitted `loss+limit` and `stop+limit` future-entry bracket contracts
  already covered by runtime/broker tests.

Closed evidence:

- `runs_omitted_loss_limit_bracket_persistent_same_id_from_csv_to_json` covers
  `strategy_pyramiding_exit_omitted_loss_limit_bracket_persistent_same_id.pine`
  through the WASM CSV host path.
- `runs_omitted_stop_limit_bracket_persistent_same_id_from_csv_to_json` covers
  `strategy_pyramiding_exit_omitted_stop_limit_bracket_persistent_same_id.pine`
  through the WASM CSV host path.

Future slices:

- same-id omitted trailing future-entry host parity coverage;
- broader host parity coverage for future public JSON contracts.

### Slice 99: Same-Id Omitted Loss+Limit/Stop+Limit Future Python Host Parity

Status: closed on 2026-06-06. This slice adds Python binding public JSON
coverage for the same-entry-id omitted-`from_entry` `loss+limit` and
`stop+limit` bracket future-entry persistence fixtures from Slices 71-72. It
does not change runtime behavior, widen the WASM claim, or claim same-id
omitted trailing future-entry persistence, shorts, reversals,
`close_entries_rule`, or broader strategy reporting semantics.

Goal:

- prove that the Python `run_script` host path exposes the same public orders,
  trades, position snapshots, plots, and empty diagnostics for the fixture-backed
  same-id omitted `loss+limit` and `stop+limit` future-entry bracket contracts
  already covered by runtime/broker tests and WASM.

Closed evidence:

- `test_run_script_returns_omitted_loss_limit_bracket_persistent_same_id_fixture_contract`
  covers
  `strategy_pyramiding_exit_omitted_loss_limit_bracket_persistent_same_id.pine`
  through the Python binding.
- `test_run_script_returns_omitted_stop_limit_bracket_persistent_same_id_fixture_contract`
  covers
  `strategy_pyramiding_exit_omitted_stop_limit_bracket_persistent_same_id.pine`
  through the Python binding.

Future slices:

- same-id omitted trailing future-entry host parity coverage;
- broader host parity coverage for future public JSON contracts.

### Slice 100: Same-Id Omitted Trail-Price/Trail-Points Future WASM Host Parity

Status: closed on 2026-06-06. This slice adds WASM public JSON coverage for the
same-entry-id omitted-`from_entry` `trail_price+trail_offset` and
`trail_points+trail_offset` trailing future-entry persistence fixtures from
Slices 73-74. It does not change runtime behavior, widen the Python binding
claim, or claim shorts, reversals, `close_entries_rule`, or broader strategy
reporting semantics.

Goal:

- prove that the WASM `run_script_csv` host path exposes the same public orders,
  trades, position snapshots, plots, and empty diagnostics for the fixture-backed
  same-id omitted trailing future-entry persistence contracts already covered by
  runtime/broker tests.

Closed evidence:

- `runs_omitted_trail_price_persistent_same_id_from_csv_to_json` covers
  `strategy_pyramiding_exit_omitted_trail_price_persistent_same_id.pine` through
  the WASM CSV host path.
- `runs_omitted_trail_points_persistent_same_id_from_csv_to_json` covers
  `strategy_pyramiding_exit_omitted_trail_points_persistent_same_id.pine`
  through the WASM CSV host path.

Future slices:

- broader host parity coverage for future public JSON contracts.

### Slice 101: Same-Id Omitted Trail-Price/Trail-Points Future Python Host Parity

Status: closed on 2026-06-06. This slice adds Python binding public JSON
coverage for the same-entry-id omitted-`from_entry`
`trail_price+trail_offset` and `trail_points+trail_offset` trailing
future-entry persistence fixtures from Slices 73-74. It does not change runtime
behavior, widen the WASM claim, or claim shorts, reversals,
`close_entries_rule`, or broader strategy reporting semantics.

Goal:

- prove that the Python `run_script` host path exposes the same public orders,
  trades, position snapshots, plots, and empty diagnostics for the fixture-backed
  same-id omitted trailing future-entry persistence contracts already covered by
  runtime/broker tests and WASM.

Closed evidence:

- `test_run_script_returns_omitted_trail_price_persistent_same_id_fixture_contract`
  covers
  `strategy_pyramiding_exit_omitted_trail_price_persistent_same_id.pine` through
  the Python binding.
- `test_run_script_returns_omitted_trail_points_persistent_same_id_fixture_contract`
  covers
  `strategy_pyramiding_exit_omitted_trail_points_persistent_same_id.pine`
  through the Python binding.

Future slices:

- broader host parity coverage for future public JSON contracts.

### Slice 74: Same-Id Omitted Trail-Points Future Runtime

Status: closed on 2026-06-06. This slice widens the fixture-backed runtime
subset for omitted-`from_entry` `strategy.exit` with
`trail_points+trail_offset`: when a full-position all-entry trailing template
is placed while one same-entry-id long trade is open, the persistent template
now also attaches to a later long trade with the same entry id using that later
trade's broker-owned open-trade key and entry price for activation. It does not
claim shorts, reversals, price-based same-tick entry exceptions, or host parity
additions.

Goal:

- resolve deferred all-entry `trail_points` exits for same-entry-id later
  trades by targeting the newly opened trade key and deriving activation from
  that trade's own entry price.

Closed evidence:

- `strategy_exit_omitted_from_entry_trail_points_persists_for_later_same_entry_id`
  proves the persistent omitted trailing exit closes both same-id trades after
  per-trade activation.
- `tests/fixtures/runtime/strategy_pyramiding_exit_omitted_trail_points_persistent_same_id.pine`
  records the conformance fixture for the narrowed public claim.
- `resolve_all_entry_deferred_relative_exit_for_entry` now shares the same
  last-open-trade key lookup used by profit/loss and relative bracket deferred
  paths, and no longer depends on the old unique-entry-id guard.

Future slices:

- price-based same-tick pyramiding-limit exceptions;
- broader host parity coverage for future public JSON contracts.

### Slice 73: Same-Id Omitted Trail-Price Future Fixture

Status: closed on 2026-06-06. This slice adds explicit fixture-backed coverage
for omitted-`from_entry` `strategy.exit` with `trail_price+trail_offset` when
the persistent all-entry absolute trailing template attaches to a later long
trade that shares the same entry id as an existing open trade. Because
`trail_price` is a shared absolute activation price, the existing persistent
all-entry trailing runtime already supports this behavior. It does not claim
same-id omitted `trail_points+trail_offset` future-entry persistence, shorts,
reversals, or host parity additions.

Goal:

- add explicit same-id fixture coverage for the absolute `trail_price` trailing
  future-entry path so the absolute trailing future-entry closeout is fully
  fixture-backed for same-entry-id trades.

Closed evidence:

- `strategy_exit_omitted_from_entry_trail_price_persists_for_later_same_entry_id`
  proves the persistent absolute trailing exit closes both same-id trades
  through the shared active trailing stop.
- `tests/fixtures/runtime/strategy_pyramiding_exit_omitted_trail_price_persistent_same_id.pine`
  records the conformance fixture for the narrowed public claim.
- No runtime change was required because the existing omitted absolute trailing
  persistence path already expands to every later open trade key.

Future slices:

- duplicate same-id omitted-`from_entry` `trail_points+trail_offset`
  future-entry persistence;
- price-based same-tick pyramiding-limit exceptions;
- broader host parity coverage for future public JSON contracts.

### Slice 72: Same-Id Omitted Stop+Limit Future Bracket Fixture

Status: closed on 2026-06-06. This slice adds explicit fixture-backed coverage
for omitted-`from_entry` `strategy.exit` with a `stop+limit` bracket when the
persistent all-entry absolute bracket attaches to a later long trade that shares
the same entry id as an existing open trade. Because both bracket legs are
absolute prices, the existing persistent all-entry absolute bracket runtime
already supports this behavior. It does not claim same-id omitted trailing
future-entry persistence, shorts, reversals, or host parity additions.

Goal:

- add explicit same-id fixture coverage for the absolute `stop+limit` bracket
  future-entry path so the same-id bracket future-entry closeout is fully
  fixture-backed.

Closed evidence:

- `strategy_exit_omitted_from_entry_stop_limit_bracket_persists_for_later_same_entry_id`
  proves the persistent absolute bracket closes both same-id trades through the
  shared absolute limit.
- `tests/fixtures/runtime/strategy_pyramiding_exit_omitted_stop_limit_bracket_persistent_same_id.pine`
  records the conformance fixture for the narrowed public claim.
- No runtime change was required because the existing omitted absolute bracket
  persistence path already expands to every later open trade key.

Future slices:

- duplicate same-id omitted-`from_entry` trailing future-entry persistence;
- price-based same-tick pyramiding-limit exceptions;
- broader host parity coverage for future public JSON contracts.

### Slice 71: Same-Id Omitted Loss+Limit Future Bracket

Status: closed on 2026-06-06. This slice widens the fixture-backed runtime
subset for omitted-`from_entry` `strategy.exit` with a `loss+limit` bracket:
when a full-position all-entry mixed relative/absolute bracket is placed while
one same-entry-id long trade is open, the persistent all-entry template now
also attaches to a later long trade with the same entry id using that later
trade's broker-owned open-trade key and entry price for the loss leg while
preserving the shared absolute limit. It does not claim same-id omitted
`stop+limit`, trailing future-entry persistence, shorts, reversals, or host
parity additions.

Goal:

- resolve the deferred all-entry `loss+limit` bracket template for the newest
  same-entry-id open trade instead of requiring the entry id to be unique.
- compute the later trade's loss leg from the later trade's own entry price
  while preserving the existing absolute limit leg.

Closed evidence:

- `resolve_all_entry_deferred_relative_exit_for_entry` now uses the latest
  matching open-trade key and entry price for `RelativeLoss+Absolute` brackets;
  `stop+limit` and trailing deferred same-id paths retain the existing
  unique-entry-id guard.
- `strategy_exit_omitted_from_entry_loss_limit_bracket_persists_for_later_same_entry_id`
  proves the persistent omitted bracket closes the earlier same-id trade
  through its own loss leg while the later same-id trade exits through the
  shared absolute limit.
- `tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_limit_bracket_persistent_same_id.pine`
  records the conformance fixture for the narrowed public claim.

Future slices:

- duplicate same-id omitted-`from_entry` `stop+limit` future-entry persistence;
- duplicate same-id omitted-`from_entry` trailing future-entry persistence;
- price-based same-tick pyramiding-limit exceptions;
- broader host parity coverage for future public JSON contracts.

### Slice 70: Same-Id Omitted Stop+Profit Future Bracket

Status: closed on 2026-06-06. This slice widens the fixture-backed runtime
subset for omitted-`from_entry` `strategy.exit` with a `stop+profit` bracket:
when a full-position all-entry mixed absolute/relative bracket is placed while
one same-entry-id long trade is open, the persistent all-entry template now
also attaches to a later long trade with the same entry id using that later
trade's broker-owned open-trade key and entry price for the profit leg while
preserving the shared absolute stop. It does not claim same-id omitted
`loss+limit`, `stop+limit`, trailing future-entry persistence, shorts,
reversals, or host parity additions.

Goal:

- resolve the deferred all-entry `stop+profit` bracket template for the newest
  same-entry-id open trade instead of requiring the entry id to be unique.
- compute the later trade's profit leg from the later trade's own entry price
  while preserving the existing absolute stop leg.

Closed evidence:

- `resolve_all_entry_deferred_relative_exit_for_entry` now uses the latest
  matching open-trade key and entry price for `Absolute+RelativeProfit`
  brackets; `loss+limit`, `stop+limit`, and trailing deferred same-id paths
  retain the existing unique-entry-id guard.
- `strategy_exit_omitted_from_entry_stop_profit_bracket_persists_for_later_same_entry_id`
  proves the persistent omitted bracket closes the later same-id trade through
  its own profit leg while the earlier same-id trade remains protected by the
  shared absolute stop.
- `tests/fixtures/runtime/strategy_pyramiding_exit_omitted_stop_profit_bracket_persistent_same_id.pine`
  records the conformance fixture for the narrowed public claim.

Future slices:

- duplicate same-id omitted-`from_entry` `loss+limit` and `stop+limit`
  future-entry persistence;
- duplicate same-id omitted-`from_entry` trailing future-entry persistence;
- price-based same-tick pyramiding-limit exceptions;
- broader host parity coverage for future public JSON contracts.

### Slice 69: Same-Id Omitted Loss+Profit Future Bracket

Status: closed on 2026-06-06. This slice widens the fixture-backed runtime
subset for omitted-`from_entry` `strategy.exit` with a `loss+profit` bracket:
when a full-position all-entry relative bracket is placed while one
same-entry-id long trade is open, the persistent all-entry template now also
attaches to a later long trade with the same entry id using that later trade's
broker-owned open-trade key and entry price for both bracket legs. It does not
claim same-id omitted `stop+profit`, `loss+limit`, `stop+limit`, trailing
future-entry persistence, shorts, reversals, or host parity additions.

Goal:

- resolve the deferred all-entry `loss+profit` bracket template for the newest
  same-entry-id open trade instead of requiring the entry id to be unique.
- compute both later-trade bracket legs from the later trade's own entry price
  while preserving the existing current-open keyed pending bracket.

Closed evidence:

- `resolve_all_entry_deferred_relative_exit_for_entry` now uses the latest
  matching open-trade key and entry price for `RelativeLoss+RelativeProfit`
  brackets; mixed absolute/relative bracket and trailing deferred same-id paths
  retain the existing unique-entry-id guard.
- `strategy_exit_omitted_from_entry_loss_profit_bracket_persists_for_later_same_entry_id`
  proves the persistent omitted bracket closes both same-id trades at prices
  derived from their own entries.
- `tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_profit_bracket_persistent_same_id.pine`
  records the conformance fixture for the narrowed public claim.

Future slices:

- duplicate same-id omitted-`from_entry` `stop+profit`, `loss+limit`, and
  `stop+limit` future-entry persistence;
- duplicate same-id omitted-`from_entry` trailing future-entry persistence;
- price-based same-tick pyramiding-limit exceptions;
- broader host parity coverage for future public JSON contracts.

### Slice 68: Same-Id Omitted Loss Future Entry

Status: closed on 2026-06-06. This slice widens the fixture-backed runtime
subset for omitted-`from_entry` `strategy.exit` with a single `loss` trigger:
when a full-position all-entry loss exit is placed while one same-entry-id long
trade is open, the persistent all-entry template now also attaches to a later
long trade with the same entry id using that later trade's broker-owned
open-trade key and entry price. It does not claim same-id omitted bracket,
trailing future-entry persistence, shorts, reversals, or host parity additions.

Goal:

- resolve the deferred all-entry loss template for the newest same-entry-id
  open trade instead of requiring the entry id to be unique.
- compute the later trade's loss stop from the later trade's own entry price
  while preserving the existing current-open keyed pending exit.

Closed evidence:

- `resolve_all_entry_deferred_relative_exit_for_entry` now uses the latest
  matching open-trade key and entry price for `LossTicks`; bracket and trailing
  deferred same-id paths retain the existing unique-entry-id guard.
- `strategy_exit_omitted_from_entry_loss_persists_for_later_same_entry_id`
  proves the persistent omitted loss exit closes both same-id trades at prices
  derived from their own entries.
- `tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_persistent_same_id.pine`
  records the conformance fixture for the narrowed public claim.

Future slices:

- duplicate same-id omitted-`from_entry` bracket/trailing future-entry
  persistence;
- price-based same-tick pyramiding-limit exceptions;
- broader host parity coverage for future public JSON contracts.

### Slice 67: Same-Id Omitted Profit Future Entry

Status: closed on 2026-06-06. This slice widens the fixture-backed runtime
subset for omitted-`from_entry` `strategy.exit` with a single `profit` trigger:
when a full-position all-entry profit exit is placed while one same-entry-id
long trade is open, the persistent all-entry template now also attaches to a
later long trade with the same entry id using that later trade's broker-owned
open-trade key and entry price. It does not claim same-id omitted loss,
bracket, trailing future-entry persistence, shorts, reversals, or host parity
additions.

Goal:

- resolve the deferred all-entry profit template for the newest same-entry-id
  open trade instead of requiring the entry id to be unique.
- compute the later trade's profit limit from the later trade's own entry price
  while preserving the existing current-open keyed pending exit.

Closed evidence:

- `resolve_all_entry_deferred_relative_exit_for_entry` now uses the latest
  matching open-trade key and entry price for `ProfitTicks` only; loss, bracket,
  and trailing deferred same-id paths retain the existing unique-entry-id guard.
- `strategy_exit_omitted_from_entry_profit_persists_for_later_same_entry_id`
  proves the persistent omitted profit exit closes both same-id trades at
  prices derived from their own entries.
- `tests/fixtures/runtime/strategy_pyramiding_exit_omitted_profit_persistent_same_id.pine`
  records the conformance fixture for the narrowed public claim.

Future slices:

- duplicate same-id omitted-`from_entry` loss-tick future-entry persistence;
- duplicate same-id omitted-`from_entry` bracket/trailing future-entry
  persistence;
- price-based same-tick pyramiding-limit exceptions;
- broader host parity coverage for future public JSON contracts.

### Slice 59: Current Same-Id Omitted Profit Exit

Status: closed on 2026-06-06. This slice widens the fixture-backed runtime
subset for current open trades only: omitted-`from_entry` `strategy.exit` with a
single `profit` trigger now handles multiple open long trades that share the
same entry id, using each open trade's own entry price and internal trade key.
It does not claim same-id omitted bracket, trailing, future-entry
persistence, shorts, reversals, or host parity additions.

Goal:

- remove the current-open duplicate entry-id guard for omitted profit-tick
  exits now that pending exits can preserve per-open-trade identity by key.

Closed evidence:

- `place_all_entry_exit_profit_ticks` now creates one keyed pending exit per
  open trade, including same-id open trades.
- Filled pending-exit cleanup now includes `target_trade_key` in the removal
  identity so one same-id fill does not remove another pending same-id exit.
- `strategy_exit_omitted_from_entry_profit_handles_same_entry_id` proves two
  same-id pyramided long trades close at different profit prices derived from
  their own entry prices.
- `tests/fixtures/runtime/strategy_pyramiding_exit_omitted_profit_same_id.pine`
  records the conformance fixture for the narrowed public claim.

Future slices:

- duplicate same-id omitted-`from_entry` `loss+profit` bracket/trailing
  targets;
- duplicate same-id omitted-`from_entry` future-entry persistence;
- price-based same-tick pyramiding-limit exceptions;
- broader host parity coverage for future public JSON contracts.

### Slice 61: Current Same-Id Omitted Loss+Profit Bracket

Status: closed on 2026-06-06. This slice widens the fixture-backed runtime
subset for current open trades only: omitted-`from_entry` `strategy.exit` with
`loss` plus `profit` now handles multiple open long trades that share the same
entry id, using each open trade's own entry price and internal trade key for the
bracket legs. It does not claim same-id omitted `stop+profit`, `loss+limit`,
`stop+limit`, trailing, future-entry persistence, shorts, reversals, or host
parity additions.

Goal:

- remove the current-open duplicate entry-id guard for omitted loss+profit
  brackets now that pending exits can preserve per-open-trade identity by key.

Closed evidence:

- `place_all_entry_exit_loss_profit_bracket` now creates one keyed pending
  bracket per open trade, including same-id open trades.
- `strategy_exit_omitted_from_entry_loss_profit_bracket_handles_same_entry_id`
  proves two same-id pyramided long trades close on different bracket legs
  derived from their own entry prices.
- `tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_profit_bracket_same_id.pine`
  records the conformance fixture for the narrowed public claim.

Future slices:

- duplicate same-id omitted-`from_entry` future-entry persistence;
- price-based same-tick pyramiding-limit exceptions;
- broader host parity coverage for future public JSON contracts.

### Slice 66: Current Same-Id Omitted Trail Price Fixture

Status: closed on 2026-06-06. This slice documents the already-supported
fixture-backed current open-trade subset for omitted-`from_entry`
`strategy.exit` with `trail_price` plus `trail_offset` when multiple open long
trades share the same entry id. Because `trail_price` uses a shared absolute
activation price and the existing all-entry trailing path, this slice adds
explicit coverage without runtime changes. It does not claim same-id
future-entry persistence, shorts, reversals, or host parity additions.

Goal:

- add explicit same-id fixture coverage for the absolute `trail_price` trailing
  path so the current-open same-id omitted exit closeout is fully fixture-backed
  across single-trigger, bracket, and trailing forms.

Closed evidence:

- `strategy_exit_omitted_from_entry_trail_price_handles_same_entry_id` proves
  two same-id pyramided long trades close through the shared absolute trailing
  activation path.
- `tests/fixtures/runtime/strategy_pyramiding_exit_omitted_trail_price_same_id.pine`
  records the conformance fixture for the narrowed public claim.
- No runtime change was required because the existing omitted absolute trailing
  path already allocates all open ledger entries.

Future slices:

- duplicate same-id omitted-`from_entry` future-entry persistence;
- price-based same-tick pyramiding-limit exceptions;
- broader host parity coverage for future public JSON contracts.

### Slice 65: Current Same-Id Omitted Trail Points

Status: closed on 2026-06-06. This slice widens the fixture-backed runtime
subset for current open trades only: omitted-`from_entry` `strategy.exit` with
`trail_points` plus `trail_offset` now handles multiple open long trades that
share the same entry id, using each open trade's own entry price and internal
trade key for activation. It does not claim same-id omitted `trail_price`
fixture coverage, future-entry persistence, shorts, reversals, or host parity
additions.

Goal:

- remove the current-open duplicate entry-id guard for omitted
  trail_points-based trailing exits now that pending exits can preserve
  per-open-trade identity by key.

Closed evidence:

- `place_all_entry_exit_trail_points` now creates one keyed pending trailing
  exit per open trade, including same-id open trades.
- `strategy_exit_omitted_from_entry_trail_points_handles_same_entry_id` proves
  two same-id pyramided long trades activate from their own entry prices and
  close through keyed trailing exits.
- `tests/fixtures/runtime/strategy_pyramiding_exit_omitted_trail_points_same_id.pine`
  records the conformance fixture for the narrowed public claim.

Future slices:

- duplicate same-id omitted-`from_entry` `trail_price` trailing fixture coverage;
- duplicate same-id omitted-`from_entry` future-entry persistence;
- price-based same-tick pyramiding-limit exceptions;
- broader host parity coverage for future public JSON contracts.

### Slice 64: Current Same-Id Omitted Stop+Limit Bracket Fixture

Status: closed on 2026-06-06. This slice documents the already-supported
fixture-backed current open-trade subset for omitted-`from_entry`
`strategy.exit` with `stop` plus `limit` when multiple open long trades share
the same entry id. Because `stop+limit` uses shared absolute prices and the
existing all-entry absolute bracket path, this slice adds explicit coverage
without runtime changes. It does not claim same-id omitted trailing,
future-entry persistence, shorts, reversals, or host parity additions.

Goal:

- add explicit same-id fixture coverage for the absolute `stop+limit` bracket
  path so the current-open bracket same-id closeout is fully fixture-backed.

Closed evidence:

- `strategy_exit_omitted_from_entry_stop_limit_bracket_handles_same_entry_id`
  proves two same-id pyramided long trades close through the shared absolute
  limit on the same eligible bar.
- `tests/fixtures/runtime/strategy_pyramiding_exit_omitted_stop_limit_bracket_same_id.pine`
  records the conformance fixture for the narrowed public claim.
- No runtime change was required because the existing omitted absolute bracket
  path already allocates all open ledger entries.

Future slices:

- duplicate same-id omitted-`from_entry` trailing targets;
- duplicate same-id omitted-`from_entry` future-entry persistence;
- price-based same-tick pyramiding-limit exceptions;
- broader host parity coverage for future public JSON contracts.

### Slice 63: Current Same-Id Omitted Loss+Limit Bracket

Status: closed on 2026-06-06. This slice widens the fixture-backed runtime
subset for current open trades only: omitted-`from_entry` `strategy.exit` with
`loss` plus `limit` now handles multiple open long trades that share the same
entry id, using each open trade's own entry price and internal trade key for the
loss leg while preserving the shared absolute limit. It does not claim same-id
omitted `stop+limit`, trailing, future-entry persistence, shorts, reversals, or
host parity additions.

Goal:

- remove the current-open duplicate entry-id guard for omitted loss+limit
  brackets now that pending exits can preserve per-open-trade identity by key.

Closed evidence:

- `place_all_entry_exit_loss_limit_bracket` now creates one keyed pending
  bracket per open trade, including same-id open trades.
- `strategy_exit_omitted_from_entry_loss_limit_bracket_handles_same_entry_id`
  proves two same-id pyramided long trades close through the per-trade loss leg
  and shared absolute limit.
- `tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_limit_bracket_same_id.pine`
  records the conformance fixture for the narrowed public claim.

Future slices:

- duplicate same-id omitted-`from_entry` `stop+limit` and trailing targets;
- duplicate same-id omitted-`from_entry` future-entry persistence;
- price-based same-tick pyramiding-limit exceptions;
- broader host parity coverage for future public JSON contracts.

### Slice 62: Current Same-Id Omitted Stop+Profit Bracket

Status: closed on 2026-06-06. This slice widens the fixture-backed runtime
subset for current open trades only: omitted-`from_entry` `strategy.exit` with
`stop` plus `profit` now handles multiple open long trades that share the same
entry id, preserving the shared absolute stop and using each open trade's own
entry price and internal trade key for the profit leg. It does not claim
same-id omitted `loss+limit`, `stop+limit`, trailing, future-entry persistence,
shorts, reversals, or host parity additions.

Goal:

- remove the current-open duplicate entry-id guard for omitted stop+profit
  brackets now that pending exits can preserve per-open-trade identity by key.

Closed evidence:

- `place_all_entry_exit_stop_profit_bracket` now creates one keyed pending
  bracket per open trade, including same-id open trades.
- `strategy_exit_omitted_from_entry_stop_profit_bracket_handles_same_entry_id`
  proves two same-id pyramided long trades close through the per-trade profit
  leg and shared absolute stop.
- `tests/fixtures/runtime/strategy_pyramiding_exit_omitted_stop_profit_bracket_same_id.pine`
  records the conformance fixture for the narrowed public claim.

Future slices:

- duplicate same-id omitted-`from_entry` `loss+limit`, `stop+limit`, and
  trailing targets;
- duplicate same-id omitted-`from_entry` future-entry persistence;
- price-based same-tick pyramiding-limit exceptions;
- broader host parity coverage for future public JSON contracts.

### Slice 60: Current Same-Id Omitted Loss Exit

Status: closed on 2026-06-06. This slice widens the fixture-backed runtime
subset for current open trades only: omitted-`from_entry` `strategy.exit` with a
single `loss` trigger now handles multiple open long trades that share the same
entry id, using each open trade's own entry price and internal trade key. It
does not claim same-id omitted bracket, trailing, future-entry persistence,
shorts, reversals, or host parity additions.

Goal:

- remove the current-open duplicate entry-id guard for omitted loss-tick exits
  now that pending exits can preserve per-open-trade identity by key.

Closed evidence:

- `place_all_entry_exit_loss_ticks` now creates one keyed pending exit per open
  trade, including same-id open trades.
- `strategy_exit_omitted_from_entry_loss_handles_same_entry_id` proves two
  same-id pyramided long trades close at different loss prices derived from
  their own entry prices.
- `tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_same_id.pine`
  records the conformance fixture for the narrowed public claim.

Future slices:

- duplicate same-id omitted-`from_entry` bracket/trailing targets;
- duplicate same-id omitted-`from_entry` future-entry persistence;
- price-based same-tick pyramiding-limit exceptions;
- broader host parity coverage for future public JSON contracts.

## Compatibility Contract

The supported strategy subset remains the one recorded in
`tests/fixtures/conformance.tsv`. Stage 13 Slice 10 claims only the
fixture-backed positive integer const `pyramiding` subset for same-direction
long market entries plus Slice 11's fixture-backed `strategy.close(id)` matching
behavior, Slice 12's fixture-backed `strategy.close_all()` flattening behavior,
and Slice 14's fixture-backed absolute `strategy.exit` matching by open
pyramided entry id plus Slice 15's fixture-backed single-trigger `profit`/`loss`
tick conversion for a matched open pyramided entry id and Slice 16's
fixture-backed same-entry-id exit allocation fan-out plus Slice 17's
fixture-backed bracket `profit`/`loss` relative leg conversion plus Slice 18's
fixture-backed trailing `trail_points` activation conversion plus Slice 19's
fixture-backed omitted-`from_entry` current open-entry absolute stop/limit
all-entry exit plus Slice 20's fixture-backed persistent future-entry expansion
for that same absolute stop/limit subset plus Slice 21's fixture-backed
omitted-`from_entry` current unique-entry-id profit-tick all-entry exit plus
Slice 22's fixture-backed omitted-`from_entry` current unique-entry-id loss-tick
all-entry exit plus Slice 23's fixture-backed omitted-`from_entry` current
unique-entry-id `loss+profit` bracket all-entry exit plus Slice 24's
fixture-backed omitted-`from_entry` current unique-entry-id `stop+profit`
bracket all-entry exit plus Slice 25's fixture-backed omitted-`from_entry`
current unique-entry-id `loss+limit` bracket all-entry exit plus Slice 26's
fixture-backed omitted-`from_entry` current all-entry `stop+limit` bracket exit
plus Slice 27's fixture-backed omitted-`from_entry` current all-entry
`trail_price+trail_offset` trailing exit plus Slice 28's fixture-backed omitted-
`from_entry` current unique-entry-id `trail_points+trail_offset` trailing exit
plus Slice 29's fixture-backed omitted-`from_entry` unique-entry-id profit-tick
future-entry persistence plus Slice 30's fixture-backed omitted-`from_entry`
unique-entry-id loss-tick future-entry persistence plus Slice 31's
fixture-backed omitted-`from_entry` unique-entry-id `loss+profit` bracket
future-entry persistence plus Slice 32's fixture-backed omitted-`from_entry`
unique-entry-id `stop+profit` bracket future-entry persistence plus Slice 33's
fixture-backed omitted-`from_entry` unique-entry-id `loss+limit` bracket
future-entry persistence plus Slice 34's fixture-backed omitted-`from_entry`
`stop+limit` absolute bracket future-entry persistence plus Slice 35's
fixture-backed omitted-`from_entry` `trail_price+trail_offset` absolute trailing
future-entry persistence plus Slice 36's fixture-backed omitted-`from_entry`
unique-entry-id `trail_points+trail_offset` relative trailing future-entry
persistence plus Slice 37's WASM public JSON parity coverage for that same
fixture plus Slice 38's Python public JSON parity coverage for the same fixture.
Slice 39 adds WASM public JSON parity coverage for Slice 35's omitted
`trail_price+trail_offset` persistent fixture, and Slice 40 adds matching Python
public JSON parity coverage for that fixture. Slice 41 adds WASM public JSON
parity coverage for Slice 29's omitted profit persistent fixture, and Slice 42
adds matching Python public JSON parity coverage for that fixture. Slice 43 adds
WASM public JSON parity coverage for Slice 30's omitted loss persistent fixture.
Slice 44 adds matching Python public JSON parity coverage for that fixture.
Slice 45 adds WASM public JSON parity coverage for Slice 31's omitted
`loss+profit` bracket persistent fixture, and Slice 46 adds matching Python
public JSON parity coverage for that fixture. Slice 47 adds WASM public JSON
parity coverage for Slice 32's omitted `stop+profit` bracket persistent
fixture, and Slice 48 adds matching Python public JSON parity coverage for that
fixture. Slice 49 adds WASM public JSON parity coverage for Slice 33's omitted
`loss+limit` bracket persistent fixture, and Slice 50 adds matching Python
public JSON parity coverage for that fixture. Slice 51 adds WASM public JSON
parity coverage for Slice 34's omitted `stop+limit` bracket persistent fixture.
Slice 52 adds matching Python public JSON parity coverage for that fixture.
Slice 53 adds WASM public JSON parity coverage for Slice 19's omitted current
all-entry absolute exit fixture, and Slice 54 adds matching Python public JSON
parity coverage for that fixture. Slice 55 adds only internal open-trade keys
for future per-open-trade exit identity work. Slice 56 adds only internal
key-scoped ledger exit allocation. Slice 57 adds only internal pending-exit
trade-key scoping. Slice 58 adds only internal key binding for the existing
unique-entry-id omitted relative expansion. Slice 59 adds fixture-backed current
same-id omitted profit-tick exits only. Slice 60 adds fixture-backed current
same-id omitted loss-tick exits only. Slice 61 adds fixture-backed current
same-id omitted `loss+profit` bracket exits only. Slice 62 adds fixture-backed
current same-id omitted `stop+profit` bracket exits only. Slice 63 adds
fixture-backed current same-id omitted `loss+limit` bracket exits only. Slice
64 adds explicit fixture-backed current same-id omitted `stop+limit` bracket
coverage without runtime changes. Slice 65 adds fixture-backed current same-id
omitted `trail_points+trail_offset` trailing exits only. Slice 66 adds explicit
fixture-backed current same-id omitted `trail_price+trail_offset` trailing
coverage without runtime changes. Slice 67 adds fixture-backed same-id omitted
profit-tick future-entry persistence only. Slice 68 adds matching same-id
omitted loss-tick future-entry persistence. Slice 69 adds matching same-id
omitted `loss+profit` bracket future-entry persistence. Slice 70 adds matching
same-id omitted `stop+profit` bracket future-entry persistence. Slice 71 adds
matching same-id omitted `loss+limit` bracket future-entry persistence. Slice
72 adds explicit same-id omitted `stop+limit` bracket future-entry coverage
without runtime changes. Slice 73 adds explicit same-id omitted
`trail_price+trail_offset` future-entry coverage without runtime changes. Slice
74 adds matching same-id omitted `trail_points+trail_offset` future-entry
runtime support. Slice 75 adds fixture-backed same-tick limit-entry
pyramiding-limit exceptions. Slice 76 adds matching same-tick stop-entry
pyramiding-limit exceptions. Slice 77 adds matching same-tick stop-limit-entry
pyramiding-limit exceptions while preserving activation-bar delay. Slice 78 adds
WASM public JSON parity coverage for the same-tick long limit, stop, and
stop-limit entry fixtures. Slice 79 adds matching Python public JSON parity
coverage for those fixtures. Slice 80 adds WASM public JSON parity coverage for
the base multi-entry ledger fixtures. Slice 81 adds matching Python public JSON
parity coverage for those fixtures. Slice 82 adds WASM public JSON parity
coverage for the absolute `strategy.exit(from_entry)`, relative profit
`strategy.exit(from_entry)`, and same-id fan-out fixtures from Slices 14-16.
Slice 83 adds matching Python public JSON parity coverage for those fixtures.
Slice 84 adds WASM public JSON parity coverage for the bracket and trailing
`strategy.exit(from_entry)` fixtures from Slices 17-18.
Slice 85 adds matching Python public JSON parity coverage for those fixtures.
Slice 86 adds WASM public JSON parity coverage for the current same-id omitted
`profit`/`loss` `strategy.exit` fixtures from Slices 59-60.
Slice 87 adds matching Python public JSON parity coverage for those fixtures.
Slice 88 adds WASM public JSON parity coverage for the current same-id omitted
`loss+profit` and `stop+profit` bracket fixtures from Slices 61-62.
Slice 89 adds matching Python public JSON parity coverage for those fixtures.
Slice 90 adds WASM public JSON parity coverage for the current same-id omitted
`loss+limit` and `stop+limit` bracket fixtures from Slices 63-64.
Slice 91 adds matching Python public JSON parity coverage for those fixtures.
Slice 92 adds WASM public JSON parity coverage for the current same-id omitted
`trail_points+trail_offset` and `trail_price+trail_offset` trailing fixtures
from Slices 65-66.
Slice 93 adds matching Python public JSON parity coverage for those fixtures.
Slice 94 adds WASM public JSON parity coverage for the same-id omitted
`profit`/`loss` future-entry persistence fixtures from Slices 67-68.
Slice 95 adds matching Python public JSON parity coverage for those fixtures.
Slice 96 adds WASM public JSON parity coverage for the same-id omitted
`loss+profit` and `stop+profit` bracket future-entry persistence fixtures from
Slices 69-70.
Slice 97 adds matching Python public JSON parity coverage for those fixtures.
Slice 98 adds WASM public JSON parity coverage for the same-id omitted
`loss+limit` and `stop+limit` bracket future-entry persistence fixtures from
Slices 71-72.
Slice 99 adds matching Python public JSON parity coverage for those fixtures.
Slice 100 adds WASM public JSON parity coverage for the same-id omitted
`trail_price+trail_offset` and `trail_points+trail_offset` trailing
future-entry persistence fixtures from Slices 73-74.
Slice 101 adds matching Python public JSON parity coverage for those fixtures.
These slices must not be used to claim shorts, reversals, `strategy.order()`,
`close_entries_rule`, or broader multi-entry `strategy.exit`/reporting support.
