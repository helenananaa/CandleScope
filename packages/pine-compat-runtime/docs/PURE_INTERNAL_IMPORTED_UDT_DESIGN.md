# Pure Internal Imported UDT Identity Design Gate

Status: closed design gate, maintained as the current imported UDT support
boundary. The runtime-backed scalar-field imported constructor, direct
field-read, ordinary same-imported-UDT reassignment, explicit typed
declaration, scalar-field typed array declaration, selected
same-imported-identity control-expression results, and direct or nested UDF
passthrough/constructor-return subset, ordinary `var` persistence,
scalar-field same-imported-identity `varip` persistence, scalar-field
same-imported-identity array `varip` persistence, and scalar-field
mutation in top-level, branch, `for`-loop, `while`-loop, and UDF-local
statement contexts are implemented. Broader imported UDT flow remains gated
below.

This document defines the internal path for future imported user-defined type
identity across source graphs. It is scoped to parser-visible qualified names,
semantic type identity, module export tables, HIR lowering, runtime UDT values,
method dispatch, fixtures, and conformance. It does not cover remote library
lookup, registry resolution, filesystem access inside core crates, host UI, or
public serialization changes.

## Current Boundary

The current import subset supports host-provided exact-key imports with aliases,
exported const expressions, pure exported functions, scalar-tree imported UDT
constructors with direct and nested field reads, and ordinary same-imported-UDT
reassignment, plus scalar-tree imported UDT typed declarations initialized or
reassigned from the same imported identity, same-imported-identity ternary,
`if`, `switch`, `while`, and `for` expression results, direct or nested imported
UDT UDF parameter passthrough returns, direct or nested constructor-return UDFs,
and ordinary imported UDT `var` declarations, plus scalar-tree imported UDT
`varip` declarations initialized from `na`, same-imported constructors, or direct
constructor inference, plus same-imported scalar-tree UDT
`array<lib.Type>`/`lib.Type[]` declarations, including `varip` declarations
initialized through `array.from(...)` or `array.new<lib.Type>(...)` that retain
their backing store across forming updates, plus scalar-tree root-field replacement in top-level, branch,
`for`-loop, `while`-loop, UDF-local statement contexts, and method-local
statement contexts outside receiver/parameter/global side-effect boundaries,
plus receiver-style pure
methods on scalar-tree imported UDT receivers, including alias-qualified
`lib.method(receiver, ...)` calls when the first argument is a same-identity
imported UDT receiver and the method parameters stay inside the
scalar/imported-UDT subset, including direct same-identity, block-local alias,
ternary-expression alias, final-if alias, final-for alias, final-while alias,
switch-expression alias, nested-method passthrough plus direct, nested, or ternary constructor returns,
method-local scalar-tree root-field replacement, scalar-tree imported UDT value
history, imported scalar-tree UDT array history snapshots, and `array.from`
construction with direct size/get/first/last, set replacement field reads, push
append field reads, unshift prepend field reads, insert
insertion field reads, fill replacement field reads, join positional
stringification, includes/indexof/lastindexof structural equality search,
sort/sort_indices by int/float/string sort_field, pop/remove/shift return field
reads, clear-size reset, copy independent field reads, reverse reordered field
reads, slice window field reads, concat appended field reads, and
statement/expression/index-value for-in value-copy field reads. Imported pure
exported UDFs and imported user methods may also return same-imported scalar-tree
UDT arrays through direct or block-alias paths, copy/new/from allocation, private
nested calls, typed methods with named/reordered arguments, and final control
flow. Imported type positions are rewritten for the active alias and
source-aware metadata isolates two aliases of the same physical library.
Qualified user-defined UDF/method results and unqualified plain root-local UDF
results returning any currently supported array kind support direct
`.size()`/`.get(index)`/`.first()`/`.last()`/`.copy()`/`.includes(value)`/
`.indexof(value)`/`.lastindexof(value)` and nested copy/read dispatch. The
unqualified form uses the impossible parser-only `$call_result`
prefix and is limited to plain lexical callees; library-private local UDF
bodies use the same normalization after module rewriting. The completed
built-in producer slice in item 9 adds `$builtin_array_result` for its exact
`array.*` producer allowlist and initially exposed only those same five helpers.
Only `.copy()` may return another array receiver for a nested allowed read/copy;
`.size()`, `.get()`, `.first()`, `.last()`, `.includes()`, `.indexof()`, and
`.lastindexof()` are terminal and cannot continue into an imported/user method
or another call-result method, including a method on a returned imported UDT
element. Imported UDT-array results must carry one concrete same-imported
scalar-tree identity. Named/`na`/
negative indexes,
bounds errors, empty and typed-`na` reads, A-to-B-to-A calls, and dual aliases
are fixture-backed. An unqualified root-local UDF result carrying a concrete
imported scalar UDT identity may also invoke existing pure user methods; the
built-in producer path does not gain that composition. The lexical prefix
`array` is reserved for built-in recognition, so an imported or user qualifier
with that spelling is not a supported qualified call-result path. At the
historical item 9 boundary, other namespaces/templates remained gated. Item 10
later admits exactly `str.split`, `ta.pivot_point_levels`, `matrix.row`,
`matrix.col`, `matrix.eigenvalues`, `map.keys`, and `map.values` on the same
synthetic path, with the same five helpers and only `.copy()` nestable. These
are scalar-array producers only: matrix row/column snapshots follow the five
supported scalar matrix kinds, eigenvalues retain the numeric-matrix
`array<float>` result, and map keys/values retain insertion order and the
corresponding five-scalar template kind. The new set does not carry or infer
imported UDT identity. Item 11 additionally admitted namespace-qualified
`matrix.mult(...)` when matrix-by-array, array-by-matrix, or array-by-array
resolution produces `array<float>`. Item 12 routes that namespace-only dynamic
candidate through `$builtin_matrix_result`, retains those five array helpers,
and admits matrix-by-matrix, matrix-by-scalar, and scalar-by-matrix
`matrix<float>` results through only `.rows()`, `.columns()`,
`.elements_count()`, `.get(row, column)`, and `.copy()`. Int inputs still
produce float collections, and only `.copy()` may continue another allowed
read/copy chain. Bound or UDF matrix-result helpers, wrong-result or broader
helpers, invalid helper arguments, and mutation remain fail-closed. Item 13
adds exact namespace `matrix.copy(values)` to the same matrix-result path. Its
`SameAsArg` result preserves the source float/int/bool/string/color matrix kind
and admits the same five matrix helpers with copy-only continuation; bound
`values.copy()` results remain gated. Item 14 adds exact namespace
`matrix.transpose(values)` with the same five element kinds and helpers,
row/column shape swapping, independent storage, and a retained bound
`values.transpose()` gate. Item 15 adds exact namespace
`matrix.submatrix(values, ...)` with preserved element kind, independent
half-open/default-full/empty range copies, the same helpers, and a retained
bound `values.submatrix()` gate. Item 16 adds exact namespace
`matrix.kron(left, right)` with a fixed float-matrix result, expanded shape,
independent storage, `na`/zero-dimension behavior, the same helpers, and a
retained bound `values.kron(other)` gate. Item 17 adds exact namespace
`matrix.diff(left, right)` with a fixed float-matrix result for matrix-matrix
and scalar/matrix operand pairs, selected-matrix shape and left-to-right
direction, the same helpers, and a retained bound `values.diff(other)` gate.
Item 18 adds exact namespace `matrix.pow(values, power)` with a fixed
float-matrix result for numeric square matrices and simple-int powers,
identity/copy/positive-power behavior, the same helpers, and a retained bound
`values.pow(power)` gate.
Item 19 adds exact namespace `matrix.inv(values)` with a fixed float-matrix
result that preserves invertible square shape, returns empty `0 x 0` or `na`
for the established boundaries, exposes the same helpers, and retains the
bound `values.inv()` gate.
Item 20 adds exact namespace `matrix.pinv(values)` with a fixed float-matrix
result that swaps rectangular row/column counts, preserves singular
matrix-valued results, returns swapped zero-cell shapes, exposes the same
helpers, yields `na` for invalid-cell inputs, and retains the bound
`values.pinv()` gate.
Item 21 adds exact namespace `matrix.eigenvectors(values)` with a fixed
float-matrix result that preserves square shape for real complete eigenvector
columns, returns empty `0 x 0`, yields `na` for invalid-cell/non-real/incomplete
results, exposes the same helpers, and retains the bound
`values.eigenvectors()` gate plus non-square runtime error.
Item 22 adds exact `matrix.new<float|int|bool|string|color>` template results
with preserved element kind, requested rectangular shape, type-compatible
initial or default `na` cells, fresh allocation, the same helpers, and retained
unsupported-template and mutation gates.
Item 23 adds exact supported scalar `map.new<K,V>` template results through a
separate `$builtin_map_result` path with known key/value kinds, fresh empty
allocation, direct size/get/contains/copy, copy-only continuation, and retained
mutation, keys/values, unsupported-template, and other map-result gates.
Item 24 adds exact namespace `map.copy(existing)` results through the same path,
retaining the source scalar template and entries in independent backing storage
while preserving the same helper, continuation, non-map-input, mutation, and
keys/values gates.
Item 25 adds exact bound matrix-receiver `values.copy()` results with preserved
float/int/bool/string/color element kind, shape, independent backing storage,
the five direct matrix read/copy helpers, copy-only continuation, and retained
other-bound-producer/non-matrix/mutation gates.
Item 26 adds exact bound matrix-receiver `values.transpose()` results with the
same five helpers, preserved element kind, swapped shape, independent backing
storage, copy-only continuation, and retained other-bound-producer/non-matrix/
mutation gates.
Item 27 adds exact bound matrix-receiver `values.submatrix(...)` results with
the same five helpers, preserved element kind, selected/default/empty half-open
ranges, independent backing storage, copy-only continuation, and retained
other-bound-producer/non-matrix/mutation gates.
Item 28 adds exact bound numeric-matrix-receiver `values.kron(other)` results
with the same five helpers, expanded shape, fixed float-matrix result kind,
independent backing storage, copy-only continuation, and retained operand/
other-bound-producer/non-matrix/mutation gates.
Item 29 adds exact bound numeric-matrix-receiver `values.diff(other)` results
for matrix or scalar operands with the same five helpers, selected matrix
shape, operand direction, fixed float-matrix result kind, independent backing
storage, copy-only continuation, and retained operand/other-bound-producer/
non-matrix/mutation gates.
Item 30 adds exact bound numeric-square-matrix-receiver `values.pow(power)`
results with the same five helpers, identity/copy/positive-power behavior,
fixed float-matrix result kind, independent backing storage, copy-only
continuation, and retained power/other-bound-producer/non-matrix/mutation
gates.
Item 31 adds exact bound numeric-square-matrix-receiver `values.inv()` results
with the same five helpers, preserved invertible square shape, empty `0 x 0`
and `na` singular/invalid-cell boundaries, fixed float-matrix result kind,
independent backing storage, copy-only continuation, and retained
other-bound-producer/non-matrix/mutation gates.
Item 32 adds exact bound numeric-matrix-receiver `values.pinv()` results with
the same five helpers, swapped rectangular shape, singular matrix results,
swapped zero-cell shapes, `na` invalid-cell boundaries, fixed float-matrix
result kind, independent backing storage, copy-only continuation, and retained
other-bound-producer/non-matrix/mutation gates.
Item 33 adds exact bound numeric-square-matrix-receiver
`values.eigenvectors()` results with the same five helpers, preserved real
square shape, empty `0 x 0` and `na` invalid/non-real/incomplete boundaries,
fixed float-matrix result kind, independent backing storage, copy-only
continuation, and retained other-bound-producer/non-matrix/mutation gates.
Item 34 adds exact bound numeric-matrix-receiver matrix-valued
`values.mult(other)` results for matrix or scalar operands with the same five
helpers, multiplied or scalar-selected shape, fixed float-matrix result kind,
`na`/zero-inner-dimension behavior, independent backing storage, copy-only
continuation, and retained array-result/UDF/non-matrix/mutation gates.
Item 35 adds unqualified local-UDF results with a concrete inferred matrix kind
through the same five helpers and copy-only continuation, retaining per-call
float/int/bool/string/color kind without adding imported identity.
Item 36 adds unqualified local-UDF results with one concrete supported scalar
map template through size/get/contains/copy and copy-only continuation,
retaining per-call key/value metadata without adding imported identity.
Item 37 adds local user-method scalar-map results, item 38 adds imported user-
method scalar-map results with same-library dual-alias isolation, and item 39
adds registered imported pure-function scalar-map results; all retain one
concrete scalar template and copy-only continuation without adding imported
identity to map metadata.
Item 40 adds local and imported user-method results with a concrete supported
matrix kind through rows/columns/elements_count/get/copy. Receiver-style,
local-type-qualified or alias-qualified, direct-constructor-receiver,
block/nested/same-kind-control-flow, five-kind, zero-dimension, dual-alias,
independent-copy, and copy-only-continuation paths carry method-call provenance
but no imported identity in matrix metadata.
Item 41 adds registered imported pure-function results with a concrete supported
matrix kind through the same five helpers. Alias-qualified, block/nested/same-
kind-control-flow, five-kind, zero-dimension, dual-alias, independent-copy, and
copy-only-continuation paths carry registered function provenance but no
imported identity in matrix metadata.
Item 42 adds `.keys()` to every existing concrete scalar-map call-result
producer. The read returns a fresh key-kind-preserving array and switches to
the closed array-result size/get/first/last/copy path, including copy-only
array continuation, without adding imported identity to map or array metadata.
Item 43 adds `.values()` across the same producer set. The read returns a fresh
value-kind-preserving array and uses the same closed array-result continuation,
without adding imported identity to map or array metadata.
Outside the exact closed producer/result paths,
unsupported `array.new<T>` types, non-producer calls, unsupported matrix
templates and map templates,
local/imported user-method matrix results without a concrete supported kind,
unregistered or unresolved user-function matrix results, unresolved or mixed
map results, and other matrix/map-returning calls, mixed or non-scalar return
identities,
non-array/non-UDT or unresolved results, nested field mutation, and
method receiver/parameter/global field side effects remain fail-closed.
`array.slice` retains its live parent view and postfix `.copy()` captures its
current values independently. `array.concat` still mutates and returns its
first input; a following reader is non-mutating, but concat remains rejected
inside library or root UDFs. Same-imported scalar-tree UDT-array tuple returns
are supported when destructured, with each
UDT-array slot retaining its own alias-qualified identity through direct and
tuple-valued ordinary declaration direct/self alias, control, shadowing, and
destructuring paths. Same-identity or `na` reassignment preserves the fixed
slot identity; cross-identity direct/control-flow reassignment fails closed at
the root span.

