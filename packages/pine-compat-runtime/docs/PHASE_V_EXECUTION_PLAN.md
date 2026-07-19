# Phase V Strategy Exit Percent Quantity Execution Plan

Status: closed for the current fixture-backed `qty_percent` partial-exit
subset. See `docs/PHASE_V_AUDIT.md`.

Phase V should widen only the current `strategy.exit` quantity surface by
adding a deterministic `qty_percent` subset on top of the Phase U fixed-`qty`
model. It must not become a reservation, multiple-pending-exit, pyramiding, or
broker-emulator parity phase.

Every slice should leave the workspace shippable and should keep semantic
claims, broker behavior, public output contracts, fixtures, snapshots, host
bindings, conformance metadata, docs, and release verification in lockstep.

## Current Starting Point

The repository has closed the current strategy progression through Phase U and
has also completed a cross-cutting code-review fix pass. The relevant strategy
baseline is:

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
- `strategy.close(id)` closes the full matching long position at the current
  bar close and cancels any matching pending exit.
- Strategy state variables are available in strategy-mode historical scripts:
  `strategy.position_size`, `strategy.position_avg_price`,
  `strategy.openprofit`, `strategy.netprofit`, `strategy.equity`,
  `strategy.closedtrades`, and `strategy.opentrades`.
- Single-trigger `strategy.exit` supports `stop`, `limit`, `profit`, and
  `loss` forms for one broker-owned pending exit on the current one-net-long
  entry.
- Bracket `strategy.exit` supports exactly one downside plus one upside leg:
  `stop + limit`, `stop + profit`, `loss + limit`, and `loss + profit`.
- Trailing `strategy.exit` supports exactly `trail_price + trail_offset` and
  `trail_points + trail_offset`.
- Optional fixed `qty` is supported on each currently supported trigger family.
  `qty` is evaluated once at placement time, must be finite and positive, and
  closes `min(qty, current position size)` on fill.
- The Phase U fixed-`qty` model leaves any remaining long position open at the
  same average price, records one existing order event and one existing closed
  trade for the filled quantity, and keeps the public result shape unchanged.
- `qty_percent`, multiple pending exits, reservation behavior, missing-entry
  pre-placement, pyramiding, short exposure, reversals, public pending-order
  records, and strategy order families beyond the current subset remain
  unsupported.
- Runtime output remains `schemaVersion: 3`. `StrategyResult`,
  `StrategyOrderEvent`, `StrategyTrade`, `StrategyPositionSnapshot`, and
  `StrategyEquitySnapshot` shapes are unchanged.
- The broker stores one current long position with `position_size`,
  `avg_price`, `entry_id`, `entry_bar_index`, and `entry_time`.
- The broker stores a single `pending_exit: Option<PendingExit>`.
- `PendingExit` already carries `PendingExitQuantity::Full` or
  `PendingExitQuantity::Fixed(f64)`.
- Runtime fill code already clamps fixed requested quantity to current
  `position_size` and handles partial fill accounting.
- `crates/pine-sema/src/analyzer/strategy.rs::strategy_exit_arg_family`
  currently treats `qty` as a supported quantity family and `qty_percent` as an
  unsupported option.
- `crates/pine-runtime/src/builtins/strategy.rs::eval_strategy_exit` currently
  extracts `qty` but does not extract or dispatch `qty_percent`.
