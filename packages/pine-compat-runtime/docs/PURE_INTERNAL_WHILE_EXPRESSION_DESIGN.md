# Pure Internal While Expression Design Gate

Status: first positive scalar source subset implemented. This document remains
the reference for the supported boundary and deferred `while` expression
variants.

This document defines the internal path for `while` expressions. It is scoped to
parser shape, semantic analysis, HIR lowering, runtime expression evaluation,
block scoping, loop control, stateful callsites, history, rollback, and
conformance. It does not cover host UI, rendering, external data, or public
serialization.

## Current Boundary

`while` supports statement loops:

```pine
while close > open
    break
```

The first source-level `while` expression subset is also supported for scalar
results:

```pine
result = while close > open
    close
```

Current evidence:

- `docs/PURE_INTERNAL_ROADMAP.md` lists scalar `while` expressions as
  implemented and records the remaining wider variants.
- `tests/fixtures/conformance.tsv` marks `while` partial and records the scalar
  while-expression subset with fixture-backed syntax and runtime evidence.
- `tests/fixtures/syntax/while_expression.pine` and
  `crates/pine-syntax/tests/fixtures.rs::parses_while_expression_fixture` keep
  fixture-backed syntax acceptance and `ExprKind::While` AST shape in place.
- `tests/fixtures/runtime/while_expression.pine` and
  `crates/pine-runtime/src/tests/runtime_control_flow.rs::runs_while_expression_scalar_result`
  cover source-level runtime execution, zero-iteration `na`, latest result, and
  break/continue result behavior.
- `tests/fixtures/runtime/while_expression_stateful_scope.pine`,
  `tests/fixtures/sema/unsupported_while_expression_scope_leak.pine`, and
  their Rust gates cover stateful callsite advancement, loop-local `var`
  declaration-site persistence, and body-local no-leak diagnostics.
- `tests/fixtures/runtime/while_expression_nested_control.pine` and
  `crates/pine-runtime/src/tests/runtime_control_flow.rs::runs_while_expression_nested_control`
  cover break/continue containment when a while expression is evaluated inside
  an outer loop.
- `tests/fixtures/runtime/while_expression_tuple.pine` and
  `crates/pine-runtime/src/tests/runtime_control_flow.rs::runs_while_expression_tuple_result`
  cover tuple declaration/destructuring from while-expression results.
- `tests/fixtures/sema/unsupported_while_expression_nested_array_result.pine`
  and
  `crates/pine-sema/src/tests/type_arrays.rs::rejects_while_expression_nested_array_result`
  keep nested-array results rejected until nested collection semantics are
  designed.
- `tests/fixtures/sema/unsupported_while_expression_no_final_result.pine` and
  `crates/pine-sema/tests/fixtures.rs::reports_unsupported_while_expression_no_final_result_fixture`
  keep bodies without a final result expression rejected with
  `E_BRANCH_RETURN`.
- `tests/fixtures/sema/unsupported_while_expression_reassignment_result.pine`
  and
  `crates/pine-sema/tests/fixtures.rs::reports_unsupported_while_expression_reassignment_result_fixture`
  keep bodies ending in reassignment statements rejected with
  `E_BRANCH_RETURN` until side-effect-only body results have explicit
  semantics.
- `tests/fixtures/sema/unsupported_while_expression_break_result.pine`,
  `tests/fixtures/sema/unsupported_while_expression_continue_result.pine`, and
  their `crates/pine-sema/tests/fixtures.rs` gates keep bodies ending in
  loop-control statements rejected with `E_BRANCH_RETURN`; `break` can preserve
  an already-produced result and `continue` can skip a result expression, but
  neither statement itself produces one.
- `tests/fixtures/sema/unsupported_while_expression_alert_result.pine` and
  `crates/pine-sema/tests/fixtures.rs::reports_unsupported_while_expression_alert_result_fixture`
  keep void side-effect calls rejected as while-expression results with
  `E_BRANCH_RETURN`.
- `tests/fixtures/runtime/while_expression_array_history.pine` covers committed
  history reads from scalar-array while-expression results, including fresh
  historical copies whose mutation does not affect the current array result and
  the first-bar `na` predicate for the missing prior array result, including a
  dynamic `na` offset predicate.
- `tests/fixtures/runtime/while_expression_array_control.pine` covers
  scalar-array while-expression result preservation across `continue` and
  `break`, where `continue` skips the final result expression and `break`
  returns the latest already-produced array result.
- `tests/fixtures/runtime/while_expression_array_zero.pine` covers the
  zero-iteration `na` result for scalar-array while expressions, including a
  safe branch-gated `array.size` call on the `na` result.
- `tests/fixtures/runtime/while_expression_matrix.pine` covers
  `matrix<float>` while-expression results with caller-side reads and mutation,
  including fresh matrix results and existing-matrix alias returns.
- `tests/fixtures/runtime/while_expression_matrix_kinds.pine` and
  `tests/fixtures/sema/supported_while_expression_matrix_kinds.pine` cover
  `matrix<int>`, `matrix<bool>`, `matrix<string>`, and `matrix<color>`
  while-expression results with caller-side reads and mutation.
- `tests/fixtures/runtime/while_expression_matrix_control.pine` covers
  `matrix<float>` while-expression result preservation across `continue` and
  `break`, where `continue` skips the final result expression and `break`
  returns the latest already-produced matrix result.
