use super::*;

pub(super) fn function_body_has_side_effect(body: &FunctionBody) -> bool {
    match body {
        FunctionBody::Expr(expr) => contains_output_or_declaration_call(expr),
        FunctionBody::Block(statements) => {
            block_return_contains_output_or_declaration_call(statements)
        }
    }
}

fn block_return_contains_output_or_declaration_call(statements: &[Stmt]) -> bool {
    let Some((last, prefix)) = statements.split_last() else {
        return false;
    };
    prefix
        .iter()
        .any(statement_contains_output_or_declaration_call)
        || return_statement_contains_output_or_declaration_call(last)
}

fn return_statement_contains_output_or_declaration_call(statement: &Stmt) -> bool {
    match &statement.kind {
        StmtKind::Expr(expr) => return_expr_contains_output_or_declaration_call(expr),
        StmtKind::If {
            condition,
            then_branch,
            else_branch,
        } => {
            contains_output_or_declaration_call(condition)
                || block_return_contains_output_or_declaration_call(then_branch)
                || block_return_contains_output_or_declaration_call(else_branch)
        }
        StmtKind::For {
            from,
            to,
            step,
            body,
            ..
        } => {
            contains_output_or_declaration_call(from)
                || contains_output_or_declaration_call(to)
                || step
                    .as_ref()
                    .is_some_and(contains_output_or_declaration_call)
                || block_return_contains_output_or_declaration_call(body)
        }
        StmtKind::ForIn { iterable, body, .. } => {
            contains_output_or_declaration_call(iterable)
                || block_return_contains_output_or_declaration_call(body)
        }
        StmtKind::While { condition, body } => {
            contains_output_or_declaration_call(condition)
                || block_return_contains_output_or_declaration_call(body)
        }
        _ => statement_contains_output_or_declaration_call(statement),
    }
}

fn return_expr_contains_output_or_declaration_call(expr: &Expr) -> bool {
    match &expr.kind {
        ExprKind::If {
            condition,
            then_branch,
            else_branch,
        } => {
            contains_output_or_declaration_call(condition)
                || block_return_contains_output_or_declaration_call(then_branch)
                || block_return_contains_output_or_declaration_call(else_branch)
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
                || block_return_contains_output_or_declaration_call(body)
        }
        ExprKind::ForIn { iterable, body, .. } => {
            contains_output_or_declaration_call(iterable)
                || block_return_contains_output_or_declaration_call(body)
        }
        ExprKind::While { condition, body } => {
            contains_output_or_declaration_call(condition)
                || block_return_contains_output_or_declaration_call(body)
        }
        ExprKind::Switch { selector, arms } => {
            selector
                .as_deref()
                .is_some_and(contains_output_or_declaration_call)
                || arms.iter().any(|arm| {
                    arm.condition
                        .as_ref()
                        .is_some_and(contains_output_or_declaration_call)
                        || switch_arm_return_contains_output_or_declaration_call(&arm.result)
                })
        }
        ExprKind::Ternary {
            condition,
            then_expr,
            else_expr,
        } => {
            contains_output_or_declaration_call(condition)
                || return_expr_contains_output_or_declaration_call(then_expr)
                || return_expr_contains_output_or_declaration_call(else_expr)
        }
        ExprKind::Unary { expr, .. } | ExprKind::History { expr, .. } => {
            return_expr_contains_output_or_declaration_call(expr)
        }
        ExprKind::Binary { left, right, .. } => {
            return_expr_contains_output_or_declaration_call(left)
                || return_expr_contains_output_or_declaration_call(right)
        }
        ExprKind::Tuple(items) => items
            .iter()
            .any(return_expr_contains_output_or_declaration_call),
        _ => contains_output_or_declaration_call(expr),
    }
}

fn switch_arm_return_contains_output_or_declaration_call(result: &SwitchArmResult) -> bool {
    match result {
        SwitchArmResult::Expr(expr) => return_expr_contains_output_or_declaration_call(expr),
        SwitchArmResult::Block(statements) => {
            block_return_contains_output_or_declaration_call(statements)
        }
    }
}

pub(super) fn first_statement_span(program: &Program) -> Option<Span> {
    program.statements.first().map(|statement| statement.span)
}

