use std::cmp::Ordering;

use pine_ir::HirCallArg;

use super::*;

impl<'a> HistoricalRuntime<'a> {
    pub(crate) fn eval_matrix_concat(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let target = self.eval_expr(&args[0].value)?;
        let source = self.eval_expr(&args[1].value)?;
        let (PineValue::Matrix(target_id), PineValue::Matrix(source_id)) = (target, source) else {
            return Ok(PineValue::Na);
        };
        Ok(self
            .matrix_concat(target_id, source_id)?
            .map(PineValue::Matrix)
            .unwrap_or(PineValue::Na))
    }

    pub(crate) fn eval_matrix_reshape(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_expr(&args[0].value)?;
        let rows = matrix_dimension_value("row", self.eval_expr(&args[1].value)?)?;
        let columns = matrix_dimension_value("column", self.eval_expr(&args[2].value)?)?;
        let PineValue::Matrix(id) = id else {
            return Ok(PineValue::Void);
        };
        self.matrix_reshape(id, rows, columns)?;
        Ok(PineValue::Void)
    }

    pub(crate) fn eval_matrix_add_row(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_expr(&args[0].value)?;
        let row = matrix_insert_index_value("row", self.eval_expr(&args[1].value)?)?;
        let array_id = self.eval_expr(&args[2].value)?;
        let PineValue::Matrix(id) = id else {
            return Ok(PineValue::Void);
        };
        let PineValue::Array(array_id) = array_id else {
            return Ok(PineValue::Void);
        };
        let Some(values) = self.array_values_clone(array_id)? else {
            return Ok(PineValue::Void);
        };
        self.matrix_add_row(id, row, values)?;
        Ok(PineValue::Void)
    }

    pub(crate) fn eval_matrix_add_col(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_expr(&args[0].value)?;
        let column = matrix_insert_index_value("column", self.eval_expr(&args[1].value)?)?;
        let array_id = self.eval_expr(&args[2].value)?;
        let PineValue::Matrix(id) = id else {
            return Ok(PineValue::Void);
        };
        let PineValue::Array(array_id) = array_id else {
            return Ok(PineValue::Void);
        };
        let Some(values) = self.array_values_clone(array_id)? else {
            return Ok(PineValue::Void);
        };
        self.matrix_add_col(id, column, values)?;
        Ok(PineValue::Void)
    }

    pub(crate) fn eval_matrix_remove_row(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_expr(&args[0].value)?;
        let row = matrix_index_value("row", self.eval_expr(&args[1].value)?)?;
        let PineValue::Matrix(id) = id else {
            return Ok(PineValue::Void);
        };
        self.matrix_remove_row(id, row)?;
        Ok(PineValue::Void)
    }

    pub(crate) fn eval_matrix_remove_col(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_expr(&args[0].value)?;
        let column = matrix_index_value("column", self.eval_expr(&args[1].value)?)?;
        let PineValue::Matrix(id) = id else {
            return Ok(PineValue::Void);
        };
        self.matrix_remove_col(id, column)?;
        Ok(PineValue::Void)
    }

    pub(crate) fn eval_matrix_swap_rows(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_expr(&args[0].value)?;
        let row1 = matrix_index_value("row", self.eval_expr(&args[1].value)?)?;
        let row2 = matrix_index_value("row", self.eval_expr(&args[2].value)?)?;
        let PineValue::Matrix(id) = id else {
            return Ok(PineValue::Void);
        };
        self.matrix_swap_rows(id, row1, row2)?;
        Ok(PineValue::Void)
    }

    pub(crate) fn eval_matrix_swap_columns(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_expr(&args[0].value)?;
        let column1 = matrix_index_value("column", self.eval_expr(&args[1].value)?)?;
        let column2 = matrix_index_value("column", self.eval_expr(&args[2].value)?)?;
        let PineValue::Matrix(id) = id else {
            return Ok(PineValue::Void);
        };
        self.matrix_swap_columns(id, column1, column2)?;
        Ok(PineValue::Void)
    }

    pub(crate) fn eval_matrix_sort(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_expr(&args[0].value)?;
        let column = match args.get(1) {
            Some(column) => matrix_index_value("column", self.eval_expr(&column.value)?)?,
            None => 0,
        };
        let descending = self.eval_matrix_sort_descending(args)?;
        let PineValue::Matrix(id) = id else {
            return Ok(PineValue::Void);
        };
        self.matrix_sort(id, column, descending)?;
        Ok(PineValue::Void)
    }

