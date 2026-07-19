# Internal Restructuring Plan

This document describes how to turn the current crate-internal implementation
into a maintainable long-term structure without changing the public behavior of
Pine Compat Runtime. It is an execution plan, not a feature plan: every phase
should preserve the supported language subset, public JSON schema, CLI behavior,
Python bindings, WASM bindings, and fixture-derived conformance claims unless a
separate compatibility change explicitly requires otherwise.

The repository already has a reasonable outer architecture: syntax, semantic
analysis, IR, runtime, built-ins, CLI, Python, and WASM live in separate crates.
The main problem is crate-internal collapse, especially the oversized runtime,
semantic analyzer, and built-in registry files. The goal is to replace those
large files with small modules that have clear ownership and stable boundaries.

## Goals

- Preserve the existing public API while moving implementation details behind
  module boundaries.
- Make each crate's `lib.rs` a small public facade rather than the main
  implementation file.
- Split runtime execution, runtime values, series storage, output collection,
  JSON serialization, profiling, realtime rollback, and built-in evaluation
  into separate modules.
- Split semantic analysis into resolver, analyzer context, type checking,
  lowering, history inference, compatibility reporting, and cache modules.
- Split built-in signatures and constants by namespace so semantic and runtime
  work can evolve without editing one large registry file.
- Add structural rules that prevent future features from being added to giant
  files again.
- Keep every restructuring step small enough to review and verify.

## Non-Goals

- Do not redesign Pine semantics during this restructuring.
- Do not introduce MIR or bytecode as part of the restructuring. Those remain
  separate architecture decisions.
- Do not move host-specific behavior into core crates.
- Do not change conformance claims, diagnostics, or public result shapes unless
  a phase explicitly identifies an accidental behavior difference and updates
  fixtures with a compatibility note.
- Do not create a new crate unless module boundaries prove that a boundary must
  be enforced across package dependencies.

## Current Hotspots

- `crates/pine-runtime/src/lib.rs` contains the runtime value model, bar model,
  series store, output model, JSON serialization, historical runtime,
  realtime runtime, expression evaluation, built-in runtime implementations,
  profiling, helper algorithms, and a large inline test module.
- `crates/pine-sema/src/lib.rs` contains analysis entry points, compile cache,
  scope resolution, analyzer state, type checking, lowering, compatibility
  reporting, history inference, utility helpers, and inline tests.
- `crates/pine-builtins/src/lib.rs` contains common signature types, parameter
  lists, the complete built-in signature registry, named colors, named numeric
  constants, named string constants, series variables, and return helpers.
- `crates/pine-cli/src/main.rs` is smaller than the core hotspots, but command
  parsing, CSV handling, JSON output, matrix output, and user-facing error
  formatting should eventually be separated if CLI behavior expands.

## Target Module Layout

### `pine-runtime`

```text
crates/pine-runtime/src/
  lib.rs
  value.rs
  bar.rs
  error.rs
  series.rs
  retention.rs
  output/
    mod.rs
    model.rs
    collect.rs
    align.rs
    json.rs
  profile.rs
  runtime/
    mod.rs
    historical.rs
    realtime.rs
    context.rs
    statements.rs
    expressions.rs
    calls.rs
    history.rs
    symbols.rs
  builtins/
    mod.rs
    args.rs
    arrays.rs
    casts.rs
    colors.rs
    math.rs
    strings.rs
    ta.rs
    time.rs
    outputs.rs
    variables.rs
  algorithms/
    mod.rs
    rolling_window.rs
    numeric.rs
    formatting.rs
    random.rs
  tests/
    mod.rs
    arrays.rs
    builtins_ta.rs
    builtins_misc.rs
    outputs.rs
    runtime_core.rs
```

Ownership rules:

- `lib.rs` exports the public API and declares modules only.
- `value.rs`, `bar.rs`, `error.rs`, `series.rs`, and `profile.rs` contain data
  models and small methods only.
