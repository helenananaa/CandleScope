# Strategy Internal Order Metadata Plan

Status: design gate closed on 2026-06-11. Runtime behavior, conformance claims,
fixtures, snapshots, matrix output, and public JSON are unchanged.

This plan defines the first strategy order metadata direction after the Stage 13
long-only multi-entry ledger closeout. The goal is to move toward Pine's
strategy order metadata surface without changing external alert delivery or the
current public `StrategyResult` JSON shape before those contracts are designed.

## Current Boundary

The current executable strategy subset accepts selected parameters on:

- `strategy.entry(id, direction, qty, limit, stop)`
- `strategy.exit(id, from_entry, stop, limit, profit, loss, trail_price,
  trail_points, trail_offset, qty, qty_percent)`
- `strategy.close(id, qty, qty_percent)`
- `strategy.close_all()`
- `strategy.cancel(id)`
- `strategy.cancel_all()`

The current public strategy output remains:

```text
strategy.orders[]
strategy.trades[]
strategy.position[]
strategy.equity[]
strategy.diagnostics[]
```

`StrategyOrderEvent` currently stores only public fill fields: id, bar index,
time, direction, quantity, and price. It does not store comments, alert
messages, alert suppression, order-fill alert events, OCA metadata, or internal
pending-order metadata in the public result.

## Non-Goals

Do not implement these in the first metadata slices:

- external alert delivery;
- public strategy JSON schema expansion;
- Strategy Tester UI fields;
- order-fill placeholder interpolation;
- custom OCA behavior;
- `strategy.order()`;
- short exposure, reversals, or close-entry-rule changes;
- metadata on unsupported order commands or unsupported trigger shapes.

## Design Decisions

- Treat metadata as broker-owned internal data first. It may be attached to
  pending entries, pending exits, immediate close requests, and closed fills, but
  it must not appear in public JSON until a schema stage says so.
- Accept only string-compatible metadata where Pine's surface expects strings.
  Non-string values should follow the existing call argument validation path.
- Preserve current no-op behavior. Metadata on an order command that otherwise
  creates no supported order must not create a public event by itself.
- Keep `disable_alert` internal-only until strategy order-fill alert emission is
  implemented. Before that point, it can be parsed and stored but has no
  external side effect.
- Keep alert metadata separate from existing indicator-style `alert()` and
  `alertcondition()` events. Order-fill alert events require their own design
  before runtime output changes.

## Internal Model

Introduce a small internal metadata struct instead of spreading optional strings
across broker call signatures:

```text
StrategyOrderMetadata
  comment: Option<String>
  alert_message: Option<String>
  disable_alert: bool
```

Initial storage targets:

- pending market/limit/stop/stop-limit entries;
- pending exits for supported single-trigger, bracket, and trailing shapes;
- immediate `strategy.close` and `strategy.close_all` fill paths;
- final internal fill summaries used to record order events and closed trades.

The first implementation should pass metadata through these internal paths and
assert that the public JSON remains unchanged.

## Slice Sequence

### Slice OM0: Design Gate

Closed on 2026-06-11.

Document the internal metadata model, public-output boundary, and implementation
order. No runtime behavior changes.

Acceptance:

- this document exists;
- `docs/STRATEGY_INTERNAL_GAP_AUDIT.md` points order metadata work here;
- no conformance support is widened;
- `scripts/verify.sh` passes.

### Slice OM1: Signature And Diagnostic Boundary

Closed on 2026-06-11.

Accept metadata parameters in semantic analysis only for already-supported
order commands and preserve unsupported forms.

Candidate parameter boundaries:

- `strategy.entry`: `comment`, `alert_message`, `disable_alert`
- `strategy.exit`: `comment`, `comment_profit`, `comment_loss`,
  `comment_trailing`, `alert_message`, `alert_profit`, `alert_loss`,
  `alert_trailing`, `disable_alert`
- `strategy.close`: `comment`, `alert_message`, `immediately`,
  `disable_alert`
- `strategy.close_all`: `comment`, `alert_message`, `immediately`,
  `disable_alert`

For OM1, `immediately` remains unsupported because no separate execution timing
design has been opened. `strategy.close(..., immediately=...)` and
`strategy.close_all(..., immediately=...)` stay diagnostic-only.

Tests:

- sema fixture accepts string-compatible metadata and bool-compatible
  `disable_alert` on supported order commands with no behavior effect yet;
- sema fixture rejects non-string metadata values and non-bool
  `disable_alert`;
- negative fixture proves `immediately` remains unsupported.

### Slice OM2: Entry Metadata Storage

Closed on 2026-06-11.

Thread `StrategyOrderMetadata` through supported `strategy.entry` placement and
fill paths without exposing it publicly.

Tests:

- broker unit test proves pending entry metadata survives until fill;
- runtime fixture proves public orders/trades/position/equity JSON is unchanged
  when metadata is present;
- CLI/Python/WASM parity only if public host output is touched.

### Slice OM3: Exit Metadata Storage

Closed on 2026-06-11.

Thread metadata through supported `strategy.exit` pending exit paths, including
single-trigger, bracket, trailing, quantity reservation, active-entry
attachment, and omitted-`from_entry` all-entry paths.

Tests:

- broker tests prove metadata replacement on same pending-exit identity;
- broker tests prove metadata fan-out across all-entry and same-entry-id exits;
- runtime fixture proves public JSON remains unchanged.

### Slice OM4: Close Metadata Storage

Closed on 2026-06-11.

Thread metadata through `strategy.close` and `strategy.close_all` fill paths
without implementing `immediately`.

Tests:

- broker tests prove metadata is available at close fill recording time;
- runtime fixture proves public JSON remains unchanged;
- negative fixture keeps unsupported immediate-close timing outside the claim.

### Slice OM5: Alert Emission Design Gate

Closed on 2026-06-11. See
`docs/STRATEGY_ORDER_FILL_ALERTS_DESIGN.md`.

Before exposing order-fill alerts, a separate design note defines:

- output shape;
- placeholder interpolation;
- `disable_alert`;
- interaction with existing `alerts[]` output;
- CLI/Python/WASM schema implications.

OM5 does not emit order-fill alert events. Later implementation slices must
follow the design note before widening runtime behavior or public output.

## Closeout Criteria

Each metadata slice is closed only when:

- accepted parameters are fixture-backed;
- unsupported timing and alert-delivery behavior remains explicit;
- public JSON either stays byte-for-byte stable or a schema plan is opened;
- conformance wording is synchronized for any accepted syntax;
- host parity tests are added if public host output changes;
- `scripts/verify.sh` passes before commit.