- `crates/pine-builtins/src/namespaces/strategy.rs` currently lists `qty` in
  the `strategy.exit` signature but not `qty_percent`.

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
cargo test -p pine-wasm strategy
python3 -m pytest python/tests
```

The release closeout gate remains:

```text
git diff --check
scripts/verify.sh
```

## Phase V Goal

Design and implement the first deterministic `qty_percent` subset for
`strategy.exit` without changing the public strategy output schema.

The target positive subset, if confirmed by the Slice 0 design gate, is:

- Support `qty_percent=percent` on every currently supported `strategy.exit`
  trigger shape:
  - single-trigger `stop`, `limit`, `profit`, and `loss`;
  - bracket `stop + limit`, `stop + profit`, `loss + limit`, and
    `loss + profit`;
  - trailing `trail_price + trail_offset` and `trail_points + trail_offset`.
- `qty_percent` evaluates at placement time.
- `qty_percent` must evaluate to a finite positive number.
- The broker resolves `qty_percent` to an absolute close quantity at placement
  time using the current matching long position size:
  `position_size * qty_percent / 100.0`.
- The resolved absolute quantity is stored as the existing fixed pending-exit
  quantity. A pending exit does not retain a live percentage expression after
  placement.
- A resolved quantity greater than or equal to the current open position size
  closes the full position on fill, preserving the Phase U clamp behavior.
- A resolved quantity smaller than the current open position size closes only
  that quantity on fill, leaves the remaining long position open at the same
  average price, and clears the filled pending exit.
- Omitted `qty` and omitted `qty_percent` keep the current full-position exit
  behavior.
- `qty` and `qty_percent` in the same `strategy.exit` call remain unsupported.
- The existing one-pending-exit model remains. A new exit placement replaces
  the previous pending exit; there is no multi-exit reservation ledger.
- Public runtime JSON, Python dictionaries, and WASM JSON keep the existing
  strategy result shape and runtime `schemaVersion: 3`.

Phase V is successful when supported `qty_percent` exits analyze, execute,
round-trip through CLI/Python/WASM, are fixture- and snapshot-covered including
incremental parity, are marked appropriately in `tests/fixtures/conformance.tsv`,
are documented, and pass the full release verification gate, while every
still-unsupported quantity or broker-lifecycle form remains diagnostic-only
unsupported.

## Non-Goals

Do not include these in the Phase V compatibility claim:

- Quantity reservation across multiple exits.
- Multiple independent pending exits.
- Dynamic percentage reservation that changes after placement.
- Public pending-order records, remaining-quantity fields, partial-fill fields,
  percent fields, exit-reason fields, or a runtime schema bump.
- Missing-entry pre-placement of pending exits.
- Multiple simultaneous entries, pyramiding, short exposure, reversals, or
  separate long/short accounting.
- `strategy.order`, order modification APIs, `oca_name`, OCA reduce/cancel
  groups, `comment`, `alert_message`, or strategy alert delivery.
- Commission, slippage, margin, currency conversion, percent-of-equity sizing,
  cash sizing, contracts sizing, or custom tick-size host metadata.
- Realtime strategy execution, forming-bar broker rollback, or intrabar path
  reconstruction.
- Same-side bracket pairs, 3+ trigger calls, invalid trailing combinations, or
  any trigger form that is unsupported before Phase V.
- Broad TradingView broker-emulator equivalence beyond the explicit historical
  OHLC rules already documented for the supported subset.

## Phase V Default Design Decisions

Slice 0 must confirm these decisions before behavior changes land. If any
decision changes, update this section first and keep fixtures, docs, matrix
metadata, and implementation aligned with the revised rule.

- Phase V is long-only and uses the current one-net-long broker.
- Phase V keeps one broker-owned pending exit slot.
- Phase V adds `qty_percent` only for trigger shapes that already support
  omitted quantity and fixed `qty`.
- `qty_percent` is mutually exclusive with `qty`.
- `qty_percent` is evaluated at placement time, after `id` and `from_entry`
  and before the pending exit is stored.
- Broker placement should validate that a matching current long entry exists
  before resolving a percent quantity. A flat or mismatched-entry call should
  keep the existing flat or mismatched-entry diagnostic instead of being
  reported as a zero-quantity percent placement.
- `qty_percent` must be finite and positive. `na`, non-finite, zero, and
  negative values are rejected with a stable runtime diagnostic and leave any
  existing pending exit unchanged.
- `qty_percent` values above `100` are allowed in the first subset. They resolve
  to an absolute quantity larger than the current position and therefore clamp
  to a full close on fill, matching Phase U fixed-`qty` behavior.
- `qty_percent=100` is equivalent to a full-position pending exit at fill time,
  but it may still be stored as a fixed quantity resolved from the current
  position size.
- Resolved percentage quantities are stored as `PendingExitQuantity::Fixed`.
  Do not add a public or persistent percent variant unless Slice 0 changes the
  placement-time decision.
- Placement identity uses the resolved absolute quantity. For example,
  `qty=5` and `qty_percent=50` on a current position of `10` are equivalent
  pending quantities for eligibility-preservation purposes.
- If the current position size changes before a repeated `qty_percent` call
  places a new pending exit, the percentage is re-resolved against the new
  current position size at that new placement time.
- Partial fills emit one existing `strategy.exit` order event and one existing
  closed-trade record using the closed absolute quantity.
- Partial exits realize profit only for the closed absolute quantity:
  `(exit_price - entry_price) * closed_qty`.
- Cash increases by `closed_qty * exit_price`.
- `strategy.closedtrades` increases by one for each filled percent exit because
  the public `StrategyTrade` list records one closed trade per fill event.
- `strategy.opentrades` remains `1` after a partial percent exit if any long
  position remains open, and becomes `0` only when the final remaining quantity
  is closed.
- Script reads see pending-exit fills on the next bar, matching existing
  pending-exit timing. Public output and equity snapshots include the fill on
  the fill bar.
- Replacing a percent pending exit with a fixed `qty` pending exit, or a fixed
  `qty` pending exit with a percent pending exit, follows the same replacement
  rule after both forms resolve to absolute quantities.
- Public strategy output remains schema-compatible. No new fields are required
  because order and trade records already expose absolute `qty`.

## Rules for Every Slice

- Add fixtures before or alongside behavior changes.
- Keep the compatibility matrix conservative. Only widen the `strategy.exit`
  row when semantic fixtures, runtime fixtures, host coverage, conformance
  metadata, docs, and verification evidence all exist for the exact
  `qty_percent` subset.
- Preserve indicator behavior. Indicator scripts must not gain broker state or
  strategy output.
- Keep strategy order calls rejected in UDFs and requested-context expressions
  under the existing side-effect policy.
- Keep `qty_percent` diagnostic-only until analyzer acceptance and runtime
  dispatch land in the same slice.
- Do not land analyzer acceptance for `qty_percent` unless runtime dispatch in
  the same slice routes accepted forms into broker placement and cannot
  silently fall back to full-position behavior.
- Keep `qty + qty_percent` diagnostic-only unsupported.
- Treat the broker as deterministic runtime state. Core crates must not depend
  on account services, wall-clock time, host callbacks, filesystem, network,
  or host-specific tick metadata.
- Do not add public pending-order, reservation, remaining-quantity, or percent
  fields in Phase V.
- Do not change runtime `schemaVersion: 3` unless a later schema review opens a
  separate public contract phase.
- Keep CLI, Python, and WASM behavior synchronized. A percent-exit script that
  runs in one host should expose the same public strategy result shape in every
  host.
- Keep snapshots authoritative for public output shapes.
- Keep existing full-position and fixed-`qty` exit fixtures passing unchanged.
- If a slice discovers that `qty_percent` requires a broader broker model, stop
  the behavior slice and record a design-only audit instead of silently widening
  scope.

## Internal Structure Rules

- Keep `BrokerState` as the public strategy runtime facade exported by
  `pine-runtime`.
- Keep pending-exit identity and placement helpers in
  `crates/pine-runtime/src/strategy/broker/exits.rs`.
- Keep fill construction and position reduction/reset logic in
  `crates/pine-runtime/src/strategy/broker/fills.rs`.
- Keep equity, position, profit, and trade-count accessors in
  `crates/pine-runtime/src/strategy/broker/accounting.rs`.
- Keep semantic validation in `crates/pine-sema/src/analyzer/strategy.rs`.
- Keep runtime argument extraction and dispatch in
  `crates/pine-runtime/src/builtins/strategy.rs`.
- Keep builtin signature metadata in
  `crates/pine-builtins/src/namespaces/strategy.rs`.
- Prefer a small internal quantity request type for runtime placement, for
  example `ExitQuantityRequest::Full | Fixed(f64) | Percent(f64)`, if it avoids
  duplicating percent resolution across stop, limit, profit, loss, bracket, and
  trailing helpers.
- Store only the final pending quantity intent needed by fill evaluation. The
  preferred persisted pending representation remains
  `PendingExitQuantity::Full | PendingExitQuantity::Fixed(f64)`.
- Add helper structs or enums only when they reduce real duplication across
  stop/limit/profit/loss, bracket, and trailing placement.
- Watch structure guardrails while editing. `crates/pine-runtime/src/builtins/arrays.rs`
  is already close to the production-file limit, and strategy work should not
  cause unrelated file growth. Treat roughly 800 lines in a production Rust
  file as a review trigger and split focused helpers before growing a
  multipurpose module.

## Intended Data Model

Use the existing single pending-exit record and normalize percent quantities to
the Phase U fixed-quantity model at placement time.

Preferred persisted shape:

```text
PendingExit {
  id: String,
  from_entry: String,
  trigger: PendingExitTrigger,
  quantity: PendingExitQuantity,
  last_update_bar_index: usize,
}

