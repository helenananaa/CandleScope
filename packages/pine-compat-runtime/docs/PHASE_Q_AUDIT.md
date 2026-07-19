# Phase Q Audit: Strategy Exit Bracket Design Gate

Status: closed.

Phase Q is a design-gate and diagnostic-hardening phase for future
`strategy.exit` bracket support. It must not widen executable strategy
compatibility, conformance status, runtime output schemas, Python dictionaries,
WASM JSON, or runtime snapshots unless a later slice is explicitly changed into
a fixture-backed behavior phase.

## Completed Slices

- Slice 0 locked the Phase P/O strategy baseline, confirmed Phase Q as a design
  gate, synchronized the long-term roadmap with the planned Phase Q target, and
  recorded the current unsupported combined-trigger boundary before any
  diagnostic or behavior changes.
- Slice 1 hardened user-visible `strategy.exit` diagnostics so they describe
  the current strategy subset instead of old phase names, added a
  diagnostic-only four-trigger combined-exit fixture, and refreshed conformance
  metadata plus the matrix metadata snapshot without changing runtime behavior.
- Slice 2 recorded the future bracket semantics decision: a first positive
  bracket subset should use one downside leg plus one upside leg in the current
  one-pending-exit broker, preserve public output shapes, and use a
  conservative stop/loss-first same-bar both-hit policy.
- Slice 3 recorded the fixture inventory a later positive bracket phase must
  add before claiming support, including semantic acceptance/rejection,
  runtime behavior, same-bar both-hit, state timing, incremental, and host
  smoke coverage.
- Slice 4 mapped a future first bracket implementation to the existing module
  ownership boundaries so a later behavior phase can proceed without moving
  broker responsibility into built-ins, output structs, Python, or WASM.
- Slice 5 recorded why bracket design is the next small strategy maintenance
  target and ranked the larger broker/reporting tails that remain deferred.
- Slice 6 synchronized maintainer-facing conformance, semantic, execution,
  architecture, and release-note docs with the Phase Q design gate while
  preserving the unsupported runtime bracket boundary.
- Slice 7 closed the audit, synchronized roadmap and execution-plan status,
  kept conformance conservative, and ran the full release verification gate.

## Slice 0 Baseline

Phase P is closed for structural broker maintenance. It split strategy broker
internals without changing the Pine compatibility surface, public runtime
schema, host output shapes, or existing strategy behavior. The current broker
layout remains:

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

Phase O is closed for the current fixture-backed strategy reporting count
subset. `strategy.closedtrades` and `strategy.opentrades` remain script-state
count variables only; no public open-trade records, pending-order records,
partial-fill fields, exit-reason fields, or schema bump were added.

The current conformance boundary remains conservative:

- `strategy`, `strategy.entry`, `strategy.close`, strategy equity, strategy
  state variables, `strategy.closedtrades`, `strategy.opentrades`, and
  `strategy.exit` are `partial`.
- Broad `strategy.*` remains `unsupported`.
- The supported `strategy.exit` subset remains stop-only, limit-only,
  profit-only, or loss-only full-position exits for the current one-net-long
  broker.
- Combined trigger, trailing, partial quantity, missing-entry, multiple pending
  exit, short exposure, pyramiding, richer order, commission, slippage, margin,
  strategy alert, and realtime strategy forms remain unsupported.

Existing combined-trigger semantic fixtures cover:

- `tests/fixtures/sema/unsupported_strategy_exit_stop_limit.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_profit_loss.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_stop_profit.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_limit_loss.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_stop_loss.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_limit_profit.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_three_triggers.pine`

The analyzer rejects combined trigger families before runtime behavior is
reachable. Runtime extraction still selects the first supported single trigger
family in the order stop, limit, profit, loss, but that fallback is protected by
semantic rejection for combined trigger calls. The broker still stores a single
`pending_exit` with one `PendingExitTrigger`, and `evaluate_pending_exits`
preserves creation-bar ineligibility with
`last_update_bar_index >= bar_index`.

