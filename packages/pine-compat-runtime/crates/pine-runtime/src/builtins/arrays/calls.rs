use super::*;

impl<'a> HistoricalRuntime<'a> {
    pub(crate) fn eval_array_call(
        &mut self,
        callee: &str,
        args: &[HirCallArg],
    ) -> Option<Result<PineValue, RuntimeError>> {
        if !callee.starts_with("array.") {
            return None;
        }

        Some(match callee {
            "array.new_float" => self.eval_array_new_float(args),
            "array.new_int" => self.eval_array_new_int(args),
            "array.new_bool" => self.eval_array_new_bool(args),
            "array.new_string" => self.eval_array_new_string(args),
            "array.new_color" => self.eval_array_new_color(args),
            "array.new_line" => self.eval_array_new_line(args),
            "array.new_linefill" => self.eval_array_new_linefill(args),
            "array.new_polyline" => self.eval_array_new_polyline(args),
            "array.new_label" => self.eval_array_new_label(args),
            "array.new_box" => self.eval_array_new_box(args),
            "array.new_table" => self.eval_array_new_table(args),
            "array.new<chart.point>" => self.eval_array_new_chart_point(args),
            _ if callee.starts_with("array.new<") && callee.ends_with('>') => {
                let type_name = &callee["array.new<".len()..callee.len() - 1];
                self.eval_array_new_user_type(args, type_name)
            }
            "array.from" => self.eval_array_from(args),
            "array.size" => self.eval_array_size(args),
            "array.push" => self.eval_array_push(args),
            "array.get" => self.eval_array_get(args),
            "array.set" => self.eval_array_set(args),
            "array.insert" => self.eval_array_insert(args),
            "array.pop" => self.eval_array_pop(args),
            "array.remove" => self.eval_array_remove(args),
            "array.shift" => self.eval_array_shift(args),
            "array.unshift" => self.eval_array_unshift(args),
            "array.fill" => self.eval_array_fill(args),
            "array.first" => self.eval_array_first(args),
            "array.last" => self.eval_array_last(args),
            "array.copy" => self.eval_array_copy(args),
            "array.slice" => self.eval_array_slice(args),
            "array.concat" => self.eval_array_concat(args),
            "array.includes" => self.eval_array_includes(args),
            "array.every" => self.eval_array_truth(args, ArrayTruthMode::Every),
            "array.some" => self.eval_array_truth(args, ArrayTruthMode::Some),
            "array.indexof" => self.eval_array_indexof(args),
            "array.lastindexof" => self.eval_array_lastindexof(args),
            "array.binary_search" => {
                self.eval_array_binary_search(args, ArrayBinarySearchMode::Exact)
            }
            "array.binary_search_leftmost" => {
                self.eval_array_binary_search(args, ArrayBinarySearchMode::Leftmost)
            }
            "array.binary_search_rightmost" => {
                self.eval_array_binary_search(args, ArrayBinarySearchMode::Rightmost)
            }
            "array.abs" => self.eval_array_abs(args),
            "array.min" => self.eval_array_numeric(args, ArrayNumericMode::Min),
            "array.max" => self.eval_array_numeric(args, ArrayNumericMode::Max),
            "array.sum" => self.eval_array_numeric(args, ArrayNumericMode::Sum),
            "array.avg" => self.eval_array_numeric(args, ArrayNumericMode::Avg),
            "array.range" => self.eval_array_numeric(args, ArrayNumericMode::Range),
            "array.median" => self.eval_array_numeric(args, ArrayNumericMode::Median),
            "array.mode" => self.eval_array_numeric(args, ArrayNumericMode::Mode),
            "array.percentile_nearest_rank" => {
                self.eval_array_percentile(args, ArrayPercentileMode::NearestRank)
            }
            "array.percentile_linear_interpolation" => {
                self.eval_array_percentile(args, ArrayPercentileMode::LinearInterpolation)
            }
            "array.percentrank" => self.eval_array_percentrank(args),
            "array.covariance" => self.eval_array_covariance(args),
            "array.standardize" => self.eval_array_standardize(args),
            "array.variance" => self.eval_array_variance(args, ArrayVarianceMode::Variance),
            "array.stdev" => self.eval_array_variance(args, ArrayVarianceMode::Stdev),
            "array.sort" => self.eval_array_sort(args),
            "array.sort_indices" => self.eval_array_sort_indices(args),
            "array.reverse" => self.eval_array_reverse(args),
            "array.join" => self.eval_array_join(args),
            "array.clear" => self.eval_array_clear(args),
            _ => return None,
        })
    }
}
