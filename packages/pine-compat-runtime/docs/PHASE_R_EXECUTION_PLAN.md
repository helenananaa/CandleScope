# Phase R Strategy Exit Bracket Implementation Execution Plan

Status: closed. Closeout is recorded in `docs/PHASE_R_AUDIT.md`. This plan is
kept as the implementation playbook used to turn `docs/PHASE_Q_AUDIT.md` into
the first positive bracket subset on top of the `docs/PHASE_P_AUDIT.md`,
`docs/PHASE_N_AUDIT.md`, and `docs/PHASE_M_AUDIT.md` baselines.

Phase R turns the Phase Q bracket design gate into the first positive
`strategy.exit` bracket subset. It implements exactly one downside leg plus one
upside leg for the current long-only, no-pyramiding, one-pending-exit broker,
using the decisions already locked in `docs/PHASE_Q_AUDIT.md`. Phase R should
not re-litigate bracket identity, same-bar precedence, or public output shape;
those are settled. Phase R should only implement, fixture-cover, and document
that settled design in small, reviewable, shippable slices.

Each slice should leave the workspace shippable and should keep semantic
claims, broker behavior, public output contracts, fixtures, snapshots, host
bindings, conformance metadata, and docs in lockstep.

## Current Starting Point

The repository has closed Phase G, Phase L, Phase M, Phase N, Phase O, Phase P,
and Phase Q for the current strategy subset:

- `tests/fixtures/conformance.tsv` marks `strategy`, `strategy.entry`,
  `strategy.close`, strategy equity, strategy state variables,
  `strategy.closedtrades`, `strategy.opentrades`, and `strategy.exit` as
  `partial`.
- Broad `strategy.*` remains `unsupported`.
- `strategy.exit(id, from_entry, stop=price)`,
  `strategy.exit(id, from_entry, limit=price)`,
  `strategy.exit(id, from_entry, profit=ticks)`, and
  `strategy.exit(id, from_entry, loss=ticks)` are supported for one
  broker-owned pending full-position exit on the current one-net-long entry.
- Combined trigger families are rejected by
  `crates/pine-sema/src/analyzer/strategy.rs::validate_strategy_exit_args`,
  which pushes the diagnostic `` `strategy.exit` combined trigger families are
  not supported in the current strategy subset `` whenever
  `trigger_count > 1`.
- Runtime `eval_strategy_exit` in
  `crates/pine-runtime/src/builtins/strategy.rs` evaluates triggers through an
  else-if chain in the order `stop`, `limit`, `profit`, `loss`, and routes to
  one of `place_exit_stop`, `place_exit_limit`, `place_exit_profit_ticks`, or
  `place_exit_loss_ticks`.
- The broker stores a single `pending_exit: Option<PendingExit>` in
  `crates/pine-runtime/src/strategy/broker/exits.rs`, where
  `PendingExitTrigger` is `Stop(f64) | Limit(f64)`.
- `place_exit` validates a finite price and a matching current long entry,
  dedups identical repeated calls, and otherwise replaces pending state with
  `last_update_bar_index = bar_index`.
- `evaluate_pending_exits` in
  `crates/pine-runtime/src/strategy/broker/mod.rs` skips the creation/
  replacement bar via `last_update_bar_index >= bar_index`, cancels pending
  exits when the position is flat or `from_entry` no longer matches, then fills
  on `low <= price` for `Stop` or `high >= price` for `Limit`.
- Profit/loss tick legs convert once at placement time from
  `self.avg_price` using `exit_tick_price_offset(ticks, mintick)` and the fixed
  default `syminfo.mintick` (`pine_builtins::named_float_constant`,
  default `0.01`).
- Runtime output remains `schemaVersion: 3`. `StrategyResult`,
  `StrategyOrderEvent`, `StrategyTrade`, `StrategyPositionSnapshot`, and
  `StrategyEquitySnapshot` shapes are unchanged.
- The broker module layout is:

  ```text
  crates/pine-runtime/src/strategy/
     mod.rs
     broker/
        mod.rs
        exits.rs
        fills.rs
        accounting.rs
        tests.rs
  ```

Existing combined-trigger semantic fixtures (must keep their meaning, some
changing from unsupported to supported per the decision record below):

- `tests/fixtures/sema/unsupported_strategy_exit_stop_limit.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_profit_loss.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_stop_profit.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_limit_loss.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_stop_loss.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_limit_profit.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_three_triggers.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_four_triggers.pine`

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

