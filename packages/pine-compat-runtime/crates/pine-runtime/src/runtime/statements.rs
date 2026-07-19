use pine_ir::{HirBinaryOp, HirExpr, HirStmt, HirStmtKind, HirSwitchStmtArm, SymbolId};

use crate::builtins::matrices::matrix_array_element_kind;
use crate::error::RuntimeLoopControl;
use crate::*;

use super::expressions::eval_binary;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum StmtControl {
    None,
    Break,
    Continue,
}

#[derive(Debug, Clone, Copy)]
struct ForInSymbols {
    index: Option<SymbolId>,
    value: SymbolId,
}

struct ForInItem {
    index: PineValue,
    value: PineValue,
}

impl StmtControl {
    fn from_runtime_error(error: &RuntimeError) -> Option<Self> {
        match error.loop_control()? {
            RuntimeLoopControl::Break => Some(Self::Break),
            RuntimeLoopControl::Continue => Some(Self::Continue),
        }
    }
}

impl<'a> HistoricalRuntime<'a> {
    pub(crate) fn eval_stmt(&mut self, statement: &HirStmt) -> Result<StmtControl, RuntimeError> {
        match &statement.kind {
            HirStmtKind::Expr(expr) => {
                self.eval_expr(expr)?;
            }
            HirStmtKind::If {
                condition,
                then_branch,
                else_branch,
            } => {
                let branch = match self.eval_expr(condition)? {
                    PineValue::Bool(true) => then_branch,
                    PineValue::Bool(false) | PineValue::Na => else_branch,
                    _ => return Ok(StmtControl::None),
                };
                for statement in branch {
                    match self.eval_stmt(statement)? {
                        StmtControl::None => {}
                        control => return Ok(control),
                    }
                }
            }
            HirStmtKind::Switch { selector, arms } => {
                return self.eval_switch_stmt(selector.as_ref(), arms);
            }
            HirStmtKind::For {
                counter,
                from,
                to,
                step,
                body,
            } => {
                self.eval_for_loop(*counter, from, to, step.as_ref(), body, None)?;
            }
            HirStmtKind::ForIn {
                index,
                value,
                iterable,
                body,
            } => {
                self.eval_for_in_loop(*index, *value, iterable, body)?;
            }
            HirStmtKind::While { condition, body } => {
                self.eval_while_loop(condition, body, None)?;
            }
            HirStmtKind::Break => return Ok(StmtControl::Break),
            HirStmtKind::Continue => return Ok(StmtControl::Continue),
            HirStmtKind::Decl { symbol, value } => {
                let value = self.eval_decl(*symbol, value)?;
                self.set_symbol_value(*symbol, value);
            }
            HirStmtKind::Reassign { symbol, value } => {
                let value = self.eval_expr(value)?;
                self.assign_persistent_symbol(*symbol, value.clone());
                self.set_symbol_value(*symbol, value);
            }
            HirStmtKind::FieldReassign {
                symbol,
                field_index,
                value,
            } => {
                let value = self.eval_expr(value)?;
                let updated = match self.current_symbols.get(symbol).cloned() {
                    Some(PineValue::UserType(mut fields)) => {
                        if *field_index < fields.len() {
                            fields[*field_index] = value;
                        }
                        PineValue::UserType(fields)
                    }
                    Some(PineValue::ChartPoint(mut point)) => {
                        point.set_field(
                            *field_index,
                            crate::builtins::chart_points::normalize_chart_point_field(
                                *field_index,
                                value,
                            ),
                        );
                        PineValue::ChartPoint(point)
                    }
                    Some(PineValue::Na) | None => return Ok(StmtControl::None),
                    Some(_) => {
                        return Err(RuntimeError {
                            message: "field mutation receiver is not an object value".to_owned(),
                        });
                    }
                };
                self.assign_persistent_symbol(*symbol, updated.clone());
                self.set_symbol_value(*symbol, updated);
            }
            HirStmtKind::ArrayFieldReassign {
                array,
                index,
                field_index,
                value,
            } => {
                self.eval_array_field_reassign(array, index, *field_index, value)?;
            }
            HirStmtKind::TupleDecl { symbols, value } => {
                let value = self.eval_expr(value)?;
                let PineValue::Tuple(values) = value else {
                    return Ok(StmtControl::None);
                };
                for (symbol, value) in symbols.iter().zip(values) {
                    self.set_symbol_value(*symbol, value);
                }
            }
        }

        Ok(StmtControl::None)
    }

