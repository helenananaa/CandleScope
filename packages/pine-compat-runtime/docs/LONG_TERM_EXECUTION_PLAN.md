# Long-Term Execution Plan

This document tracks the remaining compatibility work after the current
indicator-focused baseline. It is intentionally broader than the next-stage
playbook: use it to choose future phases, but continue to land changes through
small, fixture-backed increments.

The current rule remains unchanged: a feature is only claimed in
`tests/fixtures/conformance.tsv` when syntax, semantic analysis, runtime
behavior, public outputs, docs, and fixtures all agree.

## Current Baseline

Implemented or partially implemented:

- Historical indicator execution over OHLCV bars.
- Incremental append-bar execution.
- Realtime forming-bar rollback for outputs, `var`, callsite state, and float
  arrays.
- `if`/`else`, local scopes, tuple declarations, reassignment, and local `var`
  declaration-site storage.
- User-defined functions with expression bodies, block bodies, positional and
  named arguments, local declarations, loops inside functions, and independent
  callsite state.
- Partial `switch` expressions.
- Partial `for` and `while` loops.
- Constant non-negative history offsets and guarded dynamic integer offsets,
  including `series int`.
- Partial float/int/bool/string/color/label/line/linefill/box/table/chart.point
  arrays, reference assignment, `array.from`, `array.copy`, negative indexes for
  `array.get`/`array.set`/`array.insert`/`array.remove`, `array.slice`,
  `array.concat`, `array.fill`, search/binary search helpers, truth helpers,
  numeric abs/statistics/range/median/mode/percentile/covariance/standardize/variance/stdev
  helpers, queue/end helpers, numeric/string ordering helpers including
  `array.sort_indices`, `array.join`, and supported array method calls. The
  current scalar array pass is closed in `docs/ARRAY_STAGE_AUDIT.md`; `array.*`
  remains partial because general generic, polyline, UDT, matrix/map, history,
  and advanced aliasing semantics are still out of scope.
- A fixture-covered set of `input.*`, output calls, color helpers, math
  helpers, and `ta.*` functions. The main built-in coverage pass is closed in
  `docs/PHASE_D_AUDIT.md`; further built-in work should be maintenance unless
  a later phase needs it.
- Partial alert events for `alertcondition()` and `alert()` with a versioned
  public `alerts` runtime output. The Phase H alert subset is closed in
  `docs/PHASE_H_AUDIT.md`; `alert.freq_once_per_bar`, `alert.freq_all`, and
  `alert.freq_once_per_bar_close` are supported for const-string `alert()`
  frequency, and `alertcondition` messages support fixture-backed OHLCV plus
  ticker/interval/exchange/time placeholders, while broader placeholders, host
  delivery, and strategy alerts remain out of scope.
- Phase J libraries/user types are closed for the fixture-backed claimed
  subset in `docs/PHASE_J_AUDIT.md`: host-provided exact-key imports expose
  exported const expressions and pure exported functions, local scalar-field
  UDTs support construction, field reads, ordinary variables, and `var`
  persistence, and pure local UDT methods are supported.
- CLI, Python, and WASM surfaces for the supported runtime result model.

Remaining work falls into the phases below.

## Execution Rules

- Add or update fixtures before or alongside implementation.
- Keep unsupported variants diagnostic-only until their behavior is designed.
- Prefer one feature through the full stack over several parser-only changes.
- Preserve deterministic runtime guards for loops and mutable storage.
- Keep public JSON, Python, and WASM output schemas synchronized.
- Update `tests/fixtures/conformance.tsv` only after fixture coverage exists.
- Run the full verification set before calling a phase complete.

Recommended verification:

```text
git diff --check
scripts/verify.sh
```

## Phase A: Loop and Branch Hardening

Status: complete for the current executable subset. See
`docs/LOOP_BRANCH_AUDIT.md`.

Goal: turn the current partial loop support into a more reliable Pine subset
before adding larger runtime systems.

Scope:

- Broaden `for` fixtures for zero-iteration behavior, `na` loop bounds, step
  direction edge cases, nested loops, loop counter shadowing, and loop results.
- Broaden `while` fixtures for `na` conditions, nested loop control, local
  declarations, local `var`, and stateful calls inside loop bodies. Initial
  coverage exists; keep adding real-script cases as gaps appear.
- Add more branch interaction fixtures: `if` inside loops, loops inside `if`,
  `switch` inside loops, and loops inside UDFs. Initial coverage exists; keep
  adding real-script cases as gaps appear.
- Keep `while` expression results rejected until a dedicated expression-result
  design exists.
- Keep statement-block `switch` arms rejected until block-arm scoping and
  result semantics are designed.

Out of scope:

- Per-variable `max_bars_back` declarations and inference.
- Object systems.
- Multi-timeframe data.

Acceptance criteria:

- Runtime fixtures cover nested loop control and stateful calls inside loops.
- Incremental append execution matches full historical execution for all new
  loop fixtures.
- Diagnostics remain stable for unsupported loop forms.
- `for`, `while`, and `switch` conformance notes describe the exact supported
  subset.

Suggested commits:

1. `Harden for loop edge cases`
2. `Harden while loop edge cases`
3. `Cover loop branch interactions`
4. `Document loop compatibility boundaries`

## Phase B: Collections Beyond Float Arrays

Goal: expand mutable collection support without breaking the runtime-owned
storage model.

Status: the scalar typed-array subset is fixture-backed and should be treated
as closed for now. Use `docs/ARRAY_STAGE_AUDIT.md` before selecting any further
array work.

Scope:

- Add typed arrays beyond the current float/int/bool/string/color subset:
  source where practical.
- Add common array constructors and helpers after element typing is stable.
- Define copy/reference behavior for array values across assignments,
  function calls, `var`, rollback, and incremental execution.
- Expand method syntax for supported array functions.
- Add precise diagnostics for still-unsupported array operations.

Later candidates:

- Matrices.
- Maps.
- Array sorting/searching/statistical helpers.
- Generic collection behavior if the type system can support it cleanly.

Acceptance criteria:

- Each supported element type has creation, mutation, read, persistence,
  rollback, and UDF-boundary fixtures.
- Unsupported collection variants are rejected during semantic analysis.
- Runtime profiles include enough collection storage information to catch
  uncontrolled growth.

