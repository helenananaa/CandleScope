# Qualifier Audit

This document records the Phase C qualifier audit that follows
`docs/HISTORY_SERIES_AUDIT.md`.

## Implemented Qualifier Model

The IR has four qualifiers:

```text
const < input < simple < series
```

Current inference:

- literals and named constants are `const`
- `input.*` functions return `input` values, except `input.source`, which
  returns `series float`
- OHLCV, time components, derived price sources, and `bar_index` are `series`
- binary, ternary, switch, `for`, and `while` expressions use the strongest
  relevant operand/header/condition or branch qualifier; ternary, if-expression,
  condition-form switch expressions, selector-form switch expressions with
  known const bool/int/float/string/color selector keys, final-if UDF returns, and their
  tuple-destructuring forms with statically known const selection still require
  compatible branch value kinds but use only the selected branch qualifier plus
  the condition or selector qualifier
- known numeric conditions may include nested calls from the exact scalar
  constant whitelist: `int`, `float`, `math.min`, `math.max`, `math.abs`,
  `math.floor`, `math.ceil`, and `math.trunc`; these calls can select the
  reachable branch when all arguments and the evaluator result are known
- if-expression branches, switch block arms, and loop-expression bodies can
  return final `for`, `for...in`, or `while` loop expressions, with loop
  headers, iterables, or conditions included in the result qualifier
- history references always return `series` values
- explicit scalar typed declarations now keep the initializer qualifier when the
  initializer is not `na`; explicit scalar typed declarations initialized with
  `na` can take the qualifier from a later compatible scalar reassignment; the
  declared type constrains the value kind, while later reassignments can promote
  the variable to a stronger qualifier
- compatible scalar reassignments can promote variables from weaker qualifiers
  to stronger qualifiers instead of requiring the original qualifier forever;
  statement-/expression-form `if` branch, `while` body, `for` body, `for...in`
  body, loop-expression body, and statement-/expression-form `switch` block arm
  reassignments, plus final-if UDF and user-method branch reassignments, include
  the relevant condition, selector, header, or iterable qualifier for scalar
  values, so
  series-controlled assignments cannot remain `simple`
- array ids are `simple` values, while array element reads and aggregate helpers
  generally return `series` values
- user-defined functions are typed from the inlined body with callsite argument
  types; expression and block UDF returns preserve fixture-backed `input` and
  `simple` scalar qualifiers through `SimpleInt`/simple-string built-in
  arguments, including final `if` branches, final loop returns, and final `if`
  branches whose selected branch itself ends in a final `for`, `for...in`, or
  `while` return, plus final selector-form `switch` returns when the selector is
  supplied by a const bool/int/float/string/color callsite argument, including
  tuple-destructured UDF, nested-UDF, and user-method returns. Final loops are
  promoted by series-qualified loop headers, iterables, or conditions. Tuple
  destructuring carries callsite UDT identity through UDF parameters when
  expanding local user-method and alias-qualified imported-method tuple returns,
  so method-returned tuple elements preserve the original `input`/`simple`
  qualifiers where the method body returns those arguments.
  Imported exported UDF calls are fixture-backed for scalar/simple-string
  passthrough and block-local returns.
  Const callsite values are attached to the bound UDF/method parameter symbol,
  so bool, numeric, string, and color comparisons select the same branch in
  scalar and tuple type queries without capturing an unrelated same-named
  global. Condition-form switches accumulate qualifiers only from reachable
  preceding conditions: fallback assignments inherit earlier dynamic
  conditions, while conditions after a statically selected arm do not promote
  the selected result.
- local user-defined method returns preserve fixture-backed `input` and `simple`
  scalar qualifiers through expression, block-local, final-if, final-for,
  final-for-in, final-while, final-if branch final-loop, and switch block return
  shapes, allowing method-returned lengths and timeframe strings to satisfy
  `SimpleInt` and simple-string consumers when the body returns the callsite
  argument qualifier. Imported user-defined method receiver-style and
  alias-qualified calls are fixture-backed for scalar/simple-string passthrough
  returns.

## Parameter Acceptance Rules

The analyzer validates built-in arguments using the `Accepts` enum in
`pine-builtins` and `accepts_type` in `pine-sema`.

The scalar `Simple*`, `Const*`, and `AtMostInput*` family is represented by one
`QualifierBoundScalar` model containing an exact/at-most relation, qualifier
bound, scalar kind, and `na`-compatibility flag. Existing `Accepts` names remain
associated constants, while acceptance and expected-label diagnostics share
the generic model.

Important current rules:

- Exact type checks allow weaker qualifiers to flow into stronger targets.
- `series` targets accept weaker same-kind values.
- `int` may widen to `float`; `float` does not narrow to `int`.
- `SimpleInt` accepts `const`, `input`, or `simple` integers and rejects
  `series int`.
- `IntCompatible` accepts integer values at any implemented qualifier; current
  fixture-backed uses include dynamic history offsets, time bars-back
  arguments, `math.sum`, `ta.sma`,
  `ta.change`/`ta.mom`/`ta.roc`/`ta.rising`/`ta.falling` length,
  `ta.highest`/`ta.lowest`/`ta.highestbars`/`ta.lowestbars` length,
  `ta.valuewhen` occurrence, and `ta.pivothigh`/`ta.pivotlow` left/right bar
  counts.
- `AtMostInputNumeric`, `AtMostInputString`, `AtMostInputBool`, and
  `AtMostInputColor` accept matching `const` or `input` scalar values and
  reject `simple`/`series` values.
- `SeriesFloat` requires an actual `series float`.
- Compatibility names such as `SeriesOrSimpleNumeric` currently mean any
  numeric qualifier at or below `series`; this includes `const` and `input`.
- Coarse acceptors such as `Numeric`, `Kind`, and `Array` do not narrow by
  qualifier beyond the value kind.

## Current Gaps

