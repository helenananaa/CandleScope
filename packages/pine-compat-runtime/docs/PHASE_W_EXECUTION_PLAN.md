# Phase W Strategy Exit Reservation Execution Plan

Status: closed on 2026-06-02. This document is the step-by-step execution
playbook for the narrow strategy phase after `docs/PHASE_V_AUDIT.md`.

Phase W should turn the current single pending `strategy.exit` model into the
first deterministic reservation-backed multiple-exit subset for the existing
long-only, no-pyramiding broker. It must not become a short, pyramiding,
missing-entry pre-placement, public pending-order, or broker-emulator parity
phase.

Every slice should leave the workspace shippable and should keep semantic
claims, broker behavior, public output contracts, fixtures, snapshots, host
bindings, conformance metadata, docs, and release verification in lockstep.

## Current Starting Point

The repository has closed the current strategy progression through Phase V. The
relevant strategy baseline is:

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
  behavior.
- The current broker stores one current long position with `position_size`,
  `avg_price`, `entry_id`, `entry_bar_index`, and `entry_time`.
- The current broker stores a single `pending_exit: Option<PendingExit>`.
- `PendingExit` carries `id`, `from_entry`, `trigger`, `quantity`, and
  `last_update_bar_index`.
- `PendingExitQuantity` is currently `Full | Fixed(f64)`.
- Runtime fill code clamps fixed requested quantity to current `position_size`
  and handles partial-fill accounting.
- Runtime output remains `schemaVersion: 3`. `StrategyResult`,
  `StrategyOrderEvent`, `StrategyTrade`, `StrategyPositionSnapshot`, and
  `StrategyEquitySnapshot` shapes are unchanged.
- Multiple independent pending exits, quantity reservation, missing-entry
  pre-placement, pyramiding, short exposure, reversals, public pending-order
  records, and strategy order families beyond the current subset remain
  unsupported.

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

## Phase W Goal

Design and implement the first deterministic quantity-reservation subset for
multiple pending `strategy.exit` calls without changing the public strategy
output schema.

The target positive subset, if confirmed by Slice 0, is:

- Keep the current long-only, one-net-position, no-pyramiding broker.
- Allow multiple pending `strategy.exit` records for the current matching
  long entry when exits use different `id` values.
- Continue replacing an existing pending exit when a call uses the same
  `id + from_entry` identity.
- Resolve every pending exit to an absolute reserved close quantity at
  placement time.
- Apply reservation before storing a pending exit so the sum of open
  reservations never exceeds the current open position size.
- Release the old reservation before resolving a replacement for the same
  `id + from_entry`.
- If a new exit request has no remaining unreserved quantity, reject the new
  placement with a stable strategy diagnostic and leave existing pending exits
  unchanged.
- If a replacement request is invalid, preserve the previous pending exit and
  its reservation.
- Preserve current single-exit behavior when only one pending exit exists.
- Fill no more than each exit's reserved quantity and no more than the current
  remaining position.
- Remove a filled pending exit after it fills.
- Cancel all pending exits for an entry when that entry is fully closed or when
  `strategy.close(id)` closes the matching position.
- Keep public runtime JSON, Python dictionaries, and WASM JSON on the existing
  strategy result shape and runtime `schemaVersion: 3`.

The first runtime claim should be deliberately small:

- Multiple pending single-trigger exits for the same current long entry.
- Explicit `qty` and `qty_percent` reservations.
- Omitted quantity remains on the existing one-effective-pending full-position
  path and is outside the multiple-reservation claim.
- Bracket and trailing exits should stay one-pending-compatible until the
  single-trigger reservation subset is fixture-backed. Runtime placement must
  not silently append bracket or trailing exits with new identities before the
  selected bracket/trailing slice explicitly opens that behavior.

Phase W is successful when supported multiple-exit reservations execute
deterministically, round-trip through CLI/Python/WASM, are fixture- and
snapshot-covered including incremental parity, are marked appropriately in
`tests/fixtures/conformance.tsv`, are documented, and pass the full release
verification gate, while still-unsupported broker-lifecycle forms remain
diagnostic-only unsupported.

## Non-Goals

Do not include these in the Phase W compatibility claim:

- Short exposure, reversals, pyramiding, or multiple simultaneous entries.
- Missing-entry pre-placement of pending exits.
- `strategy.order`, `strategy.cancel`, `strategy.cancel_all`, OCA APIs,
  `comment`, `alert_message`, or strategy alert delivery.
- Public pending-order records, reservation fields, remaining-quantity fields,
  percent fields, exit-reason fields, bracket-leg fields, or a runtime schema
  bump.
- Commission, slippage, margin, currency conversion, percent-of-equity sizing,
  cash sizing, contracts sizing, or custom tick-size host metadata.
- Realtime strategy execution, forming-bar broker rollback, or intrabar path
  reconstruction.
- Full TradingView broker-emulator equivalence.
- Same-side bracket pairs `stop + loss` and `limit + profit`, 3+ trigger
  calls, invalid trailing combinations, or `qty + qty_percent`.
- Lower-timeframe request APIs, drawing object expansion, map/matrix support,
  or unrelated built-in coverage.

## Default Design Decisions

These are the default Phase W decisions. Slice 0 must confirm them before
behavior changes land. If any decision changes, update this section first and
keep fixtures, docs, matrix metadata, and implementation aligned with the
revised rule.

- Phase W is long-only and uses the current one-net-long broker.
- Phase W stores multiple broker-owned pending exits internally, but does not
  expose a public pending-order list.
- Pending exit identity is `id + from_entry`.
- The internal pending collection preserves placement order.
- A call with a new identity adds a new pending exit if the matching entry is
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
- Zero-reservation placements are rejected with a stable diagnostic.
- Invalid prices, ticks, mintick, `qty`, or `qty_percent` preserve all existing
  pending exits.