- `runtime/historical.rs` owns bar-by-bar execution orchestration, but delegates
  statement, expression, call, history, and symbol behavior.
- `runtime/realtime.rs` owns forming-bar rollback and confirmed/forming state
  selection only.
- `output/model.rs` owns public output structs. `output/collect.rs` and
  `output/align.rs` own mutation and padding helpers. `output/json.rs` owns the
  public JSON string serializer.
- `builtins/*` modules implement runtime behavior by namespace. They may depend
  on `runtime::context`, `value`, `series`, and `output`, but they must not own
  the main bar execution loop.
- `algorithms/*` modules contain reusable pure or nearly pure helpers used by
  multiple built-in implementations.

### `pine-sema`

```text
crates/pine-sema/src/
  lib.rs
  analysis.rs
  cache.rs
  compatibility.rs
  diagnostics.rs
  resolver.rs
  analyzer/
    mod.rs
    context.rs
    statements.rs
    expressions.rs
    calls.rs
    functions.rs
    scopes.rs
    unsupported.rs
  types/
    mod.rs
    accept.rs
    infer.rs
    promote.rs
    returns.rs
  lowering/
    mod.rs
    expressions.rs
    statements.rs
    functions.rs
    ids.rs
  history.rs
  symbols.rs
  tests/
    mod.rs
    compatibility.rs
    lowering.rs
    scopes.rs
    types.rs
```

Ownership rules:

- `lib.rs` exposes `analyze_source`, `Analysis`, `CompatibilityReport`,
  `CompileCache`, and stable public structs only.
- `resolver.rs` owns lexical scope and binding resolution data structures.
- `analyzer/context.rs` owns mutable analysis state and diagnostic collection.
- `analyzer/statements.rs`, `analyzer/expressions.rs`, and `analyzer/calls.rs`
  own AST walking and validation behavior.
- `types/*` owns qualifier, value-kind, argument acceptance, promotion, and
  return inference helpers.
- `lowering/*` owns AST-to-HIR construction and stable id assignment.
- `history.rs` owns history requirement collection and `max_bars_back`
  inference.
- `compatibility.rs` owns feature-use and unsupported-feature reporting.

### `pine-builtins`

```text
crates/pine-builtins/src/
  lib.rs
  signature.rs
  registry.rs
  returns.rs
  namespaces/
    mod.rs
    arrays.rs
    colors.rs
    inputs.rs
    math.rs
    outputs.rs
    strings.rs
    ta.rs
    time.rs
    variables.rs
  constants/
    mod.rs
    colors.rs
    floats.rs
    ints.rs
    strings.rs
    series.rs
```

Ownership rules:

- `signature.rs` owns `BuiltinSignature`, `BuiltinPhase`, `BuiltinParam`,
  `Accepts`, and `ReturnSpec`.
- `namespaces/*` owns signature slices grouped by namespace.
- `registry.rs` owns the combined registry and lookup helpers.
- `constants/*` owns named constants and built-in series variable metadata.
- `returns.rs` owns reusable return-type helper functions.

### `pine-cli`

```text
crates/pine-cli/src/
  main.rs
  commands/
    mod.rs
    analyze.rs
    matrix.rs
    run.rs
  csv.rs
  output.rs
  errors.rs
```

This crate does not need to be restructured first. Split it after the core
crates are stable or when CLI behavior grows enough that command-specific tests
become awkward.

## Target Dependency Direction

Allowed direction:

```text
pine-syntax -> no project dependencies
pine-ir     -> no runtime or host dependencies
pine-builtins -> pine-ir only
pine-sema   -> pine-syntax, pine-ir, pine-builtins
pine-runtime -> pine-ir, pine-builtins
pine-cli    -> syntax, sema, runtime
pine-python -> syntax, sema, runtime
pine-wasm   -> syntax, sema, runtime
```

Forbidden direction:

- `pine-builtins` must not depend on `pine-runtime`.
- `pine-ir` must not depend on syntax, semantic analysis, runtime, CLI, Python,
  or WASM crates.
