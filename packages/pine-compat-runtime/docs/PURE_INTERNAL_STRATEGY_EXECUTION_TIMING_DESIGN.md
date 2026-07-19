# Pure Internal Strategy Execution Timing Design Gate

Status: closed as a documentation-only design gate. This slice does not change
syntax acceptance, semantic analysis, runtime behavior, conformance status,
snapshots, matrix output, or public strategy output.

This document defines the internal path for future strategy execution timing and
recalculation support. It covers `process_orders_on_close`,
`calc_on_order_fills`, `calc_on_every_tick`, `use_bar_magnifier`, and
`fill_orders_on_standard_ohlc`. It is scoped to analyzer acceptance, strategy
declaration settings, historical fill scheduling, recalculation passes,
realtime rollback, lower-timeframe intrabar data, runtime guardrails, fixtures,
and conformance. It does not cover real broker connectivity, external alert
delivery, chart UI, or host-owned Strategy Tester presentation.

## Current Boundary

The current strategy runtime uses a narrow deterministic timing model:

- historical execution is one script pass per bar;
- supported market entries fill at the next historical bar open;
- supported long limit, stop, and stop-limit entries use internal pending-entry
  state and fill before script statements on eligible later bars;
- supported closes fill at the current bar close;
- supported pending exits fill after script statements using OHLC trigger checks
  and fixed supported prices.

The following declaration properties remain unsupported:

```pine
//@version=5
strategy(
    "Unsupported strategy timing",
    calc_on_order_fills=true,
    calc_on_every_tick=true,
    process_orders_on_close=true,
    use_bar_magnifier=true,
    fill_orders_on_standard_ohlc=true)
```

Current evidence:

- `docs/PURE_INTERNAL_ROADMAP.md` lists `process_orders_on_close`,
  `calc_on_order_fills`, `calc_on_every_tick`, and bar magnifier style timing as
  remaining strategy broker/account work.
- `tests/fixtures/conformance.tsv` records declaration properties beyond the
  current supported `strategy()` subset under the unsupported `strategy.*`
  boundary.
- `tests/snapshots/matrix.json` mirrors that unsupported `strategy.*` matrix
  row.
- `tests/fixtures/sema/unsupported_strategy_declaration_properties.pine` and
  `crates/pine-sema/tests/fixtures.rs::reports_unsupported_strategy_declaration_properties_fixture`
  keep these declaration properties rejected.
- `docs/STRATEGY_INTERNAL_GAP_AUDIT.md` identifies order-on-close,
  recalculation after fills, realtime rollback, repeated tick execution,
  historical intrabar assumptions, and bar magnifier lower-timeframe fills as
  foundation-level gaps.
- `docs/STRATEGY_INTERNAL_STAGE12_DECLARATION_PROPERTIES_PLAN.md` explicitly
  defers these properties until fill-timing and recalculation semantics exist.
- `docs/STRATEGY_INTERNAL_EXECUTION_PLAN.md` records realtime strategy handoff
  and bar magnifier fills outside the current pending-entry timing subset.

Do not accept these declaration properties until runtime behavior is implemented
and fixtures, conformance, snapshots, docs, and host parity are updated
together.

## Target Shape

Execution timing support must be modeled as scheduler behavior, not as stored
no-op flags.

The eventual design must answer:

- when script code executes relative to pending entry, pending exit, close, and
  cancellation processing;
- whether order fills can trigger additional script passes on the same bar;
- how repeated tick execution interacts with `var`, `varip`, history, arrays,
  UDF callsite state, alerts, and strategy state;
- how lower-timeframe intrabar data is represented for bar magnifier behavior;
- how incremental append and forming-bar realtime execution remain deterministic;
- how runtime profiles and guardrails expose or limit extra execution passes.

The first positive subset should be smaller than full timing parity. A
reasonable first target is one historical-only setting whose output can be
compared directly against the existing default timing, with realtime and
lower-timeframe behavior still rejected.

## Analyzer Policy

Initial analyzer policy for future positive slices:

- keep all timing properties rejected until a behavior-backed runtime slice lands
  in the same change;
- accept only const bool values for bool properties;
- reject dynamic, non-bool, unknown, and unsupported combinations with stable
  diagnostics;
- do not accept a declaration property if it only stores an inert HIR flag;
- keep unsupported timing properties listed in the broad declaration-property
  fixture until focused positive and negative fixtures replace that boundary.

## Runtime Scheduling Policy

Any positive timing slice must define the order of operations for:

- script execution;
- pending entry activation and fills;
- pending exit placement, activation, reservation updates, and fills;
- close and close-all fills;
- cancellation calls;
- order-fill-triggered recalculation passes;
- bar-close processing;
- realtime rollback and confirmed-bar commit.

Extra execution passes must be bounded. The runtime must expose or guard against
unbounded loops caused by fill-triggered recalculation, tick replay, or
lower-timeframe reconstruction.

## Realtime And History Policy

`calc_on_every_tick` and bar magnifier behavior must not be implemented only for
historical snapshots. They need explicit policies for:

- forming-bar rollback;
- `varip` carryover across forming updates;
- history commits after repeated executions;
- alert and strategy event rollback;
- incremental append parity;
- host-provided lower-timeframe data absence.

If a first slice is historical-only, it must continue rejecting realtime or
lower-timeframe-dependent settings.

## Deferred Variants

Keep these variants unsupported until separately designed and fixture-backed:

- `calc_on_order_fills`;
- `calc_on_every_tick`;
- `process_orders_on_close`;
- `use_bar_magnifier`;
- `fill_orders_on_standard_ohlc`;
- timing interactions with short exposure, reversals, generic `strategy.order()`,
  custom OCA groups, and `close_entries_rule="ANY"`;
- realtime order-fill alert delivery;
- public pending-order, intrabar, or scheduler profile schema expansion.

## Suggested Slice Order

1. Boundary lock: keep current declaration-property rejection and analyzer
   diagnostics stable.
2. Scheduler audit: document the current order of pending entry, script, close,
   and pending exit phases in code and fixtures.
3. Historical order-on-close design: define one behavior-backed
   `process_orders_on_close` subset without realtime changes.
4. Fill-trigger recalculation design: define bounded same-bar recalculation after
   order fills.
5. Realtime/tick design: define `calc_on_every_tick` rollback and commit rules.
6. Bar magnifier design: define lower-timeframe input, fallback, and guardrails.
7. Host parity and conformance synchronization after each positive subset is
   fixture-backed.

Each behavior slice must update `tests/fixtures/conformance.tsv`,
`tests/snapshots/matrix.json` if matrix output changes, public host snapshots
when runtime output changes, relevant strategy docs, and release notes in the
same slice.
