# Phase H Execution Plan

Phase H adds alert surfaces after the indicator runtime has stable series
evaluation, realtime rollback, drawing output snapshots, request-provider
behavior, and intrabar persistence. Execute it in small, mergeable slices. Each
slice should leave the workspace shippable and should keep semantic claims,
runtime behavior, public output contracts, fixtures, snapshots, and conformance
metadata in lockstep.

Alerts are event outputs, not broker orders and not host notifications. Core
crates must remain deterministic: they should record alert events for a fixed
program and bar stream, while hosts decide whether and how to deliver those
events outside the runtime.

## Original Starting Point

This was the repository state before Phase H started:

- `tests/fixtures/conformance.tsv` marks `alert/alertcondition` as
  `unsupported` with the fixture `tests/fixtures/sema/unsupported_alert.pine`.
- `pine-sema` rejects `alert` and `alertcondition` through the
  unsupported-feature path with `E_UNSUPPORTED_FEATURE`.
- `pine-builtins` has no alert namespace or alert signatures.
- `pine-runtime::RuntimeResult` has no alert event output field.
- CLI, Python, and WASM expose `schemaVersion: 2` runtime outputs with plots,
  drawing objects, diagnostics, and no alert event array.
- `PUBLIC_OUTPUT_SCHEMA_VERSION` was a broad machine-readable public output
  version, not a runtime-only version. It was reused by CLI matrix JSON, WASM
  analysis JSON, Python analysis dictionaries, and runtime outputs.
- Realtime rollback is fixture-backed for outputs, drawing objects, `var`,
  callsite state, arrays, dynamic history, request caches, and `varip`.
- Existing golden JSON snapshots catch public runtime output shape changes.

## Rules for Every Slice

- Add fixtures before or alongside behavior changes.
- Keep unsupported alert variants diagnostic-only until their runtime and host
  semantics are designed.
- Do not mark alerts `partial` or `supported` unless syntax, semantic analysis,
  runtime behavior, public outputs, docs, snapshots, and conformance metadata
  agree.
- Treat alerts as deterministic runtime events. Do not send network, UI,
  webhook, or clock-driven notifications from core crates.
- Keep historical, incremental append, and realtime forming-bar behavior
  explicit. Do not let host bindings infer different trigger rules.
- Preserve existing output and drawing rollback behavior when alert events are
  added.
- Keep CLI, Python, and WASM public output keys synchronized for any alert
  event field.
- Review `PUBLIC_OUTPUT_SCHEMA_VERSION` before adding alert output fields.
  Adding a top-level `alerts` field is a consumer-visible runtime contract
  change. Because the current constant is shared by runtime, analysis, and
  matrix outputs, Phase H must either accept a broad machine-readable schema
  bump or first split schema constants by output family.
- Keep alert condition evaluation side-effect-free except for the alert event
  itself.
- Once an alert call is accepted as a built-in, classify it as a side effect in
  semantic analysis before it can flow into UDF bodies, user-defined function
  arguments, requested-context expressions, or other side-effect-restricted
  paths.
- Decide realtime visibility no later than the first runtime behavior slice.
  `RealtimeRuntime` returns the forming `RuntimeResult`, so an alert append path
  can become visible to Rust callers before docs or conformance claims catch up.
- Run the full release verification gate before closing a slice that changes a
  compatibility claim or public output contract.

## Internal Structure Rules

Phase H adds another public event family. It should not turn existing output,
built-in, or analyzer files into catch-all alert modules.

- Add alert-owned modules before the first behavior slice needs them.
- Keep `pine-builtins` responsible for alert signatures and accepted parameter
  names, not event storage or trigger policy.
- Keep `pine-sema` responsible for unsupported alert variants, argument type
  restrictions, and side-effect policy.
- Keep `pine-runtime::output` responsible for the public alert event model and
  JSON serialization.
- Keep `pine-runtime::builtins::alerts` responsible for evaluating alert calls
  and appending events to runtime state.
