# Strategy Internal Stage 8 Broker Expansion Plan

Status: initial design gate and behavior-preserving internal skeleton closed
on 2026-06-04 through Slices 0-17, with closeout audit in
`docs/STRATEGY_INTERNAL_STAGE8_BROKER_EXPANSION_AUDIT.md`. Do not widen
runtime broker compatibility
until a later slice adds fixture-backed behavior, conformance metadata, host
snapshots, and release verification.

Stage 8 is the transition from the current one-net-long strategy broker to an
internal model that can eventually support multiple entries, pyramiding,
shorts, reversals, generic orders, and OCA behavior. This document is a design
gate plus the first behavior-preserving internal skeleton. It does not claim
new Pine compatibility, does not widen `tests/fixtures/conformance.tsv`, and
does not change public CLI, Python, or WASM strategy output.

## Starting Point

The current strategy runtime is intentionally narrow and fixture-backed:

- `BrokerState` is the public internal facade under
  `crates/pine-runtime/src/strategy/broker/`.
- The broker stores one net long position through fields such as
  `position_size`, `avg_price`, `entry_id`, `entry_bar_index`, `entry_time`,
  and one open-entry commission balance.
- Pending long entries are internal-only in `PendingEntryBook`.
- Pending exits and explicit exit reservations are internal-only in
  `PendingExitBook`.
- Public runtime output is still the existing `schemaVersion: 3` shape with
  `orders`, `trades`, `position`, `equity`, and `diagnostics`.
- Stage 7 closed the current long-only trade field, reporting, cost,
  percent-of-equity default sizing, active `margin_long`, long-entry
  affordability, and long-only forced-liquidation subset.
- The active-entry absolute `strategy.exit` attachment evidence slice is
  closed, but entry-relative pending-entry exits using `profit`, `loss`, or
  `trail_points` remain unsupported.

## Goal

Design a broker model that can represent future Pine-compatible behavior
without losing the current fixture-backed one-net-long subset.

Stage 8 should create a path toward:

- separate open trades with entry ids;
- net position derived from open trades;
- same-direction pyramiding;
- short positions;
- automatic reversals;
- generic `strategy.order()`;
- entry-specific exit allocation;
- OCA reduce/cancel/none behavior across supported order families.

The first runtime slices must preserve existing behavior and output exactly.
Compatibility widening should come only after the internal model and tests are
stable.

## Non-Goals For The Design Gate

- No runtime behavior changes.
- No conformance status changes.
- No public strategy JSON, Python dictionary, or WASM JSON schema expansion.
- No short exposure, reversals, pyramiding, `strategy.order()`, or custom OCA
  implementation in the design-gate slice.
- No public pending-order, reservation-ledger, open-trade-ledger,
  liquidation-price, exit-reason, bracket-leg, or trailing-state fields.
- No realtime strategy tick path, bar magnifier, lower-timeframe intrabar
  reconstruction, or recalculation-on-fill behavior.
- No broker UI, Strategy Tester UI, external broker connectivity, or remote
  market-data behavior.

## Compatibility Rules

- `tests/fixtures/conformance.tsv` remains the support authority.
- Existing strategy fixtures must keep their current public serialized outputs
  unless a later slice explicitly updates a golden snapshot with an audit note.
- Unsupported strategy forms stay rejected or no-op according to current
  documented behavior.
- Any accepted semantic widening must land atomically with runtime behavior and
  fixture evidence. Sema-only widening is not allowed for broker behavior.
- Public output changes require a separate schema plan that covers CLI,
  Python, WASM, snapshots, release notes, and migration notes.
- Existing `scripts/verify.sh` remains the release gate for a behavior slice.

## Public Output Boundary

Default Stage 8 policy: keep the public strategy result shape unchanged.

The public result continues to expose only:

```text
StrategyResult
  orders
  trades
  position
  equity
  diagnostics
```

