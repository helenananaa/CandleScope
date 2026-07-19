use crate::prelude::*;

const STRATEGY_FIXED_DEFAULT_QTY_TYPE: &str = "strategy.fixed";
const STRATEGY_PERCENT_OF_EQUITY_DEFAULT_QTY_TYPE: &str = "strategy.percent_of_equity";
const STRATEGY_CASH_PER_CONTRACT_COMMISSION_TYPE: &str = "strategy.commission.cash_per_contract";
const STRATEGY_CASH_PER_ORDER_COMMISSION_TYPE: &str = "strategy.commission.cash_per_order";
const STRATEGY_PERCENT_COMMISSION_TYPE: &str = "strategy.commission.percent";
const STRATEGY_NONE_ACCOUNT_CURRENCY: &str = "NONE";

impl Analyzer {
    pub(crate) fn validate_strategy_declaration_args(&mut self, args: &[CallArg]) {
        let mut default_qty_type_arg = None;
        let mut default_qty_value_arg = None;
        let mut default_qty_constructor: Option<fn(f64) -> pine_ir::StrategyDefaultQuantity> = None;
        let mut default_qty_value = None;
        let mut commission_type_arg = None;
        let mut commission_constructor: Option<fn(f64) -> pine_ir::StrategyCommission> = None;
        let mut commission_value_arg = None;
        let mut commission_value = None;

        for (index, arg) in args.iter().enumerate() {
            let Some(name) = arg.name.as_deref().or_else(|| {
                [
                    "title",
                    "shorttitle",
                    "overlay",
                    "max_bars_back",
                    "initial_capital",
                    "default_qty_type",
                    "default_qty_value",
                    "commission_type",
                    "commission_value",
                    "slippage",
                    "backtest_fill_limits_assumption",
                    "margin_long",
                    "margin_short",
                    "pyramiding",
                    "close_entries_rule",
                    "max_labels_count",
                    "max_boxes_count",
                    "max_lines_count",
                    "max_polylines_count",
                    "currency",
                ]
                .get(index)
                .copied()
            }) else {
                continue;
            };

            match name {
                "max_bars_back" => {
                    self.validate_max_bars_back_bound_value("strategy", "max_bars_back", arg);
                }
                "initial_capital" => {
                    let Some(initial_capital) = self.known_const_numeric_value(&arg.value) else {
                        continue;
                    };
                    if !initial_capital.is_finite() || initial_capital <= 0.0 {
                        self.diagnostics.push(Diagnostic::error(
                            "E_CALL_ARG_VALUE",
                            "`strategy` argument `initial_capital` must be positive",
                            arg.span,
                        ));
                        continue;
                    }
                    self.strategy_settings.initial_capital = initial_capital;
                }
                "currency" => {
                    let Some(currency) = self.known_const_string_value(&arg.value) else {
                        continue;
                    };
                    if currency != STRATEGY_NONE_ACCOUNT_CURRENCY {
                        self.diagnostics.push(Diagnostic::error(
                            "E_CALL_ARG_VALUE",
                            "`strategy` argument `currency` only supports currency.NONE in the current no-conversion subset",
                            arg.span,
                        ));
                    }
                }
                "default_qty_type" => {
                    default_qty_type_arg = Some(arg);
                    let Some(default_qty_type) = self.known_const_string_value(&arg.value) else {
                        continue;
                    };
                    match default_qty_type.as_str() {
                        STRATEGY_FIXED_DEFAULT_QTY_TYPE => {
                            default_qty_constructor = Some(
                                pine_ir::StrategyDefaultQuantity::Fixed
                                    as fn(f64) -> pine_ir::StrategyDefaultQuantity,
                            );
                        }
                        "strategy.cash" => {
                            default_qty_constructor = Some(
                                pine_ir::StrategyDefaultQuantity::Cash
                                    as fn(f64) -> pine_ir::StrategyDefaultQuantity,
                            );
                        }
                        STRATEGY_PERCENT_OF_EQUITY_DEFAULT_QTY_TYPE => {
                            default_qty_constructor = Some(
                                pine_ir::StrategyDefaultQuantity::PercentOfEquity
                                    as fn(f64) -> pine_ir::StrategyDefaultQuantity,
                            );
                        }
                        _ => {
                            self.diagnostics.push(Diagnostic::error(
                                "E_CALL_ARG_VALUE",
                                "`strategy` argument `default_qty_type` only supports strategy.fixed, strategy.cash, or strategy.percent_of_equity",
                                arg.span,
                            ));
                            continue;
                        }
                    }
                }
                "default_qty_value" => {
                    default_qty_value_arg = Some(arg);
                    let Some(qty) = self.known_const_numeric_value(&arg.value) else {
                        continue;
                    };
                    if !qty.is_finite() || qty <= 0.0 {
                        self.diagnostics.push(Diagnostic::error(
                            "E_CALL_ARG_VALUE",
                            "`strategy` argument `default_qty_value` must be positive",
                            arg.span,
                        ));
                        continue;
                    }
                    default_qty_value = Some(qty);
                }
                "commission_type" => {
                    commission_type_arg = Some(arg);
                    let Some(commission_type) = self.known_const_string_value(&arg.value) else {
                        continue;
                    };
                    match commission_type.as_str() {
                        STRATEGY_CASH_PER_CONTRACT_COMMISSION_TYPE => {
                            commission_constructor = Some(
                                pine_ir::StrategyCommission::CashPerContract
                                    as fn(f64) -> pine_ir::StrategyCommission,
                            );
                        }
                        STRATEGY_CASH_PER_ORDER_COMMISSION_TYPE => {
                            commission_constructor = Some(
                                pine_ir::StrategyCommission::CashPerOrder
                                    as fn(f64) -> pine_ir::StrategyCommission,
                            );
                        }
                        STRATEGY_PERCENT_COMMISSION_TYPE => {
                            commission_constructor = Some(
                                pine_ir::StrategyCommission::Percent
                                    as fn(f64) -> pine_ir::StrategyCommission,
                            );
                        }
                        _ => {
                            self.diagnostics.push(Diagnostic::error(
                                "E_CALL_ARG_VALUE",
                                "`strategy` argument `commission_type` only supports strategy.commission.cash_per_contract, strategy.commission.cash_per_order, or strategy.commission.percent",
                                arg.span,
                            ));
                            continue;
                        }
                    }
                }
                "commission_value" => {
                    commission_value_arg = Some(arg);
                    let Some(value) = self.known_const_numeric_value(&arg.value) else {
                        continue;
                    };
                    if !value.is_finite() || value < 0.0 {
                        self.diagnostics.push(Diagnostic::error(
                            "E_CALL_ARG_VALUE",
                            "`strategy` argument `commission_value` must be non-negative",
                            arg.span,
                        ));
                        continue;
                    }
                    commission_value = Some(value);
                }
                "slippage" => {
                    let Some(value) = self.known_const_numeric_value(&arg.value) else {
                        continue;
                    };
                    if !value.is_finite() || value < 0.0 || value.fract() != 0.0 {
                        self.diagnostics.push(Diagnostic::error(
                            "E_CALL_ARG_VALUE",
                            "`strategy` argument `slippage` must be a non-negative integer",
                            arg.span,
                        ));
                        continue;
                    }
                    self.strategy_settings.slippage_ticks = value;
                }
                "backtest_fill_limits_assumption" => {
                    let Some(value) = self.known_const_numeric_value(&arg.value) else {
                        continue;
                    };
                    if !value.is_finite() || value < 0.0 || value.fract() != 0.0 {
                        self.diagnostics.push(Diagnostic::error(
                            "E_CALL_ARG_VALUE",
                            "`strategy` argument `backtest_fill_limits_assumption` must be a non-negative integer",
                            arg.span,
                        ));
                        continue;
                    }
                    self.strategy_settings.backtest_fill_limit_ticks = value;
                }
                "margin_long" | "margin_short" => {
                    let Some(value) = self.known_const_numeric_value(&arg.value) else {
                        continue;
                    };
                    if !value.is_finite() || value < 0.0 {
                        self.diagnostics.push(Diagnostic::error(
                            "E_CALL_ARG_VALUE",
                            format!("`strategy` argument `{name}` must be non-negative"),
                            arg.span,
                        ));
                        continue;
                    }
                    let setting = pine_ir::StrategyMarginSetting::explicit(value);
                    if name == "margin_long" {
                        self.strategy_settings.margin_long = setting;
                    } else {
                        self.strategy_settings.margin_short = setting;
                    }
                }
                "pyramiding" => {
                    let Some(value) = self.known_const_numeric_value(&arg.value) else {
                        continue;
                    };
                    if !value.is_finite()
                        || value <= 0.0
                        || value.fract() != 0.0
                        || value > usize::MAX as f64
                    {
                        self.diagnostics.push(Diagnostic::error(
                            "E_CALL_ARG_VALUE",
                            "`strategy` argument `pyramiding` must be a positive integer",
                            arg.span,
                        ));
                        continue;
                    }
                    self.strategy_settings.pyramiding_limit = value as usize;
                }
                "close_entries_rule" => {
                    let Some(value) = self.known_const_string_value(&arg.value) else {
                        continue;
                    };
                    self.strategy_settings.close_entries_rule = match value.as_str() {
                        "FIFO" => pine_ir::StrategyCloseEntriesRule::Fifo,
                        "ANY" => pine_ir::StrategyCloseEntriesRule::Any,
                        _ => {
                            self.diagnostics.push(Diagnostic::error(
                                "E_CALL_ARG_VALUE",
                                "`strategy` argument `close_entries_rule` only supports \"FIFO\" or \"ANY\"",
                                arg.span,
                            ));
                            continue;
                        }
                    };
                }
                "max_labels_count" => {
                    self.validate_named_drawing_count_arg("strategy", name, 500, arg);
                }
                "max_boxes_count" => {
                    self.validate_named_drawing_count_arg("strategy", name, 500, arg);
                }
                "max_lines_count" => {
                    self.validate_named_drawing_count_arg("strategy", name, 500, arg);
                }
                "max_polylines_count" => {
                    self.validate_named_drawing_count_arg("strategy", name, 100, arg);
                }
                _ => {}
            }
        }

        if default_qty_type_arg.is_some() {
            if let (Some(default_qty_constructor), Some(qty)) = (
                default_qty_constructor,
                if default_qty_value_arg.is_some() {
                    default_qty_value
                } else {
                    Some(1.0)
                },
            ) {
                self.strategy_settings.default_qty = Some(default_qty_constructor(qty));
            }
        } else if let Some(qty) = default_qty_value {
            self.strategy_settings.default_qty = Some(pine_ir::StrategyDefaultQuantity::Fixed(qty));
        }
        if commission_value_arg.is_some() && commission_type_arg.is_none() {
            if let Some(arg) = commission_value_arg {
                self.diagnostics.push(Diagnostic::error(
                    "E_CALL_ARG_VALUE",
                    "`strategy` argument `commission_value` requires a supported commission_type",
                    arg.span,
                ));
            }
            return;
        }
        if let Some(commission_constructor) = commission_constructor {
            self.strategy_settings.commission =
                Some(commission_constructor(commission_value.unwrap_or(0.0)));
        }
    }
}
