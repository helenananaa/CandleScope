# Phase F Execution Plan

Status: Phase F is closed for the current fixture-backed `request.security` and
multi-timeframe subset. Use `docs/PHASE_F_AUDIT.md` as the closeout record
before adding new request maintenance work.

Phase F adds `request.*` and multi-timeframe data support only after the runtime
has a host-neutral data-provider boundary. Execute it in small, mergeable slices.
Each slice should leave the workspace shippable and should keep semantic claims,
runtime behavior, public host APIs, fixtures, and conformance metadata in
lockstep.

Phase F is not a network-fetching phase. Core crates must remain deterministic:
hosts provide all requested data, and the runtime only validates, caches, aligns,
and evaluates it.

## Original Starting Point

This was the repository state when Phase F started:

- `tests/fixtures/conformance.tsv` marks `request.*` as `unsupported` with the
  fixture `tests/fixtures/sema/unsupported_request.pine`.
- `pine-sema` rejects every `request.*` call through the unsupported-feature
  path.
- `pine-builtins` has no `request.*` namespace signatures or `barmerge.*`
  constants.
- `pine-runtime::HistoricalRuntime::new` executes one chart bar stream and has
  no host data-provider parameter.
- CLI, Python, and WASM runtime entry points accept one chart dataset only.
- Existing `syminfo.*` and `timeframe.*` helpers are fixed-default chart metadata
  helpers, not host-provided chart metadata. Phase F must introduce a chart
  metadata boundary before accepting symbol/timeframe-sensitive request forms.
- Existing timeframe helpers are conversion and fixed-default chart metadata
  helpers, not a general request alignment engine.
- Realtime rollback works by cloning runtime state for forming updates. Any
  request cache added to runtime state must remain deterministic and clone-safe,
  or must be kept behind an immutable shared provider boundary.

## Rules for Every Slice

- Add fixtures before or alongside behavior changes.
- Keep unsupported request variants diagnostic-only until their semantics are
  designed.
- Do not mark a request feature `partial` or `supported` unless syntax,
  semantic analysis, runtime behavior, host APIs, docs, and conformance metadata
  agree.
- Core crates must not download data, read arbitrary files, or depend on a live
  clock. Hosts inject requested bar streams explicitly.
- Preserve historical, incremental append, and realtime forming-bar behavior.
- Keep CLI, Python, and WASM host contracts synchronized for any new provider
  capability or public error shape.
- Keep request evaluation deterministic for a fixed program, chart bars,
  requested bars, and provider configuration.
- Prefer a narrow, fixture-backed `request.security` subset over accepting many
  parameters with approximate behavior.
- Treat chart metadata as part of the host contract. A request subset that
  accepts `syminfo.tickerid`, `timeframe.period`, or equivalent string values
  must define where the chart symbol and chart timeframe come from.
- Do not route `request.security` entirely through the ordinary built-in call
  analyzer if the requested expression needs special context handling. Add a
  request-specific semantic and lowering path before accepting forms whose third
  argument is a requested-context expression.
- Run the full release verification gate before closing a slice that changes a
  compatibility claim or public host contract.

## Internal Structure Rules

Phase F adds a runtime data subsystem. It should not turn existing hot files into
catch-all request engines.

- Do not put chart metadata, provider contracts, timeframe parsing, bar
  alignment, request cache, semantic signatures, CLI parsing, and runtime
  evaluation into one large file.
- Add request-owned modules before the first behavior slice needs them. Prefer
  narrow modules such as chart metadata, provider contracts, timeframe parsing,
  bar validation, alignment, request cache, and request built-in evaluation.
- Keep `runtime/historical.rs` as the orchestration layer. It may own the active
  provider handle and request cache, but it should delegate request semantics.
- Keep built-in declarations grouped in a dedicated `request.*` namespace file.
- Keep Python and WASM bindings thin. They should map host-provided datasets
  into the shared request-provider contract, not duplicate alignment logic.
- Treat roughly 800 lines in a production Rust file as a review trigger. Split
  by responsibility before adding another request variant or alignment mode.
