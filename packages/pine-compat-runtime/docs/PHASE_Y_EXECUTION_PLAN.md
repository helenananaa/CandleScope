# Phase Y Strategy Exit Trailing Reservation Execution Plan

Status: closed on 2026-06-02. This document records the step-by-step execution
playbook for the narrow strategy phase after `docs/PHASE_X_AUDIT.md`.

Phase Y should extend the Phase W/X reservation model from explicit fixed
`qty` or `qty_percent` single-trigger and bracket exits to explicit fixed
`qty` or `qty_percent` trailing exits. It must not become an omitted-quantity
reservation, missing-entry pre-placement, short, pyramiding, public
pending-order, realtime broker rollback, or broker-emulator parity phase.

Every slice should leave the workspace shippable and should keep semantic
claims, broker behavior, public output contracts, fixtures, snapshots, host
bindings, conformance metadata, docs, and release verification in lockstep.

## Current Starting Point

The repository has closed the current strategy progression through Phase X.
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
- Phase W multiple reservations are supported for explicit fixed `qty` or
  `qty_percent` single-trigger exits.
- Phase X multiple reservations are supported for explicit fixed `qty` or
  `qty_percent` bracket exits, and single-trigger and bracket reservations can
  share the same reservation pool for the current matching long entry.
- Runtime fill code uses `reserved_quantity` as the fill ceiling and clamps to
  current remaining `position_size`.
- Runtime output remains `schemaVersion: 3`. `StrategyResult`,
  `StrategyOrderEvent`, `StrategyTrade`, `StrategyPositionSnapshot`, and
  `StrategyEquitySnapshot` shapes are unchanged.
- Multiple pending trailing exits, omitted-quantity multiple exits,
  missing-entry pre-placement, pyramiding, short exposure, reversals, public
  pending-order records, and strategy order families beyond the current subset
  remain unsupported.

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

## Phase Y Goal

Design and implement the first deterministic trailing-reservation subset for
multiple pending `strategy.exit` trailing calls without changing the public
strategy output schema.

The target positive subset, if confirmed by Slice 0, is:

- Keep the current long-only, one-net-position, no-pyramiding broker.
- Allow multiple pending trailing `strategy.exit` records for the current
  matching long entry when exits use different `id + from_entry` identities.
- Open multiple trailing reservations only when the trailing call has explicit
  fixed `qty` or explicit `qty_percent`.
- Continue replacing an existing pending exit when a call uses the same
  `id + from_entry` identity.
- Resolve every pending exit to an absolute reserved close quantity at
  placement time.
- Apply reservation before storing a pending exit so the sum of open
  reservations never exceeds the current open position size.
- Release the old reservation before resolving a replacement for the same
  `id + from_entry`.
- If a new trailing request has no remaining unreserved quantity, reject the
  new placement with a stable strategy diagnostic and leave existing pending
  exits unchanged.
- If a replacement request is invalid, preserve the previous pending exit and
  its reservation.
- Preserve current one-effective-pending behavior for omitted-quantity trailing
  exits.
- Preserve current activation behavior: a trailing exit is ineligible on its
  creation or replacement bar, activation happens on a later eligible bar, and
  activation never fills on the same bar.
- Preserve current active trailing behavior: an active trailing stop fills
  before ratcheting when `low <= active_stop`; otherwise the stop ratchets
  upward only when `high - offset` is above the current stop.
- Keep public runtime JSON, Python dictionaries, and WASM JSON on the existing
  strategy result shape and runtime `schemaVersion: 3`.

The Phase Y runtime claim should be deliberately small:

- Multiple pending trailing exits for the same current long entry.
- Supported trailing trigger shapes remain exactly:
  - `trail_price + trail_offset`
  - `trail_points + trail_offset`
- Explicit fixed `qty` and `qty_percent` reservations only.
- Omitted quantity remains on the existing one-effective-pending full-position
  path and is outside the multiple-reservation claim.
- Missing-entry pre-placement remains unsupported.

Phase Y is successful when supported trailing reservations execute
deterministically, round-trip through CLI/Python/WASM, are fixture- and
snapshot-covered including incremental parity, are marked appropriately in
`tests/fixtures/conformance.tsv`, are documented, and pass the full release
verification gate, while still-unsupported broker-lifecycle forms remain
diagnostic-only unsupported.

## Non-Goals

Do not include these in the Phase Y compatibility claim:

- Short exposure, reversals, pyramiding, or multiple simultaneous entries.
- Missing-entry pre-placement of pending exits.
- Omitted-quantity multiple pending exits.
- Omitted-quantity trailing reservations.
- Same-side bracket pairs `stop + loss` and `limit + profit`.
- Three-trigger and four-trigger calls.
- Invalid trailing combinations, trailing-plus-bracket combinations, or
  trailing plus fixed `stop`/`limit`/`profit`/`loss`.
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

These are the default Phase Y decisions. Slice 0 must confirm them before
behavior changes land. If any decision changes, update this section first and
keep fixtures, docs, matrix metadata, and implementation aligned with the
revised rule.

- Phase Y is long-only and uses the current one-net-long broker.
- Phase Y stores multiple broker-owned pending exits internally, but does not
  expose a public pending-order list.
- Pending exit identity remains `id + from_entry`.
- The internal pending collection preserves placement order.
- A call with a new identity adds a new pending trailing exit if the matching
  entry is open and enough unreserved quantity exists after clamping/resolution.
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
- A trailing exit has an activation price and an offset price distance.
- `trail_price + trail_offset` uses the explicit activation price and converts
  positive offset ticks using the fixed default `syminfo.mintick`.
