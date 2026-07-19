#[cfg(test)]
mod tests {
    use super::*;
    use pine_builtins::{QualifierBoundScalar, ScalarKind};

    fn pine_type(qualifier: Qualifier, kind: ValueKind) -> PineType {
        PineType::new(qualifier, kind)
    }

    #[test]
    fn matrix_call_result_helpers_are_a_closed_registered_set() {
        for (method_name, builtin_name) in [
            ("rows", "matrix.rows"),
            ("columns", "matrix.columns"),
            ("elements_count", "matrix.elements_count"),
            ("get", "matrix.get"),
            ("set", "matrix.set"),
            ("fill", "matrix.fill"),
            ("reverse", "matrix.reverse"),
            ("reshape", "matrix.reshape"),
            ("add_row", "matrix.add_row"),
            ("add_col", "matrix.add_col"),
            ("sort", "matrix.sort"),
            ("swap_rows", "matrix.swap_rows"),
            ("swap_columns", "matrix.swap_columns"),
            ("remove_row", "matrix.remove_row"),
            ("remove_col", "matrix.remove_col"),
            ("copy", "matrix.copy"),
            ("diff", "matrix.diff"),
            ("eigenvectors", "matrix.eigenvectors"),
            ("inv", "matrix.inv"),
            ("kron", "matrix.kron"),
            ("mult", "matrix.mult"),
            ("pinv", "matrix.pinv"),
            ("pow", "matrix.pow"),
            ("submatrix", "matrix.submatrix"),
            ("transpose", "matrix.transpose"),
            ("row", "matrix.row"),
            ("col", "matrix.col"),
            ("eigenvalues", "matrix.eigenvalues"),
            ("is_square", "matrix.is_square"),
            ("is_zero", "matrix.is_zero"),
            ("is_binary", "matrix.is_binary"),
            ("is_diagonal", "matrix.is_diagonal"),
            ("is_identity", "matrix.is_identity"),
            ("is_symmetric", "matrix.is_symmetric"),
            ("is_antisymmetric", "matrix.is_antisymmetric"),
            ("is_stochastic", "matrix.is_stochastic"),
            ("sum", "matrix.sum"),
            ("avg", "matrix.avg"),
            ("min", "matrix.min"),
            ("max", "matrix.max"),
            ("mode", "matrix.mode"),
            ("trace", "matrix.trace"),
            ("det", "matrix.det"),
            ("rank", "matrix.rank"),
        ] {
            assert_eq!(
                matrix_call_result_builtin_name(method_name),
                Some(builtin_name)
            );
            assert!(
                pine_builtins::get_phase_1_builtin(builtin_name).is_some(),
                "matrix call-result helper `{builtin_name}` must stay registered"
            );
        }

        assert_eq!(matrix_call_result_builtin_name("size"), None);
    }

    #[test]
    fn map_call_result_helpers_are_a_closed_set() {
        for (method_name, builtin_name) in [
            ("size", "map.size"),
            ("put", "map.put"),
            ("clear", "map.clear"),
            ("remove", "map.remove"),
            ("put_all", "map.put_all"),
            ("get", "map.get"),
            ("contains", "map.contains"),
            ("copy", "map.copy"),
            ("keys", "map.keys"),
            ("values", "map.values"),
        ] {
            assert_eq!(
                map_call_result_builtin_name(method_name),
                Some(builtin_name)
            );
        }

        assert_eq!(map_call_result_builtin_name("unknown"), None);
    }

