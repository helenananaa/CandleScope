# Built-In Signatures

This document defines the first built-in surface as typed signatures. It is a
contract for semantic analysis and runtime implementation.

The syntax below is descriptive, not final Rust API syntax:

```text
name(arg_name: qualifier kind, ...) -> qualifier kind
```

`series<T>` means a series-qualified value of kind `T`.

## Phase C Qualifier Audit Notes

These signatures describe the currently implemented semantic surface, not the
full Pine surface. In this document:

- `series/simple numeric` means numeric values at any implemented qualifier up
  to `series`, including `const` and `input`.
- `simple int` means `const`, `input`, or `simple` integers, and rejects
  `series int`.
- `const` parameters require literal/named-constant style values after current
  semantic analysis.
- History offsets accept non-negative integer literals plus integer expressions
  at any implemented qualifier, including `series int`; non-integer offsets are
  rejected.

In code, exact and at-most scalar qualifier bounds share the
`QualifierBoundScalar` model. The established `Accepts::Simple*`,
`Accepts::Const*`, and `Accepts::AtMostInput*` names are retained as associated
constants over that model, so signature tables remain readable while type
acceptance and diagnostics use one rule path.

### Static Scalar Call Evaluation

The analyzer has a deliberately narrow shared evaluator for constant scalar
calls. Its complete current whitelist is:

```text
int(value)
float(value)
math.min(number, ...)
math.max(number, ...)
math.abs(number)
math.floor(number)
math.ceil(number)
math.trunc(number)
```

When every argument is a supported known scalar value and the evaluator returns
a known result, these calls may participate in static ternary/if/switch
selection, declaration-value validation, constant history-offset rejection or
lowering, and declaration/per-series `max_bars_back` inference. Cast-wrapped and
nested whitelisted calls use the same evaluator. A finite `int(float)` cast
matches the runtime's truncating, saturating conversion to `i64`; declaration
and history-bound range checks then reject values outside their narrower
non-negative/u32 domains. All-integer `math.min` and `math.max` preserve exact
`i64` precision in both analysis and execution. The `math.abs(i64::MIN)` runtime
float fallback remains a known out-of-range result for bounded integer
validation rather than being treated as unknown. By contrast, `math.floor`,
`math.ceil`, and `math.trunc` float results outside `i64` remain conservatively
unknown. `na`, non-finite, wrong-kind, and wrong-arity results are also not
treated as known constant values.

This is not a claim that every runtime-pure built-in is constant-foldable.
Calls outside this explicit whitelist keep their existing analyzer/runtime
behavior.

## Phase 1 Core

Phase 1 should be intentionally small:

- OHLCV and derived built-in series
- `indicator`
- `input`, `input.int`, `input.float`, `input.bool`, `input.source`,
  `input.color`, `input.string`, `input.price`, `input.time`, `input.symbol`,
  `input.timeframe`, `input.session`, `input.text_area`
- `plot`
- `hline`
- `fill`
- `na`
- `nz`
- `ta.sma`
- `ta.ema`

Other built-ins may be parsed and reported as unsupported until this set is
stable.

## Global Series

```text
open      -> series float
high      -> series float
low       -> series float
close     -> series float
volume    -> series float
time      -> series int
time_close -> series int
time_tradingday -> series int
last_bar_index -> series int
last_bar_time -> series int
year      -> series int
month     -> series int
weekofyear -> series int
dayofmonth -> series int
dayofweek -> series int
hour      -> series int
minute    -> series int
second    -> series int
hl2       -> series float
hlc3      -> series float
hlcc4     -> series float
ohlc4     -> series float
bar_index -> series int
timeframe.period -> simple string
timeframe.main_period -> simple string
timeframe.isticks -> simple bool
timeframe.isseconds -> simple bool
timeframe.isminutes -> simple bool
timeframe.isintraday -> simple bool
timeframe.isdaily -> simple bool
timeframe.isweekly -> simple bool
timeframe.ismonthly -> simple bool
timeframe.isdwm -> simple bool
timeframe.multiplier -> simple int
chart.left_visible_bar_time -> simple int
chart.right_visible_bar_time -> simple int
chart.bg_color -> simple color
chart.fg_color -> simple color
chart.is_standard -> simple bool
chart.is_heikinashi -> simple bool
chart.is_kagi -> simple bool
chart.is_linebreak -> simple bool
chart.is_pnf -> simple bool
chart.is_range -> simple bool
chart.is_renko -> simple bool
chart.point.new(time: int-compatible, index: int-compatible, price: numeric-compatible) -> series chart.point
chart.point.now(price: numeric-compatible) -> series chart.point
chart.point.from_index(index: int-compatible, price: numeric-compatible) -> series chart.point
chart.point.from_time(time: int-compatible, price: numeric-compatible) -> series chart.point
chart.point.copy(id: chart.point-compatible) -> series chart.point
label.new(x: int-compatible, y: numeric-compatible, text?: string-compatible, xloc?: const string, yloc?: const string, color?: color-compatible, style?: const string, textcolor?: color-compatible, size?: string-or-int-compatible, textalign?: const string, tooltip?: string-compatible, text_font_family?: const string, force_overlay?: const bool, text_formatting?: int-compatible) -> series label
label.new(point: chart.point-compatible, text?: string-compatible, xloc?: const string, yloc?: const string, color?: color-compatible, style?: const string, textcolor?: color-compatible, size?: string-or-int-compatible, textalign?: const string, tooltip?: string-compatible, text_font_family?: const string, force_overlay?: const bool, text_formatting?: int-compatible) -> series label
label.set_x(id: label-compatible, x: int-compatible) -> void
label.set_xloc(id: label-compatible, x: int-compatible, xloc: const string) -> void
label.set_y(id: label-compatible, y: numeric-compatible) -> void
label.set_xy(id: label-compatible, x: int-compatible, y: numeric-compatible) -> void
label.set_point(id: label-compatible, point: chart.point-compatible) -> void
label.set_yloc(id: label-compatible, yloc: const string) -> void
label.set_text(id: label-compatible, text: string-compatible) -> void
label.set_color(id: label-compatible, color: color-compatible) -> void
label.set_textcolor(id: label-compatible, textcolor: color-compatible) -> void
label.set_style(id: label-compatible, style: const string) -> void
label.set_size(id: label-compatible, size: string-or-int-compatible) -> void
label.set_tooltip(id: label-compatible, tooltip: string-compatible) -> void
label.set_textalign(id: label-compatible, textalign: const string) -> void
label.set_text_font_family(id: label-compatible, text_font_family: const string) -> void
label.set_text_formatting(id: label-compatible, text_formatting: int-compatible) -> void
label.delete(id: label-compatible) -> void
label.copy(id: label-compatible) -> series label
label.get_x(id: label-compatible) -> series int
label.get_y(id: label-compatible) -> series float
label.get_text(id: label-compatible) -> series string
label.all -> simple array<label>
line.new(x1: int-compatible, y1: numeric-compatible, x2: int-compatible, y2: numeric-compatible, xloc?: const string, extend?: const string, color?: color-compatible, style?: const string, width?: int-compatible, force_overlay?: const bool) -> series line
line.new(first_point: chart.point-compatible, second_point: chart.point-compatible, xloc?: const string, extend?: const string, color?: color-compatible, style?: const string, width?: int-compatible, force_overlay?: const bool) -> series line
line.set_x1(id: line-compatible, x: int-compatible) -> void
line.set_first_point(id: line-compatible, point: chart.point-compatible) -> void
line.set_y1(id: line-compatible, y: numeric-compatible) -> void
line.set_xy1(id: line-compatible, x: int-compatible, y: numeric-compatible) -> void
line.set_x2(id: line-compatible, x: int-compatible) -> void
line.set_second_point(id: line-compatible, point: chart.point-compatible) -> void
line.set_y2(id: line-compatible, y: numeric-compatible) -> void
line.set_xy2(id: line-compatible, x: int-compatible, y: numeric-compatible) -> void
line.set_xloc(id: line-compatible, x1: int-compatible, x2: int-compatible, xloc: const string) -> void
line.set_color(id: line-compatible, color: color-compatible) -> void
line.set_width(id: line-compatible, width: int-compatible) -> void
line.set_style(id: line-compatible, style: const string) -> void
line.set_extend(id: line-compatible, extend: const string) -> void
line.delete(id: line-compatible) -> void
line.copy(id: line-compatible) -> series line
line.get_price(id: line-compatible, x: int-compatible) -> series float
line.get_x1(id: line-compatible) -> series int
line.get_y1(id: line-compatible) -> series float
line.get_x2(id: line-compatible) -> series int
line.get_y2(id: line-compatible) -> series float
line.all -> simple array<line>
linefill.new(line1: line-compatible, line2: line-compatible, color: color-compatible) -> series linefill
linefill.set_color(id: linefill-compatible, color: color-compatible) -> void
linefill.get_line1(id: linefill-compatible) -> series line
linefill.get_line2(id: linefill-compatible) -> series line
linefill.delete(id: linefill-compatible) -> void
linefill.all -> simple array<linefill>
box.new(left: int-compatible, top: numeric-compatible, right: int-compatible, bottom: numeric-compatible, border_color?: color-compatible, border_width?: int-compatible, border_style?: const string, extend?: const string, xloc?: const string, bgcolor?: color-compatible, text?: string-compatible, text_size?: string-or-int-compatible, text_color?: color-compatible, text_halign?: const string, text_valign?: const string, text_wrap?: const string, text_font_family?: const string, force_overlay?: const bool, text_formatting?: int-compatible) -> series box
box.new(top_left: chart.point-compatible, bottom_right: chart.point-compatible, border_color?: color-compatible, border_width?: int-compatible, border_style?: const string, extend?: const string, xloc?: const string, bgcolor?: color-compatible, text?: string-compatible, text_size?: string-or-int-compatible, text_color?: color-compatible, text_halign?: const string, text_valign?: const string, text_wrap?: const string, text_font_family?: const string, force_overlay?: const bool, text_formatting?: int-compatible) -> series box
box.set_left(id: box-compatible, x: int-compatible) -> void
box.set_top(id: box-compatible, y: numeric-compatible) -> void
box.set_right(id: box-compatible, x: int-compatible) -> void
box.set_bottom(id: box-compatible, y: numeric-compatible) -> void
box.set_lefttop(id: box-compatible, x: int-compatible, y: numeric-compatible) -> void
box.set_top_left_point(id: box-compatible, point: chart.point-compatible) -> void
box.set_rightbottom(id: box-compatible, x: int-compatible, y: numeric-compatible) -> void
box.set_bottom_right_point(id: box-compatible, point: chart.point-compatible) -> void
box.set_bgcolor(id: box-compatible, color: color-compatible) -> void
box.set_border_color(id: box-compatible, color: color-compatible) -> void
box.set_border_width(id: box-compatible, width: int-compatible) -> void
box.set_border_style(id: box-compatible, style: const string) -> void
box.set_extend(id: box-compatible, extend: const string) -> void
box.set_xloc(id: box-compatible, left: int-compatible, right: int-compatible, xloc: const string) -> void
box.set_text(id: box-compatible, text: string-compatible) -> void
box.set_text_color(id: box-compatible, text_color: color-compatible) -> void
box.set_text_size(id: box-compatible, text_size: string-or-int-compatible) -> void
box.set_text_halign(id: box-compatible, text_halign: const string) -> void
box.set_text_valign(id: box-compatible, text_valign: const string) -> void
box.set_text_wrap(id: box-compatible, text_wrap: const string) -> void
box.set_text_font_family(id: box-compatible, text_font_family: const string) -> void
box.set_text_formatting(id: box-compatible, text_formatting: int-compatible) -> void
box.delete(id: box-compatible) -> void
box.copy(id: box-compatible) -> series box
box.get_top(id: box-compatible) -> series float
box.get_bottom(id: box-compatible) -> series float
box.get_left(id: box-compatible) -> series int
box.get_right(id: box-compatible) -> series int
box.all -> simple array<box>
table.new(position: const string, columns: int-compatible, rows: int-compatible, bgcolor?: color-compatible, frame_color?: color-compatible, frame_width?: int-compatible, border_color?: color-compatible, border_width?: int-compatible) -> series table
table.delete(id: table-compatible) -> void
table.clear(id: table-compatible, start_column: int-compatible, start_row: int-compatible, end_column: int-compatible, end_row: int-compatible) -> void
table.merge_cells(id: table-compatible, start_column: int-compatible, start_row: int-compatible, end_column: int-compatible, end_row: int-compatible) -> void
table.cell(id: table-compatible, column: int-compatible, row: int-compatible, text: string-compatible, width?: numeric-compatible, height?: numeric-compatible, text_color?: color-compatible, text_halign?: const string, text_valign?: const string, text_size?: string-or-int-compatible, bgcolor?: color-compatible, tooltip?: string-compatible, text_font_family?: const string, text_formatting?: int-compatible) -> void
table.set_position(id: table-compatible, position: const string) -> void
table.set_bgcolor(id: table-compatible, bgcolor: color-compatible) -> void
table.set_frame_color(id: table-compatible, frame_color: color-compatible) -> void
table.set_frame_width(id: table-compatible, frame_width: int-compatible) -> void
table.set_border_color(id: table-compatible, border_color: color-compatible) -> void
table.set_border_width(id: table-compatible, border_width: int-compatible) -> void
table.cell_set_text(id: table-compatible, column: int-compatible, row: int-compatible, text: string-compatible) -> void
table.cell_set_bgcolor(id: table-compatible, column: int-compatible, row: int-compatible, bgcolor: color-compatible) -> void
table.cell_set_text_color(id: table-compatible, column: int-compatible, row: int-compatible, text_color: color-compatible) -> void
table.cell_set_width(id: table-compatible, column: int-compatible, row: int-compatible, width: numeric-compatible) -> void
table.cell_set_height(id: table-compatible, column: int-compatible, row: int-compatible, height: numeric-compatible) -> void
table.cell_set_text_size(id: table-compatible, column: int-compatible, row: int-compatible, text_size: string-or-int-compatible) -> void
table.cell_set_text_halign(id: table-compatible, column: int-compatible, row: int-compatible, text_halign: const string) -> void
table.cell_set_text_valign(id: table-compatible, column: int-compatible, row: int-compatible, text_valign: const string) -> void
table.cell_set_text_wrap(id: table-compatible, column: int-compatible, row: int-compatible, text_wrap: const string) -> void
table.cell_set_tooltip(id: table-compatible, column: int-compatible, row: int-compatible, tooltip: string-compatible) -> void
table.cell_set_text_font_family(id: table-compatible, column: int-compatible, row: int-compatible, text_font_family: const string) -> void
table.cell_set_text_formatting(id: table-compatible, column: int-compatible, row: int-compatible, text_formatting: int-compatible) -> void
table.all -> simple array<table>
polyline.new(points: simple array<chart.point>, curved?: bool-compatible, closed?: bool-compatible, xloc?: const string, line_color?: color-compatible, fill_color?: color-compatible, line_style?: const string, line_width?: int-compatible, force_overlay?: const bool) -> series polyline
polyline.delete(id: polyline-compatible) -> void
polyline.all -> simple array<polyline>
```

`year`, `month`, `weekofyear`, `dayofmonth`, `dayofweek`, `hour`, `minute`,
and `second` currently expose UTC calendar components derived from each bar's
`time`. Full exchange-timezone calendar semantics are not claimed until symbol
timezone metadata exists. `dayofweek.sunday` through `dayofweek.saturday`
evaluate to const ints `1` through `7`; `weekofyear` uses the UTC ISO week
number in the current subset. `time_close` uses the fixed default 1-minute
chart timeframe and returns `time + 60000`.
`time_tradingday` currently implements the fixed UTC single-day session subset:
it returns 00:00 UTC for the current bar's UTC calendar day. Overnight sessions
whose trading day differs from the bar opening date remain outside this subset.

`last_bar_index` and `last_bar_time` reference the last known loaded chart bar
in the current dataset. `last_bar_index` is the zero-based index of that bar,
and `last_bar_time` is that bar's opening timestamp. Host-owned realtime script
restart/repaint behavior beyond the loaded runtime dataset is not expanded by
this subset.

The current chart metadata subset assumes a standard bars/candles-style chart
with a fixed full-dataset viewport and a fixed light appearance:
`chart.left_visible_bar_time` is the first loaded bar opening time and
`chart.right_visible_bar_time` is the last known loaded bar opening time.
`chart.bg_color` is opaque white and `chart.fg_color` is opaque black.
`chart.is_standard` is `true`, while `chart.is_heikinashi`, `chart.is_kagi`,
`chart.is_linebreak`, `chart.is_pnf`, `chart.is_range`, and `chart.is_renko`
are `false`. Host-owned scroll/zoom viewport changes and configurable chart
appearance are not implemented by this fixed chart metadata subset.
`chart.point` supports fixture-backed construction through `new`, `now`,
`from_index`, `from_time`, and `copy`, plus top-level `time`, `index`, and
`price` field reads/mutation. `line.new`, `line.set_first_point`,
`line.set_second_point`, `box.new`, `box.set_top_left_point`,
`box.set_bottom_right_point`, `label.new`, and `label.set_point` can consume
`chart.point` values, and point arrays can feed the partial `polyline.new`
snapshot subset. `polyline.delete`, `polyline.all`, and declaration-driven
polyline max-count eviction cover the historical and forming-bar rollback
lifecycle subset. `chart.point` typed declarations are fixture-backed for
chart-point or `na` initializers. Polyline id arrays are fixture-backed through
`array.new_polyline`, official `array.new<polyline>` template syntax,
`array.from(polyline, ...)`, typed declarations, generic object-array helpers,
and array/slice history snapshots.

Bar state:

```text
barstate.isfirst -> series bool
barstate.islast -> series bool
barstate.islastconfirmedhistory -> series bool
barstate.isnew -> series bool
barstate.isconfirmed -> series bool
barstate.ishistory -> series bool
barstate.isrealtime -> series bool
```

