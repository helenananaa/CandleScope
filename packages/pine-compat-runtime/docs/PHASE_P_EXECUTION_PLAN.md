# Phase P Strategy Broker Structure Execution Plan

Status: planned. Use `docs/PHASE_O_AUDIT.md` as the baseline closeout
record for the current strategy reporting count subset.

Phase P should make the strategy broker easier to maintain before any larger
broker-simulation feature is opened. The executable target is structural:
preserve the current Phase G/L/M/N/O strategy behavior exactly while splitting
the oversized broker implementation into smaller internal modules, locking
behavior with focused verification, and documenting the next safe strategy
maintenance target.

Each slice should leave the workspace shippable. Phase P should not widen the
compatibility matrix unless a later slice deliberately adds fixture-backed
behavior. The default assumption is that public JSON, Python, and WASM output
contracts remain unchanged.

## Current Starting Point

The repository has closed Phase G, Phase L, Phase M, Phase N, and Phase O for
the current strategy subset:

- `tests/fixtures/conformance.tsv` marks `strategy`, `strategy.entry`,
  `strategy.close`, strategy equity, strategy state variables,
  `strategy.closedtrades`, `strategy.opentrades`, and `strategy.exit` as
  `partial`.
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
  `strategy.openprofit`, `strategy.netprofit`, `strategy.equity`,
  `strategy.closedtrades`, and `strategy.opentrades`.
- `strategy.exit(id, from_entry, stop=price)`,
  `strategy.exit(id, from_entry, limit=price)`,
  `strategy.exit(id, from_entry, profit=ticks)`, and
  `strategy.exit(id, from_entry, loss=ticks)` are supported for one
  broker-owned pending full-position exit on the current one-net-long entry.
- Stop/loss exits fill on a later historical bar when `low <= exit_price`.
  Limit/profit exits fill on a later historical bar when `high >= exit_price`.
- New or replaced pending exits are not eligible on the same bar. Unchanged
  repeated exit calls preserve the original eligibility bar.
- Pending exits are evaluated after script statements for the current
  historical bar. Filled pending exits are visible to public strategy output
  and equity for that bar, but normal script reads of strategy variables see
  the updated state on the next bar.
- Filled exits append the existing public `strategy.orders`,
  `strategy.trades`, `strategy.position`, and `strategy.equity` data.
- Phase O did not add public strategy output fields or bump the runtime schema.
- `crates/pine-runtime/src/strategy/broker.rs` is over the practical review
  comfort line for strategy maintenance. It currently owns broker state,
  pending exit types, placement, eligibility, fills, accounting, accessors,
  public result conversion, and a large set of focused unit tests.

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

## Phase P Goal

The main goal is to create a maintainable strategy broker structure without
changing observable behavior:

- Split the broker implementation into small internal modules with clear
  ownership boundaries.
- Keep `BrokerState` as the public facade exported by `pine-runtime`.
- Keep all existing strategy semantics, runtime snapshots, conformance rows,
  Python dictionary shapes, and WASM JSON shapes unchanged.
- Preserve current runtime diagnostics and diagnostic ordering.
- Preserve the current timing rules for same-bar `strategy.close` and delayed
  pending-exit evaluation.
- Make the next strategy maintenance slice easier to review by isolating
  pending-exit placement, eligibility, fill, and accounting code.
- Record a design gate for the next strategy-exit maintenance target without
  implementing a larger broker feature in Phase P.

Phase P is successful when the broker file no longer carries every strategy
runtime responsibility, all existing behavior tests still pass, and the audit
clearly states that no compatibility claim was widened.

## Decision Record

Confirm these decisions in Slice 0 before moving code:

- Phase P is a structural maintenance phase by default.
- `BrokerState` remains the strategy runtime facade used by
  `HistoricalRuntime`, runtime built-ins, public result conversion, and tests.
