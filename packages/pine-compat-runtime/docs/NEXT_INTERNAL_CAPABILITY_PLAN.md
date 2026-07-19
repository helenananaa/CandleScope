# Next Internal Capability Plan

Status: active planning document, refreshed on 2026-07-18 after the Stage 13
strategy baseline, imported UDT array expansion, and host-parity hardening.

This document groups the next interpreter-internal work into seven large task
directions. It does not claim new compatibility. A task becomes supported only
after the matching syntax, semantic analysis, runtime behavior, fixtures,
conformance metadata, snapshots, docs, and release verification are complete.

## Selection Rules

- Pick one small slice from one direction at a time.
- Prefer work that can be proven with local fixtures and host-neutral JSON.
- Keep public output fields unchanged unless the slice explicitly designs a new
  contract.
- Keep unsupported variants rejected with diagnostics.
- Do not use roadmap wording as support evidence. Use
  `tests/fixtures/conformance.tsv`, snapshots, audit docs, and verification
  results.

## Direction 1: Strategy Maintenance

Goal: make the existing basic long-only strategy subset more useful without
turning it into a full broker simulator.

Current Stage 13 baseline: the runtime now has a fixture-backed long-only
multi-entry ledger subset for configured `pyramiding`, same-tick long
price-based entry exceptions, selected `strategy.close`/`strategy.close_all`
allocation, and a broad supported `strategy.exit` subset across explicit
`from_entry`, omitted-`from_entry`, current same-entry-id, and same-entry-id
future-entry persistence cases. Public strategy JSON still intentionally hides
pending orders, reservation ledgers, exit reasons, OCA state, trailing state,
and trade-key internals.

Good next slices:

- More fixture-backed strategy state variables or count helpers.
- Narrow order/trade accounting improvements that keep the current public output
  shape.
- Clearer diagnostics for still-unsupported order, account, and exit forms.
- Small host-neutral strategy metadata/accounting checks that preserve the
  current public output shape. Strategy order metadata, public `strategy.alerts`,
  and explicit `{{strategy.order.alert_message}}` host rendering are already
  closed for the fixture-backed subset.

Keep out of scope until separately designed:

- Short exposure, reversals, and `strategy.order` forms beyond the
  fixture-backed long market/limit/stop/stop-limit add-or-increase subset and
  explicit-quantity reduce-only market-short subset.
- Pyramiding behavior beyond the current fixture-backed long-only multi-entry
  ledger subset, including short/reversal netting and richer close-entry rules.
- Custom OCA behavior, unsupported margin/account behavior, and rich order
  types.
- Arbitrary future binding for unmatched `from_entry` ids.
- Public pending-order, reservation, remaining-quantity, or exit-reason records.
- Realtime strategy handoff and intrabar path reconstruction.
- External strategy alert delivery before the host-owned restart-safe durable
  attempt-store, executable retry scheduling, concrete authentication secret
  store, diagnostic emission, and failure-reporting model from
  `docs/STRATEGY_EXTERNAL_ALERT_DELIVERY_ADAPTER_PLAN.md` is implemented.

Recommended first slice: do not reopen broad broker foundations immediately
after Stage 13. Prefer either a narrow no-op/diagnostics/accounting slice that
keeps the public schema unchanged, or move to a small built-in coverage slice
from a real fixture gap. Do not add short exposure, reversals, generic
`strategy.order()` beyond the current fixture-backed subset, custom OCA, public
pending-order fields, or any conformance widening without runtime behavior and
host-parity evidence in the same slice.

Closed maintenance slice:

- Supported `strategy.exit` while-flat no-op behavior is covered for
  single-trigger stop/limit/profit/loss, stop+limit, stop+profit, and
  loss+limit/loss+profit bracket, and trailing stop shapes by runtime fixtures,
  golden snapshots, conformance matrix entries, and Python/WASM host parity
  tests without exposing pending-order or reservation internals.
- Supported explicit wrong-entry `strategy.exit` no-op behavior is covered for
  single-trigger stop/limit/profit/loss, stop+limit, stop+profit, and
  loss+limit/loss+profit bracket, and trailing stop shapes by runtime fixtures,
  golden snapshots, conformance matrix entries, and Python/WASM host parity
  tests.

## Direction 2: Built-In Coverage

Goal: increase the number of ordinary indicator scripts that run by adding small
fixture-backed built-in subsets.

Good next slices:

- Additional common `ta.*` helpers.
- Additional `math.*` helpers and edge-case coverage for existing helpers.
- Additional `str.*` formatting and parsing helpers.
- More time, timeframe, session, symbol, and color helper subsets.
- Better diagnostics for known unsupported built-in argument forms.

Keep out of scope until separately designed:

- Built-ins that require host market data, account state, chart UI state, or
  remote services.
- Approximate behavior without fixture evidence.
- Broad claims such as "all `ta.*`" or "all string formatting".

Recommended first slice: choose one high-use built-in family from real fixture
gaps, add only the smallest documented subset, and update the matrix only for
that fixture-backed subset.

## Direction 3: Arrays And Collections

Goal: make the current typed-array support more complete while preserving clear
storage lifetime and mutation rules.

Good next slices:

- More array functions or method-call aliases for existing scalar element types.
- More array behavior inside branches, loops, and user-defined functions.
- More array/history/state interaction fixtures.
- Better diagnostics for unsupported element types and invalid mutations.

Keep out of scope until separately designed:

- UDT array behavior beyond the fixture-backed same-local and same-imported
  scalar-tree subsets, especially non-scalar, nested-collection, or recursive
  UDT arrays.
- Drawing-object and `chart.point` array behavior beyond the fixture-backed
  object-id and value-array subsets.
