# Phase M Strategy Exit and Order Lifecycle Execution Plan

Status: Phase M is closed for the current fixture-backed stop/limit
`strategy.exit` subset. Use `docs/PHASE_M_AUDIT.md` as the closeout record
before adding future strategy-exit maintenance work.

Phase M widens the Phase G/L long-only strategy runtime from immediate market
entry/close behavior into a small, deterministic exit-order subset. Execute it
in small, mergeable slices. Each slice should leave the workspace shippable and
should keep semantic claims, broker behavior, public output contracts, fixtures,
snapshots, host bindings, conformance metadata, and docs in lockstep.

The first priority is `strategy.exit` design and implementation for the current
long-only broker model. Do not start this phase by adding short exposure,
reversals, pyramiding, commission, slippage, margin, currency conversion,
strategy alerts, or realtime strategy execution. Those features multiply broker
state before the project has a fixture-backed pending-exit lifecycle.

## Original Starting Point

The repository has already closed Phase G and Phase L for the first
fixture-backed strategy subset:

- `tests/fixtures/conformance.tsv` marks `strategy`, `strategy.entry`,
  `strategy.close`, strategy equity, and the first strategy state variables as
  `partial`.
- `tests/fixtures/conformance.tsv` keeps broad `strategy.*` as `unsupported`.
- `strategy(...)` supports `title`, `shorttitle`, `overlay`, `max_bars_back`,
  positive const numeric `initial_capital`, and fixed default quantity settings
  using `default_qty_type=strategy.fixed` plus positive const numeric
  `default_qty_value`.
- `strategy.entry(id, strategy.long, qty=...)` opens one long market position
  at the current bar close, with no pyramiding.
- `strategy.entry(id, strategy.long)` may omit `qty` only when the strategy
  declaration configures the supported fixed default quantity subset.
- `strategy.close(id)` closes the full matching long position at the current
  bar close and records a deterministic closed trade.
- Strategy-mode runtime output exposes a `strategy` object with `orders`,
  `trades`, `position`, `equity`, and `diagnostics` arrays.
- Indicator-mode runtime output does not include the top-level `strategy` key.
- `pine-runtime::strategy::BrokerState` already tracks initial capital, cash,
  position size, average price, entry identity, order events, closed trades,
  position snapshots, equity snapshots, runtime diagnostics, and read-only
  strategy state accessors.
- Strategy state variables are available in strategy-mode historical scripts:
  `strategy.position_size`, `strategy.position_avg_price`,
  `strategy.openprofit`, `strategy.netprofit`, and `strategy.equity`.
- At Phase M start, `strategy.exit` variants were fixture-backed unsupported
  cases.
- Historical and incremental execution are covered for strategy runtime
  fixtures. Realtime strategy broker handoff remains unsupported.

The current strategy-focused verification baseline is:

```text
cargo test -p pine-builtins strategy
cargo test -p pine-sema strategy
cargo test -p pine-runtime strategy
cargo test -p pine-cli strategy
cargo test -p pine-wasm strategy
python3 -m pytest python/tests
```

The request subsystem is not the primary Phase M target. Lower-timeframe
requests still need typed array return semantics and host output/data-shape
design. Drawing `polyline.*` still needs polyline runtime state and snapshots
beyond the current partial `chart.point` value and point-array subset.

## Rules for Every Slice

- Add fixtures before or alongside behavior changes.
- Keep the compatibility matrix conservative. Do not mark a `strategy.exit`
  subset `partial` unless the exact supported forms have positive runtime
  fixtures, negative semantic fixtures, public host coverage, and docs.
- Preserve indicator behavior. Indicator scripts must not gain broker state,
  strategy output fields, or strategy-mode-only order functions.
- Keep strategy-mode and indicator-mode diagnostics distinct. Strategy order
  functions should produce stable strategy-mode diagnostics when used from
  indicator scripts.
- Treat the broker as deterministic runtime state. Core crates must not depend
  on account services, wall-clock time, host callbacks, filesystem data, or
  network data.
- Keep fill policy explicit. If stop/limit trigger rules, same-bar ordering, or
  pending-order modification rules are not designed in a slice, keep them
  diagnostic-only.
