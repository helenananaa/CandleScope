# Code Review Fix Results

This document tracks execution of
[CODE_REVIEW_ISSUE_VERIFICATION.md](CODE_REVIEW_ISSUE_VERIFICATION.md) one item
at a time. It distinguishes direct fixes from items that should remain design
notes, deferred investigations, or non-bug records.

## CR-001: README References Missing `tests/conformance/`

**Source context**

- Review source: `CODE_REVIEW_EXECUTION_PLAN.md:949`
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-001-readme-references-missing-testsconformance`
- Affected file: `README.md`

**Classification: Direct documentation bug**

The README package layout listed `tests/conformance/`, but the current tree has
no such directory. The authoritative conformance inventory is
`tests/fixtures/conformance.tsv`, and fixture categories live under
`tests/fixtures/`.

**Action**

Updated the README layout to describe `tests/fixtures/`, the nested
`conformance.tsv`, and generated matrix snapshots.

**Verification**

- `find tests/fixtures -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort`
  confirms the actual fixture directories.
- `find tests -maxdepth 3 -type f` confirms `tests/fixtures/conformance.tsv`
  exists and no `tests/conformance/` file tree is present.

**Result: Fixed**

---

## CR-002: Workspace Repository Metadata Is Empty

**Source context**

- Review source: `CODE_REVIEW_EXECUTION_PLAN.md:950`
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-002-workspace-repository-metadata-is-empty`
- Affected file: `Cargo.toml`

**Classification: Direct package metadata bug**

`[workspace.package] repository` was an empty string. The current git remote is
`ssh://git@ssh.github.com:443/Ryan00956/pine-compat-runtime.git`, which gives a
clear repository identity for package metadata.

**Action**

Set the workspace repository metadata to the public HTTPS form:
`https://github.com/Ryan00956/pine-compat-runtime`.

**Verification**

- `git remote -v` identifies the repository owner/name as
  `Ryan00956/pine-compat-runtime`.
- `sed -n '1,35p' Cargo.toml` confirms `[workspace.package] repository` is no
  longer empty.

**Result: Fixed**

---

## CR-003: Structure Guard Only Excludes `/src/tests/` Paths

**Source context**

- Review source: `CODE_REVIEW_EXECUTION_PLAN.md:951`
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-003-structure-guard-only-excludes-srctests-paths`
- Affected file: `scripts/check_structure.py`

**Classification: Direct tooling bug**

The structure guard intended to count production Rust files, but it only
excluded files under `/src/tests/`. `crates/pine-runtime/src/strategy/broker/tests.rs`
is test support included by `#[cfg(test)] mod tests;`, so counting it as an
implementation file inflated the production-file report.

**Action**

Added an explicit `is_test_support_file` predicate that excludes `/src/tests/`,
`tests.rs`, and `*_tests.rs` files while avoiding broad substring matching on
paths containing the word "test".

**Verification**

- `rg -n "mod tests|cfg\\(test\\)|tests;" crates/pine-runtime/src/strategy`
  confirms `strategy/broker/tests.rs` is included under `#[cfg(test)]`.
- `python3 scripts/check_structure.py` now checks 134 production Rust source
  files and no longer reports `strategy/broker/tests.rs` in the largest files.

**Result: Fixed**

---

## CR-004: No Workspace Dependency Table

**Source context**