- Same-side single-trigger exits that are touched on the same eligible bar fill
  in placement order until the position is flat or no touched exits remain.
- Cross-side ambiguity uses a deterministic side policy: if any downside exit
  and any upside exit are both touched on the same eligible bar, downside exits
  are the winning side. Only the winning side fills on that bar; opposite-side
  candidates remain pending if a position remains.
- Bracket both-hit behavior remains stop/loss-first.
- Trailing exits keep their current activation and ratchet semantics.
- Filled exits emit existing `strategy.exit` order events and existing closed
  trade records using absolute filled quantities.
- `strategy.closedtrades` increases by one per filled exit record.
- `strategy.opentrades` remains `1` while any supported long position remains
  open and becomes `0` only when the final remaining quantity closes.
- Public output remains schema-compatible. No new fields are required because
  order and trade records already expose absolute `qty`.

## Rules for Every Slice

- Read this document, the relevant phase audit docs, and the current code before
  editing.
- Execute Slice 0 first. Do not start structural or runtime behavior changes
  until the baseline tests pass and the Phase W reservation decisions are
  recorded as current.
- Add fixtures before or alongside behavior changes.
- Keep the compatibility matrix conservative. Only widen the `strategy.exit`
  row when semantic fixtures, runtime fixtures, host coverage, conformance
  metadata, docs, and verification evidence all exist for the exact reservation
  subset.
- Preserve indicator behavior. Indicator scripts must not gain broker state or
  strategy output.
- Keep strategy order calls rejected in UDFs and requested-context expressions
  under the existing side-effect policy.
- Do not silently change analyzer behavior for unsupported trigger shapes.
- Do not change runtime `schemaVersion: 3` in Phase W.
- Keep snapshots authoritative for public output shapes.
- Keep CLI, Python, and WASM behavior synchronized. A reservation fixture that
  runs in one host should expose the same public strategy result shape in every
  host.
- Keep existing single-pending, bracket, trailing, fixed-`qty`, and
  `qty_percent` fixtures passing unchanged unless the slice explicitly replaces
  the single-pending lifecycle with fixture-backed reservation behavior.
- Because the analyzer validates individual `strategy.exit` calls rather than
  broker-wide pending state, runtime placement must enforce the Phase W subset
  boundary. Do not rely on semantic analysis to prevent bracket, trailing, or
  omitted-quantity multi-reservation from widening earlier than documented.
- If a slice reveals a bug in the existing single-exit subset, stop, add a
  focused regression fixture or unit test, fix it, and close that small behavior
  slice before continuing.
- If the reservation model requires public pending-order records to be useful,
  stop and record a design-only audit instead of widening the public schema
  inside Phase W.
- Stage and commit only the current slice when implementing. Do not mix cleanup,
  docs drift, or unrelated code-review fixes into a behavior slice.

## Internal Structure Rules

- Keep `BrokerState` as the public strategy runtime facade exported by
  `pine-runtime`.
- Keep pending-exit identity, reservation helpers, and placement helpers in
  `crates/pine-runtime/src/strategy/broker/exits.rs` or a focused child module
  if `exits.rs` becomes too large.
- Keep fill construction and position reduction/reset logic in
  `crates/pine-runtime/src/strategy/broker/fills.rs`.
- Keep equity, position, profit, and trade-count accessors in
  `crates/pine-runtime/src/strategy/broker/accounting.rs`.
- Keep semantic validation in `crates/pine-sema/src/analyzer/strategy.rs`.
  Phase W should need minimal semantic changes because multiple calls already
  analyze individually.
- Keep runtime argument extraction and dispatch in
  `crates/pine-runtime/src/builtins/strategy.rs`.
- Keep builtin signature metadata in
  `crates/pine-builtins/src/namespaces/strategy.rs`.
- Keep Python and WASM bindings thin. They should map the shared strategy
  result model and must not duplicate reservation math or fill precedence.
- Prefer a small internal reservation model over scattering quantity math across
  stop, limit, profit, loss, bracket, and trailing helpers.
- Treat roughly 800 lines in a production Rust file as a review trigger. Split
  focused helpers before growing a multipurpose module.

## Intended Data Model

The final model should be explicit about both placement intent and reserved
absolute quantity.

Preferred persisted shape:

```text
PendingExit {
  id: String,
  from_entry: String,
  trigger: PendingExitTrigger,
  quantity: PendingExitQuantity,
  reserved_quantity: f64,
  last_update_bar_index: usize,
  placement_sequence: u64,
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

Rules:

- `Full` is the default when both `qty` and `qty_percent` are omitted.
- `Full` resolves to all currently unreserved position quantity.
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

If a separate reservation ledger becomes clearer, prefer an internal helper
rather than public output fields:

```text
PendingExitBook:
  exits: Vec<PendingExit>
  next_sequence: u64
