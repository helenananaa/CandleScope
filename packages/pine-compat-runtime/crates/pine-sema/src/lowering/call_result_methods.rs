use super::*;

impl Analyzer {
    pub(super) fn lower_postfix_call_result_method(
        &mut self,
        callee: &Expr,
        args: &[CallArg],
        pine_type: PineType,
        series_id: Option<pine_ir::SeriesId>,
        param_exprs: &HashMap<String, HirExpr>,
        param_types: &HashMap<String, PineType>,
    ) -> Option<Option<HirExpr>> {
        if let Some(result) = self.lower_postfix_array_call_result_method(
            callee,
            args,
            pine_type,
            series_id,
            param_exprs,
            param_types,
        ) {
            return Some(result);
        }
        if let Some(result) = self.lower_postfix_matrix_call_result_method(
            callee,
            args,
            pine_type,
            series_id,
            param_exprs,
            param_types,
        ) {
            return Some(result);
        }
        if let Some(result) = self.lower_postfix_map_call_result_method(
            callee,
            args,
            pine_type,
            series_id,
            param_exprs,
            param_types,
        ) {
            return Some(result);
        }
        if let Some(result) =
            self.lower_postfix_user_type_call_result_method(callee, args, param_exprs, param_types)
        {
            let mut method_call = match result {
                Some(method_call) => method_call,
                None => return Some(None),
            };
            if super::pure_series::pure_postfix_user_type_call_result_method_series_key(
                self, callee, args,
            )
            .and(series_id)
            .is_some()
            {
                method_call.series_id = series_id;
            }
            return Some(Some(method_call));
        }
        postfix_call_result_method_parts(callee, args).map(|_| None)
    }

    pub(super) fn lower_postfix_array_call_result_method(
        &mut self,
        callee: &Expr,
        args: &[CallArg],
        pine_type: PineType,
        series_id: Option<pine_ir::SeriesId>,
        param_exprs: &HashMap<String, HirExpr>,
        param_types: &HashMap<String, PineType>,
    ) -> Option<Option<HirExpr>> {
        let (_, method_name) = postfix_call_result_method_parts(callee, args)?;
        let receiver = args.first()?;
        if !self
            .type_of_expr_with_params(&receiver.value, param_types)
            .is_some_and(|pine_type| is_array_kind(pine_type.kind))
        {
            return None;
        }
        let builtin_name = array_call_result_builtin_name(method_name)?;
        let Some(args) = self.lower_builtin_call_args(builtin_name, args, param_exprs, param_types)
        else {
            return Some(None);
        };
        Some(Some(HirExpr {
            pine_type,
            series_id,
            kind: HirExprKind::Call {
                callee: builtin_name.to_owned(),
                call_site_id: self.alloc_call_site(),
                args,
            },
        }))
    }

    pub(super) fn lower_postfix_matrix_call_result_method(
        &mut self,
        callee: &Expr,
        args: &[CallArg],
        pine_type: PineType,
        series_id: Option<pine_ir::SeriesId>,
        param_exprs: &HashMap<String, HirExpr>,
        param_types: &HashMap<String, PineType>,
    ) -> Option<Option<HirExpr>> {
        let method_name = builtin_matrix_call_result_method_name(callee, args)
            .or_else(|| {
                let (receiver_name, method_name) =
                    bound_matrix_call_result_method_parts(callee, args)?;
                let receiver_type = param_types
                    .get(receiver_name)
                    .copied()
                    .or_else(|| {
                        self.bound_symbol(receiver_name, args.first()?.value.span)
                            .map(|symbol| symbol.pine_type)
                    })
                    .or_else(|| {
                        self.scope
                            .resolve(receiver_name)
                            .map(|symbol| symbol.pine_type)
                    })?;
                is_matrix_kind(receiver_type.kind).then_some(method_name)
            })
            .or_else(|| self.user_function_call_result_method_name(callee, args))
            .or_else(|| self.user_method_call_result_method_name(callee, args))
            .or_else(|| self.local_udf_call_result_method_name(callee, args))?;
        let receiver = args.first()?;
        if !self
            .type_of_expr_with_params(&receiver.value, param_types)
            .is_some_and(|pine_type| is_matrix_kind(pine_type.kind))
        {
            return None;
        }
        let builtin_name = matrix_call_result_builtin_name(method_name)?;
        let Some(args) = self.lower_builtin_call_args(builtin_name, args, param_exprs, param_types)
        else {
            return Some(None);
        };
        Some(Some(HirExpr {
            pine_type,
            series_id,
            kind: HirExprKind::Call {
                callee: builtin_name.to_owned(),
                call_site_id: self.alloc_call_site(),
                args,
            },
        }))
    }

    pub(super) fn lower_postfix_map_call_result_method(
        &mut self,
        callee: &Expr,
        args: &[CallArg],
        pine_type: PineType,
        series_id: Option<pine_ir::SeriesId>,
        param_exprs: &HashMap<String, HirExpr>,
        param_types: &HashMap<String, PineType>,
    ) -> Option<Option<HirExpr>> {
        let method_name = builtin_map_call_result_method_name(callee, args)
            .or_else(|| self.user_function_call_result_method_name(callee, args))
            .or_else(|| self.user_method_call_result_method_name(callee, args))?;
        let receiver = args.first()?;
        if !self
            .type_of_expr_with_params(&receiver.value, param_types)
            .is_some_and(|pine_type| pine_type.kind == ValueKind::Map)
        {
            return None;
        }
        let builtin_name = map_call_result_builtin_name(method_name)?;
        let Some(args) = self.lower_builtin_call_args(builtin_name, args, param_exprs, param_types)
        else {
            return Some(None);
        };
        Some(Some(HirExpr {
            pine_type,
            series_id,
            kind: HirExprKind::Call {
                callee: builtin_name.to_owned(),
                call_site_id: self.alloc_call_site(),
                args,
            },
        }))
    }
}
