# Implementation Plan

This plan favors a serious long-term foundation over quick partial execution.

## v0.1 Baseline

The first standalone loop is implemented:

```text
source.pine + bars.csv
  -> parse
  -> analyze
  -> run
  -> result.json
```

The current baseline includes Rust library crates, a CLI, Python bindings,
WASM bindings, compile caching, incremental append-bar execution, optimized
rolling state for selected TA built-ins, executable `if`/`else` blocks,
user-defined functions, realtime forming-bar rollback, and a fixture-derived
compatibility matrix.

The runtime still makes compatibility claims by tested feature. Recursive
functions, function side effects, `varip` intrabar persistence, `request.*`,
`strategy.*`, alerts, imports, drawing objects, array history snapshots, and
per-variable `max_bars_back` declarations remain outside the executable subset
and should produce diagnostics.
Stateful calls inside `if` blocks advance their callsite state only when the
branch executes. Skipped series values are committed as `na` so history buffers
remain bar-aligned.

## v0.1 User-Defined Function Decision

User-defined functions are in the v0.1 executable subset, with explicit
boundaries:

- Single-expression and multi-statement block bodies are supported.
- Positional and named arguments are supported and evaluated once into
  callsite-local temporaries.
- Each syntactic UDF callsite owns independent state for inlined stateful calls
  and local `var` declarations.
- Parameter shadowing by local declarations and loop counters is supported.
- Recursive functions are rejected.
- Output side effects, input declarations, global reassignment, and
  side-effecting calls passed as arguments are rejected.

This makes UDFs a supported release feature rather than diagnostic-only syntax.

## Phase 0: Repository Foundation

Deliverables:

- Rust workspace.
- README and architecture docs.
- License and contribution guidelines.
- Formatting and linting configuration.
- Basic CI for format, clippy, and tests.

Exit criteria:

- `cargo fmt --check`, `cargo clippy`, and `cargo test` run in CI.

## Phase 1: Syntax

Deliverables:

- Source file abstraction.
- Tokenizer.
- AST.
- Parser for indicator declarations, variable declarations, assignments,
  expressions, function calls, named arguments, blocks, and history references.
- Syntax diagnostics with line and column spans.
- Golden parser tests.

Exit criteria:

- Parser handles a curated fixture set of common indicator scripts.
- Invalid syntax produces useful diagnostics without panics.
- Parser may accept syntax that later phases reject as unsupported.

## Phase 2: Semantic Analysis and Compatibility Gating

Deliverables:

- Scope resolver.
- Type and qualifier model.
- Name resolution for built-ins.
- Unsupported feature detection.
- AST to HIR lowering.
- Compatibility report.
- Built-in signature registry.
- Callsite and series id assignment for executable expressions.

Exit criteria:

- Analyzer can distinguish supported scripts from scripts requiring
  `strategy.*`, `request.*`, labels, unsupported array variants, imports, or
  realtime-only behavior.
- Analyzer accepts only the Phase 1 executable subset for runtime execution.
- Analyzer emits stable diagnostic codes for unsupported features.

## Phase 3: Minimal Historical Runtime

Deliverables:

- Bar data model.
- Runtime context.
- Series store.
- Persistent state store for `var`.
- Expression evaluator.
- Statement evaluator.
- `na` semantics.
- History reference semantics.
- Plot, hline, and fill output collection for the minimal subset.

Exit criteria:

- Runtime executes global-scope indicator scripts over historical OHLCV
  fixtures.
- Results are deterministic and snapshot tested.
- Constant and guarded dynamic integer history offsets, `var`, `na`, `nz`,
  core output calls, and fixture-covered `ta.*` helpers are covered by
  fixtures.

## Phase 4: Expanded Built-Ins and Output

Deliverables:

- `ta.*` built-ins for common indicators.
- Normalized JSON result model.
- CLI `analyze` and `run`.
- Tuple lowering for tuple-returning built-ins.

Exit criteria:

- CLI can run fixture-covered TA, math, string, array, input, and output
  examples.
- Output includes normalized series, annotations, fills, diagnostics, and
  compatibility reports. Input calls execute their `defval` values unless the
  Rust runtime, CLI, Python, or WASM host supplies call-site keyed overrides.

## Phase 5: Python Binding

Deliverables:

- PyO3 binding.
- maturin build configuration.
- Python package API.
- Python tests.

Exit criteria:

- `pip install -e .` or `maturin develop` exposes `compile_script`,
  `analyze_script`, and `run_script`.

## Phase 6: Performance and Incremental Runtime

Deliverables:

- Compile cache.
- Runtime allocation profiling.
- Optimized rolling TA functions.
- Optional bytecode VM.
- Incremental append-bar execution.

Current compile cache API lives in `pine-sema` as `CompileCache`. It caches
complete analysis results by source name and source text so CLI, Python, and
future host integrations can avoid repeated parse and semantic passes for
unchanged scripts.

Runtime storage profiling is exposed by `pine-runtime::run_historical_profiled`
and by the CLI:

```text
pine-compat run script.pine --bars bars.csv --profile
```

The profile reports allocation-sensitive storage lengths, capacities, and max
depth for series buffers, plot values, and runtime state maps. It also reports
history retention mode, maximum static offset, and dynamic-offset presence. It
is a portable storage profile, not a process-wide allocator hook. Static-only
history is trimmed to HIR-inferred per-series retention requirements. Dynamic
history offsets keep full committed series history up to a runtime cap, or to
the indicator-level `max_bars_back` bound when provided, so they cannot grow
storage without bound.

Rolling TA state is optimized for `ta.sma`, `ta.bb`, `ta.stdev`,
`ta.variance`, `ta.range`, `ta.dev`, `ta.vwma`, `ta.wma`, `ta.hma`,
`ta.highest`, and `ta.lowest`. These functions now maintain per-callsite
rolling windows instead of allocating a fresh window from committed history on
every bar.

Append-bar execution is exposed by `pine-runtime::HistoricalRuntime`:

```rust
let mut runtime = HistoricalRuntime::new(&hir);
runtime.append_bar(bar)?;
let partial = runtime.result();
```

The existing `run_historical` helper is implemented on top of this stateful
runtime, so full historical execution and incremental append execution share the
same code path.

Runtime fixtures are also checked through an integration test that compares
full historical execution with incremental `append_bar` execution for every
script in `tests/fixtures/runtime`.

The optional bytecode VM was evaluated and deferred. Direct HIR execution
remains the reference runtime until MIR exists and profiling shows instruction
dispatch is a real bottleneck. See
[`BYTECODE_VM_EVALUATION.md`](BYTECODE_VM_EVALUATION.md).

Exit criteria:

- Re-running a compiled program over large historical data is acceptably fast.
- Incremental update path matches full recomputation for supported fixtures.

## Phase 7: Realtime and Wider Compatibility

Deliverables:

- Forming bar support.
- Rollback model.
- Precise `varip` rejection until intrabar persistence is implemented.
- Expanded language features.
- Optional WASM binding.

Exit criteria:

- Realtime fixture tests define and verify repeated updates on the same bar.

## Release Hardening

Before publishing a v0.1 baseline, the CI and local verification path should
cover every exposed entry point:

```text
cargo fmt --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
cargo check -p pine-wasm --target wasm32-unknown-unknown
maturin build --manifest-path crates/pine-python/Cargo.toml --out dist
python -m pip install dist/*.whl
python -m pytest python/tests
```

The remaining release-hardening work should focus on release notes that describe
the supported subset and explicit unsupported boundaries.

## Development Rules

- Add fixtures before or alongside behavior.
- Unsupported features must produce diagnostics.
- Avoid host-specific assumptions in core crates.
- Do not use TradingView source, private APIs, or proprietary data.
- Keep public APIs small until semantics are stable.