Current evidence:

- `docs/PURE_INTERNAL_ROADMAP.md` records source-aware same-library dual-alias
  UDT array returns as complete and keeps broader imported collection and method
  tails as remaining structured-data work.
- `tests/fixtures/conformance.tsv` marks `import` partial and records the
  scalar-tree imported UDT constructor/direct-or-nested field-read/reassignment/typed
  declaration/direct-or-nested UDF passthrough subset plus receiver-style or
  alias-qualified scalar-tree imported UDT methods with direct same-identity,
  block-local alias, ternary-expression alias, final-if alias, final-for alias,
  final-while alias, switch-expression alias, nested-method passthrough plus direct, nested, or ternary constructor returns,
  method-local scalar-tree root-field replacement, scalar-tree value
  history, and `array.from` size/get/first/last plus set replacement field
  reads, push append field reads, unshift prepend field reads, insert insertion
  field reads, fill replacement field reads, join positional stringification,
  includes/indexof/lastindexof structural equality search, sort/sort_indices by
  int/float/string sort_field, pop/remove/shift return field reads,
  clear-size reset, copy independent field reads, reverse reordered field
  reads, slice window field reads, concat appended field reads, and
  statement/expression/index-value for-in value-copy field reads, while
  imported UDT flow outside the covered same-identity scalar-tree paths remains unsupported.
- `tests/fixtures/runtime/import_udt_array_udf_method_returns.pine`,
  `tests/fixtures/sema/supported_imported_user_type_array_udf_method_returns.pine`,
  and `tests/fixtures/libraries/import_udt_array_return_lib.pine` cover the
  accepted imported UDF/method array-return subset.
- `tests/fixtures/runtime/import_udt_array_tuple_returns.pine` and
  `tests/fixtures/sema/supported_imported_user_type_array_tuple_returns.pine`
  cover per-slot imported tuple-return identity, typed-`na`, nested tuple
  destructuring, tuple-valued declaration aliases through ternary/`switch`/
  assigned-`if` and later destructuring, and same-library dual aliases. The
  matching identity-negative fixture,
  `tests/fixtures/sema/unsupported_imported_user_type_array_tuple_alias_mutation.pine`,
  and direct call-result chaining fixture keep the conflict, stable-slot
  reassignment, root-span, and broader-helper boundaries explicit. The imported
  UDF/method return runtime fixture covers qualified user-defined and
  unqualified root-local-wrapper direct
  `.size()`/`.get(index)`/`.first()`/`.last()`/`.copy()`, nested copy/read
  chains, named/`na`/negative indexes, empty and typed-`na` reads, A-to-B-to-A,
  dual aliases, explicit same-named exports or scalar methods, and copy
  independence. The library fixture also covers the unqualified postfix path
  inside a private library UDF after module rewriting, plus exact built-in
  producer reads from `array.new<lib.Type>`, `array.from`, `array.copy`,
  `array.slice`, and UDT `array.sort_indices` in a private helper reached
  through an exported wrapper.
- `docs/CONFORMANCE.md`, `docs/EXECUTION_SEMANTICS.md`, and
  `docs/SEMANTIC_MODEL.md` describe the narrow executable imported UDT
  constructor/direct field-read/reassignment/typed declaration/direct UDF
  passthrough plus nested passthrough-chain subset, receiver-style or
  alias-qualified scalar-tree imported UDT methods with direct same-identity,
  block-local alias, ternary-expression alias, final-if alias, final-for alias,
  final-while alias, switch-expression alias, nested-method passthrough plus direct, nested, or ternary constructor returns,
  method-local scalar-tree root-field replacement, scalar-tree value
  history, and `array.from` size/get/first/last plus set replacement field
  reads, push append field reads, unshift prepend field reads, insert insertion
  field reads, fill replacement field reads, join positional stringification,
  includes/indexof/lastindexof structural equality search, sort/sort_indices by
  int/float/string sort_field, pop/remove/shift return field reads,
  clear-size reset, copy independent field reads, reverse reordered field
  reads, slice window field reads, concat appended field reads, and
  statement/expression/index-value for-in value-copy field reads, while
  imported UDT flow outside the covered same-identity scalar-tree paths remains outside the executable subset.
- `crates/pine-sema/src/source_graph.rs` assigns deterministic root/library
  `SourceId`s from host-provided source text and normalized exact import keys.
- `crates/pine-sema/src/modules.rs` currently collects exported constants,
  exported functions, and exported UDT declarations. Exported UDTs now carry
  module-local source-scoped identity metadata (`SourceId`, type name) plus
  parser-level field layout metadata at the export table boundary. The import
  plan now records alias-qualified imported UDT metadata such as `lib.Point`,
  including scalar `PineType` metadata for `int`, `float`, `bool`, `string`, and
  `color` fields, and passes it into the analyzer. Module-local method and
  function bodies also rewrite exported UDT constructor names to their
  alias-qualified imported identities for supported inline execution.
  Scalar-field exported UDT constructors may now pass module validation for the
  first positive runtime subset. Deferred-field exported UDT constructors remain
  rejected with `E_IMPORT_UNSUPPORTED_UDT`, and private UDTs remain rejected as
  non-exported symbols.
- `crates/pine-sema/src/analyzer/user_types.rs` now records root-local
  `UserTypeInfo` identity metadata as `(SourceId::root(), type_name)` while
  semantic symbol/expression mark paths mirror same-root UDT identity metadata
  beside their existing type-name strings. Lowering-created declaration,
  parameter, and receiver symbols now use the same identity mirror helper. HIR
  constructors carry `HirUserTypeIdentity { source_id, type_name }` metadata.
  The analyzer can now accept alias-qualified scalar-field imported
  constructors such as `lib.Point.new`, validate local-style positional/named
  field arguments, mark imported source-scoped identity, resolve direct scalar
  field reads such as `p.x`, and allow ordinary reassignment from the same
  imported identity. It can also accept explicit scalar imported typed
  declarations such as `lib.Point p = lib.Point.new(close)` and reject
  local/imported typed declaration identity mismatches. Same-imported-identity
  ternary, `if`, `switch`, `while`, and `for` expression results are accepted, while
  local/imported branch identity mismatches are rejected. Ordinary imported UDT
  `var` declarations use the existing persistent value slot path, while
  local/imported `var` identity mismatches remain rejected. Scalar-field
  imported UDT `varip` declarations use the existing value-clone intrabar
  slot path; local/imported `varip` identity mismatches remain rejected.
  Deferred-field imported constructors remain rejected. The existing pure-UDF passthrough
  identity path now also accepts direct imported UDT parameter returns, block-local
  aliases returned from ternary expressions, final `for in` bodies, final `while` bodies, or switch-expression arms, and nested
  passthrough calls over those alias forms when the call argument and target use
  the same imported identity. Runtime UDT values still execute as field-vector values; source
  identity is carried in semantic and HIR metadata for compatibility checks
  rather than in `PineValue`.
- Library method collection now records the declared receiver type name and,
  when it resolves to a library UDT, the receiver's source-scoped identity.
  Receiver-style and alias-qualified imported UDT method calls use the imported
  method table entries for the scalar-tree receiver and parameter subset,
  including same-identity passthrough returns; alias-qualified imported method
  receiver type mismatches remain rejected. Receiver-style calls over imported
  UDT constructor or imported method call-result receivers such as
  `lib.Point.new(...).method(...)` and
  `lib.Point.new(...).make(...).same()` are parsed as alias-qualified imported
  method calls with the receiver passed as the first internal argument.
- `tests/fixtures/libraries/import_udt_lib.pine` provides a library with an
  exported scalar UDT for `tests/fixtures/runtime/import_udt_constructor.pine`,
  plus a deferred-field exported UDT and method for rejected boundaries, while
  `tests/fixtures/libraries/import_private_udt_lib.pine` covers the private UDT
  boundary and `tests/fixtures/libraries/import_duplicate_udt_lib.pine` covers
  duplicate exported UDT names, while
  `tests/fixtures/libraries/import_duplicate_udt_const_lib.pine` covers UDT and
  const exports sharing the same name and
  `tests/fixtures/libraries/import_duplicate_udt_function_lib.pine` covers UDT
  and function exports sharing the same name.
- `tests/fixtures/runtime/import_udt_constructor.pine` keeps
  `lib.Point.new(...)` plus `p.x` executable, and
  `tests/fixtures/runtime/import_udt_reassignment.pine` keeps ordinary
  same-imported-UDT reassignment executable, and
  `tests/fixtures/runtime/import_udt_typed_declaration.pine` keeps
  `lib.Point` typed declaration plus same-imported-UDT reassignment executable,
  and `tests/fixtures/runtime/import_udt_var.pine` keeps inferred and explicit
  `lib.Point` `var` declarations plus same-imported-UDT reassignment
  executable,
  and `tests/fixtures/runtime/import_udt_varip.pine` plus
  `tests/fixtures/realtime/import_udt_varip.pine` keep scalar-tree imported
  UDT `varip` declarations executable through historical and realtime
  intrabar persistence,
  and `tests/fixtures/runtime/import_udt_field_mutation.pine` keeps scalar-tree
  imported UDT root-field replacement executable at top level,
  and `tests/fixtures/runtime/import_udt_field_mutation_control_flow.pine`
  keeps scalar-tree imported UDT root-field replacement executable in branch, `for`-loop,
  and `while`-loop statement contexts,
  and `tests/fixtures/runtime/import_udt_udf_local_field_mutation.pine` keeps
  scalar-tree imported UDT root-field replacement executable for UDF-local variables returned
  from pure functions,
  while
  `tests/fixtures/sema/unsupported_imported_udt_parameter_field_mutation.pine`
  keeps imported UDT parameter field mutation inside pure functions rejected as
  a side-effect boundary,
  and
  `tests/fixtures/sema/unsupported_imported_udt_global_field_mutation.pine`
  keeps imported UDT global field mutation inside pure functions rejected as a
  side-effect boundary,
  `tests/fixtures/runtime/import_udt_history.pine` keeps scalar-tree imported
  UDT value history and caller-side direct/nested field reads fixture-backed,
  and
  `tests/fixtures/sema/unsupported_imported_udt_nested_field_mutation.pine`
  keeps parser-level nested imported field mutation rejected,
  and `tests/fixtures/runtime/import_udt_array_typed_declarations.pine` plus
  `tests/fixtures/runtime/import_udt_array_scalar_tree.pine` keep
  same-imported scalar-tree `array<lib.Type>` and `lib.Type[]`
  declarations fixture-backed,
  while `tests/fixtures/sema/supported_imported_udt_array_decl.pine` plus
  `tests/fixtures/sema/supported_imported_udt_array_alias_decl.pine` keep the
  declaration acceptance boundary fixture-backed,
  `tests/fixtures/runtime/import_udt_array_from.pine` keeps same-imported
  scalar-field UDT `array.from` size/get/first/last plus set replacement field
  reads, push append field reads, unshift prepend field reads, insert insertion
  field reads, fill replacement field reads, join positional stringification,
  includes/indexof/lastindexof structural equality search, sort/sort_indices by
  int/float/string root sort_field, pop/remove/shift return field reads,
  clear-size reset, copy independent field reads, reverse reordered field
  reads, slice window field reads, concat appended field reads, and
  statement/expression/index-value for-in value-copy field reads fixture-backed,
  and `tests/fixtures/runtime/import_udt_array_scalar_tree.pine` keeps nested
  same-imported scalar-tree UDT arrays executable for typed declarations,
  `array.from`, field reads, set/copy/push/unshift/insert, pop/remove/shift
  returns, first/last, clear/fill/reverse/slice/concat, join, structural
  equality search, `for...in`, and `varip`, while
  `tests/fixtures/runtime/import_udt_array_history.pine` keeps committed array
  history snapshots from `array.from` and `array.new<lib.Type>()` construction
  with first-bar and dynamic na-offset predicates executable,
  `tests/fixtures/runtime/import_udt_array_new.pine` keeps imported UDT
  `array.new<lib.Point>()` templates and post-construction array helper
  operations executable,
  and `tests/fixtures/runtime/import_udt_udf_passthrough.pine` keeps direct plus
  ternary-expression alias, final-`for in`, final-`while`, and switch-expression alias imported UDT UDF parameter passthrough executable,
  and `tests/fixtures/runtime/import_udt_udf_nested_passthrough.pine` keeps
  nested imported UDT UDF parameter passthrough chains over those forms executable,
  while
  `tests/fixtures/sema/unsupported_imported_udt_constructor.pine` keeps a
  unresolved-field imported constructor rejected, and
  `tests/fixtures/sema/unsupported_imported_udt_varip.pine` keeps nested-field
  imported UDT values rejected in a `varip` initializer, while
  `tests/fixtures/sema/unsupported_imported_udt_assignment_identity.pine` keeps
  local/imported structural lookalikes rejected as different identities, while
  `tests/fixtures/sema/unsupported_imported_udt_typed_decl_identity.pine` keeps
  typed declarations from accepting local/imported structural lookalikes, while
  `tests/fixtures/sema/unsupported_imported_udt_var_identity.pine` keeps `var`
  declarations from accepting local/imported structural lookalikes, while
  `tests/fixtures/sema/unsupported_imported_udt_varip_identity.pine` keeps
  `varip` declarations from accepting local/imported structural lookalikes,
  `tests/fixtures/sema/unsupported_imported_udt_while_identity.pine` and
  `tests/fixtures/sema/unsupported_imported_udt_for_identity.pine` keep
  `while`/`for` expression results from accepting local/imported structural
  lookalikes, while
  `tests/fixtures/sema/unsupported_imported_udt_udf_passthrough_identity.pine`
  keeps direct UDF passthrough from erasing local/imported identity mismatches,
  while
  `tests/fixtures/sema/unsupported_imported_udt_udf_nested_passthrough_identity.pine`
  keeps nested passthrough chains from erasing local/imported identity
  mismatches. These local/imported identity mismatch fixtures lock the
  user-facing assignment and branch diagnostics instead of only the diagnostic
  codes, while
  `tests/fixtures/sema/unsupported_imported_private_udt_constructor.pine` keeps
  private library UDT construction rejected as private symbol access,
  `tests/fixtures/sema/unsupported_import_duplicate_exported_udt.pine` keeps
  duplicate exported UDT names rejected,
  `tests/fixtures/sema/unsupported_import_duplicate_exported_udt_const.pine`
  keeps duplicate exported UDT/const names rejected,
  `tests/fixtures/sema/unsupported_import_duplicate_exported_udt_function.pine`
  keeps duplicate exported UDT/function names rejected,
  `tests/fixtures/runtime/import_udt_method.pine` keeps receiver-style scalar-tree
  imported UDT method calls executable,
  `tests/fixtures/runtime/import_udt_method_qualified.pine` keeps
  alias-qualified imported UDT method calls executable when the first argument
  is a same-identity scalar-tree imported UDT receiver, including nested UDT
  receiver fields, named/reordered non-receiver arguments, same-identity
  scalar-tree UDT parameters, caller-side history reads from named-argument UDT
  returns, and method-local scalar-tree root-field replacement,
  `tests/fixtures/runtime/import_udt_method_expression_receiver.pine` keeps
  alias-qualified imported UDT method calls over direct constructor receiver
  expressions executable, including named/reordered non-receiver arguments,
  direct constructor nested UDT arguments, and receiver-style imported UDT
  method calls over imported constructor or imported method call-result receiver
  chains,
  `tests/fixtures/syntax/imported_method_call_result_receiver.pine` keeps
  receiver-style imported UDT method calls over call-result receiver
  expressions accepted by the parser boundary,
  `tests/fixtures/runtime/import_udt_method_return.pine` keeps direct receiver
  passthrough returns executable,
  `tests/fixtures/runtime/import_udt_method_param_return.pine` keeps direct
  same-identity parameter passthrough returns executable,
  `tests/fixtures/runtime/import_udt_method_block_return.pine` keeps
  block-local receiver and parameter alias passthrough returns executable,
  `tests/fixtures/runtime/import_udt_method_if_return.pine` keeps final
  `if`/`else` receiver and parameter alias passthrough returns executable,
  `tests/fixtures/runtime/import_udt_method_for_return.pine` keeps final
  `for` receiver and parameter alias passthrough returns executable,
  `tests/fixtures/runtime/import_udt_method_while_switch_return.pine` keeps final
  ternary-expression alias, `while`, and switch-expression receiver and
  parameter alias passthrough returns executable,
  `tests/fixtures/runtime/import_udt_method_nested_return.pine` keeps nested
  method passthrough returns executable,