- Keep `runtime/historical.rs` and `runtime/realtime.rs` as orchestration
  layers. If alert rollback or event flushing needs helper behavior, move it
  into an alert-owned runtime/output module.
- Keep Python and WASM bindings thin. They should map the same shared runtime
  alert event model instead of duplicating alert semantics.
- Treat roughly 800 lines in a production Rust file as a review trigger. Split
  by responsibility before adding another alert parameter or trigger mode.
- Each slice should have an obvious review boundary: signatures, semantic
  validation, runtime event collection, public output serialization, fixtures,
  docs, snapshots, and matrix metadata should be inspectable independently.

## Intended Module Layout

Use existing crate boundaries. Do not add a new crate for alerts; alert events
belong to the supported indicator runtime output contract.

Recommended layout:

```text
crates/pine-builtins/src/
   namespaces/alerts.rs        alert and alertcondition signatures
   namespaces/mod.rs           alert namespace export
   registry.rs                 include alert signatures once supported

crates/pine-sema/src/analyzer/
   alerts.rs                   alert-specific argument and side-effect checks
   calls.rs                    delegate alert calls before generic built-in handling
   unsupported.rs              unsupported alert variants and precise diagnostics

crates/pine-runtime/src/
   output/
      alerts.rs                AlertEvent model and helper serialization
      model.rs                 RuntimeResult alert field and schema version review
      json.rs                  shared public runtime JSON output
   builtins/
      alerts.rs                alert and alertcondition runtime evaluation
   runtime/
      historical.rs            alert event store ownership and orchestration only
      realtime.rs              forming/confirmed event rollback policy

crates/pine-cli/src/
   json.rs or commands/run.rs  no alert semantics, only shared runtime JSON use

crates/pine-python/src/
   lib.rs                      map shared alert events into dictionaries

crates/pine-wasm/src/
   lib.rs                      return shared alert event JSON
```

Ownership notes:

- `pine-builtins` should describe accepted argument shapes, optional parameters,
  and return type only.
- `pine-sema` should reject unsupported dynamic message shapes, unsupported
  frequencies, and side-effect contexts before runtime when possible.
- `pine-runtime::output::alerts` should own the public event shape. It should
  not know how alert expressions are type-checked.
- `pine-runtime::builtins::alerts` should append events through a small runtime
  helper rather than mutating public output vectors from many places.
- `RealtimeRuntime` should decide which forming-bar events are visible or
  discarded according to the Phase H policy, but it should not duplicate
  alert-call evaluation.

## Event Contract Direction

Phase H should start with a narrow event output contract and widen only after
fixtures prove historical, incremental, and realtime behavior.

Initial alert event fields should be intentionally small:

- `id`: deterministic per-alert-site id.
- `barIndex`: zero-based chart bar index where the event was produced.
- `time`: chart bar timestamp for the event.
- `message`: normalized string message.
- `source`: the alert condition title for `alertcondition`, or `alert` for the
  imperative `alert()` subset.

Later fields may include frequency, condition title, realtime update kind, or
host routing metadata only after they have clear public semantics and snapshots.

Initial public output shape:

```text
alerts: [
  { id, barIndex, time, message, source }
]
```

Schema rule:

- Slice 0 chose split schema constants: `PUBLIC_RUNTIME_SCHEMA_VERSION`,
  `PUBLIC_ANALYSIS_SCHEMA_VERSION`, and `PUBLIC_MATRIX_SCHEMA_VERSION`.
- If `alerts` is added as a new top-level runtime output field, update the
  public schema contract deliberately.
- Runtime-only alert output fields should now update the runtime schema
  contract without forcing matrix or analysis schema changes.
- Do not add host-specific alert keys to only one public surface.

## Semantics Direction

Start with deterministic historical event recording:

- `alertcondition(condition, title, message)` produces an alert event when the
  condition is true on a bar.
- The first supported `condition` rule should be explicit in semantic code:
  either add a series-bool-specific acceptance rule, or deliberately reuse the
  existing bool-compatible rule and document that const/simple/input bools are
  accepted as a narrower-compatible subset.
