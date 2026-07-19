# Phase X Strategy Exit Bracket Reservation Execution Plan

Status: closed on 2026-06-02. Closeout is recorded in
`docs/PHASE_X_AUDIT.md`. This document is the step-by-step execution playbook
used for the narrow strategy phase after `docs/PHASE_W_AUDIT.md`.

Phase X should extend the Phase W reservation model from explicit fixed `qty`
or `qty_percent` single-trigger exits to explicit fixed `qty` or `qty_percent`
bracket exits. It must not become a trailing-reservation, omitted-quantity
reservation, missing-entry pre-placement, short, pyramiding, public
pending-order, or broker-emulator parity phase.

Every slice should leave the workspace shippable and should keep semantic
claims, broker behavior, public output contracts, fixtures, snapshots, host
bindings, conformance metadata, docs, and release verification in lockstep.

## Current Starting Point

The repository has closed the current strategy progression through Phase W.
The relevant strategy baseline is:

- `tests/fixtures/conformance.tsv` marks `strategy`, `strategy.entry`,
  `strategy.close`, strategy equity, strategy state variables,
  `strategy.closedtrades`, `strategy.opentrades`, and `strategy.exit` as
  `partial`.
- Broad `strategy.*` remains `unsupported`.
- `strategy(...)` supports the fixture-backed declaration subset, including
  positive const numeric `initial_capital` and fixed default quantity settings
  through `default_qty_type=strategy.fixed` plus positive const numeric
  `default_qty_value`.
- `strategy.entry(id, strategy.long, qty=...)` opens one long market position
  at the current bar close, with no pyramiding and no short exposure. If `qty`
  is omitted, the configured fixed default entry quantity is used.
- A repeated `strategy.entry` while a long position is open is ignored under
  the current no-pyramiding rule.
- `strategy.close(id)` closes the full matching long position at the current
  bar close and cancels matching pending exit state.
- Strategy state variables are available in strategy-mode historical scripts:
  `strategy.position_size`, `strategy.position_avg_price`,
  `strategy.openprofit`, `strategy.netprofit`, `strategy.equity`,
  `strategy.closedtrades`, and `strategy.opentrades`.
- Single-trigger `strategy.exit` supports `stop`, `limit`, `profit`, and
  `loss`.
- Bracket `strategy.exit` supports exactly one downside plus one upside leg:
  `stop + limit`, `stop + profit`, `loss + limit`, and `loss + profit`.
- Trailing `strategy.exit` supports exactly `trail_price + trail_offset` and
  `trail_points + trail_offset`.
- Optional fixed `qty` and optional `qty_percent` are supported on each current
  trigger family. They are mutually exclusive, evaluated once at placement
  time, must be finite and positive, resolve to an absolute requested close
  quantity, and fill no more than the current position size.
- Omitted `qty` and omitted `qty_percent` keep the current full-position exit
  behavior through the one-effective-pending replacement path.
- The broker stores one current long position with `position_size`,
  `avg_price`, `entry_id`, `entry_bar_index`, and `entry_time`.
- The broker stores internal pending exits in `PendingExitBook`.
- `PendingExit` carries `id`, `from_entry`, `trigger`, `quantity`,
  `reserved_quantity`, `multiple_reservation`, and `last_update_bar_index`.
- `PendingExitQuantity` is currently `Full | Fixed(f64)`.
- `ExitQuantityRequest` is currently `Full | Fixed(f64) | Percent(f64)`.
- Phase W multiple reservations are supported only for explicit fixed `qty` or
  `qty_percent` single-trigger exits.
- Runtime fill code uses `reserved_quantity` as the fill ceiling and clamps to
  current remaining `position_size`.
- Runtime output remains `schemaVersion: 3`. `StrategyResult`,
  `StrategyOrderEvent`, `StrategyTrade`, `StrategyPositionSnapshot`, and
  `StrategyEquitySnapshot` shapes are unchanged.
- Multiple pending bracket exits, multiple pending trailing exits,
  omitted-quantity multiple exits, missing-entry pre-placement, pyramiding,
  short exposure, reversals, public pending-order records, and strategy order
  families beyond the current subset remain unsupported.

The current broker module layout is:

```text
crates/pine-runtime/src/strategy/
   mod.rs
   broker/
      mod.rs                 pending evaluation + result projection
      exits.rs               pending-exit identity + placement helpers
      fills.rs               fill trade construction + position reduction/reset
      accounting.rs          equity/position/profit/count accessors
      tests.rs               broker unit tests
```

The strategy-focused verification baseline is:

```text
cargo test -p pine-builtins strategy
cargo test -p pine-sema strategy
cargo test -p pine-runtime strategy
cargo test -p pine-runtime --test incremental
cargo test -p pine-runtime --test profile_fixtures
cargo test -p pine-cli strategy
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli matrix
cargo test -p pine-wasm strategy
maturin build --manifest-path crates/pine-python/Cargo.toml --out dist
python3 -m pip install --force-reinstall dist/*.whl
python3 -m pytest python/tests
```

The release closeout gate remains:

```text
git diff --check
scripts/verify.sh
```

## Phase X Goal

Design and implement the first deterministic bracket-reservation subset for
multiple pending `strategy.exit` bracket calls without changing the public
strategy output schema.

The target positive subset, if confirmed by Slice 0, is:

- Keep the current long-only, one-net-position, no-pyramiding broker.
- Allow multiple pending bracket `strategy.exit` records for the current
  matching long entry when exits use different `id + from_entry` identities.
- Open multiple bracket reservations only when the bracket call has explicit
  fixed `qty` or explicit `qty_percent`.
- Continue replacing an existing pending exit when a call uses the same
  `id + from_entry` identity.
- Resolve every pending exit to an absolute reserved close quantity at
  placement time.
- Apply reservation before storing a pending exit so the sum of open
  reservations never exceeds the current open position size.
- Release the old reservation before resolving a replacement for the same
  `id + from_entry`.
- If a new bracket request has no remaining unreserved quantity, reject the new
  placement with a stable strategy diagnostic and leave existing pending exits
  unchanged.
- If a replacement request is invalid, preserve the previous pending exit and
  its reservation.
- Preserve current one-effective-pending behavior for omitted-quantity bracket
  exits.
- Preserve current one-effective-pending behavior for trailing exits.
- Fill no more than each bracket's reserved quantity and no more than the
  current remaining position.
