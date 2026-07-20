# Architecture

This document defines the long-term architecture for Pine Compat Runtime.

The project should be built as a Rust core with thin bindings for other
environments. The core owns parsing, semantic analysis, intermediate
representations, runtime execution, built-ins, diagnostics, and output
normalization. Host applications should not need to understand parser internals
or Pine-specific execution details.

## High-Level Pipeline

```text
Pine source
  -> lexer
  -> parser
  -> AST
  -> semantic analyzer
  -> HIR
  -> MIR / bytecode
  -> bar-by-bar VM
  -> normalized output
```

Each stage should expose diagnostics with source spans. A later stage must not
hide errors from an earlier stage; it should add context.

## Crates

### `pine-syntax`

Owns source handling, tokens, parser, AST, and syntax diagnostics.

Responsibilities:

- Preserve exact source spans for tokens and AST nodes.
- Parse version declarations, statements, expressions, blocks, function calls,
  named arguments, declarations, reassignment, history references, and comments.
- Provide recoverable diagnostics where possible.
- Avoid runtime or host dependencies.

Recommended approach:

- Hand-written lexer or `logos` lexer.
- Hand-written statement parser.
- Pratt parser for expressions.

### `pine-sema`

Owns semantic analysis.

Responsibilities:

- Validate the closed Pine v1-v6 dialect and classify script mode before
  ordinary call analysis.
- Resolve names and scopes.
- Infer value kind and qualifier.
- Validate declaration and reassignment rules.
- Validate supported language features.
- Emit compatibility reports for unsupported features.
- Lower AST into HIR.

The analyzer is the boundary where unsupported features should become explicit
diagnostics instead of runtime surprises.

Version and legacy-mode admission are owned by `pine-sema::legacy`. Missing
directives select implicit v1, invalid or conflicting source-graph versions
halt before ordinary semantic analysis, and v1-v4 strategy declarations or
`strategy.*` references are stopped before broker-capable HIR can be produced.
The same source policy initializes `CompatibilityReport`, so all hosts project
one validated version, origin, dialect, script mode, and legacy report model.
Phase 2 adds the reusable translation framework. A sorted, version-ranged rule
catalog is consulted only as a scoped fallback after user declarations. Exact
matches are validated using canonical built-in signatures, recorded with the
original source span, and stored in a source-context/span-keyed lowering plan;
HIR and runtime dispatch therefore see only canonical or inaccessible internal
names. Focused input, output, expression, security, and overload binders remain
separate from exact aliases, and each unsupported shape fails closed. Legacy
translation and emulation reports are deterministically sorted and
deduplicated before leaving semantic analysis.

Phase 3 admits only Pine v4 `study(...)` declarations. A historical signature
binder canonicalizes the supported declaration subset to named `indicator`
arguments and stores argument-name reshaping in the source-context/span-keyed
lowering plan. `resolution`, `resolution_gaps`, and unmapped declaration
options fail before HIR. The first v4-only exact aliases (`sma`, `ema`, `bb`,
`crossover`, and `abs`) reuse canonical analysis/runtime implementations; tuple
element queries also consume the recorded canonical call name. Version-sensitive
canonical call surfaces such as session-bearing `time(...)` are guarded until
their focused legacy semantics phase.

Phase 4 adds a focused Pine v4 input binder. Version-gated input type constants
resolve to opaque legacy-only markers, historical overload tables bind their
own positional and named order, and the lowering plan can now keep-and-rename
or drop individual call arguments. The obsolete `type` argument is dropped
while the original call expression retains its callsite allocation; HIR,
runtime metadata, and host overrides therefore consume only canonical
`input.*` names. The v4 integer float-metadata exception is applied only to the
legacy validation view, so modern input qualifier and argument rules are not
widened.

