# Code Review Issue Verification

This document is a 1:1 follow-up to
[docs/CODE_REVIEW_EXECUTION_PLAN.md](CODE_REVIEW_EXECUTION_PLAN.md). It verifies
each recorded issue against the current worktree before recommending changes.

No functional code is changed as part of this pass. Each item should end with a
clear status:

- `Confirmed`: the issue exists in the current code or current behavior.
- `Partially confirmed`: the core concern exists, but the scope or severity needs
  adjustment.
- `Not confirmed`: current evidence contradicts the original issue.
- `Deferred evidence`: the item needs a stronger fixture, external reference, or
  broader audit before a final recommendation is responsible.

## Method

- Treat the current worktree as authoritative.
- Preserve the source issue mapping back to the rolling records in
  `CODE_REVIEW_EXECUTION_PLAN.md`.
- Prefer direct evidence: file/line references, search results, and runnable
  repro commands.
- Do not widen support claims while writing recommendations. If a change would
  alter compatibility, recommend matching fixture, conformance, docs, and host
  surface updates.

## Source Inventory

The source review document currently has 63 rolling issue records under
`发现记录` (`rg -n "^- \\[阶段" docs/CODE_REVIEW_EXECUTION_PLAN.md | wc -l`).
This verification document keeps one verification entry per source record.
Some source records describe the same root cause from different surfaces; those
remain separate entries but may share the same evidence block.

## Current Progress

| Source line | Verification id | Status | Short name |
| --- | --- | --- | --- |
| 949 | CR-001 | Confirmed | README references missing `tests/conformance/` |
| 950 | CR-002 | Confirmed | Workspace repository metadata is empty |
| 951 | CR-003 | Confirmed | Structure guard only excludes `/src/tests/` paths |
| 952 | CR-004 | Confirmed | No workspace dependency table |
| 953 | CR-005 | Confirmed | Parser expression recursion has no depth limit |
| 954 | CR-006 | Confirmed | Diagnostic columns are byte offsets, not character columns |
| 955 | CR-007 | Partially confirmed | Phase-J soft keyword parsing has uneven lookahead guards |
| 956 | CR-008 | Confirmed | Numeric lexer lacks exponent/underscore forms |
| 957 | CR-009 | Confirmed | HIR/runtime errors do not carry source spans |
| 958 | CR-010 | Confirmed | `ta.*` implicit history table is manually coupled to runtime |
| 959 | CR-011 | Confirmed | Analyzer and lowering type inference are parallel implementations |
| 960 | CR-012 | Confirmed | Sema expression/UDF recursion has no general depth limit |
| 961 | CR-013 | Confirmed | Reassignment updates symbol type directly from RHS |
| 962 | CR-014 | Superseded | 11 missing sema diagnostic codes are covered by CR-059 |
| 963 | CR-015 | Confirmed | Integer binary arithmetic collapses to `Float` |
| 964 | CR-016 | Confirmed | Under-retained series history silently reads as `Na` |
| 965 | CR-017 | Superseded | `RuntimeError` span gap is the runtime half of CR-009 |
| 966 | CR-018 | Partially confirmed | Runtime recursion, symbol scans, and realtime clone costs |
| 967 | CR-019 | Confirmed | Computed `ta.*`/`math.*` lengths become invalid |
| 968 | CR-020 | Confirmed | Timezone support is UTC-only |
| 969 | CR-021 | Deferred evidence | EMA/RMA/RSI warmup may differ from TradingView |
| 970 | CR-022 | Confirmed | Drawing object limits are fixed and error on overflow |
| 971 | CR-023 | Partially confirmed | Array bounds behavior is project-documented but differs from official Pine errors |
| 972 | CR-024 | Confirmed | Computed array indexes/sizes inherit integer collapse |
| 973 | CR-025 | Partially confirmed | Missing strategy default quantity fails, but at sema rather than runtime |
| 974 | CR-026 | Confirmed | Strategy fills at current close and exits on later high/low |
| 975 | CR-027 | Confirmed | Strategy scope intentionally excludes fees/slippage/pyramiding/shorts |
| 976 | CR-028 | Confirmed | `request.security` provider timeframe requires same-or-higher integer multiple |
| 977 | CR-029 | Confirmed | `request.security` only supports the narrow 3-arg scalar subset |
| 978 | CR-030 | Confirmed | Request cache key uses Debug string expression identity |
| 979 | CR-031 | Confirmed | Non-finite floats are serialized as invalid JSON tokens |
| 980 | CR-032 | Confirmed | Runtime JSON diagnostics are hard-coded and writer is handwritten |
| 981 | CR-033 | Confirmed | CLI `analyze` exits 0 even with error diagnostics |
| 982 | CR-034 | Confirmed | CLI CSV accepts non-finite OHLCV values |
| 983 | CR-035 | Confirmed | CLI bars input lacks monotonic/size limits and duplicates JSON escaping |
| 984 | CR-036 | Confirmed | Unsupported-feature reasons contain internal phase labels |
| 985 | CR-037 | Confirmed | Lowering UDF inline recursion/size has no limit |
| 986 | CR-038 | Confirmed | Root source is parsed twice during analysis |
| 987 | CR-039 | Confirmed | Module constant rewrite is name-based and scope-fragile |
| 988 | CR-040 | Confirmed | `syminfo.mintick` and `pointvalue` are fixed constants |
| 989 | CR-041 | Confirmed | Builtin signature/runtime reconciliation is not enforced |
| 990 | CR-042 | Confirmed | Signature/runtime diff is clean in the source review, not an issue |
| 991 | CR-043 | Confirmed | Python non-finite float representation diverges from JSON hosts |
| 992 | CR-044 | Confirmed | Python compile/run errors stringify diagnostics |
| 993 | CR-045 | Confirmed | Python compile/run reject any diagnostic severity |
| 994 | CR-046 | Confirmed | Python binding lacks profile API and has GIL/object allocation costs |
| 995 | CR-047 | Confirmed | Python host inherits deep-recursion process abort risk |
| 996 | CR-048 | Confirmed | WASM JSON string output becomes unparsable with non-finite values |
| 997 | CR-049 | Confirmed | WASM CSV accepts non-finite OHLCV values |
| 998 | CR-050 | Confirmed | WASM JSON duplicate keys collapse before provider validation |
| 999 | CR-051 | Confirmed | CSV/JSON escaping and analysis serialization are duplicated |
| 1000 | CR-052 | Confirmed | WASM host lacks profile API/panic hook/configurable chart context |
| 1001 | CR-053 | Confirmed | Conformance validates structure/existence, not semantic accuracy |
| 1002 | CR-054 | Confirmed | Runtime fixture parity does not assert numeric golden values |
| 1003 | CR-055 | Confirmed | No regression fixture for computed integer operands |
| 1004 | CR-056 | Confirmed | Syntax fixture coverage is minimal |
| 1005 | CR-057 | Confirmed | Eight legacy strategy-exit fixtures are unreferenced |
| 1006 | CR-058 | Partially confirmed | Missing non-finite tests; f64 cross-platform matrix deferred |
| 1007 | CR-059 | Confirmed | 22 emitted diagnostic codes are undocumented |
| 1008 | CR-060 | Confirmed | Core determinism grep passes; f64 platform risk remains |
| 1009 | CR-061 | Confirmed | Cross-host unbounded recursion is the main safety crash surface |
| 1010 | CR-062 | Confirmed | Clean-room policy is present; package metadata remains light |
| 1011 | CR-063 | Confirmed | Priority summary matches verified top risks so far |

All 63 source records now have matching verification sections below. The final
pass should still check wording consistency, duplicated/superseded items, and
evidence strength before treating this as a closeout document.

---

## CR-001: README References Missing `tests/conformance/`

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:949`

**Status: Confirmed**

**Evidence**

- [README.md](../README.md) has a "Current Package Layout" section but the
  current checkout does not contain a `tests/conformance/` directory.
- The actual conformance source is
  [tests/fixtures/conformance.tsv](../tests/fixtures/conformance.tsv).

**Recommendation**

Update README package-layout text to point to `tests/fixtures/conformance.tsv`
and the actual fixture directories. This is documentation-only and should not
change support claims.

---

## CR-002: Workspace Repository Metadata Is Empty

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:950`

**Status: Confirmed**

**Evidence**

- [Cargo.toml](../Cargo.toml) has `[workspace.package] repository = ""`.

**Recommendation**

Fill `repository` before publishing crates or generated package metadata. If the
repository is intentionally private or undecided, document that in release
checklists rather than leaving an empty public metadata field.

---

## CR-003: Structure Guard Only Excludes `/src/tests/` Paths

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:951`

**Status: Confirmed**

**Evidence**

- [scripts/check_structure.py](../scripts/check_structure.py) filters Rust files
  with `if "/src/tests/" not in path.as_posix()`.
- A file like
  [crates/pine-runtime/src/strategy/broker/tests.rs](../crates/pine-runtime/src/strategy/broker/tests.rs)
  is test code by name/module convention but is not under `/src/tests/`, so it is
  counted as implementation.

**Recommendation**

Extend the guard to classify `tests.rs`, `*_tests.rs`, or module-level test files
as test support when they are only included under `#[cfg(test)]`. Do this
carefully: do not exclude production modules merely because their path contains
the word "test".

---

## CR-004: No Workspace Dependency Table

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:952`

**Status: Confirmed**

**Evidence**

- [Cargo.toml](../Cargo.toml) has `[workspace]` and `[workspace.package]`, but no
  `[workspace.dependencies]`.

**Recommendation**

No urgent change while each external dependency is owned by one crate. Add
`[workspace.dependencies]` once dependencies are shared across crates or version
drift appears.

---

## CR-006: Diagnostic Columns Are Byte Offsets, Not Character Columns

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:954`

**Status: Confirmed**

**Evidence**

- [source.rs](../crates/pine-syntax/src/source.rs) builds line starts from byte
  offsets and computes `column` as `offset - line_start + 1`.
- This is correct for byte columns but over-counts user-visible columns after
  multi-byte UTF-8 characters.

**Recommendation**

If diagnostics are meant for users, compute column from `self.text[line_start ..
offset].chars().count() + 1`. Keep byte spans internally; only display columns
need character semantics.

---

