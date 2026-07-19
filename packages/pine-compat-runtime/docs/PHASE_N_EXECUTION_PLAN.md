# Phase N Strategy Exit Maintenance Execution Plan

Status: closed for the current fixture-backed `strategy.exit` profit/loss
subset. Use `docs/PHASE_M_AUDIT.md` as the baseline closeout record and
`docs/PHASE_N_AUDIT.md` as the Phase N closeout record.

Phase N should widen the existing long-only strategy exit lifecycle in small,
reviewable, fixture-backed maintenance slices. The first executable target is
`strategy.exit` profit/loss tick helpers, because they can reuse the Phase M
pending-exit lifecycle and public strategy output contract. Combined brackets,
trailing stops, partial exits, short exposure, pyramiding, and realtime broker
rollback stay out of scope unless a slice deliberately designs them.

Each slice should leave the workspace shippable and should keep semantic
claims, broker behavior, public output contracts, fixtures, snapshots, host
bindings, conformance metadata, and docs in lockstep.

## Current Starting Point

The repository has closed Phase G, Phase L, and Phase M for the current
strategy subset:

- `tests/fixtures/conformance.tsv` marks `strategy`, `strategy.entry`,
  `strategy.close`, strategy equity, strategy state variables, and
  `strategy.exit` as `partial`.
- Broad `strategy.*` remains `unsupported`.
- `strategy(...)` supports `title`, `shorttitle`, `overlay`, `max_bars_back`,
  positive const numeric `initial_capital`, and fixed default quantity settings
  through `default_qty_type=strategy.fixed` plus positive const numeric
  `default_qty_value`.
- `strategy.entry(id, strategy.long, qty=...)` opens one long market position
  at the current bar close, with no pyramiding.
- `strategy.close(id)` closes the full matching long position at the current
  bar close and cancels any matching pending exit.
- Strategy state variables are available in strategy-mode historical scripts:
  `strategy.position_size`, `strategy.position_avg_price`,
  `strategy.openprofit`, `strategy.netprofit`, and `strategy.equity`.
- Phase M added `strategy.exit(id, from_entry, stop=price)` and
  `strategy.exit(id, from_entry, limit=price)` for one broker-owned pending
  full-position exit on the current one-net-long entry.
- New or replaced pending exits are not eligible on the same bar. Unchanged
  repeated exit calls preserve the original eligibility bar.
- Stop exits fill on a later historical bar when `low <= stop`; limit exits
  fill on a later historical bar when `high >= limit`; both fill at the
  configured exit price.
- Filled exits append the existing public `strategy.orders`, `strategy.trades`,
  `strategy.position`, and `strategy.equity` data. Phase M did not add a public
  pending-order field or bump the runtime schema.
- Combined stop/limit brackets, `profit`, `loss`, trailing stops, partial
  quantity, missing-entry pre-placement, multiple pending exits, short
  exposure, `strategy.order`, rich broker settings, strategy alerts, and
  realtime strategy execution remain unsupported.

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

## Phase N Goal

The main goal is to support a narrow, deterministic `strategy.exit` profit/loss
tick subset for the current long-only full-position broker:

- `strategy.exit(id, from_entry, profit=ticks)` creates or replaces a pending
  limit exit at `strategy.position_avg_price + ticks * syminfo.mintick` for the
  current long entry.
- `strategy.exit(id, from_entry, loss=ticks)` creates or replaces a pending
  stop exit at `strategy.position_avg_price - ticks * syminfo.mintick` for the
  current long entry.
- The first executable Phase N subset should accept exactly one trigger family
  per `strategy.exit` call: one of `stop`, `limit`, `profit`, or `loss`.
- Mixed trigger families such as `stop + limit`, `profit + loss`, `stop +
  profit`, `limit + loss`, or any three-trigger form remain unsupported until
  a bracket slice defines same-bar precedence and order lifecycle rules.