Phase 5 adds a focused Pine v4 output binder for the initial ten indicator
output families. Historical argument tables remove `transp` into an internal
HIR marker, validate exact primitive plot/hline style ordinals, and retain all
canonical visual arguments without synthesizing user-visible calls. Runtime
normalization applies v4 defaults, clamps input transparency, preserves `na`
and embedded alpha, and exposes bar-aligned visual series plus common metadata.
Modern v5/v6 output signatures and unique style types remain unchanged.

Phase 6 adds result-affecting expression compatibility: strict internal `iff`
evaluation, structural `offset` history lowering, type-directed historical
`rsi` overloads, and version-selected logical/session defaults. Phase 7 adds a
focused v1-v4 `security` binder. It validates historical positional/named
signatures and merge constants, reuses the request-expression analyzer, and
lowers accepted calls to inaccessible HIR dispatch names that encode gaps and
lookahead policies. Hidden span arguments preserve the original full legacy
call for provider failures. The modern `request.security` merge surface is not
widened by this routing. Declaration-level `study(resolution=...)` remains a
focused unsupported program-context feature rather than being approximated by
wrapping the AST in a request call.

Phase 8 admits the fixture-backed v3 declaration/input/output surface and
pre-v4 aliases, with a focused constraint pass for untyped `na`. Phase 9 admits
implicit v1 and explicit v2 indicators. Its declaration resolver activates a
bounded graph only for self/forward-dependent global scalars, predeclares one
canonical symbol per active node, and records a stable lowering order. Removed
bool/numeric conversions are source-span keyed semantic decisions that lower
to ordinary canonical `float`/`bool` calls. Neither mechanism adds a legacy
execution engine: runtime dispatch continues to consume canonical HIR.

Phase 10 makes the host projection testable as one contract. CLI owns separate
registries for runtime and complete legacy analysis goldens; Python and WASM
consume the same files, while a static parity guard requires both assertions
for every manifest entry. Source dialect remains the only legacy semantic
selector. No host adapter owns a translation table, policy override, or source
migration step.

Phase 11 adds a release-evidence layer without adding another execution path.
`tests/fixtures/legacy/release_profiles.tsv` owns the sorted v1-v4 release
fixture registry, maturity, bar/request profile, realtime policy, provenance,
and resource ceiling. The public runtime integration test loads that manifest
and proves source-version selection, complete runtime-fixture coverage,
historical/incremental/realtime behavior, MTF provider behavior, and bounded
retained storage. `scripts/profile_legacy_release.py` measures the same rows
through the CLI boundary. These are verification consumers of the semantic HIR
and runtime, not a second translator or host-specific compatibility switch.

The semantic compile cache includes `LEGACY_TRANSLATOR_REVISION` in every key.
Catalog or translation-semantics changes increment that revision so cached
analysis cannot cross translator revisions. Source name and exact source text,
including its explicit directive or implicit-v1 absence, remain part of the
same key; a focused cache test proves identical script bodies in implicit v1
and explicit v2 occupy separate entries.

The semantic implementation keeps orchestration separate from focused tree
walkers. `modules.rs` owns module-graph validation while
`modules/side_effects.rs` owns side-effect and expression visitation;
`analyzer/context.rs` owns analyzer state and allocation while constant and
history-offset expression evaluation lives in `analyzer/context/const_eval.rs`;
`analyzer/expressions/resolution.rs` owns canonical and scoped legacy value
resolution while `analyzer/expressions.rs` retains expression traversal;
`lowering/mod.rs` owns the lowering entrypoints while reassignment collection
and UDT parameter resolution live in dedicated lowering modules. Pure-series
identity keeps its UDT field/value traversal in
`lowering/pure_series/user_types.rs`. `scripts/check_structure.py` applies
tighter line budgets to these split hotspots so new responsibilities continue
to land in focused child modules.