## CR-007: Phase-J Soft Keyword Parsing Has Uneven Lookahead Guards

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:955`

**Status: Fixed**

**Evidence**

- The lexer treats `library`, `export`, `type`, and `method` as identifiers.
- [parser_phase_j.rs](../crates/pine-syntax/src/parser_phase_j.rs)
  `phase_j_statement` guards `library` with `(` and `type`/`method` with a next
  identifier, but `export` has no analogous guard.

**Clarification**

The original issue grouped all soft keywords together. Current code has guards
for some of them; `export` is the clearest unguarded case.

**Recommendation**

Add lookahead for `export` so ordinary identifiers like `export = 5` do not enter
export-declaration parsing. Then add syntax fixtures for soft keyword identifier
uses and actual declarations.

---

## CR-008: Numeric Lexer Lacks Exponent/Underscore Forms

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:956`

**Status: Confirmed**

**Evidence**

- [lexer.rs](../crates/pine-syntax/src/lexer.rs) number lexing consumes ASCII
  digits, then an optional `.` followed by digits.
- It does not consume exponent markers (`e`/`E`) or separators (`_`).

**Recommendation**

First decide in `LANGUAGE_SCOPE.md` whether these literal forms are in scope. If
yes, extend lexer parsing and add fixtures for `1e6`, `1.2e-3`, and rejected
malformed forms. If no, document the limitation in language scope/conformance.

---

## CR-009: HIR/Runtime Errors Do Not Carry Source Spans

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:957`

**Status: Confirmed**

**Evidence**

- [pine-ir/src/lib.rs](../crates/pine-ir/src/lib.rs) `HirStmt` and `HirExpr`
  carry `kind`, type, and series metadata, but no `Span`.
- [error.rs](../crates/pine-runtime/src/error.rs) `RuntimeError` only has
  `message: String`.

**Recommendation**

If runtime diagnostics need source locations, add spans to HIR nodes during
lowering and propagate them into `RuntimeError`/runtime diagnostics. This is a
cross-crate contract change; update CLI/Python/WASM error surfaces together.

---

## CR-017: `RuntimeError` Has No Source Span

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:965`

**Status: Superseded**

**Evidence**

- [error.rs](../crates/pine-runtime/src/error.rs) defines `RuntimeError` with
  only `message: String`.
- This is not a separate runtime-only defect from CR-009: runtime errors cannot
  point back to source unless lowering preserves source locations on HIR nodes
  and runtime errors have a field/surface to carry them.

**Recommendation**

Handle this under CR-009 instead of creating a separate fix track. The coherent
change is to add span propagation from syntax/lowering into HIR and then expose
those spans through `RuntimeError` and all host-facing diagnostics together.

---

## CR-011: Analyzer And Lowering Type Inference Are Parallel Implementations

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:959`

**Status: Confirmed**

**Evidence**

- [calls.rs](../crates/pine-sema/src/analyzer/calls.rs) implements
  `Analyzer::return_type`.
- [expressions.rs](../crates/pine-sema/src/analyzer/expressions.rs)
  `type_of_expr_with_params` re-implements many `ReturnSpec` cases for lowering.

**Recommendation**

Extract shared pure return/type inference helpers used by both analyzer and
lowering. Keep diagnostic-producing checks in analyzer, but avoid duplicated
`ReturnSpec` matching.

---

## CR-013: Reassignment Updates Symbol Type Directly From RHS

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:961`

**Status: Confirmed**

**Evidence**

- [statements.rs](../crates/pine-sema/src/analyzer/statements.rs) calls
  `self.update_symbol_type(name, value_type)` after assignment validation.
- That means the stored symbol type can become exactly the RHS type rather than a
  merged or widened type.

**Impact**

Potential semantic drift. This pass confirms the implementation shape but has
not isolated a user-visible fixture where qualifier narrowing causes wrong
runtime behavior.

**Recommendation**

Add targeted sema/runtime tests for reassignment after series values, branch
reassignment, and `var`/`varip` reassignment. If Pine semantics require series
widening, update symbol type merging accordingly.

---

## CR-014: 11 Missing Sema Diagnostic Codes Are Covered By CR-059

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:962`

**Status: Superseded**

**Evidence**

The later full diagnostic audit in CR-059 finds 22 missing codes, including the
11 sema codes listed here.

**Recommendation**

Handle through CR-059 rather than maintaining two separate diagnostic-code tasks.

## CR-015: Integer Binary Arithmetic Collapses To `Float`

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:963`
- Original claim: `crates/pine-runtime/src/runtime/expressions.rs` routes integer
  arithmetic through `numeric_binary`, returns `Float`, and consumers using
  `as_i64()` silently reject integral float values. This breaks cases such as
  `for i = 0 to n - 1`.

**Status: Confirmed**

**Current code evidence**

- [expressions.rs](../crates/pine-runtime/src/runtime/expressions.rs) routes
  `Add`, `Sub`, `Mul`, `Div`, and `Mod` through `numeric_binary`.
- [expressions.rs](../crates/pine-runtime/src/runtime/expressions.rs) implements
  `numeric_binary` by converting both operands with `as_f64()` and returning
  `finite_float_or_na(...)`. That produces `PineValue::Float` even for
  `Int - Int` when the mathematical result is integral.
- [value.rs](../crates/pine-runtime/src/value.rs) implements `as_i64()` for
  `PineValue::Int` only; `PineValue::Float(2.0)` returns `None`.
- [statements.rs](../crates/pine-runtime/src/runtime/statements.rs) requires
  `from`, `to`, and `step` in `eval_for_loop` to pass `as_i64()`. If `to` is
  `Float(2.0)`, the loop returns `Na` before executing.

**Behavior evidence**

Command:

```bash
cargo run -q -p pine-cli -- run <(printf '%s\n' \
  '//@version=5' \
  'indicator("loop")' \
  'n = 3' \
  'sum = 0' \
  'for i = 0 to n - 1' \
  '    sum := sum + 1' \
  'plot(sum)') --bars tests/fixtures/runtime/bars.csv
```

Observed output:

```json
{"schemaVersion":3,"plots":[{"id":1,"values":[0,0,0,0]}],...}
```

Control command with literal upper bound:

```bash
cargo run -q -p pine-cli -- run <(printf '%s\n' \
  '//@version=5' \
  'indicator("loop")' \
  'sum = 0' \
  'for i = 0 to 2' \
  '    sum := sum + 1' \
  'plot(sum)') --bars tests/fixtures/runtime/bars.csv
```

Observed output:

```json
{"schemaVersion":3,"plots":[{"id":1,"values":[3,3,3,3]}],...}
```

This proves the issue is not the loop body or bar input. The failure is triggered
by the computed integer expression `n - 1`.

**Impact**

High. This silently changes program behavior without a diagnostic. It affects
common Pine patterns such as computed loop bounds, computed array indexes,
computed lengths, and any runtime path that relies on `as_i64()` after an
arithmetic expression.

**Recommended fix**

Prefer fixing the producer, not relaxing every consumer:

1. Split numeric binary evaluation by operator and operand kind.
2. Preserve `PineValue::Int` for `Int + Int`, `Int - Int`, and `Int * Int` when
   checked integer arithmetic succeeds.
3. For integer overflow in `+`, `-`, or `*`, choose an explicit policy. The
   conservative compatibility option is to fall back to finite float arithmetic
   rather than panic.
4. Keep `/` as float-producing unless the language scope explicitly requires
   integer division semantics.
5. For `%`, preserve `Int` for `Int % Int` when divisor is non-zero; retain the
   existing non-finite/zero-divisor-to-`Na` behavior for float paths.
6. Add regression coverage for `for i = 0 to n - 1`, `array.get(a, k - 1)`, and
   `ta.sma(close, n * 1)`.

Avoid changing `PineValue::as_i64()` alone as the primary fix. Accepting integral
floats there would mask type drift across the runtime and leave arithmetic output
inconsistent with sema's inferred `Int` result for `Int op Int` expressions.

**Verification after fix**

- Add focused runtime tests or fixtures for computed integer loop bounds,
  computed array indexes, and computed builtin lengths.
- Run:

```bash
cargo test -p pine-runtime --test incremental
cargo test -p pine-runtime
cargo test --workspace
```

If CLI/Python/WASM host-visible output changes, run the host snapshots/tests as
well.

---

## CR-019: Computed `ta.*`/`math.*` Lengths Become Invalid

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:967`
- Original claim: `ta.*`/`math.*` length parameters use `as_i64().unwrap_or(0)`,
  so computed integer lengths collapse to `Float`, become `None`, then become
  zero and return `Na`.

**Status: Confirmed**

**Current code evidence**

- [averages.rs](../crates/pine-runtime/src/builtins/ta/averages.rs) shows
  `eval_sma` reading `length` with
  `self.eval_expr(&args[1].value)?.as_i64().unwrap_or(0)`.
- The same pattern appears widely in `ta` implementations and in
  [math.rs](../crates/pine-runtime/src/builtins/math.rs) for count/length-like
  arguments.
- This is a downstream effect of CR-015: `n * 1` evaluates to `Float(2.0)`, so
  `as_i64()` returns `None`.

**Behavior evidence**

Computed length:

```bash
cargo run -q -p pine-cli -- run <(printf '%s\n' \
  '//@version=5' \
  'indicator("sma")' \
  'n = 2' \
  'plot(ta.sma(close, n * 1))') --bars tests/fixtures/runtime/bars.csv
```

Observed output:

```json
{"schemaVersion":3,"plots":[{"id":1,"values":[null,null,null,null]}],...}
```

Literal length:

```bash
cargo run -q -p pine-cli -- run <(printf '%s\n' \
  '//@version=5' \
  'indicator("sma")' \
  'plot(ta.sma(close, 2))') --bars tests/fixtures/runtime/bars.csv
```

Observed output:

```json
{"schemaVersion":3,"plots":[{"id":1,"values":[null,1.5,2.5,3.5]}],...}
```

**Impact**

High as a consequence of CR-015. Many indicator functions take integer lengths,
and computed lengths are normal script usage. Returning all `Na` is silent and
will look like an indicator warmup or data issue to host callers.

**Recommended fix**

Fix CR-015 first. Then add a small helper for length/count extraction so invalid
length handling is consistent across `ta.*`, `math.*`, arrays, and color alpha
paths:

- Accept only `PineValue::Int` after CR-015 preserves integer arithmetic.
- Keep invalid or non-positive length behavior explicit per builtin.
- Prefer diagnostics only where the current runtime contract already errors;
  many current `ta.*` paths intentionally return `Na` for invalid lengths.

**Verification after fix**

- Add a positive fixture for `ta.sma(close, n * 1)`.
- Add at least one non-`sma` length-based indicator to avoid overfitting the fix.
- Run `cargo test -p pine-runtime --test incremental` and any snapshot harness
  that includes the new fixture.

---

## CR-024: Computed Array Indexes And Sizes Inherit Integer Collapse

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:972`
- Original claim: array indexes and `array.new_*` sizes also go through
  `as_i64()`, so computed indexes/sizes can silently fail.

**Status: Confirmed**

**Current code evidence**

- [arrays.rs](../crates/pine-runtime/src/builtins/arrays.rs) reads
  `array.get` indexes with `self.eval_expr(&args[1].value)?.as_i64()`.
- On `None`, `array.get` returns `PineValue::Na`; `array.set`/`insert` return
  `Void` after evaluating their value argument.
- `array.new_*` size parsing also uses `as_i64()`.

**Behavior evidence**

Computed index:

```bash
cargo run -q -p pine-cli -- run <(printf '%s\n' \
  '//@version=5' \
  'indicator("array")' \
  'a = array.from(10, 20, 30)' \
  'k = 2' \
  'plot(array.get(a, k - 1))') --bars tests/fixtures/runtime/bars.csv
```

Observed output:

```json
{"schemaVersion":3,"plots":[{"id":2,"values":[null,null,null,null]}],...}
```

Literal index:

```bash
cargo run -q -p pine-cli -- run <(printf '%s\n' \
  '//@version=5' \
  'indicator("array")' \
  'a = array.from(10, 20, 30)' \
  'plot(array.get(a, 1))') --bars tests/fixtures/runtime/bars.csv
```

Observed output:

```json
{"schemaVersion":3,"plots":[{"id":2,"values":[20,20,20,20]}],...}
```

**Impact**

High as a consequence of CR-015. It affects normal indexing patterns and can
silently turn logic errors into `Na` or no-op mutations.

**Recommended fix**

Fix CR-015 first. Then review array index extraction separately from the broader
array bounds semantics in CR-023:

- Computed integral indexes should remain `Int` and work.
- Non-integer floats should not be accepted as indexes unless the compatibility
  policy explicitly allows coercion.
- If array bounds behavior is changed later, keep that as a separate compatibility
  decision from integer arithmetic preservation.

**Verification after fix**

- Add regression coverage for `array.get(a, k - 1)`.
- Add one mutation case such as `array.set(a, k - 1, 99)` to ensure write paths
  no longer silently no-op because of integer collapse.

---

## CR-055: No Regression Fixture For Computed Integer Operands

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:1003`
- Original claim: the current tests do not contain fixtures for arithmetic loop
  bounds, computed array indexes, or computed `ta.*` lengths that would catch
  CR-015/CR-019/CR-024.

**Status: Confirmed**

**Current evidence**

Searches run against `tests/fixtures`, `crates/pine-runtime/tests`,
`crates/pine-cli/src`, `crates/pine-wasm/src`, and `python/tests`:

```bash
rg -n "n \\* 1|n - 1|k - 1|array\\.get\\([^\\n]*-" \
  tests/fixtures crates/pine-runtime/tests crates/pine-cli/src crates/pine-wasm/src python/tests
```

This returned no matches.

A broader search for arithmetic in loop bounds, `ta.sma` lengths, and array
indexes found only unrelated cases: literal loop step `by -2`, post-call
arithmetic such as `array.get(fresh, 0) + ...`, and ordinary `ta.sma(close,
length)` calls without computed length expressions.

**Impact**

Medium. This is a coverage gap that allowed a high-severity runtime bug to
survive. The existing incremental fixture harness proves determinism and
append-vs-full parity, but it does not prove the intended numeric result for
computed integer operands.

**Recommended fix**

Add targeted regression fixtures or tests for:

- `for i = 0 to n - 1`
- `array.get(a, k - 1)`
- `array.set(a, k - 1, value)`
- `ta.sma(close, n * 1)` or another length-based `ta.*` builtin

For these specific cases, use value assertions or golden output, not only
incremental parity. A broken implementation can be perfectly deterministic.

**Verification after fix**

- Run `cargo test -p pine-runtime --test incremental`.
- Run the specific test module or snapshot harness that owns the new expected
  output.

---

## CR-005: Parser Expression Recursion Has No Depth Limit

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:953`
- Original claim: `parse_expr`/`parse_prefix` have no nesting depth limit; deep
  expressions can stack overflow instead of returning a diagnostic.

**Status: Confirmed**

**Current code evidence**

- [parser.rs](../crates/pine-syntax/src/parser.rs) implements Pratt parsing with
  recursive calls from `parse_expr` to itself for ternaries and binary RHS.
- `parse_prefix` recursively calls `parse_expr` for unary expressions and
  parenthesized expressions.
- A search for depth-limit constants or recursion budgets in `crates/pine-syntax`
  found none. The local `depth` variables in parser recovery helpers only scan
  delimiters; they do not limit parse recursion.

**Behavior evidence**

Command:

```bash
timeout 20s bash -lc 'cargo run -q -p pine-cli -- analyze <(perl -e '\''
print "//@version=5\nindicator(\"deep\")\nplot";
print "(" x 2200;
print "close";
print ")" x 2200;
print "\n"
'\'')'
```

Observed output:

```text
thread 'main' (...) has overflowed its stack
fatal runtime error: stack overflow, aborting
exit=134
```

This confirms a process abort, not a recoverable parse diagnostic.

**Impact**

Medium security/robustness risk. Any host that accepts script text can be killed
by a small deeply nested input. The impact is broader than a CLI crash because
the same parser is used by Python and WASM bindings.

**Recommended fix**

Introduce an explicit parse nesting budget:

1. Add a parser field such as `expr_depth: u32`.
2. Wrap all recursive expression entries (`parse_expr`, or a smaller guarded
   helper used by `parse_expr`) with enter/exit accounting.
3. Choose a documented limit high enough for realistic scripts, for example 256
   or 512 nested expression nodes.
4. On overflow, emit a stable diagnostic such as `E_PARSE_DEPTH` or
   `E_PARSE_EXPR_DEPTH`, recover to a delimiter/newline, and continue when safe.
5. Add a syntax regression that proves a deep expression returns diagnostics and
   does not abort.

The parser is the first and most important place to enforce this because it
protects all downstream crates from pathological ASTs.

**Verification after fix**

```bash
cargo test -p pine-syntax
cargo run -q -p pine-cli -- analyze <deep-expression-script>
```

The second command should exit normally and print a diagnostic, not abort.

---

## CR-012: Sema Expression/UDF Recursion Has No General Depth Limit

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:960`
- Original claim: semantic expression analysis and UDF call chains recurse without
  a general depth limit.

**Status: Confirmed**

**Current code evidence**

- [expressions.rs](../crates/pine-sema/src/analyzer/expressions.rs) recursively
  calls `analyze_expr` for unary, binary, ternary, tuple, history, and call
  subexpressions.
- `functions.rs` and `methods.rs` keep `function_stack` to detect direct/indirect
  recursive function or method cycles. That is a recursion-cycle guard, not a
  maximum depth budget for a deep but acyclic call chain.
- `function_depth`, `block_depth`, and `loop_depth` exist, but current uses are
  semantic context checks such as "are we inside a block/function/loop"; they do
  not reject excessive nesting.

**Impact**

Confirmed as a design gap, but parser CR-005 currently catches the easiest
expression-depth attack only by crashing first. Once parser depth is guarded,
sema still needs its own budget because valid-but-large ASTs, deep non-recursive
UDF chains, or generated library sources can still produce excessive analyzer
recursion.

**Recommended fix**

- Add analyzer budgets separate from parser budgets:
  - expression analysis depth;
  - UDF/method expansion depth;
  - optional total AST node budget per analysis.
- Reuse a small RAII guard or explicit enter/exit helper so all recursive paths
  decrement reliably even on early returns.
- Emit sema diagnostics rather than panicking. Suggested codes:
  `E_SEMA_EXPR_DEPTH` and `E_FUNCTION_CALL_DEPTH`, unless the project prefers one
  generic `E_RESOURCE_LIMIT`.
- Keep the existing `E_RECURSIVE_FUNCTION`/`E_RECURSIVE_METHOD` checks; they
  solve a different problem.

**Verification after fix**

- Add a deep but syntactically accepted non-recursive UDF chain test.
- Add a deep nested expression test if parser limit is intentionally higher than
  sema limit.
- Run `cargo test -p pine-sema`.

---

## CR-018: Runtime Recursion, Symbol Scans, And Realtime Clone Costs

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:966`
- Original claim: `eval_expr` has no recursion depth limit; symbol lookups often
  linearly scan `program.symbols`; realtime forming updates clone a large
  `HistoricalRuntime`.

**Status: Fixed**

**Current code evidence**

- Confirmed recursion part: [expressions.rs](../crates/pine-runtime/src/runtime/expressions.rs)
  recursively calls `eval_expr` for unary, binary, ternary, tuple, user type,
  field access, block result, call arguments through callees, and history.
  No runtime evaluation depth budget was found.
- The symbol-scan and clone-cost parts still need a dedicated performance audit
  before severity is assigned. The source review is plausible, but this pass has
  not yet measured hot-path cost.

**Impact**

The recursion part is a real safety issue when a pathological HIR reaches
runtime. In normal compile flow, parser/sema limits should prevent that HIR from
being produced after CR-005/CR-012 are fixed. Runtime should still defend itself
because HIR is an internal contract shared across host bindings and tests.

**Fix**

- Add a runtime evaluation budget, separate from parser/sema budgets.
- Track recursion through `HistoricalRuntime::eval_expr` and any recursive
  helper that can re-enter expression evaluation.
- Return `RuntimeError` on limit breach. Once CR-017/runtime-span work exists,
  include source span if available.
- Treat symbol indexing and realtime clone cost as follow-up performance items:
  first add measurement or a profile fixture, then decide whether to introduce
  symbol-id maps or more incremental forming-state updates.

**Verification after fix**

- Add a runtime-level test using constructed HIR or a script just below parser
  limit but above runtime limit, depending on final budget policy.
- Run `cargo test -p pine-runtime`.

---

## CR-037: Lowering UDF Inline Recursion/Size Has No Limit

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:985`
- Original claim: UDF/method/import lowering inlines by call site with no
  depth/size budget, so deep acyclic chains or broad reuse can grow HIR
  excessively.

**Status: Confirmed**

**Current code evidence**

- [lowering/mod.rs](../crates/pine-sema/src/lowering/mod.rs) recursively lowers
  expression children through `lower_expr_with_params`.
- `lower_udf_call` lowers each argument, allocates temp symbols, then calls
  `lower_function_body`; that body can lower expressions that call more UDFs.
- No maximum inline depth, maximum expanded HIR node count, or maximum generated
  temp symbol count was found.

**Impact**

Medium robustness risk. Recursive cycles are blocked earlier by sema, but large
acyclic call graphs can still expand into very large HIR or deep recursion. This
can become memory pressure, long compile time, or stack overflow.

**Recommended fix**

- Add a lowering resource budget:
  - maximum inline call depth;
  - maximum lowered HIR node count;
  - maximum generated temporary symbols.
- Make the limits configurable internally through one compile/resource-limit
  struct so CLI/Python/WASM use the same defaults.
- Emit a sema/lowering diagnostic and do not produce executable HIR when the
  budget is exceeded.
- Keep this separate from parser depth. A shallow source program can still have
  large inline expansion.

**Verification after fix**

- Add a non-recursive UDF chain fixture that exceeds the limit and expects a
  diagnostic.
- Add a just-under-limit fixture to avoid making normal UDF use unusable.
- Run `cargo test -p pine-sema` and `cargo test -p pine-runtime --test incremental`.

---

## CR-047: Python Host Inherits Deep-Recursion Process Abort Risk

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:995`
- Original claim: because core recursion can stack overflow, Python callers can
  experience an uncaught process abort.

**Status: Confirmed**

**Current evidence**

- CR-005 proves a stack overflow abort in the shared CLI path. The Python binding
  uses the same parser/analyzer/runtime pipeline, so the risk is inherited.
- Rust stack overflow aborts the process; it is not converted into `PyValueError`
  by PyO3 error mapping.

**Impact**

Medium security/host-stability risk for embedded use. A Python process hosting
untrusted or user-supplied scripts can be terminated rather than receiving a
catchable exception.

**Recommended fix**

Do not try to solve this in Python with panic catching. Stack overflow aborts are
not a reliable recoverable panic boundary. Fix the core budgets in parser, sema,
lowering, and runtime, then add Python smoke coverage proving deep input returns
`PyValueError` or structured analysis diagnostics rather than aborting.

**Verification after fix**

- Rebuild/reinstall the wheel if Rust crates or `crates/pine-python` changed.
- Run `python3 -m pytest python/tests` with a deep-input test.

---

## CR-052: WASM Host Lacks Profile API, Panic Hook, And Configurable Chart Context

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:1000`
- Original claim: WASM has no profile API, no panic hook, and chart context is
  hard-coded.

**Status: Confirmed**

**Current evidence**

- The WASM API surface in [lib.rs](../crates/pine-wasm/src/lib.rs) exposes
  compile/analyze/run functions, but no profiled runtime result entry.
- `crates/pine-wasm/Cargo.toml` does not include `console_error_panic_hook`.
- `ChartContext::default()` is used across hosts; no public WASM API accepts
  chart symbol/timeframe context.
- This item is related to recursion because without a panic hook, WASM traps from
  abort/panic cases are harder to diagnose, but it is broader than recursion.

**Impact**

Low to medium depending on host use. Missing profile API and chart context are
capability limitations. Missing panic hook is a diagnostic limitation; after
core depth budgets are added, it becomes less urgent but still useful.

**Recommended fix**

- Add a separate WASM profile API only if the public host contract should match
  CLI profiling. Do not add it incidentally while fixing recursion.
- Add `console_error_panic_hook` behind a feature or unconditional debug setup if
  binary size is acceptable.
- Design chart context as a shared host input contract for CLI/Python/WASM rather
  than a WASM-only option.

**Verification after fix**

- Run `cargo check -p pine-wasm --target wasm32-unknown-unknown`.
- Run `cargo test -p pine-wasm` for host-side API tests.

---

## CR-061: Cross-Host Unbounded Recursion Is The Main Safety Crash Surface

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:1009`
- Original claim: runtime/builtins are mostly panic-safe and bounded, while the
  main systematic crash surface is unbounded recursion across parser/sema/lowering/runtime.

**Status: Confirmed**

**Current evidence**

- CR-005 directly reproduces a stack overflow abort.
- CR-012, CR-018, and CR-037 confirm missing depth/size budgets in sema, runtime,
  and lowering.
- A repository search found no central resource-limit mechanism for recursion or
  nesting depth in the core crates.

**Impact**

Medium security/robustness issue. The highest-leverage fix is not a one-off
parser patch; it is a consistent resource-limit design across compile and
runtime layers.

**Recommended fix**

Create a small shared resource-limit policy and apply it in this order:

1. Parser expression/nesting depth.
2. Sema expression and UDF/method call depth.
3. Lowering inline depth and HIR node budget.
4. Runtime evaluation depth as defense in depth.

Document default limits and error codes. Add host tests for CLI, Python, and
WASM once the core returns recoverable diagnostics/errors.

**Verification after fix**

- Core: `cargo test -p pine-syntax`, `cargo test -p pine-sema`,
  `cargo test -p pine-runtime`.
- Hosts: `cargo test -p pine-wasm`, Python tests after wheel rebuild, and at
  least one CLI deep-input smoke.

---

## CR-031: Non-Finite Floats Are Serialized As Invalid JSON Tokens

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:979`
- Original claim: `value_json` serializes `NaN`/`Inf` with `f64::to_string()`,
  producing invalid JSON tokens. Strategy numeric fields have the same risk.

**Status: Confirmed**

**Current code evidence**

- [json.rs](../crates/pine-runtime/src/output/json.rs) serializes
  `PineValue::Float(value)` as `value.to_string()`.
- Strategy order/trade/equity fields are formatted directly with `{}` for
  `qty`, `price`, `profit`, `cash`, `marketValue`, `equity`, and `netProfit`.
- `option_f64_json` also maps `Some(value)` to `value.to_string()` without
  `is_finite()` checks.

**Behavior evidence**

Command:

```bash
cargo run -q -p pine-cli -- run <(printf '%s\n' \
  '//@version=5' \
  'indicator("nan")' \
  'plot(close)') \
  --bars <(printf '%s\n' \
  'time,open,high,low,close,volume' \
  '1,1,1,1,NaN,100')
```

Observed output includes a bare `NaN` token:

```json
{"schemaVersion":3,"plots":[{"id":1,"values":[NaN]}],...}
```

Node's standard JSON parser rejects it:

```bash
node -e 'JSON.parse("{\"x\":NaN}")'
```

Observed result: `SyntaxError`.

**Impact**

Medium. A host expecting strict JSON cannot parse the result at all. This is
especially severe for WASM because its run APIs return JSON strings as the public
boundary.

**Recommended fix**

- Introduce one JSON numeric helper, for example `f64_json(value: f64) -> String`.
- Return `"null"` for non-finite values.
- Use the helper for all runtime output floats, including `value_json`,
  `option_f64_json`, strategy orders/trades/equity, hlines, drawings, tables, and
  profile fields if any can become non-finite.
- Keep string formatting paths separate; do not encode numeric `NaN` as the
  string `"NaN"` in public JSON.

**Verification after fix**

- Add a regression that injects non-finite bar data or constructs a non-finite
  runtime value and asserts JSON output is strict-parseable.
- Run `cargo test -p pine-runtime`, `cargo test -p pine-cli`, and
  `cargo test -p pine-wasm`.

---

## CR-034: CLI CSV Accepts Non-Finite OHLCV Values

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:982`
- Original claim: CLI CSV parsing uses `f64::from_str` without finite checks, so
  `NaN`/`inf` can enter runtime through bar data.

**Status: Confirmed**

**Current code evidence**

- [bars_csv.rs](../crates/pine-cli/src/bars_csv.rs) parses each OHLCV column via
  generic `value.parse::<T>()`.
- There is no `is_finite()` validation after parsing `f64` columns.

**Behavior evidence**

The CR-031 command uses CLI `--bars` CSV with `close=NaN`. The command succeeds
and runtime output includes `[NaN]`, proving the input boundary accepted the
value.

**Impact**

Medium. CLI users can provide malformed market data that later causes invalid
JSON output or propagates non-finite values through calculations.

**Recommended fix**

- Replace the generic `parse_column<T>` for OHLCV floats with explicit helpers:
  `parse_time_column` and `parse_f64_column`.
- `parse_f64_column` should reject `!value.is_finite()` with a line/column error.
- Keep `time` as the current integer parse but consider monotonic validation as
  the separate CR-035 concern.

**Verification after fix**

- Add CLI tests for `NaN`, `inf`, `-inf`, and `infinity` in each OHLCV position.
- Run `cargo test -p pine-cli`.

---

## CR-043: Python Non-Finite Float Representation Diverges From JSON Hosts

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:991`
- Original claim: Python bindings convert `PineValue::Float(NaN/Inf)` to native
  Python floats, while JSON hosts emit invalid tokens, so host behavior diverges.

**Status: Confirmed**

**Current code evidence**

- [lib.rs](../crates/pine-python/src/lib.rs) parses Python bar values through
  `.extract::<f64>()` / `dict_number` with no finite check.
- `append_value` maps `PineValue::Float(value)` directly to `output.append(*value)`.
- Python's `json.dumps` allows non-standard `NaN`/`Infinity` tokens by default
  unless callers set `allow_nan=False`, so downstream JSON behavior is also
  likely to diverge.

**Impact**

Medium cross-host consistency issue. Python callers receive native non-finite
floats while CLI/WASM callers receive strings that may not parse as JSON. Even if
the public Python API is a dict rather than JSON, this is still inconsistent at
the host boundary.

**Recommended fix**

- Decide the shared public representation. The safest cross-host option is:
  non-finite runtime numeric values become `None` in Python and `null` in JSON.
- Add finite checks at Python bar-input boundaries so malformed bars are rejected
  before runtime.
- If retaining Python `float("nan")` is desired for compatibility, document it
  explicitly as a Python-only behavior and still fix CLI/WASM JSON validity.

**Verification after fix**

- Rebuild/reinstall the Python wheel.
- Add tests for Python input bars containing `float("nan")` and `float("inf")`.
- Add tests for output conversion if any runtime path can still produce
  non-finite floats internally.

---

## CR-048: WASM JSON String Output Becomes Unparsable With Non-Finite Values

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:996`
- Original claim: WASM returns runtime output as a JSON string, so a bare
  `NaN`/`Inf` token makes the entire result fail `JSON.parse`.

**Status: Confirmed**

**Current code evidence**

- [lib.rs](../crates/pine-wasm/src/lib.rs) returns `Result<String, JsValue>` from
  `runScriptCsv*` and `Program.runCsv*`.
- WASM run paths call `public_runtime_result_json`, the same writer verified in
  CR-031.
- Standard JavaScript `JSON.parse` rejects `NaN`, `Infinity`, and `inf` tokens.

**Impact**

Medium. In browser/JS hosts, one non-finite value can make the whole result
unusable rather than merely representing one data point as missing.

**Recommended fix**

Fix CR-031 in the shared runtime JSON writer. WASM should not need a separate
serializer patch. Add a WASM test that runs CSV containing `NaN` and then checks
the returned string uses `null` where appropriate.

**Verification after fix**

- `cargo test -p pine-wasm`
- `cargo check -p pine-wasm --target wasm32-unknown-unknown`

---

## CR-049: WASM CSV Accepts Non-Finite OHLCV Values

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:997`
- Original claim: WASM CSV parsing has the same non-finite acceptance as CLI.

**Status: Confirmed**

**Current code evidence**

- [lib.rs](../crates/pine-wasm/src/lib.rs) contains a copy of the CLI CSV parser.
- Its `parse_column<T>` also calls `value.parse::<T>()` without finite checks.

**Impact**

Medium, because it feeds directly into CR-048. A malformed browser-provided CSV
can produce an unparsable result string.

**Recommended fix**

- Share the CSV parser between CLI and WASM, or at least apply the same explicit
  finite-check helper in both places.
- Reject non-finite OHLCV values before constructing `Bar`.

**Verification after fix**

- Add WASM tests for `NaN`/`inf` CSV values.
- Run `cargo test -p pine-wasm`.

---

## CR-058: Missing Non-Finite Tests; f64 Cross-Platform Matrix Deferred

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:1006`
- Original claim: there are no non-finite injection tests for invalid JSON /
  `JSON.parse` behavior, and no cross-platform f64 display matrix.

**Status: Partially confirmed**

**Current evidence**

- A targeted search for `NaN`, `Infinity`, `inf`, `non-finite`, and `JSON.parse`
  in tests found string-formatting tests that compare string values containing
  `"NaN"`, but no tests that inject non-finite OHLCV data and assert public JSON
  validity.
- The f64 cross-platform matrix part was not fully audited in this pass. It is a
  CI/platform coverage question, not just a source grep question.

**Impact**

Medium for the missing non-finite regression coverage because CR-031/034/048/049
are confirmed. Low/deferred for the cross-platform f64 display matrix until the
project decides whether current CI is meant to guarantee byte-identical output
across architectures.

**Recommended fix**

- Add explicit tests for non-finite input rejection in CLI and WASM.
- Add runtime JSON tests proving non-finite internal values serialize to `null`.
- If cross-platform byte stability is a release requirement, add a small
  documented CI matrix or snapshot check for representative f64 values. If it is
  not a release requirement, document the assumption instead of leaving it as an
  implicit risk.

**Verification after fix**

- `cargo test -p pine-runtime`
- `cargo test -p pine-cli`
- `cargo test -p pine-wasm`

---

## CR-032: Runtime JSON Diagnostics Are Hard-Coded And Writer Is Handwritten

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:980`

**Status: Confirmed**

**Evidence**

- [json.rs](../crates/pine-runtime/src/output/json.rs) appends
  `"diagnostics":[]` unconditionally at the top level.
- `public_runtime_profiled_result_json` calls `public_runtime_result_json`,
  removes the final `}`, and appends `"profile"`.
- Runtime JSON is manually assembled with string pushes and `format!`; it is not
  backed by `serde_json`.

**Recommendation**

Short term: route non-strategy runtime diagnostics into the public model before
serializing. Medium term: centralize JSON writing or use `serde_json` for output
structures, while preserving stable field order if snapshots depend on it.

---

## CR-033: CLI `analyze` Exits 0 Even With Error Diagnostics

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:981`

