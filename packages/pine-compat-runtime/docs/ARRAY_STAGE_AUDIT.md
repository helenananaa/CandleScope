# Array Stage Audit

This audit closes the current scalar typed-array expansion pass. It records what
the runtime now claims, what remains intentionally out of scope, and what should
happen before moving to another language phase.

Primary references:

- TradingView Pine Script arrays documentation:
  <https://www.tradingview.com/pine-script-docs/language/arrays/>
- TradingView Pine Script methods documentation:
  <https://www.tradingview.com/pine-script-docs/language/methods/>
- Local conformance matrix source:
  `tests/fixtures/conformance.tsv`

## Stage Verdict

Stage 3 arrays are complete for the current fixture-backed scalar subset. Later
compatibility slices added fixture-backed `array.new_label` label-id arrays,
`array.new_line` line-id arrays, `array.new_linefill` linefill-id arrays,
`array.new_polyline` polyline-id arrays, `array.new_box` box-id arrays,
`array.new_table` table-id arrays, same-local and same-imported scalar-tree UDT
arrays, and
official `array.new<type>` constructor syntax for the supported scalar,
drawing-object, chart.point, and same-identity UDT element types on top of that
scalar baseline without opening general object array families.

The project should keep `array.*` marked `partial`, not `supported`, because the
current implementation deliberately excludes general generic arrays, object
families outside the fixture-backed drawing ids, non-scalar or recursive UDT
arrays, arrays of collections, `varip` value families outside the fixture-backed
subsets, richer array-history aliasing semantics, and several helper/type
combinations.

The next implementation work should not continue adding random array helpers.
Future array work should be chosen from the explicit gap list below and should
usually be paired with a larger language phase, such as object systems, user
types, or history/series semantics.

## Implemented Subset

Runtime model:

- Array values are runtime-owned ids stored in `PineValue::Array`.
- Assignment and UDF argument binding pass array ids by reference.
- `array.copy` is the explicit boundary for creating an independent array id.
- Non-`var` declarations allocate when they execute.
- `var` declarations preserve array ids and backing storage across bars.
- Realtime forming-bar rollback covers array state.
- Scalar typed-array ids referenced by supported `varip` declarations preserve
  their backing contents across repeated forming updates.
- Runtime array growth is guarded by the 100,000 element limit.

Element kinds:

- `float`
- `int`
- `bool`
- `string`
- `color`
- `label` ids
- `line` ids
- `linefill` ids
- `polyline` ids
- `box` ids
- `table` ids
- `chart.point`
- same-local scalar-field UDT values

Creation and inference:

- `array.new_float` / `array.new<float>`
- `array.new_int` / `array.new<int>`
- `array.new_bool` / `array.new<bool>`
- `array.new_string` / `array.new<string>`
- `array.new_color` / `array.new<color>`
- `array.new_label` / `array.new<label>`
- `array.new_line` / `array.new<line>`
- `array.new_linefill` / `array.new<linefill>`
- `array.new_polyline` / `array.new<polyline>`
- `array.new_box` / `array.new<box>`
- `array.new_table` / `array.new<table>`
- `array.new<chart.point>`
- `array.new<T>` for same-local scalar-field UDTs
- `array.from`

General operations:

- `array.size`
- `array.get`
- `array.set`
- `array.insert`
- `array.push`
- `array.pop`
- `array.remove`
- `array.shift`
- `array.unshift`
- `array.fill`
- `array.first`
- `array.last`
- `array.copy`
- `array.slice`
- `array.concat`
- `array.clear`

Search, predicate, and ordering helpers:

- `array.includes`
- `array.indexof`
- `array.lastindexof`
- `array.every`
- `array.some`
- `array.binary_search`
- `array.binary_search_leftmost`
- `array.binary_search_rightmost`
- `array.sort`
- `array.sort_indices`
- `array.reverse`

Numeric helpers:

- `array.abs`
- `array.min`
- `array.max`
- `array.sum`
- `array.avg`
- `array.range`
- `array.median`
- `array.mode`
- `array.percentile_nearest_rank`
- `array.percentile_linear_interpolation`
- `array.percentrank`
- `array.covariance`
- `array.standardize`
- `array.variance`
- `array.stdev`

String conversion:

- `array.join`

Method syntax:

- Supported array functions lower to the same `array.*` runtime calls where
  listed in `tests/fixtures/conformance.tsv`.
- Method syntax is supported for the scalar typed-array subset and line-id
  arrays where listed in `tests/fixtures/conformance.tsv`.

## Known Gaps

These gaps are intentional. Do not mark `array.*` broadly supported until they
are designed and fixture-backed.

Generic arrays:

- `array.new<type>()` is supported only for the scalar, drawing-object,
  chart.point, and same-local or same-imported scalar-tree UDT element kinds
  listed above.
- Type-template array declarations such as `array<float>` are not a general
  parser or semantic feature outside the current fixture-backed element kinds.
- `array.from` only infers the scalar, chart.point, drawing ids, and same-local
  or same-imported scalar-tree UDT values listed above.

Reference and object arrays:

- Arrays of object ids outside the listed drawing families are not supported.
  Label-id, line-id, linefill-id, polyline-id, box-id, and table-id arrays are
  the fixture-backed drawing-object array families.
- Additional drawing-object arrays should wait for explicit object id lifetime,
  rollback, and host-output semantics.

User-defined type arrays:

- Same-local and same-imported scalar-tree UDT arrays have fixture-backed
  construction, declarations, history, `varip`, structural search, and
  `sort_field` subsets.