Phase J introduces a source graph scaffold and the first executable import
subset. Public semantic analysis can now be driven by `AnalysisInput`, which
contains a root `SourceFile` and an optional deterministic list of
host-provided library sources. `SourceGraph` assigns stable `SourceId` values
with root source id `0` and library source ids sorted by import key, while each
source unit keeps a diagnostic display name. Library keys are normalized by
trimming outer whitespace, reject empty or whitespace/control-containing keys,
and duplicate keys are rejected before analysis. This model is intentionally
host-neutral: core crates do not read files, fetch network data, consult
clocks, or resolve library names outside the host-provided map.

The executable subset accepts exact-key `import ... as alias` when the host
provides the matching library source. Exported const expressions are inlined,
and exported pure functions are lowered through the existing UDF path under
alias-qualified call targets. Runtime execution still receives a fully lowered
HIR program; it does not resolve imports or inspect source graphs.

Phase J began with a root-local UDT/method subset. The current analyzer records
source-scoped local and imported scalar-tree UDT identities, constructors,
field reads, selected field replacement, value history, arrays, and pure method
tables before lowering. UDT values lower to runtime values with semantic identity
metadata, and local or imported pure methods lower through the same inlined body
machinery as ordinary UDF calls with the receiver passed as the first internal
parameter. Broader non-scalar values, recursive identities, and side-effecting
method flows remain outside the current source-graph contract.

### `pine-ir`

Owns host-independent intermediate representations.

Suggested layers:

- HIR: resolved names, explicit scopes, normalized declarations.
- MIR: runtime-friendly control flow and expressions.
- Bytecode: optional later target for the VM.

The current runtime executes HIR directly. An optional MIR layer should precede
any bytecode VM if profiling later justifies a second execution representation.

Phase 6 deferred the bytecode VM. See
[`BYTECODE_VM_EVALUATION.md`](BYTECODE_VM_EVALUATION.md) for the decision and
re-evaluation triggers.

### `pine-runtime`

Owns execution.

Responsibilities:

- Execute a compiled program over OHLCV bars.
- Maintain current bar state.
- Maintain committed historical series buffers.
- Implement `var` and later `varip` storage.
- Collect plot, hline, fill, bgcolor, barcolor, and signal side effects.
- Collect drawing-object snapshots behind a host-neutral output contract.
- Enforce runtime limits.

The runtime should be deterministic for a fixed program, data set, and inputs.

Phase F introduces a host-neutral request data boundary before enabling
`request.*` execution. Core runtime code owns chart metadata, request keys,
timeframe parsing, requested-bar validation, and provider error shapes, but it
must not fetch network data or read host files. Hosts supply immutable requested
bar streams through the shared request provider contract. The default runtime
environment keeps the existing fixed chart metadata and no-request provider so
current `HistoricalRuntime::new`, `RealtimeRuntime::new`, and `run_historical`
call sites keep their behavior until request execution is explicitly enabled.
CLI uses repeated `--request-bars SYMBOL:TIMEFRAME=bars.csv` options, Python
accepts a `request_bars` dictionary with the same `SYMBOL:TIMEFRAME` keys, and
WASM accepts a deterministic request-bars JSON object through
`runScriptCsvWithRequestBars`,
`runScriptCsvWithLibrariesAndRequestBars`, and
`Program.runCsvWithRequestBars`. WASM request keys use the same
`SYMBOL:TIMEFRAME` format and split on the last colon, so exchange-prefixed
symbols such as `NYSE:IBM:1` are valid. Hosts may also set chart identity:
CLI accepts `--chart-symbol` and `--chart-timeframe`; Python `run_script` and
`Program.run` accept optional `chart_symbol` and `chart_timeframe` keywords;
WASM request JSON accepts the reserved
`"$chart":{"symbol":"...","timeframe":"..."}` object. Omitting these
values retains the existing deterministic default chart. The cross-host
request fixture can be exercised with:

