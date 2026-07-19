# Strategy Internal Stage 9 Entry-Relative Exit Plan

Status: closed on 2026-06-04. Same-calculation
`strategy.exit(..., profit=...)`, `strategy.exit(..., loss=...)`, and
`strategy.exit(..., trail_points=..., trail_offset=...)` can now attach to a
matching active pending long entry. See
`docs/STRATEGY_INTERNAL_STAGE9_ENTRY_RELATIVE_EXIT_AUDIT.md` for closeout
evidence and remaining unsupported boundaries. Do not widen relative-leg
active-entry brackets until a later slice adds fixture-backed behavior,
conformance metadata, host snapshots, and release verification.

Stage 9 targets the remaining same-calculation active-entry attachment gap for
entry-relative `strategy.exit` triggers:

- `profit`;
- `loss`;
- `trail_points` when paired with `trail_offset`.

This stage is not a generic missing-entry binding feature. It is only about an
exit call that targets an active pending `strategy.entry` order with the same
`from_entry` id before that entry fills.

Primary official reference:

- TradingView Pine Script strategies, `strategy.exit()` behavior:
  https://www.tradingview.com/pine-script-docs/concepts/strategies/

The official strategy manual establishes the relevant rules:

- `strategy.exit` can be called in the same block as `strategy.entry` for a
  matching entry id;
- `from_entry` limits exit orders to matching entries, and a non-matching id
  creates no exit orders;
- `profit` and `loss` are entry-relative tick distances that compete with
  absolute `limit` and `stop` levels respectively;
- `trail_points` is an entry-relative tick distance used to compute trailing
  activation, and `trail_offset` is required for trailing stops.

## Starting Point

The current repo baseline is:

- `strategy.entry` supports current long market, limit, stop, and stop-limit
  orders without pyramiding, shorts, or reversals.
- `strategy.exit` supports current single-trigger, one-downside/one-upside
  bracket, trailing, explicit `qty`, `qty_percent`, and reservation subsets for
  the active one-net-long position.
- Same-calculation active-entry attachment is already supported for absolute
  `stop`, `limit`, and `trail_price` against a matching active pending entry.
- Same-calculation active-entry attachment using entry-relative `profit`,
  `loss`, and `trail_points + trail_offset` is supported for a matching active
  pending long entry.
- Missing-entry exits that do not target an active pending entry or current
  open position must remain unsupported/no-op according to the current
  documented boundary.
- Public output remains the existing `StrategyResult` shape with `orders`,
  `trades`, `position`, `equity`, and `diagnostics`.

## Compatibility Boundary

Stage 9 supports only this first subset:

- long-only strategy mode;
- one active pending entry id matching `from_entry`;
- current one-net-long broker with no pyramiding;
- `profit` active-entry attachment resolved from the eventual entry fill price;
- `loss` active-entry attachment resolved from the eventual entry fill price;
- `trail_points + trail_offset` active-entry attachment resolved from the
  eventual entry fill price;
- existing `qty` and `qty_percent` quantity resolution rules for matching
  active pending entries;
- existing public order, trade, position, equity, and diagnostic schema.

Stage 9 must not add:

- arbitrary future binding for unmatched missing-entry exits;
- short entries, reversals, or pyramiding;
- generic `strategy.order()`;
- public pending-order output;
- `trail_price + trail_points` precedence changes beyond the current supported
  trailing subset;
- lower-timeframe, tick-by-tick, bar magnifier, or recalculation-on-fill
  behavior.

## Design Requirement

Entry-relative pending-entry exits cannot use `strategy.position_avg_price` at
placement time because the active entry has not filled yet. The broker needs an
internal deferred trigger representation that stores the relative tick intent
and resolves it after the entry fill price is known.

For the current long-only subset:

- `profit` resolves to a take-profit limit price at
  `entry_fill_price + profit * syminfo.mintick`;
- `loss` resolves to a stop-loss price at
  `entry_fill_price - loss * syminfo.mintick`;
- `trail_points` resolves to a trailing activation price at
  `entry_fill_price + trail_points * syminfo.mintick`;
- `trail_offset` remains the trailing stop offset in ticks.

The resolved exit must keep the current same-bar rule: an active-entry
attachment created in the same calculation as the entry must not fill before
the entry itself fills.