`tests/fixtures/runtime/import_udt_method_local_field_mutation.pine` keeps
method-local imported UDT scalar-tree root-field replacement executable,
  `tests/fixtures/runtime/import_udt_method_constructor_return.pine` keeps
  direct, nested, or ternary same-imported-identity constructor returns executable,
  `tests/fixtures/runtime/import_udt_array_typed_udf_params.pine` keeps
  same-imported scalar-tree UDT array typed UDF parameters executable with
  positional and named array arguments plus caller-side history reads from
  returned imported UDT array elements, and
  `tests/fixtures/runtime/import_udt_array_typed_method_params.pine` keeps
  same-imported scalar-tree UDT array typed method parameters executable with
  positional and named array arguments plus caller-side history reads from
  returned imported UDT array elements, and
  `tests/fixtures/sema/unsupported_imported_method_qualified_receiver.pine`
  and `tests/fixtures/sema/unsupported_imported_method_qualified_receiver_order.pine`
  keep alias-qualified imported method receiver type/order mismatches rejected,
  while
  `tests/fixtures/sema/unsupported_imported_method_field_mutation.pine`
  plus `tests/fixtures/libraries/import_udt_method_side_effect_lib.pine`
  keep imported method receiver and parameter field mutation rejected through
  `function_side_effect` diagnostics.
- `crates/pine-sema/src/tests/compatibility.rs` also asserts scalar-tree
  imported UDT constructors analyze successfully, exported imported UDT
  metadata can include private scalar-tree UDT dependencies for typed-`na`
  history, with
  `tests/fixtures/runtime/import_udt_private_dependency_history.pine` keeping
  whole-value private-dependency history executable, while
  private-dependency constructor calls fail with
  `E_UDT_CONSTRUCTOR_ARG` when the nested private value cannot be supplied,
  private imported UDT constructors fail with `E_IMPORT_PRIVATE_SYMBOL`,
  local/imported assignment identity mismatches fail with `E_UDT_ASSIGN_TYPE`,
  scalar imported UDT typed declarations analyze successfully, typed
  declaration identity mismatches fail
  with `E_UDT_ASSIGN_TYPE`, direct imported UDT UDF passthrough analyzes
  successfully, ternary-expression alias, final-`for in`, final-`while`, and switch-expression alias imported UDT UDF
  passthrough analyzes successfully, nested imported UDT UDF passthrough over
  those forms analyzes successfully,
  passthrough identity mismatches fail with `E_UDT_ASSIGN_TYPE`, duplicate
  exported UDT names plus UDT/const and UDT/function export name collisions
  fail with `E_IMPORT_DUPLICATE_EXPORT`,
  receiver-style or alias-qualified scalar-tree imported UDT method calls including
  direct same-identity, block-local alias, ternary-expression alias, final-if
  alias, final-for alias, final-while alias, switch-expression alias,
  nested-method passthrough plus direct, nested, or ternary constructor returns, and method-local field
  mutation analyze successfully, and alias-qualified imported method receiver
  type mismatches fail with `E_METHOD_ARG_TYPE`.

Do not widen imported UDTs beyond the scalar constructor/direct field-read,
ordinary reassignment, explicit typed declaration, same-imported-identity
ternary/`if`/`switch`/`while`/`for` expression results, direct or nested UDF
passthrough, direct or nested constructor-return subset, ordinary `var`,
scalar-tree `varip`, scalar-tree root-field replacement in top-level, branch, `for`-loop,
`while`-loop, and UDF-local statement contexts, and receiver-style scalar-tree
imported UDT method calls until a runtime slice implements the behavior and
updates fixtures, conformance, snapshots, and docs together.

## Target Shape

Imported UDTs should be source-graph-scoped type identities, not root-local names
that happen to share spelling.

Target identity properties:

- every UDT definition has a stable semantic identity such as
  `(SourceId, type_name)`;
- root-local `Point` and imported `lib.Point` are different identities even if
  their field lists are structurally identical;
- the same imported type reached through the same resolved source graph identity
  has the same semantic identity wherever it is referenced;
- imported UDT values can be assigned, passed, returned, and field-read only when
  identity compatibility is proven;
- diagnostics should display the user-facing name (`Point`, `lib.Point`, or a
  later canonical form) while comparing internal identities.

The first positive subset should support values, not host-visible object ids.
Runtime values can continue to use the current `PineValue::UserType` field-vector
representation if semantic analysis and lowering carry enough type identity and
field layout metadata to preserve compatibility.

## Export And Import Policy

Initial export policy:

- exported type declarations in library sources become addressable through the
  import alias, for example `lib.Point`;
- non-exported type declarations remain private to their source unit;
- duplicate exported type names in one module are rejected;
- private symbol access through an import alias continues to fail;
- re-exporting imported types remains unsupported in the first positive subset;
- remote lookup and implicit library resolution remain host-owned and out of
  core scope.

Initial import policy:

- `import user/lib/1 as lib` remains the only supported import spelling;
- `lib.Point.new(...)` is the first constructor spelling to consider;
- bare `Point.new(...)` never resolves to an imported type without a local type
  declaration or explicit import alias qualification;
- `array<lib.Point>` and `lib.Point[]` resolve only for same-imported
  scalar-tree UDT arrays; `array.new<lib.Point>()` templates are supported for
  the same scalar-tree imported UDT subset.

## Field And Constructor Policy

First positive imported UDT subset:

- scalar fields only: `int`, `float`, `bool`, `string`, and `color`;
- constructor argument rules mirror local UDT constructors, including positional
  and named field arguments;
- field reads use the imported type's declaration order and field names;
- scalar field mutation follows the local UDT mutation writeback path in
  top-level, branch, `for`-loop, `while`-loop, UDF-local statement contexts,
  and method-local statement contexts;
- imported field mutation on UDF parameters or globals, method receivers,
  method parameters, or globals inside methods, nested imported field mutation,
  and imported collection/history mutation remain unsupported;
- imported UDT values can be stored in ordinary variables and explicit typed
  locals only when the initializer and later reassignment carry the same
  imported identity.

Deferred field families:

- nested imported or local UDT fields;
- arrays, maps, matrices, tuples, drawing ids, chart points, strategy records,
  and other reference-like fields;
- recursive and forward-declared fields;
- imported UDT history references outside the scalar-field value subset.

## Method Policy

Imported method support should follow imported type identity. Do not expose
library method tables as loose functions.

Initial policy:

- a method declared in a library is associated with the receiver type identity
  from that library source;
- method lookup on an imported UDT receiver searches that identity's method
  table, not root-local methods with the same receiver spelling;
- root-local methods cannot attach to imported receiver identities in the first
  subset;
- imported methods must satisfy the same pure-method and no-side-effect rules as
  local methods;
- method return identity is tracked for direct same-identity, block-local alias,
  ternary-expression alias, final-if alias, final-for alias, final-while alias,
  switch-expression alias, and nested-method passthrough plus direct, nested, or ternary constructor returns and should keep
  following constructor and parameter identity as the subset widens.

Receiver-style scalar-tree imported UDT methods are supported for scalar returns and
direct same-identity, block-local alias, ternary-expression alias, final-if alias, final-for alias,
final-while alias, switch-expression alias, and nested-method passthrough plus
direct, nested, or ternary constructor returns.
Broader imported method parameter/return flow should remain rejected until it is
fixture-backed through analysis, lowering, runtime snapshots, conformance, and
docs.

## Analyzer And Lowering Policy

Future implementation should avoid string-only identity comparisons:

- extend module collection to record exported UDT declarations and method
  declarations with source identities;
- introduce an internal `UserTypeId` or equivalent that includes `SourceId` and
  local type name;
- replace root-local UDT identity maps that store only names where imported
  values can flow;
- carry field layout and display names through semantic analysis and lowering;
- keep compile-cache keys tied to root source plus every host-provided library
  key/name/text, as today, so imported type identity cannot reuse stale graphs;
- emit precise diagnostics for unknown exports, private symbols, unsupported
  imported UDTs, mismatched imported/local identities, and unsupported imported
  method variants.

HIR and runtime should not need a new public JSON shape for the first value-only
subset. Any later public exposure of imported UDT values must be a separate
contract slice.

## Realtime, History, And Collections

First imported UDT support should not introduce new persistence behavior:

- ordinary, `var`, and scalar-tree `varip` imported UDT values behave like
  local UDT values;
- scalar-tree imported UDT value history follows existing series history, and
  same-imported scalar-tree UDT `array.from` can construct fixture-backed
  arrays for size/get/first/last, set replacement field reads, push append
  field reads, unshift prepend field reads, insert insertion field reads, fill
  replacement field reads, join positional stringification,
  includes/indexof/lastindexof structural equality search, sort/sort_indices by
  int/float/string sort_field, pop/remove/shift return field reads, clear size
  reset, copy independent field reads, reverse reordered field reads, slice
  window field reads, concat appended field reads,
  statement/expression/index-value for-in value-copy field reads, and committed
  array history snapshots with first-bar and dynamic na-offset predicates;
  broader UDT arrays and nested collection storage remain deferred until local
  equivalents and imported identity rules are both fixture-backed;
- realtime rollback follows existing value rollback once imported UDT values are
  represented as ordinary UDT values with stable identity metadata.

## Slice Order

Recommended future slices:

1. Export table shape: collect exported UDT declarations and keep them rejected
   with targeted diagnostics before constructor support. This negative boundary
   is fixture-backed; private library UDTs remain non-exported symbols and
   duplicate exported UDT names plus UDT/const and UDT/function name collisions
   are rejected through the shared export table. Exported UDT entries now retain
   parser-level field layout metadata for later constructor analysis, and the
   import plan carries alias-qualified imported UDT metadata with scalar
   `PineType` field classifications into the analyzer without changing accepted
   scripts.
2. Identity plumbing: introduce source-scoped UDT identity in semantic analysis
   without changing accepted scripts. The module/export boundary now records
   exported UDT identities as `(SourceId, type_name)`, and analyzer root-local
   `UserTypeInfo` records now carry `(SourceId::root(), type_name)` metadata
   with semantic symbol/expression identity mirrors plus lowering symbol mirror
   writes. HIR UDT constructors now carry
   `HirUserTypeIdentity { source_id, type_name }` metadata for both root-local
   and supported imported constructors.