- Put large alignment or request-expression design notes in focused documents
  only when they are needed, and link them from this playbook instead of growing
  this file into a giant design dump.
- Each slice should have an obvious review boundary: signatures, provider
  contract, runtime alignment, host API, fixtures, docs, and matrix metadata
  should be inspectable independently.

## Intended Module Layout

Use existing crate boundaries. Do not add a new crate unless a later review
proves provider contracts must be shared outside `pine-runtime` without pulling
runtime dependencies.

Recommended layout:

```text
crates/pine-builtins/src/
   namespaces/requests.rs       request.security signatures
   constants/strings.rs         barmerge.gaps_*, barmerge.lookahead_* strings if needed

crates/pine-sema/src/analyzer/
   requests.rs                  request-specific call analysis and expression restrictions
   calls.rs                     delegate request calls before ordinary built-in call handling
   unsupported.rs               unsupported request variants and precise diagnostics

crates/pine-runtime/src/
   request/
      mod.rs                    public request subsystem facade
      chart.rs                  chart symbol/timeframe metadata contract
      provider.rs               RequestDataProvider, RequestKey, provider errors
      timeframe.rs              timeframe parsing, ordering, and ratio helpers
      bars.rs                   requested bar validation and normalization
      align.rs                  chart/request bar alignment rules
      cache.rs                  deterministic per-callsite/request cache
      security.rs               request.security runtime evaluation
   builtins/
      requests.rs               dispatch from built-in calls into request subsystem
   runtime/historical.rs        provider handle, cache ownership, orchestration only
```

Ownership notes:

- `pine-builtins` owns accepted parameter names and return typing, not provider
  lookup or alignment.
- `pine-sema` owns unsupported variants, request expression restrictions, and
  side-effect safety. `request.security` should have a dedicated analysis path
  for the requested expression instead of relying only on ordinary eager argument
  analysis.
- `pine-runtime::request` owns provider contracts, requested bar validation,
  chart metadata, alignment, caching, and request-specific runtime errors.
- `pine-runtime::builtins::requests` owns call argument extraction and dispatch.
- CLI/Python/WASM own host-specific data injection only.
- `pine-ir` should stay unchanged unless request expression evaluation needs a
  stable request-context marker, expression identity, or request subprogram that
  cannot be represented with existing HIR.

## Implemented Module Layout

Phase F used the existing crate boundaries. Future request maintenance should
not add a new crate unless a later review proves the request provider boundary
must be enforced across package dependencies.

Current layout:

```text
crates/pine-builtins/src/
   namespaces/requests.rs       request.security signature

crates/pine-sema/src/analyzer/
   requests.rs                  request-specific call analysis and expression restrictions
   calls.rs                     request.* delegation before ordinary built-in handling
   unsupported.rs               unsupported request variants and precise diagnostics

crates/pine-runtime/src/
   request/
      mod.rs                    request subsystem facade and re-exports
      chart.rs                  ChartContext symbol/timeframe metadata
      provider.rs               RequestEnvironment, RequestDataProvider, RequestKey, cache key
      timeframe.rs              request timeframe parsing and seconds conversion
      bars.rs                   requested bar ordering and duplicate-time validation
   builtins/
      requests.rs               request.security evaluation, provider lookup, cache use,
                                  requested-context execution, and alignment helpers
   runtime/
      historical.rs             RequestEnvironment ownership, request cache, constructors
      realtime.rs               request-environment propagation through rollback

crates/pine-cli/src/commands/
   run.rs                       --request-bars SYMBOL:TIMEFRAME=bars.csv host injection

crates/pine-python/src/
   lib.rs                       request_bars dictionary host injection

crates/pine-wasm/src/
   lib.rs                       single-chart execution; provider-data gap remains diagnostic-only
```

Implementation notes:

- `pine-runtime::request` owns provider contracts, chart metadata, timeframe
  parsing, and requested-bar validation.
- `pine-runtime::builtins::requests` currently owns the compact runtime request
  evaluation path, including alignment and cache use. If future maintenance adds
  another request variant, merge option, lower-timeframe rule, or larger
  requested-expression engine, split alignment/cache/security helpers into
  request-owned modules before growing this file further.
