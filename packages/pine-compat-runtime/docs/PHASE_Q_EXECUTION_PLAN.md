# Phase Q Strategy Exit Bracket Design Gate Execution Plan

Status: closed. Use `docs/PHASE_Q_AUDIT.md` as the closeout record for this
design gate, `docs/PHASE_P_AUDIT.md` as the baseline closeout record for the
current strategy broker structure, and `docs/PHASE_O_AUDIT.md` as the baseline
for the current strategy reporting count subset.

Phase Q should decide the next `strategy.exit` bracket semantics without
opening a larger broker-simulation phase too early. The executable target is a
design gate and diagnostic-hardening pass: keep combined trigger exits
unsupported while documenting the exact decisions needed before any future
positive bracket support can be claimed.

Each slice should leave the workspace shippable. Phase Q should not widen the
compatibility matrix by default. If a slice adds fixtures, those fixtures should
be diagnostic-only unless a later phase deliberately implements fixture-backed
runtime behavior. Public JSON, Python, and WASM output contracts should remain
unchanged throughout this design gate.

## Current Starting Point

The repository has closed Phase G, Phase L, Phase M, Phase N, Phase O, and
Phase P for the current strategy subset:

- `tests/fixtures/conformance.tsv` marks `strategy`, `strategy.entry`,
  `strategy.close`, strategy equity, strategy state variables,
  `strategy.closedtrades`, `strategy.opentrades`, and `strategy.exit` as
  `partial`.
- Broad `strategy.*` remains `unsupported`.
- `strategy(...)` supports `title`, `shorttitle`, `overlay`, `max_bars_back`,
  positive const numeric `initial_capital`, and fixed default quantity settings
  through `default_qty_type=strategy.fixed` plus positive const numeric
  `default_qty_value`.
- `strategy.entry(id, strategy.long, qty=...)` opens one long market position
  at the current bar close, with no pyramiding.
- `strategy.close(id)` closes the full matching long position at the current
  bar close and cancels any matching pending exit.
- Strategy state variables are available in strategy-mode historical scripts:
  `strategy.position_size`, `strategy.position_avg_price`,
  `strategy.openprofit`, `strategy.netprofit`, `strategy.equity`,
  `strategy.closedtrades`, and `strategy.opentrades`.
- `strategy.exit(id, from_entry, stop=price)`,
  `strategy.exit(id, from_entry, limit=price)`,
  `strategy.exit(id, from_entry, profit=ticks)`, and
  `strategy.exit(id, from_entry, loss=ticks)` are supported for one
  broker-owned pending full-position exit on the current one-net-long entry.
- Stop/loss exits fill on a later historical bar when `low <= exit_price`.
  Limit/profit exits fill on a later historical bar when `high >= exit_price`.
- New or replaced pending exits are not eligible on the same bar. Unchanged
  repeated exit calls preserve the original eligibility bar.
- Pending exits are evaluated after script statements for the current
  historical bar. Filled pending exits are visible to public strategy output
  and equity for that bar, but normal script reads of strategy variables see
  the updated state on the next bar.
- Filled exits append the existing public `strategy.orders`,
  `strategy.trades`, `strategy.position`, and `strategy.equity` data.
- Runtime output remains `schemaVersion: 3`.
- Phase P split strategy broker internals into:

  ```text
  crates/pine-runtime/src/strategy/
     mod.rs
     broker/
        mod.rs
        exits.rs
        fills.rs
        accounting.rs
        tests.rs
  ```

- `BrokerState` remains the strategy runtime facade exported by
  `pine-runtime`.
- `broker/exits.rs` owns pending-exit identity, trigger helpers, exit
  placement, replacement, runtime diagnostics, and profit/loss tick conversion.
- `broker/mod.rs` owns entry handling, pending-exit evaluation, and public
  result projection.
- `broker/fills.rs` owns close/fill trade construction and position reset.
- `broker/accounting.rs` owns equity snapshots, open/realized/equity values,
  position accessors, and closed/open trade count accessors.
- `crates/pine-sema/src/analyzer/strategy.rs` rejects combined trigger
  families for the current `strategy.exit` subset.
- Existing unsupported semantic fixtures cover common combined trigger forms:
  `unsupported_strategy_exit_stop_limit.pine`,
  `unsupported_strategy_exit_profit_loss.pine`,
  `unsupported_strategy_exit_stop_profit.pine`,
  `unsupported_strategy_exit_limit_loss.pine`,
  `unsupported_strategy_exit_stop_loss.pine`,
  `unsupported_strategy_exit_limit_profit.pine`, and
  `unsupported_strategy_exit_three_triggers.pine`.

