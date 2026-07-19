# Strategy Internal Gap Audit

Status: planning audit, refreshed through the fixture-backed
`close_entries_rule="ANY"` and close metadata subset on 2026-06-26.

This audit compares the current fixture-backed strategy subset with the
internal strategy behavior exposed by TradingView Pine Script strategy
documentation. It is intentionally limited to interpreter, semantic-analysis,
broker-emulator, runtime-output, and host-binding work. It excludes chart UI,
Strategy Tester UI panels, settings dialogs, external alert delivery, real
broker connectivity, and remote market-data services.

This document does not claim new support. Support claims still come from
`tests/fixtures/conformance.tsv`, snapshots, phase audits, and verification
results.

## Sources Reviewed

Repository evidence:

- `tests/fixtures/conformance.tsv`
- `docs/CONFORMANCE.md`
- `docs/EXECUTION_SEMANTICS.md`
- `docs/SEMANTIC_MODEL.md`
- `crates/pine-builtins/src/namespaces/strategy.rs`
- `crates/pine-sema/src/analyzer/strategy.rs`
- `crates/pine-runtime/src/strategy/`

TradingView Pine documentation reviewed on 2026-06-02:

- https://www.tradingview.com/pine-script-docs/concepts/strategies/
- https://www.tradingview.com/pine-script-docs/language/declaration-statements/
- https://www.tradingview.com/pine-script-docs/language/execution-model/
- https://www.tradingview.com/support/solutions/43000628599-strategy-properties/

## Current Internal Baseline

The current runtime can execute a historical, long-only strategy model with a
fixture-backed multi-entry ledger subset. It is still intentionally not a full
Pine broker emulator.

Implemented and fixture-backed:

- `strategy(...)` declaration with selected metadata, positive const
  `initial_capital`, fixed/cash/percent-of-equity default quantities,
  cash-per-contract, cash-per-order, and percent commission, fixed-tick
  slippage, fixed-tick limit verification, finite non-negative
  `margin_long`/`margin_short` declaration parsing, the current long-only active
  `margin_long` subset, positive integer `pyramiding`, and fixture-backed
  `close_entries_rule="FIFO"` plus id-specific long-only
  `close_entries_rule="ANY"`.
- `strategy.entry(id, strategy.long, qty=...)` and supported configured default
  quantities, including the Stage 13 fixture-backed long-only `pyramiding`
  subset and same-tick long price-based entry exceptions.
- `strategy.close(id)` as a full close of matching long entries, plus
  fixed-`qty` and `qty_percent` partial closes where `qty` wins when both
  quantity forms are supplied, with supported `comment`, `alert_message`, and
  `disable_alert` metadata.
- `strategy.close_all()` flattening all open long ledger entries in the current
  supported long-only multi-entry subset, with supported `comment`,
  `alert_message`, and `disable_alert` metadata.
- Public strategy output with `orders`, `trades`, `position`, `equity`,
  `alerts`, and `diagnostics`.
- Read-only state/count variables:
  - `strategy.position_size`
  - `strategy.position_avg_price`
  - `strategy.openprofit`
  - `strategy.netprofit`
  - `strategy.grossprofit`
  - `strategy.grossloss`
  - `strategy.avg_trade`
  - `strategy.avg_winning_trade`
  - `strategy.avg_losing_trade`
  - `strategy.max_drawdown`
  - `strategy.equity`
  - `strategy.closedtrades`
  - `strategy.opentrades`
  - `strategy.wintrades`
  - `strategy.losstrades`
  - `strategy.eventrades`
- `strategy.exit` for:
  - single triggers: `stop`, `limit`, `profit`, `loss`;
  - one-downside/one-upside brackets: `stop + limit`, `stop + profit`,
    `loss + limit`, `loss + profit`;
  - trailing forms: `trail_price + trail_offset`,
    `trail_points + trail_offset`;
  - optional `qty` and `qty_percent`;
  - explicit fixed-`qty` or `qty_percent` multiple reservations across
    single-trigger, bracket, and trailing exits;
  - omitted-quantity replacement and explicit-reservation clearing boundaries.
  - fixture-backed multi-entry long exits by explicit `from_entry`, omitted
    `from_entry`, current same-entry-id fan-out, and same-entry-id future-entry
    persistence for the supported trigger families.