PendingExitQuantity:
  Full
  Fixed(f64)
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
- `Fixed(qty)` stores the absolute requested close quantity evaluated at
  placement time.
- `Percent(percent)` is transient. It must be resolved before `PendingExit` is
  stored.
- `Percent(percent)` resolves to
  `PendingExitQuantity::Fixed(position_size * percent / 100.0)` after matching
  entry validation has confirmed that a current long position exists.
- Fixed and percent values must be finite and positive before a pending exit is
  stored.
- Quantity participates in placement equivalence through the persisted resolved
  quantity.
- Fill code owns clamping `Fixed(qty)` to the current `position_size`.
- Fill code owns deciding whether the position becomes flat or remains open.

## Slice 0: Baseline Lock And Percent Design Gate

Goal: confirm that Phase V is a narrow percent-quantity phase, not a broker
reservation or multiple-pending-exit phase.

Steps:

1. Read the strategy sections in `docs/CONFORMANCE.md`,
   `docs/LONG_TERM_EXECUTION_PLAN.md`, `docs/PHASE_U_AUDIT.md`, and
   `tests/fixtures/conformance.tsv`.
2. Confirm `strategy.exit` currently accepts the Phase M/N/R/S/U trigger and
   fixed-`qty` shapes and still rejects `qty_percent` through semantic
   diagnostics.
3. Confirm public strategy output already has `qty` fields on order and trade
   records, so no runtime schema bump is required for the first
   `qty_percent` subset.
4. Confirm the selected `qty_percent` rules:
   - placement-time evaluation;
   - finite positive values only;
   - resolve against current matching `position_size`;
   - store the resolved absolute quantity as fixed quantity;
   - clamp to current position size on fill;
   - no reservation ledger;
   - no multiple pending exits.
5. Confirm whether values above `100` are allowed and clamp to full close, or
   whether the phase should reject them. The recommended default is to allow
   them and reuse Phase U fixed-quantity clamping.
6. Confirm `qty` plus `qty_percent` stays unsupported.
7. Add or update design notes in this document before behavior changes if any
   decision differs from the defaults above.

Suggested commands:

```text
cargo test -p pine-sema strategy_exit
cargo test -p pine-runtime strategy_exit
cargo test -p pine-cli strategy
cargo run -q -p pine-cli -- matrix
```

Exit criteria:

- Existing Phase U strategy behavior is green.
- `qty_percent` baseline unsupported behavior is understood.
- The exact first supported `qty_percent` subset is recorded.
- No compatibility claim is widened.

Slice 0 decision record, 2026-06-01:

- Current strategy support remains the Phase U subset recorded in
  `tests/fixtures/conformance.tsv`: single-trigger, one-downside/one-upside
  bracket, trailing, and optional fixed-`qty` `strategy.exit` forms are partial;
  `qty_percent`, multiple pending exits, reservation behavior, and
  missing-entry forms remain unsupported.
- `docs/PHASE_U_AUDIT.md` confirms the first quantity subset is fixed absolute
  `qty`, with `qty_percent` explicitly deferred and no public runtime schema
  change.
- Runtime internals already provide the intended Phase V base:
  `PendingExitQuantity::Full | Fixed(f64)`, placement-time fixed quantity
  validation, fill-time clamping to current `position_size`, partial-fill
  accounting, and existing order/trade `qty` public fields.
- `crates/pine-sema/src/analyzer/strategy.rs` currently classifies `qty` as the
  supported quantity family and keeps `qty_percent` in the unsupported option
  family. `crates/pine-runtime/src/builtins/strategy.rs` extracts `qty` only.
- Official TradingView strategy documentation describes omitted `qty` and
  `qty_percent` as a 100% exit, uses `qty` or `qty_percent` for partial exit
  sizing, and says oversized exit order totals are automatically reduced to the
  open position. Phase V therefore keeps the recommended default:
  `qty_percent > 100` is allowed, resolves to an absolute quantity larger than
  the current position, and reuses Phase U fixed-quantity clamping to produce a
  full close.
- Official TradingView documentation also specifies that when both `qty` and
  `qty_percent` are supplied, `qty` sizes the order and `qty_percent` is
  ignored. Phase V intentionally does not claim that precedence behavior. The
  local first subset keeps `qty + qty_percent` diagnostic-only unsupported so
  this phase does not add another compatibility rule while opening percent
  sizing.
- Phase V remains a narrow placement-time percent-to-absolute-quantity phase.
  It does not introduce a reservation ledger, multiple independent pending
  exits, missing-entry pre-placement, public pending-order records, percent
  output fields, or a runtime schema bump.
- Compatibility metadata is not widened in Slice 0.

## Slice 1: Signature And Diagnostic Guardrails

Goal: make `qty_percent` a known strategy-exit option with stable diagnostics
while keeping it unsupported until runtime dispatch opens atomically.

Steps:

1. Add `qty_percent` to `STRATEGY_EXIT_PARAMS` in
   `crates/pine-builtins/src/namespaces/strategy.rs` if it is still absent.
2. Update builtin registry tests that assert `strategy.exit` parameter names or
   positions.
3. Keep `qty_percent` in an unsupported semantic family in
   `crates/pine-sema/src/analyzer/strategy.rs`.
4. Keep `qty_percent` diagnostic-only unsupported for every trigger shape.
5. Keep `qty + qty_percent` diagnostic-only unsupported.
6. Record diagnostic priority for calls that combine `qty_percent` with
   unsupported trigger shapes:
   - same-side pairs `stop + loss` and `limit + profit`;
   - 3+ trigger calls;
   - invalid trailing combinations;
   - calls without any trigger.
7. Add or keep negative semantic fixtures for:
   - `qty_percent` on an otherwise-supported single-trigger exit;
   - `qty + qty_percent`;
   - `qty_percent` with unsupported same-side or 3+ trigger calls if existing
     broad fixtures do not already cover it;
   - `qty_percent` in indicator scripts, requested-context expressions, or UDF
     side-effect contexts if existing broad fixtures do not already cover it.
8. Do not extract or route `qty_percent` in runtime dispatch in this slice
   unless the slice is intentionally combined with Slice 3.

Candidate fixture names:

```text
tests/fixtures/sema/unsupported_strategy_exit_qty_percent.pine
tests/fixtures/sema/unsupported_strategy_exit_qty_and_qty_percent.pine
tests/fixtures/sema/unsupported_strategy_exit_qty_percent_same_side.pine
```

Suggested commands:

```text
cargo test -p pine-builtins strategy
cargo test -p pine-sema strategy_exit
cargo test -p pine-cli matrix
```

Exit criteria:

- `qty_percent` is a documented known argument in builtin metadata if the
  signature changed.
- Analyzer still rejects every user-visible `qty_percent` form.
- Existing `qty` behavior remains accepted.
- Unsupported trigger-family diagnostics remain stable and documented.
- No runtime behavior or compatibility claim is widened.

Slice 1 decision record, 2026-06-01:

- Added `qty_percent` to the builtin `strategy.exit` signature metadata and to
  `docs/BUILTIN_SIGNATURES.md` as a known optional numeric argument.
- Kept `qty_percent` classified as an unsupported strategy-exit option in
  semantic analysis. User-visible `qty_percent` calls still stop before HIR
  lowering and do not reach runtime placement.
- Added a dedicated negative semantic fixture for
  `qty_percent` combined with same-side `stop + loss` triggers. The expected
  diagnostics keep both boundaries visible: `qty_percent` remains unsupported,
  and same-side trigger families remain unsupported.
- Kept `qty + qty_percent` diagnostic-only unsupported. Phase V still does not
  claim TradingView's `qty` precedence behavior.
