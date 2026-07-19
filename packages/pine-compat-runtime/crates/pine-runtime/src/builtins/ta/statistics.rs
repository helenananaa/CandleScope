use super::*;

impl<'a> HistoricalRuntime<'a> {
    pub(crate) fn eval_rci(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let (source, length) = self.eval_source_length(args)?;
        if length < 2 {
            return Ok(PineValue::Na);
        }

        let length = length as usize;
        let window = self.update_rolling_window(call_site_id, source, length);
        if !window.is_ready(length) {
            return Ok(PineValue::Na);
        }

        let mut ranked: Vec<_> = window
            .values
            .iter()
            .flatten()
            .copied()
            .enumerate()
            .collect();
        ranked.sort_by(|left, right| left.1.total_cmp(&right.1));

        let mut price_ranks = vec![0.0; length];
        let mut start = 0;
        while start < length {
            let mut end = start + 1;
            while end < length && ranked[end].1 == ranked[start].1 {
                end += 1;
            }

            let average_rank = (start + 1 + end) as f64 / 2.0;
            for &(original_index, _) in &ranked[start..end] {
                price_ranks[original_index] = average_rank;
            }
            start = end;
        }

        let squared_rank_difference = price_ranks
            .iter()
            .enumerate()
            .map(|(index, price_rank)| {
                let difference = *price_rank - (index + 1) as f64;
                difference * difference
            })
            .sum::<f64>();
        let length = length as f64;
        let rci =
            (1.0 - 6.0 * squared_rank_difference / (length * (length * length - 1.0))) * 100.0;
        Ok(finite_float_or_na(rci))
    }

    pub(crate) fn eval_stdev(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        match self.eval_window_variance(call_site_id, args)? {
            PineValue::Float(value) => Ok(finite_float_or_na(value.sqrt())),
            value => Ok(value),
        }
    }

    pub(crate) fn eval_variance(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        self.eval_window_variance(call_site_id, args)
    }

    pub(crate) fn eval_range(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let (source, length) = self.eval_source_length(args)?;
        if length <= 0 {
            return Ok(PineValue::Na);
        }

        let length = length as usize;
        let window = self.update_rolling_window(call_site_id, source, length);
        if !window.is_ready(length) {
            return Ok(PineValue::Na);
        }

        Ok(window.range().map_or(PineValue::Na, PineValue::Float))
    }

    pub(crate) fn eval_dev(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let (source, length) = self.eval_source_length(args)?;
        if length <= 0 {
            return Ok(PineValue::Na);
        }

        let length = length as usize;
        let window = self.update_rolling_window(call_site_id, source, length);
        if !window.is_ready(length) {
            return Ok(PineValue::Na);
        }

        Ok(finite_float_or_na(window.mean_absolute_deviation(length)))
    }

