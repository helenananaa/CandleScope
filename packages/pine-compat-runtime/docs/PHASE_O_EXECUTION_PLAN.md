# Phase O Strategy Reporting Counts Execution Plan

Status: closed for the current fixture-backed strategy reporting count subset.
Use `docs/PHASE_N_AUDIT.md` as the baseline closeout record for the prior
strategy-exit subset and `docs/PHASE_O_AUDIT.md` as the closeout record for
this phase.

Phase O should add the first narrow strategy reporting variables without
opening a larger broker-simulation phase. The executable target is
`strategy.closedtrades` and `strategy.opentrades` as read-only strategy-mode
count series. This closes a useful reporting gap while reusing the existing
long-only broker state, `StrategyTrade` records, and public strategy output
contract.

Each slice should leave the workspace shippable and should keep semantic
claims, runtime behavior, fixtures, snapshots, host behavior, conformance
metadata, and docs in lockstep.

## Current Starting Point

The repository has closed Phase G, Phase L, Phase M, and Phase N for the
current strategy subset:

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
- Phase N added `strategy.exit(id, from_entry, profit=ticks)` and
  `strategy.exit(id, from_entry, loss=ticks)` by converting positive tick
  distances through the fixed default `syminfo.mintick` subset.
- Stop/loss exits fill on a later historical bar when `low <= exit_price`.
  Limit/profit exits fill on a later historical bar when `high >= exit_price`.
- Pending exits are evaluated after the script statements for the current
  historical bar. A fill created by pending-exit evaluation is therefore
  visible to strategy output and equity for that bar, but normal script reads
  of strategy variables observe it on the next bar.
- Filled exits append the existing public `strategy.orders`, `strategy.trades`,
  `strategy.position`, and `strategy.equity` data. Phase N did not add a public
  pending-order field or bump the runtime schema.
- At the Phase O starting point,
  `tests/fixtures/sema/unsupported_strategy_state_variables.pine` kept
  `strategy.closedtrades`, `strategy.opentrades`, and `strategy.max_drawdown`
  unsupported.

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

## Phase O Goal

The main goal is to support a narrow, deterministic pair of read-only strategy
reporting counts:

- `strategy.closedtrades` returns the number of closed trades recorded by the
  current broker state.
- `strategy.opentrades` returns the number of open trades represented by the
  current long-only broker state.

These variables should behave like the existing Phase L strategy state
variables:

- strategy-mode only.
- read-only.
- available as historical series values.
- usable in supported expressions, branches, switches, loops, pure UDF
  arguments, and constant history references.
- rejected in indicator scripts and requested-context expressions.
- rejected when directly assigned or otherwise treated as mutable strategy
  state.

Phase O should not add a new public strategy output field. The public
`strategy.trades` array already exposes closed-trade records, and the current
runtime has no public open-trade object model. The count variables are script
state only.

## Semantics Decision Record

Confirm these decisions in Slice 0 before changing compatibility metadata:

- `strategy.closedtrades` is a `series int` value.
- `strategy.opentrades` is a `series int` value.
- In the current long-only no-pyramiding broker, `strategy.opentrades` is `1`
  when a supported long position is open and `0` when flat.
- `strategy.closedtrades` is the length of the broker's closed-trade list.
- `strategy.close(id)` mutates broker state immediately. Reads after a
  supported `strategy.close(id)` call on the same bar see the updated
  `closedtrades` and `opentrades` counts.
- `strategy.exit(...)` pending fills are evaluated after all script statements
  on the bar. Reads during the triggering bar still see the pre-fill counts;
  reads on the next bar see the updated counts.
- A same-bar pending exit created or replaced on the current bar remains
  ineligible, matching Phase M/N.
- Missing or mismatched `strategy.close` calls stay no-op and do not change
  either count.
- Missing or mismatched `strategy.exit` calls continue to produce the existing
  runtime diagnostics and do not change either count.