- Non-scalar, recursive, nested-collection, and side-effecting UDT-array forms
  remain unsupported.

Maps and matrices:

- `matrix.*` and `map.*` remain out of scope for this historical array stage;
  later dedicated design gates now own their partial storage, type, history,
  rollback, and `varip` subsets.

`varip`:

- Scalar typed-array ids for `float`, `int`, `bool`, `string`, and `color`
  declarations are fixture-backed for historical var-like execution and
  realtime intrabar persistence.
- Drawing-id arrays, generic/non-scalar UDT arrays, tuples, and other value
  families remain unsupported for `varip` until their realtime handoff and
  rollback rules are designed.

History and snapshots:

- Scalar array, scalar slice, label-array, label-slice, line-array,
  line-slice, box-array, box-slice, linefill-array, linefill-slice,
  polyline-array, polyline-slice, table-array, table-slice, chart.point-array,
  chart.point-slice, and same-local scalar-tree UDT-array variable history
  snapshots are
  fixture-backed for the official
  `previous = a[1]; na(previous) ? na : previous.get(0)` read path, with
  scalar-array, scalar-slice, label-array, label-slice, line-array, line-slice,
  box-array, box-slice, linefill-array, linefill-slice, polyline-array,
  polyline-slice, table-array, table-slice, chart.point-array,
  chart.point-slice, and same-local scalar-tree UDT-array first-bar
  `na(previous)` predicate outputs, plus scalar array/slice, label-array/slice,
  line-array/slice, box-array/slice, linefill-array/slice,
  polyline-array/slice, table-array/slice, chart.point-array/slice, and
  same-local scalar-tree UDT-array dynamic `na` offset predicates: runtime
  commits retained array values as independent snapshots and returns a fresh
  copy on history reads.
- Remaining array history behavior still needs design for broader collection
  families and richer mutation/aliasing semantics.

Slice semantics:

- `array.slice` returns a same-kind shallow window over the parent array.
- Reads and writes through the slice mirror the parent window.
- Inserting through the slice widens the window and inserts into the parent.
- Later parent mutations that move the window outside parent bounds are runtime
  errors when the slice is accessed.
- Keep this row partial until remaining array history edge cases, future
  element families, and any remaining nested/advanced aliasing cases are
  fixture-backed.

Loops over arrays:

- Statement-form `for...in` array iteration is fixture-backed for scalar
  `array<int>`, `array<float>`, `array<bool>`, `array<string>`, and
  `array<color>` values with initial-length iteration, current-storage reads,
  empty-array and typed-`na` zero iteration, append non-extension, alias
  mutation visibility, shrink-to-out-of-bounds runtime errors, `break`/
  `continue`, loop-body local declarations, stateful built-in callsites,
  ordinary `var` scalar-array forming-bar rollback, and scalar typed-array
  `varip` forming-bar interaction. The current scalar-array `for...in` runtime
  fixtures also have explicit incremental append execution parity with full historical
  recomputation.
- Non-array iterables, object, `array<chart.point>`, UDT arrays, map, matrix,
  index/value, expression-form, and non-scalar `varip` interaction variants
  remain future loop hardening work.

Advanced sorting:

- `array.sort` and `array.sort_indices` support scalar `float`, `int`, and
  `string` arrays with `order.ascending` and `order.descending`.
- Runtime fixtures cover `array.sort` and `array.reverse` calls in branch and
  loop bodies for scalar arrays.
- `sort_field` for UDT arrays is not supported.
- Sorting object arrays is not supported.

Unsupported helpers and variants:

- Any `array.*` function absent from `tests/fixtures/conformance.tsv` remains
  unsupported.
- Any supported helper called on unsupported element kinds should remain a
  semantic error, not a runtime approximation.

## Recommended Next Phase

The best next step is to leave Stage 3 arrays and choose one of these tracks:

1. Phase C, history and series semantics.
   This is the most foundational path. It would address dynamic history
   offsets, first-bar behavior, qualifier propagation, and array history
   boundaries.

2. Phase D, built-in coverage expansion.
   This is the highest user-visible compatibility path. Start with pure
   built-ins, then stateful `ta.*`, then output options that affect public
   result schemas.

3. Phase A residual hardening.
   If stability is preferred over coverage, add more real-script loop and
   branch interaction fixtures before broadening the language.

Do not start matrices, maps, drawing objects, `request.*`, or strategy runtime
without a dedicated design document. Each of those introduces a new runtime
storage or host integration model.

## Array Follow-Up Backlog

Only take these when they are explicitly selected as the next work item:

- Design remaining generic `array.new<type>()` parsing and type checking for
  imported/nested-field UDTs, map/matrix, or other future element families.
- Design remaining array history aliasing behavior, including unsupported
  object or collection slice snapshots and mutation of historical copies.
- Extend `for...in` beyond the current scalar-array statement subset only after
  the relevant collection and realtime interaction rules are fixture-backed.
- Add additional object arrays after their object ids and lifetimes exist.
- Add UDT arrays and `sort_field` after user-defined types exist.
- Expand diagnostics for unsupported generic/object/UDT array syntax once those
  syntaxes are parsed precisely.

## Exit Criteria Met For Current Subset

- Syntax, semantic analysis, runtime behavior, conformance metadata, and docs
  agree for every claimed array feature.
- Historical and incremental fixture execution match for runtime fixtures.
- Realtime rollback covers array state.
- UDF side-effect boundaries reject array mutation inside functions.
- Unsupported collection families remain diagnostic-only.
- `array.*` remains `partial` in conformance metadata.