Internal pending orders, reservations, OCA groups, open-trade ledgers, and
allocation state should not leak into output. A later schema plan may choose to
expose more data, but that is out of scope for the first Stage 8 slices.

## Intended Internal Model

Stage 8 should move broker state toward explicit ledgers while preserving
`BrokerState` as the facade used by runtime built-ins.

Suggested internal shape:

```text
BrokerState
  settings/account model
  order_book: OrderBook
  trade_ledger: TradeLedger
  public_events: StrategyPublicEvents
  diagnostics

OrderBook
  pending_orders: Vec<PendingOrder>
  next_sequence: u64

TradeLedger
  open_trades: Vec<OpenTrade>
  closed_trades: Vec<ClosedTrade>
  net_position: NetPosition

NetPosition
  signed_size
  avg_price
  market_value helpers

OpenTrade
  trade_id
  entry_id
  direction
  qty
  entry_price
  entry_bar_index
  entry_time
  entry_commission
  max_high
  min_low
  equity baselines

PendingOrder
  order_id
  source_function
  entry_id / from_entry
  direction
  order_kind
  quantity
  trigger
  oca_policy
  created_sequence
  created_bar_index
```

The exact Rust names can differ, but the responsibilities should not stay
spread across one-position fields once Stage 8 refactoring starts.

## Direction And Quantity Semantics

Use signed quantities internally only where that makes net-position arithmetic
clear. Public order and trade quantities should remain positive absolute
quantities unless a later public schema plan changes the output contract.

Recommended internal direction model:

```text
TradeDirection = Long | Short
OrderIntent = Entry | Exit | Close | GenericOrder | Liquidation
QuantityRequest = Full | Fixed(f64) | Percent(f64) | DefaultEntry
ResolvedQuantity = absolute positive quantity plus allocation metadata
```

The current no-short subset maps to positive long quantities only. Short
support should not be added until the ledger can record direction, allocation,
costs, margin, and netting consistently.

## Order Book Semantics To Preserve

The current historical behavior must remain the baseline:

- supported market entries fill at the next historical bar open;
- supported long limit, stop, and stop-limit entries are pending and cannot
  fill on their creation bar;
- `strategy.close` and `strategy.close_all` close the current supported long
  position at the current bar close;
- supported exits are pending and cannot fill on their creation bar;
- trailing exits activate on a later eligible bar and do not fill on the
  activation bar;
- same-bar bracket touches choose the downside leg in the current supported
  subset;
- explicit fixed-quantity and `qty_percent` exit reservations use the current
  reservation ledger semantics;
- omitted-quantity exits keep full-position one-effective-pending replacement
  behavior;
- active-entry absolute exit attachment can target a matching active pending
  entry id;
- unmatched missing-entry exits do not persist as arbitrary future bindings.

## Execution Order Design

Before runtime expansion, Stage 8 must document one canonical historical bar
order. The default should preserve current behavior:

1. At the start of a historical bar, evaluate eligible pending entries created
   on earlier bars.
2. Apply entry fills, affordability checks, attached-exit cleanup for rejected
   entries, and account updates.
3. Run script statements for the current bar.
4. During script execution, enqueue new pending entries/exits/cancellations and
   process immediate close operations according to the current supported
   contract.
5. After script execution, evaluate eligible pending exits created on earlier
   bars.
6. Apply margin-call checks only where the already-supported long-only margin
   subset defines them.
7. Emit position and equity snapshots.

Stage 8 must explicitly decide where generic orders, reversals, OCA reductions,
and future recalculation-on-fill behavior fit before those features are
implemented.

## Same-Bar Precedence Design

Stage 8 must define a stable ordering key before widening broker behavior.

Recommended ordering inputs:

- bar phase: pending-entry fill, script-created immediate action,
  post-script pending-exit fill, margin liquidation;
- order creation sequence within the broker;
- order family: entry, exit, close, generic order, liquidation;
- trigger side: downside versus upside;
- OCA policy;
- entry allocation target.

