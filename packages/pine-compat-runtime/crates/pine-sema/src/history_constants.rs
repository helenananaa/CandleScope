use std::{collections::HashMap, rc::Rc};

use pine_ir::{
    HirBinaryOp, HirExpr, HirExprKind, HirLiteral, HirStmt, HirStmtKind, HirSwitchArm,
    HirSwitchStmtArm, HirUnaryOp, SymbolId, ValueKind,
};

use crate::constant_values::{ConstValue, eval_pure_const_call, exact_i64_from_numeric};

#[derive(Debug)]
pub(crate) struct ConstSymbolBinding<'a> {
    expr: &'a HirExpr,
    // A binding must retain the symbol values that were visible when it was
    // assigned. Re-evaluating an alias against the latest environment would
    // make a later reassignment retroactively change its value.
    env: Rc<ConstSymbolEnv<'a>>,
}

pub(crate) type ConstSymbolEnv<'a> = HashMap<SymbolId, Rc<ConstSymbolBinding<'a>>>;

pub(crate) fn insert_const_symbol<'a>(
    env: &mut ConstSymbolEnv<'a>,
    symbol: SymbolId,
    expr: &'a HirExpr,
) {
    let captured_env = Rc::new(env.clone());
    env.insert(
        symbol,
        Rc::new(ConstSymbolBinding {
            expr,
            env: captured_env,
        }),
    );
}

pub(crate) fn constant_hir_int_with_symbols(
    expr: &HirExpr,
    env: &ConstSymbolEnv<'_>,
) -> Option<i64> {
    let mut visiting = Vec::new();
    constant_hir_int_with_env(expr, Some(env), &mut visiting).or_else(|| {
        (expr.pine_type.kind == ValueKind::Int)
            .then(|| constant_hir_numeric_with_env(expr, Some(env), &mut visiting))
            .flatten()
            .and_then(exact_i64_from_numeric)
    })
}

fn constant_hir_int_with_env(
    expr: &HirExpr,
    env: Option<&ConstSymbolEnv<'_>>,
    visiting: &mut Vec<usize>,
) -> Option<i64> {
    match &expr.kind {
        HirExprKind::Literal(HirLiteral::Int(value)) => Some(*value),
        HirExprKind::Builtin(name) => pine_builtins::named_int_constant(name),
        HirExprKind::Symbol(symbol) => {
            with_symbol_value(*symbol, env, visiting, constant_hir_int_with_env)
        }
        HirExprKind::Unary {
            op: HirUnaryOp::Plus,
            expr,
        } => constant_hir_int_with_env(expr, env, visiting),
        HirExprKind::Unary {
            op: HirUnaryOp::Minus,
            expr,
        } => constant_hir_int_with_env(expr, env, visiting).and_then(i64::checked_neg),
        HirExprKind::Binary {
            op: HirBinaryOp::Add,
            left,
            right,
        } => constant_hir_int_with_env(left, env, visiting)?
            .checked_add(constant_hir_int_with_env(right, env, visiting)?),
        HirExprKind::Binary {
            op: HirBinaryOp::Sub,
            left,
            right,
        } => constant_hir_int_with_env(left, env, visiting)?
            .checked_sub(constant_hir_int_with_env(right, env, visiting)?),
        HirExprKind::Binary {
            op: HirBinaryOp::Mul,
            left,
            right,
        } => constant_hir_int_with_env(left, env, visiting)?
            .checked_mul(constant_hir_int_with_env(right, env, visiting)?),
        HirExprKind::Binary {
            op: HirBinaryOp::Mod,
            left,
            right,
        } => constant_hir_int_with_env(left, env, visiting)?
            .checked_rem(constant_hir_int_with_env(right, env, visiting)?),
        HirExprKind::Ternary {
            condition,
            then_expr,
            else_expr,
        } => match constant_hir_bool_with_env(condition, env, visiting) {
            Some(true) => constant_hir_int_with_env(then_expr, env, visiting),
            Some(false) => constant_hir_int_with_env(else_expr, env, visiting),
            None => {
                let then_value = constant_hir_int_with_env(then_expr, env, visiting)?;
                let else_value = constant_hir_int_with_env(else_expr, env, visiting)?;
                (then_value == else_value).then_some(then_value)
            }
        },
        HirExprKind::Block { statements, result } => {
            let Some(block_env) = block_const_symbol_env(statements, env) else {
                return constant_hir_int_with_env(result, env, visiting);
            };
            constant_hir_int_with_env(result, Some(&block_env), visiting)
        }
        HirExprKind::Switch { selector, arms } => constant_switch_result_with_env(
            selector.as_deref(),
            arms,
            env,
            visiting,
            constant_hir_int_with_env,
        ),
        HirExprKind::For {
            from,
            to,
            step,
            statements,
            result,
            ..
        } => constant_for_result_with_env(
            HirForConstParts {
                from,
                to,
                step: step.as_deref(),
                statements,
                result,
            },
            env,
            visiting,
            constant_hir_int_with_env,
        ),
        HirExprKind::FieldAccess { value, index } => constant_hir_field_value_with_env(
            value,
            *index,
            env,
            visiting,
            constant_hir_int_with_env,
        ),
        HirExprKind::Call { callee, args, .. } => {
            constant_hir_call_value_with_env(callee, args, env, visiting)?.as_int()
        }
        _ => None,
    }
}

