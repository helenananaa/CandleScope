# Strategy Order-Fill Alert Template Plan

Status: pure renderer plus Python, CLI, and WASM wrapper slices closed on
2026-06-11.

This document defines the next boundary after public `strategy.alerts`
exposure. It decides how to model the
`{{strategy.order.alert_message}}` placeholder without changing runtime
execution, public runtime JSON, or external alert delivery in this slice.

Official Pine behavior separates three concerns:

- order fills are broker events;
- `alert_message` values on order-generating `strategy.*()` calls provide the
  custom order-fill payload;
- `{{strategy.order.alert_message}}` appears in the user-created alert
  template, not inside the broker event itself.

Sources:

- TradingView Pine Script alerts documentation:
  <https://www.tradingview.com/pine-script-docs/concepts/alerts/>
- TradingView Pine Script strategies documentation:
  <https://www.tradingview.com/pine-script-docs/concepts/strategies/>

## Current State

The runtime exposes broker-owned order-fill payloads under
`strategy.alerts[].message`. That field was introduced in public runtime
`schemaVersion: 4` and remains present in the current runtime schema; it is the
resolved raw order-fill payload selected at fill time.

The analyzer still rejects TradingView-style placeholders in Pine-source
`alert()` and `alertcondition()` strings under the existing
`alert_placeholders` unsupported feature. This design does not change that
behavior.

The runtime does not model a running alert, alert condition selection, alert UI
settings, webhook delivery, or host-side alert message templates.

## Decision

Add placeholder rendering as a host-layer helper, not as broker accounting and
not as a new field in `RuntimeResult`.

The first implementation slice adds a pure renderer that takes:

- a host-provided alert message template string;
- one public `StrategyOrderFillAlertOutput` event.

It should return a rendered message string by replacing each exact
`{{strategy.order.alert_message}}` token with the event's raw `message` value.
If the event message is empty, the token renders as an empty string.

The renderer must not mutate `strategy.alerts`, top-level `alerts[]`, orders,
trades, position, equity, diagnostics, or schema versions.

## Non-Goals

- Do not implement external alert delivery.
- Do not add a running-alert scheduler or alert UI state.
- Do not change Pine-source `alert()` or `alertcondition()` placeholder
  support.
- Do not append strategy order-fill alerts to top-level `alerts[]`.
- Do not add `renderedMessage` or other pre-rendered fields to
  `strategy.alerts`.
- Do not implement the full TradingView placeholder catalog in the first
  renderer slice.
- Do not recursively render placeholders that appear inside
  `strategy.alerts[].message`.

## Template Scope

The first supported template token is exactly:

```text
{{strategy.order.alert_message}}
```

Whitespace variants such as `{{ strategy.order.alert_message }}` remain
unsupported until a later compatibility slice proves official parity and adds
fixtures. Unknown `{{...}}` tokens in the host template should produce a host
renderer diagnostic rather than silently changing runtime output.

The raw order-fill payload remains literal data. For example, if
`strategy.alerts[].message` itself contains `{{close}}`, the renderer should
insert that text as-is when replacing `{{strategy.order.alert_message}}`; it
should not perform a second placeholder pass.

## Host Boundary

The renderer belongs beside host adapters that already convert runtime results
for CLI, Python, and WASM. The core runtime should keep producing
`strategy.alerts` only.

Recommended first host shape:

- Rust helper: pure function over `&str` plus `StrategyOrderFillAlertOutput`.
- CLI: no default output change; a later explicit command or option can call
  the renderer.
- Python: no default `run_script` dictionary change; a later helper can render
  templates for a selected strategy alert event.
- WASM: no default runtime JSON change; a later helper can expose the same pure
  renderer.

This keeps schemaVersion `4` stable. A schema bump is only needed if a later
slice embeds rendered template output into public runtime JSON.

## Diagnostics

Renderer diagnostics should be host diagnostics, not Pine semantic
diagnostics. A script that only contains strategy order metadata remains
analyzable and runnable even if a host later asks to render an unsupported
template.

The existing `alert_placeholders` semantic diagnostic still applies only to
placeholders written directly in Pine-source `alert()` and `alertcondition()`
message/title strings.

## Implementation Slices

1. Closed on 2026-06-11: add a runtime-adjacent pure renderer for the exact
   `{{strategy.order.alert_message}}` token, with unit tests for replacement,
   empty message replacement, multiple occurrences, unknown placeholder
   diagnostics, and no recursive rendering.
2. Closed on 2026-06-11 for Python, CLI, and WASM: add host wrappers only after
   the pure renderer is stable. Keep default runtime JSON, Python dictionaries,
   and WASM JSON unchanged.
3. Closed on 2026-06-11: add host tests for explicit Python, CLI, and WASM
   rendering helpers.
4. Defer external alert delivery to the host-owned model in
   `docs/STRATEGY_RUNNING_ALERT_CONFIGURATION_PLAN.md`.

## Completion Gate

The design is closed when:

- `strategy.alerts[].message` remains the raw broker-owned payload;
- Pine-source alert placeholder support remains unchanged;
- the pure renderer has a narrow implementation contract;
- the Python wrapper is explicit and leaves `run_script` output unchanged;
- the CLI wrapper is explicit and leaves default `run` JSON unchanged;
- the WASM wrapper is explicit and leaves default runtime JSON unchanged;
- release notes and the strategy gap audit point to this plan.
