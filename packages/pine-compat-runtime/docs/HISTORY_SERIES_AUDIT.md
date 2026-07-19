# History and Series Audit

This document records the Phase C boundary from
`docs/LONG_TERM_EXECUTION_PLAN.md`. Phase C now has a guarded dynamic integer
history subset, static retention inference, runtime retention profiles, and
indicator-level `max_bars_back` support.

## Current Supported Subset

- History references use `expr[offset]` syntax.
- The offset must be an integer literal greater than or equal to zero, or an
  integer expression at any implemented qualifier, including `series int`.
- `expr[0]` evaluates `expr` on the current bar.
- `expr[n]` for `n > 0` reads the committed value from `n` bars ago.
- dynamic offsets are accepted when the offset expression is an integer.
- Out-of-range history reads return `na`.
- Dynamic offsets that evaluate to `na` return `na` after evaluating the source
  expression for the current bar, so expression/UDF result series histories stay
  aligned for later reads.
- Dynamic offsets that evaluate to a negative integer fail at runtime, including
  offsets produced by built-ins, UDF returns, or
  ternary/if/switch/for/for...in/while-expression results.
- Series-qualified identifiers keep stable series ids.
- Series-qualified non-identifier expressions that are lowered with history
  receive compiler-generated series ids.
- Lowering records HIR history metadata: program-wide `max_constant_offset`,
  whether dynamic offsets exist, and per-series history requirements.
- Runtime retention uses that metadata for scripts without dynamic offsets:
  each series keeps only the maximum constant offset it needs, and unindexed
  series keep no committed history.
- The metadata includes implicit history reads used by current runtime
  implementations of `ta.tr`, `ta.atr`, `ta.change`, `ta.highest`/`ta.lowest`,
  `ta.highestbars`/`ta.lowestbars`, `ta.rising`/`ta.falling`, and `ta.cross*`,
  including high/low default sources for length-only extrema overloads.
- Constant history is fixture-covered for built-in series, constant integer
  expression offsets, expression history, branch bodies, loop bodies, and
  user-defined function parameters. Shared scalar call evaluation additionally
  lowers nested or cast-wrapped `int`, `float`, `math.min`, `math.max`,
  `math.abs`, `math.floor`, `math.ceil`, and `math.trunc` results as constant
  offsets when every argument and result are known. Finite `int(float)` follows
  runtime truncation/saturation before the non-negative history-range check;
  out-of-`i64` float results from `math.floor`/`math.ceil`/`math.trunc` stay
  conservatively unknown.
- Dynamic integer history is fixture-covered for built-in series, expression
  history, series-qualified offsets, direct ternary-produced offsets including
  returned `na` offsets and result first-bar history predicates,
  branch-produced offsets including result first-bar history predicates,
  switch-produced offsets including expression block-arm, statement-context
  switch-assigned, and returned `na` offsets,
  for-loop-produced offsets including result first-bar history predicates,
  while-loop-produced offsets including result first-bar history predicates,
  stateless and direct-history TA built-in result history reads including
  direct-offset result first-bar predicates and dynamic `na` offsets, stateful
  built-in result and TA-variable history reads including direct-offset result
  first-bar predicates, dynamic `na` offsets, cumulative-result reads, and
  built-in-returned offsets with result first-bar predicates, built-in
  returned offsets including returned `na` offsets and result first-bar
  history predicates,
  user-defined function parameters including `na` offsets and result first-bar
  history predicates, plus returned offsets,
  UDF-returned `na` offsets, UDF-returned offset result first-bar history
  predicates, local and imported scalar-tree UDT field-produced offsets including
  fields on local/imported UDF passthrough/constructor-returned direct/nested
  values and local/imported method passthrough/constructor-returned direct/nested
  values, including imported receiver-style and alias-qualified method calls,
  and realtime forming rollback.

## Current Rejections

- Negative literal offsets such as `close[-1]` are rejected with
  `negative_history_offset`; literal and named-const negative offsets now have
  fixture-backed diagnostics that state history offsets must be non-negative.
  Negative values produced by the explicit scalar constant-call whitelist are
  also rejected statically, including cast-wrapped forms such as
  `close[int(math.min(-1, 0))]`.
  Runtime negative dynamic offsets are fixture-backed for direct offsets,
  UDF/built-in/control-flow-produced offsets, and UDT field-produced offsets
  including direct/nested imported fields, local/imported UDF direct/nested
  passthrough/constructor-returned fields, and local/imported method
  direct/nested passthrough/constructor-returned fields, with imported method
  coverage including receiver-style and alias-qualified calls.
