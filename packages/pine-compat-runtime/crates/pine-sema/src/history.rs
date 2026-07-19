use std::collections::{BTreeMap, HashMap};

use pine_ir::{
    HirCallArg, HirExpr, HirExprKind, HirHistoryOffset, HirHistoryRequirements,
    HirSeriesHistoryRequirement, HirSeriesMaxBarsBack, HirStmt, HirStmtKind, HirSwitchStmtArm,
    HirSymbol, SeriesId,
};

#[path = "history_constants.rs"]
mod history_constants;

use history_constants::{
    ConstSymbolEnv, constant_hir_int_with_symbols, insert_const_symbol,
    remove_reassigned_symbols_from_env,
};

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct InferredHistoryRequirements {
    pub(crate) program: HirHistoryRequirements,
    pub(crate) series: Vec<HirSeriesHistoryRequirement>,
}
#[derive(Default)]
struct HistoryRequirementCollector<'a> {
    pub(crate) program: HirHistoryRequirements,
    pub(crate) series: BTreeMap<SeriesId, HirHistoryRequirements>,
    pub(crate) builtin_series: HashMap<String, SeriesId>,
    pub(crate) const_symbols: ConstSymbolEnv<'a>,
}
pub(crate) fn infer_history_requirements(
    statements: &[HirStmt],
    symbols: &[HirSymbol],
) -> InferredHistoryRequirements {
    let mut collector = HistoryRequirementCollector {
        builtin_series: symbols
            .iter()
            .filter_map(|symbol| {
                symbol
                    .series_id
                    .map(|series_id| (symbol.name.clone(), series_id))
            })
            .collect(),
        ..HistoryRequirementCollector::default()
    };
    for statement in statements {
        collector.visit_stmt(statement);
    }
    InferredHistoryRequirements {
        program: collector.program,
        series: collector
            .series
            .into_iter()
            .map(|(series_id, requirements)| HirSeriesHistoryRequirement {
                series_id,
                max_constant_offset: requirements.max_constant_offset,
                has_dynamic_offsets: requirements.has_dynamic_offsets,
            })
            .collect(),
    }
}
pub(crate) fn infer_max_bars_back(statements: &[HirStmt]) -> Option<u32> {
    infer_max_bars_back_with_symbols(statements, &ConstSymbolEnv::new())
}

fn infer_max_bars_back_with_symbols(
    statements: &[HirStmt],
    outer_const_symbols: &ConstSymbolEnv<'_>,
) -> Option<u32> {
    let mut const_symbols = outer_const_symbols.clone();
    infer_max_bars_back_with_mut_symbols(statements, &mut const_symbols)
}

fn infer_max_bars_back_with_mut_symbols<'a>(
    statements: &'a [HirStmt],
    const_symbols: &mut ConstSymbolEnv<'a>,
) -> Option<u32> {
    for statement in statements {
        update_series_max_bars_back_const_env(statement, const_symbols);
        if let Some(value) = max_bars_back_from_stmt_with_symbols(statement, const_symbols) {
            return Some(value);
        }
    }
    None
}

pub(crate) fn infer_series_max_bars_back(statements: &[HirStmt]) -> Vec<HirSeriesMaxBarsBack> {
    let mut values: BTreeMap<SeriesId, u32> = BTreeMap::new();
    collect_series_max_bars_back_from_stmts(statements, &mut values, &ConstSymbolEnv::new());
    values
        .into_iter()
        .map(|(series_id, max_bars_back)| HirSeriesMaxBarsBack {
            series_id,
            max_bars_back,
        })
        .collect()
}

fn collect_series_max_bars_back_from_stmts(
    statements: &[HirStmt],
    values: &mut BTreeMap<SeriesId, u32>,
    outer_const_symbols: &ConstSymbolEnv<'_>,
) {
    let mut const_symbols = outer_const_symbols.clone();
    collect_series_max_bars_back_from_stmts_with_env(statements, values, &mut const_symbols);
}

fn collect_series_max_bars_back_from_stmts_with_env<'a>(
    statements: &'a [HirStmt],
    values: &mut BTreeMap<SeriesId, u32>,
    const_symbols: &mut ConstSymbolEnv<'a>,
) {
    for statement in statements {
        collect_series_max_bars_back_from_stmt(statement, &mut *values, const_symbols);
        update_series_max_bars_back_const_env(statement, const_symbols);
    }
}

