# Phase L Strategy Usability Execution Plan

Phase L widens the Phase G strategy runtime from a minimal broker proof into a
more usable, fixture-backed strategy subset. Execute it in small, mergeable
slices. Each slice should leave the workspace shippable and should keep
semantic claims, runtime behavior, public output contracts, fixtures, snapshots,
host bindings, conformance metadata, and docs in lockstep.

The first priority is read-only strategy state. Strategy scripts need to be able
to inspect position and profit state before the project accepts richer order
types. Do not start this phase by adding `strategy.exit`, stop/limit orders,
short exposure, pyramiding, or commission/slippage behavior; those are more
likely to multiply broker rules before scripts can observe the broker state
that already exists.

## Current Starting Point

The repository has already closed Phase G for the first fixture-backed strategy
subset:

- `tests/fixtures/conformance.tsv` marks `strategy`, `strategy.entry`,
  `strategy.close`, and `strategy equity` as `partial`.
- `tests/fixtures/conformance.tsv` keeps broad `strategy.*` as `unsupported`.
- `strategy(...)` supports `title`, `shorttitle`, `overlay`, `max_bars_back`,
  and positive const numeric `initial_capital`.
- `strategy.entry(id, strategy.long, qty=...)` opens one long market position
  at the current bar close, with no pyramiding.
- `strategy.close(id)` closes the full matching long position at the current
  bar close and records a deterministic closed trade.
- Strategy-mode runtime output exposes a `strategy` object with `orders`,
  `trades`, `position`, `equity`, and `diagnostics` arrays.
- Indicator-mode runtime output does not include the top-level `strategy` key.
- `pine-runtime::strategy::BrokerState` already tracks initial capital, cash,
  position size, average price, entry identity, order events, closed trades,
  position snapshots, equity snapshots, and runtime diagnostics.
- `pine-builtins` registers `strategy.entry` and `strategy.close`; it does not
  expose strategy state variables such as `strategy.position_size` or
  `strategy.position_avg_price`.
- `pine-sema` has a strategy-owned analyzer module for declaration and order
  checks, while unsupported strategy order families remain diagnostic-only.
- CLI, Python, and WASM already map the shared strategy result model.
- Historical and incremental execution are covered for strategy runtime
  fixtures. Realtime strategy broker handoff remains unsupported.

The current strategy-focused verification baseline is:

```text
cargo test -p pine-sema strategy
cargo test -p pine-runtime strategy
cargo test -p pine-cli strategy
cargo test -p pine-wasm strategy
```

The request subsystem is not the primary Phase L target. Lower-timeframe
requests still need typed array return semantics and host output/data-shape
design. Drawing `polyline.*` still needs polyline runtime state and snapshots
beyond the current partial `chart.point` value and point-array subset.

## Rules for Every Slice

- Add fixtures before or alongside behavior changes.
- Keep the compatibility matrix conservative. Do not mark a strategy feature
  `partial` unless the exact supported subset has positive runtime fixtures,
  negative semantic fixtures where applicable, public host coverage, and docs.
- Preserve indicator behavior. Indicator scripts must not gain broker state,
  strategy output fields, or strategy-mode-only variables.
- Keep strategy-mode and indicator-mode diagnostics distinct. Strategy state
  variables and order functions should produce stable strategy-mode diagnostics
  when used from indicator scripts.
- Treat the broker as deterministic runtime state. Core crates must not depend
  on account services, wall-clock time, host callbacks, filesystem data, or
  network data.
- Keep the current fill policy explicit. Until a slice deliberately changes it,
  supported market entries and closes fill immediately at the current bar
  close.
- Do not silently approximate unsupported broker behavior. If short exposure,
  stops, limits, order modification, pyramiding, commission, slippage, margin,
  currency conversion, or percent sizing is not designed in a slice, keep it
  diagnostic-only.
- Avoid public runtime JSON changes for read-only strategy variables. If a
  strategy variable can be observed through normal expressions and outputs, it
  should not add a new top-level output field.
- Review `PUBLIC_RUNTIME_SCHEMA_VERSION` only when the shared runtime output
  shape changes. Adding strategy variables that can be plotted should not bump
  the schema by itself.
- Keep CLI, Python, and WASM behavior synchronized. A script that compiles and
  runs through one public host should produce equivalent runtime JSON or native
  dictionary data through the others.
