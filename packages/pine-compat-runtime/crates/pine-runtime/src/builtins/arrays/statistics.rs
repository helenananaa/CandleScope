use std::cmp::Ordering;

use super::*;
use crate::builtins::args::call_arg_expr;

impl<'a> HistoricalRuntime<'a> {
    pub(crate) fn eval_array_includes(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let index = self.eval_array_search(args, ArraySearchMode::First)?;
        Ok(PineValue::Bool(index.is_some()))
    }

    pub(crate) fn eval_array_truth(
        &mut self,
        args: &[HirCallArg],
        mode: ArrayTruthMode,
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_expr(&args[0].value)?;
        let PineValue::Array(id) = id else {
            return Ok(PineValue::Na);
        };
        let Some(kind) = self.array_kinds.get(&id).copied() else {
            return Ok(PineValue::Na);
        };
        if !matches!(
            kind,
            ArrayElementKind::Float | ArrayElementKind::Int | ArrayElementKind::Bool
        ) {
            return Ok(PineValue::Na);
        }
        let Some(values) = self.array_values_clone(id)? else {
            return Ok(PineValue::Na);
        };
        let result = match mode {
            ArrayTruthMode::Every => values.iter().all(array_truthy_value),
            ArrayTruthMode::Some => values.iter().any(array_truthy_value),
        };
        Ok(PineValue::Bool(result))
    }

    pub(crate) fn eval_array_indexof(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let index = self
            .eval_array_search(args, ArraySearchMode::First)?
            .map_or(-1, |index| index as i64);
        Ok(PineValue::Int(index))
    }

    pub(crate) fn eval_array_lastindexof(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let index = self
            .eval_array_search(args, ArraySearchMode::Last)?
            .map_or(-1, |index| index as i64);
        Ok(PineValue::Int(index))
    }

    pub(crate) fn eval_array_search(
        &mut self,
        args: &[HirCallArg],
        mode: ArraySearchMode,
    ) -> Result<Option<usize>, RuntimeError> {
        let id = self.eval_expr(&args[0].value)?;
        let PineValue::Array(id) = id else {
            let _ = self.eval_expr(&args[1].value)?;
            return Ok(None);
        };
        let Some(kind) = self.array_kinds.get(&id).copied() else {
            let _ = self.eval_expr(&args[1].value)?;
            return Ok(None);
        };
        let value = self.eval_array_value(&args[1].value, kind)?;
        let Some(values) = self.array_values_clone(id)? else {
            return Ok(None);
        };
        let index = match mode {
            ArraySearchMode::First => values.iter().position(|item| values_equal(item, &value)),
            ArraySearchMode::Last => values.iter().rposition(|item| values_equal(item, &value)),
        };
        Ok(index)
    }

    pub(crate) fn eval_array_binary_search(
        &mut self,
        args: &[HirCallArg],
        mode: ArrayBinarySearchMode,
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_expr(&args[0].value)?;
        let PineValue::Array(id) = id else {
            let _ = self.eval_expr(&args[1].value)?;
            return Ok(PineValue::Int(-1));
        };
        let Some(kind) = self.array_kinds.get(&id).copied() else {
            let _ = self.eval_expr(&args[1].value)?;
            return Ok(PineValue::Int(-1));
        };
        if !matches!(kind, ArrayElementKind::Float | ArrayElementKind::Int) {
            let _ = self.eval_expr(&args[1].value)?;
            return Ok(PineValue::Int(-1));
        }
        let value = self.eval_array_value(&args[1].value, kind)?;
        let Some(values) = self.array_values_clone(id)? else {
            return Ok(PineValue::Int(-1));
        };
        if values.is_empty() {
            return Ok(PineValue::Int(-1));
        }

        let lower = array_numeric_lower_bound(&values, &value);
        let exact_match =
            lower < values.len() && compare_array_numeric_values(&values[lower], &value).is_eq();
        let index = match mode {
            ArrayBinarySearchMode::Exact => exact_match.then_some(lower),
            ArrayBinarySearchMode::Leftmost => {
                if exact_match || lower == 0 {
                    Some(lower.min(values.len() - 1))
                } else {
                    Some(lower - 1)
                }
            }
            ArrayBinarySearchMode::Rightmost => {
                if exact_match {
                    Some(array_numeric_upper_bound(&values, &value) - 1)
                } else {
                    Some(lower.min(values.len() - 1))
                }
            }
        }
        .map_or(-1, |index| index as i64);

        Ok(PineValue::Int(index))
    }