- The public Rust export `pine_runtime::BrokerState` remains valid.
- `StrategyResult`, `StrategyOrderEvent`, `StrategyTrade`,
  `StrategyPositionSnapshot`, and `StrategyEquitySnapshot` shapes do not
  change.
- `PUBLIC_RUNTIME_SCHEMA_VERSION` remains unchanged.
- `strategy.exit` remains exactly stop-only, limit-only, profit-only, or
  loss-only for Phase P.
- Combined trigger brackets, trailing exits, partial exits, missing-entry
  pre-placement, multiple pending exits, short exposure, pyramiding,
  commission, slippage, margin, strategy alerts, and realtime strategy
  execution remain unsupported.
- If a mechanical split requires field visibility changes, use the narrowest
  internal visibility possible, preferably `pub(super)` inside
  `pine-runtime::strategy::broker`.
- Do not use public output structs as broker state. Output remains a projection
  of broker-owned state.
- If a slice reveals a real behavior bug, stop the structural split, add a
  regression fixture or unit test, and decide whether to fix it as a separate
  behavior slice.

## Non-Goals

Do not include these in the Phase P compatibility claim:

- Supporting combined stop/limit, profit/loss, or mixed trigger brackets.
- Defining same-bar high/low precedence for brackets.
- Supporting trailing stops.
- Supporting partial exits, `qty`, `qty_percent`, reservation behavior, or
  multiple active exit orders.
- Supporting missing-entry pre-placement.
- Supporting short entries, reversals, or pyramiding.
- Supporting `strategy.order` or richer order modification APIs.
- Adding commission, slippage, margin, currency conversion, cash sizing,
  contracts, percent-of-equity sizing, or broker setting emulation.
- Adding public open-trade records, pending-order records, partial-fill fields,
  exit-reason fields, or strategy metric output fields.
- Adding strategy alerts, alert placeholders, or host delivery APIs.
- Adding realtime strategy execution or forming-bar broker rollback.
- Renaming public output fields or bumping runtime schema versions.

## Rules for Every Slice

- Prefer behavior-preserving moves before behavior changes.
- Run focused tests after every module split.
- Keep diffs reviewable. One slice should move or extract one responsibility.
- Do not widen `tests/fixtures/conformance.tsv` during pure structural slices.
- Keep unsupported strategy variants diagnostic-only unless a future phase has
  a complete semantic, runtime, fixture, host, conformance, and docs plan.
- Preserve indicator behavior. Indicator scripts must not gain broker state or
  strategy output fields.
- Preserve requested-context isolation. Strategy order calls and strategy state
  variables remain rejected in requested expressions.
- Preserve UDF side-effect policy. Strategy order calls remain rejected inside
  UDFs.
- Keep CLI, Python, and WASM synchronized. If a runtime snapshot changes during
  Phase P, treat it as a possible regression until explained by a deliberate
  behavior slice.
- Keep docs in the same change as any decision that affects future strategy
  work.
- Run the full release verification gate before closing Phase P.

## Internal Structure Rules

Phase P should reduce broker coupling without moving ownership to the wrong
crate.

- Keep `pine-builtins` responsible for strategy declarations, order
  signatures, and accepted constants. It should not own broker behavior.
- Keep `pine-sema::analyzer::strategy` responsible for strategy-mode gating,
  unsupported variants, declaration settings, order argument checks, and
  strategy-specific diagnostics.
- Keep `pine-runtime::builtins::strategy` responsible for extracting runtime
  call arguments and dispatching accepted calls into the broker facade.
- Keep `pine-runtime::builtins::variables` responsible for reading accepted
  strategy state variables from the broker facade.
- Keep `pine-runtime::strategy::broker` responsible for broker state and public
  broker methods.
- Keep exit placement, pending-exit identity, eligibility, trigger conversion,
  fill construction, and accounting as broker-internal modules.
- Keep `pine-runtime::output::strategy` limited to public result structs. It
  should not become the source of truth for broker transitions.
- Keep Python and WASM bindings thin. They should map the shared runtime result
  only.

