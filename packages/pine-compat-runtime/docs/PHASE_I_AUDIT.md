# Phase I Audit: `varip` and Intrabar Persistence

Status: closed for the fixture-backed claimed subset.

Phase I delivered the runtime, semantic-analysis, and documentation boundary for
`varip` intrabar persistence without adding host-specific realtime APIs. The
claimed surface is intentionally narrow and remains tied to the compatibility
matrix in `tests/fixtures/conformance.tsv`.

## Delivered Surface

- Global and local scalar `varip` declarations for `int`, `float`, `bool`,
  `string`, `color`, `chart.point`, and `na`.
- Local scalar declaration-site storage inside `if`, `for`, `while`, and
  lowered user-defined function bodies, with independent storage per lowered UDF
  callsite.
- Historical execution for the supported subset, where `varip` behaves like
  `var` because historical bars have one committed evaluation.
- Realtime forming-bar execution where supported scalar `varip` slots persist
  across repeated forming updates while ordinary `var`, outputs, drawing
  objects, request caches, callsite state, non-`varip` arrays, and dynamic
  history reads roll back to confirmed state, including ordinary
  `var chart.point` field mutation.
- Scalar typed-array `varip` declarations for float, int, bool, string, and
  color array ids, plus `chart.point` typed-array `varip` declarations, using
  either `array<type>` or `type[]` declaration syntax. The retained intrabar
  state includes backing array contents, element kind, branch-local declaration
  sites, and `array.copy` boundaries.
- Explicitly typed same-local scalar-field UDT `varip` values initialized from
  `na`, same-UDT constructors, or fixture-backed same-UDT ternary/switch/if/for expressions,
  with intrabar value-clone handoff and scalar field mutation writeback.
- Direct-constructor-inferred same-local scalar-field UDT `varip` values, using
  the same intrabar value-clone handoff.
- Semantic diagnostics for unsupported `varip` value families, including a
  dedicated diagnostic for drawing object ids.

## Fixture Evidence

Compatibility matrix rows:

- `varip`: `partial`
- `realtime forming rollback`: `partial`

Runtime fixtures:

- `tests/fixtures/runtime/varip_scalar.pine`
- `tests/fixtures/runtime/varip_local.pine`
- `tests/fixtures/runtime/varip_array.pine`
- `tests/fixtures/runtime/chart_point_varip.pine`

Realtime fixtures:

- `tests/fixtures/realtime/varip_scalar.pine`
- `tests/fixtures/realtime/varip_local.pine`
- `tests/fixtures/realtime/varip_array.pine`
- `tests/fixtures/realtime/chart_point_varip.pine`

Semantic fixtures:

- `tests/fixtures/sema/unsupported_varip.pine`
- `tests/fixtures/sema/unsupported_varip_drawing.pine`

The matrix output reports the same fixture paths and notes that drawing ids,
tuples, and other value families remain unsupported with semantic diagnostics.

## Host Surface Review

The CLI, Python binding, and WASM binding all reuse Rust semantic analysis for
compile/analyze entry points. Their historical run entry points compile to the
same HIR and execute through the existing historical runtime path. Phase I did
not add a public realtime host API; the realtime behavior is covered by Rust
runtime fixtures.

Manual host checks on the closeout workspace:

- `cargo run -q -p pine-cli -- matrix --format text` reports `varip` and
  `realtime forming rollback` as partial with the Phase I fixture paths.
- `cargo run -q -p pine-cli -- run tests/fixtures/runtime/varip_scalar.pine --bars tests/fixtures/runtime/bars.csv`
  completes with `schemaVersion: 2` runtime JSON.
- `cargo run -q -p pine-cli -- run tests/fixtures/runtime/varip_array.pine --bars tests/fixtures/runtime/bars.csv`
  completes with `schemaVersion: 2` runtime JSON.
- `cargo run -q -p pine-cli -- analyze tests/fixtures/sema/unsupported_varip_drawing.pine`
  emits `E_UNSUPPORTED_FEATURE` for `varip` drawing object ids.
- `cargo run -q -p pine-cli -- analyze tests/fixtures/runtime/varip_array.pine`
  reports zero diagnostics.

## Verification

The closeout workspace passed:

```text
scripts/verify.sh
```

That release gate includes `cargo fmt --check`,
`cargo clippy --workspace --all-targets -- -D warnings`,
`cargo test --workspace`, `python3 scripts/check_structure.py`,
`cargo check -p pine-wasm --target wasm32-unknown-unknown`,
`maturin build --manifest-path crates/pine-python/Cargo.toml --out dist`,
wheel reinstall through `python3 -m pip install --force-reinstall dist/*.whl`,
and `python3 -m pytest python/tests`.

## Maintenance Tails

- Drawing object ids remain rejected for `varip`. Supporting them requires an
  object-store handoff design for labels, lines, boxes, and tables instead of
  retaining ids alone.
- Tuple `varip`, maps, matrices, non-constructor-inferred or nested-field
  user-defined types, imports, UDT arrays, object arrays, generic arrays, and
  other unimplemented value families remain outside the Phase I claim.
- Array mutation inside UDFs remains rejected by the existing side-effect rules.
- Python and WASM expose historical compile/analyze/run surfaces only; no
  realtime repeated-forming-update host API is claimed.

## Closeout Checklist

- `varip` has semantic diagnostics for accepted and rejected value families.
- HIR storage metadata distinguishes ordinary `var` from `varip`.
- Historical execution has documented `varip` behavior.
- Realtime repeated forming updates preserve claimed `varip` state while
  ordinary rollback continues to work.
- Incremental append execution matches full historical execution for historical
  `varip` fixtures through the runtime test suite.
- Scalar and scalar typed-array subsets have runtime fixtures, realtime
  fixtures, conformance rows, and docs.
- Unsupported tails remain explicit in docs and diagnostics.
- No production Rust file hotspot was added during Phase I closeout.
- `scripts/verify.sh` passes on the closeout workspace.