    fn eval_switch_stmt(
        &mut self,
        selector: Option<&HirExpr>,
        arms: &[HirSwitchStmtArm],
    ) -> Result<StmtControl, RuntimeError> {
        let selector_value = match selector {
            Some(selector) => Some(self.eval_expr(selector)?),
            None => None,
        };

        for arm in arms {
            let matches = match (&selector_value, &arm.condition) {
                (Some(selector_value), Some(case_expr)) => {
                    let case_value = self.eval_expr(case_expr)?;
                    matches!(
                        eval_binary(HirBinaryOp::Eq, selector_value.clone(), case_value)?,
                        PineValue::Bool(true)
                    )
                }
                (None, Some(condition)) => {
                    matches!(self.eval_expr(condition)?, PineValue::Bool(true))
                }
                (_, None) => true,
            };

            if matches {
                for statement in &arm.body {
                    match self.eval_stmt(statement)? {
                        StmtControl::None => {}
                        control => return Ok(control),
                    }
                }
                break;
            }
        }

        Ok(StmtControl::None)
    }

    fn eval_array_field_reassign(
        &mut self,
        array: &HirExpr,
        index: &HirExpr,
        field_index: usize,
        value: &HirExpr,
    ) -> Result<(), RuntimeError> {
        let array = self.eval_expr(array)?;
        let index = self.eval_expr(index)?.as_i64();
        let value = self.eval_expr(value)?;
        let (PineValue::Array(array_id), Some(index)) = (array, index) else {
            return Ok(());
        };
        if !matches!(
            self.array_kinds.get(&array_id),
            Some(crate::builtins::arrays::ArrayElementKind::UserType)
        ) {
            return Err(RuntimeError {
                message: "chained field mutation receiver is not a UDT array".to_owned(),
            });
        }
        let Some(slot) = self.array_get_cloned(array_id, index)? else {
            return Ok(());
        };
        let updated = match slot {
            PineValue::UserType(mut fields) => {
                if field_index < fields.len() {
                    fields[field_index] = value;
                }
                PineValue::UserType(fields)
            }
            PineValue::Na => return Ok(()),
            _ => {
                return Err(RuntimeError {
                    message: "chained field mutation receiver is not a UDT value".to_owned(),
                });
            }
        };
        self.array_set_value(array_id, index, updated)
    }

