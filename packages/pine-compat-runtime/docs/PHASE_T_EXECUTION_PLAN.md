# Phase T WASM Request Provider Execution Plan

Status: closed.

Phase T closes the remaining Phase F host-surface gap by adding deterministic
WASM request-bar dataset injection for the already supported provider-backed
`request.security` subset. It must not widen Pine request semantics, add new
request variants, change request alignment rules, or bump the public runtime
schema. The goal is host parity: a script that already runs through CLI and
Python with explicit requested bars should produce equivalent runtime JSON
through WASM.

Execute Phase T in small, mergeable slices. Each slice should leave the
workspace shippable and should keep host APIs, request provider behavior,
fixtures, tests, docs, and conformance notes in lockstep.

## Current Starting Point

The repository has closed Phase F for the current fixture-backed
`request.security` subset and Phase S for the current strategy subset.

Relevant current behavior:

- `tests/fixtures/conformance.tsv` marks `request.security` as `partial`,
  `request.security_lower_tf` as `unsupported`, and broad `request.*` as
  `unsupported`.
- Core runtime request support is host-neutral. `pine-runtime` exposes
  `RequestEnvironment`, `ChartContext`, `RequestKey`, `RequestTimeframe`,
  `RequestDataProvider`, and `InMemoryRequestDataProvider`.
- CLI injects requested bars with repeated
  `--request-bars SYMBOL:TIMEFRAME=bars.csv` options in
  `crates/pine-cli/src/commands/run.rs`.
- Python injects requested bars through a `request_bars` dictionary keyed by
  `SYMBOL:TIMEFRAME` in `crates/pine-python/src/lib.rs`.
- WASM currently exposes single-chart execution plus Phase J library-source
  JSON input in `crates/pine-wasm/src/lib.rs` and
  `crates/pine-wasm/src/library_sources.rs`.
- WASM has an explicit test named `request_host_data_is_documented_wasm_gap`
  that expects provider-backed request scripts to fail with the shared missing
  request data error.
- The shared request fixture is
  `tests/fixtures/request/request_security_host.pine`, with chart bars in
  `tests/fixtures/request/chart_1m.csv` and requested bars in
  `tests/fixtures/request/ibm_1m.csv` and
  `tests/fixtures/request/ibm_5m.csv`.
- The expected host-provider fixture values remain:
  - same timeframe: `30, 32, 34, 36, 38`
  - higher timeframe: `na, na, 100, 100, 200`

The current request host contract is deliberately deterministic: core crates do
not fetch network data, read host files, or depend on wall-clock time. Hosts
must supply immutable requested bar streams before runtime execution.

## Phase T Goal

Add a stable WASM JSON request-data host shape and wire it into the shared
runtime request provider contract.

The target host API surface is:

- `runScriptCsvWithRequestBars(source, barsCsv, requestBarsJson)`
- `runScriptCsvWithLibrariesAndRequestBars(source, barsCsv, librarySourcesJson, requestBarsJson)`
- `Program.runCsvWithRequestBars(barsCsv, requestBarsJson)`

The target JSON shape is an object whose keys match the CLI/Python request key
format and whose values are arrays of bar objects:

```json
{
  "NYSE:IBM:1": [
    {"time": 0, "open": 10, "high": 11, "low": 9, "close": 30, "volume": 100}
  ],
  "NYSE:IBM:5": [
    {"time": 300000, "open": 100, "high": 101, "low": 99, "close": 100, "volume": 500}
  ]
}
```

Rules:

- Keys use `SYMBOL:TIMEFRAME`; symbols may themselves contain `:`, so parsing
  must split on the last colon, matching CLI and Python.
- Values must be arrays of objects with numeric `time`, `open`, `high`, `low`,
  `close`, and `volume` fields.
- Bar validation must reuse `InMemoryRequestDataProvider::from_streams`, so
  duplicate keys observable by the parser, unsorted bars, and duplicate
  requested bar times produce the shared request-provider errors. If the JSON
  decoder collapses duplicate object keys before streams are built, record that
  limit in the parser tests instead of claiming duplicate-key detection.
- Empty request data (`{}`) keeps the existing no-provider behavior. Hosts that
  do not want to provide request data should continue using the existing
  no-request WASM APIs instead of relying on omitted arguments to the new
  `requestBarsJson` functions.
