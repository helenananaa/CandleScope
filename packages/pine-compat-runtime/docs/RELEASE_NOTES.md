# Release Notes

## Unreleased

## 0.2.0 - 2026-07-20

- Hardened the legacy front-end after the release-candidate audit. Legacy
  dialects now reject qualified APIs introduced by later Pine versions,
  admission distinguishes a real built-in `study(...)` declaration from a
  shadowing user function, pre-v3 ordinary built-ins reject keyword arguments
  while historical annotation calls retain them, internal input-type markers
  cannot be forged or used outside the `input(type=...)` selector, and positive
  constant-expression history offsets participate correctly in the v1/v2
  declaration graph. Pine v5 `table.new(..., force_overlay=...)` is also
  accepted, while Pine v4 rejects both named and positional uses at analysis
  time; public-output propagation and pane routing remain unsupported.
- Corrected two state/time alignment bugs. Omitted-anchor `ta.vwap(source)`
  tracks its default UTC-day bucket per callsite, so a conditionally executed
  call starts or resets on its first execution in that bucket. Higher-timeframe
  request alignment now uses calendar-month closes instead of fixed 30-day
  durations, preventing `lookahead_off` from exposing 31-day monthly values
  early or delaying 28/29-day values.
- Closed input-override inconsistencies across CLI, Python, and WASM. Generic
  `input()` values are parsed from their analyzed value kind instead of text
  heuristics, normalized duplicate callsite ids fail consistently, and the
  complete public numeric color representation—including bit-32 low-RGBA
  encodings—can be passed back through `input.color` with range validation.

- Closed the current pure-internal `ta.*` indicator surface by completing the
  remaining `ta.vwap` row. Variable and omitted-anchor call forms now reset on
  the runtime's UTC `1D` boundary, explicit anchors return `na` until their
  first true value and reset before the current bar, bands accept series
  numeric multipliers, and historical, incremental/request-context, and
  realtime rollback evidence share the same callsite state model. Exchange
  calendar/session metadata remains a host boundary rather than an implicit
  runtime dependency.
- Fixed interpreter-to-host rendering data loss discovered during CandleScope
  integration. Explicit low-valued RGBA colors now retain their alpha channel
  internally and across host boundaries through the versioned bit-32 alpha
  discriminator; runtime schema 8 now advertises `renderMetadataVersion: 1`, completes plot and fill metadata,
  and keeps the established `linewidth`/`style` field names across CLI,
  Python, and WASM. Analysis reports are now schema 5 and expose compile-time
  input defaults, numeric constraints, steps, and options; Python also exports
  all three schema-version constants.
- Closed the legacy-indicator stabilization audit with explicit release
  maturity: Pine v4/v3 indicators are preview profiles, while Pine v2 and
  implicit-v1 indicators are experimental. A sorted 15-row release registry
  covers every legacy runtime fixture plus v2/v3/v4 MTF evidence across batch,
  incremental, realtime historical handoff, forming rollback, confirmation,
  provider alignment, and bounded runtime storage. The v2 historical
  lookahead profile deliberately verifies no realtime future-data leakage
  instead of asserting false batch/realtime equality.
- Re-ran the fixed original 29-item legacy corpus twice with byte-identical
  output: all 22 eligible indicators parse, analyze/lower, and run
  historically, with no crash, unknown diagnostic, or scope mismatch. The
  per-version counts of 12/7/2/1 remain below the provisional 50-script stable
  evidence gate, and no reference-output oracle is supplied, so this result is
  not advertised as full backwards compatibility.
- Added a reusable legacy release profiler, deterministic retained-value
  ceilings, explicit dialect/cache isolation tests, and an independent 4096
  declaration-edge adversarial test. All 16 emitted legacy diagnostic codes
  remain documented, public analysis/runtime/matrix schemas remain 5/8/2, and
  all committed legacy corpus/release sources are marked original.
- Closed legacy host integration with CLI-owned shared goldens across Python
  and WASM. Required runtime parity now includes implicit v1 and v4 input
  defaults; five complete analysis snapshots cover v1-v4 and a v2 graph error.
  The expanded guard rejects missing registry/manifest/host assertions, while
  focused CLI, Python, and WASM tests preserve v4 input overrides and legacy
  request errors. Source versions remain automatic; no optional policy switch
  or unsafe migration preview was added.
- Added the executable Pine v1/v2 indicator slice, including implicit-v1
  selection, historical `study`/focused `input`/`plot` admission, `sma`/`ema`,
  a bounded scalar declaration graph for self-history and safe forward
  references, v1/v2 bool arithmetic conversion, and v1-v5 numeric condition
  conversion. Removed conversions lower to explicit canonical calls, unsafe or
  cyclic graphs fail with focused diagnostics, paired v2/v6 fixtures are exact
  across batch/incremental/realtime and CLI/Python/WASM, and all 22 eligible
  indicators in the unchanged seed corpus now analyze, lower, and execute.
- Added the executable Pine v3 indicator slice. Historical `study`, `input`,
  `plot`, and `hline` signatures now bind by dialect; pre-v4 colors, the old
  `color(...)` helper, input types, plot/hline styles, weekdays, chart metadata,
  `interval`, `ticker`, `tickerid`, and `n` lower to canonical HIR with lexical
  precedence and v4-v6 isolation. Fixture-backed untyped-`na` declarations
  infer one stable scalar type from a later assignment or fail with
  `E_LEGACY_V3_NA_INFERENCE`. Chart metadata follows the supplied symbol and
  minute/second/day/week/month timeframe, and paired Rust, CLI, Python, and
  WASM evidence makes all seven original v3 corpus indicators executable.
- Added executable legacy `security` compatibility through the host-neutral
  request provider. Pine v1/v2 and v3/v4 signatures now bind with their
  historical default lookahead policies, verified bool/`barmerge` gaps and
  lookahead modes, isolated requested-context state, separate historical and
  realtime alignment, one repaint warning per lookahead-on callsite, and
  original source spans in provider failures. CLI, Python, and WASM can all
  supply chart identity plus requested streams; modern `request.security`
  remains restricted to its existing default merge surface, and
  `study(resolution=...)` remains precisely unsupported pending a whole-program
  execution coordinator.
- Added result-faithful Pine v4 expression/default compatibility. Historical
  `iff` now evaluates condition/result1/result2 once in parameter order,
  `offset` lowers to native guarded history, and `rsi(x, y)` selects the length
  or removed two-series formula overload by analyzed type. Versioned session
  parsing preserves the v4 weekday default without rewriting input strings,
  v1-v5 logical operands remain strict while v6 remains lazy, and the exact v4
  aliases `change`, `highest`, `lowest`, `max`, and `min` complete the affected
  original fixtures. Historical, incremental, realtime, CLI, Python, and WASM
  tests share the same compatibility report and output evidence.
- Added faithful Pine v4 output compatibility for `plot`, marker/arrow outputs,
  OHLC bars/candles, `hline`, both `fill` overloads, `bgcolor`, and `barcolor`.
  Historical signatures now preserve primitive styles, output-specific
  transparency defaults, clamping, `na`, embedded-alpha precedence, offsets,
  visibility metadata, and realtime/incremental alignment without weakening
  v5/v6 rules. Public runtime output is now `schemaVersion: 8`, exposing the
  normalized visual series and metadata consistently across CLI, Python, and
  WASM.
- Added executable Pine v4 input compatibility. Historical `input()` overloads
  and all eleven documented `input.*` type constants now lower to canonical
  specialized input calls with original-span translations, stable callsite ids,
  canonical metadata and host overrides, strict ambiguous-overload diagnostics,
  local const aliases, modern negative controls, paired HIR/runtime fixtures,
  and the parameter-scoped v4 integer float-metadata exception.
- Added the first executable Pine v4 indicator slice. `study(...)` now binds
  against its historical signature and lowers to canonical `indicator` HIR for
  the verified single-timeframe metadata subset; `resolution`,
  `resolution_gaps`, `explicit_plot_zorder`, and legacy session defaults fail
  closed. The v4-only `sma`, `ema`, `bb`, `crossover`, and `abs` aliases lower
  to existing canonical implementations with original-span reports, collision
  precedence, modern negative controls, paired HIR/runtime fixtures, and
  synchronized CLI, Python, WASM, and conformance coverage.
- Added the versioned legacy compatibility front-end: validated sorted rule
  catalogs, scoped fallback after user declarations, original-span translation
  records, canonical-only HIR lowering, focused unsupported-known routing,
  deterministic legacy report ordering/deduplication, and a translator revision
  in semantic compile-cache keys. Phase 2 uses synthetic exact aliases for
  framework tests and does not yet enable production aliases or `study()`
  execution.
- Established the legacy-indicator version and mode admission boundary. Pine
  v1-v6 are represented by a closed dialect model, a missing directive selects
  implicit v1, invalid/duplicate/misplaced directives and root/library version
  conflicts stop before ordinary semantic analysis, and v1-v4 strategy scripts
  now receive one stable out-of-scope diagnostic without entering broker
  analysis.
- Bumped public analysis reports to `schemaVersion: 4` across CLI JSON, Python,
  and WASM. Reports now expose `languageVersionOrigin`, `dialect`, `scriptMode`,
  `legacyTranslations`, and `legacyEmulations`; CLI `analyze` accepts
  `--format text|json`.
- Assigned explicit v5 directives to modern fixtures that previously depended
  on a missing-version default. The dedicated no-directive fixture remains an
  implicit-v1 control, while v5/v6 indicator and strategy paths retain their
  existing behavior.

## 0.1.0 - 2026-07-18

- Added a GitHub Actions binary-wheel pipeline for glibc Linux x86-64 and
  Windows x86-64, including installed-wheel tests, deterministic release
  metadata, SHA-256 checksums, and tag-to-package version validation.

- Aligned UDT `array.sort` and `array.sort_indices` runtime validation with the
  collection contract: an array element that is itself `na` now raises a stable
  runtime error, while concrete UDT elements whose selected sortable field is
  `na` retain ordinary special-value ordering. CLI, WASM, and Python error
  paths share regression fixtures.
- Extended same-local and same-imported scalar-tree UDT `array.sort` and
  `array.sort_indices` with the current selector contract: omitted `sort_field`
  defaults to root field index `0`, while supplied compile-time integer indexes
  and string field names select sortable root `int`, `float`, or `string`
  fields. Namespace, method, call-result, named-argument, and const-alias forms
  share canonical field-index lowering and host-parity fixtures.
- Added legacy expression line wrapping outside parentheses, accepting
  continuation indentation deeper than the active local block when its column
  is not a multiple of four, including end-of-line comments and mixed widths.
- Added current v6 parenthesized line wrapping, treating physical newlines,
  comments, and any continuation indentation inside round parentheses as
  layout-free whitespace across grouped expressions, calls, parameter lists,
  nested parentheses, and local blocks.
- Enforced Pine's 40,960-decoded-character limit on single-line, line-wrapped,
  and triple-delimited string literals, with Unicode-scalar counting, a stable
  full-span diagnostic, and recovery that retains later statements.
- Added deprecated Pine single-line string wrapping for quotation-mark and
  apostrophe literals, collapsing every space-indented physical continuation
  to one space without inserting a line terminator, with CRLF/bare-CR handling
  and unchanged unindented-line recovery.
- Added scalar-variable compound assignments `+=`, `-=`, `*=`, `/=`, and `%=`
  as exact shorthand for existing reassignment expressions, including numeric
  operations, string `+=`, qualifier promotion, `na`, local/UDF execution, and
  persistent `var` state.
- Added string `+` concatenation across const, input, simple, and series
  qualifiers, including UDF return inference, const-expression resolution,
  `na` propagation, UTF-8 character counting, and the 40,960-character runtime
  limit.
- Added v6 triple-quotation-mark and triple-apostrophe multiline string
  literals, including literal newline and indentation preservation, CRLF
  normalization, ordinary escape decoding, UTF-8 contents, and stable
  unterminated-literal diagnostics at EOF.
- Added apostrophe-delimited single-line string literals with the same const
  string typing, UTF-8 preservation, escape handling, and unterminated-literal
  recovery as existing quotation-mark-delimited strings.
- Added the default same-currency subsets of
  `strategy.convert_to_account(value)` and `strategy.convert_to_symbol(value)`.
  Under omitted or explicit `currency.NONE`, both are strategy-mode
  `series float` identities that coerce integers to floats, preserve typed
  `na`, and support direct, named, UDF, and history calls. Cross-currency
  conversion remains unsupported.
- Added the no-conversion `strategy(..., currency=currency.NONE)` declaration
  subset. It preserves the default behavior where
  `strategy.account_currency` inherits `syminfo.currency`; explicit account
  currencies other than `currency.NONE` remain rejected.
- Added `strategy.account_currency` as a read-only strategy-mode
  `simple string`. Under the currently supported default `currency.NONE`
  declaration path, it inherits the fixed `syminfo.currency` value (`"USD"`).
  Direct, UDF, and history reads are supported without expanding public
  strategy output; non-default account-currency configuration and conversion
  remain outside this slice.
- Added `strategy.default_entry_qty(fill_price)` as a read-only strategy-mode
  `series float` helper over the existing fixed, cash, and percent-of-equity
  default sizing paths. It supports direct, named, UDF, and history reads,
  reports the default order quantity without position-reversal adjustment, and
  preserves the current no-currency-conversion/no-symbol-point-value boundary.
- Added `strategy.position_entry_name` as a read-only strategy-mode
  `series string`. It is `na` while flat, records the entry order ID that
  initially opened the current continuous net long position, survives
  pyramiding additions and partial allocation closes, and resets only when the
  net position becomes flat. Direct, UDF, and history reads do not expand
  public strategy output.
- Added `strategy.closedtrades.first_index` as a read-only strategy-mode
  `series int`. It returns `0` throughout the current untrimmed closed-trade
  retention model, including before the first trade, and supports direct, UDF,
  and history reads without expanding public strategy output; platform-style
  order-limit trimming remains outside this slice.
- Added `strategy.openprofit_percent` as a read-only strategy-mode
  `series float`, calculated as current unrealized profit divided by realized
  equity (`initial_capital + netprofit`) times 100. It supports direct, UDF,
  and history reads, returns `na` for a non-positive or non-finite denominator,
  and does not expand public strategy output.
- Added `strategy.initial_capital` as a read-only strategy-mode `series float`
  that returns the configured or default broker starting capital on every bar,
  including UDF and history reads, without expanding public strategy output.
- Added the six script-visible trade percentage helpers
  `strategy.closedtrades.profit_percent`, `max_runup_percent`, and
  `max_drawdown_percent` plus their `strategy.opentrades.*` counterparts. They
  divide the selected trade amount by entry price times absolute quantity,
  preserve the current long-only indexed-ledger and `na` boundaries, and add
  no public strategy-result fields.
- Added `runtime.error(message)` with string-compatible const, input, simple,
  and series messages, named-argument and user-defined-function support, exact
  reached-call error propagation, a deterministic `NaN` message for `na`, and
  semantic rejection of non-string messages or attempts to consume its `void`
  return.
- Added `str.match()` compatibility for Java/Pine's rule that a backslash
  quotes any non-alphanumeric ASCII character. All ASCII punctuation and
  control/whitespace literals now work inside or outside character classes,
  including verbose-mode `\#` and `\ `, nested classes, and active case
  modes; unknown alphabetic escapes remain invalid.
- Corrected `str.match()` Java/Pine character classes so `~` remains a
  literal atom instead of allowing adjacent `~~` to invoke Rust's symmetric
  difference operator. Ordinary, escaped, quoted, nested, range-endpoint, and
  case-insensitive class uses are normalized, while tildes outside classes
  retain their literal behavior.
- Completed `str.match()` support for Java/Pine character method properties
  with the remaining nine identifier, whitespace, control, and mirrored
  classes. Java and Unicode identifier start/part retain their distinct
  currency, connector, `Other_ID_*`, and ignorable boundaries;
  `javaWhitespace` exactly excludes NEL and the three non-breaking spaces
  while including the U+001C–U+001F separators. Complements, nesting, quoting,
  exact names, and `(?U)` independence are preserved.
- Added `str.match()` support for nine basic Java/Pine character method
  properties: `javaLowerCase`, `javaUpperCase`, `javaAlphabetic`,
  `javaIdeographic`, `javaTitleCase`, `javaDigit`, `javaDefined`,
  `javaLetter`, and `javaLetterOrDigit`. Their exact case-sensitive names work
  with `\p`/`\P`, nested character classes, quoted preservation, and
  `(?i)` Unicode case closure, while membership remains independent of `(?U)`.
- Corrected `str.match()` verbose `x` mode to use Java/Pine's ASCII-only
  whitespace rules while preserving non-ASCII Unicode whitespace as literal
  text, including escaped atoms and character classes. Comments now end at LF,
  CR, NEL, line separator, or paragraph separator; the three Unicode
  terminators remain literal atoms, while VT and FF do not terminate comments.
  Global/scoped modes and quoted regions preserve these boundaries.
- Added `str.match()` support for Java/Pine's lowercase `u` Unicode-case flag.
  Global and scoped `(?iu)` now use Unicode folding for literal, quoted, and
  escaped atoms without changing default-ASCII predefined or POSIX classes;
  class-local expansions retain that boundary. `U` implies `u`, `-u` disables
  case folding without disabling Unicode classes, and `-U` disables both.
- Corrected `str.match()` Java/Pine character-class parsing so a leading `]`
  is treated as a literal class atom, including after a leading negation,
  verbose-mode whitespace or comments, and an empty `\Q\E` quote. Quoted
  closers and active ASCII/Unicode case modes retain their existing behavior.
- Added `str.match()` support for Pine's `\G` previous-match anchor. Under the
  API's single initial match search it is an absolute-start assertion, including
  multiline independence, consumed-prefix rejection, quoted preservation, and
  character-class rejection.
- Added `str.match()` support for Pine's `\0n`, `\0nn`, and `\0mnn` octal
  regex references, including Java's conditional third-digit consumption,
  required first digit, non-octal trailing characters, character-class and
  quoted behavior, verbose trivia skipping, and active case-mode handling.
- Added `str.match()` support for Pine's `\e` escape-character and `\cX`
  control-character regex references, including Java's one-Unicode-scalar
  `XOR 0x40` mapping, exact consumption, character-class and quoted behavior,
  verbose-mode trivia skipping, and ASCII/Unicode case-mode switching.
- Added `str.match()` support for Pine's `\R` line-break matcher across LF,
  VT, FF, CR, NEL, line separator, and paragraph separator, with CRLF consumed
  as one match, behavior independent of `(?U)`, quoted preservation, and
  character-class rejection matching Pine's Java regex behavior.
- Added `str.match()` support for Pine's `\v` and `\V` vertical-whitespace
  regex classes, including LF, VT, FF, CR, NEL, line separator, and paragraph
  separator, plus complements, character-class nesting, quoted preservation,
  and behavior independent of `(?U)`.
- Added `str.match()` support for two-digit `\xNN` and braced `\x{...}`
  hexadecimal regex references, including exact two-digit consumption,
  arbitrary leading zeros in braced scalar values, character-class and quoted
  behavior, ASCII/Unicode case-mode switching, and safe no-match handling for
  surrogate code-unit references.
- Extended `str.match()` case-insensitive compatibility through character
  classes. Literal atoms and ranges now use ASCII folding under `(?i)` and
  Unicode folding under `(?iU)` before negation and class intersections are
  applied, including scoped/toggled modes, predefined and POSIX expansions,
  general Unicode properties, quoted atoms, and fixed `\uHHHH` references.
  Unicode block properties retain exact membership under either mode.
- Corrected `str.match()` case-insensitive literal matching outside character
  classes. Global/scoped `(?i)` now folds ordinary ASCII literals only, while
  `(?iU)` enables Unicode-aware folding; `(?-i)`/`(?-U)` toggles, `\Q...\E`
  quoted literals, and fixed `\uHHHH` references follow the active scope.
- Added `str.match()` support for Pine/Java Unicode block properties in
  `\p{InBlockName}` and `\p{Block=BlockName}` form, including `\P` negation,
  Java block aliases, character-class nesting, quoted preservation, and the
  Unicode 16.0 block range set. Block membership is independent of `(?U)`;
  script and general-category properties retain their ordinary behavior.
- Corrected `str.match()` Java/Pine POSIX `\p{...}` and `\P{...}` classes to
  use ASCII definitions by default and Unicode compatibility definitions under
  global/scoped `(?U)`, including `(?-U)` restoration, character-class nesting,
  quoted preservation, and Unicode-mode case-insensitive POSIX names.
- Corrected `str.match()` default-dot behavior to exclude Pine's complete line
  terminator set (LF, CR/CRLF, U+0085, U+2028, and U+2029), while preserving
  global/scoped `(?s)` dotall mode, `(?-s)` restoration, and literal dots in
  escapes, character classes, and `\Q...\E` quotes.
- Added `str.match()` support for Pine's fixed four-hex-digit `\uHHHH` Unicode
  regex references inside and outside character classes, including exact
  four-digit consumption and preservation inside `\Q...\E` quoted regions.
- Corrected `str.match()` end-anchor behavior. Default `$` and `\Z` now match
  before a final newline without returning that line terminator, while `\z`
  remains absolute-end-only; global/scoped multiline mode and explicit final
  newline matches retain their distinct behavior.
- Added `str.match()` support for `\Q...\E` literal regex quoting, including
  metacharacters, backslashes, quoted class delimiters, whitespace and comments
  in verbose mode, resumption of regex syntax after `\E`, and quotes extending
  to the pattern end when `\E` is omitted.
- Added `str.match()` support for Pine's `\h` and `\H` horizontal-whitespace
  regex classes, including the complete fixed Unicode character set, character
  class nesting, and identical behavior with Unicode-aware mode enabled or
  disabled.
- Corrected `str.match()` predefined regex class behavior. `\d`, `\w`, `\s`,
  their complements, and word boundaries now default to ASCII semantics, while
  global or scoped `(?U)` enables Unicode-aware matching without accidentally
  changing quantifier greediness; `(?-U)` restores the default within the
  corresponding scope. The implementation retains the linear-time Rust regex
  engine.
- Corrected the `str.format()` `percent` number preset to its grouped
  whole-number `#,###%` behavior while retaining explicit fractional precision
  for custom percent placeholders.
- Corrected predefined `format.percent` string conversion to append `%` after
  two-decimal rounding without multiplying the input by 100. Custom formatting
  strings with a trailing `%` token retain their existing scaling behavior.
- Corrected `str.tostring(..., format.volume)` to abbreviate numeric scalars,
  array elements, and matrix cells with K/M/B/T suffixes and volume precision,
  including whole values below 1000 and suffix promotion at rounded thresholds.
- Corrected `str.tostring(..., format.mintick)` to round numeric scalars, array
  elements, and matrix cells to the fixed `syminfo.mintick = 0.01` subset,
  including negative half-tick ties rounding up and two trailing decimal places.
- Added `str.tostring()` support for float, int, bool, and string matrices.
  Matrix rows use nested brackets, numeric formats apply per cell, and empty
  row/column shapes are preserved; color matrices and direct matrix arguments
  to `str.format()` remain semantically rejected.
- Corrected `str.trim(na)` to return an empty string, matching the helper's
  existing all-whitespace result instead of propagating `na`. ASCII trimming
  and preservation of non-ASCII whitespace remain unchanged.
- Corrected the shared date/time formatter's `W` week-of-month token. It now
  groups days 1–7 through 29–31 into values `1..5`, so late dates in some
  31-day months no longer produce an out-of-range sixth week; both
  `str.format_time()` and UTC date placeholders are covered.
- Corrected `str.format_time()` handling for a `na` timestamp. The function now
  replaces the missing value with `0` and formats the UNIX epoch through the
  same UTC, fixed-offset, or IANA timezone path, while `na` format and timezone
  arguments retain their documented defaults.
- Corrected `h`/`hh` formatting at midnight and noon in the shared date/time
  formatter. The 12-hour value now follows the documented `0..11` range, with
  `hh` adding a leading zero and `a` continuing to distinguish `AM` from `PM`;
  both `str.format_time()` and UTC date/time placeholders are covered.
- Corrected `S`/`SS`/`SSS` millisecond formatting in the shared date/time
  formatter. Single `S` now preserves the complete millisecond value, while
  repeated tokens add leading zeroes to the requested minimum width without
  truncating values; both `str.format_time()` and UTC date/time placeholders
  are covered.
- Corrected doubled-apostrophe handling in shared date/time format patterns.
  Both `str.format_time()` and UTC `str.format()` date/time placeholders now
  render `''` as one literal apostrophe, including inside quoted text such as
  `'o''clock'`, while preserving existing quoted-token behavior.
- Added short `z`/`zz`/`zzz` timezone-name tokens to `str.format_time()`.
  IANA zones render timestamp-specific abbreviations such as `EST` or `EDT`,
  while UTC and fixed offsets render stable `UTC` or `GMT±HH:mm` text. Full
  localized `zzzz` names remain outside the current timezone-data subset.
- Added IANA timezone tokens to the const `timestamp(dateString)` overload.
  Named zones share numeric-calendar timestamp resolution: repeated local times
  select the earlier absolute instant and nonexistent local times shift forward
  by the actual offset jump. Invalid zone names remain runtime errors.
- Added IANA timezone support to numeric-calendar `timestamp()` calls. Named
  zones use historical DST rules after calendar overflow normalization;
  repeated local times select the earlier absolute instant, and nonexistent
  local times shift forward by the offset jump. Invalid zone names remain
  runtime errors.
- Added IANA timezone support to explicit time-based sessions in `time()` and
  `time_close()`. Session membership and close clipping follow the named zone's
  timestamp-specific DST offset; repeated close times use the later instant,
  while close times inside a forward DST gap advance to the first valid local
  minute. Invalid zone names remain runtime errors.
- Added IANA timezone support to `str.format_time()`. Named zones resolve their
  offset at the supplied absolute timestamp, preserving DST, local date
  rollover, and the matching numeric `Z` offset in formatted output. Invalid
  zone names remain runtime errors; exchange-timezone defaults remain outside
  the fixed runtime metadata model.
- Added IANA timezone support to the calendar component functions `year()`,
  `month()`, `weekofyear()`, `dayofmonth()`, `dayofweek()`, `hour()`,
  `minute()`, and `second()`. Named zones such as `America/New_York` and
  `Asia/Tokyo` resolve their offset at the supplied absolute timestamp, so DST
  and local date rollover are preserved. Invalid zone names remain runtime
  errors; `timestamp()`, `str.format_time()`, time/session functions, and
  exchange-timezone defaults remain separate unsupported IANA boundaries.
- Corrected `time()` and `time_close()` W/2W through 52W and M/2M through
  12M boundaries to use the same UTC calendar groups as `timeframe.change()`.
  Weekly periods now open on Monday, monthly periods use real calendar-month
  lengths, and `timeframe_bars_back` shifts whole requested calendar groups.
  Intraday/day buckets, chart-space `bars_back`, fixed-offset session clipping,
  and public output schemas are unchanged.
- Corrected `timeframe.change()` weekly and monthly boundary detection. `W`
  through `52W` now use UTC Monday-based calendar-week groups, while `M`
  through `12M` use UTC calendar-month groups instead of fixed Unix-epoch
  second buckets. Intraday and daily change detection, first-bar behavior,
  empty/default timeframe handling, and `na` propagation are unchanged.
- Added terminal `.put_all(source)` to every concrete scalar map call result,
  completing the registered scalar map helper set on those receivers. It
  requires an identical source template, clones source entries for self-merge
  safety, replaces values without moving retained keys, appends new keys in
  source order, returns `void`, and cannot continue. Local aliases update
  shared storage; fresh constructor, copy, imported-function, and imported-
  method targets isolate the merge. Invalid source/template/arity, UDF side-
  effect, and public-schema boundaries retain ordinary `map.put_all` behavior.
- Added terminal `.remove(key)` to every concrete scalar map call result. It
  validates the resolved key kind, deletes a matching entry without reordering
  retained keys, no-ops for a missing key, returns `void`, and cannot continue.
  Local UDF and local user-method aliases update shared storage; fresh
  constructor, copy, imported-function, and imported-method results isolate the
  removal. Invalid key/arity, UDF side-effect, remaining map-mutation, template,
  and public-schema boundaries retain ordinary `map.remove` behavior.
- Added terminal `.clear()` to every concrete scalar map call result. It
  empties the resolved backing entry list, returns `void`, and cannot continue.
  Local UDF and local user-method aliases update shared storage; fresh
  `map.new`, `map.copy`, imported-function, and imported-method results isolate
  the clear. Arity, UDF side-effect, remaining map-mutation, template, and
  public-schema boundaries retain ordinary `map.clear` behavior.
- Added terminal `.put(key, value)` to every concrete scalar map call result:
  supported `map.new<K,V>`, `map.copy(existing)`, local/imported pure functions,
  and local/imported user methods. It reuses concrete key/value validation,
  replaces an existing value without moving the key or appends a new insertion-
  order entry, returns `void`, and cannot continue. Local UDF and local user-
  method aliases update shared storage; fresh built-in and imported producers
  isolate the write. Invalid key/value/arity, UDF side-effect, remaining map-
  mutation, and public-schema boundaries are unchanged.
- Added terminal numeric-matrix `.sort(column?, order?)` to concrete matrix
  call results. It defaults to column 0 and ascending order, reorders complete
  rows with stable equal keys, places `na` last ascending and first descending,
  returns `void`, and cannot continue. Local UDF and local user-method alias
  results update shared storage; fresh namespace, bound-transform, imported-
  function, and imported-method results isolate the change. Column bounds/
  `na`, unsupported-order, upstream-`na`, UDF side effects, and public schemas
  retain ordinary `matrix.sort` boundaries. The namespace receiver signature
  is now explicitly numeric, matching existing method dispatch.
- Added terminal `.add_col(column, array_id)` to every concrete matrix call
  result. It validates a simple-int insertion index and an element-kind-
  matched array, copies the array into a new complete column—including into a
  zero-row matrix—while preserving row count and element kind, returns `void`,
  and cannot continue. Local UDF and local user-method alias results update
  shared shape; fresh namespace, bound-transform, imported-function, and
  imported-method results isolate the change. Bounds/`na` indexes, array-size
  and cell-budget errors, upstream-`na` evaluation, UDF side effects, and
  public schemas retain ordinary `matrix.add_col` boundaries.
- Added terminal `.add_row(row, array_id)` to every concrete matrix call
  result. It validates a simple-int insertion index and an element-kind-
  matched array, copies the array into a new complete row—including into a
  zero-column matrix—while preserving column count and element kind, returns
  `void`, and cannot continue. Local UDF and local user-method alias results
  update shared shape; fresh namespace, bound-transform, imported-function,
  and imported-method results isolate the change. Bounds/`na` indexes, array-
  size and cell-budget errors, upstream-`na` evaluation, UDF side effects, and
  public schemas retain ordinary `matrix.add_row` boundaries.
- Added terminal `.remove_col(column)` to every concrete matrix call result.
  It validates a simple-int column index, removes one complete column—including
  from a zero-row matrix—while preserving row count and element kind, returns
  `void`, and cannot continue. Local UDF and local user-method alias results
  update shared storage; fresh namespace, bound-transform, imported-function,
  and imported-method results isolate the shape change. Bounds/`na` indexes,
  upstream-`na` argument evaluation, UDF side effects, and public schemas
  retain ordinary `matrix.remove_col` boundaries.
- Added terminal `.remove_row(row)` to every concrete matrix call result. It
  validates a simple-int row index, removes one complete row—including from a
  zero-column matrix—while preserving column count and element kind, returns
  `void`, and cannot continue. Local UDF and local user-method alias results
  update shared storage; fresh namespace, bound-transform, imported-function,
  and imported-method results
  isolate the shape change. Bounds/`na` indexes, upstream-`na` argument
  evaluation, UDF side effects, and public schemas retain ordinary
  `matrix.remove_row` boundaries.
- Added terminal `.swap_columns(column1, column2)` to every concrete matrix
  call result. It validates two simple-int column indexes, swaps complete
  columns while preserving shape and element kind, returns `void`, and cannot
  continue. Local UDF and local user-method alias results update shared
  storage; fresh namespace, bound-transform, imported-function, and imported-
  method results isolate the write. Same-index no-op, bounds/`na` indexes,
  upstream-`na` argument evaluation, UDF side effects, and public schemas
  retain ordinary `matrix.swap_columns` boundaries.
- Added terminal `.swap_rows(row1, row2)` to every concrete matrix call
  result. It validates two simple-int row indexes, swaps complete rows while
  preserving shape and element kind, returns `void`, and cannot continue.
  Local UDF and local user-method alias results update shared storage; fresh
  namespace, bound-transform, imported-function, and imported-method results
  isolate the write. Same-index no-op, bounds/`na` indexes, upstream-`na`
  argument evaluation, UDF side effects, and public schemas retain ordinary
  `matrix.swap_rows` boundaries.
- Added terminal `.reshape(rows, columns)` to every concrete matrix call
  result. It preserves row-major cells while requiring the element count to
  remain unchanged, returns `void`, and cannot continue. Local UDF and local
  user-method alias results update shared shape; fresh namespace, bound-
  transform, imported-function, and imported-method results isolate the shape
  change. Simple-int, negative/`na`, count-mismatch, UDF side-effect, and
  upstream-`na` boundaries retain ordinary `matrix.reshape` behavior; public
  schemas are unchanged.
- Added terminal `.reverse()` to every concrete matrix call result. It reverses
  the row-major cell sequence in place without changing shape, returns `void`,
  and cannot continue. Local UDF and local user-method alias results update
  shared storage; fresh namespace, bound-transform, imported-function, and
  imported-method results isolate the reordering. Empty and upstream-`na`
  results, invalid arity, and UDF side-effect boundaries retain ordinary
  `matrix.reverse` behavior; public schemas are unchanged.
- Added terminal `.fill(value)` to every concrete matrix call result. It
  preserves the receiver's float/int/bool/string/color element kind, fills all
  cells in place, returns `void`, and cannot continue. Local UDF and local
  user-method alias results update shared storage; fresh namespace, bound-
  transform, imported-function, and imported-method results isolate the write.
  Empty and upstream-`na` results, invalid type/arity, and UDF side-effect
  boundaries retain ordinary `matrix.fill` behavior; public schemas are
  unchanged.
- Added terminal `.set(row, column, value)` to every concrete matrix call
  result. It preserves the receiver's float/int/bool/string/color element kind,
  simple-int indexes, bounds behavior, and `void`/no-continuation contract.
  Local UDF and local user-method alias results update shared storage; fresh
  namespace, bound-transform, imported-function, and imported-method results
  isolate the write from their sources. Upstream `na`, invalid type/arity, and
  UDF side-effect boundaries retain ordinary `matrix.set` behavior; public
  schemas are unchanged.
- Added mutating, array-returning `.concat(id2)` to every concrete array call
  result. It preserves the receiver kind or exact scalar-tree UDT identity,
  appends a same-kind source, returns the first array id, and may continue
  through the closed array-result chain. Alias and live-slice receivers update
  shared parent backing; fresh namespace/map/matrix snapshots remain source-
  independent. Empty and upstream-`na` behavior, the 100000-element limit,
  kind/identity/arity checks, and UDF side-effect rejection retain the existing
  `array.concat` contract; public schemas are unchanged.
- Added transforming `.sort_indices(order?, sort_field?)` to concrete same-
  local and same-imported scalar-tree UDT array call results. The compile-time
  root int/float/string field is resolved against the exact result identity;
  the operation returns a fresh stable `array<int>` of original indexes,
  leaves the source unchanged, and may continue through the existing closed
  int-array chain. Missing, unknown, dynamic, or unsupported fields and
  unresolved/non-scalar identities remain rejected; public schemas are
  unchanged.
- Added terminal top-level `.sort(order?, sort_field?)` to concrete array call
  results. Int/float/string results use ordinary stable ascending/default or
  descending ordering; same-local and same-imported scalar-tree UDT results
  require a compile-time root int/float/string field resolved against the exact
  identity. Alias/live-slice results reorder backing parents, while fresh map/
  matrix/`matrix.mult` snapshots remain independent. Empty and upstream-`na`
  results no-op after order evaluation. Unsupported kinds, field/order/arity,
  continuation, and UDF-side-effect boundaries remain closed, and public
  schemas are unchanged.
- Added terminal top-level `.fill(value, index_from?, index_to?)` to every
  concrete array call result. It validates the resolved scalar/object/
  `chart.point` kind or same-local/same-imported scalar-tree UDT identity and
  optional simple-int-compatible half-open bounds; omitted bounds fill the full
  result. Alias/live-slice writes reach backing parents, while fresh matrix/map/
  `matrix.mult` snapshots stay independent. Explicit `na`, negative, reversed,
  oversized, empty, and upstream-`na` cases no-op after all supplied arguments
  are evaluated. The mutation returns `void`, cannot continue, remains rejected
  inside UDFs, and does not widen public schemas.
- Added terminal top-level `.set(index, value)` to every concrete array call
  result. It preserves simple-int-compatible positive, in-range negative,
  explicit-`na`, empty, and out-of-range behavior; validates scalar/object/
  `chart.point` kind or same-local/same-imported scalar-tree UDT identity;
  replaces one slot without changing length; returns `void`; and cannot
  continue. Alias/live-slice writes reach backing parents, while fresh matrix/
  map/`matrix.mult` snapshots stay independent. Type/arity, upstream-`na`, and
  UDF-side-effect boundaries retain ordinary behavior; public schemas are
  unchanged.
- Added terminal top-level `.insert(index, value)` to every concrete array call
  result. It preserves simple-int-compatible positive, in-range negative, end,
  and `na` index behavior; validates scalar/object/`chart.point` kind or same-
  local/same-imported scalar-tree UDT identity; returns `void`; and cannot
  continue. Alias-returning results and nested live slices update backing
  parents, while fresh matrix/map/`matrix.mult` snapshots stay independent.
  Bounds, arity, value/identity, upstream-`na`, 100000-element capacity, and
  UDF-side-effect boundaries retain ordinary behavior; public schemas are
  unchanged.
- Added terminal top-level `.unshift(value)` to every concrete array call
  result. It validates scalar/object/`chart.point` kind or same-local/same-
  imported scalar-tree UDT identity, prepends one compatible value at the
  resolved result's start, returns `void`, and cannot continue. Alias-returning
  concat/local/imported results and nested live slices update backing parents;
  fresh matrix/map/`matrix.mult` snapshots remain independent. Invalid value/
  arity, upstream-`na`, 100000-element capacity, and UDF-side-effect boundaries
  retain ordinary behavior; public schemas are unchanged.
- Added terminal top-level `.push(value)` to every concrete array call result.
  It validates scalar/object/`chart.point` kind or same-local/same-imported
  scalar-tree UDT identity, appends one compatible value, returns `void`, and
  cannot continue. Alias-returning concat/local/imported array results and
  nested live slices update backing parents; fresh matrix/map/`matrix.mult`
  snapshots remain independent. Map-result keys/values and matrix-result row/
  column/eigenvalue continuations are also fixture-backed. Invalid value/arity,
  upstream-`na`, 100000-element capacity, and UDF-side-effect boundaries retain
  ordinary behavior; public schemas are unchanged.
- Added terminal top-level `.remove(index)` to every concrete array call result.
  It removes and returns the selected positive or in-range negative element
  with preserved scalar/object/`chart.point` kind or same-local/same-imported
  scalar-tree UDT identity. Explicit `na` indexes and upstream-`na` receivers
  return `na` without mutation; out-of-range indexes retain runtime errors.
  Alias-returning concat/local/imported function or method results and nested
  live slices delete from their backing parent; fresh matrix/map/`matrix.mult`
  snapshots remain independent. Index type/arity, terminal continuation, and
  UDF-side-effect boundaries are fixture-backed; public schemas are unchanged.
- Added terminal top-level `.shift()` to every concrete array call result. It
  removes and returns the first resolved scalar/object/`chart.point` or same-
  local/same-imported scalar-tree UDT element, preserves concrete UDT identity
  and remaining-element order, returns `na` for empty/upstream-`na`, and cannot
  continue. Alias-returning concat/local/imported function or method results
  and nested live slices shrink their backing parent; fresh matrix row/column/
  eigenvalue, map key/value, and array-returning `matrix.mult` snapshots remain
  independent. Invalid arity and UDF-side-effect boundaries are fixture-backed;
  public schemas are unchanged.
- Added terminal top-level `.pop()` to every concrete array call result. It
  removes and returns the final resolved scalar/object/`chart.point` or
  same-local/same-imported scalar-tree UDT element, preserves concrete UDT
  identity, returns `na` for empty/upstream-`na`, and cannot continue. Alias-
  returning concat/local/imported function or method results and nested live
  slices shrink their backing parent; fresh matrix row/column/eigenvalue, map
  key/value, and array-returning `matrix.mult` snapshots remain independent.
  Invalid arity and UDF-side-effect boundaries are fixture-backed; public
  schemas are unchanged.
- Added terminal top-level `.reverse()` to every concrete array call result.
  It returns `void`, cannot continue, reverses alias-returning `array.concat`
  and local/imported function or method results in place, and reorders only a
  nested live slice window in its parent. Fresh matrix row/column/eigenvalue,
  map key/value, and array-returning `matrix.mult` snapshots remain independent
  of their source collections. Static/cross-namespace/local/imported, scalar,
  object, `chart.point`, UDT, empty/upstream-`na`, invalid arity, terminal-
  continuation, and UDF-side-effect rejection boundaries are fixture-backed;
  public schemas are unchanged.
- Added terminal top-level `.clear()` to every concrete array call result. It
  returns `void`, cannot continue, clears alias-returning `array.concat` and
  local/imported function or method results in place, and deletes a nested live
  slice window from its parent. Fresh matrix row/column/eigenvalue, map key/
  value, and array-returning `matrix.mult` snapshots remain independent of
  their source collections. Static/cross-namespace/local/imported, scalar,
  object, `chart.point`, UDT, empty/upstream-`na`, invalid arity, terminal-
  continuation, and UDF-side-effect rejection boundaries are fixture-backed;
  public schemas are unchanged.
- Added transforming `.slice(index_from, index_to)` to every concrete array
  call result. The direct path preserves scalar/object/`chart.point` element
  kinds and same-local/same-imported scalar-tree UDT identity, returns the
  ordinary half-open shallow live parent window, mirrors parent and window
  writes in both directions, and can continue through the closed array helper
  set. Static/cross-namespace, matrix/map-derived, local/imported function or
  method, nested continuation, empty/upstream-`na`, invalid bounds/type/arity,
  and result-type-directed `matrix.mult` parser boundaries are fixture-backed.
- Added terminal `.join(separator?)` to every concrete scalar array call
  result and to same-local/same-imported scalar-tree UDT array results. The
  direct path preserves omitted/`na` comma fallback, explicit separators,
  scalar/color/UDT formatting, empty-string and upstream-`na` results, source
  non-mutation, and the existing 40960-character result limit. Static/cross-
  namespace, matrix/map-derived, local/imported function/method, UDT identity,
  invalid receiver/separator/arity, and terminal-continuation boundaries are
  fixture-backed.
- Added terminal `.some()` to every existing concrete bool, int, or float
  array call result. It returns fixed `series bool` when any nonzero numeric or
  `true` element exists, treats zero, `false`, and element `na` as
  nonsatisfying, returns false for empty arrays, propagates upstream `na`,
  leaves its source unchanged, and cannot continue through another postfix
  call. Static/cross-namespace, matrix/map-derived, local/imported function/
  method, invalid type/arity, terminal-continuation, empty/`na`, and UDT
  boundaries are fixture-backed.
- Added terminal `.every()` to every existing concrete bool, int, or float
  array call result. It returns fixed `series bool`, treats nonzero numerics
  and `true` as truthy, treats zero, `false`, and element `na` as false,
  returns true for empty arrays, propagates an upstream `na` array, leaves its
  source unchanged, and cannot continue through another postfix call. Static/
  cross-namespace, matrix/map-derived, local/imported function/method, invalid
  type/arity, terminal-continuation, empty/`na`, and UDT boundaries are
  fixture-backed.
- Added transforming `.sort_indices(order?)` to every existing concrete int,
  float, or string array call result. It returns an independent fixed
  `simple array<int>` of stable original indexes, preserves the established
  float-`na` and string-empty ordering, supports default ascending or explicit
  descending order, propagates upstream `na`, leaves its source unchanged, and
  can continue through the closed array-result helper set. Static/cross-
  namespace, matrix/map-derived, local/imported function/method, empty/`na`,
  nested continuation, invalid type/order/arity, source-independence, and UDT
  `sort_field` binding boundaries are fixture-backed.
- Added terminal `.stdev(biased?)` to every existing concrete numeric array
  call result. It returns the square root of the same filtered population or
  sample variance selected by default/`true` versus `false`/`na` bias.
  Single-value population standard deviation is zero; empty/all-`na`/upstream-
  `na`, insufficient-sample, and non-finite results return `na`. Static/cross-
  namespace, matrix/map-derived, local/imported function/method, invalid type/
  arity, non-mutation, provenance, and terminal-continuation paths are fixture-
  backed.
- Added terminal `.variance(biased?)` to every existing concrete numeric array
  call result. It filters `na`, returns fixed `series float`, uses population
  bias by default or for `true`, and sample bias for `false` or `na`.
  Single-value population variance is zero; empty/all-`na`/upstream-`na`,
  insufficient-sample, and non-finite results return `na`. Static/cross-
  namespace, matrix/map-derived, local/imported function/method, invalid type/
  arity, non-mutation, provenance, and terminal-continuation paths are fixture-
  backed.
- Added transforming `.standardize()` to every existing concrete numeric
  array call result. It returns an independent fixed `simple array<float>`,
  computes mean and population standard deviation over non-`na` values,
  preserves `na` positions, and maps numeric positions to `na` when deviation
  is zero or non-finite. Empty/all-`na` inputs return an empty array and
  upstream `na` propagates. Static/cross-namespace, matrix/map-derived,
  local/imported function/method, invalid type/arity, source independence, and
  copy/abs/standardize continuation paths are fixture-backed.
- Added terminal `.covariance(id2, biased?)` to every existing concrete
  numeric array call result. It requires a same-length numeric second array,
  pairs original indexes, filters pairs containing `na`, defaults to the
  population denominator, and uses the sample denominator for `false` or `na`
  bias. It returns fixed `series float`; empty/all-`na`/upstream-`na`, length-
  mismatch, insufficient-sample, and non-finite results return `na`. The read
  remains non-mutating and terminal. Static/cross-namespace, matrix/map-derived,
  local/imported function/method, invalid type/arity, provenance, and
  continuation paths are fixture-backed.
- Added terminal `.percentrank(index)` to every existing concrete numeric
  array call result. It selects the target from the original array index,
  filters `na` only from the comparison population, counts duplicates
  independently, and returns fixed `series float`. Positional or named simple-
  int-compatible indexes are accepted. Empty/all-`na`/upstream-`na`, target-
  `na`, runtime typed-`na`, negative, and out-of-range indexes return `na`; the
  read remains non-mutating and terminal. Static/cross-namespace, matrix/map-
  derived, local/imported function/method, invalid type/arity, provenance, and
  continuation paths are fixture-backed.
- Added terminal `.percentile_linear_interpolation(percentage)` to every
  existing concrete numeric array call result. It filters and sorts values,
  interpolates at `percentage / 100 * (count - 1)`, and always returns
  `series float` for integer, float, and single-element inputs. Positional or
  named series/simple numeric percentages are accepted. Empty/all-`na`/
  upstream-`na`, runtime typed-`na`, out-of-range, and non-finite results return
  `na`; the read remains non-mutating and terminal. Static/cross-namespace,
  matrix/map-derived, local/imported function/method, invalid type/arity,
  provenance, and continuation paths are fixture-backed.
- Added terminal `.percentile_nearest_rank(percentage)` to every existing
  concrete numeric array call result. It filters and sorts values, uses
  ceiling-based nearest-rank selection with 0/100 endpoints, preserves the
  receiver-derived `series int`/`series float`, and accepts positional or named
  series/simple numeric percentages. Empty/all-`na`/upstream-`na`, runtime
  typed-`na`, negative, and above-100 percentages return `na`; the read remains
  non-mutating and terminal. Static/cross-namespace, matrix/map-derived, local/
  imported function/method, invalid type/arity, provenance, and continuation
  paths are fixture-backed.
- Added terminal `.mode()` to every existing concrete numeric array call
  result. It filters `na`, returns the most frequent value in the receiver-
  derived `series int`/`series float` kind, chooses the smaller value for tied
  frequencies, and requires at least one repeated value. Empty/all-`na`/
  upstream-`na` and all-unique arrays return `na`; the read remains non-
  mutating and terminal. Static/cross-namespace, matrix/map-derived, local/
  imported function/method, invalid type/arity, provenance, and terminal-
  continuation paths are fixture-backed.
- Added terminal `.median()` to every existing concrete numeric array call
  result. It filters `na`, sorts remaining values, returns the middle value for
  odd counts and the middle-pair arithmetic mean for even counts, preserves
  receiver-derived `series int`/`series float`, and truncates integer means
  toward zero. Empty/all-`na`/upstream-`na` arrays and non-finite float results
  return `na`. Static/cross-namespace, matrix/map-derived, local/imported
  function/method, invalid type/arity, provenance, and terminal-continuation
  paths are fixture-backed.
- Added terminal `.range()` to every existing concrete numeric array call
  result. It returns filtered maximum minus minimum with receiver-derived
  `series int`/`series float`, yields `na` for empty/all-`na`/upstream-`na` or
  non-finite float differences, and remains non-mutating. Static/cross-
  namespace, matrix/map-derived, local/imported function/method, invalid type/
  arity, and terminal-continuation paths are fixture-backed.
- Added terminal `.avg()` to every existing concrete numeric array call result.
  It ignores `na`, always returns `series float`, yields `na` for empty/all-
  `na`/upstream-`na` or non-finite results, and remains non-mutating. Static/
  cross-namespace, matrix/map-derived, local/imported function/method, invalid
  type/arity, and terminal-continuation paths are fixture-backed.
- Added terminal `.sum()` to every existing concrete numeric array call result.
  It preserves receiver-derived `series int`/`series float`, ignores `na`
  elements, returns `na` for empty/all-`na`/upstream-`na` arrays, and remains
  non-mutating. Static/cross-namespace, matrix/map-derived, local/imported
  function/method, invalid type/arity, and terminal-continuation paths are
  fixture-backed.
- Added terminal `.max(nth?)` to every existing concrete numeric array call
  result. It mirrors `.min(nth?)` with descending zero-based rank order while
  preserving receiver-derived `series int`/`series float`, filtered `na`,
  duplicate ranks, dynamic integer ranks, and `nth=0` as the maximum. Empty/
  all-`na`/upstream-`na` arrays and `na`, negative, or out-of-range ranks return
  `na`. Static/cross-namespace, matrix/map-derived, local/imported function/
  method, invalid type/arity, and terminal-continuation paths are fixture-backed.
- Added terminal `.min(nth?)` to every existing concrete numeric array call
  result. It returns the receiver element's `series int` or `series float`,
  filters `na`, ranks remaining values in ascending zero-based order, accepts
  dynamic integer ranks, and defaults to rank `0`. Empty/all-`na`/upstream-`na`
  arrays and `na`, negative, or out-of-range ranks return `na`. Static/cross-
  namespace, matrix/map-derived, local/imported function/method, int/float,
  rank binding, invalid type/arity, and terminal-continuation paths are fixture-
  backed.
- Added `.abs()` to every existing concrete numeric array call result. It
  allocates a fresh same-kind int/float array, preserves `na` elements, leaves
  the source unchanged, returns an empty array for an empty receiver, and
  propagates an upstream `na` array. The result can continue through current
  array readers, `.copy()`, or another `.abs()`. Static/cross-namespace,
  numeric matrix/map-derived, local/imported function/method, invalid type/
  arity, nonnumeric/UDT, empty/`na`, independence, and continuation paths are
  fixture-backed.
- Added terminal `.binary_search_rightmost(value)` to every existing concrete
  numeric array call result. Exact duplicates return their last index; misses
  return the nearest-right element index, clamped to `0` below the minimum and
  the last index above the maximum. It retains the numeric/ascending gates,
  empty/upstream-`na` `-1`, fixed `simple int`, non-mutation, and terminal
  boundaries. Registered static/cross-namespace, numeric matrix/map-derived,
  local/imported function/method, nonnumeric/UDT rejection, invalid type/arity,
  copy-continuation, and terminal-continuation paths are fixture-backed.
- Added terminal `.binary_search_leftmost(value)` to every existing concrete
  numeric array call result. It preserves the numeric receiver/value and caller-
  owned ascending-input gates. Exact duplicates return their first index;
  misses return the nearest-left element index, clamped to `0` below the minimum
  and the last index above the maximum. Empty and upstream-`na` arrays return
  `-1`; the `simple int` result is non-mutating and terminal. Registered static/
  cross-namespace, numeric matrix/map-derived, local/imported function/method,
  clamp, nonnumeric/UDT rejection, invalid type/arity, copy-continuation, and
  terminal-continuation paths are fixture-backed.
- Added terminal `.binary_search(value)` to every existing concrete numeric
  array call result. Registered static/cross-namespace producers, qualified and
  unqualified local/imported UDF and method results, numeric matrix row/column/
  eigenvalue/mult arrays, and numeric map key/value arrays retain the ordinary
  numeric receiver/value checks. Callers provide ascending contents; exact
  lower-bound search returns the leftmost duplicate match as `simple int` or
  `-1` for missing, empty, and upstream-`na` arrays. The helper is non-mutating
  and terminal, while bool/string/color, drawing/chart-point, and UDT result
  arrays remain rejected. Invalid type/arity, copy continuation, provenance/
  dual-alias, and terminal-continuation boundaries are fixture-backed.
- Added terminal `.lastindexof(value)` last-index searches to every existing
  concrete array call result. It covers qualified and unqualified local/
  imported UDF and method results, registered static `array.*` producers, the
  seven cross-namespace scalar-array producers, matrix row/column/eigenvalue
  arrays, map key/value arrays, and array-returning `matrix.mult` overloads.
  The helper reuses ordinary element-kind and same-identity UDT validation plus
  structural/object equality, returns the last zero-based match as `simple
  int`, returns `-1` for missing or empty concrete arrays and for upstream
  `na`, performs no mutation, and creates no continuation prefix. Repeated
  scalar and structural-UDT values, A-to-B-to-A and dual-alias isolation, copy
  continuation, wrong type/identity, invalid arity, and terminal-continuation
  boundaries are fixture-backed.
- Added terminal `.indexof(value)` first-index searches to every existing
  concrete array call result. It covers qualified and unqualified local/
  imported UDF and method results, registered static `array.*` producers, the
  seven cross-namespace scalar-array producers, matrix row/column/eigenvalue
  arrays, map key/value arrays, and array-returning `matrix.mult` overloads.
  The helper reuses ordinary element-kind and same-identity UDT validation plus
  structural/object equality, returns the first zero-based match as `simple
  int`, returns `-1` for missing or empty concrete arrays and for upstream
  `na`, performs no mutation, and creates no continuation prefix. Scalar,
  drawing/chart-point, local/imported UDT, A-to-B-to-A, dual-alias isolation,
  copy continuation, wrong type/identity, invalid arity, and terminal-
  continuation boundaries are fixture-backed.
- Added terminal `.includes(value)` membership checks to every existing
  concrete array call result: qualified and unqualified local/imported UDF and
  method results, registered static `array.*` producers, the seven
  cross-namespace scalar-array producers, matrix row/column/eigenvalue arrays,
  map key/value arrays, and array-returning `matrix.mult` overloads. The helper
  reuses ordinary element-kind and same-identity UDT argument validation plus
  structural/object equality, returns `series bool`, is false for an empty
  concrete array, propagates an upstream `na` array, performs no mutation, and
  creates no continuation prefix. Scalar, drawing/chart-point, local/imported
  UDT, A-to-B-to-A, dual-alias isolation, copy continuation, wrong type/
  identity, invalid arity, and terminal-continuation boundaries are fixture-
  backed.
- Added result-type-directed `.mult(other)` continuation to every existing
  concrete numeric matrix call result. Matrix and scalar operands return
  independent `matrix<float>` results with multiplied or receiver-preserved
  shape; numeric-array operands return independent `array<float>` results with
  one value per receiver row. The resolved result selects the closed matrix or
  array helper set while retaining numeric operand checks, `na`, zero-inner-
  dimension, multiplication order, matrix cell-budget, matrix-dimension, and
  vector-length behavior. Namespace and bound operations, local/imported
  functions and methods, int-to-float lowering, nested multiplication, source
  independence, provenance, dual aliases, invalid types/arity, and runtime
  failure boundaries are fixture-backed; mutation and the remaining matrix-
  valued helpers stay gated.
- Added matrix-valued `.diff(other)` continuation to every existing concrete
  numeric matrix call result. It retains the numeric receiver and numeric-
  matrix-or-scalar operand checks, always returns an independent
  `matrix<float>`, preserves receiver shape and left-to-right subtraction,
  propagates `na` cells, `na` scalars, and upstream `na`, preserves zero
  dimensions, keeps the matching-shape runtime error for matrix operands, and
  retains the matrix-result prefix. Namespace and bound operations, local/
  imported functions and methods, int-to-float lowering, nested differences,
  scalar and matrix operands, source independence, provenance, dual aliases,
  invalid types/arity, and runtime failure boundaries are fixture-backed;
  mutation and the remaining matrix-valued helpers stay gated.
- Added matrix-valued `.kron(other)` continuation to every existing concrete
  numeric matrix call result. It retains the numeric receiver and numeric-
  matrix operand checks, always returns an independent `matrix<float>`,
  multiplies both source row and column dimensions, preserves `na` cells and
  zero dimensions, propagates upstream `na`, keeps the matrix cell-budget
  error, and retains the matrix-result prefix. Namespace and bound operations,
  local/imported functions and methods, int-to-float lowering, nested
  Kronecker products, source independence, provenance, dual aliases, invalid
  types/arity, and runtime failure boundaries are fixture-backed; mutation and
  the remaining matrix-valued helpers stay gated.
- Added matrix-valued `.pow(power)` continuation to every existing concrete
  numeric matrix call result. It retains the numeric receiver and simple-int
  power checks, always returns an independent `matrix<float>`, preserves the
  runtime square-matrix boundary, supports identity/copy/positive powers and
  empty `0 x 0`, preserves `na` cells for positive powers, retains negative and
  `na` power errors, and keeps the matrix-result prefix. Namespace and bound
  operations, local/imported functions and methods, int-to-float lowering,
  nested powers, source independence, provenance, dual aliases, invalid types/
  arity, and runtime failure boundaries are fixture-backed; mutation and the
  remaining matrix-valued helpers stay gated.
- Added matrix-valued `.eigenvectors()` continuation to every existing
  concrete numeric matrix call result. It retains the numeric receiver check,
  always returns an independent `matrix<float>`, preserves square shape for a
  complete real eigenvector basis, returns empty `0 x 0`, retains the runtime
  non-square error, yields `na` for invalid-cell, non-finite, non-real,
  incomplete, or upstream-`na` results, and retains the matrix-result prefix.
  Namespace and bound operations, local/imported functions and methods, int-
  to-float lowering, nested/double chains, source independence, provenance,
  dual aliases, invalid types/arity, and runtime failure boundaries are
  fixture-backed; mutation and the remaining matrix-valued helpers stay gated.
- Added matrix-valued `.pinv()` continuation to every existing concrete
  numeric matrix call result. It retains the numeric receiver check, always
  returns an independent `matrix<float>`, swaps rectangular row/column counts,
  preserves singular matrix-valued results and swapped zero-cell shapes,
  yields `na` for invalid-cell, non-finite, or upstream-`na` inputs, and
  retains the matrix-result prefix. Namespace and bound operations,
  local/imported functions and methods, int-to-float lowering, nested and
  double-pseudo-inverse chains, source independence, provenance, dual aliases,
  invalid types/arity, and rectangular/singular/zero-cell boundaries are
  fixture-backed; mutation and the remaining matrix-valued helpers stay gated.
- Added matrix-valued `.inv()` continuation to every existing concrete numeric
  matrix call result. It retains the numeric receiver check, always returns an
  independent `matrix<float>`, preserves square shape for invertible inputs,
  returns an empty `0 x 0` matrix for empty input, yields `na` for singular,
  invalid-cell, non-finite, or upstream-`na` inputs, and retains the matrix-
  result prefix for further supported continuations and readers. Namespace and
  bound operations, local/imported functions and methods, int-to-float
  lowering, nested chains, source independence, provenance, dual aliases,
  invalid types/arity, and the runtime non-square boundary are fixture-backed;
  mutation and the remaining matrix-valued helpers stay gated.
- Added matrix-valued `.submatrix(...)` continuation to every existing
  concrete matrix call result. It preserves float/int/bool/string/color
  element kinds, returns an independent half-open range with optional/default
  bounds, preserves empty row/column shapes, propagates upstream `na`, and may
  continue through `.copy()`, `.submatrix(...)`, `.transpose()`, or any
  supported matrix reader. Namespace and bound operations, exact templates,
  local/imported functions and methods, named arguments, nested ranges, five-
  kind reads, source independence, invalid types/arity, runtime bounds,
  provenance, and dual aliases are fixture-backed; mutation and the remaining
  matrix-valued helpers stay gated.
- Added matrix-valued `.transpose()` continuation to every existing concrete
  matrix call result. It preserves float/int/bool/string/color element kinds,
  returns an independent matrix with swapped row/column counts, propagates
  upstream `na`, and may continue through `.copy()`, another `.transpose()`, or
  any supported terminal/array-producing matrix reader. Namespace and bound
  operations, exact templates, local/imported functions and methods, empty
  shapes, five-kind reads, source independence, invalid arity, provenance, and
  dual aliases are fixture-backed; mutation and the remaining broader matrix-
  valued helpers stay gated.
- Added terminal `.rank()` reads to every existing concrete numeric matrix call
  result. The helper retains the float/int check and fixed `series int` result,
  supports rectangular and singular matrices, returns `0` for zero-element
  matrices, and returns `na` for invalid/non-finite cells or upstream `na`.
  Copy continuation, producer provenance, dual aliases, non-numeric rejection,
  invalid arity, and terminal continuation are fixture-backed.
- Added terminal `.det()` reads to every existing concrete numeric matrix call
  result. The helper retains the float/int check and fixed `series float`
  result, the runtime square-matrix boundary, `0 x 0 = 1.0`, singular zero,
  invalid-cell/non-finite `na`, and upstream-`na` propagation without adding
  static shape inference. Copy continuation, producer provenance, dual aliases,
  non-numeric rejection, invalid arity, and terminal continuation are fixture-
  backed.
- Added terminal `.trace()` reads to every existing concrete numeric matrix
  call result. The helper retains the float/int check and fixed `series float`
  result, sums non-`na` main-diagonal cells across rectangular matrices, and
  returns `na` for an empty/all-`na` diagonal, non-finite sum, or upstream-`na`
  result. Copy continuation, producer provenance, dual aliases, non-numeric
  rejection, invalid arity, and terminal continuation are fixture-backed.
- Added terminal `.mode()` reads to every existing concrete numeric matrix call
  result. The helper retains the float/int check and fixed `series float`
  result, ignores `na` cells, selects the smaller value on an equal-frequency
  tie, and returns `na` for empty, all-`na`, no-repeat, non-finite, or upstream-
  `na` results. Copy continuation, producer provenance, dual aliases, non-
  numeric rejection, invalid arity, and terminal continuation are fixture-
  backed.
- Added terminal `.max()` reads to every existing concrete numeric matrix call
  result. The helper retains the float/int check and fixed `series float`
  result, scans only non-`na` cells, and returns `na` for empty, all-`na`, non-
  finite, or upstream-`na` results. Copy continuation, producer provenance,
  dual aliases, non-numeric rejection, invalid arity, and terminal continuation
  are fixture-backed.
- Added terminal `.min()` reads to every existing concrete numeric matrix call
  result. The helper retains the float/int check and fixed `series float`
  result, scans only non-`na` cells, and returns `na` for empty, all-`na`, non-
  finite, or upstream-`na` results. Copy continuation, producer provenance,
  dual aliases, non-numeric rejection, invalid arity, and terminal continuation
  are fixture-backed.
- Added terminal `.avg()` reads to every existing concrete numeric matrix call
  result. The helper retains the float/int check and fixed `series float`
  result, averages only non-`na` cells, and returns `na` for empty, all-`na`,
  non-finite, or upstream-`na` results. Copy continuation, producer provenance,
  dual aliases, non-numeric rejection, invalid arity, and terminal continuation
  are fixture-backed.
- Added terminal `.sum()` reads to every existing concrete numeric matrix call
  result. The helper retains the float/int check and fixed `series float`
  result, ignores `na` cells, and returns `na` for empty, all-`na`, non-finite,
  or upstream-`na` results. Copy continuation, producer provenance, dual
  aliases, non-numeric rejection, invalid arity, and terminal continuation are
  fixture-backed.
- Added terminal `.is_stochastic()` reads to every existing concrete numeric
  matrix call result. The helper retains the float/int check and ordinary
  stochastic rule: a non-empty matrix of finite non-negative values is true
  when every row or every column sums exactly to one; empty matrices, invalid
  cells, and negative values are false, while upstream `na` matrices propagate
  `na`. Producer provenance, dual aliases, non-numeric rejection, invalid
  arity, and terminal continuation are fixture-backed.
- Added terminal `.is_antisymmetric()` reads to every existing concrete numeric
  matrix call result. The helper retains the float/int check and ordinary
  antisymmetric rule: square shape, exact-zero main diagonal, exact negated
  transposed pairs, false for any `na`, and true for empty 0×0 results;
  upstream `na` matrices propagate `na`. Producer provenance, dual aliases,
  non-numeric rejection, invalid arity, and terminal continuation are fixture-
  backed.
- Added terminal `.is_symmetric()` reads to every existing concrete numeric
  matrix call result. The helper retains the float/int check and ordinary
  symmetric rule: square shape, exact transposed-pair equality, false for any
  `na`, and true for empty 0×0 results; upstream `na` matrices propagate `na`.
  Producer provenance, dual aliases, non-numeric rejection, invalid arity, and
  terminal continuation are fixture-backed.
- Added terminal `.is_identity()` reads to every existing concrete numeric
  matrix call result. The helper retains the float/int check and ordinary
  identity rule: square shape, exact-one main diagonal, exact-zero off-
  diagonal cells, false for any `na`, and true for empty 0×0 results; upstream
  `na` matrices propagate `na`. Producer provenance, dual aliases, non-numeric
  rejection, invalid arity, and terminal continuation are fixture-backed.
- Added terminal `.is_diagonal()` reads to every existing concrete numeric
  matrix call result. The helper retains the float/int check and ordinary
  rectangular-diagonal rule: only off-diagonal cells must be exactly zero,
  diagonal `na` is allowed, off-diagonal `na` is false, and empty results are
  true; upstream `na` matrices propagate `na`. Producer provenance,
  dual aliases, non-numeric rejection, invalid arity, and terminal continuation
  are fixture-backed.
- Added terminal `.is_binary()` reads to every existing concrete numeric
  matrix call result. The helper retains the float/int type check and ordinary
  strict 0-or-1 rules: binary and zero-element results are true, another value
  or `na` cell is false, and an upstream `na` matrix result propagates `na`.
  Namespace/bound operations, exact numeric templates, local/imported function
  and method provenance, dual aliases, non-numeric rejection, invalid arity,
  and terminal continuation are fixture-backed.
- Added terminal `.is_zero()` reads to every existing concrete numeric matrix
  call result. The helper retains the float/int matrix check and ordinary
  zero-value rules: all-zero and zero-element results are true, a nonzero or
  `na` cell is false, and an upstream `na` matrix result propagates `na`.
  Namespace/bound operations, exact numeric templates, local/imported function
  and method provenance, dual aliases, non-numeric rejection, invalid arity,
  and terminal continuation are fixture-backed.
- Added terminal `.is_square()` reads to every existing concrete matrix call
  result. The helper accepts float/int/bool/string/color matrices, returns a
  simple bool, preserves the ordinary `matrix.is_square` shape rule, and does
  not create another postfix receiver. Namespace/bound operations, exact
  `matrix.new<T>` templates, local and imported function or method provenance,
  true/false shapes, dual aliases, invalid arity, and terminal continuation are
  fixture-backed.
- Added direct `.eigenvalues()` reads to concrete numeric matrix call results.
  The method preserves the existing numeric-matrix type check and square-
  matrix runtime boundary, returns a fresh `array<float>`, and supports direct
  binding plus `.size()`/`.get()`/`.first()`/`.last()`/`.copy()` with copy-only
  array continuation. Namespace/bound operations, local and imported function
  or method provenance, dual aliases, source independence, non-numeric
  rejection, and call-result-array mutation rejection are fixture-backed.
- Added direct `.col(index)` reads to every existing concrete matrix call-
  result producer. Each read returns a fresh element-kind-preserving scalar
  array with the same direct binding, array-reader, copy-only continuation,
  source-independence, five-kind, and dual-alias guarantees as call-result
  `.row(index)`. Column index checks, call-result-array mutation rejection, and
  the retained broader-matrix-helper boundary are fixture-backed.
- Added direct `.row(index)` reads to every existing concrete matrix call-result
  producer, including namespace and bound matrix operations, exact
  `matrix.new<float|int|bool|string|color>` templates, local UDFs, local and
  imported user methods, and registered imported functions. Each read returns
  a fresh element-kind-preserving scalar array that supports direct binding and
  `.size()`/`.get()`/`.first()`/`.last()`/`.copy()` with copy-only array
  continuation. Index type checks, source independence, all five scalar matrix
  kinds, dual aliases, and mutation boundaries are fixture-backed.
- Added direct `.values()` reads for every existing concrete scalar-map call
  result. The result is a fresh value-kind-preserving scalar array with the
  same direct binding, `.size()`/`.get()`/`.first()`/`.last()`/`.copy()`, copy-
  only continuation, dual-alias, and source-map-independence guarantees as
  call-result `.keys()`. Map or call-result-array mutation, unsupported
  templates, broader helpers, and terminal key/value-reader continuation
  remain gated.
- Added direct `.keys()` reads for every existing concrete scalar-map call
  result, including supported `map.new<K,V>`, `map.copy(existing)`, local and
  imported pure functions, and local and imported user methods. The result is
  a fresh key-kind-preserving scalar array that supports direct binding and
  `.size()`/`.get()`/`.first()`/`.last()`/`.copy()` with copy-only array
  continuation. Direct `.values()`, map or call-result-array mutation,
  unsupported templates, broader helpers, and terminal key-reader
  continuation remain gated.
- Extended qualified same-local user-method and imported UDF/user-method
  UDT-array call-result sugar with `.size()`, `.get(index)`, and `.last()`,
  alongside the existing `.first()` and `.copy()` paths. The new read-only
  accessors preserve simple-int or concrete UDT element return types through
  named indexes, nested copy chains, generic A-to-B-to-A calls, and two aliases
  of one library. Empty and typed-`na` results, `na` and negative indexes,
  precise `get` bounds errors, and explicit same-named local/imported or scalar
  UDT methods are fixture-backed. Unqualified local UDF results, mixed or
  non-scalar identities, other direct helpers, and call-result mutation remain
  gated.
- Added direct `.first()` and `.copy()` method sugar for qualified same-local
  user-method results carrying a concrete scalar-tree UDT-array identity.
  Receiver-style and type-qualified calls, independent `.first()` and
  `.copy().first()` First-to-Second-to-First sequences, generic UDF wrappers,
  and copy independence are fixture-backed. Parser-synthetic postfix calls stay
  distinct from explicit local methods named `first` or `copy`, including when
  the explicit argument is itself a method call. Unqualified local UDF results
  and helpers beyond the read-only `size`/`get`/`first`/`last`/`copy` set
  remain gated.
- Added direct `.first()` and `.copy()` method sugar for qualified imported UDF
  or user-method results that carry a concrete same-imported scalar-tree UDT
  array identity. Multi-segment `.copy().first()` chains, First-to-Second-to-
  First calls, two aliases of one library, and copy independence now lower and
  execute without binding the producer first. Import validation and rewriting
  preserve the parser's postfix receiver shape, while explicit same-named
  exports such as `lib.first(values)` and `lib.copy(values)` retain normal
  function dispatch, even when the same library also defines scalar UDT methods
  named `first` or `copy`; those scalar constructor, UDF-result, and
  method-result call chains remain user methods without a duplicated receiver,
  including method chains whose returned UDT identity differs from the input.
  Unqualified local UDF call-result receivers and direct array helpers beyond
  the read-only `size`/`get`/`first`/`last`/`copy` set remain explicitly
  rejected; namespace helpers stay available.
- Preserved same-local and same-imported scalar-tree UDT-array identity for
  every destructured UDT-array slot of tuple literals and local/imported UDF or
  user-method tuple returns. Direct, block, nested, final-control-flow,
  typed-`na`, typed-destination, A-to-B-to-A, and same-library dual-alias paths
  now lower and execute with the correct element layout; different identities
  may occupy different tuple slots. Tuple-valued ordinary declarations retain
  their element types and identities through direct and self aliases,
  ternary/`switch` results, assigned `if` results, shadowing, and later
  destructuring. The first declaration fixes each UDT-array slot identity;
  same-identity or `na` reassignment remains valid, while direct or
  control-flow reassignment to another identity and unresolved nested tuple
  consumers emit root-spanned `E_TUPLE_UDT_ARRAY_IDENTITY` diagnostics.
  Recursive tuple-declaration right-hand sides now stop after the existing
  recursion diagnostic instead of re-entering tuple type queries and
  overflowing the stack.
- Preserved same-local and same-imported scalar-tree UDT array element
  identities through ternary, `if`, `switch`, `for`, `for...in`, and `while`
  results, including array/`na` branches, block-local aliases, typed or
  inferred declarations, and caller-side helper or iteration consumption.
  Mixed UDT array identities now produce precise branch diagnostics instead of
  passing analysis without executable HIR. Generic UDF inlining now resolves
  UDT array parameters, flow aliases, array-element helpers, and reconstructed
  `array.from` values per call, preventing the final call's element layout from
  leaking into earlier calls. The local and imported UDF/method return slices
  below build on that call-specific identity model.
- Added fixture-backed imported UDF and user-method returns for same-imported
  scalar-tree UDT arrays. Direct and block-alias returns preserve the source
  array id, copy/new/from paths allocate independently, and private nested calls,
  final control flow, typed methods with named/reordered arguments, and imported
  type-position rewrites retain the caller's concrete identity. Source-aware
  import-instance metadata isolates interleaved calls through two aliases of the
  same physical library. Mixed imported identities, non-scalar returns,
  unqualified local UDF or direct call-result array methods outside the
  read-only `size`/`get`/`first`/`last`/`copy` set, and mutation
  through unsupported UDF/method side-effect contexts remain rejected;
  tuple-return conflicts are rejected per destructured UDT-array slot.
- Preserved scalar map templates at call sites when local UDFs return inferred
  map parameters, or when local UDFs and user methods return visible maps,
  block-local aliases, `map.new`/copy results, nested calls, or final
  control-flow results. The same generic UDF can now return different map
  templates at different call sites, including named and reordered arguments,
  without leaking span-cached metadata; callers can use namespace helpers,
  history, `for...in`, and map methods after binding the result. Function-body
  map mutation and direct call-result method chaining remain outside this slice.
- Preserved scalar map key/value templates through ternary, `if`, `switch`,
  `for`, `for...in`, and `while` expression results. This includes direct
  helper consumption, typed and inferred declarations, same-template
  reassignment, `map`/`na` branches, nested loop results, and block-local map or
  `na` aliases; different branch templates now produce `E_BRANCH_TYPE` instead
  of degrading into an unknown-template receiver error.
- Extended `array.min` and `array.max` with their optional zero-based `nth`
  order-statistic argument for int and float arrays. Namespace and method
  calls accept positional or named ranks, namespace arguments can be reordered,
  and dynamic series int ranks are supported; `na` elements are filtered while
  duplicates retain independent ranks, and empty/all-`na` arrays or `na`,
  negative, and out-of-range ranks return `na`. Non-int ranks are rejected
  during semantic analysis.
- Hardened built-in argument binding so required, duplicate, and positional-
  after-named arguments are validated against signature parameter slots, and
  indexed return types remain correct for reordered named calls. Aligned
  `strategy.exit` metadata with the supported optional `from_entry` form while
  preserving diagnostics for calls that omit both fixed and trailing triggers.
- Fixed host-parity discovery for rustfmt-expanded runtime snapshot tuples and
  made the representative public-host contract explicit: the current gate
  discovers 695 registered CLI snapshots and verifies the manifest-selected 418
  snapshots against both Python and WASM golden assertions. The 48 previously
  single-host snapshots are now paired, map/matrix coverage adds 12
  representatives, and any future silent single-host assertion fails the gate;
  the current reasoned-exception set is empty.
- Replaced the wasm compile-only release check with a real Node.js execution
  gate. It builds the wasm32 module, generates matching JavaScript bindings, and
  exercises analysis, direct and compiled execution, library/request/input host
  combinations, and JavaScript exception propagation.
- Added one shared scalar constant-call evaluator for the exact `int`, `float`,
  `math.min`, `math.max`, `math.abs`, `math.floor`, `math.ceil`, and
  `math.trunc` whitelist. Nested supported calls now drive static branch
  selection, declaration range checks, constant/negative history-offset
  analysis, and declaration/per-series `max_bars_back` inference. Finite
  `int(float)` calls match runtime truncation/saturation before downstream range
  checks, while out-of-`i64` rounding calls, unsupported calls, `na`, and
  non-finite results remain unknown.
- Kept these static values aligned with execution at integer boundaries:
  all-integer `math.min`/`math.max` preserve exact `i64` values at runtime,
  `math.abs(i64::MIN)` is rejected by bounded integer consumers instead of
  becoming an unchecked unknown, and HIR constant aliases retain the value
  visible when assigned rather than following later source-symbol
  reassignments during history-bound inference.
- Prevented history-offset evaluation and lowering from capturing a same-named
  global in place of a UDF or user-method parameter; dynamic callable
  arguments now retain dynamic history behavior through lowering.
- Fixed UDF and user-method const-argument propagation for numeric, string, and
  color comparisons, including tuple returns, while preventing tuple type
  queries from capturing unrelated same-named globals.
- Fixed condition-form switch qualifier propagation so fallback assignments
  include reachable preceding conditions and statically selected results ignore
  unreachable tail-condition qualifiers.
- Unified scalar `Simple*`, `Const*`, and `AtMostInput*` acceptors behind one
  exact/at-most qualifier-bound model while preserving existing signature names,
  `na` compatibility, and diagnostic labels.
- Extended stable pure-series identity to nested history expressions,
  `str.pos`, and `color.r`/`color.g`/`color.b`/`color.t`, with matching
  historical, incremental, and realtime rollback coverage.
- Prevented pure-series identity reuse across reassigned scalar dependencies so
  a later expression cannot inherit an earlier value's per-series
  `max_bars_back` retention bound, and inlined UDF/method locals keep distinct
  pre-/post-reassignment history sources.
- Split module validation, analyzer constant evaluation, lowering reassignment
  collection, lowering UDT resolution, and pure-series UDT traversal into
  focused modules, with tighter structural line-budget guards for the former
  hotspots.
- Fixed UDT array chained field mutation index validation so `series int`
  indexes are rejected with the same simple-int diagnostic as `array.get`.
- Added a fixture-backed diagnostic for imported UDT array chained field
  mutation, keeping that writeback path explicitly unsupported instead of
  reporting an unknown UDT element.
- Added fixture-backed local UDT constructor and method-result call-result
  method receivers, including `Point.new(...).method(...)` scalar returns,
  chained UDT returns, named arguments, and caller-side history reads from
  scalar and UDT method-returned values.
- Added fixture-backed imported UDT method-result receiver history identity, so
  chains such as `lib.Point.new(...).make(...).shift(...)[n]` can reuse the
  same pure series identity as their `max_bars_back` source.
- Extended local and imported method-result receiver history identity through
  block-bodied pure methods that return a local UDT constructor alias.
- Added fixture-backed local UDF-returned UDT argument history identity, so
  repeated pure UDF calls such as `read(make(...))[n]` can reuse the
  `max_bars_back` source series.
- Added imported exported-UDF-returned UDT argument history coverage, so
  `read(lib.typedPoint(...))[n]` style pure calls retain the same series
  identity as their bounded source.
- Added CLI profile gates for UDT/UDF/method `max_bars_back(source, N)` identity
  paths, covering local nested UDT aliases and imported alias-qualified method
  calls.
- Added fixture-backed pure `if`/`switch`/`for`/`while` expression identity
  reuse plus pure `for...in` over inline `array.from(...)` identity reuse for
  per-series `max_bars_back(source, N)` bounds and matching dynamic history reads.
- Added fixture-backed pure `fixnan(...)` expression identity reuse for
  per-series `max_bars_back(source, N)` bounds and matching dynamic history
  reads.
- Added fixture-backed pure `str.tonumber(...)` and `str.length(...)`
  expression identity reuse for per-series `max_bars_back(source, N)` bounds and
  matching dynamic history reads.
- Added fixture-backed bare scalar map declaration inference for
  `map name = map.new<K, V>()`, preserving the inferred template through
  method-style map reads while keeping template-less `map name = na` rejected.
- Added fixture-backed alias-qualified imported UDT method coverage for
  same-imported scalar-tree UDT values read directly from arrays, with mismatched
  local/imported element receiver identities still rejected.
- Restricted `bgcolor.show_last` and `barcolor.show_last` to const/input int
  values, with fixture coverage for accepted `input.int` counts and rejected
  simple integer counts.
- Restricted `fill.show_last` to const/input int values, with fixture coverage
  for accepted `input.int` counts and rejected simple integer counts.
- Restricted `plotcandle.show_last` to const/input int values, with fixture
  coverage for accepted `input.int` counts and rejected simple integer counts.
- Restricted `plotbar.show_last` to const/input int values, with fixture
  coverage for accepted `input.int` counts and rejected simple integer counts.
- Restricted `plotarrow.show_last` to const/input int values, with fixture
  coverage for accepted `input.int` counts and rejected simple integer counts.
- Restricted `plotshape.show_last` to const/input int values, with fixture
  coverage for accepted `input.int` counts and rejected simple integer counts.
- Restricted `plotchar.show_last` to const/input int values, with fixture
  coverage for accepted `input.int` counts and rejected simple integer counts.
- Restricted `plot.show_last` to const/input int values, with fixture coverage
  for accepted `input.int` counts and rejected simple integer counts.
- Restricted `plot.histbase` to const/input numeric values, with fixture
  coverage for accepted `input.float` bases and rejected simple/series numeric
  bases.
- Restricted `plot.linewidth` to const/input int values, with fixture coverage
  for accepted `input.int` widths and rejected simple integer widths.
- Restricted `hline.linewidth` to const/input int values, with fixture coverage
  for accepted `input.int` widths and rejected simple integer widths.
- Restricted `hline.color` to const/input color values, with fixture coverage
  for accepted `input.color` levels and rejected dynamic series colors.
- Added internal `AtMostInput*` scalar acceptors and shared expected/got
  diagnostics for future const/input string, bool, and color parameter
  signature work.
- Added HIR and runtime/profile coverage for `max_bars_back` when `N` is
  returned by an imported exported pure UDF, including declaration-level
  `indicator`/`strategy` bounds and per-series helper calls.
- Added semantic coverage for imported exported-UDF final `for`/`for...in`/`while`
  qualifier propagation, including `switch` block-arm final loop returns, through
  simple-compatible `ta.sma` length callsites.
- Improved same-local UDT `array.push` value-kind diagnostics so non-UDT values
  report the expected UDT value family with the actual Pine type.
- Avoid false positive negative-history diagnostics for `for...in` expression
  bodies when the iterable is statically empty, including empty copied arrays,
  empty concatenated arrays, empty sliced arrays, empty `array.abs`,
  `array.standardize`, and `array.sort_indices` results, empty matrices, and
  empty transposed/sliced matrices plus empty matrix row/column and
  eigenvalue arrays, eigenvector matrices, inverse matrices, and
  pseudo-inverse, Kronecker-product, matrix-multiplication matrix, array, and
  scalar results, matrix-power, and matrix-difference matrix and scalar
  results.
- Detect negative history offsets returned from statically non-empty `for...in`
  expression results, including array/matrix constructor sizes, copied
  array/matrix iterables, concatenated array iterables, statically non-empty
  sliced array windows, `array.abs`, `array.standardize`, and
  `array.sort_indices` result arrays, transposed matrix iterables, statically
  non-empty matrix submatrix windows, matrix row/column and eigenvalue arrays,
  matrix eigenvector matrices, inverse matrices, pseudo-inverse matrices, and
  Kronecker-product, matrix-multiplication matrix, array, and scalar results,
  matrix-power, and matrix-difference matrix and scalar results, and loop-body
  local aliases.
- Detect negative history offsets through `matrix.mult` and `matrix.diff`
  `for...in` iterable results when a scalar operand is a loop-body local alias.
- Detect negative history offsets returned from statically non-empty
  `str.split` `for...in` expression results, while avoiding false positives for
  statically empty empty-separator splits.
- Detect negative history offsets returned from the fixed-slot
  `ta.pivot_point_levels` `for...in` expression result array.
- Detect negative history offsets returned through loop-body tuple aliases in
  statically bounded for expressions.
- Detect negative history offsets selected by logical condition-switch arms
  involving values returned from statically bounded for expressions.
- Cover const float selector-form switch qualifier narrowing, including UDF
  parameter const-key propagation and tuple destructuring.
- Detect negative history offsets selected by int/float/bool/string/color comparisons
  involving values returned from statically bounded for expressions.
- Detect negative history offsets selected by int/float/bool/string/color
  selector-switch keys returned from statically bounded for expressions.
- Detect negative history offsets selected by bool conditions returned from
  statically bounded for expressions, including loop-body local aliases.
- Detect negative history offsets returned from statically bounded for
  expression results, including loop-body local aliases.
- Detect negative history offsets returned through branch-local tuple aliases in
  if and switch block results.
- Detect negative history offsets returned through branch-local aliases in if
  and switch block results.
- Detect negative history offsets produced by equal-valued ternary, if, and
  switch branches even when the controlling input condition is not constant.
- Added semantic guard coverage for direct `array.push` calls that try to append
  a local UDT value into a same-named imported scalar-tree UDT array.
- Added semantic guard coverage for method-style `array.push` calls that try to
  append a local UDT value into a same-named imported scalar-tree UDT array.
- Added semantic guard coverage for direct `array.push` calls that try to append
  an imported UDT value into a same-named local scalar-tree UDT array.
- Added semantic guard coverage for method-style `array.push` calls that try to
  append an imported UDT value into a same-named local scalar-tree UDT array.
- Added semantic guard coverage for direct `array.set` calls that try to
  replace a same-named imported scalar-tree UDT array element with a local UDT
  value.
- Added semantic guard coverage for method-style `array.set` calls that try to
  replace a same-named imported scalar-tree UDT array element with a local UDT
  value.
- Added semantic guard coverage for direct `array.set` calls that try to replace
  a same-named local scalar-tree UDT array element with an imported UDT value.
- Added semantic guard coverage for method-style `array.set` calls that try to
  replace a same-named local scalar-tree UDT array element with an imported UDT
  value.
- Added semantic guard coverage for direct `array.insert` calls that try to
  insert a local UDT value into a same-named imported scalar-tree UDT array.
- Added semantic guard coverage for method-style `array.insert` calls that try
  to insert a local UDT value into a same-named imported scalar-tree UDT array.
- Added semantic guard coverage for direct `array.insert` calls that try to
  insert an imported UDT value into a same-named local scalar-tree UDT array.
- Added semantic guard coverage for method-style `array.insert` calls that try
  to insert an imported UDT value into a same-named local scalar-tree UDT array.
- Added semantic guard coverage for direct `array.unshift` calls that try to
  prepend a local UDT value into a same-named imported scalar-tree UDT array.
- Added semantic guard coverage for method-style `array.unshift` calls that try
  to prepend a local UDT value into a same-named imported scalar-tree UDT array.
- Added semantic guard coverage for direct `array.unshift` calls that try to
  prepend an imported UDT value into a same-named local scalar-tree UDT array.
- Added semantic guard coverage for method-style `array.unshift` calls that try
  to prepend an imported UDT value into a same-named local scalar-tree UDT array.
- Added semantic guard coverage for direct `array.fill` calls that try to
  replace same-named imported scalar-tree UDT array elements with a local UDT
  value.
- Added semantic guard coverage for method-style `array.fill` calls that try to
  replace same-named imported scalar-tree UDT array elements with a local UDT
  value.
- Added semantic guard coverage for direct `array.fill` calls that try to
  replace same-named local scalar-tree UDT array elements with an imported UDT
  value.
- Added semantic guard coverage for method-style `array.fill` calls that try to
  replace same-named local scalar-tree UDT array elements with an imported UDT
  value.
- Added semantic guard coverage for direct `array.includes` calls that try to
  search a same-named imported scalar-tree UDT array with a local UDT value.
- Added semantic guard coverage for method-style `array.includes` calls that
  try to search a same-named imported scalar-tree UDT array with a local UDT
  value.
- Added semantic guard coverage for direct `array.includes` calls that try to
  search a same-named local scalar-tree UDT array with an imported UDT value.
- Added semantic guard coverage for method-style `array.includes` calls that
  try to search a same-named local scalar-tree UDT array with an imported UDT
  value.
- Added semantic guard coverage for direct `array.indexof` calls that try to
  search a same-named imported scalar-tree UDT array with a local UDT value.
- Added semantic guard coverage for method-style `array.indexof` calls that try
  to search a same-named imported scalar-tree UDT array with a local UDT value.
- Added semantic guard coverage for direct `array.indexof` calls that try to
  search a same-named local scalar-tree UDT array with an imported UDT value.
- Added semantic guard coverage for method-style `array.indexof` calls that try
  to search a same-named local scalar-tree UDT array with an imported UDT value.
- Added semantic guard coverage for direct `array.lastindexof` calls that try
  to search a same-named imported scalar-tree UDT array with a local UDT value.
- Added semantic guard coverage for method-style `array.lastindexof` calls that
  try to search a same-named imported scalar-tree UDT array with a local UDT
  value.
- Added semantic guard coverage for direct `array.lastindexof` calls that try
  to search a same-named local scalar-tree UDT array with an imported UDT value.
- Added semantic guard coverage for method-style `array.lastindexof` calls that
  try to search a same-named local scalar-tree UDT array with an imported UDT
  value.
- Added semantic guard coverage for direct `array.concat` calls that try to
  concatenate same-named imported and local scalar-tree UDT arrays.
- Added semantic guard coverage for method-style `array.concat` calls that try
  to concatenate same-named imported and local scalar-tree UDT arrays.
- Added semantic guard coverage for direct `array.concat` calls that try to
  concatenate same-named local and imported scalar-tree UDT arrays.
- Added semantic guard coverage for method-style `array.concat` calls that try
  to concatenate same-named local and imported scalar-tree UDT arrays.
- Added semantic guard coverage for imported scalar-tree UDT bool fields used
  as dynamic history offsets, including receiver-style and alias-qualified
  method passthrough values.
- Added semantic guard coverage for imported nested scalar-tree UDT bool fields
  used as dynamic history offsets, including receiver-style and alias-qualified
  method passthrough values.
- Added semantic guard coverage for constant-expression negative history
  offsets.
- Added semantic guard coverage for prior named const alias-chain negative
  history offsets.
- Added semantic guard coverage for prior named const expression negative
  history offsets.
- Added semantic guard coverage for prior named const ternary negative history
  offsets.
- Added syntax-level folding and semantic guard coverage for prior named const
  if-expression negative history offsets.
- Added semantic guard coverage for prior named const comparison-driven ternary
  negative history offsets.
- Added syntax-level folding and semantic guard coverage for prior named const
  numeric if- and switch-result comparison-driven ternary negative history
  offsets.
- Added semantic guard coverage for prior named const string-comparison-driven
  ternary negative history offsets.
- Added syntax-level folding and semantic guard coverage for prior named const
  string if- and switch-result comparison-driven ternary negative history
  offsets.
- Added semantic guard coverage for prior named const color-comparison-driven
  ternary negative history offsets.
- Added syntax-level folding and semantic guard coverage for prior named const
  color if- and switch-result comparison-driven ternary negative history
  offsets.
- Added semantic guard coverage for prior named const bool-comparison-driven
  ternary negative history offsets.
- Added syntax-level folding and semantic guard coverage for prior named const
  bool if- and switch-result-driven ternary negative history offsets.
- Added semantic guard coverage for prior named const logical-expression-driven
  ternary negative history offsets.
- Added semantic guard coverage for prior named const selector-switch negative
  history offsets.
- Added syntax-level folding and semantic guard coverage for prior named const
  selector-switch block-arm negative history offsets.
- Added semantic guard coverage for prior named const condition-switch negative
  history offsets.
- Added semantic guard coverage for imported scalar-tree UDT string fields used
  as dynamic history offsets, including receiver-style and alias-qualified
  method passthrough values.
- Added semantic guard coverage for imported nested scalar-tree UDT string
  fields used as dynamic history offsets, including receiver-style and
  alias-qualified method passthrough values.
- Added semantic guard coverage for imported UDT array declarations, `[]`
  aliases, `varip` declarations, and `varip` `[]` aliases whose imported UDT
  metadata contains non-scalar fields.
- Added semantic guard coverage for `array.new<lib.Type>()` when imported UDT
  metadata contains non-scalar fields.
- Added semantic guard coverage for `array.from(lib.Type.new(...))` when
  imported UDT metadata contains non-scalar fields.
- Added semantic guard coverage for imported UDT value history and `varip`
  declarations on non-scalar UDT metadata, and aligned imported scalar-tree
  checks so drawing-object fields are not treated as scalar-tree UDT fields.
- Added fixture-backed dynamic history offsets produced by integer-valued
  ternary, if, switch, for, for-in, while, and built-in call results.
- Fixed `for` loop counter qualifier propagation so a series-qualified `by`
  step promotes the counter seen inside statement and expression loop bodies.
- Improved expression-context `if`, `switch`, `for`, and `while` return
  diagnostics so side-effect-only or loop-control endings consistently require
  a value-producing expression.
- Improved `map.put_all` template mismatch diagnostics so source and target
  key/value kinds use canonical Pine type names.
- Improved ternary and switch branch type mismatch diagnostics so branch kinds
  use canonical Pine type names.
- Improved user-method parameter mismatch diagnostics so expected parameter
  types use canonical Pine type names.
- Improved local and imported UDT constructor field type diagnostics so they use
  canonical Pine type names instead of Rust enum names.
- Improved same-local UDT `array.new<T>` initial value diagnostics so non-UDT
  values now report the expected UDT identity alongside the actual type.
- Added runtime-backed UDF and user-method qualifier propagation coverage for
  scalar and simple-string values returned through expression, block-local,
  final loop, branch-loop, switch-block, nested-loop, and while-result forms,
  plus imported exported-UDF passthrough/block-local returns and imported method
  receiver-style and alias-qualified passthrough/block-local/final-loop returns.
- Added runtime-backed scalar typed declaration qualifier coverage for non-`na`
  initializer preservation, typed-`na` reassignment inheritance, UDF-local typed
  `na` reassignment, and later series promotion.
- Added runtime-backed const-condition qualifier narrowing coverage for
  literal/named/equality-derived `if`, ternary, switch, tuple, UDF, nested UDF,
  and user-method length flows into simple-only TA consumers.
- Added runtime-backed imported UDT typed-`na` value history coverage for
  exported UDTs whose scalar-tree metadata depends on private library UDTs.
- Added fixture-backed named same-imported scalar-tree UDT array typed UDF and
  method arguments, plus caller-side history reads from returned imported UDT
  array elements.
- Added fixture-backed receiver-style and alias-qualified imported UDT method
  calls with named/reordered non-receiver arguments and caller-side history
  reads from named-argument UDT returns.
- Added fixture-backed rejection for alias-qualified imported UDT method calls
  whose receiver is not the first argument.
- Added fixture-backed diagnostics for imported UDT method receiver and
  parameter field mutation side-effect boundaries.
- Fixed imported UDT method metadata so the same method name can be exported
  for different scalar-tree UDT receiver types.
- Added fixture-backed `chart.point` typed-flow declaration and value history
  coverage for values returned from `for...in` expressions.
- Added negative coverage for non-integer and negative dynamic history offsets
  produced by `for...in` expression results.
- Added fixture-backed runtime and realtime typed same-local UDT `varip`
  initialization from `for...in` and `while` expression results.
- Extended typed same-local UDT `varip` coverage to nested scalar-tree Wrapper
  values initialized from ternary, switch, if, for, for-in, and while expression
  results, with historical and realtime intrabar handoff.
- Added committed and realtime confirmed-bar history coverage for representative
  nested scalar-tree Wrapper `varip` values initialized from same-local ternary
  expression results.
- Extended same-local scalar-tree UDT array `varip` coverage to nested
  scalar-tree elements initialized through `array.from(...)` and
  `array.new<T>()`, with historical and realtime backing-store handoff.
- Added fixture-backed runtime coverage for `for...in`-produced dynamic series
  history offsets, including first-bar predicates and `na` dynamic offsets.
- Added fixture-backed user-defined method qualifier rejection for final-if
  branches or switch block arms that return series-controlled final loops when
  consumed by simple-only arguments.
- Added fixture-backed user-defined method qualifier rejection for final
  `for`, `for...in`, and `while` returns promoted by series loop controls when
  consumed by simple-only arguments.
- Added fixture-backed user-defined method qualifier propagation for scalar and
  simple-string returns through expression, block-local, final-if, loop, and
  switch return shapes, including `ta.sma` length and `timeframe.in_seconds`
  callsites.
- Added fixture-backed user-defined method returned history offsets and
  method-returned scalar series values, including returned `na` offsets and
  constant/dynamic/`na` history reads from method call results.
- Added fixture-backed caller-side history reads from local UDT UDF and method
  returned values, including passthrough, constructor, and control-flow returns.
- Added fixture-backed caller-side history reads from local nested scalar-tree
  UDT UDF and method returned values.
- Added fixture-backed history offsets produced by local and imported
  scalar-tree UDT integer fields, including nested local/imported fields,
  local UDF/method-returned values, and imported UDF/method-returned values.
- Added fixture-backed rejection for non-integer and negative history offsets
  produced by local/imported UDT fields, including imported direct/nested fields
  and imported UDF passthrough/constructor-returned plus receiver-style or
  alias-qualified method-returned direct/nested fields.
- Added fixture-backed scalar, object-id, `chart.point`, same-local
  scalar-tree UDT array, and same-imported scalar-tree UDT array typed
  user-defined function parameters for `array<T>` and `T[]`, including
  `array<int>`, `float[]`, `array<chart.point>`, and `line[]` parameter syntax,
  typed argument rejection, and history reads from UDF results.
- Added fixture-backed scalar, `chart.point`, scalar-array, object-id-array,
  chart.point-array, same-local scalar-tree UDT array, and same-imported
  scalar-tree UDT array typed user-defined method parameters, including
  receiver-style and alias-qualified imported method calls plus typed argument
  rejection.
- Added fixture-backed scalar and `chart.point` typed user-defined function
  parameters, including `chart.point` constructor returns, read-only
  passthrough, and history reads from the typed returned point value.
- Added fixture-backed same-local UDT typed user-defined function parameters,
  including constructor returns, read-only passthrough, caller-side field reads,
  and history reads from the typed returned UDT value.
- Added fixture-backed imported exported functions with same-imported UDT typed
  parameters, preserving imported UDT identity through passthrough,
  constructor-return, caller-side field reads, and history reads.
- Added fixture-backed `chart.point` UDF and user-defined method value flow for
  constructor returns and read-only passthrough, including history reads from
  the returned point value.
- Added fixture-backed explicit `chart.point` typed declarations initialized
  from `if`, `switch`, `for`, and `while` expression results, plus typed `na`
  reassignment.
- Added fixture-backed ordinary `var chart.point` realtime rollback, covering
  field-mutation rollback between repeated forming updates.
- Added fixture-backed single `chart.point` value history for `if`, `switch`,
  `for`, and `while` expression results, including dynamic `na` offsets and
  retained previous point values after current-point mutation.
- Added fixture-backed repeated dynamic same-bar single `chart.point` value
  history reads for direct point values,
  `if`/`switch`/`for`/`for...in`/`while` expression point results, and UDF- or
  method-returned point values, proving sibling historical point copies remain
  independent after field mutation.
- Added fixture-backed single `chart.point` value `varip` declarations, including
  historical var-like execution and realtime intrabar field-mutation persistence.
- Added fixture-backed committed and realtime confirmed-bar history reads for
  single `chart.point` value `varip` declarations with constant and dynamic
  offsets.
- Added fixture-backed dynamic `na` offset history reads for UDF-returned and
  method-returned single `chart.point` values.
- Added fixture-backed dynamic `na` offset history reads for single
  `chart.point` values produced by `if`, `for`, `for...in`, and `while`
  expression results, matching the existing switch-expression coverage.
- Added fixture-backed field reads from dynamically selected historical
  `array<chart.point>` and chart.point slice snapshots.
- Added fixture-backed repeated dynamic same-bar `array<chart.point>` and
  chart.point slice history reads to prove sibling historical copies remain
  independent after mutation.
- Added fixture-backed content reads from dynamically selected historical
  drawing-id array and slice snapshots for label, line, box, linefill, polyline,
  and table ids.
- Added fixture-backed repeated dynamic same-bar label, line, box, linefill,
  polyline, and table array/slice history reads to prove sibling historical copies remain
  independent after slot replacement.
- Added fixture-backed field reads from dynamically selected historical
  same-local and same-imported scalar-tree UDT array and slice snapshots.
- Added fixture-backed repeated dynamic same-bar same-imported scalar-tree UDT
  array and slice history reads to prove sibling historical copies remain
  independent after UDT slot replacement.
- Added fixture-backed content and shape reads from dynamically selected
  scalar array/slice, while-expression array, matrix-shape, and
  while-expression matrix history snapshots.
- Added fixture-backed repeated dynamic same-bar scalar array and slice history
  reads to prove sibling historical copies remain independent after mutation.
- Added fixture-backed repeated dynamic same-bar matrix history reads to prove
  sibling historical matrix copies remain independent after mutation and
  reshape.
- Added fixture-backed single `chart.point` value history, covering constant
  offsets, dynamic `na` offsets, and retained previous point values after
  mutating the current point.
- Added fixture-backed scalar map key-only direct `for...in` iteration, where
  statement and expression forms bind the single loop variable to the map key
  while preserving existing `[key, value]` iteration and size-change runtime
  rejection.
- Allowed `ta.sma` to accept integer-compatible dynamic `length` arguments
  while preserving non-integer length and non-series source rejection.
- Allowed `ta.bb` and `ta.bbw` to accept integer-compatible dynamic `length`
  arguments while preserving non-integer length and non-numeric multiplier
  rejection.
- Allowed `ta.kc` and `ta.kcw` to accept integer-compatible dynamic `length`
  arguments while preserving non-integer length, non-simple multiplier, and
  non-bool `useTrueRange` rejection.
- Allowed `math.sum` to accept integer-compatible dynamic `length` arguments
  while preserving non-integer length rejection.
- Allowed `ta.cmo`, `ta.cci`, `ta.cog`, and `ta.mfi` to accept
  integer-compatible dynamic `length` arguments while preserving non-integer
  length rejection.
- Allowed `ta.alma` and `ta.linreg` to accept integer-compatible dynamic
  `length` arguments while preserving non-integer length and simple-only
  secondary parameter rejection.
- Allowed `ta.vwma`, `ta.wma`, and `ta.hma` to accept integer-compatible
  dynamic `length` arguments while preserving non-integer length rejection.
- Allowed `ta.stoch` and `ta.wpr` to accept integer-compatible dynamic `length`
  arguments while preserving non-integer length rejection.
- Allowed `ta.percentile_nearest_rank` and
  `ta.percentile_linear_interpolation` to accept integer-compatible dynamic
  `length` arguments while preserving non-integer length and series-percentage
  rejection.
- Allowed `ta.correlation` and `ta.covariance` to accept integer-compatible
  dynamic `length` arguments while preserving non-integer length rejection.
- Allowed `ta.median`, `ta.mode`, and `ta.percentrank` to accept
  integer-compatible dynamic `length` arguments while preserving non-integer
  length rejection.
- Allowed `ta.stdev` and `ta.variance` to accept integer-compatible dynamic
  `length` arguments while preserving non-integer length rejection.
- Allowed `ta.range` and `ta.dev` to accept integer-compatible dynamic
  `length` arguments while preserving non-integer length rejection.
- Allowed `ta.percentile_nearest_rank` and
  `ta.percentile_linear_interpolation` to accept simple numeric `percentage`
  arguments while preserving series-percentage semantic rejection.
- Added fixture-backed `max_bars_back(source, N)` per-series retention for
  matching `nz(source)` and named/reordered `nz(x=source, replacement=value)`
  dynamic history reads, including profile miss diagnostics when source-level
  bounds are exceeded.
- Added fixture-backed `max_bars_back(source, N)` per-series retention when the
  helper is declared inside `array.set`/`matrix.set` method argument blocks
  before a dynamic history read.
- Added fixture-backed same-imported scalar-tree UDT `array.from` construction
  with `array.size`, namespace/method `array.get`, namespace/method
  `array.first`/`array.last` field reads, namespace/method
  `array.set`/`set()` replacement field reads, namespace/method
  `array.push`/`push()` append field reads, namespace/method
  `array.unshift`/`unshift()` prepend field reads, namespace/method
  `array.insert`/`insert()` insertion field reads, namespace/method
  `array.fill`/`fill()` replacement field reads, namespace/method
  `array.join`/`join()` positional stringification, namespace/method
  `array.includes`/`array.indexof`/`array.lastindexof` structural equality
  search, namespace/method `array.sort`/`array.sort_indices` by scalar
  `sort_field`, namespace/method
  `array.pop`/`array.remove`/`array.shift` return field reads, and
  `array.clear`/`clear()` size reset plus `array.copy`/`copy()` independent
  field reads, `array.reverse`/`reverse()` reordered field reads,
  `array.slice`/`slice()` window field reads, and
  `array.concat`/`concat()` appended field reads, plus
  statement/expression/index-value `for...in` value-copy field reads.
- Added fixture-backed same-imported scalar-tree UDT `array.new<lib.Type>`
  construction, including empty arrays, seeded initial values, typed
  declarations, nested scalar-tree imported UDT elements, post-construction
  mutation helpers, returned-element helpers, copy/window helpers, structural
  search, join, sort/sort_indices, and clear.
- Extended imported scalar-tree UDT array history coverage so arrays constructed
  via `array.new<lib.Type>()` participate in committed snapshots, first-bar
  `na` predicates, dynamic `na` offsets, mutation isolation, and `var` array
  history reads.
- Added fixture-backed same-imported scalar-tree UDT typed array declarations
  for `array<lib.Type>` and `lib.Type[]`, with `na` initialization, later
  same-identity `array.from` assignment, copy/get/push reads, and statement
  `for...in` value-copy field reads. Non-scalar imported UDT array declarations
  remain rejected.
- Added fixture-backed same-imported scalar-tree UDT array `varip`
  declarations initialized through `array.from(...)` or
  `array.new<lib.Type>(...)`, with historical and realtime intrabar
  backing-store handoff.
  Non-scalar imported UDT array `varip` declarations remain rejected.
- Extended scalar-tree imported UDT value `varip` coverage to same-imported
  ternary, switch, if, for, for-in, and while expression initializers with
  historical and realtime intrabar handoff.
- Extended scalar-tree imported UDT value `varip` coverage to nested Wrapper
  values initialized from same-imported ternary, switch, if, for, for-in, and
  while expression results, with historical and realtime intrabar handoff.
- Added committed and realtime confirmed-bar history coverage for representative
  nested scalar-tree imported Wrapper `varip` values initialized from
  same-imported ternary expression results.
- Added fixture-backed imported scalar-field UDT typed-array `slice()` and
  `concat()` coverage, keeping the array helper matrix aligned with the
  imported UDT array subset.
- Added fixture-backed scalar-tree imported UDT value history with caller-side
  field reads, while direct private imported UDT access and imported UDT value history outside the scalar-tree metadata subset
  remains rejected.
- Added fixture-backed repeated dynamic same-bar scalar-tree local and imported
  UDT value history reads, proving sibling historical UDT copies remain
  independent after root-field replacement.
- Extended local and imported scalar-tree UDT flow-result history fixtures to
  prove repeated dynamic same-bar sibling copies stay independent after
  mutating direct Point if/switch/for/for-in/while results and nested Wrapper
  if/switch/for/for-in/while result history values.
- Extended local and imported typed-UDF UDT history fixtures to prove repeated
  dynamic same-bar sibling copies stay independent for returned Point and
  Wrapper values.
- Extended local and imported direct/nested UDF passthrough UDT history fixtures
  to prove repeated dynamic same-bar sibling copies stay independent for
  returned Point and Wrapper values.
- Extended local and imported direct/nested UDF constructor-returned UDT history
  fixtures to prove repeated dynamic same-bar sibling copies stay independent
  for returned Point and Wrapper values.
- Completed local and imported method direct/nested passthrough and
  direct/nested constructor-returned UDT history fixtures to prove repeated
  dynamic same-bar sibling copies stay independent for returned Point and
  Wrapper values.
- Extended scalar-tree UDT field-produced dynamic history offset fixtures to
  cover local/imported UDF passthrough/constructor-returned direct/nested
  Settings values and local/imported method passthrough/constructor-returned
  direct/nested Settings values, including imported receiver-style and
  alias-qualified method calls.
- Extended non-integer UDT field-produced history offset diagnostics to cover
  local and imported UDF- and method-returned direct/nested values with
  representative float, bool, and string offset fields, including local/imported
  UDF direct/nested passthrough/constructor-returned fields, local method
  direct/nested passthrough/constructor-returned fields plus method-returned
  bool/string fields, and imported receiver-style or alias-qualified method
  direct/nested passthrough/constructor-returned fields.
- Extended negative UDT field-produced dynamic history offset regressions to
  cover local and imported UDF- and method-returned direct/nested values,
  including local/imported UDF direct/nested passthrough and
  constructor-returned fields plus local/imported method direct/nested
  passthrough and constructor-returned fields, with imported method coverage
  including receiver-style and alias-qualified calls.
- Added fixture-backed committed history reads for scalar-tree local and
  imported UDT `varip` values, including constant offsets, dynamic `na` offsets,
  scalar Point ternary-/switch-/if-/for-/for...in-/while-initialized and
  direct-constructor- and direct-alias-inferred values, and nested scalar-tree field reads, with
  nested Wrapper coverage for ternary-, switch-, if-, for-, for...in-,
  while-initialized, direct-constructor-inferred, and direct-alias-inferred values.
- Added semantic-analysis fixtures for same-local and same-imported scalar-tree
  UDT value history over direct values, aliases, and nested Wrapper values with
  constant and dynamic offsets.
- Extended realtime UDT `varip` fixtures so current values persist intrabar
  while UDT history reads still come from confirmed bars during repeated forming
  updates, including scalar Point ternary-/switch-/if-/for-/for...in-/while-
  initialized plus direct-constructor- and direct-alias-inferred values, switch-, if-, for-,
  for...in-, and while-initialized nested Wrapper values plus
  direct-constructor-inferred and direct-alias-inferred nested Wrapper values.
- Added semantic-analysis fixtures for same-local and same-imported scalar-tree
  UDT `varip` declarations initialized through explicit types, direct
  constructor inference, and direct alias inference.
- Added fixture-backed method-local scalar-field UDT mutation for local and
  imported pure methods, while keeping receiver/parameter/global method field
  side effects rejected.
- Added fixture-backed receiver-style and alias-qualified scalar imported UDT
  method calls, including direct receiver, same-identity parameter, block-local
  alias, final-if alias, final-for alias, and nested-method passthrough returns
  plus same-imported-identity constructor returns, using imported method receiver
  identity while keeping wrong receiver types rejected.
- Extended alias-qualified imported UDT method fixtures to cover direct
  constructor receiver expressions with named/reordered non-receiver arguments
  and direct constructor nested UDT arguments.
- Added fixture-backed local and imported UDT method final-`for...in` alias
  passthrough returns, covering both receiver and same-identity parameter
  aliases.
- Added fixture-backed imported UDT UDF final-if and final-for alias
  passthrough returns, including nested passthrough chains.
- Added fixture-backed imported UDT UDF block-local alias passthrough returns,
  including nested passthrough chains.
- Added fixture-backed imported UDT UDF constructor returns through ternary,
  `if`, `for`, `for...in`, `while`, and `switch` result shapes, including
  nested constructor-helper calls.
- Added fixture-backed imported UDT method constructor returns through `if`,
  `for`, `for...in`, `while`, and `switch` result shapes, including typed
  imported return locals and nested scalar-tree Wrapper returns.
- Added fixture-backed caller-side history reads from imported UDT method
  passthrough and constructor-return values.
- Added fixture-backed caller-side history reads from imported UDT UDF
  passthrough and constructor-return values, including nested constructor-helper
  calls.
- Added fixture-backed dynamic and `na` offset history reads for local and
  imported scalar-tree UDT values.
- Added fixture-backed caller-side history reads from same-imported-identity
  UDT `if`, `switch`, `for`, `for...in`, and `while` expression results.
- Added fixture-backed caller-side history reads from same-local UDT `if`,
  `switch`, `for`, `for...in`, and `while` expression results.
- Added fixture-backed same-local scalar-tree UDT array chained field mutation
  for `array.get(points, index).field := value` and
  `points.get(index).field := value`, including slice-window parent writeback.
  UDF-local chained UDT array mutation remains rejected as a function side
  effect.
- Added fixture-backed same-local scalar-tree UDT array `varip` support for
  `array<T>` and `T[]` declarations. Realtime forming updates now carry the
  retained array id together with its backing store and UDT element metadata,
  while non-scalar UDT array `varip` declarations remain rejected.
- Added fixture-backed repeated dynamic same-bar same-local scalar-tree UDT
  array and slice history reads, proving sibling historical copies remain
  independent after UDT slot replacement.
- Added fixture-backed matrix `varip` support for runtime-owned
  `matrix<float>`, `matrix<int>`, `matrix<bool>`, `matrix<string>`, and
  `matrix<color>` ids. Realtime forming updates now carry matrix `varip` slots
  together with their backing stores and advance retained matrix ids.
- Added fixture-backed `map.new<K, V>()` support for runtime-owned map ids over
  scalar `int`, `float`, `bool`, `string`, and `color` key/value templates,
  plus `map.size(id)`, `map.put(id, key, value)`, `map.get(id, key)`, and
  `map.contains(id, key)` namespace calls, plus `map.clear(id)` full-map
  clearing, `map.remove(id, key)` single-key deletion, and `map.copy(id)`
  independent backing-store cloning, plus `map.keys(id)` and `map.values(id)`
  insertion-order array snapshots, and `map.put_all(target, source)`
  same-template merge semantics. Equivalent `id.size()`, `id.put(...)`,
  `id.get(...)`, `id.contains(...)`, `id.clear()`, `id.remove(...)`,
  `id.copy()`, `id.keys()`, `id.values()`, and `id.put_all(source)` method
  aliases lower to the same runtime calls. Ordinary realtime rollback of
  map-store mutations is fixture-backed. Scalar `map<K,V>` typed declarations
  accept compatible or `na` initialization and same-template reassignment.
  Scalar map history snapshots now return independent historical copies, including
  dynamic `na` offset predicates plus key and size reads from dynamically selected
  historical maps, and repeated same-bar history reads remain independent when a
  sibling historical map copy is mutated.
  Scalar map `varip` now retains map ids and backing stores across realtime
  forming updates. Read-only map helpers now work through user-defined function
  parameters when the caller supplies a known scalar map template. Bare map
  declarations and non-scalar templates remain unsupported.
- Added fixture-backed `while` expression coverage for `matrix<int>`,
  `matrix<bool>`, `matrix<string>`, and `matrix<color>` results with
  caller-side reads and mutation.
- Added fixture-backed expression-form `for value in values` support for
  `array<int>`, `array<float>`, `array<bool>`, `array<string>`,
  `array<color>`, `array<label>`, `array<line>`, `array<linefill>`,
  `array<polyline>`, `array<box>`, `array<table>`, `array<chart.point>`, and
  same-local scalar-tree UDT array iterables plus runtime-owned matrix row
  iterables, returning the loop body's last expression from the last completed
  iteration and `na` for zero-iteration or typed-`na` collections, with `break`
  returning the previous result and `continue` skipping the current result
  expression, including optional zero-based index locals. Broader collection
  families remain unsupported.
- Added fixture-backed statement-form `for...in` iteration over runtime-owned
  `matrix<float>`, `matrix<int>`, `matrix<bool>`, `matrix<string>`, and
  `matrix<color>` values. Matrix loops iterate row snapshots captured at loop
  entry, expose each row as an independent `array<T>`, and support the narrow
  `for row in values` and `for row_index, row in values` statement forms while
  keeping map iteration and `varip matrix<T>` semantics unsupported.
- Added fixture-backed `matrix.new<color>` support for runtime-owned color
  matrix ids with color/`na` cells through structural matrix operations:
  get/set/fill/copy/transpose/reverse/reshape/submatrix/row/col, row/column
  insertion, deletion, swaps, shape readers, `is_square`, and
  `matrix<color>` typed declarations, while numeric matrix readers and algebra
  remain limited to float/int matrices.
- Added fixture-backed `matrix.new<string>` support for runtime-owned string
  matrix ids with string/`na` cells through structural matrix operations:
  get/set/fill/copy/transpose/reverse/reshape/submatrix/row/col, row/column
  insertion, deletion, swaps, shape readers, `is_square`, and
  `matrix<string>` typed declarations, while numeric matrix readers and algebra
  remain limited to float/int matrices.
- Added fixture-backed `matrix.new<bool>` support for runtime-owned bool matrix
  ids with bool/`na` cells through structural matrix operations:
  get/set/fill/copy/transpose/reverse/reshape/submatrix/row/col, row/column
  insertion, deletion, swaps, shape readers, `is_square`, and `matrix<bool>`
  typed declarations, while numeric matrix readers and algebra remain limited
  to float/int matrices.
- Added fixture-backed `matrix.new<int>` support for runtime-owned int matrix
  ids with int/`na` cells through `matrix.get`, `matrix.set`, `matrix.fill`,
  `matrix.copy`, `matrix.transpose`, `matrix.reverse`, `matrix.reshape`,
  `matrix.submatrix`, `matrix.row`, `matrix.col`, `matrix.add_row`,
  `matrix.add_col`, `matrix.remove_row`, `matrix.remove_col`,
  `matrix.swap_rows`, `matrix.swap_columns`, `matrix.sort`, shape readers,
  value predicates, numeric readers, float-result matrix arithmetic including
  scalar namespace mult/diff and matrix-array multiplication, linear algebra
  readers, and matching supported method aliases, including
  `array<int>` row/column insertion data and `matrix<int>` typed declarations
  with compatible matrix or `na` initializers.
- Added fixture-backed numeric-array `matrix.mult(values, vector)`,
  `values.mult(vector)`, `matrix.mult(vector, values)`, and
  `matrix.mult(left_vector, right_vector)` support, treating arrays as column
  or row vectors and returning independent `array<float>` dot-product results
  with `na` propagation and semantic rejection for non-numeric arrays.
- Added fixture-backed left-scalar namespace `matrix.diff(scalar, values)`
  support for runtime-owned float or int matrices, returning independent
  same-shape `matrix<float>` results that preserve subtraction operand order
  with `na` propagation while keeping scalar-pair calls rejected at semantic
  analysis.
- Added fixture-backed left-scalar namespace `matrix.mult(scalar, values)`
  support for runtime-owned float or int matrices, returning independent
  same-shape `matrix<float>` results with `na` propagation while keeping
  scalar-pair calls rejected at semantic analysis.
- Added fixture-backed scalar-right `matrix.mult`/`values.mult(scalar)` and
  `matrix.diff`/`values.diff(scalar)` support for runtime-owned float or int
  matrices, returning independent same-shape `matrix<float>` results with `na`
  propagation.
- Added fixture-backed `matrix.submatrix` and
  `values.submatrix(from_row?, to_row?, from_column?, to_column?)` support for
  independent runtime-owned float matrix slice copies, including default full
  ranges, empty row/column slices, semantic index checks, runtime bounds, `na`
  index, and reversed-range errors.
- Added fixture-backed `matrix.sort` and `values.sort(column?, order?)`
  support for in-place row sorting on runtime-owned float matrices, including
  default column `0`, `order.ascending`/`order.descending`, `na` sort placement,
  column-index runtime errors, semantic column/order checks, and UDF
  side-effect rejection.
- Added fixture-backed `matrix.swap_columns` and
  `values.swap_columns(column1, column2)` support for in-place column swaps on
  runtime-owned float matrices, including same-column and zero-row no-op
  behavior, column-index runtime errors, semantic index checks, and UDF
  side-effect rejection.
- Added fixture-backed `matrix.swap_rows` and `values.swap_rows(row1, row2)`
  support for in-place row swaps on runtime-owned float matrices, including
  same-row and zero-column no-op behavior, row-index runtime errors, semantic
  index checks, and UDF side-effect rejection.
- Added fixture-backed `matrix.pow` and `values.pow(power)` support for
  read-only matrix powers on runtime-owned float square matrices, including
  independent identity/copy/power results, `na` propagation, zero-dimension
  results, non-square errors, and negative-power errors.
- Added fixture-backed matrix-by-matrix `matrix.diff` and
  `values.diff(other)` support for read-only element-wise subtraction on
  runtime-owned float matrices, including independent results, `na` cell
  propagation, zero-dimension results, and shape-mismatch errors.
- Added fixture-backed matrix-by-matrix `matrix.mult` and
  `values.mult(other)` support for read-only multiplication on runtime-owned
  float matrices, including independent results, `na` cell propagation,
  zero-dimension results, shape-mismatch errors, and cell-budget errors.
- Added fixture-backed `matrix.kron` and `values.kron(other)` support for
  read-only Kronecker-product matrices on runtime-owned float matrices,
  including independent results, `na` cell propagation, zero-dimension results,
  and cell-budget errors.
- Added fixture-backed `matrix.eigenvectors` and `values.eigenvectors()`
  support for read-only eigenvector matrices on runtime-owned float square
  matrices, including symmetric, 2x2 real non-symmetric, empty, `na`,
  non-square, and non-real eigenvector boundaries.
- Added fixture-backed `matrix.eigenvalues` and `values.eigenvalues()`
  support for read-only eigenvalue arrays on runtime-owned float square
  matrices, including symmetric, 2x2 real non-symmetric, empty, `na`,
  non-square, and non-real eigenvalue boundaries.
- Added fixture-backed `matrix.pinv` and `values.pinv()` support for read-only
  Moore-Penrose pseudo-inverse reads on runtime-owned float matrices, including
  invertible square, singular square, rectangular, zero-dimension, and `na`
  matrix coverage.
- Added fixture-backed `matrix.inv` and `values.inv()` support for read-only
  inverse-matrix reads on runtime-owned float square matrices, including
  independent result matrices, empty `0 x 0` matrices, singular/`na` results,
  and non-square runtime errors.
- Added fixture-backed `matrix.rank` and `values.rank()` support for read-only
  rank reads on runtime-owned float rectangular matrices, including dependent
  rows, zero-dimension matrices, and `na` cells.
- Added fixture-backed `matrix.det` and `values.det()` support for read-only
  determinant reads on runtime-owned float square matrices, including
  row-swap pivoting, empty `0 x 0` matrices, `na` cells, and non-square runtime
  errors.
- Added fixture-backed `matrix.trace` and `values.trace()` support for
  read-only main-diagonal sums on runtime-owned float matrices, ignoring `na`
  diagonal cells and returning `na` for empty or all-`na` diagonals.
- Added fixture-backed `matrix.is_stochastic` and `values.is_stochastic()`
  support for read-only stochastic-matrix checks on runtime-owned float
  matrices, including row-sum and column-sum forms, negative values, `na`
  cells, and zero-element matrices.
- Added fixture-backed `matrix.is_antisymmetric` and
  `values.is_antisymmetric()` support for read-only antisymmetric-matrix checks
  on runtime-owned float matrices, including non-square matrices, `na` cells,
  non-zero diagonal cells, and empty `0 x 0` matrices.
- Added fixture-backed `matrix.is_symmetric` and `values.is_symmetric()`
  support for read-only symmetric-matrix checks on runtime-owned float
  matrices, including non-square matrices, `na` cells, and empty `0 x 0`
  matrices.
- Added fixture-backed `matrix.is_identity` and `values.is_identity()` support
  for read-only identity-matrix checks on runtime-owned float matrices,
  including non-square matrices, `na` cells, and empty `0 x 0` matrices.
- Added fixture-backed `matrix.is_diagonal` and `values.is_diagonal()` support
  for read-only diagonal-value checks on runtime-owned float matrices,
  including rectangular matrices, `na` cells, and zero-dimension matrices.
- Added fixture-backed `matrix.is_binary` and `values.is_binary()` support for
  read-only binary-value checks on runtime-owned float matrices, including `na`
  cells and zero-dimension matrices.
- Added fixture-backed `matrix.is_zero` and `values.is_zero()` support for
  read-only zero-value checks on runtime-owned float matrices, including `na`
  cells and zero-dimension matrices.
- Added fixture-backed `matrix.is_square` and `values.is_square()` support for
  read-only matrix shape checks on runtime-owned float matrices.
- Added fixture-backed `matrix.reverse` and `values.reverse()` support for
  in-place reversal of runtime-owned float matrices, including zero-dimension
  no-op behavior and UDF side-effect rejection.
- Added fixture-backed `matrix.transpose` and `values.transpose()` support for
  returning independent transposed copies of runtime-owned float matrices,
  including zero-dimension shape swaps.
- Added fixture-backed `matrix.elements_count` and `values.elements_count()`
  support for read-only element-count reads of runtime-owned float matrices,
  including zero-dimension and reshaped matrices.
- Added fixture-backed `matrix.mode` and `values.mode()` support for read-only
  mode scans of runtime-owned float matrices, ignoring `na` cells and returning
  `na` for empty, all-`na`, or no-repeated-value matrices.
- Added fixture-backed `matrix.min`/`matrix.max` and `values.min()`/
  `values.max()` support for read-only min/max scans of runtime-owned float
  matrices, ignoring `na` cells and returning `na` for empty or all-`na`
  matrices.
- Added fixture-backed `matrix.avg` and `values.avg()` support for read-only
  averaging of runtime-owned float matrices, ignoring `na` cells and returning
  `na` for empty or all-`na` matrices.
- Added fixture-backed `matrix.sum` and `values.sum()` support for read-only
  summing of runtime-owned float matrices, ignoring `na` cells and returning
  `na` for empty or all-`na` matrices.
- Added fixture-backed `matrix.add_row` and `values.add_row(row, array_id)`
  support for inserting copied `array<float>` rows into runtime-owned float
  matrices, with semantic UDF side-effect rejection and runtime bounds/size
  guards.
- Added fixture-backed `matrix.add_col` and `values.add_col(column, array_id)`
  support for inserting copied `array<float>` columns into runtime-owned float
  matrices, with semantic UDF side-effect rejection and runtime bounds/size
  guards.
- Added fixture-backed `matrix.remove_row` and `values.remove_row(row)` support
  for deleting rows from runtime-owned float matrices, with semantic UDF
  side-effect rejection and runtime bounds/`na` row-index guards.
- Added fixture-backed `matrix.remove_col` and `values.remove_col(column)`
  support for deleting columns from runtime-owned float matrices, with semantic
  UDF side-effect rejection and runtime bounds/`na` column-index guards.
- Added read-only strategy-mode `strategy.buy_and_hold_return_percent` as a
  series float based on the first loaded bar close, with sema/runtime fixture
  coverage for supported reads and unsupported indicator/request/mutation
  contexts.
- Added fixture-backed `matrix.reshape` namespace-call support that preserves
  matrix element order and element count.
- Added fixture-backed `values.reshape(rows, columns)` matrix method-call
  lowering to the supported `matrix.reshape` runtime operation.
- Added fixture-backed `matrix.row` and `matrix.col` namespace-call support that
  returns independent `array<float>` row/column snapshots.
- Added fixture-backed `values.row(row)` matrix method-call lowering to the
  supported `matrix.row` runtime operation.
- Added fixture-backed `values.col(column)` matrix method-call lowering to the
  supported `matrix.col` runtime operation.
- Added public runtime fixture coverage for matrix row/column extraction reads
  through `if`/`else` branches.
- Added public runtime fixture coverage for matrix row/column extraction reads
  through `while` loops.
- Added public runtime fixture coverage for matrix shape reads after reshape
  calls inside `while` loops.
- Added public runtime fixture coverage for matrix copy independence inside
  `while` loops.
- Added public runtime fixture coverage for matrix set mutation ordering inside
  `while` loops.
- Added public runtime fixture coverage for matrix fill mutation ordering inside
  `while` loops.
- Added public runtime fixture coverage for matrix reshape mutation ordering
  inside `while` loops.
- Added fixture-backed `while` expression coverage for `matrix<float>` results
  with caller-side reads and mutation, including fresh matrix results and
  existing-matrix alias returns.
- Added fixture-backed `while` expression coverage for `matrix<float>` result
  preservation across `continue` and `break`.
- Added fixture-backed `while` expression coverage for scalar-array result
  preservation across `continue` and `break`.
- Added fixture-backed history coverage for scalar-array values produced by
  `while` expressions, including fresh historical copies.
- Added fixture-backed history coverage for `matrix<float>` values produced by
  `while` expressions, including fresh historical copies.
- Added fixture-backed `while` expression coverage for scalar-array
  zero-iteration `na` results and safe branch-gated size reads on that `na`
  result.
- Added fixture-backed `while` expression coverage for `matrix<float>`
  zero-iteration `na` results and safe shape reads on that `na` result.
- Added fixture-backed `matrix<float>` typed declarations with compatible matrix
  or `na` initializers.
- Added public runtime fixture coverage for committed `matrix<float>` history
  snapshots returning independent matrix copies.
- Added public runtime fixture coverage for UDF-returned independent matrix
  copies.
- Added matrix slot/cell counters to runtime profiles.
- Added public runtime fixture coverage for read-only matrix cell and shape reads
  inside user-defined functions.
- Added public runtime fixture coverage for matrix mutation/readback ordering
  inside branches and loops.
- Added public runtime fixture coverage for zero-row and zero-column matrix
  constructor shape reads.
- Added public runtime-error fixture coverage for `na` matrix constructor
  dimensions.
- Added public runtime-error fixture coverage for `na` row/column indexes in
  matrix cell reads and writes.
- Added public runtime-error fixture coverage for negative `matrix.set`
  row/column bounds.
- Added public runtime-error fixture coverage for `matrix.set` row/column
  bounds.
- Added public runtime-error fixture coverage for negative `matrix.get`
  row/column indexes.
- Added public runtime-error fixture coverage for `matrix.get` column bounds.
- Added public runtime-error fixture coverage for negative
  `matrix.new<float>` dimensions and the cell budget guard.
- Added dedicated negative fixture coverage and a matrix-specific diagnostic for
  unsupported `varip` matrix declarations.
- Added fixture-backed ordinary `var` matrix persistence and realtime
  forming-bar rollback coverage for runtime-owned `matrix<float>` mutation.
- Added fixture-backed public coverage for same-entry-id partial
  `strategy.exit(..., from_entry=id, qty=...)` allocation under
  `close_entries_rule="ANY"`, locking stable ledger-order closed-trade output.
- Accepted `strategy(..., close_entries_rule="ANY")` for the fixture-backed
  long-only `strategy.close(id)` and `strategy.exit(..., from_entry=id)` subset,
  while keeping broader omitted-entry, close-all, short/reversal, generic-order,
  and OCA allocation behavior out of scope.
- Added internal broker coverage for `close_entries_rule="ANY"` allocation on
  `strategy.exit(..., from_entry=id)`.
- Wired the internal close-entry rule through `BrokerState` close/exit
  allocation decisions and added broker-level `"ANY"` path coverage.
- Added an internal ledger allocation helper and unit coverage for future
  `close_entries_rule="ANY"` entry-id selection.
- Expanded the pure-internal `close_entries_rule` reference with an `"ANY"`
  design audit covering command scope, deterministic entry-id allocation,
  reservation identity, closed-trade records, and the first behavior-slice
  fixtures.
- Added `strategy(..., close_entries_rule="FIFO")` as an explicit default FIFO
  allocation setting, with HIR/runtime settings storage and fixture-backed
  parity for current long-only close and exit allocation.
- Added metadata support for the fixture-backed `strategy.order()` subset:
  `comment`, `alert_message`, and `disable_alert` are accepted on supported
  long market/limit/stop/stop-limit orders and reduce-only short market orders,
  with comments retained for trade comment helpers and fill payloads exposed in
  `strategy.alerts`.
- Added omitted-qty long `strategy.order()` support for market, limit, stop, and
  stop-limit orders, resolving the configured default fixed/cash/percent
  quantity at placement time with runtime snapshot coverage for each supported
  long order family while keeping omitted `qty` unsupported for
  `strategy.short`.
- Added fixture-backed stop-limit-long
  `strategy.order(id, strategy.long, qty=..., stop=stop_price,
  limit=limit_price)` support using the existing long stop-limit timing model
  while bypassing `strategy.entry()` pyramiding.
- Added fixture-backed stop-long
  `strategy.order(id, strategy.long, qty=..., stop=price)` support using the
  existing long stop timing model while bypassing `strategy.entry()` pyramiding.
- Added fixture-backed limit-long
  `strategy.order(id, strategy.long, qty=..., limit=price)` support using the
  existing long limit timing model while bypassing `strategy.entry()`
  pyramiding.
- Added reduce-only `strategy.order(id, strategy.short, qty=...)` support that
  can shrink existing long exposure without opening short positions, while
  keeping short exposure, reversals, short price-based orders, and OCA
  unsupported.
- Added long-only `strategy.margin_liquidation_price` support for active
  `margin_long` positions, while keeping short margin, tick rounding, and
  margin-specific public schema expansion unsupported.
- Added pyramiding runtime coverage for indexed
  `strategy.closedtrades.*` field reads over multiple closed trades.
- Added pyramiding runtime coverage for `strategy.opentrades.commission`,
  `strategy.opentrades.max_runup`, and `strategy.opentrades.max_drawdown`
  indexed open-trade reads.
- Aligned individual `strategy.opentrades.*` field conformance rows with
  fixture-backed pyramiding index reads.
- Added runtime coverage for reading second open-trade field values in the
  current long-only pyramiding subset.
- Aligned strategy trade comment field semantic feature tracking with the
  existing runtime and documentation coverage.
- Clarified unsupported `strategy.risk.*` diagnostics to identify broker risk
  rules separately from generic strategy order gaps.
- Added representative negative fixture coverage for unsupported
  `strategy.risk.*` broker-rule calls.
- Added a pure-internal design gate for future `strategy.risk.*` broker rules.
- Added a pure-internal design gate for future strategy short-margin and richer
  account semantics.
- Added a pure-internal design gate for future strategy execution timing and
  recalculation semantics.
- Added a pure-internal design gate for future strategy OCA group semantics.
- Added a pure-internal design gate for future strategy `close_entries_rule`
  allocation semantics.
- Added a pure-internal design gate for future generic `strategy.order()`
  netting semantics.
- Added a pure-internal design gate for future strategy short-entry and
  automatic reversal semantics.
- Added a pure-internal design gate for future `while` expression result
  semantics.
- Added default-arm fixture coverage for rejecting `switch` statement-block
  arms.
- Added a semantic fixture for rejecting imported UDT construction inside a
  `varip` initializer until imported UDT identity is implemented.
- Added a semantic fixture for rejecting mismatched UDT identity assignment into
  an explicitly typed UDT `varip` slot.
- Added selector-form fixture coverage for rejecting `switch` statement-block
  arms, keeping future statement-block support gated behind the switch block
  design path.
- Added fixture-backed statement-form `for...in` iteration for
  `array<chart.point>` values, with value-copy loop locals, field reads, and
  local field mutation that does not write back to the source slot.
- Added fixture-backed statement-form `for...in` iteration for `array<label>`
  values, with shallow-id loop locals, getter/setter calls, and setter
  visibility through the source array id.
- Added fixture-backed statement-form `for...in` iteration for `array<line>`
  values, with shallow-id loop locals, getter/setter calls, and setter
  visibility through the source array id.
- Added fixture-backed statement-form `for...in` iteration for `array<linefill>`
  values, with shallow-id loop locals, getter/setter calls, and setter
  visibility through source array ids and linefill snapshots.
- Added fixture-backed statement-form `for...in` iteration for `array<polyline>`
  values, with shallow-id loop locals and deletion visibility through
  `polyline.all`.
- Added fixture-backed statement-form `for...in` iteration for `array<box>`
  values, with shallow-id loop locals, setter calls, deletion, and `box.all`
  visibility.
- Added fixture-backed statement-form `for...in` iteration for `array<table>`
  values, with shallow-id loop locals, cell writes, deletion, and `table.all`
  visibility.
- Added fixture-backed statement-form `for...in` iteration for same-local
  scalar-tree UDT arrays, with value-copy loop locals, field reads, and local
  field mutation that does not write back to the source slot.
- Added fixture-backed statement-form `for index, value in values` iteration for
  `array<int>` values, with a zero-based `series int` index loop-local while
  keeping imported or non-scalar-tree UDT, map/matrix, and expression-form
  index/value iteration unsupported.
- Added fixture-backed statement-form `for index, value in values` iteration for
  `array<float>` values, reusing the zero-based `series int` index loop-local
  while keeping imported or non-scalar-tree UDT and map/matrix iteration
  unsupported at that slice.
- Added fixture-backed statement-form `for index, value in values` iteration for
  `array<bool>` values, reusing the zero-based `series int` index loop-local
  while keeping imported or non-scalar-tree UDT, map/matrix, and expression-form
  index/value iteration unsupported.
- Added fixture-backed statement-form `for index, value in values` iteration for
  `array<string>` values, reusing the zero-based `series int` index loop-local
  while keeping imported or non-scalar-tree UDT, map/matrix, and expression-form
  index/value iteration unsupported.
- Added fixture-backed statement-form `for index, value in values` iteration for
  `array<color>` values, reusing the zero-based `series int` index loop-local
  while keeping imported or non-scalar-tree UDT, map/matrix, and expression-form
  index/value iteration unsupported.
- Added fixture-backed statement-form `for index, value in values` iteration for
  `array<label>` values, reusing the zero-based `series int` index loop-local
  while keeping imported or non-scalar-tree UDT, map/matrix, and expression-form
  index/value iteration unsupported.
- Added fixture-backed statement-form `for index, value in values` iteration for
  `array<line>` values, reusing the zero-based `series int` index loop-local
  while keeping imported or non-scalar-tree UDT, map/matrix, and expression-form
  index/value iteration unsupported.
- Added fixture-backed statement-form `for index, value in values` iteration for
  `array<linefill>` values, reusing the zero-based `series int` index
  loop-local while keeping imported or non-scalar-tree UDT and map/matrix
  iteration unsupported at that slice.
- Added fixture-backed statement-form `for index, value in values` iteration for
  `array<polyline>` values, reusing the zero-based `series int` index
  loop-local while keeping imported or non-scalar-tree UDT and map/matrix
  iteration unsupported at that slice.
- Added fixture-backed statement-form `for index, value in values` iteration for
  `array<box>` values, reusing the zero-based `series int` index loop-local
  while keeping imported or non-scalar-tree UDT, map/matrix, and expression-form
  index/value iteration unsupported.
- Added fixture-backed statement-form `for index, value in values` iteration for
  `array<table>` values, reusing the zero-based `series int` index loop-local
  while keeping imported or non-scalar-tree UDT, map/matrix, and expression-form
  index/value iteration unsupported.
- Added fixture-backed statement-form `for index, value in values` iteration for
  `array<chart.point>` values, reusing the zero-based `series int` index
  loop-local while preserving value-copy point locals whose field mutation does
  not write back to the source array slot.
- Added fixture-backed statement-form `for index, value in values` iteration for
  same-local scalar-tree UDT arrays, reusing the zero-based `series int` index
  loop-local while preserving value-copy UDT locals whose field mutation does not
  write back to the source array slot.
- Added a semantic fixture for rejecting non-array `for...in` iterables while
  keeping the current scalar-array statement-form subset unchanged.
- Added fixture-backed stateful built-in callsite coverage for scalar-array
  statement-form `for...in` loop bodies.
- Added fixture-backed `break`, `continue`, and loop-body local declaration
  coverage for scalar-array statement-form `for...in`.
- Added fixture-backed zero-iteration coverage for scalar-array statement-form
  `for...in` over empty arrays and typed `na` array iterables.
- Added an explicit incremental-vs-historical parity guard for the current
  scalar-array statement-form `for...in` runtime fixtures.
- Added fixture-backed scalar typed-array `varip` interaction coverage for
  statement-form `for...in`, including initial-length iteration and loop-body
  append behavior across repeated forming realtime updates.
- Added fixture-backed ordinary `var` scalar-array realtime rollback coverage for
  statement-form `for...in` loop-body mutation, while keeping index/value
  iteration, expression-form iteration, and non-scalar iterable families
  unsupported.
- Added statement-form `for...in` support for `array<float>` values, while
  keeping bool, string, color, object, UDT, map, and matrix iteration
  unsupported.
- Added statement-form `for...in` support for `array<bool>` values, while
  keeping string, color, object, UDT, map, and matrix iteration unsupported.
- Added statement-form `for...in` support for `array<string>` values, while
  keeping color, object, UDT, map, and matrix iteration unsupported.
- Added statement-form `for...in` support for `array<color>` values, completing
  the current scalar-array iteration subset while keeping object, UDT, map, and
  matrix iteration unsupported.
- Added a distinct statement-form `for...in` AST boundary for the current
  scalar-array iteration subset.
- Added a distinct internal `for...in` HIR shape, lowering path, and traversal
  support for the current scalar-array iteration subset.
- Added fixture-backed statement-form `for...in` iteration over `array<int>`
  values while keeping other element families and expression/index forms
  unsupported at that slice.
- Added fixture-backed `array<int>` `for...in` mutation policy coverage:
  initial-length iteration, current-storage reads for not-yet-visited indexes,
  append non-extension, alias mutation visibility, and shrink-to-out-of-bounds
  runtime errors.
- Added fixture-backed explicitly typed same-local scalar-field UDT `varip`
  values with realtime intrabar value persistence, including same-UDT ternary, switch, if, and for initializers.
- Added direct-constructor-inferred same-local scalar-field UDT `varip` values
  while keeping non-constructor inferred UDT `varip` rejected.
- Aligned unsupported UDT value `varip` diagnostics with the current
  explicit/direct-constructor same-local scalar-field subset, keeping UDT array
  `varip` diagnostics separate.
- Added a pure-internal design gate for future UDT `varip` values.
- Added a pure-internal design gate for future imported UDT identity.
- Added a pure-internal design gate for future `switch` statement-block arms.
- Added a parser fixture keeping `while` expressions outside the current
  statement-only `while` subset.
- Added fixture-backed direct chained UDT array slot field mutation for
  same-local scalar-field arrays, including `points.get(0).x := value` and
  `array.get(points, 0).x := value`.
- Added fixture-backed same-local scalar-tree UDT array element writeback
  semantics: field mutation on a value read from an array stays local until an
  explicit same-UDT `array.set`/`set()` writes it back.
- Added fixture-backed local pure UDF calls that consume same-local
  scalar-field UDT values read from UDT arrays and preserve UDT identity through
  passthrough or constructor returns.
- Added fixture-backed local pure UDT method calls on same-local scalar-field
  UDT values read from UDT arrays into local variables.
- Added fixture-backed `array.join` and `join()` support for same-local
  scalar-tree UDT arrays using positional `TypeName(field0, field1, ...)`
  element rendering, while keeping general `str.tostring(UDT)` unsupported.
- Added fixture-backed `array.fill` and `fill()` support for same-local
  scalar-tree UDT arrays while keeping mismatched UDT fill values rejected.
- Added fixture-backed `array.includes`, `array.indexof`, and
  `array.lastindexof` support for same-local scalar-tree UDT arrays using
  structural equality over scalar fields, while keeping mismatched UDT
  identities rejected.
- Added fixture-backed `array<T>` and `T[]` declarations for same-local
  scalar-tree UDT arrays, with `na` initialization, same-UDT reassignment, and
  UDT identity checks for mismatched array assignments.
- Added fixture-backed `array.sort_indices` support for same-local scalar-field
  UDT arrays by compile-time `int`, `float`, or `string` `sort_field`, returning
  original indexes without mutating the source array.
- Aligned existing-array `array.get`, `array.set`, `array.insert`, and
  `array.remove` out-of-bounds indexes with runtime errors while preserving
  valid negative indexing from the array end.
- Added fixture-backed lexer rejection for non-finite float literals so
  overflowing scientific notation reports `E_LEX_FLOAT` instead of silently
  becoming infinity.
- Added fixture-backed UDF-local UDT scalar field mutation for local variables
  while keeping global/parameter UDF mutation and method field mutation
  rejected as side effects.
- Added runtime fixture coverage for while-loop typed UDT declarations
  initialized and reassigned from same-local-UDT `for` expressions.
- Added fixture-backed loop-local typed UDT declarations initialized and
  reassigned from same-local-UDT `for` expressions.
- Added fixture-backed block-local typed UDT declarations initialized and
  reassigned from same-local-UDT `for` expressions.
- Added fixture-backed top-level typed UDT declarations initialized and
  reassigned from same-local-UDT `for` expressions.
- Added fixture-backed typed UDT `var` declarations initialized from
  same-local-UDT `for...in` and `while` expressions, including realtime
  rollback coverage.
- Added fixture-backed typed UDT `var` declarations initialized from
  same-local-UDT `for` expressions, including realtime rollback coverage.
- Added fixture-backed typed UDT `var` declarations initialized from
  same-local-UDT `switch` expressions, including realtime rollback coverage.
- Added fixture-backed typed UDT `var` declarations initialized from
  same-local-UDT ternary expressions, including realtime rollback coverage.
- Added fixture-backed typed UDT `var` declarations initialized from
  same-local-UDT `if` expressions, including realtime rollback coverage.
- Added fixture-backed top-level, block-local, and loop-local typed UDT
  declarations initialized from same-local-UDT `if` expressions.
- Added fixture-backed typed local UDT declarations initialized from
  same-local-UDT `if` expressions in UDF and method bodies using branch-local
  aliases.
- Added fixture-backed scalar `if` expression support with required `else`
  branches and branch-local declarations.
- Added fixture-backed typed local UDT method declarations initialized and
  reassigned from same-local-UDT `for` expressions using receiver and local UDT
  parameter aliases.
- Added fixture-backed UDF-local typed UDT declarations initialized and
  reassigned from same-local-UDT `for` expressions using UDT and scalar field
  aliases.
- Added support for omitted `label.new` text in scalar and chart-point overloads,
  defaulting the runtime snapshot text to an empty string.
- Aligned `label.new` omitted `color` and `textcolor` runtime snapshots for
  scalar and chart-point overloads with the official defaults.
- Aligned `box.new` omitted `border_color`, `bgcolor`, `text_color`, and
  `text_size` runtime snapshots for scalar and chart-point overloads with the
  official defaults.
- Aligned `line.new` omitted `color` runtime snapshots for both coordinate and
  chart-point overloads with the official `color.blue` default.
- Aligned `polyline.new` omitted `line_color` runtime snapshots with the
  official `color.blue` default and extended the fixture-backed snapshot
  coverage for omitted style arguments.
- Added fixture-backed `array.new_polyline` and `array.from(polyline, ...)`
  support for runtime-owned polyline id arrays, including generic object-array
  storage, mutation, read, search, copy, slice, concat, reverse, clear, and
  method-call behavior, plus official `array.new<polyline>` template syntax
  and typed `array<polyline>`/`polyline[]` declarations.
- Added fixture-backed polyline array and slice history snapshots across the
  WASM host contract.
- Added fixture-backed pure local UDT method coverage for constructors that
  return values from additional local UDT parameter fields through ternary,
  switch, final if/else, and final for bodies, with matching semantic analyzer
  regression tests and execution-semantics documentation.
- Added fixture-backed UDF-local and method-local typed UDT declarations
  initialized and reassigned through same-local-UDT `for...in` and `while`
  expressions.
- Added fixture-backed scalar-tree imported UDT typed declarations initialized
  and reassigned through same-imported-identity `for...in` expression results,
  with a matching identity-mismatch diagnostic fixture.
- Bumped machine-readable analysis reports to `schemaVersion: 3` and added
  top-level `inputs` metadata for executable scripts, exposing each `input*`
  call's call-site id, function name, and literal title when available.
- Added Python host `input_overrides` support for `Program.run()` and
  `run_script()`, keyed by analysis `inputs[].callSiteId` and wired to the
  runtime `InputOverrides` path for scalar `input.*` execution values.
- Added CLI `run --input-override CALL_SITE_ID=value` support, including
  profiled runs, with values parsed against the analyzed `input.*` call type.
- Added WASM `*WithInputOverrides` run APIs that accept an `inputOverridesJson`
  object keyed by analysis `inputs[].callSiteId`, including request-bars,
  library-source, and compiled `Program` run variants.
- Added a Rust runtime `InputOverrides` path for call-site keyed `input.*`
  execution values, while keeping existing default-`defval` behavior when no
  override is supplied.
- Added fixture-backed scalar array, scalar slice, label-array, label-slice,
  line-array, line-slice, box-slice, linefill-array, linefill-slice,
  polyline-array, polyline-slice, box-array, table-array, table-slice,
  chart.point-array, and chart.point-slice variable history snapshots for
  Pine-style `previous = a[1]` and
  `na(previous) ? na : previous.get(0)` reads, with retained array values copied
  into history and positive-offset history reads returning a fresh array copy.
- Added fixture-backed Pine-style shallow `array.slice` window semantics:
  slice reads/writes mirror the parent window, slice insertions widen the
  window and insert into the parent, and parent shrinkage that leaves the
  window out of bounds now reports a runtime error.
- Added fixture-backed object `array.new<type>` constructor syntax for label,
  line, linefill, box, and table arrays, normalized onto the existing
  `array.new_*` runtime paths.
- Added fixture-backed scalar `array.new<type>` constructor syntax for float,
  int, bool, string, and color arrays, normalized onto the existing
  `array.new_*` runtime paths.
- Added fixture-backed `type[]` array declaration alias coverage for `var`
  declarations and the scalar typed-array `varip` subset, aligned with Pine's
  `[var/varip ][array<type>/<type[]> ]` declaration syntax.
- Added fixture-backed `label.new(point, text, ...)` chart-point overload
  support: point-based label snapshots use `point.index` for `xloc.bar_index`
  labels and `point.time` for `xloc.bar_time` labels, while preserving label
  text, style, color, alignment, font-family, and text-formatting fields.
- Added fixture-backed `label.set_point()` chart-point coordinate mutation
  support: point-based label snapshots use `point.index` for `xloc.bar_index`
  labels and `point.time` for `xloc.bar_time` labels, with namespace-call and
  method-call coverage.
- Added fixture-backed `box.new(top_left, bottom_right, ...)` chart-point
  overload support: point-based box snapshots use `point.index` for
  `xloc.bar_index` and `point.time` for `xloc.bar_time`, while preserving the
  existing box style, text, fill, and border snapshot fields.
- Added fixture-backed `box.set_top_left_point()` and
  `box.set_bottom_right_point()` chart-point corner mutation support:
  point-based corner snapshots use `point.index` for `xloc.bar_index` boxes
  and `point.time` for `xloc.bar_time` boxes, with namespace-call and
  method-call coverage.
- Added fixture-backed `line.set_first_point()` and
  `line.set_second_point()` chart-point endpoint mutation support: point-based
  endpoint snapshots use `point.index` for `xloc.bar_index` lines and
  `point.time` for `xloc.bar_time` lines, with namespace-call and method-call
  coverage.
- Added fixture-backed `line.new(first_point, second_point, ...)` chart-point
  overload support: point-based line snapshots use `point.index` for
  `xloc.bar_index` and `point.time` for `xloc.bar_time`, while preserving the
  existing line style, extend, color, and width snapshot fields.
- Added fixture-backed `box.new()` and `box.set_xloc()` `xloc.bar_time`
  snapshot support: box snapshots now retain `xloc`, and time-coordinate
  left/right values are exposed to JSON/Python outputs.
- Added fixture-backed `line.new()` and `line.set_xloc()` `xloc.bar_time`
  snapshot support: line snapshots now retain `xloc`, time-coordinate x1/x2
  values are exposed to JSON/Python outputs, and `line.get_price()` continues
  to return `na` for time-coordinate lines because timestamp interpolation
  remains outside the supported getter subset.
- Added fixture-backed `label.new`/`label.copy` max-count eviction: omitted
  declarations use the runtime's default 50-label limit, while named
  `max_labels_count` values from 1 through 500 are consumed from
  indicator/strategy HIR and evict the oldest active label snapshots before new
  creation.
- Added fixture-backed `box.new`/`box.copy` max-count eviction: omitted
  declarations use the runtime's default 50-box limit, while named
  `max_boxes_count` values from 1 through 500 are consumed from
  indicator/strategy HIR and evict the oldest active box snapshots before new
  creation.
- Added fixture-backed `line.new`/`line.copy` max-count eviction: omitted
  declarations use the runtime's default 50-line limit, while named
  `max_lines_count` values from 1 through 500 are consumed from
  indicator/strategy HIR and evict the oldest active line snapshots before new
  creation.
- Added fixture-backed `polyline.new` max-count eviction: omitted declarations
  use the runtime's default 50-polyline limit, while named
  `max_polylines_count` values from 1 through 100 are consumed from
  indicator/strategy HIR and evict the oldest active polyline snapshots before
  new creation.
- Added fixture-backed realtime rollback coverage for the supported
  `polyline.new` / `polyline.delete` / `polyline.all` lifecycle subset,
  proving abandoned forming-bar creation, deletion, copied point lists, and
  current-id reads do not leak into confirmed runtime state.
- Added fixture-backed partial `polyline.delete` and `polyline.all` lifecycle
  support, including deletion snapshots, namespace and method-call deletion,
  `na` no-op behavior, and current-id filtering in `polyline.all`. Later
  bullets extend polyline arrays and declaration-driven max-count eviction.
- Added fixture-backed partial `polyline.new` support over
  `array<chart.point>` inputs, with runtime-owned polyline ids, copied point
  lists, style fields, CLI/Python/WASM `polylines` output, and runtime
  `schemaVersion: 7`. Later bullets extend polyline arrays and
  declaration-driven max-count eviction.
- Added fixture-backed `array.new<chart.point>()` parsing, semantic validation,
  and runtime construction for chart-point arrays, including optional
  `initial_value` handling.
- Added fixture-backed `array.from(chart.point, ...)` point-array inference and
  generic chart-point array storage/read/mutation/search support for the
  historical polyline lifecycle subset.
- Added fixture-backed partial `chart.point` constructor, copy, field read, and
  top-level field mutation support as the first executable prerequisite for
  follow-up polyline work.
- Refreshed the `polyline.*` implementation gate with an official-semantics
  sequence covering `chart.point`, `array<chart.point>`, polyline snapshots,
  deletion, `.all`, rollback, and host parity before support is claimed.
- Added fixture-backed partial `array.new_linefill` and `array.from(linefill)`
  support for linefill id arrays plus generic object-array mutation, read, and
  search helpers.
- Added fixture-backed partial `linefill.delete` support with deletion
  snapshots and `.all` omission of deleted linefills.
- Added fixture-backed partial `linefill.all` support for exposing a snapshot
  array of currently existing linefill ids while omitting replaced linefills.
- Added fixture-backed `linefill.get_line1()` and `linefill.get_line2()`
  support for returning referenced line ids from runtime-owned linefill objects.
- Synchronized drawing-object architecture documentation with current
  fixture-backed label, line, and box style, location, and extend support.
- Added explicit creation and mutation snapshot coverage for the base drawing
  style constants `line.style_solid`, `line.style_dotted`, and
  `line.style_dashed` across line styles and box border styles.
- Added fixture-backed coverage for the official `extend.left`,
  `extend.right`, `extend.both`, and `extend.none` constants in `line.new()`,
  `line.set_extend()`, `box.new()`, and `box.set_extend()` snapshots.
- Added fixture-backed semantic coverage that keeps box border styles limited to
  the official `line.style_solid`, `line.style_dotted`, and
  `line.style_dashed` subset while rejecting line arrow styles for
  `box.new()` and `box.set_border_style()`.
- Added fixture-backed coverage for the remaining official line style constants
  `line.style_arrow_left`, `line.style_arrow_right`, and
  `line.style_arrow_both` in `line.new()` creation and `line.set_style()`
  mutation snapshots.
- Added host-neutral `label.new()` creation coverage for `xloc.bar_time` and
  `yloc.abovebar`/`yloc.belowbar` snapshot fields.
- Added the remaining official label style constants
  `label.style_square`, `label.style_diamond`, and
  `label.style_label_center` for label creation and style mutation snapshots.
- Synchronized label drawing documentation with current `label.new` location,
  y-location, and official style support.
- Added fixture-backed while-loop control-flow `label.set_x` mutation coverage.
- Added fixture-backed while-loop control-flow `label.set_y` mutation coverage.
- Added fixture-backed while-loop control-flow `label.set_xy` mutation coverage.
- Added fixture-backed while-loop control-flow `label.set_text` mutation
  coverage.
- Added fixture-backed while-loop control-flow `label.set_size` mutation
  coverage.
- Added independent while-loop control-flow `label.set_x` mutation coverage.
- Added independent while-loop control-flow `label.set_y` mutation coverage.
- Added independent while-loop control-flow `label.set_xy` mutation coverage.
- Added independent while-loop control-flow `label.set_text` mutation coverage.
- Synchronized label coordinate/text/size mutator documentation with
  independent while-loop coverage.
- Added independent while-loop control-flow `label.set_color` mutation coverage.
- Added independent while-loop control-flow `label.set_textcolor` mutation
  coverage.
- Added independent while-loop control-flow `label.set_style` mutation coverage.
- Added independent while-loop control-flow `label.set_textalign` mutation
  coverage.
- Added independent while-loop control-flow `label.set_text_font_family`
  mutation coverage.
- Added independent while-loop control-flow `label.set_text_formatting`
  mutation coverage.
- Added independent while-loop control-flow `label.set_tooltip` mutation
  coverage.
- Synchronized label appearance/text-style mutator documentation with
  independent while-loop coverage.
- Added independent while-loop control-flow `label.set_size` mutation coverage.
- Added independent while-loop control-flow `label.set_xloc` mutation coverage.
- Added independent while-loop control-flow `label.set_yloc` mutation coverage.
- Strengthened `label.set_xloc` and `label.set_yloc` independent while-loop
  coverage with dedicated location fixtures.
- Added independent while-loop control-flow deletion coverage for
  `label.delete`.
- Added independent while-loop control-flow deletion coverage for `line.delete`.
- Strengthened `line.delete` independent while-loop deletion coverage with a
  dedicated line lifecycle fixture path.
- Added independent while-loop control-flow deletion coverage for `box.delete`.
- Added independent while-loop control-flow cloning coverage for `label.copy`.
- Synchronized label lifecycle documentation with independent while-loop
  coverage.
- Added independent while-loop control-flow cloning coverage for `line.copy`.
- Strengthened `line.copy` independent while-loop cloning coverage with a
  dedicated line lifecycle fixture path.
- Added independent while-loop control-flow `label.get_x` read coverage.
- Added independent while-loop control-flow `label.get_y` read coverage.
- Added independent while-loop control-flow `label.get_text` read coverage.
- Added independent while-loop control-flow read coverage for `label.all`.
- Synchronized label read documentation with independent while-loop coverage.
- Added fixture-backed while-loop control-flow `table.cell` write coverage.
- Added independent while-loop control-flow `table.cell` write coverage.
- Added independent while-loop control-flow `table.cell_set_text` mutation
  coverage.
- Added independent while-loop control-flow `table.cell_set_bgcolor` mutation
  coverage.
- Added independent while-loop control-flow `table.cell_set_text_color`
  mutation coverage.
- Added independent while-loop control-flow `table.cell_set_width` mutation
  coverage.
- Added independent while-loop control-flow `table.cell_set_height` mutation
  coverage.
- Added independent while-loop control-flow `table.cell_set_text_size` mutation
  coverage.
- Added independent while-loop control-flow `table.cell_set_text_halign`
  mutation coverage.
- Added independent while-loop control-flow `table.cell_set_text_valign`
  mutation coverage.
- Added independent while-loop control-flow `table.cell_set_text_wrap`
  mutation coverage.
- Added independent while-loop control-flow `table.cell_set_tooltip`
  mutation coverage.
- Added independent while-loop control-flow `table.cell_set_text_font_family`
  mutation coverage.
- Added independent while-loop control-flow `table.cell_set_text_formatting`
  mutation coverage.
- Synchronized table cell setter documentation with independent while-loop
  mutation coverage.
- Added independent while-loop control-flow deletion coverage for
  `table.delete`.
- Added independent while-loop control-flow clearing coverage for
  `table.clear`.
- Added independent while-loop control-flow merging coverage for
  `table.merge_cells`.
- Added independent while-loop control-flow read coverage for `table.all`.
- Synchronized table deletion and `table.all` documentation with independent
  while-loop lifecycle coverage.
- Synchronized table range-operation documentation with independent while-loop
  coverage.
- Added fixture-backed while-loop control-flow `table.set_position` mutation
  coverage.
- Added independent while-loop control-flow `table.set_position` mutation
  coverage.
- Added fixture-backed while-loop control-flow `table.set_bgcolor` mutation
  coverage.
- Added independent while-loop control-flow `table.set_bgcolor` mutation
  coverage.
- Added fixture-backed while-loop control-flow `table.set_frame_color` mutation
  coverage.
- Added independent while-loop control-flow `table.set_frame_color` mutation
  coverage.
- Added fixture-backed while-loop control-flow `table.set_frame_width` mutation
  coverage.
- Added independent while-loop control-flow `table.set_frame_width` mutation
  coverage.
- Added fixture-backed while-loop control-flow `table.set_border_color` mutation
  coverage.
- Added independent while-loop control-flow `table.set_border_color` mutation
  coverage.
- Added fixture-backed while-loop control-flow `table.set_border_width` mutation
  coverage.
- Added independent while-loop control-flow `table.set_border_width` mutation
  coverage.
- Synchronized table-level setter documentation with independent while-loop
  mutation coverage.
- Added independent while-loop control-flow `box.set_left` mutation coverage.
- Added independent while-loop control-flow `box.set_top` mutation coverage.
- Added independent while-loop control-flow `box.set_right` mutation coverage.
- Added independent while-loop control-flow `box.set_bottom` mutation coverage.
- Added independent while-loop control-flow `box.set_lefttop` mutation coverage.
- Added independent while-loop control-flow `box.set_rightbottom` mutation
  coverage.
- Synchronized box geometry mutator documentation with independent while-loop
  mutation coverage.
- Added independent while-loop control-flow `box.set_bgcolor` mutation coverage.
- Added independent while-loop control-flow `box.set_border_color` mutation
  coverage.
- Added independent while-loop control-flow `box.set_border_width` mutation
  coverage.
- Added independent while-loop control-flow `box.set_border_style` mutation
  coverage.
- Added independent while-loop control-flow `box.set_extend` mutation coverage.
- Added independent while-loop control-flow `box.set_xloc` mutation coverage.
- Synchronized box style and xloc mutator documentation with independent
  while-loop mutation coverage.
- Added independent while-loop control-flow `box.set_text` mutation coverage.
- Added independent while-loop control-flow `box.set_text_color` mutation
  coverage.
- Added independent while-loop control-flow `box.set_text_size` mutation
  coverage.
- Added independent while-loop control-flow `box.set_text_halign` mutation
  coverage.
- Added independent while-loop control-flow `box.set_text_valign` mutation
  coverage.
- Added independent while-loop control-flow `box.set_text_wrap` mutation
  coverage.
- Added independent while-loop control-flow `box.set_text_font_family`
  mutation coverage.
- Added independent while-loop control-flow `box.set_text_formatting`
  mutation coverage.
- Synchronized box text mutator documentation with independent while-loop
  mutation coverage.
- Added independent while-loop control-flow cloning coverage for `box.copy`.
- Synchronized `box.copy` and `box.delete` documentation with independent
  while-loop lifecycle coverage.
- Added independent while-loop control-flow read coverage for `box.all`.
- Added independent while-loop control-flow `box.get_left` read coverage.
- Added independent while-loop control-flow `box.get_right` read coverage.
- Added independent while-loop control-flow `box.get_top` read coverage.
- Added independent while-loop control-flow `box.get_bottom` read coverage.
- Synchronized box getter and `box.all` documentation with independent
  while-loop read coverage.
- Added independent while-loop control-flow `line.get_x1` read coverage.
- Added independent while-loop control-flow `line.get_y1` read coverage.
- Added independent while-loop control-flow `line.get_x2` read coverage.
- Added independent while-loop control-flow `line.get_y2` read coverage.
- Added independent while-loop control-flow `line.get_price` read coverage.
- Added independent while-loop control-flow read coverage for `line.all`.
- Synchronized line getter and `line.all` documentation with independent
  while-loop read coverage.
- Added independent while-loop control-flow `line.set_x1` mutation coverage.
- Added independent while-loop control-flow `line.set_y1` mutation coverage.
- Added independent while-loop control-flow `line.set_xy1` mutation coverage.
- Added independent while-loop control-flow `line.set_x2` mutation coverage.
- Added independent while-loop control-flow `line.set_y2` mutation coverage.
- Added independent while-loop control-flow `line.set_xy2` mutation coverage.
- Added independent while-loop control-flow `line.set_color` mutation coverage.
- Added independent while-loop control-flow `line.set_style` mutation coverage.
- Added independent while-loop control-flow `line.set_width` mutation coverage.
- Added independent while-loop control-flow `line.set_extend` mutation coverage.
- Added independent while-loop control-flow `line.set_xloc` mutation coverage
  for the `xloc.bar_index` subset.
- Synchronized line mutator documentation with independent while-loop
  control-flow coverage.
- Synchronized line mutator conformance notes with independent while-loop
  coverage.
- Added fixture-backed while-loop control-flow `line.set_x1` mutation
  coverage.
- Added fixture-backed while-loop control-flow `line.set_y1` mutation
  coverage.
- Added fixture-backed while-loop control-flow `line.set_xy1` mutation
  coverage.
- Added fixture-backed while-loop control-flow `line.set_x2` mutation
  coverage.
- Added fixture-backed while-loop control-flow `line.set_y2` mutation
  coverage.
- Added fixture-backed while-loop control-flow `line.set_xy2` mutation
  coverage.
- Added fixture-backed while-loop control-flow `line.set_color` mutation
  coverage.
- Added fixture-backed while-loop control-flow `line.set_style` mutation
  coverage.
- Added fixture-backed while-loop control-flow `line.set_width` mutation
  coverage.
- Added fixture-backed while-loop control-flow `line.set_extend` mutation
  coverage.
- Added fixture-backed while-loop control-flow `label.set_text_formatting`
  mutation coverage.
- Added fixture-backed while-loop control-flow `label.set_text_font_family`
  mutation coverage.
- Added fixture-backed while-loop control-flow `label.set_textalign` mutation
  coverage.
- Added fixture-backed while-loop control-flow `label.set_tooltip` mutation
  coverage.
- Added fixture-backed while-loop control-flow `label.set_style` mutation
  coverage.
- Added fixture-backed while-loop control-flow `label.set_textcolor` mutation
  coverage.
- Added fixture-backed while-loop control-flow `label.set_color` mutation
  coverage.
- Added fixture-backed while-loop control-flow `box.set_border_width` mutation
  coverage.
- Added fixture-backed while-loop control-flow `box.set_border_style` mutation
  coverage.
- Added fixture-backed while-loop control-flow `box.set_extend` mutation
  coverage.
- Added fixture-backed while-loop control-flow `box.set_xloc` mutation
  coverage for the `xloc.bar_index` subset.
- Added fixture-backed while-loop control-flow `box.set_text` mutation
  coverage.
- Added fixture-backed while-loop control-flow `box.set_text_color` mutation
  coverage.
- Added fixture-backed while-loop control-flow `box.set_text_size` mutation
  coverage.
- Added fixture-backed while-loop control-flow `box.set_text_halign` mutation
  coverage.
- Added fixture-backed while-loop control-flow `box.set_text_valign` mutation
  coverage.
- Added fixture-backed while-loop control-flow `box.set_text_wrap` mutation
  coverage.
- Added fixture-backed while-loop control-flow `box.set_text_font_family`
  mutation coverage.
- Added fixture-backed while-loop control-flow `box.set_text_formatting`
  mutation coverage.
- Added fixture-backed while-loop control-flow `box.delete` coverage.
- Added fixture-backed while-loop control-flow `box.set_border_color` mutation
  coverage.
- Added fixture-backed while-loop control-flow `box.set_bgcolor` mutation
  coverage.
- Added fixture-backed while-loop control-flow `box.set_rightbottom` mutation
  coverage.
- Added fixture-backed while-loop control-flow `box.set_lefttop` mutation
  coverage.
- Added fixture-backed while-loop control-flow `box.set_bottom` mutation coverage.
- Added fixture-backed while-loop control-flow `box.set_right` mutation coverage.
- Added fixture-backed while-loop control-flow `box.set_top` mutation coverage.
- Added fixture-backed while-loop control-flow `box.set_left` mutation coverage.
- Added fixture-backed while-loop control-flow cloning coverage for `box.copy`.
- Added fixture-backed while-loop control-flow `box.get_bottom` read coverage.
- Added fixture-backed while-loop control-flow `box.get_top` read coverage.
- Added fixture-backed while-loop control-flow `box.get_right` read coverage.
- Added fixture-backed while-loop control-flow `box.get_left` read coverage.
- Added fixture-backed while-loop control-flow `box.all` read coverage after
  deletion.
- Added fixture-backed while-loop control-flow `line.set_xloc` mutation
  coverage for the `xloc.bar_index` subset.
- Added fixture-backed while-loop control-flow `line.get_y2` read coverage.
- Added fixture-backed while-loop control-flow `line.get_x2` read coverage.
- Added fixture-backed while-loop control-flow `line.get_y1` read coverage.
- Added fixture-backed while-loop control-flow `line.get_x1` read coverage.
- Added fixture-backed while-loop control-flow `line.get_price` read coverage.
- Added fixture-backed while-loop control-flow `line.all` read coverage.
- Added fixture-backed while-loop control-flow cloning coverage for
  `line.copy`.
- Added fixture-backed while-loop control-flow deletion coverage for
  `line.delete`.
- Added fixture-backed while-loop control-flow `label.get_text` read coverage.
- Added fixture-backed while-loop control-flow `label.get_y` read coverage.
- Added fixture-backed while-loop control-flow `label.get_x` read coverage.
- Added fixture-backed while-loop control-flow `label.all` read coverage.
- Added fixture-backed while-loop control-flow cloning coverage for
  `label.copy`.
- Added fixture-backed while-loop control-flow deletion coverage for
  `label.delete`.
- Added fixture-backed while-loop control-flow y-location mutation coverage for
  `label.set_yloc`.
- Added fixture-backed while-loop control-flow x-location mutation coverage for
  `label.set_xloc`.
- Added fixture-backed while-loop control-flow cell text-formatting mutation
  coverage for `table.cell_set_text_formatting`.
- Added fixture-backed while-loop control-flow cell text font-family mutation
  coverage for `table.cell_set_text_font_family`.
- Added fixture-backed while-loop control-flow cell tooltip mutation coverage
  for `table.cell_set_tooltip`.
- Added fixture-backed while-loop control-flow cell text-wrap mutation coverage
  for `table.cell_set_text_wrap`.
- Added fixture-backed while-loop control-flow cell vertical text-alignment
  mutation coverage for `table.cell_set_text_valign`.
- Added fixture-backed while-loop control-flow cell horizontal text-alignment
  mutation coverage for `table.cell_set_text_halign`.
- Added fixture-backed while-loop control-flow cell text-size mutation coverage
  for `table.cell_set_text_size`.
- Added fixture-backed while-loop control-flow cell height mutation coverage for
  `table.cell_set_height`.
- Added fixture-backed while-loop control-flow cell width mutation coverage for
  `table.cell_set_width`.
- Added fixture-backed while-loop control-flow cell text-color mutation
  coverage for `table.cell_set_text_color`.
- Added fixture-backed while-loop control-flow cell background-color mutation
  coverage for `table.cell_set_bgcolor`.
- Added fixture-backed while-loop control-flow cell text mutation coverage for
  `table.cell_set_text`.
- Added fixture-backed while-loop control-flow merge coverage for
  `table.merge_cells`.
- Added fixture-backed while-loop control-flow clearing coverage for
  `table.clear`.
- Added fixture-backed while-loop control-flow collection coverage for
  `table.all`.
- Added fixture-backed while-loop control-flow deletion coverage for
  `table.delete`.
- Added fixture-backed while-loop control-flow mutation coverage for
  `table.set_border_width`.
- Added fixture-backed while-loop control-flow mutation coverage for
  `table.set_border_color`.
- Added fixture-backed while-loop control-flow mutation coverage for
  `table.set_frame_width`.
- Added fixture-backed while-loop control-flow mutation coverage for
  `table.set_frame_color`.
- Added fixture-backed while-loop control-flow mutation coverage for
  `table.set_bgcolor`.
- Added fixture-backed while-loop control-flow mutation coverage for
  `table.set_position`.
- Added fixture-backed branch control-flow getter coverage for
  `box.get_bottom`.
- Added fixture-backed branch control-flow getter coverage for `box.get_top`.
- Added fixture-backed branch control-flow getter coverage for `box.get_right`.
- Added fixture-backed branch control-flow getter coverage for `box.get_left`.
- Added fixture-backed branch control-flow collection coverage for `box.all`.
- Added fixture-backed for-loop control-flow copy coverage for `box.copy`.
- Added fixture-backed while-loop control-flow deletion coverage for
  `box.delete`.
- Added fixture-backed while-loop control-flow mutation coverage for
  `box.set_text_formatting`.
- Added fixture-backed while-loop control-flow mutation coverage for
  `box.set_text_font_family`.
- Added fixture-backed while-loop control-flow mutation coverage for
  `box.set_text_wrap`.
- Added fixture-backed while-loop control-flow mutation coverage for
  `box.set_text_valign`.
- Added fixture-backed while-loop control-flow mutation coverage for
  `box.set_text_halign`.
- Added fixture-backed while-loop control-flow mutation coverage for
  `box.set_text_size`.
- Added fixture-backed while-loop control-flow mutation coverage for
  `box.set_text_color`.
- Added fixture-backed while-loop control-flow mutation coverage for
  `box.set_text`.
- Added fixture-backed while-loop control-flow mutation coverage for
  `box.set_xloc`.
- Added fixture-backed while-loop control-flow mutation coverage for
  `box.set_extend`.
- Added fixture-backed switch branch control-flow mutation coverage for
  `box.set_border_color`.
- Added fixture-backed branch control-flow mutation coverage for
  `box.set_rightbottom`.
- Added fixture-backed branch control-flow mutation coverage for
  `box.set_lefttop`.
- Added fixture-backed branch control-flow mutation coverage for
  `box.set_bottom`.
- Added fixture-backed branch control-flow mutation coverage for
  `box.set_right`.
- Added fixture-backed branch control-flow mutation coverage for
  `box.set_top`.
- Added fixture-backed branch control-flow mutation coverage for
  `line.set_xy2`.
- Added fixture-backed branch control-flow mutation coverage for
  `line.set_y2`.
- Added fixture-backed branch control-flow mutation coverage for
  `line.set_x2`.
- Added fixture-backed branch control-flow mutation coverage for
  `line.set_xy1`.
- Added fixture-backed branch control-flow mutation coverage for
  `line.set_y1`.
- Added fixture-backed branch control-flow mutation coverage for
  `line.set_x1`.
- Added fixture-backed switch branch control-flow mutation coverage for
  `label.set_text_formatting`.
- Added fixture-backed switch branch control-flow mutation coverage for
  `label.set_text_font_family`.
- Added fixture-backed switch branch control-flow mutation coverage for
  `label.set_textalign`.
- Added fixture-backed switch branch control-flow mutation coverage for
  `label.set_style`.
- Added fixture-backed switch branch control-flow mutation coverage for
  `label.set_textcolor`.
- Added fixture-backed branch control-flow mutation coverage for
  `label.set_xy`.
- Added fixture-backed branch control-flow mutation coverage for
  `label.set_y`.
- Added fixture-backed branch control-flow mutation coverage for
  `label.set_x`.
- Aligned the `table.cell` conformance row with existing fixture-backed
  branch/loop control-flow cell-write coverage.
- Aligned selected `box.set_*` conformance rows with existing
  fixture-backed branch/loop control-flow mutation coverage.
- Aligned selected `line.set_*` conformance rows with existing
  fixture-backed branch/loop control-flow mutation coverage.
- Aligned selected `label.set_*` conformance rows with existing
  fixture-backed branch/loop control-flow mutation coverage.
- Aligned the aggregate `array.*` conformance row with fixture-backed
  branch/loop control-flow coverage across supported array operations.
- Added fixture-backed branch and loop control-flow copy-call coverage for
  `array.copy`.
- Added fixture-backed branch and loop control-flow call coverage for
  `array.get`.
- Added fixture-backed branch and loop control-flow mutation coverage for
  `array.push`.
- Added fixture-backed branch and loop control-flow call coverage for
  `array.size`.
- Added fixture-backed branch and loop control-flow construction coverage for
  `array.new_table`.
- Added fixture-backed branch and loop control-flow construction coverage for
  `array.new_box`.
- Added fixture-backed branch and loop control-flow construction coverage for
  `array.new_label`.
- Added fixture-backed branch and loop control-flow construction coverage for
  `array.new_line`.
- Added fixture-backed branch and loop control-flow construction coverage for
  `array.new_color`.
- Added fixture-backed branch and loop control-flow construction coverage for
  `array.new_string`.
- Added fixture-backed branch and loop control-flow construction coverage for
  `array.new_bool`.
- Added fixture-backed branch and loop control-flow construction coverage for
  `array.new_int`.
- Added fixture-backed branch and loop control-flow construction coverage for
  `array.new_float`.
- Added fixture-backed branch and loop control-flow coverage for `array.from`
  inference across scalar array element kinds.
- Added fixture-backed branch and loop control-flow coverage for `array.abs`
  while preserving source-array non-mutation.
- Added fixture-backed branch and loop control-flow read coverage for
  `array.first` and `array.last`.
- Added fixture-backed branch and loop control-flow mutation coverage for
  `array.fill`.
- Added fixture-backed branch and loop control-flow mutation coverage for
  `array.set`.
- Added fixture-backed branch and loop control-flow mutation coverage for
  `array.pop`.
- Added fixture-backed branch and loop control-flow mutation coverage for
  `array.shift` and `array.unshift`.
- Added fixture-backed branch and loop control-flow mutation coverage for
  `array.insert` and `array.remove`.
- Added fixture-backed branch and loop control-flow coverage for `array.slice`.
- Added fixture-backed branch and loop control-flow mutation coverage for
  `array.clear`.
- Added fixture-backed branch and loop control-flow coverage for `array.join`.
- Added fixture-backed branch and loop control-flow coverage for
  `array.variance` and `array.stdev`.
- Added fixture-backed branch and loop control-flow coverage for
  `array.standardize`.
- Added fixture-backed branch and loop control-flow coverage for
  `array.covariance`.
- Added fixture-backed branch and loop control-flow coverage for
  `array.percentrank`.
- Added fixture-backed branch and loop control-flow coverage for
  `array.percentile_nearest_rank` and
  `array.percentile_linear_interpolation`.
- Added fixture-backed branch and loop control-flow coverage for
  `array.median` and `array.mode`.
- Added fixture-backed branch and loop control-flow coverage for `array.sum`,
  `array.avg`, and `array.range`.
- Added fixture-backed branch and loop control-flow coverage for `array.min`
  and `array.max`.
- Added fixture-backed branch and loop control-flow coverage for
  `array.binary_search`, `array.binary_search_leftmost`, and
  `array.binary_search_rightmost`.
- Added fixture-backed branch and loop control-flow coverage for
  `array.every` and `array.some`.
- Added fixture-backed branch and loop control-flow coverage for
  `array.includes`, `array.indexof`, and `array.lastindexof`.
- Added fixture-backed branch and loop copy-site coverage for `array.copy`
  while preserving source-array independence.
- Added fixture-backed branch and loop control-flow mutation coverage for
  `array.concat` while preserving source-array non-mutation.
- Added fixture-backed branch and loop control-flow coverage for
  `array.sort_indices` while preserving source-array non-mutation.
- Added fixture-backed computed-bound coverage for `array.slice`.
- Added fixture-backed computed-index and computed-range coverage for
  `array.insert`, `array.remove`, and `array.fill` scalar-array operands.
- Added fixture-backed computed-size constructor coverage for label, line, box,
  and table id arrays while keeping linefill/polyline arrays unsupported.
- Added fixture-backed computed-size constructor coverage for int, bool, string,
  and color arrays.
- Aligned `str.pos` runtime behavior with Pine's `na` substring rule: a `na`
  search substring now returns position 0 while a `na` source still returns
  `na`.
- Added fixture-backed drawing method-syntax coverage for supported
  coordinate/location mutators while keeping unsupported chart-point variants
  out of scope.
- Added fixture-backed `array.sort` and `array.reverse` branch/loop control-flow
  coverage for scalar arrays while keeping UDF array mutation side effects
  unsupported.
- Added fixture-backed local UDT scalar field mutation coverage inside branch
  and for-loop bodies while keeping mutation inside UDFs and methods
  unsupported.
- Added fixture-backed unsupported coverage for the remaining
  `array.new_linefill` construction boundary.
- Added fixture-backed unsupported coverage for `polyline.all`, keeping the
  remaining polyline object collection boundary explicit.
- Added fixture-backed coverage for earlier linefill collection gating.
- Added fixture-backed partial `table.all` support for exposing a snapshot
  array of currently existing table ids while omitting deleted tables.
- Added fixture-backed partial `box.all` support for exposing a snapshot array
  of currently existing box ids while omitting deleted boxes.
- Added fixture-backed partial `line.all` support for exposing a snapshot array
  of currently existing line ids while omitting deleted lines.
- Added fixture-backed partial `label.all` support for exposing a snapshot
  array of currently existing label ids while omitting deleted labels.
- Added fixture-backed `str.format` UTC date/time placeholder coverage for the
  `D`, `E`, `w`, and `W` format tokens.
- Added fixture-backed `str.format_time` support for the `W` week-of-month
  format token in the current Monday-based week subset.
- Added fixture-backed `str.format_time` support for the `w` ISO week-of-year
  format token.
- Added fixture-backed `str.format_time` support for the `E` weekday format
  token.
- Added fixture-backed `str.format_time` support for the `D` day-of-year
  format token.
- Added fixture-backed fixed-offset timezone support to `time()` and
  `time_close()` time-based session filtering while leaving IANA timezone
  conversion, exchange-timezone defaults, and named-session data unsupported.
- Added fixture-backed fixed-offset timezone support to `str.format_time`,
  including UTC/GMT offset strings and numeric offsets such as `+05:30` while
  leaving IANA timezone conversion and exchange-timezone defaults unsupported.
- Added fixture-backed fixed-offset timezone support to calendar component
  functions such as `hour(time, "UTC+4")` while leaving IANA timezone
  conversion and exchange-timezone defaults unsupported.
- Added fixture-backed fixed-offset timezone support to numeric `timestamp()`
  calls, covering `UTC`/`GMT` offset strings and numeric offsets such as
  `+05:30` while leaving IANA timezone conversion and exchange-timezone default
  semantics unsupported.
- Added fixture-backed numeric `timestamp()` offset normalization for zero,
  negative, and overflow month/day/time values.
- Added fixture-backed `timestamp(dateString)` support for const ISO dates,
  English month dates, optional time-of-day, and UTC/GMT/fixed-offset timezone
  tokens while leaving IANA timezone conversion, broader date-string parsing,
  and exchange-timezone default semantics unsupported.
- Added fixture-backed UTC-equivalent `timezone` support and named calendar
  argument parsing to the numeric `timestamp()` subset while leaving
  IANA timezone conversion and exchange-timezone default semantics unsupported.
- Added fixture-backed UTC time-based `session` argument support to the current
  `time(timeframe)` and `time_close(timeframe)` subset, including `24x7`,
  `HHmm-HHmm`, comma-separated periods, optional Pine day digits, overnight
  periods, and session-end clipping for `time_close`, while leaving
  IANA/exchange timezone conversion and named-session data unsupported.
- Added fixture-backed `timeframe_bars_back` support to the current
  `time(timeframe)` and `time_close(timeframe)` subset, applying chart
  `bars_back` first and then offsetting on the requested UTC timeframe bucket
  while leaving IANA/exchange timezone conversion unsupported.
- Added fixture-backed `bars_back` support to the current `time(timeframe)` and
  `time_close(timeframe)` subset, using the fixed chart timeframe before UTC
  timeframe bucket mapping.
- Added fixture-backed `time(timeframe)` and `time_close(timeframe)` support for
  the current fixed chart timeframe and UTC higher-timeframe bucket open/close
  timestamps; session and timezone overloads remain unsupported.
- Added fixture-backed `settlement_as_close.*` and `backadjustment.*` constants
  plus partial `ticker.new`/`ticker.modify` support for recording those
  futures-specific ticker ID modifiers.
- Added fixture-backed partial `ticker.inherit` support for inheriting the
  runtime's known ticker ID modifiers onto another symbol.
- Added fixture-backed partial `ticker.pointfigure` support for Point & Figure
  ticker ID construction while leaving actual non-standard OHLC data
  host/request-provider-owned.
- Added fixture-backed partial `ticker.kagi` support for Kagi ticker ID
  construction while leaving actual non-standard OHLC data
  host/request-provider-owned.
- Added fixture-backed partial `ticker.linebreak` support for Line Break ticker
  ID construction while leaving actual non-standard OHLC data
  host/request-provider-owned.
- Added fixture-backed partial `ticker.renko` support for Renko ticker ID
  construction while leaving actual non-standard OHLC data
  host/request-provider-owned.
- Added fixture-backed partial `ticker.heikinashi` support for Heikin Ashi
  ticker ID construction while leaving actual non-standard OHLC data
  host/request-provider-owned.
- Added fixture-backed `adjustment.none`, `adjustment.splits`, and
  `adjustment.dividends` constants plus partial `ticker.new`/`ticker.modify`
  adjustment modifier support for modified ticker IDs.
- Added fixture-backed partial `ticker.modify(..., session)` support for
  session-modified ticker IDs.
- Added fixture-backed partial `ticker.new(..., session)` support for
  session-modified ticker IDs.
- Added fixture-backed partial `ticker.modify` support for the single-argument
  no-modifier ticker ID subset.
- Added fixture-backed partial `ticker.new` support for the two-argument
  default `PREFIX:TICKER` constructor subset.
- Added fixture-backed partial `ticker.standard` support for simple-string
  standard ticker IDs while leaving other ticker constructors unsupported.
- Tightened `syminfo` metadata closeout by documenting the
  `syminfo.main_tickerid` signature and asserting analyzer support evidence for
  `syminfo.main_tickerid` and `syminfo.mincontract`.
- Added fixture-backed `time_tradingday` for the current UTC single-day session
  subset while leaving overnight trading-day rollover host/session-owned.
- Added fixture-backed `barstate.islastconfirmedhistory` for the current
  runtime's last known confirmed historical bar.
- Added fixture-backed `last_bar_index` and `last_bar_time` series variables
  for the last known loaded chart bar in the current runtime dataset.
- Added fixture-backed fixed-default chart viewport metadata variables:
  `chart.left_visible_bar_time` and `chart.right_visible_bar_time`.
- Added fixture-backed fixed-default chart appearance metadata variables:
  `chart.bg_color` and `chart.fg_color`.
- Added fixture-backed fixed-default regular-session boundary variables:
  `session.isfirstbar`, `session.islastbar`,
  `session.isfirstbar_regular`, and `session.islastbar_regular`.
- Added fixture-backed fixed-default chart type metadata variables:
  `chart.is_standard`, `chart.is_heikinashi`, `chart.is_kagi`,
  `chart.is_linebreak`, `chart.is_pnf`, `chart.is_range`, and
  `chart.is_renko`.
- Added fixture-backed `syminfo.prefix(symbol)` and `syminfo.ticker(symbol)`
  simple-string helpers while preserving the existing fixed default
  `syminfo.prefix` and `syminfo.ticker` variables.
- Added fixture-backed fixed-default `syminfo.sector`,
  `syminfo.industry`, and `syminfo.country` metadata variables.
- Aligned the remaining built-in `color.*` named constants with TradingView's
  official 17-color RGB table and expanded fixture-backed channel coverage.
- Aligned the direct `color.orange` named constant with TradingView's official
  `#FF9800` RGB value and added fixture-backed channel coverage.
- Added fixture-backed direct `strategy.oca.cancel`, `strategy.oca.none`, and
  `strategy.oca.reduce` string constants while keeping OCA order behavior
  unsupported.
- Added fixture-backed direct `strategy.short` string constant coverage while
  keeping short `strategy.entry` execution unsupported.
- Added fixture-backed direct `currency.*` string constants for the official
  currency-code set without enabling request currency conversion or strategy
  account currency.
- Added fixture-backed `barmerge.gaps_on` and `barmerge.lookahead_on` string
  constants while keeping non-default `request.security` merge behavior
  unsupported.
- Added fixture-backed explicit default `request.security` merge metadata
  support for `gaps=barmerge.gaps_off` and
  `lookahead=barmerge.lookahead_off`; non-default merge modes remain
  unsupported.
- Added fixture-backed `indicator(..., format=..., precision=...)`
  declaration metadata support plus the `format.inherit` constant.
- Added fixture-backed `scale.left`, `scale.right`, and `scale.none`
  declaration metadata constants for `indicator(..., scale=...)`.
- Added fixture-backed fixed-default `syminfo.main_tickerid` and
  `syminfo.mincontract` metadata variables.
- Added fixture-backed `matrix<float>` namespace-call support for
  `matrix.new<float>`, `matrix.get`, `matrix.set`, `matrix.copy`,
  `matrix.rows`, and `matrix.columns`, including assignment/reference aliasing
  and explicit independent copies; non-float templates, fill/reshape, method
  syntax, typed declarations, history, rollback, and matrix for-in remain
  unsupported.
- Added fixture-backed unsupported `map.*` collection namespace coverage until
  a dedicated key/value storage model is designed.
- Added fixture-backed unsupported `log.*` coverage for Pine Logs functions
  until a host-owned log output contract exists.
- Added a conformance metadata guardrail that rejects non-official `label.get_*`
  rows outside `label.get_x`, `label.get_y`, and `label.get_text`.
- Restored the official label getter boundary to `label.get_x`,
  `label.get_y`, and `label.get_text`; later label getters remain unsupported.
- Added a conformance metadata guardrail requiring unsupported sema evidence for partial rows with unsupported notes.
- Extended the array conformance metadata guardrail to require linefill and polyline fixture evidence when those unsupported array kinds are claimed.
- Added a conformance metadata guardrail requiring UDT fixture evidence for array UDT notes.
- Added fixture-backed `array.clear` coverage for rejected UDT arrays.
- Added fixture-backed `array.concat` coverage for same-UDT arrays while keeping
  mixed UDT arrays rejected.
- Added fixture-backed `array.slice` coverage for same-UDT arrays while keeping
  unsupported UDT array families outside the slice subset.
- Added fixture-backed `array.insert` coverage for same-UDT arrays while
  keeping mixed UDT insert values rejected.
- Added fixture-backed `array.remove` coverage for same-UDT arrays while
  keeping unsupported UDT array families outside the slice subset.
- Added fixture-backed `array.unshift` coverage for same-UDT arrays while
  keeping mixed UDT prepend values rejected.
- Added fixture-backed realtime rollback coverage for ordinary `var`
  same-local UDT arrays.
- Added fixture-backed `array.new<T>()` construction for same-local scalar-field
  UDT arrays while keeping unknown, nested-field, and mixed-initial UDT forms
  rejected.
- Added fixture-backed `array.sort` support for same-local scalar-field UDT
  arrays by compile-time `int`, `float`, or `string` `sort_field`.
- Added fixture-backed `array.join` coverage for rejected UDT arrays.
- Added fixture-backed `array.reverse` coverage for rejected UDT arrays.
- Added fixture-backed `array.sort_indices` coverage for rejected UDT arrays.
- Added fixture-backed `array.sort` coverage for rejected UDT arrays.
- Added fixture-backed `array.clear` coverage for rejected polyline arrays.
- Added fixture-backed `array.concat` coverage for rejected polyline arrays.
- Added fixture-backed `array.slice` coverage for rejected polyline arrays.
- Added fixture-backed `array.join` coverage for rejected polyline arrays.
- Added fixture-backed `array.reverse` coverage for rejected polyline arrays.
- Added fixture-backed `array.sort_indices` coverage for rejected polyline
  arrays.
- Added fixture-backed `array.sort` coverage for rejected polyline arrays.
- Added fixture-backed `array.stdev` coverage for rejected polyline arrays.
- Added fixture-backed `array.variance` coverage for rejected polyline arrays.
- Added fixture-backed `array.standardize` coverage for rejected polyline
  arrays.
- Added fixture-backed `array.covariance` coverage for rejected polyline
  arrays.
- Added fixture-backed `array.percentrank` coverage for rejected polyline
  arrays.
- Added fixture-backed `array.percentile_linear_interpolation` coverage for
  rejected polyline arrays.
- Added fixture-backed `array.percentile_nearest_rank` coverage for rejected
  polyline arrays.
- Added fixture-backed `array.mode` coverage for rejected polyline arrays.
- Added fixture-backed `array.median` coverage for rejected polyline arrays.
- Added fixture-backed `array.range` coverage for rejected polyline arrays.
- Added fixture-backed `array.avg` coverage for rejected polyline arrays.
- Added fixture-backed `array.sum` coverage for rejected polyline arrays.
- Added fixture-backed `array.max` coverage for rejected polyline arrays.
- Added fixture-backed `array.min` coverage for rejected polyline arrays.
- Added fixture-backed `array.abs` coverage for rejected polyline arrays.
- Added fixture-backed `array.binary_search_rightmost` coverage for rejected polyline arrays.
- Added fixture-backed `array.binary_search_leftmost` coverage for rejected polyline arrays.
- Added fixture-backed `array.binary_search` coverage for rejected polyline arrays.
- Added fixture-backed `array.lastindexof` coverage for rejected polyline arrays.
- Added fixture-backed `array.indexof` coverage for rejected polyline arrays.
- Added fixture-backed `array.some` coverage for rejected polyline arrays.
- Added fixture-backed `array.every` coverage for rejected polyline arrays.
- Added fixture-backed `array.includes` coverage for rejected polyline arrays.
- Added fixture-backed `array.copy` coverage for rejected polyline arrays.
- Added fixture-backed `array.last` coverage for rejected polyline arrays.
- Added fixture-backed `array.first` coverage for rejected polyline arrays.
- Added fixture-backed `array.fill` coverage for rejected polyline arrays.
- Added fixture-backed `array.unshift` coverage for rejected polyline arrays.
- Added fixture-backed `array.shift` coverage for rejected polyline arrays.
- Added fixture-backed `array.remove` coverage for rejected polyline arrays.
- Added fixture-backed `array.pop` coverage for rejected polyline arrays.
- Added fixture-backed `array.insert` coverage for rejected polyline arrays.
- Added fixture-backed `array.set` coverage for rejected polyline arrays.
- Added fixture-backed `array.get` coverage for rejected polyline arrays.
- Added fixture-backed `array.push` coverage for rejected polyline arrays.
- Added fixture-backed `array.size` coverage for rejected polyline arrays.
- Added fixture-backed `array.from` coverage for rejected polyline arrays.
- Added fixture-backed `array.new_*` summary coverage for rejected polyline
  array constructors.
- Linked the `array.*` summary row to explicit linefill constructor rejection
  coverage.
- Added fixture-backed `array.concat` coverage for rejected linefill arrays.
- Added fixture-backed `array.join` coverage for rejected linefill arrays.
- Added fixture-backed `array.some` coverage for rejected linefill arrays.
- Added fixture-backed `array.every` coverage for rejected linefill arrays.
- Added fixture-backed `array.binary_search_rightmost` coverage for rejected
  linefill arrays.
- Added fixture-backed `array.binary_search_leftmost` coverage for rejected
  linefill arrays.
- Added fixture-backed `array.binary_search` coverage for rejected linefill
  arrays.
- Added fixture-backed `array.abs` coverage for rejected linefill arrays.
- Added fixture-backed `array.min` coverage for rejected linefill arrays.
- Added fixture-backed `array.max` coverage for rejected linefill arrays.
- Added fixture-backed `array.sum` coverage for rejected linefill arrays.
- Added fixture-backed `array.avg` coverage for rejected linefill arrays.
- Added fixture-backed `array.range` coverage for rejected linefill arrays.
- Added fixture-backed `array.median` coverage for rejected linefill arrays.
- Added fixture-backed `array.mode` coverage for rejected linefill arrays.
- Added fixture-backed `array.percentile_nearest_rank` coverage for rejected
  linefill arrays.
- Added fixture-backed `array.percentile_linear_interpolation` coverage for
  rejected linefill arrays.
- Added fixture-backed `array.percentrank` coverage for rejected linefill arrays.
- Added fixture-backed `array.covariance` coverage for rejected linefill arrays.
- Added fixture-backed `array.standardize` coverage for rejected linefill
  arrays.
- Added fixture-backed `array.variance` coverage for rejected linefill arrays.
- Added fixture-backed `array.stdev` coverage for rejected linefill arrays.
- Added fixture-backed `array.sort_indices` coverage for rejected linefill
  arrays.
- Added fixture-backed `array.sort` coverage for rejected linefill arrays.
- Added fixture-backed `array.sort_indices` coverage for rejected table arrays.
- Added fixture-backed `array.sort_indices` coverage for rejected box arrays.
- Added fixture-backed `array.sort_indices` coverage for rejected line arrays.
- Added fixture-backed `array.sort_indices` coverage for rejected label arrays.
- Added fixture-backed `array.sort` coverage for rejected table arrays.
- Added fixture-backed `array.sort` coverage for rejected box arrays.
- Added fixture-backed `array.sort` coverage for rejected line arrays.
- Added fixture-backed `array.sort` coverage for rejected label arrays.
- Added fixture-backed `array.stdev` coverage for rejected table arrays.
- Added fixture-backed `array.stdev` coverage for rejected box arrays.
- Added fixture-backed `array.stdev` coverage for rejected line arrays.
- Added fixture-backed `array.stdev` coverage for rejected label arrays.
- Added fixture-backed `array.variance` coverage for rejected table arrays.
- Added fixture-backed `array.variance` coverage for rejected box arrays.
- Added fixture-backed `array.variance` coverage for rejected line arrays.
- Added fixture-backed `array.variance` coverage for rejected label arrays.
- Added fixture-backed `array.standardize` coverage for rejected table arrays.
- Added fixture-backed `array.standardize` coverage for rejected box arrays.
- Added fixture-backed `array.standardize` coverage for rejected line arrays.
- Added fixture-backed `array.standardize` coverage for rejected label arrays.
- Added fixture-backed `array.covariance` coverage for rejected table arrays.
- Added fixture-backed `array.covariance` coverage for rejected box arrays.
- Added fixture-backed `array.covariance` coverage for rejected line arrays.
- Added fixture-backed `array.covariance` coverage for rejected label arrays.
- Added fixture-backed `array.percentrank` coverage for rejected table arrays.
- Added fixture-backed `array.percentrank` coverage for rejected box arrays.
- Added fixture-backed `array.percentrank` coverage for rejected line arrays.
- Added fixture-backed `array.percentrank` coverage for rejected label arrays.
- Added fixture-backed `array.percentile_linear_interpolation` coverage for
  rejected table arrays.
- Added fixture-backed `array.percentile_linear_interpolation` coverage for
  rejected box arrays.
- Added fixture-backed `array.percentile_linear_interpolation` coverage for
  rejected line arrays.
- Added fixture-backed `array.percentile_linear_interpolation` coverage for
  rejected label arrays.
- Added fixture-backed `array.percentile_nearest_rank` coverage for rejected
  table arrays.
- Added fixture-backed `array.percentile_nearest_rank` coverage for rejected
  box arrays.
- Added fixture-backed `array.percentile_nearest_rank` coverage for rejected
  line arrays.
- Added fixture-backed `array.percentile_nearest_rank` coverage for rejected
  label arrays.
- Added fixture-backed `array.mode` coverage for rejected table arrays.
- Added fixture-backed `array.mode` coverage for rejected box arrays.
- Added fixture-backed `array.mode` coverage for rejected line arrays.
- Added fixture-backed `array.mode` coverage for rejected label arrays.
- Added fixture-backed `array.median` coverage for rejected table arrays.
- Added fixture-backed `array.median` coverage for rejected box arrays.
- Added fixture-backed `array.median` coverage for rejected line arrays.
- Added fixture-backed `array.median` coverage for rejected label arrays.
- Added fixture-backed `array.range` coverage for rejected table arrays.
- Added fixture-backed `array.range` coverage for rejected box arrays.
- Added fixture-backed `array.range` coverage for rejected line arrays.
- Added fixture-backed `array.range` coverage for rejected label arrays.
- Added fixture-backed `array.avg` coverage for rejected table arrays.
- Added fixture-backed `array.avg` coverage for rejected box arrays.
- Added fixture-backed `array.avg` coverage for rejected line arrays.
- Added fixture-backed `array.avg` coverage for rejected label arrays.
- Added fixture-backed `array.sum` coverage for rejected table arrays.
- Added fixture-backed `array.sum` coverage for rejected box arrays.
- Added fixture-backed `array.sum` coverage for rejected line arrays.
- Added fixture-backed `array.sum` coverage for rejected label arrays.
- Added fixture-backed `array.max` coverage for rejected table arrays.
- Added fixture-backed `array.max` coverage for rejected box arrays.
- Added fixture-backed `array.max` coverage for rejected line arrays.
- Added fixture-backed `array.max` coverage for rejected label arrays.
- Added fixture-backed `array.min` coverage for rejected table arrays.
- Added fixture-backed `array.min` coverage for rejected box arrays.
- Added fixture-backed `array.min` coverage for rejected line arrays.
- Added fixture-backed `array.min` coverage for rejected label arrays.
- Added fixture-backed `array.abs` coverage for rejected table arrays.
- Added fixture-backed `array.abs` coverage for rejected box arrays.
- Added fixture-backed `array.abs` coverage for rejected line arrays.
- Added fixture-backed `array.abs` coverage for rejected label arrays.
- Added fixture-backed `array.binary_search_rightmost` coverage for rejected
  table arrays.
- Added fixture-backed `array.binary_search_rightmost` coverage for rejected
  box arrays.
- Added fixture-backed `array.binary_search_rightmost` coverage for rejected
  line arrays.
- Added fixture-backed `array.binary_search_rightmost` coverage for rejected
  label arrays.
- Added fixture-backed `array.binary_search_leftmost` coverage for rejected
  table arrays.
- Added fixture-backed `array.binary_search_leftmost` coverage for rejected
  box arrays.
- Added fixture-backed `array.binary_search_leftmost` coverage for rejected
  line arrays.
- Added fixture-backed `array.binary_search_leftmost` coverage for rejected
  label arrays.
- Added fixture-backed `array.binary_search` coverage for rejected table arrays.
- Added fixture-backed `array.binary_search` coverage for rejected box arrays.
- Added fixture-backed `array.binary_search` coverage for rejected line arrays.
- Added fixture-backed `array.binary_search` coverage for rejected label arrays.
- Added fixture-backed `array.join` coverage for rejected table arrays.
- Added fixture-backed `array.join` coverage for rejected box arrays.
- Added fixture-backed `array.join` coverage for rejected line arrays.
- Added fixture-backed `array.binary_search_rightmost` coverage for rejected
  color arrays.
- Added fixture-backed `array.binary_search_leftmost` coverage for rejected
  color arrays.
- Added fixture-backed `array.binary_search` coverage for rejected color arrays.
- Added fixture-backed `array.sort_indices` coverage for rejected color arrays.
- Added fixture-backed `array.sort` coverage for rejected color arrays.
- Added fixture-backed `array.stdev` coverage for rejected color arrays.
- Added fixture-backed `array.variance` coverage for rejected color arrays.
- Added fixture-backed `array.standardize` coverage for rejected color arrays.
- Added fixture-backed `array.covariance` coverage for rejected color arrays.
- Added fixture-backed `array.percentrank` coverage for rejected color arrays.
- Added fixture-backed `array.percentile_linear_interpolation` coverage for
  rejected color arrays.
- Added fixture-backed `array.percentile_nearest_rank` coverage for rejected
  color arrays.
- Added fixture-backed `array.mode` coverage for rejected color arrays.
- Added fixture-backed `array.median` coverage for rejected color arrays.
- Added fixture-backed `array.range` coverage for rejected color arrays.
- Added fixture-backed `array.avg` coverage for rejected color arrays.
- Added fixture-backed `array.sum` coverage for rejected color arrays.
- Added fixture-backed `array.max` coverage for rejected color arrays.
- Added fixture-backed `array.min` coverage for rejected color arrays.
- Added fixture-backed `array.abs` coverage for rejected color arrays.
- Added fixture-backed `array.avg` coverage for rejected string arrays.
- Added fixture-backed `array.stdev` coverage for rejected string arrays.
- Added fixture-backed `array.variance` coverage for rejected string arrays.
- Added fixture-backed `array.standardize` coverage for rejected string arrays.
- Added fixture-backed `array.covariance` coverage for rejected string arrays.
- Added fixture-backed `array.percentrank` coverage for rejected string arrays.
- Added fixture-backed `array.percentile_linear_interpolation` coverage for
  rejected string arrays.
- Added fixture-backed `array.percentile_nearest_rank` coverage for rejected
  string arrays.
- Added fixture-backed `array.mode` coverage for rejected string arrays.
- Added fixture-backed `array.median` coverage for rejected string arrays.
- Added fixture-backed `array.range` coverage for rejected string arrays.
- Added fixture-backed `array.sum` coverage for rejected string arrays.
- Added fixture-backed `array.max` coverage for rejected string arrays.
- Added fixture-backed `array.min` coverage for rejected string arrays.
- Added fixture-backed `array.abs` coverage for rejected string arrays.
- Added fixture-backed `array.binary_search_rightmost` coverage for rejected string arrays.
- Added fixture-backed `array.binary_search_leftmost` coverage for rejected string arrays.
- Added fixture-backed `array.binary_search` coverage for rejected string arrays.
- Added fixture-backed `array.some` coverage for rejected table arrays.
- Added fixture-backed `array.every` coverage for rejected table arrays.
- Added fixture-backed `array.some` coverage for rejected box arrays.
- Added fixture-backed `array.every` coverage for rejected box arrays.
- Added fixture-backed `array.some` coverage for rejected line arrays.
- Added fixture-backed `array.every` coverage for rejected line arrays.
- Added fixture-backed `array.some` coverage for rejected label arrays.
- Added fixture-backed `array.every` coverage for rejected label arrays.
- Added fixture-backed `array.some` coverage for rejected color arrays.
- Added fixture-backed `array.every` coverage for rejected color arrays.
- Added fixture-backed `alertcondition` coverage for rejected dynamic messages.
- Added fixture-backed `alertcondition` coverage for rejected dynamic titles.
- Expanded unsupported drawing-method conformance evidence to cite dedicated
  label and table method fixtures.
- Added fixture-backed function side-effect coverage for rejected
  `strategy.cancel_all` calls inside user-defined functions.
- Added fixture-backed function side-effect coverage for rejected
  `strategy.cancel` calls inside user-defined functions.
- Added fixture-backed function side-effect coverage for rejected
  `strategy.close_all` calls inside user-defined functions.
- Added fixture-backed function side-effect coverage for rejected
  `strategy.close` calls inside user-defined functions.
- Added fixture-backed alert placeholder coverage for rejected
  `alertcondition` plot placeholders.
- Added fixture-backed alert placeholder coverage for rejected unknown
  `alertcondition` message placeholders.
- Added fixture-backed alert placeholder coverage for rejected
  `alertcondition` title placeholders.
- Added fixture-backed function side-effect coverage for rejected declaration
  calls inside user-defined functions.
- Added fixture-backed function side-effect coverage for rejected `input.*` calls
  inside user-defined functions.
- Added dedicated fixture-backed `request.*` boundary coverage for unsupported
  request families beyond `request.security`.
- Trimmed the generic unsupported drawing-method fixture to label/line/box/table
  method coverage now that `polyline.*` has dedicated evidence.
- Added dedicated fixture-backed `polyline.*` boundary coverage for unsupported
  point-list drawing construction.
- Added fixture-backed `table.set_bgcolor` boundary coverage for unsupported
  table layout methods.
- Added fixture-backed `table.set_frame_color` boundary coverage for unsupported
  table layout methods.
- Added fixture-backed `table.set_frame_width` boundary coverage for unsupported
  table layout methods.
- Added fixture-backed `table.set_border_color` boundary coverage for unsupported
  table layout methods.
- Added fixture-backed `table.set_border_width` boundary coverage for unsupported
  table layout methods.
- Added fixture-backed `table.delete` boundary coverage for unsupported table
  layout methods.
- Added fixture-backed `table.clear` boundary coverage for unsupported table
  layout and richer styling methods.
- Added fixture-backed `table.cell_set_text` boundary coverage for unsupported
  richer table cell methods.
- Added fixture-backed `table.cell_set_bgcolor` boundary coverage for
  unsupported richer table cell methods.
- Added fixture-backed `table.cell_set_text_color` boundary coverage for
  unsupported richer table cell methods.
- Added fixture-backed `table.cell_set_width` boundary coverage for unsupported
  richer table cell layout methods.
- Added fixture-backed `table.cell_set_height` boundary coverage for unsupported
  richer table cell layout methods.
- Added fixture-backed `table.cell_set_text_size` boundary coverage for
  unsupported richer table cell layout methods.
- Added fixture-backed `table.cell_set_text_halign` boundary coverage for
  unsupported richer table cell layout methods.
- Added initial `linefill.new` support with runtime-owned linefill output
  snapshots, including same-pair replacement semantics.
- Added `linefill.set_color` support with sparse color mutation snapshots for
  existing linefill ids.
- Added explicit `table.new` fixture coverage for all nine official
  `position.*` table anchors.
- Added fixture-backed `table.cell_set_text_valign` boundary coverage for
  unsupported richer table cell layout methods.
- Corrected the `ta.vwap` conformance status to `partial` because
  session-derived anchoring remains unsupported.
- Added fixture-backed `switch` boundary coverage for unsupported
  statement-block arms.
- Added fixture-backed `alert()` boundary coverage for unsupported Pine-source
  placeholder interpolation.
- Clarified the `ta.vwap` conformance notes so the cumulative fixture-backed
  subset is not described as a semantic rejection case.
- Refined the `ta.vwap` conformance wording to describe the cumulative default
  anchoring subset without treating session resets as a rejected call shape.
- Added fixture-backed `table.set_position` boundary coverage for unsupported
  table position values.
- Added fixture-backed `table.cell` boundary coverage for unsupported table
  cell text-formatting variants.
- Added fixture-backed `table.new` boundary coverage for unsupported table
  position/layout variants.
- Added fixture-backed drawing object method syntax boundary coverage for
  unsupported drawing methods, chart.point overloads, and xloc/time variants.
- Added fixture-backed `box.get_right` boundary coverage for unsupported other
  box methods.
- Added fixture-backed `box.get_left` boundary coverage for unsupported other
  box methods.
- Added fixture-backed `box.get_bottom` boundary coverage for unsupported other
  box methods.
- Added fixture-backed `box.get_top` boundary coverage for unsupported other
  box methods.
- Added fixture-backed `box.delete` boundary coverage for unsupported later box
  methods.
- Added fixture-backed `box.set_text_formatting` boundary coverage for richer
  unsupported box text layout methods.
- Added fixture-backed `box.set_text_font_family` boundary coverage for richer
  unsupported box text layout methods.
- Added fixture-backed `box.set_text_wrap` boundary coverage for unsupported
  later box font methods.
- Added fixture-backed `box.set_text_valign` boundary coverage for unsupported
  later box text wrap/font methods.
- Added fixture-backed `box.set_text_halign` boundary coverage for unsupported
  later box text vertical alignment/wrap/font methods.
- Added fixture-backed `box.set_text_size` boundary coverage for unsupported
  later box text alignment/wrap/font methods.
- Added fixture-backed `box.set_text_color` boundary coverage for unsupported
  later box text size/style/layout methods.
- Added fixture-backed `box.set_text` boundary coverage for unsupported later
  box text style/layout methods.
- Added fixture-backed `box.set_xloc` boundary coverage for unsupported
  chart-point box methods.
- Added fixture-backed `box.set_extend` boundary coverage for unsupported later
  box methods.
- Added fixture-backed `box.set_border_style` boundary coverage for unsupported
  later box methods.
- Added fixture-backed `box.set_border_width` boundary coverage for unsupported
  later box methods.
- Added fixture-backed `box.set_border_color` boundary coverage for unsupported
  later box methods.
- Added fixture-backed `box.set_bgcolor` boundary coverage for unsupported
  later box methods.
- Added fixture-backed `box.set_rightbottom` boundary coverage for unsupported
  later box methods.
- Added fixture-backed `box.set_lefttop` boundary coverage for unsupported
  later box methods.
- Added fixture-backed `box.set_bottom` boundary coverage for unsupported later
  box methods.
- Added fixture-backed `box.set_right` boundary coverage for unsupported later
  box methods.
- Added fixture-backed `box.set_top` boundary coverage for unsupported later
  box methods.
- Added fixture-backed `box.set_left` boundary coverage for unsupported later
  box methods.
- Added fixture-backed `box.new` boundary coverage for unsupported
  `xloc.bar_time` and invalid text-formatting modes.
- Added fixture-backed `line.get_y2` boundary coverage for unsupported rich
  line methods.
- Added fixture-backed `line.get_x2` boundary coverage for unsupported rich
  line methods.
- Added fixture-backed `line.get_y1` boundary coverage for unsupported rich
  line methods.
- Added fixture-backed `line.get_x1` boundary coverage for unsupported rich
  line methods.
- Added fixture-backed `line.get_price` boundary coverage for time-coordinate
  lines.
- Added fixture-backed `line.delete` boundary coverage for unsupported later
  line methods.
- Added fixture-backed `line.set_extend` boundary coverage for unsupported
  later line methods.
- Added fixture-backed `line.set_style` boundary coverage for unsupported later
  line methods.
- Added fixture-backed `line.set_width` boundary coverage for unsupported later
  line methods.
- Added fixture-backed `line.set_color` boundary coverage for unsupported later
  line methods.
- Added fixture-backed `line.set_xloc` boundary coverage for unsupported
  chart-point line methods.
- Added fixture-backed `line.set_xy2` boundary coverage for unsupported later
  line methods.
- Added fixture-backed `line.set_y2` boundary coverage for unsupported later
  line methods.
- Added fixture-backed `line.set_x2` boundary coverage for unsupported later
  line methods.
- Added fixture-backed `line.set_xy1` boundary coverage for unsupported later
  line methods.
- Added fixture-backed `line.set_y1` boundary coverage for unsupported later
  line methods.
- Added fixture-backed `line.set_x1` boundary coverage for unsupported later
  line methods.
- Added fixture-backed `line.new` semantic coverage for unsupported mode
  options.
- Added fixture-backed `label.get_text` boundary coverage for unsupported later
  label getters.
- Added fixture-backed `label.get_y` boundary coverage for unsupported later
  label getters.
- Added fixture-backed `label.get_x` boundary coverage for unsupported later
  label getters.
- Added fixture-backed `label.delete` boundary coverage for unsupported later
  label methods.
- Added fixture-backed `label.set_text_formatting` boundary coverage for richer
  unsupported label text layout methods.
- Added fixture-backed `label.set_text_font_family` boundary coverage for richer
  unsupported label text layout methods.
- Added fixture-backed `label.set_textalign` boundary coverage for unsupported
  later label text layout methods.
- Added fixture-backed `label.set_tooltip` boundary coverage for unsupported
  later label methods.
- Added fixture-backed `label.set_size` boundary coverage for unsupported
  later label methods.
- Added fixture-backed `label.set_style` boundary coverage for unsupported
  later label methods.
- Added fixture-backed `label.set_textcolor` boundary coverage for unsupported
  later label methods.
- Added fixture-backed `label.set_color` boundary coverage for unsupported
  later label methods.
- Added fixture-backed `label.set_text` boundary coverage for unsupported later
  label methods.
- Added fixture-backed `label.set_xy` boundary coverage for unsupported later
  label methods.
- Added fixture-backed `label.set_y` boundary coverage for unsupported later
  label methods.
- Added fixture-backed `label.set_x` boundary coverage for unsupported later
  label methods.
- Added fixture-backed `label.new` semantic coverage for unsupported mode
  options.
- Added fixture-backed `array.new_table` boundary coverage for unsupported
  linefill array constructors.
- Added fixture-backed `array.new_box` boundary coverage for unsupported
  linefill array constructors.
- Added fixture-backed `array.new_label` boundary coverage for unsupported
  linefill array constructors.
- Added fixture-backed `array.new_line` boundary coverage for unsupported
  linefill array constructors.
- Added fixture-backed `array.new_color` semantic coverage for incompatible
  initial values.
- Added fixture-backed `array.new_string` semantic coverage for incompatible
  initial values.
- Added fixture-backed `array.new_bool` semantic coverage for incompatible
  initial values.
- Added fixture-backed `array.new_int` semantic coverage for incompatible
  initial values.
- Added fixture-backed `array.new_float` semantic coverage for incompatible
  initial values.
- Added fixture-backed `array.from` semantic coverage for unsupported linefill
  arrays.
- Added fixture-backed `array.size` semantic coverage for unsupported linefill
  arrays.
- Added fixture-backed `array.push` semantic coverage for unsupported linefill
  arrays.
- Added fixture-backed `array.get` semantic coverage for unsupported linefill
  arrays.
- Added fixture-backed `array.set` semantic coverage for unsupported linefill
  arrays.
- Added fixture-backed `array.insert` semantic coverage for unsupported
  linefill arrays.
- Added fixture-backed `array.fill` semantic coverage for unsupported linefill
  arrays.
- Added fixture-backed `array.unshift` semantic coverage for unsupported
  linefill arrays.
- Added fixture-backed `array.remove` semantic coverage for unsupported linefill
  arrays.
- Added fixture-backed `array.pop` semantic coverage for unsupported linefill
  arrays.
- Added fixture-backed `array.shift` semantic coverage for unsupported linefill
  arrays.
- Added fixture-backed `array.last` semantic coverage for unsupported linefill
  arrays.
- Added fixture-backed `array.first` semantic coverage for unsupported
  linefill arrays.
- Added fixture-backed `array.copy` semantic coverage for unsupported linefill
  arrays.
- Added fixture-backed `array.lastindexof` semantic coverage for unsupported
  linefill arrays.
- Added fixture-backed `array.indexof` semantic coverage for unsupported
  linefill arrays.
- Added fixture-backed `array.includes` semantic coverage for unsupported
  linefill arrays.
- Added fixture-backed `array.some` semantic coverage for unsupported string
  arrays.
- Added fixture-backed `array.every` semantic coverage for unsupported string
  arrays.
- Added fixture-backed `array.binary_search_rightmost` semantic coverage for
  unsupported bool arrays.
- Added fixture-backed `array.binary_search_leftmost` semantic coverage for
  unsupported bool arrays.
- Added fixture-backed `array.binary_search` semantic coverage for unsupported
  bool arrays.
- Added fixture-backed `array.abs` semantic coverage for unsupported bool
  arrays.
- Added fixture-backed `array.min` semantic coverage for unsupported bool
  arrays.
- Added fixture-backed `array.max` semantic coverage for unsupported bool
  arrays.
- Added fixture-backed `array.sum` semantic coverage for unsupported bool
  arrays.
- Added fixture-backed `array.avg` semantic coverage for unsupported bool
  arrays.
- Added fixture-backed `array.range` semantic coverage for unsupported bool
  arrays.
- Added fixture-backed `array.median` semantic coverage for unsupported bool
  arrays.
- Added fixture-backed `array.mode` semantic coverage for unsupported bool
  arrays.
- Added fixture-backed `array.percentile_nearest_rank` semantic coverage for
  unsupported bool arrays.
- Added fixture-backed `array.percentile_linear_interpolation` semantic
  coverage for unsupported bool arrays.
- Added fixture-backed `array.percentrank` semantic coverage for unsupported
  bool arrays.
- Added fixture-backed `array.covariance` semantic coverage for unsupported
  bool arrays.
- Added fixture-backed `array.standardize` semantic coverage for unsupported
  bool arrays.
- Added fixture-backed `array.variance` semantic coverage for unsupported bool
  arrays.
- Added fixture-backed `array.stdev` semantic coverage for unsupported bool
  arrays.
- Added fixture-backed `array.sort_indices` semantic coverage for unsupported
  bool arrays.
- Added fixture-backed `array.sort` semantic coverage for unsupported bool
  arrays.
- Added fixture-backed `array.slice` semantic coverage for unsupported linefill
  arrays.
- Added fixture-backed `array.join` semantic coverage for unsupported label
  arrays.
- Added fixture-backed `array.reverse` semantic coverage for unsupported
  linefill arrays.
- Added fixture-backed `array.clear` semantic coverage for unsupported linefill
  arrays.
- Added fixture-backed `array.clear` coverage for clearing copied table arrays
  without deleting the referenced table id and reusing the cleared array.
- Added fixture-backed `array.clear` coverage for clearing copied box arrays
  without deleting the referenced box id and reusing the cleared array.
- Added fixture-backed `array.clear` coverage for clearing copied line arrays
  without deleting the referenced line id and reusing the cleared array.
- Added fixture-backed `array.clear` coverage for clearing copied label arrays
  without deleting the referenced label id and reusing the cleared array.
- Added fixture-backed `array.concat` runtime coverage for the 100,000 element
  result limit.
- Added fixture-backed `array.concat` semantic coverage for mismatched source
  array kinds.
- Added fixture-backed `array.concat` coverage for bool source-array value
  non-mutation during append.
- Added fixture-backed `array.concat` coverage for float source-array value
  non-mutation during append.
- Added fixture-backed `array.concat` coverage for color source-array value
  non-mutation during append.
- Added fixture-backed `array.concat` coverage for string source-array value
  non-mutation during append.
- Added fixture-backed `array.concat` coverage for int source-array value
  non-mutation during append.
- Added fixture-backed `array.concat` coverage for table source-array
  non-mutation during append.
- Added fixture-backed `array.concat` coverage for box source-array
  non-mutation during append.
- Added fixture-backed `array.concat` coverage for line source-array
  non-mutation during append.
- Added fixture-backed `array.concat` coverage for label source-array
  non-mutation during append.
- Added fixture-backed `array.concat` coverage for appending into empty table
  target arrays.
- Added fixture-backed `array.concat` coverage for appending into empty box
  target arrays.
- Added fixture-backed `array.concat` coverage for appending into empty line
  target arrays.
- Added fixture-backed `array.concat` coverage for appending into empty label
  target arrays.
- Added fixture-backed `array.concat` coverage for empty table source arrays.
- Added fixture-backed `array.concat` coverage for empty box source arrays.
- Added fixture-backed `array.concat` coverage for empty line source arrays.
- Added fixture-backed `array.concat` coverage for empty label source arrays.
- Added fixture-backed `array.concat` coverage for appending into empty color
  target arrays.
- Added fixture-backed `array.concat` coverage for appending into empty bool
  target arrays.
- Added fixture-backed `array.concat` coverage for appending into empty float
  target arrays.
- Added fixture-backed `array.concat` coverage for appending into empty int
  target arrays.
- Added fixture-backed `array.concat` coverage for empty color source arrays.
- Added fixture-backed `array.concat` coverage for empty int source arrays.
- Added fixture-backed `array.concat` coverage for empty bool source arrays.
- Added fixture-backed `array.concat` coverage for empty float source arrays.
- Added fixture-backed `array.join` coverage for empty color arrays.
- Added fixture-backed `array.join` coverage for empty bool arrays.
- Added fixture-backed `array.join` coverage for empty float arrays.
- Added fixture-backed `array.join` coverage for empty int arrays.
- Added fixture-backed `array.reverse` coverage for empty color arrays.
- Added fixture-backed array ordering coverage for empty int arrays.
- Added fixture-backed `array.reverse` coverage for empty bool arrays.
- Added fixture-backed `array.reverse` coverage for empty string arrays.
- Added fixture-backed `array.sort` and `array.sort_indices` coverage for empty
  string arrays.
- Added fixture-backed `array.binary_search`, `array.binary_search_leftmost`,
  and `array.binary_search_rightmost` coverage for empty float arrays.
- Added fixture-backed `array.every` and `array.some` coverage for empty int
  and float arrays.
- Added fixture-backed `array.includes` coverage for bool and string not-found
  searches returning `false`.
- Added fixture-backed `array.indexof` and `array.lastindexof` coverage for
  bool-array repeated-hit and not-found searches.
- Added fixture-backed `array.indexof` and `array.lastindexof` coverage for
  string-array not-found searches returning `-1`.
- Added fixture-backed `array.binary_search` coverage for exact empty-array
  searches returning `-1`.
- Added fixture-backed `array.insert` coverage for out-of-range scalar inserts
  leaving existing arrays unchanged.
- Added fixture-backed `array.remove` coverage for out-of-range scalar removals
  returning `na` without mutating the array.
- Added fixture-backed `array.pop` coverage for empty scalar arrays returning
  `na` without changing array size.
- Added fixture-backed `array.shift` coverage for preserving remaining element
  order after removing the first element.
- Added fixture-backed `array.concat` coverage for appending a non-empty source
  array into an empty target array.
- Added fixture-backed `array.join` coverage for string arrays containing empty
  elements.
- Added fixture-backed `str.tostring(false)` coverage for bool stringification.
- Added fixture-backed `str.split` coverage for missing separators returning a
  single source-string element.
- Added fixture-backed `str.replace_all` coverage for no-match inputs leaving
  the source string unchanged.
- Added fixture-backed `str.substring` coverage for equal begin/end indexes
  returning an empty string.
- Added fixture-backed `str.contains`, `str.startswith`, and `str.endswith`
  coverage for ordinary no-match cases returning `false`.
- Added fixture-backed `str.length` coverage for empty strings returning 0.
- Added fixture-backed `str.format` coverage for bool placeholder arguments.
- Added fixture-backed `str.format` coverage for `na` placeholder arguments
  rendering as `NaN`.
- Added fixture-backed `str.replace` coverage for out-of-range occurrence
  values leaving the source string unchanged.
- Added fixture-backed `str.replace` coverage for `na` occurrence values
  defaulting to the first occurrence.
- Added fixture-backed `str.replace` coverage for negative occurrence values
  leaving the source string unchanged.
- Added fixture-backed `str.repeat` coverage for omitted separator arguments
  defaulting to an empty string.
- Added fixture-backed `str.tonumber` coverage for empty and whitespace-padded
  invalid inputs returning `na`.
- Added fixture-backed `str.substring` coverage for `na` source arguments.
- Added fixture-backed `str.trim` coverage for `na` input arguments.
- Added fixture-backed `str.upper` and `str.lower` coverage for `na` input
  arguments.
- Added fixture-backed `str.tostring` coverage for `na` format arguments
  defaulting to the standard numeric format.
- Added fixture-backed `str.format_time` coverage for `na` format and timezone
  arguments defaulting to the UTC subset.
- Added fixture-backed `str.format` coverage for `na` formatString arguments.
- Added fixture-backed `str.match` coverage for `na` regex arguments.
- Added fixture-backed `str.split` coverage for `na` separator arguments.
- Added fixture-backed `str.repeat` coverage for `na` source and separator
  arguments.
- Added fixture-backed `str.replace` and `str.replace_all` coverage for `na`
  target and replacement arguments.
- Added fixture-backed `str.pos` coverage for `na` source arguments.
- Added fixture-backed `str.contains`, `str.startswith`, and `str.endswith`
  coverage for `na` pattern arguments.
- Added fixture-backed `str.pos` coverage for Unicode scalar result indexes.
- Added fixture-backed `str.substring` coverage for Unicode scalar indexes.
- Added fixture-backed `str.length` coverage for Unicode scalar counting.
- Added fixture-backed `str.split` coverage for empty-separator Unicode scalar
  splitting.
- Added fixture-backed `str.substring` coverage for `na` end positions
  defaulting to the source string length.
- Preserved exact RGB color values for fully opaque `color.new` and
  `color.rgb` results.
- Preserved exact endpoint colors for clamped and equal-range
  `color.from_gradient` results.
- Added fixture-backed `color.from_gradient` lower-endpoint clamping and
  equal-range top-color coverage.
- Added fixture-backed `color.rgb` channel rounding/clamping and
  `color.new`/`color.rgb` transparency clamping coverage.
- Added zero-offset UTC/GMT timezone aliases for UTC-only time component
  helpers and `str.format_time`.
- Added `str.tonumber` support for finite ASCII scientific-notation strings.
- Added runtime fixture coverage for pure user-defined methods that return
  local UDT aliases from final `if`/`else` or `for` bodies.
- Added fixture-backed `strategy.close` no-op coverage for while-flat,
  wrong-entry-id, and repeated close calls without changing public strategy JSON.
- Added script-visible strategy trade comment helpers:
  `strategy.closedtrades.entry_comment`,
  `strategy.closedtrades.exit_comment`, and
  `strategy.opentrades.entry_comment` for fixture-backed commented trades
  without expanding public strategy JSON.
- Added `table.cell_set_text_wrap()` support for populated table cells. Runtime
  output is now `schemaVersion: 5`, and table cell snapshots include
  host-neutral `textWrap`.
- Added support for dynamic string-compatible `alert()` messages while keeping
  `freq` limited to the existing const-string frequency subset and keeping
  Pine-source `alert()` placeholder interpolation unsupported.
- Added fixture-backed `alertcondition` message interpolation for
  `{{open}}`, `{{high}}`, `{{low}}`, `{{close}}`, `{{volume}}`,
  `{{ticker}}`, `{{interval}}`, `{{exchange}}`, and UTC-formatted
  triggering-bar `{{time}}` while keeping other Pine-source alert placeholders
  unsupported.
- Documented the current fixture-backed `request.security` tuple literal
  coverage boundary and host evidence in `docs/REQUEST_TUPLE_LITERAL_AUDIT.md`.
- Added provider-backed `request.security` tuple literal fixture coverage for
  same-timeframe `math.sum` and `math.round_to_mintick` scalar elements.
- Added provider-backed `request.security` tuple literal fixture coverage for
  same-timeframe source-less `ta.highestbars` and `ta.lowestbars` scalar
  elements.
- Added provider-backed `request.security` tuple literal fixture coverage for
  same-timeframe source-less `ta.highest` and `ta.lowest` scalar elements.
- Added provider-backed `request.security` tuple literal fixture coverage for
  same-timeframe `ta.bbw` scalar elements.
- Added provider-backed `request.security` tuple literal fixture coverage for
  same-timeframe `ta.ema` and `ta.rsi` scalar elements.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` tuple literal source-less `ta.highestbars` and
  `ta.lowestbars` scalar elements while preserving default confirmation
  alignment.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` tuple literal source-less `ta.highest` and `ta.lowest`
  scalar elements while preserving default confirmation alignment.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` tuple literal `ta.bbw` scalar elements while preserving
  default confirmation alignment.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` tuple literal `ta.ema` and `ta.rsi` scalar elements while
  preserving default confirmation alignment.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` tuple literal `ta.range` and `ta.dev` scalar elements
  while preserving default confirmation alignment.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` tuple literal `ta.mom` and `ta.roc` scalar elements while
  preserving default confirmation alignment.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` tuple literal `ta.highest` and `ta.lowest` scalar elements
  while preserving default confirmation alignment.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` tuple literal `ta.tr` and `ta.atr` scalar elements while
  preserving default confirmation alignment.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` tuple literal rolling `ta.kcw` and `ta.vwap` scalar
  elements while preserving default confirmation alignment.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` tuple literal rolling `ta.cog` and `ta.bop` scalar
  elements while preserving default confirmation alignment.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` tuple literal rolling `ta.sar` and `ta.cci` scalar
  elements while preserving default confirmation alignment.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` tuple literal rolling `ta.stoch` and `ta.wpr` scalar
  elements while preserving default confirmation alignment.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` tuple literal rolling `ta.cmo` and `ta.mfi` scalar
  elements while preserving default confirmation alignment.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` tuple literal rolling `ta.tema` and `ta.tsi` scalar
  elements while preserving default confirmation alignment.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` tuple literal rolling `ta.rma` and `ta.dema` scalar
  elements while preserving default confirmation alignment.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` tuple literal rolling `ta.alma` and `ta.linreg` scalar
  elements while preserving default confirmation alignment.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` tuple literal rolling `ta.swma` and `ta.hma` scalar
  elements while preserving default confirmation alignment.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` tuple literal `ta.wvad` and `ta.ao` scalar elements
  while preserving default confirmation alignment.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` tuple literal `ta.pvi` and `ta.pvt` scalar variable
  elements while preserving default confirmation alignment.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` tuple literal `ta.nvi` and `ta.obv` scalar variable
  elements while preserving default confirmation alignment.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` tuple literal `ta.accdist` and `ta.iii` scalar variable
  elements while preserving default confirmation alignment.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` tuple literal rolling `ta.max` and `ta.min` scalar
  elements while preserving default confirmation alignment.
- Added provider-backed `request.security` tuple literal fixture coverage for
  `ta.wvad` and `ta.ao` scalar elements.
- Added provider-backed `request.security` tuple literal fixture coverage for
  `ta.pvi` and `ta.pvt` scalar variable elements.
- Added provider-backed `request.security` tuple literal fixture coverage for
  `ta.nvi` and `ta.obv` scalar variable elements.
- Added provider-backed `request.security` tuple literal fixture coverage for
  `ta.accdist` and `ta.iii` scalar variable elements.
- Added provider-backed `request.security` tuple literal fixture coverage for
  rolling `ta.kcw` and `ta.vwap` scalar elements.
- Added provider-backed `request.security` tuple literal fixture coverage for
  rolling `ta.max` and `ta.min` scalar elements.
- Added provider-backed `request.security` tuple literal fixture coverage for
  rolling `ta.cog` and `ta.bop` scalar elements.
- Added provider-backed `request.security` tuple literal fixture coverage for
  rolling `ta.sar` and `ta.cci` scalar elements.
- Added provider-backed `request.security` tuple literal fixture coverage for
  rolling `ta.stoch` and `ta.wpr` scalar elements.
- Added provider-backed `request.security` tuple literal fixture coverage for
  rolling `ta.cmo` and `ta.mfi` scalar elements.
- Added provider-backed `request.security` tuple literal fixture coverage for
  rolling `ta.tema` and `ta.tsi` scalar elements.
- Added provider-backed `request.security` tuple literal fixture coverage for
  rolling `ta.rma` and `ta.dema` scalar elements.
- Added provider-backed `request.security` tuple literal fixture coverage for
  rolling `ta.alma` and `ta.linreg` scalar elements.
- Added provider-backed `request.security` tuple literal fixture coverage for
  rolling `ta.swma` and `ta.hma` scalar elements.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` tuple literal rolling `ta.wma` and `ta.vwma` scalar
  elements while preserving default confirmation alignment.
- Added provider-backed `request.security` tuple literal fixture coverage for
  rolling `ta.wma` and `ta.vwma` scalar elements.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` tuple literal rolling `ta.stdev` and `ta.variance`
  scalar elements while preserving default confirmation alignment.
- Added provider-backed `request.security` tuple literal fixture coverage for
  rolling `ta.stdev` and `ta.variance` scalar elements.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` tuple literal rolling `ta.percentrank` scalar elements
  while preserving default confirmation alignment.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` tuple literal stateless `math.floor`, `math.ceil`, and
  `math.round` scalar elements while preserving default confirmation
  alignment.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` tuple literal root/log `math.sqrt`, `math.cbrt`, and
  `math.log10` scalar elements while preserving default confirmation
  alignment.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` tuple literal trig `math.sin`, `math.cos`, and
  `math.tan` scalar elements while preserving default confirmation
  alignment.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` tuple literal power/log `math.pow`, `math.hypot`, and
  `math.log` scalar elements while preserving default confirmation
  alignment.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` tuple literal inverse-trig/exponential `math.exp`,
  `math.acos`, `math.asin`, and `math.atan` scalar elements while preserving
  default confirmation alignment.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` tuple literal scalar/angle `math.avg`, `math.trunc`,
  `math.sign`, `math.todegrees`, and `math.toradians` scalar elements while
  preserving default confirmation alignment.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` tuple literal rolling `ta.percentile_nearest_rank` and
  `ta.percentile_linear_interpolation` scalar elements while preserving
  default confirmation alignment.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` tuple literal rolling `ta.median` and `ta.mode` scalar
  elements while preserving default confirmation alignment.
- Added provider-backed `request.security` tuple literal fixture coverage for
  rolling `ta.percentrank` scalar elements.
- Added provider-backed `request.security` tuple literal fixture coverage for
  rolling `ta.percentile_nearest_rank` and
  `ta.percentile_linear_interpolation` scalar elements.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` tuple literal rolling `math.sum` and fixed-mintick
  `math.round_to_mintick` scalar elements while preserving default
  confirmation alignment.
- Added provider-backed `request.security` tuple literal fixture coverage for
  rolling `ta.median` and `ta.mode` scalar elements.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` tuple literal rolling `ta.correlation` and
  `ta.covariance` scalar elements while preserving default confirmation
  alignment.
- Added provider-backed `request.security` tuple literal fixture coverage for
  rolling `ta.correlation` and `ta.covariance` scalar elements.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` tuple literal `ta.pivothigh` and `ta.pivotlow` scalar
  elements while preserving default confirmation alignment.
- Added provider-backed `request.security` tuple literal fixture coverage for
  `ta.pivothigh` and `ta.pivotlow` scalar elements.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` tuple literal `ta.highestbars` and `ta.lowestbars`
  scalar elements while preserving default confirmation alignment.
- Added provider-backed `request.security` tuple literal fixture coverage for
  `ta.highestbars` and `ta.lowestbars` scalar elements.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` tuple literal stateful `ta.barssince` and
  `ta.valuewhen` scalar elements while preserving default confirmation
  alignment.
- Added provider-backed `request.security` tuple literal fixture coverage for
  stateful `ta.barssince` and `ta.valuewhen` scalar elements.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` tuple literal boolean `ta.rising` and `ta.falling`
  scalar elements while preserving default confirmation alignment.
- Added provider-backed `request.security` tuple literal fixture coverage for
  boolean `ta.rising` and `ta.falling` scalar elements.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` tuple literal boolean `ta.cross`, `ta.crossover`, and
  `ta.crossunder` scalar elements while preserving default confirmation
  alignment.
- Added provider-backed `request.security` tuple literal fixture coverage for
  boolean `ta.cross`, `ta.crossover`, and `ta.crossunder` scalar elements.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` tuple literal rolling `ta.sma`, `ta.change`, and
  `ta.cum` scalar elements while preserving requested-context callsite state
  and default confirmation alignment.
- Added provider-backed `request.security` tuple literal fixture coverage for
  rolling `ta.sma`, `ta.change`, and `ta.cum` scalar elements with requested
  context callsite state.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` tuple literal stateless math scalar elements while
  preserving default confirmation alignment.
- Added provider-backed `request.security` tuple literal fixture coverage for
  stateless `math.max`, `math.min`, and `math.abs` scalar elements.
- Added provider-backed `request.security` tuple literal fixture coverage for
  same-timeframe stateless `math.floor`, `math.ceil`, and `math.round` scalar
  elements.
- Added provider-backed `request.security` tuple literal fixture coverage for
  same-timeframe root/log `math.sqrt`, `math.cbrt`, and `math.log10` scalar
  elements.
- Added provider-backed `request.security` tuple literal fixture coverage for
  same-timeframe trig `math.sin`, `math.cos`, and `math.tan` scalar elements.
- Added provider-backed `request.security` tuple literal fixture coverage for
  same-timeframe power/log `math.pow`, `math.hypot`, and `math.log` scalar
  elements.
- Added provider-backed `request.security` tuple literal fixture coverage for
  same-timeframe inverse-trig/exp `math.exp`, `math.acos`, `math.asin`, and
  `math.atan` scalar elements.
- Added provider-backed `request.security` tuple literal fixture coverage for
  same-timeframe angle/scalar `math.avg`, `math.trunc`, `math.sign`,
  `math.todegrees`, and `math.toradians` scalar elements.
- Added provider-backed `request.security` tuple literal fixture coverage for
  same-timeframe `ta.tr()` and `ta.atr()` scalar elements.
- Added provider-backed `request.security` tuple literal fixture coverage for
  same-timeframe `ta.highest()` and `ta.lowest()` scalar elements.
- Added provider-backed `request.security` tuple literal fixture coverage for
  same-timeframe `ta.mom()` and `ta.roc()` scalar elements.
- Added provider-backed `request.security` tuple literal fixture coverage for
  same-timeframe `ta.range()` and `ta.dev()` scalar elements.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` tuple literal history and `nz` scalar elements while
  preserving default confirmation alignment.
- Added provider-backed `request.security` tuple literal fixture coverage for
  history and `nz` scalar elements while keeping provider local aliases
  unsupported.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` `ta.dmi` tuple-returning calls, including aligned
  plus/minus/adx outputs.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` `ta.supertrend` tuple-returning calls while preserving
  default higher-timeframe confirmation alignment.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` `ta.vwap(source, anchor, stdev_mult)` tuple-returning
  calls, including aligned VWAP band outputs.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` `ta.kc` tuple-returning calls, including true-range based
  channel values over host-provided OHLC request bars.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` `ta.bb` tuple-returning calls while preserving the
  existing default higher-timeframe confirmation behavior.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` `ta.macd` tuple-returning calls while keeping the
  supported provider tuple subset narrow and destructuring-only.
- Added higher-timeframe fixture coverage for provider-backed
  `request.security` tuple literal expressions made from supported scalar
  elements while keeping provider local aliases and other tuple expressions
  unsupported.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept provider-backed tuple literals made from supported scalar expression
  elements while keeping provider local aliases and side-effecting expressions
  unsupported.
- Widened the fixture-backed `request.security` requested-expression subset to
  document and test same-context tuple literals made from side-effect-free
  elements.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept provider-backed tuple-returning `ta.vwap(source, anchor, stdev_mult)`
  expressions destructured directly from the request while keeping other
  provider-backed tuple expressions unsupported.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept provider-backed tuple-returning `ta.dmi` expressions destructured
  directly from the request while keeping other provider-backed tuple
  expressions unsupported.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept provider-backed tuple-returning `ta.supertrend` expressions
  destructured directly from the request while keeping other provider-backed
  tuple expressions unsupported.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept provider-backed tuple-returning `ta.kc` expressions destructured
  directly from the request while keeping other provider-backed tuple
  expressions unsupported.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept provider-backed tuple-returning `ta.bb` expressions destructured
  directly from the request while keeping other provider-backed tuple
  expressions unsupported.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept provider-backed tuple-returning `ta.macd` expressions destructured
  directly from the request while keeping other provider-backed tuple
  expressions unsupported.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept same-context tuple-returning `ta.dmi` expressions destructured directly
  from the request while keeping other provider-backed tuple expressions
  unsupported.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept same-context tuple-returning `ta.supertrend` expressions destructured
  directly from the request while keeping other provider-backed tuple
  expressions unsupported.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept same-context tuple-returning `ta.kc` expressions destructured directly
  from the request while keeping other provider-backed tuple expressions
  unsupported.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept same-context tuple-returning `ta.vwap(source, anchor, stdev_mult)`
  expressions destructured directly from the request while keeping other
  provider-backed tuple expressions unsupported.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept the already-supported scalar `ta.pvi` built-in variable in
  provider-backed scalar expressions.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept the already-supported scalar `ta.nvi` built-in variable in
  provider-backed scalar expressions.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept the already-supported scalar `ta.iii` built-in variable in
  provider-backed scalar expressions.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept the already-supported scalar `ta.accdist` built-in variable in
  provider-backed scalar expressions.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept the already-supported scalar `ta.wvad` built-in variable in
  provider-backed scalar expressions.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept the already-supported scalar `ta.pvt` built-in variable in
  provider-backed scalar expressions.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept the already-supported scalar `ta.obv` built-in variable in
  provider-backed scalar expressions.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported scalar `ta.vwap(source)` calls in same-context and
  provider-backed scalar expressions while keeping provider-backed tuple
  expressions outside the subset.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported `ta.valuewhen` calls in same-context and
  provider-backed scalar expressions.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported `ta.lowestbars` calls in same-context and
  provider-backed scalar expressions.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported `ta.highestbars` calls in same-context and
  provider-backed scalar expressions.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported `ta.barssince` calls in same-context and
  provider-backed scalar expressions.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported `ta.pivotlow` calls in same-context and
  provider-backed scalar expressions.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported `ta.pivothigh` calls in same-context and
  provider-backed scalar expressions.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported `ta.kcw` calls in same-context and provider-backed
  scalar expressions.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported one-argument `ta.min` calls in same-context and
  provider-backed scalar expressions.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept same-context `ta.bb` tuple expressions destructured directly from the
  request while keeping other provider-backed tuple expressions unsupported.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported one-argument `ta.max` calls in same-context and
  provider-backed scalar expressions.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported zero-argument `ta.ao` calls in same-context and
  provider-backed scalar expressions.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported zero-argument `ta.bop` calls in same-context and
  provider-backed scalar expressions.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept same-context `ta.macd` tuple expressions destructured directly from the
  request while keeping other provider-backed tuple expressions unsupported.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported two-argument `ta.cog` calls in same-context and
  provider-backed scalar expressions.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported two-argument `ta.cci` calls in same-context and
  provider-backed scalar expressions.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported three-argument `ta.sar` calls in same-context and
  provider-backed scalar expressions.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported single-argument `ta.wpr` calls in same-context and
  provider-backed scalar expressions.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported four-argument `ta.stoch` calls in same-context and
  provider-backed scalar expressions.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported two-argument `ta.mfi` calls in same-context and
  provider-backed scalar expressions.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported `ta.cmo` calls in same-context and provider-backed
  scalar expressions.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported `ta.tsi` calls in same-context and provider-backed
  scalar expressions.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported `ta.tema` calls in same-context and provider-backed
  scalar expressions.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported `ta.dema` calls in same-context and provider-backed
  scalar expressions.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported `ta.rma` calls in same-context and provider-backed
  scalar expressions.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported `ta.vwma` calls in same-context and provider-backed
  scalar expressions.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported `ta.percentrank` calls in same-context and
  provider-backed scalar expressions.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported `ta.percentile_linear_interpolation` calls in
  same-context and provider-backed scalar expressions.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported `ta.percentile_nearest_rank` calls in same-context
  and provider-backed scalar expressions.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported `ta.mode` calls in same-context and provider-backed
  scalar expressions.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported `ta.median` calls in same-context and provider-backed
  scalar expressions.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported `ta.covariance` calls in same-context and
  provider-backed scalar expressions.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported `ta.correlation` calls in same-context and
  provider-backed scalar expressions.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported `ta.bbw` calls in same-context and provider-backed
  scalar expressions.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported `ta.alma` calls in same-context and provider-backed
  scalar expressions.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported `ta.linreg` calls in same-context and provider-backed
  scalar expressions.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported `ta.hma` calls in same-context and provider-backed
  scalar expressions.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported `ta.swma` calls in same-context and provider-backed
  scalar expressions.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported `ta.wma` calls in same-context and provider-backed
  scalar expressions.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported `ta.variance` calls in same-context and
  provider-backed scalar expressions.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported `ta.stdev` calls in same-context and provider-backed
  scalar expressions.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported `ta.cum` calls in same-context and provider-backed
  scalar expressions with requested-context callsite state.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported `ta.cross`, `ta.crossover`, and `ta.crossunder`
  calls in same-context and provider-backed scalar expressions.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported `ta.tr()` and `ta.tr(false)` calls in same-context and
  provider-backed scalar expressions, while keeping the `ta.tr` variable form
  outside the requested-expression subset.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported `ta.rising` and `ta.falling` calls in same-context and
  provider-backed scalar expressions, with requested-context rolling trend state
  isolated from chart state.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported `ta.range` and `ta.dev` calls in same-context and
  provider-backed scalar expressions, with requested-context rolling dispersion
  state isolated from chart state.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported `ta.change`, `ta.mom`, and `ta.roc` calls in
  same-context and provider-backed scalar expressions, with requested-context
  history buffers isolated from chart state.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported `ta.highest` and `ta.lowest` calls in same-context and
  provider-backed scalar expressions, with requested-context extrema callsite
  state isolated from chart state.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported `ta.atr` calls in same-context and provider-backed
  scalar expressions, with requested-context OHLC/history and ATR callsite state
  isolated from chart state.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported `ta.rsi` calls in same-context and provider-backed
  scalar expressions, with requested-context RSI callsite state isolated from
  chart state.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported fixed-mintick `math.round_to_mintick` calls in
  same-context and provider-backed scalar expressions. Provider-specific symbol
  metadata remains outside this fixed default `syminfo.mintick` subset.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported `math.sum` calls in same-context and provider-backed
  scalar expressions, with requested-context rolling state isolated from chart
  state.
- Widened the fixture-backed `request.security` requested-expression subset to
  accept already-supported stateless `math.*` calls in same-context and
  provider-backed scalar expressions. The slice keeps provider data
  host-injected, preserves default higher-timeframe alignment and public JSON
  shapes, and keeps stateful `math.random`, UDF calls, aliases, side effects,
  optional request parameters, and lower-timeframe requests unsupported.
- Tightened the pure webhook transport boundary so host-provided transports
  receive only the already built `WebhookRequest`. Attempt-store records remain
  owned by the adapter flow, preserving the future HTTP transport gate without
  adding network I/O or changing runtime JSON.
- Locked the concrete webhook HTTP transport implementation gate for future
  host-owned alert delivery. The gate requires any real transport to stay
  behind `WebhookTransport`, use explicit host construction, enforce request
  timeouts, test only against local/fake endpoints, preserve redacted
  diagnostics, leave CLI/Python/WASM/runtime JSON unchanged, and avoid network
  side effects unless a host opts in.
- Added pure webhook retry-plan recording for future host-owned alert delivery.
  Host code can now combine a completed adapter run, bounded webhook retry
  policy, and attempt store to record `nextRetryAt` on the existing attempt
  when the decision is retryable, without creating a retry scheduler, jitter,
  dead-letter queue, durable restart recovery, network I/O, user-visible
  reporting, or runtime JSON changes.
- Added pure in-memory retry timestamp recording for future host-owned alert
  delivery. Delivery attempt stores can now record a host-planned
  `nextRetryAt` value on an existing attempt without creating a retry
  scheduler, jitter, dead-letter queue, durable restart recovery, network I/O,
  user-visible reporting, or runtime JSON changes.
- Added pure host delivery diagnostic emission from adapter runs for future
  host-owned alert delivery. `deliver_candidate_with_attempt_store` now returns
  a redacted `HostDeliveryDiagnostic` for transient or permanent failures and
  no diagnostic for delivered attempts, without adding Pine semantic
  diagnostics, public runtime JSON fields, user-visible reporting, or network
  delivery.
- Added a pure webhook delivery adapter over a host-provided transport trait
  for future host-owned alert delivery. The adapter now connects request
  construction, secret resolution, fake/host transport outcomes, HTTP-status
  classification, and attempt-store recording without adding an HTTP client,
  built-in network I/O, retry scheduling, user-visible reporting, or runtime
  JSON changes.
- Added pure webhook request construction for future host-owned alert delivery.
  Host code can now combine validated webhook configuration, resolved headers,
  and rendered payloads into a transport request object without adding an HTTP
  client, request execution, retry scheduling, or network delivery.
- Added a pure webhook secret-resolver interface and resolved-header builder
  for future host-owned alert delivery. Static headers and secret header
  references can now be combined for host transport code without serializing
  resolved secret values, adding a concrete secret store, or sending network
  requests.
- Added pure host delivery diagnostics for future external alert delivery.
  Failed delivery attempts can now produce redacted host diagnostic records from
  attempt/result pairs without adding Pine semantic diagnostics, public runtime
  JSON fields, user-visible reporting, or network delivery.
- Added pure webhook retry decision calculation for future host-owned alert
  delivery. Transient failures can now produce bounded deterministic backoff
  decisions with attempt-budget checks, without adding executable retry
  scheduling, durable restart recovery, dead-lettering, or network delivery.
- Added pure webhook delivery failure classification for future host-owned
  alert delivery. Transport and temporary provider failures now map to
  retryable external delivery results, configuration/secret/payload/provider
  rejection failures map to permanent results, and HTTP provider status codes
  are reduced to redacted status classes without adding network delivery.
- Added pure webhook payload rendering for future host-owned alert delivery.
  `renderedMessage` now produces a plain-text body, and `jsonEnvelope` produces
  a host-versioned JSON envelope over `DeliveryCandidate` without including URL,
  headers, secret references, network delivery, or public runtime JSON fields.
- Added pure host-side `WebhookAdapterConfig` validation for future webhook
  alert delivery. The slice covers URL scheme/host/port/credential checks,
  timeout bounds, duplicate header detection, static secret-header rejection,
  secret-reference checks, and body-mode serialization without network
  delivery.
- Locked the webhook alert delivery adapter design boundary for future host
  delivery work. The plan now spells out URL validation, secret-reference,
  payload-mode, timeout, failure-classification, and diagnostic-redaction gates
  before any network delivery implementation.
- Added a pure host-side `TestCollectorDeliveryAdapter` and
  `deliver_candidate_with_attempt_store` helper for future alert delivery
  adapters. The slice exercises reserve/start/deliver/complete attempt
  recording without adding network delivery, restart-safe persistence, or
  public runtime JSON fields.
- Added a host-side `DeliveryAttemptStore` trait and
  `InMemoryDeliveryAttemptStore` test implementation for future alert delivery
  adapters. The slice covers reserve/start/complete attempt recording without
  adding network delivery, restart-safe persistence, or public runtime JSON
  fields.
- Added pure host-side external delivery identity, attempt record/status, and
  result/status models for future alert delivery adapters. The slice adds tests
  for serialization, retry classification, and adapter+dedupe identity without
  adding network delivery or changing public runtime JSON.
- Added `docs/STRATEGY_EXTERNAL_ALERT_DELIVERY_ADAPTER_PLAN.md` as the closed
  host-owned external alert delivery adapter design gate. It defines adapter,
  durable attempt state, retry, authentication, payload, and failure-reporting
  boundaries without adding network delivery or changing public runtime JSON.
- Designed the shared host alert event envelope for future `both` running-alert
  selection across top-level `alerts[]` and `strategy.alerts[]`. This does not
  enable `both`, add envelope builders, or change public runtime JSON.
- Added a host-only strategy order-fill delivery-candidate builder over
  `RunningAlertConfig` and public `strategy.alerts` events. It remains a
  test/debug helper and does not add realtime source wiring, network delivery,
  or public runtime JSON fields.
- Added a pure host-side `DeliveryCandidate` model, dedupe key, and in-memory
  delivery sink for future realtime alert delivery tests without adding network
  delivery or changing public runtime JSON.
- Added `docs/STRATEGY_REALTIME_ALERT_DELIVERY_PLAN.md` as the closed
  host-owned realtime alert delivery design gate. It defines snapshot,
  dedupe, delivery-candidate, and sink boundaries without adding network
  delivery or changing runtime JSON.
- Added an explicit WASM helper for rendering a strategy order-fill
  running-alert message from host config JSON and a public `strategy.alerts`
  event JSON object. Default WASM runtime JSON and external delivery remain
  unchanged.
- Added an explicit CLI helper path for rendering a strategy order-fill
  running-alert message from host config fields and a selected public
  `strategy.alerts` event. Default runtime JSON and external delivery remain
  unchanged.
- Added an explicit Python helper for rendering a strategy order-fill
  running-alert message from a host config and public `strategy.alerts` event.
  Default `run_script` output and external delivery remain unchanged.
- Added a pure strategy order-fill running-alert evaluation helper over the
  host-side config model and public `strategy.alerts` events. It leaves default
  runtime JSON and external delivery unchanged.
- Added serializable host-side running-alert configuration types for the
  strategy order-fill alert path without applying them to runtime JSON or
  external delivery.
- Added `docs/STRATEGY_RUNNING_ALERT_CONFIGURATION_PLAN.md` as the closed
  host-owned design gate before any external strategy alert delivery work.
- Refreshed the long-term and next-capability planning docs after the strategy
  alert-template host-helper closeout, keeping external delivery gated on
  host-owned running-alert and realtime delivery designs.
- Aligned user-facing conformance and built-in strategy docs with the explicit
  host-side `{{strategy.order.alert_message}}` rendering helpers while keeping
  Pine-source alert placeholders and external alert delivery unsupported.
- Clarified strategy conformance metadata to distinguish explicit host-side
  `{{strategy.order.alert_message}}` rendering helpers from unsupported
  external alert delivery.
- Added an explicit WASM helper for rendering
  `{{strategy.order.alert_message}}` against a public strategy order-fill
  alert JSON object. The helper leaves default WASM runtime JSON, CLI runtime
  JSON, Python dictionaries, and external alert delivery unchanged.
- Added an explicit CLI helper path for rendering
  `{{strategy.order.alert_message}}` against a selected public strategy
  order-fill alert event from `pine-compat run`. The default runtime JSON,
  Python dictionaries, WASM JSON, and external alert delivery remain unchanged.
- Added an explicit Python helper for rendering a host alert template against a
  public strategy order-fill alert event. The helper does not change
  `run_script` output, runtime JSON, WASM JSON, or external alert delivery.
- Added a pure strategy order-fill alert template renderer for the exact
  `{{strategy.order.alert_message}}` host template token. It leaves runtime
  JSON, Python dictionaries, WASM JSON, Pine-source alert placeholder support,
  and external alert delivery unchanged.
- Closed the strategy order-fill alert template design gate. Future
  `{{strategy.order.alert_message}}` work should use a host-layer renderer over
  public `strategy.alerts` events, leaving runtime schema, Pine-source
  placeholder support, and external alert delivery unchanged.
- Exposed broker-owned strategy order-fill alert payloads as
  `strategy.alerts` in public runtime output and moved the runtime contract to
  `schemaVersion: 4` with CLI/Python/WASM parity. Top-level `alerts[]`,
  alert-template placeholder rendering, and external alert delivery remain
  unchanged.
- Added an internal broker-owned strategy order-fill alert event model for
  supported `strategy.entry`, `strategy.exit`, `strategy.close`, and
  `strategy.close_all` fills. The broker now records fill-time alert payloads,
  honors `disable_alert`, and selects `strategy.exit` profit/loss messages by
  filled leg. These broker-owned payloads now feed public `strategy.alerts`;
  placeholder rendering and external alert delivery remain unsupported.
- Closed the Strategy Order-Fill Alerts design gate. Future strategy
  order-fill alert work now has an internal broker event boundary for
  fill-time message selection, `disable_alert` suppression, placeholder
  handling, and host schema review. The follow-on public schema slice exposes
  the broker-owned payloads without changing top-level `alerts[]`.
- Stored supported `strategy.close` and `strategy.close_all` order metadata
  internally on closed-trade metrics. Supported close fill payloads now feed
  public `strategy.alerts`; unsupported `immediately` timing, placeholder
  rendering, and external order-fill alert delivery remain unchanged.
- Stored supported `strategy.exit` order metadata internally on pending and
  deferred exits, including same-identity replacement and omitted-`from_entry`
  fan-out paths. Supported exit fill payloads now feed public
  `strategy.alerts`; external order-fill alert delivery remains unsupported.
- Stored supported `strategy.entry` order metadata internally on pending and
  filled entries. Supported entry fill payloads now feed public
  `strategy.alerts`; external order-fill alert delivery remains unsupported.
- Accepted strategy order metadata parameters at the semantic boundary for
  supported `strategy.entry`, `strategy.exit`, `strategy.close`, and
  `strategy.close_all` calls. `comment`/alert-message fields must be
  string-compatible and `disable_alert` must be bool-compatible; metadata has
  no external alert-delivery or public JSON effect yet, and `immediately`
  remains unsupported.
- Added a Strategy Internal Order Metadata design gate for future
  `comment`/`alert_message`/`disable_alert` work on supported strategy order
  commands. Runtime behavior, public JSON, conformance claims, and host output
  are unchanged until later fixture-backed slices implement the internal
  metadata plumbing.
- Added fixture-backed UDT passthrough through UDF parameters, UDF returns, and
  pure receiver methods. Local UDT values can now be passed to a pure UDF that
  directly returns the same parameter, or a block-local alias chain that starts
  from that parameter, or a nested passthrough UDF call that maps back to that
  parameter, assigned at the callsite through positional or named arguments,
  and field-read there. Pure local UDT methods may also return the receiver
  itself, a block-local alias chain that starts from the receiver or another
  local UDT parameter, another local UDT parameter, or a nested method
  passthrough call that maps back to one of those method parameters, or
  construct and return a local UDT, directly, through nested pure
  constructor-helper UDF calls, or through same-local-UDT ternary or switch
  constructor branches, from receiver or local UDT parameter scalar fields,
  scalar fields read through block-local receiver or local UDT parameter
  aliases, block-local scalar aliases of those fields, inferred scalar
  parameters, or block-local scalar aliases of those parameters using
  positional or named constructor field arguments, and allow the caller to
  assign and field-read that returned value. Local scalar UDT fields can now be
  reassigned with `value.field := expr` outside method bodies, including
  UDF-local variables. Local `for` expressions may construct and return a local
  UDT value from their final body expression. Pure UDFs may construct and
  return local UDT values, directly,
  through nested pure constructor-helper UDF calls, or through same-local-UDT
  ternary, switch, final if/else constructor branches, or final for bodies, from
  local UDT parameter scalar fields, scalar fields read through block-local UDT
  aliases of those parameters, block-local scalar aliases of those fields,
  inferred scalar parameters, or block-local scalar aliases of those scalar
  parameters using positional or named constructor field arguments; field mutation inside
  functions or methods, imported UDT identity, UDT history, `varip`, nested UDT
  fields, and UDT arrays remain outside the supported subset.
- Closed Strategy Internal Stage 13 release-note coverage through Slice 101. The
  Stage 13 multi-entry ledger contract now records omitted-`from_entry`
  trailing future-entry persistence, CLI/WASM/Python host parity for omitted
  future-entry and same-entry-id fixtures, internal per-open-trade exit key
  scoping, current and persistent same-entry-id omitted exits, and same-tick
  price-based entry pyramiding-limit exceptions. The supported surface remains
  limited to `tests/fixtures/conformance.tsv` and does not claim shorts,
  reversals, `strategy.order()`, `close_entries_rule`, public pending-order or
  reservation records, or broader multi-entry reporting.
- Added fixture-backed `alert()` frequency support for the const-string
  `alert.freq_once_per_bar` default, `alert.freq_all`, and
  `alert.freq_once_per_bar_close` subset. The runtime now suppresses repeated
  same-callsite default/once-per-bar alerts within a bar, preserves every
  reached call for `alert.freq_all`, and emits close-frequency alerts only on
  historical or confirmed realtime bar-close execution.
- Added a representative loop/state interaction fixture covering `if`,
  `switch`, `for`, `while`, `break`/`continue`, UDF block bodies, and stateful
  TA callsites in one runtime snapshot without widening accepted syntax.
- Added fixture-backed `array.new_table()` and table-id array support for the
  existing generic array operations, including `array.from` inference and
  shallow `array.copy`. String conversion, `array.join`, `varip` table arrays,
  and polyline arrays remain unsupported.
- Added fixture-backed `array.new_box()` and box-id array support for the
  existing generic array operations, including `array.from` inference and
  shallow `array.copy`. String conversion, `array.join`, `varip` box arrays,
  and polyline arrays remain unsupported.
- Added fixture-backed `array.new_label()` and label-id array support for the
  existing generic array operations, including `array.from` inference and
  shallow `array.copy`. String conversion, `array.join`, `varip` label arrays,
  and polyline arrays remain unsupported.
- Added fixture-backed `array.new_line()` and line-id array support for the
  existing generic array operations, including `array.from` inference and
  shallow `array.copy`. String conversion, `array.join`, `varip` line arrays,
  and polyline arrays remain unsupported.
- Added fixture-backed drawing object method-call syntax for supported
  label/line/box/table id-first functions. Method calls lower to the existing
  namespace-call runtime paths, so this does not widen unsupported drawing
  methods, chart-point overloads, or unsupported xloc/time variants.
- Added fixture-backed `box.set_xloc()` support for the `xloc.bar_index`
  subset. It updates the latest existing box snapshot's left and right values;
  `na` and deleted boxes remain no-ops.
- Added fixture-backed `line.set_xloc()` support for the `xloc.bar_index`
  subset. It updates the latest existing line snapshot's x1 and x2 values;
  `na` and deleted lines remain no-ops.
- Added fixture-backed `line.get_price()` support over the latest existing
  bar-index line snapshot. It uses x1/y1/x2/y2 interpolation or extrapolation
  and returns `na` for `na`, deleted, vertical, or nonnumeric lines.
- Added fixture-backed `line.get_x1()`, `line.get_y1()`, `line.get_x2()`, and
  `line.get_y2()` support over the latest existing line snapshot. `na` and
  deleted lines return `na`.
- Added `line.new()` initialization support for existing host-neutral line
  snapshot style fields: extend, color, style, and width. The supported
  creation subset remains the x1/y1/x2/y2 overload with `xloc` omitted or
  `xloc.bar_index`; chart-point overloads and time-coordinate lines are still
  unsupported.
- Added `box.new()` initialization support for existing host-neutral box
  snapshot style and text fields, including border/background/extend/text,
  alignment, wrapping, font family, and text-formatting masks. The supported
  creation subset remains the left/top/right/bottom overload with `xloc`
  omitted or `xloc.bar_index`; chart-point overloads and time-coordinate boxes
  are still unsupported.
- Added host-neutral `box.set_text_formatting()` support. Box snapshots now
  carry `textFormatting` masks for none/bold/italic combinations while leaving
  glyph styling to hosts.
- Added host-neutral label text-formatting support. `label.new()` can now
  initialize `textalign`, `text_font_family`, and `text_formatting` snapshot
  fields, and `label.set_text_formatting()` records none/bold/italic formatting
  masks while leaving glyph styling to hosts.
- Closed Strategy Internal Stage 13 Slice 34 omitted-`from_entry`
  `strategy.exit` stop+limit bracket future-entry persistence. A full omitted-
  `from_entry` stop+limit bracket now persists for later pyramided long entries
  with the shared absolute stop and limit prices.
- Closed Strategy Internal Stage 13 Slice 33 omitted-`from_entry`
  `strategy.exit` loss+limit bracket future-entry persistence for unique entry
  ids. A full omitted-`from_entry` loss+limit bracket now persists for later
  pyramided long entries with each later entry's own loss stop and the shared
  absolute limit.
- Closed Strategy Internal Stage 13 Slice 32 omitted-`from_entry`
  `strategy.exit` stop+profit bracket future-entry persistence for unique entry
  ids. A full omitted-`from_entry` stop+profit bracket now persists for later
  pyramided long entries with the shared absolute stop and each later entry's
  own profit target.
- Closed Strategy Internal Stage 13 Slice 31 omitted-`from_entry`
  `strategy.exit` loss+profit bracket future-entry persistence for unique entry
  ids. A full omitted-`from_entry` loss+profit bracket now persists for later
  pyramided long entries and derives both bracket legs from each later entry's
  own fill price.
- Closed Strategy Internal Stage 13 Slice 30 omitted-`from_entry`
  `strategy.exit` loss-tick future-entry persistence for unique entry ids. A
  full omitted-`from_entry` loss exit now persists for later pyramided long
  entries and derives each later entry's stop from that entry's own fill price.
- Closed Strategy Internal Stage 13 Slice 29 omitted-`from_entry`
  `strategy.exit` profit-tick future-entry persistence for unique entry ids. A
  full omitted-`from_entry` profit exit now persists for later pyramided long
  entries and derives each later entry's limit from that entry's own fill price.
- Closed Strategy Internal Stage 13 Slice 28 omitted-`from_entry`
  `strategy.exit` `trail_points+trail_offset` trailing all-entry support for
  current unique entry ids. A full omitted-`from_entry` trail-points exit now
  creates entry-specific trailing exits with each open entry's entry-price-based
  activation.
- Closed Strategy Internal Stage 13 Slice 27 omitted-`from_entry`
  `strategy.exit` `trail_price+trail_offset` trailing all-entry support for
  current open entries. A full omitted-`from_entry` trail-price trailing exit now
  uses the existing all-entry FIFO allocation path to close currently open
  pyramided long entries after trailing activation and stop touch.
- Closed Strategy Internal Stage 13 Slice 26 omitted-`from_entry`
  `strategy.exit` `stop+limit` bracket all-entry support for current open
  entries. A full omitted-`from_entry` stop+limit bracket now uses the existing
  all-entry FIFO allocation path to close currently open pyramided long entries.
- Closed Strategy Internal Stage 13 Slice 25 omitted-`from_entry`
  `strategy.exit` `loss+limit` bracket all-entry support for current unique
  entry ids. A full omitted-`from_entry` loss+limit bracket now creates
  entry-specific bracket exits with entry-specific loss stops and a shared
  absolute limit for currently open pyramided long entries with distinct ids.
- Closed Strategy Internal Stage 13 Slice 24 omitted-`from_entry`
  `strategy.exit` `stop+profit` bracket all-entry support for current unique
  entry ids. A full omitted-`from_entry` stop+profit bracket now creates
  entry-specific bracket exits with a shared absolute stop and entry-specific
  profit targets for currently open pyramided long entries with distinct ids.
- Closed Strategy Internal Stage 13 Slice 23 omitted-`from_entry`
  `strategy.exit` `loss+profit` bracket all-entry support for current unique
  entry ids. A full omitted-`from_entry` loss+profit bracket now creates
  entry-specific bracket exits for currently open pyramided long entries with
  distinct ids.
- Closed Strategy Internal Stage 13 Slice 22 omitted-`from_entry`
  `strategy.exit` loss-tick all-entry support for current unique entry ids. A
  full omitted-`from_entry` loss exit now creates entry-specific stop exits for
  currently open pyramided long entries with distinct ids.
- Closed Strategy Internal Stage 13 Slice 21 omitted-`from_entry`
  `strategy.exit` profit-tick all-entry support for current unique entry ids. A
  full omitted-`from_entry` profit exit now creates entry-specific limit exits
  for currently open pyramided long entries with distinct ids.
- Closed Strategy Internal Stage 13 Slice 20 omitted-`from_entry`
  `strategy.exit` persistent future-entry support for the current absolute
  stop/limit subset. A full omitted-`from_entry` stop/limit exit now expands to
  later pyramided long entries until the position closes.
- Closed Strategy Internal Stage 13 Slice 19 omitted-`from_entry`
  `strategy.exit` current all-entry absolute exit support. Supported stop-only
  and limit-only exits without `from_entry` now close all currently open
  pyramided long entries through the ledger, while persistent future-entry
  behavior remains out of scope.
- Closed Strategy Internal Stage 13 Slice 18 trailing `strategy.exit`
  `trail_points` price basis for pyramided entries. Supported trailing
  activation now converts from the matched open entry price instead of aggregate
  average price.
- Closed Strategy Internal Stage 13 Slice 17 bracket `strategy.exit` tick price
  basis for pyramided entries. Supported bracket `profit`/`loss` relative legs now
  convert from the matched open entry price instead of aggregate average price.
- Closed Strategy Internal Stage 13 Slice 16 same-entry-id `strategy.exit`
  allocation fan-out. A supported exit matching multiple open trades with the
  same entry id now records one public exit order and one closed trade per
  matched ledger allocation.
- Closed Strategy Internal Stage 13 Slice 15 relative `strategy.exit` tick price
  basis for pyramided entries. Supported single-trigger `profit`/`loss` exits now
  convert from the matched open entry price instead of aggregate average price.
- Closed Strategy Internal Stage 13 Slice 14 absolute `strategy.exit` matching
  for pyramided entries. Supported absolute stop/limit exits can now target an
  open long ledger entry by `from_entry`, closing that entry while other
  pyramided entries remain open.
- Closed Strategy Internal Stage 13 Slice 12 multi-entry `strategy.close_all()`.
  Close-all now allocates across all open long ledger entries, records one
  closed trade per matched entry, and flattens aggregate position state.
- Closed Strategy Internal Stage 13 Slice 11 multi-entry `strategy.close(id)`
  matching. Close calls now match and clamp against the requested ledger entry
  id, so one pyramided long entry can close while another remains open.
- Closed Strategy Internal Stage 13 Slice 10 long market pyramiding entry
  foundation. `strategy(..., pyramiding=N)` now accepts positive integer const
  values for same-direction long market entries, appends open trades up to the
  configured limit, and keeps default `pyramiding=1` behavior unchanged.
- Closed Strategy Internal Stage 13 Slice 9 open-trade field ledger reads.
  `strategy.opentrades.*` field helpers now read the requested open-trade index
  from `TradeLedger`, with an internal two-entry test, while accepted scripts
  and public output remain unchanged.
- Closed Strategy Internal Stage 13 Slice 8 open-trade count ledger read.
  `BrokerState::open_trade_count()` now reads `TradeLedger::open_count()` and is
  test-backed for an internal two-entry ledger state, while accepted scripts and
  public output remain unchanged.
- Closed Strategy Internal Stage 13 Slice 7 default pyramiding gate helper.
  `BrokerState` now stores an internal `pyramiding_limit` defaulting to `1`, and
  current long-entry placement/fill paths route through `can_open_long_entry()`
  while preserving no-pyramiding behavior and public output.
- Closed Strategy Internal Stage 13 Slice 6 allocation sync helper. Existing
  long `strategy.close`, supported `strategy.exit`, and long margin-call
  reduction paths now sync aggregate `position_size` and `avg_price` from
  `TradeLedger` after allocation updates, with unchanged public behavior.
- Closed Strategy Internal Stage 13 Slice 5 aggregate position sync helper.
  Long entry fills now sync aggregate `position_size` and `avg_price` from
  `TradeLedger::net_position()` after the ledger update, preserving current
  one-open-trade behavior and public output.
- Closed Strategy Internal Stage 13 Slice 4 `TradeLedger` append helper.
  `open_long()` still preserves the current one-open-trade runtime behavior, and
  the new internal append path is covered by a weighted net-position unit test
  without widening conformance, matrix output, or public JSON.
- Closed Strategy Internal Stage 13 Slice 3 entry fill ownership helper.
  `BrokerState::entry_long()` now routes the existing one-open-long fill
  handoff through a private helper that updates legacy singleton mirrors and
  `TradeLedger` together, with no runtime behavior, conformance, matrix, or
  public JSON change.
- Closed Strategy Internal Stage 13 Slice 2 with a ledger ownership audit. The
  audit records current `TradeLedger` responsibilities, legacy singleton
  `BrokerState` mirrors, aggregate accounting owners, existing unit-test
  evidence, and the migration order needed before any positive `pyramiding` or
  multi-entry behavior.
- Closed Strategy Internal Stage 13 Slice 1 boundary lock. Sema fixture tests
  now assert unsupported `pyramiding` and short-entry diagnostics by message,
  while the repeated-entry runtime test verifies the current no-pyramiding
  one-position behavior without widening conformance, matrix output, or public
  JSON.
- Opened Strategy Internal Stage 13 as a multi-entry ledger and pyramiding design
  gate. The plan records official strategy-entry, pyramiding, close-all, FIFO,
  and generic-order dependencies, documents the current one-net-long broker and
  internal `TradeLedger` baseline, and keeps runtime behavior, conformance,
  matrix output, and public JSON unchanged.
- Closed Strategy Internal Stage 12 with a declaration-property audit. The
  closeout records the fixture-backed unsupported declaration-property boundary,
  the supported `strategy.cash` default quantity subset, unchanged public
  strategy JSON shape across CLI/Python/WASM, and the remaining broker-model
  dependencies for timing, recalculation, currency/precision, shorts, pyramiding,
  OCA, and public order-event behavior.
- Closed Strategy Internal Stage 12 Slice 3 `strategy.cash` default quantity
  support. `strategy(default_qty_type=strategy.cash, default_qty_value=N)` now
  resolves omitted supported `strategy.entry` quantities once at placement time
  as `N / close`, covers market, limit, and explicit-`qty` override fixtures
  across CLI/Python/WASM, and keeps currency conversion, precision rounding,
  lot-step constraints, `currency`, shorts, and pyramiding unsupported.
- Closed Strategy Internal Stage 12 Slice 2 property selection review. The next
  runtime target is `default_qty_type=strategy.cash`, scoped to cash divided by
  current close for omitted supported entry quantities, with explicit `qty`
  precedence preserved and currency conversion, precision rounding, `currency`,
  `strategy.order`, shorts, and pyramiding still out of scope.
- Closed Strategy Internal Stage 12 Slice 1 declaration-property boundary lock.
  The unsupported declaration-property fixture now covers only truly unsupported
  `strategy()` properties, sema tests assert each target property diagnostic by
  name, and the unsupported conformance row registers the declaration-property
  rejection fixtures without widening runtime behavior or public output.
- Opened Strategy Internal Stage 12 as a declaration-property design gate. The
  gap audit now reflects the current supported `strategy()` declaration subset,
  removes already-closed `strategy.close_all()` and `strategy.exit` `qty`
  precedence work from next-step recommendations, and keeps runtime behavior,
  conformance claims, and public output unchanged for this design slice.
- Closed Strategy Internal Stage 11 with a partial `strategy.close` audit. The
  closeout records the fixture-backed full close, fixed-`qty` partial close,
  `qty_percent` partial close, and `qty` precedence subset, confirms unchanged
  public strategy JSON shape across CLI, Python, and WASM, and keeps close
  metadata, `immediately`, partial `strategy.close_all()`, multi-entry
  allocation, and public order-event output unsupported.
- Closed Strategy Internal Stage 11 Slice 3 `qty_percent` partial
  `strategy.close`. `strategy.close(id, qty_percent=...)` now resolves finite
  positive percentages against the current matching long position, clamps
  over-100 percentages to the current position size, keeps invalid percentages
  from mutating broker state, and preserves `qty` precedence when both quantity
  forms are supplied.
- Closed Strategy Internal Stage 11 Slice 2 fixed-`qty` partial
  `strategy.close`. `strategy.close(id, qty=...)` now supports finite positive
  fixed quantities for the current one-net-long broker, clamps oversize closes
  to the matching position, keeps remaining position state open, preserves the
  existing public strategy JSON shape without close order events, and cancels
  matching pending exits only on full flatten.
- Closed Strategy Internal Stage 11 Slice 1 boundary lock. Semantic fixtures
  now prove `strategy.close` partial quantity forms and close metadata options
  remain outside the supported subset before fixed-quantity runtime support is
  introduced.
- Opened Strategy Internal Stage 11 as a partial `strategy.close` design gate.
  The plan targets fixture-backed support for fixed `qty`, `qty_percent`, and
  `qty` over `qty_percent` precedence in the current one-net-long broker while
  keeping runtime behavior, conformance claims, and public output unchanged for
  this design slice.
- Closed Strategy Internal Stage 10 with an active-entry relative bracket
  audit. The closeout records the fixture-backed `stop + profit`,
  `loss + limit`, and `loss + profit` pending-entry bracket subset, confirms
  unchanged public strategy JSON shape across CLI, Python, and WASM, and keeps
  same-side pairs, 3+ triggers, trailing-plus-bracket forms, missing-entry
  future binding, broader broker families, and public schema expansion
  unsupported.
- Closed Strategy Internal Stage 10 Slice 5 `loss + profit` active-entry
  bracket attachment. Same-calculation exits targeting a matching active
  pending long entry can now defer both bracket legs until the actual entry
  fill price is known, then place the existing bracket trigger with unchanged
  public strategy JSON shape across CLI, Python, and WASM.
- Closed Strategy Internal Stage 10 Slice 4 `loss + limit` active-entry
  bracket attachment. Same-calculation exits targeting a matching active
  pending long entry can now defer the loss leg until the actual entry fill
  price is known, then place the existing bracket trigger with unchanged public
  strategy JSON shape across CLI, Python, and WASM.
- Closed Strategy Internal Stage 10 Slice 3 `stop + profit` active-entry
  bracket attachment. Same-calculation exits targeting a matching active
  pending long entry can now defer the profit leg until the actual entry fill
  price is known, then place the existing bracket trigger with unchanged public
  strategy JSON shape across CLI, Python, and WASM.
- Closed Strategy Internal Stage 10 Slice 2 deferred bracket storage. The
  broker can now store, replace, take, cancel, and clear internal active-entry
  relative bracket intent without routing runtime `strategy.exit` calls into
  that storage or widening public behavior.
- Closed Strategy Internal Stage 10 Slice 1 boundary lock. Runtime tests now
  captured the pre-routing boundary where active-entry relative bracket forms
  filled only the matching pending entry and created no public exit orders or
  trades before deferred bracket storage was implemented.
- Opened Strategy Internal Stage 10 as an active-entry relative bracket design
  gate. The plan covers future fixture-backed support for `stop + profit`,
  `loss + limit`, and `loss + profit` against matching active pending long
  entries while keeping runtime behavior, conformance claims, and public output
  unchanged for this design slice.
- Closed Strategy Internal Stage 9 with an entry-relative active-entry exit
  audit. The closeout records the supported single-trigger `profit`, `loss`,
  and `trail_points + trail_offset` pending-entry subset, keeps the public
  strategy result schema unchanged, and leaves active-entry relative brackets
  for a separate bracket-specific design slice.
- Closed Strategy Internal Stage 9 Slice 5 `trail_points + trail_offset`
  active-entry attachment. Same-calculation trailing exits can now attach to a
  matching active pending long entry, resolve activation from the actual entry
  fill price, and preserve activation-bar behavior with CLI, Python, WASM,
  conformance, and matrix evidence while relative-leg active-entry brackets
  remain unsupported.
- Closed Strategy Internal Stage 9 Slice 4 `loss` active-entry attachment.
  Same-calculation `strategy.exit(..., loss=...)` now attaches to a matching
  active pending long entry, resolves the stop price from the actual entry fill
  price, and has CLI, Python, WASM, conformance, and matrix evidence while
  `trail_points` and relative-leg active-entry brackets remain unsupported.
- Closed Strategy Internal Stage 9 Slice 3 `profit` active-entry attachment.
  Same-calculation `strategy.exit(..., profit=...)` now attaches to a matching
  active pending long entry, resolves the take-profit limit from the actual
  entry fill price, and has CLI, Python, WASM, conformance, and matrix evidence
  while `loss` and `trail_points` active-entry attachment remain unsupported.
- Closed Strategy Internal Stage 9 Slice 2 deferred relative trigger skeleton.
  The broker can now store, replace, and clear internal `profit`, `loss`, and
  `trail_points + trail_offset` active-entry exit intent without routing
  runtime calls into that storage or widening public behavior.
- Closed Strategy Internal Stage 9 Slice 1 current boundary lock. Broker tests
  now prove `profit`, `loss`, and `trail_points + trail_offset` active-entry
  attachment remains rejected for current market, limit, stop, and stop-limit
  pending entries, without widening conformance or public output.
- Added Strategy Internal Stage 9 Slice 0 entry-relative active-entry exit
  design gate. The plan targets fixture-backed `strategy.exit` attachment for
  `profit`, `loss`, and `trail_points` against matching active pending entries
  while keeping broader missing-entry, pyramiding, short, reversal, and
  `strategy.order()` behavior unsupported.
- Closed Strategy Internal Stage 8 with a broker expansion audit. The audit
  records the completed behavior-preserving internal order, ledger, allocation,
  and fill-routing skeleton and leaves broader Pine strategy compatibility
  widening to a new staged direction.
- Closed Strategy Internal Stage 8 Slice 16 open long legacy state recorder.
  Current supported long entry fills now use one `OpenTrade` metadata object to
  update both the legacy one-position fields and internal ledger while
  preserving public output and conformance.
- Closed Strategy Internal Stage 8 Slice 15 entry position snapshot routing.
  Current supported long entry fills now write public net-position snapshots
  through the shared internal snapshot recorder while preserving output and
  conformance.
- Closed Strategy Internal Stage 8 Slice 14 entry order event routing. Current
  supported long entry fills now use the shared internal order-event recorder
  while preserving public order output, conformance, Python, and WASM behavior.
- Closed Strategy Internal Stage 8 Slice 13 order event recorder. Long
  margin-call and supported pending `strategy.exit` fills now write existing
  public order events through one internal helper, while `strategy.close`,
  public output, and conformance remain unchanged.
- Closed Strategy Internal Stage 8 Slice 12 position snapshot recorder. Full
  and partial long margin liquidation, `strategy.close`, and supported pending
  `strategy.exit` fills now write existing public net-position snapshots
  through one internal helper while preserving public output and conformance.
- Closed Strategy Internal Stage 8 Slice 11 flat long legacy state cleanup.
  Full long margin liquidation, `strategy.close`, and full supported pending
  `strategy.exit` cleanup now share one internal legacy-state reset helper,
  while ledger allocation application, position snapshots, public trades,
  closed-trade metrics, and conformance remain unchanged.
- Closed Strategy Internal Stage 8 Slice 10 closed trade fill recorder. The
  current long margin-call, `strategy.close`, and supported pending
  `strategy.exit` paths now record existing `StrategyTrade` and
  `ClosedTradeMetrics` outputs through one internal `ClosedTradeFill` helper
  while preserving public output and conformance.
- Closed Strategy Internal Stage 8 Slice 9 allocated entry fill summary. The
  current long margin-call, `strategy.close`, and supported pending
  `strategy.exit` trade-emission paths now share an internal
  `AllocatedEntryFill` summary for allocation metadata and commission fallback
  handling while preserving existing public output and conformance.
- Closed Strategy Internal Stage 8 Slice 8 allocation entry metadata. Internal
  `TradeAllocation` slices now carry entry price, entry bar index, and entry
  time from `OpenTrade`, and current margin-call, `strategy.close`, and
  supported pending `strategy.exit` trade emission reads that metadata while
  preserving existing public output and conformance.
- Closed Strategy Internal Stage 8 Slice 7 single-position exit allocation
  routing. The current long margin-call, `strategy.close`, and supported
  pending `strategy.exit` fill paths now synchronize `TradeLedger` through
  FIFO allocation helpers while preserving existing public output,
  conformance, Python, and WASM behavior.
- Added Strategy Internal Stage 8 Slice 6 internal FIFO allocation helpers.
  `TradeLedger` can now plan omitted-entry and entry-id FIFO allocation slices
  and apply them to internal open trades while rebuilding net position, without
  wiring multiple open trades into runtime behavior or changing conformance,
  public strategy output, Python, or WASM behavior.
- Closed the Strategy Internal Stage 8 Slice 5 first widening candidate by
  choosing an internal-only multiple-open-trade skeleton. `TradeLedger` now
  stores open trades as an internal list and rebuilds net position from that
  list, while current runtime behavior still permits only one supported long
  open trade and keeps public output and conformance unchanged.
- Closed the Strategy Internal Stage 8 Slice 4 multiple-open-trade allocation
  design gate. The plan now fixes future `from_entry`, omitted-`from_entry`,
  FIFO close ordering, partial-exit commission/run-up/drawdown allocation,
  margin-liquidation allocation, public-output boundaries, and concrete fixture
  gates before any pyramiding or multi-entry runtime widening.
- Added the Strategy Internal Stage 8 Slice 3 order-book skeleton. `BrokerState`
  now owns pending entries and exits through an internal `OrderBook` facade
  that delegates to the existing `PendingEntryBook` and `PendingExitBook`,
  preserving cancellation, entry fill, exit reservation, conformance, and
  public output behavior without adding generic orders or OCA support.
- Added the Strategy Internal Stage 8 Slice 2 broker ledger skeleton. The
  runtime now mirrors the existing single long open trade and net position into
  internal `TradeLedger` state across entry, open-trade extremes, partial
  reductions, margin-call reductions, and final flat transitions while keeping
  public strategy output, conformance status, and current metric behavior
  unchanged.
- Closed Strategy Internal Stage 8 Slice 1 boundary lock for the first semantic
  guardrail subset. Added dedicated negative fixtures for unsupported
  `pyramiding=2` and `strategy.exit(..., oca_name=...)` while keeping runtime
  behavior, conformance status, and public output unchanged.
- Added `docs/STRATEGY_INTERNAL_STAGE8_BROKER_EXPANSION_PLAN.md` as the
  design gate for future broker expansion. The plan keeps runtime behavior,
  conformance, and public CLI/Python/WASM strategy output unchanged while
  documenting the intended ledger, order-book, same-bar precedence, OCA, and
  slice sequence before any short, reversal, pyramiding, or generic-order work.
- Closed the current Strategy Internal Stage 7 planning boundary in docs. The
  Stage 7 audit and execution plan now mark the fixture-backed long-only
  trade-record, cost, reporting, default-sizing, and active-margin account
  subset closed, and point the next strategy step at a Stage 8 broker-expansion
  design gate rather than another runtime patch.
- Closed the Strategy Internal active-entry exit attachment evidence slice.
  A same-calculation absolute `strategy.exit` can target a matching active
  pending long entry id and later fill through the existing public
  order/trade/position/equity schema after the entry fills. The new fixture
  covers a supported long limit entry plus attached stop exit across CLI,
  Python, and WASM while keeping unmatched future binding and entry-relative
  pending-entry exits unsupported.
- Implemented Strategy Internal Margin Slice M5. Explicit active `margin_long`
  now supports the first long-only forced-liquidation subset: historical checks
  use `bar.low`, apply TradingView's documented available-funds and
  four-times-cover algorithm with temporary whole-unit truncation, emit existing
  order/trade/position/equity output only, and update
  `strategy.opentrades.capital_held` for the remaining long position.
- Closed Strategy Internal Margin Slice M4 with
  `docs/STRATEGY_INTERNAL_MARGIN_CALL_DESIGN.md`, mapping TradingView's
  documented long margin-call algorithm onto the current long-only broker and
  defining the no-schema-expansion output, timing, and whole-unit truncation
  boundary for the later liquidation implementation.
- Implemented Strategy Internal Margin Slice M3. With explicit active
  `margin_long`, supported long market, limit, stop, and stop-limit entry fills
  now check required margin at the actual fill price, reject overleveraged fills
  with a strategy diagnostic, and keep public strategy output shape unchanged;
  short margin behavior and margin liquidation price remain unsupported.
- Implemented Strategy Internal Margin Slice M2. With explicit active
  `margin_long`, `strategy.opentrades.capital_held` now returns current open
  long market value times `margin_long / 100`, returns `0.0` while flat, and
  preserves `na` in the no-margin subset.
- Implemented Strategy Internal Margin Slice M1. `strategy(..., margin_long=N,
  margin_short=N)` now accepts finite non-negative const numeric declaration
  values and stores their explicit presence in IR.
- Added `docs/STRATEGY_INTERNAL_MARGIN_ACCOUNT_MODEL_PLAN.md` as the design
  gate for future margin/account-model work. The document keeps current
  runtime behavior unchanged while defining the official semantics, non-goals,
  slice order, and stop conditions for any later `margin_long`,
  `margin_short`, `strategy.opentrades.capital_held`, and forced-liquidation
  implementation.
- Added Strategy Internal Stage 7 Slice 35
  `strategy.opentrades.capital_held` as a read-only strategy-mode variable. In
  the current no-margin subset it returns `na`, matching Pine's behavior when a
  strategy does not simulate funding trades with `margin_long` or
  `margin_short`, while public JSON, Python, and WASM strategy schemas remain
  unchanged.
- Added Strategy Internal Stage 7 Slice 34
  `strategy.max_contracts_held_all`, `strategy.max_contracts_held_long`, and
  `strategy.max_contracts_held_short`. Strategy-mode scripts can read maximum
  held quantity metrics for the current long-only subset while public JSON,
  Python, and WASM strategy schemas remain unchanged.
- Added Strategy Internal Stage 7 Slice 33
  `strategy.avg_trade_percent`, `strategy.avg_winning_trade_percent`, and
  `strategy.avg_losing_trade_percent`. Strategy-mode scripts can read average
  per-trade percentage profit/loss values while public JSON, Python, and WASM
  strategy schemas remain unchanged.
- Added Strategy Internal Stage 7 Slice 32
  `strategy.netprofit_percent`, `strategy.grossprofit_percent`, and
  `strategy.grossloss_percent`. Strategy-mode scripts can read realized
  profit/loss percentages relative to `initial_capital`, while public JSON,
  Python, and WASM strategy schemas remain unchanged.
- Added Strategy Internal Stage 7 Slice 31
  `default_qty_type=strategy.percent_of_equity`.
  Supported long entries without explicit `qty` now resolve their default
  quantity from current supported equity and current close at placement time,
  while cash sizing, margin behavior beyond the later explicit-margin subset,
  and currency conversion remain unsupported.
- Added Strategy Internal Stage 7 Slice 30
  `strategy.max_runup_percent` and `strategy.max_drawdown_percent`.
  Strategy-mode scripts can read maximum intrabar equity run-up/drawdown
  percentages over the current supported long-only trading interval, while
  keeping public JSON, Python, and WASM strategy schemas unchanged.
- Added Strategy Internal Stage 7 Slice 28 `strategy.max_runup`.
  Strategy-mode scripts can read maximum intrabar equity run-up amount over the
  current supported long-only trading interval, while keeping public JSON,
  Python, and WASM strategy schemas unchanged.
- Added Strategy Internal Stage 7 Slice 27 `strategy.max_drawdown`.
  Strategy-mode scripts can read maximum intrabar equity drawdown amount over
  the current supported trading interval, while keeping public JSON, Python,
  and WASM strategy schemas unchanged.
- Added Strategy Internal Stage 7 Slice 26 `strategy.avg_losing_trade`.
  Strategy-mode scripts can read average realized loss among losing closed
  trades only as a positive value, with `na` before the first losing closed
  trade, while keeping public JSON, Python, and WASM strategy schemas
  unchanged.
- Added Strategy Internal Stage 7 Slice 25 `strategy.avg_winning_trade`.
  Strategy-mode scripts can read average realized profit among winning closed
  trades only, with `na` before the first winning closed trade, while keeping
  public JSON, Python, and WASM strategy schemas unchanged.
- Added Strategy Internal Stage 7 Slice 24 `strategy.avg_trade`. Strategy-mode
  scripts can read average realized profit/loss per closed trade, with `na`
  before the first closed trade, while keeping public JSON, Python, and WASM
  strategy schemas unchanged.
- Added Strategy Internal Stage 7 Slice 23 `strategy.grossloss`. Strategy-mode
  scripts can read cumulative realized closed-trade loss as a positive series
  that excludes winning, flat, and current open trades while keeping public
  JSON, Python, and WASM strategy schemas unchanged.
- Added Strategy Internal Stage 7 Slice 22 `strategy.grossprofit`. Strategy-mode
  scripts can read a cumulative positive realized closed-trade profit series
  that excludes losing, flat, and current open trades while keeping public JSON,
  Python, and WASM strategy schemas unchanged.
- Added Strategy Internal Stage 7 Slice 21 percent commission accounting.
  `strategy(..., commission_type=strategy.commission.percent,
  commission_value=N)` now debits `qty * fill_price * N / 100` on supported
  entry and exit fills, updates cash, equity, closed trade profit,
  `strategy.netprofit`, and closed/open trade `commission()` field functions,
  and keeps public JSON, Python, and WASM strategy schemas unchanged.
- Added Strategy Internal Stage 7 Slice 20 fixed-tick limit verification.
  `strategy(..., backtest_fill_limits_assumption=N)` now accepts finite
  non-negative integer const ticks, requires supported long limit entry and
  supported long limit/profit exit fills to move that many fixed
  `syminfo.mintick` ticks beyond the limit price, preserves the original limit
  fill price, and keeps public JSON, Python, and WASM strategy schemas
  unchanged.
- Added Strategy Internal Stage 7 Slice 19 fixed-tick slippage. `strategy(...,
  slippage=N)` now accepts finite non-negative integer const ticks, converts
  them through the fixed `syminfo.mintick` subset, worsens supported long entry
  fill prices upward and supported long close/exit fill prices downward after
  trigger selection, and keeps public JSON, Python, and WASM strategy schemas
  unchanged.
- Added Strategy Internal Stage 7 Slice 18 cash-per-order commission
  accounting. `strategy(...,
  commission_type=strategy.commission.cash_per_order, commission_value=N)` now
  applies one fixed commission per supported entry and exit fill, allocates
  entry commission across partial closes, updates cash, equity, closed trade
  profit, `strategy.netprofit`, and the closed/open trade `commission()` field
  functions, and keeps public JSON, Python, and WASM strategy schemas
  unchanged.
- Added Strategy Internal Stage 7 Slice 17 cash-per-contract commission
  accounting. `strategy(...,
  commission_type=strategy.commission.cash_per_contract, commission_value=N)`
  now applies entry and exit commission to cash, equity, closed trade profit,
  `strategy.netprofit`, and the closed/open trade `commission()` field
  functions while leaving public JSON, Python, and WASM strategy schemas
  unchanged; unsupported commission modes beyond the current listed subset plus
  richer fill models remain unsupported.
- Added Strategy Internal Stage 7 Slice 16 closed-trade `max_drawdown()` field
  function. It exposes the largest low-based adverse excursion retained for the
  closed trade quantity, follows the same zero-based `trade_num` contract,
  returns `na` for invalid indexes, and keeps public JSON, Python, and WASM
  strategy schemas unchanged.
- Added Strategy Internal Stage 7 Slice 15 closed-trade `max_runup()` field
  function. It exposes the largest high-based favorable excursion retained for
  the closed trade quantity, follows the same zero-based `trade_num` contract,
  returns `na` for invalid indexes, and keeps public JSON, Python, and WASM
  strategy schemas unchanged.
- Added Strategy Internal Stage 7 Slice 14 open-trade `max_drawdown()` field
  function. It exposes the largest low-based adverse excursion seen so far for
  the current supported long position when `trade_num == 0`, returns `na` when
  flat or for invalid indexes, and keeps public JSON, Python, and WASM strategy
  schemas unchanged.
- Added Strategy Internal Stage 7 Slice 13 open-trade `max_runup()` field
  function. It exposes the largest high-based favorable excursion seen so far
  for the current supported long position when `trade_num == 0`, returns `na`
  when flat or for invalid indexes, and keeps public JSON, Python, and WASM
  strategy schemas unchanged.
- Added Strategy Internal Stage 7 Slice 12 open-trade `commission()` field
  function. It exposes `0.0` without configured commission, later reports the
  supported cash-per-contract entry commission when configured, returns `na`
  when flat or for invalid indexes, and keeps public JSON, Python, and WASM
  strategy schemas unchanged.
- Added Strategy Internal Stage 7 Slice 11 open-trade `entry_id()` field
  function. It exposes the current supported long position entry id when
  `trade_num == 0`, returns `na` when flat or for invalid indexes, and keeps
  public JSON, Python, and WASM strategy schemas unchanged.
- Added Strategy Internal Stage 7 Slice 10 open-trade `profit()` field
  function. It exposes the current close-based floating profit for the current
  supported long position when `trade_num == 0`, returns `na` when flat or for
  invalid indexes, and keeps public JSON, Python, and WASM strategy schemas
  unchanged.
- Added Strategy Internal Stage 7 Slice 9 open-trade `size()` field function.
  It exposes the current supported long position size for `trade_num == 0`,
  returns `na` when flat or for invalid indexes, and keeps public JSON, Python,
  and WASM strategy schemas unchanged.
- Added Strategy Internal Stage 7 Slice 8 open-trade `entry_time()` field
  function. It exposes the current supported long position's entry fill
  timestamp for `trade_num == 0`, returns `na` when flat or for invalid
  indexes, and keeps public JSON, Python, and WASM strategy schemas unchanged.
- Added Strategy Internal Stage 7 Slice 7 open-trade `entry_bar_index()` field
  function. It exposes the current supported long position's entry fill bar for
  `trade_num == 0`, returns `na` when flat or for invalid indexes, and keeps
  public JSON, Python, and WASM strategy schemas unchanged.
- Added Strategy Internal Stage 7 Slice 6 open-trade `entry_price()` field
  function. It exposes the current supported long position's entry price for
  `trade_num == 0`, returns `na` when flat or for invalid indexes, and keeps
  public JSON, Python, and WASM strategy schemas unchanged.
- Added Strategy Internal Stage 7 Slice 5 closed-trade `exit_id()` field
  function. It returns the retained close id for `strategy.close` /
  `strategy.close_all` fills and the pending exit id for `strategy.exit` fills,
  follows the same zero-based `trade_num` contract, and keeps public JSON,
  Python, and WASM strategy trade schemas unchanged.
- Added Strategy Internal Stage 7 Slice 4 closed-trade `entry_id()` field
  function. It returns the entry id already retained on closed trade records,
  follows the same zero-based `trade_num` contract, returns `na` for invalid
  indexes, and keeps public JSON, Python, and WASM strategy trade schemas
  unchanged.
- Added Strategy Internal Stage 7 Slice 3 closed-trade `commission()` field
  function. It follows the same zero-based `trade_num` contract as the existing
  script-visible closed-trade fields and returns `0.0` without configured
  commission, later reports supported entry-plus-exit cash-per-contract
  commission when configured, and keeps public JSON, Python, and WASM strategy
  trade schemas unchanged.
- Added Strategy Internal Stage 7 Slice 2 closed-trade `entry_time` and
  `exit_time` field functions. They expose the timestamps already retained on
  closed trade records, use the same zero-based `trade_num` contract, and keep
  the public runtime output shape unchanged.
- Added Strategy Internal Stage 7 Slice 1 closed-trade `size` and `profit`
  field functions. They use the same zero-based `trade_num` contract as the
  existing closed-trade field subset, return `na` for invalid or out-of-range
  indexes, and keep the public runtime output shape unchanged. Open-trade
  namespaces, runup/drawdown, ids, times, and richer reporting metrics remain
  unsupported.
- Added Strategy Internal Stage 7 Slice 0 closed-trade field functions:
  `strategy.closedtrades.entry_price`, `strategy.closedtrades.exit_price`,
  `strategy.closedtrades.entry_bar_index`, and
  `strategy.closedtrades.exit_bar_index`. These read the existing closed-trade
  list in strategy-mode scripts with zero-based integer `trade_num` indexes,
  return `na` for invalid or out-of-range indexes, and keep the public runtime
  output shape unchanged. Open-trade namespaces, additional closed-trade fields,
  and richer reporting metrics remain unsupported.
- Added Strategy Internal Stage 6 Slice 1 `strategy.cancel_all()` support for
  the current supported pending-entry and pending-exit subset. The call clears
  all supported internal pending orders, is a no-op when none exist, and keeps
  the public strategy output shape unchanged. Generic order APIs, OCA groups,
  pyramiding, shorts, and reversals remain unsupported.
- Added Strategy Internal Stage 6 Slice 0 `strategy.cancel(id)` support for
  the current supported pending-entry and pending-exit subset. Matching pending
  ids are cancelled internally, filled or unknown ids are no-op, and the public
  strategy output shape remains unchanged. Generic order APIs, OCA groups,
  pyramiding, shorts, and reversals remain unsupported.
- Added Strategy Internal Stage 5 Slice 2 long `strategy.entry(..., stop=...,
  limit=...)` stop-limit support. Supported long stop-limit entries use the
  existing internal pending-entry model, activate on a later historical bar when
  `high >= stop`, do not fill on that activation bar, and fill at the limit
  price on a later historical bar when `low <= limit`, with no public
  pending-order output. Shorts, pyramiding, and generic order APIs remain
  unsupported.
- Added Strategy Internal Stage 5 Slice 1 long `strategy.entry(..., stop=...)`
  support. Supported long stop entries use the existing internal pending-entry
  model, never fill on their creation bar, and fill at the stop price on a later
  historical bar when `high >= stop`, with no public pending-order output.
  Shorts, pyramiding, and generic order APIs remain unsupported.
- Added Strategy Internal Stage 5 Slice 0 long `strategy.entry(..., limit=...)`
  support. Supported long limit entries use the existing internal pending-entry
  model, never fill on their creation bar, and fill at the limit price on a
  later historical bar when `low <= limit`, with no public pending-order output.
  Shorts, pyramiding, and generic order APIs remain unsupported.
- Added Strategy Internal Stage 4 `strategy.exit` quantity precedence. For
  supported single-trigger, bracket, and trailing exit shapes, calls that supply
  both `qty` and `qty_percent` now follow Pine-compatible precedence where fixed
  `qty` determines the reserved or filled quantity and `qty_percent` is ignored.
  Unsupported trigger combinations remain rejected, and the public strategy
  output shape is unchanged.
- Added Strategy Internal Stage 3 Slice 1 trade outcome count variables.
  `strategy.wintrades`, `strategy.losstrades`, and `strategy.eventrades` are
  read-only strategy-mode series int counts derived from the current closed
  trade list by positive, negative, and zero realized profit. Rich trade
  namespace functions and broader reporting metrics remain unsupported, and the
  public strategy output shape is unchanged.
- Added Strategy Internal Stage 3 Slice 0 `strategy.close_all()` support for
  the current one-net-long broker. Strategy-mode scripts can close the current
  supported long position at the current bar close without naming the entry id;
  flat or already-closed calls are no-op, pending exits for the closed entry are
  cancelled, and the existing public strategy output shape is unchanged.
- Added Strategy Internal Stage 2 pending-entry timing. Supported market-long
  `strategy.entry` calls now create an internal pending entry and fill at the
  next historical bar open, with no public pending-order output. Same-calculation
  absolute `strategy.exit` attachment for the active pending entry id is
  supported, including fixed `qty` or `qty_percent` reservation against the
  pending entry quantity; same-calculation entry-relative `profit`, `loss`, and
  `trail_points` attachment remains unsupported until deferred price resolution
  is designed. Public strategy output shape remains unchanged.
- Closed Strategy Internal Stage 1 boundary lock documentation. The Stage 1
  audit records the current fixture-backed strategy support and unsupported
  boundary, aligns current reservation wording for single-trigger, bracket, and
  trailing `strategy.exit` reservations, and adds negative semantic fixtures
  for unsupported strategy declaration properties plus unsupported
  order/trade/risk namespaces. Runtime behavior and public strategy output are
  unchanged; conformance and matrix snapshots are synchronized to the added
  semantic guard coverage.
- Closed Phase Z for the omitted-quantity `strategy.exit` boundary. Omitted
  `qty` and omitted `qty_percent` exits keep full-position
  one-effective-pending behavior across supported single-trigger, bracket, and
  trailing forms, and a later omitted full-position exit clears earlier explicit
  reservations for the current matching long entry. Runtime fixtures and
  CLI/Python/WASM host tests cover the boundary. Omitted-quantity multiple
  reservations, missing-entry pre-placement, public pending/reservation fields,
  pyramiding, shorts, and richer broker behavior remain unsupported.
- Added Phase Y `strategy.exit` trailing reservations for explicit fixed `qty`
  or `qty_percent` trailing exits on the current matching long entry. Supported
  trailing reservation forms remain `trail_price + trail_offset` and
  `trail_points + trail_offset`. Different `id + from_entry` identities can keep
  multiple internal pending trailing reservations, and trailing reservations can
  share the reservation pool with Phase W single-trigger and Phase X bracket
  reservations. Inactive trailing reservations activate on a later eligible bar
  without filling on that bar; active trailing reservations fill as downside
  candidates before same-bar ratchets, and otherwise ratchet upward only. Public
  runtime output remains `schemaVersion: 3` and continues to expose only
  `orders`, `trades`, `position`, `equity`, and `diagnostics` under `strategy`.
  Omitted-quantity multiple reservations, missing-entry pre-placement, public
  pending/trailing-state records, pyramiding, shorts, and richer broker behavior
  remain unsupported.
- Added Phase X `strategy.exit` bracket reservations for explicit fixed `qty`
  or `qty_percent` one-downside/one-upside brackets on the current matching
  long entry. Different `id + from_entry` identities can keep multiple internal
  pending bracket reservations, and bracket reservations can share the
  reservation pool with Phase W single-trigger reservations. Same identities
  replace the previous reservation after releasing it; new reservations resolve
  at placement time, clamp to remaining unreserved position quantity, and are
  rejected with strategy diagnostics when no quantity remains. Same-side
  touched candidates fill in placement order, mixed downside/upside same-bar
  touches process downside candidates only, and a both-leg bracket touch
  contributes the bracket's downside candidate. Public runtime output remains
  `schemaVersion: 3` and continues to expose only `orders`, `trades`,
  `position`, `equity`, and `diagnostics` under `strategy`. Omitted-quantity
  multiple reservations, missing-entry pre-placement, public pending-order
  records, pyramiding, shorts, and richer broker behavior remain unsupported.
- Added Phase W `strategy.exit` quantity reservations for explicit fixed
  `qty` or `qty_percent` single-trigger exits on the current matching long
  entry. Different `id + from_entry` identities can keep multiple internal
  pending reservations; same identities replace the previous reservation after
  releasing it. New reservations resolve at placement time, clamp to remaining
  unreserved position quantity, and are rejected with strategy diagnostics when
  no quantity remains. Same-side touched exits fill in placement order, while
  mixed downside/upside same-bar touches process downside candidates only.
  Public runtime output remains `schemaVersion: 3` and continues to expose only
  `orders`, `trades`, `position`, `equity`, and `diagnostics` under
  `strategy`. Omitted-quantity multiple reservations, missing-entry
  pre-placement, public pending-order records, pyramiding, shorts, and richer
  broker behavior remain unsupported.
- Closed Phase V for the current fixture-backed `strategy.exit(...,
  qty_percent=...)` subset. The audit records supported single-trigger,
  one-downside/one-upside bracket, and trailing percent exits; placement-time
  percent-to-absolute resolution; fill-time clamping; unchanged public runtime
  schema; host coverage; and the full release verification gate.
- Added Phase V `strategy.exit(..., qty_percent=...)` support on the existing
  supported single-trigger, one-downside/one-upside bracket, and trailing exit
  subsets. `qty_percent` is evaluated at placement time, must be finite and
  positive, resolves to an absolute requested close quantity against the current
  position size, and fills no more than the current position. Public strategy
  outputs continue to expose absolute order/trade `qty` values with no schema
  bump. Quantity reservation, multiple pending exits, missing-entry
  pre-placement, pyramiding, shorts, and richer broker behavior remain
  unsupported.
- Added Phase U fixed `strategy.exit(..., qty=...)` support for the existing
  single-trigger, one-downside/one-upside bracket, and trailing exit subsets.
  Fixed `qty` is evaluated at placement time, must be finite and positive,
  fills `min(qty, position_size)`, leaves any remaining long position open at
  the same average price, and keeps the public strategy result shape and
  runtime `schemaVersion: 3`. Phase U did not add `qty_percent`, quantity
  reservation, multiple pending exits, missing-entry pre-placement, pyramiding,
  shorts, or richer broker behavior.
- Added Phase T WASM request-bars host injection for the existing
  provider-backed `request.security` subset. WASM hosts can now pass explicit
  `requestBarsJson` data through `runScriptCsvWithRequestBars`,
  `runScriptCsvWithLibrariesAndRequestBars`, and
  `Program.runCsvWithRequestBars`, while request semantics, conformance status,
  and runtime `schemaVersion: 3` remain unchanged.
- Added the Phase S `strategy.exit` trailing-stop subset. Supported forms are
  exactly `trail_price + trail_offset` and `trail_points + trail_offset` for
  the current long-only, no-pyramiding broker. Trailing exits activate on a
  later eligible historical bar, do not fill on the activation bar, ratchet the
  active stop upward only, emit one existing `strategy.exit` order event and one
  closed trade when filled, keep runtime `schemaVersion: 3`, and leave invalid
  trailing combinations, partial exits, missing-entry pre-placement, and richer
  broker behavior unsupported.
- Closed Phase R for the first positive `strategy.exit` bracket subset.
  Supported brackets are exactly `stop + limit`, `stop + profit`,
  `loss + limit`, and `loss + profit` for the current long-only,
  no-pyramiding broker. A bracket is one pending full-position exit, uses
  stop/loss-first precedence when both legs are touched on the same eligible
  historical bar, emits one `strategy.exit` order event and one closed trade,
  keeps runtime `schemaVersion: 3`, and leaves same-side pairs, 3+ triggers,
  trailing stops, partial exits, missing-entry pre-placement, and richer broker
  behavior unsupported.
- Closed Phase Q as a `strategy.exit` bracket design gate. At Phase Q close,
  combined trigger exits remained unsupported, and the audit recorded the
  future one-downside plus one-upside bracket subset, stop/loss-first same-bar
  precedence, identity/replacement rules, invalid-leg behavior, fixture plan,
  and module implementation blueprint, with the full release verification gate
  passing on the closeout workspace.
- Hardened `strategy.exit` unsupported diagnostics to use phase-neutral
  current-subset wording and added a diagnostic-only four-trigger
  `stop + limit + profit + loss` fixture, with conformance and matrix metadata
  updated without widening support.
- Implemented Phase P broker-structure maintenance. Strategy broker internals
  are split into facade, pending-exit, fill, accounting, and broker-test
  modules while preserving the existing strategy compatibility surface, public
  runtime `schemaVersion: 3`, CLI/Python/WASM output shapes, and runtime
  snapshots.
- Recorded Phase Q as the next strategy maintenance target after Phase P:
  a bracket design gate to specify same-bar precedence, bracket identity, and
  interaction with the current one-pending-exit model before any later support
  claim.
- Closed Phase O for the current fixture-backed strategy reporting count
  subset. The audit records supported `strategy.closedtrades` and
  `strategy.opentrades` count variables, explicit unsupported reporting
  namespaces and rich metrics, unchanged public runtime schema, host coverage,
  and the full release verification gate.
- Added Phase O strategy reporting count compatibility metadata and docs for
  `strategy.closedtrades` and `strategy.opentrades`. The supported subset is
  strategy-mode historical series int counts for the current long-only broker;
  rich trade namespaces, public open-trade records, and broader reporting
  metrics remain unsupported, with no runtime schema bump.
- Closed Phase N for the current fixture-backed `strategy.exit` profit/loss
  subset. The audit records supported profit-only and loss-only tick-distance
  exits, unsupported bracket/trailing/partial forms, unchanged public runtime
  schema, host coverage, and the full release verification gate.
- Closed Phase N Slice 7 as a bracket design gate. Combined trigger exits stay
  unsupported, including stop/limit, profit/loss, mixed price/tick, and
  three-trigger calls, because OHLC-only same-bar precedence remains a future
  broker design task.
- Hardened Phase N Slice 6 profit/loss exit interactions. Runtime fixtures now
  cover profit placement and later loss replacement through branch, switch, for,
  and while contexts, plus strategy state/history reads around the delayed loss
  fill.
- Added Phase N Slice 4 runtime fixtures and compatibility metadata for
  `strategy.exit(id, from_entry, profit=ticks)` and
  `strategy.exit(id, from_entry, loss=ticks)`. Profit/loss exits convert
  positive tick distances from the current long average entry price using the
  fixed default `syminfo.mintick`, reuse the Phase M pending-exit lifecycle,
  and keep combined trigger forms unsupported.
- Closed Phase M for the current fixture-backed `strategy.exit` subset. The
  audit records supported stop-only and limit-only full-position exits,
  unchanged public runtime `schemaVersion: 3` behavior, host coverage,
  maintenance tails, and release-gate verification.
- Completed Phase M Slice 7 public contract hardening without a runtime schema
  bump. Existing strategy `orders`, `trades`, `position`, `equity`, and
  `diagnostics` fields fully represent filled stop/limit exits across CLI,
  Python, and WASM, with no pending-order or exit-reason public fields added.
- Hardened Phase M Slice 6 strategy-exit interactions. Runtime fixtures now
  cover exit placement through branch, switch, for, and while contexts plus
  strategy state/history reads around an exit fill, and incremental append
  execution checks the new fixture.
- Closed Phase M Slice 5 with combined stop/limit exits intentionally
  unsupported. Stop-only and limit-only exits remain the supported deterministic
  subsets; combined brackets need an explicit same-bar high/low precedence
  policy before compatibility can be claimed.
- Added Phase M Slice 4 limit-exit fills. The supported `strategy.exit` subset
  now includes `strategy.exit(id, from_entry, limit=price)` for full-position
  long exits, triggering on later historical bars when `high >= limit` and
  sharing the same order, trade, position, equity, CLI, Python, and WASM
  contract as stop exits.
- Added Phase M Slice 3 stop-exit fills. The supported
  `strategy.exit(id, from_entry, stop=price)` subset now creates or replaces a
  full-position pending stop for the matching current long entry, fills on a
  later historical bar when `low <= stop`, records a `strategy.exit` order event
  plus closed trade, and is covered through CLI snapshots, Python bindings, and
  WASM JSON.
- Added Phase M Slice 2 broker-owned pending state for stop-only
  `strategy.exit`. Accepted calls now place or replace one internal pending
  stop for the matching current long entry, `strategy.close(id)` cancels that
  pending exit, and missing or mismatched entries produce a stable strategy
  diagnostic without changing the public runtime output shape.
- Added Phase M Slice 1 semantic staging for stop-only `strategy.exit`. The
  analyzer accepts `strategy.exit(id, from_entry, stop=price)` in strategy-mode
  scripts and keeps unsupported exit variants diagnostic-only before executable
  fills are claimed.
- Locked Phase M Slice 0 strategy-exit boundaries. The decision record selects
  stop-only `strategy.exit` as the first executable target, keeps combined,
  requested-context, and function-side-effect exit forms fixture-backed
  unsupported, and avoids public strategy schema changes before runtime support
  lands.
- Closed Phase L for the current strategy usability subset. The audit records
  supported strategy state variables, fixed default quantity behavior, public
  host coverage, `strategy.exit` design boundaries, remaining maintenance tails,
  and release-gate verification.
- Completed Phase L Slice 5 as a `strategy.exit` design gate. Stop, limit,
  profit/loss, trailing, partial quantity, and missing-entry exit forms now have
  explicit unsupported fixtures, and no pending-order or exit schema fields are
  added.
- Added Phase L Slice 4 fixed default quantity support. Strategy declarations
  now accept `default_qty_type=strategy.fixed` with positive const numeric
  `default_qty_value`; `strategy.entry(id, strategy.long)` uses that default,
  while explicit `qty` continues to override it.
- Hardened Phase L Slice 3 strategy variable interactions. The supported
  position/profit/equity state variables now have fixture-backed behavior in
  branches, switches, loops, pure UDF arguments, constant history references,
  incremental append execution, profile retention, and public host smoke tests;
  mutation and requested-context usage remain rejected.
- Added Phase L Slice 2 profit and equity state variables. Strategy-mode
  historical scripts can read and plot `strategy.openprofit`,
  `strategy.netprofit`, and `strategy.equity` for the current long-only broker
  subset. Expression-time `strategy.netprofit` is realized closed-trade profit
  only; the existing public strategy snapshot field `netProfit` remains
  `equity - initial_capital` and can include open profit while a position is
  open.
- Added Phase L Slice 1 position state variables. Strategy-mode historical
  scripts can read and plot `strategy.position_size` and
  `strategy.position_avg_price`; values follow the current long-only broker
  state and update immediately after supported entry/close calls.
- Locked Phase L Slice 0 strategy state-variable boundaries. Known Phase L
  strategy variables now have fixture-backed pre-implementation diagnostics, and
  broad `strategy.*` remains unsupported for unimplemented state/reporting
  helpers.
- Closed Phase G for the first fixture-backed strategy runtime subset. The
  audit records the supported declaration, long entry, full close, trade,
  position, and equity surface plus explicit maintenance tails for richer order
  types, broker settings, strategy variables, alerts, and realtime broker
  rollback.
- Added Phase G Slice 5 strategy equity snapshots and basic
  `initial_capital` handling. Strategy declarations accept positive const
  numeric `initial_capital`, long entry/close accounting updates cash, and the
  public strategy result now includes per-bar `cash`, `marketValue`, `equity`,
  and `netProfit` snapshots.
- Added Phase G Slice 4 minimal `strategy.close` support. Strategy scripts can
  fully close an existing long entry at the current bar close and receive a
  deterministic closed-trade record with entry/exit bars, prices, quantity, and
  profit; missing or repeated closes are no-ops.
- Added Phase G Slice 3 minimal `strategy.entry` support. Strategy scripts can
  open one long market position with `strategy.entry(id, strategy.long, qty=...)`
  filled at the current bar close; repeated entries are ignored under the
  current no-pyramiding rule, and short/stop/limit/indicator-mode variants
  remain rejected by semantic diagnostics.
- Added Phase G Slice 2 strategy runtime/output scaffolding. Strategy-mode
  scripts now return an empty `strategy` result contract with `orders`,
  `trades`, `position`, `equity`, and `diagnostics` arrays across CLI, Python,
  and WASM, while indicator output keys remain unchanged and order functions
  remain unsupported.
- Added Phase G Slice 1 strategy declaration scaffolding. `strategy(...)` is
  accepted as a declaration-only partial feature with strategy HIR mode
  metadata, while strategy order functions remain unsupported.
- Locked Phase G Slice 0 unsupported diagnostics for the reserved strategy
  surface. `strategy(...)`, `strategy.entry`, `strategy.exit`, and
  `strategy.close` now use fixture-backed `E_UNSUPPORTED_FEATURE` diagnostics
  while `strategy.*` remains unsupported in the conformance matrix.
- Closed Phase J for the fixture-backed libraries/imports/user-types/methods
  subset. The closeout audit records supported host-provided import behavior,
  local scalar UDTs, pure local UDT methods, and explicit maintenance tails.
- Locked Phase J Slice 9 imported UDT/method boundaries. Imported UDT identity
  and imported methods remain unsupported maintenance tails while source-graph
  imports continue to support exported constants and pure functions only.
- Added Phase J Slice 8 user-defined methods for pure methods on local UDT
  receivers with scalar parameters. Calls lower through the existing inlined
  function-body path with the receiver as the first internal parameter; side
  effects, recursion, imported methods, unknown receivers, and unsupported
  parameter families remain rejected.
- Clarified Phase J Slice 7 UDT storage semantics. Local UDT values are
  immutable, may be stored in ordinary variables and `var`, and roll back with
  confirmed `var` state during realtime forming updates. UDT `varip`, history
  references, and field mutation remain diagnostic-only unsupported forms.
- Added Phase J Slice 6 local user-defined type support for top-level scalar
  field declarations, `Type.new(...)` constructors, and field reads. UDT
  history references, field mutation, nested UDT fields, arrays of UDTs,
  imported UDTs, and advanced method forms remain unsupported.
- Added Phase J Slice 5 host parity for imported functions. CLI integration
  fixtures now run the import subset through `--library-source`, Python binding
  tests cover imported function execution through `library_sources`, and WASM
  exposes deterministic JSON library source maps via
  `compileScriptWithLibraries`, `analyzeScriptWithLibraries`, and
  `runScriptCsvWithLibraries`.
- Added Phase J Slice 4 executable import subset. Host-provided exact-key
  imports with aliases can now use exported const expressions and pure exported
  functions through `alias.name`; imported functions reuse existing UDF
  lowering/runtime behavior, including independent callsite state. The import
  conformance row is now `partial`; unaliased imports, missing host sources,
  private or unknown exports, non-const exported constants, side-effecting
  exported functions, re-exports, imported UDTs, and imported methods remain
  rejected.
- Added Phase J Slice 3 module graph validation while keeping imports
  non-executable. Analysis now validates host-provided library sources for
  missing import keys, duplicate root aliases, invalid library declarations,
  duplicate exports, dependency cycles, unknown exports, and private symbol
  access.
- Added Phase J Slice 2 parser structure for imports, library declarations,
  export declarations, user-defined type declarations, and user-defined method
  declarations. These nodes now preserve import keys, aliases, declaration
  names, fields, method parameters, bodies, and spans for future source-graph
  analysis.
- Added Phase J Slice 1 source graph scaffolding: `AnalysisInput`,
  deterministic source ids, normalized library source keys, duplicate/invalid
  key rejection, and compile-cache keys that include host-provided library
  source text. CLI now accepts repeated `--library-source KEY=path.pine`
  options for `analyze` and `run`; Python accepts `library_sources` dictionaries
  on `compile_script`, `analyze_script`, and `run_script`; WASM parity is
  covered by the later Slice 5 host contract.
- Started Phase J Slice 0 by locking the diagnostic-only boundary for
  `library`, `export`, user-defined type declarations, and user-defined method
  declarations with unsupported sema fixtures and conformance rows. Method
  calls outside later fixture-backed array and local UDT method subsets remain
  ordinary receiver/type diagnostics.
- Closed Phase I with `docs/PHASE_I_AUDIT.md`, fixture-backed scalar and scalar
  typed-array `varip` conformance rows, host-surface review for CLI/Python/WASM
  historical paths, and explicit maintenance tails for drawing ids, tuples,
  maps, matrices, UDTs, imports, and unimplemented value families.
- Added the scalar and scalar typed-array `varip` executable subset: global and
  local int/float/bool/string/color/`na` declarations now behave like `var`
  during historical execution and preserve intrabar state across repeated
  realtime forming updates. Supported float/int/bool/string/color array ids also
  retain their backing contents across repeated forming updates, including
  branch-local declaration sites and `array.copy` boundaries. Array mutation
  inside UDFs remains rejected by existing function side-effect rules. Drawing
  ids are rejected with a dedicated diagnostic because object stores still roll
  back; tuples and other value families remain unsupported.
- Added the first `request.security` executable subset:
  `request.security(syminfo.tickerid, timeframe.period, expression)` returns the
  scalar side-effect-free expression in the current chart context.
- Added same-or-higher-timeframe host dataset injection for
  `request.security("SYMBOL", timeframe, expression)` lookups in Rust
  runtime, CLI `--request-bars SYMBOL:TIMEFRAME=bars.csv`, and Python
  `request_bars` dictionaries. WASM request dataset injection was a documented
  temporary Phase F gap and is now closed for this subset by Phase T; optional
  parameters, explicit gaps/lookahead, and lower timeframe requests remain
  unsupported.
- Widened provider-backed `request.security` to evaluate scalar requested
  expressions in an isolated requested context with deterministic callsite
  caching and default higher-timeframe `gaps_off`/`lookahead_off` alignment.
  The supported provider expression subset now includes direct OHLCV/time
  sources, pure arithmetic and ternaries, history references, `na`, `nz`,
  `ta.sma`, and `ta.ema`; provider local aliases, side effects, and unsupported
  calls are rejected during semantic analysis where possible.
- Documented the lower-timeframe request boundary: lower-timeframe
  `request.security` remains runtime-rejected with a stable error, and
  `request.security_lower_tf` remains unsupported until typed array return
  semantics and host output shapes are designed.
- Added cross-host request contract fixtures for CLI and Python request dataset
  injection, plus conformance validation that prevents partial `request.*`
  claims without request-specific fixtures. WASM request dataset injection was
  the remaining temporary host gap until the Phase T JSON host shape.
- Closed Phase F with `docs/PHASE_F_AUDIT.md`, fixture-backed request matrix
  rows, same-or-higher-timeframe request contract coverage across Rust, CLI,
  and Python, plus a documented WASM provider-data gap later closed by Phase T.
- Started Phase E drawing-object infrastructure by bumping the public
  machine-readable contract to `schemaVersion: 2` and adding the
  top-level `labels` output across CLI JSON, Python dictionaries, and WASM JSON.
  It is empty for scripts that do not create supported drawing objects.
- Added the first drawing behavior: a `label.new` creation subset that returns
  deterministic label ids and emits sparse creation snapshots with bar-index
  coordinates, price y-values, text, colors, selected label styles, size, and
  tooltip metadata.
- Added sparse mutation snapshots for the initial `label.set_*` subset covering
  x/y/text/color/style/size/tooltip fields.
- Added `label.delete` lifecycle snapshots. Label creation, mutation, and
  deletion now have fixture-backed realtime rollback, and drawing side effects
  inside user-defined functions are rejected under the existing side-effect
  policy. Unsupported coordinate modes
  and advanced label methods remain unsupported.
- Added the initial `line.*` lifecycle: deterministic line ids, sparse public
  `lines` snapshots for creation/mutation/deletion, selected endpoint/color/
  width/style/extend mutators, realtime rollback coverage, and an effective
  default/declaration-driven max-count eviction path. Advanced line methods
  remain unsupported.
- Added the initial `box.*` lifecycle: deterministic box ids, sparse public
  `boxes` snapshots for creation/mutation/deletion, selected geometry/
  background/border mutators, and realtime rollback coverage. Advanced box
  methods remain unsupported.
- Added the initial `table.*` lifecycle: deterministic table ids, sparse public
  `tables` snapshots for fixed-dimension table creation and `table.cell`
  text/background/text-color writes, realtime rollback coverage, a
  deterministic 50-table runtime limit, and a 1000-cell per-table limit.
  Advanced table methods plus polyline drawing families remain unsupported.
- Kept `polyline.*` explicitly unsupported for Phase E because it depends on a
  future `chart.point` value and point-array design; the decision is captured in
  `docs/PHASE_E_POLYLINE_GATE.md`.
- Closed Phase E with `docs/PHASE_E_AUDIT.md`, fixture-backed drawing matrix
  rows, schemaVersion 2 drawing output coverage across CLI/Python/WASM, and
  family-split runtime drawing built-ins.
- Closed Phase K release infrastructure with public `schemaVersion: 1` output
  contracts for CLI, Python, and WASM public machine-readable outputs.
- Moved CLI and WASM runtime JSON onto shared runtime serialization helpers,
  with Python binding tests asserting the same public runtime key contract.
- Added golden JSON snapshots for representative CLI runtime output, CLI matrix
  JSON, and WASM analysis JSON.
- Hardened `tests/fixtures/conformance.tsv` validation so compatibility matrix
  claims require unique features, valid statuses, notes, existing fixtures, and
  status-appropriate fixture coverage.
- Added `scripts/verify.sh` as the canonical local and CI release verification
  entry point.
- Added deterministic runtime profile fixture gates for long TA histories,
  many stateful callsites, array-heavy scripts, and dynamic history retention.
- Added partial `switch` expression support for condition arms, selector/case
  arms, expression results, default arms, and conditional stateful-call
  execution.
- Added partial `while` statement support with bool conditions, `break`,
  `continue`, scoped loop bodies, and a runtime iteration guard.
- Added coverage for stateful callsite advancement inside `for` and `while`
  loop bodies.
- Added `ta.supertrend` line/direction tuple support for the fixture-covered
  ATR-based subset.
- Added `ta.dmi` `+DI`/`-DI`/`ADX` tuple support using the runtime's existing
  Wilder/RMA-style smoothing behavior.
- Added `ta.sar` Parabolic SAR support with callsite state and prior-bar
  high/low clamping.
- Added `ta.mfi` Money Flow Index support over ready positive/negative
  money-flow windows using source and volume.
- Added `ta.tsi` True Strength Index support using short/long EMA smoothing of
  source momentum and absolute momentum.
- Added `ta.cmo` Chande Momentum Oscillator support over ready rolling
  positive/negative source-change windows.
- Added `ta.cci` Commodity Channel Index support over ready source mean
  deviation windows.
- Added `ta.cog` Center of Gravity support over ready source windows.
- Added `ta.ao` Awesome Oscillator support as the fast/slow SMA spread of
  median price.
- Added `ta.bop` Balance of Power support over current OHLC values.
- Added `ta.kc` and `ta.kcw` Keltner Channel support using source/range EMA
  state.
- Added `ta.pivothigh` and `ta.pivotlow` support for confirmed left/right pivot
  windows.
- Added `ta.pivot_point_levels` support for runtime-bar anchored pivot level
  arrays across Traditional, Fibonacci, Woodie, Classic, DM, and Camarilla
  formulas.
- Added `ta.wpr` Williams %R support over ready rolling high/low windows and
  current close.
- Added `ta.stoch` four-argument stochastic oscillator support over ready
  rolling high/low windows.
- Added partial float array support with runtime-owned array ids,
  `array.new_float`, `array.push`, `array.get`, `array.set`, `array.size`,
  `array.pop`, and `array.clear`.
- Added partial int array support through `array.new_int` and the existing
  size/get/set/push/pop/clear operations.
- Added partial bool array support through `array.new_bool` and the existing
  size/get/set/push/pop/clear operations.
- Added partial string array support through `array.new_string` and the
  existing size/get/set/push/pop/clear operations.
- Added partial color array support through `array.new_color` and the existing
  size/get/set/push/pop/clear operations.
- Added `array.from` support for inferred float/int/bool/string/color typed
  arrays.
- Added array helper support for `array.first`, `array.last`, `array.shift`,
  and `array.unshift` across supported typed arrays.
- Added `array.insert` and `array.remove` support for supported typed arrays,
  including method-call syntax and array element limit checks.
- Added negative indexing support for `array.get`, `array.set`,
  `array.insert`, and `array.remove`.
- Added `array.fill` support for supported typed arrays, including optional
  half-open range bounds and method-call syntax.
- Added `array.copy` support for explicitly creating independent typed-array
  snapshots while plain array assignment remains id/reference-based.
- Added array search helpers `array.includes`, `array.indexof`,
  `array.lastindexof`, and numeric `array.binary_search*` variants.
- Added array truth helpers `array.every` and `array.some` for float, int, and
  bool arrays.
- Added numeric array statistics helpers `array.min`, `array.max`,
  `array.sum`, `array.avg`, `array.range`, `array.median`, `array.mode`,
  `array.percentile_nearest_rank`, `array.percentile_linear_interpolation`,
  `array.percentrank`, `array.covariance`, `array.standardize`,
  `array.variance`, and `array.stdev`, plus same-kind `array.abs`, for float
  and int arrays.
- Added array ordering helpers: `array.sort` for numeric/string arrays with
  optional order direction, `array.sort_indices` for numeric/string arrays with
  optional order direction, and `array.reverse` for all supported typed arrays.
- Added `array.join` support for supported typed arrays with optional string
  separators.
- Added `array.slice` and `array.concat` support for supported typed arrays,
  including method-call syntax and array element limit checks.
- Added partial array method-call syntax for supported array `size`, `get`,
  `set`, `insert`, `push`, `pop`, `remove`, `shift`, `unshift`, `first`,
  `last`, `fill`, `copy`, `slice`, `concat`, `includes`, `indexof`,
  `lastindexof`, `every`, `some`, numeric `binary_search*`, `min`, `max`,
  `sum`, `avg`, `range`, `median`, `mode`, `percentile_nearest_rank`,
  `percentile_linear_interpolation`, `percentrank`, `variance`, `stdev`,
  `sort`, `reverse`, `join`, and `clear`.
- Added `input.string` support for the executable `defval`/`title` subset.
- Added `input.price`, `input.time`, `input.symbol`, and `input.timeframe`
  support for the executable `defval`/`title` subset.
- Added generic `input` support for const int, float, bool, string, and color
  defaults.
- Added common `input.*` metadata parameters, including min/max/step,
  `options`, `tooltip`, `inline`, `group`, `confirm`, and `display` where they
  fit the supported input kinds.
- Added UTC-derived `year`, `month`, `dayofmonth`, `hour`, `minute`, and
  `second` bar time component variables.
- Added UTC-only function overloads for `year`, `month`, `dayofmonth`, `hour`,
  `minute`, and `second`.
- Added a numeric UTC subset of `timestamp`.
- Added `barstate.isfirst`, `barstate.islast`, `barstate.isnew`,
  `barstate.isconfirmed`, `barstate.ishistory`, and `barstate.isrealtime`.
- Added fixed-default regular-session `session.ismarket`,
  `session.ispremarket`, and `session.ispostmarket`.
- Added `session.regular` and `session.extended` named string constants for
  the current fixed-default session metadata subset.
- Added `bgcolor` and `barcolor` support with bar-aligned color output series.
- Added common `plot`, `hline`, `fill`, `bgcolor`, and `barcolor` metadata
  parameters for style/display compatibility; runtime output series remain
  unshifted by display metadata in this subset.
- Added basic `plotchar` support with bar-aligned values, chars, and colors.
- Expanded `plotchar` compatibility with common marker metadata parameters;
  runtime output remains normalized to value, char, and color series.
- Expanded `plotshape` and `plotarrow` compatibility with common marker
  metadata parameters while preserving the existing normalized output schemas.
- Expanded `plotbar` and `plotcandle` compatibility with common display
  metadata parameters while preserving existing OHLC output schemas.
- Added `color.from_gradient` with fixture-covered linear RGBA interpolation.
- Added conformance coverage for hex color literals as const colors.
- Added `input.session` and `input.text_area` defval execution with metadata
  validation.
- Added direct `display.pane`, `display.price_scale`, `display.status_line`,
  and `display.data_window` metadata constants.
- Accepted `confirm` metadata on `input.source`.
- Added explicit `str.tostring` handling for `format.price` and
  `format.volume`.
- Added dedicated conformance coverage for global OHLCV, derived price
  (`hl2`, `hlc3`, `hlcc4`, `ohlc4`), time, and `bar_index` series.
- Added basic `plotshape` support with bar-aligned values, style, location,
  color, text, text color, and size marker output.
- Added basic `plotarrow` support with bar-aligned numeric values, up/down
  colors, and height bounds.
- Added basic `plotbar` support with bar-aligned OHLC values and optional
  colors.
- Added basic `plotcandle` support with bar-aligned OHLC values plus body,
  wick, and border colors.
- Added `color.rgb` support for numeric RGB channels and optional transparency.
- Added optional transparency defaulting for `color.new`.
- Added `color.r`, `color.g`, `color.b`, and `color.t` channel extraction.
- Added `str.length`, `str.upper`, and `str.lower` string helpers.
- Added `str.contains`, `str.startswith`, and `str.endswith` string predicates.
- Added `str.pos` and `str.substring` string extraction helpers.
- Added `str.trim` and `str.repeat` string modification helpers.
- Added `str.replace` and `str.replace_all` string replacement helpers.
- Added `str.tonumber` numeric string parsing.
- Added `str.tostring` scalar and float-array string conversion.
- Added `str.format` indexed placeholder string formatting.
- Added `str.match` regex substring matching.
- Added `str.split` support for literal separators and empty-separator
  character splitting.
- Added a UTC subset of `str.format_time` timestamp formatting.
- Added UTC `weekofyear` and `dayofweek` calendar variables/functions plus
  `dayofweek.*` constants.
- Added fixed-default `time_close` using the current 1-minute chart timeframe
  subset.
- Added fixed-default `timeframe.period` and `timeframe.in_seconds` support for
  common seconds/minutes/days/weeks/months timeframe strings, plus
  `timeframe.from_seconds` for the exact reverse conversion subset.
- Added fixed-default `timeframe.main_period` support for the current
  single-chart-timeframe runtime subset.
- Added `timeframe.change` UTC bucket detection for the supported timeframe
  string subset.
- Added fixed-default `timeframe.is*` and `timeframe.multiplier` chart
  timeframe metadata.
- Added `int`, `float`, `bool`, `string`, and `color` scalar type casts for
  numeric, bool, string, color, and `na` values.
- Added `fixnan` support for carrying forward the last non-`na` numeric or
  color value at each callsite.
- Added `math.floor` and `math.ceil` support for numeric values.
- Added `math.sqrt`, `math.log`, and `math.pow` support for numeric values.
- Added `math.trunc`, `math.cbrt`, and `math.hypot` support for numeric
  values.
- Added `math.sin`, `math.cos`, and `math.tan` support for numeric values.
- Added `math.log10` and `math.exp` support for numeric values.
- Added `math.acos`, `math.asin`, and `math.atan` support for numeric values.
- Added `math.sign`, `math.todegrees`, and `math.toradians` support for numeric values.
- Added `math.avg` support for variadic numeric averages.
- Added `math.e`, `math.pi`, `math.phi`, and `math.rphi` constants.
- Added `precision` argument support for `math.round`.
- Added `math.round_to_mintick` support using the current default
  `syminfo.mintick` subset value.
- Added fixed-default `syminfo.*` metadata for common ticker, exchange,
  currency, session, timezone, tick-size, and price-scale fields.
- Added deterministic callsite-backed `math.random` support with optional
  `min`, `max`, and `seed` arguments.
- Added `math.sum` support for rolling source sums with simple-int lengths.
- Added `ta.stdev` support with default biased and optional sample standard
  deviation modes.
- Added `ta.variance` support with the same biased/sample window modes as
  `ta.stdev`.
- Added `ta.range` support for rolling highest-minus-lowest values.
- Added `ta.dev` support for rolling average absolute deviation.
- Added `ta.vwma` support for rolling volume-weighted moving averages.
- Added `ta.wma` support for linearly weighted moving averages.
- Added `ta.hma` support for Hull moving averages composed from internal WMA
  windows.
- Added `ta.swma` support for fixed four-bar symmetric weighted moving
  averages.
- Added `ta.alma` support for Arnaud Legoux moving averages with optional
  floored offset centers.
- Added `ta.dema` and `ta.tema` support for double and triple EMA-chain
  smoothing.
- Added `ta.linreg` support for rolling least-squares linear regression values.
- Added `ta.bbw` support for Bollinger Bands Width values.
- Added `ta.cum` support for cumulative numeric source sums.
- Added `ta.max` and `ta.min` support for all-time source extremes.
- Added `ta.tr` support as a built-in true range series variable.
- Added `ta.accdist` support as the built-in Accumulation/Distribution index
  series variable.
- Added `ta.iii` support as the built-in Intraday Intensity Index series
  variable.
- Added `ta.nvi` and `ta.pvi` support as built-in Negative/Positive Volume
  Index series variables.
- Added `ta.obv` support as the built-in On Balance Volume series variable.
- Added `ta.pvt` support as the built-in Price Volume Trend series variable.
- Added partial `ta.vwap` support for the variable form, one-argument source
  call, source/anchor call, and source/anchor/bands tuple call as runtime-bar
  cumulative VWAP; session-derived anchoring remains future work.
- Added `ta.wad` support as the built-in Williams Accumulation/Distribution
  series variable.
- Added `ta.wvad` support as the built-in Williams Variable
  Accumulation/Distribution series variable.
- Added `ta.mom` support for source momentum over explicit history lengths.
- Added `ta.roc` support for rate-of-change percentages over explicit history
  lengths.
- Expanded `ta.change` to support series int and bool sources.
- Expanded core TA source signatures to accept series int sources where the
  runtime already evaluates numeric windows through floating-point values.
- Added explicit fixture coverage for simple numeric sources in rolling
  correlation, covariance, median, mode, percentile, and percent-rank helpers.
- Added `ta.correlation` support for rolling Pearson correlation coefficients.
- Added `ta.covariance` support for rolling population covariance values.
- Added `ta.median` and `ta.mode` support for rolling sorted-window statistics.
- Added `ta.percentile_nearest_rank` support for rolling nearest-rank
  percentile values.
- Added `ta.percentile_linear_interpolation` support for rolling interpolated
  percentile values.
- Added `ta.percentrank` support for rolling percent-rank values.
- Added `ta.rising` and `ta.falling` support for current-vs-previous-window
  trend checks.
- Added two-argument `ta.highestbars` and `ta.lowestbars` support for rolling
  extreme offsets.
- Added `ta.barssince` support for tracking bars elapsed since the last true
  condition.
- Added `ta.valuewhen` support for retrieving source values from prior true
  condition occurrences.
- Added length-only overloads for `ta.highest`, `ta.lowest`,
  `ta.highestbars`, and `ta.lowestbars`.
- Tightened float array UDF boundaries: read-only array operations are allowed,
  while array mutation inside UDFs is rejected as a side effect.
- Added a 100,000-element runtime guard for each float array.

## v0.1 Baseline

This release establishes the first executable Pine-compatible indicator subset.
Compatibility claims are backed by `tests/fixtures/conformance.tsv`; run
`pine-compat matrix` or `pine-compat matrix --format json` to inspect the
feature-level matrix and its fixture paths.

Machine-readable public outputs use top-level `schemaVersion`. Runtime,
analysis, and matrix outputs now have separate schema constants:
`PUBLIC_RUNTIME_SCHEMA_VERSION`, `PUBLIC_ANALYSIS_SCHEMA_VERSION`, and
`PUBLIC_MATRIX_SCHEMA_VERSION`. Runtime output is now `schemaVersion: 5` with a
reserved top-level `alerts` array, strategy order-fill payloads under
`strategy.alerts`, and host-neutral table cell `textWrap`. Analysis and matrix
outputs remain `schemaVersion: 2`;
increment only the affected contract when an intentional consumer-visible
output change is documented with snapshot updates.

### Runtime Surfaces

- Rust crates for syntax, semantic analysis, HIR, built-ins, runtime, CLI,
  Python bindings, and WASM bindings.
- CLI commands for analysis, AST formatting, historical execution, profiling,
  and compatibility matrix output.
- Python binding exposing compile, analyze, and run entry points.
- WASM binding exposing compile, analyze, and CSV execution entry points.
- Public JSON/dictionary outputs for CLI, Python, and WASM expose
  `schemaVersion`; CLI and WASM runtime JSON share the same runtime contract
  helper.
- Runtime outputs include an `alerts` array for Phase H alert events.
  `alertcondition(condition, title, message)` is partially supported for
  bool-compatible conditions and const-string title/message, and
  `alert(message, freq?)` is partially supported for const-string messages and
  the fixture-backed `alert.freq_once_per_bar`/`alert.freq_all`/
  `alert.freq_once_per_bar_close` frequency subset. Reached true conditions and
  reached alert calls emit deterministic `{id, barIndex, time, message,
  source}` events in program order; forming realtime events roll back until
  confirmed, and close-frequency alert calls emit only on historical or
  confirmed realtime bar-close execution. TradingView-style placeholder
  interpolation remains unsupported until deterministic semantics are designed.
- The compatibility matrix source of truth is
  `tests/fixtures/conformance.tsv`; generated text and JSON matrix output must
  remain fixture-backed.

### Supported Executable Subset

- Indicator scripts over OHLCV bar input.
- Historical bar-by-bar execution and incremental append execution.
- Realtime forming-bar rollback for output, `var`, and stateful callsite state.
- Constant non-negative history references.
- Normal declarations, reassignment, tuple declarations, tuple-returning
  built-ins, and tuple `for` expression results.
- `if`/`else` blocks, nested blocks, and conditional stateful calls that advance
  only when their branch executes.
- `for` loops over inclusive integer ranges, explicit non-zero `by` steps,
  `break`, `continue`, scalar loop results, and tuple loop results.
- Local scopes for block declarations, tuple declarations, shadowing, and local
  `var` declaration-site storage.
- User-defined functions with expression bodies and multi-statement block
  bodies, positional and named arguments, single evaluation of arguments,
  function-local declarations, local `var`, loops inside functions, and
  independent state per syntactic callsite.
- `na`, `nz`, `indicator`, `input.*`, `plot`, `hline`, `fill`, `color.new`,
  selected named colors, selected `math.*` functions, and the fixture-covered
  `ta.*` built-ins listed in the compatibility matrix.
- Typed scalar arrays for float, int, bool, string, and color through the
  fixture-covered `array.*` subset documented as partial in the matrix.

### Partial Support

- `for`: supports inclusive integer ranges, loop control, and loop results, but
  does not claim full Pine loop compatibility.
- `history references`: supports constant non-negative offsets and guarded
  dynamic integer offsets, including `series int`, loop-produced offsets, and
  user-defined function parameters.
- `max_bars_back`: supports indicator/strategy-level constant non-negative
  retention bounds for dynamic history, plus top-level
  `max_bars_back(source, num)` helper calls for simple series identifiers.
- `color.*` named constants: supports the current common registry only.
- `realtime forming rollback`: covers output, alert events,
  supported drawing objects, `var`, scalar and scalar typed-array `varip`,
  callsite, array, and dynamic history rollback.

### Explicitly Unsupported

The analyzer rejects these boundaries with diagnostics instead of approximating
them silently:

- `varip` drawing ids, tuple `varip`, and `varip` value families outside the
  scalar and scalar typed-array subset.
- `request.*` multi-symbol and multi-timeframe data requests.
- `strategy.*` broker emulation and backtesting.
- Generic arrays, object arrays, user-defined type arrays, matrices, maps, and
  deferred collection semantics that are not fixture-backed in the current
  `array.*` partial subset.
- Imports and external libraries.
- Alert frequency controls.
- Advanced drawing object methods and unsupported `polyline.*` point-list
  object systems.
- Per-variable `max_bars_back` declarations beyond the top-level simple series
  identifier helper subset.
- Recursive user-defined functions.
- User-defined function side effects, including output calls, alerts,
  input declarations, indicator declarations, array mutation, global
  reassignment, and passing side-effecting calls as UDF arguments.

### Verification

The release baseline is expected to pass:

```text
scripts/verify.sh
```

Snapshot updates are intentional public-contract changes. Refresh them with the
commands in `docs/CONFORMANCE.md`, review the JSON diff, then run
`scripts/verify.sh`.