fn constant_hir_call_value_with_env(
    callee: &str,
    args: &[pine_ir::HirCallArg],
    env: Option<&ConstSymbolEnv<'_>>,
    visiting: &mut Vec<usize>,
) -> Option<ConstValue> {
    let args = args
        .iter()
        .map(|arg| constant_hir_scalar_value_with_env(&arg.value, env, visiting))
        .collect::<Option<Vec<_>>>()?;
    eval_pure_const_call(callee, &args)
}

fn constant_hir_scalar_value_with_env(
    expr: &HirExpr,
    env: Option<&ConstSymbolEnv<'_>>,
    visiting: &mut Vec<usize>,
) -> Option<ConstValue> {
    match expr.pine_type.kind {
        ValueKind::Int => constant_hir_int_with_env(expr, env, visiting)
            .map(ConstValue::Int)
            .or_else(|| constant_hir_numeric_with_env(expr, env, visiting).map(ConstValue::Float)),
        ValueKind::Float => {
            constant_hir_numeric_with_env(expr, env, visiting).map(ConstValue::Float)
        }
        ValueKind::Bool => constant_hir_bool_with_env(expr, env, visiting).map(ConstValue::Bool),
        _ => None,
    }
}

fn with_symbol_value<T>(
    symbol: SymbolId,
    env: Option<&ConstSymbolEnv<'_>>,
    visiting: &mut Vec<usize>,
    value_of: fn(&HirExpr, Option<&ConstSymbolEnv<'_>>, &mut Vec<usize>) -> Option<T>,
) -> Option<T> {
    let binding = env?.get(&symbol)?;
    let binding_id = Rc::as_ptr(binding) as usize;
    if visiting.contains(&binding_id) {
        return None;
    }
    visiting.push(binding_id);
    let result = value_of(binding.expr, Some(binding.env.as_ref()), visiting);
    visiting.pop();
    result
}

fn constant_hir_bool_with_env(
    expr: &HirExpr,
    env: Option<&ConstSymbolEnv<'_>>,
    visiting: &mut Vec<usize>,
) -> Option<bool> {
    match &expr.kind {
        HirExprKind::Literal(HirLiteral::Bool(value)) => Some(*value),
        HirExprKind::Symbol(symbol) => {
            with_symbol_value(*symbol, env, visiting, constant_hir_bool_with_env)
        }
        HirExprKind::Unary {
            op: HirUnaryOp::Not,
            expr,
        } => constant_hir_bool_with_env(expr, env, visiting).map(|value| !value),
        HirExprKind::Binary {
            op: HirBinaryOp::And,
            left,
            right,
        } => match constant_hir_bool_with_env(left, env, visiting)? {
            false => Some(false),
            true => constant_hir_bool_with_env(right, env, visiting),
        },
        HirExprKind::Binary {
            op: HirBinaryOp::Or,
            left,
            right,
        } => match constant_hir_bool_with_env(left, env, visiting)? {
            true => Some(true),
            false => constant_hir_bool_with_env(right, env, visiting),
        },
        HirExprKind::Ternary {
            condition,
            then_expr,
            else_expr,
        } => match constant_hir_bool_with_env(condition, env, visiting) {
            Some(true) => constant_hir_bool_with_env(then_expr, env, visiting),
            Some(false) => constant_hir_bool_with_env(else_expr, env, visiting),
            None => {
                let then_value = constant_hir_bool_with_env(then_expr, env, visiting)?;
                let else_value = constant_hir_bool_with_env(else_expr, env, visiting)?;
                (then_value == else_value).then_some(then_value)
            }
        },
        HirExprKind::Block { statements, result } => {
            let Some(block_env) = block_const_symbol_env(statements, env) else {
                return constant_hir_bool_with_env(result, env, visiting);
            };
            constant_hir_bool_with_env(result, Some(&block_env), visiting)
        }
        HirExprKind::Switch { selector, arms } => constant_switch_result_with_env(
            selector.as_deref(),
            arms,
            env,
            visiting,
            constant_hir_bool_with_env,
        ),
        HirExprKind::For {
            from,
            to,
            step,
            statements,
            result,
            ..
        } => constant_for_result_with_env(
            HirForConstParts {
                from,
                to,
                step: step.as_deref(),
                statements,
                result,
            },
            env,
            visiting,
            constant_hir_bool_with_env,
        ),
        HirExprKind::FieldAccess { value, index } => constant_hir_field_value_with_env(
            value,
            *index,
            env,
            visiting,
            constant_hir_bool_with_env,
        ),
        HirExprKind::Call { callee, args, .. } => {
            match constant_hir_call_value_with_env(callee, args, env, visiting)? {
                ConstValue::Bool(value) => Some(value),
                ConstValue::Int(_) | ConstValue::Float(_) => None,
            }
        }
        HirExprKind::Binary {
            op:
                op @ (HirBinaryOp::Eq
                | HirBinaryOp::NotEq
                | HirBinaryOp::Gt
                | HirBinaryOp::Gte
                | HirBinaryOp::Lt
                | HirBinaryOp::Lte),
            left,
            right,
        } => constant_hir_numeric_comparison_with_env(*op, left, right, env, visiting)
            .or_else(|| {
                constant_hir_bool_comparison(
                    *op,
                    constant_hir_bool_with_env(left, env, visiting)?,
                    constant_hir_bool_with_env(right, env, visiting)?,
                )
            })
            .or_else(|| {
                constant_hir_string_comparison(
                    *op,
                    &constant_hir_string_with_env(left, env, visiting)?,
                    &constant_hir_string_with_env(right, env, visiting)?,
                )
            })
            .or_else(|| {
                constant_hir_color_comparison(
                    *op,
                    constant_hir_color_with_env(left, env, visiting)?,
                    constant_hir_color_with_env(right, env, visiting)?,
                )
            }),
        _ => None,
    }
}

fn constant_hir_numeric_with_env(
    expr: &HirExpr,
    env: Option<&ConstSymbolEnv<'_>>,
    visiting: &mut Vec<usize>,
) -> Option<f64> {
    match &expr.kind {
        HirExprKind::Literal(HirLiteral::Int(value)) => Some(*value as f64),
        HirExprKind::Literal(HirLiteral::Float(value)) => Some(*value),
        HirExprKind::Builtin(name) => named_hir_numeric_constant(name),
        HirExprKind::Symbol(symbol) => {
            with_symbol_value(*symbol, env, visiting, constant_hir_numeric_with_env)
        }
        HirExprKind::Unary {
            op: HirUnaryOp::Plus,
            expr,
        } => constant_hir_numeric_with_env(expr, env, visiting),
        HirExprKind::Unary {
            op: HirUnaryOp::Minus,
            expr,
        } => constant_hir_numeric_with_env(expr, env, visiting).map(|value| -value),
        HirExprKind::Binary {
            op: HirBinaryOp::Add,
            left,
            right,
        } => Some(
            constant_hir_numeric_with_env(left, env, visiting)?
                + constant_hir_numeric_with_env(right, env, visiting)?,
        ),
        HirExprKind::Binary {
            op: HirBinaryOp::Sub,
            left,
            right,
        } => Some(
            constant_hir_numeric_with_env(left, env, visiting)?
                - constant_hir_numeric_with_env(right, env, visiting)?,
        ),
        HirExprKind::Binary {
            op: HirBinaryOp::Mul,
            left,
            right,
        } => Some(
            constant_hir_numeric_with_env(left, env, visiting)?
                * constant_hir_numeric_with_env(right, env, visiting)?,
        ),
        HirExprKind::Binary {
            op: HirBinaryOp::Div,
            left,
            right,
        } => finite_hir_numeric(
            constant_hir_numeric_with_env(left, env, visiting)?
                / constant_hir_numeric_with_env(right, env, visiting)?,
        ),
        HirExprKind::Binary {
            op: HirBinaryOp::Mod,
            left,
            right,
        } => finite_hir_numeric(
            constant_hir_numeric_with_env(left, env, visiting)?
                % constant_hir_numeric_with_env(right, env, visiting)?,
        ),
        HirExprKind::Ternary {
            condition,
            then_expr,
            else_expr,
        } => match constant_hir_bool_with_env(condition, env, visiting) {
            Some(true) => constant_hir_numeric_with_env(then_expr, env, visiting),
            Some(false) => constant_hir_numeric_with_env(else_expr, env, visiting),
            None => {
                let then_value = constant_hir_numeric_with_env(then_expr, env, visiting)?;
                let else_value = constant_hir_numeric_with_env(else_expr, env, visiting)?;
                (then_value == else_value).then_some(then_value)
            }
        },
        HirExprKind::Block { statements, result } => {
            let Some(block_env) = block_const_symbol_env(statements, env) else {
                return constant_hir_numeric_with_env(result, env, visiting);
            };
            constant_hir_numeric_with_env(result, Some(&block_env), visiting)
        }
        HirExprKind::Switch { selector, arms } => constant_switch_result_with_env(
            selector.as_deref(),
            arms,
            env,
            visiting,
            constant_hir_numeric_with_env,
        ),
        HirExprKind::For {
            from,
            to,
            step,
            statements,
            result,
            ..
        } => constant_for_result_with_env(
            HirForConstParts {
                from,
                to,
                step: step.as_deref(),
                statements,
                result,
            },
            env,
            visiting,
            constant_hir_numeric_with_env,
        ),
        HirExprKind::FieldAccess { value, index } => constant_hir_field_value_with_env(
            value,
            *index,
            env,
            visiting,
            constant_hir_numeric_with_env,
        ),
        HirExprKind::Call { callee, args, .. } => {
            constant_hir_call_value_with_env(callee, args, env, visiting)?.as_numeric()
        }
        _ => None,
    }
}

fn named_hir_numeric_constant(name: &str) -> Option<f64> {
    pine_builtins::named_float_constant(name)
        .or_else(|| pine_builtins::named_int_constant(name).map(|value| value as f64))
}

fn finite_hir_numeric(value: f64) -> Option<f64> {
    value.is_finite().then_some(value)
}

fn block_const_symbol_env<'a>(
    statements: &'a [HirStmt],
    outer: Option<&ConstSymbolEnv<'a>>,
) -> Option<ConstSymbolEnv<'a>> {
    let mut env = outer.cloned().unwrap_or_default();
    for statement in statements {
        match &statement.kind {
            HirStmtKind::Expr(_) => {}
            HirStmtKind::Decl { symbol, value } => {
                insert_const_symbol(&mut env, *symbol, value);
            }
            HirStmtKind::TupleDecl { symbols, value } => {
                let HirExprKind::Tuple(values) = &value.kind else {
                    return None;
                };
                if symbols.len() != values.len() {
                    return None;
                }
                for (symbol, value) in symbols.iter().zip(values) {
                    insert_const_symbol(&mut env, *symbol, value);
                }
            }
            HirStmtKind::Reassign { symbol, .. } | HirStmtKind::FieldReassign { symbol, .. } => {
                env.remove(symbol);
            }
            HirStmtKind::ArrayFieldReassign { array, .. } => {
                if let HirExprKind::Symbol(symbol) = array.kind {
                    env.remove(&symbol);
                }
            }
            statement @ (HirStmtKind::If { .. }
            | HirStmtKind::Switch { .. }
            | HirStmtKind::For { .. }
            | HirStmtKind::ForIn { .. }
            | HirStmtKind::While { .. }) => {
                remove_reassigned_symbols_from_env(&mut env, statement);
            }
            HirStmtKind::Break | HirStmtKind::Continue => return None,
        }
    }
    Some(env)
}