`barstate.isfirst` is `true` only when `bar_index == 0`.
`barstate.islast` is `true` on the last known bar in finite historical batch
execution and on current realtime updates. Open-ended `append_bar` historical
updates treat the appended bar as the latest known bar.
`barstate.islastconfirmedhistory` is `true` on the last known confirmed
historical bar in finite historical batch execution. Open-ended `append_bar`
historical updates treat the appended historical bar as the current last
confirmed historical bar. Forming and confirmed realtime updates return
`false`; host-owned market-open repaint behavior that would mark the bar
immediately preceding a realtime bar is not expanded by this subset.
`barstate.isnew` is `true` for historical bars and for the first realtime
update of a new bar. Subsequent forming updates for the same realtime bar and
the confirming update after a forming update return `false`.
`barstate.isconfirmed` is `true` for historical and confirmed updates, and
`false` for forming realtime updates.
`barstate.ishistory` is `true` for historical updates. `barstate.isrealtime`
is `true` for forming and confirmed realtime updates.

Session state:

```text
session.ismarket -> series bool
session.ispremarket -> series bool
session.ispostmarket -> series bool
session.isfirstbar -> series bool
session.islastbar -> series bool
session.isfirstbar_regular -> series bool
session.islastbar_regular -> series bool
session.regular -> const string
session.extended -> const string
adjustment.none -> const string
adjustment.splits -> const string
adjustment.dividends -> const string
settlement_as_close.on -> const string
settlement_as_close.off -> const string
settlement_as_close.inherit -> const string
backadjustment.on -> const string
backadjustment.off -> const string
backadjustment.inherit -> const string
```

The current subset assumes every runtime bar is in the regular session:
`session.ismarket` is `true`, while `session.ispremarket` and
`session.ispostmarket` are `false`. `session.isfirstbar` is `true` only on the
first runtime bar, while `session.islastbar` follows the runtime's latest known
bar policy used by `barstate.islast`: the last bar in a finite historical batch
and current realtime updates are `true`. Because this subset has only regular
session bars, `session.isfirstbar_regular` and `session.islastbar_regular`
match the non-regular-specific boundary variables. `session.regular` is the
`"regular"` string constant and `session.extended` is the `"extended"` string
constant; exchange calendars, separate session days, and extended-hours data are
not implemented by these constants.
`adjustment.none`, `adjustment.splits`, and `adjustment.dividends` are direct
string constants used by the current modified ticker ID subset. They do not
perform price adjustment unless a host request provider interprets the modified
ticker ID.
`settlement_as_close.on/off/inherit` and `backadjustment.on/off/inherit` are
direct string constants used by the current modified ticker ID subset. They
record futures-specific ticker modifiers for host request providers; they do
not perform settlement-as-close or back-adjusted data transformations on their
own.

Symbol info:

```text
syminfo.tickerid -> const string
syminfo.main_tickerid -> const string
syminfo.ticker -> const string
syminfo.prefix -> const string
syminfo.description -> const string
syminfo.sector -> const string
syminfo.industry -> const string
syminfo.country -> const string
syminfo.type -> const string
syminfo.currency -> const string
syminfo.basecurrency -> const string
syminfo.session -> const string
syminfo.timezone -> const string
syminfo.root -> const string
syminfo.volumetype -> const string
syminfo.mintick -> const float
syminfo.mincontract -> const float
syminfo.pointvalue -> const float
syminfo.minmove -> const int
syminfo.pricescale -> const int
syminfo.prefix(symbol: simple string) -> simple string
syminfo.ticker(symbol: simple string) -> simple string
ticker.heikinashi(tickerid: simple string) -> simple string
ticker.inherit(from_tickerid: simple string, symbol: simple string) -> simple string
ticker.kagi(tickerid: simple string, style: simple string, param: simple numeric-compatible) -> simple string
ticker.linebreak(tickerid: simple string, number_of_lines: simple integer-compatible) -> simple string
ticker.new(prefix: simple string, ticker: simple string, session?: simple string, adjustment?: simple string, settlement_as_close?: simple string, backadjustment?: simple string) -> simple string
ticker.modify(tickerid: simple string, session?: simple string, adjustment?: simple string, settlement_as_close?: simple string, backadjustment?: simple string) -> simple string
ticker.pointfigure(tickerid: simple string, source: simple string, style: simple string, param: simple numeric-compatible, reversal: simple integer-compatible) -> simple string
ticker.renko(tickerid: simple string, style: simple string, param: simple numeric-compatible) -> simple string
ticker.standard(symbol: simple string) -> simple string
```

`syminfo.*` currently uses fixed default symbol metadata until runtime symbol
metadata is available: `tickerid = main_tickerid = NASDAQ:AAPL`, ticker `AAPL`,
prefix `NASDAQ`, stock type, `Electronic Technology` sector,
`Telecommunications Equipment` industry, `US` country, `USD` currency/base
currency, `regular` session, `Etc/UTC` timezone, `base` volume type,
`mintick = 0.01`, `mincontract = 1.0`, `pointvalue = 1.0`, `minmove = 1`, and
`pricescale = 100`.
`syminfo.prefix(symbol)` and `syminfo.ticker(symbol)` parse the supplied simple
string directly. They split `PREFIX:TICKER` on the first `:`; symbols without a
prefix return `""` from `syminfo.prefix()` and the whole symbol from
`syminfo.ticker()`.

`ticker.heikinashi(tickerid)` currently implements the simple-string Heikin
Ashi ticker ID constructor subset. It returns a modified ticker ID that
preserves the standard symbol for `ticker.standard()`. Actual Heikin Ashi OHLC
data remains host/request-provider-owned through `request.security()`.

`ticker.inherit(from_tickerid, symbol)` currently implements a simple-string
inheritance subset over this runtime's known modified ticker ID representation.
When `from_tickerid` contains a quoted `"symbol"` field produced by supported
`ticker.*` constructors, it returns the same ticker ID shape with that field
replaced by `symbol`. Plain standard ticker IDs have no modifiers to inherit and
return `symbol` unchanged. Other TradingView ticker ID modifier encodings remain
outside this subset.

`ticker.kagi(tickerid, style, param)` currently implements the simple-string
Kagi ticker ID constructor subset for style strings such as `"ATR"` or
`"Traditional"` and simple numeric-compatible parameters. Explicit `na` param
propagates `na`. It returns a modified ticker ID that preserves the standard
symbol for `ticker.standard()`. Actual Kagi OHLC data remains
host/request-provider-owned through `request.security()`.

`ticker.linebreak(tickerid, number_of_lines)` currently implements the
simple-string Line Break ticker ID constructor subset with a simple
integer-compatible line count. Explicit `na` line count propagates `na`. It
returns a modified ticker ID that preserves the standard symbol for
`ticker.standard()`. Actual Line Break OHLC data remains host/request-provider-
owned through `request.security()`.

`ticker.new(prefix, ticker)` currently implements the default ticker constructor
subset and returns `PREFIX:TICKER`. Supplying the optional `session` and
`adjustment` arguments with values such as `session.regular`,
`session.extended`, `syminfo.session`, `adjustment.none`, `adjustment.splits`,
`adjustment.dividends`, `settlement_as_close.on/off/inherit`, and
`backadjustment.on/off/inherit` returns a modified ticker ID that preserves the
standard symbol for `ticker.standard()`. Host request semantics for adjusted,
settlement-as-close, and back-adjusted data remain outside this subset.

`ticker.modify(tickerid)` currently implements the no-modifier identity subset
and returns the supplied ticker ID. Supplying the optional `session` and
`adjustment` arguments with values such as `session.regular`,
`session.extended`, `syminfo.session`, `adjustment.none`, `adjustment.splits`,
`adjustment.dividends`, `settlement_as_close.on/off/inherit`, and
`backadjustment.on/off/inherit` returns a modified ticker ID that preserves the
standard symbol for `ticker.standard()`. Host request semantics for adjusted,
settlement-as-close, and back-adjusted data remain outside this subset.

`ticker.pointfigure(tickerid, source, style, param, reversal)` currently
implements the simple-string Point & Figure ticker ID constructor subset for
source strings such as `"hl"` or `"close"`, style strings such as `"ATR"` or
`"Traditional"`, simple numeric-compatible parameters, and simple
integer-compatible reversal amounts. Explicit `na` param or reversal propagates
`na`. It returns a modified ticker ID that preserves the standard symbol for
`ticker.standard()`. Actual Point & Figure OHLC data remains
host/request-provider-owned through `request.security()`.

`ticker.renko(tickerid, style, param)` currently implements the simple-string
Renko ticker ID constructor subset for style strings such as `"ATR"` or
`"Traditional"` and simple numeric-compatible parameters. Explicit `na` param
propagates `na`. It returns a modified ticker ID that preserves the standard
symbol for `ticker.standard()`. Actual Renko OHLC data remains
host/request-provider-owned through `request.security()`.

`ticker.standard(symbol)` currently implements the simple-string standard ticker
ID subset. Plain `PREFIX:TICKER` values are returned unchanged, and known
TradingView ticker-id strings containing a quoted `"symbol"` field return that
field's value. Other modifier encodings and ticker constructors remain outside
this subset.

The same names are also supported as functions over a timestamp:

```text
year(time: int-compatible, timezone?: string-compatible) -> int with strongest qualifier
month(time: int-compatible, timezone?: string-compatible) -> int with strongest qualifier
weekofyear(time: int-compatible, timezone?: string-compatible) -> int with strongest qualifier
dayofmonth(time: int-compatible, timezone?: string-compatible) -> int with strongest qualifier
dayofweek(time: int-compatible, timezone?: string-compatible) -> int with strongest qualifier
hour(time: int-compatible, timezone?: string-compatible) -> int with strongest qualifier
minute(time: int-compatible, timezone?: string-compatible) -> int with strongest qualifier
second(time: int-compatible, timezone?: string-compatible) -> int with strongest qualifier
timestamp(timezone?: string-compatible, year: int-compatible, month: int-compatible, day: int-compatible, hour?: int-compatible, minute?: int-compatible, second?: int-compatible)
  -> int with strongest qualifier
timestamp(dateString: const string) -> const int
time(timeframe: simple string, session?: string-compatible, timezone?: string-compatible, bars_back?: int-compatible, timeframe_bars_back?: int-compatible) -> series int
time_close(timeframe: simple string, session?: string-compatible, timezone?: string-compatible, bars_back?: int-compatible, timeframe_bars_back?: int-compatible) -> series int
```

Calendar component functions and `str.format_time` support UTC/GMT/numeric
fixed-offset and IANA `timezone` arguments, resolving IANA offsets at the
supplied absolute timestamp so DST transitions affect returned local values.
`time` and `time_close` also accept IANA zones for explicit time-based session
interpretation and session-end clipping. Unsupported time zones are runtime
errors. The component variables still use the runtime's UTC bar-time view while
exchange timezone defaults remain unsupported. `timestamp` currently supports numeric calendar arguments with an
optional UTC/GMT/numeric fixed-offset or IANA `timezone` argument, including
named calendar parameters and normalized
zero/negative/overflow `month`, `day`, `hour`, `minute`, and `second` offsets.
IANA overlaps select the earlier absolute instant, and nonexistent local times
shift forward by the zone's offset jump while preserving minute and second.
Omitted hour/minute/second default to 0, `na` inputs return `na`, and timestamp
values outside the UTC datetime range are runtime errors. The
`timestamp(dateString)` overload accepts const strings
for ISO dates such as `"2021-01-01"`, English month dates such as
`"29 Aug 2024"`, optional `HH:mm` or `HH:mm:ss` time-of-day tokens, and
optional `UTC`/`GMT`/fixed-offset or IANA timezone tokens such as `"UTC+0"`,
`"-0400"`, or `"America/New_York"`; omitted time-of-day and timezone default
to midnight UTC. IANA overlaps and nonexistent local times use the same
resolution policy as numeric-calendar calls. Broader date-string parsing and
exchange-timezone default semantics remain unsupported.
`time(timeframe, session, timezone, bars_back, timeframe_bars_back)` and
`time_close(timeframe, session, timezone, bars_back, timeframe_bars_back)`
currently implement the simple-string timeframe subset with optional
time-based session strings, UTC/GMT/numeric fixed-offset or IANA timezone strings,
int-compatible `bars_back`, and int-compatible `timeframe_bars_back` offsets.
`""` and
`timeframe.period` use the current fixed chart timeframe and return the current
bar's existing `time` or `time_close` value when no session is supplied and both
offsets are omitted or 0. For nonzero `bars_back`, the runtime offsets from the
current bar using the fixed 1-minute chart timeframe before mapping to the
requested UTC timeframe bucket. It then applies `timeframe_bars_back` on that
requested timeframe bucket. Supported seconds, minutes, and days return fixed-
duration UTC bucket boundaries; weeks return Monday-based UTC calendar-week
group boundaries, and months return UTC calendar-month group boundaries.
Negative `bars_back` and `timeframe_bars_back` values can reference at most 500
future bars in their respective offset spaces. The session subset accepts
`24x7`, `HHmm-HHmm`,
comma-separated intraday periods, optional Pine day digits, and fixed-offset
or IANA timezone interpretation for those session strings. Overnight periods
are supported. `time_close` clips the returned close timestamp to the matching
session period end; IANA offsets follow DST at the bar and close instants,
repeated close times choose the later instant, and nonexistent close times
advance to the first valid local minute. Exchange timezone defaults and
named-session data remain unsupported.

Timeframe helpers:

```text
timeframe.in_seconds(timeframe?: simple string) -> simple int
timeframe.from_seconds(seconds: simple int|na) -> simple string
timeframe.change(timeframe: simple string) -> series bool
```

The current subset assumes a fixed default chart timeframe of `1` minute, so
`timeframe.period` and `timeframe.main_period` return `"1"`,
`timeframe.multiplier` returns `1`,
`timeframe.isminutes` and `timeframe.isintraday` return `true`, and
`timeframe.isticks`, `timeframe.isseconds`, `timeframe.isdaily`,
`timeframe.isweekly`, `timeframe.ismonthly`, and `timeframe.isdwm` return
`false`.

`timeframe.main_period` currently matches the single chart timeframe. Main
timeframe overrides from declaration parameters and requested-context
differences remain outside this subset.

Request helpers:

```text
request.security(symbol: simple string, timeframe: simple string, expression: any, gaps?: const string, lookahead?: const string)
  -> series type matching expression
```

The current executable subset has two forms:

- `request.security(syminfo.tickerid, timeframe.period, expression)` evaluates a
  scalar side-effect-free expression in the chart context. Same-context tuple
  literals whose elements are side-effect-free expressions are supported when
  destructured directly from the request. Selected same-context tuple-returning
  calls are also supported when destructured directly, currently including
  `ta.macd`, `ta.bb`, `ta.kc`, `ta.supertrend`, `ta.dmi`, and
  `ta.vwap(source, anchor, stdev_mult)`.
- `request.security("SYMBOL", timeframe, expression)` and
  `request.security(syminfo.tickerid, timeframe, expression)` evaluate
  side-effect-free expressions over host-provided same-or-higher-timeframe bars.
  The supported provider expression subset includes direct OHLCV/time sources,
  pure arithmetic and ternaries, history references, `na`, `nz`, selected
  stateless `math.*` calls, fixed-mintick `math.round_to_mintick`, `math.sum`,
  `ta.cum`, `ta.sma`, `ta.ema`, `ta.dema`, `ta.tema`, `ta.rma`, `ta.rsi`,
  `ta.accdist`, `ta.iii`, `ta.nvi`, `ta.obv`, `ta.pvi`, `ta.pvt`, `ta.wvad`, `ta.tsi`, `ta.cmo`, `ta.cci`, `ta.cog`, `ta.bop`, `ta.ao`, `ta.max`, `ta.min`, `ta.mfi`, `ta.stoch`, `ta.wpr`, `ta.sar`, `ta.tr` function calls, `ta.atr`, `ta.highest`, `ta.lowest`, `ta.highestbars`, `ta.lowestbars`, `ta.change`, `ta.mom`, `ta.roc`, `ta.range`,
  `ta.dev`, `ta.vwap`, `ta.bbw`, `ta.kcw`, `ta.pivothigh`, `ta.pivotlow`,
  `ta.correlation`, `ta.covariance`, `ta.median`,
  `ta.mode`, `ta.percentile_nearest_rank`,
  `ta.percentile_linear_interpolation`, `ta.percentrank`, `ta.stdev`,
  `ta.variance`, `ta.wma`, `ta.vwma`, `ta.swma`, `ta.hma`, `ta.alma`,
  `ta.linreg`, `ta.rising`, `ta.falling`, `ta.barssince`, `ta.valuewhen`, `ta.cross`,
  `ta.crossover`, and `ta.crossunder`.
  Requested-context rolling callsite state is isolated from the chart context.
  Provider-backed tuple literals whose elements are in that scalar subset are
  supported when destructured directly from the request. Selected
  provider-backed tuple-returning calls are also supported when destructured
  directly, currently `ta.macd`, `ta.bb`, `ta.kc`, `ta.supertrend`, `ta.dmi`,
  and `ta.vwap(source, anchor, stdev_mult)`. Other provider-backed tuple
  expressions remain unsupported.
  Higher-timeframe alignment uses default `gaps_off` and `lookahead_off`: only
  confirmed requested bars are visible, and missing requested bars forward-fill
  the last confirmed value.
  Explicit default merge options are accepted as metadata:
  `gaps=barmerge.gaps_off` and `lookahead=barmerge.lookahead_off`.