- Core crates must not depend on `pine-cli`, `pine-python`, or `pine-wasm`.
- Runtime modules must not import CLI/Python/WASM formatting or host behavior.
- Semantic modules must not call runtime evaluators.

## Migration Strategy

Use mechanical moves first, then boundary improvements. A phase is complete
only when formatting, clippy, tests, and public fixture outputs remain stable.

Recommended verification for every phase:

```text
cargo fmt --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
```

When a phase touches public binding behavior, also run:

```text
cargo check -p pine-wasm --target wasm32-unknown-unknown
maturin build --manifest-path crates/pine-python/Cargo.toml --out dist
python -m pytest python/tests
```

For release-grade completion, run:

```text
scripts/verify.sh
```

## Phase 0: Baseline and Safety Net

Goal: make the current behavior measurable before moving code.

Tasks:

- Record current file sizes for `crates/pine-runtime/src/lib.rs`,
  `crates/pine-sema/src/lib.rs`, and `crates/pine-builtins/src/lib.rs`.
- Run the full workspace test suite and record the command output in the pull
  request or issue for the restructuring branch.
- Generate or confirm existing runtime snapshots and conformance metadata.
- Identify any currently failing tests. If failures exist, document them before
  restructuring and do not hide them inside structural commits.
- Add a short PR checklist requiring that public API names and output schemas
  remain stable for mechanical move phases.

Acceptance criteria:

- There is a known green or explicitly documented baseline.
- No restructuring commit starts from an unknown test state.
- The restructuring branch has a written list of public functions and structs
  that must remain exported.

Suggested commits:

1. `Record restructuring baseline`

## Phase 1: Extract Runtime Tests

Goal: remove the first major source of file size without changing production
code.

Tasks:

- Move the inline runtime test module from `crates/pine-runtime/src/lib.rs` into
  `crates/pine-runtime/src/tests/mod.rs`.
- If the test module remains very large, split it by behavior after the first
  move: runtime core, TA built-ins, arrays, outputs, strings/time/math, and
  realtime-adjacent cases.
- Keep helpers private to the test module where possible.
- Do not rewrite assertions during this phase unless a move requires a small
  path fix.

Acceptance criteria:

- Runtime production code is separated from runtime tests.
- `crates/pine-runtime/src/lib.rs` no longer contains a large inline test
  module.
- All moved tests still run under `cargo test -p pine-runtime`.

Suggested commits:

1. `Move runtime inline tests`
2. `Split runtime tests by behavior`

## Phase 2: Turn Runtime `lib.rs` into a Facade

Goal: move low-coupling runtime data models and serializers out of `lib.rs`.

Tasks:

- Extract `PineValue` and small value conversion helpers to `value.rs`.
- Extract `RuntimeError` to `error.rs`.
- Extract `Bar`, `BarUpdate`, and `BarUpdateKind` to `bar.rs`.
- Extract `SeriesStore` and basic series buffer helpers to `series.rs`.
- Extract history retention policy to `retention.rs`.
- Extract `RuntimeResult`, output structs, and output traits to `output/model.rs`.
- Extract public JSON serialization functions and JSON helpers to
  `output/json.rs`.
- Extract `RuntimeProfile`, `RuntimeProfiledResult`, and
  `HistoryRetentionMode` to `profile.rs` unless `HistoryRetentionMode` remains
  more naturally owned by `retention.rs` with a public re-export.
- Re-export the same public items from `lib.rs`.

Acceptance criteria:

- Public users can still import the same public runtime items from
  `pine_runtime`.
- There is no behavior change in runtime tests or binding tests.
- `lib.rs` is mostly module declarations and public re-exports.

Suggested commits:

1. `Extract runtime value and bar models`
2. `Extract runtime series storage`
3. `Extract runtime output models`
4. `Extract runtime JSON serialization`
5. `Extract runtime profiling models`

## Phase 3: Split Runtime Orchestration

