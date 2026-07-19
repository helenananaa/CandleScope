use std::collections::HashSet;

use crate::analyzer::user_types::{
    UserTypeArrayElementInference, classify_user_type_array_element_names,
};
use crate::prelude::*;
use crate::source_graph::{SourceContextId, SourceId};

pub(crate) fn function_param_names(params: &[FunctionParam]) -> Vec<String> {
    params.iter().map(|param| param.name.clone()).collect()
}

pub(crate) fn resolve_udf_arg_indices(
    params: &[String],
    args: &[CallArg],
) -> Result<Vec<usize>, UdfArgError> {
    let mut used = vec![false; params.len()];
    let mut indices = Vec::with_capacity(args.len());
    let mut next_positional = 0;
    let mut saw_named = false;

    for arg in args {
        if let Some(name) = &arg.name {
            saw_named = true;
            let Some(param_index) = params.iter().position(|param| param == name) else {
                return Err(UdfArgError::UnknownName {
                    name: name.clone(),
                    span: arg.span,
                });
            };
            if used[param_index] {
                return Err(UdfArgError::Duplicate {
                    name: name.clone(),
                    span: arg.span,
                });
            }
            used[param_index] = true;
            indices.push(param_index);
        } else {
            if saw_named {
                return Err(UdfArgError::PositionalAfterNamed { span: arg.span });
            }
            while next_positional < used.len() && used[next_positional] {
                next_positional += 1;
            }
            if next_positional >= params.len() {
                return Err(UdfArgError::TooMany { span: arg.span });
            }
            used[next_positional] = true;
            indices.push(next_positional);
            next_positional += 1;
        }
    }

    if let Some(missing_index) = used.iter().position(|used| !*used) {
        return Err(UdfArgError::Missing {
            param: params[missing_index].clone(),
        });
    }

    Ok(indices)
}
pub(crate) fn contains_output_or_declaration_call(expr: &Expr) -> bool {
    match &expr.kind {
        ExprKind::Call { callee, args } => {
            let name = expr_name(callee);
            name.as_deref().is_some_and(|name| {
                is_output_or_declaration_builtin(name)
                    || is_array_mutation_builtin(name)
                    || is_array_mutation_method_call_name(name)
                    || is_map_mutation_builtin(name)
                    || is_map_mutation_method_call_name(name)
            }) || args
                .iter()
                .any(|arg| contains_output_or_declaration_call(&arg.value))
        }
        ExprKind::Unary { expr, .. } | ExprKind::History { expr, .. } => {
            contains_output_or_declaration_call(expr)
        }
        ExprKind::Binary { left, right, .. } => {
            contains_output_or_declaration_call(left) || contains_output_or_declaration_call(right)
        }
        ExprKind::Ternary {
            condition,
            then_expr,
            else_expr,
        } => {
            contains_output_or_declaration_call(condition)
                || contains_output_or_declaration_call(then_expr)
                || contains_output_or_declaration_call(else_expr)
        }
        ExprKind::If {
            condition,
            then_branch,
            else_branch,
        } => {
            contains_output_or_declaration_call(condition)
                || then_branch
                    .iter()
                    .any(statement_contains_output_or_declaration_call)
                || else_branch
                    .iter()
                    .any(statement_contains_output_or_declaration_call)
        }
        ExprKind::Switch { selector, arms } => {
            selector
                .as_deref()
                .is_some_and(contains_output_or_declaration_call)
                || arms.iter().any(|arm| {
                    arm.condition
                        .as_ref()
                        .is_some_and(contains_output_or_declaration_call)
                        || switch_arm_result_contains_output_or_declaration_call(&arm.result)
                })
        }
        ExprKind::For {
            from,
            to,
            step,
            body,
            ..
        } => {
            contains_output_or_declaration_call(from)
                || contains_output_or_declaration_call(to)
                || step
                    .as_deref()
                    .is_some_and(contains_output_or_declaration_call)
                || body.iter().any(|statement| match &statement.kind {
                    StmtKind::Expr(expr) => contains_output_or_declaration_call(expr),
                    StmtKind::Decl { value, .. }
                    | StmtKind::Reassign { value, .. }
                    | StmtKind::FieldReassign { value, .. }
                    | StmtKind::TupleDecl { value, .. } => {
                        contains_output_or_declaration_call(value)
                    }
                    StmtKind::ArrayFieldReassign {
                        array,
                        index,
                        value,
                        ..
                    } => {
                        contains_output_or_declaration_call(array)
                            || contains_output_or_declaration_call(index)
                            || contains_output_or_declaration_call(value)
                    }
                    StmtKind::If {
                        condition,
                        then_branch,
                        else_branch,
                    } => {
                        contains_output_or_declaration_call(condition)
                            || then_branch.iter().any(|statement| {
                                statement_contains_output_or_declaration_call(statement)
                            })
                            || else_branch.iter().any(|statement| {
                                statement_contains_output_or_declaration_call(statement)
                            })
                    }
                    StmtKind::For { .. } | StmtKind::ForIn { .. } | StmtKind::While { .. } => true,
                    StmtKind::Break | StmtKind::Continue | StmtKind::Function { .. } => false,
                    StmtKind::Import(_)
                    | StmtKind::Library(_)
                    | StmtKind::Export(_)
                    | StmtKind::UserType(_)
                    | StmtKind::Method(_) => false,
                    StmtKind::Unsupported { .. } => false,
                })
        }
        ExprKind::While { condition, body } => {
            contains_output_or_declaration_call(condition)
                || body
                    .iter()
                    .any(statement_contains_output_or_declaration_call)
        }
        ExprKind::ForIn { iterable, body, .. } => {
            contains_output_or_declaration_call(iterable)
                || body
                    .iter()
                    .any(statement_contains_output_or_declaration_call)
        }
        ExprKind::Tuple(items) => items.iter().any(contains_output_or_declaration_call),
        ExprKind::Literal(_) | ExprKind::Identifier(_) | ExprKind::QualifiedName(_) => false,
    }
}