- `trail_points + trail_offset` converts positive activation and offset ticks
  from `strategy.position_avg_price` using the fixed default `syminfo.mintick`.
- A pending trailing exit is ineligible on its creation/replacement bar through
  the existing `last_update_bar_index >= bar_index` guard.
- An inactive trailing exit activates when `high >= activation_price`.
- An activation updates that trailing exit to active state with
  `stop_price = high - offset_price_distance` and never fills on the activation
  bar.
- An active trailing exit is a downside candidate when `low <= stop_price`.
- If an active trailing exit is not touched, its stop ratchets upward only when
  `high - offset_price_distance > stop_price`.
- Trailing stop state updates are persisted for pending exits that remain open.
- If multiple downside candidates are touched on one eligible historical bar,
  including active trailing stops, they fill in placement order.
- If any downside candidate and any upside candidate are both touched across
  the pending collection on the same eligible historical bar, downside is the
  winning side. Only winning-side candidates fill on that bar; opposite-side
  candidates remain pending if a position remains.
- Newly activated trailing exits do not participate as fill candidates on their
  activation bar, even when another pending exit fills on that bar.
- Filled exits emit existing `strategy.exit` order events and existing closed
  trade records using absolute filled quantities.
- `strategy.closedtrades` increases by one per filled exit record.
- `strategy.opentrades` remains `1` while any supported long position remains
  open and becomes `0` only when the final remaining quantity closes.
- Public output remains schema-compatible. No new fields are required because
  order and trade records already expose absolute `qty`.

## Rules for Every Slice

- Read this document, `docs/PHASE_S_AUDIT.md`,
  `docs/PHASE_W_AUDIT.md`, `docs/PHASE_X_AUDIT.md`, and the current code
  before editing.
- Execute Slice 0 first. Do not start structural or runtime behavior changes
  until the baseline tests pass and the Phase Y trailing-reservation decisions
  are recorded as current.
- Add fixtures before or alongside behavior changes.
- Keep the compatibility matrix conservative. Only widen the `strategy.exit`
  row when semantic fixtures, runtime fixtures, host coverage, conformance
  metadata, docs, and verification evidence all exist for the exact
  trailing-reservation subset.
- Preserve indicator behavior. Indicator scripts must not gain broker state or
  strategy output.
- Keep strategy order calls rejected in UDFs and requested-context expressions
  under the existing side-effect policy.
- Do not silently change analyzer behavior for unsupported trigger shapes.
- Do not change runtime `schemaVersion: 3` in Phase Y.
- Keep snapshots authoritative for public output shapes.
- Keep CLI, Python, and WASM behavior synchronized. A trailing-reservation
  fixture that runs in one host should expose the same public strategy result
  shape in every host.
- Keep existing single-pending, single-trigger reservation, bracket
  reservation, trailing, fixed-`qty`, and `qty_percent` fixtures passing
  unchanged unless the slice explicitly widens trailing reservation with
  fixture-backed behavior.
- Because the analyzer validates individual `strategy.exit` calls rather than
  broker-wide pending state, runtime placement must enforce the Phase Y subset
  boundary. Do not rely on semantic analysis to prevent omitted-quantity
  multi-reservation or unsupported mixed trigger forms from widening earlier
  than documented.
- If a slice reveals a bug in the existing single-exit or Phase W/X
  reservation subset, stop, add a focused regression fixture or unit test, fix
  it, and close that small behavior slice before continuing.
- If the trailing-reservation model requires public pending-order records or
  trailing-state output to be useful, stop and record a design-only audit
  instead of widening the public schema inside Phase Y.
- Stage and commit only the current slice when implementing. Do not mix
  cleanup, docs drift, or unrelated code-review fixes into a behavior slice.

## Internal Structure Rules

- Keep `BrokerState` as the public strategy runtime facade exported by
  `pine-runtime`.
- Keep pending-exit identity, reservation helpers, trigger classification,
  trailing-state helpers, and placement helpers in
  `crates/pine-runtime/src/strategy/broker/exits.rs` or a focused child module
  if `exits.rs` becomes too large.
- Keep pending evaluation, trailing activation/ratchet decisions, and same-bar
  precedence in `crates/pine-runtime/src/strategy/broker/mod.rs`.
- Keep fill construction and position reduction/reset logic in
  `crates/pine-runtime/src/strategy/broker/fills.rs`.
- Keep equity, position, profit, and trade-count accessors in
  `crates/pine-runtime/src/strategy/broker/accounting.rs`.
- Keep semantic validation in `crates/pine-sema/src/analyzer/strategy.rs`.
  Phase Y should need minimal semantic changes because trailing calls already
  analyze individually after Phase S and quantity arguments already analyze
  individually after Phases U/V.
- Keep runtime argument extraction and dispatch in
  `crates/pine-runtime/src/builtins/strategy.rs`.
- Keep builtin signature metadata in
  `crates/pine-builtins/src/namespaces/strategy.rs`.
- Keep Python and WASM bindings thin. They should map the shared strategy
  result model and must not duplicate reservation math, trailing activation,
  ratcheting, fill precedence, or quantity resolution.
- Prefer a small internal trailing update helper over scattering activation,
  fill-candidate, and ratchet logic across single-pending and multiple-pending
  paths.
- Treat roughly 800 lines in a production Rust file as a review trigger. Split
  focused helpers before growing a multipurpose module.

## Intended Data Model

The existing Phase X data model should be retained and generalized narrowly for
trailing reservation.

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

PendingTrailingExit:
  spec: PendingTrailingSpec
  state: PendingTrailingState

PendingTrailingState:
  Inactive
  Active { stop_price: f64 }
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
  Trailing
  OneEffectivePendingOnly