Lower timeframe requests, provider expression local variable aliases, UDF calls,
stateful math calls such as `math.random`, `ta.tr` variable form,
output/drawing side effects, input
declarations, array mutation, non-default barmerge behavior, and non-default
explicit gaps/lookahead remain unsupported.
`request.security_lower_tf` is unsupported; it returns arrays in Pine and is not
claimed until typed array return semantics and host output shapes are designed.
`timeframe.in_seconds()` and `timeframe.in_seconds("")` return `60`.
Explicit timeframe strings support Pine-style seconds (`1S`, `5S`, `10S`,
`15S`, `30S`, `45S`), minutes (`1` through `1440`), days (`D`/`1D` through
`365D`), weeks (`W`/`1W` through `52W`), and months (`M`/`1M` through `12M`,
using 30-day month seconds). Tick and invalid timeframe strings are runtime
errors in this subset, while a `na` timeframe argument returns `na`.
`timeframe.from_seconds` supports the exact reverse conversion for values
representable in that subset, preferring canonical strings such as `"1"`, `"D"`,
`"W"`, and `"M"` over equivalent longer forms. Non-positive or otherwise
unrepresentable second counts are runtime errors, while a `na` seconds argument
returns `na`. `timeframe.change` uses the same supported timeframe string subset
and returns `true` on the first executed bar or when the UTC timeframe bucket
changes from the previous committed bar. Seconds, minutes, and days use fixed-
duration UTC buckets; weeks use Monday-based UTC calendar-week groups, and
months use UTC calendar-month groups. An empty-string timeframe argument uses
the fixed default chart timeframe, while a `na` timeframe argument returns `na`.

Type casts:

```text
int(x: int|float|bool|na) -> int with same qualifier
float(x: int|float|bool|na) -> float with same qualifier
bool(x: int|float|bool|na) -> bool with argument qualifier
string(x: int|float|bool|string|na) -> string with same qualifier
color(x: color|na) -> color with same qualifier
box(x: box|na) -> box
label(x: label|na) -> label
line(x: line|na) -> line
linefill(x: linefill|na) -> linefill
polyline(x: polyline|na) -> polyline
table(x: table|na) -> table
```

`int` truncates finite floats toward zero and maps bools to `1`/`0`.
`float` maps ints and bools to numeric floats. `bool` maps zero and `na` to
`false`, nonzero numeric values to `true`, and returns a bool with the argument
qualifier through the same `BoolFromArg` rule used by `na(x)`. `int(na)` and
`float(na)` return `na`. `string` maps scalar values using the default numeric
text format and returns `na` for `string(na)`. `color` preserves color values and
returns `na` for `color(na)`. `box` preserves box ids and returns `na` for
`box(na)`.
`label` preserves label ids and returns `na` for `label(na)`. `line` preserves
line ids and returns `na` for `line(na)`. `linefill` preserves linefill ids and
returns `na` for `linefill(na)`. `polyline` preserves polyline ids and returns
`na` for `polyline(na)`. `table` preserves table ids and returns `na` for
`table(na)`. Numeric-to-color and other object casts are not part of the current
subset.

Derived values:

```text
hl2   = (high + low) / 2
hlc3  = (high + low + close) / 3
hlcc4 = (high + low + close + close) / 4
ohlc4 = (open + high + low + close) / 4
```

## Declarations

```text
indicator(title: const string, shorttitle?: const string, overlay?: const bool, format?: const string, precision?: const int, scale?: const string, max_bars_back?: const int, max_labels_count?: const int named-only subset, max_boxes_count?: const int named-only subset, max_lines_count?: const int named-only subset, max_polylines_count?: const int named-only subset, ...)
  -> void
strategy(title: const string, shorttitle?: const string, overlay?: const bool, max_bars_back?: const int, initial_capital?: const numeric, currency?: const string, default_qty_type?: const string, default_qty_value?: const numeric, commission_type?: const string, commission_value?: const numeric, slippage?: const numeric, backtest_fill_limits_assumption?: const numeric, margin_long?: const numeric, margin_short?: const numeric, pyramiding?: const numeric, close_entries_rule?: const string, max_labels_count?: const int named-only subset, max_boxes_count?: const int named-only subset, max_lines_count?: const int named-only subset, max_polylines_count?: const int named-only subset)
  -> void
max_bars_back(source: series numeric, num: const int)
  -> void
strategy.entry(id: simple string, direction: string-compatible, qty?: series/simple numeric, limit?: series/simple numeric, stop?: series/simple numeric, comment?: string-compatible, alert_message?: string-compatible, disable_alert?: bool-compatible)
-> void
strategy.order(id: simple string, direction: string-compatible, qty?: series/simple numeric, limit?: series/simple numeric, stop?: series/simple numeric, oca_name?: string-compatible, oca_type?: string-compatible, comment?: string-compatible, alert_message?: string-compatible, disable_alert?: bool-compatible)
-> void
strategy.close(id: simple string, qty?: series/simple numeric, qty_percent?: series/simple numeric, comment?: string-compatible, alert_message?: string-compatible, disable_alert?: bool-compatible)
-> void
strategy.close_all(comment?: string-compatible, alert_message?: string-compatible, disable_alert?: bool-compatible) -> void
strategy.cancel(id: simple string) -> void
strategy.cancel_all() -> void
strategy.exit(id: simple string, from_entry?: simple string, stop?: series/simple numeric, limit?: series/simple numeric, profit?: series/simple numeric, loss?: series/simple numeric, trail_price?: series/simple numeric, trail_points?: series/simple numeric, trail_offset?: series/simple numeric, qty?: series/simple numeric, qty_percent?: series/simple numeric, comment?: string-compatible, comment_profit?: string-compatible, comment_loss?: string-compatible, comment_trailing?: string-compatible, alert_message?: string-compatible, alert_profit?: string-compatible, alert_loss?: string-compatible, alert_trailing?: string-compatible, disable_alert?: bool-compatible)
  -> void
strategy.convert_to_account(value: series/simple numeric) -> series float
strategy.convert_to_symbol(value: series/simple numeric) -> series float
strategy.default_entry_qty(fill_price: series/simple numeric) -> series float
strategy.account_currency -> simple string
strategy.position_entry_name -> series string
strategy.openprofit_percent -> series float
strategy.netprofit_percent -> series float
strategy.grossprofit -> series float
strategy.grossprofit_percent -> series float
strategy.grossloss -> series float
strategy.grossloss_percent -> series float
strategy.buy_and_hold_return_percent -> series float
strategy.avg_trade -> series float
strategy.avg_trade_percent -> series float
strategy.avg_winning_trade -> series float
strategy.avg_winning_trade_percent -> series float
strategy.avg_losing_trade -> series float
strategy.avg_losing_trade_percent -> series float
strategy.max_runup -> series float
strategy.max_runup_percent -> series float
strategy.max_drawdown -> series float
strategy.max_drawdown_percent -> series float
strategy.max_contracts_held_all -> series float
strategy.max_contracts_held_long -> series float
strategy.max_contracts_held_short -> series float
strategy.closedtrades.first_index -> series int
strategy.closedtrades.entry_price(trade_num: series/simple numeric) -> series float
strategy.closedtrades.entry_comment(trade_num: series/simple numeric) -> series string
strategy.closedtrades.entry_id(trade_num: series/simple numeric) -> series string
strategy.closedtrades.exit_price(trade_num: series/simple numeric) -> series float
strategy.closedtrades.exit_comment(trade_num: series/simple numeric) -> series string
strategy.closedtrades.exit_id(trade_num: series/simple numeric) -> series string
strategy.closedtrades.entry_bar_index(trade_num: series/simple numeric) -> series int
strategy.closedtrades.exit_bar_index(trade_num: series/simple numeric) -> series int
strategy.closedtrades.entry_time(trade_num: series/simple numeric) -> series int
strategy.closedtrades.exit_time(trade_num: series/simple numeric) -> series int
strategy.closedtrades.commission(trade_num: series/simple numeric) -> series float
strategy.closedtrades.size(trade_num: series/simple numeric) -> series float
strategy.closedtrades.profit(trade_num: series/simple numeric) -> series float
strategy.closedtrades.profit_percent(trade_num: series/simple numeric) -> series float
strategy.closedtrades.max_runup(trade_num: series/simple numeric) -> series float
strategy.closedtrades.max_runup_percent(trade_num: series/simple numeric) -> series float
strategy.closedtrades.max_drawdown(trade_num: series/simple numeric) -> series float
strategy.closedtrades.max_drawdown_percent(trade_num: series/simple numeric) -> series float
strategy.opentrades.capital_held -> series float
strategy.margin_liquidation_price -> series float
strategy.opentrades.entry_price(trade_num: series/simple numeric) -> series float
strategy.opentrades.entry_comment(trade_num: series/simple numeric) -> series string
strategy.opentrades.entry_id(trade_num: series/simple numeric) -> series string
strategy.opentrades.entry_bar_index(trade_num: series/simple numeric) -> series int
strategy.opentrades.entry_time(trade_num: series/simple numeric) -> series int
strategy.opentrades.size(trade_num: series/simple numeric) -> series float
strategy.opentrades.profit(trade_num: series/simple numeric) -> series float
strategy.opentrades.profit_percent(trade_num: series/simple numeric) -> series float
strategy.opentrades.commission(trade_num: series/simple numeric) -> series float
strategy.opentrades.max_runup(trade_num: series/simple numeric) -> series float
strategy.opentrades.max_runup_percent(trade_num: series/simple numeric) -> series float
strategy.opentrades.max_drawdown(trade_num: series/simple numeric) -> series float
strategy.opentrades.max_drawdown_percent(trade_num: series/simple numeric) -> series float
```