- Prefer one complete exit path over several approximate order families.
- Do not silently approximate unsupported broker behavior. Short exposure,
  reversals, pyramiding, partial exits, trailing stops, commission, slippage,
  margin, currency conversion, and percent/cash/contracts sizing stay
  unsupported unless a slice explicitly designs and fixtures them.
- Keep CLI, Python, and WASM behavior synchronized. A script that compiles and
  runs through one public host should produce equivalent runtime JSON or native
  dictionary data through the others.
- Keep strategy orders out of requested-context expressions. The current
  request provider context is isolated and data-only.
- Keep strategy order calls rejected in UDFs under the existing side-effect
  policy unless a later phase deliberately changes that policy.
- Review `PUBLIC_RUNTIME_SCHEMA_VERSION` only when the shared runtime output
  shape changes. Reusing existing `orders`, `trades`, `position`, `equity`, and
  `diagnostics` fields may not require a schema bump; adding pending-order
  fields or changing item shapes probably does.
- Run the full release verification gate before closing a slice that changes a
  compatibility claim, public host contract, or public output contract.

## Internal Structure Rules

Phase M should grow the strategy subsystem without turning existing analyzer,
runtime, or output modules into catch-all broker files.

- Keep `pine-builtins` responsible for strategy declaration/order signatures and
  accepted constants. It should not own broker semantics.
- Keep `pine-sema::analyzer::strategy` responsible for strategy-mode gating,
  unsupported strategy variants, declaration settings, order argument checks,
  and strategy-specific diagnostic policy.
- Keep `pine-runtime::strategy` responsible for broker state, pending orders,
  fill rules, state accessors, profit calculations, and future broker rule
  helpers.
- Keep `pine-runtime::builtins::strategy` responsible for evaluating accepted
  strategy calls and refreshing strategy state variables after broker mutation.
- Keep `pine-runtime::output::strategy` limited to public result structs. It
  should not become the source of truth for broker transitions.
- Keep Python and WASM bindings thin. They should map the shared strategy
  result model and must not duplicate broker math or fill rules.
- Treat roughly 800 lines in a production Rust file as a review trigger. Split
  before adding another order family, trigger rule, or accounting path.
- Each slice should have an obvious review boundary: type metadata, semantic
  checks, broker model, runtime dispatch, fixtures, snapshots, docs,
  conformance metadata, and host tests should be inspectable independently.

## Intended Module Layout

Use existing crate boundaries. A new crate is not needed for Phase M.

Recommended layout:

```text
crates/pine-builtins/src/
   constants/strings.rs         strategy direction/order constants as needed
   namespaces/strategy.rs       declaration and accepted order signatures only

crates/pine-sema/src/analyzer/
   strategy.rs                  strategy mode checks and order validation
   expressions.rs               request/UDF side-effect gating if needed
   unsupported.rs               unsupported strategy variants and reasons

crates/pine-runtime/src/
   strategy/
      mod.rs                    broker facade and re-exports
      broker.rs                 broker state and high-level transitions
      orders.rs                 add if pending orders outgrow broker.rs
      fills.rs                  add when OHLC trigger rules need isolation
      limits.rs                 add only when pyramiding/quantity rules arrive
   builtins/
      strategy.rs               strategy call evaluation and symbol refresh hooks
   runtime/
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
   lib.rs                       returns shared strategy JSON only
```

Ownership notes:

- Pending exits should be broker state, not output state.
- Runtime output arrays are evidence of broker behavior after it happens. They
  should not drive broker decisions.
- Strategy variables should refresh from broker state after every supported
  broker mutation.
- The existing public `StrategyOrderEvent` may be enough for filled orders. If
  Phase M needs visible pending orders, add a deliberate public output shape and
  schema review instead of overloading filled-order events.

## Exit Semantics Direction

Phase M should start with exit forms that are derivable from the current
long-only broker state.

Initial target candidates:

- `strategy.exit(id, from_entry, stop=price)` for a full-position long stop
  exit.
- `strategy.exit(id, from_entry, limit=price)` for a full-position long limit
  exit.
- A later slice may accept both `stop` and `limit` on the same exit only after
  same-bar trigger precedence is designed and fixture-backed.

Initial visibility and lifecycle policy:

- `strategy.exit` is accepted only in strategy-mode scripts.
- Exit calls in indicator scripts remain semantic errors.
- Exit calls inside UDF bodies remain rejected as side effects.
- Exit calls inside requested-context expressions remain rejected.
- The first supported subset targets the one-net-long-position model.
- `from_entry` must identify the current supported long entry id.
- The first supported subset should close the full matching long position; no
  partial quantity support is claimed.
- A supported exit call creates or replaces a deterministic pending exit for the
  matching entry id. Repeated calls with the same `id` and `from_entry` update
  the pending exit rather than creating multiple active exits.
- Pending exits are evaluated on each historical bar after ordinary script
  statements for that bar, unless Slice 0 records a different deliberate
  ordering. The chosen ordering must be documented and covered by fixtures.
- Market `strategy.close(id)` continues to close immediately at the current bar
  close and cancels any pending exit for the closed entry.
- Pending exits are cancelled when their entry closes or when a future slice
  adds an explicit cancellation API.
- Realtime strategy exit behavior remains unsupported until broker rollback for
  forming bars is designed.

Initial long stop/limit fill policy candidates:

- Long stop exits trigger when the current bar low is less than or equal to the
  stop price and fill at the stop price.
- Long limit exits trigger when the current bar high is greater than or equal to
  the limit price and fill at the limit price.
- If both stop and limit are accepted on one exit, same-bar ambiguity must be
  resolved before support is claimed. A conservative first phase should reject
  combined stop/limit exits until precedence is designed.

Out of initial scope:

- Short entries and short exits.
- Reversal behavior.
- Pyramiding and multiple simultaneous entries.
- Partial exits through `qty`, `qty_percent`, or equivalent arguments.
- Trailing stops and `trail_*` arguments.
- Profit/loss tick abstractions unless a tick-size and entry-relative contract
  is designed.
- Commission, slippage, margin, currency conversion, and percent/cash/contracts
  sizing.
- Strategy order namespaces beyond the first `strategy.exit` subset.
- Strategy closed-trade/open-trade reporting namespaces.
- Strategy alerts.
- Realtime strategy execution and forming-bar broker rollback.

## Public Output Contract Direction

Phase M should prefer reusing the existing strategy output contract when
possible:

```text
strategy: {
  orders: [],
  trades: [],
  position: [],
  equity: [],
  diagnostics: []
}
```

Recommended first output policy:

- A triggered exit must append a closed trade and update position/equity
  snapshots. Whether it also appends a filled order event is a Slice 0 public
  contract decision, because the current `strategy.close` evidence model records
  a trade and flat-position snapshot but does not append a separate close order
  event.
- Creating or replacing a pending exit should not appear in public output unless
  the phase deliberately adds a pending-order output contract.
- Runtime diagnostics should report broker-state problems that cannot be caught
  semantically, such as a missing matching open entry when the call arguments
  are otherwise valid.
- If a new pending-order output field is added, or if existing order/trade item
  shapes need a field such as order type, source entry id, or exit id, review
  runtime schema version, CLI/WASM snapshots, Python dictionary tests, and docs
  in the same slice.

The first implementation should avoid adding a pending-order public field unless
downstream hosts need to inspect unfilled exits. Closed trades and equity curves
are usually enough to prove fill behavior for the initial runtime subset, but
the decision record must still state how an exit id and `from_entry` id are
represented in public trades and optional order events.

## How to Use the Acceptance Criteria

The exit criteria under each slice are local merge criteria for that slice.
Phase M should not be marked closed until a closeout audit records the supported
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

Maintenance tails may keep advanced order families, realtime broker rollback,
and rich broker settings out of scope. They must not weaken these Phase M
acceptance criteria:

- Strategy scripts can express a minimal deterministic protective or target
  exit for the current long-only order subset.
- Indicator and strategy modes remain clearly separated.
- Public host behavior remains synchronized across CLI, Python, and WASM.
- Unsupported strategy variants continue to produce stable diagnostics.
- Compatibility claims remain fixture-backed.

## Slice 0: Exit Boundary Audit

Goal: lock the current unsupported boundary and record exact first-slice
decisions before accepting any positive `strategy.exit` support.

Steps:

1. Keep broad `strategy.*` marked `unsupported` in conformance metadata.
2. Review the existing unsupported fixtures for `strategy.exit` variants:
   - stop exit.
   - limit exit.
   - profit/loss arguments.
   - trailing arguments.
   - partial quantity arguments.
   - missing or mismatched entry forms.
3. Add missing negative semantic fixtures before behavior changes if any of the
   planned unsupported boundaries are not fixture-backed.
4. Decide and record the first supported shape:
   - stop-only first, limit-only first, or both as separate supported forms.
   - whether combined `stop` plus `limit` remains unsupported initially.
   - whether `from_entry` is required.
   - whether `id` and `from_entry` must be const strings in the first subset.
5. Decide and record pending-exit lifecycle rules:
   - creation timing.
   - replacement semantics for repeated calls.
   - cancellation when the position closes.
   - behavior when no matching open entry exists.
6. Decide and record historical fill ordering:
   - whether pending exits are checked before or after script statements on the
     same bar.
   - whether a newly created exit can fill on the same bar.
7. Decide and record public output policy:
   - filled order/trade only.
   - or explicit pending-order output shape with schema review.
   - whether `StrategyTrade.id` stores the exit id, the source entry id, or
     remains entry-compatible with a documented limitation.
   - whether a visible exit order event is emitted, and if so what stable
     `direction` or order-type representation is used.
   - whether public structs need `fromEntry`, `orderType`, or similar fields; if
     they do, review `PUBLIC_RUNTIME_SCHEMA_VERSION` in the same slice.
8. Decide and record how semantic acceptance is staged:
   - Either Slice 1 adds a runtime placeholder that handles accepted
     `strategy.exit` calls without hitting the generic unsupported-runtime-call
     path, returns `void`, and emits a stable strategy diagnostic until broker
     behavior lands.
   - Or positive semantic acceptance is deferred until the first executable
     runtime slice, keeping all `strategy.exit` forms unsupported in Slice 1.
   - Do not merge a slice where an analyzer-accepted strategy script can fail
     only because runtime dispatch does not recognize `strategy.exit`.
9. Add a Phase M decision record section to this document before Slice 1.
10. Confirm no runtime JSON, Python dictionary, or WASM JSON shape changes occur
   in this slice.

Exit criteria:

- The first supported `strategy.exit` subset is precisely named.
- Unsupported `strategy.exit` variants remain stable and fixture-backed.
- Public output identity, order/trade field shape, and schema decisions are
  documented before code changes.
- The semantic/runtime staging decision prevents accepted scripts from reaching
  the generic unsupported runtime call path.
- The conformance matrix remains conservative.

Verification:

```text
cargo test -p pine-builtins strategy
cargo test -p pine-sema strategy
cargo test -p pine-runtime strategy
cargo test --workspace
```

## Phase M Decision Record

Fill this section during Slice 0 before accepting any positive
`strategy.exit` support. Later slices should update it only when an
implementation result deliberately differs from the recorded decision.

- First supported forms: `strategy.exit(id, from_entry, stop=price)` and
  `strategy.exit(id, from_entry, limit=price)` for the current one-net-long
  broker model.
- Combined stop plus limit: unsupported in Phase M. Slice 5 keeps the combined
  form rejected because a single historical bar can cross both `high >= limit`
  and `low <= stop` without fixture-backed intrabar path precedence.
- Required `from_entry`: required for the first subset. The call targets the
  currently open supported long entry; orphan pre-entry exits are not supported.
- `id` and `from_entry` qualifier requirements: both must follow the existing
  strategy id policy and be simple strings in the first subset.
- Pending-exit replacement key and lifecycle: broker state keeps at most one
  active pending exit for the current entry id. A later supported exit call for
  the same `from_entry` replaces the previous pending exit, including its exit
  id and price. Pending exits are cancelled when the entry closes through
  `strategy.close` or an exit fill.
- Missing matching entry behavior: semantically valid stop-exit calls with no
  matching current long entry produce a stable strategy runtime diagnostic and
  do not create an orphan pending order.
- Historical fill ordering: pending exits are evaluated after ordinary script
  statements for the bar and before the per-bar strategy equity snapshot.
- Same-bar newly-created-exit fill behavior: exits created or replaced on the
  current bar are not eligible to fill until a later bar. This avoids claiming
  intrabar ordering between a current-bar close entry and the same bar low/high.
