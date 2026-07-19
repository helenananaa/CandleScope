use crate::prelude::*;
use std::collections::HashMap;

mod body_fields;
mod call_args;
mod control_flow;
mod user_types;
use body_fields::{BodyFieldContext, BodyFieldKind, collect_body_field_param_keys};
use user_types::{
    alias_field_param_keys, collect_imported_user_type_field_param_keys_with_params,
    field_param_keys_for_source_path, field_param_keys_for_user_type_expr,
    user_type_field_series_key, user_type_value_series_key,
};

pub(super) fn pure_expr_series_key(analyzer: &Analyzer, expr: &Expr) -> Option<String> {
    pure_expr_series_key_with_params(analyzer, expr, &HashMap::new(), true, &mut Vec::new())
}

pub(super) fn pure_udf_call_series_key(
    analyzer: &Analyzer,
    name: &str,
    args: &[CallArg],
) -> Option<String> {
    pure_udf_call_series_key_inner(analyzer, name, args, &HashMap::new(), &mut Vec::new())
}

pub(super) fn pure_user_method_call_series_key(
    analyzer: &Analyzer,
    receiver_name: &str,
    method_name: &str,
    receiver_span: Span,
    args: &[CallArg],
) -> Option<String> {
    pure_user_method_call_series_key_inner(
        analyzer,
        receiver_name,
        method_name,
        receiver_span,
        args,
        &HashMap::new(),
        &mut Vec::new(),
    )
}

pub(super) fn pure_alias_qualified_user_method_call_series_key(
    analyzer: &Analyzer,
    name: &str,
    args: &[CallArg],
) -> Option<String> {
    pure_alias_qualified_user_method_call_series_key_inner(
        analyzer,
        name,
        args,
        &HashMap::new(),
        &mut Vec::new(),
    )
}

pub(super) fn pure_local_qualified_user_method_call_series_key(
    analyzer: &Analyzer,
    name: &str,
    args: &[CallArg],
) -> Option<String> {
    pure_local_qualified_user_method_call_series_key_inner(
        analyzer,
        name,
        args,
        &HashMap::new(),
        &mut Vec::new(),
    )
}

pub(super) fn pure_postfix_user_type_call_result_method_series_key(
    analyzer: &Analyzer,
    callee: &Expr,
    args: &[CallArg],
) -> Option<String> {
    pure_postfix_user_type_call_result_method_series_key_inner(
        analyzer,
        callee,
        args,
        &HashMap::new(),
        &mut Vec::new(),
    )
}

fn pure_udf_call_series_key_inner(
    analyzer: &Analyzer,
    name: &str,
    args: &[CallArg],
    caller_param_keys: &HashMap<String, String>,
    udf_stack: &mut Vec<String>,
) -> Option<String> {
    if udf_stack.iter().any(|stacked| stacked == name) {
        return None;
    }
    let function = analyzer.functions.get(name)?;
    let param_keys = udf_call_param_keys(analyzer, function, args, caller_param_keys, udf_stack)?;

    udf_stack.push(name.to_owned());
    let body_key = analyzer.with_source_context_ref(function.source_context_id, |analyzer| {
        pure_function_body_series_key(analyzer, &function.body, &param_keys, udf_stack)
    });
    udf_stack.pop();
    let body_key = body_key?;
    Some(format!("udf:{name}:{body_key}"))
}

