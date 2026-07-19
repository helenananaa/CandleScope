use super::*;

pub(crate) fn lower_literal(literal: &Literal) -> HirLiteral {
    match literal {
        Literal::Int(value) => HirLiteral::Int(*value),
        Literal::Float(value) => HirLiteral::Float(*value),
        Literal::Bool(value) => HirLiteral::Bool(*value),
        Literal::String(value) => HirLiteral::String(value.clone()),
        Literal::ColorHex(value) => HirLiteral::ColorHex(value.clone()),
    }
}

pub(super) fn literal_series_key(literal: &Literal) -> String {
    match literal {
        Literal::Int(value) => format!("int:{value}"),
        Literal::Float(value) => format!("float:{}", value.to_bits()),
        Literal::Bool(value) => format!("bool:{value}"),
        Literal::String(value) => format!("string:{value:?}"),
        Literal::ColorHex(value) => format!("color:{value}"),
    }
}