The strategy-focused verification baseline is:

```text
cargo test -p pine-builtins strategy
cargo test -p pine-sema strategy
cargo test -p pine-runtime strategy
cargo test -p pine-runtime --test incremental
cargo test -p pine-runtime --test profile_fixtures
cargo test -p pine-cli strategy
cargo test -p pine-wasm strategy
python3 -m pytest python/tests
```

The release closeout gate remains:

```text
git diff --check
scripts/verify.sh
```

## Phase Q Goal

The main goal is to close the bracket design gap before implementing any
combined trigger support:

- Keep every combined `strategy.exit` trigger form unsupported in Phase Q.
- Document the exact bracket forms that may be eligible for a future positive
  support phase.
- Decide how stop/limit prices and profit/loss tick distances map into one
  broker-owned bracket order for the current long-only broker.
- Decide same-bar high/low precedence for a bar whose OHLC range touches both
  bracket legs.
- Decide whether same-bar both-hit behavior should be deterministic support,
  a runtime diagnostic, or deferred until a richer intrabar path model exists.
- Decide how bracket identity interacts with the current one-pending-exit
  model, replacement rule, and unchanged repeated calls.
- Decide how future bracket fills should appear in the existing public
  `strategy.orders`, `strategy.trades`, `strategy.position`, and
  `strategy.equity` arrays without adding public pending-order fields.
- Keep public host schemas unchanged unless a later phase deliberately opens a
  schema review.
- Produce a future implementation blueprint that can be executed as small,
  fixture-backed slices after the design gate closes.

Phase Q is successful when the repository has a stable written decision record
for combined trigger exits, existing unsupported fixtures still pass, and the
next implementation phase can start without re-litigating bracket identity or
same-bar precedence.

## Decision Record To Close In Phase Q

Confirm or fill these decisions before any future bracket implementation
changes semantic acceptance or runtime behavior:

- Phase Q is a design-gate phase by default.
- No `tests/fixtures/conformance.tsv` status is widened during Phase Q.
  Diagnostic-only fixtures may only be added to existing unsupported or
  partial rows without changing status.
- `strategy.exit` remains exactly stop-only, limit-only, profit-only, or
  loss-only for executable behavior during Phase Q.
- Combined trigger forms remain diagnostic-only unsupported during Phase Q.
- Public runtime output remains `schemaVersion: 3`.
- `StrategyResult`, `StrategyOrderEvent`, `StrategyTrade`,
  `StrategyPositionSnapshot`, and `StrategyEquitySnapshot` shapes do not
  change.
- The existing long-only no-pyramiding broker remains the only broker model in
  scope for a future first bracket subset.
- A future first bracket subset, if selected, should be full-position only.
- A future first bracket subset should not add partial quantity reservation,
  multiple entries, multiple active pending exits, or public pending-order
  records.
- Profit/loss tick values, if combined into a future bracket, should use the
  same fixed default `syminfo.mintick` source as Phase N unless a later phase
  deliberately widens chart metadata.
- Stop/loss legs should remain downside triggers for the current long-only
  broker. Limit/profit legs should remain upside triggers for the current
  long-only broker.
- The design must explicitly choose one same-bar both-hit policy before
  support is claimed. Acceptable outcomes include a deterministic fill
  precedence, a runtime diagnostic for ambiguous bars, or continued deferral.
- The design must explicitly choose whether `stop + limit`, `profit + loss`,
  and mixed price/tick pairs are all order brackets or whether some pairs stay
  unsupported.
- The design must explicitly choose future bracket expression evaluation order
  and failure behavior before support is claimed.
- The design must explicitly choose how an unchanged repeated bracket call
  preserves eligibility and how a changed bracket call resets eligibility.
- The design must explicitly choose how replacing a single-trigger pending exit
  with a bracket, or replacing a bracket with a single-trigger exit, behaves.
- The design must explicitly choose how future bracket fills update
  `strategy.closedtrades`, `strategy.opentrades`, `strategy.netprofit`, and
  `strategy.equity` read timing.
- If any slice reveals a behavior bug in the existing single-trigger subset,
  stop the design gate, add a regression fixture or unit test, and decide
  whether to fix it as a separate behavior slice.

## Design Questions

Use these questions as the working checklist for the design slices.

Trigger family questions:

- Should `stop + limit` be the first supported bracket form?
- Should `profit + loss` be supported in the same first bracket subset, or wait
  until price-based brackets land?
