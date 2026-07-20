use pine_ir::{
    HirCallArg, HirExpr, HirExprKind, HirLiteral, HirProgram, HirStmt, HirStmtKind, HirUnaryOp,
    ValueKind,
};

use crate::PineValue;

#[derive(Debug, Clone, PartialEq)]
pub struct InputCall {
    pub call_site_id: u32,
    pub name: String,
    /// The analyzer-resolved value kind returned by this input call.
    ///
    /// This is especially important for the generic legacy `input()` form:
    /// hosts must parse overrides according to the resolved `defval` type
    /// instead of guessing from a textual override.
    pub value_kind: ValueKind,
    pub title: Option<String>,
    pub default_value: Option<PineValue>,
    pub min_value: Option<PineValue>,
    pub max_value: Option<PineValue>,
    pub step: Option<PineValue>,
    pub options: Vec<PineValue>,
}

#[must_use]
pub fn input_calls(program: &HirProgram) -> Vec<InputCall> {
    let mut calls = Vec::new();
    collect_input_calls_from_stmts(&program.statements, &mut calls);
    calls
}

fn collect_input_calls_from_stmts(statements: &[HirStmt], calls: &mut Vec<InputCall>) {
    for statement in statements {
        match &statement.kind {
            HirStmtKind::Expr(expr)
            | HirStmtKind::Decl { value: expr, .. }
            | HirStmtKind::Reassign { value: expr, .. }
            | HirStmtKind::FieldReassign { value: expr, .. }
            | HirStmtKind::TupleDecl { value: expr, .. } => {
                collect_input_calls_from_expr(expr, calls);
            }
            HirStmtKind::ArrayFieldReassign {
                array,
                index,
                value,
                ..
            } => {
                collect_input_calls_from_expr(array, calls);
                collect_input_calls_from_expr(index, calls);
                collect_input_calls_from_expr(value, calls);
            }
            HirStmtKind::If {
                condition,
                then_branch,
                else_branch,
            } => {
                collect_input_calls_from_expr(condition, calls);
                collect_input_calls_from_stmts(then_branch, calls);
                collect_input_calls_from_stmts(else_branch, calls);
            }
            HirStmtKind::Switch { selector, arms } => {
                if let Some(selector) = selector {
                    collect_input_calls_from_expr(selector, calls);
                }
                for arm in arms {
                    if let Some(condition) = &arm.condition {
                        collect_input_calls_from_expr(condition, calls);
                    }
                    collect_input_calls_from_stmts(&arm.body, calls);
                }
            }
            HirStmtKind::For {
                from,
                to,
                step,
                body,
                ..
            } => {
                collect_input_calls_from_expr(from, calls);
                collect_input_calls_from_expr(to, calls);
                if let Some(step) = step {
                    collect_input_calls_from_expr(step, calls);
                }
                collect_input_calls_from_stmts(body, calls);
            }
            HirStmtKind::ForIn { iterable, body, .. } => {
                collect_input_calls_from_expr(iterable, calls);
                collect_input_calls_from_stmts(body, calls);
            }
            HirStmtKind::While { condition, body } => {
                collect_input_calls_from_expr(condition, calls);
                collect_input_calls_from_stmts(body, calls);
            }
            HirStmtKind::Break | HirStmtKind::Continue => {}
        }
    }
}