Suggested commits:

1. `Document collection semantics`
2. `Design map collection support`

## Phase C: History and Series Semantics

Goal: make series behavior closer to Pine while keeping static guarantees where
possible.

Status: substantially complete for the current executable subset. The static
and integer dynamic history boundary is recorded in
`docs/HISTORY_SERIES_AUDIT.md`; qualifier findings are recorded in
`docs/QUALIFIER_AUDIT.md`; built-in signature notes were tightened in
`docs/BUILTIN_SIGNATURES.md`. Series-qualified integer history offsets are
supported with runtime guards. Runtime profiles expose max series depth and
history retention mode, and committed series history has a hard runtime cap. HIR
lowering records program-wide and per-series history requirements, runtime
retention trims static-only scripts to those requirements, and
`indicator(..., max_bars_back=N)` bounds dynamic retention.

Remaining follow-up:

- Add clearer diagnostics/profile fields or per-variable `max_bars_back`
  handling for scripts that depend on dynamic history.
- Continue expanding tests around `na`, first-bar behavior, and interactions
  with more built-ins as needed.
- Revisit scalar `simple` inference and qualifier-bound helper APIs if Phase D
  built-ins need stricter qualifier semantics.

Residual risks:

- Dynamic offsets can require deeper history retention and new runtime bounds.
- Future qualifier changes may affect many built-in signatures at once.

Acceptance criteria:

- Any supported dynamic-offset subset has explicit retention limits/profile
  fields and runtime errors for unsafe offsets.
- Built-in signature docs match semantic checks.
- Existing fixture results remain stable unless a deliberate compatibility fix
  is documented.

Suggested commits:

1. `Document history series audit`
2. `Audit qualifier propagation`
3. `Design dynamic history offset support`
4. `Implement guarded dynamic history offsets`
5. `Infer history retention requirements`
6. `Trim static history retention`
7. `Support series history offsets`
8. `Expose history retention profile`
9. `Support indicator max bars back`
10. `Cover dynamic history scopes`
11. `Close Phase C audit`

## Phase D: Built-In Coverage Expansion

Status: closed for the current executable indicator subset. See
`docs/PHASE_D_AUDIT.md`.

Goal: grow useful indicator compatibility through high-value built-ins before
large platform features.

Closed coverage:

- Additional `ta.*` functions. Initial Phase D coverage includes `ta.stdev`
  and `ta.variance` with default biased and optional sample window modes, plus
  `ta.range`, `ta.dev`, `ta.vwma`, `ta.wma`, `ta.hma`, `ta.swma`, `ta.alma`,
  `ta.linreg`, `ta.bbw`, `ta.correlation`, `ta.covariance`, `ta.median`,
  `ta.mode`, `ta.kc`, `ta.kcw`,
  `ta.pivothigh`, `ta.pivotlow`,
  `ta.percentile_nearest_rank`, `ta.percentile_linear_interpolation`, and
  `ta.percentrank` over ready rolling windows, `ta.cum` cumulative sums,
  `ta.cmo` Chande Momentum Oscillator rolling change sums,
  `ta.cci` Commodity Channel Index mean-deviation oscillator,
  `ta.cog` Center of Gravity rolling weighted-ratio oscillator,
  `ta.ao` Awesome Oscillator fast/slow median-price SMA spread,
  `ta.bop` Balance of Power OHLC range oscillator,
  `ta.tsi` True Strength Index double-EMA momentum support,
  `ta.accdist`/`ta.iii`/`ta.nvi`/
  `ta.obv`/`ta.pvi`/`ta.pvt`, partial `ta.vwap` variable/source/anchor/bands
  support,
  `ta.mfi` Money Flow Index support,
  `ta.pivot_point_levels` runtime-bar anchored pivot arrays,
  `ta.max`/`ta.min` all-time source extremes, `ta.tr` as a true range series
  variable, `ta.wad`/`ta.wvad` flow variables, `ta.supertrend`
  line/direction tuple support, `ta.dmi` directional movement tuple support,
  `ta.sar` Parabolic SAR support, and `ta.stoch` stochastic oscillator support,
  `ta.wpr` Williams %R support, `ta.dema`/`ta.tema` EMA-chain smoothing,
  numeric `series int`/`series float` sources across core TA windows,
  `ta.change` over numeric and bool series sources,
  `ta.mom`/`ta.roc` over explicit source history, and
  `ta.rising`/`ta.falling` trend-window checks. It also includes
  source/length and length-only rolling extreme helpers, `ta.barssince`
  condition counters, plus `ta.valuewhen` condition occurrence lookups.
- Additional `math.*` and `str.*` helpers. Initial post-baseline math coverage
  includes `math.floor`, `math.ceil`, `math.sqrt`, `math.log`, `math.log10`,
  `math.exp`, `math.acos`, `math.asin`, `math.atan`, `math.sign`,
  `math.todegrees`, `math.toradians`, `math.sin`, `math.cos`, `math.tan`,
  `math.trunc`, `math.cbrt`, `math.hypot`, `math.avg`, `math.e`, `math.pi`,
  `math.phi`, `math.rphi`, `math.pow`, `math.round`,
  `math.round_to_mintick`, `math.random`, and `math.sum`;
  string coverage includes `str.split`; time
  helper coverage includes numeric and const-dateString IANA-aware `timestamp`,
  IANA-aware calendar
  component functions such as `weekofyear` and `dayofweek`, IANA-aware
  `str.format_time` with short timezone-name tokens, doubled-apostrophe
  literals, `na`-to-epoch timestamps, `1..5` week-of-month and `0..11` 12-hour
  tokens, and complete millisecond-width formatting, and `time`/`time_close`
  subsets with IANA-aware explicit
  time-based sessions and UTC calendar
  week/month higher-timeframe boundaries, plus a fixed-default
  `timeframe.period` and `timeframe.in_seconds`/`timeframe.from_seconds`
  conversion subset, `timeframe.change` fixed intraday/day plus calendar
  week/month UTC bucket detection, plus
  fixed-default `timeframe.is*` and `timeframe.multiplier` metadata.
- Initial utility helper coverage includes `fixnan` for the current numeric
  and color last-non-`na` callsite subset.