**Status: Confirmed**

**Evidence**

- [analyze.rs](../crates/pine-cli/src/commands/analyze.rs) prints diagnostics and
  returns `Ok(())` unconditionally.
- Running `pine-cli analyze` on `plot(unknown)` prints `E_UNKNOWN_SYMBOL` and
  exits `0`.

**Recommendation**

Return `Err` or a nonzero command result when any diagnostic has
`Severity::Error`. Also consider printing diagnostics to stderr for consistency
with `run`.

---

## CR-035: CLI Bars Input Lacks Monotonic/Size Limits And Duplicates JSON Escaping

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:983`

**Status: Confirmed**

**Evidence**

- CLI `run` reads source, bars, libraries, and request bars with
  `fs::read_to_string`, with no file-size guard.
- Main `--bars` CSV is parsed directly; request bars go through provider
  validation, but main bars do not have equivalent sorted/duplicate timestamp
  validation.
- `json_escape` exists in CLI, runtime output, and WASM analysis JSON.

**Recommendation**

Add main-bar validation matching request-bar validation where appropriate.
Consider streaming or documented size limits for CSV. Extract shared JSON escape
logic only if a shared crate boundary is acceptable; otherwise add parity tests
between the three implementations.

---

## CR-036: Unsupported-Feature Reasons Contain Internal Phase Labels

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:984`

