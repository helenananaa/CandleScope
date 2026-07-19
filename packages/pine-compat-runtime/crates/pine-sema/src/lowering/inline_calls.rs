use std::collections::HashMap;

use crate::prelude::*;

use super::prepend_block_statements;

struct LoweredMethodReceiver {
    label: String,
    type_name: String,
    span: Span,
    expr: HirExpr,
}

impl Analyzer {
    pub(crate) fn lower_postfix_user_type_call_result_method(
        &mut self,
        callee: &Expr,
        args: &[CallArg],
        outer_param_exprs: &HashMap<String, HirExpr>,
        outer_param_types: &HashMap<String, PineType>,
    ) -> Option<Option<HirExpr>> {
        let (_, method_name) = postfix_call_result_method_parts(callee, args)?;
        let receiver = args.first()?;
        if !self
            .type_of_expr_with_params(&receiver.value, outer_param_types)
            .is_some_and(|pine_type| pine_type.kind == ValueKind::UserType)
        {
            return None;
        }
        let receiver_type_name =
            self.user_type_name_of_expr_with_params(&receiver.value, outer_param_exprs)?;
        if !self
            .methods
            .contains_key(&(receiver_type_name.clone(), method_name.to_owned()))
        {
            return None;
        }
        let receiver_expr =
            self.lower_expr_with_params(&receiver.value, outer_param_exprs, outer_param_types)?;
        let label = receiver_type_name
            .split_once('.')
            .map_or(receiver_type_name.as_str(), |(alias, _)| alias)
            .to_owned();
        Some(self.lower_user_method_call_with_receiver_expr(
            LoweredMethodReceiver {
                label,
                type_name: receiver_type_name,
                span: receiver.span,
                expr: receiver_expr,
            },
            method_name,
            &args[1..],
            outer_param_exprs,
            outer_param_types,
        ))
    }

    pub(crate) fn lower_udf_call(
        &mut self,
        name: &str,
        span: Span,
        args: &[CallArg],
        outer_param_exprs: &HashMap<String, HirExpr>,
        outer_param_types: &HashMap<String, PineType>,
    ) -> Option<HirExpr> {
        let function = self.functions.get(name)?.clone();
        let arg_indices = resolve_udf_arg_indices(&function.params, args).ok()?;
        let mut resolved_args = vec![None; function.params.len()];
        for (arg, param_index) in args.iter().zip(arg_indices) {
            let arg_user_type =
                self.user_type_name_of_expr_with_params(&arg.value, outer_param_exprs);
            let arg_user_type_array =
                self.user_type_array_name_of_expr_with_params(&arg.value, outer_param_exprs);
            let arg_expr =
                self.lower_expr_with_params(&arg.value, outer_param_exprs, outer_param_types)?;
            let arg_type = self.type_of_expr_with_params(&arg.value, outer_param_types)?;
            let arg_const_switch_key = self.known_const_switch_key(&arg.value);
            resolved_args[param_index] = Some((
                arg_expr,
                arg_type,
                arg_user_type,
                arg_user_type_array,
                arg_const_switch_key,
            ));
        }

        let mut param_exprs = HashMap::new();
        let mut param_types = HashMap::new();
        let mut param_const_switch_keys = HashMap::new();
        let mut arg_statements = Vec::new();
        for (param, resolved_arg) in function.params.iter().zip(resolved_args) {
            let (arg_expr, arg_type, arg_user_type, arg_user_type_array, arg_const_switch_key) =
                resolved_arg?;
            if !self.record_lowering_temp_symbol(span) {
                return None;
            }
            let symbol = self.fresh_temp_symbol(&format!("{name}.{param}"), arg_type);
            if let Some(type_name) = arg_user_type {
                self.mark_symbol_id_user_type(symbol.id, type_name);
            }
            if let Some(type_name) = arg_user_type_array {
                self.mark_symbol_user_type_array(symbol, type_name);
            }
            if let Some(key) = arg_const_switch_key {
                param_const_switch_keys.insert(param.clone(), key);
            }
            arg_statements.push(HirStmt {
                kind: HirStmtKind::Decl {
                    symbol: symbol.id,
                    value: arg_expr,
                },
            });
            param_exprs.insert(
                param.clone(),
                HirExpr {
                    kind: HirExprKind::Symbol(symbol.id),
                    pine_type: arg_type,
                    series_id: symbol.series_id,
                },
            );
            param_types.insert(param.clone(), arg_type);
        }
        if !self.enter_lowering_inline(span) {
            return None;
        }
        self.function_param_const_switch_keys
            .push(param_const_switch_keys);
        let body = self.with_source_context(function.source_context_id, |analyzer| {
            analyzer.lower_function_body(&function.body, &param_exprs, &param_types)
        });
        self.function_param_const_switch_keys.pop();
        self.exit_lowering_inline();
        let body = body?;
        Some(prepend_block_statements(arg_statements, body))
    }

