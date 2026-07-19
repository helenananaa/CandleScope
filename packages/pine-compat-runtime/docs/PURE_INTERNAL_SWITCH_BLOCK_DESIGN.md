# Pure Internal Switch Statement-Block Design Gate

Status: design gate closed; condition-form, selector-form, and default positive
scalar subsets are implemented for expression statement-block arms. Statement
context `switch` block arms can execute for side effects and outer assignment
without a final result expression.

This document defines the internal path for future statement-block arms in
`switch` expressions. It is scoped to parser shape, semantic analysis, HIR
lowering, runtime expression evaluation, block scoping, stateful callsites, loop
control, and conformance. It does not cover host UI, rendering, external data,
or public serialization.

## Current Boundary

`switch` supports expression arms in condition and selector forms, plus
statement-block arms whose block ends in a result expression:

```pine
value = switch
    close > open => high
    => close

value = switch direction
    1 => high
    => close

value = switch
    close > open =>
        local = high
        local
    => close

value = switch direction
    1 =>
        local = high
        local
    => close

value = switch
    close > open => high
    =>
        local = close
        local
```

Expression-context statement-block arms that do not end in a result expression
are semantic errors.
Statement-context `switch` arms can be used as standalone statements and do not
require a result expression:

```pine
switch direction
    1 =>
        total := total + high
    =>
        total := total + low
```

Current evidence:

- `docs/PURE_INTERNAL_ROADMAP.md` lists broader block result variants as
  remaining language/control-flow work.
- `tests/fixtures/conformance.tsv` marks `switch` partial and records the
  supported condition-form, selector-form, and default block subsets plus the
  remaining no-final-result semantic boundary.
- `tests/fixtures/runtime/switch_statement_block.pine`,
  `tests/fixtures/runtime/switch_statement_block_selector.pine`,
  `tests/fixtures/runtime/switch_statement_block_default.pine`, and
  `crates/pine-runtime/src/tests/runtime_control_flow.rs` cover selected-arm
  execution and block-local final-result behavior.
- `tests/fixtures/runtime/switch_statement_block_scope.pine` covers selected-arm
  outer reassignment from block arms.
- `tests/fixtures/runtime/switch_statement_block_loop_control.pine` covers
  selected-arm `break`/`continue` propagation to the nearest enclosing loop.
- `tests/fixtures/runtime/switch_statement_form.pine` covers standalone
  statement-context switch arms in condition-form, selector-form, default-arm,
  outer-reassignment, and loop-control paths without dummy result expressions.
- `tests/fixtures/runtime/switch_statement_block_tuple.pine` covers tuple
  declaration/destructuring results from selected block arms.
- `tests/fixtures/runtime/switch_statement_block_udt.pine` covers same-local
  UDT constructor and block-local alias results from selected block arms.
- `tests/fixtures/sema/unsupported_switch_statement_block.pine` keeps the
  no-final-result block diagnostic and message in place.
- `tests/fixtures/sema/unsupported_switch_statement_block_selector.pine` keeps
  selector-form no-final-result diagnostics and message in place.
- `tests/fixtures/sema/unsupported_switch_statement_block_default.pine` keeps
  default-arm no-final-result diagnostics and message in place.
- `tests/fixtures/sema/unsupported_switch_statement_block_alert_result.pine`
  and
  `crates/pine-sema/tests/fixtures.rs::reports_unsupported_switch_statement_block_alert_result_fixture`
  keep void side-effect calls rejected as switch statement-block arm results
  with `E_BRANCH_RETURN`.
- `tests/fixtures/sema/unsupported_switch_statement_block_reassignment_result.pine`
  and
  `crates/pine-sema/tests/fixtures.rs::reports_unsupported_switch_statement_block_reassignment_result_fixture`
  keep reassignment statements rejected as switch statement-block arm results
  with `E_BRANCH_RETURN`.
- `tests/fixtures/sema/unsupported_switch_statement_block_scope_leak.pine`
  keeps branch-local block declarations from leaking after the switch
  expression.
- `tests/fixtures/sema/unsupported_switch_statement_block_udt_identity.pine`
  keeps mismatched UDT identities across block arms rejected with a message-level
  switch UDT identity diagnostic.
