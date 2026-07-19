# Strategy Internal Execution Plan

Status: planning document.

This document turns `docs/STRATEGY_INTERNAL_GAP_AUDIT.md` into an executable
eight-stage strategy roadmap. It does not claim new support. A stage becomes
supported only after syntax, semantic analysis, runtime behavior, fixtures,
conformance metadata, snapshots, documentation, and release verification are
complete.

The stages below are intentionally ordered for dependency management. Do not
execute the gap-audit inventory numbers mechanically; that inventory is a
coverage checklist, not the implementation order.

## Execution Rules

- Work one small slice at a time.
- Start every slice by rechecking `tests/fixtures/conformance.tsv`, matrix
  output, current phase audits, and the relevant strategy modules.
- Keep unsupported variants explicitly rejected with diagnostics or documented
  no-op behavior.
- Preserve the public runtime output shape unless the stage explicitly designs a
  new host contract.
- Do not widen conformance claims before fixture-backed runtime and host parity
  evidence exists.
- If repo evidence and plan wording diverge, stop and reconcile the document or
  report the blocker before implementation.

## Stage 1: Boundary Lock

Status: closed on 2026-06-02. See
`docs/STRATEGY_INTERNAL_STAGE1_BOUNDARY_AUDIT.md`.

Goal: freeze the current strategy boundary before adding new behavior.

Scope:

- Reconcile known documentation drift between current conformance evidence and
  older phase-audit wording.
- Confirm the current fixture-backed strategy subset:
  - long-only one-net-position broker;
  - fixed default quantity and explicit positive `qty`;
  - `strategy.entry`, `strategy.close`, supported `strategy.exit` shapes;
  - `qty` and `qty_percent` partial exits;
  - explicit fixed-`qty` or `qty_percent` reservations for supported
    single-trigger, bracket, and trailing exits;
  - supported position, profit, equity, and trade-count variables.
- Add or update negative semantic fixtures only where unsupported strategy
  forms are not clearly guarded.

Out of scope:

- Runtime compatibility widening.
- Public output schema changes.
- Reinterpreting unsupported Pine behavior as supported.

Acceptance:

- Current support and unsupported boundaries agree across conformance, matrix,
  docs, and strategy audit wording.
- Unsupported declaration properties, order APIs, risk APIs, trade namespace
  functions, and unsupported `strategy.exit` combinations remain guarded.
- `scripts/verify.sh` passes before this stage is considered closed.

## Stage 2: Pending Entry And Order Timing Foundation

Status: closed on 2026-06-02. See
`docs/STRATEGY_INTERNAL_STAGE2_PENDING_ENTRY_AUDIT.md`.

Goal: introduce the internal pending-entry model needed by Pine-compatible order
timing.

Scope:

- Add active entry orders that can exist before fill.
- Preserve public output unless an entry actually fills.
- Fixture the selected default historical fill policy; Stage 2 selected
  next-historical-bar-open behavior for market entries.
- Support same-calculation `strategy.entry` plus `strategy.exit` attachment when
  the exit refers to the active entry id.

Out of scope:

- Arbitrary future binding for unmatched `from_entry` ids.
- Entry limit, stop, or stop-limit orders.
- Pyramiding, shorts, reversals, or generic pending-order cancellation.
- Realtime strategy handoff and bar magnifier fills.

Acceptance:

- Pending entries are internally represented and tested without exposing an
  unstable public pending-order shape.
- Same-calculation entry/exit attachment has semantic, broker, runtime,
  incremental, and host parity coverage.
- Missing-entry exits keep the documented unsupported or no-op boundary.

## Stage 3: Small Independent Strategy Utilities

Status: closed on 2026-06-02. See
`docs/STRATEGY_INTERNAL_STAGE3_UTILITIES_AUDIT.md`.

Goal: add narrow, high-value helpers that do not require the full broker model.

Scope:

- Implement `strategy.close_all()` for the current one-net-long model.
- Add win/loss/even trade count variables for the current closed-trade list.
- Keep these as small slices; either item can be skipped if Stage 2 exposes a
  blocker that should be handled first.

Out of scope:

- Partial `strategy.close`.
- Close ordering across multiple entries.
- Rich trade namespace functions.
- Commission, slippage, margin, or account-model changes beyond the separately
  closed Stage 7 cost slices.

Acceptance:

- Each helper has accepted and rejected semantic fixtures.
- Runtime fixtures prove behavior in flat, open-position, and already-closed
  cases.
- Public output shape is unchanged unless a separate contract is explicitly
  designed.