This path keeps the feature useful while avoiding a premature bracket engine.
It also keeps public strategy output stable by representing filled profit/loss
exits through the same `strategy.exit` order event and closed-trade contract
used by Phase M stop/limit exits.

## Non-Goals

Do not include these in the first Phase N compatibility claim:

- combined bracket exits with multiple active trigger prices.
- same-bar high/low precedence between stop and limit triggers.
- trailing stop behavior.
- partial exits, `qty`, `qty_percent`, and reservation behavior.
- multiple simultaneous entries, pyramiding, short exposure, and reversals.
- `strategy.order` and richer order modification APIs.
- commission, slippage, margin, currency conversion, cash sizing, contracts,
  and percent-of-equity sizing.
- strategy closed-trade/open-trade namespaces.
- strategy alerts, alert placeholders, and `alert_message` delivery.
- realtime strategy execution and forming-bar broker rollback.
- host-specific broker APIs or chart UI behavior outside the public runtime
  contract.

## Rules for Every Slice

- Add fixtures before or alongside behavior changes.
- Keep the compatibility matrix conservative. Do not widen a strategy row
  unless the exact supported form has semantic fixtures, runtime fixtures,
  host coverage, conformance metadata, docs, and verification evidence.
- Preserve indicator behavior. Indicator scripts must not gain broker state,
  strategy output fields, or strategy-mode-only order functions.
- Keep strategy order calls rejected in UDFs under the existing side-effect
  policy.
- Keep strategy order calls rejected in requested-context expressions. The
  request provider context remains isolated and data-only.
- Treat the broker as deterministic runtime state. Core crates must not depend
  on account services, wall-clock time, host callbacks, filesystem data, or
  network data.
- Keep all trigger policies explicit. If a trigger combination, same-bar
  ordering rule, or order modification rule is not designed in a slice, keep it
  diagnostic-only.
- Reuse the existing public strategy output contract whenever possible. Adding
  public pending-order fields or changing item shapes requires schema review,
  snapshot refreshes, CLI/Python/WASM contract updates, and release notes.
- Keep CLI, Python, and WASM behavior synchronized. A script that compiles and
  runs through one public host should produce equivalent runtime JSON or native
  dictionary data through the others.
- Keep docs and conformance metadata in the same change as behavior. No code
  slice should leave a feature implemented but unclaimed, or claimed without
  fixture coverage.
- Run the full release verification gate before closing Phase N.

## Internal Structure Rules

Phase N should grow the strategy subsystem without turning existing analyzer,
runtime, or output modules into catch-all broker files.

- Keep `pine-builtins` responsible for strategy declaration/order signatures
  and accepted constants. It should not own broker semantics.
- Keep `pine-sema::analyzer::strategy` responsible for strategy-mode gating,
  unsupported strategy variants, declaration settings, order argument checks,
  and strategy-specific diagnostic policy.
- Keep `pine-runtime::strategy` responsible for broker state, pending exits,
  trigger conversion, fill rules, state accessors, and profit calculations.
- Keep `pine-runtime::builtins::strategy` responsible for evaluating accepted
  strategy calls, extracting runtime arguments, and refreshing strategy state
  variables after broker mutation.
- Keep `pine-runtime::output::strategy` limited to public result structs. It
  should not become the source of truth for broker transitions.
- Keep Python and WASM bindings thin. They should map the shared strategy
  result model and must not duplicate broker math or fill rules.
- Treat roughly 800 lines in a production Rust file as a review trigger. Split
  before adding another order family, trigger rule, or accounting path.

## Intended Module Layout

Use existing crate boundaries. A new crate is not needed for Phase N.

Recommended layout:

