use pine_ir::{HirCallArg, HirExpr};

use crate::builtins::strings::{
    stringify_array_join_element, stringify_user_type_array_join_element,
};
use crate::*;

mod calls;
mod constructors;
mod ordering;
mod statistics;
mod store;
mod support;

pub(crate) use support::*;

impl<'a> HistoricalRuntime<'a> {
    pub(crate) fn eval_array_size(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_expr(&args[0].value)?;
        let PineValue::Array(id) = id else {
            return Ok(PineValue::Na);
        };
        let Some(len) = self.array_len(id)? else {
            return Ok(PineValue::Na);
        };
        Ok(PineValue::Int(len as i64))
    }

    pub(crate) fn eval_array_push(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_expr(&args[0].value)?;
        let PineValue::Array(id) = id else {
            let _ = self.eval_expr(&args[1].value)?;
            return Ok(PineValue::Void);
        };
        let Some(kind) = self.array_kinds.get(&id).copied() else {
            let _ = self.eval_expr(&args[1].value)?;
            return Ok(PineValue::Void);
        };
        let value = self.eval_array_value(&args[1].value, kind)?;
        let Some(len) = self.array_len(id)? else {
            return Ok(PineValue::Void);
        };
        let Some(parent_len) = self.array_parent_len_for_insert(id) else {
            return Ok(PineValue::Void);
        };
        if parent_len >= MAX_ARRAY_ELEMENTS {
            return Err(RuntimeError {
                message: format!("array.push cannot exceed {MAX_ARRAY_ELEMENTS} elements"),
            });
        }
        self.array_insert_value(id, len as i64, value)?;
        Ok(PineValue::Void)
    }

    pub(crate) fn eval_array_get(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_expr(&args[0].value)?;
        let index = self.eval_expr(&args[1].value)?.as_i64();
        let (PineValue::Array(id), Some(index)) = (id, index) else {
            return Ok(PineValue::Na);
        };
        Ok(self.array_get_cloned(id, index)?.unwrap_or(PineValue::Na))
    }

    pub(crate) fn eval_array_set(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_expr(&args[0].value)?;
        let index = self.eval_expr(&args[1].value)?.as_i64();
        let (PineValue::Array(id), Some(index)) = (id, index) else {
            let _ = self.eval_expr(&args[2].value)?;
            return Ok(PineValue::Void);
        };
        let Some(kind) = self.array_kinds.get(&id).copied() else {
            let _ = self.eval_expr(&args[2].value)?;
            return Ok(PineValue::Void);
        };
        let value = self.eval_array_value(&args[2].value, kind)?;
        self.array_set_value(id, index, value)?;
        Ok(PineValue::Void)
    }

    pub(crate) fn eval_array_insert(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_expr(&args[0].value)?;
        let index = self.eval_expr(&args[1].value)?.as_i64();
        let (PineValue::Array(id), Some(index)) = (id, index) else {
            let _ = self.eval_expr(&args[2].value)?;
            return Ok(PineValue::Void);
        };
        let Some(kind) = self.array_kinds.get(&id).copied() else {
            let _ = self.eval_expr(&args[2].value)?;
            return Ok(PineValue::Void);
        };
        let value = self.eval_array_value(&args[2].value, kind)?;
        let Some(parent_len) = self.array_parent_len_for_insert(id) else {
            return Ok(PineValue::Void);
        };
        if parent_len >= MAX_ARRAY_ELEMENTS {
            return Err(RuntimeError {
                message: format!("array.insert cannot exceed {MAX_ARRAY_ELEMENTS} elements"),
            });
        }
        self.array_insert_value(id, index, value)?;
        Ok(PineValue::Void)
    }

    pub(crate) fn eval_array_pop(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_expr(&args[0].value)?;
        let PineValue::Array(id) = id else {
            return Ok(PineValue::Na);
        };
        let Some(len) = self.array_len(id)? else {
            return Ok(PineValue::Na);
        };
        if len == 0 {
            return Ok(PineValue::Na);
        }
        Ok(self
            .array_remove_value(id, (len - 1) as i64)?
            .unwrap_or(PineValue::Na))
    }

    pub(crate) fn eval_array_remove(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_expr(&args[0].value)?;
        let index = self.eval_expr(&args[1].value)?.as_i64();
        let (PineValue::Array(id), Some(index)) = (id, index) else {
            return Ok(PineValue::Na);
        };
        Ok(self.array_remove_value(id, index)?.unwrap_or(PineValue::Na))
    }

    pub(crate) fn eval_array_shift(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_expr(&args[0].value)?;
        let PineValue::Array(id) = id else {
            return Ok(PineValue::Na);
        };
        let Some(len) = self.array_len(id)? else {
            return Ok(PineValue::Na);
        };
        if len == 0 {
            return Ok(PineValue::Na);
        }
        Ok(self.array_remove_value(id, 0)?.unwrap_or(PineValue::Na))
    }

