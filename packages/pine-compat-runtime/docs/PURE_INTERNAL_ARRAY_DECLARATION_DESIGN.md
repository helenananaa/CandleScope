# Pure Internal Array Declaration Design Gate

Status: closed as a documentation-only design gate. This slice does not change
syntax acceptance, semantic analysis, runtime behavior, conformance status,
snapshots, or public output.

This document defines the internal path for future generic and bare array
declaration support. It is scoped to interpreter internals only: parser shape,
semantic type identity, HIR lowering, runtime array storage, history, rollback,
and conformance. It does not cover host UI, rendering, external data, public
serialization of array values, or any new host contract.

## Current Boundary

Array declarations are intentionally fixture-backed, not generally generic.

Current evidence:

- `docs/CONFORMANCE.md` and `tests/fixtures/conformance.tsv` mark typed
  declarations as partial. Supported array declarations are limited to scalar
  `array<int>`, `array<float>`, `array<bool>`, `array<string>`,
  `array<color>`, object-id `array<label>`, `array<line>`,
  `array<linefill>`, `array<polyline>`, `array<box>`, `array<table>`,
  `array<chart.point>`, same-local scalar-tree UDT `array<T>`, and equivalent
  `type[]` aliases.
- `docs/ARRAY_STAGE_AUDIT.md` records that type-template declarations such as
  `array<float>` are not a general parser or semantic feature outside the
  current fixture-backed element kinds.
- `crates/pine-syntax/src/ast.rs` stores `StmtKind::Decl.declared_type` as
  `Option<DeclaredType>`, and `crates/pine-syntax/src/parser.rs` parses
  `array<T>` and `T[]` declarations through that representation while preserving
  current canonical names for diagnostics and compatibility reporting.
- `crates/pine-ir/src/lib.rs` maps only a fixed allowlist of array element
  `ValueKind`s into concrete array `ValueKind`s and maps concrete array
  `ValueKind`s back to their element `ValueKind`s for element-return helpers.
  `array.from` element-kind inference and final array-kind conversion,
  `array.new_*`/`array.new<chart.point>` return signatures,
  `array.get`/`array.pop`/`array.shift`/`array.first`/
  `array.last` element returns, numeric array helper returns, array value
  argument compatibility checks, generic/scalar/truth/order array accept and
  receiver checks, scalar typed-array `varip` allowlist,
  typed-declaration diagnostic names, and
  `crates/pine-sema/src/analyzer/statements.rs` all use shared semantic mapping
  for currently supported element families.
- `tests/fixtures/runtime/array_typed_declarations.pine`,
  `tests/fixtures/runtime/array_type_alias_declarations.pine`, and
  `tests/fixtures/runtime/user_type_array_typed_declarations.pine` cover
  accepted scalar, object-id, chart-point, and same-local scalar-tree UDT array
  declaration forms.
- `tests/fixtures/sema/varip_chart_point_array.pine` covers the accepted
  chart-point typed-array `varip` declaration subset after realtime handoff
  rules were proven for runtime-owned `chart.point` arrays.
- `tests/fixtures/sema/unsupported_varip_drawing_array.pine` keeps drawing-id
  typed-array `varip` declarations rejected under the same boundary.