The current supported subset already has partial precedence rules. Do not add
multiple entries, shorts, or generic orders until the precedence table says how
same-bar conflicts resolve.

## OCA And Reservation Direction

The current reservation model is exit-specific. Stage 8 should not bolt custom
OCA behavior onto `PendingExitBook` directly.

Recommended direction:

- keep existing exit reservations unchanged until an order-book abstraction can
  own reservations;
- model OCA policy as order metadata, not as ad hoc fields on exit triggers;
- define `reduce`, `cancel`, and `none` behavior over generic pending orders
  only after the book can represent entries, exits, and generic orders
  uniformly;
- preserve the current public output shape while OCA remains internal.

## Account And Margin Direction

The Stage 7 long-only margin subset must continue to work during refactors:

- active `margin_long` capital held;
- long-entry affordability checks;
- long-only forced liquidation using `bar.low`;
- supported commission allocation;
- supported slippage and limit verification;
- profit, equity, run-up, and drawdown state variables.

Do not add `margin_short`, currency conversion, symbol precision rounding, or
`strategy.margin_liquidation_price` until the ledger can represent short
market value, short margin requirements, and per-trade liquidation allocation.

## Slice Sequence

### Slice 0: Design Gate Closeout

Document the Stage 8 broker model and update status docs. No code behavior
changes.

Acceptance:

- this document exists;
- `docs/STRATEGY_INTERNAL_EXECUTION_PLAN.md` points Stage 8 to this design
  gate;
- `docs/NEXT_INTERNAL_CAPABILITY_PLAN.md` continues to recommend Stage 8 design
  before runtime expansion;
- release notes record the docs-only design gate;
- no conformance support is widened;
- `git diff --check` and `cargo test -p pine-cli conformance --quiet` pass.

Stop condition:

- stop if current docs or conformance still imply active-entry attachment,
  margin, or `qty + qty_percent` gaps that are already closed.

### Slice 1: Boundary Lock

Closed on 2026-06-04 for the first semantic boundary-lock subset.

Add or refresh negative fixtures only if the current unsupported broker boundary
is not explicit enough.

Candidate boundaries:

- short entries remain unsupported;
- pyramiding remains unsupported;
- generic `strategy.order()` remains unsupported;
- custom OCA names and policies remain unsupported;
- public pending-order and open-trade ledgers remain unsupported;
- entry-relative active-entry exit attachment remains unsupported.

Implemented:

- added `tests/fixtures/sema/unsupported_strategy_pyramiding.pine` to lock
  `strategy(..., pyramiding=2)` as unsupported until the broker can represent
  multiple open trades;
- added `tests/fixtures/sema/unsupported_strategy_exit_oca_name.pine` to lock
  custom exit OCA names as unsupported until OCA policy is modeled by the
  broader order book;
- kept short-entry and generic-order boundaries on the existing dedicated
  fixtures;
- kept entry-relative active-entry exit attachment as a documented runtime
  boundary, not a semantic fixture, because the analyzer cannot know whether a
  matching active pending entry will exist at runtime.

Acceptance:

- accepted behavior does not widen;
- matrix and conformance wording stay conservative;
- existing strategy runtime snapshots remain unchanged.

Stop condition:

- stop if a fixture reveals the analyzer accepts a broker feature that runtime
  does not implement.

### Slice 2: Behavior-Preserving Ledger Skeleton

Status: closed on 2026-06-04 for the first behavior-preserving internal
ledger skeleton.

Introduce internal ledger types while preserving all public behavior.

Implemented:

- added an internal broker `ledger` module with `OpenTrade`, `NetPosition`,
  and `TradeLedger`;
- mirrored the current single long entry, open-trade extremes, partial exit
  reductions, margin-call reductions, and final flat transitions into the
  ledger;
- kept existing `BrokerState` fields as the compatibility source for public
  output and strategy metrics;
- added broker unit tests for long-entry mirroring and partial/final long
  reductions.

Suggested work:

- add small internal structs for open trade, closed trade metrics, and net
  position;
