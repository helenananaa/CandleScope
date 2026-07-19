use pine_ir::HirCallArg;

use crate::builtins::args::call_arg_expr;
use crate::{HistoricalRuntime, PineValue, RuntimeError};

impl<'a> HistoricalRuntime<'a> {
    pub(super) fn eval_strategy_closed_trade_field(
        &mut self,
        callee: &str,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let Some(trade_num_expr) = call_arg_expr(args, 0, "trade_num") else {
            return Ok(PineValue::Na);
        };
        let Some(trade_num) = self.eval_expr(trade_num_expr)?.as_i64() else {
            return Ok(PineValue::Na);
        };
        let Some(trade) = self.strategy_broker.closed_trade(trade_num) else {
            return Ok(PineValue::Na);
        };

        Ok(match callee {
            "strategy.closedtrades.entry_price" => PineValue::Float(trade.entry_price),
            "strategy.closedtrades.entry_comment" => self
                .strategy_broker
                .closed_trade_entry_comment(trade_num)
                .map(|value| PineValue::String(value.to_owned()))
                .unwrap_or(PineValue::Na),
            "strategy.closedtrades.entry_id" => PineValue::String(trade.id.clone()),
            "strategy.closedtrades.exit_price" => PineValue::Float(trade.exit_price),
            "strategy.closedtrades.exit_comment" => self
                .strategy_broker
                .closed_trade_exit_comment(trade_num)
                .map(|value| PineValue::String(value.to_owned()))
                .unwrap_or(PineValue::Na),
            "strategy.closedtrades.exit_id" => PineValue::String(trade.exit_id.clone()),
            "strategy.closedtrades.entry_bar_index" => {
                PineValue::Int(i64::try_from(trade.entry_bar_index).unwrap_or(i64::MAX))
            }
            "strategy.closedtrades.exit_bar_index" => {
                PineValue::Int(i64::try_from(trade.exit_bar_index).unwrap_or(i64::MAX))
            }
            "strategy.closedtrades.entry_time" => PineValue::Int(trade.entry_time),
            "strategy.closedtrades.exit_time" => PineValue::Int(trade.exit_time),
            "strategy.closedtrades.commission" => self
                .strategy_broker
                .closed_trade_commission(trade_num)
                .map_or(PineValue::Na, PineValue::Float),
            "strategy.closedtrades.size" => PineValue::Float(trade.qty),
            "strategy.closedtrades.profit" => PineValue::Float(trade.profit),
            "strategy.closedtrades.profit_percent" => self
                .strategy_broker
                .closed_trade_profit_percent(trade_num)
                .map_or(PineValue::Na, PineValue::Float),
            "strategy.closedtrades.max_runup" => self
                .strategy_broker
                .closed_trade_max_runup(trade_num)
                .map_or(PineValue::Na, PineValue::Float),
            "strategy.closedtrades.max_runup_percent" => self
                .strategy_broker
                .closed_trade_max_runup_percent(trade_num)
                .map_or(PineValue::Na, PineValue::Float),
            "strategy.closedtrades.max_drawdown" => self
                .strategy_broker
                .closed_trade_max_drawdown(trade_num)
                .map_or(PineValue::Na, PineValue::Float),
            "strategy.closedtrades.max_drawdown_percent" => self
                .strategy_broker
                .closed_trade_max_drawdown_percent(trade_num)
                .map_or(PineValue::Na, PineValue::Float),
            _ => PineValue::Na,
        })
    }

    pub(super) fn eval_strategy_open_trade_field(
        &mut self,
        callee: &str,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let Some(trade_num_expr) = call_arg_expr(args, 0, "trade_num") else {
            return Ok(PineValue::Na);
        };
        let Some(trade_num) = self.eval_expr(trade_num_expr)?.as_i64() else {
            return Ok(PineValue::Na);
        };

        Ok(match callee {
            "strategy.opentrades.entry_price" => self
                .strategy_broker
                .open_trade_entry_price(trade_num)
                .map_or(PineValue::Na, PineValue::Float),
            "strategy.opentrades.entry_comment" => self
                .strategy_broker
                .open_trade_entry_comment(trade_num)
                .map(|value| PineValue::String(value.to_owned()))
                .unwrap_or(PineValue::Na),
            "strategy.opentrades.entry_id" => self
                .strategy_broker
                .open_trade_entry_id(trade_num)
                .map(|value| PineValue::String(value.to_owned()))
                .unwrap_or(PineValue::Na),
            "strategy.opentrades.entry_bar_index" => self
                .strategy_broker
                .open_trade_entry_bar_index(trade_num)
                .map(|value| PineValue::Int(i64::try_from(value).unwrap_or(i64::MAX)))
                .unwrap_or(PineValue::Na),
            "strategy.opentrades.entry_time" => self
                .strategy_broker
                .open_trade_entry_time(trade_num)
                .map_or(PineValue::Na, PineValue::Int),
            "strategy.opentrades.size" => self
                .strategy_broker
                .open_trade_size(trade_num)
                .map_or(PineValue::Na, PineValue::Float),
            "strategy.opentrades.profit" => {
                let Some(bar) = self.current_bar else {
                    return Ok(PineValue::Na);
                };
                self.strategy_broker
                    .open_trade_profit(trade_num, bar.close)
                    .map_or(PineValue::Na, PineValue::Float)
            }
            "strategy.opentrades.profit_percent" => {
                let Some(bar) = self.current_bar else {
                    return Ok(PineValue::Na);
                };
                self.strategy_broker
                    .open_trade_profit_percent(trade_num, bar.close)
                    .map_or(PineValue::Na, PineValue::Float)
            }
            "strategy.opentrades.commission" => self
                .strategy_broker
                .open_trade_commission(trade_num)
                .map_or(PineValue::Na, PineValue::Float),
            "strategy.opentrades.max_runup" => self
                .strategy_broker
                .open_trade_max_runup(trade_num)
                .map_or(PineValue::Na, PineValue::Float),
            "strategy.opentrades.max_runup_percent" => self
                .strategy_broker
                .open_trade_max_runup_percent(trade_num)
                .map_or(PineValue::Na, PineValue::Float),
            "strategy.opentrades.max_drawdown" => self
                .strategy_broker
                .open_trade_max_drawdown(trade_num)
                .map_or(PineValue::Na, PineValue::Float),
            "strategy.opentrades.max_drawdown_percent" => self
                .strategy_broker
                .open_trade_max_drawdown_percent(trade_num)
                .map_or(PineValue::Na, PineValue::Float),
            _ => PineValue::Na,
        })
    }
}