    pub(crate) fn eval_array_numeric(
        &mut self,
        args: &[HirCallArg],
        mode: ArrayNumericMode,
    ) -> Result<PineValue, RuntimeError> {
        let (id, nth) = if matches!(mode, ArrayNumericMode::Min | ArrayNumericMode::Max) {
            let mut evaluated_args = Vec::with_capacity(args.len());
            for arg in args {
                evaluated_args.push(self.eval_expr(&arg.value)?);
            }

            let Some(PineValue::Array(id)) =
                evaluated_call_arg_value(args, &evaluated_args, 0, "id")
            else {
                return Ok(PineValue::Na);
            };
            let nth = match evaluated_call_arg_value(args, &evaluated_args, 1, "nth") {
                Some(PineValue::Int(nth)) => usize::try_from(*nth).ok(),
                Some(_) => None,
                None => Some(0),
            };
            let Some(nth) = nth else {
                return Ok(PineValue::Na);
            };
            (*id, Some(nth))
        } else {
            let Some(id_expr) = call_arg_expr(args, 0, "id") else {
                return Ok(PineValue::Na);
            };
            let id = self.eval_expr(id_expr)?;
            let PineValue::Array(id) = id else {
                return Ok(PineValue::Na);
            };
            (id, None)
        };
        let Some(kind) = self.array_kinds.get(&id).copied() else {
            return Ok(PineValue::Na);
        };
        if !matches!(kind, ArrayElementKind::Float | ArrayElementKind::Int) {
            return Ok(PineValue::Na);
        }
        let Some(values) = self.array_values_clone(id)? else {
            return Ok(PineValue::Na);
        };

        match mode {
            ArrayNumericMode::Min | ArrayNumericMode::Max => {
                let nth = nth.expect("min/max rank is resolved before reading the array");
                let selection_index = |len: usize| {
                    (nth < len).then(|| match mode {
                        ArrayNumericMode::Min => nth,
                        ArrayNumericMode::Max => len - nth - 1,
                        _ => unreachable!("only min/max modes are handled here"),
                    })
                };

                match kind {
                    ArrayElementKind::Int => {
                        let mut numeric_values: Vec<_> = values
                            .iter()
                            .filter_map(|value| match value {
                                PineValue::Int(value) => Some(*value),
                                _ => None,
                            })
                            .collect();
                        numeric_values.sort_unstable();
                        Ok(selection_index(numeric_values.len())
                            .and_then(|index| numeric_values.get(index))
                            .copied()
                            .map_or(PineValue::Na, PineValue::Int))
                    }
                    ArrayElementKind::Float => {
                        let mut numeric_values: Vec<_> =
                            values.iter().filter_map(PineValue::as_f64).collect();
                        numeric_values.sort_by(|left, right| {
                            left.partial_cmp(right).unwrap_or(Ordering::Equal)
                        });
                        Ok(selection_index(numeric_values.len())
                            .and_then(|index| numeric_values.get(index))
                            .copied()
                            .map_or(PineValue::Na, finite_float_or_na))
                    }
                    _ => Ok(PineValue::Na),
                }
            }
            ArrayNumericMode::Range => {
                let mut min: Option<f64> = None;
                let mut max: Option<f64> = None;
                for value in values.iter().filter_map(PineValue::as_f64) {
                    min = Some(min.map_or(value, |current| current.min(value)));
                    max = Some(max.map_or(value, |current| current.max(value)));
                }
                let (Some(min), Some(max)) = (min, max) else {
                    return Ok(PineValue::Na);
                };
                Ok(array_numeric_result(kind, max - min))
            }
            ArrayNumericMode::Sum | ArrayNumericMode::Avg => {
                let mut total = 0.0;
                let mut count = 0_usize;
                for value in values.iter().filter_map(PineValue::as_f64) {
                    total += value;
                    count += 1;
                }
                if count == 0 {
                    return Ok(PineValue::Na);
                }
                if matches!(mode, ArrayNumericMode::Avg) {
                    Ok(finite_float_or_na(total / count as f64))
                } else {
                    Ok(array_numeric_result(kind, total))
                }
            }
            ArrayNumericMode::Median => {
                let mut numeric_values: Vec<_> =
                    values.iter().filter_map(PineValue::as_f64).collect();
                if numeric_values.is_empty() {
                    return Ok(PineValue::Na);
                }
                numeric_values
                    .sort_by(|left, right| left.partial_cmp(right).unwrap_or(Ordering::Equal));
                let middle = numeric_values.len() / 2;
                let median = if numeric_values.len() % 2 == 0 {
                    (numeric_values[middle - 1] + numeric_values[middle]) / 2.0
                } else {
                    numeric_values[middle]
                };
                Ok(array_numeric_result(kind, median))
            }
            ArrayNumericMode::Mode => {
                let mut numeric_values: Vec<_> =
                    values.iter().filter_map(PineValue::as_f64).collect();
                if numeric_values.is_empty() {
                    return Ok(PineValue::Na);
                }
                numeric_values
                    .sort_by(|left, right| left.partial_cmp(right).unwrap_or(Ordering::Equal));

                let mut best_value = numeric_values[0];
                let mut best_count = 0_usize;
                let mut current_value = numeric_values[0];
                let mut current_count = 0_usize;
                for value in numeric_values {
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
                    best_count = current_count;
                }
                if best_count < 2 {
                    return Ok(PineValue::Na);
                }
                Ok(array_numeric_result(kind, best_value))
            }
        }
    }