```text
cargo run -p pine-cli -- run tests/fixtures/request/request_security_host.pine \
  --bars tests/fixtures/request/chart_1m.csv \
  --chart-symbol NASDAQ:AAPL --chart-timeframe 1 \
  --request-bars NYSE:IBM:1=tests/fixtures/request/ibm_1m.csv \
  --request-bars NYSE:IBM:5=tests/fixtures/request/ibm_5m.csv
```

Provider-backed `request.security` expressions are evaluated in a separate
requested-context `HistoricalRuntime` over the immutable provider bars, then
cached by callsite, requested symbol, requested timeframe, and HIR expression
identity. That keeps requested history, `ta.*` callsite state, `var` storage,
arrays, and drawing state isolated from the chart runtime. Slice 4 intentionally
uses the lowered HIR expression debug identity as the cache expression marker;
future widening that rewrites request expressions should replace it with an
explicit request-expression id.

Modern provider requests retain the default `lookahead_off`/`gaps_off` subset.
Same-timeframe `gaps_off` uses the latest requested bar whose open is not later
than the chart bar open; `gaps_on` is reserved for the legacy route and requires
an exact boundary. Coarser lookahead-off values become visible only when the
requested close is not later than the chart close. Legacy historical
lookahead-on instead makes a coarser value visible from its requested open;
forming and confirmed realtime updates intentionally use confirmed
lookahead-off alignment. `gaps_off` forward-fills the latest eligible value,
while `gaps_on` returns values only on the corresponding open or confirmation
boundary. Chart bars before the first eligible requested value return `na`.
Each provider evaluation receives a child request environment whose chart
symbol/timeframe match the requested key; cache and callsite state remain
isolated. Legacy missing-data errors add the original security call span, and
v1/v2 historical lookahead emits one non-error warning per callsite.
Lower-timeframe `request.security` alignment is intentionally not implemented
in Phase F because it needs a separate rule for selecting intrabars inside each
chart bar and bounded storage for multiple requested bars per chart bar. The
array-returning `request.security_lower_tf` API remains unsupported until typed
array return shapes and host JSON bindings are designed together. Phase F's
closed request boundary and maintenance tails are recorded in
[`PHASE_F_AUDIT.md`](PHASE_F_AUDIT.md).

Realtime execution uses explicit bar update kinds for historical, forming, and
confirmed bars. See [`REALTIME_MODEL.md`](REALTIME_MODEL.md).

Strategy execution is owned by `pine-runtime::strategy`. `BrokerState` remains
the runtime facade used by historical execution, runtime built-ins, strategy
variable reads, and public result projection. Broker internals are split under
`pine-runtime::strategy::broker`: pending-exit identity, trigger conversion,
single-trigger and bracket placement live in `exits`; pending-exit evaluation,
including stop/loss-first bracket both-hit selection, stays in the broker
facade; close/fill trade construction and position reset live in `fills`;
equity, profit, position, and trade-count accessors live in `accounting`;
broker-focused unit tests live in `tests`. Public strategy result structs
remain in `pine-runtime::output::strategy`, and host bindings continue to map
the shared runtime result without owning broker transitions. Phase R implements
the first one-downside/one-upside bracket subset inside these ownership
boundaries; it does not move broker behavior into built-in signatures, output
structs, Python, or WASM.

### `pine-builtins`

Owns built-in namespaces and functions.

Initial namespaces:

- `ta`
- `input`
- `plot` functions
- `color`
- `math`
- basic time/bar state helpers

Built-ins must be implemented against runtime abstractions instead of directly
depending on host charting code.

### `pine-cli`

Owns command line usage.

Planned commands:

```text
pine-compat analyze script.pine
pine-compat analyze script.pine --format json
pine-compat run script.pine --bars bars.csv --out result.json
pine-compat fmt-ast script.pine
```

### `pine-python`

Owns Python bindings through PyO3 and maturin.

The binding should be thin. It should expose compile, analyze, and run APIs,
but should not duplicate runtime logic in Python.

### `pine-wasm`

Owns browser and plugin use cases.

