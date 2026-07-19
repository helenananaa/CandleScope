# Pure Internal Strategy Close Entries Rule Design Gate

Status: active reference. The first public `"ANY"` slice now accepts
`close_entries_rule="FIFO"` and fixture-backed id-specific long-only
`close_entries_rule="ANY"` allocation for `strategy.close(id)` and
`strategy.exit(..., from_entry=id)`; broader `"ANY"` allocation behavior remains
deferred.

This document defines the internal path for the supported FIFO
`close_entries_rule` subset, the first id-specific `"ANY"` subset, and remaining
non-default allocation support on `strategy(...)`. It is scoped to analyzer
acceptance, strategy declaration settings, ledger allocation, close/exit order
matching, trade namespace values, fixtures, and conformance. It does not cover
chart UI, real broker connectivity, external alert delivery, public open-trade
ledgers, or host-owned Strategy Tester presentation.

## Current Boundary

The current strategy declaration supports a narrow broker-settings subset.
`close_entries_rule="FIFO"` is supported as an explicit default FIFO allocation
setting, and `close_entries_rule="ANY"` is supported for fixture-backed
id-specific long-only close and exit allocation:

```pine
//@version=5
strategy("Supported close entries rule", close_entries_rule="FIFO")
strategy("Supported close entries rule ANY", close_entries_rule="ANY")
```

Current evidence:

- `docs/PURE_INTERNAL_ROADMAP.md` lists broader `close_entries_rule="ANY"` work
  as remaining strategy broker/account work.
- `tests/fixtures/conformance.tsv` records `close_entries_rule="FIFO"` and the
  first fixture-backed id-specific `close_entries_rule="ANY"` subset under the
  partial `strategy` row while keeping unsupported variants under the broad
  `strategy.*` boundary.
- `tests/snapshots/matrix.json` mirrors those conformance rows.
- `tests/fixtures/sema/supported_strategy_close_entries_rule_fifo.pine` and
  `crates/pine-sema/tests/fixtures.rs::accepts_supported_strategy_close_entries_rule_fifo_fixture`
  cover accepted FIFO storage.
- `tests/fixtures/sema/supported_strategy_close_entries_rule_any.pine` and
  `crates/pine-sema/tests/fixtures.rs::accepts_supported_strategy_close_entries_rule_any_fixture`
  cover accepted `"ANY"` storage.
- `tests/fixtures/sema/unsupported_strategy_close_entries_rule_unknown.pine` and
  `crates/pine-sema/tests/fixtures.rs::reports_unsupported_strategy_close_entries_rule_unknown_fixture`
  keep unknown values rejected.
- `tests/fixtures/runtime/strategy_close_entries_rule_fifo.pine`,
  `tests/fixtures/runtime/strategy_close_entries_rule_fifo_close_all.pine`, and
  `crates/pine-runtime/src/tests/strategy.rs::strategy_close_entries_rule_fifo_preserves_default_allocation_order`
  prove representative long-only close/exit output stays on the current FIFO
  path.
- `tests/fixtures/runtime/strategy_close_entries_rule_any_close.pine`,
  `tests/fixtures/runtime/strategy_close_entries_rule_any_exit_from_entry.pine`,
  `tests/fixtures/runtime/strategy_close_entries_rule_any_exit_same_id_partial.pine`,
  and `crates/pine-runtime/src/tests/strategy.rs::strategy_close_entries_rule_any_uses_entry_id_allocation`
  plus
  `crates/pine-runtime/src/tests/strategy.rs::strategy_close_entries_rule_any_partial_exit_same_id_preserves_ledger_order`
  prove the first id-specific long-only `"ANY"` close/exit subset, including
  same-entry-id partial exit allocation in stable ledger order.
- `docs/STRATEGY_INTERNAL_GAP_AUDIT.md` records close-entry ordering as larger
  broker-model work.
- `docs/STRATEGY_INTERNAL_STAGE13_MULTI_ENTRY_LEDGER_PLAN.md` documents the
  historical default FIFO allocation path and broader non-default allocation
  exclusions.