    pub(crate) fn eval_for_loop(
        &mut self,
        counter: SymbolId,
        from: &HirExpr,
        to: &HirExpr,
        step: Option<&HirExpr>,
        body: &[HirStmt],
        result: Option<&HirExpr>,
    ) -> Result<PineValue, RuntimeError> {
        let Some(from) = self.eval_expr(from)?.as_i64() else {
            return Ok(PineValue::Na);
        };
        let Some(mut to_boundary) = self.eval_expr(to)?.as_i64() else {
            return Ok(PineValue::Na);
        };
        let step_size = if let Some(step) = step {
            let Some(step) = self.eval_expr(step)?.as_i64() else {
                return Ok(PineValue::Na);
            };
            if step == 0 {
                return Err(RuntimeError {
                    message: "for loop step cannot be zero".to_owned(),
                });
            }
            step.checked_abs().ok_or_else(|| RuntimeError {
                message: "for loop step is out of range".to_owned(),
            })?
        } else {
            1
        };
        let dynamic_boundary = self.uses_v6_semantics();
        let step = if from <= to_boundary {
            step_size
        } else {
            -step_size
        };
        let mut value = from;
        let mut loop_result = PineValue::Na;
        loop {
            if (step > 0 && value > to_boundary) || (step < 0 && value < to_boundary) {
                break;
            }
            self.set_symbol_value(counter, PineValue::Int(value));
            let mut control = StmtControl::None;
            for statement in body {
                match self.eval_stmt(statement) {
                    Ok(StmtControl::None) => {}
                    Ok(next_control) => {
                        control = next_control;
                        break;
                    }
                    Err(error) => match StmtControl::from_runtime_error(&error) {
                        Some(next_control) => {
                            control = next_control;
                            break;
                        }
                        None => return Err(error),
                    },
                }
            }
            match control {
                StmtControl::None => {
                    if let Some(result) = result {
                        match self.eval_expr(result) {
                            Ok(value) => loop_result = value,
                            Err(error) => match StmtControl::from_runtime_error(&error) {
                                Some(StmtControl::Break) => break,
                                Some(StmtControl::Continue) => {}
                                Some(StmtControl::None) => {}
                                None => return Err(error),
                            },
                        }
                    }
                }
                StmtControl::Break => break,
                StmtControl::Continue => {}
            }
            let Some(next) = value.checked_add(step) else {
                break;
            };
            value = next;
            if dynamic_boundary {
                let Some(next_boundary) = self.eval_expr(to)?.as_i64() else {
                    return Ok(PineValue::Na);
                };
                to_boundary = next_boundary;
            }
        }
        Ok(loop_result)
    }

    pub(crate) fn eval_while_loop(
        &mut self,
        condition: &HirExpr,
        body: &[HirStmt],
        result: Option<&HirExpr>,
    ) -> Result<PineValue, RuntimeError> {
        let mut iterations = 0_usize;
        let mut loop_result = PineValue::Na;
        loop {
            match self.eval_expr(condition)? {
                PineValue::Bool(true) => {}
                PineValue::Bool(false) | PineValue::Na => break,
                _ => break,
            }

            if iterations >= MAX_WHILE_ITERATIONS {
                return Err(RuntimeError {
                    message: format!(
                        "while loop exceeded maximum iteration count of {MAX_WHILE_ITERATIONS}"
                    ),
                });
            }
            iterations += 1;

            let mut control = StmtControl::None;
            for statement in body {
                match self.eval_stmt(statement) {
                    Ok(StmtControl::None) => {}
                    Ok(next_control) => {
                        control = next_control;
                        break;
                    }
                    Err(error) => match StmtControl::from_runtime_error(&error) {
                        Some(next_control) => {
                            control = next_control;
                            break;
                        }
                        None => return Err(error),
                    },
                }
            }
            match control {
                StmtControl::None => {
                    if let Some(result) = result {
                        match self.eval_expr(result) {
                            Ok(value) => loop_result = value,
                            Err(error) => match StmtControl::from_runtime_error(&error) {
                                Some(StmtControl::Break) => break,
                                Some(StmtControl::Continue) => {}
                                Some(StmtControl::None) => {}
                                None => return Err(error),
                            },
                        }
                    }
                }
                StmtControl::Break => return Ok(loop_result),
                StmtControl::Continue => {}
            }
        }

        Ok(loop_result)
    }

