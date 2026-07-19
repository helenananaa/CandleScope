# Pure Internal UDT Varip Design

Status: closed design gate; typed/direct-alias and direct-constructor scalar-tree subset
implemented for same-local UDTs and scalar-tree imported UDTs, plus explicit
typed-`na` non-scalar local/imported UDT declarations that can only remain `na`.

This gate defines how user-defined type values may enter the `varip` subset.
The current positive subset is limited to explicitly typed same-local or
same-imported scalar-tree UDT values initialized from `na`, same-UDT
constructors, same-identity aliases, and fixture-backed same-UDT ternary,
switch, if, for, for...in, and while expressions. Direct-constructor-inferred
or direct-alias-inferred same-local or same-imported scalar-tree UDT values are
also supported. Explicit typed-`na` local or imported non-scalar UDT `varip`
declarations are supported only while the value remains `na`; assigning an
object-backed non-scalar UDT value, including through field reassignment, remains
rejected to preserve drawing-id rollback safety. Committed history
reads from those scalar-tree UDT `varip` values are fixture-backed for constant
and dynamic offsets, and realtime forming runs keep those history reads pinned
to confirmed bars while the current `varip` value is carried intrabar.

## Current Boundary

The executable `varip` subset supports scalar `int`, `float`, `bool`,
`string`, `color`, and `na` values, plus scalar typed-array ids and their
backing stores. Realtime forming updates clone the confirmed runtime, seed only
`varip` slots from the previous forming runtime, and then execute the current
update. Scalar typed-array `varip` slots also seed the referenced array backing
store.

Broader untyped non-constructor-inferred UDT `varip` expressions remain outside
that subset. The current negative boundary is covered by
`tests/fixtures/sema/unsupported_user_type_varip.pine`, which rejects:

```pine
type Point
    float x

varip p = bar_index == 0 ? Point.new(close) : Point.new(open)
```

Same-local scalar-tree UDT array `varip` declarations are fixture-backed by
`tests/fixtures/runtime/user_type_array_varip.pine`,
`tests/fixtures/realtime/user_type_array_varip.pine`, and
`tests/fixtures/sema/supported_user_type_array_varip_decl.pine`, including
nested local scalar-tree elements initialized through `array.from(...)` and
`array.new<T>()` for backing-store handoff. The declaration boundary stays
fixture-backed by `tests/fixtures/sema/supported_user_type_array_varip_nested_decl.pine`.
Same-imported scalar-tree UDT array `varip` declarations are fixture-backed by
`tests/fixtures/runtime/import_udt_array_varip.pine`,
`tests/fixtures/realtime/import_udt_array_varip.pine`, and
`tests/fixtures/sema/supported_imported_udt_array_varip_nested_decl.pine`, while
scalar-tree local UDT `varip` values are covered by
`tests/fixtures/runtime/user_type_varip.pine` and
`tests/fixtures/realtime/user_type_varip.pine`; the runtime fixtures also cover
constant and dynamic committed history reads from local and imported scalar-tree
UDT `varip` values, including nested scalar-tree field reads, while the
realtime fixtures keep those history reads on confirmed bars across repeated
forming updates; this includes representative same-local and same-imported
nested scalar-tree Wrapper values initialized from ternary expressions.
`tests/fixtures/runtime/user_type_varip.pine` and
`tests/fixtures/realtime/user_type_varip.pine` also cover same-local Point and
nested scalar-tree Wrapper ternary, switch, if, for, for...in, and while
expression initializers under the intrabar value-clone handoff, and
`tests/fixtures/runtime/import_udt_varip.pine` plus
`tests/fixtures/realtime/import_udt_varip.pine` cover same-imported Point and
nested scalar-tree Wrapper ternary, switch, if, for, for...in, and while
expression initializers.
Mismatched UDT assignment into an already typed UDT `varip` slot is rejected by
`tests/fixtures/sema/unsupported_user_type_varip_assign_identity.pine`, with the
fixture locking the user-facing different-UDT assignment diagnostic.
Private-dependency imported UDT `varip` construction remains rejected by
`tests/fixtures/sema/unsupported_imported_udt_varip.pine`, while
local/imported lookalike assignment into an imported `varip` slot is rejected by
`tests/fixtures/sema/unsupported_imported_udt_varip_identity.pine`, with a
message-level different-UDT assignment diagnostic.
Explicit typed-`na` non-scalar local and imported UDT `varip` declarations are
covered by `tests/fixtures/sema/supported_user_type_history_non_scalar_typed_na.pine`,
`tests/fixtures/sema/supported_imported_udt_varip_non_scalar_typed_na.pine`,
`tests/fixtures/runtime/user_type_non_scalar_typed_na_history.pine`, and
`tests/fixtures/runtime/import_non_scalar_udt_typed_na_history.pine`.
Object-backed non-scalar UDT reassignments remain rejected by
`tests/fixtures/sema/unsupported_user_type_varip_non_scalar_reassign.pine`,
`tests/fixtures/sema/unsupported_user_type_varip_non_scalar_field_reassign.pine`,
and `tests/fixtures/sema/unsupported_imported_udt_varip_non_scalar_reassign.pine`.

