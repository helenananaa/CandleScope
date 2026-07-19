# Phase Z Strategy Exit Omitted-Quantity Boundary Execution Plan

Status: closed on 2026-06-02. This document is the step-by-step execution
playbook for the narrow strategy phase after `docs/PHASE_Y_AUDIT.md`.

Phase Z should close the omitted-quantity multiple-exit ambiguity left after the
Phase W/X/Y reservation work. It should be treated first as a design gate and
boundary-hardening phase. It must not become an omitted-quantity reservation
implementation, missing-entry pre-placement, short, pyramiding, public
pending-order, realtime broker rollback, or broker-emulator parity phase unless
Slice 0 proves that a smaller positive subset is already fixture-backed and
safe to claim.

Every slice should leave the workspace shippable and should keep semantic
claims, broker behavior, public output contracts, fixtures, snapshots, host
bindings, conformance metadata, docs, and release verification in lockstep.

## Current Starting Point

The repository has closed the current strategy progression through Phase Y. The
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
- Phase W supports multiple pending explicit fixed `qty` or `qty_percent`
  single-trigger reservations.
- Phase X supports multiple pending explicit fixed `qty` or `qty_percent`
  bracket reservations.
- Phase Y supports multiple pending explicit fixed `qty` or `qty_percent`
  trailing reservations.
- Single-trigger, bracket, and trailing explicit-quantity reservations share
  one internal reservation pool for the current matching long entry.
- Omitted `qty` and omitted `qty_percent` keep the current full-position exit
  behavior through the one-effective-pending replacement path.
- Runtime output remains `schemaVersion: 3`. `StrategyResult`,
  `StrategyOrderEvent`, `StrategyTrade`, `StrategyPositionSnapshot`, and
  `StrategyEquitySnapshot` shapes are unchanged.
- Multiple pending omitted-quantity exits, missing-entry pre-placement,
  pyramiding, short exposure, reversals, public pending-order records, and
  strategy order families beyond the current subset remain unsupported.

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

## Phase Z Goal

Lock the omitted-quantity `strategy.exit` boundary after Phase W/X/Y so that
the supported reservation claim remains explicit-quantity-only.

The expected Phase Z conclusion, if Slice 0 confirms the current repo behavior,
is:

- Keep the current long-only, one-net-position, no-pyramiding broker.
- Keep omitted `qty` and omitted `qty_percent` full-position exits on the
  existing one-effective-pending replacement path.
- Confirm that new omitted-quantity `strategy.exit` identities do not append
  independent reservations while any pending exit already exists.
- Confirm that omitted-quantity single-trigger, bracket, and trailing calls
  continue to replace the effective pending exit rather than sharing the Phase
  W/X/Y reservation pool.
- Confirm that same-identity omitted-quantity calls preserve the existing
  replacement semantics and creation/replacement-bar eligibility rules.
- Confirm that explicit fixed `qty` and explicit `qty_percent` reservations
  remain unchanged for single-trigger, bracket, and trailing exits.
- Confirm that mixing an omitted-quantity exit with explicit-quantity
  reservations falls back to one-effective-pending behavior only when the
  omitted-quantity call is involved, without corrupting reservation accounting.
- Add fixture and snapshot evidence for the exact boundary.
- Update documentation so user-facing compatibility claims do not imply
  omitted-quantity multiple reservations.
- Keep public runtime JSON, Python dictionaries, and WASM JSON on the existing
  strategy result shape and runtime `schemaVersion: 3`.

Phase Z is successful when the current omitted-quantity boundary is
fixture-backed across runtime, incremental execution, and host surfaces; docs and
matrix metadata stay conservative; and the release gate passes. Phase Z should
not widen the `strategy.exit` compatibility claim unless a later explicitly
approved slice designs, implements, and verifies a positive omitted-quantity
reservation subset.

## Non-Goals

Do not include these in the Phase Z compatibility claim:

- Multiple pending omitted-quantity reservations.
- Omitted-quantity bracket or trailing reservations.
- Any public pending-order records, reservation fields, remaining-quantity
  fields, percent fields, bracket-leg fields, trailing-state fields,
  activation fields, exit-reason fields, or a runtime schema bump.
- Missing-entry pre-placement of pending exits.
- Short exposure, reversals, pyramiding, or multiple simultaneous entries.
- Same-side bracket pairs `stop + loss` and `limit + profit`.
- Three-trigger and four-trigger calls.
- Invalid trailing combinations, trailing-plus-bracket combinations, or
  trailing plus fixed `stop`/`limit`/`profit`/`loss`.
- `qty + qty_percent`.
- `strategy.order`, `strategy.cancel`, `strategy.cancel_all`, OCA APIs,
  `comment`, `alert_message`, or strategy alert delivery.