- The first supported `title` and `message` shapes should be `ConstString`.
  Do not accept `input.string()` or other simple string expressions until the
  message model has fixtures and docs for that wider boundary.
- Phase H treats `alertcondition` as a runtime event-producing statement in the
  executable subset, not as a TradingView-style global UI declaration. If it is
  allowed in branches or loops, that scope behavior must be documented in
  execution semantics and conformance notes.
- `alert(message)` records an event when execution reaches the call.
- `alert()` inside skipped branches should not produce events.
- Alert event order should follow program execution order within a bar and bar
  order across the dataset.
- Realtime forming-update behavior must be picked before any runtime alert
  append helper is enabled.

Recommended initial realtime policy:

- Historical and confirmed realtime updates may produce visible alert events.
- Slice 2 selected visible forming events: a `RealtimeRuntime::update(Forming)`
  result includes alert events from that current forming evaluation.
- Forming updates roll back alert events like other runtime outputs.
- No alert event should survive from an abandoned forming update after the next
  forming update recomputes the same bar.

Out of initial scope:

- Webhook delivery, sound/UI notification, email/SMS, or any external delivery
  mechanism.
- User alert creation APIs.
- Full TradingView frequency modes before a deterministic runtime policy exists.
- Placeholder interpolation beyond a small fixture-backed string subset.
- Strategy-order alerts; those belong with Phase G strategy runtime.
- Alerts inside requested-context `request.security` expressions.

## How to Use the Acceptance Criteria

The exit criteria under each slice are local merge criteria for that slice.
Phase H should not be marked complete until the closeout checklist is done or a
remaining alert variant is explicitly moved to a documented Phase H maintenance
tail.

Maintenance tails must be narrow. They may keep advanced frequency modes,
placeholders, host delivery, or strategy alerts out of scope, but they must not
weaken these Phase H acceptance criteria:

- Claimed alert surfaces produce deterministic public alert events.
- Historical, incremental, and realtime policy are fixture-backed.
- Public output keys are synchronized across CLI, Python, and WASM.
- Unsupported alert variants produce stable diagnostics before runtime when
  possible.

## Slice 0: Schema Version Decision

Goal: decide the alert output schema strategy before changing any public output
or accepting alert calls.

Steps:

1. Inventory every current `PUBLIC_OUTPUT_SCHEMA_VERSION` consumer:
   - CLI runtime JSON.
   - CLI matrix JSON.
   - WASM runtime JSON.
   - WASM analysis JSON.
   - Python analysis dictionaries.
   - Python runtime dictionaries.
   - Golden JSON snapshots under `tests/snapshots/`.
2. Choose one schema strategy. Phase H chose to split runtime, analysis, and
   matrix schema constants before adding runtime-only alert fields.
3. If keeping one shared version, update all schema assertions and snapshots in
   the same change, including matrix and analysis snapshots.
4. After splitting constants, document the ownership boundary in
   `docs/ARCHITECTURE.md` and `docs/CONFORMANCE.md`, then update tests so each
   output family asserts the intended version.
5. Update `docs/RELEASE_NOTES.md` with the schema decision and migration impact.
6. Keep `alert` and `alertcondition` rejected in semantic analysis.
7. Keep `tests/fixtures/conformance.tsv` unchanged.

Exit criteria:

- The repository has one explicit schema strategy for Phase H.
- Snapshot refresh scope is known before `alerts: []` is added.
- Runtime, analysis, and matrix schema ownership are documented.
- Existing alert calls still report `E_UNSUPPORTED_FEATURE`.

Verification:

```text
cargo test -p pine-cli matrix_output_matches_golden_snapshot
cargo test -p pine-wasm analysis_outputs_match_golden_snapshots
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test --workspace
```

## Slice 1: Alert Output Contract Scaffold

Goal: add the public output and internal event model needed for alerts without
claiming executable alert support yet.

Steps:

1. Add an `AlertEvent` model under `pine-runtime::output`.
2. Add an `alerts` field to `RuntimeResult`, or reserve it through a documented
   compatible output-contract decision.