Ordinary `var` UDT values already have realtime rollback coverage:

- `tests/fixtures/realtime/user_type_var_rollback.pine` covers inferred UDT
  `var` values;
- `tests/fixtures/realtime/user_type_typed_var_rollback.pine` covers typed
  local UDT `var` declarations initialized from `na`, constructors, and
  same-UDT expressions.

Those fixtures are the rollback baseline that a positive UDT `varip` slice must
contrast against.

## Target Shape

The first positive UDT `varip` subset should be smaller than general UDT value
support:

- same-source scalar-tree UDT values only, local or imported;
- local/global declaration sites that already pass ordinary typed UDT
  declaration rules;
- typed declarations initialized from `na`, a same-UDT constructor, or a
  same-identity alias; same-local typed declarations also accept
  fixture-backed same-UDT ternary, switch, if, `for`, `for...in`, or `while`
  expressions;
- later assignment from the same UDT identity;
- scalar field reads and, for local UDTs only, field mutations on the root local
  symbol; imported UDTs use same-identity reassignment because imported field
  mutation remains unsupported;
- imported identities are limited to scalar-tree UDT values with source-scoped
  identity metadata;
- no unresolved or recursive UDT arrays;
- committed history references are limited to the fixture-backed scalar-tree
  local/imported UDT `varip` values;
- no drawing ids, chart points, tuples, maps, matrices, or arrays as UDT fields;
- no field mutation inside UDF or method bodies beyond the subset already
  accepted for ordinary local UDT mutation.

Historical bars should execute UDT `varip` like `var`: initialize the slot once
and reuse it on later historical bars. Realtime forming updates should carry the
current intrabar UDT value forward from the previous forming update after the
declaration has run at least once. The confirmed update for that bar should
seed from the last forming value, execute once, and commit the resulting UDT
value into the confirmed runtime.

## Semantic Policy

Allow only declarations where both identity and runtime storage are explicit:

```pine
type Point
    float x

varip Point p = na
if na(p)
    p := Point.new(close)
else
    p.x := p.x + 1
plot(p.x)
```

An untyped constructor initializer such as `varip p = Point.new(close)` or
`varip p = lib.Point.new(close)` and an untyped direct alias initializer such as
`varip p = existingPoint` or `varip w = importedWrapper` are accepted when the
semantic analyzer binds the initializer to a concrete local or imported
scalar-tree UDT identity.

Explicitly typed same-UDT alias, ternary, switch, if, for, for...in, and while
initializers, such as
`varip Point p = condition ? Point.new(close) : Point.new(open)` or a
same-identity variable initializer, a selector-form `switch`, an `if`
expression whose branches return the same local UDT, or a `for`/`for...in`/
`while` expression whose body returns the same local UDT, use the same identity
and value-clone handoff as other typed UDT `varip` declarations. Broader
untyped non-constructor inference, including untyped ternary initializers,
remains rejected.

Reject:

- unresolved imported UDT fields;
- non-scalar fields except for explicit typed-`na` local/imported UDT `varip`
  declarations that remain `na`;
- direct UDT arrays or UDT arrays wrapped by another value;
- UDT history references outside the supported scalar-tree local/imported
  `varip` value subset and explicit typed-`na` non-scalar local/imported `varip`
  subset;