3. Constructor, field-read, and ordinary reassignment subset:
   `lib.Point.new(...)` for scalar-tree imported UDTs with runtime snapshots
   proving direct and nested field-read value behavior is implemented. Ordinary
   same-imported-UDT reassignment is also fixture-backed, while local/imported
   structural lookalikes remain rejected as distinct identities. Explicit
   scalar imported typed declarations initialized or reassigned from the same
   imported identity are fixture-backed, while local/imported typed declaration
   identity mismatches remain rejected. Same-imported-identity ternary, `if`,
   `switch`, `while`, and `for` expression results are fixture-backed, while
   local/imported branch identity mismatches remain rejected. Scalar-field value
   history and `array.from` size/get/first/last plus set replacement field
   reads, push append field reads, unshift prepend field reads, insert insertion
   field reads, fill replacement field reads, join positional stringification,
   includes/indexof/lastindexof structural equality search, sort/sort_indices by
   int/float/string sort_field, pop/remove/shift return field reads,
   clear-size reset, copy independent field reads, reverse reordered field
   reads, slice window field reads, concat appended field reads, and
   statement/expression/index-value for-in value-copy field reads are
   fixture-backed, while unresolved-field constructors, unsupported field
   mutation, and collections beyond the explicit helper and call-return subsets
   remain rejected.
4. UDF passthrough: allow imported UDT values to flow through pure UDFs while
   rejecting mismatched identities. Direct parameter passthrough returns such
   as `passthrough(p) => p` are now fixture-backed for same imported identity,
   while local/imported identity mismatches remain rejected. Final `for in`,
   final `while`, switch-expression alias passthrough, nested passthrough chains,
   and direct or nested constructor-return helpers are fixture-backed for same imported
   identity, while nested local/imported identity mismatches remain rejected.
5. Imported methods: support pure methods whose receiver identity is imported
   and whose parameters/returns stay inside the supported identity subset.
Receiver-style and alias-qualified scalar-tree imported UDT method calls plus
named/reordered non-receiver arguments, direct same-identity, scalar-tree parameters, block-local alias,
ternary-expression alias, final-if alias, final-for alias, final-while alias,
switch-expression alias, nested-method passthrough plus direct, nested, or ternary constructor returns,
and method-local scalar-tree root-field replacement are fixture-backed.
Receiver-style scalar imported UDT call-result expressions and qualified
same-imported UDT-array result `.first()`/`.copy()` were fixture-backed in the
initial direct-helper slice; qualified same-local user-method results have
equivalent local coverage. Same-imported scalar-tree UDT array returns from
typed methods are also fixture-backed, while broader imported method
return/parameter flow remains deferred.
6. Imported UDF/user-method same-scalar-tree UDT array returns preserve direct,
   alias, copy/new/from, private nested, final-flow, type-position, and dual-alias
   call-site identity. Tuple returns preserve that identity independently per
   destructured UDT-array slot, including block/nested/final-flow and typed-`na`
   paths plus tuple-valued ordinary declaration direct/self alias, control,
   shadowing, and destructuring. Same-identity or `na` reassignment preserves
   the fixed slot layout, while conflicting identities and cross-identity
   direct/control-flow reassignment fail closed. Qualified same-imported array
   results and qualified same-local user-method results gained direct
   `.first()`/`.copy()` in this historical slice; at that boundary, unqualified
   local UDF results, broader direct methods, non-scalar returns, and
   unsupported mutation contexts remained later collection work.
7. Qualified same-imported UDF/method and same-local user-method UDT-array
   results extend that direct read-only set with `.size()`, `.get(index)`, and
   `.last()`. The fixture-backed contract covers simple-int and concrete UDT
   element results, named/`na`/negative indexes, precise bounds errors, empty
   and typed-`na` reads, nested copy/read chains, A-to-B-to-A and dual-alias
   isolation, generic wrappers, and explicit same-named imported, local, or
   scalar-UDT dispatch controls. Done. At this historical slice boundary, other
   direct helpers, unqualified local UDF results, mixed/non-scalar identities,
   and mutation remained gated.
8. Unqualified plain local UDF call-result receivers normalize through the
   impossible parser-only `$call_result` prefix, including private library UDF
   bodies after module rewriting. Results returning any currently supported
   array kind share the read-only
   `.size()`/`.get(index)`/`.first()`/`.last()`/`.copy()` path with qualified
   user-defined results; imported UDT arrays still require one concrete
   same-imported scalar-tree identity. Concrete imported scalar UDT results may
   invoke existing pure user methods. Plain-callee validation keeps local UDFs
   named after built-in namespaces unambiguous. At this historical slice
   boundary, built-in-qualified/template results remained parser-gated, and
   mixed/non-scalar UDT arrays, non-array/non-UDT results, unknown/`na` results
   without a concrete supported type or identity, broader array helpers, and
   mutation remained rejected. Done.
9. Exact built-in array producers normalize through the separate
   `$builtin_array_result` prefix, including inside private library helpers
   after module rewriting. The exact admitted producer set is `array.new_float`,
   `array.new_int`, `array.new_bool`, `array.new_string`, `array.new_color`,
   `array.new_line`, `array.new_linefill`, `array.new_polyline`,
   `array.new_label`, `array.new_box`, `array.new_table`,
   `array.new<chart.point>`, supported `array.new<UDT>`, `array.from`,
   `array.copy`, `array.slice`, `array.concat`, `array.abs`,
   `array.standardize`, and `array.sort_indices`; supported
   scalar/drawing-id/`chart.point` and concrete
   same-local/same-imported scalar-tree UDT `array.new<T>` source forms use the
   canonical constructor or checked UDT-template path. Only `.size()`,
   `.get(index)`, `.first()`, `.last()`, and `.copy()` may follow. Only
   `.copy()` can yield another array receiver for a nested allowed read/copy;
   terminal readers cannot invoke imported/user methods or other call-result
   methods, including on returned imported UDT elements. Producer arguments,
   array kind, and concrete imported identity are revalidated and fail closed.
   Other namespaces/templates, unsupported UDT templates, non-producer
   `array.*` members, and postfix mutation stay gated. The lexical `array`
   prefix remains reserved for built-in recognition and is not a supported
   import-alias call-result path. Slice remains a live parent view and postfix
   copy is independent. Concat mutates and returns its first input; the outer
   reader is non-mutating, but concat remains rejected inside UDFs. Done.
10. A later scalar-array producer slice reuses `$builtin_array_result` for
    exactly `str.split`, `ta.pivot_point_levels`, `matrix.row`, `matrix.col`,
    `matrix.eigenvalues`, `map.keys`, and `map.values`. Each exposes only
    `.size()`, `.get(index)`, `.first()`, `.last()`, and `.copy()`; only
    `.copy()` can continue into another allowed read/copy. Row/column results
    are independent arrays matching the float/int/bool/string/color matrix
    element kind, eigenvalues retain the independent `array<float>` result for
    supported numeric matrices, and map key/value results are independent
    insertion-order arrays matching the corresponding
    int/float/bool/string/color template side. Empty/`na`, negative-index,
    bounds, typed destinations, UDF reads, and copy independence are
    fixture-backed. Namespace-qualified `matrix.mult(...)` direct-result
    chains, matrix-returning calls, unsupported matrix templates and map templates, all other
    namespaces/non-producers, and mutation remain gated; the existing
    bound-receiver `matrix_id.mult(array).size()` path is unchanged. Built-in
    prefixes stay reserved. This slice deliberately adds no imported
    UDT identity and no public schema field. Done.
11. A conditional namespace `matrix.mult` slice adds that callee as a parser
    candidate while preserving semantic result-type gating. Matrix-by-array,
    array-by-matrix, and array-by-array overloads resolve to `array<float>` and
    expose only `.size()`, `.get(index)`, `.first()`, `.last()`, and `.copy()`;
    only `.copy()` may continue. Matrix-by-matrix, matrix-by-scalar, and
    scalar-by-matrix overloads resolve to `matrix<float>` and keep the generic
    direct call-result rejection. Invalid indexes, other helpers, mutation,
    empty/`na` values, typed destinations, UDF reads, and nested-copy behavior
    are fixture-backed. The existing bound-receiver
    `matrix_id.mult(array).size()` path is unchanged. No imported UDT identity
    or public schema field is added. Done.
12. The namespace matrix-result continuation routes `matrix.mult(...)` through
    `$builtin_matrix_result` and keeps result-type-directed dispatch. The three
    array-returning overload families retain the item 11 five-helper contract.
    Matrix-by-matrix, matrix-by-scalar, and scalar-by-matrix resolve to
    `matrix<float>` and expose only `.rows()`, `.columns()`,
    `.elements_count()`, `.get(row, column)`, and `.copy()`, including int-input
    float-result matrices. Only `.copy()` may continue another allowed
    read/copy chain. Wrong-result helpers, bad helper arity or types, mutation,
    and broader helpers fail closed; bound or UDF matrix-result receivers retain
    the generic direct call-result rejection, while the existing bound
    `matrix_id.mult(array).size()` path is unchanged. Empty/`na` values, typed
    destinations, UDF-contained namespace calls, copy independence, and the
    retained boundaries are fixture-backed. No imported UDT identity or public
    schema field is added. Done.
13. The exact namespace matrix-copy continuation routes `matrix.copy(values)`
    through `$builtin_matrix_result`. Its `SameAsArg` result preserves all five
    supported scalar matrix element kinds and exposes only `.rows()`,
    `.columns()`, `.elements_count()`, `.get(row, column)`, and `.copy()`, with
    named helper arguments and copy-only continuation. Empty/`na`, nested-copy,
    UDF-contained namespace reads, and source/copy independence are
    fixture-backed. Wrong receivers, invalid helper arguments, mutation,
    broader helpers, and bound `values.copy()` call-result reads fail closed.
    No imported UDT identity or public schema field is added. Done.
14. The exact namespace matrix-transpose continuation routes
    `matrix.transpose(values)` through `$builtin_matrix_result`. Its `SameAsArg`
    result preserves all five supported scalar element kinds while swapping
    row/column shape and allocating independent storage. It exposes only the
    five matrix read/copy helpers with named arguments and copy-only
    continuation. Zero dimensions, `na`, coordinate mapping, nested copies,
    UDF-contained namespace reads, and source independence are fixture-backed.
    Wrong receivers, invalid helper arguments, mutation, broader helpers, and
    bound `values.transpose()` call-result reads fail closed. No imported UDT
    identity or public schema field is added. Done.
15. The exact namespace matrix-submatrix continuation routes
    `matrix.submatrix(values, ...)` through `$builtin_matrix_result`. Its
    `SameAsArg` result preserves all five supported scalar element kinds while
    returning independent half-open ranges with default full bounds and empty
    row/column slices. It exposes only the five matrix read/copy helpers with
    named arguments and copy-only continuation. `na`, coordinate mapping,
    nested copies, UDF-contained namespace reads, and source independence are
    fixture-backed. Wrong producer/helper arguments, wrong receivers, mutation,
    broader helpers, and bound `values.submatrix()` call-result reads fail
    closed. No imported UDT identity or public schema field is added. Done.
16. The exact namespace matrix-kron continuation routes
    `matrix.kron(left, right)` through `$builtin_matrix_result`. Its fixed
    `simple matrix<float>` result accepts numeric matrix operands, expands both
    source dimensions, and exposes only the five matrix read/copy helpers with
    named arguments and copy-only continuation. Int-input float results, `na`,
    zero rows/columns, nested copies, UDF-contained namespace reads, and source
    independence are fixture-backed. Wrong producer/helper arguments,
    mutation, broader helpers, and bound `values.kron(other)` call-result reads
    fail closed. No imported UDT identity or public schema field is added. Done.
17. The exact namespace matrix-diff continuation routes
    `matrix.diff(left, right)` through `$builtin_matrix_result`. Its fixed
    `simple matrix<float>` result accepts matrix-matrix, matrix-scalar, and
    scalar-matrix numeric operands, preserves the selected matrix shape and
    left-to-right subtraction order, and exposes only the five matrix read/copy
    helpers with named arguments and copy-only continuation. Int-input float
    results, `na`, zero rows/columns, nested copies, UDF-contained namespace
    reads, and source independence are fixture-backed. Wrong producer/helper
    arguments, mutation, broader helpers, and bound `values.diff(other)`
    call-result reads fail closed. No imported UDT identity or public schema
    field is added. Done.
18. The exact namespace matrix-power continuation routes
    `matrix.pow(values, power)` through `$builtin_matrix_result`. Its fixed
    `simple matrix<float>` result accepts numeric square matrices and simple-int
    powers, preserves independent identity/copy/positive-power results, and
    exposes only the five matrix read/copy helpers with named arguments and
    copy-only continuation. Int-input float results, `na`, empty `0 x 0`,
    nested copies, UDF-contained namespace reads, and source independence are
    fixture-backed. Wrong producer/helper arguments, mutation, broader helpers,
    and bound `values.pow(power)` call-result reads fail closed. No imported UDT
    identity or public schema field is added. Done.
19. The exact namespace matrix-inverse continuation routes `matrix.inv(values)`
    through `$builtin_matrix_result`. Its fixed `simple matrix<float>` result
    preserves invertible square shape, returns an empty `0 x 0` matrix for
    empty input and `na` for singular or invalid-cell inputs, and exposes only
    the five matrix read/copy helpers with named arguments and copy-only
    continuation. Int-input float results, nested copies, UDF-contained
    namespace reads, and source independence are fixture-backed. Wrong
    producer/helper arguments, mutation, broader helpers, and bound
    `values.inv()` call-result reads fail closed. No imported UDT identity or
    public schema field is added. Done.
20. The exact namespace matrix-pseudo-inverse continuation routes
    `matrix.pinv(values)` through `$builtin_matrix_result`. Its fixed
    `simple matrix<float>` result swaps rectangular row/column counts,
    preserves singular matrix-valued results, returns swapped zero-cell shapes
    for zero-row or zero-column inputs, and yields `na` for invalid-cell
    inputs. It exposes only the five matrix read/copy helpers with named
    arguments and copy-only continuation. Int-input float results, nested
    copies, UDF-contained namespace reads, and source independence are
    fixture-backed. Wrong producer/helper arguments, mutation, broader
    helpers, and bound `values.pinv()` call-result reads fail closed. No
    imported UDT identity or public schema field is added. Done.