pub(crate) fn remove_reassigned_symbols_from_env(
    env: &mut ConstSymbolEnv<'_>,
    statement: &HirStmtKind,
) {
    match statement {
        HirStmtKind::Reassign { symbol, .. } | HirStmtKind::FieldReassign { symbol, .. } => {
            env.remove(symbol);
        }
        HirStmtKind::ArrayFieldReassign { array, .. } => {
            if let HirExprKind::Symbol(symbol) = array.kind {
                env.remove(&symbol);
            }
        }
        HirStmtKind::If {
            then_branch,
            else_branch,
            ..
        } => {
            for statement in then_branch.iter().chain(else_branch) {
                remove_reassigned_symbols_from_env(env, &statement.kind);
            }
        }
        HirStmtKind::Switch { arms, .. } => {
            for statement in switch_stmt_arm_bodies(arms) {
                remove_reassigned_symbols_from_env(env, &statement.kind);
            }
        }
        HirStmtKind::For { counter, body, .. } => {
            env.remove(counter);
            for statement in body {
                remove_reassigned_symbols_from_env(env, &statement.kind);
            }
        }
        HirStmtKind::ForIn {
            index, value, body, ..
        } => {
            if let Some(index) = index {
                env.remove(index);
            }
            env.remove(value);
            for statement in body {
                remove_reassigned_symbols_from_env(env, &statement.kind);
            }
        }
        HirStmtKind::While { body, .. } => {
            for statement in body {
                remove_reassigned_symbols_from_env(env, &statement.kind);
            }
        }
        HirStmtKind::Expr(_)
        | HirStmtKind::Decl { .. }
        | HirStmtKind::TupleDecl { .. }
        | HirStmtKind::Break
        | HirStmtKind::Continue => {}
    }
}

