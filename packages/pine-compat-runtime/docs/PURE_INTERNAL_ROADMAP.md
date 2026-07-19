# Pure Internal Roadmap

Status: planning document.

This document tracks interpreter-internal work only. It is intentionally narrower
than `docs/LONG_TERM_EXECUTION_PLAN.md` and `docs/NEXT_INTERNAL_CAPABILITY_PLAN.md`.
It does not claim new compatibility. A feature becomes supported only after the
matching syntax, semantic analysis, runtime behavior, fixtures, conformance
metadata, snapshots, documentation, and release verification are complete.

## Scope Boundary

In scope:

- parser, AST, semantic analysis, type and qualifier checks;
- HIR/runtime execution semantics;
- series history, persistence, realtime rollback, and deterministic guards;
- pure built-in functions and constants that do not require host services;
- internal collection storage models;
- local and imported user-defined type semantics;
- strategy broker emulation, account math, and script-visible strategy variables;
- conformance metadata, snapshots, runtime profiles, and structural guardrails.

Out of scope for this roadmap:

- chart rendering, visual layout, drag behavior, or host UI;
- external market-data lookup, symbol discovery, or remote request execution;
- webhook, email, push, or other external alert delivery;
- real broker connectivity or live trading adapters;
- hosted dashboards, notebooks, application integrations, or product UI;
- widening public JSON, Python, or WASM host contracts unless a slice explicitly
  designs that contract as part of an interpreter behavior change.

`request.*`, drawing objects, and alert delivery are therefore not roadmap drivers
here. Their existing docs still matter for current behavior, but new work in
those areas should stay outside this pure-internal plan unless the slice is
strictly about analyzer/runtime semantics with no host-service dependency.

## Source Of Truth

Use these files before selecting a slice:

- `tests/fixtures/conformance.tsv`
- `tests/snapshots/matrix.json`
- `docs/CONFORMANCE.md`
- `docs/EXECUTION_SEMANTICS.md`
- `docs/SEMANTIC_MODEL.md`
- `docs/HISTORY_SERIES_AUDIT.md`
- `docs/QUALIFIER_AUDIT.md`
- `docs/ARRAY_STAGE_AUDIT.md`
- `docs/STRATEGY_INTERNAL_GAP_AUDIT.md`
- latest relevant phase or stage audit

Roadmap text is not support evidence. If a roadmap and the current matrix
disagree, trust the matrix, snapshots, fixtures, and latest audit first.

## Execution Rules

- Work one small slice at a time.
- Start every slice by rechecking conformance, matrix output, current docs, and
  the relevant runtime/analyzer modules.
- Keep unsupported variants rejected with stable diagnostics until their behavior
  is deliberately designed.
- Prefer one behavior through the full stack over several parser-only changes.
- Avoid accepting no-op syntax for future compatibility claims.
- Preserve public output shape unless the slice explicitly designs a schema
  change.
- Update `tests/fixtures/conformance.tsv` only after fixture-backed behavior
  exists.
- Close every behavior slice with `git diff --check` and `scripts/verify.sh`.

## Current Baseline

The interpreter already has a broad fixture-backed subset:

- historical and incremental bar execution;
- realtime forming-bar rollback for supported runtime state;
- `if`/`else`, partial `switch`, partial `for`, and partial `while`;
- user-defined functions with local declarations and independent callsite state;
- guarded integer history offsets, including `series int`;
- partial typed arrays and array history snapshots for supported element
  families;
- local scalar-field user-defined types and pure local methods;
- many pure `ta.*`, `math.*`, `str.*`, time, timeframe, session, color, and
  symbol helpers;
- long-only strategy runtime with a fixture-backed Stage 13 multi-entry ledger
  and `pyramiding` subset.

The remaining work is mostly about closing large semantic families, not creating
the first executable runtime.

## Direction 1: Language And Control Flow

Goal: make ordinary Pine control-flow and expression behavior more complete while
preserving deterministic execution and diagnostics.

Current baseline:

- `if`/`else` blocks and scalar `if` expressions are fixture-backed.
- `switch` supports expression arms plus fixture-backed expression
  statement-block arms whose block ends in a result expression, including
  selected-arm outer reassignment, branch-local no-leak fixtures, and
  loop-control propagation from selected arms inside loop bodies, plus tuple
  declaration/destructuring results, same-local UDT results from selected block
  arms, same-imported-identity UDT results from selected block arms, and
  message-level diagnostics for no-final-expression expression block arms.
  Statement-context `switch` block arms also execute selected condition,
  selector, and default arms for side effects, outer reassignment, and loop
  control without requiring dummy result expressions.
- `for` and `while` loops support statement execution, expression loops where
  currently claimed, local declarations, loop control, stateful callsite
  interaction fixtures, statement-form `for...in` over supported array element
  families including the narrow `array<int>`/`array<float>`/`array<bool>`/
  `array<string>`/`array<color>`/`array<label>`/`array<line>`/
  `array<linefill>`/`array<polyline>`/`array<box>`/`array<table>`/
  `array<chart.point>`/same-local scalar-tree UDT array index/value form, and
  `while` statement-body history-read/pure-UDF interaction fixtures, with
  fixture-backed diagnostics for loop control used outside loops.
- Scalar, tuple, same-local UDT, scalar-array, and `matrix<float>` `while`
  expression results with caller-side reads and mutation are fixture-backed
  through parser, semantic analysis, HIR lowering, and runtime execution. The
  collection subsets cover fresh results, existing-alias returns, scalar-array
  history reads returning fresh historical copies, and array/matrix
  zero-iteration `na` results, including array/matrix result preservation across
  `continue` and `break`, plus committed matrix history reads that return fresh
  historical copies. They return the latest reached final body
  expression or `na` when no iteration produces a value, and share
  statement-loop condition, break/continue, scoping, and iteration-guard rules.
  Same-imported-identity UDT results are supported, while nested-array results
  through `while` expressions remain rejected with fixture-backed semantic
  diagnostics.

Remaining internal work:

- broader positive `while` expression nested collection interaction semantics;
- broader `for...in` index/value element families and collection iteration;
- better diagnostics for remaining unsupported expression-context switch forms;
- additional stress fixtures for nested control flow and stateful built-ins.

Non-goals:

- host-driven scheduling;
- visual outputs as a reason to widen language semantics;
- unbounded recursion or execution that can bypass runtime guardrails.

Good next slice:

- one unsupported control-flow form should first get a design note and negative
  fixtures, then one narrow positive fixture-backed subset.

The statement-block `switch` arm design gate is closed in
`docs/PURE_INTERNAL_SWITCH_BLOCK_DESIGN.md`, and its scalar expression-arm block
subsets are implemented. The `while` expression design gate is closed in
`docs/PURE_INTERNAL_WHILE_EXPRESSION_DESIGN.md`. Use those documents before
widening broader `switch` block result variants or `while` expression support.

## Direction 2: Type, Qualifier, And History Semantics

Goal: make the static model closer to Pine without weakening runtime safety.

Current baseline:

- qualifiers use the current `const < input < simple < series` model;
- explicit scalar typed declarations preserve non-`na` initializer qualifiers,
  while explicit scalar typed declarations initialized with `na` can take the
  qualifier from a later compatible scalar reassignment;
- const-condition ternary, if-expression, condition-form switch, const-key
  selector-form switch, final-if UDF returns, and their tuple-destructuring
  forms preserve the selected branch qualifier for literal, named, or
  numeric/bool/string/color equality-derived const conditions and const
  bool/int/string/color selector keys while still checking branch kind
  compatibility;
- scalar `simple` inference preserves the fixture-backed typed-declaration,
  reassignment, UDF/method argument, tuple, and statically selected
  ternary/if/switch paths, including numeric, string, color, and bool const
  comparisons without same-named global capture;
- exact and at-most scalar qualifier bounds share one signature/diagnostic rule
  path for the implemented `Simple*`, `Const*`, and `AtMostInput*` families;
- shared scalar constant evaluation recognizes only `int(...)`, `float(...)`,
  `math.min(...)`, `math.max(...)`, `math.abs(...)`, `math.floor(...)`,
  `math.ceil(...)`, and `math.trunc(...)`; those calls feed static branch
  selection, declaration-value validation, constant history offsets, and
  declaration/per-series `max_bars_back` inference;
- history offsets accept non-negative integer literals and guarded dynamic integer
  expressions, including `series int`;
- `ta.pivothigh` and `ta.pivotlow` left/right bar counts accept integer values
  at any implemented qualifier while runtime guards invalid counts to `na`;
- `ta.change` length accepts integer values at any implemented qualifier and
  uses guarded runtime history reads for dynamic lengths;
- `ta.mom` and `ta.roc` length accept integer values at any implemented
  qualifier and use guarded runtime history reads for dynamic lengths;
- `ta.rising` and `ta.falling` length accept integer values at any implemented
  qualifier and compare against retained source history for dynamic lengths;
- `ta.highest`, `ta.lowest`, `ta.highestbars`, and `ta.lowestbars` length
  accept integer values at any implemented qualifier, including length-only
  default-source overloads, and use retained source history for dynamic lengths;
- `ta.valuewhen` occurrence accepts integer values at any implemented qualifier
  and retains per-callsite match state for dynamic occurrence reads;
- static-only scripts use HIR history metadata to trim committed history;
- dynamic-history scripts keep full committed history up to the runtime cap;
- `indicator(..., max_bars_back=N)` and `strategy(..., max_bars_back=N)` with
  supported non-negative constant integer expressions, including pure
  UDF-returned and imported exported-UDF-returned constant length values, plus
  fixture-backed top-level, block expression-statement,
  `for`/`for...in`/`while` statement-body, statement-context switch block-arm,
  switch expression block-arm, tuple-destructured switch expression block-arm,
  if-expression block branch, tuple-destructured if-expression block branch,
  call-argument block expression / block-result /
  `for`/`for...in`/`while` loop-result nested expression
  `max_bars_back(source, N)` helper calls bound dynamic retention when `N` is a
  supported non-negative constant integer expression, including pure
  UDF-returned and imported exported-UDF-returned constant length values, for
  built-in, derived, alias-chain, or direct expression series numeric sources,
  including stable pure
  unary/binary/ternary plus pure `if`/`switch`/`for`/`while` expression identity
  reuse and pure `for...in` over inline `array.from(...)` identity reuse for
  matching history reads,
  builtin qualified constants/simple metadata, bar/session flags, positional and
  fixed-arity named stateless pure math calls, fixed-arity pure `nz`/`fixnan`
  value-helper calls, pure string numeric-source calls including `str.tonumber`
  and `str.length`, pure numeric cast calls, stable nested history expressions,
  `str.pos`, `color.r`/`color.g`/`color.b`/`color.t`, and unreassigned pure
  scalar series declaration aliases; identity reuse is disabled across scalar
  reassignments, including inlined UDF/method locals;
- runtime diagnostics and profiles expose dynamic-retention misses and maximum
  missed offsets when dynamic reads exceed the explicit retained bound.

Remaining internal work:

- per-variable `max_bars_back` inference beyond the fixture-backed top-level,
  statement-block, `for`/`for...in`/`while` statement-body,
  statement-context switch block-arm, switch expression
  block-arm, tuple-destructured switch expression block-arm, if-expression
  block branch, tuple-destructured if-expression block branch, and
  value-producing block-expression prefix-statement/call-argument/block-result/
  loop-result helper subset;
- constant evaluation outside the explicit scalar-call whitelist, including
  string/color/collection results and arbitrary pure built-ins, remains
  unsupported rather than being inferred from runtime purity;
- broader first-bar, `na`, UDF, loop, array-history, and built-in interaction
  fixtures.

Non-goals:

- silently accepting non-integer or negative history offsets;
- unbounded history retention;
- changing built-in qualifier acceptance without synchronized docs and fixtures.

Good next slice:

- choose one concrete remaining history/value-expression gap with a negative
  boundary first; do not widen constant-call folding by treating every pure
  runtime built-in as statically evaluable.

## Direction 3: Collections

Goal: extend the fixture-backed array, scalar-map, typed-matrix, and scalar-tree
UDT-array subsets without blurring the remaining collection boundaries.

Current baseline:

- runtime-owned array ids;
- reference assignment and explicit `array.copy` independence;
- supported scalar and existing object-id array element families as recorded in
  conformance;
- many creation, mutation, search, ordering, numeric, slice, concat, and method
  call helpers;
- array history snapshots for the fixture-backed element families;
- scalar-key/scalar-value maps with helper calls, history, rollback, `varip`,
  and direct key-only or key/value `for...in` iteration;
- runtime-owned `matrix<float>`, `matrix<int>`, `matrix<bool>`,
  `matrix<string>`, and `matrix<color>` values with typed declarations,
  two-dimensional reads and mutations, shape/structural helpers, history,
  realtime rollback, `varip`, and row-based `for...in` iteration as recorded in
  conformance;
