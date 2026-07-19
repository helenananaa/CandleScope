use pine_ir::{PineType, Qualifier, ValueKind};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct BuiltinSignature {
    pub name: &'static str,
    pub phase: BuiltinPhase,
    pub params: &'static [BuiltinParam],
    pub returns: ReturnSpec,
    pub variadic: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BuiltinPhase {
    Phase1Core,
    Later,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct BuiltinParam {
    pub name: &'static str,
    pub accepts: Accepts,
    pub optional: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum QualifierRelation {
    Exact,
    AtMost,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ScalarKind {
    Int,
    Numeric,
    Bool,
    String,
    Color,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct QualifierBoundScalar {
    relation: QualifierRelation,
    qualifier: Qualifier,
    kind: ScalarKind,
    compatible: bool,
}

impl QualifierBoundScalar {
    #[must_use]
    pub const fn exact(qualifier: Qualifier, kind: ScalarKind, compatible: bool) -> Self {
        Self {
            relation: QualifierRelation::Exact,
            qualifier,
            kind,
            compatible,
        }
    }

    #[must_use]
    pub const fn at_most(qualifier: Qualifier, kind: ScalarKind, compatible: bool) -> Self {
        Self {
            relation: QualifierRelation::AtMost,
            qualifier,
            kind,
            compatible,
        }
    }

    #[must_use]
    pub const fn accepts(self, actual: PineType) -> bool {
        let qualifier_matches = match self.relation {
            QualifierRelation::Exact => {
                qualifier_rank(actual.qualifier) == qualifier_rank(self.qualifier)
            }
            QualifierRelation::AtMost => {
                qualifier_rank(actual.qualifier) <= qualifier_rank(self.qualifier)
            }
        };
        qualifier_matches
            && ((self.compatible && matches!(actual.kind, ValueKind::Na))
                || scalar_kind_matches(self.kind, actual.kind))
    }

    #[must_use]
    pub fn expected_label(self) -> String {
        let qualifier = match (self.relation, self.qualifier) {
            (QualifierRelation::Exact, Qualifier::Const)
            | (QualifierRelation::AtMost, Qualifier::Const) => "const",
            (QualifierRelation::Exact, Qualifier::Input) => "input",
            (QualifierRelation::AtMost, Qualifier::Input) => "const/input",
            (QualifierRelation::Exact, Qualifier::Simple)
            | (QualifierRelation::AtMost, Qualifier::Simple) => "simple",
            (QualifierRelation::Exact, Qualifier::Series) => "series",
            (QualifierRelation::AtMost, Qualifier::Series) => "series/simple",
        };
        let kind = match (self.kind, self.compatible) {
            (ScalarKind::Int, false) => "int",
            (ScalarKind::Int, true) => "integer-compatible",
            (ScalarKind::Numeric, false) => "numeric",
            (ScalarKind::Numeric, true) => "numeric-compatible",
            (ScalarKind::Bool, false) => "bool",
            (ScalarKind::Bool, true) => "bool-compatible",
            // `SimpleString` has always accepted `na` while reporting the
            // established `simple string` diagnostic label.
            (ScalarKind::String, true)
                if self.relation == QualifierRelation::AtMost
                    && self.qualifier == Qualifier::Simple =>
            {
                "string"
            }
            (ScalarKind::String, false) => "string",
            (ScalarKind::String, true) => "string-compatible",
            (ScalarKind::Color, false) => "color",
            (ScalarKind::Color, true) => "color-compatible",
        };
        format!("{qualifier} {kind}")
    }
}

const fn qualifier_rank(qualifier: Qualifier) -> u8 {
    match qualifier {
        Qualifier::Const => 0,
        Qualifier::Input => 1,
        Qualifier::Simple => 2,
        Qualifier::Series => 3,
    }
}

const fn scalar_kind_matches(expected: ScalarKind, actual: ValueKind) -> bool {
    match expected {
        ScalarKind::Int => matches!(actual, ValueKind::Int),
        ScalarKind::Numeric => matches!(actual, ValueKind::Int | ValueKind::Float),
        ScalarKind::Bool => matches!(actual, ValueKind::Bool),
        ScalarKind::String => matches!(actual, ValueKind::String),
        ScalarKind::Color => matches!(actual, ValueKind::Color),
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Accepts {
    Any,
    Exact(PineType),
    Kind(ValueKind),
    Numeric,
    SeriesFloat,
    SeriesNumeric,
    SeriesNumericOrBool,
    SeriesOrSimpleNumeric,
    SeriesOrSimpleNumericOrBool,
    QualifierBoundScalar(QualifierBoundScalar),
    ColorCompatible,
    StringCompatible,
    StringConvertible,
    FormatConvertible,
    StringOrIntCompatible,
    CastScalar,
    StringCastScalar,
    ValueWhenSource,
    NumericOrColorCompatible,
    NumericCompatible,
    IntCompatible,
    BoolCompatible,
    LabelCompatible,
    LineCompatible,
    LineFillCompatible,
    PolylineCompatible,
    BoxCompatible,
    TableCompatible,
    ChartPointCompatible,
    PlotOrHLine,
    Array,
    FloatMatrix,
    NumericMatrix,
    Matrix,
    Map,
    MatrixOrNumericCompatibleWithMatrixCounterpart(usize),
    MatrixOrNumericOrNumericArrayCompatibleWithMatrixCounterpart(usize),
    MatrixElementCompatible(usize),
    MatrixElementArray(usize),
    Tuple,
    ScalarArray,
    NumericArray,
    NumericOrBoolArray,
    NumericOrStringArray,
    InputDefval,
}

#[allow(non_upper_case_globals)]
impl Accepts {
    pub const SimpleInt: Self = Self::QualifierBoundScalar(QualifierBoundScalar::at_most(
        Qualifier::Simple,
        ScalarKind::Int,
        false,
    ));
    pub const SimpleIntCompatible: Self = Self::QualifierBoundScalar(
        QualifierBoundScalar::at_most(Qualifier::Simple, ScalarKind::Int, true),
    );
    pub const SimpleString: Self = Self::QualifierBoundScalar(QualifierBoundScalar::at_most(
        Qualifier::Simple,
        ScalarKind::String,
        true,
    ));
    pub const SimpleNumeric: Self = Self::QualifierBoundScalar(QualifierBoundScalar::at_most(
        Qualifier::Simple,
        ScalarKind::Numeric,
        false,
    ));
    pub const SimpleNumericCompatible: Self = Self::QualifierBoundScalar(
        QualifierBoundScalar::at_most(Qualifier::Simple, ScalarKind::Numeric, true),
    );
    pub const SimpleBool: Self = Self::QualifierBoundScalar(QualifierBoundScalar::at_most(
        Qualifier::Simple,
        ScalarKind::Bool,
        false,
    ));
    pub const SimpleBoolCompatible: Self = Self::QualifierBoundScalar(
        QualifierBoundScalar::at_most(Qualifier::Simple, ScalarKind::Bool, true),
    );
    pub const ConstNumeric: Self = Self::QualifierBoundScalar(QualifierBoundScalar::exact(
        Qualifier::Const,
        ScalarKind::Numeric,
        false,
    ));
    pub const ConstString: Self = Self::QualifierBoundScalar(QualifierBoundScalar::exact(
        Qualifier::Const,
        ScalarKind::String,
        false,
    ));
    pub const ConstBool: Self = Self::QualifierBoundScalar(QualifierBoundScalar::exact(
        Qualifier::Const,
        ScalarKind::Bool,
        false,
    ));
    pub const AtMostInputNumeric: Self = Self::QualifierBoundScalar(QualifierBoundScalar::at_most(
        Qualifier::Input,
        ScalarKind::Numeric,
        false,
    ));
    pub const AtMostInputInt: Self = Self::QualifierBoundScalar(QualifierBoundScalar::at_most(
        Qualifier::Input,
        ScalarKind::Int,
        false,
    ));
    pub const AtMostInputString: Self = Self::QualifierBoundScalar(QualifierBoundScalar::at_most(
        Qualifier::Input,
        ScalarKind::String,
        false,
    ));
    pub const AtMostInputBool: Self = Self::QualifierBoundScalar(QualifierBoundScalar::at_most(
        Qualifier::Input,
        ScalarKind::Bool,
        false,
    ));
    pub const AtMostInputColor: Self = Self::QualifierBoundScalar(QualifierBoundScalar::at_most(
        Qualifier::Input,
        ScalarKind::Color,
        false,
    ));
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ReturnSpec {
    Fixed(PineType),
    Tuple(&'static [PineType]),
    SameAsArg(usize),
    BoolFromArg(usize),
    ColorFromArg(usize),
    PromotedColor,
    PromotedBool,
    PromotedInt,
    PromotedString,
    FloatFromStringArg(usize),
    PromotedNumeric,
    ArrayElement(usize),
    ArrayNumeric(usize),
    ArrayFromArgs,
    MatrixElement(usize),
    MatrixArray(usize),
    MatrixMult,
    IntFromArg(usize),
    FloatFromArg(usize),
    SeriesFromArg(usize),
    ChangeFromArg(usize),
    PromotedFloat,
    Round,
    InputFromArg(usize),
}

#[cfg(test)]
mod tests {
    use super::*;

    fn pine_type(qualifier: Qualifier, kind: ValueKind) -> PineType {
        PineType::new(qualifier, kind)
    }

    #[test]
    fn qualifier_bound_scalar_distinguishes_exact_from_at_most() {
        let exact = QualifierBoundScalar::exact(Qualifier::Input, ScalarKind::Numeric, false);
        let at_most = QualifierBoundScalar::at_most(Qualifier::Input, ScalarKind::Numeric, false);

        assert!(exact.accepts(pine_type(Qualifier::Input, ValueKind::Int)));
        assert!(!exact.accepts(pine_type(Qualifier::Const, ValueKind::Int)));
        assert!(at_most.accepts(pine_type(Qualifier::Const, ValueKind::Float)));
        assert!(at_most.accepts(pine_type(Qualifier::Input, ValueKind::Int)));
        assert!(!at_most.accepts(pine_type(Qualifier::Simple, ValueKind::Int)));
        assert!(!at_most.accepts(pine_type(Qualifier::Input, ValueKind::Na)));
        assert!(!at_most.accepts(pine_type(Qualifier::Input, ValueKind::String)));
    }

    #[test]
    fn qualifier_bound_scalar_compatibility_allows_na_only_within_qualifier_bound() {
        let compatible = QualifierBoundScalar::at_most(Qualifier::Simple, ScalarKind::Bool, true);

        assert!(compatible.accepts(pine_type(Qualifier::Const, ValueKind::Bool)));
        assert!(compatible.accepts(pine_type(Qualifier::Simple, ValueKind::Na)));
        assert!(!compatible.accepts(pine_type(Qualifier::Simple, ValueKind::String)));
        assert!(!compatible.accepts(pine_type(Qualifier::Series, ValueKind::Bool)));
        assert!(!compatible.accepts(pine_type(Qualifier::Series, ValueKind::Na)));
    }

    #[test]
    fn legacy_scalar_acceptor_constants_keep_models_and_labels() {
        for (accepts, expected_bound, expected_label) in [
            (
                Accepts::SimpleInt,
                QualifierBoundScalar::at_most(Qualifier::Simple, ScalarKind::Int, false),
                "simple int",
            ),
            (
                Accepts::SimpleIntCompatible,
                QualifierBoundScalar::at_most(Qualifier::Simple, ScalarKind::Int, true),
                "simple integer-compatible",
            ),
            (
                Accepts::SimpleString,
                QualifierBoundScalar::at_most(Qualifier::Simple, ScalarKind::String, true),
                "simple string",
            ),
            (
                Accepts::SimpleNumeric,
                QualifierBoundScalar::at_most(Qualifier::Simple, ScalarKind::Numeric, false),
                "simple numeric",
            ),
            (
                Accepts::SimpleNumericCompatible,
                QualifierBoundScalar::at_most(Qualifier::Simple, ScalarKind::Numeric, true),
                "simple numeric-compatible",
            ),
            (
                Accepts::SimpleBool,
                QualifierBoundScalar::at_most(Qualifier::Simple, ScalarKind::Bool, false),
                "simple bool",
            ),
            (
                Accepts::SimpleBoolCompatible,
                QualifierBoundScalar::at_most(Qualifier::Simple, ScalarKind::Bool, true),
                "simple bool-compatible",
            ),
            (
                Accepts::ConstNumeric,
                QualifierBoundScalar::exact(Qualifier::Const, ScalarKind::Numeric, false),
                "const numeric",
            ),
            (
                Accepts::ConstString,
                QualifierBoundScalar::exact(Qualifier::Const, ScalarKind::String, false),
                "const string",
            ),
            (
                Accepts::ConstBool,
                QualifierBoundScalar::exact(Qualifier::Const, ScalarKind::Bool, false),
                "const bool",
            ),
            (
                Accepts::AtMostInputNumeric,
                QualifierBoundScalar::at_most(Qualifier::Input, ScalarKind::Numeric, false),
                "const/input numeric",
            ),
            (
                Accepts::AtMostInputInt,
                QualifierBoundScalar::at_most(Qualifier::Input, ScalarKind::Int, false),
                "const/input int",
            ),
            (
                Accepts::AtMostInputString,
                QualifierBoundScalar::at_most(Qualifier::Input, ScalarKind::String, false),
                "const/input string",
            ),
            (
                Accepts::AtMostInputBool,
                QualifierBoundScalar::at_most(Qualifier::Input, ScalarKind::Bool, false),
                "const/input bool",
            ),
            (
                Accepts::AtMostInputColor,
                QualifierBoundScalar::at_most(Qualifier::Input, ScalarKind::Color, false),
                "const/input color",
            ),
        ] {
            let Accepts::QualifierBoundScalar(actual_bound) = accepts else {
                panic!("legacy scalar acceptor must use the generic model");
            };
            assert_eq!(actual_bound, expected_bound);
            assert_eq!(actual_bound.expected_label(), expected_label);
        }
    }
}
