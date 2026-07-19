use std::collections::{HashMap, HashSet};

use pine_syntax::{
    CallArg, DeclaredType, ExportDecl, ExportItem, Expr, ExprKind, FunctionBody, Program, Stmt,
    StmtKind, SwitchArm, SwitchArmResult,
};

use crate::analyzer::calls::{expr_name, postfix_call_result_method_parts};

#[derive(Clone, Default)]
pub(super) struct RewriteContext {
    pub(super) constants: HashMap<String, Expr>,
    pub(super) function_targets: HashMap<String, String>,
    pub(super) type_targets: HashMap<String, String>,
    shadowed_names: HashSet<String>,
}

pub(super) fn rewrite_program(program: &Program, context: &RewriteContext) -> Program {
    Program {
        version: program.version,
        statements: rewrite_statements(&program.statements, context),
    }
}

fn rewrite_statements(statements: &[Stmt], context: &RewriteContext) -> Vec<Stmt> {
    let mut scoped_context = context.clone();
    let mut rewritten = Vec::with_capacity(statements.len());
    for statement in statements {
        rewritten.push(rewrite_stmt(statement, &scoped_context));
        record_statement_bindings(statement, &mut scoped_context);
    }
    rewritten
}

fn rewrite_stmt(statement: &Stmt, context: &RewriteContext) -> Stmt {
    let kind = match &statement.kind {
        StmtKind::Expr(expr) => StmtKind::Expr(rewrite_expr(expr, context)),
        StmtKind::If {
            condition,
            then_branch,
            else_branch,
        } => StmtKind::If {
            condition: rewrite_expr(condition, context),
            then_branch: rewrite_statements(then_branch, context),
            else_branch: rewrite_statements(else_branch, context),
        },
        StmtKind::For {
            counter,
            from,
            to,
            step,
            body,
        } => StmtKind::For {
            counter: counter.clone(),
            from: rewrite_expr(from, context),
            to: rewrite_expr(to, context),
            step: step.as_ref().map(|step| rewrite_expr(step, context)),
            body: {
                let body_context = context.shadowing(counter);
                rewrite_statements(body, &body_context)
            },
        },
        StmtKind::While { condition, body } => StmtKind::While {
            condition: rewrite_expr(condition, context),
            body: rewrite_statements(body, context),
        },
        StmtKind::ForIn {
            index,
            value,
            iterable,
            body,
        } => StmtKind::ForIn {
            index: index.clone(),
            value: value.clone(),
            iterable: rewrite_expr(iterable, context),
            body: {
                let body_context = if let Some(index) = index {
                    context.shadowing(index).shadowing(value)
                } else {
                    context.shadowing(value)
                };
                rewrite_statements(body, &body_context)
            },
        },
        StmtKind::Decl {
            mode,
            declared_type,
            name,
            value,
        } => StmtKind::Decl {
            mode: *mode,
            declared_type: declared_type
                .as_ref()
                .map(|declared_type| rewrite_declared_type(declared_type, context)),
            name: name.clone(),
            value: rewrite_expr(value, context),
        },
        StmtKind::Reassign { name, value } => StmtKind::Reassign {
            name: name.clone(),
            value: rewrite_expr(value, context),
        },
        StmtKind::FieldReassign {
            receiver,
            field,
            value,
        } => StmtKind::FieldReassign {
            receiver: receiver.clone(),
            field: field.clone(),
            value: rewrite_expr(value, context),
        },
        StmtKind::ArrayFieldReassign {
            array,
            index,
            field,
            value,
        } => StmtKind::ArrayFieldReassign {
            array: rewrite_expr(array, context),
            index: rewrite_expr(index, context),
            field: field.clone(),
            value: rewrite_expr(value, context),
        },
        StmtKind::TupleDecl { names, value } => StmtKind::TupleDecl {
            names: names.clone(),
            value: rewrite_expr(value, context),
        },
        StmtKind::Export(export) => {
            let item = match &export.item {
                ExportItem::Function {
                    name,
                    params,
                    body,
                    span,
                } => ExportItem::Function {
                    name: name.clone(),
                    params: params.clone(),
                    body: {
                        let param_names = function_param_names(params);
                        rewrite_function_body(body, &param_names, context)
                    },
                    span: *span,
                },
                ExportItem::Const { name, value, span } => ExportItem::Const {
                    name: name.clone(),
                    value: rewrite_expr(value, context),
                    span: *span,
                },
                ExportItem::UserType { decl, span } => ExportItem::UserType {
                    decl: decl.clone(),
                    span: *span,
                },
                ExportItem::Unknown { span } => ExportItem::Unknown { span: *span },
            };
            StmtKind::Export(ExportDecl { item })
        }
        StmtKind::Function { name, params, body } => StmtKind::Function {
            name: name.clone(),
            params: params.clone(),
            body: {
                let param_names = function_param_names(params);
                rewrite_function_body(body, &param_names, context)
            },
        },
        StmtKind::Import(_)
        | StmtKind::Library(_)
        | StmtKind::UserType(_)
        | StmtKind::Method(_)
        | StmtKind::Break
        | StmtKind::Continue
        | StmtKind::Unsupported { .. } => statement.kind.clone(),
    };
    Stmt {
        kind,
        span: statement.span,
    }
}

