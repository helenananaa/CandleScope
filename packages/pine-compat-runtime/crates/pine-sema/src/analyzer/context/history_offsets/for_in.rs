use std::collections::HashMap;

use super::super::{Analyzer, HistoryOffsetIntEnv};
use crate::types::accepts_type;
use pine_builtins::Accepts;

impl Analyzer {
    pub(in crate::analyzer::context) fn known_history_offset_for_in_branch_result<T>(
        &self,
        index: &Option<String>,
        value: &str,
        iterable: &pine_syntax::Expr,
        body: &[pine_syntax::Stmt],
        env: &mut HistoryOffsetIntEnv,
        f: impl FnOnce(&Self, &[pine_syntax::Stmt], &mut HistoryOffsetIntEnv) -> Option<T>,
    ) -> Option<T> {
        if !self.known_history_offset_for_in_iterable_non_empty(iterable, env)? {
            return None;
        }
        self.with_history_offset_for_in_locals(index, value, env, |analyzer, env| {
            f(analyzer, body, env)
        })
    }

    fn known_history_offset_for_in_iterable_non_empty(
        &self,
        expr: &pine_syntax::Expr,
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<bool> {
        match &expr.kind {
            pine_syntax::ExprKind::Identifier(name) => {
                if let Some(local) = env.locals.get(name).cloned() {
                    if env.local_visiting.contains(name) {
                        return None;
                    }
                    env.local_visiting.push(name.clone());
                    let result = self.known_history_offset_for_in_iterable_non_empty(&local, env);
                    env.local_visiting.pop();
                    return result;
                }
                if env.shadowed_locals.contains(name) {
                    return None;
                }

                let symbol = self.const_lookup_symbol(name, expr.span)?;
                if env.symbol_visiting.contains(&symbol.id) {
                    return None;
                }
                env.symbol_visiting.push(symbol.id);
                let result = self.with_symbol_initializer(symbol.id, |analyzer, init_expr| {
                    analyzer.known_history_offset_for_in_iterable_non_empty(init_expr, env)
                });
                env.symbol_visiting.pop();
                result
            }
            pine_syntax::ExprKind::Call { callee, args } => {
                let name = history_offset_expr_name(callee)?;
                if name == "array.from" {
                    return Some(!args.is_empty());
                }
                if name == "str.split" {
                    return self
                        .known_history_offset_str_split_size_from_args(args, env)
                        .map(|size| size > 0);
                }
                if name == "ta.pivot_point_levels" {
                    return self
                        .known_history_offset_ta_pivot_point_levels_size_from_args(args)
                        .map(|size| size > 0);
                }
                if is_array_new_call(&name) {
                    return self
                        .known_history_offset_collection_size_arg(args, "size", env)
                        .map(|size| size > 0);
                }
                if is_matrix_new_call(&name) {
                    return self
                        .known_history_offset_collection_size_arg(args, "rows", env)
                        .map(|rows| rows > 0);
                }
                if name == "matrix.transpose" {
                    return self
                        .known_history_offset_matrix_row_count_from_args(args, env)
                        .map(|rows| rows > 0);
                }
                if name == "matrix.submatrix" {
                    return self
                        .known_history_offset_matrix_submatrix_shape_from_args(args, env)
                        .map(|(rows, _)| rows > 0);
                }
                if name == "matrix.eigenvectors"
                    || name == "matrix.inv"
                    || name == "matrix.pinv"
                    || name == "matrix.pow"
                {
                    return self
                        .known_history_offset_matrix_shape(expr, env)
                        .map(|(rows, _)| rows > 0);
                }
                if name == "matrix.kron" {
                    return self
                        .known_history_offset_matrix_shape(expr, env)
                        .map(|(rows, _)| rows > 0);
                }
                if name == "matrix.mult" {
                    if let Some((rows, _)) = self.known_history_offset_matrix_shape(expr, env) {
                        return Some(rows > 0);
                    }
                    return self
                        .known_history_offset_array_iterable_size(expr, env)
                        .map(|size| size > 0);
                }
                if name == "matrix.diff" {
                    return self
                        .known_history_offset_matrix_shape(expr, env)
                        .map(|(rows, _)| rows > 0);
                }
                if name == "array.copy" || name == "matrix.copy" {
                    return self.known_history_offset_copy_source_non_empty(args.first(), env);
                }
                if name == "array.concat" {
                    return self.known_history_offset_array_concat_non_empty(args, env);
                }
                if name == "array.slice" {
                    return self.known_history_offset_array_slice_non_empty(args, env);
                }
                if name == "array.abs"
                    || name == "array.standardize"
                    || name == "array.sort_indices"
                {
                    return self
                        .known_history_offset_array_iterable_size(expr, env)
                        .map(|size| size > 0);
                }
                if name == "matrix.row" || name == "matrix.col" {
                    return self
                        .known_history_offset_array_iterable_size(expr, env)
                        .map(|size| size > 0);
                }
                if name == "matrix.eigenvalues" {
                    return self
                        .known_history_offset_array_iterable_size(expr, env)
                        .map(|size| size > 0);
                }
                if let Some(receiver) = history_offset_method_receiver(callee, "copy")
                    && args.is_empty()
                {
                    return self.known_history_offset_for_in_iterable_non_empty(&receiver, env);
                }
                if let Some(receiver) = history_offset_method_receiver(callee, "concat") {
                    return self
                        .known_history_offset_array_concat_method_non_empty(&receiver, args, env);
                }
                if let Some(receiver) = history_offset_method_receiver(callee, "slice") {
                    return self
                        .known_history_offset_array_slice_method_non_empty(&receiver, args, env);
                }
                if let Some(receiver) = history_offset_method_receiver(callee, "transpose")
                    && args.is_empty()
                {
                    return self
                        .known_history_offset_matrix_transpose_row_count(&receiver, env)
                        .map(|rows| rows > 0);
                }
                if let Some(receiver) = history_offset_method_receiver(callee, "submatrix") {
                    return self
                        .known_history_offset_matrix_submatrix_shape(&receiver, args, 0, env)
                        .map(|(rows, _)| rows > 0);
                }
                if history_offset_method_receiver(callee, "eigenvectors").is_some()
                    || history_offset_method_receiver(callee, "inv").is_some()
                    || history_offset_method_receiver(callee, "pinv").is_some()
                    || history_offset_method_receiver(callee, "pow").is_some()
                    || history_offset_method_receiver(callee, "kron").is_some()
                    || history_offset_method_receiver(callee, "diff").is_some()
                {
                    return self
                        .known_history_offset_matrix_shape(expr, env)
                        .map(|(rows, _)| rows > 0);
                }
                if history_offset_method_receiver(callee, "mult").is_some() {
                    if let Some((rows, _)) = self.known_history_offset_matrix_shape(expr, env) {
                        return Some(rows > 0);
                    }
                    return self
                        .known_history_offset_array_iterable_size(expr, env)
                        .map(|size| size > 0);
                }
                if history_offset_method_receiver(callee, "row").is_some()
                    || history_offset_method_receiver(callee, "col").is_some()
                    || history_offset_method_receiver(callee, "abs").is_some()
                    || history_offset_method_receiver(callee, "standardize").is_some()
                    || history_offset_method_receiver(callee, "sort_indices").is_some()
                    || history_offset_method_receiver(callee, "eigenvalues").is_some()
                {
                    return self
                        .known_history_offset_array_iterable_size(expr, env)
                        .map(|size| size > 0);
                }
                None
            }
            _ => None,
        }
    }

    fn known_history_offset_copy_source_non_empty(
        &self,
        source_arg: Option<&pine_syntax::CallArg>,
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<bool> {
        let source_arg =
            source_arg.filter(|arg| arg.name.as_deref().is_none_or(|name| name == "id"))?;
        self.known_history_offset_for_in_iterable_non_empty(&source_arg.value, env)
    }

    fn known_history_offset_array_concat_non_empty(
        &self,
        args: &[pine_syntax::CallArg],
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<bool> {
        let target = history_offset_call_arg(args, 0, "id")?;
        let source = history_offset_call_arg(args, 1, "id2")?;
        self.known_history_offset_any_iterable_non_empty(target, source, env)
    }

    fn known_history_offset_array_concat_method_non_empty(
        &self,
        receiver: &pine_syntax::Expr,
        args: &[pine_syntax::CallArg],
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<bool> {
        let source = history_offset_call_arg(args, 0, "id2")?;
        self.known_history_offset_any_iterable_non_empty(receiver, source, env)
    }

    fn known_history_offset_array_slice_non_empty(
        &self,
        args: &[pine_syntax::CallArg],
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<bool> {
        let source = history_offset_call_arg(args, 0, "id")?;
        let index_from = history_offset_call_arg(args, 1, "index_from")?;
        let index_to = history_offset_call_arg(args, 2, "index_to")?;
        self.known_history_offset_array_slice_size(source, index_from, index_to, env)
            .map(|size| size > 0)
    }

    fn known_history_offset_array_slice_method_non_empty(
        &self,
        receiver: &pine_syntax::Expr,
        args: &[pine_syntax::CallArg],
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<bool> {
        let index_from = history_offset_call_arg(args, 0, "index_from")?;
        let index_to = history_offset_call_arg(args, 1, "index_to")?;
        self.known_history_offset_array_slice_size(receiver, index_from, index_to, env)
            .map(|size| size > 0)
    }

    fn known_history_offset_array_slice_size(
        &self,
        source: &pine_syntax::Expr,
        index_from: &pine_syntax::Expr,
        index_to: &pine_syntax::Expr,
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<i64> {
        let index_from = self.known_history_offset_int_value_inner(index_from, env)?;
        let index_to = self.known_history_offset_int_value_inner(index_to, env)?;
        if index_from < 0 || index_to < 0 || index_from > index_to {
            return Some(0);
        }
        let source_size = self.known_history_offset_array_iterable_size(source, env)?;
        if index_to > source_size {
            return Some(0);
        }
        Some(index_to - index_from)
    }

    fn known_history_offset_any_iterable_non_empty(
        &self,
        left: &pine_syntax::Expr,
        right: &pine_syntax::Expr,
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<bool> {
        let left = self.known_history_offset_for_in_iterable_non_empty(left, env);
        if left == Some(true) {
            return Some(true);
        }
        let right = self.known_history_offset_for_in_iterable_non_empty(right, env);
        if right == Some(true) {
            return Some(true);
        }
        (left == Some(false) && right == Some(false)).then_some(false)
    }

    fn known_history_offset_array_iterable_size(
        &self,
        expr: &pine_syntax::Expr,
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<i64> {
        match &expr.kind {
            pine_syntax::ExprKind::Identifier(name) => {
                if let Some(local) = env.locals.get(name).cloned() {
                    if env.local_visiting.contains(name) {
                        return None;
                    }
                    env.local_visiting.push(name.clone());
                    let result = self.known_history_offset_array_iterable_size(&local, env);
                    env.local_visiting.pop();
                    return result;
                }
                if env.shadowed_locals.contains(name) {
                    return None;
                }

                let symbol = self.const_lookup_symbol(name, expr.span)?;
                if env.symbol_visiting.contains(&symbol.id) {
                    return None;
                }
                env.symbol_visiting.push(symbol.id);
                let result = self.with_symbol_initializer(symbol.id, |analyzer, init_expr| {
                    analyzer.known_history_offset_array_iterable_size(init_expr, env)
                });
                env.symbol_visiting.pop();
                result
            }
            pine_syntax::ExprKind::Call { callee, args } => {
                let name = history_offset_expr_name(callee)?;
                if name == "array.from" {
                    return Some(args.len() as i64);
                }
                if name == "str.split" {
                    return self.known_history_offset_str_split_size_from_args(args, env);
                }
                if name == "ta.pivot_point_levels" {
                    return self.known_history_offset_ta_pivot_point_levels_size_from_args(args);
                }
                if is_array_new_call(&name) {
                    return self.known_history_offset_collection_size_arg(args, "size", env);
                }
                if name == "array.copy" {
                    return self.known_history_offset_array_copy_source_size(args.first(), env);
                }
                if name == "array.abs" || name == "array.standardize" {
                    return self.known_history_offset_unary_array_result_size(args, env);
                }
                if name == "array.concat" {
                    return self.known_history_offset_array_concat_size(args, env);
                }
                if name == "array.slice" {
                    return self.known_history_offset_array_slice_size_from_args(args, env);
                }
                if name == "array.sort_indices" {
                    return self.known_history_offset_array_sort_indices_size(args, env);
                }
                if name == "matrix.row" {
                    return self.known_history_offset_matrix_row_array_size_from_args(args, env);
                }
                if name == "matrix.col" {
                    return self.known_history_offset_matrix_col_array_size_from_args(args, env);
                }
                if name == "matrix.eigenvalues" {
                    return self.known_history_offset_matrix_eigenvalues_size_from_args(args, env);
                }
                if name == "matrix.mult" {
                    return self.known_history_offset_matrix_mult_array_size_from_args(args, env);
                }
                if let Some(receiver) = history_offset_method_receiver(callee, "copy")
                    && args.is_empty()
                {
                    return self.known_history_offset_array_iterable_size(&receiver, env);
                }
                if let Some(receiver) = history_offset_method_receiver(callee, "abs")
                    && args.is_empty()
                {
                    return self.known_history_offset_array_iterable_size(&receiver, env);
                }
                if let Some(receiver) = history_offset_method_receiver(callee, "standardize")
                    && args.is_empty()
                {
                    return self.known_history_offset_array_iterable_size(&receiver, env);
                }
                if let Some(receiver) = history_offset_method_receiver(callee, "concat") {
                    return self
                        .known_history_offset_array_concat_method_size(&receiver, args, env);
                }
                if let Some(receiver) = history_offset_method_receiver(callee, "slice") {
                    return self.known_history_offset_array_slice_method_size(&receiver, args, env);
                }
                if let Some(receiver) = history_offset_method_receiver(callee, "sort_indices") {
                    return self.known_history_offset_array_iterable_size(&receiver, env);
                }
                if let Some(receiver) = history_offset_method_receiver(callee, "row") {
                    return self
                        .known_history_offset_matrix_row_array_size(&receiver, args, 0, env);
                }
                if let Some(receiver) = history_offset_method_receiver(callee, "col") {
                    return self
                        .known_history_offset_matrix_col_array_size(&receiver, args, 0, env);
                }
                if let Some(receiver) = history_offset_method_receiver(callee, "eigenvalues")
                    && args.is_empty()
                {
                    return self.known_history_offset_matrix_eigenvalues_size(&receiver, env);
                }
                if let Some(receiver) = history_offset_method_receiver(callee, "mult") {
                    return self
                        .known_history_offset_matrix_mult_array_method_size(&receiver, args, env);
                }
                None
            }
            _ => None,
        }
    }

    fn known_history_offset_array_copy_source_size(
        &self,
        source_arg: Option<&pine_syntax::CallArg>,
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<i64> {
        let source_arg =
            source_arg.filter(|arg| arg.name.as_deref().is_none_or(|name| name == "id"))?;
        self.known_history_offset_array_iterable_size(&source_arg.value, env)
    }

    fn known_history_offset_unary_array_result_size(
        &self,
        args: &[pine_syntax::CallArg],
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<i64> {
        let source = history_offset_call_arg(args, 0, "id")?;
        self.known_history_offset_array_iterable_size(source, env)
    }

    fn known_history_offset_array_concat_size(
        &self,
        args: &[pine_syntax::CallArg],
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<i64> {
        let target = history_offset_call_arg(args, 0, "id")?;
        let source = history_offset_call_arg(args, 1, "id2")?;
        let target_size = self.known_history_offset_array_iterable_size(target, env)?;
        let source_size = self.known_history_offset_array_iterable_size(source, env)?;
        target_size.checked_add(source_size)
    }

    fn known_history_offset_array_concat_method_size(
        &self,
        receiver: &pine_syntax::Expr,
        args: &[pine_syntax::CallArg],
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<i64> {
        let source = history_offset_call_arg(args, 0, "id2")?;
        let receiver_size = self.known_history_offset_array_iterable_size(receiver, env)?;
        let source_size = self.known_history_offset_array_iterable_size(source, env)?;
        receiver_size.checked_add(source_size)
    }

    fn known_history_offset_array_slice_size_from_args(
        &self,
        args: &[pine_syntax::CallArg],
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<i64> {
        let source = history_offset_call_arg(args, 0, "id")?;
        let index_from = history_offset_call_arg(args, 1, "index_from")?;
        let index_to = history_offset_call_arg(args, 2, "index_to")?;
        self.known_history_offset_array_slice_size(source, index_from, index_to, env)
    }

    fn known_history_offset_array_slice_method_size(
        &self,
        receiver: &pine_syntax::Expr,
        args: &[pine_syntax::CallArg],
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<i64> {
        let index_from = history_offset_call_arg(args, 0, "index_from")?;
        let index_to = history_offset_call_arg(args, 1, "index_to")?;
        self.known_history_offset_array_slice_size(receiver, index_from, index_to, env)
    }

    fn known_history_offset_array_sort_indices_size(
        &self,
        args: &[pine_syntax::CallArg],
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<i64> {
        let source = history_offset_call_arg(args, 0, "id")?;
        self.known_history_offset_array_iterable_size(source, env)
    }

    fn known_history_offset_str_split_size_from_args(
        &self,
        args: &[pine_syntax::CallArg],
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<i64> {
        let source = history_offset_call_arg(args, 0, "source")?;
        let separator = history_offset_call_arg(args, 1, "separator")?;
        let source = self.known_history_offset_string_value_inner(source, env)?;
        let separator = self.known_history_offset_string_value_inner(separator, env)?;
        let size = if separator.is_empty() {
            source.chars().count()
        } else {
            source.split(&separator).count()
        };
        i64::try_from(size).ok()
    }

    fn known_history_offset_ta_pivot_point_levels_size_from_args(
        &self,
        args: &[pine_syntax::CallArg],
    ) -> Option<i64> {
        let _type = history_offset_call_arg(args, 0, "type")?;
        let _anchor = history_offset_call_arg(args, 1, "anchor")?;
        Some(11)
    }

    fn known_history_offset_matrix_row_array_size_from_args(
        &self,
        args: &[pine_syntax::CallArg],
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<i64> {
        let source = history_offset_call_arg(args, 0, "id")?;
        self.known_history_offset_matrix_row_array_size(source, args, 1, env)
    }

    fn known_history_offset_matrix_row_array_size(
        &self,
        source: &pine_syntax::Expr,
        args: &[pine_syntax::CallArg],
        index_arg: usize,
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<i64> {
        let (rows, columns) = self.known_history_offset_matrix_shape(source, env)?;
        let row = self.known_history_offset_call_int_arg(args, index_arg, "row", env)?;
        (0..rows).contains(&row).then_some(columns)
    }

    fn known_history_offset_matrix_col_array_size_from_args(
        &self,
        args: &[pine_syntax::CallArg],
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<i64> {
        let source = history_offset_call_arg(args, 0, "id")?;
        self.known_history_offset_matrix_col_array_size(source, args, 1, env)
    }

    fn known_history_offset_matrix_col_array_size(
        &self,
        source: &pine_syntax::Expr,
        args: &[pine_syntax::CallArg],
        index_arg: usize,
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<i64> {
        let (rows, columns) = self.known_history_offset_matrix_shape(source, env)?;
        let column = self.known_history_offset_call_int_arg(args, index_arg, "column", env)?;
        (0..columns).contains(&column).then_some(rows)
    }

    fn known_history_offset_matrix_eigenvalues_size_from_args(
        &self,
        args: &[pine_syntax::CallArg],
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<i64> {
        let source = history_offset_call_arg(args, 0, "id")?;
        self.known_history_offset_matrix_eigenvalues_size(source, env)
    }

    fn known_history_offset_matrix_eigenvalues_size(
        &self,
        source: &pine_syntax::Expr,
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<i64> {
        let (rows, columns) = self.known_history_offset_matrix_shape(source, env)?;
        (rows == columns).then_some(rows)
    }

    fn known_history_offset_matrix_mult_array_size_from_args(
        &self,
        args: &[pine_syntax::CallArg],
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<i64> {
        let left = history_offset_call_arg(args, 0, "id1")?;
        let right = history_offset_call_arg(args, 1, "id2")?;
        if let Some(size) = self.known_history_offset_matrix_right_array_mult_size(left, right, env)
        {
            return Some(size);
        }
        if let Some(size) = self.known_history_offset_array_left_matrix_mult_size(left, right, env)
        {
            return Some(size);
        }
        self.known_history_offset_array_pair_mult_size(left, right, env)
    }

    fn known_history_offset_matrix_mult_array_method_size(
        &self,
        receiver: &pine_syntax::Expr,
        args: &[pine_syntax::CallArg],
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<i64> {
        let right = history_offset_call_arg(args, 0, "id2")?;
        self.known_history_offset_matrix_right_array_mult_size(receiver, right, env)
    }

    fn known_history_offset_matrix_right_array_mult_size(
        &self,
        matrix: &pine_syntax::Expr,
        vector: &pine_syntax::Expr,
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<i64> {
        let (rows, columns) = self.known_history_offset_matrix_shape(matrix, env)?;
        let vector_size = self.known_history_offset_array_iterable_size(vector, env)?;
        (columns == vector_size).then_some(rows)
    }

    fn known_history_offset_array_left_matrix_mult_size(
        &self,
        vector: &pine_syntax::Expr,
        matrix: &pine_syntax::Expr,
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<i64> {
        let vector_size = self.known_history_offset_array_iterable_size(vector, env)?;
        let (rows, columns) = self.known_history_offset_matrix_shape(matrix, env)?;
        (vector_size == rows).then_some(columns)
    }

    fn known_history_offset_array_pair_mult_size(
        &self,
        left: &pine_syntax::Expr,
        right: &pine_syntax::Expr,
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<i64> {
        let left_size = self.known_history_offset_array_iterable_size(left, env)?;
        let right_size = self.known_history_offset_array_iterable_size(right, env)?;
        (left_size == right_size).then_some(1)
    }

    fn known_history_offset_matrix_row_count_from_args(
        &self,
        args: &[pine_syntax::CallArg],
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<i64> {
        let source = history_offset_call_arg(args, 0, "id")?;
        self.known_history_offset_matrix_transpose_row_count(source, env)
    }

    fn known_history_offset_matrix_transpose_row_count(
        &self,
        source: &pine_syntax::Expr,
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<i64> {
        self.known_history_offset_matrix_shape(source, env)
            .map(|(_, columns)| columns)
    }

    fn known_history_offset_matrix_submatrix_shape_from_args(
        &self,
        args: &[pine_syntax::CallArg],
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<(i64, i64)> {
        let source = history_offset_call_arg(args, 0, "id")?;
        self.known_history_offset_matrix_submatrix_shape(source, args, 1, env)
    }

    fn known_history_offset_matrix_submatrix_shape(
        &self,
        source: &pine_syntax::Expr,
        args: &[pine_syntax::CallArg],
        first_range_arg: usize,
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<(i64, i64)> {
        let (source_rows, source_columns) = self.known_history_offset_matrix_shape(source, env)?;
        let from_row = self.known_history_offset_optional_call_int_arg(
            args,
            first_range_arg,
            "from_row",
            0,
            env,
        )?;
        let to_row = self.known_history_offset_optional_call_int_arg(
            args,
            first_range_arg + 1,
            "to_row",
            source_rows,
            env,
        )?;
        let from_column = self.known_history_offset_optional_call_int_arg(
            args,
            first_range_arg + 2,
            "from_column",
            0,
            env,
        )?;
        let to_column = self.known_history_offset_optional_call_int_arg(
            args,
            first_range_arg + 3,
            "to_column",
            source_columns,
            env,
        )?;

        if from_row < 0
            || to_row < 0
            || from_column < 0
            || to_column < 0
            || from_row > source_rows
            || to_row > source_rows
            || from_column > source_columns
            || to_column > source_columns
            || from_row > to_row
            || from_column > to_column
        {
            return None;
        }

        Some((to_row - from_row, to_column - from_column))
    }

    fn known_history_offset_square_matrix_result_shape_from_args(
        &self,
        args: &[pine_syntax::CallArg],
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<(i64, i64)> {
        let source = history_offset_call_arg(args, 0, "id")?;
        self.known_history_offset_square_matrix_result_shape(source, env)
    }

    fn known_history_offset_square_matrix_result_shape(
        &self,
        source: &pine_syntax::Expr,
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<(i64, i64)> {
        let (rows, columns) = self.known_history_offset_matrix_shape(source, env)?;
        (rows == columns).then_some((rows, rows))
    }

    fn known_history_offset_matrix_pow_shape_from_args(
        &self,
        args: &[pine_syntax::CallArg],
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<(i64, i64)> {
        let source = history_offset_call_arg(args, 0, "id")?;
        let _power = history_offset_call_arg(args, 1, "power")?;
        self.known_history_offset_square_matrix_result_shape(source, env)
    }

    fn known_history_offset_matrix_pow_method_shape(
        &self,
        receiver: &pine_syntax::Expr,
        args: &[pine_syntax::CallArg],
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<(i64, i64)> {
        let _power = history_offset_call_arg(args, 0, "power")?;
        self.known_history_offset_square_matrix_result_shape(receiver, env)
    }

    fn known_history_offset_matrix_pinv_shape_from_args(
        &self,
        args: &[pine_syntax::CallArg],
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<(i64, i64)> {
        let source = history_offset_call_arg(args, 0, "id")?;
        self.known_history_offset_matrix_pinv_shape(source, env)
    }

    fn known_history_offset_matrix_pinv_shape(
        &self,
        source: &pine_syntax::Expr,
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<(i64, i64)> {
        self.known_history_offset_matrix_shape(source, env)
            .map(|(rows, columns)| (columns, rows))
    }

    fn known_history_offset_matrix_kron_shape_from_args(
        &self,
        args: &[pine_syntax::CallArg],
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<(i64, i64)> {
        let left = history_offset_call_arg(args, 0, "id1")?;
        let right = history_offset_call_arg(args, 1, "id2")?;
        self.known_history_offset_matrix_kron_shape(left, right, env)
    }

    fn known_history_offset_matrix_kron_method_shape(
        &self,
        receiver: &pine_syntax::Expr,
        args: &[pine_syntax::CallArg],
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<(i64, i64)> {
        let right = history_offset_call_arg(args, 0, "id2")?;
        self.known_history_offset_matrix_kron_shape(receiver, right, env)
    }

    fn known_history_offset_matrix_kron_shape(
        &self,
        left: &pine_syntax::Expr,
        right: &pine_syntax::Expr,
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<(i64, i64)> {
        let (left_rows, left_columns) = self.known_history_offset_matrix_shape(left, env)?;
        let (right_rows, right_columns) = self.known_history_offset_matrix_shape(right, env)?;
        let rows = left_rows.checked_mul(right_rows)?;
        let columns = left_columns.checked_mul(right_columns)?;
        Some((rows, columns))
    }

    fn known_history_offset_matrix_mult_shape_from_args(
        &self,
        args: &[pine_syntax::CallArg],
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<(i64, i64)> {
        let left = history_offset_call_arg(args, 0, "id1")?;
        let right = history_offset_call_arg(args, 1, "id2")?;
        self.known_history_offset_matrix_mult_shape(left, right, env)
    }

    fn known_history_offset_matrix_mult_method_shape(
        &self,
        receiver: &pine_syntax::Expr,
        args: &[pine_syntax::CallArg],
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<(i64, i64)> {
        let right = history_offset_call_arg(args, 0, "id2")?;
        self.known_history_offset_matrix_mult_shape(receiver, right, env)
    }

    fn known_history_offset_matrix_mult_shape(
        &self,
        left: &pine_syntax::Expr,
        right: &pine_syntax::Expr,
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<(i64, i64)> {
        if let Some((left_rows, left_columns)) = self.known_history_offset_matrix_shape(left, env) {
            if let Some((right_rows, right_columns)) =
                self.known_history_offset_matrix_shape(right, env)
            {
                return (left_columns == right_rows).then_some((left_rows, right_columns));
            }
            if self.known_history_offset_numeric_scalar_expr(right, env) {
                return Some((left_rows, left_columns));
            }
        }
        if self.known_history_offset_numeric_scalar_expr(left, env) {
            return self.known_history_offset_matrix_shape(right, env);
        }
        None
    }

    fn known_history_offset_matrix_matching_pair_shape_from_args(
        &self,
        args: &[pine_syntax::CallArg],
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<(i64, i64)> {
        let left = history_offset_call_arg(args, 0, "id1")?;
        let right = history_offset_call_arg(args, 1, "id2")?;
        self.known_history_offset_matrix_matching_pair_shape(left, right, env)
    }

    fn known_history_offset_matrix_matching_pair_method_shape(
        &self,
        receiver: &pine_syntax::Expr,
        args: &[pine_syntax::CallArg],
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<(i64, i64)> {
        let right = history_offset_call_arg(args, 0, "id2")?;
        self.known_history_offset_matrix_matching_pair_shape(receiver, right, env)
    }

    fn known_history_offset_matrix_matching_pair_shape(
        &self,
        left: &pine_syntax::Expr,
        right: &pine_syntax::Expr,
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<(i64, i64)> {
        if let Some(left_shape) = self.known_history_offset_matrix_shape(left, env) {
            if let Some(right_shape) = self.known_history_offset_matrix_shape(right, env) {
                return (left_shape == right_shape).then_some(left_shape);
            }
            if self.known_history_offset_numeric_scalar_expr(right, env) {
                return Some(left_shape);
            }
        }
        if self.known_history_offset_numeric_scalar_expr(left, env) {
            return self.known_history_offset_matrix_shape(right, env);
        }
        None
    }

    fn known_history_offset_numeric_scalar_expr(
        &self,
        expr: &pine_syntax::Expr,
        env: &mut HistoryOffsetIntEnv,
    ) -> bool {
        if let pine_syntax::ExprKind::Identifier(name) = &expr.kind {
            if let Some(local) = env.locals.get(name).cloned() {
                if env.local_visiting.contains(name) {
                    return false;
                }
                env.local_visiting.push(name.clone());
                let result = self.known_history_offset_numeric_scalar_expr(&local, env);
                env.local_visiting.pop();
                return result;
            }
            if env.shadowed_locals.contains(name) {
                return false;
            }
        }

        self.type_of_expr_with_params(expr, &HashMap::new())
            .is_some_and(|pine_type| accepts_type(Accepts::NumericCompatible, pine_type))
    }

    fn known_history_offset_collection_size_arg(
        &self,
        args: &[pine_syntax::CallArg],
        name: &str,
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<i64> {
        let size_arg = args
            .iter()
            .find(|arg| arg.name.as_deref() == Some(name))
            .or_else(|| args.first().filter(|arg| arg.name.is_none()))?;
        self.known_history_offset_int_value_inner(&size_arg.value, env)
    }

    fn known_history_offset_matrix_shape(
        &self,
        expr: &pine_syntax::Expr,
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<(i64, i64)> {
        match &expr.kind {
            pine_syntax::ExprKind::Identifier(name) => {
                if let Some(local) = env.locals.get(name).cloned() {
                    if env.local_visiting.contains(name) {
                        return None;
                    }
                    env.local_visiting.push(name.clone());
                    let result = self.known_history_offset_matrix_shape(&local, env);
                    env.local_visiting.pop();
                    return result;
                }
                if env.shadowed_locals.contains(name) {
                    return None;
                }

                let symbol = self.const_lookup_symbol(name, expr.span)?;
                if env.symbol_visiting.contains(&symbol.id) {
                    return None;
                }
                env.symbol_visiting.push(symbol.id);
                let result = self.with_symbol_initializer(symbol.id, |analyzer, init_expr| {
                    analyzer.known_history_offset_matrix_shape(init_expr, env)
                });
                env.symbol_visiting.pop();
                result
            }
            pine_syntax::ExprKind::Call { callee, args } => {
                let name = history_offset_expr_name(callee)?;
                if is_matrix_new_call(&name) {
                    let rows = self.known_history_offset_call_int_arg(args, 0, "rows", env)?;
                    let columns =
                        self.known_history_offset_call_int_arg(args, 1, "columns", env)?;
                    return Some((rows, columns));
                }
                if name == "matrix.copy" {
                    let source = history_offset_call_arg(args, 0, "id")?;
                    return self.known_history_offset_matrix_shape(source, env);
                }
                if name == "matrix.transpose" {
                    let source = history_offset_call_arg(args, 0, "id")?;
                    return self
                        .known_history_offset_matrix_shape(source, env)
                        .map(|(rows, columns)| (columns, rows));
                }
                if name == "matrix.submatrix" {
                    return self.known_history_offset_matrix_submatrix_shape_from_args(args, env);
                }
                if name == "matrix.eigenvectors" || name == "matrix.inv" {
                    return self
                        .known_history_offset_square_matrix_result_shape_from_args(args, env);
                }
                if name == "matrix.pow" {
                    return self.known_history_offset_matrix_pow_shape_from_args(args, env);
                }
                if name == "matrix.pinv" {
                    return self.known_history_offset_matrix_pinv_shape_from_args(args, env);
                }
                if name == "matrix.kron" {
                    return self.known_history_offset_matrix_kron_shape_from_args(args, env);
                }
                if name == "matrix.mult" {
                    return self.known_history_offset_matrix_mult_shape_from_args(args, env);
                }
                if name == "matrix.diff" {
                    return self
                        .known_history_offset_matrix_matching_pair_shape_from_args(args, env);
                }
                if let Some(receiver) = history_offset_method_receiver(callee, "copy")
                    && args.is_empty()
                {
                    return self.known_history_offset_matrix_shape(&receiver, env);
                }
                if let Some(receiver) = history_offset_method_receiver(callee, "transpose")
                    && args.is_empty()
                {
                    return self
                        .known_history_offset_matrix_shape(&receiver, env)
                        .map(|(rows, columns)| (columns, rows));
                }
                if let Some(receiver) = history_offset_method_receiver(callee, "submatrix") {
                    return self
                        .known_history_offset_matrix_submatrix_shape(&receiver, args, 0, env);
                }
                if let Some(receiver) = history_offset_method_receiver(callee, "eigenvectors")
                    && args.is_empty()
                {
                    return self.known_history_offset_square_matrix_result_shape(&receiver, env);
                }
                if let Some(receiver) = history_offset_method_receiver(callee, "inv")
                    && args.is_empty()
                {
                    return self.known_history_offset_square_matrix_result_shape(&receiver, env);
                }
                if let Some(receiver) = history_offset_method_receiver(callee, "pow") {
                    return self.known_history_offset_matrix_pow_method_shape(&receiver, args, env);
                }
                if let Some(receiver) = history_offset_method_receiver(callee, "pinv")
                    && args.is_empty()
                {
                    return self.known_history_offset_matrix_pinv_shape(&receiver, env);
                }
                if let Some(receiver) = history_offset_method_receiver(callee, "kron") {
                    return self
                        .known_history_offset_matrix_kron_method_shape(&receiver, args, env);
                }
                if let Some(receiver) = history_offset_method_receiver(callee, "mult") {
                    return self
                        .known_history_offset_matrix_mult_method_shape(&receiver, args, env);
                }
                if let Some(receiver) = history_offset_method_receiver(callee, "diff") {
                    return self.known_history_offset_matrix_matching_pair_method_shape(
                        &receiver, args, env,
                    );
                }
                None
            }
            _ => None,
        }
    }

    fn known_history_offset_call_int_arg(
        &self,
        args: &[pine_syntax::CallArg],
        index: usize,
        name: &str,
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<i64> {
        let arg = history_offset_call_arg(args, index, name)?;
        self.known_history_offset_int_value_inner(arg, env)
    }

    fn known_history_offset_optional_call_int_arg(
        &self,
        args: &[pine_syntax::CallArg],
        index: usize,
        name: &str,
        default: i64,
        env: &mut HistoryOffsetIntEnv,
    ) -> Option<i64> {
        match history_offset_call_arg(args, index, name) {
            Some(arg) => self.known_history_offset_int_value_inner(arg, env),
            None => Some(default),
        }
    }

    fn with_history_offset_for_in_locals<T>(
        &self,
        index: &Option<String>,
        value: &str,
        env: &mut HistoryOffsetIntEnv,
        f: impl FnOnce(&Self, &mut HistoryOffsetIntEnv) -> Option<T>,
    ) -> Option<T> {
        let shadowed_len = env.shadowed_locals.len();
        if let Some(index) = index {
            env.shadowed_locals.push(index.clone());
        }
        env.shadowed_locals.push(value.to_owned());
        let result = f(self, env);
        env.shadowed_locals.truncate(shadowed_len);
        result
    }
}

fn is_array_new_call(name: &str) -> bool {
    name.starts_with("array.new_") || name.starts_with("array.new<")
}

fn is_matrix_new_call(name: &str) -> bool {
    name.starts_with("matrix.new<")
}

fn history_offset_expr_name(expr: &pine_syntax::Expr) -> Option<String> {
    match &expr.kind {
        pine_syntax::ExprKind::Identifier(name) => Some(name.clone()),
        pine_syntax::ExprKind::QualifiedName(parts) => Some(parts.join(".")),
        _ => None,
    }
}

fn history_offset_call_arg<'a>(
    args: &'a [pine_syntax::CallArg],
    index: usize,
    name: &str,
) -> Option<&'a pine_syntax::Expr> {
    args.iter()
        .find(|arg| arg.name.as_deref() == Some(name))
        .or_else(|| args.get(index).filter(|arg| arg.name.is_none()))
        .map(|arg| &arg.value)
}

fn history_offset_method_receiver(
    expr: &pine_syntax::Expr,
    method: &str,
) -> Option<pine_syntax::Expr> {
    match &expr.kind {
        pine_syntax::ExprKind::QualifiedName(parts) if parts.len() == 2 && parts[1] == method => {
            Some(pine_syntax::Expr {
                kind: pine_syntax::ExprKind::Identifier(parts[0].clone()),
                span: expr.span,
            })
        }
        _ => None,
    }
}
