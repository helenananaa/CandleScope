# Phase H Audit: Alerts

Status: closed for the fixture-backed claimed subset.

Phase H delivered deterministic alert events for the narrow
`alertcondition()` and `alert()` subsets without adding host-specific alert
delivery APIs. The claimed surface is intentionally tied to
`tests/fixtures/conformance.tsv`, runtime snapshots, and the shared public
runtime output model.

## Delivered Surface

- Public runtime output schema `3` includes a top-level `alerts` array.
- Runtime alert event shape is `{id, barIndex, time, message, source}`.
- `alertcondition(condition, title, message)` accepts bool-compatible
  conditions plus const-string title/message values, with `{{open}}`,
  `{{high}}`, `{{low}}`, `{{close}}`, `{{volume}}`, `{{ticker}}`,
  `{{interval}}`, `{{exchange}}`, and UTC-formatted triggering-bar `{{time}}`
  interpolation in the message only.
- `alert(message, freq?)` accepts string-compatible dynamic messages and a
  narrow const-string frequency subset.
- Reached true alert conditions and reached `alert()` calls emit events in
  program order, subject to supported `alert()` frequency filtering. False and
  `na` alert conditions emit nothing.
- Realtime forming results expose the current forming alert events, while
  `confirmed_result()` exposes only committed events. Repeated forming updates
  recompute from the confirmed snapshot, so abandoned forming alert events do
  not leak or duplicate.
- `alert` and `alertcondition` are classified as output side effects and remain
  rejected in UDFs and requested-context expressions.
- Dynamic alert strings, `{{...}}` placeholder interpolation outside the
  supported `alertcondition` message subset, host delivery, strategy alerts, and
  other alert variants remain unsupported.

## Schema And Host Surface

Runtime schema ownership is split from analysis and matrix schema ownership:

- `PUBLIC_RUNTIME_SCHEMA_VERSION = 3`
- `PUBLIC_ANALYSIS_SCHEMA_VERSION = 2`
- `PUBLIC_MATRIX_SCHEMA_VERSION = 2`

CLI runtime JSON and WASM runtime JSON use the shared
`public_runtime_result_json` helper, which serializes `alerts` with the same
field names and value normalization. Python keeps explicit native-dictionary
conversion, and `python/tests/test_bindings.py` covers empty alert output,
alertcondition events, imperative alert events, and the alert-frequency fixture
with the same keys. WASM tests cover the same alert-frequency fixture through
`runScriptCsv`.

Phase H did not add a public realtime host API. Realtime behavior is covered by
Rust runtime fixtures and tests.

## Fixture Evidence

Compatibility matrix rows:

- `alertcondition`: `partial`
- `alert`: `partial`
- `alert frequency`: `partial`
- `alert placeholders`: `unsupported` outside the supported `alertcondition`
  message subset
- `function side effects`: `unsupported`
- `realtime forming rollback`: `partial`

Runtime fixtures:

- `tests/fixtures/runtime/alertcondition.pine`
- `tests/fixtures/runtime/alert.pine`
- `tests/fixtures/runtime/alert_frequency.pine`

Realtime fixtures:

- `tests/fixtures/realtime/alertcondition_rollback.pine`
- `tests/fixtures/realtime/alert_rollback.pine`
- `tests/fixtures/realtime/alert_policy.pine`
- `tests/fixtures/realtime/alert_frequency_rollback.pine`
- `tests/fixtures/realtime/alert_frequency_close.pine`

Semantic fixtures:

- `tests/fixtures/sema/unsupported_alert.pine`
- `tests/fixtures/sema/unsupported_alert_dynamic_frequency.pine`
- `tests/fixtures/sema/unsupported_alert_unknown_frequency.pine`
- `tests/fixtures/sema/unsupported_alert_placeholder.pine`
- `tests/fixtures/sema/unsupported_alertcondition_placeholder.pine`
  for unknown `alertcondition` message placeholders
- `tests/fixtures/sema/unsupported_alert_function_side_effect.pine`
- `tests/fixtures/sema/unsupported_imperative_alert_function_side_effect.pine`

Golden snapshots:

- `tests/snapshots/runtime_alertcondition.json`
- `tests/snapshots/runtime_alert.json`
- `tests/snapshots/runtime_alert_frequency.json`
- `tests/snapshots/runtime_io.json`, which keeps empty `alerts: []` in the
  no-alert baseline.
- `tests/snapshots/matrix.json`, which records the alert conformance rows.

The runtime incremental fixture test covers both alert runtime fixtures because
it runs every `tests/fixtures/runtime/*.pine` file through full historical and
incremental append execution and compares the complete `RuntimeResult`.

## Manual Host Checks

Manual checks on the closeout workspace:

- `cargo run -q -p pine-cli -- matrix --format text | rg "alert|realtime forming rollback"`
  reports `alertcondition`, `alert`, and `alert frequency` as partial,
  `alert placeholders` as unsupported, and includes the realtime alert fixture
  paths.
- `cargo run -q -p pine-cli -- run tests/fixtures/runtime/alertcondition.pine --bars tests/fixtures/runtime/bars.csv`
  emits `schemaVersion: 3` and alertcondition events with `source` equal to the
  const title.
- `cargo run -q -p pine-cli -- run tests/fixtures/runtime/alert.pine --bars tests/fixtures/runtime/bars.csv`
  emits `schemaVersion: 3` and `alert()` events with `source: "alert"`.
- `cargo run -q -p pine-cli -- run tests/fixtures/runtime/alert_frequency.pine --bars tests/fixtures/runtime/bars.csv`
  emits default/once-per-bar and close-frequency alert events once per callsite
  per historical bar, and `alert.freq_all` events for every reached call.

## Verification

Slice-level verification included:

```text
cargo test -p pine-sema alert
cargo test -p pine-runtime alert
cargo test -p pine-runtime --test realtime alert
cargo test -p pine-runtime --test realtime
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli matrix_output_matches_golden_snapshot
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test --workspace
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

## Maintenance Tails

- TradingView-style alert placeholder interpolation remains unsupported outside
  the supported `alertcondition` message placeholders.
- Dynamic/simple/input/series message strings remain unsupported for alert
  messages and alertcondition titles/messages.
- Host-side alert delivery, subscriptions, throttling, and UI/API notification
  behavior are outside Phase H.
- Strategy alerts remain out of scope until Phase G defines strategy runtime
  output and broker-emulation semantics.
- Alert side effects inside UDFs and requested-context expressions remain
  rejected by the side-effect policy.

## Structure Check

Alert-specific code is split across dedicated modules:

- `crates/pine-builtins/src/namespaces/alerts.rs`
- `crates/pine-runtime/src/builtins/alerts.rs`
- `crates/pine-runtime/src/output/alerts.rs`
- `crates/pine-sema/src/analyzer/alerts.rs`

After closeout cleanup, `crates/pine-sema/src/analyzer/calls.rs` is back under
800 lines. The alert runtime and built-in namespace files remain small and
focused.

## Closeout Checklist

- Alert output contract is versioned and snapshot-backed.
- Runtime, analysis, and matrix schema ownership is explicit.
- `alertcondition` support has semantic, runtime, incremental, realtime,
  matrix, and public-output coverage for its claimed subset.
- `alert()` support has semantic, runtime, incremental, realtime, matrix, and
  public-output coverage for its claimed subset.
- Realtime alert policy is documented and fixture-backed.
- Realtime alert-frequency rollback covers default once-per-bar suppression,
  `alert.freq_all` repeated-call emission, abandoned forming event removal, and
  confirmed/historical parity.
- Unsupported message, frequency, placeholder, UDF, requested-context, and
  strategy-alert variants have stable diagnostics or explicit maintenance
  tails. Placeholder diagnostics still cover `alert()` placeholders and unknown
  `alertcondition` placeholders. Frequency diagnostics include literal,
  dynamic, and unknown const-string fixture coverage.
- CLI, Python, and WASM public outputs include the same alert keys and runtime
  schema version.
- Matrix and snapshot tests catch accidental alert compatibility widening.
- `scripts/verify.sh` passes on the closeout workspace.
