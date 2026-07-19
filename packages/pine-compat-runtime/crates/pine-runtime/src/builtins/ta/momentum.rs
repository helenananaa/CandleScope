use super::*;

impl<'a> HistoricalRuntime<'a> {
    pub(crate) fn eval_change(&mut self, args: &[HirCallArg]) -> Result<PineValue, RuntimeError> {
        let Some(source_arg) = ta_arg(args, 0, "source") else {
            return Ok(PineValue::Na);
        };
        let current = self.eval_expr(source_arg)?;
        let length = if let Some(length_arg) = ta_arg(args, 1, "length") {
            self.eval_expr(length_arg)?.as_i64().unwrap_or(1)
        } else {
            1
        };
        if length <= 0 {
            return Ok(PineValue::Na);
        }

        let Some(series_id) = source_arg.series_id else {
            return Ok(PineValue::Na);
        };
        let previous = self.series_store.read(series_id, length as usize);

        match (current, previous) {
            (PineValue::Bool(current), PineValue::Bool(previous)) => {
                Ok(PineValue::Bool(current != previous))
            }
            (current, previous) => {
                let Some(current) = current.as_f64() else {
                    return Ok(PineValue::Na);
                };
                let Some(previous) = previous.as_f64() else {
                    return Ok(PineValue::Na);
                };
                Ok(PineValue::Float(current - previous))
            }
        }
    }

    pub(crate) fn eval_mom(&mut self, args: &[HirCallArg]) -> Result<PineValue, RuntimeError> {
        let Some((current, previous)) = self.current_and_previous(args)? else {
            return Ok(PineValue::Na);
        };

        Ok(PineValue::Float(current - previous))
    }

    pub(crate) fn eval_roc(&mut self, args: &[HirCallArg]) -> Result<PineValue, RuntimeError> {
        let Some((current, previous)) = self.current_and_previous(args)? else {
            return Ok(PineValue::Na);
        };
        if previous == 0.0 {
            return Ok(PineValue::Na);
        }

        Ok(finite_float_or_na(100.0 * (current - previous) / previous))
    }

    pub(crate) fn current_and_previous(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<Option<(f64, f64)>, RuntimeError> {
        let Some(source_arg) = ta_arg(args, 0, "source") else {
            return Ok(None);
        };
        let Some(length_arg) = ta_arg(args, 1, "length") else {
            return Ok(None);
        };
        let current = self.eval_expr(source_arg)?;
        let length = self.eval_expr(length_arg)?.as_i64().unwrap_or(0);
        if length <= 0 {
            return Ok(None);
        }

        let Some(current) = current.as_f64() else {
            return Ok(None);
        };
        let Some(series_id) = source_arg.series_id else {
            return Ok(None);
        };
        let previous = self.series_store.read(series_id, length as usize);
        let Some(previous) = previous.as_f64() else {
            return Ok(None);
        };

        Ok(Some((current, previous)))
    }

    pub(crate) fn eval_tsi(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let source_arg = ta_arg(args, 0, "source");
        let source = source_arg
            .map(|arg| self.eval_expr(arg))
            .transpose()?
            .unwrap_or(PineValue::Na);
        let short_length = ta_arg(args, 1, "short_length")
            .map(|arg| self.eval_expr(arg))
            .transpose()?
            .and_then(|value| value.as_i64())
            .unwrap_or(0);
        let long_length = ta_arg(args, 2, "long_length")
            .map(|arg| self.eval_expr(arg))
            .transpose()?
            .and_then(|value| value.as_i64())
            .unwrap_or(0);
        if short_length <= 0 || long_length <= 0 {
            return Ok(PineValue::Na);
        }

        let Some(source) = source.as_f64() else {
            return Ok(PineValue::Na);
        };
        let Some(series_id) = source_arg.and_then(|arg| arg.series_id) else {
            return Ok(PineValue::Na);
        };
        let Some(previous_source) = self.read_declared_series_history(series_id, 1).as_f64() else {
            return Ok(PineValue::Na);
        };

        let momentum = source - previous_source;
        let previous = tsi_state(self.call_state.get(&call_site_id));
        let short_momentum = ema_next(previous.map(|state| state.0), momentum, short_length);
        let long_momentum = ema_next(previous.map(|state| state.1), short_momentum, long_length);
        let short_abs_momentum =
            ema_next(previous.map(|state| state.2), momentum.abs(), short_length);
        let long_abs_momentum = ema_next(
            previous.map(|state| state.3),
            short_abs_momentum,
            long_length,
        );

        self.call_state.insert(
            call_site_id,
            PineValue::Tuple(vec![
                PineValue::Float(short_momentum),
                PineValue::Float(long_momentum),
                PineValue::Float(short_abs_momentum),
                PineValue::Float(long_abs_momentum),
            ]),
        );

        if long_abs_momentum == 0.0 {
            return Ok(PineValue::Na);
        }
        Ok(finite_float_or_na(long_momentum / long_abs_momentum))
    }

    pub(crate) fn eval_cmo(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let source_arg = ta_arg(args, 0, "source");
        let source = source_arg
            .map(|arg| self.eval_expr(arg))
            .transpose()?
            .unwrap_or(PineValue::Na);
        let length = ta_arg(args, 1, "length")
            .map(|arg| self.eval_expr(arg))
            .transpose()?
            .and_then(|value| value.as_i64())
            .unwrap_or(0);
        if length <= 0 {
            return Ok(PineValue::Na);
        }

        let length = length as usize;
        let (positive_change, negative_change) =
            match (source.as_f64(), source_arg.and_then(|arg| arg.series_id)) {
                (Some(source), Some(series_id)) => {
                    match self.read_declared_series_history(series_id, 1).as_f64() {
                        Some(previous) => {
                            let change = source - previous;
                            (Some(change.max(0.0)), Some((-change).max(0.0)))
                        }
                        None => (None, None),
                    }
                }
                _ => (None, None),
            };

        self.update_cmo_windows(call_site_id, positive_change, negative_change, length);

        let positive_window = self
            .rolling_windows
            .get(&RollingWindowKey::CmoPositive(call_site_id));
        let negative_window = self
            .rolling_windows
            .get(&RollingWindowKey::CmoNegative(call_site_id));
        let (Some(positive_window), Some(negative_window)) = (positive_window, negative_window)
        else {
            return Ok(PineValue::Na);
        };
        if !positive_window.is_ready(length) || !negative_window.is_ready(length) {
            return Ok(PineValue::Na);
        }

        let positive_sum = positive_window.sum;
        let negative_sum = negative_window.sum;
        let denominator = positive_sum + negative_sum;
        if denominator == 0.0 {
            return Ok(PineValue::Na);
        }

        Ok(finite_float_or_na(
            100.0 * (positive_sum - negative_sum) / denominator,
        ))
    }

    pub(crate) fn update_cmo_windows(
        &mut self,
        call_site_id: CallSiteId,
        positive_change: Option<f64>,
        negative_change: Option<f64>,
        length: usize,
    ) {
        self.update_rolling_window_key(
            RollingWindowKey::CmoPositive(call_site_id),
            positive_change,
            length,
        );
        self.update_rolling_window_key(
            RollingWindowKey::CmoNegative(call_site_id),
            negative_change,
            length,
        );
    }
}