- Initial type-cast coverage includes the pure scalar `int`, `float`, `bool`,
  `string`, and `color` numeric/bool/string/color/`na` subset.
- Initial color helper coverage includes `color.from_gradient` linear RGBA
  interpolation and `#RRGGBB`/`#RRGGBBAA` hex color literals.
- Initial symbol metadata coverage includes a fixed-default `syminfo.*` subset
  for common string, tick-size, and price-scale fields.
- Initial `barstate.*` coverage includes `barstate.isfirst`,
  `barstate.islast`, `barstate.isnew`, `barstate.isconfirmed`,
  `barstate.ishistory`, and `barstate.isrealtime`.
- Initial session-state coverage includes fixed-default `session.ismarket`,
  `session.ispremarket`, and `session.ispostmarket`.
- Initial global derived source coverage includes `hl2`, `hlc3`, `hlcc4`, and
  `ohlc4` as bar-local OHLC price series.
- Initial `input.*` metadata coverage accepts common min/max/step, `options`,
  `tooltip`, `inline`, `group`, `confirm`, and `display` parameters while
  executing the `defval` value unless the Rust runtime, CLI, Python, or WASM
  host supplies call-site keyed input overrides. Additional string-like input
  coverage includes `input.session` and `input.text_area`.
- Initial output metadata coverage accepts common style/display/editability
  parameters on `plot`, `hline`, `fill`, `bgcolor`, and `barcolor` without
  changing the normalized runtime output schemas. Direct `display.*` constant
  coverage includes all/none plus pane, price scale, status line, and data
  window values.
- Initial `plotchar` metadata coverage accepts common marker display/style
  parameters while keeping the normalized value/char/color output schema.
- Initial `plotshape`/`plotarrow` metadata coverage accepts common marker
  display/style parameters while preserving existing normalized output schemas.
- Initial `plotbar`/`plotcandle` metadata coverage accepts common display
  parameters while preserving existing OHLC output schemas.

Maintenance tails:

- `ta.vwap` session-derived anchoring remains future work.
- `color.*` named constants are a common registry, not an exhaustive claim.
- Rust, CLI, Python, and WASM input override APIs expose call-site keyed scalar
  overrides.
- More plot options, visibility controls, styles, and display-driven renderer
  behavior remain future work.

Maintenance order:

1. Prefer small compatibility fixes inside already supported built-in families.
2. Keep new stateful helpers explicit about callsite state and rollback.
3. Move public output schema expansion into Phase K or the relevant platform
   phase.

Acceptance criteria:

- Every maintained built-in change has semantic signature tests and runtime
  fixtures.
- Stateful built-ins behave correctly inside `if`, `switch`, loops, and UDF
  callsites when those combinations are claimed.
- CLI, Python, and WASM expose any new result fields consistently.

## Phase E: Drawing Object Systems

Goal: support Pine drawing objects as first-class runtime outputs.

Execution playbook: `docs/PHASE_E_EXECUTION_PLAN.md`.
Closeout audit: `docs/PHASE_E_AUDIT.md`.

Status: closed for the current fixture-backed partial drawing platform. Labels,
lines, boxes, and tables have public sparse snapshots, deterministic ids,
limits, incremental append coverage, and realtime rollback coverage for their
claimed method subsets. `linefill.new` has initial runtime-owned object ids,
color snapshots, and same-pair replacement semantics, and `linefill.set_color`
can mutate existing linefill colors. `linefill.get_line1` and
`linefill.get_line2` can return referenced line ids. `linefill.all` can return
currently existing linefill ids, and `linefill.delete` can append deletion
snapshots. `array.new_linefill` and `array.from` can construct linefill id
arrays for generic object-array storage, reads, mutation, and search.
`chart.point` has fixture-backed constructor/copy, top-level field access, and
point-array support. `polyline.new` can copy point arrays into host-neutral
runtime snapshots; `polyline.delete` appends lifecycle deletion snapshots, and
`polyline.all` reads currently existing ids. Realtime rollback is fixture-backed
for the supported lifecycle subset, and `polyline.new` consumes the default
polyline display limit plus named `max_polylines_count` declarations to evict
oldest active polyline snapshots before creating new ones. General polyline
arrays remain unsupported pending host-surface parity.

Object families:

- `label.*`
- `line.*`
- `box.*`
- `table.*`
- `linefill.new`, `linefill.set_color`, `linefill.get_line1`, and
  `linefill.get_line2` partial; `linefill.all`, `linefill.delete`, and
  linefill object-array construction/read/mutation/search partial
- `polyline.*`

Required design:

- `array.new<chart.point>()` and `array.from(chart.point, ...)` point-list
  construction are fixture-backed prerequisites for `polyline.new`; the next
  runtime claim should focus on limit parity and general array boundaries for
  the supported polyline lifecycle subset.
- Runtime object ids and lifetime rules.
- Per-bar creation, mutation, and deletion semantics.
- Rollback behavior for forming bars.
- Output schema for object snapshots or event streams.
- Limits for object counts and memory use.
- UDF side-effect policy for object creation and mutation.

Acceptance criteria:

- Object creation, update, delete, rollback, and limit fixtures exist for each
  supported family.
- Public outputs are stable enough for downstream renderers.
- Unsupported object families or methods produce precise diagnostics.

Suggested first slice:

1. Implement `label.new` plus a minimal immutable snapshot output.
2. Add `label.set_*` mutation methods.
3. Add deletion and object limits.
4. Repeat the pattern for `line` after label semantics settle.

## Phase F: `request.*` and Multi-Timeframe Data

Goal: support external data requests only after the runtime has a clear data
provider abstraction.

Execution playbook: `docs/PHASE_F_EXECUTION_PLAN.md`.

Scope:

- Design a host data-provider API for symbols and timeframes.
- Define bar alignment and gap behavior.
- Define caching and deterministic replay semantics.
- Implement a narrow `request.security` subset first.
- Preserve diagnostics for unsupported request variants.

Risks:

- Multi-timeframe alignment can change stateful-call behavior.
- Host APIs differ across CLI, Python, WASM, and future embeddings.

Acceptance criteria:

- Fixtures cover higher-timeframe and lower-timeframe alignment.
- Historical, incremental, and realtime paths agree.
- Missing data and provider errors produce stable diagnostics or runtime
  errors.