    fn eval_source_length(
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

    pub(crate) fn eval_correlation(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let (left, right, length) = self.eval_pair_sources_length(args)?;
        if length <= 0 {
            return Ok(PineValue::Na);
        }

        let length = length as usize;
        let left = left.as_f64();
        let right = right.as_f64();
        let product = left.zip(right).map(|(left, right)| left * right);
        self.update_rolling_window_key(
            RollingWindowKey::CorrelationLeft(call_site_id),
            left,
            length,
        );
        self.update_rolling_window_key(
            RollingWindowKey::CorrelationRight(call_site_id),
            right,
            length,
        );
        self.update_rolling_window_key(
            RollingWindowKey::CorrelationProduct(call_site_id),
            product,
            length,
        );

        let left = self
            .rolling_windows
            .get(&RollingWindowKey::CorrelationLeft(call_site_id));
        let right = self
            .rolling_windows
            .get(&RollingWindowKey::CorrelationRight(call_site_id));
        let product = self
            .rolling_windows
            .get(&RollingWindowKey::CorrelationProduct(call_site_id));
        let (Some(left), Some(right), Some(product)) = (left, right, product) else {
            return Ok(PineValue::Na);
        };
        if !left.is_ready(length) || !right.is_ready(length) || !product.is_ready(length) {
            return Ok(PineValue::Na);
        }

        let left_variance = left.variance(length, true);
        let right_variance = right.variance(length, true);
        let denominator = (left_variance * right_variance).sqrt();
        if denominator == 0.0 || !denominator.is_finite() {
            return Ok(PineValue::Na);
        }

        let covariance = product.mean(length) - (left.mean(length) * right.mean(length));
        Ok(finite_float_or_na(covariance / denominator))
    }

    pub(crate) fn eval_covariance(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let (left, right, length) = self.eval_pair_sources_length(args)?;
        if length <= 0 {
            return Ok(PineValue::Na);
        }

        let length = length as usize;
        let left = left.as_f64();
        let right = right.as_f64();
        let product = left.zip(right).map(|(left, right)| left * right);
        self.update_rolling_window_key(
            RollingWindowKey::CovarianceLeft(call_site_id),
            left,
            length,
        );
        self.update_rolling_window_key(
            RollingWindowKey::CovarianceRight(call_site_id),
            right,
            length,
        );
        self.update_rolling_window_key(
            RollingWindowKey::CovarianceProduct(call_site_id),
            product,
            length,
        );

        let left = self
            .rolling_windows
            .get(&RollingWindowKey::CovarianceLeft(call_site_id));
        let right = self
            .rolling_windows
            .get(&RollingWindowKey::CovarianceRight(call_site_id));
        let product = self
            .rolling_windows
            .get(&RollingWindowKey::CovarianceProduct(call_site_id));
        let (Some(left), Some(right), Some(product)) = (left, right, product) else {
            return Ok(PineValue::Na);
        };
        if !left.is_ready(length) || !right.is_ready(length) || !product.is_ready(length) {
            return Ok(PineValue::Na);
        }

        let covariance = product.mean(length) - (left.mean(length) * right.mean(length));
        Ok(finite_float_or_na(covariance))
    }

    fn eval_pair_sources_length(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<(PineValue, PineValue, i64), RuntimeError> {
        let left = ta_arg(args, 0, "source1")
            .map(|arg| self.eval_expr(arg))
            .transpose()?
            .unwrap_or(PineValue::Na);
        let right = ta_arg(args, 1, "source2")
            .map(|arg| self.eval_expr(arg))
            .transpose()?
            .unwrap_or(PineValue::Na);
        let length = ta_arg(args, 2, "length")
            .map(|arg| self.eval_expr(arg))
            .transpose()?
            .and_then(|value| value.as_i64())
            .unwrap_or(0);
        Ok((left, right, length))
    }

    pub(crate) fn eval_median(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let (source, length) = self.eval_source_length(args)?;
        if length <= 0 {
            return Ok(PineValue::Na);
        }

        let length = length as usize;
        let window = self.update_rolling_window(call_site_id, source, length);
        if !window.is_ready(length) {
            return Ok(PineValue::Na);
        }

        let mut values: Vec<_> = window.values.iter().flatten().copied().collect();
        values.sort_by(|left, right| left.partial_cmp(right).unwrap_or(Ordering::Equal));
        let middle = values.len() / 2;
        let median = if values.len() % 2 == 0 {
            (values[middle - 1] + values[middle]) / 2.0
        } else {
            values[middle]
        };
        Ok(finite_float_or_na(median))
    }

    pub(crate) fn eval_mode(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let (source, length) = self.eval_source_length(args)?;
        if length <= 0 {
            return Ok(PineValue::Na);
        }

        let length = length as usize;
        let window = self.update_rolling_window(call_site_id, source, length);
        if !window.is_ready(length) {
            return Ok(PineValue::Na);
        }

        let mut values: Vec<_> = window.values.iter().flatten().copied().collect();
        values.sort_by(|left, right| left.partial_cmp(right).unwrap_or(Ordering::Equal));

        let mut best_value = values[0];
        let mut best_count = 0_usize;
        let mut current_value = values[0];
        let mut current_count = 0_usize;
        for value in values {
            if (value - current_value).abs() < f64::EPSILON {
                current_count += 1;
            } else {
                if current_count > best_count {
                    best_value = current_value;
                    best_count = current_count;
                }
                current_value = value;
                current_count = 1;
            }
        }
        if current_count > best_count {
            best_value = current_value;
        }

        Ok(finite_float_or_na(best_value))
    }

    pub(crate) fn eval_percentile(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
        mode: ArrayPercentileMode,
    ) -> Result<PineValue, RuntimeError> {
        let (source, length, percentage) = self.eval_percentile_source_length_percentage(args)?;
        if length <= 0 {
            return Ok(PineValue::Na);
        }
        let Some(percentage) = percentage else {
            return Ok(PineValue::Na);
        };
        if !(0.0..=100.0).contains(&percentage) {
            return Ok(PineValue::Na);
        }

        let length = length as usize;
        let window = self.update_rolling_window(call_site_id, source, length);
        if !window.is_ready(length) {
            return Ok(PineValue::Na);
        }

        let mut values: Vec<_> = window.values.iter().flatten().copied().collect();
        values.sort_by(|left, right| left.partial_cmp(right).unwrap_or(Ordering::Equal));
        match mode {
            ArrayPercentileMode::NearestRank => {
                let rank = ((percentage / 100.0) * values.len() as f64).ceil();
                let index = (rank as usize).saturating_sub(1).min(values.len() - 1);
                Ok(finite_float_or_na(values[index]))
            }
            ArrayPercentileMode::LinearInterpolation => {
                if values.len() == 1 {
                    return Ok(finite_float_or_na(values[0]));
                }
                let rank = (percentage / 100.0) * (values.len() - 1) as f64;
                let lower = rank.floor() as usize;
                let upper = rank.ceil() as usize;
                let fraction = rank - lower as f64;
                let value = values[lower] + (values[upper] - values[lower]) * fraction;
                Ok(finite_float_or_na(value))
            }
        }
    }

    pub(crate) fn eval_percentrank(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let (source, length) = self.eval_source_length(args)?;
        if length <= 0 {
            return Ok(PineValue::Na);
        }

        let length = length as usize;
        let target = source.as_f64();
        let window = self.update_rolling_window(call_site_id, source, length);
        let Some(target) = target else {
            return Ok(PineValue::Na);
        };
        if !window.is_ready(length) {
            return Ok(PineValue::Na);
        }

        let count = window
            .values
            .iter()
            .flatten()
            .filter(|value| **value <= target || (**value - target).abs() < f64::EPSILON)
            .count();
        Ok(finite_float_or_na(count as f64 / length as f64 * 100.0))
    }

    pub(crate) fn eval_window_variance(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let (source, length) = self.eval_source_length(args)?;
        let biased = if let Some(arg) = ta_arg(args, 2, "biased") {
            matches!(self.eval_expr(arg)?, PineValue::Bool(true))
        } else {
            true
        };
        if length <= 0 {
            return Ok(PineValue::Na);
        }

        let length = length as usize;
        let window = self.update_rolling_window(call_site_id, source, length);
        if !window.is_ready(length) || (!biased && length < 2) {
            return Ok(PineValue::Na);
        }

        Ok(finite_float_or_na(window.variance(length, biased)))
    }

    fn eval_percentile_source_length_percentage(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<(PineValue, i64, Option<f64>), RuntimeError> {
        let (source, length) = self.eval_source_length(args)?;
        let percentage = ta_arg(args, 2, "percentage")
            .map(|arg| self.eval_expr(arg))
            .transpose()?
            .and_then(|value| value.as_f64());
        Ok((source, length, percentage))
    }
}