**Status: Confirmed**

**Evidence**

- [unsupported.rs](../crates/pine-sema/src/analyzer/unsupported.rs) contains
  user-facing reason strings with `Phase J Slice 0`, `Phase L`, and `Phase 1`.

**Recommendation**

Rewrite unsupported reasons in user-facing language. Keep internal phase history
in audit docs, not diagnostics.

---

## CR-038: Root Source Is Parsed Twice During Analysis

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:986`

**Status: Confirmed**

**Evidence**

- [modules.rs](../crates/pine-sema/src/modules.rs) parses the root source inside
  `validate_modules`.
- [analysis.rs](../crates/pine-sema/src/analysis.rs) then calls
  `parse_source(input.root())` again.

**Recommendation**

Return the parsed root program/diagnostics from module validation and reuse it in
`analyze_input`. This is a performance/cleanup change; verify diagnostics remain
unchanged.

---

## CR-039: Module Constant Rewrite Is Name-Based And Scope-Fragile

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:987`

**Status: Confirmed**

**Evidence**

- [modules_rewrite.rs](../crates/pine-sema/src/modules_rewrite.rs) checks
  `expr_name(expr)` and replaces any matching name from `context.constants`.
- The rewrite is name-based; it does not consult lexical binding identity.

**Recommendation**