## Intended Module Layout

Use existing crate boundaries. A new crate is not needed for Phase P.

Recommended runtime layout after the structural slices:

```text
crates/pine-runtime/src/
   strategy/
      mod.rs                  BrokerState facade re-export
      broker/
         mod.rs               BrokerState fields, constructor, facade methods,
                              result projection, small shared helpers
         exits.rs             PendingExit, PendingExitTrigger, placement,
                              replacement, tick conversion, eligibility
         fills.rs             close/fill trade construction and position reset
         accounting.rs        equity snapshots, open/realized/equity values,
                              position/count accessors
         tests.rs             broker-focused unit tests, split by behavior area
   builtins/
      strategy.rs             runtime call extraction only
      variables.rs            strategy variable reads only
   runtime/
      historical.rs           statement execution, pending-exit evaluation
                              ordering, equity recording
   output/
      strategy.rs             public strategy result structs only
      json.rs                 no Phase P changes expected
```

Ownership notes:

- `PendingExit` and `PendingExitTrigger` should remain broker-internal. Do not
  expose them from `pine-runtime`.
- The fill module may construct `StrategyOrderEvent` and `StrategyTrade`, but
  it should not decide public JSON shape.
- The accounting module may read broker state and append equity snapshots, but
  it should not evaluate script expressions.
- Runtime built-ins should not learn about pending-exit internals. They should
  keep calling facade methods such as `place_exit_stop`, `place_exit_limit`,
  `place_exit_profit_ticks`, and `place_exit_loss_ticks`.
- `HistoricalRuntime` should continue to call only high-level broker methods:
  `evaluate_pending_exits`, `record_equity`, and `result`.

## Slice 0: Baseline Lock and Split Design Confirmation

Goal: lock the Phase O baseline and confirm that Phase P is structural before
moving code.

Steps:

1. Review `docs/PHASE_O_AUDIT.md` and confirm the closed supported surface.
2. Review the strategy rows in `tests/fixtures/conformance.tsv`.
3. Review `crates/pine-runtime/src/strategy/broker.rs` and identify the exact
   responsibilities to extract:
   - pending exit data types.
   - exit placement and replacement.
   - tick-distance conversion.
   - pending-exit eligibility and fill triggering.
   - close/fill trade construction.
   - equity and profit accounting.
   - state/count accessors.
   - unit tests.
4. Review `crates/pine-runtime/src/builtins/strategy.rs` and confirm it uses
   only broker facade methods.
5. Review `crates/pine-runtime/src/builtins/variables.rs` and confirm strategy
   state reads use broker facade accessors.
6. Review `crates/pine-runtime/src/runtime/historical.rs` and confirm pending
   exits are evaluated after script statements and before equity recording.
7. Record the current line count for the strategy runtime files:

   ```text
   wc -l crates/pine-runtime/src/strategy/broker.rs \
     crates/pine-runtime/src/builtins/strategy.rs \
     crates/pine-runtime/src/builtins/variables.rs \
     crates/pine-runtime/src/output/strategy.rs
   ```

8. Run the focused baseline verification.

Acceptance criteria:

- The team agrees Phase P does not widen the compatibility matrix by default.
- The intended module layout is confirmed.
- The current strategy tests pass before any file move.
- The current line-count pressure is recorded.

Suggested verification:

```text
cargo test -p pine-sema strategy
cargo test -p pine-runtime strategy
cargo test -p pine-cli conformance_metadata_references_existing_fixtures
git diff --check
```

Slice 0 confirmation:

- `docs/PHASE_O_AUDIT.md` is the closed baseline for the current strategy
  reporting count subset.
- `tests/fixtures/conformance.tsv` keeps the strategy surface conservative:
  strategy declarations, entries, closes, equity/state/count variables, and
  the stop/limit/profit/loss-only `strategy.exit` subset are `partial`; broad
  `strategy.*` remains `unsupported`.