    pub(crate) fn eval_array_abs(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_expr(&args[0].value)?;
        let PineValue::Array(id) = id else {
            return Ok(PineValue::Na);
        };
        let Some(kind) = self.array_kinds.get(&id).copied() else {
            return Ok(PineValue::Na);
        };
        if !matches!(kind, ArrayElementKind::Float | ArrayElementKind::Int) {
            return Ok(PineValue::Na);
        }
        let Some(values) = self.array_values_clone(id)? else {
            return Ok(PineValue::Na);
        };

        let values = values
            .iter()
            .map(|value| match (kind, value) {
                (_, PineValue::Na) => PineValue::Na,
                (ArrayElementKind::Int, PineValue::Int(value)) => value
                    .checked_abs()
                    .map(PineValue::Int)
                    .unwrap_or(PineValue::Na),
                (ArrayElementKind::Float, PineValue::Float(value)) => {
                    finite_float_or_na(value.abs())
                }
                (ArrayElementKind::Float, PineValue::Int(value)) => {
                    finite_float_or_na((*value as f64).abs())
                }
                _ => PineValue::Na,
            })
            .collect();

        Ok(self.new_array_from_values(kind, values))
    }

    pub(crate) fn eval_array_percentile(
        &mut self,
        args: &[HirCallArg],
        mode: ArrayPercentileMode,
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_expr(&args[0].value)?;
        let percentage = self.eval_expr(&args[1].value)?.as_f64();
        let PineValue::Array(id) = id else {
            return Ok(PineValue::Na);
        };
        let Some(percentage) = percentage else {
            return Ok(PineValue::Na);
        };
        if !(0.0..=100.0).contains(&percentage) {
            return Ok(PineValue::Na);
        }
        let Some(kind) = self.array_kinds.get(&id).copied() else {
            return Ok(PineValue::Na);
        };
        if !matches!(kind, ArrayElementKind::Float | ArrayElementKind::Int) {
            return Ok(PineValue::Na);
        }
        let Some(values) = self.array_values_clone(id)? else {
            return Ok(PineValue::Na);
        };
        let mut numeric_values: Vec<_> = values.iter().filter_map(PineValue::as_f64).collect();
        if numeric_values.is_empty() {
            return Ok(PineValue::Na);
        }
        numeric_values.sort_by(|left, right| left.partial_cmp(right).unwrap_or(Ordering::Equal));

        match mode {
            ArrayPercentileMode::NearestRank => {
                let rank = ((percentage / 100.0) * numeric_values.len() as f64).ceil();
                let index = (rank as usize)
                    .saturating_sub(1)
                    .min(numeric_values.len() - 1);
                Ok(array_numeric_result(kind, numeric_values[index]))
            }
            ArrayPercentileMode::LinearInterpolation => {
                if numeric_values.len() == 1 {
                    return Ok(finite_float_or_na(numeric_values[0]));
                }
                let rank = (percentage / 100.0) * (numeric_values.len() - 1) as f64;
                let lower = rank.floor() as usize;
                let upper = rank.ceil() as usize;
                let fraction = rank - lower as f64;
                let value = numeric_values[lower]
                    + (numeric_values[upper] - numeric_values[lower]) * fraction;
                Ok(finite_float_or_na(value))
            }
        }
    }