The WASM binding is intentionally thin and returns normalized JSON strings from
compile/analyze/run entry points without duplicating runtime semantics.

## Core Data Model

### Types and Qualifiers

```rust
enum Qualifier {
    Const,
    Input,
    Simple,
    Series,
}

enum ValueKind {
    Int,
    Float,
    Bool,
    String,
    Color,
    Plot,
    HLine,
    Label,
    Void,
    Na,
}

struct PineType {
    kind: ValueKind,
    qualifier: Qualifier,
}
```

Qualifiers are not decorative metadata. They determine valid function
arguments, expression results, and runtime behavior. Expressions should promote
to the strongest qualifier involved.

### Runtime Values

```rust
enum PineValue {
    Int(i64),
    Float(f64),
    Bool(bool),
    String(String),
    Color(Color),
    Plot(PlotId),
    HLine(HLineId),
    Label(LabelId),
    Na,
    Void,
}
```

Series state should live in a dedicated store instead of inside arbitrary
values.

### Series Store

```rust
struct SeriesStore {
    current_bar: usize,
    buffers: Vec<Vec<PineValue>>,
}
```

`x[1]` means "the committed value of `x` one bar before the current bar." It is
not a normal array index. The runtime must make that distinction explicit.

The actual implementation should key buffers by stable series ids assigned
during lowering. Series ids may represent variables, built-in series, temporary
expressions, function callsites, or plot output. See
[`SERIES_MODEL.md`](SERIES_MODEL.md) for the detailed model.

### Built-In Registry

Built-ins should be declared through a registry shared by semantic analysis and
runtime execution. The registry should include:

- namespace and function name
- accepted positional and named arguments
- value kind and qualifier constraints
- return kind and qualifier behavior
- whether the call requires callsite-local state
- whether the call produces output side effects

See [`BUILTIN_SIGNATURES.md`](BUILTIN_SIGNATURES.md) for the initial supported
surface.

## Public API Shape

Rust:

```rust
let program = pine_compat::compile(source)?;
let report = program.compatibility_report();
let result = program.run(&bars, &inputs)?;
```

Python:

```python
from pine_compat import compile_script

program = compile_script(
    source,
    library_sources={"user/lib/1": 'library("lib")\n'},
)
result = program.run(
    bars,
    request_bars={"NYSE:IBM:1": requested_bars},
    chart_symbol="NASDAQ:AAPL",
    chart_timeframe="1",
)
```

CLI:

```bash
pine-compat analyze script.pine --library-source user/lib/1=lib.pine
pine-compat run script.pine --bars bars.csv \
  --library-source user/lib/1=lib.pine \
  --chart-symbol NASDAQ:AAPL --chart-timeframe 1 \
  --request-bars NYSE:IBM:1=ibm.csv
```

The WASM API exposes deterministic JSON library source injection through
`compileScriptWithLibraries`, `analyzeScriptWithLibraries`, and
`runScriptCsvWithLibraries`. The JSON value must be an object mapping import
keys to source text; malformed JSON is reported as a host-input diagnostic from
the binding layer before semantic analysis.
WASM request data injection is exposed through `runScriptCsvWithRequestBars`,
`runScriptCsvWithLibrariesAndRequestBars`, and
`Program.runCsvWithRequestBars`. The `requestBarsJson` value is an object
mapping `SYMBOL:TIMEFRAME` keys to arrays of `{time, open, high, low, close,
volume}` bar objects. The reserved optional `$chart` key maps to an object with
string `symbol` and `timeframe` fields instead of a bar array. This is explicit
host-provided data; the WASM crate does not fetch network data, read files, or
discover symbols.