- The count variables do not expose trade details. Functions and namespaces
  such as `strategy.closedtrades.profit(...)`,
  `strategy.closedtrades.entry_price(...)`, or
  `strategy.opentrades.entry_price(...)` remain unsupported.
- `strategy.max_drawdown`, `strategy.wintrades`, `strategy.losstrades`, rich
  metrics, broker settings, and reporting helper namespaces remain
  unsupported.

## Non-Goals

Do not include these in the Phase O compatibility claim:

- Strategy closed-trade or open-trade namespace functions.
- Public open-trade records.
- Public pending-order records.
- Public output schema changes or a schema version bump.
- Exit-reason fields or partial-fill fields.
- Combined trigger brackets and same-bar high/low precedence.
- Trailing stops.
- Partial exits and quantity reservation behavior.
- Missing-entry pre-placement and multiple pending exits.
- Short entries, reversals, and short exposure.
- Multiple simultaneous entries and pyramiding.
- `strategy.order` and richer order modification semantics.
- Commission, slippage, margin, currency conversion, cash sizing, contracts,
  and percent-of-equity sizing.
- Strategy alerts and alert placeholders.
- Realtime strategy execution and forming-bar broker rollback.
- Host-specific broker APIs or chart UI behavior outside the public runtime
  contract.

## Rules for Every Slice

- Add fixtures before or alongside behavior changes.
- Keep the compatibility matrix conservative. Do not widen a strategy row
  unless the exact supported form has semantic fixtures, runtime fixtures,
  host coverage, conformance metadata, docs, and verification evidence.
- Preserve indicator behavior. Indicator scripts must not gain broker state,
  strategy output fields, or strategy-mode-only order functions.
- Keep strategy order calls rejected in UDFs under the existing side-effect
  policy. Phase O variables may be passed to pure UDFs as values, matching the
  existing strategy state variable subset.
- Keep strategy state and order calls rejected in requested-context
  expressions. The request provider context remains isolated and data-only.
- Treat the broker as deterministic runtime state. Core crates must not depend
  on account services, wall-clock time, host callbacks, filesystem data, or
  network data.
- Keep all count timing rules explicit. Do not silently change pending-exit
  evaluation ordering to make count variables easier to implement.
- Reuse the existing public strategy output contract. Adding public
  open-trade, pending-order, or metric fields requires schema review, snapshot
  refreshes, CLI/Python/WASM contract updates, and release notes.
- Keep CLI, Python, and WASM behavior synchronized. A script that compiles and
  runs through one public host should produce equivalent runtime JSON or native
  dictionary data through the others.
- Keep docs and conformance metadata in the same change as behavior. No code
  slice should leave a feature implemented but unclaimed, or claimed without
  fixture coverage.
- Run the full release verification gate before closing Phase O.

## Internal Structure Rules

Phase O should stay smaller than a broker redesign.

- Keep `pine-builtins` responsible for built-in series value typing. It should
  not own broker semantics.
- Keep `pine-sema::analyzer::strategy` responsible for strategy-mode gating,
  unsupported strategy reporting variants, and read-only strategy state policy.
- Keep `pine-runtime::strategy` responsible for broker state accessors and the
  source of truth for counts.
- Keep `pine-runtime::builtins::variables` responsible for evaluating the
  accepted strategy reporting variables at runtime.
- Keep `pine-runtime::output::strategy` unchanged unless a later phase
  deliberately adds public reporting output. Phase O should not need it.
- Keep Python and WASM bindings thin. They should not duplicate broker count
  logic.
- `crates/pine-runtime/src/strategy/broker.rs` is close to the existing
  review trigger. Adding tiny accessors is acceptable; adding another order
  family, trigger rule, or accounting path should first split strategy runtime
  modules.

## Intended Module Layout

Use existing crate boundaries. A new crate is not needed for Phase O.

Recommended layout:

```text
crates/pine-builtins/src/
   constants/series.rs         add series int value types for the two counts

crates/pine-sema/src/analyzer/
   strategy.rs                 strategy-mode gating and supported state list
   unsupported.rs              unsupported strategy reporting reasons if needed

crates/pine-runtime/src/
   strategy/
      broker.rs                count accessors only; no new order lifecycle
   builtins/
      variables.rs             runtime evaluation for count variables
   output/
      strategy.rs              no Phase O changes expected
      json.rs                  no Phase O changes expected

crates/pine-cli/src/
   main.rs                     snapshot list only if a new runtime fixture is added

crates/pine-python/src/
   lib.rs                      no Phase O changes expected unless host smoke tests need helpers

crates/pine-wasm/src/
   tests/                      representative host assertion if needed
```

Ownership notes:

- Count values should be derived from broker state, not from public JSON.
- `strategy.closedtrades` should not count order events. It counts closed
  trades only.
- `strategy.opentrades` should not infer from `strategy.position` snapshots. It
  should read the live broker position/open-entry state.
- Runtime output arrays are evidence of broker behavior after it happens. They
  should not drive broker decisions or variable reads.

## Slice 0: Baseline Lock and Design Confirmation

Goal: lock the Phase N baseline and confirm the exact Phase O count semantics
before positive support is claimed.

Steps:

1. Review the Phase N closeout boundary in `docs/PHASE_N_AUDIT.md`.
2. Review strategy rows in `tests/fixtures/conformance.tsv`.
3. Review existing unsupported reporting fixture:
   `tests/fixtures/sema/unsupported_strategy_state_variables.pine`.
4. Review `crates/pine-runtime/src/runtime/historical.rs` to confirm pending
   exits are evaluated after script statements.
5. Review `tests/fixtures/runtime/strategy_exit_interactions.pine` and its
   snapshot to confirm current strategy variable timing around pending exits.
6. Confirm the Phase O decision record in this document.
7. Do not change conformance metadata in this slice unless fixtures already
   exist in the same change.

Acceptance criteria:

- The team agrees that Phase O supports only the two count variables.
- The timing distinction between immediate `strategy.close` and post-statement
  pending-exit fills is documented.
- Existing unsupported forms remain explicit.
- No public runtime schema change is expected.

Slice 0 confirmation:

- `docs/PHASE_N_AUDIT.md` closes Phase N for the fixture-backed profit/loss
  `strategy.exit` subset and keeps reporting namespaces unsupported.
- `tests/fixtures/conformance.tsv` keeps `strategy.*` unsupported beyond the
  supported order functions and position/profit/equity variables.
- At Slice 0,
  `tests/fixtures/sema/unsupported_strategy_state_variables.pine` still rejected
  `strategy.closedtrades`, `strategy.opentrades`, and `strategy.max_drawdown`.
- `crates/pine-runtime/src/runtime/historical.rs` evaluates pending exits after
  script statements, matching the count timing decision.
- `tests/fixtures/runtime/strategy_exit_interactions.pine` and its snapshot
  show script reads before the delayed exit fill while strategy output and
  equity include the fill on that bar.

Suggested verification:

```text
cargo test -p pine-sema strategy
cargo test -p pine-runtime strategy
```

## Slice 1: Semantic and Type Staging

Goal: make the analyzer and built-in type registry recognize the two count
variables while keeping unsupported reporting helpers diagnostic-only.

Steps:

1. Add `strategy.closedtrades` and `strategy.opentrades` to the supported
   strategy state variable list in `crates/pine-sema/src/analyzer/strategy.rs`.
2. Keep indicator-mode usage rejected through the existing `E_STRATEGY_MODE`
   strategy-state path.
3. Keep requested-context usage rejected through the existing request-provider
   unsupported strategy-state path.
4. Keep direct mutation rejected through the existing read-only strategy state
   policy.
5. Add both variables to `crates/pine-builtins/src/constants/series.rs` as
   `PineType::new(Qualifier::Series, ValueKind::Int)`.
6. Add a positive semantic fixture such as
   `tests/fixtures/sema/supported_strategy_trade_counts.pine`:

   ```pine
   //@version=5
   strategy("Trade counts")
   plot(strategy.closedtrades)
   plot(strategy.opentrades)
   ```