- Commission, slippage, margin, currency conversion, percent-of-equity sizing,
  cash sizing, contracts sizing, or custom tick-size host metadata.
- Realtime strategy execution, forming-bar broker rollback, or intrabar path
  reconstruction.
- Full TradingView broker-emulator equivalence.
- Lower-timeframe request APIs, drawing object expansion, map/matrix support,
  or unrelated built-in coverage.

## Default Design Decisions

These are the default Phase Z decisions. Slice 0 must confirm them before any
fixture or docs claim lands. If any decision changes, update this section first
and keep fixtures, docs, matrix metadata, and implementation aligned with the
revised rule.

- Phase Z is long-only and uses the current one-net-long broker.
- Phase Z is boundary-hardening by default, not a positive capability expansion.
- Pending exit identity remains `id + from_entry`.
- The internal pending collection preserves placement order for supported
  explicit-quantity reservations.
- Explicit fixed `qty` and explicit `qty_percent` remain the only quantity
  forms that can enter the multiple-reservation placement path.
- `ExitQuantityRequest::Full` is the runtime representation for omitted
  `qty` plus omitted `qty_percent`.
- `PendingExitQuantity::Full` stays outside the multiple-reservation support
  subset.
- A `Full` request resolves to the available current position quantity only for
  the one-effective-pending replacement path. It does not reserve "all
  unreserved" quantity while preserving other pending exits.
- An omitted-quantity call with a new identity uses the one-effective-pending
  replacement path. It must not append beside existing supported
  explicit-quantity reservations, and it must clear or supersede incompatible
  pending state as one effective full-position exit.
- An omitted-quantity call must not leave behind stale reservations for exits it
  supersedes.
- An omitted-quantity replacement remains ineligible on its creation or
  replacement bar through the existing `last_update_bar_index` policy.
- Omitted-quantity single-trigger exits still close the full current remaining
  position when filled.
- Omitted-quantity bracket exits still represent one full-position bracket
  pending exit. Filling either leg removes the effective pending exit.
- Omitted-quantity trailing exits still represent one full-position trailing
  pending exit with the existing activation and ratchet behavior.
- Existing explicit fixed `qty` and `qty_percent` reservation fixtures must
  remain unchanged.
- Existing `qty + qty_percent`, missing-entry, invalid trigger, and unsupported
  strategy order diagnostics must remain unchanged.
- Public output remains schema-compatible. No new fields are required because
  Phase Z should not expose pending order or reservation state.

## Rules for Every Slice

- Read this document, `docs/PHASE_W_AUDIT.md`, `docs/PHASE_X_AUDIT.md`,
  `docs/PHASE_Y_AUDIT.md`, and the current code before editing.
- Execute Slice 0 first. Do not change runtime behavior until the current
  omitted-quantity behavior is reproduced and the intended boundary is
  confirmed.
- Add or update fixtures before or alongside implementation.
- Keep the compatibility matrix conservative. Only update
  `tests/fixtures/conformance.tsv` after the exact fixture-backed boundary is
  understood.
- Preserve indicator behavior. Indicator scripts must not gain broker state or
  strategy output.
- Keep strategy order calls rejected in UDFs and requested-context expressions
  under the existing side-effect policy.
- Do not silently change analyzer behavior for unsupported trigger shapes.
- Do not change runtime `schemaVersion: 3` in Phase Z.
- Keep snapshots authoritative for public output shapes.
- Keep CLI, Python, and WASM behavior synchronized.
- Keep existing single-pending, explicit fixed-`qty`, `qty_percent`,
  single-trigger reservation, bracket reservation, and trailing reservation
  fixtures passing unchanged.
- Because the analyzer validates individual `strategy.exit` calls rather than
  broker-wide pending state, runtime placement must enforce the Phase Z
  boundary. Do not rely on semantic analysis to prevent omitted-quantity
  multi-reservation from widening.
- If Slice 0 finds that live runtime behavior already differs from the
  documented boundary, stop and classify it as either:
  - a real behavior bug requiring a narrow fix; or
  - a docs/conformance drift requiring docs-only correction.
- If a slice reveals that omitted-quantity reservations require public
  pending-order records, OCA/reduce groups, or remaining-quantity public fields,
  stop and record a design-only audit instead of widening the public schema.
- Stage and commit only the current slice when implementing. Do not mix cleanup,
  docs drift, or unrelated code-review fixes into a behavior slice.

## Internal Structure Rules

- Keep `BrokerState` as the public strategy runtime facade exported by
  `pine-runtime`.
- Keep pending-exit identity, quantity resolution, reservation helpers, trigger
  classification, and placement helpers in
  `crates/pine-runtime/src/strategy/broker/exits.rs` or a focused child module
  if `exits.rs` becomes too large.
