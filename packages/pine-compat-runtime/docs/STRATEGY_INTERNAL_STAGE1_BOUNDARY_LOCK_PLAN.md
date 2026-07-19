# Strategy Internal Stage 1 Boundary Lock Plan

Status: closed on 2026-06-02.

This document expands Stage 1 from
`docs/STRATEGY_INTERNAL_EXECUTION_PLAN.md`. The goal is to lock the current
strategy support boundary before any pending-entry or broker-timing work starts.

Stage 1 must not add new Pine strategy behavior. It may correct documentation
drift, align matrix/conformance wording with fixture-backed behavior, and add
negative fixtures only when an unsupported boundary is not clearly guarded.

## Goal

Freeze the current fixture-backed strategy subset and unsupported boundary so
later implementation slices can rely on a stable baseline.

The Stage 1 closeout should answer:

- What strategy behavior is currently supported?
- What strategy behavior is explicitly unsupported?
- Which claims are backed by fixtures, matrix output, host parity tests, and
  phase audits?
- Which existing documents were stale and how were they reconciled?

## Source Evidence

Review these before making edits:

- `docs/STRATEGY_INTERNAL_EXECUTION_PLAN.md`
- `docs/STRATEGY_INTERNAL_GAP_AUDIT.md`
- `tests/fixtures/conformance.tsv`
- `tests/snapshots/matrix.json`
- `docs/CONFORMANCE.md`
- `docs/EXECUTION_SEMANTICS.md`
- `docs/SEMANTIC_MODEL.md`
- `docs/BUILTIN_SIGNATURES.md`
- `docs/PHASE_W_AUDIT.md`
- `docs/PHASE_W_EXECUTION_PLAN.md`
- `docs/PHASE_X_AUDIT.md`
- `docs/PHASE_Y_AUDIT.md`
- `docs/PHASE_Z_AUDIT.md`
- `docs/RELEASE_NOTES.md`
- `crates/pine-builtins/src/namespaces/strategy.rs`
- `crates/pine-sema/src/analyzer/strategy.rs`
- `crates/pine-runtime/src/builtins/strategy.rs`
- `crates/pine-runtime/src/strategy/`
- CLI strategy fixture harness in `crates/pine-cli/src/main.rs`
- Python strategy host tests in `python/tests/test_bindings.py`
- WASM strategy host tests in `crates/pine-wasm/src/tests/mod.rs`

## Current Boundary To Confirm

Supported or partial strategy surface should remain limited to:

- `strategy(...)` declaration metadata currently listed in conformance.
- Positive const `initial_capital`.
- `default_qty_type=strategy.fixed` with positive const
  `default_qty_value`.
- Long-only `strategy.entry` market entries with explicit positive `qty` or
  configured fixed default quantity.
- One-net-long, no-pyramiding broker state.
- `strategy.close(id)` full close for the matching long position.
- Public strategy output shape:
  - `orders`;
  - `trades`;
  - `position`;
  - `equity`;
  - `diagnostics`.
- Read-only state/count variables:
  - `strategy.position_size`;
  - `strategy.position_avg_price`;
  - `strategy.openprofit`;
  - `strategy.netprofit`;
  - `strategy.equity`;
  - `strategy.closedtrades`;
  - `strategy.opentrades`.
- `strategy.exit` supported trigger families:
  - single `stop`, `limit`, `profit`, or `loss`;
  - one-downside/one-upside brackets: `stop + limit`, `stop + profit`,
    `loss + limit`, `loss + profit`;
  - trailing forms: `trail_price + trail_offset` and
    `trail_points + trail_offset`.
- Optional fixed `qty` and `qty_percent` on supported `strategy.exit` trigger
  shapes.
- Explicit fixed-`qty` or `qty_percent` multiple reservations for supported
  single-trigger, bracket, and trailing exits.
- Omitted-quantity full-position replacement behavior and clearing of earlier
  explicit reservations when a later full-position omitted-quantity exit is
  placed.

Unsupported boundary should remain explicit for:

- Short exposure, reversals, pyramiding, and multiple simultaneous entries.
- Active pending entries and Pine-compatible next-tick order timing.
- Entry `limit`, `stop`, and stop-limit orders.
- `strategy.close_all()`.
- Partial `strategy.close`.
- `strategy.order`, `strategy.cancel`, and `strategy.cancel_all`.
- `strategy.risk.*`.
- `strategy.closedtrades.*` and `strategy.opentrades.*` namespace functions.
- Strategy declaration properties beyond the current subset, including
  `pyramiding`, `calc_on_order_fills`, `calc_on_every_tick`,
  `process_orders_on_close`, `backtest_fill_limits_assumption`, cash and
  percent-of-equity sizing, `currency`, `slippage`, commission, margin,
  `close_entries_rule`, `risk_free_rate`, bar magnifier, and standard-OHLC fill
  settings.
- `strategy.exit` same-side pairs, 3+ trigger combinations, invalid trailing
  combinations, `qty + qty_percent`, missing-entry forms, omitted-quantity
  multiple reservations, and reservation behavior outside the current explicit
  fixed-`qty` or `qty_percent` supported shapes.
- Public pending-order records, reservation ledgers, remaining quantities,
  percent inputs, trigger-side metadata, bracket-leg metadata, trailing-state
  metadata, exit reasons, commission fields, runup/drawdown fields, and runtime
  schema changes.

## Execution Steps

### Step 1: Establish Worktree Scope

- Run `git status --short`.
- Identify unrelated existing user edits.
- Do not modify unrelated files.
- Keep any eventual commit scoped to Stage 1 only.