PendingExitUpdate:
  NoChange
  Persist(PendingExit)
  Candidate { pending_exit: PendingExit, exit_price: f64, side: PendingExitSide }
```

Rules:

- `Full` is the default when both `qty` and `qty_percent` are omitted.
- `Full` stays outside Phase Y multiple-reservation support.
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
- Trailing trigger equivalence compares the resolved activation and offset spec
  for inactive exits. For active exits, unchanged repeated placement should
  preserve active state only when the existing Phase S equivalence rule says
  the placement is unchanged.
- Multiple-pending evaluation must persist trailing state updates for unfilled
  exits before removing filled identities or clearing all pending exits.

## Slice 0: Baseline Lock And Trailing Reservation Decision Confirmation

Goal: confirm that Phase Y is a narrow trailing-reservation phase, not a broad
broker emulator phase, and record that the default decisions above still match
the live repo before any code behavior changes.

Steps:

1. Check worktree state with `git status --short`. Protect unrelated local
   edits and stage only Phase Y files when implementing.
2. Read the strategy sections in `docs/CONFORMANCE.md`,
   `docs/EXECUTION_SEMANTICS.md`, `docs/SEMANTIC_MODEL.md`,
   `docs/LONG_TERM_EXECUTION_PLAN.md`, `docs/PHASE_S_AUDIT.md`,
   `docs/PHASE_W_AUDIT.md`, `docs/PHASE_X_AUDIT.md`, and
   `tests/fixtures/conformance.tsv`.
3. Read the live broker and dispatch code:
   - `crates/pine-runtime/src/strategy/broker/mod.rs`
   - `crates/pine-runtime/src/strategy/broker/exits.rs`
   - `crates/pine-runtime/src/strategy/broker/fills.rs`
   - `crates/pine-runtime/src/strategy/broker/accounting.rs`
   - `crates/pine-runtime/src/builtins/strategy.rs`
   - `crates/pine-sema/src/analyzer/strategy.rs`
4. Confirm the existing Phase S trailing behavior with focused tests.
5. Confirm the existing Phase W/X reservation behavior with focused tests.
6. Confirm the exact Phase Y positive subset:
   - multiple pending trailing exits;
   - explicit fixed `qty` and `qty_percent`;
   - only existing supported trailing trigger shapes;
   - omitted quantity stays on the one-effective-pending full-position path;
   - missing-entry pre-placement remains unsupported.
7. Confirm trailing reservation math:
   - release old reservation before replacement;
   - clamp fixed and percent quantities to unreserved quantity;
   - reject zero-reservation placements;
   - preserve old pending exits on invalid replacement.
8. Confirm trailing state policy:
   - creation/replacement bar ineligible;
   - activation never fills on the activation bar;
   - active stop fill is checked before ratchet;
   - ratchet only moves upward;
   - state updates persist for unfilled exits;
   - filled exits are removed by identity;
   - all pending exits clear when the position becomes flat.
9. Confirm mixed same-bar fill precedence:
   - active trailing stop fills are downside candidates;
   - single-trigger stop/loss, bracket downside, and active trailing downside
     candidates share placement-order filling;
   - downside candidates win over limit/profit/bracket-upside candidates;
   - opposite-side candidates remain pending after partial downside fills if a
     supported long position remains.
10. Confirm diagnostic codes and messages for zero-reservation and invalid
    reservation states. Prefer reusing `E_STRATEGY_EXIT_QTY`,
    `E_STRATEGY_EXIT_QTY_PERCENT`, `E_STRATEGY_EXIT_PRICE`,
    `E_STRATEGY_EXIT_TICKS`, `E_STRATEGY_EXIT_MINTICK`, and
    `E_STRATEGY_EXIT_ENTRY`.
11. Do not change runtime behavior, conformance metadata, or snapshots in this
    slice unless the decisions above require a docs-only clarification.
12. Record the final decisions in this document before Slice 1 starts.

Suggested commands:

```text
cargo test -p pine-sema strategy
cargo test -p pine-runtime strategy
cargo test -p pine-cli strategy
cargo run -q -p pine-cli -- matrix
```

Exit criteria:

- The current Phase S trailing behavior is green.
- The current Phase W/X reservation behavior is green.
- The exact first trailing-reservation subset is recorded as confirmed or
  explicitly revised in this document.
- The trailing same-bar update/fill policy is recorded as confirmed or
  explicitly revised in this document.
- No compatibility claim is widened.

### Slice 0 Decision Record

Status: confirmed on 2026-06-02 from the live repository before behavior
changes.

Repo-grounded baseline:

- `docs/CONFORMANCE.md`, `docs/EXECUTION_SEMANTICS.md`,
  `docs/SEMANTIC_MODEL.md`, `docs/LONG_TERM_EXECUTION_PLAN.md`,
  `docs/PHASE_S_AUDIT.md`, `docs/PHASE_W_AUDIT.md`,
  `docs/PHASE_X_AUDIT.md`, and `tests/fixtures/conformance.tsv` agree that
  Phase S trailing exits, Phase W single-trigger reservations, and Phase X
  bracket reservations are closed, while multiple pending trailing reservations
  remain unsupported.
- `PendingExitTrigger::reservation_family` currently classifies trailing exits
  as `OneEffectivePendingOnly`. `place_exit` opens the multiple-reservation
  path only for explicit fixed `qty` or `qty_percent` single-trigger and
  bracket exits, so explicit-quantity trailing calls still replace through the
  one-effective-pending path.
- The multiple-pending evaluator currently uses `touched_candidate`, which
  covers single-trigger and bracket candidates only. Trailing activation,
  active-stop fill, and ratchet behavior still live in the single-pending path.
- The analyzer validates each `strategy.exit` call shape individually and does
  not inspect broker-wide pending state. Phase Y runtime placement must enforce
  the multiple-reservation boundary.

Confirmed Phase Y positive subset:

- Keep the broker long-only, one-net-position, and no-pyramiding.
- Support multiple pending trailing exits only for the current matching long
  entry, only for different `id + from_entry` identities, and only when each
  trailing call has explicit fixed `qty` or explicit `qty_percent`.
- Supported trailing trigger forms remain exactly `trail_price + trail_offset`
  and `trail_points + trail_offset`.
- Omitted `qty` and omitted `qty_percent` trailing exits remain on the existing
  one-effective-pending full-position replacement path.
- Same-identity trailing calls replace after releasing the old reservation. If
  the replacement request is invalid, the old pending exit and reservation must
  remain unchanged.
- Missing-entry pre-placement, omitted-quantity multiple exits, `qty +
  qty_percent`, same-side pairs, invalid trailing combinations, shorts,
  pyramiding, public pending-order output, realtime broker rollback, and runtime
  schema changes remain outside Phase Y.

Confirmed reservation and diagnostic rules:

- Fixed `qty` resolves to `min(qty, unreserved_position_quantity)`.
- `qty_percent` resolves to `position_size * qty_percent / 100.0`, then clamps
  to currently unreserved position quantity. Values above `100` remain allowed.
- Zero-reservation placements reuse `E_STRATEGY_EXIT_QTY`.
- Invalid fixed `qty` reuses `E_STRATEGY_EXIT_QTY`; invalid `qty_percent`
  reuses `E_STRATEGY_EXIT_QTY_PERCENT`; invalid prices, ticks, mintick, and
  entry matching reuse the existing `E_STRATEGY_EXIT_PRICE`,
  `E_STRATEGY_EXIT_TICKS`, `E_STRATEGY_EXIT_MINTICK`, and
  `E_STRATEGY_EXIT_ENTRY` diagnostics.

Confirmed trailing state policy:

- A newly created or replaced trailing exit remains ineligible on its
  creation/replacement bar through `last_update_bar_index >= bar_index`.
- An inactive trailing exit activates on a later eligible bar when
  `high >= activation_price`; activation sets `stop_price = high -
  offset_price_distance` and never fills on that activation bar.
- An active trailing exit first checks `low <= active_stop`. If touched, it is a
  downside fill candidate at the active stop price. If not touched, it ratchets
  upward only when `high - offset_price_distance` is above the current stop.
- State updates for unfilled trailing exits must be persisted. Filled exits are
  removed by `id + from_entry`; all pending exits clear when the position
  becomes flat.

Confirmed mixed-collection rule:

- Phase Y should support one shared reservation pool containing explicit fixed
  `qty` or explicit `qty_percent` single-trigger, bracket, and trailing
  reservations for the current matching long entry.
- Active trailing stops participate as downside candidates. Single-trigger
  stop/loss, bracket downside, and active trailing downside candidates fill in
  placement order.
- If any downside candidate and any upside candidate are both touched on one
  eligible historical bar, downside candidates fill on that bar in placement
  order. Opposite-side candidates remain pending if a supported long position
  remains.
- Newly activated trailing exits do not participate as fill candidates on their
  activation bar, even when another pending exit fills on that bar.

Slice 0 does not widen conformance metadata, runtime behavior, public JSON,
Python dictionaries, WASM JSON, matrix snapshots, or compatibility claims.

## Slice 1: Trailing Update Helpers Without Behavior Widening

Goal: factor trailing activation, fill-candidate, and ratchet logic so multiple
pending evaluation can support trailing exits without opening new runtime
behavior yet.

Steps:

1. In `crates/pine-runtime/src/strategy/broker/exits.rs`, add or refactor
   helper methods on `PendingExitTrigger` or `PendingTrailingExit` for:
   - whether the trigger is eligible for Phase Y trailing reservation;
   - activation detection for inactive trailing exits;
   - active-stop fill candidate detection;
   - ratchet calculation for active trailing exits;
   - side and price classification for touched trailing exits.
2. Keep current behavior unchanged:
   - single-trigger explicit `qty`/`qty_percent` reservations still append or
     replace according to Phase W rules;
   - bracket explicit `qty`/`qty_percent` reservations still append or replace
     according to Phase X rules;
   - trailing exits still use the one-effective-pending replacement path;
   - omitted-quantity exits still use the one-effective-pending replacement
     path.
3. Make the single-pending trailing path call the new helper if that makes the
   code easier to audit.
4. Do not wire trailing exits into multi-pending placement yet.
5. Add broker unit tests for helper behavior:
   - inactive trailing activation creates active state with the expected stop;
   - activation does not create a fill candidate;
   - active stop touched returns a downside candidate at the active stop price;
   - active stop not touched ratchets upward when eligible;
   - active stop does not ratchet downward;
   - creation/replacement bar remains ineligible through the existing guard.
6. Keep public structs, JSON output, conformance metadata, matrix snapshots,
   CLI/Python/WASM behavior, and runtime fixtures unchanged.

Suggested commands:

```text
cargo fmt --check
cargo test -p pine-runtime strategy
cargo test -p pine-cli strategy
```

Exit criteria:

- Helper tests prove trailing activation, fill, and ratchet classification.
- Existing trailing fixtures remain unchanged.
- Trailing multi-reservation is still not user-visible.
- No conformance row changes.
- No public output shape changes.

### Slice 1 Implementation Record

Status: completed on 2026-06-02.

Implemented changes:

- Added internal `PendingTrailingUpdate` classification for trailing no-change,
  persisted-state, and active-stop candidate outcomes.
- Added `PendingTrailingExit::evaluate_update` to centralize inactive
  activation, active-stop fill candidate detection, and upward-only ratchet
  calculation.
- Kept `PendingExitTrigger::reservation_family` returning
  `OneEffectivePendingOnly` for trailing exits, so trailing reservations remain
  not user-visible in Slice 1.
- Rewired the single-pending trailing evaluation path to use the new helper
  without changing activation-bar, fill-before-ratchet, or ratchet semantics.
- Added broker unit tests for trailing helper activation/no-candidate behavior,
  active-stop candidate selection, upward ratcheting, and no downward ratchet.

No runtime fixture, conformance metadata, matrix snapshot, public output shape,
Python binding, or WASM binding changed in Slice 1.

Slice 1 verification:

```text
cargo fmt --check
cargo test -p pine-runtime strategy
cargo test -p pine-cli strategy
```

All commands passed on the Slice 1 workspace.

## Slice 2: Fixed-Quantity Trailing Reservations

Goal: open the first positive multiple-pending trailing subset for explicit
fixed `qty` trailing exits.

Steps:

1. Generalize the internal reservation-family check so multiple reservations
   are allowed for:
   - existing explicit fixed `qty` or `qty_percent` single-trigger exits;
   - existing explicit fixed `qty` or `qty_percent` bracket exits; and
   - Phase Y explicit fixed `qty` trailing exits.
2. Keep `qty_percent` trailing multi-reservation closed until Slice 3.
3. Keep omitted-quantity trailing exits on the existing one-effective-pending
   replacement path.
4. Implement multiple-pending evaluation for trailing updates:
   - skip creation/replacement bars;
   - activate inactive trailing exits when eligible and persist the active
     state without filling on that bar;
   - collect active trailing downside candidates when `low <= active_stop`;
   - ratchet active trailing exits upward when they are not touched;
   - persist ratcheted state for exits that remain open;
   - fill winning-side candidates in placement order;
   - remove filled identities;
   - keep untouched or opposite-side exits pending if a position remains;
   - clear all pending exits if the position becomes flat.
5. Add broker unit tests for:
   - two fixed-`qty` trailing exits reserving partial quantities and activating
     independently;
   - two active trailing exits filling in placement order;
   - same-identity trailing replacement releasing and recalculating only that
     reservation;
   - a new trailing reservation exceeding remaining unreserved quantity
     clamping to the remaining unreserved quantity;
   - a new trailing reservation when no unreserved quantity remains being
     rejected;
   - a full trailing fill canceling remaining pending exits;
   - invalid trailing replacement preserving the old pending trailing exit;
   - unfilled active trailing exits ratcheting and persisting state.
6. Add runtime fixtures and snapshots for:
   - two fixed-`qty` `trail_price + trail_offset` exits activating and filling;
   - two fixed-`qty` `trail_points + trail_offset` exits;
   - fixed-`qty` trailing replacement preserving other pending exits;
   - fixed-`qty` trailing over-reservation clamping;
   - active trailing ratchet state across multiple pending exits.
7. Add the fixtures to the CLI golden snapshot harness.
8. Add incremental append coverage for the new runtime fixtures.
9. Update `tests/fixtures/conformance.tsv` only for the exact fixed-quantity
   trailing reservation subset, or defer conformance widening to Slice 5 if
   this slice is kept runtime-only.

Candidate fixture names:

```text
tests/fixtures/runtime/strategy_exit_reservation_qty_trailing_price_multi.pine
tests/fixtures/runtime/strategy_exit_reservation_qty_trailing_points_multi.pine
tests/fixtures/runtime/strategy_exit_reservation_qty_trailing_replacement.pine
tests/fixtures/runtime/strategy_exit_reservation_qty_trailing_clamp.pine
tests/fixtures/runtime/strategy_exit_reservation_trailing_state.pine
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