    pub(crate) fn eval_matrix_submatrix(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_expr(&args[0].value)?;
        let PineValue::Matrix(id) = id else {
            return Ok(PineValue::Na);
        };
        let Some((rows, columns)) = self.matrix_shape(id) else {
            return Ok(PineValue::Na);
        };
        let from_row = self.eval_optional_matrix_slice_index(args, 1, "row", 0)?;
        let to_row = self.eval_optional_matrix_slice_index(args, 2, "row", rows as i64)?;
        let from_column = self.eval_optional_matrix_slice_index(args, 3, "column", 0)?;
        let to_column = self.eval_optional_matrix_slice_index(args, 4, "column", columns as i64)?;
        self.matrix_submatrix(id, from_row, to_row, from_column, to_column)
    }

    pub(crate) fn matrix_reshape(
        &mut self,
        id: u32,
        rows: i64,
        columns: i64,
    ) -> Result<(), RuntimeError> {
        let rows = matrix_dimension("row", rows)?;
        let columns = matrix_dimension("column", columns)?;
        let cells = rows.checked_mul(columns).ok_or_else(|| RuntimeError {
            message: "matrix reshape dimensions must preserve element count".to_owned(),
        })?;
        let Some(matrix) = self.matrix_store.get_mut(&id) else {
            return Ok(());
        };
        if cells != matrix.values.len() {
            return Err(RuntimeError {
                message: "matrix reshape dimensions must preserve element count".to_owned(),
            });
        }
        matrix.rows = rows;
        matrix.columns = columns;
        Ok(())
    }

    pub(crate) fn matrix_concat(
        &mut self,
        target_id: u32,
        source_id: u32,
    ) -> Result<Option<u32>, RuntimeError> {
        let Some(source) = self.matrix_store.get(&source_id).cloned() else {
            return Ok(None);
        };
        let Some(target) = self.matrix_store.get_mut(&target_id) else {
            return Ok(None);
        };
        if target.kind != source.kind {
            return Ok(None);
        }
        if target.columns != source.columns {
            return Err(RuntimeError {
                message: format!(
                    "matrix.concat column count {} must match source column count {}",
                    target.columns, source.columns
                ),
            });
        }
        let new_rows = target
            .rows
            .checked_add(source.rows)
            .ok_or_else(|| RuntimeError {
                message: format!("matrix cell count cannot exceed {MAX_MATRIX_CELLS}"),
            })?;
        let new_cells = target
            .values
            .len()
            .checked_add(source.values.len())
            .ok_or_else(|| RuntimeError {
                message: format!("matrix cell count cannot exceed {MAX_MATRIX_CELLS}"),
            })?;
        if new_cells > MAX_MATRIX_CELLS {
            return Err(RuntimeError {
                message: format!("matrix cell count cannot exceed {MAX_MATRIX_CELLS}"),
            });
        }
        target.values.extend(source.values);
        target.rows = new_rows;
        Ok(Some(target_id))
    }

    pub(crate) fn matrix_add_row(
        &mut self,
        id: u32,
        row: i64,
        values: Vec<PineValue>,
    ) -> Result<(), RuntimeError> {
        let Some(matrix) = self.matrix_store.get_mut(&id) else {
            return Ok(());
        };
        let row = matrix_insert_index("row", row, matrix.rows)?;
        if values.len() != matrix.columns {
            return Err(RuntimeError {
                message: format!(
                    "matrix add_row array size {} must match column count {}",
                    values.len(),
                    matrix.columns
                ),
            });
        }
        let new_cells = (matrix.rows + 1)
            .checked_mul(matrix.columns)
            .ok_or_else(|| RuntimeError {
                message: format!("matrix cell count cannot exceed {MAX_MATRIX_CELLS}"),
            })?;
        if new_cells > MAX_MATRIX_CELLS {
            return Err(RuntimeError {
                message: format!("matrix cell count cannot exceed {MAX_MATRIX_CELLS}"),
            });
        }
        let offset = row * matrix.columns;
        let kind = matrix.kind;
        matrix.values.splice(
            offset..offset,
            values
                .into_iter()
                .map(|value| eval_matrix_value_for_kind(kind, value)),
        );
        matrix.rows += 1;
        Ok(())
    }