- Should mixed forms such as `stop + profit`, `limit + loss`, `stop + loss`,
  and `limit + profit` remain unsupported even after basic brackets land?
- Are three-trigger and four-trigger forms always unsupported for the current
  broker model?

Price conversion questions:

- Are profit/loss tick distances converted at placement time from the current
  `strategy.position_avg_price`?
- If the position average changes in a future pyramiding phase, do existing
  bracket prices stay fixed or recompute?
- Should invalid tick distances produce the existing runtime diagnostics before
  bracket identity or replacement is evaluated?
- If one future bracket leg evaluates to an invalid value and the other leg is
  valid, is the whole bracket rejected or does the valid leg become a
  single-trigger exit?
- Are both accepted bracket leg expressions evaluated before broker placement,
  and in what order are runtime diagnostics emitted?

Identity and replacement questions:

- Is a bracket identified by `id + from_entry`, with both legs owned by one
  pending exit record?
- Is changing either leg enough to reset `last_update_bar_index` and make the
  bracket ineligible on the replacement bar?
- Does repeating the identical bracket preserve the original eligibility bar,
  matching the current single-trigger behavior?
- Does replacing a pending single stop with `stop + limit` preserve the stop
  leg's eligibility or create a new bracket with a new eligibility bar?
- Does replacing a bracket with a single-trigger exit cancel the unused bracket
  leg immediately?

Same-bar precedence questions:

- When both low and high touch bracket legs on the same historical bar, which
  leg fills?
- Should precedence depend on the bar open, entry price, leg distance, or a
  fixed conservative rule?
- Should both-hit bars be rejected with a runtime diagnostic until intrabar
  path data exists?
- If a deterministic rule is chosen, how is it documented so snapshot changes
  are explainable?

Timing questions:

- Does a newly created bracket remain ineligible on the creation bar, matching
  the current single-trigger exit rule?
- Are pending brackets still evaluated after script statements on each
  historical bar?
- Do script reads on a triggering bar see pre-fill state while public strategy
  output for that bar includes the fill?
- Do next-bar reads of strategy variables see closed/open trade counts and
  profit/equity after a bracket fill?

Public contract questions:

- Does a bracket fill emit exactly one `strategy.exit` order event using the
  exit id?
- Does the resulting closed trade remain keyed by the source entry id?
- Is the filled leg visible only through price/profit in the existing order and
  trade records, with no explicit exit-reason field?
- Is a public exit-reason field deferred until a separate schema review?
- Do CLI, Python, and WASM keep identical output shapes?

Scope questions:

- Does bracket support require multiple active pending exits? The preferred
  answer for the first future subset should be no.
- Does bracket support require partial quantity or reservation semantics? The
  preferred answer for the first future subset should be no.
- Does bracket support require missing-entry pre-placement? The preferred
  answer for the first future subset should be no.
- Does bracket support require short exposure or reversals? The preferred
  answer for the first future subset should be no.

## Non-Goals

Do not include these in the Phase Q compatibility claim:

- Supporting combined stop/limit, profit/loss, or mixed trigger brackets at
  runtime.
- Widening semantic acceptance for combined trigger families.
- Changing current stop-only, limit-only, profit-only, or loss-only behavior.
- Adding same-bar bracket fill behavior before the design record is closed.
- Supporting trailing stops.
- Supporting partial exits, `qty`, `qty_percent`, reservation behavior, or
  multiple active exit orders.
- Supporting missing-entry pre-placement.
- Supporting short entries, reversals, or pyramiding.
- Supporting `strategy.order` or richer order modification APIs.
- Adding commission, slippage, margin, currency conversion, cash sizing,
  contracts, percent-of-equity sizing, or broker setting emulation.
- Adding public open-trade records, pending-order records, partial-fill fields,
  exit-reason fields, or strategy metric output fields.
- Adding strategy alerts, alert placeholders, or host delivery APIs.
- Adding realtime strategy execution or forming-bar broker rollback.
- Renaming public output fields or bumping runtime schema versions.

## Rules For Every Slice

- Keep the compatibility matrix conservative. Do not widen a strategy row
  unless a later phase has semantic fixtures, runtime fixtures, host coverage,
  conformance metadata, docs, and verification evidence for that exact form.
- Preserve indicator behavior. Indicator scripts must not gain broker state or
  strategy output fields.
- Preserve requested-context isolation. Strategy order calls and strategy state
  variables remain rejected in requested expressions.
- Preserve UDF side-effect policy. Strategy order calls remain rejected inside
  UDFs.