- Keep pending evaluation, trailing activation/ratchet decisions, and same-bar
  precedence in `crates/pine-runtime/src/strategy/broker/mod.rs`.
- Keep fill construction and position reduction/reset logic in
  `crates/pine-runtime/src/strategy/broker/fills.rs`.
- Keep equity, position, profit, and trade-count accessors in
  `crates/pine-runtime/src/strategy/broker/accounting.rs`.
- Keep semantic validation in `crates/pine-sema/src/analyzer/strategy.rs`.
  Phase Z should need little or no semantic change because omitted-quantity
  calls already analyze individually.
- Keep runtime argument extraction and dispatch in
  `crates/pine-runtime/src/builtins/strategy.rs`.
- Keep builtin signature metadata in
  `crates/pine-builtins/src/namespaces/strategy.rs`.
- Keep Python and WASM bindings thin. They should map the shared strategy
  result model and must not duplicate replacement, reservation, fill precedence,
  or quantity resolution.
- Treat roughly 800 lines in a production Rust file as a review trigger. Split
  focused helpers before growing a multipurpose module.

## Intended Data Model

The existing Phase Y data model should be retained. Phase Z should mostly
confirm classification and boundary behavior.

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

Rules:

- `Full` is the default when both `qty` and `qty_percent` are omitted.
- `Full` stays outside Phase Z multiple-reservation support.
- `Fixed(qty)` stores the absolute requested close quantity as intent, but
  reserves only `min(qty, unreserved_position_quantity)`.
- `Percent(percent)` is transient. It resolves to
  `position_size * percent / 100.0`, then reserves no more than the currently
  unreserved position quantity.
- `reserved_quantity` is the fill ceiling for each pending exit.
- `multiple_reservation` must remain `false` for omitted-quantity pending
  exits.
- A supported explicit-quantity reservation may coexist with other supported
  explicit-quantity reservations.
- A `Full` omitted-quantity placement must not be used to append a new
  reservation beside existing pending exits.
- Fill code owns clamping a pending exit's quantity to the current remaining
  `position_size`.
- Fill code owns deciding whether the position becomes flat or remains open.

## Slice 0: Baseline Lock And Boundary Decision

Goal: confirm the live repo's omitted-quantity behavior and decide whether
Phase Z remains a boundary-hardening phase or must stop for a real bug.

Steps:

1. Check worktree state with `git status --short`. Protect unrelated local
   edits and stage only Phase Z files when implementing.
2. Read the strategy sections in `docs/CONFORMANCE.md`,
   `docs/EXECUTION_SEMANTICS.md`, `docs/SEMANTIC_MODEL.md`,
   `docs/LONG_TERM_EXECUTION_PLAN.md`, `docs/PHASE_W_AUDIT.md`,
   `docs/PHASE_X_AUDIT.md`, `docs/PHASE_Y_AUDIT.md`, and
   `tests/fixtures/conformance.tsv`.
3. Read the live broker and dispatch code:
   - `crates/pine-runtime/src/strategy/broker/mod.rs`
   - `crates/pine-runtime/src/strategy/broker/exits.rs`
   - `crates/pine-runtime/src/strategy/broker/fills.rs`
   - `crates/pine-runtime/src/strategy/broker/accounting.rs`
   - `crates/pine-runtime/src/builtins/strategy.rs`
   - `crates/pine-sema/src/analyzer/strategy.rs`
4. Confirm the existing explicit-quantity reservation behavior with focused
   tests.
5. Confirm the existing omitted-quantity single-pending behavior with focused
   tests.
6. Confirm the exact Phase Z boundary:
   - omitted-quantity single-trigger exits do not append multiple reservations;
   - omitted-quantity bracket exits do not append multiple reservations;
   - omitted-quantity trailing exits do not append multiple reservations;
   - omitted-quantity calls do not leave stale explicit reservations behind;
   - explicit fixed `qty` and explicit `qty_percent` reservations remain
     unchanged.
7. Check current fixture coverage for omitted-quantity replacement:
   - same-trigger repeated full-position exit;
   - bracket repeated full-position exit;
   - trailing repeated full-position exit;
   - omitted-quantity call after explicit reservation;
   - explicit reservation after omitted-quantity call.
8. If coverage is missing, list the exact fixtures needed in this document
   before adding them.
9. If behavior does not match the intended boundary, stop and write down the
   smallest fix slice before proceeding.
10. Do not update conformance metadata or support claims in Slice 0 unless this
    document itself needs a decision-record clarification.

Suggested commands:

```text
cargo test -p pine-sema strategy
cargo test -p pine-runtime strategy
cargo test -p pine-cli strategy
cargo run -q -p pine-cli -- matrix
```