pub(super) fn visit_statement_exprs(statement: &Stmt, visitor: &mut impl FnMut(&Expr)) {
    match &statement.kind {
        StmtKind::Expr(expr)
        | StmtKind::Decl { value: expr, .. }
        | StmtKind::Reassign { value: expr, .. }
        | StmtKind::FieldReassign { value: expr, .. }
        | StmtKind::TupleDecl { value: expr, .. } => visit_expr(expr, visitor),
        StmtKind::ArrayFieldReassign {
            array,
            index,
            value,
            ..
        } => {
            visit_expr(array, visitor);
            visit_expr(index, visitor);
            visit_expr(value, visitor);
        }
        StmtKind::If {
            condition,
            then_branch,
            else_branch,
        } => {
            visit_expr(condition, visitor);
            for statement in then_branch.iter().chain(else_branch) {
                visit_statement_exprs(statement, visitor);
            }
        }
        StmtKind::For {
            from,
            to,
            step,
            body,
            ..
        } => {
            visit_expr(from, visitor);
            visit_expr(to, visitor);
            if let Some(step) = step {
                visit_expr(step, visitor);
            }
            for statement in body {
                visit_statement_exprs(statement, visitor);
            }
        }
        StmtKind::While { condition, body } => {
            visit_expr(condition, visitor);
            for statement in body {
                visit_statement_exprs(statement, visitor);
            }
        }
        StmtKind::ForIn { iterable, body, .. } => {
            visit_expr(iterable, visitor);
            for statement in body {
                visit_statement_exprs(statement, visitor);
            }
        }
        StmtKind::Export(export) => match &export.item {
            ExportItem::Const { value, .. } => visit_expr(value, visitor),
            ExportItem::Function { body, .. } => visit_function_body(body, visitor),
            ExportItem::UserType { .. } => {}
            ExportItem::Unknown { .. } => {}
        },
        StmtKind::Method(method) => visit_function_body(&method.body, visitor),
        StmtKind::Import(_)
        | StmtKind::Library(_)
        | StmtKind::UserType(_)
        | StmtKind::Break
        | StmtKind::Continue
        | StmtKind::Function { .. }
        | StmtKind::Unsupported { .. } => {}
    }
}

fn visit_function_body(body: &FunctionBody, visitor: &mut impl FnMut(&Expr)) {
    match body {
        FunctionBody::Expr(expr) => visit_expr(expr, visitor),
        FunctionBody::Block(statements) => {
            for statement in statements {
                visit_statement_exprs(statement, visitor);
            }
        }
    }
}

fn visit_expr(expr: &Expr, visitor: &mut impl FnMut(&Expr)) {
    visitor(expr);
    match &expr.kind {
        ExprKind::Unary { expr, .. } | ExprKind::History { expr, .. } => visit_expr(expr, visitor),
        ExprKind::Binary { left, right, .. } => {
            visit_expr(left, visitor);
            visit_expr(right, visitor);
        }
        ExprKind::Ternary {
            condition,
            then_expr,
            else_expr,
        } => {
            visit_expr(condition, visitor);
            visit_expr(then_expr, visitor);
            visit_expr(else_expr, visitor);
        }
        ExprKind::If {
            condition,
            then_branch,
            else_branch,
        } => {
            visit_expr(condition, visitor);
            for statement in then_branch.iter().chain(else_branch) {
                visit_statement_exprs(statement, visitor);
            }
        }
        ExprKind::For {
            from,
            to,
            step,
            body,
            ..
        } => {
            visit_expr(from, visitor);
            visit_expr(to, visitor);
            if let Some(step) = step {
                visit_expr(step, visitor);
            }
            for statement in body {
                visit_statement_exprs(statement, visitor);
            }
        }
        ExprKind::ForIn { iterable, body, .. } => {
            visit_expr(iterable, visitor);
            for statement in body {
                visit_statement_exprs(statement, visitor);
            }
        }
        ExprKind::While { condition, body } => {
            visit_expr(condition, visitor);
            for statement in body {
                visit_statement_exprs(statement, visitor);
            }
        }
        ExprKind::Switch { selector, arms } => {
            if let Some(selector) = selector {
                visit_expr(selector, visitor);
            }
            for arm in arms {
                if let Some(condition) = &arm.condition {
                    visit_expr(condition, visitor);
                }
                match &arm.result {
                    SwitchArmResult::Expr(result) => visit_expr(result, visitor),
                    SwitchArmResult::Block(statements) => {
                        for statement in statements {
                            visit_statement_exprs(statement, visitor);
                        }
                    }
                }
            }
        }
        ExprKind::Tuple(items) => {
            for item in items {
                visit_expr(item, visitor);
            }
        }
        ExprKind::Call { callee, args } => {
            visit_expr(callee, visitor);
            for arg in args {
                visit_expr(&arg.value, visitor);
            }
        }
        ExprKind::Literal(_) | ExprKind::Identifier(_) | ExprKind::QualifiedName(_) => {}
    }
}