- Keep unsupported combined trigger forms diagnostic-only in Phase Q.
- If adding diagnostic-only fixtures, update conformance metadata only to
  reference fixtures inside existing unsupported or partial rows. Do not widen
  status.
- Keep runtime snapshots unchanged. A changed runtime snapshot during Phase Q
  is a regression unless a later approved behavior slice explains it.
- Keep public schemas unchanged. Any proposal to expose pending orders,
  exit-reason fields, or bracket-leg metadata belongs in a separate schema
  review.
- Keep Python and WASM bindings thin. They should not learn broker bracket
  rules during this design gate.
- Prefer phase-neutral diagnostics. User-visible messages should describe the
  current supported subset, not an old phase or slice number.
- Keep docs in the same change as any decision that affects future strategy
  work.
- Run the full release verification gate before closing Phase Q if any code,
  fixtures, snapshots, or conformance metadata changed.

## Internal Structure Rules

Phase Q should work with the Phase P broker structure and should not move
runtime ownership to the wrong crate.

- Keep `pine-builtins` responsible for strategy declarations, order
  signatures, and accepted constants. It should not own broker behavior.
- Keep `pine-sema::analyzer::strategy` responsible for strategy-mode gating,
  unsupported variants, declaration settings, order argument checks, and
  strategy-specific diagnostics.
- Keep `pine-runtime::builtins::strategy` responsible for extracting runtime
  call arguments and dispatching accepted calls into the broker facade.
- Keep `pine-runtime::builtins::variables` responsible for reading accepted
  strategy state variables from broker accessors.
- Keep `pine-runtime::strategy::broker` responsible for broker state and
  public broker methods.
- Keep pending-exit identity, trigger conversion, and future bracket leg
  structures in `broker/exits.rs`.
- Keep trigger evaluation orchestration in `broker/mod.rs` unless future
  bracket logic grows enough to justify a dedicated broker-internal module.
- Keep fill construction and position reset in `broker/fills.rs`.
- Keep equity, profit, position, and count accessors in `broker/accounting.rs`.
- Keep `pine-runtime::output::strategy` limited to public result structs. It
  should not become the source of truth for broker transitions.

## Future Implementation Shape To Evaluate

Phase Q should not implement this shape, but it should leave enough detail for
the next phase to execute safely.

Potential future runtime layout:

```text
crates/pine-runtime/src/
   strategy/
      broker/
         mod.rs               BrokerState facade and pending-exit evaluation
         exits.rs             PendingExit, trigger/bracket leg types,
                              placement, replacement, tick conversion
         fills.rs             single fill construction and position reset
         accounting.rs        equity/profit/state/count accessors
         tests.rs             broker-focused single-trigger and bracket tests
   builtins/
      strategy.rs             runtime call extraction and facade dispatch
      variables.rs            strategy variable reads only
   output/
      strategy.rs             no bracket-specific fields in the first subset
```

Potential future broker data model options:

- Option A: extend `PendingExitTrigger` into a single-trigger or two-leg
  bracket enum. This keeps one `pending_exit` slot and fits the current
  one-net-long broker.
- Option B: store two pending triggers inside `PendingExit` as optional stop
  and limit legs. This is explicit but must avoid looking like support for
  multiple independent pending exits.
- Option C: introduce a pending-order collection. This should be deferred
  until multiple entries, partial exits, or order reservation behavior are in
  scope.

Phase Q should record which option is preferred for the first future bracket
implementation and why the others remain deferred.

## Slice 0: Baseline Lock And Design-Gate Confirmation

Goal: lock the Phase P baseline and confirm that Phase Q is a design gate, not
a bracket implementation phase.

Steps:

1. Review `docs/PHASE_P_AUDIT.md` and confirm the structural broker split is
   closed.
2. Review `docs/PHASE_O_AUDIT.md` and confirm strategy count behavior remains
   the latest reporting baseline.
3. Review strategy rows in `tests/fixtures/conformance.tsv`, especially
   `strategy`, `strategy.exit`, and `strategy.*`.
4. Review existing combined-trigger fixtures under `tests/fixtures/sema/`:
   - `unsupported_strategy_exit_stop_limit.pine`
   - `unsupported_strategy_exit_profit_loss.pine`
   - `unsupported_strategy_exit_stop_profit.pine`
   - `unsupported_strategy_exit_limit_loss.pine`
   - `unsupported_strategy_exit_stop_loss.pine`
   - `unsupported_strategy_exit_limit_profit.pine`
   - `unsupported_strategy_exit_three_triggers.pine`