- `crates/pine-runtime/src/strategy/broker/ledger.rs` and
  `crates/pine-runtime/src/strategy/broker/fills.rs` currently route supported
  closes and exits through FIFO or internal-key allocation helpers, not through
  an `"ANY"` allocation policy.
- `crates/pine-runtime/src/strategy/broker/ledger.rs::allocate_exit_any_for_entry`
  and
  `crates/pine-runtime/src/strategy/broker/tests.rs::trade_ledger_allocates_any_rule_by_exact_entry_id_in_ledger_order`
  define the first internal allocation helper for future `"ANY"` entry-id
  selection without widening analyzer acceptance.
- `crates/pine-runtime/src/strategy/broker/mod.rs` stores the internal
  close-entry rule on `BrokerState`, and
  `crates/pine-runtime/src/strategy/broker/fills.rs` routes `strategy.close(id)`
  plus `strategy.exit(..., from_entry=id)` through a single FIFO/ANY allocation
  decision point. Internal broker tests cover the `"ANY"` path:
  `close_entries_rule_any_internal_close_uses_exact_entry_id_allocation`,
  `close_entries_rule_any_internal_exit_from_entry_uses_exact_entry_id_allocation`,
  and `close_entries_rule_any_internal_omitted_exit_stays_fifo`.

## Target Shape

`close_entries_rule` controls how close and exit commands choose open trades
when multiple entries exist. It must not be accepted as an inert declaration
property.

The accepted subsets preserve the existing default behavior while making the
allocation setting explicit:

- accept `strategy(..., close_entries_rule="FIFO")` as a no-semantics-change
  declaration setting only after fixtures prove output parity with the existing
  default FIFO allocation;
- store the setting in HIR/runtime strategy settings so later slices can branch
  on it deliberately;
- keep broader `close_entries_rule="ANY"` behavior deferred until each
  allocation path is fixture-backed;
- preserve the current public strategy JSON shape.

`close_entries_rule="ANY"` is accepted only for the fixture-backed
entry-id-specific close and exit allocation subset across current and pending
long ledger entries.

## Analyzer Policy

Current analyzer policy:

- accept only `"FIFO"` or `"ANY"` and require a const string value;
- reject non-string, dynamic, unknown, and case-mismatched values with stable
  diagnostics;
- do not accept other unsupported declaration properties merely because this
  property is being added.

The broad
`tests/fixtures/sema/unsupported_strategy_declaration_properties.pine` fixture
should stay focused on still-unsupported declaration properties. FIFO support
and `"ANY"` rejection each have focused fixtures.

## Runtime Allocation Policy

The current broker has two relevant allocation paths:

- FIFO allocation across matching open long trades;
- internal key-scoped allocation for broker-owned pending exits that target a
  specific open trade.

`close_entries_rule="FIFO"` uses the existing FIFO path. Positive
`close_entries_rule="ANY"` support must introduce an explicit allocation
decision point instead of letting each command choose ad hoc ledger helpers.
That decision point should receive the declaration setting, command kind,
optional requested entry id, requested quantity, reservation identity when
present, and current open-trade snapshot, then return deterministic
`TradeAllocation` values.

`close_entries_rule` behavior by command:

- `strategy.close(id)`: under `"FIFO"`, keep oldest matching open trades for
  that id. Under `"ANY"`, close trades whose entry id is exactly `id` before any
  other open trades. When multiple open trades share that id, preserve their
  internal open-trade order for deterministic partial fills.
- `strategy.close_all()`: ignore the rule and keep full-position FIFO
  allocation, because there is no requested entry id.
- `strategy.exit(id, from_entry=...)`: under `"FIFO"`, keep the current matching
  FIFO or target-trade-key behavior. Under `"ANY"`, `from_entry` must bind to
  the matching entry id and reservations created for individual open trades
  must keep using their captured trade keys.
- omitted-`from_entry` exits: keep FIFO for both settings until a later slice
  defines a non-id-specific `"ANY"` policy. Accepting `"ANY"` must not silently
  change omitted-`from_entry` behavior.
- future generic `strategy.order()` reductions: remain outside this design until
  generic order netting is implemented.

