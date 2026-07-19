# Strategy Internal Stage 4 Qty Precedence Audit

Status: closed.

This audit tracks `docs/STRATEGY_INTERNAL_EXECUTION_PLAN.md` Stage 4:
Pine-Compatible `qty + qty_percent`.

## Slice 0: `qty` wins over `qty_percent`

Status: closed on 2026-06-02.

Goal: accept supported `strategy.exit` calls that supply both `qty` and
`qty_percent`, with fixed `qty` determining the reserved or filled quantity.

Context checked:

- `docs/STRATEGY_INTERNAL_EXECUTION_PLAN.md` Stage 4 scope;
- current `tests/fixtures/conformance.tsv` strategy exit row;
- `crates/pine-sema/src/analyzer/strategy.rs`;
- `crates/pine-runtime/src/builtins/strategy.rs`;
- existing fixed-`qty`, `qty_percent`, bracket, trailing, reservation, CLI,
  Python, and WASM coverage.

Implemented:

- removed the semantic diagnostic that rejected `qty + qty_percent`;
- kept unsupported trigger-shape diagnostics unchanged, including same-side
  pairs, 3+ triggers, invalid trailing forms, and missing-entry forms;
- changed runtime quantity selection so `qty` wins when both `qty` and
  `qty_percent` are present;
- added supported semantic fixtures for single-trigger, bracket, and trailing
  `qty + qty_percent` forms;
- added runtime tests proving single-trigger, bracket, and trailing forms fill
  using `qty=0.75` rather than `qty_percent=25` on a size-2 position;
- added runtime fixtures, CLI snapshot coverage, Python host coverage, and WASM
  host coverage.

Compatibility boundary:

- No public JSON schema or public strategy output shape changed.
- `qty + qty_percent` is accepted only on trigger shapes that already support
  fixed `qty` and `qty_percent` independently.
- Multiple-entry, pyramiding, short exposure, omitted-quantity multiple
  reservations, and unsupported trigger families remain out of scope.

Validation:

```text
cargo fmt --all --check
cargo test -p pine-sema --test fixtures strategy_exit
cargo test -p pine-runtime qty_and_qty_percent
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli runtime_outputs_match_golden_snapshots
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli matrix_output_matches_golden_snapshot
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli matrix_output_matches_golden_snapshot
cargo test -p pine-cli conformance_metadata_references_existing_fixtures
cargo test -p pine-wasm qty_precedence
cargo test -p pine-runtime runtime_fixtures_match_incremental_append_execution
maturin build --manifest-path crates/pine-python/Cargo.toml --out dist
python3 -m pip install --user --force-reinstall dist/pine_compat_runtime-0.1.0-cp310-abi3-manylinux_2_35_x86_64.whl
python3 -m pytest python/tests/test_bindings.py -q
git diff --check
scripts/verify.sh
```

Result:

- `cargo fmt --all --check` passed.
- `cargo test -p pine-sema --test fixtures strategy_exit` passed.
- `cargo test -p pine-runtime qty_and_qty_percent` passed.
- CLI runtime and matrix snapshots were updated and then rechecked without
  `UPDATE_SNAPSHOTS`.
- `cargo test -p pine-cli conformance_metadata_references_existing_fixtures`
  passed.
- `cargo test -p pine-wasm qty_precedence` passed.
- `cargo test -p pine-runtime runtime_fixtures_match_incremental_append_execution`
  passed.
- `maturin build --manifest-path crates/pine-python/Cargo.toml --out dist`
  passed.
- `python3 -m pytest python/tests/test_bindings.py -q` passed with 49 tests
  after reinstalling the rebuilt wheel.
- `git diff --check` passed.
- `scripts/verify.sh` passed, including workspace formatting, clippy, tests,
  structure guardrail, wasm32 check, Python wheel rebuild/install, and Python
  tests.