## Stage 4: Pine-Compatible `qty + qty_percent`

Status: closed on 2026-06-02. See
`docs/STRATEGY_INTERNAL_STAGE4_QTY_PRECEDENCE_AUDIT.md`.

Goal: align `strategy.exit` quantity precedence with Pine where `qty` wins over
`qty_percent`.

Scope:

- Replace the current diagnostic-only rejection for `qty + qty_percent` with a
  fixture-backed rule where `qty` determines the reserved or filled quantity.
- Cover supported single-trigger, bracket, and trailing exit shapes.
- Preserve existing placement-time quantity evaluation and fill-time clamping
  rules.

Out of scope:

- New trigger families.
- Omitted-quantity multiple reservations.
- Multiple-entry or pyramiding quantity allocation.

Acceptance:

- Analyzer and runtime agree on the same accepted forms.
- Negative fixtures still reject unsupported trigger combinations even when
  `qty_percent` is present.
- Public output continues to expose absolute filled quantities only.

## Stage 5: Entry Limit, Stop, And Stop-Limit Orders

Status: closed on 2026-06-02. See
`docs/STRATEGY_INTERNAL_STAGE5_ENTRY_ORDERS_AUDIT.md`.

Goal: extend `strategy.entry` beyond market-long entries after pending-entry
timing is stable.

Scope:

- Add long entry `limit`, `stop`, and stop-limit order forms in the current
  one-net-long model.
- Reuse the Stage 2 pending-entry timing foundation.
- Define deterministic historical trigger and fill behavior for each order form.

Out of scope:

- Short entries and automatic reversals.
- Pyramiding.
- Generic `strategy.order`.
- Cancellation APIs unless Stage 6 is already complete.
- Bar magnifier or lower-timeframe reconstruction.

Acceptance:

- Entry order forms have semantic fixtures, broker tests, runtime snapshots, and
  incremental parity coverage.
- Repeated entries under no-pyramiding keep the documented behavior.
- Supported entry orders interact correctly with same-calculation exit
  attachment.

## Stage 6: General Pending-Order Book And Cancellation

Status: closed on 2026-06-02. See
`docs/STRATEGY_INTERNAL_STAGE6_CANCELLATION_AUDIT.md`.

Goal: add cancellation semantics after pending orders are no longer
exit-specific.

Scope:

- Introduce a general internal pending-order book spanning supported pending
  entries and exits.
- Implement `strategy.cancel(id)` for supported pending order ids.
- Implement `strategy.cancel_all()` for all supported pending orders.

Out of scope:

- Generic `strategy.order`.
- Custom OCA groups.
- Pyramiding, shorts, reversals, and multi-entry ledgers.
- Public pending-order records unless separately designed.

Acceptance:

- Cancel behavior is deterministic for pending entries, pending exits, filled
  orders, flat positions, and unknown ids.
- Runtime and incremental paths agree.
- CLI, Python, and WASM parity tests cover at least one cancellation fixture if
  host-visible output changes.

## Stage 7: Trade Records, Costs, And Account Model

Status: closed on 2026-06-04 for the current long-only trade-record, cost,
reporting, default-sizing, and active-margin account subset. Slices 0, 1, 2,
and 3 closed on 2026-06-02; Slices 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34,
and 35 closed on 2026-06-03; the long-only margin/account model closed through
`docs/STRATEGY_INTERNAL_MARGIN_ACCOUNT_MODEL_PLAN.md` Slice M5 on
2026-06-03. See `docs/STRATEGY_INTERNAL_STAGE7_TRADE_RECORDS_AUDIT.md`.

Goal: enrich strategy reporting and accounting without jumping directly to a
multi-position broker.

Scope:

- Add a small individual trade namespace subset, starting with closed-trade
  `entry_price`, `exit_price`, `entry_bar_index`, and `exit_bar_index` if the
  script-variable-only contract is acceptable.
- Add selected cost or account-model slices only after the output contract is
  explicit.
- Candidate cost/account slices include additional commission modes, richer fill
  models, cash sizing, and percent-of-equity sizing.
- Margin/account-model work must pass through
  `docs/STRATEGY_INTERNAL_MARGIN_ACCOUNT_MODEL_PLAN.md` before runtime support
  is widened.

Out of scope:

- Full trade namespace coverage.
- Remaining trade namespace fields beyond the current closed/open-trade field
  slices.
- Margin behavior beyond the current explicit-`margin_long` long-only account
  slices until broader account constraints are designed.
- Public JSON expansion without an explicit host contract.

Acceptance:

- Script-variable support and public-output decisions are documented before
  implementation.
- Closed-trade field slices keep their functions script-visible only and do not
  expand public CLI/Python/WASM runtime schema.
- Open-trade field slices keep their functions script-visible only and limited
  to the documented one-net-long broker subset unless a later slice designs a
  broader ledger.
- Profit, equity, and trade-count behavior remain internally consistent when
  costs or account sizing are introduced.
- Existing strategy fixtures either remain unchanged or are intentionally
  updated with clear audit notes.

## Stage 8: Full Broker Expansion

Status: closed on 2026-06-04 as a behavior-preserving internal broker
expansion skeleton. See
`docs/STRATEGY_INTERNAL_STAGE8_BROKER_EXPANSION_AUDIT.md`.

Goal: move from the current one-net-long model toward Pine's broader broker
semantics.

Scope:

- Multiple entries and per-entry trade ledgers.
- Pyramiding.
- Short positions and automatic reversals.
- Generic `strategy.order()`.
- Full OCA behavior, including custom OCA names and OCA behavior across mixed
  order families.

Out of scope:

- Treating any of these as small compatibility patches.
- Widening public claims before the broker model, same-bar precedence, account
  interactions, and host contracts are designed together.

Acceptance:

- The internal broker can represent separate open trades, net position, and
  order-family state without losing current one-net-long behavior.
- Same-bar precedence and order allocation are fixture-backed.
- Public output and host bindings are updated only through an explicit schema
  and release plan.

## Stage 9: Entry-Relative Active-Entry Exits

Status: closed on 2026-06-04. See
`docs/STRATEGY_INTERNAL_STAGE9_ENTRY_RELATIVE_EXIT_PLAN.md` and
`docs/STRATEGY_INTERNAL_STAGE9_ENTRY_RELATIVE_EXIT_AUDIT.md`.

Goal: close the remaining same-calculation active-entry `strategy.exit`
attachment gap for entry-relative `profit`, `loss`, and `trail_points`
triggers.

Current supported Stage 9 subset:

- same-calculation `strategy.exit(..., profit=...)` can target a matching active
  pending long entry id and resolves its limit from the eventual entry fill
  price.
- same-calculation `strategy.exit(..., loss=...)` can target a matching active
  pending long entry id and resolves its stop from the eventual entry fill
  price.
- same-calculation
  `strategy.exit(..., trail_points=..., trail_offset=...)` can target a
  matching active pending long entry id and resolves its trailing activation
  from the eventual entry fill price.

Remaining Stage 9 subset:

- none. Stage 9 stops at the documented single-trigger active-entry subset.

Scope:

- Current long-only active pending-entry subset.
- Deferred relative trigger resolution from the eventual entry fill price.
- Existing public `StrategyResult` schema.
- Fixture-backed CLI, Python, and WASM parity before compatibility claims
  widen.

Next direction boundary:

- Same-calculation relative-leg active-entry bracket forms are official Pine
  behavior, but they are not part of the closed Stage 9 subset. Implement them
  only through a new bracket-specific design slice that covers deferred
  relative legs, bracket precedence, reservations, quantity handling,
  conformance, and host parity together.

Out of scope:

- Arbitrary future binding for unmatched missing-entry exits.
- Pyramiding, shorts, reversals, and generic `strategy.order()`.
- Public pending-order schema expansion.
- Tick-level or bar-magnifier behavior.

## Stage 10: Active-Entry Relative Brackets

Status: closed on 2026-06-05. See
`docs/STRATEGY_INTERNAL_STAGE10_ACTIVE_ENTRY_BRACKET_PLAN.md` and
`docs/STRATEGY_INTERNAL_STAGE10_ACTIVE_ENTRY_BRACKET_AUDIT.md`.

Goal: design and then fixture-back same-calculation active-entry
`strategy.exit` bracket attachment when one or both bracket legs are
entry-relative.

Target first subset:

- `strategy.exit(..., stop=..., profit=...)` against a matching active pending
  long entry;
- `strategy.exit(..., loss=..., limit=...)` against a matching active pending
  long entry;
- `strategy.exit(..., loss=..., profit=...)` against a matching active pending
  long entry.

Scope:

- Current long-only active pending-entry subset.
- One downside leg plus one upside leg only.
- Deferred relative leg resolution from the eventual entry fill price.
- Existing bracket precedence, reservation, quantity, and public output
  contracts after resolution.
- Fixture-backed CLI, Python, and WASM parity before compatibility claims
  widen.

Out of scope:

- Same-side pairs, 3+ triggers, or trailing-plus-bracket forms.
- Missing-entry future binding and `strategy.exit()` persistence for unmatched
  future entries.
- Pyramiding, shorts, reversals, generic `strategy.order()`, public
  pending-order output, and schema expansion.

## Stage 11: Partial `strategy.close`

Status: closed on 2026-06-05. See
`docs/STRATEGY_INTERNAL_STAGE11_PARTIAL_CLOSE_AUDIT.md`.

Goal: add fixture-backed partial market close support for the current
one-net-long `strategy.close()` subset.

Target first subset:

- `strategy.close(id, qty=...)`;
- `strategy.close(id, qty_percent=...)`;
- `strategy.close(id, qty=..., qty_percent=...)` where `qty` wins.

Scope:

- Current long-only one-net-position broker.
- Market close at current bar close using existing close fill and slippage
  behavior.
- Quantity resolution and clamping against the matching current open quantity.
- Existing public `StrategyResult` schema.
- Fixture-backed CLI, Python, and WASM parity before compatibility claims
  widen.

Out of scope:

- Partial `strategy.close_all()`.
- `immediately`, comments, alert messages, alert suppression, and
  order-fill alert delivery.
- Multiple entries, pyramiding, shorts, reversals, custom close ordering,
  public pending-order output, and schema expansion.

## Stage 12: Strategy Declaration Property Boundary

Status: closed on 2026-06-05. See
`docs/STRATEGY_INTERNAL_STAGE12_DECLARATION_PROPERTIES_AUDIT.md`.

Goal: refresh the post-Stage-11 strategy gap boundary before accepting another
`strategy()` declaration property.

Target first subset:

- no runtime widening in the design slice;
- explicit supported/unsupported declaration-property inventory;
- a candidate-slice order that avoids no-op keyword acceptance and broker-model
  shortcuts.

Scope:

- Current `strategy()` declaration subset recorded in
  `tests/fixtures/conformance.tsv`.
- Current long-only one-net-position broker.
- Existing semantic rejection path for unsupported declaration properties.
- Existing public `StrategyResult` schema.

Out of scope:

- `pyramiding`, `process_orders_on_close`, `calc_on_order_fills`,
  `calc_on_every_tick`, `currency`, `close_entries_rule`, `risk_free_rate`,
  `use_bar_magnifier`, `fill_orders_on_standard_ohlc`, strategy
  alert/order-fill settings, and runtime `margin_short` behavior.
- Short exposure, reversals, multi-entry ledgers, OCA behavior, public
  order-event output, and schema expansion.

## Stage 13: Multi-Entry Ledger And Pyramiding Design

Status: closed through Slice 101 on 2026-06-06. See
`docs/STRATEGY_INTERNAL_STAGE13_MULTI_ENTRY_LEDGER_PLAN.md` and
`docs/RELEASE_NOTES.md`.

Goal: design and fixture-back the long-only multi-entry ledger foundation before
any short/reversal behavior, `close_entries_rule`, or generic `strategy.order()`
support.

Closed subset:

- official strategy-entry, pyramiding, close-all, FIFO, and generic-order
  dependencies recorded;
- fixture-backed positive integer const `pyramiding` for long market entries and
  same-tick long price-based entry exceptions;
- long-only multi-entry `strategy.close`, `strategy.close_all`, and supported
  `strategy.exit` allocation for the fixture-backed subset;
- CLI, Python, and WASM host-parity coverage for the public JSON fixtures;
- preserved public `StrategyResult` schema.

Scope:

- Current long-only broker and internal `TradeLedger`.
- Current supported entry/close/exit/cancel behavior.
- Existing semantic rejection path for unsupported broker-model features.
- Existing public strategy JSON.

Out of scope:

- `pyramiding` behavior beyond the closed long-only fixture-backed subset and
  any runtime acceptance of `close_entries_rule`.
- Short exposure, reversals, `strategy.order()`, OCA across order families,
  public pending-order/open-trade ledgers, realtime recalculation, and strategy
  order-fill alert delivery.

## Shared Completion Gates

Every stage or slice must close with:

- semantic fixtures for accepted and rejected forms;
- broker unit tests for state transitions and accounting;
- runtime fixtures and golden snapshots;
- incremental/runtime interaction tests where state timing matters;
- CLI, Python, and WASM parity tests when public output or host behavior
  changes;
- synchronized `tests/fixtures/conformance.tsv`, matrix snapshot, docs, and
  release notes;
- a phase audit recording the supported and unsupported boundary;
- `scripts/verify.sh`.