The default FIFO path should remain the baseline. `"ANY"` must not be reduced to
"find any matching id" without specifying deterministic ordering, partial fills,
pending-exit reservations, same-entry-id pyramiding, and closed-trade record
identity.

## ANY Design Audit

Before accepting `"ANY"`, the runtime must satisfy these internal constraints:

- **Command scope:** the first positive behavior slice should cover only
  `strategy.close(id)` and `strategy.exit(..., from_entry=id)` for current
  long-only open trades. `strategy.close_all()`, omitted-`from_entry` exits,
  generic `strategy.order()` reductions, shorts, reversals, and OCA remain
  unchanged.
- **Selection rule:** requested entry ids must match `OpenTrade.id` exactly.
  Among multiple open trades with that id, allocation order remains their
  stable ledger order so partial fills and trade indexes stay deterministic.
- **Reservation rule:** pending exits that already target a concrete
  `OpenTrade.key` must keep that key through trigger evaluation. `"ANY"` should
  choose which trade keys are reserved when the exit is placed, not when an
  unrelated later trade appears with the same entry id.
- **Closed-trade identity:** each ledger allocation still emits one closed trade
  using the allocated trade's entry id, entry price, entry bar/time, entry
  comment, and proportional entry commission. The exit id/comment continues to
  come from the closing command.
- **Replacement and cancellation:** closing the full quantity for an entry id
  clears pending exits for that id. Partial closes must reduce only affected
  trade quantities and must not clear unrelated pending exits unless the current
  FIFO behavior already does so.
- **Host output:** public strategy JSON shape stays unchanged. Tests should
  prove behavior through existing orders, trades, position, alerts, and plot
  outputs; no public open-trade ledger is introduced.
- **Unsupported diagnostics:** unknown `close_entries_rule` values remain
  rejected after `"FIFO"` and the first fixture-backed `"ANY"` subset are
  accepted.

The first behavior slice adds fixture-backed tests before widening analyzer
acceptance. The fixture pair is:

- two long entries with different ids, then `strategy.close("newer")` under
  `"ANY"` proving the newer matching entry closes while an older different id
  remains open;
- two same-id long entries, then a partial `strategy.exit(..., from_entry=id)`
  proving deterministic same-id ledger-order allocation and stable closed-trade
  records.

Both fixtures should keep `"FIFO"` comparison coverage so default behavior does
not regress while `"ANY"` is introduced.

## Public Output Policy

Supporting `close_entries_rule` does not by itself require public schema
expansion. Runtime order and trade arrays should remain the current public
shape unless a separate schema slice deliberately exposes declaration settings,
pending orders, or open-trade ledgers.

Every accepted behavior must be covered across CLI, Python, and WASM host parity
when runtime output changes.

## Deferred Variants

Keep these variants unsupported until separately designed and fixture-backed:

- broader `close_entries_rule="ANY"` behavior for omitted-`from_entry`,
  `strategy.close_all()`, unmatched future entry binding, and other
  non-id-specific reductions;
- close-entry behavior with short exposure or reversal;
- generic `strategy.order()` reductions;
- custom OCA behavior;
- public pending-order or open-trade ledger output;
- realtime tick recalculation, order-on-close, and bar magnifier timing;
- external order-fill alert delivery.

## Suggested Slice Order

1. Boundary lock: kept earlier `close_entries_rule` rejection covered by the
   broad declaration-property fixture.
2. FIFO setting storage: accepted only `close_entries_rule="FIFO"` and proved it
   exactly matches the current default output for representative long-only close
   and exit fixtures.
3. ANY design audit: define id-specific close/exit allocation with same-entry-id
   pyramiding, reservations, and closed-trade identity.
4. ANY behavior: accepted the narrow long-only id-specific close/exit subset;
   widen only with fixtures.
5. Host parity and conformance synchronization after each positive subset is
   fixture-backed.

Each behavior slice must update `tests/fixtures/conformance.tsv`,
`tests/snapshots/matrix.json` if matrix output changes, public host snapshots
when runtime output changes, relevant strategy docs, and release notes in the
same slice.
