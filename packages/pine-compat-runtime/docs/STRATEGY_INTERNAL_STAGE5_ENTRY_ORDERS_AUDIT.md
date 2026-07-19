# Strategy Internal Stage 5 Entry Orders Audit

Status: closed.

This audit tracks `docs/STRATEGY_INTERNAL_EXECUTION_PLAN.md` Stage 5: Entry
Limit, Stop, And Stop-Limit Orders.

## Slice 0: Long limit entries

Status: closed on 2026-06-02.

Goal: support `strategy.entry(..., limit=price)` for the current long-only,
one-net-position broker.

Context checked:

- `docs/STRATEGY_INTERNAL_EXECUTION_PLAN.md` Stage 5 scope;
- current `tests/fixtures/conformance.tsv` strategy entry row;
- `crates/pine-builtins/src/namespaces/strategy.rs`;
- `crates/pine-sema/src/analyzer/strategy.rs`;
- `crates/pine-runtime/src/builtins/strategy.rs`;
- current pending-entry book, same-calculation exit attachment, CLI, Python,
  and WASM coverage.

Implemented:

- added optional `limit` to the `strategy.entry` signature;
- accepted series/simple numeric `limit` values in strategy-mode entry calls;
- rejected non-positive const and runtime limit prices;
- reused the internal pending-entry book for long limit entries;
- kept limit entries from filling on the creation bar;
- filled eligible long limit entries at the limit price before script
  statements on a later historical bar when `low <= limit`;
- preserved same-calculation absolute `strategy.exit` attachment to the active
  pending limit entry id;
- added semantic, broker, runtime, CLI snapshot, Python host, and WASM host
  coverage.

Compatibility boundary:

- No public JSON schema or public strategy output shape changed.
- Pending limit entries are internal and emit no public order until filled.
- Stop entries, stop-limit entries, short entries, reversals, pyramiding,
  cancellation APIs, and generic `strategy.order` remain out of scope.

Validation:

```text
cargo fmt --all --check
cargo test -p pine-builtins strategy_entry
cargo test -p pine-sema --test fixtures strategy_entry
cargo test -p pine-runtime entry_limit
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli runtime_outputs_match_golden_snapshots
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli matrix_output_matches_golden_snapshot
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli matrix_output_matches_golden_snapshot
cargo test -p pine-cli conformance_metadata_references_existing_fixtures
cargo test -p pine-wasm entry_limit
cargo test -p pine-runtime runtime_fixtures_match_incremental_append_execution
maturin build --manifest-path crates/pine-python/Cargo.toml --out dist
python3 -m pip install --user --force-reinstall dist/pine_compat_runtime-0.1.0-cp310-abi3-manylinux_2_35_x86_64.whl
python3 -m pytest python/tests/test_bindings.py -q
git diff --check
scripts/verify.sh
```

Result:

- `cargo fmt --all --check` passed.
- `cargo test -p pine-builtins strategy_entry` passed.
- `cargo test -p pine-sema --test fixtures strategy_entry` passed.
- `cargo test -p pine-runtime entry_limit` passed.
- CLI runtime and matrix snapshots were updated and then rechecked without
  `UPDATE_SNAPSHOTS`.
- `cargo test -p pine-cli conformance_metadata_references_existing_fixtures`
  passed.
- `cargo test -p pine-wasm entry_limit` passed.
- `cargo test -p pine-runtime runtime_fixtures_match_incremental_append_execution`
  passed.
- `maturin build --manifest-path crates/pine-python/Cargo.toml --out dist`
  passed.
- `python3 -m pytest python/tests/test_bindings.py -q` passed with 50 tests
  after reinstalling the rebuilt wheel.
- `git diff --check` passed.
- `scripts/verify.sh` passed, including workspace formatting, clippy, tests,
  structure guardrail, wasm32 check, Python wheel rebuild/install, and Python
  tests.

## Slice 2: Long stop-limit entries

Status: closed on 2026-06-02.

Goal: support `strategy.entry(..., stop=price, limit=price)` for the current
long-only, one-net-position broker.

Context checked:

- `docs/STRATEGY_INTERNAL_EXECUTION_PLAN.md` Stage 5 scope;
- current `tests/fixtures/conformance.tsv` strategy entry row;
- current long limit and long stop entry implementation from Slices 0 and 1;
- `crates/pine-builtins/src/namespaces/strategy.rs`;
- `crates/pine-sema/src/analyzer/strategy.rs`;
- `crates/pine-runtime/src/builtins/strategy.rs`;
- current pending-entry book, same-calculation exit attachment, CLI, Python,
  and WASM coverage.

Implemented:

- accepted `limit + stop` on `strategy.entry` as a long stop-limit entry;
- kept positive const and runtime validation for both stop and limit prices;
- reused the internal pending-entry book with an activation state for long
  stop-limit entries;
- activated stop-limit entries on a later historical bar when `high >= stop`;
- kept stop-limit entries from filling on the activation bar;
- filled activated stop-limit entries at the limit price before script
  statements on a later historical bar when `low <= limit`;
- preserved same-calculation absolute `strategy.exit` attachment to the active
  pending stop-limit entry id;
- added semantic, broker, runtime, CLI snapshot, Python host, and WASM host
  coverage.

Compatibility boundary:

- No public JSON schema or public strategy output shape changed.
- Pending stop-limit entries are internal and emit no public order until filled.
- Short entries, reversals, pyramiding, cancellation APIs, and generic
  `strategy.order` remain out of scope.
- Same-bar stop-limit activation and fill is intentionally not claimed because
  the current historical engine does not model intrabar path reconstruction.

Validation:

```text
cargo fmt --all --check
cargo test -p pine-builtins strategy_entry
cargo test -p pine-sema --test fixtures strategy_entry
cargo test -p pine-runtime stop_limit_entry
cargo test -p pine-runtime entry_stop_limit
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli runtime_outputs_match_golden_snapshots
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli matrix_output_matches_golden_snapshot
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli matrix_output_matches_golden_snapshot
cargo test -p pine-cli conformance_metadata_references_existing_fixtures
cargo test -p pine-wasm entry_stop_limit
cargo test -p pine-runtime runtime_fixtures_match_incremental_append_execution
maturin build --manifest-path crates/pine-python/Cargo.toml --out dist
python3 -m pip install --user --force-reinstall dist/pine_compat_runtime-0.1.0-cp310-abi3-manylinux_2_35_x86_64.whl
python3 -m pytest python/tests/test_bindings.py -q
git diff --check
scripts/verify.sh
```

Result:

- `cargo fmt --all --check` passed.
- `cargo test -p pine-builtins strategy_entry` passed.
- `cargo test -p pine-sema --test fixtures strategy_entry` passed.
- `cargo test -p pine-runtime stop_limit_entry` passed.
- `cargo test -p pine-runtime entry_stop_limit` passed.
- CLI runtime and matrix snapshots were updated and then rechecked without
  `UPDATE_SNAPSHOTS`.
- `cargo test -p pine-cli conformance_metadata_references_existing_fixtures`
  passed.
- `cargo test -p pine-wasm entry_stop_limit` passed.
- `cargo test -p pine-runtime runtime_fixtures_match_incremental_append_execution`
  passed.
- `maturin build --manifest-path crates/pine-python/Cargo.toml --out dist`
  passed.
- `python3 -m pytest python/tests/test_bindings.py -q` passed with 52 tests
  after reinstalling the rebuilt wheel.
- `git diff --check` passed.
- `scripts/verify.sh` passed, including workspace formatting, clippy, tests,
  structure guardrail, wasm32 check, Python wheel rebuild/install, and Python
  tests.

## Slice 1: Long stop entries

Status: closed on 2026-06-02.

Goal: support `strategy.entry(..., stop=price)` for the current long-only,
one-net-position broker.

Context checked:

- `docs/STRATEGY_INTERNAL_EXECUTION_PLAN.md` Stage 5 scope;
- current `tests/fixtures/conformance.tsv` strategy entry row;
- current long limit entry implementation from Slice 0;
- `crates/pine-builtins/src/namespaces/strategy.rs`;
- `crates/pine-sema/src/analyzer/strategy.rs`;
- `crates/pine-runtime/src/builtins/strategy.rs`;
- current pending-entry book, same-calculation exit attachment, CLI, Python,
  and WASM coverage.

Implemented:

- added optional `stop` to the `strategy.entry` signature;
- accepted series/simple numeric `stop` values in strategy-mode entry calls;
- rejected non-positive const and runtime stop prices;
- left `limit + stop` entry stop-limit orders for Slice 2;
- reused the internal pending-entry book for long stop entries;
- kept stop entries from filling on the creation bar;
- filled eligible long stop entries at the stop price before script statements
  on a later historical bar when `high >= stop`;
- preserved same-calculation absolute `strategy.exit` attachment to the active
  pending stop entry id;
- hardened runtime optional argument lookup so named `stop` is not treated as a
  positional `limit`;
- added semantic, broker, runtime, CLI snapshot, Python host, and WASM host
  coverage.

Compatibility boundary:

- No public JSON schema or public strategy output shape changed.
- Pending stop entries are internal and emit no public order until filled.
- Stop-limit entries remained out of scope for Slice 1 and were handled in
  Slice 2. Short entries, reversals, pyramiding, cancellation APIs, and generic
  `strategy.order` remained out of scope.

Validation:

```text
cargo fmt --all --check
cargo test -p pine-builtins strategy_entry
cargo test -p pine-sema --test fixtures strategy_entry
cargo test -p pine-runtime entry_stop
cargo test -p pine-runtime pending_stop_entry
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli runtime_outputs_match_golden_snapshots
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli matrix_output_matches_golden_snapshot
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli matrix_output_matches_golden_snapshot
cargo test -p pine-cli conformance_metadata_references_existing_fixtures
cargo test -p pine-wasm entry_stop
cargo test -p pine-runtime runtime_fixtures_match_incremental_append_execution
maturin build --manifest-path crates/pine-python/Cargo.toml --out dist
python3 -m pip install --user --force-reinstall dist/pine_compat_runtime-0.1.0-cp310-abi3-manylinux_2_35_x86_64.whl
python3 -m pytest python/tests/test_bindings.py -q
git diff --check
scripts/verify.sh
```

Result:

- `cargo fmt --all --check` passed.
- `cargo test -p pine-builtins strategy_entry` passed.
- `cargo test -p pine-sema --test fixtures strategy_entry` passed.
- `cargo test -p pine-runtime entry_stop` passed.
- `cargo test -p pine-runtime pending_stop_entry` passed.
- CLI runtime and matrix snapshots were updated and then rechecked without
  `UPDATE_SNAPSHOTS`.
- `cargo test -p pine-cli conformance_metadata_references_existing_fixtures`
  passed.
- `cargo test -p pine-wasm entry_stop` passed.
- `cargo test -p pine-runtime runtime_fixtures_match_incremental_append_execution`
  passed.
- `maturin build --manifest-path crates/pine-python/Cargo.toml --out dist`
  passed.
- `python3 -m pytest python/tests/test_bindings.py -q` passed with 51 tests
  after reinstalling the rebuilt wheel.
- `git diff --check` passed.
- `scripts/verify.sh` passed, including workspace formatting, clippy, tests,
  structure guardrail, wasm32 check, Python wheel rebuild/install, and Python
  tests.