    pub(crate) fn eval_array_percentrank(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_expr(&args[0].value)?;
        let index = self.eval_expr(&args[1].value)?.as_i64();
        let PineValue::Array(id) = id else {
            return Ok(PineValue::Na);
        };
        let Some(index) = index else {
            return Ok(PineValue::Na);
        };
        if index < 0 {
            return Ok(PineValue::Na);
        }
        let Some(kind) = self.array_kinds.get(&id).copied() else {
            return Ok(PineValue::Na);
        };
        if !matches!(kind, ArrayElementKind::Float | ArrayElementKind::Int) {
            return Ok(PineValue::Na);
        }
        let Some(values) = self.array_values_clone(id)? else {
            return Ok(PineValue::Na);
        };
        let Some(target) = values.get(index as usize).and_then(PineValue::as_f64) else {
            return Ok(PineValue::Na);
        };
        let numeric_values: Vec<_> = values.iter().filter_map(PineValue::as_f64).collect();
        if numeric_values.is_empty() {
            return Ok(PineValue::Na);
        }
        let count = numeric_values
            .iter()
            .filter(|value| **value <= target || (**value - target).abs() < f64::EPSILON)
            .count();
        Ok(finite_float_or_na(
            count as f64 / numeric_values.len() as f64 * 100.0,
        ))
    }

    pub(crate) fn eval_array_standardize(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_expr(&args[0].value)?;
        let PineValue::Array(id) = id else {
            return Ok(PineValue::Na);
        };
        let Some(kind) = self.array_kinds.get(&id).copied() else {
            return Ok(PineValue::Na);
        };
        if !matches!(kind, ArrayElementKind::Float | ArrayElementKind::Int) {
            return Ok(PineValue::Na);
        }
        let Some(values) = self.array_values_clone(id)? else {
            return Ok(PineValue::Na);
        };

        let numeric_values: Vec<_> = values.iter().filter_map(PineValue::as_f64).collect();
        let count = numeric_values.len();
        if count == 0 {
            return Ok(self.new_array_from_values(ArrayElementKind::Float, Vec::new()));
        }

        let mean = numeric_values.iter().sum::<f64>() / count as f64;
        let variance = numeric_values
            .iter()
            .map(|value| {
                let diff = value - mean;
                diff * diff
            })
            .sum::<f64>()
            / count as f64;
        let stdev = variance.sqrt();

        let values = values
            .iter()
            .map(|value| {
                let Some(value) = value.as_f64() else {
                    return PineValue::Na;
                };
                if stdev == 0.0 || !stdev.is_finite() {
                    PineValue::Na
                } else {
                    finite_float_or_na((value - mean) / stdev)
                }
            })
            .collect();

        Ok(self.new_array_from_values(ArrayElementKind::Float, values))
    }