```text
crates/pine-builtins/src/
   constants/strings.rs         strategy direction/order constants as needed
   namespaces/strategy.rs       declaration and accepted order signatures only

crates/pine-sema/src/analyzer/
   strategy.rs                  strategy mode checks and order validation
   expressions.rs               request/UDF side-effect gating if needed
   unsupported.rs               unsupported strategy variants and reasons

crates/pine-runtime/src/
   strategy/
      mod.rs                    broker facade and re-exports
      broker.rs                 broker state and high-level transitions
      exits.rs                  add if trigger conversion outgrows broker.rs
      fills.rs                  add if OHLC trigger rules need isolation
      limits.rs                 add only when quantity rules arrive
   builtins/
      strategy.rs               strategy call evaluation and symbol refresh hooks
   runtime/
      historical.rs             strategy orchestration only
      realtime.rs               keep strategy realtime unsupported until designed
   output/
      strategy.rs               public strategy result structs
      json.rs                   shared public runtime JSON

crates/pine-cli/src/
   commands/run.rs              no broker logic; uses shared runtime behavior

crates/pine-python/src/
   lib.rs                       maps shared runtime result only

crates/pine-wasm/src/
   lib.rs                       returns shared strategy JSON only
```

Ownership notes:

- Profit/loss conversion should be broker-owned or strategy-runtime-owned, not
  output-owned.
- If conversion uses `syminfo.mintick`, the mintick source must be the same
  fixed-default symbol metadata used by the current `syminfo.mintick` and
  `math.round_to_mintick` subsets unless a slice explicitly widens chart
  metadata.
- Pending exits remain internal broker state. Runtime output arrays record
  filled events and resulting account state after broker behavior happens.
- Strategy variables should refresh from broker state after every supported
  broker mutation.

## Phase N Decision Record

Slice 0 confirmed this decision record before the first behavior slice changes
conformance metadata. Future slices may amend it only with matching fixtures,
docs, matrix metadata, and verification evidence.

- First supported forms: exactly one of `profit` or `loss`, with `id` and
  `from_entry`, in strategy-mode scripts only.
- Tick value: `profit` and `loss` are numeric tick distances. They must be
  finite and positive after runtime evaluation.
- Mintick source: use the current fixed-default `syminfo.mintick` value exposed
  by `pine-builtins::named_float_constant("syminfo.mintick")` unless a later
  phase widens chart metadata.
- Long profit conversion: `target_price = current_avg_price + ticks * mintick`.
- Long loss conversion: `target_price = current_avg_price - ticks * mintick`.
- Position requirement: conversion is accepted only when `from_entry` matches
  the current supported long entry. Missing or mismatched entries produce the
  existing stable strategy-exit entry diagnostic and do not create orphan
  pending exits.
- Replacement rule: a supported profit/loss exit creates or replaces the single
  active pending exit for the current entry id, following the Phase M pending
  exit lifecycle.
- Eligibility rule: a new or changed profit/loss exit is not eligible on the
  same bar. An unchanged repeated profit/loss exit preserves the original
  eligibility bar.
- Fill rule: profit-derived exits reuse the Phase M limit trigger. Loss-derived
  exits reuse the Phase M stop trigger.
- Public output: filled profit/loss exits append the same `strategy.exit` order
  event and closed-trade output shapes as Phase M stop/limit exits. Do not add
  public pending-order output in the first Phase N slice.
- Schema review: no runtime schema bump is expected for the first profit/loss
  subset if the public output item shapes remain unchanged.
- Combined trigger policy: any call with more than one trigger family remains
  unsupported until the bracket design gate is complete.

## Slice 0: Baseline Lock and Design Confirmation

Goal: lock the Phase M closeout boundary and confirm the exact Phase N first
slice before positive support is claimed.

Steps:

1. Read `docs/PHASE_M_AUDIT.md`, this document, and
   `tests/fixtures/conformance.tsv` before editing code.
2. Confirm the decision record above, especially tick conversion, mintick
   source, mixed-trigger rejection, same-bar eligibility, and public output
   policy.
