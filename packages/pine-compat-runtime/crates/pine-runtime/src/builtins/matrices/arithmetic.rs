use pine_ir::HirCallArg;

use super::*;

impl<'a> HistoricalRuntime<'a> {
    pub(crate) fn eval_matrix_kron(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let left = self.eval_expr(&args[0].value)?;
        let right = self.eval_expr(&args[1].value)?;
        let (PineValue::Matrix(left_id), PineValue::Matrix(right_id)) = (left, right) else {
            return Ok(PineValue::Na);
        };
        self.matrix_kron(left_id, right_id)
    }

    pub(crate) fn eval_matrix_mult(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let left = self.eval_expr(&args[0].value)?;
        let right = self.eval_expr(&args[1].value)?;
        match (left, right) {
            (PineValue::Matrix(left_id), PineValue::Matrix(right_id)) => {
                self.matrix_mult(left_id, right_id)
            }
            (PineValue::Matrix(left_id), PineValue::Array(right_id)) => {
                self.matrix_mult_array(left_id, right_id)
            }
            (PineValue::Array(left_id), PineValue::Matrix(right_id)) => {
                self.array_mult_matrix(left_id, right_id)
            }
            (PineValue::Array(left_id), PineValue::Array(right_id)) => {
                self.array_mult_array(left_id, right_id)
            }
            (PineValue::Matrix(left_id), scalar) => self.matrix_mult_scalar(left_id, scalar),
            (scalar, PineValue::Matrix(right_id)) => self.matrix_mult_scalar(right_id, scalar),
            _ => Ok(PineValue::Na),
        }
    }

    pub(crate) fn eval_matrix_diff(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let left = self.eval_expr(&args[0].value)?;
        let right = self.eval_expr(&args[1].value)?;
        match (left, right) {
            (PineValue::Matrix(left_id), PineValue::Matrix(right_id)) => {
                self.matrix_diff(left_id, right_id)
            }
            (PineValue::Matrix(left_id), scalar) => self.matrix_diff_scalar(left_id, scalar),
            (scalar, PineValue::Matrix(right_id)) => {
                self.matrix_map_scalar(right_id, scalar, |cell, scalar| scalar - cell)
            }
            _ => Ok(PineValue::Na),
        }
    }

    pub(crate) fn eval_matrix_pow(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_expr(&args[0].value)?;
        let power = matrix_power_value(self.eval_expr(&args[1].value)?)?;
        let PineValue::Matrix(id) = id else {
            return Ok(PineValue::Na);
        };
        self.matrix_pow(id, power)
    }

    pub(crate) fn matrix_kron(
        &mut self,
        left_id: u32,
        right_id: u32,
    ) -> Result<PineValue, RuntimeError> {
        let (Some(left), Some(right)) = (
            self.matrix_store.get(&left_id).cloned(),
            self.matrix_store.get(&right_id).cloned(),
        ) else {
            return Ok(PineValue::Na);
        };
        let rows = left
            .rows
            .checked_mul(right.rows)
            .ok_or_else(|| RuntimeError {
                message: format!("matrix cell count cannot exceed {MAX_MATRIX_CELLS}"),
            })?;
        let columns = left
            .columns
            .checked_mul(right.columns)
            .ok_or_else(|| RuntimeError {
                message: format!("matrix cell count cannot exceed {MAX_MATRIX_CELLS}"),
            })?;
        let cells = rows.checked_mul(columns).ok_or_else(|| RuntimeError {
            message: format!("matrix cell count cannot exceed {MAX_MATRIX_CELLS}"),
        })?;
        if cells > MAX_MATRIX_CELLS {
            return Err(RuntimeError {
                message: format!("matrix cell count cannot exceed {MAX_MATRIX_CELLS}"),
            });
        }

        let mut values = Vec::with_capacity(cells);
        for left_row in 0..left.rows {
            for right_row in 0..right.rows {
                for left_column in 0..left.columns {
                    let left_value = &left.values[left_row * left.columns + left_column];
                    for right_column in 0..right.columns {
                        let right_value = &right.values[right_row * right.columns + right_column];
                        values.push(match (left_value.as_f64(), right_value.as_f64()) {
                            (Some(left), Some(right)) if left.is_finite() && right.is_finite() => {
                                finite_float_or_na(left * right)
                            }
                            _ => PineValue::Na,
                        });
                    }
                }
            }
        }

        Ok(self.insert_matrix_storage(MatrixElementKind::Float, rows, columns, values))
    }

    pub(crate) fn matrix_mult(
        &mut self,
        left_id: u32,
        right_id: u32,
    ) -> Result<PineValue, RuntimeError> {
        let (Some(left), Some(right)) = (
            self.matrix_store.get(&left_id).cloned(),
            self.matrix_store.get(&right_id).cloned(),
        ) else {
            return Ok(PineValue::Na);
        };
        let result = matrix_multiply_storage(&left, &right)?;
        Ok(self.insert_matrix_storage(
            MatrixElementKind::Float,
            result.rows,
            result.columns,
            result.values,
        ))
    }

