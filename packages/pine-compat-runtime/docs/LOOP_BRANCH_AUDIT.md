# Loop and Branch Audit

This document records the Phase A boundary from
`docs/LONG_TERM_EXECUTION_PLAN.md`. Phase A is complete for the current
fixture-backed executable subset: `if`, `switch`, `for`, and `while` now have
explicit runtime fixtures, incremental append coverage, and documented
compatibility boundaries.

## Current Supported Subset

Branches:

- `if` and `else` statement blocks execute conditionally.
- Branch-local normal and tuple declarations do not leak outside the branch.
- Stateful callsites inside branches advance only when their branch executes.
- Skipped branch-local series slots commit `na` for that bar.

Switch expressions:

- Selector-less condition arms are supported.
- Selector/case arms are supported.
- Default arms are supported.
- Expression arms and result-producing statement-block arms are supported.
- Stateful callsites inside switch arms advance only when the selected arm
  executes.
- A switch with no matching arm and no default returns `na`.
- Imported UDT constructor results from statement-block arms are fixture-backed
  rejected.

For loops:

- Inclusive integer ranges are supported.
- The loop direction is derived from `start <= end` or `start > end`.
- Explicit `by step` values provide an absolute non-zero integer step
  magnitude; the sign does not override range direction.
- Runtime `na` for `start`, `end`, or `step` skips the loop body.
- `break` and `continue` target the nearest enclosing loop.
- Loop counters are scoped to the loop body.
- Nested loops and loop counter shadowing are supported.
- Statement loops and expression-result loops are supported.
- Tuple assignment from a `for` expression result is supported.
- Stateful callsites inside `for` bodies advance once per executed iteration.

While loops:

- Statement-form `while condition` loops and scalar `while` expression results
  are supported.
- Conditions must type-check as bool.
- Runtime `na` conditions exit the loop like false.
- `break` and `continue` target the nearest enclosing loop.
- Nested loops, local declarations, local `var`, and stateful callsites inside
  loop bodies are supported.
- Scalar `while` expressions return the latest reached final body expression or
  `na`, with fixture-backed stateful callsite advancement and loop-local
  declaration no-leak behavior.
- `break` and `continue` inside a while-expression body are contained by the
  nearest while expression when evaluated inside an outer loop.
- Tuple declaration/destructuring from while-expression results is covered.
- Same-local UDT constructor or block-local alias results from while
  expressions are covered.
- Fresh or existing-alias scalar-array results with caller-side reads and
  mutation from while expressions are covered.
- Nested-array results from while expressions are fixture-backed rejected.
- Imported UDT constructor results from while expressions are fixture-backed
  rejected.
- A deterministic runtime iteration guard rejects non-terminating loops.

Branch and loop interactions:

- `if` inside loops is covered.
- Loops inside `if` branches are covered.
- `switch` inside loops is covered.
- Loops inside user-defined function block bodies are covered.
- Stateful TA callsites inside loops nested in UDF block bodies are covered.

## Current Rejections

- `break` and `continue` outside loops are rejected.
- Non-int `for` range bounds are rejected.
- Non-int `for` steps are rejected.
- Literal zero `for` steps are rejected by semantic analysis; runtime zero
  steps also fail defensively.
- `for` expression bodies must end with an expression.
- `while` expressions are rejected until expression-result semantics are
  designed.
- Non-bool `while` conditions are rejected.
- Statement-block `switch` arms are rejected until block-arm scoping and result
  semantics are designed.
- Switch arms with incompatible result types are rejected.

## Fixture Coverage

Runtime fixtures:

- `tests/fixtures/runtime/block_statements.pine`
- `tests/fixtures/runtime/branch_loop_interactions.pine`
- `tests/fixtures/runtime/for_edges.pine`
- `tests/fixtures/runtime/for_stateful.pine`
- `tests/fixtures/runtime/local_scope.pine`
- `tests/fixtures/runtime/loop_state_interactions.pine`
- `tests/fixtures/runtime/switch.pine`
- `tests/fixtures/runtime/while.pine`
- `tests/fixtures/runtime/while_edges.pine`
- `tests/fixtures/runtime/while_stateful.pine`

Semantic fixtures and tests cover supported block statements plus rejected loop
control, malformed `for` loops, malformed `while` loops, and unsupported switch
arm forms.

All runtime fixtures are included in the incremental append consistency test,
which compares append execution with full historical recomputation.

## Phase A Closeout

Completed:

- Hardened `for` edge cases for dynamic and `na` bounds, signed step
  magnitudes, nested loop control, loop counter shadowing, expression results,
  tuple results, and stateful callsites in loop bodies.
- Hardened `while` edge cases for `na` conditions, nested control, local
  declarations, local `var`, stateful callsites, and the runtime guard.
- Covered branch interactions across `if`, `switch`, loops, and UDF block
  bodies.
- Added a representative loop/state fixture covering `if`, `switch`, `for`,
  `while`, `break`/`continue`, UDF block bodies, and stateful TA callsites in
  one runtime path.
- Preserved diagnostics for unsupported loop and switch forms.
- Documented the supported compatibility boundary in
  `docs/LANGUAGE_SCOPE.md`, `docs/EXECUTION_SEMANTICS.md`, and
  `tests/fixtures/conformance.tsv`.

Deferred:

- `while` expression results.
- Statement-block `switch` arms.
- Additional real-indicator fixtures if future scripts expose uncovered loop or
  branch patterns.

## Acceptance Criteria For Expanding Loop Support

- Add or update fixtures before expanding the accepted syntax or runtime
  behavior.
- Keep unsupported variants diagnostic-only until their scoping and result
  semantics are designed.
- Ensure incremental append execution matches full historical execution for new
  loop fixtures.
- Update `tests/fixtures/conformance.tsv` only after fixture coverage exists.
