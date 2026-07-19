use super::*;

impl<'a> HistoricalRuntime<'a> {
    pub(crate) fn eval_pivot(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
        mode: WindowExtreme,
    ) -> Result<PineValue, RuntimeError> {
        let (source, leftbars, rightbars) = self.eval_pivot_args(args, mode)?;
        if leftbars < 0 || rightbars < 0 {
            return Ok(PineValue::Na);
        }

        let leftbars = leftbars as usize;
        let rightbars = rightbars as usize;
        let length = leftbars + rightbars + 1;
        let window = self.update_rolling_window(call_site_id, source, length);
        if !window.is_ready(length) {
            return Ok(PineValue::Na);
        }

        let candidate_index = length - 1 - rightbars;
        let candidate = window.values.get(candidate_index).and_then(|value| *value);
        let Some(candidate) = candidate else {
            return Ok(PineValue::Na);
        };

        let is_pivot = window
            .values
            .iter()
            .flatten()
            .enumerate()
            .all(|(index, value)| {
                index == candidate_index
                    || match mode {
                        WindowExtreme::Highest => candidate > *value,
                        WindowExtreme::Lowest => candidate < *value,
                    }
            });
        if !is_pivot {
            return Ok(PineValue::Na);
        }

        Ok(finite_float_or_na(candidate))
    }

    pub(crate) fn eval_pivot_args(
        &mut self,
        args: &[HirCallArg],
        mode: WindowExtreme,
    ) -> Result<(PineValue, i64, i64), RuntimeError> {
        if args.len() == 2 {
            let leftbars = ta_arg(args, 0, "leftbars")
                .map(|arg| self.eval_expr(arg))
                .transpose()?
                .and_then(|value| value.as_i64())
                .unwrap_or(-1);
            let rightbars = ta_arg(args, 1, "rightbars")
                .map(|arg| self.eval_expr(arg))
                .transpose()?
                .and_then(|value| value.as_i64())
                .unwrap_or(-1);
            let source_name = match mode {
                WindowExtreme::Highest => "high",
                WindowExtreme::Lowest => "low",
            };
            let source = self
                .current_builtin_f64(source_name)
                .map_or(PineValue::Na, PineValue::Float);
            return Ok((source, leftbars, rightbars));
        }

        let source = ta_arg(args, 0, "source")
            .map(|arg| self.eval_expr(arg))
            .transpose()?
            .unwrap_or(PineValue::Na);
        let leftbars = ta_arg(args, 1, "leftbars")
            .map(|arg| self.eval_expr(arg))
            .transpose()?
            .and_then(|value| value.as_i64())
            .unwrap_or(-1);
        let rightbars = ta_arg(args, 2, "rightbars")
            .map(|arg| self.eval_expr(arg))
            .transpose()?
            .and_then(|value| value.as_i64())
            .unwrap_or(-1);
        Ok((source, leftbars, rightbars))
    }

    pub(crate) fn eval_pivot_point_levels(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let type_arg = pivot_point_arg(args, 0, "type").ok_or_else(|| RuntimeError {
            message: "ta.pivot_point_levels missing type argument".to_owned(),
        })?;
        let anchor_arg = pivot_point_arg(args, 1, "anchor").ok_or_else(|| RuntimeError {
            message: "ta.pivot_point_levels missing anchor argument".to_owned(),
        })?;
        let PineValue::String(type_name) = self.eval_expr(type_arg)? else {
            return Ok(self.new_array_from_values(ArrayElementKind::Float, pivot_na_levels()));
        };
        let anchor = matches!(self.eval_expr(anchor_arg)?, PineValue::Bool(true));
        let developing = if let Some(arg) = pivot_point_arg(args, 2, "developing") {
            matches!(self.eval_expr(arg)?, PineValue::Bool(true))
        } else {
            false
        };

        let (Some(open), Some(high), Some(low), Some(close)) = (
            self.current_builtin_f64("open"),
            self.current_builtin_f64("high"),
            self.current_builtin_f64("low"),
            self.current_builtin_f64("close"),
        ) else {
            return Ok(self.new_array_from_values(ArrayElementKind::Float, pivot_na_levels()));
        };
        if !open.is_finite() || !high.is_finite() || !low.is_finite() || !close.is_finite() {
            return Ok(self.new_array_from_values(ArrayElementKind::Float, pivot_na_levels()));
        }

        let state = self.pivot_point_state.entry(call_site_id).or_default();
        if anchor {
            if let Some(previous) = state.current {
                state.active_levels = Some(pivot_point_levels(&type_name, previous, open));
            }
            state.current = Some(PivotPointPeriod::new(open, high, low, close));
        } else if let Some(current) = &mut state.current {
            current.update(high, low, close);
        } else {
            state.current = Some(PivotPointPeriod::new(open, high, low, close));
        }

        let levels = if developing {
            state
                .current
                .map(|current| pivot_point_levels(&type_name, current, current.open))
        } else {
            state.active_levels.clone()
        }
        .unwrap_or_else(pivot_na_levels);

        Ok(self.new_array_from_values(ArrayElementKind::Float, levels))
    }
}