    pub(crate) fn eval_for_in_loop(
        &mut self,
        index_symbol: Option<SymbolId>,
        value_symbol: SymbolId,
        iterable: &HirExpr,
        body: &[HirStmt],
    ) -> Result<(), RuntimeError> {
        let iterable = self.eval_expr(iterable)?;
        match iterable {
            PineValue::Array(array_id) => {
                let Some(initial_len) = self.array_len(array_id)? else {
                    return Ok(());
                };

                for index in 0..initial_len {
                    let value = self.array_get_cloned(array_id, index as i64)?;
                    let Some(value) = value else {
                        return Err(RuntimeError {
                            message: "for...in array is not available".to_owned(),
                        });
                    };
                    if self.eval_for_in_iteration(
                        index_symbol,
                        value_symbol,
                        PineValue::Int(index as i64),
                        value,
                        body,
                    )? {
                        return Ok(());
                    }
                }
            }
            PineValue::Matrix(matrix_id) => {
                let Some((initial_rows, kind)) = self
                    .matrix_store
                    .get(&matrix_id)
                    .map(|matrix| (matrix.rows, matrix.kind))
                else {
                    return Ok(());
                };
                let array_kind = matrix_array_element_kind(kind);

                let mut row_snapshots = Vec::with_capacity(initial_rows);
                for index in 0..initial_rows {
                    let Some(values) = self.matrix_row_values(matrix_id, index as i64)? else {
                        return Err(RuntimeError {
                            message: "for...in matrix is not available".to_owned(),
                        });
                    };
                    row_snapshots.push(self.new_array_from_values(array_kind, values));
                }

                for (index, value) in row_snapshots.into_iter().enumerate() {
                    if self.eval_for_in_iteration(
                        index_symbol,
                        value_symbol,
                        PineValue::Int(index as i64),
                        value,
                        body,
                    )? {
                        return Ok(());
                    }
                }
            }
            PineValue::Map(map_id) => {
                let Some(entries) = self
                    .map_store
                    .get(&map_id)
                    .map(|storage| storage.entries.clone())
                else {
                    return Ok(());
                };
                let initial_len = entries.len();
                for (key, value) in entries {
                    let (index_value, loop_value) = if index_symbol.is_some() {
                        (key, value)
                    } else {
                        (PineValue::Na, key)
                    };
                    if self.eval_for_in_iteration(
                        index_symbol,
                        value_symbol,
                        index_value,
                        loop_value,
                        body,
                    )? {
                        return Ok(());
                    }
                    self.ensure_map_for_in_size(map_id, initial_len)?;
                }
            }
            PineValue::Na => {}
            _ => {
                return Err(RuntimeError {
                    message: "for...in iterable is not an array, matrix, or map".to_owned(),
                });
            }
        }
        Ok(())
    }

    pub(crate) fn eval_for_in_expr(
        &mut self,
        index_symbol: Option<SymbolId>,
        value_symbol: SymbolId,
        iterable: &HirExpr,
        body: &[HirStmt],
        result: &HirExpr,
    ) -> Result<PineValue, RuntimeError> {
        let iterable = self.eval_expr(iterable)?;
        let mut loop_result = PineValue::Na;
        let symbols = ForInSymbols {
            index: index_symbol,
            value: value_symbol,
        };

        match iterable {
            PineValue::Array(array_id) => {
                let Some(initial_len) = self.array_len(array_id)? else {
                    return Ok(PineValue::Na);
                };

                for index in 0..initial_len {
                    let value = self.array_get_cloned(array_id, index as i64)?;
                    let Some(value) = value else {
                        return Err(RuntimeError {
                            message: "for...in array is not available".to_owned(),
                        });
                    };
                    if self.eval_for_in_expr_iteration(
                        symbols,
                        ForInItem {
                            index: PineValue::Int(index as i64),
                            value,
                        },
                        body,
                        result,
                        &mut loop_result,
                    )? {
                        break;
                    }
                }
            }
            PineValue::Matrix(matrix_id) => {
                let Some((initial_rows, kind)) = self
                    .matrix_store
                    .get(&matrix_id)
                    .map(|matrix| (matrix.rows, matrix.kind))
                else {
                    return Ok(PineValue::Na);
                };
                let array_kind = matrix_array_element_kind(kind);

                let mut row_snapshots = Vec::with_capacity(initial_rows);
                for index in 0..initial_rows {
                    let Some(values) = self.matrix_row_values(matrix_id, index as i64)? else {
                        return Err(RuntimeError {
                            message: "for...in matrix is not available".to_owned(),
                        });
                    };
                    row_snapshots.push(self.new_array_from_values(array_kind, values));
                }

                for (index, value) in row_snapshots.into_iter().enumerate() {
                    if self.eval_for_in_expr_iteration(
                        symbols,
                        ForInItem {
                            index: PineValue::Int(index as i64),
                            value,
                        },
                        body,
                        result,
                        &mut loop_result,
                    )? {
                        break;
                    }
                }
            }
            PineValue::Map(map_id) => {
                let Some(entries) = self
                    .map_store
                    .get(&map_id)
                    .map(|storage| storage.entries.clone())
                else {
                    return Ok(PineValue::Na);
                };
                let initial_len = entries.len();
                for (key, value) in entries {
                    let item = if symbols.index.is_some() {
                        ForInItem { index: key, value }
                    } else {
                        ForInItem {
                            index: PineValue::Na,
                            value: key,
                        }
                    };
                    if self.eval_for_in_expr_iteration(
                        symbols,
                        item,
                        body,
                        result,
                        &mut loop_result,
                    )? {
                        break;
                    }
                    self.ensure_map_for_in_size(map_id, initial_len)?;
                }
            }
            PineValue::Na => {}
            _ => {
                return Err(RuntimeError {
                    message: "for...in expression iterable is not an array, matrix, or map"
                        .to_owned(),
                });
            }
        }

        Ok(loop_result)
    }