fn constant_hir_string_with_env(
    expr: &HirExpr,
    env: Option<&ConstSymbolEnv<'_>>,
    visiting: &mut Vec<usize>,
) -> Option<String> {
    match &expr.kind {
        HirExprKind::Literal(HirLiteral::String(value)) => Some(value.clone()),
        HirExprKind::Builtin(name) => pine_builtins::named_string_constant(name).map(str::to_owned),
        HirExprKind::Symbol(symbol) => {
            with_symbol_value(*symbol, env, visiting, constant_hir_string_with_env)
        }
        HirExprKind::Ternary {
            condition,
            then_expr,
            else_expr,
        } => match constant_hir_bool_with_env(condition, env, visiting) {
            Some(true) => constant_hir_string_with_env(then_expr, env, visiting),
            Some(false) => constant_hir_string_with_env(else_expr, env, visiting),
            None => {
                let then_value = constant_hir_string_with_env(then_expr, env, visiting)?;
                let else_value = constant_hir_string_with_env(else_expr, env, visiting)?;
                (then_value == else_value).then_some(then_value)
            }
        },
        HirExprKind::Block { statements, result } => {
            let Some(block_env) = block_const_symbol_env(statements, env) else {
                return constant_hir_string_with_env(result, env, visiting);
            };
            constant_hir_string_with_env(result, Some(&block_env), visiting)
        }
        HirExprKind::Switch { selector, arms } => constant_switch_result_with_env(
            selector.as_deref(),
            arms,
            env,
            visiting,
            constant_hir_string_with_env,
        ),
        HirExprKind::For {
            from,
            to,
            step,
            statements,
            result,
            ..
        } => constant_for_result_with_env(
            HirForConstParts {
                from,
                to,
                step: step.as_deref(),
                statements,
                result,
            },
            env,
            visiting,
            constant_hir_string_with_env,
        ),
        HirExprKind::FieldAccess { value, index } => constant_hir_field_value_with_env(
            value,
            *index,
            env,
            visiting,
            constant_hir_string_with_env,
        ),
        _ => None,
    }
}