fn switch_arm_result_contains_output_or_declaration_call(result: &SwitchArmResult) -> bool {
    match result {
        SwitchArmResult::Expr(expr) => contains_output_or_declaration_call(expr),
        SwitchArmResult::Block(statements) => statements
            .iter()
            .any(statement_contains_output_or_declaration_call),
    }
}

fn function_branch_has_return(branch: &[Stmt]) -> bool {
    branch.last().is_some_and(|statement| {
        matches!(
            statement.kind,
            StmtKind::Expr(_)
                | StmtKind::For { .. }
                | StmtKind::ForIn { .. }
                | StmtKind::While { .. }
        )
    })
}

pub(crate) fn statement_contains_output_or_declaration_call(statement: &Stmt) -> bool {
    match &statement.kind {
        StmtKind::Expr(expr) => contains_output_or_declaration_call(expr),
        StmtKind::Decl { value, .. }
        | StmtKind::Reassign { value, .. }
        | StmtKind::FieldReassign { value, .. }
        | StmtKind::TupleDecl { value, .. } => contains_output_or_declaration_call(value),
        StmtKind::ArrayFieldReassign {
            array,
            index,
            value,
            ..
        } => {
            contains_output_or_declaration_call(array)
                || contains_output_or_declaration_call(index)
                || contains_output_or_declaration_call(value)
        }
        StmtKind::If {
            condition,
            then_branch,
            else_branch,
        } => {
            contains_output_or_declaration_call(condition)
                || then_branch
                    .iter()
                    .any(statement_contains_output_or_declaration_call)
                || else_branch
                    .iter()
                    .any(statement_contains_output_or_declaration_call)
        }
        StmtKind::For { .. } | StmtKind::ForIn { .. } | StmtKind::While { .. } => true,
        StmtKind::Break | StmtKind::Continue | StmtKind::Function { .. } => false,
        StmtKind::Import(_)
        | StmtKind::Library(_)
        | StmtKind::Export(_)
        | StmtKind::UserType(_)
        | StmtKind::Method(_) => false,
        StmtKind::Unsupported { .. } => false,
    }
}
pub(crate) fn has_duplicate_param(params: &[String]) -> bool {
    for (index, param) in params.iter().enumerate() {
        if params[index + 1..].iter().any(|other| other == param) {
            return true;
        }
    }
    false
}