- Multiple fixed-`qty` trailing exits work end to end for the selected trailing
  forms.
- Existing one-exit, single-trigger reservation, bracket reservation, trailing,
  fixed-`qty`, and `qty_percent` fixtures remain green.
- Conformance text claims no more than the fixed-`qty` trailing reservation
  subset if conformance is updated in this slice.
- Public output shape is unchanged.

### Slice 2 Implementation Record

Status: completed on 2026-06-02.

Implemented changes:

- Added a distinct internal trailing reservation family and opened the
  multiple-reservation placement path only for explicit fixed `qty` trailing
  exits.
- Kept omitted-quantity trailing exits and `qty_percent` trailing exits on the
  existing one-effective-pending path.
- Extended multiple-pending evaluation to activate inactive trailing exits,
  persist active-state updates, collect active trailing downside candidates,
  ratchet unfilled active trailing exits upward, fill winning-side candidates
  in placement order, remove filled identities, and clear all pending exits
  when the position becomes flat.
- Added broker tests for fixed-`qty` trailing reservation placement,
  independent activation, placement-order fills, same-identity replacement,
  clamping, zero-unreserved rejection, invalid replacement preservation, full
  close cleanup, and ratcheted state persistence.
- Added runtime fixtures and snapshots for fixed-`qty` trailing price
  reservations, trailing points reservations, replacement, clamping, and state
  timing.