Exit criteria:

- The live omitted-quantity behavior is recorded.
- The exact fixtures needed for Phase Z are listed.
- No compatibility claim is widened.
- Either Phase Z is confirmed as boundary-hardening, or the phase stops for a
  real behavior bug report.

### Slice 0 Decision Record

Status: completed on 2026-06-02.

Record:

- Current worktree state before Slice 0 edits:
  - branch `main` was ahead of `origin/main` by one commit;
  - `docs/PHASE_Z_EXECUTION_PLAN.md` was the only untracked file;
  - no unrelated tracked local edits were present.
- Commands run and results:
  - `cargo test -p pine-sema strategy` passed: 31 strategy fixture tests passed;
  - `cargo test -p pine-runtime strategy` passed: 180 strategy-filtered unit
    tests passed, plus the strategy profile fixture test;
  - `cargo test -p pine-cli strategy` passed: 8 CLI strategy tests passed;
  - `cargo run -q -p pine-cli -- matrix` passed and kept `strategy.exit`
    `partial` with multiple pending exits limited to explicit fixed-`qty` or
    `qty_percent` single-trigger/bracket/trailing reservation forms.
- Live omitted-quantity behavior from code inspection:
  - runtime dispatch maps omitted `qty` plus omitted `qty_percent` to
    `StrategyExitQuantityArg::Full`;
  - broker placement maps `ExitQuantityRequest::Full` to no
    `multiple_reservation_family`;
  - because `multiple_reservation_family` is `None`, omitted-quantity
    single-trigger, bracket, and trailing placements use `replace_all`, not
    `replace_or_append`;
  - omitted-quantity pending exits resolve to `PendingExitQuantity::Full`,
    reserve the current position for the one-effective-pending path, and set
    `multiple_reservation == false`.
- Explicit-quantity reservation behavior remains unchanged:
  - `Fixed(_)` and `Percent(_)` single-trigger, bracket, and trailing forms are
    the only forms that can enter the multiple-reservation placement path;
  - existing fixed-`qty`, `qty_percent`, bracket-reservation, and
    trailing-reservation tests passed unchanged.
- Existing fixture coverage:
  - same-identity full-position repeated single-trigger behavior is covered by
    existing broker/unit replacement tests;
  - same-identity omitted-quantity bracket replacement is covered by
    `tests/fixtures/runtime/strategy_exit_bracket_replacement.pine`;
  - same-identity omitted-quantity trailing replacement is covered by
    `tests/fixtures/runtime/strategy_exit_trailing_replacement.pine`;
  - explicit fixed-quantity and percent-quantity multiple reservations are
    covered for single-trigger, bracket, and trailing families.
- Missing Phase Z evidence to add in later slices:
  - broker test for different-id omitted-quantity single-trigger replacement;
  - broker test for different-id omitted-quantity bracket replacement;
  - broker test for different-id omitted-quantity trailing replacement;
  - broker tests for explicit reservation followed by omitted-quantity exit and
    omitted-quantity exit followed by explicit reservation;
  - runtime fixture and snapshot for omitted single-trigger replacement;
  - runtime fixture and snapshot for omitted bracket replacement;
  - runtime fixture and snapshot for omitted trailing replacement;
  - runtime fixture and snapshot for omitted exit replacing explicit
    reservations without exposing pending/reservation fields.
- Docs/conformance check:
  - `tests/fixtures/conformance.tsv`, `docs/CONFORMANCE.md`,
    `docs/EXECUTION_SEMANTICS.md`, `docs/SEMANTIC_MODEL.md`, and
    `docs/LONG_TERM_EXECUTION_PLAN.md` keep the reservation claim limited to
    explicit fixed `qty` or `qty_percent` single-trigger/bracket/trailing
    exits;
  - no current docs/conformance statement was found to be broader than live
    runtime behavior.
- Slice 0 decision:
  - Phase Z remains a boundary-hardening phase;
  - no behavior fix slice is required before Slice 1;
  - no compatibility claim should be widened in Slice 0.

## Slice 1: Broker Boundary Unit Tests

Goal: add focused broker tests that lock the omitted-quantity placement boundary
without changing public behavior.

Steps:

1. Add tests in `crates/pine-runtime/src/strategy/broker/tests.rs` for
   omitted-quantity single-trigger replacement:
   - open a long position;
   - place a full-position stop exit with one id;
   - place a full-position limit/profit/loss exit with a different id;
   - assert there is one effective pending exit, not two reservations;
   - assert `multiple_reservation == false`;
   - assert `quantity == PendingExitQuantity::Full`.
2. Add tests for omitted-quantity bracket replacement:
   - place a full-position bracket;
   - place a second full-position bracket with a different id;
   - assert the second call replaces the effective pending exit;
   - assert no stale reservation remains from the first bracket.
