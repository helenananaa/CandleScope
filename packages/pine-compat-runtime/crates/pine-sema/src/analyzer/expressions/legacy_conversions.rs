use super::*;

impl Analyzer {
    pub(super) fn infer_unary_with_legacy(
        &mut self,
        op: UnaryOp,
        expr_type: PineType,
        operand_span: Span,
        expression_span: Span,
    ) -> Option<PineType> {
        let dialect = self.legacy.dialect();
        if matches!(dialect, PineDialect::V1 | PineDialect::V2)
            && matches!(op, UnaryOp::Plus | UnaryOp::Minus)
            && expr_type.kind == ValueKind::Bool
        {
            self.record_bool_to_float_coercion(operand_span);
            let result = PineType::new(expr_type.qualifier, ValueKind::Float);
            self.expr_types
                .insert(self.expr_key(expression_span), result);
            return Some(result);
        }
        if dialect != PineDialect::V6
            && op == UnaryOp::Not
            && matches!(
                expr_type.kind,
                ValueKind::Int | ValueKind::Float | ValueKind::Na
            )
        {
            self.record_numeric_to_bool_coercion(operand_span);
            let result = PineType::new(expr_type.qualifier, ValueKind::Bool);
            self.expr_types
                .insert(self.expr_key(expression_span), result);
            return Some(result);
        }
        self.infer_unary(op, expr_type, operand_span)
    }

    pub(super) fn infer_binary_with_legacy(
        &mut self,
        op: BinaryOp,
        left_type: PineType,
        right_type: PineType,
        left_span: Span,
        right_span: Span,
        span: Span,
    ) -> Option<PineType> {
        let dialect = self.legacy.dialect();
        let arithmetic = matches!(
            op,
            BinaryOp::Add | BinaryOp::Sub | BinaryOp::Mul | BinaryOp::Div | BinaryOp::Mod
        );
        let legacy_numeric_kind = |kind| {
            matches!(
                kind,
                ValueKind::Int | ValueKind::Float | ValueKind::Bool | ValueKind::Na
            )
        };
        if matches!(dialect, PineDialect::V1 | PineDialect::V2)
            && arithmetic
            && (left_type.kind == ValueKind::Bool || right_type.kind == ValueKind::Bool)
            && legacy_numeric_kind(left_type.kind)
            && legacy_numeric_kind(right_type.kind)
        {
            if left_type.kind == ValueKind::Bool {
                self.record_bool_to_float_coercion(left_span);
            }
            if right_type.kind == ValueKind::Bool {
                self.record_bool_to_float_coercion(right_span);
            }
            let result = PineType::new(
                strongest_qualifier(left_type.qualifier, right_type.qualifier),
                ValueKind::Float,
            );
            self.expr_types.insert(self.expr_key(span), result);
            return Some(result);
        }
        if dialect != PineDialect::V6
            && matches!(op, BinaryOp::And | BinaryOp::Or)
            && matches!(
                left_type.kind,
                ValueKind::Bool | ValueKind::Int | ValueKind::Float | ValueKind::Na
            )
            && matches!(
                right_type.kind,
                ValueKind::Bool | ValueKind::Int | ValueKind::Float | ValueKind::Na
            )
        {
            if left_type.kind != ValueKind::Bool {
                self.record_numeric_to_bool_coercion(left_span);
            }
            if right_type.kind != ValueKind::Bool {
                self.record_numeric_to_bool_coercion(right_span);
            }
            return Some(PineType::new(
                strongest_qualifier(left_type.qualifier, right_type.qualifier),
                ValueKind::Bool,
            ));
        }
        self.infer_binary(op, left_type, right_type, span)
    }

    pub(super) fn record_bool_to_float_coercion(&mut self, span: Span) {
        self.legacy_bool_to_float_exprs.insert(self.expr_key(span));
        let version = self.legacy.dialect().version();
        self.compatibility
            .legacy_emulations
            .push(crate::compatibility::LegacyEmulation {
                feature: format!("v{version}.bool_arithmetic"),
                behavior: format!(
                    "Pine v{version} boolean arithmetic converts true to 1.0, false to 0.0, and unavailable boolean values to canonical na before applying the numeric operator"
                ),
                span,
            });
    }

    pub(super) fn record_numeric_to_bool_coercion(&mut self, span: Span) {
        self.legacy_numeric_to_bool_exprs
            .insert(self.expr_key(span));
        let version = self.legacy.dialect().version();
        self.compatibility
            .legacy_emulations
            .push(crate::compatibility::LegacyEmulation {
                feature: format!("v{version}.numeric_to_bool"),
                behavior: format!(
                    "Pine v{version} condition conversion treats zero and na as false and every other finite numeric value as true"
                ),
                span,
            });
    }
}