impl Analyzer {
    pub(crate) fn function_param_type(
        &mut self,
        type_name: &str,
        span: Span,
    ) -> Option<FunctionParamInfo> {
        let (pine_type, user_type_name) =
            match type_name {
                _ if type_name.starts_with("array<") && type_name.ends_with('>') => {
                    let element_type = &type_name["array<".len()..type_name.len() - 1];
                    if let Some(kind) = array_kind_from_element_type_name(element_type) {
                        (PineType::new(Qualifier::Series, kind), None)
                    } else if matches!(
                        classify_user_type_array_element_names(
                            &self.user_types,
                            &[element_type.to_owned()]
                        ),
                        Some(UserTypeArrayElementInference::SameScalarLocal(_))
                    ) || self.imported_user_types.get(element_type).is_some_and(
                        |user_type| self.imported_user_type_has_scalar_tree_fields(user_type),
                    ) {
                        (
                            PineType::new(Qualifier::Series, ValueKind::UserTypeArray),
                            Some(element_type.to_owned()),
                        )
                    } else {
                        self.diagnostics.push(Diagnostic::error(
                            "E_FUNCTION_PARAM_TYPE",
                            format!("function parameter type `{type_name}` is not supported"),
                            span,
                        ));
                        return None;
                    }
                }
                "int" => (PineType::new(Qualifier::Series, ValueKind::Int), None),
                "float" => (PineType::new(Qualifier::Series, ValueKind::Float), None),
                "bool" => (PineType::new(Qualifier::Series, ValueKind::Bool), None),
                "string" => (PineType::new(Qualifier::Series, ValueKind::String), None),
                "color" => (PineType::new(Qualifier::Series, ValueKind::Color), None),
                "label" => (PineType::new(Qualifier::Series, ValueKind::Label), None),
                "line" => (PineType::new(Qualifier::Series, ValueKind::Line), None),
                "linefill" => (PineType::new(Qualifier::Series, ValueKind::LineFill), None),
                "polyline" => (PineType::new(Qualifier::Series, ValueKind::Polyline), None),
                "box" => (PineType::new(Qualifier::Series, ValueKind::Box), None),
                "table" => (PineType::new(Qualifier::Series, ValueKind::Table), None),
                "chart.point" => (
                    PineType::new(Qualifier::Series, ValueKind::ChartPoint),
                    None,
                ),
                _ if self.user_types.contains_key(type_name) => (
                    PineType::new(Qualifier::Series, ValueKind::UserType),
                    Some(type_name.to_owned()),
                ),
                _ if self.imported_user_types.contains_key(type_name) => (
                    PineType::new(Qualifier::Series, ValueKind::UserType),
                    Some(type_name.to_owned()),
                ),
                _ => {
                    self.diagnostics.push(Diagnostic::error(
                        "E_FUNCTION_PARAM_TYPE",
                        format!("function parameter type `{type_name}` is not supported"),
                        span,
                    ));
                    return None;
                }
            };
        Some(FunctionParamInfo {
            pine_type,
            user_type_name,
            span,
        })
    }

    pub(crate) fn register_functions(&mut self, program: &Program) {
        for statement in &program.statements {
            let StmtKind::Function { name, params, body } = &statement.kind else {
                continue;
            };
            if self.functions.contains_key(name) {
                self.diagnostics.push(Diagnostic::error(
                    "E_FUNCTION_DUPLICATE",
                    format!("function `{name}` is already defined"),
                    statement.span,
                ));
                continue;
            }
            if pine_builtins::is_phase_1_builtin(name)
                || INITIAL_SYMBOLS
                    .iter()
                    .any(|(symbol_name, _)| symbol_name == name)
            {
                self.diagnostics.push(Diagnostic::error(
                    "E_FUNCTION_NAME",
                    format!("function `{name}` conflicts with an existing symbol"),
                    statement.span,
                ));
                continue;
            }
            let param_names = function_param_names(params);
            if has_duplicate_param(&param_names) {
                self.diagnostics.push(Diagnostic::error(
                    "E_FUNCTION_PARAM",
                    format!("function `{name}` has duplicate parameter names"),
                    statement.span,
                ));
                continue;
            }
            let mut param_types = Vec::with_capacity(params.len());
            let mut valid = true;
            for param in params {
                let Some(type_name) = &param.type_name else {
                    param_types.push(None);
                    continue;
                };
                let Some(param_type) = self.function_param_type(type_name, param.span) else {
                    valid = false;
                    param_types.push(None);
                    continue;
                };
                param_types.push(Some(param_type));
            }
            if !valid {
                continue;
            }
            self.functions.insert(
                name.clone(),
                FunctionInfo {
                    source_id: SourceId::root(),
                    source_context_id: SourceContextId::root(),
                    params: param_names,
                    param_types,
                    body: body.clone(),
                    span: statement.span,
                },
            );
        }
    }

