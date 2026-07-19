# Task Breakdown

This document tracks implementation work at the level of issues or focused
commits. The initial v0.1 baseline is implemented; future work should widen
coverage through fixtures and compatibility metadata rather than broad,
untested claims.

## Phase 0: Repository Foundation

Status: complete.

- [x] Create Cargo workspace.
- [x] Create initial crates.
- [x] Add `.gitignore`.
- [x] Add license.
- [x] Add contribution guidelines.
- [x] Add CI for format, clippy, and tests.
- [x] Verify `cargo fmt --check`.
- [x] Verify `cargo clippy --workspace --all-targets -- -D warnings`.
- [x] Verify `cargo test --workspace`.

## Phase 1: Syntax

Status: baseline complete.

- [x] Add `SourceFile`.
- [x] Add `Span` and line/column mapping.
- [x] Add diagnostic model.
- [x] Add token model.
- [x] Add lexer for identifiers, literals, operators, comments, version
  directives, history brackets, and call punctuation.
- [x] Add lexer tests.
- [x] Add AST model for the executable Phase 1 subset.
- [x] Add Pratt expression parser.
- [x] Add parser support for calls, named arguments, qualified names, and
  history references.
- [x] Add parser support for declarations and reassignment.
- [x] Add parser tests.
- [x] Add parse recovery tests for malformed scripts.
- [x] Add fixture-based parser tests.
- [x] Add parser support for `if` syntax as parse-only when execution is not
  enabled.
- [x] Add tuple expression and tuple assignment parsing.
- [x] Add expression-body function declaration parsing.
- [x] Add simple `for` parsing as unsupported syntax.

## Phase 2: Semantic Analysis and Compatibility Gating

Status: baseline complete.

- [x] Add compatibility report data model.
- [x] Add first unsupported-feature diagnostics.
- [x] Add Phase 1 builtin registry scaffold.
- [x] Wire analyzer to the builtin registry.
- [x] Add stable diagnostic code catalog.
- [x] Add minimal global symbol table.
- [x] Add scope resolver.
- [x] Add type model integration.
- [x] Add qualifier promotion rules.
- [x] Add builtin signature validation.
- [x] Add constant-history-offset validation.
- [x] Add guarded dynamic-history-offset support.
- [x] Add `varip` rejection fixture.
- [x] Add first `request.*` unsupported fixture.
- [x] Add `strategy.*`, drawing object, array, import, and alert
  unsupported fixtures.
- [x] Assign stable `SeriesId`, `CallSiteId`, and `VarSlotId` during lowering.
- [x] Lower AST to executable HIR for the Phase 1 subset.

## Phase 3: Minimal Historical Runtime

Status: baseline complete.

- [x] Add bar input model and CSV fixture reader.
- [x] Add runtime value model.
- [x] Add frame/current-value store.
- [x] Add committed series store.
- [x] Add persistent `var` store.
- [x] Evaluate literals and identifiers.
- [x] Evaluate unary and binary expressions.
- [x] Evaluate ternary expressions.
- [x] Evaluate history references with constant offsets.
- [x] Implement `na` and `nz`.
- [x] Implement initial `input.*` value injection using defaults.
- [x] Implement initial `plot` output collection.
- [x] Implement `hline` and `fill` output collection.
- [x] Implement `ta.sma`.
- [x] Implement `ta.ema`.
- [x] Add first runtime tests.

## Phase 4: Expanded Built-Ins and Output

Status: baseline complete.

- [x] Define initial normalized result JSON schema in code.
- [x] Add CLI `run`.
- [x] Add tuple lowering.
- [x] Implement `ta.rma`.
- [x] Implement `ta.rsi`.
- [x] Implement `ta.macd`.
- [x] Implement `ta.bb`.
- [x] Implement `ta.tr` and `ta.atr`.
- [x] Implement `ta.change`, `ta.cross`, `ta.crossover`, and `ta.crossunder`.
- [x] Implement highest/lowest.
- [x] Add color registry and `color.new`.
- [x] Add selected `math.*` functions.
- [x] Add conformance matrix output.

## Phase 5: Python Binding

Status: baseline complete.

- [x] Add `pine-python` crate.
- [x] Add PyO3 and maturin configuration.
- [x] Expose `compile_script`.
- [x] Expose `analyze_script`.
- [x] Expose `run_script`.
- [x] Add Python tests.
- [x] Add package metadata.

## Phase 6: Performance and Incremental Runtime

Status: baseline complete.

- [x] Add compile cache.
- [x] Profile runtime allocations.
- [x] Optimize rolling TA built-ins.
- [x] Add append-bar execution.
- [x] Verify incremental execution against full recomputation.
- [x] Evaluate optional bytecode VM after MIR semantics stabilize.