    pub(crate) fn matrix_mult_scalar(
        &mut self,
        id: u32,
        scalar: PineValue,
    ) -> Result<PineValue, RuntimeError> {
        self.matrix_map_scalar(id, scalar, |left, right| left * right)
    }

    pub(crate) fn matrix_mult_array(
        &mut self,
        left_id: u32,
        right_id: u32,
    ) -> Result<PineValue, RuntimeError> {
        let Some(left) = self.matrix_store.get(&left_id).cloned() else {
            return Ok(PineValue::Na);
        };
        let Some(right) = self.array_values_clone(right_id)? else {
            return Ok(PineValue::Na);
        };
        if left.columns != right.len() {
            return Err(RuntimeError {
                message: "matrix multiplication requires matrix column count to match array size"
                    .to_owned(),
            });
        }

        let mut values = Vec::with_capacity(left.rows);
        for row in 0..left.rows {
            let mut sum = 0.0;
            let mut valid = true;
            for (column, right_value) in right.iter().enumerate() {
                let left_value = &left.values[row * left.columns + column];
                let (Some(left_number), Some(right_number)) =
                    (left_value.as_f64(), right_value.as_f64())
                else {
                    valid = false;
                    break;
                };
                if !left_number.is_finite() || !right_number.is_finite() {
                    valid = false;
                    break;
                }
                sum += left_number * right_number;
            }
            values.push(if valid {
                finite_float_or_na(sum)
            } else {
                PineValue::Na
            });
        }

        Ok(self.new_array_from_values(ArrayElementKind::Float, values))
    }

    pub(crate) fn array_mult_matrix(
        &mut self,
        left_id: u32,
        right_id: u32,
    ) -> Result<PineValue, RuntimeError> {
        let Some(left) = self.array_values_clone(left_id)? else {
            return Ok(PineValue::Na);
        };
        let Some(right) = self.matrix_store.get(&right_id).cloned() else {
            return Ok(PineValue::Na);
        };
        if left.len() != right.rows {
            return Err(RuntimeError {
                message: "matrix multiplication requires array size to match matrix row count"
                    .to_owned(),
            });
        }

        let mut values = Vec::with_capacity(right.columns);
        for column in 0..right.columns {
            let mut sum = 0.0;
            let mut valid = true;
            for (row, left_value) in left.iter().enumerate() {
                let right_value = &right.values[row * right.columns + column];
                let (Some(left_number), Some(right_number)) =
                    (left_value.as_f64(), right_value.as_f64())
                else {
                    valid = false;
                    break;
                };
                if !left_number.is_finite() || !right_number.is_finite() {
                    valid = false;
                    break;
                }
                sum += left_number * right_number;
            }
            values.push(if valid {
                finite_float_or_na(sum)
            } else {
                PineValue::Na
            });
        }

        Ok(self.new_array_from_values(ArrayElementKind::Float, values))
    }

    pub(crate) fn array_mult_array(
        &mut self,
        left_id: u32,
        right_id: u32,
    ) -> Result<PineValue, RuntimeError> {
        let Some(left) = self.array_values_clone(left_id)? else {
            return Ok(PineValue::Na);
        };
        let Some(right) = self.array_values_clone(right_id)? else {
            return Ok(PineValue::Na);
        };
        if left.len() != right.len() {
            return Err(RuntimeError {
                message: "matrix multiplication requires left array size to match right array size"
                    .to_owned(),
            });
        }

        let mut sum = 0.0;
        let mut valid = true;
        for (left_value, right_value) in left.iter().zip(right.iter()) {
            let (Some(left_number), Some(right_number)) =
                (left_value.as_f64(), right_value.as_f64())
            else {
                valid = false;
                break;
            };
            if !left_number.is_finite() || !right_number.is_finite() {
                valid = false;
                break;
            }
            sum += left_number * right_number;
        }

        let value = if valid {
            finite_float_or_na(sum)
        } else {
            PineValue::Na
        };
        Ok(self.new_array_from_values(ArrayElementKind::Float, vec![value]))
    }

    pub(crate) fn matrix_diff(
        &mut self,
        left_id: u32,
        right_id: u32,
    ) -> Result<PineValue, RuntimeError> {
        let (Some(left), Some(right)) = (
            self.matrix_store.get(&left_id).cloned(),
            self.matrix_store.get(&right_id).cloned(),
        ) else {
            return Ok(PineValue::Na);
        };
        if left.rows != right.rows || left.columns != right.columns {
            return Err(RuntimeError {
                message: "matrix difference requires matching row and column counts".to_owned(),
            });
        }

        let values = left
            .values
            .iter()
            .zip(&right.values)
            .map(|(left_value, right_value)| {
                let (Some(left_number), Some(right_number)) =
                    (left_value.as_f64(), right_value.as_f64())
                else {
                    return PineValue::Na;
                };
                if left_number.is_finite() && right_number.is_finite() {
                    finite_float_or_na(left_number - right_number)
                } else {
                    PineValue::Na
                }
            })
            .collect();

        Ok(self.insert_matrix_storage(MatrixElementKind::Float, left.rows, left.columns, values))
    }