    pub(crate) fn lower_user_method_call(
        &mut self,
        receiver_name: &str,
        method_name: &str,
        receiver_span: Span,
        args: &[CallArg],
        outer_param_exprs: &HashMap<String, HirExpr>,
        outer_param_types: &HashMap<String, PineType>,
    ) -> Option<HirExpr> {
        let receiver_symbol = self
            .bound_symbol(receiver_name, receiver_span)
            .or_else(|| self.scope.resolve(receiver_name))?;
        let receiver_type_name = self.symbol_user_types.get(&receiver_symbol.id)?.clone();
        let receiver_expr = outer_param_exprs
            .get(receiver_name)
            .cloned()
            .unwrap_or(HirExpr {
                kind: HirExprKind::Symbol(receiver_symbol.id),
                pine_type: receiver_symbol.pine_type,
                series_id: receiver_symbol.series_id,
            });
        self.lower_user_method_call_with_receiver_expr(
            LoweredMethodReceiver {
                label: receiver_name.to_owned(),
                type_name: receiver_type_name,
                span: receiver_span,
                expr: receiver_expr,
            },
            method_name,
            args,
            outer_param_exprs,
            outer_param_types,
        )
    }

    fn lower_user_method_call_with_receiver_expr(
        &mut self,
        receiver: LoweredMethodReceiver,
        method_name: &str,
        args: &[CallArg],
        outer_param_exprs: &HashMap<String, HirExpr>,
        outer_param_types: &HashMap<String, PineType>,
    ) -> Option<HirExpr> {
        let method = self
            .methods
            .get(&(receiver.type_name, method_name.to_owned()))?
            .clone();
        let param_names: Vec<_> = method
            .params
            .iter()
            .map(|param| param.name.clone())
            .collect();
        let arg_indices = resolve_udf_arg_indices(&param_names, args).ok()?;

        let mut param_exprs = HashMap::new();
        let mut param_types = HashMap::new();
        let mut param_const_switch_keys = HashMap::new();
        let mut arg_statements = Vec::new();
        if !self.record_lowering_temp_symbol(receiver.span) {
            return None;
        }
        let receiver_temp = self.fresh_temp_symbol(
            &format!("{method_name}.{}", receiver.label),
            receiver.expr.pine_type,
        );
        self.mark_symbol_id_user_type(receiver_temp.id, method.receiver_type.clone());
        arg_statements.push(HirStmt {
            kind: HirStmtKind::Decl {
                symbol: receiver_temp.id,
                value: receiver.expr,
            },
        });
        param_exprs.insert(
            method.receiver_name.clone(),
            HirExpr {
                kind: HirExprKind::Symbol(receiver_temp.id),
                pine_type: receiver_temp.pine_type,
                series_id: receiver_temp.series_id,
            },
        );
        param_types.insert(method.receiver_name.clone(), receiver_temp.pine_type);

        let mut resolved_args = vec![None; method.params.len()];
        for (arg, param_index) in args.iter().zip(arg_indices) {
            let arg_user_type =
                self.user_type_name_of_expr_with_params(&arg.value, outer_param_exprs);
            let arg_user_type_array =
                self.user_type_array_name_of_expr_with_params(&arg.value, outer_param_exprs);
            let arg_expr =
                self.lower_expr_with_params(&arg.value, outer_param_exprs, outer_param_types)?;
            let arg_type = self.type_of_expr_with_params(&arg.value, outer_param_types)?;
            let arg_const_switch_key = self.known_const_switch_key(&arg.value);
            resolved_args[param_index] = Some((
                arg_expr,
                arg_type,
                arg_user_type,
                arg_user_type_array,
                arg_const_switch_key,
            ));
        }
        for (param, resolved_arg) in method.params.iter().zip(resolved_args) {
            let (arg_expr, arg_type, arg_user_type, arg_user_type_array, arg_const_switch_key) =
                resolved_arg?;
            if !self.record_lowering_temp_symbol(receiver.span) {
                return None;
            }
            let symbol = self.fresh_temp_symbol(&format!("{method_name}.{}", param.name), arg_type);
            if let Some(type_name) = arg_user_type {
                self.mark_symbol_id_user_type(symbol.id, type_name);
            }
            if let Some(type_name) = arg_user_type_array {
                self.mark_symbol_user_type_array(symbol, type_name);
            }
            if let Some(key) = arg_const_switch_key {
                param_const_switch_keys.insert(param.name.clone(), key);
            }
            arg_statements.push(HirStmt {
                kind: HirStmtKind::Decl {
                    symbol: symbol.id,
                    value: arg_expr,
                },
            });
            param_exprs.insert(
                param.name.clone(),
                HirExpr {
                    kind: HirExprKind::Symbol(symbol.id),
                    pine_type: arg_type,
                    series_id: symbol.series_id,
                },
            );
            param_types.insert(param.name.clone(), arg_type);
        }
        if !self.enter_lowering_inline(receiver.span) {
            return None;
        }
        self.function_param_const_switch_keys
            .push(param_const_switch_keys);
        let body = self.with_source_context(method.source_context_id, |analyzer| {
            analyzer.lower_function_body(&method.body, &param_exprs, &param_types)
        });
        self.function_param_const_switch_keys.pop();
        self.exit_lowering_inline();
        let body = body?;
        Some(prepend_block_statements(arg_statements, body))
    }