    pub(crate) fn analyze_udf_call(
        &mut self,
        name: &str,
        span: Span,
        call_span: Span,
        args: &[CallArg],
        arg_types: &[Option<PineType>],
    ) -> Option<PineType> {
        let function = self.functions.get(name)?.clone();
        if self.function_stack.iter().any(|active| active == name) {
            self.diagnostics.push(Diagnostic::error(
                "E_RECURSIVE_FUNCTION",
                format!("recursive function `{name}` is not supported"),
                span,
            ));
            return None;
        }
        if self.function_stack.len() >= MAX_FUNCTION_CALL_DEPTH {
            self.diagnostics.push(Diagnostic::error(
                "E_FUNCTION_CALL_DEPTH",
                "user-defined function call chain is too deep",
                span,
            ));
            return None;
        }
        for arg in args {
            if contains_output_or_declaration_call(&arg.value) {
                self.unsupported(
                    "function_side_effect",
                    "side-effecting calls cannot be passed as user-defined function arguments",
                    arg.span,
                );
            }
        }
        let arg_indices = match resolve_udf_arg_indices(&function.params, args) {
            Ok(arg_indices) => arg_indices,
            Err(error) => {
                self.report_udf_arg_error(name, span, function.params.len(), args.len(), error);
                return None;
            }
        };

        self.compatibility.supported.push(FeatureUse {
            feature: "function".to_owned(),
            span: function.span,
        });
        let mut resolved_arg_types = vec![None; function.params.len()];
        let mut resolved_arg_user_types = vec![None; function.params.len()];
        let mut resolved_arg_user_type_arrays = vec![None; function.params.len()];
        let mut resolved_arg_map_infos = vec![None; function.params.len()];
        let mut resolved_arg_const_switch_keys = vec![None; function.params.len()];
        for (arg_index, param_index) in arg_indices.iter().copied().enumerate() {
            resolved_arg_types[param_index] = arg_types.get(arg_index).copied().flatten();
            resolved_arg_user_types[param_index] = args
                .get(arg_index)
                .and_then(|arg| self.user_type_name_of_expr(&arg.value));
            resolved_arg_user_type_arrays[param_index] = args
                .get(arg_index)
                .and_then(|arg| self.user_type_array_name_of_expr(&arg.value));
            resolved_arg_map_infos[param_index] = args
                .get(arg_index)
                .and_then(|arg| self.map_type_of_expr(&arg.value));
            resolved_arg_const_switch_keys[param_index] = args
                .get(arg_index)
                .and_then(|arg| self.known_const_switch_key(&arg.value));
        }
        self.scope.push_scope();
        let mut param_symbols = std::collections::HashSet::new();
        let mut param_const_switch_keys = std::collections::HashMap::new();
        for (
            (param, expected_type),
            (
                (((arg_type, arg_user_type), arg_user_type_array), arg_map_info),
                arg_const_switch_key,
            ),
        ) in function.params.iter().zip(function.param_types.iter()).zip(
            resolved_arg_types
                .into_iter()
                .zip(resolved_arg_user_types)
                .zip(resolved_arg_user_type_arrays)
                .zip(resolved_arg_map_infos)
                .zip(resolved_arg_const_switch_keys),
        ) {
            let arg_type = arg_type.unwrap_or(UNKNOWN);
            let symbol = self.define_local_symbol(param, arg_type, None, false);
            param_symbols.insert(symbol.id);
            if let Some(key) = arg_const_switch_key.as_ref() {
                self.record_symbol_const_switch_key(symbol, key);
            }
            if let Some(expected_type) = expected_type {
                if !can_assign(expected_type.pine_type, arg_type) {
                    self.diagnostics.push(Diagnostic::error(
                        "E_FUNCTION_ARG_TYPE",
                        format!(
                            "cannot pass {} to function parameter `{}` of type {}",
                            pine_type_name(arg_type),
                            param,
                            pine_type_name(expected_type.pine_type)
                        ),
                        expected_type.span,
                    ));
                }
                if expected_type.pine_type.kind == ValueKind::UserTypeArray {
                    if let Some(expected_type_name) = &expected_type.user_type_name {
                        if arg_user_type_array.as_deref() == Some(expected_type_name.as_str()) {
                            self.mark_symbol_user_type_array(symbol, expected_type_name.clone());
                        } else if arg_type.kind == ValueKind::UserTypeArray {
                            self.diagnostics.push(Diagnostic::error(
                                "E_FUNCTION_ARG_TYPE",
                                format!(
                                    "cannot pass a different user-defined type array to function parameter `{param}`",
                                ),
                                expected_type.span,
                            ));
                        }
                    }
                } else {
                    if let Some(expected_type_name) = &expected_type.user_type_name
                        && arg_user_type.as_deref() == Some(expected_type_name.as_str())
                    {
                        self.mark_symbol_user_type(symbol, expected_type_name.clone());
                    }
                }
            }
            if let Some(type_name) = arg_user_type {
                self.mark_symbol_user_type(symbol, type_name);
            }
            if let Some(type_name) = arg_user_type_array {
                self.mark_symbol_user_type_array(symbol, type_name);
            }
            if let Some(info) = arg_map_info {
                self.mark_symbol_map(symbol, info);
            }
            if let Some(key) = arg_const_switch_key {
                param_const_switch_keys.insert(param.clone(), key);
            }
        }
        self.function_stack.push(name.to_owned());
        self.function_param_symbols.push(param_symbols);
        self.function_param_const_switch_keys
            .push(param_const_switch_keys);
        self.function_context_is_method.push(false);
        self.function_tuple_identity_slots.push(HashSet::new());
        self.function_depth += 1;
        let (return_type, body_user_type, body_user_type_array, body_map, unresolved_tuple_slots) =
            self.with_source_context(function.source_context_id, |analyzer| {
                let diagnostic_start = analyzer.diagnostics.len();
                let return_type = analyzer.analyze_function_body(&function.body, function.span);
                let body_user_type = return_type
                    .is_some_and(|pine_type| pine_type.kind == ValueKind::UserType)
                    .then(|| analyzer.user_type_name_of_function_body(&function.body))
                    .flatten();
                let body_user_type_array = return_type
                    .is_some_and(|pine_type| pine_type.kind == ValueKind::UserTypeArray)
                    .then(|| analyzer.user_type_array_name_of_function_body(&function.body))
                    .flatten();
                let body_map = return_type
                    .is_some_and(|pine_type| pine_type.kind == ValueKind::Map)
                    .then(|| analyzer.map_type_of_function_body(&function.body))
                    .flatten();
                let has_new_errors = analyzer.diagnostics[diagnostic_start..]
                    .iter()
                    .any(|diagnostic| diagnostic.severity == Severity::Error);
                let unresolved_tuple_slots = if !has_new_errors
                    && return_type.is_some_and(|pine_type| pine_type.kind == ValueKind::Tuple)
                {
                    analyzer.unresolved_function_body_user_type_array_tuple_slots(&function.body)
                } else {
                    Vec::new()
                };
                (
                    return_type,
                    body_user_type,
                    body_user_type_array,
                    body_map,
                    unresolved_tuple_slots,
                )
            });
        self.function_depth -= 1;
        self.function_context_is_method.pop();
        self.function_param_const_switch_keys.pop();
        self.function_param_symbols.pop();
        self.function_stack.pop();
        self.scope.pop_scope();

        let mut tuple_identity_slots = self
            .function_tuple_identity_slots
            .pop()
            .expect("tuple identity call scope should exist");
        tuple_identity_slots.extend(unresolved_tuple_slots);
        if let Some(parent_slots) = self.function_tuple_identity_slots.last_mut() {
            parent_slots.extend(tuple_identity_slots);
        } else {
            let mut tuple_identity_slots: Vec<_> = tuple_identity_slots.into_iter().collect();
            tuple_identity_slots.sort_unstable();
            for index in tuple_identity_slots {
                self.diagnostics.push(Diagnostic::error(
                    "E_TUPLE_UDT_ARRAY_IDENTITY",
                    format!(
                        "tuple element {} user-defined type array must resolve to one element identity",
                        index + 1
                    ),
                    call_span,
                ));
            }
        }

        if return_type.is_some_and(|pine_type| pine_type.kind == ValueKind::UserType) {
            let returned_type_name = body_user_type.or_else(|| {
                let FunctionBody::Expr(expr) = &function.body else {
                    return None;
                };
                let ExprKind::Identifier(returned_param) = &expr.kind else {
                    return None;
                };
                let param_index = function
                    .params
                    .iter()
                    .position(|param| param == returned_param)?;
                let arg_index = arg_indices
                    .iter()
                    .position(|mapped_param_index| *mapped_param_index == param_index)?;
                self.user_type_name_of_expr(&args[arg_index].value)
            });
            if let Some(type_name) = returned_type_name {
                self.mark_expr_user_type(call_span, type_name.clone());
                self.mark_expr_user_type(span, type_name);
            }
        }
        if return_type.is_some_and(|pine_type| pine_type.kind == ValueKind::UserTypeArray)
            && let Some(type_name) = body_user_type_array
        {
            self.mark_expr_user_type_array(call_span, type_name.clone());
            self.mark_expr_user_type_array(span, type_name);
        }
        if return_type.is_some_and(|pine_type| pine_type.kind == ValueKind::Map)
            && let Some(info) = body_map
        {
            self.mark_expr_map(call_span, info);
            self.mark_expr_map(span, info);
        }

        return_type
    }