3. Review existing negative fixtures:
   - `tests/fixtures/sema/unsupported_strategy_exit_profit_loss.pine`
   - `tests/fixtures/sema/unsupported_strategy_exit_stop_limit.pine`
   - `tests/fixtures/sema/unsupported_strategy_exit_trailing.pine`
   - `tests/fixtures/sema/unsupported_strategy_exit_partial_quantity.pine`
   - `tests/fixtures/sema/unsupported_strategy_exit_missing_id.pine`
4. Add or tighten negative fixtures before implementation if any planned
   unsupported combination is not fixture-backed:
   - `profit + loss`.
   - `stop + profit`.
   - `limit + loss`.
   - `profit` or `loss` with `qty` or `qty_percent`.
   - trailing arguments mixed with supported Phase N arguments.
   Slice 0 fixture coverage:
   - `tests/fixtures/sema/unsupported_strategy_exit_profit_loss.pine`
   - `tests/fixtures/sema/unsupported_strategy_exit_stop_profit.pine`
   - `tests/fixtures/sema/unsupported_strategy_exit_limit_loss.pine`
   - `tests/fixtures/sema/unsupported_strategy_exit_profit_qty.pine`
   - `tests/fixtures/sema/unsupported_strategy_exit_loss_qty_percent.pine`
   - `tests/fixtures/sema/unsupported_strategy_exit_profit_trailing.pine`
5. Run the focused semantic baseline:

   ```text
   cargo test -p pine-sema strategy
   cargo test -p pine-builtins strategy
   ```

6. Do not update `tests/fixtures/conformance.tsv` in Slice 0 unless the update
   only documents unsupported boundaries with fixtures already present.

Acceptance criteria:

- The first Phase N supported forms and rejected forms are written down before
  runtime behavior changes.
- Unsupported profit/loss and mixed-trigger variants are fixture-backed.
- Existing Phase M stop/limit support remains unchanged.

## Slice 1: Built-In Signature and Semantic Staging

Goal: teach semantic analysis which Phase N `strategy.exit` forms are allowed,
without yet claiming runtime behavior broadly.

Steps:

1. Update the strategy namespace signature in `pine-builtins` if `profit` and
   `loss` are not accepted named arguments for `strategy.exit`.
2. Update `crates/pine-sema/src/analyzer/strategy.rs` so
   `validate_strategy_exit_args` understands trigger families:
   - price triggers: `stop`, `limit`.
   - tick triggers: `profit`, `loss`.
   - rejected quantity triggers/options: `qty`, `qty_percent`.
   - rejected trailing triggers: `trail_price`, `trail_points`,
     `trail_offset`.
   - rejected metadata/options: `oca_name`, `comment`, `alert_message`, and
     any other unimplemented strategy-exit option.
3. Accept exactly one trigger family for the first executable subset.
4. Keep all mixed trigger families diagnostic-only. Use stable diagnostics that
   make clear the combined trigger or bracket behavior is not yet supported.
5. Keep `strategy.exit` strategy-mode-only.
6. Keep `strategy.exit` rejected in UDF and requested-context side-effect
   paths.
7. Add positive semantic fixtures:
   - `tests/fixtures/sema/supported_strategy_exit_profit.pine`
   - `tests/fixtures/sema/supported_strategy_exit_loss.pine`
8. Add or update negative semantic fixtures for mixed triggers and unsupported
   options.
9. Add focused tests in `crates/pine-sema/tests/fixtures.rs` following the
   existing strategy fixture style.
10. Run:

    ```text
    cargo test -p pine-builtins strategy
    cargo test -p pine-sema strategy
    ```

Acceptance criteria:

- `strategy.exit(id, from_entry, profit=...)` and
  `strategy.exit(id, from_entry, loss=...)` analyze successfully in
  strategy-mode scripts.
- Indicator-mode, UDF side-effect, requested-context, mixed-trigger, trailing,
  and partial-quantity variants still produce stable diagnostics.
- No runtime or public output compatibility claim has changed yet.

## Slice 2: Broker Conversion Helpers

Goal: add broker-owned profit/loss conversion while reusing the Phase M pending
exit lifecycle.

Steps:

1. Add broker methods for profit/loss tick exits, or add a small internal
   conversion helper if the existing broker file remains readable:
   - `place_exit_profit_ticks(id, from_entry, ticks, mintick, bar_index)`.
   - `place_exit_loss_ticks(id, from_entry, ticks, mintick, bar_index)`.
2. Validate tick distance and mintick before creating pending state:
   - ticks must be finite and positive.
   - mintick must be finite and positive.
   - invalid values should append a stable runtime diagnostic and leave pending
     state unchanged.
3. Reuse existing current-entry validation. Missing or mismatched entries
   should not create pending exits.
4. Convert prices for the current long broker model:
   - profit -> limit price from average entry price.
   - loss -> stop price from average entry price.
5. Reuse the existing `PendingExitTrigger::Limit` and
   `PendingExitTrigger::Stop` fill paths if no public distinction is needed.
6. Preserve Phase M replacement semantics:
   - unchanged repeated trigger keeps original eligibility.
   - changed trigger price or trigger kind replaces pending state and delays
     eligibility to the replacement bar.
7. Add broker unit tests for:
   - profit conversion from average entry price.
   - loss conversion from average entry price.
   - invalid tick values.
   - invalid mintick values.
   - missing or mismatched entry ids.
   - unchanged repeated profit/loss call preserving eligibility.
   - changed profit/loss call delaying eligibility.
   - profit replacing stop and loss replacing limit, if mixed replacement
     across separate calls is accepted.
8. If `crates/pine-runtime/src/strategy/broker.rs` grows beyond the review
   threshold, split trigger conversion into `strategy/exits.rs` before adding
   more behavior.
9. Run:

   ```text
   cargo test -p pine-runtime strategy
   ```

Acceptance criteria:

- Broker tests prove profit/loss conversion without touching public output
  shapes.
- Existing stop/limit tests continue to pass.
- Invalid runtime values are deterministic diagnostics, not panics.

## Slice 3: Runtime Dispatch

Goal: evaluate `profit` and `loss` arguments at runtime and route them through
the broker conversion helpers.

Steps:

1. Update `crates/pine-runtime/src/builtins/strategy.rs` so
   `eval_strategy_exit` extracts `profit` and `loss` named arguments.
2. Preserve positional behavior for the existing `id`, `from_entry`, `stop`,
   and `limit` subset. Do not add ambiguous positional support for `profit` or
   `loss` unless semantic signatures and fixtures explicitly require it.
3. Evaluate `id` and `from_entry` once, as the existing runtime path does.
4. Evaluate only the accepted trigger argument after semantic staging has
   guaranteed at most one supported trigger family.
5. Convert the evaluated trigger value with `as_f64().unwrap_or(f64::NAN)` or
   the existing local convention, then let broker validation decide whether it
   is usable.
6. Fetch mintick through the existing fixed-default symbol metadata path used
   by `math.round_to_mintick`, unless Slice 0 deliberately chose another
   source.
7. Route:
   - `profit` -> broker profit tick helper.
   - `loss` -> broker loss tick helper.
   - existing `stop` and `limit` -> existing broker methods.
8. Add runtime unit tests in `crates/pine-runtime/src/tests/strategy.rs` for
   direct source snippets that use `profit` and `loss`.
9. Run:

   ```text
   cargo test -p pine-runtime strategy
   cargo test -p pine-runtime --test incremental
   ```

Acceptance criteria:

- Runtime dispatch supports profit/loss without changing stop/limit behavior.
- Profit/loss exits fill through the same pending-exit eligibility rules as
  Phase M.
- Incremental append execution still matches full historical execution for all
  runtime fixtures.

## Slice 4: Runtime Fixtures, Snapshots, and Conformance

Goal: claim the first positive Phase N runtime behavior with golden evidence.

Steps:

1. Add runtime fixtures:
   - `tests/fixtures/runtime/strategy_exit_profit.pine`
   - `tests/fixtures/runtime/strategy_exit_loss.pine`