Phase Q therefore remains appropriate as a design gate rather than a bracket
implementation phase. The next slice should harden user-visible
`strategy.exit` diagnostics and add a diagnostic-only four-trigger fixture
without changing runtime behavior or public host contracts.

## Slice 1 Diagnostic Boundary

Slice 1 kept diagnostic codes unchanged while replacing stale Phase N/Slice 1
wording in `validate_strategy_exit_args` with phase-neutral current-subset
messages:

- positional `profit`/`loss` rejection:
  `` `strategy.exit` profit and loss arguments must be named arguments ``
- unsupported option rejection:
  `` `strategy.exit` argument `{name}` is not supported in the current strategy subset ``
- combined trigger rejection:
  `` `strategy.exit` combined trigger families are not supported in the current strategy subset ``

The diagnostic-only fixture
`tests/fixtures/sema/unsupported_strategy_exit_four_triggers.pine` now covers
the maximal `stop + limit + profit + loss` trigger family directly. It is
referenced from the existing `strategy.exit` partial row and broad
`strategy.*` unsupported row in `tests/fixtures/conformance.tsv`; neither row
changed status. `tests/snapshots/matrix.json` was refreshed only for the
metadata fixture-list change.

## Slice 2 Bracket Decision Record

Phase Q does not implement bracket behavior. These decisions define the first
future positive bracket subset that a later behavior phase may implement with
fixtures.

Selected future first bracket subset:

- Accept exactly two trigger legs: one downside leg and one upside leg for the
  current long-only broker.
- Downside legs are `stop=price` and `loss=ticks`.
- Upside legs are `limit=price` and `profit=ticks`.
- The first future subset may therefore support `stop + limit`,
  `stop + profit`, `loss + limit`, and `loss + profit`.
- Keep same-side pairs unsupported in the first future subset:
  `stop + loss` and `limit + profit`.
- Keep three-trigger and four-trigger calls unsupported for the current broker
  model.

Price and tick conversion:

- Profit/loss tick distances are converted once at placement time from the
  current `strategy.position_avg_price`.
- Converted tick legs use the same fixed default `syminfo.mintick` source as
  Phase N.
- If a later pyramiding phase changes average price behavior, existing bracket
  prices should remain fixed after placement unless that later phase explicitly
  reopens order-repricing semantics.

Expression evaluation and invalid-leg behavior:

- A future implementation should evaluate only the selected bracket leg
  expressions after `id` and `from_entry`.
- Leg evaluation should use a broker-neutral canonical order: downside leg
  first, then upside leg. Within each side, direct price legs (`stop`, `limit`)
  should be handled before tick-distance legs (`loss`, `profit`) when a
  diagnostic needs a stable ordering.
- Runtime diagnostics for invalid prices, invalid tick distances, invalid
  mintick, flat state, or mismatched `from_entry` happen before identity
  comparison or replacement.
- If either bracket leg is invalid, the whole bracket placement is rejected.
  A valid remaining leg must not silently become a single-trigger exit.
- Invalid bracket placement leaves any existing pending exit unchanged.

Pending-exit model:

- Prefer extending `PendingExitTrigger` into a single-trigger or bracket enum.
  This keeps the existing one `pending_exit` slot and avoids implying support
  for multiple independent pending exits.
- Defer a pending-order collection until partial exits, multiple entries,
  reservation behavior, or richer order reporting is in scope.

Identity and replacement:

- A bracket is owned by one pending exit record with `id`, `from_entry`, and
  both leg definitions.
- Repeating an identical bracket preserves the original eligibility bar.
- Changing either leg kind or price resets `last_update_bar_index`, making the
  bracket ineligible on the replacement bar.
- Replacing a single-trigger pending exit with a bracket creates a new pending
  exit and resets eligibility.
- Replacing a bracket with a single-trigger exit cancels the unused leg
  immediately and resets eligibility.
- Changing the exit `id` for the same current `from_entry` replaces the pending
  exit under the existing one-slot model. `from_entry` must still match the
  current long entry.

Same-bar both-hit policy:

- Use deterministic stop/loss-first precedence for the first future long-only
  bracket subset when a later eligible historical bar touches both bracket legs.