- route the current single long position through the ledger;
- keep `BrokerState` public methods and output collection unchanged;
- keep current `StrategyTrade` and `StrategyOrderEvent` output unchanged.

Acceptance:

- all current strategy runtime tests pass;
- current CLI golden snapshots remain unchanged;
- no conformance row changes;
- no public schema changes.

Stop condition:

- stop if the refactor changes any serialized strategy output without a
  deliberate schema decision.

### Slice 3: Order Book Skeleton

Status: closed on 2026-06-04 for an internal order-book facade that delegates
to existing entry and exit books.

Unify pending entry and pending exit ownership behind an internal order-book
facade while preserving current behavior.

Implemented:

- added an internal broker `order_book` module with `OrderBook`;
- moved `BrokerState` pending-order ownership to `OrderBook` while keeping
  `PendingEntryBook` and `PendingExitBook` as the behavior sources;
- routed cancellation, entry fill lookup, exit lookup, and reservation queries
  through the facade;
- added broker unit tests for facade-backed cancellation, pending entry fill,
  and exit reservation behavior.

Suggested work:

- keep existing `PendingEntryBook` and `PendingExitBook` behavior initially;
- introduce a thin `OrderBook` facade that delegates to them;
- add broker unit tests for current cancellation, entry fill, and exit
  reservation behavior through the facade;
- do not add generic orders or OCA.

Acceptance:

- current entry/exit/cancel behavior is unchanged;
- same snapshots and conformance rows remain valid;
- internal names make future `strategy.order()` support possible without
  claiming it.

Stop condition:

- stop if the facade duplicates reservation state in a way that can diverge
  from `PendingExitBook`.

### Slice 4: Allocation Design For Multiple Open Trades

Status: closed on 2026-06-04 as a design-only allocation gate. No runtime
behavior or public output shape changes are included in this slice.

Write a focused design note or extend this plan before implementing multiple
open trades.

Design decisions:

- `from_entry` selection: an exit with a non-empty `from_entry` may allocate
  only against currently open trades whose entry id exactly matches
  `from_entry`. If no active trade matches, the current unsupported behavior
  remains until a later fixture-backed widening explicitly accepts deferred or
  future binding.
- Omitted `from_entry`: when a later slice accepts omitted `from_entry`, it
  should allocate across all open trades in FIFO entry order. This keeps
  allocation deterministic and matches the current single-position mental
  model. LIFO or best-price allocation is out of scope unless a Pine parity
  fixture proves otherwise.
- Entry-specific ordering: for exits tied to one entry id, allocation is FIFO
  among open trades with that id. This handles future same-id pyramiding while
  preserving entry-specific behavior.
- `strategy.close(id)`: close requests should use the same entry-id FIFO
  allocation as `from_entry=id`; close-all requests should use global FIFO.
- Partial exits: each closed slice consumes quantity from one open trade,
  prorates that open trade's remaining entry commission by closed quantity,
  keeps exit commission on the exit slice, and records run-up/drawdown from
  the consumed open trade state at the time of close.
- Average price: `NetPosition.avg_price` should be derived from remaining open
  trades weighted by signed quantity after every allocation. The legacy
  single-long average price remains unchanged while only one open trade is
  possible.
- Margin and cash: margin requirements and forced liquidation should consume
  long open trades in global FIFO order unless a later Pine parity audit proves
  a different liquidation order. Forced liquidation must emit the same public
  order/trade schema as normal exits for each closed allocation slice.
- Public trades: the existing `StrategyTrade` schema can represent a closed
  allocation slice with `id`, `exit_id`, quantity, prices, times, and profit.
  If a later feature needs bracket-leg identity, OCA group, allocation reason,
  trailing state, or liquidation reason in public output, that feature must
  stop and produce a separate schema plan before widening support.
- Public orders and position: `StrategyOrderEvent` remains one public fill
  event per supported order fill, and `StrategyPositionSnapshot` remains the
  net position after allocation. Internal allocation details stay in
  `TradeLedger` and `OrderBook`.