fn collect_series_max_bars_back_from_stmt(
    statement: &HirStmt,
    values: &mut BTreeMap<SeriesId, u32>,
    const_symbols: &ConstSymbolEnv<'_>,
) {
    match &statement.kind {
        HirStmtKind::Expr(expr) => {
            collect_series_max_bars_back_from_expr_stmt(expr, values, const_symbols);
        }
        HirStmtKind::Decl { value, .. }
        | HirStmtKind::Reassign { value, .. }
        | HirStmtKind::FieldReassign { value, .. }
        | HirStmtKind::TupleDecl { value, .. } => {
            collect_nested_series_max_bars_back_from_expr(value, values, const_symbols);
        }
        HirStmtKind::ArrayFieldReassign {
            array,
            index,
            value,
            ..
        } => {
            collect_nested_series_max_bars_back_from_expr(array, values, const_symbols);
            collect_nested_series_max_bars_back_from_expr(index, values, const_symbols);
            collect_nested_series_max_bars_back_from_expr(value, values, const_symbols);
        }
        HirStmtKind::If {
            condition,
            then_branch,
            else_branch,
        } => {
            collect_nested_series_max_bars_back_from_expr(condition, values, const_symbols);
            collect_series_max_bars_back_from_stmts(then_branch, values, const_symbols);
            collect_series_max_bars_back_from_stmts(else_branch, values, const_symbols);
        }
        HirStmtKind::Switch { selector, arms } => {
            collect_series_max_bars_back_from_switch_stmt(
                selector.as_ref(),
                arms,
                values,
                const_symbols,
            );
        }
        HirStmtKind::For {
            from,
            to,
            step,
            body,
            ..
        } => {
            collect_nested_series_max_bars_back_from_expr(from, values, const_symbols);
            collect_nested_series_max_bars_back_from_expr(to, values, const_symbols);
            if let Some(step) = step {
                collect_nested_series_max_bars_back_from_expr(step, values, const_symbols);
            }
            collect_series_max_bars_back_from_stmts(body, values, const_symbols);
        }
        HirStmtKind::ForIn { iterable, body, .. } => {
            collect_nested_series_max_bars_back_from_expr(iterable, values, const_symbols);
            collect_series_max_bars_back_from_stmts(body, values, const_symbols);
        }
        HirStmtKind::While { condition, body } => {
            collect_nested_series_max_bars_back_from_expr(condition, values, const_symbols);
            collect_series_max_bars_back_from_stmts(body, values, const_symbols);
        }
        HirStmtKind::Break | HirStmtKind::Continue => {}
    }
}

fn collect_series_max_bars_back_from_switch_stmt(
    selector: Option<&HirExpr>,
    arms: &[HirSwitchStmtArm],
    values: &mut BTreeMap<SeriesId, u32>,
    const_symbols: &ConstSymbolEnv<'_>,
) {
    if let Some(selector) = selector {
        collect_nested_series_max_bars_back_from_expr(selector, values, const_symbols);
    }
    for arm in arms {
        if let Some(condition) = &arm.condition {
            collect_nested_series_max_bars_back_from_expr(condition, values, const_symbols);
        }
        collect_series_max_bars_back_from_stmts(&arm.body, values, const_symbols);
    }
}

fn series_max_bars_back_from_expr_stmt(
    expr: &HirExpr,
    const_symbols: &ConstSymbolEnv<'_>,
) -> Option<(SeriesId, u32)> {
    let HirExprKind::Call { callee, args, .. } = &expr.kind else {
        return None;
    };
    if callee != "max_bars_back" {
        return None;
    }

    let source = call_arg(args, 0, "source")?;
    let num = call_arg(args, 1, "num")?;
    let series_id = source.series_id?;
    let max_bars_back = constant_hir_int_with_symbols(num, const_symbols)
        .and_then(|value| u32::try_from(value).ok())?;
    Some((series_id, max_bars_back))
}

fn collect_series_max_bars_back_from_expr_stmt(
    expr: &HirExpr,
    values: &mut BTreeMap<SeriesId, u32>,
    const_symbols: &ConstSymbolEnv<'_>,
) {
    collect_series_max_bars_back_from_expr_stmt_context(expr, values, const_symbols, true);
}

fn collect_nested_series_max_bars_back_from_expr(
    expr: &HirExpr,
    values: &mut BTreeMap<SeriesId, u32>,
    const_symbols: &ConstSymbolEnv<'_>,
) {
    collect_series_max_bars_back_from_expr_stmt_context(expr, values, const_symbols, false);
}

