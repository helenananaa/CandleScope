# Strategy Internal Stage 10 Active-Entry Bracket Plan

Status: closed on 2026-06-05. See
`docs/STRATEGY_INTERNAL_STAGE10_ACTIVE_ENTRY_BRACKET_AUDIT.md`.

Stage 10 targets the next official Pine strategy gap after the Stage 9
single-trigger active-entry closeout: same-calculation `strategy.exit` bracket
attachment against a matching active pending long entry when one bracket leg is
entry-relative.

Primary official reference:

- TradingView Pine Script strategies, `strategy.exit()` behavior:
  https://www.tradingview.com/pine-script-docs/concepts/strategies/

Relevant official rules:

- a `strategy.exit()` call can create a take-profit plus stop-loss bracket;
- when both absolute and relative alternatives define the same take-profit or
  stop-loss side, Pine creates the order expected to trigger first;
- when a `from_entry` id does not match an entry, no exit orders are created;
- if one `strategy.exit()` call creates multiple order types, only the first
  triggered one fills and the others are cancelled;
- multiple `strategy.exit()` calls reserve portions of the open position, and
  `qty` takes precedence over `qty_percent`.

## Starting Point

The current repo baseline is:

- Stage 9 supports same-calculation active-entry single-trigger attachment for
  `profit`, `loss`, and `trail_points + trail_offset`.
- Absolute same-calculation active-entry attachment already supports
  single-trigger `stop`, `limit`, and `trail_price`.
- Existing current-position brackets support exactly one downside leg plus one
  upside leg:
  - `stop + limit`;
  - `stop + profit`;
  - `loss + limit`;
  - `loss + profit`.
- Existing same-side pairs (`stop + loss`, `limit + profit`), 3+ triggers, and
  invalid trailing combinations remain unsupported.
- `PendingExitTrigger::Bracket { downside, upside }` already represents the
  resolved executable bracket.
- `DeferredRelativeExitTrigger` currently stores only one relative trigger at a
  time: `ProfitTicks`, `LossTicks`, or `TrailPoints`.

## Compatibility Boundary

Stage 10 may support only this first active-entry bracket subset:

- long-only strategy mode;
- one active pending entry id matching `from_entry`;
- no pyramiding, shorts, reversals, or generic `strategy.order()`;
- one resolved downside leg plus one resolved upside leg;
- current public `StrategyResult` schema only;
- existing `qty` and `qty_percent` placement-time rules against the matching
  pending entry quantity;
- existing bracket fill semantics after resolution: later-bar eligibility,
  downside-first when both legs are touched on one eligible bar, and one public
  exit order plus one closed trade per fill.

Stage 10 must not add:

- arbitrary future binding for unmatched missing-entry exits;
- public pending-order, bracket-leg, reservation, or OCA output fields;
- same-side pairs, 3+ triggers, or trailing-plus-bracket combinations;
- multiple active entries, pyramiding, shorts, reversals, or per-entry public
  trade ledgers;
- `strategy.exit()` persistence for missing `from_entry`;
- `trail_price + trail_points` precedence changes.

## Target Bracket Forms

The first positive Stage 10 behavior should support exactly these
same-calculation active-entry forms:

- `strategy.exit(..., stop=..., profit=...)`
  - downside is absolute and known at placement;
  - upside is deferred until the entry fill price is known.
- `strategy.exit(..., loss=..., limit=...)`
  - downside is deferred until the entry fill price is known;
  - upside is absolute and known at placement.
- `strategy.exit(..., loss=..., profit=...)`
  - both sides are deferred until the entry fill price is known.

`strategy.exit(..., stop=..., limit=...)` is already covered by the existing
absolute active-entry attachment path and should remain a regression fixture,
not the first Stage 10 runtime widening target.

## Design Requirement

Active-entry relative bracket attachment cannot resolve all prices at placement
time because the pending entry has not filled yet. The broker needs an internal
deferred bracket representation that can carry one already-resolved absolute
leg plus one or two relative tick legs until the matching entry fills.

Use an internal resolved-side model rather than encoding each public parameter
combination separately:

```text
DeferredBracketLeg::Absolute(price)
DeferredBracketLeg::RelativeProfit { ticks, mintick }
DeferredBracketLeg::RelativeLoss { ticks, mintick }

DeferredRelativeExitTrigger::Bracket {
    downside: DeferredBracketLeg,
    upside: DeferredBracketLeg,
}
```

Fill-time resolution for the current long-only subset:

- `RelativeProfit` resolves to `entry_fill_price + ticks * mintick`;
- `RelativeLoss` resolves to `entry_fill_price - ticks * mintick`;
- absolute `stop` and `limit` legs keep their placement-time price;
- after both legs resolve, place the normal
  `PendingExitTrigger::Bracket { downside, upside }` with the original
  `last_update_bar_index`.

The resolved bracket must keep current timing behavior. A bracket attached in
the same calculation as the entry must not fill before the entry itself fills,
and after resolution it must use the existing pending-exit later-bar
eligibility and same-bar downside-first policy.

## Slice Plan

### Slice 0: Design Gate

Status: this document. This slice does not add runtime behavior, widen
conformance, or update matrix support claims.

Goal:

- define the Stage 10 bracket-specific boundary, official rule dependency, and
  implementation order before changing code.

Acceptance:

- current repo baseline is documented;
- supported and unsupported Stage 10 forms are explicit;
- implementation ownership stays in broker/runtime built-ins, not Python or
  WASM wrappers;
- no runtime fixtures, snapshots, or conformance rows change.

### Slice 1: Boundary Lock

Status: Closed on 2026-06-05. This slice added runtime boundary tests only and
did not widen behavior, conformance, matrix, or public output.

Goal:

- add broker and/or runtime tests proving active-entry relative bracket forms
  remain unsupported before behavior routing changes.

Closed evidence:

- `crates/pine-runtime/src/tests/strategy.rs` now proves `stop + profit`,
  `loss + limit`, and `loss + profit` active-entry bracket calls still allow
  the matching pending entry to fill but do not create public exit orders or
  trades;
- the current runtime boundary remains an `E_STRATEGY_EXIT_ENTRY` diagnostic
  for those active-entry relative bracket forms;
- no runtime fixtures, golden snapshots, conformance rows, matrix support
  claims, Python tests, or WASM tests changed.

Acceptance:

- `stop + profit`, `loss + limit`, and `loss + profit` active-entry bracket
  calls still produce no public exit orders in the current baseline;
- same-side and 3+ trigger forms remain rejected by existing semantic
  diagnostics;
- no support claims widen.

### Slice 2: Deferred Bracket Storage

Status: Closed on 2026-06-05 as an internal storage skeleton. This slice does
not route runtime `strategy.exit` calls into deferred bracket storage and does
not resolve deferred brackets after entry fills.

Goal:

- extend the internal deferred relative exit representation so it can store a
  one-downside/one-upside bracket intent without routing runtime calls into it.

Closed evidence:

- added internal `DeferredBracketLeg` plus
  `DeferredRelativeExitTrigger::Bracket { downside, upside }`;
- kept `resolve_deferred_relative_exits_for_entry` explicit about not resolving
  bracket intent yet;
- added broker order-book tests for bracket deferred-intent replacement,
  lookup, take-by-entry, cancel-by-id, clear-by-entry, and clear-all behavior;
- no runtime dispatch, fixtures, snapshots, conformance rows, matrix support
  claims, Python tests, or WASM tests changed.

Acceptance:

- `PendingExitBook` can replace, append, and clear deferred bracket intent by
  id/from_entry using the same identity rules as existing deferred relative
  exits;
- fill-time cleanup for cancelled/rejected pending entries clears deferred
  bracket intent;
- no runtime behavior or public output changes.

### Slice 3: `stop + profit` Active-Entry Bracket

Status: Closed on 2026-06-05. This slice widens the active-entry bracket subset
only for absolute downside plus deferred entry-relative upside.

Goal:

- support the smallest mixed bracket: absolute downside plus deferred
  entry-relative upside.

Closed evidence:

- added broker placement and fill-time resolution for
  `strategy.exit(..., stop=..., profit=...)` targeting the matching active
  pending long entry;
- profit ticks resolve from the actual entry fill price before placing the
  existing `PendingExitTrigger::Bracket { downside, upside }`;
- added runtime fixture `strategy_exit_active_entry_stop_profit_bracket.pine`
  plus CLI golden, Python, WASM, incremental, conformance, matrix, docs, and
  release-note coverage;
- existing mixed-pair fixture now demonstrates supported active-entry
  `stop + profit` while `loss + limit` still remained unsupported at Slice 3
  close;
- `loss + limit` and `loss + profit` active-entry bracket forms remained
  explicitly guarded for later slices.

Acceptance:

- placement validates the absolute stop, profit ticks, mintick, and quantity
  against the matching pending entry quantity;
