# Strategy Internal Stage 7 Trade Records Audit

Status: closed on 2026-06-04 for the current long-only trade-record,
cost, reporting, default-sizing, and active-margin account subset. Slices 0,
1, 2, and 3 closed on 2026-06-02; Slices 4, 5, 6, 7, 8, 9, 10, 11, 12, 13,
14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32,
33, 34, and 35 closed on 2026-06-03; the long-only margin/account model closed
through `docs/STRATEGY_INTERNAL_MARGIN_ACCOUNT_MODEL_PLAN.md` Slice M5 on
2026-06-03.

Stage 7 enriches strategy reporting and accounting while preserving the current
one-net-long broker and public output contract unless a later slice explicitly
designs a new host schema.

## Slice 0: Closed Trade Field Functions

Closed on 2026-06-02.

Supported script-visible functions:

- `strategy.closedtrades.entry_price(trade_num)`;
- `strategy.closedtrades.exit_price(trade_num)`;
- `strategy.closedtrades.entry_bar_index(trade_num)`;
- `strategy.closedtrades.exit_bar_index(trade_num)`.

Contract:

- strategy-mode scripts only;
- `trade_num` is a zero-based integer index into the current closed-trade list;
- missing, negative, out-of-range, or non-integer indexes return `na`;
- values read the existing closed trade records retained by the broker;
- public CLI JSON, Python dictionaries, and WASM JSON keep the existing strategy
  output shape with no new top-level fields.

Evidence:

- runtime fixture: `tests/fixtures/runtime/strategy_closedtrades_fields.pine`;
- semantic fixtures:
  `tests/fixtures/sema/supported_strategy_closedtrades_fields.pine`,
  `tests/fixtures/sema/unsupported_strategy_closedtrades_fields_indicator.pine`,
  and `tests/fixtures/sema/unsupported_strategy_order_and_trade_namespaces.pine`;
- host parity tests cover Python and WASM plot values; CLI matrix and
  conformance metadata cover fixture registration.

Still unsupported:

- `strategy.opentrades.*` namespace functions outside `entry_price`,
  `entry_id`, `entry_bar_index`, `entry_time`, `size`, `profit`,
  `commission`, `max_runup`, `max_drawdown`, and the `capital_held` variable;
- closed-trade field functions beyond `entry_price`, `entry_id`, `exit_price`,
  `exit_id`, `entry_bar_index`, `exit_bar_index`, `entry_time`, `exit_time`,
  `commission`, `size`, `profit`, `max_runup`, and `max_drawdown`;
- richer reporting metrics;
- public trade namespace schema expansion.

## Slice 1: Closed Trade Size And Profit Functions

Closed on 2026-06-02.

Supported script-visible functions:

- `strategy.closedtrades.size(trade_num)`;
- `strategy.closedtrades.profit(trade_num)`.

Contract:

- strategy-mode scripts only;
- `trade_num` follows the same zero-based integer index contract as Slice 0;
- missing, negative, out-of-range, or non-integer indexes return `na`;
- `size` returns the closed trade's absolute filled quantity in the current
  long-only subset;
- `profit` returns the closed trade's realized profit;
- public CLI JSON, Python dictionaries, and WASM JSON keep the existing strategy
  output shape with no new top-level fields.

## Slice 2: Closed Trade Time Functions

Closed on 2026-06-02.

Supported script-visible functions:

- `strategy.closedtrades.entry_time(trade_num)`;
- `strategy.closedtrades.exit_time(trade_num)`.

Contract:

- strategy-mode scripts only;
- `trade_num` follows the same zero-based integer index contract as Slices 0
  and 1;
- missing, negative, out-of-range, or non-integer indexes return `na`;
- `entry_time` and `exit_time` return the timestamps already retained on the
  closed trade record;
- public CLI JSON, Python dictionaries, and WASM JSON keep the existing strategy
  output shape with no new top-level fields.

## Slice 3: Closed Trade Commission Function

Closed on 2026-06-02.

Supported script-visible function:

- `strategy.closedtrades.commission(trade_num)`.

Contract:

- strategy-mode scripts only;
- `trade_num` follows the same zero-based integer index contract as Slices 0,
  1, and 2;
- missing, negative, out-of-range, or non-integer indexes return `na`;
- `commission` returns `0.0` without configured commission, and later cost
  slices may wire supported commission models into the same script-visible
  function;
- public CLI JSON, Python dictionaries, and WASM JSON keep the existing strategy
  output shape with no new top-level fields.

## Slice 4: Closed Trade Entry Id Function

Closed on 2026-06-03.

Supported script-visible function:

- `strategy.closedtrades.entry_id(trade_num)`.

Contract:

- strategy-mode scripts only;
- `trade_num` follows the same zero-based integer index contract as Slices 0
  through 3;
- missing, negative, out-of-range, or non-integer indexes return `na`;
- `entry_id` returns the entry id already retained on the closed trade record;
- public CLI JSON, Python dictionaries, and WASM JSON keep the existing strategy
  output shape with no new top-level fields.

## Slice 5: Closed Trade Exit Id Function

Closed on 2026-06-03.

Supported script-visible function:

- `strategy.closedtrades.exit_id(trade_num)`.

Contract:

- strategy-mode scripts only;
- `trade_num` follows the same zero-based integer index contract as Slices 0
  through 4;