fn collect_series_max_bars_back_from_expr_stmt_context(
    expr: &HirExpr,
    values: &mut BTreeMap<SeriesId, u32>,
    const_symbols: &ConstSymbolEnv<'_>,
    allow_direct_call: bool,
) {
    if allow_direct_call
        && let Some((series_id, max_bars_back)) =
            series_max_bars_back_from_expr_stmt(expr, const_symbols)
    {
        values
            .entry(series_id)
            .and_modify(|current| *current = (*current).max(max_bars_back))
            .or_insert(max_bars_back);
        return;
    }

    match &expr.kind {
        HirExprKind::Call { args, .. } => {
            for arg in args {
                collect_series_max_bars_back_from_expr_stmt_context(
                    &arg.value,
                    values,
                    const_symbols,
                    false,
                );
            }
        }
        HirExprKind::Unary { expr, .. } => {
            collect_series_max_bars_back_from_expr_stmt_context(expr, values, const_symbols, false)
        }
        HirExprKind::Binary { left, right, .. } => {
            collect_series_max_bars_back_from_expr_stmt_context(left, values, const_symbols, false);
            collect_series_max_bars_back_from_expr_stmt_context(
                right,
                values,
                const_symbols,
                false,
            );
        }
        HirExprKind::Ternary {
            condition,
            then_expr,
            else_expr,
        } => {
            collect_series_max_bars_back_from_expr_stmt_context(
                condition,
                values,
                const_symbols,
                false,
            );
            collect_series_max_bars_back_from_expr_stmt_context(
                then_expr,
                values,
                const_symbols,
                false,
            );
            collect_series_max_bars_back_from_expr_stmt_context(
                else_expr,
                values,
                const_symbols,
                false,
            );
        }
        HirExprKind::Switch { selector, arms } => {
            if let Some(selector) = selector {
                collect_series_max_bars_back_from_expr_stmt_context(
                    selector,
                    values,
                    const_symbols,
                    false,
                );
            }
            for arm in arms {
                if let Some(condition) = &arm.condition {
                    collect_series_max_bars_back_from_expr_stmt_context(
                        condition,
                        values,
                        const_symbols,
                        false,
                    );
                }
                collect_series_max_bars_back_from_expr_stmt_context(
                    &arm.result,
                    values,
                    const_symbols,
                    false,
                );
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
            collect_series_max_bars_back_from_expr_stmt_context(from, values, const_symbols, false);
            collect_series_max_bars_back_from_expr_stmt_context(to, values, const_symbols, false);
            if let Some(step) = step {
                collect_series_max_bars_back_from_expr_stmt_context(
                    step,
                    values,
                    const_symbols,
                    false,
                );
            }
            let mut loop_const_symbols = const_symbols.clone();
            collect_series_max_bars_back_from_stmts_with_env(
                statements,
                values,
                &mut loop_const_symbols,
            );
            collect_series_max_bars_back_from_expr_stmt_context(
                result,
                values,
                &loop_const_symbols,
                false,
            );
        }
        HirExprKind::ForIn {
            iterable,
            statements,
            result,
            ..
        } => {
            collect_series_max_bars_back_from_expr_stmt_context(
                iterable,
                values,
                const_symbols,
                false,
            );
            let mut loop_const_symbols = const_symbols.clone();
            collect_series_max_bars_back_from_stmts_with_env(
                statements,
                values,
                &mut loop_const_symbols,
            );
            collect_series_max_bars_back_from_expr_stmt_context(
                result,
                values,
                &loop_const_symbols,
                false,
            );
        }
        HirExprKind::While {
            condition,
            statements,
            result,
        } => {
            collect_series_max_bars_back_from_expr_stmt_context(
                condition,
                values,
                const_symbols,
                false,
            );
            let mut loop_const_symbols = const_symbols.clone();
            collect_series_max_bars_back_from_stmts_with_env(
                statements,
                values,
                &mut loop_const_symbols,
            );
            collect_series_max_bars_back_from_expr_stmt_context(
                result,
                values,
                &loop_const_symbols,
                false,
            );
        }
        HirExprKind::Tuple(items)
        | HirExprKind::UserTypeConstruct { fields: items, .. }
        | HirExprKind::UserTypeArrayConstruct {
            elements: items, ..
        } => {
            for item in items {
                collect_series_max_bars_back_from_expr_stmt_context(
                    item,
                    values,
                    const_symbols,
                    false,
                );
            }
        }
        HirExprKind::FieldAccess { value, .. } => {
            collect_series_max_bars_back_from_expr_stmt_context(value, values, const_symbols, false)
        }
        HirExprKind::Block { statements, result } => {
            let mut block_const_symbols = const_symbols.clone();
            collect_series_max_bars_back_from_stmts_with_env(
                statements,
                values,
                &mut block_const_symbols,
            );
            collect_series_max_bars_back_from_expr_stmt_context(
                result,
                values,
                &block_const_symbols,
                false,
            );
        }
        HirExprKind::History { expr, offset } => {
            collect_series_max_bars_back_from_expr_stmt_context(expr, values, const_symbols, false);
            if let HirHistoryOffset::Dynamic(offset) = offset {
                collect_series_max_bars_back_from_expr_stmt_context(
                    offset,
                    values,
                    const_symbols,
                    false,
                );
            }
        }
        HirExprKind::Literal(_) | HirExprKind::Symbol(_) | HirExprKind::Builtin(_) => {}
    }
}

fn update_series_max_bars_back_const_env<'a>(
    statement: &'a HirStmt,
    const_symbols: &mut ConstSymbolEnv<'a>,
) {
    match &statement.kind {
        HirStmtKind::Decl { symbol, value } | HirStmtKind::Reassign { symbol, value } => {
            if hir_const_symbol_value(value) {
                insert_const_symbol(const_symbols, *symbol, value);
            } else {
                const_symbols.remove(symbol);
            }
        }
        HirStmtKind::TupleDecl { symbols, value } => {
            if let HirExprKind::Tuple(values) = &value.kind
                && symbols.len() == values.len()
            {
                for (symbol, value) in symbols.iter().zip(values) {
                    if hir_const_symbol_value(value) {
                        insert_const_symbol(const_symbols, *symbol, value);
                    } else {
                        const_symbols.remove(symbol);
                    }
                }
            } else {
                for symbol in symbols {
                    const_symbols.remove(symbol);
                }
            }
        }
        HirStmtKind::FieldReassign { symbol, .. } => {
            const_symbols.remove(symbol);
        }
        HirStmtKind::ArrayFieldReassign { array, .. } => {
            if let HirExprKind::Symbol(symbol) = array.kind {
                const_symbols.remove(&symbol);
            }
        }
        HirStmtKind::If { .. }
        | HirStmtKind::Switch { .. }
        | HirStmtKind::For { .. }
        | HirStmtKind::ForIn { .. }
        | HirStmtKind::While { .. } => {
            remove_reassigned_symbols_from_env(const_symbols, &statement.kind);
        }
        HirStmtKind::Expr(_) | HirStmtKind::Break | HirStmtKind::Continue => {}
    }
}