5. Review `crates/pine-sema/src/analyzer/strategy.rs` to confirm combined
   trigger families are rejected before runtime behavior is reachable.
6. Review `crates/pine-runtime/src/strategy/broker/exits.rs` to confirm the
   current broker stores one single-trigger pending exit.
7. Review `crates/pine-runtime/src/strategy/broker/mod.rs` to confirm pending
   exits are evaluated after creation-bar eligibility checks.
8. Review `crates/pine-runtime/src/builtins/strategy.rs` to confirm runtime
   dispatch currently selects the first supported trigger family.
9. Record Slice 0 findings in `docs/PHASE_Q_AUDIT.md` or in a temporary
   baseline section in this document before continuing.
10. Confirm that Phase Q will not update conformance status or runtime output
    snapshots unless a diagnostic-only fixture or documentation-only snapshot
    change is explicitly required.

Acceptance criteria:

- The team agrees that Phase Q is a design gate.
- The baseline review leaves an auditable written artifact.
- Existing stop-only, limit-only, profit-only, and loss-only behavior remains
  unchanged.
- Existing combined trigger fixtures remain diagnostic-only.
- Public runtime schema and host output shapes are unchanged.

Suggested verification:

```text
cargo test -p pine-sema strategy
cargo test -p pine-runtime strategy::broker
git diff --check
```

## Slice 1: Unsupported Boundary And Diagnostic Hardening

Goal: keep combined trigger exits unsupported while making the diagnostic
boundary stable and phase-neutral.

Steps:

1. Inspect `validate_strategy_exit_args` in
   `crates/pine-sema/src/analyzer/strategy.rs`.
2. Replace user-visible diagnostic messages that mention old phase names or
   slice numbers with current-subset wording. Suggested messages:
   - positional `profit`/`loss` rejection:
     `` `strategy.exit` profit and loss arguments must be named arguments ``
   - unsupported option rejection:
     `` `strategy.exit` argument `{name}` is not supported in the current strategy subset ``
   - combined trigger rejection:
     `` `strategy.exit` combined trigger families are not supported in the current strategy subset ``
3. Keep diagnostic codes unchanged unless a separate diagnostic-versioning
   review approves a code change.
4. Confirm existing tests assert diagnostic codes and still pass.
5. Add a diagnostic-only four-trigger fixture so the unsupported boundary
   covers the maximal `stop + limit + profit + loss` trigger family directly.
6. If adding a new fixture, update `crates/pine-sema/tests/fixtures.rs` and
   `tests/fixtures/conformance.tsv` fixture references without changing status.
7. Do not change runtime behavior.
8. Do not refresh runtime snapshots.

Acceptance criteria:

- Diagnostics no longer mention stale phase or slice names.
- All existing combined-trigger fixtures still fail with stable diagnostic
  codes.
- Any new fixture is diagnostic-only and referenced conservatively.
- No runtime output changes occur.

Suggested verification:

```text
cargo test -p pine-sema strategy
cargo test -p pine-cli conformance_metadata_references_existing_fixtures
git diff --check
```

## Slice 2: Bracket Semantics Decision Record

Goal: decide the exact semantics required before future bracket support can be
implemented.

Steps:

1. Add a decision record section to this document or create
   `docs/PHASE_Q_AUDIT.md` if closing the design gate in the same change.
2. Decide the first future bracket form set. Recommended candidates to compare:
   - price bracket only: `stop + limit`
   - tick bracket only: `profit + loss`
   - both canonical pairs: `stop + limit` and `profit + loss`
   - mixed pairs too, only if they can be explained without adding order
     reservation semantics
3. Decide whether three-trigger and four-trigger calls remain unsupported.
4. Decide whether profit/loss distances are converted once at placement time.
5. Decide future bracket expression evaluation and invalid-leg behavior:
   - whether selected leg expressions are evaluated stop/limit before
     profit/loss, source order, or a broker-neutral canonical order
   - whether one invalid leg rejects the whole bracket
   - whether runtime diagnostics happen before identity comparison and
     replacement
   - whether invalid bracket placement leaves an existing pending exit
     unchanged
6. Decide the pending-exit data model for future support:
   - one pending bracket record with two legs
   - one pending record with a trigger enum that can be single or bracket
   - multiple pending order records, deferred unless a larger broker phase is
     opened
7. Decide bracket identity and replacement rules:
   - unchanged repeated bracket call preserves eligibility
   - changed leg price resets eligibility
   - changed id or from_entry replaces the pending exit only through existing
     supported order semantics
   - replacing a single trigger with a bracket creates a new pending exit
   - replacing a bracket with a single trigger cancels the unused leg