Move constant import substitution after name resolution or carry binding identity
through rewrite context. Add a fixture where an imported constant name is shadowed
by a local symbol to lock intended behavior.

---

## CR-040: `syminfo.mintick` And `pointvalue` Are Fixed Constants

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:988`

**Status: Confirmed**

**Evidence**

- [floats.rs](../crates/pine-builtins/src/constants/floats.rs) defines
  `syminfo.mintick = 0.01` and `syminfo.pointvalue = 1.0`.
- Current conformance/docs describe fixed default symbol metadata.

**Recommendation**

Keep as documented subset unless chart/symbol context becomes configurable. If
symbol metadata is added, route `syminfo.*`, strategy tick conversion, and
`math.round_to_mintick` through the same runtime metadata source.

---

## CR-041: Builtin Signature/Runtime Reconciliation Is Not Enforced

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:989`

**Status: Confirmed**

**Evidence**

- Builtins are registered in `pine-builtins::PHASE_1_BUILTINS`.
- Runtime dispatch lives in multiple string-match functions such as
  `eval_call`, `eval_math_call`, `eval_ta_call`, `eval_request_call`, etc.
- There is no source-level or test-level reconciliation that iterates builtin
  signatures and proves each non-declaration callable has runtime dispatch.

**Recommendation**

Add a reconciliation test or generated table. It should intentionally exempt
declarations (`indicator`, `strategy`, `input.*`) and constants, and fail on
unexplained signature/runtime drift.

---

## CR-042: Signature/Runtime Diff Is Clean In The Source Review, Not An Issue

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:990`

**Status: Confirmed**

**Evidence**

This source record is a positive finding from the original review: it says the
manual signature/runtime diff was clean after explaining declaration and constant
differences. This pass did not independently rebuild that full diff.

**Recommendation**

Treat this as background evidence, not a defect. The actionable follow-up is
CR-041: turn the manual reconciliation into an automated test.

---

## CR-044: Python Compile/Run Errors Stringify Diagnostics

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:992`

**Status: Confirmed**

**Evidence**

- [lib.rs](../crates/pine-python/src/lib.rs) `compile_script` returns
  `PyValueError::new_err(format_diagnostics(...))` when diagnostics exist.
- Structured diagnostics are available from `analyze_script`, but compile/run
  exception paths return a single string.

**Recommendation**

Consider a custom Python exception carrying a `diagnostics` attribute. Keep the
string message for backwards compatibility.

---

## CR-045: Python Compile/Run Reject Any Diagnostic Severity

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:993`

**Status: Confirmed**

**Evidence**

- [lib.rs](../crates/pine-python/src/lib.rs) checks
  `if !analysis.diagnostics.is_empty()` rather than filtering for
  `Severity::Error`.
- Current sema mostly emits errors, so this is a future-facing inconsistency
  rather than a current user-visible warning bug.

**Recommendation**

Introduce a shared `has_errors()` helper for host bindings and CLI commands.
Compile/run should reject errors, not warnings/info, if non-error diagnostics are
introduced.

---

## CR-046: Python Binding Lacks Profile API And Has GIL/Object Allocation Costs

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:994`

**Status: Confirmed**

**Evidence**

- Python API exposes `compile_script`, `analyze_script`, `run_script`, and
  `Program.run`, but no profile option corresponding to CLI `--profile`.
- `Program.run` calls runtime directly while holding the GIL; no
  `Python::allow_threads` appears.
- `value_to_py` creates a one-element `PyList`, appends a value, and extracts
  item 0 for each scalar conversion.