Goal: separate execution orchestration from expression and built-in behavior.

Tasks:

- Move `HistoricalRuntime` construction, `append_bars`, `append_bar`, result
  creation, profile creation, and bar finalization to `runtime/historical.rs`.
- Move `RealtimeRuntime` to `runtime/realtime.rs`.
- Move symbol/value stores and current-bar helper methods to
  `runtime/context.rs` or `runtime/symbols.rs`.
- Move statement evaluation to `runtime/statements.rs`.
- Move expression evaluation, unary/binary evaluation, switch evaluation, and
  loop expression behavior to `runtime/expressions.rs`.
- Move history-reference evaluation to `runtime/history.rs`.
- Keep method receivers on `HistoricalRuntime` at first. Avoid introducing a
  large trait hierarchy during the mechanical split.

Acceptance criteria:

- The main historical runtime file describes the bar execution lifecycle rather
  than every supported operation.
- Statement and expression behavior can be reviewed without scrolling through
  built-in implementations.
- Realtime rollback behavior is isolated and testable.

Suggested commits:

1. `Extract historical runtime orchestration`
2. `Extract realtime runtime`
3. `Extract runtime symbol context`
4. `Extract statement evaluation`
5. `Extract expression and history evaluation`

## Phase 4: Split Runtime Built-In Implementations

Goal: end the giant built-in implementation block and make new built-ins land
in namespace modules.

Tasks:

- Move call argument helpers to `builtins/args.rs`.
- Move output-producing calls to `builtins/outputs.rs`.
- Move `input.*` and built-in series variable evaluation to
  `builtins/variables.rs`.
- Move array constructors, mutation, reads, sorting, searching, and numeric
  helpers to `builtins/arrays.rs`.
- Move numeric casts and scalar casts to `builtins/casts.rs`.
- Move color helpers to `builtins/colors.rs`.
- Move math helpers to `builtins/math.rs`.
- Move string helpers to `builtins/strings.rs`.
- Move time and timeframe helpers to `builtins/time.rs`.
- Move TA functions and their state helpers to `builtins/ta.rs`, then split TA
  further if the file remains too large. Good second-level groups are rolling
  windows, EMA/RMA chains, oscillators, pivots, flow indicators, and trend
  helpers.
- Move reusable helpers such as rolling windows, numeric comparisons,
  formatter helpers, and random number helpers to `algorithms/*` modules.

Acceptance criteria:

- Adding a new `ta.*` function does not require editing output, string, array,
  or core expression modules.
- Adding a new `str.*` function does not require touching TA or array modules.
- Built-in runtime behavior remains covered by existing fixture and unit tests.
- No single built-in namespace file exceeds an agreed threshold without a
  follow-up split issue. A practical threshold is 1,500 lines for implementation
  modules and 800 lines for model/helper modules.

Suggested commits:

1. `Extract runtime builtin argument helpers`
2. `Extract output builtin runtime handlers`
3. `Extract array builtin runtime handlers`
4. `Extract scalar and color runtime handlers`
5. `Extract string and time runtime handlers`
6. `Extract math runtime handlers`
7. `Extract TA runtime handlers`
8. `Extract reusable runtime algorithms`

## Phase 5: Replace the Giant Runtime Call Match

Goal: keep call dispatch readable while avoiding a second hidden monolith.

Tasks:

- Replace the single `eval_call` match with a small dispatcher that routes by
  namespace or exact call family.
- Keep dispatch deterministic and explicit. Avoid macro-heavy registration
  until the module split is stable.
- Use helpers such as `eval_output_call`, `eval_array_call`, `eval_ta_call`,
  `eval_math_call`, `eval_string_call`, `eval_time_call`, `eval_color_call`, and
  `eval_cast_call`.
- Return `None` from namespace dispatchers when the function name is not owned
  by that namespace, then produce one consistent unsupported runtime error at
  the top level.
- Add small focused tests for the unsupported-call path and representative
  dispatch paths if existing tests do not cover them clearly.