- Added the new negative fixture to `tests/fixtures/conformance.tsv` and
  refreshed the matrix snapshot. This expands unsupported evidence only; it
  does not widen the supported compatibility claim.
- Runtime `strategy.exit` dispatch still extracts `qty` only. `qty_percent`
  routing is intentionally deferred until the atomic semantic/runtime support
  slice.

## Slice 2: Runtime Percent Quantity Resolution Internals

Goal: add the internal ability to resolve percent quantity requests without
opening user-visible analyzer support yet.

Steps:

1. Add a transient runtime quantity request representation if useful, for
   example `ExitQuantityRequest::Full | Fixed(f64) | Percent(f64)`.
2. Route existing omitted-quantity and fixed-`qty` runtime placement through
   the new representation without changing behavior.
3. Add a broker-side resolver that converts quantity requests to persisted
   `PendingExitQuantity` after matching-entry validation:
   - `Full` remains `Full`;
   - `Fixed(qty)` validates finite positive and stores `Fixed(qty)`;
   - `Percent(percent)` validates finite positive and stores
     `Fixed(position_size * percent / 100.0)`.
4. Preserve existing diagnostics for flat and mismatched-entry placement before
   percent resolution.
5. Add a stable runtime diagnostic for invalid percent values, for example
   `E_STRATEGY_EXIT_QTY_PERCENT` with message
   `` `strategy.exit` qty_percent must be finite and positive ``.
6. Ensure invalid percent values leave any existing pending exit unchanged.
7. Ensure fixed `qty` invalid values keep the existing Phase U diagnostic and
   behavior.
8. Add broker unit tests for internal percent placement if the new helper is
   reachable from broker tests:
   - `qty_percent=50` stores fixed half of the current position;
   - `qty_percent=100` stores fixed full current position;
   - `qty_percent>100` stores a fixed quantity larger than the position and
     later clamps to full close;
   - invalid percent leaves existing pending exit unchanged;
   - flat placement keeps the existing flat diagnostic.
9. Keep analyzer support closed so normal user scripts with `qty_percent` do
   not lower to runtime.

Suggested commands:

```text
cargo test -p pine-runtime strategy::broker
cargo test -p pine-runtime strategy_exit
cargo test -p pine-sema strategy_exit
```

Exit criteria:

- Existing full-position and fixed-`qty` behavior remains unchanged.
- Internal percent resolution is deterministic and placement-time only.
- Invalid percent values have stable runtime diagnostics.
- Analyzer still rejects user-script `strategy.exit(..., qty_percent=...)`
  forms, so no public compatibility claim is widened.
- No public output fields change.

Slice 2 execution record, 2026-06-01:

- Added internal broker quantity requests with `Full`, `Fixed`, and `Percent`
  variants. Persisted pending exits still store only `Full` or resolved
  `Fixed` quantities, so strategy output schema remains unchanged.
- Routed existing full-position and fixed-`qty` placement through the request
  layer. Fixed invalid quantity diagnostics remain `E_STRATEGY_EXIT_QTY`.
- Added percent placement helpers for the currently supported stop, limit,
  profit, loss, bracket, and trailing exit families. These helpers are internal
  broker/runtime API only; semantic analysis still rejects user scripts that
  pass `qty_percent`.
- Resolved valid percent values after matching-entry validation as
  `position_size * qty_percent / 100.0`. Percent values greater than 100 are
  stored as larger fixed requests and rely on the existing fill-time clamp to
  close no more than the open position.
- Added `E_STRATEGY_EXIT_QTY_PERCENT` for invalid percent values. Flat and
  mismatched-entry percent placements continue to emit `E_STRATEGY_EXIT_ENTRY`
  before percent validation and leave pending state unchanged.

## Slice 3: Atomic Semantic And Runtime Support For `qty_percent`

Goal: open the selected `strategy.exit(..., qty_percent=...)` surface in one
atomic slice so accepted scripts cannot fall through to full-position runtime
behavior.

Steps:

1. Update `StrategyExitArgFamily` in
   `crates/pine-sema/src/analyzer/strategy.rs` so `qty_percent` is classified
   as a percent quantity argument rather than an unsupported option.
2. Permit `qty_percent` only on trigger shapes already supported before
   Phase V:
   - single-trigger `stop`, `limit`, `profit`, and `loss`;
   - bracket `stop + limit`, `stop + profit`, `loss + limit`, and
     `loss + profit`;
   - trailing `trail_price + trail_offset` and `trail_points + trail_offset`.
3. Reject calls that contain both `qty` and `qty_percent`.
4. Keep `qty_percent` rejected for unsupported trigger shapes:
   - same-side pairs `stop + loss` and `limit + profit`;
   - 3+ trigger calls;
   - invalid trailing combinations;
   - calls without any trigger.
5. Validate only semantic shape in the analyzer. Do not require `qty_percent`
   to be const; runtime should evaluate supported numeric expressions at
   placement time.
6. Extract `qty_percent` in `eval_strategy_exit` in
   `crates/pine-runtime/src/builtins/strategy.rs`.
7. Evaluate `qty_percent` once at placement time, after `id` and `from_entry`.
8. Convert the runtime argument state to the quantity request representation:
   - omitted `qty` and omitted `qty_percent` means full;
   - present `qty` means fixed absolute quantity;
   - present `qty_percent` means percent quantity;
   - both present means analyzer should have rejected the script; keep a
     defensive runtime diagnostic or deterministic precedence guard.