    pub(crate) fn matrix_add_col(
        &mut self,
        id: u32,
        column: i64,
        values: Vec<PineValue>,
    ) -> Result<(), RuntimeError> {
        let Some(matrix) = self.matrix_store.get_mut(&id) else {
            return Ok(());
        };
        let column = matrix_insert_index("column", column, matrix.columns)?;
        if values.len() != matrix.rows {
            return Err(RuntimeError {
                message: format!(
                    "matrix add_col array size {} must match row count {}",
                    values.len(),
                    matrix.rows
                ),
            });
        }
        let new_columns = matrix.columns + 1;
        let new_cells = matrix
            .rows
            .checked_mul(new_columns)
            .ok_or_else(|| RuntimeError {
                message: format!("matrix cell count cannot exceed {MAX_MATRIX_CELLS}"),
            })?;
        if new_cells > MAX_MATRIX_CELLS {
            return Err(RuntimeError {
                message: format!("matrix cell count cannot exceed {MAX_MATRIX_CELLS}"),
            });
        }

        let kind = matrix.kind;
        let mut inserted_values = values
            .into_iter()
            .map(|value| eval_matrix_value_for_kind(kind, value));
        let mut next_values = Vec::with_capacity(new_cells);
        for row in 0..matrix.rows {
            let start = row * matrix.columns;
            let insert_offset = start + column;
            next_values.extend_from_slice(&matrix.values[start..insert_offset]);
            next_values.push(inserted_values.next().unwrap_or(PineValue::Na));
            next_values.extend_from_slice(&matrix.values[insert_offset..start + matrix.columns]);
        }
        matrix.columns = new_columns;
        matrix.values = next_values;
        Ok(())
    }

    pub(crate) fn matrix_remove_row(&mut self, id: u32, row: i64) -> Result<(), RuntimeError> {
        let Some(matrix) = self.matrix_store.get_mut(&id) else {
            return Ok(());
        };
        let row = matrix_index("row", row, matrix.rows)?;
        let start = row * matrix.columns;
        let end = start + matrix.columns;
        matrix.values.drain(start..end);
        matrix.rows -= 1;
        Ok(())
    }

    pub(crate) fn matrix_remove_col(&mut self, id: u32, column: i64) -> Result<(), RuntimeError> {
        let Some(matrix) = self.matrix_store.get_mut(&id) else {
            return Ok(());
        };
        let column = matrix_index("column", column, matrix.columns)?;
        let new_columns = matrix.columns - 1;
        let mut next_values = Vec::with_capacity(matrix.rows * new_columns);
        for row in 0..matrix.rows {
            let start = row * matrix.columns;
            let remove_offset = start + column;
            next_values.extend_from_slice(&matrix.values[start..remove_offset]);
            next_values
                .extend_from_slice(&matrix.values[remove_offset + 1..start + matrix.columns]);
        }
        matrix.columns = new_columns;
        matrix.values = next_values;
        Ok(())
    }

    pub(crate) fn matrix_swap_rows(
        &mut self,
        id: u32,
        row1: i64,
        row2: i64,
    ) -> Result<(), RuntimeError> {
        let Some(matrix) = self.matrix_store.get_mut(&id) else {
            return Ok(());
        };
        let row1 = matrix_index("row", row1, matrix.rows)?;
        let row2 = matrix_index("row", row2, matrix.rows)?;
        if row1 == row2 || matrix.columns == 0 {
            return Ok(());
        }
        for column in 0..matrix.columns {
            matrix.values.swap(
                row1 * matrix.columns + column,
                row2 * matrix.columns + column,
            );
        }
        Ok(())
    }

    pub(crate) fn matrix_swap_columns(
        &mut self,
        id: u32,
        column1: i64,
        column2: i64,
    ) -> Result<(), RuntimeError> {
        let Some(matrix) = self.matrix_store.get_mut(&id) else {
            return Ok(());
        };
        let column1 = matrix_index("column", column1, matrix.columns)?;
        let column2 = matrix_index("column", column2, matrix.columns)?;
        if column1 == column2 || matrix.rows == 0 {
            return Ok(());
        }
        for row in 0..matrix.rows {
            matrix.values.swap(
                row * matrix.columns + column1,
                row * matrix.columns + column2,
            );
        }
        Ok(())
    }