## Slice Plan

### Slice 0: Design Gate

Status: closed on 2026-06-04 as this document. This slice does not add runtime
behavior, widen conformance, or change public output.

Goal:

- pick the next official Pine compatibility subset after Stage 8 and define a
  safe implementation boundary.

Acceptance:

- current repo boundary is documented;
- official behavior dependency is documented;
- implementation slices are ordered from smallest to highest risk;
- no conformance row changes;
- no public schema changes.

### Slice 1: Current Boundary Lock

Status: closed on 2026-06-04 as a broker boundary-lock slice. This slice does
not add runtime support, widen conformance, or change public output.

Goal:

- add or refresh focused fixtures that prove `profit`, `loss`, and
  `trail_points` active-entry attachment remain unsupported before behavior is
  widened.

Implemented:

- added broker coverage proving `profit`, `loss`, and
  `trail_points + trail_offset` active-entry attachment is still rejected for
  current long market, limit, stop, and stop-limit pending entries;
- kept the pending entry intact after each rejected attachment attempt;
- kept pending exits empty and diagnostics on the existing
  `E_STRATEGY_EXIT_ENTRY` boundary;
- made no analyzer, runtime fixture, conformance, matrix, or public schema
  changes.

Acceptance:

- current unsupported boundary is explicit for all current pending entry
  families;
- no conformance row changes;
- no public schema changes.

Stop condition:

- stop before accepting `profit`, `loss`, or `trail_points` active-entry
  attachment without deferred trigger storage and fixture-backed runtime
  evidence.

Original implementation notes:

- prefer runtime or broker tests that target same-calculation pending-entry
  attachment directly;
- keep current public output unchanged;
- do not change analyzer acceptance unless the current fixture boundary is
  stale.

### Slice 2: Deferred Relative Trigger Skeleton

Status: closed on 2026-06-04 as an internal storage skeleton. This slice does
not route analyzer or runtime `strategy.exit` calls into deferred triggers,
does not fill new exits, does not widen conformance, and does not change public
output.

Goal:

- add internal deferred trigger data for active pending-entry exits without
  filling new exits yet.

Implemented:

- added `DeferredRelativeExitTrigger` for `profit`, `loss`, and
  `trail_points + trail_offset` entry-relative trigger intent;
- added `DeferredRelativeExit` to store id, `from_entry`, deferred trigger,
  unresolved quantity request, and update bar;
- added internal `PendingExitBook` storage for deferred relative exits separate
  from the existing resolved pending-exit list;
- made order-book clear/cancel paths clear deferred relative exits as well;
- added broker tests for storing all deferred trigger shapes, replacing a
  matching identity, preserving distinct `from_entry` identities, clearing by
  entry, canceling by id, and clearing all.

Acceptance:

- existing `pending_exit_count()` and fill evaluation still ignore deferred
  relative exits;
- current `profit`, `loss`, and `trail_points` active-entry attachment remains
  unsupported through existing runtime paths;
- no conformance row changes;
- no public schema changes.

Stop condition:

- stop before resolving or filling deferred relative exits from entry fills
  without runtime fixtures and host parity evidence.

Original implementation notes:

- store relative trigger intent in broker/order-book structures;
- keep absolute `stop`, `limit`, and `trail_price` behavior unchanged;
- add broker unit tests for storing, replacing, and clearing deferred relative
  attachments.

### Slice 3: `profit` Active-Entry Attachment

Status: Closed on 2026-06-04.

Goal:

- support same-calculation `strategy.exit(..., profit=...)` for the current
  active pending long entry subset.

Closed evidence:

- added deferred `profit` routing from `strategy.exit` to the broker when
  `from_entry` matches an active pending long entry;
- resolved the pending take-profit limit from the actual long entry fill price;
- preserved existing `qty` and `qty_percent` validation and reservation
  semantics against the pending entry quantity before price resolution;
- kept active-entry `loss`, `trail_points`, and `stop + profit` bracket
  attachment rejected until later slices;
- added broker tests for deferred storage, fill-time resolution, fixed quantity,
  percent quantity, and the remaining unsupported boundary;
- added `tests/fixtures/runtime/strategy_exit_active_entry_profit_attachment.pine`
  plus CLI golden, Python, WASM, conformance, matrix, and release-note evidence.

