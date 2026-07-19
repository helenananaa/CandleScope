# Strategy Running Alert Configuration Plan

Status: design gate closed on 2026-06-11.

This document defines the host-owned configuration model required before
implementing external strategy alert delivery. It does not add delivery,
scheduling, public runtime JSON fields, or Pine-source placeholder support.

## Background

The current runtime already exposes supported strategy order-fill payloads under
`strategy.alerts`, and explicit Python, CLI, and WASM host helpers can render
`{{strategy.order.alert_message}}` for a selected public strategy fill event.

Official Pine behavior separates alert events from running alerts:

- Pine code and broker fills create alert events.
- A running alert is created by the user through the host/UI, not by Pine code.
- Running alerts use a snapshot of the script, inputs, chart symbol, and
  timeframe from alert-creation time.
- Script alerts on strategies can include `alert()` function events, order-fill
  events, or both.
- Order-fill alert messages can use `{{strategy.order.alert_message}}` in the
  host-created alert message template.
- Alert triggering is a realtime host concern, not historical backtest delivery.

Sources:

- TradingView Pine Script alerts documentation:
  <https://www.tradingview.com/pine-script-docs/concepts/alerts/>
- TradingView Pine Script strategies documentation:
  <https://www.tradingview.com/pine-script-docs/concepts/strategies/>

## Decision

Model running alerts as host configuration over existing runtime events, not as
new Pine language state and not as broker accounting.

The first running-alert model should be a serializable host-side contract with
these conceptual fields:

```text
RunningAlertConfig
  scriptSnapshotId: string
  symbol: string
  timeframe: string
  eventSelection: RunningAlertEventSelection
  messageTemplate: string
  realtimePolicy: RealtimeOnly
```

`scriptSnapshotId` identifies an immutable host snapshot of the script source,
inputs, libraries, request data binding, symbol, and timeframe. The runtime
should not look up mutable editor state when evaluating a running alert.

`eventSelection` describes which existing events can trigger the running alert:

```text
RunningAlertEventSelection
  indicatorAlertCalls
  strategyOrderFills
  both
```

The first implementation slice should focus on `strategyOrderFills` only,
because the strategy order-fill renderer is already explicit and host-owned.
`both` should stay implementation-pending until the shared host event envelope
in `docs/STRATEGY_REALTIME_ALERT_DELIVERY_PLAN.md` has executable builders and
host tests for both event streams.

`messageTemplate` is host data. The initial supported strategy template token is
the exact `{{strategy.order.alert_message}}` token already implemented by the
host helpers. Pine-source `alert()` and `alertcondition()` placeholders remain
under the existing unsupported semantic boundary.

`realtimePolicy` is fixed to realtime-only for compatibility with official
running-alert behavior. Historical runs may continue to expose deterministic
`alerts[]` and `strategy.alerts` events for local analysis and tests, but a later
delivery API must not silently deliver historical backtest events as running
alerts.

## Non-Goals

- Do not send webhooks, email, push notifications, orders, or broker messages.
- Do not implement alert creation, deletion, persistence, UI dialogs, or
  scheduling in the core runtime.
- Do not change public `RuntimeResult`, `strategy.alerts`, or top-level
  `alerts[]` schemas.
- Do not add `renderedMessage` to runtime JSON.
- Do not implement placeholder tokens beyond
  `{{strategy.order.alert_message}}`.
- Do not change Pine-source `alert()` or `alertcondition()` placeholder
  diagnostics.
- Do not merge strategy order-fill events into top-level `alerts[]`.

## Runtime Boundary

The runtime remains responsible for deterministic event production:

- top-level `alerts[]` for supported `alert()` and `alertcondition()` events;
- `strategy.alerts` for supported strategy order-fill events.

The host remains responsible for selecting events, applying a running-alert
configuration, rendering a message template, and optionally delivering the
rendered message through a future external channel.

This separation keeps historical CLI/Python/WASM analysis deterministic while
leaving room for a realtime host loop later.

## Compatibility Rules

1. A running-alert configuration is immutable once created. Host code must create
   a new config when script source, inputs, symbol, timeframe, libraries, or
   request data bindings change.
2. Strategy order-fill delivery candidates come from public
   `strategy.alerts` events only. Internal broker events are not a host API.
3. `disable_alert` has already been applied before a public `strategy.alerts`
   event exists, so hosts do not need a second suppression pass.
4. Template rendering errors are host errors. They must not become Pine semantic
   diagnostics for otherwise runnable scripts.
5. Historical event replay is a test/debug mode only and must be opt-in if it is
   ever added.

## Implementation Slices

1. Closed on 2026-06-11: design only, with this document plus cross-references
   from the strategy alert template and gap-audit docs.
2. Closed on 2026-06-11: add serializable Rust structs for
   `RunningAlertConfig`, `RunningAlertEventSelection`, and the realtime-only
   policy without applying them to runtime output or delivery.
3. Closed on 2026-06-11: add a strategy order-fill evaluation helper that takes
   one config and one public `StrategyOrderFillAlertOutput`, returning either a
   rendered host message or a host diagnostic. The helper accepts
   `strategyOrderFills` only; `both` remains implementation-pending until
   indicator alert calls and strategy order fills share executable host envelope
   builders and tests.
   Default JSON remains unchanged.
4. Closed on 2026-06-11: expose the helper explicitly through Python, CLI, and
   WASM host wrappers with tests that default runtime output stays unchanged.
5. Closed on 2026-06-11: realtime loop and delivery-sink boundary design in
   `docs/STRATEGY_REALTIME_ALERT_DELIVERY_PLAN.md`. External network delivery
   remains out of scope.

## Completion Gate

This design gate is closed when:

- the running-alert config is documented as host-owned and immutable;
- event selection separates strategy order fills from indicator alert calls;
- realtime-only delivery is explicit;
- public runtime JSON remains unchanged;
- no external delivery mechanism is implemented;
- later implementation slices have clear testable boundaries.
