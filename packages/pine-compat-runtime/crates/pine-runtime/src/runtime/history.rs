use pine_ir::{HirExpr, HirHistoryOffset};

use crate::*;

impl<'a> HistoricalRuntime<'a> {
    pub(crate) fn eval_history(
        &mut self,
        expr: &HirExpr,
        offset: &HirHistoryOffset,
    ) -> Result<PineValue, RuntimeError> {
        let is_dynamic_offset = matches!(offset, HirHistoryOffset::Dynamic(_));
        let Some(offset) = self.eval_history_offset(offset)? else {
            self.eval_expr(expr)?;
            return Ok(PineValue::Na);
        };

        if offset == 0 {
            return self.eval_expr(expr);
        }

        self.eval_expr(expr)?;
        if let Some(series_id) = expr.series_id {
            if is_dynamic_offset
                && let Some(max_depth) = self.series_retention.max_depth_for(series_id)
                && offset > max_depth
            {
                self.history_dynamic_retention_misses =
                    self.history_dynamic_retention_misses.saturating_add(1);
                self.history_dynamic_retention_max_bars_back = Some(
                    self.history_dynamic_retention_max_bars_back
                        .map_or(max_depth, |current| current.min(max_depth)),
                );
                self.history_dynamic_retention_max_missed_offset = Some(
                    self.history_dynamic_retention_max_missed_offset
                        .map_or(offset, |current| current.max(offset)),
                );
            }
            let value = self.series_store.read(series_id, offset);
            self.clone_collection_history_value(value)
        } else {
            Ok(PineValue::Na)
        }
    }

    pub(crate) fn eval_history_offset(
        &mut self,
        offset: &HirHistoryOffset,
    ) -> Result<Option<usize>, RuntimeError> {
        let value = match offset {
            HirHistoryOffset::Constant(offset) => return Ok(Some(*offset as usize)),
            HirHistoryOffset::Dynamic(expr) => self.eval_expr(expr)?,
        };

        match value {
            PineValue::Int(value) if value >= 0 => {
                usize::try_from(value).map(Some).map_err(|_| RuntimeError {
                    message: "history offset is too large".to_owned(),
                })
            }
            PineValue::Int(_) => Err(RuntimeError {
                message: "history offset must be non-negative".to_owned(),
            }),
            PineValue::Float(value) if value >= 0.0 && value.fract() == 0.0 => {
                if value > usize::MAX as f64 {
                    Err(RuntimeError {
                        message: "history offset is too large".to_owned(),
                    })
                } else {
                    Ok(Some(value as usize))
                }
            }
            PineValue::Float(value) if value < 0.0 => Err(RuntimeError {
                message: "history offset must be non-negative".to_owned(),
            }),
            PineValue::Na => Ok(None),
            _ => Err(RuntimeError {
                message: "history offset must be an int".to_owned(),
            }),
        }
    }

    pub(crate) fn clone_collection_history_value(
        &mut self,
        value: PineValue,
    ) -> Result<PineValue, RuntimeError> {
        match value {
            PineValue::Array(id) => {
                let Some(kind) = self.array_kinds.get(&id).copied() else {
                    return Ok(PineValue::Na);
                };
                let Some(values) = self.array_values_clone(id)? else {
                    return Ok(PineValue::Na);
                };
                Ok(self.new_array_from_values_with_user_type_metadata(id, kind, values))
            }
            PineValue::Matrix(id) => Ok(self.copy_matrix(id)),
            PineValue::Map(id) => Ok(self.copy_map(id)),
            value => Ok(value),
        }
    }
}