    pub(crate) fn matrix_diff_scalar(
        &mut self,
        id: u32,
        scalar: PineValue,
    ) -> Result<PineValue, RuntimeError> {
        self.matrix_map_scalar(id, scalar, |left, right| left - right)
    }

    fn matrix_map_scalar(
        &mut self,
        id: u32,
        scalar: PineValue,
        operation: impl Fn(f64, f64) -> f64,
    ) -> Result<PineValue, RuntimeError> {
        let Some(source) = self.matrix_store.get(&id).cloned() else {
            return Ok(PineValue::Na);
        };
        let scalar = scalar.as_f64().filter(|value| value.is_finite());
        let values = source
            .values
            .iter()
            .map(|value| {
                let (Some(left), Some(right)) = (value.as_f64(), scalar) else {
                    return PineValue::Na;
                };
                if left.is_finite() {
                    finite_float_or_na(operation(left, right))
                } else {
                    PineValue::Na
                }
            })
            .collect();

        Ok(self.insert_matrix_storage(
            MatrixElementKind::Float,
            source.rows,
            source.columns,
            values,
        ))
    }

    pub(crate) fn matrix_pow(&mut self, id: u32, power: usize) -> Result<PineValue, RuntimeError> {
        let Some(source) = self.matrix_store.get(&id).cloned() else {
            return Ok(PineValue::Na);
        };
        if source.rows != source.columns {
            return Err(RuntimeError {
                message: "matrix power requires a square matrix".to_owned(),
            });
        }
        if power == 0 {
            return Ok(self.insert_matrix_storage(
                MatrixElementKind::Float,
                source.rows,
                source.columns,
                identity_matrix_values(source.rows),
            ));
        }
        if power == 1 {
            return Ok(self.insert_matrix_storage(
                MatrixElementKind::Float,
                source.rows,
                source.columns,
                source.values,
            ));
        }

        let mut result = MatrixStorage {
            kind: MatrixElementKind::Float,
            rows: source.rows,
            columns: source.columns,
            values: identity_matrix_values(source.rows),
        };
        let mut base = source;
        let mut exponent = power;
        while exponent > 0 {
            if exponent % 2 == 1 {
                result = matrix_multiply_storage(&result, &base)?;
            }
            exponent /= 2;
            if exponent > 0 {
                base = matrix_multiply_storage(&base, &base)?;
            }
        }

        Ok(self.insert_matrix_storage(
            MatrixElementKind::Float,
            result.rows,
            result.columns,
            result.values,
        ))
    }
}

fn matrix_power_value(value: PineValue) -> Result<usize, RuntimeError> {
    let power = value.as_i64().ok_or_else(|| RuntimeError {
        message: "matrix power cannot be na".to_owned(),
    })?;
    if power < 0 {
        return Err(RuntimeError {
            message: "matrix power cannot be negative".to_owned(),
        });
    }
    Ok(power as usize)
}

fn identity_matrix_values(size: usize) -> Vec<PineValue> {
    let mut values = Vec::with_capacity(size * size);
    for row in 0..size {
        for column in 0..size {
            values.push(PineValue::Float(if row == column { 1.0 } else { 0.0 }));
        }
    }
    values
}

fn matrix_multiply_storage(
    left: &MatrixStorage,
    right: &MatrixStorage,
) -> Result<MatrixStorage, RuntimeError> {
    if left.columns != right.rows {
        return Err(RuntimeError {
            message: "matrix multiplication requires left column count to match right row count"
                .to_owned(),
        });
    }
    let cells = left
        .rows
        .checked_mul(right.columns)
        .ok_or_else(|| RuntimeError {
            message: format!("matrix cell count cannot exceed {MAX_MATRIX_CELLS}"),
        })?;
    if cells > MAX_MATRIX_CELLS {
        return Err(RuntimeError {
            message: format!("matrix cell count cannot exceed {MAX_MATRIX_CELLS}"),
        });
    }

    let mut values = Vec::with_capacity(cells);
    for row in 0..left.rows {
        for column in 0..right.columns {
            let mut total = 0.0;
            let mut has_na = false;
            for index in 0..left.columns {
                let left_value = &left.values[row * left.columns + index];
                let right_value = &right.values[index * right.columns + column];
                let (Some(left_number), Some(right_number)) =
                    (left_value.as_f64(), right_value.as_f64())
                else {
                    has_na = true;
                    break;
                };
                if !left_number.is_finite() || !right_number.is_finite() {
                    has_na = true;
                    break;
                }
                total += left_number * right_number;
            }
            values.push(if has_na {
                PineValue::Na
            } else {
                finite_float_or_na(total)
            });
        }
    }

    Ok(MatrixStorage {
        kind: MatrixElementKind::Float,
        rows: left.rows,
        columns: right.columns,
        values,
    })
}
