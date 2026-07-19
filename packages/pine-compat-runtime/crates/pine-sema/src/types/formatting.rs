use pine_ir::{PineType, Qualifier, ValueKind};

pub(crate) fn pine_type_name(pine_type: PineType) -> String {
    format!(
        "{} {}",
        qualifier_name(pine_type.qualifier),
        value_kind_name(pine_type.kind)
    )
}

fn qualifier_name(qualifier: Qualifier) -> &'static str {
    match qualifier {
        Qualifier::Const => "const",
        Qualifier::Input => "input",
        Qualifier::Simple => "simple",
        Qualifier::Series => "series",
    }
}

pub(crate) fn value_kind_name(kind: ValueKind) -> &'static str {
    match kind {
        ValueKind::Int => "int",
        ValueKind::Float => "float",
        ValueKind::Bool => "bool",
        ValueKind::String => "string",
        ValueKind::Color => "color",
        ValueKind::Plot => "plot",
        ValueKind::HLine => "hline",
        ValueKind::Label => "label",
        ValueKind::Line => "line",
        ValueKind::LineFill => "linefill",
        ValueKind::Polyline => "polyline",
        ValueKind::Box => "box",
        ValueKind::Table => "table",
        ValueKind::ChartPoint => "chart.point",
        ValueKind::FloatArray => "array<float>",
        ValueKind::IntArray => "array<int>",
        ValueKind::BoolArray => "array<bool>",
        ValueKind::StringArray => "array<string>",
        ValueKind::ColorArray => "array<color>",
        ValueKind::LabelArray => "array<label>",
        ValueKind::LineArray => "array<line>",
        ValueKind::LineFillArray => "array<linefill>",
        ValueKind::PolylineArray => "array<polyline>",
        ValueKind::BoxArray => "array<box>",
        ValueKind::TableArray => "array<table>",
        ValueKind::ChartPointArray => "array<chart.point>",
        ValueKind::UserTypeArray => "array<UDT>",
        ValueKind::FloatMatrix => "matrix<float>",
        ValueKind::IntMatrix => "matrix<int>",
        ValueKind::BoolMatrix => "matrix<bool>",
        ValueKind::StringMatrix => "matrix<string>",
        ValueKind::ColorMatrix => "matrix<color>",
        ValueKind::Map => "map",
        ValueKind::UserType => "UDT",
        ValueKind::Tuple => "tuple",
        ValueKind::Na => "na",
        ValueKind::Void => "void",
    }
}
