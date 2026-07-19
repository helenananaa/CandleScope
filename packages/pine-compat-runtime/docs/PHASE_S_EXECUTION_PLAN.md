# Phase S Strategy Exit Trailing Stop Execution Plan

Status: closed for the current fixture-backed trailing-stop subset. See
`docs/PHASE_S_AUDIT.md` for the closeout evidence.

Phase S should not become a broader broker-simulation phase. It should widen
only the current `strategy.exit` surface by adding one deterministic,
fixture-backed trailing-stop subset for the existing long-only,
no-pyramiding, one-pending-exit broker. Every slice should leave the workspace
shippable and should keep semantic claims, broker behavior, public output
contracts, fixtures, snapshots, host bindings, conformance metadata, and docs
in lockstep.

## Current Starting Point

The repository has closed Phase G, Phase L, Phase M, Phase N, Phase O, Phase P,
Phase Q, and Phase R for the current strategy subset:

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
  at the current bar close, with no pyramiding and no short exposure.
- `strategy.close(id)` closes the full matching long position at the current
  bar close and cancels any matching pending exit.
- Strategy state variables are available in strategy-mode historical scripts:
  `strategy.position_size`, `strategy.position_avg_price`,
  `strategy.openprofit`, `strategy.netprofit`, `strategy.equity`,
  `strategy.closedtrades`, and `strategy.opentrades`.
- Single-trigger `strategy.exit` supports stop, limit, profit, and loss forms
  for one broker-owned pending full-position exit on the current one-net-long
  entry.
- Bracket `strategy.exit` supports exactly one downside plus one upside leg:
  `stop + limit`, `stop + profit`, `loss + limit`, and `loss + profit`.
- Same-side bracket pairs `stop + loss` and `limit + profit`, 3+ trigger
  calls, trailing stops, partial quantities, missing-entry pre-placement,
  multiple pending exits, pyramiding, short exposure, and reversals remain
  unsupported.
- Runtime output remains `schemaVersion: 3`. `StrategyResult`,
  `StrategyOrderEvent`, `StrategyTrade`, `StrategyPositionSnapshot`, and
  `StrategyEquitySnapshot` shapes are unchanged.
- The broker stores a single `pending_exit: Option<PendingExit>` in
  `crates/pine-runtime/src/strategy/broker/exits.rs`.
- `PendingExitTrigger` is currently `Stop(f64)`, `Limit(f64)`, or
  `Bracket { downside: f64, upside: f64 }`.
- `place_exit` validates finite prices, requires a matching current long
  entry, deduplicates identical repeated calls, and otherwise replaces pending
  state with `last_update_bar_index = bar_index`.
- `evaluate_pending_exits` skips the creation or replacement bar via
  `last_update_bar_index >= bar_index`, cancels pending exits when the
  position is flat or `from_entry` no longer matches, and fills stop/limit or
  bracket exits on later historical bars.
- Profit/loss tick legs convert once at placement time from `self.avg_price`
  using the fixed default `syminfo.mintick`.
- `crates/pine-sema/src/analyzer/strategy.rs::validate_strategy_exit_args`
  currently rejects `trail_price`, `trail_points`, and `trail_offset` as
  unsupported `strategy.exit` arguments.
- Runtime `eval_strategy_exit` in `crates/pine-runtime/src/builtins/strategy.rs`
  does not extract or dispatch trailing-stop arguments.

The current broker module layout is:

```text
crates/pine-runtime/src/strategy/
   mod.rs
   broker/
      mod.rs                 pending evaluation + result projection
      exits.rs               pending-exit identity + placement helpers
      fills.rs               fill trade construction + position reset
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

## Phase S Goal

Design and implement the first deterministic trailing-stop subset for
`strategy.exit` without changing the public strategy output schema.

The target positive subset, if confirmed by the Slice 0 design gate, is:

- `strategy.exit(id, from_entry, trail_price=price, trail_offset=ticks)`.
- `strategy.exit(id, from_entry, trail_points=ticks, trail_offset=ticks)`.
- Exactly one activation family is accepted per trailing exit:
  `trail_price` or `trail_points`, but not both.
- `trail_offset` is required for every supported trailing exit.
- `trail_price` is a finite activation price.
- `trail_points` is a finite positive tick distance converted once at
  placement time from `strategy.position_avg_price` using the fixed default
  `syminfo.mintick`.
- `trail_offset` is a finite positive tick distance converted once at
  placement time to a price distance using the same fixed default
  `syminfo.mintick`.
- A trailing exit is one broker-owned pending full-position exit from the
  current matching long entry.
- A trailing exit starts inactive. Once activated, its stop price ratchets
  upward for long positions and never loosens.
- Filling the active trailing stop emits exactly one `strategy.exit` order
  event, records one closed trade under the source entry id, clears the
  position, updates normal position/equity snapshots, and cancels the pending
  exit.
- Public runtime JSON, Python dictionaries, and WASM JSON keep the existing
  strategy result shape and runtime `schemaVersion: 3`.

Phase S is successful when the selected trailing forms analyze, execute,
round-trip through CLI/Python/WASM, are fixture- and snapshot-covered including
incremental parity, are marked appropriately in `tests/fixtures/conformance.tsv`,
are documented, and pass the full release verification gate, while every
still-unsupported trailing combination remains diagnostic-only unsupported.

## Non-Goals

Do not include these in the Phase S compatibility claim:

- Combining trailing arguments with `stop`, `limit`, `profit`, or `loss`.
- Combining trailing arguments with an existing bracket form.
- Accepting both `trail_price` and `trail_points` in the same call unless Slice
  0 explicitly selects and documents a precedence rule.
- `strategy.exit` partial quantities, `qty`, `qty_percent`, reservation
  behavior, or partial fills.
- Missing-entry pre-placement of pending exits.
- Multiple simultaneous entries, pyramiding, short exposure, and reversals.
- Multiple independent pending exits or a public pending-order collection.
- Public trailing-stop metadata, activation-state fields, exit-reason fields,
  pending-order fields, or any runtime schema bump.
- `oca_name`, `comment`, `alert_message`, `strategy.order`, and richer order
  modification APIs.
- Commission, slippage, margin, currency conversion, percent-of-equity sizing,
  cash sizing, contracts sizing, and custom tick-size host metadata.
- Strategy alerts and alert placeholder delivery.
- Realtime strategy execution, forming-bar broker rollback for trailing stops,
  and intrabar path reconstruction.
- Matching TradingView broker-emulator intrabar assumptions beyond the explicit
  OHLC-only deterministic policy selected in this document.

## Phase S Default Design Decisions

Slice 0 must confirm these decisions before behavior changes land. If any
decision changes, update this section first and keep fixtures, docs, matrix
metadata, and implementation aligned with the revised rule.

- Phase S supports long-only trailing stops only.
- A trailing exit is represented in the existing single pending-exit slot.
- `trail_price + trail_offset` and `trail_points + trail_offset` are the first
  supported forms.
- `trail_price`, when selected, is the activation price.
- `trail_points`, when selected, converts to an activation price at placement
  time: `strategy.position_avg_price + trail_points * syminfo.mintick`.
- `trail_offset` converts to a fixed price distance at placement time:
  `trail_offset * syminfo.mintick`.
- Tick conversions use the same fixed default `syminfo.mintick` subset already
  used by profit/loss exits.
- New or replaced trailing exits are not eligible on the creation or
  replacement bar.
- An inactive trailing exit activates on a later eligible bar when
  `high >= activation_price`.
- Activation sets the first trailing stop price to
  `high - offset_price_distance` for the activation bar.
- The activation bar does not fill the newly activated trailing stop. This
  avoids claiming an intrabar path between the bar's high and low.
- On later bars after activation, the broker first checks the previously active
  stop price. If `low <= active_stop_price`, the exit fills at
  `active_stop_price`.
- If an active trailing stop does not fill on the current bar, the broker then
  ratchets the stop for future bars to
  `max(active_stop_price, high - offset_price_distance)`.
- The trailing stop never moves downward for a long position.
- Repeating an identical trailing call preserves the original eligibility bar
  and any current active trailing state.
- Changing the exit id, `from_entry`, activation price, offset distance, or
  activation family replaces the pending exit, resets it to inactive, and makes
  it ineligible on the replacement bar.
- Replacing a single-trigger or bracket pending exit with a trailing exit, or
  replacing a trailing exit with a single-trigger or bracket exit, follows the
  same replacement rule.
- Invalid activation or offset values leave any existing pending exit unchanged
  and emit a stable runtime diagnostic.
- Filled trailing exits update `strategy.closedtrades`, `strategy.opentrades`,
  `strategy.netprofit`, and `strategy.equity` with the same read-timing rules
  as existing pending `strategy.exit` fills: script reads see pending-exit fills
  on the next bar, while public output and equity snapshots include the fill on
  the fill bar.

## Rules for Every Slice

- Add fixtures before or alongside behavior changes.
- Keep the compatibility matrix conservative. Only widen the `strategy.exit`
  row when semantic fixtures, runtime fixtures, host coverage, conformance
  metadata, docs, and verification evidence all exist for the exact trailing
  subset.
- Preserve indicator behavior. Indicator scripts must not gain broker state or
  strategy output.
- Keep strategy order calls rejected in UDFs and requested-context expressions
  under the existing side-effect policy.
- Keep trailing arguments diagnostic-only until runtime dispatch in the same
  slice routes accepted forms into broker placement.
- Do not silently reinterpret an unsupported trailing combination as a stop,
  limit, profit, loss, or bracket exit.
- Treat the broker as deterministic runtime state. Core crates must not depend
  on account services, wall-clock time, host callbacks, filesystem, network,
  or host-specific tick metadata.
- Reuse the existing public strategy output contract. No public pending-order
  fields, item-shape changes, trailing-state fields, or schema bump.
- Keep CLI, Python, and WASM behavior synchronized. A supported trailing script
  that runs through one host must produce equivalent runtime JSON or native
  dictionary data through the others.
- Keep docs and conformance metadata in the same change as behavior.
- If any slice reveals a behavior bug in the existing single-trigger or bracket
  subset, stop, add a regression fixture or unit test, and fix it as a separate
  behavior slice before continuing trailing-stop work.
- Run the full release verification gate before closing Phase S.

## Internal Structure Rules

Phase S should extend the existing strategy subsystem without turning analyzer,
runtime, or output modules into catch-all broker files.

- Keep `pine-builtins` responsible for strategy declaration/order signatures
  and accepted constants only. It must not own trailing-stop semantics.
- Keep `crates/pine-sema/src/analyzer/strategy.rs` responsible for strategy
  mode gating, trailing argument-shape classification, accepted/rejected
  combinations, and stable diagnostics.
- Keep `crates/pine-runtime/src/strategy/broker/exits.rs` responsible for
  pending-exit identity, trailing placement, replacement, tick conversion, and
  runtime placement diagnostics.
- Keep `crates/pine-runtime/src/strategy/broker/mod.rs` responsible for pending
  evaluation, activation, ratcheting, fill triggering, and result projection.
- Keep `crates/pine-runtime/src/strategy/broker/fills.rs` responsible for fill
  trade construction and position reset.
- Keep `crates/pine-runtime/src/builtins/strategy.rs` responsible for
  extracting runtime arguments, evaluating accepted expressions, and
  dispatching to broker placement.
- Keep `crates/pine-runtime/src/output/strategy.rs` limited to public result
  structs. It must not become the source of truth for trailing-stop state.
- Keep Python and WASM bindings thin. They map the shared strategy result model
  and must not duplicate trailing math or fill rules.
- Treat roughly 800 lines in a production Rust file as a review trigger. Split
  before adding another trigger rule or accounting path.

## Intended Module Layout

Use existing crate boundaries. No new crate is needed for Phase S.

```text
crates/pine-builtins/src/
   namespaces/strategy.rs       strategy.exit signature accepts trailing names