fn udf_call_param_keys(
    analyzer: &Analyzer,
    function: &FunctionInfo,
    args: &[CallArg],
    caller_param_keys: &HashMap<String, String>,
    udf_stack: &mut Vec<String>,
) -> Option<HashMap<String, String>> {
    let arg_indices = resolve_udf_arg_indices(&function.params, args).ok()?;
    let mut param_keys = HashMap::new();
    let mut pending_field_keys = Vec::new();
    for (arg, param_index) in args.iter().zip(arg_indices) {
        let param_name = function.params.get(param_index)?;
        let arg_user_type_name = analyzer.user_type_name_of_expr(&arg.value);
        let arg_key = if let Some(type_name) = arg_user_type_name.as_deref() {
            user_type_value_series_key(
                analyzer,
                &arg.value,
                type_name,
                caller_param_keys,
                udf_stack,
            )?
        } else {
            pure_expr_series_key_with_params(
                analyzer,
                &arg.value,
                caller_param_keys,
                true,
                udf_stack,
            )?
        };
        param_keys.insert(param_name.clone(), arg_key);
        let caller_field_keys = alias_field_param_keys(param_name, &arg.value, caller_param_keys);
        if !caller_field_keys.is_empty() {
            pending_field_keys.push(caller_field_keys);
        } else if let Some(type_name) = arg_user_type_name.as_deref()
            && let Some(field_keys) = field_param_keys_for_user_type_expr(
                analyzer,
                param_name,
                &arg.value,
                type_name,
                caller_param_keys,
                udf_stack,
            )
        {
            pending_field_keys.push(field_keys);
        }
    }
    if param_keys.len() != function.params.len() {
        return None;
    }
    for field_keys in pending_field_keys {
        param_keys.extend(field_keys);
    }
    Some(param_keys)
}

fn pure_user_method_call_series_key_inner(
    analyzer: &Analyzer,
    receiver_name: &str,
    method_name: &str,
    receiver_span: Span,
    args: &[CallArg],
    caller_param_keys: &HashMap<String, String>,
    udf_stack: &mut Vec<String>,
) -> Option<String> {
    let receiver_symbol = analyzer
        .bound_symbol(receiver_name, receiver_span)
        .or_else(|| analyzer.scope.resolve(receiver_name))?;
    let receiver_type_name = analyzer.symbol_user_types.get(&receiver_symbol.id)?;
    let stack_key = format!("method:{receiver_type_name}.{method_name}");
    if udf_stack.iter().any(|stacked| stacked == &stack_key) {
        return None;
    }
    let method = analyzer
        .methods
        .get(&(receiver_type_name.clone(), method_name.to_owned()))?;
    let param_names: Vec<_> = method
        .params
        .iter()
        .map(|param| param.name.clone())
        .collect();
    let arg_indices = resolve_udf_arg_indices(&param_names, args).ok()?;
    let mut param_keys = HashMap::new();
    let mut pending_field_keys = Vec::new();
    let receiver_key = pure_expr_series_key_with_params(
        analyzer,
        &Expr {
            kind: ExprKind::Identifier(receiver_name.to_owned()),
            span: receiver_span,
        },
        caller_param_keys,
        true,
        udf_stack,
    )?;
    param_keys.insert(method.receiver_name.clone(), receiver_key);
    for (arg, param_index) in args.iter().zip(arg_indices) {
        let param = method.params.get(param_index)?;
        let param_name = &param.name;
        let arg_key = if let Some(type_name) = &param.user_type_name {
            user_type_value_series_key(
                analyzer,
                &arg.value,
                type_name,
                caller_param_keys,
                udf_stack,
            )?
        } else {
            pure_expr_series_key_with_params(
                analyzer,
                &arg.value,
                caller_param_keys,
                true,
                udf_stack,
            )?
        };
        param_keys.insert(param_name.clone(), arg_key);
        let caller_field_keys = alias_field_param_keys(param_name, &arg.value, caller_param_keys);
        if !caller_field_keys.is_empty() {
            pending_field_keys.push(caller_field_keys);
        } else if let Some(type_name) = &param.user_type_name
            && let Some(field_keys) = field_param_keys_for_user_type_expr(
                analyzer,
                param_name,
                &arg.value,
                type_name,
                caller_param_keys,
                udf_stack,
            )
        {
            pending_field_keys.push(field_keys);
        }
    }
    if param_keys.len() != method.params.len() + 1 {
        return None;
    }
    let caller_receiver_field_keys =
        field_param_keys_for_source_path(&method.receiver_name, receiver_name, caller_param_keys);
    if !caller_receiver_field_keys.is_empty() {
        param_keys.extend(caller_receiver_field_keys);
    } else if let Some(field_keys) = receiver_field_param_keys(
        analyzer,
        &method.receiver_name,
        receiver_symbol.id,
        receiver_type_name,
        udf_stack,
    ) {
        param_keys.extend(field_keys);
    }
    for field_keys in pending_field_keys {
        param_keys.extend(field_keys);
    }

    udf_stack.push(stack_key.clone());
    let body_key = analyzer.with_source_context_ref(method.source_context_id, |analyzer| {
        pure_function_body_series_key(analyzer, &method.body, &param_keys, udf_stack)
    });
    udf_stack.pop();
    let body_key = body_key?;
    Some(format!("{stack_key}:{body_key}"))
}