- Keep strategy variables out of requested-context expressions until a slice
  explicitly designs requested-context broker state. The current request
  provider context is isolated and data-only.
- Keep strategy variables out of UDF side-effect policy decisions unless a
  slice changes that policy. Reading state variables is pure; order calls remain
  side effects.
- Run the full release verification gate before closing a slice that changes a
  compatibility claim, public host contract, or public output contract.

## Internal Structure Rules

Phase L should grow the strategy subsystem without turning existing analyzer,
runtime, or output modules into catch-all broker files.

- Keep `pine-builtins` responsible for strategy variable type metadata and
  accepted order/declaration signatures. It should not own broker semantics.
- Keep `pine-sema::analyzer::strategy` responsible for strategy-mode gating,
  unsupported strategy variants, declaration settings, and strategy-specific
  diagnostic policy.
- Keep `pine-runtime::strategy` responsible for broker state, state accessors,
  order transitions, profit calculations, and future broker rule helpers.
- Keep `pine-runtime::builtins::strategy` responsible for evaluating accepted
  strategy calls and refreshing strategy state variables after broker mutation.
- Keep `pine-runtime::runtime::context` responsible for installing current
  built-in symbol values at the start of each bar. If strategy symbols become
  live after order calls, add a small strategy-owned refresh helper rather than
  duplicating symbol writes in many call sites.
- Keep `pine-runtime::output::strategy` limited to public result structs. It
  should not become the source of truth for expression-time strategy variables.
- Keep Python and WASM bindings thin. They should not duplicate broker math.
- Treat roughly 800 lines in a production Rust file as a review trigger. Split
  before adding more strategy argument families or broker accounting paths.
- Each slice should have an obvious review boundary: type metadata, semantic
  checks, broker accessors, runtime symbol values, fixtures, snapshots, docs,
  conformance metadata, and host tests should be inspectable independently.

## Intended Module Layout

Use existing crate boundaries. A new crate is not needed for Phase L.

Recommended layout:

```text
crates/pine-builtins/src/
   constants/series.rs          strategy state variable type metadata
   constants/strings.rs         strategy direction/default constants as needed
   namespaces/strategy.rs       declaration/order signatures only

crates/pine-sema/src/analyzer/
   strategy.rs                  strategy mode checks and argument validation
   expressions.rs               delegate strategy variable mode checks if needed
   unsupported.rs               unsupported strategy variants and reasons

crates/pine-runtime/src/
   strategy/
      mod.rs                    broker facade and re-exports
      broker.rs                 broker state, accessors, profit calculations
      settings.rs               only if declaration settings outgrow HIR metadata
      limits.rs                 only when pyramiding or quantity rules are added
   builtins/
      strategy.rs               strategy call evaluation and symbol refresh hooks
   runtime/
      context.rs                install built-in symbols at bar start
      historical.rs             strategy orchestration only
      realtime.rs               keep strategy realtime unsupported until designed
   output/
      strategy.rs               public strategy result structs
      json.rs                   shared public runtime JSON

crates/pine-cli/src/
   commands/run.rs              no broker logic; uses shared runtime behavior

crates/pine-python/src/
   lib.rs                       maps shared runtime result only

crates/pine-wasm/src/
   lib.rs                       returns shared runtime JSON only
```

Ownership notes:

- Strategy variables should be represented as series/simple built-in values,
  not as named float constants. They depend on runtime broker state.
- Broker accessors should expose values such as position size and average
  price without revealing mutable broker internals.
- Runtime symbol refresh should be centralized so a later order call cannot
  forget to update expression-visible strategy state.
- Strategy output arrays remain the reviewable public result contract. Strategy
  variables are expression inputs that may be observed through existing output
  calls such as `plot`.

## Strategy State Semantics Direction

Phase L should start with variables that are already derivable from the Phase G
broker state.

Initial variable candidates:

- `strategy.position_size`: current signed position size. In the Phase L
  long-only subset this is `0` when flat and positive when long.
- `strategy.position_avg_price`: current average entry price. Return `na` when
  flat unless public Pine documentation and fixtures justify a different
  compatibility choice before implementation.
- `strategy.openprofit`: unrealized profit for the current open position using
  the current bar close under the existing fill/mark-to-market policy. Return
  `0` when flat.