crates/pine-sema/src/analyzer/
   strategy.rs                  trailing argument-shape diagnostics

crates/pine-runtime/src/
   strategy/
      mod.rs                    broker facade and re-exports
      broker/
         mod.rs                 pending evaluation + trailing activation/ratchet
         exits.rs               trailing pending state + placement helpers
         fills.rs               fill trade construction (unchanged contract)
         accounting.rs          equity/position accessors (unchanged contract)
         tests.rs               broker unit tests including trailing cases
   builtins/
      strategy.rs               eval_strategy_exit extracts and dispatches trailing legs
   output/
      strategy.rs               public structs unchanged

crates/pine-cli/src/            no broker logic; shared runtime behavior
crates/pine-python/src/lib.rs   maps shared runtime result only
crates/pine-wasm/src/lib.rs     returns shared strategy JSON only
```

Ownership notes:

- The pending-exit slot stays a single `Option<PendingExit>`.
- Do not make active trailing state part of public output.
- Do not compare mutable active trailing state when deduplicating repeated
  trailing calls. Deduplication should compare the placement specification
  (`id`, `from_entry`, activation family, activation price, and offset
  distance) while preserving the current active stop state.
- Tick legs continue to convert once at placement time from the fixed default
  `syminfo.mintick`.
- Trailing activation and offset prices remain fixed after placement except for
  the active trailing stop's ratchet.

## Slice 0: Design Gate And Baseline Lock

Goal: lock the trailing-stop design before accepting any new executable form.

Tasks:

1. Review `docs/PHASE_R_AUDIT.md`, `docs/PHASE_Q_AUDIT.md`,
   `docs/PHASE_M_AUDIT.md`, and `tests/fixtures/conformance.tsv`.
2. Confirm the Phase S default design decisions in this document.
3. If any decision changes, update this document before touching analyzer or
   runtime behavior.
4. Verify the current trailing forms remain unsupported by existing or new
   diagnostic fixtures.
5. Confirm no public runtime schema change is required.
6. Confirm no new strategy output fields are required.
7. Confirm WASM and Python host parity can use the existing strategy output
   model.

Suggested verification:

```text
cargo test -p pine-builtins strategy
cargo test -p pine-sema strategy
cargo test -p pine-runtime strategy
cargo test -p pine-cli strategy
cargo test -p pine-wasm strategy
python3 -m pytest python/tests
```

Exit criteria:

- This document records the selected activation, ratchet, replacement,
  invalid-value, and public-output decisions.
- No compatibility claim is widened.
- Existing strategy tests pass.

## Slice 1: Diagnostic-Only Trailing Guardrails

Goal: make every still-unsupported trailing form explicit and stable before
positive support lands.

Add or confirm semantic fixtures:

- `tests/fixtures/sema/unsupported_strategy_exit_trailing.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_profit_trailing.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_trail_price_only.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_trail_points_only.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_trail_offset_only.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_trail_price_points.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_trailing_bracket.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_trailing_partial_quantity.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_trailing_indicator.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_trailing_function_side_effect.pine`
- `tests/fixtures/sema/unsupported_request_strategy_trailing_exit.pine`

Tasks:

1. Add missing fixtures as diagnostic-only cases.
2. Keep the diagnostic stable and phase-neutral, for example:
   `` `strategy.exit` trailing stop arguments are not supported in the current strategy subset ``.
3. Add `trail_price`, `trail_points`, and `trail_offset` to
   `crates/pine-builtins/src/namespaces/strategy.rs` so named arguments do not
   fall through to the generic unknown-argument diagnostic. This signature
   widening is diagnostic plumbing only; the strategy analyzer must still reject
   every trailing form in this slice.
4. Keep the broad `strategy.*` unsupported row conservative.
5. Do not accept any trailing form in semantic analysis yet unless Slice 2 and
   Slice 4 behavior are landing in the same change.
6. Update `tests/fixtures/conformance.tsv` only to cite new unsupported
   fixtures, without widening status.

Suggested verification:

```text
cargo test -p pine-builtins strategy
cargo test -p pine-sema strategy
cargo test -p pine-cli matrix
```

Exit criteria:

- Unsupported trailing forms produce stable diagnostics instead of falling
  through to generic unknown-argument errors.
- Conformance metadata remains conservative.

## Slice 2: Semantic Classification And Acceptance Gate

Goal: prepare the analyzer to classify exactly the selected trailing forms
without creating a sema-only compatibility widening. If this slice lands by
itself, trailing forms must remain diagnostic-only unsupported. Positive
semantic acceptance may land only in the same change set as broker placement,
runtime dispatch, execution behavior, and runtime fixtures for the same forms.

Positive semantic fixtures, added only when acceptance lands together with
runtime behavior:

- `tests/fixtures/sema/supported_strategy_exit_trail_price.pine`
- `tests/fixtures/sema/supported_strategy_exit_trail_points.pine`

Tasks:

1. In `crates/pine-sema/src/analyzer/strategy.rs`, classify strategy-exit
   trigger families as:
   - downside fixed-price/tick families: `stop`, `loss`
   - upside fixed-price/tick families: `limit`, `profit`
   - trailing activation families: `trail_price`, `trail_points`
   - trailing offset family: `trail_offset`
2. Record the selected acceptance shape in code comments or helper names:
   `trail_price + trail_offset` and `trail_points + trail_offset` are the only
   future positive forms when no other trigger family is present.
3. If this slice is standalone, keep both selected forms rejected with the
   stable trailing-unsupported diagnostic.
4. When this acceptance gate is combined with runtime behavior, accept
   `trail_price + trail_offset` and `trail_points + trail_offset` and reject
   every other trailing combination.
5. Reject calls with `trail_offset` but no activation family.
6. Reject calls with `trail_price` or `trail_points` but no `trail_offset`.
7. Reject calls with both `trail_price` and `trail_points`, unless Slice 0
   explicitly selected a precedence rule.
8. Reject calls that combine trailing arguments with `stop`, `limit`,
   `profit`, `loss`, `qty`, `qty_percent`, or 3+ trigger families.
9. Preserve existing supported single-trigger and bracket forms unchanged.
10. Preserve indicator-mode, UDF side-effect, and requested-context rejection.
11. Keep argument name diagnostics stable for unsupported trailing variants.

Suggested verification:

```text
cargo test -p pine-sema strategy
cargo test -p pine-builtins strategy
```

If positive acceptance lands in the same change set, also run the verification
for the broker, runtime dispatch, and runtime fixture slices included in that
change.

Exit criteria:

- Standalone execution: no positive trailing fixture analyzes yet, every
  trailing fixture remains diagnostic-only, and existing exit behavior is
  unchanged.
- Combined behavior execution: exactly two positive semantic fixtures analyze,
  every unsupported trailing fixture remains diagnostic-only, and matching
  broker/runtime/fixture coverage exists in the same change set.
- No runtime support is claimed from semantic acceptance alone.

## Slice 3: Broker Trailing State Model

Goal: add internal pending-exit state for trailing stops without changing
public output.

Tasks:

1. Extend `PendingExitTrigger` or introduce an internal trigger/spec split that
   can represent a trailing exit.
2. Store immutable placement data:
   - activation family, if needed for deduplication diagnostics
   - activation price
   - offset price distance
3. Store mutable trailing state separately from the placement identity:
   - inactive state before activation
   - active state with current stop price after activation
4. Add broker placement helpers, for example:
   - `place_exit_trail_price(id, from_entry, activation_price, offset_ticks, mintick, bar_index)`
   - `place_exit_trail_points(id, from_entry, activation_ticks, offset_ticks, mintick, bar_index)`
5. Reuse existing tick validation diagnostics where the message is still exact;
   add specific diagnostics only when needed, for example:
   - `E_STRATEGY_EXIT_TRAIL_ACTIVATION`
   - `E_STRATEGY_EXIT_TRAIL_OFFSET`
6. Ensure invalid activation or offset values do not replace an existing
   pending exit.
7. Ensure missing or mismatched entries keep using the existing
   `E_STRATEGY_EXIT_ENTRY` behavior.
8. Implement a placement-equivalence comparison that ignores mutable active
   trailing state so repeated identical calls preserve the current active stop.
9. Add broker unit tests in `crates/pine-runtime/src/strategy/broker/tests.rs`
   before or alongside behavior evaluation.

Suggested broker unit tests:

- Trailing placement requires matching current long entry.
- Invalid activation price leaves existing pending state unchanged.
- Invalid offset ticks leave existing pending state unchanged.
- Repeated identical trailing placement preserves `last_update_bar_index`.
- Repeated identical trailing placement preserves active trailing state.
- Changed activation or offset replaces pending state and resets eligibility.
- `strategy.close` cancellation still cancels matching trailing exits.

Suggested verification:

```text
cargo test -p pine-runtime strategy::broker
cargo test -p pine-runtime strategy
```

Exit criteria:

- Broker can store trailing pending exits internally.
- No public strategy output shape changes.
- Existing stop/limit/profit/loss/bracket tests still pass.

## Slice 4: Runtime Dispatch For Trailing Arguments

Goal: route accepted trailing forms from `strategy.exit` calls into broker
placement and prevent silent fallback to existing trigger forms.

Tasks:

1. In `crates/pine-runtime/src/builtins/strategy.rs`, extract `trail_price`,
   `trail_points`, and `trail_offset` arguments by name.
2. Evaluate trailing arguments only after `id` and `from_entry` evaluate to
   strings, matching existing strategy-exit behavior.
3. Use deterministic runtime evaluation order:
   - `id`
   - `from_entry`
   - `trail_price` or `trail_points`
   - `trail_offset`
4. Convert `trail_points` and `trail_offset` using the fixed default
   `syminfo.mintick`.
5. Dispatch `trail_price + trail_offset` to the trailing price placement
   helper.
6. Dispatch `trail_points + trail_offset` to the trailing points placement
   helper.
7. Keep semantic-only unsupported combinations unreachable in normal lowered
   programs, but avoid runtime panics if malformed HIR appears.
8. Preserve existing dispatch for stop, limit, profit, loss, and bracket forms.

Suggested verification:

```text
cargo test -p pine-runtime strategy
cargo test -p pine-runtime --test incremental
```

Exit criteria:

- Runtime places trailing exits for the two accepted forms.
- Existing exit behavior remains unchanged.
- Invalid trailing values emit diagnostics rather than replacing pending state.

## Slice 5: Trailing Activation, Ratchet, And Fill Evaluation

Goal: execute trailing exits with the deterministic OHLC-only policy selected
in this document.

Tasks:

1. Update `evaluate_pending_exits` to handle trailing pending exits.
2. Preserve creation and replacement bar ineligibility.
3. For inactive trailing exits on eligible bars:
   - activate when `high >= activation_price`
   - set active stop to `high - offset_price_distance`
   - do not fill on the activation bar
4. For active trailing exits on later bars:
   - check `low <= active_stop_price` first
   - fill at `active_stop_price` when touched
   - if not filled, ratchet to
     `max(active_stop_price, high - offset_price_distance)` for future bars
5. Ensure the active stop never decreases.
6. Ensure fill construction uses the existing `strategy.exit` order event and
   closed-trade contract.
7. Ensure filled trailing exits clear pending state and position state exactly
   like existing pending exits.
8. Ensure position, equity, net profit, open-trade count, and closed-trade
   count timing matches existing pending-exit fills.
9. Add broker unit tests for activation, no same-bar activation fill, ratchet,
   no-loosen behavior, and fill.

Suggested verification:

```text
cargo test -p pine-runtime strategy::broker
cargo test -p pine-runtime strategy
cargo test -p pine-runtime --test incremental
```

Exit criteria:

- The broker deterministically activates, ratchets, and fills trailing stops.
- No public output schema changes.
- Existing bracket same-bar precedence remains unchanged.

## Slice 6: Runtime Fixtures And Snapshots

Goal: cover the trailing behavior through normal runtime fixtures and golden
snapshots.

Add runtime fixtures and snapshots:

- `tests/fixtures/runtime/strategy_exit_trail_price_fill.pine`
- `tests/fixtures/runtime/strategy_exit_trail_points_fill.pine`
- `tests/fixtures/runtime/strategy_exit_trailing_activation_bar.pine`
- `tests/fixtures/runtime/strategy_exit_trailing_ratchet.pine`
- `tests/fixtures/runtime/strategy_exit_trailing_repeated.pine`
- `tests/fixtures/runtime/strategy_exit_trailing_replacement.pine`
- `tests/fixtures/runtime/strategy_exit_trailing_invalid.pine`
- `tests/fixtures/runtime/strategy_exit_trailing_close_cancel.pine`
- `tests/fixtures/runtime/strategy_exit_trailing_interactions.pine`
- `tests/fixtures/runtime/strategy_exit_trailing_state.pine`
- matching `tests/snapshots/runtime_strategy_exit_trailing_*.json` snapshots

Fixture requirements:

1. `trail_price` activates from an explicit price and fills on a later bar.
2. `trail_points` activates from entry-relative ticks and fills on a later bar.
3. Activation bar does not fill even when low also crosses the new stop.
4. Active stop ratchets upward after favorable highs.
5. Active stop does not loosen after lower highs.
6. Repeated identical calls preserve eligibility and active state.
7. Replacement resets inactive state and creation-bar ineligibility.
8. Invalid activation or offset values leave existing pending exit unchanged.
9. `strategy.close` cancels a matching trailing pending exit.
10. Branch, switch, for, and while contexts are covered for supported calls.
11. Strategy state and history reads around trailing fills match existing
    pending-exit timing.
12. Incremental append execution matches full historical execution.

Snapshot refresh command when public runtime snapshots intentionally change:

```text
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli runtime_outputs_match_golden_snapshots
```

Suggested verification:

```text
cargo test -p pine-runtime strategy
cargo test -p pine-runtime --test incremental
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
```

Exit criteria:

- Runtime fixtures cover the full selected trailing subset.
- Golden snapshots show filled trailing stops through existing public strategy
  fields only.
- Full and incremental execution agree.

## Slice 7: Public Host Parity

Goal: prove CLI, Python, and WASM expose the same trailing-stop result contract
without binding-level broker logic.

Tasks:

1. Add or extend CLI snapshot coverage for all trailing runtime fixtures.
2. Add one targeted CLI host assertion for a representative trailing fixture.
3. Add one Python binding test that runs the same representative trailing
   fixture and asserts:
   - one `strategy.exit` order event
   - one closed trade
   - expected fill price
   - unchanged top-level runtime keys
4. Add one WASM test that runs the same representative trailing fixture and
   asserts the same JSON contract.
5. Keep Python and WASM bindings thin; do not duplicate trailing math.

Suggested verification:

```text
cargo test -p pine-cli strategy
cargo test -p pine-wasm strategy
maturin build --manifest-path crates/pine-python/Cargo.toml --out dist
python3 -m pip install --force-reinstall dist/*.whl
python3 -m pytest python/tests
```

Exit criteria:

- CLI, Python, and WASM agree on the representative trailing result.
- Runtime `schemaVersion` remains `3`.
- Python returns native dictionaries with no new strategy keys.

## Slice 8: Conformance, Docs, And Release Notes

Goal: synchronize compatibility metadata and maintainer-facing docs with the
implemented trailing subset.

Tasks:

1. Update `tests/fixtures/conformance.tsv`:
   - keep `strategy.exit` as `partial`
   - add the exact supported trailing forms to its notes
   - cite positive trailing semantic and runtime fixtures
   - cite unsupported trailing combination fixtures
   - keep broad `strategy.*` `unsupported`
2. Refresh `tests/snapshots/matrix.json` if matrix output changes:

   ```text
   UPDATE_SNAPSHOTS=1 cargo test -p pine-cli matrix_output_matches_golden_snapshot
   ```

3. Update `docs/CONFORMANCE.md` with the exact trailing subset and unsupported
   boundaries.
4. Update `docs/LANGUAGE_SCOPE.md` and `docs/EXECUTION_SEMANTICS.md` if they
   describe strategy-exit timing or unsupported strategy boundaries.
5. Update `docs/RELEASE_NOTES.md` under `Unreleased`.
6. Update `docs/LONG_TERM_EXECUTION_PLAN.md` to move trailing stops from the
   deferred broker tails into the closed Phase S summary once closeout happens.
7. Update `README.md` if the current baseline summary or design document list
   should mention Phase S.

Suggested verification:

```text
cargo test -p pine-cli matrix
cargo test -p pine-cli matrix_output_matches_golden_snapshot
git diff --check
```

Exit criteria:

- Matrix, docs, snapshots, and release notes describe the same trailing subset.
- Unsupported trailing variants remain explicit.

## Slice 9: Closeout Audit And Release Gate

Goal: close Phase S with durable evidence and a clear next maintenance target.

Tasks:

1. Create `docs/PHASE_S_AUDIT.md` with:
   - completed slices
   - supported trailing surface
   - unsupported trailing and broker tails
   - public output and host behavior
   - semantic fixture evidence
   - runtime fixture and snapshot evidence
   - host parity evidence
   - verification results
   - deferred broker tails
2. Confirm `docs/PHASE_S_EXECUTION_PLAN.md` status can be changed to closed
   only after the audit and release gate pass.
3. Run the full release gate:

   ```text
   git diff --check
   scripts/verify.sh
   ```

4. Record the exact closeout command output summary in `docs/PHASE_S_AUDIT.md`.
5. Decide the next narrow strategy maintenance target, such as partial exits,
   missing-entry pre-placement, multiple pending exits, or short/pyramiding
   design, without starting it in the Phase S closeout change.

Exit criteria:

- `docs/PHASE_S_AUDIT.md` exists and matches implementation reality.
- `scripts/verify.sh` passes.
- The repository has no trailing-stop compatibility claim that lacks fixture
  evidence.

## Suggested Commit Order

1. `Add Phase S trailing stop plan`
2. `Harden trailing stop diagnostics`
3. `Classify trailing stop forms without widening support`
4. `Add broker trailing pending state`
5. `Enable trailing dispatch and fill evaluation`
6. `Add trailing stop semantic and runtime fixtures`
7. `Cover trailing stop host parity`
8. `Document trailing stop conformance`
9. `Close Phase S trailing stop audit`

Each commit should be reviewable on its own. A commit must not leave the
repository claiming trailing-stop support from semantic analysis alone. If
implementation pressure grows large, split commits by crate boundary while
keeping every positive support claim paired with matching broker behavior,
runtime fixtures, snapshots, conformance metadata, and docs.

## Slice Verification Matrix

Use this as the default verification menu while working through Phase S.

```text
# Semantic and builtin checks
cargo test -p pine-builtins strategy
cargo test -p pine-sema strategy

# Runtime behavior and append parity
cargo test -p pine-runtime strategy
cargo test -p pine-runtime --test incremental
cargo test -p pine-runtime --test profile_fixtures

# Public host surfaces
cargo test -p pine-cli strategy
cargo test -p pine-wasm strategy
maturin build --manifest-path crates/pine-python/Cargo.toml --out dist
python3 -m pip install --force-reinstall dist/*.whl
python3 -m pytest python/tests

# Snapshot refreshes only after intentional public-output or matrix changes
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli runtime_outputs_match_golden_snapshots
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli matrix_output_matches_golden_snapshot

# Release closeout
git diff --check
scripts/verify.sh
```

## Deferred Broker Tails After Phase S

Carry these forward unchanged unless a later phase designs them explicitly:

- Partial exits, `qty`, `qty_percent`, and reservation behavior.
- Missing-entry pre-placement.
- Multiple entries, pyramiding, short exposure, and reversals.
- Multiple independent pending exits and public pending-order records.
- Commission, slippage, margin, currency conversion, and richer sizing.
- Strategy alerts and realtime broker rollback.
- Intrabar path reconstruction and richer OHLC path emulation.
- Public exit-reason, activation-state, or pending-order metadata.

If Phase S decides not to implement trailing stops after the design gate, move
trailing stops back into this deferred list, keep all positive fixtures absent,
and close the phase as a diagnostic/design audit only.
