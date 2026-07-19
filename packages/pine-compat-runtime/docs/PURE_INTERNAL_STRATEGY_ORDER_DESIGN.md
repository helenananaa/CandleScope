# Pure Internal Strategy Order Design Gate

Status: active reference document for fixture-backed `strategy.order()` slices.
The original design-gate slice was documentation-only; later slices update this
boundary as syntax, runtime behavior, conformance, and matrix evidence widen.

This document defines the internal path for future `strategy.order()` support.
It is scoped to analyzer acceptance, generic order netting, pending-order
storage, cancellation, OCA interaction, strategy metadata, broker accounting,
script-visible strategy variables, runtime guardrails, fixtures, and
conformance. It does not cover real broker connectivity, external alert
delivery, chart UI, hosted order books, or host-service behavior.

## Current Boundary

The current strategy order subset accepts dedicated commands plus the first
fixture-backed generic order forms:

```pine
//@version=5
strategy("Current order subset")
strategy.entry("L", strategy.long, qty=1)
strategy.order("O", strategy.long, qty=1)
strategy.order("D", strategy.long)
strategy.order("L", strategy.long, qty=1, limit=close)
strategy.order("S", strategy.long, qty=1, stop=close)
strategy.order("SL", strategy.long, qty=1, stop=close, limit=close)
strategy.order("R", strategy.short, qty=1)
strategy.order("M", strategy.long, qty=1, comment="order", alert_message="fill")
```

The supported generic forms are market-long add/increase with explicit quantity
or the configured default quantity, limit-long add/increase through the
supported long limit timing model, stop-long add/increase through the supported
long stop timing model, stop-limit-long add/increase through the supported long
stop-limit timing model, and explicit-quantity reduce-only market-short long
reduction. Unsupported variants still include omitted quantity for
`strategy.short`, short exposure, reversal, short price-based orders, and OCA.

Unsupported examples include:

```pine
//@version=5
strategy("Unsupported strategy order")
strategy.order("MissingShortQty", strategy.short)
strategy.order("ShortStopLimit", strategy.short, qty=1, limit=close, stop=close)
strategy.order("ShortLimit", strategy.short, qty=1, limit=close)
```

Current evidence:

- `docs/PURE_INTERNAL_ROADMAP.md` lists generic `strategy.order()` as remaining
  strategy broker/account work, but the support matrix now splits out the first
  positive subset.
- `tests/fixtures/conformance.tsv` records the market-long, limit-long,
  stop-long, stop-limit-long, long default-quantity, and explicit-quantity
  reduce-only market-short generic order subset under `strategy.order`.
- `tests/snapshots/matrix.json` mirrors that partial `strategy.order` matrix
  row.
- `tests/fixtures/sema/unsupported_strategy_orders.pine` and
  `crates/pine-sema/tests/fixtures.rs::reports_unsupported_strategy_order_fixture`
  keep the remaining diagnostic boundary in place.
- `docs/STRATEGY_INTERNAL_GAP_AUDIT.md` records generic orders as large
  foundation work because they need short/reversal/netting semantics and a
  richer pending-order book.
- `docs/STRATEGY_INTERNAL_STAGE13_MULTI_ENTRY_LEDGER_PLAN.md` closed the
  current long-only multi-entry ledger while explicitly excluding
  `strategy.order()`.
- `tests/fixtures/runtime/strategy_order_metadata.pine` and
  `tests/fixtures/sema/supported_strategy_order_metadata.pine` cover metadata
  on the supported `strategy.order()` subset; metadata still does not imply
  support for otherwise unsupported generic order forms.
- `crates/pine-sema/src/analyzer/unsupported.rs` still reports the broad
  strategy unsupported reason for unsupported strategy order families.

Do not widen `strategy.order()` beyond the fixture-backed subset until a runtime
slice implements the behavior and updates fixtures, conformance, snapshots,
docs, and host parity together.

## Target Shape

`strategy.order()` must be treated as a generic netting command, not as an alias
for `strategy.entry()`:

- it can increase, reduce, close, or reverse the current net position depending
  on direction, current exposure, and quantity;
