use super::*;

impl<'a> HistoricalRuntime<'a> {
    pub(crate) fn eval_sma(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let source = ta_arg(args, 0, "source")
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
        let window = self.update_rolling_window(call_site_id, source, length);
        if !window.is_ready(length) {
            return Ok(PineValue::Na);
        }

        Ok(PineValue::Float(window.mean(length)))
    }

    pub(crate) fn eval_bb(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let (source, length, mult) = self.eval_average_source_length_mult(args)?;
        if length <= 0 {
            return Ok(PineValue::Tuple(vec![
                PineValue::Na,
                PineValue::Na,
                PineValue::Na,
            ]));
        }

        let length = length as usize;
        let window = self.update_rolling_window(call_site_id, source, length);
        if !window.is_ready(length) {
            return Ok(PineValue::Tuple(vec![
                PineValue::Na,
                PineValue::Na,
                PineValue::Na,
            ]));
        }
        let Some(mult) = mult else {
            return Ok(PineValue::Tuple(vec![
                PineValue::Na,
                PineValue::Na,
                PineValue::Na,
            ]));
        };

        let basis = window.mean(length);
        let variance = window.variance(length, true);
        let dev = mult * variance.sqrt();

        Ok(PineValue::Tuple(vec![
            PineValue::Float(basis),
            PineValue::Float(basis + dev),
            PineValue::Float(basis - dev),
        ]))
    }

    pub(crate) fn eval_bbw(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let (source, length, mult) = self.eval_average_source_length_mult(args)?;
        if length <= 0 {
            return Ok(PineValue::Na);
        }

        let length = length as usize;
        let window = self.update_rolling_window(call_site_id, source, length);
        if !window.is_ready(length) {
            return Ok(PineValue::Na);
        }
        let Some(mult) = mult else {
            return Ok(PineValue::Na);
        };

        let basis = window.mean(length);
        if basis == 0.0 {
            return Ok(PineValue::Na);
        }
        let dev = mult * window.variance(length, true).sqrt();

        Ok(finite_float_or_na((2.0 * dev) / basis))
    }

    pub(crate) fn eval_kc(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let Some((basis, range_ema, mult)) = self.eval_kc_components(call_site_id, args)? else {
            return Ok(three_na_tuple());
        };

        Ok(PineValue::Tuple(vec![
            finite_float_or_na(basis),
            finite_float_or_na(basis + range_ema * mult),
            finite_float_or_na(basis - range_ema * mult),
        ]))
    }

    pub(crate) fn eval_kcw(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let Some((basis, range_ema, mult)) = self.eval_kc_components(call_site_id, args)? else {
            return Ok(PineValue::Na);
        };
        if basis == 0.0 {
            return Ok(PineValue::Na);
        }

        Ok(finite_float_or_na((2.0 * range_ema * mult) / basis))
    }