- Remove a filled pending bracket after it fills.
- Cancel all pending exits for an entry when that entry is fully closed or when
  `strategy.close(id)` closes the matching position.
- Keep public runtime JSON, Python dictionaries, and WASM JSON on the existing
  strategy result shape and runtime `schemaVersion: 3`.

The Phase X runtime claim should be deliberately small:

- Multiple pending bracket exits for the same current long entry.
- Supported bracket trigger shapes remain exactly:
  - `stop + limit`
  - `stop + profit`
  - `loss + limit`
  - `loss + profit`
- Explicit fixed `qty` and `qty_percent` reservations only.
- Omitted quantity remains on the existing one-effective-pending full-position
  path and is outside the multiple-reservation claim.
- Trailing exits remain one-effective-pending until a later trailing-specific
  phase.

Phase X is successful when supported bracket reservations execute
deterministically, round-trip through CLI/Python/WASM, are fixture- and
snapshot-covered including incremental parity, are marked appropriately in
`tests/fixtures/conformance.tsv`, are documented, and pass the full release
verification gate, while still-unsupported broker-lifecycle forms remain
diagnostic-only unsupported.

## Non-Goals

Do not include these in the Phase X compatibility claim:

- Short exposure, reversals, pyramiding, or multiple simultaneous entries.
- Missing-entry pre-placement of pending exits.
- Omitted-quantity multiple pending exits.
- Multiple pending trailing reservations.
- Same-side bracket pairs `stop + loss` and `limit + profit`.
- Three-trigger and four-trigger calls.
- Invalid trailing combinations or trailing-plus-bracket combinations.
- `qty + qty_percent`.
- `strategy.order`, `strategy.cancel`, `strategy.cancel_all`, OCA APIs,
  `comment`, `alert_message`, or strategy alert delivery.
- Public pending-order records, reservation fields, remaining-quantity fields,
  percent fields, bracket-leg fields, trailing-state fields, exit-reason
  fields, or a runtime schema bump.
- Commission, slippage, margin, currency conversion, percent-of-equity sizing,
  cash sizing, contracts sizing, or custom tick-size host metadata.
- Realtime strategy execution, forming-bar broker rollback, or intrabar path
  reconstruction.
- Full TradingView broker-emulator equivalence.
- Lower-timeframe request APIs, drawing object expansion, map/matrix support,
  or unrelated built-in coverage.

## Default Design Decisions

These are the default Phase X decisions. Slice 0 must confirm them before
behavior changes land. If any decision changes, update this section first and
keep fixtures, docs, matrix metadata, and implementation aligned with the
revised rule.

- Phase X is long-only and uses the current one-net-long broker.
- Phase X stores multiple broker-owned pending exits internally, but does not
  expose a public pending-order list.
- Pending exit identity remains `id + from_entry`.
- The internal pending collection preserves placement order.
- A call with a new identity adds a new pending bracket if the matching entry is
  open and enough unreserved quantity exists after clamping/resolution.
- A call with an existing identity replaces that pending exit. The old
  reservation is released before resolving the replacement quantity. If the
  replacement is invalid, the old pending exit remains unchanged.
- Omitted `qty` and omitted `qty_percent` keep the previous full-position
  behavior through the one-effective-pending replacement path.
- Fixed `qty` resolves to `min(qty, unreserved_position_quantity)`.
- `qty_percent` resolves to `position_size * qty_percent / 100.0`, then clamps
  to the current unreserved position quantity.
- `qty_percent > 100` remains allowed and therefore resolves to all currently
  unreserved quantity when it exceeds the position.
- Zero-reservation placements are rejected with `E_STRATEGY_EXIT_QTY`.
- Invalid prices, ticks, mintick, `qty`, or `qty_percent` preserve all existing
  pending exits.
- A bracket has one downside leg and one upside leg. Downside legs are `stop`
  and `loss`; upside legs are `limit` and `profit`.
- Tick legs convert once at placement time from
  `strategy.position_avg_price` using the fixed default `syminfo.mintick`.
- Bracket prices remain fixed after placement.
- A pending bracket is ineligible on its creation/replacement bar through the
  existing `last_update_bar_index >= bar_index` guard.
- A bracket candidate is downside-touched when `low <= downside_price`.
- A bracket candidate is upside-touched when `high >= upside_price`.
- If both legs of a single bracket are touched on the same eligible historical
  bar, the bracket candidate's selected side is downside and its fill price is
  the downside price.
- If any downside candidate and any upside candidate are both touched across
  the pending collection on the same eligible bar, downside is the winning side.
  Only winning-side candidates fill on that bar; opposite-side candidates
  remain pending if a position remains.
- Candidates on the winning side fill in placement order until the position is
  flat or no touched candidates remain.
- Filled exits emit existing `strategy.exit` order events and existing closed
  trade records using absolute filled quantities.
- `strategy.closedtrades` increases by one per filled exit record.
- `strategy.opentrades` remains `1` while any supported long position remains
  open and becomes `0` only when the final remaining quantity closes.
- Public output remains schema-compatible. No new fields are required because
  order and trade records already expose absolute `qty`.

## Rules for Every Slice

- Read this document, `docs/PHASE_R_AUDIT.md`,
  `docs/PHASE_W_AUDIT.md`, and the current code before editing.
- Execute Slice 0 first. Do not start structural or runtime behavior changes
  until the baseline tests pass and the Phase X bracket-reservation decisions
  are recorded as current.
- Add fixtures before or alongside behavior changes.
- Keep the compatibility matrix conservative. Only widen the `strategy.exit`
  row when semantic fixtures, runtime fixtures, host coverage, conformance
  metadata, docs, and verification evidence all exist for the exact
  bracket-reservation subset.
- Preserve indicator behavior. Indicator scripts must not gain broker state or
  strategy output.
- Keep strategy order calls rejected in UDFs and requested-context expressions
  under the existing side-effect policy.
- Do not silently change analyzer behavior for unsupported trigger shapes.
- Do not change runtime `schemaVersion: 3` in Phase X.
- Keep snapshots authoritative for public output shapes.
- Keep CLI, Python, and WASM behavior synchronized. A bracket-reservation
  fixture that runs in one host should expose the same public strategy result
  shape in every host.
