# Phase J Audit: Libraries, Imports, User Types, and Methods

Status: closed for the fixture-backed claimed subset.

Phase J delivered a host-neutral source graph, a narrow executable import
subset, local scalar-field user-defined types, and pure local UDT methods. The
claim is intentionally limited to behavior covered by
`tests/fixtures/conformance.tsv`, host binding tests, runtime fixtures, semantic
fixtures, and the compatibility matrix.

## Delivered Surface

- `AnalysisInput` accepts one root source plus deterministic host-provided
  library sources. `SourceGraph` assigns root source id `0` and sorted library
  source ids by import key.
- Compile cache keys include the root source name/text and every
  host-provided library key/name/text.
- CLI accepts repeated `--library-source KEY=path.pine` options for `analyze`
  and `run`.
- Python accepts `library_sources={"KEY": "source text"}` on
  `compile_script`, `analyze_script`, and `run_script`.
- WASM exposes `compileScriptWithLibraries`, `analyzeScriptWithLibraries`, and
  `runScriptCsvWithLibraries` with deterministic JSON library source maps.
- Exact-key `import ... as alias` supports exported const expressions and pure
  exported functions.
- Imported pure functions lower through the existing inlined UDF body path and
  keep independent callsite state.
- Local scalar-field UDTs support top-level `type` declarations,
  `Type.new(...)` construction, field reads, ordinary variables, and `var`
  persistence.
- UDT runtime values roll back through ordinary `var` confirmed-state semantics
  during realtime forming updates. Local scalar fields can be reassigned
  outside method bodies, including branch, `for` loop, and UDF-local variables.
- Pure user-defined methods on local UDT receivers with scalar parameters lower
  through the existing inlined UDF body path with the receiver as the first
  internal argument.

## Fixture Evidence

Compatibility matrix rows:

- `import`: `partial`
- `library`: `unsupported`
- `export`: `unsupported`
- `user-defined types`: `partial`
- `user-defined methods`: `partial`

Runtime fixtures:

- `tests/fixtures/runtime/import.pine`
- `tests/fixtures/runtime/import_state.pine`
- `tests/fixtures/runtime/user_types.pine`
- `tests/fixtures/runtime/user_type_functions.pine`
- `tests/fixtures/runtime/user_methods.pine`

Realtime fixtures:

- `tests/fixtures/realtime/user_type_var_rollback.pine`

Library fixtures:

- `tests/fixtures/libraries/import_lib.pine`
- `tests/fixtures/libraries/import_udt_lib.pine`

Semantic fixtures:

- `tests/fixtures/sema/unsupported_import.pine`
- `tests/fixtures/sema/unsupported_library.pine`
- `tests/fixtures/sema/unsupported_export.pine`
- `tests/fixtures/sema/unsupported_user_type.pine`
- `tests/fixtures/sema/unsupported_user_type_varip.pine`
- `tests/fixtures/sema/unsupported_user_type_field_mutation.pine`
- `tests/fixtures/sema/unsupported_user_method.pine`
- `tests/fixtures/sema/unsupported_user_method_side_effect.pine`
- `tests/fixtures/sema/unsupported_non_array_method.pine`

The matrix snapshot records the same fixture paths and keeps unsupported tails
visible in the row notes.

## Host Surface Review

All host surfaces route library source input into the shared `AnalysisInput`
contract. Core crates do not read library files, fetch remote registry data, or
perform host lookup.

Manual and automated host coverage on the closeout workspace:

- `cargo test -p pine-cli library_source`
- `cargo test -p pine-cli runs_imported_function_with_library_source_integration_fixture`
- `python3 -m pytest python/tests/test_bindings.py -q -k "user_type_functions_fixture_contract or user_methods_fixture_contract"`
- `python3 -m pytest python/tests/test_bindings.py -q -k "unsupported_user_type_field_fixture or unsupported_user_method_fixture"`
- `python3 -m pytest python/tests/test_bindings.py -q -k "unsupported_user_type_varip_fixture or unsupported_user_type_field_mutation_fixture or unsupported_user_method_side_effect_fixture or unsupported_non_array_method_fixture"`
- `python3 -m pytest python/tests`
- `cargo test -p pine-wasm library_source_json`
- `cargo test -p pine-wasm run_script_csv_returns_user_type_functions_fixture_contract`
- `cargo test -p pine-wasm run_script_csv_returns_user_methods_fixture_contract`
- `cargo test -p pine-wasm analyze_script_reports_unsupported_user`
- `cargo test -p pine-wasm analyze_script_reports_unsupported_non_array_method_fixture`
- `cargo run -p pine-cli -- matrix`