- same-local and same-imported scalar-tree UDT arrays with fixture-backed
  history, rollback, `varip`, and `for...in` behavior, plus local and imported
  UDT array returns from UDFs and user methods through direct, alias, copy,
  new/from, private nested-call, typed-method, and final-control-flow paths with
  per-call identity. Imported type-position rewrites and source-aware import
  instances isolate calls through two aliases of the same physical library.
  Local UDF/typed-method parameter iteration also preserves call-local value
  identity for statement loops and final scalar, UDT-element, or rebuilt
  UDT-array results. Tuple literals and local/imported UDF or method tuple
  returns preserve same-local or same-imported scalar-tree UDT-array identity
  independently per destructured UDT-array slot, including tuple-valued
  ordinary declaration direct/self alias, control-flow alias,
  later-destructuring, fresh shadowing, typed-`na`, A-to-B-to-A, and dual-alias
  paths. Same-identity or `na` tuple reassignment preserves the fixed slot
  layout; cross-identity direct/control-flow reassignment fails closed.
  Qualified user-defined UDF/method results and unqualified plain local UDF
  results returning any currently supported array kind support direct
  `.size()`/`.get(index)`/`.first()`/`.last()`/`.copy()` and nested copy/read
  chains. The completed built-in array producer slice admits the same five
  postfix helpers for the exact admitted producer set `array.new_float`,
  `array.new_int`, `array.new_bool`, `array.new_string`, `array.new_color`,
  `array.new_line`, `array.new_linefill`, `array.new_polyline`,
  `array.new_label`, `array.new_box`, `array.new_table`,
  `array.new<chart.point>`, supported `array.new<UDT>`, `array.from`,
  `array.copy`, `array.slice`, `array.concat`, `array.abs`,
  `array.standardize`, and `array.sort_indices`,
  plus the existing supported scalar/drawing-id/`chart.point` and concrete
  scalar-tree UDT `array.new<T>` source forms through their canonical or
  checked template paths. The parser uses `$builtin_array_result` for this
  closed path. Only `.copy()` can yield another array receiver for a nested
  allowed read/copy; `.size()`/`.get()`/`.first()`/`.last()` are terminal and
  cannot continue into a user or other call-result method.
  UDT arrays still require one concrete same-local or same-imported scalar-tree
  identity and preserve A-to-B-to-A identity, imported dual-alias isolation,
  named-index binding, empty/typed-`na` behavior, and copy independence.
  Unqualified local UDF results carrying a concrete scalar UDT identity may
  invoke the existing pure user-method subset, but built-in producer element
  reads do not open that composition. The lexical `array` prefix is reserved
  for built-in producer recognition; a user/import qualifier with that spelling
  is not a supported qualified call-result path. A later closed slice adds the
  exact non-`array` producer set `str.split`, `ta.pivot_point_levels`,
  `matrix.row`, `matrix.col`, `matrix.eigenvalues`, `map.keys`, and
  `map.values` to the same `$builtin_array_result` path. They share only the
  same five read/copy helpers, and only `.copy()` may continue a chain.
  Row/column results preserve the element kind of the five supported scalar
  matrix templates, eigenvalues preserve the existing numeric-matrix
  `array<float>` result, and map key/value results preserve insertion order and
  the corresponding five-scalar key/value template kind. All of those results
  keep independent snapshot/copy semantics. Built-in namespace prefixes stay
  reserved. The scalar-only extension adds no UDT/import identity and no public
  schema field. Unsupported templates, non-producer `array.*` members,
  namespaces and members outside the seven fixed producers, and postfix
  mutation fail closed. A following closed slice admits namespace-qualified
  `matrix.mult(...)` through the separate `$builtin_matrix_result` candidate
  path. Matrix-by-array, array-by-matrix, and array-by-array `array<float>`
  results share the existing `.size()`/`.get(index)`/`.first()`/`.last()`/
  `.copy()` set. The next closed slice admits matrix-by-matrix,
  matrix-by-scalar, and scalar-by-matrix `matrix<float>` results through only
  `.rows()`/`.columns()`/`.elements_count()`/`.get(row, column)`/`.copy()`.
  Int inputs still produce float collections, and only `.copy()` may continue
  another allowed read/copy chain on either result kind. Wrong-result helpers,
  invalid arity or argument types, broader helpers, and mutation fail closed.
  The existing bound-receiver `matrix_id.mult(array).size()` path is unchanged,
  while bound or UDF matrix-result call-result helpers remain gated.
  A subsequent closed slice admits exact namespace `matrix.copy(values)` on the
  same `$builtin_matrix_result` path. It always resolves to a matrix through
  `SameAsArg`, preserves the source float/int/bool/string/color matrix element
  kind, and shares only the five matrix read/copy helpers plus copy-only
  continuation. The returned store and nested copies remain independent;
  bound `values.copy()` call-result helpers stay gated.
  A later closed slice admits exact bound matrix-receiver `values.copy()`
  results after confirming the original receiver has a supported matrix kind.
  These results preserve element kind, shape, and independent backing storage,
  and expose only the same five helpers with copy-only continuation. Other
  bound matrix producers and UDF matrix results remain gated.
  A later closed bound-result slice admits exact matrix-receiver
  `values.transpose()` results. It preserves the receiver element kind, swaps
  shape, returns independent storage, and exposes the same five helpers with
  copy-only continuation. Bound `submatrix` and other producers remain gated.
  The following closed bound-result slice admits exact matrix-receiver
  `values.submatrix(...)` results. It preserves element kind, returns an
  independent selected half-open range including default full and valid empty
  ranges, and exposes the same five helpers with copy-only continuation. Bound
  `kron` and other producers remain gated.
  The next closed bound-result slice admits exact numeric matrix-receiver
  `values.kron(other)` results. It expands both dimensions, returns independent
  fixed `matrix<float>` storage, and exposes the same five helpers with
  copy-only continuation. Bound `diff` and other producers remain gated.
  The following closed bound-result slice admits exact numeric matrix-receiver
  `values.diff(other)` results for matrix or scalar operands. It preserves
  left-to-right direction and selected matrix shape, returns independent fixed
  `matrix<float>` storage, and exposes the same five helpers with copy-only
  continuation. Bound `pow` and other producers remain gated.
  The next closed bound-result slice admits exact numeric square matrix-receiver
  `values.pow(power)` results. It preserves square shape across identity, copy,
  and positive powers, returns independent fixed `matrix<float>` storage, and
  exposes the same five helpers with copy-only continuation. Bound `inv` and
  other producers remain gated.
  The following closed bound-result slice admits exact numeric square
  matrix-receiver `values.inv()` results. It preserves invertible square shape,
  returns empty `0 x 0` or `na` at the established boundaries, uses independent
  fixed `matrix<float>` storage, and exposes the same five helpers with
  copy-only continuation. Bound `pinv` and other producers remain gated.
  The next closed bound-result slice admits exact numeric matrix-receiver
  `values.pinv()` results. It swaps rectangular shape, preserves singular
  matrix results and swapped zero-cell shapes, yields `na` for invalid cells,
  uses independent fixed `matrix<float>` storage, and exposes the same five
  helpers with copy-only continuation. Bound `eigenvectors` and other producers
  remain gated.
  The following closed bound-result slice admits exact numeric square
  matrix-receiver `values.eigenvectors()` results. It preserves real square
  shape, returns empty `0 x 0` or `na` at the established boundaries, uses
  independent fixed `matrix<float>` storage, and exposes the same five helpers
  with copy-only continuation. Matrix-valued bound `mult`, UDF matrix results,
  and other producers remain gated.
  The next closed bound-result slice admits exact numeric matrix-receiver
  matrix-valued `values.mult(other)` results for matrix or scalar operands. It
  preserves multiplied or scalar-selected shape, `na` and zero-inner-dimension
  behavior, uses independent fixed `matrix<float>` storage, and exposes the
  same five helpers with copy-only continuation. Array-result overloads retain
  array-helper dispatch, while UDF matrix results remain gated.
  The next closed call-boundary slice admits unqualified local-UDF results that
  infer a concrete supported matrix kind through `$call_result`. Parameter
  passthrough, block aliases, nested calls, same-kind control flow,
  matrix-operation and constructor returns, named/reordered arguments, zero
  dimensions, call-specific float/int/bool/string/color kinds, and independent
  copies share the five matrix helpers with copy-only continuation. Unknown/
  `na`, scalar, array, map, remaining user-function results, broader helper,
  mutation, and terminal-read continuation cases remain gated.
  The next closed call-boundary slice admits local and imported user-method
  results with a concrete supported matrix kind. Receiver-style, local-type-
  qualified or alias-qualified, direct-constructor-receiver, block/nested/same-
  kind-control-flow, float/int/bool/string/color, zero-dimension, same-library
  dual-alias, independent-copy, and copy-only-continuation paths share the same
  five helpers. Unknown/`na`, non-matrix or unresolved method results,
  unregistered or unresolved user-function matrix results, broader helpers,
  mutation, and
  terminal-read continuation remain gated.
  The following closed call-boundary slice admits registered imported pure-
  function results with a concrete supported matrix kind. Alias-qualified,
  block/nested/same-kind-control-flow, float/int/bool/string/color, zero-
  dimension, same-library dual-alias, independent-copy, and copy-only-
  continuation paths share the same five helpers. Unknown/`na`, non-matrix,
  unregistered or unresolved function results, broader helpers, mutation, and
  terminal-read continuation remain gated.
  The following closed slice admits exact namespace
  `matrix.transpose(values)` on that path. It preserves the same five element
  kinds through `SameAsArg`, swaps row/column shape, returns independent
  storage, and shares the five matrix helpers plus copy-only continuation;
  bound `values.transpose()` results stay gated.
  The next closed slice admits exact namespace `matrix.submatrix(values, ...)`.
  Its `SameAsArg` result preserves the five element kinds, returns independent
  half-open ranges with default full bounds and empty row/column slices, and
  shares the five matrix helpers plus copy-only continuation; bound
  `values.submatrix()` results stay gated.
  The following closed slice admits exact namespace `matrix.kron(left, right)`.
  Its fixed `simple matrix<float>` result accepts numeric matrix inputs,
  expands both dimensions, retains independent storage plus `na` and
  zero-dimension behavior, and shares the five matrix helpers plus copy-only
  continuation; bound `values.kron(other)` results stay gated.
  The next closed slice admits exact namespace `matrix.diff(left, right)`.
  Its fixed `simple matrix<float>` result accepts matrix-matrix, matrix-scalar,
  and scalar-matrix numeric operands, preserves the selected matrix shape and
  left-to-right subtraction direction, and shares the five matrix helpers plus
  copy-only continuation; bound `values.diff(other)` results stay gated.
  The following closed slice admits exact namespace `matrix.pow(values, power)`.
  Its fixed `simple matrix<float>` result accepts numeric square matrices and
  simple-int powers, preserves independent identity/copy/positive-power
  results plus `na` and empty `0 x 0` behavior, and shares the five matrix
  helpers plus copy-only continuation; bound `values.pow(power)` results stay
  gated.
  The next closed slice admits exact namespace `matrix.inv(values)`. Its fixed
  `simple matrix<float>` result preserves square shape for invertible numeric
  matrices, yields an empty `0 x 0` matrix for empty input and `na` for singular
  or invalid-cell inputs, and shares the five matrix helpers plus copy-only
  continuation; bound `values.inv()` results stay gated.
  The following closed slice admits exact namespace `matrix.pinv(values)`. Its
  fixed `simple matrix<float>` result accepts numeric matrices, swaps
  rectangular row/column counts, preserves singular matrix-valued results,
  returns swapped zero-cell shapes for zero-row or zero-column inputs, and
  shares the five matrix helpers plus copy-only continuation; invalid-cell
  inputs yield `na`, and bound `values.pinv()` results stay gated.
  The next closed slice admits exact namespace `matrix.eigenvectors(values)`.
  Its fixed `simple matrix<float>` result accepts numeric square matrices,
  preserves square shape for real complete eigenvector columns, returns empty
  `0 x 0`, and yields `na` for invalid-cell, non-real, or incomplete results.
  It shares the five matrix helpers plus copy-only continuation; bound
  `values.eigenvectors()` results stay gated and non-square runtime errors are
  unchanged.
  The next terminal element-mutation slice adds top-level `.pop()` across the
  same producer set. It removes and returns the final resolved scalar/object/
  `chart.point` or concrete local/imported UDT element, returns `na` for empty
  or upstream-`na`, and cannot continue. Alias results and nested live slices
  shrink their backing parent, while fresh matrix/map/mult snapshots leave
  sources unchanged. Invalid arity, UDF-side-effect, and element-identity
  boundaries are fixture-backed; remaining direct mutations stay gated and
  public schemas are unchanged.
  The symmetric terminal element-mutation slice adds top-level `.shift()`
  across the same producer set. It removes and returns the first resolved
  scalar/object/`chart.point` or concrete local/imported UDT element, preserves
  remaining-element order, returns `na` for empty or upstream-`na`, and cannot
  continue. Alias results and nested live slices shrink their backing parent,
  while fresh matrix/map/mult snapshots leave sources unchanged. Invalid arity,
  UDF-side-effect, and element-identity boundaries are fixture-backed; remaining
  direct mutations stay gated and public schemas are unchanged.
  The indexed terminal element-mutation slice adds top-level `.remove(index)`
  across the same producer set. It removes and returns the selected positive or
  in-range negative scalar/object/`chart.point` or concrete local/imported UDT
  element. Explicit `na` indexes and upstream-`na` receivers return `na` without
  mutation; out-of-range indexes retain runtime errors. Alias results and nested
  live slices delete from their backing parent, while fresh matrix/map/mult
  snapshots leave sources unchanged. Index type/arity, UDF-side-effect, and
  identity boundaries are fixture-backed; public schemas are unchanged.
  The single-value append slice adds top-level `.push(value)` across the same
  producer set plus concrete map-result keys/values and matrix-result row/col/
  eigenvalue continuations. It validates scalar/object/`chart.point` kind or
  local/imported UDT identity, appends to alias/live-slice parent backing,
  returns `void`, and cannot continue; fresh derived snapshots leave source
  collections unchanged. Invalid value/arity, upstream-`na`, 100000-element
  capacity, and UDF-side-effect boundaries are fixture-backed; public schemas
  remain unchanged.
  The symmetric single-value prepend slice adds top-level `.unshift(value)`
  across the same producer set. It validates the same element kind or concrete
  UDT identity, inserts at the alias/live-slice start, returns `void`, and
  cannot continue; fresh derived snapshots remain source-independent. Invalid
  value/arity, upstream-`na`, 100000-element capacity, and UDF-side-effect
  boundaries retain ordinary behavior; public schemas remain unchanged.
  The indexed insertion slice adds top-level `.insert(index, value)` across the
  same producer set. It preserves simple-int-compatible positive, in-range
  negative, end, and `na` index behavior, validates element kind or concrete
  UDT identity, inserts into alias/live-slice parent backing, returns `void`,
  and cannot continue; fresh derived snapshots stay source-independent.
  Bounds, value/arity, upstream-`na`, capacity, and UDF-side-effect boundaries
  retain ordinary behavior; public schemas remain unchanged.
  The indexed replacement slice adds top-level `.set(index, value)` across the
  same producer set. It preserves simple-int-compatible positive, in-range
  negative, explicit-`na`, empty, and out-of-range index behavior, validates
  element kind or concrete UDT identity, replaces an alias/live-slice parent
  slot without changing length, returns `void`, and cannot continue; fresh
  snapshots remain source-independent. Value/arity, upstream-`na`, and UDF-
  side-effect boundaries retain ordinary behavior; public schemas stay fixed.
  The range-fill slice adds top-level
  `.fill(value, index_from?, index_to?)` across the same producer set. It
  validates the element kind or concrete UDT identity and optional simple-int-
  compatible half-open bounds; omitted bounds fill the full result. Alias/live-
  slice writes reach parent backing, while fresh derived snapshots stay source-
  independent. Explicit `na`, negative, reversed, oversized, empty, and
  upstream-`na` cases no-op after all supplied arguments are evaluated. The
  mutation returns `void`, cannot continue, stays rejected inside UDFs, and
  leaves public schemas unchanged.
  The in-place ordering slice adds terminal top-level
  `.sort(order?, sort_field?)` across the same concrete producer set. Int/
  float/string results preserve ordinary stable ascending/default or descending
  ordering; same-local and same-imported scalar-tree UDT results require a
  compile-time root int/float/string field resolved against their exact
  identity. Alias/live-slice results reorder parent backing, while fresh
  derived snapshots stay source-independent. Empty/upstream-`na`, unsupported
  kind, field/order/arity, terminal continuation, and UDF-side-effect behavior
  remains unchanged; public schemas stay fixed.
  The non-mutating index-ordering slice extends
  `.sort_indices(order?, sort_field?)` to concrete same-local and same-imported
  scalar-tree UDT call results across the identity-preserving built-in and
  user-defined producer paths. A compile-time root int/float/string field is
  lowered against the exact result identity. The operation returns a fresh,
  stable `array<int>` of original indexes, leaves the UDT source unchanged,
  and may continue through the existing closed int-array chain; missing,
  unknown, dynamic, unsupported-field, unresolved-identity, and non-scalar-
  identity boundaries remain closed without changing public schemas.
  The array-returning mutation slice adds `.concat(id2)` across every concrete
  array call result and derived-array continuation. It requires the same
  scalar/object/`chart.point` kind or exact scalar-tree UDT identity, appends
  into the receiver, returns the first array id, and may continue through the
  closed helper set. Alias and live-slice results update shared parent backing;
  fresh namespace/map/matrix/`matrix.mult` snapshots remain source-independent.
  Empty/upstream-`na`, capacity, kind/identity/arity, and UDF-side-effect
  behavior retain the existing `array.concat` contract; schemas stay fixed.
  The following closed slice admits exact
  `matrix.new<float|int|bool|string|color>` template results. They preserve the
  registered element kind, requested rectangular shape, type-compatible
  initial or default `na` cells, fresh allocation, and copy independence, and
  share the five matrix helpers plus copy-only continuation. Unsupported or
  deferred matrix templates and postfix mutation stay gated.
  The next closed collection-result slice admits exact supported scalar
  `map.new<K,V>` templates through `$builtin_map_result`. Fresh empty maps
  retain concrete key/value kinds and expose only `.size()`, `.get(key)`,
  `.contains(key)`, and `.copy()`, with copy-only continuation. Mutation,
  direct `keys()`/`values()`, unsupported templates, and other map call-result
  receivers remain gated.
  The following closed map-result slice admits exact namespace
  `map.copy(existing)` through the same prefix. It retains the source scalar
  key/value kinds and entries in an independent backing store and exposes the
  same four helpers with copy-only continuation. Non-map inputs, mutation, and
  direct `keys()`/`values()` remain gated.
  The next closed map call-boundary slice admits unqualified local-UDF results
  with one concrete supported scalar map template through `$call_result`.
  Parameter passthrough, block aliases, nested calls, same-template control
  flow, constructed/copied results, named/reordered arguments, empty maps,
  per-call scalar key/value kinds, and independent copies share the four map
  helpers with copy-only continuation. Unknown/`na`, scalar, array, matrix,
  local user-method, imported user-method/imported-function,
  wrong-template/key, broader-helper, mutation, and terminal-read continuation
  remain gated.
  The following closed map call-boundary slice admits local user-method results
  with one concrete supported scalar map template. Receiver-style,
  local-type-qualified, direct-constructor-receiver, block-return,
  nested-method, same-template control-flow, constructed-result,
  scalar-template-interleaving, independent-copy, and copy-only-continuation
  paths share the four helpers. Imported methods, unresolved or mixed
  templates, broader helpers, mutation, and terminal-read continuation remain
  gated.
  The next closed map call-boundary slice admits imported user-method results
  with one concrete supported scalar map template through the same
  analysis-marked method-result path. Receiver-style, alias-qualified,
  direct-constructor-receiver, block-return, nested-method, same-template
  control-flow, constructed-result, scalar-template-interleaving, same-library
  dual-alias, independent-copy, and copy-only-continuation cases are
  fixture-backed.
  The next closed map call-boundary slice admits registered imported pure
  functions with one concrete supported scalar map template. Alias-qualified,
  block-return, nested-function, same-template control-flow,
  constructed-result, scalar-template-interleaving, same-library dual-alias,
  independent-copy, and copy-only-continuation cases share the four helpers;
  wrong-template/key, broader-helper, mutation, scalar-return, and terminal-
  reader boundaries remain gated.
  The following read-only map-result slice admits `.keys()` on every existing
  concrete scalar-map call-result producer: supported `map.new<K,V>`,
  `map.copy(existing)`, local/imported pure functions, and local/imported user
  methods. The result is a fresh key-kind-preserving scalar array and supports
  direct binding plus `.size()`/`.get()`/`.first()`/`.last()`/`.copy()`, with
  copy-only array continuation and source-map independence. Direct `.values()`,
  map or call-result-array mutation, unsupported templates, broader helpers,
  and continuation after a terminal key-array reader remain gated.
  The next read-only map-result slice adds `.values()` across the same producer
  set. It returns a fresh value-kind-preserving scalar array and supports the
  same direct binding, five array readers, copy-only continuation, dual-alias,
  and source-map-independence paths. Map or call-result-array mutation,
  unsupported templates, broader helpers, and continuation after a terminal
  key/value-array reader remain gated.
  The next map-result mutation slice adds terminal `.put(key, value)` across
  that concrete scalar-map producer set. It validates the resolved scalar key/
  value kinds, replaces an existing value without changing key position or
  appends a new insertion-order entry, returns `void`, and cannot continue.
  Local UDF/user-method alias results update shared storage; fresh `map.new`,
  `map.copy`, imported-function, and imported-method results isolate the write.
  Invalid key/value/arity, UDF-side-effect, remaining map-mutation, and public-
  schema boundaries retain ordinary `map.put` behavior.
  The following map-result mutation slice adds terminal `.clear()` across the
  same producer set. It empties the resolved backing map, returns `void`, and
  cannot continue. Local UDF/user-method alias results update shared storage;
  fresh constructor, copy, imported-function, and imported-method results
  isolate the clear. Arity, UDF-side-effect, remaining mutation, template, and
  public-schema boundaries retain ordinary `map.clear` behavior.
  The next map-result mutation slice adds terminal `.remove(key)` across the
  same producer set. It validates the resolved key kind, deletes a matching
  entry without reordering retained keys, no-ops for a missing key, returns
  `void`, and cannot continue. Local alias results update shared storage;
  fresh constructor, copy, imported-function, and imported-method results
  isolate the removal. Invalid key/arity, UDF-side-effect, remaining mutation,
  template, and public-schema boundaries retain ordinary `map.remove` behavior.
  The final registered scalar map-result mutation slice adds terminal
  `.put_all(source)` across the same producer set. It requires an identical
  source template, clones source entries for self-merge safety, replaces values
  without moving retained keys, appends new keys in source order, returns
  `void`, and cannot continue. Local aliases merge into shared storage; fresh
  constructor, copy, imported-function, and imported-method targets isolate the
  merge. Invalid source/template/arity, UDF-side-effect, and public-schema
  boundaries retain ordinary `map.put_all` behavior. This completes the
  registered scalar map helper set on concrete map call results.
  The following read-only matrix-result slice adds `.row(index)` to every
  existing concrete matrix call-result producer: namespace and bound matrix
  operations, exact `matrix.new<float|int|bool|string|color>` templates, local
  UDFs, local/imported user methods, and registered imported pure functions.
  The result is a fresh element-kind-preserving scalar array and supports
  direct binding plus `.size()`/`.get()`/`.first()`/`.last()`/`.copy()`, with
  copy-only array continuation, source-matrix independence, and dual-alias
  isolation. Bad indexes retain the ordinary `matrix.row` checks. `.col()`,
  matrix or call-result-array mutation, broader helpers, and continuation after
  a terminal row-array reader remain gated.
  The next read-only matrix-result slice adds `.col(index)` across the same
  producer set. It returns a fresh element-kind-preserving scalar array with
  direct binding, the five array readers, copy-only continuation, source-matrix
  independence, and dual-alias isolation. Bad indexes retain the ordinary
  `matrix.col` checks. Matrix or call-result-array mutation, broader matrix
  helpers, and continuation after a terminal column-array reader remain gated.
  The following numeric matrix-result slice adds `.eigenvalues()` wherever the
  concrete call result satisfies the existing numeric-matrix signature. It
  returns a fresh `array<float>` with the five array readers and copy-only
  continuation; the existing square-matrix runtime boundary, `na`/non-real
  result behavior, and source independence remain unchanged. Non-numeric
  matrix results, array mutation, broader matrix helpers, and continuation
  after a terminal eigenvalue-array reader remain gated.
  The next matrix-result predicate slice adds terminal `.is_square()` across
  the same concrete producer set. It accepts all five supported scalar matrix
  kinds, returns a simple bool using the ordinary row/column equality rule,
  and intentionally does not transition to another matrix or array call-result
  prefix. Namespace/bound operations, exact templates, local/imported function
  and method provenance, true/false shapes, dual aliases, invalid arity, and
  terminal continuation are fixture-backed; other broader helpers and mutation
  remain gated.
  The following numeric matrix-result predicate slice adds terminal
  `.is_zero()` to every concrete float/int matrix producer. It retains the
  ordinary exact-zero, zero-element, `na`-cell, and upstream-`na` result rules,
  returns a simple bool, and creates no further result prefix. Namespace/bound
  operations, exact numeric templates, local/imported function and method
  provenance, dual aliases, non-numeric rejection, invalid arity, and terminal
  continuation are fixture-backed; remaining broader helpers and mutation stay
  gated.
  The next numeric predicate slice adds terminal `.is_binary()` across the
  same float/int producer set. It preserves the exact 0-or-1 test, true empty-
  matrix result, false non-binary/`na`-cell results, upstream-`na` propagation,
  simple-bool return, and no-prefix terminal behavior. Namespace/bound
  operations, exact numeric templates, local/imported function and method
  provenance, dual aliases, non-numeric rejection, invalid arity, and terminal
  continuation are fixture-backed; other broader helpers and mutation remain
  gated.
  The following numeric predicate slice adds terminal `.is_diagonal()` across
  the same producer set. It does not require square shape, permits arbitrary
  main-diagonal values (including `na`), requires exact-zero off-diagonal
  cells, returns true for empty matrices, propagates upstream `na`, and creates
  no result prefix. Numeric type rejection, provenance/dual aliases, invalid
  arity, and terminal continuation are fixture-backed.
  The next numeric predicate slice adds terminal `.is_identity()` across the
  same producer set. It requires square shape, exact-one main-diagonal cells,
  exact-zero off-diagonal cells, returns false for any `na`, true for empty
  0×0 matrices, propagates upstream `na`, and creates no result prefix. Numeric
  rejection, provenance/dual aliases, invalid arity, and terminal continuation
  are fixture-backed.
  The following numeric predicate slice adds terminal `.is_symmetric()` across
  the same producer set. It requires square shape and exact equality of every
  transposed pair, returns false for any `na`, true for empty 0×0 matrices,
  propagates upstream `na`, and creates no result prefix. Numeric rejection,
  provenance/dual aliases, invalid arity, and terminal continuation are
  fixture-backed.
  The next numeric predicate slice adds terminal `.is_antisymmetric()` across
  the same producer set. It requires square shape, an exact-zero main diagonal,
  and exact negation across every transposed pair; it returns false for any
  `na`, true for empty 0×0 matrices, propagates upstream `na`, and creates no
  result prefix. Numeric rejection, provenance/dual aliases, invalid arity,
  and terminal continuation are fixture-backed.
  The following numeric predicate slice adds terminal `.is_stochastic()`
  across the same producer set. It requires a non-empty matrix of finite non-
  negative values and returns true when every row or every column sums exactly
  to one; empty matrices, invalid cells, and negative values are false, while
  upstream `na` propagates. It creates no result prefix, and numeric rejection,
  provenance/dual aliases, invalid arity, and terminal continuation are
  fixture-backed.
  The next numeric aggregate slice adds terminal `.sum()` across the same
  producer set. It retains the fixed `series float` result, ignores `na`
  cells, returns `na` for empty, all-`na`, non-finite, or upstream-`na`
  results, and creates no result prefix. Numeric rejection, copy continuation,
  provenance/dual aliases, invalid arity, and terminal continuation are
  fixture-backed.
  The following numeric aggregate slice adds terminal `.avg()` across the same
  producer set. It retains the fixed `series float` result, averages only non-
  `na` cells, returns `na` for empty, all-`na`, non-finite, or upstream-`na`
  results, and creates no result prefix. Numeric rejection, copy continuation,
  provenance/dual aliases, invalid arity, and terminal continuation are
  fixture-backed.
  The next numeric aggregate slice adds terminal `.min()` across the same
  producer set. It retains the fixed `series float` result, scans only non-
  `na` cells, returns `na` for empty, all-`na`, non-finite, or upstream-`na`
  results, and creates no result prefix. Numeric rejection, copy continuation,
  provenance/dual aliases, invalid arity, and terminal continuation are
  fixture-backed.
  The following numeric aggregate slice adds terminal `.max()` across the same
  producer set. It retains the fixed `series float` result, scans only non-
  `na` cells, returns `na` for empty, all-`na`, non-finite, or upstream-`na`
  results, and creates no result prefix. Numeric rejection, copy continuation,
  provenance/dual aliases, invalid arity, and terminal continuation are
  fixture-backed.
  The next numeric aggregate slice adds terminal `.mode()` across the same
  producer set. It retains the fixed `series float` result, ignores `na` cells,
  selects the smaller value on an equal-frequency tie, returns `na` for empty,
  all-`na`, no-repeat, non-finite, or upstream-`na` results, and creates no
  result prefix. Numeric rejection, copy continuation, provenance/dual aliases,
  invalid arity, and terminal continuation are fixture-backed.
  The following numeric aggregate slice adds terminal `.trace()` across the
  same producer set. It retains the fixed `series float` result, sums non-`na`
  main-diagonal cells over `min(rows, columns)`, returns `na` for an empty/all-
  `na` diagonal, non-finite sum, or upstream-`na` result, and creates no result
  prefix. Numeric rejection, copy continuation, provenance/dual aliases,
  invalid arity, and terminal continuation are fixture-backed.
  The next linear-algebra reader slice adds terminal `.det()` across the same
  producer set. It retains the fixed `series float` result, runtime square-
  matrix error, `0 x 0 = 1.0`, singular zero, invalid-cell/non-finite `na`, and
  upstream-`na` propagation without adding static shape inference. Numeric
  rejection, copy continuation, provenance/dual aliases, invalid arity, and
  terminal continuation are fixture-backed.
  The following linear-algebra reader slice adds terminal `.rank()` across the
  same producer set. It retains the fixed `series int` result, supports
  rectangular and singular matrices, returns `0` for zero-element matrices,
  returns `na` for invalid/non-finite cells or upstream `na`, and creates no
  result prefix. Numeric rejection, copy continuation, provenance/dual aliases,
  invalid arity, and terminal continuation are fixture-backed.
  The next matrix-valued continuation slice adds `.transpose()` across every
  existing concrete matrix-result producer. It preserves the receiver's
  float/int/bool/string/color element kind, returns an independent matrix with
  swapped row/column counts, propagates upstream `na`, preserves zero-cell
  shapes, and retains the matrix-result prefix across `.copy()`, repeated
  `.transpose()`, and supported readers. Namespace/bound operations, exact
  templates, local/imported functions and methods, five-kind reads, source
  independence, provenance/dual aliases, repeated continuation, and invalid
  arity are fixture-backed; mutation and other matrix-valued transforms remain
  gated.
  The following matrix-valued continuation slice adds `.submatrix(...)`
  across the same producer set. It preserves float/int/bool/string/color
  element kind, returns an independent optional/default half-open range,
  preserves empty row/column shapes, propagates upstream `na`, and retains the
  matrix-result prefix. Namespace/bound operations, exact templates,
  local/imported functions and methods, named arguments, nested ranges, five-
  kind reads, source independence, provenance/dual aliases, invalid types/
  arity, and runtime bounds are fixture-backed; mutation and other matrix-
  valued transforms remain gated.
  The next numeric matrix-valued continuation slice adds `.inv()` across every
  existing concrete numeric matrix-result producer. It retains the numeric
  receiver check, always returns an independent fixed `matrix<float>`,
  preserves square shape for invertible inputs, returns empty `0 x 0` for
  empty input, yields `na` for singular, invalid-cell, non-finite, or upstream-
  `na` inputs, and retains the matrix-result prefix. Namespace and bound
  operations, local/imported functions and methods, int-to-float lowering,
  nested chains, source independence, provenance/dual aliases, invalid types/
  arity, and the runtime non-square boundary are fixture-backed; mutation and
  other matrix-valued transforms remain gated.
  The following numeric matrix-valued continuation slice adds `.pinv()` across
  the same concrete producer set. It retains the numeric receiver check,
  always returns an independent fixed `matrix<float>`, swaps rectangular row/
  column counts, preserves singular matrix-valued results and swapped zero-cell
  shapes, yields `na` for invalid-cell, non-finite, or upstream-`na` inputs,
  and retains the matrix-result prefix. Namespace and bound operations,
  local/imported functions and methods, int-to-float lowering, nested/double
  chains, source independence, provenance/dual aliases, invalid types/arity,
  and rectangular/singular/zero-cell boundaries are fixture-backed; mutation
  and other matrix-valued transforms remain gated.
  The next numeric matrix-valued continuation slice adds `.eigenvectors()`
  across the same concrete producer set. It retains the numeric receiver check,
  always returns an independent fixed `matrix<float>`, preserves square shape
  for a complete real eigenvector basis, returns empty `0 x 0`, retains the
  runtime non-square error, yields `na` for invalid-cell, non-finite, non-real,
  incomplete, or upstream-`na` results, and retains the matrix-result prefix.
  Namespace and bound operations, local/imported functions and methods, int-
  to-float lowering, nested/double chains, source independence, provenance/
  dual aliases, invalid types/arity, and runtime failure boundaries are
  fixture-backed; mutation and other matrix-valued transforms remain gated.
  The following numeric matrix-valued continuation slice adds `.pow(power)`
  across the same concrete producer set. It retains the numeric receiver and
  simple-int power checks, always returns an independent fixed `matrix<float>`,
  keeps the runtime square-matrix boundary, supports identity/copy/positive
  powers and empty `0 x 0`, preserves `na` cells for positive powers, retains
  negative and `na` power errors, and keeps the matrix-result prefix. Namespace
  and bound operations, local/imported functions and methods, int-to-float
  lowering, nested powers, source independence, provenance/dual aliases,
  invalid types/arity, and runtime failure boundaries are fixture-backed;
  mutation and other matrix-valued transforms remain gated.
  The following numeric matrix-valued continuation slice adds `.mult(other)`
  across the same concrete producer set. It retains the numeric receiver and
  numeric matrix/scalar/array operand checks. Matrix operands return an
  independent fixed `matrix<float>` with receiver rows and operand columns,
  scalar operands preserve receiver shape, and numeric-array operands return
  an independent `array<float>` with one value per receiver row. Semantic
  result typing selects the closed matrix or array continuation set while
  retaining `na`, zero-inner-dimension, multiplication-order, matrix cell-
  budget, matrix-dimension, and vector-length behavior. Namespace and bound
  operations, local/imported functions and methods, int-to-float lowering,
  nested multiplication, source independence, provenance/dual aliases,
  invalid types/arity, and runtime failure boundaries are fixture-backed;
  mutation and other matrix-valued transforms remain gated.
  The following numeric matrix-valued continuation slice adds `.kron(other)`
  across the same concrete producer set. It retains the numeric receiver and
  numeric-matrix operand checks, always returns an independent fixed
  `matrix<float>`, multiplies both source row and column dimensions, preserves
  `na` cells and zero dimensions, propagates upstream `na`, keeps the matrix
  cell-budget error, and retains the matrix-result prefix. Namespace and bound
  operations, local/imported functions and methods, int-to-float lowering,
  nested Kronecker products, source independence, provenance/dual aliases,
  invalid types/arity, and runtime failure boundaries are fixture-backed;
  mutation and other matrix-valued transforms remain gated.
  The following numeric matrix-valued continuation slice adds `.diff(other)`
  across the same concrete producer set. It retains the numeric receiver and
  numeric-matrix-or-scalar operand checks, always returns an independent fixed
  `matrix<float>`, preserves receiver shape and left-to-right subtraction,
  propagates `na` cells, `na` scalars, and upstream `na`, preserves zero
  dimensions, keeps the matching-shape runtime error for matrix operands, and
  retains the matrix-result prefix. Namespace and bound operations, local/
  imported functions and methods, int-to-float lowering, nested differences,
  scalar and matrix operands, source independence, provenance/dual aliases,
  invalid types/arity, and runtime failure boundaries are fixture-backed;
  mutation and other matrix-valued transforms remain gated.
  The next terminal array-result slice adds `.includes(value)` to every
  existing concrete array call-result producer: qualified and unqualified
  local/imported UDF and method results, the static `array.*` producer
  allowlist, the seven cross-namespace scalar-array producers, matrix-derived
  row/column/eigenvalue arrays, map key/value arrays, and array-returning
  `matrix.mult` overloads. It reuses the ordinary element-kind and same-
  identity UDT argument checks plus structural/object equality, returns
  `series bool`, is false for an empty concrete array, propagates an upstream
  `na` array, performs no mutation, and creates no continuation prefix. Scalar,
  drawing/chart-point, local/imported UDT, A-to-B-to-A, dual-alias isolation,
  wrong type/identity, invalid arity, copy continuation, and terminal-
  continuation boundaries are fixture-backed.
  The following terminal array-result slice adds `.indexof(value)` across the
  same producer set. It reuses the ordinary element-kind and same-identity UDT
  validation plus structural/object equality, returns the first zero-based
  match as `simple int`, returns `-1` for missing or empty concrete arrays and
  for an upstream `na` array, performs no mutation, and creates no continuation
  prefix. Scalar, drawing/chart-point, local/imported UDT, A-to-B-to-A, dual-
  alias isolation, wrong type/identity, invalid arity, copy continuation, and
  terminal-continuation boundaries are fixture-backed.
  The next terminal array-result slice adds `.lastindexof(value)` across the
  same producer set. It reuses the same validation and equality path, returns
  the last zero-based match as `simple int`, returns `-1` for missing or empty
  concrete arrays and for an upstream `na` array, performs no mutation, and
  creates no continuation prefix. Repeated scalar and structural-UDT values,
  every existing static/cross-namespace/matrix-derived/map-derived producer,
  wrong type/identity, invalid arity, copy continuation, and terminal-
  continuation boundaries are fixture-backed.
  The following numeric-only array-result slice adds
  `.binary_search(value)` to concrete `array<int>` and `array<float>` results
  across the registered static and cross-namespace producers plus qualified/
  unqualified local and imported UDF/method results. It preserves the ordinary
  numeric receiver/value checks, expects ascending contents, performs an exact
  lower-bound search so duplicates select the leftmost index, returns `simple
  int`, returns `-1` for missing, empty, and upstream-`na` arrays, performs no
  mutation, and creates no continuation prefix. Numeric constructor/copy/from/
  slice/concat/abs/standardize/sort-indices, numeric matrix row/column/
  eigenvalue/mult, numeric map key/value, local/imported scalar array results,
  wrong type/arity, nonnumeric/object/UDT rejection, copy continuation, and
  terminal-continuation paths are fixture-backed.
  The next numeric-only slice adds `.binary_search_leftmost(value)` across the
  same result producers. It keeps the ascending-input and numeric gates; exact
  duplicates return their first index, while misses return the nearest-left
  element index, clamped to `0` below the minimum and the last index above the
  maximum. Empty and upstream-`na` arrays return `-1`; the fixed `simple int`
  result is non-mutating and terminal. Static/cross-namespace, numeric matrix/
  map-derived, local/imported function/method, duplicate, between-value, clamp,
  empty/`na`, invalid type/arity, copy-continuation, and terminal-continuation
  paths are fixture-backed.
  The following symmetric slice adds `.binary_search_rightmost(value)` to that
  numeric producer set. Exact duplicates return their last index; misses return
  the nearest-right element index, with the same below-min/above-max clamps,
  empty/upstream-`na` `-1`, numeric/ascending gates, fixed `simple int`, non-
  mutation, and terminal boundaries. Static/cross-namespace, numeric matrix/
  map-derived, local/imported function/method, duplicate, between-value, clamp,
  invalid type/arity, copy-continuation, and terminal-continuation paths are
  fixture-backed.
  The next transformation slice adds `.abs()` to every concrete numeric array
  call result. It returns a fresh same-kind int/float array, preserves `na`
  elements, leaves the source unchanged, returns empty for an empty receiver,
  propagates upstream `na`, and may continue through another admitted reader,
  `.copy()`, or `.abs()`. Static/cross-namespace, matrix/map-derived, local/
  imported function/method, nonnumeric/UDT rejection, invalid arity, empty/
  `na`, and continuation paths are fixture-backed.
  The following terminal aggregate slice adds `.min(nth?)` to every concrete
  numeric array call result. It returns the receiver element's series numeric
  kind, ranks filtered non-`na` values in ascending order with a zero-based
  optional dynamic integer rank defaulting to `0`, and preserves duplicate
  ranks. Empty/all-`na`/upstream-`na` arrays and `na`, negative, or out-of-range
  ranks return `na`. Static/cross-namespace, matrix/map-derived, local/imported
  function/method, int/float, rank binding, invalid type/arity, and terminal-
  continuation paths are fixture-backed.
  The symmetric terminal aggregate slice adds `.max(nth?)` to the same numeric
  result set. It uses descending zero-based rank order (`nth=0` is the maximum)
  while retaining receiver-derived series int/float results, filtered `na`,
  duplicate ranks, dynamic integer ranks, empty/all-`na`/upstream-`na`, invalid
  rank, nonnumeric/UDT, arity, and terminal-continuation boundaries.
  The next terminal aggregate slice adds `.sum()` to the same numeric result
  set. It preserves receiver-derived series int/float results, ignores `na`
  elements, returns `na` for empty/all-`na`/upstream-`na` arrays, does not
  mutate the receiver, and retains nonnumeric/UDT, arity, and terminal-chain
  boundaries across static, cross-namespace, matrix/map-derived, and local/
  imported function/method producers.
  The following terminal aggregate slice adds `.avg()` over the same concrete
  numeric results. It always returns series float, filters `na`, returns `na`
  for empty/all-`na`/upstream-`na` or non-finite results, and retains the sum
  slice's provenance, type, arity, non-mutation, and terminal boundaries.
  The next terminal aggregate slice adds `.range()`. It computes filtered
  maximum minus minimum, preserves receiver-derived series int/float, returns
  `na` for empty/all-`na`/upstream-`na` or non-finite float differences, and
  retains the same producer, invalid-type/arity, non-mutation, and terminal
  boundaries.
  The following terminal aggregate slice adds `.median()`. It sorts filtered
  values, uses a middle item or middle-pair mean, preserves receiver-derived
  series int/float with integer pair means truncated toward zero, and retains
  empty/all-`na`/upstream-`na`, non-finite float, provenance, invalid-type/
  arity, non-mutation, and terminal boundaries.
  The next terminal aggregate slice adds `.mode()`. It returns the most
  frequent filtered value in the receiver-derived series int/float kind,
  chooses the smaller value for tied frequencies, requires at least one
  repeated value, and retains empty/all-`na`/upstream-`na`, provenance,
  invalid-type/arity, non-mutation, and terminal boundaries.
  The next percentile slice adds `.percentile_nearest_rank(percentage)`. It
  filters and sorts values, uses `ceil(percentage / 100 * count)` nearest-rank
  selection with 0/100 endpoints, preserves receiver-derived series int/float,
  accepts positional or named series/simple numeric percentages, and retains
  empty/all-`na`/upstream-`na`, runtime typed-`na`, out-of-range, provenance,
  invalid-type/arity, non-mutation, and terminal boundaries.
  The following percentile slice adds
  `.percentile_linear_interpolation(percentage)`. It interpolates sorted
  floor/ceiling members at `percentage / 100 * (count - 1)`, always returns
  series float for int/float and single-element inputs, accepts positional or
  named series/simple numeric percentages, and retains empty/all-`na`/upstream-
  `na`, runtime typed-`na`, out-of-range, non-finite-result, provenance,
  invalid-type/arity, non-mutation, and terminal boundaries.
  The next indexed-statistics slice adds `.percentrank(index)`. It selects the
  target from the original array index, filters `na` only from the comparison
  population, counts duplicate values independently, and returns fixed series
  float. Positional or named simple-int-compatible indexes are accepted while
  empty/all-`na`/upstream-`na`, target-`na`, runtime typed-`na`, negative, and
  out-of-range indexes retain `na`; provenance, invalid-type/arity, non-
  mutation, and terminal boundaries remain closed.
  The following paired-statistics slice adds `.covariance(id2, biased?)`. It
  requires a same-length numeric second array, aligns cells by original index,
  filters pairs containing `na`, defaults to the population denominator, and
  uses the sample denominator for `false` or `na` bias. It returns fixed series
  float while retaining empty/all-`na`/upstream-`na`, mismatched-length,
  insufficient-sample, non-finite-result, provenance, invalid-type/arity, non-
  mutation, and terminal boundaries.
  The next numeric transformation slice adds `.standardize()`. It returns an
  independent fixed float array, computes mean and population standard
  deviation over non-`na` values, preserves `na` positions, and maps numeric
  positions to `na` when the deviation is zero or non-finite. Empty/all-`na`
  inputs return an empty array and upstream-`na` propagates. Static, cross-
  namespace, matrix/map-derived, local/imported result provenance, invalid
  type/arity, source independence, and copy/abs/standardize/sort_indices continuation are
  fixture-backed.
  The following dispersion slice adds terminal `.variance(biased?)`. It
  filters `na`, returns fixed series float, uses the population denominator by
  default or for `true`, and the sample denominator for `false` or `na`.
  Single-value population variance is zero; empty/all-`na`/upstream-`na`,
  insufficient-sample, and non-finite results retain `na`. Static, cross-
  namespace, matrix/map-derived, local/imported provenance, invalid type/
  arity, non-mutation, and terminal-continuation boundaries are fixture-backed.
  The paired dispersion slice then adds terminal `.stdev(biased?)`, taking the
  square root of the same selected population or sample variance. It retains
  filtered `na`, default/`true` population and `false`/`na` sample bias,
  single-value population zero, empty/all-`na`/upstream-`na`, insufficient-
  sample, non-finite, provenance, invalid type/arity, non-mutation, and
  terminal-continuation coverage across the same four result-source families.
  The following ordering transformation slice adds `.sort_indices(order?)` to
  every concrete int, float, or string array call result across the same
  static, cross-namespace, matrix/map-derived, and local/imported result-source
  families. It returns an independent fixed int-index array with stable
  original-index ordering, default ascending or explicit descending order,
  established float-`na` and string-empty placement, empty results, upstream-
  `na` propagation, source non-mutation, and nested sort/copy/read/search/
  transformation/statistic continuation. Bool/color/object/chart-point results,
  invalid order/arity, direct mutation, and UDT result ordering before an
  identity-preserving binding remain gated.
  The next predicate slice adds terminal `.every()` to every concrete bool,
  int, or float array call result across the same static, cross-namespace,
  matrix/map-derived, and local/imported result-source families. It returns
  fixed series bool, accepts only nonzero numerics or `true` as truthy, treats
  zero, `false`, and element `na` as false, returns true for empty arrays,
  propagates an upstream `na` array, and leaves the source unchanged. String,
  color, object, chart-point, UDT, extra-arity, and terminal-continuation
  boundaries are fixture-backed.
  The paired predicate slice adds terminal `.some()` across the same concrete
  bool/int/float result-source families. It shares the truthiness rules but
  returns true when any nonzero numeric or `true` element exists, treats zero,
  `false`, and element `na` as nonsatisfying, returns false for empty arrays,
  propagates upstream `na`, leaves the source unchanged, and retains the same
  invalid-type/arity, UDT, and terminal-continuation boundaries.
  The join slice adds terminal `.join(separator?)` to every concrete scalar
  array call result and to same-local/same-imported scalar-tree UDT results.
  It retains ordinary default/explicit/`na` separator behavior, scalar/color/
  UDT formatting, empty-string and upstream-`na` results, source non-mutation,
  and the 40960-character runtime limit; object/chart-point, invalid separator/
  arity, unresolved UDT identity, and terminal-continuation boundaries remain
  closed.
  The slice-window continuation adds `.slice(index_from, index_to)` to every
  concrete array call result across static, cross-namespace, matrix/map-
  derived, and local/imported function or method producers. It preserves
  scalar/object/`chart.point` kinds and same-local/same-imported UDT identity,
  returns the ordinary half-open shallow live parent window, mirrors writes in
  both directions, and may continue through the closed helper set. Empty and
  upstream-`na` receivers, negative/reversed/out-of-range bounds, nested
  slices, invalid type/arity, and the result-type-directed `matrix.mult`
  parser transition are fixture-backed.
  `array.slice` retains its live parent-window semantics while postfix `copy`
  snapshots the current window independently. `array.concat` still mutates and
  returns its first array; a following reader is non-mutating but does not make
  concat legal inside a UDF.
  The next terminal mutation slice adds top-level `.clear()` to every concrete
  array call result. It returns `void`, cannot continue, clears alias-returning
  concat and local/imported UDF or method results in place, deletes nested live
  slice windows from their parent, and mutates only fresh matrix/map/mult
  snapshots rather than their source collections. Empty/upstream-`na`, invalid
  arity, and UDF-side-effect rejection paths are fixture-backed; all other
  direct call-result mutation remains gated and public schemas are unchanged.
  The following terminal mutation slice adds top-level `.reverse()` across the
  same producer set. It returns `void`, cannot continue, reverses alias-
  returning concat/local/imported UDF or method results in place, reorders only
  a nested live slice's parent window, and mutates fresh matrix/map/mult
  snapshots without changing their sources. All supported array kinds, empty/
  upstream-`na`, invalid arity, and UDF-side-effect boundaries are fixture-
  backed; remaining direct mutations stay gated and public schemas are
  unchanged.
  The first matrix call-result mutation slice adds terminal
  `.set(row, column, value)` to every concrete matrix-result producer. It
  preserves float/int/bool/string/color element kinds, simple-int indexes,
  ordinary bounds and upstream-`na` behavior, returns `void`, and cannot
  continue. Local UDF or local user-method aliases update shared storage;
  namespace, bound-transform, imported-function, and imported-method results
  isolate writes in fresh matrices. Invalid type/arity, UDF-side-effect, and
  public-schema boundaries are fixture-backed; other matrix-result mutations
  remain gated.
  The next matrix call-result mutation slice adds terminal `.fill(value)` to
  the same concrete producer set. It preserves float/int/bool/string/color
  element kinds, replaces every cell, returns `void`, and cannot continue.
  Local UDF and local user-method aliases update shared storage; namespace,
  bound-transform, imported-function, and imported-method results isolate
  writes in fresh matrices. Empty/upstream-`na`, invalid type/arity, UDF-side-
  effect, and public-schema boundaries are fixture-backed; remaining matrix-
  result mutations stay gated.
  The following matrix mutation slice adds terminal `.reverse()` to the same
  producer set. It reverses the row-major cell sequence without changing
  shape, returns `void`, and cannot continue. Local UDF and local user-method
  aliases update shared storage; namespace, bound-transform, imported-function,
  and imported-method results isolate writes in fresh matrices. Empty/upstream-
  `na`, invalid arity, UDF-side-effect, and public-schema boundaries are
  fixture-backed; remaining matrix-result mutations stay gated.
  The next shape mutation slice adds terminal `.reshape(rows, columns)` to the
  same producer set. It preserves row-major cells, requires simple-int non-
  negative dimensions with unchanged element count, returns `void`, and cannot
  continue. Local aliases update shared shape; fresh producer results isolate
  the change. Upstream-`na` dimension evaluation, negative/`na` and count-
  mismatch errors, invalid type/arity, UDF-side-effect, and public-schema
  boundaries are fixture-backed; remaining matrix-result mutations stay gated.
  The next row-permutation slice adds terminal `.swap_rows(row1, row2)` to the
  same producer set. It requires two simple-int row indexes, swaps complete
  rows while preserving shape and element kind, returns `void`, and cannot
  continue. Local aliases update shared storage; fresh producer results isolate
  the write. Same-index no-op, bounds/`na` indexes, upstream-`na` argument
  evaluation, invalid type/arity, UDF-side-effect, and public-schema boundaries
  are fixture-backed; remaining matrix-result mutations stay gated.
  The symmetric column-permutation slice adds terminal
  `.swap_columns(column1, column2)` to the same producer set. It requires two
  simple-int column indexes, swaps complete columns while preserving shape and
  element kind, returns `void`, and cannot continue. Local aliases update
  shared storage; fresh producer results isolate the write. Same-index no-op,
  bounds/`na` indexes, upstream-`na` argument evaluation, invalid type/arity,
  UDF-side-effect, and public-schema boundaries are fixture-backed; remaining
  matrix-result mutations stay gated.
  The next row-shape mutation slice adds terminal `.remove_row(row)` to the
  same producer set. It requires one simple-int row index, removes the selected
  complete row, including from a zero-column matrix, while preserving column
  count and element kind, returns `void`, and cannot continue. Local aliases
  update shared shape; fresh producer
  results isolate the change. Bounds/`na` indexes, upstream-`na` argument
  evaluation, invalid type/arity, UDF-side-effect, and public-schema boundaries
  are fixture-backed; remaining matrix-result mutations stay gated.
  The symmetric column-shape mutation slice adds terminal
  `.remove_col(column)` to the same producer set. It requires one simple-int
  column index, removes the selected complete column, including from a zero-
  row matrix, while preserving row count and element kind, returns `void`, and
  cannot continue. Local aliases update shared shape; fresh producer results
  isolate the change. Bounds/`na` indexes, upstream-`na` argument evaluation,
  invalid type/arity, UDF-side-effect, and public-schema boundaries are
  fixture-backed; remaining matrix-result mutations stay gated.
  The next insertion slice adds terminal `.add_row(row, array_id)` to the same
  producer set. It requires one simple-int insertion index and an element-kind-
  matched array, copies the array into a complete new row, including for a
  zero-column matrix, while preserving column count and element kind, returns
  `void`, and cannot continue. Local aliases update shared shape; fresh
  producer results isolate the change. `0..=rows` bounds/`na`, array-size,
  cell-budget, upstream-`na`, invalid type/arity, UDF-side-effect, and public-
  schema boundaries are fixture-backed; remaining matrix-result mutations stay
  gated.
  The symmetric insertion slice adds terminal `.add_col(column, array_id)` to
  the same producer set. It requires one simple-int insertion index and an
  element-kind-matched array, copies the array into a complete new column,
  including for a zero-row matrix, while preserving row count and element
  kind, returns `void`, and cannot continue. Local aliases update shared shape;
  fresh producer results isolate the change. `0..=columns` bounds/`na`, array-
  size, cell-budget, upstream-`na`, invalid type/arity, UDF-side-effect, and
  public-schema boundaries are fixture-backed; remaining matrix-result
  mutations stay gated.
  The numeric ordering slice adds terminal `.sort(column?, order?)` to concrete
  float/int producers. It defaults to column 0 and ascending order, reorders
  complete rows with stable equal keys, places `na` last ascending and first
  descending, returns `void`, and cannot continue. Local aliases update shared
  storage; fresh producers isolate the change. Column bounds/`na`, unsupported-
  order, upstream-`na`, invalid type/arity, non-numeric receiver, UDF-side-
  effect, and public-schema boundaries are fixture-backed; remaining matrix-
  result mutations stay gated.