- `crates/pine-runtime/src/strategy/broker.rs` currently owns pending exit
  data types, exit placement and replacement, tick-distance conversion,
  pending-exit eligibility, close/fill construction, equity/profit accounting,
  state/count accessors, public result projection, and broker-focused unit
  tests.
- `crates/pine-runtime/src/builtins/strategy.rs` dispatches accepted strategy
  calls through `BrokerState` facade methods.
- `crates/pine-runtime/src/builtins/variables.rs` reads accepted strategy state
  variables through `BrokerState` accessors.
- `crates/pine-runtime/src/runtime/historical.rs` evaluates pending exits after
  script statements and before equity recording.
- Current line counts before the structural split:

  ```text
    812 crates/pine-runtime/src/strategy/broker.rs
    140 crates/pine-runtime/src/builtins/strategy.rs
    216 crates/pine-runtime/src/builtins/variables.rs
     49 crates/pine-runtime/src/output/strategy.rs
   1217 total
  ```

- Focused baseline verification passed:

  ```text
  cargo test -p pine-sema strategy
  cargo test -p pine-runtime strategy
  cargo test -p pine-cli conformance_metadata_references_existing_fixtures
  git diff --check
  ```

## Slice 1: Mechanical Broker Module Relocation

Goal: convert the single broker file into a broker module directory without
changing behavior.

Steps:

1. Create the directory `crates/pine-runtime/src/strategy/broker/`.
2. Move the current broker implementation from
   `crates/pine-runtime/src/strategy/broker.rs` to
   `crates/pine-runtime/src/strategy/broker/mod.rs`.
3. Keep `crates/pine-runtime/src/strategy/mod.rs` as:

   ```rust
   mod broker;

   pub use broker::BrokerState;
   ```

4. Do not change logic, visibility, tests, or public exports in this slice.
5. Run formatting and focused strategy tests.
6. Inspect the diff to ensure it is a file relocation only.

Acceptance criteria:

- `pine_runtime::BrokerState` remains exported.
- Runtime built-ins and `HistoricalRuntime` compile without import changes
  outside the mechanical path update.
- All broker unit tests and strategy runtime tests pass with identical
  expectations.
- No snapshots change.

Suggested verification:

```text
cargo fmt --check
cargo test -p pine-runtime strategy
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
git diff --check
```

## Slice 2: Extract Pending Exit Domain Model

Goal: move pending-exit data structures and simple trigger helpers out of the
broker facade module.

Steps:

1. Add `crates/pine-runtime/src/strategy/broker/exits.rs`.
2. Move `PendingExitTrigger` into `exits.rs`.
3. Move `PendingExit` into `exits.rs`.
4. Keep both types broker-internal. Prefer `pub(super)` only where sibling
   modules need access.
5. Move the `PendingExitTrigger::price` helper into `exits.rs`.
6. Add small helper methods if they make the later slices clearer, for example:
   - `PendingExit::matches_replacement(...)`.
   - `PendingExit::is_eligible_on(bar_index)`.
   - `PendingExit::price()`.
7. Update `broker/mod.rs` imports.
8. Keep all existing tests in place for this slice.
9. Run focused broker and runtime strategy tests.

Acceptance criteria:

- Pending-exit types are no longer defined in the broker facade module.
- Pending-exit types are not exported outside `pine-runtime::strategy::broker`.
- No behavior changes occur for exit placement, replacement, eligibility, or
  fills.
- No snapshots change.

Suggested verification:

```text
cargo fmt --check
cargo test -p pine-runtime strategy::broker
cargo test -p pine-runtime strategy
git diff --check
```

## Slice 3: Extract Exit Placement and Trigger Conversion

Goal: isolate supported `strategy.exit` placement rules from the broker facade
while keeping the public broker methods unchanged.

Steps:

1. Keep the facade methods on `BrokerState` available with their current names:
   - `place_exit_stop`.
   - `place_exit_limit`.
   - `place_exit_profit_ticks`.
   - `place_exit_loss_ticks`.