fn pure_alias_qualified_user_method_call_series_key_inner(
    analyzer: &Analyzer,
    name: &str,
    args: &[CallArg],
    caller_param_keys: &HashMap<String, String>,
    udf_stack: &mut Vec<String>,
) -> Option<String> {
    let (alias, method_name) = alias_qualified_method_name(name)?;
    let receiver_arg = args.first()?;
    let receiver_type_name = analyzer.user_type_name_of_expr(&receiver_arg.value)?;
    if !receiver_type_name.starts_with(&format!("{alias}.")) {
        return None;
    }
    pure_expr_receiver_user_method_call_series_key_inner(
        analyzer,
        receiver_type_name,
        method_name,
        receiver_arg,
        &args[1..],
        caller_param_keys,
        udf_stack,
    )
}

fn pure_local_qualified_user_method_call_series_key_inner(
    analyzer: &Analyzer,
    name: &str,
    args: &[CallArg],
    caller_param_keys: &HashMap<String, String>,
    udf_stack: &mut Vec<String>,
) -> Option<String> {
    let (type_name, method_name) = alias_qualified_method_name(name)?;
    if !analyzer.user_types.contains_key(type_name) {
        return None;
    }
    let receiver_arg = args.first()?;
    let receiver_type_name = analyzer.user_type_name_of_expr(&receiver_arg.value)?;
    if receiver_type_name != type_name {
        return None;
    }
    pure_expr_receiver_user_method_call_series_key_inner(
        analyzer,
        receiver_type_name,
        method_name,
        receiver_arg,
        &args[1..],
        caller_param_keys,
        udf_stack,
    )
}

fn pure_postfix_user_type_call_result_method_series_key_inner(
    analyzer: &Analyzer,
    callee: &Expr,
    args: &[CallArg],
    caller_param_keys: &HashMap<String, String>,
    udf_stack: &mut Vec<String>,
) -> Option<String> {
    let (_, method_name) = postfix_call_result_method_parts(callee, args)?;
    let receiver_arg = args.first()?;
    let receiver_type_name = analyzer.user_type_name_of_expr(&receiver_arg.value)?;
    pure_expr_receiver_user_method_call_series_key_inner(
        analyzer,
        receiver_type_name,
        method_name,
        receiver_arg,
        &args[1..],
        caller_param_keys,
        udf_stack,
    )
}