    #[test]
    fn array_call_result_helpers_are_a_closed_registered_set() {
        for (method_name, builtin_name) in [
            ("size", "array.size"),
            ("get", "array.get"),
            ("first", "array.first"),
            ("last", "array.last"),
            ("copy", "array.copy"),
            ("includes", "array.includes"),
            ("every", "array.every"),
            ("some", "array.some"),
            ("indexof", "array.indexof"),
            ("lastindexof", "array.lastindexof"),
            ("binary_search", "array.binary_search"),
            ("binary_search_leftmost", "array.binary_search_leftmost"),
            ("binary_search_rightmost", "array.binary_search_rightmost"),
            ("abs", "array.abs"),
            ("min", "array.min"),
            ("max", "array.max"),
            ("sum", "array.sum"),
            ("avg", "array.avg"),
            ("range", "array.range"),
            ("median", "array.median"),
            ("mode", "array.mode"),
            (
                "percentile_nearest_rank",
                "array.percentile_nearest_rank",
            ),
            (
                "percentile_linear_interpolation",
                "array.percentile_linear_interpolation",
            ),
            ("percentrank", "array.percentrank"),
            ("covariance", "array.covariance"),
            ("standardize", "array.standardize"),
            ("variance", "array.variance"),
            ("stdev", "array.stdev"),
            ("sort_indices", "array.sort_indices"),
            ("join", "array.join"),
            ("slice", "array.slice"),
            ("concat", "array.concat"),
            ("clear", "array.clear"),
            ("reverse", "array.reverse"),
            ("pop", "array.pop"),
            ("shift", "array.shift"),
            ("remove", "array.remove"),
            ("push", "array.push"),
            ("unshift", "array.unshift"),
            ("insert", "array.insert"),
            ("set", "array.set"),
            ("fill", "array.fill"),
            ("sort", "array.sort"),
        ] {
            assert_eq!(
                array_call_result_builtin_name(method_name),
                Some(builtin_name)
            );
            assert!(pine_builtins::get_phase_1_builtin(builtin_name).is_some());
        }
    }

    #[test]
    fn generic_qualifier_bound_acceptor_drives_expected_label() {
        let accepts = Accepts::QualifierBoundScalar(QualifierBoundScalar::exact(
            Qualifier::Input,
            ScalarKind::Bool,
            true,
        ));
        let diagnostic = call_arg_accepts_type_expected_diagnostic(
            "future.input_bool",
            "value",
            accepts,
            pine_type(Qualifier::Const, ValueKind::Bool),
            Span::default(),
        )
        .expect("const bool should not satisfy exact input bool-compatible");

        assert_eq!(
            diagnostic.message,
            "`future.input_bool` argument `value` expects input bool-compatible, got const bool"
        );
    }