- Keep existing single-pending, single-trigger reservation, bracket, trailing,
  fixed-`qty`, and `qty_percent` fixtures passing unchanged unless the slice
  explicitly widens bracket reservation with fixture-backed behavior.
- Because the analyzer validates individual `strategy.exit` calls rather than
  broker-wide pending state, runtime placement must enforce the Phase X subset
  boundary. Do not rely on semantic analysis to prevent trailing or
  omitted-quantity multi-reservation from widening earlier than documented.
- If a slice reveals a bug in the existing single-exit or Phase W reservation
  subset, stop, add a focused regression fixture or unit test, fix it, and
  close that small behavior slice before continuing.
- If the bracket-reservation model requires public pending-order records to be
  useful, stop and record a design-only audit instead of widening the public
  schema inside Phase X.
- Stage and commit only the current slice when implementing. Do not mix
  cleanup, docs drift, or unrelated code-review fixes into a behavior slice.

## Internal Structure Rules

- Keep `BrokerState` as the public strategy runtime facade exported by
  `pine-runtime`.
- Keep pending-exit identity, reservation helpers, bracket classification, and
  placement helpers in `crates/pine-runtime/src/strategy/broker/exits.rs` or a
  focused child module if `exits.rs` becomes too large.
- Keep pending evaluation and same-bar precedence in
  `crates/pine-runtime/src/strategy/broker/mod.rs`.
- Keep fill construction and position reduction/reset logic in
  `crates/pine-runtime/src/strategy/broker/fills.rs`.
- Keep equity, position, profit, and trade-count accessors in
  `crates/pine-runtime/src/strategy/broker/accounting.rs`.
- Keep semantic validation in `crates/pine-sema/src/analyzer/strategy.rs`.
  Phase X should need minimal semantic changes because bracket calls already
  analyze individually after Phase R and quantity arguments already analyze
  individually after Phases U/V.
- Keep runtime argument extraction and dispatch in
  `crates/pine-runtime/src/builtins/strategy.rs`.
- Keep builtin signature metadata in
  `crates/pine-builtins/src/namespaces/strategy.rs`.
- Keep Python and WASM bindings thin. They should map the shared strategy
  result model and must not duplicate reservation math, bracket precedence, or
  quantity resolution.
- Prefer a small internal trigger-candidate helper over scattering OHLC
  selection logic across stop, limit, bracket, and trailing paths.
- Treat roughly 800 lines in a production Rust file as a review trigger. Split
  focused helpers before growing a multipurpose module.

## Intended Data Model

The existing Phase W data model should be retained and generalized narrowly for
bracket reservation.

Preferred persisted shape:

```text
PendingExit {
  id: String,
  from_entry: String,
  trigger: PendingExitTrigger,
  quantity: PendingExitQuantity,
  reserved_quantity: f64,
  multiple_reservation: bool,
  last_update_bar_index: usize,
}

PendingExitQuantity:
  Full
  Fixed(f64)

PendingExitTrigger:
  Stop(f64)
  Limit(f64)
  Bracket { downside: f64, upside: f64 }
  Trailing(PendingTrailingExit)
```

Preferred transient runtime placement shape:

```text
ExitQuantityRequest:
  Full
  Fixed(f64)
  Percent(f64)
```

Suggested trigger-family helpers:

```text
PendingExitReservationFamily:
  SingleTrigger
  Bracket
  OneEffectivePendingOnly

TouchedExitCandidate:
  pending_exit: PendingExit
  exit_price: f64
  side: PendingExitSide
```

Rules:

- `Full` is the default when both `qty` and `qty_percent` are omitted.
- `Full` stays outside Phase X multiple-reservation support.
- `Fixed(qty)` stores the absolute requested close quantity as intent, but
  reserves only `min(qty, unreserved_position_quantity)`.
- `Percent(percent)` is transient. It resolves to
  `position_size * percent / 100.0`, then reserves no more than the currently
  unreserved position quantity.
- `reserved_quantity` is the fill ceiling for that pending exit.
- Quantity intent participates in repeated-placement equivalence by comparing
  the effective trigger plus resolved `reserved_quantity`, not the raw percent
  expression.
- Fill code owns clamping a reserved quantity to the current remaining
  `position_size`.
- Fill code owns deciding whether the position becomes flat or remains open.
- Bracket trigger equivalence compares both resolved leg prices, not the raw
  source argument forms.

## Slice 0: Baseline Lock And Bracket Reservation Decision Confirmation

Goal: confirm that Phase X is a narrow bracket-reservation phase, not a broad
broker emulator phase, and record that the default decisions above still match
the live repo before any code behavior changes.

Steps:

1. Check worktree state with `git status --short`. Protect unrelated local
   edits and stage only Phase X files when implementing.
2. Read the strategy sections in `docs/CONFORMANCE.md`,
   `docs/EXECUTION_SEMANTICS.md`, `docs/SEMANTIC_MODEL.md`,
   `docs/LONG_TERM_EXECUTION_PLAN.md`, `docs/PHASE_R_AUDIT.md`,
   `docs/PHASE_W_AUDIT.md`, and `tests/fixtures/conformance.tsv`.
3. Read the live broker and dispatch code:
   - `crates/pine-runtime/src/strategy/broker/mod.rs`
   - `crates/pine-runtime/src/strategy/broker/exits.rs`
   - `crates/pine-runtime/src/strategy/broker/fills.rs`
   - `crates/pine-runtime/src/strategy/broker/accounting.rs`
   - `crates/pine-runtime/src/builtins/strategy.rs`
   - `crates/pine-sema/src/analyzer/strategy.rs`
4. Confirm the existing Phase W reservation behavior with focused tests.
5. Confirm the exact Phase X positive subset:
   - multiple pending bracket exits;
   - explicit fixed `qty` and `qty_percent`;
   - only existing supported bracket trigger shapes;
   - omitted quantity stays on the one-effective-pending full-position path;
   - trailing multi-reservation remains deferred until a later phase.
6. Confirm bracket reservation math:
   - release old reservation before replacement;
   - clamp fixed and percent quantities to unreserved quantity;
   - reject zero-reservation placements;
   - preserve old pending exits on invalid replacement.
7. Confirm bracket same-bar fill precedence:
   - within one bracket, downside wins when both legs are touched;
   - across multiple touched candidates, downside wins over upside;
   - winning-side candidates fill in placement order;
   - opposite-side candidates remain pending if a position remains.
