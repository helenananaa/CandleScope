# Pure Internal For-In Iteration Design Gate

Status: closed design gate; statement-form `array<int>`, `array<float>`,
`array<bool>`, `array<string>`, `array<color>`, `array<label>`, `array<line>`,
`array<linefill>`, `array<polyline>`, `array<box>`, `array<table>`,
`array<chart.point>`, and same-local scalar-tree UDT array runtime subsets plus
the `array<int>` mutation-policy fixture slice and ordinary `var` scalar-array
realtime rollback fixture plus scalar typed-array `varip` interaction fixture
implemented, plus statement-form matrix row iteration and expression-form
scalar-array, drawing-id-array, chart.point-array, and same-local scalar-field
UDT-array plus matrix-row iteration with optional expression-form index locals
while broader `for...in` iteration remains unsupported.

This document defines the internal path for future `for...in` iteration over
arrays and later collection families. It is scoped to interpreter internals only:
parser shape, semantic analysis, HIR lowering, runtime execution, collection
aliasing, history, rollback, and conformance. It does not cover host UI,
rendering, external data, public serialization, or any new host contract.

## Current Boundary

`for...in` iteration currently supports statement-form loops over
`array<int>`, `array<float>`, `array<bool>`, `array<string>`, `array<color>`,
`array<label>`, `array<line>`, `array<linefill>`, `array<polyline>`,
`array<box>`, `array<table>`, `array<chart.point>`, and same-local scalar-field
UDT array values, statement-form loops over runtime-owned matrix row snapshots,
and expression-form `for value in values` over `array<int>`, `array<float>`,
and `array<bool>` values.

Current evidence:

- `docs/PURE_INTERNAL_ROADMAP.md` lists `for...in` array iteration as remaining
  language/control-flow and collection work.
- `docs/ARRAY_STAGE_AUDIT.md` records that `for...in` array iteration is not
  part of the current loop subset.
- `crates/pine-syntax/src/parser.rs` parses range loops as
  `for counter = from to to [by step]` and has a distinct statement-form
  `for value in iterable` AST shape.
- `crates/pine-syntax/src/ast.rs` has `For` statement and expression nodes for
  range loops, plus a `ForIn` statement node for the unsupported iteration
  boundary.
- `crates/pine-ir/src/lib.rs` has distinct range-loop and statement-form
  `for...in` HIR nodes.
- `crates/pine-runtime/src/runtime/statements.rs` executes range loops against
  integer bounds and executes the first `array<int>`, `array<float>`,
  `array<bool>`, `array<string>`, `array<color>`, `array<label>`,
  `array<line>`, `array<linefill>`, `array<polyline>`, `array<box>`,
  `array<table>`, `array<chart.point>`, and same-local scalar-tree UDT array
  `for...in` subsets with initial-length iteration.
- `tests/fixtures/runtime/for_in.pine` records the current positive
  statement-form `for value in values` `array<int>` subset.
- `tests/fixtures/runtime/for_in_float.pine` records the current positive
  statement-form `for value in values` `array<float>` subset.
- `tests/fixtures/runtime/for_in_bool.pine` records the current positive
  statement-form `for value in values` `array<bool>` subset.
- `tests/fixtures/runtime/for_in_string.pine` records the current positive
  statement-form `for value in values` `array<string>` subset.
- `tests/fixtures/runtime/for_in_color.pine` records the current positive
  statement-form `for value in values` `array<color>` subset.
- `tests/fixtures/runtime/for_in_label.pine` records label-array shallow-id loop
  variables with getter/setter calls and setter mutations visible through the
  source array id.
- `tests/fixtures/runtime/for_in_line.pine` records line-array shallow-id loop
  variables with getter/setter calls and setter mutations visible through the
  source array id.
- `tests/fixtures/runtime/for_in_linefill.pine` records linefill-array
  shallow-id loop variables with getter/setter calls and setter mutations visible
  through the source array id.
- `tests/fixtures/runtime/for_in_polyline.pine` records polyline-array
  shallow-id loop variables with deletion and `polyline.all` visibility for the
  source array ids.