fn constant_hir_color_with_env(
    expr: &HirExpr,
    env: Option<&ConstSymbolEnv<'_>>,
    visiting: &mut Vec<usize>,
) -> Option<u32> {
    match &expr.kind {
        HirExprKind::Literal(HirLiteral::ColorHex(value)) => parse_color_hex(value),
        HirExprKind::Builtin(name) => pine_builtins::named_color(name),
        HirExprKind::Symbol(symbol) => {
            with_symbol_value(*symbol, env, visiting, constant_hir_color_with_env)
        }
        HirExprKind::Ternary {
            condition,
            then_expr,
            else_expr,
        } => match constant_hir_bool_with_env(condition, env, visiting) {
            Some(true) => constant_hir_color_with_env(then_expr, env, visiting),
            Some(false) => constant_hir_color_with_env(else_expr, env, visiting),
            None => {
                let then_value = constant_hir_color_with_env(then_expr, env, visiting)?;
                let else_value = constant_hir_color_with_env(else_expr, env, visiting)?;
                (then_value == else_value).then_some(then_value)
            }
        },
        HirExprKind::Block { statements, result } => {
            let Some(block_env) = block_const_symbol_env(statements, env) else {
                return constant_hir_color_with_env(result, env, visiting);
            };
            constant_hir_color_with_env(result, Some(&block_env), visiting)
        }
        HirExprKind::Switch { selector, arms } => constant_switch_result_with_env(
            selector.as_deref(),
            arms,
            env,
            visiting,
            constant_hir_color_with_env,
        ),
        HirExprKind::For {
            from,
            to,
            step,
            statements,
            result,
            ..
        } => constant_for_result_with_env(
            HirForConstParts {
                from,
                to,
                step: step.as_deref(),
                statements,
                result,
            },
            env,
            visiting,
            constant_hir_color_with_env,
        ),
        HirExprKind::FieldAccess { value, index } => constant_hir_field_value_with_env(
            value,
            *index,
            env,
            visiting,
            constant_hir_color_with_env,
        ),
        _ => None,
    }
}

fn constant_hir_field_value_with_env<T>(
    value: &HirExpr,
    index: usize,
    env: Option<&ConstSymbolEnv<'_>>,
    visiting: &mut Vec<usize>,
    value_of: fn(&HirExpr, Option<&ConstSymbolEnv<'_>>, &mut Vec<usize>) -> Option<T>,
) -> Option<T>
where
    T: PartialEq,
{
    match &value.kind {
        HirExprKind::UserTypeConstruct { fields, .. } => {
            value_of(fields.get(index)?, env, visiting)
        }
        HirExprKind::Symbol(symbol) => {
            let binding = env?.get(symbol)?;
            let binding_id = Rc::as_ptr(binding) as usize;
            if visiting.contains(&binding_id) {
                return None;
            }
            visiting.push(binding_id);
            let result = constant_hir_field_value_with_env(
                binding.expr,
                index,
                Some(binding.env.as_ref()),
                visiting,
                value_of,
            );
            visiting.pop();
            result
        }
        HirExprKind::FieldAccess {
            value,
            index: inner_index,
        } => {
            let resolved = constant_hir_field_expr_with_env(value, *inner_index, env, visiting)?;
            constant_hir_field_value_with_env(
                resolved.expr,
                index,
                resolved.env.as_deref(),
                visiting,
                value_of,
            )
        }
        HirExprKind::Block { statements, result } => {
            let Some(block_env) = block_const_symbol_env(statements, env) else {
                return constant_hir_field_value_with_env(result, index, env, visiting, value_of);
            };
            constant_hir_field_value_with_env(result, index, Some(&block_env), visiting, value_of)
        }
        HirExprKind::Ternary {
            condition,
            then_expr,
            else_expr,
        } => match constant_hir_bool_with_env(condition, env, visiting) {
            Some(true) => {
                constant_hir_field_value_with_env(then_expr, index, env, visiting, value_of)
            }
            Some(false) => {
                constant_hir_field_value_with_env(else_expr, index, env, visiting, value_of)
            }
            None => {
                let then_value =
                    constant_hir_field_value_with_env(then_expr, index, env, visiting, value_of)?;
                let else_value =
                    constant_hir_field_value_with_env(else_expr, index, env, visiting, value_of)?;
                (then_value == else_value).then_some(then_value)
            }
        },
        HirExprKind::Switch { selector, arms } => constant_switch_result_with_env(
            selector.as_deref(),
            arms,
            env,
            visiting,
            |value, env, visiting| {
                constant_hir_field_value_with_env(value, index, env, visiting, value_of)
            },
        ),
        HirExprKind::For {
            from,
            to,
            step,
            statements,
            result,
            ..
        } => constant_for_result_with_env(
            HirForConstParts {
                from,
                to,
                step: step.as_deref(),
                statements,
                result,
            },
            env,
            visiting,
            |value, env, visiting| {
                constant_hir_field_value_with_env(value, index, env, visiting, value_of)
            },
        ),
        _ => None,
    }
}

struct ResolvedConstHirExpr<'a> {
    expr: &'a HirExpr,
    env: Option<Rc<ConstSymbolEnv<'a>>>,
}