    #[test]
    fn acceptor_expected_diagnostic_uses_labels_for_selected_qualifier_bounds() {
        let diagnostic = call_arg_accepts_type_expected_diagnostic(
            "ta.sma",
            "length",
            Accepts::SimpleInt,
            pine_type(Qualifier::Series, ValueKind::Int),
            Span::default(),
        )
        .expect("series int should not satisfy simple int");
        assert_eq!(
            diagnostic.message,
            "`ta.sma` argument `length` expects simple int, got series int"
        );

        let diagnostic = call_arg_accepts_type_expected_diagnostic(
            "ta.pivothigh",
            "leftbars",
            Accepts::IntCompatible,
            pine_type(Qualifier::Const, ValueKind::Float),
            Span::default(),
        )
        .expect("const float should not satisfy integer-compatible");
        assert_eq!(
            diagnostic.message,
            "`ta.pivothigh` argument `leftbars` expects integer-compatible, got const float"
        );

        let diagnostic = call_arg_accepts_type_expected_diagnostic(
            "hline",
            "price",
            Accepts::AtMostInputNumeric,
            pine_type(Qualifier::Simple, ValueKind::Int),
            Span::default(),
        )
        .expect("simple int should not satisfy at-most-input numeric");
        assert_eq!(
            diagnostic.message,
            "`hline` argument `price` expects const/input numeric, got simple int"
        );

        let diagnostic = call_arg_accepts_type_expected_diagnostic(
            "hline",
            "linewidth",
            Accepts::AtMostInputInt,
            pine_type(Qualifier::Simple, ValueKind::Int),
            Span::default(),
        )
        .expect("simple int should not satisfy at-most-input int");
        assert_eq!(
            diagnostic.message,
            "`hline` argument `linewidth` expects const/input int, got simple int"
        );

        let diagnostic = call_arg_accepts_type_expected_diagnostic(
            "future.input_string",
            "value",
            Accepts::AtMostInputString,
            pine_type(Qualifier::Simple, ValueKind::String),
            Span::default(),
        )
        .expect("simple string should not satisfy at-most-input string");
        assert_eq!(
            diagnostic.message,
            "`future.input_string` argument `value` expects const/input string, got simple string"
        );

        let diagnostic = call_arg_accepts_type_expected_diagnostic(
            "future.input_bool",
            "value",
            Accepts::AtMostInputBool,
            pine_type(Qualifier::Series, ValueKind::Bool),
            Span::default(),
        )
        .expect("series bool should not satisfy at-most-input bool");
        assert_eq!(
            diagnostic.message,
            "`future.input_bool` argument `value` expects const/input bool, got series bool"
        );

        let diagnostic = call_arg_accepts_type_expected_diagnostic(
            "future.input_color",
            "value",
            Accepts::AtMostInputColor,
            pine_type(Qualifier::Simple, ValueKind::Color),
            Span::default(),
        )
        .expect("simple color should not satisfy at-most-input color");
        assert_eq!(
            diagnostic.message,
            "`future.input_color` argument `value` expects const/input color, got simple color"
        );

        let diagnostic = call_arg_accepts_type_expected_diagnostic(
            "time",
            "timeframe",
            Accepts::SimpleString,
            pine_type(Qualifier::Const, ValueKind::Int),
            Span::default(),
        )
        .expect("const int should not satisfy simple string");
        assert_eq!(
            diagnostic.message,
            "`time` argument `timeframe` expects simple string, got const int"
        );

        let diagnostic = call_arg_accepts_type_expected_diagnostic(
            "timestamp",
            "dateString",
            Accepts::ConstString,
            pine_type(Qualifier::Simple, ValueKind::String),
            Span::default(),
        )
        .expect("simple string should not satisfy const string");
        assert_eq!(
            diagnostic.message,
            "`timestamp` argument `dateString` expects const string, got simple string"
        );

        let diagnostic = call_arg_accepts_type_expected_diagnostic(
            "ta.stdev",
            "biased",
            Accepts::ConstBool,
            pine_type(Qualifier::Series, ValueKind::Bool),
            Span::default(),
        )
        .expect("series bool should not satisfy const bool");
        assert_eq!(
            diagnostic.message,
            "`ta.stdev` argument `biased` expects const bool, got series bool"
        );

        let diagnostic = call_arg_accepts_type_expected_diagnostic(
            "strategy",
            "initial_capital",
            Accepts::ConstNumeric,
            pine_type(Qualifier::Input, ValueKind::Float),
            Span::default(),
        )
        .expect("input float should not satisfy const numeric");
        assert_eq!(
            diagnostic.message,
            "`strategy` argument `initial_capital` expects const numeric, got input float"
        );

        let diagnostic = call_arg_accepts_type_expected_diagnostic(
            "ta.alma",
            "offset",
            Accepts::SimpleNumeric,
            pine_type(Qualifier::Series, ValueKind::Float),
            Span::default(),
        )
        .expect("series float should not satisfy simple numeric");
        assert_eq!(
            diagnostic.message,
            "`ta.alma` argument `offset` expects simple numeric, got series float"
        );

        let diagnostic = call_arg_accepts_type_expected_diagnostic(
            "ta.alma",
            "floor",
            Accepts::SimpleBool,
            pine_type(Qualifier::Series, ValueKind::Bool),
            Span::default(),
        )
        .expect("series bool should not satisfy simple bool");
        assert_eq!(
            diagnostic.message,
            "`ta.alma` argument `floor` expects simple bool, got series bool"
        );

        let diagnostic = call_arg_accepts_type_expected_diagnostic(
            "ta.sma",
            "source",
            Accepts::SeriesNumeric,
            pine_type(Qualifier::Const, ValueKind::Int),
            Span::default(),
        )
        .expect("const int should not satisfy series numeric");
        assert_eq!(
            diagnostic.message,
            "`ta.sma` argument `source` expects series numeric, got const int"
        );

        let diagnostic = call_arg_accepts_type_expected_diagnostic(
            "ta.valuewhen",
            "condition",
            Accepts::SeriesNumericOrBool,
            pine_type(Qualifier::Const, ValueKind::String),
            Span::default(),
        )
        .expect("const string should not satisfy series numeric or bool");
        assert_eq!(
            diagnostic.message,
            "`ta.valuewhen` argument `condition` expects series numeric or bool, got const string"
        );

        let diagnostic = call_arg_accepts_type_expected_diagnostic(
            "ta.cum",
            "source",
            Accepts::SeriesOrSimpleNumeric,
            pine_type(Qualifier::Const, ValueKind::Bool),
            Span::default(),
        )
        .expect("const bool should not satisfy series/simple numeric");
        assert_eq!(
            diagnostic.message,
            "`ta.cum` argument `source` expects series/simple numeric, got const bool"
        );

        let diagnostic = call_arg_accepts_type_expected_diagnostic(
            "plotshape",
            "series",
            Accepts::SeriesOrSimpleNumericOrBool,
            pine_type(Qualifier::Const, ValueKind::String),
            Span::default(),
        )
        .expect("const string should not satisfy series/simple numeric or bool");
        assert_eq!(
            diagnostic.message,
            "`plotshape` argument `series` expects series/simple numeric or bool, got const string"
        );

        let diagnostic = call_arg_accepts_type_expected_diagnostic(
            "ta.bb",
            "mult",
            Accepts::Numeric,
            pine_type(Qualifier::Const, ValueKind::String),
            Span::default(),
        )
        .expect("const string should not satisfy numeric");
        assert_eq!(
            diagnostic.message,
            "`ta.bb` argument `mult` expects numeric, got const string"
        );

        let diagnostic = call_arg_accepts_type_expected_diagnostic(
            "timeframe.from_seconds",
            "seconds",
            Accepts::SimpleIntCompatible,
            pine_type(Qualifier::Series, ValueKind::Int),
            Span::default(),
        )
        .expect("series int should not satisfy simple integer-compatible");
        assert_eq!(
            diagnostic.message,
            "`timeframe.from_seconds` argument `seconds` expects simple integer-compatible, got series int"
        );

        let diagnostic = call_arg_accepts_type_expected_diagnostic(
            "ta.barssince",
            "condition",
            Accepts::BoolCompatible,
            pine_type(Qualifier::Const, ValueKind::String),
            Span::default(),
        )
        .expect("const string should not satisfy bool-compatible");
        assert_eq!(
            diagnostic.message,
            "`ta.barssince` argument `condition` expects bool-compatible, got const string"
        );

        let diagnostic = call_arg_accepts_type_expected_diagnostic(
            "array.join",
            "separator",
            Accepts::StringCompatible,
            pine_type(Qualifier::Series, ValueKind::Float),
            Span::default(),
        )
        .expect("series float should not satisfy string-compatible");
        assert_eq!(
            diagnostic.message,
            "`array.join` argument `separator` expects string-compatible, got series float"
        );

        let diagnostic = call_arg_accepts_type_expected_diagnostic(
            "str.tostring",
            "value",
            Accepts::StringConvertible,
            pine_type(Qualifier::Simple, ValueKind::ColorArray),
            Span::default(),
        )
        .expect("simple array<color> should not satisfy string-convertible");
        assert_eq!(
            diagnostic.message,
            "`str.tostring` argument `value` expects string-convertible, got simple array<color>"
        );

        let diagnostic = call_arg_accepts_type_expected_diagnostic(
            "int",
            "x",
            Accepts::CastScalar,
            pine_type(Qualifier::Simple, ValueKind::String),
            Span::default(),
        )
        .expect("simple string should not satisfy int/float/bool-compatible");
        assert_eq!(
            diagnostic.message,
            "`int` argument `x` expects int/float/bool-compatible, got simple string"
        );

        let diagnostic = call_arg_accepts_type_expected_diagnostic(
            "string",
            "x",
            Accepts::StringCastScalar,
            pine_type(Qualifier::Simple, ValueKind::Color),
            Span::default(),
        )
        .expect("simple color should not satisfy int/float/bool/string-compatible");
        assert_eq!(
            diagnostic.message,
            "`string` argument `x` expects int/float/bool/string-compatible, got simple color"
        );

        let diagnostic = call_arg_accepts_type_expected_diagnostic(
            "fixnan",
            "source",
            Accepts::NumericOrColorCompatible,
            pine_type(Qualifier::Simple, ValueKind::String),
            Span::default(),
        )
        .expect("simple string should not satisfy numeric/color-compatible");
        assert_eq!(
            diagnostic.message,
            "`fixnan` argument `source` expects numeric/color-compatible, got simple string"
        );

        let diagnostic = call_arg_accepts_type_expected_diagnostic(
            "array.new_float",
            "initial_value",
            Accepts::NumericCompatible,
            pine_type(Qualifier::Const, ValueKind::String),
            Span::default(),
        )
        .expect("const string should not satisfy numeric-compatible");
        assert_eq!(
            diagnostic.message,
            "`array.new_float` argument `initial_value` expects numeric-compatible, got const string"
        );

        let diagnostic = call_arg_accepts_type_expected_diagnostic(
            "input.color",
            "defval",
            Accepts::ColorCompatible,
            pine_type(Qualifier::Const, ValueKind::String),
            Span::default(),
        )
        .expect("const string should not satisfy color-compatible");
        assert_eq!(
            diagnostic.message,
            "`input.color` argument `defval` expects color-compatible, got const string"
        );

        let diagnostic = call_arg_accepts_type_expected_diagnostic(
            "array.new_label",
            "initial_value",
            Accepts::LabelCompatible,
            pine_type(Qualifier::Const, ValueKind::String),
            Span::default(),
        )
        .expect("const string should not satisfy label-compatible");
        assert_eq!(
            diagnostic.message,
            "`array.new_label` argument `initial_value` expects label-compatible, got const string"
        );

        let diagnostic = call_arg_accepts_type_expected_diagnostic(
            "ta.valuewhen",
            "source",
            Accepts::ValueWhenSource,
            pine_type(Qualifier::Const, ValueKind::String),
            Span::default(),
        )
        .expect("const string should not satisfy valuewhen source");
        assert_eq!(
            diagnostic.message,
            "`ta.valuewhen` argument `source` expects numeric/bool/color-compatible, got const string"
        );

        let diagnostic = call_arg_accepts_type_expected_diagnostic(
            "label.new",
            "size",
            Accepts::StringOrIntCompatible,
            pine_type(Qualifier::Series, ValueKind::Float),
            Span::default(),
        )
        .expect("series float should not satisfy string/int-compatible");
        assert_eq!(
            diagnostic.message,
            "`label.new` argument `size` expects string/int-compatible, got series float"
        );

        let diagnostic = call_arg_accepts_type_expected_diagnostic(
            "label.new",
            "point",
            Accepts::ChartPointCompatible,
            pine_type(Qualifier::Series, ValueKind::Float),
            Span::default(),
        )
        .expect("series float should not satisfy chart.point-compatible");
        assert_eq!(
            diagnostic.message,
            "`label.new` argument `point` expects chart.point-compatible, got series float"
        );

        let diagnostic = call_arg_accepts_type_expected_diagnostic(
            "fill",
            "plot1",
            Accepts::PlotOrHLine,
            pine_type(Qualifier::Series, ValueKind::Float),
            Span::default(),
        )
        .expect("series float should not satisfy plot/hline");
        assert_eq!(
            diagnostic.message,
            "`fill` argument `plot1` expects plot/hline, got series float"
        );

        let diagnostic = call_arg_accepts_type_expected_diagnostic(
            "map.get",
            "id",
            Accepts::Map,
            pine_type(Qualifier::Series, ValueKind::Float),
            Span::default(),
        )
        .expect("series float should not satisfy map");
        assert_eq!(
            diagnostic.message,
            "`map.get` argument `id` expects map, got series float"
        );

        let diagnostic = call_arg_accepts_type_expected_diagnostic(
            "array.size",
            "id",
            Accepts::Array,
            pine_type(Qualifier::Series, ValueKind::Float),
            Span::default(),
        )
        .expect("series float should not satisfy array");
        assert_eq!(
            diagnostic.message,
            "`array.size` argument `id` expects array, got series float"
        );

        let diagnostic = call_arg_accepts_type_expected_diagnostic(
            "array.sum",
            "id",
            Accepts::NumericArray,
            pine_type(Qualifier::Simple, ValueKind::StringArray),
            Span::default(),
        )
        .expect("string array should not satisfy numeric array");
        assert_eq!(
            diagnostic.message,
            "`array.sum` argument `id` expects numeric array, got simple array<string>"
        );

        let diagnostic = call_arg_accepts_type_expected_diagnostic(
            "array.every",
            "id",
            Accepts::NumericOrBoolArray,
            pine_type(Qualifier::Simple, ValueKind::StringArray),
            Span::default(),
        )
        .expect("string array should not satisfy numeric/bool array");
        assert_eq!(
            diagnostic.message,
            "`array.every` argument `id` expects numeric/bool array, got simple array<string>"
        );

        let diagnostic = call_arg_accepts_type_expected_diagnostic(
            "array.sort",
            "id",
            Accepts::NumericOrStringArray,
            pine_type(Qualifier::Simple, ValueKind::BoolArray),
            Span::default(),
        )
        .expect("bool array should not satisfy numeric/string array");
        assert_eq!(
            diagnostic.message,
            "`array.sort` argument `id` expects numeric/string array, got simple array<bool>"
        );

        let diagnostic = call_arg_accepts_type_expected_diagnostic(
            "array.join",
            "id",
            Accepts::ScalarArray,
            pine_type(Qualifier::Simple, ValueKind::ChartPointArray),
            Span::default(),
        )
        .expect("chart.point array should not satisfy scalar array");
        assert_eq!(
            diagnostic.message,
            "`array.join` argument `id` expects scalar array, got simple array<chart.point>"
        );

        let diagnostic = call_arg_accepts_type_expected_diagnostic(
            "matrix.fill",
            "id",
            Accepts::Matrix,
            pine_type(Qualifier::Const, ValueKind::Na),
            Span::default(),
        )
        .expect("const na should not satisfy matrix");
        assert_eq!(
            diagnostic.message,
            "`matrix.fill` argument `id` expects matrix, got const na"
        );

        let diagnostic = call_arg_accepts_type_expected_diagnostic(
            "matrix.sum",
            "id",
            Accepts::NumericMatrix,
            pine_type(Qualifier::Simple, ValueKind::BoolMatrix),
            Span::default(),
        )
        .expect("bool matrix should not satisfy numeric matrix");
        assert_eq!(
            diagnostic.message,
            "`matrix.sum` argument `id` expects numeric matrix, got simple matrix<bool>"
        );

        let diagnostic = call_arg_accepts_type_expected_diagnostic(
            "matrix.mode",
            "id",
            Accepts::FloatMatrix,
            pine_type(Qualifier::Simple, ValueKind::IntMatrix),
            Span::default(),
        )
        .expect("int matrix should not satisfy matrix<float>");
        assert_eq!(
            diagnostic.message,
            "`matrix.mode` argument `id` expects matrix<float>, got simple matrix<int>"
        );

        let diagnostic = call_arg_accepts_type_expected_diagnostic(
            "input.int",
            "options",
            Accepts::Tuple,
            pine_type(Qualifier::Const, ValueKind::Int),
            Span::default(),
        )
        .expect("const int should not satisfy tuple");
        assert_eq!(
            diagnostic.message,
            "`input.int` argument `options` expects tuple, got const int"
        );

        let diagnostic = call_arg_accepts_type_expected_diagnostic(
            "input",
            "defval",
            Accepts::InputDefval,
            pine_type(Qualifier::Series, ValueKind::Float),
            Span::default(),
        )
        .expect("series float should not satisfy input defval");
        assert_eq!(
            diagnostic.message,
            "`input` argument `defval` expects const int/float/bool/string/color, got series float"
        );

        let diagnostic = call_arg_accepts_type_expected_diagnostic(
            "input.int",
            "minval",
            Accepts::Exact(PineType::new(Qualifier::Const, ValueKind::Int)),
            pine_type(Qualifier::Series, ValueKind::Float),
            Span::default(),
        )
        .expect("series float should not satisfy exact const int");
        assert_eq!(
            diagnostic.message,
            "`input.int` argument `minval` expects const int, got series float"
        );

        let diagnostic = call_arg_accepts_type_expected_diagnostic(
            "future.kind",
            "value",
            Accepts::Kind(ValueKind::Plot),
            pine_type(Qualifier::Series, ValueKind::Float),
            Span::default(),
        )
        .expect("series float should not satisfy plot kind");
        assert_eq!(
            diagnostic.message,
            "`future.kind` argument `value` expects plot, got series float"
        );
    }