7. Add an interaction semantic fixture such as
   `tests/fixtures/sema/supported_strategy_trade_count_interactions.pine` that
   uses the counts in branches, switches, loops, pure UDF arguments, and
   constant history references.
8. Update `crates/pine-sema/tests/fixtures.rs` so the new fixtures assert
   support for both variables.
9. Split or update `tests/fixtures/sema/unsupported_strategy_state_variables.pine`
   so it continues to cover still-unsupported reporting state, especially
   `strategy.max_drawdown`, without expecting `strategy.closedtrades` or
   `strategy.opentrades` to remain unsupported.
10. Update indicator and request negative fixtures to include the new count
    variables, or add dedicated fixtures if that keeps diagnostics easier to
    inspect.

Acceptance criteria:

- Strategy-mode scripts can analyze the two variables without diagnostics.
- Indicator-mode scripts report stable `E_STRATEGY_MODE` diagnostics for the
  two variables.
- Requested-context usage remains unsupported.
- `strategy.max_drawdown` and rich reporting helpers remain unsupported.
- The HIR lowers the variables as ordinary read-only series int values.

Suggested verification:

```text
cargo test -p pine-builtins strategy
cargo test -p pine-sema strategy
```

## Slice 2: Broker Count Accessors

Goal: expose minimal broker-owned accessors for the count variables without
changing broker behavior.

Steps:

1. Add `closed_trade_count(&self) -> i64` or an equivalent integer accessor to
   `crates/pine-runtime/src/strategy/broker.rs`. It should return
   `self.trades.len()` converted through the existing runtime integer type.
2. Add `open_trade_count(&self) -> i64` or an equivalent integer accessor. In
   the current broker, it should return `1` when `position_size > 0.0` and the
   entry identity is present, otherwise `0`.
3. Add focused broker unit tests near the existing strategy broker tests:
   - flat broker starts with `0` closed and `0` open trades.
   - `entry_long` changes open count to `1` and keeps closed count `0`.
   - repeated entries under no-pyramiding keep open count `1`.
   - `close_long` changes open count to `0` and closed count to `1`.
   - a filled pending exit changes open count to `0` and closed count to `1`.
   - mismatched close and mismatched exit do not change either count.
4. Do not add public output fields.
5. Do not refactor broker order lifecycle unless a test exposes a real problem.

Acceptance criteria:

- Counts are broker-owned and deterministic.
- Existing strategy entry, close, exit, equity, and diagnostics tests still
  pass unchanged unless expectations deliberately add count assertions.
- No public JSON/Python/WASM output shape changes occur in this slice.

Suggested verification:

```text
cargo test -p pine-runtime strategy
```

## Slice 3: Runtime Variable Evaluation

Goal: route runtime reads of the two variables through the broker accessors.

Steps:

1. Update `crates/pine-runtime/src/builtins/variables.rs`:
   - `strategy.closedtrades` returns `PineValue::Int(broker.closed_trade_count())`.
   - `strategy.opentrades` returns `PineValue::Int(broker.open_trade_count())`.
2. Keep existing runtime behavior for the Phase L variables unchanged.
3. Add runtime unit tests in `crates/pine-runtime/src/tests/strategy.rs`:
   - count variables start at zero.
   - reads after `strategy.entry` on the same bar show open count `1`.
   - reads after `strategy.close` on the same bar show closed count `1` and
     open count `0`.
   - pending exit fills are visible to reads on the next bar, matching
     `strategy.netprofit` timing.
   - constant history references work, for example
     `strategy.closedtrades[1]` and `strategy.opentrades[1]`.
4. If the plot pipeline serializes integer values as numbers, keep snapshot
   expectations numeric and do not coerce counts to float unless the type
   system requires it.

Acceptance criteria:

- Runtime reads return integer count values.
- Same-bar `strategy.close` behavior is immediate.
- Pending-exit behavior matches the current post-statement fill model.
- Existing strategy state variables continue to behave unchanged.