- Non-integer dynamic offsets such as `close[close]`, `close[close > open]`,
  UDF-returned float offsets, built-in-returned float offsets, or
  ternary/if/switch/for/for...in/while-expression float results are rejected
  with `dynamic_history_offset` diagnostics that include the actual offset
  type. UDT field-produced non-integer offsets are fixture-backed for direct
  fields, local/imported UDF direct/nested passthrough/constructor-returned
  fields, local method direct/nested passthrough/constructor-returned fields
  plus method-returned bool/string fields, and imported receiver-style or
  alias-qualified method direct/nested passthrough/constructor-returned fields.
- `max_bars_back(source, N)` rejects non-series-numeric sources, non-const `num`
  arguments, negative `num` values, overflow beyond the runtime history-bound
  field, and declaration use as a value-producing expression with
  fixture-backed user-facing diagnostics.
- Scalar array, scalar slice, label-array, label-slice, line-array,
  line-slice, box-slice, linefill-array, linefill-slice, polyline-array,
  polyline-slice, box-array, table-array, table-slice, chart.point-array,
  chart.point-slice, and same-local scalar-tree UDT-array variable history
  snapshots are fixture-backed for the official `previous = a[1]` and
  `na(previous) ? na : previous.get(0)` pattern, including ordinary
  scalar-array, scalar-slice, label-array, label-slice, line-array, line-slice,
  box-array, box-slice, linefill-array, linefill-slice, polyline-array,
  polyline-slice, table-array, table-slice, chart.point-array,
  chart.point-slice, and same-local scalar-tree UDT-array first-bar
  `na(previous)` predicate output, plus scalar array/slice, label-array/slice,
  line-array/slice, box-array/slice, linefill-array/slice,
  polyline-array/slice, table-array/slice, chart.point-array/slice, and
  same-local or same-imported scalar-tree UDT-array dynamic `na` offset
  predicates. Scalar array and slice dynamic-history snapshots include
  fixture-backed element reads and repeated same-bar copy independence after
  mutating a sibling historical array or slice. Chart.point array and slice
  dynamic-history snapshots also include fixture-backed field reads from the
  dynamically selected historical point plus repeated same-bar copy independence
  after mutating a sibling historical chart.point array or slice.
  Label, line, box, linefill, polyline, and table array/slice dynamic-history
  snapshots likewise include fixture-backed id content reads through supported
  getters or `.all` membership checks. Label, line, box, linefill, polyline, and table
  array/slice dynamic-history snapshots also cover repeated same-bar copy
  independence after replacing a sibling historical array or slice slot.
  Same-local and same-imported scalar-tree UDT array and slice dynamic-history
  snapshots include fixture-backed field reads from dynamically selected
  historical elements; same-local and same-imported UDT array/slice snapshots
  also cover repeated same-bar copy independence after replacing a sibling
  historical array or slice slot.
- Single chart.point value history is fixture-backed for constant offsets,
  dynamic `na` offsets, field reads from the previous value, and retained
  previous values after mutating the current point, plus repeated dynamic
  same-bar copy independence for direct point values,
  `if`/`switch`/`for`/`for...in`/`while` expression point results, and UDF- or
  method-returned point values, including direct point constructors,
  `if`/`switch`/`for`/`for...in`/`while` expression results, and UDF- or
  method-returned point values with dynamic `na` offsets.
- Scalar-array and matrix while-expression result history snapshots include
  dynamic `na` offset predicates and fixture-backed content reads from
  dynamically selected historical results. Matrix history snapshots are
  fixture-backed for committed matrix values, dynamic matrix offsets including
  `na` offset predicates, shape-history dynamic `na` offset predicates and
  shape reads, repeated dynamic same-bar matrix history reads as independent
  copies after mutating a sibling historical matrix, and while-expression matrix
  results. Scalar map history snapshots are
  fixture-backed with independent historical copies plus dynamic `na` offset
  predicates, key reads, and size reads from dynamically selected historical maps.
  Repeated scalar-map history reads from the same historical bar are fixture-backed
  as independent copies when a sibling historical map copy is mutated.
  Scalar-tree local and imported UDT value history is fixture-backed, including
  repeated same-bar copy independence after replacing a sibling historical
  value's root field, plus same-local and same-imported
  if/switch/for/for-in/while flow-result value copies and same-local or
  same-imported typed-UDF returned Point/Wrapper value copies, same-local and
  same-imported UDF direct/nested passthrough Point/Wrapper value copies,
  same-local and same-imported UDF direct/nested constructor-returned
  Point/Wrapper value copies, plus same-local and same-imported
  method-returned direct/nested passthrough and direct/nested constructor-returned
  Point/Wrapper value copies. Local and imported non-scalar typed-`na` UDT
  values are fixture-backed for direct, `var`, ternary, `if`, `switch`, `for`,
  `for...in`, `while`, local and imported exported UDF passthrough, method
  parameter passthrough, imported method non-receiver parameter passthrough,
  method receiver/nested receiver passthrough, and imported alias-qualified
  method receiver passthrough identity-preserving history reads plus direct
  field reads, field history, and `na()` checks,
  plus local/imported constructed label/line/box/chart.point-field UDT value
  history with direct `chart.point` field chains, while broader non-scalar UDT
  value history remains outside the supported subset. Non-scalar UDT value
  history outside that fixture-backed local/imported
  label/line/box/chart.point-field path,
  drawing-object
  collections beyond fixture-backed id arrays/slices, nested map/collection map
  templates, and richer aliasing cases remain undesigned or rejected.
  `tests/fixtures/runtime/import_udt_private_dependency_history.pine` keeps
  typed-`na` history over an exported imported UDT whose scalar-tree metadata
  depends on a private library UDT executable, including dynamic `na` offset
  predicates, while
  `tests/fixtures/sema/supported_imported_udt_private_dependency_history.pine`
  keeps the same metadata subset accepted during semantic analysis and direct
  private imported UDT access remains rejected by private-symbol diagnostics.