## Phase R Goal

Implement the first positive `strategy.exit` bracket subset exactly as designed
in `docs/PHASE_Q_AUDIT.md`:

- Accept exactly two trigger legs: one downside leg and one upside leg for the
  current long-only broker.
  - Downside legs: `stop=price`, `loss=ticks`.
  - Upside legs: `limit=price`, `profit=ticks`.
- Therefore newly supported bracket forms are exactly:
  - `stop + limit`
  - `stop + profit`
  - `loss + limit`
  - `loss + profit`
- Keep same-side pairs unsupported: `stop + loss` and `limit + profit`.
- Keep three-trigger and four-trigger calls unsupported.
- Keep single-trigger `stop`/`limit`/`profit`/`loss` exits working unchanged.
- A bracket is one pending exit. Filling either leg closes the full position
  and cancels the other leg.
- Same-bar both-hit uses deterministic stop/loss-first precedence: when a later
  eligible bar's OHLC range touches both legs, fill the downside leg.
- A bracket fill emits exactly one `strategy.exit` order event using the exit
  id, keyed to the source entry, with no new public pending-order or bracket-leg
  fields and no runtime schema bump.

Phase R is successful when the four bracket forms above analyze, execute, fill
deterministically, round-trip through CLI/Python/WASM, are fixture- and
snapshot-covered including incremental parity, are marked appropriately in
`tests/fixtures/conformance.tsv`, are documented, and pass the full release
verification gate, while same-side and 3+ trigger forms remain diagnostic-only
unsupported.

## Non-Goals

Do not include these in the Phase R compatibility claim:

- same-side pairs `stop + loss` and `limit + profit`.
- three-trigger and four-trigger calls.
- trailing stop behavior (`trail_price`, `trail_points`, `trail_offset`).
- partial exits, `qty`, `qty_percent`, and reservation behavior.
- missing-entry pre-placement of pending exits.
- multiple simultaneous entries, pyramiding, short exposure, and reversals.
- multiple independent pending exits or a public pending-order collection.
- bracket-leg metadata, exit-reason fields, or any public schema bump.
- `oca_name`, `comment`, `alert_message`, `strategy.order`, and richer order
  modification APIs.
- commission, slippage, margin, currency conversion, and percent-of-equity
  sizing.
- strategy alerts and alert placeholder delivery.
- realtime strategy execution and forming-bar broker rollback for brackets.
- intrabar path reconstruction beyond the deterministic stop/loss-first OHLC
  rule.

## Rules for Every Slice

- Add fixtures before or alongside behavior changes.
- Keep the compatibility matrix conservative. Only widen the `strategy.exit`
  row when the exact bracket form has semantic fixtures, runtime fixtures,
  host coverage, conformance metadata, docs, and verification evidence.
- Preserve indicator behavior. Indicator scripts must not gain broker state or
  strategy output.
- Keep strategy order calls rejected in UDFs and requested-context expressions
  under the existing side-effect policy.
- Treat the broker as deterministic runtime state. Core crates must not depend
  on account services, wall-clock time, host callbacks, filesystem, or network.
- Keep every still-unsupported trigger combination diagnostic-only with a
  stable diagnostic.
- Do not land analyzer acceptance for any bracket form unless runtime dispatch
  in the same slice routes that form to bracket placement and cannot silently
  fall back to a single-trigger exit.
- Reuse the existing public strategy output contract. No public pending-order
  fields, no item-shape changes, no schema bump.
- Keep CLI, Python, and WASM behavior synchronized. A bracket script that runs
  through one host must produce equivalent runtime JSON or native dictionary
  data through the others.
- Keep docs and conformance metadata in the same change as behavior.
- If any slice reveals a behavior bug in the existing single-trigger subset,
  stop, add a regression fixture or unit test, and fix it as a separate
  behavior slice before continuing the bracket work.
- Run the full release verification gate before closing Phase R.

## Internal Structure Rules

Phase R should grow the strategy subsystem without turning analyzer, runtime,
or output modules into catch-all broker files.

- Keep `pine-builtins` responsible for strategy declaration/order signatures
  and accepted constants only. It must not own bracket semantics.
- Keep `crates/pine-sema/src/analyzer/strategy.rs` responsible for strategy
  mode gating, trigger-family classification, accepted/rejected bracket
  combinations, and strategy-exit diagnostics.