    fn eval_for_in_expr_iteration(
        &mut self,
        symbols: ForInSymbols,
        item: ForInItem,
        body: &[HirStmt],
        result: &HirExpr,
        loop_result: &mut PineValue,
    ) -> Result<bool, RuntimeError> {
        if let Some(index_symbol) = symbols.index {
            self.set_symbol_value(index_symbol, item.index);
        }
        self.set_symbol_value(symbols.value, item.value);

        let mut control = StmtControl::None;
        for statement in body {
            match self.eval_stmt(statement) {
                Ok(StmtControl::None) => {}
                Ok(next_control) => {
                    control = next_control;
                    break;
                }
                Err(error) => match StmtControl::from_runtime_error(&error) {
                    Some(next_control) => {
                        control = next_control;
                        break;
                    }
                    None => return Err(error),
                },
            }
        }
        match control {
            StmtControl::None => match self.eval_expr(result) {
                Ok(value) => *loop_result = value,
                Err(error) => match StmtControl::from_runtime_error(&error) {
                    Some(StmtControl::Break) => return Ok(true),
                    Some(StmtControl::Continue) => {}
                    Some(StmtControl::None) => {}
                    None => return Err(error),
                },
            },
            StmtControl::Break => return Ok(true),
            StmtControl::Continue => {}
        }
        Ok(false)
    }

    fn eval_for_in_iteration(
        &mut self,
        index_symbol: Option<SymbolId>,
        value_symbol: SymbolId,
        index: PineValue,
        value: PineValue,
        body: &[HirStmt],
    ) -> Result<bool, RuntimeError> {
        if let Some(index_symbol) = index_symbol {
            self.set_symbol_value(index_symbol, index);
        }
        self.set_symbol_value(value_symbol, value);
        for statement in body {
            match self.eval_stmt(statement) {
                Ok(StmtControl::None) => {}
                Ok(StmtControl::Break) => return Ok(true),
                Ok(StmtControl::Continue) => break,
                Err(error) => match StmtControl::from_runtime_error(&error) {
                    Some(StmtControl::Break) => return Ok(true),
                    Some(StmtControl::Continue) => break,
                    Some(StmtControl::None) => {}
                    None => return Err(error),
                },
            }
        }
        Ok(false)
    }

    fn ensure_map_for_in_size(&self, map_id: u32, initial_len: usize) -> Result<(), RuntimeError> {
        let Some(current_len) = self
            .map_store
            .get(&map_id)
            .map(|storage| storage.entries.len())
        else {
            return Ok(());
        };
        if current_len != initial_len {
            return Err(RuntimeError {
                message: "map size cannot change during direct for...in iteration".to_owned(),
            });
        }
        Ok(())
    }
}