    pub(crate) fn analyze_function_body(
        &mut self,
        body: &FunctionBody,
        span: Span,
    ) -> Option<PineType> {
        match body {
            FunctionBody::Expr(expr) => self.analyze_expr(expr),
            FunctionBody::Block(statements) => {
                let Some((last, prefix)) = statements.split_last() else {
                    self.diagnostics.push(Diagnostic::error(
                        "E_FUNCTION_RETURN",
                        "user-defined function block must end with an expression",
                        span,
                    ));
                    return None;
                };
                for statement in prefix {
                    self.analyze_stmt(statement);
                }
                match &last.kind {
                    StmtKind::Expr(expr) => self.analyze_expr(expr),
                    StmtKind::If {
                        condition,
                        then_branch,
                        else_branch,
                    } if function_branch_has_return(then_branch)
                        && function_branch_has_return(else_branch) =>
                    {
                        self.analyze_function_if_return(
                            condition,
                            then_branch,
                            else_branch,
                            last.span,
                        )
                    }
                    StmtKind::For {
                        counter,
                        from,
                        to,
                        step,
                        body,
                    } => self.analyze_for_expr(counter, from, to, step.as_ref(), body, last.span),
                    StmtKind::ForIn {
                        index,
                        value,
                        iterable,
                        body,
                    } => {
                        self.analyze_for_in_expr(index.as_deref(), value, iterable, body, last.span)
                    }
                    StmtKind::While { condition, body } => {
                        self.analyze_while_expr(condition, body, last.span)
                    }
                    _ => {
                        self.analyze_stmt(last);
                        self.diagnostics.push(Diagnostic::error(
                            "E_FUNCTION_RETURN",
                            "user-defined function block must end with an expression",
                            last.span,
                        ));
                        None
                    }
                }
            }
        }
    }