- This is a conservative rule for historical OHLC bars without intrabar path
  data. It avoids optimistic fills and keeps snapshots deterministic.
- The first future subset should not emit a runtime diagnostic merely because
  both legs were touched. A richer intrabar path model may reopen this decision
  in a later phase.

Fill output and public contract:

- A bracket fill emits exactly one `strategy.exit` order event using the exit
  id.
- The resulting closed trade remains keyed by the source entry id.
- The filled leg is visible only through the existing filled price and trade
  profit fields.
- No public pending-order record, bracket-leg metadata, or exit-reason field is
  added in the first future subset.
- CLI JSON, Python dictionaries, and WASM JSON keep the existing shared
  strategy result shape and runtime `schemaVersion: 3`.

State-variable timing:

- Newly created or replaced brackets remain ineligible on the creation or
  replacement bar.
- Pending brackets are evaluated after script statements on each historical
  bar.
- Script reads on a triggering bar see pre-fill state.
- Public strategy output and equity for the triggering bar include the fill
  after pending-exit evaluation.
- Next-bar reads see updated `strategy.position_size`,
  `strategy.position_avg_price`, `strategy.openprofit`,
  `strategy.netprofit`, `strategy.equity`, `strategy.closedtrades`, and
  `strategy.opentrades`.

Deferred broker tails:

- Partial exits, `qty`, `qty_percent`, and reservation behavior remain
  deferred because they require quantity allocation and partial trade
  accounting.
- Missing-entry pre-placement remains deferred because it requires pending
  exits without a current position and stronger order lifecycle rules.
- Multiple pending exits and pending-order collections remain deferred until
  multiple entries, pyramiding, or richer order reporting is in scope.
- Short exposure, reversals, commission, slippage, margin, strategy alerts, and
  realtime broker rollback remain separate larger broker phases.

## Slice 3 Future Fixture Plan

These fixtures are not added in Phase Q except for diagnostic-only unsupported
coverage from Slice 1. A later positive bracket implementation phase must add
or update this inventory before widening any conformance claim.

Semantic acceptance fixtures:

- `tests/fixtures/sema/supported_strategy_exit_stop_limit.pine`
- `tests/fixtures/sema/supported_strategy_exit_stop_profit.pine`
- `tests/fixtures/sema/supported_strategy_exit_limit_loss.pine`
- `tests/fixtures/sema/supported_strategy_exit_profit_loss.pine`

Semantic fixtures that must remain unsupported in the first future subset:

- `tests/fixtures/sema/unsupported_strategy_exit_stop_loss.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_limit_profit.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_three_triggers.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_four_triggers.pine`
- existing trailing, partial quantity, missing-entry, requested-context, and
  UDF side-effect fixtures.

Runtime fixtures for normal bracket behavior:

- `tests/fixtures/runtime/strategy_exit_bracket_stop_limit_limit_fill.pine`
  plus `tests/snapshots/runtime_strategy_exit_bracket_stop_limit_limit_fill.json`
  for a price bracket whose upside limit leg fills on a later bar.
- `tests/fixtures/runtime/strategy_exit_bracket_stop_limit_stop_fill.pine`
  plus `tests/snapshots/runtime_strategy_exit_bracket_stop_limit_stop_fill.json`
  for a price bracket whose downside stop leg fills on a later bar.
- `tests/fixtures/runtime/strategy_exit_bracket_profit_loss_profit_fill.pine`
  plus `tests/snapshots/runtime_strategy_exit_bracket_profit_loss_profit_fill.json`
  for tick conversion and later upside profit fill.
- `tests/fixtures/runtime/strategy_exit_bracket_profit_loss_loss_fill.pine`
  plus `tests/fixtures/runtime/strategy_exit_bracket_profit_loss_loss_bars.csv`
  and `tests/snapshots/runtime_strategy_exit_bracket_profit_loss_loss_fill.json`
  for tick conversion and later downside loss fill.
- `tests/fixtures/runtime/strategy_exit_bracket_mixed_pairs.pine` plus
  `tests/snapshots/runtime_strategy_exit_bracket_mixed_pairs.json` for
  `stop + profit` and `loss + limit` acceptance.