fn pure_expr_receiver_user_method_call_series_key_inner(
    analyzer: &Analyzer,
    receiver_type_name: String,
    method_name: &str,
    receiver_arg: &CallArg,
    method_args: &[CallArg],
    caller_param_keys: &HashMap<String, String>,
    udf_stack: &mut Vec<String>,
) -> Option<String> {
    let stack_key = format!("method:{receiver_type_name}.{method_name}");
    if udf_stack.iter().any(|stacked| stacked == &stack_key) {
        return None;
    }
    let method = analyzer
        .methods
        .get(&(receiver_type_name.clone(), method_name.to_owned()))?;
    let param_names: Vec<_> = method
        .params
        .iter()
        .map(|param| param.name.clone())
        .collect();
    let arg_indices = resolve_udf_arg_indices(&param_names, method_args).ok()?;
    let mut param_keys = HashMap::new();
    let mut pending_field_keys = Vec::new();
    let receiver_key = user_type_value_series_key(
        analyzer,
        &receiver_arg.value,
        &receiver_type_name,
        caller_param_keys,
        udf_stack,
    )?;
    param_keys.insert(method.receiver_name.clone(), receiver_key);
    if let Some(field_keys) = field_param_keys_for_user_type_expr(
        analyzer,
        &method.receiver_name,
        &receiver_arg.value,
        &receiver_type_name,
        caller_param_keys,
        udf_stack,
    ) {
        pending_field_keys.push(field_keys);
    }
    for (arg, param_index) in method_args.iter().zip(arg_indices) {
        let param = method.params.get(param_index)?;
        let param_name = &param.name;
        let arg_key = if let Some(type_name) = &param.user_type_name {
            user_type_value_series_key(
                analyzer,
                &arg.value,
                type_name,
                caller_param_keys,
                udf_stack,
            )?
        } else {
            pure_expr_series_key_with_params(
                analyzer,
                &arg.value,
                caller_param_keys,
                true,
                udf_stack,
            )?
        };
        param_keys.insert(param_name.clone(), arg_key);
        let caller_field_keys = alias_field_param_keys(param_name, &arg.value, caller_param_keys);
        if !caller_field_keys.is_empty() {
            pending_field_keys.push(caller_field_keys);
        } else if let Some(type_name) = &param.user_type_name
            && let Some(field_keys) = field_param_keys_for_user_type_expr(
                analyzer,
                param_name,
                &arg.value,
                type_name,
                caller_param_keys,
                udf_stack,
            )
        {
            pending_field_keys.push(field_keys);
        }
    }
    if param_keys.len() != method.params.len() + 1 {
        return None;
    }
    for field_keys in pending_field_keys {
        param_keys.extend(field_keys);
    }

    udf_stack.push(stack_key.clone());
    let body_key = analyzer.with_source_context_ref(method.source_context_id, |analyzer| {
        pure_function_body_series_key(analyzer, &method.body, &param_keys, udf_stack)
    });
    udf_stack.pop();
    let body_key = body_key?;
    Some(format!("{stack_key}:{body_key}"))
}

fn pure_function_body_series_key(
    analyzer: &Analyzer,
    body: &FunctionBody,
    param_keys: &HashMap<String, String>,
    udf_stack: &mut Vec<String>,
) -> Option<String> {
    match body {
        FunctionBody::Expr(expr) => {
            pure_expr_series_key_with_params(analyzer, expr, param_keys, true, udf_stack)
        }
        FunctionBody::Block(statements) => {
            let (last, prefix) = statements.split_last()?;
            let StmtKind::Expr(result) = &last.kind else {
                return None;
            };
            let mut local_keys = param_keys.clone();
            for statement in prefix {
                match &statement.kind {
                    StmtKind::Decl {
                        mode,
                        declared_type: _,
                        name,
                        value,
                    } => {
                        if *mode != pine_syntax::DeclMode::Normal {
                            return None;
                        }
                        let field_aliases = alias_field_param_keys(name, value, &local_keys);
                        if let Some(value_key) = pure_expr_series_key_with_params(
                            analyzer,
                            value,
                            &local_keys,
                            true,
                            udf_stack,
                        ) {
                            if local_keys.insert(name.clone(), value_key).is_some() {
                                return None;
                            }
                        } else if field_aliases.is_empty() || local_keys.contains_key(name) {
                            return None;
                        }
                        local_keys.extend(field_aliases);
                    }
                    StmtKind::Expr(expr) => {
                        pure_expr_series_key_with_params(
                            analyzer,
                            expr,
                            &local_keys,
                            true,
                            udf_stack,
                        )?;
                    }
                    _ => return None,
                }
            }
            pure_expr_series_key_with_params(analyzer, result, &local_keys, true, udf_stack)
        }
    }
}