fn constant_hir_field_expr_with_env<'a>(
    value: &'a HirExpr,
    index: usize,
    env: Option<&ConstSymbolEnv<'a>>,
    visiting: &mut Vec<usize>,
) -> Option<ResolvedConstHirExpr<'a>> {
    match &value.kind {
        HirExprKind::UserTypeConstruct { fields, .. } => Some(ResolvedConstHirExpr {
            expr: fields.get(index)?,
            env: env.cloned().map(Rc::new),
        }),
        HirExprKind::Symbol(symbol) => {
            let binding = env?.get(symbol)?;
            let binding_id = Rc::as_ptr(binding) as usize;
            if visiting.contains(&binding_id) {
                return None;
            }
            visiting.push(binding_id);
            let result = constant_hir_field_expr_with_env(
                binding.expr,
                index,
                Some(binding.env.as_ref()),
                visiting,
            );
            visiting.pop();
            result
        }
        HirExprKind::FieldAccess {
            value,
            index: inner_index,
        } => {
            let resolved = constant_hir_field_expr_with_env(value, *inner_index, env, visiting)?;
            constant_hir_field_expr_with_env(
                resolved.expr,
                index,
                resolved.env.as_deref(),
                visiting,
            )
        }
        _ => None,
    }
}

struct HirForConstParts<'a> {
    from: &'a HirExpr,
    to: &'a HirExpr,
    step: Option<&'a HirExpr>,
    statements: &'a [HirStmt],
    result: &'a HirExpr,
}

