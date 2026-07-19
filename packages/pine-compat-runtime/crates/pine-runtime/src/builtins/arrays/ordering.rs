use pine_ir::HirCallArg;

use super::{compare_array_sort_values, compare_user_type_sort_field_values};
use crate::*;

impl<'a> HistoricalRuntime<'a> {
    pub(crate) fn eval_array_sort(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_expr(&args[0].value)?;
        let descending = self.eval_array_sort_descending(args, "array.sort")?;
        let PineValue::Array(id) = id else {
            return Ok(PineValue::Void);
        };
        let Some(kind) = self.array_kinds.get(&id).copied() else {
            return Ok(PineValue::Void);
        };
        if kind == ArrayElementKind::UserType {
            let Some(field_index) = self.eval_array_sort_field_index(args)? else {
                return Ok(PineValue::Void);
            };
            if let Some(mut values) = self.array_values_clone(id)? {
                validate_user_type_sort_values("array.sort", &values)?;
                values.sort_by(|left, right| {
                    compare_user_type_sort_field_values(left, right, field_index, descending)
                });
                self.array_replace_values(id, values)?;
            }
            return Ok(PineValue::Void);
        }
        if !matches!(
            kind,
            ArrayElementKind::Float | ArrayElementKind::Int | ArrayElementKind::String
        ) {
            return Ok(PineValue::Void);
        }
        if let Some(mut values) = self.array_values_clone(id)? {
            values.sort_by(|left, right| compare_array_sort_values(kind, left, right, descending));
            self.array_replace_values(id, values)?;
        }
        Ok(PineValue::Void)
    }

    pub(crate) fn eval_array_sort_indices(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_expr(&args[0].value)?;
        let descending = self.eval_array_sort_descending(args, "array.sort_indices")?;
        let PineValue::Array(id) = id else {
            return Ok(PineValue::Na);
        };
        let Some(kind) = self.array_kinds.get(&id).copied() else {
            return Ok(PineValue::Na);
        };
        let Some(values) = self.array_values_clone(id)? else {
            return Ok(PineValue::Na);
        };
        if kind == ArrayElementKind::UserType {
            let Some(field_index) = self.eval_array_sort_field_index(args)? else {
                return Ok(PineValue::Na);
            };
            validate_user_type_sort_values("array.sort_indices", &values)?;
            return Ok(self.sorted_index_array(values.len(), |left, right| {
                compare_user_type_sort_field_values(
                    &values[*left],
                    &values[*right],
                    field_index,
                    descending,
                )
            }));
        }
        if !matches!(
            kind,
            ArrayElementKind::Float | ArrayElementKind::Int | ArrayElementKind::String
        ) {
            return Ok(PineValue::Na);
        }

        Ok(self.sorted_index_array(values.len(), |left, right| {
            compare_array_sort_values(kind, &values[*left], &values[*right], descending)
        }))
    }

    fn sorted_index_array<F>(&mut self, len: usize, mut compare: F) -> PineValue
    where
        F: FnMut(&usize, &usize) -> std::cmp::Ordering,
    {
        let mut indices = (0..len).collect::<Vec<_>>();
        indices.sort_by(|left, right| compare(left, right).then_with(|| left.cmp(right)));
        let values = indices
            .into_iter()
            .map(|index| PineValue::Int(index as i64))
            .collect();
        self.new_array_from_values(ArrayElementKind::Int, values)
    }

    pub(crate) fn eval_array_sort_descending(
        &mut self,
        args: &[HirCallArg],
        callee: &str,
    ) -> Result<bool, RuntimeError> {
        match args.get(1) {
            Some(order) => match self.eval_expr(&order.value)? {
                PineValue::String(order) if order == "order.descending" => Ok(true),
                PineValue::String(order) if order == "order.ascending" => Ok(false),
                PineValue::String(order) => Err(RuntimeError {
                    message: format!("unsupported {callee} order `{order}`"),
                }),
                _ => Ok(false),
            },
            None => Ok(false),
        }
    }

    fn eval_array_sort_field_index(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<Option<usize>, RuntimeError> {
        match args.get(2) {
            Some(arg) => match self.eval_expr(&arg.value)? {
                PineValue::Int(index) if index >= 0 => Ok(Some(index as usize)),
                _ => Ok(None),
            },
            None => Ok(None),
        }
    }
}

fn validate_user_type_sort_values(callee: &str, values: &[PineValue]) -> Result<(), RuntimeError> {
    if values.iter().any(|value| matches!(value, PineValue::Na)) {
        return Err(RuntimeError {
            message: format!("{callee} cannot sort UDT arrays containing na elements"),
        });
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_na_user_type_array_elements_before_sorting() {
        let error = validate_user_type_sort_values(
            "array.sort_indices",
            &[
                PineValue::UserType(vec![PineValue::Float(1.0)]),
                PineValue::Na,
            ],
        )
        .expect_err("top-level na UDT element should fail");

        assert_eq!(
            error.message,
            "array.sort_indices cannot sort UDT arrays containing na elements"
        );
    }

    #[test]
    fn permits_na_fields_inside_concrete_user_type_elements() {
        validate_user_type_sort_values("array.sort", &[PineValue::UserType(vec![PineValue::Na])])
            .expect("na UDT fields should remain sortable");
    }
}
