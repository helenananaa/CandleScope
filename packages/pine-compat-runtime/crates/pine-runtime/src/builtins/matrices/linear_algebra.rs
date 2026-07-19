use pine_ir::HirCallArg;

use super::linalg::{eigenvalues, eigenvectors, pseudo_inverse};
use super::*;

impl<'a> HistoricalRuntime<'a> {
    pub(crate) fn eval_matrix_det(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let PineValue::Matrix(id) = self.eval_expr(&args[0].value)? else {
            return Ok(PineValue::Na);
        };
        Ok(self.matrix_det(id)?.unwrap_or(PineValue::Na))
    }

    pub(crate) fn eval_matrix_inv(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let PineValue::Matrix(id) = self.eval_expr(&args[0].value)? else {
            return Ok(PineValue::Na);
        };
        self.matrix_inv(id)
    }

    pub(crate) fn eval_matrix_eigenvalues(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let PineValue::Matrix(id) = self.eval_expr(&args[0].value)? else {
            return Ok(PineValue::Na);
        };
        self.matrix_eigenvalues(id)
    }

    pub(crate) fn eval_matrix_eigenvectors(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let PineValue::Matrix(id) = self.eval_expr(&args[0].value)? else {
            return Ok(PineValue::Na);
        };
        self.matrix_eigenvectors(id)
    }

    pub(crate) fn eval_matrix_pinv(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let PineValue::Matrix(id) = self.eval_expr(&args[0].value)? else {
            return Ok(PineValue::Na);
        };
        Ok(self.matrix_pinv(id))
    }

    pub(crate) fn eval_matrix_rank(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let PineValue::Matrix(id) = self.eval_expr(&args[0].value)? else {
            return Ok(PineValue::Na);
        };
        Ok(self.matrix_rank(id).unwrap_or(PineValue::Na))
    }

    pub(crate) fn matrix_det(&self, id: u32) -> Result<Option<PineValue>, RuntimeError> {
        let Some(matrix) = self.matrix_store.get(&id) else {
            return Ok(None);
        };
        if matrix.rows != matrix.columns {
            return Err(RuntimeError {
                message: "matrix determinant requires a square matrix".to_owned(),
            });
        }
        let size = matrix.rows;
        if size == 0 {
            return Ok(Some(PineValue::Float(1.0)));
        }

        let mut values = Vec::with_capacity(matrix.values.len());
        for value in &matrix.values {
            let Some(number) = value.as_f64() else {
                return Ok(Some(PineValue::Na));
            };
            if !number.is_finite() {
                return Ok(Some(PineValue::Na));
            }
            values.push(number);
        }

        let mut determinant = 1.0;
        for pivot in 0..size {
            let mut pivot_row = pivot;
            let mut pivot_abs = values[pivot * size + pivot].abs();
            for row in (pivot + 1)..size {
                let candidate_abs = values[row * size + pivot].abs();
                if candidate_abs > pivot_abs {
                    pivot_abs = candidate_abs;
                    pivot_row = row;
                }
            }

            if pivot_abs == 0.0 {
                return Ok(Some(PineValue::Float(0.0)));
            }
            if pivot_row != pivot {
                for column in 0..size {
                    values.swap(pivot * size + column, pivot_row * size + column);
                }
                determinant = -determinant;
            }

            let pivot_value = values[pivot * size + pivot];
            determinant *= pivot_value;
            for row in (pivot + 1)..size {
                let factor = values[row * size + pivot] / pivot_value;
                values[row * size + pivot] = 0.0;
                for column in (pivot + 1)..size {
                    values[row * size + column] -= factor * values[pivot * size + column];
                }
            }
        }

        Ok(Some(finite_float_or_na(determinant)))
    }

    pub(crate) fn matrix_inv(&mut self, id: u32) -> Result<PineValue, RuntimeError> {
        let Some(matrix) = self.matrix_store.get(&id).cloned() else {
            return Ok(PineValue::Na);
        };
        if matrix.rows != matrix.columns {
            return Err(RuntimeError {
                message: "matrix inverse requires a square matrix".to_owned(),
            });
        }

        let size = matrix.rows;
        let mut left = Vec::with_capacity(matrix.values.len());
        for value in &matrix.values {
            let Some(number) = value.as_f64() else {
                return Ok(PineValue::Na);
            };
            if !number.is_finite() {
                return Ok(PineValue::Na);
            }
            left.push(number);
        }

        let mut right = vec![0.0; size * size];
        for index in 0..size {
            right[index * size + index] = 1.0;
        }

        for pivot in 0..size {
            let mut pivot_row = pivot;
            let mut pivot_abs = left[pivot * size + pivot].abs();
            for row in (pivot + 1)..size {
                let candidate_abs = left[row * size + pivot].abs();
                if candidate_abs > pivot_abs {
                    pivot_abs = candidate_abs;
                    pivot_row = row;
                }
            }

            if pivot_abs == 0.0 {
                return Ok(PineValue::Na);
            }
            if pivot_row != pivot {
                for column in 0..size {
                    left.swap(pivot * size + column, pivot_row * size + column);
                    right.swap(pivot * size + column, pivot_row * size + column);
                }
            }

            let pivot_value = left[pivot * size + pivot];
            for column in 0..size {
                left[pivot * size + column] /= pivot_value;
                right[pivot * size + column] /= pivot_value;
            }

            for row in 0..size {
                if row == pivot {
                    continue;
                }
                let factor = left[row * size + pivot];
                if factor == 0.0 {
                    continue;
                }
                left[row * size + pivot] = 0.0;
                for column in 0..size {
                    if column != pivot {
                        left[row * size + column] -= factor * left[pivot * size + column];
                    }
                    right[row * size + column] -= factor * right[pivot * size + column];
                }
            }
        }

        Ok(self.insert_matrix_storage(
            MatrixElementKind::Float,
            size,
            size,
            right.into_iter().map(finite_float_or_na).collect(),
        ))
    }