## Phase G: Strategy Runtime

Status: closed for the first fixture-backed partial subset. See
`docs/PHASE_G_AUDIT.md`.

Goal: add `strategy.*` only as a separate runtime mode, not as a small built-in
extension.

Execution playbook: `docs/PHASE_G_EXECUTION_PLAN.md`.

Scope:

- Strategy declaration with positive const numeric `initial_capital`.
- Long-only `strategy.entry` and full-position `strategy.close`.
- Broker emulator state for one net long position, realized trades, position
  snapshots, and per-bar equity snapshots.
- Strategy output schema across CLI, Python, and WASM.
- Commission, slippage, margin, percent sizing, pyramiding, richer order types,
  strategy variables, strategy alerts, and realtime broker rollback remain
  maintenance tails.

Dependencies:

- Stable historical execution.
- Clear result schema versioning.
- Dedicated strategy fixtures separate from indicator fixtures.

Acceptance criteria:

- Indicator and strategy runtime modes are clearly separated.
- Order execution is deterministic and fixture-backed.
- Public APIs expose strategy results without weakening indicator results.

## Phase H: Alerts

Status: closed for the fixture-backed claimed subset. See
`docs/PHASE_H_AUDIT.md`.

Goal: support alert surfaces after series and condition evaluation semantics
are stable.

Execution playbook: `docs/PHASE_H_EXECUTION_PLAN.md`.

Delivered scope:

- `alertcondition(condition, title, message)` with bool-compatible conditions,
  const-string title/message values, and supported message placeholders.
- `alert(message, freq?)` with string-compatible dynamic messages plus
  `alert.freq_once_per_bar`, `alert.freq_all`, and
  `alert.freq_once_per_bar_close`.
- Deterministic public runtime alert events in `schemaVersion: 3`.
- Historical, incremental, and realtime rollback fixture coverage.
- Stable diagnostics for unsupported frequency modes, unsupported placeholders,
  side-effect contexts, and requested-context alert side effects.

Maintenance tails:

- Broader Pine-source alert placeholder interpolation needs a dedicated design
  before support is claimed.
- Host-side alert delivery APIs are not part of the current runtime host
  surfaces.
- Strategy order-fill alert payloads are now part of the strategy runtime
  surface under `strategy.alerts`, with explicit host helpers for
  `{{strategy.order.alert_message}}`; broader running-alert configuration and
  realtime delivery boundaries are tracked in
  `docs/STRATEGY_RUNNING_ALERT_CONFIGURATION_PLAN.md` and
  `docs/STRATEGY_REALTIME_ALERT_DELIVERY_PLAN.md`.

Acceptance criteria:

- Alert outputs are represented as deterministic events.
- Realtime forming-bar behavior is explicitly documented.
- Unsupported alert options remain diagnostic-only.

## Phase I: `varip` and Intrabar Persistence

Status: closed for the fixture-backed claimed subset. See
`docs/PHASE_I_AUDIT.md`.

Goal: implement intrabar persistence only after realtime update semantics are
fully specified.

Execution playbook: `docs/PHASE_I_EXECUTION_PLAN.md`.

Delivered scope:

- `varip` declaration analysis.
- Intrabar storage distinct from confirmed-bar `var` storage.
- Interaction with forming-bar rollback.
- Interaction with scalar typed-array ids and backing contents.

Maintenance tails:

- Drawing object ids remain rejected for `varip` until object-store handoff rules
  are designed.
- Tuple `varip`, maps, matrices, UDTs, imports, object arrays, generic arrays,
  and other value families remain outside the Phase I claim.
- Realtime behavior is covered in Rust runtime fixtures; CLI, Python, and WASM
  continue to expose historical compile/analyze/run host surfaces.

## Phase J: Libraries, Imports, User Types, and Methods

Status: closed for the fixture-backed claimed subset. See
`docs/PHASE_J_AUDIT.md`.

Goal: support larger Pine programs after the core runtime model has matured.

Execution playbook: `docs/PHASE_J_EXECUTION_PLAN.md`.

Delivered scope:

- Host-neutral `AnalysisInput` and deterministic `SourceGraph`.
- CLI, Python, and WASM host-supplied library source maps.
- Exact-key `import ... as alias` for exported const expressions and pure
  exported functions.
- Local scalar-field user-defined types with `Type.new(...)`, field reads,
  ordinary variables, local for-expression constructor results,
  top-level/block-local/loop-local same-UDT ternary, switch, or `if`
  expression initialization, top-level/block-local/loop-local same-UDT `for`
  expression initialization and reassignment, `var` persistence from `na`,
  same-UDT constructors, same-UDT ternary expressions, same-UDT switch
  expressions, same-UDT `if` expressions, or same-UDT `for` expressions, scalar
  field mutation outside method bodies including branch, `for` loop, and
  UDF-local variables, and UDF constructor returns, directly, through nested pure
  constructor-helper UDF calls, or through
  same-local-UDT ternary, switch, `if` expression, final if/else constructor
  branches, or final for bodies, from local UDT parameter scalar fields, scalar
  fields read through block-local UDT aliases of those
  parameters, block-local scalar aliases of those fields, inferred scalar
  parameters, or block-local scalar aliases of those scalar parameters using
  positional or named constructor field arguments.
- Pure methods on local UDT receivers with scalar or local UDT parameters and
  direct UDT passthrough returns, block-local receiver alias passthrough
  returns, block-local local UDT parameter alias passthrough returns,
  nested-method UDT parameter passthrough returns, plus local UDT constructor
  returns, directly, through nested pure constructor-helper UDF calls, or
  through same-local-UDT ternary, switch, `if` expression, final if/else
  constructor branches, or final for bodies, from receiver or local UDT
  parameter scalar fields, scalar fields read through block-local receiver or
  local UDT parameter aliases, block-local scalar aliases of those
  fields, inferred scalar parameters, or block-local scalar aliases of those
  parameters using positional or named constructor field arguments.

Maintenance tails:

- Remote registry lookup, version resolution, re-exports, wildcard/unaliased
  imports, imported UDT identity, imported methods, private exported UDTs, and
  advanced library visibility remain unsupported.
