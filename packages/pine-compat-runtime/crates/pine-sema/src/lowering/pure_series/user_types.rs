use super::*;

pub(super) fn user_type_field_series_key(
    analyzer: &Analyzer,
    parts: &[String],
    span: Span,
    udf_stack: &mut Vec<String>,
) -> Option<String> {
    if parts.len() < 2 {
        return None;
    }
    let receiver_name = &parts[0];
    let symbol = analyzer
        .bound_symbol(receiver_name, span)
        .or_else(|| analyzer.scope.resolve(receiver_name))?;
    let type_name = analyzer.symbol_user_types.get(&symbol.id)?;
    analyzer.with_symbol_initializer(symbol.id, |analyzer, initializer| {
        user_type_field_path_series_key(analyzer, initializer, type_name, &parts[1..], udf_stack)
    })
}

fn user_type_field_path_series_key(
    analyzer: &Analyzer,
    source_expr: &Expr,
    type_name: &str,
    field_names: &[String],
    udf_stack: &mut Vec<String>,
) -> Option<String> {
    if analyzer.imported_user_types.contains_key(type_name) {
        return imported_user_type_field_path_series_key(
            analyzer,
            source_expr,
            type_name,
            field_names,
            udf_stack,
        );
    }
    let (field_index, field) = analyzer.user_type_field(type_name, field_names.first()?)?;
    let field_arg = direct_constructor_field_arg(analyzer, source_expr, type_name, field_index)?;
    analyzer.with_source_context_ref(field_arg.source_context_id, |analyzer| {
        if field_names.len() == 1 {
            return pure_expr_series_key_with_params(
                analyzer,
                &field_arg.expr,
                &HashMap::new(),
                true,
                udf_stack,
            );
        }
        let next_type_name = field.user_type_name.as_deref()?;
        user_type_field_path_series_key(
            analyzer,
            &field_arg.expr,
            next_type_name,
            &field_names[1..],
            udf_stack,
        )
    })
}

fn direct_constructor_field_arg(
    analyzer: &Analyzer,
    expr: &Expr,
    type_name: &str,
    field_index: usize,
) -> Option<SourcedExpr> {
    if let ExprKind::Identifier(name) = &expr.kind {
        let symbol = analyzer
            .bound_symbol(name, expr.span)
            .or_else(|| analyzer.scope.resolve(name))?;
        return analyzer.with_symbol_initializer(symbol.id, |analyzer, initializer| {
            direct_constructor_field_arg(analyzer, initializer, type_name, field_index)
        });
    }
    let ExprKind::Call { callee, args } = &expr.kind else {
        return None;
    };
    let constructor_name = expr_name(callee)?;
    if constructor_name != format!("{type_name}.new") {
        return None;
    }
    let constructor = if analyzer.imported_user_types.contains_key(type_name) {
        analyzer.imported_user_type_constructor_for_lowering(
            &constructor_name,
            args,
            &HashMap::new(),
        )?
    } else {
        analyzer.user_type_constructor_for_lowering(&constructor_name, args, &HashMap::new())?
    };
    constructor
        .field_args
        .get(field_index)
        .cloned()
        .map(|expr| SourcedExpr {
            source_context_id: analyzer.current_source_context_id(),
            expr,
        })
}