- mismatched constructor or assignment identities;
- method or UDF side effects that are still rejected for ordinary UDT values.

Diagnostic wording should continue to report feature `varip` while naming the
unsupported value family precisely enough to distinguish UDT values from UDT
arrays. The UDT value diagnostic should name the supported explicit or
direct-constructor same-local or same-imported scalar-tree subset, and keep
untyped non-constructor inference, nested or object-backed non-scalar UDT values,
and UDT arrays outside that subset.

## Runtime Policy

The existing realtime handoff already clones `PineValue` slots when seeding
`PersistenceKind::Varip` from the previous forming runtime. A UDT value is a
plain runtime value, so the first positive scalar-tree subset should use
value-clone semantics:

- seed the whole UDT field vector by value;
- treat field mutation as mutation of the carried slot value;
- avoid introducing object identity for scalar-tree UDT values;
- keep array backing-store seeding separate from UDT value seeding;
- preserve existing ordinary `var` rollback by not widening non-`varip`
  persistence behavior.

If later UDT value support grows references, imported identity side tables, or
nested field stores, this gate should be reopened before enabling UDT `varip`
for those shapes.

## Required Fixtures

A positive implementation slice should add at least:

- runtime historical fixture for typed scalar-tree UDT `varip` initialized from
  `na` and later same-UDT assignment;
- realtime fixture showing local UDT `varip` field mutation or imported UDT
  same-identity reassignment persists across repeated forming updates;
- paired realtime fixture showing ordinary UDT `var` still rolls back on
  repeated forming updates;
- semantic fixture rejecting mismatched UDT assignment into a `varip` UDT slot;
- semantic fixture keeping non-scalar UDT array `varip` rejected;
- semantic fixture keeping imported UDT `varip` constructor arguments rejected
  when the exported type depends on a private nested UDT value that callers
  cannot construct.

Snapshot expectations must show the intrabar difference directly: ordinary UDT
`var` output resets from confirmed state on each forming update, while UDT
`varip` output continues from the previous forming update.

## Suggested Slice Order

1. Tighten negative diagnostics for UDT value versus UDT array `varip` if the
   current message is too broad. Done.
2. Add typed scalar-tree UDT `varip` semantic acceptance for local same-source
   UDT identities only. Done.
3. Add runtime and realtime fixtures proving field-vector clone handoff and
   confirmed-bar commit. Done for the typed scalar-tree subset.
4. Add same-local scalar-tree UDT array `varip` handoff by reusing the
   runtime-owned array backing-store seeding path and preserving UDT element
   identity metadata. Done.
4. Add untyped constructor inference only after typed declarations are stable.
   Done for direct same-local scalar-tree constructors only.
5. Add explicitly typed same-UDT ternary initializer fixtures under the existing
   scalar-tree value-clone handoff. Done.
6. Add explicitly typed same-UDT switch initializer fixtures under the same
   scalar-tree value-clone handoff. Done.
7. Add explicitly typed same-UDT if-expression initializer fixtures under the
   same scalar-tree value-clone handoff. Done.
8. Add explicitly typed same-UDT for-expression initializer fixtures under the
   same scalar-tree value-clone handoff. Done.
9. Add explicitly typed same-UDT for...in and while-expression initializer
   fixtures under the same scalar-tree value-clone handoff. Done.
9. Add same-local nested scalar-tree UDT value fixtures for typed
   ternary/switch/if/for/for...in/while initializer handoff. Done.
9. Add representative same-local and same-imported nested scalar-tree UDT
   `varip` committed and realtime confirmed-bar history reads for ternary
   initializer handoff. Done.
10. Add scalar-tree imported UDT `varip` declarations under the same value-clone
   handoff. Done for `na`, same-imported constructors, typed and direct
   same-identity aliases, direct constructor inference, and same-imported
   Point and nested scalar-tree Wrapper ternary, switch, if, for, for...in, and
   while expression initializers.
10. Add scalar-tree same-local and same-imported UDT array `varip` handoff after
    UDT array identity and imported UDT identity metadata are stable. Done.
11. Consider recursive UDT arrays only after recursive UDT identity and history
    interactions are independently designed.

Completion for the first positive subset requires focused semantic/runtime
tests, CLI fixture snapshots, `git diff --check`, and `scripts/verify.sh`.