- missing, negative, out-of-range, or non-integer indexes return `na`;
- `exit_id` returns the close id for `strategy.close` / `strategy.close_all`
  fills and the pending exit id for `strategy.exit` fills;
- public CLI JSON, Python dictionaries, and WASM JSON keep the existing strategy
  output shape with no new top-level fields.

## Slice 6: Open Trade Entry Price Function

Closed on 2026-06-03.

Supported script-visible function:

- `strategy.opentrades.entry_price(trade_num)`.

Contract:

- strategy-mode scripts only;
- `trade_num == 0` addresses the current supported single open long position;
- missing, negative, out-of-range, or non-integer indexes return `na`;
- flat state returns `na`;
- the value reads the current open position average entry price already tracked
  by the broker;
- public CLI JSON, Python dictionaries, and WASM JSON keep the existing strategy
  output shape with no new top-level fields or open-trade records.

Evidence:

- runtime fixture: `tests/fixtures/runtime/strategy_opentrades_fields.pine`;
- semantic fixture:
  `tests/fixtures/sema/supported_strategy_opentrades_fields.pine`;
- unsupported namespace fixture keeps other open-trade fields out of scope with
  `strategy.opentrades.entry_comment(0)`;
- host parity tests cover CLI snapshots plus Python and WASM plot values.

## Slice 7: Open Trade Entry Bar Index Function

Closed on 2026-06-03.

Supported script-visible function:

- `strategy.opentrades.entry_bar_index(trade_num)`.

Contract:

- strategy-mode scripts only;
- `trade_num == 0` addresses the current supported single open long position;
- missing, negative, out-of-range, or non-integer indexes return `na`;
- flat state returns `na`;
- the value reads the current open position entry fill bar already tracked by
  the broker;
- public CLI JSON, Python dictionaries, and WASM JSON keep the existing strategy
  output shape with no new top-level fields or open-trade records.

Evidence:

- runtime fixture: `tests/fixtures/runtime/strategy_opentrades_fields.pine`;
- semantic fixture:
  `tests/fixtures/sema/supported_strategy_opentrades_fields.pine`;
- requested-context negative fixture:
  `tests/fixtures/sema/unsupported_request_strategy_state.pine`;
- host parity tests cover CLI snapshots plus Python and WASM plot values.

## Slice 8: Open Trade Entry Time Function

Closed on 2026-06-03.

Supported script-visible function:

- `strategy.opentrades.entry_time(trade_num)`.

Contract:

- strategy-mode scripts only;
- `trade_num == 0` addresses the current supported single open long position;
- missing, negative, out-of-range, or non-integer indexes return `na`;
- flat state returns `na`;
- the value reads the current open position entry fill timestamp already
  tracked by the broker;
- public CLI JSON, Python dictionaries, and WASM JSON keep the existing strategy
  output shape with no new top-level fields or open-trade records.

Evidence:

- runtime fixture: `tests/fixtures/runtime/strategy_opentrades_fields.pine`;
- semantic fixture:
  `tests/fixtures/sema/supported_strategy_opentrades_fields.pine`;
- requested-context negative fixture:
  `tests/fixtures/sema/unsupported_request_strategy_state.pine`;
- host parity tests cover CLI snapshots plus Python and WASM plot values.

## Slice 9: Open Trade Size Function

Closed on 2026-06-03.

Supported script-visible function:

- `strategy.opentrades.size(trade_num)`.

Contract:

- strategy-mode scripts only;
- `trade_num == 0` addresses the current supported single open long position;
- missing, negative, out-of-range, or non-integer indexes return `na`;
- flat state returns `na`;
- the value reads the current open position size already tracked by the broker;
- public CLI JSON, Python dictionaries, and WASM JSON keep the existing strategy
  output shape with no new top-level fields or open-trade records.

Evidence:

- runtime fixture: `tests/fixtures/runtime/strategy_opentrades_fields.pine`;
- semantic fixture:
  `tests/fixtures/sema/supported_strategy_opentrades_fields.pine`;
- requested-context negative fixture:
  `tests/fixtures/sema/unsupported_request_strategy_state.pine`;
- host parity tests cover CLI snapshots plus Python and WASM plot values.

## Slice 10: Open Trade Profit Function

Closed on 2026-06-03.

Supported script-visible function:

- `strategy.opentrades.profit(trade_num)`.

Contract:

- strategy-mode scripts only;
- `trade_num == 0` addresses the current supported single open long position;
- missing, negative, out-of-range, or non-integer indexes return `na`;
- flat state returns `na`;
- the value reads the current close-based floating profit already tracked by
  the broker for the current open position;
- public CLI JSON, Python dictionaries, and WASM JSON keep the existing strategy
  output shape with no new top-level fields or open-trade records.

Evidence:

- runtime fixture: `tests/fixtures/runtime/strategy_opentrades_fields.pine`;
- semantic fixture:
  `tests/fixtures/sema/supported_strategy_opentrades_fields.pine`;
- requested-context negative fixture:
  `tests/fixtures/sema/unsupported_request_strategy_state.pine`;
- host parity tests cover CLI snapshots plus Python and WASM plot values.

## Slice 11: Open Trade Entry Id Function

Closed on 2026-06-03.

Supported script-visible function:

- `strategy.opentrades.entry_id(trade_num)`.

Contract:

- strategy-mode scripts only;
- `trade_num == 0` addresses the current supported single open long position;
- missing, negative, out-of-range, or non-integer indexes return `na`;
- flat state returns `na`;
- the value reads the retained current entry id already tracked by the broker;
- public CLI JSON, Python dictionaries, and WASM JSON keep the existing strategy
  output shape with no new top-level fields or open-trade records.

Evidence:

- runtime fixture: `tests/fixtures/runtime/strategy_opentrades_fields.pine`;
- semantic fixture:
  `tests/fixtures/sema/supported_strategy_opentrades_fields.pine`;
- requested-context negative fixture:
  `tests/fixtures/sema/unsupported_request_strategy_state.pine`;
- unsupported namespace fixture keeps other open-trade fields out of scope with
  `strategy.opentrades.entry_comment(0)`;
- host parity tests cover CLI snapshots plus Python and WASM plot values.

## Slice 12: Open Trade Commission Function

Closed on 2026-06-03.

Supported script-visible function:

- `strategy.opentrades.commission(trade_num)`.

Contract:

- strategy-mode scripts only;
- `trade_num == 0` addresses the current supported single open long position;
- missing, negative, out-of-range, or non-integer indexes return `na`;
- flat state returns `na`;
- the value is `0.0` without configured commission, and later cost slices may
  wire supported commission models into the same script-visible function;
- public CLI JSON, Python dictionaries, and WASM JSON keep the existing strategy
  output shape with no new top-level fields or open-trade records.

Evidence:

- runtime fixture: `tests/fixtures/runtime/strategy_opentrades_fields.pine`;
- semantic fixture:
  `tests/fixtures/sema/supported_strategy_opentrades_fields.pine`;
- requested-context negative fixture:
  `tests/fixtures/sema/unsupported_request_strategy_state.pine`;
- unsupported namespace fixture keeps other open-trade fields out of scope with
  `strategy.opentrades.entry_comment(0)`;
- host parity tests cover CLI snapshots plus Python and WASM plot values.

## Slice 13: Open Trade Max Runup Function

Closed on 2026-06-03.

Supported script-visible function:

- `strategy.opentrades.max_runup(trade_num)`.

Contract:

- strategy-mode scripts only;
- `trade_num == 0` addresses the current supported single open long position;
- missing, negative, out-of-range, or non-integer indexes return `na`;
- flat state returns `na`;
- the value is the largest high-based favorable excursion seen so far for the
  current supported open long position;
- public CLI JSON, Python dictionaries, and WASM JSON keep the existing strategy
  output shape with no new top-level fields or open-trade records.

Evidence:

- runtime fixture: `tests/fixtures/runtime/strategy_opentrades_fields.pine`;
- semantic fixture:
  `tests/fixtures/sema/supported_strategy_opentrades_fields.pine`;
- requested-context negative fixture:
  `tests/fixtures/sema/unsupported_request_strategy_state.pine`;
- unsupported namespace fixture keeps other open-trade fields out of scope with
  `strategy.opentrades.entry_comment(0)`;
- host parity tests cover CLI snapshots plus Python and WASM plot values.

## Slice 14: Open Trade Max Drawdown Function

Closed on 2026-06-03.

Supported script-visible function:

- `strategy.opentrades.max_drawdown(trade_num)`.

Contract:

- strategy-mode scripts only;
- `trade_num == 0` addresses the current supported single open long position;
- missing, negative, out-of-range, or non-integer indexes return `na`;
- flat state returns `na`;
- the value is the largest low-based adverse excursion seen so far for the
  current supported open long position;
- public CLI JSON, Python dictionaries, and WASM JSON keep the existing strategy
  output shape with no new top-level fields or open-trade records.

Evidence:

- runtime fixture: `tests/fixtures/runtime/strategy_opentrades_fields.pine`;
- semantic fixture:
  `tests/fixtures/sema/supported_strategy_opentrades_fields.pine`;
- requested-context negative fixture:
  `tests/fixtures/sema/unsupported_request_strategy_state.pine`;
- unsupported namespace fixture keeps other open-trade fields out of scope with
  `strategy.opentrades.entry_comment(0)`;
- host parity tests cover CLI snapshots plus Python and WASM plot values.

## Slice 15: Closed Trade Max Runup Function

Closed on 2026-06-03.

Supported script-visible function:

- `strategy.closedtrades.max_runup(trade_num)`.

Contract:

- strategy-mode scripts only;
- `trade_num` is a zero-based integer index into the current closed-trade list;
- missing, negative, out-of-range, or non-integer indexes return `na`;
- the value is the largest high-based favorable excursion retained for the
  closed trade quantity;
- public CLI JSON, Python dictionaries, and WASM JSON keep the existing strategy
  output shape with no new top-level fields or public trade metric fields.

Evidence:

- runtime fixture: `tests/fixtures/runtime/strategy_closedtrades_fields.pine`;
- semantic fixture:
  `tests/fixtures/sema/supported_strategy_closedtrades_fields.pine`;
- requested-context negative fixture:
  `tests/fixtures/sema/unsupported_request_strategy_state.pine`;
- unsupported namespace fixture keeps other closed-trade fields out of scope
  with `strategy.closedtrades.exit_comment(0)`;
- host parity tests cover CLI snapshots plus Python and WASM plot values.

## Slice 16: Closed Trade Max Drawdown Function

Closed on 2026-06-03.

Supported script-visible function:

- `strategy.closedtrades.max_drawdown(trade_num)`.

Contract:

- strategy-mode scripts only;
- `trade_num` is a zero-based integer index into the current closed-trade list;
- missing, negative, out-of-range, or non-integer indexes return `na`;
- the value is the largest low-based adverse excursion retained for the closed
  trade quantity;
- public CLI JSON, Python dictionaries, and WASM JSON keep the existing strategy
  output shape with no new top-level fields or public trade metric fields.

Evidence:

- runtime fixture: `tests/fixtures/runtime/strategy_closedtrades_fields.pine`;
- semantic fixture:
  `tests/fixtures/sema/supported_strategy_closedtrades_fields.pine`;
- requested-context negative fixture:
  `tests/fixtures/sema/unsupported_request_strategy_state.pine`;
- unsupported namespace fixture keeps other closed-trade fields out of scope
  with `strategy.closedtrades.exit_comment(0)`;
- host parity tests cover CLI snapshots plus Python and WASM plot values.

## Slice 17: Cash Per Contract Commission

Closed on 2026-06-03.

Supported declaration subset:

- `strategy(..., commission_type=strategy.commission.cash_per_contract,
  commission_value=N)`.

Contract:

- strategy-mode scripts only;
- `commission_value` must be a finite non-negative const numeric value;
- each supported entry and exit debits `qty * commission_value`;
- closed trade `profit`, `strategy.netprofit`, and trade-count outcomes use net
  realized profit after entry-plus-exit commission for the closed quantity;
- `strategy.closedtrades.commission(trade_num)` returns entry-plus-exit
  cash-per-contract commission for the closed quantity;
- `strategy.opentrades.commission(trade_num)` returns the current open
  cash-per-contract entry commission for `trade_num == 0`;
- equity snapshots and `strategy.equity` include supported commission cash
  debits;
- public CLI JSON, Python dictionaries, and WASM JSON keep the existing strategy
  output shape with no new top-level fields or public trade metric fields.

Evidence:

- runtime fixture:
  `tests/fixtures/runtime/strategy_commission_cash_per_contract.pine`;
- semantic fixtures:
  `tests/fixtures/sema/supported_strategy_commission_cash_per_contract.pine`
  and `tests/fixtures/sema/unsupported_strategy_commission_unknown.pine`;
- host parity tests cover CLI snapshots plus Python plot and trade/equity
  values.

## Slice 18: Cash Per Order Commission

Closed on 2026-06-03.

Supported declaration subset:

- `strategy(..., commission_type=strategy.commission.cash_per_order,
  commission_value=N)`.

Contract:

- strategy-mode scripts only;
- `commission_value` must be a finite non-negative const numeric value;
- each supported entry and exit fill debits one fixed `commission_value`;
- closed trade `profit`, `strategy.netprofit`, and trade-count outcomes use net
  realized profit after allocated entry commission plus exit commission for the
  closed quantity;
- partial exits allocate the original entry-order commission proportionally to
  the closed quantity and leave the remainder attached to the open trade;
- `strategy.closedtrades.commission(trade_num)` returns allocated entry
  cash-per-order commission plus exit cash-per-order commission for the closed
  quantity;
- `strategy.opentrades.commission(trade_num)` returns the remaining open
  cash-per-order entry commission for `trade_num == 0`;
- equity snapshots and `strategy.equity` include supported commission cash
  debits;
- public CLI JSON, Python dictionaries, and WASM JSON keep the existing strategy
  output shape with no new top-level fields or public trade metric fields.

Evidence:

- runtime fixture:
  `tests/fixtures/runtime/strategy_commission_cash_per_order.pine`;
- semantic fixture:
  `tests/fixtures/sema/supported_strategy_commission_cash_per_order.pine`;
- unsupported commission modes remain covered by
  `tests/fixtures/sema/unsupported_strategy_commission_unknown.pine`;
- host parity tests cover CLI snapshots plus Python plot and trade/equity
  values.

## Slice 19: Fixed Tick Slippage

Closed on 2026-06-03.

Supported declaration subset:

- `strategy(..., slippage=N)`.

Contract:

- strategy-mode scripts only;
- `slippage` must be a finite non-negative integer const tick count;
- ticks convert through the current fixed `syminfo.mintick` subset;
- supported long entry fill prices are worsened upward after trigger selection;
- supported long close and `strategy.exit` fill prices are worsened downward
  after trigger selection;
- trigger conditions are unchanged by slippage;
- order fill prices, trade entry/exit prices, realized profit, floating profit,
  and equity snapshots use the adjusted fill prices;
- public CLI JSON, Python dictionaries, and WASM JSON keep the existing strategy
  output shape with no new top-level fields or public trade metric fields.

Evidence:

- runtime fixtures: `tests/fixtures/runtime/strategy_slippage.pine` and
  `tests/fixtures/runtime/strategy_exit_slippage.pine`;
- semantic fixtures:
  `tests/fixtures/sema/supported_strategy_slippage.pine` and
  `tests/fixtures/sema/unsupported_strategy_slippage.pine`;
- host parity tests cover CLI snapshots plus Python plot and trade/equity
  values.

## Slice 20: Fixed Tick Limit Verification

Closed on 2026-06-03.

Supported declaration subset:

- `strategy(..., backtest_fill_limits_assumption=N)`.

Contract:

- strategy-mode scripts only;
- `backtest_fill_limits_assumption` must be a finite non-negative integer const
  tick count;
- ticks convert through the current fixed `syminfo.mintick` subset;
- supported long limit entries and stop-limit entry limit legs require
  `low <= limit - ticks * syminfo.mintick`;
- supported long limit/profit exit fills and bracket upside fills require
  `high >= limit_or_profit_price + ticks * syminfo.mintick`;
- verified limit orders still fill at the original limit/profit price, not the
  verification threshold;
- stop/loss/trailing triggers and slippage direction are unchanged;
- public CLI JSON, Python dictionaries, and WASM JSON keep the existing strategy
  output shape with no new top-level fields or public trade metric fields.

Evidence:

- runtime fixtures:
  `tests/fixtures/runtime/strategy_limit_verification_entry.pine` and
  `tests/fixtures/runtime/strategy_limit_verification_exit.pine`;
- semantic fixtures:
  `tests/fixtures/sema/supported_strategy_limit_verification.pine` and
  `tests/fixtures/sema/unsupported_strategy_limit_verification.pine`;
- host parity tests cover CLI snapshots plus Python trade/order values.

## Slice 21: Percent Commission

Closed on 2026-06-03.

Supported declaration subset:

- `strategy(..., commission_type=strategy.commission.percent,
  commission_value=N)`.

Contract:

- strategy-mode scripts only;
- `commission_value` must be a finite non-negative const numeric value;
- each supported entry and exit fill debits
  `qty * fill_price * commission_value / 100`;
- closed trade `profit`, `strategy.netprofit`, and trade-count outcomes use net
  realized profit after allocated entry commission plus exit commission for the
  closed quantity;
- partial exits allocate the original entry percentage commission
  proportionally to the closed quantity and leave the remainder attached to the
  open trade;
- `strategy.closedtrades.commission(trade_num)` returns allocated entry
  percent commission plus exit percent commission for the closed quantity;
- `strategy.opentrades.commission(trade_num)` returns the remaining open entry
  percent commission for `trade_num == 0`;
- equity snapshots and `strategy.equity` include supported percent commission
  cash debits;
- public CLI JSON, Python dictionaries, and WASM JSON keep the existing strategy
  output shape with no new top-level fields or public trade metric fields.

Evidence:

- runtime fixture: `tests/fixtures/runtime/strategy_commission_percent.pine`;
- semantic fixtures:
  `tests/fixtures/sema/supported_strategy_commission_percent.pine` and
  `tests/fixtures/sema/unsupported_strategy_commission_unknown.pine`;
- host parity tests cover CLI snapshots plus Python plot and trade/equity
  values.

## Slice 22: Gross Profit State Variable

Closed on 2026-06-03.

Supported variable:

- `strategy.grossprofit`.

Contract:

- strategy-mode scripts only;
- read-only `series float`;
- returns cumulative positive realized closed-trade profit;
- losing, flat, and current open trades do not change it;
- supported commission, slippage, and limit verification feed into realized
  closed-trade profit before the positive-only sum;
- public CLI JSON, Python dictionaries, and WASM JSON keep the existing
  strategy output shape with no new top-level fields.

Evidence:

- runtime fixture: `tests/fixtures/runtime/strategy_trade_outcome_counts.pine`;
- semantic fixtures:
  `tests/fixtures/sema/supported_strategy_profit_state.pine`,
  `tests/fixtures/sema/unsupported_strategy_state_indicator.pine`,
  `tests/fixtures/sema/unsupported_request_strategy_state.pine`, and
  `tests/fixtures/sema/unsupported_strategy_state_mutation.pine`;
- host parity tests cover CLI snapshots plus Python and WASM plot values.

## Slice 23: Gross Loss State Variable

Closed on 2026-06-03.

Supported variable:

- `strategy.grossloss`.

Contract:

- strategy-mode scripts only;
- read-only `series float`;
- returns cumulative realized closed-trade loss as a positive value;
- winning, flat, and current open trades do not change it;
- supported commission, slippage, and limit verification feed into realized
  closed-trade profit/loss before the loss-only sum;
- public CLI JSON, Python dictionaries, and WASM JSON keep the existing
  strategy output shape with no new top-level fields.

Evidence:

- runtime fixture: `tests/fixtures/runtime/strategy_trade_outcome_counts.pine`;
- semantic fixtures:
  `tests/fixtures/sema/supported_strategy_profit_state.pine`,
  `tests/fixtures/sema/unsupported_strategy_state_indicator.pine`,
  `tests/fixtures/sema/unsupported_request_strategy_state.pine`, and
  `tests/fixtures/sema/unsupported_strategy_state_mutation.pine`;
- host parity tests cover CLI snapshots plus Python and WASM plot values.

## Slice 24: Average Trade State Variable

Closed on 2026-06-03.

Supported variable:

- `strategy.avg_trade`.

Contract:

- strategy-mode scripts only;
- read-only `series float`;
- returns average realized profit/loss per closed trade;
- returns `na` before the first closed trade;
- current open trades do not affect it;
- supported commission, slippage, and limit verification feed into realized
  closed-trade profit/loss before the average;
- public CLI JSON, Python dictionaries, and WASM JSON keep the existing
  strategy output shape with no new top-level fields.

Evidence:

- runtime fixture: `tests/fixtures/runtime/strategy_trade_outcome_counts.pine`;
- semantic fixtures:
  `tests/fixtures/sema/supported_strategy_profit_state.pine`,
  `tests/fixtures/sema/unsupported_strategy_state_indicator.pine`,
  `tests/fixtures/sema/unsupported_request_strategy_state.pine`, and
  `tests/fixtures/sema/unsupported_strategy_state_mutation.pine`;
- host parity tests cover CLI snapshots plus Python and WASM plot values.

## Slice 25: Average Winning Trade State Variable

Closed on 2026-06-03.

Supported variable:

- `strategy.avg_winning_trade`.

Contract:

- strategy-mode scripts only;
- read-only `series float`;
- returns average realized profit among winning closed trades only;
- returns `na` before the first winning closed trade;
- losing, flat, and current open trades do not affect it;
- supported commission, slippage, and limit verification feed into realized
  closed-trade profit/loss before filtering and averaging;
- public CLI JSON, Python dictionaries, and WASM JSON keep the existing
  strategy output shape with no new top-level fields.

Evidence:

- runtime fixture: `tests/fixtures/runtime/strategy_trade_outcome_counts.pine`;
- semantic fixtures:
  `tests/fixtures/sema/supported_strategy_profit_state.pine`,
  `tests/fixtures/sema/unsupported_strategy_state_indicator.pine`,
  `tests/fixtures/sema/unsupported_request_strategy_state.pine`, and
  `tests/fixtures/sema/unsupported_strategy_state_mutation.pine`;
- host parity tests cover CLI snapshots plus Python and WASM plot values.

## Slice 26: Average Losing Trade State Variable

Closed on 2026-06-03.

Supported variable:

- `strategy.avg_losing_trade`.

Contract:

- strategy-mode scripts only;
- read-only `series float`;
- returns average realized loss among losing closed trades only as a positive
  value;
- returns `na` before the first losing closed trade;
- winning, flat, and current open trades do not affect it;
- supported commission, slippage, and limit verification feed into realized
  closed-trade profit/loss before filtering and averaging;
- public CLI JSON, Python dictionaries, and WASM JSON keep the existing
  strategy output shape with no new top-level fields.

Evidence:

- runtime fixture: `tests/fixtures/runtime/strategy_trade_outcome_counts.pine`;
- semantic fixtures:
  `tests/fixtures/sema/supported_strategy_profit_state.pine`,
  `tests/fixtures/sema/unsupported_strategy_state_indicator.pine`,
  `tests/fixtures/sema/unsupported_request_strategy_state.pine`, and
  `tests/fixtures/sema/unsupported_strategy_state_mutation.pine`;
- host parity tests cover CLI snapshots plus Python and WASM plot values.

## Slice 27: Maximum Drawdown State Variable

Closed on 2026-06-03.

Supported variable:

- `strategy.max_drawdown`.

Contract:

- strategy-mode scripts only;
- read-only `series float`;
- returns the maximum intrabar equity drawdown amount over the current
  supported long-only trading interval;
- uses the supported entry equity, the maximum equity before that entry, and
  the lowest low reached while the supported position is open;
- returns `0` before any drawdown from the maximum equity baseline;
- margin, currency conversion, pyramiding, and short exposure remain outside
  the current account model;
- public CLI JSON, Python dictionaries, and WASM JSON keep the existing
  strategy output shape with no new top-level fields.

Evidence:

- runtime fixture: `tests/fixtures/runtime/strategy_profit_state.pine`;
- semantic fixtures:
  `tests/fixtures/sema/supported_strategy_profit_state.pine`,
  `tests/fixtures/sema/unsupported_strategy_state_indicator.pine`,
  `tests/fixtures/sema/unsupported_request_strategy_state.pine`, and
  `tests/fixtures/sema/unsupported_strategy_state_mutation.pine`;
- host parity tests cover CLI snapshots plus Python and WASM plot values.

## Slice 28: Maximum Run-Up State Variable

Closed on 2026-06-03.

Supported variable:

- `strategy.max_runup`.

Contract:

- strategy-mode scripts only;
- read-only `series float`;
- returns the maximum intrabar equity run-up amount over the current supported
  long-only trading interval;
- uses the supported entry equity, the minimum equity before that entry, and
  the highest high reached while the supported position is open;
- returns `0` before any run-up from the minimum equity baseline;
- margin, currency conversion, pyramiding, and short exposure remain outside
  the current account model;
- public CLI JSON, Python dictionaries, and WASM JSON keep the existing
  strategy output shape with no new top-level fields.

Evidence:

- runtime fixture: `tests/fixtures/runtime/strategy_profit_state.pine`;
- semantic fixtures:
  `tests/fixtures/sema/supported_strategy_profit_state.pine`,
  `tests/fixtures/sema/unsupported_strategy_state_indicator.pine`,
  `tests/fixtures/sema/unsupported_request_strategy_state.pine`, and
  `tests/fixtures/sema/unsupported_strategy_state_mutation.pine`;
- host parity tests cover CLI snapshots plus Python and WASM plot values.

## Slice 29: Maximum Drawdown Official Intrabar Alignment

Closed on 2026-06-03.

Correction:

- `strategy.max_drawdown` now uses the TradingView-documented intrabar
  long-trade drawdown formula for the current supported long-only account
  model;
- the runtime tracks the maximum equity before each supported entry, the entry
  equity, and the lowest low reached while the position is open;
