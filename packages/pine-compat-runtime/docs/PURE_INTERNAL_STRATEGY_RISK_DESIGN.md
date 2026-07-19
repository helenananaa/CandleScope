# Pure Internal Strategy Risk Rule Design

Status: design gate closed. This document does not enable any
`strategy.risk.*` runtime behavior.

This note defines the internal boundary for future `strategy.risk.*` support.
Risk rules are broker directives that can reject entries, cancel pending orders,
or stop later order placement. They are not reporting variables and must not be
accepted as inert no-op calls.

## Current Boundary

The current interpreter rejects `strategy.risk.*` calls. Existing supported
names such as `strategy.max_drawdown`, `strategy.max_contracts_held_all`, and
trade `max_drawdown()` fields are read-only reporting metrics only. They do not
configure broker risk rules.

Current strategy runtime constraints:

- long-only exposure in supported positive behavior;
- selected long entries, closes, cancellations, exits, reservations, and
  pyramiding;
- selected long margin affordability and liquidation behavior;
- no short exposure, automatic reversal, generic `strategy.order()`, custom OCA
  behavior, order-on-close, calc-on-fill, calc-on-every-tick, or bar magnifier
  timing;
- no public pending-order or account-ledger schema.

Because risk rules interact with all of those systems, they must remain rejected
until a slice deliberately wires one rule through the broker.

## Design Principles

Future risk-rule work must follow these constraints:

- risk calls are declarations of broker policy, not ordinary value-producing
  expressions;
- a risk rule becomes supported only when its effect is observable in
  fixture-backed order admission, pending-order cancellation, fills, diagnostics,
  and script-visible strategy state;
- unsupported risk calls must continue to produce diagnostics rather than being
  accepted as no-ops;
- rule evaluation must be deterministic in both historical and incremental
  execution;
- rule state must survive ordinary bar-to-bar execution and obey realtime
  rollback semantics if the rule can trigger on forming bars;
- public host result shapes stay unchanged unless a separate schema design
  exposes risk-rule state.

## Rule Families

Treat risk rules as separate feature families. Do not implement them as one
generic namespace switch.

### Entry Direction Rules

`strategy.risk.allow_entry_in()` depends on positive short/reversal semantics.
The rule must decide whether a disallowed opposite-direction entry is rejected,
converted into a reduce-only close, or cancels/replaces pending orders. That
choice must be consistent with the short/reversal design gate before any
positive support.

### Drawdown And Loss Rules

Rules such as maximum drawdown or maximum intraday loss depend on account equity,
open profit, realized profit, margin behavior, and session/day boundaries.
Before support, the runtime must define:

- the equity basis used for rule thresholds;
- cash versus percent threshold interpretation;
- whether open profit is included;
- when an intraday period resets;
- what pending orders are cancelled when the rule trips;
- whether later strategy order calls emit diagnostics or become broker no-ops.

Do not infer these rules from read-only `strategy.max_drawdown` reporting. A
reporting metric can exist without becoming a broker stop rule.

### Position Size Rules

Maximum position-size rules require the entry admission path to check the
post-fill exposure, not only the requested order quantity. They also need shared
handling for pyramiding, partial exits, generic orders, and future short
exposure.

The first implementation should limit itself to supported long entries and the
current pyramiding subset if generic orders and shorts are still unsupported.

### Filled-Order Count Rules

Filled-order count rules depend on when fills are counted and when an intraday
window resets. They also interact with `calc_on_order_fills` and order-on-close
timing, so they should not be supported until the relevant execution-timing
boundary is fixture-backed or the slice explicitly limits the subset to current
historical bar timing.

## Internal Model

Future broker state should keep risk configuration and triggered state separate:

```text
StrategyRiskRules
  allow_entry_direction
  max_drawdown
  max_intraday_loss
  max_position_size
  max_intraday_filled_orders

StrategyRiskState
  tripped_rules
  intraday_counters
  blocked_order_placement
```

Suggested broker hooks:

- `record_risk_rule_call(...)` during script execution validates arguments and
  stores or updates policy for later order calls;
- `check_risk_before_order(...)` rejects or rewrites an order before it enters
  the pending-order book;
- `check_risk_after_fill(...)` updates triggered state after fills and performs
  rule-owned pending-order cancellation when required;
- `reset_intraday_risk_state(...)` runs on the chosen session/day boundary;
- script-visible strategy variables read the resulting broker state through the
  existing deterministic timing boundary.

Do not hide risk effects in parser or analyzer acceptance alone. The runtime
broker must own policy state and transitions.

## Suggested Slice Order

1. Boundary fixture: keep representative `strategy.risk.*` calls rejected and
   document that they are broker directives, not report variables.
2. Entry-direction design check: align `allow_entry_in()` with the short/reversal
   design before implementation.
3. Long-only max position size: admit one positive fixed numeric limit for the
   current long market-entry and pyramiding subset, with no public schema change.
4. Long-only drawdown/loss stop: add one threshold family only after equity and
   reset timing are explicitly fixture-backed.
5. Filled-order count: add only after execution timing semantics are stable
   enough to define when fills increment the counter.
6. Conformance and matrix updates happen only in the same slice that adds
   fixture-backed positive runtime behavior.

If a slice needs short exposure, generic order netting, custom OCA, public
pending-order ledgers, or account currency conversion to be correct, stop and
implement or design that dependency first.