- UDT field mutation inside functions or methods, UDT history references,
  `varip` UDTs, nested UDT fields, UDT arrays, recursive UDTs, method side
  effects, recursive methods, generic methods, and strategy-library
  interactions remain unsupported.

Risks:

- This touches semantic analysis, name resolution, caching, packaging, and
  security boundaries.

Acceptance criteria:

- Compile cache keys include all source dependencies.
- Diagnostics identify the originating file and span.
- Imported code follows the same side-effect and compatibility rules as local
  code.

## Phase K: Release and Compatibility Infrastructure

Goal: keep the growing subset maintainable.

Execution playbook: `docs/PHASE_K_EXECUTION_PLAN.md`.
Closure audit: `docs/PHASE_K_AUDIT.md`.

Scope:

- Result schema versioning for CLI, Python, and WASM.
- Fixture-backed conformance metadata gates.
- Golden JSON snapshots for public output shapes.
- Deterministic runtime profile gates for long histories and many callsites.
- A shared CI/local release verification entry point covering Rust, Python
  wheel, and WASM target checks.
- Compatibility matrix reporting by feature, status, fixture, and known gaps.

Acceptance criteria:

- New feature work cannot accidentally widen compatibility claims without
  conformance metadata.
- Public output changes are intentional and documented.
- Performance regressions are visible before release.

## Phase L: Strategy Usability

Goal: make the Phase G long-only strategy runtime easier to use before adding
richer order types.

Status: closed for the current fixture-backed subset. Execution playbook:
`docs/PHASE_L_EXECUTION_PLAN.md`. Closeout audit: `docs/PHASE_L_AUDIT.md`.

Closed scope:

- Read-only strategy state variables such as `strategy.position_size`,
  `strategy.position_avg_price`, `strategy.openprofit`, `strategy.netprofit`,
  and `strategy.equity` for strategy-mode scripts.
- Strategy variable behavior across supported expressions, control flow,
  history, incremental append execution, and public host surfaces.
- A design gate for fixed default quantity settings.
- A design gate for `strategy.exit` before stop/limit or pending-order behavior
  is accepted.

Closeout evidence:

- Strategy scripts can observe the broker state needed to control the current
  long-only order subset.
- Indicator and strategy modes remain clearly separated.
- Public host behavior remains synchronized across CLI, Python, and WASM.
- Unsupported strategy variants continue to produce stable diagnostics.
- `scripts/verify.sh` passed on the Phase L closeout workspace.

## Phase M: Strategy Exit and Order Lifecycle

Goal: make the Phase G/L long-only strategy runtime able to express a minimal
deterministic exit-order lifecycle before adding richer broker behavior.

Status: closed for the current fixture-backed subset. Execution playbook:
`docs/PHASE_M_EXECUTION_PLAN.md`. Closeout audit:
`docs/PHASE_M_AUDIT.md`.

Closed scope:

- A design gate for the first `strategy.exit` subset before any positive
  compatibility claim changes.
- Strategy-mode-only `strategy.exit` support for the current one-net-long
  broker model.
- Full-position long stop and limit exits with explicit historical OHLC
  trigger and fill rules.
- Pending-exit lifecycle semantics such as replacement, close cancellation, and
  missing-entry behavior.
- Public host behavior synchronized across CLI, Python, and WASM through the
  existing strategy result contract without a runtime schema bump.

Closeout evidence:

- `strategy.exit(id, from_entry, stop=price)` and
  `strategy.exit(id, from_entry, limit=price)` are fixture-backed partial
  claims in `tests/fixtures/conformance.tsv`.
- Runtime snapshots cover stop exits, limit exits, and branch/switch/loop plus
  strategy-state interactions.
- Python and WASM host tests assert the representative public contracts.
- Combined stop/limit brackets and richer broker behavior remain unsupported
  with stable diagnostics.
- `scripts/verify.sh` passed on the Phase M closeout workspace.

Out of scope until separately designed:

- Combined trigger brackets, active-entry or future-entry exit attachment,
  multiple pending exits, and richer order modification rules.
- Short exposure, reversals, pyramiding, partial exits, trailing stops,
  commission, slippage, margin, currency conversion, strategy order namespaces,
  strategy alerts, and realtime strategy execution.

## Phase N: Strategy Exit Profit And Loss

Goal: widen the Phase M stop/limit exit lifecycle with deterministic
entry-relative profit/loss tick helpers without adding bracket behavior or a
new public runtime schema.

Status: closed for the current fixture-backed subset. Execution playbook:
`docs/PHASE_N_EXECUTION_PLAN.md`. Closeout audit:
`docs/PHASE_N_AUDIT.md`.

Closed scope:

- A design gate for profit/loss tick helpers before any positive compatibility
  claim changes.
- Strategy-mode-only `strategy.exit(id, from_entry, profit=ticks)` and
  `strategy.exit(id, from_entry, loss=ticks)` support for the current
  one-net-long broker model.
- Tick-distance conversion through the fixed default `syminfo.mintick` subset
  from `strategy.position_avg_price`.
- Reuse of the Phase M one-pending-exit lifecycle, later-bar trigger rules, and
  public strategy output contract.
- A bracket design gate that keeps every combined trigger form unsupported.

Closeout evidence:

- Stop-only, limit-only, profit-only, and loss-only `strategy.exit` calls are
  fixture-backed partial claims in `tests/fixtures/conformance.tsv`.
- Runtime snapshots cover profit exits, loss exits, and branch/switch/loop plus
  strategy-state/history interactions.
- Python and WASM host tests assert representative profit/loss public
  contracts.
- Combined trigger brackets, trailing stops, partial exits, and richer broker
  behavior remain unsupported with stable diagnostics.
- `scripts/verify.sh` passed on the Phase N closeout workspace.

Out of scope until separately designed:

- Combined trigger brackets, same-bar high/low precedence, missing-entry
  pre-placement, multiple pending exits, and richer order modification rules.
- Short exposure, reversals, pyramiding, partial exits, trailing stops,
  commission, slippage, margin, currency conversion, strategy order namespaces,
  strategy alerts, and realtime strategy execution.

## Phase O: Strategy Reporting Counts

Goal: add the first narrow strategy reporting variables without opening a
larger broker-simulation phase or changing the public runtime schema.