3. Apply the schema decision from Slice 0. Do not make an implicit schema bump
   inside this slice.
4. Update CLI and WASM JSON through the shared runtime serialization helpers.
5. Update Python dictionary conversion with the same top-level `alerts` key.
6. Add tests that assert the key exists and is empty for scripts without alerts.
7. Refresh golden JSON snapshots for representative runtime outputs. If Slice 0
   kept one shared schema version and bumped it, refresh matrix and WASM
   analysis snapshots in the same patch set as well.
8. Keep `alert` and `alertcondition` rejected in semantic analysis during this
   slice.
9. Update `docs/CONFORMANCE.md`, `docs/ARCHITECTURE.md`, and release notes with
   the alert output contract and schema decision.

Exit criteria:

- Existing scripts expose a stable empty `alerts` array across CLI, Python, and
  WASM if the field is added.
- Matrix and analysis snapshots are either unchanged by design, or refreshed
  deliberately according to the Slice 0 schema strategy.
- Existing alert calls still report `E_UNSUPPORTED_FEATURE`.
- Golden snapshots catch accidental alert output shape drift.
- No runtime event semantics are claimed yet.

Verification:

```text
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-wasm
maturin build --manifest-path crates/pine-python/Cargo.toml --out dist
python3 -m pip install --force-reinstall dist/*.whl
python3 -m pytest python/tests
cargo test --workspace
```

## Slice 2: Minimal `alertcondition` Events

Goal: support the first useful declarative alert subset with deterministic
historical events.

Initial scope:

- `alertcondition(condition, title, message)`.
- `condition`: an explicitly documented bool-compatible or series-bool rule.
- `title`: `ConstString`.
- `message`: `ConstString`.
- Historical, incremental append, and the initial realtime rollback policy.

Steps:

1. Add `alertcondition` to `pine-builtins` with a narrow signature and void
   return.
2. Add alert-specific semantic checks so unsupported parameters, dynamic
   messages, optional arguments, and side-effect contexts have precise
   diagnostics.
3. Add alert calls to the semantic side-effect classification before enabling
   them as ordinary built-ins.
4. Document whether `alertcondition` is accepted only at global scope or as a
   runtime event-producing statement in branches/loops. If branches or loops
   are accepted, add conformance notes that make this deliberate.
5. Use the selected initial realtime policy: return current forming events from
   `RealtimeRuntime` while proving they roll back and do not survive abandoned
   forming updates.
6. Add runtime evaluation that appends one event when `condition` is true for a
   bar.
7. Assign deterministic alert-site ids through existing output/callsite id
   mechanisms or a small alert-site allocator.
8. Preserve program-order event ordering when multiple `alertcondition` calls
   trigger on the same bar.
9. Add runtime fixtures for true/false conditions, `na` conditions, branch
   execution, multiple alert sites, and message/title output.
10. Add realtime fixtures for forming updates according to the chosen initial
    policy.
11. Add incremental append tests through the existing runtime fixture harness.
12. Update `tests/fixtures/conformance.tsv` from `unsupported` to `partial`
    only after fixtures exist.
13. Refresh matrix and runtime golden snapshots.
14. Update `docs/EXECUTION_SEMANTICS.md`, `docs/REALTIME_MODEL.md`,
    `docs/LANGUAGE_SCOPE.md`, and release notes with the accepted
    `alertcondition` subset.

Exit criteria:

- `alertcondition` events are deterministic for historical runs.
- False or `na` conditions do not produce events.
- Incremental append execution matches full historical execution for alert
  fixtures.
- Realtime forming update behavior is tested before the `alertcondition` claim
  is added to the matrix.
- UDF, requested-context, user-defined function argument, and other
  side-effect-restricted contexts reject `alertcondition`.
- `title` and `message` do not accidentally accept `input.string()` or wider
  simple string values unless that wider support is explicitly designed.
- Unsupported alert parameters still fail during semantic analysis.
- Matrix notes name the exact supported `alertcondition` subset.