2. Keep fixture scripts small and explicit:
   - one long entry.
   - one profit or loss exit.
   - bars that prove the exit is not eligible on placement bar.
   - a later bar that triggers the converted limit or stop price.
   - plots for relevant state variables if they help review behavior.
3. Add edge fixture coverage if needed:
   - repeated unchanged profit/loss call.
   - replacement from one tick distance to another.
   - `strategy.close(id)` cancelling a profit/loss pending exit.
4. Refresh golden runtime snapshots through the existing CLI snapshot workflow.
   Use the repository's established update command only for snapshots that
   intentionally change.
5. Update `crates/pine-cli/src/main.rs` golden snapshot lists if runtime
   snapshots are enumerated there.
6. Update `tests/fixtures/conformance.tsv`:
   - keep `strategy.exit` as `partial`.
   - extend its notes to include the exact profit/loss tick subset.
   - keep broad `strategy.*` as `unsupported`.
   - keep mixed trigger/bracket notes unsupported.
7. Refresh `tests/snapshots/matrix.json` if conformance metadata changes.
8. Run:

   ```text
   UPDATE_SNAPSHOTS=1 cargo test -p pine-cli runtime_outputs_match_golden_snapshots
   UPDATE_SNAPSHOTS=1 cargo test -p pine-cli matrix_output_matches_golden_snapshot
   cargo test -p pine-cli strategy
   cargo test -p pine-runtime strategy
   cargo test -p pine-runtime --test incremental
   ```

Acceptance criteria:

- Positive runtime fixtures and snapshots cover profit and loss exits.
- Conformance metadata exactly matches the implemented subset.
- Public strategy output remains schema-compatible unless a deliberate schema
  review says otherwise.

## Slice 5: Public Host Contract Coverage

Goal: prove CLI, Python, and WASM expose the same profit/loss strategy result
contract.

Steps:

1. Add or extend CLI tests to include the profit and loss runtime snapshots.
2. Add Python binding tests in `python/tests/test_bindings.py` for representative
   profit and loss exits:
   - `orders` contains the entry order and the `strategy.exit` order.
   - the exit order uses the converted fill price.
   - `trades` contains the source entry id and expected profit.
   - `position` clears after the exit fill.
   - `equity` reflects realized profit/loss.
3. Add WASM JSON tests in `crates/pine-wasm/src/tests/mod.rs` for equivalent
   output fields.
4. Keep host tests focused on public contracts. Do not duplicate every broker
   unit test in host bindings.
5. If `crates/pine-python/src/lib.rs` changes, rebuild and reinstall the wheel
   before pytest:

   ```text
   maturin build --manifest-path crates/pine-python/Cargo.toml --out dist
   python3 -m pip install --force-reinstall dist/*.whl
   python3 -m pytest python/tests
   ```

6. Otherwise run the focused host checks:

   ```text
   cargo test -p pine-cli strategy
   cargo test -p pine-wasm strategy
   python3 -m pytest python/tests
   ```

Acceptance criteria:

- CLI, Python, and WASM expose equivalent profit/loss exit results.
- Python dictionary keys and WASM JSON fields remain synchronized with the
  shared runtime result model.
- No host binding contains independent broker math.

## Slice 6: Interaction Hardening

Goal: prove profit/loss exits behave correctly in supported statement and state
contexts.

Steps:

1. Add a runtime interaction fixture, or extend the existing Phase M
   interaction fixture only if it remains readable:
   - branch-gated profit/loss placement.
   - switch-gated profit/loss placement.
   - loop-gated profit/loss placement.
   - strategy state variables read before and after placement/fill.
   - constant history references to strategy state after the fill.
   - replacement of a pending profit/loss exit from a later supported branch.
2. Add negative semantic fixtures only for gaps not already covered:
   - profit/loss inside UDF side-effect contexts.
   - profit/loss inside requested-context expressions.
