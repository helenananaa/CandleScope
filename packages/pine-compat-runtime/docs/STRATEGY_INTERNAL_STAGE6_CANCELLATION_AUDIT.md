# Strategy Internal Stage 6 Cancellation Audit

Status: closed.

This audit tracks `docs/STRATEGY_INTERNAL_EXECUTION_PLAN.md` Stage 6: General
Pending-Order Book And Cancellation.

## Slice 0: `strategy.cancel(id)`

Status: closed on 2026-06-02.

Goal: support `strategy.cancel(id)` for the currently supported internal
pending entry and pending exit subset while preserving the public strategy
output shape.

Context checked:

- `docs/STRATEGY_INTERNAL_EXECUTION_PLAN.md` Stage 6 scope;
- current `tests/fixtures/conformance.tsv` strategy rows;
- `crates/pine-builtins/src/namespaces/strategy.rs`;
- `crates/pine-sema/src/analyzer/strategy.rs` and
  `crates/pine-sema/src/analyzer/calls.rs`;
- `crates/pine-runtime/src/builtins/strategy.rs`;
- broker pending entry and pending exit books;
- existing CLI, Python, and WASM host contract tests.

Implemented:

- added the `strategy.cancel(id: simple string) -> void` built-in signature;
- accepted `strategy.cancel` in strategy-mode scripts and kept it rejected in
  unsupported side-effect contexts such as user-defined functions;
- added broker cancellation for matching pending entry ids and pending exit ids;
- wired runtime execution so `strategy.cancel(id)` evaluates the id once on the
  active bar and cancels matching internal pending orders;
- kept filled, unknown, and already-cancelled ids as no-op behavior;
- added semantic, broker, runtime, CLI snapshot, Python, and WASM coverage for
  the cancel-entry public contract.

Compatibility boundary:

- `strategy.cancel_all()` was out of scope for Slice 0 and is covered by
  Slice 1 below.
- Cancellation covers only the current supported internal pending entry and
  pending exit subset.
- No public JSON, Python, or WASM schema fields were added.
- No public pending-order, cancellation, or remaining-quantity records are
  exposed.
- Generic `strategy.order`, OCA groups, pyramiding, shorts, reversals,
  multi-entry ledgers, broker emulation settings, and richer order reporting
  remain out of scope.

Validation:

```text
cargo fmt --all --check
cargo test -p pine-builtins strategy_cancel
cargo test -p pine-sema --test fixtures strategy_cancel
cargo test -p pine-sema --test fixtures order_and_trade_namespace
cargo test -p pine-runtime strategy_cancel
cargo test -p pine-runtime cancel_pending_order
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli runtime_outputs_match_golden_snapshots
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli matrix_output_matches_golden_snapshot
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli matrix_output_matches_golden_snapshot
cargo test -p pine-cli conformance_metadata_references_existing_fixtures
cargo test -p pine-wasm strategy_cancel
cargo test -p pine-runtime runtime_fixtures_match_incremental_append_execution
maturin build --manifest-path crates/pine-python/Cargo.toml --out dist
python3 -m pip install --user --force-reinstall dist/pine_compat_runtime-0.1.0-cp310-abi3-manylinux_2_35_x86_64.whl
python3 -m pytest python/tests/test_bindings.py -q
git diff --check
scripts/verify.sh
```

Result:

- `cargo fmt --all --check` passed.
- `cargo test -p pine-builtins strategy_cancel` passed.
- `cargo test -p pine-sema --test fixtures strategy_cancel` passed.
- `cargo test -p pine-sema --test fixtures order_and_trade_namespace` passed.
- `cargo test -p pine-runtime strategy_cancel` passed.
- `cargo test -p pine-runtime cancel_pending_order` passed.
- CLI runtime and matrix snapshots were updated and then rechecked without
  `UPDATE_SNAPSHOTS`.
- `cargo test -p pine-cli conformance_metadata_references_existing_fixtures`
  passed.
- `cargo test -p pine-wasm strategy_cancel` passed.
- `cargo test -p pine-runtime runtime_fixtures_match_incremental_append_execution`
  passed.
- `maturin build --manifest-path crates/pine-python/Cargo.toml --out dist`
  passed.
- `python3 -m pip install --user --force-reinstall dist/pine_compat_runtime-0.1.0-cp310-abi3-manylinux_2_35_x86_64.whl`
  passed.