- Review source: `CODE_REVIEW_EXECUTION_PLAN.md:952`
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-004-no-workspace-dependency-table`
- Affected file: `Cargo.toml`

**Classification: Deferred engineering preference, not a current bug**

The workspace does not define `[workspace.dependencies]`, but the current
external dependencies are not obviously duplicated across crates with divergent
versions. The verification recommendation is also conditional: add a workspace
dependency table once dependencies are shared or version drift appears.

**Action**

No code change. Do not introduce workspace dependency indirection until there is
a concrete shared-dependency drift problem or a release policy requiring it.

**Verification**

- `rg` over `Cargo.toml` and `crates/*/Cargo.toml` shows no current
  `[workspace.dependencies]` table.
- Current external dependencies are crate-local, such as `chrono`/`regex` in
  runtime, `pyo3` in Python, and `wasm-bindgen`/`serde_json` in WASM.

**Result: Deferred, no fix applied**

---

## CR-005: Parser Expression Recursion Has No Depth Limit

**Source context**

- Review source: `CODE_REVIEW_EXECUTION_PLAN.md:953`
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-005-parser-expression-recursion-has-no-depth-limit`
- Affected file: `crates/pine-syntax/src/parser.rs`

**Classification: Direct robustness bug**

`parse_expr` and `parse_prefix` recursively parse nested expressions without a
budget. A deeply nested expression can consume process stack before the parser
has a chance to return a normal diagnostic.

**Action**

Added an internal `MAX_EXPR_DEPTH` budget and parser `expr_depth` counter.
`parse_expr` now emits `E_PARSE_EXPR_DEPTH` and returns `None` once nesting goes
past the parser limit, allowing existing statement recovery to handle the rest
of the line. Added a unit test with nested parentheses beyond the limit.

**Verification**

- `cargo test -p pine-syntax rejects_expression_nesting_past_depth_limit`
  passes.
- `cargo test -p pine-syntax` passes: 34 unit tests, 1 fixture test, and doctests.

**Result: Fixed**

---

## CR-006: Diagnostic Columns Are Byte Offsets, Not Character Columns

**Source context**

- Review source: `CODE_REVIEW_EXECUTION_PLAN.md:954`
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-006-diagnostic-columns-are-byte-offsets-not-character-columns`
- Affected file: `crates/pine-syntax/src/source.rs`

**Classification: Direct user-visible diagnostic bug**

`SourceFile::line_col` kept byte offsets internally, which is correct for
`Span`, but also used byte distance as the displayed column. Multi-byte UTF-8
characters before a diagnostic therefore inflated the user-facing column number.

**Action**

Changed displayed column calculation to count `chars()` from the line start to
the byte offset while leaving stored line starts and spans byte-based. Added a
UTF-8 regression test.

**Verification**

- `cargo test -p pine-syntax maps_utf8_offsets_to_character_columns` passes.
- `cargo test -p pine-syntax` passes: 35 unit tests, 1 fixture test, and doctests.

**Result: Fixed**

---

## CR-007: Phase-J Soft Keyword Parsing Has Uneven Lookahead Guards

**Source context**

- Review source: `CODE_REVIEW_EXECUTION_PLAN.md:955`
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-007-phase-j-soft-keyword-parsing-has-uneven-lookahead-guards`
- Affected file: `crates/pine-syntax/src/parser_phase_j.rs`

**Classification: Direct parser bug for the confirmed `export` subset**

The original review grouped several soft keywords together, but current code
already guarded `library`, `type`, and `method`. The confirmed bug was narrower:
`export` always entered export-declaration parsing, so `export = 5` could not be
parsed as an ordinary declaration.

**Action**

Added a lookahead guard so `export` is treated as a Phase-J export declaration
only when followed by an item identifier. Added a regression test for
`export = 5`.

**Verification**

- `cargo test -p pine-syntax parses_export_as_plain_identifier_when_not_followed_by_item_name`
  passes.
- `cargo test -p pine-syntax` passes: 36 unit tests, 1 fixture test, and doctests.

**Result: Fixed for the confirmed subset**

---

## CR-008: Numeric Lexer Lacks Exponent/Underscore Forms

**Source context**

- Review source: `CODE_REVIEW_EXECUTION_PLAN.md:956`
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-008-numeric-lexer-lacks-exponentunderscore-forms`
- Affected files:
  - `crates/pine-syntax/src/lexer.rs`
  - `crates/pine-syntax/tests/fixtures.rs`
  - `tests/fixtures/syntax/phase1_basic.pine`
  - `tests/fixtures/conformance.tsv`
  - `tests/snapshots/matrix.json`

**Classification: Direct lexer compatibility bug for scientific notation; underscore support deferred**

The lexer consumed only decimal digits and an optional fractional part. Official
Pine documentation shows float literals with `e`/`E` notation, such as `3e8`
and `6.02E-23`, so splitting `1e6` into `Int(1)` plus identifier `e6` was a
confirmed syntax compatibility bug. Numeric underscore separators remain
deferred because the current local scope and the checked official literal docs
do not establish that they are required.

**Action**

Added exponent parsing for integer and decimal numeric literals when `e`/`E` is
followed by digits or a signed digit sequence. The lexer now emits a float token
for `3e8`, `6.02E-23`, and `1E+6`. Added a lexer unit test, extended the syntax
fixture, added a conservative conformance row, and refreshed the matrix JSON
snapshot through the existing snapshot workflow.

**Verification**

- `cargo test -p pine-syntax lexes_scientific_float_literals` passes.
- `cargo test -p pine-syntax parses_phase_1_basic_fixture` passes.
- `cargo test -p pine-syntax` passes: 37 unit tests, 1 fixture test, and doctests.
- `UPDATE_SNAPSHOTS=1 cargo test -p pine-cli matrix_output_matches_golden_snapshot`
  refreshed `tests/snapshots/matrix.json`.
- `cargo test -p pine-cli matrix` passes.

**Result: Fixed for scientific notation; underscore separators deferred**

---

## CR-009: HIR/Runtime Errors Do Not Carry Source Spans

**Source context**

- Review source: `CODE_REVIEW_EXECUTION_PLAN.md:957`
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-009-hirruntime-errors-do-not-carry-source-spans`
- Related duplicate: `CR-017`
- Affected areas:
  - `crates/pine-ir/src/lib.rs`
  - `crates/pine-runtime/src/error.rs`
  - CLI, Python, and WASM diagnostic/error surfaces

**Classification: Confirmed design/contract gap, not a safe isolated bug fix**

`HirStmt` and `HirExpr` do not carry source spans, and `RuntimeError` only carries
`message`. The gap is real, but a coherent fix requires preserving spans during
lowering, threading them through runtime evaluation and builtins, and deciding
how host-facing runtime diagnostics expose those spans. Adding a field only to
`RuntimeError` would not make runtime errors source-locatable because the HIR
nodes currently have no source location to attach.

**Action**

No code change in this pass. Treat CR-009 and CR-017 as one future diagnostic
contract phase. That phase should explicitly cover HIR shape, runtime error
construction helpers, host JSON/Python/WASM output compatibility, tests, and any
schema/version impact.

**Verification**

- `crates/pine-ir/src/lib.rs` shows `HirStmt`/`HirExpr` contain kind/type/history
  data but no `Span`.
- `crates/pine-runtime/src/error.rs` shows `RuntimeError { message: String }`.
- `rg RuntimeError` shows many runtime and builtin constructors, confirming this
  is a broad API migration rather than a local edit.

**Result: Deferred, no fix applied**

---

## CR-010: `ta.*` Implicit History Table Is Manually Coupled To Runtime

**Source context**

- Review source: `CODE_REVIEW_EXECUTION_PLAN.md:958`
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-010-ta-implicit-history-table-is-manually-coupled-to-runtime`
- Affected areas:
  - `crates/pine-sema/src/history.rs`
  - `crates/pine-runtime/src/builtins/ta/*`
  - builtin signature/runtime metadata

**Classification: Confirmed architectural drift risk, fixed with guardrails**

`crates/pine-builtins/src/history.rs` now declares implicit history
requirements for selected `ta.*` calls, and `crates/pine-sema/src/history.rs`
consumes that metadata instead of owning a separate callee table. Runtime
implementations still live separately in `crates/pine-runtime/src/builtins/ta/*`,
but fixed-offset implicit reads now use a debug/test assertion helper and
reviewed runtime metadata is reconciled against the shared declaration.
The remaining risk is real: if runtime starts reading deeper history than the
shared metadata retains, output can silently become `na`. This item is still not
a concrete current failing fixture like CR-015/CR-019.

**Action**

Introduced a focused metadata phase: builtin history requirements are declared
once in `pine-builtins` and consumed by sema. Added a metadata registration test,
kept the existing sema lowering regression over the major implicit `ta.*`
requirements, and added a runtime reviewed-list reconciliation test
(`runtime_implicit_history_calls_match_shared_metadata`). Bound the existing
`ta.sar` end-to-end numeric regression to its HIR retention requirements
(`high[2]`, `low[2]`, `close[1]`), the existing `ta.dmi` numeric regression to
`high[1]`, `low[1]`, and `close[1]`, and the existing `ta.supertrend` numeric
regression to `close[1]`. Also bound the existing `ta.kc` and `ta.kcw` numeric
regressions to `close[1]`, and the existing `ta.mfi` and `ta.tsi` numeric
regressions to `close[1]`. Bound the existing `ta.cross`, `ta.crossover`, and
`ta.crossunder` numeric regression to `close[1]` and series `baseline[1]`.
Added `HistoricalRuntime::read_declared_series_history` so fixed-offset runtime
implicit-history reads assert in debug/test builds when their requested offset
exceeds declared retention, while explicit history and length-derived reads keep
Pine warmup/`na` semantics.

**Verification**

- `crates/pine-builtins/src/history.rs` contains the shared
  `BUILTIN_HISTORY_METADATA` table for `ta.tr`, `ta.atr`, `ta.dmi`, `ta.sar`,
  `ta.change`, `ta.mom`, `ta.roc`, and cross helpers.
- `crates/pine-sema/src/history.rs` consumes
  `pine_builtins::builtin_history_requirement(...)`.
- Runtime TA implementations are separate from that table under
  `crates/pine-runtime/src/builtins/ta/`.
- `history_metadata_names_are_registered_builtins` ensures declared history
  metadata names have registered builtin signatures.
- `infers_implicit_ta_history_requirements_by_series` covers inferred history
  behavior.
- `runtime_implicit_history_calls_match_shared_metadata` checks reviewed runtime
  implicit-history reads against `BUILTIN_HISTORY_METADATA`.
- `runs_sar_over_historical_bars` asserts both the SAR numeric sequence and the
  HIR retention requirements for `high[2]`, `low[2]`, and `close[1]`.
- `runs_dmi_over_historical_bars` asserts both the DMI numeric sequences and the
  HIR retention requirements for `high[1]`, `low[1]`, and `close[1]`.
- `runs_supertrend_over_historical_bars` asserts both the Supertrend numeric
  sequences and the HIR retention requirement for `close[1]`.
- `runs_keltner_channels_over_historical_bars` and
  `runs_keltner_channel_width_over_historical_bars` assert both their numeric
  sequences and the HIR retention requirement for `close[1]`.
- `runs_mfi_over_historical_bars` and `runs_tsi_over_historical_bars` assert
  both their numeric sequences and the HIR retention requirement for `close[1]`.
- `runs_cross_functions_over_historical_bars` asserts the cross helper numeric
  sequences and the HIR retention requirements for `close[1]` and series
  `baseline[1]`.
- `read_declared_series_history` is used by builtin OHLC lookback helpers and
  fixed-offset TA source lookbacks for MFI, TSI, CMO, and cross helpers.

**Result: Fixed with shared metadata, reviewed-list reconciliation, fixed-offset runtime assertions, and retention-bound numeric regressions**

---

## CR-011: Analyzer And Lowering Type Inference Are Parallel Implementations

**Source context**

- Review source: `CODE_REVIEW_EXECUTION_PLAN.md:959`
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-011-analyzer-and-lowering-type-inference-are-parallel-implementations`
- Affected files:
  - `crates/pine-sema/src/analyzer/calls.rs`
  - `crates/pine-sema/src/analyzer/expressions.rs`
  - lowering call sites using `type_of_expr_with_params`

**Classification: Confirmed maintainability/refactor item, not a current isolated bug**

`Analyzer::return_type` and `type_of_expr_with_params` both match many
`ReturnSpec` variants. That duplication can drift, but the current review item
does not identify a specific expression where analyzer and lowering currently
disagree. A broad extraction would touch core semantic inference and lowering
behavior without a narrow failing fixture.

**Action**

No code change in this pass. Defer to a refactor slice that first adds parity
tests for representative `ReturnSpec` families, then extracts a shared pure
return-type helper used by both analyzer diagnostics and lowering.

**Verification**

- `rg` confirms `Analyzer::return_type` in `calls.rs` and repeated
  `ReturnSpec` matching in `type_of_expr_with_params`.
- The duplicated paths cover many builtins and array/method return variants,
  making this a broad refactor rather than a one-line correction.

**Result: Deferred, no fix applied**

---

## CR-012: Sema Expression/UDF Recursion Has No General Depth Limit

**Source context**

- Review source: `CODE_REVIEW_EXECUTION_PLAN.md:960`
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-012-sema-expressionudf-recursion-has-no-general-depth-limit`
- Affected files:
  - `crates/pine-sema/src/analyzer/context.rs`
  - `crates/pine-sema/src/analyzer/expressions.rs`
  - `crates/pine-sema/src/analyzer/functions.rs`
  - `crates/pine-sema/src/analyzer/methods.rs`
  - `crates/pine-sema/src/analysis.rs`
  - `crates/pine-sema/src/tests/{type_core.rs,scopes.rs}`

**Classification: Direct robustness bug**

Semantic expression analysis recursively walks AST expressions, and user-defined
function/method bodies can recursively expand through deep acyclic call chains.
Existing recursive-function checks catch cycles, but they do not bound large
non-recursive inputs.

**Action**

Added sema resource budgets:

- `MAX_SEMA_EXPR_DEPTH` limits semantic expression nesting and emits
  `E_SEMA_EXPR_DEPTH`.
- `MAX_FUNCTION_CALL_DEPTH` limits UDF/method call-chain depth and emits
  `E_FUNCTION_CALL_DEPTH`.

Added regression tests for a deeply nested unary expression and a deep acyclic
function call chain. This does not address lowering-time HIR expansion limits;
that remains tracked by CR-037.

**Verification**

- `cargo test -p pine-sema rejects_deep_semantic_expression_nesting` passes.
- `cargo test -p pine-sema rejects_deep_acyclic_function_call_chain` passes.
- `cargo test -p pine-sema` passes: 250 unit tests, 58 fixture tests, and
  doctests.

**Result: Fixed for sema analysis depth; lowering expansion remains CR-037**

---

## CR-013: Reassignment Updates Symbol Type Directly From RHS

**Source context**

- Review source: `CODE_REVIEW_EXECUTION_PLAN.md:961`
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-013-reassignment-updates-symbol-type-directly-from-rhs`
- Affected files:
  - `crates/pine-sema/src/analyzer/statements.rs`
  - `crates/pine-sema/src/tests/scopes.rs`

**Classification: Direct semantic narrowing bug for confirmed reassignment subset**

The confirmed failure mode is symbol narrowing: a variable initially inferred as
`series float` could be reassigned from a `const int`, after which the analyzer
stored the RHS type directly. That loses the stronger qualifier and wider
numeric kind in the symbol table.

**Action**

Changed reassignment updates to merge target and RHS types instead of replacing
the symbol type with the RHS. The merged type keeps the strongest qualifier and
the common kind, so `series float` reassigned from `const int` remains
`series float`. Invalid assignments no longer update the symbol type after
emitting `E_ASSIGN_TYPE`.

This does not broaden the current policy for whether a const/simple declaration
may later receive a series value; it only prevents narrowing an already broader
symbol.

**Verification**

- `cargo test -p pine-sema reassignment_does_not_narrow_existing_series_symbol`
  passes.
- `cargo test -p pine-sema` passes: 251 unit tests, 58 fixture tests, and
  doctests.

**Result: Fixed for confirmed narrowing subset**

---

## CR-014: 11 Missing Sema Diagnostic Codes Are Covered By CR-059

**Source context**

- Review source: `CODE_REVIEW_EXECUTION_PLAN.md:962`
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-014-11-missing-sema-diagnostic-codes-are-covered-by-cr-059`
- Superseding item: `CR-059`
- Affected file: `docs/DIAGNOSTIC_CODES.md`

**Classification: Superseded duplicate**

The missing sema diagnostic codes listed in CR-014 are included in the broader
CR-059 diagnostic-code audit. Fixing them here would split one documentation
consistency task into two overlapping edits.

**Action**

No separate change. Defer diagnostic-code documentation updates to CR-059, where
all missing emitted codes can be added and guarded by a drift test together.

**Verification**

- `CODE_REVIEW_ISSUE_VERIFICATION.md` marks CR-014 as superseded by CR-059.
- The broader CR-059 list includes the sema codes named by CR-014, such as
  `E_STRATEGY_MODE`, `E_SCRIPT_DECL_LOCATION`, `E_LOOP_CONTROL`,
  `E_UNKNOWN_FUNCTION`, and `E_METHOD_RECEIVER_TYPE`.

**Result: Superseded, no separate fix applied**

---

## CR-015: Integer Binary Arithmetic Collapses To `Float`

**Source context**

- Review source: `CODE_REVIEW_EXECUTION_PLAN.md:963`
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-015-integer-binary-arithmetic-collapses-to-float`
- Affected files:
  - `crates/pine-runtime/src/runtime/expressions.rs`
  - `crates/pine-runtime/src/tests/runtime_control_flow.rs`
  - `crates/pine-runtime/src/tests/arrays.rs`

**Classification: Direct runtime correctness bug**

Runtime binary arithmetic converted both operands to `f64` and returned
`PineValue::Float` for every numeric operator. That made integral expressions
such as `n - 1` unusable in runtime consumers that require `PineValue::Int`,
including `for` loop bounds and array indexes.

**Action**

Split numeric runtime arithmetic by operator:

- `Int + Int`, `Int - Int`, and `Int * Int` now preserve `PineValue::Int` when
  checked integer arithmetic succeeds.
- Integer overflow in those operators falls back to finite float arithmetic
  rather than panicking.
- `/` remains float-producing.
- `Int % Int` preserves `PineValue::Int`, returns `na` for zero divisors, and
  falls back to the existing float path for non-integer operands.

Added regressions for `for i = 0 to n - 1` and `array.get(values, k - 1)`.

**Verification**

- `cargo test -p pine-runtime runs_for_loop_with_computed_integer_bound` passes.
- `cargo test -p pine-runtime runs_array_get_with_computed_integer_index` passes.
- `cargo test -p pine-runtime` passes: 394 unit tests, incremental/profile/realtime
  integration tests, and doctests.

**Result: Fixed**

---

## CR-016: Under-Retained Series History Silently Reads As `Na`

**Source context**

- Review source: `CODE_REVIEW_EXECUTION_PLAN.md:964`
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-016-under-retained-series-history-silently-reads-as-na`
- Related item: `CR-010`
- Affected areas:
  - `crates/pine-runtime/src/retention.rs`
  - `crates/pine-runtime/src/series.rs`
  - `crates/pine-runtime/src/runtime/context.rs`

**Classification: Confirmed consequence of history metadata drift, not a direct isolated fix**

Runtime retention is driven by sema-provided `program.series_history`. If that
metadata underestimates a required offset, `SeriesStore::read` returns `na`.
That fallback is correct for normal warmup and out-of-range Pine history reads,
so changing it globally into an error would create false positives and alter
supported behavior.

**Action**

The CR-010 metadata phase has started: implicit history requirements are now a
shared declaration consumed by sema, reviewed runtime implicit-history reads are
reconciled against that metadata, and the
SAR/DMI/Supertrend/KC/KCW/MFI/TSI/Cross numeric regressions are tied to HIR
retention requirements. Fixed-offset runtime implicit-history reads now go
through `read_declared_series_history`, which keeps release behavior unchanged
but debug-asserts when a runtime implicit read asks for more history than sema
declared. Explicit history and length-derived reads continue using the normal
`SeriesStore::read` warmup/`Na` behavior.

**Verification**

- `SeriesRetention::from_program` builds static retention from
  `program.series_history`.
- `commit_current_series` commits each series using
  `series_retention.max_depth_for(series_id)`.
- `SeriesStore::read` returns `PineValue::Na` when the requested offset is not in
  the retained buffer.
- `read_declared_series_history` asserts fixed-offset implicit reads against
  `series_retention.max_depth_for(series_id)` before delegating to
  `SeriesStore::read`.

**Result: Fixed for fixed-offset implicit-history drift; explicit history and length-derived warmup semantics remain unchanged**

---

## CR-017: `RuntimeError` Has No Source Span

**Source context**

- Review source: `CODE_REVIEW_EXECUTION_PLAN.md:965`
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-017-runtimeerror-has-no-source-span`
- Superseding item: `CR-009`
- Affected file: `crates/pine-runtime/src/error.rs`

**Classification: Superseded duplicate**

`RuntimeError` has only `message`, but this is the runtime half of CR-009. A
runtime error cannot be source-locatable until HIR/source span propagation exists
and host-facing diagnostics define how to expose those locations.

**Action**

No separate change. Keep the runtime error shape unchanged until the CR-009
diagnostic contract phase handles HIR spans, runtime error construction, and
CLI/Python/WASM surfaces together.

**Verification**

- `crates/pine-runtime/src/error.rs` defines `RuntimeError { message: String }`.
- `CODE_REVIEW_ISSUE_VERIFICATION.md` marks CR-017 as superseded by CR-009.

**Result: Superseded, no separate fix applied**

---

## CR-018: Runtime Recursion, Symbol Scans, And Realtime Clone Costs

**Source context**

- Review source: `CODE_REVIEW_EXECUTION_PLAN.md:966`
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-018-runtime-recursion-symbol-scans-and-realtime-clone-costs`
- Affected files:
  - `crates/pine-runtime/src/lib.rs`
  - `crates/pine-runtime/src/runtime/historical.rs`
  - `crates/pine-runtime/src/runtime/expressions.rs`
  - `crates/pine-runtime/src/tests/runtime_core.rs`

**Classification: Direct runtime safety bug for recursion; performance subclaims deferred**

The recursion portion is confirmed: `HistoricalRuntime::eval_expr` recursively
re-enters through unary, binary, ternary, switch, block, call argument, history,
tuple, and user-type expression paths without a runtime-level budget. Parser and
sema limits now protect normal source input, but runtime still needs its own
defense for constructed HIR and host-facing internal contracts.

The symbol linear-scan and realtime clone-cost claims remain plausible
performance concerns, not correctness bugs established by this pass. They need a
profile fixture or measurement before changing data structures or rollback
state.

**Action**

Added `MAX_RUNTIME_EVAL_DEPTH` and `HistoricalRuntime::eval_expr_depth`, then
wrapped `eval_expr` with depth accounting before dispatching to the existing
expression evaluator. When the runtime budget is exceeded, evaluation now
returns `RuntimeError { message: "runtime expression evaluation exceeded maximum depth" }`.

Added a regression that starts from a normally analyzed program to keep runtime
builtin-symbol initialization valid, replaces its statements with a directly
constructed deeply nested HIR expression, and verifies the runtime returns the
new depth error instead of recursing unboundedly.

**Verification**

- `cargo test -p pine-runtime rejects_hir_expression_past_runtime_eval_depth` passes.
- `cargo test -p pine-runtime` passes: 395 unit tests, incremental/profile/realtime
  integration tests, and doctests.
- `cargo fmt -- crates/pine-runtime/src/lib.rs crates/pine-runtime/src/runtime/historical.rs crates/pine-runtime/src/runtime/expressions.rs crates/pine-runtime/src/tests/runtime_core.rs` completed.

**Result: Fixed for runtime recursion; symbol-scan and realtime clone-cost items deferred for performance audit**

---

## CR-019: Computed `ta.*`/`math.*` Lengths Become Invalid

**Source context**

- Review source: `CODE_REVIEW_EXECUTION_PLAN.md:967`
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-019-computed-tamath-lengths-become-invalid`
- Root-cause item: `CR-015`
- Affected files:
  - `crates/pine-runtime/src/tests/builtins_ta_averages.rs`
  - `crates/pine-runtime/src/tests/builtins_math.rs`
  - `tests/fixtures/runtime/computed_lengths.pine`
  - `tests/fixtures/conformance.tsv`
  - `tests/snapshots/matrix.json`

**Classification: Confirmed runtime bug, fixed by CR-015 root-cause change and covered here with regressions**

The original failure came from integer arithmetic collapsing to `PineValue::Float`.
Length consumers such as `ta.sma` and `math.sum` intentionally read runtime
lengths with `as_i64()`, so a computed length like `n * 1` became non-integer to
those call sites and degraded to the invalid-length path.

CR-015 changed runtime integer arithmetic to preserve `PineValue::Int` for
integer `+`, `-`, `*`, and `%`. This item adds direct coverage for the affected
`ta.*`/`math.*` length users instead of changing each `as_i64().unwrap_or(0)`
call site.

**Action**

Added runtime regressions for:

- `ta.sma(close, n * 1)`, expecting the computed length to produce normal SMA
  values instead of all `na`.
- `math.sum(close, n + 0)`, expecting the computed length to produce normal
  rolling sums instead of all `na`.

Added `tests/fixtures/runtime/computed_lengths.pine` and updated the
`math.sum`/`ta.sma` conformance rows to state fixture-backed computed integer
length support. Refreshed `tests/snapshots/matrix.json` for the conformance
metadata change.

**Verification**

- `cargo test -p pine-runtime runs_sma_with_computed_integer_length` passes.
- `cargo test -p pine-runtime runs_math_sum_with_computed_integer_length` passes.
- `cargo test -p pine-runtime --test incremental` passes.
- `UPDATE_SNAPSHOTS=1 cargo test -p pine-cli matrix_output_matches_golden_snapshot` refreshed the matrix snapshot.
- `cargo test -p pine-cli matrix_output_matches_golden_snapshot` passes after refresh.
- `cargo test -p pine-runtime` passes: 397 unit tests, incremental/profile/realtime
  integration tests, and doctests.

**Result: Fixed via CR-015 root-cause change, with direct CR-019 regressions and fixture-backed conformance updates**

---

## CR-020: Timezone Support Is UTC-Only

**Source context**

- Review source: `CODE_REVIEW_EXECUTION_PLAN.md:968`
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-020-timezone-support-is-utc-only`
- Affected areas:
  - `crates/pine-runtime/src/builtins/time.rs`
  - `crates/pine-runtime/src/tests/builtins_time.rs`
  - `docs/BUILTIN_SIGNATURES.md`
  - `docs/LANGUAGE_SCOPE.md`
  - `tests/fixtures/conformance.tsv`

**Classification: Fixed compatibility gap**

The runtime intentionally supports only UTC-equivalent timezone strings today:
`UTC`, `Etc/UTC`, `GMT`, `Z`, `+0000`, and `+00:00`. IANA/exchange timezone
support would require a real timezone-data decision and affects host/WASM bundle
shape, so it is not a small bug fix.

The current subset is already explicit in the repo: `BUILTIN_SIGNATURES.md`
documents UTC-only calendar functions and `str.format_time`; `LANGUAGE_SCOPE.md`
refers to UTC time helpers; `tests/fixtures/conformance.tsv` and the generated
matrix describe time helpers, `timestamp`, `timeframe.change`, and
`str.format_time` as UTC subsets.

**Action**

No implementation change. Keep the runtime error for unsupported timezone
strings and leave IANA/exchange timezone semantics for a dedicated compatibility
expansion phase.

**Verification**

- `crates/pine-runtime/src/builtins/time.rs` gates timezone arguments through
  `is_supported_utc_timezone`.
- `crates/pine-runtime/src/tests/builtins_time.rs` already includes
  `rejects_unsupported_calendar_function_timezone` for `America/New_York`.
- `docs/BUILTIN_SIGNATURES.md` explicitly says unsupported time zones are
  runtime errors until exchange/IANA timezone support is implemented.
- `tests/fixtures/conformance.tsv` records UTC subset claims for time-related
  features.

**Result: Deferred, no fix applied**

---

## CR-021: EMA/RMA/RSI Warmup May Differ From TradingView

**Source context**

- Review source: `CODE_REVIEW_EXECUTION_PLAN.md:969`
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-021-emarmarsi-warmup-may-differ-from-tradingview`
- Affected areas:
  - `crates/pine-runtime/src/builtins/ta.rs`
  - `crates/pine-runtime/src/builtins/ta/averages.rs`
  - `crates/pine-runtime/src/builtins/ta/flow.rs`

**Classification: Deferred evidence, no fix applied**

The current implementation is confirmed to seed EMA/RMA-family state from the
first observed source value. RSI, ATR, DMI/ADX, Supertrend, DEMA/TEMA, and other
recursive indicators build on that behavior.

The review claim is not yet a proven bug because the pass does not include a
trusted numeric oracle for TradingView warmup values. Changing seeding without
fixture-backed expected outputs would risk replacing one undocumented behavior
with another.

**Action**

No code change. Treat this as a numeric-conformance investigation: collect
accepted golden outputs for representative EMA, RMA, RSI, ATR, DMI/ADX, and
Supertrend inputs, then decide per builtin whether the seeding rule needs to
change.

**Verification**

- `rma_next` and `ema_next` both return `source` when previous state is absent.
- `eval_rsi` initializes average gain/loss as absent state and then uses
  `rma_next` on subsequent bars.
- Existing runtime tests cover deterministic current behavior, but they are not
  external TradingView oracle fixtures.

**Result: Deferred, no fix applied**

---

## CR-022: Drawing Object Limits Are Fixed And Error On Overflow

**Source context**

- Review source: `CODE_REVIEW_EXECUTION_PLAN.md:970`
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-022-drawing-object-limits-are-fixed-and-error-on-overflow`
- Affected areas:
  - `crates/pine-runtime/src/builtins/drawings/labels.rs`
  - `crates/pine-runtime/src/builtins/drawings/lines.rs`
  - `crates/pine-runtime/src/builtins/drawings/boxes.rs`
  - `tests/fixtures/conformance.tsv`

**Classification: Confirmed documented compatibility gap, no code fix in this pass**

The implementation uses hard runtime caps of 500 labels, 500 lines, and 500
boxes, and returns `RuntimeError` when a script creates more. That differs from
TradingView's retention model, but it is not currently a hidden bug in this
repo: the conformance matrix explicitly describes `label.new`, `line.new`, and
`box.new` as partial features with a 500-object runtime limit.

A correct alignment change is larger than replacing an error with `remove(0)`: it
needs declaration settings for `max_labels_count`, `max_lines_count`, and
`max_boxes_count`, a decision for evicted object IDs and setter/delete behavior,
and host snapshot expectations for retained versus evicted objects.

**Action**

No code change. Leave this for a dedicated drawing-retention compatibility phase
that can update declaration analysis, HIR/runtime settings, runtime retention,
conformance notes, and output snapshots together.

**Verification**

- `MAX_LABELS`, `MAX_LINES`, and `MAX_BOXES` are fixed at 500 in
  `crates/pine-runtime/src/lib.rs`.
- `eval_label_new`, `eval_line_new`, and `eval_box_new` return runtime errors
  when the corresponding output vector reaches the cap.
- `tests/fixtures/conformance.tsv` documents the 500-object runtime limit for
  label, line, and box creation.
- Existing output tests cover the current limit-error behavior.

**Result: Deferred, no fix applied**

---

## CR-023: Array Bounds Behavior Differs From Official Pine Errors

**Source context**

- Review source: `CODE_REVIEW_EXECUTION_PLAN.md:971`
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-023-array-bounds-behavior-is-project-documented-but-differs-from-official-pine-errors`
- Affected areas:
  - `crates/pine-runtime/src/builtins/arrays.rs`
  - `crates/pine-runtime/src/tests/arrays.rs`
  - `docs/BUILTIN_SIGNATURES.md`
  - `tests/fixtures/conformance.tsv`

**Classification: Confirmed documented compatibility gap, no code fix in this pass**

Negative indexes themselves are supported by official Pine and by this runtime.
The confirmed divergence was out-of-bounds handling: `array.get` returned `na`,
and mutation/removal paths either no-op'd or returned `na`, while official Pine
raises runtime errors for indexes outside the positive or negative bounds.

This pass aligns existing-array out-of-bounds reads and mutations with runtime
errors while preserving valid negative indexing from the array end.

**Action**

- `array_read_index` and `array_insert_index` now return `RuntimeError` when a
  real array exists but normalization fails.
- Valid negative indexes remain supported for `array.get`, `array.set`,
  `array.insert`, and `array.remove`.
- Empty `array.pop`/`array.shift` behavior remains documented separately as
  `na`; direct empty `array.remove` is a bounds runtime error.

**Verification**

- Unit tests cover positive and negative out-of-bounds `array.get`, mutation
  paths, and direct empty `array.remove`.
- Runtime-error fixtures cover `array.get` positive/negative bounds,
  `array.set` bounds, `array.insert` bounds, and empty `array.remove`.
- `docs/BUILTIN_SIGNATURES.md`, `docs/EXECUTION_SEMANTICS.md`, and
  `tests/fixtures/conformance.tsv` now document out-of-bounds runtime errors.

**Result: Fixed**

---

## CR-024: Computed Array Indexes And Sizes Inherit Integer Collapse

**Source context**

- Review source: `CODE_REVIEW_EXECUTION_PLAN.md:972`
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-024-computed-array-indexes-and-sizes-inherit-integer-collapse`
- Root-cause item: `CR-015`
- Affected files:
  - `crates/pine-runtime/src/tests/arrays.rs`
  - `tests/fixtures/runtime/computed_array_operands.pine`
  - `tests/fixtures/conformance.tsv`
  - `tests/snapshots/matrix.json`

**Classification: Confirmed runtime bug, fixed by CR-015 root-cause change and covered here with regressions**

Like CR-019, this was a downstream effect of integer arithmetic collapsing to
`PineValue::Float`. Array indexes and `array.new_*` sizes intentionally read
runtime operands through `as_i64()`, so computed integer expressions such as
`k - 1` or `n + 1` failed before CR-015 preserved integer arithmetic.

**Action**

Kept the CR-015 numeric fix as the root-cause implementation and added direct
array regressions for:

- `array.get(values, k - 1)`.
- `array.set(values, n - 1, close)` and `array.set(values, n, close + 10)`.
- `array.new_float(n + 1)`.

Added `tests/fixtures/runtime/computed_array_operands.pine` and updated the
`array.new_float`, `array.get`, and `array.set` conformance rows to record
fixture-backed computed integer operand support. Refreshed
`tests/snapshots/matrix.json` for the conformance metadata change.

**Verification**

- `cargo test -p pine-runtime runs_array_get_with_computed_integer_index` passes.
- `cargo test -p pine-runtime runs_array_mutation_and_size_with_computed_integer_operands` passes.
- `cargo test -p pine-runtime --test incremental` passes.
- `UPDATE_SNAPSHOTS=1 cargo test -p pine-cli matrix_output_matches_golden_snapshot` refreshed the matrix snapshot.
- `cargo test -p pine-cli matrix_output_matches_golden_snapshot` passes after refresh.

**Result: Fixed via CR-015 root-cause change, with direct CR-024 regressions and fixture-backed conformance updates**

---

## CR-025: Missing Strategy Default Quantity Fails

**Source context**

- Review source: `CODE_REVIEW_EXECUTION_PLAN.md:973`
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-025-missing-strategy-default-quantity-fails-but-at-sema-rather-than-runtime`
- Affected files:
  - `crates/pine-ir/src/lib.rs`
  - `crates/pine-sema/src/analyzer/strategy.rs`
  - `crates/pine-sema/tests/fixtures.rs`
  - `crates/pine-runtime/src/tests/strategy.rs`
  - `tests/fixtures/sema/supported_strategy_entry_default_quantity.pine`
  - `tests/fixtures/runtime/strategy_builtin_default_quantity.pine`
  - `tests/fixtures/conformance.tsv`
  - `tests/snapshots/matrix.json`
  - `docs/BUILTIN_SIGNATURES.md`

**Classification: Direct compatibility bug**

The user-visible failure was real: a bare `strategy.entry("L", strategy.long)`
was rejected during sema unless the script explicitly configured a fixed default
quantity. TradingView's default strategy quantity is fixed `1`, so the current
subset should allow omitted `qty` and use that default.

**Action**

Changed `StrategySettings::default()` to set `default_qty` to
`StrategyDefaultQuantity::Fixed(1.0)`. Sema no longer emits the missing-qty
arity error for `strategy.entry`; it still validates explicit `qty` values and
still rejects unsupported default quantity types. An explicit
`default_qty_value` now sets the fixed default quantity even when
`default_qty_type` is omitted, matching the fixed default type.

Replaced the old unsupported missing-qty sema fixture with a supported fixture,
added a runtime fixture for builtin default quantity, updated conformance and
`BUILTIN_SIGNATURES.md`, and refreshed the matrix snapshot.

**Verification**

- `cargo test -p pine-sema --test fixtures strategy` passes.
- `cargo test -p pine-runtime strategy_entry_uses_builtin_default_qty_when_qty_is_absent` passes.
- `cargo test -p pine-runtime --test incremental` passes.
- `UPDATE_SNAPSHOTS=1 cargo test -p pine-cli matrix_output_matches_golden_snapshot` refreshed the matrix snapshot.
- `cargo test -p pine-cli matrix_output_matches_golden_snapshot` passes after refresh.
- `cargo test -p pine-sema` passes: 251 unit tests, 58 fixture tests, and doctests.
- `cargo test -p pine-runtime` passes: 399 unit tests, incremental/profile/realtime
  integration tests, and doctests.

**Result: Fixed**

---

## CR-026: Strategy Fill Timing Uses Current Bar Close Instead Of TradingView Next Bar Open

**Source context**

- Review source: `CODE_REVIEW_EXECUTION_PLAN.md:974`
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-026-strategy-fill-timing-uses-current-bar-close-instead-of-tradingview-next-bar-open`
- Affected files:
  - `crates/pine-runtime/src/builtins/strategy.rs`
  - `crates/pine-runtime/src/strategy/broker/mod.rs`
  - `crates/pine-runtime/src/tests/strategy.rs`
  - `tests/fixtures/conformance.tsv`
  - `docs/CONFORMANCE.md`

**Classification: Confirmed compatibility gap, documented project contract**

The review claim is correct: `strategy.entry` and `strategy.close` currently
fill immediately at the active bar's close, while pending exits are evaluated on
later bars using high/low. TradingView's default market-order behavior fills no
earlier than the next bar's open.

This is not a missing local guard or accidental regression in the current
implementation. The project already documents the supported strategy subset as
current-bar-close fill, and runtime tests explicitly assert that contract.
Changing this now would alter strategy equity, trade timing, state-variable
visibility, and many existing fixtures.

**Action**

No code change applied. Preserved the current documented subset:

- `eval_strategy_entry` calls `entry_long(..., bar.close, qty)`.
- `eval_strategy_close` calls `close_long(..., bar.close)`.
- `strategy.entry` conformance says "current-bar-close fill".
- `docs/CONFORMANCE.md` says `strategy.entry` and `strategy.close` fill at the
  current bar close.
- `strategy_entry_opens_long_position_at_current_close` locks the behavior.

Aligning with TradingView should be a separate broker-model phase that introduces
pending market orders and explicitly decides `process_orders_on_close`,
`calc_on_order_fills`, and intrabar fill semantics.

**Verification**

- Read `crates/pine-runtime/src/builtins/strategy.rs` and confirmed entry/close
  fill price source is `bar.close`.
- Read `crates/pine-runtime/src/tests/strategy.rs` and confirmed the current
  close-fill behavior is covered by a named regression test.
- Read `tests/fixtures/conformance.tsv` and `docs/CONFORMANCE.md` and confirmed
  the behavior is already disclosed in compatibility metadata/docs.

**Result: Deferred, no fix applied**

---

## CR-027: Strategy Scope Intentionally Excludes Fees, Slippage, Pyramiding, Shorts

**Source context**

- Review source: `CODE_REVIEW_EXECUTION_PLAN.md:975`
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-027-strategy-scope-intentionally-excludes-fees-slippage-pyramiding-shorts`
- Affected files:
  - `crates/pine-builtins/src/namespaces/core.rs`
  - `crates/pine-sema/src/analyzer/strategy.rs`
  - `tests/fixtures/sema/unsupported_strategy_orders.pine`
  - `tests/fixtures/sema/unsupported_strategy_entry_short.pine`
  - `tests/fixtures/sema/unsupported_strategy_default_quantity.pine`
  - `tests/fixtures/conformance.tsv`

**Classification: Confirmed intentional partial scope**

The review claim is correct, but it describes an intentionally narrow strategy
subset rather than a direct bug. The project currently supports long-only market
entries, fixed default quantity, one net long position, current-close fills, and
the documented `strategy.exit` subset. Commission, slippage, pyramiding, short
exposure, rich order types, and non-fixed sizing modes are outside the current
contract.

**Action**

No code change applied. The current restrictions are already enforced and
documented:

- `strategy(...)` only exposes `title`, `shorttitle`, `overlay`,
  `max_bars_back`, `initial_capital`, `default_qty_type`, and
  `default_qty_value`.
- `default_qty_type` is validated to `strategy.fixed`.
- `strategy.entry` direction is validated to `strategy.long`.
- Unsupported order functions and sizing modes remain covered by negative sema
  fixtures.
- Conformance explicitly documents no commission, slippage, margin, percent
  sizing, currency conversion, pyramiding, or short exposure.

Any expansion here should be a separate compatibility phase, because it would
change broker state, output schema expectations, equity calculations, and
strategy fixture baselines.

**Verification**

- Read `crates/pine-builtins/src/namespaces/core.rs` and confirmed the limited
  `strategy(...)` parameter list.
- Read `crates/pine-sema/src/analyzer/strategy.rs` and confirmed fixed-only
  default sizing plus long-only entry validation.
- Read unsupported sema fixtures for `strategy.order`, short entry, and
  percent-of-equity default sizing.
- Read `tests/fixtures/conformance.tsv` and confirmed the unsupported strategy
  scope is explicitly listed.

**Result: Deferred, no fix applied**

---

## CR-028: `request.security` Provider Timeframe Requires Same-Or-Higher Integer Multiple

**Source context**

- Review source: `CODE_REVIEW_EXECUTION_PLAN.md:976`
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-028-requestsecurity-provider-timeframe-requires-same-or-higher-integer-multiple`
- Affected files:
  - `crates/pine-runtime/src/builtins/requests.rs`
  - `crates/pine-runtime/src/tests/request.rs`
  - `tests/fixtures/conformance.tsv`
  - `docs/BUILTIN_SIGNATURES.md`
  - `docs/CONFORMANCE.md`

**Classification: Confirmed compatibility gap, documented project contract**

The review claim is correct: provider-backed `request.security` rejects lower
requested timeframes and rejects requested timeframes that are not an integer
multiple of the chart timeframe. TradingView supports broader request behavior,
including lower-timeframe retrieval in `request.security` with caveats and the
separate `request.security_lower_tf` API.

For this project, the current provider-backed subset is intentionally narrower:
same-context identity plus host-provided same-or-higher-timeframe scalar
expressions with default higher-timeframe alignment. Lower-timeframe arrays,
arbitrary timeframe alignment, and `request.security_lower_tf` output shape are
not designed in the public contract.

**Action**

No code change applied. Preserved the existing guard because removing only the
integer-multiple or lower-timeframe checks would make the current
`align_requested_value` behavior ambiguous for unmodeled timeframe pairs.

A future compatibility phase should define arbitrary timeframe alignment, lower
timeframe behavior, chart-context configurability across hosts, output shapes for
array-returning lower-timeframe requests, and conformance fixtures before
widening runtime acceptance.

**Verification**

- Read `validate_provider_timeframe` and confirmed both the lower-timeframe and
  integer-multiple guards.
- Read `align_requested_value` and confirmed the implementation is built around
  the current same/higher-timeframe confirmed-bar model.
- Read `request_security_rejects_lower_timeframe_provider_requests` and confirmed
  the lower-timeframe rejection is covered by a regression test.
- Read `tests/fixtures/conformance.tsv`, `docs/BUILTIN_SIGNATURES.md`, and
  `docs/CONFORMANCE.md` and confirmed the public docs describe the narrow
  same-or-higher-timeframe provider subset.

**Result: Deferred, no fix applied**

---

## CR-029: `request.security` Only Supports The Narrow 3-Arg Scalar Subset

**Source context**

- Review source: `CODE_REVIEW_EXECUTION_PLAN.md:977`
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-029-requestsecurity-only-supports-the-narrow-3-arg-scalar-subset`
- Affected files:
  - `crates/pine-builtins/src/namespaces/requests.rs`
  - `crates/pine-sema/src/analyzer/requests.rs`
  - `crates/pine-runtime/src/builtins/requests.rs`
  - `tests/fixtures/sema/unsupported_request.pine`
  - `tests/fixtures/sema/unsupported_request_lower_tf.pine`
  - `tests/fixtures/conformance.tsv`
  - `docs/BUILTIN_SIGNATURES.md`

**Classification: Confirmed compatibility gap, documented project contract**

The review claim is correct: `request.security` is currently limited to the
3-argument scalar subset, and broader request APIs such as
`request.security_lower_tf` are unsupported. This is a documented partial scope,
not an accidental omission in a claimed-supported feature.

**Action**

No code change applied. The current layers are consistent:

- Builtin signatures register only `request.security(symbol, timeframe,
  expression)`.
- Sema marks non-3-arg, named-arg, non-scalar, non-provider-safe, and
  side-effecting requested expressions unsupported.
- Runtime rejects calls whose lowered argument count is not exactly 3.
- Conformance and builtin docs state that optional params, explicit
  gaps/lookahead, lower-timeframe arrays, and broader request families remain
  unsupported.

Optional `gaps`/`lookahead` arguments and lower-timeframe APIs should only be
accepted after runtime alignment semantics, output shapes, fixtures, and host
request surfaces are designed together.

**Verification**

- Read `crates/pine-builtins/src/namespaces/requests.rs` and confirmed the
  single 3-parameter `request.security` signature.
- Read `crates/pine-sema/src/analyzer/requests.rs` and confirmed the positional,
  scalar, side-effect-free subset checks plus unsupported handling for other
  request names.
- Read `crates/pine-runtime/src/builtins/requests.rs` and confirmed runtime
  arity enforcement for exactly 3 lowered args.
- Read unsupported request fixtures and conformance/docs rows for the current
  narrow request subset.

**Result: Deferred, no fix applied**

---

## CR-030: Request Cache Key Uses Debug String Expression Identity

**Source context**

- Review source: `CODE_REVIEW_EXECUTION_PLAN.md:978`
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-030-request-cache-key-uses-debug-string-expression-identity`
- Affected files:
  - `crates/pine-runtime/src/builtins/requests.rs`
  - `crates/pine-runtime/src/request/provider.rs`
  - `crates/pine-runtime/src/tests/request.rs`
  - `crates/pine-sema/src/analyzer/context.rs`

**Classification: Direct implementation quality bug**

The cache key included `format!("{:?}", expression.kind)`, which allocated a
Debug string and made request-cache identity depend on formatting details. The
lowerer already assigns a stable `CallSiteId` per static call site, so the Debug
string was redundant for the current static request-call model.

**Action**

Removed the expression Debug string from `RequestCacheKey`. The key now contains
only the static `call_site_id`, symbol, and timeframe. Added a regression test
with two `request.security` call sites using the same symbol/timeframe but
different expressions (`open` and `close`) to prove `CallSiteId` keeps the caches
isolated without expression Debug text.

If dynamic request expressions are introduced later and static call-site identity
is no longer enough, the cache should use a structured expression identity from
lowering rather than Debug output.

**Verification**

- `cargo fmt -p pine-runtime` passes.
- `cargo test -p pine-runtime request_security_cache_isolates_same_context_different_callsite_expressions` passes.
- `cargo test -p pine-runtime request_security_caches_requested_context_values_by_callsite` passes.
- `cargo test -p pine-runtime request` passes: 24 request-related tests.

**Result: Fixed**

---

## CR-031: Non-Finite Floats Are Serialized As Invalid JSON Tokens

**Source context**

- Review source: `CODE_REVIEW_EXECUTION_PLAN.md:979`
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-031-non-finite-floats-are-serialized-as-invalid-json-tokens`
- Affected files:
  - `crates/pine-runtime/src/output/json.rs`
  - `crates/pine-cli/src/commands/run.rs`
  - WASM/Python public JSON callers that consume shared runtime JSON

**Classification: Direct public-output bug**

The review claim was correct. `PineValue::Float` and strategy float fields were
serialized with raw `f64::to_string()` / `{}` formatting, which can emit bare
`NaN`, `inf`, or `-inf`. Those are not valid JSON number tokens, so strict host
parsers can reject the entire runtime result.

**Action**

Added a single `f64_json` helper in the shared runtime JSON writer. Finite floats
serialize normally; non-finite floats serialize as JSON `null`. Reused it for:

- `PineValue::Float` through `value_json`.
- `Option<f64>` strategy fields through `option_f64_json`.
- Strategy order, trade, position, and equity float fields.

Profile fields are integer counters/options and do not use floating formatting.
String formatting paths remain separate, so Pine string output can still contain
text such as `NaN` where that is the actual string value.

**Verification**

- `cargo fmt -p pine-runtime` passes.
- `cargo test -p pine-runtime runtime_json_serializes_non_finite_plot_floats_as_null` passes.
- `cargo test -p pine-runtime runtime_json_serializes_non_finite_strategy_floats_as_null` passes.
- CLI end-to-end check with `close=NaN` outputs `"values":[null]` and parses with
  `python3 -m json.tool`.

**Result: Fixed**

---

## CR-032: Runtime JSON Diagnostics Are Hard-Coded And Writer Is Handwritten

**Source context**

- Review source: `CODE_REVIEW_EXECUTION_PLAN.md:980`
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-032-runtime-json-diagnostics-are-hard-coded-and-writer-is-handwritten`
- Affected files:
  - `crates/pine-runtime/src/output/json.rs`
  - `crates/pine-runtime/src/output/model.rs`
  - `crates/pine-cli/src/commands/run.rs`
  - `crates/pine-wasm/src/lib.rs`

**Classification: Direct serialization bug plus deferred architecture risk**

The top-level runtime JSON serializer ignored `RuntimeResult.diagnostics` and
always emitted `"diagnostics":[]`. That is a direct model/serialization bug.
The broader handwritten JSON writer concern is real, but replacing the public
runtime writer with `serde_json` is a larger architecture and snapshot-ordering
change, not a focused bug fix.

**Action**

Changed `public_runtime_result_json` to serialize
`runtime_diagnostics_json(&result.diagnostics)` for the top-level diagnostics
field. Reused the existing diagnostic serializer already used for strategy
diagnostics, preserving the current JSON field shape and escaping behavior.

Deferred a full handwritten-writer migration. If the project moves to structured
JSON writing later, it should be done as a dedicated compatibility-safe output
phase with field-order and snapshot review across CLI/WASM hosts.

**Verification**

- `cargo fmt -p pine-runtime` passes.
- `cargo test -p pine-runtime runtime_json_serializes_top_level_diagnostics` passes.
- `cargo test -p pine-runtime output::json` passes: 3 JSON output tests.

**Result: Fixed for dropped top-level diagnostics; handwritten writer migration deferred**

---

## CR-033: CLI `analyze` Exits 0 Even With Error Diagnostics

**Source context**

- Review source: `CODE_REVIEW_EXECUTION_PLAN.md:981`
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-033-cli-analyze-exits-0-even-with-error-diagnostics`
- Affected files:
  - `crates/pine-cli/src/commands/analyze.rs`
  - `crates/pine-cli/src/main.rs`

**Classification: Direct CLI behavior bug**

The `analyze` command printed diagnostics but always returned `Ok(())`, so the
process exited successfully even when semantic analysis produced error
severity diagnostics. That made CLI automation unable to distinguish a clean
analysis from a failed one by exit status.

**Action**

`analyze` now checks whether any diagnostic has `Severity::Error` before
consuming the diagnostics for printing. If so, it returns
`Err("analysis failed")`, which the existing top-level CLI `main` maps to a
nonzero exit code. The existing diagnostic text output format is preserved.

Added a command unit test using `plot(unknown)` to assert that error diagnostics
make `analyze` return `Err`.

**Verification**

- `cargo fmt -p pine-cli` passes.
- `cargo test -p pine-cli analyze_returns_error_when_error_diagnostics_exist` passes.
- End-to-end `cargo run -q -p pine-cli -- analyze <invalid script>` exits with
  status `1`.
- `cargo test -p pine-cli` passes: 34 tests.

**Result: Fixed**

---

## CR-034: CLI CSV Accepts Non-Finite OHLCV Values

**Source context**

- Review source: `CODE_REVIEW_EXECUTION_PLAN.md:982`
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-034-cli-csv-accepts-non-finite-ohlcv-values`
- Affected files:
  - `crates/pine-cli/src/bars_csv.rs`
  - `crates/pine-cli/src/commands/run.rs`

**Classification: Direct input validation bug**

The CLI bars CSV parser accepted `NaN`, `inf`, and related non-finite values for
OHLCV columns because it parsed floats without an `is_finite()` check. CR-031
now keeps public JSON strict, but accepting malformed market data at the CLI
input boundary was still incorrect.

**Action**

Replaced the generic parse helper with explicit `parse_time_column` and
`parse_f64_column` helpers. OHLCV columns now parse as `f64` and then reject
`!value.is_finite()` with a line/field-specific error. Time remains an integer
parse; timestamp monotonicity and duplicate checks remain the separate CR-035
scope.

Added a table-style unit test covering `NaN`, `inf`, `-inf`, and `infinity` in
each OHLCV column.

**Verification**

- `cargo fmt -p pine-cli` passes.
- `cargo test -p pine-cli rejects_non_finite_ohlcv_values` passes.
- End-to-end `pine-cli run` with `close=NaN` exits nonzero and reports
  `invalid `close` value `NaN` at bars CSV line 2: value must be finite`.
- `cargo test -p pine-cli` passes: 35 tests.

**Result: Fixed**

---

## CR-035: CLI Bars Input Lacks Monotonic/Size Limits And Duplicates JSON Escaping

**Source context**

- Review source: `CODE_REVIEW_EXECUTION_PLAN.md:983`
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-035-cli-bars-input-lacks-monotonicsize-limits-and-duplicates-json-escaping`
- Affected files:
  - `crates/pine-cli/src/bars_csv.rs`
  - `crates/pine-cli/src/commands/run.rs`
  - `crates/pine-cli/src/json.rs`
  - `crates/pine-runtime/src/request/bars.rs`
  - `crates/pine-wasm/src/analysis_json.rs`

**Classification: Mixed direct validation bug and deferred architecture/boundary risks**

The main `--bars` CSV path lacked sorted/duplicate timestamp validation even
though request bars already validate the same property. That is a direct input
validation gap. The file-size limit question and duplicate JSON escape helpers
are real maintainability/resource-boundary concerns, but they need an explicit
shared-crate/API boundary decision rather than an incidental fix.

**Action**

Added main bars timestamp validation inside `parse_bars_csv`:

- duplicate timestamps now return `duplicate bar time ... in bars CSV`;
- decreasing timestamps now return `bars CSV is not sorted ...`.

This validation applies to the shared CLI CSV parser used by main bars and
request-bars specs before runtime/provider construction.

Deferred file-size limits and JSON escape deduplication. Those should be handled
as a dedicated host input/resource policy and shared-output utility design,
respectively.

**Verification**

- `cargo fmt -p pine-cli` passes.
- `cargo test -p pine-cli rejects_duplicate_bar_times` passes.
- `cargo test -p pine-cli rejects_unsorted_bar_times` passes.
- `cargo test -p pine-cli rejects_non_finite_ohlcv_values` still passes.
- `cargo test -p pine-cli` passes: 37 tests.

**Result: Fixed for main bars duplicate/sorted validation; size limits and JSON escape deduplication deferred**

---

## CR-036: Unsupported-Feature Reasons Contain Internal Phase Labels

**Source context**

- Review source: `CODE_REVIEW_EXECUTION_PLAN.md:984`
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-036-unsupported-feature-reasons-contain-internal-phase-labels`
- Affected files:
  - `crates/pine-sema/src/analyzer/unsupported.rs`
  - `crates/pine-sema/src/analyzer/requests.rs`
  - `crates/pine-sema/src/analyzer/expressions.rs`
  - `crates/pine-sema/src/analyzer/user_types.rs`
  - `crates/pine-sema/tests/fixtures.rs`

**Classification: Direct user-facing diagnostic quality bug**

The unsupported-feature reasons are emitted in diagnostics and compatibility
metadata, so internal rollout labels such as `Phase J Slice 0`, `Phase L`, and
`Phase 1` leak into user-facing output. The behavior being rejected is correct;
the bug is the wording and inconsistent scope language.

**Action**

Rewrote unsupported reasons to describe the current supported subset in user
terms:

- request family diagnostics now refer to the supported `request.security`
  subset;
- strategy diagnostics now refer to supported `strategy.entry`,
  `strategy.close`, and `strategy.exit` subsets plus unsupported broker/rich
  backtesting behavior;
- library/export/import and UDT/method diagnostics now describe the supported
  host-provided import and local UDT/method subsets;
- UDT history/nested-field diagnostics no longer mention internal slice names;
- strategy state mutation wording now says state variables are read-only in the
  current strategy subset.

Updated the request-lower-timeframe fixture assertion to match the new public
wording.

**Verification**

- `cargo fmt -p pine-sema` passes.
- `cargo test -p pine-sema --test fixtures reports_unsupported_request_lower_tf_fixture` passes.
- `cargo test -p pine-sema --test fixtures` passes: 58 fixture tests.
- `cargo test -p pine-sema` passes: 251 unit tests, 58 fixture tests, and doctests.
- `cargo test -p pine-wasm` passes: 39 tests and doctests.
- `cargo test -p pine-cli matrix_output_matches_golden_snapshot` passes.
- `rg` confirms no `Phase J`, `Phase L`, `Phase 1`, `current runtime scope`, or
  `strategy usability subset` wording remains under `crates/pine-sema/src` or
  `crates/pine-sema/tests`.

**Result: Fixed**

---

## CR-037: Lowering UDF Inline Recursion/Size Has No Limit

**Source context**

- Source record: `CODE_REVIEW_EXECUTION_PLAN.md:985`.
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-037-lowering-udf-inline-recursionsize-has-no-limit`.
- Confirmed lowering inlines UDFs and methods by call site through `lower_udf_call` / `lower_user_method_call` -> `lower_function_body` -> `lower_expr_with_params` without a lowering-specific budget.
- Earlier sema recursion checks prevent recursive cycles and deep analyzed call chains, but they do not bound lowering-time HIR size or generated temporary symbols for broad acyclic call graphs.

**Decision**

Treat as a direct compiler robustness bug. Added a lowering resource budget shared by the sema path so CLI, Python, and WASM receive the same diagnostic behavior.

**Changes**

- Added internal `LoweringLimits` defaults for max inline depth, max lowered HIR nodes, and max generated lowering temp symbols.
- Added lowering state counters to `Analyzer` and initialized them in `analyze_input`.
- Counted HIR nodes in `lower_stmt_with_params` and `lower_expr_with_params`.
- Counted temp symbols generated during UDF and user-method inlining.
- Counted nested UDF/user-method body inlining depth.
- Emit `E_LOWERING_BUDGET` once when a limit is exceeded and stop producing executable HIR.

**Verification**

- `cargo fmt -p pine-sema`
- `cargo test -p pine-sema rejects_lowering_temp_symbol_budget_exhaustion`
- `cargo test -p pine-sema`

**Result: Fixed**

---

## CR-038: Root Source Is Parsed Twice During Analysis

**Source context**

- Source record: `CODE_REVIEW_EXECUTION_PLAN.md:986`.
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-038-root-source-is-parsed-twice-during-analysis`.
- Confirmed `validate_modules` parsed the root source, then `analyze_input` parsed the same root source again for diagnostics and language version.

**Decision**

Treat as a direct performance/cleanup bug with behavior preservation.

**Changes**

- Root parse diagnostics are now collected inside `validate_modules` alongside library parse diagnostics.
- `analyze_input` no longer calls `parse_source(input.root())`.
- Language version is now read from `module_validation.root_program`, which is the already parsed/rewrite-preserved root program.

**Verification**

- `cargo fmt -p pine-sema`
- `cargo test -p pine-sema`

**Result: Fixed**

---

## CR-039: Module Constant Rewrite Is Name-Based And Scope-Fragile

**Source context**

- Source record: `CODE_REVIEW_EXECUTION_PLAN.md:987`.
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-039-module-constant-rewrite-is-name-based-and-scope-fragile`.
- Confirmed `modules_rewrite.rs` replaced matching imported constants by `expr_name` only and did not account for lexical bindings that shadow the same name.
- Repro shape: an imported library exports constant `offset`, and an exported function declares a local `offset`; the function body return expression was rewritten to the exported constant instead of the local declaration.

**Decision**

Treat as a direct module rewrite correctness bug.

**Changes**

- Added scoped shadow tracking to `RewriteContext`.
- Rewrote statement lists with sequential scope updates so declarations and tuple declarations shadow later expressions in the same block.
- Function parameters now shadow imported constants/function targets in function bodies.
- `for` counters shadow imported names inside loop bodies without leaking outside the loop body.
- Qualified names are also blocked when their leading segment is shadowed.

**Verification**

- Added runtime regression `imported_function_locals_shadow_exported_constants`.
- `cargo fmt -p pine-sema -p pine-runtime`
- `cargo test -p pine-runtime imported_function_locals_shadow_exported_constants`
- `cargo test -p pine-runtime imports`
- `cargo test -p pine-sema import_accepts_exported_constant_and_pure_function_subset`
- `cargo test -p pine-sema`

**Result: Fixed**

---

## CR-040: `syminfo.mintick` And `pointvalue` Are Fixed Constants

**Source context**

- Source record: `CODE_REVIEW_EXECUTION_PLAN.md:988`.
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-040-syminfomintick-and-pointvalue-are-fixed-constants`.
- Confirmed `pine-builtins` defines `syminfo.mintick = 0.01` and `syminfo.pointvalue = 1.0` as fixed constants.
- Current conformance and docs explicitly describe `syminfo.*` as a fixed default symbol metadata subset.

**Decision**

No direct fix for this pass. This is a documented compatibility limitation, not an implementation bug relative to the current supported subset.

**Deferred follow-up**

When runtime chart/symbol metadata becomes configurable, route all of the following through one metadata source:

- `syminfo.*` runtime/builtin values;
- `math.round_to_mintick`;
- strategy profit/loss/trailing tick conversion.

**Verification**

- Reviewed `docs/BUILTIN_SIGNATURES.md`, `tests/fixtures/conformance.tsv`, `crates/pine-builtins/src/constants/floats.rs`, `crates/pine-runtime/src/builtins/math.rs`, and `crates/pine-runtime/src/builtins/strategy.rs` references.

**Result: Deferred, no fix applied**

---

## CR-041: Builtin Signature/Runtime Reconciliation Is Not Enforced

**Source context**

- Source record: `CODE_REVIEW_EXECUTION_PLAN.md:989`.
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-041-builtin-signatureruntime-reconciliation-is-not-enforced`.
- Confirmed builtin signatures live in `pine_builtins::PHASE_1_BUILTINS`, while runtime dispatch is split across multiple string-match dispatchers.
- No test previously required registered callable signatures to have runtime dispatch, or runtime dispatch names to remain registered.

**Decision**

Treat as a direct guardrail bug. Add a test-level reconciliation table with explicit declaration/input exemptions.

**Changes**

- Added `crates/pine-runtime/src/tests/builtin_registry.rs`.
- The test builds sets from `pine_builtins::PHASE_1_BUILTINS` and a runtime-dispatch table.
- It exempts `indicator`, `strategy`, `input`, and `input.*` declaration/input entries as recommended.
- It fails both ways: registered callable without runtime dispatch, and runtime dispatch without registered signature.

**Verification**

- `cargo fmt -p pine-runtime`
- `cargo test -p pine-runtime builtin_signatures_have_runtime_dispatch`
- `cargo test -p pine-runtime`

**Result: Fixed**

---

## CR-042: Signature/Runtime Diff Is Clean In The Source Review, Not An Issue

**Source context**

- Source record: `CODE_REVIEW_EXECUTION_PLAN.md:990`.
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-042-signatureruntime-diff-is-clean-in-the-source-review-not-an-issue`.
- The source record is a positive review finding: the manual signature/runtime diff was clean after accounting for declaration and constant differences.

**Decision**

No direct fix. This is background evidence, not a bug.

**Follow-up relationship**

The actionable guardrail from this area is CR-041, which now adds automated signature/runtime reconciliation.

**Verification**

- Reviewed the CR-042 verification entry and the CR-041 automated reconciliation fix.

**Result: No fix required; covered by CR-041 guardrail**

---

## CR-043: Python Non-Finite Float Representation Diverges From JSON Hosts

**Source context**

- Source record: `CODE_REVIEW_EXECUTION_PLAN.md:991`.
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-043-python-non-finite-float-representation-diverges-from-json-hosts`.
- Confirmed Python bindings accepted non-finite OHLCV values and converted `PineValue::Float(NaN/Inf)` to native Python floats, diverging from the JSON host behavior fixed in CR-031.

**Decision**

Treat as a direct cross-host boundary bug.

**Changes**

- Python bar parsing now keeps `time` as integer extraction but validates `open`, `high`, `low`, `close`, and `volume` as finite `f64` values for both dict and sequence bar inputs.
- Python `PineValue::Float` output conversion now emits `None` for non-finite values.
- Python strategy float fields now use shared finite helpers, emitting `None` for non-finite values and for absent optional float values.
- Added Python tests for rejecting `math.nan` bar input and converting runtime non-finite plot values to `None`.

**Verification**

- `cargo fmt -p pine-python`
- `cargo test -p pine-python`
- `maturin develop --manifest-path crates/pine-python/Cargo.toml` failed because no virtualenv/conda environment is active.
- `maturin build --manifest-path crates/pine-python/Cargo.toml`
- `python3 -m pip install --force-reinstall target/wheels/pine_compat_runtime-0.1.0-cp310-abi3-manylinux_2_35_x86_64.whl`
- `python3 -m pytest python/tests/test_bindings.py -q -k 'non_finite'`
- `python3 -m pytest python/tests -q`

**Result: Fixed**

---

## CR-044: Python Compile/Run Errors Stringify Diagnostics

**Source context**

- Source record: `CODE_REVIEW_EXECUTION_PLAN.md:992`.
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-044-python-compilerun-errors-stringify-diagnostics`.
- Confirmed `compile_script` currently raises `PyValueError` with `format_diagnostics(...)`, while `analyze_script` exposes structured diagnostics.

**Decision**

No direct fix in this pass. This is a Python API design improvement rather than a clear implementation bug in the current contract.

**Deferred follow-up**

Consider adding a custom Python exception type that preserves the current string message for compatibility and also exposes structured diagnostics as an attribute. That should be designed together with Python API compatibility expectations and documented for callers.

**Current workaround**

Callers needing structured diagnostics can call `analyze_script` before `compile_script` / `run_script`.

**Result: Deferred, no fix applied**

---

## CR-045: Python Compile/Run Reject Any Diagnostic Severity

**Source context**

- Source record: `CODE_REVIEW_EXECUTION_PLAN.md:993`.
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-045-python-compilerun-reject-any-diagnostic-severity`.
- Confirmed `compile_script` rejected on `!analysis.diagnostics.is_empty()` rather than checking for `Severity::Error`.
- Current non-error diagnostics are not emitted in normal sema paths, so this was future-facing but inconsistent with `Analysis.hir` / `analyze_script(executable)` semantics.

**Decision**

Treat as a low-risk correctness guardrail fix.

**Changes**

- Added `diagnostics_have_errors` helper in `crates/pine-python/src/lib.rs`.
- `compile_script` now rejects only diagnostics with `Severity::Error`.
- Added Rust unit coverage proving warning/info diagnostics do not trip the helper and error diagnostics do.

**Verification**

- `cargo fmt -p pine-python`
- `cargo test -p pine-python diagnostics_have_errors`
- `cargo test -p pine-python`
- `maturin build --manifest-path crates/pine-python/Cargo.toml`
- `python3 -m pip install --force-reinstall target/wheels/pine_compat_runtime-0.1.0-cp310-abi3-manylinux_2_35_x86_64.whl`
- `python3 -m pytest python/tests -q`

**Result: Fixed**

---

## CR-046: Python Binding Lacks Profile API And Has GIL/Object Allocation Costs

**Source context**

- Source record: `CODE_REVIEW_EXECUTION_PLAN.md:994`.
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-046-python-binding-lacks-profile-api-and-has-gilobject-allocation-costs`.
- Confirmed Python exposes compile/analyze/run APIs but no profile output API, holds the GIL during runtime execution, and uses a one-element list helper for scalar conversion.

**Decision**

No direct fix in this pass. This is API parity and performance cleanup, not a correctness bug in the current Python contract.

**Deferred follow-up**

- Decide whether Python should expose profile output to match CLI `--profile`.
- If adding profile support, design the Python result shape and tests with the public runtime schema.
- Consider `Python::allow_threads` around runtime execution only after confirming all borrowed Python objects are converted before releasing the GIL.
- Replace the one-element list conversion helper with direct object construction helpers as a performance cleanup.

**Result: Deferred, no fix applied**

---

## CR-047: Python Host Inherits Deep-Recursion Process Abort Risk

**Source context**

- Source record: `CODE_REVIEW_EXECUTION_PLAN.md:995`.
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-047-python-host-inherits-deep-recursion-process-abort-risk`.
- Confirmed Python shares the same parser/analyzer/runtime pipeline, so stack-overflow abort risks from core recursion would also affect Python hosts.

**Decision**

Treat as fixed by the core budget work from earlier CRs, with Python smoke coverage added here.

**Related fixes**

- CR-005 added parser expression nesting limits.
- CR-012 added sema expression/UDF call-depth limits.
- CR-018 added runtime expression evaluation depth limits.
- CR-037 added lowering resource budgets.

**Changes**

- Added Python smoke test `test_compile_script_rejects_deep_input_without_aborting_process`, which compiles a deeply nested expression and asserts a catchable `ValueError` containing `E_PARSE_EXPR_DEPTH`.

**Verification**

- `python3 -m pytest python/tests/test_bindings.py -q -k 'deep_input or non_finite'`
- `python3 -m pytest python/tests -q`

**Result: Fixed by core recursion/resource budgets, with Python smoke coverage added**

---

## CR-048: WASM JSON String Output Becomes Unparsable With Non-Finite Values

**Source context**

- Source record: `CODE_REVIEW_EXECUTION_PLAN.md:996`.
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-048-wasm-json-string-output-becomes-unparsable-with-non-finite-values`.
- Confirmed WASM run APIs return runtime output as JSON strings and use the shared `public_runtime_result_json` writer.

**Decision**

Treat as fixed by the shared runtime JSON fix from CR-031, with WASM-specific regression coverage added here.

**Changes**

- Added WASM regression `run_script_csv_serializes_non_finite_values_as_json_null`.
- The test runs a finite CSV input with a runtime expression producing a non-finite float, parses the returned JSON string with `serde_json`, and asserts the output value is `null` with no `NaN` or `Infinity` tokens.

**Verification**

- `cargo fmt -p pine-wasm`
- `cargo test -p pine-wasm run_script_csv_serializes_non_finite_values_as_json_null`
- `cargo check -p pine-wasm --target wasm32-unknown-unknown`
- `cargo test -p pine-wasm`

**Result: Fixed by CR-031 shared JSON writer, with WASM regression coverage added**

---

## CR-049: WASM CSV Accepts Non-Finite OHLCV Values

**Source context**

- Source record: `CODE_REVIEW_EXECUTION_PLAN.md:997`.
- Verification entry: `CODE_REVIEW_ISSUE_VERIFICATION.md#cr-049-wasm-csv-accepts-non-finite-ohlcv-values`.
- Confirmed WASM CSV parsing used generic `FromStr` parsing for every column, so `f64` OHLCV columns accepted `NaN`, `inf`, `-inf`, and `infinity`.

**Decision**

Treat as a direct host input validation bug.

**Changes**

- Split WASM CSV parsing into `parse_time_column` and `parse_f64_column`.
- `time` remains integer parsed.
- `open`, `high`, `low`, `close`, and `volume` now reject non-finite values before constructing `Bar`.
- Added WASM regression covering non-finite values in every OHLCV column.

**Verification**

- `cargo fmt -p pine-wasm`
- `cargo test -p pine-wasm run_script_csv_rejects_non_finite_ohlcv_values`
- `cargo test -p pine-wasm`
- `cargo check -p pine-wasm --target wasm32-unknown-unknown`

**Result: Fixed**

---

## CR-050: WASM JSON Duplicate Keys Collapse Before Provider Validation

**Source context**

Verification confirms the WASM request-bars and library-source JSON paths parse
objects through map-backed JSON values before host validation. In
`crates/pine-wasm/src/request_bars.rs`, duplicate object keys are collapsed by
`serde_json::Value` before `InMemoryRequestDataProvider` can detect duplicate
request streams. The existing `request_bars_documents_duplicate_json_key_collapse`
test explicitly documents that last-key behavior.

**Result: no code change; documented as host input-contract/design follow-up**

This is not a clear correctness bug in the currently documented WASM JSON input
contract. Rejecting duplicate keys would require a custom JSON object visitor and
would intentionally change WASM host API behavior; it should be handled as a
cross-host parity/API decision together with library-source JSON duplicate-key
handling. The current behavior remains covered by an explicit regression test.

---

## CR-051: CSV/JSON Escaping And Analysis Serialization Are Duplicated

**Source context**

Verification confirms duplicated host-boundary code: CLI and WASM keep separate
CSV parsers, JSON escaping exists in multiple host/output paths, and WASM/Python
analysis serialization is maintained by separate writers. The concrete boundary
bugs exposed by that duplication were handled in prior CRs: non-finite runtime
JSON normalization, CLI/WASM CSV finite-value rejection, and WASM strict JSON
regression coverage.

**Result: no direct code change; documented as structural follow-up**

This item is a maintainability/parity risk rather than a standalone correctness
bug. Extracting a shared host-support crate or unified analysis serializer would
change crate boundaries and should be done as a scoped refactor with parity
fixtures. The current pass leaves behavior unchanged here and relies on the
specific boundary regression tests added under the earlier concrete CRs.

---

## CR-052: WASM Host Lacks Profile API, Panic Hook, And Configurable Chart Context

**Source context**

Verification confirms the WASM public API exposes compile/analyze/run entrypoints
but no profiled run entrypoint, no `console_error_panic_hook` dependency/setup,
and no public way to override the default chart context. `request_bars.rs` and
the normal run path still use default request/chart context plumbing.

**Result: no direct code change; documented as host-contract/design follow-up**

This is a capability and diagnostics gap, not a clear current correctness bug.
A WASM profile API should be added only as part of an explicit public host API
parity decision. Chart context configuration should be designed as a shared
CLI/Python/WASM contract rather than a WASM-only option. The panic-hook item is
less urgent after the parser/sema/runtime/lowering depth budgets added for the
recursion crash surface, and should be weighed against WASM binary-size and
initialization behavior.

---

## CR-053: Conformance Validates Structure/Existence, Not Semantic Accuracy

**Source context**

Verification confirms `crates/pine-cli/src/conformance.rs` validates TSV shape,
unique features, allowed status values, non-empty notes/fixture paths, broad
fixture-path categories, request fixture naming, and path existence in tests.
It does not prove that a referenced fixture semantically exercises the row's
feature or that `supported`/`partial`/`unsupported` matches actual behavior.

**Result: no direct code change; documented as test-infrastructure follow-up**

This is a coverage-quality limitation, not a localized implementation bug.
A real fix requires adding explicit feature tags or another semantic linkage to
fixtures and then migrating the current matrix gradually. Adding a superficial
validator without fixture metadata would not improve correctness, so this pass
keeps the current structural guard and records the semantic-link work as a
separate testing project.

---

## CR-054: Runtime Fixture Parity Does Not Assert Numeric Golden Values

**Source context**

Verification confirms `crates/pine-runtime/tests/incremental.rs` compiles each
runtime fixture, runs full historical execution, runs incremental append
execution, and asserts those two local execution modes match. That catches
incremental/full divergence but does not prove indicator or strategy values
match an external numeric oracle. The repo also has focused runtime snapshots
and unit tests, but not broad golden oracle coverage for high-risk TA/math
fixtures.

**Result: no direct code change; documented as oracle-coverage follow-up**

This is a test-strength gap rather than a localized implementation bug. A useful
fix needs curated golden values for selected indicators and strategy price cases,
with explicit source/oracle expectations. Adding arbitrary self-generated
snapshots would mostly freeze current behavior, so this pass leaves the parity
harness intact and records separate golden numeric coverage as future work.

---

## CR-055: No Regression Fixture For Computed Integer Operands

**Source context**

Verification originally found no fixture or value-asserting coverage for the
computed integer cases tied to CR-015/CR-019/CR-024: arithmetic loop bounds,
computed array indexes/mutations, and computed TA/math lengths. The current
checkout now includes `tests/fixtures/runtime/computed_array_operands.pine` and
`tests/fixtures/runtime/computed_lengths.pine`, and `tests/fixtures/conformance.tsv`
references them for the relevant array, `ta.sma`, and `math.sum` rows.

**Result: fixed/covered by targeted regression tests and fixtures**

Runtime value assertions now cover `for i = 0 to n - 1`, `array.get(values,
k - 1)`, `array.set(values, n - 1, close)`, `array.new_float(n + 1)`,
`ta.sma(close, n * 1)`, and `math.sum(close, n + 0)`. This satisfies the
recommendation that the coverage not rely only on incremental parity.

**Verification**

- `cargo test -p pine-runtime computed_integer`
- `cargo test -p pine-runtime runtime_fixtures_match_incremental_append_execution`

---

## CR-056: Syntax Fixture Coverage Is Minimal

**Source context**

Verification confirmed `crates/pine-syntax/tests/fixtures.rs` only exercised
`tests/fixtures/syntax/phase1_basic.pine`, leaving parser/lexer boundary cases
covered mostly by inline unit tests rather than shared fixtures.

**Result: fixed**

Added syntax fixtures for:

- deep expression nesting rejection;
- UTF-8 character-column diagnostics;
- `export` as a soft-keyword identifier;
- malformed integer recovery;
- parser recovery after a missing expression.

Updated `crates/pine-syntax/tests/fixtures.rs` to parse those fixtures and assert
expected diagnostics or recovery behavior.

**Verification**

- `cargo test -p pine-syntax --test fixtures`
- `cargo test -p pine-syntax`

---

## CR-057: Eight Legacy Strategy-Exit Fixtures Are Unreferenced

**Source context**

Verification identified eight `tests/fixtures/sema/unsupported_strategy_exit_*.pine`
files that were not referenced by live crate tests, conformance rows, snapshots,
or Python tests. Inspection confirmed they encode old unsupported states for
strategy.exit shapes that now have supported fixtures or newer explicit boundary
fixtures.

**Result: fixed**

Deleted the obsolete unreferenced fixtures:

- `unsupported_strategy_exit_stop.pine`
- `unsupported_strategy_exit_stop_limit.pine`
- `unsupported_strategy_exit_stop_profit.pine`
- `unsupported_strategy_exit_limit_loss.pine`
- `unsupported_strategy_exit_profit_loss.pine`
- `unsupported_strategy_exit_profit_qty.pine`
- `unsupported_strategy_exit_qty_stop.pine`
- `unsupported_strategy_exit_trailing_partial_quantity.pine`

Historical phase docs still mention some of these old migration artifacts, but
live tests and conformance no longer depend on them.

**Verification**

- `cargo test -p pine-cli conformance`
- `cargo test -p pine-sema --test fixtures strategy_exit`

---

## CR-058: Missing Non-Finite Tests; f64 Cross-Platform Matrix Deferred

**Source context**

Verification split this item into two parts: missing non-finite input/output
regressions, and the broader question of cross-platform f64 byte stability. The
non-finite coverage gap overlapped the concrete host-boundary bugs fixed under
CR-031, CR-034, CR-043, CR-048, and CR-049.

**Result: partially fixed; f64 CI matrix deferred**

The non-finite regression coverage is now present across the relevant boundary
surfaces:

- runtime JSON serializes non-finite plot and strategy floats as `null`;
- CLI CSV rejects non-finite OHLCV values;
- WASM CSV rejects non-finite OHLCV values and public JSON remains strict;
- Python rejects non-finite bar inputs and converts non-finite plot values to
  `None`.

The cross-platform f64 display matrix remains a release/CI policy decision. It
should be added only if byte-identical serialized float output across target
architectures is an explicit release requirement.

**Verification**

- `cargo test -p pine-runtime runtime_json_serializes_non_finite`
- `cargo test -p pine-cli rejects_non_finite_ohlcv_values`
- `cargo test -p pine-wasm non_finite`
- `python3 -m pytest python/tests/test_bindings.py -q -k 'non_finite'`

---

## CR-059: 22 Emitted Diagnostic Codes Are Undocumented

**Source context**

Verification found emitted diagnostic codes that were absent from
`docs/DIAGNOSTIC_CODES.md`, including lexer/parser block codes, loop/type codes,
unknown function/method/color codes, strategy runtime diagnostics, and script
mode/declaration diagnostics. During implementation the live source scan also
included newer budget/depth/runtime codes added by this fix pass.

**Result: fixed**

Updated `docs/DIAGNOSTIC_CODES.md` to document all currently emitted public
codes, including:

- `E_LEX_INDENT`;
- `E_PARSE_BLOCK`, `E_PARSE_EXPR_DEPTH`, `E_PARSE_FOR`, `E_PARSE_FUNCTION`;
- `E_FUNCTION_CALL_DEPTH`, `E_SEMA_EXPR_DEPTH`, `E_LOWERING_BUDGET`;
- loop diagnostics, unknown function/method/color diagnostics, method receiver
  diagnostics, script declaration diagnostics;
- runtime and strategy broker diagnostics.

Added `diagnostic_reference_documents_emitted_codes`, which scans Rust source
for emitted `E_*` codes and fails if `docs/DIAGNOSTIC_CODES.md` is missing one.
The test ignores the test-only `E_TEST` fixture code.

**Verification**

- `cargo test -p pine-cli diagnostic_reference_documents_emitted_codes`
- `cargo test -p pine-cli`

---

## CR-060: Core Determinism Grep Passes; f64 Platform Risk Remains

**Source context**

Verification confirmed the positive determinism finding: source grep across core
crates found no direct use of reviewed time, random, filesystem, network, or
environment APIs in deterministic execution paths. A fresh grep in this pass
also returned no matches for the reviewed patterns.

**Result: no code change; f64 platform matrix deferred**

No current deterministic execution bug was identified. The remaining concern is
cross-platform byte-identical floating-point formatting/snapshot output. Current
CI runs the release gate on Ubuntu only, so a broader f64 stability guarantee
would require an explicit CI matrix or platform snapshot policy. This remains a
release-policy follow-up, consistent with CR-058.

---

## CR-061: Cross-Host Unbounded Recursion Is The Main Safety Crash Surface

**Source context**

Verification summarized the main systematic crash surface as unbounded recursion
or expansion across parser, sema, lowering, and runtime evaluation. The concrete
subproblems were handled under CR-005, CR-012, CR-018, CR-037, and CR-047.

**Result: fixed by coordinated resource budgets**

The repo now has recoverable limits across the relevant layers:

- parser expression nesting emits `E_PARSE_EXPR_DEPTH`;
- semantic expression nesting emits `E_SEMA_EXPR_DEPTH`;
- UDF/method call-chain depth emits `E_FUNCTION_CALL_DEPTH`;
- lowering inline depth, HIR node count, and generated temporary symbols emit
  `E_LOWERING_BUDGET`;
- runtime expression evaluation returns a recoverable runtime error when the
  evaluation budget is exceeded;
- Python has a smoke test proving deep input becomes a catchable exception
  rather than a process abort.

**Verification**

- `cargo test -p pine-syntax rejects_expression_nesting_past_depth_limit`
- `cargo test -p pine-sema rejects_deep_semantic_expression_nesting`
- `cargo test -p pine-sema rejects_deep_acyclic_function_call_chain`
- `cargo test -p pine-sema rejects_lowering_temp_symbol_budget_exhaustion`
- `cargo test -p pine-runtime rejects_hir_expression_past_runtime_eval_depth`
- `python3 -m pytest python/tests/test_bindings.py -q -k 'deep_input'`

---

## CR-062: Clean-Room Policy Is Present; Package Metadata Remains Light

**Source context**

Verification confirmed `docs/COMPATIBILITY_AND_LEGAL.md` and `README.md` already
contain clean-room and non-affiliation language. CR-002 had already fixed the
empty workspace repository metadata, but member package metadata still did not
inherit repository information or include non-affiliation positioning in package
description fields.

**Result: fixed metadata gap**

Added workspace package description:

`Clean-room Pine-compatible indicator runtime subset; not affiliated with TradingView.`

Updated all member crates to inherit workspace `description` and `repository`
metadata. This keeps package metadata aligned with the existing clean-room and
non-affiliation policy without changing code behavior.

**Verification**

- `cargo metadata --no-deps --format-version 1`
- `cargo check --workspace`

---

## CR-063: Priority Summary Matches Verified Top Risks So Far

**Source context**

Verification confirmed that the original priority summary matched the main risk
clusters: integer arithmetic collapse, unbounded recursion/resource limits,
non-finite host boundaries, and `ta.*` history/runtime coupling.

**Result: no standalone code change; summary reconciled with individual CRs**

This item is a prioritization summary, not an independent defect. The actual
outcomes are tracked under the individual CR entries:

- integer arithmetic collapse and computed integer downstream cases were fixed
  under CR-015/019/024/055;
- recursion/resource limits were fixed under CR-005/012/018/037/047/061;
- non-finite input/output boundaries were fixed and regression-tested under
  CR-031/034/043/048/049/058;
- `ta.*` history coupling remains a structural follow-up under CR-010/016/021:
  shared metadata, reviewed-list runtime reconciliation, and
  SAR/DMI/Supertrend/KC/KCW/MFI/TSI/Cross retention-bound numeric coverage now
  exists, with fixed-offset runtime implicit reads guarded by
  `read_declared_series_history`.