Runtime lifecycle fixtures:

- `tests/fixtures/runtime/strategy_exit_bracket_creation_bar.pine` for
  creation-bar ineligibility when both legs would otherwise be touched.
- `tests/fixtures/runtime/strategy_exit_bracket_repeated.pine` for unchanged
  repeated brackets preserving the original eligibility bar.
- `tests/fixtures/runtime/strategy_exit_bracket_replacement.pine` for changed
  leg price resetting eligibility, single-trigger to bracket replacement, and
  bracket to single-trigger replacement.
- `tests/fixtures/runtime/strategy_exit_bracket_invalid_leg.pine` for invalid
  price/tick diagnostics rejecting the whole bracket while leaving an existing
  pending exit unchanged.

Same-bar both-hit fixture:

- `tests/fixtures/runtime/strategy_exit_bracket_both_hit.pine` plus
  `tests/fixtures/runtime/strategy_exit_bracket_both_hit_bars.csv` and
  `tests/snapshots/runtime_strategy_exit_bracket_both_hit.json`.
- The CSV should contain a small OHLC series where a later eligible bar touches
  both the downside and upside legs; the snapshot must prove the selected
  stop/loss-first fill price and one-order/one-trade output.

State-timing fixtures:

- `tests/fixtures/runtime/strategy_exit_bracket_state.pine` plus
  `tests/snapshots/runtime_strategy_exit_bracket_state.json`.
- The fixture must plot or otherwise expose `strategy.position_size`,
  `strategy.position_avg_price`, `strategy.openprofit`, `strategy.netprofit`,
  `strategy.equity`, `strategy.closedtrades`, and `strategy.opentrades` before
  fill, on the triggering bar, and on the next bar.

Interaction fixtures:

- `tests/fixtures/runtime/strategy_exit_bracket_interactions.pine` plus
  `tests/snapshots/runtime_strategy_exit_bracket_interactions.json`.
- Include branch, switch, for, while, pure UDF argument, and constant history
  reference contexts only if the future support claim says brackets can appear
  in the same expression/statement contexts as current single-trigger exits.

Incremental coverage:

- Add every new runtime fixture that mutates broker state to
  `crates/pine-runtime/tests/incremental.rs`.
- If a fixture needs non-default OHLC data, add a dedicated CSV and route it
  through the existing per-fixture bars mapping.

Host and snapshot coverage:

- Add CLI golden snapshot entries in `crates/pine-cli/src/main.rs` for every
  new runtime fixture and refresh only the bracket-related runtime snapshots.
- Add WASM smoke tests for representative `stop + limit`, `profit + loss`, and
  same-bar both-hit contracts.
- Add Python binding smoke tests for representative `stop + limit` and
  `profit + loss` dictionary contracts.
- Keep the public strategy object shape unchanged in all host tests:
  `orders`, `trades`, `position`, `equity`, and `diagnostics` only.

Conformance and docs:

- Only after semantic, runtime, incremental, CLI, WASM, and Python evidence is
  in place may a future phase update `tests/fixtures/conformance.tsv`.
- The `strategy.exit` row may stay `partial`; its notes should name the exact
  bracket pairs accepted.
- The `strategy.*` row should continue to list same-side pairs, three/four
  triggers, trailing, partial, missing-entry, and richer broker behavior as
  unsupported.

## Slice 4 Future Implementation Blueprint

Phase Q does not apply this blueprint. It records the module ownership and test
order a later positive bracket implementation should follow.

Semantic analysis:

- Update `crates/pine-sema/src/analyzer/strategy.rs`.
- Accept exactly the selected one-downside plus one-upside pairs:
  `stop + limit`, `stop + profit`, `loss + limit`, and `loss + profit`.
- Keep `stop + loss`, `limit + profit`, three-trigger calls, four-trigger
  calls, trailing arguments, partial quantity arguments, and missing-entry
  variants diagnostic-only unsupported unless a later phase explicitly widens
  them.