- The public runtime output remains `schemaVersion: 3`.
- The supported Pine request subset does not change.

Phase T is successful when the shared request fixture runs through WASM with
the same plot values as CLI/Python, malformed WASM host input has stable errors,
the previous documented WASM gap test is replaced by positive coverage, docs
describe the new host shape, and the release verification gate passes.

## Non-Goals

Do not include these in Phase T:

- New Pine request variants.
- `request.security_lower_tf` or lower-timeframe array returns.
- Optional `request.security` parameters, explicit `gaps`, explicit
  `lookahead`, currency conversion, ignore-invalid-symbol behavior, or
  advanced request families.
- Network fetching, filesystem access, browser APIs, host callbacks, or symbol
  discovery inside core crates or the WASM crate.
- A new runtime output schema, request metadata output, pending request records,
  or host-specific runtime result fields.
- Chart metadata JSON beyond the current default `ChartContext`. If a later
  phase needs host-provided chart symbol/timeframe metadata, design it as a
  separate host-contract phase.
- Duplicating request alignment, request caching, requested-context execution,
  or provider validation logic in WASM.

## Rules for Every Slice

- Keep the request provider contract host-neutral. WASM should parse host JSON
  and hand bars to `InMemoryRequestDataProvider`; it must not own request
  semantics.
- Preserve CLI and Python behavior.
- Keep `request.security_lower_tf` and broad `request.*` rows unsupported.
- Do not update `tests/fixtures/conformance.tsv` unless the feature claim
  text needs to mention WASM host parity; the Pine language subset is already
  partial and does not widen in this phase.
- Use the existing request integration fixture whenever possible instead of
  inventing a parallel WASM-only script.
- Add negative tests for malformed host input in the same slice that introduces
  parsing.
- Keep library-source JSON and request-bars JSON independent. A host should be
  able to supply either one without constructing a combined object.
- Run focused WASM request tests before broader checks.
- Run the full release verification gate before closing Phase T.

## Internal Structure Rules

Phase T should be a thin host binding phase.

- Add a request-bars parser module under `crates/pine-wasm/src/`, for example
  `request_bars.rs`.
- Keep `crates/pine-wasm/src/lib.rs` responsible for exported functions and
  high-level orchestration only.
- Reuse `parse_bars_csv` for chart CSV input, but parse requested bars from
  JSON objects so browser hosts do not need to generate temporary CSV text.
- Reuse `RequestKey::new`, `RequestTimeframe::parse`,
  `InMemoryRequestDataProvider::from_streams`, and `RequestEnvironment::new`.
- Use `ChartContext::default()` in Phase T unless a separate chart-metadata
  contract is explicitly opened.
- Keep JSON parsing errors human-readable and stable enough for tests, similar
  to the existing library-source host input errors.
- Treat roughly 800 lines in a production Rust file as a review trigger. If
  `crates/pine-wasm/src/lib.rs` starts growing host parsing details, move them
  into focused modules.

## Intended Module Layout

Use existing crate boundaries. No new crate is needed.

```text
crates/pine-wasm/src/
   lib.rs                exported functions, compile/run orchestration
   library_sources.rs    existing Phase J library-source JSON parser
   request_bars.rs       Phase T request-bars JSON parser and environment builder

crates/pine-runtime/src/request/
   provider.rs           existing RequestEnvironment and InMemoryRequestDataProvider
   timeframe.rs          existing RequestTimeframe parsing
   bars.rs               existing requested-bar validation
```

Ownership notes:

- WASM owns only host input decoding.
- `pine-runtime` remains the source of truth for request data validation,
  missing-data errors, alignment, requested-context evaluation, and caching.
- `pine-sema` remains unchanged unless a Phase T test reveals a real analyzer
  bug unrelated to host injection.
- CLI and Python remain unchanged unless docs or parity tests reveal an actual
  drift.

## Slice 0: Baseline Lock And Contract Confirmation

Goal: confirm that Phase T is a host parity phase, not a request semantics
phase.

Steps:

1. Read `docs/PHASE_F_AUDIT.md`, the request section in
   `docs/ARCHITECTURE.md`, and the request rows in
   `tests/fixtures/conformance.tsv`.
2. Confirm the current WASM gap test still fails with the shared missing-data
   message before adding a request-bars API.