- Keep `crates/pine-runtime/src/strategy/broker/exits.rs` responsible for
  pending-exit identity, bracket placement, replacement, eligibility, and tick
  conversion.
- Keep `crates/pine-runtime/src/strategy/broker/mod.rs` responsible for pending
  evaluation, same-bar both-hit precedence, and result projection.
- Keep `crates/pine-runtime/src/strategy/broker/fills.rs` responsible for fill
  trade construction and position reset.
- Keep `crates/pine-runtime/src/builtins/strategy.rs` responsible for
  extracting runtime arguments and dispatching to broker placement.
- Keep `crates/pine-runtime/src/output/strategy.rs` limited to public result
  structs. It must not become the source of truth for bracket transitions.
- Keep Python and WASM bindings thin. They map the shared strategy result model
  and must not duplicate bracket math or fill rules.
- Treat roughly 800 lines in a production Rust file as a review trigger. Split
  before adding another trigger rule or accounting path.

## Intended Module Layout

Use existing crate boundaries. No new crate is needed for Phase R.

```text
crates/pine-builtins/src/
   namespaces/strategy.rs       strategy.exit signature accepts the same named args

crates/pine-sema/src/analyzer/
   strategy.rs                  bracket family classification + diagnostics

crates/pine-runtime/src/
   strategy/
      mod.rs                    broker facade and re-exports
      broker/
         mod.rs                 pending evaluation + same-bar precedence + projection
         exits.rs               PendingExitTrigger enum extension + bracket placement
         fills.rs               fill trade construction (unchanged contract)
         accounting.rs          equity/position accessors (unchanged contract)
         tests.rs               broker unit tests including bracket cases
   builtins/
      strategy.rs               eval_strategy_exit extracts and dispatches bracket legs
   output/
      strategy.rs               public structs unchanged

crates/pine-cli/src/            no broker logic; shared runtime behavior
crates/pine-python/src/lib.rs   maps shared runtime result only
crates/pine-wasm/src/lib.rs     returns shared strategy JSON only
```

Ownership notes:

- The pending-exit slot stays a single `Option<PendingExit>`. Add a bracket by
  extending the trigger representation, not by adding a second pending slot or a
  pending-order collection.
- Tick legs continue to convert once at placement time from `self.avg_price`
  using the existing `exit_tick_price_offset` and fixed-default
  `syminfo.mintick`.
- Bracket prices remain fixed after placement.

## Phase R Decision Record

These decisions are inherited from `docs/PHASE_Q_AUDIT.md` and are binding for
Phase R. They may only be amended with matching fixtures, docs, matrix
metadata, and verification evidence.

- Supported bracket forms: `stop + limit`, `stop + profit`, `loss + limit`,
  `loss + profit`. Exactly one downside leg and one upside leg.
- Rejected forms: `stop + loss`, `limit + profit`, any three- or four-trigger
  call, and all existing unsupported strategy-exit families (trailing, partial
  quantity, missing entry, requested context, UDF side effect).
- Single-trigger `stop`/`limit`/`profit`/`loss` exits keep their current
  behavior.
- Tick conversion: `profit`/`loss` legs convert once at placement from the
  current `strategy.position_avg_price` using the fixed-default
  `syminfo.mintick`. Upside `profit` becomes a limit price; downside `loss`
  becomes a stop price. Bracket prices are fixed after placement.
- Leg evaluation order: evaluate `id` and `from_entry` first, then the downside
  leg, then the upside leg. Within a side, direct price legs (`stop`, `limit`)
  are handled before tick legs (`loss`, `profit`) when a diagnostic needs a
  stable ordering.
- Invalid-leg behavior: if either leg is invalid (non-finite/non-positive price
  or ticks, invalid mintick, flat state, mismatched `from_entry`), reject the
  whole bracket placement, push the existing stable runtime diagnostic, and
  leave any existing pending exit unchanged. A valid remaining leg must not
  silently degrade into a single-trigger exit.
- Identity and replacement: a bracket is one pending exit carrying `id`,
  `from_entry`, and both legs. An identical repeated bracket preserves the
  original eligibility bar. Changing either leg kind or price resets
  `last_update_bar_index`, making the bracket ineligible on the replacement bar.
  Replacing a single-trigger exit with a bracket, or a bracket with a
  single-trigger exit, creates new pending state and resets eligibility.
  `from_entry` must still match the current long entry.