- Public trade identity: `StrategyTrade.id` remains the source entry id for the
  first subset, matching the current `strategy.close` trade identity. The exit
  id remains internal unless a later public-contract slice deliberately adds a
  field.
- Public order event policy for exit fills: filled Phase M exits append a
  visible `StrategyOrderEvent` with the exit id and `strategy.exit` direction,
  while `StrategyTrade.id` remains the source entry id.
- Runtime schema version decision: no public output shape change is planned for
  the first subset, so `PUBLIC_RUNTIME_SCHEMA_VERSION` remains unchanged unless
  a later slice adds fields or pending-order output.
- Semantic/runtime staging decision: Slice 1 uses placeholder staging. Analyzer
  accepted stop-exit scripts must be recognized by runtime dispatch, return
  `void`, emit a stable strategy diagnostic, and avoid broker mutation until
  the pending-exit broker model and fills land.

## Slice 1: Strategy Exit Signature and Semantic Gate

Goal: add semantic support for the first `strategy.exit` subset without yet
changing broker fill behavior.

Initial scope:

- Strategy-mode scripts only.
- Historical strategy scripts only.
- One-net-long-position model only.
- Full-position exits only.
- No public output shape change.
- Runtime dispatch must either handle accepted calls with a stable placeholder
  diagnostic or this slice must defer positive acceptance until executable
  runtime behavior lands.

Steps:

1. Register the accepted `strategy.exit` signature in `pine-builtins` with only
   the first supported arguments.
2. Delegate `strategy.exit` calls to `pine-sema::analyzer::strategy` before
   generic call validation if needed.
3. Add strategy-mode gating:
   - accepted only when the script declaration is `strategy(...)`.
   - rejected in indicator scripts with `E_STRATEGY_MODE` or the existing
     strategy-mode diagnostic family.
4. Validate required arguments:
   - `id`.
   - `from_entry`, if Slice 0 requires it.
   - exactly one of `stop` or `limit`, if combined exits remain unsupported.
5. Validate first-subset argument families:
   - string ids according to the existing strategy entry/close policy.
   - numeric stop/limit values.
   - no `qty`, `qty_percent`, `profit`, `loss`, `trail_price`, `trail_points`,
     `trail_offset`, OCA arguments, comments, or alert arguments unless a slice
     explicitly accepts them.
6. Preserve side-effect restrictions:
   - reject inside UDF bodies.
   - reject as UDF arguments if the current policy rejects side-effecting calls.
   - reject inside requested-context expressions.
7. Add positive semantic fixtures for accepted stop-only or limit-only forms.
8. Keep negative semantic fixtures for unsupported variants.
9. If Slice 0 chose placeholder staging, add runtime dispatch for accepted
   `strategy.exit` calls that returns `void`, records a stable strategy
   diagnostic, and does not mutate broker state or public output.
10. If Slice 0 chose deferred acceptance, keep positive `strategy.exit` fixtures
    pending and leave the analyzer rejection path in place until the first
    executable runtime slice.
11. Do not update conformance metadata to `partial` until runtime behavior lands
    in a later slice.

Exit criteria:

- The analyzer accepts only the planned first `strategy.exit` subset.
- Indicator-mode and side-effect-context diagnostics are stable.
- Unsupported variants do not accidentally become accepted built-in calls.
- Analyzer-accepted scripts do not hit the generic unsupported runtime call path.
- Runtime behavior is unchanged except for an explicit placeholder diagnostic if
  Slice 0 selected placeholder staging.

Verification:

```text
cargo test -p pine-builtins strategy
cargo test -p pine-sema strategy
cargo test -p pine-runtime strategy
cargo test --workspace
```

## Slice 2: Pending Exit Broker Model

Goal: add broker-owned pending exit state without changing public output shape
or accepting fills yet.

Initial scope:

- One active pending exit for the current long entry, or a clearly documented
  map keyed by `(exit_id, from_entry)` if Slice 0 chooses multiple records.
- Stop-only or limit-only pending orders according to Slice 0.
- Full-position close only.
- Historical runtime only.

Steps:

1. Add a private broker model for pending exits:
   - exit id.
   - source entry id.
   - optional stop price.
   - optional limit price.
   - creation or last update bar index if useful for diagnostics.