21. The exact namespace matrix-eigenvector continuation routes
    `matrix.eigenvectors(values)` through `$builtin_matrix_result`. Its fixed
    `simple matrix<float>` result preserves square shape for real complete
    eigenvector columns, returns an empty `0 x 0` matrix for empty input, and
    yields `na` for invalid-cell, non-real, or incomplete results. It exposes
    only the five matrix read/copy helpers with named arguments and copy-only
    continuation. Int-input float results, nested copies, UDF-contained
    namespace reads, and source independence are fixture-backed. Wrong
    producer/helper arguments, mutation, broader helpers, and bound
    `values.eigenvectors()` call-result reads fail closed; non-square runtime
    errors are unchanged. No imported UDT identity or public schema field is
    added. Done.
22. The exact matrix-constructor-template continuation routes
    `matrix.new<float>`, `matrix.new<int>`, `matrix.new<bool>`,
    `matrix.new<string>`, and `matrix.new<color>` results through
    `$builtin_matrix_result`. Each preserves its element kind, requested
    rectangular shape, type-compatible initial or default `na` cells, fresh
    allocation, and copy independence, and exposes only the five matrix
    read/copy helpers with named arguments and copy-only continuation. Zero
    dimensions, nested copies, UDF-contained template reads, and fresh-source
    behavior are fixture-backed. Invalid constructor/helper arguments,
    mutation, broader helpers, and unsupported/deferred templates fail closed.
    No imported UDT identity or public schema field is added. Done.
23. The exact scalar-map-constructor continuation routes supported
    `map.new<K,V>` templates through `$builtin_map_result`, where both `K` and
    `V` are int, float, bool, string, or color. Fresh empty maps retain their
    concrete key/value kinds and expose only `.size()`, `.get(key)`,
    `.contains(key)`, and `.copy()` with named arguments and copy-only
    continuation. All 25 template pairs, missing reads, nested copies,
    copy-then-mutate behavior, fresh allocation, and UDF-contained reads are
    fixture-backed. Wrong key/arity, mutation, direct `keys()`/`values()`,
    unsupported templates, broader helpers, and other map-result receivers
    fail closed. No imported UDT identity or public schema field is added.
    Done.
24. The exact namespace-map-copy continuation routes `map.copy(existing)`
    through `$builtin_map_result`. The result retains the source scalar
    key/value kinds and populated entries in independent backing storage and
    exposes only `.size()`, `.get(key)`, `.contains(key)`, and `.copy()` with
    named arguments and copy-only continuation. Populated reads, nested copy,
    source/copy independence, multiple scalar templates, and UDF-contained
    reads are fixture-backed. Wrong receiver/key/arity, mutation, direct
    `keys()`/`values()`, broader helpers, and other map-result receivers fail
    closed. No imported UDT identity or public schema field is added. Done.
25. The exact bound-matrix-copy continuation recognizes `values.copy()` only
    when `values` resolves to a supported concrete matrix kind. The result
    retains element kind, shape, and independent backing storage and exposes
    only rows/columns/elements_count/get/copy with copy-only continuation.
    Float/int/bool/string/color receivers, nested copy, UDF-contained reads,
    wrong indexes, broader helpers, non-matrix receivers, and the retained
    bound-transpose gate are fixture-backed. No imported UDT identity or public
    schema field is added. Done.
26. The exact bound-matrix-transpose continuation recognizes
    `values.transpose()` only when `values` resolves to a supported concrete
    matrix kind. The result retains element kind, swaps row/column shape, uses
    independent backing storage, and exposes only
    rows/columns/elements_count/get/copy with copy-only continuation. Five
    element kinds, nested copy, UDF-contained reads, wrong indexes, broader
    helpers, non-matrix receivers, and the retained bound-submatrix gate are
    fixture-backed. No imported UDT identity or public schema field is added.
    Done.
27. The exact bound-matrix-submatrix continuation recognizes
    `values.submatrix(...)` only when `values` resolves to a supported concrete
    matrix kind. The result retains element kind, selects an independent
    half-open range including default full and valid empty ranges, and exposes
    only rows/columns/elements_count/get/copy with copy-only continuation. Five
    element kinds, nested copy, UDF-contained reads, wrong ranges/indexes,
    broader helpers, non-matrix receivers, and the retained bound-kron gate are
    fixture-backed. No imported UDT identity or public schema field is added.
    Done.
28. The exact bound-matrix-Kronecker continuation recognizes
    `values.kron(other)` only when `values` resolves to a supported numeric
    matrix kind. The result expands both dimensions, uses independent fixed
    float-matrix storage, and exposes only
    rows/columns/elements_count/get/copy with copy-only continuation. Float/int
    operands, nested copy, UDF-contained reads, wrong operands/indexes, broader
    helpers, non-numeric/non-matrix receivers, and the retained bound-diff gate
    are fixture-backed. No imported UDT identity or public schema field is
    added. Done.
29. The exact bound-matrix-difference continuation recognizes
    `values.diff(other)` only when `values` resolves to a supported numeric
    matrix kind and `other` is a numeric matrix or scalar. The result preserves
    left-to-right direction and selected matrix shape, uses independent fixed
    float-matrix storage, and exposes only rows/columns/elements_count/get/copy
    with copy-only continuation. Matrix/scalar operands, nested copy,
    UDF-contained reads, wrong operands/indexes, broader helpers,
    non-numeric/non-matrix receivers, and the retained bound-pow gate are
    fixture-backed. No imported UDT identity or public schema field is added.
    Done.
30. The exact bound-matrix-power continuation recognizes `values.pow(power)`
    only when `values` resolves to a supported numeric square matrix kind and
    `power` is simple int. The result preserves square shape across identity,
    copy, and positive powers, uses independent fixed float-matrix storage, and
    exposes only rows/columns/elements_count/get/copy with copy-only
    continuation. Float/int receivers, nested copy, UDF-contained reads, wrong
    powers/indexes, broader helpers, non-numeric/non-matrix receivers, and the
    retained bound-inverse gate are fixture-backed. No imported UDT identity
    or public schema field is added. Done.
31. The exact bound-matrix-inverse continuation recognizes `values.inv()` only
    when `values` resolves to a supported numeric square matrix kind. The
    result preserves invertible square shape, returns empty `0 x 0` or `na` at
    the established boundaries, uses independent fixed float-matrix storage,
    and exposes only rows/columns/elements_count/get/copy with copy-only
    continuation. Float/int receivers, nested copy, UDF-contained reads,
    wrong indexes, broader helpers, non-numeric/non-matrix receivers, and the
    retained bound-pseudo-inverse gate are fixture-backed. No imported UDT
    identity or public schema field is added. Done.
32. The exact bound-matrix-pseudo-inverse continuation recognizes
    `values.pinv()` only when `values` resolves to a supported numeric matrix
    kind. The result swaps rectangular shape, preserves singular matrix results
    and swapped zero-cell shapes, returns `na` for invalid-cell inputs, uses
    independent fixed float-matrix storage, and exposes only
    rows/columns/elements_count/get/copy with copy-only continuation. Float/int
    receivers, nested copy, UDF-contained reads, wrong indexes, broader
    helpers, non-numeric/non-matrix receivers, and the retained bound
    `values.eigenvectors()` gate are fixture-backed. No imported UDT identity
    or public schema field is added. Done.
33. The exact bound-matrix-eigenvector continuation recognizes
    `values.eigenvectors()` only when `values` resolves to a supported numeric
    square matrix kind. The result preserves real square shape, returns empty
    `0 x 0` or `na` at the established boundaries, uses independent fixed
    float-matrix storage, and exposes only rows/columns/elements_count/get/copy
    with copy-only continuation. Float/int receivers, nested copy,
    UDF-contained reads, wrong indexes, broader helpers, non-numeric/non-matrix
    receivers, and the retained matrix-valued bound `values.mult(other)` gate
    are fixture-backed. No imported UDT identity or public schema field is
    added. Done.
34. The exact bound-matrix-multiplication continuation recognizes matrix-valued
    `values.mult(other)` only when `values` resolves to a supported numeric
    matrix kind and `other` is a numeric matrix or scalar. The result preserves
    multiplied or scalar-selected shape, `na` and zero-inner-dimension
    behavior, uses independent fixed float-matrix storage, and exposes only
    rows/columns/elements_count/get/copy with copy-only continuation.
    Matrix-array overloads retain array-helper dispatch. Float/int operands,
    nested copy, UDF-contained reads, wrong result helpers/indexes,
    non-numeric/non-matrix receivers, and the retained UDF matrix-result gate
    are fixture-backed. No imported UDT identity or public schema field is
    added. Done.
35. Unqualified local-UDF results whose inferred call-specific result is a
    concrete supported matrix kind normalize through `$call_result` and expose
    only rows/columns/elements_count/get/copy with copy-only continuation.
    Parameter passthrough, block aliases, nested calls, same-kind control flow,
    matrix-operation and constructor returns, named/reordered arguments, zero
    dimensions, float/int/bool/string/color interleaving, and independent
    copies are fixture-backed. Unknown/`na`, scalar, array, map, qualified
    user-method/imported-function results, broader helpers, mutation, and
    terminal-read continuation remain fail closed. No imported UDT identity or
    public schema field is added. Done.
36. Unqualified local-UDF results whose call-specific result retains one
    concrete supported scalar map template expose only
    size/get/contains/copy through `$call_result`, with copy-only continuation.
    Parameter passthrough, block aliases, nested calls, same-template control
    flow, constructed/copied returns, named/reordered arguments, empty maps,
    scalar template interleaving, and independent copies are fixture-backed.
    Unknown/`na`, scalar, array, matrix, qualified user-method/imported-function
    results, wrong templates/keys, broader helpers, mutation, and terminal-read
    continuation remain fail closed. No imported UDT identity or public schema
    field is added. Done.
37. Local user-method results whose call-specific result retains one concrete
    supported scalar map template expose only size/get/contains/copy with
    copy-only continuation. Analysis records root-source method-call
    provenance so receiver-style, local-type-qualified, direct-constructor-
    receiver, block-return, nested-method, same-template control-flow,
    constructed-result, scalar-template-interleaving, and independent-copy
    paths lower without admitting imported methods. Unresolved/mixed templates,
    broader helpers, mutation, and terminal-read continuation remain fail
    closed. No imported UDT identity or public schema field is added. Done.
38. Imported user-method results whose call-specific result retains one
    concrete supported scalar map template expose only size/get/contains/copy
    with copy-only continuation. Source-context-aware method-call provenance
    preserves receiver-style, alias-qualified, direct-constructor-receiver,
    block-return, nested-method, same-template control-flow,
    constructed-result, scalar-template-interleaving, same-library dual-alias,
    and independent-copy paths. Imported functions, unresolved/mixed
    templates, broader helpers, mutation, and terminal-read continuation
    remain fail closed. No imported UDT identity is carried into map metadata
    and no public schema field is added. Done.
39. Registered imported pure-function results whose call-specific result
    retains one concrete supported scalar map template expose only
    size/get/contains/copy with copy-only continuation. Qualified function
    provenance preserves alias-qualified, block-return, nested-function,
    same-template control-flow, constructed-result, scalar-template
    interleaving, same-library dual-alias, and independent-copy paths. Scalar
    or unresolved/mixed results, broader helpers, mutation, and terminal-read
    continuation remain fail closed. No imported UDT identity is carried into
    map metadata and no public schema field is added. Done.
40. Local and imported user-method results whose call-specific result is one
    concrete supported matrix kind expose only
    rows/columns/elements_count/get/copy with copy-only continuation. Recorded
    root-source and source-context-aware method-call provenance preserves
    receiver-style, local-type-qualified or alias-qualified, direct-
    constructor-receiver, block-return, nested-method, same-kind-control-flow,
    float/int/bool/string/color, zero-dimension, same-library dual-alias, and
    independent-copy paths. Unknown/`na`, non-matrix or unresolved method
    results, remaining user-function matrix results, broader helpers, mutation,
    and terminal-read continuation remain fail closed. No imported UDT identity
    is carried into matrix metadata and no public schema field is added. Done.
41. Registered imported pure-function results whose call-specific result is one
    concrete supported matrix kind expose only
    rows/columns/elements_count/get/copy with copy-only continuation. Qualified
    function provenance preserves alias-qualified, block-return, nested-
    function, same-kind-control-flow, float/int/bool/string/color, zero-
    dimension, same-library dual-alias, and independent-copy paths. Unknown/
    `na`, non-matrix, unregistered or unresolved function results, broader
    helpers, mutation, and terminal-read continuation remain fail closed. No
    imported UDT identity is carried into matrix metadata and no public schema
    field is added. Done.
42. Concrete scalar-map call results from supported constructors, namespace
    copies, local/imported pure functions, and local/imported user methods
    expose `.keys()` as a fresh key-kind-preserving array. Direct binding,
    int/float/bool/string/color key kinds, size/get/first/last/copy, copy-only
    array continuation, dual-alias paths, and source-map independence are
    fixture-backed. Direct `.values()`, map or call-result-array mutation,
    unsupported templates, broader helpers, and terminal key-reader
    continuation remain fail closed. No imported UDT identity or public schema
    field is added. Done.
43. The same concrete scalar-map call-result producers expose `.values()` as a
    fresh value-kind-preserving array. Direct binding, int/float/bool/string/
    color value kinds, size/get/first/last/copy, copy-only array continuation,
    dual-alias paths, and source-map independence are fixture-backed. Map or
    call-result-array mutation, unsupported templates, broader helpers, and
    terminal key/value-reader continuation remain fail closed. No imported UDT
    identity or public schema field is added. Done.
44. Every existing concrete matrix call-result producer exposes `.row(index)`
    as a fresh element-kind-preserving scalar array. Namespace and bound matrix
    operations, exact five-scalar `matrix.new<T>` templates, local UDFs,
    local/imported user methods, and imported pure functions support direct
    binding plus size/get/first/last/copy with copy-only array continuation.
    Index checking, copy independence, five scalar element kinds, and imported
    dual-alias paths are fixture-backed; `.col()`, mutation, broader helpers,
    and terminal row-reader continuation remain fail closed. No imported UDT
    identity or public schema field is added. Done.
