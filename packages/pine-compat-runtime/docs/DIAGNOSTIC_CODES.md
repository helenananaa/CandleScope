# Diagnostic Codes

Diagnostic codes are part of the public developer experience. Messages can be
improved over time, but codes should remain stable once published.

## Lexing

- `E_LEX_CHAR`: unexpected character.
- `E_LEX_COLOR`: invalid color literal.
- `E_LEX_FLOAT`: invalid float literal.
- `E_LEX_INDENT`: indentation is not a supported multiple of spaces.
- `E_LEX_INT`: invalid integer literal.
- `E_LEX_STRING`: unterminated or invalid string literal.
- `E_LEX_STRING_LIMIT`: decoded string literal exceeds 40,960 characters.
- `E_LEX_VERSION`: invalid version directive.

## Parsing

- `E_PARSE_BLOCK`: invalid or unterminated statement block.
- `E_PARSE_ASSIGN`: invalid reassignment.
- `E_PARSE_DECL`: invalid declaration.
- `E_PARSE_EXPECTED`: expected token was missing.
- `E_PARSE_EXPR`: expected expression.
- `E_PARSE_EXPR_DEPTH`: expression nesting exceeds the parser limit.
- `E_PARSE_EXPORT`: invalid export declaration.
- `E_PARSE_FOR`: invalid for-loop declaration.
- `E_PARSE_FUNCTION`: invalid function declaration.
- `E_PARSE_METHOD`: invalid user-defined method declaration.
- `E_PARSE_IF_EXPR`: invalid if expression.
- `E_PARSE_IMPORT`: invalid import declaration.
- `E_PARSE_LIBRARY`: invalid library declaration.
- `E_PARSE_NAME`: invalid qualified name.
- `E_PARSE_SWITCH`: invalid switch expression.
- `E_PARSE_TYPE`: invalid user-defined type declaration.
- `E_LANGUAGE_VERSION_DUPLICATE`: more than one exact `//@version=N`
  directive was found.
- `E_LANGUAGE_VERSION_PLACEMENT`: an exact version directive appeared after a
  source statement instead of in the leading comment/directive region.

## Semantic Analysis

- `E_HOST_INPUT`: a host binding rejected malformed input before semantic
  analysis, such as invalid WASM library-source JSON.
- `E_LANGUAGE_VERSION_`: internal diagnostic-family prefix used to stop before
  ordinary semantic analysis; this prefix is not emitted as a complete code.
- `E_LANGUAGE_VERSION_CONFLICT`: root and host-provided library sources select
  different Pine language versions.
- `E_LANGUAGE_VERSION_UNSUPPORTED`: the selected Pine language version is
  outside the supported closed range v1 through v6.
- `E_LEGACY_INDICATOR_DECLARATION`: a legacy source has a missing, mixed, modern,
  or otherwise inadmissible indicator declaration; the verified v1-v4
  `study()` subsets are executable.
- `E_LEGACY_INPUT_OVERLOAD`: a Pine v1-v4 `input()` call has an ambiguous,
  uninferable, forged, or unsupported historical type selection; the call is
  rejected before canonical lowering or runtime.
- `E_LEGACY_INPUT_CONSTANT_CONTEXT`: a legacy input type constant such as
  `input.integer` is used outside the `type` selector of a versioned `input()`
  annotation; internal selector markers cannot be consumed as ordinary
  strings or propagated through aliases and expressions.
- `E_LEGACY_OUTPUT_ARGUMENT`: a Pine v1-v4 output call uses an invalid historical
  transparency/style value or mixes incompatible fill endpoints; the call is
  rejected before canonical lowering or runtime.
- `E_LEGACY_REFERENCE_GRAPH`: a Pine v1/v2 declaration graph has a duplicate or
  otherwise structurally invalid global declaration.
- `E_LEGACY_REFERENCE_GRAPH_LIMIT`: an active Pine v1/v2 declaration graph
  exceeds 256 nodes or 4096 dependency edges.
- `E_LEGACY_REFERENCE_GRAPH_UNSAFE`: an active Pine v1/v2 graph declaration
  initializer contains a call, mutation, output, request, tuple, or complex
  control flow outside the side-effect-free scalar subset.
- `E_LEGACY_FORWARD_REFERENCE_UNSAFE`: a Pine v1/v2 current-bar forward
  dependency crosses a non-declaration statement barrier and cannot be safely
  reordered.
- `E_LEGACY_REFERENCE_CYCLE`: Pine v1/v2 current-bar declaration dependencies
  contain a cycle with no deterministic source-compatible evaluation order.
- `E_LEGACY_REFERENCE_TYPE`: the bounded Pine v1/v2 declaration graph cannot
  infer one stable scalar type for a participating declaration.
- `E_LEGACY_RSI_OVERLOAD`: a v1-v4 `rsi(x, y)` call cannot select the
  historical length or two-series overload from the analyzed numeric types;
  the call is rejected instead of guessing modern `ta.rsi` behavior.