- `strategy.netprofit`: cumulative realized profit from closed trades only.
- `strategy.equity`: initial capital plus realized profit plus current open
  profit.

Visibility policy:

- Strategy state variables are accepted only in strategy-mode scripts.
- Indicator scripts that reference strategy state variables should fail during
  semantic analysis with a stable strategy-mode diagnostic.
- Values are evaluated against the current broker state at the point of
  expression evaluation.
- Because the current fill policy mutates broker state immediately when a
  supported order call executes, later statements on the same bar should see
  the updated state.
- When a strategy variable is referenced as a series, the final value visible
  at the end of the bar should be committed consistently with other series.
- Realtime strategy variable behavior remains unsupported until strategy
  realtime broker rollback is designed.

Profit policy for the first slices:

- `strategy.netprofit` should use realized closed-trade profit only.
- `strategy.openprofit` should use current close mark-to-market for the open
  long position.
- `strategy.equity` should equal `initial_capital + strategy.netprofit +
  strategy.openprofit` for the current long-only subset.
- The existing public equity snapshot field named `netProfit` currently means
  `equity - initial_capital`. Before adding `strategy.netprofit`, document this
  distinction clearly or rename only through a deliberate public schema change.
  Do not make a silent output-schema change in the strategy-variable slice.

## How to Use the Acceptance Criteria

The exit criteria under each slice are local merge criteria for that slice.
Phase L should not be marked closed until a closeout audit records the supported
surface, public host behavior, fixture evidence, verification results, and
remaining maintenance tails.

Every slice that changes conformance metadata should update these files in the
same change:

- `tests/fixtures/conformance.tsv`
- `tests/snapshots/matrix.json` through the documented snapshot workflow
- `docs/CONFORMANCE.md`
- `docs/LANGUAGE_SCOPE.md`
- `docs/EXECUTION_SEMANTICS.md`
- `docs/RELEASE_NOTES.md`
- This execution plan, if implementation decisions differ from the plan

Maintenance tails may keep advanced order families, strategy reporting helper
families, realtime broker rollback, and rich broker settings out of scope. They
must not weaken these Phase L acceptance criteria:

- Strategy scripts can observe the broker state needed to control the current
  long-only order subset.
- Indicator and strategy modes remain clearly separated.
- Public host behavior remains synchronized across CLI, Python, and WASM.
- Unsupported strategy variants continue to produce stable diagnostics.
- Compatibility claims remain fixture-backed.

## Slice 0: Strategy State Boundary Audit

Goal: lock the current unsupported boundary for strategy state variables before
accepting any positive variable support.

Steps:

1. Keep `strategy.*` broad support marked `unsupported` in conformance
   metadata.
2. Add or update negative semantic fixtures for the state variables selected
   for Slice 1 and Slice 2 while they are still unsupported, including:
   - `strategy.position_size` in an indicator script.
   - `strategy.position_avg_price` in an indicator script.
   - `strategy.openprofit`, `strategy.netprofit`, and `strategy.equity` in an
     indicator script if they are selected for Phase L.
   - unknown strategy variables that should remain unsupported.
3. Decide the diagnostic code strategy:
   - Prefer a strategy-mode diagnostic when a known strategy variable is used
     outside `strategy(...)` mode.
   - Preserve existing unknown-name diagnostics for truly unknown variables.
4. Confirm that unsupported variables do not accidentally become named constants
   through `pine-builtins` constant registries.
5. Document the first supported variable subset in this file before Slice 1
   changes behavior.
6. Confirm no public runtime JSON, Python dictionary, or WASM JSON shape changes
   occur in this slice.

Exit criteria:

- Current unsupported strategy-variable behavior is stable and fixture-backed.
- Known Phase L variable names have clear diagnostics before implementation.
- The conformance matrix remains conservative.
- No public output schema changes occur.

Slice 0 decision record:

- The first executable Phase L subset remains Slice 1 position state variables:
  `strategy.position_size` and `strategy.position_avg_price`.
- Before Slice 1, known Phase L strategy variables are semantic-analysis errors:
  indicator scripts receive `E_STRATEGY_MODE`, while strategy-mode scripts keep
  `E_UNSUPPORTED_FEATURE` with a strategy-state-variable reason.