fn pure_expr_series_key_with_params(
    analyzer: &Analyzer,
    expr: &Expr,
    param_keys: &HashMap<String, String>,
    allow_udf_calls: bool,
    udf_stack: &mut Vec<String>,
) -> Option<String> {
    match &expr.kind {
        ExprKind::Literal(literal) => Some(format!(
            "lit:{}",
            super::literals::literal_series_key(literal)
        )),
        ExprKind::Identifier(name) => param_keys.get(name).cloned().or_else(|| {
            let symbol = analyzer.bound_symbol(name, expr.span)?;
            (!analyzer.lower_reassigned_symbols.contains(&symbol.id))
                .then(|| format!("sym:{}", symbol.id.0))
        }),
        ExprKind::QualifiedName(parts) => {
            if let Some(key) = param_keys.get(&parts.join(".")) {
                return Some(key.clone());
            }
            if analyzer
                .type_of_bound_chart_point_field_access(parts, expr.span)
                .or_else(|| analyzer.type_of_chart_point_field_access(parts))
                .is_some()
            {
                None
            } else if analyzer
                .type_of_bound_user_type_field_access(parts, expr.span)
                .or_else(|| analyzer.type_of_user_type_field_access(parts))
                .is_some()
            {
                user_type_field_series_key(analyzer, parts, expr.span, udf_stack)
            } else {
                super::builtin_qualified_series_key(parts)
            }
        }
        ExprKind::Unary { op, expr } => Some(format!(
            "unary:{op:?}:{}",
            pure_expr_series_key_with_params(
                analyzer,
                expr,
                param_keys,
                allow_udf_calls,
                udf_stack
            )?
        )),
        ExprKind::Binary { op, left, right } => Some(format!(
            "binary:{op:?}:{}:{}",
            pure_expr_series_key_with_params(
                analyzer,
                left,
                param_keys,
                allow_udf_calls,
                udf_stack
            )?,
            pure_expr_series_key_with_params(
                analyzer,
                right,
                param_keys,
                allow_udf_calls,
                udf_stack
            )?
        )),
        ExprKind::Ternary {
            condition,
            then_expr,
            else_expr,
        } => Some(format!(
            "ternary:{}:{}:{}",
            pure_expr_series_key_with_params(
                analyzer,
                condition,
                param_keys,
                allow_udf_calls,
                udf_stack
            )?,
            pure_expr_series_key_with_params(
                analyzer,
                then_expr,
                param_keys,
                allow_udf_calls,
                udf_stack
            )?,
            pure_expr_series_key_with_params(
                analyzer,
                else_expr,
                param_keys,
                allow_udf_calls,
                udf_stack
            )?
        )),
        ExprKind::If {
            condition,
            then_branch,
            else_branch,
        } => control_flow::pure_if_expr_series_key(
            analyzer,
            condition,
            then_branch,
            else_branch,
            param_keys,
            allow_udf_calls,
            udf_stack,
        ),
        ExprKind::For {
            counter,
            from,
            to,
            step,
            body,
        } => control_flow::pure_for_expr_series_key(
            control_flow::PureForExprSeriesKeyInput {
                analyzer,
                counter,
                from,
                to,
                step: step.as_deref(),
                body,
                param_keys,
                allow_udf_calls,
            },
            udf_stack,
        ),
        ExprKind::ForIn {
            index,
            value,
            iterable,
            body,
        } => control_flow::pure_for_in_expr_series_key(
            control_flow::PureForInExprSeriesKeyInput {
                analyzer,
                index: index.as_deref(),
                value,
                iterable,
                body,
                param_keys,
                allow_udf_calls,
            },
            udf_stack,
        ),
        ExprKind::While { condition, body } => control_flow::pure_while_expr_series_key(
            analyzer,
            condition,
            body,
            param_keys,
            allow_udf_calls,
            udf_stack,
        ),
        ExprKind::Switch { selector, arms } => control_flow::pure_switch_expr_series_key(
            analyzer,
            selector.as_deref(),
            arms,
            param_keys,
            allow_udf_calls,
            udf_stack,
        ),
        ExprKind::History { expr, offset } => Some(format!(
            "history:{}:{}",
            pure_expr_series_key_with_params(
                analyzer,
                expr,
                param_keys,
                allow_udf_calls,
                udf_stack,
            )?,
            pure_expr_series_key_with_params(
                analyzer,
                offset,
                param_keys,
                allow_udf_calls,
                udf_stack,
            )?
        )),
        ExprKind::Call { callee, args } => {
            let name = expr_name(callee)?;
            if allow_udf_calls
                && let Some(method_key) = pure_postfix_user_type_call_result_method_series_key_inner(
                    analyzer, callee, args, param_keys, udf_stack,
                )
            {
                return Some(method_key);
            }
            if allow_udf_calls
                && matches!(callee.kind, ExprKind::Identifier(_))
                && analyzer.functions.contains_key(&name)
            {
                return pure_udf_call_series_key_inner(
                    analyzer, &name, args, param_keys, udf_stack,
                );
            }
            if allow_udf_calls
                && let Some(method_key) = pure_alias_qualified_user_method_call_series_key_inner(
                    analyzer, &name, args, param_keys, udf_stack,
                )
            {
                return Some(method_key);
            }
            if allow_udf_calls
                && let Some(method_key) = pure_local_qualified_user_method_call_series_key_inner(
                    analyzer, &name, args, param_keys, udf_stack,
                )
            {
                return Some(method_key);
            }
            if allow_udf_calls
                && let Some((receiver_name, method_name)) = method_call_parts(callee)
                && let Some(method_key) = pure_user_method_call_series_key_inner(
                    analyzer,
                    receiver_name,
                    method_name,
                    callee.span,
                    args,
                    param_keys,
                    udf_stack,
                )
            {
                return Some(method_key);
            }
            let is_pure_numeric_cast = matches!(name.as_str(), "int" | "float");
            let is_pure_fixed_builtin = super::pure_fixed_builtin_call_name(&name);
            if !super::pure_math_call_name(&name) && !is_pure_numeric_cast && !is_pure_fixed_builtin
            {
                return None;
            }
            let arg_keys = if super::pure_math_variadic_call_name(&name) {
                if args.iter().all(|arg| arg.name.is_none()) {
                    args.iter()
                        .map(|arg| {
                            pure_expr_series_key_with_params(
                                analyzer,
                                &arg.value,
                                param_keys,
                                allow_udf_calls,
                                udf_stack,
                            )
                        })
                        .collect::<Option<Vec<_>>>()?
                } else {
                    call_args::pure_variadic_named_call_arg_keys(
                        analyzer,
                        &name,
                        args,
                        param_keys,
                        allow_udf_calls,
                        udf_stack,
                    )?
                }
            } else {
                call_args::pure_fixed_call_arg_keys(
                    analyzer,
                    &name,
                    args,
                    param_keys,
                    allow_udf_calls,
                    udf_stack,
                )?
            };
            Some(format!("call:{name}:{}", arg_keys.join(":")))
        }
        _ => None,
    }
}