    pub(crate) fn matrix_eigenvalues(&mut self, id: u32) -> Result<PineValue, RuntimeError> {
        let Some(matrix) = self.matrix_store.get(&id).cloned() else {
            return Ok(PineValue::Na);
        };
        if matrix.rows != matrix.columns {
            return Err(RuntimeError {
                message: "matrix eigenvalues require a square matrix".to_owned(),
            });
        }

        let mut values = Vec::with_capacity(matrix.values.len());
        for value in &matrix.values {
            let Some(number) = value.as_f64() else {
                return Ok(PineValue::Na);
            };
            if !number.is_finite() {
                return Ok(PineValue::Na);
            }
            values.push(number);
        }

        let Some(values) = eigenvalues(&values, matrix.rows) else {
            return Ok(PineValue::Na);
        };
        Ok(self.new_array_from_values(
            ArrayElementKind::Float,
            values.into_iter().map(finite_float_or_na).collect(),
        ))
    }

    pub(crate) fn matrix_eigenvectors(&mut self, id: u32) -> Result<PineValue, RuntimeError> {
        let Some(matrix) = self.matrix_store.get(&id).cloned() else {
            return Ok(PineValue::Na);
        };
        if matrix.rows != matrix.columns {
            return Err(RuntimeError {
                message: "matrix eigenvectors require a square matrix".to_owned(),
            });
        }

        let size = matrix.rows;
        let mut values = Vec::with_capacity(matrix.values.len());
        for value in &matrix.values {
            let Some(number) = value.as_f64() else {
                return Ok(PineValue::Na);
            };
            if !number.is_finite() {
                return Ok(PineValue::Na);
            }
            values.push(number);
        }

        let Some(vectors) = eigenvectors(&values, size) else {
            return Ok(PineValue::Na);
        };
        Ok(self.insert_matrix_storage(
            MatrixElementKind::Float,
            size,
            size,
            vectors.into_iter().map(finite_float_or_na).collect(),
        ))
    }

    pub(crate) fn matrix_pinv(&mut self, id: u32) -> PineValue {
        let Some(matrix) = self.matrix_store.get(&id).cloned() else {
            return PineValue::Na;
        };

        let mut values = Vec::with_capacity(matrix.values.len());
        for value in &matrix.values {
            let Some(number) = value.as_f64() else {
                return PineValue::Na;
            };
            if !number.is_finite() {
                return PineValue::Na;
            }
            values.push(number);
        }

        let inverse_values = pseudo_inverse(&values, matrix.rows, matrix.columns);
        self.insert_matrix_storage(
            MatrixElementKind::Float,
            matrix.columns,
            matrix.rows,
            inverse_values.into_iter().map(finite_float_or_na).collect(),
        )
    }

    pub(crate) fn matrix_rank(&self, id: u32) -> Option<PineValue> {
        let matrix = self.matrix_store.get(&id)?;
        if matrix.values.is_empty() {
            return Some(PineValue::Int(0));
        }

        let mut values = Vec::with_capacity(matrix.values.len());
        for value in &matrix.values {
            let Some(number) = value.as_f64() else {
                return Some(PineValue::Na);
            };
            if !number.is_finite() {
                return Some(PineValue::Na);
            }
            values.push(number);
        }

        let mut rank = 0_usize;
        let mut pivot_row = 0_usize;
        for column in 0..matrix.columns {
            let mut best_row = pivot_row;
            let mut best_abs = 0.0;
            for row in pivot_row..matrix.rows {
                let candidate_abs = values[row * matrix.columns + column].abs();
                if candidate_abs > best_abs {
                    best_abs = candidate_abs;
                    best_row = row;
                }
            }
            if best_abs == 0.0 {
                continue;
            }

            if best_row != pivot_row {
                for swap_column in 0..matrix.columns {
                    values.swap(
                        pivot_row * matrix.columns + swap_column,
                        best_row * matrix.columns + swap_column,
                    );
                }
            }

            let pivot_value = values[pivot_row * matrix.columns + column];
            for row in (pivot_row + 1)..matrix.rows {
                let factor = values[row * matrix.columns + column] / pivot_value;
                values[row * matrix.columns + column] = 0.0;
                for elimination_column in (column + 1)..matrix.columns {
                    values[row * matrix.columns + elimination_column] -=
                        factor * values[pivot_row * matrix.columns + elimination_column];
                }
            }

            rank += 1;
            pivot_row += 1;
            if pivot_row == matrix.rows {
                break;
            }
        }

        Some(PineValue::Int(rank as i64))
    }
}