8. Decide same-bar both-hit policy. Document all considered options and the
   selected one:
   - stop-first conservative fill
   - limit-first optimistic fill
   - open-proximity or assumed intrabar path rule
   - runtime diagnostic for ambiguous bars
   - continued unsupported bracket behavior until intrabar data exists
9. Decide fill output behavior:
   - one `strategy.exit` order event per bracket fill
   - one closed trade under the source entry id
   - no public pending-order record
   - no exit-reason field in the first future subset unless schema review is
     opened
10. Decide state-variable timing after future bracket fills:
   - script reads on the triggering bar see pre-fill state
   - output/equity on the triggering bar include the fill after pending-exit
     evaluation
   - next-bar reads see updated `closedtrades`, `opentrades`, `netprofit`, and
     `equity`
11. Record which larger broker tails remain deferred and why.

Acceptance criteria:

- Every design question in this document has an explicit answer or a documented
  deferral.
- The selected future first bracket subset can be tested without adding public
  output fields.
- Future invalid-leg and diagnostic ordering behavior is specified enough to
  write broker unit tests before runtime fixtures.
- Same-bar both-hit behavior is no longer ambiguous in the written design.
- The design does not require partial exits, pyramiding, short exposure,
  missing-entry pre-placement, or realtime broker rollback.

Suggested verification:

```text
git diff --check
```

## Slice 3: Future Fixture Plan

Goal: define the exact fixtures a later positive bracket implementation must
add before claiming support.

Steps:

1. Write a fixture inventory in this document or in the future implementation
   phase plan.
2. Define positive semantic fixtures for any future accepted bracket forms,
   for example:
   - `tests/fixtures/sema/supported_strategy_exit_stop_limit.pine`
   - `tests/fixtures/sema/supported_strategy_exit_profit_loss.pine`
3. Keep unsupported semantic fixtures for any combined forms deliberately left
   out of the first future subset.
4. Define runtime fixtures for normal bracket behavior:
   - bracket created on one bar and neither leg touched on creation bar
   - limit/profit leg fills on a later bar
   - stop/loss leg fills on a later bar
   - unchanged repeated bracket preserves original eligibility
   - changed bracket leg resets eligibility
   - replacing single-trigger exit with bracket
   - replacing bracket with single-trigger exit
5. Define a runtime fixture for same-bar both-hit behavior using a deliberately
   small OHLC series where high and low touch both legs on the same bar.
6. Define runtime fixtures for strategy variable reads around bracket fills:
   - `strategy.position_size`
   - `strategy.position_avg_price`
   - `strategy.openprofit`
   - `strategy.netprofit`
   - `strategy.equity`
   - `strategy.closedtrades`
   - `strategy.opentrades`
7. Define interaction fixtures for branch, switch, for, while, pure UDF
   arguments, and constant history references only if the future subset claims
   those expression contexts.
8. Define incremental append coverage for all future runtime fixtures that
   affect broker state.
9. Define host smoke tests for CLI snapshots, Python dictionaries, and WASM
   JSON only after runtime fixtures are stable.
10. Define snapshot refresh commands but do not run them during Phase Q unless
    actual runtime fixtures are added by a later behavior phase.

Acceptance criteria:

- The future implementation phase can start with a named fixture list.
- Same-bar both-hit behavior has a dedicated fixture requirement.
- Host and incremental coverage are included in the future fixture plan.
- Phase Q still does not claim positive bracket support.

Suggested verification:

```text
git diff --check
```

## Slice 4: Future Implementation Blueprint

Goal: de-risk the first future bracket implementation by mapping changes to
specific modules without editing runtime behavior in Phase Q.

Steps:

1. Document the semantic changes a future implementation would need in
   `crates/pine-sema/src/analyzer/strategy.rs`:
   - accept only the selected bracket trigger pairs
   - keep unsupported pairs diagnostic-only
   - keep trailing and partial quantity arguments unsupported
   - keep strategy-mode, requested-context, and UDF side-effect policy
     unchanged
2. Document the built-in signature considerations in
   `crates/pine-builtins/src/namespaces/strategy.rs`:
   - current optional `stop`, `limit`, `profit`, and `loss` parameters can
     already represent combined calls syntactically
   - acceptance should remain analyzer-owned