Only metadata arguments needed by the output and history-retention model should
be accepted in Phase 1. Declaration-level `max_bars_back` and top-level
`max_bars_back(source, num)` helper calls must use non-negative constant
integer lengths, including supported constant integer expressions, that fit in
the runtime's 32-bit unsigned history-bound field. The helper-call subset is
limited to series numeric sources, including simple identifiers and direct
series numeric expressions with stable pure unary/binary expression identity
reuse plus pure ternary expression identity reuse, including builtin qualified
constants/simple metadata, bar/session flags, and positional plus fixed-arity
named stateless pure math calls plus pure numeric cast calls, for matching history reads and unreassigned pure scalar series
declaration aliases, accepts positional or named
arguments, and applies a per-series retention bound for dynamic history reads.
Unsupported named arguments should produce compatibility diagnostics.
Typed variable declarations are fixture-backed for `int`, `float`, `bool`,
`string`, `color`, `chart.point`, and drawing-id `label`, `line`, `linefill`,
`box`, `table`, and `polyline` values, plus scalar `array<int>`,
`array<float>`, `array<bool>`, `array<string>`, `array<color>`, and
object-id `array<label>`, `array<line>`, `array<linefill>`,
`array<polyline>`, `array<box>`, `array<table>`, `array<chart.point>`, and
same-local scalar-field UDT `array<T>` values, and same-imported scalar-field
UDT `array<lib.Type>` values, with compatible or `na` initializers. The
fixture-backed scalar subset preserves initializer qualifiers for explicit
typed declarations, so const/input/simple initializers remain acceptable for
simple-parameter calls until a later reassignment promotes the symbol to a
stronger qualifier.
equivalent `type[]` aliases are fixture-backed for the same
supported array element types, including `var` declarations and the scalar
typed-array `varip` subset. These declarations assign the declared value kind to
the symbol, so later compatible reassignment works after `na` initialization.
Bare `array`, non-scalar UDT arrays, bare map,
map templates beyond scalar key/value kinds, bare matrix, and other typed
declarations remain unsupported with semantic diagnostics unless covered by a
narrower fixture-backed row.
`indicator(..., scale=...)` accepts the fixture-backed `scale.left`,
`scale.right`, and `scale.none` named constants as declaration metadata. The
runtime rejects other const string scale values and does not emit chart axis
placement or price-scale layout fields; those remain host-owned.
`indicator(..., format=...)` accepts `format.inherit`, `format.price`,
`format.percent`, and `format.volume`, while `precision` accepts const integer
values from 0 through 16. The runtime rejects other const string format values
and out-of-range precision values. Declaration formatting remains host-owned and
does not add runtime JSON fields.
`indicator(..., max_labels_count=N)` accepts named const integer values from
1 through 500 and stores them in HIR for label runtime eviction.
`indicator(..., max_boxes_count=N)` accepts named const integer values from
1 through 500 and stores them in HIR for box runtime eviction.
`indicator(..., max_lines_count=N)` accepts named const integer values from
1 through 500 and stores them in HIR for line runtime eviction.
`indicator(..., max_polylines_count=N)` accepts named const integer values from
1 through 100 and stores them in HIR for polyline runtime eviction.
Both positional declaration slots remain outside the current subset.
`strategy(...)` defaults `default_qty_type` to `strategy.fixed` and
`default_qty_value` to `1`, so `strategy.entry(..., qty=...)` may omit `qty` and
use the configured or default fixed quantity.
`default_qty_type=strategy.cash` is also supported for positive const numeric
`default_qty_value`; omitted supported entry `qty` resolves once at placement
time as cash divided by the current close under the current
no-currency-conversion boundary. `default_qty_type=strategy.percent_of_equity`
is also supported for positive const numeric `default_qty_value`; omitted
supported entry `qty` resolves once at placement time from current supported
equity and current close. `strategy.default_entry_qty(fill_price)` exposes the
same fixed, cash, and percent-of-equity sizing calculation as a read-only
strategy-mode series float. Cash sizing divides the configured cash by
`fill_price`; percent sizing divides the selected percentage of current
supported equity by `fill_price`; fixed sizing returns the configured unit
count. The helper does not add reversal quantity for an open position. Direct,
named, UDF, and history reads are supported. Non-positive or non-finite prices
produce `na` for price-dependent modes, as does non-positive or non-finite
supported equity for percent sizing. Currency conversion, symbol point value,
precision, and lot-step handling remain outside this subset.
`strategy(...)` accepts
`commission_type=strategy.commission.cash_per_contract`,
`strategy.commission.cash_per_order`, or `strategy.commission.percent` with a
finite non-negative const numeric `commission_value`; entry cash, exit cash,
realized trade profit, `strategy.netprofit`, and `strategy.equity` include that
commission when configured. `strategy(..., slippage=N)` accepts finite
non-negative integer
const ticks and uses the fixed `syminfo.mintick` subset; configured slippage
worsens supported long entry fill prices upward and supported long exit/close
fill prices downward after trigger selection.
`strategy(..., backtest_fill_limits_assumption=N)` accepts finite non-negative
integer const ticks and requires supported limit-order fills to move that many
fixed `syminfo.mintick` ticks past the limit price while preserving the limit
fill price. Other commission modes and richer fill models remain unsupported.
`strategy(..., margin_long=N, margin_short=N)` accepts finite non-negative
const numeric declaration values and stores their explicit presence for future
account-model slices. The current runtime uses explicit active `margin_long`
for long-only `strategy.opentrades.capital_held` and supported long-entry
affordability checks at the actual fill price. It also supports the first
long-only forced-liquidation subset using `bar.low` and whole-unit truncation.
Short margin behavior, symbol precision rounding, and margin liquidation price
remain unsupported.
`strategy(..., pyramiding=N)` accepts positive integer const values and limits
same-direction long `strategy.entry()` market entries to that many open trades
for the current position. The default remains `1`. Fixture-backed market-long
`strategy.order(id, strategy.long, qty=...)`, or omitted-qty long orders using
the configured default quantity, fill on the next historical bar open and can
add to an existing long position without consuming the `strategy.entry()`
pyramiding limit. Fixture-backed limit-long
`strategy.order(id, strategy.long, qty=..., limit=price)` fills through the
supported long limit timing model and also bypasses the `strategy.entry()`
pyramiding limit; omitted long `qty` uses the configured default quantity at
placement time. Fixture-backed stop-long
`strategy.order(id, strategy.long, qty=..., stop=price)` fills through the
supported long stop timing model and also bypasses the `strategy.entry()`
pyramiding limit; omitted long `qty` uses the configured default quantity at
placement time. Fixture-backed stop-limit-long
`strategy.order(id, strategy.long, qty=..., stop=stop_price, limit=limit_price)`
uses the supported long stop-limit activation and fill timing model and also
bypasses the `strategy.entry()` pyramiding limit; omitted long `qty` uses the
configured default quantity at placement time. Fixture-backed reduce-only market
`strategy.order(id, strategy.short, qty=...)` can reduce an existing long
position on the next historical bar open and clamps oversized quantities without
opening short exposure; while flat, it is a no-op. Omitted `qty` remains
unsupported for `strategy.short`. Short exposure, reversals, short price-based
orders, OCA behavior, same-tick price-based entry exceptions, and broader
multi-entry exit/reporting
semantics remain unsupported unless fixture-backed.
The supported `strategy.order()` subset accepts `comment`, `alert_message`,
and `disable_alert` metadata; long fills retain entry comments and reduce-only
short fills retain exit comments for script-visible trade comment helpers, while
supported fill payloads are exposed in `strategy.alerts`.
`strategy(..., max_labels_count=N)` accepts named const integer values from
1 through 500 and stores them in HIR for label runtime eviction.
`strategy(..., max_boxes_count=N)` accepts named const integer values from
1 through 500 and stores them in HIR for box runtime eviction.
`strategy(..., max_lines_count=N)` accepts named const integer values from
1 through 500 and stores them in HIR for line runtime eviction.
`strategy(..., max_polylines_count=N)` accepts named const integer values from
1 through 100 and stores them in HIR for polyline runtime eviction.
Both positional declaration slots remain outside the current subset.
`strategy.close(id)` can close a requested pyramided long entry id; multi-entry
`strategy.close_all()` can flatten all accepted open long entries. Fixture-backed
absolute stop/limit `strategy.exit` calls can target a requested open pyramided
long entry id, and supported single-trigger and bracket `profit`/`loss` exits
convert from that matched entry price. Supported trailing `trail_points` exits
also convert activation from that matched entry price. A supported exit matching
multiple open trades with the same entry id emits one exit order and one closed
trade per matched ledger allocation. Fixture-backed omitted-`from_entry`
absolute stop/limit exits can close all currently open pyramided long entries
and persist for later open long entries until the position closes. Broader
omitted-`from_entry` profit/loss-tick exits can close currently open pyramided
long entries with unique entry ids using each entry's own entry-price-derived
target, and omitted-`from_entry` full profit/loss-tick exits can persist for
later open long entries with unique entry ids until the position closes.
Omitted-`from_entry` full brackets (`stop+limit`, `stop+profit`,
`loss+limit`, and `loss+profit`) can close currently open pyramided long entries
with unique entry ids, using each entry's own entry-price-derived relative legs
when present, and full `stop+limit`, `loss+profit`, and `loss+limit` brackets
can persist for later open long entries until the position closes. Full
`stop+profit` brackets can also persist for later open long entries with unique
entry ids, using the shared absolute stop and each entry's own
entry-price-derived profit target. Omitted-`from_entry` full trailing exits
(`trail_price+trail_offset` and
`trail_points+trail_offset`) can close currently open pyramided long entries,
using each entry's own entry-price-derived activation for `trail_points` when
entry ids are unique. Omitted-`from_entry` full trailing exits can also persist
for later open long entries until the position closes: `trail_price` uses the
shared absolute activation price, while `trail_points` uses each unique entry's
own entry-price-derived activation. Duplicate same-id relative targets remain
outside the current claim. Broader
multi-entry `strategy.exit` semantics remain outside the current claim.
`strategy.initial_capital` is a read-only strategy-mode series float that
returns the positive configured `strategy(..., initial_capital=...)` value, or
the existing default starting capital when omitted, on every bar. It follows
ordinary series history and does not add a public runtime schema field.
`strategy.account_currency` is a read-only strategy-mode simple string. In the
current default-only `currency.NONE` declaration subset, it inherits the fixed
`syminfo.currency` value, currently `"USD"`. Direct, UDF, and history reads are
supported without adding a public runtime schema field. The explicit
`strategy(..., currency=currency.NONE)` no-conversion declaration is accepted;
other currency values and settings overrides remain outside the current subset.
`strategy.convert_to_account(value)` and `strategy.convert_to_symbol(value)`
support the resulting same-currency boundary as strategy-mode `series float`
identities. They accept series/simple numeric values, coerce integers to floats,
preserve typed `na`, and support direct, named, UDF, and history calls. Indicator
and requested-context use are rejected; cross-currency conversion remains
unsupported, and no public runtime schema field is added.
`strategy.position_entry_name` is a read-only strategy-mode series string. It
is `na` while flat and otherwise returns the entry order ID that initially
opened the current continuous net long position. Pyramiding additions and
partial allocation closes do not replace it; returning to flat clears it so a
later position can establish a new name. Direct, UDF, and history reads are
supported without adding a public runtime schema field.
`strategy.openprofit_percent` is a read-only strategy-mode series float that
divides current unrealized profit by realized equity
(`initial_capital + netprofit`) and multiplies by 100. It returns `na` when the
realized-equity denominator is non-positive or non-finite.
`strategy.netprofit_percent`, `strategy.grossprofit_percent`, and
`strategy.grossloss_percent` are read-only strategy-mode series floats that
divide the corresponding realized amount by `initial_capital` and multiply by
100.
`strategy.closedtrades.first_index` is a read-only strategy-mode series int.
It remains `0` in the current broker because closed trades are not trimmed,
including before the first close; direct, UDF, and history reads are supported,
while platform order-limit trimming remains outside this contract.
`strategy.buy_and_hold_return_percent` is a read-only strategy-mode series
float that returns `(close - first_close) / first_close * 100`, using the first
loaded bar close as `first_close`; it returns `na` when that baseline is zero or
non-finite.
`strategy.grossprofit` is a read-only strategy-mode series float that sums
positive realized closed-trade profit only. Losing, flat, and current open
trades do not change it. `strategy.grossloss` is a read-only strategy-mode
series float that sums realized closed-trade losses as positive values.
Winning, flat, and current open trades do not change it. `strategy.avg_trade`
is a read-only strategy-mode series float that returns average realized
profit/loss per closed trade, or `na` before the first closed trade.
`strategy.avg_trade_percent`, `strategy.avg_winning_trade_percent`, and
`strategy.avg_losing_trade_percent` are read-only strategy-mode series floats
that average per-closed-trade percentage profit/loss values, using each closed
trade's net profit divided by that trade's entry price times quantity; the
losing variant returns positive loss percentages.
`strategy.avg_winning_trade` is a read-only strategy-mode series float that
returns average realized profit among winning closed trades only, or `na`
before the first winning closed trade.
`strategy.avg_losing_trade` is a read-only strategy-mode series float that
returns average realized loss among losing closed trades only as a positive
value, or `na` before the first losing closed trade.
`strategy.max_contracts_held_all`, `strategy.max_contracts_held_long`, and
`strategy.max_contracts_held_short` are read-only strategy-mode series floats
for the maximum contracts/shares/lots/units held over the whole trading range;
in the current long-only subset, `all` and `long` track the maximum filled
long-entry quantity and `short` remains `0`.
`strategy.max_runup` is a read-only strategy-mode series float that returns the
maximum intrabar equity run-up amount over the current supported long-only
trading interval, using the supported entry equity, the minimum equity before
that entry, and the highest high reached while the supported position is open.
`strategy.max_runup_percent` is a read-only strategy-mode series float that
divides the supported run-up amount by entry price times current supported
position quantity and multiplies by 100.
`strategy.max_drawdown` is a read-only strategy-mode series float that returns
the maximum intrabar equity drawdown amount over the current supported trading
interval, using the supported entry equity, the maximum equity before that
entry, and the lowest low reached while the supported position is open.
`strategy.max_drawdown_percent` is a read-only strategy-mode series float that
divides the supported drawdown amount by entry price times current supported
position quantity and multiplies by 100.
Supported market-long entries fill at the next
historical bar open. Supported long limit entries wait until a later
historical bar where `low <= limit`, or below the configured verified limit
threshold, and fill at the limit price. Supported long stop entries wait until
a later historical bar where `high >= stop` and fill at
the stop price. Supported long stop-limit entries wait until a later historical
bar where `high >= stop`, activate an internal limit order without filling on
that activation bar, then fill at the limit price on a later historical bar
where `low <= limit`, or below the configured verified limit threshold. These
entry forms do not expose public pending-order records while pending.
`strategy.close` supports full close, fixed `qty` partial close, and
`qty_percent` partial close for the current matching long entry id at the current
bar close. Fixed `qty` and `qty_percent` must be finite and positive;
`qty_percent` resolves against the current matching position size, and fixed
`qty` wins when both quantity forms are provided. Oversized quantities clamp to
the current matching position size, remaining long position state stays open at
the same average price, and matching pending exits are cancelled only when the
close fully flattens the entry. `comment`, `alert_message`, and
`disable_alert` arguments are stored internally on closed-trade metrics without
external alert-delivery or public JSON effect. `immediately`, partial
`strategy.close_all()`, and multi-entry close allocation remain unsupported.
`strategy.close_all()` closes the current supported long position at the current
bar close and is a no-op while flat; its `comment`, `alert_message`, and
`disable_alert` arguments have the same internal-only metadata boundary.
`strategy.cancel(id)` cancels matching internal pending entry ids and matching
internal pending exit ids in the current supported order subset. Unknown,
already-filled, and already-cancelled ids are no-op. Cancellation emits no
public order record and does not add pending-order fields to the public output.
`strategy.cancel_all()` cancels all currently supported internal pending entries
and pending exits. Calling it while there are no pending orders is a no-op, and
it does not add public pending-order or cancellation records.
`strategy.exit` accepts `qty`, `qty_percent`, or both on supported
single-trigger, one-downside/one-upside bracket, and trailing trigger shapes.
When both are present, fixed `qty` determines the reserved or filled quantity
and `qty_percent` is ignored. Explicit fixed `qty` or `qty_percent` exits on
those supported shapes can keep multiple reserved pending exits for different
`id + from_entry` identities on the current matching long entry, a matching
open pyramided long entry for fixture-backed absolute stop/limit exits, or the
active pending entry for same-calculation absolute `stop`, `limit`, and
`trail_price` attachment plus entry-relative `profit`, `loss`, and
`trail_points` attachment. Supported `strategy.entry`, `strategy.order`,
`strategy.exit`, `strategy.close`, and `strategy.close_all` metadata arguments
are retained on broker-owned fill events and exposed as raw order-fill payloads in
`strategy.alerts` for supported fills. Explicit Python, CLI, and WASM host
helpers can render `{{strategy.order.alert_message}}` for selected public fill
events; external alert delivery remains unsupported. Richer strategy order
options remain unsupported.
`strategy.closedtrades.entry_price`, `strategy.closedtrades.exit_price`,
`strategy.closedtrades.entry_comment`, `strategy.closedtrades.entry_id`,
`strategy.closedtrades.exit_comment`, `strategy.closedtrades.exit_id`,
`strategy.closedtrades.entry_bar_index`, and
`strategy.closedtrades.exit_bar_index`, `strategy.closedtrades.entry_time`,
`strategy.closedtrades.exit_time`, `strategy.closedtrades.commission`,
`strategy.closedtrades.size`, `strategy.closedtrades.profit`,
`strategy.closedtrades.profit_percent`, `strategy.closedtrades.max_runup`,
`strategy.closedtrades.max_runup_percent`,
`strategy.closedtrades.max_drawdown`, and
`strategy.closedtrades.max_drawdown_percent` are
read-only strategy-mode field functions over the current closed-trade list.
`strategy.opentrades.entry_price`, `strategy.opentrades.entry_comment`,
`strategy.opentrades.entry_id`, and
`strategy.opentrades.entry_bar_index`, `strategy.opentrades.entry_time`, and
`strategy.opentrades.size`, `strategy.opentrades.profit`,
`strategy.opentrades.profit_percent`, `strategy.opentrades.commission`,
`strategy.opentrades.max_runup`, `strategy.opentrades.max_runup_percent`,
`strategy.opentrades.max_drawdown`, and
`strategy.opentrades.max_drawdown_percent` are read-only strategy-mode field functions
over the current long-only open-trade ledger.
The six percentage helpers divide the matching amount by the selected trade's
entry price times absolute quantity and multiply by 100. Invalid indexes,
flat-state open-trade reads, and non-positive or non-finite entry values return
`na`, matching the indexed trade-field boundary.
`strategy.opentrades.capital_held` is a read-only strategy-mode variable. The
current no-margin subset returns `na`; with explicit active `margin_long`, the
current long-only subset returns current open long market value multiplied by
`margin_long / 100`, including after the current long-only forced-liquidation
subset reduces the open position. Short margin behavior remains unsupported.
`strategy.margin_liquidation_price` is a read-only strategy-mode series float
that returns the current long-only broker price where supported equity equals
required long margin for an active `margin_long` position. It returns `na`
without active long margin, while flat, or when the long margin denominator is
unattainable, such as `margin_long=100`. Symbol tick rounding, short margin,
and public margin-specific schema expansion remain unsupported.
`trade_num` is a zero-based integer index; missing, negative, out-of-range, or
non-integer indexes return `na`. Closed- and open-trade `entry_id` return the
retained entry id. Closed-trade `exit_id` returns the retained close or exit id.
Closed- and open-trade `commission` return `0.0` without configured commission,
or supported cash commission when a declaration commission mode is configured.
Open-trade `profit` returns the current close-based floating profit for the
current supported long position. Closed- and open-trade
`max_runup` return the largest high-based favorable excursion seen so far for
the retained trade quantity. Closed- and open-trade `max_drawdown` return the
largest low-based adverse excursion seen so far for the retained trade
quantity. They do not add public runtime schema fields. Other closed-trade
fields outside `entry_price`, `entry_comment`, `entry_id`, `exit_price`,
`exit_comment`, `exit_id`, `entry_bar_index`, `exit_bar_index`, `entry_time`,
`exit_time`, `size`, `profit`, `profit_percent`, `commission`, `max_runup`,
`max_runup_percent`, `max_drawdown`, and `max_drawdown_percent` remain
unsupported. Other open-trade namespace functions outside `entry_price`,
`entry_comment`, `entry_id`, `entry_bar_index`, `entry_time`, `size`, `profit`,
`profit_percent`, `commission`, `max_runup`, `max_runup_percent`,
`max_drawdown`, and `max_drawdown_percent` remain unsupported.

## Inputs

```text
input(defval: const int/float/bool/string/color, title?: const string, options?: tuple, tooltip?: const string, inline?: const string, group?: const string, confirm?: const bool, display?: string-compatible) -> input defval kind
input.int(defval: const int, title?: const string, minval?: const int, maxval?: const int, step?: const int, options?: tuple, tooltip?: const string, inline?: const string, group?: const string, confirm?: const bool, display?: string-compatible) -> input int
input.float(defval: const float, title?: const string, minval?: const numeric, maxval?: const numeric, step?: const numeric, options?: tuple, tooltip?: const string, inline?: const string, group?: const string, confirm?: const bool, display?: string-compatible) -> input float
input.bool(defval: const bool, title?: const string, tooltip?: const string, inline?: const string, group?: const string, confirm?: const bool, display?: string-compatible) -> input bool
input.color(defval: const color, title?: const string, tooltip?: const string, inline?: const string, group?: const string, confirm?: const bool, display?: string-compatible) -> input color
input.string(defval: const string, title?: const string, options?: tuple, tooltip?: const string, inline?: const string, group?: const string, confirm?: const bool, display?: string-compatible) -> input string
input.price(defval: const float, title?: const string, minval?: const numeric, maxval?: const numeric, step?: const numeric, options?: tuple, tooltip?: const string, inline?: const string, group?: const string, confirm?: const bool, display?: string-compatible) -> input float
input.time(defval: const int, title?: const string, minval?: const int, maxval?: const int, step?: const int, options?: tuple, tooltip?: const string, inline?: const string, group?: const string, confirm?: const bool, display?: string-compatible) -> input int
input.symbol(defval: const string, title?: const string, options?: tuple, tooltip?: const string, inline?: const string, group?: const string, confirm?: const bool, display?: string-compatible) -> input string
input.timeframe(defval: const string, title?: const string, options?: tuple, tooltip?: const string, inline?: const string, group?: const string, confirm?: const bool, display?: string-compatible) -> input string
input.session(defval: const string, title?: const string, options?: tuple, tooltip?: const string, inline?: const string, group?: const string, confirm?: const bool, display?: string-compatible) -> input string
input.text_area(defval: const string, title?: const string, tooltip?: const string, group?: const string, confirm?: const bool, display?: string-compatible) -> input string
input.source(defval: series float, title?: const string, tooltip?: const string, inline?: const string, group?: const string, confirm?: const bool, display?: string-compatible) -> series float
```

Rules:

- Input metadata is accepted and validated during analysis.
- Runtime execution uses each input's `defval` unless the Rust runtime is run
  with call-site keyed `InputOverrides`, the CLI supplies
  `--input-override CALL_SITE_ID=value`, or the Python host supplies a
  call-site keyed `input_overrides` dictionary to `Program.run()` or
  `run_script()`, or the WASM host supplies an `inputOverridesJson` object to a
  `*WithInputOverrides` run API.
- The supported metadata subset validates common option names and types, then
  ignores metadata at runtime; call-site keyed overrides provide the executable
  value only when explicitly supplied by the Rust, CLI, Python, or WASM host.
- `input.session` and `input.text_area` currently execute their `defval`
  strings unless a Rust, CLI, Python, or WASM host override is supplied.
- `input.source` returns the selected source series. Phase 1 may restrict this
  to known OHLCV-derived series. Host-side `input.source` overrides remain
  unsupported.

## Plotting

```text
alertcondition(condition: bool-compatible, title: const string, message: const string)
  -> void

alert(message: string-compatible, freq?: const string)
  -> void

plot(series: series/simple numeric, title?: const string, color?: color-compatible, linewidth?: input/const int, style?: const string, trackprice?: const bool, histbase?: input/const numeric, offset?: simple integer-compatible, join?: const bool, editable?: const bool, show_last?: input/const int, display?: const string, format?: const string, precision?: simple integer-compatible, force_overlay?: const bool)
  -> plot

plotchar(series: series/simple numeric-or-bool, title?: const string, char?: const string, color?: color-compatible, location?: const string, offset?: simple integer-compatible, text?: const string, textcolor?: color-compatible, editable?: const bool, size?: const string, show_last?: input/const int, display?: const string)
  -> void

plotshape(series: series/simple numeric-or-bool, title?: const string, style?: const string, location?: const string, color?: color-compatible, offset?: simple integer-compatible, text?: const string, textcolor?: color-compatible, editable?: const bool, size?: const string, show_last?: input/const int, display?: const string, force_overlay?: const bool)
  -> void

plotarrow(series: series/simple numeric, title?: const string, colorup?: color-compatible, colordown?: color-compatible, offset?: simple integer-compatible, minheight?: simple integer-compatible, maxheight?: simple integer-compatible, editable?: const bool, show_last?: input/const int, display?: const string, force_overlay?: const bool)
  -> void

plotbar(open: series/simple numeric, high: series/simple numeric, low: series/simple numeric, close: series/simple numeric, title?: const string, color?: color-compatible, editable?: const bool, show_last?: input/const int, display?: const string)
  -> void

plotcandle(open: series/simple numeric, high: series/simple numeric, low: series/simple numeric, close: series/simple numeric, title?: const string, color?: color-compatible, wickcolor?: color-compatible, editable?: const bool, show_last?: input/const int, bordercolor?: color-compatible, display?: const string)
  -> void

hline(price: input/const numeric, title?: const string, color?: input/const color, linestyle?: const string, linewidth?: input/const int, editable?: const bool, display?: const string)
  -> hline

fill(plot1: plot-or-hline, plot2: plot-or-hline, color?: color-compatible, title?: const string, editable?: const bool, show_last?: input/const int, fillgaps?: const bool, display?: const string)
  -> void

bgcolor(color: color-compatible, title?: const string, offset?: simple integer-compatible, editable?: const bool, show_last?: input/const int, display?: const string) -> void
barcolor(color: color-compatible, title?: const string, offset?: simple integer-compatible, editable?: const bool, show_last?: input/const int, display?: const string) -> void
```

