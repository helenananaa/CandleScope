use pine_ir::{PineType, Qualifier, ValueKind};

use crate::namespaces::types::SERIES_FLOAT_TUPLE;

pub fn fallback_bool_for_arg(arg_type: PineType) -> PineType {
    PineType::new(arg_type.qualifier, ValueKind::Bool)
}

#[must_use]
pub fn color_return_for_arg(arg_type: PineType) -> PineType {
    PineType::new(arg_type.qualifier, ValueKind::Color)
}

#[must_use]
pub fn change_return_for_arg(arg_type: PineType) -> Option<PineType> {
    match arg_type.kind {
        ValueKind::Bool => Some(PineType::new(Qualifier::Series, ValueKind::Bool)),
        ValueKind::Int | ValueKind::Float => {
            Some(PineType::new(Qualifier::Series, ValueKind::Float))
        }
        _ => None,
    }
}

#[must_use]
pub fn input_return_for_arg(arg_type: PineType) -> Option<PineType> {
    if arg_type.qualifier != Qualifier::Const {
        return None;
    }
    match arg_type.kind {
        ValueKind::Int
        | ValueKind::Float
        | ValueKind::Bool
        | ValueKind::String
        | ValueKind::Color => Some(PineType::new(Qualifier::Input, arg_type.kind)),
        _ => None,
    }
}

#[must_use]
pub const fn tuple_return_type() -> PineType {
    SERIES_FLOAT_TUPLE
}