Current public output remains intentionally smaller than Pine's full strategy
tester model. It does not expose pending orders, reservation ledgers, exit
reasons, bracket legs, trailing state, OCA state, alert metadata, or internal
trade keys.

## Gap Scale

- Small: likely one focused slice using the existing broker and public output
  shape.
- Medium: requires new internal state or semantics, but can probably preserve the
  current public runtime schema.
- Large: requires a broader broker model, new state lifetimes, or coordinated
  CLI/Python/WASM public-contract work.
- Foundation: should be designed before multiple later gaps, because many
  features depend on it.

## Priority Correction: Active Entry Attachment, Not Arbitrary Future Binding

The next strategy gap should not be described as "bind an exit to any future
entry with a matching id." Pine's documented behavior is narrower:

- an exit with `from_entry` applies to existing open trades with that entry id;
- exits can be created around active entry orders in the same strategy logic;
- if `from_entry` does not match a current position or active entry order, the
  command creates no exit orders.

Current docs and plans should use a narrower phrase such as active-entry exit
attachment or same-calculation entry/exit attachment. The supported unmatched
explicit-`from_entry` boundary is no-op behavior with no persistent future
reservations.

Current repo status: the supported absolute active-entry subset is fixture
backed. A same-calculation `strategy.exit` using absolute `stop`, `limit`, or
`trail_price` may target a matching active pending entry id. The fixture-backed
subset also resolves same-calculation entry-relative `profit`, `loss`, and
`trail_points` attachments, plus the supported stop/profit/loss/limit bracket
pairs, from the actual entry fill price. Other trigger combinations remain
outside the supported active-entry attachment boundary.

## Internal Gap Inventory

### 1. Strategy Declaration Properties

Current state: the declaration parser and runtime now support a meaningful but
still narrow property subset: positive const `initial_capital`, fixed, cash, and
percent-of-equity default quantities, the supported cash-per-contract,
cash-per-order, and percent commission modes, fixed-tick slippage, fixed-tick
limit verification through `backtest_fill_limits_assumption`, and finite
non-negative `margin_long`/`margin_short` declaration parsing. Active
`margin_long` also drives the current long-only capital-held, affordability, and
forced-liquidation subset. This remains declaration-property compatibility for a
single long-only broker, not a full broker-settings model.

Missing internal behavior:

- `pyramiding` behavior beyond the current fixture-backed long-only subset
- broader `close_entries_rule="ANY"` behavior beyond the fixture-backed
  id-specific long-only close/exit allocation subset
- `calc_on_order_fills`
- `calc_on_every_tick`
- `process_orders_on_close`
- `currency`
- commission modes beyond `strategy.commission.cash_per_contract`,
  `strategy.commission.cash_per_order`, and `strategy.commission.percent`
- fill models beyond fixed-tick slippage and fixed-tick limit verification on
  supported long fills
- runtime behavior for `margin_short`
- `risk_free_rate`
- `use_bar_magnifier`
- `fill_orders_on_standard_ohlc`
- strategy-specific alert and order-fill settings that affect runtime output

Gap size: large.

Best first slice: Stage 12 and Stage 13 closed the current declaration/property
and long-only pyramiding subset. Do not accept another property until the
boundary fixture, supported conformance wording, and runtime implications are
reviewed together. Order-on-close, calc-on-fill, short margin, and close-order
settings require larger broker-model designs.

### 2. Broker Execution Timing And Fill Model

Current state: historical execution is one pass per bar. Supported market
entries fill at the next historical bar open. Supported long limit, stop, and
stop-limit entries are represented as internal pending entries and fill before
script statements on eligible later bars. Supported closes fill at the current
bar close. Pending exits fill after script statements using simple OHLC trigger
checks and fixed prices.

Missing internal behavior:

- exact next-tick parity beyond the current historical bar-open/bar-OHLC
  subset;
- active-entry attachment beyond the fixture-backed absolute, entry-relative,
  trailing, and mixed bracket trigger forms;
- order processing on close;
- recalculation after order fills;
- realtime strategy rollback and repeated tick execution;
- historical intrabar tick assumptions;
- bar magnifier lower-timeframe fills;
- better/worse price behavior for limit and stop orders;
- stricter limit fill verification.

Gap size: foundation.