3. Add tests for omitted-quantity trailing replacement:
   - place a full-position trailing exit;
   - place a second full-position trailing exit with a different id;
   - assert the second call replaces the effective pending exit;
   - assert trailing creation/replacement bar ineligibility still applies.
4. Add tests for mixing omitted-quantity and explicit reservations:
   - explicit reservation followed by omitted-quantity exit;
   - omitted-quantity exit followed by explicit reservation;
   - explicit single-trigger plus bracket/trailing reservation after the
     omitted-quantity replacement.
5. Assert that supported explicit fixed `qty` and explicit `qty_percent`
   reservations still append when no omitted-quantity call is involved.
6. Do not update runtime fixtures, snapshots, conformance metadata, or public
   docs in this slice unless the tests expose a real bug.
7. If a test fails because live behavior is wrong, fix only the smallest
   broker placement/accounting bug and rerun focused tests.

Suggested commands:

```text
cargo fmt --check
cargo test -p pine-runtime strategy
cargo test -p pine-cli strategy
```

Exit criteria:

- Broker tests lock the omitted-quantity boundary.
- Explicit-quantity reservation tests remain green.
- No public output shape changes.
- No conformance widening.

### Slice 1 Implementation Record

Status: completed on 2026-06-02.

Record:

- Tests added in `crates/pine-runtime/src/strategy/broker/tests.rs`:
  - `omitted_quantity_single_trigger_with_new_identity_replaces_instead_of_appending`;
  - `omitted_quantity_bracket_with_new_identity_replaces_instead_of_appending`;
  - `omitted_quantity_trailing_with_new_identity_replaces_and_resets_eligibility`;
  - `omitted_quantity_exit_replaces_explicit_reservation_pool`;
  - `explicit_reservation_after_omitted_quantity_replaces_full_then_appends_supported_reservations`.
- Implementation changes required:
  - none; live broker placement already matched the Slice 0 boundary decision.
- Behavior bugs fixed:
  - none.
- Commands run and results:
  - `cargo fmt --check` passed;
  - `cargo test -p pine-runtime strategy` passed: 185 strategy-filtered unit
    tests passed, plus the strategy profile fixture test;
  - `cargo test -p pine-cli strategy` passed: 8 CLI strategy tests passed.
- Compatibility claim:
  - unchanged; no runtime fixtures, snapshots, conformance metadata, matrix
    metadata, or public docs were updated in Slice 1.

## Slice 2: Runtime Fixtures And Snapshots

Goal: add user-visible runtime fixtures that prove omitted-quantity calls remain
one-effective-pending across supported trigger families.

Steps:

1. Add a single-trigger omitted-quantity replacement fixture:
   - enter a long position;
   - place a full-position stop exit with one id;
   - place a full-position limit or profit exit with another id;
   - drive bars so only the second effective pending exit fills;
   - assert one `strategy.exit` order and one closed trade.
2. Add a bracket omitted-quantity replacement fixture:
   - place a full-position bracket with one id;
   - place a full-position bracket with another id;
   - drive bars so the second bracket's expected leg fills;
   - assert no output from the first bracket.
3. Add a trailing omitted-quantity replacement fixture:
   - place a full-position trailing exit with one id;
   - place a full-position trailing exit with another id;
   - drive activation and fill for the second trailing exit;
   - assert activation-bar behavior and final fill match the existing trailing
     rules.
4. Add a mixed omitted/explicit fixture:
   - place explicit fixed `qty` or `qty_percent` reservations;
   - place an omitted-quantity full-position exit;
   - assert the final public orders/trades show one effective full-position path
     and no public pending/reservation fields.
5. Add snapshots in `tests/snapshots/` through the existing snapshot update
   flow.
6. Add the fixtures to the CLI golden snapshot harness.
7. Add incremental append parity coverage for the new runtime fixtures.
8. Keep fixture names explicit about the boundary.

Candidate fixture names:

```text
tests/fixtures/runtime/strategy_exit_omitted_single_replacement.pine
tests/fixtures/runtime/strategy_exit_omitted_bracket_replacement.pine
tests/fixtures/runtime/strategy_exit_omitted_trailing_replacement.pine
tests/fixtures/runtime/strategy_exit_omitted_replaces_reservations.pine
```

Suggested commands:

```text
cargo fmt --check
cargo test -p pine-runtime --test incremental
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli strategy
```

Exit criteria:

- Runtime fixtures prove the omitted-quantity boundary for single-trigger,
  bracket, trailing, and mixed omitted/explicit cases.
- Snapshots expose only existing public strategy fields.
- Incremental append parity passes.
- No unsupported broker tail is claimed.