```

## Slice 0: Baseline Lock And Reservation Decision Confirmation

Goal: confirm that Phase W is a narrow reservation phase, not a broad broker
emulator phase, and record that the default decisions above still match the live
repo before any code behavior changes.

Steps:

1. Read the strategy sections in `docs/CONFORMANCE.md`,
   `docs/EXECUTION_SEMANTICS.md`, `docs/LONG_TERM_EXECUTION_PLAN.md`,
   `docs/PHASE_U_AUDIT.md`, `docs/PHASE_V_AUDIT.md`, and
   `tests/fixtures/conformance.tsv`.
2. Read the live broker code:
   - `crates/pine-runtime/src/strategy/broker/mod.rs`
   - `crates/pine-runtime/src/strategy/broker/exits.rs`
   - `crates/pine-runtime/src/strategy/broker/fills.rs`
   - `crates/pine-runtime/src/strategy/broker/accounting.rs`
   - `crates/pine-runtime/src/builtins/strategy.rs`
   - `crates/pine-sema/src/analyzer/strategy.rs`
3. Confirm the existing single-pending behavior with focused tests.
4. Confirm the exact first positive subset:
   - multiple pending single-trigger exits;
   - explicit `qty` and `qty_percent`;
   - omitted quantity stays on the one-effective-pending full-position path;
   - bracket/trailing multi-reservation deferred until later slices.
5. Confirm reservation math:
   - release old reservation before replacement;
   - clamp fixed and percent quantities to unreserved quantity;
   - reject zero-reservation placements;
   - preserve old pending exits on invalid replacement.
6. Confirm same-bar fill precedence:
   - same-side candidates fill in placement order;
   - downside wins over upside when both sides are touched;
   - only the winning side fills on a mixed-side both-hit bar.
7. Confirm diagnostic codes and messages for zero-reservation and invalid
   reservation states. Prefer reusing `E_STRATEGY_EXIT_QTY` for invalid
   absolute quantity and adding a focused code only if existing codes are too
   ambiguous.
8. Do not change runtime behavior, conformance metadata, or snapshots in this
   slice unless the decisions above require a docs-only clarification.
9. Record the final decisions in this document before Slice 1 starts.

Suggested commands:

```text
cargo test -p pine-sema strategy
cargo test -p pine-runtime strategy
cargo test -p pine-cli strategy
cargo run -q -p pine-cli -- matrix
```

Exit criteria:

- The current Phase V strategy behavior is green.
- The exact first reservation subset is recorded as confirmed or explicitly
  revised in this document.
- The same-bar fill policy is recorded as confirmed or explicitly revised in
  this document.
- No compatibility claim is widened.

### Slice 0 Decision Record

Status: confirmed on 2026-06-01 from the live repository before behavior
changes.

Evidence read:

- `docs/CONFORMANCE.md`
- `docs/EXECUTION_SEMANTICS.md`
- `docs/LONG_TERM_EXECUTION_PLAN.md`
- `docs/PHASE_U_AUDIT.md`
- `docs/PHASE_V_AUDIT.md`
- `tests/fixtures/conformance.tsv`
- `crates/pine-runtime/src/strategy/broker/mod.rs`
- `crates/pine-runtime/src/strategy/broker/exits.rs`
- `crates/pine-runtime/src/strategy/broker/fills.rs`
- `crates/pine-runtime/src/strategy/broker/accounting.rs`
- `crates/pine-runtime/src/builtins/strategy.rs`
- `crates/pine-sema/src/analyzer/strategy.rs`

Confirmed baseline:

- The current broker is still long-only, one-net-position, no-pyramiding, and
  stores one `pending_exit: Option<PendingExit>`.
- Current `strategy.exit` support remains one broker-owned pending exit with
  optional fixed `qty` or `qty_percent`, no reservation ledger, and no public
  pending-order fields.
- `tests/fixtures/conformance.tsv` and the matrix still mark
  `strategy.exit` as `partial` and leave multiple pending exits, reservation
  behavior, and missing-entry forms unsupported.
- The analyzer validates each `strategy.exit` call shape individually. Phase W
  runtime placement must enforce broker-wide multiple-pending boundaries.

Confirmed Phase W first subset:

- Multiple pending exits open first only for single-trigger `stop`, `limit`,
  `profit`, and `loss` forms on the current matching long entry.
- Explicit fixed `qty` and `qty_percent` participate in the reservation model.
- Omitted quantity stays on the one-effective-pending full-position path and is
  outside the Phase W multiple-reservation claim.
- Bracket and trailing multiple-pending reservation remains deferred until a
  later explicit slice; until then, new-identity bracket/trailing calls must
  stay one-pending-compatible.

Confirmed reservation rules:

- Pending exit identity is `id + from_entry`.
- A same-identity replacement releases the old reservation before resolving the
  replacement quantity.
- Fixed `qty` and `qty_percent` resolve at placement time and clamp to the
  currently unreserved position quantity.
- `qty_percent > 100` remains allowed and reserves all currently unreserved
  quantity after clamping.
- Zero-reservation placements are rejected with a stable strategy diagnostic
  and leave existing pending exits unchanged.
- Invalid prices, ticks, mintick, `qty`, or `qty_percent` preserve all existing
  pending exits.
- Quantity-equivalence for repeated placements compares effective trigger plus
  resolved `reserved_quantity`, not the raw percent expression.

Confirmed fill and output policy:

- Same-side touched candidates fill in placement order until the position is
  flat or no touched candidates remain.
- If downside and upside single-trigger exits are both touched on the same
  eligible bar, downside is the winning side and only the winning side fills on
  that bar.
- Opposite-side candidates remain pending after a partial winning-side fill if
  a long position remains.
- Filled exits emit existing `strategy.exit` order events and closed-trade
  records with absolute quantities.
- Public runtime output remains `schemaVersion: 3` with the existing strategy
  result shape; Phase W does not add public pending-order, reservation,
  remaining-quantity, percent, side, or exit-reason fields.

Slice 0 made no runtime behavior, conformance metadata, snapshot, host binding,
or public schema changes.

Slice 0 verification:

```text
cargo test -p pine-sema strategy
cargo test -p pine-runtime strategy
cargo test -p pine-cli strategy
cargo run -q -p pine-cli -- matrix
```

All commands passed on the Slice 0 workspace. The matrix output still reports
`strategy.exit` as `partial` and broad `strategy.*` as `unsupported`, with
multiple pending exits and reservation behavior outside the current compatibility
claim.

## Slice 1: Pending Exit Collection Without Behavior Widening

Goal: migrate the broker from one optional pending exit to an internal
collection while preserving the current externally visible one-pending-exit
behavior.

Steps:

1. Introduce a focused internal pending-exit book, or replace
   `pending_exit: Option<PendingExit>` with a small collection while exposing
   helper methods that keep existing call sites simple.
2. Preserve current behavior in this slice:
   - every new placement still replaces the previous pending exit;
   - `strategy.close(id)` cancels matching pending state;
   - flat or mismatched-entry evaluation clears matching pending state;
   - repeated identical placement preserves the original eligibility bar.
3. Add helper methods for:
   - finding pending exit by `id + from_entry`;
   - iterating pending exits in placement order;
   - clearing exits for a matching entry;
   - computing current pending count for tests.
4. Update broker unit tests to assert the one-pending behavior through the new
   helpers.
5. Keep public structs, JSON output, conformance metadata, and snapshots
   unchanged.
6. Run focused strategy tests.

Suggested commands:

```text
cargo test -p pine-runtime strategy
cargo test -p pine-runtime --test incremental
cargo test -p pine-cli strategy
```

Exit criteria:

- All existing strategy snapshots remain unchanged.
- Broker internals can store or represent a collection, but runtime behavior is
  still one effective pending exit.
- No conformance row changes.
- No public output shape changes.

### Slice 1 Implementation Record

Status: completed on 2026-06-01.

Implemented changes:

- Replaced the broker's single internal `pending_exit: Option<PendingExit>`
  storage with `PendingExitBook`, a small broker-owned collection wrapper around
  `Vec<PendingExit>`.
- Added internal helper methods for:
  - current effective pending exit access;
  - same-identity lookup by `id + from_entry`;
  - placement-order iteration;
  - clearing exits for a matching entry;
  - pending-exit count checks.
- Preserved Slice 1 runtime behavior: every accepted new placement still
  replaces the previous effective pending exit, unchanged repeated placement
  preserves the original eligibility bar, `strategy.close(id)` cancels matching
  pending state, invalid placements preserve existing pending state, and fills
  clear the effective pending exit.
- Updated broker unit tests to assert one-pending behavior through the new
  collection helpers, including identity lookup and placement-order iteration.

No public runtime JSON, Python dictionary, WASM JSON, conformance metadata,
snapshot, semantic-analysis, or compatibility-claim changes were made.

Slice 1 verification:

```text
cargo fmt --check
cargo test -p pine-runtime strategy
cargo test -p pine-runtime --test incremental
cargo test -p pine-cli strategy
```

All commands passed on the Slice 1 workspace.

## Slice 2: Reservation Accounting Internals

Goal: add reservation calculation helpers behind the still-single-effective
behavior.

Steps:

1. Add a helper that computes total reserved quantity for the current matching
   entry.
2. Add a helper that computes available unreserved quantity:
   `max(position_size - reserved_quantity, 0)`.
3. Add a placement-time resolver that takes `ExitQuantityRequest` and returns
   an absolute `reserved_quantity` after matching-entry validation.
4. Preserve the old reservation when a replacement request is invalid.
5. Release an existing same-identity reservation before resolving its
   replacement.
6. Add unit tests for:
   - full quantity resolves to position size with no prior reservation;
   - fixed quantity clamps to unreserved quantity;
   - percent quantity resolves against current position size and clamps to
     unreserved quantity;
   - over-100 percent reserves all available unreserved quantity;
   - invalid fixed quantity preserves existing pending state;
   - invalid percent quantity preserves existing pending state;
   - zero available quantity rejects new placement and preserves existing
     pending state.
7. Keep user-visible multiple pending behavior closed in this slice if Slice 1
   kept replacement semantics. If the implementation naturally opens multiple
   records here, stop and split the behavior into Slice 3.

Suggested commands:

```text
cargo test -p pine-runtime strategy
cargo test -p pine-sema strategy
```

Exit criteria:

- Reservation math is unit-tested.
- Existing single-pending fixtures remain unchanged.
- Invalid placement never corrupts existing pending state.
- No compatibility claim is widened.

### Slice 2 Implementation Record

Status: completed on 2026-06-01.

Implemented changes:

- Added internal `reserved_quantity` storage to `PendingExit` while keeping
  `PendingExitQuantity` as the placement intent (`Full` or absolute `Fixed`).
- Added internal pending-book helpers for total reserved quantity and available
  unreserved quantity, with support for excluding a same-identity replacement
  reservation.
- Added a placement-time reservation resolver that resolves `Full`, fixed
  quantity, and percent quantity requests to an absolute reserved quantity.
- Kept Slice 2 user-visible behavior closed: accepted placements still replace
  the single effective pending exit, so existing one-pending fixtures and
  snapshots remain unchanged.
- Updated fill logic to use `reserved_quantity` as the fill ceiling, while
  still clamping to current remaining `position_size`.
- Added broker unit tests for full reservations, fixed and percent clamping,
  over-100 percent clamping, zero-available rejection, identity-release
  availability, and invalid-placement preservation of existing pending state.

No public runtime JSON, Python dictionary, WASM JSON, conformance metadata,
snapshot, semantic-analysis, or compatibility-claim changes were made.

Slice 2 verification:

```text
cargo fmt --check
cargo test -p pine-runtime strategy
cargo test -p pine-sema strategy
```

All commands passed on the Slice 2 workspace.

## Slice 3: Multiple Single-Trigger Fixed-Quantity Exits

Goal: open the first positive multiple-pending subset for explicit fixed
`qty` single-trigger exits.

Steps:

1. Change placement for a new `id + from_entry` to append a pending exit instead
   of replacing all pending exits.
2. Keep same-identity calls as replacements.
3. Restrict the first positive runtime claim to explicit fixed `qty` on
   single-trigger exits:
   - `stop + qty`;
   - `limit + qty`;
   - `profit + qty`;
   - `loss + qty`.
4. Keep bracket and trailing new-identity calls one-pending-compatible in this
   slice. If the runtime cannot restrict by trigger family cleanly, stop and
   split the placement path before claiming multiple pending support.
5. Implement fill evaluation for same-side multiple exits:
   - skip creation/replacement bars;
   - collect touched candidates;
   - process candidates in placement order;
   - fill each candidate up to its reserved quantity and the remaining position;
   - remove filled exits;
   - keep untouched exits pending if a position remains.
6. Add broker unit tests for:
   - two stop exits reserve partial quantities and both fill in placement order;
   - two limit exits reserve partial quantities and both fill in placement
     order;
   - replacing one exit releases and recalculates only that reservation;
   - a new exit that exceeds remaining unreserved quantity is reduced to the
     remaining unreserved quantity;
   - a new exit when no unreserved quantity remains is rejected;
   - full close cancels remaining pending exits.
7. Add runtime fixtures and snapshots for:
   - two fixed-`qty` stop exits;
   - two fixed-`qty` limit exits;
   - fixed-`qty` replacement preserving other pending exits;
   - over-reservation clamping.
8. Add the fixtures to the CLI golden snapshot harness.
9. Add incremental append coverage for the new runtime fixtures.
10. Update `tests/fixtures/conformance.tsv` only for the exact fixed-quantity
    multiple single-trigger subset.

Candidate fixture names:

```text
tests/fixtures/runtime/strategy_exit_reservation_qty_stop_multi.pine
tests/fixtures/runtime/strategy_exit_reservation_qty_limit_multi.pine
tests/fixtures/runtime/strategy_exit_reservation_qty_replacement.pine
tests/fixtures/runtime/strategy_exit_reservation_qty_clamp.pine
```

Suggested commands:

```text
cargo test -p pine-runtime strategy
cargo test -p pine-runtime --test incremental
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli matrix
```

Exit criteria:

- Multiple fixed-`qty` single-trigger exits work end to end.
- Existing one-exit, bracket, trailing, fixed-`qty`, and `qty_percent` fixtures
  remain green.
- Conformance text claims only the fixed-`qty` multiple single-trigger subset.
- Public output shape is unchanged.

### Slice 3 Implementation Record

Status: completed on 2026-06-01.

Implemented changes:

- Opened multiple pending exits only for explicit fixed-`qty` same-side
  single-trigger exits (`stop`, `limit`, and their `loss`/`profit` converted
  forms).
- Kept full-position exits, `qty_percent`, bracket exits, trailing exits, and
  mixed-side fixed-`qty` exits on the previous one-effective-pending
  replacement path.
- Added internal tracking to distinguish explicit fixed-`qty` reservation
  records from `qty_percent` records after both resolve to absolute quantities.
- Added placement-order evaluation for multiple fixed-`qty` stop/limit exits:
  creation/replacement bars are skipped, touched candidates fill in placement
  order, filled identities are removed, and untouched exits remain pending while
  the position remains open.
- Added broker tests for multi-stop and multi-limit fills, replacement
  reservation release, over-reservation clamping, zero-unreserved rejection,
  full-close cancellation, and the `qty_percent` one-pending boundary.
- Added runtime fixtures, golden snapshots, incremental coverage, and
  conformance text for the exact fixed-`qty` same-side single-trigger
  reservation subset.

No public runtime JSON, Python dictionary, WASM JSON, or strategy output schema
changes were made.

Slice 3 verification:

```text
cargo fmt --check
cargo test -p pine-runtime strategy
cargo test -p pine-sema strategy
cargo test -p pine-runtime --test incremental
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli runtime_outputs_match_golden_snapshots
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli matrix_output_matches_golden_snapshot
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli matrix
```

All commands passed on the Slice 3 workspace.

## Slice 4: Percent Reservation For Multiple Single-Trigger Exits

Goal: extend the Slice 3 multiple single-trigger subset to `qty_percent`.

Steps:

1. Reuse the reservation resolver from Slice 2 for percent quantities.
2. Confirm percent quantities resolve against the current open position size,
   not the unreserved quantity, then clamp to unreserved quantity.
3. Keep `qty + qty_percent` unsupported.
4. Add broker unit tests for:
   - two percent stop exits reserve expected absolute quantities;
   - percent plus fixed exits share the same reservation pool;
   - percent replacement releases old reservation first;
   - `qty_percent > 100` reserves all remaining unreserved quantity;
   - zero remaining unreserved quantity rejects the new percent placement.
5. Add runtime fixtures and snapshots for:
   - two `qty_percent` stop exits;
   - mixed fixed and percent exits;
   - percent replacement;
   - over-100 percent clamping.
6. Add incremental append coverage.
7. Add or update representative semantic fixtures only if needed. Most
   `qty_percent` calls already analyze individually after Phase V.
8. Update conformance notes and fixtures for the exact percent reservation
   subset.

Candidate fixture names:

```text
tests/fixtures/runtime/strategy_exit_reservation_qty_percent_stop_multi.pine
tests/fixtures/runtime/strategy_exit_reservation_qty_mixed_stop_multi.pine
tests/fixtures/runtime/strategy_exit_reservation_qty_percent_replacement.pine
tests/fixtures/runtime/strategy_exit_reservation_qty_percent_clamp.pine
```

Suggested commands:

```text
cargo test -p pine-runtime strategy
cargo test -p pine-runtime --test incremental
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli matrix
```

Exit criteria:

- Multiple percent reservations work end to end.
- Mixed fixed and percent reservations are deterministic.
- Existing Phase V single-exit percent fixtures remain green.
- Public output shape is unchanged.

### Slice 4 Implementation Record

Status: completed on 2026-06-01.

Implemented changes:

- Extended the Slice 3 multiple single-trigger reservation path from explicit
  fixed `qty` to explicit fixed `qty` or `qty_percent`.
- Kept percent sizing semantics placement-time and position-based:
  `qty_percent` resolves against the current open position size first, then
  clamps its reserved quantity to remaining unreserved quantity.
- Kept `qty + qty_percent` unsupported through the existing semantic guardrail;
  no semantic fixture changes were needed.
- Kept bracket, trailing, full-position exits, and mixed-side percent/fixed
  exits on the existing one-effective-pending replacement path.
- Added broker tests for two percent exits, mixed fixed/percent reservations,
  percent replacement reservation release, over-100 percent clamping, and
  zero-unreserved rejection.
- Added runtime fixtures, golden snapshots, incremental coverage, and
  conformance text for the exact percent reservation subset.

No public runtime JSON, Python dictionary, WASM JSON, or strategy output schema
changes were made.

Slice 4 verification:

```text
cargo fmt --check
cargo test -p pine-runtime strategy
cargo test -p pine-sema strategy
cargo test -p pine-runtime --test incremental
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli runtime_outputs_match_golden_snapshots
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli matrix_output_matches_golden_snapshot
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli matrix
```

All commands passed on the Slice 4 workspace.

## Slice 5: Cross-Side Fill Precedence And State Timing

Goal: cover deterministic mixed downside/upside behavior for multiple
single-trigger pending exits.

Steps:

1. Implement the Slice 0 mixed-side policy exactly.
2. If Slice 0 selected the recommended conservative rule, then on a bar where
   any downside and any upside candidate are both touched:
   - process downside candidates only;
   - process them in placement order;
   - keep untouched or opposite-side pending exits if a long position remains;
   - cancel all pending exits if the position becomes flat.
3. Add broker unit tests for:
   - downside and upside both touched, downside fills first;
   - multiple downside candidates fill in placement order;
   - upside candidates remain pending after a partial downside fill if a
     position remains;
   - position state, closed trade count, open trade count, and equity update
     after partial and full multi-exit fills.
4. Add runtime fixtures and snapshots for:
   - mixed stop/limit reservations on the same bar;
   - state variables before fill, on fill bar, and next bar;
   - branch/switch/loop placement interactions if not already covered.
5. Add incremental append coverage.
6. Update docs with the mixed-side OHLC policy.

Candidate fixture names:

```text
tests/fixtures/runtime/strategy_exit_reservation_mixed_side_precedence.pine
tests/fixtures/runtime/strategy_exit_reservation_state.pine
tests/fixtures/runtime/strategy_exit_reservation_interactions.pine
```

Suggested commands:

```text
cargo test -p pine-runtime strategy
cargo test -p pine-runtime --test incremental
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
```

Exit criteria:

- Same-bar mixed-side behavior is deterministic and documented.
- State variable timing matches existing pending-exit timing.
- Public strategy output and expression-time reads remain consistent with
  existing Phase M/N/R/S/U/V timing rules.

### Slice 5 Implementation Record

Status: completed on 2026-06-02.

Implemented changes:

- Opened mixed-side multiple pending reservations for explicit fixed `qty` or
  `qty_percent` single-trigger exits while keeping full-position, bracket, and
  trailing exits on the existing one-effective-pending replacement path.
- Implemented the Slice 0 mixed-side policy: touched candidates are collected
  for an eligible bar, downside stop/loss candidates win when both downside and
  upside candidates are touched, and only the winning side fills on that bar.
- Preserved placement-order fills within the winning side, removed only filled
  identities when a position remains, and kept opposite-side pending exits for
  later bars after partial downside fills.
- Added broker tests for mixed-side same-bar precedence, multiple downside
  placement-order fills, opposite-side pending preservation, and
  partial-to-full position/count/equity updates.
- Added runtime fixtures, golden snapshots, incremental coverage, conformance
  text, and docs for the mixed-side OHLC policy and state timing.

No public runtime JSON, Python dictionary, WASM JSON, or strategy output schema
changes were made.

Slice 5 verification:

```text
cargo fmt --check
cargo test -p pine-runtime strategy
cargo test -p pine-sema strategy
cargo test -p pine-runtime --test incremental
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli runtime_outputs_match_golden_snapshots
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli matrix_output_matches_golden_snapshot
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli matrix
```

All commands passed on the Slice 5 workspace.

## Slice 6: Bracket And Trailing Reservation Decision

Goal: decide whether Phase W should include bracket/trailing multiple-exit
reservation or close after the single-trigger subset.

Steps:

1. Review the passing Slice 3-5 evidence.
2. Decide whether bracket and trailing exits can share the same reservation
   model without new ambiguity:
   - bracket reservations have two possible trigger sides and existing
     stop/loss-first both-hit behavior;
   - trailing reservations have activation state and ratcheting active stops;
   - both must preserve public output shape.
3. If the answer is no, record a design-only deferral in this document and
   keep bracket/trailing multiple-pending behavior unsupported or explicitly
   outside the Phase W compatibility claim.
4. If the answer is yes, implement one family at a time:
   - bracket reservation fixtures first;
   - trailing reservation fixtures second;
   - no mixed bracket/trailing claims until both standalone families are
     fixture-backed.
5. Add broker tests for reservation release, replacement, fill precedence, and
   cancellation for the selected family.
6. Add runtime fixtures, snapshots, incremental coverage, conformance notes,
   and docs for the selected family.

Suggested commands:

```text
cargo test -p pine-runtime strategy
cargo test -p pine-runtime --test incremental
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli matrix
```

Exit criteria:

- Either bracket/trailing reservation is explicitly deferred with no behavior
  claim, or one selected family is fully fixture-backed.
- No ambiguous bracket/trailing behavior is silently claimed.
- Existing bracket/trailing single-exit fixtures remain green.

### Slice 6 Decision Record

Status: completed on 2026-06-02.

Decision: defer bracket and trailing multiple-exit reservation out of Phase W.

Evidence reviewed:

- Slice 3 opened explicit fixed-`qty` same-side single-trigger reservations.
- Slice 4 extended the same single-trigger reservation pool to `qty_percent`.
- Slice 5 opened mixed-side single-trigger reservations with the confirmed
  downside-wins same-bar policy.
- Existing bracket support is one pending exit with exactly one downside and one
  upside leg, including stop/loss-first behavior when both bracket legs are
  touched on the same eligible bar.
- Existing trailing support carries activation state and ratchets active stops
  upward across bars, with no fill on the activation bar.

Deferral rationale:

- Bracket reservations combine a reserved quantity with two trigger sides and
  existing both-hit leg precedence. Extending multiple pending brackets would
  require additional fixture-backed rules for bracket-vs-single-trigger,
  bracket-vs-bracket, and mixed bracket/single-trigger same-bar precedence.
- Trailing reservations combine a reserved quantity with per-exit activation
  state, active stop state, and ratchet timing. Extending multiple pending
  trailing exits would require additional fixture-backed rules for activation
  ordering, active-stop updates, trailing-vs-fixed single-trigger precedence,
  and replacement of active trailing state.
- Neither family needs public pending-order, reservation, remaining-quantity,
  bracket-leg, trailing-state, or exit-reason fields for the current public
  schema, but the behavior surface is large enough to deserve a separate
  explicit phase rather than being silently claimed inside Phase W.

Phase W boundary after Slice 6:

- Multiple pending reservations are supported only for explicit fixed `qty` or
  `qty_percent` single-trigger `stop`, `limit`, `profit`, and `loss` exits on
  the current matching long entry.
- Full-position exits, bracket exits, and trailing exits remain on the existing
  one-effective-pending replacement path.
- Bracket and trailing multiple-pending reservation remains unsupported and
  outside the Phase W compatibility claim.
- Public runtime JSON, Python dictionaries, WASM JSON, and
  `schemaVersion: 3` remain unchanged.

No runtime behavior, conformance metadata, public output schema, host binding,
or snapshot changes were made in Slice 6.

Slice 6 verification:

```text
cargo test -p pine-runtime strategy
cargo test -p pine-runtime --test incremental
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli matrix
git diff --check
```

All commands passed on the Slice 6 workspace.

## Slice 7: Host Surface Parity

Goal: prove the supported reservation subset round-trips identically through
CLI, Python, and WASM host surfaces.

Steps:

1. Add or extend a CLI strategy test that runs one representative reservation
   fixture and asserts the expected order/trade quantities, position snapshots,
   equity, diagnostics, and unchanged top-level runtime keys.
2. Add or extend a Python binding test in `python/tests` for the same fixture.
   Rebuild and reinstall the wheel before running pytest if linked Rust crates
   changed.
3. Add or extend a WASM test in `crates/pine-wasm/src/tests` for the same
   fixture.
4. Confirm no host binding duplicates reservation math, fill precedence, or
   quantity resolution.
5. Confirm runtime output remains `schemaVersion: 3`.
6. Confirm public strategy keys remain exactly:

   ```text
   orders
   trades
   position
   equity
   diagnostics
   ```

Suggested commands:

```text
cargo test -p pine-cli strategy
cargo test -p pine-wasm strategy
maturin build --manifest-path crates/pine-python/Cargo.toml --out dist
python3 -m pip install --force-reinstall dist/*.whl
python3 -m pytest python/tests
```

Exit criteria:

- CLI, Python, and WASM expose equivalent reservation results.
- No public strategy result keys are added, removed, or renamed.
- No host contains broker reservation logic.

### Slice 7 Implementation Record

Status: completed on 2026-06-02.

Representative host-parity fixture:

- `tests/fixtures/runtime/strategy_exit_reservation_mixed_side_precedence.pine`

Slice 7 added host-surface assertions for the same mixed-side reservation
fixture across:

- CLI: `strategy_exit_reservation_fixture_has_host_stable_shape`
- Python: `test_run_script_returns_strategy_exit_reservation_fixture_contract`
- WASM:
  `runs_strategy_exit_reservation_fixture_from_csv_to_public_strategy_json`

The host tests assert the shared public runtime contract:

- runtime output remains `schemaVersion: 3`;
- strategy result keys remain `orders`, `trades`, `position`, `equity`, and
  `diagnostics`;
- the fixture exposes the same absolute order and trade quantities:
  `0.5` for `XS` and `1.5` for `XL`;
- position snapshots show the remaining long position after the first fill and
  flat state after the second fill;
- diagnostics remain empty at both the runtime and strategy levels;
- internal reservation fields such as `pending`, `remainingQty`,
  `qtyPercent`, and `qty_percent` are not exposed publicly.

No host binding implements reservation math, fill precedence, or quantity
resolution. CLI, Python, and WASM continue to call the shared runtime path and
only serialize/project the resulting public strategy output.

## Slice 8: Conformance, Matrix, Docs, And Release Notes

Goal: synchronize the compatibility claim after behavior and host evidence
exist.

Steps:

1. Update `tests/fixtures/conformance.tsv`:
   - keep `strategy.exit` `partial`;
   - describe exactly the supported reservation subset;
   - reference the new positive reservation fixtures;
   - keep broad `strategy.*` `unsupported`;
   - keep missing-entry pre-placement, pyramiding, short exposure, public
     pending-order records, and rich strategy order families unsupported.
2. Refresh matrix snapshots:

   ```text
   UPDATE_SNAPSHOTS=1 cargo test -p pine-cli matrix_output_matches_golden_snapshot
   cargo test -p pine-cli matrix_output_matches_golden_snapshot
   ```

3. Update documentation that states strategy boundaries:
   - `README.md`
   - `docs/CONFORMANCE.md`
   - `docs/EXECUTION_SEMANTICS.md`
   - `docs/SEMANTIC_MODEL.md`
   - `docs/BUILTIN_SIGNATURES.md` if signature wording changes;
   - `docs/LONG_TERM_EXECUTION_PLAN.md`
4. Add a `docs/RELEASE_NOTES.md` entry describing:
   - the supported reservation subset;
   - placement-time reservation;
   - replacement behavior;
   - same-bar fill precedence;
   - unchanged public runtime schema;
   - still-unsupported broker features.
5. Keep historical phase docs unchanged unless they contain active, misleading
   current-state claims. If a historical doc references old unsupported
   fixtures that no longer exist, either leave it as historical record or add a
   small note in a separate docs-cleanup slice.
6. Run docs and matrix checks.

Suggested commands:

```text
cargo test -p pine-cli matrix
cargo test -p pine-cli matrix_output_matches_golden_snapshot
git diff --check
```

Exit criteria:

- Matrix output and docs claim exactly the implemented subset.
- No docs claim public pending-order records or full broker-emulator parity.
- Unsupported boundaries are explicit.

### Slice 8 Implementation Record

Status: completed on 2026-06-02.

Slice 8 synchronized the public compatibility claim after runtime,
incremental, and host evidence existed:

- `tests/fixtures/conformance.tsv` keeps `strategy.exit` `partial`, records the
  explicit fixed-`qty` or `qty_percent` single-trigger reservation subset, and
  keeps broad `strategy.*` unsupported outside the claimed subset.
- `tests/snapshots/matrix.json` was refreshed from the conformance matrix.
- `README.md`, `docs/BUILTIN_SIGNATURES.md`, `docs/EXECUTION_SEMANTICS.md`,
  `docs/SEMANTIC_MODEL.md`, and `docs/LONG_TERM_EXECUTION_PLAN.md` now state
  the Phase W reservation boundary without claiming public pending-order
  records, reservation fields, full broker-emulator parity, missing-entry
  pre-placement, short exposure, pyramiding, omitted-quantity multiple exits, or
  bracket/trailing multiple reservations.
- `docs/RELEASE_NOTES.md` includes an Unreleased Phase W entry covering
  placement-time reservation, same-identity replacement, mixed-side same-bar
  precedence, unchanged `schemaVersion: 3`, unchanged public strategy keys, and
  still-unsupported broker tails.

Slice 8 verification:

```text
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli matrix_output_matches_golden_snapshot
cargo test -p pine-cli matrix
cargo test -p pine-cli matrix_output_matches_golden_snapshot
git diff --check
```

All commands passed on the Slice 8 workspace.

## Slice 9: Audit And Release Verification

Goal: close Phase W with an audit that ties implementation, fixtures, docs, and
verification together.

Steps:

1. Create `docs/PHASE_W_AUDIT.md`.
2. Record:
   - supported surface;
   - unsupported boundaries;
   - public output and host behavior;
   - fixture evidence;
   - host evidence;
   - docs evidence;
   - verification results.
3. Mark this execution plan `Status: closed` only after the release gate passes.
4. Update `docs/LONG_TERM_EXECUTION_PLAN.md` to mark Phase W closed and to
   identify the next small strategy tail, if any.
5. Run focused verification:

   ```text
   cargo fmt --check
   cargo test -p pine-builtins strategy
   cargo test -p pine-sema strategy
   cargo test -p pine-runtime strategy
   cargo test -p pine-runtime --test incremental
   cargo test -p pine-runtime --test profile_fixtures
   cargo test -p pine-cli strategy
   cargo test -p pine-cli runtime_outputs_match_golden_snapshots
   cargo test -p pine-cli matrix
   cargo test -p pine-cli matrix_output_matches_golden_snapshot
   cargo test -p pine-wasm strategy
   maturin build --manifest-path crates/pine-python/Cargo.toml --out dist
   python3 -m pip install --force-reinstall dist/*.whl
   python3 -m pytest python/tests
   git diff --check
   ```

6. Run the closeout release gate:

   ```text
   scripts/verify.sh
   ```

Exit criteria:

- `docs/PHASE_W_AUDIT.md` exists and matches repo evidence.
- `docs/PHASE_W_EXECUTION_PLAN.md` is marked closed.
- Focused verification passes.
- `scripts/verify.sh` passes.
- The workspace is ready for a narrow Phase W commit.

### Slice 9 Implementation Record

Status: completed on 2026-06-02.

Slice 9 created `docs/PHASE_W_AUDIT.md`, tied the supported surface,
unsupported boundaries, public output contract, fixture evidence, host
evidence, docs evidence, and verification evidence together, and closed this
execution plan after the release gate passed.

Focused verification:

```text
cargo fmt --check
cargo test -p pine-builtins strategy
cargo test -p pine-sema strategy
cargo test -p pine-runtime strategy
cargo test -p pine-runtime --test incremental
cargo test -p pine-runtime --test profile_fixtures
cargo test -p pine-cli strategy
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli matrix
cargo test -p pine-cli matrix_output_matches_golden_snapshot
cargo test -p pine-wasm strategy
maturin build --manifest-path crates/pine-python/Cargo.toml --out dist
python3 -m pip install --force-reinstall dist/pine_compat_runtime-0.1.0-cp310-abi3-manylinux_2_35_x86_64.whl
python3 -m pytest python/tests
git diff --check
```

Release verification:

```text
scripts/verify.sh
```

All commands passed on the Slice 9 workspace.

## Expected Final Compatibility Boundary

At Phase W close, the expected claim should be no broader than:

- `strategy.exit` remains `partial`.
- Multiple pending exits are supported only for the fixture-backed explicit
  fixed-`qty` or `qty_percent` single-trigger subset.
- Reservation applies only to the current one-net-long position.
- Reserved quantities are absolute placement-time quantities.
- Fills emit existing order and trade records with absolute filled quantities.
- Public runtime schema remains `schemaVersion: 3`.
- Omitted-quantity full-position exits, bracket exits, and trailing exits remain
  on the one-effective-pending replacement path.
- Missing-entry pre-placement, multiple entries, pyramiding, short exposure,
  reversals, public pending-order records, rich order APIs, OCA behavior,
  commission, slippage, margin, strategy alerts, realtime broker rollback, and
  intrabar path reconstruction remain unsupported.