- it is not governed by `pyramiding` in the same way as `strategy.entry()`;
- it must share the same pending market/limit/stop/stop-limit timing model as
  other supported strategy order commands;
- it must interact with cancellation, OCA groups, metadata, slippage,
  commission, limit verification, margin, and script-visible strategy state
  through explicit broker rules;
- it must preserve the current public strategy output shape unless a separate
  schema slice deliberately changes it.

The first positive subset should be smaller than full strategy parity. A
reasonable first target is explicit-quantity, market-only, long-direction
`strategy.order()` in a flat or long-only account, with short direction,
reversal, price-based forms, and OCA still rejected.

## Analyzer Policy

Initial analyzer policy for a future positive slice:

- keep `strategy.order()` rejected until runtime behavior lands in the same
  slice;
- when accepting the first subset, require strategy mode and reuse the current
  side-effect restrictions for strategy order calls;
- require `id` and `direction` arguments before any optional order parameters;
- accept only direction values whose runtime behavior is implemented in that
  slice;
- keep unsupported order arguments rejected with stable diagnostics rather than
  storing inert syntax.

Metadata arguments must follow `docs/STRATEGY_INTERNAL_ORDER_METADATA_PLAN.md`
only after the order command itself is behavior-backed. Metadata must not make
an otherwise unsupported `strategy.order()` call acceptable.

## Broker And Netting Policy

The broker must define `strategy.order()` in terms of net-position transitions:

- same-side orders increase net exposure unless a quantity or risk rule prevents
  the fill;
- opposite-side orders reduce current exposure first;
- quantities larger than the opposite exposure may reverse only after reversal
  behavior is designed and fixture-backed;
- realized PnL, commissions, slippage, average price, and max-held fields must
  be updated through one deterministic fill path;
- pending generic orders must be distinguishable from pending entries and exits
  while sharing cancellation infrastructure where possible.

Do not route generic orders through the current `strategy.entry()` long-only
pyramiding path. Generic order behavior must be owned by a side-aware broker
netting model.

## Cancellation And OCA Policy

Generic orders need a richer pending-order book before broad support:

- `strategy.cancel(id)` must define whether it cancels entries, exits, generic
  orders, or all matching pending order families;
- `strategy.cancel_all()` must define family ordering and whether it clears
  reservations, OCA groups, and deferred exits;
- OCA behavior must define cancel, reduce, and none semantics across generic
  orders before custom OCA names are accepted;
- reservation and reduction behavior must stay internal until public schema is
  designed.

Existing supported cancellation behavior for entries and exits must remain
unchanged for scripts that do not use `strategy.order()`.

## Deferred Variants

Keep these variants unsupported until separately designed and fixture-backed:

- short-direction generic orders;
- automatic reversal through generic orders;
- short price-based generic orders;
- mixed pending entries, exits, and generic orders with the same id;
- `close_entries_rule` interaction;
- custom OCA behavior;
- margin-short behavior and `strategy.margin_liquidation_price`;
- `strategy.risk.*` interactions;
- public pending-order or reservation schema expansion;
- external order-fill alert delivery;
- realtime tick recalculation, order-on-close, and bar magnifier behavior.

## Suggested Slice Order

1. Boundary lock: assert current `strategy.order()` rejection and cancellation
   boundaries across sema and analyze output.
2. Pending-order model audit: identify entry, exit, generic order,
   cancellation, reservation, and OCA storage that must share an id lookup
   model.
3. Market long generic order: accept explicit-quantity and configured-default
   quantity market long `strategy.order()` in flat/long-only cases without
   reversal.
4. Reduce-only opposite generic order: define whether a long-position
   short-direction generic order can reduce without reversing.
5. Price-based generic orders: add short-side price-based timing only after
   short exposure and reversal are designed.
6. Cancellation and OCA: widen cancellation and OCA behavior only after generic
   pending-order state exists.
7. Host parity and conformance synchronization after the positive subset is
   fixture-backed.

Each behavior slice must update `tests/fixtures/conformance.tsv`,
`tests/snapshots/matrix.json` if matrix output changes, public host snapshots
when runtime output changes, relevant strategy docs, and release notes in the
same slice.