- Broader per-variable `max_bars_back` inference remains deferred. Top-level,
  statement-block, `for`/`for...in`/`while` statement-body, statement-context switch block-arm, switch expression
  block-arm, tuple-destructured switch expression block-arm, if-expression
  block branch, tuple-destructured if-expression block branch,
  value-producing block-expression prefix statement,
  call-argument block expression, collection mutation argument block expression,
  block-result nested expression,
  and `for`/`for...in`/`while` loop-expression result nested expression helper calls such as
  `max_bars_back(close, 20)`,
  `src = close; max_bars_back(src, 20)`, derived or alias-chain series
  variables, and direct series numeric expressions such as
  `max_bars_back(close + open, 20)` are fixture-backed with stable pure
  unary/binary/ternary plus pure `if`/`switch`/`for`/`while` expression identity
  and pure `for...in` over inline `array.from(...)` identity reused for matching history reads,
  including builtin qualified constants/simple metadata, bar/session flags,
  direct-constructor local or imported scalar-tree UDT scalar field expressions
  including nested field paths,
  positional, fixed-arity named, and signature-bound fully named or mixed
  variadic stateless pure math calls, stable nested history expressions,
  fixed-arity pure `nz`/`fixnan`
  value-helper calls including named/reordered `nz` replacement, pure string
  numeric-source calls including `str.tonumber`, `str.length`, and `str.pos`,
  pure color-channel calls `color.r`/`color.g`/`color.b`/`color.t`, pure numeric
  cast calls, and
  unreassigned pure scalar series declaration aliases plus expression-body or pure
  expression-statement-prefixed normal typed or untyped local-alias block-body
  parameterized pure UDF calls, including nested pure UDF calls, and
  direct-constructor local or imported scalar-tree UDT-argument scalar-field
  pure UDF calls, including named/reordered UDF arguments,
  direct-constructor UDT argument expressions, nested scalar field paths, and
  nested pure UDF passthrough over those paths including named/reordered
  arguments and direct-constructor UDT argument expressions, plus
  receiver-unused parameterized pure user method calls plus direct-constructor
  local or imported scalar-tree receiver scalar-field pure user method calls
  through direct reads or block-local receiver aliases or nested field aliases
  including nested scalar field paths, plus alias-qualified imported method
  calls with bound or direct-constructor receiver expressions and scalar-tree
  UDT argument field paths, including named/reordered method arguments and
  nested method passthrough over those paths including named/reordered
  arguments and direct-constructor UDT argument expressions, and direct-constructor local or imported
  scalar-tree UDT-argument scalar-field pure user method calls, including local
  named/reordered method arguments, direct-constructor UDT argument expressions,
  nested scalar field paths, and nested pure user method passthrough over those
  paths including named/reordered arguments and direct-constructor UDT argument
  expressions, with
  non-negative constant integer lengths, including supported constant
  expressions, shared constant-call results from the exact `int`, `float`,
  `math.min`, `math.max`, `math.abs`, `math.floor`, `math.ceil`, and
  `math.trunc` whitelist, pure UDF-returned and imported exported pure
  UDF-returned constant length values, and block/loop-local const length aliases
  visible to the statement or result expression, that fit in the runtime
  history-bound field and apply per-series retention bounds.
  Named/reordered helper arguments are fixture-backed, and repeated helper
  calls for the same series use the largest declared bound. Identity reuse is
  deliberately disabled when an expression depends on a reassigned scalar
  symbol, so a later expression cannot inherit an earlier value's per-series
  retention bound. Constant aliases retain their assignment-time dependency
  environment, so later source-symbol reassignment cannot retroactively widen a
  helper bound, and inlined UDF/method locals preserve distinct
  pre-/post-reassignment history sources. The history-expression,
  color-channel, and string-position slice is
  covered by matching historical, incremental-append, and realtime rollback
  results.