3. Document the runtime extraction changes a future implementation would need
   in `crates/pine-runtime/src/builtins/strategy.rs`:
   - evaluate only the selected trigger expressions in the chosen order
   - handle invalid single-leg or bracket-leg values according to the decision
     record
   - convert tick distances through the existing fixed default mintick source
   - dispatch into broker facade methods without exposing broker internals
4. Document the broker changes a future implementation would need in
   `crates/pine-runtime/src/strategy/broker/exits.rs`:
   - represent single-trigger and bracket pending exits
   - compare bracket identity for unchanged repeated calls
   - validate finite prices and positive tick distances
   - keep runtime diagnostics stable
5. Document the pending-exit evaluation changes a future implementation would
   need in `crates/pine-runtime/src/strategy/broker/mod.rs`:
   - preserve creation-bar ineligibility
   - evaluate bracket legs after script statements
   - apply the selected same-bar precedence rule
6. Document the fill changes a future implementation would need in
   `crates/pine-runtime/src/strategy/broker/fills.rs`:
   - create exactly one order event and one trade for a filled bracket
   - close the full current long position
   - clear the pending bracket
7. Document the accounting expectations in
   `crates/pine-runtime/src/strategy/broker/accounting.rs`:
   - existing accessors should derive from broker state after fill
   - no bracket-specific public accounting fields are needed
8. Document the test order for a future implementation:
   - semantic acceptance/rejection first
   - broker unit tests second
   - runtime fixtures and snapshots third
   - incremental/profile checks fourth
   - host smoke tests fifth
   - docs/conformance/release notes last
9. Do not implement the blueprint in Phase Q unless the team explicitly turns
   Phase Q into a behavior phase.

Acceptance criteria:

- Future code changes are mapped to module ownership boundaries.
- No runtime behavior changes occur in Phase Q.
- The blueprint keeps public output schema changes out of the first future
  bracket subset.

Suggested verification:

```text
git diff --check
```

## Slice 5: Scope Guard And Tail Ranking

Goal: document why bracket design comes before other strategy maintenance tails
and keep larger broker phases deferred.

Steps:

1. Review the remaining strategy tails from `docs/PHASE_O_AUDIT.md` and
   `docs/PHASE_P_AUDIT.md`:
   - trade namespace functions
   - public open-trade records
   - public pending-order records, partial-fill fields, and exit-reason fields
   - rich metrics such as max drawdown, win trades, loss trades, and runup
   - combined trigger brackets and same-bar high/low precedence
   - trailing stops
   - partial exits and quantity reservation behavior
   - missing-entry pre-placement and multiple pending exits
   - short entries, reversals, and short exposure
   - `strategy.order` and richer order modification semantics
   - commission, slippage, margin, currency conversion, cash sizing,
     contracts, and percent-of-equity sizing
   - strategy alerts and realtime strategy execution
2. Record why bracket design is the next small target:
   - existing fixtures already mark the unsupported boundary
   - the Phase P broker split isolated exit placement and evaluation
   - no public host schema is required for a first design gate
   - same-bar precedence is the main unresolved blocker
3. Record why missing-entry pre-placement remains deferred:
   - it requires pending exits without a current position
   - it changes entry/exit lifecycle ordering
   - it may require multiple pending exits or stronger order identity rules
4. Record why rich reporting metrics remain deferred:
   - metric names and script-state timing need a separate reporting design
   - drawdown/runup semantics may require richer equity and trade history
   - public output expectations are not yet defined
5. Record why partial exits remain deferred:
   - they require quantity reservation and partial trade accounting
   - they likely require public or internal exit reason and remaining quantity
     semantics
6. Record why pyramiding, short exposure, and realtime broker rollback remain
   larger broker phases.
7. Update `docs/LONG_TERM_EXECUTION_PLAN.md` only if the team wants Phase Q to
   appear as a named planned or closed phase before implementation starts.

Acceptance criteria:

- The roadmap explains why bracket design is next.
- Deferred broker tails remain explicit and conservative.
- No unrelated strategy feature is accidentally selected for Phase Q.

Suggested verification:

```text
git diff --check
```

## Slice 6: Documentation And Roadmap Synchronization

Goal: synchronize maintainer-facing docs with the Phase Q design gate.

Steps:

1. Update `docs/LONG_TERM_EXECUTION_PLAN.md` if Phase Q should be tracked as a
   named phase:
   - add Phase Q as planned while the design gate is open
   - mark it closed only after `docs/PHASE_Q_AUDIT.md` exists
   - keep bracket runtime support out of the supported surface until a future
     behavior phase lands
2. Update `docs/CONFORMANCE.md` only if the design record changes how the
   unsupported strategy-exit boundary is explained. Do not claim support.