- `E_LEGACY_SECURITY_MERGE`: a v1-v4 `security` gaps/lookahead argument is not
  a compile-time bool or the corresponding `barmerge` constant; runtime
  alignment is not guessed from series metadata.
- `E_LEGACY_STRATEGY_OUT_OF_SCOPE`: a v1-v4 source declares `strategy()` or
  references `strategy.*`; legacy strategy execution is outside this project.
- `E_LEGACY_V3_NA_INFERENCE`: a Pine v3 untyped `na` declaration cannot infer
  exactly one stable scalar type from a later assignment because it is
  unresolved, collection/object-valued, or conflicts with another assignment;
  the declaration is rejected without relaxing v4-v6 typing.
- `E_LEGACY_VERSION_FEATURE`: a legacy source directly uses a qualified
  built-in spelling that was introduced by a later Pine dialect; canonical
  names produced internally by verified legacy translations remain allowed.

The legacy release audit compares every `E_LEGACY_*` and `W_LEGACY_*` token
emitted by semantic/runtime source with this document. All 16 current legacy
codes are listed here; Phase 11 adds no public diagnostic family and does not
change the current analysis `schemaVersion: 5` or runtime `schemaVersion: 8`.
- `E_ASSIGN_TYPE`: reassignment type mismatch.
- `E_BRANCH_RETURN`: branch expression body does not end with an expression.
- `E_BRANCH_TYPE`: ternary branch type mismatch.
- `E_CALL_ARG_DUPLICATE`: a built-in call argument was provided more than once.
- `E_CALL_ARG_NAME`: unknown named argument.
- `E_CALL_ARG_ORDER`: positional argument followed a named argument in a
  built-in call.
- `E_CALL_ARG_TYPE`: argument type does not satisfy the built-in signature.
- `E_CALL_ARG_VALUE`: argument type is valid, but the value is outside the
  supported range.
- `E_CALL_ARITY`: wrong number of call arguments.
- `E_CALL_TARGET`: invalid function call target.
- `E_CONDITION_TYPE`: condition expression is not bool.
- `E_DECL_TYPE`: typed declaration uses a type name outside the supported
  subset.
- `E_DECL_VALUE`: declaration initializer is not a value-producing expression.
- `E_FUNCTION_ARG_DUPLICATE`: user-defined function argument was provided more
  than once.
- `E_FUNCTION_ARG_NAME`: unknown user-defined function named argument.
- `E_FUNCTION_ARG_ORDER`: positional argument followed a named argument in a
  user-defined function call.
- `E_FUNCTION_ARG_TYPE`: user-defined function argument type does not match the
  declared parameter.
- `E_FUNCTION_ARITY`: wrong number of user-defined function arguments.
- `E_FUNCTION_DUPLICATE`: user-defined function name was declared more than
  once.
- `E_FUNCTION_CALL_DEPTH`: user-defined function or method call nesting exceeds
  the semantic analysis limit.
- `E_FUNCTION_NAME`: user-defined function name conflicts with an existing
  symbol or built-in.
- `E_FUNCTION_PARAM`: user-defined function parameter list is invalid.
- `E_FUNCTION_PARAM_TYPE`: user-defined function parameter declares a type
  outside the supported subset.
- `E_FUNCTION_RETURN`: user-defined function block does not end with an
  expression.
- `E_UDT_ASSIGN_TYPE`: reassignment changed a local user-defined type identity.
- `E_UDT_CONSTRUCTOR_ARG`: user-defined type constructor arguments do not match
  declared fields.
- `E_UDT_DECL_LOCATION`: user-defined type declaration is not top-level.
- `E_UDT_DUPLICATE`: duplicate user-defined type declaration.
- `E_UDT_FIELD_DUPLICATE`: duplicate field in a user-defined type declaration.
- `E_UDT_FIELD_TYPE`: unsupported or unknown user-defined type field type.
- `E_UDT_FIELD_MUTATION`: field reassignment targets a value that is not a
  supported local user-defined type.
- `E_UDT_UNKNOWN_FIELD`: field read references a field not declared on the
  receiver's user-defined type.
- `E_CHART_POINT_UNKNOWN_FIELD`: field read or mutation references a field not
  declared on `chart.point`.
- `E_METHOD_ARG_TYPE`: user-defined method argument type does not match the
  declared parameter.
- `E_METHOD_DECL_LOCATION`: user-defined method declaration is not top-level.
- `E_METHOD_DUPLICATE`: duplicate method declaration for the same receiver
  type and method name.
- `E_METHOD_PARAM`: user-defined method parameter list is invalid.
- `E_METHOD_RECEIVER_TYPE`: user-defined method receiver type is missing,
  malformed, or does not match the call receiver.
- `E_RECURSIVE_METHOD`: recursive user-defined method call is not supported.
- `E_LOWERING_BUDGET`: lowering exceeded the supported inline depth, HIR node,
  or generated temporary-symbol budget.