- Eligibility: a new or replaced bracket is ineligible on its creation/
  replacement bar via the existing `last_update_bar_index >= bar_index` guard.
- Fill rule: on a later eligible bar, the downside leg fills when
  `low <= downside_price` and the upside leg fills when `high >= upside_price`.
- Same-bar both-hit: when both legs would fill on the same eligible bar, fill
  the downside (stop/loss) leg. No diagnostic is emitted merely because both
  legs were touched.
- Public output: a bracket fill emits exactly one `strategy.exit` order event
  using the exit id, keyed to the source entry, visible only through existing
  filled-price and trade-profit fields. No public pending-order record,
  bracket-leg metadata, or exit-reason field is added. Runtime output remains
  `schemaVersion: 3`.
- State-variable timing: brackets are ineligible on creation/replacement bars;
  pending brackets evaluate after script statements each historical bar; script
  reads on a triggering bar see pre-fill state; public strategy output and
  equity for the triggering bar include the fill; next-bar reads see updated
  `strategy.position_size`, `strategy.position_avg_price`,
  `strategy.openprofit`, `strategy.netprofit`, `strategy.equity`,
  `strategy.closedtrades`, and `strategy.opentrades`.

## Slice 0: Baseline Lock and Design Confirmation

Goal: lock the Phase Q decision record and confirm the exact Phase R supported
and rejected forms before any positive support is claimed.

Steps:

1. Read `docs/PHASE_Q_AUDIT.md`, this document, and
   `tests/fixtures/conformance.tsv` before editing code.
2. Confirm the decision record above, especially the four supported bracket
   forms, the two rejected same-side pairs, the stop/loss-first same-bar rule,
   identity/replacement, invalid-leg rejection, and the unchanged public
   output contract.
3. Inventory the existing combined-trigger semantic fixtures and classify each
   as future-supported or permanently-rejected for Phase R:
   - to become supported: `unsupported_strategy_exit_stop_limit.pine`,
     `unsupported_strategy_exit_stop_profit.pine`,
     `unsupported_strategy_exit_limit_loss.pine` (migrated to
     `supported_strategy_exit_loss_limit.pine` for downside-first naming), and
     `unsupported_strategy_exit_profit_loss.pine` (migrated to
     `supported_strategy_exit_loss_profit.pine` for downside-first naming).
   - to stay rejected: `unsupported_strategy_exit_stop_loss.pine`,
     `unsupported_strategy_exit_limit_profit.pine`,
     `unsupported_strategy_exit_three_triggers.pine`,
     `unsupported_strategy_exit_four_triggers.pine`.
4. Do not change `tests/fixtures/conformance.tsv` in Slice 0.
5. Run the focused semantic baseline:

   ```text
   cargo test -p pine-sema strategy
   cargo test -p pine-builtins strategy
   ```

Acceptance criteria:

- The four supported bracket forms and all rejected forms are written down
  before runtime behavior changes.
- The fixture migration plan (which negative fixtures become positive) is
  recorded.
- Existing single-trigger support remains unchanged.

## Slice 1: Broker Bracket Representation and Placement

Goal: extend broker pending-exit state to carry a bracket while preserving the
single pending slot, without yet widening semantic acceptance or runtime
dispatch. Combined-trigger Pine scripts must still be rejected by the analyzer
at the end of this slice.

Steps:

1. In `crates/pine-runtime/src/strategy/broker/exits.rs`, extend the pending
   trigger model. Prefer extending `PendingExitTrigger` so a `PendingExit` can
   carry either a single trigger or a bracket, for example:

   ```text
   enum PendingExitTrigger {
       Stop(f64),
       Limit(f64),
       Bracket { downside: f64, upside: f64 },
   }
   ```

   Keep the existing single variants so single-trigger behavior is untouched.
2. Add a broker placement method that takes both already-resolved leg prices,
   for example
   `place_exit_bracket(id, from_entry, downside_price, upside_price, bar_index)`.
3. Validate the whole bracket before mutating pending state:
   - both leg prices must be finite (reuse the `E_STRATEGY_EXIT_PRICE` path).
   - the position must be long and `from_entry` must match (reuse the
     `E_STRATEGY_EXIT_ENTRY` path).
   - if validation fails, push the existing stable diagnostic and leave any
     existing pending exit unchanged.