3. Ensure every new runtime fixture participates in full historical vs
   incremental append execution through the existing fixture runner.
4. Add profile fixture coverage only if profit/loss conversion introduces new
   retained storage beyond the existing pending-exit state.
5. Run:

   ```text
   cargo test -p pine-sema strategy
   cargo test -p pine-runtime strategy
   cargo test -p pine-runtime --test incremental
   cargo test -p pine-runtime --test profile_fixtures
   ```

Acceptance criteria:

- Profit/loss exits behave consistently across supported control-flow contexts.
- Strategy state variables and history references remain bar-aligned.
- Incremental append execution matches full historical execution.

## Slice 7: Bracket Design Gate

Goal: decide whether combined trigger support is ready, or keep it explicitly
unsupported with stronger fixtures.

This slice is a design gate. Do not implement combined brackets until these
questions have written answers and fixture examples:

1. Which combined forms are in scope?
   - `stop + limit`.
   - `profit + loss`.
   - `stop + profit`.
   - `limit + loss`.
   - other mixed forms.
2. Does a bracket create one pending exit with two triggers, or two linked
   pending child exits?
3. If both high and low cross their trigger prices on the same historical bar,
   which trigger wins for the current OHLC-only model?
4. Does same-bar precedence depend on whether the script is long-only, short,
   or future multi-entry? Phase N should only answer long-only if it proceeds.
5. Does a repeated bracket call preserve eligibility when both trigger prices
   are unchanged?
6. Does changing one side of the bracket reset eligibility for both sides or
   only the changed side?
7. How does `strategy.close(id)` cancel a bracket?
8. What public output should reveal the chosen trigger, if anything? The first
   Phase N bracket should prefer the existing `strategy.exit` order event shape
   unless a review proves an exit reason field is required.
9. Does bracket support require a runtime schema bump?
10. Which negative fixtures remain unsupported after the bracket decision?

Recommended conservative outcome for Phase N:

- Keep combined brackets unsupported after profit/loss support lands.
- Add explicit negative fixtures for all common combined trigger families.
- Record same-bar precedence as a future design task instead of silently
  choosing a rule.

Slice 7 outcome:

- Phase N keeps every combined trigger form unsupported. This includes
  `stop + limit`, `profit + loss`, `stop + profit`, `limit + loss`,
  `stop + loss`, `limit + profit`, and three-trigger calls.
- The broker continues to model one pending exit with one trigger price. It
  does not create two-trigger brackets or linked child exits.
- Same-bar high/low precedence remains deliberately undesigned for Phase N
  because the current OHLC-only historical model cannot prove which side of a
  bracket would have filled first.
- Repeated bracket eligibility, one-sided bracket replacement, and
  `strategy.close(id)` bracket cancellation remain future design questions.
- No public exit-reason field, pending-order field, or runtime schema bump is
  introduced for bracket behavior in Phase N.
- Unsupported combined trigger fixtures:
  - `tests/fixtures/sema/unsupported_strategy_exit_stop_limit.pine`
  - `tests/fixtures/sema/unsupported_strategy_exit_profit_loss.pine`
  - `tests/fixtures/sema/unsupported_strategy_exit_stop_profit.pine`
  - `tests/fixtures/sema/unsupported_strategy_exit_limit_loss.pine`
  - `tests/fixtures/sema/unsupported_strategy_exit_stop_loss.pine`
  - `tests/fixtures/sema/unsupported_strategy_exit_limit_profit.pine`
  - `tests/fixtures/sema/unsupported_strategy_exit_three_triggers.pine`

If bracket implementation is deliberately selected after the design gate, use a
separate follow-up slice with its own positive fixtures, broker tests, host
tests, conformance update, and closeout evidence.

Acceptance criteria:

- Combined trigger behavior is either deliberately designed or deliberately
  kept unsupported.
- Unsupported combined variants remain fixture-backed.
- The project does not accidentally claim bracket compatibility because
  profit/loss support landed.