- Added `strategy_exit_reservation_trailing_bars.csv` so the new fixtures cover
  the bar after trailing reservation fills.
- Added the new fixtures to the CLI golden snapshot harness and incremental
  append parity harness.

Conformance wording and matrix claims were intentionally not widened in Slice
2; they remain conservative until the host-parity/conformance slice.

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

## Slice 3: Percent Trailing Reservations

Goal: extend the Slice 2 trailing-reservation subset to explicit
`qty_percent`.

Steps:

1. Reuse the existing reservation resolver for percent quantities.
2. Confirm percent quantities resolve against the current open position size,
   not the unreserved quantity, then clamp to unreserved quantity.
3. Keep `qty + qty_percent` unsupported through the existing semantic
   guardrail.
4. Keep omitted-quantity trailing exits on the one-effective-pending
   replacement path.
5. Add broker unit tests for:
   - two percent trailing exits reserve expected absolute quantities;
   - percent plus fixed trailing exits share the same reservation pool;
   - percent trailing replacement releases old reservation first;
   - `qty_percent > 100` reserves all remaining unreserved quantity;
   - zero remaining unreserved quantity rejects the new percent trailing
     placement;
   - invalid percent replacement preserves the old pending trailing exit.
6. Add runtime fixtures and snapshots for:
   - two `qty_percent` trailing exits;
   - mixed fixed and percent trailing exits;
   - percent trailing replacement;
   - over-100 percent trailing clamping.