Verification:

```text
cargo test -p pine-sema alert
cargo test -p pine-runtime alert
cargo test -p pine-runtime --test realtime alert
cargo test -p pine-runtime --test incremental
cargo test -p pine-cli matrix
cargo test --workspace
```

## Slice 3: Imperative `alert()` Events

Goal: support imperative alert calls as execution-reached events after the event
model is stable.

Initial scope:

- `alert(message)`.
- `message`: `ConstString`.
- Calls in global flow and ordinary branch/loop contexts.
- Historical, incremental append, and the realtime policy already selected in
  Slice 2.

Steps:

1. Add `alert` to `pine-builtins` with a narrow signature and void return.
2. Add `alert` to the same semantic side-effect classification used for output
   and declaration built-ins before accepting it in ordinary call analysis.
3. Add semantic checks for unsupported optional frequency arguments until a
   deterministic frequency policy is designed.
4. Reject `alert()` inside UDF bodies, user-defined function arguments,
   requested-context expressions, and other side-effect-restricted contexts in
   the initial subset.
5. Reuse the alert event append helper from Slice 2.
6. Add fixtures where `alert()` is reached every bar, only inside a true branch,
   inside a loop, and after a stateful condition.
7. Add fixtures proving skipped branches do not emit events.
8. Add realtime fixtures showing `alert()` follows the Slice 2 forming/confirmed
   policy.
9. Update conformance notes to distinguish `alert()` from `alertcondition`.
10. Update public snapshots if representative alert output changes.

Exit criteria:

- `alert()` emits events only when execution reaches the call.
- Branch and loop behavior matches the normal runtime execution model.
- `alert()` is rejected everywhere output side effects are rejected unless a
  later slice deliberately widens side-effect policy.
- Dynamic message and frequency arguments remain unsupported with precise
  diagnostics.
- Unsupported frequency and side-effect contexts have stable diagnostics.
- `alertcondition` behavior from Slice 2 remains unchanged.

Verification:

```text
cargo test -p pine-sema alert
cargo test -p pine-runtime alert
cargo test -p pine-runtime --test realtime alert
cargo test -p pine-runtime runtime_control_flow
cargo test --workspace
```

## Slice 4: Realtime Alert Policy Hardening

Goal: harden and document the realtime policy selected in the first runtime
behavior slice.

Recommended initial scope:

- Historical bars and confirmed realtime updates produce visible alert events.
- Forming updates recompute alert events with the forming runtime but do not
  persist abandoned forming events after rollback.
- No intrabar delivery guarantee is claimed.

Steps:

1. Audit the Slice 2/3 realtime fixtures against the implementation path in
   `RealtimeRuntime`.
2. Add any missing fixtures for repeated forming updates, condition changes
   between forming updates, multiple alert sites, and a confirmed update.
3. Ensure ordinary output rollback, drawing rollback, request cache rollback,
   and `varip` persistence remain unchanged.
4. Confirm whether public runtime results from a forming update include current
   forming alert events or only confirmed events, and align docs with that
   already-tested behavior.
5. Add runtime tests proving abandoned forming events are not duplicated or
   retained into the confirmed state.
6. Update conformance notes only after the realtime fixture behavior is stable.

Exit criteria:

- Repeated forming updates cannot leak stale alert events, including when later
  forming updates trigger fewer alert sites or none.
- Confirmed realtime updates produce the same final alert event state as the
  equivalent historical execution where applicable.
- Runtime docs describe whether forming alert events are visible or suppressed.
- No host binding claims a realtime alert API it does not expose.

Verification:

```text
cargo test -p pine-runtime --test realtime alert
cargo test -p pine-runtime --test realtime
cargo test -p pine-runtime alert
cargo test --workspace
```

## Slice 5: Message and Frequency Boundary

Goal: decide which alert message and frequency options are worth supporting in
Phase H, and keep the rest diagnostic-only.

Steps:

1. Inventory current string support, series string behavior, and any existing
   formatting helpers before accepting dynamic messages.