4. Extract or expose focused broker helpers for tick-to-price conversion so
   bracket dispatch can reuse the same `E_STRATEGY_EXIT_TICKS` and
   `E_STRATEGY_EXIT_MINTICK` diagnostics without placing a single-trigger
   pending exit as a side effect. Do not call `place_exit_profit_ticks` or
   `place_exit_loss_ticks` as the bracket conversion mechanism.
5. Preserve identity/replacement semantics in `place_exit`:
   - an identical repeated bracket (same id, from_entry, both leg prices)
     preserves the original `last_update_bar_index`.
   - any change to either leg replaces pending state with the current
     `bar_index`.
6. Add broker unit tests in
   `crates/pine-runtime/src/strategy/broker/tests.rs` for:
   - bracket placement from explicit prices.
   - tick-derived bracket placement from average entry price through the shared
     conversion helpers.
   - invalid downside price, invalid upside price, invalid ticks, invalid
     mintick, flat state, and mismatched entry leaving pending state unchanged.
   - identical repeated bracket preserving eligibility.
   - changed leg resetting eligibility.
   - single-trigger replaced by bracket and bracket replaced by single-trigger,
     both resetting eligibility.
7. Keep the existing combined-trigger sema fixtures negative in this slice. Do
   not update `tests/fixtures/conformance.tsv`, matrix snapshots, public output
   schemas, CLI, Python, or WASM.
8. If `exits.rs` approaches the review threshold, split bracket conversion into
   a focused helper before adding more behavior.
9. Run:

   ```text
   cargo test -p pine-runtime strategy
   cargo test -p pine-sema strategy
   ```

Acceptance criteria:

- Broker tests prove bracket placement and replacement without touching public
  output shapes.
- Existing stop/limit/profit/loss broker tests continue to pass.
- Invalid runtime values are deterministic diagnostics, not panics.
- Analyzer behavior is unchanged: every combined-trigger fixture remains
  unsupported.

## Slice 2: Internal Bracket Fill Evaluation

Goal: evaluate pending brackets with deterministic stop/loss-first precedence,
still without widening semantic acceptance or runtime dispatch.

Steps:

1. In `crates/pine-runtime/src/strategy/broker/mod.rs`, extend
   `evaluate_pending_exits` to handle the `Bracket` variant:
   - keep the creation/replacement bar guard
     (`last_update_bar_index >= bar_index`).
   - keep the flat/mismatched-entry cancellation path.
   - compute `downside_hit = low <= downside_price` and
     `upside_hit = high >= upside_price`.
   - if `downside_hit`, fill at the downside price (stop/loss-first precedence),
     regardless of `upside_hit`.
   - else if `upside_hit`, fill at the upside price.
2. Adjust `fill_pending_exit` or add a focused fill helper so the evaluation
   path passes the resolved fill price explicitly. A bracket fill must not rely
   on `PendingExitTrigger::price()` unless that method is also given an
   unambiguous selected leg.
3. Reuse the existing fill construction so a bracket fill produces exactly one
   `strategy.exit` order event and one closed trade keyed to the source entry.
4. Do not emit any diagnostic merely because both legs were touched.
5. Add broker unit tests for:
   - downside-only hit fills at the downside price.
   - upside-only hit fills at the upside price.
   - both-hit fills at the downside price (stop/loss-first).
   - no-hit leaves the bracket pending for a later bar.
   - existing single-trigger stop/limit fill behavior remains unchanged.
6. Keep the analyzer's combined-trigger rejection unchanged in this slice.
7. Run:

   ```text
   cargo test -p pine-runtime strategy
   cargo test -p pine-sema strategy
   ```

Acceptance criteria:

- Bracket fills are deterministic and use the documented precedence.
- A bracket fill closes the full position and cancels the unused leg.
- Existing single-trigger fills are unchanged.
- Analyzer behavior is unchanged: every combined-trigger fixture remains
  unsupported.

## Slice 3: Atomic Semantic Acceptance and Runtime Dispatch

Goal: teach the analyzer and runtime about the bracket subset in the same
shippable slice, so any bracket form that analyzes successfully also executes
through bracket placement instead of silently degrading to a single-trigger
exit.

Steps:

1. In `crates/pine-sema/src/analyzer/strategy.rs`, replace the simple
   `trigger_count > 1` rejection with leg classification:
   - downside legs: `stop`, `loss`.
   - upside legs: `limit`, `profit`.
