# Strategy Internal Stage 1 Boundary Audit

Status: closed on 2026-06-02.

This audit records the Stage 1 boundary-lock evidence from
`docs/STRATEGY_INTERNAL_STAGE1_BOUNDARY_LOCK_PLAN.md`. Stage 1 must not add new
Pine strategy behavior. Support claims below are limited to current
fixture-backed evidence.

## Slice 1 Scope

Completed Stage 1 Step 1 and Step 2:

- established the current worktree scope;
- read the strategy rows in `tests/fixtures/conformance.tsv`;
- checked the corresponding strategy entries in `tests/snapshots/matrix.json`
  through `cargo run -q -p pine-cli -- matrix`;
- read current strategy sections in `docs/CONFORMANCE.md`,
  `docs/EXECUTION_SEMANTICS.md`, `docs/SEMANTIC_MODEL.md`, and
  `docs/BUILTIN_SIGNATURES.md`;
- read the Stage 1 section in `docs/STRATEGY_INTERNAL_EXECUTION_PLAN.md` and the
  current baseline in `docs/STRATEGY_INTERNAL_GAP_AUDIT.md`.

The W/X/Y/Z drift check, semantic guard check, runtime/host evidence check, and
final release gate remain for later Stage 1 slices.

## Worktree Scope

Existing non-Stage-1 edits were present before this slice:

```text
M README.md
M docs/LONG_TERM_EXECUTION_PLAN.md
?? docs/NEXT_INTERNAL_CAPABILITY_PLAN.md
?? docs/STRATEGY_INTERNAL_EXECUTION_PLAN.md
?? docs/STRATEGY_INTERNAL_GAP_AUDIT.md
?? docs/STRATEGY_INTERNAL_STAGE1_BOUNDARY_LOCK_PLAN.md
```

This slice touched only Stage 1 boundary artifacts plus one stale current
signature note:

- `docs/STRATEGY_INTERNAL_STAGE1_BOUNDARY_AUDIT.md`
- `docs/BUILTIN_SIGNATURES.md`

## Current Supported Boundary

The current fixture-backed strategy subset is partial and narrow:

- `strategy(...)` accepts the selected declaration metadata in conformance,
  positive const numeric `initial_capital`, and fixed default quantity through
  `default_qty_type=strategy.fixed` plus positive const numeric
  `default_qty_value`.
- `strategy.entry(id, strategy.long, qty=...)` supports long market entries with
  explicit positive quantity; `qty` may be omitted only when fixed default
  quantity is configured.
- The broker model is one net long position with no pyramiding.
- `strategy.close(id)` fully closes the matching long position at the current
  bar close; missing or repeated closes are no-op.
- Public strategy output remains `schemaVersion: 3` with the `strategy` object
  keys `orders`, `trades`, `position`, `equity`, and `diagnostics`.
- Read-only strategy variables are limited to `strategy.position_size`,
  `strategy.position_avg_price`, `strategy.openprofit`, `strategy.netprofit`,
  `strategy.equity`, `strategy.closedtrades`, and `strategy.opentrades`.
- `strategy.exit` supports single triggers `stop`, `limit`, `profit`, and
  `loss`; one-downside/one-upside brackets `stop + limit`, `stop + profit`,
  `loss + limit`, and `loss + profit`; and trailing forms
  `trail_price + trail_offset` and `trail_points + trail_offset`.
- Supported `strategy.exit` trigger shapes accept optional fixed `qty` or
  `qty_percent`; both quantity forms evaluate once at placement time and expose
  only absolute filled quantities in public output.
- Explicit fixed-`qty` or `qty_percent` single-trigger, bracket, and trailing
  exits can keep multiple reserved pending exits for the current matching long
  entry.
- Omitted `qty` and omitted `qty_percent` exits keep full-position
  one-effective-pending replacement behavior across supported single-trigger,
  bracket, and trailing forms, and a later omitted full-position exit clears
  earlier explicit reservations for the current matching long entry.

Primary evidence:

- `tests/fixtures/conformance.tsv`
- `tests/snapshots/matrix.json`
- `docs/CONFORMANCE.md`
- `docs/EXECUTION_SEMANTICS.md`
- `docs/SEMANTIC_MODEL.md`
- `docs/STRATEGY_INTERNAL_GAP_AUDIT.md`
- `docs/STRATEGY_INTERNAL_EXECUTION_PLAN.md`

## Current Unsupported Boundary

The following remain outside the current supported strategy boundary:

- short exposure, reversals, pyramiding, and multiple simultaneous entries;
- active pending entries and Pine-compatible next-tick order timing;
- entry `limit`, `stop`, and stop-limit orders;
- `strategy.close_all()` and partial `strategy.close`;
- `strategy.order`, `strategy.cancel`, and `strategy.cancel_all`;
- `strategy.risk.*`;
- `strategy.closedtrades.*` and `strategy.opentrades.*` namespace functions;
- strategy declaration properties beyond the current subset, including
  `pyramiding`, `calc_on_order_fills`, `calc_on_every_tick`,
  `process_orders_on_close`, `backtest_fill_limits_assumption`, cash sizing,
  percent-of-equity sizing, `currency`, `slippage`, commission, margin,
  `close_entries_rule`, `risk_free_rate`, bar magnifier, and standard-OHLC fill
  settings;
- `strategy.exit` same-side pairs, 3+ trigger combinations, invalid trailing
  combinations, `qty + qty_percent`, missing-entry forms, omitted-quantity
  multiple reservations, and reservation behavior outside explicit fixed-`qty`
  or `qty_percent` single-trigger, bracket, and trailing exits;
- public pending-order records, reservation ledgers, remaining quantities,
  percent inputs, trigger-side metadata, bracket-leg metadata,
  trailing-state metadata, exit reasons, commission fields, runup/drawdown
  fields, and runtime schema changes.

Primary evidence:

- `tests/fixtures/conformance.tsv`
- `tests/snapshots/matrix.json`
- `docs/CONFORMANCE.md`
- `docs/EXECUTION_SEMANTICS.md`
- `docs/SEMANTIC_MODEL.md`
- `docs/STRATEGY_INTERNAL_GAP_AUDIT.md`

## Drift Corrected In Slice 1

`docs/BUILTIN_SIGNATURES.md` described multiple reserved pending exits only for
single-trigger `strategy.exit` calls. Current conformance, matrix, and strategy
semantics include explicit fixed-`qty` or `qty_percent` reservations for
single-trigger, bracket, and trailing supported trigger shapes. This slice
updated that wording without changing signatures, runtime behavior,
conformance, matrix snapshots, or public output.

## Slice 1 Validation

Passed:

```bash
git diff --check
rg -n "[ \t]+$" docs/STRATEGY_INTERNAL_STAGE1_BOUNDARY_AUDIT.md docs/STRATEGY_INTERNAL_STAGE1_BOUNDARY_LOCK_PLAN.md docs/BUILTIN_SIGNATURES.md
cargo run -q -p pine-cli -- matrix
```

The `rg` command exited with no matches, which confirms there is no trailing
whitespace in the checked Stage 1 docs.

## Slice 2 Scope

Completed Stage 1 Step 3:

- compared `docs/PHASE_W_AUDIT.md`, `docs/PHASE_W_EXECUTION_PLAN.md`,
  `docs/PHASE_X_AUDIT.md`, `docs/PHASE_Y_AUDIT.md`, and
  `docs/PHASE_Z_AUDIT.md` against current conformance and matrix evidence;
- checked reservation wording for single-trigger, bracket, and trailing exits;
- checked omitted-quantity replacement and explicit-reservation clearing
  wording;
- treated each historical phase audit as evidence for its own closed scope.

The semantic guard check, runtime/host evidence check, and final release gate
remain for later Stage 1 slices.

## W/X/Y/Z Drift Check

No historical phase audit needed widening:

- `docs/PHASE_W_AUDIT.md` correctly records the Phase W scope as explicit
  fixed-`qty` or `qty_percent` single-trigger reservations only.
- `docs/PHASE_X_AUDIT.md` correctly extends the reservation model to explicit
  fixed-`qty` or `qty_percent` one-downside/one-upside bracket exits.
- `docs/PHASE_Y_AUDIT.md` correctly extends the reservation model to explicit
  fixed-`qty` or `qty_percent` trailing exits.
- `docs/PHASE_Z_AUDIT.md` correctly records omitted-quantity full-position
  replacement across supported single-trigger, bracket, and trailing forms, plus
  clearing of earlier explicit reservations by a later omitted full-position
  exit.

`docs/PHASE_W_EXECUTION_PLAN.md` contains Phase W starting-point, implementation
record, and "At Phase W close" statements that are narrower than the current
post-Phase-Z boundary. Those statements are historical Phase W records, not
stale current-boundary claims, so this slice left them unchanged.