2. Move their implementations, plus `exit_tick_price_offset` and shared
   `place_exit`, into `broker/exits.rs` as a separate `impl BrokerState` block.
3. If sibling-module access to `BrokerState` fields is needed, change only the
   necessary fields to `pub(super)` and keep `BrokerState` construction through
   `BrokerState::new`.
4. Preserve every runtime diagnostic code and message:
   - `E_STRATEGY_EXIT_PRICE`.
   - `E_STRATEGY_EXIT_TICKS`.
   - `E_STRATEGY_EXIT_MINTICK`.
   - `E_STRATEGY_EXIT_ENTRY`.
5. Preserve the unchanged repeated-exit rule: an identical accepted exit call
   keeps the original eligibility bar.
6. Preserve the changed repeated-exit rule: a changed accepted exit replaces
   the pending exit and is ineligible on the replacement bar.
7. Keep runtime built-in call extraction unchanged.
8. Run focused strategy tests.

Acceptance criteria:

- The runtime built-in layer still calls the same broker facade methods.
- Stop, limit, profit, and loss placement tests pass unchanged.
- Invalid price, invalid ticks, invalid mintick, and mismatched entry
  diagnostics pass unchanged.
- Public output snapshots remain unchanged.

Suggested verification:

```text
cargo fmt --check
cargo test -p pine-runtime strategy::broker::tests::place_exit
cargo test -p pine-runtime strategy::broker::tests::profit_ticks
cargo test -p pine-runtime strategy::broker::tests::loss_ticks
cargo test -p pine-runtime strategy
git diff --check
```

If the exact test filters above do not match after test relocation, use the
nearest focused filters or run the full strategy runtime test set.

## Slice 4: Extract Fill and Position-Reset Logic

Goal: isolate close/fill trade construction and position reset behavior without
changing strategy output.

Steps:

1. Add `crates/pine-runtime/src/strategy/broker/fills.rs`.
2. Move the implementation of `close_long` into `fills.rs` as an
   `impl BrokerState` block, while preserving its facade method name.
3. Move `fill_pending_exit` into `fills.rs`.
4. Keep `evaluate_pending_exits` in `exits.rs` or move it with fill logic only
   if the responsibility boundary is clearer. The preferred split is:
   - `exits.rs`: checks pending exit eligibility and trigger crossing.
   - `fills.rs`: records order/trade output, updates cash, clears position,
     clears pending exit, and appends position snapshots.
5. Preserve `strategy.close(id)` behavior:
   - mismatched or flat close is a no-op.
   - matching close cancels any matching pending exit.
   - matching close records a closed trade at current bar close.
   - later statements on the same bar see updated broker state.
6. Preserve pending-exit fill behavior:
   - stop/loss fills at the configured stop price.
   - limit/profit fills at the configured limit price.
   - fill appends one `strategy.exit` order event.
   - fill appends one closed trade under the source entry id.
   - fill clears position and pending exit.
7. Run broker tests, runtime strategy tests, and runtime golden snapshots.

Acceptance criteria:

- `StrategyOrderEvent` and `StrategyTrade` shapes are unchanged.
- `strategy.orders`, `strategy.trades`, and `strategy.position` snapshots are
  unchanged for all existing runtime fixtures.
- Same-bar `strategy.close` state reads remain immediate.
- Pending-exit state reads remain next-bar visible to scripts.
- No public runtime schema version changes.

Suggested verification:

```text
cargo fmt --check
cargo test -p pine-runtime strategy
cargo test -p pine-runtime --test incremental
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
git diff --check
```

## Slice 5: Extract Accounting and State Accessors

Goal: isolate broker accounting and read-only state accessors used by strategy
variables.

Steps:

1. Add `crates/pine-runtime/src/strategy/broker/accounting.rs`.
2. Move these methods into `accounting.rs` as an `impl BrokerState` block:
   - `record_equity`.
   - `open_profit`.
   - `realized_profit`.
   - `equity_value`.
   - `position_size`.
   - `position_avg_price_value`.
   - `closed_trade_count`.
   - `open_trade_count`.