9. Route single-trigger stop, limit, profit, and loss exits with percent
   quantity.
10. Route bracket exits with percent quantity.
11. Route trailing exits with percent quantity.
12. Ensure unsupported trigger shapes with `qty_percent` do not silently place
    a partial single-trigger exit.
13. Preserve existing runtime diagnostics for invalid trigger prices, invalid
    profit/loss ticks, invalid trailing offsets, flat state, mismatched
    `from_entry`, and invalid fixed `qty`.
14. Add positive semantic fixtures for:
    - single-trigger stop with `qty_percent`;
    - bracket with `qty_percent`;
    - trailing with `qty_percent`.
15. Convert `unsupported_strategy_exit_qty_percent.pine` and any other
    now-supported negative fixtures to supported fixtures only when their exact
    shape is in the Phase V subset.
16. Keep negative fixtures for `qty + qty_percent` and unsupported trigger
    shapes.

Candidate positive semantic fixture names:

```text
tests/fixtures/sema/supported_strategy_exit_qty_percent_stop.pine
tests/fixtures/sema/supported_strategy_exit_qty_percent_bracket.pine
tests/fixtures/sema/supported_strategy_exit_qty_percent_trailing.pine
```

Suggested commands:

```text
cargo test -p pine-builtins strategy
cargo test -p pine-sema strategy_exit
cargo test -p pine-runtime strategy_exit
```

Exit criteria:

- Analyzer and runtime accept the same selected `qty_percent` forms in the same
  slice.
- Runtime full-exit behavior remains unchanged when both `qty` and
  `qty_percent` are omitted.
- Fixed `qty` behavior remains unchanged.
- Invalid `qty_percent` does not replace an existing pending exit.
- `qty + qty_percent` remains diagnostic-only unsupported.

Slice 3 execution record, 2026-06-01:

- Reclassified `qty_percent` as a percent quantity argument in semantic
  analysis instead of an unsupported option.
- Opened `qty_percent` on the same trigger shapes that already supported fixed
  `qty`: single-trigger stop, limit, profit, and loss; one-downside/one-upside
  brackets; and valid trailing stop forms.
- Kept `qty + qty_percent` diagnostic-only unsupported and kept same-side,
  3+ trigger, invalid trailing, and triggerless forms rejected.
- Extracted and evaluated `qty_percent` once in `eval_strategy_exit`, after
  `id` and `from_entry`, and routed stop, limit, profit, loss, bracket, and
  trailing placements to the broker percent helpers added in Slice 2.
- Converted the now-supported negative semantic fixtures for stop/loss
  `qty_percent` into supported fixtures, added bracket and trailing supported
  semantic fixtures, and updated the builtin signature notes.
- Added runtime unit coverage proving accepted percent exits dispatch partial
  quantities for single-trigger, bracket, and trailing paths, and proving
  invalid percent values preserve an existing pending exit.

## Slice 4: Runtime Fixtures, Snapshots, And Incremental Parity

Goal: cover the supported percent quantity behavior through public runtime
fixtures and golden snapshots.

Steps:

1. Add runtime fixtures for representative percent exits:
   - stop partial percent fill;
   - limit partial percent fill;
   - bracket partial percent fill;
   - trailing partial percent fill;
   - `qty_percent=100` full close;
   - `qty_percent>100` full-clamp behavior;
   - repeated percent call preserving eligibility when the resolved quantity is
     unchanged;
   - changed percent call replacing pending exit and resetting eligibility;
   - percent exit state-variable behavior after partial fill.
2. Use dedicated bars CSV files only when the shared runtime bars do not
   express the needed stop/limit/bracket/trailing path.
3. Add each fixture to the CLI runtime snapshot harness in
   `crates/pine-cli/src/main.rs`.
4. Refresh only the intended runtime snapshots.
5. Add each new runtime fixture to incremental append parity coverage in
   `crates/pine-runtime/tests/incremental.rs`.
6. Confirm public runtime JSON still contains only the existing strategy keys:
   `orders`, `trades`, `position`, `equity`, and `diagnostics`.
7. Confirm order and trade `qty` values are absolute filled quantities, not
   percent values.
8. Confirm existing Phase U fixed-`qty` snapshots do not change.

Candidate runtime fixture names:

```text
tests/fixtures/runtime/strategy_exit_qty_percent_stop_partial.pine
tests/fixtures/runtime/strategy_exit_qty_percent_limit_partial.pine
tests/fixtures/runtime/strategy_exit_qty_percent_bracket_partial.pine
tests/fixtures/runtime/strategy_exit_qty_percent_trailing_partial.pine
tests/fixtures/runtime/strategy_exit_qty_percent_full.pine
tests/fixtures/runtime/strategy_exit_qty_percent_full_clamp.pine
tests/fixtures/runtime/strategy_exit_qty_percent_repeated.pine
tests/fixtures/runtime/strategy_exit_qty_percent_replacement.pine
tests/fixtures/runtime/strategy_exit_qty_percent_state.pine
```

Suggested commands:

```text
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-runtime strategy_exit
cargo test -p pine-runtime --test incremental
```

Exit criteria:

- New runtime fixtures and snapshots cover the selected percent subset.
- Full-position and fixed-`qty` snapshots remain stable except for intentional
  harness ordering changes, if any.
- Incremental append execution matches full historical execution for every new
  percent fixture.
- Public output shape remains unchanged.

Slice 4 execution record, 2026-06-01:

- Added public runtime fixtures and golden snapshots for stop, limit, bracket,
  and trailing partial percent exits; `qty_percent=100`; `qty_percent>100`
  full-clamp behavior; repeated unchanged percent placement; changed percent
  replacement; and state-variable behavior after a partial percent fill.
- Reused the existing default runtime bars except for trailing percent coverage,
  which uses the existing trailing bars fixture.
- Added the new fixtures to the CLI runtime snapshot harness and to incremental
  append parity coverage.
- Confirmed public strategy JSON still exposes only the existing strategy
  result shape and records absolute order/trade quantities rather than percent
  values.
- Updated conformance metadata and matrix snapshots to include the public
  percent runtime fixtures and the refined quantity support claim.

## Slice 5: Host Parity For CLI, Python, And WASM

Goal: prove the percent quantity subset round-trips through every public host
surface using the same shared runtime behavior.

Steps:

1. Add or update CLI host tests to assert a percent partial fixture produces:
   - one entry order;
   - one percent-resolved exit order with absolute filled `qty`;
   - one closed trade with the same absolute `qty`;
   - a remaining open position after a partial fill;
   - unchanged top-level runtime keys and strategy keys.
2. Add Python binding tests in `python/tests/test_bindings.py` for the same
   representative fixture.
3. Rebuild and reinstall the Python wheel before running Python tests if Rust
   or binding code changed.
4. Add WASM tests in `crates/pine-wasm/src/tests/mod.rs` for the same
   representative fixture.
5. Confirm CLI, Python, and WASM all serialize non-finite values and diagnostics
   according to the already shared output rules; do not duplicate percent math
   in bindings.
6. If new host helper code is needed, keep it thin and delegate to shared
   runtime code.

Suggested commands:

```text
cargo test -p pine-cli strategy
cargo test -p pine-wasm strategy
maturin build --manifest-path crates/pine-python/Cargo.toml --out dist
python3 -m pip install --force-reinstall dist/*.whl
python3 -m pytest python/tests
```

Exit criteria:

- CLI, Python, and WASM expose the same percent-resolved absolute quantities.
- Host output shapes remain unchanged.
- No host contains independent percent-fill math.

Slice 5 execution record, 2026-06-01:

- Reused the existing CLI host assertion for
  `strategy_exit_qty_percent_stop_partial.pine`, which checks one entry order,
  one percent-resolved exit order, one closed trade, remaining open position,
  and unchanged public strategy output shape.
- Added Python binding coverage for the same representative fixture and default
  runtime bars. The test asserts the shared runtime result keys, strategy keys,
  absolute order/trade quantity, remaining position, plot values, and empty
  diagnostics.
- Added WASM host coverage for the same representative fixture and default
  runtime bars. The test checks the same absolute quantity and remaining
  position through the serialized JSON host surface.
- Confirmed no new host helper or binding math was needed; CLI, Python, and
  WASM continue to delegate percent resolution to shared runtime code and do
  not expose internal pending, remaining, or percent fields.

## Slice 6: Conformance, Matrix, Docs, And Release Notes

Goal: widen the compatibility claim only after the implementation and host
evidence exist.

Steps:

1. Update the `strategy.exit` row in `tests/fixtures/conformance.tsv` to include
   the exact `qty_percent` subset and every new positive/negative fixture.
2. Keep the broad `strategy.*` unsupported row explicit about remaining
   unsupported strategy behavior:
   - quantity reservation;
   - multiple pending exits;
   - missing-entry pre-placement;
   - `qty + qty_percent`;
   - unsupported trigger families;
   - rich order APIs and rich reporting.
3. Refresh the matrix snapshot only after conformance changes are complete.
4. Update `docs/CONFORMANCE.md` to describe:
   - placement-time percent evaluation;
   - percent-to-absolute quantity resolution;
   - clamping to full close;
   - unchanged public output shape;
   - remaining unsupported broker behaviors.
5. Update `docs/EXECUTION_SEMANTICS.md` with the Phase V timing and accounting
   rule.
6. Update `docs/BUILTIN_SIGNATURES.md` if builtin strategy-exit parameters
   changed.
7. Update `docs/RELEASE_NOTES.md` with a conservative Phase V entry.
8. Update `docs/LONG_TERM_EXECUTION_PLAN.md` to mark Phase V closed only after
   verification and audit are complete. Before closeout, keep it as planned or
   in progress.
9. Add this execution plan to any doc index only if the surrounding index is
   being kept current for recent phases.

Suggested commands:

```text
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli matrix_output_matches_golden_snapshot
cargo test -p pine-cli matrix
cargo test -p pine-cli matrix_output_matches_golden_snapshot
cargo run -q -p pine-cli -- matrix
git diff --check
```

Exit criteria:

- `tests/fixtures/conformance.tsv`, `tests/snapshots/matrix.json`, semantic
  docs, release notes, and roadmap wording describe the same exact subset.
- No unsupported broker behavior is accidentally claimed.
- Matrix output is deterministic and snapshot-backed.