`alertcondition` emits a runtime alert event when its reached condition
evaluates to `true`. `title` is serialized as event `source`; `message` is
serialized as event `message` after replacing `{{open}}`, `{{high}}`,
`{{low}}`, `{{close}}`, and `{{volume}}` with triggering-bar values, plus
`{{ticker}}`, `{{interval}}`, and `{{exchange}}` with current chart metadata,
and `{{time}}` with the triggering bar timestamp using the UTC
`str.format_time` default format. `alert` serializes `source` as `alert`,
evaluates its string-compatible `message` at runtime, and supports a narrow
const-string frequency subset: the default
`alert.freq_once_per_bar` emits at most one event per callsite per bar, while
`alert.freq_all` emits every reached call. `alert.freq_once_per_bar_close`
emits at most one event per callsite only during historical or confirmed
realtime bar-close execution. Dynamic `alertcondition` title/message strings,
`alert()` placeholders, `alertcondition` title placeholders, unknown
`alertcondition` message placeholders, and alert side effects inside UDF or
requested-context expressions are not part of the current subset.

`color-compatible` should initially accept:

- const color
- input color
- series color where the target built-in supports dynamic color
- `na` to mean no color for that bar when supported

The output collector retains plot ids, hline ids, and bar-aligned output series
so host integrations can adapt the normalized result without reinterpreting the
script. The supported output metadata subset accepts common style, visibility,
display, and editability parameters for compatibility, but accepted metadata is
not the same as emitted output schema.

Current normalized output fields are:

- `plot`: id and values only. Color, line style, width, trackprice, histbase,
  join, format, precision, and editability metadata are accepted but not
  emitted as fields.
- `hline`: id and price only. Color, line style, width, editability, and
  display metadata are accepted but not emitted as fields.
- `fill`: id plus first/second plot or hline ids only. Color, title,
  editability, show_last, fillgaps, and display metadata are accepted but not
  emitted as fields.
- `bgcolor`/`barcolor`: id and color values only.
- `plotchar`: value, char, and color series only. Location, text, textcolor,
  size, visibility, and editability metadata are accepted but not emitted as
  fields.
- `plotshape`: value, style, location, color, text, textcolor, and size
  series.
- `plotarrow`: value, up-color, down-color, min-height, and max-height series.
- `plotbar`: open, high, low, close, and color series.
- `plotcandle`: open, high, low, close, body color, wick color, and border
  color series.
- `label.all`: a snapshot label-array of currently existing label ids in
  creation order. Deleted or max-count evicted labels are omitted from
  subsequent reads. Mutating the returned array does not mutate the underlying
  label store.
- `line.all`: a snapshot line-array of currently existing line ids in creation
  order. Deleted or max-count evicted lines are omitted from subsequent reads.
  Mutating the returned array does not mutate the underlying line store.
- `linefill.all`: a snapshot linefill-array of currently existing linefill ids
  in creation order. Replaced or deleted linefills are omitted from subsequent
  reads. Mutating the returned array does not mutate the underlying linefill
  store.
- `box.all`: a snapshot box-array of currently existing box ids in creation
  order. Deleted or max-count evicted boxes are omitted from subsequent reads.
  Mutating the returned array does not mutate the underlying box store.
- `table.all`: a snapshot table-array of currently existing table ids in
  creation order. Deleted tables are omitted from subsequent reads. Mutating the
  returned array does not mutate the underlying table store.

Parameters such as `offset`, `show_last`, `display`, `force_overlay`, and
`editable` do not yet transform, filter, or annotate the runtime output series.
Supported direct display constants include `display.all`, `display.none`,
`display.pane`, `display.price_scale`, `display.status_line`, and
`display.data_window`. Display flag arithmetic is not implemented yet.
Supported direct format constants include `format.inherit`, `format.mintick`,
`format.price`, `format.percent`, and `format.volume`. Indicator declaration
format metadata accepts `format.inherit`, `format.price`, `format.percent`, and
`format.volume`; `format.mintick` remains covered by `str.tostring`.
Supported indicator scale constants include `scale.left`, `scale.right`, and
`scale.none` as declaration metadata; chart axis placement remains host-owned.
Supported request merge constants include `barmerge.gaps_off`,
`barmerge.gaps_on`, `barmerge.lookahead_off`, and
`barmerge.lookahead_on` as string constants. `request.security` accepts only
the default `barmerge.gaps_off` and `barmerge.lookahead_off` merge metadata;
non-default merge behavior remains unsupported.
Supported direct currency constants include the official `currency.*`
currency-code set from `currency.AUD` through `currency.ZAR`, including
`currency.NONE`, `currency.BTC`, `currency.ETH`, `currency.USD`, and
`currency.USDT`, as string values such as `"USD"`. Request currency conversion,
non-`NONE` strategy account-currency configuration, and cross-currency strategy
conversion are not implemented; the default and explicit `currency.NONE`
`strategy.account_currency` reads and same-currency strategy conversions are
supported as described above.
Supported direct strategy constants include `strategy.long`, `strategy.short`,
`strategy.fixed`, `strategy.cash`, `strategy.percent_of_equity`,
`strategy.oca.cancel`, `strategy.oca.none`, `strategy.oca.reduce`,
`strategy.commission.cash_per_contract`,
`strategy.commission.cash_per_order`, and `strategy.commission.percent` as
string values. `strategy.entry` execution remains long-only; `strategy.short`
entries remain unsupported, and OCA order behavior remains unsupported.

## Utility

```text
na(x: any) -> bool with argument qualifier
nz(x: numeric-or-color-series) -> same kind and qualifier as x
nz(x: T, replacement: T) -> strongest qualifier of x and replacement, kind T
fixnan(source: series/simple int|float|color) -> same kind and qualifier as source
runtime.error(message: string-compatible) -> void
```

`na(x)` returns a bool with the argument qualifier: input, simple, and series
arguments produce input, simple, and series bool results respectively.

`nz` overloads must be explicit. Do not implement `nz` with a generic host
language null helper.
`fixnan` returns the current non-`na` source value and otherwise returns the
last non-`na` value observed at the same callsite. It returns `na` until the
callsite has observed a non-`na` value.
`runtime.error` accepts const, input, simple, or series strings. When execution
reaches the call, it evaluates the message and immediately stops the current
script run with that exact text. It is allowed inside user-defined functions,
supports the named `message` argument, and has no value-producing return. A
string-compatible `na` message is normalized to `NaN`, matching the runtime's
existing string rendering convention.

## Arrays

```text
array.new_float(size?: simple integer-compatible, initial_value?: numeric-compatible) -> simple float-array
array.new<float>(size?: simple integer-compatible, initial_value?: numeric-compatible) -> simple float-array
array.new_int(size?: simple integer-compatible, initial_value?: int-compatible) -> simple int-array
array.new<int>(size?: simple integer-compatible, initial_value?: int-compatible) -> simple int-array
array.new_bool(size?: simple integer-compatible, initial_value?: bool-compatible) -> simple bool-array
array.new<bool>(size?: simple integer-compatible, initial_value?: bool-compatible) -> simple bool-array
array.new_string(size?: simple integer-compatible, initial_value?: string-compatible) -> simple string-array
array.new<string>(size?: simple integer-compatible, initial_value?: string-compatible) -> simple string-array
array.new_color(size?: simple integer-compatible, initial_value?: color-compatible) -> simple color-array
array.new<color>(size?: simple integer-compatible, initial_value?: color-compatible) -> simple color-array
array.new_label(size?: simple integer-compatible, initial_value?: label-compatible) -> simple label-array
array.new<label>(size?: simple integer-compatible, initial_value?: label-compatible) -> simple label-array
array.new_line(size?: simple integer-compatible, initial_value?: line-compatible) -> simple line-array
array.new<line>(size?: simple integer-compatible, initial_value?: line-compatible) -> simple line-array
array.new_linefill(size?: simple integer-compatible, initial_value?: linefill-compatible) -> simple linefill-array
array.new<linefill>(size?: simple integer-compatible, initial_value?: linefill-compatible) -> simple linefill-array
array.new_polyline(size?: simple integer-compatible, initial_value?: polyline-compatible) -> simple polyline-array
array.new<polyline>(size?: simple integer-compatible, initial_value?: polyline-compatible) -> simple polyline-array
array.new_box(size?: simple integer-compatible, initial_value?: box-compatible) -> simple box-array
array.new<box>(size?: simple integer-compatible, initial_value?: box-compatible) -> simple box-array
array.new_table(size?: simple integer-compatible, initial_value?: table-compatible) -> simple table-array
array.new<table>(size?: simple integer-compatible, initial_value?: table-compatible) -> simple table-array
array.new<chart.point>(size?: simple integer-compatible, initial_value?: chart-point-compatible) -> simple chart-point-array
array.from(value, ...) -> simple inferred scalar-or-object-array
array.size(id: float-array|int-array|bool-array|string-array|color-array|label-array|line-array|linefill-array|polyline-array|box-array|table-array|chart-point-array) -> simple int
array.push(id: float-array|int-array|bool-array|string-array|color-array|label-array|line-array|linefill-array|polyline-array|box-array|table-array|chart-point-array, value: element-compatible) -> void
array.get(id: float-array|int-array|bool-array|string-array|color-array|label-array|line-array|linefill-array|polyline-array|box-array|table-array|chart-point-array, index: simple integer-compatible) -> series element
array.set(id: float-array|int-array|bool-array|string-array|color-array|label-array|line-array|linefill-array|polyline-array|box-array|table-array|chart-point-array, index: simple integer-compatible, value: element-compatible) -> void
array.insert(id: float-array|int-array|bool-array|string-array|color-array|label-array|line-array|linefill-array|polyline-array|box-array|table-array|chart-point-array, index: simple integer-compatible, value: element-compatible) -> void
array.pop(id: float-array|int-array|bool-array|string-array|color-array|label-array|line-array|linefill-array|polyline-array|box-array|table-array|chart-point-array) -> series element
array.remove(id: float-array|int-array|bool-array|string-array|color-array|label-array|line-array|linefill-array|polyline-array|box-array|table-array|chart-point-array, index: simple integer-compatible) -> series element
array.shift(id: float-array|int-array|bool-array|string-array|color-array|label-array|line-array|linefill-array|polyline-array|box-array|table-array|chart-point-array) -> series element
array.unshift(id: float-array|int-array|bool-array|string-array|color-array|label-array|line-array|linefill-array|polyline-array|box-array|table-array|chart-point-array, value: element-compatible) -> void
array.fill(id: float-array|int-array|bool-array|string-array|color-array|label-array|line-array|linefill-array|polyline-array|box-array|table-array|chart-point-array, value: element-compatible, index_from?: simple integer-compatible, index_to?: simple integer-compatible) -> void
array.first(id: float-array|int-array|bool-array|string-array|color-array|label-array|line-array|linefill-array|polyline-array|box-array|table-array|chart-point-array) -> series element
array.last(id: float-array|int-array|bool-array|string-array|color-array|label-array|line-array|linefill-array|polyline-array|box-array|table-array|chart-point-array) -> series element
array.copy(id: float-array|int-array|bool-array|string-array|color-array|label-array|line-array|linefill-array|polyline-array|box-array|table-array|chart-point-array) -> same array kind
array.slice(id: float-array|int-array|bool-array|string-array|color-array|label-array|line-array|linefill-array|polyline-array|box-array|table-array|chart-point-array, index_from: simple integer-compatible, index_to: simple integer-compatible) -> same array kind
array.concat(id: float-array|int-array|bool-array|string-array|color-array|label-array|line-array|linefill-array|polyline-array|box-array|table-array|chart-point-array, id2: same array kind) -> same array kind
array.includes(id: float-array|int-array|bool-array|string-array|color-array|label-array|line-array|linefill-array|polyline-array|box-array|table-array|chart-point-array, value: element-compatible) -> series bool
array.includes(id: same-local-scalar-field-UDT-array, value: same local UDT) -> series bool
array.every(id: float-array|int-array|bool-array) -> series bool
array.some(id: float-array|int-array|bool-array) -> series bool
array.indexof(id: float-array|int-array|bool-array|string-array|color-array|label-array|line-array|linefill-array|polyline-array|box-array|table-array|chart-point-array, value: element-compatible) -> simple int
array.indexof(id: same-local-scalar-field-UDT-array, value: same local UDT) -> simple int
array.lastindexof(id: float-array|int-array|bool-array|string-array|color-array|label-array|line-array|linefill-array|polyline-array|box-array|table-array|chart-point-array, value: element-compatible) -> simple int
array.lastindexof(id: same-local-scalar-field-UDT-array, value: same local UDT) -> simple int
array.binary_search(id: float-array|int-array, value: element-compatible) -> simple int
array.binary_search_leftmost(id: float-array|int-array, value: element-compatible) -> simple int
array.binary_search_rightmost(id: float-array|int-array, value: element-compatible) -> simple int
array.abs(id: float-array|int-array) -> same array kind
array.min(id: float-array|int-array, nth?: int-compatible) -> series element
array.max(id: float-array|int-array, nth?: int-compatible) -> series element
array.sum(id: float-array|int-array) -> series element
array.avg(id: float-array|int-array) -> series float
array.range(id: float-array|int-array) -> series element
array.median(id: float-array|int-array) -> series element
array.mode(id: float-array|int-array) -> series element
array.percentile_nearest_rank(id: float-array|int-array, percentage: numeric-compatible) -> series element
array.percentile_linear_interpolation(id: float-array|int-array, percentage: numeric-compatible) -> series float
array.percentrank(id: float-array|int-array, index: simple integer-compatible) -> series float
array.covariance(id1: float-array|int-array, id2: float-array|int-array, biased?: bool-compatible) -> series float
array.standardize(id: float-array|int-array) -> float-array
array.variance(id: float-array|int-array, biased?: bool-compatible) -> series float
array.stdev(id: float-array|int-array, biased?: bool-compatible) -> series float
array.sort(id: float-array|int-array|string-array, order?: const string) -> void
array.sort(id: UDT-array, order?: const string, sort_field?: const int|string = 0) -> void
array.sort_indices(id: float-array|int-array|string-array, order?: const string) -> int-array
array.sort_indices(id: UDT-array, order?: const string, sort_field?: const int|string = 0) -> int-array
array.reverse(id: float-array|int-array|bool-array|string-array|color-array|label-array|line-array|linefill-array|polyline-array|box-array|table-array|chart-point-array) -> void
array.join(id: float-array|int-array|bool-array|string-array|color-array, separator?: string-compatible) -> series string
array.clear(id: float-array|int-array|bool-array|string-array|color-array|label-array|line-array|linefill-array|polyline-array|box-array|table-array|chart-point-array) -> void
```

The supported typed-array subset covers float, int, bool, string, color, label,
line, linefill, polyline, box, table, and chart.point arrays. Scalar and drawing-object
arrays can be constructed through the supported type-specific `array.new_*`
calls or the official `array.new<type>`
syntax for float, int, bool, string, color, label, line, linefill, polyline,
box, and table.
The scalar constructors and their official `array.new<float>`,
`array.new<int>`, `array.new<bool>`, `array.new<string>`, and
`array.new<color>` template forms return fixed `simple array<T>` values
accepted by matching element-array consumers and rejected by mismatched ones.
Drawing-object constructors, their official `array.new<type>` template forms,
and `array.new<chart.point>` also return fixed `simple array<T>` values
accepted by matching typed-array consumers and rejected by mismatched ones.
Float arrays accept int, float, or `na` values and store int values as floats. Int
arrays accept int values. Bool arrays accept bool values. String arrays accept
string values. Color arrays accept color values. Label, line, linefill, polyline, box,
and table arrays accept their matching drawing ids or `na` and keep reference
elements shallow across `array.copy`. `array.from(label|line|linefill|polyline|
box|table|chart.point, ...)` returns fixed `simple array<T>` values accepted by
matching typed-array consumers and rejected by mismatched ones.
`array.new<chart.point>()`, `array.from(chart.point, ...)`, and
`array.from(polyline, ...)` construct chart-point or polyline arrays, and the
generic storage/read/mutation/search subset can carry `chart.point` and `polyline` values;
`polyline.new` consumes these arrays as its point-list input and copies the
values into runtime snapshots. Numeric, truth, sort, and join helpers still
reject chart-point and polyline arrays. Array
assignment and side-effect-free user-defined function
parameters pass the array id; array mutation inside user-defined functions
remains unsupported. `array.from` infers the array
kind from its arguments, requires at least one non-`na` supported typed value,
allows `na` in otherwise typed arrays, and promotes mixed int/float arguments
to a float array. `array.join` supports scalar typed arrays and the
fixture-backed same-local scalar-tree UDT array subset, while
`str.tostring(array)` remains limited to non-color scalar typed arrays. Color,
linefill, drawing-id, chart-point, and UDT arrays remain outside the
`str.tostring(array)` subset. Separately, `str.tostring` accepts the supported
float/int/bool/string matrix families but not color matrices. Array
size/index/range parameters are simple
integer-compatible: explicit `na` size returns `na`, read-style `na` indexes or
slice bounds return `na`, and mutation-style `na` indexes or fill bounds are
no-ops. Linefill arrays are supported for generic
object-array storage and search, chart-point arrays are supported for generic
point-list storage and search, and `polyline.all` exposes a read-only snapshot
polyline id array. General polyline array construction and mutation remain
unsupported.
`size/get/set/insert/push/pop/remove/shift/unshift/fill/first/last/copy/slice/concat/includes/indexof/lastindexof/clear`
may also be called with method syntax on a supported array receiver.
`array.get`, `array.set`, `array.insert`, and `array.remove` support negative
indexes from the array end. `array.insert` inserts a compatible value before
the requested index; greater-than-size or otherwise out-of-bounds indexes are
runtime errors. `array.remove` removes and returns an element, while
out-of-bounds indexes are runtime errors. `array.fill` fills the whole array by
default or the half-open
`[index_from, index_to)` window when bounds are supplied; invalid ranges are
no-ops. The semantic analyzer also allows `array.fill`/`fill()` for
same-local scalar-tree UDT arrays with a same-UDT value; mismatched local UDT
values remain rejected. `array.slice` returns a same-kind shallow window over the parent
array's half-open `[index_from, index_to)` range; slice reads and writes mirror
the parent window, slice insertions widen the window and insert into the parent,
invalid creation bounds return `na`, and later parent mutations that move the
window out of bounds are runtime errors.
`array.concat` requires two arrays of the same kind,
appends `id2` values to `id` in place, and returns `id`. Numeric array
`binary_search/binary_search_leftmost/binary_search_rightmost/abs/min/max/sum/avg/range/median/mode/percentile_nearest_rank/percentile_linear_interpolation/percentrank/covariance/standardize/variance/stdev`
helpers may also be called with method syntax on float and int array receivers.
`every/some` may also be called with method syntax on float, int, and bool
array receivers.
`sort/sort_indices` may also be called with method syntax on float, int, and
string array receivers.
Binary search helpers expect the current array contents to be sorted ascending;
`array.binary_search` returns `-1` when not found, while leftmost/rightmost
return the nearest existing insertion-side index, clamping searches below the
minimum or above the maximum to the nearest valid edge, and return `-1` for
empty arrays. `array.every` and `array.some` are limited to float, int, and bool
arrays; false, zero, and `na` elements are falsey, other numeric values are
truthy, empty arrays return `true` for `every` and `false` for `some`.
`array.abs` allocates a new same-kind array containing the absolute
value of each source element, preserves `na`, and does not mutate the source.
`array.min` and `array.max` ignore `na` elements and accept an optional
zero-based `nth` rank at any integer qualifier, including a value that changes
on each bar. The omitted rank defaults to zero, duplicate values occupy
separate ranks, and empty/all-`na` arrays or `na`, negative, and out-of-range
ranks return `na`. Namespace and method calls support positional and named
`nth` arguments; namespace arguments may also be reordered by name.
`array.range` returns max minus min while ignoring `na` elements.
`array.median` returns the median of non-`na` values. `array.mode` returns the
smallest value among tied most-frequent values and returns `na` when all
remaining values occur only once.
Percentile helpers operate on non-`na` values sorted ascending. Percentages
outside `0..=100`, empty/all-`na` arrays, and invalid percentrank indexes
return `na`.
`array.covariance` requires two same-size numeric arrays, skips pairs where
either side is `na`, and uses a biased population estimate by default; pass
`false` for an unbiased sample estimate.
`array.standardize` allocates a new float array, uses non-`na` values to
calculate mean and population standard deviation, preserves `na` element
positions when at least one numeric value is present, and returns an empty
array for empty/all-`na` arrays.
`array.variance` and `array.stdev` ignore `na` elements and use a biased
population estimate by default; pass `false` for an unbiased sample estimate.
`array.sort` and `array.sort_indices` support float, int, and string arrays,
sort ascending by default, and accept `order.ascending` or `order.descending`.
`na` values and empty string elements sort last in ascending order and first in
descending order. Fixture-backed `array.sort` calls can run in branch and loop
bodies. `array.sort_indices` returns a new int array containing original indexes
in sorted order without modifying the source array. Both ordering helpers also
support concrete same-local or same-imported scalar-tree UDT arrays. Their
optional compile-time `sort_field` is a zero-based integer field index or a
string field name, defaults to field index `0`, and must select a root `int`,
`float`, or `string` field. A UDT array element that is itself `na` raises a
runtime error, while a selected field value may be `na` and follows the
ordinary special-value ordering. `array.reverse` supports
every supported typed array and is fixture-backed in branch and loop bodies for
scalar array values.
`array.join` supports supported scalar typed arrays, defaults the separator
to `,`, uses the default numeric string format, and renders colors as their
normalized integer color values. The semantic analyzer also allows `array.join`
for same-local scalar-tree UDT arrays; those elements render as
`TypeName(field0, field1, ...)`, with `NaN` for `na` elements. Drawing-id,
chart.point, map, and matrix arrays remain outside the join subset. Array assignment passes the runtime array
id by reference; use `array.copy` to allocate an independent array with the same
current element values.
Same-local and same-imported scalar-tree UDT array element identities are
preserved through ternary, `if`, `switch`, `for`, `for...in`, and `while`
results. This includes array/`na` branches, block-local aliases, typed or
inferred declarations, and caller-side array helpers or iteration. Branches
that resolve to different UDT identities are rejected before lowering.