Remaining internal work:

- broader map storage and key/value type rules beyond the scalar key/value
  subset, whose helper calls, history, rollback, varip, and direct key/value
  `for...in` iteration are fixture-backed;
- matrix element/type families and collection interactions beyond the
  fixture-backed float/int/bool/string/color matrix subsets;
- UDT array behavior beyond the same-local and same-imported scalar-tree
  subsets, including mixed imported return identities, non-scalar imported
  returns, conflicting identities within one tuple slot, direct helpers beyond
  the `.size()`/`.get()`/`.first()`/`.last()`/`.copy()`/
  `.slice(index_from, index_to)`/`.concat(id2)`/
  `.includes(value)`/`.indexof(value)`/`.lastindexof(value)` plus bool/int/float-
  only `.every()`/`.some()`, scalar/same-identity scalar-tree UDT
  `.join(separator?)`, and numeric-only
  `.binary_search(value)`/`.binary_search_leftmost(value)`/
  `.binary_search_rightmost(value)`/`.abs()`/`.min(nth?)`/`.max(nth?)`/
  `.sum()`/`.avg()`/`.range()`/`.median()`/`.mode()`/`.percentile_nearest_rank(percentage)`/`.percentile_linear_interpolation(percentage)`/`.percentrank(index)`/`.covariance(id2, biased?)`/`.standardize()`/`.variance(biased?)`/`.stdev(biased?)` set, the int/float/string or exact-identity scalar-tree UDT `.sort_indices(order?, sort_field?)` call-result transformation, and
  mutation through unsupported UDF/method side-effect contexts;