- `HistoricalRuntime` and `RealtimeRuntime` carry `RequestEnvironment` while
  preserving the existing no-provider constructors.
- CLI and Python map host-provided bars into the shared runtime provider
  contract. WASM intentionally keeps request dataset injection out of scope for
  the closed Phase F subset.
- The compatibility matrix remains the source of truth for the supported
  `request.security` subset and the unsupported request-family boundaries.

## Request Contract Direction

Start with a narrow `request.security` subset and widen only after fixtures prove
historical, incremental, and realtime agreement.

Initial target shape:

```text
request.security(symbol, timeframe, expression)
```

Initial rules:

- `symbol` is a const/simple string or supported symbol metadata value.
- `timeframe` is a const/simple timeframe string or supported timeframe metadata
  value.
- `expression` is evaluated without side effects in the requested context.
- Same-context support is an identity subset only: it may return the
  chart-context expression value when symbol and timeframe equal the current
  chart metadata, but it must not be described as requested-context evaluation
  until Slice 4 implements isolated requested-context execution.
- Default merge behavior is explicit and fixture-backed before support is
  claimed. Prefer `barmerge.gaps_off` and `barmerge.lookahead_off` first.
- Provider data is immutable for a runtime execution. A host may reuse provider
  objects across runs, but the runtime must see deterministic data.
- Missing requested data is a stable runtime error unless a slice explicitly
  designs an `ignore_invalid_symbol` subset.

Out of initial scope unless a later slice explicitly adds it:

- Network fetching or automatic symbol discovery.
- `request.security_lower_tf` array-returning behavior.
- Currency conversion, financial/economic request families, dividends, splits,
  earnings, and seed data.
- `lookahead_on`, custom gap modes beyond the first supported subset, and rare
  request parameters.
- Request calls with output, drawing, input, array mutation, or other side
  effects inside the requested expression.

## How to Use the Acceptance Criteria

The exit criteria under each slice are local merge criteria for that slice.
Phase F should not be marked complete until the closeout checklist is done or a
remaining request variant is explicitly moved to a documented maintenance tail.

Maintenance tails must be narrow. They may keep advanced parameters or request
families out of scope, but they must not weaken these Phase F acceptance
criteria:

- Supported request forms have deterministic provider lookup, alignment,
  caching, rollback, incremental execution, and diagnostics.
- Unsupported request variants produce stable diagnostics.
- CLI, Python, and WASM can supply the same fixture-backed requested datasets or
  explicitly document why one host surface remains unsupported.
- The conformance matrix describes request support at narrow feature granularity.
  Do not replace the current broad `request.*` unsupported row with a broad
  partial claim. Prefer rows such as `request.security` for the supported subset,
  `request.security_lower_tf` for the lower-timeframe API boundary, and
  `request.* advanced families` for still-unsupported request families.

## Slice 1: Chart Metadata and Request Provider Contract Scaffold

Goal: add host-neutral chart metadata and provider boundaries without accepting
`request.*` yet.

Steps:

1. Add a focused request subsystem under `pine-runtime/src/request/` with
   chart metadata, provider, key, timeframe, requested-bar validation, and error
   types.
2. Define a `ChartContext` or equivalent metadata shape for the current chart
   symbol and timeframe. Keep the existing fixed-default metadata behavior as the
   default no-host-metadata path.
3. Define a `RequestKey` shape that includes symbol and timeframe, and keep any
   optional request parameters out until a later slice supports them.
4. Define a `RequestDataProvider` trait or equivalent immutable provider
   interface that returns validated bar streams without doing I/O in core crates.
5. Add a no-request default provider and default chart metadata so existing
   `HistoricalRuntime::new` and `run_historical` call sites keep working
   unchanged.
6. Add `HistoricalRuntime` and `RealtimeRuntime` constructors or builders that
   can share immutable chart metadata/provider state without breaking the
   existing no-provider constructors.
7. Add unit tests for timeframe parsing, unsupported timeframe strings, missing
   provider data, duplicate requested bars, unsorted requested bars, and default
   chart metadata.
