use std::collections::HashMap;

use pine_syntax::{Expr, ExprKind, FunctionBody, Stmt, StmtKind, SwitchArmResult};

use super::UserTypeIdentity;
use crate::analyzer::calls::expr_name;
use crate::analyzer::context::FunctionInfo;
use crate::analyzer::functions::resolve_udf_arg_indices;

pub(super) fn returned_udf_param_index(
    body: &FunctionBody,
    params: &[String],
    functions: &HashMap<String, FunctionInfo>,
    depth: usize,
) -> Option<usize> {
    if depth > params.len() + functions.len() {
        return None;
    }
    match body {
        FunctionBody::Expr(expr) => returned_expr_param_index(expr, params, functions, depth),
        FunctionBody::Block(statements) => {
            returned_statements_param_index(statements, params, functions, &HashMap::new(), depth)
        }
    }
}

fn returned_statements_param_index(
    statements: &[Stmt],
    params: &[String],
    functions: &HashMap<String, FunctionInfo>,
    outer_aliases: &HashMap<String, String>,
    depth: usize,
) -> Option<usize> {
    let (last, prefix) = statements.split_last()?;
    let mut aliases = outer_aliases.clone();
    for statement in prefix {
        if let StmtKind::Decl { name, value, .. } = &statement.kind
            && let Some(source_name) = identifier_name(value)
        {
            aliases.insert(name.clone(), source_name.clone());
        }
    }
    match &last.kind {
        StmtKind::Expr(expr) => {
            returned_expr_param_index_with_aliases(expr, params, functions, &aliases, depth)
        }
        StmtKind::If {
            then_branch,
            else_branch,
            ..
        } => {
            let then_index =
                returned_statements_param_index(then_branch, params, functions, &aliases, depth)?;
            let else_index =
                returned_statements_param_index(else_branch, params, functions, &aliases, depth)?;
            (then_index == else_index).then_some(then_index)
        }
        StmtKind::For { body, .. } => {
            returned_statements_param_index(body, params, functions, &aliases, depth)
        }
        StmtKind::ForIn { body, .. } => {
            returned_statements_param_index(body, params, functions, &aliases, depth)
        }
        StmtKind::While { body, .. } => {
            returned_statements_param_index(body, params, functions, &aliases, depth)
        }
        _ => None,
    }
}

fn returned_expr_param_index(
    expr: &Expr,
    params: &[String],
    functions: &HashMap<String, FunctionInfo>,
    depth: usize,
) -> Option<usize> {
    returned_expr_param_index_with_aliases(expr, params, functions, &HashMap::new(), depth)
}

fn returned_expr_param_index_with_aliases(
    expr: &Expr,
    params: &[String],
    functions: &HashMap<String, FunctionInfo>,
    aliases: &HashMap<String, String>,
    depth: usize,
) -> Option<usize> {
    if let Some(returned_name) = identifier_name(expr) {
        return aliased_param_index(returned_name, params, aliases);
    }
    match &expr.kind {
        ExprKind::Call { callee, args } => {
            let callee_name = expr_name(callee)?;
            let function = functions.get(&callee_name)?;
            let returned_param_index =
                returned_udf_param_index(&function.body, &function.params, functions, depth + 1)?;
            let arg_indices = resolve_udf_arg_indices(&function.params, args).ok()?;
            let arg_index = arg_indices
                .iter()
                .position(|mapped_param_index| *mapped_param_index == returned_param_index)?;
            returned_expr_param_index_with_aliases(
                &args[arg_index].value,
                params,
                functions,
                aliases,
                depth,
            )
        }
        ExprKind::Ternary {
            then_expr,
            else_expr,
            ..
        } => {
            let then_index = returned_expr_param_index_with_aliases(
                then_expr, params, functions, aliases, depth,
            )?;
            let else_index = returned_expr_param_index_with_aliases(
                else_expr, params, functions, aliases, depth,
            )?;
            (then_index == else_index).then_some(then_index)
        }
        ExprKind::Switch { arms, .. } => {
            let mut resolved = None;
            for arm in arms {
                let index = returned_switch_arm_param_index(
                    &arm.result,
                    params,
                    functions,
                    aliases,
                    depth,
                )?;
                if resolved.is_some_and(|resolved| resolved != index) {
                    return None;
                }
                resolved = Some(index);
            }
            resolved
        }
        _ => None,
    }
}

fn returned_switch_arm_param_index(
    result: &SwitchArmResult,
    params: &[String],
    functions: &HashMap<String, FunctionInfo>,
    aliases: &HashMap<String, String>,
    depth: usize,
) -> Option<usize> {
    match result {
        SwitchArmResult::Expr(expr) => {
            returned_expr_param_index_with_aliases(expr, params, functions, aliases, depth)
        }
        SwitchArmResult::Block(statements) => {
            returned_statements_param_index(statements, params, functions, aliases, depth)
        }
    }
}

fn aliased_param_index(
    returned_name: &str,
    params: &[String],
    aliases: &HashMap<String, String>,
) -> Option<usize> {
    let mut name = returned_name.to_owned();
    for _ in 0..=aliases.len() {
        if let Some(index) = params.iter().position(|param| param == &name) {
            return Some(index);
        }
        name = aliases.get(&name)?.clone();
    }
    None
}

fn identifier_name(expr: &Expr) -> Option<&String> {
    let ExprKind::Identifier(name) = &expr.kind else {
        return None;
    };
    Some(name)
}

pub(super) fn is_na_expr(expr: &Expr) -> bool {
    match &expr.kind {
        ExprKind::Identifier(name) => name == "na",
        ExprKind::QualifiedName(parts) if parts.len() == 1 => parts[0] == "na",
        _ => false,
    }
}

pub(super) fn user_type_identity_matches_name(
    identity: &UserTypeIdentity,
    type_name: &str,
) -> bool {
    identity.name == type_name
        || type_name
            .strip_suffix(&format!(".{}", identity.name))
            .is_some_and(|prefix| !prefix.is_empty())
}

pub(super) fn branch_return_expr(branch: &[Stmt]) -> Option<(&[Stmt], &Expr)> {
    let (last, prefix) = branch.split_last()?;
    let StmtKind::Expr(expr) = &last.kind else {
        return None;
    };
    Some((prefix, expr))
}

pub(super) fn merge_user_type_name(
    resolved: &mut Option<String>,
    type_name: Option<String>,
    is_na: bool,
) -> Option<()> {
    match type_name {
        Some(type_name) if resolved.as_ref().is_some_and(|name| name != &type_name) => None,
        Some(type_name) => {
            resolved.get_or_insert(type_name);
            Some(())
        }
        None => is_na.then_some(()),
    }
}