Status: closed for the fixture-backed count variables. Execution playbook:
`docs/PHASE_O_EXECUTION_PLAN.md`; closeout audit:
`docs/PHASE_O_AUDIT.md`.

Planned scope:

- Strategy-mode-only `strategy.closedtrades` as a read-only count of closed
  trades recorded by the current broker state.
- Strategy-mode-only `strategy.opentrades` as a read-only count of open trades
  represented by the current long-only broker state.
- Series integer behavior in supported expression, control-flow, pure UDF
  argument, and constant history-reference contexts.
- Existing Phase M/N timing rules: `strategy.close` mutates immediately for
  subsequent reads, while pending-exit fills are evaluated after script
  statements and become visible to script reads on the next bar.
- No new public strategy output fields and no runtime schema bump.

Out of scope until separately designed:

- Strategy closed-trade and open-trade namespace functions.
- Public open-trade records, pending-order records, partial-fill fields, and
  exit-reason fields.
- Rich broker metrics such as drawdown, win/loss trade counts, and runup.
- Combined trigger brackets, partial exits, trailing stops, pyramiding, short
  exposure, commission, slippage, margin, strategy alerts, and realtime
  strategy execution.

## Phase P: Strategy Broker Structure

Goal: preserve the current fixture-backed strategy behavior while splitting
the oversized broker implementation into smaller internal modules before any
larger broker-simulation feature is opened.

Status: closed for structural broker maintenance. Execution playbook:
`docs/PHASE_P_EXECUTION_PLAN.md`; closeout audit:
`docs/PHASE_P_AUDIT.md`.

Planned scope:

- Keep `BrokerState` as the public strategy runtime facade exported by
  `pine-runtime`.
- Move the broker implementation into a module directory and extract
  pending-exit state, exit placement, fill construction, accounting/state
  accessors, and broker-focused tests into clear internal modules.
- Preserve the current Phase G/L/M/N/O strategy semantics, public runtime JSON,
  Python dictionaries, WASM JSON, conformance claims, and snapshots.
- Record the next small strategy maintenance target after the structural split:
  a bracket design gate that keeps combined trigger exits unsupported while
  documenting the same-bar precedence and bracket-identity decisions needed
  before support.

Out of scope until separately designed:

- New strategy compatibility surface.
- Public strategy output schema changes.
- Combined trigger brackets, partial exits, trailing stops, multiple pending
  exits, pyramiding, short exposure, commission, slippage, margin, strategy
  alerts, and realtime strategy execution.

## Phase Q: Strategy Exit Bracket Design Gate

Goal: close the `strategy.exit` combined-trigger design gap before any positive
bracket support is claimed.

Status: closed as a design gate. Execution playbook:
`docs/PHASE_Q_EXECUTION_PLAN.md`; closeout audit:
`docs/PHASE_Q_AUDIT.md`.

Closed scope:

- Keep combined `strategy.exit` trigger families unsupported during the design
  gate.
- Harden phase-neutral diagnostics around unsupported combined trigger
  variants.
- Record the first future bracket subset, or explicitly defer it, before
  implementation begins.
- Decide bracket identity, replacement, expression-evaluation, invalid-leg, and
  same-bar high/low both-hit semantics for the current one-net-long broker.
- Plan the future semantic, runtime, incremental, CLI, Python, WASM, and
  conformance fixture coverage needed before support can be claimed.
- Keep public runtime JSON, Python dictionaries, WASM JSON, conformance
  statuses, and runtime snapshots unchanged unless a diagnostic-only fixture or
  documentation-only metadata update requires a conservative reference change.

Out of scope until a later behavior phase:

- Runtime support for combined stop/limit, profit/loss, or mixed trigger
  brackets.
- Public pending-order records, partial-fill fields, exit-reason fields, or a
  runtime schema bump.
- Partial exits, quantity reservation, active-entry or future-entry exit
  attachment, multiple pending exits, pyramiding, short exposure, trailing
  stops, commission, slippage, margin, strategy alerts, and realtime broker
  rollback.

## Phase R: Strategy Exit Bracket Implementation

Goal: turn the Phase Q design gate into the first positive
`strategy.exit` bracket subset without changing the public strategy output
schema.

Status: closed for the current fixture-backed subset. Execution playbook:
`docs/PHASE_R_EXECUTION_PLAN.md`; closeout audit:
`docs/PHASE_R_AUDIT.md`.

Closed scope:

- Strategy-mode-only brackets with exactly one downside leg plus one upside leg
  for the current one-net-long, no-pyramiding broker.
- Supported bracket forms are `stop + limit`, `stop + profit`, `loss + limit`,
  and `loss + profit`.
- A bracket is one broker-owned pending full-position exit; filling either leg
  cancels the other leg.
- Later-bar fills use `low <= stop/loss price` or
  `high >= limit/profit price`. If both legs are touched on the same eligible
  historical bar, the stop/loss side fills first.
- Filled brackets emit exactly one `strategy.exit` order event, one closed
  trade under the source entry id, normal position/equity snapshots, and no
  public pending-order, bracket-leg, exit-reason, or schema changes.
- Semantic, runtime, incremental, CLI, Python, WASM, conformance, and docs
  coverage are fixture-backed.

Out of scope until separately designed:

- Same-side pairs `stop + loss` and `limit + profit`, and 3+ trigger forms.
- Partial exits, `qty`, `qty_percent`, and reservation behavior.
- Missing-entry pre-placement.
- Multiple entries, pyramiding, short exposure, and reversals.
- Multiple pending exits and public pending-order records.
- Commission, slippage, margin, richer sizing, strategy alerts, and realtime
  broker rollback for brackets.

## Phase S: Strategy Exit Trailing Stop Implementation

Goal: add the first deterministic `strategy.exit` trailing-stop subset without
changing the public strategy output schema.

Status: implemented for the current fixture-backed subset. Execution playbook:
`docs/PHASE_S_EXECUTION_PLAN.md`.

Closed scope:

- Strategy-mode-only trailing exits for the current one-net-long,
  no-pyramiding broker.
- Supported forms are exactly `trail_price + trail_offset` and
  `trail_points + trail_offset`.