Concrete fixture gates for later behavior slices:

- two same-id long entries with `pyramiding=2`, one fixed-quantity exit, FIFO
  allocation, and unchanged public result shape unless a schema plan says
  otherwise;
- two different long entry ids, `strategy.exit(..., from_entry="A")`, proving
  only entry `A` is reduced;
- omitted `from_entry` fixed-quantity exit across two open trades, proving
  global FIFO allocation;
- partial exit with commission enabled, proving entry commission proration and
  realized profit;
- forced liquidation with multiple long open trades, proving deterministic FIFO
  allocation and stable public events.

Must decide:

- how `from_entry` selects open trades;
- how omitted `from_entry` allocates exits;
- FIFO versus entry-specific close ordering;
- how partial exits allocate commission, run-up, drawdown, and margin;
- how public `orders` and `trades` remain stable or change.

Acceptance:

- no code required unless the design is split into a later refactor;
- public-output decision is explicit;
- Stage 8 behavior slices after this point have concrete fixtures.

Stop condition:

- stop if Pine parity requires public information the current output schema
  cannot represent.

### Slice 5: First Compatibility Widening Candidate

Status: closed on 2026-06-04 by choosing the internal-only
multiple-open-trade skeleton. This slice does not widen accepted Pine syntax,
runtime behavior, conformance support, or public output.

Choose only one after Slices 2 through 4 are stable.

Chosen candidate:

- internal-only multiple-open-trade skeleton that preserves the current
  no-pyramiding external behavior.

Implemented:

- `TradeLedger` now stores open trades as an internal list, while current entry
  behavior still clears the list before adding the one supported long open
  trade;
- net position is rebuilt from the internal open-trade list, preserving the
  current single-long size and average price;
- partial and final reductions continue to operate on the one supported open
  trade, with tests asserting the list remains single-entry until flat;
- `pyramiding=1`, short entries, reversals, generic `strategy.order()`, and
  custom OCA remain unsupported.

Preferred first candidates:

- `pyramiding=1` as an accepted no-op alias only if it adds real compatibility
  value and does not imply multiple entries;
- entry-relative active-entry exit attachment for `profit`, `loss`, or
  `trail_points` if deferred price resolution can be proven without
  multi-entry ledgers;
- an internal-only multiple-open-trade skeleton that still preserves the
  current no-pyramiding external behavior.

Avoid as first widening candidates:

- short entries;
- automatic reversal;
- full pyramiding;
- generic `strategy.order()`;
- custom OCA.

### Slice 6: Internal FIFO Allocation Helpers

Status: closed on 2026-06-04 as an internal-only allocation helper slice.
This slice does not connect multiple open trades to runtime entry behavior,
does not accept `pyramiding`, and does not change conformance or public output.

Goal:

- make the internal `TradeLedger` capable of planning deterministic FIFO exit
  allocations before any runtime compatibility widening.

Implemented:

- added `TradeAllocation` as an internal allocation slice carrying trade index,
  entry id, allocated quantity, and allocated entry commission;
- added global FIFO allocation for omitted `from_entry`;
- added entry-id FIFO allocation for explicit `from_entry`;
- added allocation application that removes fully consumed open trades, reduces
  partially consumed open trades, and rebuilds net position from remaining open
  trades;
- added ledger unit tests for omitted-entry FIFO allocation, matching-entry
  FIFO allocation, and net-position rebuild after applying allocations.

Acceptance:

- allocation helpers stay internal to the broker ledger;
- current runtime behavior remains one supported open long trade;
- public CLI, Python, and WASM strategy output remains unchanged;
- conformance remains conservative.

Stop condition:

- stop before wiring these helpers into runtime behavior if a later feature
  needs public allocation metadata, bracket-leg identity, OCA identity, or
  liquidation reason fields.

### Slice 7: Single-Position Exit Allocation Routing