Best first slice: already closed for the current absolute active-entry subset
and the Stage 13 long-only multi-entry ledger subset. Do not widen further
without a separate design for entry-relative deferred price resolution,
realtime behavior, short exposure, or reversal.

### 3. Entry Orders

Current state: `strategy.entry` supports long market, limit, stop, and
stop-limit entries, with explicit positive quantity, configured fixed default
quantity, supported cash default quantity, or supported percent-of-equity
default quantity. Stage 13 adds a fixture-backed long-only `pyramiding` subset
with multiple open long ledger entries and selected same-tick price-based entry
exceptions.

Missing internal behavior:

- short entries;
- automatic reversal when an opposite entry is placed;
- pyramiding behavior beyond the current fixture-backed long-only multi-entry
  subset;
- entry metadata behavior beyond the supported `comment`, `alert_message`, and
  `disable_alert` subset;
- richer default quantity modes;
- interaction with `strategy.risk.allow_entry_in`.

Gap size: large.

Best first slice: not short/reversal first. The active pending-entry model,
supported stop/limit entry forms, and Stage 13 long-only multi-entry ledger are
already in place, so future entry-order work should target one narrow
metadata/default-sizing/risk interaction or wait for a short/reversal design.

### 4. Market Close Commands

Current state: `strategy.close(id)` closes matching long ledger entries at the
current bar close and cancels matching pending exits when the close fully
flattens that entry. `strategy.close(id, qty=...)` and
`strategy.close(id, qty_percent=...)` can partially close the matching current
long position while keeping matching pending exits alive; `qty` wins when both
quantity forms are supplied. `strategy.close_all()` closes all open long ledger
entries without requiring an entry id. Both close commands accept supported
`comment`, `alert_message`, and `disable_alert` metadata; closed-trade comment
helpers and supported order-fill alert payloads are fixture-backed for that
metadata. `close_entries_rule="FIFO"` is fixture-backed as the explicit default,
and `close_entries_rule="ANY"` is fixture-backed for id-specific long-only
`strategy.close(id)` and `strategy.exit(..., from_entry=id)`, including
same-entry-id partial exit allocation in stable ledger order.

Missing internal behavior:

- `immediately`;
- close behavior beyond the current fixture-backed long-only multi-entry
  allocation subset;
- broader `close_entries_rule="ANY"` allocation rules beyond the current
  id-specific long-only close/exit subset.

Gap size: medium to large.

Best first slice: full `strategy.close_all()`, partial `strategy.close()`, close
metadata, explicit FIFO, and the first id-specific long-only `"ANY"` allocation
subset are already closed. Do not continue market-close work until
`immediately` or broader non-default close-entry ordering has a separate
execution/allocation design.

### 5. Generic Orders And Cancellation

Current state: `strategy.order` is partial. The fixture-backed subset supports
explicit-quantity market-long add/increase orders, limit-long add/increase
orders through the supported long limit timing model, stop-long add/increase
orders through the supported long stop timing model, stop-limit-long
add/increase orders through the supported long stop-limit timing model, and
reduce-only market-short orders that shrink existing long exposure without
opening shorts. The supported subset also accepts `comment`, `alert_message`,
and `disable_alert` metadata; long fills retain entry comments, reduce-only
short fills retain exit comments, and supported fill payloads are exposed under
`strategy.alerts`.
Stage 6 added the fixture-backed supported `strategy.cancel(id)` and
`strategy.cancel_all()` subsets for current internal pending entries and exits.

Missing internal behavior:

- full `strategy.order()` as a generic long/short order that can open, reduce,
  reverse, or close positions across both sides;
- short exposure, reversal, and short price-based generic orders;
- generic-order-specific cancellation/OCA behavior beyond the current shared
  pending-entry cancellation subset.

Gap size: large.

Best first slice: do not start here. Cancellation needs a richer pending-order
book, and `strategy.order` needs short/reversal/netting semantics.

### 6. Exit Orders

Current state: this is the most developed part of the strategy runtime. The
current subset supports stop/limit/profit/loss, the first bracket subset,
trailing stops, partial quantities, percent quantities, explicit multiple
reservations, omitted-quantity replacement behavior, explicit `from_entry`
matching across supported long ledger entries, omitted-`from_entry` all-entry
behavior, current same-entry-id fan-out, and selected same-entry-id future-entry
persistence.

Missing internal behavior:

- exact semantics for overlapping price and tick alternatives in one exit call;
- entry-relative exit attachment to active entry orders before those entries
  fill beyond the already-supported fixture-backed subset;
- exits across multiple open trades beyond the current Stage 13 long-only
  supported trigger families;
- custom OCA names and OCA behavior;
- exit metadata behavior beyond the supported `comment`, `comment_profit`,
  `comment_loss`, `comment_trailing`, `alert_message`, `alert_profit`,
  `alert_loss`, `alert_trailing`, and `disable_alert` subset;
- broader no-op coverage for invalid `from_entry` ids outside the currently
  supported trigger and quantity shapes.

Gap size: medium.

Best first slice: active-entry attachment and the Stage 13 multi-entry long
subset are now closed for the current supported trigger families. The
`qty + qty_percent` precedence gap is also closed for the supported
`strategy.exit` trigger shapes: `qty` determines the reserved or filled
quantity. Remaining exit work should avoid syntax-tail expansion and instead
wait for a broader broker-model design when it depends on short exposure,
reversal, OCA allocation, public pending-order fields, or alert metadata.

### 7. OCA Groups And Reservation Semantics

Current state: explicit `qty` and `qty_percent` reservations exist internally for
supported single-trigger, bracket, and trailing exits. Public output does not
expose the reservation book.

Missing internal behavior:

- `strategy.oca.reduce`, `strategy.oca.cancel`, and `strategy.oca.none`;
- custom `oca_name`;
- OCA behavior for generic orders, not only exits;
- OCA behavior across pyramided entries and mixed order families.

Gap size: large.

Best first slice: defer until generic pending-order state exists. The current
reservation model is a useful base, but it is exit-specific.

### 8. Multiple Entries, Pyramiding, Shorts, And Reversals

Current state: Stage 13 adds a fixture-backed long-only multi-entry ledger for
the supported `pyramiding` subset. There is still no short exposure and no
reversal.

Missing internal behavior:

- multi-entry behavior beyond the current fixture-backed long-only subset;
- short positions;
- automatic reversal from long to short or short to long;
- configured close ordering beyond explicit default FIFO;
- net position versus individual trade accounting.

Gap size: foundation and large.

Best first slice: defer short/reversal work. The long-only multi-entry ledger is
settled for the current fixture-backed subset, but short exposure and reversal
still require a broader netting and close-order design.

### 9. Position Sizing And Account Model

Current state: explicit positive quantities, fixed default quantities, cash
default quantities, and a percent-of-equity default quantity subset are
supported. Cash, market value, equity, and net profit are calculated for the
current long-only model with the supported cost modes.

Missing internal behavior:

- contract/share minimum and rounding behavior;
- currency selection and conversion;
- margin requirements beyond supported explicit-`margin_long` long-entry
  affordability, long-only capital held, and long-only forced liquidation;
- margin-backed capital-held behavior beyond the current long-only explicit
  `margin_long` subset;
- account constraints beyond supported long-entry affordability.

Gap size: large.

Best next slice: use
`docs/STRATEGY_INTERNAL_MARGIN_ACCOUNT_MODEL_PLAN.md` as the design gate before
implementing additional margin, additional forced-liquidation, or
account-constraint behavior.

### 10. Costs And Price Adjustments

Current state: cash-per-contract commission, cash-per-order commission, percent
commission, fixed-tick slippage, and fixed-tick limit-order verification are
supported for configured strategy declarations. Other commission modes and
richer fill models remain unsupported.

Missing internal behavior:

- cost fields in trade data and performance variables.

Gap size: medium to large.

Best next slice: a narrow cost field or account-model setting would be bounded,
but it needs a precise script-visible versus public-output contract before
implementation.

### 11. Strategy Information Variables

Current state: position size, average price, open profit, net profit, net profit
percent, gross profit, gross profit percent, gross loss, gross loss percent,
average trade, average winning trade, average losing trade, their percent
variants, max run-up amount and percent, max drawdown amount and percent,
max contracts/shares held, equity, closed/open trade counts, and win/loss/even
trade counts are supported.

Missing internal behavior:

- remaining percent variants outside the supported profit/average-trade/run-up
  and drawdown subset;
- margin-backed capital-held behavior beyond the current long-only explicit
  `margin_long` subset;
- built-ins whose value depends on costs, margin, or individual trade records.