- `python3 -m pytest python/tests/test_bindings.py -q` passed with 53 tests.
- `git diff --check` passed.
- `scripts/verify.sh` passed, including workspace formatting, clippy, tests,
  structure guardrail, wasm32 check, Python wheel rebuild/install, and Python
  tests.

## Slice 1: `strategy.cancel_all()`

Status: closed on 2026-06-02.

Goal: support `strategy.cancel_all()` for the currently supported internal
pending entry and pending exit subset while preserving the public strategy
output shape.

Context checked:

- `docs/STRATEGY_INTERNAL_EXECUTION_PLAN.md` Stage 6 scope;
- current `tests/fixtures/conformance.tsv` strategy rows;
- `crates/pine-builtins/src/namespaces/strategy.rs`;
- `crates/pine-sema/src/analyzer/strategy.rs` and
  `crates/pine-sema/src/analyzer/calls.rs`;
- `crates/pine-runtime/src/builtins/strategy.rs`;
- broker pending entry and pending exit books;
- existing `strategy.cancel(id)` slice implementation and host coverage.

Implemented:

- added the `strategy.cancel_all() -> void` built-in signature;
- accepted `strategy.cancel_all()` in strategy-mode scripts and kept it covered
  by the strategy-order side-effect guard;
- added broker cancellation for all supported internal pending entries and
  pending exits;
- wired runtime execution so `strategy.cancel_all()` clears supported internal
  pending orders on the active bar;
- kept calls with no pending orders as no-op behavior;
- added semantic, broker, runtime, CLI snapshot, Python, and WASM coverage for
  the cancel-all public contract.

Compatibility boundary:

- Cancellation covers only the current supported internal pending entry and
  pending exit subset.
- No public JSON, Python, or WASM schema fields were added.
- No public pending-order, cancellation, or remaining-quantity records are
  exposed.
- Generic `strategy.order`, OCA groups, pyramiding, shorts, reversals,
  multi-entry ledgers, broker emulation settings, and richer order reporting
  remain out of scope.

Validation:

```text
cargo fmt --all --check
cargo test -p pine-builtins strategy_cancel_all
cargo test -p pine-sema --test fixtures strategy_cancel_all
cargo test -p pine-sema --test fixtures order_and_trade_namespace
cargo test -p pine-runtime strategy_cancel_all
cargo test -p pine-runtime cancel_all_pending_orders
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli runtime_outputs_match_golden_snapshots
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli matrix_output_matches_golden_snapshot
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli matrix_output_matches_golden_snapshot
cargo test -p pine-cli conformance_metadata_references_existing_fixtures
cargo test -p pine-wasm strategy_cancel_all
cargo test -p pine-runtime runtime_fixtures_match_incremental_append_execution
maturin build --manifest-path crates/pine-python/Cargo.toml --out dist
python3 -m pip install --user --force-reinstall dist/pine_compat_runtime-0.1.0-cp310-abi3-manylinux_2_35_x86_64.whl
python3 -m pytest python/tests/test_bindings.py -q
git diff --check
scripts/verify.sh
```

Result:

- `cargo fmt --all --check` passed.
- `cargo test -p pine-builtins strategy_cancel_all` passed.
- `cargo test -p pine-sema --test fixtures strategy_cancel_all` passed.
- `cargo test -p pine-sema --test fixtures order_and_trade_namespace` passed.
- `cargo test -p pine-runtime strategy_cancel_all` passed.
- `cargo test -p pine-runtime cancel_all_pending_orders` passed.
- CLI runtime and matrix snapshots were updated and then rechecked without
  `UPDATE_SNAPSHOTS`.
- `cargo test -p pine-cli conformance_metadata_references_existing_fixtures`
  passed.
- `cargo test -p pine-wasm strategy_cancel_all` passed.
- `cargo test -p pine-runtime runtime_fixtures_match_incremental_append_execution`
  passed.
- `maturin build --manifest-path crates/pine-python/Cargo.toml --out dist`
  passed.
- `python3 -m pip install --user --force-reinstall dist/pine_compat_runtime-0.1.0-cp310-abi3-manylinux_2_35_x86_64.whl`
  passed.
- `python3 -m pytest python/tests/test_bindings.py -q` passed with 54 tests.
- `git diff --check` passed.
- `scripts/verify.sh` passed, including workspace formatting, clippy, tests,
  structure guardrail, wasm32 check, Python wheel rebuild/install, and Python
  tests.