8. Keep `request.*` semantic diagnostics unchanged in this slice.
9. Document the chart metadata and provider ownership boundary in
   `docs/ARCHITECTURE.md` if the public runtime API changes.

Exit criteria:

- Existing scripts behave exactly as before.
- Provider validation is deterministic and covered by tests.
- Chart metadata has an explicit default and an explicit host-provided path.
- No host entry point needs to pass requested data until a later slice enables
  request execution.
- `request.*` remains unsupported in conformance metadata.
- Realtime construction can carry the same immutable metadata/provider boundary
  as historical execution, even though request execution remains unsupported.

Verification:

```text
cargo test -p pine-runtime request
cargo test -p pine-sema request
cargo test --workspace
```

## Slice 2: Minimal Same-Context `request.security`

Goal: support the smallest executable `request.security` form without external
bar alignment.

Initial scope:

- `request.security(syminfo.tickerid, timeframe.period, expression)`.
- Const/simple strings equal to the current chart symbol and timeframe may be
  accepted if chart metadata is available.
- `expression` must be side-effect-free and limited to scalar expressions that
  already work in the chart context.
- No optional parameters are supported yet.

Steps:

1. Add `request.security` to `pine-builtins` with a return type that follows the
   requested expression where the current type system can express it.
2. Add `barmerge.gaps_off` and `barmerge.lookahead_off` constants only if the
   accepted signature needs them in this slice.
3. Add a request-specific semantic analysis path before ordinary built-in call
   analysis accepts the call. It should validate symbol/timeframe arguments,
   analyze the requested expression under the current same-context restrictions,
   and keep unsupported request variants on the precise diagnostic path.
4. Add request-specific lowering only if ordinary call HIR cannot preserve the
   expression identity and future requested-context boundary. Do not paint
   yourself into a corner where Slice 4 must reinterpret a normal eagerly
   evaluated argument as a requested-context subexpression.
5. Reject side-effecting requested expressions during semantic analysis.
6. Add runtime dispatch in `pine-runtime::builtins::requests` that evaluates the
   same-context expression deterministically as an identity subset. It must not
   use external provider data or claim requested-context isolation yet.
7. Add runtime fixtures for direct OHLCV series, simple arithmetic, `na`, and a
   stateful helper that is either supported with isolated callsite state or
   explicitly rejected.
8. Update `tests/fixtures/conformance.tsv` with a narrow `request.security` row
   only after runtime fixtures exist. Keep a separate unsupported row for broader
   request families and unsupported request variants.
9. Keep CLI/Python/WASM output schemas unchanged unless a public error shape
   changes.

Exit criteria:

- The minimal same-context request returns the same values as the equivalent
  direct chart expression.
- The implementation and docs clearly state that same-context support is not
  general requested-context evaluation.
- Unsupported symbols, timeframes, optional parameters, and request variants are
  still diagnostic-only.
- The matrix does not imply general multi-timeframe support.
- Incremental append execution matches full historical execution for the new
  fixtures.

Verification:

```text
cargo test -p pine-builtins request
cargo test -p pine-sema request
cargo test -p pine-runtime request
cargo test --workspace
```

## Slice 3: Host Dataset Injection

Goal: let hosts provide requested datasets through one shared runtime contract.

Steps:

1. Add a runtime constructor or builder that accepts an immutable request data
   provider while preserving the existing no-provider constructor.
2. Add an in-memory provider implementation for tests and host bindings.
3. Thread the same provider and chart metadata contract through realtime runtime
   construction, and add a rollback test that proves provider data is immutable
   across repeated forming updates.
4. Add CLI support for fixture-backed requested datasets, for example a repeated
   `--request-bars SYMBOL:TIMEFRAME=path.csv` option. Keep the exact syntax
   documented and covered by tests.
5. Add Python binding support for passing requested datasets as dictionaries or
   typed helper objects that map to the same runtime provider contract.
6. Add WASM support for passing requested datasets through a deterministic JSON
   shape, or explicitly keep WASM request execution diagnostic-only until the
   next slice records the reason.
7. Add host-level tests for missing datasets, malformed datasets, duplicate keys,
   and successful same-timeframe external-symbol lookup.