45. The same concrete matrix call-result producers expose `.col(index)` as a
    fresh element-kind-preserving scalar array with direct binding and
    size/get/first/last/copy plus copy-only array continuation. Namespace and
    bound operations, five-scalar constructors, local/imported function and
    method provenance, index checks, copy independence, and dual aliases are
    fixture-backed. Mutation, broader matrix helpers, and terminal column-
    reader continuation remain fail closed. No imported UDT identity or public
    schema field is added. Done.
46. Concrete numeric matrix call-result producers expose `.eigenvalues()` as a
    fresh `array<float>` with size/get/first/last/copy and copy-only array
    continuation. Existing numeric type checks and square-matrix runtime
    boundaries remain authoritative. Namespace/bound operations, local and
    imported function/method provenance, dual aliases, copy independence, non-
    numeric rejection, and array-mutation rejection are fixture-backed. No
    imported UDT identity or public schema field is added. Done.
47. Every existing concrete matrix call-result producer exposes terminal
    `.is_square()`. It accepts all five supported scalar matrix kinds, reuses
    the ordinary row/column equality rule, and returns a simple bool without a
    result-prefix transition. Namespace/bound operations, exact templates,
    local/imported function and method provenance, true/false shapes, dual
    aliases, invalid arity, and terminal continuation are fixture-backed. No
    imported UDT identity or public schema field is added. Done.
48. Every existing concrete numeric matrix call-result producer exposes
    terminal `.is_zero()`. It retains the float/int type check and ordinary
    exact-zero, zero-element, `na`-cell, and upstream-`na` rules, returns a
    simple bool, and creates no result prefix. Namespace/bound operations,
    exact numeric templates, local/imported function and method provenance,
    dual aliases, non-numeric rejection, invalid arity, and terminal
    continuation are fixture-backed. No imported UDT identity or public schema
    field is added. Done.
49. The same concrete numeric matrix call-result producer set exposes terminal
    `.is_binary()`. It retains the float/int type check and ordinary strict
    0-or-1, zero-element, `na`-cell, and upstream-`na` rules, returns a simple
    bool, and creates no result prefix. Namespace/bound operations, exact
    numeric templates, local/imported function and method provenance, dual
    aliases, non-numeric rejection, invalid arity, and terminal continuation
    are fixture-backed. No imported UDT identity or public schema field is
    added. Done.
50. The same concrete numeric matrix call-result producer set exposes terminal
    `.is_diagonal()`. It permits rectangular matrices and arbitrary main-
    diagonal cells, requires exact-zero off-diagonal cells, returns true for
    empty matrices and false for off-diagonal `na`, propagates upstream `na`,
    and creates no result prefix. Numeric rejection, provenance/dual aliases,
    invalid arity, and terminal continuation are fixture-backed. No imported
    UDT identity or public schema field is added. Done.
51. The same concrete numeric matrix call-result producer set exposes terminal
    `.is_identity()`. It requires square shape, exact-one diagonal and exact-
    zero off-diagonal cells, returns false for every `na`, true for empty 0×0,
    propagates upstream `na`, and creates no result prefix. Numeric rejection,
    provenance/dual aliases, invalid arity, and terminal continuation are
    fixture-backed. No imported UDT identity or public schema field is added.
    Done.
52. The same concrete numeric matrix call-result producer set exposes terminal
    `.is_symmetric()`. It requires square shape and exact equality of
    transposed pairs, returns false for every `na`, true for empty 0×0,
    propagates upstream `na`, and creates no result prefix. Numeric rejection,
    provenance/dual aliases, invalid arity, and terminal continuation are
    fixture-backed. No imported UDT identity or public schema field is added.
    Done.
53. The same concrete numeric matrix call-result producer set exposes terminal
    `.is_antisymmetric()`. It requires square shape, an exact-zero main
    diagonal, and exact negation across transposed pairs, returns false for
    every `na`, true for empty 0×0, propagates upstream `na`, and creates no
    result prefix. Numeric rejection, provenance/dual aliases, invalid arity,
    and terminal continuation are fixture-backed. No imported UDT identity or
    public schema field is added. Done.
54. The same concrete numeric matrix call-result producer set exposes terminal
    `.is_stochastic()`. It requires a non-empty matrix of finite non-negative
    values and returns true when every row or every column sums exactly to one;
    empty matrices, invalid cells, and negative values are false, while
    upstream `na` propagates. It creates no result prefix. Numeric rejection,
    provenance/dual aliases, invalid arity, and terminal continuation are
    fixture-backed. No imported UDT identity or public schema field is added.
    Done.
55. The same concrete numeric matrix call-result producer set exposes terminal
    `.sum()` with its fixed `series float` result. It ignores `na` cells,
    returns `na` for empty, all-`na`, non-finite, or upstream-`na` results, and
    creates no result prefix. Numeric rejection, copy continuation, provenance/
    dual aliases, invalid arity, and terminal continuation are fixture-backed.
    No imported UDT identity or public schema field is added. Done.
56. The same concrete numeric matrix call-result producer set exposes terminal
    `.avg()` with its fixed `series float` result. It averages only non-`na`
    cells, returns `na` for empty, all-`na`, non-finite, or upstream-`na`
    results, and creates no result prefix. Numeric rejection, copy continuation,
    provenance/dual aliases, invalid arity, and terminal continuation are
    fixture-backed. No imported UDT identity or public schema field is added.
    Done.
57. The same concrete numeric matrix call-result producer set exposes terminal
    `.min()` with its fixed `series float` result. It scans only non-`na`
    cells, returns `na` for empty, all-`na`, non-finite, or upstream-`na`
    results, and creates no result prefix. Numeric rejection, copy continuation,
    provenance/dual aliases, invalid arity, and terminal continuation are
    fixture-backed. No imported UDT identity or public schema field is added.
    Done.
58. The same concrete numeric matrix call-result producer set exposes terminal
    `.max()` with its fixed `series float` result. It scans only non-`na`
    cells, returns `na` for empty, all-`na`, non-finite, or upstream-`na`
    results, and creates no result prefix. Numeric rejection, copy continuation,
    provenance/dual aliases, invalid arity, and terminal continuation are
    fixture-backed. No imported UDT identity or public schema field is added.
    Done.
59. The same concrete numeric matrix call-result producer set exposes terminal
    `.mode()` with its fixed `series float` result. It ignores `na` cells,
    selects the smallest value among equally frequent repeats, returns `na` for
    empty, all-`na`, no-repeat, selected non-finite, or upstream-`na` results,
    and creates no result prefix. Numeric rejection, copy continuation,
    provenance/dual aliases, invalid arity, and terminal continuation are
    fixture-backed. No imported UDT identity or public schema field is added.
    Done.
60. The same concrete numeric matrix call-result producer set exposes terminal
    `.trace()` with its fixed `series float` result. It sums non-`na` main-
    diagonal cells over `min(rows, columns)`, returns `na` for an empty/all-
    `na` diagonal, non-finite sum, or upstream-`na` result, and creates no
    result prefix. Numeric rejection, copy continuation, provenance/dual
    aliases, invalid arity, and terminal continuation are fixture-backed. No
    imported UDT identity or public schema field is added. Done.
61. The same concrete numeric matrix call-result producer set exposes terminal
    `.det()` with its fixed `series float` result. It retains the runtime
    square-matrix error, `0 x 0 = 1.0`, singular zero, and invalid-cell/non-
    finite/upstream-`na` results without adding static shape inference or a
    result prefix. Numeric rejection, copy continuation, provenance/dual
    aliases, invalid arity, and terminal continuation are fixture-backed. No
    imported UDT identity or public schema field is added. Done.
62. The same concrete numeric matrix call-result producer set exposes terminal
    `.rank()` with its fixed `series int` result. It supports rectangular and
    singular matrices, returns `0` for zero-element matrices, returns `na` for
    invalid/non-finite cells or upstream `na`, and creates no result prefix.
    Numeric rejection, copy continuation, provenance/dual aliases, invalid
    arity, and terminal continuation are fixture-backed. No imported UDT
    identity or public schema field is added. Done.
63. Every existing concrete matrix call-result producer also exposes
    `.transpose()` as an independent, element-kind-preserving matrix
    continuation with swapped row/column counts. It retains the matrix-result
    prefix across `.copy()` and repeated `.transpose()` chains, propagates
    upstream `na`, and adds no imported UDT identity or public schema field.
    Namespace/bound operations, exact templates, local/imported functions and
    methods, five-kind reads, zero-cell shapes, source independence,
    provenance/dual aliases, repeated continuation, and invalid arity are
    fixture-backed. Done.
64. Every existing concrete matrix call-result producer also exposes
    `.submatrix(...)` as an independent, element-kind-preserving matrix
    continuation over an optional/default half-open range. It preserves empty
    row/column shapes, propagates upstream `na`, retains the matrix-result
    prefix, and adds no imported UDT identity or public schema field.
    Namespace/bound operations, exact templates, local/imported functions and
    methods, named arguments, nested ranges, five-kind reads, source
    independence, provenance/dual aliases, invalid types/arity, and runtime
    bounds are fixture-backed. Done.
65. Every existing concrete numeric matrix call-result producer additionally
    exposes `.inv()` as an independent fixed-`matrix<float>` continuation. It
    preserves square shape for invertible inputs, returns empty `0 x 0` for
    empty input, yields `na` for singular, invalid-cell, non-finite, or
    upstream-`na` inputs, and retains the matrix-result prefix without adding
    imported UDT identity or a public schema field. Namespace/bound operations,
    local/imported functions and methods, int-to-float lowering, nested chains,
    source independence, provenance/dual aliases, invalid types/arity, and the
    runtime non-square boundary are fixture-backed. Done.
66. The same concrete numeric matrix call-result producer set additionally
    exposes `.pinv()` as an independent fixed-`matrix<float>` continuation. It
    swaps rectangular row/column counts, preserves singular matrix-valued
    results and swapped zero-cell shapes, yields `na` for invalid-cell, non-
    finite, or upstream-`na` inputs, and retains the matrix-result prefix
    without adding imported UDT identity or a public schema field. Namespace/
    bound operations, local/imported functions and methods, int-to-float
    lowering, nested/double chains, source independence, provenance/dual
    aliases, invalid types/arity, and rectangular/singular/zero-cell boundaries
    are fixture-backed. Done.
67. The same concrete numeric matrix call-result producer set additionally
    exposes `.eigenvectors()` as an independent fixed-`matrix<float>`
    continuation. It preserves square shape for a complete real eigenvector
    basis, returns empty `0 x 0`, retains the runtime non-square error, yields
    `na` for invalid-cell, non-finite, non-real, incomplete, or upstream-`na`
    results, and retains the matrix-result prefix without adding imported UDT
    identity or a public schema field. Namespace/bound operations,
    local/imported functions and methods, int-to-float lowering, nested/double
    chains, source independence, provenance/dual aliases, invalid types/arity,
    and runtime failure boundaries are fixture-backed. Done.
68. The same concrete numeric matrix call-result producer set additionally
    exposes `.pow(power)` as an independent fixed-`matrix<float>` continuation.
    It retains the simple-int argument gate and runtime square-matrix boundary,
    supports identity/copy/positive powers and empty `0 x 0`, preserves `na`
    cells for positive powers, retains negative and `na` power errors, and
    keeps the matrix-result prefix without adding imported UDT identity or a
    public schema field. Namespace/bound operations, local/imported functions
    and methods, int-to-float lowering, nested powers, source independence,
    provenance/dual aliases, invalid types/arity, and runtime failure
    boundaries are fixture-backed. Done.
69. The same concrete numeric matrix call-result producer set additionally
    exposes `.kron(other)` as an independent fixed-`matrix<float>`
    continuation. It retains the numeric-matrix operand gate, multiplies both
    source row and column dimensions, preserves `na` cells and zero dimensions,
    propagates upstream `na`, keeps the matrix cell-budget error, and retains
    the matrix-result prefix without adding imported UDT identity or a public
    schema field. Namespace/bound operations, local/imported functions and
    methods, int-to-float lowering, nested Kronecker products, source
    independence, provenance/dual aliases, invalid types/arity, and runtime
    failure boundaries are fixture-backed. Done.
70. The same concrete numeric matrix call-result producer set additionally
    exposes `.diff(other)` as an independent fixed-`matrix<float>`
    continuation. It retains the numeric-matrix-or-scalar operand gate,
    preserves receiver shape and left-to-right subtraction, propagates `na`
    cells, `na` scalars, and upstream `na`, preserves zero dimensions, keeps
    the matching-shape runtime error for matrix operands, and retains the
    matrix-result prefix without adding imported UDT identity or a public
    schema field. Namespace/bound operations, local/imported functions and
    methods, int-to-float lowering, nested differences, scalar and matrix
    operands, source independence, provenance/dual aliases, invalid types/
    arity, and runtime failure boundaries are fixture-backed. Done.
71. The same concrete numeric matrix call-result producer set additionally
    exposes `.mult(other)` with result-type-directed continuation. Matrix and
    scalar operands return independent fixed `matrix<float>` results with
    multiplied or receiver-preserved shape; numeric-array operands return an
    independent `array<float>` with one value per receiver row. The existing
    numeric operand checks, `na`, zero-inner-dimension, multiplication order,
    cell-budget, dimension, and vector-length boundaries remain unchanged, and
    the resolved result selects the closed matrix or array helper set without
    adding imported UDT identity or a public schema field. Namespace/bound
    operations, local/imported functions and methods, int-to-float lowering,
    nested multiplication, source independence, provenance/dual aliases,
    invalid types/arity, and runtime failure boundaries are fixture-backed.
    Done.
