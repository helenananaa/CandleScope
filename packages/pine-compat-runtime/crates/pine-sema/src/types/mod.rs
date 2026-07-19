use pine_builtins::Accepts;
use pine_ir::{PineType, Qualifier, ValueKind};
use pine_syntax::BinaryOp;

mod constants;
mod formatting;
mod matrices;

pub(crate) use constants::{
    const_color_value, const_int_value, const_numeric_value, const_string_value, literal_type,
};
pub(crate) use formatting::{pine_type_name, value_kind_name};
pub(crate) use matrices::{
    accepts_matrix_element_arg, accepts_matrix_element_array_arg, is_matrix_kind,
    is_numeric_matrix_kind, matrix_array_return_type, matrix_element_return_type,
    matrix_method_builtin_name, matrix_mult_return_type,
};

pub(crate) const UNKNOWN: PineType = PineType::new(Qualifier::Series, ValueKind::Na);

pub(crate) fn accepts_type(accepts: Accepts, arg_type: PineType) -> bool {
    match accepts {
        Accepts::Any => true,
        Accepts::Exact(expected) => can_assign(expected, arg_type),
        Accepts::Kind(kind) => arg_type.kind == kind,
        Accepts::Numeric => is_numeric(arg_type.kind),
        Accepts::SeriesFloat => {
            accepts_kind_exact(arg_type, Qualifier::Series, |kind| kind == ValueKind::Float)
        }
        Accepts::SeriesNumeric => accepts_kind_exact(arg_type, Qualifier::Series, is_numeric),
        Accepts::SeriesNumericOrBool => accepts_kind_exact(arg_type, Qualifier::Series, |kind| {
            is_numeric(kind) || kind == ValueKind::Bool
        }),
        Accepts::SeriesOrSimpleNumeric => {
            accepts_kind_at_most(arg_type, Qualifier::Series, is_numeric)
        }
        Accepts::SeriesOrSimpleNumericOrBool => {
            accepts_kind_at_most(arg_type, Qualifier::Series, |kind| {
                is_numeric(kind) || kind == ValueKind::Bool
            })
        }
        Accepts::QualifierBoundScalar(bound) => bound.accepts(arg_type),
        Accepts::ColorCompatible => {
            accepts_kind_compatible(arg_type, |kind| kind == ValueKind::Color)
        }
        Accepts::StringCompatible => {
            accepts_kind_compatible(arg_type, |kind| kind == ValueKind::String)
        }
        Accepts::StringConvertible => accepts_kind_compatible(arg_type, |kind| {
            matches!(
                kind,
                ValueKind::Int
                    | ValueKind::Float
                    | ValueKind::Bool
                    | ValueKind::String
                    | ValueKind::FloatArray
                    | ValueKind::IntArray
                    | ValueKind::BoolArray
                    | ValueKind::StringArray
                    | ValueKind::FloatMatrix
                    | ValueKind::IntMatrix
                    | ValueKind::BoolMatrix
                    | ValueKind::StringMatrix
            )
        }),
        Accepts::FormatConvertible => accepts_kind_compatible(arg_type, |kind| {
            matches!(
                kind,
                ValueKind::Int
                    | ValueKind::Float
                    | ValueKind::Bool
                    | ValueKind::String
                    | ValueKind::FloatArray
                    | ValueKind::IntArray
                    | ValueKind::BoolArray
                    | ValueKind::StringArray
            )
        }),
        Accepts::StringOrIntCompatible => accepts_kind_compatible(arg_type, |kind| {
            matches!(kind, ValueKind::String | ValueKind::Int)
        }),
        Accepts::CastScalar => accepts_kind_compatible(arg_type, |kind| {
            matches!(kind, ValueKind::Int | ValueKind::Float | ValueKind::Bool)
        }),
        Accepts::StringCastScalar => accepts_kind_compatible(arg_type, |kind| {
            matches!(
                kind,
                ValueKind::Int | ValueKind::Float | ValueKind::Bool | ValueKind::String
            )
        }),
        Accepts::ValueWhenSource => accepts_kind_compatible(arg_type, |kind| {
            matches!(
                kind,
                ValueKind::Int | ValueKind::Float | ValueKind::Bool | ValueKind::Color
            )
        }),
        Accepts::NumericOrColorCompatible => accepts_kind_compatible(arg_type, |kind| {
            is_numeric(kind) || kind == ValueKind::Color
        }),
        Accepts::NumericCompatible => accepts_kind_compatible(arg_type, is_numeric),
        Accepts::IntCompatible => accepts_kind_compatible(arg_type, |kind| kind == ValueKind::Int),
        Accepts::BoolCompatible => {
            accepts_kind_compatible(arg_type, |kind| kind == ValueKind::Bool)
        }
        Accepts::LabelCompatible => {
            accepts_kind_compatible(arg_type, |kind| kind == ValueKind::Label)
        }
        Accepts::LineCompatible => {
            accepts_kind_compatible(arg_type, |kind| kind == ValueKind::Line)
        }
        Accepts::LineFillCompatible => {
            accepts_kind_compatible(arg_type, |kind| kind == ValueKind::LineFill)
        }
        Accepts::PolylineCompatible => {
            accepts_kind_compatible(arg_type, |kind| kind == ValueKind::Polyline)
        }
        Accepts::BoxCompatible => accepts_kind_compatible(arg_type, |kind| kind == ValueKind::Box),
        Accepts::TableCompatible => {
            accepts_kind_compatible(arg_type, |kind| kind == ValueKind::Table)
        }
        Accepts::ChartPointCompatible => {
            accepts_kind_compatible(arg_type, |kind| kind == ValueKind::ChartPoint)
        }
        Accepts::PlotOrHLine => matches!(arg_type.kind, ValueKind::Plot | ValueKind::HLine),
        Accepts::Array => is_array_kind(arg_type.kind),
        Accepts::FloatMatrix => arg_type.kind == ValueKind::FloatMatrix,
        Accepts::NumericMatrix => matrices::is_numeric_matrix_kind(arg_type.kind),
        Accepts::Matrix => is_matrix_kind(arg_type.kind),
        Accepts::Map => arg_type.kind == ValueKind::Map,
        Accepts::MatrixOrNumericCompatibleWithMatrixCounterpart(_) => {
            is_matrix_kind(arg_type.kind) || accepts_type(Accepts::NumericCompatible, arg_type)
        }
        Accepts::MatrixOrNumericOrNumericArrayCompatibleWithMatrixCounterpart(_) => {
            is_matrix_kind(arg_type.kind)
                || accepts_type(Accepts::NumericCompatible, arg_type)
                || accepts_type(Accepts::NumericArray, arg_type)
        }
        Accepts::MatrixElementCompatible(_) => false,
        Accepts::MatrixElementArray(_) => false,
        Accepts::Tuple => arg_type.kind == ValueKind::Tuple,
        Accepts::ScalarArray => is_scalar_array_kind(arg_type.kind),
        Accepts::NumericArray => is_numeric_array_kind(arg_type.kind),
        Accepts::NumericOrBoolArray => matches!(
            arg_type.kind.array_element_kind(),
            Some(ValueKind::Float | ValueKind::Int | ValueKind::Bool)
        ),
        Accepts::NumericOrStringArray => matches!(
            arg_type.kind.array_element_kind(),
            Some(ValueKind::Float | ValueKind::Int | ValueKind::String)
        ),
        Accepts::InputDefval => accepts_kind_exact(arg_type, Qualifier::Const, |kind| {
            matches!(
                kind,
                ValueKind::Int
                    | ValueKind::Float
                    | ValueKind::Bool
                    | ValueKind::String
                    | ValueKind::Color
            )
        }),
    }
}
fn accepts_kind_exact(
    arg_type: PineType,
    qualifier: Qualifier,
    accepts_kind: impl Fn(ValueKind) -> bool,
) -> bool {
    arg_type.qualifier == qualifier && accepts_kind(arg_type.kind)
}
fn accepts_kind_at_most(
    arg_type: PineType,
    max_qualifier: Qualifier,
    accepts_kind: impl Fn(ValueKind) -> bool,
) -> bool {
    qualifier_at_most(arg_type.qualifier, max_qualifier) && accepts_kind(arg_type.kind)
}