- `tests/fixtures/runtime/for_in_box.pine` records box-array shallow-id loop
  variables with setter calls, deletion, and `box.all` visibility for the
  source array ids.
- `tests/fixtures/runtime/for_in_table.pine` records table-array shallow-id
  loop variables with cell writes, deletion, and `table.all` visibility for the
  source array ids.
- `tests/fixtures/runtime/for_in_chart_point.pine` records chart.point array
  value-copy loop variables with field reads and local field mutation that does
  not write back to the source array slot.
- `tests/fixtures/runtime/for_in_udt.pine` records same-local scalar-tree UDT
  array value-copy loop variables with field reads and local field mutation that
  does not write back to the source array slot.
- `tests/fixtures/runtime/for_in_control_flow.pine` records direct `break`,
  `continue`, and loop-body local declaration behavior for scalar-array
  statement-form `for...in`.
- `tests/fixtures/runtime/for_in_stateful.pine` records stateful built-in
  callsite advancement from a scalar-array statement-form `for...in` loop body.
- `tests/fixtures/runtime/for_in_mutation.pine` records the current
  initial-length/current-storage mutation policy for `array<int>` loops.
- `tests/fixtures/runtime/for_in_zero_iteration.pine` records zero-iteration
  behavior for empty scalar arrays and typed `na` scalar-array iterables.
- `crates/pine-runtime/tests/incremental.rs` records explicit
  incremental-vs-historical parity for the current scalar-array `for...in`
  runtime fixtures.
- `tests/fixtures/realtime/for_in_rollback.pine` records ordinary `var`
  scalar-array loop-body mutation rollback across repeated forming realtime
  updates and historical parity for the confirmed result.
- `tests/fixtures/realtime/for_in_varip.pine` records scalar typed-array
  `varip` loop-body mutation retention across repeated forming realtime updates
  while preserving the initial-length iteration policy for each execution.
- `tests/fixtures/regressions/for_in_pop_shrink_bounds.pine` and
  `tests/fixtures/regressions/for_in_clear_shrink_bounds.pine` keep
  shrink-to-out-of-bounds iteration aligned with `array.get` runtime errors.
- `tests/fixtures/sema/unsupported_for_in.pine` keeps remaining unsupported
  iterable families rejected.
- `tests/fixtures/runtime/map_for_in.pine` records statement and expression
  direct scalar-map iteration where a single loop variable receives the key and
  `[key, value]` receives the key and value in insertion order.
- `tests/fixtures/runtime/matrix_for_in.pine` covers statement-form
  `for...in` over runtime-owned matrix row snapshots, including the narrow
  index/value form.
- `tests/fixtures/runtime/for_in_expression.pine` covers expression-form
  `for value in values` over `array<int>`, `array<float>`, `array<bool>`, and
  `array<string>`, and `array<color>`, including last-result, zero-iteration,
  typed-`na`, `break`, and `continue` behavior.
- `tests/fixtures/sema/supported_for_in_expression.pine` records the accepted
  semantic subset for expression-form `array<int>` iteration.
- `tests/fixtures/sema/supported_for_in_expression_float.pine` records the
  accepted semantic subset for expression-form `array<float>` iteration.
- `tests/fixtures/sema/supported_for_in_expression_bool.pine` records the
  accepted semantic subset for expression-form `array<bool>` iteration.
- `tests/fixtures/sema/supported_for_in_expression_string.pine` records the
  accepted semantic subset for expression-form `array<string>` iteration.
- `tests/fixtures/sema/supported_for_in_expression_color.pine` records the
  accepted semantic subset for expression-form `array<color>` iteration.
- `tests/fixtures/sema/supported_for_in_expression_label.pine` records the
  accepted semantic subset for expression-form `array<label>` iteration.
- `tests/fixtures/sema/supported_for_in_expression_line.pine` records the
  accepted semantic subset for expression-form `array<line>` iteration.
- `tests/fixtures/sema/supported_for_in_expression_linefill.pine` records the
  accepted semantic subset for expression-form `array<linefill>` iteration.