- Unknown `strategy.*` variables remain on the existing broad unsupported
  strategy path rather than becoming named constants or unknown-name diagnostics.
- No public runtime JSON, Python dictionary, or WASM JSON shape changes belong
  to Slice 0.

Verification:

```text
cargo test -p pine-sema strategy
cargo test --workspace
```

## Slice 1: Position State Variables

Goal: expose the first read-only strategy state variables:
`strategy.position_size` and `strategy.position_avg_price`.

Initial scope:

- Strategy-mode scripts only.
- Historical execution only, through the existing public run entry points.
- Values follow the existing immediate current-close fill policy.
- No new order types, no realtime strategy support, and no public output schema
  change.

Steps:

1. Add type metadata for `strategy.position_size` and
   `strategy.position_avg_price` as series float values.
2. Add semantic strategy-mode gating for these variables:
   - Accepted in `strategy(...)` scripts.
   - Rejected in `indicator(...)` scripts.
   - Rejected in requested-context expressions unless a later slice designs
     requested-context broker state.
3. Add broker accessors:
   - `position_size() -> f64`.
   - `position_avg_price() -> PineValue` or an equivalent value-level helper
     that returns `na` when flat.
4. Add a runtime helper that installs current strategy variable values into
   `current_symbols` and `current_series` for referenced symbols.
5. Call the helper at bar start after ordinary built-in symbols are installed.
6. Call the helper after `strategy.entry` and `strategy.close` mutate broker
   state so later statements on the same bar observe updated values.
7. Add runtime fixtures for:
   - Flat strategy state before any order.
   - State after a long entry.
   - State after close returns to flat.
   - Conditional entry followed by a later same-bar read if the parser/runtime
     can express a useful same-bar sequence.
8. Add semantic fixtures for indicator-mode rejection and requested-context
   rejection if the request analyzer can currently see those variable names.
9. Add golden runtime snapshots only if the fixture output is part of the
   public snapshot set.
10. Add Python and WASM tests that run a script plotting the variables, or
    extend existing strategy host tests if that gives clearer coverage.
11. Add conformance rows such as `strategy.position_size` and
    `strategy.position_avg_price` with `partial` status and fixture paths.
12. Update docs to state the exact flat-position and same-bar visibility
    policy.

Exit criteria:

- Strategy scripts can branch or plot based on current position size.
- Average price is deterministic and `na` when flat under the documented first
  policy.
- Indicator scripts cannot read strategy state variables.
- Public host surfaces agree on the observed plotted values.
- No output schema changes are introduced.

Slice 1 implementation record:

- `strategy.position_size` and `strategy.position_avg_price` are accepted as
  strategy-mode-only historical series float values.
- `strategy.position_size` is `0` when flat and the current long quantity in the
  supported long-only broker subset.
- `strategy.position_avg_price` is `na` when flat and the current average entry
  price while long.
- Values are read from `BrokerState` at expression-evaluation time. Because
  supported market entry and close calls mutate the broker immediately, later
  statements on the same bar observe the updated position values.
- The variables remain rejected in indicator scripts and requested-context
  expressions. Profit/equity variables were left for Slice 2.
- No runtime JSON, Python dictionary, or WASM JSON schema fields were added;
  host coverage observes the variables through ordinary plot outputs.

Verification:

```text
cargo test -p pine-builtins strategy
cargo test -p pine-sema strategy
cargo test -p pine-runtime strategy
cargo test -p pine-cli strategy
cargo test -p pine-wasm strategy
python3 -m pytest python/tests
cargo test --workspace
```

## Slice 2: Profit and Equity Variables

Goal: expose the first read-only strategy profit variables:
`strategy.openprofit`, `strategy.netprofit`, and `strategy.equity`.

Initial scope:

- Strategy-mode scripts only.
- Historical execution only.
- Current long-only broker model only.
- No commission, slippage, margin, short exposure, pyramiding, or currency
  conversion.
- No runtime output schema change.

Steps:

1. Confirm the naming and formulas against public documentation and the Phase L
   local profit policy before writing code.
2. Add type metadata for the selected variables as series float values.
3. Add semantic strategy-mode gating and requested-context rejection matching
   Slice 1.
4. Add broker accessors for:
   - realized closed-trade profit.
   - open profit marked to the current close.
   - current equity.