8. Keep provider errors stable and machine-readable where public APIs expose
   them.

Exit criteria:

- CLI, Python, and WASM either share the same provider capability or have an
  explicitly documented temporary gap.
- Core runtime still performs no file or network I/O.
- Missing or malformed provider data produces stable errors without panics.
- Existing single-dataset scripts still run without host changes.
- Realtime request execution uses the same provider data as historical execution
  and rollback does not mutate provider-owned data.

Verification:

```text
cargo test -p pine-cli request
cargo test -p pine-runtime request
cargo check -p pine-wasm --target wasm32-unknown-unknown
maturin build --manifest-path crates/pine-python/Cargo.toml --out dist
python3 -m pytest python/tests
```

## Slice 4: Requested-Context Evaluation Cache

Goal: evaluate supported requested expressions in the requested dataset context,
with isolated state and deterministic caching.

Steps:

1. Define the cache key: syntactic callsite, requested symbol, requested
   timeframe, expression identity, and supported merge options.
2. Confirm the HIR/lowering representation from Slice 2 is sufficient for stable
   expression identity. If not, add the smallest request-context IR marker before
   widening runtime behavior.
3. Decide whether request-context evaluation reuses `HistoricalRuntime` with a
   restricted subprogram or uses a dedicated expression evaluator. Document the
   boundary before implementation.
4. Ensure requested expression state is isolated from chart-context callsite
   state, `var` storage, arrays, and drawing objects.
5. Reject requested expressions with output calls, drawing calls, input
   declarations, array mutation, UDF side effects, and other unsupported side
   effects.
6. Add fixtures for pure arithmetic, `ta.sma`, `ta.ema`, history references,
   local variables where supported, and unsupported side effects.
7. Add profile fields or request cache tests if cache growth can become
   unbounded.
8. Preserve deterministic runtime errors for requested expression failures.

Exit criteria:

- Requested expressions can be evaluated over provider bars without polluting
  chart runtime state.
- Repeated identical request calls reuse deterministic cached requested-context
  results.
- Unsupported requested expressions fail during semantic analysis where
  possible, or with stable runtime errors when provider data is required.
- Full historical and incremental append execution agree for request expression
  fixtures.

Verification:

```text
cargo test -p pine-sema request
cargo test -p pine-runtime request
cargo test -p pine-runtime --test incremental
cargo test --workspace
```

## Slice 5: Higher-Timeframe Alignment

Goal: support fixture-backed higher-timeframe `request.security` alignment.

Initial scope:

- Requested timeframe is coarser than the chart timeframe.
- Provider supplies the requested timeframe bars directly; automatic aggregation
  from chart bars is not required in the first pass.
- Start with default `gaps_off` and `lookahead_off` behavior.

Steps:

1. Implement timeframe ordering and ratio checks for the supported timeframe
   strings.
2. Add alignment helpers that map each chart bar to the correct requested bar
   value without peeking into future requested bars.
3. Define first-bar, pre-history, missing requested bar, gap, and session-boundary
   behavior through fixtures.
4. Add runtime fixtures for daily-on-minute or hourly-on-minute style alignment,
   including gaps and incomplete requested bars.
5. Add realtime forming-bar fixtures that prove higher-timeframe values roll
   back or advance only as documented.
6. Update matrix notes so `request.security` describes the exact higher-timeframe
   subset.
7. Add golden snapshot coverage only if public output shapes change.

Exit criteria:

- Higher-timeframe values are deterministic and do not use future requested
  values under the supported default merge mode.
- Historical, incremental append, and realtime forming updates agree for the
  fixture-covered subset.
- Unsupported gap/lookahead options still produce precise diagnostics.

Verification:

```text
cargo test -p pine-runtime request
cargo test -p pine-runtime realtime
cargo test --workspace
```

## Slice 6: Lower-Timeframe Boundary

Goal: decide and implement the first lower-timeframe behavior without claiming
array-returning request APIs.

Steps:

1. Record the lower-timeframe design boundary before implementation. Keep
   `request.security_lower_tf` unsupported unless typed array semantics and
   public expectations are designed in the same slice.