fn hir_const_symbol_value(expr: &HirExpr) -> bool {
    expr.pine_type.qualifier == pine_ir::Qualifier::Const
}

fn call_arg<'a>(args: &'a [HirCallArg], index: usize, name: &str) -> Option<&'a HirExpr> {
    args.iter()
        .find(|arg| arg.name.as_deref() == Some(name))
        .or_else(|| args.get(index).filter(|arg| arg.name.is_none()))
        .map(|arg| &arg.value)
}

fn max_bars_back_from_stmt_with_symbols(
    statement: &HirStmt,
    const_symbols: &ConstSymbolEnv<'_>,
) -> Option<u32> {
    match &statement.kind {
        HirStmtKind::Expr(expr)
        | HirStmtKind::Decl { value: expr, .. }
        | HirStmtKind::Reassign { value: expr, .. }
        | HirStmtKind::FieldReassign { value: expr, .. }
        | HirStmtKind::TupleDecl { value: expr, .. } => {
            max_bars_back_from_expr_with_symbols(expr, const_symbols)
        }
        HirStmtKind::ArrayFieldReassign {
            array,
            index,
            value,
            ..
        } => max_bars_back_from_expr_with_symbols(array, const_symbols)
            .or_else(|| max_bars_back_from_expr_with_symbols(index, const_symbols))
            .or_else(|| max_bars_back_from_expr_with_symbols(value, const_symbols)),
        HirStmtKind::If {
            condition,
            then_branch,
            else_branch,
        } => max_bars_back_from_expr_with_symbols(condition, const_symbols)
            .or_else(|| infer_max_bars_back_with_symbols(then_branch, const_symbols))
            .or_else(|| infer_max_bars_back_with_symbols(else_branch, const_symbols)),
        HirStmtKind::Switch { selector, arms } => {
            max_bars_back_from_switch_stmt_with_symbols(selector.as_ref(), arms, const_symbols)
        }
        HirStmtKind::For {
            from,
            to,
            step,
            body,
            ..
        } => max_bars_back_from_expr_with_symbols(from, const_symbols)
            .or_else(|| max_bars_back_from_expr_with_symbols(to, const_symbols))
            .or_else(|| {
                step.as_ref()
                    .and_then(|step| max_bars_back_from_expr_with_symbols(step, const_symbols))
            })
            .or_else(|| infer_max_bars_back_with_symbols(body, const_symbols)),
        HirStmtKind::ForIn { iterable, body, .. } => {
            max_bars_back_from_expr_with_symbols(iterable, const_symbols)
                .or_else(|| infer_max_bars_back_with_symbols(body, const_symbols))
        }
        HirStmtKind::While { condition, body } => {
            max_bars_back_from_expr_with_symbols(condition, const_symbols)
                .or_else(|| infer_max_bars_back_with_symbols(body, const_symbols))
        }
        HirStmtKind::Break | HirStmtKind::Continue => None,
    }
}