Status: closed on 2026-06-04 as a behavior-preserving internal routing slice.
This slice routes the current one-open-long exit paths through ledger
allocation helpers without accepting multiple runtime entries, widening
conformance, or changing public output.

Goal:

- prove the internal allocation helpers can serve current broker exit paths
  before they are used for any multi-entry behavior.

Implemented:

- routed long margin-call liquidation through `TradeLedger::allocate_exit_fifo`
  and `TradeLedger::apply_allocations`;
- routed `strategy.close` for the current long entry through explicit-entry
  FIFO allocation;
- routed supported pending `strategy.exit` fills through explicit-entry FIFO
  allocation;
- kept legacy single-position fields as the public behavior source while
  synchronizing the ledger through allocation application;
- strengthened broker tests to assert ledger state after partial and full
  margin liquidation.

Acceptance:

- current single-position close, exit, and long margin-call behavior remains
  unchanged;
- current CLI golden snapshots remain unchanged;
- no conformance row changes;
- no public schema changes.

Stop condition:

- stop before allowing multiple runtime open trades if any existing close,
  exit, margin, or trade-field fixture changes serialized output.

### Slice 8: Allocation Entry Metadata

Status: closed on 2026-06-04 as a behavior-preserving internal allocation
metadata slice. This slice does not add multiple runtime entries, does not
widen conformance, and does not change public output.

Goal:

- make allocation slices carry enough entry metadata to later emit closed
  trades from per-trade allocations instead of single-position legacy fields.

Implemented:

- extended `TradeAllocation` with entry price, entry bar index, and entry time;
- populated allocation metadata directly from `OpenTrade`;
- routed current margin-call, `strategy.close`, and pending `strategy.exit`
  trade emission through allocation metadata with legacy fallback;
- updated ledger allocation tests to assert metadata preservation.

Acceptance:

- current single-position public trade fields remain unchanged;
- current CLI golden snapshots remain unchanged;
- no conformance row changes;
- no public schema changes.

Stop condition:

- stop before emitting multiple public trades from one order fill unless the
  schema and fixture plan explicitly accepts that public-output shape.

### Slice 9: Allocated Entry Fill Summary

Status: closed on 2026-06-04 as a behavior-preserving internal fill-summary
refactor. This slice does not add multiple runtime entries, widen conformance,
or change public output.

Goal:

- consolidate the current close, exit, and margin-call trade-emission paths so
  they read one internal allocation summary instead of repeating allocation
  metadata fallback logic.

Implemented:

- added an internal `AllocatedEntryFill` summary in the broker fill path;
- centralized entry price, entry bar index, entry time, and allocated entry
  commission fallback handling;
- routed long margin-call liquidation, `strategy.close`, and supported pending
  `strategy.exit` trade emission through that summary;
- preserved current one-position public trade fields and ledger allocation
  application.

Acceptance:

- current single-position close, exit, and long margin-call behavior remains
  unchanged;
- current CLI golden snapshots remain unchanged;
- no conformance row changes;
- no public schema changes.

Stop condition:

- stop before splitting one public fill into multiple public trades unless a
  later schema and fixture plan explicitly requires that output shape.

### Slice 10: Closed Trade Fill Recorder

Status: closed on 2026-06-04 as a behavior-preserving internal trade-recording
refactor. This slice does not add multiple runtime entries, widen conformance,
or change public output.

Goal:

- consolidate public trade and closed-trade-metric recording behind one
  internal fill recorder before any future multi-allocation trade emission.

Implemented:

- added an internal `ClosedTradeFill` summary in the broker fill path;
- added `BrokerState::record_closed_trade_fill` to write the existing
  `StrategyTrade` and `ClosedTradeMetrics` outputs in one place;
- routed long margin-call liquidation, `strategy.close`, and supported pending
  `strategy.exit` trade recording through that helper;
- preserved current one-position public trade fields and closed-trade metrics.

Acceptance:

- current single-position close, exit, and long margin-call behavior remains
  unchanged;