2. Accept exactly one downside leg plus one upside leg. Continue to accept
   exactly one trigger overall (the existing single-trigger subset).
3. Reject these with stable diagnostics:
   - two downside legs (`stop + loss`): keep the combined-trigger diagnostic or
     a clearer same-side message.
   - two upside legs (`limit + profit`): same.
   - any total trigger count greater than two.
   - zero triggers when `args.len() >= 2` (preserve the existing
     `E_CALL_ARITY` message).
4. Keep unsupported options (`qty`, `qty_percent`, `trail_*`, `oca_name`,
   `comment`, `alert_message`) rejected exactly as today.
5. Keep `strategy.exit` strategy-mode-only and rejected in UDF and
   requested-context side-effect paths.
6. In `crates/pine-runtime/src/builtins/strategy.rs`, update
   `eval_strategy_exit` so it detects when both a downside and an upside leg are
   present and dispatches to bracket placement instead of the single-trigger
   else-if chain.
7. Preserve the single-trigger else-if behavior when only one leg is present.
8. Evaluate `id` and `from_entry` once, then evaluate the present legs in the
   canonical order: downside leg first (`stop` before `loss`), then upside leg
   (`limit` before `profit`).
9. Convert tick legs to prices using the same fixed-default mintick path
   (`pine_builtins::named_float_constant("syminfo.mintick")`), then pass
   resolved prices to `place_exit_bracket`. Reuse the conversion helper from
   Slice 1; do not duplicate the math and do not call a method that places a
   single-trigger pending exit as a side effect.
10. Use the existing `as_f64().unwrap_or(f64::NAN)` convention and let broker
    validation reject invalid values.
11. Migrate fixtures:
    - rename or replace the four to-be-supported negative fixtures with
      positive fixtures:
      - `tests/fixtures/sema/supported_strategy_exit_stop_limit.pine`
      - `tests/fixtures/sema/supported_strategy_exit_stop_profit.pine`
      - `tests/fixtures/sema/supported_strategy_exit_loss_limit.pine`
      - `tests/fixtures/sema/supported_strategy_exit_loss_profit.pine`
    - keep these negative fixtures rejected:
      - `tests/fixtures/sema/unsupported_strategy_exit_stop_loss.pine`
      - `tests/fixtures/sema/unsupported_strategy_exit_limit_profit.pine`
      - `tests/fixtures/sema/unsupported_strategy_exit_three_triggers.pine`
      - `tests/fixtures/sema/unsupported_strategy_exit_four_triggers.pine`
12. Update the sema fixture test list (`crates/pine-sema/tests/fixtures.rs` or
    the strategy fixture module) for the renamed/added fixtures.
13. Add a minimal runtime fixture or unit test proving an accepted bracket call
    routes to a bracket pending exit rather than the old single-trigger
    fallback. Full runtime snapshot coverage remains in Slice 5.
14. Run:

   ```text
   cargo test -p pine-builtins strategy
   cargo test -p pine-sema strategy
   cargo test -p pine-runtime strategy
   ```

Acceptance criteria:

- The four bracket forms analyze successfully in strategy-mode scripts and
  route to bracket placement at runtime.
- `stop + loss`, `limit + profit`, 3-trigger, and 4-trigger calls still
  produce stable diagnostics.
- Indicator-mode, UDF side-effect, and requested-context variants still produce
  stable diagnostics.
- Single-trigger exits still route to single-trigger placement.
- Invalid legs reject the whole bracket and leave existing pending state
  unchanged.
- No conformance, matrix, host-surface, or public output compatibility claim has
  changed yet.

## Slice 4: Runtime Dispatch Guardrails

Goal: harden the newly enabled runtime dispatch before broad fixture expansion,
with focused regression coverage for expression order, whole-bracket rejection,
and no public output shape changes.

Steps:

1. Add focused runtime tests or fixtures for:
   - each of the four accepted bracket forms creating a bracket pending exit.
   - direct-price legs evaluated before tick-distance legs within each side
     when diagnostic order matters.
   - one invalid bracket leg rejecting the entire placement and preserving an
     existing pending exit.
   - accepted bracket calls still emitting no new public pending-order,
     bracket-leg, or exit-reason fields.
2. Confirm unsupported options and unsupported contexts are still guarded by
   sema before runtime dispatch is reachable.