## Slice 8: Documentation, Release Notes, and Audit

Goal: close Phase N with a durable record of exactly what changed and what
remains unsupported.

Steps:

1. Update `docs/PHASE_M_AUDIT.md` only if it needs a pointer to Phase N
   maintenance. Do not rewrite Phase M history.
2. Add `docs/PHASE_N_AUDIT.md` when implementation is complete.
3. The audit should record:
   - supported profit/loss forms.
   - unsupported mixed trigger and bracket forms.
   - runtime fill and eligibility rules.
   - public output/schema decision.
   - fixture evidence.
   - host binding evidence.
   - verification commands and results.
   - remaining maintenance tails.
   - recommended next stage.
4. Update `docs/RELEASE_NOTES.md` if the repository uses it to describe the
   currently supported subset.
5. Update `docs/LONG_TERM_EXECUTION_PLAN.md` only if Phase N changes backlog
   priority or closes a documented maintenance tail.
6. Run the full closeout gate:

   ```text
   git diff --check
   scripts/verify.sh
   ```

Acceptance criteria:

- Phase N has a closeout audit similar to previous phase audit documents.
- Release notes and long-term planning docs do not contradict the conformance
  matrix.
- A future strategy phase can start without relying on unstated profit/loss or
  bracket semantics.

## Verification Ladder

Use focused commands while developing, then the full release gate before
closeout.

Semantic and built-in checks:

```text
cargo test -p pine-builtins strategy
cargo test -p pine-sema strategy
```

Runtime checks:

```text
cargo test -p pine-runtime strategy
cargo test -p pine-runtime --test incremental
cargo test -p pine-runtime --test profile_fixtures
```

Public host checks:

```text
cargo test -p pine-cli strategy
cargo test -p pine-wasm strategy
python3 -m pytest python/tests
```

Snapshot refreshes, only when expected:

```text
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli runtime_outputs_match_golden_snapshots
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli matrix_output_matches_golden_snapshot
UPDATE_SNAPSHOTS=1 cargo test -p pine-wasm analysis_outputs_match_golden_snapshots
```

Python wheel rebuild, only when Rust crates used by Python bindings or
`crates/pine-python` changed:

```text
maturin build --manifest-path crates/pine-python/Cargo.toml --out dist
python3 -m pip install --force-reinstall dist/*.whl
python3 -m pytest python/tests
```

Closeout:

```text
git diff --check
scripts/verify.sh
```

## Phase N Closeout Checklist

Complete this checklist before calling Phase N closed. If an item is
intentionally deferred, record the reason and risk in `docs/PHASE_N_AUDIT.md`.

- [x] Phase N decision record confirms supported profit/loss forms and rejected
      combined trigger forms.
- [x] Positive semantic fixtures cover supported `profit` and `loss` calls.
- [x] Negative semantic fixtures cover mixed triggers, trailing options,
      partial quantity options, UDF side effects, requested-context use, and
      indicator-mode misuse.
- [x] Broker unit tests cover tick conversion, invalid values, missing entries,
      replacement, same-bar ineligibility, and fill behavior.
- [x] Runtime fixtures and snapshots cover profit and loss exits.
- [x] Interaction fixtures cover supported branch, switch, loop, strategy
      state, history, and incremental paths.
- [x] CLI, Python, and WASM tests assert representative public contracts.
- [x] `tests/fixtures/conformance.tsv` records the exact supported subset and
      keeps broad `strategy.*` unsupported.
- [x] Matrix snapshots are refreshed if conformance metadata changed.
- [x] Runtime schema version is reviewed and either unchanged with a note or
      bumped with public snapshot updates.
- [x] Combined bracket support is either deliberately deferred with fixtures or
      implemented through a separate designed slice.
- [x] `docs/PHASE_N_AUDIT.md` records closure evidence and remaining tails.
- [x] Release notes and long-term planning docs are updated if needed.
- [x] `git diff --check` passes.
- [x] `scripts/verify.sh` passes.