fn receiver_field_param_keys(
    analyzer: &Analyzer,
    receiver_param_name: &str,
    receiver_symbol_id: pine_ir::SymbolId,
    receiver_type_name: &str,
    udf_stack: &mut Vec<String>,
) -> Option<HashMap<String, String>> {
    let mut field_keys = HashMap::new();
    analyzer.with_symbol_initializer(receiver_symbol_id, |analyzer, initializer| {
        collect_user_type_field_param_keys(
            analyzer,
            receiver_param_name,
            initializer,
            receiver_type_name,
            &mut field_keys,
            udf_stack,
        )
    })?;
    Some(field_keys)
}

fn collect_user_type_field_param_keys(
    analyzer: &Analyzer,
    receiver_path: &str,
    source_expr: &Expr,
    type_name: &str,
    field_keys: &mut HashMap<String, String>,
    udf_stack: &mut Vec<String>,
) -> Option<()> {
    collect_user_type_field_param_keys_with_params(
        analyzer,
        receiver_path,
        source_expr,
        type_name,
        field_keys,
        &HashMap::new(),
        udf_stack,
    )
}

fn collect_user_type_field_param_keys_with_params(
    analyzer: &Analyzer,
    receiver_path: &str,
    source_expr: &Expr,
    type_name: &str,
    field_keys: &mut HashMap<String, String>,
    param_keys: &HashMap<String, String>,
    udf_stack: &mut Vec<String>,
) -> Option<()> {
    if let ExprKind::Identifier(name) = &source_expr.kind {
        let alias_field_keys = field_param_keys_for_source_path(receiver_path, name, param_keys);
        if !alias_field_keys.is_empty() {
            field_keys.extend(alias_field_keys);
            return Some(());
        }
        let symbol = analyzer
            .bound_symbol(name, source_expr.span)
            .or_else(|| analyzer.scope.resolve(name))?;
        return analyzer.with_symbol_initializer(symbol.id, |analyzer, initializer| {
            collect_user_type_field_param_keys_with_params(
                analyzer,
                receiver_path,
                initializer,
                type_name,
                field_keys,
                param_keys,
                udf_stack,
            )
        });
    }
    if analyzer.imported_user_types.contains_key(type_name) {
        return collect_imported_user_type_field_param_keys_with_params(
            analyzer,
            receiver_path,
            source_expr,
            type_name,
            field_keys,
            param_keys,
            udf_stack,
        );
    }
    let user_type = analyzer.user_types.get(type_name)?;
    let ExprKind::Call { callee, args } = &source_expr.kind else {
        return None;
    };
    let constructor_name = expr_name(callee)?;
    if constructor_name == format!("{type_name}.new") {
        let constructor = analyzer.user_type_constructor_for_lowering(
            &constructor_name,
            args,
            &HashMap::new(),
        )?;
        for (field, field_arg) in user_type.fields.iter().zip(constructor.field_args.iter()) {
            let field_path = format!("{receiver_path}.{}", field.name);
            if let Some(field_type_name) = field.user_type_name.as_deref() {
                collect_user_type_field_param_keys_with_params(
                    analyzer,
                    &field_path,
                    field_arg,
                    field_type_name,
                    field_keys,
                    param_keys,
                    udf_stack,
                )?;
            } else {
                let key = pure_expr_series_key_with_params(
                    analyzer, field_arg, param_keys, true, udf_stack,
                )?;
                field_keys.insert(field_path, key);
            }
        }
        return Some(());
    }
    if collect_udf_result_field_param_keys(
        analyzer,
        receiver_path,
        source_expr,
        type_name,
        field_keys,
        param_keys,
        udf_stack,
    )
    .is_some()
    {
        return Some(());
    }
    collect_local_user_method_result_field_param_keys(
        analyzer,
        receiver_path,
        source_expr,
        type_name,
        field_keys,
        param_keys,
        udf_stack,
    )
}

