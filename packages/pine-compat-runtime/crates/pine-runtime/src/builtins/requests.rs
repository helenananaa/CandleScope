use pine_ir::{CallSiteId, HirCallArg, HirExpr};

use crate::builtins::args::call_arg_expr;
use crate::builtins::time::calendar_timeframe_close;
use crate::*;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum RequestGaps {
    Off,
    On,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum RequestLookahead {
    Off,
    On,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct RequestMergePolicy {
    gaps: RequestGaps,
    lookahead: RequestLookahead,
}

impl RequestMergePolicy {
    const MODERN: Self = Self {
        gaps: RequestGaps::Off,
        lookahead: RequestLookahead::Off,
    };
}

impl<'a> HistoricalRuntime<'a> {
    pub(crate) fn eval_request_call(
        &mut self,
        callee: &str,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Option<Result<PineValue, RuntimeError>> {
        let (merge, legacy) = match callee {
            "request.security" => (RequestMergePolicy::MODERN, None),
            "$legacy.security.gaps_off.lookahead_off" => (
                RequestMergePolicy {
                    gaps: RequestGaps::Off,
                    lookahead: RequestLookahead::Off,
                },
                legacy_source_span(args),
            ),
            "$legacy.security.gaps_on.lookahead_off" => (
                RequestMergePolicy {
                    gaps: RequestGaps::On,
                    lookahead: RequestLookahead::Off,
                },
                legacy_source_span(args),
            ),
            "$legacy.security.gaps_off.lookahead_on" => (
                RequestMergePolicy {
                    gaps: RequestGaps::Off,
                    lookahead: RequestLookahead::On,
                },
                legacy_source_span(args),
            ),
            "$legacy.security.gaps_on.lookahead_on" => (
                RequestMergePolicy {
                    gaps: RequestGaps::On,
                    lookahead: RequestLookahead::On,
                },
                legacy_source_span(args),
            ),
            _ => return None,
        };
        if merge.lookahead == RequestLookahead::On {
            self.legacy_security_repaint_warnings
                .entry(call_site_id)
                .or_insert(legacy.unwrap_or((0, 0)));
        }
        let result = self.eval_request_security(call_site_id, args, merge);
        Some(match legacy {
            Some((start, end)) => result.map_err(|error| RuntimeError {
                message: format!(
                    "legacy security at source span {start}..{end}: {}",
                    error.message
                ),
            }),
            None => result,
        })
    }

    fn eval_request_security(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
        merge: RequestMergePolicy,
    ) -> Result<PineValue, RuntimeError> {
        if !(3..=5).contains(&args.len()) {
            return Err(RuntimeError {
                message: format!(
                    "request.security expects 3 to 5 argument(s), got {}",
                    args.len()
                ),
            });
        }

        let Some(symbol_expr) = call_arg_expr(args, 0, "symbol") else {
            return Err(RuntimeError {
                message: "request.security missing symbol argument".to_owned(),
            });
        };
        let PineValue::String(symbol) = self.eval_expr(symbol_expr)? else {
            return Err(RuntimeError {
                message: "request.security symbol must evaluate to string".to_owned(),
            });
        };
        let Some(timeframe_expr) = call_arg_expr(args, 1, "timeframe") else {
            return Err(RuntimeError {
                message: "request.security missing timeframe argument".to_owned(),
            });
        };
        let PineValue::String(timeframe) = self.eval_expr(timeframe_expr)? else {
            return Err(RuntimeError {
                message: "request.security timeframe must evaluate to string".to_owned(),
            });
        };
        let Some(expression) = call_arg_expr(args, 2, "expression") else {
            return Err(RuntimeError {
                message: "request.security missing expression argument".to_owned(),
            });
        };

        let requested_timeframe =
            RequestTimeframe::parse(&timeframe).map_err(|err| RuntimeError {
                message: err.to_string(),
            })?;
        let chart = self.request_environment.chart();
        let chart_symbol = chart.symbol().to_owned();
        let chart_timeframe = chart.timeframe().clone();

        if symbol == chart_symbol && requested_timeframe == chart_timeframe {
            return self.eval_expr(expression);
        }

        self.eval_provider_security(
            call_site_id,
            &symbol,
            requested_timeframe,
            &chart_timeframe,
            expression,
            merge,
        )
    }

    fn eval_provider_security(
        &mut self,
        call_site_id: CallSiteId,
        symbol: &str,
        requested_timeframe: RequestTimeframe,
        chart_timeframe: &RequestTimeframe,
        expression: &HirExpr,
        merge: RequestMergePolicy,
    ) -> Result<PineValue, RuntimeError> {
        validate_provider_timeframe(symbol, &requested_timeframe, chart_timeframe)?;
        let key = RequestKey::new(symbol, requested_timeframe.clone());
        let current_time = self
            .current_bar
            .map(|bar| bar.time)
            .ok_or_else(|| RuntimeError {
                message: "request.security has no current chart bar".to_owned(),
            })?;

        let cache_key = RequestCacheKey::new(call_site_id, key.symbol(), key.timeframe().value());
        if !self.request_cache.contains_key(&cache_key) {
            let requested_bars = self
                .request_environment
                .provider()
                .bars(&key)
                .map_err(|err| RuntimeError {
                    message: err.to_string(),
                })?
                .to_vec();
            let requested_environment = self
                .request_environment
                .for_chart(ChartContext::new(key.symbol(), requested_timeframe.clone()));
            let requested_values =
                self.evaluate_requested_values(&requested_bars, expression, requested_environment)?;
            self.request_cache
                .insert(cache_key.clone(), requested_values);
        }

        let requested_values = self
            .request_cache
            .get(&cache_key)
            .ok_or_else(|| RuntimeError {
                message: "request.security requested context cache was not populated".to_owned(),
            })?;
        Ok(align_requested_value(
            requested_values,
            current_time,
            &requested_timeframe,
            chart_timeframe,
            merge,
            self.current_bar_update_kind,
        ))
    }

    fn evaluate_requested_values(
        &mut self,
        requested_bars: &[Bar],
        expression: &HirExpr,
        requested_environment: RequestEnvironment,
    ) -> Result<Vec<(i64, PineValue)>, RuntimeError> {
        let mut runtime =
            HistoricalRuntime::with_request_environment(self.program, requested_environment);
        let mut values = Vec::with_capacity(requested_bars.len());
        for bar in requested_bars {
            values.push((
                bar.time,
                runtime.eval_requested_bar_expression(*bar, expression)?,
            ));
        }
        self.legacy_security_repaint_warnings
            .extend(runtime.legacy_security_repaint_warnings);
        Ok(values)
    }

    fn eval_requested_bar_expression(
        &mut self,
        bar: Bar,
        expression: &HirExpr,
    ) -> Result<PineValue, RuntimeError> {
        let bar_index = self.bars;
        self.current_bar_update_kind = BarUpdateKind::Historical;
        self.current_bar_is_new = true;
        self.current_bar = Some(bar);
        self.series_store.set_current_bar(bar_index);
        self.current_symbols.clear();
        self.current_series.clear();
        self.set_builtin_symbols(&bar, bar_index)?;

        let value = self.eval_expr(expression)?;
        self.commit_current_series()?;
        self.previous_bar_time = Some(bar.time);
        self.bars += 1;
        self.current_bar_update_kind = BarUpdateKind::Historical;
        self.current_bar_is_new = true;
        self.current_bar = None;
        Ok(value)
    }
}

fn validate_provider_timeframe(
    symbol: &str,
    requested_timeframe: &RequestTimeframe,
    chart_timeframe: &RequestTimeframe,
) -> Result<(), RuntimeError> {
    if requested_timeframe.seconds() < chart_timeframe.seconds() {
        return Err(RuntimeError {
            message: format!(
                "request.security lower timeframe requests are not supported for symbol `{symbol}` timeframe `{}` on chart timeframe `{}`",
                requested_timeframe.value(),
                chart_timeframe.value()
            ),
        });
    }
    if requested_timeframe.seconds() % chart_timeframe.seconds() != 0 {
        return Err(RuntimeError {
            message: format!(
                "request.security requested timeframe `{}` must be an integer multiple of chart timeframe `{}`",
                requested_timeframe.value(),
                chart_timeframe.value()
            ),
        });
    }
    Ok(())
}

fn align_requested_value(
    requested_values: &[(i64, PineValue)],
    current_time: i64,
    requested_timeframe: &RequestTimeframe,
    chart_timeframe: &RequestTimeframe,
    merge: RequestMergePolicy,
    update_kind: BarUpdateKind,
) -> PineValue {
    if requested_timeframe == chart_timeframe {
        let matched = match merge.gaps {
            RequestGaps::On => requested_values
                .iter()
                .find(|(time, _)| *time == current_time),
            RequestGaps::Off => requested_values
                .iter()
                .take_while(|(time, _)| *time <= current_time)
                .last(),
        };
        return matched
            .map(|(_, value)| value.clone())
            .unwrap_or(PineValue::Na);
    }

    let chart_close = request_bar_nominal_close(current_time, chart_timeframe);
    let historical_lookahead =
        merge.lookahead == RequestLookahead::On && update_kind == BarUpdateKind::Historical;
    let matched = match (historical_lookahead, merge.gaps) {
        (true, RequestGaps::On) => requested_values
            .iter()
            .find(|(time, _)| *time == current_time),
        (true, RequestGaps::Off) => requested_values
            .iter()
            .take_while(|(time, _)| *time <= current_time)
            .last(),
        (false, RequestGaps::On) => requested_values
            .iter()
            .enumerate()
            .find(|(index, _)| {
                requested_bar_close(requested_values, *index, requested_timeframe) == chart_close
            })
            .map(|(_, value)| value),
        (false, RequestGaps::Off) => requested_values
            .iter()
            .enumerate()
            .take_while(|(index, _)| {
                requested_bar_close(requested_values, *index, requested_timeframe) <= chart_close
            })
            .last()
            .map(|(_, value)| value),
    };
    matched
        .map(|(_, value)| value.clone())
        .unwrap_or(PineValue::Na)
}

fn request_bar_nominal_close(open_time: i64, timeframe: &RequestTimeframe) -> i64 {
    calendar_timeframe_close(open_time, timeframe.value(), timeframe.seconds())
        .unwrap_or_else(|| open_time.saturating_add(timeframe.seconds().saturating_mul(1000)))
}

fn requested_bar_close(
    requested_values: &[(i64, PineValue)],
    index: usize,
    timeframe: &RequestTimeframe,
) -> i64 {
    let open_time = requested_values[index].0;
    let nominal_close = request_bar_nominal_close(open_time, timeframe);
    requested_values
        .get(index + 1)
        .map(|(next_open, _)| *next_open)
        .filter(|next_open| *next_open > open_time)
        .map_or(nominal_close, |next_open| nominal_close.min(next_open))
}

fn legacy_source_span(args: &[HirCallArg]) -> Option<(i64, i64)> {
    let literal = |name: &str| {
        args.iter()
            .find(|arg| arg.name.as_deref() == Some(name))
            .and_then(|arg| match arg.value.kind {
                pine_ir::HirExprKind::Literal(pine_ir::HirLiteral::Int(value)) => Some(value),
                _ => None,
            })
    };
    Some((literal("$legacy_span_start")?, literal("$legacy_span_end")?))
}