## Phase 7: Realtime and Wider Compatibility

Status: baseline complete for forming-bar rollback and explicit `varip`
rejection.

- [x] Define forming-bar model.
- [x] Add rollback semantics.
- [x] Implement or reject `varip` precisely.
- [x] Add repeated-update fixtures.
- [x] Expand syntax and semantic support based on conformance gaps.
- [x] Add optional WASM binding after the core API is stable.

## Release Hardening

Status: baseline complete; the release gate remains mandatory for every slice.

- [x] Add CI coverage for Python binding tests.
- [x] Add CI coverage for WASM build checks.
- [x] Document local Python binding test setup.
- [x] Move the compatibility matrix from registry-seeded claims to
  fixture-derived conformance metadata.
- [x] Expand realtime fixture coverage beyond rollback and `var` behavior.
- [x] Decide whether user-defined functions enter the executable subset or stay
  diagnostic-only for the next release.
- [x] Add release notes describing the supported subset and explicit
  unsupported boundaries.

## Next Language Expansion

Status: v0.1 expansion complete. The next stage is planned in
[`NEXT_LANGUAGE_EXPANSION_PLAYBOOK.md`](NEXT_LANGUAGE_EXPANSION_PLAYBOOK.md).

- [x] Parse indentation into executable blocks.
- [x] Lower `if`/`else` statements to HIR.
- [x] Execute `if`/`else` branches in the historical and realtime runtimes.
- [x] Keep skipped conditional series bar-aligned by committing `na`.
- [x] Support stateful calls inside `if` blocks with callsite state advancing
  only when the branch executes.
- [x] Cover conditional SMA, EMA, BB, RSI, ATR, and MACD fixtures.
- [x] Support normal block-local declarations inside `if` branches.
- [x] Support tuple block-local declarations inside `if` branches.
- [x] Add expression-body user-defined function execution by inlining.
- [x] Support named arguments for user-defined functions.
- [x] Evaluate user-defined function arguments once into callsite-local
  temporaries.
- [x] Add multi-statement user-defined function execution with final expression
  returns.
- [x] Reject recursive functions and function side effects.
- [x] Support executable `for` loops for inclusive integer ranges with optional
  explicit step.
- [x] Support `break` and `continue` inside executable `for` loops.
- [x] Support scalar and tuple `for` expression results in declarations.
- [x] Add fixture-derived conformance metadata for block statements.
- [x] Add fixture-derived conformance metadata for user-defined functions.
- [x] Preserve UDF parameter shadowing by local declarations and loop counters.
- [x] Preserve tuple declaration shadowing in local scopes.
- [x] Cover local `var` declarations in blocks, loops, and UDF callsites.
- [x] Implement full local-scope declarations and shadowing rules.

## Next Planned Expansion

Status: baseline complete for the current partial `switch`, `while`, and typed
array subsets. Further expansion is selected through the current capability and
language playbooks.

- [x] Add partial `switch` expression support.
- [x] Add partial `while` statement support with an iteration guard.
- [x] Design and implement partial float array support.

## Long-Term Backlog

Status: active maintenance. Completed items below refer only to their current
fixture-backed subsets; broader Pine compatibility remains tracked in
[`LONG_TERM_EXECUTION_PLAN.md`](LONG_TERM_EXECUTION_PLAN.md) and
[`NEXT_INTERNAL_CAPABILITY_PLAN.md`](NEXT_INTERNAL_CAPABILITY_PLAN.md).

- [x] Harden loop and branch edge cases.
- [x] Expand scalar typed-array support beyond float arrays.
- [ ] Design unsupported collection families and remaining Pine array
  semantics.
- [x] Revisit history and qualifier semantics for the current executable subset.
- [ ] Add per-variable `max_bars_back` and deeper history diagnostics.
- [ ] Add more built-in coverage.
- [x] Design fixture-backed host-neutral drawing object outputs; additional
  families and lifecycle behavior remain partial.
- [x] Design deterministic host-provided `request.security` data; broader
  `request.*` families remain unsupported.
- [x] Design the fixture-backed long-only strategy runtime; short exposure,
  reversals, custom OCA, and richer broker contracts remain deferred.
- [x] Design local runtime alert output; external delivery remains host-owned
  and deferred.
- [x] Design scalar and supported scalar-array `varip` persistence; broader
  value families remain partial or unsupported.
- [x] Design exact-key imports plus the fixture-backed local/imported UDT and
  method subsets; remote registry behavior and broader identity flows remain
  deferred.
