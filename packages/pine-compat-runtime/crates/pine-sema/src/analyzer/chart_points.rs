use crate::prelude::*;

#[derive(Debug, Clone)]
pub(crate) struct ChartPointFieldAccess {
    pub(crate) receiver: String,
    pub(crate) index: usize,
}

pub(crate) struct ChartPointFieldMutation {
    pub(crate) pine_type: PineType,
}

pub(crate) fn chart_point_field_type(
    receiver_type: PineType,
    field_name: &str,
) -> Option<PineType> {
    let kind = match field_name {
        "time" | "index" => ValueKind::Int,
        "price" => ValueKind::Float,
        _ => return None,
    };
    Some(PineType::new(receiver_type.qualifier, kind))
}

pub(crate) fn chart_point_field_index(field_name: &str) -> Option<usize> {
    match field_name {
        "time" => Some(0),
        "index" => Some(1),
        "price" => Some(2),
        _ => None,
    }
}

impl Analyzer {
    pub(crate) fn resolve_chart_point_field_access(
        &mut self,
        parts: &[String],
        span: Span,
    ) -> Option<PineType> {
        if parts.len() != 2 {
            return None;
        }
        let receiver = &parts[0];
        let field_name = &parts[1];
        let symbol = self.scope.resolve(receiver)?;
        if symbol.pine_type.kind != ValueKind::ChartPoint {
            return None;
        }
        let Some(pine_type) = chart_point_field_type(symbol.pine_type, field_name) else {
            self.diagnostics.push(Diagnostic::error(
                "E_CHART_POINT_UNKNOWN_FIELD",
                format!("unknown field `{field_name}` on `chart.point`"),
                span,
            ));
            return Some(UNKNOWN);
        };
        self.bind_symbol(receiver, span, symbol);
        self.compatibility.supported.push(FeatureUse {
            feature: "chart.point fields".to_owned(),
            span,
        });
        Some(pine_type)
    }

    pub(crate) fn type_of_chart_point_field_access(&self, parts: &[String]) -> Option<PineType> {
        if parts.len() != 2 {
            return None;
        }
        let symbol = self.scope.resolve(&parts[0])?;
        if symbol.pine_type.kind != ValueKind::ChartPoint {
            return None;
        }
        chart_point_field_type(symbol.pine_type, &parts[1])
    }

    pub(crate) fn type_of_bound_chart_point_field_access(
        &self,
        parts: &[String],
        span: Span,
    ) -> Option<PineType> {
        if parts.len() != 2 {
            return None;
        }
        let symbol = self
            .bound_symbol(&parts[0], span)
            .or_else(|| self.scope.resolve(&parts[0]))?;
        if symbol.pine_type.kind != ValueKind::ChartPoint {
            return None;
        }
        chart_point_field_type(symbol.pine_type, &parts[1])
    }

    pub(crate) fn resolve_chart_point_field_mutation(
        &mut self,
        receiver: &str,
        field_name: &str,
        span: Span,
    ) -> Option<ChartPointFieldMutation> {
        let symbol = self.scope.resolve(receiver)?;
        if symbol.pine_type.kind != ValueKind::ChartPoint {
            return None;
        }
        let Some(pine_type) = chart_point_field_type(symbol.pine_type, field_name) else {
            self.diagnostics.push(Diagnostic::error(
                "E_CHART_POINT_UNKNOWN_FIELD",
                format!("unknown field `{field_name}` on `chart.point`"),
                span,
            ));
            return None;
        };
        self.bind_symbol(receiver, span, symbol);
        Some(ChartPointFieldMutation { pine_type })
    }

    pub(crate) fn chart_point_field_access_for_lowering(
        &self,
        parts: &[String],
        span: Span,
    ) -> Option<ChartPointFieldAccess> {
        if parts.len() != 2 {
            return None;
        }
        let symbol = self
            .bound_symbol(&parts[0], span)
            .or_else(|| self.scope.resolve(&parts[0]))?;
        if symbol.pine_type.kind != ValueKind::ChartPoint {
            return None;
        }
        Some(ChartPointFieldAccess {
            receiver: parts[0].clone(),
            index: chart_point_field_index(&parts[1])?,
        })
    }
}