fn constant_for_result_with_env<T, F>(
    parts: HirForConstParts<'_>,
    env: Option<&ConstSymbolEnv<'_>>,
    visiting: &mut Vec<usize>,
    value_of: F,
) -> Option<T>
where
    F: Fn(&HirExpr, Option<&ConstSymbolEnv<'_>>, &mut Vec<usize>) -> Option<T> + Copy,
{
    constant_hir_int_with_env(parts.from, env, visiting)?;
    constant_hir_int_with_env(parts.to, env, visiting)?;
    if let Some(step) = parts.step
        && constant_hir_int_with_env(step, env, visiting)? == 0
    {
        return None;
    }
    if contains_loop_control(parts.statements) {
        return None;
    }
    let block_env = block_const_symbol_env(parts.statements, env)?;
    value_of(parts.result, Some(&block_env), visiting)
}

fn contains_loop_control(statements: &[HirStmt]) -> bool {
    statements
        .iter()
        .any(|statement| statement_contains_loop_control(&statement.kind))
}

fn switch_stmt_arm_bodies(arms: &[HirSwitchStmtArm]) -> impl Iterator<Item = &HirStmt> {
    arms.iter().flat_map(|arm| arm.body.iter())
}

fn statement_contains_loop_control(statement: &HirStmtKind) -> bool {
    match statement {
        HirStmtKind::Break | HirStmtKind::Continue => true,
        HirStmtKind::If {
            then_branch,
            else_branch,
            ..
        } => contains_loop_control(then_branch) || contains_loop_control(else_branch),
        HirStmtKind::For { body, .. }
        | HirStmtKind::ForIn { body, .. }
        | HirStmtKind::While { body, .. } => contains_loop_control(body),
        HirStmtKind::Switch { arms, .. } => switch_stmt_arm_bodies(arms)
            .any(|statement| statement_contains_loop_control(&statement.kind)),
        HirStmtKind::Expr(_)
        | HirStmtKind::Decl { .. }
        | HirStmtKind::Reassign { .. }
        | HirStmtKind::FieldReassign { .. }
        | HirStmtKind::ArrayFieldReassign { .. }
        | HirStmtKind::TupleDecl { .. } => false,
    }
}

#[derive(Debug, Clone, PartialEq)]
enum ConstSwitchValue {
    Numeric(f64),
    Bool(bool),
    String(String),
    Color(u32),
}

fn constant_hir_switch_value(
    expr: &HirExpr,
    env: Option<&ConstSymbolEnv<'_>>,
    visiting: &mut Vec<usize>,
) -> Option<ConstSwitchValue> {
    constant_hir_bool_with_env(expr, env, visiting)
        .map(ConstSwitchValue::Bool)
        .or_else(|| constant_hir_string_with_env(expr, env, visiting).map(ConstSwitchValue::String))
        .or_else(|| constant_hir_color_with_env(expr, env, visiting).map(ConstSwitchValue::Color))
        .or_else(|| {
            constant_hir_numeric_with_env(expr, env, visiting).map(ConstSwitchValue::Numeric)
        })
}

fn constant_switch_values_equal(
    left: &ConstSwitchValue,
    right: &HirExpr,
    env: Option<&ConstSymbolEnv<'_>>,
    visiting: &mut Vec<usize>,
) -> Option<bool> {
    let right = constant_hir_switch_value(right, env, visiting)?;
    Some(match (left, right) {
        (ConstSwitchValue::Numeric(left), ConstSwitchValue::Numeric(right)) => *left == right,
        (ConstSwitchValue::Bool(left), ConstSwitchValue::Bool(right)) => *left == right,
        (ConstSwitchValue::String(left), ConstSwitchValue::String(right)) => *left == right,
        (ConstSwitchValue::Color(left), ConstSwitchValue::Color(right)) => *left == right,
        _ => false,
    })
}

fn constant_switch_result_with_env<T, F>(
    selector: Option<&HirExpr>,
    arms: &[HirSwitchArm],
    env: Option<&ConstSymbolEnv<'_>>,
    visiting: &mut Vec<usize>,
    value_of: F,
) -> Option<T>
where
    T: PartialEq,
    F: Fn(&HirExpr, Option<&ConstSymbolEnv<'_>>, &mut Vec<usize>) -> Option<T> + Copy,
{
    if let Some(selector) = selector {
        let Some(selector_value) = constant_hir_switch_value(selector, env, visiting) else {
            return constant_all_switch_results_with_default(arms, env, visiting, value_of);
        };
        for (index, arm) in arms.iter().enumerate() {
            match &arm.condition {
                Some(condition) => {
                    match constant_switch_values_equal(&selector_value, condition, env, visiting) {
                        Some(true) => return value_of(&arm.result, env, visiting),
                        Some(false) => {}
                        None => {
                            return constant_all_switch_results_with_default(
                                &arms[index..],
                                env,
                                visiting,
                                value_of,
                            );
                        }
                    }
                }
                None => return value_of(&arm.result, env, visiting),
            }
        }
        return None;
    }

    for (index, arm) in arms.iter().enumerate() {
        match &arm.condition {
            Some(condition) => match constant_hir_bool_with_env(condition, env, visiting) {
                Some(true) => return value_of(&arm.result, env, visiting),
                Some(false) => {}
                None => {
                    return constant_all_switch_results_with_default(
                        &arms[index..],
                        env,
                        visiting,
                        value_of,
                    );
                }
            },
            None => return value_of(&arm.result, env, visiting),
        }
    }
    None
}

fn constant_all_switch_results_with_default<T, F>(
    arms: &[HirSwitchArm],
    env: Option<&ConstSymbolEnv<'_>>,
    visiting: &mut Vec<usize>,
    value_of: F,
) -> Option<T>
where
    T: PartialEq,
    F: Fn(&HirExpr, Option<&ConstSymbolEnv<'_>>, &mut Vec<usize>) -> Option<T> + Copy,
{
    if !arms.iter().any(|arm| arm.condition.is_none()) {
        return None;
    }
    let mut expected = None;
    for arm in arms {
        let value = value_of(&arm.result, env, visiting)?;
        match &expected {
            Some(expected) if *expected != value => return None,
            Some(_) => {}
            None => expected = Some(value),
        }
    }
    expected
}

fn parse_color_hex(value: &str) -> Option<u32> {
    u32::from_str_radix(value.trim_start_matches('#'), 16).ok()
}

fn constant_hir_numeric_comparison_with_env(
    op: HirBinaryOp,
    left: &HirExpr,
    right: &HirExpr,
    env: Option<&ConstSymbolEnv<'_>>,
    visiting: &mut Vec<usize>,
) -> Option<bool> {
    let left = constant_hir_numeric_with_env(left, env, visiting)?;
    let right = constant_hir_numeric_with_env(right, env, visiting)?;
    Some(match op {
        HirBinaryOp::Eq => left == right,
        HirBinaryOp::NotEq => left != right,
        HirBinaryOp::Gt => left > right,
        HirBinaryOp::Gte => left >= right,
        HirBinaryOp::Lt => left < right,
        HirBinaryOp::Lte => left <= right,
        _ => return None,
    })
}

fn constant_hir_string_comparison(op: HirBinaryOp, left: &str, right: &str) -> Option<bool> {
    Some(match op {
        HirBinaryOp::Eq => left == right,
        HirBinaryOp::NotEq => left != right,
        _ => return None,
    })
}

fn constant_hir_color_comparison(op: HirBinaryOp, left: u32, right: u32) -> Option<bool> {
    Some(match op {
        HirBinaryOp::Eq => left == right,
        HirBinaryOp::NotEq => left != right,
        _ => return None,
    })
}

fn constant_hir_bool_comparison(op: HirBinaryOp, left: bool, right: bool) -> Option<bool> {
    Some(match op {
        HirBinaryOp::Eq => left == right,
        HirBinaryOp::NotEq => left != right,
        _ => return None,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use pine_ir::{HirUserTypeIdentity, PineType, Qualifier, ValueKind};

    fn const_int_expr(kind: HirExprKind) -> HirExpr {
        HirExpr {
            kind,
            pine_type: PineType::new(Qualifier::Const, ValueKind::Int),
            series_id: None,
        }
    }

    fn const_user_type_expr(kind: HirExprKind) -> HirExpr {
        HirExpr {
            kind,
            pine_type: PineType::new(Qualifier::Const, ValueKind::UserType),
            series_id: None,
        }
    }

    fn user_type_construct(fields: Vec<HirExpr>) -> HirExpr {
        const_user_type_expr(HirExprKind::UserTypeConstruct {
            identity: HirUserTypeIdentity {
                source_id: 0,
                type_name: "Box".to_owned(),
            },
            fields,
        })
    }

    #[test]
    fn resolves_alias_chain_int_symbols() {
        let base_symbol = SymbolId(1);
        let base = const_int_expr(HirExprKind::Literal(HirLiteral::Int(8)));
        let length = const_int_expr(HirExprKind::Binary {
            op: HirBinaryOp::Add,
            left: Box::new(const_int_expr(HirExprKind::Symbol(base_symbol))),
            right: Box::new(const_int_expr(HirExprKind::Literal(HirLiteral::Int(2)))),
        });
        let mut env = ConstSymbolEnv::new();
        insert_const_symbol(&mut env, base_symbol, &base);

        assert_eq!(constant_hir_int_with_symbols(&length, &env), Some(10));
    }

    #[test]
    fn returns_none_for_unbound_forward_symbol() {
        let first_symbol = SymbolId(1);
        let second_symbol = SymbolId(2);
        let first = const_int_expr(HirExprKind::Symbol(second_symbol));
        let second = const_int_expr(HirExprKind::Symbol(first_symbol));
        let mut env = ConstSymbolEnv::new();
        insert_const_symbol(&mut env, first_symbol, &first);
        insert_const_symbol(&mut env, second_symbol, &second);

        assert_eq!(constant_hir_int_with_symbols(&first, &env), None);
    }

    #[test]
    fn aliases_keep_the_value_visible_at_declaration_time() {
        let base_symbol = SymbolId(1);
        let alias_symbol = SymbolId(2);
        let base_two = const_int_expr(HirExprKind::Literal(HirLiteral::Int(2)));
        let alias = const_int_expr(HirExprKind::Symbol(base_symbol));
        let base_five = const_int_expr(HirExprKind::Literal(HirLiteral::Int(5)));
        let alias_use = const_int_expr(HirExprKind::Symbol(alias_symbol));
        let mut env = ConstSymbolEnv::new();

        insert_const_symbol(&mut env, base_symbol, &base_two);
        insert_const_symbol(&mut env, alias_symbol, &alias);
        insert_const_symbol(&mut env, base_symbol, &base_five);

        assert_eq!(constant_hir_int_with_symbols(&alias_use, &env), Some(2));
    }

    #[test]
    fn self_reassignment_uses_the_previous_binding_version() {
        let symbol = SymbolId(1);
        let initial = const_int_expr(HirExprKind::Literal(HirLiteral::Int(2)));
        let incremented = const_int_expr(HirExprKind::Binary {
            op: HirBinaryOp::Add,
            left: Box::new(const_int_expr(HirExprKind::Symbol(symbol))),
            right: Box::new(const_int_expr(HirExprKind::Literal(HirLiteral::Int(1)))),
        });
        let symbol_use = const_int_expr(HirExprKind::Symbol(symbol));
        let mut env = ConstSymbolEnv::new();

        insert_const_symbol(&mut env, symbol, &initial);
        insert_const_symbol(&mut env, symbol, &incremented);

        assert_eq!(constant_hir_int_with_symbols(&symbol_use, &env), Some(3));
    }

    #[test]
    fn nested_user_type_aliases_keep_their_assignment_time_environment() {
        let inner_symbol = SymbolId(1);
        let outer_symbol = SymbolId(2);
        let initial_inner = user_type_construct(vec![const_int_expr(HirExprKind::Literal(
            HirLiteral::Int(2),
        ))]);
        let outer = user_type_construct(vec![const_user_type_expr(HirExprKind::Symbol(
            inner_symbol,
        ))]);
        let reassigned_inner = user_type_construct(vec![const_int_expr(HirExprKind::Literal(
            HirLiteral::Int(5),
        ))]);
        let outer_inner = const_user_type_expr(HirExprKind::FieldAccess {
            value: Box::new(const_user_type_expr(HirExprKind::Symbol(outer_symbol))),
            index: 0,
        });
        let nested_length = const_int_expr(HirExprKind::FieldAccess {
            value: Box::new(outer_inner),
            index: 0,
        });
        let mut env = ConstSymbolEnv::new();

        insert_const_symbol(&mut env, inner_symbol, &initial_inner);
        insert_const_symbol(&mut env, outer_symbol, &outer);
        insert_const_symbol(&mut env, inner_symbol, &reassigned_inner);

        assert_eq!(constant_hir_int_with_symbols(&nested_length, &env), Some(2));
    }
}