Map support is currently limited to runtime-owned scalar maps, size reads, and
the first mutation/lookup helpers:

```text
map.new<K, V>() -> simple map
map.size(id: map) -> simple int
map.put(id: map, key: K, value: V) -> void
map.get(id: map, key: K) -> series V
map.contains(id: map, key: K) -> series bool
map.clear(id: map) -> void
map.remove(id: map, key: K) -> void
map.copy(id: map) -> simple map
map.keys(id: map<K, V>) -> simple array<K>
map.values(id: map<K, V>) -> simple array<V>
map.put_all(target: map<K, V>, source: map<K, V>) -> void
```

`map.new<K, V>()` accepts `int`, `float`, `bool`, `string`, or `color` for both
template positions and allocates an empty map id. `map.size(id)` returns the
current entry count for a map id. `map.put` inserts or replaces entries,
`map.get` returns the current value or `na` for missing keys, and
`map.contains` returns whether the key is present. `map.clear` removes all
entries from the map id. `map.remove` deletes the entry for a present key and
is a no-op for missing keys. Assignment copies the runtime map id by reference,
while `map.copy` clones the backing store into an independent map id with the
same scalar key/value template. `map.keys` and `map.values` return independent
array snapshots in insertion order. `map.put_all` merges entries from a source
map into a target map with the same scalar key/value template; existing keys
replace values without moving order, and new keys append in source insertion
order. Scalar `map<K,V>` typed declarations are supported with compatible or
`na` initialization and later same-template reassignment. Same-template map
metadata is preserved through ternary, `if`, `switch`, `for`, `for...in`, and
`while` expression results, including `map`/`na` branches and block-local map
aliases; branches with different key/value templates are rejected. These
results can initialize typed or inferred bare-map declarations and can be used
directly by map helpers. Equivalent method
aliases are supported for the same subset:
`id.size()`, `id.put(key, value)`, `id.get(key)`, `id.contains(key)`,
`id.clear()`, `id.remove(key)`, `id.copy()`, `id.keys()`, `id.values()`, and
`id.put_all(source)`. Scalar map history snapshots are supported with
independent historical copies. Scalar map `varip` declarations retain the map id
and backing store across repeated realtime forming updates. Read-only map
helpers can consume map ids passed through user-defined function parameters when
the caller supplies a known scalar map template. Local user-defined functions
and methods also preserve a known scalar map template when returning a direct,
block-local, copied, newly constructed, nested-call, or final control-flow map
result. A generic local UDF can return different templates at different call
sites; callers can consume those results through namespace helpers, history,
`for...in`, or map methods after first binding the result. Direct method chaining
on a call result such as `returnMap().get(key)` remains outside the parser
subset. Bare map declarations and non-scalar map templates remain unsupported.

## TA Built-Ins

Initial signatures:

```text
ta.sma(source: series int/float, length: int-compatible) -> series float
ta.ema(source: series int/float, length: simple integer-compatible) -> series float
```

Next signatures after Phase 1 is stable:

```text
ta.dema(source: series int/float, length: simple integer-compatible) -> series float
ta.tema(source: series int/float, length: simple integer-compatible) -> series float
ta.rma(source: series int/float, length: simple integer-compatible) -> series float
ta.rsi(source: series int/float, length: simple integer-compatible) -> series float
ta.rci(source: series/simple numeric, length: simple integer-compatible) -> series float
ta.macd(source: series int/float, fastlen: simple integer-compatible, slowlen: simple integer-compatible, siglen: simple integer-compatible)
  -> tuple(series float, series float, series float)
ta.tsi(source: series int/float, short_length: simple integer-compatible, long_length: simple integer-compatible) -> series float
ta.cmo(source: series int/float, length: int-compatible) -> series float
ta.cci(source: series int/float, length: int-compatible) -> series float
ta.cog(source: series int/float, length: int-compatible) -> series float
ta.ao() -> series float
ta.bop() -> series float
ta.bb(source: series int/float, length: int-compatible, mult: numeric-compatible)
  -> tuple(series float, series float, series float)
ta.bbw(source: series int/float, length: int-compatible, mult: numeric-compatible) -> series float
ta.kc(source: series int/float, length: int-compatible, mult: simple numeric-compatible, useTrueRange?: bool-compatible)
  -> tuple(series float, series float, series float)
ta.kcw(source: series int/float, length: int-compatible, mult: simple numeric-compatible, useTrueRange?: bool-compatible) -> series float
ta.pivothigh(leftbars: int-compatible, rightbars: int-compatible) -> series float
ta.pivothigh(source: series int/float, leftbars: int-compatible, rightbars: int-compatible) -> series float
ta.pivotlow(leftbars: int-compatible, rightbars: int-compatible) -> series float
ta.pivotlow(source: series int/float, leftbars: int-compatible, rightbars: int-compatible) -> series float
ta.pivot_point_levels(type: series string, anchor: series bool, developing?: series bool) -> float[]
ta.stdev(source: series int/float, length: int-compatible, biased?: bool-compatible) -> series float
ta.variance(source: series int/float, length: int-compatible, biased?: bool-compatible) -> series float
ta.range(source: series int/float, length: int-compatible) -> series float
ta.dev(source: series int/float, length: int-compatible) -> series float
ta.vwma(source: series int/float, length: int-compatible) -> series float
ta.wma(source: series int/float, length: int-compatible) -> series float
ta.hma(source: series int/float, length: int-compatible) -> series float
ta.swma(source: series int/float) -> series float
ta.alma(series: series int/float, length: int-compatible, offset: simple numeric-compatible, sigma: simple numeric-compatible, floor?: simple bool-compatible) -> series float
ta.linreg(source: series int/float, length: int-compatible, offset: simple integer-compatible) -> series float
ta.stoch(source: series int/float, high: series int/float, low: series int/float, length: int-compatible) -> series float
ta.wpr(length: int-compatible) -> series float
ta.cum(source: series/simple numeric) -> series float
ta.max(source: series/simple numeric) -> series float
ta.min(source: series/simple numeric) -> series float
ta.accdist -> series float
ta.iii -> series float
ta.nvi -> series float
ta.obv -> series float
ta.pvi -> series float
ta.pvt -> series float
ta.tr -> series float
ta.vwap -> series float
ta.vwap(source: series/simple numeric) -> series float
ta.vwap(source: series/simple numeric, anchor: bool-compatible) -> series float
ta.vwap(source: series/simple numeric, anchor: bool-compatible, stdev_mult: simple numeric-compatible) -> [series float, series float, series float]
ta.wad -> series float
ta.wvad -> series float
ta.mfi(source: series int/float, length: int-compatible) -> series float
ta.atr(length: simple integer-compatible) -> series float
ta.tr(handle_na?: const bool) -> series float
ta.supertrend(factor: simple numeric-compatible, atrPeriod: simple integer-compatible) -> [series float, series float]
ta.dmi(diLength: simple integer-compatible, adxSmoothing: simple integer-compatible) -> [series float, series float, series float]
ta.sar(start: simple numeric-compatible, inc: simple numeric-compatible, max: simple numeric-compatible) -> series float
ta.change(source: series int/float/bool, length?: int-compatible) -> series float/bool
ta.mom(source: series int/float, length: int-compatible) -> series float
ta.roc(source: series int/float, length: int-compatible) -> series float
ta.correlation(source1: series/simple numeric, source2: series/simple numeric, length: int-compatible) -> series float
ta.covariance(source1: series/simple numeric, source2: series/simple numeric, length: int-compatible) -> series float
ta.median(source: series/simple numeric, length: int-compatible) -> series float
ta.mode(source: series/simple numeric, length: int-compatible) -> series float
ta.percentile_nearest_rank(source: series/simple numeric, length: int-compatible, percentage: simple numeric-compatible) -> series float
ta.percentile_linear_interpolation(source: series/simple numeric, length: int-compatible, percentage: simple numeric-compatible) -> series float
ta.percentrank(source: series/simple numeric, length: int-compatible) -> series float
ta.rising(source: series int/float, length: int-compatible) -> series bool
ta.falling(source: series int/float, length: int-compatible) -> series bool
ta.barssince(condition: series bool) -> series int
ta.valuewhen(condition: series bool, source: series int/float/bool/color, occurrence: int-compatible) -> series source-kind
ta.cross(source1: series/simple numeric, source2: series/simple numeric) -> series bool
ta.crossover(source1: series/simple numeric, source2: series/simple numeric) -> series bool
ta.crossunder(source1: series/simple numeric, source2: series/simple numeric) -> series bool
ta.highest(length: int-compatible) -> series float
ta.highest(source: series int/float, length: int-compatible) -> series float
ta.lowest(length: int-compatible) -> series float
ta.lowest(source: series int/float, length: int-compatible) -> series float
ta.highestbars(length: int-compatible) -> series int
ta.highestbars(source: series int/float, length: int-compatible) -> series int
ta.lowestbars(length: int-compatible) -> series int
ta.lowestbars(source: series int/float, length: int-compatible) -> series int
```

Rules:

- Most window `length` arguments are still `simple int`; reject `series int`
  lengths unless a function is explicitly listed as integer-compatible.
  `ta.pivothigh`/`ta.pivotlow` left/right bar counts accept integer values at
  any implemented qualifier. `ta.change`, `ta.mom`, `ta.roc`,
  `ta.rising`, `ta.falling`, `ta.highest`, `ta.lowest`, `ta.highestbars`,
  and `ta.lowestbars` follow the direct history-read qualifier policy.
- TA source parameters documented as `series int/float` accept numeric series
  sources and evaluate through the runtime's floating-point calculation path.
- `ta.sma` accepts integer-compatible `length`, supports named/reordered
  `source`/`length` argument binding, and uses the same callsite rolling-window
  mean state.
- `ta.ema`/`ta.rma` support named/reordered `source`/`length` argument binding
  and use the same callsite running-average state. Explicit `na` lengths return
  `na` without advancing callsite state.
- `ta.bb` currently accepts integer-compatible `length` and any
  numeric-compatible qualifier for `mult`, returning an all-`na` tuple when
  `mult` is `na`.
- `ta.bbw` uses the same basis/deviation window as `ta.bb` and returns
  `(upper - lower) / basis`; it returns `na` when the window is not ready or
  basis or `mult` is `na`. `ta.bb`/`ta.bbw` support named/reordered
  `source`/`length`/`mult` argument binding, with integer-compatible `length`.
- `ta.kc` returns Keltner Channels as `[ema(source, length), basis +
  ema(span, length) * mult, basis - ema(span, length) * mult]`, where `span`
  defaults to true range and uses `high - low` when `useTrueRange` is `false`;
  `mult` accepts simple numeric-compatible values and an `na` multiplier
  returns an all-`na` tuple.
- `ta.kcw` uses the same Keltner Channel basis/range EMA calculation and
  returns `(upper - lower) / basis`; it returns `na` when inputs are `na`,
  length is non-positive, or basis is zero. `ta.kc`/`ta.kcw` support
  named/reordered `source`/`length`/`mult`/`useTrueRange` argument binding,
  with integer-compatible `length`.
- `ta.dema` returns `2 * ema(source, length) - ema(ema(source, length),
  length)` using independent callsite state. Named/reordered `source`/`length`
  arguments bind to the same EMA-chain state. Explicit `na` length returns
  `na` without advancing the chain state.
- `ta.tema` returns `3 * ema1 - 3 * ema2 + ema3`, where each EMA is the next
  EMA of the previous EMA in the chain, using independent callsite state.
  Named/reordered `source`/`length` arguments bind to the same EMA-chain state.
  Explicit `na` length returns `na` without advancing the chain state.
- `ta.rsi` supports named/reordered `source`/`length` arguments and uses the
  same callsite RMA-smoothed gain/loss state. Explicit `na` length returns
  `na` without advancing state.
- `ta.rci` computes the Rank Correlation Index over a ready rolling source
  window. It assigns ascending one-based price ranks, averages ranks for equal
  values, and returns
  `(1 - 6 * sum((price_rank - time_rank)^2) / (length * (length^2 - 1))) * 100`.
  Named/reordered `source`/`length` arguments bind to the same callsite window.
  The source accepts series or simple numeric values, while length remains
  simple integer-compatible; lengths below two and incomplete or non-finite
  windows return `na`.
- `ta.macd` supports named/reordered `source`/`fastlen`/`slowlen`/`siglen`
  arguments and uses the same callsite EMA-chain state. Explicit `na` lengths
  return an all-`na` tuple.
- `ta.pivothigh`/`ta.pivotlow` support the default-source two-argument forms
  and explicit-source three-argument forms. The default sources are `high` and
  `low` respectively. The current subset accepts integer left/right bar counts
  at any implemented qualifier, supports named/reordered
  `source`/`leftbars`/`rightbars` argument binding, and returns the confirmed
  pivot value `rightbars` bars after the pivot bar, otherwise `na`.
- `ta.pivot_point_levels` returns an 11-element float array ordered as
  `[P, R1, S1, R2, S2, R3, S3, R4, S4, R5, S5]`. The current subset supports
  `Traditional`, `Fibonacci`, `Woodie`, `Classic`, `DM`, and `Camarilla`
  formulas over runtime bars using the caller-provided `anchor` condition. With
  `developing = false`, levels update from the completed period when `anchor`
  is true; with `developing = true`, levels are recalculated from the current
  in-progress period. It does not request higher-timeframe/session data.
- `ta.stdev` defaults `biased` to `true`; `false` uses sample standard
  deviation and returns `na` for windows shorter than two values.
  Named/reordered `source`/`length`/`biased` arguments bind to the same window
  state.
- `ta.variance` uses the same `biased` default and sample/population window
  rules as `ta.stdev`. Named/reordered `source`/`length`/`biased` arguments
  bind to the same window state.
- `ta.range` returns highest minus lowest over the ready rolling window.
  Named/reordered `source`/`length` arguments bind to the same window state.
- `ta.dev` returns the average absolute deviation from the window mean.
  Named/reordered `source`/`length` arguments bind to the same window state.
- `ta.vwma` returns `sum(source * volume) / sum(volume)` over the ready rolling
  window and returns `na` when the volume sum is zero. Named/reordered
  `source`/`length` arguments bind to the same weighted-window state. Its
  `length` argument is integer-compatible.