- after entry fill, profit resolves from actual entry fill price and the broker
  places the existing bracket trigger;
- CLI golden, Python, WASM, incremental, conformance, matrix, docs, and release
  notes cover one representative fixture;
- at Slice 3 close, `loss + limit` and `loss + profit` remained unsupported
  until later slices.

### Slice 4: `loss + limit` Active-Entry Bracket

Status: Closed on 2026-06-05. This slice widens the active-entry bracket subset
only for deferred entry-relative downside plus absolute upside.

Goal:

- support deferred entry-relative downside plus absolute upside.

Closed evidence:

- added broker placement and fill-time resolution for
  `strategy.exit(..., loss=..., limit=...)` targeting the matching active
  pending long entry;
- loss ticks resolve from the actual entry fill price before placing the
  existing `PendingExitTrigger::Bracket { downside, upside }`;
- added runtime fixture `strategy_exit_active_entry_loss_limit_bracket.pine`
  plus CLI golden, Python, WASM, incremental, conformance, matrix, docs, and
  release-note coverage;
- `loss + profit` remained explicitly guarded for a later slice.

Acceptance:

- loss resolves from actual entry fill price after the pending entry fills;
- existing bracket both-hit and later-bar rules apply after resolution;
- fixed `qty` and `qty_percent` evidence covers pending-entry quantity
  validation if not already covered by Slice 3;
- host parity and conformance update in the same slice.

### Slice 5: `loss + profit` Active-Entry Bracket

Status: Closed on 2026-06-05. This slice completes the planned Stage 10
active-entry relative bracket behavior forms.

Goal:

- support the fully deferred relative bracket where both legs resolve from the
  eventual entry fill price.

Closed evidence:

- added broker placement and fill-time resolution for
  `strategy.exit(..., loss=..., profit=...)` targeting the matching active
  pending long entry;
- both loss and profit ticks resolve from the actual entry fill price before
  placing the existing `PendingExitTrigger::Bracket { downside, upside }`;
- invalid one-leg resolution rejects the whole deferred bracket path instead of
  downgrading to a single-trigger exit;
- added runtime fixture `strategy_exit_active_entry_loss_profit_bracket.pine`
  plus CLI golden, Python, WASM, incremental, conformance, matrix, docs, and
  release-note coverage.

Acceptance:

- both relative legs resolve atomically after entry fill;
- invalid one-leg resolution rejects the whole bracket and does not silently
  downgrade to a single-trigger exit;
- public output remains identical in shape across CLI, Python, and WASM;
- same-side pairs, 3+ triggers, missing-entry future binding, and unsupported
  broker families remain unsupported.

### Slice 6: Closeout Audit

Status: Closed on 2026-06-05. This slice did not widen runtime behavior or
public output; it synchronized the Stage 10 closeout audit and stage status.

Goal:

- close Stage 10 with synchronized docs, conformance, matrix, host parity, and
  audit evidence.

Closed evidence:

- added `docs/STRATEGY_INTERNAL_STAGE10_ACTIVE_ENTRY_BRACKET_AUDIT.md`;
- confirmed the completed `stop + profit`, `loss + limit`, and `loss + profit`
  active-entry relative bracket subset;
- recorded still-unsupported same-side pairs, 3+ triggers,
  trailing-plus-bracket forms, missing-entry future binding, broader broker
  families, and public schema expansion;
- left runtime behavior, fixtures, snapshots, conformance, matrix, Python, and
  WASM output unchanged from Slice 5.

Acceptance:

- a Stage 10 audit lists completed forms, still-unsupported forms, and next
  direction boundaries;
- `tests/fixtures/conformance.tsv` precisely names the supported active-entry
  bracket subset;
- `scripts/verify.sh` passes before commit.

## Verification Plan

Each behavior slice should run:

```text
cargo fmt
cargo test -p pine-runtime strategy --quiet
cargo test -p pine-runtime --test incremental --quiet
cargo test -p pine-sema strategy --quiet
cargo test -p pine-cli runtime_outputs_match_golden_snapshots --quiet
cargo test -p pine-cli matrix_output_matches_golden_snapshot --quiet
cargo test -p pine-cli conformance --quiet
cargo test -p pine-wasm strategy --quiet
python3 -m pytest python/tests -q
python3 scripts/check_structure.py
```

Before final closeout, run:

```text
scripts/verify.sh
```

Stop if official parity requires multiple open trades, short exposure,
pyramiding, generic `strategy.order()`, public schema changes, or a host-data
dependency that is not available in repo fixtures.