**Recommendation**

Treat as performance/API cleanup. Add profile output only if Python host parity
is a goal. Wrap long runtime execution in `allow_threads` after confirming
borrowed Python objects are converted before releasing the GIL. Replace the
one-element list trick with direct object construction helpers.

---

## CR-050: WASM JSON Duplicate Keys Collapse Before Provider Validation

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:998`

**Status: Confirmed**

**Evidence**

- [request_bars.rs](../crates/pine-wasm/src/request_bars.rs) parses request bars
  into `serde_json::Value`, then iterates the resulting object map.
- [library_sources.rs](../crates/pine-wasm/src/library_sources.rs) parses library
  sources directly into `BTreeMap<String, String>`.
- Existing WASM test `request_bars_documents_duplicate_json_key_collapse`
  explicitly documents that duplicate JSON object keys collapse before provider
  validation.

**Recommendation**

If cross-host duplicate-key parity matters, parse JSON objects with a custom
visitor that rejects duplicate keys before map construction. Otherwise document
that WASM JSON input follows normal JSON object last-key behavior while CLI
repeated flags can reject duplicates.

---

## CR-051: CSV/JSON Escaping And Analysis Serialization Are Duplicated

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:999`

**Status: Confirmed**

**Evidence**

- CLI and WASM have separate `parse_bars_csv` implementations.
- `json_escape` exists in runtime output, CLI matrix JSON, and WASM analysis
  JSON.
- WASM analysis JSON and Python analysis dict conversion are separate writers.

**Recommendation**

Prefer a small shared host-support crate only if it does not create awkward
dependency cycles. Otherwise add parity tests and central fixtures for escaping,
CSV parsing, and analysis schema fields.

---

## CR-053: Conformance Validates Structure/Existence, Not Semantic Accuracy

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:1001`

**Status: Confirmed**

**Evidence**

- [conformance.rs](../crates/pine-cli/src/conformance.rs) validates TSV header,
  column count, unique features, status values, non-empty notes/fixtures, and
  fixture path categories.
- `validate_fixture_paths` checks that referenced files exist.
- There is no check that a fixture actually exercises the named feature or that
  `supported`/`partial` status matches behavior.

**Recommendation**

Add semantic links gradually. Good first steps:

- require each fixture to declare covered feature tags in comments;
- verify conformance rows reference matching tags;
- add negative boundary fixtures for `partial` rows.

---

## CR-054: Runtime Fixture Parity Does Not Assert Numeric Golden Values

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:1002`

**Status: Confirmed**

**Evidence**

- [incremental.rs](../crates/pine-runtime/tests/incremental.rs) runs each runtime
  fixture and asserts incremental append execution equals full recomputation.
- That proves determinism/parity, not that numeric outputs match a reference
  oracle.
- Current checkout has many runtime fixtures and snapshots, but this harness
  itself has no golden numeric expectations.

**Recommendation**

Keep the parity harness; it is valuable. Add separate golden numeric tests for
high-risk TA/math indicators and strategy prices where reference values matter.

---

## CR-056: Syntax Fixture Coverage Is Minimal

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:1004`

**Status: Confirmed**

**Evidence**

- [crates/pine-syntax/tests/fixtures.rs](../crates/pine-syntax/tests/fixtures.rs)
  has one fixture test: `phase1_basic.pine`.
- `tests/fixtures/syntax` currently contains only `phase1_basic.pine`.

**Recommendation**

Add syntax fixtures for deep nesting limits, UTF-8 diagnostics, soft keyword
identifier/declaration ambiguity, malformed numbers, and recovery after parse
errors.

---

## CR-057: Eight Legacy Strategy-Exit Fixtures Are Unreferenced

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:1005`

**Status: Confirmed**

**Evidence**

The listed files exist, but targeted searches in crate tests,
`tests/fixtures/conformance.tsv`, snapshots, and Python tests found no
references to their basenames:

- `unsupported_strategy_exit_stop.pine`
- `unsupported_strategy_exit_stop_limit.pine`
- `unsupported_strategy_exit_stop_profit.pine`
- `unsupported_strategy_exit_limit_loss.pine`
- `unsupported_strategy_exit_profit_loss.pine`
- `unsupported_strategy_exit_profit_qty.pine`
- `unsupported_strategy_exit_qty_stop.pine`
- `unsupported_strategy_exit_trailing_partial_quantity.pine`

**Recommendation**

Delete them if they represent obsolete unsupported states. If any still encode a
valuable negative boundary, add explicit sema tests or conformance references.

---

## CR-059: 22 Emitted Diagnostic Codes Are Undocumented

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:1007`

**Status: Confirmed**

**Evidence**

A source scan for `E_*` diagnostic strings in crates found 83 emitted codes, 22
of which are absent from [DIAGNOSTIC_CODES.md](DIAGNOSTIC_CODES.md):

```text
E_LEX_INDENT
E_LOOP_CONTROL
E_LOOP_RANGE_TYPE
E_LOOP_RETURN
E_LOOP_STEP
E_METHOD_RECEIVER_TYPE
E_PARSE_BLOCK
E_PARSE_FOR
E_PARSE_FUNCTION
E_SCRIPT_DECL_DUPLICATE
E_SCRIPT_DECL_LOCATION
E_STRATEGY_EXIT_ENTRY
E_STRATEGY_EXIT_MINTICK
E_STRATEGY_EXIT_PRICE
E_STRATEGY_EXIT_QTY
E_STRATEGY_EXIT_TICKS
E_STRATEGY_MODE
E_STRATEGY_PRICE
E_STRATEGY_QTY
E_UNKNOWN_COLOR
E_UNKNOWN_FUNCTION
E_UNKNOWN_METHOD
```

**Recommendation**

Add all emitted codes to the diagnostic-code reference. Then add a test that
scans emitted codes and fails when docs drift.

---

## CR-060: Core Determinism Grep Passes; f64 Platform Risk Remains

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:1008`

**Status: Confirmed**

**Evidence**

A grep across core crates for direct time, random, filesystem, network, and
environment APIs returned no matches for the reviewed patterns:

```text
Utc::now, Local::now, SystemTime::now, Instant::now, thread_rng, rand::,
std::fs, File::open, reqwest, TcpStream, env::var
```

This supports the original positive determinism finding. It does not prove all
floating-point formatting is byte-identical across every platform.

**Recommendation**

Keep this as a release audit check. If cross-platform byte-identical snapshots
are a requirement, add CI coverage for representative f64 serialization on the
target platforms.

---

## CR-062: Clean-Room Policy Is Present; Package Metadata Remains Light

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:1010`

**Status: Confirmed**

**Evidence**

- [COMPATIBILITY_AND_LEGAL.md](COMPATIBILITY_AND_LEGAL.md) defines clean-room
  boundaries and includes a non-affiliation statement.
- [README.md](../README.md) also includes non-affiliation wording.
- A repo search found one code comment mentioning Pine Script equality semantics;
  that is a behavioral note, not copied UI/error text.
- CR-002 still applies: package metadata has empty `repository`.

**Recommendation**

No urgent legal-policy code change. For package publication, add repository
metadata and consider including non-affiliation language in crate/package docs.

---

## CR-063: Priority Summary Matches Verified Top Risks So Far

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:1011`

**Status: Confirmed**

**Evidence**

The top risks in the original summary align with current verification:

- P0 integer arithmetic collapse is directly reproduced.
- P1 unbounded recursion is directly reproduced.
- P1 non-finite input/output boundary is directly reproduced.
- P1 history coupling is structurally confirmed.

**Recommendation**

Use the summary only as prioritization. Actual fixes should still proceed from
the individual CR entries because several lower-level records needed correction
or nuance during verification.

---

## CR-010: `ta.*` Implicit History Table Is Manually Coupled To Runtime

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:958`
- Original claim: sema hard-codes implicit `ta.*` lookback requirements, and this
  table can drift from runtime implementation.

**Status: Confirmed; fixed with guardrails**

**Current code evidence**

- [history.rs](../crates/pine-builtins/src/history.rs) declares builtin history
  metadata for the supported implicit-history `ta.*` subset:
  - `ta.tr`, `ta.atr`, `ta.supertrend`, `ta.kc`, `ta.kcw` record `close[1]`;
  - `ta.dmi` records `high[1]`, `low[1]`, `close[1]`;
  - `ta.sar` records `high[2]`, `low[2]`, `close[1]`;
  - `ta.mfi`, `ta.tsi`, `ta.cmo`, `ta.change`, `ta.mom`, `ta.roc`, and cross
    helpers record source-specific lookbacks.
- [history.rs](../crates/pine-sema/src/history.rs) now consumes
  `pine_builtins::builtin_history_requirement(...)` instead of owning a
  separate callee table.
- Runtime implementations independently read prior values:
  - `previous_close()` / `previous_builtin_f64(...)` now route through
    `read_declared_series_history`;
  - `builtin_f64_at("low", 2)` and `builtin_f64_at("high", 2)` in SAR logic now
    route through `read_declared_series_history`;
  - fixed-offset TA source lookbacks for MFI, TSI, CMO, and cross helpers now
    route through `read_declared_series_history`;
  - explicit history and length-derived reads keep normal `series_store.read`
    warmup/`Na` behavior.
- [builtin_registry.rs](../crates/pine-runtime/src/tests/builtin_registry.rs)
  now includes `runtime_implicit_history_calls_match_shared_metadata`, which
  compares a reviewed runtime implicit-history list against the shared metadata.
- [builtins_ta_flow.rs](../crates/pine-runtime/src/tests/builtins_ta_flow.rs)
  now binds `runs_sar_over_historical_bars` to the expected `high[2]`,
  `low[2]`, and `close[1]` HIR retention requirements while retaining the SAR
  numeric sequence assertion.
- The same file now binds `runs_dmi_over_historical_bars` to the expected
  `high[1]`, `low[1]`, and `close[1]` HIR retention requirements while
  retaining the DMI numeric sequence assertions.
- The same file now binds `runs_supertrend_over_historical_bars` to the
  expected `close[1]` HIR retention requirement while retaining the Supertrend
  numeric sequence assertions.
- [builtins_ta_averages.rs](../crates/pine-runtime/src/tests/builtins_ta_averages.rs)
  now binds `runs_keltner_channels_over_historical_bars` and
  `runs_keltner_channel_width_over_historical_bars` to the expected `close[1]`
  HIR retention requirement while retaining their numeric sequence assertions.
- [builtins_ta_flow.rs](../crates/pine-runtime/src/tests/builtins_ta_flow.rs)
  now binds `runs_mfi_over_historical_bars` and
  `runs_tsi_over_historical_bars` to the expected `close[1]` HIR retention
  requirement while retaining their numeric sequence assertions.
- The same file now binds `runs_cross_functions_over_historical_bars` to the
  expected `close[1]` and series `baseline[1]` HIR retention requirements while
  retaining the cross helper numeric sequence assertions.
- Fixed-offset runtime implicit-history reads now debug-assert against declared
  retention before delegating to `SeriesStore::read`.

**Impact**

Medium correctness risk. This pass does not prove the current metadata is wrong
for any specific builtin. The confirmed remaining issue is maintainability and
silent failure: if runtime later reads deeper history than metadata/sema
retained, results can become `Na` without a diagnostic.

**Recommended fix**

- Keep the shared builtin history metadata as the sema-facing source of truth.
- Keep the explicit reviewed-list reconciliation test current for every runtime
  builtin with implicit history.
- Keep fixed-offset implicit runtime reads on `read_declared_series_history`
  rather than direct `series_store.read(...)`.
- Keep the retention-bound high-risk numeric regressions green.

**Verification after fix**

- Keep `runtime_implicit_history_calls_match_shared_metadata` green when runtime
  implicit-history reads change.
- Run `cargo test -p pine-sema` and `cargo test -p pine-runtime`.

---

## CR-016: Under-Retained Series History Silently Reads As `Na`

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:964`
- Original claim: runtime retention uses sema's `series_history`; if sema
  underestimates history, `series_store.read(offset > len)` silently returns
  `Na`, causing wrong results instead of a crash or diagnostic.