- call-result receivers outside the qualified user-defined, unqualified plain
  local-UDF, exact built-in array-producing subsets, and the result-type-checked
  namespace-qualified `matrix.mult(...)` array/matrix paths plus the exact
  namespace `matrix.copy(...)`/`matrix.transpose(...)`/`matrix.submatrix(...)`/
  `matrix.kron(...)`/`matrix.diff(...)`/`matrix.pow(...)`/`matrix.inv(...)`/
  `matrix.pinv(...)`/`matrix.eigenvectors(...)`
  matrix paths plus exact `matrix.new<float|int|bool|string|color>` templates
  plus exact supported scalar `map.new<K,V>` templates and namespace
  `map.copy(existing)`,
  including bound matrix-result receivers other than exact matrix-receiver
  `values.copy()`/`values.transpose()`/`values.submatrix(...)`/
  `values.kron(other)`/`values.diff(other)`/`values.pow(power)`/
  `values.inv()`/`values.pinv()`/`values.eigenvectors()`/
  matrix-valued `values.mult(other)`, local/imported user-method matrix-result
  receivers without a concrete supported matrix kind, unregistered or
  unresolved user-function matrix-result receivers, unqualified local-UDF
  results without a concrete supported matrix kind,
  other matrix-returning calls, unsupported matrix/map templates, local or
  imported user-function/user-method map results without one concrete
  supported scalar template, and other map call-result receivers,
  other built-in namespaces or non-producer members, non-producer `array.*`
  calls, unsupported `array.new<T>` templates, non-array/non-UDT results,
  unknown/`na` results
  without a concrete supported type or identity, terminal producer readers
  other than the supported map-result `.keys()`/`.values()` array paths
  followed by another method, and collection mutation outside the admitted
  array-result set plus the closed terminal matrix-result mutations and map-
  result `.put(...)`. The existing bound-receiver
  `matrix_id.mult(array).size()` path is not part of that namespace exclusion;