    pub(crate) fn matrix_sort(
        &mut self,
        id: u32,
        column: i64,
        descending: bool,
    ) -> Result<(), RuntimeError> {
        let Some(matrix) = self.matrix_store.get_mut(&id) else {
            return Ok(());
        };
        let column = matrix_index("column", column, matrix.columns)?;
        if matrix.rows <= 1 || matrix.columns == 0 {
            return Ok(());
        }

        let mut row_indexes = (0..matrix.rows).collect::<Vec<_>>();
        row_indexes.sort_by(|left, right| {
            let left_value = &matrix.values[left * matrix.columns + column];
            let right_value = &matrix.values[right * matrix.columns + column];
            compare_matrix_sort_values(left_value, right_value, descending)
                .then_with(|| left.cmp(right))
        });

        let mut next_values = Vec::with_capacity(matrix.values.len());
        for row in row_indexes {
            let start = row * matrix.columns;
            next_values.extend_from_slice(&matrix.values[start..start + matrix.columns]);
        }
        matrix.values = next_values;
        Ok(())
    }

    pub(crate) fn matrix_submatrix(
        &mut self,
        id: u32,
        from_row: i64,
        to_row: i64,
        from_column: i64,
        to_column: i64,
    ) -> Result<PineValue, RuntimeError> {
        let Some(matrix) = self.matrix_store.get(&id).cloned() else {
            return Ok(PineValue::Na);
        };
        let from_row = matrix_slice_index("row", from_row, matrix.rows)?;
        let to_row = matrix_slice_index("row", to_row, matrix.rows)?;
        let from_column = matrix_slice_index("column", from_column, matrix.columns)?;
        let to_column = matrix_slice_index("column", to_column, matrix.columns)?;
        if from_row > to_row {
            return Err(RuntimeError {
                message: "matrix row range start cannot be greater than end".to_owned(),
            });
        }
        if from_column > to_column {
            return Err(RuntimeError {
                message: "matrix column range start cannot be greater than end".to_owned(),
            });
        }

        let rows = to_row - from_row;
        let columns = to_column - from_column;
        let mut values = Vec::with_capacity(rows * columns);
        for row in from_row..to_row {
            let start = row * matrix.columns + from_column;
            values.extend_from_slice(&matrix.values[start..start + columns]);
        }
        Ok(self.insert_matrix_storage(matrix.kind, rows, columns, values))
    }

    fn eval_matrix_sort_descending(&mut self, args: &[HirCallArg]) -> Result<bool, RuntimeError> {
        match args.get(2) {
            Some(order) => match self.eval_expr(&order.value)? {
                PineValue::String(order) if order == "order.descending" => Ok(true),
                PineValue::String(order) if order == "order.ascending" => Ok(false),
                PineValue::String(order) => Err(RuntimeError {
                    message: format!("unsupported matrix.sort order `{order}`"),
                }),
                _ => Ok(false),
            },
            None => Ok(false),
        }
    }

    fn eval_optional_matrix_slice_index(
        &mut self,
        args: &[HirCallArg],
        index: usize,
        name: &str,
        default: i64,
    ) -> Result<i64, RuntimeError> {
        match args.get(index) {
            Some(arg) => matrix_index_value(name, self.eval_expr(&arg.value)?),
            None => Ok(default),
        }
    }
}

fn compare_matrix_sort_values(left: &PineValue, right: &PineValue, descending: bool) -> Ordering {
    match (left.as_f64(), right.as_f64()) {
        (Some(left), Some(right)) => {
            let ordering = left.partial_cmp(&right).unwrap_or(Ordering::Equal);
            if descending {
                ordering.reverse()
            } else {
                ordering
            }
        }
        (Some(_), None) => {
            if descending {
                Ordering::Greater
            } else {
                Ordering::Less
            }
        }
        (None, Some(_)) => {
            if descending {
                Ordering::Less
            } else {
                Ordering::Greater
            }
        }
        (None, None) => Ordering::Equal,
    }
}

fn matrix_slice_index(name: &str, value: i64, len: usize) -> Result<usize, RuntimeError> {
    if value < 0 || value as usize > len {
        return Err(RuntimeError {
            message: format!(
                "matrix {name} index {value} is out of bounds for size {}",
                len + 1
            ),
        });
    }
    Ok(value as usize)
}