    fn analyze_function_if_return(
        &mut self,
        condition: &Expr,
        then_branch: &[Stmt],
        else_branch: &[Stmt],
        span: Span,
    ) -> Option<PineType> {
        let condition_type = self.analyze_expr(condition)?;
        self.expect_bool(condition_type, condition.span);
        self.compatibility.supported.push(FeatureUse {
            feature: "if".to_owned(),
            span,
        });

        let condition_qualifier = condition_type.qualifier;
        let condition_value = self.known_const_bool_value(condition);
        self.block_depth += 1;
        self.assignment_qualifier_context.push(condition_qualifier);
        let (then_type, else_type) = match condition_value {
            Some(true) => {
                let then_type = self.analyze_function_branch_return(then_branch);
                let else_type = self.analyze_without_symbol_effects(|analyzer| {
                    analyzer.analyze_function_branch_return(else_branch)
                });
                (then_type, else_type)
            }
            Some(false) => {
                let then_type = self.analyze_without_symbol_effects(|analyzer| {
                    analyzer.analyze_function_branch_return(then_branch)
                });
                let else_type = self.analyze_function_branch_return(else_branch);
                (then_type, else_type)
            }
            None => {
                let then_type = self.analyze_function_branch_return(then_branch);
                let else_type = self.analyze_function_branch_return(else_branch);
                (then_type, else_type)
            }
        };
        self.assignment_qualifier_context.pop();
        self.block_depth -= 1;

        let then_type = then_type?;
        let else_type = else_type?;
        let pine_type =
            self.merge_branch_types(condition_type, then_type, else_type, condition_value, span)?;
        if pine_type.kind == ValueKind::UserType
            && self
                .user_type_name_of_if_branches(then_branch, else_branch)
                .is_none()
        {
            self.diagnostics.push(Diagnostic::error(
                "E_BRANCH_TYPE",
                "if user-defined type branches must resolve to the same local UDT",
                span,
            ));
            return None;
        }
        if pine_type.kind == ValueKind::Map && !self.mark_if_map(span, then_branch, else_branch) {
            self.diagnostics.push(Diagnostic::error(
                "E_BRANCH_TYPE",
                "if map branches must resolve to the same map template",
                span,
            ));
            return None;
        }
        if pine_type.kind == ValueKind::UserTypeArray
            && !self.mark_if_user_type_array(span, then_branch, else_branch)
        {
            self.diagnostics.push(Diagnostic::error(
                "E_BRANCH_TYPE",
                "if UDT array branches must resolve to the same element identity",
                span,
            ));
            return None;
        }
        Some(pine_type)
    }