pub(super) fn rewrite_function_body(
    body: &FunctionBody,
    params: &[String],
    context: &RewriteContext,
) -> FunctionBody {
    let context = context.shadowing_all(params);
    match body {
        FunctionBody::Expr(expr) => FunctionBody::Expr(rewrite_expr(expr, &context)),
        FunctionBody::Block(statements) => {
            FunctionBody::Block(rewrite_statements(statements, &context))
        }
    }
}

fn function_param_names(params: &[pine_syntax::FunctionParam]) -> Vec<String> {
    params.iter().map(|param| param.name.clone()).collect()
}

pub(super) fn rewrite_expr(expr: &Expr, context: &RewriteContext) -> Expr {
    if let Some(name) = expr_name(expr)
        && let Some(value) = context.constant(&name)
    {
        return value.clone();
    }

    let kind = match &expr.kind {
        ExprKind::Call { callee, args } => {
            let postfix_call_result_method =
                postfix_call_result_method_parts(callee, args).is_some();
            let callee = if !postfix_call_result_method
                && let Some(name) = expr_name(callee)
                && let Some(target) = context.function_target(&name)
            {
                Expr {
                    kind: ExprKind::Identifier(target.clone()),
                    span: callee.span,
                }
            } else if let Some(name) = expr_name(callee)
                && let Some(target) = rewrite_array_new_type_target(&name, context)
            {
                Expr {
                    kind: ExprKind::Identifier(target),
                    span: callee.span,
                }
            } else {
                rewrite_expr(callee, context)
            };
            ExprKind::Call {
                callee: Box::new(callee),
                args: args
                    .iter()
                    .map(|arg| CallArg {
                        name: arg.name.clone(),
                        value: rewrite_expr(&arg.value, context),
                        span: arg.span,
                    })
                    .collect(),
            }
        }
        ExprKind::Unary { op, expr } => ExprKind::Unary {
            op: *op,
            expr: Box::new(rewrite_expr(expr, context)),
        },
        ExprKind::Binary { op, left, right } => ExprKind::Binary {
            op: *op,
            left: Box::new(rewrite_expr(left, context)),
            right: Box::new(rewrite_expr(right, context)),
        },
        ExprKind::Ternary {
            condition,
            then_expr,
            else_expr,
        } => ExprKind::Ternary {
            condition: Box::new(rewrite_expr(condition, context)),
            then_expr: Box::new(rewrite_expr(then_expr, context)),
            else_expr: Box::new(rewrite_expr(else_expr, context)),
        },
        ExprKind::If {
            condition,
            then_branch,
            else_branch,
        } => ExprKind::If {
            condition: Box::new(rewrite_expr(condition, context)),
            then_branch: rewrite_statements(then_branch, context),
            else_branch: rewrite_statements(else_branch, context),
        },
        ExprKind::For {
            counter,
            from,
            to,
            step,
            body,
        } => ExprKind::For {
            counter: counter.clone(),
            from: Box::new(rewrite_expr(from, context)),
            to: Box::new(rewrite_expr(to, context)),
            step: step
                .as_ref()
                .map(|step| Box::new(rewrite_expr(step, context))),
            body: {
                let body_context = context.shadowing(counter);
                rewrite_statements(body, &body_context)
            },
        },
        ExprKind::ForIn {
            index,
            value,
            iterable,
            body,
        } => ExprKind::ForIn {
            index: index.clone(),
            value: value.clone(),
            iterable: Box::new(rewrite_expr(iterable, context)),
            body: {
                let body_context = index.as_ref().map_or_else(
                    || context.shadowing(value),
                    |index| context.shadowing(index).shadowing(value),
                );
                rewrite_statements(body, &body_context)
            },
        },
        ExprKind::While { condition, body } => ExprKind::While {
            condition: Box::new(rewrite_expr(condition, context)),
            body: rewrite_statements(body, context),
        },
        ExprKind::Switch { selector, arms } => ExprKind::Switch {
            selector: selector
                .as_ref()
                .map(|selector| Box::new(rewrite_expr(selector, context))),
            arms: arms
                .iter()
                .map(|arm| SwitchArm {
                    condition: arm
                        .condition
                        .as_ref()
                        .map(|condition| rewrite_expr(condition, context)),
                    result: rewrite_switch_arm_result(&arm.result, context),
                })
                .collect(),
        },
        ExprKind::Tuple(items) => ExprKind::Tuple(
            items
                .iter()
                .map(|item| rewrite_expr(item, context))
                .collect(),
        ),
        ExprKind::History { expr, offset } => ExprKind::History {
            expr: Box::new(rewrite_expr(expr, context)),
            offset: Box::new(rewrite_expr(offset, context)),
        },
        ExprKind::QualifiedName(parts) => {
            rewrite_qualified_name(parts, context).unwrap_or_else(|| expr.kind.clone())
        }
        ExprKind::Literal(_) | ExprKind::Identifier(_) => expr.kind.clone(),
    };
    Expr {
        kind,
        span: expr.span,
    }
}