5. Store cumulative realized profit directly in `BrokerState`, or derive it
   deterministically from closed trades if that remains cheap and clear.
6. Ensure open profit and equity can be refreshed at bar start and after broker
   mutation through the same centralized strategy-symbol helper from Slice 1.
7. Add runtime fixtures for:
   - Flat no-order strategy.
   - Open position with rising close.
   - Open position with falling close.
   - Closed profitable trade.
   - Closed losing trade.
8. Add host tests that observe the values through ordinary outputs.
9. Update golden snapshots if selected runtime fixtures are snapshot-backed.
10. Add conformance rows for each accepted variable with exact subset notes.
11. Update docs to distinguish expression-time `strategy.netprofit` from the
    existing public equity snapshot `netProfit` field if their meanings differ.

Exit criteria:

- Strategy scripts can observe realized, unrealized, and total equity state for
  the long-only subset.
- Profit values are deterministic across Rust runtime, CLI, Python, and WASM.
- Docs clearly state what is and is not included in each profit variable.
- Existing strategy output snapshots remain stable unless deliberately updated.

Slice 2 implementation record:

- `strategy.openprofit`, `strategy.netprofit`, and `strategy.equity` are
  accepted as strategy-mode-only historical series float values.
- `strategy.openprofit` is `0` when flat and marks the current long position to
  the current close while long.
- `strategy.netprofit` is cumulative realized closed-trade profit only and does
  not include current open profit.
- `strategy.equity` is `initial_capital + strategy.netprofit +
  strategy.openprofit` in the current long-only broker subset.
- Values are read from `BrokerState` at expression-evaluation time. Later
  statements on the same bar observe supported entry/close mutations
  immediately.
- The variables remain rejected in indicator scripts and requested-context
  expressions.
- The existing public strategy equity snapshot field `netProfit` remains
  `equity - initial_capital`, so it can include open profit while a position is
  open. No runtime JSON, Python dictionary, or WASM JSON schema fields were
  added.

Verification:

```text
cargo test -p pine-sema strategy
cargo test -p pine-runtime strategy
cargo test -p pine-cli strategy
cargo test -p pine-wasm strategy
python3 -m pytest python/tests
cargo test --workspace
```

## Slice 3: Strategy Variable Interactions

Goal: harden strategy variables across control flow, history, incremental
execution, and side-effect boundaries before adding more broker features.

Initial scope:

- Variables accepted in ordinary expressions, branches, loops, UDF arguments,
  and history references only when those expression forms are already supported
  for series float values.
- Strategy variables remain read-only.
- Order calls remain side effects and continue to be rejected in UDF bodies and
  other side-effect-restricted contexts.
- Requested-context strategy variables remain unsupported.

Steps:

1. Add fixtures for `strategy.position_size` inside `if`, `switch`, `for`, and
   `while` forms that are already supported.
2. Add fixtures for `strategy.position_size[1]` and `strategy.openprofit[1]`
   once history semantics are verified for these generated series ids.
3. Add fixtures for passing strategy variables into a pure UDF.
4. Add negative fixtures for assigning to strategy variables or otherwise
   treating them as mutable symbols.
5. Confirm incremental append execution matches full historical execution for
   every new runtime fixture.
6. Confirm runtime profile output does not grow unexpectedly from strategy
   variable history retention.
7. Update conformance notes to mention supported control-flow and history
   interactions.

Exit criteria:

- Strategy variables behave like ordinary read-only series values in supported
  expression contexts.
- History and incremental execution are fixture-backed.
- Unsupported mutation and requested-context usage remain diagnostic-only.

Slice 3 implementation record:

- Added fixture-backed coverage for strategy state variables in supported
  expression contexts: `if`, `switch`, `for`, `while`, pure UDF arguments, and
  constant history references.
- Verified `strategy.position_size[1]` and `strategy.openprofit[1]` use the
  normal generated-series history path and static one-bar retention.
- Confirmed incremental append execution matches full historical execution for
  the new runtime fixture through the existing runtime fixture sweep.
- Added negative fixtures for direct strategy state mutation and for
  `strategy.entry` side effects inside UDF bodies.
- No runtime JSON, Python dictionary, or WASM JSON schema fields were added.

Verification:

```text
cargo test -p pine-sema strategy
cargo test -p pine-runtime strategy
cargo test -p pine-runtime --test incremental
cargo test --workspace
```