    pub(crate) fn eval_kc_components(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<Option<(f64, f64, f64)>, RuntimeError> {
        let (source, length) = self.eval_average_source_length(args)?;
        let Some(source) = source.as_f64() else {
            return Ok(None);
        };
        let Some(mult) = ta_arg(args, 2, "mult")
            .map(|arg| self.eval_expr(arg))
            .transpose()?
            .and_then(|value| value.as_f64())
        else {
            return Ok(None);
        };
        let use_true_range = if let Some(arg) = ta_arg(args, 3, "useTrueRange") {
            match self.eval_expr(arg)? {
                PineValue::Bool(value) => value,
                PineValue::Na => true,
                _ => false,
            }
        } else {
            true
        };
        if length <= 0 {
            return Ok(None);
        }

        let span = if use_true_range {
            self.true_range(true).as_f64()
        } else {
            match (
                self.current_builtin_f64("high"),
                self.current_builtin_f64("low"),
            ) {
                (Some(high), Some(low)) => Some(high - low),
                _ => None,
            }
        };
        let Some(span) = span else {
            return Ok(None);
        };

        let previous = kc_state(self.call_state.get(&call_site_id));
        let basis = ema_next(previous.map(|state| state.0), source, length);
        let range_ema = ema_next(previous.map(|state| state.1), span, length);
        self.call_state.insert(
            call_site_id,
            PineValue::Tuple(vec![PineValue::Float(basis), PineValue::Float(range_ema)]),
        );

        Ok(Some((basis, range_ema, mult)))
    }

    pub(crate) fn eval_wma(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let (source, length) = self.eval_average_source_length(args)?;
        if length <= 0 {
            return Ok(PineValue::Na);
        }

        let length = length as usize;
        let window = self.update_rolling_window(call_site_id, source, length);
        if !window.is_ready(length) {
            return Ok(PineValue::Na);
        }

        Ok(finite_float_or_na(window.weighted_mean(length)))
    }

    pub(crate) fn eval_hma(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let (source, length) = self.eval_average_source_length(args)?;
        if length <= 0 {
            return Ok(PineValue::Na);
        }

        let length = length as usize;
        let half_length = (length / 2).max(1);
        let smooth_length = (length as f64).sqrt().round().max(1.0) as usize;
        let source = source.as_f64();

        self.update_rolling_window_key(
            RollingWindowKey::HmaHalf(call_site_id),
            source,
            half_length,
        );
        self.update_rolling_window_key(RollingWindowKey::HmaFull(call_site_id), source, length);

        let half = self
            .rolling_windows
            .get(&RollingWindowKey::HmaHalf(call_site_id));
        let full = self
            .rolling_windows
            .get(&RollingWindowKey::HmaFull(call_site_id));
        let diff = match (half, full) {
            (Some(half), Some(full)) if half.is_ready(half_length) && full.is_ready(length) => {
                Some(2.0 * half.weighted_mean(half_length) - full.weighted_mean(length))
            }
            _ => None,
        };

        let smooth = self.update_rolling_window_key(
            RollingWindowKey::HmaSmooth(call_site_id),
            diff,
            smooth_length,
        );
        if !smooth.is_ready(smooth_length) {
            return Ok(PineValue::Na);
        }

        Ok(finite_float_or_na(smooth.weighted_mean(smooth_length)))
    }

    fn eval_average_source_length(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<(PineValue, i64), RuntimeError> {
        let source = ta_arg(args, 0, "source")
            .map(|arg| self.eval_expr(arg))
            .transpose()?
            .unwrap_or(PineValue::Na);
        let length = ta_arg(args, 1, "length")
            .map(|arg| self.eval_expr(arg))
            .transpose()?
            .and_then(|value| value.as_i64())
            .unwrap_or(0);
        Ok((source, length))
    }

    fn eval_average_source_length_mult(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<(PineValue, i64, Option<f64>), RuntimeError> {
        let (source, length) = self.eval_average_source_length(args)?;
        let mult = ta_arg(args, 2, "mult")
            .map(|arg| self.eval_expr(arg))
            .transpose()?
            .and_then(|value| value.as_f64());
        Ok((source, length, mult))
    }

    pub(crate) fn eval_swma(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let source = ta_arg(args, 0, "source")
            .map(|arg| self.eval_expr(arg))
            .transpose()?
            .unwrap_or(PineValue::Na);
        let length = 4_usize;
        let window = self.update_rolling_window(call_site_id, source, length);
        if !window.is_ready(length) {
            return Ok(PineValue::Na);
        }

        let values: Vec<_> = window.values.iter().flatten().copied().collect();
        let value = (values[0] + 2.0 * values[1] + 2.0 * values[2] + values[3]) / 6.0;
        Ok(finite_float_or_na(value))
    }

    pub(crate) fn eval_alma(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let source = ta_arg(args, 0, "series")
            .map(|arg| self.eval_expr(arg))
            .transpose()?
            .unwrap_or(PineValue::Na);
        let length = ta_arg(args, 1, "length")
            .map(|arg| self.eval_expr(arg))
            .transpose()?
            .and_then(|value| value.as_i64())
            .unwrap_or(0);
        let offset = ta_arg(args, 2, "offset")
            .map(|arg| self.eval_expr(arg))
            .transpose()?
            .and_then(|value| value.as_f64());
        let sigma = ta_arg(args, 3, "sigma")
            .map(|arg| self.eval_expr(arg))
            .transpose()?
            .and_then(|value| value.as_f64());
        let floor_center = ta_arg(args, 4, "floor")
            .map(|arg| self.eval_expr(arg))
            .transpose()?
            .is_some_and(|value| matches!(value, PineValue::Bool(true)));
        if length <= 0 {
            return Ok(PineValue::Na);
        }
        let (Some(offset), Some(sigma)) = (offset, sigma) else {
            return Ok(PineValue::Na);
        };
        if sigma <= 0.0 || !offset.is_finite() || !sigma.is_finite() {
            return Ok(PineValue::Na);
        }

        let length = length as usize;
        let window = self.update_rolling_window(call_site_id, source, length);
        if !window.is_ready(length) {
            return Ok(PineValue::Na);
        }

        let mut center = offset * (length as f64 - 1.0);
        if floor_center {
            center = center.floor();
        }
        let scale = length as f64 / sigma;
        if scale == 0.0 || !scale.is_finite() {
            return Ok(PineValue::Na);
        }

        let mut weighted_sum = 0.0;
        let mut weight_sum = 0.0;
        for (index, value) in window.values.iter().flatten().copied().enumerate() {
            let distance = index as f64 - center;
            let weight = (-(distance * distance) / (2.0 * scale * scale)).exp();
            weighted_sum += value * weight;
            weight_sum += weight;
        }
        if weight_sum == 0.0 || !weight_sum.is_finite() {
            return Ok(PineValue::Na);
        }

        Ok(finite_float_or_na(weighted_sum / weight_sum))
    }

    pub(crate) fn eval_linreg(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let (source, length) = self.eval_average_source_length(args)?;
        let offset = ta_arg(args, 2, "offset")
            .map(|arg| self.eval_expr(arg))
            .transpose()?
            .and_then(|value| value.as_i64())
            .unwrap_or(0);
        if length <= 0 {
            return Ok(PineValue::Na);
        }

        let length = length as usize;
        let window = self.update_rolling_window(call_site_id, source, length);
        if !window.is_ready(length) {
            return Ok(PineValue::Na);
        }

        let values: Vec<_> = window.values.iter().flatten().copied().collect();
        if values.len() == 1 {
            return Ok(finite_float_or_na(values[0]));
        }

        let n = length as f64;
        let mut sum_x = 0.0;
        let mut sum_y = 0.0;
        let mut sum_x_squared = 0.0;
        let mut sum_xy = 0.0;
        for (index, value) in values.iter().enumerate() {
            let x = index as f64;
            sum_x += x;
            sum_y += value;
            sum_x_squared += x * x;
            sum_xy += x * value;
        }

        let denominator = n * sum_x_squared - sum_x * sum_x;
        if denominator == 0.0 {
            return Ok(PineValue::Na);
        }
        let slope = (n * sum_xy - sum_x * sum_y) / denominator;
        let intercept = (sum_y - slope * sum_x) / n;
        let value = intercept + slope * (length as f64 - 1.0 - offset as f64);
        Ok(finite_float_or_na(value))
    }

    pub(crate) fn eval_ema(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let (source, length) = self.eval_average_source_length(args)?;
        let Some(source) = source.as_f64() else {
            return Ok(PineValue::Na);
        };
        if length <= 0 {
            return Ok(PineValue::Na);
        }

        let alpha = 2.0 / (length as f64 + 1.0);
        let value = match self
            .call_state
            .get(&call_site_id)
            .and_then(PineValue::as_f64)
        {
            Some(previous) => PineValue::Float(alpha * source + (1.0 - alpha) * previous),
            None => PineValue::Float(source),
        };
        self.call_state.insert(call_site_id, value.clone());
        Ok(value)
    }

    pub(crate) fn eval_dema(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let Some((source, length)) = self.eval_ema_source_and_length(args)? else {
            return Ok(PineValue::Na);
        };
        let (previous_ema1, previous_ema2, _) = ema_chain_state(self.call_state.get(&call_site_id));
        let ema1 = ema_next(previous_ema1, source, length);
        let ema2 = ema_next(previous_ema2, ema1, length);
        self.call_state.insert(
            call_site_id,
            PineValue::Tuple(vec![PineValue::Float(ema1), PineValue::Float(ema2)]),
        );
        Ok(finite_float_or_na(2.0 * ema1 - ema2))
    }

    pub(crate) fn eval_tema(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let Some((source, length)) = self.eval_ema_source_and_length(args)? else {
            return Ok(PineValue::Na);
        };
        let (previous_ema1, previous_ema2, previous_ema3) =
            ema_chain_state(self.call_state.get(&call_site_id));
        let ema1 = ema_next(previous_ema1, source, length);
        let ema2 = ema_next(previous_ema2, ema1, length);
        let ema3 = ema_next(previous_ema3, ema2, length);
        self.call_state.insert(
            call_site_id,
            PineValue::Tuple(vec![
                PineValue::Float(ema1),
                PineValue::Float(ema2),
                PineValue::Float(ema3),
            ]),
        );
        Ok(finite_float_or_na(3.0 * ema1 - 3.0 * ema2 + ema3))
    }

    pub(crate) fn eval_ema_source_and_length(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<Option<(f64, i64)>, RuntimeError> {
        let (source, length) = self.eval_average_source_length(args)?;
        let Some(source) = source.as_f64() else {
            return Ok(None);
        };
        if length <= 0 {
            return Ok(None);
        }
        Ok(Some((source, length)))
    }

    pub(crate) fn eval_rma(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let (source, length) = self.eval_average_source_length(args)?;
        let Some(source) = source.as_f64() else {
            return Ok(PineValue::Na);
        };
        if length <= 0 {
            return Ok(PineValue::Na);
        }

        let value = rma_next(
            self.call_state
                .get(&call_site_id)
                .and_then(PineValue::as_f64),
            source,
            length,
        );
        let value = PineValue::Float(value);
        self.call_state.insert(call_site_id, value.clone());
        Ok(value)
    }

    pub(crate) fn eval_rsi(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let (source, length) = self.eval_average_source_length(args)?;
        let Some(source) = source.as_f64() else {
            return Ok(PineValue::Na);
        };
        if length <= 0 {
            return Ok(PineValue::Na);
        }

        let Some(mut state) = self.rsi_state.get(&call_site_id).copied() else {
            self.rsi_state.insert(
                call_site_id,
                RsiState {
                    previous_source: source,
                    average_gain: None,
                    average_loss: None,
                },
            );
            return Ok(PineValue::Na);
        };

        let change = source - state.previous_source;
        let gain = change.max(0.0);
        let loss = (-change).max(0.0);
        let average_gain = rma_next(state.average_gain, gain, length);
        let average_loss = rma_next(state.average_loss, loss, length);
        state.previous_source = source;
        state.average_gain = Some(average_gain);
        state.average_loss = Some(average_loss);
        self.rsi_state.insert(call_site_id, state);

        Ok(PineValue::Float(rsi_from_averages(
            average_gain,
            average_loss,
        )))
    }

    pub(crate) fn eval_macd(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let source = ta_arg(args, 0, "source")
            .map(|arg| self.eval_expr(arg))
            .transpose()?
            .unwrap_or(PineValue::Na);
        let fast_length = ta_arg(args, 1, "fastlen")
            .map(|arg| self.eval_expr(arg))
            .transpose()?
            .and_then(|value| value.as_i64())
            .unwrap_or(0);
        let slow_length = ta_arg(args, 2, "slowlen")
            .map(|arg| self.eval_expr(arg))
            .transpose()?
            .and_then(|value| value.as_i64())
            .unwrap_or(0);
        let signal_length = ta_arg(args, 3, "siglen")
            .map(|arg| self.eval_expr(arg))
            .transpose()?
            .and_then(|value| value.as_i64())
            .unwrap_or(0);
        let Some(source) = source.as_f64() else {
            return Ok(PineValue::Tuple(vec![
                PineValue::Na,
                PineValue::Na,
                PineValue::Na,
            ]));
        };
        if fast_length <= 0 || slow_length <= 0 || signal_length <= 0 {
            return Ok(PineValue::Tuple(vec![
                PineValue::Na,
                PineValue::Na,
                PineValue::Na,
            ]));
        }

        let mut state = self
            .macd_state
            .get(&call_site_id)
            .copied()
            .unwrap_or(MacdState {
                fast_ema: None,
                slow_ema: None,
                signal_ema: None,
            });
        let fast_ema = ema_next(state.fast_ema, source, fast_length);
        let slow_ema = ema_next(state.slow_ema, source, slow_length);
        let macd = fast_ema - slow_ema;
        let signal = ema_next(state.signal_ema, macd, signal_length);
        let hist = macd - signal;
        state.fast_ema = Some(fast_ema);
        state.slow_ema = Some(slow_ema);
        state.signal_ema = Some(signal);
        self.macd_state.insert(call_site_id, state);

        Ok(PineValue::Tuple(vec![
            PineValue::Float(macd),
            PineValue::Float(signal),
            PineValue::Float(hist),
        ]))
    }
}