WASM input overrides are exposed through `runScriptCsvWithInputOverrides`,
`runScriptCsvWithRequestBarsAndInputOverrides`,
`runScriptCsvWithLibrariesAndInputOverrides`,
`runScriptCsvWithLibrariesAndRequestBarsAndInputOverrides`,
`Program.runCsvWithInputOverrides`, and
`Program.runCsvWithRequestBarsAndInputOverrides`. The `inputOverridesJson`
value is an object keyed by analysis `inputs[].callSiteId`; values are parsed
against the analyzed `input.*` call type. Host-side `input.source` overrides
remain unsupported.

## Output Model

The core output must remain host-neutral:

```json
{
  "schemaVersion": 8,
  "plots": [],
  "plotChars": [],
  "plotShapes": [],
  "plotArrows": [],
  "plotBars": [],
  "plotCandles": [],
  "bgColors": [],
  "barColors": [],
  "hlines": [],
  "fills": [],
  "labels": [],
  "lines": [],
  "lineFills": [],
  "polylines": [],
  "boxes": [],
  "tables": [],
  "alerts": [],
  "diagnostics": []
}
```

The runtime `schemaVersion` field is owned by
`PUBLIC_RUNTIME_SCHEMA_VERSION` and is exposed unchanged by CLI runtime JSON,
Python runtime dictionaries, and WASM runtime JSON. `schemaVersion: 2` added
top-level drawing-object fields, and `schemaVersion: 3` reserves the top-level
`alerts` event array. Phase H's initial event shape is `{id, barIndex, time,
message, source}` for the narrow `alertcondition` and `alert` subsets. For
`alertcondition`, `source` is the const title; for `alert`, `source` is
`alert`. `schemaVersion: 4` adds broker-owned strategy order-fill alert
payloads under `strategy.alerts` without changing the top-level `alerts[]`
callsite event shape. `schemaVersion: 5` adds host-neutral table cell
`textWrap` snapshots. `schemaVersion: 6` adds top-level `lineFills` snapshots
for the supported linefill subset. `schemaVersion: 7` adds top-level
`polylines` snapshots for the supported `polyline.new` and lifecycle subset.
`schemaVersion: 8` adds normalized colors and fixture-backed visual metadata
to plots, markers, bars, candles, colors, hlines, and fills. The completed
contract carries `renderMetadataVersion: 1`, preserves the public
`linewidth`/`style` field names, exposes plot `format`/`precision` and
`forceOverlay`, identifies fill endpoint kinds, and reserves bit 32 on numeric
colors as the alpha discriminator when an RGBA payload would otherwise look
like `0xRRGGBB`. Host integrations can adapt this model into
their charting or API format, but should preserve the runtime schema version
when they forward machine-readable runtime results.

Machine-readable analysis and matrix outputs use separate schema ownership.
`pine-sema::PUBLIC_ANALYSIS_SCHEMA_VERSION` owns CLI/Python/WASM analysis
reports, while `PUBLIC_MATRIX_SCHEMA_VERSION` owns CLI matrix JSON. Runtime is
currently `8`; analysis is currently `5`, adding compile-time input defaults,
constraints, and options to the existing version, diagnostic, dialect,
translation/emulation, and compatibility evidence; matrix
remains `2`. These contracts can evolve independently when a runtime-only
output field does not affect analysis or matrix contracts.

Drawing-object outputs use sparse snapshot families. The Phase E drawing
contract reserves `labels`, `lines`, `boxes`, and `tables`, whose entries have
an object `id` and a `snapshots` array. Label snapshots use `barIndex`,
`exists`, and, while `exists` is true, the mutable label fields represented by
normalized Pine values, including `textAlign`, `textFontFamily`, and
`textFormatting` for host-side text layout. `label.new` can initialize
bar-index or bar-time x locations directly or from a `chart.point` using
`point.index` for `xloc.bar_index` and `point.time` for `xloc.bar_time`,
price/abovebar/belowbar y locations, official label styles, string and integer
sizes, tooltip, text alignment, font-family, and text-formatting snapshot
fields. Supported `label.set_*`
mutators include coordinate, `label.set_point` chart-point coordinate mutation,
x-location, y-location, text, size, color, style, tooltip, alignment,
font-family, and text-formatting snapshot mutation from ordinary and
independent while-loop control-flow blocks. `label.set_point` uses
`point.index` for `xloc.bar_index` labels and `point.time` for
`xloc.bar_time` labels, while always using `point.price` for `y`.
`label.copy` cloning
from ordinary and independent while-loop control-flow blocks, and
`label.delete` deletion snapshots from ordinary and independent while-loop
control-flow blocks also use the label snapshot model; `label.all` reads
currently existing label ids, `label.get_x` reads latest label x-coordinates,
`label.get_y` reads latest label y-coordinates, and `label.get_text` reads
latest label text from ordinary and independent while-loop control-flow blocks.
Line snapshots cover `x1`, `y1`,
`x2`, `y2`, `xloc`, `color`, `width`, `style`, and `extend`. `line.new` can
initialize those host-neutral style snapshot fields, including official line
style and extend constants, for the x1/y1/x2/y2 overload when `xloc` is omitted
or `xloc.bar_index`, when `xloc.bar_time` stores time-coordinate x values, or
from two `chart.point` values using `point.index` for `xloc.bar_index` and
`point.time` for `xloc.bar_time`.
Supported `line.set_*` mutators include geometry, color, width, official style,
official extend, `line.set_first_point`/`line.set_second_point` for
`chart.point` values, and `line.set_xloc` for
`xloc.bar_index`/`xloc.bar_time`, which rewrites x1, x2, and xloc from
ordinary and independent while-loop control-flow blocks; they reuse the same
snapshot model.
`line.copy` cloning from ordinary and independent while-loop control-flow
blocks and `line.delete` deletion from ordinary and independent while-loop
control-flow blocks also use that model. `line.all` reads current line ids from
ordinary and independent while-loop control-flow blocks. `line.get_x1`,
`line.get_y1`, `line.get_x2`, and `line.get_y2` read latest existing line
coordinates from ordinary and independent while-loop control-flow blocks;
`line.get_price` derives a host-neutral bar-index price from ordinary and
independent while-loop control-flow blocks by interpolating or extrapolating
across the latest existing x1/y1/x2/y2 snapshot; time-coordinate lines return
`na` because timestamp interpolation remains outside the supported getter
subset. Box snapshots
cover `left`, `top`,
`right`, `bottom`, `xloc`, `bgColor`, `borderColor`, `borderWidth`, `borderStyle`,
`extend`, `text`, `textColor`, `textSize`, `textHalign`, `textValign`,
`textWrap`, `textFontFamily`, and `textFormatting`. `box.new` can initialize
those host-neutral style and text snapshot fields, including
solid/dotted/dashed border styles and official extend constants, for the
left/top/right/bottom overload and the `chart.point` top-left/bottom-right
overload when `xloc` is omitted or `xloc.bar_index`; `xloc.bar_time` stores
time-coordinate left/right values and uses `point.time` for point-overload
boxes. Supported
`box.set_*` mutators include geometry, background, border
color/width/style, official extend, text and text-layout snapshot setters from
ordinary and independent while-loop control-flow blocks,
`box.set_top_left_point`/`box.set_bottom_right_point` for `chart.point` values,
and the
`box.set_xloc` subset for `xloc.bar_index`/`xloc.bar_time` that rewrites left,
right, and xloc from ordinary and independent while-loop control-flow blocks.
`box.copy` cloning
from ordinary and independent while-loop control-flow blocks and `box.delete`
deletion from ordinary and independent while-loop control-flow blocks reuse the
same snapshot model;
`box.all` reads current box ids from ordinary and independent while-loop
control-flow blocks after deletion. `box.get_left`, `box.get_right`,
`box.get_top`, and `box.get_bottom` read latest existing box values from
ordinary and independent while-loop control-flow blocks.
Table entries
carry `position`, `bgColor`, `frameColor`, `frameWidth`, `borderColor`,
`borderWidth`, `columns`, `rows`, and sparse cell snapshots. Each table snapshot
carries `exists`; existing table snapshots store cells whose entries carry
`column`, `row`, `text`, `bgColor`, `textColor`, `width`, `height`, `textSize`,
`textHalign`, `textValign`, `textWrap`, `tooltip`, `textFontFamily`, and
`textFormatting`, avoiding host-specific table layout assumptions;
`table.new` may initialize the final background color, frame color, frame
width, border color, and border width through its optional `bgcolor`,
`frame_color`, `frame_width`, `border_color`, and `border_width` arguments;
`table.set_position` updates the table's final position, including when called
from ordinary and independent while-loop control-flow blocks, `table.set_bgcolor`
updates the table's final background color, including when called from ordinary
and independent while-loop control-flow blocks, `table.set_frame_color` updates
the table's final frame color, including when called from ordinary and
independent while-loop control-flow blocks, `table.set_frame_width` updates the
table's final frame width, including when called from ordinary and independent
while-loop control-flow blocks, `table.set_border_color` updates the table's
final border color, including when called from ordinary and independent
while-loop control-flow blocks, `table.set_border_width` updates the table's
final border width, including when called from ordinary and independent
while-loop control-flow blocks, `table.delete` records an
`exists: false` snapshot, including when called from ordinary and independent
while-loop control-flow blocks, while `table.cell_set_text`, `table.cell_set_bgcolor`,
`table.cell_set_text_color`, `table.cell_set_width`, `table.cell_set_height`,
`table.cell_set_text_size`, `table.cell_set_text_halign`,
`table.cell_set_text_valign`, `table.cell_set_text_wrap`,
`table.cell_set_tooltip`, `table.cell_set_text_font_family`, and
`table.cell_set_text_formatting`, including when called from ordinary and
independent while-loop control-flow blocks, mutate only
the stored text/background/text color/width/height/text size/text
alignment/text wrap/tooltip/font-family/text-formatting for cells already
populated by `table.cell`, `table.clear` removes populated cells in an
inclusive rectangular range, including from ordinary and independent while-loop
control-flow blocks, and removes merged-cell records intersecting that range,
`table.merge_cells` records inclusive host-neutral merge rectangles, including
from ordinary and independent while-loop control-flow blocks, and `table.delete`
appends a deleted snapshot, including
from ordinary and independent while-loop control-flow blocks.
`table.all` reads currently existing table ids in creation order, including
from ordinary and independent while-loop control-flow blocks after deletion.
Delete calls append an `exists: false`
snapshot for families with deletion; deleting `na` or an already deleted
drawing object is a no-op; ids are not reused. The historical runtime caps
labels, lines, and boxes at 500 objects, caps tables at 50 objects, and caps a
single table at 1000 cells.
Drawing-object method-call syntax is normalized before runtime. For supported
label, line, box, and table id-first functions, semantic analysis validates the
receiver type and lowering rewrites calls such as `id.set_text("x")` to the
same HIR callee and argument list as `label.set_text(id, "x")`. Runtime modules
therefore execute one canonical namespace-call path.

Alert events are flat runtime events rather than sparse snapshots. Historical
execution appends events in program order when an `alertcondition` call is
reached and true, or when an `alert` call is reached. Realtime forming events
live in the forming runtime snapshot and are discarded on rollback unless a
confirmed update emits the same event. Forming `RuntimeResult` values expose
the currently recomputed forming events, but `confirmed_result()` only exposes
events committed by historical or confirmed updates.

The `pine-runtime` crate owns the shared runtime-result JSON helpers used by the
CLI and WASM bindings. Python keeps explicit dictionary conversion code because
it returns native Python objects, but its top-level runtime result keys are
tested against the same public contract. Analysis reports and compatibility
matrix JSON keep distinct schema constants even where their current field shapes
remain host-owned.
