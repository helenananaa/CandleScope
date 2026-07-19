use pine_ir::{HirCallArg, HirExpr, HirExprKind, HirLiteral, HirProgram, HirStmt, HirStmtKind};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InputCall {
    pub call_site_id: u32,
    pub name: String,
    pub title: Option<String>,
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
                    title: input_title(args),
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
    args.iter()
        .find(|arg| arg.name.as_deref() == Some("title"))
        .or_else(|| args.get(1))
        .and_then(|arg| match &arg.value.kind {
            HirExprKind::Literal(HirLiteral::String(value)) => Some(value.clone()),
            _ => None,
        })
}