- a dedicated runtime regression test covers a bar whose close returns to entry
  price while intrabar low still produces drawdown;
- public CLI JSON, Python dictionaries, and WASM JSON keep the existing
  strategy output shape with no new top-level fields.

Evidence:

- runtime tests:
  `strategy_max_drawdown_follows_intrabar_low_and_max_equity` and
  `strategy_max_drawdown_uses_intrabar_low`;
- runtime fixture: `tests/fixtures/runtime/strategy_profit_state.pine`;
- host parity tests continue to cover CLI snapshots plus Python and WASM plot
  values.

## Slice 30: Maximum Run-Up/Drawdown Percent State Variables

Closed on 2026-06-03.

Supported variables:

- `strategy.max_runup_percent`;
- `strategy.max_drawdown_percent`.

Contract:

- strategy-mode scripts only;
- read-only `series float`;
- return the maximum intrabar equity run-up or drawdown percentage over the
  current supported long-only trading interval;
- divide the supported run-up or drawdown amount by entry price times current
  supported position quantity and multiply by 100;
- return `0` before any run-up or drawdown from the relevant equity baseline;
- margin, currency conversion, pyramiding, and short exposure remain outside
  the current account model;
- public CLI JSON, Python dictionaries, and WASM JSON keep the existing
  strategy output shape with no new top-level fields.

Evidence:

- runtime tests:
  `strategy_max_runup_and_drawdown_percent_use_trade_value_denominator` and
  `strategy_profit_state_variables_follow_realized_and_open_profit`;
- runtime fixture: `tests/fixtures/runtime/strategy_profit_state.pine`;
- semantic fixtures:
  `tests/fixtures/sema/supported_strategy_profit_state.pine`,
  `tests/fixtures/sema/unsupported_strategy_state_indicator.pine`,
  `tests/fixtures/sema/unsupported_request_strategy_state.pine`, and
  `tests/fixtures/sema/unsupported_strategy_state_mutation.pine`;
- host parity tests cover CLI snapshots plus Python and WASM plot values.

## Slice 31: Percent-Of-Equity Default Entry Quantity

Closed on 2026-06-03.

Supported declaration subset:

- `strategy(..., default_qty_type=strategy.percent_of_equity,
  default_qty_value=N)`.

Contract:

- strategy-mode scripts only;
- positive const numeric `default_qty_value`;
- applies when a supported `strategy.entry` omits explicit `qty`;
- resolves the absolute quantity once at placement time as
  `strategy.equity * N / 100 / close`, using the current supported equity and
  current close;
- explicit `qty` still takes precedence over the configured default quantity;
- no public CLI JSON, Python dictionary, or WASM JSON schema expansion;
- cash sizing, contract/share rounding policy, margin constraints beyond the
  current explicit-`margin_long` long-only account subset, symbol precision
  rounding, and currency conversion remain unsupported.

Evidence:

- runtime test:
  `strategy_entry_uses_percent_of_equity_default_qty_when_qty_is_absent`;
- runtime fixture:
  `tests/fixtures/runtime/strategy_percent_of_equity_default_quantity.pine`;
- semantic fixture:
  `tests/fixtures/sema/supported_strategy_percent_of_equity_default_quantity.pine`;
- unsupported fixture:
  `tests/fixtures/sema/unsupported_strategy_default_quantity.pine` keeps
  `strategy.cash` guarded;
- CLI golden snapshot covers the public runtime shape.

## Slice 32: Profit Percent State Variables

Closed on 2026-06-03.

Supported variables:

- `strategy.netprofit_percent`;
- `strategy.grossprofit_percent`;
- `strategy.grossloss_percent`.

Contract:

- strategy-mode scripts only;
- read-only `series float`;
- divide the corresponding realized amount by `initial_capital` and multiply by
  100;
- `strategy.netprofit_percent` uses cumulative realized closed-trade profit,
  excluding current open profit;
- `strategy.grossprofit_percent` uses positive realized closed-trade profit
  only;
- `strategy.grossloss_percent` uses realized closed-trade losses as a positive
  value;
- public CLI JSON, Python dictionaries, and WASM JSON keep the existing
  strategy output shape with no new top-level fields.

Evidence:

- runtime test:
  `strategy_profit_percent_variables_use_initial_capital_denominator`;
- runtime fixture:
  `tests/fixtures/runtime/strategy_profit_percent_state.pine`;
- semantic fixtures:
  `tests/fixtures/sema/supported_strategy_profit_state.pine`,
  `tests/fixtures/sema/unsupported_strategy_state_indicator.pine`,
  `tests/fixtures/sema/unsupported_request_strategy_state.pine`, and
  `tests/fixtures/sema/unsupported_strategy_state_mutation.pine`;
- host parity tests cover CLI snapshots plus Python and WASM plot values.

## Slice 33: Average Trade Percent Variables

Closed on 2026-06-03.

Supported variables:

- `strategy.avg_trade_percent`;
- `strategy.avg_winning_trade_percent`;
- `strategy.avg_losing_trade_percent`.

Contract:

- strategy-mode scripts only;
- read-only `series float`;
- each closed trade records an internal percentage value as net closed-trade
  profit divided by that closed trade's entry price times quantity, multiplied
  by 100;
- `strategy.avg_trade_percent` averages all closed-trade percentage values and
  returns `na` before the first closed trade;