8. Confirm diagnostic codes and messages for zero-reservation and invalid
   reservation states. Prefer reusing `E_STRATEGY_EXIT_QTY`,
   `E_STRATEGY_EXIT_QTY_PERCENT`, `E_STRATEGY_EXIT_PRICE`,
   `E_STRATEGY_EXIT_TICKS`, `E_STRATEGY_EXIT_MINTICK`, and
   `E_STRATEGY_EXIT_ENTRY`.
9. Do not change runtime behavior, conformance metadata, or snapshots in this
   slice unless the decisions above require a docs-only clarification.
10. Record the final decisions in this document before Slice 1 starts.

Suggested commands:

```text
cargo test -p pine-sema strategy
cargo test -p pine-runtime strategy
cargo test -p pine-cli strategy
cargo run -q -p pine-cli -- matrix
```

Exit criteria:

- The current Phase W strategy behavior is green.
- The exact first bracket-reservation subset is recorded as confirmed or
  explicitly revised in this document.
- The bracket same-bar fill policy is recorded as confirmed or explicitly
  revised in this document.
- No compatibility claim is widened.

### Slice 0 Decision Record

Status: completed on 2026-06-02.

Docs and code read:

- `docs/CONFORMANCE.md`
- `docs/EXECUTION_SEMANTICS.md`
- `docs/SEMANTIC_MODEL.md`
- `docs/LONG_TERM_EXECUTION_PLAN.md`
- `docs/PHASE_R_AUDIT.md`
- `docs/PHASE_W_AUDIT.md`
- `tests/fixtures/conformance.tsv`
- `crates/pine-runtime/src/strategy/broker/mod.rs`
- `crates/pine-runtime/src/strategy/broker/exits.rs`
- `crates/pine-runtime/src/strategy/broker/fills.rs`
- `crates/pine-runtime/src/strategy/broker/accounting.rs`
- `crates/pine-runtime/src/builtins/strategy.rs`
- `crates/pine-sema/src/analyzer/strategy.rs`

Focused baseline verification:

```text
cargo test -p pine-sema strategy
cargo test -p pine-runtime strategy
cargo test -p pine-cli strategy
cargo run -q -p pine-cli -- matrix
```

All commands passed on the Slice 0 workspace.

Confirmed Phase X positive subset:

- Multiple pending bracket `strategy.exit` reservations may be opened only for
  the current matching long entry.
- Supported bracket trigger shapes remain exactly `stop + limit`,
  `stop + profit`, `loss + limit`, and `loss + profit`.
- Multiple bracket reservations require explicit fixed `qty` or explicit
  `qty_percent`.
- Existing same-identity replacement remains `id + from_entry` based.
- Reservations resolve once at placement time to absolute reserved close
  quantities.
- Fixed `qty` reserves `min(qty, unreserved_position_quantity)`.
- `qty_percent` resolves from the current open `position_size`, then clamps to
  the currently unreserved position quantity.
- Old same-identity reservations are released before replacement quantity
  resolution.
- Invalid replacement requests preserve the previous pending exit and its
  reservation.

Confirmed unsupported boundaries:

- Omitted `qty` and omitted `qty_percent` bracket exits stay on the existing
  one-effective-pending full-position path.
- Trailing exits stay on the existing one-effective-pending path.
- Missing-entry pre-placement, omitted-quantity multiple exits, same-side
  bracket pairs, three-or-more trigger calls, invalid trailing combinations,
  `qty + qty_percent`, short exposure, reversals, pyramiding, multiple
  simultaneous entries, public pending-order records, reservation output fields,
  and runtime schema changes remain outside Phase X.

Confirmed fill precedence:

- A pending bracket is ineligible on its creation or replacement bar.
- Within one bracket, if both legs are touched on the same eligible historical
  bar, the downside leg wins and fills at the downside price.
- Across multiple touched pending candidates, downside candidates win over
  upside candidates on the same eligible historical bar.
- Winning-side candidates fill in placement order until the position is flat or
  no touched winning-side candidates remain.
- Opposite-side candidates remain pending after a partial winning-side fill if a
  supported long position remains.

Confirmed diagnostic choices:

- Reuse `E_STRATEGY_EXIT_QTY` for invalid fixed quantity and zero-reservation
  placements.
- Reuse `E_STRATEGY_EXIT_QTY_PERCENT` for invalid percent quantity.
- Reuse `E_STRATEGY_EXIT_PRICE`, `E_STRATEGY_EXIT_TICKS`,
  `E_STRATEGY_EXIT_MINTICK`, and `E_STRATEGY_EXIT_ENTRY` for the existing price,
  tick, mintick, and entry guardrails.
- Do not add Phase X-specific diagnostic codes unless a later slice proves an
  existing code cannot describe the failing condition clearly.

Local worktree notes:

- `docs/PHASE_W_EXECUTION_PLAN.md` has an unrelated local documentation
  clarification about omitted-quantity exits staying one-effective-pending; it
  was reviewed as consistent with Phase X's baseline and intentionally left
  unstaged.
- `docs/CODE_REVIEW_FIX_AUDIT.md` is unrelated to Phase X and was intentionally
  left unstaged.
- No runtime behavior, conformance metadata, matrix snapshot, public output
  shape, Python binding, or WASM binding changed in Slice 0.

## Slice 1: Trigger Candidate Helpers Without Behavior Widening

Goal: factor pending-exit trigger classification and touch selection so bracket
reservations can reuse the Phase W multiple-pending evaluator without opening
new runtime behavior yet.

Steps:

1. In `crates/pine-runtime/src/strategy/broker/exits.rs`, add or refactor
   helper methods on `PendingExitTrigger` for:
   - whether the trigger is eligible for Phase W single-trigger reservation;
   - whether the trigger is eligible for Phase X bracket reservation;
   - selected touched side and price for a given historical bar range.
2. Keep current behavior unchanged:
   - single-trigger explicit `qty`/`qty_percent` reservations still append or
     replace according to Phase W rules;
   - bracket exits still use the one-effective-pending replacement path;
   - trailing exits still use the one-effective-pending replacement path;
   - omitted-quantity exits still use the one-effective-pending replacement
     path.
3. Move duplicated OHLC touch logic into a focused helper only if it keeps
   `evaluate_pending_exits` easier to audit.