fn rewrite_switch_arm_result(
    result: &SwitchArmResult,
    context: &RewriteContext,
) -> SwitchArmResult {
    match result {
        SwitchArmResult::Expr(expr) => SwitchArmResult::Expr(rewrite_expr(expr, context)),
        SwitchArmResult::Block(statements) => {
            SwitchArmResult::Block(rewrite_statements(statements, context))
        }
    }
}

fn rewrite_declared_type(declared_type: &DeclaredType, context: &RewriteContext) -> DeclaredType {
    match declared_type {
        DeclaredType::Named(type_name) => DeclaredType::Named(
            context
                .type_target_in_type_position(type_name)
                .cloned()
                .unwrap_or_else(|| type_name.clone()),
        ),
        DeclaredType::Array { element_type } => DeclaredType::Array {
            element_type: context
                .type_target_in_type_position(element_type)
                .cloned()
                .unwrap_or_else(|| element_type.clone()),
        },
        DeclaredType::Matrix { .. } | DeclaredType::Map { .. } => declared_type.clone(),
    }
}

fn rewrite_array_new_type_target(name: &str, context: &RewriteContext) -> Option<String> {
    let type_name = name.strip_prefix("array.new<")?.strip_suffix('>')?;
    let target = context.type_target_in_type_position(type_name)?;
    Some(format!("array.new<{target}>"))
}

impl RewriteContext {
    fn shadowing(&self, name: &str) -> Self {
        let mut context = self.clone();
        context.shadowed_names.insert(name.to_owned());
        context
    }

    fn shadowing_all<'a>(&self, names: impl IntoIterator<Item = &'a String>) -> Self {
        let mut context = self.clone();
        context
            .shadowed_names
            .extend(names.into_iter().map(|name| name.to_owned()));
        context
    }

    fn constant(&self, name: &str) -> Option<&Expr> {
        if self.is_shadowed(name) {
            return None;
        }
        self.constants.get(name)
    }

    fn function_target(&self, name: &str) -> Option<&String> {
        if self.is_shadowed(name) {
            return None;
        }
        self.function_targets.get(name)
    }

    fn type_target(&self, name: &str) -> Option<&String> {
        if self.is_shadowed(name) {
            return None;
        }
        self.type_targets.get(name)
    }

    fn type_target_in_type_position(&self, name: &str) -> Option<&String> {
        self.type_targets.get(name)
    }

    fn is_shadowed(&self, name: &str) -> bool {
        self.shadowed_names.contains(name)
            || name
                .split_once('.')
                .is_some_and(|(prefix, _)| self.shadowed_names.contains(prefix))
    }
}

fn rewrite_qualified_name(parts: &[String], context: &RewriteContext) -> Option<ExprKind> {
    let (head, tail) = parts.split_first()?;
    let target = context.type_target(head)?;
    let mut rewritten = target.split('.').map(str::to_owned).collect::<Vec<_>>();
    rewritten.extend(tail.iter().cloned());
    Some(ExprKind::QualifiedName(rewritten))
}