72. Every existing concrete array call-result producer additionally exposes
    terminal `.includes(value)`. This covers qualified and unqualified local/
    imported UDF and method results, the static built-in array producer set,
    the seven cross-namespace scalar-array producers, matrix-derived row/
    column/eigenvalue arrays, map key/value arrays, and array-returning
    `matrix.mult` overloads. It reuses ordinary element-kind and concrete
    imported-UDT identity argument checks plus structural/object equality,
    returns `series bool`, is false for an empty concrete array, propagates an
    upstream `na` array, performs no mutation, and creates no result prefix.
    Scalar, drawing/chart-point, local/imported UDT, A-to-B-to-A, dual-alias
    isolation, copy continuation, invalid type/identity/arity, and terminal-
    continuation paths are fixture-backed. It adds no imported UDT identity or
    public schema field. Done.
73. Every existing concrete array call-result producer additionally exposes
    terminal `.indexof(value)`. It reuses ordinary element-kind and concrete
    imported-UDT identity argument checks plus structural/object equality,
    returns the first zero-based match as `simple int`, returns `-1` for missing
    or empty concrete arrays and for an upstream `na` array, performs no
    mutation, and creates no result prefix. Static/cross-namespace producers,
    local/imported UDF and method results, matrix-derived and map-derived
    arrays, array-returning `matrix.mult`, scalar/drawing/chart-point/local/
    imported UDT, A-to-B-to-A, dual-alias isolation, copy continuation, invalid
    type/identity/arity, and terminal-continuation paths are fixture-backed. It
    adds no imported UDT identity or public schema field. Done.
74. Every existing concrete array call-result producer additionally exposes
    terminal `.lastindexof(value)`. It reuses ordinary element-kind and
    concrete imported-UDT identity argument checks plus structural/object
    equality, returns the last zero-based match as `simple int`, returns `-1`
    for missing or empty concrete arrays and for an upstream `na` array,
    performs no mutation, and creates no result prefix. Repeated scalar and
    structural-UDT values, static/cross-namespace producers, local/imported UDF
    and method results, matrix-derived and map-derived arrays, array-returning
    `matrix.mult`, A-to-B-to-A, dual-alias isolation, copy continuation,
    invalid type/identity/arity, and terminal-continuation paths are fixture-
    backed. It adds no imported UDT identity or public schema field. Done.
75. Concrete numeric array call results additionally expose terminal
    `.binary_search(value)`. Qualified and unqualified local/imported UDF and
    method results returning `array<int>` or `array<float>`, registered static
    producers, numeric cross-namespace producers, matrix-derived numeric
    arrays, numeric map key/value arrays, and array-returning `matrix.mult`
    overloads share the ordinary numeric receiver/value checks. Ascending
    contents are caller-owned; exact lower-bound search returns the leftmost
    duplicate match as `simple int` or `-1` for missing, empty, and upstream-
    `na` arrays. It is non-mutating and terminal. Imported UDT arrays and every
    nonnumeric/object array remain rejected; invalid type/arity, copy-
    continuation, terminal-continuation, and dual-alias paths are fixture-
    backed. It adds no imported UDT identity or public schema field. Done.
76. The same concrete numeric array call-result producer set additionally
    exposes terminal `.binary_search_leftmost(value)`. It preserves the numeric
    receiver/value and caller-owned ascending-input gates. Exact duplicates
    return their first index; misses return the nearest-left element index,
    clamped to `0` below the minimum and the last index above the maximum.
    Empty and upstream-`na` arrays return `-1`; the `simple int` result is non-
    mutating and terminal. Static/cross-namespace, matrix/map-derived, local/
    imported function/method, duplicate, between-value, clamp, invalid type/
    arity, dual-alias, copy-continuation, and terminal-continuation paths are
    fixture-backed. Imported UDT and nonnumeric result arrays remain rejected;
    no imported identity or public schema field is widened. Done.
77. The same numeric producer set exposes terminal
    `.binary_search_rightmost(value)`. Exact duplicates return their last index;
    misses return the nearest-right element index, clamped to `0` below the
    minimum and the last index above the maximum. It retains the numeric/
    ascending, empty/upstream-`na` `-1`, `simple int`, non-mutation, and terminal
    boundaries. Static/cross-namespace, matrix/map-derived, local/imported
    function/method, duplicate, between-value, clamp, invalid type/arity, dual-
    alias, copy-continuation, and terminal-continuation paths are fixture-backed.
    Imported UDT and nonnumeric result arrays remain rejected; no imported
    identity or public schema field is widened. Done.
78. The same concrete numeric array-result producer set exposes `.abs()` as a
    fresh same-kind array transformation. Int/float kind, `na` elements, empty
    arrays, upstream `na`, source independence, and subsequent admitted array
    reads/copy/abs chains are preserved. Imported UDT and every nonnumeric
    result remain rejected; no imported identity or public schema field is
    widened. Done.
79. The same numeric producer set exposes terminal `.min(nth?)`. It preserves
    receiver-derived series int/float results, filtered ascending zero-based
    rank semantics, dynamic integer ranks, duplicates, and empty/all-`na`/
    upstream-`na` plus invalid-rank `na` boundaries. Imported UDT and nonnumeric
    arrays remain rejected; no imported identity or public schema field is
    widened. Done.
80. The same numeric producer set exposes terminal `.max(nth?)` with descending
    zero-based rank semantics. It retains receiver-derived series int/float,
    dynamic integer ranks, duplicates, empty/all-`na`/upstream-`na`, invalid-
    rank `na`, and nonnumeric/imported-UDT rejection without widening imported
    identity or public schemas. Done.
81. The same numeric producer set exposes terminal `.sum()`. It retains
    receiver-derived series int/float, filters `na`, returns `na` for empty,
    all-`na`, or upstream-`na` arrays, and keeps nonnumeric/imported-UDT,
    arity, and terminal-continuation boundaries closed without widening
    imported identity or public schemas. Done.
82. The same numeric producer set exposes terminal `.avg()`. It always returns
    series float, shares filtered `na` and empty/all-`na`/upstream-`na`
    behavior, converts non-finite results to `na`, and keeps nonnumeric/
    imported-UDT, arity, and terminal-continuation boundaries closed. Done.
83. The same numeric producer set exposes terminal `.range()`. It preserves
    receiver-derived series int/float, computes filtered maximum minus minimum,
    returns `na` for empty/all-`na`/upstream-`na` or non-finite float
    differences, and keeps nonnumeric/imported-UDT, arity, and terminal-
    continuation boundaries closed. Done.
84. The same numeric producer set exposes terminal `.median()`. It sorts
    filtered non-`na` values, returns the odd middle or even middle-pair mean,
    preserves receiver-derived series int/float, and truncates integer means
    toward zero. Empty/all-`na`/upstream-`na` arrays and non-finite float
    results return `na`; nonnumeric/imported-UDT, arity, provenance, and
    terminal-continuation boundaries remain closed. Done.
85. The same numeric producer set exposes terminal `.mode()`. It returns the
    most frequent filtered value in the receiver-derived series int/float kind,
    chooses the smaller value for tied frequencies, and requires at least one
    repetition. Empty/all-`na`/upstream-`na` and all-unique arrays return `na`;
    nonnumeric/imported-UDT, arity, provenance, and terminal-continuation
    boundaries remain closed. Done.
86. The same numeric producer set exposes terminal
    `.percentile_nearest_rank(percentage)`. It filters and sorts values, applies
    ceiling-based nearest-rank selection with 0/100 endpoints, preserves
    receiver-derived series int/float, and accepts positional or named series/
    simple numeric percentages. Empty/all-`na`/upstream-`na`, runtime typed-
    `na`, out-of-range, nonnumeric/imported-UDT, arity, provenance, and terminal-
    continuation boundaries remain closed. Done.
87. The same numeric producer set exposes terminal
    `.percentile_linear_interpolation(percentage)`. It interpolates sorted
    floor/ceiling members at `percentage / 100 * (count - 1)`, always returns
    series float for int/float and single-element inputs, and accepts positional
    or named series/simple numeric percentages. Empty/all-`na`/upstream-`na`,
    runtime typed-`na`, out-of-range, non-finite-result, nonnumeric/imported-UDT,
    arity, provenance, and terminal-continuation boundaries remain closed. Done.
88. The same numeric producer set exposes terminal `.percentrank(index)`. It
    selects the target from the original array index, filters `na` only from
    the comparison population, counts duplicates independently, and returns
    fixed series float. Positional or named simple-int-compatible indexes are
    accepted. Empty/all-`na`/upstream-`na`, target-`na`, runtime typed-`na`,
    negative, out-of-range, nonnumeric/imported-UDT, arity, provenance, and
    terminal-continuation boundaries remain closed. Done.
89. The same numeric producer set exposes terminal
    `.covariance(id2, biased?)`. It requires a same-length numeric second array,
    aligns cells by original index, filters pairs containing `na`, defaults to
    population bias, uses the sample denominator for `false` or `na`, and
    returns fixed series float. Empty/all-`na`/upstream-`na`, mismatched-length,
    insufficient-sample, non-finite-result, nonnumeric/imported-UDT second-
    array, arity, provenance, and terminal-continuation boundaries remain
    closed. Done.
90. The same numeric producer set exposes transforming `.standardize()`. It
    returns an independent fixed float array, computes mean and population
    standard deviation over non-`na` values, preserves `na` positions, maps
    numeric positions to `na` for zero or non-finite deviation, returns empty
    for empty/all-`na`, and propagates upstream `na`. Nonnumeric/imported-UDT,
    arity, provenance, source-independence, and copy/abs/standardize/sort_indices
    continuation boundaries are fixture-backed. Done.
91. The same numeric producer set exposes terminal `.variance(biased?)`. It
    filters `na`, returns fixed series float, uses population bias by default
    or for `true`, and sample bias for `false` or `na`. Single-value population
    variance is zero; empty/all-`na`/upstream-`na`, insufficient-sample, and
    non-finite results retain `na`. Nonnumeric/imported-UDT, invalid bias/
    arity, provenance, non-mutation, and terminal-continuation boundaries are
    fixture-backed. Done.
92. The same numeric producer set exposes terminal `.stdev(biased?)`. It takes
    the square root of the same selected filtered population or sample
    variance and retains bias, single-value population zero, fixed series-
    float, empty/all-`na`/upstream-`na`, insufficient-sample, non-finite,
    nonnumeric/imported-UDT, invalid type/arity, provenance, non-mutation, and
    terminal-continuation boundaries. Done.
93. Concrete int, float, or string array call results expose transforming
    `.sort_indices(order?)` across local/imported functions and methods plus
    the existing static, cross-namespace, matrix/map-derived producer sets. It
    returns an independent fixed int-index array with stable original indexes,
    default ascending or explicit descending order, established float-`na` and
    string-empty placement, empty results, upstream-`na` propagation, source
    non-mutation, and nested sort/copy/read/search/transformation/statistic
    continuation. Bool/color/object/chart-point, invalid order/arity, direct
    mutation, and imported-UDT result `sort_field` ordering before binding
    remain closed. Done.
94. Concrete bool, int, or float array call results expose terminal `.every()`
    across local/imported functions and methods plus the existing static,
    cross-namespace, and matrix/map-derived producer sets. Nonzero numerics and
    `true` are truthy; zero, `false`, and element `na` are false. Empty results
    return true, upstream `na` propagates, and the source remains unchanged.
    String/color/object/chart-point/imported-UDT, extra-arity, and terminal-
    continuation boundaries remain closed. Done.
95. The same concrete bool/int/float result families expose terminal `.some()`.
    It returns true when any nonzero numeric or `true` element exists, treats
    zero, `false`, and element `na` as nonsatisfying, returns false for empty
    arrays, propagates upstream `na`, leaves sources unchanged, and retains the
    same unsupported-kind, extra-arity, imported-UDT, and terminal-continuation
    boundaries. Done.
96. Concrete scalar array call results and concrete same-imported scalar-tree
    UDT-array results expose terminal `.join(separator?)` across imported/local
    functions and methods plus the existing producer families. Ordinary
    default/explicit/`na` separators, scalar/color/imported-UDT formatting,
    empty-string/upstream-`na` results, source non-mutation, and the 40960-
    character limit are preserved. Object/chart-point, invalid separator/
    arity, unresolved identity, and terminal-continuation boundaries remain
    closed. Done.
97. Every concrete array call result additionally exposes transforming
    `.slice(index_from, index_to)`. The result preserves scalar, object,
    `chart.point`, and concrete same-imported scalar-tree UDT identity, retains
    the ordinary half-open shallow live-window aliasing, and may continue
    through the closed array helper set. Parent-to-window and window-to-parent
    writes, nested slices, empty/upstream-`na`/invalid-range behavior,
    positional or named simple-int-compatible bounds, invalid type/arity,
    same-library identity isolation, and matrix/map-derived snapshot
    boundaries are fixture-backed. Done.
98. Every concrete array call result additionally exposes terminal top-level
    `.clear()`. It returns `void`, accepts no explicit arguments, tolerates
    empty or upstream-`na` receivers, and cannot continue. Imported/local UDF
    and method alias results plus `array.concat` results clear shared backing;
    nested slices delete their live parent window; fresh matrix/map/
    `matrix.mult` snapshots remain independent. Mutation inside UDF bodies and
    every other direct postfix mutation remain rejected at this slice. No
    imported identity or public schema field is widened. Done.
99. The same producer set additionally exposes terminal top-level `.reverse()`.
    It returns `void`, accepts no explicit arguments, cannot continue, and
    preserves scalar, object, `chart.point`, and concrete imported UDT array
    identity. Alias results reverse shared backing, nested slices reorder only
    their live parent window, and fresh matrix/map/`matrix.mult` snapshots
    remain source-independent. Empty/upstream-`na` results are no-ops; UDF-body
    and all remaining direct mutations stay rejected. No imported identity or
    public schema field is widened. Done.
