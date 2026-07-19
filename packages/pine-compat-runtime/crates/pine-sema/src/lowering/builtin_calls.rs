use super::*;

fn sort_field_index_expr(index: usize) -> HirExpr {
    HirExpr {
        kind: HirExprKind::Literal(HirLiteral::Int(index as i64)),
        pine_type: PineType::new(Qualifier::Const, ValueKind::Int),
        series_id: None,
    }
}

fn ascending_sort_order_expr() -> HirExpr {
    HirExpr {
        kind: HirExprKind::Literal(HirLiteral::String("order.ascending".to_owned())),
        pine_type: PineType::new(Qualifier::Const, ValueKind::String),
        series_id: None,
    }
}

impl Analyzer {
    pub(super) fn lower_builtin_call_args(
        &mut self,
        builtin_name: &str,
        args: &[CallArg],
        param_exprs: &HashMap<String, HirExpr>,
        param_types: &HashMap<String, PineType>,
    ) -> Option<Vec<HirCallArg>> {
        let sort_field_index = matches!(builtin_name, "array.sort" | "array.sort_indices")
            .then(|| self.user_type_array_sort_field_index(args))
            .flatten();
        if let Some(sort_field_index) = sort_field_index {
            let (_, id) = crate::analyzer::user_type_array_sort::user_type_array_sort_arg(args, 0)?;
            let id = self.lower_expr_with_params(&id.value, param_exprs, param_types)?;
            let order = crate::analyzer::user_type_array_sort::user_type_array_sort_arg(args, 1)
                .and_then(|(_, order)| {
                    self.lower_expr_with_params(&order.value, param_exprs, param_types)
                })
                .unwrap_or_else(ascending_sort_order_expr);
            return Some(vec![
                HirCallArg {
                    name: None,
                    value: id,
                },
                HirCallArg {
                    name: None,
                    value: order,
                },
                HirCallArg {
                    name: None,
                    value: sort_field_index_expr(sort_field_index),
                },
            ]);
        }

        args.iter()
            .map(|arg| {
                Some(HirCallArg {
                    name: arg.name.clone(),
                    value: self.lower_expr_with_params(&arg.value, param_exprs, param_types)?,
                })
            })
            .collect()
    }
}