fn collect_udf_result_field_param_keys(
    analyzer: &Analyzer,
    receiver_path: &str,
    source_expr: &Expr,
    result_type_name: &str,
    field_keys: &mut HashMap<String, String>,
    caller_param_keys: &HashMap<String, String>,
    udf_stack: &mut Vec<String>,
) -> Option<()> {
    if analyzer.user_type_name_of_expr(source_expr).as_deref()? != result_type_name {
        return None;
    }
    let ExprKind::Call { callee, args } = &source_expr.kind else {
        return None;
    };
    let name = expr_name(callee)?;
    if udf_stack.iter().any(|stacked| stacked == &name) {
        return None;
    }
    let function = analyzer.functions.get(&name)?;
    let param_keys = udf_call_param_keys(analyzer, function, args, caller_param_keys, udf_stack)?;
    let kind = if analyzer.imported_user_types.contains_key(result_type_name) {
        BodyFieldKind::Imported
    } else {
        BodyFieldKind::Local
    };
    udf_stack.push(name);
    let result = analyzer.with_source_context_ref(function.source_context_id, |analyzer| {
        let mut body_context = BodyFieldContext {
            analyzer,
            receiver_path,
            result_type_name,
            field_keys,
            udf_stack,
            kind,
        };
        collect_body_field_param_keys(&mut body_context, &function.body, &param_keys)
    });
    udf_stack.pop();
    result
}