3. Confirm broad `strategy.*` remains unsupported and `strategy.exit` remains
   `partial` with no conformance row update yet.
4. Run:

   ```text
   cargo test -p pine-builtins strategy
   cargo test -p pine-sema strategy
   cargo test -p pine-runtime strategy
   ```

Acceptance criteria:

- Runtime dispatch behavior is regression-covered before broad snapshots and
  host parity are added.
- No public output structs, JSON schema version, Python dictionary shape, WASM
  JSON shape, conformance row, or matrix snapshot has changed yet.

## Slice 5: Runtime Fixtures, Snapshots, and Incremental Parity

Goal: prove end-to-end bracket behavior with fixtures, golden snapshots, and
incremental append parity.

Steps:

1. Add normal-behavior runtime fixtures and snapshots:
   - `tests/fixtures/runtime/strategy_exit_bracket_stop_limit_limit_fill.pine`
     + `tests/snapshots/runtime_strategy_exit_bracket_stop_limit_limit_fill.json`
   - `tests/fixtures/runtime/strategy_exit_bracket_stop_limit_stop_fill.pine`
     + `tests/snapshots/runtime_strategy_exit_bracket_stop_limit_stop_fill.json`
   - `tests/fixtures/runtime/strategy_exit_bracket_loss_profit_profit_fill.pine`
     + `tests/snapshots/runtime_strategy_exit_bracket_loss_profit_profit_fill.json`
   - `tests/fixtures/runtime/strategy_exit_bracket_loss_profit_loss_fill.pine`
     + `tests/fixtures/runtime/strategy_exit_bracket_loss_profit_loss_bars.csv`
     + `tests/snapshots/runtime_strategy_exit_bracket_loss_profit_loss_fill.json`
   - `tests/fixtures/runtime/strategy_exit_bracket_mixed_pairs.pine`
     + `tests/snapshots/runtime_strategy_exit_bracket_mixed_pairs.json`
     covering `stop + profit` and `loss + limit` acceptance.
2. Add lifecycle fixtures:
   - `tests/fixtures/runtime/strategy_exit_bracket_creation_bar.pine` for
     creation-bar ineligibility when both legs would otherwise be touched.
   - `tests/fixtures/runtime/strategy_exit_bracket_repeated.pine` for unchanged
     repeated brackets preserving the original eligibility bar.
   - `tests/fixtures/runtime/strategy_exit_bracket_replacement.pine` for changed
     leg price resetting eligibility, single-trigger to bracket replacement, and
     bracket to single-trigger replacement.
   - `tests/fixtures/runtime/strategy_exit_bracket_invalid_leg.pine` for invalid
     price/tick diagnostics rejecting the whole bracket while leaving an
     existing pending exit unchanged.
3. Add the same-bar both-hit fixture:
   - `tests/fixtures/runtime/strategy_exit_bracket_both_hit.pine`
     + `tests/fixtures/runtime/strategy_exit_bracket_both_hit_bars.csv`
     + `tests/snapshots/runtime_strategy_exit_bracket_both_hit.json`.
   - The CSV must contain a small OHLC series where a later eligible bar touches
     both legs; the snapshot must prove the stop/loss-first fill price and the
     one-order/one-trade output.
4. Add the state-timing fixture:
   - `tests/fixtures/runtime/strategy_exit_bracket_state.pine`
     + `tests/snapshots/runtime_strategy_exit_bracket_state.json`.
   - The fixture must expose `strategy.position_size`,
     `strategy.position_avg_price`, `strategy.openprofit`,
     `strategy.netprofit`, `strategy.equity`, `strategy.closedtrades`, and
     `strategy.opentrades` before fill, on the triggering bar, and on the next
     bar.
5. Add an interaction fixture if brackets are claimed in the same
   expression/statement contexts as single-trigger exits:
   - `tests/fixtures/runtime/strategy_exit_bracket_interactions.pine`
     + `tests/snapshots/runtime_strategy_exit_bracket_interactions.json`
     covering branch, switch, for, while, pure UDF argument, and constant
     history reference contexts.
6. Register every new runtime fixture in the runtime fixture test list and add
   every state-mutating fixture to `crates/pine-runtime/tests/incremental.rs`.
   Route non-default OHLC fixtures through the existing per-fixture bars mapping.
