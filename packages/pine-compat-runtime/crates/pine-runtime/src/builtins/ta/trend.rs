use super::*;

impl<'a> HistoricalRuntime<'a> {
    pub(crate) fn eval_tr(&mut self, args: &[HirCallArg]) -> Result<PineValue, RuntimeError> {
        let handle_na = if let Some(arg) = ta_arg(args, 0, "handle_na") {
            matches!(self.eval_expr(arg)?, PineValue::Bool(true))
        } else {
            true
        };

        Ok(self.true_range(handle_na))
    }

    pub(crate) fn eval_atr(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let length = ta_arg(args, 0, "length")
            .map(|arg| self.eval_expr(arg))
            .transpose()?
            .and_then(|value| value.as_i64())
            .unwrap_or(0);
        if length <= 0 {
            return Ok(PineValue::Na);
        }

        let true_range = self.true_range(true);
        let Some(true_range) = true_range.as_f64() else {
            return Ok(PineValue::Na);
        };
        let value = rma_next(
            self.call_state
                .get(&call_site_id)
                .and_then(PineValue::as_f64),
            true_range,
            length,
        );
        let value = PineValue::Float(value);
        self.call_state.insert(call_site_id, value.clone());
        Ok(value)
    }

    pub(crate) fn eval_supertrend(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let Some(factor) = ta_arg(args, 0, "factor")
            .map(|arg| self.eval_expr(arg))
            .transpose()?
            .and_then(|value| value.as_f64())
        else {
            return Ok(two_na_tuple());
        };
        let atr_period = ta_arg(args, 1, "atrPeriod")
            .map(|arg| self.eval_expr(arg))
            .transpose()?
            .and_then(|value| value.as_i64())
            .unwrap_or(0);
        if atr_period <= 0 {
            return Ok(two_na_tuple());
        }

        let Some(true_range) = self.true_range(true).as_f64() else {
            return Ok(two_na_tuple());
        };
        let (Some(high), Some(low), Some(close)) = (
            self.current_builtin_f64("high"),
            self.current_builtin_f64("low"),
            self.current_builtin_f64("close"),
        ) else {
            return Ok(two_na_tuple());
        };

        let previous = supertrend_state(self.call_state.get(&call_site_id));
        let atr = rma_next(previous.map(|state| state.0), true_range, atr_period);
        let hl2 = (high + low) / 2.0;
        let basic_upper = hl2 + factor * atr;
        let basic_lower = hl2 - factor * atr;
        let previous_close = self.previous_close();

        let upper = match previous.zip(previous_close) {
            Some(((_, previous_upper, _, _), previous_close))
                if basic_upper >= previous_upper && previous_close <= previous_upper =>
            {
                previous_upper
            }
            _ => basic_upper,
        };
        let lower = match previous.zip(previous_close) {
            Some(((_, _, previous_lower, _), previous_close))
                if basic_lower <= previous_lower && previous_close >= previous_lower =>
            {
                previous_lower
            }
            _ => basic_lower,
        };

        let direction = match previous {
            None => 1.0,
            Some((_, previous_upper, _, previous_supertrend))
                if previous_supertrend == previous_upper && close > upper =>
            {
                -1.0
            }
            Some((_, previous_upper, _, previous_supertrend))
                if previous_supertrend == previous_upper =>
            {
                1.0
            }
            Some(_) if close < lower => 1.0,
            Some(_) => -1.0,
        };
        let supertrend = if direction < 0.0 { lower } else { upper };

        self.call_state.insert(
            call_site_id,
            PineValue::Tuple(vec![
                PineValue::Float(atr),
                PineValue::Float(upper),
                PineValue::Float(lower),
                PineValue::Float(supertrend),
            ]),
        );

        Ok(PineValue::Tuple(vec![
            finite_float_or_na(supertrend),
            PineValue::Float(direction),
        ]))
    }

    pub(crate) fn eval_dmi(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let di_length = ta_arg(args, 0, "diLength")
            .map(|arg| self.eval_expr(arg))
            .transpose()?
            .and_then(|value| value.as_i64())
            .unwrap_or(0);
        let adx_smoothing = ta_arg(args, 1, "adxSmoothing")
            .map(|arg| self.eval_expr(arg))
            .transpose()?
            .and_then(|value| value.as_i64())
            .unwrap_or(0);
        if di_length <= 0 || adx_smoothing <= 0 {
            return Ok(three_na_tuple());
        }

        let (Some(high), Some(low)) = (
            self.current_builtin_f64("high"),
            self.current_builtin_f64("low"),
        ) else {
            return Ok(three_na_tuple());
        };
        let Some(true_range) = self.true_range(true).as_f64() else {
            return Ok(three_na_tuple());
        };

        let (plus_dm, minus_dm) = match (
            self.previous_builtin_f64("high"),
            self.previous_builtin_f64("low"),
        ) {
            (Some(previous_high), Some(previous_low)) => {
                let up_move = high - previous_high;
                let down_move = previous_low - low;
                (
                    if up_move > down_move && up_move > 0.0 {
                        up_move
                    } else {
                        0.0
                    },
                    if down_move > up_move && down_move > 0.0 {
                        down_move
                    } else {
                        0.0
                    },
                )
            }
            _ => (0.0, 0.0),
        };

        let previous = dmi_state(self.call_state.get(&call_site_id));
        let smoothed_tr = rma_next(previous.map(|state| state.0), true_range, di_length);
        let smoothed_plus_dm = rma_next(previous.map(|state| state.1), plus_dm, di_length);
        let smoothed_minus_dm = rma_next(previous.map(|state| state.2), minus_dm, di_length);
        let (plus_di, minus_di) = if smoothed_tr.is_finite() && smoothed_tr != 0.0 {
            (
                100.0 * smoothed_plus_dm / smoothed_tr,
                100.0 * smoothed_minus_dm / smoothed_tr,
            )
        } else {
            (0.0, 0.0)
        };
        let di_sum = plus_di + minus_di;
        let dx = if di_sum.is_finite() && di_sum != 0.0 {
            100.0 * (plus_di - minus_di).abs() / di_sum
        } else {
            0.0
        };
        let adx = rma_next(previous.map(|state| state.3), dx, adx_smoothing);

        self.call_state.insert(
            call_site_id,
            PineValue::Tuple(vec![
                PineValue::Float(smoothed_tr),
                PineValue::Float(smoothed_plus_dm),
                PineValue::Float(smoothed_minus_dm),
                PineValue::Float(adx),
            ]),
        );

        Ok(PineValue::Tuple(vec![
            finite_float_or_na(plus_di),
            finite_float_or_na(minus_di),
            finite_float_or_na(adx),
        ]))
    }