- generic or bare `array` declarations beyond current fixture-backed element
  kinds;
- `for...in` iteration beyond the fixture-backed array, matrix-row, UDT-array,
  and scalar-map key-only/key/value subsets;
- richer aliasing, nested collection, history, and rollback rules;
- remaining non-scalar collection `varip` families and cross-feature
  interactions beyond the fixture-backed scalar maps, typed matrices, and
  same-local/same-imported scalar-tree UDT arrays.

Non-goals:

- treating `array.*` as broadly complete because many helpers exist;
- treating map syntax or storage as broadly complete beyond the fixture-backed
  scalar key/value subset;
- treating `matrix.*` as broadly complete because the five fixture-backed
  scalar element families already cover typed declarations, history, rollback,
  `varip`, row iteration, and many namespace/method helpers;
- host-visible collection output as part of the first internal collection slice.

Good next slice:

- add one missing array helper only for an already-supported scalar element
  family, add one missing negative fixture for a closed design gate, or start
  the semantic-only shared array element-kind refactor. The map design gate is
  closed in
  `docs/PURE_INTERNAL_MAP_DESIGN.md`; the matrix design gate is closed in
  `docs/PURE_INTERNAL_MATRIX_DESIGN.md`; the UDT array design gate is closed in
  `docs/PURE_INTERNAL_UDT_ARRAY_DESIGN.md`; the generic/bare array declaration
  design gate is closed in `docs/PURE_INTERNAL_ARRAY_DECLARATION_DESIGN.md`; the
  `for...in` design gate is closed in `docs/PURE_INTERNAL_FOR_IN_DESIGN.md`.
  Use those documents before widening `map.*`, any broader `matrix.*`, UDT
  array, declaration-widening, or `for...in` support.