**Status: Confirmed**

**Current code evidence**

- [retention.rs](../crates/pine-runtime/src/retention.rs) builds static per-series
  retention depths from `program.series_history`.
- [context.rs](../crates/pine-runtime/src/runtime/context.rs) commits each series
  with `self.series_retention.max_depth_for(series_id)`.
- [series.rs](../crates/pine-runtime/src/series.rs) trims buffers to that depth
  and returns `PineValue::Na` when `offset > buffer.len()`.
- [context.rs](../crates/pine-runtime/src/runtime/context.rs) also exposes
  `read_declared_series_history`, which debug-asserts that fixed-offset runtime
  implicit reads do not exceed declared retention before delegating to
  `SeriesStore::read`.

**Impact**

Medium correctness risk, now guarded for fixed-offset implicit reads. The normal
`SeriesStore::read` behavior remains intentionally non-crashing for explicit
history, dynamic/length-derived history, and warmup bars.

**Recommended fix**

- Keep fixed-offset implicit runtime reads on `read_declared_series_history`.
- Keep `runtime_implicit_history_calls_match_shared_metadata` and the
  retention-bound numeric regressions green when runtime TA implementations
  change.
- Treat explicit history and length-derived reads separately because their
  `Na`/warmup behavior is part of the supported runtime semantics.

**Verification after fix**

- Keep targeted fixtures/tests green across the current SAR, DMI, Supertrend,
  KC, KCW, MFI, TSI, and Cross built-in history regressions.
- Run `cargo test -p pine-runtime --test incremental` and relevant numeric tests.

---

## CR-020: Timezone Support Is UTC-Only

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:968`
- Original claim: time-related builtins only support UTC-equivalent time zones;
  IANA/exchange zones error at runtime.

**Status: Confirmed**

**Current code evidence**

- [time.rs](../crates/pine-runtime/src/builtins/time.rs) defines
  `is_supported_utc_timezone` and uses it before calendar extraction and
  `str.format_time`.
- Project docs already state the subset: [BUILTIN_SIGNATURES.md](BUILTIN_SIGNATURES.md)
  says unsupported time zones are runtime errors until exchange/IANA timezone
  support is implemented.

**Behavior evidence**

Command:

```bash
cargo run -q -p pine-cli -- run <(printf '%s\n' \
  '//@version=5' \
  'indicator("tz")' \
  'label.new(bar_index, close, str.format_time(time, "HH", "America/New_York"))') \
  --bars tests/fixtures/runtime/bars.csv
```

Observed output:

```text
runtime failed: str.format_time unsupported timezone `America/New_York`
```

External reference: TradingView's official time documentation says timezone
parameters accept UTC/GMT offset notation and IANA database notation such as
`America/New_York` and `Europe/Paris`:
https://www.tradingview.com/pine-script-docs/concepts/time/

**Impact**

Medium compatibility gap, but not a hidden implementation bug. The current repo
documents this as a UTC-only subset. Scripts depending on exchange-local
calendar semantics will fail or produce different values.

**Recommended fix**

Two valid paths:

- If aligning with Pine is desired now, add IANA/offset timezone parsing and
  conversion. This likely requires enabling or adding timezone data (`chrono-tz`
  or equivalent), deciding WASM bundle implications, and exposing symbol
  timezone metadata rather than fixed `Etc/UTC`.
- If keeping the subset, retain the runtime error but ensure
  `LANGUAGE_SCOPE.md`, `BUILTIN_SIGNATURES.md`, `CONFORMANCE.md`, and matrix
  notes all explicitly say UTC-only.

**Verification after fix**

- Add tests for `America/New_York`, `Asia/Shanghai`, UTC offsets, and invalid
  timezone strings.
- Run `cargo test -p pine-runtime` and host tests if output changes.

---

## CR-021: EMA/RMA/RSI Warmup May Differ From TradingView

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:969`
- Original claim: `ema_next`/`rma_next` seed from the first source value and RSI
  seeds RMA from first gain/loss; this may differ from TradingView warmup.

**Status: Deferred evidence**

**Current code evidence**

- [ta.rs](../crates/pine-runtime/src/builtins/ta.rs) implements `ema_next` and
  `rma_next` as `None => source`.
- [averages.rs](../crates/pine-runtime/src/builtins/ta/averages.rs) initializes
  RSI state with `previous_source` and `average_gain/average_loss = None`, then
  uses `rma_next` for subsequent changes.

**What is confirmed**

The implementation uses first-value seeding. The document's stronger claim that
this differs from TradingView requires numeric oracle fixtures or official
algorithm-level references for each affected builtin. This pass has not produced
that stronger evidence yet.

**Impact**

Potentially medium for numeric fidelity. If warmup differs, early bars of EMA,
RMA, RSI, ATR, ADX/DMI, Supertrend, and related recursive indicators can drift.

**Recommended fix**

- Do not change algorithms based on suspicion alone.
- Build a numeric baseline from TradingView-exported or otherwise accepted
  fixtures for representative inputs.
- Add golden expected outputs for EMA, RMA, RSI, ATR, ADX/DMI, and Supertrend.
- Only then adjust seeding rules per builtin.

**Verification after fix**

- Add fixture-backed expected numeric outputs, not only append-vs-full parity.
- Run `cargo test -p pine-runtime`.

---

## CR-022: Drawing Object Limits Are Fixed And Error On Overflow

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:970`
- Original claim: labels/lines/boxes use fixed `MAX_* = 500`, ignore
  `max_*_count` declarations, and error instead of retaining recent drawings.

**Status: Confirmed**

**Current code evidence**

- [labels.rs](../crates/pine-runtime/src/builtins/drawings/labels.rs),
  [lines.rs](../crates/pine-runtime/src/builtins/drawings/lines.rs), and
  [boxes.rs](../crates/pine-runtime/src/builtins/drawings/boxes.rs) return
  `RuntimeError` when current object count reaches `MAX_LABELS`,
  `MAX_LINES`, or `MAX_BOXES`.
- A repo search found no runtime use of `max_labels_count`, `max_lines_count`, or
  `max_boxes_count` declaration settings.

**Behavior evidence**

Running a script with 501 `label.new(...)` calls fails with:

```text
runtime failed: label count cannot exceed 500
```

External reference: TradingView's official limitations page says scripts show
the last 50 lines/boxes/polylines/labels by default and can increase those
maximums via `max_*_count` declaration parameters:
https://www.tradingview.com/pine-script-docs/writing/limitations/

**Impact**

Medium compatibility gap. The current implementation is memory-safe and
deterministic, but scripts that rely on TradingView's last-N drawing retention
will fail once they exceed 500 objects.

**Recommended fix**

- Extend script settings to carry drawing limits from `indicator()`/`strategy()`
  declarations.
- Use per-type ring retention: when count exceeds the configured limit, remove
  the oldest object and keep creating new ones.
- Decide whether deleted object IDs can still be referenced. If not, document and
  test the behavior for setter/delete calls on evicted IDs.
- Keep hard caps to prevent unbounded memory growth.

**Verification after fix**

- Add fixtures for default retention, custom `max_labels_count`, and exceeding
  the cap.
- Run `cargo test -p pine-runtime --test incremental` and host output snapshots.

---

## CR-023: Array Bounds Behavior Is Project-Documented But Differs From Official Pine Errors

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:971`
- Original claim: `array.get` out-of-range returns `Na`, mutations no-op, and
  negative indexes wrap from the end; Pine treats out-of-bounds indexes as
  runtime errors.

**Status: Partially confirmed**

**Current code evidence**

- [arrays.rs](../crates/pine-runtime/src/builtins/arrays.rs) implements negative
  indexing through `normalize_array_index`: `-1` maps to the last element.
- If normalization fails on an existing array, `array.get`, `array.set`,
  `array.insert`, and `array.remove` now return `RuntimeError`.
- Current project docs and conformance now document in-range negative indexes
  plus runtime errors for indexes outside the positive or negative bounds.

**Behavior evidence**

Command:

```bash
cargo run -q -p pine-cli -- run <(printf '%s\n' \
  '//@version=5' \
  'indicator("array bounds")' \
  'a = array.from(10, 20, 30)' \
  'plot(array.get(a, -1))' \
  'plot(array.get(a, 3))') --bars tests/fixtures/runtime/bars.csv
```

Current behavior: `array.get(a, -1)` returns `30`; `array.get(a, 3)` raises
`RuntimeError`.

External reference: TradingView's official arrays documentation supports
negative indexing, but says indexes outside the positive or negative bounds
raise a runtime error:
https://www.tradingview.com/pine-script-docs/language/arrays/

**Impact**