fn accepts_kind_compatible(arg_type: PineType, accepts_kind: impl Fn(ValueKind) -> bool) -> bool {
    qualifier_at_most(arg_type.qualifier, Qualifier::Series)
        && (arg_type.kind == ValueKind::Na || accepts_kind(arg_type.kind))
}

pub(crate) fn can_assign(target: PineType, value: PineType) -> bool {
    if target.kind == value.kind {
        return qualifier_at_most(value.qualifier, target.qualifier)
            || target.qualifier == Qualifier::Series;
    }
    if value.kind == ValueKind::Na && can_assign_na_to_kind(target.kind) {
        return qualifier_at_most(value.qualifier, target.qualifier)
            || target.qualifier == Qualifier::Series;
    }

    target.kind == ValueKind::Float
        && value.kind == ValueKind::Int
        && (qualifier_at_most(value.qualifier, target.qualifier)
            || target.qualifier == Qualifier::Series)
}

fn can_assign_na_to_kind(kind: ValueKind) -> bool {
    matches!(
        kind,
        ValueKind::Int
            | ValueKind::Float
            | ValueKind::Bool
            | ValueKind::String
            | ValueKind::Color
            | ValueKind::Label
            | ValueKind::Line
            | ValueKind::LineFill
            | ValueKind::Polyline
            | ValueKind::Box
            | ValueKind::Table
            | ValueKind::ChartPoint
            | ValueKind::UserType
            | ValueKind::IntArray
            | ValueKind::FloatArray
            | ValueKind::BoolArray
            | ValueKind::StringArray
            | ValueKind::ColorArray
            | ValueKind::LabelArray
            | ValueKind::LineArray
            | ValueKind::LineFillArray
            | ValueKind::BoxArray
            | ValueKind::TableArray
            | ValueKind::ChartPointArray
            | ValueKind::UserTypeArray
            | ValueKind::FloatMatrix
            | ValueKind::IntMatrix
            | ValueKind::BoolMatrix
            | ValueKind::StringMatrix
            | ValueKind::ColorMatrix
            | ValueKind::Map
    )
}
pub(crate) fn qualifier_at_most(actual: Qualifier, max: Qualifier) -> bool {
    qualifier_rank(actual) <= qualifier_rank(max)
}
pub(crate) fn strongest_qualifier(left: Qualifier, right: Qualifier) -> Qualifier {
    if qualifier_rank(left) >= qualifier_rank(right) {
        left
    } else {
        right
    }
}
pub(crate) fn qualifier_rank(qualifier: Qualifier) -> u8 {
    match qualifier {
        Qualifier::Const => 0,
        Qualifier::Input => 1,
        Qualifier::Simple => 2,
        Qualifier::Series => 3,
    }
}
pub(crate) fn is_numeric(kind: ValueKind) -> bool {
    matches!(kind, ValueKind::Int | ValueKind::Float)
}
pub(crate) fn numeric_result_kind(op: BinaryOp, left: ValueKind, right: ValueKind) -> ValueKind {
    if op == BinaryOp::Div || left == ValueKind::Float || right == ValueKind::Float {
        ValueKind::Float
    } else {
        ValueKind::Int
    }
}
pub(crate) fn common_kind(left: ValueKind, right: ValueKind) -> Option<ValueKind> {
    if left == right {
        Some(left)
    } else if is_numeric(left) && is_numeric(right) {
        Some(ValueKind::Float)
    } else if left == ValueKind::Na {
        Some(right)
    } else if right == ValueKind::Na {
        Some(left)
    } else {
        None
    }
}
pub(crate) fn merge_result_types(current: Option<PineType>, next: PineType) -> Option<PineType> {
    match current {
        Some(current) => Some(PineType::new(
            strongest_qualifier(current.qualifier, next.qualifier),
            common_kind(current.kind, next.kind)?,
        )),
        None => Some(next),
    }
}
pub(crate) fn promoted_numeric_type(arg_types: &[Option<PineType>]) -> Option<PineType> {
    let mut result: Option<PineType> = None;
    for arg_type in arg_types {
        let arg_type = (*arg_type)?;
        if !is_numeric(arg_type.kind) && arg_type.kind != ValueKind::Na {
            return None;
        }
        result = Some(match result {
            Some(current) => PineType::new(
                strongest_qualifier(current.qualifier, arg_type.qualifier),
                common_kind(current.kind, arg_type.kind)?,
            ),
            None => arg_type,
        });
    }
    result
}
pub(crate) fn float_return_for_arg(arg_type: PineType) -> PineType {
    PineType::new(arg_type.qualifier, ValueKind::Float)
}
pub(crate) fn int_return_for_arg(arg_type: PineType) -> PineType {
    PineType::new(arg_type.qualifier, ValueKind::Int)
}
pub(crate) fn series_return_for_arg(arg_type: PineType) -> Option<PineType> {
    match arg_type.kind {
        ValueKind::Int | ValueKind::Float | ValueKind::Bool | ValueKind::Color | ValueKind::Na => {
            Some(PineType::new(Qualifier::Series, arg_type.kind))
        }
        _ => None,
    }
}
pub(crate) fn promoted_float_type(arg_types: &[Option<PineType>]) -> Option<PineType> {
    let mut qualifier: Option<Qualifier> = None;
    for arg_type in arg_types {
        let arg_type = (*arg_type)?;
        if !is_numeric(arg_type.kind) && arg_type.kind != ValueKind::Na {
            return None;
        }
        qualifier = Some(match qualifier {
            Some(current) => strongest_qualifier(current, arg_type.qualifier),
            None => arg_type.qualifier,
        });
    }
    qualifier.map(|qualifier| PineType::new(qualifier, ValueKind::Float))
}
pub(crate) fn promoted_color_type(arg_types: &[Option<PineType>]) -> Option<PineType> {
    let mut qualifier: Option<Qualifier> = None;
    for arg_type in arg_types {
        let arg_type = (*arg_type)?;
        qualifier = Some(match qualifier {
            Some(current) => strongest_qualifier(current, arg_type.qualifier),
            None => arg_type.qualifier,
        });
    }
    qualifier.map(|qualifier| PineType::new(qualifier, ValueKind::Color))
}
pub(crate) fn promoted_bool_type(arg_types: &[Option<PineType>]) -> Option<PineType> {
    let mut qualifier: Option<Qualifier> = None;
    for arg_type in arg_types {
        let arg_type = (*arg_type)?;
        qualifier = Some(match qualifier {
            Some(current) => strongest_qualifier(current, arg_type.qualifier),
            None => arg_type.qualifier,
        });
    }
    qualifier.map(|qualifier| PineType::new(qualifier, ValueKind::Bool))
}
pub(crate) fn promoted_int_type(arg_types: &[Option<PineType>]) -> Option<PineType> {
    promoted_kind_type(arg_types, ValueKind::Int)
}
pub(crate) fn promoted_string_type(arg_types: &[Option<PineType>]) -> Option<PineType> {
    promoted_kind_type(arg_types, ValueKind::String)
}
pub(crate) fn promoted_kind_type(
    arg_types: &[Option<PineType>],
    kind: ValueKind,
) -> Option<PineType> {
    let mut qualifier: Option<Qualifier> = None;
    for arg_type in arg_types {
        let arg_type = (*arg_type)?;
        qualifier = Some(match qualifier {
            Some(current) => strongest_qualifier(current, arg_type.qualifier),
            None => arg_type.qualifier,
        });
    }
    qualifier.map(|qualifier| PineType::new(qualifier, kind))
}
pub(crate) fn round_return_type(arg_types: &[Option<PineType>]) -> Option<PineType> {
    let number_type = arg_types.first().copied().flatten()?;
    if arg_types.len() > 1 {
        promoted_kind_type(arg_types, ValueKind::Float)
    } else {
        Some(PineType::new(number_type.qualifier, ValueKind::Int))
    }
}
pub(crate) fn array_element_return_type(
    arg_types: &[Option<PineType>],
    index: usize,
) -> Option<PineType> {
    let array_type = arg_types.get(index).copied().flatten()?;
    let kind = array_type.kind.array_element_kind()?;
    Some(PineType::new(Qualifier::Series, kind))
}
pub(crate) fn array_numeric_return_type(
    arg_types: &[Option<PineType>],
    index: usize,
) -> Option<PineType> {
    let array_type = arg_types.get(index).copied().flatten()?;
    let kind = match array_type.kind.array_element_kind()? {
        ValueKind::Float => ValueKind::Float,
        ValueKind::Int => ValueKind::Int,
        _ => return None,
    };
    Some(PineType::new(Qualifier::Series, kind))
}
pub(crate) fn array_from_return_type(arg_types: &[Option<PineType>]) -> Option<PineType> {
    let mut inferred_element_kind: Option<ValueKind> = None;
    for arg_type in arg_types {
        let arg_type = (*arg_type)?;
        let next_element_kind = match arg_type.kind {
            ValueKind::Na => continue,
            kind if kind.array_kind_from_element_kind().is_some() => kind,
            _ => return None,
        };
        inferred_element_kind = Some(match (inferred_element_kind, next_element_kind) {
            (None, kind) => kind,
            (Some(ValueKind::Int), ValueKind::Float)
            | (Some(ValueKind::Float), ValueKind::Int)
            | (Some(ValueKind::Float), ValueKind::Float)
            | (Some(ValueKind::Int), ValueKind::Int) => {
                if matches!(next_element_kind, ValueKind::Float)
                    || matches!(inferred_element_kind, Some(ValueKind::Float))
                {
                    ValueKind::Float
                } else {
                    ValueKind::Int
                }
            }
            (Some(current), kind) if current == kind => current,
            _ => return None,
        });
    }
    let array_kind = inferred_element_kind?.array_kind_from_element_kind()?;
    Some(PineType::new(Qualifier::Simple, array_kind))
}