- current CLI golden snapshots remain unchanged;
- no conformance row changes;
- no public schema changes.

Stop condition:

- stop before recording multiple public trades for one order fill unless a
  later schema and fixture plan explicitly requires that output shape.

### Slice 11: Flat Long Legacy State Cleanup

Status: closed on 2026-06-04 as a behavior-preserving internal cleanup slice.
This slice does not add multiple runtime entries, widen conformance, or change
public output.

Goal:

- keep current one-position legacy state cleanup centralized while allocation
  and trade-recording logic moves toward ledger-backed internals.

Implemented:

- added `BrokerState::clear_open_long_legacy_state` in the broker fill path;
- routed full long margin liquidation, `strategy.close`, and full supported
  pending `strategy.exit` cleanup through that helper;
- kept ledger allocation application, position snapshots, public trades, and
  closed-trade metrics unchanged.

Acceptance:

- current full close, full exit, and full long margin-call behavior remains
  unchanged;
- current CLI golden snapshots remain unchanged;
- no conformance row changes;
- no public schema changes.

Stop condition:

- stop before changing flat-state cleanup ordering if any public position,
  equity, trade, or diagnostic fixture changes.

### Slice 12: Position Snapshot Recorder

Status: closed on 2026-06-04 as a behavior-preserving internal snapshot
cleanup slice. This slice does not add multiple runtime entries, widen
conformance, or change public output.

Goal:

- centralize public position snapshot creation after supported close, exit, and
  margin-call fills while the broker still exposes the existing net-position
  public shape.

Implemented:

- added `BrokerState::record_position_snapshot` in the broker fill path;
- routed full and partial long margin liquidation, `strategy.close`, and
  supported pending `strategy.exit` position snapshot writes through that
  helper;
- kept flat snapshots as `{ size: 0.0, avg_price: None }` and non-flat
  snapshots as the current legacy net long size and average price.

Acceptance:

- current public position snapshots remain unchanged;
- current CLI golden snapshots remain unchanged;
- no conformance row changes;
- no public schema changes.

Stop condition:

- stop before changing position snapshot semantics from net position to
  per-trade output without a public schema plan.

### Slice 13: Order Event Recorder

Status: closed on 2026-06-04 as a behavior-preserving internal order-event
cleanup slice. This slice does not add multiple runtime entries, widen
conformance, or change public output.

Goal:

- centralize public order-event creation for the current fill paths that emit
  order events before future order families are introduced.

Implemented:

- added `BrokerState::record_order_event` in the broker fill path;
- routed long margin-call and supported pending `strategy.exit` order-event
  writes through that helper;
- left `strategy.close` behavior unchanged because the current public contract
  does not emit a separate order event for `strategy.close`;
- left entry-fill order recording outside this slice to keep the change scoped
  to exit-like fills.

Acceptance:

- current public order events remain unchanged;
- current CLI golden snapshots remain unchanged;
- no conformance row changes;
- no public schema changes.

Stop condition:

- stop before changing which strategy operations emit public order events
  without a public output and fixture plan.

### Slice 14: Entry Order Event Routing

Status: closed on 2026-06-04 as a behavior-preserving internal order-event
routing slice. This slice does not add multiple runtime entries, widen
conformance, or change public output.

Goal:

- route the current supported long entry fill public order event through the
  same internal order-event recorder used by exit-like fills.

Implemented:

- made `BrokerState::record_order_event` available within broker modules;
- routed current `strategy.entry` long fill order-event writes through that
  helper;
- kept `strategy.close` no-order-event behavior unchanged;
- kept public CLI, Python, and WASM output unchanged.

Acceptance:

- current public entry order events remain unchanged;
- current CLI golden snapshots remain unchanged;
- no conformance row changes;
- no public schema changes.

Stop condition:

- stop before changing which entry variants emit public order events without a
  public output and fixture plan.

### Slice 15: Entry Position Snapshot Routing