- `E_MAP_ASSIGN_TYPE`: reassignment changed a map key/value template identity.
- `E_IMPORT_CYCLE`: import dependency graph contains a cycle.
- `E_IMPORT_ALIAS_REQUIRED`: an import used by the executable subset omitted
  the required alias.
- `E_IMPORT_CONST_VALUE`: an exported library constant is not a const
  expression in the supported import subset.
- `E_IMPORT_DUPLICATE_ALIAS`: root imports reuse the same alias.
- `E_IMPORT_DUPLICATE_EXPORT`: a library exports the same name more than once.
- `E_IMPORT_FUNCTION_SIDE_EFFECT`: an exported library function uses side
  effects that are not supported in imported functions.
- `E_IMPORT_INVALID_LIBRARY`: host-provided library source does not contain
  exactly one library declaration.
- `E_IMPORT_MISSING_LIBRARY`: an import key has no host-provided source.
- `E_IMPORT_PRIVATE_SYMBOL`: root code accessed a non-exported library symbol,
  including a private library user-defined type.
- `E_IMPORT_UNSUPPORTED_METHOD`: root code accessed a library method through an
  import alias or an imported UDT receiver, but imported method dispatch is
  outside the current supported subset.
- `E_IMPORT_UNSUPPORTED_UDT`: root code accessed an exported library
  user-defined type, but imported UDT identity is outside the current supported
  subset.
- `E_IMPORT_UNKNOWN_EXPORT`: root code accessed an export that the library does
  not declare.
- `E_RECURSIVE_FUNCTION`: recursive user-defined function call is not supported.
- `E_LOOP_CONTROL`: loop control statement is used outside a supported loop
  context.
- `E_LOOP_RANGE_TYPE`: for-loop range bounds are not integer-compatible.
- `E_LOOP_RETURN`: loop expression result type is not compatible with the
  surrounding expression.
- `E_LOOP_STEP`: for-loop step is invalid.
- `E_OPERATOR_TYPE`: operator does not accept the operand types.
- `E_SCRIPT_DECL_DUPLICATE`: more than one top-level script declaration was
  found.
- `E_SCRIPT_DECL_LOCATION`: `indicator`, `strategy`, or `library` declaration is
  not in a supported top-level location.
- `E_SEMA_EXPR_DEPTH`: expression nesting exceeds the semantic analysis limit.
- `E_TUPLE_ARITY`: tuple assignment target count does not match value count.
- `E_TUPLE_UDT_ARRAY_IDENTITY`: a tuple expression, ordinary declaration,
  reassignment, or call-return slot containing a user-defined-type array does
  not resolve to one stable concrete element identity.
- `E_TUPLE_TYPE`: tuple assignment value is not a tuple.
- `E_UNKNOWN_COLOR`: color literal or color constant cannot be resolved.
- `E_UNKNOWN_FUNCTION`: function call target cannot be resolved.
- `E_UNKNOWN_METHOD`: method call target cannot be resolved for the receiver.
- `E_UNKNOWN_SYMBOL`: symbol cannot be resolved.
- `E_UNSUPPORTED_FEATURE`: recognized feature is outside the current supported
  subset.

## Runtime

- `E_RUNTIME`: runtime execution emitted a host-visible diagnostic.
- `W_LEGACY_SECURITY_LOOKAHEAD`: a reached legacy `security` callsite uses
  historical lookahead-on alignment, whether by v1/v2 default or explicit
  selection, and can repaint. The warning
  is emitted once per distinct callsite in stable order and does not fail
  execution.
- `E_STRATEGY_MODE`: strategy-only feature is used outside `strategy()` mode or
  an unsupported strategy mode was requested.
- `E_STRATEGY_MARGIN`: supported strategy entry fill requires more margin than
  available simulated equity.
- `E_STRATEGY_PRICE`: strategy order fill price is not finite.
- `E_STRATEGY_QTY`: strategy order quantity is not finite and positive.
- `E_STRATEGY_CLOSE_QTY`: `strategy.close` quantity is not finite and positive.
- `E_STRATEGY_CLOSE_QTY_PERCENT`: `strategy.close` percent quantity is not
  finite and positive.
- `E_STRATEGY_EXIT_ENTRY`: `strategy.exit` could not use an active pending entry
  attachment shape. Plain unmatched explicit `from_entry` calls in supported
  exit shapes are no-ops instead.
- `E_STRATEGY_EXIT_MINTICK`: `strategy.exit` tick conversion requires a finite
  positive minimum tick.
- `E_STRATEGY_EXIT_PRICE`: `strategy.exit` price argument is not finite.
- `E_STRATEGY_EXIT_QTY`: `strategy.exit` quantity is not finite and positive.
- `E_STRATEGY_EXIT_QTY_PERCENT`: `strategy.exit` percent quantity is not finite
  and positive.
- `E_STRATEGY_EXIT_TICKS`: `strategy.exit` tick distance is not finite and
  positive.