Suggested verification:

```text
cargo test -p pine-runtime strategy
```

## Slice 4: Runtime Fixtures, Snapshots, and Incremental Coverage

Goal: prove the count variables through fixture-backed historical and
incremental execution.

Steps:

1. Add a runtime fixture such as
   `tests/fixtures/runtime/strategy_trade_counts.pine` covering:
   - initial flat counts.
   - open count after entry.
   - closed count after `strategy.close`.
   - repeated close no-op.
   - history references for both counts.
2. Add a second runtime fixture such as
   `tests/fixtures/runtime/strategy_exit_trade_counts.pine` covering:
   - entry on one bar.
   - supported stop/limit or profit/loss pending exit placement.
   - pre-fill count reads on the triggering bar.
   - next-bar count reads after pending-exit evaluation.
3. Prefer reusing existing simple OHLC fixture bars unless a custom CSV is
   needed for exact high/low trigger timing.
4. Add golden snapshots for the new runtime fixtures through the existing CLI
   snapshot harness.
5. Update the incremental fixture test list if it enumerates runtime fixtures
   explicitly. The new count fixtures must pass full historical and
   incremental append execution with identical outputs.
6. Keep public `strategy` output unchanged except for existing arrays that
   naturally show the entry/close/exit behavior in the fixture.

Acceptance criteria:

- Runtime snapshots prove both variables in normal close and pending-exit
  scenarios.
- Incremental append execution matches full historical execution.
- No new public strategy output keys are introduced.

Suggested verification:

```text
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-runtime --test incremental
cargo test -p pine-runtime strategy
```

## Slice 5: Public Host Contract Smoke Coverage

Goal: ensure CLI, Python, and WASM remain synchronized even though Phase O does
not change the public strategy output schema.

Steps:

1. Add or extend a CLI strategy snapshot entry for the representative count
   fixture.
2. Add a WASM test that runs a small strategy script with the two plots and
   asserts the JSON contains expected plot values and the unchanged strategy
   object shape.
3. Add a Python binding test only if the existing Python strategy tests do not
   already cover the new representative fixture path. The assertion should
   focus on plot values and unchanged strategy dictionary keys.
4. Do not add Python or WASM broker math. Both hosts should consume the shared
   runtime result only.
5. If `crates/pine-python` or linked Rust crates change in this slice, rebuild
   and reinstall the wheel before running Python tests:

   ```text
   maturin build --manifest-path crates/pine-python/Cargo.toml --out dist
   python3 -m pip install --force-reinstall dist/*.whl
   python3 -m pytest python/tests
   ```

Acceptance criteria:

- CLI snapshots, WASM JSON, and Python dictionaries agree on plot values.
- Public `strategy` output keys remain `orders`, `trades`, `position`,
  `equity`, and `diagnostics`.
- `PUBLIC_RUNTIME_SCHEMA_VERSION` remains unchanged unless an unexpected public
  output shape change is deliberately approved.

Suggested verification:

```text
cargo test -p pine-cli strategy
cargo test -p pine-wasm strategy
python3 -m pytest python/tests
```

## Slice 6: Conformance, Docs, and Release Notes

Goal: claim exactly the fixture-backed Phase O surface and synchronize user
documentation.

Steps:

1. Update `tests/fixtures/conformance.tsv`:
   - Add `strategy.closedtrades` as `partial` with notes describing the
     current count-only closed-trade subset.
   - Add `strategy.opentrades` as `partial` with notes describing the current
     long-only `0` or `1` open-trade subset.
   - Update the `strategy` row to mention the two count variables if needed.
   - Update the `strategy.*` row so rich trade namespaces and metrics remain
     unsupported.
2. Update `docs/SEMANTIC_MODEL.md` with type, strategy-mode, and unsupported
   namespace boundaries.
3. Update `docs/EXECUTION_SEMANTICS.md` with runtime count timing:
   - `strategy.close` is immediate for subsequent reads.
   - pending-exit fills are visible to script reads on the next bar.