3. Confirm CLI and Python still run the shared request fixture with the expected
   values.
4. Confirm `crates/pine-wasm/Cargo.toml` already has `serde_json`, so Phase T
   does not need a new parsing dependency.
5. Confirm `PUBLIC_RUNTIME_SCHEMA_VERSION` remains unchanged.
6. Confirm no new matrix status is required for Pine semantics.

Suggested commands:

```text
cargo test -p pine-wasm request_host_data_is_documented_wasm_gap
cargo test -p pine-cli runs_request_bars_integration_fixture
python3 -m pytest python/tests -q
cargo run -p pine-cli -- run tests/fixtures/request/request_security_host.pine \
  --bars tests/fixtures/request/chart_1m.csv \
  --request-bars NYSE:IBM:1=tests/fixtures/request/ibm_1m.csv \
  --request-bars NYSE:IBM:5=tests/fixtures/request/ibm_5m.csv
```

Exit criteria:

- The starting behavior is recorded in the slice notes or PR description.
- The selected JSON request-bars shape is confirmed.
- No compatibility claim is widened.

Slice 0 baseline notes, recorded 2026-05-31:

- `docs/PHASE_F_AUDIT.md`, `docs/ARCHITECTURE.md`, and
  `tests/fixtures/conformance.tsv` agree that `request.security` is partial,
  `request.security_lower_tf` and broad `request.*` are unsupported, and WASM
  request dataset injection is the remaining host-surface gap.
- `crates/pine-wasm/Cargo.toml` already depends on `serde_json`, and
  `PUBLIC_RUNTIME_SCHEMA_VERSION` remains `3`.
- WASM still uses the no-request `run_historical` path for `runScriptCsv`, and
  `request_host_data_is_documented_wasm_gap` still reports the shared missing
  request data error before any Phase T API is added.
- CLI and Python still use the shared request provider contract with
  `SYMBOL:TIMEFRAME` keys split on the last colon.
- The selected WASM `requestBarsJson` shape remains the object form documented
  above, using CLI/Python-compatible keys such as `NYSE:IBM:1` and arrays of
  bar objects with `time`, `open`, `high`, `low`, `close`, and `volume`.
- Baseline verification passed:
  `cargo test -p pine-wasm request_host_data_is_documented_wasm_gap`,
  `cargo test -p pine-cli runs_request_bars_integration_fixture`,
  `python3 -m pytest python/tests -q`,
  `cargo check -p pine-wasm --target wasm32-unknown-unknown`, and
  `cargo run -q -p pine-cli -- run tests/fixtures/request/request_security_host.pine --bars tests/fixtures/request/chart_1m.csv --request-bars NYSE:IBM:1=tests/fixtures/request/ibm_1m.csv --request-bars NYSE:IBM:5=tests/fixtures/request/ibm_5m.csv`.
  The CLI fixture output contained plot values `[30,32,34,36,38]` and
  `[null,null,100,100,200]`.
- `cargo run -q -p pine-cli -- matrix` still reports `request.security` as
  `partial` and `request.security_lower_tf` plus broad `request.*` as
  `unsupported`; no matrix or conformance status change is required for Slice 0.

## Slice 1: WASM Request-Bars JSON Parser

Goal: parse host request bars into the shared `RequestEnvironment` without
changing exported runtime functions yet.

Steps:

1. Add `crates/pine-wasm/src/request_bars.rs`.
2. Define a private deserialization shape for request bar objects with fields
   `time`, `open`, `high`, `low`, `close`, and `volume`.
3. Parse `requestBarsJson` as a JSON object mapping string keys to arrays of
   bar objects. Prefer a deterministic map type for stable test behavior.
4. Implement key parsing with `rsplit_once(':')`, matching CLI and Python.
5. Reject empty symbols with the same style of message used by CLI/Python:
   `request bars symbol must not be empty`.
6. Parse the timeframe with `RequestTimeframe::parse` and forward its error
   text.
7. Convert deserialized objects into `Vec<Bar>`.
8. Build an `InMemoryRequestDataProvider::from_streams(streams)` so runtime
   validation catches duplicate keys that survive host-input decoding,
   unsorted bars, and duplicate bar times.