7. Run:

   ```text
   cargo test -p pine-runtime strategy
   cargo test -p pine-runtime --test incremental
   cargo test -p pine-runtime --test profile_fixtures
   ```

Acceptance criteria:

- Every bracket form, lifecycle case, both-hit case, and state-timing case has a
  fixture and, where output is asserted, a golden snapshot.
- Incremental append execution matches full historical execution for all new
  bracket fixtures.
- Snapshots prove one order event and one closed trade per bracket fill with no
  schema change.

## Slice 6: Host Surface Parity

Goal: confirm brackets round-trip identically through CLI, Python, and WASM
without any binding-level broker logic.

Steps:

1. Add or extend a CLI strategy test that runs a bracket fixture and asserts the
   shared runtime JSON contains the expected single order event and closed
   trade.
2. Add or extend a Python test in `python/tests` that runs a bracket fixture and
   asserts the native dictionary matches the shared runtime result.
3. Add or extend a WASM test in `crates/pine-wasm/src/tests` that runs a bracket
   fixture and asserts the returned JSON matches the shared strategy result.
4. Confirm no binding duplicates bracket math, leg evaluation, or fill rules.
5. Run:

   ```text
   cargo test -p pine-cli strategy
   cargo test -p pine-wasm strategy
   python3 -m pytest python/tests
   ```

   If `pine-python` or its linked crates changed, rebuild and reinstall the
   wheel before pytest:

   ```text
   maturin build --manifest-path crates/pine-python/Cargo.toml --out dist
   python3 -m pip install --force-reinstall dist/*.whl
   ```

Acceptance criteria:

- A bracket script produces equivalent runtime output through CLI, Python, and
  WASM.
- No host binding contains broker fill or bracket conversion logic.

## Slice 7: Conformance, Docs, and Closeout

Goal: claim the bracket subset in the matrix, synchronize docs, and run the
full release verification gate.

Steps:

1. Update `tests/fixtures/conformance.tsv`:
   - keep `strategy.exit` `partial`.
   - update its notes to describe the supported single-trigger plus the four
     bracket forms, and explicitly list the still-unsupported same-side pairs
     and 3+ trigger forms.
   - reference the new positive bracket fixtures.
   - keep broad `strategy.*` `unsupported`.
2. Refresh `tests/snapshots/matrix.json` for the metadata change.
3. Synchronize maintainer-facing docs with the implemented subset:
   - `docs/CONFORMANCE.md`
   - `docs/SEMANTIC_MODEL.md`
   - `docs/EXECUTION_SEMANTICS.md`
   - `docs/ARCHITECTURE.md` (broker bracket evaluation, if it documents broker
     internals)
   - `docs/LONG_TERM_EXECUTION_PLAN.md` strategy status
   - `README.md` supported-subset wording if it enumerates `strategy.exit`
     behavior
4. Add a Phase R entry to `docs/RELEASE_NOTES.md` describing the four supported
   bracket forms, the stop/loss-first same-bar precedence, identity/replacement
   rules, invalid-leg rejection, unchanged public schema, and the still
   unsupported same-side and 3+ trigger forms.
5. Create `docs/PHASE_R_AUDIT.md` as the closeout record with completed slices,
   the implemented decision record, and the deferred broker tails carried
   forward from `docs/PHASE_Q_AUDIT.md`.
6. Set this plan's status to closed and point it at `docs/PHASE_R_AUDIT.md`.
7. Run the strategy-focused baseline and then the full release gate:

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

   ```text
   git diff --check
   scripts/verify.sh
   ```

Acceptance criteria:

- `tests/fixtures/conformance.tsv` and `tests/snapshots/matrix.json` describe
  exactly the implemented bracket subset, no more and no less.
- Docs and release notes match runtime behavior.
- `docs/PHASE_R_AUDIT.md` records the closeout, and the full release
  verification gate passes.

## Deferred Broker Tails

Carry these forward unchanged from `docs/PHASE_Q_AUDIT.md`; they remain out of
scope after Phase R:

- same-side pairs `stop + loss` and `limit + profit`, and 3+ trigger forms.
- trailing stops.
- partial exits, `qty`, `qty_percent`, and reservation behavior.
- missing-entry pre-placement.
- multiple entries, pyramiding, short exposure, and reversals.
- multiple pending exits and public pending-order records.
- commission, slippage, margin, and richer sizing.
- strategy alerts and realtime broker rollback for brackets.
