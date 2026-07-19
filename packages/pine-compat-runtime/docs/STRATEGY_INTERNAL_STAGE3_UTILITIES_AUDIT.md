# Strategy Internal Stage 3 Utilities Audit

Status: closed.

This audit tracks `docs/STRATEGY_INTERNAL_EXECUTION_PLAN.md` Stage 3: Small
Independent Strategy Utilities. Stage 3 should add narrow helpers that fit the
current one-net-long broker without requiring a richer order book.

## Slice 0: `strategy.close_all()`

Status: closed on 2026-06-02.

Goal: add the smallest useful close helper for the current supported broker:
`strategy.close_all()` closes the current long position without requiring an
entry id.

Context checked:

- `docs/STRATEGY_INTERNAL_EXECUTION_PLAN.md` Stage 3 scope;
- current `tests/fixtures/conformance.tsv` strategy rows;
- `crates/pine-builtins/src/namespaces/strategy.rs`;
- `crates/pine-sema/src/analyzer/strategy.rs`;
- `crates/pine-runtime/src/builtins/strategy.rs`;
- `crates/pine-runtime/src/strategy/broker/fills.rs`;
- existing `strategy.close` runtime, CLI, Python, and WASM coverage.

Implemented:

- added a no-argument `strategy.close_all()` builtin signature;
- accepted `strategy.close_all()` only in strategy-mode scripts;
- kept indicator-mode calls on the existing `E_STRATEGY_MODE` diagnostic path;
- added broker/runtime dispatch that closes the current supported long position
  at the current bar close;
- kept flat and already-closed calls as no-op;
- reused the existing close path so pending exits for the closed entry are
  cancelled and public strategy output shape remains unchanged;
- added semantic fixtures, runtime fixture, CLI snapshot coverage, Python host
  coverage, and WASM host coverage.

Compatibility boundary:

- No public JSON schema or public pending-order shape changed.
- `strategy.close_all()` only applies to the current one-net-long supported
  broker. There is no partial close, close ordering across multiple entries,
  short support, pyramiding support, or generic cancellation API.
- `strategy.cancel`, `strategy.cancel_all`, risk APIs, and rich trade namespace
  functions remain unsupported.

Validation:

```text
cargo fmt --all --check
cargo test -p pine-builtins strategy_close_all
cargo test -p pine-sema strategy_close_all
cargo test -p pine-runtime strategy_close_all
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli runtime_outputs_match_golden_snapshots
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli matrix_output_matches_golden_snapshot
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli matrix_output_matches_golden_snapshot
cargo test -p pine-wasm close_all
python3 -m pytest python/tests/test_bindings.py -q
cargo test -p pine-runtime runtime_fixtures_match_incremental_append_execution
git diff --check
scripts/verify.sh
```

Result:

- `cargo fmt --all --check` passed.
- `cargo test -p pine-builtins strategy_close_all` passed.
- `cargo test -p pine-sema strategy_close_all` passed.
- `cargo test -p pine-runtime strategy_close_all` passed.
- CLI runtime and matrix snapshots were updated and then rechecked without
  `UPDATE_SNAPSHOTS`.
- `cargo test -p pine-wasm close_all` passed.
- `python3 -m pytest python/tests/test_bindings.py -q` passed after rebuilding
  and reinstalling the Python wheel for the new runtime dispatch.
- `cargo test -p pine-runtime runtime_fixtures_match_incremental_append_execution`
  passed.
- `git diff --check` passed.
- `scripts/verify.sh` passed, including workspace formatting, clippy, tests,
  structure guardrail, wasm32 check, Python wheel rebuild/install, and Python
  tests.

Next slice candidate:

- Add win/loss/even trade count variables for the current closed-trade list.

## Slice 1: trade outcome count variables

Status: closed on 2026-06-02.

Goal: add the smallest reporting helpers for closed-trade outcomes:
`strategy.wintrades`, `strategy.losstrades`, and `strategy.eventrades`.

Context checked:

- `docs/STRATEGY_INTERNAL_EXECUTION_PLAN.md` Stage 3 scope;
- current `tests/fixtures/conformance.tsv` strategy state rows;
- existing Phase O `strategy.closedtrades` and `strategy.opentrades` paths;
- `crates/pine-builtins/src/constants/series.rs`;
- `crates/pine-sema/src/analyzer/strategy.rs`;
- `crates/pine-runtime/src/builtins/variables.rs`;
- `crates/pine-runtime/src/strategy/broker/accounting.rs`;
- existing runtime, CLI, Python, and WASM trade-count coverage.

Implemented:

- added read-only series int builtin values for `strategy.wintrades`,
  `strategy.losstrades`, and `strategy.eventrades`;
- kept the variables strategy-mode only, requested-context unsupported, and
  direct mutation rejected through the existing strategy state variable paths;
- derived counts from the existing closed-trade list using positive, negative,
  and zero realized profit;
- kept public strategy JSON unchanged, with scripts observing the values only
  through ordinary outputs such as `plot`;
- added semantic fixtures, a 9-bar runtime fixture that produces one winning,
  one losing, and one even trade, CLI snapshot coverage, Python host coverage,
  and WASM host coverage.

Compatibility boundary:

- No public JSON schema or host strategy output shape changed.
- The counts only cover the current long-only broker's closed trades.
- Rich `strategy.closedtrades.*` and `strategy.opentrades.*` namespace
  functions, `strategy.max_drawdown`, and broader reporting metrics remain
  unsupported.

Validation:

```text
cargo fmt --all --check
cargo test -p pine-builtins strategy_trade_count
cargo test -p pine-runtime trade_outcome
cargo test -p pine-sema --test fixtures strategy
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli runtime_outputs_match_golden_snapshots
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli matrix_output_matches_golden_snapshot
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli matrix_output_matches_golden_snapshot
cargo test -p pine-cli conformance_metadata_references_existing_fixtures
cargo test -p pine-wasm trade_outcome
cargo test -p pine-runtime runtime_fixtures_match_incremental_append_execution
maturin build --manifest-path crates/pine-python/Cargo.toml --out dist
python3 -m pip install --user --force-reinstall dist/pine_compat_runtime-0.1.0-cp310-abi3-manylinux_2_35_x86_64.whl
python3 -m pytest python/tests/test_bindings.py -q
scripts/verify.sh
```

Result:

- `cargo fmt --all --check` passed.
- `cargo test -p pine-builtins strategy_trade_count` passed.
- `cargo test -p pine-runtime trade_outcome` passed.
- `cargo test -p pine-sema --test fixtures strategy` passed.
- CLI runtime and matrix snapshots were updated and then rechecked without
  `UPDATE_SNAPSHOTS`.
- `cargo test -p pine-cli conformance_metadata_references_existing_fixtures`
  passed.
- `cargo test -p pine-wasm trade_outcome` passed.
- `cargo test -p pine-runtime runtime_fixtures_match_incremental_append_execution`
  passed.
- `maturin build --manifest-path crates/pine-python/Cargo.toml --out dist`
  passed.
- `python3 -m pytest python/tests/test_bindings.py -q` passed with 48 tests
  after reinstalling the rebuilt wheel.
- `git diff --check` passed.
- `scripts/verify.sh` passed, including workspace formatting, clippy, tests,
  structure guardrail, wasm32 check, Python wheel rebuild/install, and Python
  tests.

Next slice candidate:

- Stage 3 scope is closed. Continue with Stage 4 `qty + qty_percent`
  precedence if the strategy roadmap remains the next priority.