Current conformance and matrix evidence agrees with the post-Phase-Z boundary:
explicit fixed-`qty` or `qty_percent` single-trigger, bracket, and trailing
exits are the only fixture-backed multiple-reservation subset; omitted-quantity
multiple reservations, `qty + qty_percent`, missing-entry pre-placement, public
pending/reservation fields, shorts, pyramiding, and richer broker behavior
remain unsupported.

## Drift Corrected In Slice 2

`docs/CONFORMANCE.md` had a stale sentence fragment between the Phase Y
reservation wording and the Phase Z omitted-quantity paragraph. This slice
removed the fragment and kept the existing current boundary unchanged.

At Slice 2 close, `docs/RELEASE_NOTES.md` recorded that Strategy Internal Stage
1 boundary-lock documentation had started and that the current reservation
wording was aligned without runtime behavior, conformance, matrix, or
public-output changes. Slice 3 later updated that same release note after adding
negative semantic guard fixtures.

## Slice 2 Validation

Passed:

```bash
git diff --check
rg -n "[ \t]+$" docs/STRATEGY_INTERNAL_STAGE1_BOUNDARY_AUDIT.md docs/STRATEGY_INTERNAL_STAGE1_BOUNDARY_LOCK_PLAN.md docs/BUILTIN_SIGNATURES.md docs/CONFORMANCE.md docs/RELEASE_NOTES.md
cargo run -q -p pine-cli -- matrix
```

The `rg` command exited with no matches, which confirms there is no trailing
whitespace in the checked Stage 1 and current-boundary docs.

## Slice 3 Scope

Completed Stage 1 Step 4:

- read the current strategy builtins in
  `crates/pine-builtins/src/namespaces/strategy.rs`;
- read the current `strategy(...)` declaration signature in
  `crates/pine-builtins/src/namespaces/core.rs`;
- read the strategy semantic analyzer in
  `crates/pine-sema/src/analyzer/strategy.rs`;
- checked existing strategy semantic fixtures under `tests/fixtures/sema`;
- added explicit negative fixtures for unsupported declaration properties and
  unsupported order/trade/risk namespaces;
- synchronized `tests/fixtures/conformance.tsv` and the matrix snapshot with the
  added semantic guard fixtures.

The runtime/host evidence check and final release gate remain for later Stage 1
slices.

## Semantic Guard Check

The current semantic boundary remains guarded before runtime:

- `strategy(...)` accepts only the current declaration subset from the core
  builtin signature. Unknown declaration properties are rejected by named
  argument checking, while existing strategy-specific validation keeps
  `initial_capital`, `default_qty_type`, and `default_qty_value` inside the
  current supported subset.
- `strategy.entry` remains long-only and rejects unsupported directions, active
  pending entry order forms, and invalid quantities.
- `strategy.exit` rejects unsupported quantity combinations, same-side trigger
  pairs, 3+ trigger combinations, invalid trailing combinations, missing
  triggers, and missing-entry pre-placement forms.
- `strategy.close_all`, `strategy.order`, `strategy.cancel`,
  `strategy.cancel_all`, `strategy.risk.*`, and
  `strategy.closedtrades.*`/`strategy.opentrades.*` namespace functions remain
  unsupported.
- Unsupported strategy assignments remain rejected by the existing semantic
  mutation checks.

Existing fixtures already covered many unsupported `strategy.entry`,
`strategy.exit`, state-variable, mutation, indicator-mode, and
`strategy.order` cases. This slice found two current-boundary guard areas that
were code-protected but not explicit in semantic fixtures:

- unsupported `strategy(...)` declaration properties beyond the current subset;
- unsupported order/trade/risk namespaces such as `strategy.close_all`,
  `strategy.cancel`, `strategy.cancel_all`, `strategy.risk.max_drawdown`,
  `strategy.closedtrades.entry_price`, and `strategy.opentrades.entry_price`.

This slice added:

- `tests/fixtures/sema/unsupported_strategy_declaration_properties.pine`
- `tests/fixtures/sema/unsupported_strategy_order_and_trade_namespaces.pine`

Those fixtures assert that Stage 1 did not widen strategy declaration support,
order management APIs, risk APIs, or closed/open-trade namespace functions.

## Drift Corrected In Slice 3

`tests/fixtures/conformance.tsv` and `tests/snapshots/matrix.json` now include
the added negative semantic fixtures, so the matrix records the explicit
unsupported-boundary guard coverage. `docs/RELEASE_NOTES.md` was updated to
record that conformance and matrix snapshots changed only for negative semantic
guard coverage; runtime behavior and public strategy output remain unchanged.

