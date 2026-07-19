use super::*;
use std::collections::HashMap;

#[derive(Clone, Copy)]
pub(super) enum BodyFieldKind {
    Local,
    Imported,
}

pub(super) struct BodyFieldContext<'a> {
    pub(super) analyzer: &'a Analyzer,
    pub(super) receiver_path: &'a str,
    pub(super) result_type_name: &'a str,
    pub(super) field_keys: &'a mut HashMap<String, String>,
    pub(super) udf_stack: &'a mut Vec<String>,
    pub(super) kind: BodyFieldKind,
}

pub(super) fn collect_body_field_param_keys(
    context: &mut BodyFieldContext<'_>,
    body: &FunctionBody,
    param_keys: &HashMap<String, String>,
) -> Option<()> {
    match body {
        FunctionBody::Expr(expr) => collect_body_result_field_param_keys(context, expr, param_keys),
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
                        let mut accepted_decl = false;
                        let field_aliases = alias_field_param_keys(name, value, &local_keys);
                        if !field_aliases.is_empty() {
                            local_keys.extend(field_aliases);
                            accepted_decl = true;
                        } else if let Some(type_name) =
                            context.analyzer.user_type_name_of_expr(value)
                            && let Some(field_keys) = field_param_keys_for_user_type_expr(
                                context.analyzer,
                                name,
                                value,
                                &type_name,
                                &local_keys,
                                context.udf_stack,
                            )
                        {
                            local_keys.extend(field_keys);
                            accepted_decl = true;
                        }
                        if let Some(value_key) = pure_expr_series_key_with_params(
                            context.analyzer,
                            value,
                            &local_keys,
                            true,
                            context.udf_stack,
                        ) {
                            if local_keys.insert(name.clone(), value_key).is_some() {
                                return None;
                            }
                            accepted_decl = true;
                        }
                        if !accepted_decl {
                            return None;
                        }
                    }
                    StmtKind::Expr(expr) => {
                        pure_expr_series_key_with_params(
                            context.analyzer,
                            expr,
                            &local_keys,
                            true,
                            context.udf_stack,
                        )?;
                    }
                    _ => return None,
                }
            }
            collect_body_result_field_param_keys(context, result, &local_keys)
        }
    }
}

fn collect_body_result_field_param_keys(
    context: &mut BodyFieldContext<'_>,
    expr: &Expr,
    param_keys: &HashMap<String, String>,
) -> Option<()> {
    match context.kind {
        BodyFieldKind::Local => collect_user_type_field_param_keys_with_params(
            context.analyzer,
            context.receiver_path,
            expr,
            context.result_type_name,
            context.field_keys,
            param_keys,
            context.udf_stack,
        ),
        BodyFieldKind::Imported => collect_imported_user_type_field_param_keys_with_params(
            context.analyzer,
            context.receiver_path,
            expr,
            context.result_type_name,
            context.field_keys,
            param_keys,
            context.udf_stack,
        ),
    }
}