4. For bracket candidate selection, encode the intended rule but do not wire it
   into multi-pending placement yet:
   - downside hit when `low <= downside`;
   - upside hit when `high >= upside`;
   - if both are hit, return downside.
5. Add broker unit tests for helper behavior:
   - single-trigger side classification;
   - bracket reservation-family classification;
   - trailing excluded from reservation families;
   - bracket downside-only, upside-only, both-hit, and no-hit candidate
     selection.
6. Keep public structs, JSON output, conformance metadata, matrix snapshots,
   CLI/Python/WASM behavior, and runtime fixtures unchanged.

Suggested commands:

```text
cargo fmt --check
cargo test -p pine-runtime strategy
cargo test -p pine-cli strategy
```

Exit criteria:

- Helper tests prove bracket candidate classification.
- Existing Phase W fixtures remain unchanged.
- Bracket multi-reservation is still not user-visible.
- No conformance row changes.
- No public output shape changes.

### Slice 1 Implementation Record

Status: completed on 2026-06-02.

Implemented changes:

- Added internal `PendingExitReservationFamily` classification for
  single-trigger, bracket, and one-effective-pending-only trigger families.
- Added `PendingExitTouch` and trigger touch-selection helpers that return the
  selected fill side and price for stop, limit, and bracket triggers.
- Kept the multiple-pending evaluator wired only to the single-trigger touch
  helper, so bracket exits remain on the existing one-effective-pending path in
  Slice 1.
- Added broker unit tests for single-trigger classification, bracket
  classification, trailing exclusion, single-trigger touch selection, and
  bracket downside-only, upside-only, both-hit, and no-hit candidate selection.

No runtime fixture, conformance metadata, matrix snapshot, public output shape,
Python binding, or WASM binding changed in Slice 1.

Slice 1 verification:

```text
cargo fmt --check
cargo test -p pine-runtime strategy
cargo test -p pine-cli strategy
```

All commands passed on the Slice 1 workspace.

## Slice 2: Fixed-Quantity Bracket Reservations

Goal: open the first positive multiple-pending bracket subset for explicit
fixed `qty` bracket exits.

Steps:

1. Generalize the internal reservation-family check so multiple reservations
   are allowed for:
   - existing explicit fixed `qty` or `qty_percent` single-trigger exits; and
   - Phase X explicit fixed `qty` bracket exits.
2. Keep `qty_percent` bracket multi-reservation closed until Slice 3.
3. Keep omitted-quantity bracket exits on the existing one-effective-pending
   replacement path.
4. Keep trailing exits on the existing one-effective-pending replacement path.
5. Keep multiple pending collections homogeneous or explicitly compatible:
   - a pending single-trigger reservation may coexist with a fixed-`qty`
     bracket reservation only if Slice 2 intentionally implements mixed-family
     interaction; otherwise defer mixed-family interactions to Slice 4.
   - if mixed-family behavior is deferred, a new bracket reservation should
     replace incompatible pending state rather than silently append.
6. Implement multiple-pending evaluation for bracket candidates:
   - skip creation/replacement bars;
   - collect touched single-trigger and bracket candidates according to the
     active supported family set;
   - select downside as the winning side if any downside candidate is touched;
   - otherwise select upside if any upside candidate is touched;
   - fill winning-side candidates in placement order;
   - remove filled identities;
   - keep untouched or opposite-side exits pending if a position remains;
   - clear all pending exits if the position becomes flat.
7. Add broker unit tests for:
   - two fixed-`qty` brackets reserving partial quantities and filling in
     placement order;
   - same-identity bracket replacement releasing and recalculating only that
     reservation;
   - a new bracket that exceeds remaining unreserved quantity clamping to the
     remaining unreserved quantity;
   - a new bracket when no unreserved quantity remains being rejected;
   - a full bracket fill canceling remaining pending exits;
   - invalid bracket replacement preserving the old pending bracket.
8. Add runtime fixtures and snapshots for:
   - two fixed-`qty` `stop + limit` brackets with downside fills;
   - two fixed-`qty` `stop + limit` brackets with upside fills;
   - fixed-`qty` bracket replacement preserving other pending exits;
   - fixed-`qty` bracket over-reservation clamping.
9. Add the fixtures to the CLI golden snapshot harness.
10. Add incremental append coverage for the new runtime fixtures.
11. Update `tests/fixtures/conformance.tsv` only for the exact fixed-quantity
    bracket reservation subset, or defer conformance widening to Slice 5 if
    this slice is kept runtime-only.

Candidate fixture names:

```text
tests/fixtures/runtime/strategy_exit_reservation_qty_bracket_stop_limit_downside_multi.pine
tests/fixtures/runtime/strategy_exit_reservation_qty_bracket_stop_limit_upside_multi.pine
tests/fixtures/runtime/strategy_exit_reservation_qty_bracket_replacement.pine
tests/fixtures/runtime/strategy_exit_reservation_qty_bracket_clamp.pine
```

Suggested commands:

```text
cargo fmt --check
cargo test -p pine-runtime strategy
cargo test -p pine-runtime --test incremental
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli matrix
```

Exit criteria:

- Multiple fixed-`qty` bracket exits work end to end for the selected bracket
  forms.
- Existing one-exit, single-trigger reservation, bracket, trailing,
  fixed-`qty`, and `qty_percent` fixtures remain green.
- Conformance text claims no more than the fixed-`qty` bracket reservation
  subset if conformance is updated in this slice.
- Public output shape is unchanged.

### Slice 2 Implementation Record

Status: completed on 2026-06-02.

Implemented changes:

- Opened multiple pending reservations for explicit fixed-`qty` bracket exits
  using the existing `PendingExitBook` reservation ledger.
- Kept bracket reservation support limited to the existing bracket trigger
  shapes: `stop + limit`, `stop + profit`, `loss + limit`, and `loss + profit`.
- Kept `qty_percent` bracket calls, omitted-quantity bracket calls, trailing
  exits, and incompatible mixed single-trigger/bracket pools on the
  one-effective-pending replacement path.
- Generalized pending-exit placement to choose a supported reservation family
  before resolving available quantity. Same-family reservations append or
  replace by `id + from_entry`; incompatible families replace the current
  pending pool.
- Generalized the multiple-pending evaluator to use trigger touch helpers, so
  fixed-`qty` bracket reservations fill using the confirmed downside-wins and
  placement-order policy.