### Slice 2 Implementation Record

Status: completed on 2026-06-02.

Record:

- Added runtime fixtures and golden snapshots for omitted-quantity replacement
  across single-trigger, bracket, trailing, and mixed omitted/explicit
  reservation cases:
  - `tests/fixtures/runtime/strategy_exit_omitted_single_replacement.pine`
  - `tests/fixtures/runtime/strategy_exit_omitted_bracket_replacement.pine`
  - `tests/fixtures/runtime/strategy_exit_omitted_trailing_replacement.pine`
  - `tests/fixtures/runtime/strategy_exit_omitted_replaces_reservations.pine`
- Added all four fixtures to the CLI golden snapshot harness. The trailing
  omitted fixture uses the existing trailing bars fixture in both CLI snapshot
  execution and runtime incremental append parity.
- Snapshot inspection confirmed one effective public exit path in each fixture:
  `XL`, `XB2`, `XT2`, and `XFULL` respectively. The first/replaced exit ids and
  internal pending/reservation fields do not appear in the public snapshots.
- Commands run:
  - `UPDATE_SNAPSHOTS=1 cargo test -p pine-cli runtime_outputs_match_golden_snapshots`
  - `cargo fmt --check`
  - `cargo test -p pine-runtime --test incremental`
  - `cargo test -p pine-cli runtime_outputs_match_golden_snapshots`
  - `cargo test -p pine-cli strategy`
  - `git diff --check`
- No runtime implementation changes were required.

## Slice 3: Host Parity Boundary Coverage

Goal: prove the omitted-quantity boundary through CLI, Python, and WASM without
duplicating broker logic in host bindings.

Steps:

1. Pick one representative fixture from Slice 2, preferably
   `strategy_exit_omitted_replaces_reservations.pine` if it covers the mixed
   omitted/explicit boundary.
2. Add or update a CLI host-shape test that asserts:
   - runtime `schemaVersion` remains `3`;
   - public `strategy` keys remain `orders`, `trades`, `position`, `equity`,
     and `diagnostics`;
   - no public `pending`, `reservation`, `remainingQuantity`,
     `reservedQuantity`, `qtyPercent`, `triggerSide`, `activation`, or
     `exitReason` fields appear;
   - public order/trade quantities are absolute filled quantities.
3. Add a Python binding test in `python/tests/test_bindings.py` for the same
   fixture and assertions.
4. Add a WASM test in `crates/pine-wasm/src/tests/mod.rs` for the same fixture
   and assertions.
5. Ensure the host tests all call the shared runtime path.
6. Do not implement replacement or reservation math in host code.

Suggested commands:

```text
cargo fmt --check
cargo test -p pine-cli strategy
cargo test -p pine-wasm strategy
maturin build --manifest-path crates/pine-python/Cargo.toml --out dist
python3 -m pip install --force-reinstall dist/*.whl
python3 -m pytest python/tests
```

Exit criteria:

- CLI, Python, and WASM expose the same omitted-quantity boundary behavior.
- Host bindings stay thin.
- Public strategy result shape remains unchanged.

### Slice 3 Implementation Record

Status: completed on 2026-06-02.

Record:

- Added host-shape coverage for
  `tests/fixtures/runtime/strategy_exit_omitted_replaces_reservations.pine` in:
  - `crates/pine-cli/src/main.rs`;
  - `python/tests/test_bindings.py`;
  - `crates/pine-wasm/src/tests/mod.rs`.
- Each host test calls the existing shared runtime path and asserts:
  - public runtime `schemaVersion` remains `3`;
  - public `strategy` keys remain `orders`, `trades`, `position`, `equity`,
    and `diagnostics`;
  - the final public exit path is one `XFULL` order/trade with absolute
    quantity `2`;
  - internal pending, reservation, remaining-quantity, qty-percent, trigger,
    activation, and exit-reason fields do not appear.
- Commands run:
  - `cargo fmt --check`
  - `cargo test -p pine-cli strategy`
  - `cargo test -p pine-wasm strategy`
  - `maturin build --manifest-path crates/pine-python/Cargo.toml --out dist`
  - `python3 -m pip install --force-reinstall dist/pine_compat_runtime-0.1.0-cp310-abi3-manylinux_2_35_x86_64.whl`
  - `python3 -m pytest python/tests`
- No host-specific behavior issue was found, and no binding/runtime
  implementation changes were required.

## Slice 4: Conformance And Matrix Boundary Sync

Goal: synchronize machine-readable conformance metadata with the fixture-backed
Phase Z boundary without widening support.

Steps:

1. Update `tests/fixtures/conformance.tsv` only if the new fixtures need to be
   named in the `strategy.exit` row as boundary evidence.