fn record_statement_bindings(statement: &Stmt, context: &mut RewriteContext) {
    match &statement.kind {
        StmtKind::Decl { name, .. } | StmtKind::Function { name, .. } => {
            context.shadowed_names.insert(name.clone());
        }
        StmtKind::TupleDecl { names, .. } => {
            context.shadowed_names.extend(names.iter().cloned());
        }
        _ => {}
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use pine_syntax::Span;

    fn context() -> RewriteContext {
        RewriteContext {
            type_targets: HashMap::from([("Point".to_owned(), "lib.Point".to_owned())]),
            ..RewriteContext::default()
        }
    }

    #[test]
    fn alias_qualifies_user_type_array_new_templates() {
        let expr = Expr {
            kind: ExprKind::Call {
                callee: Box::new(Expr {
                    kind: ExprKind::Identifier("array.new<Point>".to_owned()),
                    span: Span::new(2, 18),
                }),
                args: Vec::new(),
            },
            span: Span::new(2, 20),
        };

        let rewritten = rewrite_expr(&expr, &context());

        let ExprKind::Call { callee, .. } = rewritten.kind else {
            panic!("call expected");
        };
        assert_eq!(expr_name(&callee).as_deref(), Some("array.new<lib.Point>"));
    }

    #[test]
    fn alias_qualifies_user_type_declarations() {
        assert_eq!(
            rewrite_declared_type(&DeclaredType::Named("Point".to_owned()), &context()),
            DeclaredType::Named("lib.Point".to_owned())
        );
        assert_eq!(
            rewrite_declared_type(
                &DeclaredType::Array {
                    element_type: "Point".to_owned(),
                },
                &context(),
            ),
            DeclaredType::Array {
                element_type: "lib.Point".to_owned(),
            }
        );
    }

    #[test]
    fn value_shadowing_does_not_hide_names_in_type_positions() {
        let context = context().shadowing("Point");

        assert_eq!(
            rewrite_array_new_type_target("array.new<Point>", &context),
            Some("array.new<lib.Point>".to_owned())
        );
        assert_eq!(
            rewrite_declared_type(
                &DeclaredType::Array {
                    element_type: "Point".to_owned(),
                },
                &context,
            ),
            DeclaredType::Array {
                element_type: "lib.Point".to_owned(),
            }
        );
    }

    #[test]
    fn postfix_call_result_method_callee_is_not_rewritten_as_an_exported_function() {
        let receiver = Expr {
            kind: ExprKind::Call {
                callee: Box::new(Expr {
                    kind: ExprKind::QualifiedName(vec!["lib".to_owned(), "direct".to_owned()]),
                    span: Span::new(2, 12),
                }),
                args: Vec::new(),
            },
            span: Span::new(2, 14),
        };
        let postfix = Expr {
            kind: ExprKind::Call {
                callee: Box::new(Expr {
                    kind: ExprKind::QualifiedName(vec!["lib".to_owned(), "copy".to_owned()]),
                    span: Span::new(15, 19),
                }),
                args: vec![CallArg {
                    name: None,
                    value: receiver.clone(),
                    span: receiver.span,
                }],
            },
            span: Span::new(2, 21),
        };
        let explicit = Expr {
            kind: ExprKind::Call {
                callee: Box::new(Expr {
                    kind: ExprKind::QualifiedName(vec!["lib".to_owned(), "copy".to_owned()]),
                    span: Span::new(2, 10),
                }),
                args: vec![CallArg {
                    name: None,
                    value: receiver,
                    span: Span::new(11, 23),
                }],
            },
            span: Span::new(2, 24),
        };
        let context = RewriteContext {
            function_targets: HashMap::from([("lib.copy".to_owned(), "lib.copy".to_owned())]),
            ..RewriteContext::default()
        };

        let ExprKind::Call {
            callee: postfix_callee,
            ..
        } = rewrite_expr(&postfix, &context).kind
        else {
            panic!("postfix call expected");
        };
        assert!(matches!(postfix_callee.kind, ExprKind::QualifiedName(_)));

        let ExprKind::Call {
            callee: explicit_callee,
            ..
        } = rewrite_expr(&explicit, &context).kind
        else {
            panic!("explicit call expected");
        };
        assert!(matches!(explicit_callee.kind, ExprKind::Identifier(_)));
    }
}