    pub(crate) fn lower_alias_qualified_user_method_call(
        &mut self,
        name: &str,
        _span: Span,
        args: &[CallArg],
        outer_param_exprs: &HashMap<String, HirExpr>,
        outer_param_types: &HashMap<String, PineType>,
    ) -> Option<HirExpr> {
        let (alias, method_name) = alias_qualified_method_name(name)?;
        let receiver_arg = args.first()?;
        let receiver_user_type =
            self.user_type_name_of_expr_with_params(&receiver_arg.value, outer_param_exprs)?;
        if !receiver_user_type.starts_with(&format!("{alias}.")) {
            return None;
        }
        if !self
            .methods
            .contains_key(&(receiver_user_type.clone(), method_name.to_owned()))
        {
            return None;
        }
        let receiver_expr =
            self.lower_expr_with_params(&receiver_arg.value, outer_param_exprs, outer_param_types)?;
        self.lower_user_method_call_with_receiver_expr(
            LoweredMethodReceiver {
                label: alias.to_owned(),
                type_name: receiver_user_type,
                span: receiver_arg.span,
                expr: receiver_expr,
            },
            method_name,
            &args[1..],
            outer_param_exprs,
            outer_param_types,
        )
    }

    pub(crate) fn lower_local_qualified_user_method_call(
        &mut self,
        name: &str,
        _span: Span,
        args: &[CallArg],
        outer_param_exprs: &HashMap<String, HirExpr>,
        outer_param_types: &HashMap<String, PineType>,
    ) -> Option<HirExpr> {
        let (type_name, method_name) = alias_qualified_method_name(name)?;
        if !self.user_types.contains_key(type_name) {
            return None;
        }
        let receiver_arg = args.first()?;
        let receiver_user_type =
            self.user_type_name_of_expr_with_params(&receiver_arg.value, outer_param_exprs)?;
        if receiver_user_type != type_name {
            return None;
        }
        if !self
            .methods
            .contains_key(&(receiver_user_type.clone(), method_name.to_owned()))
        {
            return None;
        }
        let receiver_expr =
            self.lower_expr_with_params(&receiver_arg.value, outer_param_exprs, outer_param_types)?;
        self.lower_user_method_call_with_receiver_expr(
            LoweredMethodReceiver {
                label: type_name.to_owned(),
                type_name: receiver_user_type,
                span: receiver_arg.span,
                expr: receiver_expr,
            },
            method_name,
            &args[1..],
            outer_param_exprs,
            outer_param_types,
        )
    }
}