- Keep strategy-mode gating, requested-context rejection, UDF side-effect
  rejection, and diagnostic code stability unchanged.

Built-in signatures:

- `crates/pine-builtins/src/namespaces/strategy.rs` already exposes optional
  `stop`, `limit`, `profit`, and `loss` parameters for `strategy.exit`.
- A first bracket implementation should not add new built-in parameters.
- Pair acceptance should remain analyzer-owned, not signature-owned.

Runtime call extraction:

- Update `crates/pine-runtime/src/builtins/strategy.rs`.
- Continue evaluating `id` and `from_entry` before trigger legs.
- For supported bracket pairs, evaluate only the selected legs in the canonical
  order from the decision record: downside then upside.
- Convert `profit` and `loss` through the existing fixed
  `syminfo.mintick` source before broker placement.
- Dispatch through broker facade methods such as a future
  `place_exit_bracket(...)`; do not expose broker internals to runtime built-in
  extraction.
- If bracket validation fails, preserve any existing pending exit and avoid
  falling back to a single-trigger placement.

Broker pending-exit placement:

- Update `crates/pine-runtime/src/strategy/broker/exits.rs`.
- Prefer a trigger model equivalent to:

  ```text
  PendingExitTrigger =
      Single(ExitLeg)
    | Bracket { downside: ExitLeg, upside: ExitLeg }
  ```

- `ExitLeg` should preserve the resolved trigger side and fill price after any
  tick conversion. It should not preserve public-only exit-reason metadata in
  the first subset.
- Identity comparison should include exit `id`, `from_entry`, trigger kind,
  leg sides, and resolved leg prices.
- Reuse existing runtime diagnostic codes where possible:
  `E_STRATEGY_EXIT_PRICE`, `E_STRATEGY_EXIT_TICKS`,
  `E_STRATEGY_EXIT_MINTICK`, and `E_STRATEGY_EXIT_ENTRY`.
- Add new diagnostic codes only if an implementation exposes a genuinely new
  runtime error family; otherwise keep diagnostics stable.

Pending-exit evaluation:

- Update `crates/pine-runtime/src/strategy/broker/mod.rs`.
- Preserve `last_update_bar_index >= bar_index` creation/replacement-bar
  ineligibility.
- Evaluate pending brackets after script statements, matching existing
  pending-exit timing.
- For eligible brackets, check downside and upside leg triggers against the
  current bar and apply stop/loss-first precedence when both sides are touched.
- Keep stale or mismatched pending exits cleared under the existing current
  entry check.

Fill construction:

- Update `crates/pine-runtime/src/strategy/broker/fills.rs`.
- Reuse the current one-fill path for bracket fills: one `StrategyOrderEvent`
  with `direction: "strategy.exit"`, one `StrategyTrade`, full current long
  quantity, cash update, flat position snapshot, and pending-exit clear.
- The selected fill price should come from the leg chosen by trigger evaluation.
- Do not add partial-fill, pending-order, or exit-reason output fields in the
  first subset.

Accounting and public output:

- `crates/pine-runtime/src/strategy/broker/accounting.rs` should continue to
  derive position, open profit, realized profit, equity, and trade counts from
  broker state after fills.
- `crates/pine-runtime/src/output/strategy.rs` should not change for the first
  bracket subset.
- CLI, Python, and WASM should keep consuming the shared runtime result shape
  without host-specific bracket logic.

Implementation test order:

1. Semantic acceptance/rejection fixtures and `cargo test -p pine-sema strategy`.
2. Broker unit tests for bracket placement, identity, invalid-leg handling,
   replacement, and same-bar precedence.
3. Runtime fixtures plus CLI golden snapshots for normal fills, lifecycle,
   both-hit, state timing, and interactions.
4. Incremental append coverage for every broker-mutating runtime fixture.
5. WASM and Python smoke tests for representative public contracts.
6. Conformance metadata, matrix snapshot, docs, release notes, and closeout
   audit updates.
7. Full release gate before claiming the future bracket phase complete.

## Slice 5 Scope Guard And Tail Ranking

