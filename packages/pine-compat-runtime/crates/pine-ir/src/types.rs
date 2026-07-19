#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Qualifier {
    Const,
    Input,
    Simple,
    Series,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ValueKind {
    Int,
    Float,
    Bool,
    String,
    Color,
    Plot,
    HLine,
    Label,
    Line,
    LineFill,
    Polyline,
    Box,
    Table,
    ChartPoint,
    FloatArray,
    IntArray,
    BoolArray,
    StringArray,
    ColorArray,
    LabelArray,
    LineArray,
    LineFillArray,
    PolylineArray,
    BoxArray,
    TableArray,
    ChartPointArray,
    UserTypeArray,
    FloatMatrix,
    IntMatrix,
    BoolMatrix,
    StringMatrix,
    ColorMatrix,
    Map,
    UserType,
    Tuple,
    Na,
    Void,
}

impl ValueKind {
    #[must_use]
    pub const fn array_kind_from_element_kind(self) -> Option<Self> {
        match self {
            Self::Int => Some(Self::IntArray),
            Self::Float => Some(Self::FloatArray),
            Self::Bool => Some(Self::BoolArray),
            Self::String => Some(Self::StringArray),
            Self::Color => Some(Self::ColorArray),
            Self::Label => Some(Self::LabelArray),
            Self::Line => Some(Self::LineArray),
            Self::LineFill => Some(Self::LineFillArray),
            Self::Polyline => Some(Self::PolylineArray),
            Self::Box => Some(Self::BoxArray),
            Self::Table => Some(Self::TableArray),
            Self::ChartPoint => Some(Self::ChartPointArray),
            _ => None,
        }
    }

    #[must_use]
    pub const fn array_element_kind(self) -> Option<Self> {
        match self {
            Self::IntArray => Some(Self::Int),
            Self::FloatArray => Some(Self::Float),
            Self::BoolArray => Some(Self::Bool),
            Self::StringArray => Some(Self::String),
            Self::ColorArray => Some(Self::Color),
            Self::LabelArray => Some(Self::Label),
            Self::LineArray => Some(Self::Line),
            Self::LineFillArray => Some(Self::LineFill),
            Self::PolylineArray => Some(Self::Polyline),
            Self::BoxArray => Some(Self::Box),
            Self::TableArray => Some(Self::Table),
            Self::ChartPointArray => Some(Self::ChartPoint),
            Self::UserTypeArray => Some(Self::UserType),
            _ => None,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PineType {
    pub qualifier: Qualifier,
    pub kind: ValueKind,
}

impl PineType {
    #[must_use]
    pub const fn new(qualifier: Qualifier, kind: ValueKind) -> Self {
        Self { qualifier, kind }
    }
}

#[cfg(test)]
mod tests {
    use super::ValueKind;

    #[test]
    fn maps_supported_array_element_kinds() {
        let cases = [
            (ValueKind::Int, ValueKind::IntArray),
            (ValueKind::Float, ValueKind::FloatArray),
            (ValueKind::Bool, ValueKind::BoolArray),
            (ValueKind::String, ValueKind::StringArray),
            (ValueKind::Color, ValueKind::ColorArray),
            (ValueKind::Label, ValueKind::LabelArray),
            (ValueKind::Line, ValueKind::LineArray),
            (ValueKind::LineFill, ValueKind::LineFillArray),
            (ValueKind::Polyline, ValueKind::PolylineArray),
            (ValueKind::Box, ValueKind::BoxArray),
            (ValueKind::Table, ValueKind::TableArray),
            (ValueKind::ChartPoint, ValueKind::ChartPointArray),
        ];

        for (element_kind, array_kind) in cases {
            assert_eq!(
                element_kind.array_kind_from_element_kind(),
                Some(array_kind)
            );
            assert_eq!(array_kind.array_element_kind(), Some(element_kind));
        }
    }

    #[test]
    fn rejects_non_array_element_kinds() {
        for kind in [
            ValueKind::IntArray,
            ValueKind::FloatArray,
            ValueKind::UserType,
            ValueKind::Tuple,
            ValueKind::Na,
            ValueKind::Void,
        ] {
            assert_eq!(kind.array_kind_from_element_kind(), None);
        }
    }

    #[test]
    fn rejects_non_array_kinds_for_element_lookup() {
        for kind in [
            ValueKind::Int,
            ValueKind::Float,
            ValueKind::UserType,
            ValueKind::Tuple,
            ValueKind::Na,
            ValueKind::Void,
        ] {
            assert_eq!(kind.array_element_kind(), None);
        }
    }

    #[test]
    fn exposes_internal_user_type_array_element_kind_without_inference() {
        assert_eq!(ValueKind::UserType.array_kind_from_element_kind(), None,);
        assert_eq!(
            ValueKind::UserTypeArray.array_element_kind(),
            Some(ValueKind::UserType),
        );
    }
}