3. Keep the method names and return types unchanged.
4. Keep `normalize_zero` in the smallest module that needs it, or move it to a
   broker-private helper module if both fill and accounting code need it.
5. Preserve count semantics:
   - closed count is the number of broker closed trades.
   - open count is `1` only when the supported long position is open and an
     entry id is present.
6. Preserve equity semantics:
   - per-bar equity snapshots use current close mark-to-market.
   - `strategy.netprofit` remains realized closed-trade profit only.
   - `strategy.equity` remains initial capital plus realized and open profit.
7. Run strategy variable, profile, and runtime snapshot tests.

Acceptance criteria:

- Runtime strategy state variable tests pass unchanged.
- Phase O count variable tests pass unchanged.
- Profile fixture behavior for strategy variable history is unchanged.
- Public strategy output remains schema version 3.

Suggested verification:

```text
cargo fmt --check
cargo test -p pine-runtime strategy_trade_count
cargo test -p pine-runtime strategy_variables
cargo test -p pine-runtime --test profile_fixtures
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
git diff --check
```

If the exact runtime test filters above are too narrow for the current test
names, run `cargo test -p pine-runtime strategy`.

## Slice 6: Split Broker Tests by Behavior Area

Goal: make future strategy changes easier to review by grouping broker tests
with the behavior they protect.

Steps:

1. Add `crates/pine-runtime/src/strategy/broker/tests.rs` or multiple private
   test modules under `broker/` if that keeps filters clearer.
2. Move existing broker tests out of `broker/mod.rs`.
3. Group tests by behavior area:
   - entry/no-pyramiding basics.
   - close and pending-exit cancellation.
   - stop/limit placement and fills.
   - profit/loss tick conversion.
   - repeated-exit replacement and eligibility.
   - trade count accessors.
   - invalid runtime diagnostics.
4. Keep helper functions such as `broker_with_long_entry` private to tests.
5. Preserve test names where practical. If names change, keep filters easy to
   discover with `cargo test -p pine-runtime strategy::broker -- --list`.
6. Do not change production behavior in this slice.

Acceptance criteria:

- Production modules are easier to scan because tests are no longer embedded
  in the broker facade implementation.
- All existing broker behavior remains covered.
- Focused broker test filters remain usable.

Suggested verification:

```text
cargo fmt --check
cargo test -p pine-runtime strategy::broker
cargo test -p pine-runtime strategy
git diff --check
```

## Slice 7: Public Contract Regression Sweep

Goal: prove that the structural split did not affect public host behavior.

Steps:

1. Run runtime strategy fixtures through the CLI golden snapshot harness.
2. Run incremental append execution for strategy runtime fixtures.
3. Run profile fixtures that touch strategy state history.
4. Run WASM strategy tests.
5. Run Python binding tests. If any Rust crates used by the Python wheel have
   changed since the last installed wheel, rebuild and reinstall first:

   ```text
   maturin build --manifest-path crates/pine-python/Cargo.toml --out dist
   python3 -m pip install --force-reinstall dist/*.whl
   python3 -m pytest python/tests
   ```

6. Compare strategy runtime snapshots. Any snapshot diff in Phase P should be
   treated as a regression unless a deliberate behavior-fix slice is added.
7. Confirm `PUBLIC_RUNTIME_SCHEMA_VERSION` has not changed.

Acceptance criteria:

- CLI golden snapshots are unchanged.
- Incremental append execution matches full historical execution.
- Python and WASM host behavior is unchanged.
- Runtime schema remains unchanged.

Suggested verification:

```text
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-runtime --test incremental
cargo test -p pine-runtime --test profile_fixtures
cargo test -p pine-wasm strategy
maturin build --manifest-path crates/pine-python/Cargo.toml --out dist
python3 -m pip install --force-reinstall dist/*.whl
python3 -m pytest python/tests
git diff --check
```

