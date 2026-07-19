# Pure Internal Strategy Short And Reversal Design Gate

Status: closed as a documentation-only design gate. This slice does not change
syntax acceptance, semantic analysis, runtime behavior, conformance status,
snapshots, matrix output, or public strategy output.

This document defines the internal path for future `strategy.short` entries and
automatic long/short reversal. It is scoped to analyzer acceptance, broker
position accounting, trade-ledger directionality, pending entry and exit books,
margin interaction, script-visible strategy variables, runtime guardrails,
fixtures, and conformance. It does not cover real broker connectivity, external
alert delivery, chart UI, or host-service behavior.

## Current Boundary

The current strategy runtime is long-only:

```pine
//@version=5
strategy("Long-only subset")
strategy.entry("L", strategy.long, qty=1)
```

`strategy.short` constants exist as values, but short entries remain rejected:

```pine
//@version=5
strategy("Unsupported short strategy entry")
strategy.entry("S", strategy.short, qty=1)
```

Current evidence:

- `docs/PURE_INTERNAL_ROADMAP.md` lists short exposure and automatic long/short
  reversal as remaining broker/account work.
- `tests/fixtures/conformance.tsv` marks `strategy`, `strategy.entry`, and
  `strategy constants` partial while recording that short entries, reversals,
  and `strategy.order()` remain unsupported.
- `tests/fixtures/sema/unsupported_strategy_entry_short.pine` and
  `crates/pine-sema/tests/fixtures.rs::reports_strategy_entry_short_fixture`
  keep the short-entry diagnostic boundary in place.
- `docs/STRATEGY_INTERNAL_GAP_AUDIT.md` records short entries and automatic
  reversal as large foundation work that must wait for a broader netting and
  close-order design.
- `docs/STRATEGY_INTERNAL_STAGE13_MULTI_ENTRY_LEDGER_PLAN.md` closed the
  current long-only multi-entry ledger and explicitly excludes shorts,
  reversals, `strategy.order()`, and `close_entries_rule`.
- `docs/BUILTIN_SIGNATURES.md`, `docs/SEMANTIC_MODEL.md`, and
  `docs/EXECUTION_SEMANTICS.md` document that `strategy.entry` execution remains
  long-only and that `strategy.max_contracts_held_short` stays `0` in the
  current subset.

Do not accept `strategy.short` entries until a runtime slice implements the
behavior and updates fixtures, conformance, snapshots, docs, and host parity
together.

## Target Shape

The first positive short/reversal subset should be smaller than general
strategy order parity:

- `strategy.entry(id, strategy.short, qty=...)` only, with existing supported
  explicit/default quantity sources;
- market entries before limit, stop, or stop-limit short entries;
- long and short positions represented as signed aggregate position state while
  preserving direction on individual ledger trades;
- automatic reversal from long to short and short to long by closing the current
  opposite exposure and opening the requested entry in one deterministic broker
  operation;
- aggregate `strategy.position_size`, `strategy.position_avg_price`,
  `strategy.openprofit`, `strategy.netprofit`, `strategy.equity`, max-contracts
  fields, and trade namespace values derived from the ledger after every fill;
- current public strategy output shape preserved unless a separate schema slice
  deliberately changes it.

Existing long-only behavior, including supported pyramiding, closes, exits,
reservations, commissions, slippage, limit verification, and long-margin
behavior, must remain unchanged for scripts that do not place short entries.

## Analyzer Policy

Initial analyzer policy for a future positive slice:

- keep `strategy.short` accepted as a constant value;
- continue rejecting `strategy.short` in `strategy.entry` until the runtime
  implementation lands in the same slice;
- when accepting the first subset, require strategy mode and reuse the current
  side-effect restrictions for strategy order calls;
- keep `strategy.order()` rejected until generic netting semantics are designed;
- keep custom OCA settings, `close_entries_rule`, and risk-rule interactions
  rejected unless their behavior is designed in separate slices.

Diagnostic wording should name the still-supported direction or the unsupported
short/reversal boundary. Existing short-entry fixtures should be updated only
when positive behavior exists.

## Broker Accounting Policy

Short support must make the broker direction-aware before it changes semantics:

- store every open trade with an explicit long/short side;
- derive aggregate position size as positive for net long, negative for net
  short, and zero when flat;
- calculate average price only across the current net-position side;
- make realized PnL sign-correct for both long exits and short covers;
- keep commissions and slippage applied through the same supported fill-price
  pipeline;
- update max-held long, max-held short, and max-held all independently;
- keep cancellation and pending-entry books side-aware.

Automatic reversal should be modeled as a close of the existing opposite net
position followed by a new entry for the requested side. The implementation must
define whether that produces one or multiple public order/trade records before
fixtures are accepted.

## Exit And Reservation Policy

Do not let existing long-exit support implicitly apply to shorts. A positive
short-entry slice must either:

- keep `strategy.exit`, `strategy.close`, and `strategy.close_all` short
  interactions rejected or no-op with explicit fixture coverage; or
- implement one narrow short close/exit subset with matching reservation,
  trigger, slippage, and public-order fixtures.

Reservation ledgers must be side-aware before multiple short exits or mixed
long/short reversal cases are accepted.

## Margin And Account Policy

`margin_short` currently has declaration storage but no short-margin runtime
behavior. Short-entry support must define:

- whether the first short subset runs with no margin checks or requires active
  `margin_short`;
- how short affordability, capital held, equity, and liquidation inputs are
  calculated;
- whether `strategy.margin_liquidation_price` remains unsupported;
- how symbol precision and rounding stay outside the first subset.

Long-margin behavior must remain unchanged.

## History, Incremental, And Realtime Policy

Every positive short/reversal behavior must have deterministic coverage across:

- historical execution;
- incremental append parity;
- forming-bar rollback if the behavior can execute in realtime paths;
- branch, switch, loop, and UDF callsite interactions where strategy order
  calls are already allowed;
- history reads of script-visible strategy variables affected by short state.

Runtime guardrails must continue to prevent unbounded order, trade, reservation,
or ledger growth.

## Deferred Variants

Keep these variants unsupported until separately designed and fixture-backed:

- generic `strategy.order()` netting;
- short limit, stop, and stop-limit entries if the first positive slice is
  market-only;
- mixed pending long and short entries;
- `close_entries_rule="ANY"`;
- custom OCA behavior;
- `strategy.risk.*` entry-direction rules;
- public pending-order or open-trade ledger schema expansion;
- external order-fill alert delivery;
- short margin liquidation and `strategy.margin_liquidation_price`;
- currency conversion, symbol precision rounding, and exchange-specific account
  rules.

## Suggested Slice Order

1. Boundary lock: assert current `strategy.short` entry rejection, generic
   `strategy.order()` rejection, and long-only max-short state behavior.
2. Internal model audit: identify broker, ledger, pending-entry, pending-exit,
   and public mirror fields that must become side-aware.
3. Market short entry runtime: accept one explicit-quantity market short entry
   without reversal, with aggregate position and max-held-short fixtures.
4. Short close-all or close-by-id subset: close the first supported short
   exposure and prove realized PnL.
5. Automatic reversal: close current opposite exposure and open the requested
   side under one deterministic historical-bar rule.
6. Host parity and conformance synchronization after the positive subset is
   fixture-backed.

Each behavior slice must update `tests/fixtures/conformance.tsv`,
`tests/snapshots/matrix.json` if matrix output changes, public host snapshots
when runtime output changes, relevant strategy docs, and release notes in the
same slice.