- Map and matrix behavior beyond the current fixture-backed typed subsets.
- Behavior that requires object identity or lifetime rules not already modeled.

Recommended first slice: add one missing array helper for already-supported
scalar arrays, with branch/loop/UDF interaction fixtures if the helper mutates
state.

## Direction 4: User-Defined Types And Methods

Goal: expand the local and imported structured-data subsets without weakening
source-scoped type identity or method resolution.

Recent closure:

- Local and imported scalar-tree UDT values now have fixture-backed
  construction, typed declarations, selected control-flow results, history,
  ordinary `var`, scalar-tree `varip`, and same-identity array subsets.
- Pure local and imported UDT methods now have fixture-backed receiver,
  parameter passthrough, alias, nested-method passthrough, constructor helper,
  and selected control-flow return coverage.

Good next slices:

- Clearer diagnostics for unsupported imported UDT and imported-method tails,
  nested mutation, and side-effecting methods.
- One additional imported-method or imported-UDT value-flow slice outside the
  current scalar-tree subset.
- Negative fixture maintenance for unsupported method parameter families or
  mismatched local UDT identity.
- Audit-only sync work when UDT/method matrix, semantic docs, and runtime
  fixtures drift.

Keep out of scope until separately designed:

- Imported UDT identity beyond the current same-imported-identity scalar-tree
  value, history, array, and method subsets.
- Imported methods beyond the current pure scalar-tree receiver/parameter/return
  subset.
- UDT arrays beyond the fixture-backed same-local and same-imported scalar-tree
  subsets, especially non-scalar, nested-collection, or recursive UDT arrays.
- Object-backed non-scalar UDT `varip` values and broader UDT history shapes.
- Side effects inside methods.

Recommended first slice: one diagnostics fixture/message improvement for an
unsupported UDT or method boundary, or one narrow imported-method value-flow
slice that keeps the current side-effect and non-scalar collection boundaries.

## Direction 5: Request Support

Goal: widen request behavior only where the runtime can stay deterministic and
host-provided data can prove the result.

Good next slices:

- More same-symbol or exact-key higher-timeframe `request.security` cases.
- More supported scalar expression shapes inside requested contexts.
- More alignment and gap-handling fixtures.
- Better host parity coverage for CLI, Python, and WASM request data injection.

Keep out of scope until separately designed:

- Lower-timeframe array-returning requests.
- Broad `request.*` families.
- Remote data lookup inside core crates.
- Requested-context strategy state or side effects.

Recommended first slice: one additional deterministic higher-timeframe
alignment case backed by request fixtures and host parity tests.

## Direction 6: Drawing Objects

Goal: add useful drawing lifecycle behavior while keeping the output
host-neutral.

Good next slices:

- Finish declaration-driven drawing object-count eviction beyond the now-backed
  label, box, line, and polyline lifecycle subsets if another drawable family is
  added.
- More `label.*`, `line.*`, `box.*`, and `table.*` methods.
- More deletion, mutation, no-op, and runtime-limit fixtures.
- More realtime rollback fixtures for already-supported drawing families.
- Better diagnostics for unsupported coordinate modes and invalid ids.

Keep out of scope until separately designed:

- General polyline arrays until the id-array behavior is deliberately designed
  and fixture-backed.
- Host-specific visual layout, drag behavior, or chart interaction.
- Drawing behavior that cannot be represented in the current JSON contract.

Recommended first slice: one missing method from an already-supported drawing
family, with runtime snapshot and realtime rollback coverage if it changes
state.

## Direction 7: Alerts

Goal: make alert events more useful while keeping alert behavior deterministic
and local to runtime output.

Closed slice:

- The local const-string alert frequency subset is fixture-backed for
  `alert.freq_once_per_bar`, `alert.freq_all`, and
  `alert.freq_once_per_bar_close`.
- Dynamic string-compatible `alert()` messages are fixture-backed through
  runtime snapshots and direct Python/WASM host parity assertions, while
  Pine-source `alert()` placeholder interpolation remains unsupported.
- Alert diagnostic fixtures cover dynamic frequency expressions, unknown
  const-string frequency values, and alertcondition placeholder rejection.
- Realtime alert-frequency rollback fixtures cover default once-per-bar
  suppression and `alert.freq_all` repeated-call emission across forming and
  confirmed updates.

Good next slices:

- Additional alert argument validation and diagnostics beyond the current
  message/title/frequency boundary.
- More branch, loop, and realtime rollback fixtures beyond the current alert
  policy and frequency rollback coverage.
- Better parity tests for alert output through CLI, Python, and WASM.
- Use `docs/STRATEGY_RUNNING_ALERT_CONFIGURATION_PLAN.md` before any external
  strategy alert delivery work.

Keep out of scope until separately designed:

- Sending webhooks, email, push notifications, or other external delivery.
- TradingView-style placeholder interpolation.
- Host scheduling, throttling, or user notification policy.

Recommended next slice: choose alert work only when it is fixture-backed and
does not require external delivery or host scheduling.

## Recommended Order

1. Built-in coverage selected from real fixture gaps, unless a narrow
   post-Stage-13 strategy maintenance issue already has a clear contract.
2. Strategy maintenance limited to diagnostics, accounting, or metadata that
   preserves the public schema.
3. Arrays and collections for already-supported scalar element types.
4. User-defined type and method maintenance.
5. Request support for one deterministic host-data case.
6. Drawing object method maintenance.
7. Alert policy maintenance.

This order keeps the runtime useful for ordinary indicator execution and the
current basic strategy subset while postponing work that needs new public
contracts, chart rendering, remote data, or external delivery systems.