fn collect_input_calls_from_expr(expr: &HirExpr, calls: &mut Vec<InputCall>) {
    match &expr.kind {
        HirExprKind::Call {
            callee,
            call_site_id,
            args,
        } => {
            if is_input_call(callee) {
                calls.push(InputCall {
                    call_site_id: call_site_id.0,
                    name: callee.clone(),
                    value_kind: expr.pine_type.kind,
                    title: input_title(args),
                    default_value: input_arg_value(args, 0, "defval"),
                    min_value: matches!(
                        callee.as_str(),
                        "input.int" | "input.float" | "input.price" | "input.time"
                    )
                    .then(|| input_arg_value(args, 2, "minval"))
                    .flatten(),
                    max_value: matches!(
                        callee.as_str(),
                        "input.int" | "input.float" | "input.price" | "input.time"
                    )
                    .then(|| input_arg_value(args, 3, "maxval"))
                    .flatten(),
                    step: matches!(
                        callee.as_str(),
                        "input.int" | "input.float" | "input.price" | "input.time"
                    )
                    .then(|| input_arg_value(args, 4, "step"))
                    .flatten(),
                    options: input_options(callee, args),
                });
            }
            for arg in args {
                collect_input_calls_from_expr(&arg.value, calls);
            }
        }
        HirExprKind::Unary { expr, .. }
        | HirExprKind::FieldAccess { value: expr, .. }
        | HirExprKind::History { expr, .. } => collect_input_calls_from_expr(expr, calls),
        HirExprKind::Binary { left, right, .. } => {
            collect_input_calls_from_expr(left, calls);
            collect_input_calls_from_expr(right, calls);
        }
        HirExprKind::Ternary {
            condition,
            then_expr,
            else_expr,
        } => {
            collect_input_calls_from_expr(condition, calls);
            collect_input_calls_from_expr(then_expr, calls);
            collect_input_calls_from_expr(else_expr, calls);
        }
        HirExprKind::Switch { selector, arms } => {
            if let Some(selector) = selector {
                collect_input_calls_from_expr(selector, calls);
            }
            for arm in arms {
                if let Some(condition) = &arm.condition {
                    collect_input_calls_from_expr(condition, calls);
                }
                collect_input_calls_from_expr(&arm.result, calls);
            }
        }
        HirExprKind::For {
            from,
            to,
            step,
            statements,
            result,
            ..
        } => {
            collect_input_calls_from_expr(from, calls);
            collect_input_calls_from_expr(to, calls);
            if let Some(step) = step {
                collect_input_calls_from_expr(step, calls);
            }
            collect_input_calls_from_stmts(statements, calls);
            collect_input_calls_from_expr(result, calls);
        }
        HirExprKind::ForIn {
            iterable,
            statements,
            result,
            ..
        } => {
            collect_input_calls_from_expr(iterable, calls);
            collect_input_calls_from_stmts(statements, calls);
            collect_input_calls_from_expr(result, calls);
        }
        HirExprKind::While {
            condition,
            statements,
            result,
        } => {
            collect_input_calls_from_expr(condition, calls);
            collect_input_calls_from_stmts(statements, calls);
            collect_input_calls_from_expr(result, calls);
        }
        HirExprKind::Tuple(values)
        | HirExprKind::UserTypeConstruct { fields: values, .. }
        | HirExprKind::UserTypeArrayConstruct {
            elements: values, ..
        } => {
            for value in values {
                collect_input_calls_from_expr(value, calls);
            }
        }
        HirExprKind::Block { statements, result } => {
            collect_input_calls_from_stmts(statements, calls);
            collect_input_calls_from_expr(result, calls);
        }
        HirExprKind::Literal(_) | HirExprKind::Symbol(_) | HirExprKind::Builtin(_) => {}
    }
}

fn is_input_call(name: &str) -> bool {
    name == "input" || name.starts_with("input.")
}

fn input_title(args: &[HirCallArg]) -> Option<String> {
    input_arg(args, 1, "title").and_then(|expr| match &expr.kind {
        HirExprKind::Literal(HirLiteral::String(value)) => Some(value.clone()),
        _ => None,
    })
}

fn input_arg<'a>(args: &'a [HirCallArg], index: usize, name: &str) -> Option<&'a HirExpr> {
    args.iter()
        .find(|arg| arg.name.as_deref() == Some(name))
        .or_else(|| args.get(index).filter(|arg| arg.name.is_none()))
        .map(|arg| &arg.value)
}

fn input_arg_value(args: &[HirCallArg], index: usize, name: &str) -> Option<PineValue> {
    input_arg(args, index, name).and_then(constant_value)
}

fn input_options(name: &str, args: &[HirCallArg]) -> Vec<PineValue> {
    let index = if matches!(
        name,
        "input"
            | "input.int"
            | "input.float"
            | "input.price"
            | "input.time"
            | "input.string"
            | "input.symbol"
            | "input.timeframe"
            | "input.session"
    ) {
        if matches!(
            name,
            "input.int" | "input.float" | "input.price" | "input.time"
        ) {
            5
        } else {
            2
        }
    } else {
        return Vec::new();
    };
    let Some(expr) = input_arg(args, index, "options") else {
        return Vec::new();
    };
    match &expr.kind {
        HirExprKind::Tuple(values) => values.iter().filter_map(constant_value).collect(),
        _ => Vec::new(),
    }
}

fn constant_value(expr: &HirExpr) -> Option<PineValue> {
    match &expr.kind {
        HirExprKind::Literal(HirLiteral::Int(value)) => Some(PineValue::Int(*value)),
        HirExprKind::Literal(HirLiteral::Float(value)) => Some(PineValue::Float(*value)),
        HirExprKind::Literal(HirLiteral::Bool(value)) => Some(PineValue::Bool(*value)),
        HirExprKind::Literal(HirLiteral::String(value)) => Some(PineValue::String(value.clone())),
        HirExprKind::Literal(HirLiteral::ColorHex(value)) => Some(PineValue::String(value.clone())),
        HirExprKind::Builtin(value) => Some(PineValue::String(value.clone())),
        HirExprKind::Unary { op, expr } => {
            let value = constant_value(expr)?;
            match (op, value) {
                (HirUnaryOp::Plus, value @ (PineValue::Int(_) | PineValue::Float(_))) => {
                    Some(value)
                }
                (HirUnaryOp::Minus, PineValue::Int(value)) => Some(PineValue::Int(-value)),
                (HirUnaryOp::Minus, PineValue::Float(value)) => Some(PineValue::Float(-value)),
                (HirUnaryOp::Not, PineValue::Bool(value)) => Some(PineValue::Bool(!value)),
                _ => None,
            }
        }
        _ => None,
    }
}