- `Simple` inference is complete for the current fixture-backed scalar scope.
  That scope includes explicit scalar typed declarations, including typed-`na`
  scalar declarations followed by compatible
  scalar reassignments, scalar statement-/expression-`if`,
  statement-/expression-loop, statement-/expression-`switch`, and final-if
  UDF/user-method reassignments, UDF-local aliases, and const-condition branch
  selection preserve or promote initializer/callsite qualifiers for
  fixture-backed const, input, simple, and series scalar flows, including tuple
  destructuring from literal, named, or numeric/bool/string/color
  equality-derived const condition branches plus condition-form switch arms and
  selector-form switch arms with const bool/int/float/string/color callsite selector
  arguments. `tests/fixtures/runtime/typed_declaration_qualifiers.pine` keeps
  explicit scalar typed declaration qualifier preservation, typed-`na`
  reassignment inheritance, UDF-local typed-`na` reassignment, and later series
  promotion executable. `tests/fixtures/runtime/const_condition_qualifier_narrowing.pine`
  keeps the same narrowing paths executable against simple-only TA consumers.
  `tests/fixtures/runtime/udf_qualifier_propagation.pine` and
  `tests/fixtures/runtime/method_qualifier_propagation.pine` keep local UDF and
  local user-method scalar/simple-string qualifier propagation executable across
  expression, block-local, final-loop, branch-loop, switch-block, nested-loop,
  and while-result return forms,
  `tests/fixtures/runtime/import_udt_udf_qualifier_propagation.pine` keeps
  imported exported-UDF passthrough and block-local returns executable, while
  `tests/fixtures/runtime/import_udt_method_qualifier_propagation.pine` keeps
  imported receiver-style and alias-qualified method passthrough, block-local,
  and final-loop returns executable.
  Statement-form and expression-form `for` loop counters now include the
  explicit `by` step qualifier, so a series-qualified step promotes the counter
  visible inside the loop body.
  Broader whole-program qualifier inference remains intentionally limited.
- There is no separate runtime input immutability model beyond the qualifier
  assigned by semantic analysis.
- Constant-call reasoning is intentionally not a general purity engine. Only
  `int`, `float`, `math.min`, `math.max`, `math.abs`, `math.floor`, `math.ceil`,
  and `math.trunc` currently feed static branch selection, declaration checks,
  history-offset analysis, and `max_bars_back`; other pure calls remain outside
  this static-value boundary.
- Built-in signature docs use descriptive Pine-like terms, while code uses a
  smaller `Accepts` enum. Qualifier-bounded scalar phrases now share the generic
  `QualifierBoundScalar` data model, but not every Pine-style collection,
  cross-parameter, or promoted-return phrase has a distinct variant.
- History offsets accept non-negative integer literals plus integer expressions,
  including local and imported scalar-tree UDT integer field reads, and fields on
  imported UDF/method-returned scalar-tree UDT values at any implemented
  qualifier, including `series int`. Runtime negative-offset rejection is
  fixture-backed for direct/nested imported scalar-tree UDT fields as well as
  imported UDF/receiver-style or alias-qualified method-returned direct/nested
  fields.
- Scalar array, scalar slice, label-array, label-slice, line-array,
  line-slice, box-slice, linefill-array, linefill-slice, polyline-array,
  polyline-slice, box-array, table-array, table-slice, chart.point-array,
  chart.point-slice, and same-local or same-imported scalar-tree UDT-array ids
  can now receive series storage for fixture-backed array history snapshots.
- Matrix history snapshots are fixture-backed for committed matrix values,
  dynamic matrix offsets including `na` offset predicates, and
while-expression matrix results. Scalar map values, scalar-tree local UDT
values, scalar-tree imported UDT values, local/imported non-scalar typed-`na`
UDT values with direct, `var`, ternary, `if`, `switch`, `for`, `for...in`,
`while`, local/imported exported UDF passthrough, method parameter passthrough,
imported method non-receiver parameter passthrough, method receiver/nested
receiver passthrough, and imported alias-qualified method receiver passthrough
identity-preserving history plus direct field reads, field history, and `na()`
checks, and
scalar-tree local/imported UDT `varip` values are fixture-backed for history snapshots,
including exported imported UDTs whose scalar-tree metadata depends on private
library UDT declarations. Local/imported constructed non-scalar
label/line/box/chart.point-field UDT history is fixture-backed, including
direct chained `chart.point` field reads such as `value.anchor.index`;
non-scalar UDT value history outside that narrow path, drawing-object
collections beyond fixture-backed id arrays/slices, and broader aliasing rules
remain undesigned or rejected.

## Impact On Dynamic History

Dynamic history offsets now use an explicit integer-kind policy:

- `const int`: supported; non-negative literals and supported constant integer
  expressions lower to a constant offset, while other const int expressions are
  evaluated by the runtime guard.
- `input int`: supported with runtime validation.
- `simple int`: supported with runtime validation.
- `series int`: supported with runtime validation and conservative full-history
  retention up to the runtime cap.
- non-integer offsets remain rejected, including UDT field-read offsets.
  Fixture coverage includes local/imported UDF direct/nested passthrough/
  constructor-returned fields, local method direct/nested
  passthrough/constructor-returned fields plus method-returned bool/string
  fields, and imported receiver-style or alias-qualified method direct/nested
  passthrough/constructor-returned fields.

## Phase C Closeout

The history-offset qualifier policy is implemented and fixture-covered for
const, input, simple, and series integers, including integer-valued ternary, if,
switch, for, for-in, while, and built-in call results. Shared qualifier-bound argument
helpers back the current "at most input" and "at most simple" acceptors,
including fixture-backed UDT `array.new<T>` size and initial_value diagnostics,
plus its local scalar-tree UDT requirement diagnostic,
while the generic built-in argument path shares the same diagnostic constructor
after preserving its specialized acceptor checks. UDT array sort and sort_indices
order/sort_field const-string and sort-field requirement diagnostics also use
shared helpers, and map template plus map operation receiver/source and
key/value diagnostics share the same diagnostic constructor while preserving
map-specific key/value compatibility checks. `map.put_all` source/target
template mismatch diagnostics now report canonical key/value type names.
Drawing constructor
argument type diagnostics for `label.new`, `line.new`, and `box.new` now use
the same expected/got acceptor helper, including `string/int-compatible` and
`chart.point-compatible` labels, while keeping their dedicated drawing option
validators.