- `ta.wma` returns a weighted mean where the oldest ready-window value has
  weight `1` and the current value has weight `length`. Named/reordered
  `source`/`length` arguments bind to the same window state. Its `length`
  argument is integer-compatible.
- `ta.hma` composes `ta.wma`-style windows as
  `wma(2 * wma(source, length / 2) - wma(source, length), round(sqrt(length)))`.
  Named/reordered `source`/`length` arguments bind to the same staged window
  state. Its `length` argument is integer-compatible.
- `ta.swma` returns a fixed four-bar symmetric weighted average using weights
  `1, 2, 2, 1`; it returns `na` until the fixed window is ready or when the
  window contains `na`. Named/reordered `source` arguments bind to the same
  fixed-window state.
- `ta.alma` returns the Arnaud Legoux Moving Average using Gaussian weights
  over the ready source window. Optional `floor` floors the offset-derived
  center before weighting. Named/reordered `series`/`length`/`offset`/`sigma`/
  `floor` arguments bind to the same window state. Its `length` argument is
  integer-compatible, `offset` and `sigma` are simple numeric-compatible, and
  `floor` is simple bool-compatible. Explicit `na` offset or sigma returns
  `na`; explicit `na` floor uses the default non-floored center.
- `ta.linreg` fits a least-squares line over the ready source window and
  returns `intercept + slope * (length - 1 - offset)`. Named/reordered
  `source`/`length`/`offset` arguments bind to the same window state. Its
  `length` argument is integer-compatible, while `offset` remains simple
  integer-compatible; explicit `na` offset is treated as 0.
- `ta.cum` returns the cumulative sum of numeric source values from the start of
  execution; a current `na` source returns `na` and resets the next cumulative
  step to the next available source value. Named/reordered `source` arguments
  bind to the same callsite accumulator state.
- `ta.max` and `ta.min` return the all-time maximum/minimum over executed
  non-`na` source values in their callsite state. A current `na` source leaves
  the previous extreme unchanged; if no non-`na` value has executed yet, they
  return `na`. Named/reordered `source` arguments bind to the same callsite
  extreme state.
- `ta.accdist` is a built-in series variable equivalent to cumulative
  Accumulation/Distribution money flow volume:
  `(((close - low) - (high - close)) / (high - low)) * volume`. It returns
  `na` and resets the next cumulative step when `high == low`.
- `ta.iii` is a built-in series variable equivalent to
  `(2 * close - high - low) / ((high - low) * volume)`; it returns `na` when
  the price range or volume is zero.
- `ta.nvi` is a built-in series variable with an initial value of `1.0`; it
  updates by `((close - close[1]) / close[1]) * previous_nvi` only when
  `volume < volume[1]`, and carries the previous value when the current or
  previous close is zero.
- `ta.obv` is a built-in series variable equivalent to
  `ta.cum(math.sign(ta.change(close)) * volume)`.
- `ta.pvi` is a built-in series variable with an initial value of `1.0`; it
  updates by `((close - close[1]) / close[1]) * previous_pvi` only when
  `volume > volume[1]`, and carries the previous value when the current or
  previous close is zero.
- `ta.pvt` is a built-in series variable equivalent to
  `ta.cum((ta.change(close) / close[1]) * volume)`.
- `ta.tr` variable form is true range without first-bar `na` handling; it
  returns `na` until `close[1]` is available.
- `ta.vwap` variable form returns cumulative
  `sum(hlc3 * volume) / sum(volume)` over the runtime bars.
- `ta.vwap(source)` returns cumulative `sum(source * volume) / sum(volume)` in
  its own call-site state. `ta.vwap(source, anchor)` uses the same call-site
  cumulative state and resets it before the current bar when `anchor` is true.
  `ta.vwap(source, anchor, stdev_mult)` returns `[vwap, upper_band, lower_band]`
  using the call-site weighted standard deviation multiplied by `stdev_mult`;
  `stdev_mult` accepts simple numeric-compatible values, and `na` returns an
  all-`na` tuple.
  Named/reordered `source`/`anchor`/`stdev_mult` arguments bind to the same
  VWAP state. These forms return `na` while the cumulative volume is zero.
  Session-derived anchoring is not implemented yet.
- `ta.wad` is a built-in series variable equivalent to cumulative Williams
  Accumulation/Distribution gain using `trueHigh = max(high, close[1])` and
  `trueLow = min(low, close[1])`.
- `ta.wvad` is a built-in series variable equivalent to
  `(close - open) / (high - low) * volume`; it returns `na` when
  `high == low`.
- `ta.change` returns `source - source[length]` for numeric sources and whether
  the value changed for bool sources. Constant lengths record the required
  source history depth, while dynamic integer lengths use guarded runtime
  history reads. Named/reordered `source`/`length` arguments bind to the same
  history-read semantics.
- `ta.mom` returns `source - source[length]`. Constant lengths record the
  required source history depth, while dynamic integer lengths use guarded
  runtime history reads. Named/reordered `source`/`length` arguments bind to
  the same history-read semantics.
- `ta.roc` returns `100 * (source - source[length]) / source[length]` and
  returns `na` when the historical denominator is zero. Constant lengths record
  the required source history depth, while dynamic integer lengths use guarded
  runtime history reads. Named/reordered `source`/`length` arguments bind to
  the same history-read semantics.
- `ta.correlation` returns the Pearson correlation coefficient over the ready
  paired source window and returns `na` while the window is not ready, contains
  `na`, or either source has zero variance. Named/reordered
  `source1`/`source2`/`length` arguments bind to the same paired-window state
  semantics.
- `ta.covariance` returns population covariance over the ready paired source
  window and returns `na` while the window is not ready or contains `na`.
  Named/reordered `source1`/`source2`/`length` arguments bind to the same
  paired-window state semantics.
- `ta.median` sorts the ready source window ascending and returns the middle
  value, or the average of the two middle values for even windows.
  Named/reordered `source`/`length` arguments bind to the same window state.
- `ta.mode` returns the most frequent ready-window value. Ties, including
  windows where every value is unique, resolve to the smallest value.
  Named/reordered `source`/`length` arguments bind to the same window state.
- `ta.percentile_nearest_rank` sorts the ready source window ascending and
  returns the nearest-rank percentile member. It returns `na` while the window
  is not ready, contains `na`, when `percentage` is `na`, or when `percentage`
  is outside `0..=100`.
  Named/reordered `source`/`length`/`percentage` arguments bind to the same
  window state.
- `ta.percentile_linear_interpolation` uses the same ready sorted window and
  interpolates between adjacent ranks. It returns `na` under the same invalid
  window or percentage conditions as `ta.percentile_nearest_rank`.
  Named/reordered `source`/`length`/`percentage` arguments bind to the same
  window state.
- `ta.percentrank` returns the percentage of ready-window values less than or
  equal to the current source value. It returns `na` while the window is not
  ready or contains `na`. Named/reordered `source`/`length` arguments bind to
  the same window state.
- `ta.rising`/`ta.falling` compare the current source against each prior source
  value from offset `1` through `length`, record the required source history
  depth for constant lengths, use retained source history for dynamic integer
  lengths, and return `false` while any required prior value is unavailable or
  `na`. Named/reordered `source`/`length` arguments bind to the same history-read
  semantics.
- `ta.barssince` returns `0` on true conditions, increments after the last true
  condition, and returns `na` before the first true condition. Named
  `condition` arguments bind to the same callsite state semantics.
- `ta.valuewhen` returns the `source` value from the nth most recent true
  condition, where `occurrence = 0` is the most recent match. Series occurrence
  values are evaluated per bar and keep recent-match state up to the runtime
  retention cap. Named/reordered `condition`/`source`/`occurrence` arguments
  bind to those same state slots.
- `ta.highest`/`ta.highestbars` length-only overloads use `high` as the source.
  `ta.lowest`/`ta.lowestbars` length-only overloads use `low` as the source.
- `ta.highest`/`ta.lowest` and `ta.highestbars`/`ta.lowestbars` compare the
  current source with retained source history offsets `1..length - 1`. Constant
  lengths record source history depth as `length - 1`, while dynamic integer
  lengths use retained source history. Named/reordered `source`/`length`
  arguments bind to the same explicit-source or length-only overload semantics.
- `ta.highestbars`/`ta.lowestbars` return the offset to the most recent
  matching extreme in the ready window.
- `ta.cross`/`ta.crossover`/`ta.crossunder` support named/reordered
  `source1`/`source2` arguments and use the same one-bar retained history for
  series operands.
- `ta.tr(handle_na)` supports named/reordered `handle_na` arguments and uses
  the same current/previous OHLC true-range path as the positional form.
- `ta.atr` supports named/reordered `length` arguments and uses the same
  callsite RMA-smoothed true-range state. Explicit `na` length returns `na`
  without advancing state.
- `ta.supertrend` returns `[line, direction]`, where direction is `-1` for the
  uptrend line and `1` for the downtrend line. The current subset follows the
  TradingView band update rules using the runtime's existing RMA-style ATR
  behavior. Named/reordered `factor`/`atrPeriod` arguments bind to the same
  callsite trend state. An explicit `na` factor or `atrPeriod` returns
  `[na, na]`.
- `ta.dmi` returns `[+DI, -DI, ADX]`. The current subset uses Wilder/RMA-style
  smoothing from the first executed bar, reuses `ta.tr(true)` true range
  semantics, and returns an all-`na` tuple for non-positive or `na` lengths.
  Named/reordered `diLength`/`adxSmoothing` arguments bind to the same callsite
  smoothing state.
- `ta.sar` supports the three-argument Parabolic SAR form. It initializes from
  the previous bar, clamps against the previous two highs/lows when available,
  and returns `na` until the callsite has enough prior OHLC data to initialize.
  The `start`/`inc`/`max` parameters accept simple numeric-compatible values;
  an explicit `na` parameter returns `na`.
  Named/reordered `start`/`inc`/`max` arguments bind to the same callsite SAR
  state.
- `ta.mfi` supports the two-argument Money Flow Index form using the supplied
  source, current `volume`, and ready positive/negative money-flow windows. It
  returns `na` before the window is ready, when source/volume is `na`, for
  non-positive lengths, or when both flow sums are zero. Named/reordered
  `source`/`length` arguments bind to the same money-flow windows. Its `length`
  argument is integer-compatible.
- `ta.tsi` returns the True Strength Index in the TradingView-style `[-1, 1]`
  range. The current subset double-smooths source momentum and absolute
  momentum with short then long EMA stages and returns `na` when prior source
  data is unavailable, lengths are non-positive, or the smoothed absolute
  momentum denominator is zero. Named/reordered
  `source`/`short_length`/`long_length` arguments bind to the same callsite
  smoothing state.
- `ta.cmo` returns the Chande Momentum Oscillator as `100 * (sum(up) -
  sum(down)) / (sum(up) + sum(down))` over ready rolling source-change windows.
  It returns `na` before the window is ready, for non-positive lengths, or when
  the denominator is zero. Named/reordered `source`/`length` arguments bind to
  the same source-change windows. Its `length` argument is integer-compatible.
- `ta.cci` returns the Commodity Channel Index as `(source - sma(source,
  length)) / (0.015 * ta.dev(source, length))`. It returns `na` before the
  rolling window is ready, for non-positive lengths, when source is `na`, or
  when mean absolute deviation is zero. Named/reordered `source`/`length`
  arguments bind to the same rolling window. Its `length` argument is
  integer-compatible.
- `ta.cog` returns the Center of Gravity as `-sum(source[i] * (i + 1)) /
  math.sum(source, length)` over the ready source window. It returns `na` before
  the rolling window is ready, for non-positive lengths, when source is `na`, or
  when the source sum is zero. Named/reordered `source`/`length` arguments bind
  to the same rolling window. Its `length` argument is integer-compatible.
- `ta.ao` returns the Awesome Oscillator as `sma(hl2, 5) - sma(hl2, 34)`.
  It returns `na` until both rolling windows are ready or when either window
  contains `na`.
- `ta.bop` returns the Balance of Power as `(close - open) / (high - low)`.
  It returns `na` when any OHLC input is `na` or the high-low range is zero.
- `ta.stoch` supports the four-argument stochastic oscillator form using ready
  rolling `high`/`low` windows. It returns `na` before the window is ready, when
  either window contains `na`, for non-positive lengths, or when the high-low
  range is zero. Named/reordered `source`/`high`/`low`/`length` arguments bind
  to the same high/low windows.
- `ta.wpr` supports the single-argument Williams %R form over ready rolling
  `high`/`low` windows and current `close`. It returns `na` before the window is
  ready, for non-positive lengths, or when the high-low range is zero.
  Named/reordered `length` arguments bind to the same high/low windows.
- Stateful TA functions require callsite ids.
- Tuple-returning functions require tuple lowering before execution.
- Numerical formulas must be fixture-tested with tolerance.

## Color

```text
color.new(color: color-compatible, transp?: simple integer-compatible) -> same qualifier color
color.rgb(red: numeric-compatible, green: numeric-compatible, blue: numeric-compatible, transp?: numeric-compatible) -> color with strongest qualifier
color.r(color: color-compatible) -> float with same qualifier
color.g(color: color-compatible) -> float with same qualifier
color.b(color: color-compatible) -> float with same qualifier
color.t(color: color-compatible) -> float with same qualifier
color.from_gradient(value: numeric-compatible, bottom_value: numeric-compatible, top_value: numeric-compatible, bottom_color: color-compatible, top_color: color-compatible) -> color with strongest qualifier
```

Named colors include fixture-backed official RGB values for the 17 built-in
TradingView color constants: `color.aqua`, `color.black`, `color.blue`,
`color.fuchsia`, `color.gray`, `color.green`, `color.lime`, `color.maroon`,
`color.navy`, `color.olive`, `color.orange`, `color.purple`, `color.red`,
`color.silver`, `color.teal`, `color.white`, and `color.yellow`.
Hex color literals in `#RRGGBB` and `#RRGGBBAA` form are accepted as const
colors.
`color.new` defaults `transp` to 0 when omitted or explicitly `na` and clamps
transparency to the 0-100 range. Fully opaque results preserve the exact RGB
color value.
`color.rgb` rounds channel inputs to integer RGBA channels, clamps RGB channels
to 0-255, and clamps transparency to 0-100. Fully opaque results preserve the
exact RGB color value. If any supplied channel or transparency argument is
`na`, it returns `na`.
`color.r`, `color.g`, `color.b`, and `color.t` return `na` for `na` colors;
`color.t` returns transparency on the 0-100 scale.
`color.from_gradient` linearly interpolates RGBA channels between the two
colors, clamps values outside the numeric range to the exact endpoint color,
and returns `na` when any supplied numeric or color input is `na`. Equal
bottom/top values return the top color.

Hex color literals are parsed by the syntax layer and lowered to the runtime's
single normalized `Color` representation.

## String

```text
str.length(string: string-compatible) -> int with same qualifier
str.upper(string: string-compatible) -> string with same qualifier
str.lower(string: string-compatible) -> string with same qualifier
str.contains(source: string-compatible, str: string-compatible) -> bool with strongest qualifier
str.startswith(source: string-compatible, str: string-compatible) -> bool with strongest qualifier
str.endswith(source: string-compatible, str: string-compatible) -> bool with strongest qualifier
str.pos(source: string-compatible, str: string-compatible) -> int with strongest qualifier
str.substring(source: string-compatible, begin_pos: int-compatible, end_pos?: int-compatible)
  -> string with strongest qualifier
str.trim(string: string-compatible) -> string with same qualifier
str.repeat(source: string-compatible, repeat: int-compatible, separator?: string-compatible)
  -> string with strongest qualifier
str.replace(source: string-compatible, target: string-compatible, replacement: string-compatible, occurrence?: int-compatible)
  -> string with strongest qualifier
str.replace_all(source: string-compatible, target: string-compatible, replacement: string-compatible)
  -> string with strongest qualifier
str.tonumber(string: string-compatible) -> float with same qualifier
str.tostring(value: int|float|bool|string|float-array|int-array|bool-array|string-array|float-matrix|int-matrix|bool-matrix|string-matrix|na, format?: string-compatible)
  -> string with strongest qualifier
str.format(formatString: string-compatible, arg0?: int|float|bool|string|float-array|int-array|bool-array|string-array|na, ...)
  -> string with strongest qualifier
str.match(source: string-compatible, regex: string-compatible)
  -> string with strongest qualifier
str.split(source: string-compatible, separator: string-compatible)
  -> simple string-array
str.format_time(time: int-compatible, format?: string-compatible, timezone?: string-compatible)
  -> string with strongest qualifier
```

