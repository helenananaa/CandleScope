use std::collections::HashSet;

use super::*;

impl Analyzer {
    pub(super) fn collect_lower_reassigned_symbols(
        &self,
        statements: &[Stmt],
    ) -> HashSet<SymbolId> {
        let mut symbols = HashSet::new();
        self.collect_lower_reassigned_symbols_from_stmts(statements, &mut symbols);
        for function in self.functions.values() {
            self.with_source_context_ref(function.source_context_id, |analyzer| {
                analyzer.collect_lower_reassigned_symbols_from_body(&function.body, &mut symbols);
            });
        }
        for method in self.methods.values() {
            self.with_source_context_ref(method.source_context_id, |analyzer| {
                analyzer.collect_lower_reassigned_symbols_from_body(&method.body, &mut symbols);
            });
        }
        symbols
    }

    fn collect_lower_reassigned_symbols_from_body(
        &self,
        body: &FunctionBody,
        symbols: &mut HashSet<SymbolId>,
    ) {
        match body {
            FunctionBody::Expr(expr) => {
                self.collect_lower_reassigned_symbols_from_expr(expr, symbols);
            }
            FunctionBody::Block(statements) => {
                self.collect_lower_reassigned_symbols_from_stmts(statements, symbols);
            }
        }
    }

    fn collect_lower_reassigned_symbols_from_stmts(
        &self,
        statements: &[Stmt],
        symbols: &mut HashSet<SymbolId>,
    ) {
        for statement in statements {
            match &statement.kind {
                StmtKind::Expr(expr) => {
                    self.collect_lower_reassigned_symbols_from_expr(expr, symbols);
                }
                StmtKind::If {
                    condition,
                    then_branch,
                    else_branch,
                } => {
                    self.collect_lower_reassigned_symbols_from_expr(condition, symbols);
                    self.collect_lower_reassigned_symbols_from_stmts(then_branch, symbols);
                    self.collect_lower_reassigned_symbols_from_stmts(else_branch, symbols);
                }
                StmtKind::For {
                    from,
                    to,
                    step,
                    body,
                    ..
                } => {
                    self.collect_lower_reassigned_symbols_from_expr(from, symbols);
                    self.collect_lower_reassigned_symbols_from_expr(to, symbols);
                    if let Some(step) = step {
                        self.collect_lower_reassigned_symbols_from_expr(step, symbols);
                    }
                    self.collect_lower_reassigned_symbols_from_stmts(body, symbols);
                }
                StmtKind::ForIn { iterable, body, .. } => {
                    self.collect_lower_reassigned_symbols_from_expr(iterable, symbols);
                    self.collect_lower_reassigned_symbols_from_stmts(body, symbols);
                }
                StmtKind::While { condition, body } => {
                    self.collect_lower_reassigned_symbols_from_expr(condition, symbols);
                    self.collect_lower_reassigned_symbols_from_stmts(body, symbols);
                }
                StmtKind::Decl { value, .. } | StmtKind::TupleDecl { value, .. } => {
                    self.collect_lower_reassigned_symbols_from_expr(value, symbols);
                }
                StmtKind::Reassign { name, value } => {
                    if let Some(symbol) = self.bindings.get(&self.binding_key(name, statement.span))
                    {
                        symbols.insert(symbol.id);
                    }
                    self.collect_lower_reassigned_symbols_from_expr(value, symbols);
                }
                StmtKind::FieldReassign { value, .. } => {
                    self.collect_lower_reassigned_symbols_from_expr(value, symbols);
                }
                StmtKind::ArrayFieldReassign {
                    array,
                    index,
                    value,
                    ..
                } => {
                    self.collect_lower_reassigned_symbols_from_expr(array, symbols);
                    self.collect_lower_reassigned_symbols_from_expr(index, symbols);
                    self.collect_lower_reassigned_symbols_from_expr(value, symbols);
                }
                StmtKind::Function { .. }
                | StmtKind::Import(_)
                | StmtKind::Library(_)
                | StmtKind::Export(_)
                | StmtKind::UserType(_)
                | StmtKind::Method(_)
                | StmtKind::Break
                | StmtKind::Continue
                | StmtKind::Unsupported { .. } => {}
            }
        }
    }

    fn collect_lower_reassigned_symbols_from_expr(
        &self,
        expr: &Expr,
        symbols: &mut HashSet<SymbolId>,
    ) {
        match &expr.kind {
            ExprKind::Unary { expr, .. } | ExprKind::History { expr, .. } => {
                self.collect_lower_reassigned_symbols_from_expr(expr, symbols);
            }
            ExprKind::Binary { left, right, .. } => {
                self.collect_lower_reassigned_symbols_from_expr(left, symbols);
                self.collect_lower_reassigned_symbols_from_expr(right, symbols);
            }
            ExprKind::Ternary {
                condition,
                then_expr,
                else_expr,
            } => {
                self.collect_lower_reassigned_symbols_from_expr(condition, symbols);
                self.collect_lower_reassigned_symbols_from_expr(then_expr, symbols);
                self.collect_lower_reassigned_symbols_from_expr(else_expr, symbols);
            }
            ExprKind::If {
                condition,
                then_branch,
                else_branch,
            } => {
                self.collect_lower_reassigned_symbols_from_expr(condition, symbols);
                self.collect_lower_reassigned_symbols_from_stmts(then_branch, symbols);
                self.collect_lower_reassigned_symbols_from_stmts(else_branch, symbols);
            }
            ExprKind::Switch { selector, arms } => {
                if let Some(selector) = selector {
                    self.collect_lower_reassigned_symbols_from_expr(selector, symbols);
                }
                for arm in arms {
                    if let Some(condition) = &arm.condition {
                        self.collect_lower_reassigned_symbols_from_expr(condition, symbols);
                    }
                    match &arm.result {
                        SwitchArmResult::Expr(expr) => {
                            self.collect_lower_reassigned_symbols_from_expr(expr, symbols);
                        }
                        SwitchArmResult::Block(statements) => {
                            self.collect_lower_reassigned_symbols_from_stmts(statements, symbols);
                        }
                    }
                }
            }
            ExprKind::For {
                from,
                to,
                step,
                body,
                ..
            } => {
                self.collect_lower_reassigned_symbols_from_expr(from, symbols);
                self.collect_lower_reassigned_symbols_from_expr(to, symbols);
                if let Some(step) = step {
                    self.collect_lower_reassigned_symbols_from_expr(step, symbols);
                }
                self.collect_lower_reassigned_symbols_from_stmts(body, symbols);
            }
            ExprKind::ForIn { iterable, body, .. } => {
                self.collect_lower_reassigned_symbols_from_expr(iterable, symbols);
                self.collect_lower_reassigned_symbols_from_stmts(body, symbols);
            }
            ExprKind::While { condition, body } => {
                self.collect_lower_reassigned_symbols_from_expr(condition, symbols);
                self.collect_lower_reassigned_symbols_from_stmts(body, symbols);
            }
            ExprKind::Tuple(items) => {
                for item in items {
                    self.collect_lower_reassigned_symbols_from_expr(item, symbols);
                }
            }
            ExprKind::Call { callee, args } => {
                self.collect_lower_reassigned_symbols_from_expr(callee, symbols);
                for arg in args {
                    self.collect_lower_reassigned_symbols_from_expr(&arg.value, symbols);
                }
            }
            ExprKind::Literal(_) | ExprKind::Identifier(_) | ExprKind::QualifiedName(_) => {}
        }
    }
}