9. Return `RequestEnvironment::default()` for an empty JSON object.
10. Add focused unit tests for:
    - exchange-prefixed symbols such as `NYSE:IBM:1`;
    - malformed JSON that is not an object;
    - invalid keys without a timeframe;
    - empty symbols;
    - invalid timeframe strings;
    - missing bar fields;
    - duplicate request keys if JSON parsing can observe them, or a documented
      test/fixture note explaining why duplicate object keys cannot be
      reliably detected after map-style JSON parsing;
    - unsorted requested bars;
    - duplicate requested bar times.

Exit criteria:

- WASM can build a `RequestEnvironment` from JSON in tests.
- Invalid host input fails before runtime execution with clear messages.
- Provider validation is reused, not copied.

Verification:

```text
cargo test -p pine-wasm request_bars
cargo fmt --check
```

## Slice 2: Export Direct WASM Request API

Goal: add a direct `source + chart CSV + request bars JSON` run function.

Steps:

1. Export `runScriptCsvWithRequestBars(source, barsCsv, requestBarsJson)` from
   `crates/pine-wasm/src/lib.rs`.
2. Add an internal helper that compiles the script through the existing
   `compile_program(analysis_input(source))` path.
3. Parse chart bars with the existing `parse_bars_csv` helper.
4. Parse request bars through the new `request_bars` module.
5. Execute with `run_historical_with_request_environment` instead of
   `run_historical`.
6. Serialize with the existing `public_runtime_result_json` helper.
7. Replace the old documented-gap test with a positive request fixture test
   that calls `run_script_csv_with_request_bars` and checks:
   - `schemaVersion` equals `PUBLIC_RUNTIME_SCHEMA_VERSION`;
   - one plot contains `"values":[30,32,34,36,38]`;
   - one plot contains `"values":[null,null,100,100,200]`.
8. Add a negative test that the same function reports missing data when a
   required request key is absent from `requestBarsJson`.

Exit criteria:

- The shared request fixture runs through the direct WASM request API.
- Runtime missing-data behavior remains the shared runtime error.
- Existing `runScriptCsv` behavior is unchanged.

Verification:

```text
cargo test -p pine-wasm request
cargo check -p pine-wasm --target wasm32-unknown-unknown
```

## Slice 3: Export Program Request API

Goal: support compiled WASM programs that can be reused with request data.

Steps:

1. Add `Program.runCsvWithRequestBars(barsCsv, requestBarsJson)` to the
   `#[wasm_bindgen] impl WasmProgram` block.
2. Add an internal `run_csv_with_request_environment_internal` helper if it
   avoids duplicating chart-bar parsing, runtime execution, and serialization.
3. Keep `Program.runCsv(barsCsv)` unchanged and still backed by the default
   no-request environment.
4. Add a unit test that compiles the shared request fixture with
   `compile_script`, then runs it through the program method with request data.
5. Add a unit test that a compiled program reports the same missing-data error
   when `requestBarsJson` omits the required key.

Exit criteria:

- Direct run and compiled-program run produce equivalent JSON for the request
  fixture.
- No HIR or runtime state is mutated by request environment reuse between runs.

Verification:

```text
cargo test -p pine-wasm run_csv_with_request_bars
cargo test -p pine-wasm request
```

## Slice 4: Combine Library Sources And Request Bars

Goal: allow Phase J library injection and Phase F request data injection in one
WASM run without creating a combined host-input schema.

Steps:

1. Export
   `runScriptCsvWithLibrariesAndRequestBars(source, barsCsv, librarySourcesJson, requestBarsJson)`.
2. Build the `AnalysisInput` with the existing
   `analysis_input_with_libraries(source, librarySourcesJson)` helper.
3. Compile through the existing `compile_program` path.
4. Parse request bars through the Phase T request-bars module.
5. Execute with `run_historical_with_request_environment`.
6. Add a runtime fixture or inline test source that imports a pure helper and
   uses `request.security` in the same script. Keep it side-effect-free and
   inside the already supported requested-expression subset.
7. Add malformed-host-input tests showing library JSON errors and request-bars
   JSON errors remain distinguishable.

Exit criteria:

- Hosts can combine library source injection and request data injection without
  a new wrapper object.
- Existing library-source tests still pass.
- Existing request-bars tests still pass.

Verification:

```text
cargo test -p pine-wasm library_source_json
cargo test -p pine-wasm request
cargo check -p pine-wasm --target wasm32-unknown-unknown
```

