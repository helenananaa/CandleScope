# Legacy Indicator Phase 5 Audit

## Outcome

Phase 5 makes the initial Pine v4 output family executable as faithful,
host-neutral visual data. Historical signatures are bound before canonical
validation, legacy transparency and primitive styles are preserved explicitly,
and all ten selected output families now expose their visual series and
metadata through Rust, CLI, Python, and WASM.

The supported family is:

```text
plot        plotchar     plotshape    plotarrow
plotbar     plotcandle   hline        fill
bgcolor     barcolor
```

This phase does not enable any legacy strategy path. Pine v1-v3 outputs remain
behind their declaration and version phases.

## Historical Contract

The binder was checked against TradingView's archived
[Pine v4 reference](https://in.tradingview.com/pine-script-reference/v4/),
[v4 color documentation](https://www.tradingview.com/pine-script-docs/v4/essential/colors/),
[v4 shape/character/arrow documentation](https://www.tradingview.com/pine-script-docs/v4/annotations/plotting-shapes-chars-and-arrows/),
and the official
[v4-to-v5 migration guide](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-5/).
The implementation uses per-function positional tables instead of sending old
calls directly to current signatures.

The accepted v4 order is:

```text
plot(series, title, color, linewidth, style, trackprice, transp, histbase,
     offset, join, editable, show_last, display)
plotchar(series, title, char, location, color, transp, offset, text,
         textcolor, editable, size, show_last, display)
plotshape(series, title, style, location, color, transp, offset, text,
          textcolor, editable, size, show_last, display)
plotarrow(series, title, colorup, colordown, transp, offset, minheight,
          maxheight, editable, show_last, display)
plotbar(open, high, low, close, title, color, editable, show_last, display)
plotcandle(open, high, low, close, title, color, wickcolor, editable,
           show_last, bordercolor, display)
hline(price, title, color, linestyle, linewidth, editable)
fill(plot1, plot2, color, transp, title, editable, show_last, fillgaps)
fill(hline1, hline2, color, transp, title, editable, fillgaps)
bgcolor(color, transp, offset, editable, show_last, title)
barcolor(color, offset, editable, show_last, title)
```

Plot and hline fill overloads must use two endpoints of the same kind. Unknown
names, later-only arguments, duplicate or misordered arguments, invalid style
values, series transparency, and mixed fill endpoints fail during analysis.
The focused failures use `E_LEGACY_OUTPUT_ARGUMENT` where the historical value
contract is violated; ordinary name/order/arity failures retain the shared call
diagnostics and original spans.

## Style and Transparency Semantics

Pine v4 primitive style values are converted only in their historical style
slots. The exact maps are:

| Ordinal | Plot style |
| ---: | --- |
| 0 | `plot.style_line` |
| 1 | `plot.style_stepline` |
| 2 | `plot.style_histogram` |
| 3 | `plot.style_cross` |
| 4 | `plot.style_area` |
| 5 | `plot.style_columns` |
| 6 | `plot.style_circles` |
| 7 | `plot.style_linebr` |
| 8 | `plot.style_areabr` |

| Ordinal | Hline style |
| ---: | --- |
| 0 | `hline.style_solid` |
| 1 | `hline.style_dotted` |
| 2 | `hline.style_dashed` |

Constant invalid ordinals fail analysis. Input-qualified ordinals remain
overrideable, but an invalid host override raises a stable runtime error rather
than falling back to a line.

`transp` is accepted only by `plot`, `plotchar`, `plotshape`, `plotarrow`,
`bgcolor`, and `fill`. It is an input-compatible integer or `na`, not a series
value. The normalization rules are:

| Case | Result |
| --- | --- |
| Omitted on `plot`/marker/arrow | effective transparency `0` |
| Omitted on `bgcolor` or `fill` | v4 default transparency `90` |
| Value below 0 or above 100 | clamp to `0..100` |
| Explicit `na` transparency | effective transparency `0` |
| `na` color | remains `na` |
| Color already carrying alpha | embedded alpha wins; `transp` is ignored |
| Opaque color | normalized RGBA color is emitted |

The analyzer removes the user-visible `transp` argument and writes an internal
`$legacy_transp` argument into canonical HIR. Runtime output functions consume
that marker without creating a synthetic stateful callsite. Compatibility
reports record `outputAdaptation` translations and separate transparency or
numeric-style emulations. `LEGACY_TRANSLATOR_REVISION` is `4`, so cached
analysis cannot cross this semantic change.

## Runtime Output Contract

The public runtime contract is now `schemaVersion: 8`. Default-valued metadata
is omitted from machine-readable output, while non-default values are exposed
consistently by CLI/WASM JSON and Python dictionaries.

- `plots` now carries per-bar `colors`, plus `linewidth`, `style`,
  `trackPrice`, `histBase`, `join`, and common metadata.
- `plotChars`, `plotShapes`, and `plotArrows` expose every supported visual
  value as a bar-aligned series, including character/style/location, primary
  colors, text/text colors, size, and height bounds.
- `plotBars` and `plotCandles` expose OHLC and body/wick/border color series.
- `bgColors` and `barColors` carry normalized color series and metadata.
- `hlines` carry price, title, color, style, linewidth, editable, and display.
- `fills` carry endpoint ids, color series, title, editable, show-last,
  fill-gaps, and display.
- Common metadata is title, offset, editable, show-last, and display where the
  underlying signature accepts it.

Series alignment pads unreached conditional calls with `na`. Output metadata
is retained with its callsite-owned output and does not change callsite ids.
The runtime's incremental clone and realtime forming-bar snapshot include the
expanded values, so append execution matches a full historical run and rollback
removes stale forming values instead of duplicating them.

## Fixture and Host Evidence

The primary pair is:

- `tests/fixtures/legacy/v4/runtime/outputs_legacy.pine`
- `tests/fixtures/legacy/v4/runtime/outputs_canonical.pine`

It covers all ten families, both fill overloads, primitive and named styles,
input-qualified styles, explicit and default transparency, embedded alpha
precedence, offsets, visibility metadata, `na` placement, and normalized
colors. Rust compares the complete `RuntimeResult` values. Dedicated tests add
transparency clamping, explicit `na`, dynamic input overrides, invalid runtime
style ordinals, incremental append, and realtime rollback.

`tests/fixtures/legacy/v4/unsupported/output_arguments.pine` proves a
later-only argument stops during analysis. The shared
`tests/snapshots/runtime_legacy_v4_outputs.json` golden is asserted byte for
byte by CLI, Python, and WASM, and host analysis tests assert the new
`outputAdaptation` and emulation report entries.

## Corpus Effect

The unchanged 29-item Phase 0 manifest was run twice at fixed build revision
`phase5`. The reports were byte-for-byte identical with SHA-256:

```text
e7dbd42488b40c41b72c83279edccd15a9da18d81c9b010274ebcecacbe71dea
```

Rates retain the denominator of 22 eligible legacy indicators:

| Stage | Passed | Attempted | Eligible denominator | Rate |
| --- | ---: | ---: | ---: | ---: |
| Parse | 22 | 22 | 22 | 100% |
| Analyze | 7 | 22 | 22 | 31.82% |
| Lower | 7 | 7 | 22 | 31.82% of eligible; 100% of attempted |
| Historical run | 7 | 7 | 22 | 31.82% of eligible; 100% of attempted |

Within v4, analysis and historical execution improved from 5 of 12 to 7 of 12
indicators (58.33%). The newly passing items are exactly
`legacy_v4_plot_style` and `legacy_v4_transp`. The leading remaining clusters
are ten pre-v4 declarations, five known unsupported v4 semantic families, two
`plot.series` cascades, and two unqualified `change` calls. The corpus tool does
not yet attempt incremental, realtime, or reference-output stages, so those
remain `notRun` and are not inflated into the compatibility rate.

## Deferred Boundary

- Pine v1-v3 output admission and their constants remain Phase 8/9 work.
- `iff`, `offset`, the legacy `rsi` overload, strict logical behavior, and
  session defaults remain Phase 6 work.
- `security` and declaration timeframes remain Phase 7 work.
- Drawing objects and alerts are not part of the Phase 5 legacy milestone.
- Chart rendering and host-specific layout remain consumer responsibilities;
  this runtime exposes normalized visual data only.
- Legacy strategies remain permanently out of scope.

## Verification

Targeted semantic/runtime tests, historical pair equality, incremental and
realtime tests, CLI/Python/WASM golden parity, conformance and matrix guards,
and both fixed-revision corpus runs passed. The complete `scripts/verify.sh`
release gate then passed, including the Rust workspace and doc tests, all 513
WASM tests, all 487 installed-wheel Python tests, the 296-file structural
guard, the nine corpus-analyzer tests, host parity over 721 registered CLI
snapshots and 425 required host golden assertions, and the Node WASM smoke test.
Snapshot changes were generated only with the documented
`UPDATE_SNAPSHOTS=1` workflow and rechecked without the update flag.