- `strategy.avg_winning_trade_percent` averages winning closed-trade
  percentage values only and returns `na` before the first winning trade;
- `strategy.avg_losing_trade_percent` averages losing closed-trade percentage
  values as positive percentages and returns `na` before the first losing
  trade;
- current open trades do not affect any of the values;
- public CLI JSON, Python dictionaries, and WASM JSON keep the existing
  strategy output shape with no new top-level fields or trade fields.

Evidence:

- runtime test:
  `strategy_trade_outcome_count_variables_follow_closed_trade_profits`;
- runtime fixture:
  `tests/fixtures/runtime/strategy_trade_outcome_counts.pine`;
- semantic fixtures:
  `tests/fixtures/sema/supported_strategy_profit_state.pine`,
  `tests/fixtures/sema/unsupported_strategy_state_indicator.pine`,
  `tests/fixtures/sema/unsupported_request_strategy_state.pine`, and
  `tests/fixtures/sema/unsupported_strategy_state_mutation.pine`;
- host parity tests cover CLI snapshots plus Python and WASM plot values.

## Slice 34: Maximum Contracts Held Variables

Closed on 2026-06-03.

Supported variables:

- `strategy.max_contracts_held_all`;
- `strategy.max_contracts_held_long`;
- `strategy.max_contracts_held_short`.

Contract:

- strategy-mode scripts only;
- read-only `series float`;
- report the maximum contracts/shares/lots/units held over the whole trading
  range;
- in the current long-only, one-net-position subset, `all` and `long` track the
  maximum filled long-entry quantity seen so far;
- `short` remains `0.0` because short entries are unsupported;
- current open trades and closed trades are both included once their entry fill
  has occurred;
- public CLI JSON, Python dictionaries, and WASM JSON keep the existing
  strategy output shape with no new top-level fields.

Evidence:

- runtime test:
  `strategy_position_state_variables_follow_broker_mutations`;
- runtime fixture:
  `tests/fixtures/runtime/strategy_position_state.pine`;
- semantic fixtures:
  `tests/fixtures/sema/supported_strategy_position_state.pine`,
  `tests/fixtures/sema/unsupported_strategy_state_indicator.pine`,
  `tests/fixtures/sema/unsupported_request_strategy_state.pine`, and
  `tests/fixtures/sema/unsupported_strategy_state_mutation.pine`;
- host parity tests cover CLI snapshots plus Python and WASM plot values.

## Slice 35: Open-Trade Capital Held Variable

Closed on 2026-06-03.

Supported variable:

- `strategy.opentrades.capital_held`.

Contract:

- strategy-mode scripts only;
- read-only `series float`;
- supported as the unique variable under the `strategy.opentrades.*`
  namespace, not as a `trade_num` field function;
- returns `na` in the current no-margin subset, matching Pine's behavior when
  the strategy does not simulate funding trades with nonzero margin settings;
- Strategy Internal Margin Slice M2 adds the current long-only explicit
  `margin_long` subset, where the variable returns `0.0` while flat and
  current open long market value times `margin_long / 100` while open;
- Strategy Internal Margin Slice M3 adds supported long-entry affordability
  checks at the actual fill price for explicit active `margin_long`;
- Strategy Internal Margin Slice M5 adds the first long-only forced-liquidation
  subset using `bar.low` and whole-unit truncation;
- `margin_short`, symbol precision rounding, and margin liquidation price
  remain unsupported;
- public CLI JSON, Python dictionaries, and WASM JSON keep the existing
  strategy output shape with no new top-level fields.

Evidence:

- runtime fixture:
  `tests/fixtures/runtime/strategy_opentrades_fields.pine`;
- runtime fixture:
  `tests/fixtures/runtime/strategy_margin_capital_held_long.pine`;
- semantic fixtures:
  `tests/fixtures/sema/supported_strategy_opentrades_fields.pine`,
  `tests/fixtures/sema/unsupported_strategy_state_indicator.pine`,
  `tests/fixtures/sema/unsupported_request_strategy_state.pine`, and
  `tests/fixtures/sema/unsupported_strategy_state_mutation.pine`;
- host parity tests cover CLI snapshots plus Python and WASM plot values.

## Stage 7 Closeout Boundary

Stage 7 is closed for the current fixture-backed one-net-long reporting and
accounting subset. Runtime support now covers the documented closed/open trade
field functions, supported commission modes, fixed-tick slippage, fixed-tick
limit verification, percent-of-equity default entry sizing, supported
profit/run-up/drawdown reporting variables, maximum contracts held variables,
`strategy.opentrades.capital_held`, explicit active `margin_long` long-entry
affordability checks, and the first long-only forced-liquidation subset.

Still deferred:

- public open-trade or pending-order records;
- public reservation, liquidation-price, exit-reason, bracket-leg, or trailing
  state fields;
- `strategy.margin_liquidation_price`;
- short-margin behavior, shorts, reversals, pyramiding, and per-entry ledgers;
- generic `strategy.order()` and full OCA behavior;
- symbol precision rounding, currency conversion, and richer broker fill
  models beyond the documented long-only subset.

The next strategy step should start as a Stage 8 broker-expansion design gate,
not as a runtime compatibility patch. That design needs to settle multi-entry
ledgers, net-position accounting, short/reversal behavior, OCA allocation,
same-bar precedence, and whether any public JSON/Python/WASM contract must
change before conformance is widened.