pub(crate) fn array_kind_from_element_type_name(element_type: &str) -> Option<ValueKind> {
    let element_kind = match element_type {
        "int" => ValueKind::Int,
        "float" => ValueKind::Float,
        "bool" => ValueKind::Bool,
        "string" => ValueKind::String,
        "color" => ValueKind::Color,
        "label" => ValueKind::Label,
        "line" => ValueKind::Line,
        "linefill" => ValueKind::LineFill,
        "polyline" => ValueKind::Polyline,
        "box" => ValueKind::Box,
        "table" => ValueKind::Table,
        "chart.point" => ValueKind::ChartPoint,
        _ => return None,
    };
    element_kind.array_kind_from_element_kind()
}

pub(crate) fn is_array_kind(kind: ValueKind) -> bool {
    kind.array_element_kind().is_some()
}
pub(crate) fn is_collection_kind(kind: ValueKind) -> bool {
    is_array_kind(kind) || is_matrix_kind(kind) || kind == ValueKind::Map
}
pub(crate) fn is_numeric_array_kind(kind: ValueKind) -> bool {
    matches!(
        kind.array_element_kind(),
        Some(ValueKind::Float | ValueKind::Int)
    )
}

pub(crate) fn is_scalar_array_kind(kind: ValueKind) -> bool {
    matches!(
        kind.array_element_kind(),
        Some(
            ValueKind::Float
                | ValueKind::Int
                | ValueKind::Bool
                | ValueKind::String
                | ValueKind::Color
        )
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn pine_type(qualifier: Qualifier, kind: ValueKind) -> PineType {
        PineType::new(qualifier, kind)
    }

    #[test]
    fn at_most_input_numeric_accepts_only_const_or_input_numbers() {
        assert!(accepts_type(
            Accepts::AtMostInputNumeric,
            pine_type(Qualifier::Const, ValueKind::Int)
        ));
        assert!(accepts_type(
            Accepts::AtMostInputNumeric,
            pine_type(Qualifier::Input, ValueKind::Float)
        ));
        assert!(!accepts_type(
            Accepts::AtMostInputNumeric,
            pine_type(Qualifier::Simple, ValueKind::Float)
        ));
        assert!(!accepts_type(
            Accepts::AtMostInputNumeric,
            pine_type(Qualifier::Series, ValueKind::Float)
        ));
        assert!(!accepts_type(
            Accepts::AtMostInputNumeric,
            pine_type(Qualifier::Input, ValueKind::String)
        ));
    }

    #[test]
    fn at_most_input_scalar_acceptors_accept_only_const_or_input_matching_kinds() {
        for (accepts, kind, wrong_kind) in [
            (Accepts::AtMostInputInt, ValueKind::Int, ValueKind::Float),
            (
                Accepts::AtMostInputString,
                ValueKind::String,
                ValueKind::Bool,
            ),
            (Accepts::AtMostInputBool, ValueKind::Bool, ValueKind::String),
            (Accepts::AtMostInputColor, ValueKind::Color, ValueKind::Int),
        ] {
            assert!(accepts_type(accepts, pine_type(Qualifier::Const, kind)));
            assert!(accepts_type(accepts, pine_type(Qualifier::Input, kind)));
            assert!(!accepts_type(accepts, pine_type(Qualifier::Simple, kind)));
            assert!(!accepts_type(accepts, pine_type(Qualifier::Series, kind)));
            assert!(!accepts_type(
                accepts,
                pine_type(Qualifier::Input, wrong_kind)
            ));
            assert!(!accepts_type(
                accepts,
                pine_type(Qualifier::Input, ValueKind::Na)
            ));
        }
    }

    #[test]
    fn series_acceptors_require_exact_series_qualifier() {
        assert!(accepts_type(
            Accepts::SeriesFloat,
            pine_type(Qualifier::Series, ValueKind::Float)
        ));
        assert!(accepts_type(
            Accepts::SeriesNumeric,
            pine_type(Qualifier::Series, ValueKind::Int)
        ));
        assert!(accepts_type(
            Accepts::SeriesNumericOrBool,
            pine_type(Qualifier::Series, ValueKind::Bool)
        ));

        for qualifier in [Qualifier::Const, Qualifier::Input, Qualifier::Simple] {
            assert!(!accepts_type(
                Accepts::SeriesFloat,
                pine_type(qualifier, ValueKind::Float)
            ));
            assert!(!accepts_type(
                Accepts::SeriesNumeric,
                pine_type(qualifier, ValueKind::Int)
            ));
            assert!(!accepts_type(
                Accepts::SeriesNumericOrBool,
                pine_type(qualifier, ValueKind::Bool)
            ));
        }

        assert!(!accepts_type(
            Accepts::SeriesNumeric,
            pine_type(Qualifier::Series, ValueKind::Bool)
        ));
        assert!(!accepts_type(
            Accepts::SeriesNumericOrBool,
            pine_type(Qualifier::Series, ValueKind::String)
        ));
    }

    #[test]
    fn const_acceptors_require_exact_const_qualifier() {
        assert!(accepts_type(
            Accepts::ConstNumeric,
            pine_type(Qualifier::Const, ValueKind::Float)
        ));
        assert!(accepts_type(
            Accepts::ConstString,
            pine_type(Qualifier::Const, ValueKind::String)
        ));
        assert!(accepts_type(
            Accepts::ConstBool,
            pine_type(Qualifier::Const, ValueKind::Bool)
        ));
        assert!(accepts_type(
            Accepts::InputDefval,
            pine_type(Qualifier::Const, ValueKind::Color)
        ));

        for qualifier in [Qualifier::Input, Qualifier::Simple, Qualifier::Series] {
            assert!(!accepts_type(
                Accepts::ConstNumeric,
                pine_type(qualifier, ValueKind::Float)
            ));
            assert!(!accepts_type(
                Accepts::ConstString,
                pine_type(qualifier, ValueKind::String)
            ));
            assert!(!accepts_type(
                Accepts::ConstBool,
                pine_type(qualifier, ValueKind::Bool)
            ));
            assert!(!accepts_type(
                Accepts::InputDefval,
                pine_type(qualifier, ValueKind::Int)
            ));
        }

        assert!(!accepts_type(
            Accepts::ConstNumeric,
            pine_type(Qualifier::Const, ValueKind::String)
        ));
        assert!(!accepts_type(
            Accepts::InputDefval,
            pine_type(Qualifier::Const, ValueKind::Line)
        ));
    }

    #[test]
    fn simple_acceptors_accept_weaker_qualifiers_and_reject_series() {
        for qualifier in [Qualifier::Const, Qualifier::Input, Qualifier::Simple] {
            assert!(accepts_type(
                Accepts::SimpleInt,
                pine_type(qualifier, ValueKind::Int)
            ));
            assert!(accepts_type(
                Accepts::SimpleNumeric,
                pine_type(qualifier, ValueKind::Float)
            ));
            for kind in [ValueKind::Int, ValueKind::Float, ValueKind::Na] {
                assert!(accepts_type(
                    Accepts::SimpleNumericCompatible,
                    pine_type(qualifier, kind)
                ));
            }
            assert!(accepts_type(
                Accepts::SimpleBool,
                pine_type(qualifier, ValueKind::Bool)
            ));
            assert!(accepts_type(
                Accepts::SimpleString,
                pine_type(qualifier, ValueKind::String)
            ));
            assert!(accepts_type(
                Accepts::SimpleString,
                pine_type(qualifier, ValueKind::Na)
            ));
            for kind in [ValueKind::Bool, ValueKind::Na] {
                assert!(accepts_type(
                    Accepts::SimpleBoolCompatible,
                    pine_type(qualifier, kind)
                ));
            }
        }

        assert!(!accepts_type(
            Accepts::SimpleInt,
            pine_type(Qualifier::Series, ValueKind::Int)
        ));
        assert!(!accepts_type(
            Accepts::SimpleNumeric,
            pine_type(Qualifier::Series, ValueKind::Float)
        ));
        assert!(!accepts_type(
            Accepts::SimpleNumericCompatible,
            pine_type(Qualifier::Series, ValueKind::Float)
        ));
        assert!(!accepts_type(
            Accepts::SimpleNumericCompatible,
            pine_type(Qualifier::Series, ValueKind::Na)
        ));
        assert!(!accepts_type(
            Accepts::SimpleBool,
            pine_type(Qualifier::Series, ValueKind::Bool)
        ));
        assert!(!accepts_type(
            Accepts::SimpleString,
            pine_type(Qualifier::Series, ValueKind::String)
        ));
        assert!(!accepts_type(
            Accepts::SimpleString,
            pine_type(Qualifier::Series, ValueKind::Na)
        ));
        assert!(!accepts_type(
            Accepts::SimpleBoolCompatible,
            pine_type(Qualifier::Series, ValueKind::Bool)
        ));
        assert!(!accepts_type(
            Accepts::SimpleBoolCompatible,
            pine_type(Qualifier::Simple, ValueKind::String)
        ));
    }

    #[test]
    fn simple_int_compatible_accepts_weaker_int_or_na_and_rejects_series() {
        for qualifier in [Qualifier::Const, Qualifier::Input, Qualifier::Simple] {
            assert!(accepts_type(
                Accepts::SimpleIntCompatible,
                pine_type(qualifier, ValueKind::Int)
            ));
            assert!(accepts_type(
                Accepts::SimpleIntCompatible,
                pine_type(qualifier, ValueKind::Na)
            ));
        }

        assert!(!accepts_type(
            Accepts::SimpleIntCompatible,
            pine_type(Qualifier::Series, ValueKind::Int)
        ));
        assert!(!accepts_type(
            Accepts::SimpleIntCompatible,
            pine_type(Qualifier::Series, ValueKind::Na)
        ));
        assert!(!accepts_type(
            Accepts::SimpleIntCompatible,
            pine_type(Qualifier::Input, ValueKind::Float)
        ));
    }

    #[test]
    fn compatible_acceptors_allow_series_values_and_na_for_matching_kinds() {
        assert!(accepts_type(
            Accepts::LabelCompatible,
            pine_type(Qualifier::Series, ValueKind::Label)
        ));
        assert!(accepts_type(
            Accepts::LabelCompatible,
            pine_type(Qualifier::Series, ValueKind::Na)
        ));
        assert!(accepts_type(
            Accepts::NumericCompatible,
            pine_type(Qualifier::Input, ValueKind::Float)
        ));
        assert!(!accepts_type(
            Accepts::LabelCompatible,
            pine_type(Qualifier::Series, ValueKind::Line)
        ));
        assert!(!accepts_type(
            Accepts::NumericCompatible,
            pine_type(Qualifier::Series, ValueKind::String)
        ));
    }

    #[test]
    fn series_or_simple_acceptors_accept_all_numeric_qualifiers() {
        for qualifier in [
            Qualifier::Const,
            Qualifier::Input,
            Qualifier::Simple,
            Qualifier::Series,
        ] {
            assert!(accepts_type(
                Accepts::SeriesOrSimpleNumeric,
                pine_type(qualifier, ValueKind::Int)
            ));
            assert!(accepts_type(
                Accepts::SeriesOrSimpleNumeric,
                pine_type(qualifier, ValueKind::Float)
            ));
            assert!(accepts_type(
                Accepts::SeriesOrSimpleNumericOrBool,
                pine_type(qualifier, ValueKind::Bool)
            ));
        }

        assert!(!accepts_type(
            Accepts::SeriesOrSimpleNumeric,
            pine_type(Qualifier::Series, ValueKind::Bool)
        ));
        assert!(!accepts_type(
            Accepts::SeriesOrSimpleNumericOrBool,
            pine_type(Qualifier::Series, ValueKind::String)
        ));
    }

    #[test]
    fn treats_user_type_array_as_array_but_not_numeric_or_scalar_array() {
        assert!(is_array_kind(ValueKind::UserTypeArray));
        assert!(!is_numeric_array_kind(ValueKind::UserTypeArray));
        assert!(!is_scalar_array_kind(ValueKind::UserTypeArray));
        let user_type_array = PineType::new(Qualifier::Simple, ValueKind::UserTypeArray);
        assert_eq!(
            array_element_return_type(&[Some(user_type_array)], 0),
            Some(PineType::new(Qualifier::Series, ValueKind::UserType))
        );
    }

    #[test]
    fn does_not_infer_user_type_array_from_user_type_values() {
        assert_eq!(
            array_from_return_type(&[Some(PineType::new(Qualifier::Series, ValueKind::UserType,))]),
            None
        );
    }
}