7. Add incremental append coverage.
8. Add or update representative semantic fixtures only if needed. Most
   `qty_percent` trailing calls already analyze individually after Phase V.
9. Update conformance notes and fixtures for the exact percent trailing
   reservation subset, or defer final wording to Slice 5.

Candidate fixture names:

```text
tests/fixtures/runtime/strategy_exit_reservation_qty_percent_trailing_multi.pine
tests/fixtures/runtime/strategy_exit_reservation_qty_mixed_trailing_multi.pine
tests/fixtures/runtime/strategy_exit_reservation_qty_percent_trailing_replacement.pine
tests/fixtures/runtime/strategy_exit_reservation_qty_percent_trailing_clamp.pine
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

- Multiple percent trailing reservations work end to end.
- Mixed fixed and percent trailing reservations are deterministic.
- Existing Phase V single-exit percent fixtures remain green.
- Public output shape is unchanged.

### Slice 3 Implementation Record

Status: completed on 2026-06-02.

Implemented changes:

- Opened the multiple-reservation placement path for explicit
  `qty_percent` trailing exits.
- Reused the existing percent resolver so percent quantities resolve against
  current `position_size`, then clamp to currently unreserved quantity.
- Kept `qty + qty_percent` unsupported through the existing analyzer/runtime
  guardrail and kept omitted-quantity trailing exits on the one-effective
  replacement path.
- Added broker tests for two percent trailing reservations, fixed plus percent
  shared reservation pools, percent replacement, `qty_percent > 100` clamping,
  zero-unreserved rejection, and invalid percent replacement preservation.
- Added runtime fixtures and snapshots for percent trailing reservations,
  mixed fixed/percent trailing reservations, percent replacement, and percent
  clamping.
- Added the new fixtures to the CLI golden snapshot harness and incremental
  append parity harness.

Conformance wording and matrix claims remain conservative until the
host-parity/conformance slice.

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

## Slice 4: Mixed Single-Trigger, Bracket, And Trailing Reservation Interactions

Goal: cover deterministic interaction between Phase W single-trigger
reservations, Phase X bracket reservations, and Phase Y trailing reservations.

Steps:

1. Decide whether Phase Y supports mixed pending collections containing
   trailing reservations plus single-trigger or bracket reservations. The
   recommended decision is yes, because active trailing fills are downside
   candidates and inactive trailing activations are state updates.
2. If mixed-family support is accepted, ensure placement allows explicit fixed
   `qty` or `qty_percent` single-trigger, bracket, and trailing reservations to
   share the same reservation pool for the current matching long entry.
3. If mixed-family support is rejected, record the rejection in this document
   and keep runtime behavior one-effective-pending when incompatible pending
   families are mixed.
4. For the recommended support path, add broker tests for:
   - active trailing stop plus single-trigger stop both touched, fill in
     placement order on the downside side;
   - active trailing stop plus bracket downside both touched, fill in placement
     order on the downside side;
   - active trailing downside plus limit or bracket-upside candidates touched,
     downside wins;
   - inactive trailing activation plus upside candidate on the same bar, the
     trailing exit activates but does not fill;
   - opposite-side candidates remain pending after a partial downside fill;
   - same-identity replacement between trailing and single-trigger/bracket
     releases the old reservation before resolving the new one;
   - strategy close cancels all mixed-family pending exits for the entry.
5. Add runtime fixtures and snapshots for:
   - trailing plus single-trigger downside placement order;
   - trailing plus bracket downside placement order;
   - trailing downside winning over upside candidates;
   - inactive trailing activation while another reservation fills;
   - mixed-family replacement;
   - state variables before activation, after activation, on fill bar, and next
     bar.
6. Add incremental append coverage.
7. Update docs with the mixed-family OHLC and trailing-state policy.

Candidate fixture names:

```text
tests/fixtures/runtime/strategy_exit_reservation_trailing_single_downside_order.pine
tests/fixtures/runtime/strategy_exit_reservation_trailing_bracket_downside_order.pine
tests/fixtures/runtime/strategy_exit_reservation_trailing_mixed_side_precedence.pine
tests/fixtures/runtime/strategy_exit_reservation_trailing_activation_mixed_fill.pine
tests/fixtures/runtime/strategy_exit_reservation_trailing_replacement_mixed.pine
tests/fixtures/runtime/strategy_exit_reservation_trailing_mixed_state.pine
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

- Mixed single-trigger, bracket, and trailing reservations are deterministic,
  or are explicitly deferred without accidental runtime widening.