4. Update `docs/CONFORMANCE.md` or generated matrix documentation if it is
   manually maintained.
5. Update `docs/RELEASE_NOTES.md` with a short compatibility note.
6. Update `docs/LONG_TERM_EXECUTION_PLAN.md` after the implementation lands:
   - mark Phase O closed when the audit exists.
   - keep rich reporting namespaces, brackets, partial exits, pyramiding, and
     realtime strategy execution out of scope.
7. If matrix snapshots are generated by CLI tests, refresh only the affected
   snapshots:

   ```text
   UPDATE_SNAPSHOTS=1 cargo test -p pine-cli matrix_output_matches_golden_snapshot
   ```

Acceptance criteria:

- The conformance matrix claims only the count variables, not rich namespaces.
- Docs match semantic and runtime behavior.
- Release notes describe the useful surface and the explicit unsupported
  boundaries.
- Snapshot changes are limited to intentional conformance/runtime evidence.

Suggested verification:

```text
cargo test -p pine-cli matrix_output_matches_golden_snapshot
cargo test -p pine-sema strategy
cargo test -p pine-runtime strategy
git diff --check
```

## Slice 7: Closeout Audit

Goal: close Phase O with a concise audit once all fixture-backed claims are in
place.

Steps:

1. Create `docs/PHASE_O_AUDIT.md`.
2. Record completed slices.
3. Record the supported surface:
   - `strategy.closedtrades` count only.
   - `strategy.opentrades` count only.
   - strategy-mode historical scripts only.
   - current long-only no-pyramiding broker only.
4. Record unsupported variants:
   - trade namespace functions.
   - rich metrics.
   - public open-trade records.
   - richer broker behavior from Phase N maintenance tails.
5. Record public output behavior and schema-version decision.
6. Record fixture evidence:
   - semantic fixtures.
   - runtime fixtures and snapshots.
   - host tests.
   - incremental tests.
7. Record verification commands and results.
8. Update `docs/LONG_TERM_EXECUTION_PLAN.md` to mark Phase O closed and choose
   the next recommended maintenance target.

Acceptance criteria:

- The audit can be used as the baseline for the next strategy maintenance
  slice.
- The repository has a clear source of truth for the Phase O compatibility
  claim.
- Full release verification passes.

Closeout verification:

```text
git diff --check
scripts/verify.sh
```

## Suggested Commit Order

1. `Document strategy reporting count plan`
2. `Stage strategy trade count semantics`
3. `Expose broker trade count variables`
4. `Cover strategy trade counts in fixtures`
5. `Synchronize trade count host contracts`
6. `Document strategy trade count compatibility`
7. `Close strategy reporting count audit`

## Phase O Completion Checklist

- [x] Slice 0 decision record confirmed.
- [x] `strategy.closedtrades` is typed as `series int`.
- [x] `strategy.opentrades` is typed as `series int`.
- [x] Strategy-mode semantic fixtures accept both count variables.
- [x] Indicator-mode diagnostics reject both count variables.
- [x] Requested-context diagnostics reject both count variables.
- [x] Mutation diagnostics keep strategy state read-only.
- [x] Broker accessors return deterministic closed/open counts.
- [x] Runtime variable reads use broker accessors.
- [x] Same-bar `strategy.close` count behavior is covered.
- [x] Pending-exit next-bar count behavior is covered.
- [x] Constant history references are covered.
- [x] Runtime snapshots are refreshed intentionally.
- [x] Incremental append execution matches full historical execution.
- [x] CLI, Python, and WASM behavior remain synchronized.
- [x] Public strategy output schema remains unchanged, or any deliberate schema
      change is reviewed and documented.
- [x] `tests/fixtures/conformance.tsv` claims only the fixture-backed count
      subset.
- [x] Semantic, execution, release, and long-term docs are synchronized.
- [x] `docs/PHASE_O_AUDIT.md` records closeout evidence.
- [x] `git diff --check` passes.
- [x] `scripts/verify.sh` passes.