## Slice 4: Default Quantity Design Gate

Goal: decide whether Phase L should accept default quantity declaration
settings before adding any new order type.

This is a design gate. It should not change compatibility claims unless the
slice deliberately implements a narrow default quantity subset.

Candidate scope:

- `default_qty_type=strategy.fixed` with positive const numeric
  `default_qty_value`.
- `strategy.entry(id, strategy.long)` may use the fixed default quantity only
  after fixtures prove the behavior.
- Percent-of-equity sizing remains out of scope unless a later slice designs
  equity timing, rounding, and invalid quantity behavior.

Steps:

1. Add string constants for `strategy.fixed` only if the implementation slice
   accepts the fixed default subset.
2. Decide whether `qty` remains required on `strategy.entry` until the default
   settings implementation lands.
3. Decide invalid declaration behavior for missing, zero, negative, non-finite,
   or non-const default quantity values.
4. Decide whether default quantity belongs in `pine_ir::StrategySettings`.
5. Add negative semantic fixtures for unsupported default quantity variants.
6. If implementing the fixed default subset:
   - Add built-in signature support for optional `qty` only in the accepted
     shape.
   - Add broker entry quantity resolution through a strategy-owned helper.
   - Add runtime fixtures for explicit `qty` overriding the default and absent
     `qty` using the default.
   - Add conformance metadata and docs.
7. Keep `strategy.percent_of_equity`, cash sizing, contracts, margin, and
   currency conversion unsupported unless selected by a later phase.

Exit criteria for design-only slice:

- The repo records a clear decision on default quantity scope and ordering.
- Unsupported default quantity variants have stable diagnostics if their syntax
  is already accepted by generic call handling.
- No compatibility claim changes occur.

Exit criteria for implementation slice:

- A fixed default quantity subset is fixture-backed across semantic analysis,
  runtime behavior, host surfaces, docs, and conformance metadata.
- Explicit `qty` behavior remains unchanged.

Slice 4 implementation record:

- Phase L accepts the fixed default quantity subset:
  `default_qty_type=strategy.fixed` with positive const numeric
  `default_qty_value`.
- `strategy.entry(id, strategy.long)` may omit `qty` only when that fixed
  default is configured; otherwise semantic analysis reports a stable arity
  diagnostic.
- Explicit `qty` remains supported and overrides the declaration default.
- `pine_ir::StrategySettings` owns the selected default quantity so CLI, Python,
  WASM, and Rust runtime entry points share the same behavior.
- Unsupported default quantity modes, including percent-of-equity-style string
  values, remain rejected. Cash sizing, contracts, margin, currency conversion,
  and percent-of-equity sizing stay outside Phase L.
- No runtime JSON, Python dictionary, or WASM JSON schema fields were added.

Verification:

```text
cargo test -p pine-builtins strategy
cargo test -p pine-sema strategy
cargo test -p pine-runtime strategy
cargo test --workspace
```

## Slice 5: Strategy Exit Design Gate

Goal: prepare for `strategy.exit` without accepting stop/limit behavior
prematurely.

This slice should stay design-only unless the project explicitly chooses a
small executable exit subset and can keep every broker rule fixture-backed.

Required design questions:

- Which first exit shape is useful and deterministic?
- Does `strategy.exit` create pending orders, or does it only become executable
  once stop/limit order simulation exists?
- If stop and limit orders are accepted, does the fill policy use OHLC traversal
  assumptions, bar-close-only behavior, or a conservative diagnostic boundary?
- How are partial exits represented in `orders`, `trades`, `position`, and
  `equity` outputs?
- How do repeated exit calls modify existing pending exits?
- How do exits interact with the current no-pyramiding single-position model?
- Do strategy state variables update after pending exit creation, only after
  fills, or both?

Steps:

1. Keep `strategy.exit` unsupported in conformance metadata during the design
   gate.
2. Add or refresh negative fixtures for stop, limit, profit, loss, trailing,
   partial quantity, and missing-entry cases.
3. Draft the first executable `strategy.exit` subset in this document or a
   dedicated strategy-exit design note.
4. Decide whether public strategy output needs pending order records before
   support lands.
5. Decide whether schema changes are required for pending orders, modified
   orders, partial fills, or exit reasons.
