use pine_ir::{CallSiteId, HirCallArg};

use crate::*;

pub(crate) fn eval_static_builtin_value(name: &str) -> PineValue {
    if let Some(color) = pine_builtins::named_color(name) {
        return PineValue::Color(u64::from(color));
    }
    if let Some(value) = pine_builtins::named_float_constant(name) {
        return PineValue::Float(value);
    }
    if let Some(value) = pine_builtins::named_int_constant(name) {
        return PineValue::Int(value);
    }
    pine_builtins::named_string_constant(name)
        .map(|constant| PineValue::String(constant.to_owned()))
        .unwrap_or(PineValue::Void)
}

fn chart_symbol_part(symbol: &str, prefix: bool) -> String {
    match (symbol.split_once(':'), prefix) {
        (Some((prefix, _)), true) => prefix.to_owned(),
        (Some((_, ticker)), false) => ticker.to_owned(),
        (None, true) => String::new(),
        (None, false) => symbol.to_owned(),
    }
}

fn chart_timeframe_unit(timeframe: &str) -> Option<char> {
    timeframe.chars().last().filter(char::is_ascii_alphabetic)
}

fn chart_timeframe_multiplier(timeframe: &str) -> i64 {
    let number = if chart_timeframe_unit(timeframe).is_some() {
        &timeframe[..timeframe.len().saturating_sub(1)]
    } else {
        timeframe
    };
    if number.is_empty() {
        1
    } else {
        number.parse().unwrap_or(1)
    }
}

