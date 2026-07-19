use pine_ir::{PineType, Qualifier, ValueKind};

pub(crate) const INPUT_INT: PineType = PineType::new(Qualifier::Input, ValueKind::Int);
pub(crate) const INPUT_FLOAT: PineType = PineType::new(Qualifier::Input, ValueKind::Float);
pub(crate) const INPUT_BOOL: PineType = PineType::new(Qualifier::Input, ValueKind::Bool);
pub(crate) const INPUT_COLOR: PineType = PineType::new(Qualifier::Input, ValueKind::Color);
pub(crate) const INPUT_STRING: PineType = PineType::new(Qualifier::Input, ValueKind::String);
pub(crate) const SERIES_FLOAT: PineType = PineType::new(Qualifier::Series, ValueKind::Float);
pub(crate) const SERIES_INT: PineType = PineType::new(Qualifier::Series, ValueKind::Int);
pub(crate) const SERIES_BOOL: PineType = PineType::new(Qualifier::Series, ValueKind::Bool);
pub(crate) const SERIES_STRING: PineType = PineType::new(Qualifier::Series, ValueKind::String);
pub(crate) const SERIES_FLOAT_TUPLE: PineType = PineType::new(Qualifier::Series, ValueKind::Tuple);
pub(crate) const PLOT: PineType = PineType::new(Qualifier::Const, ValueKind::Plot);
pub(crate) const HLINE: PineType = PineType::new(Qualifier::Const, ValueKind::HLine);
pub(crate) const SERIES_LABEL: PineType = PineType::new(Qualifier::Series, ValueKind::Label);
pub(crate) const SERIES_LINE: PineType = PineType::new(Qualifier::Series, ValueKind::Line);
pub(crate) const SERIES_LINE_FILL: PineType = PineType::new(Qualifier::Series, ValueKind::LineFill);
pub(crate) const SERIES_POLYLINE: PineType = PineType::new(Qualifier::Series, ValueKind::Polyline);
pub(crate) const SERIES_BOX: PineType = PineType::new(Qualifier::Series, ValueKind::Box);
pub(crate) const SERIES_TABLE: PineType = PineType::new(Qualifier::Series, ValueKind::Table);
pub(crate) const SERIES_CHART_POINT: PineType =
    PineType::new(Qualifier::Series, ValueKind::ChartPoint);
pub(crate) const VOID: PineType = PineType::new(Qualifier::Const, ValueKind::Void);
pub(crate) const SIMPLE_INT: PineType = PineType::new(Qualifier::Simple, ValueKind::Int);
pub(crate) const SIMPLE_FLOAT: PineType = PineType::new(Qualifier::Simple, ValueKind::Float);
pub(crate) const SIMPLE_BOOL: PineType = PineType::new(Qualifier::Simple, ValueKind::Bool);
pub(crate) const SIMPLE_COLOR: PineType = PineType::new(Qualifier::Simple, ValueKind::Color);
pub(crate) const SIMPLE_STRING: PineType = PineType::new(Qualifier::Simple, ValueKind::String);
pub(crate) const SIMPLE_FLOAT_MATRIX: PineType =
    PineType::new(Qualifier::Simple, ValueKind::FloatMatrix);
pub(crate) const SIMPLE_INT_MATRIX: PineType =
    PineType::new(Qualifier::Simple, ValueKind::IntMatrix);
pub(crate) const SIMPLE_BOOL_MATRIX: PineType =
    PineType::new(Qualifier::Simple, ValueKind::BoolMatrix);
pub(crate) const SIMPLE_STRING_MATRIX: PineType =
    PineType::new(Qualifier::Simple, ValueKind::StringMatrix);
pub(crate) const SIMPLE_COLOR_MATRIX: PineType =
    PineType::new(Qualifier::Simple, ValueKind::ColorMatrix);

const fn simple_array_type_from_element_kind(element_kind: ValueKind) -> PineType {
    match element_kind.array_kind_from_element_kind() {
        Some(array_kind) => PineType::new(Qualifier::Simple, array_kind),
        None => panic!("unsupported array element kind"),
    }
}

pub(crate) const SIMPLE_FLOAT_ARRAY: PineType =
    simple_array_type_from_element_kind(ValueKind::Float);
pub(crate) const SIMPLE_INT_ARRAY: PineType = simple_array_type_from_element_kind(ValueKind::Int);
pub(crate) const SIMPLE_BOOL_ARRAY: PineType = simple_array_type_from_element_kind(ValueKind::Bool);
pub(crate) const SIMPLE_STRING_ARRAY: PineType =
    simple_array_type_from_element_kind(ValueKind::String);
pub(crate) const SIMPLE_COLOR_ARRAY: PineType =
    simple_array_type_from_element_kind(ValueKind::Color);
pub(crate) const SIMPLE_LABEL_ARRAY: PineType =
    simple_array_type_from_element_kind(ValueKind::Label);
pub(crate) const SIMPLE_LINE_ARRAY: PineType = simple_array_type_from_element_kind(ValueKind::Line);
pub(crate) const SIMPLE_LINE_FILL_ARRAY: PineType =
    simple_array_type_from_element_kind(ValueKind::LineFill);
pub(crate) const SIMPLE_POLYLINE_ARRAY: PineType =
    simple_array_type_from_element_kind(ValueKind::Polyline);
pub(crate) const SIMPLE_BOX_ARRAY: PineType = simple_array_type_from_element_kind(ValueKind::Box);
pub(crate) const SIMPLE_TABLE_ARRAY: PineType =
    simple_array_type_from_element_kind(ValueKind::Table);
pub(crate) const SIMPLE_CHART_POINT_ARRAY: PineType =
    simple_array_type_from_element_kind(ValueKind::ChartPoint);