fn collect_local_user_method_result_field_param_keys(
    analyzer: &Analyzer,
    receiver_path: &str,
    source_expr: &Expr,
    result_type_name: &str,
    field_keys: &mut HashMap<String, String>,
    caller_param_keys: &HashMap<String, String>,
    udf_stack: &mut Vec<String>,
) -> Option<()> {
    if analyzer.user_type_name_of_expr(source_expr).as_deref()? != result_type_name {
        return None;
    }
    let ExprKind::Call { callee, args } = &source_expr.kind else {
        return None;
    };
    let name = expr_name(callee)?;
    let (receiver_type_name, method_name) = alias_qualified_method_name(&name)?;
    if !analyzer.user_types.contains_key(receiver_type_name) {
        return None;
    }
    let receiver_arg = args.first()?;
    let method = analyzer
        .methods
        .get(&(receiver_type_name.to_owned(), method_name.to_owned()))?;
    let stack_key = format!("method:{receiver_type_name}.{method_name}");
    if udf_stack.iter().any(|stacked| stacked == &stack_key) {
        return None;
    }

    let param_names: Vec<_> = method
        .params
        .iter()
        .map(|param| param.name.clone())
        .collect();
    let arg_indices = resolve_udf_arg_indices(&param_names, &args[1..]).ok()?;
    let mut param_keys = HashMap::new();
    let mut pending_field_keys = Vec::new();

    let receiver_key = user_type_value_series_key(
        analyzer,
        &receiver_arg.value,
        receiver_type_name,
        caller_param_keys,
        udf_stack,
    )?;
    param_keys.insert(method.receiver_name.clone(), receiver_key);
    if let Some(field_keys) = field_param_keys_for_user_type_expr(
        analyzer,
        &method.receiver_name,
        &receiver_arg.value,
        receiver_type_name,
        caller_param_keys,
        udf_stack,
    ) {
        pending_field_keys.push(field_keys);
    }

    for (arg, param_index) in args[1..].iter().zip(arg_indices) {
        let param = method.params.get(param_index)?;
        let param_name = &param.name;
        let arg_key = if let Some(type_name) = &param.user_type_name {
            user_type_value_series_key(
                analyzer,
                &arg.value,
                type_name,
                caller_param_keys,
                udf_stack,
            )?
        } else {
            pure_expr_series_key_with_params(
                analyzer,
                &arg.value,
                caller_param_keys,
                true,
                udf_stack,
            )?
        };
        param_keys.insert(param_name.clone(), arg_key);
        let caller_field_keys = alias_field_param_keys(param_name, &arg.value, caller_param_keys);
        if !caller_field_keys.is_empty() {
            pending_field_keys.push(caller_field_keys);
        } else if let Some(type_name) = &param.user_type_name
            && let Some(field_keys) = field_param_keys_for_user_type_expr(
                analyzer,
                param_name,
                &arg.value,
                type_name,
                caller_param_keys,
                udf_stack,
            )
        {
            pending_field_keys.push(field_keys);
        }
    }
    if param_keys.len() != method.params.len() + 1 {
        return None;
    }
    for field_keys in pending_field_keys {
        param_keys.extend(field_keys);
    }

    udf_stack.push(stack_key);
    let result = analyzer.with_source_context_ref(method.source_context_id, |analyzer| {
        let mut body_context = BodyFieldContext {
            analyzer,
            receiver_path,
            result_type_name,
            field_keys,
            udf_stack,
            kind: BodyFieldKind::Local,
        };
        collect_body_field_param_keys(&mut body_context, &method.body, &param_keys)
    });
    udf_stack.pop();
    result
}
