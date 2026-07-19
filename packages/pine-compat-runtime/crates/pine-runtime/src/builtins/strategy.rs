use pine_ir::{CallSiteId, HirCallArg};

use crate::builtins::args::call_arg_expr;
use crate::strategy::{
    LossLimitBracketSpec, LossProfitBracketSpec, StopProfitBracketSpec, StrategyExitMetadata,
    TrailPointsExitSpec, TrailPriceExitSpec,
};
use crate::*;

mod exit_placements;
mod fields;
mod metadata;

#[derive(Clone, Copy)]
enum StrategyExitQuantityArg {
    Full,
    Fixed(f64),
    Percent(f64),
}

struct RuntimeExitTicksPlacement {
    id: String,
    from_entry: String,
    ticks: f64,
    mintick: f64,
    quantity: StrategyExitQuantityArg,
    bar_index: usize,
    metadata: StrategyExitMetadata,
}

struct RuntimeExitBracketPlacement {
    id: String,
    from_entry: String,
    downside_price: f64,
    upside_price: f64,
    quantity: StrategyExitQuantityArg,
    bar_index: usize,
    metadata: StrategyExitMetadata,
}

impl<'a> HistoricalRuntime<'a> {
    pub(crate) fn eval_strategy_call(
        &mut self,
        callee: &str,
        _call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Option<Result<PineValue, RuntimeError>> {
        Some(match callee {
            "strategy.convert_to_account" | "strategy.convert_to_symbol" => {
                self.eval_strategy_currency_conversion(args)
            }
            "strategy.default_entry_qty" => self.eval_strategy_default_entry_qty(args),
            "strategy.entry" => self.eval_strategy_entry(args),
            "strategy.order" => self.eval_strategy_order(args),
            "strategy.close" => self.eval_strategy_close(args),
            "strategy.close_all" => self.eval_strategy_close_all(args),
            "strategy.cancel" => self.eval_strategy_cancel(args),
            "strategy.cancel_all" => self.eval_strategy_cancel_all(),
            "strategy.exit" => self.eval_strategy_exit(args),
            "strategy.closedtrades.entry_price"
            | "strategy.closedtrades.entry_comment"
            | "strategy.closedtrades.entry_id"
            | "strategy.closedtrades.exit_price"
            | "strategy.closedtrades.exit_comment"
            | "strategy.closedtrades.exit_id"
            | "strategy.closedtrades.entry_bar_index"
            | "strategy.closedtrades.exit_bar_index"
            | "strategy.closedtrades.entry_time"
            | "strategy.closedtrades.exit_time"
            | "strategy.closedtrades.commission"
            | "strategy.closedtrades.size"
            | "strategy.closedtrades.profit"
            | "strategy.closedtrades.profit_percent"
            | "strategy.closedtrades.max_runup"
            | "strategy.closedtrades.max_runup_percent"
            | "strategy.closedtrades.max_drawdown"
            | "strategy.closedtrades.max_drawdown_percent" => {
                self.eval_strategy_closed_trade_field(callee, args)
            }
            "strategy.opentrades.entry_price"
            | "strategy.opentrades.entry_comment"
            | "strategy.opentrades.entry_id"
            | "strategy.opentrades.entry_bar_index"
            | "strategy.opentrades.entry_time"
            | "strategy.opentrades.size"
            | "strategy.opentrades.profit"
            | "strategy.opentrades.profit_percent"
            | "strategy.opentrades.commission"
            | "strategy.opentrades.max_runup"
            | "strategy.opentrades.max_runup_percent"
            | "strategy.opentrades.max_drawdown"
            | "strategy.opentrades.max_drawdown_percent" => {
                self.eval_strategy_open_trade_field(callee, args)
            }
            _ => return None,
        })
    }

    fn eval_strategy_currency_conversion(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let Some(value_expr) = call_arg_expr(args, 0, "value") else {
            return Ok(PineValue::Na);
        };
        Ok(self
            .eval_expr(value_expr)?
            .as_f64()
            .map_or(PineValue::Na, PineValue::Float))
    }

    fn eval_strategy_default_entry_qty(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let Some(fill_price_expr) = call_arg_expr(args, 0, "fill_price") else {
            return Ok(PineValue::Na);
        };
        let fill_price = self
            .eval_expr(fill_price_expr)?
            .as_f64()
            .unwrap_or(f64::NAN);
        let Some(bar) = self.current_bar else {
            return Err(RuntimeError {
                message: "`strategy.default_entry_qty` requires an active bar".to_owned(),
            });
        };
        let equity = self.strategy_broker.equity_value(bar.close);
        Ok(self
            .program
            .strategy_settings
            .default_entry_qty(equity, fill_price)
            .map_or(PineValue::Na, PineValue::Float))
    }

    fn eval_strategy_entry(&mut self, args: &[HirCallArg]) -> Result<PineValue, RuntimeError> {
        let Some(bar) = self.current_bar else {
            return Err(RuntimeError {
                message: "`strategy.entry` requires an active bar".to_owned(),
            });
        };
        let Some(id_expr) = call_arg_expr(args, 0, "id") else {
            return Ok(PineValue::Void);
        };
        let Some(direction_expr) = call_arg_expr(args, 1, "direction") else {
            return Ok(PineValue::Void);
        };

        let id = match self.eval_expr(id_expr)? {
            PineValue::String(value) => value,
            _ => return Ok(PineValue::Void),
        };
        let direction = self.eval_expr(direction_expr)?;
        if direction != PineValue::String("strategy.long".to_owned()) {
            return Ok(PineValue::Void);
        }
        let qty_expr = args
            .iter()
            .find(|arg| arg.name.as_deref() == Some("qty"))
            .or_else(|| args.get(2).filter(|arg| arg.name.is_none()))
            .map(|arg| &arg.value);
        let limit_expr = args
            .iter()
            .find(|arg| arg.name.as_deref() == Some("limit"))
            .or_else(|| args.get(3).filter(|arg| arg.name.is_none()))
            .map(|arg| &arg.value);
        let stop_expr = args
            .iter()
            .find(|arg| arg.name.as_deref() == Some("stop"))
            .or_else(|| args.get(4).filter(|arg| arg.name.is_none()))
            .map(|arg| &arg.value);
        let metadata = self.eval_strategy_entry_metadata(args)?;

        let qty = if let Some(qty_expr) = qty_expr {
            self.eval_expr(qty_expr)?.as_f64().unwrap_or(f64::NAN)
        } else {
            let equity = self.strategy_broker.equity_value(bar.close);
            self.program
                .strategy_settings
                .default_entry_qty(equity, bar.close)
                .unwrap_or(f64::NAN)
        };
        if let (Some(limit_expr), Some(stop_expr)) = (limit_expr, stop_expr) {
            let limit = self.eval_expr(limit_expr)?.as_f64().unwrap_or(f64::NAN);
            let stop = self.eval_expr(stop_expr)?.as_f64().unwrap_or(f64::NAN);
            self.strategy_broker
                .place_pending_stop_limit_long_entry_with_metadata(
                    id, qty, stop, limit, self.bars, metadata,
                );
            return Ok(PineValue::Void);
        }
        if let Some(limit_expr) = limit_expr {
            let limit = self.eval_expr(limit_expr)?.as_f64().unwrap_or(f64::NAN);
            self.strategy_broker
                .place_pending_limit_long_entry_with_metadata(id, qty, limit, self.bars, metadata);
            return Ok(PineValue::Void);
        }
        if let Some(stop_expr) = stop_expr {
            let stop = self.eval_expr(stop_expr)?.as_f64().unwrap_or(f64::NAN);
            self.strategy_broker
                .place_pending_stop_long_entry_with_metadata(id, qty, stop, self.bars, metadata);
            return Ok(PineValue::Void);
        }

        self.strategy_broker
            .place_pending_market_long_entry_with_metadata(id, qty, self.bars, metadata);
        Ok(PineValue::Void)
    }

    fn eval_strategy_order(&mut self, args: &[HirCallArg]) -> Result<PineValue, RuntimeError> {
        let Some(bar) = self.current_bar else {
            return Err(RuntimeError {
                message: "`strategy.order` requires an active bar".to_owned(),
            });
        };
        let Some(id_expr) = call_arg_expr(args, 0, "id") else {
            return Ok(PineValue::Void);
        };
        let Some(direction_expr) = call_arg_expr(args, 1, "direction") else {
            return Ok(PineValue::Void);
        };
        let optional_order_arg_expr = |index: usize, name: &str| {
            args.iter()
                .find(|arg| arg.name.as_deref() == Some(name))
                .or_else(|| args.get(index).filter(|arg| arg.name.is_none()))
                .map(|arg| &arg.value)
        };
        let qty_expr = optional_order_arg_expr(2, "qty");
        let limit_expr = optional_order_arg_expr(3, "limit");
        let stop_expr = optional_order_arg_expr(4, "stop");

        let id = match self.eval_expr(id_expr)? {
            PineValue::String(value) => value,
            _ => return Ok(PineValue::Void),
        };
        let direction = self.eval_expr(direction_expr)?;
        let qty = if let Some(qty_expr) = qty_expr {
            self.eval_expr(qty_expr)?.as_f64().unwrap_or(f64::NAN)
        } else if direction == PineValue::String("strategy.long".to_owned()) {
            let equity = self.strategy_broker.equity_value(bar.close);
            self.program
                .strategy_settings
                .default_entry_qty(equity, bar.close)
                .unwrap_or(f64::NAN)
        } else {
            return Ok(PineValue::Void);
        };
        let limit = match limit_expr {
            Some(expr) => Some(self.eval_expr(expr)?.as_f64().unwrap_or(f64::NAN)),
            None => None,
        };
        let stop = match stop_expr {
            Some(expr) => Some(self.eval_expr(expr)?.as_f64().unwrap_or(f64::NAN)),
            None => None,
        };
        let metadata = self.eval_strategy_order_metadata(args)?;
        match direction {
            PineValue::String(value) if value == "strategy.long" => match (limit, stop) {
                (Some(limit), Some(stop)) => self
                    .strategy_broker
                    .place_pending_stop_limit_long_order_with_metadata(
                        id, qty, stop, limit, self.bars, metadata,
                    ),
                (Some(limit), None) => self
                    .strategy_broker
                    .place_pending_limit_long_order_with_metadata(
                        id, qty, limit, self.bars, metadata,
                    ),
                (None, Some(stop)) => self
                    .strategy_broker
                    .place_pending_stop_long_order_with_metadata(
                        id, qty, stop, self.bars, metadata,
                    ),
                (None, None) => self
                    .strategy_broker
                    .place_pending_market_long_order_with_metadata(id, qty, self.bars, metadata),
            },
            PineValue::String(value)
                if value == "strategy.short" && limit.is_none() && stop.is_none() =>
            {
                self.strategy_broker
                    .place_pending_market_short_order_with_metadata(id, qty, self.bars, metadata);
            }
            _ => {}
        }
        Ok(PineValue::Void)
    }

    fn eval_strategy_close(&mut self, args: &[HirCallArg]) -> Result<PineValue, RuntimeError> {
        let Some(bar) = self.current_bar else {
            return Err(RuntimeError {
                message: "`strategy.close` requires an active bar".to_owned(),
            });
        };
        let Some(id_expr) = call_arg_expr(args, 0, "id") else {
            return Ok(PineValue::Void);
        };
        let id = match self.eval_expr(id_expr)? {
            PineValue::String(value) => value,
            _ => return Ok(PineValue::Void),
        };
        let qty_expr = args
            .iter()
            .find(|arg| arg.name.as_deref() == Some("qty"))
            .map(|arg| &arg.value);
        let qty_percent_expr = args
            .iter()
            .find(|arg| arg.name.as_deref() == Some("qty_percent"))
            .map(|arg| &arg.value);
        let metadata = self.eval_strategy_close_metadata(args, 3)?;

        if let Some(qty_expr) = qty_expr {
            let qty = self.eval_expr(qty_expr)?.as_f64().unwrap_or(f64::NAN);
            self.strategy_broker
                .with_next_close_metadata(metadata, |broker| {
                    broker.close_long_qty(id, self.bars, bar.time, bar.close, qty)
                });
        } else if let Some(qty_percent_expr) = qty_percent_expr {
            let qty_percent = self
                .eval_expr(qty_percent_expr)?
                .as_f64()
                .unwrap_or(f64::NAN);
            self.strategy_broker
                .with_next_close_metadata(metadata, |broker| {
                    broker.close_long_qty_percent(id, self.bars, bar.time, bar.close, qty_percent)
                });
        } else {
            self.strategy_broker
                .with_next_close_metadata(metadata, |broker| {
                    broker.close_long(id, self.bars, bar.time, bar.close)
                });
        }
        Ok(PineValue::Void)
    }

    fn eval_strategy_close_all(&mut self, args: &[HirCallArg]) -> Result<PineValue, RuntimeError> {
        let Some(bar) = self.current_bar else {
            return Err(RuntimeError {
                message: "`strategy.close_all` requires an active bar".to_owned(),
            });
        };
        let metadata = self.eval_strategy_close_metadata(args, 0)?;

        self.strategy_broker
            .with_next_close_metadata(metadata, |broker| {
                broker.close_all_long(self.bars, bar.time, bar.close)
            });
        Ok(PineValue::Void)
    }

    fn eval_strategy_cancel(&mut self, args: &[HirCallArg]) -> Result<PineValue, RuntimeError> {
        let Some(_bar) = self.current_bar else {
            return Err(RuntimeError {
                message: "`strategy.cancel` requires an active bar".to_owned(),
            });
        };
        let Some(id_expr) = call_arg_expr(args, 0, "id") else {
            return Ok(PineValue::Void);
        };
        let id = match self.eval_expr(id_expr)? {
            PineValue::String(value) => value,
            _ => return Ok(PineValue::Void),
        };

        self.strategy_broker.cancel_pending_order(&id);
        Ok(PineValue::Void)
    }

    fn eval_strategy_cancel_all(&mut self) -> Result<PineValue, RuntimeError> {
        let Some(_bar) = self.current_bar else {
            return Err(RuntimeError {
                message: "`strategy.cancel_all` requires an active bar".to_owned(),
            });
        };

        self.strategy_broker.cancel_all_pending_orders();
        Ok(PineValue::Void)
    }

    fn eval_strategy_exit(&mut self, args: &[HirCallArg]) -> Result<PineValue, RuntimeError> {
        let Some(_bar) = self.current_bar else {
            return Err(RuntimeError {
                message: "`strategy.exit` requires an active bar".to_owned(),
            });
        };
        let Some(id_expr) = call_arg_expr(args, 0, "id") else {
            return Ok(PineValue::Void);
        };
        let from_entry_expr = args
            .iter()
            .find(|arg| arg.name.as_deref() == Some("from_entry"))
            .or_else(|| args.get(1).filter(|arg| arg.name.is_none()))
            .map(|arg| &arg.value);
        let stop_expr = args
            .iter()
            .find(|arg| arg.name.as_deref() == Some("stop"))
            .or_else(|| args.get(2).filter(|arg| arg.name.is_none()))
            .map(|arg| &arg.value);
        let limit_expr = args
            .iter()
            .find(|arg| arg.name.as_deref() == Some("limit"))
            .or_else(|| args.get(3).filter(|arg| arg.name.is_none()))
            .map(|arg| &arg.value);
        let profit_expr = args
            .iter()
            .find(|arg| arg.name.as_deref() == Some("profit"))
            .map(|arg| &arg.value);
        let loss_expr = args
            .iter()
            .find(|arg| arg.name.as_deref() == Some("loss"))
            .map(|arg| &arg.value);
        let trail_price_expr = args
            .iter()
            .find(|arg| arg.name.as_deref() == Some("trail_price"))
            .map(|arg| &arg.value);
        let trail_points_expr = args
            .iter()
            .find(|arg| arg.name.as_deref() == Some("trail_points"))
            .map(|arg| &arg.value);
        let trail_offset_expr = args
            .iter()
            .find(|arg| arg.name.as_deref() == Some("trail_offset"))
            .map(|arg| &arg.value);
        let qty_expr = args
            .iter()
            .find(|arg| arg.name.as_deref() == Some("qty"))
            .map(|arg| &arg.value);
        let qty_percent_expr = args
            .iter()
            .find(|arg| arg.name.as_deref() == Some("qty_percent"))
            .map(|arg| &arg.value);
        let metadata = self.eval_strategy_exit_metadata(args)?;

        let id = match self.eval_expr(id_expr)? {
            PineValue::String(value) => value,
            _ => return Ok(PineValue::Void),
        };
        let from_entry = match from_entry_expr {
            Some(expr) => match self.eval_expr(expr)? {
                PineValue::String(value) => value,
                _ => return Ok(PineValue::Void),
            },
            None => String::new(),
        };
        let qty = if let Some(qty_expr) = qty_expr {
            Some(self.eval_expr(qty_expr)?.as_f64().unwrap_or(f64::NAN))
        } else {
            None
        };
        let qty_percent = if let Some(qty_percent_expr) = qty_percent_expr {
            Some(
                self.eval_expr(qty_percent_expr)?
                    .as_f64()
                    .unwrap_or(f64::NAN),
            )
        } else {
            None
        };
        let quantity = match (qty, qty_percent) {
            (Some(qty), Some(_)) => StrategyExitQuantityArg::Fixed(qty),
            (Some(qty), None) => StrategyExitQuantityArg::Fixed(qty),
            (None, Some(qty_percent)) => StrategyExitQuantityArg::Percent(qty_percent),
            (None, None) => StrategyExitQuantityArg::Full,
        };
        let has_downside = stop_expr.is_some() || loss_expr.is_some();
        let has_upside = limit_expr.is_some() || profit_expr.is_some();
        let has_fixed_exit = has_downside || has_upside;
        let has_trailing_activation = trail_price_expr.is_some() || trail_points_expr.is_some();
        let has_trailing = has_trailing_activation || trail_offset_expr.is_some();
        let has_single_trailing_activation =
            trail_price_expr.is_some() != trail_points_expr.is_some();
        let is_trailing_only =
            !has_fixed_exit && has_single_trailing_activation && trail_offset_expr.is_some();
        let is_stop_profit_bracket = stop_expr.is_some()
            && profit_expr.is_some()
            && loss_expr.is_none()
            && limit_expr.is_none();
        let is_loss_limit_bracket = loss_expr.is_some()
            && limit_expr.is_some()
            && stop_expr.is_none()
            && profit_expr.is_none();
        let is_loss_profit_bracket = loss_expr.is_some()
            && profit_expr.is_some()
            && stop_expr.is_none()
            && limit_expr.is_none();
        let is_omitted_absolute_single = (stop_expr.is_some() != limit_expr.is_some())
            && profit_expr.is_none()
            && loss_expr.is_none()
            && !has_trailing;
        let is_omitted_absolute_bracket = stop_expr.is_some()
            && limit_expr.is_some()
            && profit_expr.is_none()
            && loss_expr.is_none()
            && !has_trailing
            && matches!(quantity, StrategyExitQuantityArg::Full);
        let is_omitted_relative_single = (profit_expr.is_some() != loss_expr.is_some())
            && stop_expr.is_none()
            && limit_expr.is_none()
            && !has_trailing
            && matches!(quantity, StrategyExitQuantityArg::Full);
        let is_omitted_loss_profit_bracket = is_loss_profit_bracket
            && !has_trailing
            && matches!(quantity, StrategyExitQuantityArg::Full);
        let is_omitted_stop_profit_bracket = is_stop_profit_bracket
            && !has_trailing
            && matches!(quantity, StrategyExitQuantityArg::Full);
        let is_omitted_loss_limit_bracket = is_loss_limit_bracket
            && !has_trailing
            && matches!(quantity, StrategyExitQuantityArg::Full);
        let is_omitted_trail_price = is_trailing_only
            && trail_price_expr.is_some()
            && trail_points_expr.is_none()
            && matches!(quantity, StrategyExitQuantityArg::Full);
        let is_omitted_trail_points = is_trailing_only
            && trail_points_expr.is_some()
            && trail_price_expr.is_none()
            && matches!(quantity, StrategyExitQuantityArg::Full);
        if from_entry.is_empty()
            && !(is_omitted_absolute_single
                || is_omitted_absolute_bracket
                || is_omitted_relative_single
                || is_omitted_loss_profit_bracket
                || is_omitted_stop_profit_bracket
                || is_omitted_loss_limit_bracket
                || is_omitted_trail_price
                || is_omitted_trail_points)
        {
            return Ok(PineValue::Void);
        }
        let has_unsupported_entry_relative_active_entry_exit = (trail_points_expr.is_some()
            && !is_trailing_only)
            || ((profit_expr.is_some() || loss_expr.is_some())
                && has_downside
                && has_upside
                && !is_stop_profit_bracket
                && !is_loss_limit_bracket
                && !is_loss_profit_bracket);
        if has_unsupported_entry_relative_active_entry_exit
            && self
                .strategy_broker
                .reject_entry_relative_exit_for_pending_entry(&from_entry)
        {
            return Ok(PineValue::Void);
        }

        if has_trailing {
            if !is_trailing_only {
                return Ok(PineValue::Void);
            }

            let mintick = pine_builtins::named_float_constant("syminfo.mintick").unwrap_or(0.01);
            if let Some(trail_price_expr) = trail_price_expr {
                let activation_price = self
                    .eval_expr(trail_price_expr)?
                    .as_f64()
                    .unwrap_or(f64::NAN);
                let trail_offset_expr =
                    trail_offset_expr.expect("checked trailing offset presence");
                let trail_offset_ticks = self
                    .eval_expr(trail_offset_expr)?
                    .as_f64()
                    .unwrap_or(f64::NAN);
                self.place_exit_trail_price_quantity(
                    id,
                    from_entry,
                    TrailPriceExitSpec {
                        activation_price,
                        offset_ticks: trail_offset_ticks,
                        mintick,
                    },
                    quantity,
                    self.bars,
                    metadata.clone(),
                );
                return Ok(PineValue::Void);
            }

            if let Some(trail_points_expr) = trail_points_expr {
                let activation_ticks = self
                    .eval_expr(trail_points_expr)?
                    .as_f64()
                    .unwrap_or(f64::NAN);
                let trail_offset_expr =
                    trail_offset_expr.expect("checked trailing offset presence");
                let trail_offset_ticks = self
                    .eval_expr(trail_offset_expr)?
                    .as_f64()
                    .unwrap_or(f64::NAN);
                if from_entry.is_empty() {
                    self.strategy_broker
                        .with_next_exit_metadata(metadata.clone(), |broker| {
                            broker.place_all_entry_exit_trail_points(
                                id,
                                activation_ticks,
                                trail_offset_ticks,
                                mintick,
                                self.bars,
                            )
                        });
                    return Ok(PineValue::Void);
                }
                self.place_exit_trail_points_quantity(
                    id,
                    from_entry,
                    TrailPointsExitSpec {
                        activation_ticks,
                        offset_ticks: trail_offset_ticks,
                        mintick,
                    },
                    quantity,
                    self.bars,
                    metadata.clone(),
                );
                return Ok(PineValue::Void);
            }

            return Ok(PineValue::Void);
        }

        if has_downside && has_upside {
            if is_stop_profit_bracket {
                let stop_price = self
                    .eval_expr(stop_expr.expect("checked stop presence"))?
                    .as_f64()
                    .unwrap_or(f64::NAN);
                let profit_ticks = self
                    .eval_expr(profit_expr.expect("checked profit presence"))?
                    .as_f64()
                    .unwrap_or(f64::NAN);
                let mintick =
                    pine_builtins::named_float_constant("syminfo.mintick").unwrap_or(0.01);
                if from_entry.is_empty() {
                    self.strategy_broker
                        .with_next_exit_metadata(metadata.clone(), |broker| {
                            broker.place_all_entry_exit_stop_profit_bracket(
                                id,
                                StopProfitBracketSpec {
                                    stop_price,
                                    profit_ticks,
                                    mintick,
                                },
                                self.bars,
                            )
                        });
                    return Ok(PineValue::Void);
                }
                self.place_exit_stop_profit_bracket_quantity(
                    id,
                    from_entry,
                    StopProfitBracketSpec {
                        stop_price,
                        profit_ticks,
                        mintick,
                    },
                    quantity,
                    self.bars,
                    metadata.clone(),
                );
                return Ok(PineValue::Void);
            }
            if is_loss_limit_bracket {
                let loss_ticks = self
                    .eval_expr(loss_expr.expect("checked loss presence"))?
                    .as_f64()
                    .unwrap_or(f64::NAN);
                let limit_price = self
                    .eval_expr(limit_expr.expect("checked limit presence"))?
                    .as_f64()
                    .unwrap_or(f64::NAN);
                let mintick =
                    pine_builtins::named_float_constant("syminfo.mintick").unwrap_or(0.01);
                if from_entry.is_empty() {
                    self.strategy_broker
                        .with_next_exit_metadata(metadata.clone(), |broker| {
                            broker.place_all_entry_exit_loss_limit_bracket(
                                id,
                                LossLimitBracketSpec {
                                    loss_ticks,
                                    limit_price,
                                    mintick,
                                },
                                self.bars,
                            )
                        });
                    return Ok(PineValue::Void);
                }
                self.place_exit_loss_limit_bracket_quantity(
                    id,
                    from_entry,
                    LossLimitBracketSpec {
                        loss_ticks,
                        limit_price,
                        mintick,
                    },
                    quantity,
                    self.bars,
                    metadata.clone(),
                );
                return Ok(PineValue::Void);
            }
            if is_loss_profit_bracket {
                let loss_ticks = self
                    .eval_expr(loss_expr.expect("checked loss presence"))?
                    .as_f64()
                    .unwrap_or(f64::NAN);
                let profit_ticks = self
                    .eval_expr(profit_expr.expect("checked profit presence"))?
                    .as_f64()
                    .unwrap_or(f64::NAN);
                let mintick =
                    pine_builtins::named_float_constant("syminfo.mintick").unwrap_or(0.01);
                if from_entry.is_empty() {
                    self.strategy_broker
                        .with_next_exit_metadata(metadata.clone(), |broker| {
                            broker.place_all_entry_exit_loss_profit_bracket(
                                id,
                                LossProfitBracketSpec {
                                    loss_ticks,
                                    profit_ticks,
                                    mintick,
                                },
                                self.bars,
                            )
                        });
                    return Ok(PineValue::Void);
                }
                self.place_exit_loss_profit_bracket_quantity(
                    id,
                    from_entry,
                    LossProfitBracketSpec {
                        loss_ticks,
                        profit_ticks,
                        mintick,
                    },
                    quantity,
                    self.bars,
                    metadata.clone(),
                );
                return Ok(PineValue::Void);
            }

            let downside_price = if let Some(stop_expr) = stop_expr {
                let stop_price = self.eval_expr(stop_expr)?.as_f64().unwrap_or(f64::NAN);
                if !stop_price.is_finite() {
                    self.place_exit_bracket_quantity(RuntimeExitBracketPlacement {
                        id,
                        from_entry,
                        downside_price: stop_price,
                        upside_price: f64::NAN,
                        quantity,
                        bar_index: self.bars,
                        metadata: metadata.clone(),
                    });
                    return Ok(PineValue::Void);
                }
                stop_price
            } else if let Some(loss_expr) = loss_expr {
                let loss_ticks = self.eval_expr(loss_expr)?.as_f64().unwrap_or(f64::NAN);
                let mintick =
                    pine_builtins::named_float_constant("syminfo.mintick").unwrap_or(0.01);
                let Some(loss_price) = self
                    .strategy_broker
                    .exit_loss_price_from_ticks(loss_ticks, mintick)
                else {
                    return Ok(PineValue::Void);
                };
                loss_price
            } else {
                return Ok(PineValue::Void);
            };

            let upside_price = if let Some(limit_expr) = limit_expr {
                let limit_price = self.eval_expr(limit_expr)?.as_f64().unwrap_or(f64::NAN);
                if !limit_price.is_finite() {
                    self.place_exit_bracket_quantity(RuntimeExitBracketPlacement {
                        id,
                        from_entry,
                        downside_price,
                        upside_price: limit_price,
                        quantity,
                        bar_index: self.bars,
                        metadata: metadata.clone(),
                    });
                    return Ok(PineValue::Void);
                }
                limit_price
            } else if let Some(profit_expr) = profit_expr {
                let profit_ticks = self.eval_expr(profit_expr)?.as_f64().unwrap_or(f64::NAN);
                let mintick =
                    pine_builtins::named_float_constant("syminfo.mintick").unwrap_or(0.01);
                let Some(profit_price) = self
                    .strategy_broker
                    .exit_profit_price_from_ticks(profit_ticks, mintick)
                else {
                    return Ok(PineValue::Void);
                };
                profit_price
            } else {
                return Ok(PineValue::Void);
            };

            self.place_exit_bracket_quantity(RuntimeExitBracketPlacement {
                id,
                from_entry,
                downside_price,
                upside_price,
                quantity,
                bar_index: self.bars,
                metadata: metadata.clone(),
            });
        } else if let Some(stop_expr) = stop_expr {
            let stop_price = self.eval_expr(stop_expr)?.as_f64().unwrap_or(f64::NAN);
            self.place_exit_stop_quantity(
                id,
                from_entry,
                stop_price,
                quantity,
                self.bars,
                metadata.clone(),
            );
        } else if let Some(limit_expr) = limit_expr {
            let limit_price = self.eval_expr(limit_expr)?.as_f64().unwrap_or(f64::NAN);
            self.place_exit_limit_quantity(
                id,
                from_entry,
                limit_price,
                quantity,
                self.bars,
                metadata.clone(),
            );
        } else if let Some(profit_expr) = profit_expr {
            let profit_ticks = self.eval_expr(profit_expr)?.as_f64().unwrap_or(f64::NAN);
            let mintick = pine_builtins::named_float_constant("syminfo.mintick").unwrap_or(0.01);
            if from_entry.is_empty() {
                self.strategy_broker
                    .with_next_exit_metadata(metadata.clone(), |broker| {
                        broker.place_all_entry_exit_profit_ticks(
                            id,
                            profit_ticks,
                            mintick,
                            self.bars,
                        )
                    });
                return Ok(PineValue::Void);
            }
            self.place_exit_profit_ticks_quantity(RuntimeExitTicksPlacement {
                id,
                from_entry,
                ticks: profit_ticks,
                mintick,
                quantity,
                bar_index: self.bars,
                metadata: metadata.clone(),
            });
        } else if let Some(loss_expr) = loss_expr {
            let loss_ticks = self.eval_expr(loss_expr)?.as_f64().unwrap_or(f64::NAN);
            let mintick = pine_builtins::named_float_constant("syminfo.mintick").unwrap_or(0.01);
            if from_entry.is_empty() {
                self.strategy_broker
                    .with_next_exit_metadata(metadata.clone(), |broker| {
                        broker.place_all_entry_exit_loss_ticks(id, loss_ticks, mintick, self.bars)
                    });
                return Ok(PineValue::Void);
            }
            self.place_exit_loss_ticks_quantity(RuntimeExitTicksPlacement {
                id,
                from_entry,
                ticks: loss_ticks,
                mintick,
                quantity,
                bar_index: self.bars,
                metadata: metadata.clone(),
            });
        }
        Ok(PineValue::Void)
    }
}