Supported `str.*` helpers return `na` for `na` inputs unless documented
otherwise below.
`str.length` counts Unicode scalar values.
`str.upper` and `str.lower` convert ASCII letters only and preserve non-ASCII
characters unchanged in the current fixture-backed subset.
`str.contains`, `str.startswith`, and `str.endswith` return `true` for empty
substring arguments.
`str.pos` returns `na` when no match is found or when the source is `na`;
empty or `na` substring arguments return 0. `str.substring` treats `na`
`begin_pos` as 0 and omitted, `na`, or too-large `end_pos` as the string
length; invalid ranges are runtime errors.
`str.trim` removes leading and trailing ASCII whitespace only and returns an
empty string when its source is `na` or consists entirely of trimmed
whitespace. `str.repeat` defaults `separator` to an empty string, returns an
empty string for repeat 0, and errors for negative counts or results over
40,960 characters.
`str.replace` replaces one non-overlapping occurrence, defaulting `occurrence`
to 0. `str.replace_all` replaces all non-overlapping occurrences. Empty
targets replace zero-width character boundaries. Replacement results over
40,960 characters are runtime errors.
`str.tonumber` accepts strings containing ASCII digits, an optional leading
sign, at most one decimal point, and optional scientific notation exponent. It
returns `na` for invalid formats, `na` inputs, and non-finite parsed results.
`str.tostring` supports scalar int, float, bool, string, `na`, fixture-covered
float-, int-, bool-, and string-array values, and float/int/bool/string matrices.
Matrices render as an outer bracketed list of bracketed rows, preserve empty
row/column shapes, and apply numeric formats to each numeric cell. Color
matrices, UDT and tuple values, and color, drawing-id, chart.point, and UDT
arrays remain outside the argument subset. Numeric formatting supports the
default `#.########`, `format.price` as the default format, and fixture-covered
custom patterns using `#`, `0`, `.`, `,`, and trailing `%` tokens.
`format.percent` rounds the original value to two fractional digits and appends
`%` without rescaling it, whereas a trailing `%` token in a custom pattern
multiplies the value by 100. `format.volume` rounds values below 1000 to whole
numbers and abbreviates larger magnitudes with K/M/B/T suffixes and up to three
fractional digits, including threshold promotion after rounding.
`format.mintick` rounds to the nearest multiple of the fixed
`syminfo.mintick = 0.01` subset with ties rounded up, then preserves the
corresponding two fractional digits. All predefined formats apply per cell to
supported numeric arrays and matrices.
`str.format` supports indexed placeholders such as `{0}`, numeric placeholders
such as `{0,number,#.00}`, and fixture-covered `integer`, `percent`, and
`currency` number presets, plus fixture-covered float-, int-, bool-, and
string-array placeholders. The `percent` preset uses `#,###%`: it multiplies
the value by 100, rounds to a whole number, inserts grouping separators, and
appends `%`; custom percent placeholders keep their explicitly requested
fractional precision. Matrix values, UDT and tuple values, plus color,
drawing-id, chart.point, and UDT arrays remain outside the `str.format`
argument subset. It also supports fixture-covered UTC timestamp placeholders
such as `{0,date,yyyy-MM-dd}` and `{0,time,HH:mm:ssZ}`. Quoted
literal sequences between apostrophes are not parsed as placeholders, and `''`
emits one literal apostrophe. The UTC timestamp placeholder subset shares the
same fixture-covered `D`, `E`, `w`, and `W` token behavior as
`str.format_time`, including fixture-covered `h`/`hh` 12-hour clock,
millisecond, and AM/PM tokens, but does not accept a timezone argument. Missing
placeholder indexes remain literal text. Date/time patterns preserve quoted literals and
render each doubled apostrophe `''` as one literal apostrophe, including inside
quoted text. Unmatched braces are runtime errors. Non-numeric
format modifiers outside the fixture-covered subset are not yet claimed.
`str.match` uses the linear-time Rust regex engine for the fixture-covered Pine
subset. The predefined `\d`/`\D`, `\w`/`\W`, and `\s`/`\S` classes and
`\b`/`\B` word boundaries use ASCII semantics by default, including inside
character classes. Global or scoped `(?U)` enables their Unicode-aware
semantics, and `(?-U)` disables them again; Pine's `U` flag does not change
quantifier greediness. The `\h`/`\H` classes use Pine's fixed Unicode
horizontal-whitespace set regardless of `U`, including space, tab, nonbreaking
space, U+1680, U+180E, U+2000 through U+200A, U+202F, U+205F, and U+3000. It
also supports `\v`/`\V` using Pine's fixed vertical-whitespace set regardless
of `U`: LF, VT, FF, CR, U+0085, U+2028, and U+2029. Both horizontal and
vertical classes can be nested in character classes and remain literal in
quoted regions. The `\R` matcher recognizes the same seven vertical characters
and consumes CRLF as one line break. It is independent of `U`, remains literal
in quoted regions, and is invalid inside a character class, matching Pine's
Java regex behavior. It also supports the Java/Pine POSIX property names `Lower`,
`Upper`, `ASCII`, `Alpha`, `Digit`, `Alnum`, `Punct`, `Graph`, `Print`, `Blank`,
`Cntrl`, `XDigit`, and `Space` for `\p{...}` and `\P{...}`. These classes use
their ASCII definitions by default and their Unicode compatibility definitions
under global or scoped `(?U)`; `(?-U)` restores ASCII behavior. POSIX names are
case-sensitive by default and case-insensitive under `(?U)`. The Java/Pine
character method properties `javaLowerCase`, `javaUpperCase`,
`javaAlphabetic`, `javaIdeographic`, `javaTitleCase`, `javaDigit`,
`javaDefined`, `javaLetter`, and `javaLetterOrDigit` are also supported with
exact case-sensitive names for `\p` and `\P`, including nested character
classes and quoted preservation. They map to the corresponding Unicode
lowercase, uppercase, alphabetic, ideographic, titlecase, decimal-digit,
defined, letter, and letter-or-decimal-digit sets. Their membership is
independent of `(?U)`, while active `(?i)` applies Unicode case closure as in
Java. The remaining character method properties are
`javaJavaIdentifierStart`, `javaJavaIdentifierPart`,
`javaUnicodeIdentifierStart`, `javaUnicodeIdentifierPart`,
`javaIdentifierIgnorable`, `javaSpaceChar`, `javaWhitespace`,
`javaISOControl`, and `javaMirrored`. The Java identifier sets include their
letter-number, currency, connector, digit, mark, and ignorable rules, while
the Unicode sets use `ID_Start`/`ID_Continue` plus Java's ignorable controls
and format characters. `javaSpaceChar` covers the separator categories;
`javaWhitespace` additionally covers TAB through CR and U+001C–U+001F but
excludes NEL, no-break space, figure space, and narrow no-break space.
`javaISOControl` covers U+0000–U+001F and U+007F–U+009F, and
`javaMirrored` follows the Unicode bidi-mirrored property. They share the same
exact-name, complement, class, quote, case, and `U`-independent behavior.
Other Unicode property references retain their ordinary Unicode behavior.
Pine/Java Unicode block properties are supported in `\p{InBlockName}` and
`\p{Block=BlockName}` form, together with their `\P` complements, canonical
no-space names, and Java public-field aliases. They use the Unicode 16.0 block
ranges and are independent of `(?U)`; script and general-category properties
continue through the regex engine unchanged. Block properties can be nested in
character classes and remain literal in quoted regions. It also supports
`\Q...\E` literal quoting inside or outside character classes, including quoted
whitespace and `#` in verbose mode; an omitted closing `\E` quotes through the
end of the pattern. In verbose `(?x)` mode, Java/Pine ignores only ASCII space,
tab, LF, VT, FF, and CR; non-ASCII Unicode whitespace remains a literal atom
inside or outside character classes. Unescaped `#` comments end at LF, CR, NEL,
line separator, or paragraph separator. LF and CR are then ignored as ASCII
trivia, the three Unicode terminators remain literal, and VT/FF inside a comment
do not terminate it. Escaped and quoted whitespace or `#` remains literal, and
global/scoped `x` state is preserved. Fixed-width four-hex-digit Unicode
references such as `\u2014` work inside and outside character classes,
consume exactly four digits,
and remain literal inside quoted regions. Two-digit `\xNN` and braced
`\x{...}` references are also supported; the fixed form consumes exactly two
hex digits, the braced form accepts leading zeros around a Unicode scalar, and
surrogate code-unit references match no scalar value. Both spellings remain
literal in quoted regions. Java/Pine `\N{UNICODE CHARACTER NAME}` references
resolve Unicode 16.0 names case-insensitively, with Java's surrounding ASCII
whitespace trimming and C0/C1 control names. Java-generated CJK unified
ideograph, Hangul syllable, Tangut, and Tangut Supplement hexadecimal names are
also supported across their Unicode 16.0 assigned ranges. They work inside or
outside classes, participate in ranges and active case modes, and remain
literal in quoted regions. Loose missing-space, repeated-space, underscore,
unknown, leading-zero algorithmic, and canonical Unicode CJK/Hangul spellings
that Java does not recognize remain invalid. The fixed `\e`
escape-character reference and
`\cX` control reference are also supported inside and outside character
classes. A control reference consumes one Unicode scalar and applies Java's
`XOR 0x40` mapping; verbose mode skips its intervening ASCII whitespace and
comments, and quoted spellings remain literal. Java/Pine octal references are
supported in `\0n`, `\0nn`, and `\0mnn` form: at least one octal digit is
required, a third digit is consumed only when the first is `0..3`, verbose
trivia between digits is ignored, and class, quote, and case modes are
preserved. Java/Pine character classes may use `]` as their first literal atom,
including after a leading `^`, verbose-mode ASCII whitespace or comments, and
an empty `\Q\E` quote. Such leading closers are normalized without changing
quoted closers, negation, or the active case mode. A `~` inside a Java/Pine
character class is always a literal atom, including adjacent `~~`, escaped or
quoted forms, nested classes, range endpoints, and active case modes; it does
not expose Rust's symmetric-difference operator. Tildes outside classes retain
their literal behavior. A backslash before any non-alphanumeric ASCII
character quotes that character as a Java/Pine literal inside or outside a
class. This includes punctuation, controls and whitespace, verbose-mode `\#`
and `\ `, nested classes, and active case modes; unsupported alphabetic
escapes remain errors. Inside character classes, raw hyphens follow Java/Pine
range parsing rather than Rust's character-class
difference operator. This preserves literal leading/trailing hyphens,
hyphen-start and hyphen-end ranges, nested classes, quoted or escaped range
atoms, intersections (including verbose trivia between `&&`), and active case
modes. Illegal descending ranges and set-valued range endpoints remain runtime
regex errors. Raw ampersands use Java/Pine class parsing across single literal
atoms, leading or trailing empty pairs, and linear odd/even runs, including
verbose-separated pairs, nested classes, quoted or escaped atoms, single ranges
or sets, and active case modes. A leading empty intersection such as `[&&]`
remains a regex error. Direct odd-run continuations after a mixed predicate or
prior intersection preserve Java's mutable BitClass membership and recursive
right-hand-side scope instead of inheriting Rust's different set algebra,
including repeated empty pairs before a later literal or non-empty
intersection and range-start continuations that carry the same mutable BitClass
through later ranges, nested predicates, escaped or ordinary literals, and
subsequent intersections. Outside character classes, global or scoped `(?i)` applies Pine's
ASCII-only case folding to ordinary and
`\Q...\E`-quoted literals plus `\uHHHH`/`\x` references. Lowercase `(?u)`
independently enables Unicode-aware folding when `i` is active without changing
the default-ASCII predefined or POSIX class sets; those expansions retain their
own folding boundary even inside a larger character class. `(?U)` enables
Unicode character classes and implies `u`, `(?-u)` disables Unicode folding
without disabling Unicode classes, and `(?-U)` disables both. The same active
case mode applies to character-class literals and ranges before negation and
intersections, including `\Q...\E` atoms and `\uHHHH`/`\x` references.
`(?-i)` and scoped groups restore their enclosing or default modes. General
Unicode properties retain their Unicode case behavior, while Unicode block
membership remains exact under either case mode. Because `str.match`
performs one initial match search with no reusable Matcher state, Pine's `\G`
previous-match anchor
is equivalent to the absolute source start for this API. It is independent of
multiline mode, remains literal when quoted, and is invalid in a character
class. By default, `$`
and `\Z` match either at the absolute end or immediately before a final `\n`,
without including that line terminator in the returned substring; `\z` matches
only the absolute end. Global or scoped `(?m)` gives `$` multiline behavior,
and `(?-m)` restores the default. A default `.` excludes Pine's full line
terminator set: LF, CR (including CRLF), U+0085, U+2028, and U+2029. Global or
scoped `(?s)` lets `.` match those characters, and `(?-s)` restores the
default. Global or scoped `(?d)` enables Java/Pine UNIX-lines mode: only LF is
treated as a line terminator by `.`, `^`, `$`, and `\Z`; `(?-d)` restores the
surrounding mode. Dotall `s` still takes precedence for `.`, `\R` remains the
full line-break matcher, and escaped, character-class, and `\Q...\E`-quoted
dots remain literal. It
returns the first matched substring, an empty string when there is no match,
`na` for `na` inputs, and a runtime error for invalid regex patterns.
Backreferences, lookaround, atomic groups, possessive quantifiers, and other
backtracking-dependent Pine regex constructs remain outside this linear-time
subset.
`str.split` splits by a literal separator and returns a string array. Empty
separators split the source into Unicode scalar values. It returns `na` for
`na` inputs and errors if the result would exceed 100,000 array elements.
`str.format_time` supports UNIX timestamps in milliseconds and UTC/GMT/numeric
fixed-offset or IANA timezone strings such as `UTC+4`, `GMT-5`, `+05:30`, and
`America/New_York`. IANA offsets are resolved at the supplied timestamp, so
DST and local date rollover are reflected in the formatted value. A `na`
timestamp is replaced with `0` and formats the UNIX epoch. Omitted or `na`
`format` defaults to `yyyy-MM-dd'T'HH:mm:ssZ`; omitted or `na` `timezone`
defaults to UTC. Supported tokens include `y`/`Y`, `M`, `d`, `H`, `D`, `E`,
`w`, `W`, `h`, `m`, `s`, `S`, `a`, `Z`, short `z`/`zz`/`zzz`, and
single-quoted literals.
`D` renders the day of the year with optional zero-padding, `E` renders short
or full weekday names, `w` renders the current ISO week-of-year subset, and `W`
renders the `1..5` week-of-month value from seven-day day-of-month groups, both
with optional zero-padding. Short `z` tokens render timestamp-specific IANA
abbreviations such as `EST`/`EDT`, `UTC` for zero offset, or canonical
`GMT±HH:mm` text for other fixed offsets. Full localized `zzzz` names and
exchange timezone defaults remain unsupported. Quoted literals can contain
doubled apostrophes, and `''`
outside a quoted block also renders one literal apostrophe. `h` renders the
12-hour value in the `0..11` range, and `hh` adds a leading zero. `S` renders the
complete `0..999` millisecond value, while `SS` and `SSS` add leading zeroes to
a minimum width of two or three without truncating larger values.

## Math

Phase 1 may include only the math functions required by fixtures.

Supported constants:

```text
math.e -> const float
math.pi -> const float
math.phi -> const float
math.rphi -> const float
```

Recommended first set:

```text
math.abs(number: numeric|na) -> same numeric kind and qualifier for numeric args; na for na args
math.max(a: numeric|na, b: numeric|na, ...) -> promoted numeric kind and strongest qualifier
math.min(a: numeric|na, b: numeric|na, ...) -> promoted numeric kind and strongest qualifier
math.avg(number: numeric|na, ...) -> float with strongest qualifier
math.floor(number: numeric|na) -> int with same qualifier
math.ceil(number: numeric|na) -> int with same qualifier
math.trunc(number: numeric|na) -> int with same qualifier
math.sqrt(number: numeric|na) -> float with same qualifier
math.cbrt(number: numeric|na) -> float with same qualifier
math.log(number: numeric|na) -> float with same qualifier
math.log10(number: numeric|na) -> float with same qualifier
math.exp(number: numeric|na) -> float with same qualifier
math.acos(number: numeric|na) -> float with same qualifier
math.asin(number: numeric|na) -> float with same qualifier
math.atan(number: numeric|na) -> float with same qualifier
math.sign(number: numeric|na) -> float with same qualifier
math.todegrees(radians: numeric|na) -> float with same qualifier
math.toradians(degrees: numeric|na) -> float with same qualifier
math.sin(number: numeric|na) -> float with same qualifier
math.cos(number: numeric|na) -> float with same qualifier
math.tan(number: numeric|na) -> float with same qualifier
math.pow(base: numeric|na, exponent: numeric|na) -> float with strongest qualifier
math.hypot(number1: numeric|na, number2: numeric|na) -> float with strongest qualifier
math.round(number: numeric|na) -> int with same qualifier
math.round(number: numeric|na, precision: int|na) -> float with strongest qualifier
math.round_to_mintick(number: numeric|na) -> float with same qualifier
math.random(min?: numeric|na, max?: numeric|na, seed?: simple integer-compatible) -> series float
math.sum(source: series/simple numeric|na, length: int-compatible) -> series float
```

Each added math function must declare its coercion and `na` behavior.

Current Phase 4 behavior:

- `math.e`, `math.pi`, `math.phi`, and `math.rphi` evaluate as const floats.
- `math.abs` preserves int/float kind and qualifier for numeric inputs.
  Const-or-series `na` inputs return `na`; direct untyped `na` results still
  need a typed numeric consumer such as `float(...)` before numeric-only output
  calls.
- `math.avg` accepts one or more numeric-or-`na` args and returns their average
  as a float. Const-or-series `na` inputs return `na`.
- `math.floor`, `math.ceil`, and `math.trunc` return int values with the
  argument qualifier; const-or-series `na`, non-finite, or out-of-range float
  results return `na`.
- `math.sqrt`, `math.cbrt`, `math.log`, `math.log10`, `math.exp`,
  `math.acos`, `math.asin`, `math.atan`, `math.sign`, `math.todegrees`,
  `math.toradians`, `math.sin`, `math.cos`, `math.tan`,
  `math.round_to_mintick`, `math.pow`, and `math.hypot` return float values
  and preserve or promote qualifiers from their arguments. The one-argument
  helpers, `math.round_to_mintick`, `math.pow`, and `math.hypot` return `na`
  for const-or-series `na` inputs.
- `math.round` returns an int when `precision` is omitted, with ties rounding
  up; with `precision`, it returns a float rounded to that many decimal places.
  Const-or-series `na` number or precision inputs return `na`.
- `math.round_to_mintick` rounds to the nearest multiple of the current
  `syminfo.mintick` subset value, with ties rounding up.
- `math.random` returns a deterministic pseudorandom `series float` sequence
  per callsite. Omitted `min`/`max` default to `0` and `1`; seeded calls are
  reproducible for the same callsite and seed. Explicit `na` seed uses the
  unseeded callsite sequence. Invalid or non-finite ranges return `na`;
  const-or-series `na` min/max inputs return `na`.
- `math.sum` returns the rolling sum of `source` over a ready integer-compatible
  `length` window; it returns `na` for invalid lengths, until the window is
  ready, or when the window contains const-or-series `na`.
- `math.max` and `math.min` require at least two numeric-or-`na` args and
  accept variadic numeric-or-`na` args. Const-or-series `na` inputs return `na`.
- `math.max` and `math.min` return int only when all args are int; otherwise they return float.
- All selected math functions return `na` if any required numeric input is `na`.