### Step 2: Read Current Support Evidence

- Read the strategy rows in `tests/fixtures/conformance.tsv`.
- Read the corresponding strategy entries in `tests/snapshots/matrix.json`.
- Read current strategy sections in `docs/CONFORMANCE.md`,
  `docs/EXECUTION_SEMANTICS.md`, `docs/SEMANTIC_MODEL.md`, and
  `docs/BUILTIN_SIGNATURES.md`.
- Read `docs/STRATEGY_INTERNAL_GAP_AUDIT.md` and the Stage 1 section in
  `docs/STRATEGY_INTERNAL_EXECUTION_PLAN.md`.

Deliverable: a short list of the current supported and unsupported strategy
surface, with file references.

### Step 3: Check Reservation And Omitted-Quantity Drift

- Compare `docs/PHASE_W_AUDIT.md`, `docs/PHASE_W_EXECUTION_PLAN.md`,
  `docs/PHASE_X_AUDIT.md`, `docs/PHASE_Y_AUDIT.md`, and
  `docs/PHASE_Z_AUDIT.md` against current conformance and matrix evidence.
- Pay special attention to reservation wording for single-trigger, bracket, and
  trailing exits, plus omitted-quantity replacement and explicit-reservation
  clearing.
- Treat each historical phase audit as evidence for its own closed scope:
  Phase W for single-trigger reservations, Phase X for bracket reservations,
  Phase Y for trailing reservations, and Phase Z for omitted-quantity
  replacement and clearing.
- Patch only text that presents a stale current-boundary claim. Do not broaden
  a historical phase's own scoped audit wording merely because later phases
  expanded the current fixture-backed boundary.

Deliverable: W/X/Y/Z drift either corrected or explicitly reported as absent.

### Step 4: Check Semantic Guards

- Inspect `crates/pine-builtins/src/namespaces/strategy.rs` for known function
  signatures.
- Inspect `crates/pine-sema/src/analyzer/strategy.rs` for declaration,
  order-call, state-variable, and `strategy.exit` shape validation.
- Check semantic fixtures under `tests/fixtures/sema/*strategy*`.

Confirm key unsupported boundaries are guarded:

- unsupported declaration properties;
- `strategy.entry` short and stop/limit forms;
- strategy order calls in indicator mode;
- `strategy.order`;
- unsupported strategy state variables and mutation;
- `strategy.exit` same-side pairs, 3+ triggers, invalid trailing forms,
  missing-entry forms, and `qty + qty_percent`.

Deliverable: either no fixture gap, or a narrow list of missing negative
fixtures to add.

### Step 5: Check Runtime And Host Evidence

- Inspect `crates/pine-runtime/src/builtins/strategy.rs`.
- Inspect `crates/pine-runtime/src/strategy/`.
- Check runtime fixtures under `tests/fixtures/runtime/*strategy*`.
- Check CLI, Python, and WASM host tests for strategy output shape and
  reservation host parity.

Confirm current runtime evidence covers:

- baseline strategy output shape;
- entry and close behavior;
- equity and state variables;
- stop/limit/profit/loss exits;
- bracket exits;
- trailing exits;
- fixed-`qty` and `qty_percent` partial exits;
- explicit fixed-`qty` or `qty_percent` single-trigger, bracket, and trailing
  reservations;
- omitted-quantity replacement and explicit-reservation clearing.

Deliverable: either no runtime/host gap, or a narrow list of missing runtime or
host evidence to add without widening behavior.

### Step 6: Patch Only Boundary Artifacts

Allowed edits:

- Correct stale documentation wording.
- Add or update negative semantic fixtures for unsupported forms.
- Update conformance or matrix wording only to match already fixture-backed
  behavior.
- Update release notes only if Stage 1 changes user-visible documentation,
  conformance metadata, or fixture coverage.

Disallowed edits:

- New runtime behavior.
- New accepted Pine syntax unless it is only a diagnostic metadata correction
  and remains rejected semantically.
- Public strategy JSON shape changes.
- Pending-entry, order-timing, `close_all`, entry stop/limit, cancel, trade
  namespace, cost/account, or broker-expansion work.

### Step 7: Verify

Minimum checks for documentation-only changes:

```bash
git diff --check
cargo run -q -p pine-cli -- matrix
```

Additional checks when semantic fixtures change:

```bash
cargo test -p pine-sema strategy
cargo run -q -p pine-cli -- matrix
```

Additional checks when runtime fixture or host evidence changes:

```bash
cargo test -p pine-runtime strategy
cargo test -p pine-runtime --test incremental
cargo test -p pine-cli strategy
python3 -m pytest python/tests
cargo test -p pine-wasm strategy
scripts/verify.sh
```

Use `scripts/verify.sh` as the closeout gate when conformance, snapshots,
runtime fixtures, host behavior, or release-facing docs change.

## Stop Conditions

Stop and report instead of implementing if:

- The current repo evidence cannot determine whether a strategy behavior is
  supported.
- A doc/conformance/runtime conflict cannot be resolved by correcting stale
  wording.
- Closing a fixture gap would require new runtime behavior.
- A public output shape change appears necessary.
- The work starts depending on Stage 2 or later behavior.

## Stage 1 Closeout Artifacts

Stage 1 should close with:

- a concise audit note or phase audit describing the locked supported and
  unsupported boundary;
- corrected drift in Phase W/X/Y/Z or other strategy docs if found;
- any added negative fixtures listed explicitly;
- synchronized conformance and matrix output if their wording or fixture lists
  changed;
- release notes only if user-visible documentation or metadata changed;
- validation command results recorded in the closeout response or audit.