Implementation notes:

- resolve the take-profit limit from the actual entry fill price;
- preserve existing `qty` and `qty_percent` active-entry quantity resolution;
- add runtime, incremental, CLI golden, Python, WASM, conformance, docs, and
  release evidence in the same slice.

### Slice 4: `loss` Active-Entry Attachment

Status: Closed on 2026-06-04 for the single-trigger `loss` active-entry
attachment subset.

Goal:

- support same-calculation `strategy.exit(..., loss=...)` for the current
  active pending long entry subset.

Closed evidence:

- added deferred `loss` routing from `strategy.exit` to the broker when
  `from_entry` matches an active pending long entry;
- resolved the pending stop price from the actual long entry fill price;
- preserved existing `qty` and `qty_percent` validation and reservation
  semantics against the pending entry quantity before price resolution;
- kept active-entry `trail_points` and relative-leg bracket attachment
  unsupported until later slices;
- added broker tests for deferred storage, fill-time resolution, fixed quantity,
  percent quantity, and the remaining unsupported `trail_points` boundary;
- added `tests/fixtures/runtime/strategy_exit_active_entry_loss_attachment.pine`
  plus CLI golden, Python, WASM, conformance, matrix, and release-note evidence.

Implementation notes:

- resolve the stop price from the actual entry fill price;
- keep `loss + profit`, `loss + limit`, and `stop + profit` active-entry bracket
  evidence for a later bracket-specific slice;
- keep same-side unsupported combinations unchanged.

### Slice 5: `trail_points` Active-Entry Attachment

Status: Closed on 2026-06-04 for the single trailing
`trail_points + trail_offset` active-entry attachment subset.

Goal:

- support same-calculation
  `strategy.exit(..., trail_points=..., trail_offset=...)` for the current
  active pending long entry subset.

Closed evidence:

- added deferred `trail_points + trail_offset` routing from `strategy.exit` to
  the broker when `from_entry` matches an active pending long entry;
- resolved trailing activation from the actual long entry fill price and
  preserved the tick-distance offset;
- preserved existing `qty` and `qty_percent` validation and reservation
  semantics against the pending entry quantity before price resolution;
- kept active-entry relative-leg brackets and `trail_price + trail_points`
  combinations unsupported until later slices;
- added broker tests for deferred storage, fill-time resolution, activation,
  ratchet/fill, fixed quantity, and percent quantity;
- added
  `tests/fixtures/runtime/strategy_exit_active_entry_trail_points_attachment.pine`
  plus CLI golden, Python, WASM, conformance, matrix, and release-note evidence.

Implementation notes:

- resolve trailing activation from the actual entry fill price;
- preserve current trailing activation-bar behavior;
- do not add `trail_price + trail_points` precedence changes unless a later
  fixture-backed slice explicitly targets that official behavior.

### Slice 6: Host Parity, Conformance, And Audit

Status: Closed on 2026-06-04. See
`docs/STRATEGY_INTERNAL_STAGE9_ENTRY_RELATIVE_EXIT_AUDIT.md`.

Goal:

- close Stage 9 with synchronized host parity, conformance, matrix snapshot,
  docs, release notes, and an audit.

Closed evidence:

- CLI, Python, and WASM expose public strategy output for representative
  `profit`, `loss`, and `trail_points + trail_offset` active-entry fixtures;
- conformance now names the supported single-trigger active-entry subset
  without claiming active-entry relative brackets;
- broader missing-entry, pyramiding, short, reversal, generic-order, public
  pending-order, and active-entry bracket behavior remains unsupported.

Acceptance:

- CLI, Python, and WASM expose identical public strategy output for at least one
  representative active-entry relative-exit fixture;
- `tests/fixtures/conformance.tsv` precisely lists the supported and
  unsupported Stage 9 subset;
- broader missing-entry, pyramiding, short, reversal, and generic-order
  behavior remains unsupported.

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
python3 -m pytest python/tests -q
cargo test -p pine-wasm strategy --quiet
python3 scripts/check_structure.py
```

Before final closeout, run:

```text
scripts/verify.sh
```

Stop if official behavior requires multiple open trades, short exposure,
generic `strategy.order()`, public schema changes, or a host-data dependency
that is not available in the repo fixtures.