    #[test]
    fn acceptor_expected_diagnostic_returns_none_for_valid_arguments() {
        assert!(
            call_arg_accepts_type_expected_diagnostic(
                "ta.highest",
                "length",
                Accepts::SimpleInt,
                pine_type(Qualifier::Input, ValueKind::Int),
                Span::default(),
            )
            .is_none()
        );
        assert!(
            call_arg_accepts_type_expected_diagnostic(
                "ta.pivothigh",
                "rightbars",
                Accepts::IntCompatible,
                pine_type(Qualifier::Series, ValueKind::Int),
                Span::default(),
            )
            .is_none()
        );
        assert!(
            call_arg_accepts_type_expected_diagnostic(
                "hline",
                "price",
                Accepts::AtMostInputNumeric,
                pine_type(Qualifier::Input, ValueKind::Float),
                Span::default(),
            )
            .is_none()
        );
        assert!(
            call_arg_accepts_type_expected_diagnostic(
                "hline",
                "linewidth",
                Accepts::AtMostInputInt,
                pine_type(Qualifier::Input, ValueKind::Int),
                Span::default(),
            )
            .is_none()
        );
        assert!(
            call_arg_accepts_type_expected_diagnostic(
                "future.input_string",
                "value",
                Accepts::AtMostInputString,
                pine_type(Qualifier::Input, ValueKind::String),
                Span::default(),
            )
            .is_none()
        );
        assert!(
            call_arg_accepts_type_expected_diagnostic(
                "future.input_bool",
                "value",
                Accepts::AtMostInputBool,
                pine_type(Qualifier::Const, ValueKind::Bool),
                Span::default(),
            )
            .is_none()
        );
        assert!(
            call_arg_accepts_type_expected_diagnostic(
                "future.input_color",
                "value",
                Accepts::AtMostInputColor,
                pine_type(Qualifier::Input, ValueKind::Color),
                Span::default(),
            )
            .is_none()
        );
        assert!(
            call_arg_accepts_type_expected_diagnostic(
                "time",
                "timeframe",
                Accepts::SimpleString,
                pine_type(Qualifier::Simple, ValueKind::String),
                Span::default(),
            )
            .is_none()
        );
        assert!(
            call_arg_accepts_type_expected_diagnostic(
                "timestamp",
                "dateString",
                Accepts::ConstString,
                pine_type(Qualifier::Const, ValueKind::String),
                Span::default(),
            )
            .is_none()
        );
        assert!(
            call_arg_accepts_type_expected_diagnostic(
                "ta.stdev",
                "biased",
                Accepts::ConstBool,
                pine_type(Qualifier::Const, ValueKind::Bool),
                Span::default(),
            )
            .is_none()
        );
        assert!(
            call_arg_accepts_type_expected_diagnostic(
                "strategy",
                "initial_capital",
                Accepts::ConstNumeric,
                pine_type(Qualifier::Const, ValueKind::Float),
                Span::default(),
            )
            .is_none()
        );
        assert!(
            call_arg_accepts_type_expected_diagnostic(
                "ta.alma",
                "offset",
                Accepts::SimpleNumeric,
                pine_type(Qualifier::Simple, ValueKind::Float),
                Span::default(),
            )
            .is_none()
        );
        assert!(
            call_arg_accepts_type_expected_diagnostic(
                "ta.alma",
                "floor",
                Accepts::SimpleBool,
                pine_type(Qualifier::Input, ValueKind::Bool),
                Span::default(),
            )
            .is_none()
        );
    }
}