2. Add broker methods such as:
   - `place_exit(...)`.
   - `cancel_exit_for_entry(...)`.
   - `pending_exit_count()` for tests if needed.
3. Make `strategy.close(id)` cancel pending exits for the closed entry.
4. Decide whether a repeated `strategy.entry` no-op leaves an existing pending
   exit untouched or cleared; document the chosen behavior.
5. Add unit tests around broker state transitions without OHLC fills:
   - place exit while flat.
   - place exit while long.
   - replace an existing exit.
   - close cancels exit.
   - mismatched entry id is a no-op or diagnostic according to Slice 0.
6. Keep runtime public output unchanged.
7. Keep conformance metadata unchanged.

Exit criteria:

- Pending exits are represented inside `pine-runtime::strategy`, not in output
  or host bindings.
- Existing `strategy.entry`, `strategy.close`, state variables, position
  snapshots, and equity snapshots remain unchanged for scripts without
  `strategy.exit`.
- Broker state transitions are deterministic and unit-tested.

Verification:

```text
cargo test -p pine-runtime strategy
cargo test --workspace
```

Slice 2 implementation note: repeated `strategy.entry` calls that are ignored
because the long-only broker already has an open position leave any existing
pending exit untouched. The only lifecycle events that mutate pending exits in
Slice 2 are accepted `strategy.exit` calls, which place or replace one pending
exit for the matching current entry id, and `strategy.close(id)`, which cancels
the pending exit for the closed entry. Slice 4 extends the same pending-exit
model to limit exits.

## Slice 3: Stop Exit Runtime Fill

Goal: implement the first filled `strategy.exit` behavior for long stop exits.

Initial scope:

- `strategy.exit(id, from_entry, stop=price)` only, unless Slice 0 selected a
  different first runtime path.
- Long-only full-position exit.
- Trigger on historical bar low crossing the stop price.
- Fill at the stop price.
- No public pending-order field.

Steps:

1. Add runtime dispatch for accepted `strategy.exit` calls in
   `pine-runtime::builtins::strategy`.
2. Evaluate `id`, `from_entry`, and `stop` arguments using existing call-arg
   helpers.
3. Place or replace a pending stop exit in `BrokerState`.
4. Add a broker method to evaluate pending exits against the current bar OHLC.
5. Call pending-exit evaluation at the bar ordering point decided in Slice 0.
6. On trigger:
   - append a filled order event with a stable direction/type representation.
   - append a closed trade using the stop price as exit price.
   - update cash, position, average price, and entry identity.
   - append a position snapshot if this matches existing close behavior.
   - clear the pending exit.
   - refresh strategy state variables so later visible state is correct at the
     next evaluation point.
7. Add runtime fixtures for:
   - stop not reached.
   - stop reached after entry.
   - stop reached on a later bar.
   - repeated stop call replacing the stop price.
   - `strategy.close` cancelling a pending stop before it triggers.
8. Add snapshots if the fixture participates in public runtime golden outputs.
9. Add incremental append coverage by relying on the existing all-runtime-fixture
   incremental test, and add a focused test if the generic fixture path is not
   enough.
10. Add CLI, Python, and WASM host tests that observe the same trade/equity
    result.
11. Update conformance metadata only when semantic, runtime, host, docs, and
    fixture coverage are all present.

Exit criteria:

- A long stop exit can close the current supported long position
  deterministically.
- Existing `strategy.close` behavior remains unchanged.
- Strategy state variables and equity snapshots agree with the triggered exit.
- Public host surfaces agree on the closed trade and equity output.
- The conformance row for the supported `strategy.exit` stop subset is partial
  and fixture-backed.

Verification:

```text
cargo test -p pine-builtins strategy
cargo test -p pine-sema strategy
cargo test -p pine-runtime strategy
cargo test -p pine-runtime --test incremental
cargo test -p pine-cli strategy
cargo test -p pine-wasm strategy
python3 -m pytest python/tests
cargo test --workspace
```

## Slice 4: Limit Exit Runtime Fill

Goal: implement the matching long limit exit subset after stop exits are stable.

Initial scope:

- `strategy.exit(id, from_entry, limit=price)` only.
- Long-only full-position exit.
- Trigger on historical bar high crossing the limit price.
- Fill at the limit price.
- No combined stop/limit exit unless Slice 0 explicitly selected it and Slice 3
  already covered ambiguity.