Gap size: medium.

Best next slice: the remaining script-visible reporting gap is now tied to the
margin/account model. Follow
`docs/STRATEGY_INTERNAL_MARGIN_ACCOUNT_MODEL_PLAN.md` before changing runtime
behavior.

### 12. Individual Trade Namespaces

Current state: `strategy.closedtrades` and `strategy.opentrades` are count
variables. Stage 7 Slice 0 also supports script-visible
`strategy.closedtrades.entry_price()`, `.exit_price()`, `.entry_bar_index()`,
`.exit_bar_index()`, `.entry_time()`, `.exit_time()`, `.commission()`,
`.entry_id()`, `.exit_id()`, `.size()`, and `.profit()` over the current
closed-trade list without public runtime schema expansion. Stage 7 Slice 6
also supports `strategy.opentrades.entry_price()` for the current supported
single open long position. Stage 7 Slice 7 adds
`strategy.opentrades.entry_bar_index()` for that same open position. Stage 7
Slice 8 adds `strategy.opentrades.entry_time()`, and Slice 9 adds
`strategy.opentrades.size()`. Stage 7 Slice 10 adds
`strategy.opentrades.profit()`. Stage 7 Slice 11 adds
`strategy.opentrades.entry_id()`. Stage 7 Slice 12 adds
`strategy.opentrades.commission()`. Stage 7 Slice 13 adds
`strategy.opentrades.max_runup()`. Stage 7 Slice 14 adds
`strategy.opentrades.max_drawdown()`. Stage 7 Slice 15 adds
`strategy.closedtrades.max_runup()`. Stage 7 Slice 16 adds
`strategy.closedtrades.max_drawdown()`. Stage 7 Slice 17 adds
cash-per-contract commission accounting for supported entries/exits and updates
closed/open trade commission functions without public runtime schema expansion.
Stage 7 Slice 18 adds cash-per-order commission accounting under the same
public contract. Stage 7 Slice 19 adds fixed-tick slippage for supported long
entry, close, and exit fill prices without public schema expansion. Stage 7
Slice 20 adds fixed-tick limit-order verification for supported long limit
entry and supported long limit/profit exit fills without public schema
expansion. Stage 7 Slice 21 adds percent commission accounting for supported
entry/exit fills under the same public contract. Stage 7 Slice 22 adds
`strategy.grossprofit` as a script-visible read-only series float without
public schema expansion. Stage 7 Slice 23 adds `strategy.grossloss` under the
same public-output contract. Stage 7 Slice 24 adds `strategy.avg_trade` under
the same public-output contract. Stage 7 Slice 25 adds
`strategy.avg_winning_trade` under the same public-output contract. Stage 7
Slice 26 adds `strategy.avg_losing_trade` under the same public-output
contract. Stage 7 Slice 27 adds `strategy.max_drawdown` under the same
public-output contract. Stage 7 Slice 28 adds `strategy.max_runup` under the
same public-output contract. Stage 7 Slice 29 aligns `strategy.max_drawdown`
with the official intrabar long-trade drawdown formula under the same
public-output contract. Stage 7 Slice 30 adds `strategy.max_runup_percent` and
`strategy.max_drawdown_percent` under the same public-output contract. Stage 7
Slice 31 adds `default_qty_type=strategy.percent_of_equity` for supported entry
default sizing without expanding public output. Stage 7 Slice 32 adds
`strategy.netprofit_percent`, `strategy.grossprofit_percent`, and
`strategy.grossloss_percent` without expanding public output. Stage 7 Slice 33
adds `strategy.avg_trade_percent`, `strategy.avg_winning_trade_percent`, and
`strategy.avg_losing_trade_percent` without expanding public output. Stage 7
Slice 34 adds `strategy.max_contracts_held_all`,
`strategy.max_contracts_held_long`, and `strategy.max_contracts_held_short`
without expanding public output. Stage 7 Slice 35 adds
`strategy.opentrades.capital_held` as a read-only variable in the current
no-margin subset, returning `na`. Strategy Internal Margin Slice M2 adds the
current long-only explicit-`margin_long` subset, where `capital_held` returns
`0.0` while flat and current open long market value times `margin_long / 100`
while open. Other namespace functions are unsupported.

Missing internal behavior:

- `strategy.closedtrades.*()` fields beyond the supported price/id/bar-index,
  time, commission, size, profit, runup, and drawdown subset;
- `strategy.opentrades.capital_held` behavior beyond the current long-only
  explicit-`margin_long` subset;
- open-trade and closed-trade records with enough retained metadata.

Gap size: large.

First slice closed: closed-trade `entry_price`, `exit_price`,
`entry_bar_index`, and `exit_bar_index` for the current closed-trade list are
script-variable only. Public JSON, Python, and WASM runtime schema remains
unchanged.

Second slice closed: closed-trade `size` and `profit` follow the same
script-variable-only, zero-based `trade_num` contract without changing public
runtime schema.

Third slice closed: closed-trade `entry_time` and `exit_time` expose the
already-retained timestamps under the same script-variable-only contract.

Fourth slice closed: closed-trade `commission` returns `0.0` until a supported
commission model is configured and keeps the same script-variable-only
contract.

Fifth slice closed: closed-trade `entry_id` exposes the retained entry id under
the same script-variable-only contract.

Sixth slice closed: closed-trade `exit_id` exposes the retained close or exit id
under the same script-variable-only contract.

### 13. Risk Management

Current state: `strategy.risk.*` is unsupported.

Missing internal behavior:

- entry-direction restrictions;
- max intraday loss, max drawdown, max position size, and similar risk stops;
- risk rules interacting with pending orders and recalculation behavior.

Gap size: large.

Best first slice: defer. Risk rules need a more complete broker state, order
book, and account model.

### 14. Strategy Alerts And Order Metadata

Current state: indicator-style alert events are supported in a narrow runtime
event model. Strategy order-fill alert metadata is stored internally on
supported strategy order paths, and
`docs/STRATEGY_ORDER_FILL_ALERTS_DESIGN.md` defines the order-fill alert event
boundary. The broker now records internal order-fill alert events for supported
entry, supported generic order, exit, close, and close_all fills, including
`disable_alert` suppression and exit leg-specific message selection. The current
public runtime `schemaVersion: 7` exposes those broker-owned payloads under
`strategy.alerts` with CLI, Python, and WASM parity. The host-layer
`{{strategy.order.alert_message}}` renderer is
available through explicit Python, CLI, and WASM helpers without changing
default runtime output.

Missing internal behavior:

- richer strategy-specific placeholder data beyond
  `{{strategy.order.alert_message}}`;
- concrete realtime delivery implementation for broker fills, including
  durable attempt-store behavior across host restarts, external delivery
  adapters such as webhook, retry, authentication, and failure reporting.

Gap size: medium.

Best next slice: use `docs/STRATEGY_EXTERNAL_ALERT_DELIVERY_ADAPTER_PLAN.md`
for the host-owned adapter boundary. Keep default runtime JSON, Python
dictionaries, WASM JSON, Pine-source alert placeholder support, and external
network delivery unchanged until restart-safe durable attempt-store behavior,
executable retry scheduling, concrete authentication secret stores, diagnostic
emission, and failure reporting are implemented through explicit host APIs.

## Recommended Internal Roadmap

1. Keep the Stage 13 long-only multi-entry ledger subset stable with fixture and
   host-parity coverage.
2. Prefer narrow diagnostics, accounting, metadata, or built-in coverage slices
   that preserve the current public runtime schema.
3. Use `docs/STRATEGY_INTERNAL_MARGIN_ACCOUNT_MODEL_PLAN.md` before widening
   margin/account behavior.
4. Keep strategy order-fill alert metadata and public `strategy.alerts` stable
   before adding placeholder rendering or external delivery.
5. Defer short exposure, reversals, generic `strategy.order()`, custom OCA
   behavior, public pending-order records, and broader non-default close-entry
   ordering until a new broker-model design explicitly covers their state
   transitions.

## Completion Gates For Any Slice

Each internal strategy slice should include:

- semantic fixtures for accepted and rejected forms;
- broker unit tests for state transitions and accounting;
- runtime fixtures and golden snapshots;
- incremental/runtime interaction tests where state timing matters;
- CLI, Python, and WASM parity tests if public output or host behavior changes;
- synchronized `tests/fixtures/conformance.tsv`, matrix snapshot, docs, and
  release notes;
- a phase audit recording the supported and unsupported boundary;
- `scripts/verify.sh` before closeout.