Bracket design is the next small strategy maintenance target because:

- The unsupported boundary already has semantic fixtures for common combined
  trigger forms, plus the four-trigger fixture added in Phase Q.
- Phase P isolated pending-exit placement in `broker/exits.rs` and pending-exit
  evaluation in `broker/mod.rs`, so bracket design maps cleanly to existing
  ownership.
- A first design gate and future first bracket subset can preserve the current
  public strategy output shape; no pending-order, partial-fill, exit-reason, or
  schema review is needed up front.
- Same-bar high/low precedence and bracket identity were the main unresolved
  blockers before any honest positive bracket claim could be made.

Deferred strategy reporting tails:

- Strategy closed-trade and open-trade namespace functions remain deferred
  until a separate reporting design defines function names, return types,
  indexing semantics, history behavior, and unsupported contexts.
- Rich metrics such as max drawdown, win trades, loss trades, runup, and
  detailed per-trade helpers remain deferred because they need richer trade and
  equity history semantics than the current count-only subset.
- Public open-trade records remain deferred because Phase O intentionally kept
  open-trade data as script-visible counts, not public result objects.

Deferred public schema tails:

- Public pending-order records, partial-fill fields, exit-reason fields, and
  bracket-leg metadata remain deferred until a separate schema review.
- The first future bracket subset should keep bracket fills explainable through
  existing order price and trade profit fields.

Deferred broker lifecycle tails:

- Missing-entry pre-placement remains deferred because it requires pending
  exits without a current position, changes entry/exit lifecycle ordering, and
  may require stronger order identity or multiple pending exits.
- Partial exits, `qty`, `qty_percent`, and reservation behavior remain
  deferred because they require quantity reservation, remaining-position
  accounting, and partial trade semantics.
- Multiple active pending exits remain deferred until multiple entries,
  partial exits, or public pending-order reporting are deliberately opened.
- Trailing stops remain deferred because they require per-bar trigger movement,
  ratcheting rules, and additional lifecycle fixtures beyond fixed bracket
  legs.

Deferred larger broker phases:

- Short entries, reversals, pyramiding, multiple simultaneous entries, and
  `strategy.order` remain larger broker phases because they change the
  one-net-long position model.
- Commission, slippage, margin, currency conversion, cash sizing, contracts,
  and percent-of-equity sizing remain deferred because they affect fills,
  accounting, and strategy settings together.
- Strategy alerts and realtime broker rollback remain deferred because they
  cross strategy execution with host alert delivery or forming-bar rollback
  semantics.

Roadmap priority after Slice 5:

1. Finish Phase Q as the design gate and close it with audit evidence.
2. If the design remains stable, use a future small behavior phase for the
   fixture-backed bracket subset selected here.
3. If bracket implementation is paused, limit strategy work to diagnostic-only
   maintenance or a separately scoped reporting/broker tail.
4. Do not select missing-entry pre-placement, partial exits, pyramiding, short
   exposure, rich metrics, or realtime strategy execution as incidental work
   inside the bracket path.

## Slice 6 Documentation Synchronization

Slice 6 kept compatibility claims conservative:

- `docs/LONG_TERM_EXECUTION_PLAN.md` already tracks Phase Q as planned.
- `docs/CONFORMANCE.md` now points to the Phase P structural audit and Phase Q
  bracket design gate without claiming combined-trigger support.
- `docs/SEMANTIC_MODEL.md` clarifies that combined trigger forms remain
  diagnostic-only unsupported and that diagnostics should use current-subset
  wording.
- `docs/EXECUTION_SEMANTICS.md` clarifies that Phase Q records future bracket
  design while current runtime behavior remains single-trigger only.
- `docs/ARCHITECTURE.md` records that the future bracket blueprint stays within
  existing broker ownership boundaries and does not move behavior into host
  bindings or public output structs.
- `docs/RELEASE_NOTES.md` records the Phase Q design gate and Slice 1
  diagnostic hardening/conformance metadata update.

## Phase Q Closeout

Phase Q did not widen positive strategy compatibility.