    pub(crate) fn eval_array_covariance(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id1 = self.eval_expr(&args[0].value)?;
        let id2 = self.eval_expr(&args[1].value)?;
        let biased = match args.get(2) {
            Some(arg) => matches!(self.eval_expr(&arg.value)?, PineValue::Bool(true)),
            None => true,
        };
        let (PineValue::Array(id1), PineValue::Array(id2)) = (id1, id2) else {
            return Ok(PineValue::Na);
        };
        let (Some(kind1), Some(kind2)) = (
            self.array_kinds.get(&id1).copied(),
            self.array_kinds.get(&id2).copied(),
        ) else {
            return Ok(PineValue::Na);
        };
        if !matches!(kind1, ArrayElementKind::Float | ArrayElementKind::Int)
            || !matches!(kind2, ArrayElementKind::Float | ArrayElementKind::Int)
        {
            return Ok(PineValue::Na);
        }
        let (Some(values1), Some(values2)) =
            (self.array_values_clone(id1)?, self.array_values_clone(id2)?)
        else {
            return Ok(PineValue::Na);
        };
        if values1.len() != values2.len() {
            return Ok(PineValue::Na);
        }

        let pairs: Vec<_> = values1
            .iter()
            .zip(values2)
            .filter_map(|(left, right)| Some((left.as_f64()?, right.as_f64()?)))
            .collect();
        let count = pairs.len();
        if count == 0 || (!biased && count < 2) {
            return Ok(PineValue::Na);
        }

        let mean1 = pairs.iter().map(|(left, _)| left).sum::<f64>() / count as f64;
        let mean2 = pairs.iter().map(|(_, right)| right).sum::<f64>() / count as f64;
        let covariance_sum = pairs
            .iter()
            .map(|(left, right)| (left - mean1) * (right - mean2))
            .sum::<f64>();
        let denominator = if biased { count } else { count - 1 };
        Ok(finite_float_or_na(covariance_sum / denominator as f64))
    }

    pub(crate) fn eval_array_variance(
        &mut self,
        args: &[HirCallArg],
        mode: ArrayVarianceMode,
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_expr(&args[0].value)?;
        let biased = match args.get(1) {
            Some(arg) => matches!(self.eval_expr(&arg.value)?, PineValue::Bool(true)),
            None => true,
        };
        let PineValue::Array(id) = id else {
            return Ok(PineValue::Na);
        };
        let Some(kind) = self.array_kinds.get(&id).copied() else {
            return Ok(PineValue::Na);
        };
        if !matches!(kind, ArrayElementKind::Float | ArrayElementKind::Int) {
            return Ok(PineValue::Na);
        }
        let Some(values) = self.array_values_clone(id)? else {
            return Ok(PineValue::Na);
        };

        let numeric_values: Vec<_> = values.iter().filter_map(PineValue::as_f64).collect();
        let count = numeric_values.len();
        if count == 0 || (!biased && count < 2) {
            return Ok(PineValue::Na);
        }

        let mean = numeric_values.iter().sum::<f64>() / count as f64;
        let squared_diff_sum = numeric_values
            .iter()
            .map(|value| {
                let diff = value - mean;
                diff * diff
            })
            .sum::<f64>();
        let denominator = if biased { count } else { count - 1 };
        let variance = squared_diff_sum / denominator as f64;
        let result = match mode {
            ArrayVarianceMode::Variance => variance,
            ArrayVarianceMode::Stdev => variance.sqrt(),
        };

        Ok(finite_float_or_na(result))
    }
}

fn evaluated_call_arg_value<'a>(
    args: &[HirCallArg],
    evaluated_args: &'a [PineValue],
    index: usize,
    name: &str,
) -> Option<&'a PineValue> {
    args.iter()
        .position(|arg| arg.name.as_deref() == Some(name))
        .or_else(|| (index < args.len()).then_some(index))
        .and_then(|arg_index| evaluated_args.get(arg_index))
}