impl<'a> HistoricalRuntime<'a> {
    pub(crate) fn eval_variable_call(
        &mut self,
        callee: &str,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Option<Result<PineValue, RuntimeError>> {
        Some(match callee {
            "indicator" | "strategy" | "max_bars_back" => Ok(PineValue::Void),
            "input" | "input.int" | "input.float" | "input.bool" | "input.color"
            | "input.string" | "input.price" | "input.time" | "input.symbol"
            | "input.timeframe" | "input.session" | "input.text_area" | "input.source" => {
                self.eval_input(call_site_id, args)
            }
            "na" => self.eval_na(args),
            "nz" => self.eval_nz(args),
            "fixnan" => self.eval_fixnan(call_site_id, args),
            _ => return None,
        })
    }

    pub(crate) fn eval_input(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        if let Some(value) = self.input_overrides.get(call_site_id) {
            return Ok(value.clone());
        }
        self.eval_expr(&args[0].value)
    }

    pub(crate) fn eval_na(&mut self, args: &[HirCallArg]) -> Result<PineValue, RuntimeError> {
        let value = self.eval_expr(&args[0].value)?;
        Ok(PineValue::Bool(value.is_na()))
    }

    pub(crate) fn eval_nz(&mut self, args: &[HirCallArg]) -> Result<PineValue, RuntimeError> {
        let value = self.eval_expr(&args[0].value)?;
        if value.is_na() {
            if let Some(replacement) = args.get(1) {
                self.eval_expr(&replacement.value)
            } else {
                Ok(PineValue::Int(0))
            }
        } else {
            Ok(value)
        }
    }

    pub(crate) fn eval_builtin_value(&mut self, name: &str) -> PineValue {
        if name == "barstate.isfirst" {
            return PineValue::Bool(self.bars == 0);
        }
        if name == "barstate.islast" {
            return PineValue::Bool(self.is_latest_known_bar());
        }
        if name == "barstate.islastconfirmedhistory" {
            return PineValue::Bool(self.is_last_confirmed_history_bar());
        }
        if name == "barstate.isnew" {
            return PineValue::Bool(self.current_bar_is_new);
        }
        if name == "barstate.isconfirmed" {
            return PineValue::Bool(matches!(
                self.current_bar_update_kind,
                BarUpdateKind::Historical | BarUpdateKind::Confirmed
            ));
        }
        if name == "barstate.ishistory" {
            return PineValue::Bool(matches!(
                self.current_bar_update_kind,
                BarUpdateKind::Historical
            ));
        }
        if name == "barstate.isrealtime" {
            return PineValue::Bool(matches!(
                self.current_bar_update_kind,
                BarUpdateKind::Forming | BarUpdateKind::Confirmed
            ));
        }
        if name == "session.ismarket" {
            return PineValue::Bool(true);
        }
        if name == "session.ispremarket" || name == "session.ispostmarket" {
            return PineValue::Bool(false);
        }
        if matches!(name, "session.isfirstbar" | "session.isfirstbar_regular") {
            return PineValue::Bool(self.bars == 0);
        }
        if matches!(name, "session.islastbar" | "session.islastbar_regular") {
            return PineValue::Bool(self.is_latest_known_bar());
        }
        if name == "last_bar_index" {
            return self
                .last_bar_index
                .map_or(PineValue::Na, |index| PineValue::Int(index as i64));
        }
        if name == "last_bar_time" {
            return self.last_bar_time.map_or(PineValue::Na, PineValue::Int);
        }
        if matches!(name, "syminfo.tickerid" | "syminfo.main_tickerid") {
            return PineValue::String(self.request_environment.chart().symbol().to_owned());
        }
        if name == "syminfo.ticker" {
            return PineValue::String(chart_symbol_part(
                self.request_environment.chart().symbol(),
                false,
            ));
        }
        if name == "syminfo.prefix" {
            return PineValue::String(chart_symbol_part(
                self.request_environment.chart().symbol(),
                true,
            ));
        }
        if matches!(name, "timeframe.period" | "timeframe.main_period") {
            return PineValue::String(
                self.request_environment
                    .chart()
                    .timeframe()
                    .value()
                    .to_owned(),
            );
        }
        let chart_timeframe = self.request_environment.chart().timeframe().value();
        let chart_timeframe_unit = chart_timeframe_unit(chart_timeframe);
        if name == "timeframe.isticks" {
            return PineValue::Bool(false);
        }
        if name == "timeframe.isseconds" {
            return PineValue::Bool(chart_timeframe_unit == Some('S'));
        }
        if name == "timeframe.isminutes" {
            return PineValue::Bool(chart_timeframe_unit.is_none());
        }
        if name == "timeframe.isintraday" {
            return PineValue::Bool(matches!(chart_timeframe_unit, None | Some('S')));
        }
        if name == "timeframe.isdaily" {
            return PineValue::Bool(chart_timeframe_unit == Some('D'));
        }
        if name == "timeframe.isweekly" {
            return PineValue::Bool(chart_timeframe_unit == Some('W'));
        }
        if name == "timeframe.ismonthly" {
            return PineValue::Bool(chart_timeframe_unit == Some('M'));
        }
        if name == "timeframe.isdwm" {
            return PineValue::Bool(matches!(chart_timeframe_unit, Some('D' | 'W' | 'M')));
        }
        if name == "timeframe.multiplier" {
            return PineValue::Int(chart_timeframe_multiplier(chart_timeframe));
        }
        if name == "chart.left_visible_bar_time" {
            return self
                .chart_visible_left_time
                .map_or(PineValue::Na, PineValue::Int);
        }
        if name == "chart.right_visible_bar_time" {
            return self
                .chart_visible_right_time
                .map_or(PineValue::Na, PineValue::Int);
        }
        if name == "chart.bg_color" {
            return PineValue::Color(0xFFFFFF);
        }
        if name == "chart.fg_color" {
            return PineValue::Color(0x000000);
        }
        if name == "chart.is_standard" {
            return PineValue::Bool(true);
        }
        if matches!(
            name,
            "chart.is_heikinashi"
                | "chart.is_kagi"
                | "chart.is_linebreak"
                | "chart.is_pnf"
                | "chart.is_range"
                | "chart.is_renko"
        ) {
            return PineValue::Bool(false);
        }
        if name == "label.all" {
            let labels = self
                .labels
                .iter()
                .filter(|label| {
                    label
                        .snapshots
                        .last()
                        .is_some_and(|snapshot| snapshot.exists)
                })
                .map(|label| PineValue::Label(label.id))
                .collect();
            return self.new_array_from_values(ArrayElementKind::Label, labels);
        }
        if name == "line.all" {
            let lines = self
                .lines
                .iter()
                .filter(|line| {
                    line.snapshots
                        .last()
                        .is_some_and(|snapshot| snapshot.exists)
                })
                .map(|line| PineValue::Line(line.id))
                .collect();
            return self.new_array_from_values(ArrayElementKind::Line, lines);
        }
        if name == "linefill.all" {
            let line_fills = self
                .line_fills
                .iter()
                .filter(|line_fill| {
                    line_fill
                        .snapshots
                        .last()
                        .is_some_and(|snapshot| snapshot.exists)
                })
                .map(|line_fill| PineValue::LineFill(line_fill.id))
                .collect();
            return self.new_array_from_values(ArrayElementKind::LineFill, line_fills);
        }
        if name == "polyline.all" {
            let polylines = self
                .polylines
                .iter()
                .filter(|polyline| {
                    polyline
                        .snapshots
                        .last()
                        .is_some_and(|snapshot| snapshot.exists)
                })
                .map(|polyline| PineValue::Polyline(polyline.id))
                .collect();
            return self.new_array_from_values(ArrayElementKind::Polyline, polylines);
        }
        if name == "box.all" {
            let boxes = self
                .boxes
                .iter()
                .filter(|drawing_box| {
                    drawing_box
                        .snapshots
                        .last()
                        .is_some_and(|snapshot| snapshot.exists)
                })
                .map(|drawing_box| PineValue::Box(drawing_box.id))
                .collect();
            return self.new_array_from_values(ArrayElementKind::Box, boxes);
        }
        if name == "table.all" {
            let tables = self
                .tables
                .iter()
                .filter(|table| {
                    table
                        .snapshots
                        .last()
                        .is_some_and(|snapshot| snapshot.exists)
                })
                .map(|table| PineValue::Table(table.id))
                .collect();
            return self.new_array_from_values(ArrayElementKind::Table, tables);
        }
        if name == "strategy.account_currency" {
            return eval_static_builtin_value("syminfo.currency");
        }
        if name == "strategy.position_size" {
            return PineValue::Float(self.strategy_broker.position_size());
        }
        if name == "strategy.position_avg_price" {
            return self.strategy_broker.position_avg_price_value();
        }
        if name == "strategy.position_entry_name" {
            return self.strategy_broker.position_entry_name_value();
        }
        if name == "strategy.initial_capital" {
            return PineValue::Float(self.strategy_broker.initial_capital());
        }
        if name == "strategy.closedtrades" {
            return PineValue::Int(self.strategy_broker.closed_trade_count());
        }
        if name == "strategy.closedtrades.first_index" {
            return PineValue::Int(self.strategy_broker.first_closed_trade_index());
        }
        if name == "strategy.wintrades" {
            return PineValue::Int(self.strategy_broker.winning_trade_count());
        }
        if name == "strategy.losstrades" {
            return PineValue::Int(self.strategy_broker.losing_trade_count());
        }
        if name == "strategy.eventrades" {
            return PineValue::Int(self.strategy_broker.even_trade_count());
        }
        if name == "strategy.opentrades" {
            return PineValue::Int(self.strategy_broker.open_trade_count());
        }
        if name == "strategy.opentrades.capital_held" {
            return self.current_bar.map_or(PineValue::Na, |bar| {
                self.strategy_broker
                    .open_trade_capital_held(bar.close)
                    .map_or(PineValue::Na, PineValue::Float)
            });
        }
        if name == "strategy.margin_liquidation_price" {
            return self
                .strategy_broker
                .margin_liquidation_price()
                .map_or(PineValue::Na, PineValue::Float);
        }
        if name == "strategy.openprofit" {
            return self.current_bar.map_or(PineValue::Na, |bar| {
                PineValue::Float(self.strategy_broker.open_profit(bar.close))
            });
        }
        if name == "strategy.openprofit_percent" {
            return self.current_bar.map_or(PineValue::Na, |bar| {
                self.strategy_broker
                    .open_profit_percent(bar.close)
                    .map_or(PineValue::Na, PineValue::Float)
            });
        }
        if name == "strategy.netprofit" {
            return PineValue::Float(self.strategy_broker.realized_profit());
        }
        if name == "strategy.netprofit_percent" {
            return PineValue::Float(self.strategy_broker.realized_profit_percent());
        }
        if name == "strategy.grossprofit" {
            return PineValue::Float(self.strategy_broker.gross_profit());
        }
        if name == "strategy.grossprofit_percent" {
            return PineValue::Float(self.strategy_broker.gross_profit_percent());
        }
        if name == "strategy.grossloss" {
            return PineValue::Float(self.strategy_broker.gross_loss());
        }
        if name == "strategy.grossloss_percent" {
            return PineValue::Float(self.strategy_broker.gross_loss_percent());
        }
        if name == "strategy.buy_and_hold_return_percent" {
            return self.strategy_buy_and_hold_return_percent();
        }
        if name == "strategy.avg_trade" {
            return self
                .strategy_broker
                .average_trade()
                .map_or(PineValue::Na, PineValue::Float);
        }
        if name == "strategy.avg_trade_percent" {
            return self
                .strategy_broker
                .average_trade_percent()
                .map_or(PineValue::Na, PineValue::Float);
        }
        if name == "strategy.avg_winning_trade" {
            return self
                .strategy_broker
                .average_winning_trade()
                .map_or(PineValue::Na, PineValue::Float);
        }
        if name == "strategy.avg_winning_trade_percent" {
            return self
                .strategy_broker
                .average_winning_trade_percent()
                .map_or(PineValue::Na, PineValue::Float);
        }
        if name == "strategy.avg_losing_trade" {
            return self
                .strategy_broker
                .average_losing_trade()
                .map_or(PineValue::Na, PineValue::Float);
        }
        if name == "strategy.avg_losing_trade_percent" {
            return self
                .strategy_broker
                .average_losing_trade_percent()
                .map_or(PineValue::Na, PineValue::Float);
        }
        if name == "strategy.max_runup" {
            return PineValue::Float(self.strategy_broker.max_runup());
        }
        if name == "strategy.max_runup_percent" {
            return PineValue::Float(self.strategy_broker.max_runup_percent());
        }
        if name == "strategy.max_drawdown" {
            return PineValue::Float(self.strategy_broker.max_drawdown());
        }
        if name == "strategy.max_drawdown_percent" {
            return PineValue::Float(self.strategy_broker.max_drawdown_percent());
        }
        if name == "strategy.max_contracts_held_all" {
            return PineValue::Float(self.strategy_broker.max_contracts_held_all());
        }
        if name == "strategy.max_contracts_held_long" {
            return PineValue::Float(self.strategy_broker.max_contracts_held_long());
        }
        if name == "strategy.max_contracts_held_short" {
            return PineValue::Float(self.strategy_broker.max_contracts_held_short());
        }
        if name == "strategy.equity" {
            return self.current_bar.map_or(PineValue::Na, |bar| {
                PineValue::Float(self.strategy_broker.equity_value(bar.close))
            });
        }
        if name == "ta.accdist" {
            return self.accdist_current.clone();
        }
        if name == "ta.iii" {
            return self.iii_current.clone();
        }
        if name == "ta.nvi" {
            return self.nvi_current.clone();
        }
        if name == "ta.obv" {
            return self.obv_current.clone();
        }
        if name == "ta.pvi" {
            return self.pvi_current.clone();
        }
        if name == "ta.pvt" {
            return self.pvt_current.clone();
        }
        if name == "ta.tr" {
            return self.true_range(false);
        }
        if name == "ta.vwap" {
            return self.vwap_current.clone();
        }
        if name == "ta.wad" {
            return self.wad_current.clone();
        }
        if name == "ta.wvad" {
            return self.wvad_current.clone();
        }
        eval_static_builtin_value(name)
    }

    fn is_latest_known_bar(&self) -> bool {
        match self.current_bar_update_kind {
            BarUpdateKind::Historical => self
                .historical_end
                .is_none_or(|historical_end| self.bars + 1 == historical_end),
            BarUpdateKind::Forming | BarUpdateKind::Confirmed => true,
        }
    }

    fn is_last_confirmed_history_bar(&self) -> bool {
        match self.current_bar_update_kind {
            BarUpdateKind::Historical => self.is_latest_known_bar(),
            BarUpdateKind::Forming | BarUpdateKind::Confirmed => false,
        }
    }

    fn strategy_buy_and_hold_return_percent(&self) -> PineValue {
        let Some(current_bar) = self.current_bar else {
            return PineValue::Na;
        };
        let Some(first_close) = self.first_bar_close else {
            return PineValue::Na;
        };
        if first_close == 0.0 || !first_close.is_finite() || !current_bar.close.is_finite() {
            return PineValue::Na;
        }
        PineValue::Float((current_bar.close - first_close) / first_close * 100.0)
    }
}

impl<'a> HistoricalRuntime<'a> {
    pub(crate) fn eval_fixnan(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let value = self.eval_expr(&args[0].value)?;
        if value.is_na() {
            Ok(self
                .call_state
                .get(&call_site_id)
                .cloned()
                .unwrap_or(PineValue::Na))
        } else {
            self.call_state.insert(call_site_id, value.clone());
            Ok(value)
        }
    }
}