100. The same producer set additionally exposes terminal top-level `.pop()`.
    It accepts no explicit arguments, removes and returns the final resolved
    scalar/object/`chart.point` or concrete imported UDT element, returns `na`
    for empty or upstream-`na`, and cannot continue. Imported/local alias
    results shrink shared backing, nested slices delete from their live parent
    window, and fresh matrix/map/`matrix.mult` snapshots remain source-
    independent. UDF-body and all remaining direct mutations stay rejected.
    No imported identity or public schema field is widened. Done.
101. The same producer set additionally exposes terminal top-level `.shift()`.
    It accepts no explicit arguments, removes and returns the first resolved
    scalar/object/`chart.point` or concrete imported UDT element, preserves
    remaining-element order, returns `na` for empty or upstream-`na`, and cannot
    continue. Imported/local alias results shrink shared backing, nested slices
    delete the first element from their live parent window, and fresh matrix/
    map/`matrix.mult` snapshots remain source-independent. UDF-body and all
    remaining direct mutations stay rejected. No imported identity or public
    schema field is widened. Done.
102. The same producer set additionally exposes terminal top-level
    `.remove(index)`. It accepts one simple-int-compatible index, removes and
    returns the selected positive or in-range negative scalar/object/
    `chart.point` or concrete imported UDT element, and cannot continue.
    Explicit `na` indexes and upstream-`na` receivers return `na` without
    mutation; out-of-range indexes retain runtime errors. Imported/local alias
    results and nested slices delete from shared backing, while fresh matrix/
    map/`matrix.mult` snapshots remain source-independent. UDF-body and all
    remaining direct mutations stay rejected. No imported identity or public
    schema field is widened. Done.
103. The same producer set additionally exposes terminal top-level
    `.push(value)`. It accepts one element-compatible scalar/object/
    `chart.point` or concrete imported UDT value, appends at the resolved
    result's end, returns `void`, and cannot continue. Imported/local alias
    results and nested slices update shared parent backing, while fresh matrix/
    map/`matrix.mult` snapshots remain source-independent. Mismatched kind or
    imported identity, arity, capacity, and UDF-body boundaries remain
    rejected, while upstream-`na` results remain no-ops after value evaluation.
    No imported identity or public schema field is widened. Done.
104. The same producer set additionally exposes terminal top-level
    `.unshift(value)`. It accepts one element-compatible scalar/object/
    `chart.point` or concrete imported UDT value, prepends at the resolved
    result's start, returns `void`, and cannot continue. Imported/local alias
    results and nested slices update shared parent backing, while fresh matrix/
    map/`matrix.mult` snapshots remain source-independent. Upstream-`na`
    results remain no-ops after value evaluation; mismatched kind or imported
    identity, arity, capacity, and UDF-body boundaries remain rejected. No
    imported identity or public schema field is widened. Done.
105. The same producer set additionally exposes terminal top-level
    `.insert(index, value)`. It accepts a simple-int-compatible index plus one
    element-compatible scalar/object/`chart.point` or concrete imported UDT
    value, inserts at the positive, in-range negative, or end position, returns
    `void`, and cannot continue. Imported/local alias results and nested slices
    update shared parent backing; fresh matrix/map/`matrix.mult` snapshots stay
    source-independent. Explicit `na` indexes and upstream-`na` results remain
    no-ops after value evaluation; bounds, kind/identity, arity, capacity, and
    UDF-body boundaries remain fixture-backed. No imported identity or public
    schema field is widened. Done.
106. The same producer set additionally exposes terminal top-level
    `.set(index, value)`. It accepts a simple-int-compatible index plus one
    element-compatible scalar/object/`chart.point` or concrete imported UDT
    value, replaces the positive or in-range negative slot without changing
    length, returns `void`, and cannot continue. Imported/local alias results
    and nested slices write shared parent backing; fresh matrix/map/
    `matrix.mult` snapshots stay source-independent. Explicit `na` indexes and
    upstream-`na` results remain no-ops after value evaluation; empty/out-of-
    range, kind/identity, arity, and UDF-body boundaries remain fixture-backed.
    No imported identity or public schema field is widened. Done.
107. The same producer set additionally exposes terminal top-level
    `.fill(value, index_from?, index_to?)`. It validates an element-compatible
    scalar/object/`chart.point` or concrete imported UDT value plus optional
    simple-int-compatible half-open bounds; omitted bounds fill the full
    result. Imported/local alias results and nested slices update shared parent
    backing, while fresh matrix/map/`matrix.mult` snapshots stay source-
    independent. Explicit `na`, negative, reversed, oversized, empty, and
    upstream-`na` cases no-op after all supplied arguments are evaluated. It
    returns `void`, cannot continue, stays rejected inside UDFs, and widens no
    imported identity or public schema field. Done.
108. The same producer set additionally exposes terminal top-level
    `.sort(order?, sort_field?)`. Concrete int/float/string results use
    ordinary stable ascending/default or descending ordering. Concrete
    imported scalar-tree UDT results require a compile-time root int/float/
    string field resolved against their exact imported identity. Imported/
    local aliases and nested slices reorder shared parent backing, while fresh
    matrix/map/`matrix.mult` snapshots stay source-independent. Empty and
    upstream-`na` results no-op after order evaluation; unsupported kinds,
    field/order/arity, terminal continuation, and UDF mutation remain closed.
    No imported identity or public schema field is widened. Done.
109. Transforming `.sort_indices(order?, sort_field?)` now accepts concrete
    same-imported scalar-tree UDT array call results from the identity-
    preserving built-in and imported UDF/method producer paths. The required
    compile-time root int/float/string field is resolved against the exact
    imported identity. It returns a fresh stable `array<int>` of original
    indexes, leaves the imported UDT source unchanged, and may continue through
    the existing closed int-array chain. Missing, unknown, dynamic, bool/non-
    root fields, unresolved/mixed identities, and non-scalar imported UDTs stay
    rejected. No imported identity or public schema field is widened. Done.
110. Every concrete array call result and derived-array continuation now
    exposes mutating, array-returning `.concat(id2)`. The source must preserve
    the receiver kind or exact imported scalar-tree UDT identity. The operation
    returns the first array id and may continue through the existing closed
    array-result chain. Imported/local alias results and live slices append to
    shared parent backing, while fresh namespace/map/matrix/`matrix.mult`
    snapshots remain source-independent. Empty source, upstream-`na`, self-
    concat cloning, capacity, kind/identity/arity, and UDF-side-effect behavior
    retain the ordinary `array.concat` contract. No imported identity or public
    schema field is widened. Done.
111. Concrete matrix results from imported pure functions and imported user
    methods, together with the existing built-in, bound, and local producer
    set, now expose terminal `.set(row, column, value)`. The operation retains
    concrete float/int/bool/string/color kind checks, simple-int indexes,
    bounds, upstream-`na`, `void`, no-continuation, and UDF-side-effect rules.
    Imported producers allocate fresh matrices, so writes do not escape to a
    source; local alias-returning producers retain shared-storage behavior. No
    imported UDT identity or public schema is widened. Done.
112. The same concrete matrix-result producer set now exposes terminal
    `.fill(value)`. It preserves float/int/bool/string/color value checks,
    replaces every cell, returns `void`, and cannot continue. Imported and
    built-in producers isolate writes in fresh matrices, while local alias-
    returning producers retain shared-storage behavior. Empty/upstream-`na`,
    invalid arity, and UDF-side-effect rules remain unchanged. No imported UDT
    identity or public schema is widened. Done.
113. The same concrete matrix-result producer set now exposes terminal
    `.reverse()`. It reverses the row-major cell sequence without changing
    shape, returns `void`, and cannot continue. Imported and built-in producers
    isolate writes in fresh matrices, while local alias-returning producers
    retain shared-storage behavior. Empty/upstream-`na`, invalid arity, and UDF
    side-effect rules remain unchanged. No imported UDT identity or public
    schema is widened. Done.
114. The same concrete matrix-result producer set now exposes terminal
    `.reshape(rows, columns)`. It preserves row-major cells, validates simple-
    int non-negative dimensions with unchanged element count, returns `void`,
    and cannot continue. Imported and built-in producers isolate shape changes
    in fresh matrices, while local alias-returning producers retain shared-
    shape behavior. Upstream-`na` dimension evaluation, dimension/count errors,
    arity, and UDF side-effect rules remain unchanged. No imported UDT identity
    or public schema is widened. Done.
115. The same concrete matrix-result producer set now exposes terminal
    `.swap_rows(row1, row2)`. It validates two simple-int row indexes, swaps
    complete rows while preserving shape and element kind, returns `void`, and
    cannot continue. Imported and built-in producers isolate writes in fresh
    matrices, while local alias-returning producers retain shared-storage
    behavior. Same-index no-op, bounds/`na` indexes, upstream-`na` argument
    evaluation, arity/type, and UDF side-effect rules remain unchanged. No
    imported UDT identity or public schema is widened. Done.
116. The same concrete matrix-result producer set now exposes terminal
    `.swap_columns(column1, column2)`. It validates two simple-int column
    indexes, swaps complete columns while preserving shape and element kind,
    returns `void`, and cannot continue. Imported and built-in producers
    isolate writes in fresh matrices, while local alias-returning producers
    retain shared-storage behavior. Same-index no-op, bounds/`na` indexes,
    upstream-`na` argument evaluation, arity/type, and UDF side-effect rules
    remain unchanged. No imported UDT identity or public schema is widened.
    Done.
117. The same concrete matrix-result producer set now exposes terminal
    `.remove_row(row)`. It validates one simple-int row index, removes the
    selected complete row, including from a zero-column matrix, while
    preserving column count and element kind, returns `void`, and cannot
    continue. Imported and built-in producers
    isolate shape changes in fresh matrices, while local alias-returning
    producers retain shared-shape behavior. Bounds/`na` indexes, upstream-`na`
    argument evaluation, arity/type, and UDF side-effect rules remain
    unchanged. No imported UDT identity or public schema is widened. Done.
118. The same concrete matrix-result producer set now exposes terminal
    `.remove_col(column)`. It validates one simple-int column index, removes
    the selected complete column, including from a zero-row matrix, while
    preserving row count and element kind, returns `void`, and cannot
    continue. Imported and built-in producers isolate shape changes in fresh
    matrices, while local alias-returning producers retain shared-shape
    behavior. Bounds/`na` indexes, upstream-`na` argument evaluation, arity/
    type, and UDF side-effect rules remain unchanged. No imported UDT identity
    or public schema is widened. Done.
119. The same concrete matrix-result producer set now exposes terminal
    `.add_row(row, array_id)`. It validates one simple-int insertion index and
    an element-kind-matched array, copies the array into a complete new row,
    including for a zero-column matrix, while preserving column count and
    element kind, returns `void`, and cannot continue. Imported and built-in
    producers isolate shape changes in fresh matrices, while local alias-
    returning producers retain shared-shape behavior. `0..=rows` bounds/`na`,
    array-size, cell-budget, upstream-`na`, arity/type, and UDF side-effect
    rules remain unchanged. No imported UDT identity or public schema is
    widened. Done.
120. The same concrete matrix-result producer set now exposes terminal
    `.add_col(column, array_id)`. It validates one simple-int insertion index
    and an element-kind-matched array, copies the array into a complete new
    column, including for a zero-row matrix, while preserving row count and
    element kind, returns `void`, and cannot continue. Imported and built-in
    producers isolate shape changes in fresh matrices, while local alias-
    returning producers retain shared-shape behavior. `0..=columns` bounds/
    `na`, array-size, cell-budget, upstream-`na`, arity/type, and UDF side-
    effect rules remain unchanged. No imported UDT identity or public schema
    is widened. Done.
121. The same concrete numeric matrix-result producer set now exposes terminal
    `.sort(column?, order?)`. It defaults to column 0 and ascending order,
    reorders complete rows with stable equal keys, places `na` last ascending
    and first descending, preserves float/int element kind and shape, returns
    `void`, and cannot continue. Imported and built-in producers isolate the
    change in fresh matrices, while local alias-returning producers retain
    shared-storage behavior. Column bounds/`na`, unsupported-order, upstream-
    `na`, arity/type, non-numeric receiver, and UDF side-effect rules remain
    unchanged. No imported UDT identity or public schema is widened. Done.
122. Every concrete scalar map-result producer now exposes terminal
    `.put(key, value)`. It validates the resolved scalar key/value template,
    preserves insertion order on replacement, appends new keys, returns `void`,
    and cannot continue. Local alias-returning producers retain shared-storage
    behavior, while imported and built-in producers isolate writes in fresh
    maps. Invalid key/value/arity, UDF-side-effect, remaining map-mutation, and
    public-schema rules remain unchanged. No imported UDT identity is widened.
    Done.
123. Every concrete scalar map-result producer now exposes terminal `.clear()`.
    It empties the resolved backing entry list, returns `void`, and cannot
    continue. Local alias-returning producers retain shared-storage behavior,
    while imported and built-in producers isolate clears in fresh maps. Arity,
    UDF-side-effect, remaining map-mutation, template, and public-schema rules
    remain unchanged. No imported UDT identity is widened. Done.
124. Every concrete scalar map-result producer now exposes terminal
    `.remove(key)`. It validates the resolved scalar key kind, removes a
    matching entry without reordering retained keys, no-ops for a missing key,
    returns `void`, and cannot continue. Local aliases retain shared-storage
    behavior, while imported and built-in producers isolate removal in fresh
    maps. Invalid key/arity, UDF-side-effect, remaining map-mutation, template,
    and public-schema rules remain unchanged. No imported UDT identity is
    widened. Done.
125. Every concrete scalar map-result producer now exposes terminal
    `.put_all(source)`, completing the registered scalar map helper set. It
    requires an identical source template, clones source entries for self-
    merge safety, replaces retained-key values in place, appends new keys in
    source order, returns `void`, and cannot continue. Local aliases retain
    shared-storage behavior, while imported and built-in targets isolate the
    merge. Invalid source/template/arity, UDF-side-effect, and public-schema
    rules remain unchanged. No imported UDT identity is widened. Done.