Acceptance criteria:

- The top-level call dispatcher fits on one screen or close to it.
- Namespace dispatchers live next to their implementations.
- Unsupported runtime call errors remain stable.

Suggested commits:

1. `Route runtime calls by namespace`
2. `Cover runtime call dispatch errors`

## Phase 6: Split `pine-builtins`

Goal: make the shared semantic/runtime signature registry maintainable.

Tasks:

- Move signature model types to `signature.rs`.
- Move reusable return helpers to `returns.rs`.
- Move signatures into `namespaces/*` modules by namespace.
- Move named colors, float constants, int constants, string constants, and
  series variable metadata into `constants/*` modules.
- Keep existing lookup functions stable: `get_phase_1_builtin`,
  `is_phase_1_builtin`, `named_color`, `named_float_constant`,
  `named_int_constant`, `named_string_constant`, and
  `builtin_series_value_type`.
- Build the combined registry in `registry.rs` from namespace slices.

Acceptance criteria:

- Semantic analysis and runtime imports do not change outside ordinary module
  path fixes.
- New built-in signatures are added to namespace files, not to a giant root
  registry file.
- Built-in lookup behavior remains unchanged.

Suggested commits:

1. `Extract builtin signature model`
2. `Split builtin signatures by namespace`
3. `Split builtin constants by kind`
4. `Rebuild builtin registry facade`

## Phase 7: Split `pine-sema`

Goal: separate semantic responsibilities without changing HIR output.

Tasks:

- Move public result structs and `analyze_source` facade to `analysis.rs`.
- Move compile cache types and keying logic to `cache.rs`.
- Move compatibility report models and feature reporting helpers to
  `compatibility.rs`.
- Move scope resolver and binding key logic to `resolver.rs`.
- Move analyzer mutable state to `analyzer/context.rs`.
- Move statement validation/lowering orchestration to `analyzer/statements.rs`.
- Move expression validation/lowering orchestration to
  `analyzer/expressions.rs`.
- Move call validation, argument validation, and method resolution to
  `analyzer/calls.rs`.
- Move user-defined function handling to `analyzer/functions.rs`.
- Move unsupported-feature classification to `analyzer/unsupported.rs`.
- Move type acceptance, promotion, and return inference helpers to `types/*`.
- Move HIR construction and id assignment to `lowering/*`.
- Move history requirement inference to `history.rs`.
- Move initial symbol construction to `symbols.rs`.
- Move inline tests to `tests/*`, grouped by compatibility, scopes, type
  inference, and lowering.

Acceptance criteria:

- HIR produced for existing fixtures is unchanged.
- Diagnostics and compatibility reports are unchanged for existing fixtures.
- `Analyzer` no longer owns unrelated helper functions in one file.
- Future type-system changes can be made in `types/*` without editing lowering
  code unless HIR output changes.

Suggested commits:

1. `Extract semantic analysis facade and cache`
2. `Extract semantic compatibility reporting`
3. `Extract semantic resolver`
4. `Extract analyzer context and statement handling`
5. `Extract expression and call analysis`
6. `Extract type inference helpers`
7. `Extract HIR lowering helpers`
8. `Extract history inference`
9. `Move semantic inline tests`

## Phase 8: Normalize Tests and Fixtures

Goal: make tests mirror the new architecture.

Tasks:

- Keep cross-crate behavior fixtures in `tests/fixtures` and crate integration
  tests.
- Keep module-level edge cases near the module that owns the logic.
- Prefer fixture-backed tests for Pine language behavior and small unit tests
  for pure helpers.
- Move broad runtime behavior tests out of `src/lib.rs` into either
  `crates/pine-runtime/tests/*` or `src/tests/*` depending on whether private
  helper access is needed.
- Add a short `tests/snapshots/README.md` update only if snapshot ownership
  changes.

Acceptance criteria:

- Test file names make it clear which subsystem failed.
- Private helper tests do not force production helper visibility unless there
  is a real API reason.