    pub(crate) fn eval_sar(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let Some(start) = ta_arg(args, 0, "start")
            .map(|arg| self.eval_expr(arg))
            .transpose()?
            .and_then(|value| value.as_f64())
        else {
            return Ok(PineValue::Na);
        };
        let Some(increment) = ta_arg(args, 1, "inc")
            .map(|arg| self.eval_expr(arg))
            .transpose()?
            .and_then(|value| value.as_f64())
        else {
            return Ok(PineValue::Na);
        };
        let Some(max_acceleration) = ta_arg(args, 2, "max")
            .map(|arg| self.eval_expr(arg))
            .transpose()?
            .and_then(|value| value.as_f64())
        else {
            return Ok(PineValue::Na);
        };
        if !start.is_finite() || !increment.is_finite() || !max_acceleration.is_finite() {
            return Ok(PineValue::Na);
        }

        let (Some(high), Some(low), Some(close)) = (
            self.current_builtin_f64("high"),
            self.current_builtin_f64("low"),
            self.current_builtin_f64("close"),
        ) else {
            return Ok(PineValue::Na);
        };

        let mut is_first_trend_bar = false;
        let (mut result, mut max_min, mut acceleration, mut is_below) =
            if let Some(state) = sar_state(self.call_state.get(&call_site_id)) {
                state
            } else {
                let (Some(previous_close), Some(previous_high), Some(previous_low)) = (
                    self.previous_builtin_f64("close"),
                    self.previous_builtin_f64("high"),
                    self.previous_builtin_f64("low"),
                ) else {
                    return Ok(PineValue::Na);
                };
                is_first_trend_bar = true;
                if close > previous_close {
                    (previous_low, high, start, true)
                } else {
                    (previous_high, low, start, false)
                }
            };

        result += acceleration * (max_min - result);
        if is_below {
            if result > low {
                is_first_trend_bar = true;
                is_below = false;
                result = high.max(max_min);
                max_min = low;
                acceleration = start;
            }
        } else if result < high {
            is_first_trend_bar = true;
            is_below = true;
            result = low.min(max_min);
            max_min = high;
            acceleration = start;
        }

        if !is_first_trend_bar {
            if is_below {
                if high > max_min {
                    max_min = high;
                    acceleration = (acceleration + increment).min(max_acceleration);
                }
            } else if low < max_min {
                max_min = low;
                acceleration = (acceleration + increment).min(max_acceleration);
            }
        }

        if is_below {
            if let Some(previous_low) = self.previous_builtin_f64("low") {
                result = result.min(previous_low);
            }
            if let Some(previous_previous_low) = self.builtin_f64_at("low", 2) {
                result = result.min(previous_previous_low);
            }
        } else {
            if let Some(previous_high) = self.previous_builtin_f64("high") {
                result = result.max(previous_high);
            }
            if let Some(previous_previous_high) = self.builtin_f64_at("high", 2) {
                result = result.max(previous_previous_high);
            }
        }

        self.call_state.insert(
            call_site_id,
            PineValue::Tuple(vec![
                PineValue::Float(result),
                PineValue::Float(max_min),
                PineValue::Float(acceleration),
                PineValue::Bool(is_below),
            ]),
        );

        Ok(finite_float_or_na(result))
    }

    pub(crate) fn true_range(&self, handle_na: bool) -> PineValue {
        let Some(high) = self.current_builtin_f64("high") else {
            return PineValue::Na;
        };
        let Some(low) = self.current_builtin_f64("low") else {
            return PineValue::Na;
        };
        let high_low = high - low;
        let previous_close = self.previous_close();

        let Some(previous_close) = previous_close else {
            return if handle_na {
                PineValue::Float(high_low)
            } else {
                PineValue::Na
            };
        };

        PineValue::Float(
            high_low
                .max((high - previous_close).abs())
                .max((low - previous_close).abs()),
        )
    }
}