## Direction 4: User-Defined Types, Methods, And Imports

Goal: expand structured data while preserving type identity, method dispatch, and
side-effect boundaries.

Current baseline:

- local scalar-tree UDT construction, reads, ordinary variables, and `var`
  persistence;
- local typed UDT declarations from fixture-backed same-UDT expressions;
- pure local UDT methods with receiver, local UDT parameter passthrough, nested
  method passthrough, ternary-expression alias passthrough, constructor helpers,
  and selected control-flow returns;
- exact-key source graph import subset for exported const expressions, pure
  exported functions, scalar-tree imported UDT constructors with direct and
  nested field reads, ordinary same-imported-UDT reassignment, and scalar-tree
  imported UDT typed declarations initialized or reassigned from the same
  imported identity, imported UDT ternary, `if`, `switch`, `while`, and `for`
  expression results from the same imported identity, plus imported UDT UDF
  direct, ternary-expression alias, final-`for in`, final-`while`,
  switch-expression alias, or nested parameter passthrough, direct or nested
  constructor-return results, and ordinary imported UDT `var` declarations,
  scalar-tree same-imported-identity `varip` declarations, and scalar-tree
  root-field replacement in top-level, branch, `for`-loop, `while`-loop, and
  UDF-local statement contexts, plus receiver-style or alias-qualified
  scalar-tree imported UDT method ternary-expression alias passthrough and
  alias-qualified imported method calls over direct same-imported receiver
  expressions, including direct constructor receiver expressions and
  named/reordered non-receiver arguments.

Remaining internal work:

- broader imported UDT identity flow across source graphs, including history
  and collections;
- broader imported methods beyond the scalar-tree imported UDT subset, with
  imported constructor and imported method call-result receiver chains covered
  by the current parser-normalized receiver-style path;
- UDT arrays beyond the fixture-backed same-local and same-imported scalar-tree
  subsets, and UDT history references beyond the current value shapes;
- broader `varip` UDT values beyond the typed/direct-constructor scalar-tree subset;
- side effects inside methods or UDFs, if ever accepted;
- clearer diagnostics for unsupported imported UDT and method side-effect
  boundaries.

Non-goals:

- cross-library UDT identity without a source-graph design;
- method side effects as a small syntax patch;
- recursive types or recursive functions without an explicit termination model.

Good next slice:

- one additional positive imported-method value-flow slice or a diagnostics
  fixture/message improvement for an unsupported UDT or method boundary.

The imported UDT identity design gate is closed in
`docs/PURE_INTERNAL_IMPORTED_UDT_DESIGN.md`. Use it before any positive imported
UDT constructor, value, assignment, or method support.

The UDT `varip` design gate is closed in
`docs/PURE_INTERNAL_UDT_VARIP_DESIGN.md`. The typed and direct-constructor
same-local scalar-tree subset is fixture-backed; use the gate before broadening
UDT `varip` value support.

## Direction 5: Pure Built-In Coverage

Goal: improve ordinary script compatibility through small pure built-in slices.

Current baseline:

- broad fixture-backed coverage across common `ta.*`, `math.*`, `str.*`, time,
  timeframe, session, syminfo, color, and cast helpers, including scalar-matrix
  `str.tostring` representations for float/int/bool/string elements and fixed
  mintick-aware plus K/M/B/T volume numeric formatting across scalars, arrays,
  and matrices, with predefined non-scaling percent formatting kept distinct
  from custom scaling `%` tokens and the grouped whole-number `str.format`
  percent preset, plus `str.match` default-ASCII predefined classes and word
  boundaries with global/scoped `(?U)` Unicode-aware switching and fixed
  Unicode `\h`/`\H` horizontal- and `\v`/`\V` vertical-whitespace classes plus
  CRLF-aware `\R` line-break matching and `\Q...\E` literal quoting, plus
  Java/Pine verbose `x` ASCII-only trivia, literal non-ASCII whitespace, and
  LF/CR/NEL/line-separator/paragraph-separator comment boundaries inside and
  outside character classes, the 13
  Java/Pine POSIX `\p`/`\P` classes with
  ASCII-default and global/scoped `(?U)` Unicode compatibility mappings,
  all 18 Java/Pine `javaLowerCase` through `javaMirrored` character method
  properties, including distinct Java/Unicode identifier sets, exact
  ignorable/space/whitespace/ISO-control boundaries, and bidi-mirrored
  membership, with exact case-sensitive names, `\p`/`\P` complements,
  `U`-independent membership, class nesting, quoted preservation, and
  case-insensitive Unicode closure,
  Unicode 16.0 `\p{InBlockName}`/`\p{Block=BlockName}` properties and `\P`
  complements,
  fixed-width `\uHHHH`, two-digit `\xNN`, braced `\x{...}`, one-to-three-digit
  `\0` octal, Unicode 16.0 `\N{CHARACTER NAME}` references with exact
  Java/Pine name boundaries, C0/C1 control names, and Java-generated CJK,
  Hangul, and Tangut algorithmic names, fixed `\e`, and one-scalar `\cX`
  control references, and
  single-search `\G` previous-match plus final-newline-aware `$`/`\Z` end
  anchors, leading literal `]` character-class atoms across negation, verbose
  trivia, and quoted regions, literal `~` class atoms protected from Rust's
  symmetric-difference syntax across ordinary, escaped, quoted, nested, range,
  and case-mode forms, Java/Pine backslash quoting for every non-alphanumeric
  ASCII literal across ordinary/class/verbose/nested/case contexts, raw class
  hyphens normalized with Java/Pine literal/range precedence instead of Rust's
  difference operator across leading/trailing, nested, quoted, escaped,
  intersection, verbose, case-mode, and invalid-range boundaries, plus raw
  class ampersands with Java/Pine single-literal, empty-pair, linear
  odd/even-run, nested, verbose, single-range/set, quoted, escaped, case-mode,
  and invalid-leading-pair boundaries instead of Rust's unconditional `&&` set
  parsing, including direct mixed-predicate or prior-intersection odd-run
  continuations with mutable Java BitClass revival and recursive RHS scope plus
  repeated empty pairs before later literals or non-empty intersections and
  range-start continuations that carry the same BitClass through later ranges,
  nested predicates, literals, and intersections, plus
  default-dot exclusion of Pine's full
  line-terminator set with
  global/scoped `(?s)` and `(?-s)` restoration, plus global/scoped Java/Pine
  `(?d)` UNIX-lines mode with LF-only dot/anchor semantics, `(?-d)` restoration,
  dotall precedence, and `\R` independence,
  and ASCII-default `(?i)` versus independent lowercase-`u` Unicode case
  folding, with `U` implying `u`, separate `-u`/`-U` restoration, preserved
  ASCII predefined/POSIX class boundaries, and character-class
  negation/intersection ordering plus exact block membership, on the
  linear-time regex path;
- calendar-aware UTC `time`/`time_close` and `timeframe.change` week and month
  groups alongside fixed intraday/day buckets;
- IANA timezone and DST-aware calendar component and `str.format_time` calls,
  including timestamp-specific short timezone abbreviations and shared
  doubled-apostrophe literals, `na`-to-epoch timestamps, `1..5` week-of-month
  and `0..11` 12-hour tokens, and complete millisecond-width formatting,
  plus explicit `time`/`time_close` session filtering and clipping, while
  exchange timezone defaults remain outside the fixed runtime metadata model;
- numeric and const-dateString `timestamp` IANA local-time conversion with
  explicit overlap and DST gap resolution;
- many edge-case fixtures for numeric rolling windows, `na`, tuple returns, and
  supported qualifier families.

Remaining internal work:

- missing high-use pure `ta.*` helpers;
- more `math.*` and `str.*` edge cases;
- more time/session/timezone helper semantics that do not require exchange data;
- tighter diagnostics for unsupported argument families;
- qualifier alignment between `docs/BUILTIN_SIGNATURES.md` and code acceptors.

Non-goals:

- built-ins that require remote data, account state, chart UI, or services;
- approximate behavior without fixture evidence;
- broad claims such as "all `ta.*`" or "all string formatting".

Good next slice:

- choose one high-use pure built-in gap from real fixtures, implement the smallest
  documented subset, and update only the corresponding conformance row.

## Direction 6: Strategy Broker And Account Semantics

Goal: continue strategy compatibility only where the internal broker model can
prove deterministic state transitions.

Current baseline:

- long-only broker with Stage 13 fixture-backed multi-entry ledger and positive
  integer `pyramiding` subset;
- supported long market, limit, stop, and stop-limit entries;
- supported `strategy.close`, `strategy.close_all`, `strategy.cancel`, and
  `strategy.cancel_all` subsets;
- broad supported `strategy.exit` subset across single triggers, brackets,
  trailing exits, partial quantities, reservations, omitted-quantity replacement,
  and long-only multi-entry allocation;
- script-visible strategy variables and trade namespace subsets;
- supported cash-per-contract, cash-per-order, and percent commission modes,
  fixed-tick slippage, fixed-tick limit verification, cash default sizing,
  percent-of-equity default sizing, explicit `close_entries_rule="FIFO"`,
  fixture-backed id-specific long-only `close_entries_rule="ANY"`, and selected
  long-margin behavior.

Remaining internal work:

- short exposure;
- automatic long/short reversal;
- `strategy.order()` behavior beyond the fixture-backed long
  market/limit/stop/stop-limit add-or-increase subset and explicit-quantity
  reduce-only market-short subset;
- broader `close_entries_rule="ANY"` behavior beyond fixture-backed
  id-specific long-only close/exit allocation;
- custom OCA behavior across order families;
- `process_orders_on_close`, `calc_on_order_fills`, `calc_on_every_tick`, and bar
  magnifier style timing;
- `margin_short`, richer account constraints, currency conversion, broader
  short-side, rounded, and currency-aware `strategy.margin_liquidation_price`
  behavior;
- remaining strategy information variables and trade namespace fields;
- `strategy.risk.*` rules after broker/account foundations are stronger.

Non-goals:

- reopening broad broker foundations immediately after Stage 13;
- accepting new `strategy()` properties as inert no-ops;
- public pending-order, reservation, or open-trade ledgers before a schema design;
- real broker connectivity.

Good next slice:

- a narrow no-op, diagnostic, accounting, or script-visible field slice that keeps
  the current public strategy result shape unchanged. Short/reversal and generic
  order work should start with a design gate, not an implementation patch.

The strategy short/reversal design gate is closed in
`docs/PURE_INTERNAL_STRATEGY_SHORT_REVERSAL_DESIGN.md`. Use it before any
positive `strategy.short` entry, short exposure, or automatic reversal support.

The generic strategy order design gate is closed in
`docs/PURE_INTERNAL_STRATEGY_ORDER_DESIGN.md`. Use it before any positive
`strategy.order()` support beyond the current fixture-backed subset, generic
order netting, or generic-order OCA work.

The strategy close-entries-rule reference is in
`docs/PURE_INTERNAL_STRATEGY_CLOSE_ENTRIES_RULE_DESIGN.md`. Use it before any
non-default close allocation behavior.

The strategy OCA design gate is closed in
`docs/PURE_INTERNAL_STRATEGY_OCA_DESIGN.md`. Use it before any positive
`oca_name`, `strategy.oca.*`, or cross-order-family OCA behavior.

The strategy execution-timing design gate is closed in
`docs/PURE_INTERNAL_STRATEGY_EXECUTION_TIMING_DESIGN.md`. Use it before any
positive `process_orders_on_close`, `calc_on_order_fills`,
`calc_on_every_tick`, bar magnifier, or standard-OHLC fill timing support.

The strategy margin-short/account design gate is closed in
`docs/PURE_INTERNAL_STRATEGY_MARGIN_SHORT_ACCOUNT_DESIGN.md`. Use it before any
positive `margin_short` runtime behavior, broader/short/rounded/currency-aware
`strategy.margin_liquidation_price`, symbol precision rounding, or
currency-conversion account behavior.

The strategy risk-rule design gate is closed in
`docs/PURE_INTERNAL_STRATEGY_RISK_DESIGN.md`. Use it before any positive
`strategy.risk.*` support, including entry-direction, drawdown/loss, position
size, or filled-order-count risk rules.

## Direction 7: Runtime Guardrails And Verification

Goal: keep the runtime maintainable as compatibility widens.

Current baseline:

- conformance matrix guards;
- golden runtime snapshots;
- an explicit public-host golden manifest: the current gate discovers all 695
  registered ordinary CLI runtime snapshots and requires representative paired
  Python/WASM assertions for 418 named snapshots, rejects silent single-host
  assertions, and currently has no reasoned single-host exceptions; the smaller
  required set is a deliberate contract policy, not an undiscovered-registry
  shortcut;
- strict public `schemaVersion` checks;
- structure guardrail;
- runtime profiles for history and callsite state;
- a real wasm32 module build, generated JavaScript bindings, and Node.js smoke
  covering analysis, execution, compiled execution, combined host inputs, and
  JavaScript exceptions;
- full release gate in `scripts/verify.sh`.

Remaining internal work:

- more profile fields when new storage families land;
- focused stress fixtures for loops, collection growth, UDF call depth, and
  history retention;
- clearer runtime errors for storage and guardrail limits;
- periodic audits to keep roadmap, conformance, snapshots, and docs aligned.

Non-goals:

- weakening guardrails to accept broader scripts;
- using roadmap text as a substitute for fixture-backed behavior;
- updating snapshots without rerunning the non-update verification path.

Good next slice:

- add a guardrail or profile assertion only when it protects an existing or
  immediately upcoming runtime behavior slice.

## Recommended Order

1. Small pure built-in or diagnostic slices from real fixture gaps.
2. Type/qualifier/history hardening that unlocks multiple later built-ins.
3. Collection design gates for map, matrix, UDT arrays, generic declarations,
   and iteration before runtime support.
4. UDT/import identity design before imported UDTs or imported methods.
5. Conservative strategy maintenance slices that preserve public output shape.
6. Large strategy broker work only after a fresh design gate for short/reversal,
   generic order, OCA, or account-model behavior.
7. Runtime guardrail work whenever a new semantic family would otherwise grow
   state or execution cost without visibility.

Avoid opening request, drawing, alert delivery, or host-integration work from this
roadmap. Those belong in the broader platform plans unless the change is purely a
semantic analyzer or runtime-core boundary fixture.

## Completion Gate

Before any pure-internal slice is closed:

```text
git diff --check
scripts/verify.sh
```

The closeout note or audit must state:

- what changed;
- what remains unsupported;
- which fixtures prove the new boundary;
- whether public output shape changed;
- which docs and conformance rows were updated.