## Slice 8: Next Strategy Maintenance Design Gate

Goal: choose the next small strategy maintenance target without implementing it
inside Phase P.

Steps:

1. Review the Phase O maintenance tails:
   - trade namespace functions.
   - public open-trade records.
   - public pending-order records, partial-fill fields, and exit-reason fields.
   - rich metrics such as max drawdown, win trades, loss trades, and runup.
   - combined trigger brackets and same-bar high/low precedence.
   - trailing stops.
   - partial exits and quantity reservation behavior.
   - missing-entry pre-placement and multiple pending exits.
   - short entries, reversals, and short exposure.
   - `strategy.order` and richer order modification semantics.
   - commission, slippage, margin, currency conversion, cash sizing,
     contracts, and percent-of-equity sizing.
   - strategy alerts and realtime strategy execution.
2. Prefer a target that can be fixture-backed without changing public host
   schemas. The recommended next target is one of:
   - bracket design gate only: keep combined triggers unsupported but document
     the exact same-bar precedence decisions needed before support.
   - missing-entry pre-placement design gate only: keep it unsupported but
     define whether pending exits may exist before a matching entry.
   - small strategy reporting metric design gate only: keep rich metrics
     unsupported but decide which metric can be derived from existing closed
     trades without new public output.
3. Do not select partial exits, pyramiding, short exposure, or realtime broker
   rollback as the next target unless the team deliberately opens a larger
   broker phase.
4. Add or update docs to record the selected next target and why the other
   tails remain deferred.
5. If existing unsupported fixtures do not cover the selected design gate,
   add semantic fixtures that keep the unsupported boundary stable.
6. Do not update conformance status from `unsupported` or `partial` to a wider
   claim in this slice.

Acceptance criteria:

- The repository has a documented next strategy maintenance target.
- Existing unsupported boundaries remain explicit.
- Any new design-gate fixtures assert diagnostics only.
- No runtime behavior changes occur in this slice.

Suggested verification:

```text
cargo test -p pine-sema strategy
cargo test -p pine-cli conformance_metadata_references_existing_fixtures
git diff --check
```

Slice 8 decision:

- Next strategy maintenance target: bracket design gate only.
- Keep every combined trigger form unsupported while documenting the decisions
  needed before support: same-bar high/low precedence, whether stop/limit and
  profit/loss pairs are order brackets or mutually exclusive replacements,
  and how bracket identity interacts with the current one-pending-exit model.
- Existing semantic fixtures already keep this unsupported boundary stable:
  `unsupported_strategy_exit_stop_limit.pine`,
  `unsupported_strategy_exit_profit_loss.pine`,
  `unsupported_strategy_exit_stop_profit.pine`,
  `unsupported_strategy_exit_limit_loss.pine`,
  `unsupported_strategy_exit_stop_loss.pine`,
  `unsupported_strategy_exit_limit_profit.pine`, and
  `unsupported_strategy_exit_three_triggers.pine`.
- Missing-entry pre-placement remains deferred because it requires deciding
  whether broker-owned pending exits may exist without a matching current
  entry, which would widen pending-order lifecycle semantics.
- Rich reporting metrics remain deferred because public metric names, script
  state semantics, and host-output expectations need a separate reporting
  design.
- Partial exits, pyramiding, short exposure, and realtime broker rollback
  remain larger broker phases, not the next maintenance target.
- No conformance status changes are made for this design gate.

## Slice 9: Documentation and Roadmap Synchronization

Goal: synchronize the structural outcome with user-facing and maintainer docs.

Steps:

1. Update `docs/LONG_TERM_EXECUTION_PLAN.md` after the implementation lands:
   - add Phase P as closed when the audit exists.
   - keep the Phase O compatibility surface unchanged.
   - record the next recommended strategy maintenance target.
2. Update `docs/ARCHITECTURE.md` if it describes strategy runtime ownership or
   crate boundaries.