Slice 6 execution record, 2026-06-01:

- Confirmed `tests/fixtures/conformance.tsv` and `tests/snapshots/matrix.json`
  already name the same fixture-backed `qty_percent` subset and the remaining
  unsupported broker behaviors.
- Updated `docs/CONFORMANCE.md` to describe placement-time percent evaluation,
  percent-to-absolute quantity resolution, full-position clamping, unchanged
  public output shape, and the remaining unsupported `qty + qty_percent`,
  reservation, multiple-pending, and missing-entry boundaries.
- Updated `docs/EXECUTION_SEMANTICS.md`, `docs/RELEASE_NOTES.md`,
  `docs/LONG_TERM_EXECUTION_PLAN.md`, and `README.md` so user-facing strategy
  wording matches the conformance and matrix boundary. `docs/BUILTIN_SIGNATURES.md`
  already exposed `qty_percent` on `strategy.exit`, so no signature edit was
  needed in this slice.
- Left Phase V unclosed at Slice 6 so the final closed status could wait for
  the Slice 7 audit and release gate.

## Slice 7: Audit And Release Verification

Goal: close Phase V with an explicit audit and the full release gate.

Steps:

1. Create `docs/PHASE_V_AUDIT.md`.
2. Summarize each completed slice and the exact compatibility boundary.
3. Record supported `qty_percent` forms:
   - single-trigger forms;
   - bracket forms;
   - trailing forms;
   - placement-time percent resolution;
   - absolute quantity output;
   - clamping behavior.
4. Record unsupported boundaries:
   - `qty + qty_percent`;
   - reservation behavior;
   - multiple pending exits;
   - missing-entry pre-placement;
   - unsupported trigger shapes;
   - public schema changes;
   - richer broker simulation.
5. List semantic fixtures, runtime fixtures, snapshots, host tests,
   incremental tests, conformance rows, and docs changed by the phase.
6. Run focused verification commands for strategy, snapshots, hosts, and matrix.
7. Run the full release gate.
8. If the release gate fails on structure or lint, fix the smallest local issue
   and rerun the gate before marking the phase closed.
9. Update `docs/LONG_TERM_EXECUTION_PLAN.md` status from planned or in-progress
   to closed only after the audit and release gate pass.

Suggested focused verification:

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

Closeout gate:

```text
scripts/verify.sh
```

Exit criteria:

- `docs/PHASE_V_AUDIT.md` exists and accurately records the final boundary.
- Focused verification passes.
- `scripts/verify.sh` passes.
- The roadmap and conformance docs no longer describe Phase V as future work.
- Remaining broker tails are explicitly deferred.

Slice 7 execution record, 2026-06-01:

- Added `docs/PHASE_V_AUDIT.md` with the completed slice summary, supported
  `qty_percent` boundary, unsupported broker tails, fixture evidence, host
  evidence, documentation evidence, and verification record.
- Updated `docs/LONG_TERM_EXECUTION_PLAN.md` to mark Phase V closed after audit
  and release-gate verification, and updated semantic/conformance references to
  point at the final audit.
- Updated `docs/SEMANTIC_MODEL.md` to remove stale `qty_percent` unsupported
  wording and describe the current percent quantity semantics.
- Added a conservative Phase V closeout entry to `docs/RELEASE_NOTES.md`.
- Ran focused verification, snapshot refresh checks, Python wheel rebuild and
  reinstall, Python tests, and `scripts/verify.sh`; all passed.

## Suggested Commit Slices

Use one commit per slice when implementing this plan:

1. `Plan Phase V strategy exit qty percent`
2. `Guard strategy exit qty percent diagnostics`
3. `Add strategy exit percent quantity internals`
4. `Support strategy exit qty percent`
5. `Cover strategy exit qty percent runtime fixtures`
6. `Cover strategy exit qty percent host parity`
7. `Sync strategy exit qty percent conformance docs`
8. `Close Phase V strategy exit qty percent`

Do not stage unrelated local files. In particular, preserve any independent
review or audit documents that are not part of the current slice unless the
slice explicitly updates them.

## Stop Conditions

Stop and report instead of widening scope if any of these happen:

- Supporting `qty_percent` requires multiple pending exits or a reservation
  ledger.
- A percent quantity cannot be resolved deterministically from current broker
  state at placement time.
- Supporting percent exits requires public pending-order fields or a runtime
  schema bump.
- Host parity would require duplicating broker math in CLI, Python, or WASM.
- Existing fixed-`qty` fixtures or snapshots change unexpectedly.
- Incremental execution diverges from full historical execution.
- `scripts/verify.sh` fails for a reason that cannot be fixed within the
  current slice without broadening the slice.

## Expected Post-Phase Backlog

After Phase V, keep future strategy work narrow and fixture-backed. The next
strategy tails should still be treated as separate phases:

- Quantity reservation across multiple exits.
- Multiple independent pending exits.
- Missing-entry pre-placement.
- Multiple entries, pyramiding, short exposure, and reversals.
- Richer order APIs, OCA behavior, comments, alert messages, and strategy
  alerts.
- Commission, slippage, margin, currency conversion, and richer sizing modes.
- Public pending-order records or a schema-reviewed richer strategy output
  model.