fn max_bars_back_from_switch_stmt_with_symbols(
    selector: Option<&HirExpr>,
    arms: &[HirSwitchStmtArm],
    const_symbols: &ConstSymbolEnv<'_>,
) -> Option<u32> {
    selector
        .and_then(|selector| max_bars_back_from_expr_with_symbols(selector, const_symbols))
        .or_else(|| {
            arms.iter().find_map(|arm| {
                arm.condition
                    .as_ref()
                    .and_then(|condition| {
                        max_bars_back_from_expr_with_symbols(condition, const_symbols)
                    })
                    .or_else(|| infer_max_bars_back_with_symbols(&arm.body, const_symbols))
            })
        })
}

fn max_bars_back_from_expr_with_symbols(
    expr: &HirExpr,
    const_symbols: &ConstSymbolEnv<'_>,
) -> Option<u32> {
    match &expr.kind {
        HirExprKind::Call { callee, args, .. } if callee == "indicator" || callee == "strategy" => {
            let index = if callee == "indicator" { 6 } else { 3 };
            args.iter()
                .enumerate()
                .find(|(arg_index, arg)| {
                    arg.name.as_deref() == Some("max_bars_back")
                        || (arg.name.is_none() && *arg_index == index)
                })
                .and_then(|(_, arg)| constant_hir_int_with_symbols(&arg.value, const_symbols))
                .and_then(|value| u32::try_from(value).ok())
        }
        HirExprKind::Call { args, .. } => args
            .iter()
            .find_map(|arg| max_bars_back_from_expr_with_symbols(&arg.value, const_symbols)),
        HirExprKind::Unary { expr, .. } => {
            max_bars_back_from_expr_with_symbols(expr, const_symbols)
        }
        HirExprKind::Binary { left, right, .. } => {
            max_bars_back_from_expr_with_symbols(left, const_symbols)
                .or_else(|| max_bars_back_from_expr_with_symbols(right, const_symbols))
        }
        HirExprKind::Ternary {
            condition,
            then_expr,
            else_expr,
        } => max_bars_back_from_expr_with_symbols(condition, const_symbols)
            .or_else(|| max_bars_back_from_expr_with_symbols(then_expr, const_symbols))
            .or_else(|| max_bars_back_from_expr_with_symbols(else_expr, const_symbols)),
        HirExprKind::Switch { selector, arms } => selector
            .as_deref()
            .and_then(|selector| max_bars_back_from_expr_with_symbols(selector, const_symbols))
            .or_else(|| {
                arms.iter().find_map(|arm| {
                    arm.condition
                        .as_ref()
                        .and_then(|condition| {
                            max_bars_back_from_expr_with_symbols(condition, const_symbols)
                        })
                        .or_else(|| {
                            max_bars_back_from_expr_with_symbols(&arm.result, const_symbols)
                        })
                })
            }),
        HirExprKind::For {
            from,
            to,
            step,
            statements,
            result,
            ..
        } => max_bars_back_from_expr_with_symbols(from, const_symbols)
            .or_else(|| max_bars_back_from_expr_with_symbols(to, const_symbols))
            .or_else(|| {
                step.as_deref()
                    .and_then(|step| max_bars_back_from_expr_with_symbols(step, const_symbols))
            })
            .or_else(|| {
                let mut loop_const_symbols = const_symbols.clone();
                infer_max_bars_back_with_mut_symbols(statements, &mut loop_const_symbols)
                    .or_else(|| max_bars_back_from_expr_with_symbols(result, &loop_const_symbols))
            }),
        HirExprKind::ForIn {
            iterable,
            statements,
            result,
            ..
        } => max_bars_back_from_expr_with_symbols(iterable, const_symbols).or_else(|| {
            let mut loop_const_symbols = const_symbols.clone();
            infer_max_bars_back_with_mut_symbols(statements, &mut loop_const_symbols)
                .or_else(|| max_bars_back_from_expr_with_symbols(result, &loop_const_symbols))
        }),
        HirExprKind::While {
            condition,
            statements,
            result,
        } => max_bars_back_from_expr_with_symbols(condition, const_symbols).or_else(|| {
            let mut loop_const_symbols = const_symbols.clone();
            infer_max_bars_back_with_mut_symbols(statements, &mut loop_const_symbols)
                .or_else(|| max_bars_back_from_expr_with_symbols(result, &loop_const_symbols))
        }),
        HirExprKind::Tuple(items)
        | HirExprKind::UserTypeConstruct { fields: items, .. }
        | HirExprKind::UserTypeArrayConstruct {
            elements: items, ..
        } => items
            .iter()
            .find_map(|item| max_bars_back_from_expr_with_symbols(item, const_symbols)),
        HirExprKind::FieldAccess { value, .. } => {
            max_bars_back_from_expr_with_symbols(value, const_symbols)
        }
        HirExprKind::Block { statements, result } => {
            let mut block_const_symbols = const_symbols.clone();
            infer_max_bars_back_with_mut_symbols(statements, &mut block_const_symbols)
                .or_else(|| max_bars_back_from_expr_with_symbols(result, &block_const_symbols))
        }
        HirExprKind::History { expr, offset } => {
            max_bars_back_from_expr_with_symbols(expr, const_symbols).or_else(|| {
                if let HirHistoryOffset::Dynamic(offset) = offset {
                    max_bars_back_from_expr_with_symbols(offset, const_symbols)
                } else {
                    None
                }
            })
        }
        HirExprKind::Literal(_) | HirExprKind::Symbol(_) | HirExprKind::Builtin(_) => None,
    }
}
impl<'a> HistoryRequirementCollector<'a> {
    fn visit_stmt(&mut self, statement: &'a HirStmt) {
        match &statement.kind {
            HirStmtKind::Expr(expr) => self.visit_expr(expr),
            HirStmtKind::Decl { value, .. }
            | HirStmtKind::Reassign { value, .. }
            | HirStmtKind::TupleDecl { value, .. } => {
                self.visit_expr(value);
                update_series_max_bars_back_const_env(statement, &mut self.const_symbols);
            }
            HirStmtKind::FieldReassign { symbol, value, .. } => {
                self.visit_expr(value);
                self.const_symbols.remove(symbol);
            }
            HirStmtKind::ArrayFieldReassign {
                array,
                index,
                value,
                ..
            } => {
                self.visit_expr(array);
                self.visit_expr(index);
                self.visit_expr(value);
                if let HirExprKind::Symbol(symbol) = array.kind {
                    self.const_symbols.remove(&symbol);
                }
            }
            HirStmtKind::If {
                condition,
                then_branch,
                else_branch,
            } => {
                self.visit_expr(condition);
                self.visit_scoped_stmts(then_branch);
                self.visit_scoped_stmts(else_branch);
                remove_reassigned_symbols_from_env(&mut self.const_symbols, &statement.kind);
            }
            HirStmtKind::Switch { selector, arms } => {
                if let Some(selector) = selector {
                    self.visit_expr(selector);
                }
                for arm in arms {
                    if let Some(condition) = &arm.condition {
                        self.visit_expr(condition);
                    }
                    self.visit_scoped_stmts(&arm.body);
                }
                remove_reassigned_symbols_from_env(&mut self.const_symbols, &statement.kind);
            }
            HirStmtKind::For {
                from,
                to,
                step,
                body,
                ..
            } => {
                self.visit_expr(from);
                self.visit_expr(to);
                if let Some(step) = step {
                    self.visit_expr(step);
                }
                self.visit_scoped_stmts(body);
                remove_reassigned_symbols_from_env(&mut self.const_symbols, &statement.kind);
            }
            HirStmtKind::ForIn { iterable, body, .. } => {
                self.visit_expr(iterable);
                self.visit_scoped_stmts(body);
                remove_reassigned_symbols_from_env(&mut self.const_symbols, &statement.kind);
            }
            HirStmtKind::While { condition, body } => {
                self.visit_expr(condition);
                self.visit_scoped_stmts(body);
                remove_reassigned_symbols_from_env(&mut self.const_symbols, &statement.kind);
            }
            HirStmtKind::Break | HirStmtKind::Continue => {}
        }
    }