    pub(crate) fn eval_array_unshift(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_expr(&args[0].value)?;
        let PineValue::Array(id) = id else {
            let _ = self.eval_expr(&args[1].value)?;
            return Ok(PineValue::Void);
        };
        let Some(kind) = self.array_kinds.get(&id).copied() else {
            let _ = self.eval_expr(&args[1].value)?;
            return Ok(PineValue::Void);
        };
        let value = self.eval_array_value(&args[1].value, kind)?;
        let Some(parent_len) = self.array_parent_len_for_insert(id) else {
            return Ok(PineValue::Void);
        };
        if parent_len >= MAX_ARRAY_ELEMENTS {
            return Err(RuntimeError {
                message: format!("array.unshift cannot exceed {MAX_ARRAY_ELEMENTS} elements"),
            });
        }
        self.array_insert_value(id, 0, value)?;
        Ok(PineValue::Void)
    }

    pub(crate) fn eval_array_fill(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_expr(&args[0].value)?;
        let PineValue::Array(id) = id else {
            let _ = self.eval_expr(&args[1].value)?;
            if let Some(index_from) = args.get(2) {
                let _ = self.eval_expr(&index_from.value)?;
            }
            if let Some(index_to) = args.get(3) {
                let _ = self.eval_expr(&index_to.value)?;
            }
            return Ok(PineValue::Void);
        };
        let Some(kind) = self.array_kinds.get(&id).copied() else {
            let _ = self.eval_expr(&args[1].value)?;
            if let Some(index_from) = args.get(2) {
                let _ = self.eval_expr(&index_from.value)?;
            }
            if let Some(index_to) = args.get(3) {
                let _ = self.eval_expr(&index_to.value)?;
            }
            return Ok(PineValue::Void);
        };
        let value = self.eval_array_value(&args[1].value, kind)?;
        let index_from = if let Some(index_from) = args.get(2) {
            self.eval_expr(&index_from.value)?.as_i64()
        } else {
            Some(0)
        };
        let Some(index_from) = index_from else {
            return Ok(PineValue::Void);
        };
        let index_to = if let Some(index_to) = args.get(3) {
            self.eval_expr(&index_to.value)?.as_i64()
        } else {
            self.array_len(id)?.map(|len| len as i64)
        };
        let Some(index_to) = index_to else {
            return Ok(PineValue::Void);
        };
        if index_from < 0 || index_to < 0 || index_from > index_to {
            return Ok(PineValue::Void);
        }
        let index_from = index_from as usize;
        let index_to = index_to as usize;
        if let Some(len) = self.array_len(id)? {
            if index_to > len {
                return Ok(PineValue::Void);
            }
            for index in index_from..index_to {
                self.array_set_value(id, index as i64, value.clone())?;
            }
        }
        Ok(PineValue::Void)
    }

    pub(crate) fn eval_array_first(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_expr(&args[0].value)?;
        let PineValue::Array(id) = id else {
            return Ok(PineValue::Na);
        };
        let Some(len) = self.array_len(id)? else {
            return Ok(PineValue::Na);
        };
        if len == 0 {
            return Ok(PineValue::Na);
        }
        Ok(self.array_get_cloned(id, 0)?.unwrap_or(PineValue::Na))
    }

    pub(crate) fn eval_array_last(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_expr(&args[0].value)?;
        let PineValue::Array(id) = id else {
            return Ok(PineValue::Na);
        };
        let Some(len) = self.array_len(id)? else {
            return Ok(PineValue::Na);
        };
        if len == 0 {
            return Ok(PineValue::Na);
        }
        Ok(self
            .array_get_cloned(id, (len - 1) as i64)?
            .unwrap_or(PineValue::Na))
    }

    pub(crate) fn eval_array_copy(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_expr(&args[0].value)?;
        let PineValue::Array(id) = id else {
            return Ok(PineValue::Na);
        };
        let Some(kind) = self.array_kinds.get(&id).copied() else {
            return Ok(PineValue::Na);
        };
        let Some(values) = self.array_values_clone(id)? else {
            return Ok(PineValue::Na);
        };
        Ok(self.new_array_from_values_with_user_type_metadata(id, kind, values))
    }