- `tests/fixtures/runtime/import_udt_switch_statement_block.pine` and
  `crates/pine-sema/src/tests/compatibility.rs::import_accepts_switch_block_imported_user_type_result`
  cover same-imported-identity UDT constructor and block-local alias results
  from selected block arms.
- `tests/fixtures/sema/unsupported_imported_udt_switch_identity.pine` keeps
  local/imported UDT identity mismatches rejected across switch arms with the
  same message-level switch UDT identity diagnostic.
- `crates/pine-syntax/src/ast.rs` represents switch arm results as either an
  expression or statement block, and lowering reuses `HirExprKind::Block` for
  supported block arms.

Do not widen broader result forms until the runtime behavior and fixtures are
updated together.

## Target Shape

Implemented first positive subset:

```pine
value = switch
    close > open =>
        local = high
        local
    =>
        close
```

Target properties:

- condition-form and selector-form switches keep the same arm-selection rules
  as expression arms;
- only the selected arm's block executes;
- the selected block's result is the final expression statement in that block;
- if the selected block has no result-producing final expression, semantic
  analysis rejects the switch expression;
- if no arm matches and no default arm exists, the switch expression returns
  `na`, matching current expression-arm behavior;
- existing expression arms continue to parse and lower through the current path.

## Parser Policy

Parser policy:

- after `=>`, accept either the current same-line expression or a newline plus
  an indented block;
- preserve a distinct AST shape for block arms instead of encoding them as a
  synthetic expression;
- keep arm condition spans and result/body spans precise for diagnostics;
- require at least one statement in a block arm;
- keep nested `switch`, `if`, `for`, and `while` bodies parsed by existing block
  machinery;
- keep statement-context `switch` lowering separate from expression `switch`
  so expression arms continue to require a value-producing result.

## Scoping And Result Policy

Semantic policy:

- each block arm creates a branch-local scope equivalent to `if` expression
  branches and `for` expression bodies;
- variables declared inside one arm are not visible in sibling arms or after the
  switch expression;
- assignment to already-visible outer variables follows existing branch
  assignment rules;
- `var` declarations inside an arm follow declaration-site persistence rules and
  are initialized only when that declaration executes;
- the block result is the last expression statement reached in the selected arm;
- `break` and `continue` remain legal only when the selected arm executes inside
  an enclosing loop, and they target that nearest loop, not the switch itself;
- a selected arm that exits by `break`/`continue` should propagate the existing
  loop-control signal instead of producing a value.

Type unification should use the existing switch expression common-type rules
after each arm has a known result type. Branches that produce incompatible UDT
identities remain rejected.

## Runtime Policy

Runtime policy:

- evaluate the optional selector once before arm matching;
- evaluate condition-form arm conditions in source order until the first `true`;
- treat `false` and `na` condition-form arm conditions as non-matches;
- evaluate only the selected arm body;
- execute statements in the selected arm using the same branch-local runtime
  scope discipline as existing expression blocks;
- return the selected arm's final expression value;
- preserve stateful built-in callsite semantics by advancing only callsites in
  the selected arm;
- no public output schema changes are required.

Realtime rollback follows existing state rollback rules because switch block
arms introduce no new storage family by themselves.

## Deferred Variants

Keep these out of the first positive subset:

- expression-context arm blocks without a final result expression beyond the
  current diagnostic;
- result-producing blocks that end in declarations, reassignment, drawing,
  strategy, or alert statements;
- imported UDT identity interactions beyond the same-imported-identity switch
  expression subset;
- any host-visible output change.

## Slice Order

Recommended future slices:

1. Done: AST shape represents expression arms and statement-block arms
   distinctly.
2. Done: supported block arms lower through existing `HirExprKind::Block`.
3. Done: first positive scalar subset covers condition-form block arms returning
   scalar values, with selected-arm-only execution fixtures.
4. Done: selector-form parity for block arms.
5. Done: default-arm block parity.
6. Done: broader scope fixture for selected-arm outer assignment and
   branch-local declaration no-leak behavior.
7. Done: loop-control propagation fixtures for selected block arms inside loop
   bodies.
8. Done: tuple declaration/destructuring result fixture for selected block arms.
9. Done: same-local UDT constructor and block-local alias result fixtures for
   selected block arms.
10. Done: same-imported-identity imported UDT constructor and block-local alias
    result fixtures for selected block arms, with local/imported identity
    mismatches still rejected.