2. Treat `ConstString` as the completed initial subset. Any move to
   `input.string()`, simple strings, or series strings is a widening change that
   needs semantic tests, runtime fixtures, snapshots, and docs in the same
   slice.
3. Decide whether placeholder interpolation belongs in Phase H. If yes, design
   a deterministic parser and fixture set before implementation. If no, add a
   clear unsupported diagnostic and maintenance-tail note.
4. Pick a frequency policy only if it can be expressed deterministically for
   historical and realtime execution.
5. Add semantic diagnostics for frequency modes or message forms that remain
   unsupported.
6. Add fixtures for every supported message/frequency shape and for rejected
   shapes.
7. Update docs and conformance notes with exact boundaries.

Exit criteria:

- Message values in public alert events are deterministic and snapshot-backed.
- Frequency behavior, if supported, has historical and realtime fixtures.
- Unsupported placeholders and frequency modes fail with precise diagnostics.
  The selected Phase H policy is to reject TradingView-style `{{...}}`
  placeholders rather than serialize them as interpolated values.
- Public output schema changes are intentional and snapshot-backed.

Verification:

```text
cargo test -p pine-sema alert
cargo test -p pine-runtime alert
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test --workspace
```

## Slice 6: Host Surfaces, Snapshots, and Closeout

Goal: close Phase H for the claimed alert subset and record remaining
maintenance tails.

Steps:

1. Review CLI, Python, and WASM runtime outputs for the same alert event keys
   and value normalization.
2. Confirm the schema strategy from Slice 0 is reflected in every public output
   family and snapshot.
3. Add or refresh golden snapshots for scripts with `alertcondition`, `alert()`,
   and scripts without alerts.
4. Ensure matrix JSON includes the alert rows with fixture-backed partial or
   supported status.
5. Update `docs/CONFORMANCE.md`, `docs/EXECUTION_SEMANTICS.md`,
   `docs/LANGUAGE_SCOPE.md`, `docs/REALTIME_MODEL.md`,
   `docs/ARCHITECTURE.md`, and `docs/RELEASE_NOTES.md`.
6. Add `docs/PHASE_H_AUDIT.md` summarizing completed slices, public output
   contract, supported surface, verification results, and maintenance tails.
7. Record unsupported host delivery, advanced frequency modes, placeholders,
   strategy alerts, requested-context alerts, or UDF-side-effect alerts as
   explicit maintenance tails.
8. Run the canonical release gate before marking Phase H closed.

Exit criteria:

- The compatibility matrix describes the exact alert subset and cites fixture
  paths.
- Runtime tests cover historical, incremental, and realtime policy for every
  claimed alert surface.
- CLI, Python, and WASM expose the same public alert event contract.
- Docs and release notes agree on unsupported tails.
- Phase H has a closeout audit with verification evidence.
- No production Rust file crosses the structural guardrail because of alert
  work.

Verification:

```text
git diff --check
scripts/verify.sh
```

## Closeout Checklist

- Alert output contract is versioned and snapshot-backed.
- Runtime, analysis, and matrix schema ownership is explicit.
- `alertcondition` support has semantic, runtime, incremental, and matrix
  fixtures for its claimed subset.
- `alert()` support has semantic, runtime, incremental, and matrix fixtures for
  its claimed subset, or remains explicitly unsupported with a fixture.
- Realtime alert policy is documented and fixture-backed.
- Unsupported message, frequency, placeholder, UDF, requested-context, and
  strategy-alert variants have stable diagnostics.
- CLI, Python, and WASM public outputs include the same alert keys and schema
  version.
- Matrix and snapshot tests catch accidental alert compatibility widening.
- Phase H audit records completed slices, verification command results,
  supported surface, and maintenance tails.

## Suggested Commit Order

1. `Decide public schema strategy for alerts`
2. `Add alert output contract scaffold`
3. `Support minimal alertcondition events`
4. `Support imperative alert events`
5. `Harden realtime alert policy`
6. `Resolve alert message and frequency boundary`
7. `Close Phase H audit`