    pub(crate) fn eval_array_slice(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_expr(&args[0].value)?;
        let index_from = self.eval_expr(&args[1].value)?.as_i64();
        let index_to = self.eval_expr(&args[2].value)?.as_i64();
        let (PineValue::Array(id), Some(index_from), Some(index_to)) = (id, index_from, index_to)
        else {
            return Ok(PineValue::Na);
        };
        if index_from < 0 || index_to < 0 || index_from > index_to {
            return Ok(PineValue::Na);
        }

        if !self.array_kinds.contains_key(&id) {
            return Ok(PineValue::Na);
        }
        let Some(len) = self.array_len(id)? else {
            return Ok(PineValue::Na);
        };
        let index_from = index_from as usize;
        let index_to = index_to as usize;
        if index_to > len {
            return Ok(PineValue::Na);
        }

        Ok(self.new_array_slice(id, index_from, index_to))
    }

    pub(crate) fn eval_array_concat(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let target = self.eval_expr(&args[0].value)?;
        let source = self.eval_expr(&args[1].value)?;
        let (PineValue::Array(target_id), PineValue::Array(source_id)) = (target, source) else {
            return Ok(PineValue::Na);
        };
        let Some(target_kind) = self.array_kinds.get(&target_id).copied() else {
            return Ok(PineValue::Na);
        };
        let Some(source_kind) = self.array_kinds.get(&source_id).copied() else {
            return Ok(PineValue::Na);
        };
        if target_kind != source_kind {
            return Ok(PineValue::Na);
        }
        let Some(source_values) = self.array_values_clone(source_id)? else {
            return Ok(PineValue::Na);
        };
        let Some(target_len) = self.array_len(target_id)? else {
            return Ok(PineValue::Na);
        };
        let Some(parent_len) = self.array_parent_len_for_insert(target_id) else {
            return Ok(PineValue::Na);
        };
        if parent_len + source_values.len() > MAX_ARRAY_ELEMENTS {
            return Err(RuntimeError {
                message: format!("array.concat cannot exceed {MAX_ARRAY_ELEMENTS} elements"),
            });
        }
        for (offset, value) in source_values.into_iter().enumerate() {
            self.array_insert_value(target_id, (target_len + offset) as i64, value)?;
        }
        Ok(PineValue::Array(target_id))
    }

    pub(crate) fn eval_array_reverse(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_expr(&args[0].value)?;
        let PineValue::Array(id) = id else {
            return Ok(PineValue::Void);
        };
        if let Some(mut values) = self.array_values_clone(id)? {
            values.reverse();
            self.array_replace_values(id, values)?;
        }
        Ok(PineValue::Void)
    }

    pub(crate) fn eval_array_join(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_expr(&args[0].value)?;
        let PineValue::Array(id) = id else {
            if let Some(separator) = args.get(1) {
                let _ = self.eval_expr(&separator.value)?;
            }
            return Ok(PineValue::Na);
        };
        let separator = if let Some(separator) = args.get(1) {
            match self.eval_expr(&separator.value)? {
                PineValue::String(separator) => separator,
                PineValue::Na => ",".to_owned(),
                _ => return Ok(PineValue::Na),
            }
        } else {
            ",".to_owned()
        };
        let Some(values) = self.array_values_clone(id)? else {
            return Ok(PineValue::Na);
        };
        let user_type_name = self.array_user_types.get(&id).map(String::as_str);
        let mut result = String::new();
        for (index, value) in values.iter().enumerate() {
            if index > 0 {
                result.push_str(&separator);
            }
            if let Some(type_name) = user_type_name {
                result.push_str(&stringify_user_type_array_join_element(
                    value,
                    type_name,
                    &self.program.user_types,
                ));
            } else {
                result.push_str(&stringify_array_join_element(value));
            }
        }
        self.string_value_or_error(result, "array.join")
    }

    pub(crate) fn eval_array_clear(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let id = self.eval_expr(&args[0].value)?;
        let PineValue::Array(id) = id else {
            return Ok(PineValue::Void);
        };
        if let Some(len) = self.array_len(id)? {
            for _ in 0..len {
                let _ = self.array_remove_value(id, 0)?;
            }
        }
        Ok(PineValue::Void)
    }

    pub(crate) fn eval_array_value(
        &mut self,
        expr: &HirExpr,
        kind: ArrayElementKind,
    ) -> Result<PineValue, RuntimeError> {
        let value = self.eval_expr(expr)?;
        Ok(array_value_for_kind(kind, value))
    }
}

#[cfg(test)]
mod tests {
    use pine_ir::{
        DrawingSettings, HirExpr, HirExprKind, HirHistoryRequirements, HirLiteral, HirProgram,
        HirUserTypeIdentity, PineType, Qualifier, ScriptMode, StrategySettings, ValueKind,
    };

    use super::*;