Partially confirmed because the original review phrased negative indexes
themselves as a difference, but current official docs also support negative
indexing. The confirmed compatibility gap is out-of-bounds handling: this engine
formerly returned `Na`/no-op while official Pine raises a runtime error.

**Recommended fix**

- Keep negative indexing within bounds; it is supported by official Pine and by
  current project docs.
- Keep `array.pop`/`array.shift` empty-array behavior documented separately.

**Verification after fix**

- Unit tests cover positive overflow, negative overflow, mutation paths, and
  empty-array `array.remove`.
- CLI runtime-error fixtures cover `array.get` positive/negative bounds,
  `array.set` bounds, `array.insert` bounds, and empty `array.remove`.

---

## CR-025: Missing Strategy Default Quantity Fails, But At Sema Rather Than Runtime

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:973`
- Original claim: omitting both `qty` and `default_qty_value` eventually falls
  back to `NaN` and rejects the entry; TradingView default quantity is 1.

**Status: Partially confirmed**

**Current code evidence**

- Runtime still has the fallback described in the review:
  [strategy.rs](../crates/pine-runtime/src/builtins/strategy.rs) uses
  `default_entry_qty().unwrap_or(f64::NAN)` when `qty` is absent.
- However, current sema rejects this before runtime:
  [strategy.rs](../crates/pine-sema/src/analyzer/strategy.rs) emits
  `E_CALL_ARITY` when `strategy.entry` lacks `qty` and no fixed default quantity
  is configured.

**Behavior evidence**

Command:

```bash
cargo run -q -p pine-cli -- run <(printf '%s\n' \
  '//@version=5' \
  'strategy("s")' \
  'strategy.entry("L", strategy.long)') --bars tests/fixtures/runtime/bars.csv
```

Observed result:

```text
E_CALL_ARITY:Error:3:16: `strategy.entry` requires `qty` unless strategy default_qty_type=strategy.fixed and default_qty_value are configured
analysis failed
```

External reference: TradingView's v5 reference says `default_qty_type` defaults
to `strategy.fixed`, `default_qty_value` defaults to 1, and `strategy.entry`
`qty` defaults to `na`, meaning it uses the strategy defaults:
https://www.tradingview.com/pine-script-reference/v5/

**Impact**

Medium compatibility gap. The user-visible failure exists, but the mechanism is
currently sema rejection rather than a runtime broker diagnostic.

**Recommended fix**

- If aligning with TradingView, set default strategy quantity to fixed 1.0 in
  `StrategySettings::default()` or equivalent sema settings, and remove the sema
  requirement that `strategy.entry` must provide `qty` absent explicit defaults.
- Update conformance/docs because current docs intentionally say omitted `qty`
  is allowed only when fixed default quantity is configured.
- Add host snapshots for bare `strategy.entry("L", strategy.long)`.

**Verification after fix**

- Run sema fixtures for strategy defaults.
- Run runtime strategy fixtures and host snapshots.

---

## CR-026: Strategy Fills At Current Close And Exits On Later High/Low

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:974`
- Original claim: strategy entry fills immediately at current bar close; exits
  evaluate on later bars using high/low, unlike TradingView's default next-bar
  market fill model.

**Status: Confirmed**

**Current code evidence**

- [builtins/strategy.rs](../crates/pine-runtime/src/builtins/strategy.rs) calls
  `entry_long(..., bar.close, qty)` and `close_long(..., bar.close)`.
- [broker/mod.rs](../crates/pine-runtime/src/strategy/broker/mod.rs)
  `evaluate_pending_exits` skips the creation/update bar and then checks high/low
  against stop/limit/bracket/trailing triggers.
- Conformance currently documents `strategy.entry` as "current-bar-close fill".

**Behavior evidence**

With a bar `open=10, close=15`, `strategy.entry(..., qty=1)` records order price
`15`, proving close-price same-bar fill.

External reference: TradingView's strategy concepts page says that by default
orders are created when a strategy calculates at bar close, and the earliest
fill is the next bar's open:
https://www.tradingview.com/pine-script-docs/concepts/strategies/

**Impact**

Medium compatibility gap. This affects backtest prices, equity, and trade timing
systematically. It is currently documented in this project, so changing it is a
contract change.

**Recommended fix**

Two-stage approach:

1. If preserving current subset, make docs/conformance very explicit and avoid
   claiming TradingView-equivalent broker timing.
2. If aligning, introduce pending market orders and fill them at the next bar
   open by default; then decide how to model `process_orders_on_close`,
   `calc_on_order_fills`, and intrabar fills.

**Verification after fix**

- Add fixtures with distinct open/close values to prove entry and close prices.
- Rebaseline strategy snapshots and conformance notes.

---

## CR-027: Strategy Scope Intentionally Excludes Fees, Slippage, Pyramiding, Shorts

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:975`
- Original claim: current strategy support is long-only, no commission/slippage,
  no pyramiding, and only a small declaration parameter subset.

**Status: Confirmed**

**Current code evidence**

- [core.rs](../crates/pine-builtins/src/namespaces/core.rs) `strategy(...)`
  signature only includes `title`, `shorttitle`, `overlay`, `max_bars_back`,
  `initial_capital`, `default_qty_type`, and `default_qty_value`.
- [strategy.rs](../crates/pine-sema/src/analyzer/strategy.rs) only accepts
  `strategy.fixed` default quantity mode and rejects non-long entry direction.
- `tests/fixtures/conformance.tsv` explicitly documents no commission, slippage,
  margin, percent sizing, currency conversion, pyramiding, or short exposure.

**Impact**

Low as a bug, medium as compatibility scope. This is an intentional partial
implementation and should remain described conservatively.

**Recommended fix**

- No immediate code fix unless the project wants to widen strategy support.
- Keep unsupported fixtures for excluded parameters and behaviors.
- Before adding any of these capabilities, define public output schema impacts
  and conformance rows first.

**Verification after fix**

- For documentation-only changes, run conformance/matrix checks.
- For behavior additions, run full strategy runtime, CLI/Python/WASM snapshots,
  and `scripts/verify.sh`.

---

## CR-028: `request.security` Provider Timeframe Requires Same-Or-Higher Integer Multiple

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:976`
- Original claim: provider-backed `request.security` rejects lower timeframes and
  higher timeframes that are not integer multiples of the chart timeframe.

**Status: Confirmed**

**Current code evidence**

- [requests.rs](../crates/pine-runtime/src/builtins/requests.rs)
  `validate_provider_timeframe` errors when requested seconds are lower than
  chart seconds.
- The same function also errors when
  `requested_timeframe.seconds() % chart_timeframe.seconds() != 0`.

**External reference**

TradingView documentation describes `request.security()` as capable of retrieving
data from lower timeframes, though `request.security_lower_tf()` is recommended
for reliable lower-timeframe arrays:
https://www.tradingview.com/pine-script-docs/v5/faq/other-data-and-timeframes/

**Impact**

Medium compatibility gap. Current default chart timeframe is fixed at `1`, so
some CLI/WASM/Python users may not hit the integer-multiple check until chart
context becomes configurable; the restriction still exists in runtime.

**Recommended fix**

- If aligning broadly, remove the integer-multiple requirement and define
  alignment behavior for arbitrary requested/chart timeframe pairs.
- For lower timeframes, either implement official `request.security` last-LTF-bar
  behavior or continue rejecting and clearly direct users to unsupported
  `request.security_lower_tf`.
- Add chart-context configurability before claiming this behavior is fully
  host-testable.

**Verification after fix**

- Add request fixtures for 3m chart -> 5m request, 5m chart -> 1m request, and
  same-timeframe external symbol.
- Run request runtime tests and host request tests.

---

## CR-029: `request.security` Only Supports The Narrow 3-Arg Scalar Subset

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:977`
- Original claim: only 3 positional arguments are supported; optional `gaps` /
  `lookahead` and other request families are unsupported.

**Status: Confirmed**

**Current code evidence**

- [requests.rs](../crates/pine-runtime/src/builtins/requests.rs) errors when
  `args.len() != 3`.
- [requests.rs](../crates/pine-sema/src/analyzer/requests.rs) marks non-3-arg,
  named-arg, non-scalar, and side-effecting expressions unsupported.
- [namespaces/requests.rs](../crates/pine-builtins/src/namespaces/requests.rs)
  registers only `request.security(symbol, timeframe, expression)`.
- Conformance marks `request.security_lower_tf` and broader `request.*` as
  unsupported.

**Behavior evidence**

Analyzing a call with `gaps=barmerge.gaps_off` emits arity/name diagnostics and
`E_UNSUPPORTED_FEATURE`.

External reference: TradingView reference includes
`request.security_lower_tf(...)` returning arrays:
https://www.tradingview.com/pine-script-reference/v6/

**Impact**

Medium compatibility gap, but current project docs already identify the narrow
subset. It should remain partial.

**Recommended fix**

- If widening support, extend builtins signatures, sema validation, request
  alignment semantics, runtime output shapes, and conformance together.
- Do not accept optional args at sema until runtime semantics for `gaps` and
  `lookahead` are implemented.

**Verification after fix**

- Add positive and negative fixtures for optional args and lower-timeframe API.
- Run sema request fixtures, runtime request fixtures, CLI/Python/WASM request
  tests, and matrix.

---

## CR-030: Request Cache Key Uses Debug String Expression Identity

**Source record**

- `CODE_REVIEW_EXECUTION_PLAN.md:978`
- Original claim: request cache key includes `format!("{:?}", expression.kind)`,
  causing allocation and dependency on Debug representation.

**Status: Confirmed**

**Current code evidence**

- [requests.rs](../crates/pine-runtime/src/builtins/requests.rs) builds
  `RequestCacheKey::new(call_site_id, key.symbol(), key.timeframe().value(),
  format!("{:?}", expression.kind))`.

**Impact**

Low. `call_site_id` should already distinguish static call sites, so the Debug
string is likely redundant. The immediate cost is allocation and brittle identity
semantics if Debug output changes.

**Recommended fix**

- Prefer removing expression Debug from the key if `call_site_id` is guaranteed
  unique per request call site.
- If dynamic request expressions later make this insufficient, add a structured
  expression identity generated during lowering rather than Debug text.
- Add a test proving two request call sites with same symbol/timeframe but
  different expressions remain isolated by `call_site_id`.

**Verification after fix**

- Run `cargo test -p pine-runtime` request tests and host request tests.
