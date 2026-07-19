# Strategy Order-Fill Alerts Design

Status: design gate closed on 2026-06-11.

This document closes Slice OM5 from
`docs/STRATEGY_INTERNAL_ORDER_METADATA_PLAN.md`. It defines the next runtime
shape for strategy order-fill alerts, but does not implement alert emission or
change public host output.

## Current State

The runtime currently has two separate surfaces:

- indicator-style `alerts[]` events from reached `alert()` and
  `alertcondition()` calls;
- strategy broker order/trade output under `strategy.orders` and
  `strategy.trades`.

Strategy order metadata is now accepted and stored internally for the supported
`strategy.entry`, `strategy.exit`, `strategy.close`, and `strategy.close_all`
subset. That metadata is intentionally not emitted externally yet.

Official Pine behavior keeps strategy order-fill alerts tied to broker fills:
strategy orders can create alerts when they execute, order calls may provide
`alert_message`, users can reference that value through the
`{{strategy.order.alert_message}}` placeholder in an alert message, and
`disable_alert` suppresses order-fill alert firing for that order.

Sources:

- TradingView Pine Script alerts documentation:
  <https://www.tradingview.com/pine-script-docs/concepts/alerts/>
- TradingView Pine Script strategies documentation:
  <https://www.tradingview.com/pine-script-docs/concepts/strategies/>

## Non-Goals

- Do not expose strategy order-fill alerts in public JSON in this design slice.
- Do not increment `PUBLIC_RUNTIME_SCHEMA_VERSION` in this design slice.
- Do not add a host-specific alert shape in CLI, Python, or WASM.
- Do not implement external alert delivery.
- Do not implement unsupported order commands, shorts, reversals, or
  `strategy.close(..., immediately=...)`.

## Internal Event Model

The next implementation slice should add an internal broker-owned event type
before touching public output:

```rust
pub(crate) struct StrategyOrderFillAlertEvent {
    pub(crate) id: String,
    pub(crate) bar_index: usize,
    pub(crate) time: i64,
    pub(crate) direction: String,
    pub(crate) qty: f64,
    pub(crate) price: f64,
    pub(crate) entry_id: Option<String>,
    pub(crate) exit_id: Option<String>,
    pub(crate) message: String,
}
```

The event should be recorded at the same point as the public
`StrategyOrderEvent` fill, not when the order placement call executes. This is
required for delayed pending entries and exits, because their fill bar, fill
price, quantity, and chosen exit leg can differ from placement-time state.

The broker should keep these events internal until a later schema slice decides
how to expose them. The immediate tests should assert only internal event
content and that existing public runtime snapshots remain unchanged.

## Message Selection

For `strategy.entry`, `strategy.close`, and `strategy.close_all`, use
`StrategyOrderMetadata.alert_message` when present. When it is absent, the
internal alert event message should be an empty string.

For `strategy.exit`, choose the most specific available message for the filled
leg:

- profit/limit leg: `alert_profit`, falling back to `alert_message`;
- loss/stop leg: `alert_loss`, falling back to `alert_message`;
- trailing leg: `alert_trailing`, falling back to `alert_message`;
- any other supported exit fill: `alert_message`.

If `disable_alert` is true on the metadata attached to the filled order, do not
record a strategy order-fill alert event for that fill.

## Placeholder Boundary

Placeholder interpolation should not happen inside the broker in the first
implementation slice. The broker should store the resolved
`strategy.order.alert_message` payload only. A later public-output slice can
decide whether to expose:

- the raw order-fill alert payload;
- a pre-rendered message that substitutes `{{strategy.order.alert_message}}`;
- both fields under a schema-versioned contract.

This keeps the broker focused on fill-time facts and avoids mixing UI alert
template rendering with order accounting.

The follow-on host template boundary is defined in
`docs/STRATEGY_ORDER_FILL_ALERT_TEMPLATE_PLAN.md`. It keeps
`strategy.alerts[].message` as the raw fill payload and treats
`{{strategy.order.alert_message}}` rendering as host-layer work.

## Interaction With `alerts[]`

Do not append strategy order-fill events to the existing indicator-style
`alerts[]` array without a schema review. Today `AlertEvent.source` identifies
the reached `alert()` or `alertcondition()` callsite. Strategy order-fill alerts
are broker events with order ids, fill prices, quantities, and optional entry or
exit ids. Reusing the same public shape would lose type information and make
host consumers infer strategy fills from a generic source string.

The public schema plan chooses a schema-versioned `strategy.alerts` array over
an explicit top-level typed alert union. The public-output slice exposes that
shape with CLI, Python, and WASM parity.

## Host And Schema Implications

Any public exposure of strategy order-fill alerts must:

- increment `PUBLIC_RUNTIME_SCHEMA_VERSION`;
- update CLI JSON snapshots;
- update Python dict conversion and tests;
- update WASM runtime JSON tests;
- document the exact public fields in release notes and conformance text.

Until that slice lands, `alerts[]` and `strategy` public JSON remain unchanged.

## Internal Event Slice

Closed on 2026-06-11.

The first runtime slice is internal-only:

1. add the broker-owned `StrategyOrderFillAlertEvent` collection;
2. record entry, exit, close, and close_all fill events from existing metadata;
3. honor `disable_alert`;
4. choose `strategy.exit` leg-specific messages;
5. add broker unit tests for event content and suppression;
6. add a runtime snapshot proving public JSON remains byte-for-byte unchanged.

The broker now records those events internally. Public runtime output remains
unchanged.

## Next Public Schema Slice

Only after the internal event model stays stable should a separate schema slice
expose strategy order-fill alerts to hosts.
`docs/STRATEGY_ORDER_FILL_ALERTS_PUBLIC_SCHEMA_PLAN.md` chooses a
schema-versioned `strategy.alerts` array over a top-level typed alert union.
The implementation slice must update CLI, Python, and WASM host parity
together.