pub(super) fn collect_imported_user_type_field_param_keys_with_params(
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
            collect_imported_user_type_field_param_keys_with_params(
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
    let user_type = analyzer.imported_user_types.get(type_name)?;
    let ExprKind::Call { callee, args } = &source_expr.kind else {
        return None;
    };
    let constructor_name = expr_name(callee)?;
    if constructor_name == format!("{type_name}.new") {
        let constructor = analyzer.imported_user_type_constructor_for_lowering(
            &constructor_name,
            args,
            &HashMap::new(),
        )?;
        for (field, field_arg) in user_type.fields.iter().zip(constructor.field_args.iter()) {
            let field_path = format!("{receiver_path}.{}", field.name);
            let field_names = [field.name.clone()];
            let (_, field_type_name, _) = analyzer.imported_user_type_field_path(
                type_name,
                constructor.pine_type.qualifier,
                &field_names,
            )?;
            if let Some(field_type_name) = field_type_name {
                collect_imported_user_type_field_param_keys_with_params(
                    analyzer,
                    &field_path,
                    field_arg,
                    &field_type_name,
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
    collect_imported_user_method_result_field_param_keys(
        analyzer,
        receiver_path,
        source_expr,
        type_name,
        field_keys,
        param_keys,
        udf_stack,
    )
}

fn collect_imported_user_method_result_field_param_keys(
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
    let (alias, method_name) = alias_qualified_method_name(&name)?;
    let receiver_arg = args.first()?;
    let receiver_type_name = analyzer.user_type_name_of_expr(&receiver_arg.value)?;
    if !receiver_type_name.starts_with(&format!("{alias}.")) {
        return None;
    }
    let method = analyzer
        .methods
        .get(&(receiver_type_name.clone(), method_name.to_owned()))?;
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
            kind: BodyFieldKind::Imported,
        };
        collect_body_field_param_keys(&mut body_context, &method.body, &param_keys)
    });
    udf_stack.pop();
    result
}

pub(super) fn user_type_value_series_key(
    analyzer: &Analyzer,
    expr: &Expr,
    type_name: &str,
    param_keys: &HashMap<String, String>,
    udf_stack: &mut Vec<String>,
) -> Option<String> {
    match &expr.kind {
        ExprKind::Identifier(name) => param_keys.get(name).cloned().or_else(|| {
            analyzer
                .bound_symbol(name, expr.span)
                .or_else(|| analyzer.scope.resolve(name))
                .map(|symbol| format!("sym:{}", symbol.id.0))
        }),
        ExprKind::QualifiedName(parts) => param_keys.get(&parts.join(".")).cloned().or_else(|| {
            pure_expr_series_key_with_params(analyzer, expr, param_keys, true, udf_stack)
        }),
        _ => {
            let mut field_keys = HashMap::new();
            collect_user_type_field_param_keys(
                analyzer,
                "$value",
                expr,
                type_name,
                &mut field_keys,
                udf_stack,
            )?;
            let mut sorted_keys: Vec<_> = field_keys.into_iter().collect();
            sorted_keys.sort_by(|left, right| left.0.cmp(&right.0));
            Some(format!(
                "udt:{type_name}:{}",
                sorted_keys
                    .into_iter()
                    .map(|(field, key)| format!("{field}={key}"))
                    .collect::<Vec<_>>()
                    .join(":")
            ))
        }
    }
}

pub(super) fn field_param_keys_for_user_type_expr(
    analyzer: &Analyzer,
    param_name: &str,
    expr: &Expr,
    type_name: &str,
    caller_param_keys: &HashMap<String, String>,
    udf_stack: &mut Vec<String>,
) -> Option<HashMap<String, String>> {
    let caller_field_keys = alias_field_param_keys(param_name, expr, caller_param_keys);
    if !caller_field_keys.is_empty() {
        return Some(caller_field_keys);
    }
    let mut field_keys = HashMap::new();
    collect_user_type_field_param_keys(
        analyzer,
        param_name,
        expr,
        type_name,
        &mut field_keys,
        udf_stack,
    )?;
    Some(field_keys)
}

fn imported_user_type_field_path_series_key(
    analyzer: &Analyzer,
    source_expr: &Expr,
    type_name: &str,
    field_names: &[String],
    udf_stack: &mut Vec<String>,
) -> Option<String> {
    let field_names = field_names.split_first()?;
    let (_, next_type_name, steps) = analyzer.imported_user_type_field_path(
        type_name,
        pine_ir::Qualifier::Series,
        std::slice::from_ref(field_names.0),
    )?;
    let field_index = steps.first()?.index;
    let field_arg = direct_constructor_field_arg(analyzer, source_expr, type_name, field_index)?;
    analyzer.with_source_context_ref(field_arg.source_context_id, |analyzer| {
        if field_names.1.is_empty() {
            return pure_expr_series_key_with_params(
                analyzer,
                &field_arg.expr,
                &HashMap::new(),
                true,
                udf_stack,
            );
        }
        let next_type_name = next_type_name?;
        imported_user_type_field_path_series_key(
            analyzer,
            &field_arg.expr,
            &next_type_name,
            field_names.1,
            udf_stack,
        )
    })
}

pub(super) fn alias_field_param_keys(
    alias_name: &str,
    value: &Expr,
    param_keys: &HashMap<String, String>,
) -> HashMap<String, String> {
    let source_path = match &value.kind {
        ExprKind::Identifier(name) => name.clone(),
        ExprKind::QualifiedName(parts) => parts.join("."),
        _ => return HashMap::new(),
    };
    field_param_keys_for_source_path(alias_name, &source_path, param_keys)
}

pub(super) fn field_param_keys_for_source_path(
    alias_name: &str,
    source_path: &str,
    param_keys: &HashMap<String, String>,
) -> HashMap<String, String> {
    let source_prefix = format!("{source_path}.");
    param_keys
        .iter()
        .filter_map(|(key, value)| {
            key.strip_prefix(&source_prefix)
                .map(|suffix| (format!("{alias_name}.{suffix}"), value.clone()))
        })
        .collect()
}