    fn visit_stmts(&mut self, statements: &'a [HirStmt]) {
        for statement in statements {
            self.visit_stmt(statement);
        }
    }

    fn visit_scoped_stmts(&mut self, statements: &'a [HirStmt]) {
        let outer = self.const_symbols.clone();
        self.visit_stmts(statements);
        self.const_symbols = outer;
    }

    fn visit_expr(&mut self, expr: &'a HirExpr) {
        match &expr.kind {
            HirExprKind::Literal(_) | HirExprKind::Symbol(_) => {}
            HirExprKind::Builtin(name) => {
                if let Some(requirement) = pine_builtins::builtin_history_requirement(name) {
                    self.record_builtin_history_requirement(requirement, &[]);
                }
            }
            HirExprKind::Unary { expr, .. } => self.visit_expr(expr),
            HirExprKind::Binary { left, right, .. } => {
                self.visit_expr(left);
                self.visit_expr(right);
            }
            HirExprKind::Ternary {
                condition,
                then_expr,
                else_expr,
            } => {
                self.visit_expr(condition);
                self.visit_expr(then_expr);
                self.visit_expr(else_expr);
            }
            HirExprKind::Switch { selector, arms } => {
                if let Some(selector) = selector {
                    self.visit_expr(selector);
                }
                for arm in arms {
                    if let Some(condition) = &arm.condition {
                        self.visit_expr(condition);
                    }
                    self.visit_expr(&arm.result);
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
                self.visit_expr(from);
                self.visit_expr(to);
                if let Some(step) = step {
                    self.visit_expr(step);
                }
                let outer = self.const_symbols.clone();
                self.visit_stmts(statements);
                self.visit_expr(result);
                self.const_symbols = outer;
            }
            HirExprKind::ForIn {
                iterable,
                statements,
                result,
                ..
            } => {
                self.visit_expr(iterable);
                let outer = self.const_symbols.clone();
                self.visit_stmts(statements);
                self.visit_expr(result);
                self.const_symbols = outer;
            }
            HirExprKind::While {
                condition,
                statements,
                result,
            } => {
                self.visit_expr(condition);
                let outer = self.const_symbols.clone();
                self.visit_stmts(statements);
                self.visit_expr(result);
                self.const_symbols = outer;
            }
            HirExprKind::Tuple(items) => {
                for item in items {
                    self.visit_expr(item);
                }
            }
            HirExprKind::UserTypeConstruct { fields, .. } => {
                for field in fields {
                    self.visit_expr(field);
                }
            }
            HirExprKind::UserTypeArrayConstruct { elements, .. } => {
                for element in elements {
                    self.visit_expr(element);
                }
            }
            HirExprKind::FieldAccess { value, .. } => self.visit_expr(value),
            HirExprKind::Block { statements, result } => {
                let outer = self.const_symbols.clone();
                self.visit_stmts(statements);
                self.visit_expr(result);
                self.const_symbols = outer;
            }
            HirExprKind::Call { callee, args, .. } => {
                for arg in args {
                    self.visit_expr(&arg.value);
                }
                self.record_call_history(callee, args);
            }
            HirExprKind::History { expr, offset } => {
                self.record_history(expr.series_id, offset);
                self.visit_expr(expr);
                if let HirHistoryOffset::Dynamic(offset) = offset {
                    self.visit_expr(offset);
                }
            }
        }
    }

    fn record_history(&mut self, series_id: Option<SeriesId>, offset: &HirHistoryOffset) {
        match offset {
            HirHistoryOffset::Constant(offset) => {
                self.record_constant_history(series_id, *offset);
            }
            HirHistoryOffset::Dynamic(offset) => {
                match constant_hir_int_with_symbols(offset, &self.const_symbols) {
                    Some(offset) if offset >= 0 => {
                        self.record_constant_history(series_id, offset as u32)
                    }
                    _ => self.record_dynamic_history(series_id),
                }
            }
        }
    }

    fn record_call_history(&mut self, callee: &str, args: &[HirCallArg]) {
        if let Some(requirement) = pine_builtins::builtin_history_requirement(callee) {
            self.record_builtin_history_requirement(requirement, args);
        }
    }

    fn record_builtin_history_requirement(
        &mut self,
        requirement: pine_builtins::BuiltinHistoryRequirement,
        args: &[HirCallArg],
    ) {
        match requirement {
            pine_builtins::BuiltinHistoryRequirement::BuiltinSeries(requirements) => {
                for requirement in requirements {
                    self.record_builtin_history(requirement.symbol, requirement.offset);
                }
            }
            pine_builtins::BuiltinHistoryRequirement::SourceOffset { source_arg, offset } => self
                .record_constant_history(
                    call_arg(args, source_arg, "source").and_then(|arg| arg.series_id),
                    offset,
                ),
            pine_builtins::BuiltinHistoryRequirement::OptionalLengthOffset {
                source_arg,
                length_arg,
                default_offset,
            } => self.record_optional_length_history(args, source_arg, length_arg, default_offset),
            pine_builtins::BuiltinHistoryRequirement::RequiredLengthOffset {
                source_arg,
                length_arg,
            } => self.record_required_length_history(args, source_arg, length_arg),
            pine_builtins::BuiltinHistoryRequirement::WindowLengthOffset {
                source_arg,
                length_arg,
                default_source,
            } => self.record_window_length_history(args, source_arg, length_arg, default_source),
            pine_builtins::BuiltinHistoryRequirement::Cross {
                args: count,
                offset,
            } => {
                self.record_cross_history(args, count, offset);
            }
        }
    }

    fn record_optional_length_history(
        &mut self,
        args: &[HirCallArg],
        source_arg: usize,
        length_arg: usize,
        default_offset: u32,
    ) {
        let series_id = call_arg(args, source_arg, "source").and_then(|arg| arg.series_id);
        match call_arg(args, length_arg, "length")
            .and_then(|arg| constant_hir_int_with_symbols(arg, &self.const_symbols))
        {
            Some(length) if length > 0 => self.record_constant_history(series_id, length as u32),
            Some(_) => {}
            None if call_arg(args, length_arg, "length").is_some() => {
                self.record_dynamic_history(series_id)
            }
            None => self.record_constant_history(series_id, default_offset),
        }
    }

    fn record_required_length_history(
        &mut self,
        args: &[HirCallArg],
        source_arg: usize,
        length_arg: usize,
    ) {
        let series_id = call_arg(args, source_arg, "source").and_then(|arg| arg.series_id);
        match call_arg(args, length_arg, "length")
            .and_then(|arg| constant_hir_int_with_symbols(arg, &self.const_symbols))
        {
            Some(length) if length > 0 => self.record_constant_history(series_id, length as u32),
            Some(_) => {}
            None => self.record_dynamic_history(series_id),
        }
    }

    fn record_window_length_history(
        &mut self,
        args: &[HirCallArg],
        source_arg: usize,
        length_arg: usize,
        default_source: Option<&str>,
    ) {
        let has_explicit_source = args.iter().any(|arg| arg.name.as_deref() == Some("source"))
            || args
                .get(source_arg)
                .is_some_and(|arg| arg.name.is_none() && args.len() > length_arg);
        let (series_id, length) = if has_explicit_source {
            (
                call_arg(args, source_arg, "source").and_then(|arg| arg.series_id),
                call_arg(args, length_arg, "length"),
            )
        } else {
            (
                default_source.and_then(|name| self.builtin_series.get(name).copied()),
                call_arg(args, source_arg, "length"),
            )
        };

        match length.and_then(|arg| constant_hir_int_with_symbols(arg, &self.const_symbols)) {
            Some(length) if length > 0 => {
                self.record_constant_history(series_id, (length as u32).saturating_sub(1))
            }
            Some(_) => {}
            None => self.record_dynamic_history(series_id),
        }
    }

    fn record_cross_history(&mut self, args: &[HirCallArg], count: usize, offset: u32) {
        for arg in args.iter().take(count) {
            self.record_constant_history(arg.value.series_id, offset);
        }
    }

    fn record_builtin_history(&mut self, name: &str, offset: u32) {
        let series_id = self.builtin_series.get(name).copied();
        self.record_constant_history(series_id, offset);
    }

    fn record_constant_history(&mut self, series_id: Option<SeriesId>, offset: u32) {
        self.program.max_constant_offset = self.program.max_constant_offset.max(offset);
        if let Some(series_id) = series_id {
            let requirement = self.series.entry(series_id).or_default();
            requirement.max_constant_offset = requirement.max_constant_offset.max(offset);
        }
    }

    fn record_dynamic_history(&mut self, series_id: Option<SeriesId>) {
        self.program.has_dynamic_offsets = true;
        if let Some(series_id) = series_id {
            self.series
                .entry(series_id)
                .or_default()
                .has_dynamic_offsets = true;
        }
    }
}