2. Keep `strategy.exit` status as `partial`.
3. Keep broad `strategy.*` status as `unsupported`.
4. Ensure the `strategy.exit` row says:
   - explicit fixed `qty` or explicit `qty_percent` single-trigger, bracket,
     and trailing exits can keep multiple reserved pending exits;
   - omitted `qty` and omitted `qty_percent` preserve full-position
     one-effective-pending behavior;
   - multiple pending exits outside the explicit fixed-`qty` or
     `qty_percent` reservation subset remain unsupported.
5. Ensure the `strategy.*` row still lists omitted-quantity multiple exits and
   missing-entry forms as unsupported.
6. Regenerate `tests/snapshots/matrix.json` if conformance metadata changed.
7. Run matrix tests and inspect the text output for accidental claim widening.

Suggested commands:

```text
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli matrix_output_matches_golden_snapshot
cargo test -p pine-cli matrix
cargo test -p pine-cli matrix_output_matches_golden_snapshot
cargo run -q -p pine-cli -- matrix
```

Exit criteria:

- Matrix output and conformance TSV agree.
- `strategy.exit` remains `partial`.
- Broad `strategy.*` remains `unsupported`.
- Omitted-quantity multiple reservations are not claimed.

### Slice 4 Implementation Record

Status: completed on 2026-06-02.

Record:

- Updated `tests/fixtures/conformance.tsv`:
  - kept `strategy.exit` as `partial`;
  - kept broad `strategy.*` as `unsupported`;
  - added the four Slice 2 omitted-quantity runtime fixtures to the
    `strategy.exit` evidence list;
  - clarified that omitted `qty` and `qty_percent` keep full-position
    one-effective-pending behavior, including replacement across ids for
    single-trigger, bracket, and trailing forms and clearing earlier explicit
    reservations when a later omitted full-position exit is placed;
  - clarified that omitted-quantity multiple reservations remain unsupported.
- Regenerated `tests/snapshots/matrix.json`.
- Commands run:
  - `UPDATE_SNAPSHOTS=1 cargo test -p pine-cli matrix_output_matches_golden_snapshot`
  - `cargo test -p pine-cli matrix`
  - `cargo test -p pine-cli matrix_output_matches_golden_snapshot`
  - `cargo run -q -p pine-cli -- matrix`
- Final matrix wording:
  - `strategy.exit`: `partial`; notes include omitted full-position
    one-effective-pending replacement across ids and explicit-reservation
    clearing, plus unsupported omitted-quantity multiple reservations.
  - `strategy.*`: `unsupported`; notes include multiple pending exits outside
    the explicit fixed-`qty` or `qty_percent` reservation subset, including
    omitted-quantity multiple reservations.

## Slice 5: Documentation Closeout

Goal: close Phase Z with docs that tie the boundary fixtures, host parity, and
verification evidence together.

Steps:

1. Create `docs/PHASE_Z_AUDIT.md`.
2. Record:
   - Phase Z supported and unsupported surfaces;
   - the exact omitted-quantity boundary;
   - broker tests;
   - runtime fixtures and snapshots;
   - host parity tests;
   - conformance/matrix evidence;
   - verification commands and results.
3. Update `docs/CONFORMANCE.md` to match `tests/fixtures/conformance.tsv`.
4. Update `docs/EXECUTION_SEMANTICS.md` with omitted-quantity replacement,
   interaction with explicit reservations, and public-output rules.
5. Update `docs/SEMANTIC_MODEL.md` with the exact analyzer/runtime boundary.
6. Update `docs/LONG_TERM_EXECUTION_PLAN.md`:
   - add or mark Phase Z closed;
   - remove omitted-quantity multiple exits from the "next tail" examples if
     the boundary is now closed as unsupported and fixture-backed;
   - list the still-deferred broker tails, such as missing-entry pre-placement,
     short/pyramiding behavior, public pending-order records, and richer order
     APIs.
7. Update `docs/RELEASE_NOTES.md` with a concise Phase Z entry.
8. Update README or user-facing support summaries only if they already mention
   strategy reservation support.
9. Do not mark omitted-quantity multiple reservations, missing-entry
   pre-placement, short exposure, pyramiding, rich order APIs, public
   pending/reservation fields, or realtime broker rollback as supported.
10. Run docs-sensitive and focused verification.

Suggested commands:

```text
cargo fmt --check
cargo test -p pine-cli matrix
cargo test -p pine-cli matrix_output_matches_golden_snapshot
git diff --check
```

Exit criteria:

- `docs/PHASE_Z_AUDIT.md` exists and cites concrete fixture/test evidence.
- Roadmap, conformance docs, semantic docs, release notes, conformance TSV, and
  matrix snapshot agree.