The scalar const-value path is also shared rather than duplicated across
qualifier and history consumers. Its explicit `int`, `float`, `math.min`,
`math.max`, `math.abs`, `math.floor`, `math.ceil`, and `math.trunc` whitelist
drives static branch selection, declaration range checks, history-offset
classification, and `max_bars_back` inference without implying support for
arbitrary pure-call folding. Finite `int(float)` calls use the runtime-compatible
truncating/saturating `i64` conversion before consumer-specific range checks;
out-of-`i64` float results from `math.floor`, `math.ceil`, and `math.trunc`
remain unknown.

Array value compatibility and concatenation diagnostics use expected/got
call-argument helpers for element-family and array-kind labels, and
`array.from` inference failures report the actual argument types, while
UDT-specific `array.from` failures distinguish mixed UDT identities from
non-scalar-field UDTs or unresolved UDT identities, preserving
array-kind-specific compatibility checks. UDT array identity
mismatch diagnostics also share the
expected/got label helper while preserving UDT-specific type names, and UDT
array value-kind diagnostics report the expected UDT value family. Selected
special overload validators, including pivot default-source bar counts and
single-argument extrema lengths, now share an acceptor-to-expected-label helper
for clearer qualifier-bound diagnostics while keeping the generic built-in
argument path stable. The generic built-in argument path also uses that helper
for the `AtMostInput*` scalar acceptor family, so fixture-backed `plot`
histbase, `hline` price, `plot`/`hline` linewidth,
`plot`/`plotchar`/`plotshape`/`plotarrow`/`plotbar`/`plotcandle`/`fill`/
`bgcolor`/`barcolor` show_last, and `hline` color diagnostics
report the expected const/input numeric, int, or color bound rather than only the
rejected actual type, and future const/input string or bool parameters can share
the same expected/got diagnostic path. The `time`/`time_close` and `timestamp` custom overload
validators use the same helper for simple-string timeframe and const-string
dateString diagnostics while preserving their overload-specific positional
messages. The generic built-in argument path additionally uses the helper for
`Numeric`, object-compatible drawing/table identifiers, `IntCompatible`,
`SimpleInt`, `SimpleString`, `SimpleNumeric`, `SimpleBool`, `ConstString`,
`ConstBool`, and `ConstNumeric` parameters, so
fixture-backed `request.security` symbol/timeframe-style arguments and TA
parameters such as `ta.alma` offset/sigma/floor, `ta.kc`/`ta.kcw` mult,
`ta.supertrend` factor, and `ta.sar` acceleration values report explicit
simple-bound expectations, fixture-backed TA length/offset and array index
parameters report explicit simple-int expectations, object array constructors
and object casts report explicit object-compatible expectations, while array
sort `order` parameters report explicit const-string expectations and `ta.tr`
`handle_na` reports explicit const-bool expectations. `max_bars_back(source, N)`
now uses the same generic source-argument helper, so non-series sources report
the expected series-numeric bound instead of a bespoke value diagnostic.
`request.security` has fixture-backed `SeriesFromArg` return semantics for the
supported same-context scalar subset: int, float, bool, color, and string
expressions produce matching series results accepted by series-compatible
consumers and rejected by stricter simple or const/input consumers.
Fixture-backed dynamic integer parameters such as `math.sum`, `ta.sma`,
`ta.change`/`ta.mom`/`ta.roc` length, and `ta.valuewhen` occurrence report
explicit integer-compatible expectations. Helper unit coverage also locks the
generic const-numeric
expected label. The same helper also backs same-local UDT
`array.new<T>` size
diagnostics so the fixture-backed simple-int bound reports the expected
qualifier rather than only the rejected actual type.
UDT array chained field mutation index diagnostics also use the helper, so the
fixture-backed `array.get` index bound reports the same simple-int expectation
as normal array reads. Generic array receiver acceptors for plain, numeric,
numeric/bool, numeric/string, and scalar arrays also use the helper, so
fixture-backed `array.concat`, `array.sort`, `array.sort_indices`,
`array.every`, `array.some`, `array.variance`, and `array.stdev` receiver
diagnostics report the expected array family instead of only the rejected actual
type. Fixture-backed `array.covariance` pair diagnostics now lock both `id1`
and `id2` numeric-array expectations. Basic matrix receiver acceptors for any,
numeric, and float matrices also use the helper, so fixture-backed namespace
`id` diagnostics report either matrix or numeric-matrix expectations instead of
only the rejected actual type. String
conversion, scalar cast, string-cast, and numeric/color helper acceptors also
use the expected/got helper, so fixture-backed `str.tostring`/`str.format`
diagnostics for collection, object-array, UDT, and tuple rejections, plus
helper-covered cast/fixnan diagnostics, report the expected compatible family.
Numeric casts `int()` and `float()` have fixture-backed return qualifier
propagation: input numeric arguments produce input numeric results accepted by
const/input consumers, while simple numeric arguments produce simple numeric
results rejected by those consumers.
String and color casts `string()` and `color()` have fixture-backed return
qualifier propagation: input arguments produce input strings/colors accepted by
const/input consumers, while simple arguments produce simple strings/colors
rejected by those consumers.
`bool()` and `na()` have fixture-backed `BoolFromArg` return propagation: input,
simple, and series arguments produce input, simple, and series bool results
respectively.
Input functions have fixture-backed return qualifiers: generic `input()`
promotes const scalar defval arguments to the matching input qualifier,
specialized scalar input functions return their fixed input qualifiers, and
`input.source` returns `series float`. The fixture set covers accepted
input/simple/series consumers plus const-string, const-bool, and simple-numeric
rejections.
Value helpers `nz()` and `fixnan()` have fixture-backed `SameAsArg` return
propagation: input arguments preserve input numeric/color results accepted by
const/input consumers, while simple arguments remain simple and are rejected by
those consumers.
Time component functions `year`, `month`, `weekofyear`, `dayofmonth`,
`dayofweek`, `hour`, `minute`, and `second`, plus `timestamp`, have
fixture-backed `PromotedInt` return propagation: input time/calendar arguments
produce input int results accepted by const/input int consumers, while simple
arguments produce simple int results rejected by those consumers.
Global time variables `time`, `time_close`, and `time_tradingday` have
fixture-backed fixed `series int` semantics: they are accepted by series numeric
consumers such as `plot(...)` and rejected by simple-int consumers such as
`plot(offset=...)`.
Time functions `time()` and `time_close()` have fixture-backed fixed
`series int` return semantics using the same series numeric and simple-int
consumers. `timeframe.change()` has fixture-backed fixed `series bool` return
semantics using the same series-bool and simple-bool consumers as session state
variables.
Time component variables `year`, `month`, `weekofyear`, `dayofmonth`,
`dayofweek`, `hour`, `minute`, and `second` have fixture-backed fixed
`series int` semantics using the same series numeric and simple-int consumers as
global time variables.
Global OHLCV variables `open`, `high`, `low`, `close`, and `volume` have
fixture-backed fixed `series float` semantics: they are accepted by series
numeric consumers such as `plot(...)` and rejected by simple numeric consumers
such as `ta.alma(..., offset/sigma=...)`.
Derived price sources `hl2`, `hlc3`, `hlcc4`, and `ohlc4` have fixture-backed
fixed `series float` semantics using the same series numeric and simple numeric
consumers as OHLCV variables. `bar_index` has fixture-backed fixed `series int`
semantics: it is accepted by series numeric consumers such as `plot(...)` and
rejected by simple-int consumers such as `plot(offset=...)`.
Last-bar metadata variables `last_bar_index` and `last_bar_time` have
fixture-backed fixed `series int` semantics: they are accepted by series numeric
consumers such as `plot(...)` and rejected by simple-int consumers such as
`plot(offset=...)`.
Bar-state metadata variables `barstate.isfirst`, `barstate.islast`,
`barstate.islastconfirmedhistory`, `barstate.isnew`, `barstate.isconfirmed`,
`barstate.ishistory`, and `barstate.isrealtime` have fixture-backed fixed
`series bool` semantics using the same series-bool and simple-bool consumers as
session state variables.
Session state and boundary variables `session.ismarket`, `session.ispremarket`,
`session.ispostmarket`, `session.isfirstbar`, `session.islastbar`,
`session.isfirstbar_regular`, and `session.islastbar_regular` have
fixture-backed fixed `series bool` semantics: they are accepted in series-bool
expressions and rejected by simple-bool consumers such as `ta.alma(...,
floor=...)`.
`timeframe.in_seconds` has fixture-backed fixed `simple int` return semantics:
the result is accepted by simple-int consumers such as moving-average lengths
and rejected by const/input int consumers such as `plot(show_last=...)` across
no-argument, const-timeframe, and input-timeframe calls.
`timeframe.from_seconds` has fixture-backed fixed `simple string` return
semantics: the result is accepted by simple-string consumers such as `time`
timeframe arguments and rejected by const string consumers such as
`timestamp(dateString=...)` across const, nested simple, and input-second calls.
Timeframe metadata strings `timeframe.period` and `timeframe.main_period` have
fixture-backed fixed `simple string` return semantics using the same
simple-string and const-string consumers.
Timeframe metadata booleans `timeframe.isticks`, `timeframe.isseconds`,
`timeframe.isminutes`, `timeframe.isintraday`, `timeframe.isdaily`,
`timeframe.isweekly`, `timeframe.ismonthly`, and `timeframe.isdwm` have
fixture-backed fixed `simple bool` return semantics: they are accepted by
simple-bool consumers such as `ta.alma(..., floor=...)` and rejected by
const-bool consumers such as `ta.tr(handle_na=...)`.
Chart type metadata booleans `chart.is_standard`, `chart.is_heikinashi`,
`chart.is_kagi`, `chart.is_linebreak`, `chart.is_pnf`, `chart.is_range`, and
`chart.is_renko` have fixture-backed fixed `simple bool` return semantics using
the same simple-bool and const-bool consumers.
Chart appearance metadata colors `chart.bg_color` and `chart.fg_color` have
fixture-backed fixed `simple color` return semantics: they are accepted by
color-compatible consumers such as `plot(color=...)` and rejected by const/input
color consumers such as `hline(color=...)`.
`chart.point.new`, `chart.point.now`, `chart.point.from_index`,
`chart.point.from_time`, and `chart.point.copy` have fixture-backed fixed
`series chart.point` return semantics: results are accepted by
chart.point-compatible consumers such as `label.new(point=...)` and rejected
by numeric consumers such as `hline(price=...)`.
Drawing constructors `label.new`, `line.new`, `box.new`, `table.new`,
`linefill.new`, and `polyline.new` have fixture-backed fixed series object
return semantics: results are accepted by their matching object-compatible
consumers and rejected by numeric consumers such as `hline(price=...)`.
Drawing object helpers `label.copy`, `line.copy`, `box.copy`,
`linefill.get_line1`, and `linefill.get_line2` have fixture-backed fixed series
object return semantics with the same matching-consumer and numeric-rejection
coverage, including namespace and method forms for `linefill` line getters.
Drawing scalar getters `label.get_x`, `label.get_y`, `label.get_text`,
`line.get_price`, `line.get_x1`, `line.get_y1`, `line.get_x2`, `line.get_y2`,
`box.get_left`, `box.get_top`, `box.get_right`, and `box.get_bottom` have
fixture-backed fixed series scalar return semantics: numeric results are
accepted by series numeric consumers and rejected by const/input numeric
consumers, while text results are accepted by string-compatible consumers and
rejected by simple string consumers, in both namespace and method forms.
Drawing collection variables `label.all`, `line.all`, `box.all`, `table.all`,
`linefill.all`, and `polyline.all` have fixture-backed fixed
`simple array<T>` return semantics: results are accepted by matching typed
object-array consumers and rejected by mismatched object-array consumers.
String metadata variables `syminfo.tickerid`, `syminfo.main_tickerid`,
`syminfo.ticker`, `syminfo.prefix`, `syminfo.description`, `syminfo.sector`,
`syminfo.industry`, `syminfo.country`, `syminfo.type`, `syminfo.currency`,
`syminfo.basecurrency`, `syminfo.session`, `syminfo.timezone`, `syminfo.root`,
and `syminfo.volumetype` have fixture-backed fixed `simple string` semantics:
they are accepted by simple-string consumers such as `syminfo.prefix(symbol=...)`
and rejected by const string consumers such as `timestamp(dateString=...)`.
Symbol helper functions `syminfo.prefix(symbol)` and `syminfo.ticker(symbol)`
also have fixture-backed fixed `simple string` return semantics: results are
accepted by simple-string consumers and rejected by const-string consumers.
Numeric metadata variables `syminfo.mintick`, `syminfo.mincontract`, and
`syminfo.pointvalue` have fixture-backed fixed `simple float` semantics, while
`syminfo.minmove` and `syminfo.pricescale` have fixture-backed fixed
`simple int` semantics: they are accepted by simple numeric/int consumers and
rejected by const/input numeric/int consumers.
Ticker ID constructors and modifiers `ticker.new`, `ticker.modify`,
`ticker.standard`, `ticker.heikinashi`, `ticker.inherit`, `ticker.linebreak`,
`ticker.kagi`, `ticker.pointfigure`, and `ticker.renko` have fixture-backed
fixed `simple string` return semantics: results are accepted by simple-string
consumers and rejected by const-string consumers.
`timeframe.multiplier`, `chart.left_visible_bar_time`, and
`chart.right_visible_bar_time` have fixture-backed fixed `simple int` return
semantics: they are accepted by simple-int consumers such as `plot(offset=...)`
and rejected by const/input int consumers such as `plot(show_last=...)`.
Integer rounding helpers `math.floor`, `math.ceil`, and `math.trunc` have
fixture-backed return qualifier propagation: input numeric arguments produce
input int results accepted by const/input int consumers, while simple numeric
arguments produce simple int results rejected by those consumers.
`math.round` has fixture-backed dedicated return propagation: the single-arg
form returns an int with the number argument's qualifier, while the precision
form returns a float with promoted argument qualifiers; simple results from
both forms remain simple and are rejected by const/input consumers.
`math.abs` has fixture-backed `SameAsArg` return propagation: input int and
input float arguments preserve both numeric kind and qualifier for const/input
consumers, while simple int and simple float arguments remain simple and are
rejected by those consumers.
Current `FloatFromArg` math helpers, including logarithmic, exponential,
inverse-trig, trigonometric, conversion, sign, and mintick-rounding helpers,
now have fixture-backed return qualifier propagation: input numeric arguments
produce input float results accepted by const/input numeric consumers, while
simple numeric arguments produce simple float results rejected by those
consumers.
`ta.sma`, `ta.ema`, `ta.dema`, `ta.tema`, `ta.rma`, and `ta.rsi` have
fixture-backed fixed `series float` return semantics accepted by series numeric
consumers and rejected by const/input numeric consumers.
`ta.change` has fixture-backed `ChangeFromArg` return semantics: numeric
sources produce `series float` results accepted by series numeric consumers and
rejected by const/input numeric consumers, while bool sources produce
`series bool` results rejected by simple-bool consumers.
`ta.mom` and `ta.roc` have fixture-backed fixed `series float` return
semantics accepted by series numeric consumers and rejected by const/input
numeric consumers.
`ta.tsi`, `ta.cmo`, `ta.cci`, and `ta.cog` have fixture-backed fixed
`series float` return semantics accepted by series numeric consumers and
rejected by const/input numeric consumers.
`ta.mfi`, `ta.stoch`, and `ta.wpr` have fixture-backed fixed `series float`
return semantics accepted by series numeric consumers and rejected by
const/input numeric consumers.
`ta.tr` variable and function forms, `ta.atr`, and `ta.sar` have
fixture-backed fixed `series float` return semantics accepted by series
numeric consumers and rejected by const/input numeric consumers.
`ta.range`, `ta.dev`, `ta.bbw`, and `ta.kcw` have fixture-backed fixed
`series float` return semantics accepted by series numeric consumers and
rejected by const/input numeric consumers.
`ta.correlation`, `ta.covariance`, `ta.stdev`, and `ta.variance` have
fixture-backed fixed `series float` return semantics accepted by series
numeric consumers and rejected by const/input numeric consumers.
`ta.median`, `ta.mode`, `ta.percentile_nearest_rank`,
`ta.percentile_linear_interpolation`, and `ta.percentrank` have fixture-backed
fixed `series float` return semantics accepted by series numeric consumers and
rejected by const/input numeric consumers.
`ta.wma`, `ta.vwma`, `ta.swma`, `ta.hma`, `ta.alma`, and `ta.linreg` have
fixture-backed fixed `series float` return semantics accepted by series
numeric consumers and rejected by const/input numeric consumers.
`ta.macd` has fixture-backed tuple element `series float` return semantics
accepted by series numeric consumers and rejected by const/input numeric
consumers after destructuring.
`ta.supertrend` has fixture-backed tuple element `series float` return
semantics accepted by series numeric consumers and rejected by const/input
numeric consumers after destructuring.
`ta.dmi` has fixture-backed tuple element `series float` return semantics
accepted by series numeric consumers and rejected by const/input numeric
consumers after destructuring.
`ta.bb` and `ta.kc` have fixture-backed tuple element `series float` return
semantics accepted by series numeric consumers and rejected by const/input
numeric consumers after destructuring.
`ta.cum`, `ta.max`, and `ta.min` have fixture-backed fixed `series float`
return semantics accepted by series numeric consumers and rejected by
const/input numeric consumers.
Zero-argument helpers `ta.ao` and `ta.bop` have fixture-backed fixed
`series float` return semantics accepted by series numeric consumers and
rejected by const/input numeric consumers.
TA volume/accumulation variables `ta.accdist`, `ta.iii`, `ta.nvi`, `ta.obv`,
`ta.pvi`, `ta.pvt`, `ta.wad`, and `ta.wvad` have fixture-backed fixed
`series float` return semantics accepted by series numeric consumers and
rejected by const/input numeric consumers.
`ta.highest` and `ta.lowest` have fixture-backed fixed `series float` return
semantics accepted by series numeric consumers and rejected by const/input
numeric consumers, while `ta.highestbars` and `ta.lowestbars` have
fixture-backed fixed `series int` return semantics accepted by series numeric
consumers and rejected by simple-int consumers.
`ta.rising` and `ta.falling` have fixture-backed fixed `series bool` return
semantics: results are accepted by series-bool conditions and rejected by
simple-bool consumers.
`ta.cross`, `ta.crossover`, and `ta.crossunder` have fixture-backed fixed
`series bool` return semantics: results are accepted by series-bool conditions
and rejected by simple-bool consumers.
`ta.barssince` has fixture-backed fixed `series int` return semantics: results
are accepted by series numeric consumers and rejected by simple-int consumers.
`ta.valuewhen` has fixture-backed `SeriesFromArg` return semantics from its
source argument: int, float, bool, and color sources produce matching series
results accepted by series-compatible consumers and rejected by stricter
simple or const/input consumers.
`ta.vwap` has fixture-backed fixed `series float` return semantics for the
variable, source, and source/anchor scalar forms, and its bands overload has
fixture-backed tuple element semantics where basis, upper, and lower are each
`series float`; all are accepted by series numeric consumers and rejected by
const/input numeric consumers.
`color.new` has fixture-backed `ColorFromArg` return propagation from its base
color argument: input color arguments produce input colors accepted by
const/input color consumers, while simple color arguments remain simple colors
and are rejected by those consumers.
Color component helpers `color.r`, `color.g`, `color.b`, and `color.t` have
fixture-backed `FloatFromArg` return propagation from color arguments: input
color arguments produce input float channel values accepted by const/input
numeric consumers, while simple color arguments produce simple float results
rejected by those consumers.
`str.length` has fixture-backed `IntFromArg` return propagation from string
arguments: input string arguments produce input int lengths accepted by
const/input int consumers, while simple string arguments produce simple int
results rejected by those consumers.
`str.upper`, `str.lower`, and `str.trim` have fixture-backed `SameAsArg`
string return propagation, verified indirectly through `str.length`: input
string arguments stay input strings and simple string arguments stay simple
strings.
`str.contains`, `str.startswith`, and `str.endswith` have fixture-backed
`PromotedBool` return propagation: input string arguments produce input bool
results accepted by simple-bool consumers but rejected by const-bool consumers,
simple string arguments remain simple bools rejected by const-bool consumers,
and series string arguments produce series bool results rejected by simple-bool
consumers.
`str.substring`, `str.repeat`, `str.replace`, and `str.replace_all` have
fixture-backed `PromotedString` return propagation, also verified indirectly
through `str.length`: input string/int arguments produce input strings while
simple string arguments remain simple strings.
`str.match` has fixture-backed `PromotedString` return propagation, also
verified indirectly through `str.length`: input source/regex arguments produce
input strings while simple arguments remain simple strings.
`str.split` has fixture-backed fixed `simple array<string>` return semantics:
results are accepted by exact string-array consumers and rejected by mismatched
array consumers, including when the source argument is series string.
`str.tostring`, `str.format`, and `str.format_time` have fixture-backed
`PromotedString` return propagation, also verified indirectly through
`str.length`: input formatting/value arguments produce input strings while
simple arguments remain simple strings.
`str.tonumber` has fixture-backed `FloatFromStringArg` return propagation:
input string arguments produce input float values accepted by const/input
numeric consumers, while simple string arguments produce simple float results
rejected by those consumers.
`array.from` has fixture-backed `ArrayFromArgs` return qualifier semantics:
scalar int, mixed int/float, bool, string, and color arguments produce matching
`simple array<T>` results, with mixed numeric arguments promoted to
`simple array<float>`; results are accepted or rejected by exact matrix
element-array consumers accordingly. Label, line, linefill, polyline, box,
table, and chart.point arguments likewise produce matching `simple array<T>`
results accepted or rejected by exact typed-UDF and typed-method array
consumers. Local and imported scalar-tree UDT arguments likewise produce same-identity
`simple array<UDT>` results accepted by matching typed-UDF and typed-method
array consumers and rejected when the UDT identity differs.
`array.new_float`, `array.new_int`, `array.new_bool`, `array.new_string`,
`array.new_color`, and their official `array.new<float>`, `array.new<int>`,
`array.new<bool>`, `array.new<string>`, and `array.new<color>` template forms
have fixture-backed fixed `simple array<T>` return semantics: constructed arrays
are accepted or rejected by exact matrix element-array consumers according to
their element kind.
`array.new_label`, `array.new_line`, `array.new_linefill`,
`array.new_polyline`, `array.new_box`, `array.new_table`, their official
`array.new<type>` template forms, and `array.new<chart.point>` have
fixture-backed fixed `simple array<T>` return semantics: constructed arrays are
accepted or rejected by exact typed-UDF and typed-method array consumers
according to their element kind.
`array.new<UDT>` has fixture-backed same-identity `simple array<UDT>` return
semantics for local and imported scalar-tree UDTs: constructed arrays are
accepted by matching typed-UDF and typed-method array consumers and rejected
when the UDT identity differs.
`array.size` has fixture-backed fixed `simple int` return semantics for both
namespace and method-call forms: results are accepted by simple-int consumers and
rejected by const/input int consumers.
`array.get`, `array.remove`, `array.pop`, `array.shift`, `array.first`, and
`array.last` have fixture-backed `ArrayElement` return qualifier semantics for
namespace and method-call forms: scalar element results are returned as series
values accepted by series consumers and rejected by const/input consumers, while
object/chart.point and same-identity local/imported scalar-tree UDT element
results flow into matching typed-method consumers and reject mismatched
identities or object kinds, including alias-qualified imported method calls over
same-imported scalar-tree UDT array element receivers.
`array.copy`, `array.slice`, and `array.concat` have fixture-backed
`SameAsArg` simple-array return qualifier semantics for namespace and
method-call forms: returned arrays preserve the first array argument's
`simple array<T>` type and are accepted or rejected by exact matrix
element-array consumers accordingly. Non-side-effecting `array.copy` and
`array.slice` results are also fixture-backed through direct typed-method array
consumers for scalar, object, chart.point, and same-identity local/imported
scalar-tree UDT arrays; direct `array.concat` method arguments remain governed
by the existing user-method side-effect policy.
`array.includes` has fixture-backed fixed `series bool` return semantics for
namespace and method-call forms over scalar, object/chart.point, and
same-identity local/imported scalar-tree UDT arrays: results are accepted by
series-bool consumers and rejected by const-bool consumers. `array.every` and
`array.some` have the same return-qualifier coverage for their supported
int/float/bool scalar truthiness array families; object/chart.point and UDT
truthiness remains unsupported.
`array.indexof` and `array.lastindexof` have fixture-backed fixed `simple int`
return semantics for namespace and method-call forms over scalar,
object/chart.point, and same-identity local/imported scalar-tree UDT arrays:
results are accepted by simple-int consumers and rejected by const/input int
consumers. `array.binary_search`, `array.binary_search_leftmost`, and
`array.binary_search_rightmost` have the same return-qualifier coverage for
namespace and method-call forms over their supported int/float numeric ordering
array families; object/chart.point and UDT ordering remains unsupported.
`array.abs` has fixture-backed `SameAsArg` simple-array return qualifier
semantics for namespace and method-call forms over int/float numeric arrays:
returned arrays preserve the source array's `simple array<int>` or
`simple array<float>` type and are accepted or rejected by exact matrix
element-array consumers accordingly.
`array.min`, `array.max`, `array.sum`, `array.range`, `array.median`,
`array.mode`, and `array.percentile_nearest_rank` have fixture-backed
`ArrayNumeric` return qualifier semantics for namespace and method-call forms:
int-array results are returned as `series int`, while float-array results are
returned as `series float`, and both are rejected by stricter const/input
consumers.
`array.avg`, `array.percentile_linear_interpolation`, `array.percentrank`,
`array.covariance`, `array.variance`, and `array.stdev` have fixture-backed
fixed `series float` return semantics for namespace and method-call forms over
int/float arrays: results are accepted by series numeric consumers and rejected
by const/input numeric consumers.
`array.standardize` and `array.sort_indices` have fixture-backed fixed
simple-array return semantics for namespace and method-call forms over int/float
arrays:
`array.standardize` returns `simple array<float>`, while `array.sort_indices`
returns `simple array<int>`, and both are accepted or rejected by exact matrix
element-array consumers accordingly.
`array.join` has fixture-backed fixed `series string` return semantics for
namespace and method-call forms: results are accepted by series-string
consumers through `str.length` and rejected by simple-string consumers.
`map.size` has fixture-backed fixed `simple int` return semantics for namespace
and method-call forms: results are accepted by simple-int consumers and rejected
by const/input int consumers.
`map.get` and `map.contains` have fixture-backed fixed `series` value/bool
return semantics for namespace and method-call forms, while `map.keys` and
`map.values` have fixture-backed fixed `simple array<K/V>` return semantics;
namespace and method-call results are accepted by series or exact element-array
consumers and rejected by const/input or mismatched element-array consumers.
`map.copy` keeps the source map template available to later map operations.
`matrix.rows`, `matrix.columns`, and `matrix.elements_count` have fixture-backed
fixed `simple int` return semantics for each namespace and method-call form:
results are accepted by simple-int consumers and rejected by const/input int
consumers.
`matrix.is_square`, `matrix.is_binary`, `matrix.is_diagonal`,
`matrix.is_identity`, `matrix.is_symmetric`, `matrix.is_antisymmetric`,
`matrix.is_stochastic`, and `matrix.is_zero` have fixture-backed fixed
`simple bool` return semantics for namespace and method-call forms: results are
accepted by simple-bool consumers and rejected by const-bool consumers.
`matrix.is_antidiagonal` and `matrix.is_triangular` instead follow their
official fixed `series bool` return qualifiers for namespace and method-call
forms: results are accepted by series-bool conditions and rejected by
simple-bool consumers.
`matrix.row` and `matrix.col` have fixture-backed `MatrixArray` return
qualifier semantics for namespace and method-call forms: returned arrays
preserve the source matrix element kind as `simple array<T>` for
float/int/bool/string/color matrices and are accepted or rejected by exact
matrix element-array consumers accordingly.
`matrix.concat`, `matrix.copy`, `matrix.transpose`, and `matrix.submatrix` have fixture-backed
`SameAsArg` simple-matrix return qualifier semantics for namespace and
method-call forms: returned matrices preserve the source matrix element kind for
float/int/bool/string/color matrices and are accepted or rejected by matrix
element-compatible consumers accordingly; `matrix.concat` returns the same
mutated first-matrix id while the other helpers return independent matrices.
`matrix.get` has fixture-backed `MatrixElement` return qualifier semantics for
namespace and method-call forms: float/int/bool/string/color element results
are returned as series values accepted by matching series-compatible consumers
and rejected by stricter const/input or simple consumers.
`matrix.median` also has fixture-backed official element-kind-preserving
`MatrixElement` return semantics for namespace and method-call forms over
numeric matrices: `matrix<int>` results are `series int`, while `matrix<float>`
results are `series float`, and both are rejected by const/input consumers.
`matrix.sum`, `matrix.avg`, `matrix.min`, `matrix.max`, `matrix.mode`,
`matrix.trace`, and `matrix.det` have fixture-backed fixed `series float`
return semantics for namespace and method-call forms over int/float matrices,
while `matrix.rank` has fixture-backed fixed `series int` return semantics;
results are accepted by series numeric consumers and rejected by const/input
numeric or int consumers.
`matrix.new<float>`, `matrix.new<int>`, `matrix.new<bool>`,
`matrix.new<string>`, and `matrix.new<color>` have fixture-backed fixed
`simple matrix<T>` return semantics: constructed matrices are accepted by
matching element-compatible namespace and method-call consumers and rejected by
mismatched `matrix.fill` value consumers.
`matrix.eigenvalues` has fixture-backed fixed `simple array<float>` return
semantics, while `matrix.eigenvectors`, `matrix.kron`, `matrix.diff`,
`matrix.pow`, `matrix.inv`, and `matrix.pinv` have fixture-backed fixed
`simple matrix<float>` return semantics for int/float numeric matrices in
namespace and method-call forms; results are accepted by float collection
consumers and rejected by stricter int/string-mismatched consumers.
`matrix.mult` has fixture-backed `MatrixMult` return semantics for namespace
and method-call forms: int/float numeric matrix-by-matrix and matrix/scalar
combinations return `simple matrix<float>`, while int/float matrix/array
combinations return `simple array<float>`, with both shapes accepted by float
collection consumers and rejected by stricter int/string-mismatched consumers.
Multi-argument `PromotedFloat` math helpers now include `math.avg`,
`math.pow`, and `math.hypot` fixture coverage, preserving input qualifiers for
const/input numeric consumers and preserving simple qualifiers for rejection.
Generic input defval, tuple options, and plot/hline fill
source acceptors now also use the helper, so fixture-backed `input`,
`input.int`, and `fill` diagnostics report the expected argument family.
Dynamic `Exact(PineType)` and kind-only acceptors also use the helper, so
fixture-backed `input.int` exact const-int metadata diagnostics and
helper-covered future kind-only diagnostics report explicit expected types. UDT
array chained field mutation indexes now report the same simple-int expectation
as normal `array.get` indexes, including `series int` rejection.
Matrix element and row/column array cross-parameter acceptors now derive
expected labels from the counterpart matrix argument, so fixture-backed
`matrix.fill`/`matrix.set` value diagnostics for numeric/bool/string/color/int
matrices and `matrix.add_row`/`matrix.add_col` array diagnostics report the
expected element or array family instead of only the rejected actual type.
Matrix pair acceptors used by `matrix.kron`, `matrix.diff`, and `matrix.mult`
also derive labels from the counterpart argument, distinguishing strict
numeric-matrix pairs from the wider `matrix.diff`/`matrix.mult`
matrix-plus-scalar/vector case, while scalar/scalar or vector/vector pairs
still require at least one side to be a numeric matrix. Matrix row/column and
shape parameters for reads, writes, removes, and reshape now have
fixture-backed simple-int diagnostics for namespace and method syntax; the same
coverage now extends to swap, sort, and submatrix index parameters, with
`matrix.sort` order fixtures locking const-string expectations. Unary numeric/bool
and binary numeric/bool operator type diagnostics now also report the expected
operand family with the actual operand type, and relational comparisons now
require numeric operands instead of accepting every value kind. Equality and
inequality comparisons now reject incomparable cross-kind operands while still
sharing the common kind rules used by conditional merges, including same-kind,
numeric int/float, and `na` comparisons. Ternary and switch branch type
mismatch diagnostics also use canonical Pine type names for incompatible branch
kinds. Scalar reassignment and scalar UDT
field mutation type diagnostics use the same canonical type names for assigned
and target values, and local/imported UDT constructor field diagnostics now use
the same canonical type names instead of Rust enum names. User-method parameter
mismatch diagnostics also use canonical Pine type names for expected parameter
types. Expression-context branch and loop diagnostics now consistently describe
side-effect-only or loop-control endings as requiring a value-producing
expression. Control-flow
qualifier promotion fixtures for final loop
returns, final-if branch loop returns, method switch block loop returns,
branch/body loop-expression results, and UDF or user-method final
`for`/`for...in`/`while` returns now also lock the resulting `SimpleInt`
rejection message, so these paths prove both the series promotion and the
user-facing expected/got diagnostic. Imported exported-UDF final
`for`/`for...in`/`while` returns, including `switch` block-arm final loop
returns, are also covered through simple-compatible `ta.sma` length callsites.
Remaining qualifier work is not a blocker for Phase C history support:

1. Keep the shared qualifier-bound argument helpers covered as more built-in
   signatures move from bespoke acceptors to "at most input" or "at most
   simple" semantics.
2. Keep `docs/BUILTIN_SIGNATURES.md` aligned with code acceptors as new
   built-ins are added, because most built-in length parameters still rely on
   `SimpleInt` semantics while dedicated dynamic-history/state parameters such
   as `math.sum`, `ta.sma`, `ta.change`/`ta.mom`/`ta.roc` length,
   `ta.valuewhen` occurrence, and pivot left/right bars use `IntCompatible`.
3. Revisit scalar `simple` inference if later built-ins require stricter Pine
   qualifier behavior than the current subset.