- Trailing activation and ratchet state remains deterministic when other exits
  fill.
- State variable timing matches existing pending-exit timing.
- Public strategy output and expression-time reads remain consistent with
  existing Phase M/N/R/S/U/V/W/X timing rules.

### Slice 4 Implementation Record

Status: completed on 2026-06-02.

Implemented changes:

- Confirmed the support path for mixed explicit fixed/percent single-trigger,
  bracket, and trailing reservation collections; no runtime widening was needed
  beyond the Slice 2/3 placement and evaluator paths.
- Added broker tests for trailing plus single-trigger downside placement order,
  trailing plus bracket downside placement order, trailing downside precedence
  over touched upside candidates, inactive trailing activation with a same-bar
  upside fill, cross-family same-identity replacement, and `strategy.close`
  cleanup across single-trigger, bracket, and trailing reservations.
- Added `strategy_exit_reservation_trailing_mixed_bars.csv` so runtime fixtures
  can activate, ratchet, and then trigger mixed candidates deterministically
  without ordinary stops/brackets filling before the intended bar.
- Added runtime fixtures and snapshots for trailing plus single-trigger downside
  order, trailing plus bracket downside order, trailing downside precedence over
  preserved upside candidates, activation with a mixed upside fill, mixed-family
  replacement, and mixed state-variable timing.
- Added the new fixtures to the CLI golden snapshot harness and incremental
  append parity harness.

Conformance wording and matrix claims remain conservative until the
host-parity/conformance slice.

Slice 4 verification:

```text
cargo fmt --check
cargo test -p pine-runtime strategy
cargo test -p pine-runtime --test incremental
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli matrix
```

All commands passed on the Slice 4 workspace.

## Slice 5: Host Parity, Conformance, And Public Shape Guardrails

Goal: prove the trailing-reservation subset through all host surfaces and align
the compatibility metadata conservatively.

Steps:

1. Select one representative Phase Y fixture for host parity. Prefer a fixture
   that includes:
   - two trailing reservations;
   - one activation without same-bar fill;
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
     `trailing`, `stop_price`, activation, pending-order, or exit-reason
     fields.
3. Add or update a Python binding test in `python/tests/test_bindings.py` using
   the same representative fixture.
4. Add or update a WASM test in `crates/pine-wasm/src/tests/mod.rs` using the
   same representative fixture.
5. Confirm CLI, Python, and WASM use the shared runtime path and do not
   implement reservation math, trailing activation, ratchet, or fill precedence
   in host bindings.
6. Update `tests/fixtures/conformance.tsv` and regenerate
   `tests/snapshots/matrix.json` if earlier slices did not already do so.
7. Keep the `strategy.exit` row `partial`.
8. Keep broad `strategy.*` `unsupported`.
9. Ensure conformance wording says no more than:
   - explicit fixed `qty` or `qty_percent` trailing reservations;
   - current one-net-long, no-pyramiding broker;
   - existing supported trailing shapes only;
   - no omitted-quantity trailing reservations;
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

- CLI, Python, and WASM expose the same Phase Y public strategy result.
- No host binding exposes internal reservation, trailing-state, activation, or
  pending-order details.
- Matrix and conformance match the exact implemented subset.
- Public runtime schema remains `schemaVersion: 3`.

### Slice 5 Implementation Record

Status: completed on 2026-06-02.

Implemented changes:

- Added `strategy_exit_reservation_trailing_host_parity.pine` with a fixed
  trailing reservation and a `qty_percent` trailing reservation sharing the
  same reservation pool. The dedicated host-parity bars activate both exits,
  fill one reservation partially on a later bar, then fill the remaining
  percent reservation on the final bar.
- Added CLI host-shape assertions for the representative Phase Y fixture,
  including order count, absolute filled quantities, fill prices, public
  position/trade shape, `schemaVersion: 3`, and absence of reservation,
  trailing-state, activation, pending-order, `qty_percent`, and exit-reason
  fields.
- Added matching WASM and Python binding tests using the same fixture and bars.
- Added the host-parity fixture to golden runtime snapshots and incremental
  append parity coverage.
- Updated `tests/fixtures/conformance.tsv` and `tests/snapshots/matrix.json`
  to claim only the implemented explicit fixed-`qty` or `qty_percent`
  single-trigger, bracket, and trailing reservation subset.
- Kept `strategy.exit` `partial` and broad `strategy.*` `unsupported`.

Host bindings still call the shared runtime path; no reservation math, trailing
activation, ratchet, or fill precedence was added to CLI, Python, or WASM
binding code.

Slice 5 verification:

```text
cargo fmt --check
cargo test -p pine-cli strategy
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli matrix_output_matches_golden_snapshot
cargo test -p pine-cli matrix
cargo test -p pine-wasm strategy
maturin build --manifest-path crates/pine-python/Cargo.toml --out dist
python3 -m pip install --force-reinstall dist/pine_compat_runtime-0.1.0-cp310-abi3-manylinux_2_35_x86_64.whl
python3 -m pytest python/tests
cargo test -p pine-runtime --test incremental
```

All commands passed on the Slice 5 workspace.

## Slice 6: Documentation Closeout And Audit

Goal: close Phase Y with an audit that ties implementation, fixtures, docs, and
verification evidence together.

Steps:

1. Create `docs/PHASE_Y_AUDIT.md`.
2. Record:
   - supported Phase Y subset;
   - unsupported boundaries;
   - public output shape;
   - runtime fixtures and snapshots;
   - host parity tests;
   - conformance/matrix evidence;
   - verification commands and results.
