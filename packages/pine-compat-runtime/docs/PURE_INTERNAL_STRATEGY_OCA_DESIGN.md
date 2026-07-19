# Pure Internal Strategy OCA Design Gate

Status: closed as a documentation-only design gate. This slice does not change
syntax acceptance, semantic analysis, runtime behavior, conformance status,
snapshots, matrix output, or public strategy output.

This document defines the internal path for future strategy OCA support. It is
scoped to analyzer acceptance, `strategy.oca.*` constants, `oca_name` and OCA
type arguments, pending-order grouping, reservation interaction, cancellation,
generic order interaction, fixtures, and conformance. It does not cover real
broker connectivity, external alert delivery, chart UI, hosted order books, or
public pending-order schema unless a later slice explicitly designs that schema.

## Current Boundary

The current subset exposes OCA constants as string values:

```pine
//@version=5
strategy("OCA constants")
plot(strategy.oca.cancel == "strategy.oca.cancel" ? 1 : 0)
```

Custom OCA parameters remain unsupported on order commands:

```pine
//@version=5
strategy("Unsupported strategy exit OCA name")
strategy.exit("XL", "L", stop=low, oca_name="group")
```

Current evidence:

- `docs/PURE_INTERNAL_ROADMAP.md` lists custom OCA behavior across order
  families as remaining strategy broker/account work.
- `tests/fixtures/conformance.tsv` marks `strategy constants` supported for
  direct `strategy.oca.cancel`, `strategy.oca.none`, and
  `strategy.oca.reduce` string constants while documenting that OCA order
  behavior remains unsupported.
- `tests/fixtures/conformance.tsv` and `tests/snapshots/matrix.json` keep
  custom OCA parameters under the unsupported `strategy.*` boundary.
- `tests/fixtures/sema/unsupported_strategy_exit_oca_name.pine` and
  `crates/pine-sema/tests/fixtures.rs::reports_unsupported_strategy_exit_variant_fixtures`
  keep the `oca_name` diagnostic boundary in place.
- `docs/STRATEGY_INTERNAL_GAP_AUDIT.md` records OCA groups and reservation
  semantics as large work that should wait for generic pending-order state.
- `docs/STRATEGY_INTERNAL_ORDER_METADATA_PLAN.md` explicitly excludes custom
  OCA behavior from the current order metadata slices.
- `docs/PURE_INTERNAL_STRATEGY_ORDER_DESIGN.md` requires OCA behavior to be
  designed across generic orders before custom OCA names are accepted.
- `crates/pine-builtins/src/constants/strings.rs` exposes OCA constants, while
  `crates/pine-sema/src/analyzer/strategy.rs` classifies `oca_name` as an
  unsupported strategy-exit option.

Do not accept `oca_name`, OCA type arguments, or custom OCA behavior until a
runtime slice implements the behavior and updates fixtures, conformance,
snapshots, docs, and host parity together.

## Target Shape

OCA support must be modeled as pending-order group behavior, not as inert
metadata:

- `strategy.oca.cancel` cancels peer orders in the same group after one order
  fills;
- `strategy.oca.reduce` reduces peer order quantities after a partial or full
  fill;
- `strategy.oca.none` keeps otherwise grouped orders independent;
- `oca_name` identifies the group within the current script execution context;
- behavior is deterministic when multiple same-group orders become eligible on
  the same historical fill pass.

The first positive subset should be narrower than full OCA parity. A reasonable
first target is internal-only OCA handling for one existing supported long
strategy-exit reservation family, with no public pending-order output and no
generic `strategy.order()` participation.

## Analyzer Policy

Initial analyzer policy for a future positive slice:

- keep OCA constants accepted as ordinary string constants;
- keep `oca_name` rejected until runtime group behavior lands in the same slice;
- accept only const/string-compatible OCA names in the first positive subset;
- accept only OCA type values whose runtime behavior is implemented in that
  slice;
- keep OCA arguments rejected on unsupported order commands or unsupported
  trigger shapes;
- do not accept OCA parameters as passive metadata.

Existing unsupported fixtures should remain until positive behavior exists. A
future slice should split focused fixtures for supported OCA behavior and still
unsupported OCA variants.

## Runtime Policy

OCA behavior needs a side-effecting internal group model:

- pending entries, exits, and future generic orders need stable group keys;
- group operations must update pending-order state, reservations, and deferred
  exit templates together;
- cancellation and reduction must be deterministic when multiple orders share an
  id, group, or entry target;
- quantity reductions must respect existing fixed-quantity and qty-percent
  reservation rules;
- fills that trigger OCA changes must keep current public order/trade output
  shape unless a schema slice deliberately exposes group state.

The current exit reservation model can be reused only after it is explicit about
which pending exits are group peers and how peer reductions interact with
already reserved quantities.

## Deferred Variants

Keep these variants unsupported until separately designed and fixture-backed:

- OCA across generic `strategy.order()` calls;
- OCA across mixed entries, exits, and generic orders;
- OCA with short exposure or automatic reversal;
- OCA with `close_entries_rule="ANY"`;
- OCA behavior in realtime tick recalculation or order-on-close modes;
- public pending-order, reservation, or OCA-group schema expansion;
- external order-fill alert delivery.

## Suggested Slice Order

1. Boundary lock: keep `oca_name` rejected and OCA constants accepted as pure
   constants.
2. OCA state audit: identify pending entry, pending exit, reservation, and
   cancellation storage that must carry group state.
3. One-family OCA cancel: implement one long-only supported exit reservation
   shape with `strategy.oca.cancel`.
4. One-family OCA reduce: add deterministic peer quantity reduction after the
   cancel subset is stable.
5. Cross-family OCA: widen only after generic pending-order state exists.
6. Host parity and conformance synchronization after the positive subset is
   fixture-backed.

Each behavior slice must update `tests/fixtures/conformance.tsv`,
`tests/snapshots/matrix.json` if matrix output changes, public host snapshots
when runtime output changes, relevant strategy docs, and release notes in the
same slice.