## Slice 3 Validation

Passed:

```bash
cargo test -p pine-sema strategy
cargo test -p pine-cli matrix
cargo test -p pine-cli matrix_output_matches_golden_snapshot
git diff --check
rg -n "[ \t]+$" docs/STRATEGY_INTERNAL_STAGE1_BOUNDARY_AUDIT.md docs/STRATEGY_INTERNAL_STAGE1_BOUNDARY_LOCK_PLAN.md docs/BUILTIN_SIGNATURES.md docs/CONFORMANCE.md docs/RELEASE_NOTES.md crates/pine-sema/tests/fixtures.rs tests/fixtures/conformance.tsv tests/fixtures/sema/unsupported_strategy_declaration_properties.pine tests/fixtures/sema/unsupported_strategy_order_and_trade_namespaces.pine
cargo run -q -p pine-cli -- matrix
scripts/verify.sh
```

The `rg` command exited with no matches, which confirms there is no trailing
whitespace in the checked Stage 1 docs, current-boundary docs, fixture index,
and added semantic fixtures. `scripts/verify.sh` passed the full release gate,
including `cargo fmt --check`, clippy, workspace tests, structure guard,
WASM check, Python wheel build/install, and Python binding tests.

## Slice 4 Scope

Completed Stage 1 Step 5:

- read `crates/pine-runtime/src/builtins/strategy.rs`;
- read the broker implementation under `crates/pine-runtime/src/strategy/`;
- checked runtime strategy fixtures under `tests/fixtures/runtime`;
- checked CLI strategy fixture harness and host-shape assertions in
  `crates/pine-cli/src/main.rs`;
- checked Python strategy host tests in `python/tests/test_bindings.py`;
- checked WASM strategy host tests in `crates/pine-wasm/src/tests/mod.rs`;
- checked public strategy output serialization in
  `crates/pine-runtime/src/output/strategy.rs`,
  `crates/pine-runtime/src/output/json.rs`, and
  `crates/pine-python/src/lib.rs`.

The final Stage 1 closeout gate remains for a later slice.

## Runtime And Host Evidence Check

No runtime or host evidence gap was found for the current supported boundary.
The current runtime surface still flows through the existing strategy builtin
dispatcher and one broker state:

- `crates/pine-runtime/src/builtins/strategy.rs` dispatches only
  `strategy.entry`, `strategy.close`, and `strategy.exit`.
- `crates/pine-runtime/src/strategy/broker/mod.rs`,
  `crates/pine-runtime/src/strategy/broker/exits.rs`,
  `crates/pine-runtime/src/strategy/broker/fills.rs`, and
  `crates/pine-runtime/src/strategy/broker/accounting.rs` keep the current
  one-net-long broker state, equity snapshots, close fills, pending exits,
  quantity resolution, reservation ledger, and omitted-quantity replacement
  behavior.
- `crates/pine-runtime/src/builtins/variables.rs` serves only the supported
  read-only strategy variables from broker state.
- Public output remains limited to the `StrategyResult` fields `orders`,
  `trades`, `position`, `equity`, and `diagnostics`.

Runtime fixtures and snapshots cover the current behavior families:

- baseline strategy output shape:
  `tests/fixtures/runtime/strategy_no_order.pine`;
- entry, fixed default quantity, and close behavior:
  `strategy_entry.pine`, `strategy_default_quantity.pine`,
  `strategy_default_quantity_override.pine`,
  `strategy_builtin_default_quantity.pine`, and `strategy_close.pine`;
- equity and state/count variables:
  `strategy_equity.pine`, `strategy_position_state.pine`,
  `strategy_profit_state.pine`, `strategy_trade_counts.pine`,
  `strategy_exit_trade_counts.pine`, and
  `strategy_variable_interactions.pine`;
- stop, limit, profit, and loss exits:
  `strategy_exit_stop.pine`, `strategy_exit_limit.pine`,
  `strategy_exit_profit.pine`, `strategy_exit_loss.pine`, and
  `strategy_exit_profit_loss_interactions.pine`;
- bracket exits:
  `strategy_exit_bracket_*` fixtures;
- trailing exits:
  `strategy_exit_trail_*` and `strategy_exit_trailing_*` fixtures;
- fixed-`qty` and `qty_percent` partial exits:
  `strategy_exit_qty_*` and `strategy_exit_qty_percent_*` fixtures;