- Implicit TA history metadata for source/length helpers is fixture-backed for
  named/reordered `source` and `length` arguments, including direct-length,
  dynamic-length, rolling-window, and trend-window requirements.

## Series Offset Policy

Series integer offsets are supported as a guarded dynamic subset:

- the offset expression is evaluated on the current bar
- `na` offsets return `na` after evaluating the source expression for the
  current bar
- negative offsets fail at runtime
- out-of-range offsets return `na`
- scripts with any dynamic offset keep full committed series history up to the
  configured runtime cap
- `indicator(..., max_bars_back=N)` and
  `strategy(..., max_bars_back=N)` bound dynamic retention when `N` is a
  non-negative constant integer expression, including pure UDF-returned and
  imported exported pure UDF-returned constant length values and nested known
  results from the exact `int`, `float`, `math.min`, `math.max`,
  `math.abs`, `math.floor`, `math.ceil`, and `math.trunc` static-call whitelist,
  that fits in the runtime history-bound field
- runtime profiles expose the retention mode, HIR history requirement fields,
  and dynamic-retention miss counters when a runtime offset exceeds the retained
  `max_bars_back` window
- runtime diagnostics report the effective retention window that caused a
  dynamic-retention miss, including per-series `max_bars_back(source, N)` bounds
  that are stricter than the script-level bound

Static-only scripts still use HIR metadata to trim retention.

## Phase C Closeout

Completed:

- Hardened constant history coverage.
- Audited qualifier propagation for const, input, simple, and series values.
  Current findings are in `docs/QUALIFIER_AUDIT.md`.
- Audited and tightened built-in signature docs for implemented qualifier
  behavior.
- Implemented guarded dynamic integer history, including `series int` offsets.
- Added HIR history requirement metadata and runtime static retention trimming.
- Added indicator-level `max_bars_back` bounds for dynamic history retention.
- Added one shared, explicit scalar constant-call evaluator for static history
  offsets and declaration/per-series `max_bars_back` values. It recognizes only
  `int`, `float`, `math.min`, `math.max`, `math.abs`, `math.floor`, `math.ceil`,
  and `math.trunc`; other runtime-pure calls are not implicitly folded.
- Added profile fields for retention mode, static depth, dynamic-offset
  presence, `max_bars_back`, and dynamic-retention misses.
- Added runtime diagnostics for dynamic offsets beyond explicit retention
  bounds, including effective-window reporting when per-series bounds are
  stricter than script-level bounds.
- Added fixture coverage for historical, incremental, and realtime rollback
  paths.

Deferred:

- Per-variable `max_bars_back` inference beyond the fixture-backed top-level,
  statement-block, `for`/`for...in`/`while` statement-body, statement-context switch block-arm, switch expression
  block-arm, tuple-destructured switch expression block-arm, if-expression
  block branch, tuple-destructured if-expression block branch, and
  value-producing block-expression prefix
  statement/call-argument/collection-mutation-argument/block-result/loop-result nested expression
  `max_bars_back(source, N)` helper subset.
- Nested map/collection map templates plus richer object-collection aliasing
  cases beyond the fixture-backed array/slice, matrix, and scalar map snapshots.
- Otherwise unsupported local/imported UDT value history remains rejected until
  value identity and copy semantics are deliberately designed. Local/imported
  constructed label/line/box/chart.point-field UDT history, including direct
  chained `chart.point` field reads such as `value.anchor.index`, and
  local/imported non-scalar typed-`na` values are
  accepted for direct, `var`, ternary, `if`, `switch`, `for`, `for...in`, and
  `while` identity-preserving history plus local/imported exported UDF, method
  parameter, method receiver/nested receiver, and imported alias-qualified
  method receiver passthrough history, direct field reads, field history, and
  `na()` checks only.

## Acceptance Criteria For Expanding History

- The supported subset is represented in `tests/fixtures/conformance.tsv`.
- Every accepted offset form has semantic and runtime fixture coverage.
- Unsupported variants fail during semantic analysis with stable diagnostics.
- Incremental append execution matches full historical execution.
- Realtime rollback keeps history, `var`, callsite state, and outputs
  consistent for confirmed bars and forming-bar updates.