- `tests/fixtures/sema/unsupported_array_typed_decl.pine`,
  `tests/fixtures/sema/unsupported_var_array_typed_decl.pine`,
  `tests/fixtures/sema/unsupported_array_na_typed_decl.pine`,
  `tests/fixtures/sema/unsupported_array_from_typed_decl.pine`,
  `tests/fixtures/sema/unsupported_array_typed_decl_initial.pine`,
  `tests/fixtures/sema/supported_user_type_array_decl.pine`,
  `tests/fixtures/sema/supported_user_type_array_alias_decl.pine`, and
  `tests/fixtures/sema/unsupported_user_type_array_from_decl.pine` keep bare,
  `var` bare, bare-`na`, initializer-inferred bare, mismatched scalar-array
  initializer, accepted scalar-tree UDT, and mismatched UDT array declaration
  forms fixture-backed.
  `tests/fixtures/sema/supported_user_type_array_varip_decl.pine` covers
  same-local scalar-tree UDT array `varip` declarations after realtime handoff
  rules were fixture-backed, while
  `tests/fixtures/sema/supported_user_type_array_varip_nested_decl.pine` keeps
  scalar-tree nested UDT array `varip` declarations accepted. The explicit
  `tests/fixtures/sema/unsupported_array_map_typed_decl.pine` and
  `tests/fixtures/sema/unsupported_array_matrix_typed_decl.pine` fixtures keep
  unsupported template elements rejected without adding map or matrix support.
  `tests/fixtures/sema/unsupported_map_typed_decl.pine` keeps bare map typed
  declarations rejected until map storage and key/value typing are designed.
  `tests/fixtures/runtime/matrix_typed_declarations.pine` covers
  `matrix<float>` and `matrix<int>` typed declarations, while
  `tests/fixtures/sema/unsupported_matrix_typed_decl.pine` keeps bare
  matrix typed declarations rejected and
  `tests/fixtures/sema/unsupported_matrix_int_typed_decl.pine` keeps
  cross-element matrix typed declaration initialization rejected.
  `tests/fixtures/sema/unsupported_array_nested_typed_decl.pine` keeps array
  elements that would require nested collection semantics rejected, and
  `tests/fixtures/sema/unsupported_array_tuple_typed_decl.pine` keeps tuple
  elements rejected without adding tuple array semantics.
  `tests/fixtures/sema/unsupported_array_strategy_typed_decl.pine` keeps
  strategy-like record elements rejected without adding strategy record arrays.

Do not widen typed array declarations until a runtime slice implements the
behavior and updates fixtures, conformance, snapshots, and docs together.

## Target Shape

The next array declaration model should make element identity explicit instead
of relying on ad hoc declared-type strings.

Target properties:

- one semantic element-kind registry maps declaration syntax, constructor
  syntax, `array.from` inference, helper signatures, history snapshots, and
  diagnostics;
- `array<T>` and `T[]` are equivalent spellings only after they resolve to the
  same supported element kind;
- an array variable has exactly one element kind for assignment compatibility;
- `na` initialization is allowed only when the declaration supplies a concrete
  element kind;
- assignment from `array.new_*`, `array.new<T>`, `array.from`, `array.copy`,
  slices, and history snapshots must preserve or prove compatible element kind;
- rejected element kinds fail in semantic analysis with precise diagnostics;
- runtime array ids remain the storage identity and are still passed by
  reference.

This is still not a host-visible generic collection system. It is an internal
type-identity cleanup that makes future collection families easier to add.

## Element Kind Policy

Already fixture-backed element kinds:

- `int`
- `float`
- `bool`
- `string`
- `color`
- `label`
- `line`
- `linefill`
- `polyline`
- `box`
- `table`
- `chart.point`

Deferred element kinds:

- imported or non-scalar-field user-defined types;
- maps;
- matrices;
- arrays of arrays;
- tuples;
- strategy/order/trade records;
- imported UDTs or imported opaque values.

Adding one deferred element kind should be a separate positive support slice
with fixtures for declaration, construction, assignment, mutation, copy,
history, rollback, and unsupported helpers.

## Bare `array` Policy

Bare `array` declarations must remain unsupported until the analyzer has a clear
inference and mutation model.

Do not accept these forms in the first positive declaration cleanup:

- `array values = na`
- `array values = array.new_float()`
- `var array values = array.new_float()`
- `array values = array.from(close)`
- reassignment of a bare array variable from arrays of different element kinds.

Rationale:

- `na` carries no element kind;
- initializer-only inference makes later reassignment compatibility harder to
  explain;
- `var` and rollback need a stable element kind before the first runtime write;
- bare `array` would otherwise become a weak dynamic type that bypasses the
  conformance matrix.

If bare `array` is ever accepted, it should be a later slice with exactly one
inference rule, for example "initializer must be a non-`na` array expression and
the declaration is rewritten to that concrete element kind." That rule must
still reject later incompatible reassignment.

## Parser And Semantic Model

Parser cleanup should stay narrow:

- continue parsing `array<T>` and `T[]` declaration spellings;
- normalize whitespace and namespace forms to a canonical element type;
- do not parse nested declarations such as `array<array<float>>` until nested
  arrays are designed;
- do not parse `map<K,V>` or `matrix<T>` as arrays;
- preserve the declared type span for precise diagnostics.

Semantic cleanup should introduce an internal representation such as:

```text
ArrayElementKind::Float
ArrayElementKind::Int
ArrayElementKind::Bool
ArrayElementKind::String
ArrayElementKind::Color
ArrayElementKind::Label
ArrayElementKind::Line
ArrayElementKind::LineFill
ArrayElementKind::Polyline
ArrayElementKind::Box
ArrayElementKind::Table
ArrayElementKind::ChartPoint
```

This representation should be shared by declaration typing and array built-in
signature resolution. It should not be inferred from display strings after
parsing.

## Assignment And Inference

Initial policy:

- a declared `array<T>` or `T[]` accepts `na`;
- a declared `array<T>` or `T[]` accepts an array expression of the same element
  kind;
- `array<int>` does not accept `array<float>` even though int values can promote
  into float arrays in `array.from`;
- `array<float>` may accept int-valued elements only through constructors or
  helpers that already normalize those elements into a float array;
- object-id arrays accept only their matching id family or `na` elements;
- chart-point arrays accept only chart-point values or `na` elements;
- assignment compatibility should use element kind, not user-facing type text.

`array.from` should remain inference-based for expressions, but its result must
be a concrete element kind before assignment. All-`na` argument lists and
array-valued arguments remain rejected.

## History And Realtime

First cleanup policy:

- no new history families are introduced by declaration cleanup alone;
- supported array history snapshots keep the existing element-kind list;
- `var` declarations preserve array ids and backing storage exactly as today;
- `varip` remains limited to fixture-backed typed-array element families with
  explicit realtime handoff rules, including scalar arrays, chart-point arrays,
  and same-local scalar-tree UDT arrays;
- drawing-id, generic, bare-array, map-element, matrix-element, nested-array, and
  other unsupported typed-array `varip` declarations remain rejected until
  realtime handoff rules are explicit.

Later policy:

- adding a new element kind requires explicit historical snapshot behavior;
- nested array or collection element kinds require deep-copy policy before
  history support;
- `varip` support for any non-scalar element kind needs realtime fixtures for
  repeated forming updates, aliasing, and `array.copy` boundaries.

## Diagnostics

Current diagnostics should stay stable before positive support:

- bare array declaration: `typed declaration \`array\` is not supported`;
- unsupported template element: `typed declaration \`array<T>\` is not
  supported`;
- incompatible initializer: `cannot initialize \`name\` of type array<T> with
  ...`.

When support widens, unsupported variants should fail with precise diagnostics:

- unsupported array element type;
- nested array element type without nested-array support;
- generic declaration missing a concrete element kind;
- incompatible declaration initializer;
- incompatible reassignment;
- unsupported `varip` array element kind;
- unsupported array history element kind;
- unsupported helper for the declared element kind.

## Slice Order

Recommended future slices:

1. Diagnostic cleanup: add missing negative fixtures for unsupported template
   element types without accepting new runtime behavior.
2. Assignment/helper cleanup: make declaration assignment and array helpers use
   the same element-kind registry where they still depend on array kind matches.
3. Optional bare-array inference design slice, still with negative fixtures
   until the exact rule is accepted.
4. Additional positive element kinds only after their storage, helper, history,
   and rollback rules are documented.
5. Any `varip` widening only after realtime handoff and aliasing fixtures are in
   place.

## Completion Gate For Future Positive Support

Any positive array declaration widening must include:

- semantic fixtures for accepted and rejected declaration forms;
- runtime fixtures for construction, assignment, reassignment, and helper use;
- history and realtime rollback tests when the element kind has state timing;
- `varip` realtime tests for any newly supported `varip` element kind;
- matrix snapshot updates if the public compatibility inventory changes;
- synchronized `tests/fixtures/conformance.tsv`, `docs/CONFORMANCE.md`,
  `docs/BUILTIN_SIGNATURES.md`, release notes, and this design document;
- `git diff --check`;
- `scripts/verify.sh`.

## Closed Slice Result

This design gate closes only the planning prerequisite. A later cleanup slice
also replaced the declaration AST field with `Option<DeclaredType>` while
preserving the supported runtime subset, and a later positive slice added
same-local scalar-tree UDT `array<T>` and `T[]` declarations. Generic and bare
array declaration behavior remains limited to the current fixture-backed
accepted and rejected forms until a later slice implements syntax, analysis,
runtime behavior, and conformance updates together.