## Slice 5: Documentation And Public Contract Update

Goal: publish the WASM request-bars host shape and remove the documented gap.

Steps:

1. Update `README.md` under the WASM Binding section with:
   - the new function names;
   - the `requestBarsJson` object shape;
   - an example key such as `NYSE:IBM:1`;
   - a note that this is explicit host data injection, not network fetching.
2. Update `docs/ARCHITECTURE.md` request section to say CLI, Python, and WASM
   can all inject requested bar streams explicitly.
3. Update `docs/PHASE_F_AUDIT.md` maintenance tails to remove or revise the
   WASM request dataset injection gap.
4. Update `docs/RELEASE_NOTES.md` with a concise Unreleased entry.
5. Update this document if implementation details differ from the plan.
6. Only update `tests/fixtures/conformance.tsv` and the matrix snapshot if the
   request row notes need to mention WASM host parity. Do not change feature
   status solely for host parity.

Exit criteria:

- The README has enough information for a browser host to construct request
  data JSON.
- Architecture and Phase F audit no longer contradict the new WASM behavior.
- Release notes record the host-surface change.

Verification:

```text
cargo test -p pine-cli matrix_output_matches_golden_snapshot
git diff --check
```

## Slice 6: Phase T Audit And Closeout

Goal: close Phase T with evidence and keep future request work scoped.

Steps:

1. Add `docs/PHASE_T_AUDIT.md` after implementation is complete.
2. Record completed slices and the exact exported WASM APIs.
3. Record the final request-bars JSON contract.
4. Record positive fixture evidence and negative host-input tests.
5. Record unchanged public runtime schema and unchanged Pine request semantics.
6. Record remaining request maintenance tails:
   - lower-timeframe request arrays;
   - optional gaps/lookahead parameters;
   - chart metadata host JSON;
   - advanced request families;
   - requested-expression UDF/local alias widening if still unsupported.
7. Run focused verification and the full release gate.
8. Update `docs/LONG_TERM_EXECUTION_PLAN.md` only if request roadmap wording
   needs to reflect that WASM provider injection is no longer a host-surface
   gap.

Exit criteria:

- `docs/PHASE_T_AUDIT.md` records closure evidence.
- All WASM request APIs are tested.
- CLI/Python/WASM request host surfaces are documented as synchronized for the
  supported provider-backed subset.
- The full release gate passes.

Verification:

```text
cargo fmt --check
cargo test -p pine-wasm request
cargo test -p pine-cli runs_request_bars_integration_fixture
python3 -m pytest python/tests -q
cargo check -p pine-wasm --target wasm32-unknown-unknown
git diff --check
scripts/verify.sh
```

## Recommended Execution Order

Use this order unless a discovered blocker requires reordering:

1. Baseline lock and contract confirmation.
2. WASM request-bars JSON parser.
3. Direct `runScriptCsvWithRequestBars` API.
4. Compiled `Program.runCsvWithRequestBars` API.
5. Combined library-source plus request-bars API.
6. Documentation and public contract updates.
7. Phase T audit and closeout.

## Phase T Closeout Checklist

Complete this checklist before treating Phase T as closed. If an item is
intentionally deferred, record the reason and risk in `docs/PHASE_T_AUDIT.md`.

- [x] WASM parses request-bars JSON into the shared `RequestEnvironment`.
- [x] WASM accepts exchange-prefixed symbols by splitting request keys on the
      last colon.
- [x] WASM rejects malformed request-bars JSON with stable host-input errors.
- [x] WASM reuses shared requested-bar validation for duplicate and unsorted
      bars.
- [x] `runScriptCsvWithRequestBars` runs the shared request fixture.
- [x] `Program.runCsvWithRequestBars` runs the shared request fixture.
- [x] Library-source injection and request-bars injection work together.
- [x] The previous documented WASM provider-data gap test has been replaced by
      positive host parity coverage.
- [x] README documents the request-bars JSON shape and exported WASM APIs.
- [x] Architecture, Phase F audit, and release notes agree with the new host
      surface.
- [x] Runtime output remains `schemaVersion: 3`.
- [x] `request.security_lower_tf` and broad `request.*` remain unsupported.
- [x] `docs/PHASE_T_AUDIT.md` records verification evidence and remaining
      request tails.
- [x] `scripts/verify.sh` passes.