- explicit fixed-`qty` or `qty_percent` single-trigger, bracket, and trailing
  reservations:
  `strategy_exit_reservation_qty_*`,
  `strategy_exit_reservation_qty_percent_*`, and
  `strategy_exit_reservation_qty_mixed_*` fixtures across single-trigger,
  bracket, and trailing families;
- omitted-quantity replacement and explicit-reservation clearing:
  `strategy_exit_omitted_single_replacement.pine`,
  `strategy_exit_omitted_bracket_replacement.pine`,
  `strategy_exit_omitted_trailing_replacement.pine`, and
  `strategy_exit_omitted_replaces_reservations.pine`.

Host evidence is present on all current public entrypoints:

- CLI runtime fixture snapshots include the strategy runtime fixtures above,
  and targeted CLI tests assert host-stable public shape for single-trigger,
  bracket, trailing, and omitted-quantity reservation fixtures.
- Python tests assert the same public result keys, `schemaVersion: 3`, concrete
  order/trade/position/equity values for entry, close, stop/limit/profit/loss,
  bracket, trailing, fixed-`qty`, `qty_percent`, single-trigger reservation,
  bracket reservation, trailing reservation, and omitted-quantity replacement.
- WASM tests assert the same strategy JSON shape and representative values for
  entry, default quantity, state/count variables, close, stop/limit/profit/loss,
  bracket, trailing, fixed-`qty`, `qty_percent`, single-trigger reservation,
  bracket reservation, trailing reservation, and omitted-quantity replacement.
- CLI, Python, and WASM host tests also assert that public strategy output does
  not expose pending-order records, reservation ledgers, reserved or remaining
  quantities, percent inputs, trigger-side metadata, bracket metadata, trailing
  state, activation data, or exit reasons.

## Drift Corrected In Slice 4

None. This slice did not change runtime behavior, host behavior, conformance,
matrix snapshots, public output shape, or release-facing docs. The existing
runtime and host evidence already covers the current fixture-backed Stage 1
boundary.

## Slice 4 Validation

Passed:

```bash
cargo test -p pine-runtime strategy
cargo test -p pine-cli strategy
cargo test -p pine-wasm strategy
python3 -m pytest python/tests
cargo run -q -p pine-cli -- matrix
git diff --check
rg -n "[ \t]+$" docs/STRATEGY_INTERNAL_STAGE1_BOUNDARY_AUDIT.md docs/STRATEGY_INTERNAL_STAGE1_BOUNDARY_LOCK_PLAN.md
```

The `rg` command exited with no matches, which confirms there is no trailing
whitespace in the checked Stage 1 docs.

## Stage 1 Closeout

Stage 1 is closed for the current boundary-lock scope. The closeout answers from
`docs/STRATEGY_INTERNAL_STAGE1_BOUNDARY_LOCK_PLAN.md` are:

- current supported behavior is recorded in `Current Supported Boundary`;
- explicitly unsupported behavior is recorded in `Current Unsupported Boundary`;
- fixture, matrix, host, and phase-audit evidence is recorded in Slice 1 through
  Slice 4;
- stale current-boundary wording was reconciled in Slice 1, Slice 2, and Slice
  3;
- no runtime or host evidence gap was found in Slice 4.

Execution-step status:

- Step 1 and Step 2: complete in Slice 1.
- Step 3: complete in Slice 2.
- Step 4: complete in Slice 3.
- Step 5: complete in Slice 4.
- Step 6: complete. All edits stayed within boundary-lock artifacts, current
  documentation wording, negative semantic fixtures, conformance/matrix metadata
  for those negative fixtures, and release notes. No runtime behavior, public
  strategy JSON shape, pending-entry behavior, order timing, `close_all`, entry
  stop/limit, cancellation API, trade namespace, cost/account, or broker
  expansion work was added.
- Step 7: complete. Slice-specific validation passed, and the final closeout
  gate below passed.

Stop conditions were not reached. Repo evidence was sufficient to determine the
current boundary, stale documentation wording was resolved without introducing a
doc/conformance/runtime conflict, and the only fixture gaps found were closed by
negative semantic fixtures that keep unsupported behavior rejected.

## Final Closeout Validation

Passed:

```bash
scripts/verify.sh
cargo run -q -p pine-cli -- matrix
git diff --check
rg -n "[ \t]+$" docs/STRATEGY_INTERNAL_STAGE1_BOUNDARY_LOCK_PLAN.md docs/STRATEGY_INTERNAL_STAGE1_BOUNDARY_AUDIT.md docs/STRATEGY_INTERNAL_EXECUTION_PLAN.md docs/RELEASE_NOTES.md
```