    fn runtime() -> HistoricalRuntime<'static> {
        let program = Box::leak(Box::new(HirProgram {
            language_version: None,
            script_mode: ScriptMode::Indicator,
            strategy_settings: StrategySettings::default(),
            drawing_settings: DrawingSettings::default(),
            user_types: Vec::new(),
            symbols: Vec::new(),
            statements: Vec::new(),
            next_series_id: 0,
            next_call_site_id: 0,
            next_var_slot_id: 0,
            max_bars_back: None,
            series_max_bars_back: Vec::new(),
            history: HirHistoryRequirements::default(),
            series_history: Vec::new(),
        }));
        HistoricalRuntime::new(program)
    }

    fn hir_float(value: f64) -> HirExpr {
        HirExpr {
            kind: HirExprKind::Literal(HirLiteral::Float(value)),
            pine_type: PineType::new(Qualifier::Const, ValueKind::Float),
            series_id: None,
        }
    }

    fn hir_point(x: f64) -> HirExpr {
        HirExpr {
            kind: HirExprKind::UserTypeConstruct {
                identity: HirUserTypeIdentity {
                    source_id: 0,
                    type_name: "Point".to_owned(),
                },
                fields: vec![hir_float(x)],
            },
            pine_type: PineType::new(Qualifier::Series, ValueKind::UserType),
            series_id: None,
        }
    }

    #[test]
    fn evaluates_internal_user_type_array_construct_with_metadata() {
        let mut runtime = runtime();
        let expr = HirExpr {
            kind: HirExprKind::UserTypeArrayConstruct {
                type_name: "Point".to_owned(),
                elements: vec![hir_point(1.0), hir_point(2.0)],
            },
            pine_type: PineType::new(Qualifier::Series, ValueKind::UserTypeArray),
            series_id: None,
        };

        let PineValue::Array(id) = runtime.eval_expr(&expr).expect("array construct succeeds")
        else {
            panic!("expected user-defined type array");
        };

        assert_eq!(
            runtime.array_kinds.get(&id),
            Some(&ArrayElementKind::UserType)
        );
        assert_eq!(runtime.array_user_type_name(id), Some("Point"));
        assert_eq!(
            runtime.array_store.get(&id),
            Some(&vec![
                PineValue::UserType(vec![PineValue::Float(1.0)]),
                PineValue::UserType(vec![PineValue::Float(2.0)]),
            ])
        );
    }

    #[test]
    fn preserves_user_type_array_metadata_across_internal_clones() {
        let mut runtime = runtime();
        let source = runtime.new_user_type_array_from_values(
            "Point",
            vec![
                PineValue::UserType(vec![PineValue::Float(1.0)]),
                PineValue::UserType(vec![PineValue::Float(2.0)]),
            ],
        );
        let PineValue::Array(source_id) = source else {
            panic!("expected source array");
        };
        assert_eq!(
            runtime.array_kinds.get(&source_id),
            Some(&ArrayElementKind::UserType)
        );
        assert_eq!(runtime.array_user_type_name(source_id), Some("Point"));

        let copied = runtime.new_array_from_values_with_user_type_metadata(
            source_id,
            ArrayElementKind::UserType,
            vec![PineValue::UserType(vec![PineValue::Float(3.0)])],
        );
        let PineValue::Array(copied_id) = copied else {
            panic!("expected copied array");
        };
        assert_eq!(
            runtime.array_kinds.get(&copied_id),
            Some(&ArrayElementKind::UserType)
        );
        assert_eq!(runtime.array_user_type_name(copied_id), Some("Point"));

        let slice = runtime.new_array_slice(source_id, 0, 1);
        let PineValue::Array(slice_id) = slice else {
            panic!("expected slice array");
        };
        assert_eq!(
            runtime.array_kinds.get(&slice_id),
            Some(&ArrayElementKind::UserType)
        );
        assert_eq!(runtime.array_user_type_name(slice_id), Some("Point"));

        let history = runtime
            .clone_collection_history_value(PineValue::Array(source_id))
            .expect("history clone should succeed");
        let PineValue::Array(history_id) = history else {
            panic!("expected history array");
        };
        assert_eq!(
            runtime.array_kinds.get(&history_id),
            Some(&ArrayElementKind::UserType)
        );
        assert_eq!(runtime.array_user_type_name(history_id), Some("Point"));
    }

    #[test]
    fn cloned_runtime_preserves_user_type_array_metadata() {
        let mut runtime = runtime();
        let source = runtime.new_user_type_array_from_values(
            "Point",
            vec![PineValue::UserType(vec![PineValue::Float(1.0)])],
        );
        let PineValue::Array(source_id) = source else {
            panic!("expected source array");
        };

        let cloned = runtime.clone();

        assert_eq!(
            cloned.array_kinds.get(&source_id),
            Some(&ArrayElementKind::UserType)
        );
        assert_eq!(cloned.array_user_type_name(source_id), Some("Point"));
    }
}