Steps:

1. Extend semantic validation to accept limit-only exits if it did not already.
2. Extend the pending exit model to carry a limit price.
3. Add long limit trigger evaluation against current bar high.
4. Fill at the limit price and reuse the same closed-trade/accounting path as
   stop exits.
5. Add runtime fixtures for:
   - limit not reached.
   - limit reached after entry.
   - repeated limit call replacing the limit price.
   - `strategy.close` cancelling a pending limit before it triggers.
6. Add host tests and snapshots matching Slice 3 expectations.
7. Update conformance metadata and docs for the limit subset.

Exit criteria:

- Stop and limit exits share the same broker accounting path.
- Limit fills are deterministic and fixture-backed.
- Unsupported combined exits remain rejected unless explicitly designed.

Verification:

```text
cargo test -p pine-sema strategy
cargo test -p pine-runtime strategy
cargo test -p pine-cli strategy
cargo test -p pine-wasm strategy
python3 -m pytest python/tests
cargo test --workspace
```

## Slice 5: Combined Stop/Limit Bracket Decision

Goal: either accept a narrow bracket exit with both `stop` and `limit`, or close
the combined form as intentionally unsupported for Phase M.

Steps:

1. Review stop-only and limit-only fixture results for same-bar ambiguity.
2. Decide whether Phase M should support combined `stop` plus `limit`.
3. If keeping unsupported:
   - keep semantic diagnostics stable.
   - add or retain a negative fixture.
   - document the reason in `docs/CONFORMANCE.md` and this plan.
4. If supporting combined exits:
   - define trigger precedence when both high and low cross on the same bar.
   - define output event ordering.
   - add fixtures for stop-only trigger, limit-only trigger, both-trigger same
     bar, replacement, and close cancellation.
   - update broker fill helpers instead of duplicating logic in runtime call
     dispatch.
   - update conformance metadata and docs.

Exit criteria:

- Combined stop/limit behavior is either explicitly unsupported or fully
  fixture-backed.
- There is no implicit same-bar ambiguity in the supported matrix.

Slice 5 decision: keep combined stop/limit exits unsupported for Phase M.
The stop-only and limit-only subsets are deterministic because each has a
single trigger condition and fill price. A combined bracket can hit both sides
on one historical bar, and this runtime does not model intrabar price path
precedence. The existing negative fixture remains the compatibility boundary.

Verification:

```text
cargo test -p pine-sema strategy
cargo test -p pine-runtime strategy
cargo test --workspace
```

## Slice 6: Interaction Hardening

Goal: harden the accepted exit subset across existing strategy and language
features.

Steps:

1. Add runtime fixtures for `strategy.exit` interactions with:
   - `if` branches.
   - `switch` expressions controlling prices or calls where supported.
   - `for` and `while` loops only if side-effect policy permits order calls in
     those statement contexts.
   - strategy state variables read before and after exit placement.
   - constant history references to strategy state after an exit.
2. Add negative fixtures for UDF side-effect contexts if they are not already
   covered.
3. Add incremental append assertions for every new runtime fixture through the
   existing fixture runner.
4. Add profile fixture coverage if pending-exit state introduces new storage
   growth risk.
5. Confirm `scripts/check_structure.py` still accepts the strategy module
   layout, or update the structure guard deliberately if new strategy-owned
   modules are added.
6. Update docs with the exact supported interaction contexts.

Exit criteria:

- The supported exit subset behaves consistently inside claimed control-flow
  contexts.
- UDF/request side-effect boundaries remain stable.
- Incremental append execution matches full historical execution for exit
  fixtures.
- Storage growth remains bounded and visible if new profile fields are needed.

Verification:

```text
cargo test -p pine-sema strategy
cargo test -p pine-runtime strategy
cargo test -p pine-runtime --test incremental
cargo test -p pine-runtime --test profile_fixtures
python3 scripts/check_structure.py
cargo test --workspace
```

## Slice 7: Public Contract and Snapshot Hardening

Goal: make sure the public strategy contract is intentional and synchronized
after exit fills are visible.

Steps:

1. Review `StrategyOrderEvent`, `StrategyTrade`, `StrategyPositionSnapshot`,
   and `StrategyEquitySnapshot` for whether existing fields explain exit fills
   clearly enough.
2. If a field is added or renamed:
   - review `PUBLIC_RUNTIME_SCHEMA_VERSION`.
   - update shared JSON serialization.
   - update CLI golden snapshots.
   - update WASM golden snapshots or runtime tests.
   - update Python dictionary mapping and key-contract tests.
3. If no field changes are needed:
   - add a short decision note to this plan or the future closeout audit.
4. Refresh matrix snapshots only through the documented commands.
5. Run cross-host tests for a representative stop exit and limit exit.

Exit criteria:

- CLI, Python, and WASM expose equivalent exit results.
- Snapshot diffs are intentional and reviewed.
- Runtime schema versioning is documented either as unchanged or deliberately
  bumped.

Slice 7 decision: keep `PUBLIC_RUNTIME_SCHEMA_VERSION` unchanged. Filled
strategy exits are fully represented by the existing `orders`, `trades`,
`position`, `equity`, and `diagnostics` strategy fields: the exit order id is
visible in `orders`, the source entry id remains visible in `trades`, and no
public pending-order, partial-fill, or exit-reason field is added in Phase M.

Verification:

```text
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli runtime_outputs_match_golden_snapshots
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli matrix_output_matches_golden_snapshot
UPDATE_SNAPSHOTS=1 cargo test -p pine-wasm analysis_outputs_match_golden_snapshots
cargo test -p pine-cli strategy
cargo test -p pine-wasm strategy
python3 -m pytest python/tests
cargo test --workspace
```

Run snapshot refresh commands only when a public output or matrix change is
intentional. Review the JSON diff before keeping refreshed snapshots.

## Slice 8: Closeout Audit

Goal: close Phase M only after the supported strategy exit subset is documented,
fixture-backed, and verified across hosts.

Steps:

1. Create `docs/PHASE_M_AUDIT.md` with:
   - completed slices.
   - supported `strategy.exit` surface.
   - public output and host behavior.
   - fixture evidence.
   - verification results.
   - remaining maintenance tails.
   - structure check notes.
2. Update `docs/LONG_TERM_EXECUTION_PLAN.md` to mark Phase M closed or to record
   any deferred slices.
3. Update `docs/CONFORMANCE.md`, `docs/LANGUAGE_SCOPE.md`,
   `docs/EXECUTION_SEMANTICS.md`, and `docs/RELEASE_NOTES.md` so they agree on
   the exact supported exit subset.
4. Update `README.md` design-document links if the audit should be discoverable
   from the top-level docs list.
5. Run the full release verification gate.
6. Record the verification command and result in the audit.

Exit criteria:

- Phase M has a closeout audit matching the style of previous phases.
- The conformance matrix is the source of truth for supported and unsupported
  strategy exit behavior.
- Unsupported strategy variants remain explicit maintenance tails.
- `scripts/verify.sh` passes on the closeout workspace.

Verification:

```text
git diff --check
scripts/verify.sh
```

## Maintenance Tails

These should remain out of scope until selected as a later phase or a deliberate
Phase M extension:

- Short entries, reversals, and short exposure.
- `strategy.order` and richer order modification semantics.
- Multiple simultaneous entries and pyramiding.
- Partial exits and quantity reservation behavior.
- Trailing stops.
- Profit/loss tick helpers if they require mintick, entry-relative conversion,
  or same-bar precedence rules beyond the first stop/limit subset.
- Commission, slippage, margin, currency conversion, cash sizing, contracts,
  and percent-of-equity sizing.
- Strategy closed-trade and open-trade namespaces.
- Strategy alerts and alert placeholders.
- Realtime strategy execution and forming-bar broker rollback.
- Host-specific broker APIs or chart UI behavior outside the public runtime
  contract.

## Suggested Commit Order

1. `Document strategy exit phase plan`
2. `Lock strategy exit unsupported boundary`
3. `Accept narrow strategy.exit semantics`
4. `Add pending exit broker state`
5. `Implement long stop exits`
6. `Implement long limit exits`
7. `Resolve bracket exit boundary`
8. `Harden strategy exit interactions`
9. `Harden strategy exit public contract`
10. `Close Phase M strategy exit audit`