- `trail_price` is an explicit activation price. `trail_points` converts to an
  entry-relative activation price with fixed default `syminfo.mintick`.
  `trail_offset` converts to a fixed price distance with the same mintick
  subset.
- A trailing exit is one broker-owned pending full-position exit. It starts
  inactive, is not eligible on its creation or replacement bar, activates on a
  later eligible bar when `high >= activation`, and does not fill on the
  activation bar.
- Once active, the stop fills first when `low <= active_stop`; otherwise it
  ratchets upward to `max(active_stop, high - offset_distance)` and never
  decreases.
- Filled trailing exits emit exactly one `strategy.exit` order event, one
  closed trade under the source entry id, normal position/equity snapshots, and
  no public pending-order, trailing-state, exit-reason, or schema changes.
- Semantic, runtime, incremental, CLI, Python, WASM, conformance, and docs
  coverage are fixture-backed.

Out of scope until separately designed:

- Combining trailing exits with fixed `stop`, `limit`, `profit`, or `loss`
  triggers.
- Calls with both `trail_price` and `trail_points`, missing `trail_offset`, or
  no activation argument.
- Partial exits, `qty`, `qty_percent`, and reservation behavior.
- Missing-entry pre-placement.
- Multiple entries, pyramiding, short exposure, and reversals.
- Multiple pending exits and public pending-order records.
- Commission, slippage, margin, richer sizing, strategy alerts, and realtime
  broker rollback for trailing stops.

## Phase U: Strategy Exit Partial Quantity

Goal: add the first deterministic partial-quantity `strategy.exit` subset
without changing the public strategy output schema.

Status: closed for the current fixture-backed fixed `qty` partial-exit subset.
See `docs/PHASE_U_AUDIT.md`. Execution playbook:
`docs/PHASE_U_EXECUTION_PLAN.md`.

Planned scope:

- Strategy-mode-only `strategy.exit(..., qty=...)` for the current
  one-net-long, no-pyramiding, one-pending-exit broker.
- Support `qty` on the currently supported single-trigger, bracket, and
  trailing exit forms.
- Evaluate `qty` at placement time, require finite positive values, and clamp
  filled quantity to the current open position size.
- Partial fills record one strategy exit order event and one closed trade for
  the filled quantity, leave any remaining long position open at the same
  average price, and keep the existing strategy result shape and runtime
  `schemaVersion: 3`.

Out of scope until separately designed:

- Quantity reservation across multiple exits.
- Multiple independent pending exits.
- Missing-entry pre-placement.
- Multiple entries, pyramiding, short exposure, and reversals.
- Public pending-order records, partial-fill fields, exit-reason fields, or a
  runtime schema bump.
- `qty_percent`, which Phase U explicitly defers to Phase V.

## Phase V: Strategy Exit Percent Quantity

Goal: add the first deterministic percent-quantity `strategy.exit` subset
without changing the public strategy output schema.

Status: closed for the current fixture-backed `qty_percent` partial-exit subset.
See `docs/PHASE_V_AUDIT.md`. Execution playbook:
`docs/PHASE_V_EXECUTION_PLAN.md`.

Planned scope:

- Strategy-mode-only `strategy.exit(..., qty_percent=...)` for the current
  one-net-long, no-pyramiding, one-pending-exit broker.
- Support `qty_percent` on the currently supported single-trigger, bracket, and
  trailing exit forms.
- Evaluate `qty_percent` at placement time, require finite positive values,
  resolve it to an absolute requested close quantity against the current open
  position size, and clamp filled quantity to the current position size.
- Partial fills record one strategy exit order event and one closed trade for
  the absolute filled quantity, leave any remaining long position open at the
  same average price, and keep the existing strategy result shape and runtime
  `schemaVersion: 3`.

Out of scope until separately designed:

- Calls that combine `qty` and `qty_percent`.
- Quantity reservation across multiple exits.
- Multiple independent pending exits.
- Missing-entry pre-placement.
- Multiple entries, pyramiding, short exposure, and reversals.
- Public pending-order records, percent fields, remaining-quantity fields,
  exit-reason fields, or a runtime schema bump.

## Phase W: Strategy Exit Quantity Reservations

Goal: add the first deterministic multiple-exit reservation subset without
changing the public strategy output schema.

Status: closed for the current fixture-backed explicit fixed `qty` or
`qty_percent` single-trigger reservation subset. See `docs/PHASE_W_AUDIT.md`.
Execution playbook: `docs/PHASE_W_EXECUTION_PLAN.md`.

Planned scope:

- Strategy-mode-only multiple pending `strategy.exit` reservations for the
  current one-net-long, no-pyramiding broker.
- Support different `id + from_entry` identities only for explicit fixed `qty`
  or `qty_percent` single-trigger exits.
- Resolve reservations at placement time, clamp new reservations to remaining
  unreserved position quantity, and reject zero-reservation placements without
  changing existing pending exits.
- Replace same-identity pending exits after releasing the old reservation.
- Fill same-side touched exits in placement order, and process downside
  candidates only when downside and upside candidates are both touched on the
  same eligible bar.
- Keep the existing strategy result shape and runtime `schemaVersion: 3`.

Out of scope until separately designed:

- Calls that combine `qty` and `qty_percent`.
- Omitted-quantity multiple reservations, closed as unsupported by Phase Z.
- Multiple pending bracket or trailing reservations.
- Reservation behavior outside explicit fixed `qty` or `qty_percent`
  single-trigger exits.
- Missing-entry pre-placement.
- Multiple entries, pyramiding, short exposure, and reversals.
- Public pending-order records, reservation fields, remaining-quantity fields,
  exit-reason fields, or a runtime schema bump.

## Phase X: Strategy Exit Bracket Reservations

Goal: extend the deterministic multiple-exit reservation subset to supported
one-downside/one-upside bracket exits without changing the public strategy
output schema.

Status: closed for the current fixture-backed explicit fixed `qty` or
`qty_percent` bracket reservation subset. See `docs/PHASE_X_AUDIT.md`.
Execution playbook: `docs/PHASE_X_EXECUTION_PLAN.md`.

Supported scope:

- Strategy-mode-only multiple pending `strategy.exit` reservations for the
  current one-net-long, no-pyramiding broker.