3. Update `docs/CONFORMANCE.md` to match `tests/fixtures/conformance.tsv`.
4. Update `docs/EXECUTION_SEMANTICS.md` with trailing-reservation placement,
   activation, ratchet, fill timing, same-bar precedence, and public-output
   rules.
5. Update `docs/SEMANTIC_MODEL.md` with the exact semantic/runtime boundary.
6. Update `docs/LONG_TERM_EXECUTION_PLAN.md`:
   - add or mark Phase Y closed;
   - list still-deferred broker tails;
   - recommend the next narrow strategy tail only after repo-grounded review.
7. Update `docs/RELEASE_NOTES.md` with a concise Phase Y entry.
8. Update README or user-facing support summaries only if they already mention
   strategy reservation support.
9. Do not mark omitted-quantity multiple exits, missing-entry pre-placement,
   short exposure, pyramiding, rich order APIs, public pending/reservation
   fields, or realtime broker rollback as supported.
10. Run docs-sensitive and focused verification.

Suggested commands:

```text
cargo fmt --check
cargo test -p pine-cli matrix
cargo test -p pine-cli matrix_output_matches_golden_snapshot
git diff --check
```

Exit criteria:

- `docs/PHASE_Y_AUDIT.md` exists and cites concrete fixture/test evidence.
- Roadmap, conformance docs, semantic docs, release notes, conformance TSV, and
  matrix snapshot agree.
- No unsupported broker tail is accidentally claimed.

### Slice 6 Implementation Record

Status: completed on 2026-06-02.

Implemented changes:

- Created `docs/PHASE_Y_AUDIT.md` with supported surface, unsupported
  boundaries, public output shape, runtime fixture/snapshot evidence, host
  parity tests, conformance/matrix evidence, and verification commands.
- Updated `docs/CONFORMANCE.md` to match the conformance TSV claim for explicit
  fixed-`qty` or `qty_percent` single-trigger, bracket, and trailing
  reservations.
- Updated `docs/EXECUTION_SEMANTICS.md` with trailing-reservation placement,
  activation, ratchet, same-bar precedence, and public-output rules.
- Updated `docs/SEMANTIC_MODEL.md` with the exact analyzer/runtime boundary and
  public schema guardrail.
- Added Phase Y to `docs/LONG_TERM_EXECUTION_PLAN.md`, marked it closed, and
  removed trailing reservations from the current next-tail examples.
- Updated `docs/RELEASE_NOTES.md` and `README.md` support summaries while keeping
  omitted-quantity multiple exits, missing-entry pre-placement, short exposure,
  pyramiding, public pending/reservation/trailing-state fields, and richer
  broker behavior unsupported.

Slice 6 verification:

```text
cargo fmt --check
cargo test -p pine-cli matrix
cargo test -p pine-cli matrix_output_matches_golden_snapshot
git diff --check
```

All commands passed on the Slice 6 workspace.

## Slice 7: Release Verification

Goal: run the canonical release gate and leave the workspace ready for a narrow
Phase Y commit.

Steps:

1. Check worktree state with `git status --short`.
2. Confirm the only intended Phase Y files are changed.
3. Run the full release gate.
4. If `scripts/verify.sh` fails:
   - fix in the smallest local slice if the failure is caused by Phase Y;
   - stop and report if the failure is environmental or unrelated.
5. Re-run `git diff --check` after any final formatting/docs edits.
6. Record final verification results in `docs/PHASE_Y_AUDIT.md`.
7. Stage only Phase Y files.
8. Commit with a narrow message, for example:

```text
Implement Phase Y trailing exit reservations
```

Suggested commands:

```text
git diff --check
scripts/verify.sh
git status --short
```

Exit criteria:

- `scripts/verify.sh` passes.
- The Phase Y audit contains final verification evidence.
- The staged/committed files contain only Phase Y work.
- The workspace is ready for the next repo-grounded phase selection.

### Slice 7 Implementation Record

Status: completed on 2026-06-02.

Implemented changes:

- Ran the final release gate after all Phase Y behavior, host parity,
  conformance, and documentation slices were committed.
- Updated `docs/PHASE_Y_AUDIT.md` from closeout-in-progress to closed and
  recorded canonical release verification evidence.
- Marked this execution plan closed.

Slice 7 verification:

```text
git diff --check
scripts/verify.sh
git status --short
```

`git diff --check` and `scripts/verify.sh` passed. `git status --short` showed
only pre-existing unrelated changes outside Phase Y:

```text
 M docs/PHASE_W_EXECUTION_PLAN.md
 M docs/PHASE_X_EXECUTION_PLAN.md
?? docs/CODE_REVIEW_FIX_AUDIT.md
```

## Closeout Claim

At Phase Y close, the expected claim should be no broader than:

- `strategy.exit` remains `partial`.
- Multiple pending trailing exits are supported only for the fixture-backed
  explicit fixed-`qty` or `qty_percent` trailing subset.
- Supported trailing shapes remain `trail_price + trail_offset` and
  `trail_points + trail_offset`.
- Reservation applies only to the current one-net-long position.
- Reserved quantities are absolute placement-time quantities.
- Trailing activation never fills on the activation bar.
- Active trailing fills are downside candidates and fill before ratcheting.
- Unfilled active trailing stops ratchet upward only.
- Fills emit existing order and trade records with absolute filled quantities.
- Public runtime schema remains `schemaVersion: 3`.
- Omitted-quantity full-position exits remain on the one-effective-pending
  replacement path.
- Missing-entry pre-placement, multiple entries, pyramiding, short exposure,
  reversals, public pending-order records, rich order APIs, OCA behavior,
  commission, slippage, margin, strategy alerts, realtime broker rollback, and
  intrabar path reconstruction remain unsupported.