    fn analyze_function_branch_return(&mut self, branch: &[Stmt]) -> Option<PineType> {
        let (last, prefix) = branch.split_last()?;
        self.scope.push_scope();
        for statement in prefix {
            self.analyze_stmt(statement);
        }
        let pine_type = match &last.kind {
            StmtKind::Expr(expr) => self.analyze_expr(expr),
            StmtKind::For {
                counter,
                from,
                to,
                step,
                body,
            } => self.analyze_for_expr(counter, from, to, step.as_ref(), body, last.span),
            StmtKind::ForIn {
                index,
                value,
                iterable,
                body,
            } => self.analyze_for_in_expr(index.as_deref(), value, iterable, body, last.span),
            StmtKind::While { condition, body } => {
                self.analyze_while_expr(condition, body, last.span)
            }
            _ => None,
        };
        self.scope.pop_scope();
        pine_type
    }

    pub(crate) fn report_udf_arg_error(
        &mut self,
        function_name: &str,
        call_span: Span,
        expected: usize,
        got: usize,
        error: UdfArgError,
    ) {
        match error {
            UdfArgError::UnknownName { name, span } => {
                self.diagnostics.push(Diagnostic::error(
                    "E_FUNCTION_ARG_NAME",
                    format!("`{function_name}` has no argument named `{name}`"),
                    span,
                ));
            }
            UdfArgError::Duplicate { name, span } => {
                self.diagnostics.push(Diagnostic::error(
                    "E_FUNCTION_ARG_DUPLICATE",
                    format!("`{function_name}` argument `{name}` is provided more than once"),
                    span,
                ));
            }
            UdfArgError::PositionalAfterNamed { span } => {
                self.diagnostics.push(Diagnostic::error(
                    "E_FUNCTION_ARG_ORDER",
                    "positional arguments cannot follow named arguments in user-defined function calls",
                    span,
                ));
            }
            UdfArgError::TooMany { span } => {
                self.diagnostics.push(Diagnostic::error(
                    "E_FUNCTION_ARITY",
                    format!("`{function_name}` expects {expected} argument(s), got {got}"),
                    span,
                ));
            }
            UdfArgError::Missing { param } => {
                self.diagnostics.push(Diagnostic::error(
                    "E_FUNCTION_ARITY",
                    format!("`{function_name}` is missing argument `{param}`"),
                    call_span,
                ));
            }
        }
    }
}