- Integration tests continue to cover CLI, runtime fixtures, realtime,
  incremental execution, Python bindings, and WASM build checks.

Suggested commits:

1. `Group runtime tests by subsystem`
2. `Group semantic tests by subsystem`
3. `Normalize fixture ownership notes`

## Phase 9: Add Structural Guardrails

Goal: prevent the repository from drifting back into giant files.

Tasks:

- Document module ownership rules in `CONTRIBUTING.md` or a short architecture
  appendix.
- Add a lightweight file-size check script that fails when a production Rust
  source file exceeds the agreed threshold unless it is allowlisted.
- Suggested default thresholds:
  - Facade files: 300 lines.
  - Model/helper modules: 800 lines.
  - Implementation modules: 1,500 lines.
  - Generated or table-heavy registry modules: allowlisted with a comment and
    split plan.
- Add the file-size check to local verification or CI after the restructuring
  is complete.
- Require every new built-in to include a semantic signature change, runtime
  implementation change, fixture coverage, and conformance metadata update when
  applicable.

Acceptance criteria:

- New code has an obvious destination module.
- Oversized modules are caught during verification.
- Allowlisted large files have a documented reason and an owner.

Suggested commits:

1. `Document module ownership rules`
2. `Add source file size guardrail`
3. `Wire structure checks into verification`

## Phase 10: Optional Boundary Improvements

Goal: improve internal APIs after the mechanical split has settled.

Only start this phase after Phases 1-9 are complete and tests are stable.

Candidates:

- Introduce a small runtime call context type so built-in handlers do not need
  unrestricted access to all `HistoricalRuntime` fields.
- Replace ad hoc call argument access with a typed argument reader shared by
  built-in handlers.
- Convert selected pure helper functions into unit-tested algorithm modules.
- Consider table-driven runtime dispatch only after namespace dispatch is clear
  and stable.
- Consider moving high-value pure built-in algorithms into `pine-builtins` only
  if they do not require runtime state and can stay independent of
  `pine-runtime`.
- Consider a new internal crate only if two existing crates need the same logic
  and dependency direction cannot stay clean otherwise.

Acceptance criteria:

- Boundary improvements reduce coupling rather than merely moving code again.
- Runtime state mutation points are easier to audit.
- No public API churn is introduced without a release note.

Suggested commits:

1. `Introduce runtime builtin context`
2. `Introduce typed runtime argument reader`
3. `Promote pure algorithms to shared modules`

## Final Completion Criteria

The restructuring is complete when all of the following are true:

- `crates/pine-runtime/src/lib.rs`, `crates/pine-sema/src/lib.rs`, and
  `crates/pine-builtins/src/lib.rs` are facades or small registries rather than
  implementation monoliths.
- No production implementation module exceeds the agreed threshold without an
  explicit allowlist entry and follow-up plan.
- Runtime, semantic analysis, and built-in registry ownership boundaries match
  this document or a documented successor decision.
- The public Rust API remains source-compatible for the existing CLI, Python,
  and WASM crates.
- Existing fixture outputs, diagnostics, compatibility reports, runtime
  profiles, incremental execution behavior, and realtime rollback behavior are
  unchanged except for deliberate, documented fixes.
- `scripts/verify.sh` passes.
- `CONTRIBUTING.md` or another contributor-facing document tells future
  contributors where to add syntax, semantic, runtime, and built-in changes.

## Review Checklist

Use this checklist for every restructuring pull request:

- Does this PR move code without changing behavior unless explicitly stated?
- Are public exports preserved or intentionally re-exported from the facade?
- Is the new module the long-term owner of the moved code?
- Did any private helper become public only to satisfy tests?
- Are fixtures, snapshots, diagnostics, and public JSON outputs unchanged?
- Did the PR reduce the size or responsibility of an oversized file?
- Is the next feature likely to land in a focused module instead of a facade?
- Were formatting, clippy, workspace tests, and relevant binding checks run?