3. Update `docs/SEMANTIC_MODEL.md` only if diagnostic behavior or accepted
   syntax wording changes.
4. Update `docs/EXECUTION_SEMANTICS.md` only if it needs to clarify that
   combined trigger runtime behavior remains unsupported.
5. Update `docs/ARCHITECTURE.md` only if the future implementation blueprint
   changes module ownership expectations.
6. Update `docs/RELEASE_NOTES.md` only if Phase Q changes code, fixtures,
   diagnostics, conformance references, or roadmap-visible behavior.
7. Do not update runtime snapshots during Phase Q.
8. Run docs-sensitive and conformance checks if metadata or fixture references
   changed.

Acceptance criteria:

- Docs describe Phase Q as a design gate, not runtime bracket support.
- Compatibility claims remain conservative.
- Release notes, if touched, clearly state that combined triggers remain
  unsupported.

Suggested verification:

```text
cargo test -p pine-cli conformance_metadata_references_existing_fixtures
cargo test -p pine-cli matrix_output_matches_golden_snapshot
git diff --check
```

## Slice 7: Closeout Audit

Goal: close Phase Q with a concise audit once the bracket design gate is
complete.

Steps:

1. Create `docs/PHASE_Q_AUDIT.md`.
2. Record completed slices.
3. Record that Phase Q did not widen positive strategy compatibility unless a
   later approved behavior slice was deliberately included.
4. Record the final bracket decision record:
   - selected future trigger-pair subset
   - unsupported trigger combinations
   - price/tick conversion timing
   - same-bar both-hit policy
   - identity and replacement rules
   - script-state timing after future fills
   - public output/schema decision
5. Record fixture evidence:
   - existing unsupported fixtures that remain stable
   - any new diagnostic-only fixtures added during Phase Q
   - no runtime snapshots changed, unless explicitly approved
6. Record verification commands and results.
7. Update `docs/LONG_TERM_EXECUTION_PLAN.md` to mark Phase Q closed and choose
   the next recommended strategy maintenance target:
   - a small positive bracket implementation phase, if the design is complete
     and low-risk
   - continued diagnostic-only maintenance, if same-bar precedence remains
     deferred
   - another maintenance tail only if bracket support is deliberately paused
8. Keep `tests/fixtures/conformance.tsv` conservative.
9. Run the full release verification gate if any code, fixtures, metadata, or
   public docs changed.

Acceptance criteria:

- The audit can be used as the baseline for a future bracket implementation
  phase.
- The repository has a clear source of truth for why combined triggers remain
  unsupported or how they will be implemented later.
- Full release verification passes when required.

Closeout verification:

```text
git diff --check
scripts/verify.sh
```

Closeout verification passed on the Phase Q closeout workspace.

## Suggested Commit Order

1. `Document strategy bracket design gate`
2. `Harden strategy exit diagnostics`
3. `Record strategy bracket semantics decisions`
4. `Plan bracket fixture coverage`
5. `Document bracket implementation blueprint`
6. `Synchronize bracket roadmap docs`
7. `Close strategy bracket design audit`

## Phase Q Completion Checklist

- [x] Slice 0 baseline and design-gate decision confirmed.
- [x] Existing combined trigger fixtures reviewed.
- [x] Existing broker single-trigger behavior reviewed.
- [x] User-visible `strategy.exit` diagnostics are phase-neutral, if code is
      touched.
- [x] Any new diagnostic-only fixtures are referenced conservatively.
- [x] `strategy.exit` remains stop-only, limit-only, profit-only, or loss-only
      for executable behavior during Phase Q.
- [x] No runtime snapshots change unexpectedly.
- [x] No public runtime schema changes are made.
- [x] Future accepted bracket trigger pairs are selected or explicitly
      deferred.
- [x] Three-trigger and four-trigger policy is recorded.
- [x] Price/tick conversion timing is recorded.
- [x] Bracket identity and replacement rules are recorded.
- [x] Same-bar both-hit policy is recorded.
- [x] Future script-state timing after bracket fills is recorded.
- [x] Future public output behavior is recorded.
- [x] Future fixture plan is recorded.
- [x] Future implementation module ownership is recorded.
- [x] Other strategy maintenance tails remain explicitly deferred.
- [x] Roadmap docs are synchronized if Phase Q is added as a named phase.
- [x] `docs/PHASE_Q_AUDIT.md` records closeout evidence.
- [x] `git diff --check` passes.
- [x] `scripts/verify.sh` passes when required by the scope of changes.
