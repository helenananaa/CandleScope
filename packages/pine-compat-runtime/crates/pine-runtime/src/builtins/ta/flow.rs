use pine_ir::SeriesId;

use super::*;

impl<'a> HistoricalRuntime<'a> {
    pub(crate) fn eval_cum(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let source = self.eval_flow_source(args)?;
        let Some(source) = source.as_f64() else {
            self.call_state.insert(call_site_id, PineValue::Na);
            return Ok(PineValue::Na);
        };

        let value = self
            .call_state
            .get(&call_site_id)
            .and_then(PineValue::as_f64)
            .unwrap_or(0.0)
            + source;
        let value = PineValue::Float(value);
        self.call_state.insert(call_site_id, value.clone());
        Ok(value)
    }

    pub(crate) fn eval_all_time_extreme(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
        mode: WindowExtreme,
    ) -> Result<PineValue, RuntimeError> {
        let source = self.eval_flow_source(args)?;
        let Some(source) = source.as_f64() else {
            return Ok(self
                .call_state
                .get(&call_site_id)
                .cloned()
                .unwrap_or(PineValue::Na));
        };

        let value = match self
            .call_state
            .get(&call_site_id)
            .and_then(PineValue::as_f64)
        {
            Some(previous) => match mode {
                WindowExtreme::Highest => previous.max(source),
                WindowExtreme::Lowest => previous.min(source),
            },
            None => source,
        };
        let value = finite_float_or_na(value);
        self.call_state.insert(call_site_id, value.clone());
        Ok(value)
    }

    pub(crate) fn eval_cci(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let (source, length) = self.eval_flow_source_length(args)?;
        if length <= 0 {
            return Ok(PineValue::Na);
        }

        let Some(current) = source.as_f64() else {
            self.update_rolling_window(call_site_id, source, length as usize);
            return Ok(PineValue::Na);
        };

        let length = length as usize;
        let window = self.update_rolling_window(call_site_id, PineValue::Float(current), length);
        if !window.is_ready(length) {
            return Ok(PineValue::Na);
        }

        let deviation = window.mean_absolute_deviation(length);
        if deviation == 0.0 {
            return Ok(PineValue::Na);
        }

        Ok(finite_float_or_na(
            (current - window.mean(length)) / (0.015 * deviation),
        ))
    }

    pub(crate) fn eval_cog(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let (source, length) = self.eval_flow_source_length(args)?;
        if length <= 0 {
            return Ok(PineValue::Na);
        }

        let length = length as usize;
        let window = self.update_rolling_window(call_site_id, source, length);
        if !window.is_ready(length) || window.sum == 0.0 {
            return Ok(PineValue::Na);
        }

        Ok(finite_float_or_na(window.center_of_gravity(length)))
    }

    pub(crate) fn eval_vwma(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let (source, length) = self.eval_flow_source_length(args)?;
        if length <= 0 {
            return Ok(PineValue::Na);
        }

        let length = length as usize;
        let Some(source) = source.as_f64() else {
            self.update_rolling_window_key(
                RollingWindowKey::VwmaWeighted(call_site_id),
                None,
                length,
            );
            self.update_rolling_window_key(
                RollingWindowKey::VwmaVolume(call_site_id),
                None,
                length,
            );
            return Ok(PineValue::Na);
        };
        let Some(volume) = self.current_builtin_f64("volume") else {
            self.update_rolling_window_key(
                RollingWindowKey::VwmaWeighted(call_site_id),
                None,
                length,
            );
            self.update_rolling_window_key(
                RollingWindowKey::VwmaVolume(call_site_id),
                None,
                length,
            );
            return Ok(PineValue::Na);
        };

        self.update_rolling_window_key(
            RollingWindowKey::VwmaWeighted(call_site_id),
            Some(source * volume),
            length,
        );
        self.update_rolling_window_key(
            RollingWindowKey::VwmaVolume(call_site_id),
            Some(volume),
            length,
        );

        let weighted = self
            .rolling_windows
            .get(&RollingWindowKey::VwmaWeighted(call_site_id));
        let volumes = self
            .rolling_windows
            .get(&RollingWindowKey::VwmaVolume(call_site_id));
        let (Some(weighted), Some(volumes)) = (weighted, volumes) else {
            return Ok(PineValue::Na);
        };
        if !weighted.is_ready(length) || !volumes.is_ready(length) || volumes.sum == 0.0 {
            return Ok(PineValue::Na);
        }

        Ok(finite_float_or_na(weighted.sum / volumes.sum))
    }