- Added broker tests for fixed-quantity bracket append, downside fills, upside
  fills, same-identity replacement, clamp to remaining unreserved quantity,
  zero-unreserved rejection, full-fill cleanup, invalid replacement preservation,
  incompatible single-trigger replacement, and percent bracket deferral.

Runtime fixtures and snapshots added:

```text
tests/fixtures/runtime/strategy_exit_reservation_qty_bracket_stop_limit_downside_multi.pine
tests/snapshots/runtime_strategy_exit_reservation_qty_bracket_stop_limit_downside_multi.json
tests/fixtures/runtime/strategy_exit_reservation_qty_bracket_stop_limit_upside_multi.pine
tests/snapshots/runtime_strategy_exit_reservation_qty_bracket_stop_limit_upside_multi.json
tests/fixtures/runtime/strategy_exit_reservation_qty_bracket_replacement.pine
tests/snapshots/runtime_strategy_exit_reservation_qty_bracket_replacement.json
tests/fixtures/runtime/strategy_exit_reservation_qty_bracket_clamp.pine
tests/snapshots/runtime_strategy_exit_reservation_qty_bracket_clamp.json
```

The runtime fixtures are included in the CLI golden snapshot harness and the
generic incremental append fixture harness. `tests/fixtures/conformance.tsv` and
`tests/snapshots/matrix.json` were intentionally left unchanged in Slice 2; the
public compatibility wording is deferred to the host/conformance slice after
fixed and percent bracket reservation evidence are both available.

No public runtime JSON, Python dictionary, WASM JSON, or `schemaVersion: 3`
shape changed in Slice 2.

Slice 2 verification:

```text
cargo fmt --check
cargo test -p pine-runtime strategy
cargo test -p pine-runtime --test incremental
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli matrix
```

All commands passed on the Slice 2 workspace.

## Slice 3: Percent Bracket Reservations

Goal: extend the Slice 2 bracket-reservation subset to explicit
`qty_percent`.

Steps:

1. Reuse the existing reservation resolver for percent quantities.
2. Confirm percent quantities resolve against the current open position size,
   not the unreserved quantity, then clamp to unreserved quantity.
3. Keep `qty + qty_percent` unsupported through the existing semantic
   guardrail.
4. Keep omitted-quantity bracket exits on the one-effective-pending replacement
   path.
5. Add broker unit tests for:
   - two percent bracket exits reserve expected absolute quantities;
   - percent plus fixed bracket exits share the same reservation pool;
   - percent bracket replacement releases old reservation first;
   - `qty_percent > 100` reserves all remaining unreserved quantity;
   - zero remaining unreserved quantity rejects the new percent bracket
     placement;
   - invalid percent replacement preserves the old pending bracket.
6. Add runtime fixtures and snapshots for:
   - two `qty_percent` brackets;
   - mixed fixed and percent brackets;
   - percent bracket replacement;
   - over-100 percent bracket clamping.
7. Add incremental append coverage.
8. Add or update representative semantic fixtures only if needed. Most
   `qty_percent` bracket calls already analyze individually after Phase V.
9. Update conformance notes and fixtures for the exact percent bracket
   reservation subset, or defer final wording to Slice 5.

Candidate fixture names:

```text
tests/fixtures/runtime/strategy_exit_reservation_qty_percent_bracket_multi.pine
tests/fixtures/runtime/strategy_exit_reservation_qty_mixed_bracket_multi.pine
tests/fixtures/runtime/strategy_exit_reservation_qty_percent_bracket_replacement.pine
tests/fixtures/runtime/strategy_exit_reservation_qty_percent_bracket_clamp.pine
```

Suggested commands:

```text
cargo fmt --check
cargo test -p pine-runtime strategy
cargo test -p pine-runtime --test incremental
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli matrix
```

Exit criteria:

- Multiple percent bracket reservations work end to end.
- Mixed fixed and percent bracket reservations are deterministic.
- Existing Phase V single-exit percent fixtures remain green.
- Public output shape is unchanged.

### Slice 3 Implementation Record

Status: completed on 2026-06-02.

Implemented changes:

- Extended the Slice 2 bracket reservation family from explicit fixed `qty` to
  explicit fixed `qty` or `qty_percent`.
- Reused the existing percent quantity resolver: `qty_percent` resolves against
  the current open `position_size` at placement time, then clamps to currently
  unreserved position quantity.
- Kept `qty + qty_percent` rejected by the existing semantic guardrail.
- Kept omitted-quantity bracket exits and trailing exits outside the
  multiple-reservation claim.
- Added broker tests for two percent brackets, mixed fixed and percent brackets,
  percent replacement, over-100 percent clamping, zero-unreserved rejection, and
  invalid percent replacement preserving the previous pending bracket.

Runtime fixtures and snapshots added:

```text
tests/fixtures/runtime/strategy_exit_reservation_qty_percent_bracket_multi.pine
tests/snapshots/runtime_strategy_exit_reservation_qty_percent_bracket_multi.json
tests/fixtures/runtime/strategy_exit_reservation_qty_mixed_bracket_multi.pine
tests/snapshots/runtime_strategy_exit_reservation_qty_mixed_bracket_multi.json
tests/fixtures/runtime/strategy_exit_reservation_qty_percent_bracket_replacement.pine
tests/snapshots/runtime_strategy_exit_reservation_qty_percent_bracket_replacement.json
tests/fixtures/runtime/strategy_exit_reservation_qty_percent_bracket_clamp.pine
tests/snapshots/runtime_strategy_exit_reservation_qty_percent_bracket_clamp.json
```

The runtime fixtures are included in the CLI golden snapshot harness and the
generic incremental append fixture harness. `tests/fixtures/conformance.tsv` and
`tests/snapshots/matrix.json` were intentionally left unchanged in Slice 3; final
compatibility wording is deferred to the host/conformance slice.

No public runtime JSON, Python dictionary, WASM JSON, or `schemaVersion: 3`
shape changed in Slice 3.

Slice 3 verification:

```text
cargo fmt --check
cargo test -p pine-runtime strategy
cargo test -p pine-runtime --test incremental
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli matrix
```

All commands passed on the Slice 3 workspace.

## Slice 4: Mixed Single-Trigger And Bracket Reservation Interactions

Goal: cover deterministic interaction between Phase W single-trigger
reservations and Phase X bracket reservations.