3. Update `docs/EXECUTION_SEMANTICS.md` only if wording needs to clarify that
   behavior was preserved after the split. Do not change semantics claims.
4. Update `docs/RELEASE_NOTES.md` with a maintenance note:
   - broker internals were split for maintainability.
   - no public runtime schema changed.
   - no strategy compatibility surface changed.
5. Do not update `tests/fixtures/conformance.tsv` unless Slice 8 adds new
   diagnostic-only fixtures that need matrix references.
6. Run docs-sensitive and conformance checks.

Acceptance criteria:

- Docs describe the new strategy runtime ownership without claiming new Pine
  compatibility.
- Release notes clearly mark Phase P as maintenance.
- Conformance metadata remains conservative and fixture-backed.

Suggested verification:

```text
cargo test -p pine-cli conformance_metadata_references_existing_fixtures
cargo test -p pine-cli matrix_output_matches_golden_snapshot
git diff --check
```

## Slice 10: Closeout Audit

Goal: close Phase P with a concise audit once the structural split and design
gate are complete.

Steps:

1. Create `docs/PHASE_P_AUDIT.md`.
2. Record completed slices.
3. Record the behavior-preservation claim:
   - no new strategy compatibility surface.
   - no public runtime schema change.
   - no public Python or WASM shape change.
   - no conformance widening beyond any diagnostic-only fixture references.
4. Record final module layout and ownership:
   - broker facade.
   - pending exit domain.
   - fill logic.
   - accounting and state accessors.
   - tests.
5. Record the verification evidence:
   - strategy sema tests.
   - runtime strategy tests.
   - incremental and profile tests.
   - CLI snapshots and conformance tests.
   - Python and WASM host tests.
   - full release gate.
6. Record the selected next strategy maintenance target from Slice 8.
7. Update `docs/LONG_TERM_EXECUTION_PLAN.md` to mark Phase P closed and point
   to the audit.
8. Run the full release verification gate.

Acceptance criteria:

- The audit can be used as the baseline for the next strategy maintenance
  slice.
- The repository has a clear record that Phase P changed internals only.
- Full release verification passes.

Closeout verification:

```text
git diff --check
scripts/verify.sh
```

## Suggested Commit Order

1. `Document strategy broker structure plan`
2. `Move strategy broker into module directory`
3. `Extract strategy pending exit model`
4. `Extract strategy exit placement rules`
5. `Extract strategy fill helpers`
6. `Extract strategy accounting accessors`
7. `Split strategy broker tests`
8. `Verify strategy public contracts`
9. `Record next strategy maintenance gate`
10. `Close strategy broker structure audit`

## Phase P Completion Checklist

- [x] Slice 0 baseline and split design are confirmed.
- [x] `BrokerState` remains the public strategy runtime facade.
- [x] `crates/pine-runtime/src/strategy/broker.rs` is moved to a broker module
      directory.
- [x] Pending-exit types are broker-internal and extracted from the facade.
- [x] Exit placement and tick conversion are isolated.
- [x] Fill and position-reset behavior is isolated.
- [x] Accounting and read-only state accessors are isolated.
- [x] Broker tests are grouped by behavior area.
- [x] Existing stop/limit/profit/loss exit behavior is unchanged.
- [x] Existing strategy state and count variable behavior is unchanged.
- [x] Runtime snapshots are unchanged or any deliberate behavior fix is
      separately documented.
- [x] Incremental append execution matches full historical execution.
- [x] CLI, Python, and WASM behavior remain synchronized.
- [x] Public strategy output schema remains unchanged.
- [x] `tests/fixtures/conformance.tsv` does not claim a wider strategy surface.
- [x] Next strategy maintenance target is documented.
- [x] Release notes and roadmap are synchronized.
- [x] `docs/PHASE_P_AUDIT.md` records closeout evidence.
- [x] `git diff --check` passes.
- [x] `scripts/verify.sh` passes.
