# Strategy Order-Fill Alerts Public Schema Plan

Status: implementation slice closed on 2026-06-11.

This document closes the public-schema design slice after
`docs/STRATEGY_ORDER_FILL_ALERTS_DESIGN.md`. It chooses the host output shape
for exposing broker-owned strategy order-fill alert events. The implementation
slice introduced this shape in public runtime `schemaVersion: 4`; later runtime
schema versions continue to expose the same strategy alert payload.

## Decision

Expose strategy order-fill alert events under the strategy payload as
`strategy.alerts`.

Do not reuse the existing top-level `alerts[]` array. Top-level alerts currently
represent reached `alert()` and `alertcondition()` callsites with
`id`, `barIndex`, `time`, `message`, and `source`. Strategy order-fill alerts
are broker fill events with order ids, fill prices, fill quantities, and entry
or exit identity. Keeping them under `strategy` preserves that distinction and
lets consumers opt into strategy-specific fields without guessing from a
generic source string.

## Public JSON Shape

The public-output slice increments `PUBLIC_RUNTIME_SCHEMA_VERSION` from `3` to
`4` and adds this field to `strategy`:

```json
{
  "strategy": {
    "orders": [],
    "trades": [],
    "position": [],
    "equity": [],
    "alerts": [
      {
        "id": "XL",
        "barIndex": 2,
        "time": 3,
        "direction": "strategy.exit",
        "qty": 2,
        "price": 3.5,
        "entryId": "L",
        "exitId": "XL",
        "message": "exit profit alert"
      }
    ],
    "diagnostics": []
  }
}
```

Field meanings:

- `id`: the filled order id. For entries, this is the entry id. For exits and
  closes, this is the exit/close order id used by the broker event.
- `barIndex`: fill bar index.
- `time`: fill bar time.
- `direction`: public strategy order direction string, matching the
  corresponding `strategy.orders[].direction` value where possible.
- `qty`: filled quantity after reservation and clamping.
- `price`: actual fill price after supported slippage and limit verification
  behavior.
- `entryId`: the filled entry id when known, otherwise `null`.
- `exitId`: the exit or close id when known, otherwise `null`.
- `message`: the resolved raw `strategy.order.alert_message` payload for the
  fill. It is not a rendered UI alert template.

The new array belongs after `equity` and before `diagnostics` in the JSON and
Python dict order, matching the logical flow from broker fills to diagnostics.

## Placeholder Boundary

The runtime should expose only the raw order-fill alert payload in `message`.
It should not render a user alert template and should not substitute
`{{strategy.order.alert_message}}` in this schema slice.

Reason: TradingView's placeholder appears in a user-created alert message
template outside the Pine source. This runtime does not yet model that external
alert configuration, so template rendering would require inventing host state
that does not exist in the current API.

Future placeholder work can add a separate host API for template rendering, but
that should not block exposing the broker-owned fill payload. The follow-on
template boundary is defined in
`docs/STRATEGY_ORDER_FILL_ALERT_TEMPLATE_PLAN.md`.

## Host Parity Requirements

The implementation slice that exposes `strategy.alerts` updates all public
hosts in one commit:

- Rust runtime model: add `alerts: Vec<StrategyOrderFillAlertOutput>` to
  `StrategyResult`.
- Broker result assembly: copy internal order-fill alert events into
  `StrategyResult.alerts`.
- CLI JSON: serialize `strategy.alerts` and bump
  `PUBLIC_RUNTIME_SCHEMA_VERSION` to `4`.
- Python bindings: add `strategy["alerts"]` with the same keys and Python
  `None` for missing `entryId`/`exitId`.
- WASM: rely on shared runtime JSON and refresh WASM snapshot expectations.
- Snapshots: update existing strategy snapshots to include `"alerts":[]`, and
  add at least one metadata fixture with non-empty `strategy.alerts`.

## Conformance Wording

When public exposure lands, conformance rows for `strategy.entry`,
`strategy.exit`, `strategy.close`, and `strategy.close_all` should change from
"without public JSON fields or external order-fill alert delivery" to a more
precise claim:

> order-fill alert payloads are exposed in `strategy.alerts` for supported
> fills; external alert delivery and alert-template placeholder rendering
> remain unsupported.

Top-level `alerts[]` wording should remain limited to reached `alert()` and
`alertcondition()` calls.

## Implementation Slices

Keep the public exposure narrow:

1. Add `strategy.alerts` with empty-array schema coverage across all strategy
   snapshots and host bindings.
2. Add non-empty `strategy.alerts` coverage for entry, close, close_all, and
   exit profit/loss fills using existing metadata fixtures or one focused new
   runtime fixture.
3. Add tests that `disable_alert=true` suppresses the public strategy alert
   event while the public order/trade remains present.
4. Leave placeholder rendering, external alert delivery, alert UI settings,
   and top-level typed alert unions out of scope.

## Rejected Shape

Rejected: top-level typed alert union.

That shape would force all top-level alert consumers to handle broker-specific
fields and type tags even when they only care about indicator alerts. It also
creates migration risk for the existing `alerts[]` array, whose current entries
are callsite-based rather than fill-based.