- `tests/fixtures/conformance.tsv` status values were not widened.
- `strategy.exit` remains executable only for stop-only, limit-only,
  profit-only, or loss-only full-position exits on the current one-net-long
  broker.
- Combined trigger runtime behavior remains unsupported in Phase Q.
- Public runtime output remains `schemaVersion: 3`.
- `StrategyResult`, `StrategyOrderEvent`, `StrategyTrade`,
  `StrategyPositionSnapshot`, and `StrategyEquitySnapshot` shapes did not
  change.
- CLI JSON, Python dictionaries, and WASM JSON output contracts did not change.
- No runtime snapshots were refreshed during Phase Q.

Fixture evidence:

- Existing combined-trigger unsupported fixtures remain referenced from
  `tests/fixtures/conformance.tsv`.
- Phase Q added one diagnostic-only fixture:
  `tests/fixtures/sema/unsupported_strategy_exit_four_triggers.pine`.
- `tests/snapshots/matrix.json` changed only to reflect the new conformance
  metadata fixture reference.

Final bracket decision record:

- A future first positive bracket subset should accept exactly one downside leg
  plus one upside leg for the current long-only broker.
- Future supported pairs are `stop + limit`, `stop + profit`, `loss + limit`,
  and `loss + profit`.
- Same-side pairs `stop + loss` and `limit + profit`, plus three-trigger and
  four-trigger calls, remain unsupported for the first future subset.
- Profit/loss tick distances convert once at placement time using the fixed
  default `syminfo.mintick` source.
- Invalid bracket legs reject the whole bracket and leave any existing pending
  exit unchanged.
- Bracket identity includes exit id, `from_entry`, leg kinds, sides, and
  resolved prices; unchanged repeated calls preserve eligibility, while changed
  brackets or single/bracket replacements reset eligibility.
- Same-bar both-hit behavior uses deterministic stop/loss-first precedence for
  the first future long-only subset.
- Future bracket fills use the existing one-order/one-trade public output
  shape, without pending-order records, bracket-leg metadata, or exit-reason
  fields.

Next recommended strategy maintenance target:

- If strategy work continues, open a small positive bracket implementation
  phase using this audit as the baseline.
- Keep missing-entry pre-placement, partial exits, multiple pending exits,
  pyramiding, short exposure, rich metrics, public pending-order records, and
  realtime broker rollback deferred until separate phases.

## Verification

Slice 0 verification:

```text
cargo test -p pine-sema strategy
cargo test -p pine-runtime strategy::broker
git diff --check
```

All Slice 0 verification commands passed on the Slice 0 workspace.

Slice 1 verification:

```text
cargo fmt --check
cargo test -p pine-sema strategy
cargo test -p pine-cli conformance_metadata_references_existing_fixtures
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli matrix_output_matches_golden_snapshot
cargo test -p pine-cli matrix_output_matches_golden_snapshot
git diff --check
```

All Slice 1 verification commands passed on the Slice 1 workspace.

Slice 2 verification:

```text
git diff --check
```

Slice 2 verification passed on the Slice 2 workspace.

Slice 3 verification:

```text
git diff --check
```

Slice 3 verification passed on the Slice 3 workspace.

Slice 4 verification:

```text
git diff --check
```

Slice 4 verification passed on the Slice 4 workspace.

Slice 5 verification:

```text
git diff --check
```

Slice 5 verification passed on the Slice 5 workspace.

Slice 6 verification:

```text
cargo test -p pine-cli conformance_metadata_references_existing_fixtures
cargo test -p pine-cli matrix_output_matches_golden_snapshot
git diff --check
```

Slice 6 verification passed on the Slice 6 workspace.

Closeout verification:

```text
git diff --check
scripts/verify.sh
```

Closeout verification passed on the Phase Q closeout workspace. The release
gate covered `cargo fmt --check`, `cargo clippy --workspace --all-targets -- -D
warnings`, `cargo test --workspace`, `python3 scripts/check_structure.py`,
`cargo check -p pine-wasm --target wasm32-unknown-unknown`, `maturin build`,
wheel reinstall, and `python3 -m pytest python/tests`.