Steps:

1. Decide whether Phase X supports mixed pending collections containing both
   single-trigger reservations and bracket reservations. The recommended
   decision is yes, because both resolve to a touched candidate with one
   selected side and fill price.
2. If mixed-family support is accepted, ensure placement allows explicit
   fixed `qty` or `qty_percent` single-trigger reservations and explicit fixed
   `qty` or `qty_percent` bracket reservations to share the same reservation
   pool for the current matching long entry.
3. If mixed-family support is rejected, record the rejection in this document
   and keep runtime behavior one-effective-pending when incompatible pending
   families are mixed.
4. For the recommended support path, add broker tests for:
   - single-trigger stop plus bracket downside both touched, fill in placement
     order on the downside side;
   - single-trigger limit plus bracket upside both touched, fill in placement
     order on the upside side;
   - mixed downside/upside candidates across families, downside wins;
   - opposite-side candidates remain pending after a partial winning-side fill;
   - same-identity replacement between single-trigger and bracket releases the
     old reservation before resolving the new one;
   - strategy close cancels all mixed-family pending exits for the entry.
5. Add runtime fixtures and snapshots for:
   - mixed single-trigger and bracket downside precedence;
   - mixed single-trigger and bracket upside placement order;
   - mixed-family replacement;
   - state variables before fill, on fill bar, and next bar.
6. Add incremental append coverage.
7. Update docs with the mixed-family OHLC policy.

Candidate fixture names:

```text
tests/fixtures/runtime/strategy_exit_reservation_bracket_single_downside_precedence.pine
tests/fixtures/runtime/strategy_exit_reservation_bracket_single_upside_order.pine
tests/fixtures/runtime/strategy_exit_reservation_bracket_single_replacement.pine
tests/fixtures/runtime/strategy_exit_reservation_bracket_state.pine
```

Suggested commands:

```text
cargo fmt --check
cargo test -p pine-runtime strategy
cargo test -p pine-runtime --test incremental
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli matrix
```

Exit criteria:

- Mixed single-trigger and bracket reservations are deterministic, or are
  explicitly deferred without accidental runtime widening.
- State variable timing matches existing pending-exit timing.
- Public strategy output and expression-time reads remain consistent with
  existing Phase M/N/R/S/U/V/W timing rules.

### Slice 4 Implementation Record

Decision: support mixed single-trigger and bracket reservation collections for
the same matching long entry when every existing pending exit in that entry
uses the Phase W/X explicit `qty` or `qty_percent` reservation path. This keeps
both families on the same touched-candidate evaluation model and still excludes
trailing and full-position exits from the multi-reservation path.

Implementation:

- Replaced the same-family placement gate with a supported-reservation gate:
  existing pending exits may share the reservation pool when they are marked
  `multiple_reservation` and classify as either `SingleTrigger` or `Bracket`.
- Kept trailing and full-position exits on the single-effective-pending
  replacement path.
- Added broker tests for downside and upside placement order, mixed-side
  downside precedence, same-identity single-trigger/bracket replacement, and
  `strategy.close` cancellation of mixed reservations.
- Added runtime fixtures and snapshots for mixed downside precedence, upside
  placement order, replacement, and strategy state timing.

Verification:

```text
cargo fmt --check
cargo test -p pine-runtime strategy
cargo test -p pine-runtime --test incremental
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli matrix
```

## Slice 5: Host Parity, Conformance, And Public Shape Guardrails

Goal: prove the bracket-reservation subset through all host surfaces and align
the compatibility metadata conservatively.

Steps:

1. Select one representative Phase X fixture for host parity. Prefer a fixture
   that includes:
   - two bracket reservations;
   - one partial fill;
   - a later fill of a remaining reservation;
   - fixed and percent quantity coverage if that does not make the fixture
     hard to audit.
2. Add or update a CLI host-shape assertion in `crates/pine-cli/src/main.rs`.
   Assert:
   - expected `strategy.exit` order count;
   - expected absolute `qty` values;
   - expected filled prices;
   - no public `reserved_quantity`, `remaining_quantity`, `qty_percent`,
     bracket-leg metadata, or pending-order fields.
3. Add or update a Python binding test in `python/tests/test_bindings.py` using
   the same representative fixture.
4. Add or update a WASM test in `crates/pine-wasm/src/tests/mod.rs` using the
   same representative fixture.
5. Confirm CLI, Python, and WASM use the shared runtime path and do not
   implement reservation math or bracket precedence in host bindings.
6. Update `tests/fixtures/conformance.tsv` and regenerate
   `tests/snapshots/matrix.json` if earlier slices did not already do so.
7. Keep the `strategy.exit` row `partial`.
8. Keep broad `strategy.*` `unsupported`.
9. Ensure conformance wording says no more than:
   - explicit fixed `qty` or `qty_percent` bracket reservations;
   - current one-net-long, no-pyramiding broker;
   - existing supported bracket shapes only;
   - no omitted-quantity bracket reservations;
   - no trailing reservations;
   - no missing-entry pre-placement;
   - no public schema changes.
10. Run host and matrix checks.

Suggested commands:

```text
cargo fmt --check
cargo test -p pine-cli strategy
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli matrix
cargo test -p pine-cli matrix_output_matches_golden_snapshot
cargo test -p pine-wasm strategy
maturin build --manifest-path crates/pine-python/Cargo.toml --out dist
python3 -m pip install --force-reinstall dist/*.whl
python3 -m pytest python/tests
```

Exit criteria:

- CLI, Python, and WASM expose the same Phase X public strategy result.
- No host binding exposes internal reservation or bracket-leg details.
- Matrix and conformance match the exact implemented subset.
- Public runtime schema remains `schemaVersion: 3`.

### Slice 5 Implementation Record

Representative host fixture:

- Added `strategy_exit_reservation_bracket_host_parity.pine`, covering one
  fixed-`qty` bracket reservation and one `qty_percent` bracket reservation.
  The fixed reservation fills partially on bar 1, and the percent reservation
  fills later on bar 2 as an absolute quantity.

Implementation:

- Added the host-parity fixture to CLI runtime golden snapshots.
- Added CLI, Python, and WASM host-shape assertions for:
  - two public `strategy.exit` order events;
  - absolute filled quantities `0.5` and `1`;
  - filled prices `2` and `3`;
  - unchanged public strategy result keys and `schemaVersion: 3`;
  - no public pending, reserved quantity, remaining quantity, qty-percent, or
    bracket-leg fields.