- Support different `id + from_entry` identities for supported bracket forms
  only when each bracket has explicit fixed `qty` or `qty_percent`.
- Supported bracket forms remain `stop + limit`, `stop + profit`,
  `loss + limit`, and `loss + profit`.
- Single-trigger reservations and bracket reservations can share the same
  reservation pool for the current matching long entry.
- Resolve reservations at placement time, clamp new reservations to remaining
  unreserved position quantity, and reject zero-reservation placements without
  changing existing pending exits.
- Replace same-identity pending exits after releasing the old reservation.
- Fill same-side touched candidates in placement order, process downside
  candidates only when downside and upside candidates are both touched on the
  same eligible bar, and treat a both-leg bracket touch as that bracket's
  downside candidate.
- Keep the existing strategy result shape and runtime `schemaVersion: 3`.

Out of scope until separately designed:

- Calls that combine `qty` and `qty_percent`.
- Omitted-quantity multiple reservations, closed as unsupported by Phase Z.
- Multiple pending trailing reservations.
- Reservation behavior outside explicit fixed `qty` or `qty_percent`
  single-trigger and bracket exits.
- Missing-entry pre-placement.
- Multiple entries, pyramiding, short exposure, and reversals.
- Public pending-order records, reservation fields, remaining-quantity fields,
  bracket-leg fields, exit-reason fields, or a runtime schema bump.

## Phase Y: Strategy Exit Trailing Reservations

Goal: extend the deterministic multiple-exit reservation subset to supported
trailing exits without changing the public strategy output schema.

Status: closed for the current fixture-backed explicit fixed `qty` or
`qty_percent` trailing reservation subset. See `docs/PHASE_Y_AUDIT.md`.
Execution playbook: `docs/PHASE_Y_EXECUTION_PLAN.md`.

Supported scope:

- Strategy-mode-only multiple pending `strategy.exit` reservations for the
  current one-net-long, no-pyramiding broker.
- Support different `id + from_entry` identities for supported trailing forms
  only when each trailing exit has explicit fixed `qty` or `qty_percent`.
- Supported trailing forms remain `trail_price + trail_offset` and
  `trail_points + trail_offset`.
- Single-trigger, bracket, and trailing reservations can share the same
  reservation pool for the current matching long entry.
- Resolve reservations at placement time, clamp new reservations to remaining
  unreserved position quantity, and reject zero-reservation placements without
  changing existing pending exits.
- Replace same-identity pending exits after releasing the old reservation.
- Inactive trailing reservations activate on a later eligible bar and do not
  fill on the activation bar.
- Active trailing reservations fill as downside candidates before same-bar
  ratchets, and unfilled active trailing stops ratchet upward only.
- Fill same-side touched candidates in placement order, process downside
  candidates only when downside and upside candidates are both touched on the
  same eligible bar, and preserve opposite-side candidates when a long position
  remains.
- Keep the existing strategy result shape and runtime `schemaVersion: 3`.

Out of scope until separately designed:

- Calls that combine `qty` and `qty_percent`.
- Omitted-quantity multiple reservations, closed as unsupported by Phase Z.
- Reservation behavior outside explicit fixed `qty` or `qty_percent`
  single-trigger, bracket, and trailing exits.
- Missing-entry pre-placement.
- Multiple entries, pyramiding, short exposure, and reversals.
- Public pending-order records, reservation fields, remaining-quantity fields,
  bracket-leg fields, trailing-state fields, activation fields, exit-reason
  fields, or a runtime schema bump.

## Phase Z: Strategy Exit Omitted-Quantity Boundary

Goal: close the omitted-quantity multiple-exit boundary without widening the
reservation subset or changing the public strategy output schema.

Status: closed for the current fixture-backed omitted-quantity replacement
boundary. Omitted-quantity multiple reservations are fixture-backed as
unsupported. See `docs/PHASE_Z_AUDIT.md`.
Execution playbook: `docs/PHASE_Z_EXECUTION_PLAN.md`.

Supported boundary:

- Omitted `qty` and omitted `qty_percent` calls keep full-position
  one-effective-pending behavior.
- Different `id + from_entry` identities replace the previous omitted
  full-position pending exit for supported single-trigger, bracket, and trailing
  forms.
- A later omitted full-position exit clears earlier explicit fixed-`qty` or
  `qty_percent` reservations for the current matching long entry.
- The existing strategy result shape and runtime `schemaVersion: 3` remain
  unchanged.

Closed unsupported boundary:

- Omitted-quantity multiple pending reservations.
- Reservation behavior outside explicit fixed `qty` or `qty_percent`
  single-trigger, bracket, and trailing exits.

Still deferred:

- Missing-entry pre-placement.
- Multiple entries, pyramiding, short exposure, and reversals.
- Public pending-order records, reservation fields, remaining-quantity fields,
  trigger-side fields, activation fields, exit-reason fields, or a runtime
  schema bump.
- Richer broker behavior beyond the current fixture-backed subset, including
  `strategy.order`, full OCA APIs, short exposure, pyramiding, reversals,
  margin behavior beyond the supported long-only account subset, and realtime
  strategy handoff.

## Backlog Priority

Recommended order from the current state:

The seven broad interpreter-internal task directions are summarized in
`docs/NEXT_INTERNAL_CAPABILITY_PLAN.md`. The order below remains the roadmap
priority for choosing one small fixture-backed slice at a time.

1. Prefer a small built-in compatibility slice selected from a real fixture
   gap, unless a narrow strategy diagnostics, accounting, or metadata issue
   already has a clear contract.
2. Keep the Stage 13 long-only multi-entry strategy baseline stable. Require a
   new broker-model design before adding short/reversal behavior, custom OCA,
   richer generic order APIs, or public pending-order contracts.
3. Phase J maintenance only when a small, fixture-backed change widens the
   already claimed import, UDT, or method subsets.
4. Phase E/F/H/I maintenance only when a small, fixture-backed change widens an
   already claimed drawing, request, alert, or `varip` subset.
5. Phase K maintenance only when release contracts, snapshots, or matrix gates
   need tightening.
6. Phase B/C maintenance when new work exposes collection, history, or
   qualifier gaps.

This order keeps the project useful for indicator and basic strategy execution
while delaying features that require new host APIs, object lifetimes, or richer
broker simulation.