6. Do not implement runtime fills until the fill policy is precise enough to
   write small OHLC fixtures.

Exit criteria:

- `strategy.exit` remains unsupported with better documented boundaries, or a
  new implementation slice is drafted with precise semantics.
- No broad `strategy.*` claim is widened by accident.
- The next executable order slice has explicit fixture requirements before
  code starts.

Slice 5 design record:

- Phase L keeps `strategy.exit` unsupported. No runtime fills, pending orders,
  partial exits, public strategy output fields, Python dictionary keys, or WASM
  JSON fields are added in this slice.
- The first useful executable `strategy.exit` subset should be a future
  stop/limit pending-exit slice for the existing single long entry model. It
  must be full-position only at first: no partial quantity, no pyramiding, no
  shorts, no multiple open entries, no trailing exits, and no repeated-order
  modification semantics until each rule is fixture-backed.
- A future executable slice must decide whether the public `orders` array
  represents pending exit creation, fills only, or both before code starts. If
  pending orders are exposed, the schema needs explicit fields for order kind,
  linked entry id, pending/filled/canceled status, trigger prices, and optional
  exit reason.
- Fill policy remains the blocker. A later implementation must define exact
  OHLC traversal behavior, same-bar creation/fill handling, gap behavior,
  stop-vs-limit precedence when both are touched, and whether all fills are
  bar-close-only or price-triggered.
- Strategy state variables should update only when an exit fill mutates broker
  position state, not when a pending exit is merely created.
- Negative fixtures now cover `strategy.exit` stop, limit, profit/loss,
  trailing, partial quantity, and missing-entry forms. They all remain on the
  broad unsupported strategy-order path.

Verification:

```text
cargo test -p pine-sema strategy
cargo test --workspace
```

## Slice 6: Phase L Closeout

Goal: close the Phase L strategy usability subset and document maintenance
tails before adding richer broker mechanics.

Steps:

1. Run the full release verification gate.
2. Add `docs/PHASE_L_AUDIT.md` with:
   - completed slices
   - supported surface
   - public output and host behavior
   - fixture evidence
   - verification results
   - remaining maintenance tails
3. Update `docs/LONG_TERM_EXECUTION_PLAN.md`, `docs/CONFORMANCE.md`,
   `docs/LANGUAGE_SCOPE.md`, `docs/EXECUTION_SEMANTICS.md`, and
   `docs/RELEASE_NOTES.md` so they agree on the Phase L surface.
4. Refresh `tests/snapshots/matrix.json` if conformance metadata changed.
5. Confirm indicator runtime snapshots did not change unexpectedly.
6. Confirm Python and WASM host tests cover the same top-level behavior as CLI
   and Rust runtime tests.
7. Keep advanced strategy families explicit as maintenance tails.

Exit criteria:

- Strategy state variables are documented as partial and fixture-backed.
- Indicator and strategy modes remain separated.
- Public host behavior is synchronized across Rust runtime, CLI, Python, and
  WASM.
- Unsupported strategy order types and broker settings remain explicit.
- `scripts/verify.sh` passes.

Slice 6 closeout record:

- Phase L is closed for the current strategy usability subset.
- `docs/PHASE_L_AUDIT.md` records completed slices, supported surface, public
  host behavior, fixture evidence, verification results, and maintenance tails.
- `docs/LONG_TERM_EXECUTION_PLAN.md`, `docs/CONFORMANCE.md`,
  `docs/LANGUAGE_SCOPE.md`, `docs/EXECUTION_SEMANTICS.md`, and
  `docs/RELEASE_NOTES.md` now point to the same Phase L boundary.
- No runtime JSON, Python dictionary, or WASM JSON schema fields were added in
  Slice 6.

Verification:

```text
git diff --check
scripts/verify.sh
```

## Later Strategy Maintenance Tails

Do not start these until Phase L state variables are stable:

- `strategy.exit` stop/limit exits.
- Short entries and reversal behavior.
- `strategy.order` and richer order modification semantics.
- Pyramiding and multiple simultaneous entries.
- Commission, slippage, margin, currency conversion, cash sizing, and
  percent-of-equity sizing.
- Strategy reporting helpers beyond the first position/profit variables.
- Strategy closed-trade and open-trade namespaces.
- Strategy alerts and alert placeholders.
- Realtime strategy execution and forming-bar broker rollback.