    fn eval_flow_source(&mut self, args: &[HirCallArg]) -> Result<PineValue, RuntimeError> {
        ta_arg(args, 0, "source")
            .map(|arg| self.eval_expr(arg))
            .transpose()
            .map(|value| value.unwrap_or(PineValue::Na))
    }

    fn eval_flow_source_length(
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

    pub(crate) fn eval_mfi(
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
        let Some(source) = source.as_f64() else {
            self.update_mfi_windows(call_site_id, None, None, length);
            return Ok(PineValue::Na);
        };
        let Some(volume) = self.current_builtin_f64("volume") else {
            self.update_mfi_windows(call_site_id, None, None, length);
            return Ok(PineValue::Na);
        };
        let Some(series_id) = source_arg.and_then(|arg| arg.series_id) else {
            self.update_mfi_windows(call_site_id, None, None, length);
            return Ok(PineValue::Na);
        };

        let (positive_flow, negative_flow) =
            match self.read_declared_series_history(series_id, 1).as_f64() {
                Some(previous) if source > previous => (Some(source * volume), Some(0.0)),
                Some(previous) if source < previous => (Some(0.0), Some(source * volume)),
                Some(_) | None => (Some(0.0), Some(0.0)),
            };
        self.update_mfi_windows(call_site_id, positive_flow, negative_flow, length);

        let positive_window = self
            .rolling_windows
            .get(&RollingWindowKey::MfiPositive(call_site_id));
        let negative_window = self
            .rolling_windows
            .get(&RollingWindowKey::MfiNegative(call_site_id));
        let (Some(positive_window), Some(negative_window)) = (positive_window, negative_window)
        else {
            return Ok(PineValue::Na);
        };
        if !positive_window.is_ready(length) || !negative_window.is_ready(length) {
            return Ok(PineValue::Na);
        }

        let positive_sum = positive_window.sum;
        let negative_sum = negative_window.sum;
        if positive_sum == 0.0 && negative_sum == 0.0 {
            return Ok(PineValue::Na);
        }
        if negative_sum == 0.0 {
            return Ok(PineValue::Float(100.0));
        }

        Ok(finite_float_or_na(
            100.0 - 100.0 / (1.0 + positive_sum / negative_sum),
        ))
    }

    pub(crate) fn eval_vwap_source(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let has_bands = vwap_arg(args, 2, "stdev_mult").is_some();
        let source_arg = vwap_arg(args, 0, "source").ok_or_else(|| RuntimeError {
            message: "ta.vwap missing source argument".to_owned(),
        })?;
        let source = self.eval_expr(source_arg)?;
        let anchor = if let Some(arg) = vwap_arg(args, 1, "anchor") {
            matches!(self.eval_expr(arg)?, PineValue::Bool(true))
        } else {
            false
        };
        let stdev_mult = if let Some(arg) = vwap_arg(args, 2, "stdev_mult") {
            let Some(mult) = self.eval_expr(arg)?.as_f64() else {
                self.vwap_call_state.remove(&call_site_id);
                return Ok(vwap_result_na(has_bands));
            };
            Some(mult)
        } else {
            None
        };
        let (Some(source), Some(volume)) = (source.as_f64(), self.current_builtin_f64("volume"))
        else {
            self.vwap_call_state.remove(&call_site_id);
            return Ok(vwap_result_na(has_bands));
        };
        let weighted = source * volume;
        let weighted_square = source * source * volume;
        if !source.is_finite()
            || !volume.is_finite()
            || !weighted.is_finite()
            || !weighted_square.is_finite()
        {
            self.vwap_call_state.remove(&call_site_id);
            return Ok(vwap_result_na(has_bands));
        }
        if let Some(mult) = stdev_mult
            && !mult.is_finite()
        {
            self.vwap_call_state.remove(&call_site_id);
            return Ok(vwap_result_na(has_bands));
        }

        let state = self.vwap_call_state.entry(call_site_id).or_default();
        if anchor {
            *state = VwapState::default();
        }
        state.weighted_sum += weighted;
        state.weighted_square_sum += weighted_square;
        state.volume_sum += volume;
        if state.volume_sum == 0.0
            || !state.weighted_sum.is_finite()
            || !state.weighted_square_sum.is_finite()
            || !state.volume_sum.is_finite()
        {
            return Ok(vwap_result_na(has_bands));
        }

        let vwap = state.weighted_sum / state.volume_sum;
        let value = finite_float_or_na(vwap);
        let Some(mult) = stdev_mult else {
            return Ok(value);
        };
        let variance = (state.weighted_square_sum / state.volume_sum) - vwap * vwap;
        let deviation = variance.max(0.0).sqrt();
        let band = deviation * mult;
        Ok(PineValue::Tuple(vec![
            value,
            finite_float_or_na(vwap + band),
            finite_float_or_na(vwap - band),
        ]))
    }

    pub(crate) fn eval_stoch(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let source = ta_arg(args, 0, "source")
            .map(|arg| self.eval_expr(arg))
            .transpose()?
            .and_then(|value| value.as_f64());
        let high = ta_arg(args, 1, "high")
            .map(|arg| self.eval_expr(arg))
            .transpose()?
            .and_then(|value| value.as_f64());
        let low = ta_arg(args, 2, "low")
            .map(|arg| self.eval_expr(arg))
            .transpose()?
            .and_then(|value| value.as_f64());
        let length = ta_arg(args, 3, "length")
            .map(|arg| self.eval_expr(arg))
            .transpose()?
            .and_then(|value| value.as_i64())
            .unwrap_or(0);
        if length <= 0 {
            return Ok(PineValue::Na);
        }

        let length = length as usize;
        self.update_rolling_window_key(RollingWindowKey::StochHigh(call_site_id), high, length);
        self.update_rolling_window_key(RollingWindowKey::StochLow(call_site_id), low, length);

        let high_window = self
            .rolling_windows
            .get(&RollingWindowKey::StochHigh(call_site_id));
        let low_window = self
            .rolling_windows
            .get(&RollingWindowKey::StochLow(call_site_id));
        let (Some(source), Some(high_window), Some(low_window)) = (source, high_window, low_window)
        else {
            return Ok(PineValue::Na);
        };
        if !high_window.is_ready(length) || !low_window.is_ready(length) {
            return Ok(PineValue::Na);
        }

        let (Some(highest_high), Some(lowest_low)) = (
            high_window.extreme(WindowExtreme::Highest),
            low_window.extreme(WindowExtreme::Lowest),
        ) else {
            return Ok(PineValue::Na);
        };
        let range = highest_high - lowest_low;
        if range == 0.0 {
            return Ok(PineValue::Na);
        }

        Ok(finite_float_or_na(100.0 * (source - lowest_low) / range))
    }

    pub(crate) fn eval_wpr(
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

        let length = length as usize;
        let close = self.current_builtin_f64("close");
        self.update_rolling_window_key(
            RollingWindowKey::WprHigh(call_site_id),
            self.current_builtin_f64("high"),
            length,
        );
        self.update_rolling_window_key(
            RollingWindowKey::WprLow(call_site_id),
            self.current_builtin_f64("low"),
            length,
        );

        let high_window = self
            .rolling_windows
            .get(&RollingWindowKey::WprHigh(call_site_id));
        let low_window = self
            .rolling_windows
            .get(&RollingWindowKey::WprLow(call_site_id));
        let (Some(close), Some(high_window), Some(low_window)) = (close, high_window, low_window)
        else {
            return Ok(PineValue::Na);
        };
        if !high_window.is_ready(length) || !low_window.is_ready(length) {
            return Ok(PineValue::Na);
        }

        let (Some(highest_high), Some(lowest_low)) = (
            high_window.extreme(WindowExtreme::Highest),
            low_window.extreme(WindowExtreme::Lowest),
        ) else {
            return Ok(PineValue::Na);
        };
        let range = highest_high - lowest_low;
        if range == 0.0 {
            return Ok(PineValue::Na);
        }

        Ok(finite_float_or_na(-100.0 * (highest_high - close) / range))
    }

    pub(crate) fn eval_ao(&mut self, call_site_id: CallSiteId) -> Result<PineValue, RuntimeError> {
        let source = match (
            self.current_builtin_f64("high"),
            self.current_builtin_f64("low"),
        ) {
            (Some(high), Some(low)) => Some((high + low) / 2.0),
            _ => None,
        };

        self.update_rolling_window_key(RollingWindowKey::AoFast(call_site_id), source, 5);
        self.update_rolling_window_key(RollingWindowKey::AoSlow(call_site_id), source, 34);

        let fast_window = self
            .rolling_windows
            .get(&RollingWindowKey::AoFast(call_site_id));
        let slow_window = self
            .rolling_windows
            .get(&RollingWindowKey::AoSlow(call_site_id));
        let (Some(fast_window), Some(slow_window)) = (fast_window, slow_window) else {
            return Ok(PineValue::Na);
        };
        if !fast_window.is_ready(5) || !slow_window.is_ready(34) {
            return Ok(PineValue::Na);
        }

        Ok(finite_float_or_na(
            fast_window.mean(5) - slow_window.mean(34),
        ))
    }

    pub(crate) fn eval_bop(&self) -> Result<PineValue, RuntimeError> {
        let (Some(open), Some(high), Some(low), Some(close)) = (
            self.current_builtin_f64("open"),
            self.current_builtin_f64("high"),
            self.current_builtin_f64("low"),
            self.current_builtin_f64("close"),
        ) else {
            return Ok(PineValue::Na);
        };

        let range = high - low;
        if range == 0.0 {
            return Ok(PineValue::Na);
        }

        Ok(finite_float_or_na((close - open) / range))
    }

    pub(crate) fn eval_rising_falling(
        &mut self,
        _call_site_id: CallSiteId,
        args: &[HirCallArg],
        mode: RisingFallingMode,
    ) -> Result<PineValue, RuntimeError> {
        let Some(source_arg) = ta_arg(args, 0, "source") else {
            return Ok(PineValue::Bool(false));
        };
        let source = self.eval_expr(source_arg)?;
        let length = ta_arg(args, 1, "length")
            .map(|arg| self.eval_expr(arg))
            .transpose()?
            .and_then(|value| value.as_i64())
            .unwrap_or(0);
        if length <= 0 {
            return Ok(PineValue::Bool(false));
        }

        let length = length as usize;
        let Some(current) = source.as_f64() else {
            return Ok(PineValue::Bool(false));
        };
        let Some(series_id) = source_arg.series_id else {
            return Ok(PineValue::Bool(false));
        };
        for offset in 1..=length {
            let Some(previous) = self.series_store.read(series_id, offset).as_f64() else {
                return Ok(PineValue::Bool(false));
            };
            let trending = match mode {
                RisingFallingMode::Rising => current > previous,
                RisingFallingMode::Falling => current < previous,
            };
            if !trending {
                return Ok(PineValue::Bool(false));
            }
        }

        Ok(PineValue::Bool(true))
    }

    pub(crate) fn eval_cross(
        &mut self,
        args: &[HirCallArg],
        mode: CrossMode,
    ) -> Result<PineValue, RuntimeError> {
        let Some(left_arg) = ta_arg(args, 0, "source1") else {
            return Ok(PineValue::Bool(false));
        };
        let Some(right_arg) = ta_arg(args, 1, "source2") else {
            return Ok(PineValue::Bool(false));
        };
        let current_left = self.eval_expr(left_arg)?;
        let current_right = self.eval_expr(right_arg)?;
        let Some(left_series_id) = left_arg.series_id else {
            return Ok(PineValue::Bool(false));
        };
        let previous_left = self.read_declared_series_history(left_series_id, 1);
        let previous_right = if let Some(right_series_id) = right_arg.series_id {
            self.read_declared_series_history(right_series_id, 1)
        } else {
            current_right.clone()
        };

        let Some(current_left) = current_left.as_f64() else {
            return Ok(PineValue::Bool(false));
        };
        let Some(current_right) = current_right.as_f64() else {
            return Ok(PineValue::Bool(false));
        };
        let Some(previous_left) = previous_left.as_f64() else {
            return Ok(PineValue::Bool(false));
        };
        let Some(previous_right) = previous_right.as_f64() else {
            return Ok(PineValue::Bool(false));
        };

        let crossed_over = current_left > current_right && previous_left <= previous_right;
        let crossed_under = current_left < current_right && previous_left >= previous_right;
        Ok(PineValue::Bool(match mode {
            CrossMode::Any => crossed_over || crossed_under,
            CrossMode::Over => crossed_over,
            CrossMode::Under => crossed_under,
        }))
    }

    pub(crate) fn eval_barssince(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let condition = ta_arg(args, 0, "condition")
            .map(|arg| self.eval_expr(arg))
            .transpose()?
            .unwrap_or(PineValue::Na);
        let value = if matches!(condition, PineValue::Bool(true)) {
            PineValue::Int(0)
        } else if let Some(previous) = self
            .call_state
            .get(&call_site_id)
            .and_then(PineValue::as_i64)
        {
            PineValue::Int(previous + 1)
        } else {
            PineValue::Na
        };

        if matches!(value, PineValue::Int(_)) {
            self.call_state.insert(call_site_id, value.clone());
        }
        Ok(value)
    }

    pub(crate) fn eval_valuewhen(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let condition = ta_arg(args, 0, "condition")
            .map(|arg| self.eval_expr(arg))
            .transpose()?
            .unwrap_or(PineValue::Na);
        let source = ta_arg(args, 1, "source")
            .map(|arg| self.eval_expr(arg))
            .transpose()?
            .unwrap_or(PineValue::Na);
        let occurrence_arg = ta_arg(args, 2, "occurrence");
        let occurrence = occurrence_arg
            .map(|arg| self.eval_expr(arg))
            .transpose()?
            .and_then(|value| value.as_i64())
            .unwrap_or(-1);

        if matches!(condition, PineValue::Bool(true)) {
            let retain = if occurrence_arg
                .is_some_and(|arg| arg.pine_type.qualifier == pine_ir::Qualifier::Series)
            {
                MAX_SERIES_HISTORY_VALUES
            } else if occurrence >= 0 && (occurrence as usize) < MAX_SERIES_HISTORY_VALUES {
                occurrence as usize + 1
            } else {
                0
            };

            let values = self.valuewhen_state.entry(call_site_id).or_default();
            values.push_front(source);
            values.truncate(retain);
        }

        if occurrence < 0 {
            return Ok(PineValue::Na);
        }

        let occurrence = occurrence as usize;
        if occurrence >= MAX_SERIES_HISTORY_VALUES {
            return Ok(PineValue::Na);
        }

        Ok(self
            .valuewhen_state
            .get(&call_site_id)
            .and_then(|values| values.get(occurrence))
            .cloned()
            .unwrap_or(PineValue::Na))
    }

    pub(crate) fn eval_window_extreme(
        &mut self,
        _call_site_id: CallSiteId,
        args: &[HirCallArg],
        mode: WindowExtreme,
    ) -> Result<PineValue, RuntimeError> {
        let (source, series_id, length) = self.eval_extreme_source_length(args, mode)?;
        if length <= 0 {
            return Ok(PineValue::Na);
        }

        let Some(length) = usize::try_from(length).ok() else {
            return Ok(PineValue::Na);
        };
        self.window_extreme_value(source, series_id, length, mode)
            .map_or(Ok(PineValue::Na), |value| Ok(finite_float_or_na(value)))
    }

    pub(crate) fn eval_window_extreme_offset(
        &mut self,
        _call_site_id: CallSiteId,
        args: &[HirCallArg],
        mode: WindowExtreme,
    ) -> Result<PineValue, RuntimeError> {
        let (source, series_id, length) = self.eval_extreme_source_length(args, mode)?;
        if length <= 0 {
            return Ok(PineValue::Na);
        }

        let Some(length) = usize::try_from(length).ok() else {
            return Ok(PineValue::Na);
        };
        Ok(self
            .window_extreme_offset(source, series_id, length, mode)
            .map_or(PineValue::Na, |offset| PineValue::Int(offset as i64)))
    }

    pub(crate) fn eval_extreme_source_length(
        &mut self,
        args: &[HirCallArg],
        mode: WindowExtreme,
    ) -> Result<(PineValue, Option<SeriesId>, i64), RuntimeError> {
        let has_explicit_source = args.iter().any(|arg| arg.name.as_deref() == Some("source"))
            || args
                .first()
                .is_some_and(|arg| arg.name.is_none() && args.len() > 1);

        if has_explicit_source {
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
            return Ok((source, source_arg.and_then(|arg| arg.series_id), length));
        }

        let length = ta_arg(args, 0, "length")
            .map(|arg| self.eval_expr(arg))
            .transpose()?
            .and_then(|value| value.as_i64())
            .unwrap_or(0);
        let source_name = match mode {
            WindowExtreme::Highest => "high",
            WindowExtreme::Lowest => "low",
        };
        let source = self
            .current_builtin_f64(source_name)
            .map_or(PineValue::Na, PineValue::Float);
        Ok((source, self.builtin_series_id(source_name), length))
    }

    fn window_extreme_value(
        &self,
        source: PineValue,
        series_id: Option<SeriesId>,
        length: usize,
        mode: WindowExtreme,
    ) -> Option<f64> {
        let mut extreme = finite_f64(source)?;
        let series_id = series_id?;
        for offset in 1..length {
            let previous = finite_f64(self.series_store.read(series_id, offset))?;
            extreme = match mode {
                WindowExtreme::Highest => extreme.max(previous),
                WindowExtreme::Lowest => extreme.min(previous),
            };
        }
        Some(extreme)
    }

    fn window_extreme_offset(
        &self,
        source: PineValue,
        series_id: Option<SeriesId>,
        length: usize,
        mode: WindowExtreme,
    ) -> Option<usize> {
        let mut extreme = finite_f64(source)?;
        let mut best_offset = 0usize;
        let series_id = series_id?;
        for offset in 1..length {
            let previous = finite_f64(self.series_store.read(series_id, offset))?;
            let better = match mode {
                WindowExtreme::Highest => previous > extreme,
                WindowExtreme::Lowest => previous < extreme,
            };
            if better {
                extreme = previous;
                best_offset = offset;
            }
        }
        Some(best_offset)
    }

    fn builtin_series_id(&self, name: &str) -> Option<SeriesId> {
        self.program
            .symbols
            .iter()
            .find(|symbol| symbol.name == name)
            .and_then(|symbol| symbol.series_id)
    }

    pub(crate) fn update_rolling_window(
        &mut self,
        call_site_id: CallSiteId,
        source: PineValue,
        length: usize,
    ) -> &RollingWindowState {
        let source = source.as_f64();
        self.update_rolling_window_key(RollingWindowKey::Single(call_site_id), source, length)
    }

    pub(crate) fn update_mfi_windows(
        &mut self,
        call_site_id: CallSiteId,
        positive_flow: Option<f64>,
        negative_flow: Option<f64>,
        length: usize,
    ) {
        self.update_rolling_window_key(
            RollingWindowKey::MfiPositive(call_site_id),
            positive_flow,
            length,
        );
        self.update_rolling_window_key(
            RollingWindowKey::MfiNegative(call_site_id),
            negative_flow,
            length,
        );
    }

    pub(crate) fn update_rolling_window_key(
        &mut self,
        key: RollingWindowKey,
        source: Option<f64>,
        length: usize,
    ) -> &RollingWindowState {
        let window = self.rolling_windows.entry(key).or_default();
        window.push(source.filter(|value| value.is_finite()), length);
        window
    }
}

fn finite_f64(value: PineValue) -> Option<f64> {
    value.as_f64().filter(|value| value.is_finite())
}
