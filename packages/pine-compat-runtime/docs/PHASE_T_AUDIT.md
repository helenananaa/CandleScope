# Phase T Audit: WASM Request Provider Host Parity

Status: closed for the current provider-backed `request.security` WASM host
parity subset.

Phase T closes the remaining Phase F WASM host-surface gap by adding explicit,
deterministic request-bars JSON injection for the already supported
provider-backed `request.security` subset. It does not widen Pine request
semantics, add new request variants, change request alignment rules, or bump
the public runtime schema.

## Completed Slices

- Slice 0 locked the Phase F/S baseline, confirmed the existing WASM
  diagnostic-only gap, verified CLI/Python request fixture parity, selected the
  JSON host shape, and kept conformance claims unchanged.
- Slice 1 added `crates/pine-wasm/src/request_bars.rs`, parsing
  `requestBarsJson` into the shared `RequestEnvironment` and testing malformed
  host input, key parsing, empty objects, duplicate JSON key collapse behavior,
  unsorted bars, and duplicate requested bar times.
- Slice 2 added `runScriptCsvWithRequestBars(source, barsCsv,
  requestBarsJson)`, replaced the old documented-gap WASM test with positive
  request fixture coverage, and preserved shared runtime missing-data errors.
- Slice 3 added `Program.runCsvWithRequestBars(barsCsv, requestBarsJson)`,
  verified compiled-program output matches the direct API, and checked repeated
  compiled runs do not mutate HIR or request state.
- Slice 4 added
  `runScriptCsvWithLibrariesAndRequestBars(source, barsCsv,
  librarySourcesJson, requestBarsJson)`, verifying library-source JSON and
  request-bars JSON remain independent host inputs.
- Slice 5 documented the WASM request-bars host shape in `README.md`,
  `docs/ARCHITECTURE.md`, `docs/PHASE_F_AUDIT.md`, and
  `docs/RELEASE_NOTES.md` without changing conformance or matrix status.
- Slice 6 added this audit, closed the execution plan, split WASM analysis JSON
  helpers out of `crates/pine-wasm/src/lib.rs` to satisfy the structural
  guardrail, and ran focused verification plus the release gate.

## Exported WASM APIs

Phase T adds these WASM exports:

- `runScriptCsvWithRequestBars(source, barsCsv, requestBarsJson)`
- `runScriptCsvWithLibrariesAndRequestBars(source, barsCsv,
  librarySourcesJson, requestBarsJson)`
- `Program.runCsvWithRequestBars(barsCsv, requestBarsJson)`

Existing no-request APIs remain available and continue to use the default
no-provider request environment:

- `runScriptCsv(source, barsCsv)`
- `runScriptCsvWithLibraries(source, barsCsv, librarySourcesJson)`
- `Program.runCsv(barsCsv)`

## Request-Bars JSON Contract

`requestBarsJson` is a JSON object. Keys use the same `SYMBOL:TIMEFRAME`
format as CLI and Python request data. Symbols may contain `:`, so WASM splits
keys on the last colon; `NYSE:IBM:1` means symbol `NYSE:IBM` and timeframe
`1`.

Values are arrays of bar objects:

```json
{
  "NYSE:IBM:1": [
    {"time": 0, "open": 10, "high": 11, "low": 9, "close": 30, "volume": 100}
  ]
}
```

Bar objects require numeric `time`, `open`, `high`, `low`, `close`, and
`volume` fields. `time` is parsed as an integer timestamp. Empty `{}` keeps the
existing no-provider behavior. Duplicate object keys are subject to
`serde_json` map parsing behavior before provider validation; duplicate
requested bar times and unsorted requested bars are still rejected by the
shared `InMemoryRequestDataProvider`.

The WASM crate only decodes host input and builds the shared
`RequestEnvironment`. It does not fetch network data, read files, discover
symbols, implement request alignment, or duplicate provider validation.

## Evidence

Positive coverage:

- `request_bars::tests::request_bars_parses_exchange_prefixed_symbol` proves
  `NYSE:IBM:1` key parsing and provider construction.
- `tests::request_host_data_runs_through_direct_wasm_api` runs
  `tests/fixtures/request/request_security_host.pine` through
  `runScriptCsvWithRequestBars` and checks `[30,32,34,36,38]` plus
  `[null,null,100,100,200]`.
- `tests::run_csv_with_request_bars_matches_direct_request_api` verifies
  compiled `Program.runCsvWithRequestBars` output matches the direct API and is
  stable across repeated runs.
- `tests::library_source_json_combines_with_request_bars` verifies library
  source injection and request-bars injection work together without a combined
  wrapper object.

Negative coverage:

- Malformed request-bars JSON, non-object JSON, invalid keys, empty symbols,
  invalid timeframes, missing bar fields, unsorted bars, and duplicate
  requested bar times fail in focused WASM parser tests.
- Missing provider keys still return the shared runtime missing-data message.
- The combined library/request API reports library-source JSON errors and
  request-bars JSON errors distinctly.

## Unchanged Contracts

- Runtime output remains `schemaVersion: 3`.
- `tests/fixtures/conformance.tsv` still marks `request.security` as
  `partial`, `request.security_lower_tf` as `unsupported`, and broad
  `request.*` as `unsupported`.
- `tests/snapshots/matrix.json` does not change for Phase T because Pine
  request semantics did not widen.
- CLI and Python request behavior remains unchanged.
- Core runtime request alignment, requested-context evaluation, caching, and
  provider validation remain owned by `pine-runtime`.

## Remaining Request Tails

- Lower-timeframe request arrays and `request.security_lower_tf`.
- Optional `request.security` parameters, explicit `gaps`, explicit
  `lookahead`, custom merge behavior, currency conversion, and
  ignore-invalid-symbol behavior.
- Chart metadata host JSON beyond the current default `ChartContext`.
- Advanced request families beyond the current `request.security` subset.
- Requested-expression local aliases, UDF calls, input declarations,
  output/drawing side effects, array mutation, and other side-effecting
  requested expressions.

## Verification Results

Focused verification:

```text
cargo fmt --check
cargo test -p pine-wasm request
cargo test -p pine-cli runs_request_bars_integration_fixture
python3 -m pytest python/tests -q
cargo check -p pine-wasm --target wasm32-unknown-unknown
git diff --check
```

Closeout verification:

```text
scripts/verify.sh
```

Both focused verification and the closeout release gate passed on the Phase T
closeout workspace.
