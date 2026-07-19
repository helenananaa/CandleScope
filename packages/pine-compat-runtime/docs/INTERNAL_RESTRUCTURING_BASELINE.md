# Internal Restructuring Baseline

Recorded for `docs/INTERNAL_RESTRUCTURING_PLAN.md` Phase 0.

- Date: 2026-05-22T18:44:13+08:00
- Baseline commit: `3e9b4b6`
- Scope: internal restructuring only. Public behavior, schemas, fixtures, and
  conformance claims must remain stable during mechanical move phases.

## Current Hotspot Sizes

```text
  17117 crates/pine-runtime/src/lib.rs
   7750 crates/pine-sema/src/lib.rs
   3972 crates/pine-builtins/src/lib.rs
```

Other production Rust files over 800 lines at baseline:

```text
   1137 crates/pine-syntax/src/parser.rs
    803 crates/pine-cli/src/main.rs
```

## Public API Names To Preserve

The following crate-root public names must remain importable from their current
crates unless a later compatibility change explicitly documents otherwise.

### `pine-runtime`

- Types: `PineValue`, `Bar`, `BarUpdateKind`, `BarUpdate`, `SeriesStore`,
  `RuntimeResult`, `RuntimeProfiledResult`, `RuntimeProfile`,
  `HistoryRetentionMode`, `PlotSeries`, `ColorSeries`, `PlotCharSeries`,
  `PlotShapeSeries`, `PlotArrowSeries`, `PlotBarSeries`, `PlotCandleSeries`,
  `HLineOutput`, `FillOutput`, `RuntimeDiagnostic`, `RuntimeError`,
  `HistoricalRuntime`, `RealtimeRuntime`.
- Functions: `public_runtime_result_json`,
  `public_runtime_profiled_result_json`, `run_historical`,
  `run_historical_profiled`.

### `pine-sema`

- Types: `Analysis`, `CompatibilityReport`, `FeatureUse`,
  `UnsupportedFeature`, `CompileCache`, `CompileCacheStats`.
- Functions: `analyze_source`.

### `pine-builtins`

- Types: `BuiltinSignature`, `BuiltinPhase`, `BuiltinParam`, `Accepts`,
  `ReturnSpec`, `NamedColor`.
- Functions: `is_phase_1_builtin`, `get_phase_1_builtin`, `named_color`,
  `named_float_constant`, `named_int_constant`,
  `builtin_series_value_type`, `named_string_constant`,
  `fallback_bool_for_arg`, `color_return_for_arg`, `change_return_for_arg`,
  `input_return_for_arg`.

## Baseline Verification

Required Phase 0 verification:

```text
cargo fmt --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
```

Observed results:

- `cargo fmt --check`: passed.
- `cargo clippy --workspace --all-targets -- -D warnings`: passed.
- `cargo test --workspace`: passed.

Workspace test summary from the baseline run:

- `pine-cli`: 15 passed.
- `pine-runtime`: 225 unit tests passed.
- `pine-runtime` integration tests: incremental 1 passed, profile fixtures 4
  passed, realtime 5 passed.
- `pine-sema`: 181 unit tests passed and 13 fixture tests passed.
- `pine-syntax`: 27 unit tests passed and 1 fixture test passed.
- `pine-wasm`: 3 unit tests passed.
- Doc tests for workspace crates passed.

No currently failing tests are documented for this baseline.

## Snapshot And Conformance Evidence

The existing snapshot and conformance metadata checks are part of the baseline:

- `cargo test -p pine-cli runtime_outputs_match_golden_snapshots`: passed.
- `cargo test -p pine-cli matrix_output_matches_golden_snapshot`: passed.
- `cargo test -p pine-cli conformance_metadata_references_existing_fixtures`:
  passed.
- `cargo run -q -p pine-cli -- matrix --format json` matches
  `tests/snapshots/matrix.json` with no diff.

The golden snapshot ownership remains in `tests/snapshots/README.md`.

## Mechanical Move Checklist

Use this checklist for each restructuring commit or pull request:

- Public crate-root imports listed above still compile or are re-exported from
  the facade.
- Public JSON output schemas and field names are unchanged.
- CLI output, Python binding behavior, and WASM binding behavior are unchanged
  unless the phase explicitly touches those surfaces and records the reason.
- Fixture outputs, snapshots, diagnostics, compatibility reports, runtime
  profiles, incremental execution behavior, and realtime rollback behavior are
  unchanged.
- Private helpers did not become public only to make tests compile.
- Each moved item has an obvious long-term owner module.
- `cargo fmt --check`, `cargo clippy --workspace --all-targets -- -D warnings`,
  and `cargo test --workspace` pass before moving to the next phase.