2. For `request.security` with a lower requested timeframe, choose a narrow
   deterministic rule such as the last confirmed requested bar inside each chart
   bar.
3. Add alignment fixtures with multiple requested bars per chart bar, missing
   intrabars, chart bars with no requested data, and forming-bar updates.
4. Ensure lower-timeframe alignment does not require unbounded memory growth.
5. Add diagnostics for lower-timeframe combinations that remain unsupported.
6. Update conformance notes to distinguish higher-timeframe and lower-timeframe
   support.

Exit criteria:

- Lower-timeframe support is either fixture-backed as partial support or remains
  explicitly unsupported with a design note.
- Any supported lower-timeframe subset has documented gap, first-bar, and
  realtime behavior.
- The matrix does not imply support for `request.security_lower_tf` unless that
  API is implemented end to end.

Verification:

```text
cargo test -p pine-sema request
cargo test -p pine-runtime request
cargo test --workspace
```

## Slice 7: Public Host Contract Hardening

Goal: make request support reliable across CLI, Python, WASM, and release
verification.

Steps:

1. Add CLI integration fixtures that run chart CSV plus requested CSV datasets.
2. Add Python tests that pass requested datasets and compare runtime output with
   CLI behavior for the same fixtures.
3. Add WASM tests for the supported request host-data JSON shape, or keep a
   documented diagnostic-only WASM gap with conformance-safe wording.
4. Add provider error snapshots if public error JSON changes.
5. Add conformance validation rules that prevent `request.*` claims without
   request fixtures.
6. Update `docs/CONFORMANCE.md`, `docs/ARCHITECTURE.md`, and `docs/RELEASE_NOTES.md`
   with the host-data contract and unsupported boundaries.
7. Ensure conformance rows distinguish supported `request.security` subsets from
   still-unsupported request APIs and advanced request families.
8. Ensure `scripts/verify.sh` covers the new host-surface tests.

Exit criteria:

- A contributor can run one documented command to verify request support across
  Rust, CLI, Python, and WASM surfaces.
- Public host APIs expose the same request semantics or explicitly documented
  temporary gaps.
- Matrix and snapshot tests catch accidental request compatibility widening.

Verification:

```text
git diff --check
scripts/verify.sh
```

## Slice 8: Phase F Closeout

Goal: close the first request and multi-timeframe platform phase with a clear
audit trail.

Steps:

1. Add `docs/PHASE_F_AUDIT.md` summarizing supported request forms, provider
   contracts, alignment rules, public host surfaces, known gaps, and verification
   evidence.
2. Confirm `tests/fixtures/conformance.tsv` describes each request claim at the
   correct granularity.
3. Refresh matrix and golden snapshots after any intentional public output or
   error-contract changes.
4. Update release notes, architecture, conformance, realtime, and execution
   semantics docs.
5. Run `git diff --check` and `scripts/verify.sh`.
6. Record any maintenance tails without weakening supported request claims.

Closeout checklist:

- Supported `request.security` forms have provider lookup, expression evaluation,
  alignment, rollback, incremental, and missing-data coverage.
- Chart metadata defaults and host-provided chart metadata are documented and
  covered by tests.
- Unsupported request variants and parameters have stable diagnostics and
  fixtures.
- CLI, Python, and WASM request host contracts are synchronized or documented as
  deliberate gaps.
- Public output schema versioning has been reviewed and snapshots are refreshed
  if needed.
- Conformance matrix rows cite fixture paths for every request claim.
- Request implementation modules remain split by responsibility; no new Phase F
  production file becomes a giant catch-all for provider or alignment semantics.
- Any lower-timeframe or requested-expression design notes are focused and
  linked from this playbook.

Verification:

```text
git diff --check
scripts/verify.sh
```

## Suggested Commit Order

1. `Add chart metadata and request provider scaffold`
2. `Support same-context request security`
3. `Add host request dataset injection`
4. `Evaluate requested context expressions`
5. `Support higher timeframe request alignment`
6. `Resolve lower timeframe request boundary`
7. `Harden request host contracts`
8. `Close Phase F audit`