- Updated `tests/fixtures/conformance.tsv` and `tests/snapshots/matrix.json`
  to claim only the implemented explicit fixed-`qty` or `qty_percent`
  single-trigger/bracket reservation subset.
- Kept `strategy.exit` `partial` and broad `strategy.*` `unsupported`.

Verification:

```text
cargo fmt --check
cargo test -p pine-cli strategy
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli matrix
cargo test -p pine-cli matrix_output_matches_golden_snapshot
cargo test -p pine-wasm strategy
maturin build --manifest-path crates/pine-python/Cargo.toml --out dist
python3 -m pip install --force-reinstall dist/pine_compat_runtime-0.1.0-cp310-abi3-manylinux_2_35_x86_64.whl
python3 -m pytest python/tests
```

## Slice 6: Documentation Closeout And Audit

Goal: close Phase X with an audit that ties implementation, fixtures, docs, and
verification evidence together.

Steps:

1. Create `docs/PHASE_X_AUDIT.md`.
2. Record:
   - supported Phase X subset;
   - unsupported boundaries;
   - public output shape;
   - runtime fixtures and snapshots;
   - host parity tests;
   - conformance/matrix evidence;
   - verification commands and results.
3. Update `docs/CONFORMANCE.md` to match `tests/fixtures/conformance.tsv`.
4. Update `docs/EXECUTION_SEMANTICS.md` with bracket-reservation placement,
   precedence, fill timing, and public-output rules.
5. Update `docs/SEMANTIC_MODEL.md` with the exact semantic/runtime boundary.
6. Update `docs/LONG_TERM_EXECUTION_PLAN.md`:
   - mark Phase X closed;
   - list still-deferred broker tails;
   - recommend the next narrow strategy tail only after repo-grounded review.
7. Update `docs/RELEASE_NOTES.md` with a concise Phase X entry.
8. Update README or user-facing support summaries only if they already mention
   strategy reservation support.
9. Do not mark trailing reservations, omitted-quantity multiple exits,
   missing-entry pre-placement, short exposure, pyramiding, or rich order APIs
   as supported.
10. Run docs-sensitive and focused verification.

Suggested commands:

```text
cargo fmt --check
cargo test -p pine-cli matrix
cargo test -p pine-cli matrix_output_matches_golden_snapshot
git diff --check
```

Exit criteria:

- `docs/PHASE_X_AUDIT.md` exists and cites concrete fixture/test evidence.
- Roadmap, conformance docs, semantic docs, release notes, conformance TSV, and
  matrix snapshot agree.
- No unsupported broker tail is accidentally claimed.

### Slice 6 Implementation Record

Implementation:

- Added `docs/PHASE_X_AUDIT.md` with supported surface, unsupported
  boundaries, public output shape, fixture evidence, host evidence,
  documentation evidence, focused verification, and pending release-gate
  status.
- Updated `README.md`, `docs/CONFORMANCE.md`,
  `docs/EXECUTION_SEMANTICS.md`, `docs/SEMANTIC_MODEL.md`,
  `docs/LONG_TERM_EXECUTION_PLAN.md`, and `docs/RELEASE_NOTES.md` to align on
  the explicit fixed-`qty` or `qty_percent` single-trigger/bracket reservation
  subset.
- Marked Phase X closed in the long-term roadmap while leaving missing-entry
  pre-placement, omitted-quantity multiple exits, trailing reservations,
  short/pyramiding behavior, richer broker APIs, and public pending/reservation
  fields deferred.
- Kept `strategy.exit` `partial`, broad `strategy.*` `unsupported`, and runtime
  output at `schemaVersion: 3`.

Verification:

```text
cargo fmt --check
cargo test -p pine-cli matrix
cargo test -p pine-cli matrix_output_matches_golden_snapshot
git diff --check
```

## Slice 7: Release Verification

Goal: run the canonical release gate and leave the workspace ready for a narrow
Phase X commit.

Steps:

1. Check worktree state with `git status --short`.
2. Confirm the only intended Phase X files are changed.
3. Run the full release gate.
4. If `scripts/verify.sh` fails:
   - fix in the smallest local slice if the failure is caused by Phase X;
   - stop and report if the failure is environmental or unrelated.
5. Re-run `git diff --check` after any final formatting/docs edits.
6. Record final verification results in `docs/PHASE_X_AUDIT.md`.
7. Stage only Phase X files.
8. Commit with a narrow message, for example:

```text
Implement Phase X bracket exit reservations
```

Suggested commands:

```text
git diff --check
scripts/verify.sh
git status --short
```

Exit criteria:

- `scripts/verify.sh` passes.
- The Phase X audit contains final verification evidence.
- The staged/committed files contain only Phase X work.
- The workspace is ready for the next repo-grounded phase selection.

### Slice 7 Implementation Record

Implementation:

- Confirmed the only remaining unstaged files before the release gate were the
  unrelated `docs/PHASE_W_EXECUTION_PLAN.md` edit and
  `docs/CODE_REVIEW_FIX_AUDIT.md`.
- Ran the canonical release gate successfully.
- Updated `docs/PHASE_X_AUDIT.md` to mark Phase X closed and record
  release-gate evidence.

Verification:

```text
scripts/verify.sh
git diff --check
git status --short
```

## Closeout Claim

At Phase X close, the expected claim should be no broader than:

- `strategy.exit` remains `partial`.
- Multiple pending bracket exits are supported only for the fixture-backed
  explicit fixed-`qty` or `qty_percent` bracket subset.
- Supported bracket shapes remain `stop + limit`, `stop + profit`,
  `loss + limit`, and `loss + profit`.
- Reservation applies only to the current one-net-long position.
- Reserved quantities are absolute placement-time quantities.
- Fills emit existing order and trade records with absolute filled quantities.
- Public runtime schema remains `schemaVersion: 3`.
- Omitted-quantity full-position exits and trailing exits remain on the
  one-effective-pending replacement path.
- Missing-entry pre-placement, multiple entries, pyramiding, short exposure,
  reversals, public pending-order records, rich order APIs, OCA behavior,
  commission, slippage, margin, strategy alerts, realtime broker rollback, and
  intrabar path reconstruction remain unsupported.