WASM request-bar dataset injection remains a separate Phase F gap. It does not
affect Phase J library source injection, which is covered by WASM tests.

## Diagnostics

The supported subset preserves diagnostic-only boundaries:

- missing host library source: `E_IMPORT_MISSING_LIBRARY`
- missing import alias: `E_IMPORT_ALIAS_REQUIRED`
- duplicate aliases: `E_IMPORT_DUPLICATE_ALIAS`
- invalid library declarations: `E_IMPORT_INVALID_LIBRARY`
- duplicate exports: `E_IMPORT_DUPLICATE_EXPORT`
- duplicate exported UDT names: `E_IMPORT_DUPLICATE_EXPORT`
- duplicate exported UDT/const names: `E_IMPORT_DUPLICATE_EXPORT`
- duplicate exported UDT/function names: `E_IMPORT_DUPLICATE_EXPORT`
- private or unknown imported symbols: `E_IMPORT_PRIVATE_SYMBOL` and
  `E_IMPORT_UNKNOWN_EXPORT`
- import cycles: `E_IMPORT_CYCLE`
- exported series constants: `E_IMPORT_CONST_VALUE`
- side-effecting exported functions: `E_IMPORT_FUNCTION_SIDE_EFFECT`
- recursive imported functions: `E_RECURSIVE_FUNCTION`
- exported imported UDT constructors: `E_IMPORT_UNSUPPORTED_UDT`
- private imported UDT constructors: `E_IMPORT_PRIVATE_SYMBOL`
- imported methods: `E_UNKNOWN_METHOD` for receiver-style lookup and
  `E_IMPORT_UNSUPPORTED_METHOD` for alias-qualified access
- unsupported UDT field types: `E_UDT_FIELD_TYPE`
- unsupported UDT forms: `E_UNSUPPORTED_FEATURE`
- unsupported UDT field mutation: `E_UNSUPPORTED_FEATURE`
- unsupported UDT `varip`: `E_UNSUPPORTED_FEATURE`
- unsupported user method declarations and side effects:
  `E_METHOD_RECEIVER_TYPE` or `E_UNSUPPORTED_FEATURE`

## Verification

Slice-level verification included focused gates for each delivered subset:

```text
cargo test -p pine-sema import
cargo test -p pine-sema user_types
cargo test -p pine-sema methods
cargo test -p pine-runtime import
cargo test -p pine-runtime user_types
cargo test -p pine-runtime methods
cargo test -p pine-runtime --test realtime user_type
cargo test -p pine-cli library_source
cargo test -p pine-wasm library_source_json
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli matrix_output_matches_golden_snapshot
```

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

The structural guardrail passed with no Phase J production Rust hotspot over
the configured limit.

## Maintenance Tails

- Remote library registry lookup, version resolution, package ownership,
  filesystem lookup inside core crates, and network access remain outside the
  host-neutral source graph.
- Re-exports, wildcard imports, unaliased imports, imported UDT identity,
  imported constructors, imported methods, and source-graph-wide method tables
  remain unsupported. Private library UDTs remain non-exported symbols.
- Side-effecting exported functions, library output declarations, library
  inputs, strategy-library interactions, and cross-library runtime state
  semantics remain unsupported.
- UDT field mutation inside functions or methods, UDT history references, UDT
  `varip`, nested UDT fields, recursive UDTs, UDT arrays, generic UDT fields,
  and imported UDT values remain unsupported.
- User-defined methods remain limited to pure methods on local UDT receivers
  with scalar parameters; recursive methods, generic methods, imported methods,
  side effects, and unsupported receiver families remain rejected.
- Remote source identity and rich cross-file diagnostic presentation can be
  widened later without changing the current deterministic source graph
  contract.

## Closeout Checklist

- Source graph behavior is deterministic and host-provided only.
- Import/library support has positive runtime fixtures and negative diagnostic
  fixtures for the exact claimed subset.
- CLI, Python, and WASM host contracts are synchronized for library source
  injection.
- Imported functions obey local UDF side-effect, recursion, and callsite-state
  rules.
- UDT construction, field access, persistence, history, rollback, and mutation
  boundaries are explicit and fixture-backed.
- User-defined method resolution is receiver-typed and does not regress array
  method syntax.
- Matrix rows prevent accidental widening of import, UDT, or method claims.
- Docs and release notes record unsupported tails.
- `scripts/verify.sh` passes on the closeout workspace.