- `tests/fixtures/runtime/while_expression_matrix_history.pine` covers
  committed history reads from `matrix<float>` while-expression results,
  including fresh historical copies whose mutation does not affect the current
  matrix result and the first-bar `na` predicate for the missing prior matrix
  result, including a dynamic `na` offset predicate.
- `tests/fixtures/runtime/while_expression_matrix_zero.pine` covers the
  zero-iteration `na` result for `matrix<float>` while expressions, including
  safe shape-reader calls on the `na` result.
- `tests/fixtures/runtime/import_udt_while_expression.pine` and
  `crates/pine-sema/src/tests/compatibility.rs::import_accepts_while_expression_imported_user_type_result`
  cover same-imported-identity while-expression results.
- `tests/fixtures/sema/unsupported_imported_udt_while_identity.pine` keeps
  local/imported typed identity mismatches rejected for while-expression
  results.
- `crates/pine-syntax/src/parser.rs` accepts `while` in expression position and
  preserves the condition/body AST shape.
- `crates/pine-sema/src/analyzer/expressions.rs` requires a bool condition and
  final-result body shape before lowering.
- `crates/pine-ir/src/lib.rs` has `HirExprKind::While` result metadata carrying
  condition, prefix statements, and a result expression.
- `crates/pine-runtime/src/runtime/expressions.rs` executes while-expression HIR
  for the scalar subset, including zero-iteration `na`, latest result updates,
  `break`, `continue`, and the shared iteration guard.
- `docs/EXECUTION_SEMANTICS.md`, `docs/SEMANTIC_MODEL.md`, and
  `docs/LANGUAGE_SCOPE.md` document the current statement and scalar-expression
  `while` subset.
- `crates/pine-runtime/src/runtime/statements.rs` hosts the shared executable
  loop implementation for statement and expression `while`.

Do not widen `while` expression variants beyond this scalar subset until a
runtime slice implements the behavior and updates fixtures, conformance,
snapshots, and docs together.

## Target Shape

The first positive subset should mirror existing `for` expression result rules
where possible:

```pine
value = while bar_index < 10
    next = close + 1
    next
```

Target properties:

- condition evaluation follows statement `while`: `true` executes, `false` or
  `na` exits;
- the condition is evaluated before each iteration;
- the body uses the same loop-local scope discipline as statement `while`;
- the expression result is the latest reached final expression statement in the
  loop body;
- if no iteration reaches the final expression, the result is `na`;
- `break` exits the nearest enclosing loop and preserves the latest produced
  loop result;
- `continue` skips the rest of the current body and re-evaluates the condition;
- the existing runtime iteration guard applies unchanged.

Existing statement-form `while` behavior must remain unchanged.

## Parser Policy

Current parser policy:

- accept `while` in expression position only when followed by a condition,
  newline, and an indented body;
- preserve a distinct AST shape or explicit expression flag instead of lowering
  expression loops through statement-only syntax;
- keep condition and body spans precise for diagnostics;
- require at least one body statement;
- allow semantic analysis to own unsupported body-shape diagnostics.

## Semantic Policy

Current semantic policy:

- the condition must type-check as `bool`, matching statement `while`;
- the body must have a final result-producing expression statement for the first
  positive subset;
- declarations inside the body are loop-local and do not leak after the
  expression;
- `var` declarations inside the body follow existing declaration-site
  persistence rules and initialize only when reached;
- type unification uses the produced body expression type and `na` for the
  zero-produced-result path;
- `break` and `continue` target the nearest enclosing loop, which may be the
  `while` expression itself.

Reject body shapes that do not produce a value until they have explicit
semantics and fixtures, including bodies ending in declarations, reassignment,
drawing, strategy, alert, or other side-effect statements.

## Runtime Policy

Current runtime policy:

- evaluate the condition before each iteration;
- exit on `false` or `na`;
- execute statements in loop-local runtime scope;
- update the expression result whenever the final expression statement is
  reached;
- return `na` if the loop never produces a result;
- propagate existing loop-control signals correctly through nested loops;
- advance stateful built-in callsites only when their statements execute;
- preserve the existing deterministic iteration guard.

Realtime rollback follows existing state rollback rules because while
expressions introduce no new storage family by themselves.

## Deferred Variants

Keep these out of the first positive subset:

- bodies without a final result expression;
- imported UDT identity interactions beyond the same-imported-identity
  while-expression subset;
- nested collection semantics beyond the fixture-backed scalar-array and
  matrix result read/mutation subsets, including fresh results and
  existing-collection alias returns. Nested-array results are fixture-backed
  rejected;
- any host-visible output change.

## Slice Order

Recommended future slices:

1. Done: AST shape represents `while` expressions distinctly.
2. Done internally: HIR shape carries result metadata and runtime can execute
   manually constructed expression loops.
3. Done: first positive source subset for `while` expressions returning scalar values,
   including fixture-backed syntax acceptance, zero-iteration `na`, and
   break/continue behavior.
4. Done: stateful callsites, branch-local declarations, `var` declaration
   sites, and nested loop-control propagation stress fixtures.
5. Partly done: tuple, same-local UDT, same-imported-identity UDT,
   scalar-array, and matrix result read/mutation fixtures, including
   fresh collection results, existing-collection alias returns, and array/matrix
   result `continue`/`break` preservation. Nested array result rejection,
   array/matrix zero-iteration `na` results, and committed history reads from
   array/matrix while-expression results are fixture-backed. Remaining positive work:
   broader nested collection interaction semantics only after scalar, tuple,
   local UDT, imported UDT, scalar-array, and matrix result behavior is stable.