- No unsupported broker tail is accidentally claimed.

### Slice 5 Implementation Record

Status: completed on 2026-06-02.

Record:

- Added `docs/PHASE_Z_AUDIT.md` with supported/unsupported boundaries,
  broker-test evidence, runtime fixture/snapshot evidence, host parity evidence,
  conformance/matrix evidence, and focused verification results.
- Synchronized omitted-quantity boundary wording in:
  - `README.md`;
  - `docs/CONFORMANCE.md`;
  - `docs/EXECUTION_SEMANTICS.md`;
  - `docs/SEMANTIC_MODEL.md`;
  - `docs/LONG_TERM_EXECUTION_PLAN.md`;
  - `docs/RELEASE_NOTES.md`.
- Updated `docs/LONG_TERM_EXECUTION_PLAN.md` with a closed Phase Z section and
  removed omitted-quantity multiple exits from the next-backlog examples.
- Remaining unsupported broker tails:
  - omitted-quantity multiple pending reservations;
  - missing-entry pre-placement;
  - short exposure, reversals, pyramiding, and multiple simultaneous entries;
  - public pending/reservation/remaining-quantity/trigger-side/activation/
    exit-reason fields;
  - richer order APIs and broker behavior, including `strategy.order`,
    `strategy.cancel`, OCA APIs, commission, slippage, margin, realtime
    strategy handoff, and intrabar path reconstruction.
- Commands run:
  - `rg -n "omitted-quantity bracket or trailing reservations|omitted-quantity brackets/trailing|omitted-quantity multiple exits|full-position multiple-pending exits|Multiple pending exits for omitted-quantity" README.md docs/CONFORMANCE.md docs/EXECUTION_SEMANTICS.md docs/SEMANTIC_MODEL.md docs/LONG_TERM_EXECUTION_PLAN.md docs/RELEASE_NOTES.md docs/PHASE_Z_AUDIT.md`
  - `cargo fmt --check`
  - `cargo test -p pine-cli matrix`
  - `cargo test -p pine-cli matrix_output_matches_golden_snapshot`
  - `git diff --check`

## Slice 6: Release Verification

Goal: run the canonical release gate and leave the workspace ready for a narrow
Phase Z commit.

Steps:

1. Check worktree state with `git status --short`.
2. Confirm the only intended Phase Z files are changed.
3. Run the full release gate.
4. If `scripts/verify.sh` fails:
   - fix in the smallest local slice if the failure is caused by Phase Z;
   - stop and report if the failure is environmental or unrelated.
5. Re-run `git diff --check` after any final formatting/docs edits.
6. Record final verification results in `docs/PHASE_Z_AUDIT.md`.
7. Mark this execution plan closed only after the release gate passes.
8. Stage only Phase Z files.
9. Commit with a narrow message, for example:

```text
Close Phase Z omitted-quantity exit boundary
```

Suggested commands:

```text
git diff --check
scripts/verify.sh
git status --short
```

Exit criteria:

- `scripts/verify.sh` passes.
- The Phase Z audit contains final verification evidence.
- This execution plan is marked closed.
- The staged/committed files contain only Phase Z work.
- The workspace is ready for the next repo-grounded phase selection.

### Slice 6 Implementation Record

Status: completed on 2026-06-02.

Record:

- Final verification commands and results:
  - `git diff --check` passed before the release gate;
  - `scripts/verify.sh` passed, covering formatting, clippy with
    `-D warnings`, workspace tests, structural guardrails, wasm32 checking for
    `pine-wasm`, Python wheel build/install, and Python binding tests;
  - `git status --short` was clean after the release gate.
- Final file list for this Slice 6 commit:
  - `docs/PHASE_Z_AUDIT.md`
  - `docs/PHASE_Z_EXECUTION_PLAN.md`
- Commit hash if committed: recorded by the Slice 6 commit.

## Closeout Claim

At Phase Z close, the expected claim should be no broader than:

- `strategy.exit` remains `partial`.
- Explicit fixed `qty` or explicit `qty_percent` single-trigger, bracket, and
  trailing exits remain the only supported multiple-reservation subset.
- Omitted-quantity full-position exits remain on the one-effective-pending
  replacement path.
- Omitted-quantity single-trigger, bracket, and trailing calls do not append
  independent reservations.
- Existing explicit-quantity reservation behavior remains unchanged.
- Fills emit existing order and trade records with absolute filled quantities.
- Public runtime schema remains `schemaVersion: 3`.
- Missing-entry pre-placement, multiple entries, pyramiding, short exposure,
  reversals, public pending-order records, rich order APIs, OCA behavior,
  commission, slippage, margin, strategy alerts, realtime broker rollback, and
  intrabar path reconstruction remain unsupported.