Status: closed on 2026-06-04 as a behavior-preserving internal position
snapshot routing slice. This slice does not add multiple runtime entries,
widen conformance, or change public output.

Goal:

- route the current supported long entry fill position snapshot through the
  same internal recorder used by exit, close, and margin-call fills.

Implemented:

- made `BrokerState::record_position_snapshot` available within broker
  modules;
- routed current `strategy.entry` long fill position snapshots through that
  helper after `position_size` and `avg_price` are updated;
- kept public net-position snapshot semantics unchanged.

Acceptance:

- current public entry position snapshots remain unchanged;
- current CLI golden snapshots remain unchanged;
- no conformance row changes;
- no public schema changes.

Stop condition:

- stop before changing position snapshots from current net-position output to
  per-entry or per-trade output without a public schema plan.

### Slice 16: Open Long Legacy State Recorder

Status: closed on 2026-06-04 as a behavior-preserving internal open-position
state routing slice. This slice does not add multiple runtime entries, widen
conformance, or change public output.

Goal:

- route the current supported long entry fill legacy state setup through one
  helper that consumes the same `OpenTrade` metadata recorded in the ledger.

Implemented:

- added `BrokerState::record_open_long_legacy_state` for the current
  one-net-long legacy fields;
- changed `entry_long` to build one `OpenTrade`, use it to update legacy open
  state, and then record it in `TradeLedger`;
- kept cash, commission, entry metadata, runup/drawdown baselines, order
  events, and position snapshots unchanged.

Acceptance:

- current public entry, position, equity, and trade behavior remains
  unchanged;
- current CLI golden snapshots remain unchanged;
- no conformance row changes;
- no public schema changes.

Stop condition:

- stop before deriving public position, cash, or trade metrics only from the
  ledger without a separate fixture-backed migration slice.

### Slice 17: Closeout Audit

Status: closed on 2026-06-04 as the Stage 8 closeout audit. This slice does
not add runtime behavior, widen conformance, or change public output.

Goal:

- verify that the behavior-preserving internal broker expansion skeleton is
  closed enough to stop Stage 8 before compatibility widening.

Implemented:

- added `docs/STRATEGY_INTERNAL_STAGE8_BROKER_EXPANSION_AUDIT.md`;
- documented completed internal surfaces, repo evidence, verification commands,
  unsupported boundaries, and next-direction options;
- kept public strategy compatibility claims tied to conformance and matrix
  output instead of Stage 8 roadmap wording.

Acceptance:

- Stage 8 has an explicit closeout record;
- unsupported strategy broker behavior remains unsupported in docs;
- no conformance row changes;
- no public schema changes.

Stop condition:

- stop Stage 8 here; open a new staged direction for `StrategyPublicEvents`,
  ledger-derived public state, or fixture-backed Pine compatibility widening.

## Verification Plan

Docs-only design gate:

```text
git diff --check
cargo test -p pine-cli conformance --quiet
python3 scripts/check_structure.py
```

Behavior-preserving internal refactor:

```text
cargo fmt
cargo test -p pine-runtime strategy --quiet
cargo test -p pine-runtime --test incremental
cargo test -p pine-sema strategy --quiet
cargo test -p pine-cli runtime_outputs_match_golden_snapshots --quiet
cargo test -p pine-cli matrix_output_matches_golden_snapshot --quiet
cargo test -p pine-wasm strategy --quiet
python3 -m pytest python/tests -q
python3 scripts/check_structure.py
scripts/verify.sh
```

Any public output or host behavior change must additionally update and verify
CLI, Python, WASM, conformance, snapshots, docs, and release notes in the same
slice.

## Closeout Criteria

Stage 8 design is closed only when:

- the intended internal broker model is documented;
- public-output policy is explicit;
- same-bar ordering and order allocation questions are listed with defaults or
  stop conditions;
- the first implementation slice is behavior-preserving;
- unsupported Stage 8 broker features remain unsupported in conformance and
  docs;
- verification commands pass for the slice type.