- `tests/fixtures/sema/supported_for_in_expression_polyline.pine` records the
  accepted semantic subset for expression-form `array<polyline>` iteration.
- `tests/fixtures/sema/supported_for_in_expression_box.pine` records the
  accepted semantic subset for expression-form `array<box>` iteration.
- `tests/fixtures/sema/supported_for_in_expression_table.pine` records the
  accepted semantic subset for expression-form `array<table>` iteration.
- `tests/fixtures/sema/supported_for_in_expression_chart_point.pine` records
  the accepted semantic subset for expression-form `array<chart.point>`
  iteration.
- `tests/fixtures/sema/supported_for_in_expression_udt.pine` records the
  accepted semantic subset for expression-form same-local scalar-tree UDT array
  iteration.
- `tests/fixtures/sema/supported_for_in_expression_matrix.pine` records the
  accepted semantic subset for expression-form runtime-owned matrix row
  iteration.
- `tests/fixtures/sema/unsupported_for_in_expression_non_array.pine` keeps
  expression-form non-collection iteration rejected before runtime.
- `tests/fixtures/sema/unsupported_for_in_non_array.pine` keeps non-array
  iterables rejected before runtime.
- `tests/fixtures/syntax/for_in_index_value.pine` records the accepted narrow
  index/value spelling. `tests/fixtures/syntax/unsupported_for_in_index_value.pine`
  keeps multi-value destructuring rejected. The expression-form
  `tests/fixtures/syntax/for_in_expression_index_value.pine` records the
  accepted optional index/value result syntax.

Do not widen beyond the current scalar-array, label array, line array, linefill
array, polyline array, box array, table array, chart.point array, same-local
scalar-tree UDT array, runtime-owned matrix row, and expression-form
scalar-array, drawing-id-array, chart.point-array, and same-local scalar-field
UDT-array plus matrix-row subset until a runtime slice implements the behavior
and updates fixtures, conformance, snapshots, and docs together.

## Target Shape

The first positive `for...in` subset should be a collection iteration feature,
not syntactic sugar for an integer range loop.

Target properties:

- parser distinguishes range loops from collection iteration loops;
- semantic analysis resolves the iterable expression to one supported collection
  element kind;
- the loop value variable has the element type of the collection;
- the loop body follows existing block scoping and loop-control rules;
- `break` and `continue` behave exactly as they do for range and while loops;
- statement-form loops and expression-form loops are designed separately;
- mutation of the iterated collection during iteration has explicit behavior;
- runtime execution is deterministic across historical, incremental, and
  realtime forming-bar paths.

The first positive subset was array-only. Matrix row iteration is now supported
for runtime-owned matrices by snapshotting rows at loop entry. Map iteration
must still wait for its key/value storage model and iteration order policy.

## Syntax Policy

Candidate first syntax:

```pine
for value in values
    body
```

Candidate later syntax:

```pine
for index, value in values
    body
```

Initial parser policy:

- accept one loop value variable for the baseline statement-form slice;
- accept the narrow `for index, value in values` statement form for
  `array<int>`, `array<float>`, `array<bool>`, `array<string>`,
  `array<color>`, `array<label>`, `array<line>`, `array<linefill>`,
  `array<polyline>`, `array<box>`, `array<table>`, `array<chart.point>`, and
  same-local or same-imported scalar-tree UDT arrays only;
- require a newline after the iterable expression;
- reuse the existing indented-block parser for the body;
- preserve spans for the loop variable, iterable expression, and body;
- keep range-loop parsing unchanged;
- reject tuple/multi-value destructuring beyond the supported index/value form;
- reject map iteration syntax until that collection design is implemented.

Expression-form `for...in` should remain unsupported in the first positive
syntax slice unless result semantics are designed at the same time.

## Element Type Policy

First positive iterable families:

- `array<int>`
- `array<float>`
- `array<bool>`
- `array<string>`
- `array<color>`
- `array<label>`
- `array<line>`
- `array<linefill>`
- `array<polyline>`
- `array<box>`
- `array<table>`
- `array<chart.point>`

Deferred iterable families:

- typed imported or non-scalar-tree UDT arrays;
- map keys, values, or entries;
- matrix rows, columns, or cells;
- nested collections;
- tuples;
- strategy/order/trade records.

Rationale:

- label, line, linefill, polyline, box, and table ids use the existing shallow
  object-id storage and mutation semantics;
- broader UDT values need copy/mutation policy for structured values;
- scalar map iteration now uses insertion order, with key-only and key/value
  loop-variable binding rules;
- matrix iteration needs row/column traversal semantics.

## Runtime Iteration Policy

Initial policy:

- evaluate the iterable expression once before the loop starts;
- if the iterable evaluates to `na`, execute zero iterations;
- snapshot the array length before the loop starts;
- iterate zero-based from index `0` to `initial_len - 1`;
- read each element from the current array storage at that index when the
  iteration reaches it;
- if the array shrinks so a future index is out of bounds, raise the same runtime
  error policy chosen for invalid `array.get`;
- if the array grows during iteration, do not visit new elements in the current
  loop;
- assign the loop variable by value for scalar, supported drawing id, and supported
  structured elements;
- preserve normal side effects from statements inside the body.

This policy intentionally allows mutation to affect not-yet-visited existing
indexes while preventing unbounded loops caused by appends. If a later slice
chooses a full element snapshot instead, it must document copy cost and aliasing
behavior explicitly.

## Scoping And Assignment

Initial policy:

- the loop value variable is block-local to the loop body;
- it may shadow outer symbols using existing loop-counter shadowing rules;
- assigning to the loop value variable does not write back into the source array;
- writing back requires explicit `array.set` with an index, which is deferred
  until index iteration is supported or the script tracks its own index;
- `var` and `varip` declarations inside the loop body follow existing
  declaration-site persistence rules;
- stateful built-in calls inside the loop body use the same callsite semantics as
  range loops.

For accepted index/value iteration, the index variable is an int local whose
value is the zero-based visited index. It is not a reference into collection
storage.

## Mutation And Aliasing

First supported-array policy:

- assigning the array id to another variable before iteration preserves reference
  semantics as today;
- mutating through any alias mutates the same backing store;
- the loop's initial length is taken from the evaluated array id;
- `array.copy` before iteration creates an independent iteration source;
- scalar, supported drawing id, chart.point, and same-local scalar-tree UDT element
  variables are copied values and have no alias to array slots;
- label, line, linefill, polyline, box, and table element variables are
  shallow-copied ids, so drawing setters or lifecycle operations mutate the
  target object while assignment to the loop local does not write the source
  array slot.

Deferred policies:

- typed imported or non-scalar-tree UDT arrays need the broader UDT array
  design gate rules;
- nested collections need deep-copy or id-reference policy before iteration.

## History And Realtime

First history policy:

- no new history families are introduced by `for...in` support alone;
- iterating over an array history snapshot should remain unsupported until
  historical collection values and copy cost are explicit for that element kind;
- ordinary `var` arrays still roll back to confirmed backing storage before a
  forming-bar re-execution, including loop-body mutation in the current
  scalar-array `for...in` subset;
- scalar typed-array `varip` backing storage preserves existing intrabar
  behavior when iterated by the current scalar-array `for...in` subset, including
  loop-body mutation retention across repeated forming updates.

Realtime fixtures are required for any positive support because mutation during
iteration can interact with rollback and aliasing.

## Diagnostics

Before positive support lands, unsupported `for...in` forms should keep failing
at parse or semantic analysis.

When support starts, unsupported variants should fail with precise diagnostics:

- unsupported `for...in` syntax;
- iterable expression is not a supported collection;
- unsupported array element kind;
- tuple/multi-value destructuring beyond the supported index/value form;
- map iteration before storage and order rules exist;
- expression-form `for...in` beyond the fixture-backed scalar-array,
  drawing-id-array, chart.point-array, same-local scalar-tree UDT-array, and
  matrix-row subset;
- mutation pattern that violates the selected iteration policy.

## Slice Order

Recommended future slices:

1. Parser AST shape: add distinct statement-form `for...in` AST while keeping it
   rejected by semantic analysis. Done.
2. HIR shape: add a distinct HIR node and lowering path for statement-form
   array iteration, still without runtime execution. Done.
3. First positive scalar array subset: iterate read-only over int arrays with no
   source mutation inside the loop. Done.
4. Mutation policy fixtures: cover push/pop/set/clear interactions with the
   selected initial-length/current-storage policy. Done.
5. Additional scalar element kinds: `array<float>`, `array<bool>`,
   `array<string>`, and `array<color>` are done.
6. Direct `break`/`continue` and loop-body local declaration fixture. Done.
7. Stateful built-in callsite fixture. Done.
8. Zero-iteration empty-array and typed-`na` iterable fixture. Done.
9. Ordinary `var` scalar-array realtime rollback fixture. Done.
10. Scalar typed-array `varip` interaction fixture. Done.
11. Incremental parity fixtures. Done.
12. Optional index/value iteration over `array<int>`, `array<float>`,
    `array<bool>`, `array<string>`, `array<color>`, `array<label>`,
    `array<line>`, `array<linefill>`, `array<polyline>`, `array<box>`,
    `array<table>`, `array<chart.point>`, and same-local plus same-imported
    scalar-tree UDT arrays are done.
13. Statement-form iteration over runtime-owned matrix rows is done, including
    index/value row numbers and loop-entry row snapshots.
14. Expression-form `for value in values` over scalar arrays, drawing-id
    arrays, chart.point arrays, same-local scalar-tree UDT arrays, and
    runtime-owned matrix rows is done, including last-result, zero-iteration,
    typed-`na`, `break`, and `continue` behavior.
15. Index/value iteration over typed imported or non-scalar-tree UDT arrays and
    map iteration only after their specific design gates and storage rules are
    implemented.

## Completion Gate For Future Positive Support

Any positive `for...in` support must include:

- parser fixtures for accepted and rejected syntax;
- semantic fixtures for supported and unsupported iterable types;
- runtime fixtures for empty arrays, `na` iterables, normal iteration, `break`,
  `continue`, local declarations, stateful calls, and mutation interactions;
- realtime rollback tests when the iterated collection can persist or mutate;
- incremental-vs-historical parity tests;
- synchronized `tests/fixtures/conformance.tsv`, `docs/CONFORMANCE.md`,
  `docs/SEMANTIC_MODEL.md`, matrix snapshot, release notes, and this design
  document;
- `git diff --check`;
- `scripts/verify.sh`.

## Closed Slice Result

This design gate closes the planning prerequisite, the first positive
`array<int>`, `array<float>`, `array<bool>`, `array<string>`, `array<color>`,
`array<label>`, `array<line>`, `array<linefill>`, `array<polyline>`,
`array<box>`, `array<table>`, `array<chart.point>`, and same-local
scalar-tree UDT statement-form slices, the `array<int>`, `array<float>`,
`array<bool>`, and
`array<string>`, `array<color>`, `array<label>`, `array<line>`,
`array<linefill>`, `array<polyline>`, `array<box>`, `array<table>`,
`array<chart.point>`, and same-local scalar-tree UDT array index/value
statement-form slices, the `array<int>` mutation-policy fixture slice, the
direct `break`/`continue` and loop-body local declaration fixture
slice, the stateful built-in callsite fixture slice, the zero-iteration
empty-array and typed-`na` iterable fixture
slice, the ordinary `var` scalar-array realtime rollback fixture slice, and the
scalar typed-array `varip` interaction fixture slice, plus explicit
incremental-vs-historical parity coverage for the scalar-array runtime fixtures,
and the runtime-owned matrix row statement-form slice with optional row indexes
and loop-entry row snapshots, plus the expression-form scalar-array,
drawing-id-array, chart.point-array, and same-local scalar-tree UDT-array
plus matrix-row slice with last-result, zero-iteration, typed-`na`, `break`,
`continue`, and optional index-local fixtures. Broader `for...in` iteration
remains unsupported until later slices implement fixture-backed analysis,
runtime behavior, and conformance updates together.
