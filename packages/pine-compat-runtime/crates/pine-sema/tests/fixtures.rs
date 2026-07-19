use std::{collections::HashSet, fs, path::PathBuf};

use pine_sema::{AnalysisInput, analyze_input, analyze_source};
use pine_syntax::SourceFile;

fn workspace_fixture(path: &str) -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .join(path)
}

#[test]
fn reports_unsupported_request_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/unsupported_request.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert_eq!(analysis.compatibility.unsupported.len(), 1);
    assert_eq!(
        analysis.compatibility.unsupported[0].feature,
        "request.security"
    );
}

#[test]
fn reports_unsupported_request_lower_tf_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_request_lower_tf.pine",
        "request.security_lower_tf",
        "array-returning lower-timeframe request semantics",
    );
}

#[test]
fn reports_unsupported_request_family_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_request_family.pine",
        "request.financial",
        "outside the supported request.security subset",
    );
}

#[test]
fn reports_unsupported_request_math_calls_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_request_math_calls.pine",
        "request.security",
        "same-context request.security",
    );
}

#[test]
fn reports_unsupported_request_security_symbol_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_request_security_symbol_qualifier.pine",
        &["`request.security` argument `symbol` expects simple string, got series float"],
    );
}

#[test]
fn reports_unsupported_request_security_timeframe_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_request_security_timeframe_qualifier.pine",
        &["`request.security` argument `timeframe` expects simple string, got series string"],
    );
}

#[test]
fn accepts_supported_request_security_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_request_security_return_qualifier.pine");
}

#[test]
fn reports_unsupported_request_security_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_request_security_return_qualifier.pine",
        &[
            "`plot` argument `offset` expects simple integer-compatible, got series int",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`ta.alma` argument `floor` expects simple bool-compatible, got series bool",
            "`hline` argument `color` expects const/input color, got series color",
            "`syminfo.prefix` argument `symbol` expects simple string, got series string",
        ],
    );
}

#[test]
fn accepts_supported_math_sum_series_length_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_math_sum_series_length.pine");
}

#[test]
fn reports_unsupported_math_sum_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_math_sum_length.pine",
        &["`math.sum` argument `length` expects integer-compatible, got const float"],
    );
}

#[test]
fn accepts_supported_math_random_na_seed_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_math_random_na_seed.pine");
}

#[test]
fn reports_unsupported_math_random_series_seed_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_math_random_series_seed.pine",
        &["`math.random` argument `seed` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_request_merge_options_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_request_merge_options.pine",
        "request.security",
        "optional gaps/lookahead",
    );
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_request_merge_options_named_const.pine",
        "request.security",
        "optional gaps/lookahead",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_request_merge_options.pine",
        &["barmerge.gaps_off", "barmerge.lookahead_off"],
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_request_merge_options_named_const.pine",
        &["barmerge.gaps_off", "barmerge.lookahead_off"],
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_request_security_merge_qualifier.pine",
        &[
            "`request.security` argument `gaps` expects simple string, got series string",
            "`request.security` argument `lookahead` expects simple string, got series string",
        ],
    );
}

#[test]
fn accepts_supported_request_merge_options_named_const_fixture() {
    let path =
        workspace_fixture("tests/fixtures/sema/supported_request_merge_options_named_const.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(
        analysis.compatibility.unsupported.is_empty(),
        "{} unsupported: {:?}",
        path.display(),
        analysis.compatibility.unsupported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_provider_request_context_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/request_security_provider_context.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_supported_time_na_simple_string_params_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_time_na_simple_string_params.pine");
}

#[test]
fn accepts_supported_timeframe_from_seconds_na_simple_int_param_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_timeframe_from_seconds_na_simple_int_param.pine",
    );
}

#[test]
fn reports_unsupported_timeframe_from_seconds_series_param_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_timeframe_from_seconds_series_param.pine",
        &[
            "`timeframe.from_seconds` argument `seconds` expects simple integer-compatible, got series int",
        ],
    );
}

#[test]
fn accepts_supported_timeframe_from_seconds_simple_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_timeframe_from_seconds_simple_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_timeframe_from_seconds_const_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_timeframe_from_seconds_const_return_qualifier.pine",
        &[
            "`timestamp` argument `dateString` expects const string, got simple string",
            "`timestamp` argument `dateString` expects const string, got simple string",
            "`timestamp` argument `dateString` expects const string, got simple string",
        ],
    );
}

#[test]
fn reports_unsupported_timeframe_series_simple_string_params_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_timeframe_series_simple_string_params.pine",
        &[
            "`timeframe.in_seconds` argument `timeframe` expects simple string, got series string",
            "`timeframe.change` argument `timeframe` expects simple string, got series string",
        ],
    );
}

#[test]
fn accepts_supported_time_function_series_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_time_function_series_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_time_function_simple_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_time_function_simple_return_qualifier.pine",
        &[
            "`plot` argument `offset` expects simple integer-compatible, got series int",
            "`plot` argument `offset` expects simple integer-compatible, got series int",
            "`ta.alma` argument `floor` expects simple bool-compatible, got series bool",
        ],
    );
}

#[test]
fn accepts_supported_timeframe_metadata_simple_string_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_timeframe_metadata_simple_string_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_timeframe_metadata_const_string_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_timeframe_metadata_const_string_return_qualifier.pine",
        &[
            "`timestamp` argument `dateString` expects const string, got simple string",
            "`timestamp` argument `dateString` expects const string, got simple string",
        ],
    );
}

#[test]
fn accepts_supported_timeframe_metadata_simple_bool_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_timeframe_metadata_simple_bool_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_timeframe_metadata_const_bool_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_timeframe_metadata_const_bool_return_qualifier.pine",
        &["`ta.tr` argument `handle_na` expects const bool, got simple bool"],
    );
}

#[test]
fn accepts_supported_bool_cast_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_bool_cast_return_qualifier.pine");
}

#[test]
fn reports_unsupported_bool_cast_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_bool_cast_return_qualifier.pine",
        &[
            "`ta.tr` argument `handle_na` expects const bool, got input bool",
            "`ta.tr` argument `handle_na` expects const bool, got simple bool",
            "`ta.alma` argument `floor` expects simple bool-compatible, got series bool",
        ],
    );
}

#[test]
fn accepts_supported_na_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_na_return_qualifier.pine");
}

#[test]
fn reports_unsupported_na_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_na_return_qualifier.pine",
        &[
            "`ta.tr` argument `handle_na` expects const bool, got input bool",
            "`ta.tr` argument `handle_na` expects const bool, got simple bool",
            "`ta.alma` argument `floor` expects simple bool-compatible, got series bool",
        ],
    );
}

#[test]
fn accepts_supported_timeframe_in_seconds_simple_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_timeframe_in_seconds_simple_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_timeframe_in_seconds_const_input_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_timeframe_in_seconds_const_input_return_qualifier.pine",
        &[
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`plot` argument `show_last` expects const/input int, got simple int",
        ],
    );
}

#[test]
fn accepts_supported_chart_metadata_simple_bool_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_chart_metadata_simple_bool_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_chart_metadata_const_bool_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_chart_metadata_const_bool_return_qualifier.pine",
        &["`ta.tr` argument `handle_na` expects const bool, got simple bool"],
    );
}

#[test]
fn accepts_supported_chart_metadata_simple_color_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_chart_metadata_simple_color_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_chart_metadata_const_input_color_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_chart_metadata_const_input_color_return_qualifier.pine",
        &[
            "`hline` argument `color` expects const/input color, got simple color",
            "`hline` argument `color` expects const/input color, got simple color",
        ],
    );
}

#[test]
fn accepts_supported_session_metadata_series_bool_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_session_metadata_series_bool_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_session_metadata_simple_bool_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_session_metadata_simple_bool_qualifier.pine",
        &[
            "`ta.alma` argument `floor` expects simple bool-compatible, got series bool",
            "`ta.alma` argument `floor` expects simple bool-compatible, got series bool",
            "`ta.alma` argument `floor` expects simple bool-compatible, got series bool",
            "`ta.alma` argument `floor` expects simple bool-compatible, got series bool",
            "`ta.alma` argument `floor` expects simple bool-compatible, got series bool",
            "`ta.alma` argument `floor` expects simple bool-compatible, got series bool",
            "`ta.alma` argument `floor` expects simple bool-compatible, got series bool",
        ],
    );
}

#[test]
fn accepts_supported_barstate_metadata_series_bool_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_barstate_metadata_series_bool_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_barstate_metadata_simple_bool_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_barstate_metadata_simple_bool_qualifier.pine",
        &[
            "`ta.alma` argument `floor` expects simple bool-compatible, got series bool",
            "`ta.alma` argument `floor` expects simple bool-compatible, got series bool",
            "`ta.alma` argument `floor` expects simple bool-compatible, got series bool",
            "`ta.alma` argument `floor` expects simple bool-compatible, got series bool",
            "`ta.alma` argument `floor` expects simple bool-compatible, got series bool",
            "`ta.alma` argument `floor` expects simple bool-compatible, got series bool",
            "`ta.alma` argument `floor` expects simple bool-compatible, got series bool",
        ],
    );
}

#[test]
fn accepts_supported_ohlcv_series_float_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ohlcv_series_float_qualifier.pine");
}

#[test]
fn reports_unsupported_ohlcv_simple_numeric_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ohlcv_simple_numeric_qualifier.pine",
        &[
            "`ta.alma` argument `offset` expects simple numeric-compatible, got series float",
            "`ta.alma` argument `offset` expects simple numeric-compatible, got series float",
            "`ta.alma` argument `sigma` expects simple numeric-compatible, got series float",
            "`ta.alma` argument `offset` expects simple numeric-compatible, got series float",
            "`ta.alma` argument `sigma` expects simple numeric-compatible, got series float",
        ],
    );
}

#[test]
fn accepts_supported_derived_price_bar_index_series_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_derived_price_bar_index_series_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_derived_price_bar_index_simple_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_derived_price_bar_index_simple_qualifier.pine",
        &[
            "`ta.alma` argument `offset` expects simple numeric-compatible, got series float",
            "`ta.alma` argument `offset` expects simple numeric-compatible, got series float",
            "`ta.alma` argument `sigma` expects simple numeric-compatible, got series float",
            "`ta.alma` argument `offset` expects simple numeric-compatible, got series float",
            "`plot` argument `offset` expects simple integer-compatible, got series int",
        ],
    );
}

#[test]
fn accepts_supported_time_globals_series_int_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_time_globals_series_int_qualifier.pine");
}

#[test]
fn reports_unsupported_time_globals_simple_int_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_time_globals_simple_int_qualifier.pine",
        &[
            "`plot` argument `offset` expects simple integer-compatible, got series int",
            "`plot` argument `offset` expects simple integer-compatible, got series int",
            "`plot` argument `offset` expects simple integer-compatible, got series int",
        ],
    );
}

#[test]
fn accepts_supported_time_component_globals_series_int_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_time_component_globals_series_int_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_time_component_globals_simple_int_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_time_component_globals_simple_int_qualifier.pine",
        &[
            "`plot` argument `offset` expects simple integer-compatible, got series int",
            "`plot` argument `offset` expects simple integer-compatible, got series int",
            "`plot` argument `offset` expects simple integer-compatible, got series int",
            "`plot` argument `offset` expects simple integer-compatible, got series int",
            "`plot` argument `offset` expects simple integer-compatible, got series int",
            "`plot` argument `offset` expects simple integer-compatible, got series int",
            "`plot` argument `offset` expects simple integer-compatible, got series int",
            "`plot` argument `offset` expects simple integer-compatible, got series int",
        ],
    );
}

#[test]
fn accepts_supported_last_bar_metadata_series_int_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_last_bar_metadata_series_int_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_last_bar_metadata_simple_int_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_last_bar_metadata_simple_int_qualifier.pine",
        &[
            "`plot` argument `offset` expects simple integer-compatible, got series int",
            "`plot` argument `offset` expects simple integer-compatible, got series int",
        ],
    );
}

#[test]
fn accepts_supported_metadata_simple_int_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_metadata_simple_int_return_qualifier.pine");
}

#[test]
fn reports_unsupported_metadata_const_input_int_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_metadata_const_input_int_return_qualifier.pine",
        &[
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`plot` argument `show_last` expects const/input int, got simple int",
        ],
    );
}

#[test]
fn accepts_supported_time_promoted_int_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_time_promoted_int_return_qualifier.pine");
}

#[test]
fn reports_unsupported_time_promoted_int_simple_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_time_promoted_int_simple_return_qualifier.pine",
        &[
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`plot` argument `show_last` expects const/input int, got simple int",
        ],
    );
}

#[test]
fn accepts_supported_syminfo_na_simple_string_params_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_syminfo_na_simple_string_params.pine");
}

#[test]
fn reports_unsupported_syminfo_series_simple_string_params_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_syminfo_series_simple_string_params.pine",
        &[
            "`syminfo.prefix` argument `symbol` expects simple string, got series string",
            "`syminfo.ticker` argument `symbol` expects simple string, got series string",
        ],
    );
}

#[test]
fn accepts_supported_syminfo_metadata_simple_string_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_syminfo_metadata_simple_string_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_syminfo_metadata_const_string_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_syminfo_metadata_const_string_return_qualifier.pine",
        &[
            "`timestamp` argument `dateString` expects const string, got simple string",
            "`timestamp` argument `dateString` expects const string, got simple string",
            "`timestamp` argument `dateString` expects const string, got simple string",
            "`timestamp` argument `dateString` expects const string, got simple string",
            "`timestamp` argument `dateString` expects const string, got simple string",
            "`timestamp` argument `dateString` expects const string, got simple string",
            "`timestamp` argument `dateString` expects const string, got simple string",
            "`timestamp` argument `dateString` expects const string, got simple string",
            "`timestamp` argument `dateString` expects const string, got simple string",
            "`timestamp` argument `dateString` expects const string, got simple string",
            "`timestamp` argument `dateString` expects const string, got simple string",
            "`timestamp` argument `dateString` expects const string, got simple string",
            "`timestamp` argument `dateString` expects const string, got simple string",
            "`timestamp` argument `dateString` expects const string, got simple string",
            "`timestamp` argument `dateString` expects const string, got simple string",
        ],
    );
}

#[test]
fn accepts_supported_syminfo_helper_simple_string_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_syminfo_helper_simple_string_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_syminfo_helper_const_string_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_syminfo_helper_const_string_return_qualifier.pine",
        &[
            "`timestamp` argument `dateString` expects const string, got simple string",
            "`timestamp` argument `dateString` expects const string, got simple string",
        ],
    );
}

#[test]
fn accepts_supported_syminfo_metadata_simple_numeric_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_syminfo_metadata_simple_numeric_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_syminfo_metadata_const_input_numeric_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_syminfo_metadata_const_input_numeric_qualifier.pine",
        &[
            "`hline` argument `price` expects const/input numeric, got simple float",
            "`hline` argument `price` expects const/input numeric, got simple float",
            "`hline` argument `price` expects const/input numeric, got simple float",
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`plot` argument `show_last` expects const/input int, got simple int",
        ],
    );
}

#[test]
fn reports_unsupported_time_function_arg_types_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_time_function_arg_types.pine",
        &[
            "`time` argument `timeframe` expects simple string, got const int",
            "`time_close` argument `session` expects string-compatible, got const int",
        ],
    );
}

#[test]
fn reports_unsupported_time_positional_overload_types_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_time_positional_overload_types.pine",
        &[
            "`time` argument `second positional` expects a session string or bars_back int, got const float",
            "`time_close` argument `second positional` expects a session string or bars_back int, got const float",
            "`time` argument `third positional` expects a timezone string or bars_back int, got const float",
            "`timestamp` argument `first positional` expects a year int or timezone string, got const float",
        ],
    );
}

#[test]
fn reports_unsupported_timestamp_date_string_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_timestamp_date_string_qualifier.pine",
        &["`timestamp` argument `dateString` expects const string, got simple string"],
    );
}

#[test]
fn reports_unsupported_operator_types_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_operator_types.pine",
        &[
            "operator `+` expects numeric, got const string",
            "operator `not` expects bool, got const int",
            "operator `+` expects numeric or string operands, got const string and const int",
            "operator `and` expects bool operands, got const bool and const int",
        ],
    );
}

#[test]
fn accepts_supported_string_concatenation_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_string_concatenation.pine");
}

#[test]
fn reports_string_concatenation_qualifier_boundaries_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_string_concatenation_qualifiers.pine",
        &[
            "`plot` argument `title` expects const string, got input string",
            "`timestamp` argument `dateString` expects const string, got simple string",
            "`syminfo.prefix` argument `symbol` expects simple string, got series string",
        ],
    );
}

#[test]
fn accepts_supported_compound_assignments_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_compound_assignments.pine");
}

#[test]
fn reports_unsupported_compound_assignment_types_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_compound_assignment_types.pine",
        &[
            "operator `+` expects numeric or string operands, got const int and const string",
            "operator `-` expects numeric operands, got const string and const string",
            "operator `*` expects numeric operands, got const bool and const int",
        ],
    );
}

#[test]
fn reports_unknown_compound_assignment_target_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_compound_assignment_unknown_target.pine",
        "E_UNKNOWN_SYMBOL",
    );
}

#[test]
fn reports_unsupported_assignment_types_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_assignment_types.pine",
        &[
            "cannot assign const string to `count` of type const int",
            "cannot assign const string to `point.x` of type series float",
        ],
    );
}

#[test]
fn reports_unsupported_relational_operator_types_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_relational_operator_types.pine",
        &[
            "operator `>` expects numeric operands, got const string and const int",
            "operator `<=` expects numeric operands, got const bool and const bool",
        ],
    );
}

#[test]
fn reports_unsupported_equality_operator_types_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_equality_operator_types.pine",
        &[
            "operator `==` expects comparable operands, got const string and const int",
            "operator `!=` expects comparable operands, got const bool and const int",
        ],
    );
}

#[test]
fn accepts_supported_hline_input_price_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_hline_input_price.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "hline"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_hline_input_color_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_hline_input_color.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "hline"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_hline_input_linewidth_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_hline_input_linewidth.pine");
}

#[test]
fn accepts_supported_indicator_named_const_metadata_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_indicator_named_const_metadata.pine");
}

#[test]
fn reports_unsupported_input_defval_series_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_input_defval_series.pine",
        &["`input` argument `defval` expects const int/float/bool/string/color, got series float"],
    );
}

#[test]
fn accepts_supported_input_return_qualifiers_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_input_return_qualifiers.pine");
}

#[test]
fn reports_unsupported_input_return_qualifiers_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_input_return_qualifiers.pine",
        &[
            "`plot` argument `title` expects const string, got input string",
            "`plot` argument `trackprice` expects const bool, got input bool",
            "`ta.alma` argument `offset` expects simple numeric-compatible, got series float",
        ],
    );
}

#[test]
fn reports_unsupported_input_options_non_tuple_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_input_options_non_tuple.pine",
        &["`input.int` argument `options` expects tuple, got const int"],
    );
}

#[test]
fn reports_unsupported_input_int_minval_series_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_input_int_minval_series.pine",
        &["`input.int` argument `minval` expects const int, got series float"],
    );
}

#[test]
fn reports_unsupported_hline_series_price_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_hline_series_price.pine",
        &["`hline` argument `price` expects const/input numeric, got series float"],
    );
}

#[test]
fn reports_unsupported_hline_simple_price_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_hline_simple_price.pine",
        &["`hline` argument `price` expects const/input numeric, got simple int"],
    );
}

#[test]
fn reports_unsupported_hline_series_color_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_hline_series_color.pine",
        &["`hline` argument `color` expects const/input color, got series color"],
    );
}

#[test]
fn reports_unsupported_hline_simple_color_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_hline_simple_color.pine",
        &["`hline` argument `color` expects const/input color, got simple color"],
    );
}

#[test]
fn reports_unsupported_hline_simple_linewidth_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_hline_simple_linewidth.pine",
        &["`hline` argument `linewidth` expects const/input int, got simple int"],
    );
}

#[test]
fn accepts_supported_promoted_return_qualifiers_for_input_params_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_promoted_return_qualifiers_for_input_params.pine",
    );
}

#[test]
fn reports_unsupported_promoted_return_qualifiers_for_simple_params_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_promoted_return_qualifiers_for_simple_params.pine",
        &[
            "`hline` argument `price` expects const/input numeric, got simple int",
            "`hline` argument `price` expects const/input numeric, got simple int",
            "`hline` argument `price` expects const/input numeric, got simple float",
            "`hline` argument `price` expects const/input numeric, got simple float",
            "`hline` argument `price` expects const/input numeric, got simple float",
            "`plot` argument `show_last` expects const/input int, got simple int",
        ],
    );
}

#[test]
fn accepts_supported_str_promoted_bool_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_str_promoted_bool_return_qualifier.pine");
}

#[test]
fn reports_unsupported_str_promoted_bool_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_str_promoted_bool_return_qualifier.pine",
        &[
            "`ta.tr` argument `handle_na` expects const bool, got input bool",
            "`ta.tr` argument `handle_na` expects const bool, got simple bool",
            "`ta.alma` argument `floor` expects simple bool-compatible, got series bool",
        ],
    );
}

#[test]
fn accepts_supported_str_length_input_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_str_length_input_return_qualifier.pine");
}

#[test]
fn reports_unsupported_str_length_simple_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_str_length_simple_return_qualifier.pine",
        &["`plot` argument `show_last` expects const/input int, got simple int"],
    );
}

#[test]
fn accepts_supported_str_case_trim_same_as_arg_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_str_case_trim_same_as_arg_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_str_case_trim_simple_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_str_case_trim_simple_return_qualifier.pine",
        &[
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`plot` argument `show_last` expects const/input int, got simple int",
        ],
    );
}

#[test]
fn accepts_supported_str_promoted_string_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_str_promoted_string_return_qualifier.pine");
}

#[test]
fn reports_unsupported_str_promoted_string_simple_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_str_promoted_string_simple_return_qualifier.pine",
        &[
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`plot` argument `show_last` expects const/input int, got simple int",
        ],
    );
}

#[test]
fn accepts_supported_str_formatting_promoted_string_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_str_formatting_promoted_string_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_str_formatting_promoted_string_simple_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_str_formatting_promoted_string_simple_return_qualifier.pine",
        &[
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`plot` argument `show_last` expects const/input int, got simple int",
        ],
    );
}

#[test]
fn accepts_supported_str_match_promoted_string_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_str_match_promoted_string_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_str_match_promoted_string_simple_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_str_match_promoted_string_simple_return_qualifier.pine",
        &["`plot` argument `show_last` expects const/input int, got simple int"],
    );
}

#[test]
fn accepts_supported_str_tonumber_input_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_str_tonumber_input_return_qualifier.pine");
}

#[test]
fn reports_unsupported_str_tonumber_simple_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_str_tonumber_simple_return_qualifier.pine",
        &["`hline` argument `price` expects const/input numeric, got simple float"],
    );
}

#[test]
fn accepts_supported_array_size_simple_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_array_size_simple_return_qualifier.pine");
}

#[test]
fn reports_unsupported_array_size_const_input_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_size_const_input_return_qualifier.pine",
        &[
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`plot` argument `show_last` expects const/input int, got simple int",
        ],
    );
}

#[test]
fn accepts_supported_matrix_dimension_simple_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_matrix_dimension_simple_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_matrix_dimension_const_input_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_matrix_dimension_const_input_return_qualifier.pine",
        &[
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`plot` argument `show_last` expects const/input int, got simple int",
        ],
    );
}

#[test]
fn accepts_supported_matrix_predicate_simple_bool_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_matrix_predicate_simple_bool_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_matrix_predicate_const_bool_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_matrix_predicate_const_bool_return_qualifier.pine",
        &[
            "`ta.tr` argument `handle_na` expects const bool, got simple bool",
            "`ta.tr` argument `handle_na` expects const bool, got simple bool",
            "`ta.tr` argument `handle_na` expects const bool, got simple bool",
            "`ta.tr` argument `handle_na` expects const bool, got simple bool",
            "`ta.tr` argument `handle_na` expects const bool, got simple bool",
            "`ta.tr` argument `handle_na` expects const bool, got simple bool",
            "`ta.tr` argument `handle_na` expects const bool, got simple bool",
            "`ta.tr` argument `handle_na` expects const bool, got simple bool",
            "`ta.tr` argument `handle_na` expects const bool, got simple bool",
            "`ta.tr` argument `handle_na` expects const bool, got simple bool",
            "`ta.tr` argument `handle_na` expects const bool, got simple bool",
            "`ta.tr` argument `handle_na` expects const bool, got simple bool",
            "`ta.tr` argument `handle_na` expects const bool, got simple bool",
            "`ta.tr` argument `handle_na` expects const bool, got simple bool",
            "`ta.tr` argument `handle_na` expects const bool, got simple bool",
            "`ta.tr` argument `handle_na` expects const bool, got simple bool",
        ],
    );
}

#[test]
fn accepts_supported_matrix_is_antidiagonal_series_bool_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_matrix_is_antidiagonal_series_bool_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_matrix_is_antidiagonal_simple_bool_return_qualifier_fixture() {
    assert_exact_diagnostic_messages(
        "tests/fixtures/sema/unsupported_matrix_is_antidiagonal_simple_bool_return_qualifier.pine",
        &[
            "`ta.alma` argument `floor` expects simple bool-compatible, got series bool",
            "`ta.alma` argument `floor` expects simple bool-compatible, got series bool",
            "`ta.alma` argument `floor` expects simple bool-compatible, got series bool",
            "`ta.alma` argument `floor` expects simple bool-compatible, got series bool",
        ],
    );
}

#[test]
fn accepts_supported_numeric_cast_input_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_numeric_cast_input_return_qualifier.pine");
}

#[test]
fn reports_unsupported_numeric_cast_simple_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_numeric_cast_simple_return_qualifier.pine",
        &[
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`hline` argument `price` expects const/input numeric, got simple float",
        ],
    );
}

#[test]
fn accepts_supported_string_color_cast_input_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_string_color_cast_input_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_string_color_cast_simple_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_string_color_cast_simple_return_qualifier.pine",
        &[
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`hline` argument `color` expects const/input color, got simple color",
        ],
    );
}

#[test]
fn accepts_supported_value_helpers_same_as_arg_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_value_helpers_same_as_arg_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_value_helpers_simple_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_value_helpers_simple_return_qualifier.pine",
        &[
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`hline` argument `price` expects const/input numeric, got simple float",
            "`hline` argument `color` expects const/input color, got simple color",
        ],
    );
}

#[test]
fn accepts_supported_math_abs_same_as_arg_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_math_abs_same_as_arg_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_math_abs_simple_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_math_abs_simple_return_qualifier.pine",
        &[
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`hline` argument `price` expects const/input numeric, got simple float",
        ],
    );
}

#[test]
fn accepts_supported_math_rounding_input_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_math_rounding_input_return_qualifier.pine");
}

#[test]
fn reports_unsupported_math_rounding_simple_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_math_rounding_simple_return_qualifier.pine",
        &[
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`plot` argument `show_last` expects const/input int, got simple int",
        ],
    );
}

#[test]
fn accepts_supported_math_round_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_math_round_return_qualifier.pine");
}

#[test]
fn reports_unsupported_math_round_simple_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_math_round_simple_return_qualifier.pine",
        &[
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`hline` argument `price` expects const/input numeric, got simple float",
        ],
    );
}

#[test]
fn accepts_supported_math_unary_float_input_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_math_unary_float_input_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_math_unary_float_simple_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_math_unary_float_simple_return_qualifier.pine",
        &[
            "`hline` argument `price` expects const/input numeric, got simple float",
            "`hline` argument `price` expects const/input numeric, got simple float",
            "`hline` argument `price` expects const/input numeric, got simple float",
            "`hline` argument `price` expects const/input numeric, got simple float",
            "`hline` argument `price` expects const/input numeric, got simple float",
            "`hline` argument `price` expects const/input numeric, got simple float",
            "`hline` argument `price` expects const/input numeric, got simple float",
            "`hline` argument `price` expects const/input numeric, got simple float",
            "`hline` argument `price` expects const/input numeric, got simple float",
            "`hline` argument `price` expects const/input numeric, got simple float",
            "`hline` argument `price` expects const/input numeric, got simple float",
            "`hline` argument `price` expects const/input numeric, got simple float",
            "`hline` argument `price` expects const/input numeric, got simple float",
            "`hline` argument `price` expects const/input numeric, got simple float",
            "`hline` argument `price` expects const/input numeric, got simple float",
        ],
    );
}

#[test]
fn accepts_supported_color_rgb_numeric_compatible_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_color_rgb_numeric_compatible.pine");
}

#[test]
fn accepts_supported_color_rgb_input_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_color_rgb_input_return_qualifier.pine");
}

#[test]
fn reports_unsupported_color_rgb_simple_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_color_rgb_simple_return_qualifier.pine",
        &["`hline` argument `color` expects const/input color, got simple color"],
    );
}

#[test]
fn accepts_supported_color_component_input_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_color_component_input_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_color_component_simple_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_color_component_simple_return_qualifier.pine",
        &[
            "`hline` argument `price` expects const/input numeric, got simple float",
            "`hline` argument `price` expects const/input numeric, got simple float",
            "`hline` argument `price` expects const/input numeric, got simple float",
            "`hline` argument `price` expects const/input numeric, got simple float",
        ],
    );
}

#[test]
fn accepts_supported_color_new_na_transp_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_color_new_na_transp.pine");
}

#[test]
fn accepts_supported_color_new_input_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_color_new_input_return_qualifier.pine");
}

#[test]
fn reports_unsupported_color_new_series_transp_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_color_new_series_transp.pine",
        &["`color.new` argument `transp` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_color_new_simple_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_color_new_simple_return_qualifier.pine",
        &["`hline` argument `color` expects const/input color, got simple color"],
    );
}

#[test]
fn accepts_supported_color_from_gradient_numeric_compatible_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_color_from_gradient_numeric_compatible.pine",
    );
}

#[test]
fn accepts_supported_color_from_gradient_input_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_color_from_gradient_input_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_color_from_gradient_simple_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_color_from_gradient_simple_return_qualifier.pine",
        &["`hline` argument `color` expects const/input color, got simple color"],
    );
}

#[test]
fn accepts_supported_plot_input_linewidth_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_plot_input_linewidth.pine");
}

#[test]
fn reports_unsupported_plot_simple_linewidth_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_plot_simple_linewidth.pine",
        &["`plot` argument `linewidth` expects const/input int, got simple int"],
    );
}

#[test]
fn accepts_supported_plot_input_histbase_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_plot_input_histbase.pine");
}

#[test]
fn reports_unsupported_plot_series_histbase_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_plot_series_histbase.pine",
        &["`plot` argument `histbase` expects const/input numeric, got series float"],
    );
}

#[test]
fn reports_unsupported_plot_simple_histbase_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_plot_simple_histbase.pine",
        &["`plot` argument `histbase` expects const/input numeric, got simple int"],
    );
}

#[test]
fn accepts_supported_plot_input_show_last_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_plot_input_show_last.pine");
}

#[test]
fn reports_unsupported_plot_simple_show_last_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_plot_simple_show_last.pine",
        &["`plot` argument `show_last` expects const/input int, got simple int"],
    );
}

#[test]
fn accepts_supported_output_na_simple_int_params_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_output_na_simple_int_params.pine");
}

#[test]
fn reports_unsupported_output_series_simple_int_params_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_output_series_simple_int_params.pine",
        &[
            "`plot` argument `offset` expects simple integer-compatible, got series int",
            "`plot` argument `precision` expects simple integer-compatible, got series int",
            "`plotchar` argument `offset` expects simple integer-compatible, got series int",
            "`plotshape` argument `offset` expects simple integer-compatible, got series int",
            "`plotarrow` argument `offset` expects simple integer-compatible, got series int",
            "`plotarrow` argument `minheight` expects simple integer-compatible, got series int",
            "`plotarrow` argument `maxheight` expects simple integer-compatible, got series int",
            "`bgcolor` argument `offset` expects simple integer-compatible, got series int",
            "`barcolor` argument `offset` expects simple integer-compatible, got series int",
        ],
    );
}

#[test]
fn reports_unsupported_output_series_show_last_params_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_output_series_show_last_params.pine",
        &[
            "`plot` argument `show_last` expects const/input int, got series int",
            "`plotchar` argument `show_last` expects const/input int, got series int",
            "`plotshape` argument `show_last` expects const/input int, got series int",
            "`plotarrow` argument `show_last` expects const/input int, got series int",
            "`plotbar` argument `show_last` expects const/input int, got series int",
            "`plotcandle` argument `show_last` expects const/input int, got series int",
            "`fill` argument `show_last` expects const/input int, got series int",
            "`bgcolor` argument `show_last` expects const/input int, got series int",
            "`barcolor` argument `show_last` expects const/input int, got series int",
        ],
    );
}

#[test]
fn accepts_supported_plotchar_input_show_last_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_plotchar_input_show_last.pine");
}

#[test]
fn reports_unsupported_plotchar_simple_show_last_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_plotchar_simple_show_last.pine",
        &["`plotchar` argument `show_last` expects const/input int, got simple int"],
    );
}

#[test]
fn accepts_supported_plotshape_input_show_last_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_plotshape_input_show_last.pine");
}

#[test]
fn reports_unsupported_plotshape_simple_show_last_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_plotshape_simple_show_last.pine",
        &["`plotshape` argument `show_last` expects const/input int, got simple int"],
    );
}

#[test]
fn accepts_supported_plotarrow_input_show_last_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_plotarrow_input_show_last.pine");
}

#[test]
fn reports_unsupported_plotarrow_simple_show_last_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_plotarrow_simple_show_last.pine",
        &["`plotarrow` argument `show_last` expects const/input int, got simple int"],
    );
}

#[test]
fn accepts_supported_plotbar_input_show_last_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_plotbar_input_show_last.pine");
}

#[test]
fn reports_unsupported_plotbar_simple_show_last_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_plotbar_simple_show_last.pine",
        &["`plotbar` argument `show_last` expects const/input int, got simple int"],
    );
}

#[test]
fn accepts_supported_plotcandle_input_show_last_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_plotcandle_input_show_last.pine");
}

#[test]
fn reports_unsupported_plotcandle_simple_show_last_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_plotcandle_simple_show_last.pine",
        &["`plotcandle` argument `show_last` expects const/input int, got simple int"],
    );
}

#[test]
fn accepts_supported_fill_input_show_last_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_fill_input_show_last.pine");
}

#[test]
fn reports_unsupported_fill_simple_show_last_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_fill_simple_show_last.pine",
        &["`fill` argument `show_last` expects const/input int, got simple int"],
    );
}

#[test]
fn accepts_supported_bgcolor_input_show_last_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_bgcolor_input_show_last.pine");
}

#[test]
fn accepts_supported_barcolor_input_show_last_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_barcolor_input_show_last.pine");
}

#[test]
fn reports_unsupported_bgcolor_simple_show_last_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_bgcolor_simple_show_last.pine",
        &["`bgcolor` argument `show_last` expects const/input int, got simple int"],
    );
}

#[test]
fn reports_unsupported_barcolor_simple_show_last_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_barcolor_simple_show_last.pine",
        &["`barcolor` argument `show_last` expects const/input int, got simple int"],
    );
}

#[test]
fn reports_unsupported_fill_plot_source_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_fill_plot_source.pine",
        &["`fill` argument `plot1` expects plot/hline, got series float"],
    );
}

#[test]
fn accepts_supported_ta_sma_simple_length_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_ta_sma_simple_length.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "ta.sma"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn reports_unsupported_ta_sma_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_sma_length.pine",
        &["`ta.sma` argument `length` expects integer-compatible, got const float"],
    );
}

#[test]
fn accepts_supported_ta_sma_series_length_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_sma_series_length.pine");
}

#[test]
fn reports_unsupported_ta_sma_const_source_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_sma_const_source.pine",
        &["`ta.sma` argument `source` expects series numeric, got const int"],
    );
}

#[test]
fn reports_unsupported_ta_ema_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_ema_length.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got const float"],
    );
}

#[test]
fn reports_unsupported_ta_ema_series_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_ema_series_length.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_ta_dema_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_dema_length.pine",
        &["`ta.dema` argument `length` expects simple integer-compatible, got const float"],
    );
}

#[test]
fn reports_unsupported_ta_dema_series_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_dema_series_length.pine",
        &["`ta.dema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_ta_tema_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_tema_length.pine",
        &["`ta.tema` argument `length` expects simple integer-compatible, got const float"],
    );
}

#[test]
fn reports_unsupported_ta_tema_series_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_tema_series_length.pine",
        &["`ta.tema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_ta_rma_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_rma_length.pine",
        &["`ta.rma` argument `length` expects simple integer-compatible, got const float"],
    );
}

#[test]
fn reports_unsupported_ta_rma_series_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_rma_series_length.pine",
        &["`ta.rma` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_ta_rsi_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_rsi_length.pine",
        &["`ta.rsi` argument `length` expects simple integer-compatible, got const float"],
    );
}

#[test]
fn reports_unsupported_ta_rsi_series_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_rsi_series_length.pine",
        &["`ta.rsi` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn accepts_supported_ta_rci_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_rci_return_qualifier.pine");
}

#[test]
fn reports_unsupported_ta_rci_args_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_rci_args.pine",
        &[
            "`ta.rci` argument `source` expects series/simple numeric, got const string",
            "`ta.rci` argument `length` expects simple integer-compatible, got const float",
            "`ta.rci` argument `length` expects simple integer-compatible, got series int",
        ],
    );
}

#[test]
fn reports_unsupported_ta_rci_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_rci_return_qualifier.pine",
        &["`hline` argument `price` expects const/input numeric, got series float"],
    );
}

#[test]
fn accepts_supported_ta_ema_family_na_lengths_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_ema_family_na_lengths.pine");
}

#[test]
fn accepts_supported_ta_average_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_average_return_qualifier.pine");
}

#[test]
fn reports_unsupported_ta_average_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_average_return_qualifier.pine",
        &[
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
        ],
    );
}

#[test]
fn reports_unsupported_ta_macd_fastlen_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_macd_fastlen.pine",
        &["`ta.macd` argument `fastlen` expects simple integer-compatible, got const float"],
    );
}

#[test]
fn reports_unsupported_ta_macd_slowlen_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_macd_slowlen.pine",
        &["`ta.macd` argument `slowlen` expects simple integer-compatible, got const float"],
    );
}

#[test]
fn reports_unsupported_ta_macd_siglen_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_macd_siglen.pine",
        &["`ta.macd` argument `siglen` expects simple integer-compatible, got const float"],
    );
}

#[test]
fn accepts_supported_ta_macd_na_lengths_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_macd_na_lengths.pine");
}

#[test]
fn accepts_supported_ta_macd_tuple_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_macd_tuple_return_qualifier.pine");
}

#[test]
fn reports_unsupported_ta_macd_tuple_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_macd_tuple_return_qualifier.pine",
        &[
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
        ],
    );
}

#[test]
fn reports_unsupported_ta_alma_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_alma_length.pine",
        &["`ta.alma` argument `length` expects integer-compatible, got const float"],
    );
}

#[test]
fn accepts_supported_ta_alma_linreg_series_length_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_alma_linreg_series_length.pine");
}

#[test]
fn reports_unsupported_ta_alma_offset_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_alma_offset.pine",
        &["`ta.alma` argument `offset` expects simple numeric-compatible, got const bool"],
    );
}

#[test]
fn reports_unsupported_ta_alma_series_offset_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_alma_series_offset.pine",
        &["`ta.alma` argument `offset` expects simple numeric-compatible, got series float"],
    );
}

#[test]
fn reports_unsupported_ta_alma_sigma_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_alma_sigma.pine",
        &["`ta.alma` argument `sigma` expects simple numeric-compatible, got const bool"],
    );
}

#[test]
fn reports_unsupported_ta_alma_series_sigma_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_alma_series_sigma.pine",
        &["`ta.alma` argument `sigma` expects simple numeric-compatible, got series float"],
    );
}

#[test]
fn accepts_supported_ta_alma_na_offset_sigma_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_alma_na_offset_sigma.pine");
}

#[test]
fn accepts_supported_ta_alma_na_floor_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_alma_na_floor.pine");
}

#[test]
fn accepts_supported_ta_alma_simple_floor_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_ta_alma_simple_floor.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "ta.alma"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_ta_alma_input_floor_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_ta_alma_input_floor.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "ta.alma"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn reports_unsupported_ta_alma_floor_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_alma_floor.pine",
        &["`ta.alma` argument `floor` expects simple bool-compatible, got const int"],
    );
}

#[test]
fn reports_unsupported_ta_alma_series_floor_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_alma_series_floor.pine",
        &["`ta.alma` argument `floor` expects simple bool-compatible, got series bool"],
    );
}

#[test]
fn reports_unsupported_ta_bb_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_bb_length.pine",
        &["`ta.bb` argument `length` expects integer-compatible, got const float"],
    );
}

#[test]
fn accepts_supported_ta_bollinger_series_length_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_bollinger_series_length.pine");
}

#[test]
fn accepts_supported_ta_bollinger_na_mult_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_bollinger_na_mult.pine");
}

#[test]
fn reports_unsupported_ta_bb_mult_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_bb_mult.pine",
        &["`ta.bb` argument `mult` expects numeric-compatible, got const string"],
    );
}

#[test]
fn reports_unsupported_ta_bbw_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_bbw_length.pine",
        &["`ta.bbw` argument `length` expects integer-compatible, got const float"],
    );
}

#[test]
fn reports_unsupported_ta_bbw_mult_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_bbw_mult.pine",
        &["`ta.bbw` argument `mult` expects numeric-compatible, got const string"],
    );
}

#[test]
fn accepts_supported_ta_channel_tuple_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_channel_tuple_return_qualifier.pine");
}

#[test]
fn reports_unsupported_ta_channel_tuple_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_channel_tuple_return_qualifier.pine",
        &[
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
        ],
    );
}

#[test]
fn accepts_supported_ta_width_dispersion_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_width_dispersion_return_qualifier.pine");
}

#[test]
fn reports_unsupported_ta_width_dispersion_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_width_dispersion_return_qualifier.pine",
        &[
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
        ],
    );
}

#[test]
fn accepts_supported_ta_vwap_na_stdev_mult_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_vwap_na_stdev_mult.pine");
}

#[test]
fn reports_unsupported_ta_vwap_series_stdev_mult_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_vwap_series_stdev_mult.pine",
        &["`ta.vwap` argument `stdev_mult` expects simple numeric-compatible, got series float"],
    );
}

#[test]
fn accepts_supported_ta_vwap_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_vwap_return_qualifier.pine");
}

#[test]
fn reports_unsupported_ta_vwap_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_vwap_return_qualifier.pine",
        &[
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
        ],
    );
}

#[test]
fn accepts_supported_ta_kc_simple_mult_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_ta_kc_simple_mult.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    for feature in ["ta.kc", "ta.kcw"] {
        assert!(
            analysis
                .compatibility
                .supported
                .iter()
                .any(|supported| supported.feature == feature),
            "{} supported features: {:?}",
            path.display(),
            analysis.compatibility.supported
        );
    }
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_ta_kc_input_mult_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_ta_kc_input_mult.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    for feature in ["ta.kc", "ta.kcw"] {
        assert!(
            analysis
                .compatibility
                .supported
                .iter()
                .any(|supported| supported.feature == feature),
            "{} supported features: {:?}",
            path.display(),
            analysis.compatibility.supported
        );
    }
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_ta_kc_na_mult_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_kc_na_mult.pine");
}

#[test]
fn reports_unsupported_ta_kc_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_kc_length.pine",
        &["`ta.kc` argument `length` expects integer-compatible, got const float"],
    );
}

#[test]
fn accepts_supported_ta_kc_series_length_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_kc_series_length.pine");
}

#[test]
fn reports_unsupported_ta_kc_mult_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_kc_mult.pine",
        &["`ta.kc` argument `mult` expects simple numeric-compatible, got series float"],
    );
}

#[test]
fn reports_unsupported_ta_kc_use_true_range_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_kc_use_true_range.pine",
        &["`ta.kc` argument `useTrueRange` expects bool-compatible, got const string"],
    );
}

#[test]
fn reports_unsupported_ta_kcw_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_kcw_length.pine",
        &["`ta.kcw` argument `length` expects integer-compatible, got const float"],
    );
}

#[test]
fn reports_unsupported_ta_kcw_mult_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_kcw_mult.pine",
        &["`ta.kcw` argument `mult` expects simple numeric-compatible, got series float"],
    );
}

#[test]
fn reports_unsupported_ta_kcw_use_true_range_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_kcw_use_true_range.pine",
        &["`ta.kcw` argument `useTrueRange` expects bool-compatible, got const string"],
    );
}

#[test]
fn reports_unsupported_ta_dmi_di_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_dmi_di_length.pine",
        &["`ta.dmi` argument `diLength` expects simple integer-compatible, got const float"],
    );
}

#[test]
fn reports_unsupported_ta_dmi_series_di_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_dmi_series_di_length.pine",
        &["`ta.dmi` argument `diLength` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_ta_dmi_adx_smoothing_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_dmi_adx_smoothing.pine",
        &["`ta.dmi` argument `adxSmoothing` expects simple integer-compatible, got const float"],
    );
}

#[test]
fn reports_unsupported_ta_dmi_series_adx_smoothing_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_dmi_series_adx_smoothing.pine",
        &["`ta.dmi` argument `adxSmoothing` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn accepts_supported_ta_dmi_na_lengths_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_dmi_na_lengths.pine");
}

#[test]
fn accepts_supported_ta_dmi_tuple_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_dmi_tuple_return_qualifier.pine");
}

#[test]
fn reports_unsupported_ta_dmi_tuple_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_dmi_tuple_return_qualifier.pine",
        &[
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
        ],
    );
}

#[test]
fn reports_unsupported_ta_tsi_short_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_tsi_short_length.pine",
        &["`ta.tsi` argument `short_length` expects simple integer-compatible, got const float"],
    );
}

#[test]
fn reports_unsupported_ta_tsi_series_short_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_tsi_series_short_length.pine",
        &["`ta.tsi` argument `short_length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_ta_tsi_long_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_tsi_long_length.pine",
        &["`ta.tsi` argument `long_length` expects simple integer-compatible, got const float"],
    );
}

#[test]
fn reports_unsupported_ta_tsi_series_long_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_tsi_series_long_length.pine",
        &["`ta.tsi` argument `long_length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn accepts_supported_ta_tsi_na_lengths_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_tsi_na_lengths.pine");
}

#[test]
fn accepts_supported_ta_flow_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_flow_return_qualifier.pine");
}

#[test]
fn reports_unsupported_ta_flow_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_flow_return_qualifier.pine",
        &[
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
        ],
    );
}

#[test]
fn reports_unsupported_ta_atr_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_atr_length.pine",
        &["`ta.atr` argument `length` expects simple integer-compatible, got const float"],
    );
}

#[test]
fn reports_unsupported_ta_atr_series_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_atr_series_length.pine",
        &["`ta.atr` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn accepts_supported_ta_atr_na_length_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_atr_na_length.pine");
}

#[test]
fn accepts_supported_ta_volatility_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_volatility_return_qualifier.pine");
}

#[test]
fn reports_unsupported_ta_volatility_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_volatility_return_qualifier.pine",
        &[
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
        ],
    );
}

#[test]
fn reports_unsupported_ta_cci_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_cci_length.pine",
        &["`ta.cci` argument `length` expects integer-compatible, got const float"],
    );
}

#[test]
fn accepts_supported_ta_flow_series_length_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_flow_series_length.pine");
}

#[test]
fn reports_unsupported_ta_cmo_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_cmo_length.pine",
        &["`ta.cmo` argument `length` expects integer-compatible, got const float"],
    );
}

#[test]
fn reports_unsupported_ta_cog_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_cog_length.pine",
        &["`ta.cog` argument `length` expects integer-compatible, got const float"],
    );
}

#[test]
fn reports_unsupported_ta_dev_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_dev_length.pine",
        &["`ta.dev` argument `length` expects integer-compatible, got const float"],
    );
}

#[test]
fn accepts_supported_ta_range_dev_series_length_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_range_dev_series_length.pine");
}

#[test]
fn reports_unsupported_ta_median_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_median_length.pine",
        &["`ta.median` argument `length` expects integer-compatible, got const float"],
    );
}

#[test]
fn accepts_supported_ta_distribution_series_length_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_distribution_series_length.pine");
}

#[test]
fn accepts_supported_ta_distribution_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_distribution_return_qualifier.pine");
}

#[test]
fn reports_unsupported_ta_distribution_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_distribution_return_qualifier.pine",
        &[
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
        ],
    );
}

#[test]
fn reports_unsupported_ta_mfi_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_mfi_length.pine",
        &["`ta.mfi` argument `length` expects integer-compatible, got const float"],
    );
}

#[test]
fn accepts_supported_ta_oscillator_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_oscillator_return_qualifier.pine");
}

#[test]
fn reports_unsupported_ta_oscillator_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_oscillator_return_qualifier.pine",
        &[
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
        ],
    );
}

#[test]
fn reports_unsupported_ta_mode_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_mode_length.pine",
        &["`ta.mode` argument `length` expects integer-compatible, got const float"],
    );
}

#[test]
fn reports_unsupported_ta_mom_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_mom_length.pine",
        &["`ta.mom` argument `length` expects integer-compatible, got const float"],
    );
}

#[test]
fn accepts_supported_ta_momentum_series_length_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_momentum_series_length.pine");
}

#[test]
fn accepts_supported_ta_momentum_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_momentum_return_qualifier.pine");
}

#[test]
fn reports_unsupported_ta_momentum_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_momentum_return_qualifier.pine",
        &[
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
        ],
    );
}

#[test]
fn accepts_supported_ta_extreme_window_history_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_extreme_window_history.pine");
}

#[test]
fn accepts_supported_ta_extreme_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_extreme_return_qualifier.pine");
}

#[test]
fn reports_unsupported_ta_extreme_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_extreme_return_qualifier.pine",
        &[
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`plot` argument `offset` expects simple integer-compatible, got series int",
            "`plot` argument `offset` expects simple integer-compatible, got series int",
        ],
    );
}

#[test]
fn accepts_supported_ta_named_reordered_history_metadata_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_named_reordered_history_metadata.pine");
}

#[test]
fn reports_unsupported_ta_highest_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_highest_length.pine",
        &["`ta.highest` argument `length` expects integer-compatible, got const float"],
    );
}

#[test]
fn accepts_supported_ta_extreme_series_length_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_extreme_series_length.pine");
}

#[test]
fn reports_unsupported_ta_highest_source_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_highest_source.pine",
        &["`ta.highest` argument `source` expects series numeric, got const string"],
    );
}

#[test]
fn reports_unsupported_ta_highest_default_source_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_highest_default_source_length.pine",
        &["`ta.highest` argument `length` expects integer-compatible, got series float"],
    );
}

#[test]
fn reports_unsupported_ta_lowest_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_lowest_length.pine",
        &["`ta.lowest` argument `length` expects integer-compatible, got const float"],
    );
}

#[test]
fn reports_unsupported_ta_lowest_source_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_lowest_source.pine",
        &["`ta.lowest` argument `source` expects series numeric, got const string"],
    );
}

#[test]
fn accepts_supported_ta_pivot_series_bars_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_ta_pivot_series_bars.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "expected fixture to analyze cleanly, got {:?}",
        analysis.diagnostics
    );
}

#[test]
fn reports_unsupported_ta_max_source_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_max_source.pine",
        &["`ta.max` argument `source` expects series/simple numeric, got const bool"],
    );
}

#[test]
fn reports_unsupported_ta_min_source_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_min_source.pine",
        &["`ta.min` argument `source` expects series/simple numeric, got const bool"],
    );
}

#[test]
fn accepts_supported_ta_running_extreme_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_running_extreme_return_qualifier.pine");
}

#[test]
fn reports_unsupported_ta_running_extreme_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_running_extreme_return_qualifier.pine",
        &[
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
        ],
    );
}

#[test]
fn reports_unsupported_ta_pivothigh_default_leftbars_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_pivothigh_default_leftbars.pine",
        &["`ta.pivothigh` argument `leftbars` expects integer-compatible, got const float"],
    );
}

#[test]
fn reports_unsupported_ta_pivotlow_default_rightbars_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_pivotlow_default_rightbars.pine",
        &["`ta.pivotlow` argument `rightbars` expects integer-compatible, got const float"],
    );
}

#[test]
fn reports_unsupported_ta_highestbars_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_highestbars_length.pine",
        &["`ta.highestbars` argument `length` expects integer-compatible, got const float"],
    );
}

#[test]
fn reports_unsupported_ta_highestbars_source_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_highestbars_source.pine",
        &["`ta.highestbars` argument `source` expects series numeric, got const string"],
    );
}

#[test]
fn reports_unsupported_ta_lowestbars_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_lowestbars_length.pine",
        &["`ta.lowestbars` argument `length` expects integer-compatible, got const float"],
    );
}

#[test]
fn reports_unsupported_ta_lowestbars_source_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_lowestbars_source.pine",
        &["`ta.lowestbars` argument `source` expects series numeric, got const string"],
    );
}

#[test]
fn reports_unsupported_ta_falling_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_falling_length.pine",
        &["`ta.falling` argument `length` expects integer-compatible, got const float"],
    );
}

#[test]
fn reports_unsupported_ta_rising_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_rising_length.pine",
        &["`ta.rising` argument `length` expects integer-compatible, got const float"],
    );
}

#[test]
fn accepts_supported_ta_trend_series_length_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_trend_series_length.pine");
}

#[test]
fn accepts_supported_ta_trend_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_trend_return_qualifier.pine");
}

#[test]
fn reports_unsupported_ta_trend_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_trend_return_qualifier.pine",
        &[
            "`ta.alma` argument `floor` expects simple bool-compatible, got series bool",
            "`ta.alma` argument `floor` expects simple bool-compatible, got series bool",
        ],
    );
}

#[test]
fn accepts_supported_ta_trend_window_history_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_trend_window_history.pine");
}

#[test]
fn reports_unsupported_ta_range_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_range_length.pine",
        &["`ta.range` argument `length` expects integer-compatible, got const float"],
    );
}

#[test]
fn reports_unsupported_ta_roc_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_roc_length.pine",
        &["`ta.roc` argument `length` expects integer-compatible, got const float"],
    );
}

#[test]
fn reports_unsupported_ta_vwma_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_vwma_length.pine",
        &["`ta.vwma` argument `length` expects integer-compatible, got const float"],
    );
}

#[test]
fn accepts_supported_ta_weighted_averages_series_length_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_weighted_averages_series_length.pine");
}

#[test]
fn accepts_supported_ta_weighted_regression_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_ta_weighted_regression_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_ta_weighted_regression_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_weighted_regression_return_qualifier.pine",
        &[
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
        ],
    );
}

#[test]
fn reports_unsupported_ta_wma_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_wma_length.pine",
        &["`ta.wma` argument `length` expects integer-compatible, got const float"],
    );
}

#[test]
fn reports_unsupported_ta_hma_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_hma_length.pine",
        &["`ta.hma` argument `length` expects integer-compatible, got const float"],
    );
}

#[test]
fn reports_unsupported_ta_wpr_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_wpr_length.pine",
        &["`ta.wpr` argument `length` expects integer-compatible, got const float"],
    );
}

#[test]
fn accepts_supported_ta_stoch_wpr_series_length_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_stoch_wpr_series_length.pine");
}

#[test]
fn reports_unsupported_ta_correlation_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_correlation_length.pine",
        &["`ta.correlation` argument `length` expects integer-compatible, got const float"],
    );
}

#[test]
fn accepts_supported_ta_statistics_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_statistics_return_qualifier.pine");
}

#[test]
fn reports_unsupported_ta_statistics_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_statistics_return_qualifier.pine",
        &[
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
        ],
    );
}

#[test]
fn accepts_supported_ta_pairwise_series_length_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_pairwise_series_length.pine");
}

#[test]
fn reports_unsupported_ta_covariance_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_covariance_length.pine",
        &["`ta.covariance` argument `length` expects integer-compatible, got const float"],
    );
}

#[test]
fn reports_unsupported_ta_linreg_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_linreg_length.pine",
        &["`ta.linreg` argument `length` expects integer-compatible, got const float"],
    );
}

#[test]
fn reports_unsupported_ta_linreg_offset_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_linreg_offset.pine",
        &["`ta.linreg` argument `offset` expects simple integer-compatible, got const float"],
    );
}

#[test]
fn reports_unsupported_ta_linreg_series_offset_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_linreg_series_offset.pine",
        &["`ta.linreg` argument `offset` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn accepts_supported_ta_linreg_na_offset_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_linreg_na_offset.pine");
}

#[test]
fn accepts_supported_ta_percentile_input_percentage_fixture() {
    let path =
        workspace_fixture("tests/fixtures/sema/supported_ta_percentile_input_percentage.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    for feature in [
        "ta.percentile_nearest_rank",
        "ta.percentile_linear_interpolation",
    ] {
        assert!(
            analysis
                .compatibility
                .supported
                .iter()
                .any(|supported| supported.feature == feature),
            "{} supported features: {:?}",
            path.display(),
            analysis.compatibility.supported
        );
    }
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_ta_percentile_simple_percentage_fixture() {
    let path =
        workspace_fixture("tests/fixtures/sema/supported_ta_percentile_simple_percentage.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    for feature in [
        "ta.percentile_nearest_rank",
        "ta.percentile_linear_interpolation",
    ] {
        assert!(
            analysis
                .compatibility
                .supported
                .iter()
                .any(|supported| supported.feature == feature),
            "{} supported features: {:?}",
            path.display(),
            analysis.compatibility.supported
        );
    }
    assert!(analysis.hir.is_some());
}

#[test]
fn reports_unsupported_ta_percentile_linear_interpolation_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_percentile_linear_interpolation_length.pine",
        &[
            "`ta.percentile_linear_interpolation` argument `length` expects integer-compatible, got const float",
        ],
    );
}

#[test]
fn accepts_supported_ta_percentile_series_length_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_percentile_series_length.pine");
}

#[test]
fn reports_unsupported_ta_percentile_linear_interpolation_percentage_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_percentile_linear_interpolation_percentage.pine",
        &[
            "`ta.percentile_linear_interpolation` argument `percentage` expects simple numeric-compatible, got const string",
        ],
    );
}

#[test]
fn reports_unsupported_ta_percentile_linear_interpolation_series_percentage_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_percentile_linear_interpolation_series_percentage.pine",
        &[
            "`ta.percentile_linear_interpolation` argument `percentage` expects simple numeric-compatible, got series float",
        ],
    );
}

#[test]
fn reports_unsupported_ta_percentile_nearest_rank_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_percentile_nearest_rank_length.pine",
        &[
            "`ta.percentile_nearest_rank` argument `length` expects integer-compatible, got const float",
        ],
    );
}

#[test]
fn reports_unsupported_ta_percentile_nearest_rank_percentage_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_percentile_nearest_rank_percentage.pine",
        &[
            "`ta.percentile_nearest_rank` argument `percentage` expects simple numeric-compatible, got const string",
        ],
    );
}

#[test]
fn reports_unsupported_ta_percentile_nearest_rank_series_percentage_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_percentile_nearest_rank_series_percentage.pine",
        &[
            "`ta.percentile_nearest_rank` argument `percentage` expects simple numeric-compatible, got series float",
        ],
    );
}

#[test]
fn accepts_supported_ta_percentile_na_percentage_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_percentile_na_percentage.pine");
}

#[test]
fn reports_unsupported_ta_percentrank_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_percentrank_length.pine",
        &["`ta.percentrank` argument `length` expects integer-compatible, got const float"],
    );
}

#[test]
fn reports_unsupported_ta_stdev_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_stdev_length.pine",
        &["`ta.stdev` argument `length` expects integer-compatible, got const float"],
    );
}

#[test]
fn accepts_supported_ta_stdev_variance_series_length_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_stdev_variance_series_length.pine");
}

#[test]
fn reports_unsupported_ta_stdev_biased_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_stdev_biased.pine",
        &["`ta.stdev` argument `biased` expects bool-compatible, got const int"],
    );
}

#[test]
fn reports_unsupported_ta_variance_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_variance_length.pine",
        &["`ta.variance` argument `length` expects integer-compatible, got const float"],
    );
}

#[test]
fn reports_unsupported_ta_variance_biased_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_variance_biased.pine",
        &["`ta.variance` argument `biased` expects bool-compatible, got const int"],
    );
}

#[test]
fn reports_unsupported_ta_stoch_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_stoch_length.pine",
        &["`ta.stoch` argument `length` expects integer-compatible, got const float"],
    );
}

#[test]
fn reports_unsupported_ta_supertrend_factor_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_supertrend_factor.pine",
        &["`ta.supertrend` argument `factor` expects simple numeric-compatible, got const string"],
    );
}

#[test]
fn reports_unsupported_ta_supertrend_series_factor_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_supertrend_series_factor.pine",
        &["`ta.supertrend` argument `factor` expects simple numeric-compatible, got series float"],
    );
}

#[test]
fn accepts_supported_ta_supertrend_na_factor_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_supertrend_na_factor.pine");
}

#[test]
fn reports_unsupported_ta_supertrend_atr_period_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_supertrend_atr_period.pine",
        &[
            "`ta.supertrend` argument `atrPeriod` expects simple integer-compatible, got const float",
        ],
    );
}

#[test]
fn reports_unsupported_ta_supertrend_series_atr_period_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_supertrend_series_atr_period.pine",
        &["`ta.supertrend` argument `atrPeriod` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn accepts_supported_ta_supertrend_na_atr_period_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_supertrend_na_atr_period.pine");
}

#[test]
fn accepts_supported_ta_supertrend_tuple_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_supertrend_tuple_return_qualifier.pine");
}

#[test]
fn reports_unsupported_ta_supertrend_tuple_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_supertrend_tuple_return_qualifier.pine",
        &[
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
        ],
    );
}

#[test]
fn reports_unsupported_ta_barssince_condition_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_barssince_condition.pine",
        &["`ta.barssince` argument `condition` expects bool-compatible, got const string"],
    );
}

#[test]
fn accepts_supported_ta_barssince_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_barssince_return_qualifier.pine");
}

#[test]
fn reports_unsupported_ta_barssince_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_barssince_return_qualifier.pine",
        &["`plot` argument `offset` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_ta_change_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_change_length.pine",
        &["`ta.change` argument `length` expects integer-compatible, got const float"],
    );
}

#[test]
fn accepts_supported_ta_change_series_length_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_change_series_length.pine");
}

#[test]
fn accepts_supported_ta_change_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_change_return_qualifier.pine");
}

#[test]
fn reports_unsupported_ta_change_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_change_return_qualifier.pine",
        &[
            "`hline` argument `price` expects const/input numeric, got series float",
            "`ta.alma` argument `floor` expects simple bool-compatible, got series bool",
        ],
    );
}

#[test]
fn reports_unsupported_ta_sar_start_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_sar_start.pine",
        &["`ta.sar` argument `start` expects simple numeric-compatible, got const string"],
    );
}

#[test]
fn reports_unsupported_ta_sar_series_start_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_sar_series_start.pine",
        &["`ta.sar` argument `start` expects simple numeric-compatible, got series float"],
    );
}

#[test]
fn reports_unsupported_ta_sar_inc_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_sar_inc.pine",
        &["`ta.sar` argument `inc` expects simple numeric-compatible, got const string"],
    );
}

#[test]
fn reports_unsupported_ta_sar_series_inc_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_sar_series_inc.pine",
        &["`ta.sar` argument `inc` expects simple numeric-compatible, got series float"],
    );
}

#[test]
fn reports_unsupported_ta_sar_max_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_sar_max.pine",
        &["`ta.sar` argument `max` expects simple numeric-compatible, got const string"],
    );
}

#[test]
fn reports_unsupported_ta_sar_series_max_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_sar_series_max.pine",
        &["`ta.sar` argument `max` expects simple numeric-compatible, got series float"],
    );
}

#[test]
fn accepts_supported_ta_sar_na_params_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_sar_na_params.pine");
}

#[test]
fn reports_unsupported_ta_tr_handle_na_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_tr_handle_na.pine",
        &["`ta.tr` argument `handle_na` expects const bool, got const string"],
    );
}

#[test]
fn reports_unsupported_ta_valuewhen_condition_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_valuewhen_condition.pine",
        &["`ta.valuewhen` argument `condition` expects bool-compatible, got const string"],
    );
}

#[test]
fn reports_unsupported_ta_valuewhen_source_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_valuewhen_source.pine",
        &[
            "`ta.valuewhen` argument `source` expects numeric/bool/color-compatible, got const string",
        ],
    );
}

#[test]
fn reports_unsupported_ta_valuewhen_occurrence_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_valuewhen_occurrence.pine",
        &["`ta.valuewhen` argument `occurrence` expects integer-compatible, got const float"],
    );
}

#[test]
fn accepts_supported_ta_valuewhen_series_occurrence_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_valuewhen_series_occurrence.pine");
}

#[test]
fn accepts_supported_ta_valuewhen_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_valuewhen_return_qualifier.pine");
}

#[test]
fn reports_unsupported_ta_valuewhen_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_valuewhen_return_qualifier.pine",
        &[
            "`plot` argument `offset` expects simple integer-compatible, got series int",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`ta.alma` argument `floor` expects simple bool-compatible, got series bool",
            "`hline` argument `color` expects const/input color, got series color",
        ],
    );
}

#[test]
fn reports_unsupported_ta_accdist_call_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_accdist_call.pine",
        &["unknown function `ta.accdist`"],
    );
}

#[test]
fn reports_unsupported_ta_ao_arguments_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_ao_arguments.pine",
        &["`ta.ao` expects at most 0 argument(s), got 1"],
    );
}

#[test]
fn accepts_supported_ta_zero_arg_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_zero_arg_return_qualifier.pine");
}

#[test]
fn reports_unsupported_ta_bop_arguments_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_bop_arguments.pine",
        &["`ta.bop` expects at most 0 argument(s), got 1"],
    );
}

#[test]
fn reports_unsupported_ta_zero_arg_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_zero_arg_return_qualifier.pine",
        &[
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
        ],
    );
}

#[test]
fn reports_unsupported_ta_cum_source_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_cum_source.pine",
        &["`ta.cum` argument `source` expects series/simple numeric, got const bool"],
    );
}

#[test]
fn reports_unsupported_ta_cross_source_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_cross_source.pine",
        &["`ta.cross` argument `source2` expects series/simple numeric, got const string"],
    );
}

#[test]
fn accepts_supported_ta_cross_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_cross_return_qualifier.pine");
}

#[test]
fn reports_unsupported_ta_cross_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_cross_return_qualifier.pine",
        &[
            "`ta.alma` argument `floor` expects simple bool-compatible, got series bool",
            "`ta.alma` argument `floor` expects simple bool-compatible, got series bool",
            "`ta.alma` argument `floor` expects simple bool-compatible, got series bool",
        ],
    );
}

#[test]
fn reports_unsupported_ta_crossover_source_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_crossover_source.pine",
        &["`ta.crossover` argument `source2` expects series/simple numeric, got const string"],
    );
}

#[test]
fn reports_unsupported_ta_crossunder_source_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_crossunder_source.pine",
        &["`ta.crossunder` argument `source2` expects series/simple numeric, got const string"],
    );
}

#[test]
fn reports_unsupported_ta_iii_call_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_iii_call.pine",
        &["unknown function `ta.iii`"],
    );
}

#[test]
fn reports_unsupported_ta_nvi_call_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_nvi_call.pine",
        &["unknown function `ta.nvi`"],
    );
}

#[test]
fn reports_unsupported_ta_obv_call_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_obv_call.pine",
        &["unknown function `ta.obv`"],
    );
}

#[test]
fn reports_unsupported_ta_pvi_call_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_pvi_call.pine",
        &["unknown function `ta.pvi`"],
    );
}

#[test]
fn reports_unsupported_ta_pvt_call_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_pvt_call.pine",
        &["unknown function `ta.pvt`"],
    );
}

#[test]
fn reports_unsupported_ta_wad_call_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_wad_call.pine",
        &["unknown function `ta.wad`"],
    );
}

#[test]
fn reports_unsupported_ta_wvad_call_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_wvad_call.pine",
        &["unknown function `ta.wvad`"],
    );
}

#[test]
fn accepts_supported_ta_volume_variable_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ta_volume_variable_return_qualifier.pine");
}

#[test]
fn reports_unsupported_ta_volume_variable_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ta_volume_variable_return_qualifier.pine",
        &[
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
        ],
    );
}

#[test]
fn reports_unsupported_varip_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/unsupported_varip.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert_eq!(analysis.compatibility.unsupported.len(), 1);
    assert_eq!(analysis.compatibility.unsupported[0].feature, "varip");
    assert!(
        analysis.compatibility.unsupported[0]
            .reason
            .contains("tuples")
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn reports_unsupported_varip_drawing_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/unsupported_varip_drawing.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert_eq!(analysis.compatibility.unsupported.len(), 1);
    assert_eq!(analysis.compatibility.unsupported[0].feature, "varip");
    assert!(
        analysis.compatibility.unsupported[0]
            .reason
            .contains("drawing object ids")
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn accepts_supported_varip_chart_point_array_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/varip_chart_point_array.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(analysis.hir.is_some());
    assert_eq!(
        analysis
            .compatibility
            .supported
            .iter()
            .filter(|supported| supported.feature == "varip")
            .count(),
        2
    );
}

#[test]
fn reports_unsupported_varip_drawing_array_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_varip_drawing_array.pine",
        "varip",
        "drawing ids, tuples",
    );
}

#[test]
fn accepts_supported_varip_user_type_array_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_user_type_array_varip_decl.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "varip"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_varip_user_type_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_user_type_varip_decl.pine");
}

#[test]
fn accepts_supported_user_type_history_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_user_type_history.pine");
}

#[test]
fn accepts_supported_user_type_history_non_scalar_typed_na_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_user_type_history_non_scalar_typed_na.pine",
    );
}

#[test]
fn reports_unsupported_user_type_varip_non_scalar_reassign_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_user_type_varip_non_scalar_reassign.pine",
        "varip",
        "non-scalar UDT varip values can only remain `na`",
    );
}

#[test]
fn reports_unsupported_user_type_varip_non_scalar_field_reassign_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_user_type_varip_non_scalar_field_reassign.pine",
        "varip",
        "non-scalar UDT varip values can only remain `na`",
    );
}

#[test]
fn accepts_supported_user_type_history_non_scalar_constructed_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_user_type_history_non_scalar_constructed.pine",
    );
}

#[test]
fn accepts_supported_user_type_field_non_scalar_typed_na_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_user_type_field_non_scalar_typed_na.pine");
}

#[test]
fn accepts_supported_varip_user_type_array_nested_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_user_type_array_varip_nested_decl.pine");
}

#[test]
fn reports_unsupported_udt_array_chained_field_mutation_udf_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_udt_array_chained_field_mutation_udf.pine",
        "function_side_effect",
        "user-defined type array fields",
    );
}

#[test]
fn reports_unsupported_udt_array_chained_field_mutation_index_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_udt_array_chained_field_mutation_index.pine",
        &["`array.get` argument `index` expects simple integer-compatible, got const string"],
    );
}

#[test]
fn reports_unsupported_udt_array_chained_field_mutation_series_index_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_udt_array_chained_field_mutation_series_index.pine",
        &["`array.get` argument `index` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_strategy_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_strategy.pine",
        "E_STRATEGY_MODE",
    );
}

#[test]
fn accepts_supported_strategy_declaration_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_strategy_declaration.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "strategy"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    let hir = analysis.hir.expect("strategy declaration should lower");
    assert_eq!(hir.script_mode, pine_ir::ScriptMode::Strategy);
}

#[test]
fn accepts_supported_strategy_pyramiding_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_strategy_pyramiding.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    let hir = analysis.hir.expect("strategy declaration should lower");
    assert_eq!(hir.strategy_settings.pyramiding_limit, 2);
}

#[test]
fn accepts_supported_strategy_close_entries_rule_fifo_fixture() {
    let path =
        workspace_fixture("tests/fixtures/sema/supported_strategy_close_entries_rule_fifo.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    let hir = analysis.hir.expect("strategy declaration should lower");
    assert_eq!(
        hir.strategy_settings.close_entries_rule,
        pine_ir::StrategyCloseEntriesRule::Fifo
    );
}

#[test]
fn accepts_supported_strategy_close_entries_rule_any_fixture() {
    let path =
        workspace_fixture("tests/fixtures/sema/supported_strategy_close_entries_rule_any.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    let hir = analysis.hir.expect("strategy declaration should lower");
    assert_eq!(
        hir.strategy_settings.close_entries_rule,
        pine_ir::StrategyCloseEntriesRule::Any
    );
}

#[test]
fn accepts_supported_strategy_named_const_close_entries_rule_fixture() {
    let path = workspace_fixture(
        "tests/fixtures/sema/supported_strategy_named_const_close_entries_rule.pine",
    );
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    let hir = analysis.hir.expect("strategy declaration should lower");
    assert_eq!(
        hir.strategy_settings.close_entries_rule,
        pine_ir::StrategyCloseEntriesRule::Any
    );
}

#[test]
fn accepts_supported_indicator_max_polylines_count_fixture() {
    let path =
        workspace_fixture("tests/fixtures/sema/supported_indicator_max_polylines_count.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    let hir = analysis.hir.expect("indicator declaration should lower");
    assert_eq!(hir.drawing_settings.max_polylines_count, Some(75));
}

#[test]
fn accepts_supported_indicator_max_lines_count_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_indicator_max_lines_count.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    let hir = analysis.hir.expect("indicator declaration should lower");
    assert_eq!(hir.drawing_settings.max_lines_count, Some(75));
}

#[test]
fn accepts_supported_indicator_max_labels_count_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_indicator_max_labels_count.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    let hir = analysis.hir.expect("indicator declaration should lower");
    assert_eq!(hir.drawing_settings.max_labels_count, Some(75));
}

#[test]
fn accepts_supported_indicator_named_const_max_labels_count_fixture() {
    let path = workspace_fixture(
        "tests/fixtures/sema/supported_indicator_named_const_max_labels_count.pine",
    );
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    let hir = analysis.hir.expect("indicator declaration should lower");
    assert_eq!(hir.drawing_settings.max_labels_count, Some(75));
}

#[test]
fn accepts_supported_indicator_max_boxes_count_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_indicator_max_boxes_count.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    let hir = analysis.hir.expect("indicator declaration should lower");
    assert_eq!(hir.drawing_settings.max_boxes_count, Some(75));
}

#[test]
fn accepts_supported_strategy_max_polylines_count_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_strategy_max_polylines_count.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    let hir = analysis.hir.expect("strategy declaration should lower");
    assert_eq!(hir.script_mode, pine_ir::ScriptMode::Strategy);
    assert_eq!(hir.drawing_settings.max_polylines_count, Some(75));
}

#[test]
fn accepts_supported_strategy_named_const_max_polylines_count_fixture() {
    let path = workspace_fixture(
        "tests/fixtures/sema/supported_strategy_named_const_max_polylines_count.pine",
    );
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    let hir = analysis.hir.expect("strategy declaration should lower");
    assert_eq!(hir.script_mode, pine_ir::ScriptMode::Strategy);
    assert_eq!(hir.drawing_settings.max_polylines_count, Some(75));
}

#[test]
fn accepts_supported_strategy_max_lines_count_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_strategy_max_lines_count.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    let hir = analysis.hir.expect("strategy declaration should lower");
    assert_eq!(hir.script_mode, pine_ir::ScriptMode::Strategy);
    assert_eq!(hir.drawing_settings.max_lines_count, Some(75));
}

#[test]
fn accepts_supported_strategy_max_labels_count_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_strategy_max_labels_count.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    let hir = analysis.hir.expect("strategy declaration should lower");
    assert_eq!(hir.script_mode, pine_ir::ScriptMode::Strategy);
    assert_eq!(hir.drawing_settings.max_labels_count, Some(75));
}

#[test]
fn accepts_supported_strategy_max_boxes_count_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_strategy_max_boxes_count.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    let hir = analysis.hir.expect("strategy declaration should lower");
    assert_eq!(hir.script_mode, pine_ir::ScriptMode::Strategy);
    assert_eq!(hir.drawing_settings.max_boxes_count, Some(75));
}

#[test]
fn accepts_supported_strategy_initial_capital_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_strategy_initial_capital.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("strategy declaration should lower");
    assert_eq!(hir.strategy_settings.initial_capital, 2500.0);
}

#[test]
fn accepts_supported_strategy_default_quantity_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_strategy_default_quantity.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("strategy declaration should lower");
    assert_eq!(
        hir.strategy_settings.default_entry_qty(100.0, 10.0),
        Some(3.0)
    );
}

#[test]
fn accepts_supported_strategy_named_const_default_quantity_fixture() {
    let path = workspace_fixture(
        "tests/fixtures/sema/supported_strategy_named_const_default_quantity.pine",
    );
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("strategy declaration should lower");
    assert_eq!(
        hir.strategy_settings.default_entry_qty(100.0, 10.0),
        Some(10.0)
    );
}

#[test]
fn accepts_supported_strategy_named_const_numeric_metadata_fixture() {
    let path = workspace_fixture(
        "tests/fixtures/sema/supported_strategy_named_const_numeric_metadata.pine",
    );
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("strategy declaration should lower");
    let settings = hir.strategy_settings;
    assert_eq!(settings.initial_capital, 100000.0);
    assert_eq!(settings.default_entry_qty(100.0, 10.0), Some(5.0));
    assert_eq!(
        settings.commission,
        Some(pine_ir::StrategyCommission::CashPerOrder(0.5))
    );
    assert_eq!(settings.slippage_ticks, 100.0);
    assert_eq!(settings.backtest_fill_limit_ticks, 40.0);
    assert_eq!(
        settings.margin_long,
        pine_ir::StrategyMarginSetting::explicit(50.0)
    );
    assert_eq!(
        settings.margin_short,
        pine_ir::StrategyMarginSetting::explicit(50.0)
    );
    assert_eq!(settings.pyramiding_limit, 2);
}

#[test]
fn accepts_supported_strategy_percent_of_equity_default_quantity_fixture() {
    let path = workspace_fixture(
        "tests/fixtures/sema/supported_strategy_percent_of_equity_default_quantity.pine",
    );
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("strategy declaration should lower");
    assert_eq!(
        hir.strategy_settings.default_qty,
        Some(pine_ir::StrategyDefaultQuantity::PercentOfEquity(25.0))
    );
    assert_eq!(
        hir.strategy_settings.default_entry_qty(1000.0, 10.0),
        Some(25.0)
    );
}

#[test]
fn accepts_supported_strategy_cash_default_quantity_fixture() {
    let path =
        workspace_fixture("tests/fixtures/sema/supported_strategy_cash_default_quantity.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("strategy declaration should lower");
    assert_eq!(
        hir.strategy_settings.default_qty,
        Some(pine_ir::StrategyDefaultQuantity::Cash(100.0))
    );
    assert_eq!(
        hir.strategy_settings.default_entry_qty(1000.0, 10.0),
        Some(10.0)
    );
}

#[test]
fn accepts_supported_strategy_commission_cash_per_contract_fixture() {
    let path = workspace_fixture(
        "tests/fixtures/sema/supported_strategy_commission_cash_per_contract.pine",
    );
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("strategy declaration should lower");
    assert_eq!(
        hir.strategy_settings.commission,
        Some(pine_ir::StrategyCommission::CashPerContract(0.5))
    );
}

#[test]
fn accepts_supported_strategy_commission_cash_per_order_fixture() {
    let path =
        workspace_fixture("tests/fixtures/sema/supported_strategy_commission_cash_per_order.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("strategy declaration should lower");
    assert_eq!(
        hir.strategy_settings.commission,
        Some(pine_ir::StrategyCommission::CashPerOrder(1.5))
    );
}

#[test]
fn accepts_supported_strategy_commission_percent_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_strategy_commission_percent.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("strategy declaration should lower");
    assert_eq!(
        hir.strategy_settings.commission,
        Some(pine_ir::StrategyCommission::Percent(10.0))
    );
}

#[test]
fn accepts_supported_strategy_slippage_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_strategy_slippage.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("strategy declaration should lower");
    assert_eq!(hir.strategy_settings.slippage_ticks, 100.0);
}

#[test]
fn accepts_supported_strategy_limit_verification_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_strategy_limit_verification.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("strategy declaration should lower");
    assert_eq!(hir.strategy_settings.backtest_fill_limit_ticks, 100.0);
}

#[test]
fn accepts_supported_strategy_margin_declaration_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_strategy_margin_declaration.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("strategy declaration should lower");
    assert_eq!(
        hir.strategy_settings.margin_long,
        pine_ir::StrategyMarginSetting::explicit(25.0)
    );
    assert_eq!(
        hir.strategy_settings.margin_short,
        pine_ir::StrategyMarginSetting::explicit(50.0)
    );
}

#[test]
fn reports_strategy_initial_capital_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_strategy_initial_capital.pine",
        "E_CALL_ARG_VALUE",
    );
}

#[test]
fn reports_unsupported_strategy_default_quantity_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_strategy_default_quantity.pine",
        "E_CALL_ARG_VALUE",
    );
}

#[test]
fn reports_unsupported_strategy_default_entry_qty_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_strategy_default_entry_qty.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_strategy_commission_unknown_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_strategy_commission_unknown.pine",
        "E_CALL_ARG_VALUE",
    );
}

#[test]
fn reports_unsupported_strategy_slippage_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_strategy_slippage.pine",
        "E_CALL_ARG_VALUE",
    );
}

#[test]
fn reports_unsupported_strategy_named_const_slippage_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_strategy_named_const_slippage.pine",
        "E_CALL_ARG_VALUE",
    );
}

#[test]
fn reports_unsupported_strategy_limit_verification_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_strategy_limit_verification.pine",
        "E_CALL_ARG_VALUE",
    );
}

#[test]
fn reports_unsupported_strategy_margin_declaration_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_strategy_margin_declaration.pine",
        "E_CALL_ARG_VALUE",
    );
}

#[test]
fn reports_unsupported_strategy_declaration_properties_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_strategy_declaration_properties.pine",
        "E_CALL_ARG_NAME",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_strategy_declaration_properties.pine",
        &[
            "calc_on_order_fills",
            "calc_on_every_tick",
            "process_orders_on_close",
            "currency",
            "risk_free_rate",
            "use_bar_magnifier",
            "fill_orders_on_standard_ohlc",
        ],
    );
}

#[test]
fn reports_unsupported_strategy_currency_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_strategy_currency.pine",
        &["`strategy` argument `currency` only supports currency.NONE"],
    );
}

#[test]
fn reports_unsupported_strategy_close_entries_rule_unknown_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_strategy_close_entries_rule_unknown.pine",
        "E_CALL_ARG_VALUE",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_strategy_close_entries_rule_unknown.pine",
        &["close_entries_rule", "FIFO", "ANY"],
    );
}

#[test]
fn reports_unsupported_strategy_named_const_close_entries_rule_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_strategy_named_const_close_entries_rule.pine",
        "E_CALL_ARG_VALUE",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_strategy_named_const_close_entries_rule.pine",
        &["close_entries_rule", "FIFO", "ANY"],
    );
}

#[test]
fn reports_unsupported_strategy_pyramiding_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_strategy_pyramiding.pine",
        "E_CALL_ARG_VALUE",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_strategy_pyramiding.pine",
        &["pyramiding"],
    );
}

#[test]
fn reports_unsupported_indicator_max_polylines_count_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_indicator_max_polylines_count.pine",
        "E_CALL_ARG_VALUE",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_indicator_max_polylines_count.pine",
        &["max_polylines_count"],
    );
}

#[test]
fn reports_unsupported_indicator_max_lines_count_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_indicator_max_lines_count.pine",
        "E_CALL_ARG_VALUE",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_indicator_max_lines_count.pine",
        &["max_lines_count"],
    );
}

#[test]
fn reports_unsupported_indicator_max_labels_count_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_indicator_max_labels_count.pine",
        "E_CALL_ARG_VALUE",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_indicator_max_labels_count.pine",
        &["max_labels_count"],
    );
}

#[test]
fn reports_unsupported_indicator_named_const_max_labels_count_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_indicator_named_const_max_labels_count.pine",
        "E_CALL_ARG_VALUE",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_indicator_named_const_max_labels_count.pine",
        &["max_labels_count"],
    );
}

#[test]
fn reports_unsupported_indicator_max_boxes_count_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_indicator_max_boxes_count.pine",
        "E_CALL_ARG_VALUE",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_indicator_max_boxes_count.pine",
        &["max_boxes_count"],
    );
}

#[test]
fn reports_unsupported_indicator_named_const_precision_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_indicator_named_const_precision.pine",
        "E_CALL_ARG_VALUE",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_indicator_named_const_precision.pine",
        &["precision"],
    );
}

#[test]
fn reports_unsupported_indicator_named_const_metadata_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_indicator_named_const_metadata.pine",
        "E_CALL_ARG_VALUE",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_indicator_named_const_metadata.pine",
        &["scale.left", "scale.right", "scale.none"],
    );
}

#[test]
fn reports_unsupported_strategy_max_polylines_count_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_strategy_max_polylines_count.pine",
        "E_CALL_ARG_VALUE",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_strategy_max_polylines_count.pine",
        &["max_polylines_count"],
    );
}

#[test]
fn reports_unsupported_strategy_named_const_max_polylines_count_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_strategy_named_const_max_polylines_count.pine",
        "E_CALL_ARG_VALUE",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_strategy_named_const_max_polylines_count.pine",
        &["max_polylines_count"],
    );
}

#[test]
fn reports_unsupported_strategy_max_lines_count_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_strategy_max_lines_count.pine",
        "E_CALL_ARG_VALUE",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_strategy_max_lines_count.pine",
        &["max_lines_count"],
    );
}

#[test]
fn reports_unsupported_strategy_max_labels_count_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_strategy_max_labels_count.pine",
        "E_CALL_ARG_VALUE",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_strategy_max_labels_count.pine",
        &["max_labels_count"],
    );
}

#[test]
fn reports_unsupported_strategy_max_boxes_count_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_strategy_max_boxes_count.pine",
        "E_CALL_ARG_VALUE",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_strategy_max_boxes_count.pine",
        &["max_boxes_count"],
    );
}

#[test]
fn reports_unsupported_strategy_order_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_strategy_orders.pine",
        "E_CALL_ARG_VALUE",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_strategy_orders.pine",
        &[
            "explicit positive qty",
            "strategy.long",
            "only supported for strategy.long",
            "market/limit/stop/stop-limit-long subset",
            "oca_name",
            "oca_type",
        ],
    );
}

#[test]
fn reports_unsupported_strategy_order_named_const_direction_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_strategy_order_named_const_direction.pine",
        "E_CALL_ARG_VALUE",
    );
}

#[test]
fn reports_unsupported_strategy_exit_variant_fixtures() {
    for (path, code) in [
        (
            "tests/fixtures/sema/unsupported_strategy_exit_stop_loss.pine",
            "E_CALL_ARG_NAME",
        ),
        (
            "tests/fixtures/sema/unsupported_strategy_exit_limit_profit.pine",
            "E_CALL_ARG_NAME",
        ),
        (
            "tests/fixtures/sema/unsupported_strategy_exit_three_triggers.pine",
            "E_CALL_ARG_NAME",
        ),
        (
            "tests/fixtures/sema/unsupported_strategy_exit_four_triggers.pine",
            "E_CALL_ARG_NAME",
        ),
        (
            "tests/fixtures/sema/unsupported_strategy_exit_qty_percent_same_side.pine",
            "E_CALL_ARG_NAME",
        ),
        (
            "tests/fixtures/sema/unsupported_strategy_exit_qty_same_side.pine",
            "E_CALL_ARG_NAME",
        ),
        (
            "tests/fixtures/sema/unsupported_strategy_exit_trailing.pine",
            "E_CALL_ARG_NAME",
        ),
        (
            "tests/fixtures/sema/unsupported_strategy_exit_profit_trailing.pine",
            "E_CALL_ARG_NAME",
        ),
        (
            "tests/fixtures/sema/unsupported_strategy_exit_trail_price_only.pine",
            "E_CALL_ARG_NAME",
        ),
        (
            "tests/fixtures/sema/unsupported_strategy_exit_trail_points_only.pine",
            "E_CALL_ARG_NAME",
        ),
        (
            "tests/fixtures/sema/unsupported_strategy_exit_trail_offset_only.pine",
            "E_CALL_ARG_NAME",
        ),
        (
            "tests/fixtures/sema/unsupported_strategy_exit_trail_price_points.pine",
            "E_CALL_ARG_NAME",
        ),
        (
            "tests/fixtures/sema/unsupported_strategy_exit_trailing_bracket.pine",
            "E_CALL_ARG_NAME",
        ),
        (
            "tests/fixtures/sema/unsupported_strategy_exit_trailing_indicator.pine",
            "E_STRATEGY_MODE",
        ),
        (
            "tests/fixtures/sema/unsupported_strategy_exit_trailing_function_side_effect.pine",
            "E_UNSUPPORTED_FEATURE",
        ),
        (
            "tests/fixtures/sema/unsupported_request_strategy_trailing_exit.pine",
            "E_UNSUPPORTED_FEATURE",
        ),
        (
            "tests/fixtures/sema/unsupported_strategy_exit_partial_quantity.pine",
            "E_CALL_ARITY",
        ),
        (
            "tests/fixtures/sema/unsupported_strategy_exit_missing_trigger.pine",
            "E_CALL_ARITY",
        ),
        (
            "tests/fixtures/sema/unsupported_strategy_exit_named_missing_trigger.pine",
            "E_CALL_ARITY",
        ),
        (
            "tests/fixtures/sema/unsupported_strategy_exit_missing_id.pine",
            "E_CALL_ARITY",
        ),
        (
            "tests/fixtures/sema/unsupported_strategy_exit_oca_name.pine",
            "E_CALL_ARG_NAME",
        ),
        (
            "tests/fixtures/sema/unsupported_strategy_order_metadata_types.pine",
            "E_CALL_ARG_TYPE",
        ),
        (
            "tests/fixtures/sema/unsupported_strategy_close_immediately.pine",
            "E_CALL_ARG_NAME",
        ),
        (
            "tests/fixtures/sema/unsupported_strategy_exit_function_side_effect.pine",
            "E_UNSUPPORTED_FEATURE",
        ),
        (
            "tests/fixtures/sema/unsupported_request_strategy_exit.pine",
            "E_UNSUPPORTED_FEATURE",
        ),
    ] {
        assert_diagnostic_fixture(path, code);
    }
}

#[test]
fn reports_strategy_exit_quantity_guardrail_messages() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_strategy_exit_qty_percent_same_side.pine",
        &["`strategy.exit` combined trigger families are not supported"],
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_strategy_exit_qty_same_side.pine",
        &["`strategy.exit` combined trigger families are not supported"],
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_strategy_exit_partial_quantity.pine",
        &["`strategy.exit` requires one of `stop`, `limit`, `profit`, or `loss`"],
    );
    for fixture in [
        "tests/fixtures/sema/unsupported_strategy_exit_missing_trigger.pine",
        "tests/fixtures/sema/unsupported_strategy_exit_named_missing_trigger.pine",
    ] {
        assert_diagnostic_messages(
            fixture,
            &["`strategy.exit` requires one of `stop`, `limit`, `profit`, or `loss`"],
        );
    }
}

#[test]
fn accepts_supported_strategy_exit_fixtures() {
    for fixture in [
        "tests/fixtures/sema/supported_strategy_exit_stop.pine",
        "tests/fixtures/sema/supported_strategy_exit_limit.pine",
        "tests/fixtures/sema/supported_strategy_exit_profit.pine",
        "tests/fixtures/sema/supported_strategy_exit_loss.pine",
        "tests/fixtures/sema/supported_strategy_exit_stop_limit.pine",
        "tests/fixtures/sema/supported_strategy_exit_stop_profit.pine",
        "tests/fixtures/sema/supported_strategy_exit_loss_limit.pine",
        "tests/fixtures/sema/supported_strategy_exit_loss_profit.pine",
        "tests/fixtures/sema/supported_strategy_exit_trail_price.pine",
        "tests/fixtures/sema/supported_strategy_exit_trail_points.pine",
        "tests/fixtures/sema/supported_strategy_exit_omitted_from_entry.pine",
        "tests/fixtures/sema/supported_strategy_exit_qty_stop.pine",
        "tests/fixtures/sema/supported_strategy_exit_qty_bracket.pine",
        "tests/fixtures/sema/supported_strategy_exit_qty_trailing.pine",
        "tests/fixtures/sema/supported_strategy_exit_qty_percent_stop.pine",
        "tests/fixtures/sema/supported_strategy_exit_qty_percent_loss.pine",
        "tests/fixtures/sema/supported_strategy_exit_qty_percent_bracket.pine",
        "tests/fixtures/sema/supported_strategy_exit_qty_percent_trailing.pine",
        "tests/fixtures/sema/supported_strategy_exit_qty_and_qty_percent_stop.pine",
        "tests/fixtures/sema/supported_strategy_exit_qty_and_qty_percent_bracket.pine",
        "tests/fixtures/sema/supported_strategy_exit_qty_and_qty_percent_trailing.pine",
        "tests/fixtures/sema/supported_strategy_order_metadata.pine",
    ] {
        let path = workspace_fixture(fixture);
        let text = fs::read_to_string(&path).expect("fixture should be readable");
        let source = SourceFile::new(path.display().to_string(), text);
        let analysis = analyze_source(&source);

        assert!(
            analysis.diagnostics.is_empty(),
            "{} diagnostics: {:?}",
            path.display(),
            analysis.diagnostics
        );
        assert!(analysis.compatibility.unsupported.is_empty());
        assert!(
            analysis
                .compatibility
                .supported
                .iter()
                .any(|supported| supported.feature == "strategy.exit")
        );
        assert!(analysis.hir.is_some());
    }
}

#[test]
fn accepts_supported_strategy_entry_default_quantity_fixture() {
    let path =
        workspace_fixture("tests/fixtures/sema/supported_strategy_entry_default_quantity.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("strategy entry should lower");
    assert_eq!(
        hir.strategy_settings.default_entry_qty(100.0, 10.0),
        Some(1.0)
    );
}

#[test]
fn accepts_supported_strategy_entry_fixture() {
    for fixture in [
        "tests/fixtures/sema/supported_strategy_entry.pine",
        "tests/fixtures/sema/supported_strategy_entry_limit.pine",
        "tests/fixtures/sema/supported_strategy_entry_stop.pine",
        "tests/fixtures/sema/supported_strategy_entry_stop_limit.pine",
        "tests/fixtures/sema/supported_strategy_entry_named_const_numeric.pine",
        "tests/fixtures/sema/supported_strategy_entry_named_const_direction.pine",
    ] {
        let path = workspace_fixture(fixture);
        let text = fs::read_to_string(&path).expect("fixture should be readable");
        let source = SourceFile::new(path.display().to_string(), text);
        let analysis = analyze_source(&source);

        assert!(
            analysis.diagnostics.is_empty(),
            "{} diagnostics: {:?}",
            path.display(),
            analysis.diagnostics
        );
        assert!(analysis.compatibility.unsupported.is_empty());
        assert!(
            analysis
                .compatibility
                .supported
                .iter()
                .any(|supported| supported.feature == "strategy.entry")
        );
        assert!(analysis.hir.is_some());
    }
}

#[test]
fn accepts_supported_strategy_order_fixture() {
    for fixture in [
        "tests/fixtures/sema/supported_strategy_order.pine",
        "tests/fixtures/sema/supported_strategy_order_named_const_numeric.pine",
        "tests/fixtures/sema/supported_strategy_order_named_const_direction.pine",
    ] {
        let path = workspace_fixture(fixture);
        let text = fs::read_to_string(&path).expect("fixture should be readable");
        let source = SourceFile::new(path.display().to_string(), text);
        let analysis = analyze_source(&source);

        assert!(
            analysis.diagnostics.is_empty(),
            "{} diagnostics: {:?}",
            path.display(),
            analysis.diagnostics
        );
        assert!(analysis.compatibility.unsupported.is_empty());
        assert!(
            analysis
                .compatibility
                .supported
                .iter()
                .any(|supported| supported.feature == "strategy.order")
        );
        assert!(analysis.hir.is_some());
    }
}

#[test]
fn reports_unsupported_strategy_order_series_simple_string_ids_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_strategy_order_series_simple_string_ids.pine",
        &[
            "`strategy.entry` argument `id` expects simple string, got series string",
            "`strategy.order` argument `id` expects simple string, got series string",
            "`strategy.close` argument `id` expects simple string, got series string",
            "`strategy.cancel` argument `id` expects simple string, got series string",
            "`strategy.exit` argument `id` expects simple string, got series string",
            "`strategy.exit` argument `from_entry` expects simple string, got series string",
        ],
    );
}

#[test]
fn reports_strategy_entry_indicator_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_strategy_entry_indicator.pine",
        "E_STRATEGY_MODE",
    );
}

#[test]
fn reports_strategy_entry_short_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_strategy_entry_short.pine",
        "E_CALL_ARG_VALUE",
    );
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_strategy_entry_named_const_short_direction.pine",
        "E_CALL_ARG_VALUE",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_strategy_entry_short.pine",
        &["strategy.long"],
    );
}

#[test]
fn reports_strategy_entry_qty_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_strategy_entry_qty.pine",
        "E_CALL_ARG_VALUE",
    );
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_strategy_entry_named_const_qty.pine",
        "E_CALL_ARG_VALUE",
    );
}

#[test]
fn accepts_supported_strategy_close_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_strategy_close.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "strategy.close")
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn reports_unsupported_strategy_close_partial_quantity_fixture() {
    let path =
        workspace_fixture("tests/fixtures/sema/unsupported_strategy_close_partial_quantity.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.iter().any(|diagnostic| {
            diagnostic.code == "E_CALL_ARG_NAME"
                && diagnostic
                    .message
                    .contains("partial quantity arguments must be named")
        }),
        "{} diagnostics should reject positional strategy.close quantity: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(
        analysis.diagnostics.iter().any(|diagnostic| {
            diagnostic.code == "E_CALL_ARG_VALUE"
                && diagnostic
                    .message
                    .contains("argument `qty` must be finite and positive")
        }),
        "{} diagnostics should reject non-positive strategy.close qty: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(
        analysis.diagnostics.iter().any(|diagnostic| {
            diagnostic.code == "E_CALL_ARG_VALUE"
                && diagnostic
                    .message
                    .contains("argument `qty_percent` must be finite and positive")
        }),
        "{} diagnostics should reject non-positive strategy.close qty_percent: {:?}",
        path.display(),
        analysis.diagnostics
    );
    let name = "immediately";
    assert!(
        analysis.diagnostics.iter().any(|diagnostic| {
            diagnostic.code == "E_CALL_ARG_NAME" && diagnostic.message.contains(name)
        }),
        "{} diagnostics should reject strategy.close argument `{}`: {:?}",
        path.display(),
        name,
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn reports_unsupported_strategy_close_named_const_quantity_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_strategy_close_named_const_quantity.pine",
        "E_CALL_ARG_VALUE",
    );
}

#[test]
fn reports_strategy_order_metadata_type_guardrails() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_strategy_order_metadata_types.pine",
        &[
            "argument `comment` expects string-compatible",
            "argument `disable_alert` expects bool-compatible",
            "argument `alert_message` expects string-compatible",
        ],
    );
}

#[test]
fn reports_strategy_close_immediately_remains_unsupported() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_strategy_close_immediately.pine",
        &["immediately"],
    );
}

#[test]
fn accepts_supported_strategy_close_qty_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_strategy_close_qty.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "strategy.close")
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_strategy_close_qty_percent_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_strategy_close_qty_percent.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics should be empty: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_strategy_close_named_const_numeric_fixture() {
    let path =
        workspace_fixture("tests/fixtures/sema/supported_strategy_close_named_const_numeric.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics should be empty: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_strategy_close_qty_precedence_fixture() {
    let path =
        workspace_fixture("tests/fixtures/sema/supported_strategy_close_qty_precedence.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics should be empty: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_strategy_close_all_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_strategy_close_all.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "strategy.close_all")
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_strategy_position_state_fixture() {
    assert_strategy_state_supported_fixture(
        "tests/fixtures/sema/supported_strategy_position_state.pine",
        &[
            "strategy.position_size",
            "strategy.position_avg_price",
            "strategy.position_entry_name",
            "strategy.max_contracts_held_all",
            "strategy.max_contracts_held_long",
            "strategy.max_contracts_held_short",
        ],
    );
}

#[test]
fn accepts_supported_strategy_account_currency_fixture() {
    assert_strategy_state_supported_fixture(
        "tests/fixtures/sema/supported_strategy_account_currency.pine",
        &["strategy.account_currency"],
    );
}

#[test]
fn accepts_supported_strategy_currency_conversion_fixture() {
    assert_strategy_state_supported_fixture(
        "tests/fixtures/sema/supported_strategy_currency_conversion.pine",
        &["strategy.convert_to_account", "strategy.convert_to_symbol"],
    );
}

#[test]
fn reports_strategy_currency_conversion_argument_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_strategy_currency_conversion.pine",
        "E_CALL_ARG_TYPE",
    );
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_strategy_currency_conversion.pine",
        "E_CALL_ARITY",
    );
}

#[test]
fn reports_strategy_currency_conversion_indicator_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_strategy_currency_conversion_indicator.pine",
        &[
            "`strategy.convert_to_account` is only supported in scripts declared with strategy(...)",
            "`strategy.convert_to_symbol` is only supported in scripts declared with strategy(...)",
        ],
    );
}

#[test]
fn reports_strategy_account_currency_const_consumer_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_strategy_account_currency_const.pine",
        &["`timestamp` argument `dateString` expects const string, got simple string"],
    );
}

#[test]
fn accepts_supported_strategy_profit_state_fixture() {
    assert_strategy_state_supported_fixture(
        "tests/fixtures/sema/supported_strategy_profit_state.pine",
        &[
            "strategy.initial_capital",
            "strategy.openprofit",
            "strategy.openprofit_percent",
            "strategy.netprofit",
            "strategy.netprofit_percent",
            "strategy.grossprofit",
            "strategy.grossprofit_percent",
            "strategy.grossloss",
            "strategy.grossloss_percent",
            "strategy.buy_and_hold_return_percent",
            "strategy.avg_trade",
            "strategy.avg_trade_percent",
            "strategy.avg_winning_trade",
            "strategy.avg_winning_trade_percent",
            "strategy.avg_losing_trade",
            "strategy.avg_losing_trade_percent",
            "strategy.max_runup",
            "strategy.max_runup_percent",
            "strategy.max_drawdown",
            "strategy.max_drawdown_percent",
            "strategy.margin_liquidation_price",
            "strategy.equity",
        ],
    );
}

#[test]
fn accepts_supported_strategy_variable_interactions_fixture() {
    assert_strategy_state_supported_fixture(
        "tests/fixtures/sema/supported_strategy_variable_interactions.pine",
        &[
            "strategy.position_size",
            "strategy.openprofit",
            "strategy.netprofit",
        ],
    );
}

#[test]
fn accepts_supported_strategy_trade_counts_fixture() {
    assert_strategy_state_supported_fixture(
        "tests/fixtures/sema/supported_strategy_trade_counts.pine",
        &[
            "strategy.closedtrades",
            "strategy.closedtrades.first_index",
            "strategy.opentrades",
        ],
    );
}

#[test]
fn accepts_supported_strategy_closedtrades_fields_fixture() {
    assert_strategy_state_supported_fixture(
        "tests/fixtures/sema/supported_strategy_closedtrades_fields.pine",
        &[
            "strategy.closedtrades.entry_price",
            "strategy.closedtrades.entry_comment",
            "strategy.closedtrades.entry_id",
            "strategy.closedtrades.exit_price",
            "strategy.closedtrades.exit_comment",
            "strategy.closedtrades.exit_id",
            "strategy.closedtrades.entry_bar_index",
            "strategy.closedtrades.exit_bar_index",
            "strategy.closedtrades.entry_time",
            "strategy.closedtrades.exit_time",
            "strategy.closedtrades.commission",
            "strategy.closedtrades.size",
            "strategy.closedtrades.profit",
            "strategy.closedtrades.max_runup",
            "strategy.closedtrades.max_drawdown",
        ],
    );
}

#[test]
fn accepts_supported_strategy_opentrades_fields_fixture() {
    assert_strategy_state_supported_fixture(
        "tests/fixtures/sema/supported_strategy_opentrades_fields.pine",
        &[
            "strategy.opentrades.entry_price",
            "strategy.opentrades.entry_comment",
            "strategy.opentrades.entry_id",
            "strategy.opentrades.entry_bar_index",
            "strategy.opentrades.entry_time",
            "strategy.opentrades.size",
            "strategy.opentrades.profit",
            "strategy.opentrades.commission",
            "strategy.opentrades.max_runup",
            "strategy.opentrades.max_drawdown",
            "strategy.opentrades.capital_held",
        ],
    );
}

#[test]
fn accepts_supported_strategy_trade_count_interactions_fixture() {
    assert_strategy_state_supported_fixture(
        "tests/fixtures/sema/supported_strategy_trade_count_interactions.pine",
        &["strategy.closedtrades", "strategy.opentrades"],
    );
}

#[test]
fn accepts_supported_strategy_trade_outcome_counts_fixture() {
    assert_strategy_state_supported_fixture(
        "tests/fixtures/sema/supported_strategy_trade_outcome_counts.pine",
        &[
            "strategy.wintrades",
            "strategy.losstrades",
            "strategy.eventrades",
        ],
    );
}

#[test]
fn reports_strategy_close_indicator_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_strategy_close_indicator.pine",
        "E_STRATEGY_MODE",
    );
}

#[test]
fn reports_strategy_close_all_indicator_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_strategy_close_all_indicator.pine",
        "E_STRATEGY_MODE",
    );
}

#[test]
fn reports_strategy_state_indicator_fixture() {
    assert_strategy_state_mode_fixture(
        "tests/fixtures/sema/unsupported_strategy_state_indicator.pine",
    );
}

#[test]
fn reports_unknown_strategy_variable_fixture() {
    assert_strategy_unsupported_fixture(
        "tests/fixtures/sema/unsupported_strategy_unknown_variable.pine",
        &["strategy.future_metric"],
    );
}

#[test]
fn reports_unsupported_strategy_order_and_trade_namespace_fixture() {
    assert_strategy_unsupported_fixture(
        "tests/fixtures/sema/unsupported_strategy_order_and_trade_namespaces.pine",
        &[
            "strategy.risk.allow_entry_in",
            "strategy.risk.max_drawdown",
            "strategy.risk.max_intraday_loss",
            "strategy.risk.max_position_size",
            "strategy.risk.max_intraday_filled_orders",
        ],
    );
}

#[test]
fn reports_strategy_closedtrades_fields_indicator_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_strategy_closedtrades_fields_indicator.pine",
        "E_STRATEGY_MODE",
    );
}

#[test]
fn accepts_supported_strategy_cancel_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_strategy_cancel.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "strategy.cancel")
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_strategy_cancel_all_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_strategy_cancel_all.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "strategy.cancel_all")
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn reports_request_strategy_state_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_request_strategy_state.pine",
        "request.security",
        "same-context request.security",
    );
}

#[test]
fn reports_strategy_state_mutation_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_strategy_state_mutation.pine",
        "strategy state variable mutation",
        "read-only",
    );
}

#[test]
fn reports_unsupported_strategy_duplicate_declaration_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_strategy_duplicate_declaration.pine",
        "E_SCRIPT_DECL_DUPLICATE",
    );
}

#[test]
fn reports_unsupported_strategy_local_declaration_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_strategy_local_declaration.pine",
        "E_SCRIPT_DECL_LOCATION",
    );
}

#[test]
fn reports_unsupported_drawing_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_drawing.pine",
        "label.set_text_wrap",
        "drawing object",
    );
}

#[test]
fn accepts_supported_drawing_object_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_drawing_object_return_qualifier.pine");
}

#[test]
fn reports_unsupported_drawing_object_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_drawing_object_return_qualifier.pine",
        &[
            "`hline` argument `price` expects const/input numeric, got series label",
            "`hline` argument `price` expects const/input numeric, got series line",
            "`hline` argument `price` expects const/input numeric, got series box",
            "`hline` argument `price` expects const/input numeric, got series table",
            "`hline` argument `price` expects const/input numeric, got series linefill",
            "`hline` argument `price` expects const/input numeric, got series polyline",
        ],
    );
}

#[test]
fn accepts_supported_drawing_object_copy_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_drawing_object_copy_return_qualifier.pine");
}

#[test]
fn reports_unsupported_drawing_object_copy_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_drawing_object_copy_return_qualifier.pine",
        &[
            "`hline` argument `price` expects const/input numeric, got series label",
            "`hline` argument `price` expects const/input numeric, got series line",
            "`hline` argument `price` expects const/input numeric, got series box",
            "`hline` argument `price` expects const/input numeric, got series line",
            "`hline` argument `price` expects const/input numeric, got series line",
            "`hline` argument `price` expects const/input numeric, got series line",
            "`hline` argument `price` expects const/input numeric, got series line",
        ],
    );
}

#[test]
fn accepts_supported_drawing_getter_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_drawing_getter_return_qualifier.pine");
}

#[test]
fn reports_unsupported_drawing_getter_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_drawing_getter_return_qualifier.pine",
        &[
            "`hline` argument `price` expects const/input numeric, got series int",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`syminfo.prefix` argument `symbol` expects simple string, got series string",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series int",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series int",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series int",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series int",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series int",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`syminfo.prefix` argument `symbol` expects simple string, got series string",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series int",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series int",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series int",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series int",
            "`hline` argument `price` expects const/input numeric, got series float",
        ],
    );
}

#[test]
fn accepts_supported_drawing_all_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_drawing_all_return_qualifier.pine");
}

#[test]
fn reports_unsupported_drawing_all_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_drawing_all_return_qualifier.pine",
        &[
            "cannot pass simple array<label> to function parameter `values` of type series array<line>",
            "cannot pass simple array<line> to function parameter `values` of type series array<label>",
            "cannot pass simple array<polyline> to function parameter `values` of type series array<linefill>",
            "cannot pass simple array<linefill> to function parameter `values` of type series array<polyline>",
            "cannot pass simple array<box> to function parameter `values` of type series array<table>",
            "cannot pass simple array<table> to function parameter `values` of type series array<box>",
        ],
    );
}

#[test]
fn reports_unsupported_label_new_modes_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_label_new_modes.pine",
        &["yloc.abovebar", "label.style_label_down", "size.normal"],
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_label_new_named_const_options.pine",
        &["label.style_label_down", "text.format_"],
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_label_new_type_options.pine",
        &[
            "`label.new` argument `style` expects const string, got series string",
            "`label.new` argument `size` expects string/int-compatible, got series float",
            "`label.new` argument `point` expects chart.point-compatible, got series float",
        ],
    );
}

#[test]
fn reports_unsupported_line_new_modes_fixture() {
    for fixture in [
        "tests/fixtures/sema/unsupported_line_new_modes.pine",
        "tests/fixtures/sema/unsupported_line_new_named_const_options.pine",
    ] {
        assert_diagnostic_messages(fixture, &["line.style_"]);
    }
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_line_new_type_options.pine",
        &[
            "`line.new` argument `style` expects const string, got series string",
            "`line.new` argument `width` expects integer-compatible, got series float",
        ],
    );
}

#[test]
fn reports_unsupported_box_new_modes_fixture() {
    for fixture in [
        "tests/fixtures/sema/unsupported_box_new_modes.pine",
        "tests/fixtures/sema/unsupported_box_new_named_const_options.pine",
    ] {
        assert_diagnostic_messages(fixture, &["text.format_"]);
    }
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_box_new_type_options.pine",
        &[
            "`box.new` argument `border_style` expects const string, got series string",
            "`box.new` argument `text_size` expects string/int-compatible, got series float",
        ],
    );
}

#[test]
fn reports_unsupported_box_border_style_arrow_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_box_border_style_arrow.pine",
        &["line.style_solid", "line.style_dotted", "line.style_dashed"],
    );
}

#[test]
fn accepts_supported_drawing_constructor_named_const_options_fixture() {
    for fixture in [
        "tests/fixtures/sema/supported_label_new_named_const_options.pine",
        "tests/fixtures/sema/supported_line_new_named_const_options.pine",
        "tests/fixtures/sema/supported_box_new_named_const_options.pine",
    ] {
        let path = workspace_fixture(fixture);
        let text = fs::read_to_string(&path).expect("fixture should be readable");
        let source = SourceFile::new(path.display().to_string(), text);
        let analysis = analyze_source(&source);

        assert!(
            analysis.diagnostics.is_empty(),
            "{} diagnostics: {:?}",
            path.display(),
            analysis.diagnostics
        );
        assert!(
            analysis.compatibility.unsupported.is_empty(),
            "{} unsupported: {:?}",
            path.display(),
            analysis.compatibility.unsupported
        );
        assert!(analysis.hir.is_some());
    }
}

#[test]
fn reports_unsupported_table_new_modes_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_table_new_modes.pine",
        "E_CALL_ARG_VALUE",
    );
}

#[test]
fn reports_unsupported_table_cell_text_formatting_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_table_cell_text_formatting.pine",
        "E_CALL_ARG_VALUE",
    );
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_table_cell_named_const_text_formatting.pine",
        "E_CALL_ARG_VALUE",
    );
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_table_cell_named_const_text_size.pine",
        "E_CALL_ARG_VALUE",
    );
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_table_cell_set_named_const_text_options.pine",
        "E_CALL_ARG_VALUE",
    );
}

#[test]
fn accepts_supported_table_cell_named_const_text_options_fixture() {
    for fixture in [
        "tests/fixtures/sema/supported_table_cell_named_const_text_options.pine",
        "tests/fixtures/sema/supported_table_cell_set_named_const_text_options.pine",
    ] {
        let path = workspace_fixture(fixture);
        let text = fs::read_to_string(&path).expect("fixture should be readable");
        let source = SourceFile::new(path.display().to_string(), text);
        let analysis = analyze_source(&source);

        assert!(
            analysis.diagnostics.is_empty(),
            "{} diagnostics: {:?}",
            path.display(),
            analysis.diagnostics
        );
        assert!(analysis.compatibility.unsupported.is_empty());
        assert!(analysis.hir.is_some());
    }
}

#[test]
fn reports_unsupported_table_set_position_values_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_table_set_position_values.pine",
        "E_CALL_ARG_VALUE",
    );
}

#[test]
fn reports_unsupported_table_method_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_table_method.pine",
        "table.set_border_style",
        "drawing object",
    );
}

#[test]
fn reports_unsupported_table_cell_method_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_table_cell_method.pine",
        "table.cell_set_border_color",
        "drawing object",
    );
}

#[test]
fn reports_unsupported_if_condition_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_if_condition.pine",
        &["condition must be bool, got const string"],
    );
}

#[test]
fn reports_unsupported_if_expression_alert_result_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_if_expression_alert_result.pine",
        "E_BRANCH_RETURN",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_if_expression_alert_result.pine",
        &["if expression branches must end with a value-producing expression"],
    );
}

#[test]
fn reports_unsupported_if_expression_no_final_result_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_if_expression_no_final_result.pine",
        "E_BRANCH_RETURN",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_if_expression_no_final_result.pine",
        &["if expression branches must end with a value-producing expression"],
    );
}

#[test]
fn reports_unsupported_if_expression_reassignment_result_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_if_expression_reassignment_result.pine",
        "E_BRANCH_RETURN",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_if_expression_reassignment_result.pine",
        &["if expression branches must end with a value-producing expression"],
    );
}

#[test]
fn reports_unsupported_switch_condition_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_switch_condition.pine",
        &["condition must be bool, got const string"],
    );
}

#[test]
fn reports_unsupported_for_in_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in.pine",
        "for...in",
        "scalar maps with key-only or key/value loop variables",
    );
}

#[test]
fn reports_unsupported_for_in_non_array_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_non_array.pine",
        "for...in",
        "scalar maps with key-only or key/value loop variables",
    );
}

#[test]
fn reports_unsupported_for_in_index_value_non_int_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_index_value_non_int.pine",
        "for...in",
        "scalar maps where the first variable receives the key",
    );
}

#[test]
fn accepts_supported_for_in_expression_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_for_in_expression.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "for")
    );
}

#[test]
fn accepts_supported_for_in_expression_float_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_for_in_expression_float.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "for")
    );
}

#[test]
fn accepts_supported_for_in_expression_bool_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_for_in_expression_bool.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "for")
    );
}

#[test]
fn accepts_supported_for_in_expression_string_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_for_in_expression_string.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "for")
    );
}

#[test]
fn accepts_supported_for_in_expression_color_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_for_in_expression_color.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "for")
    );
}

#[test]
fn accepts_supported_for_in_expression_label_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_for_in_expression_label.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "for")
    );
}

#[test]
fn accepts_supported_for_in_expression_line_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_for_in_expression_line.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "for")
    );
}

#[test]
fn accepts_supported_for_in_expression_linefill_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_for_in_expression_linefill.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "for")
    );
}

#[test]
fn accepts_supported_for_in_expression_polyline_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_for_in_expression_polyline.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "for")
    );
}

#[test]
fn accepts_supported_for_in_expression_box_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_for_in_expression_box.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "for")
    );
}

#[test]
fn accepts_supported_for_in_expression_table_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_for_in_expression_table.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "for")
    );
}

#[test]
fn accepts_supported_for_in_expression_chart_point_fixture() {
    let path =
        workspace_fixture("tests/fixtures/sema/supported_for_in_expression_chart_point.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "for")
    );
}

#[test]
fn accepts_supported_for_in_expression_udt_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_for_in_expression_udt.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "for")
    );
}

#[test]
fn accepts_supported_for_in_expression_matrix_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_for_in_expression_matrix.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "for")
    );
}

#[test]
fn accepts_supported_for_in_expression_index_value_fixture() {
    let path =
        workspace_fixture("tests/fixtures/sema/supported_for_in_expression_index_value.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "for")
    );
}

#[test]
fn reports_unsupported_for_in_expression_non_array_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_expression_non_array.pine",
        "for...in expression",
        "scalar maps with key-only or key/value loop variables",
    );
}

#[test]
fn reports_unsupported_for_in_expression_reassignment_result_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_for_in_expression_reassignment_result.pine",
        "E_LOOP_RETURN",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_expression_reassignment_result.pine",
        &["for...in expression body must end with a value-producing expression"],
    );
}

#[test]
fn reports_unsupported_for_in_expression_alert_result_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_for_in_expression_alert_result.pine",
        "E_LOOP_RETURN",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_expression_alert_result.pine",
        &["for...in expression body must end with a value-producing expression"],
    );
}

#[test]
fn reports_unsupported_for_expression_alert_result_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_for_expression_alert_result.pine",
        "E_LOOP_RETURN",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_expression_alert_result.pine",
        &["for expression body must end with a value-producing expression"],
    );
}

#[test]
fn reports_unsupported_for_expression_break_result_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_for_expression_break_result.pine",
        "E_LOOP_RETURN",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_expression_break_result.pine",
        &["for expression body must end with a value-producing expression"],
    );
}

#[test]
fn reports_unsupported_for_expression_continue_result_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_for_expression_continue_result.pine",
        "E_LOOP_RETURN",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_expression_continue_result.pine",
        &["for expression body must end with a value-producing expression"],
    );
}

#[test]
fn reports_unsupported_for_expression_no_final_result_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_for_expression_no_final_result.pine",
        "E_LOOP_RETURN",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_expression_no_final_result.pine",
        &["for expression body must end with a value-producing expression"],
    );
}

#[test]
fn reports_unsupported_for_expression_reassignment_result_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_for_expression_reassignment_result.pine",
        "E_LOOP_RETURN",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_expression_reassignment_result.pine",
        &["for expression body must end with a value-producing expression"],
    );
}

#[test]
fn reports_unsupported_switch_statement_block_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_switch_statement_block.pine",
        "E_BRANCH_RETURN",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_switch_statement_block.pine",
        &["switch expression branches must end with a value-producing expression"],
    );
}

#[test]
fn reports_unsupported_switch_statement_block_selector_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_switch_statement_block_selector.pine",
        "E_BRANCH_RETURN",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_switch_statement_block_selector.pine",
        &["switch expression branches must end with a value-producing expression"],
    );
}

#[test]
fn reports_unsupported_switch_statement_block_default_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_switch_statement_block_default.pine",
        "E_BRANCH_RETURN",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_switch_statement_block_default.pine",
        &["switch expression branches must end with a value-producing expression"],
    );
}

#[test]
fn reports_unsupported_switch_statement_block_alert_result_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_switch_statement_block_alert_result.pine",
        "E_BRANCH_RETURN",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_switch_statement_block_alert_result.pine",
        &["switch expression branches must end with a value-producing expression"],
    );
}

#[test]
fn reports_unsupported_switch_statement_block_reassignment_result_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_switch_statement_block_reassignment_result.pine",
        "E_BRANCH_RETURN",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_switch_statement_block_reassignment_result.pine",
        &["switch expression branches must end with a value-producing expression"],
    );
}

#[test]
fn reports_unsupported_switch_statement_block_scope_leak_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_switch_statement_block_scope_leak.pine",
        "E_UNKNOWN_SYMBOL",
    );
}

#[test]
fn reports_unsupported_switch_statement_block_udt_identity_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_switch_statement_block_udt_identity.pine",
        &["switch user-defined type arms must resolve to the same UDT identity"],
    );
}

#[test]
fn reports_unsupported_imported_udt_switch_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_switch_identity.pine",
        &["switch user-defined type arms must resolve to the same UDT identity"],
    );
}

#[test]
fn reports_unsupported_while_condition_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_while_condition.pine",
        &["condition must be bool, got const string"],
    );
}

#[test]
fn reports_unsupported_while_expression_scope_leak_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_while_expression_scope_leak.pine",
        "E_UNKNOWN_SYMBOL",
    );
}

#[test]
fn accepts_supported_while_expression_matrix_kinds_fixture() {
    let path =
        workspace_fixture("tests/fixtures/sema/supported_while_expression_matrix_kinds.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn reports_unsupported_while_expression_no_final_result_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_while_expression_no_final_result.pine",
        "E_BRANCH_RETURN",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_while_expression_no_final_result.pine",
        &["while expression branches must end with a value-producing expression"],
    );
}

#[test]
fn reports_unsupported_while_expression_reassignment_result_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_while_expression_reassignment_result.pine",
        "E_BRANCH_RETURN",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_while_expression_reassignment_result.pine",
        &["while expression branches must end with a value-producing expression"],
    );
}

#[test]
fn reports_unsupported_while_expression_break_result_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_while_expression_break_result.pine",
        "E_BRANCH_RETURN",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_while_expression_break_result.pine",
        &["while expression branches must end with a value-producing expression"],
    );
}

#[test]
fn reports_unsupported_while_expression_continue_result_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_while_expression_continue_result.pine",
        "E_BRANCH_RETURN",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_while_expression_continue_result.pine",
        &["while expression branches must end with a value-producing expression"],
    );
}

#[test]
fn reports_unsupported_while_expression_alert_result_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_while_expression_alert_result.pine",
        "E_BRANCH_RETURN",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_while_expression_alert_result.pine",
        &["while expression branches must end with a value-producing expression"],
    );
}

#[test]
fn reports_unsupported_label_method_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_label_method.pine",
        "label.set_text_wrap",
        "drawing object",
    );
}

#[test]
fn reports_unsupported_label_getter_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_label_getter.pine",
        "label.get_style",
        "drawing object",
    );
}

#[test]
fn reports_unsupported_str_tostring_color_array_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_str_tostring_color_array.pine",
        &["`str.tostring` argument `value` expects string-convertible, got simple array<color>"],
    );
}

#[test]
fn accepts_supported_str_tostring_scalar_matrices_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_str_tostring_scalar_matrices.pine");
}

#[test]
fn reports_unsupported_str_tostring_color_matrix_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_str_tostring_color_matrix.pine",
        &["`str.tostring` argument `value` expects string-convertible, got simple matrix<color>"],
    );
}

#[test]
fn reports_unsupported_str_tostring_label_array_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_str_tostring_label_array.pine",
        &["`str.tostring` argument `value` expects string-convertible, got simple array<label>"],
    );
}

#[test]
fn reports_unsupported_str_tostring_chart_point_array_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_str_tostring_chart_point_array.pine",
        &[
            "`str.tostring` argument `value` expects string-convertible, got simple array<chart.point>",
        ],
    );
}

#[test]
fn reports_unsupported_str_tostring_udt_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_str_tostring_udt.pine",
        &["`str.tostring` argument `value` expects string-convertible, got series UDT"],
    );
}

#[test]
fn reports_unsupported_str_tostring_tuple_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_str_tostring_tuple.pine",
        &["`str.tostring` argument `value` expects string-convertible, got series tuple"],
    );
}

#[test]
fn reports_unsupported_str_format_color_array_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_str_format_color_array.pine",
        &["`str.format` argument `arg` expects string-convertible, got simple array<color>"],
    );
}

#[test]
fn reports_unsupported_str_format_matrix_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_str_format_matrix.pine",
        &["`str.format` argument `arg` expects string-convertible, got simple matrix<float>"],
    );
}

#[test]
fn reports_unsupported_str_format_label_array_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_str_format_label_array.pine",
        &["`str.format` argument `arg` expects string-convertible, got simple array<label>"],
    );
}

#[test]
fn reports_unsupported_str_format_chart_point_array_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_str_format_chart_point_array.pine",
        &["`str.format` argument `arg` expects string-convertible, got simple array<chart.point>"],
    );
}

#[test]
fn reports_unsupported_str_format_udt_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_str_format_udt.pine",
        &["`str.format` argument `arg` expects string-convertible, got series UDT"],
    );
}

#[test]
fn accepts_supported_str_split_simple_array_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_str_split_simple_array_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_str_split_simple_array_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_str_split_simple_array_return_qualifier.pine",
        &[
            "`matrix.add_row` argument `array_id` expects simple array<color>, got simple array<string>",
        ],
    );
}

#[test]
fn reports_unsupported_str_format_tuple_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_str_format_tuple.pine",
        &["`str.format` argument `arg` expects string-convertible, got series tuple"],
    );
}

#[test]
fn reports_unsupported_array_new_float_initial_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_new_float_initial.pine",
        &[
            "`array.new_float` argument `initial_value` expects numeric-compatible, got const string",
        ],
    );
}

#[test]
fn accepts_supported_array_new_float_na_initial_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_array_new_float_na_initial.pine");
}

#[test]
fn accepts_supported_array_new_fixed_simple_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_array_new_fixed_simple_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_array_new_fixed_simple_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_new_fixed_simple_return_qualifier.pine",
        &[
            "`matrix.add_row` argument `array_id` expects simple array<int>, got simple array<float>",
            "`matrix.add_row` argument `array_id` expects simple array<float>, got simple array<int>",
            "`matrix.add_row` argument `array_id` expects simple array<string>, got simple array<bool>",
            "`matrix.add_row` argument `array_id` expects simple array<color>, got simple array<string>",
            "`matrix.add_row` argument `array_id` expects simple array<bool>, got simple array<color>",
        ],
    );
}

#[test]
fn accepts_supported_array_new_template_fixed_simple_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_array_new_template_fixed_simple_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_array_new_template_fixed_simple_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_new_template_fixed_simple_return_qualifier.pine",
        &[
            "`matrix.add_row` argument `array_id` expects simple array<int>, got simple array<float>",
            "`matrix.add_row` argument `array_id` expects simple array<float>, got simple array<int>",
            "`matrix.add_row` argument `array_id` expects simple array<string>, got simple array<bool>",
            "`matrix.add_row` argument `array_id` expects simple array<color>, got simple array<string>",
            "`matrix.add_row` argument `array_id` expects simple array<bool>, got simple array<color>",
        ],
    );
}

#[test]
fn accepts_supported_object_array_new_fixed_simple_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_object_array_new_fixed_simple_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_object_array_new_fixed_simple_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_object_array_new_fixed_simple_return_qualifier.pine",
        &[
            "cannot pass simple array<label> to function parameter `values` of type series array<line>",
            "cannot pass simple array<line> to function parameter `values` of type series array<label>",
            "cannot pass simple array<polyline> to function parameter `values` of type series array<linefill>",
            "cannot pass simple array<linefill> to function parameter `values` of type series array<polyline>",
            "cannot pass simple array<box> to function parameter `values` of type series array<table>",
            "cannot pass simple array<table> to function parameter `values` of type series array<box>",
            "cannot pass simple array<label> to function parameter `values` of type series array<chart.point>",
        ],
    );
}

#[test]
fn accepts_supported_object_array_new_method_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_object_array_new_method_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_object_array_new_method_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_object_array_new_method_return_qualifier.pine",
        &[
            "cannot pass simple array<label> to method parameter `values` of type array<line>",
            "cannot pass simple array<line> to method parameter `values` of type array<label>",
            "cannot pass simple array<polyline> to method parameter `values` of type array<linefill>",
            "cannot pass simple array<linefill> to method parameter `values` of type array<polyline>",
            "cannot pass simple array<box> to method parameter `values` of type array<table>",
            "cannot pass simple array<table> to method parameter `values` of type array<box>",
            "cannot pass simple array<label> to method parameter `values` of type array<chart.point>",
        ],
    );
}

#[test]
fn reports_unsupported_array_new_chart_point_initial_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_new_chart_point_initial.pine",
        &[
            "`array.new<chart.point>` argument `initial_value` expects chart.point-compatible, got series float",
        ],
    );
}

#[test]
fn reports_unsupported_chart_point_typed_decl_initial_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_chart_point_typed_decl_initial.pine",
        &["cannot initialize `point` of type chart.point with series float"],
    );
}

#[test]
fn accepts_supported_chart_point_varip_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_chart_point_varip.pine");
}

#[test]
fn accepts_supported_chart_point_typed_udf_params_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_chart_point_typed_udf_params.pine");
}

#[test]
fn accepts_supported_chart_point_method_values_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_chart_point_method_values.pine");
}

#[test]
fn accepts_supported_chart_point_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_chart_point_return_qualifier.pine");
}

#[test]
fn reports_unsupported_chart_point_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_chart_point_return_qualifier.pine",
        &[
            "`hline` argument `price` expects const/input numeric, got series chart.point",
            "`hline` argument `price` expects const/input numeric, got series chart.point",
            "`hline` argument `price` expects const/input numeric, got series chart.point",
            "`hline` argument `price` expects const/input numeric, got series chart.point",
            "`hline` argument `price` expects const/input numeric, got series chart.point",
        ],
    );
}

#[test]
fn reports_unsupported_chart_point_typed_udf_param_mismatch_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_chart_point_typed_udf_param_mismatch.pine",
        &["cannot pass series float to function parameter `point` of type series chart.point"],
    );
}

#[test]
fn accepts_supported_array_typed_udf_params_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_array_typed_udf_params.pine");
}

#[test]
fn accepts_supported_object_array_typed_udf_params_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_object_array_typed_udf_params.pine");
}

#[test]
fn accepts_supported_user_type_array_typed_udf_params_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_user_type_array_typed_udf_params.pine");
}

#[test]
fn accepts_supported_user_type_array_typed_method_params_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_user_type_array_typed_method_params.pine");
}

#[test]
fn reports_unsupported_array_typed_udf_param_mismatch_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_typed_udf_param_mismatch.pine",
        &[
            "cannot pass simple array<float> to function parameter `values` of type series array<int>",
        ],
    );
}

#[test]
fn reports_unsupported_object_array_typed_udf_param_mismatch_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_object_array_typed_udf_param_mismatch.pine",
        &[
            "cannot pass simple array<label> to function parameter `values` of type series array<line>",
        ],
    );
}

#[test]
fn reports_unsupported_user_type_array_typed_udf_param_mismatch_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_user_type_array_typed_udf_param_mismatch.pine",
        &["cannot pass a different user-defined type array to function parameter `values`"],
    );
}

#[test]
fn reports_unsupported_user_type_array_typed_method_param_mismatch_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_user_type_array_typed_method_param_mismatch.pine",
        &["cannot pass a different user-defined type array to method parameter `values`"],
    );
}

#[test]
fn reports_unsupported_chart_point_array_typed_decl_initial_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_chart_point_array_typed_decl_initial.pine",
        &["cannot initialize `points` of type array<chart.point> with simple array<float>"],
    );
}

#[test]
fn reports_unsupported_scalar_typed_decl_initial_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_scalar_typed_decl_initial.pine",
        &["cannot initialize `count` of type int with const string"],
    );
}

#[test]
fn reports_unsupported_array_typed_decl_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_typed_decl.pine",
        &["typed declaration `array` is not supported"],
    );
}

#[test]
fn reports_unsupported_var_array_typed_decl_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_var_array_typed_decl.pine",
        &["typed declaration `array` is not supported"],
    );
}

#[test]
fn reports_unsupported_array_na_typed_decl_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_na_typed_decl.pine",
        &["typed declaration `array` is not supported"],
    );
}

#[test]
fn reports_unsupported_array_from_typed_decl_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_from_typed_decl.pine",
        &["typed declaration `array` is not supported"],
    );
}

#[test]
fn accepts_supported_array_from_udt_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_array_from_udt.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
}

#[test]
fn accepts_supported_array_from_same_udt_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_array_from_same_udt.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
}

#[test]
fn reports_unsupported_map_typed_decl_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_map_typed_decl.pine",
        &["typed declaration `map` is not supported"],
    );
}

#[test]
fn reports_unsupported_map_typed_decl_template_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_map_typed_decl_template.pine",
        "E_DECL_TYPE",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_map_typed_decl_template.pine",
        &["typed declaration `map<label,float>` is not supported"],
    );
}

#[test]
fn reports_unsupported_map_typed_decl_assign_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_map_typed_decl_assign.pine",
        "E_MAP_ASSIGN_TYPE",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_map_typed_decl_assign.pine",
        &["cannot assign a different map template to `values`"],
    );
}

#[test]
fn reports_unsupported_matrix_typed_decl_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_matrix_typed_decl.pine",
        &["typed declaration `matrix` is not supported"],
    );
}

#[test]
fn reports_unsupported_matrix_int_typed_decl_initial_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_matrix_int_typed_decl.pine",
        &["cannot initialize `values` of type matrix<int> with simple matrix<float>"],
    );
}

#[test]
fn reports_unsupported_matrix_label_typed_decl_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_matrix_label_typed_decl.pine",
        &["typed declaration `matrix<label>` is not supported"],
    );
}

#[test]
fn reports_matrix_for_in_row_array_plot_type_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_for_in.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn accepts_supported_matrix_for_in_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_matrix_for_in.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "for")
    );
}

#[test]
fn accepts_supported_matrix_varip_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_matrix_varip.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "varip")
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_user_type_array_decl_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_user_type_array_decl.pine");
}

#[test]
fn accepts_supported_user_type_array_alias_decl_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_user_type_array_alias_decl.pine");
}

#[test]
fn accepts_supported_user_type_array_control_flow_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_user_type_array_control_flow.pine");
}

#[test]
fn accepts_supported_user_type_array_udf_method_returns_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_user_type_array_udf_method_returns.pine");
}

#[test]
fn accepts_supported_user_type_array_tuple_returns_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_user_type_array_tuple_returns.pine");
}

#[test]
fn reports_unsupported_user_type_array_tuple_return_identities_fixture() {
    let path = "tests/fixtures/sema/unsupported_user_type_array_tuple_return_identities.pine";
    assert_diagnostic_messages(
        path,
        &[
            "tuple element 1 user-defined type array must resolve to one element identity",
            "tuple element 2 user-defined type array must resolve to one element identity",
            "cannot assign a different user-defined type array to `wrong_typed`",
        ],
    );
    assert_diagnostic_count(path, 24);

    let path = workspace_fixture(path);
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text.clone());
    let analysis = analyze_source(&source);
    let mut locations = HashSet::new();
    let tuple_diagnostics: Vec<_> = analysis
        .diagnostics
        .iter()
        .filter(|diagnostic| diagnostic.code == "E_TUPLE_UDT_ARRAY_IDENTITY")
        .collect();
    assert_eq!(tuple_diagnostics.len(), 23);
    for diagnostic in tuple_diagnostics {
        let excerpt = text
            .get(diagnostic.span.start..diagnostic.span.end)
            .expect("tuple identity diagnostic should point into the root fixture");
        assert!(
            excerpt.contains("bad"),
            "unexpected diagnostic span: {excerpt}"
        );
        assert!(locations.insert((
            diagnostic.message.clone(),
            diagnostic.span.start,
            diagnostic.span.end,
        )));
    }
}

#[test]
fn reports_unsupported_user_type_array_tuple_alias_mutation_fixture() {
    let path = "tests/fixtures/sema/unsupported_user_type_array_tuple_alias_mutation.pine";
    assert_diagnostic_messages(
        path,
        &[
            "tuple element 1 user-defined type array must resolve to one element identity",
            "tuple element 2 user-defined type array must resolve to one element identity",
        ],
    );
    assert_diagnostic_count(path, 16);

    let path = workspace_fixture(path);
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text.clone());
    let analysis = analyze_source(&source);
    let mut locations = HashSet::new();
    let root_markers = [
        "direct_mixed =",
        "direct_reassigned :=",
        "branch_reassigned :=",
        "bad_scalar =",
        "bad_loop =",
        "bad_tuple_decl_sink =",
        "bad_method_scalar =",
        "bad_method_tuple_decl_sink =",
    ];
    for diagnostic in analysis
        .diagnostics
        .iter()
        .filter(|diagnostic| diagnostic.code == "E_TUPLE_UDT_ARRAY_IDENTITY")
    {
        let line_start = text[..diagnostic.span.start]
            .rfind('\n')
            .map_or(0, |index| index + 1);
        let line_end = text[diagnostic.span.end..]
            .find('\n')
            .map_or(text.len(), |index| diagnostic.span.end + index);
        let line = &text[line_start..line_end];
        assert!(
            root_markers.iter().any(|marker| line.contains(marker)),
            "tuple identity diagnostic should point at a root call or reassignment, got `{line}`"
        );
        assert!(locations.insert((
            diagnostic.message.clone(),
            diagnostic.span.start,
            diagnostic.span.end,
        )));
    }
    assert_eq!(locations.len(), 16);
}

#[test]
fn reports_recursive_tuple_declarations_without_overflowing() {
    let path = "tests/fixtures/sema/unsupported_recursive_tuple_declarations.pine";
    assert_diagnostic_messages(
        path,
        &[
            "recursive function `direct` is not supported",
            "recursive function `wrapped` is not supported",
            "recursive function `mutualA` is not supported",
            "recursive method `recursive` is not supported",
        ],
    );
    assert_diagnostic_count(path, 4);
}

#[test]
fn accepts_supported_user_type_array_param_for_in_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_user_type_array_param_for_in.pine");
}

#[test]
fn reports_unsupported_user_type_array_udf_method_return_identities_fixture() {
    let path = "tests/fixtures/sema/unsupported_user_type_array_udf_method_return_identities.pine";
    assert_diagnostic_messages(
        path,
        &[
            "ternary UDT array branches must resolve to the same element identity",
            "if UDT array branches must resolve to the same element identity",
            "cannot assign a different user-defined type array to `wrong_typed`",
        ],
    );
    assert_diagnostic_count(path, 3);
}

#[test]
fn reports_unsupported_local_user_type_array_call_result_chaining_fixture() {
    let path = "tests/fixtures/sema/unsupported_local_user_type_array_call_result_chaining.pine";
    assert_diagnostic_messages(
        path,
        &[
            "`array.get` argument `index` expects simple integer-compatible, got const string",
            "`array.includes` argument `value` expects UDT `First`, got `Second`",
            "`array.includes` expects at most 2 argument(s), got 3",
            "`array.indexof` argument `value` expects UDT `First`, got `Second`",
            "`array.indexof` expects at most 2 argument(s), got 3",
            "`array.lastindexof` argument `value` expects UDT `First`, got `Second`",
            "`array.lastindexof` expects at most 2 argument(s), got 3",
            "`array.binary_search` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.binary_search_leftmost` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.binary_search_rightmost` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.sum` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.avg` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.range` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.median` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.mode` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.percentile_nearest_rank` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.percentile_linear_interpolation` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.transform` is not supported: direct array call-result methods currently support only `.size()`, `.get()`, `.first()`, `.last()`, `.copy()`, `.slice()`, `.concat()`, `.includes()`, `.every()`, `.some()`, `.indexof()`, `.lastindexof()`, `.binary_search()`, `.binary_search_leftmost()`, `.binary_search_rightmost()`, `.abs()`, `.min()`, `.max()`, `.sum()`, `.avg()`, `.range()`, `.median()`, `.mode()`, `.percentile_nearest_rank()`, `.percentile_linear_interpolation()`, `.percentrank()`, `.covariance()`, `.standardize()`, `.variance()`, `.stdev()`, `.sort_indices()`, `.join()`, `.clear()`, `.reverse()`, `.pop()`, `.shift()`, `.remove()`, `.push()`, `.unshift()`, `.insert()`, `.set()`, `.fill()`, and `.sort()`; bind the result or use the namespace helper",
            "`array.slice` argument `index_from` expects simple integer-compatible, got const string",
            "`array.slice` argument `index_to` expects simple integer-compatible, got const string",
            "`array.slice` expects at least 3 argument(s), got 2",
            "`array.slice` expects at most 3 argument(s), got 4",
            "ternary UDT array branches must resolve to the same element identity",
            "ternary UDT array branches must resolve to the same element identity",
            "ternary UDT array branches must resolve to the same element identity",
            "ternary UDT array branches must resolve to the same element identity",
            "`call_result.first` is not supported: direct call-result methods require a supported concrete receiver type; bind the result first",
            "`call_result.copy` is not supported: direct call-result methods require a supported concrete receiver type; bind the result first",
            "`call_result.size` is not supported: direct call-result methods require a supported concrete receiver type; bind the result first",
            "`call_result.get` is not supported: direct call-result methods require a supported concrete receiver type; bind the result first",
            "`call_result.last` is not supported: direct call-result methods require a supported concrete receiver type; bind the result first",
            "`array.includes` argument `value` expects UDT `First`, got `Second`",
            "`array.includes` argument `value` expects integer-compatible, got const string",
            "`array.indexof` argument `value` expects UDT `First`, got `Second`",
            "`array.indexof` argument `value` expects integer-compatible, got const string",
            "`array.lastindexof` argument `value` expects UDT `First`, got `Second`",
            "`array.lastindexof` argument `value` expects integer-compatible, got const string",
            "`array.binary_search` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.binary_search` argument `id` expects numeric array, got simple array<string>",
            "`array.binary_search` expects at most 2 argument(s), got 3",
            "`array.binary_search_leftmost` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.binary_search_leftmost` argument `id` expects numeric array, got simple array<string>",
            "`array.binary_search_leftmost` expects at most 2 argument(s), got 3",
            "`array.binary_search_rightmost` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.binary_search_rightmost` argument `id` expects numeric array, got simple array<string>",
            "`array.binary_search_rightmost` expects at most 2 argument(s), got 3",
            "`array.abs` argument `id` expects numeric array, got simple array<UDT>",
            "`array.abs` argument `id` expects numeric array, got simple array<string>",
            "`array.abs` expects at most 1 argument(s), got 2",
            "`array.min` argument `id` expects numeric array, got simple array<UDT>",
            "`array.min` argument `id` expects numeric array, got simple array<string>",
            "`array.min` argument `nth` expects integer-compatible, got const float",
            "`array.min` expects at most 2 argument(s), got 3",
            "`array.max` argument `id` expects numeric array, got simple array<UDT>",
            "`array.max` argument `id` expects numeric array, got simple array<string>",
            "`array.max` argument `nth` expects integer-compatible, got const float",
            "`array.max` expects at most 2 argument(s), got 3",
            "`array.sum` argument `id` expects numeric array, got simple array<UDT>",
            "`array.sum` argument `id` expects numeric array, got simple array<string>",
            "`array.sum` expects at most 1 argument(s), got 2",
            "`array.avg` argument `id` expects numeric array, got simple array<UDT>",
            "`array.avg` argument `id` expects numeric array, got simple array<string>",
            "`array.avg` expects at most 1 argument(s), got 2",
            "`array.range` argument `id` expects numeric array, got simple array<UDT>",
            "`array.range` argument `id` expects numeric array, got simple array<string>",
            "`array.range` expects at most 1 argument(s), got 2",
            "`array.median` argument `id` expects numeric array, got simple array<UDT>",
            "`array.median` argument `id` expects numeric array, got simple array<string>",
            "`array.median` expects at most 1 argument(s), got 2",
            "`array.mode` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.mode` argument `id` expects numeric array, got simple array<string>",
            "`array.mode` expects at most 1 argument(s), got 2",
            "`array.percentile_nearest_rank` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.percentile_nearest_rank` argument `id` expects numeric array, got simple array<string>",
            "`array.percentile_nearest_rank` expects at least 2 argument(s), got 1",
            "`array.percentile_nearest_rank` argument `percentage` expects series/simple numeric, got const string",
            "`array.percentile_nearest_rank` expects at most 2 argument(s), got 3",
            "`array.percentile_linear_interpolation` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.percentile_linear_interpolation` argument `id` expects numeric array, got simple array<string>",
            "`array.percentile_linear_interpolation` expects at least 2 argument(s), got 1",
            "`array.percentile_linear_interpolation` argument `percentage` expects series/simple numeric, got const string",
            "`array.percentile_linear_interpolation` expects at most 2 argument(s), got 3",
            "`array.percentrank` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.percentrank` argument `id` expects numeric array, got simple array<string>",
            "`array.percentrank` expects at least 2 argument(s), got 1",
            "`array.percentrank` argument `index` expects simple integer-compatible, got const string",
            "`array.percentrank` argument `index` expects simple integer-compatible, got series int",
            "`array.percentrank` expects at most 2 argument(s), got 3",
            "`array.covariance` argument `id1` expects numeric array, got simple array<UDT>",
            "`array.covariance` argument `id2` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.covariance` argument `id1` expects numeric array, got simple array<string>",
            "`array.covariance` argument `id2` expects numeric array, got simple array<string>",
            "`array.covariance` expects at least 2 argument(s), got 1",
            "`array.covariance` argument `biased` expects bool-compatible, got series float",
            "`array.covariance` expects at most 3 argument(s), got 4",
            "`array.standardize` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.standardize` argument `id` expects numeric array, got simple array<string>",
            "`array.standardize` expects at most 1 argument(s), got 2",
            "`array.variance` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.variance` argument `id` expects numeric array, got simple array<string>",
            "`array.variance` argument `biased` expects bool-compatible, got series float",
            "`array.variance` expects at most 2 argument(s), got 3",
            "`array.stdev` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.stdev` argument `id` expects numeric array, got simple array<string>",
            "`array.stdev` argument `biased` expects bool-compatible, got series float",
            "`array.stdev` expects at most 2 argument(s), got 3",
            "`array.sort_indices` requires a scalar-tree UDT array and a root int, float, or string `sort_field`",
            "`array.sort_indices` argument `sort_field` expects const int or string, got series string",
            "`array.sort_indices` argument `id` expects numeric/string array, got simple array<bool>",
            "`array.sort_indices` argument `order` expects const string, got series float",
            "`array.sort_indices` expects at most 2 argument(s), got 3",
            "`array.concat` expects at least 2 argument(s), got 1",
            "`array.concat` argument `id2` expects simple array<int>, got simple array<string>",
            "`array.concat` argument `id2` expects UDT array `First`, got `Second`",
            "`array.concat` expects at most 2 argument(s), got 3",
            "`array.transform` is not supported: direct array call-result methods currently support only `.size()`, `.get()`, `.first()`, `.last()`, `.copy()`, `.slice()`, `.concat()`, `.includes()`, `.every()`, `.some()`, `.indexof()`, `.lastindexof()`, `.binary_search()`, `.binary_search_leftmost()`, `.binary_search_rightmost()`, `.abs()`, `.min()`, `.max()`, `.sum()`, `.avg()`, `.range()`, `.median()`, `.mode()`, `.percentile_nearest_rank()`, `.percentile_linear_interpolation()`, `.percentrank()`, `.covariance()`, `.standardize()`, `.variance()`, `.stdev()`, `.sort_indices()`, `.join()`, `.clear()`, `.reverse()`, `.pop()`, `.shift()`, `.remove()`, `.push()`, `.unshift()`, `.insert()`, `.set()`, `.fill()`, and `.sort()`; bind the result or use the namespace helper",
            "ternary UDT array branches must resolve to the same element identity",
            "`call_result.first` is not supported: direct call-result methods require a supported concrete receiver type; bind the result first",
            "`call_result.copy` is not supported: direct call-result methods require a supported concrete receiver type; bind the result first",
            "`call_result.size` is not supported: direct call-result methods require a supported concrete receiver type; bind the result first",
            "`call_result.get` is not supported: direct call-result methods require a supported concrete receiver type; bind the result first",
            "`call_result.last` is not supported: direct call-result methods require a supported concrete receiver type; bind the result first",
            "`call_result.size` is not supported: direct call-result methods require a supported concrete receiver type; bind the result first",
            "`array.clear` expects at most 1 argument(s), got 2",
            "`array.reverse` expects at most 1 argument(s), got 2",
            "`array.pop` expects at most 1 argument(s), got 2",
            "`array.shift` expects at most 1 argument(s), got 2",
            "`array.remove` argument `index` expects simple integer-compatible, got const string",
            "`array.remove` expects at most 2 argument(s), got 3",
            "`array.push` argument `value` expects UDT `First`, got `Second`",
            "`array.push` expects at most 2 argument(s), got 3",
            "`array.unshift` argument `value` expects UDT `First`, got `Second`",
            "`array.unshift` expects at most 2 argument(s), got 3",
            "`array.insert` argument `index` expects simple integer-compatible, got const string",
            "`array.insert` argument `value` expects UDT `First`, got `Second`",
            "`array.insert` expects at most 3 argument(s), got 4",
            "`array.set` argument `index` expects simple integer-compatible, got const string",
            "`array.set` argument `value` expects UDT `First`, got `Second`",
            "`array.set` expects at most 3 argument(s), got 4",
            "`array.fill` argument `value` expects UDT `First`, got `Second`",
            "`array.fill` argument `index_from` expects simple integer-compatible, got const string",
            "`array.fill` argument `index_to` expects simple integer-compatible, got const string",
            "`array.fill` expects at most 4 argument(s), got 5",
            "`array.sort` requires a scalar-tree UDT array and a root int, float, or string `sort_field`",
            "`array.sort` argument `sort_field` expects const int or string, got series float",
            "`array.sort` argument `id` expects numeric/string array, got simple array<bool>",
            "`array.sort` argument `order` expects const string, got series float",
            "`array.sort` expects at most 2 argument(s), got 3",
        ],
    );
    assert_diagnostic_count(path, 210);
}

#[test]
fn accepts_supported_builtin_array_call_result_reads_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_builtin_array_call_result_reads.pine");
}

#[test]
fn accepts_supported_builtin_namespace_array_call_result_reads_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_builtin_namespace_array_call_result_reads.pine",
    );
}

#[test]
fn reports_unsupported_builtin_namespace_array_call_result_reads_fixture() {
    let path = "tests/fixtures/sema/unsupported_builtin_namespace_array_call_result_reads.pine";
    assert_exact_diagnostic_messages(
        path,
        &[
            "`array.get` argument `index` expects simple integer-compatible, got const string",
            "`array.push` argument `value` expects string-compatible, got const int",
            "`array.push` expects at least 2 argument(s), got 1",
            "`array.push` expects at most 2 argument(s), got 3",
            "`array.unshift` argument `value` expects string-compatible, got const int",
            "`array.unshift` expects at least 2 argument(s), got 1",
            "`array.unshift` expects at most 2 argument(s), got 3",
            "`array.insert` argument `index` expects simple integer-compatible, got const string",
            "`array.insert` argument `value` expects string-compatible, got const int",
            "`array.insert` expects at least 3 argument(s), got 2",
            "`array.insert` expects at most 3 argument(s), got 4",
            "`array.set` argument `index` expects simple integer-compatible, got const string",
            "`array.set` argument `value` expects string-compatible, got const int",
            "`array.set` expects at least 3 argument(s), got 2",
            "`array.set` expects at most 3 argument(s), got 4",
            "`array.fill` argument `value` expects string-compatible, got const int",
            "`array.fill` argument `index_from` expects simple integer-compatible, got const string",
            "`array.fill` argument `index_to` expects simple integer-compatible, got const string",
            "`array.fill` expects at least 2 argument(s), got 1",
            "`array.fill` expects at most 4 argument(s), got 5",
            "`array.sort` argument `id` expects numeric/string array, got simple array<bool>",
            "`array.sort` argument `id` expects numeric/string array, got simple array<color>",
            "`array.sort` argument `id` expects numeric/string array, got simple array<bool>",
            "`array.sort` argument `order` expects const string, got series float",
            "`array.sort` expects at most 2 argument(s), got 3",
            "`array.get` argument `index` expects simple integer-compatible, got const string",
            "`matrix.row` argument `row` expects simple int, got const string",
            "`matrix.col` argument `column` expects simple int, got const string",
            "`array.get` argument `index` expects simple integer-compatible, got const string",
            "`array.get` argument `index` expects simple integer-compatible, got const string",
            "`array.get` argument `index` expects simple integer-compatible, got const string",
            "`array.get` argument `index` expects simple integer-compatible, got const string",
            "`array.remove` argument `index` expects simple integer-compatible, got const string",
            "`array.remove` expects at least 2 argument(s), got 1",
            "`array.remove` expects at most 2 argument(s), got 3",
            "`array.get` argument `index` expects simple integer-compatible, got const string",
            "`array.includes` argument `value` expects string-compatible, got const int",
            "`array.includes` argument `value` expects numeric-compatible, got const string",
            "`array.includes` argument `value` expects numeric-compatible, got const string",
            "`array.includes` argument `value` expects string-compatible, got const int",
            "`array.includes` argument `value` expects numeric-compatible, got const string",
            "`array.includes` argument `value` expects numeric-compatible, got const string",
            "`array.includes` expects at most 2 argument(s), got 3",
            "`array.indexof` argument `value` expects string-compatible, got const int",
            "`array.indexof` argument `value` expects numeric-compatible, got const string",
            "`array.indexof` argument `value` expects numeric-compatible, got const string",
            "`array.indexof` argument `value` expects string-compatible, got const int",
            "`array.indexof` argument `value` expects numeric-compatible, got const string",
            "`array.indexof` argument `value` expects numeric-compatible, got const string",
            "`array.indexof` expects at most 2 argument(s), got 3",
            "`array.lastindexof` argument `value` expects string-compatible, got const int",
            "`array.lastindexof` argument `value` expects numeric-compatible, got const string",
            "`array.lastindexof` argument `value` expects numeric-compatible, got const string",
            "`array.lastindexof` argument `value` expects string-compatible, got const int",
            "`array.lastindexof` argument `value` expects numeric-compatible, got const string",
            "`array.lastindexof` argument `value` expects numeric-compatible, got const string",
            "`array.lastindexof` expects at most 2 argument(s), got 3",
            "`array.binary_search` argument `id` expects numeric array, got simple array<string>",
            "`array.binary_search` argument `id` expects numeric array, got simple array<bool>",
            "`array.binary_search` argument `id` expects numeric array, got simple array<string>",
            "`array.binary_search` argument `id` expects numeric array, got simple array<color>",
            "`array.binary_search` argument `id` expects numeric array, got simple array<bool>",
            "`array.binary_search` argument `id` expects numeric array, got simple array<string>",
            "`array.binary_search` argument `value` expects numeric-compatible, got const string",
            "`array.binary_search` expects at most 2 argument(s), got 3",
            "`array.binary_search_leftmost` argument `id` expects numeric array, got simple array<string>",
            "`array.binary_search_leftmost` argument `id` expects numeric array, got simple array<bool>",
            "`array.binary_search_leftmost` argument `id` expects numeric array, got simple array<string>",
            "`array.binary_search_leftmost` argument `id` expects numeric array, got simple array<color>",
            "`array.binary_search_leftmost` argument `id` expects numeric array, got simple array<bool>",
            "`array.binary_search_leftmost` argument `id` expects numeric array, got simple array<string>",
            "`array.binary_search_leftmost` argument `value` expects numeric-compatible, got const string",
            "`array.binary_search_leftmost` expects at most 2 argument(s), got 3",
            "`array.binary_search_rightmost` argument `id` expects numeric array, got simple array<string>",
            "`array.binary_search_rightmost` argument `id` expects numeric array, got simple array<bool>",
            "`array.binary_search_rightmost` argument `id` expects numeric array, got simple array<string>",
            "`array.binary_search_rightmost` argument `id` expects numeric array, got simple array<color>",
            "`array.binary_search_rightmost` argument `id` expects numeric array, got simple array<bool>",
            "`array.binary_search_rightmost` argument `id` expects numeric array, got simple array<string>",
            "`array.binary_search_rightmost` argument `value` expects numeric-compatible, got const string",
            "`array.binary_search_rightmost` expects at most 2 argument(s), got 3",
            "`array.abs` argument `id` expects numeric array, got simple array<string>",
            "`array.abs` argument `id` expects numeric array, got simple array<bool>",
            "`array.abs` argument `id` expects numeric array, got simple array<string>",
            "`array.abs` argument `id` expects numeric array, got simple array<color>",
            "`array.abs` argument `id` expects numeric array, got simple array<bool>",
            "`array.abs` argument `id` expects numeric array, got simple array<string>",
            "`array.abs` expects at most 1 argument(s), got 2",
            "`array.min` argument `id` expects numeric array, got simple array<string>",
            "`array.min` argument `id` expects numeric array, got simple array<bool>",
            "`array.min` argument `id` expects numeric array, got simple array<string>",
            "`array.min` argument `id` expects numeric array, got simple array<color>",
            "`array.min` argument `id` expects numeric array, got simple array<bool>",
            "`array.min` argument `id` expects numeric array, got simple array<string>",
            "`array.min` argument `nth` expects integer-compatible, got const float",
            "`array.min` argument `nth` expects integer-compatible, got const string",
            "`array.min` expects at most 2 argument(s), got 3",
            "`array.max` argument `id` expects numeric array, got simple array<string>",
            "`array.max` argument `id` expects numeric array, got simple array<bool>",
            "`array.max` argument `id` expects numeric array, got simple array<string>",
            "`array.max` argument `id` expects numeric array, got simple array<color>",
            "`array.max` argument `id` expects numeric array, got simple array<bool>",
            "`array.max` argument `id` expects numeric array, got simple array<string>",
            "`array.max` argument `nth` expects integer-compatible, got const float",
            "`array.max` argument `nth` expects integer-compatible, got const string",
            "`array.max` expects at most 2 argument(s), got 3",
            "`array.sum` argument `id` expects numeric array, got simple array<string>",
            "`array.sum` argument `id` expects numeric array, got simple array<bool>",
            "`array.sum` argument `id` expects numeric array, got simple array<string>",
            "`array.sum` argument `id` expects numeric array, got simple array<color>",
            "`array.sum` argument `id` expects numeric array, got simple array<bool>",
            "`array.sum` argument `id` expects numeric array, got simple array<string>",
            "`array.sum` expects at most 1 argument(s), got 2",
            "`array.avg` argument `id` expects numeric array, got simple array<string>",
            "`array.avg` argument `id` expects numeric array, got simple array<bool>",
            "`array.avg` argument `id` expects numeric array, got simple array<string>",
            "`array.avg` argument `id` expects numeric array, got simple array<color>",
            "`array.avg` argument `id` expects numeric array, got simple array<bool>",
            "`array.avg` argument `id` expects numeric array, got simple array<string>",
            "`array.avg` expects at most 1 argument(s), got 2",
            "`array.range` argument `id` expects numeric array, got simple array<string>",
            "`array.range` argument `id` expects numeric array, got simple array<bool>",
            "`array.range` argument `id` expects numeric array, got simple array<string>",
            "`array.range` argument `id` expects numeric array, got simple array<color>",
            "`array.range` argument `id` expects numeric array, got simple array<bool>",
            "`array.range` argument `id` expects numeric array, got simple array<string>",
            "`array.range` expects at most 1 argument(s), got 2",
            "`array.median` argument `id` expects numeric array, got simple array<string>",
            "`array.median` argument `id` expects numeric array, got simple array<bool>",
            "`array.median` argument `id` expects numeric array, got simple array<string>",
            "`array.median` argument `id` expects numeric array, got simple array<color>",
            "`array.median` argument `id` expects numeric array, got simple array<bool>",
            "`array.median` argument `id` expects numeric array, got simple array<string>",
            "`array.median` expects at most 1 argument(s), got 2",
            "`array.mode` argument `id` expects numeric array, got simple array<string>",
            "`array.mode` argument `id` expects numeric array, got simple array<bool>",
            "`array.mode` argument `id` expects numeric array, got simple array<string>",
            "`array.mode` argument `id` expects numeric array, got simple array<color>",
            "`array.mode` argument `id` expects numeric array, got simple array<bool>",
            "`array.mode` argument `id` expects numeric array, got simple array<string>",
            "`array.mode` expects at most 1 argument(s), got 2",
            "`array.percentile_nearest_rank` argument `id` expects numeric array, got simple array<string>",
            "`array.percentile_nearest_rank` argument `id` expects numeric array, got simple array<bool>",
            "`array.percentile_nearest_rank` argument `id` expects numeric array, got simple array<string>",
            "`array.percentile_nearest_rank` argument `id` expects numeric array, got simple array<color>",
            "`array.percentile_nearest_rank` argument `id` expects numeric array, got simple array<bool>",
            "`array.percentile_nearest_rank` argument `id` expects numeric array, got simple array<string>",
            "`array.percentile_nearest_rank` expects at least 2 argument(s), got 1",
            "`array.percentile_nearest_rank` argument `percentage` expects series/simple numeric, got const string",
            "`array.percentile_nearest_rank` expects at most 2 argument(s), got 3",
            "`array.percentile_linear_interpolation` argument `id` expects numeric array, got simple array<string>",
            "`array.percentile_linear_interpolation` argument `id` expects numeric array, got simple array<bool>",
            "`array.percentile_linear_interpolation` argument `id` expects numeric array, got simple array<string>",
            "`array.percentile_linear_interpolation` argument `id` expects numeric array, got simple array<color>",
            "`array.percentile_linear_interpolation` argument `id` expects numeric array, got simple array<bool>",
            "`array.percentile_linear_interpolation` argument `id` expects numeric array, got simple array<string>",
            "`array.percentile_linear_interpolation` expects at least 2 argument(s), got 1",
            "`array.percentile_linear_interpolation` argument `percentage` expects series/simple numeric, got const string",
            "`array.percentile_linear_interpolation` expects at most 2 argument(s), got 3",
            "`array.percentrank` argument `id` expects numeric array, got simple array<string>",
            "`array.percentrank` argument `id` expects numeric array, got simple array<bool>",
            "`array.percentrank` argument `id` expects numeric array, got simple array<string>",
            "`array.percentrank` argument `id` expects numeric array, got simple array<color>",
            "`array.percentrank` argument `id` expects numeric array, got simple array<bool>",
            "`array.percentrank` argument `id` expects numeric array, got simple array<string>",
            "`array.percentrank` expects at least 2 argument(s), got 1",
            "`array.percentrank` argument `index` expects simple integer-compatible, got const string",
            "`array.percentrank` argument `index` expects simple integer-compatible, got series int",
            "`array.percentrank` expects at most 2 argument(s), got 3",
            "`array.covariance` argument `id1` expects numeric array, got simple array<string>",
            "`array.covariance` argument `id1` expects numeric array, got simple array<bool>",
            "`array.covariance` argument `id1` expects numeric array, got simple array<string>",
            "`array.covariance` argument `id1` expects numeric array, got simple array<color>",
            "`array.covariance` argument `id1` expects numeric array, got simple array<bool>",
            "`array.covariance` argument `id1` expects numeric array, got simple array<string>",
            "`array.covariance` argument `id2` expects numeric array, got simple array<string>",
            "`array.covariance` expects at least 2 argument(s), got 1",
            "`array.covariance` argument `biased` expects bool-compatible, got series float",
            "`array.covariance` expects at most 3 argument(s), got 4",
            "`array.standardize` argument `id` expects numeric array, got simple array<string>",
            "`array.standardize` argument `id` expects numeric array, got simple array<bool>",
            "`array.standardize` argument `id` expects numeric array, got simple array<string>",
            "`array.standardize` argument `id` expects numeric array, got simple array<color>",
            "`array.standardize` argument `id` expects numeric array, got simple array<bool>",
            "`array.standardize` argument `id` expects numeric array, got simple array<string>",
            "`array.standardize` expects at most 1 argument(s), got 2",
            "`array.variance` argument `id` expects numeric array, got simple array<string>",
            "`array.variance` argument `id` expects numeric array, got simple array<bool>",
            "`array.variance` argument `id` expects numeric array, got simple array<string>",
            "`array.variance` argument `id` expects numeric array, got simple array<color>",
            "`array.variance` argument `id` expects numeric array, got simple array<bool>",
            "`array.variance` argument `id` expects numeric array, got simple array<string>",
            "`array.variance` argument `biased` expects bool-compatible, got series float",
            "`array.variance` expects at most 2 argument(s), got 3",
            "`array.stdev` argument `id` expects numeric array, got simple array<string>",
            "`array.stdev` argument `id` expects numeric array, got simple array<bool>",
            "`array.stdev` argument `id` expects numeric array, got simple array<string>",
            "`array.stdev` argument `id` expects numeric array, got simple array<color>",
            "`array.stdev` argument `id` expects numeric array, got simple array<bool>",
            "`array.stdev` argument `id` expects numeric array, got simple array<string>",
            "`array.stdev` argument `biased` expects bool-compatible, got series float",
            "`array.stdev` expects at most 2 argument(s), got 3",
            "`array.sort_indices` argument `id` expects numeric/string array, got simple array<bool>",
            "`array.sort_indices` argument `id` expects numeric/string array, got simple array<color>",
            "`array.sort_indices` argument `id` expects numeric/string array, got simple array<bool>",
            "`array.sort_indices` argument `id` expects numeric/string array, got simple array<color>",
            "`array.sort_indices` argument `order` expects const string, got series float",
            "`array.sort_indices` expects at most 2 argument(s), got 3",
            "`array.every` argument `id` expects numeric/bool array, got simple array<string>",
            "`array.every` argument `id` expects numeric/bool array, got simple array<string>",
            "`array.every` argument `id` expects numeric/bool array, got simple array<color>",
            "`array.every` argument `id` expects numeric/bool array, got simple array<string>",
            "`array.every` argument `id` expects numeric/bool array, got simple array<color>",
            "`array.every` expects at most 1 argument(s), got 2",
            "`array.some` argument `id` expects numeric/bool array, got simple array<string>",
            "`array.some` argument `id` expects numeric/bool array, got simple array<string>",
            "`array.some` argument `id` expects numeric/bool array, got simple array<color>",
            "`array.some` argument `id` expects numeric/bool array, got simple array<string>",
            "`array.some` argument `id` expects numeric/bool array, got simple array<color>",
            "`array.some` expects at most 1 argument(s), got 2",
            "`array.join` argument `separator` expects string-compatible, got series float",
            "`array.join` expects at most 2 argument(s), got 3",
            "`array.slice` argument `index_from` expects simple integer-compatible, got const string",
            "`array.slice` argument `index_to` expects simple integer-compatible, got const string",
            "`array.slice` expects at least 3 argument(s), got 2",
            "`array.slice` expects at most 3 argument(s), got 4",
            "`array.clear` expects at most 1 argument(s), got 2",
            "`array.reverse` expects at most 1 argument(s), got 2",
            "`array.pop` expects at most 1 argument(s), got 2",
            "`array.shift` expects at most 1 argument(s), got 2",
        ],
    );
    assert_diagnostic_count(path, 230);
}

#[test]
fn accepts_supported_builtin_namespace_matrix_call_result_reads_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_builtin_namespace_matrix_call_result_reads.pine",
    );
}

#[test]
fn accepts_supported_bound_matrix_copy_call_result_reads_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_bound_matrix_copy_call_result_reads.pine");
}

#[test]
fn accepts_supported_bound_matrix_transpose_call_result_reads_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_bound_matrix_transpose_call_result_reads.pine",
    );
}

#[test]
fn accepts_supported_bound_matrix_submatrix_call_result_reads_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_bound_matrix_submatrix_call_result_reads.pine",
    );
}

#[test]
fn accepts_supported_bound_matrix_kron_call_result_reads_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_bound_matrix_kron_call_result_reads.pine");
}

#[test]
fn accepts_supported_bound_matrix_diff_call_result_reads_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_bound_matrix_diff_call_result_reads.pine");
}

#[test]
fn accepts_supported_bound_matrix_pow_call_result_reads_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_bound_matrix_pow_call_result_reads.pine");
}

#[test]
fn reports_unsupported_bound_matrix_pow_call_result_reads_fixture() {
    let path = "tests/fixtures/sema/unsupported_bound_matrix_pow_call_result_reads.pine";
    assert_exact_diagnostic_messages(
        path,
        &[
            "`matrix.pow` argument `power` expects simple int, got const string",
            "`matrix.get` argument `row` expects simple int, got const string",
            "`matrix.set` argument `value` expects numeric-compatible, got const string",
            "`matrix.size` is not supported: direct matrix call-result methods currently support only `.rows()`, `.columns()`, `.elements_count()`, `.get()`, `.set()`, `.fill()`, `.reverse()`, `.reshape()`, `.add_row()`, `.add_col()`, numeric-only `.sort()`, `.swap_rows()`, `.swap_columns()`, `.remove_row()`, `.remove_col()`, `.copy()`, `.diff()`, `.eigenvectors()`, `.inv()`, `.kron()`, `.mult()`, `.pinv()`, `.pow()`, `.submatrix()`, `.transpose()`, `.row()`, `.col()`, `.eigenvalues()`, `.is_square()`, `.is_zero()`, `.is_binary()`, `.is_diagonal()`, `.is_identity()`, `.is_symmetric()`, `.is_antisymmetric()`, `.is_stochastic()`, `.sum()`, `.avg()`, `.min()`, `.max()`, `.mode()`, `.trace()`, `.det()`, and `.rank()`; bind the result or use the namespace helper",
            "method `pow` is not supported for simple matrix<bool>",
            "unknown array method `pow`",
        ],
    );
    assert_diagnostic_count(path, 6);
}

#[test]
fn accepts_supported_bound_matrix_inv_call_result_reads_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_bound_matrix_inv_call_result_reads.pine");
}

#[test]
fn reports_unsupported_bound_matrix_inv_call_result_reads_fixture() {
    let path = "tests/fixtures/sema/unsupported_bound_matrix_inv_call_result_reads.pine";
    assert_exact_diagnostic_messages(
        path,
        &[
            "`matrix.get` argument `row` expects simple int, got const string",
            "`matrix.set` argument `value` expects numeric-compatible, got const string",
            "`matrix.size` is not supported: direct matrix call-result methods currently support only `.rows()`, `.columns()`, `.elements_count()`, `.get()`, `.set()`, `.fill()`, `.reverse()`, `.reshape()`, `.add_row()`, `.add_col()`, numeric-only `.sort()`, `.swap_rows()`, `.swap_columns()`, `.remove_row()`, `.remove_col()`, `.copy()`, `.diff()`, `.eigenvectors()`, `.inv()`, `.kron()`, `.mult()`, `.pinv()`, `.pow()`, `.submatrix()`, `.transpose()`, `.row()`, `.col()`, `.eigenvalues()`, `.is_square()`, `.is_zero()`, `.is_binary()`, `.is_diagonal()`, `.is_identity()`, `.is_symmetric()`, `.is_antisymmetric()`, `.is_stochastic()`, `.sum()`, `.avg()`, `.min()`, `.max()`, `.mode()`, `.trace()`, `.det()`, and `.rank()`; bind the result or use the namespace helper",
            "method `inv` is not supported for simple matrix<bool>",
            "unknown array method `inv`",
        ],
    );
    assert_diagnostic_count(path, 5);
}

#[test]
fn accepts_supported_bound_matrix_pinv_call_result_reads_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_bound_matrix_pinv_call_result_reads.pine");
}

#[test]
fn reports_unsupported_bound_matrix_pinv_call_result_reads_fixture() {
    let path = "tests/fixtures/sema/unsupported_bound_matrix_pinv_call_result_reads.pine";
    assert_exact_diagnostic_messages(
        path,
        &[
            "`matrix.get` argument `row` expects simple int, got const string",
            "`matrix.set` argument `value` expects numeric-compatible, got const string",
            "`matrix.size` is not supported: direct matrix call-result methods currently support only `.rows()`, `.columns()`, `.elements_count()`, `.get()`, `.set()`, `.fill()`, `.reverse()`, `.reshape()`, `.add_row()`, `.add_col()`, numeric-only `.sort()`, `.swap_rows()`, `.swap_columns()`, `.remove_row()`, `.remove_col()`, `.copy()`, `.diff()`, `.eigenvectors()`, `.inv()`, `.kron()`, `.mult()`, `.pinv()`, `.pow()`, `.submatrix()`, `.transpose()`, `.row()`, `.col()`, `.eigenvalues()`, `.is_square()`, `.is_zero()`, `.is_binary()`, `.is_diagonal()`, `.is_identity()`, `.is_symmetric()`, `.is_antisymmetric()`, `.is_stochastic()`, `.sum()`, `.avg()`, `.min()`, `.max()`, `.mode()`, `.trace()`, `.det()`, and `.rank()`; bind the result or use the namespace helper",
            "method `pinv` is not supported for simple matrix<bool>",
            "unknown array method `pinv`",
        ],
    );
    assert_diagnostic_count(path, 5);
}

#[test]
fn accepts_supported_bound_matrix_eigenvectors_call_result_reads_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_bound_matrix_eigenvectors_call_result_reads.pine",
    );
}

#[test]
fn reports_unsupported_bound_matrix_eigenvectors_call_result_reads_fixture() {
    let path = "tests/fixtures/sema/unsupported_bound_matrix_eigenvectors_call_result_reads.pine";
    assert_exact_diagnostic_messages(
        path,
        &[
            "`matrix.get` argument `row` expects simple int, got const string",
            "`matrix.set` argument `value` expects numeric-compatible, got const string",
            "`matrix.size` is not supported: direct matrix call-result methods currently support only `.rows()`, `.columns()`, `.elements_count()`, `.get()`, `.set()`, `.fill()`, `.reverse()`, `.reshape()`, `.add_row()`, `.add_col()`, numeric-only `.sort()`, `.swap_rows()`, `.swap_columns()`, `.remove_row()`, `.remove_col()`, `.copy()`, `.diff()`, `.eigenvectors()`, `.inv()`, `.kron()`, `.mult()`, `.pinv()`, `.pow()`, `.submatrix()`, `.transpose()`, `.row()`, `.col()`, `.eigenvalues()`, `.is_square()`, `.is_zero()`, `.is_binary()`, `.is_diagonal()`, `.is_identity()`, `.is_symmetric()`, `.is_antisymmetric()`, `.is_stochastic()`, `.sum()`, `.avg()`, `.min()`, `.max()`, `.mode()`, `.trace()`, `.det()`, and `.rank()`; bind the result or use the namespace helper",
            "method `eigenvectors` is not supported for simple matrix<bool>",
            "unknown array method `eigenvectors`",
        ],
    );
    assert_diagnostic_count(path, 5);
}

#[test]
fn accepts_supported_bound_matrix_mult_call_result_reads_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_bound_matrix_mult_call_result_reads.pine");
}

#[test]
fn reports_unsupported_bound_matrix_mult_call_result_reads_fixture() {
    let path = "tests/fixtures/sema/unsupported_bound_matrix_mult_call_result_reads.pine";
    assert_exact_diagnostic_messages(
        path,
        &[
            "`matrix.get` argument `row` expects simple int, got const string",
            "`matrix.set` argument `value` expects numeric-compatible, got const string",
            "`matrix.size` is not supported: direct matrix call-result methods currently support only `.rows()`, `.columns()`, `.elements_count()`, `.get()`, `.set()`, `.fill()`, `.reverse()`, `.reshape()`, `.add_row()`, `.add_col()`, numeric-only `.sort()`, `.swap_rows()`, `.swap_columns()`, `.remove_row()`, `.remove_col()`, `.copy()`, `.diff()`, `.eigenvectors()`, `.inv()`, `.kron()`, `.mult()`, `.pinv()`, `.pow()`, `.submatrix()`, `.transpose()`, `.row()`, `.col()`, `.eigenvalues()`, `.is_square()`, `.is_zero()`, `.is_binary()`, `.is_diagonal()`, `.is_identity()`, `.is_symmetric()`, `.is_antisymmetric()`, `.is_stochastic()`, `.sum()`, `.avg()`, `.min()`, `.max()`, `.mode()`, `.trace()`, `.det()`, and `.rank()`; bind the result or use the namespace helper",
            "`array.rows` is not supported: direct array call-result methods currently support only `.size()`, `.get()`, `.first()`, `.last()`, `.copy()`, `.slice()`, `.concat()`, `.includes()`, `.every()`, `.some()`, `.indexof()`, `.lastindexof()`, `.binary_search()`, `.binary_search_leftmost()`, `.binary_search_rightmost()`, `.abs()`, `.min()`, `.max()`, `.sum()`, `.avg()`, `.range()`, `.median()`, `.mode()`, `.percentile_nearest_rank()`, `.percentile_linear_interpolation()`, `.percentrank()`, `.covariance()`, `.standardize()`, `.variance()`, `.stdev()`, `.sort_indices()`, `.join()`, `.clear()`, `.reverse()`, `.pop()`, `.shift()`, `.remove()`, `.push()`, `.unshift()`, `.insert()`, `.set()`, `.fill()`, and `.sort()`; bind the result or use the namespace helper",
            "method `mult` is not supported for simple matrix<bool>",
            "unknown array method `mult`",
        ],
    );
    assert_diagnostic_count(path, 6);
}

#[test]
fn accepts_supported_local_udf_matrix_call_result_reads_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_local_udf_matrix_call_result_reads.pine");
}

#[test]
fn reports_unsupported_local_udf_matrix_call_result_reads_fixture() {
    let path = "tests/fixtures/sema/unsupported_local_udf_matrix_call_result_reads.pine";
    assert_exact_diagnostic_messages(
        path,
        &[
            "`matrix.get` argument `row` expects simple int, got const string",
            "`matrix.set` argument `value` expects numeric-compatible, got const string",
            "`matrix.size` is not supported: direct matrix call-result methods currently support only `.rows()`, `.columns()`, `.elements_count()`, `.get()`, `.set()`, `.fill()`, `.reverse()`, `.reshape()`, `.add_row()`, `.add_col()`, numeric-only `.sort()`, `.swap_rows()`, `.swap_columns()`, `.remove_row()`, `.remove_col()`, `.copy()`, `.diff()`, `.eigenvectors()`, `.inv()`, `.kron()`, `.mult()`, `.pinv()`, `.pow()`, `.submatrix()`, `.transpose()`, `.row()`, `.col()`, `.eigenvalues()`, `.is_square()`, `.is_zero()`, `.is_binary()`, `.is_diagonal()`, `.is_identity()`, `.is_symmetric()`, `.is_antisymmetric()`, `.is_stochastic()`, `.sum()`, `.avg()`, `.min()`, `.max()`, `.mode()`, `.trace()`, `.det()`, and `.rank()`; bind the result or use the namespace helper",
            "`call_result.copy` is not supported: direct call-result methods require a supported concrete receiver type; bind the result first",
            "`call_result.rows` is not supported: direct call-result methods require a supported concrete receiver type; bind the result first",
            "`call_result.rows` is not supported: direct call-result methods require a supported concrete receiver type; bind the result first",
            "`array.rows` is not supported: direct array call-result methods currently support only `.size()`, `.get()`, `.first()`, `.last()`, `.copy()`, `.slice()`, `.concat()`, `.includes()`, `.every()`, `.some()`, `.indexof()`, `.lastindexof()`, `.binary_search()`, `.binary_search_leftmost()`, `.binary_search_rightmost()`, `.abs()`, `.min()`, `.max()`, `.sum()`, `.avg()`, `.range()`, `.median()`, `.mode()`, `.percentile_nearest_rank()`, `.percentile_linear_interpolation()`, `.percentrank()`, `.covariance()`, `.standardize()`, `.variance()`, `.stdev()`, `.sort_indices()`, `.join()`, `.clear()`, `.reverse()`, `.pop()`, `.shift()`, `.remove()`, `.push()`, `.unshift()`, `.insert()`, `.set()`, `.fill()`, and `.sort()`; bind the result or use the namespace helper",
            "`map.rows` is not supported: direct map call-result methods currently support only `.size()`, terminal `.put()`, `.clear()`, `.remove()`, and `.put_all()`, `.get()`, `.contains()`, `.copy()`, `.keys()`, and `.values()`; bind the result or use the namespace helper",
        ],
    );
    assert_diagnostic_count(path, 8);
}

#[test]
fn accepts_supported_user_method_matrix_call_result_reads_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_user_method_matrix_call_result_reads.pine");
}

#[test]
fn reports_unsupported_user_method_matrix_call_result_reads_fixture() {
    let path = "tests/fixtures/sema/unsupported_user_method_matrix_call_result_reads.pine";
    assert_exact_diagnostic_messages(
        path,
        &[
            "`matrix.get` argument `row` expects simple int, got const string",
            "`matrix.set` argument `value` expects numeric-compatible, got const string",
            "`matrix.size` is not supported: direct matrix call-result methods currently support only `.rows()`, `.columns()`, `.elements_count()`, `.get()`, `.set()`, `.fill()`, `.reverse()`, `.reshape()`, `.add_row()`, `.add_col()`, numeric-only `.sort()`, `.swap_rows()`, `.swap_columns()`, `.remove_row()`, `.remove_col()`, `.copy()`, `.diff()`, `.eigenvectors()`, `.inv()`, `.kron()`, `.mult()`, `.pinv()`, `.pow()`, `.submatrix()`, `.transpose()`, `.row()`, `.col()`, `.eigenvalues()`, `.is_square()`, `.is_zero()`, `.is_binary()`, `.is_diagonal()`, `.is_identity()`, `.is_symmetric()`, `.is_antisymmetric()`, `.is_stochastic()`, `.sum()`, `.avg()`, `.min()`, `.max()`, `.mode()`, `.trace()`, `.det()`, and `.rank()`; bind the result or use the namespace helper",
            "`call_result.copy` is not supported: direct call-result methods require a supported concrete receiver type; bind the result first",
            "`call_result.rows` is not supported: direct call-result methods require a supported concrete receiver type; bind the result first",
            "`call_result.rows` is not supported: direct call-result methods require a supported concrete receiver type; bind the result first",
            "`array.rows` is not supported: direct array call-result methods currently support only `.size()`, `.get()`, `.first()`, `.last()`, `.copy()`, `.slice()`, `.concat()`, `.includes()`, `.every()`, `.some()`, `.indexof()`, `.lastindexof()`, `.binary_search()`, `.binary_search_leftmost()`, `.binary_search_rightmost()`, `.abs()`, `.min()`, `.max()`, `.sum()`, `.avg()`, `.range()`, `.median()`, `.mode()`, `.percentile_nearest_rank()`, `.percentile_linear_interpolation()`, `.percentrank()`, `.covariance()`, `.standardize()`, `.variance()`, `.stdev()`, `.sort_indices()`, `.join()`, `.clear()`, `.reverse()`, `.pop()`, `.shift()`, `.remove()`, `.push()`, `.unshift()`, `.insert()`, `.set()`, `.fill()`, and `.sort()`; bind the result or use the namespace helper",
            "`map.rows` is not supported: direct map call-result methods currently support only `.size()`, terminal `.put()`, `.clear()`, `.remove()`, and `.put_all()`, `.get()`, `.contains()`, `.copy()`, `.keys()`, and `.values()`; bind the result or use the namespace helper",
        ],
    );
    assert_diagnostic_count(path, 8);
}

#[test]
fn reports_unsupported_bound_matrix_diff_call_result_reads_fixture() {
    let path = "tests/fixtures/sema/unsupported_bound_matrix_diff_call_result_reads.pine";
    assert_exact_diagnostic_messages(
        path,
        &[
            "`matrix.diff` argument `id2` expects numeric matrix or numeric-compatible, got simple array<float>",
            "`matrix.get` argument `row` expects simple int, got const string",
            "`matrix.set` argument `value` expects numeric-compatible, got const string",
            "`matrix.size` is not supported: direct matrix call-result methods currently support only `.rows()`, `.columns()`, `.elements_count()`, `.get()`, `.set()`, `.fill()`, `.reverse()`, `.reshape()`, `.add_row()`, `.add_col()`, numeric-only `.sort()`, `.swap_rows()`, `.swap_columns()`, `.remove_row()`, `.remove_col()`, `.copy()`, `.diff()`, `.eigenvectors()`, `.inv()`, `.kron()`, `.mult()`, `.pinv()`, `.pow()`, `.submatrix()`, `.transpose()`, `.row()`, `.col()`, `.eigenvalues()`, `.is_square()`, `.is_zero()`, `.is_binary()`, `.is_diagonal()`, `.is_identity()`, `.is_symmetric()`, `.is_antisymmetric()`, `.is_stochastic()`, `.sum()`, `.avg()`, `.min()`, `.max()`, `.mode()`, `.trace()`, `.det()`, and `.rank()`; bind the result or use the namespace helper",
            "method `diff` is not supported for simple matrix<bool>",
            "unknown array method `diff`",
        ],
    );
    assert_diagnostic_count(path, 6);
}

#[test]
fn reports_unsupported_bound_matrix_kron_call_result_reads_fixture() {
    let path = "tests/fixtures/sema/unsupported_bound_matrix_kron_call_result_reads.pine";
    assert_exact_diagnostic_messages(
        path,
        &[
            "`matrix.kron` argument `id2` expects numeric matrix, got simple array<float>",
            "`matrix.get` argument `row` expects simple int, got const string",
            "`matrix.set` argument `value` expects numeric-compatible, got const string",
            "`matrix.size` is not supported: direct matrix call-result methods currently support only `.rows()`, `.columns()`, `.elements_count()`, `.get()`, `.set()`, `.fill()`, `.reverse()`, `.reshape()`, `.add_row()`, `.add_col()`, numeric-only `.sort()`, `.swap_rows()`, `.swap_columns()`, `.remove_row()`, `.remove_col()`, `.copy()`, `.diff()`, `.eigenvectors()`, `.inv()`, `.kron()`, `.mult()`, `.pinv()`, `.pow()`, `.submatrix()`, `.transpose()`, `.row()`, `.col()`, `.eigenvalues()`, `.is_square()`, `.is_zero()`, `.is_binary()`, `.is_diagonal()`, `.is_identity()`, `.is_symmetric()`, `.is_antisymmetric()`, `.is_stochastic()`, `.sum()`, `.avg()`, `.min()`, `.max()`, `.mode()`, `.trace()`, `.det()`, and `.rank()`; bind the result or use the namespace helper",
            "method `kron` is not supported for simple matrix<bool>",
            "unknown array method `kron`",
        ],
    );
    assert_diagnostic_count(path, 6);
}

#[test]
fn reports_unsupported_bound_matrix_submatrix_call_result_reads_fixture() {
    let path = "tests/fixtures/sema/unsupported_bound_matrix_submatrix_call_result_reads.pine";
    assert_exact_diagnostic_messages(
        path,
        &[
            "`matrix.submatrix` argument `from_row` expects simple int, got const string",
            "`matrix.get` argument `row` expects simple int, got const string",
            "`matrix.get` argument `column` expects simple int, got const string",
            "`matrix.set` argument `value` expects numeric-compatible, got const string",
            "`matrix.size` is not supported: direct matrix call-result methods currently support only `.rows()`, `.columns()`, `.elements_count()`, `.get()`, `.set()`, `.fill()`, `.reverse()`, `.reshape()`, `.add_row()`, `.add_col()`, numeric-only `.sort()`, `.swap_rows()`, `.swap_columns()`, `.remove_row()`, `.remove_col()`, `.copy()`, `.diff()`, `.eigenvectors()`, `.inv()`, `.kron()`, `.mult()`, `.pinv()`, `.pow()`, `.submatrix()`, `.transpose()`, `.row()`, `.col()`, `.eigenvalues()`, `.is_square()`, `.is_zero()`, `.is_binary()`, `.is_diagonal()`, `.is_identity()`, `.is_symmetric()`, `.is_antisymmetric()`, `.is_stochastic()`, `.sum()`, `.avg()`, `.min()`, `.max()`, `.mode()`, `.trace()`, `.det()`, and `.rank()`; bind the result or use the namespace helper",
            "unknown array method `submatrix`",
        ],
    );
    assert_diagnostic_count(path, 6);
}

#[test]
fn reports_unsupported_bound_matrix_transpose_call_result_reads_fixture() {
    let path = "tests/fixtures/sema/unsupported_bound_matrix_transpose_call_result_reads.pine";
    assert_exact_diagnostic_messages(
        path,
        &[
            "`matrix.get` argument `row` expects simple int, got const string",
            "`matrix.get` argument `column` expects simple int, got const string",
            "`matrix.set` argument `value` expects numeric-compatible, got const string",
            "`matrix.reverse` expects at most 1 argument(s), got 2",
            "`matrix.size` is not supported: direct matrix call-result methods currently support only `.rows()`, `.columns()`, `.elements_count()`, `.get()`, `.set()`, `.fill()`, `.reverse()`, `.reshape()`, `.add_row()`, `.add_col()`, numeric-only `.sort()`, `.swap_rows()`, `.swap_columns()`, `.remove_row()`, `.remove_col()`, `.copy()`, `.diff()`, `.eigenvectors()`, `.inv()`, `.kron()`, `.mult()`, `.pinv()`, `.pow()`, `.submatrix()`, `.transpose()`, `.row()`, `.col()`, `.eigenvalues()`, `.is_square()`, `.is_zero()`, `.is_binary()`, `.is_diagonal()`, `.is_identity()`, `.is_symmetric()`, `.is_antisymmetric()`, `.is_stochastic()`, `.sum()`, `.avg()`, `.min()`, `.max()`, `.mode()`, `.trace()`, `.det()`, and `.rank()`; bind the result or use the namespace helper",
            "unknown array method `transpose`",
        ],
    );
    assert_diagnostic_count(path, 6);
}

#[test]
fn reports_unsupported_bound_matrix_copy_call_result_reads_fixture() {
    let path = "tests/fixtures/sema/unsupported_bound_matrix_copy_call_result_reads.pine";
    assert_exact_diagnostic_messages(
        path,
        &[
            "`matrix.get` argument `row` expects simple int, got const string",
            "`matrix.get` argument `column` expects simple int, got const string",
            "`matrix.set` argument `value` expects numeric-compatible, got const string",
            "`matrix.reverse` expects at most 1 argument(s), got 2",
            "`matrix.size` is not supported: direct matrix call-result methods currently support only `.rows()`, `.columns()`, `.elements_count()`, `.get()`, `.set()`, `.fill()`, `.reverse()`, `.reshape()`, `.add_row()`, `.add_col()`, numeric-only `.sort()`, `.swap_rows()`, `.swap_columns()`, `.remove_row()`, `.remove_col()`, `.copy()`, `.diff()`, `.eigenvectors()`, `.inv()`, `.kron()`, `.mult()`, `.pinv()`, `.pow()`, `.submatrix()`, `.transpose()`, `.row()`, `.col()`, `.eigenvalues()`, `.is_square()`, `.is_zero()`, `.is_binary()`, `.is_diagonal()`, `.is_identity()`, `.is_symmetric()`, `.is_antisymmetric()`, `.is_stochastic()`, `.sum()`, `.avg()`, `.min()`, `.max()`, `.mode()`, `.trace()`, `.det()`, and `.rank()`; bind the result or use the namespace helper",
            "`array.rows` is not supported: direct array call-result methods currently support only `.size()`, `.get()`, `.first()`, `.last()`, `.copy()`, `.slice()`, `.concat()`, `.includes()`, `.every()`, `.some()`, `.indexof()`, `.lastindexof()`, `.binary_search()`, `.binary_search_leftmost()`, `.binary_search_rightmost()`, `.abs()`, `.min()`, `.max()`, `.sum()`, `.avg()`, `.range()`, `.median()`, `.mode()`, `.percentile_nearest_rank()`, `.percentile_linear_interpolation()`, `.percentrank()`, `.covariance()`, `.standardize()`, `.variance()`, `.stdev()`, `.sort_indices()`, `.join()`, `.clear()`, `.reverse()`, `.pop()`, `.shift()`, `.remove()`, `.push()`, `.unshift()`, `.insert()`, `.set()`, `.fill()`, and `.sort()`; bind the result or use the namespace helper",
        ],
    );
    assert_diagnostic_count(path, 6);
}

#[test]
fn accepts_supported_builtin_map_call_result_reads_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_builtin_map_call_result_reads.pine");
}

#[test]
fn reports_unsupported_builtin_map_call_result_reads_fixture() {
    let path = "tests/fixtures/sema/unsupported_builtin_map_call_result_reads.pine";
    assert_exact_diagnostic_messages(
        path,
        &[
            "`function_side_effect` is not supported: collection mutation via `map.put` is not supported inside user-defined functions",
            "`function_side_effect` is not supported: collection mutation via `map.clear` is not supported inside user-defined functions",
            "`function_side_effect` is not supported: collection mutation via `map.remove` is not supported inside user-defined functions",
            "`function_side_effect` is not supported: collection mutation via `map.put_all` is not supported inside user-defined functions",
            "`map.get` argument `key` expects string-compatible, got const int",
            "`map.contains` argument `key` expects integer-compatible, got const string",
            "`map.size` expects 1 argument(s), got 2",
            "`map.put` argument `key` expects string-compatible, got const int",
            "`map.put` argument `value` expects numeric-compatible, got const string",
            "`map.put` expects 3 argument(s), got 2",
            "`map.clear` expects 1 argument(s), got 2",
            "`map.remove` argument `key` expects string-compatible, got const int",
            "`map.remove` expects 2 argument(s), got 1",
            "`map.put_all` source map template int/float does not match target string/float",
            "`map.put_all` argument `source` expects map, got series float",
            "`map.put_all` expects 2 argument(s), got 1",
        ],
    );
    assert_diagnostic_count(path, 16);
}

#[test]
fn accepts_supported_builtin_map_copy_call_result_reads_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_builtin_map_copy_call_result_reads.pine");
}

#[test]
fn reports_unsupported_builtin_map_copy_call_result_reads_fixture() {
    let path = "tests/fixtures/sema/unsupported_builtin_map_copy_call_result_reads.pine";
    assert_exact_diagnostic_messages(
        path,
        &[
            "`map.get` argument `key` expects string-compatible, got const int",
            "`map.contains` argument `key` expects string-compatible, got const int",
            "`map.size` expects 1 argument(s), got 2",
            "`map.put` argument `key` expects string-compatible, got const int",
            "`map.clear` expects 1 argument(s), got 2",
            "`map.remove` argument `key` expects string-compatible, got const int",
            "`map.put_all` source map template int/float does not match target string/float",
            "`map.copy` argument `id` expects map, got series float",
        ],
    );
    assert_diagnostic_count(path, 8);
}

#[test]
fn accepts_supported_local_udf_map_call_result_reads_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_local_udf_map_call_result_reads.pine");
}

#[test]
fn reports_unsupported_local_udf_map_call_result_reads_fixture() {
    let path = "tests/fixtures/sema/unsupported_local_udf_map_call_result_reads.pine";
    assert_exact_diagnostic_messages(
        path,
        &[
            "`map.get` argument `key` expects string-compatible, got const int",
            "`map.contains` argument `key` expects string-compatible, got const int",
            "`map.get` expects 2 argument(s), got 3",
            "`map.put` argument `key` expects string-compatible, got const int",
            "`map.clear` expects 1 argument(s), got 2",
            "`map.remove` argument `key` expects string-compatible, got const int",
            "`map.put_all` source map template int/float does not match target string/float",
            "`array.contains` is not supported: direct array call-result methods currently support only `.size()`, `.get()`, `.first()`, `.last()`, `.copy()`, `.slice()`, `.concat()`, `.includes()`, `.every()`, `.some()`, `.indexof()`, `.lastindexof()`, `.binary_search()`, `.binary_search_leftmost()`, `.binary_search_rightmost()`, `.abs()`, `.min()`, `.max()`, `.sum()`, `.avg()`, `.range()`, `.median()`, `.mode()`, `.percentile_nearest_rank()`, `.percentile_linear_interpolation()`, `.percentrank()`, `.covariance()`, `.standardize()`, `.variance()`, `.stdev()`, `.sort_indices()`, `.join()`, `.clear()`, `.reverse()`, `.pop()`, `.shift()`, `.remove()`, `.push()`, `.unshift()`, `.insert()`, `.set()`, `.fill()`, and `.sort()`; bind the result or use the namespace helper",
            "`call_result.copy` is not supported: direct call-result methods require a supported concrete receiver type; bind the result first",
            "`call_result.size` is not supported: direct call-result methods require a supported concrete receiver type; bind the result first",
            "`call_result.size` is not supported: direct call-result methods require a supported concrete receiver type; bind the result first",
            "`array.contains` is not supported: direct array call-result methods currently support only `.size()`, `.get()`, `.first()`, `.last()`, `.copy()`, `.slice()`, `.concat()`, `.includes()`, `.every()`, `.some()`, `.indexof()`, `.lastindexof()`, `.binary_search()`, `.binary_search_leftmost()`, `.binary_search_rightmost()`, `.abs()`, `.min()`, `.max()`, `.sum()`, `.avg()`, `.range()`, `.median()`, `.mode()`, `.percentile_nearest_rank()`, `.percentile_linear_interpolation()`, `.percentrank()`, `.covariance()`, `.standardize()`, `.variance()`, `.stdev()`, `.sort_indices()`, `.join()`, `.clear()`, `.reverse()`, `.pop()`, `.shift()`, `.remove()`, `.push()`, `.unshift()`, `.insert()`, `.set()`, `.fill()`, and `.sort()`; bind the result or use the namespace helper",
            "`matrix.contains` is not supported: direct matrix call-result methods currently support only `.rows()`, `.columns()`, `.elements_count()`, `.get()`, `.set()`, `.fill()`, `.reverse()`, `.reshape()`, `.add_row()`, `.add_col()`, numeric-only `.sort()`, `.swap_rows()`, `.swap_columns()`, `.remove_row()`, `.remove_col()`, `.copy()`, `.diff()`, `.eigenvectors()`, `.inv()`, `.kron()`, `.mult()`, `.pinv()`, `.pow()`, `.submatrix()`, `.transpose()`, `.row()`, `.col()`, `.eigenvalues()`, `.is_square()`, `.is_zero()`, `.is_binary()`, `.is_diagonal()`, `.is_identity()`, `.is_symmetric()`, `.is_antisymmetric()`, `.is_stochastic()`, `.sum()`, `.avg()`, `.min()`, `.max()`, `.mode()`, `.trace()`, `.det()`, and `.rank()`; bind the result or use the namespace helper",
        ],
    );
    assert_diagnostic_count(path, 13);
}

#[test]
fn accepts_supported_local_user_method_map_call_result_reads_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_local_user_method_map_call_result_reads.pine",
    );
}

#[test]
fn reports_unsupported_local_user_method_map_call_result_reads_fixture() {
    let path = "tests/fixtures/sema/unsupported_local_user_method_map_call_result_reads.pine";
    assert_exact_diagnostic_messages(
        path,
        &[
            "`map.get` argument `key` expects string-compatible, got const int",
            "`map.contains` argument `key` expects string-compatible, got const int",
            "`map.get` expects 2 argument(s), got 3",
            "`map.put` argument `key` expects string-compatible, got const int",
            "`map.clear` expects 1 argument(s), got 2",
            "`map.remove` argument `key` expects string-compatible, got const int",
            "`map.put_all` source map template int/float does not match target string/float",
            "`array.contains` is not supported: direct array call-result methods currently support only `.size()`, `.get()`, `.first()`, `.last()`, `.copy()`, `.slice()`, `.concat()`, `.includes()`, `.every()`, `.some()`, `.indexof()`, `.lastindexof()`, `.binary_search()`, `.binary_search_leftmost()`, `.binary_search_rightmost()`, `.abs()`, `.min()`, `.max()`, `.sum()`, `.avg()`, `.range()`, `.median()`, `.mode()`, `.percentile_nearest_rank()`, `.percentile_linear_interpolation()`, `.percentrank()`, `.covariance()`, `.standardize()`, `.variance()`, `.stdev()`, `.sort_indices()`, `.join()`, `.clear()`, `.reverse()`, `.pop()`, `.shift()`, `.remove()`, `.push()`, `.unshift()`, `.insert()`, `.set()`, `.fill()`, and `.sort()`; bind the result or use the namespace helper",
            "`call_result.copy` is not supported: direct call-result methods require a supported concrete receiver type; bind the result first",
            "ternary map branches must resolve to the same map template",
            "`call_result.size` is not supported: direct call-result methods require a supported concrete receiver type; bind the result first",
            "`call_result.size` is not supported: direct call-result methods require a supported concrete receiver type; bind the result first",
            "`array.contains` is not supported: direct array call-result methods currently support only `.size()`, `.get()`, `.first()`, `.last()`, `.copy()`, `.slice()`, `.concat()`, `.includes()`, `.every()`, `.some()`, `.indexof()`, `.lastindexof()`, `.binary_search()`, `.binary_search_leftmost()`, `.binary_search_rightmost()`, `.abs()`, `.min()`, `.max()`, `.sum()`, `.avg()`, `.range()`, `.median()`, `.mode()`, `.percentile_nearest_rank()`, `.percentile_linear_interpolation()`, `.percentrank()`, `.covariance()`, `.standardize()`, `.variance()`, `.stdev()`, `.sort_indices()`, `.join()`, `.clear()`, `.reverse()`, `.pop()`, `.shift()`, `.remove()`, `.push()`, `.unshift()`, `.insert()`, `.set()`, `.fill()`, and `.sort()`; bind the result or use the namespace helper",
            "`matrix.contains` is not supported: direct matrix call-result methods currently support only `.rows()`, `.columns()`, `.elements_count()`, `.get()`, `.set()`, `.fill()`, `.reverse()`, `.reshape()`, `.add_row()`, `.add_col()`, numeric-only `.sort()`, `.swap_rows()`, `.swap_columns()`, `.remove_row()`, `.remove_col()`, `.copy()`, `.diff()`, `.eigenvectors()`, `.inv()`, `.kron()`, `.mult()`, `.pinv()`, `.pow()`, `.submatrix()`, `.transpose()`, `.row()`, `.col()`, `.eigenvalues()`, `.is_square()`, `.is_zero()`, `.is_binary()`, `.is_diagonal()`, `.is_identity()`, `.is_symmetric()`, `.is_antisymmetric()`, `.is_stochastic()`, `.sum()`, `.avg()`, `.min()`, `.max()`, `.mode()`, `.trace()`, `.det()`, and `.rank()`; bind the result or use the namespace helper",
        ],
    );
    assert_diagnostic_count(path, 14);
}

#[test]
fn accepts_supported_imported_user_method_map_call_result_reads_fixture() {
    assert_import_valid_fixture(
        "tests/fixtures/sema/supported_imported_user_method_map_call_result_reads.pine",
    );
}

#[test]
fn reports_unsupported_imported_user_method_map_call_result_reads_fixture() {
    let path = "tests/fixtures/sema/unsupported_imported_user_method_map_call_result_reads.pine";
    assert_import_diagnostic_messages(
        path,
        &[
            "`map.get` argument `key` expects string-compatible, got const int",
            "`map.contains` argument `key` expects string-compatible, got const int",
            "`map.get` expects 2 argument(s), got 3",
            "`map.put` argument `key` expects string-compatible, got const int",
            "`map.clear` expects 1 argument(s), got 2",
            "`map.remove` argument `key` expects string-compatible, got const int",
            "`map.put_all` source map template int/float does not match target string/float",
            "`array.contains` is not supported: direct array call-result methods currently support only `.size()`, `.get()`, `.first()`, `.last()`, `.copy()`, `.slice()`, `.concat()`, `.includes()`, `.every()`, `.some()`, `.indexof()`, `.lastindexof()`, `.binary_search()`, `.binary_search_leftmost()`, `.binary_search_rightmost()`, `.abs()`, `.min()`, `.max()`, `.sum()`, `.avg()`, `.range()`, `.median()`, `.mode()`, `.percentile_nearest_rank()`, `.percentile_linear_interpolation()`, `.percentrank()`, `.covariance()`, `.standardize()`, `.variance()`, `.stdev()`, `.sort_indices()`, `.join()`, `.clear()`, `.reverse()`, `.pop()`, `.shift()`, `.remove()`, `.push()`, `.unshift()`, `.insert()`, `.set()`, `.fill()`, and `.sort()`; bind the result or use the namespace helper",
            "`call_result.copy` is not supported: direct call-result methods require a supported concrete receiver type; bind the result first",
            "`call_result.size` is not supported: direct call-result methods require a supported concrete receiver type; bind the result first",
        ],
    );
    assert_import_diagnostic_count(path, 10);
}

#[test]
fn accepts_supported_imported_user_method_matrix_call_result_reads_fixture() {
    assert_import_valid_fixture(
        "tests/fixtures/sema/supported_imported_user_method_matrix_call_result_reads.pine",
    );
}

#[test]
fn reports_unsupported_imported_user_method_matrix_call_result_reads_fixture() {
    let path = "tests/fixtures/sema/unsupported_imported_user_method_matrix_call_result_reads.pine";
    assert_import_diagnostic_messages(
        path,
        &[
            "`matrix.get` argument `row` expects simple int, got const string",
            "`matrix.set` argument `value` expects numeric-compatible, got const string",
            "`matrix.size` is not supported: direct matrix call-result methods currently support only `.rows()`, `.columns()`, `.elements_count()`, `.get()`, `.set()`, `.fill()`, `.reverse()`, `.reshape()`, `.add_row()`, `.add_col()`, numeric-only `.sort()`, `.swap_rows()`, `.swap_columns()`, `.remove_row()`, `.remove_col()`, `.copy()`, `.diff()`, `.eigenvectors()`, `.inv()`, `.kron()`, `.mult()`, `.pinv()`, `.pow()`, `.submatrix()`, `.transpose()`, `.row()`, `.col()`, `.eigenvalues()`, `.is_square()`, `.is_zero()`, `.is_binary()`, `.is_diagonal()`, `.is_identity()`, `.is_symmetric()`, `.is_antisymmetric()`, `.is_stochastic()`, `.sum()`, `.avg()`, `.min()`, `.max()`, `.mode()`, `.trace()`, `.det()`, and `.rank()`; bind the result or use the namespace helper",
            "`call_result.copy` is not supported: direct call-result methods require a supported concrete receiver type; bind the result first",
            "`call_result.rows` is not supported: direct call-result methods require a supported concrete receiver type; bind the result first",
            "`array.rows` is not supported: direct array call-result methods currently support only `.size()`, `.get()`, `.first()`, `.last()`, `.copy()`, `.slice()`, `.concat()`, `.includes()`, `.every()`, `.some()`, `.indexof()`, `.lastindexof()`, `.binary_search()`, `.binary_search_leftmost()`, `.binary_search_rightmost()`, `.abs()`, `.min()`, `.max()`, `.sum()`, `.avg()`, `.range()`, `.median()`, `.mode()`, `.percentile_nearest_rank()`, `.percentile_linear_interpolation()`, `.percentrank()`, `.covariance()`, `.standardize()`, `.variance()`, `.stdev()`, `.sort_indices()`, `.join()`, `.clear()`, `.reverse()`, `.pop()`, `.shift()`, `.remove()`, `.push()`, `.unshift()`, `.insert()`, `.set()`, `.fill()`, and `.sort()`; bind the result or use the namespace helper",
            "`map.rows` is not supported: direct map call-result methods currently support only `.size()`, terminal `.put()`, `.clear()`, `.remove()`, and `.put_all()`, `.get()`, `.contains()`, `.copy()`, `.keys()`, and `.values()`; bind the result or use the namespace helper",
        ],
    );
    assert_import_diagnostic_count(path, 8);
}

#[test]
fn accepts_supported_imported_function_matrix_call_result_reads_fixture() {
    assert_import_valid_fixture(
        "tests/fixtures/sema/supported_imported_function_matrix_call_result_reads.pine",
    );
}

#[test]
fn reports_unsupported_imported_function_matrix_call_result_reads_fixture() {
    let path = "tests/fixtures/sema/unsupported_imported_function_matrix_call_result_reads.pine";
    assert_import_diagnostic_messages(
        path,
        &[
            "`matrix.get` argument `row` expects simple int, got const string",
            "`matrix.set` argument `value` expects numeric-compatible, got const string",
            "`matrix.size` is not supported: direct matrix call-result methods currently support only `.rows()`, `.columns()`, `.elements_count()`, `.get()`, `.set()`, `.fill()`, `.reverse()`, `.reshape()`, `.add_row()`, `.add_col()`, numeric-only `.sort()`, `.swap_rows()`, `.swap_columns()`, `.remove_row()`, `.remove_col()`, `.copy()`, `.diff()`, `.eigenvectors()`, `.inv()`, `.kron()`, `.mult()`, `.pinv()`, `.pow()`, `.submatrix()`, `.transpose()`, `.row()`, `.col()`, `.eigenvalues()`, `.is_square()`, `.is_zero()`, `.is_binary()`, `.is_diagonal()`, `.is_identity()`, `.is_symmetric()`, `.is_antisymmetric()`, `.is_stochastic()`, `.sum()`, `.avg()`, `.min()`, `.max()`, `.mode()`, `.trace()`, `.det()`, and `.rank()`; bind the result or use the namespace helper",
            "`call_result.copy` is not supported: direct call-result methods require a supported concrete receiver type; bind the result first",
            "`call_result.rows` is not supported: direct call-result methods require a supported concrete receiver type; bind the result first",
            "`array.rows` is not supported: direct array call-result methods currently support only `.size()`, `.get()`, `.first()`, `.last()`, `.copy()`, `.slice()`, `.concat()`, `.includes()`, `.every()`, `.some()`, `.indexof()`, `.lastindexof()`, `.binary_search()`, `.binary_search_leftmost()`, `.binary_search_rightmost()`, `.abs()`, `.min()`, `.max()`, `.sum()`, `.avg()`, `.range()`, `.median()`, `.mode()`, `.percentile_nearest_rank()`, `.percentile_linear_interpolation()`, `.percentrank()`, `.covariance()`, `.standardize()`, `.variance()`, `.stdev()`, `.sort_indices()`, `.join()`, `.clear()`, `.reverse()`, `.pop()`, `.shift()`, `.remove()`, `.push()`, `.unshift()`, `.insert()`, `.set()`, `.fill()`, and `.sort()`; bind the result or use the namespace helper",
            "`map.rows` is not supported: direct map call-result methods currently support only `.size()`, terminal `.put()`, `.clear()`, `.remove()`, and `.put_all()`, `.get()`, `.contains()`, `.copy()`, `.keys()`, and `.values()`; bind the result or use the namespace helper",
        ],
    );
    assert_import_diagnostic_count(path, 8);
}

#[test]
fn accepts_supported_imported_function_map_call_result_reads_fixture() {
    assert_import_valid_fixture(
        "tests/fixtures/sema/supported_imported_function_map_call_result_reads.pine",
    );
}

#[test]
fn reports_unsupported_imported_function_map_call_result_reads_fixture() {
    let path = "tests/fixtures/sema/unsupported_imported_function_map_call_result_reads.pine";
    assert_import_diagnostic_messages(
        path,
        &[
            "`map.get` argument `key` expects string-compatible, got const int",
            "`map.contains` argument `key` expects string-compatible, got const int",
            "`map.get` expects 2 argument(s), got 3",
            "`map.put` argument `key` expects string-compatible, got const int",
            "`map.clear` expects 1 argument(s), got 2",
            "`map.remove` argument `key` expects string-compatible, got const int",
            "`map.put_all` source map template int/float does not match target string/float",
            "`array.contains` is not supported: direct array call-result methods currently support only `.size()`, `.get()`, `.first()`, `.last()`, `.copy()`, `.slice()`, `.concat()`, `.includes()`, `.every()`, `.some()`, `.indexof()`, `.lastindexof()`, `.binary_search()`, `.binary_search_leftmost()`, `.binary_search_rightmost()`, `.abs()`, `.min()`, `.max()`, `.sum()`, `.avg()`, `.range()`, `.median()`, `.mode()`, `.percentile_nearest_rank()`, `.percentile_linear_interpolation()`, `.percentrank()`, `.covariance()`, `.standardize()`, `.variance()`, `.stdev()`, `.sort_indices()`, `.join()`, `.clear()`, `.reverse()`, `.pop()`, `.shift()`, `.remove()`, `.push()`, `.unshift()`, `.insert()`, `.set()`, `.fill()`, and `.sort()`; bind the result or use the namespace helper",
            "`call_result.copy` is not supported: direct call-result methods require a supported concrete receiver type; bind the result first",
            "`call_result.size` is not supported: direct call-result methods require a supported concrete receiver type; bind the result first",
        ],
    );
    assert_import_diagnostic_count(path, 10);
}

#[test]
fn reports_unsupported_builtin_namespace_matrix_call_result_reads_fixture() {
    let path = "tests/fixtures/sema/unsupported_builtin_namespace_matrix_call_result_reads.pine";
    assert_exact_diagnostic_messages(
        path,
        &[
            "method calls on call-result receivers require an unqualified call, qualified user-defined result, or supported built-in collection producer receiver",
            "method calls on call-result receivers require an unqualified call, qualified user-defined result, or supported built-in collection producer receiver",
            "`function_side_effect` is not supported: collection mutation via `matrix.set` is not supported inside user-defined functions",
            "`function_side_effect` is not supported: collection mutation via `matrix.fill` is not supported inside user-defined functions",
            "`function_side_effect` is not supported: collection mutation via `matrix.reverse` is not supported inside user-defined functions",
            "`function_side_effect` is not supported: collection mutation via `matrix.reshape` is not supported inside user-defined functions",
            "`function_side_effect` is not supported: collection mutation via `matrix.swap_rows` is not supported inside user-defined functions",
            "`function_side_effect` is not supported: collection mutation via `matrix.swap_columns` is not supported inside user-defined functions",
            "`function_side_effect` is not supported: collection mutation via `matrix.remove_row` is not supported inside user-defined functions",
            "`function_side_effect` is not supported: collection mutation via `matrix.remove_col` is not supported inside user-defined functions",
            "`function_side_effect` is not supported: collection mutation via `matrix.add_row` is not supported inside user-defined functions",
            "`function_side_effect` is not supported: collection mutation via `matrix.add_col` is not supported inside user-defined functions",
            "`function_side_effect` is not supported: collection mutation via `matrix.sort` is not supported inside user-defined functions",
            "`matrix.get` argument `row` expects simple int, got const string",
            "`matrix.get` argument `column` expects simple int, got const string",
            "`matrix.set` argument `row` expects simple int, got const string",
            "`matrix.fill` argument `value` expects numeric-compatible, got const string",
            "`matrix.reverse` expects at most 1 argument(s), got 2",
            "`matrix.reshape` argument `rows` expects simple int, got const string",
            "`matrix.swap_rows` argument `row1` expects simple int, got const string",
            "`matrix.swap_columns` argument `column1` expects simple int, got const string",
            "`matrix.remove_row` argument `row` expects simple int, got const string",
            "`matrix.remove_col` argument `column` expects simple int, got const string",
            "`matrix.add_row` argument `row` expects simple int, got const string",
            "`matrix.add_col` argument `column` expects simple int, got const string",
            "`matrix.sort` argument `column` expects simple int, got const string",
            "`matrix.size` is not supported: direct matrix call-result methods currently support only `.rows()`, `.columns()`, `.elements_count()`, `.get()`, `.set()`, `.fill()`, `.reverse()`, `.reshape()`, `.add_row()`, `.add_col()`, numeric-only `.sort()`, `.swap_rows()`, `.swap_columns()`, `.remove_row()`, `.remove_col()`, `.copy()`, `.diff()`, `.eigenvectors()`, `.inv()`, `.kron()`, `.mult()`, `.pinv()`, `.pow()`, `.submatrix()`, `.transpose()`, `.row()`, `.col()`, `.eigenvalues()`, `.is_square()`, `.is_zero()`, `.is_binary()`, `.is_diagonal()`, `.is_identity()`, `.is_symmetric()`, `.is_antisymmetric()`, `.is_stochastic()`, `.sum()`, `.avg()`, `.min()`, `.max()`, `.mode()`, `.trace()`, `.det()`, and `.rank()`; bind the result or use the namespace helper",
            "`matrix.get` argument `row` expects simple int, got const string",
            "`matrix.set` argument `column` expects simple int, got const string",
            "`matrix.fill` expects at least 2 argument(s), got 1",
            "`matrix.reshape` argument `columns` expects simple int, got const string",
            "`matrix.swap_rows` argument `row2` expects simple int, got const string",
            "`matrix.swap_columns` argument `column2` expects simple int, got const string",
            "`matrix.remove_row` argument `row` expects simple int, got const string",
            "`matrix.remove_col` argument `column` expects simple int, got const string",
            "`matrix.add_row` argument `array_id` expects simple array<float>, got simple array<int>",
            "`matrix.add_col` argument `array_id` expects simple array<float>, got simple array<int>",
            "`matrix.sort` argument `order` expects const string, got series float",
            "`matrix.size` is not supported: direct matrix call-result methods currently support only `.rows()`, `.columns()`, `.elements_count()`, `.get()`, `.set()`, `.fill()`, `.reverse()`, `.reshape()`, `.add_row()`, `.add_col()`, numeric-only `.sort()`, `.swap_rows()`, `.swap_columns()`, `.remove_row()`, `.remove_col()`, `.copy()`, `.diff()`, `.eigenvectors()`, `.inv()`, `.kron()`, `.mult()`, `.pinv()`, `.pow()`, `.submatrix()`, `.transpose()`, `.row()`, `.col()`, `.eigenvalues()`, `.is_square()`, `.is_zero()`, `.is_binary()`, `.is_diagonal()`, `.is_identity()`, `.is_symmetric()`, `.is_antisymmetric()`, `.is_stochastic()`, `.sum()`, `.avg()`, `.min()`, `.max()`, `.mode()`, `.trace()`, `.det()`, and `.rank()`; bind the result or use the namespace helper",
            "`matrix.copy` argument `id` expects matrix, got simple array<float>",
            "`array.rows` is not supported: direct array call-result methods currently support only `.size()`, `.get()`, `.first()`, `.last()`, `.copy()`, `.slice()`, `.concat()`, `.includes()`, `.every()`, `.some()`, `.indexof()`, `.lastindexof()`, `.binary_search()`, `.binary_search_leftmost()`, `.binary_search_rightmost()`, `.abs()`, `.min()`, `.max()`, `.sum()`, `.avg()`, `.range()`, `.median()`, `.mode()`, `.percentile_nearest_rank()`, `.percentile_linear_interpolation()`, `.percentrank()`, `.covariance()`, `.standardize()`, `.variance()`, `.stdev()`, `.sort_indices()`, `.join()`, `.clear()`, `.reverse()`, `.pop()`, `.shift()`, `.remove()`, `.push()`, `.unshift()`, `.insert()`, `.set()`, `.fill()`, and `.sort()`; bind the result or use the namespace helper",
            "`matrix.get` argument `column` expects simple int, got const string",
            "`matrix.set` argument `value` expects numeric-compatible, got const string",
            "`matrix.fill` expects at most 2 argument(s), got 3",
            "`matrix.reshape` expects at least 3 argument(s), got 2",
            "`matrix.swap_rows` expects at least 3 argument(s), got 2",
            "`matrix.swap_columns` expects at least 3 argument(s), got 2",
            "`matrix.remove_row` expects at least 2 argument(s), got 1",
            "`matrix.remove_col` expects at least 2 argument(s), got 1",
            "`matrix.add_row` expects at least 3 argument(s), got 2",
            "`matrix.add_col` expects at least 3 argument(s), got 2",
            "`matrix.sort` expects at most 3 argument(s), got 4",
            "`matrix.size` is not supported: direct matrix call-result methods currently support only `.rows()`, `.columns()`, `.elements_count()`, `.get()`, `.set()`, `.fill()`, `.reverse()`, `.reshape()`, `.add_row()`, `.add_col()`, numeric-only `.sort()`, `.swap_rows()`, `.swap_columns()`, `.remove_row()`, `.remove_col()`, `.copy()`, `.diff()`, `.eigenvectors()`, `.inv()`, `.kron()`, `.mult()`, `.pinv()`, `.pow()`, `.submatrix()`, `.transpose()`, `.row()`, `.col()`, `.eigenvalues()`, `.is_square()`, `.is_zero()`, `.is_binary()`, `.is_diagonal()`, `.is_identity()`, `.is_symmetric()`, `.is_antisymmetric()`, `.is_stochastic()`, `.sum()`, `.avg()`, `.min()`, `.max()`, `.mode()`, `.trace()`, `.det()`, and `.rank()`; bind the result or use the namespace helper",
            "`matrix.transpose` argument `id` expects matrix, got simple array<float>",
            "`array.rows` is not supported: direct array call-result methods currently support only `.size()`, `.get()`, `.first()`, `.last()`, `.copy()`, `.slice()`, `.concat()`, `.includes()`, `.every()`, `.some()`, `.indexof()`, `.lastindexof()`, `.binary_search()`, `.binary_search_leftmost()`, `.binary_search_rightmost()`, `.abs()`, `.min()`, `.max()`, `.sum()`, `.avg()`, `.range()`, `.median()`, `.mode()`, `.percentile_nearest_rank()`, `.percentile_linear_interpolation()`, `.percentrank()`, `.covariance()`, `.standardize()`, `.variance()`, `.stdev()`, `.sort_indices()`, `.join()`, `.clear()`, `.reverse()`, `.pop()`, `.shift()`, `.remove()`, `.push()`, `.unshift()`, `.insert()`, `.set()`, `.fill()`, and `.sort()`; bind the result or use the namespace helper",
            "`matrix.submatrix` argument `from_row` expects simple int, got const string",
            "`matrix.get` argument `row` expects simple int, got const string",
            "`matrix.set` expects at least 4 argument(s), got 3",
            "`matrix.reshape` expects at most 3 argument(s), got 4",
            "`matrix.swap_rows` expects at most 3 argument(s), got 4",
            "`matrix.swap_columns` expects at most 3 argument(s), got 4",
            "`matrix.remove_row` expects at most 2 argument(s), got 3",
            "`matrix.remove_col` expects at most 2 argument(s), got 3",
            "`matrix.add_row` expects at most 3 argument(s), got 4",
            "`matrix.add_col` expects at most 3 argument(s), got 4",
            "`matrix.sort` argument `id` expects numeric matrix, got simple matrix<bool>",
            "`matrix.size` is not supported: direct matrix call-result methods currently support only `.rows()`, `.columns()`, `.elements_count()`, `.get()`, `.set()`, `.fill()`, `.reverse()`, `.reshape()`, `.add_row()`, `.add_col()`, numeric-only `.sort()`, `.swap_rows()`, `.swap_columns()`, `.remove_row()`, `.remove_col()`, `.copy()`, `.diff()`, `.eigenvectors()`, `.inv()`, `.kron()`, `.mult()`, `.pinv()`, `.pow()`, `.submatrix()`, `.transpose()`, `.row()`, `.col()`, `.eigenvalues()`, `.is_square()`, `.is_zero()`, `.is_binary()`, `.is_diagonal()`, `.is_identity()`, `.is_symmetric()`, `.is_antisymmetric()`, `.is_stochastic()`, `.sum()`, `.avg()`, `.min()`, `.max()`, `.mode()`, `.trace()`, `.det()`, and `.rank()`; bind the result or use the namespace helper",
            "`matrix.submatrix` argument `id` expects matrix, got simple array<float>",
            "`array.rows` is not supported: direct array call-result methods currently support only `.size()`, `.get()`, `.first()`, `.last()`, `.copy()`, `.slice()`, `.concat()`, `.includes()`, `.every()`, `.some()`, `.indexof()`, `.lastindexof()`, `.binary_search()`, `.binary_search_leftmost()`, `.binary_search_rightmost()`, `.abs()`, `.min()`, `.max()`, `.sum()`, `.avg()`, `.range()`, `.median()`, `.mode()`, `.percentile_nearest_rank()`, `.percentile_linear_interpolation()`, `.percentrank()`, `.covariance()`, `.standardize()`, `.variance()`, `.stdev()`, `.sort_indices()`, `.join()`, `.clear()`, `.reverse()`, `.pop()`, `.shift()`, `.remove()`, `.push()`, `.unshift()`, `.insert()`, `.set()`, `.fill()`, and `.sort()`; bind the result or use the namespace helper",
            "`matrix.kron` argument `id2` expects numeric matrix, got simple array<float>",
            "`matrix.get` argument `row` expects simple int, got const string",
            "`matrix.set` expects at most 4 argument(s), got 5",
            "`matrix.size` is not supported: direct matrix call-result methods currently support only `.rows()`, `.columns()`, `.elements_count()`, `.get()`, `.set()`, `.fill()`, `.reverse()`, `.reshape()`, `.add_row()`, `.add_col()`, numeric-only `.sort()`, `.swap_rows()`, `.swap_columns()`, `.remove_row()`, `.remove_col()`, `.copy()`, `.diff()`, `.eigenvectors()`, `.inv()`, `.kron()`, `.mult()`, `.pinv()`, `.pow()`, `.submatrix()`, `.transpose()`, `.row()`, `.col()`, `.eigenvalues()`, `.is_square()`, `.is_zero()`, `.is_binary()`, `.is_diagonal()`, `.is_identity()`, `.is_symmetric()`, `.is_antisymmetric()`, `.is_stochastic()`, `.sum()`, `.avg()`, `.min()`, `.max()`, `.mode()`, `.trace()`, `.det()`, and `.rank()`; bind the result or use the namespace helper",
            "`matrix.diff` argument `id2` expects numeric matrix or numeric-compatible, got simple array<float>",
            "`matrix.get` argument `row` expects simple int, got const string",
            "`matrix.set` argument `value` expects numeric-compatible, got const string",
            "`matrix.size` is not supported: direct matrix call-result methods currently support only `.rows()`, `.columns()`, `.elements_count()`, `.get()`, `.set()`, `.fill()`, `.reverse()`, `.reshape()`, `.add_row()`, `.add_col()`, numeric-only `.sort()`, `.swap_rows()`, `.swap_columns()`, `.remove_row()`, `.remove_col()`, `.copy()`, `.diff()`, `.eigenvectors()`, `.inv()`, `.kron()`, `.mult()`, `.pinv()`, `.pow()`, `.submatrix()`, `.transpose()`, `.row()`, `.col()`, `.eigenvalues()`, `.is_square()`, `.is_zero()`, `.is_binary()`, `.is_diagonal()`, `.is_identity()`, `.is_symmetric()`, `.is_antisymmetric()`, `.is_stochastic()`, `.sum()`, `.avg()`, `.min()`, `.max()`, `.mode()`, `.trace()`, `.det()`, and `.rank()`; bind the result or use the namespace helper",
            "`matrix.pow` argument `id` expects numeric matrix, got simple array<float>",
            "`matrix.pow` argument `power` expects simple int, got const string",
            "`matrix.get` argument `row` expects simple int, got const string",
            "`matrix.set` argument `value` expects numeric-compatible, got const string",
            "`matrix.size` is not supported: direct matrix call-result methods currently support only `.rows()`, `.columns()`, `.elements_count()`, `.get()`, `.set()`, `.fill()`, `.reverse()`, `.reshape()`, `.add_row()`, `.add_col()`, numeric-only `.sort()`, `.swap_rows()`, `.swap_columns()`, `.remove_row()`, `.remove_col()`, `.copy()`, `.diff()`, `.eigenvectors()`, `.inv()`, `.kron()`, `.mult()`, `.pinv()`, `.pow()`, `.submatrix()`, `.transpose()`, `.row()`, `.col()`, `.eigenvalues()`, `.is_square()`, `.is_zero()`, `.is_binary()`, `.is_diagonal()`, `.is_identity()`, `.is_symmetric()`, `.is_antisymmetric()`, `.is_stochastic()`, `.sum()`, `.avg()`, `.min()`, `.max()`, `.mode()`, `.trace()`, `.det()`, and `.rank()`; bind the result or use the namespace helper",
            "`matrix.inv` argument `id` expects numeric matrix, got simple array<float>",
            "`matrix.get` argument `row` expects simple int, got const string",
            "`matrix.set` argument `value` expects numeric-compatible, got const string",
            "`matrix.size` is not supported: direct matrix call-result methods currently support only `.rows()`, `.columns()`, `.elements_count()`, `.get()`, `.set()`, `.fill()`, `.reverse()`, `.reshape()`, `.add_row()`, `.add_col()`, numeric-only `.sort()`, `.swap_rows()`, `.swap_columns()`, `.remove_row()`, `.remove_col()`, `.copy()`, `.diff()`, `.eigenvectors()`, `.inv()`, `.kron()`, `.mult()`, `.pinv()`, `.pow()`, `.submatrix()`, `.transpose()`, `.row()`, `.col()`, `.eigenvalues()`, `.is_square()`, `.is_zero()`, `.is_binary()`, `.is_diagonal()`, `.is_identity()`, `.is_symmetric()`, `.is_antisymmetric()`, `.is_stochastic()`, `.sum()`, `.avg()`, `.min()`, `.max()`, `.mode()`, `.trace()`, `.det()`, and `.rank()`; bind the result or use the namespace helper",
            "`matrix.pinv` argument `id` expects numeric matrix, got simple array<float>",
            "`matrix.get` argument `row` expects simple int, got const string",
            "`matrix.set` argument `value` expects numeric-compatible, got const string",
            "`matrix.size` is not supported: direct matrix call-result methods currently support only `.rows()`, `.columns()`, `.elements_count()`, `.get()`, `.set()`, `.fill()`, `.reverse()`, `.reshape()`, `.add_row()`, `.add_col()`, numeric-only `.sort()`, `.swap_rows()`, `.swap_columns()`, `.remove_row()`, `.remove_col()`, `.copy()`, `.diff()`, `.eigenvectors()`, `.inv()`, `.kron()`, `.mult()`, `.pinv()`, `.pow()`, `.submatrix()`, `.transpose()`, `.row()`, `.col()`, `.eigenvalues()`, `.is_square()`, `.is_zero()`, `.is_binary()`, `.is_diagonal()`, `.is_identity()`, `.is_symmetric()`, `.is_antisymmetric()`, `.is_stochastic()`, `.sum()`, `.avg()`, `.min()`, `.max()`, `.mode()`, `.trace()`, `.det()`, and `.rank()`; bind the result or use the namespace helper",
            "`matrix.eigenvectors` argument `id` expects numeric matrix, got simple array<float>",
            "`matrix.get` argument `row` expects simple int, got const string",
            "`matrix.set` argument `value` expects numeric-compatible, got const string",
            "`matrix.size` is not supported: direct matrix call-result methods currently support only `.rows()`, `.columns()`, `.elements_count()`, `.get()`, `.set()`, `.fill()`, `.reverse()`, `.reshape()`, `.add_row()`, `.add_col()`, numeric-only `.sort()`, `.swap_rows()`, `.swap_columns()`, `.remove_row()`, `.remove_col()`, `.copy()`, `.diff()`, `.eigenvectors()`, `.inv()`, `.kron()`, `.mult()`, `.pinv()`, `.pow()`, `.submatrix()`, `.transpose()`, `.row()`, `.col()`, `.eigenvalues()`, `.is_square()`, `.is_zero()`, `.is_binary()`, `.is_diagonal()`, `.is_identity()`, `.is_symmetric()`, `.is_antisymmetric()`, `.is_stochastic()`, `.sum()`, `.avg()`, `.min()`, `.max()`, `.mode()`, `.trace()`, `.det()`, and `.rank()`; bind the result or use the namespace helper",
            "`matrix.new<float>` argument `rows` expects simple int, got const string",
            "`matrix.get` argument `row` expects simple int, got const string",
            "`matrix.set` argument `value` expects bool-compatible, got const string",
            "`matrix.fill` argument `value` expects bool-compatible, got const string",
            "`matrix.size` is not supported: direct matrix call-result methods currently support only `.rows()`, `.columns()`, `.elements_count()`, `.get()`, `.set()`, `.fill()`, `.reverse()`, `.reshape()`, `.add_row()`, `.add_col()`, numeric-only `.sort()`, `.swap_rows()`, `.swap_columns()`, `.remove_row()`, `.remove_col()`, `.copy()`, `.diff()`, `.eigenvectors()`, `.inv()`, `.kron()`, `.mult()`, `.pinv()`, `.pow()`, `.submatrix()`, `.transpose()`, `.row()`, `.col()`, `.eigenvalues()`, `.is_square()`, `.is_zero()`, `.is_binary()`, `.is_diagonal()`, `.is_identity()`, `.is_symmetric()`, `.is_antisymmetric()`, `.is_stochastic()`, `.sum()`, `.avg()`, `.min()`, `.max()`, `.mode()`, `.trace()`, `.det()`, and `.rank()`; bind the result or use the namespace helper",
            "`array.rows` is not supported: direct array call-result methods currently support only `.size()`, `.get()`, `.first()`, `.last()`, `.copy()`, `.slice()`, `.concat()`, `.includes()`, `.every()`, `.some()`, `.indexof()`, `.lastindexof()`, `.binary_search()`, `.binary_search_leftmost()`, `.binary_search_rightmost()`, `.abs()`, `.min()`, `.max()`, `.sum()`, `.avg()`, `.range()`, `.median()`, `.mode()`, `.percentile_nearest_rank()`, `.percentile_linear_interpolation()`, `.percentrank()`, `.covariance()`, `.standardize()`, `.variance()`, `.stdev()`, `.sort_indices()`, `.join()`, `.clear()`, `.reverse()`, `.pop()`, `.shift()`, `.remove()`, `.push()`, `.unshift()`, `.insert()`, `.set()`, `.fill()`, and `.sort()`; bind the result or use the namespace helper",
            "`array.columns` is not supported: direct array call-result methods currently support only `.size()`, `.get()`, `.first()`, `.last()`, `.copy()`, `.slice()`, `.concat()`, `.includes()`, `.every()`, `.some()`, `.indexof()`, `.lastindexof()`, `.binary_search()`, `.binary_search_leftmost()`, `.binary_search_rightmost()`, `.abs()`, `.min()`, `.max()`, `.sum()`, `.avg()`, `.range()`, `.median()`, `.mode()`, `.percentile_nearest_rank()`, `.percentile_linear_interpolation()`, `.percentrank()`, `.covariance()`, `.standardize()`, `.variance()`, `.stdev()`, `.sort_indices()`, `.join()`, `.clear()`, `.reverse()`, `.pop()`, `.shift()`, `.remove()`, `.push()`, `.unshift()`, `.insert()`, `.set()`, `.fill()`, and `.sort()`; bind the result or use the namespace helper",
            "`array.elements_count` is not supported: direct array call-result methods currently support only `.size()`, `.get()`, `.first()`, `.last()`, `.copy()`, `.slice()`, `.concat()`, `.includes()`, `.every()`, `.some()`, `.indexof()`, `.lastindexof()`, `.binary_search()`, `.binary_search_leftmost()`, `.binary_search_rightmost()`, `.abs()`, `.min()`, `.max()`, `.sum()`, `.avg()`, `.range()`, `.median()`, `.mode()`, `.percentile_nearest_rank()`, `.percentile_linear_interpolation()`, `.percentrank()`, `.covariance()`, `.standardize()`, `.variance()`, `.stdev()`, `.sort_indices()`, `.join()`, `.clear()`, `.reverse()`, `.pop()`, `.shift()`, `.remove()`, `.push()`, `.unshift()`, `.insert()`, `.set()`, `.fill()`, and `.sort()`; bind the result or use the namespace helper",
            "`array.get` expects at most 2 argument(s), got 3",
            "`array.rows` is not supported: direct array call-result methods currently support only `.size()`, `.get()`, `.first()`, `.last()`, `.copy()`, `.slice()`, `.concat()`, `.includes()`, `.every()`, `.some()`, `.indexof()`, `.lastindexof()`, `.binary_search()`, `.binary_search_leftmost()`, `.binary_search_rightmost()`, `.abs()`, `.min()`, `.max()`, `.sum()`, `.avg()`, `.range()`, `.median()`, `.mode()`, `.percentile_nearest_rank()`, `.percentile_linear_interpolation()`, `.percentrank()`, `.covariance()`, `.standardize()`, `.variance()`, `.stdev()`, `.sort_indices()`, `.join()`, `.clear()`, `.reverse()`, `.pop()`, `.shift()`, `.remove()`, `.push()`, `.unshift()`, `.insert()`, `.set()`, `.fill()`, and `.sort()`; bind the result or use the namespace helper",
            "`matrix.row` argument `row` expects simple int, got const string",
            "`matrix.col` argument `column` expects simple int, got const string",
            "`matrix.eigenvalues` argument `id` expects numeric matrix, got simple matrix<bool>",
            "`matrix.is_square` expects at most 1 argument(s), got 2",
            "`matrix.is_zero` argument `id` expects numeric matrix, got simple matrix<bool>",
            "`matrix.is_zero` expects at most 1 argument(s), got 2",
            "`matrix.is_binary` argument `id` expects numeric matrix, got simple matrix<bool>",
            "`matrix.is_binary` expects at most 1 argument(s), got 2",
            "`matrix.is_diagonal` argument `id` expects numeric matrix, got simple matrix<bool>",
            "`matrix.is_diagonal` expects at most 1 argument(s), got 2",
            "`matrix.is_identity` argument `id` expects numeric matrix, got simple matrix<bool>",
            "`matrix.is_identity` expects at most 1 argument(s), got 2",
            "`matrix.is_symmetric` argument `id` expects numeric matrix, got simple matrix<bool>",
            "`matrix.is_symmetric` expects at most 1 argument(s), got 2",
            "`matrix.is_antisymmetric` argument `id` expects numeric matrix, got simple matrix<bool>",
            "`matrix.is_antisymmetric` expects at most 1 argument(s), got 2",
            "`matrix.is_stochastic` argument `id` expects numeric matrix, got simple matrix<bool>",
            "`matrix.is_stochastic` expects at most 1 argument(s), got 2",
            "`matrix.sum` argument `id` expects numeric matrix, got simple matrix<bool>",
            "`matrix.sum` expects at most 1 argument(s), got 2",
            "`matrix.avg` argument `id` expects numeric matrix, got simple matrix<bool>",
            "`matrix.avg` expects at most 1 argument(s), got 2",
            "`matrix.min` argument `id` expects numeric matrix, got simple matrix<bool>",
            "`matrix.min` expects at most 1 argument(s), got 2",
            "`matrix.max` argument `id` expects numeric matrix, got simple matrix<bool>",
            "`matrix.max` expects at most 1 argument(s), got 2",
            "`matrix.mode` argument `id` expects numeric matrix, got simple matrix<bool>",
            "`matrix.mode` expects at most 1 argument(s), got 2",
            "`matrix.trace` argument `id` expects numeric matrix, got simple matrix<bool>",
            "`matrix.trace` expects at most 1 argument(s), got 2",
            "`matrix.det` argument `id` expects numeric matrix, got simple matrix<bool>",
            "`matrix.det` expects at most 1 argument(s), got 2",
            "`matrix.rank` argument `id` expects numeric matrix, got simple matrix<bool>",
            "`matrix.rank` expects at most 1 argument(s), got 2",
            "`matrix.transpose` expects at most 1 argument(s), got 2",
            "`matrix.submatrix` argument `from_row` expects simple int, got const string",
            "`matrix.submatrix` expects at most 5 argument(s), got 6",
            "`matrix.inv` argument `id` expects numeric matrix, got simple matrix<bool>",
            "`matrix.inv` expects at most 1 argument(s), got 2",
            "`matrix.pinv` argument `id` expects numeric matrix, got simple matrix<bool>",
            "`matrix.pinv` expects at most 1 argument(s), got 2",
            "`matrix.eigenvectors` argument `id` expects numeric matrix, got simple matrix<bool>",
            "`matrix.eigenvectors` expects at most 1 argument(s), got 2",
            "`matrix.pow` argument `id` expects numeric matrix, got simple matrix<bool>",
            "`matrix.pow` argument `power` expects simple int, got const string",
            "`matrix.pow` expects at most 2 argument(s), got 3",
            "`matrix.kron` argument `id1` expects numeric matrix, got simple matrix<bool>",
            "`matrix.kron` argument `id2` expects numeric matrix, got simple array<float>",
            "`matrix.kron` expects at most 2 argument(s), got 3",
            "`matrix.diff` argument `id1` expects numeric matrix or numeric-compatible, got simple matrix<bool>",
            "`matrix.diff` argument `id2` expects numeric matrix or numeric-compatible, got simple array<float>",
            "`matrix.diff` expects at most 2 argument(s), got 3",
            "`matrix.mult` argument `id1` expects numeric matrix, numeric-compatible, or numeric array, got simple matrix<bool>",
            "`matrix.mult` argument `id2` expects numeric matrix, numeric-compatible, or numeric array, got simple matrix<bool>",
            "`matrix.mult` expects at most 2 argument(s), got 3",
            "`array.rows` is not supported: direct array call-result methods currently support only `.size()`, `.get()`, `.first()`, `.last()`, `.copy()`, `.slice()`, `.concat()`, `.includes()`, `.every()`, `.some()`, `.indexof()`, `.lastindexof()`, `.binary_search()`, `.binary_search_leftmost()`, `.binary_search_rightmost()`, `.abs()`, `.min()`, `.max()`, `.sum()`, `.avg()`, `.range()`, `.median()`, `.mode()`, `.percentile_nearest_rank()`, `.percentile_linear_interpolation()`, `.percentrank()`, `.covariance()`, `.standardize()`, `.variance()`, `.stdev()`, `.sort_indices()`, `.join()`, `.clear()`, `.reverse()`, `.pop()`, `.shift()`, `.remove()`, `.push()`, `.unshift()`, `.insert()`, `.set()`, `.fill()`, and `.sort()`; bind the result or use the namespace helper",
            "`matrix.size` is not supported: direct matrix call-result methods currently support only `.rows()`, `.columns()`, `.elements_count()`, `.get()`, `.set()`, `.fill()`, `.reverse()`, `.reshape()`, `.add_row()`, `.add_col()`, numeric-only `.sort()`, `.swap_rows()`, `.swap_columns()`, `.remove_row()`, `.remove_col()`, `.copy()`, `.diff()`, `.eigenvectors()`, `.inv()`, `.kron()`, `.mult()`, `.pinv()`, `.pow()`, `.submatrix()`, `.transpose()`, `.row()`, `.col()`, `.eigenvalues()`, `.is_square()`, `.is_zero()`, `.is_binary()`, `.is_diagonal()`, `.is_identity()`, `.is_symmetric()`, `.is_antisymmetric()`, `.is_stochastic()`, `.sum()`, `.avg()`, `.min()`, `.max()`, `.mode()`, `.trace()`, `.det()`, and `.rank()`; bind the result or use the namespace helper",
        ],
    );
    assert_diagnostic_count(path, 161);
}

#[test]
fn reports_unsupported_builtin_array_call_result_reads_fixture() {
    let path = "tests/fixtures/sema/unsupported_builtin_array_call_result_reads.pine";
    assert_diagnostic_messages(
        path,
        &[
            "`array.get` argument `index` expects simple integer-compatible, got const string",
            "`array.transform` is not supported: direct array call-result methods currently support only `.size()`, `.get()`, `.first()`, `.last()`, `.copy()`, `.slice()`, `.concat()`, `.includes()`, `.every()`, `.some()`, `.indexof()`, `.lastindexof()`, `.binary_search()`, `.binary_search_leftmost()`, `.binary_search_rightmost()`, `.abs()`, `.min()`, `.max()`, `.sum()`, `.avg()`, `.range()`, `.median()`, `.mode()`, `.percentile_nearest_rank()`, `.percentile_linear_interpolation()`, `.percentrank()`, `.covariance()`, `.standardize()`, `.variance()`, `.stdev()`, `.sort_indices()`, `.join()`, `.clear()`, `.reverse()`, `.pop()`, `.shift()`, `.remove()`, `.push()`, `.unshift()`, `.insert()`, `.set()`, `.fill()`, and `.sort()`; bind the result or use the namespace helper",
            "`array.slice` argument `index_from` expects simple integer-compatible, got const string",
            "`array.slice` argument `index_to` expects simple integer-compatible, got const string",
            "`array.slice` expects at least 3 argument(s), got 2",
            "`array.slice` expects at most 3 argument(s), got 4",
            "`array.clear` expects at most 1 argument(s), got 2",
            "`array.reverse` expects at most 1 argument(s), got 2",
            "`array.pop` expects at most 1 argument(s), got 2",
            "`array.shift` expects at most 1 argument(s), got 2",
            "`array.remove` argument `index` expects simple integer-compatible, got const string",
            "`array.remove` expects at least 2 argument(s), got 1",
            "`array.remove` expects at most 2 argument(s), got 3",
            "`array.push` argument `value` expects integer-compatible, got const string",
            "`array.push` argument `value` expects UDT `First`, got `Second`",
            "`array.push` expects at least 2 argument(s), got 1",
            "`array.push` expects at most 2 argument(s), got 3",
            "`array.unshift` argument `value` expects integer-compatible, got const string",
            "`array.unshift` argument `value` expects UDT `First`, got `Second`",
            "`array.unshift` expects at least 2 argument(s), got 1",
            "`array.unshift` expects at most 2 argument(s), got 3",
            "`array.insert` argument `index` expects simple integer-compatible, got const string",
            "`array.insert` argument `value` expects integer-compatible, got const string",
            "`array.insert` argument `value` expects UDT `First`, got `Second`",
            "`array.insert` expects at least 3 argument(s), got 2",
            "`array.insert` expects at most 3 argument(s), got 4",
            "`array.set` argument `index` expects simple integer-compatible, got const string",
            "`array.set` argument `value` expects integer-compatible, got const string",
            "`array.set` argument `value` expects UDT `First`, got `Second`",
            "`array.set` expects at least 3 argument(s), got 2",
            "`array.set` expects at most 3 argument(s), got 4",
            "`array.fill` argument `value` expects integer-compatible, got const string",
            "`array.fill` argument `value` expects UDT `First`, got `Second`",
            "`array.fill` argument `index_from` expects simple integer-compatible, got const string",
            "`array.fill` argument `index_to` expects simple integer-compatible, got const string",
            "`array.fill` expects at least 2 argument(s), got 1",
            "`array.fill` expects at most 4 argument(s), got 5",
            "`array.from` expects one scalar-tree UDT identity, got mixed UDT identities",
            "`array.concat` argument `id2` expects UDT array `First`, got `Second`",
            "`array.new<Nested>` does not support UDT arrays with non-scalar fields",
            "`array.size` is not supported: direct UDT-array call-result methods require a known same-local or same-imported element identity",
            "`array.new<Missing>` requires a local or imported scalar-tree UDT",
            "`array.size` is not supported: direct UDT-array call-result methods require a known same-local or same-imported element identity",
            "`array.from` expects one supported array element kind, got const na and const na",
            "`array.abs` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.size` is not supported: direct UDT-array call-result methods require one concrete same-local or same-imported element identity",
            "`array.standardize` argument `id` expects numeric array, got simple array<string>",
            "`array.sort_indices` requires a scalar-tree UDT array and a root int, float, or string `sort_field`",
            "`array.slice` argument `index_from` expects simple integer-compatible, got const string",
            "`array.includes` argument `value` expects UDT `First`, got `Second`",
            "`array.includes` argument `value` expects integer-compatible, got const string",
            "`array.includes` expects at most 2 argument(s), got 3",
            "`array.indexof` argument `value` expects UDT `First`, got `Second`",
            "`array.indexof` argument `value` expects integer-compatible, got const string",
            "`array.indexof` expects at most 2 argument(s), got 3",
            "`array.lastindexof` argument `value` expects UDT `First`, got `Second`",
            "`array.lastindexof` argument `value` expects integer-compatible, got const string",
            "`array.lastindexof` expects at most 2 argument(s), got 3",
            "`array.binary_search` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.binary_search` argument `id` expects numeric array, got simple array<string>",
            "`array.binary_search` argument `id` expects numeric array, got simple array<bool>",
            "`array.binary_search` argument `id` expects numeric array, got simple array<chart.point>",
            "`array.binary_search` argument `value` expects integer-compatible, got const string",
            "`array.binary_search` expects at most 2 argument(s), got 3",
            "`array.binary_search_leftmost` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.binary_search_leftmost` argument `id` expects numeric array, got simple array<string>",
            "`array.binary_search_leftmost` argument `id` expects numeric array, got simple array<bool>",
            "`array.binary_search_leftmost` argument `id` expects numeric array, got simple array<chart.point>",
            "`array.binary_search_leftmost` argument `value` expects integer-compatible, got const string",
            "`array.binary_search_leftmost` expects at most 2 argument(s), got 3",
            "`array.binary_search_rightmost` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.binary_search_rightmost` argument `id` expects numeric array, got simple array<string>",
            "`array.binary_search_rightmost` argument `id` expects numeric array, got simple array<bool>",
            "`array.binary_search_rightmost` argument `id` expects numeric array, got simple array<chart.point>",
            "`array.binary_search_rightmost` argument `value` expects integer-compatible, got const string",
            "`array.binary_search_rightmost` expects at most 2 argument(s), got 3",
            "`array.abs` argument `id` expects numeric array, got simple array<string>",
            "`array.abs` argument `id` expects numeric array, got simple array<bool>",
            "`array.abs` argument `id` expects numeric array, got simple array<color>",
            "`array.abs` argument `id` expects numeric array, got simple array<chart.point>",
            "`array.abs` expects at most 1 argument(s), got 2",
            "`array.min` argument `id` expects numeric array, got simple array<UDT>",
            "`array.min` argument `id` expects numeric array, got simple array<string>",
            "`array.min` argument `id` expects numeric array, got simple array<bool>",
            "`array.min` argument `id` expects numeric array, got simple array<color>",
            "`array.min` argument `id` expects numeric array, got simple array<chart.point>",
            "`array.min` argument `nth` expects integer-compatible, got const float",
            "`array.min` argument `nth` expects integer-compatible, got const string",
            "`array.min` expects at most 2 argument(s), got 3",
            "`array.max` argument `id` expects numeric array, got simple array<UDT>",
            "`array.max` argument `id` expects numeric array, got simple array<string>",
            "`array.max` argument `id` expects numeric array, got simple array<bool>",
            "`array.max` argument `id` expects numeric array, got simple array<color>",
            "`array.max` argument `id` expects numeric array, got simple array<chart.point>",
            "`array.max` argument `nth` expects integer-compatible, got const float",
            "`array.max` argument `nth` expects integer-compatible, got const string",
            "`array.max` expects at most 2 argument(s), got 3",
            "`array.sum` argument `id` expects numeric array, got simple array<UDT>",
            "`array.sum` argument `id` expects numeric array, got simple array<string>",
            "`array.sum` argument `id` expects numeric array, got simple array<bool>",
            "`array.sum` argument `id` expects numeric array, got simple array<color>",
            "`array.sum` argument `id` expects numeric array, got simple array<chart.point>",
            "`array.sum` expects at most 1 argument(s), got 2",
            "`array.avg` argument `id` expects numeric array, got simple array<UDT>",
            "`array.avg` argument `id` expects numeric array, got simple array<string>",
            "`array.avg` argument `id` expects numeric array, got simple array<bool>",
            "`array.avg` argument `id` expects numeric array, got simple array<color>",
            "`array.avg` argument `id` expects numeric array, got simple array<chart.point>",
            "`array.avg` expects at most 1 argument(s), got 2",
            "`array.range` argument `id` expects numeric array, got simple array<UDT>",
            "`array.range` argument `id` expects numeric array, got simple array<string>",
            "`array.range` argument `id` expects numeric array, got simple array<bool>",
            "`array.range` argument `id` expects numeric array, got simple array<color>",
            "`array.range` argument `id` expects numeric array, got simple array<chart.point>",
            "`array.range` expects at most 1 argument(s), got 2",
            "`array.median` argument `id` expects numeric array, got simple array<UDT>",
            "`array.median` argument `id` expects numeric array, got simple array<string>",
            "`array.median` argument `id` expects numeric array, got simple array<bool>",
            "`array.median` argument `id` expects numeric array, got simple array<color>",
            "`array.median` argument `id` expects numeric array, got simple array<chart.point>",
            "`array.median` expects at most 1 argument(s), got 2",
            "`array.mode` argument `id` expects numeric array, got simple array<UDT>",
            "`array.mode` argument `id` expects numeric array, got simple array<string>",
            "`array.mode` argument `id` expects numeric array, got simple array<bool>",
            "`array.mode` argument `id` expects numeric array, got simple array<color>",
            "`array.mode` argument `id` expects numeric array, got simple array<chart.point>",
            "`array.mode` expects at most 1 argument(s), got 2",
            "`array.percentile_nearest_rank` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.percentile_nearest_rank` argument `id` expects numeric array, got simple array<string>",
            "`array.percentile_nearest_rank` argument `id` expects numeric array, got simple array<bool>",
            "`array.percentile_nearest_rank` argument `id` expects numeric array, got simple array<color>",
            "`array.percentile_nearest_rank` argument `id` expects numeric array, got simple array<chart.point>",
            "`array.percentile_nearest_rank` expects at least 2 argument(s), got 1",
            "`array.percentile_nearest_rank` argument `percentage` expects series/simple numeric, got const string",
            "`array.percentile_nearest_rank` expects at most 2 argument(s), got 3",
            "`array.percentile_linear_interpolation` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.percentile_linear_interpolation` argument `id` expects numeric array, got simple array<string>",
            "`array.percentile_linear_interpolation` argument `id` expects numeric array, got simple array<bool>",
            "`array.percentile_linear_interpolation` argument `id` expects numeric array, got simple array<color>",
            "`array.percentile_linear_interpolation` argument `id` expects numeric array, got simple array<chart.point>",
            "`array.percentile_linear_interpolation` expects at least 2 argument(s), got 1",
            "`array.percentile_linear_interpolation` argument `percentage` expects series/simple numeric, got const string",
            "`array.percentile_linear_interpolation` expects at most 2 argument(s), got 3",
            "`array.percentrank` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.percentrank` argument `id` expects numeric array, got simple array<string>",
            "`array.percentrank` argument `id` expects numeric array, got simple array<bool>",
            "`array.percentrank` argument `id` expects numeric array, got simple array<color>",
            "`array.percentrank` argument `id` expects numeric array, got simple array<chart.point>",
            "`array.percentrank` expects at least 2 argument(s), got 1",
            "`array.percentrank` argument `index` expects simple integer-compatible, got const string",
            "`array.percentrank` argument `index` expects simple integer-compatible, got series int",
            "`array.percentrank` expects at most 2 argument(s), got 3",
            "`array.covariance` argument `id1` expects numeric array, got simple array<UDT>",
            "`array.covariance` argument `id2` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.covariance` argument `id1` expects numeric array, got simple array<string>",
            "`array.covariance` argument `id2` expects numeric array, got simple array<string>",
            "`array.covariance` argument `id2` expects numeric array, got series float",
            "`array.covariance` expects at least 2 argument(s), got 1",
            "`array.covariance` argument `biased` expects bool-compatible, got series float",
            "`array.covariance` expects at most 3 argument(s), got 4",
            "`array.standardize` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.standardize` argument `id` expects numeric array, got simple array<string>",
            "`array.standardize` argument `id` expects numeric array, got simple array<bool>",
            "`array.standardize` argument `id` expects numeric array, got simple array<color>",
            "`array.standardize` argument `id` expects numeric array, got simple array<chart.point>",
            "`array.standardize` expects at most 1 argument(s), got 2",
            "`array.variance` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.variance` argument `id` expects numeric array, got simple array<string>",
            "`array.variance` argument `id` expects numeric array, got simple array<bool>",
            "`array.variance` argument `id` expects numeric array, got simple array<color>",
            "`array.variance` argument `id` expects numeric array, got simple array<chart.point>",
            "`array.variance` argument `biased` expects bool-compatible, got series float",
            "`array.variance` expects at most 2 argument(s), got 3",
            "`array.stdev` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.stdev` argument `id` expects numeric array, got simple array<string>",
            "`array.stdev` argument `id` expects numeric array, got simple array<bool>",
            "`array.stdev` argument `id` expects numeric array, got simple array<color>",
            "`array.stdev` argument `id` expects numeric array, got simple array<chart.point>",
            "`array.stdev` argument `biased` expects bool-compatible, got series float",
            "`array.stdev` expects at most 2 argument(s), got 3",
            "`array.sort_indices` requires a scalar-tree UDT array and a root int, float, or string `sort_field`",
            "`array.sort_indices` argument `sort_field` expects const int or string, got series string",
            "`array.sort_indices` argument `id` expects numeric/string array, got simple array<bool>",
            "`array.sort_indices` argument `id` expects numeric/string array, got simple array<color>",
            "`array.sort_indices` argument `id` expects numeric/string array, got simple array<chart.point>",
            "`array.sort_indices` argument `order` expects const string, got series float",
            "`array.sort_indices` expects at most 2 argument(s), got 3",
            "`array.concat` expects at least 2 argument(s), got 1",
            "`array.concat` argument `id2` expects simple array<int>, got simple array<string>",
            "`array.concat` argument `id2` expects simple array<line>, got simple array<label>",
            "`array.concat` expects at most 2 argument(s), got 3",
            "`array.sort` argument `id` expects numeric/string array, got simple array<bool>",
            "`array.sort` argument `id` expects numeric/string array, got simple array<color>",
            "`array.sort` argument `id` expects numeric/string array, got simple array<chart.point>",
            "`array.sort` requires a scalar-tree UDT array and a root int, float, or string `sort_field`",
            "`array.sort` argument `order` expects const string, got series float",
            "`array.sort` expects at most 2 argument(s), got 3",
            "`array.join` argument `id` expects scalar array, got simple array<line>",
            "`array.join` argument `id` expects scalar array, got simple array<chart.point>",
            "`array.join` argument `separator` expects string-compatible, got series float",
            "`array.join` expects at most 2 argument(s), got 3",
            "`function_side_effect` is not supported: collection mutation via `array.concat` is not supported inside user-defined functions",
            "`function_side_effect` is not supported: collection mutation via `array.clear` is not supported inside user-defined functions",
            "`function_side_effect` is not supported: collection mutation via `array.reverse` is not supported inside user-defined functions",
            "`function_side_effect` is not supported: collection mutation via `array.pop` is not supported inside user-defined functions",
            "`function_side_effect` is not supported: collection mutation via `array.shift` is not supported inside user-defined functions",
            "`function_side_effect` is not supported: collection mutation via `array.remove` is not supported inside user-defined functions",
            "`function_side_effect` is not supported: collection mutation via `array.push` is not supported inside user-defined functions",
            "`function_side_effect` is not supported: collection mutation via `array.unshift` is not supported inside user-defined functions",
            "`function_side_effect` is not supported: collection mutation via `array.insert` is not supported inside user-defined functions",
            "`function_side_effect` is not supported: collection mutation via `array.set` is not supported inside user-defined functions",
            "`function_side_effect` is not supported: collection mutation via `array.fill` is not supported inside user-defined functions",
            "`function_side_effect` is not supported: collection mutation via `array.sort` is not supported inside user-defined functions",
        ],
    );
    assert_diagnostic_count(path, 255);
}

#[test]
fn reports_unsupported_user_type_array_control_flow_identity_fixture() {
    let path = "tests/fixtures/sema/unsupported_user_type_array_control_flow_identity.pine";
    assert_diagnostic_messages(
        path,
        &[
            "ternary UDT array branches must resolve to the same element identity",
            "if UDT array branches must resolve to the same element identity",
            "switch UDT array arms must resolve to the same element identity",
        ],
    );
    assert_diagnostic_count(path, 3);
}

#[test]
fn reports_unsupported_user_type_array_from_decl_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_user_type_array_from_decl.pine",
        &["cannot assign a different user-defined type array to `points`"],
    );
}

#[test]
fn reports_unsupported_array_new_unknown_udt_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_new_unknown_udt.pine",
        &["`array.new<Point>` requires a local or imported scalar-tree UDT"],
    );
}

#[test]
fn accepts_supported_array_new_nested_udt_field_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_array_new_nested_udt_field.pine");
}

#[test]
fn reports_unsupported_array_new_mixed_udt_initial_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_new_mixed_udt_initial.pine",
        &["`array.new<Point>` argument `initial_value` expects UDT `Point`, got `Marker`"],
    );
}

#[test]
fn reports_unsupported_array_new_udt_initial_type_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_new_udt_initial_type.pine",
        &["`array.new<Point>` argument `initial_value` expects UDT `Point`, got series float"],
    );
}

#[test]
fn reports_unsupported_array_push_udt_value_type_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_push_udt_value_type.pine",
        &["`array.push` argument `value` expects UDT value, got series float"],
    );
}

#[test]
fn reports_unsupported_array_new_udt_series_size_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_new_udt_series_size.pine",
        &["`array.new<Point>` argument `size` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn accepts_supported_udt_array_new_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_udt_array_new_return_qualifier.pine");
}

#[test]
fn reports_unsupported_udt_array_new_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_udt_array_new_return_qualifier.pine",
        &[
            "cannot pass a different user-defined type array to function parameter `values`",
            "cannot pass a different user-defined type array to function parameter `values`",
        ],
    );
}

#[test]
fn accepts_supported_udt_array_new_method_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_udt_array_new_method_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_udt_array_new_method_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_udt_array_new_method_return_qualifier.pine",
        &[
            "cannot pass a different user-defined type array to method parameter `values`",
            "cannot pass a different user-defined type array to method parameter `values`",
        ],
    );
}

#[test]
fn reports_unsupported_array_map_typed_decl_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_map_typed_decl.pine",
        &["typed declaration `array<map>` is not supported"],
    );
}

#[test]
fn reports_unsupported_array_matrix_typed_decl_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_matrix_typed_decl.pine",
        &["typed declaration `array<matrix>` is not supported"],
    );
}

#[test]
fn reports_unsupported_array_nested_typed_decl_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_nested_typed_decl.pine",
        &["typed declaration `array<array>` is not supported"],
    );
}

#[test]
fn reports_unsupported_array_tuple_typed_decl_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_tuple_typed_decl.pine",
        &["typed declaration `array<tuple>` is not supported"],
    );
}

#[test]
fn reports_unsupported_array_strategy_typed_decl_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_strategy_typed_decl.pine",
        &["typed declaration `array<strategy>` is not supported"],
    );
}

#[test]
fn reports_unsupported_array_typed_decl_initial_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_typed_decl_initial.pine",
        &["cannot initialize `prices` of type array<float> with simple array<string>"],
    );
}

#[test]
fn reports_unsupported_array_new_int_initial_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_new_int_initial.pine",
        &["`array.new_int` argument `initial_value` expects integer-compatible, got series float"],
    );
}

#[test]
fn reports_unsupported_array_new_bool_initial_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_new_bool_initial.pine",
        &["`array.new_bool` argument `initial_value` expects bool-compatible, got series float"],
    );
}

#[test]
fn reports_unsupported_array_new_string_initial_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_new_string_initial.pine",
        &[
            "`array.new_string` argument `initial_value` expects string-compatible, got series float",
        ],
    );
}

#[test]
fn reports_unsupported_array_new_color_initial_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_new_color_initial.pine",
        &["`array.new_color` argument `initial_value` expects color-compatible, got series float"],
    );
}

#[test]
fn reports_unsupported_array_new_line_initial_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_new_line_initial.pine",
        &["`array.new_line` argument `initial_value` expects line-compatible, got const string"],
    );
}

#[test]
fn reports_unsupported_array_new_label_initial_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_new_label_initial.pine",
        &["`array.new_label` argument `initial_value` expects label-compatible, got const string"],
    );
}

#[test]
fn reports_unsupported_array_new_box_initial_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_new_box_initial.pine",
        &["`array.new_box` argument `initial_value` expects box-compatible, got const string"],
    );
}

#[test]
fn reports_unsupported_array_new_table_initial_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_new_table_initial.pine",
        &["`array.new_table` argument `initial_value` expects table-compatible, got const string"],
    );
}

#[test]
fn reports_unsupported_array_new_linefill_initial_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_new_linefill_initial.pine",
        &[
            "`array.new_linefill` argument `initial_value` expects linefill-compatible, got const string",
        ],
    );
}

#[test]
fn reports_unsupported_array_new_polyline_initial_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_new_polyline_initial.pine",
        &[
            "`array.new_polyline` argument `initial_value` expects polyline-compatible, got const string",
        ],
    );
}

#[test]
fn reports_unsupported_box_cast_source_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_box_cast_source.pine",
        &["`box` argument `x` expects box-compatible, got const string"],
    );
}

#[test]
fn reports_unsupported_label_cast_source_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_label_cast_source.pine",
        &["`label` argument `x` expects label-compatible, got const string"],
    );
}

#[test]
fn reports_unsupported_line_cast_source_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_line_cast_source.pine",
        &["`line` argument `x` expects line-compatible, got const string"],
    );
}

#[test]
fn reports_unsupported_linefill_cast_source_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_linefill_cast_source.pine",
        &["`linefill` argument `x` expects linefill-compatible, got const string"],
    );
}

#[test]
fn reports_unsupported_polyline_cast_source_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_polyline_cast_source.pine",
        &["`polyline` argument `x` expects polyline-compatible, got const string"],
    );
}

#[test]
fn reports_unsupported_table_cast_source_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_table_cast_source.pine",
        &["`table` argument `x` expects table-compatible, got const string"],
    );
}

#[test]
fn reports_unsupported_array_from_array_argument_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_from_array_argument.pine",
        &["`array.from` expects one supported array element kind, got simple array<linefill>"],
    );
}

#[test]
fn reports_unsupported_array_from_mixed_kinds_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_from_mixed_kinds.pine",
        &["`array.from` expects one supported array element kind, got const int and const string"],
    );
}

#[test]
fn reports_unsupported_array_from_mixed_udt_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_from_mixed_udt.pine",
        &["`array.from` expects one scalar-tree UDT identity, got mixed UDT identities"],
    );
}

#[test]
fn accepts_supported_array_from_nested_udt_field_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_array_from_nested_udt_field.pine");
}

#[test]
fn reports_unsupported_array_from_all_na_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_from_all_na.pine",
        &["`array.from` expects one supported array element kind, got const na and const na"],
    );
}

#[test]
fn accepts_supported_array_from_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_array_from_return_qualifier.pine");
}

#[test]
fn reports_unsupported_array_from_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_from_return_qualifier.pine",
        &[
            "`matrix.add_row` argument `array_id` expects simple array<float>, got simple array<int>",
            "`matrix.add_row` argument `array_id` expects simple array<int>, got simple array<float>",
            "`matrix.add_row` argument `array_id` expects simple array<string>, got simple array<bool>",
            "`matrix.add_row` argument `array_id` expects simple array<color>, got simple array<string>",
            "`matrix.add_row` argument `array_id` expects simple array<bool>, got simple array<color>",
        ],
    );
}

#[test]
fn accepts_supported_udt_array_from_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_udt_array_from_return_qualifier.pine");
}

#[test]
fn reports_unsupported_udt_array_from_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_udt_array_from_return_qualifier.pine",
        &[
            "cannot pass a different user-defined type array to function parameter `values`",
            "cannot pass a different user-defined type array to function parameter `values`",
        ],
    );
}

#[test]
fn accepts_supported_udt_array_from_method_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_udt_array_from_method_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_udt_array_from_method_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_udt_array_from_method_return_qualifier.pine",
        &[
            "cannot pass a different user-defined type array to method parameter `values`",
            "cannot pass a different user-defined type array to method parameter `values`",
        ],
    );
}

#[test]
fn reports_unsupported_array_abs_chart_point_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_abs_chart_point.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_abs_chart_point_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_abs_chart_point_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_from_polyline_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_from_polyline.pine",
        &["`array.from` expects one supported array element kind, got simple array<polyline>"],
    );
}

#[test]
fn reports_unsupported_array_insert_value_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_insert_value.pine",
        &["`array.insert` argument `value` expects bool-compatible, got series float"],
    );
}

#[test]
fn reports_unsupported_array_insert_value_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_insert_value_method.pine",
        &["`array.insert` argument `value` expects bool-compatible, got series float"],
    );
}

#[test]
fn reports_unsupported_array_insert_index_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_insert_index.pine",
        &["`array.insert` argument `index` expects simple integer-compatible, got const string"],
    );
}

#[test]
fn reports_unsupported_array_insert_index_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_insert_index_method.pine",
        &["`array.insert` argument `index` expects simple integer-compatible, got const string"],
    );
}

#[test]
fn reports_unsupported_array_insert_udt_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_insert_udt.pine",
        &["`array.insert` argument `value` expects UDT `Point`, got `Marker`"],
    );
}

#[test]
fn reports_unsupported_array_insert_udt_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_insert_udt_method.pine",
        &["`array.insert` argument `value` expects UDT `Point`, got `Marker`"],
    );
}

#[test]
fn reports_unsupported_array_set_value_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_set_value.pine",
        &["`array.set` argument `value` expects bool-compatible, got series float"],
    );
}

#[test]
fn reports_unsupported_array_set_value_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_set_value_method.pine",
        &["`array.set` argument `value` expects bool-compatible, got series float"],
    );
}

#[test]
fn reports_unsupported_array_set_index_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_set_index.pine",
        &["`array.set` argument `index` expects simple integer-compatible, got const string"],
    );
}

#[test]
fn reports_unsupported_array_set_index_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_set_index_method.pine",
        &["`array.set` argument `index` expects simple integer-compatible, got const string"],
    );
}

#[test]
fn reports_unsupported_array_set_mixed_udt_fixture() {
    assert_array_udt_marker_value_identity_message(
        "tests/fixtures/sema/unsupported_array_set_mixed_udt.pine",
        "array.set",
    );
}

#[test]
fn reports_unsupported_array_set_mixed_udt_method_fixture() {
    assert_array_udt_marker_value_identity_message(
        "tests/fixtures/sema/unsupported_array_set_mixed_udt_method.pine",
        "array.set",
    );
}

#[test]
fn reports_unsupported_array_get_index_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_get_index.pine",
        &["`array.get` argument `index` expects simple integer-compatible, got const string"],
    );
}

#[test]
fn accepts_supported_array_na_simple_int_params_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_array_na_simple_int_params.pine");
}

#[test]
fn reports_unsupported_array_get_index_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_get_index_method.pine",
        &["`array.get` argument `index` expects simple integer-compatible, got const string"],
    );
}

#[test]
fn reports_unsupported_array_push_mixed_udt_fixture() {
    assert_array_udt_marker_value_identity_message(
        "tests/fixtures/sema/unsupported_array_push_mixed_udt.pine",
        "array.push",
    );
}

#[test]
fn reports_unsupported_array_push_mixed_udt_method_fixture() {
    assert_array_udt_marker_value_identity_message(
        "tests/fixtures/sema/unsupported_array_push_mixed_udt_method.pine",
        "array.push",
    );
}

#[test]
fn reports_unsupported_array_push_value_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_push_value.pine",
        &["`array.push` argument `value` expects bool-compatible, got series float"],
    );
}

#[test]
fn reports_unsupported_array_push_value_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_push_value_method.pine",
        &["`array.push` argument `value` expects bool-compatible, got series float"],
    );
}

#[test]
fn reports_unsupported_array_remove_index_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_remove_index.pine",
        &["`array.remove` argument `index` expects simple integer-compatible, got const string"],
    );
}

#[test]
fn reports_unsupported_array_remove_index_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_remove_index_method.pine",
        &["`array.remove` argument `index` expects simple integer-compatible, got const string"],
    );
}

#[test]
fn reports_unsupported_array_unshift_value_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_unshift_value.pine",
        &["`array.unshift` argument `value` expects bool-compatible, got series float"],
    );
}

#[test]
fn reports_unsupported_array_unshift_value_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_unshift_value_method.pine",
        &["`array.unshift` argument `value` expects bool-compatible, got series float"],
    );
}

#[test]
fn reports_unsupported_array_unshift_udt_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_unshift_udt.pine",
        &["`array.unshift` argument `value` expects UDT `Point`, got `Marker`"],
    );
}

#[test]
fn reports_unsupported_array_unshift_udt_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_unshift_udt_method.pine",
        &["`array.unshift` argument `value` expects UDT `Point`, got `Marker`"],
    );
}

#[test]
fn reports_unsupported_array_fill_value_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_fill_value.pine",
        &["`array.fill` argument `value` expects bool-compatible, got series float"],
    );
}

#[test]
fn reports_unsupported_array_fill_value_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_fill_value_method.pine",
        &["`array.fill` argument `value` expects bool-compatible, got series float"],
    );
}

#[test]
fn reports_unsupported_array_fill_udt_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_fill_udt.pine",
        &["`array.fill` argument `value` expects UDT `Point`, got `Marker`"],
    );
}

#[test]
fn reports_unsupported_array_fill_udt_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_fill_udt_method.pine",
        &["`array.fill` argument `value` expects UDT `Point`, got `Marker`"],
    );
}

#[test]
fn reports_unsupported_array_fill_index_from_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_fill_index_from.pine",
        &["`array.fill` argument `index_from` expects simple integer-compatible, got const string"],
    );
}

#[test]
fn reports_unsupported_array_fill_index_from_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_fill_index_from_method.pine",
        &["`array.fill` argument `index_from` expects simple integer-compatible, got const string"],
    );
}

#[test]
fn reports_unsupported_array_fill_index_to_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_fill_index_to.pine",
        &["`array.fill` argument `index_to` expects simple integer-compatible, got const string"],
    );
}

#[test]
fn reports_unsupported_array_fill_index_to_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_fill_index_to_method.pine",
        &["`array.fill` argument `index_to` expects simple integer-compatible, got const string"],
    );
}

#[test]
fn reports_unsupported_array_reverse_map_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_reverse_map.pine",
        &["`array.new<map>` requires a local or imported scalar-tree UDT"],
    );
}

#[test]
fn reports_unsupported_array_reverse_map_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_reverse_map_method.pine",
        &["`array.new<map>` requires a local or imported scalar-tree UDT"],
    );
}

#[test]
fn reports_unsupported_array_reverse_matrix_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_reverse_matrix.pine",
        &["`array.new<matrix>` requires a local or imported scalar-tree UDT"],
    );
}

#[test]
fn reports_unsupported_array_reverse_matrix_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_reverse_matrix_method.pine",
        &["`array.new<matrix>` requires a local or imported scalar-tree UDT"],
    );
}

#[test]
fn reports_unsupported_array_join_label_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_join_label.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_join_label_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_join_label_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_join_line_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_join_line.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_join_line_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_join_line_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_join_box_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_join_box.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_join_box_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_join_box_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_join_table_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_join_table.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_join_table_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_join_table_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_join_linefill_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_join_linefill.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_join_linefill_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_join_linefill_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_join_polyline_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_join_polyline.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_join_polyline_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_join_polyline_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_join_chart_point_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_join_chart_point.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_join_chart_point_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_join_chart_point_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_join_map_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_join_map.pine",
        &["`array.new<map>` requires a local or imported scalar-tree UDT"],
    );
}

#[test]
fn reports_unsupported_array_join_map_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_join_map_method.pine",
        &["`array.new<map>` requires a local or imported scalar-tree UDT"],
    );
}

#[test]
fn reports_unsupported_array_join_matrix_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_join_matrix.pine",
        &["`array.new<matrix>` requires a local or imported scalar-tree UDT"],
    );
}

#[test]
fn reports_unsupported_array_join_matrix_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_join_matrix_method.pine",
        &["`array.new<matrix>` requires a local or imported scalar-tree UDT"],
    );
}

#[test]
fn reports_unsupported_array_slice_map_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_slice_map.pine",
        &["`array.new<map>` requires a local or imported scalar-tree UDT"],
    );
}

#[test]
fn reports_unsupported_array_slice_map_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_slice_map_method.pine",
        &["`array.new<map>` requires a local or imported scalar-tree UDT"],
    );
}

#[test]
fn reports_unsupported_array_slice_matrix_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_slice_matrix.pine",
        &["`array.new<matrix>` requires a local or imported scalar-tree UDT"],
    );
}

#[test]
fn reports_unsupported_array_slice_matrix_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_slice_matrix_method.pine",
        &["`array.new<matrix>` requires a local or imported scalar-tree UDT"],
    );
}

#[test]
fn reports_unsupported_array_join_separator_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_join_separator.pine",
        &["`array.join` argument `separator` expects string-compatible, got series float"],
    );
}

#[test]
fn reports_unsupported_array_join_separator_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_join_separator_method.pine",
        &["`array.join` argument `separator` expects string-compatible, got series float"],
    );
}

#[test]
fn accepts_supported_array_join_series_string_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_array_join_series_string_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_array_join_simple_string_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_join_simple_string_return_qualifier.pine",
        &[
            "`timeframe.in_seconds` argument `timeframe` expects simple string, got series string",
            "`timeframe.in_seconds` argument `timeframe` expects simple string, got series string",
        ],
    );
}

#[test]
fn reports_unsupported_array_slice_index_from_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_slice_index_from.pine",
        &[
            "`array.slice` argument `index_from` expects simple integer-compatible, got const string",
        ],
    );
}

#[test]
fn reports_unsupported_array_slice_index_from_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_slice_index_from_method.pine",
        &[
            "`array.slice` argument `index_from` expects simple integer-compatible, got const string",
        ],
    );
}

#[test]
fn reports_unsupported_array_slice_index_to_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_slice_index_to.pine",
        &["`array.slice` argument `index_to` expects simple integer-compatible, got const string"],
    );
}

#[test]
fn reports_unsupported_array_slice_index_to_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_slice_index_to_method.pine",
        &["`array.slice` argument `index_to` expects simple integer-compatible, got const string"],
    );
}

#[test]
fn accepts_supported_array_same_as_arg_array_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_array_same_as_arg_array_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_array_same_as_arg_array_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_same_as_arg_array_return_qualifier.pine",
        &[
            "`matrix.add_row` argument `array_id` expects simple array<float>, got simple array<int>",
            "`matrix.add_col` argument `array_id` expects simple array<int>, got simple array<float>",
            "`matrix.add_row` argument `array_id` expects simple array<float>, got simple array<int>",
            "`matrix.add_col` argument `array_id` expects simple array<int>, got simple array<float>",
            "`matrix.add_row` argument `array_id` expects simple array<float>, got simple array<int>",
            "`matrix.add_col` argument `array_id` expects simple array<int>, got simple array<float>",
        ],
    );
}

#[test]
fn accepts_supported_array_same_as_arg_method_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_array_same_as_arg_method_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_array_same_as_arg_method_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_same_as_arg_method_return_qualifier.pine",
        &[
            "cannot pass simple array<int> to method parameter `values` of type array<float>",
            "cannot pass simple array<float> to method parameter `values` of type array<int>",
            "cannot pass simple array<bool> to method parameter `values` of type array<string>",
            "cannot pass simple array<string> to method parameter `values` of type array<color>",
            "cannot pass simple array<color> to method parameter `values` of type array<bool>",
            "cannot pass simple array<int> to method parameter `values` of type array<float>",
            "cannot pass simple array<float> to method parameter `values` of type array<int>",
            "cannot pass simple array<bool> to method parameter `values` of type array<string>",
            "cannot pass simple array<string> to method parameter `values` of type array<color>",
            "cannot pass simple array<color> to method parameter `values` of type array<bool>",
        ],
    );
}

#[test]
fn accepts_supported_object_array_same_as_arg_method_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_object_array_same_as_arg_method_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_object_array_same_as_arg_method_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_object_array_same_as_arg_method_return_qualifier.pine",
        &[
            "cannot pass simple array<label> to method parameter `values` of type array<line>",
            "cannot pass simple array<line> to method parameter `values` of type array<label>",
            "cannot pass simple array<linefill> to method parameter `values` of type array<polyline>",
            "cannot pass simple array<polyline> to method parameter `values` of type array<linefill>",
            "cannot pass simple array<box> to method parameter `values` of type array<table>",
            "cannot pass simple array<table> to method parameter `values` of type array<box>",
            "cannot pass simple array<label> to method parameter `values` of type array<chart.point>",
            "cannot pass simple array<label> to method parameter `values` of type array<line>",
            "cannot pass simple array<line> to method parameter `values` of type array<label>",
            "cannot pass simple array<linefill> to method parameter `values` of type array<polyline>",
            "cannot pass simple array<polyline> to method parameter `values` of type array<linefill>",
            "cannot pass simple array<box> to method parameter `values` of type array<table>",
            "cannot pass simple array<table> to method parameter `values` of type array<box>",
            "cannot pass simple array<label> to method parameter `values` of type array<chart.point>",
        ],
    );
}

#[test]
fn accepts_supported_udt_array_same_as_arg_method_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_udt_array_same_as_arg_method_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_udt_array_same_as_arg_method_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_udt_array_same_as_arg_method_return_qualifier.pine",
        &[
            "cannot pass a different user-defined type array to method parameter `values`",
            "cannot pass a different user-defined type array to method parameter `values`",
            "cannot pass a different user-defined type array to method parameter `values`",
            "cannot pass a different user-defined type array to method parameter `values`",
        ],
    );
}

#[test]
fn accepts_supported_array_element_series_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_array_element_series_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_array_element_const_input_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_element_const_input_return_qualifier.pine",
        &[
            "`plot` argument `show_last` expects const/input int, got series int",
            "`plot` argument `show_last` expects const/input int, got series int",
            "`plot` argument `show_last` expects const/input int, got series int",
            "`plot` argument `show_last` expects const/input int, got series int",
            "`plot` argument `show_last` expects const/input int, got series int",
            "`plot` argument `show_last` expects const/input int, got series int",
            "`plot` argument `show_last` expects const/input int, got series int",
            "`plot` argument `show_last` expects const/input int, got series int",
            "`plot` argument `show_last` expects const/input int, got series int",
            "`plot` argument `show_last` expects const/input int, got series int",
            "`plot` argument `show_last` expects const/input int, got series int",
            "`plot` argument `show_last` expects const/input int, got series int",
        ],
    );
}

#[test]
fn accepts_supported_object_array_element_method_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_object_array_element_method_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_object_array_element_method_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_object_array_element_method_return_qualifier.pine",
        &[
            "cannot pass series label to method parameter `value` of type line",
            "cannot pass series line to method parameter `value` of type chart.point",
            "cannot pass series chart.point to method parameter `value` of type label",
            "cannot pass series label to method parameter `value` of type line",
            "cannot pass series label to method parameter `value` of type chart.point",
            "cannot pass series chart.point to method parameter `value` of type label",
        ],
    );
}

#[test]
fn accepts_supported_udt_array_element_method_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_udt_array_element_method_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_udt_array_element_method_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_udt_array_element_method_return_qualifier.pine",
        &[
            "cannot pass argument to method parameter `other` of user-defined type `Point`",
            "cannot pass argument to method parameter `other` of user-defined type `Point`",
            "cannot pass argument to method parameter `other` of user-defined type `Point`",
            "cannot pass argument to method parameter `other` of user-defined type `Point`",
            "cannot pass argument to method parameter `other` of user-defined type `Point`",
            "cannot pass argument to method parameter `other` of user-defined type `Point`",
        ],
    );
}

#[test]
fn reports_unsupported_array_includes_value_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_includes_value.pine",
        &["`array.includes` argument `value` expects bool-compatible, got series float"],
    );
}

#[test]
fn reports_unsupported_array_includes_value_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_includes_value_method.pine",
        &["`array.includes` argument `value` expects bool-compatible, got series float"],
    );
}

#[test]
fn reports_unsupported_array_includes_udt_fixture() {
    assert_array_udt_value_identity_message(
        "tests/fixtures/sema/unsupported_array_includes_udt.pine",
        "array.includes",
    );
}

#[test]
fn reports_unsupported_array_includes_udt_method_fixture() {
    assert_array_udt_value_identity_message(
        "tests/fixtures/sema/unsupported_array_includes_udt_method.pine",
        "array.includes",
    );
}

#[test]
fn accepts_supported_array_includes_object_udt_series_bool_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_array_includes_object_udt_series_bool_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_array_includes_object_udt_const_bool_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_includes_object_udt_const_bool_return_qualifier.pine",
        &[
            "`input.bool` argument `defval` expects const bool, got series bool",
            "`input.bool` argument `defval` expects const bool, got series bool",
            "`input.bool` argument `defval` expects const bool, got series bool",
            "`input.bool` argument `defval` expects const bool, got series bool",
        ],
    );
}

#[test]
fn accepts_supported_array_predicate_series_bool_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_array_predicate_series_bool_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_array_predicate_const_bool_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_predicate_const_bool_return_qualifier.pine",
        &[
            "`input.bool` argument `defval` expects const bool, got series bool",
            "`input.bool` argument `defval` expects const bool, got series bool",
            "`input.bool` argument `defval` expects const bool, got series bool",
            "`input.bool` argument `defval` expects const bool, got series bool",
            "`input.bool` argument `defval` expects const bool, got series bool",
            "`input.bool` argument `defval` expects const bool, got series bool",
            "`input.bool` argument `defval` expects const bool, got series bool",
            "`input.bool` argument `defval` expects const bool, got series bool",
            "`input.bool` argument `defval` expects const bool, got series bool",
            "`input.bool` argument `defval` expects const bool, got series bool",
            "`input.bool` argument `defval` expects const bool, got series bool",
            "`input.bool` argument `defval` expects const bool, got series bool",
            "`input.bool` argument `defval` expects const bool, got series bool",
            "`input.bool` argument `defval` expects const bool, got series bool",
        ],
    );
}

#[test]
fn reports_unsupported_array_indexof_value_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_indexof_value.pine",
        &["`array.indexof` argument `value` expects bool-compatible, got series float"],
    );
}

#[test]
fn reports_unsupported_array_indexof_value_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_indexof_value_method.pine",
        &["`array.indexof` argument `value` expects bool-compatible, got series float"],
    );
}

#[test]
fn reports_unsupported_array_indexof_udt_fixture() {
    assert_array_udt_value_identity_message(
        "tests/fixtures/sema/unsupported_array_indexof_udt.pine",
        "array.indexof",
    );
}

#[test]
fn reports_unsupported_array_indexof_udt_method_fixture() {
    assert_array_udt_value_identity_message(
        "tests/fixtures/sema/unsupported_array_indexof_udt_method.pine",
        "array.indexof",
    );
}

#[test]
fn reports_unsupported_array_lastindexof_value_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_lastindexof_value.pine",
        &["`array.lastindexof` argument `value` expects bool-compatible, got series float"],
    );
}

#[test]
fn reports_unsupported_array_lastindexof_value_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_lastindexof_value_method.pine",
        &["`array.lastindexof` argument `value` expects bool-compatible, got series float"],
    );
}

#[test]
fn reports_unsupported_array_lastindexof_udt_fixture() {
    assert_array_udt_value_identity_message(
        "tests/fixtures/sema/unsupported_array_lastindexof_udt.pine",
        "array.lastindexof",
    );
}

#[test]
fn reports_unsupported_array_lastindexof_udt_method_fixture() {
    assert_array_udt_value_identity_message(
        "tests/fixtures/sema/unsupported_array_lastindexof_udt_method.pine",
        "array.lastindexof",
    );
}

#[test]
fn accepts_supported_array_indexof_object_udt_simple_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_array_indexof_object_udt_simple_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_array_indexof_object_udt_const_input_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_indexof_object_udt_const_input_return_qualifier.pine",
        &[
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`plot` argument `show_last` expects const/input int, got simple int",
        ],
    );
}

#[test]
fn accepts_supported_array_search_simple_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_array_search_simple_return_qualifier.pine");
}

#[test]
fn accepts_supported_array_binary_search_float_simple_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_array_binary_search_float_simple_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_array_search_const_input_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_search_const_input_return_qualifier.pine",
        &[
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`plot` argument `show_last` expects const/input int, got simple int",
        ],
    );
}

#[test]
fn reports_unsupported_array_binary_search_float_const_input_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_binary_search_float_const_input_return_qualifier.pine",
        &[
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`plot` argument `show_last` expects const/input int, got simple int",
        ],
    );
}

#[test]
fn accepts_supported_array_abs_same_as_arg_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_array_abs_same_as_arg_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_array_abs_same_as_arg_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_abs_same_as_arg_return_qualifier.pine",
        &[
            "`matrix.add_row` argument `array_id` expects simple array<float>, got simple array<int>",
            "`matrix.add_col` argument `array_id` expects simple array<int>, got simple array<float>",
            "`matrix.add_row` argument `array_id` expects simple array<int>, got simple array<float>",
            "`matrix.add_col` argument `array_id` expects simple array<float>, got simple array<int>",
        ],
    );
}

#[test]
fn accepts_supported_array_numeric_series_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_array_numeric_series_return_qualifier.pine",
    );
}

#[test]
fn accepts_supported_array_min_max_nth_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_array_min_max_nth.pine");
}

#[test]
fn reports_unsupported_array_min_max_nth_type_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_min_max_nth_type.pine",
        &[
            "`array.min` argument `nth` expects integer-compatible, got const float",
            "`array.max` argument `nth` expects integer-compatible, got const string",
            "`array.min` argument `nth` expects integer-compatible, got const float",
            "`array.max` argument `nth` expects integer-compatible, got const string",
        ],
    );
}

#[test]
fn reports_unsupported_array_min_max_nth_bindings_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_min_max_nth_bindings.pine",
        &[
            "`array.min` is missing argument `id`",
            "`array.max` argument `id` is provided more than once",
            "`array.min` argument `id` is provided more than once",
            "positional arguments cannot follow named arguments in built-in calls",
            "`array.min` argument `id` is provided more than once",
        ],
    );
}

#[test]
fn accepts_supported_object_array_from_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_object_array_from_return_qualifier.pine");
}

#[test]
fn reports_unsupported_object_array_from_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_object_array_from_return_qualifier.pine",
        &[
            "cannot pass simple array<label> to function parameter `values` of type series array<line>",
            "cannot pass simple array<line> to function parameter `values` of type series array<label>",
            "cannot pass simple array<polyline> to function parameter `values` of type series array<linefill>",
            "cannot pass simple array<linefill> to function parameter `values` of type series array<polyline>",
            "cannot pass simple array<box> to function parameter `values` of type series array<table>",
            "cannot pass simple array<table> to function parameter `values` of type series array<box>",
            "cannot pass simple array<label> to function parameter `values` of type series array<chart.point>",
        ],
    );
}

#[test]
fn accepts_supported_object_array_from_method_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_object_array_from_method_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_object_array_from_method_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_object_array_from_method_return_qualifier.pine",
        &[
            "cannot pass simple array<label> to method parameter `values` of type array<line>",
            "cannot pass simple array<line> to method parameter `values` of type array<label>",
            "cannot pass simple array<polyline> to method parameter `values` of type array<linefill>",
            "cannot pass simple array<linefill> to method parameter `values` of type array<polyline>",
            "cannot pass simple array<box> to method parameter `values` of type array<table>",
            "cannot pass simple array<table> to method parameter `values` of type array<box>",
            "cannot pass simple array<label> to method parameter `values` of type array<chart.point>",
        ],
    );
}

#[test]
fn reports_unsupported_array_numeric_int_const_input_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_numeric_int_const_input_return_qualifier.pine",
        &[
            "`plot` argument `show_last` expects const/input int, got series int",
            "`plot` argument `show_last` expects const/input int, got series int",
            "`plot` argument `show_last` expects const/input int, got series int",
            "`plot` argument `show_last` expects const/input int, got series int",
            "`plot` argument `show_last` expects const/input int, got series int",
            "`plot` argument `show_last` expects const/input int, got series int",
            "`plot` argument `show_last` expects const/input int, got series int",
            "`plot` argument `show_last` expects const/input int, got series int",
            "`plot` argument `show_last` expects const/input int, got series int",
            "`plot` argument `show_last` expects const/input int, got series int",
            "`plot` argument `show_last` expects const/input int, got series int",
            "`plot` argument `show_last` expects const/input int, got series int",
            "`plot` argument `show_last` expects const/input int, got series int",
            "`plot` argument `show_last` expects const/input int, got series int",
        ],
    );
}

#[test]
fn reports_unsupported_array_numeric_float_const_input_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_numeric_float_const_input_return_qualifier.pine",
        &[
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
        ],
    );
}

#[test]
fn accepts_supported_array_stat_series_float_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_array_stat_series_float_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_array_stat_const_input_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_stat_const_input_return_qualifier.pine",
        &[
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
        ],
    );
}

#[test]
fn accepts_supported_array_fixed_simple_array_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_array_fixed_simple_array_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_array_fixed_simple_array_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_fixed_simple_array_return_qualifier.pine",
        &[
            "`matrix.add_row` argument `array_id` expects simple array<int>, got simple array<float>",
            "`matrix.add_col` argument `array_id` expects simple array<int>, got simple array<float>",
            "`matrix.add_row` argument `array_id` expects simple array<int>, got simple array<float>",
            "`matrix.add_col` argument `array_id` expects simple array<int>, got simple array<float>",
            "`matrix.add_row` argument `array_id` expects simple array<float>, got simple array<int>",
            "`matrix.add_col` argument `array_id` expects simple array<float>, got simple array<int>",
            "`matrix.add_row` argument `array_id` expects simple array<float>, got simple array<int>",
            "`matrix.add_col` argument `array_id` expects simple array<float>, got simple array<int>",
        ],
    );
}

#[test]
fn accepts_supported_array_sort_udt_named_const_field_fixture() {
    let path =
        workspace_fixture("tests/fixtures/sema/supported_array_sort_udt_named_const_field.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_array_sort_udt_field_index_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_array_sort_udt_field_index.pine");
}

#[test]
fn reports_unsupported_array_sort_bool_fixture() {
    assert_array_sort_id_message(
        "tests/fixtures/sema/unsupported_array_sort_bool.pine",
        "array.sort",
        "array<bool>",
    );
}

#[test]
fn reports_unsupported_array_sort_bool_method_fixture() {
    assert_array_sort_id_message(
        "tests/fixtures/sema/unsupported_array_sort_bool_method.pine",
        "array.sort",
        "array<bool>",
    );
}

#[test]
fn reports_unsupported_array_sort_color_fixture() {
    assert_array_sort_id_message(
        "tests/fixtures/sema/unsupported_array_sort_color.pine",
        "array.sort",
        "array<color>",
    );
}

#[test]
fn reports_unsupported_array_sort_color_method_fixture() {
    assert_array_sort_id_message(
        "tests/fixtures/sema/unsupported_array_sort_color_method.pine",
        "array.sort",
        "array<color>",
    );
}

#[test]
fn reports_unsupported_array_sort_label_fixture() {
    assert_array_sort_id_message(
        "tests/fixtures/sema/unsupported_array_sort_label.pine",
        "array.sort",
        "array<label>",
    );
}

#[test]
fn reports_unsupported_array_sort_label_method_fixture() {
    assert_array_sort_id_message(
        "tests/fixtures/sema/unsupported_array_sort_label_method.pine",
        "array.sort",
        "array<label>",
    );
}

#[test]
fn reports_unsupported_array_sort_line_fixture() {
    assert_array_sort_id_message(
        "tests/fixtures/sema/unsupported_array_sort_line.pine",
        "array.sort",
        "array<line>",
    );
}

#[test]
fn reports_unsupported_array_sort_line_method_fixture() {
    assert_array_sort_id_message(
        "tests/fixtures/sema/unsupported_array_sort_line_method.pine",
        "array.sort",
        "array<line>",
    );
}

#[test]
fn reports_unsupported_array_sort_box_fixture() {
    assert_array_sort_id_message(
        "tests/fixtures/sema/unsupported_array_sort_box.pine",
        "array.sort",
        "array<box>",
    );
}

#[test]
fn reports_unsupported_array_sort_box_method_fixture() {
    assert_array_sort_id_message(
        "tests/fixtures/sema/unsupported_array_sort_box_method.pine",
        "array.sort",
        "array<box>",
    );
}

#[test]
fn reports_unsupported_array_sort_table_fixture() {
    assert_array_sort_id_message(
        "tests/fixtures/sema/unsupported_array_sort_table.pine",
        "array.sort",
        "array<table>",
    );
}

#[test]
fn reports_unsupported_array_sort_table_method_fixture() {
    assert_array_sort_id_message(
        "tests/fixtures/sema/unsupported_array_sort_table_method.pine",
        "array.sort",
        "array<table>",
    );
}

#[test]
fn reports_unsupported_array_sort_linefill_fixture() {
    assert_array_sort_id_message(
        "tests/fixtures/sema/unsupported_array_sort_linefill.pine",
        "array.sort",
        "array<linefill>",
    );
}

#[test]
fn reports_unsupported_array_sort_linefill_namespace_fixture() {
    assert_array_sort_id_message(
        "tests/fixtures/sema/unsupported_array_sort_linefill_namespace.pine",
        "array.sort",
        "array<linefill>",
    );
}

#[test]
fn reports_unsupported_array_sort_polyline_fixture() {
    assert_array_sort_id_message(
        "tests/fixtures/sema/unsupported_array_sort_polyline.pine",
        "array.sort",
        "array<polyline>",
    );
}

#[test]
fn reports_unsupported_array_sort_polyline_namespace_fixture() {
    assert_array_sort_id_message(
        "tests/fixtures/sema/unsupported_array_sort_polyline_namespace.pine",
        "array.sort",
        "array<polyline>",
    );
}

#[test]
fn reports_unsupported_array_sort_chart_point_fixture() {
    assert_array_sort_id_message(
        "tests/fixtures/sema/unsupported_array_sort_chart_point.pine",
        "array.sort",
        "array<chart.point>",
    );
}

#[test]
fn reports_unsupported_array_sort_chart_point_namespace_fixture() {
    assert_array_sort_id_message(
        "tests/fixtures/sema/unsupported_array_sort_chart_point_namespace.pine",
        "array.sort",
        "array<chart.point>",
    );
}

#[test]
fn reports_unsupported_array_sort_udt_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_sort_udt.pine",
        &[
            "`array.sort` requires a scalar-tree UDT array and a root int, float, or string `sort_field`",
        ],
    );
}

#[test]
fn reports_unsupported_array_sort_udt_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_sort_udt_method.pine",
        &[
            "`array.sort` requires a scalar-tree UDT array and a root int, float, or string `sort_field`",
        ],
    );
}

#[test]
fn reports_unsupported_array_sort_udt_field_index_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_sort_udt_field_index.pine",
        &[
            "`array.sort` requires a scalar-tree UDT array and a root int, float, or string `sort_field`",
            "`array.sort` requires a scalar-tree UDT array and a root int, float, or string `sort_field`",
            "`array.sort` requires a scalar-tree UDT array and a root int, float, or string `sort_field`",
            "`array.sort` argument `sort_field` expects const int or string, got series int",
            "`array.sort` requires a scalar-tree UDT array and a root int, float, or string `sort_field`",
            "`array.sort` argument `sort_field` expects const int or string, got const float",
            "`array.sort` requires a scalar-tree UDT array and a root int, float, or string `sort_field`",
        ],
    );
}

#[test]
fn reports_unsupported_array_sort_udt_unknown_field_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_sort_udt_unknown_field.pine",
        &[
            "`array.sort` requires a scalar-tree UDT array and a root int, float, or string `sort_field`",
        ],
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_sort_udt_named_const_unknown_field.pine",
        &[
            "`array.sort` requires a scalar-tree UDT array and a root int, float, or string `sort_field`",
        ],
    );
}

#[test]
fn reports_unsupported_array_sort_udt_unknown_field_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_sort_udt_unknown_field_method.pine",
        &[
            "`array.sort` requires a scalar-tree UDT array and a root int, float, or string `sort_field`",
        ],
    );
}

#[test]
fn reports_unsupported_array_sort_udt_bool_field_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_sort_udt_bool_field.pine",
        &[
            "`array.sort` requires a scalar-tree UDT array and a root int, float, or string `sort_field`",
        ],
    );
}

#[test]
fn reports_unsupported_array_sort_udt_bool_field_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_sort_udt_bool_field_method.pine",
        &[
            "`array.sort` requires a scalar-tree UDT array and a root int, float, or string `sort_field`",
        ],
    );
}

#[test]
fn reports_unsupported_array_sort_udt_dynamic_field_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_sort_udt_dynamic_field.pine",
        &[
            "`array.sort` argument `sort_field` expects const int or string, got series string",
            "`array.sort` requires a scalar-tree UDT array and a root int, float, or string `sort_field`",
        ],
    );
}

#[test]
fn reports_unsupported_array_sort_udt_dynamic_field_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_sort_udt_dynamic_field_method.pine",
        &[
            "`array.sort` argument `sort_field` expects const int or string, got series string",
            "`array.sort` requires a scalar-tree UDT array and a root int, float, or string `sort_field`",
        ],
    );
}

#[test]
fn reports_unsupported_array_sort_order_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_sort_order.pine",
        &["`array.sort` argument `order` expects const string, got series float"],
    );
}

#[test]
fn reports_unsupported_array_sort_order_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_sort_order_method.pine",
        &["`array.sort` argument `order` expects const string, got series float"],
    );
}

#[test]
fn reports_unsupported_array_sort_indices_bool_fixture() {
    assert_array_sort_id_message(
        "tests/fixtures/sema/unsupported_array_sort_indices_bool.pine",
        "array.sort_indices",
        "array<bool>",
    );
}

#[test]
fn reports_unsupported_array_sort_indices_bool_namespace_fixture() {
    assert_array_sort_id_message(
        "tests/fixtures/sema/unsupported_array_sort_indices_bool_namespace.pine",
        "array.sort_indices",
        "array<bool>",
    );
}

#[test]
fn reports_unsupported_array_sort_indices_label_fixture() {
    assert_array_sort_id_message(
        "tests/fixtures/sema/unsupported_array_sort_indices_label.pine",
        "array.sort_indices",
        "array<label>",
    );
}

#[test]
fn reports_unsupported_array_sort_indices_label_namespace_fixture() {
    assert_array_sort_id_message(
        "tests/fixtures/sema/unsupported_array_sort_indices_label_namespace.pine",
        "array.sort_indices",
        "array<label>",
    );
}

#[test]
fn reports_unsupported_array_sort_indices_line_fixture() {
    assert_array_sort_id_message(
        "tests/fixtures/sema/unsupported_array_sort_indices_line.pine",
        "array.sort_indices",
        "array<line>",
    );
}

#[test]
fn reports_unsupported_array_sort_indices_line_namespace_fixture() {
    assert_array_sort_id_message(
        "tests/fixtures/sema/unsupported_array_sort_indices_line_namespace.pine",
        "array.sort_indices",
        "array<line>",
    );
}

#[test]
fn reports_unsupported_array_sort_indices_box_fixture() {
    assert_array_sort_id_message(
        "tests/fixtures/sema/unsupported_array_sort_indices_box.pine",
        "array.sort_indices",
        "array<box>",
    );
}

#[test]
fn reports_unsupported_array_sort_indices_box_namespace_fixture() {
    assert_array_sort_id_message(
        "tests/fixtures/sema/unsupported_array_sort_indices_box_namespace.pine",
        "array.sort_indices",
        "array<box>",
    );
}

#[test]
fn reports_unsupported_array_sort_indices_table_fixture() {
    assert_array_sort_id_message(
        "tests/fixtures/sema/unsupported_array_sort_indices_table.pine",
        "array.sort_indices",
        "array<table>",
    );
}

#[test]
fn reports_unsupported_array_sort_indices_table_namespace_fixture() {
    assert_array_sort_id_message(
        "tests/fixtures/sema/unsupported_array_sort_indices_table_namespace.pine",
        "array.sort_indices",
        "array<table>",
    );
}

#[test]
fn reports_unsupported_array_sort_indices_linefill_fixture() {
    assert_array_sort_id_message(
        "tests/fixtures/sema/unsupported_array_sort_indices_linefill.pine",
        "array.sort_indices",
        "array<linefill>",
    );
}

#[test]
fn reports_unsupported_array_sort_indices_linefill_namespace_fixture() {
    assert_array_sort_id_message(
        "tests/fixtures/sema/unsupported_array_sort_indices_linefill_namespace.pine",
        "array.sort_indices",
        "array<linefill>",
    );
}

#[test]
fn reports_unsupported_array_sort_indices_polyline_fixture() {
    assert_array_sort_id_message(
        "tests/fixtures/sema/unsupported_array_sort_indices_polyline.pine",
        "array.sort_indices",
        "array<polyline>",
    );
}

#[test]
fn reports_unsupported_array_sort_indices_polyline_namespace_fixture() {
    assert_array_sort_id_message(
        "tests/fixtures/sema/unsupported_array_sort_indices_polyline_namespace.pine",
        "array.sort_indices",
        "array<polyline>",
    );
}

#[test]
fn reports_unsupported_array_sort_indices_chart_point_fixture() {
    assert_array_sort_id_message(
        "tests/fixtures/sema/unsupported_array_sort_indices_chart_point.pine",
        "array.sort_indices",
        "array<chart.point>",
    );
}

#[test]
fn reports_unsupported_array_sort_indices_chart_point_namespace_fixture() {
    assert_array_sort_id_message(
        "tests/fixtures/sema/unsupported_array_sort_indices_chart_point_namespace.pine",
        "array.sort_indices",
        "array<chart.point>",
    );
}

#[test]
fn reports_unsupported_array_sort_indices_udt_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_sort_indices_udt.pine",
        &[
            "`array.sort_indices` requires a scalar-tree UDT array and a root int, float, or string `sort_field`",
        ],
    );
}

#[test]
fn reports_unsupported_array_sort_indices_udt_namespace_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_sort_indices_udt_namespace.pine",
        &[
            "`array.sort_indices` requires a scalar-tree UDT array and a root int, float, or string `sort_field`",
        ],
    );
}

#[test]
fn reports_unsupported_array_sort_indices_udt_unknown_field_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_sort_indices_udt_unknown_field.pine",
        &[
            "`array.sort_indices` requires a scalar-tree UDT array and a root int, float, or string `sort_field`",
        ],
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_sort_indices_udt_named_const_unknown_field.pine",
        &[
            "`array.sort_indices` requires a scalar-tree UDT array and a root int, float, or string `sort_field`",
        ],
    );
}

#[test]
fn reports_unsupported_array_sort_indices_udt_unknown_field_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_sort_indices_udt_unknown_field_method.pine",
        &[
            "`array.sort_indices` requires a scalar-tree UDT array and a root int, float, or string `sort_field`",
        ],
    );
}

#[test]
fn reports_unsupported_array_sort_indices_udt_bool_field_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_sort_indices_udt_bool_field.pine",
        &[
            "`array.sort_indices` requires a scalar-tree UDT array and a root int, float, or string `sort_field`",
        ],
    );
}

#[test]
fn reports_unsupported_array_sort_indices_udt_bool_field_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_sort_indices_udt_bool_field_method.pine",
        &[
            "`array.sort_indices` requires a scalar-tree UDT array and a root int, float, or string `sort_field`",
        ],
    );
}

#[test]
fn reports_unsupported_array_sort_indices_udt_dynamic_field_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_sort_indices_udt_dynamic_field.pine",
        &[
            "`array.sort_indices` argument `sort_field` expects const int or string, got series string",
            "`array.sort_indices` requires a scalar-tree UDT array and a root int, float, or string `sort_field`",
        ],
    );
}

#[test]
fn reports_unsupported_array_sort_indices_udt_dynamic_field_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_sort_indices_udt_dynamic_field_method.pine",
        &[
            "`array.sort_indices` argument `sort_field` expects const int or string, got series string",
            "`array.sort_indices` requires a scalar-tree UDT array and a root int, float, or string `sort_field`",
        ],
    );
}

#[test]
fn reports_unsupported_array_sort_indices_color_fixture() {
    assert_array_sort_id_message(
        "tests/fixtures/sema/unsupported_array_sort_indices_color.pine",
        "array.sort_indices",
        "array<color>",
    );
}

#[test]
fn reports_unsupported_array_sort_indices_color_namespace_fixture() {
    assert_array_sort_id_message(
        "tests/fixtures/sema/unsupported_array_sort_indices_color_namespace.pine",
        "array.sort_indices",
        "array<color>",
    );
}

#[test]
fn reports_unsupported_array_sort_indices_order_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_sort_indices_order.pine",
        &["`array.sort_indices` argument `order` expects const string, got series float"],
    );
}

#[test]
fn reports_unsupported_array_sort_indices_order_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_sort_indices_order_method.pine",
        &["`array.sort_indices` argument `order` expects const string, got series float"],
    );
}

#[test]
fn reports_unsupported_array_stdev_bool_fixture() {
    assert_array_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_stdev_bool.pine",
        "array.stdev",
        "array<bool>",
    );
}

#[test]
fn reports_unsupported_array_stdev_bool_method_fixture() {
    assert_array_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_stdev_bool_method.pine",
        "array.stdev",
        "array<bool>",
    );
}

#[test]
fn reports_unsupported_array_stdev_string_fixture() {
    assert_array_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_stdev_string.pine",
        "array.stdev",
        "array<string>",
    );
}

#[test]
fn reports_unsupported_array_stdev_string_method_fixture() {
    assert_array_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_stdev_string_method.pine",
        "array.stdev",
        "array<string>",
    );
}

#[test]
fn reports_unsupported_array_stdev_color_fixture() {
    assert_array_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_stdev_color.pine",
        "array.stdev",
        "array<color>",
    );
}

#[test]
fn reports_unsupported_array_stdev_color_method_fixture() {
    assert_array_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_stdev_color_method.pine",
        "array.stdev",
        "array<color>",
    );
}

#[test]
fn reports_unsupported_array_stdev_label_fixture() {
    assert_array_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_stdev_label.pine",
        "array.stdev",
        "array<label>",
    );
}

#[test]
fn reports_unsupported_array_stdev_label_method_fixture() {
    assert_array_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_stdev_label_method.pine",
        "array.stdev",
        "array<label>",
    );
}

#[test]
fn reports_unsupported_array_stdev_line_fixture() {
    assert_array_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_stdev_line.pine",
        "array.stdev",
        "array<line>",
    );
}

#[test]
fn reports_unsupported_array_stdev_line_method_fixture() {
    assert_array_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_stdev_line_method.pine",
        "array.stdev",
        "array<line>",
    );
}

#[test]
fn reports_unsupported_array_stdev_box_fixture() {
    assert_array_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_stdev_box.pine",
        "array.stdev",
        "array<box>",
    );
}

#[test]
fn reports_unsupported_array_stdev_box_method_fixture() {
    assert_array_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_stdev_box_method.pine",
        "array.stdev",
        "array<box>",
    );
}

#[test]
fn reports_unsupported_array_stdev_table_fixture() {
    assert_array_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_stdev_table.pine",
        "array.stdev",
        "array<table>",
    );
}

#[test]
fn reports_unsupported_array_stdev_table_method_fixture() {
    assert_array_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_stdev_table_method.pine",
        "array.stdev",
        "array<table>",
    );
}

#[test]
fn reports_unsupported_array_stdev_linefill_fixture() {
    assert_array_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_stdev_linefill.pine",
        "array.stdev",
        "array<linefill>",
    );
}

#[test]
fn reports_unsupported_array_stdev_linefill_method_fixture() {
    assert_array_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_stdev_linefill_method.pine",
        "array.stdev",
        "array<linefill>",
    );
}

#[test]
fn reports_unsupported_array_stdev_polyline_fixture() {
    assert_array_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_stdev_polyline.pine",
        "array.stdev",
        "array<polyline>",
    );
}

#[test]
fn reports_unsupported_array_stdev_polyline_method_fixture() {
    assert_array_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_stdev_polyline_method.pine",
        "array.stdev",
        "array<polyline>",
    );
}

#[test]
fn reports_unsupported_array_stdev_chart_point_fixture() {
    assert_array_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_stdev_chart_point.pine",
        "array.stdev",
        "array<chart.point>",
    );
}

#[test]
fn reports_unsupported_array_stdev_chart_point_method_fixture() {
    assert_array_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_stdev_chart_point_method.pine",
        "array.stdev",
        "array<chart.point>",
    );
}

#[test]
fn reports_unsupported_array_stdev_udt_fixture() {
    assert_array_unsupported_udt_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_stdev_udt.pine",
        "array.stdev",
    );
}

#[test]
fn reports_unsupported_array_stdev_udt_method_fixture() {
    assert_array_unsupported_udt_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_stdev_udt_method.pine",
        "array.stdev",
    );
}

#[test]
fn reports_unsupported_array_stdev_biased_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_stdev_biased.pine",
        &["`array.stdev` argument `biased` expects bool-compatible, got series float"],
    );
}

#[test]
fn reports_unsupported_array_stdev_biased_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_stdev_biased_method.pine",
        &["`array.stdev` argument `biased` expects bool-compatible, got series float"],
    );
}

#[test]
fn reports_unsupported_array_variance_bool_fixture() {
    assert_array_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_variance_bool.pine",
        "array.variance",
        "array<bool>",
    );
}

#[test]
fn reports_unsupported_array_variance_bool_method_fixture() {
    assert_array_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_variance_bool_method.pine",
        "array.variance",
        "array<bool>",
    );
}

#[test]
fn reports_unsupported_array_variance_string_fixture() {
    assert_array_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_variance_string.pine",
        "array.variance",
        "array<string>",
    );
}

#[test]
fn reports_unsupported_array_variance_string_method_fixture() {
    assert_array_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_variance_string_method.pine",
        "array.variance",
        "array<string>",
    );
}

#[test]
fn reports_unsupported_array_variance_color_fixture() {
    assert_array_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_variance_color.pine",
        "array.variance",
        "array<color>",
    );
}

#[test]
fn reports_unsupported_array_variance_color_method_fixture() {
    assert_array_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_variance_color_method.pine",
        "array.variance",
        "array<color>",
    );
}

#[test]
fn reports_unsupported_array_variance_label_fixture() {
    assert_array_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_variance_label.pine",
        "array.variance",
        "array<label>",
    );
}

#[test]
fn reports_unsupported_array_variance_label_method_fixture() {
    assert_array_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_variance_label_method.pine",
        "array.variance",
        "array<label>",
    );
}

#[test]
fn reports_unsupported_array_variance_line_fixture() {
    assert_array_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_variance_line.pine",
        "array.variance",
        "array<line>",
    );
}

#[test]
fn reports_unsupported_array_variance_line_method_fixture() {
    assert_array_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_variance_line_method.pine",
        "array.variance",
        "array<line>",
    );
}

#[test]
fn reports_unsupported_array_variance_box_fixture() {
    assert_array_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_variance_box.pine",
        "array.variance",
        "array<box>",
    );
}

#[test]
fn reports_unsupported_array_variance_box_method_fixture() {
    assert_array_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_variance_box_method.pine",
        "array.variance",
        "array<box>",
    );
}

#[test]
fn reports_unsupported_array_variance_table_fixture() {
    assert_array_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_variance_table.pine",
        "array.variance",
        "array<table>",
    );
}

#[test]
fn reports_unsupported_array_variance_table_method_fixture() {
    assert_array_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_variance_table_method.pine",
        "array.variance",
        "array<table>",
    );
}

#[test]
fn reports_unsupported_array_variance_linefill_fixture() {
    assert_array_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_variance_linefill.pine",
        "array.variance",
        "array<linefill>",
    );
}

#[test]
fn reports_unsupported_array_variance_linefill_method_fixture() {
    assert_array_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_variance_linefill_method.pine",
        "array.variance",
        "array<linefill>",
    );
}

#[test]
fn reports_unsupported_array_variance_polyline_fixture() {
    assert_array_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_variance_polyline.pine",
        "array.variance",
        "array<polyline>",
    );
}

#[test]
fn reports_unsupported_array_variance_polyline_method_fixture() {
    assert_array_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_variance_polyline_method.pine",
        "array.variance",
        "array<polyline>",
    );
}

#[test]
fn reports_unsupported_array_variance_chart_point_fixture() {
    assert_array_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_variance_chart_point.pine",
        "array.variance",
        "array<chart.point>",
    );
}

#[test]
fn reports_unsupported_array_variance_chart_point_method_fixture() {
    assert_array_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_variance_chart_point_method.pine",
        "array.variance",
        "array<chart.point>",
    );
}

#[test]
fn reports_unsupported_array_variance_udt_fixture() {
    assert_array_unsupported_udt_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_variance_udt.pine",
        "array.variance",
    );
}

#[test]
fn reports_unsupported_array_variance_udt_method_fixture() {
    assert_array_unsupported_udt_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_variance_udt_method.pine",
        "array.variance",
    );
}

#[test]
fn reports_unsupported_array_variance_biased_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_variance_biased.pine",
        &["`array.variance` argument `biased` expects bool-compatible, got series float"],
    );
}

#[test]
fn reports_unsupported_array_variance_biased_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_variance_biased_method.pine",
        &["`array.variance` argument `biased` expects bool-compatible, got series float"],
    );
}

#[test]
fn reports_unsupported_array_every_string_fixture() {
    assert_array_numeric_bool_id_message(
        "tests/fixtures/sema/unsupported_array_every_string.pine",
        "array.every",
        "array<string>",
    );
}

#[test]
fn reports_unsupported_array_every_string_method_fixture() {
    assert_array_numeric_bool_id_message(
        "tests/fixtures/sema/unsupported_array_every_string_method.pine",
        "array.every",
        "array<string>",
    );
}

#[test]
fn reports_unsupported_array_every_color_fixture() {
    assert_array_numeric_bool_id_message(
        "tests/fixtures/sema/unsupported_array_every_color.pine",
        "array.every",
        "array<color>",
    );
}

#[test]
fn reports_unsupported_array_every_color_method_fixture() {
    assert_array_numeric_bool_id_message(
        "tests/fixtures/sema/unsupported_array_every_color_method.pine",
        "array.every",
        "array<color>",
    );
}

#[test]
fn reports_unsupported_array_every_label_fixture() {
    assert_array_numeric_bool_id_message(
        "tests/fixtures/sema/unsupported_array_every_label.pine",
        "array.every",
        "array<label>",
    );
}

#[test]
fn reports_unsupported_array_every_label_method_fixture() {
    assert_array_numeric_bool_id_message(
        "tests/fixtures/sema/unsupported_array_every_label_method.pine",
        "array.every",
        "array<label>",
    );
}

#[test]
fn reports_unsupported_array_every_line_fixture() {
    assert_array_numeric_bool_id_message(
        "tests/fixtures/sema/unsupported_array_every_line.pine",
        "array.every",
        "array<line>",
    );
}

#[test]
fn reports_unsupported_array_every_line_method_fixture() {
    assert_array_numeric_bool_id_message(
        "tests/fixtures/sema/unsupported_array_every_line_method.pine",
        "array.every",
        "array<line>",
    );
}

#[test]
fn reports_unsupported_array_every_box_fixture() {
    assert_array_numeric_bool_id_message(
        "tests/fixtures/sema/unsupported_array_every_box.pine",
        "array.every",
        "array<box>",
    );
}

#[test]
fn reports_unsupported_array_every_box_method_fixture() {
    assert_array_numeric_bool_id_message(
        "tests/fixtures/sema/unsupported_array_every_box_method.pine",
        "array.every",
        "array<box>",
    );
}

#[test]
fn reports_unsupported_array_every_table_fixture() {
    assert_array_numeric_bool_id_message(
        "tests/fixtures/sema/unsupported_array_every_table.pine",
        "array.every",
        "array<table>",
    );
}

#[test]
fn reports_unsupported_array_every_table_method_fixture() {
    assert_array_numeric_bool_id_message(
        "tests/fixtures/sema/unsupported_array_every_table_method.pine",
        "array.every",
        "array<table>",
    );
}

#[test]
fn reports_unsupported_array_every_linefill_fixture() {
    assert_array_numeric_bool_id_message(
        "tests/fixtures/sema/unsupported_array_every_linefill.pine",
        "array.every",
        "array<linefill>",
    );
}

#[test]
fn reports_unsupported_array_every_linefill_method_fixture() {
    assert_array_numeric_bool_id_message(
        "tests/fixtures/sema/unsupported_array_every_linefill_method.pine",
        "array.every",
        "array<linefill>",
    );
}

#[test]
fn reports_unsupported_array_every_polyline_fixture() {
    assert_array_numeric_bool_id_message(
        "tests/fixtures/sema/unsupported_array_every_polyline.pine",
        "array.every",
        "array<polyline>",
    );
}

#[test]
fn reports_unsupported_array_every_polyline_method_fixture() {
    assert_array_numeric_bool_id_message(
        "tests/fixtures/sema/unsupported_array_every_polyline_method.pine",
        "array.every",
        "array<polyline>",
    );
}

#[test]
fn reports_unsupported_array_every_chart_point_fixture() {
    assert_array_numeric_bool_id_message(
        "tests/fixtures/sema/unsupported_array_every_chart_point.pine",
        "array.every",
        "array<chart.point>",
    );
}

#[test]
fn reports_unsupported_array_every_chart_point_method_fixture() {
    assert_array_numeric_bool_id_message(
        "tests/fixtures/sema/unsupported_array_every_chart_point_method.pine",
        "array.every",
        "array<chart.point>",
    );
}

#[test]
fn reports_unsupported_array_every_udt_fixture() {
    assert_array_unsupported_udt_numeric_bool_id_message(
        "tests/fixtures/sema/unsupported_array_every_udt.pine",
        "array.every",
    );
}

#[test]
fn reports_unsupported_array_every_udt_method_fixture() {
    assert_array_unsupported_udt_numeric_bool_id_message(
        "tests/fixtures/sema/unsupported_array_every_udt_method.pine",
        "array.every",
    );
}

#[test]
fn reports_unsupported_array_some_string_fixture() {
    assert_array_numeric_bool_id_message(
        "tests/fixtures/sema/unsupported_array_some_string.pine",
        "array.some",
        "array<string>",
    );
}

#[test]
fn reports_unsupported_array_some_string_method_fixture() {
    assert_array_numeric_bool_id_message(
        "tests/fixtures/sema/unsupported_array_some_string_method.pine",
        "array.some",
        "array<string>",
    );
}

#[test]
fn reports_unsupported_array_some_color_fixture() {
    assert_array_numeric_bool_id_message(
        "tests/fixtures/sema/unsupported_array_some_color.pine",
        "array.some",
        "array<color>",
    );
}

#[test]
fn reports_unsupported_array_some_color_method_fixture() {
    assert_array_numeric_bool_id_message(
        "tests/fixtures/sema/unsupported_array_some_color_method.pine",
        "array.some",
        "array<color>",
    );
}

#[test]
fn reports_unsupported_array_some_label_fixture() {
    assert_array_numeric_bool_id_message(
        "tests/fixtures/sema/unsupported_array_some_label.pine",
        "array.some",
        "array<label>",
    );
}

#[test]
fn reports_unsupported_array_some_label_method_fixture() {
    assert_array_numeric_bool_id_message(
        "tests/fixtures/sema/unsupported_array_some_label_method.pine",
        "array.some",
        "array<label>",
    );
}

#[test]
fn reports_unsupported_array_some_line_fixture() {
    assert_array_numeric_bool_id_message(
        "tests/fixtures/sema/unsupported_array_some_line.pine",
        "array.some",
        "array<line>",
    );
}

#[test]
fn reports_unsupported_array_some_line_method_fixture() {
    assert_array_numeric_bool_id_message(
        "tests/fixtures/sema/unsupported_array_some_line_method.pine",
        "array.some",
        "array<line>",
    );
}

#[test]
fn reports_unsupported_array_some_box_fixture() {
    assert_array_numeric_bool_id_message(
        "tests/fixtures/sema/unsupported_array_some_box.pine",
        "array.some",
        "array<box>",
    );
}

#[test]
fn reports_unsupported_array_some_box_method_fixture() {
    assert_array_numeric_bool_id_message(
        "tests/fixtures/sema/unsupported_array_some_box_method.pine",
        "array.some",
        "array<box>",
    );
}

#[test]
fn reports_unsupported_array_some_table_fixture() {
    assert_array_numeric_bool_id_message(
        "tests/fixtures/sema/unsupported_array_some_table.pine",
        "array.some",
        "array<table>",
    );
}

#[test]
fn reports_unsupported_array_some_table_method_fixture() {
    assert_array_numeric_bool_id_message(
        "tests/fixtures/sema/unsupported_array_some_table_method.pine",
        "array.some",
        "array<table>",
    );
}

#[test]
fn reports_unsupported_array_some_linefill_fixture() {
    assert_array_numeric_bool_id_message(
        "tests/fixtures/sema/unsupported_array_some_linefill.pine",
        "array.some",
        "array<linefill>",
    );
}

#[test]
fn reports_unsupported_array_some_linefill_method_fixture() {
    assert_array_numeric_bool_id_message(
        "tests/fixtures/sema/unsupported_array_some_linefill_method.pine",
        "array.some",
        "array<linefill>",
    );
}

#[test]
fn reports_unsupported_array_some_polyline_fixture() {
    assert_array_numeric_bool_id_message(
        "tests/fixtures/sema/unsupported_array_some_polyline.pine",
        "array.some",
        "array<polyline>",
    );
}

#[test]
fn reports_unsupported_array_some_polyline_method_fixture() {
    assert_array_numeric_bool_id_message(
        "tests/fixtures/sema/unsupported_array_some_polyline_method.pine",
        "array.some",
        "array<polyline>",
    );
}

#[test]
fn reports_unsupported_array_some_chart_point_fixture() {
    assert_array_numeric_bool_id_message(
        "tests/fixtures/sema/unsupported_array_some_chart_point.pine",
        "array.some",
        "array<chart.point>",
    );
}

#[test]
fn reports_unsupported_array_some_chart_point_method_fixture() {
    assert_array_numeric_bool_id_message(
        "tests/fixtures/sema/unsupported_array_some_chart_point_method.pine",
        "array.some",
        "array<chart.point>",
    );
}

#[test]
fn reports_unsupported_array_some_udt_fixture() {
    assert_array_unsupported_udt_numeric_bool_id_message(
        "tests/fixtures/sema/unsupported_array_some_udt.pine",
        "array.some",
    );
}

#[test]
fn reports_unsupported_array_some_udt_method_fixture() {
    assert_array_unsupported_udt_numeric_bool_id_message(
        "tests/fixtures/sema/unsupported_array_some_udt_method.pine",
        "array.some",
    );
}

#[test]
fn reports_unsupported_array_covariance_bool_fixture() {
    assert_array_numeric_pair_messages(
        "tests/fixtures/sema/unsupported_array_covariance_bool.pine",
        "array.covariance",
        "array<bool>",
    );
}

#[test]
fn reports_unsupported_array_covariance_bool_method_fixture() {
    assert_array_numeric_pair_messages(
        "tests/fixtures/sema/unsupported_array_covariance_bool_method.pine",
        "array.covariance",
        "array<bool>",
    );
}

#[test]
fn reports_unsupported_array_covariance_string_fixture() {
    assert_array_numeric_pair_messages(
        "tests/fixtures/sema/unsupported_array_covariance_string.pine",
        "array.covariance",
        "array<string>",
    );
}

#[test]
fn reports_unsupported_array_covariance_string_method_fixture() {
    assert_array_numeric_pair_messages(
        "tests/fixtures/sema/unsupported_array_covariance_string_method.pine",
        "array.covariance",
        "array<string>",
    );
}

#[test]
fn reports_unsupported_array_covariance_color_fixture() {
    assert_array_numeric_pair_messages(
        "tests/fixtures/sema/unsupported_array_covariance_color.pine",
        "array.covariance",
        "array<color>",
    );
}

#[test]
fn reports_unsupported_array_covariance_color_method_fixture() {
    assert_array_numeric_pair_messages(
        "tests/fixtures/sema/unsupported_array_covariance_color_method.pine",
        "array.covariance",
        "array<color>",
    );
}

#[test]
fn reports_unsupported_array_covariance_label_fixture() {
    assert_array_numeric_pair_messages(
        "tests/fixtures/sema/unsupported_array_covariance_label.pine",
        "array.covariance",
        "array<label>",
    );
}

#[test]
fn reports_unsupported_array_covariance_label_method_fixture() {
    assert_array_numeric_pair_messages(
        "tests/fixtures/sema/unsupported_array_covariance_label_method.pine",
        "array.covariance",
        "array<label>",
    );
}

#[test]
fn reports_unsupported_array_covariance_line_fixture() {
    assert_array_numeric_pair_messages(
        "tests/fixtures/sema/unsupported_array_covariance_line.pine",
        "array.covariance",
        "array<line>",
    );
}

#[test]
fn reports_unsupported_array_covariance_line_method_fixture() {
    assert_array_numeric_pair_messages(
        "tests/fixtures/sema/unsupported_array_covariance_line_method.pine",
        "array.covariance",
        "array<line>",
    );
}

#[test]
fn reports_unsupported_array_covariance_box_fixture() {
    assert_array_numeric_pair_messages(
        "tests/fixtures/sema/unsupported_array_covariance_box.pine",
        "array.covariance",
        "array<box>",
    );
}

#[test]
fn reports_unsupported_array_covariance_box_method_fixture() {
    assert_array_numeric_pair_messages(
        "tests/fixtures/sema/unsupported_array_covariance_box_method.pine",
        "array.covariance",
        "array<box>",
    );
}

#[test]
fn reports_unsupported_array_covariance_table_fixture() {
    assert_array_numeric_pair_messages(
        "tests/fixtures/sema/unsupported_array_covariance_table.pine",
        "array.covariance",
        "array<table>",
    );
}

#[test]
fn reports_unsupported_array_covariance_table_method_fixture() {
    assert_array_numeric_pair_messages(
        "tests/fixtures/sema/unsupported_array_covariance_table_method.pine",
        "array.covariance",
        "array<table>",
    );
}

#[test]
fn reports_unsupported_array_covariance_linefill_fixture() {
    assert_array_numeric_pair_messages(
        "tests/fixtures/sema/unsupported_array_covariance_linefill.pine",
        "array.covariance",
        "array<linefill>",
    );
}

#[test]
fn reports_unsupported_array_covariance_linefill_method_fixture() {
    assert_array_numeric_pair_messages(
        "tests/fixtures/sema/unsupported_array_covariance_linefill_method.pine",
        "array.covariance",
        "array<linefill>",
    );
}

#[test]
fn reports_unsupported_array_covariance_polyline_fixture() {
    assert_array_numeric_pair_messages(
        "tests/fixtures/sema/unsupported_array_covariance_polyline.pine",
        "array.covariance",
        "array<polyline>",
    );
}

#[test]
fn reports_unsupported_array_covariance_polyline_method_fixture() {
    assert_array_numeric_pair_messages(
        "tests/fixtures/sema/unsupported_array_covariance_polyline_method.pine",
        "array.covariance",
        "array<polyline>",
    );
}

#[test]
fn reports_unsupported_array_covariance_chart_point_fixture() {
    assert_array_numeric_pair_messages(
        "tests/fixtures/sema/unsupported_array_covariance_chart_point.pine",
        "array.covariance",
        "array<chart.point>",
    );
}

#[test]
fn reports_unsupported_array_covariance_chart_point_method_fixture() {
    assert_array_numeric_pair_messages(
        "tests/fixtures/sema/unsupported_array_covariance_chart_point_method.pine",
        "array.covariance",
        "array<chart.point>",
    );
}

#[test]
fn reports_unsupported_array_covariance_udt_fixture() {
    assert_array_unsupported_udt_numeric_pair_messages(
        "tests/fixtures/sema/unsupported_array_covariance_udt.pine",
        "array.covariance",
    );
}

#[test]
fn reports_unsupported_array_covariance_udt_method_fixture() {
    assert_array_unsupported_udt_numeric_pair_messages(
        "tests/fixtures/sema/unsupported_array_covariance_udt_method.pine",
        "array.covariance",
    );
}

#[test]
fn reports_unsupported_array_covariance_id2_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_covariance_id2.pine",
        &["`array.covariance` argument `id2` expects numeric array, got series float"],
    );
}

#[test]
fn reports_unsupported_array_covariance_id2_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_covariance_id2_method.pine",
        &["`array.covariance` argument `id2` expects numeric array, got series float"],
    );
}

#[test]
fn reports_unsupported_array_covariance_biased_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_covariance_biased.pine",
        &["`array.covariance` argument `biased` expects bool-compatible, got series float"],
    );
}

#[test]
fn reports_unsupported_array_covariance_biased_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_covariance_biased_method.pine",
        &["`array.covariance` argument `biased` expects bool-compatible, got series float"],
    );
}

#[test]
fn reports_unsupported_array_percentrank_bool_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentrank_bool.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentrank_bool_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentrank_bool_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentrank_string_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentrank_string.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentrank_string_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentrank_string_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentrank_color_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentrank_color.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentrank_color_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentrank_color_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentrank_label_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentrank_label.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentrank_label_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentrank_label_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentrank_line_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentrank_line.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentrank_line_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentrank_line_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentrank_box_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentrank_box.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentrank_box_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentrank_box_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentrank_table_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentrank_table.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentrank_table_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentrank_table_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentrank_linefill_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentrank_linefill.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentrank_linefill_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentrank_linefill_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentrank_polyline_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentrank_polyline.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentrank_polyline_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentrank_polyline_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentrank_chart_point_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentrank_chart_point.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentrank_chart_point_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentrank_chart_point_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentrank_udt_fixture() {
    assert_array_unsupported_udt_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_percentrank_udt.pine",
        "array.percentrank",
    );
}

#[test]
fn reports_unsupported_array_percentrank_udt_method_fixture() {
    assert_array_unsupported_udt_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_percentrank_udt_method.pine",
        "array.percentrank",
    );
}

#[test]
fn reports_unsupported_array_percentrank_index_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_percentrank_index.pine",
        &[
            "`array.percentrank` argument `index` expects simple integer-compatible, got const string",
        ],
    );
}

#[test]
fn reports_unsupported_array_percentrank_index_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_percentrank_index_method.pine",
        &[
            "`array.percentrank` argument `index` expects simple integer-compatible, got const string",
        ],
    );
}

#[test]
fn reports_unsupported_array_percentile_linear_interpolation_bool_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentile_linear_interpolation_bool.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentile_linear_interpolation_bool_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentile_linear_interpolation_bool_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentile_linear_interpolation_string_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentile_linear_interpolation_string.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentile_linear_interpolation_string_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentile_linear_interpolation_string_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentile_linear_interpolation_color_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentile_linear_interpolation_color.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentile_linear_interpolation_color_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentile_linear_interpolation_color_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentile_linear_interpolation_label_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentile_linear_interpolation_label.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentile_linear_interpolation_label_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentile_linear_interpolation_label_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentile_linear_interpolation_line_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentile_linear_interpolation_line.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentile_linear_interpolation_line_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentile_linear_interpolation_line_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentile_linear_interpolation_box_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentile_linear_interpolation_box.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentile_linear_interpolation_box_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentile_linear_interpolation_box_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentile_linear_interpolation_table_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentile_linear_interpolation_table.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentile_linear_interpolation_table_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentile_linear_interpolation_table_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentile_linear_interpolation_linefill_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentile_linear_interpolation_linefill.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentile_linear_interpolation_linefill_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentile_linear_interpolation_linefill_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentile_linear_interpolation_polyline_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentile_linear_interpolation_polyline.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentile_linear_interpolation_polyline_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentile_linear_interpolation_polyline_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentile_linear_interpolation_chart_point_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentile_linear_interpolation_chart_point.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentile_linear_interpolation_chart_point_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentile_linear_interpolation_chart_point_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentile_linear_interpolation_udt_fixture() {
    assert_array_unsupported_udt_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_percentile_linear_interpolation_udt.pine",
        "array.percentile_linear_interpolation",
    );
}

#[test]
fn reports_unsupported_array_percentile_linear_interpolation_udt_method_fixture() {
    assert_array_unsupported_udt_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_percentile_linear_interpolation_udt_method.pine",
        "array.percentile_linear_interpolation",
    );
}

#[test]
fn reports_unsupported_array_percentile_linear_interpolation_percentage_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_percentile_linear_interpolation_percentage.pine",
        &[
            "`array.percentile_linear_interpolation` argument `percentage` expects series/simple numeric, got const string",
        ],
    );
}

#[test]
fn reports_unsupported_array_percentile_linear_interpolation_percentage_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_percentile_linear_interpolation_percentage_method.pine",
        &[
            "`array.percentile_linear_interpolation` argument `percentage` expects series/simple numeric, got const string",
        ],
    );
}

#[test]
fn reports_unsupported_array_percentile_nearest_rank_bool_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentile_nearest_rank_bool.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentile_nearest_rank_bool_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentile_nearest_rank_bool_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentile_nearest_rank_string_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentile_nearest_rank_string.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentile_nearest_rank_string_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentile_nearest_rank_string_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentile_nearest_rank_color_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentile_nearest_rank_color.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentile_nearest_rank_color_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentile_nearest_rank_color_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentile_nearest_rank_label_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentile_nearest_rank_label.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentile_nearest_rank_label_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentile_nearest_rank_label_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentile_nearest_rank_line_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentile_nearest_rank_line.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentile_nearest_rank_line_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentile_nearest_rank_line_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentile_nearest_rank_box_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentile_nearest_rank_box.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentile_nearest_rank_box_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentile_nearest_rank_box_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentile_nearest_rank_table_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentile_nearest_rank_table.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentile_nearest_rank_table_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentile_nearest_rank_table_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentile_nearest_rank_linefill_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentile_nearest_rank_linefill.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentile_nearest_rank_linefill_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentile_nearest_rank_linefill_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentile_nearest_rank_polyline_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentile_nearest_rank_polyline.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentile_nearest_rank_polyline_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentile_nearest_rank_polyline_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentile_nearest_rank_chart_point_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentile_nearest_rank_chart_point.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentile_nearest_rank_chart_point_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_percentile_nearest_rank_chart_point_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_percentile_nearest_rank_udt_fixture() {
    assert_array_unsupported_udt_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_percentile_nearest_rank_udt.pine",
        "array.percentile_nearest_rank",
    );
}

#[test]
fn reports_unsupported_array_percentile_nearest_rank_udt_method_fixture() {
    assert_array_unsupported_udt_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_percentile_nearest_rank_udt_method.pine",
        "array.percentile_nearest_rank",
    );
}

#[test]
fn reports_unsupported_array_percentile_nearest_rank_percentage_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_percentile_nearest_rank_percentage.pine",
        &[
            "`array.percentile_nearest_rank` argument `percentage` expects series/simple numeric, got const string",
        ],
    );
}

#[test]
fn reports_unsupported_array_percentile_nearest_rank_percentage_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_percentile_nearest_rank_percentage_method.pine",
        &[
            "`array.percentile_nearest_rank` argument `percentage` expects series/simple numeric, got const string",
        ],
    );
}

#[test]
fn reports_unsupported_array_mode_bool_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_mode_bool.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_mode_bool_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_mode_bool_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_mode_string_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_mode_string.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_mode_string_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_mode_string_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_mode_color_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_mode_color.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_mode_color_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_mode_color_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_mode_label_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_mode_label.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_mode_label_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_mode_label_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_mode_line_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_mode_line.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_mode_line_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_mode_line_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_mode_box_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_mode_box.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_mode_box_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_mode_box_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_mode_table_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_mode_table.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_mode_table_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_mode_table_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_mode_linefill_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_mode_linefill.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_mode_linefill_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_mode_linefill_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_mode_polyline_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_mode_polyline.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_mode_polyline_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_mode_polyline_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_mode_chart_point_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_mode_chart_point.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_mode_chart_point_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_mode_chart_point_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_mode_udt_fixture() {
    assert_array_unsupported_udt_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_mode_udt.pine",
        "array.mode",
    );
}

#[test]
fn reports_unsupported_array_mode_udt_method_fixture() {
    assert_array_unsupported_udt_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_mode_udt_method.pine",
        "array.mode",
    );
}

#[test]
fn reports_unsupported_array_median_bool_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_median_bool.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_median_bool_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_median_bool_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_median_string_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_median_string.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_median_string_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_median_string_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_median_color_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_median_color.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_median_color_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_median_color_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_median_label_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_median_label.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_median_label_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_median_label_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_median_line_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_median_line.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_median_line_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_median_line_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_median_box_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_median_box.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_median_box_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_median_box_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_median_table_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_median_table.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_median_table_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_median_table_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_median_linefill_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_median_linefill.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_median_linefill_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_median_linefill_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_median_polyline_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_median_polyline.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_median_polyline_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_median_polyline_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_median_chart_point_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_median_chart_point.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_median_chart_point_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_median_chart_point_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_median_udt_fixture() {
    assert_array_unsupported_udt_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_median_udt.pine",
        "array.median",
    );
}

#[test]
fn reports_unsupported_array_median_udt_method_fixture() {
    assert_array_unsupported_udt_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_median_udt_method.pine",
        "array.median",
    );
}

#[test]
fn reports_unsupported_array_range_bool_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_range_bool.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_range_bool_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_range_bool_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_range_string_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_range_string.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_range_string_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_range_string_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_range_color_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_range_color.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_range_color_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_range_color_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_range_label_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_range_label.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_range_label_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_range_label_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_range_line_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_range_line.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_range_line_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_range_line_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_range_box_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_range_box.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_range_box_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_range_box_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_range_table_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_range_table.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_range_table_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_range_table_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_range_linefill_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_range_linefill.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_range_linefill_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_range_linefill_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_range_polyline_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_range_polyline.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_range_polyline_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_range_polyline_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_range_chart_point_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_range_chart_point.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_range_chart_point_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_range_chart_point_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_range_udt_fixture() {
    assert_array_unsupported_udt_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_range_udt.pine",
        "array.range",
    );
}

#[test]
fn reports_unsupported_array_range_udt_method_fixture() {
    assert_array_unsupported_udt_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_range_udt_method.pine",
        "array.range",
    );
}

#[test]
fn reports_unsupported_array_avg_bool_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_avg_bool.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_avg_bool_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_avg_bool_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_avg_string_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_avg_string.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_avg_string_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_avg_string_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_avg_color_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_avg_color.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_avg_color_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_avg_color_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_avg_label_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_avg_label.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_avg_label_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_avg_label_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_avg_line_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_avg_line.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_avg_line_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_avg_line_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_avg_box_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_avg_box.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_avg_box_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_avg_box_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_avg_table_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_avg_table.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_avg_table_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_avg_table_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_avg_linefill_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_avg_linefill.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_avg_linefill_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_avg_linefill_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_avg_polyline_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_avg_polyline.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_avg_polyline_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_avg_polyline_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_avg_chart_point_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_avg_chart_point.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_avg_chart_point_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_avg_chart_point_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_avg_udt_fixture() {
    assert_array_unsupported_udt_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_avg_udt.pine",
        "array.avg",
    );
}

#[test]
fn reports_unsupported_array_avg_udt_method_fixture() {
    assert_array_unsupported_udt_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_avg_udt_method.pine",
        "array.avg",
    );
}

#[test]
fn reports_unsupported_array_sum_bool_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_sum_bool.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_sum_bool_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_sum_bool_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_sum_string_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_sum_string.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_sum_string_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_sum_string_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_sum_color_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_sum_color.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_sum_color_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_sum_color_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_sum_label_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_sum_label.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_sum_label_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_sum_label_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_sum_line_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_sum_line.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_sum_line_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_sum_line_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_sum_box_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_sum_box.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_sum_box_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_sum_box_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_sum_table_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_sum_table.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_sum_table_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_sum_table_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_sum_linefill_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_sum_linefill.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_sum_linefill_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_sum_linefill_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_sum_polyline_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_sum_polyline.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_sum_polyline_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_sum_polyline_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_sum_chart_point_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_sum_chart_point.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_sum_chart_point_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_sum_chart_point_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_sum_udt_fixture() {
    assert_array_unsupported_udt_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_sum_udt.pine",
        "array.sum",
    );
}

#[test]
fn reports_unsupported_array_sum_udt_method_fixture() {
    assert_array_unsupported_udt_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_sum_udt_method.pine",
        "array.sum",
    );
}

#[test]
fn reports_unsupported_array_max_bool_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_max_bool.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_max_bool_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_max_bool_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_max_string_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_max_string.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_max_string_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_max_string_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_max_color_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_max_color.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_max_color_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_max_color_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_max_label_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_max_label.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_max_label_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_max_label_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_max_line_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_max_line.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_max_line_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_max_line_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_max_box_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_max_box.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_max_box_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_max_box_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_max_table_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_max_table.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_max_table_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_max_table_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_max_linefill_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_max_linefill.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_max_linefill_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_max_linefill_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_max_polyline_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_max_polyline.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_max_polyline_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_max_polyline_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_max_chart_point_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_max_chart_point.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_max_chart_point_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_max_chart_point_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_max_udt_fixture() {
    assert_array_unsupported_udt_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_max_udt.pine",
        "array.max",
    );
}

#[test]
fn reports_unsupported_array_max_udt_method_fixture() {
    assert_array_unsupported_udt_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_max_udt_method.pine",
        "array.max",
    );
}

#[test]
fn reports_unsupported_array_min_bool_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_min_bool.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_min_bool_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_min_bool_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_min_string_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_min_string.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_min_string_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_min_string_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_min_color_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_min_color.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_min_color_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_min_color_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_min_label_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_min_label.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_min_label_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_min_label_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_min_line_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_min_line.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_min_line_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_min_line_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_min_box_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_min_box.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_min_box_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_min_box_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_min_table_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_min_table.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_min_table_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_min_table_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_min_linefill_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_min_linefill.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_min_linefill_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_min_linefill_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_min_polyline_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_min_polyline.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_min_polyline_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_min_polyline_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_min_chart_point_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_min_chart_point.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_min_chart_point_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_min_chart_point_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_min_udt_fixture() {
    assert_array_unsupported_udt_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_min_udt.pine",
        "array.min",
    );
}

#[test]
fn reports_unsupported_array_min_udt_method_fixture() {
    assert_array_unsupported_udt_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_min_udt_method.pine",
        "array.min",
    );
}

#[test]
fn reports_unsupported_array_abs_bool_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_abs_bool.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_abs_bool_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_abs_bool_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_abs_string_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_abs_string.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_abs_string_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_abs_string_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_abs_color_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_abs_color.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_abs_color_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_abs_color_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_abs_label_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_abs_label.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_abs_label_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_abs_label_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_abs_line_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_abs_line.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_abs_line_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_abs_line_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_abs_box_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_abs_box.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_abs_box_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_abs_box_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_abs_table_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_abs_table.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_abs_table_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_abs_table_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_abs_linefill_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_abs_linefill.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_abs_linefill_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_abs_linefill_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_abs_polyline_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_abs_polyline.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_abs_polyline_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_abs_polyline_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_abs_udt_fixture() {
    assert_array_unsupported_udt_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_abs_udt.pine",
        "array.abs",
    );
}

#[test]
fn reports_unsupported_array_abs_udt_method_fixture() {
    assert_array_unsupported_udt_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_abs_udt_method.pine",
        "array.abs",
    );
}

#[test]
fn reports_unsupported_array_binary_search_bool_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_bool.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_bool_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_bool_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_string_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_string.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_string_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_string_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_color_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_color.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_color_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_color_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_label_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_label.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_label_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_label_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_line_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_line.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_line_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_line_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_box_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_box.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_box_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_box_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_table_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_table.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_table_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_table_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_linefill_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_linefill.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_linefill_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_linefill_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_polyline_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_polyline.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_polyline_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_polyline_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_chart_point_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_chart_point.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_chart_point_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_chart_point_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_udt_fixture() {
    assert_array_binary_search_udt_message(
        "tests/fixtures/sema/unsupported_array_binary_search_udt.pine",
        "array.binary_search",
    );
}

#[test]
fn reports_unsupported_array_binary_search_udt_method_fixture() {
    assert_array_binary_search_udt_message(
        "tests/fixtures/sema/unsupported_array_binary_search_udt_method.pine",
        "array.binary_search",
    );
}

#[test]
fn reports_unsupported_array_binary_search_value_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_binary_search_value.pine",
        &["`array.binary_search` argument `value` expects integer-compatible, got const string"],
    );
}

#[test]
fn reports_unsupported_array_binary_search_value_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_binary_search_value_method.pine",
        &["`array.binary_search` argument `value` expects integer-compatible, got const string"],
    );
}

#[test]
fn reports_unsupported_array_binary_search_leftmost_bool_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_leftmost_bool.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_leftmost_bool_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_leftmost_bool_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_leftmost_string_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_leftmost_string.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_leftmost_string_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_leftmost_string_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_leftmost_color_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_leftmost_color.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_leftmost_color_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_leftmost_color_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_leftmost_label_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_leftmost_label.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_leftmost_label_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_leftmost_label_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_leftmost_line_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_leftmost_line.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_leftmost_line_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_leftmost_line_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_leftmost_box_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_leftmost_box.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_leftmost_box_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_leftmost_box_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_leftmost_table_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_leftmost_table.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_leftmost_table_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_leftmost_table_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_leftmost_linefill_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_leftmost_linefill.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_leftmost_linefill_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_leftmost_linefill_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_leftmost_polyline_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_leftmost_polyline.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_leftmost_polyline_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_leftmost_polyline_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_leftmost_chart_point_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_leftmost_chart_point.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_leftmost_chart_point_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_leftmost_chart_point_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_leftmost_udt_fixture() {
    assert_array_binary_search_udt_message(
        "tests/fixtures/sema/unsupported_array_binary_search_leftmost_udt.pine",
        "array.binary_search_leftmost",
    );
}

#[test]
fn reports_unsupported_array_binary_search_leftmost_udt_method_fixture() {
    assert_array_binary_search_udt_message(
        "tests/fixtures/sema/unsupported_array_binary_search_leftmost_udt_method.pine",
        "array.binary_search_leftmost",
    );
}

#[test]
fn reports_unsupported_array_binary_search_leftmost_value_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_binary_search_leftmost_value.pine",
        &[
            "`array.binary_search_leftmost` argument `value` expects integer-compatible, got const string",
        ],
    );
}

#[test]
fn reports_unsupported_array_binary_search_leftmost_value_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_binary_search_leftmost_value_method.pine",
        &[
            "`array.binary_search_leftmost` argument `value` expects integer-compatible, got const string",
        ],
    );
}

#[test]
fn reports_unsupported_array_binary_search_rightmost_bool_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_rightmost_bool.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_rightmost_bool_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_rightmost_bool_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_rightmost_string_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_rightmost_string.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_rightmost_string_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_rightmost_string_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_rightmost_color_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_rightmost_color.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_rightmost_color_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_rightmost_color_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_rightmost_label_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_rightmost_label.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_rightmost_label_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_rightmost_label_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_rightmost_line_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_rightmost_line.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_rightmost_line_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_rightmost_line_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_rightmost_box_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_rightmost_box.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_rightmost_box_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_rightmost_box_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_rightmost_table_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_rightmost_table.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_rightmost_table_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_rightmost_table_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_rightmost_linefill_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_rightmost_linefill.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_rightmost_linefill_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_rightmost_linefill_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_rightmost_polyline_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_rightmost_polyline.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_rightmost_polyline_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_rightmost_polyline_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_rightmost_chart_point_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_rightmost_chart_point.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_rightmost_chart_point_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_binary_search_rightmost_chart_point_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_binary_search_rightmost_udt_fixture() {
    assert_array_binary_search_udt_message(
        "tests/fixtures/sema/unsupported_array_binary_search_rightmost_udt.pine",
        "array.binary_search_rightmost",
    );
}

#[test]
fn reports_unsupported_array_binary_search_rightmost_udt_method_fixture() {
    assert_array_binary_search_udt_message(
        "tests/fixtures/sema/unsupported_array_binary_search_rightmost_udt_method.pine",
        "array.binary_search_rightmost",
    );
}

#[test]
fn reports_unsupported_array_binary_search_rightmost_value_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_binary_search_rightmost_value.pine",
        &[
            "`array.binary_search_rightmost` argument `value` expects integer-compatible, got const string",
        ],
    );
}

#[test]
fn reports_unsupported_array_binary_search_rightmost_value_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_binary_search_rightmost_value_method.pine",
        &[
            "`array.binary_search_rightmost` argument `value` expects integer-compatible, got const string",
        ],
    );
}

#[test]
fn reports_unsupported_array_standardize_bool_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_standardize_bool.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_standardize_bool_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_standardize_bool_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_standardize_string_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_standardize_string.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_standardize_string_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_standardize_string_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_standardize_color_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_standardize_color.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_standardize_color_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_standardize_color_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_standardize_label_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_standardize_label.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_standardize_label_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_standardize_label_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_standardize_line_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_standardize_line.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_standardize_line_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_standardize_line_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_standardize_box_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_standardize_box.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_standardize_box_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_standardize_box_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_standardize_table_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_standardize_table.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_standardize_table_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_standardize_table_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_standardize_linefill_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_standardize_linefill.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_standardize_linefill_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_standardize_linefill_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_standardize_polyline_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_standardize_polyline.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_standardize_polyline_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_standardize_polyline_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_standardize_chart_point_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_standardize_chart_point.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_standardize_chart_point_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_array_standardize_chart_point_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_array_standardize_udt_fixture() {
    assert_array_unsupported_udt_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_standardize_udt.pine",
        "array.standardize",
    );
}

#[test]
fn reports_unsupported_array_standardize_udt_method_fixture() {
    assert_array_unsupported_udt_numeric_id_message(
        "tests/fixtures/sema/unsupported_array_standardize_udt_method.pine",
        "array.standardize",
    );
}

#[test]
fn reports_unsupported_array_concat_mismatch_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_concat_mismatch.pine",
        &["`array.concat` argument `id2` expects simple array<int>, got simple array<float>"],
    );
}

#[test]
fn reports_unsupported_array_concat_id2_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_concat_id2.pine",
        &["`array.concat` argument `id2` expects array, got series float"],
    );
}

#[test]
fn reports_unsupported_array_concat_udt_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_concat_udt.pine",
        &["`array.concat` argument `id2` expects UDT array `Point`, got `Marker`"],
    );
}

#[test]
fn reports_unsupported_array_concat_map_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_concat_map.pine",
        &["`array.new<map>` requires a local or imported scalar-tree UDT"],
    );
}

#[test]
fn reports_unsupported_array_concat_map_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_concat_map_method.pine",
        &["`array.new<map>` requires a local or imported scalar-tree UDT"],
    );
}

#[test]
fn reports_unsupported_array_concat_matrix_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_concat_matrix.pine",
        &["`array.new<matrix>` requires a local or imported scalar-tree UDT"],
    );
}

#[test]
fn reports_unsupported_array_concat_matrix_method_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_concat_matrix_method.pine",
        &["`array.new<matrix>` requires a local or imported scalar-tree UDT"],
    );
}

#[test]
fn reports_import_fixture_missing_host_library() {
    let path = workspace_fixture("tests/fixtures/sema/unsupported_import.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(analysis.diagnostics.iter().any(|diagnostic| {
        diagnostic.code == "E_IMPORT_MISSING_LIBRARY"
            || diagnostic.code == "E_IMPORT_ALIAS_REQUIRED"
    }));
    assert!(analysis.hir.is_none());
}

#[test]
fn reports_unsupported_imported_udt_constructor_fixture() {
    assert_import_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_imported_udt_constructor.pine",
        "E_UDT_CONSTRUCTOR_ARG",
    );
}

#[test]
fn reports_unsupported_imported_udt_array_chained_field_mutation_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_chained_field_mutation.pine",
        &[
            "chained UDT array field mutation supports only same-local scalar-tree UDT arrays; imported UDT array field mutation is not supported",
        ],
    );
}

#[test]
fn reports_unsupported_imported_private_udt_constructor_fixture() {
    let path =
        workspace_fixture("tests/fixtures/sema/unsupported_imported_private_udt_constructor.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let library_path = workspace_fixture("tests/fixtures/libraries/import_private_udt_lib.pine");
    let library_text =
        fs::read_to_string(&library_path).expect("library fixture should be readable");
    let library_source = SourceFile::new(library_path.display().to_string(), library_text);
    let input = AnalysisInput::with_library_sources(
        source,
        vec![("user/private_udt/1".to_owned(), library_source)],
    )
    .expect("library fixture input should be valid");
    let analysis = analyze_input(&input);

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_IMPORT_PRIVATE_SYMBOL"),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn reports_unsupported_import_duplicate_exported_udt_fixture() {
    let path =
        workspace_fixture("tests/fixtures/sema/unsupported_import_duplicate_exported_udt.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let library_path = workspace_fixture("tests/fixtures/libraries/import_duplicate_udt_lib.pine");
    let library_text =
        fs::read_to_string(&library_path).expect("library fixture should be readable");
    let library_source = SourceFile::new(library_path.display().to_string(), library_text);
    let input = AnalysisInput::with_library_sources(
        source,
        vec![("user/duplicate_udt/1".to_owned(), library_source)],
    )
    .expect("library fixture input should be valid");
    let analysis = analyze_input(&input);

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_IMPORT_DUPLICATE_EXPORT"),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn reports_unsupported_import_duplicate_exported_udt_const_fixture() {
    let path = workspace_fixture(
        "tests/fixtures/sema/unsupported_import_duplicate_exported_udt_const.pine",
    );
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let library_path =
        workspace_fixture("tests/fixtures/libraries/import_duplicate_udt_const_lib.pine");
    let library_text =
        fs::read_to_string(&library_path).expect("library fixture should be readable");
    let library_source = SourceFile::new(library_path.display().to_string(), library_text);
    let input = AnalysisInput::with_library_sources(
        source,
        vec![("user/duplicate_udt_const/1".to_owned(), library_source)],
    )
    .expect("library fixture input should be valid");
    let analysis = analyze_input(&input);

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_IMPORT_DUPLICATE_EXPORT"),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn reports_unsupported_import_duplicate_exported_udt_function_fixture() {
    let path = workspace_fixture(
        "tests/fixtures/sema/unsupported_import_duplicate_exported_udt_function.pine",
    );
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let library_path =
        workspace_fixture("tests/fixtures/libraries/import_duplicate_udt_function_lib.pine");
    let library_text =
        fs::read_to_string(&library_path).expect("library fixture should be readable");
    let library_source = SourceFile::new(library_path.display().to_string(), library_text);
    let input = AnalysisInput::with_library_sources(
        source,
        vec![("user/duplicate_udt_function/1".to_owned(), library_source)],
    )
    .expect("library fixture input should be valid");
    let analysis = analyze_input(&input);

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_IMPORT_DUPLICATE_EXPORT"),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn reports_unsupported_imported_udt_varip_fixture() {
    assert_import_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_imported_udt_varip.pine",
        "E_UDT_CONSTRUCTOR_ARG",
    );
}

#[test]
fn accepts_supported_imported_udt_varip_non_scalar_typed_na_fixture() {
    assert_import_ok_fixture_with_library(
        "tests/fixtures/sema/supported_imported_udt_varip_non_scalar_typed_na.pine",
        "user/non_scalar_udt/1",
        "tests/fixtures/libraries/import_non_scalar_udt_lib.pine",
    );
}

#[test]
fn reports_unsupported_imported_udt_varip_non_scalar_reassign_fixture() {
    assert_import_unsupported_fixture_with_library(
        "tests/fixtures/sema/unsupported_imported_udt_varip_non_scalar_reassign.pine",
        "user/non_scalar_udt/1",
        "tests/fixtures/libraries/import_non_scalar_udt_lib.pine",
        "varip",
        "non-scalar UDT varip values can only remain `na`",
    );
}

#[test]
fn accepts_supported_imported_udt_varip_fixture() {
    assert_import_ok_fixture("tests/fixtures/sema/supported_imported_udt_varip_decl.pine");
}

#[test]
fn accepts_supported_imported_udt_history_fixture() {
    assert_import_ok_fixture("tests/fixtures/sema/supported_imported_udt_history.pine");
}

#[test]
fn accepts_supported_imported_user_type_array_control_flow_fixture() {
    assert_import_ok_fixture(
        "tests/fixtures/sema/supported_imported_user_type_array_control_flow.pine",
    );
}

#[test]
fn reports_unsupported_imported_user_type_array_control_flow_identity_fixture() {
    let path =
        "tests/fixtures/sema/unsupported_imported_user_type_array_control_flow_identity.pine";
    assert_import_diagnostic_messages_with_library(
        path,
        "user/udt/1",
        "tests/fixtures/libraries/import_udt_lib.pine",
        &[
            "ternary UDT array branches must resolve to the same element identity",
            "if UDT array branches must resolve to the same element identity",
            "switch UDT array arms must resolve to the same element identity",
        ],
    );
    assert_import_diagnostic_count_with_library(
        path,
        "user/udt/1",
        "tests/fixtures/libraries/import_udt_lib.pine",
        3,
    );
}

#[test]
fn accepts_supported_imported_user_type_array_returns_fixture() {
    assert_import_ok_fixture_with_library(
        "tests/fixtures/sema/supported_imported_user_type_array_udf_method_returns.pine",
        "user/udt_array_returns/1",
        "tests/fixtures/libraries/import_udt_array_return_lib.pine",
    );
}

#[test]
fn reports_unsupported_imported_user_type_array_return_identities_fixture() {
    let path = "tests/fixtures/sema/unsupported_imported_user_type_array_udf_method_return_identities.pine";
    let library = "tests/fixtures/libraries/import_udt_array_return_lib.pine";
    assert_import_diagnostic_messages_with_library(
        path,
        "user/udt_array_returns/1",
        library,
        &[
            "ternary UDT array branches must resolve to the same element identity",
            "if UDT array branches must resolve to the same element identity",
            "cannot assign a different user-defined type array to `wrong_typed`",
            "cannot pass a different user-defined type array to function parameter `values`",
            "cannot pass a different user-defined type array to method parameter `values`",
        ],
    );
    assert_import_diagnostic_count_with_library(path, "user/udt_array_returns/1", library, 5);
}

#[test]
fn accepts_supported_imported_user_type_array_tuple_returns_fixture() {
    assert_import_ok_fixture_with_library(
        "tests/fixtures/sema/supported_imported_user_type_array_tuple_returns.pine",
        "user/udt_array_returns/1",
        "tests/fixtures/libraries/import_udt_array_return_lib.pine",
    );
}

#[test]
fn reports_unsupported_imported_user_type_array_tuple_return_identities_fixture() {
    let path =
        "tests/fixtures/sema/unsupported_imported_user_type_array_tuple_return_identities.pine";
    let library = "tests/fixtures/libraries/import_udt_array_return_lib.pine";
    assert_import_diagnostic_messages_with_library(
        path,
        "user/udt_array_returns/1",
        library,
        &[
            "tuple element 1 user-defined type array must resolve to one element identity",
            "tuple element 2 user-defined type array must resolve to one element identity",
        ],
    );
    assert_import_diagnostic_count_with_library(path, "user/udt_array_returns/1", library, 27);

    let path = workspace_fixture(path);
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text.clone());
    let library_path = workspace_fixture(library);
    let library_text =
        fs::read_to_string(&library_path).expect("library fixture should be readable");
    let library_source = SourceFile::new(library_path.display().to_string(), library_text);
    let input = AnalysisInput::with_library_sources(
        source,
        vec![("user/udt_array_returns/1".to_owned(), library_source)],
    )
    .expect("library fixture input should be valid");
    let analysis = analyze_input(&input);
    let mut locations = HashSet::new();
    let tuple_diagnostics: Vec<_> = analysis
        .diagnostics
        .iter()
        .filter(|diagnostic| diagnostic.code == "E_TUPLE_UDT_ARRAY_IDENTITY")
        .collect();
    assert_eq!(tuple_diagnostics.len(), 27);
    for diagnostic in tuple_diagnostics {
        let excerpt = text
            .get(diagnostic.span.start..diagnostic.span.end)
            .expect("tuple identity diagnostic should point into the root fixture");
        assert!(
            excerpt.contains("tupleMixed"),
            "unexpected diagnostic span: {excerpt}"
        );
        assert!(locations.insert((
            diagnostic.message.clone(),
            diagnostic.span.start,
            diagnostic.span.end,
        )));
    }
}

#[test]
fn reports_unsupported_imported_user_type_array_tuple_alias_mutation_fixture() {
    let path = "tests/fixtures/sema/unsupported_imported_user_type_array_tuple_alias_mutation.pine";
    let library = "tests/fixtures/libraries/import_udt_array_return_lib.pine";
    assert_import_diagnostic_messages_with_library(
        path,
        "user/udt_array_returns/1",
        library,
        &[
            "tuple element 1 user-defined type array must resolve to one element identity",
            "tuple element 2 user-defined type array must resolve to one element identity",
        ],
    );
    assert_import_diagnostic_count_with_library(path, "user/udt_array_returns/1", library, 9);

    let path = workspace_fixture(path);
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text.clone());
    let library_path = workspace_fixture(library);
    let library_text =
        fs::read_to_string(&library_path).expect("library fixture should be readable");
    let library_source = SourceFile::new(library_path.display().to_string(), library_text);
    let input = AnalysisInput::with_library_sources(
        source,
        vec![("user/udt_array_returns/1".to_owned(), library_source)],
    )
    .expect("library fixture input should be valid");
    let analysis = analyze_input(&input);
    let mut locations = HashSet::new();
    let root_markers = [
        "direct_mixed =",
        "direct_reassigned :=",
        "branch_reassigned :=",
        "bad_tuple_decl_sink =",
        "bad_method_tuple_decl_sink =",
    ];
    for diagnostic in analysis
        .diagnostics
        .iter()
        .filter(|diagnostic| diagnostic.code == "E_TUPLE_UDT_ARRAY_IDENTITY")
    {
        let line_start = text[..diagnostic.span.start]
            .rfind('\n')
            .map_or(0, |index| index + 1);
        let line_end = text[diagnostic.span.end..]
            .find('\n')
            .map_or(text.len(), |index| diagnostic.span.end + index);
        let line = &text[line_start..line_end];
        assert!(
            root_markers.iter().any(|marker| line.contains(marker)),
            "tuple identity diagnostic should point at a root call or reassignment, got `{line}`"
        );
        assert!(locations.insert((
            diagnostic.message.clone(),
            diagnostic.span.start,
            diagnostic.span.end,
        )));
    }
    assert_eq!(locations.len(), 9);
}

#[test]
fn reports_unsupported_imported_user_type_array_call_result_chaining_fixture() {
    let path = "tests/fixtures/sema/unsupported_imported_user_type_array_call_result_chaining.pine";
    let library = "tests/fixtures/libraries/import_udt_array_return_lib.pine";
    assert_import_diagnostic_messages_with_library(
        path,
        "user/udt_array_returns/1",
        library,
        &[
            "`array.concat` argument `id2` expects UDT array `lib.First`, got `lib.Second`",
            "`array.sort_indices` requires a scalar-tree UDT array and a root int, float, or string `sort_field`",
            "`array.includes` argument `value` expects UDT `lib.First`, got `lib.Second`",
            "`array.includes` argument `value` expects UDT `lib.First`, got `lib.Second`",
            "`array.includes` argument `value` expects integer-compatible, got const string",
            "`array.includes` expects at most 2 argument(s), got 3",
            "`array.indexof` argument `value` expects UDT `lib.First`, got `lib.Second`",
            "`array.indexof` argument `value` expects UDT `lib.First`, got `lib.Second`",
            "`array.indexof` argument `value` expects integer-compatible, got const string",
            "`array.indexof` expects at most 2 argument(s), got 3",
            "`array.lastindexof` argument `value` expects UDT `lib.First`, got `lib.Second`",
            "`array.lastindexof` argument `value` expects UDT `lib.First`, got `lib.Second`",
            "`array.lastindexof` argument `value` expects integer-compatible, got const string",
            "`array.lastindexof` expects at most 2 argument(s), got 3",
            "`array.binary_search` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.binary_search` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.binary_search` argument `id` expects numeric array, got simple array<string>",
            "`array.binary_search` expects at most 2 argument(s), got 3",
            "`array.binary_search_leftmost` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.binary_search_leftmost` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.binary_search_leftmost` argument `id` expects numeric array, got simple array<string>",
            "`array.binary_search_leftmost` expects at most 2 argument(s), got 3",
            "`array.binary_search_rightmost` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.binary_search_rightmost` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.binary_search_rightmost` argument `id` expects numeric array, got simple array<string>",
            "`array.binary_search_rightmost` expects at most 2 argument(s), got 3",
            "`array.abs` argument `id` expects numeric array, got simple array<UDT>",
            "`array.abs` argument `id` expects numeric array, got simple array<string>",
            "`array.abs` expects at most 1 argument(s), got 2",
            "`array.min` argument `id` expects numeric array, got simple array<UDT>",
            "`array.min` argument `id` expects numeric array, got simple array<string>",
            "`array.min` argument `nth` expects integer-compatible, got const float",
            "`array.min` expects at most 2 argument(s), got 3",
            "`array.max` argument `id` expects numeric array, got simple array<UDT>",
            "`array.max` argument `id` expects numeric array, got simple array<string>",
            "`array.max` argument `nth` expects integer-compatible, got const float",
            "`array.max` expects at most 2 argument(s), got 3",
            "`array.sum` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.sum` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.sum` argument `id` expects numeric array, got simple array<string>",
            "`array.sum` expects at most 1 argument(s), got 2",
            "`array.avg` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.avg` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.avg` argument `id` expects numeric array, got simple array<string>",
            "`array.avg` expects at most 1 argument(s), got 2",
            "`array.range` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.range` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.range` argument `id` expects numeric array, got simple array<string>",
            "`array.range` expects at most 1 argument(s), got 2",
            "`array.median` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.median` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.median` argument `id` expects numeric array, got simple array<string>",
            "`array.median` expects at most 1 argument(s), got 2",
            "`array.mode` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.mode` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.mode` argument `id` expects numeric array, got simple array<string>",
            "`array.mode` expects at most 1 argument(s), got 2",
            "`array.percentile_nearest_rank` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.percentile_nearest_rank` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.percentile_nearest_rank` argument `id` expects numeric array, got simple array<string>",
            "`array.percentile_nearest_rank` expects at least 2 argument(s), got 1",
            "`array.percentile_nearest_rank` argument `percentage` expects series/simple numeric, got const string",
            "`array.percentile_nearest_rank` expects at most 2 argument(s), got 3",
            "`array.percentile_linear_interpolation` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.percentile_linear_interpolation` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.percentile_linear_interpolation` argument `id` expects numeric array, got simple array<string>",
            "`array.percentile_linear_interpolation` expects at least 2 argument(s), got 1",
            "`array.percentile_linear_interpolation` argument `percentage` expects series/simple numeric, got const string",
            "`array.percentile_linear_interpolation` expects at most 2 argument(s), got 3",
            "`array.percentrank` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.percentrank` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.percentrank` argument `id` expects numeric array, got simple array<string>",
            "`array.percentrank` expects at least 2 argument(s), got 1",
            "`array.percentrank` argument `index` expects simple integer-compatible, got const string",
            "`array.percentrank` argument `index` expects simple integer-compatible, got series int",
            "`array.percentrank` expects at most 2 argument(s), got 3",
            "`array.covariance` argument `id1` expects numeric array, got simple array<UDT>",
            "`array.covariance` argument `id2` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.covariance` argument `id1` expects numeric array, got simple array<UDT>",
            "`array.covariance` argument `id2` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.covariance` argument `id1` expects numeric array, got simple array<string>",
            "`array.covariance` argument `id2` expects numeric array, got simple array<string>",
            "`array.covariance` expects at least 2 argument(s), got 1",
            "`array.covariance` argument `biased` expects bool-compatible, got series float",
            "`array.covariance` expects at most 3 argument(s), got 4",
            "`array.standardize` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.standardize` argument `id` expects numeric array, got simple array<string>",
            "`array.standardize` expects at most 1 argument(s), got 2",
            "`array.variance` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.variance` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.variance` argument `id` expects numeric array, got simple array<string>",
            "`array.variance` argument `biased` expects bool-compatible, got series float",
            "`array.variance` expects at most 2 argument(s), got 3",
            "`array.stdev` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.stdev` argument `id` expects numeric array, got simple array<UDT>",
            "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`",
            "`array.stdev` argument `id` expects numeric array, got simple array<string>",
            "`array.stdev` argument `biased` expects bool-compatible, got series float",
            "`array.stdev` expects at most 2 argument(s), got 3",
            "`array.sort_indices` requires a scalar-tree UDT array and a root int, float, or string `sort_field`",
            "`array.sort_indices` argument `sort_field` expects const int or string, got series string",
            "`array.sort_indices` argument `id` expects numeric/string array, got simple array<bool>",
            "`array.sort_indices` argument `order` expects const string, got series float",
            "`array.sort_indices` expects at most 2 argument(s), got 3",
            "`array.concat` expects at least 2 argument(s), got 1",
            "`array.concat` argument `id2` expects simple array<int>, got simple array<string>",
            "`array.concat` expects at most 2 argument(s), got 3",
            "`array.join` argument `separator` expects string-compatible, got series float",
            "`array.join` expects at most 2 argument(s), got 3",
            "`array.slice` argument `index_from` expects simple integer-compatible, got const string",
            "`array.slice` argument `index_to` expects simple integer-compatible, got const string",
            "`array.slice` expects at least 3 argument(s), got 2",
            "`array.slice` expects at most 3 argument(s), got 4",
            "`array.clear` expects at most 1 argument(s), got 2",
            "`array.reverse` expects at most 1 argument(s), got 2",
            "`array.pop` expects at most 1 argument(s), got 2",
            "`array.shift` expects at most 1 argument(s), got 2",
            "`array.remove` argument `index` expects simple integer-compatible, got const string",
            "`array.remove` expects at most 2 argument(s), got 3",
            "`array.push` argument `value` expects UDT `lib.First`, got `lib.Second`",
            "`array.push` expects at most 2 argument(s), got 3",
            "`array.unshift` argument `value` expects UDT `lib.First`, got `lib.Second`",
            "`array.unshift` expects at most 2 argument(s), got 3",
            "`array.insert` argument `index` expects simple integer-compatible, got const string",
            "`array.insert` argument `value` expects UDT `lib.First`, got `lib.Second`",
            "`array.insert` expects at most 3 argument(s), got 4",
            "`array.set` argument `index` expects simple integer-compatible, got const string",
            "`array.set` argument `value` expects UDT `lib.First`, got `lib.Second`",
            "`array.set` expects at most 3 argument(s), got 4",
            "`array.fill` argument `value` expects UDT `lib.First`, got `lib.Second`",
            "`array.fill` argument `index_from` expects simple integer-compatible, got const string",
            "`array.fill` argument `index_to` expects simple integer-compatible, got const string",
            "`array.fill` expects at most 4 argument(s), got 5",
            "`array.sort` requires a scalar-tree UDT array and a root int, float, or string `sort_field`",
            "`array.sort` argument `sort_field` expects const int or string, got series float",
            "`array.sort` argument `id` expects numeric/string array, got simple array<bool>",
            "`array.sort` argument `order` expects const string, got series float",
            "`array.sort` expects at most 2 argument(s), got 3",
        ],
    );
    assert_import_diagnostic_count_with_library(path, "user/udt_array_returns/1", library, 192);
}

#[test]
fn accepts_supported_imported_udt_history_non_scalar_typed_na_fixture() {
    assert_import_ok_fixture_with_library(
        "tests/fixtures/sema/supported_imported_udt_history_non_scalar_typed_na.pine",
        "user/non_scalar_udt/1",
        "tests/fixtures/libraries/import_non_scalar_udt_lib.pine",
    );
}

#[test]
fn accepts_supported_imported_udt_history_non_scalar_constructed_fixture() {
    assert_import_ok_fixture_with_library(
        "tests/fixtures/sema/supported_imported_udt_history_non_scalar_constructed.pine",
        "user/non_scalar_udt/1",
        "tests/fixtures/libraries/import_non_scalar_udt_lib.pine",
    );
}

#[test]
fn accepts_supported_imported_udt_method_param_non_scalar_fixture() {
    assert_import_ok_fixture_with_library(
        "tests/fixtures/sema/supported_imported_udt_method_param_non_scalar.pine",
        "user/non_scalar_udt/1",
        "tests/fixtures/libraries/import_non_scalar_udt_lib.pine",
    );
}

#[test]
fn accepts_supported_imported_udt_private_dependency_history_fixture() {
    assert_import_ok_fixture(
        "tests/fixtures/sema/supported_imported_udt_private_dependency_history.pine",
    );
}

#[test]
fn accepts_supported_imported_udt_array_new_fixture() {
    assert_import_ok_fixture("tests/fixtures/sema/supported_imported_udt_array_new.pine");
}

#[test]
fn accepts_supported_imported_udt_array_new_return_qualifier_fixture() {
    assert_import_ok_fixture(
        "tests/fixtures/sema/supported_imported_udt_array_new_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_imported_udt_array_new_return_qualifier_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_new_return_qualifier.pine",
        &[
            "cannot pass a different user-defined type array to function parameter `points`",
            "cannot pass a different user-defined type array to function parameter `points`",
        ],
    );
}

#[test]
fn accepts_supported_imported_udt_array_new_method_return_qualifier_fixture() {
    assert_import_ok_fixture(
        "tests/fixtures/sema/supported_imported_udt_array_new_method_return_qualifier.pine",
    );
}

#[test]
fn accepts_supported_imported_udt_array_sort_field_fixture() {
    assert_import_ok_fixture("tests/fixtures/sema/supported_imported_udt_array_sort_field.pine");
}

#[test]
fn reports_unsupported_imported_udt_array_sort_missing_field_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_sort_missing_field.pine",
        &[
            "`array.sort` requires a scalar-tree UDT array and a root int, float, or string `sort_field`",
        ],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_sort_unknown_field_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_sort_unknown_field.pine",
        &[
            "`array.sort` requires a scalar-tree UDT array and a root int, float, or string `sort_field`",
        ],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_sort_bool_field_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_sort_bool_field.pine",
        &[
            "`array.sort` requires a scalar-tree UDT array and a root int, float, or string `sort_field`",
        ],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_sort_dynamic_field_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_sort_dynamic_field.pine",
        &[
            "`array.sort` argument `sort_field` expects const int or string, got series string",
            "`array.sort` requires a scalar-tree UDT array and a root int, float, or string `sort_field`",
        ],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_sort_indices_missing_field_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_sort_indices_missing_field.pine",
        &[
            "`array.sort_indices` requires a scalar-tree UDT array and a root int, float, or string `sort_field`",
        ],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_sort_indices_unknown_field_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_sort_indices_unknown_field.pine",
        &[
            "`array.sort_indices` requires a scalar-tree UDT array and a root int, float, or string `sort_field`",
        ],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_sort_indices_bool_field_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_sort_indices_bool_field.pine",
        &[
            "`array.sort_indices` requires a scalar-tree UDT array and a root int, float, or string `sort_field`",
        ],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_sort_indices_dynamic_field_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_sort_indices_dynamic_field.pine",
        &[
            "`array.sort_indices` argument `sort_field` expects const int or string, got series string",
            "`array.sort_indices` requires a scalar-tree UDT array and a root int, float, or string `sort_field`",
        ],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_new_method_return_qualifier_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_new_method_return_qualifier.pine",
        &[
            "cannot pass a different user-defined type array to method parameter `points`",
            "cannot pass a different user-defined type array to method parameter `points`",
        ],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_new_non_scalar_fixture() {
    assert_import_diagnostic_messages_with_library(
        "tests/fixtures/sema/unsupported_imported_udt_array_new_non_scalar.pine",
        "user/non_scalar_udt/1",
        "tests/fixtures/libraries/import_non_scalar_udt_lib.pine",
        &["`array.new<lib.Marker>` requires a local or imported scalar-tree UDT"],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_from_non_scalar_fixture() {
    assert_import_diagnostic_messages_with_library(
        "tests/fixtures/sema/unsupported_imported_udt_array_from_non_scalar.pine",
        "user/non_scalar_udt/1",
        "tests/fixtures/libraries/import_non_scalar_udt_lib.pine",
        &["`array.from` expects supported scalar-tree UDT values"],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_decl_non_scalar_fixture() {
    assert_import_diagnostic_messages_with_library(
        "tests/fixtures/sema/unsupported_imported_udt_array_decl_non_scalar.pine",
        "user/non_scalar_udt/1",
        "tests/fixtures/libraries/import_non_scalar_udt_lib.pine",
        &[
            "typed declaration `array<lib.Marker>` does not support imported UDT arrays with non-scalar, unresolved, or recursive fields",
        ],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_alias_decl_non_scalar_fixture() {
    assert_import_diagnostic_messages_with_library(
        "tests/fixtures/sema/unsupported_imported_udt_array_alias_decl_non_scalar.pine",
        "user/non_scalar_udt/1",
        "tests/fixtures/libraries/import_non_scalar_udt_lib.pine",
        &[
            "typed declaration `array<lib.Marker>` does not support imported UDT arrays with non-scalar, unresolved, or recursive fields",
        ],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_varip_decl_non_scalar_fixture() {
    assert_import_diagnostic_messages_with_library(
        "tests/fixtures/sema/unsupported_imported_udt_array_varip_decl_non_scalar.pine",
        "user/non_scalar_udt/1",
        "tests/fixtures/libraries/import_non_scalar_udt_lib.pine",
        &[
            "typed declaration `array<lib.Marker>` does not support imported UDT arrays with non-scalar, unresolved, or recursive fields",
        ],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_varip_alias_decl_non_scalar_fixture() {
    assert_import_diagnostic_messages_with_library(
        "tests/fixtures/sema/unsupported_imported_udt_array_varip_alias_decl_non_scalar.pine",
        "user/non_scalar_udt/1",
        "tests/fixtures/libraries/import_non_scalar_udt_lib.pine",
        &[
            "typed declaration `array<lib.Marker>` does not support imported UDT arrays with non-scalar, unresolved, or recursive fields",
        ],
    );
}

#[test]
fn accepts_supported_imported_udt_array_typed_udf_params_fixture() {
    assert_import_ok_fixture(
        "tests/fixtures/sema/supported_imported_udt_array_typed_udf_params.pine",
    );
}

#[test]
fn accepts_supported_imported_udt_array_from_return_qualifier_fixture() {
    assert_import_ok_fixture(
        "tests/fixtures/sema/supported_imported_udt_array_from_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_imported_udt_array_from_return_qualifier_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_from_return_qualifier.pine",
        &[
            "cannot pass a different user-defined type array to function parameter `points`",
            "cannot pass a different user-defined type array to function parameter `points`",
        ],
    );
}

#[test]
fn accepts_supported_imported_udt_array_from_method_return_qualifier_fixture() {
    assert_import_ok_fixture(
        "tests/fixtures/sema/supported_imported_udt_array_from_method_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_imported_udt_array_from_method_return_qualifier_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_from_method_return_qualifier.pine",
        &[
            "cannot pass a different user-defined type array to method parameter `points`",
            "cannot pass a different user-defined type array to method parameter `points`",
        ],
    );
}

#[test]
fn accepts_supported_imported_udt_array_same_as_arg_method_return_qualifier_fixture() {
    assert_import_ok_fixture(
        "tests/fixtures/sema/supported_imported_udt_array_same_as_arg_method_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_imported_udt_array_same_as_arg_method_return_qualifier_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_same_as_arg_method_return_qualifier.pine",
        &[
            "cannot pass a different user-defined type array to method parameter `points`",
            "cannot pass a different user-defined type array to method parameter `points`",
            "cannot pass a different user-defined type array to method parameter `points`",
            "cannot pass a different user-defined type array to method parameter `points`",
        ],
    );
}

#[test]
fn accepts_supported_imported_udt_array_element_method_return_qualifier_fixture() {
    assert_import_ok_fixture(
        "tests/fixtures/sema/supported_imported_udt_array_element_method_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_imported_udt_array_element_method_return_qualifier_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_element_method_return_qualifier.pine",
        &[
            "cannot pass argument to method parameter `other` of user-defined type `lib.Wrapper`",
            "cannot pass argument to method parameter `other` of user-defined type `lib.Wrapper`",
            "cannot pass argument to method parameter `other` of user-defined type `lib.Wrapper`",
            "cannot pass argument to method parameter `other` of user-defined type `lib.Wrapper`",
            "cannot pass argument to method parameter `other` of user-defined type `lib.Wrapper`",
            "cannot pass argument to method parameter `other` of user-defined type `lib.Wrapper`",
            "cannot pass receiver `Wrapper` to imported method `lib.sameWrapper`",
        ],
    );
}

#[test]
fn accepts_supported_imported_udt_array_typed_method_params_fixture() {
    assert_import_ok_fixture(
        "tests/fixtures/sema/supported_imported_udt_array_typed_method_params.pine",
    );
}

#[test]
fn reports_unsupported_imported_udt_assignment_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_assignment_identity.pine",
        &["cannot assign a different user-defined type to `p`"],
    );
}

#[test]
fn reports_unsupported_imported_udt_typed_decl_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_typed_decl_identity.pine",
        &["cannot assign a different user-defined type to `p`"],
    );
}

#[test]
fn reports_unsupported_imported_udt_var_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_var_identity.pine",
        &["cannot assign a different user-defined type to `p`"],
    );
}

#[test]
fn reports_unsupported_imported_udt_varip_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_varip_identity.pine",
        &["cannot assign a different user-defined type to `p`"],
    );
}

#[test]
fn reports_unsupported_imported_udt_ternary_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_ternary_identity.pine",
        &["ternary user-defined type branches must resolve to the same UDT identity"],
    );
}

#[test]
fn reports_unsupported_imported_udt_if_expression_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_if_expression_identity.pine",
        &["if user-defined type branches must resolve to the same UDT identity"],
    );
}

#[test]
fn reports_unsupported_imported_udt_while_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_while_identity.pine",
        &["cannot assign a different user-defined type to `p`"],
    );
}

#[test]
fn reports_unsupported_imported_udt_for_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_for_identity.pine",
        &["cannot assign a different user-defined type to `p`"],
    );
}

#[test]
fn reports_unsupported_imported_udt_udf_passthrough_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_udf_passthrough_identity.pine",
        &["cannot assign a different user-defined type to `p`"],
    );
}

#[test]
fn reports_unsupported_imported_udt_udf_nested_passthrough_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_udf_nested_passthrough_identity.pine",
        &["cannot assign a different user-defined type to `p`"],
    );
}

#[test]
fn reports_unsupported_imported_udt_udf_constructor_return_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_udf_constructor_return_identity.pine",
        &["cannot assign a different user-defined type to `p`"],
    );
}

#[test]
fn reports_unsupported_imported_udt_udf_nested_constructor_return_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_udf_nested_constructor_return_identity.pine",
        &["cannot assign a different user-defined type to `p`"],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_typed_udf_param_mismatch_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_typed_udf_param_mismatch.pine",
        &["cannot pass a different user-defined type array to function parameter `points`"],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_typed_method_param_mismatch_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_typed_method_param_mismatch.pine",
        &["cannot pass a different user-defined type array to method parameter `points`"],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_push_mixed_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_push_mixed_identity.pine",
        &["`array.push` argument `value` expects UDT `lib.Point`, got `Point`"],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_push_method_mixed_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_push_method_mixed_identity.pine",
        &["`array.push` argument `value` expects UDT `lib.Point`, got `Point`"],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_push_local_target_mixed_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_push_local_target_mixed_identity.pine",
        &["`array.push` argument `value` expects UDT `Point`, got `lib.Point`"],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_push_local_target_method_mixed_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_push_local_target_method_mixed_identity.pine",
        &["`array.push` argument `value` expects UDT `Point`, got `lib.Point`"],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_set_mixed_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_set_mixed_identity.pine",
        &["`array.set` argument `value` expects UDT `lib.Point`, got `Point`"],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_set_method_mixed_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_set_method_mixed_identity.pine",
        &["`array.set` argument `value` expects UDT `lib.Point`, got `Point`"],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_set_local_target_mixed_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_set_local_target_mixed_identity.pine",
        &["`array.set` argument `value` expects UDT `Point`, got `lib.Point`"],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_set_local_target_method_mixed_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_set_local_target_method_mixed_identity.pine",
        &["`array.set` argument `value` expects UDT `Point`, got `lib.Point`"],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_insert_mixed_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_insert_mixed_identity.pine",
        &["`array.insert` argument `value` expects UDT `lib.Point`, got `Point`"],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_insert_method_mixed_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_insert_method_mixed_identity.pine",
        &["`array.insert` argument `value` expects UDT `lib.Point`, got `Point`"],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_insert_local_target_mixed_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_insert_local_target_mixed_identity.pine",
        &["`array.insert` argument `value` expects UDT `Point`, got `lib.Point`"],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_insert_local_target_method_mixed_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_insert_local_target_method_mixed_identity.pine",
        &["`array.insert` argument `value` expects UDT `Point`, got `lib.Point`"],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_unshift_mixed_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_unshift_mixed_identity.pine",
        &["`array.unshift` argument `value` expects UDT `lib.Point`, got `Point`"],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_unshift_method_mixed_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_unshift_method_mixed_identity.pine",
        &["`array.unshift` argument `value` expects UDT `lib.Point`, got `Point`"],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_unshift_local_target_mixed_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_unshift_local_target_mixed_identity.pine",
        &["`array.unshift` argument `value` expects UDT `Point`, got `lib.Point`"],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_unshift_local_target_method_mixed_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_unshift_local_target_method_mixed_identity.pine",
        &["`array.unshift` argument `value` expects UDT `Point`, got `lib.Point`"],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_fill_mixed_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_fill_mixed_identity.pine",
        &["`array.fill` argument `value` expects UDT `lib.Point`, got `Point`"],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_fill_method_mixed_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_fill_method_mixed_identity.pine",
        &["`array.fill` argument `value` expects UDT `lib.Point`, got `Point`"],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_fill_local_target_mixed_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_fill_local_target_mixed_identity.pine",
        &["`array.fill` argument `value` expects UDT `Point`, got `lib.Point`"],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_fill_local_target_method_mixed_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_fill_local_target_method_mixed_identity.pine",
        &["`array.fill` argument `value` expects UDT `Point`, got `lib.Point`"],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_includes_mixed_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_includes_mixed_identity.pine",
        &["`array.includes` argument `value` expects UDT `lib.Point`, got `Point`"],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_includes_method_mixed_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_includes_method_mixed_identity.pine",
        &["`array.includes` argument `value` expects UDT `lib.Point`, got `Point`"],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_includes_local_target_mixed_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_includes_local_target_mixed_identity.pine",
        &["`array.includes` argument `value` expects UDT `Point`, got `lib.Point`"],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_includes_local_target_method_mixed_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_includes_local_target_method_mixed_identity.pine",
        &["`array.includes` argument `value` expects UDT `Point`, got `lib.Point`"],
    );
}

#[test]
fn accepts_supported_imported_udt_array_includes_series_bool_return_qualifier_fixture() {
    assert_import_ok_fixture(
        "tests/fixtures/sema/supported_imported_udt_array_includes_series_bool_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_imported_udt_array_includes_const_bool_return_qualifier_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_includes_const_bool_return_qualifier.pine",
        &[
            "`input.bool` argument `defval` expects const bool, got series bool",
            "`input.bool` argument `defval` expects const bool, got series bool",
        ],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_indexof_mixed_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_indexof_mixed_identity.pine",
        &["`array.indexof` argument `value` expects UDT `lib.Point`, got `Point`"],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_indexof_method_mixed_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_indexof_method_mixed_identity.pine",
        &["`array.indexof` argument `value` expects UDT `lib.Point`, got `Point`"],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_indexof_local_target_mixed_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_indexof_local_target_mixed_identity.pine",
        &["`array.indexof` argument `value` expects UDT `Point`, got `lib.Point`"],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_indexof_local_target_method_mixed_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_indexof_local_target_method_mixed_identity.pine",
        &["`array.indexof` argument `value` expects UDT `Point`, got `lib.Point`"],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_lastindexof_mixed_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_lastindexof_mixed_identity.pine",
        &["`array.lastindexof` argument `value` expects UDT `lib.Point`, got `Point`"],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_lastindexof_method_mixed_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_lastindexof_method_mixed_identity.pine",
        &["`array.lastindexof` argument `value` expects UDT `lib.Point`, got `Point`"],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_lastindexof_local_target_mixed_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_lastindexof_local_target_mixed_identity.pine",
        &["`array.lastindexof` argument `value` expects UDT `Point`, got `lib.Point`"],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_lastindexof_local_target_method_mixed_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_lastindexof_local_target_method_mixed_identity.pine",
        &["`array.lastindexof` argument `value` expects UDT `Point`, got `lib.Point`"],
    );
}

#[test]
fn accepts_supported_imported_udt_array_indexof_simple_return_qualifier_fixture() {
    assert_import_ok_fixture(
        "tests/fixtures/sema/supported_imported_udt_array_indexof_simple_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_imported_udt_array_indexof_const_input_return_qualifier_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_indexof_const_input_return_qualifier.pine",
        &[
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`plot` argument `show_last` expects const/input int, got simple int",
        ],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_concat_mixed_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_concat_mixed_identity.pine",
        &["`array.concat` argument `id2` expects UDT array `lib.Point`, got `Point`"],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_concat_method_mixed_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_concat_method_mixed_identity.pine",
        &["`array.concat` argument `id2` expects UDT array `lib.Point`, got `Point`"],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_concat_local_target_mixed_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_concat_local_target_mixed_identity.pine",
        &["`array.concat` argument `id2` expects UDT array `Point`, got `lib.Point`"],
    );
}

#[test]
fn reports_unsupported_imported_udt_array_concat_local_target_method_mixed_identity_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_udt_array_concat_local_target_method_mixed_identity.pine",
        &["`array.concat` argument `id2` expects UDT array `Point`, got `lib.Point`"],
    );
}

#[test]
fn reports_unsupported_imported_method_qualified_receiver_fixture() {
    assert_import_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_imported_method_qualified_receiver.pine",
        "E_METHOD_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_imported_method_qualified_receiver_order_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_imported_method_qualified_receiver_order.pine",
        &["cannot pass const int as receiver to imported method `lib.shift`"],
    );
}

#[test]
fn reports_unsupported_imported_method_field_mutation_fixture() {
    assert_import_diagnostic_messages_with_library(
        "tests/fixtures/sema/unsupported_imported_method_field_mutation.pine",
        "user/udt_side_effect/1",
        "tests/fixtures/libraries/import_udt_method_side_effect_lib.pine",
        &[
            "`function_side_effect` is not supported: mutating user-defined type fields inside methods is not supported",
        ],
    );
    assert_import_diagnostic_count_with_library(
        "tests/fixtures/sema/unsupported_imported_method_field_mutation.pine",
        "user/udt_side_effect/1",
        "tests/fixtures/libraries/import_udt_method_side_effect_lib.pine",
        2,
    );
}

#[test]
fn reports_unsupported_library_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_library.pine",
        "library",
        "library declarations",
    );
}

#[test]
fn reports_unsupported_export_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_export.pine",
        "export",
        "export declarations",
    );
}

#[test]
fn reports_unsupported_user_type_field_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/unsupported_user_type.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| { diagnostic.code == "E_UDT_FIELD_TYPE" })
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn reports_unsupported_user_type_forward_field_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_user_type_forward_field.pine",
        "E_UDT_FIELD_TYPE",
    );
}

#[test]
fn reports_unsupported_user_type_duplicate_field_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_user_type_duplicate_field.pine",
        "E_UDT_FIELD_DUPLICATE",
    );
}

#[test]
fn reports_unsupported_user_type_duplicate_decl_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_user_type_duplicate_decl.pine",
        "E_UDT_DUPLICATE",
    );
}

#[test]
fn reports_unsupported_user_type_decl_location_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_user_type_decl_location.pine",
        "E_UDT_DECL_LOCATION",
    );
}

#[test]
fn reports_unsupported_user_type_constructor_arg_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_user_type_constructor_arg.pine",
        "E_UDT_CONSTRUCTOR_ARG",
    );
}

#[test]
fn reports_unsupported_user_type_constructor_duplicate_arg_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_user_type_constructor_duplicate_arg.pine",
        "E_UDT_CONSTRUCTOR_ARG",
    );
}

#[test]
fn reports_unsupported_user_type_constructor_pos_after_named_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_user_type_constructor_pos_after_named.pine",
        "E_UDT_CONSTRUCTOR_ARG",
    );
}

#[test]
fn reports_unsupported_user_type_constructor_too_many_args_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_user_type_constructor_too_many_args.pine",
        "E_UDT_CONSTRUCTOR_ARG",
    );
}

#[test]
fn reports_unsupported_user_type_constructor_missing_arg_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_user_type_constructor_missing_arg.pine",
        "E_UDT_CONSTRUCTOR_ARG",
    );
}

#[test]
fn reports_unsupported_user_type_constructor_field_type_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_user_type_constructor_field_type.pine",
        &["cannot assign const bool to field `x` of type float"],
    );
}

#[test]
fn reports_unsupported_user_type_unknown_field_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_user_type_unknown_field.pine",
        "E_UDT_UNKNOWN_FIELD",
    );
}

#[test]
fn reports_unsupported_user_type_varip_non_constructor_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_user_type_varip.pine",
        "varip",
        "UDT varip supports only explicit scalar-tree declarations",
    );
}

#[test]
fn reports_unsupported_user_type_varip_assign_identity_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_user_type_varip_assign_identity.pine",
        &["cannot assign a different user-defined type to `p`"],
    );
}

#[test]
fn reports_unsupported_user_type_assign_identity_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_user_type_assign_identity.pine",
        &["cannot assign a different user-defined type to `p`"],
    );
}

#[test]
fn accepts_supported_user_type_typed_udf_params_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_user_type_typed_udf_params.pine");
}

#[test]
fn reports_unsupported_user_type_initializer_identity_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_user_type_initializer_identity.pine",
        &["cannot assign a different user-defined type to `p`"],
    );
}

#[test]
fn reports_unsupported_user_type_nested_field_assign_identity_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_user_type_nested_field_assign_identity.pine",
        &["cannot assign series UDT to `w.inner` of user-defined type `Point`"],
    );
}

#[test]
fn reports_unsupported_user_type_nested_constructor_identity_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_user_type_nested_constructor_identity.pine",
        &["cannot assign series UDT to field `inner` of type UDT"],
    );
}

#[test]
fn reports_unsupported_user_type_ternary_branch_identity_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_user_type_ternary_branch_identity.pine",
        &["ternary user-defined type branches must resolve to the same UDT identity"],
    );
}

#[test]
fn reports_unsupported_user_type_switch_branch_identity_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_user_type_switch_branch_identity.pine",
        &["switch user-defined type arms must resolve to the same UDT identity"],
    );
}

#[test]
fn reports_unsupported_user_type_final_if_branch_identity_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_user_type_final_if_branch_identity.pine",
        &["if user-defined type branches must resolve to the same local UDT"],
    );
}

#[test]
fn reports_unsupported_user_type_field_mutation_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_user_type_field_mutation.pine",
        "function_side_effect",
        "mutating fields on global user-defined type values inside user-defined functions",
    );
}

#[test]
fn reports_unsupported_user_type_parameter_field_mutation_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_user_type_parameter_field_mutation.pine",
        "function_side_effect",
        "mutating user-defined type parameter fields inside user-defined functions",
    );
}

#[test]
fn reports_unsupported_user_method_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/unsupported_user_method.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_METHOD_RECEIVER_TYPE")
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn reports_unsupported_user_method_decl_location_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_user_method_decl_location.pine",
        "E_METHOD_DECL_LOCATION",
    );
}

#[test]
fn reports_unsupported_user_method_side_effect_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_user_method_side_effect.pine",
        "function_side_effect",
        "inside user-defined functions",
    );
}

#[test]
fn reports_unsupported_user_method_side_effect_arg_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_user_method_side_effect_arg.pine",
        "function_side_effect",
        "side-effecting calls cannot be passed as user-defined method arguments",
    );
}

#[test]
fn reports_unsupported_user_method_field_mutation_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_user_method_field_mutation.pine",
        "function_side_effect",
        "mutating user-defined type fields inside methods",
    );
}

#[test]
fn reports_unsupported_user_method_arg_type_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_user_method_arg_type.pine",
        "E_METHOD_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_user_method_missing_arg_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_user_method_missing_arg.pine",
        "E_FUNCTION_ARITY",
    );
}

#[test]
fn reports_unsupported_user_method_too_many_args_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_user_method_too_many_args.pine",
        "E_FUNCTION_ARITY",
    );
}

#[test]
fn reports_unsupported_user_method_unknown_named_arg_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_user_method_unknown_named_arg.pine",
        "E_FUNCTION_ARG_NAME",
    );
}

#[test]
fn reports_unsupported_user_method_duplicate_named_arg_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_user_method_duplicate_named_arg.pine",
        "E_FUNCTION_ARG_DUPLICATE",
    );
}

#[test]
fn reports_unsupported_user_method_pos_after_named_arg_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_user_method_pos_after_named_arg.pine",
        "E_FUNCTION_ARG_ORDER",
    );
}

#[test]
fn reports_unsupported_user_method_duplicate_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_user_method_duplicate.pine",
        "E_METHOD_DUPLICATE",
    );
}

#[test]
fn reports_unsupported_user_method_duplicate_param_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_user_method_duplicate_param.pine",
        "E_METHOD_PARAM",
    );
}

#[test]
fn reports_unsupported_user_method_receiver_duplicate_param_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_user_method_receiver_duplicate_param.pine",
        "E_METHOD_PARAM",
    );
}

#[test]
fn reports_unsupported_user_method_missing_receiver_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_user_method_missing_receiver.pine",
        "E_METHOD_PARAM",
    );
}

#[test]
fn reports_unsupported_user_method_param_type_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_user_method_param_type.pine",
        "E_METHOD_PARAM",
    );
}

#[test]
fn accepts_supported_typed_method_params_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_typed_method_params.pine");
}

#[test]
fn reports_unsupported_chart_point_typed_method_param_mismatch_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_chart_point_typed_method_param_mismatch.pine",
        &["cannot pass series float to method parameter `point` of type chart.point"],
    );
}

#[test]
fn reports_unsupported_array_typed_method_param_mismatch_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_array_typed_method_param_mismatch.pine",
        &["cannot pass simple array<float> to method parameter `values` of type array<int>"],
    );
}

#[test]
fn reports_unsupported_object_array_typed_method_param_mismatch_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_object_array_typed_method_param_mismatch.pine",
        &["cannot pass simple array<label> to method parameter `values` of type array<line>"],
    );
}

#[test]
fn reports_unsupported_user_method_recursive_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_user_method_recursive.pine",
        "E_RECURSIVE_METHOD",
    );
}

#[test]
fn reports_unsupported_user_method_call_depth_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_user_method_call_depth.pine",
        "E_FUNCTION_CALL_DEPTH",
    );
}

#[test]
fn reports_unsupported_user_method_unknown_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_user_method_unknown.pine",
        "E_UNKNOWN_METHOD",
    );
}

#[test]
fn reports_non_array_method_fixture_as_receiver_diagnostic() {
    let path = workspace_fixture("tests/fixtures/sema/unsupported_non_array_method.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_METHOD_RECEIVER_TYPE"),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(analysis.hir.is_none());
}

#[test]
fn reports_unsupported_alert_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_alert.pine",
        "alert_frequency",
        "alert.freq_all, alert.freq_once_per_bar, and alert.freq_once_per_bar_close",
    );
}

#[test]
fn reports_unsupported_alert_dynamic_frequency_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_alert_dynamic_frequency.pine",
        "alert_frequency",
        "alert.freq_all, alert.freq_once_per_bar, and alert.freq_once_per_bar_close",
    );
}

#[test]
fn reports_unsupported_alert_unknown_frequency_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_alert_unknown_frequency.pine",
        "alert_frequency",
        "alert.freq_all, alert.freq_once_per_bar, and alert.freq_once_per_bar_close",
    );
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_alert_named_const_frequency.pine",
        "alert_frequency",
        "alert.freq_all, alert.freq_once_per_bar, and alert.freq_once_per_bar_close",
    );
}

#[test]
fn accepts_supported_alert_named_const_frequency_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_alert_named_const_frequency.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(analysis.hir.is_some());
}

#[test]
fn reports_unsupported_alert_placeholder_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_alert_placeholder.pine",
        "alert_placeholders",
        "alert placeholder `{{close}}`",
    );
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_alert_named_const_placeholder.pine",
        "alert_placeholders",
        "alert placeholder `{{close}}`",
    );
}

#[test]
fn reports_unsupported_alertcondition_placeholder_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_alertcondition_placeholder.pine",
        "alert_placeholders",
        "alert placeholder `{{timenow}}`",
    );
}

#[test]
fn reports_unsupported_alertcondition_title_placeholder_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_alertcondition_title_placeholder.pine",
        "alert_placeholders",
        "alert placeholder `{{close}}`",
    );
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_alertcondition_named_const_title_placeholder.pine",
        "alert_placeholders",
        "alert placeholder `{{close}}`",
    );
}

#[test]
fn accepts_supported_alertcondition_named_const_placeholder_fixture() {
    let path = workspace_fixture(
        "tests/fixtures/sema/supported_alertcondition_named_const_placeholder.pine",
    );
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(analysis.hir.is_some());
}

#[test]
fn reports_unsupported_alertcondition_unknown_placeholder_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_alertcondition_unknown_placeholder.pine",
        "alert_placeholders",
        "alert placeholder `{{unknown}}`",
    );
}

#[test]
fn reports_unsupported_alertcondition_plot_placeholder_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_alertcondition_plot_placeholder.pine",
        "alert_placeholders",
        "alert placeholder `{{plot_0}}`",
    );
}

#[test]
fn reports_unsupported_log_fixture() {
    assert_unsupported_features_fixture(
        "tests/fixtures/sema/unsupported_log.pine",
        &[
            ("log.info", "Pine Logs output is not implemented"),
            ("log.warning", "Pine Logs output is not implemented"),
            ("log.error", "Pine Logs output is not implemented"),
        ],
    );
}

#[test]
fn reports_unknown_log_function_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unknown_log_function.pine",
        &["unknown function `log.debug`"],
    );
}

#[test]
fn reports_unsupported_ticker_constructors_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_ticker_constructors.pine",
        "E_CALL_ARITY",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ticker_constructors.pine",
        &[
            "ticker.new",
            "ticker.modify",
            "ticker.inherit",
            "ticker.renko",
            "ticker.linebreak",
            "ticker.kagi",
            "ticker.pointfigure",
        ],
    );
}

#[test]
fn accepts_supported_ticker_na_simple_string_params_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ticker_na_simple_string_params.pine");
}

#[test]
fn accepts_supported_ticker_simple_string_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_ticker_simple_string_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_ticker_const_string_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ticker_const_string_return_qualifier.pine",
        &[
            "`timestamp` argument `dateString` expects const string, got simple string",
            "`timestamp` argument `dateString` expects const string, got simple string",
            "`timestamp` argument `dateString` expects const string, got simple string",
            "`timestamp` argument `dateString` expects const string, got simple string",
            "`timestamp` argument `dateString` expects const string, got simple string",
            "`timestamp` argument `dateString` expects const string, got simple string",
            "`timestamp` argument `dateString` expects const string, got simple string",
            "`timestamp` argument `dateString` expects const string, got simple string",
            "`timestamp` argument `dateString` expects const string, got simple string",
        ],
    );
}

#[test]
fn reports_unsupported_ticker_series_simple_string_params_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ticker_series_simple_string_params.pine",
        &[
            "`ticker.new` argument `prefix` expects simple string, got series string",
            "`ticker.new` argument `ticker` expects simple string, got series string",
            "`ticker.new` argument `session` expects simple string, got series string",
            "`ticker.modify` argument `tickerid` expects simple string, got series string",
            "`ticker.standard` argument `symbol` expects simple string, got series string",
            "`ticker.heikinashi` argument `tickerid` expects simple string, got series string",
            "`ticker.inherit` argument `symbol` expects simple string, got series string",
            "`ticker.linebreak` argument `tickerid` expects simple string, got series string",
            "`ticker.kagi` argument `style` expects simple string, got series string",
            "`ticker.pointfigure` argument `source` expects simple string, got series string",
            "`ticker.pointfigure` argument `style` expects simple string, got series string",
            "`ticker.renko` argument `style` expects simple string, got series string",
        ],
    );
}

#[test]
fn accepts_supported_ticker_na_simple_int_params_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ticker_na_simple_int_params.pine");
}

#[test]
fn reports_unsupported_ticker_series_simple_int_params_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ticker_series_simple_int_params.pine",
        &[
            "`ticker.linebreak` argument `number_of_lines` expects simple integer-compatible, got series int",
            "`ticker.pointfigure` argument `reversal` expects simple integer-compatible, got series int",
        ],
    );
}

#[test]
fn accepts_supported_ticker_na_simple_numeric_params_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_ticker_na_simple_numeric_params.pine");
}

#[test]
fn reports_unsupported_ticker_series_simple_numeric_params_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_ticker_series_simple_numeric_params.pine",
        &[
            "`ticker.kagi` argument `param` expects simple numeric-compatible, got series float",
            "`ticker.pointfigure` argument `param` expects simple numeric-compatible, got series float",
            "`ticker.renko` argument `param` expects simple numeric-compatible, got series float",
        ],
    );
}

#[test]
fn reports_unsupported_map_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_map.pine",
        "E_CALL_ARG_TYPE",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_map.pine",
        &["`map.put` argument `id` expects map, got const na"],
    );
}

#[test]
fn reports_unsupported_map_new_template_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_map_new_template.pine",
        "map.new<line,float>",
        "map.new currently supports only",
    );
}

#[test]
fn reports_unsupported_map_new_dotted_template_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_map_new_dotted_template.pine",
        "map.new<chart.point,chart.point>",
        "map.new currently supports only",
    );
}

#[test]
fn accepts_supported_map_new_size_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_map_new_size.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "map.*"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_map_size_simple_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_map_size_simple_return_qualifier.pine");
}

#[test]
fn reports_unsupported_map_size_const_input_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_map_size_const_input_return_qualifier.pine",
        &[
            "`plot` argument `show_last` expects const/input int, got simple int",
            "`plot` argument `show_last` expects const/input int, got simple int",
        ],
    );
}

#[test]
fn accepts_supported_map_operation_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_map_operation_return_qualifier.pine");
}

#[test]
fn reports_unsupported_map_operation_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_map_operation_return_qualifier.pine",
        &[
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`input.bool` argument `defval` expects const bool, got series bool",
            "`input.bool` argument `defval` expects const bool, got series bool",
            "`matrix.add_row` argument `array_id` expects simple array<float>, got simple array<string>",
            "`matrix.add_row` argument `array_id` expects simple array<float>, got simple array<string>",
            "`matrix.add_col` argument `array_id` expects simple array<int>, got simple array<float>",
            "`matrix.add_col` argument `array_id` expects simple array<int>, got simple array<float>",
        ],
    );
}

#[test]
fn accepts_supported_map_put_get_contains_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_map_put_get_contains.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "map.*"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_map_clear_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_map_clear.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "map.*"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_map_remove_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_map_remove.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "map.*"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_map_copy_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_map_copy.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "map.*"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_map_methods_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_map_methods.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "map.*"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_map_keys_values_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_map_keys_values.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "map.*"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_map_for_in_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_map_for_in.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "for"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "map.*"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_map_put_all_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_map_put_all.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "map.*"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_map_history_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_map_history.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "map.*"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_map_varip_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_map_varip.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "varip"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_map_udf_read_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_map_udf_read.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "map.*"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_map_typed_decl_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_map_typed_decl.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "map.*"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_map_control_flow_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_map_control_flow.pine");
}

#[test]
fn reports_unsupported_map_control_flow_template_fixture() {
    let path = "tests/fixtures/sema/unsupported_map_control_flow_template.pine";
    assert_diagnostic_messages(
        path,
        &[
            "ternary map branches must resolve to the same map template",
            "if map branches must resolve to the same map template",
            "switch map arms must resolve to the same map template",
        ],
    );
    assert_diagnostic_count(path, 3);
}

#[test]
fn accepts_supported_map_udf_method_returns_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_map_udf_method_returns.pine");
}

#[test]
fn reports_unsupported_map_udf_method_return_templates_fixture() {
    let path = "tests/fixtures/sema/unsupported_map_udf_method_return_templates.pine";
    assert_diagnostic_messages(
        path,
        &[
            "ternary map branches must resolve to the same map template",
            "if map branches must resolve to the same map template",
            "cannot assign a different map template to `wrong_typed`",
            "`map.put_all` source map template int/string does not match target string/float",
        ],
    );
    assert_diagnostic_count(path, 4);
}

#[test]
fn reports_unsupported_map_get_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_map_get.pine",
        "E_CALL_ARG_TYPE",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_map_get.pine",
        &["`map.get` argument `id` expects map, got const na"],
    );
}

#[test]
fn reports_unsupported_map_contains_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_map_contains.pine",
        "E_CALL_ARG_TYPE",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_map_contains.pine",
        &["`map.contains` argument `id` expects map, got const na"],
    );
}

#[test]
fn reports_unsupported_map_put_key_type_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_map_put_key_type.pine",
        "E_CALL_ARG_TYPE",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_map_put_key_type.pine",
        &["`map.put` argument `key` expects string-compatible, got const int"],
    );
}

#[test]
fn reports_unsupported_map_put_value_type_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_map_put_value_type.pine",
        "E_CALL_ARG_TYPE",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_map_put_value_type.pine",
        &["`map.put` argument `value` expects numeric-compatible, got const string"],
    );
}

#[test]
fn reports_unsupported_map_get_key_type_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_map_get_key_type.pine",
        "E_CALL_ARG_TYPE",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_map_get_key_type.pine",
        &["`map.get` argument `key` expects string-compatible, got const int"],
    );
}

#[test]
fn reports_unsupported_map_remove_key_type_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_map_remove_key_type.pine",
        "E_CALL_ARG_TYPE",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_map_remove_key_type.pine",
        &["`map.remove` argument `key` expects string-compatible, got const int"],
    );
}

#[test]
fn reports_unsupported_map_assign_template_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_map_assign_template.pine",
        "E_MAP_ASSIGN_TYPE",
    );
}

#[test]
fn reports_unsupported_map_put_udf_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_map_put_udf.pine",
        "function_side_effect",
        "collection mutation via `map.put`",
    );
}

#[test]
fn reports_unsupported_map_put_method_udf_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_map_put_method_udf.pine",
        "function_side_effect",
        "collection mutation via `map.put`",
    );
}

#[test]
fn reports_unsupported_map_clear_udf_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_map_clear_udf.pine",
        "function_side_effect",
        "collection mutation via `map.clear`",
    );
}

#[test]
fn reports_unsupported_map_remove_udf_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_map_remove_udf.pine",
        "function_side_effect",
        "collection mutation via `map.remove`",
    );
}

#[test]
fn reports_unsupported_map_size_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_map_size.pine",
        "E_CALL_ARG_TYPE",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_map_size.pine",
        &["`map.size` argument `id` expects map, got const na"],
    );
}

#[test]
fn reports_unsupported_map_remove_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_map_remove.pine",
        "E_CALL_ARG_TYPE",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_map_remove.pine",
        &["`map.remove` argument `id` expects map, got const na"],
    );
}

#[test]
fn reports_unsupported_map_clear_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_map_clear.pine",
        "E_CALL_ARG_TYPE",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_map_clear.pine",
        &["`map.clear` argument `id` expects map, got const na"],
    );
}

#[test]
fn reports_unsupported_map_copy_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_map_copy.pine",
        "E_CALL_ARG_TYPE",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_map_copy.pine",
        &["`map.copy` argument `id` expects map, got series float"],
    );
}

#[test]
fn reports_unsupported_map_keys_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_map_keys.pine",
        "E_CALL_ARG_TYPE",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_map_keys.pine",
        &["`map.keys` argument `id` expects map, got series float"],
    );
}

#[test]
fn reports_unsupported_map_values_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_map_values.pine",
        "E_CALL_ARG_TYPE",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_map_values.pine",
        &["`map.values` argument `id` expects map, got series float"],
    );
}

#[test]
fn reports_unsupported_map_put_all_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_map_put_all.pine",
        "E_CALL_ARG_TYPE",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_map_put_all.pine",
        &["`map.put_all` argument `source` expects map, got series float"],
    );
}

#[test]
fn reports_unsupported_map_put_all_template_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_map_put_all_template.pine",
        "E_CALL_ARG_TYPE",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_map_put_all_template.pine",
        &["`map.put_all` source map template string/int does not match target string/float"],
    );
}

#[test]
fn reports_unsupported_map_put_all_udf_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_map_put_all_udf.pine",
        "function_side_effect",
        "collection mutation via `map.put_all` is not supported inside user-defined functions",
    );
}

#[test]
fn reports_unsupported_map_put_all_method_udf_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_map_put_all_method_udf.pine",
        "function_side_effect",
        "collection mutation via `map.put_all` is not supported inside user-defined functions",
    );
}

#[test]
fn reports_unsupported_matrix_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix.pine",
        "matrix.concat",
        "id2",
        "simple matrix<float>",
        "simple matrix<int>",
    );
}

#[test]
fn accepts_supported_matrix_concat_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_matrix_concat.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "matrix.concat"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn reports_unsupported_matrix_concat_method_template_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_concat_method_template.pine",
        "matrix.concat",
        "id2",
        "simple matrix<float>",
        "simple matrix<int>",
    );
}

#[test]
fn reports_unsupported_matrix_concat_non_matrix_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_matrix_concat_non_matrix.pine",
        &[
            "`matrix.concat` argument `id1` expects matrix, got const na",
            "`matrix.concat` argument `id2` expects matrix, got const na",
        ],
    );
}

#[test]
fn reports_unsupported_matrix_concat_method_receiver_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_concat_method_receiver.pine",
        "E_METHOD_RECEIVER_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_concat_udf_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_matrix_concat_udf.pine",
        &[
            "`function_side_effect` is not supported: collection mutation via `matrix.concat` is not supported inside user-defined functions",
            "`function_side_effect` is not supported: collection mutation via `matrix.concat` is not supported inside user-defined functions",
        ],
    );
}

#[test]
fn accepts_supported_runtime_error_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_runtime_error.pine");
}

#[test]
fn reports_unsupported_runtime_error_message_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_runtime_error_message.pine",
        &["`runtime.error` argument `message` expects string-compatible, got series float"],
    );
}

#[test]
fn reports_unsupported_runtime_error_return_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_runtime_error_return.pine",
        &[
            "declarations must be initialized with a value-producing expression",
            "`plot` argument `series` expects series/simple numeric, got const void",
        ],
    );
}

#[test]
fn reports_unsupported_matrix_add_row_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_add_row.pine",
        "matrix.add_row",
        "array_id",
        "simple array<float>",
        "series float",
    );
}

#[test]
fn reports_unsupported_matrix_add_col_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_add_col.pine",
        "matrix.add_col",
        "array_id",
        "simple array<float>",
        "series float",
    );
}

#[test]
fn reports_unsupported_matrix_remove_row_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_remove_row.pine",
        "matrix.remove_row",
        "row",
        "simple int",
        "series float",
    );
}

#[test]
fn reports_unsupported_matrix_remove_col_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_remove_col.pine",
        "matrix.remove_col",
        "column",
        "simple int",
        "series float",
    );
}

#[test]
fn reports_unsupported_matrix_rows_fixture() {
    assert_matrix_id_message(
        "tests/fixtures/sema/unsupported_matrix_rows.pine",
        "matrix.rows",
        "const na",
    );
}

#[test]
fn reports_unsupported_matrix_rows_method_receiver_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_rows_method_receiver.pine",
        "E_METHOD_RECEIVER_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_columns_fixture() {
    assert_matrix_id_message(
        "tests/fixtures/sema/unsupported_matrix_columns.pine",
        "matrix.columns",
        "const na",
    );
}

#[test]
fn reports_unsupported_matrix_columns_method_receiver_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_columns_method_receiver.pine",
        "E_METHOD_RECEIVER_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_row_fixture() {
    assert_matrix_id_message(
        "tests/fixtures/sema/unsupported_matrix_row.pine",
        "matrix.row",
        "const na",
    );
}

#[test]
fn reports_unsupported_matrix_row_method_receiver_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_row_method_receiver.pine",
        "E_METHOD_RECEIVER_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_row_index_type_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_row_index_type.pine",
        "matrix.row",
        "row",
        "simple int",
        "const string",
    );
}

#[test]
fn reports_unsupported_matrix_row_method_index_type_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_row_method_index_type.pine",
        "matrix.row",
        "row",
        "simple int",
        "const string",
    );
}

#[test]
fn reports_unsupported_matrix_col_fixture() {
    assert_matrix_id_message(
        "tests/fixtures/sema/unsupported_matrix_col.pine",
        "matrix.col",
        "const na",
    );
}

#[test]
fn reports_unsupported_matrix_col_method_receiver_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_col_method_receiver.pine",
        "E_METHOD_RECEIVER_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_col_index_type_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_col_index_type.pine",
        "matrix.col",
        "column",
        "simple int",
        "const string",
    );
}

#[test]
fn reports_unsupported_matrix_col_method_index_type_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_col_method_index_type.pine",
        "matrix.col",
        "column",
        "simple int",
        "const string",
    );
}

#[test]
fn accepts_supported_matrix_row_col_array_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_matrix_row_col_array_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_matrix_row_col_array_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_matrix_row_col_array_return_qualifier.pine",
        &[
            "`matrix.add_row` argument `array_id` expects simple array<float>, got simple array<int>",
            "`matrix.add_col` argument `array_id` expects simple array<float>, got simple array<int>",
            "`matrix.add_row` argument `array_id` expects simple array<int>, got simple array<float>",
            "`matrix.add_col` argument `array_id` expects simple array<int>, got simple array<float>",
            "`matrix.add_row` argument `array_id` expects simple array<string>, got simple array<bool>",
            "`matrix.add_col` argument `array_id` expects simple array<string>, got simple array<bool>",
            "`matrix.add_row` argument `array_id` expects simple array<color>, got simple array<string>",
            "`matrix.add_col` argument `array_id` expects simple array<color>, got simple array<string>",
            "`matrix.add_row` argument `array_id` expects simple array<bool>, got simple array<color>",
            "`matrix.add_col` argument `array_id` expects simple array<bool>, got simple array<color>",
        ],
    );
}

#[test]
fn reports_unsupported_matrix_get_fixture() {
    assert_matrix_id_message(
        "tests/fixtures/sema/unsupported_matrix_get.pine",
        "matrix.get",
        "const na",
    );
}

#[test]
fn reports_unsupported_matrix_get_method_receiver_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_get_method_receiver.pine",
        "E_METHOD_RECEIVER_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_get_row_type_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_get_row_type.pine",
        "matrix.get",
        "row",
        "simple int",
        "const string",
    );
}

#[test]
fn reports_unsupported_matrix_get_column_type_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_get_column_type.pine",
        "matrix.get",
        "column",
        "simple int",
        "const string",
    );
}

#[test]
fn reports_unsupported_matrix_get_method_row_type_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_get_method_row_type.pine",
        "matrix.get",
        "row",
        "simple int",
        "const string",
    );
}

#[test]
fn reports_unsupported_matrix_get_method_column_type_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_get_method_column_type.pine",
        "matrix.get",
        "column",
        "simple int",
        "const string",
    );
}

#[test]
fn accepts_supported_matrix_get_series_element_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_matrix_get_series_element_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_matrix_get_const_input_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_matrix_get_const_input_return_qualifier.pine",
        &[
            "`plot` argument `show_last` expects const/input int, got series int",
            "`plot` argument `show_last` expects const/input int, got series int",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`input.bool` argument `defval` expects const bool, got series bool",
            "`input.bool` argument `defval` expects const bool, got series bool",
            "`syminfo.prefix` argument `symbol` expects simple string, got series string",
            "`syminfo.prefix` argument `symbol` expects simple string, got series string",
            "`hline` argument `color` expects const/input color, got series color",
            "`hline` argument `color` expects const/input color, got series color",
        ],
    );
}

#[test]
fn accepts_supported_matrix_aggregate_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_matrix_aggregate_return_qualifier.pine");
}

#[test]
fn reports_unsupported_matrix_aggregate_const_input_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_matrix_aggregate_const_input_return_qualifier.pine",
        &[
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`plot` argument `show_last` expects const/input int, got series int",
            "`plot` argument `show_last` expects const/input int, got series int",
            "`plot` argument `show_last` expects const/input int, got series int",
            "`plot` argument `show_last` expects const/input int, got series int",
        ],
    );
}

#[test]
fn accepts_supported_matrix_median_series_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_matrix_median_series_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_matrix_median_const_input_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_matrix_median_const_input_return_qualifier.pine",
        &[
            "`plot` argument `show_last` expects const/input int, got series int",
            "`plot` argument `show_last` expects const/input int, got series int",
            "`hline` argument `price` expects const/input numeric, got series float",
            "`hline` argument `price` expects const/input numeric, got series float",
        ],
    );
}

#[test]
fn accepts_supported_matrix_fixed_float_collection_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_matrix_fixed_float_collection_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_matrix_fixed_float_collection_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_matrix_fixed_float_collection_return_qualifier.pine",
        &[
            "`matrix.add_row` argument `array_id` expects simple array<int>, got simple array<float>",
            "`matrix.add_col` argument `array_id` expects simple array<int>, got simple array<float>",
            "`matrix.add_row` argument `array_id` expects simple array<int>, got simple array<float>",
            "`matrix.add_col` argument `array_id` expects simple array<int>, got simple array<float>",
            "`matrix.fill` argument `value` expects numeric-compatible, got const string",
            "`matrix.fill` argument `value` expects numeric-compatible, got const string",
            "`matrix.fill` argument `value` expects numeric-compatible, got const string",
            "`matrix.fill` argument `value` expects numeric-compatible, got const string",
            "`matrix.fill` argument `value` expects numeric-compatible, got const string",
            "`matrix.fill` argument `value` expects numeric-compatible, got const string",
            "`matrix.fill` argument `value` expects numeric-compatible, got const string",
            "`matrix.fill` argument `value` expects numeric-compatible, got const string",
            "`matrix.fill` argument `value` expects numeric-compatible, got const string",
            "`matrix.fill` argument `value` expects numeric-compatible, got const string",
            "`matrix.fill` argument `value` expects numeric-compatible, got const string",
            "`matrix.fill` argument `value` expects numeric-compatible, got const string",
            "`matrix.fill` argument `value` expects numeric-compatible, got const string",
            "`matrix.fill` argument `value` expects numeric-compatible, got const string",
            "`matrix.fill` argument `value` expects numeric-compatible, got const string",
            "`matrix.fill` argument `value` expects numeric-compatible, got const string",
            "`matrix.fill` argument `value` expects numeric-compatible, got const string",
            "`matrix.fill` argument `value` expects numeric-compatible, got const string",
            "`matrix.fill` argument `value` expects numeric-compatible, got const string",
            "`matrix.fill` argument `value` expects numeric-compatible, got const string",
            "`matrix.fill` argument `value` expects numeric-compatible, got const string",
            "`matrix.fill` argument `value` expects numeric-compatible, got const string",
            "`matrix.fill` argument `value` expects numeric-compatible, got const string",
            "`matrix.fill` argument `value` expects numeric-compatible, got const string",
        ],
    );
}

#[test]
fn accepts_supported_matrix_mult_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_matrix_mult_return_qualifier.pine");
}

#[test]
fn reports_unsupported_matrix_mult_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_matrix_mult_return_qualifier.pine",
        &[
            "`matrix.fill` argument `value` expects numeric-compatible, got const string",
            "`matrix.fill` argument `value` expects numeric-compatible, got const string",
            "`matrix.fill` argument `value` expects numeric-compatible, got const string",
            "`matrix.fill` argument `value` expects numeric-compatible, got const string",
            "`matrix.fill` argument `value` expects numeric-compatible, got const string",
            "`matrix.fill` argument `value` expects numeric-compatible, got const string",
            "`matrix.fill` argument `value` expects numeric-compatible, got const string",
            "`matrix.fill` argument `value` expects numeric-compatible, got const string",
            "`matrix.fill` argument `value` expects numeric-compatible, got const string",
            "`matrix.fill` argument `value` expects numeric-compatible, got const string",
            "`matrix.add_row` argument `array_id` expects simple array<int>, got simple array<float>",
            "`matrix.add_row` argument `array_id` expects simple array<int>, got simple array<float>",
            "`matrix.add_row` argument `array_id` expects simple array<int>, got simple array<float>",
            "`matrix.add_row` argument `array_id` expects simple array<int>, got simple array<float>",
            "`matrix.add_row` argument `array_id` expects simple array<int>, got simple array<float>",
            "`matrix.add_row` argument `array_id` expects simple array<int>, got simple array<float>",
        ],
    );
}

#[test]
fn reports_unsupported_matrix_copy_fixture() {
    assert_matrix_id_message(
        "tests/fixtures/sema/unsupported_matrix_copy.pine",
        "matrix.copy",
        "const na",
    );
}

#[test]
fn reports_unsupported_matrix_copy_method_receiver_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_copy_method_receiver.pine",
        "E_METHOD_RECEIVER_TYPE",
    );
}

#[test]
fn accepts_supported_matrix_same_as_arg_return_qualifier_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_matrix_same_as_arg_return_qualifier.pine");
}

#[test]
fn reports_unsupported_matrix_same_as_arg_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_matrix_same_as_arg_return_qualifier.pine",
        &[
            "`matrix.fill` argument `value` expects integer-compatible, got const float",
            "`matrix.fill` argument `value` expects numeric-compatible, got const string",
            "`matrix.fill` argument `value` expects bool-compatible, got const int",
            "`matrix.fill` argument `value` expects string-compatible, got const int",
            "`matrix.fill` argument `value` expects color-compatible, got const int",
            "`matrix.fill` argument `value` expects integer-compatible, got const float",
            "`matrix.fill` argument `value` expects numeric-compatible, got const string",
            "`matrix.fill` argument `value` expects bool-compatible, got const int",
            "`matrix.fill` argument `value` expects string-compatible, got const int",
            "`matrix.fill` argument `value` expects color-compatible, got const int",
            "`matrix.fill` argument `value` expects integer-compatible, got const float",
            "`matrix.fill` argument `value` expects numeric-compatible, got const string",
            "`matrix.fill` argument `value` expects bool-compatible, got const int",
            "`matrix.fill` argument `value` expects string-compatible, got const int",
            "`matrix.fill` argument `value` expects color-compatible, got const int",
            "`matrix.fill` argument `value` expects integer-compatible, got const float",
            "`matrix.fill` argument `value` expects numeric-compatible, got const string",
            "`matrix.fill` argument `value` expects bool-compatible, got const int",
            "`matrix.fill` argument `value` expects string-compatible, got const int",
            "`matrix.fill` argument `value` expects color-compatible, got const int",
        ],
    );
}

#[test]
fn reports_unsupported_matrix_set_fixture() {
    assert_matrix_id_message(
        "tests/fixtures/sema/unsupported_matrix_set.pine",
        "matrix.set",
        "const na",
    );
}

#[test]
fn reports_unsupported_matrix_set_method_receiver_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_set_method_receiver.pine",
        "E_METHOD_RECEIVER_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_set_row_type_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_set_row_type.pine",
        "matrix.set",
        "row",
        "simple int",
        "const string",
    );
}

#[test]
fn reports_unsupported_matrix_set_column_type_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_set_column_type.pine",
        "matrix.set",
        "column",
        "simple int",
        "const string",
    );
}

#[test]
fn reports_unsupported_matrix_set_value_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_set_value.pine",
        "matrix.set",
        "value",
        "numeric-compatible",
        "const string",
    );
}

#[test]
fn reports_unsupported_matrix_set_method_value_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_set_method_value.pine",
        "matrix.set",
        "value",
        "numeric-compatible",
        "const string",
    );
}

#[test]
fn reports_unsupported_matrix_set_method_row_type_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_set_method_row_type.pine",
        "matrix.set",
        "row",
        "simple int",
        "const string",
    );
}

#[test]
fn reports_unsupported_matrix_set_method_column_type_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_set_method_column_type.pine",
        "matrix.set",
        "column",
        "simple int",
        "const string",
    );
}

#[test]
fn reports_unsupported_matrix_fill_fixture() {
    assert_matrix_id_message(
        "tests/fixtures/sema/unsupported_matrix_fill.pine",
        "matrix.fill",
        "const na",
    );
}

#[test]
fn reports_unsupported_matrix_fill_method_receiver_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_fill_method_receiver.pine",
        "E_METHOD_RECEIVER_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_fill_value_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_fill_value.pine",
        "matrix.fill",
        "value",
        "numeric-compatible",
        "const string",
    );
}

#[test]
fn reports_unsupported_matrix_fill_method_value_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_fill_method_value.pine",
        "matrix.fill",
        "value",
        "numeric-compatible",
        "const string",
    );
}

#[test]
fn reports_unsupported_matrix_reshape_fixture() {
    assert_matrix_id_message(
        "tests/fixtures/sema/unsupported_matrix_reshape.pine",
        "matrix.reshape",
        "const na",
    );
}

#[test]
fn reports_unsupported_matrix_reshape_method_receiver_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_reshape_method_receiver.pine",
        "E_METHOD_RECEIVER_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_reshape_row_type_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_reshape_row_type.pine",
        "matrix.reshape",
        "rows",
        "simple int",
        "const string",
    );
}

#[test]
fn reports_unsupported_matrix_reshape_column_type_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_reshape_column_type.pine",
        "matrix.reshape",
        "columns",
        "simple int",
        "const string",
    );
}

#[test]
fn reports_unsupported_matrix_reshape_method_row_type_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_reshape_method_row_type.pine",
        "matrix.reshape",
        "rows",
        "simple int",
        "const string",
    );
}

#[test]
fn reports_unsupported_matrix_reshape_method_column_type_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_reshape_method_column_type.pine",
        "matrix.reshape",
        "columns",
        "simple int",
        "const string",
    );
}

#[test]
fn reports_unsupported_matrix_new_template_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_matrix_new_template.pine",
        "matrix.new<line>",
        "matrix function is outside",
    );
}

#[test]
fn reports_unsupported_matrix_new_deferred_template_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_matrix_new_deferred_template.pine",
        "matrix.new<label>",
        "runtime-owned matrix<float> subset",
    );
}

#[test]
fn reports_unsupported_matrix_new_initial_value_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_new_initial_value.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn accepts_supported_matrix_new_fixed_simple_return_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_matrix_new_fixed_simple_return_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_matrix_new_fixed_simple_return_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_matrix_new_fixed_simple_return_qualifier.pine",
        &[
            "`matrix.fill` argument `value` expects integer-compatible, got const float",
            "`matrix.fill` argument `value` expects numeric-compatible, got const string",
            "`matrix.fill` argument `value` expects bool-compatible, got const int",
            "`matrix.fill` argument `value` expects string-compatible, got const int",
            "`matrix.fill` argument `value` expects color-compatible, got const int",
        ],
    );
}

#[test]
fn accepts_supported_matrix_new_int_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_matrix_new_int.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "matrix.new<int>")
    );
}

#[test]
fn accepts_supported_matrix_new_bool_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_matrix_new_bool.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "matrix.new<bool>")
    );
}

#[test]
fn accepts_supported_matrix_new_string_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_matrix_new_string.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "matrix.new<string>")
    );
}

#[test]
fn accepts_supported_matrix_new_color_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_matrix_new_color.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "matrix.new<color>")
    );
}

#[test]
fn reports_unsupported_matrix_new_int_initial_value_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_new_int_initial_value.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_new_bool_initial_value_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_new_bool_initial_value.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_new_string_initial_value_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_new_string_initial_value.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_new_color_initial_value_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_new_color_initial_value.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_bool_sum_fixture() {
    assert_numeric_matrix_id_message(
        "tests/fixtures/sema/unsupported_matrix_bool_sum.pine",
        "matrix.sum",
        "simple matrix<bool>",
    );
}

#[test]
fn reports_unsupported_matrix_string_sum_fixture() {
    assert_numeric_matrix_id_message(
        "tests/fixtures/sema/unsupported_matrix_string_sum.pine",
        "matrix.sum",
        "simple matrix<string>",
    );
}

#[test]
fn reports_unsupported_matrix_color_sum_fixture() {
    assert_numeric_matrix_id_message(
        "tests/fixtures/sema/unsupported_matrix_color_sum.pine",
        "matrix.sum",
        "simple matrix<color>",
    );
}

#[test]
fn reports_unsupported_matrix_bool_set_float_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_bool_set_float.pine",
        "matrix.set",
        "value",
        "bool-compatible",
        "series float",
    );
}

#[test]
fn reports_unsupported_matrix_string_set_float_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_string_set_float.pine",
        "matrix.set",
        "value",
        "string-compatible",
        "series float",
    );
}

#[test]
fn reports_unsupported_matrix_color_set_float_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_color_set_float.pine",
        "matrix.set",
        "value",
        "color-compatible",
        "series float",
    );
}

#[test]
fn reports_unsupported_matrix_bool_fill_float_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_bool_fill_float.pine",
        "matrix.fill",
        "value",
        "bool-compatible",
        "series float",
    );
}

#[test]
fn reports_unsupported_matrix_string_fill_float_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_string_fill_float.pine",
        "matrix.fill",
        "value",
        "string-compatible",
        "series float",
    );
}

#[test]
fn reports_unsupported_matrix_color_fill_float_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_color_fill_float.pine",
        "matrix.fill",
        "value",
        "color-compatible",
        "series float",
    );
}

#[test]
fn reports_unsupported_matrix_int_set_float_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_int_set_float.pine",
        "matrix.set",
        "value",
        "integer-compatible",
        "const float",
    );
}

#[test]
fn reports_unsupported_matrix_int_fill_float_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_int_fill_float.pine",
        "matrix.fill",
        "value",
        "integer-compatible",
        "const float",
    );
}

#[test]
fn reports_unsupported_matrix_int_add_row_float_array_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_int_add_row_float_array.pine",
        "matrix.add_row",
        "array_id",
        "simple array<int>",
        "simple array<float>",
    );
}

#[test]
fn reports_unsupported_matrix_int_add_col_float_array_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_int_add_col_float_array.pine",
        "matrix.add_col",
        "array_id",
        "simple array<int>",
        "simple array<float>",
    );
}

#[test]
fn accepts_supported_matrix_add_row_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_matrix_add_row.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "matrix.add_row"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_matrix_add_col_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_matrix_add_col.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "matrix.add_col"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_matrix_remove_row_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_matrix_remove_row.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "matrix.remove_row"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_matrix_remove_col_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_matrix_remove_col.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "matrix.remove_col"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_matrix_swap_rows_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_matrix_swap_rows.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "matrix.swap_rows"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_matrix_swap_columns_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_matrix_swap_columns.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "matrix.swap_columns"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_matrix_sort_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_matrix_sort.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "matrix.sort"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_matrix_submatrix_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_matrix_submatrix.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "matrix.submatrix"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_matrix_sum_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_matrix_sum.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "matrix.sum"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_matrix_avg_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_matrix_avg.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "matrix.avg"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_matrix_min_max_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_matrix_min_max.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    for feature in ["matrix.min", "matrix.max"] {
        assert!(
            analysis
                .compatibility
                .supported
                .iter()
                .any(|supported| supported.feature == feature),
            "{} supported features: {:?}",
            path.display(),
            analysis.compatibility.supported
        );
    }
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_matrix_mode_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_matrix_mode.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "matrix.mode"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_matrix_median_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_matrix_median.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "matrix.median"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_matrix_trace_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_matrix_trace.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "matrix.trace"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_matrix_det_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_matrix_det.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "matrix.det"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_matrix_eigenvalues_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_matrix_eigenvalues.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "matrix.eigenvalues"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_matrix_eigenvectors_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_matrix_eigenvectors.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "matrix.eigenvectors"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_matrix_kron_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_matrix_kron.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "matrix.kron"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_matrix_mult_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_matrix_mult.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "matrix.mult"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_matrix_diff_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_matrix_diff.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "matrix.diff"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_matrix_pow_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_matrix_pow.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "matrix.pow"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_matrix_inv_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_matrix_inv.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "matrix.inv"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_matrix_pinv_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_matrix_pinv.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "matrix.pinv"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_matrix_rank_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_matrix_rank.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "matrix.rank"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_matrix_elements_count_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_matrix_elements_count.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "matrix.elements_count"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_matrix_is_square_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_matrix_is_square.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "matrix.is_square"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_matrix_is_binary_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_matrix_is_binary.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "matrix.is_binary"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_matrix_is_diagonal_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_matrix_is_diagonal.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        [
            "matrix.is_diagonal",
            "matrix.is_antidiagonal",
            "matrix.is_triangular",
        ]
        .iter()
        .all(|feature| analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == *feature)),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_matrix_is_identity_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_matrix_is_identity.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "matrix.is_identity"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_matrix_is_symmetric_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_matrix_is_symmetric.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "matrix.is_symmetric"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_matrix_is_antisymmetric_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_matrix_is_antisymmetric.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "matrix.is_antisymmetric"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_matrix_is_stochastic_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_matrix_is_stochastic.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "matrix.is_stochastic"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_matrix_is_zero_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_matrix_is_zero.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "matrix.is_zero"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_matrix_transpose_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_matrix_transpose.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "matrix.transpose"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_supported_matrix_reverse_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_matrix_reverse.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|supported| supported.feature == "matrix.reverse"),
        "{} supported features: {:?}",
        path.display(),
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn reports_unsupported_matrix_sum_fixture() {
    assert_numeric_matrix_id_message(
        "tests/fixtures/sema/unsupported_matrix_sum.pine",
        "matrix.sum",
        "const na",
    );
}

#[test]
fn reports_unsupported_matrix_sum_method_receiver_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_sum_method_receiver.pine",
        "E_METHOD_RECEIVER_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_avg_fixture() {
    assert_numeric_matrix_id_message(
        "tests/fixtures/sema/unsupported_matrix_avg.pine",
        "matrix.avg",
        "const na",
    );
}

#[test]
fn reports_unsupported_matrix_avg_method_receiver_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_avg_method_receiver.pine",
        "E_METHOD_RECEIVER_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_min_fixture() {
    assert_numeric_matrix_id_message(
        "tests/fixtures/sema/unsupported_matrix_min.pine",
        "matrix.min",
        "const na",
    );
}

#[test]
fn reports_unsupported_matrix_min_method_receiver_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_min_method_receiver.pine",
        "E_METHOD_RECEIVER_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_max_fixture() {
    assert_numeric_matrix_id_message(
        "tests/fixtures/sema/unsupported_matrix_max.pine",
        "matrix.max",
        "const na",
    );
}

#[test]
fn reports_unsupported_matrix_max_method_receiver_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_max_method_receiver.pine",
        "E_METHOD_RECEIVER_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_mode_fixture() {
    assert_numeric_matrix_id_message(
        "tests/fixtures/sema/unsupported_matrix_mode.pine",
        "matrix.mode",
        "const na",
    );
}

#[test]
fn reports_unsupported_matrix_mode_method_receiver_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_mode_method_receiver.pine",
        "E_METHOD_RECEIVER_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_median_fixture() {
    assert_numeric_matrix_id_message(
        "tests/fixtures/sema/unsupported_matrix_median.pine",
        "matrix.median",
        "const na",
    );
}

#[test]
fn reports_unsupported_matrix_median_method_receiver_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_median_method_receiver.pine",
        "E_METHOD_RECEIVER_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_trace_fixture() {
    assert_numeric_matrix_id_message(
        "tests/fixtures/sema/unsupported_matrix_trace.pine",
        "matrix.trace",
        "const na",
    );
}

#[test]
fn reports_unsupported_matrix_trace_method_receiver_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_trace_method_receiver.pine",
        "E_METHOD_RECEIVER_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_det_fixture() {
    assert_numeric_matrix_id_message(
        "tests/fixtures/sema/unsupported_matrix_det.pine",
        "matrix.det",
        "const na",
    );
}

#[test]
fn reports_unsupported_matrix_det_method_receiver_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_det_method_receiver.pine",
        "E_METHOD_RECEIVER_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_eigenvalues_fixture() {
    assert_numeric_matrix_id_message(
        "tests/fixtures/sema/unsupported_matrix_eigenvalues.pine",
        "matrix.eigenvalues",
        "const na",
    );
}

#[test]
fn reports_unsupported_matrix_eigenvalues_method_receiver_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_eigenvalues_method_receiver.pine",
        "E_METHOD_RECEIVER_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_eigenvectors_fixture() {
    assert_numeric_matrix_id_message(
        "tests/fixtures/sema/unsupported_matrix_eigenvectors.pine",
        "matrix.eigenvectors",
        "const na",
    );
}

#[test]
fn reports_unsupported_matrix_eigenvectors_method_receiver_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_eigenvectors_method_receiver.pine",
        "E_METHOD_RECEIVER_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_kron_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_kron.pine",
        "matrix.kron",
        "id1",
        "numeric matrix",
        "const na",
    );
}

#[test]
fn reports_unsupported_matrix_kron_method_receiver_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_kron_method_receiver.pine",
        "E_METHOD_RECEIVER_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_kron_value_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_kron_value.pine",
        "matrix.kron",
        "id2",
        "numeric matrix",
        "series float",
    );
}

#[test]
fn reports_unsupported_matrix_kron_method_value_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_kron_method_value.pine",
        "matrix.kron",
        "id2",
        "numeric matrix",
        "series float",
    );
}

#[test]
fn reports_unsupported_matrix_mult_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_mult.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_mult_method_receiver_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_mult_method_receiver.pine",
        "E_METHOD_RECEIVER_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_mult_value_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_mult_value.pine",
        "matrix.mult",
        "id2",
        "numeric matrix, numeric-compatible, or numeric array",
        "const string",
    );
}

#[test]
fn reports_unsupported_matrix_mult_scalar_pair_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_matrix_mult_scalar_pair.pine",
        &[
            "`matrix.mult` argument `id1` expects numeric matrix, got const int",
            "`matrix.mult` argument `id2` expects numeric matrix, got const int",
        ],
    );
}

#[test]
fn accepts_supported_matrix_mult_array_pair_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_matrix_mult_array_pair.pine");
}

#[test]
fn reports_unsupported_matrix_mult_bool_array_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_mult_bool_array.pine",
        "matrix.mult",
        "id2",
        "numeric matrix, numeric-compatible, or numeric array",
        "simple array<bool>",
    );
}

#[test]
fn reports_unsupported_matrix_mult_method_value_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_mult_method_value.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_diff_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_diff.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_diff_method_receiver_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_diff_method_receiver.pine",
        "E_METHOD_RECEIVER_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_diff_value_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_diff_value.pine",
        "matrix.diff",
        "id2",
        "numeric matrix or numeric-compatible",
        "const string",
    );
}

#[test]
fn reports_unsupported_matrix_diff_scalar_pair_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_matrix_diff_scalar_pair.pine",
        &[
            "`matrix.diff` argument `id1` expects numeric matrix, got const int",
            "`matrix.diff` argument `id2` expects numeric matrix, got const int",
        ],
    );
}

#[test]
fn reports_unsupported_matrix_diff_method_value_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_diff_method_value.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_pow_fixture() {
    assert_numeric_matrix_id_message(
        "tests/fixtures/sema/unsupported_matrix_pow.pine",
        "matrix.pow",
        "const na",
    );
}

#[test]
fn reports_unsupported_matrix_pow_method_receiver_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_pow_method_receiver.pine",
        "E_METHOD_RECEIVER_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_pow_power_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_pow_power.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_pow_method_power_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_pow_method_power.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_inv_fixture() {
    assert_numeric_matrix_id_message(
        "tests/fixtures/sema/unsupported_matrix_inv.pine",
        "matrix.inv",
        "const na",
    );
}

#[test]
fn reports_unsupported_matrix_inv_method_receiver_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_inv_method_receiver.pine",
        "E_METHOD_RECEIVER_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_pinv_fixture() {
    assert_numeric_matrix_id_message(
        "tests/fixtures/sema/unsupported_matrix_pinv.pine",
        "matrix.pinv",
        "const na",
    );
}

#[test]
fn reports_unsupported_matrix_pinv_method_receiver_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_pinv_method_receiver.pine",
        "E_METHOD_RECEIVER_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_rank_fixture() {
    assert_numeric_matrix_id_message(
        "tests/fixtures/sema/unsupported_matrix_rank.pine",
        "matrix.rank",
        "const na",
    );
}

#[test]
fn reports_unsupported_matrix_rank_method_receiver_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_rank_method_receiver.pine",
        "E_METHOD_RECEIVER_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_elements_count_fixture() {
    assert_matrix_id_message(
        "tests/fixtures/sema/unsupported_matrix_elements_count.pine",
        "matrix.elements_count",
        "const na",
    );
}

#[test]
fn reports_unsupported_matrix_elements_count_method_receiver_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_elements_count_method_receiver.pine",
        "E_METHOD_RECEIVER_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_is_square_fixture() {
    assert_matrix_id_message(
        "tests/fixtures/sema/unsupported_matrix_is_square.pine",
        "matrix.is_square",
        "const na",
    );
}

#[test]
fn reports_unsupported_matrix_is_square_method_receiver_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_is_square_method_receiver.pine",
        "E_METHOD_RECEIVER_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_is_binary_fixture() {
    assert_numeric_matrix_id_message(
        "tests/fixtures/sema/unsupported_matrix_is_binary.pine",
        "matrix.is_binary",
        "const na",
    );
}

#[test]
fn reports_unsupported_matrix_is_binary_method_receiver_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_is_binary_method_receiver.pine",
        "E_METHOD_RECEIVER_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_is_diagonal_fixture() {
    assert_numeric_matrix_id_message(
        "tests/fixtures/sema/unsupported_matrix_is_diagonal.pine",
        "matrix.is_diagonal",
        "const na",
    );
    assert_numeric_matrix_id_message(
        "tests/fixtures/sema/unsupported_matrix_is_diagonal.pine",
        "matrix.is_antidiagonal",
        "const na",
    );
    assert_numeric_matrix_id_message(
        "tests/fixtures/sema/unsupported_matrix_is_diagonal.pine",
        "matrix.is_triangular",
        "const na",
    );
}

#[test]
fn reports_unsupported_matrix_is_diagonal_method_receiver_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_is_diagonal_method_receiver.pine",
        "E_METHOD_RECEIVER_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_is_identity_fixture() {
    assert_numeric_matrix_id_message(
        "tests/fixtures/sema/unsupported_matrix_is_identity.pine",
        "matrix.is_identity",
        "const na",
    );
}

#[test]
fn reports_unsupported_matrix_is_identity_method_receiver_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_is_identity_method_receiver.pine",
        "E_METHOD_RECEIVER_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_is_symmetric_fixture() {
    assert_numeric_matrix_id_message(
        "tests/fixtures/sema/unsupported_matrix_is_symmetric.pine",
        "matrix.is_symmetric",
        "const na",
    );
}

#[test]
fn reports_unsupported_matrix_is_symmetric_method_receiver_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_is_symmetric_method_receiver.pine",
        "E_METHOD_RECEIVER_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_is_antisymmetric_fixture() {
    assert_numeric_matrix_id_message(
        "tests/fixtures/sema/unsupported_matrix_is_antisymmetric.pine",
        "matrix.is_antisymmetric",
        "const na",
    );
}

#[test]
fn reports_unsupported_matrix_is_antisymmetric_method_receiver_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_is_antisymmetric_method_receiver.pine",
        "E_METHOD_RECEIVER_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_is_stochastic_fixture() {
    assert_numeric_matrix_id_message(
        "tests/fixtures/sema/unsupported_matrix_is_stochastic.pine",
        "matrix.is_stochastic",
        "const na",
    );
}

#[test]
fn reports_unsupported_matrix_is_stochastic_method_receiver_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_is_stochastic_method_receiver.pine",
        "E_METHOD_RECEIVER_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_is_zero_fixture() {
    assert_numeric_matrix_id_message(
        "tests/fixtures/sema/unsupported_matrix_is_zero.pine",
        "matrix.is_zero",
        "const na",
    );
}

#[test]
fn reports_unsupported_matrix_is_zero_method_receiver_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_is_zero_method_receiver.pine",
        "E_METHOD_RECEIVER_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_transpose_fixture() {
    assert_matrix_id_message(
        "tests/fixtures/sema/unsupported_matrix_transpose.pine",
        "matrix.transpose",
        "const na",
    );
}

#[test]
fn reports_unsupported_matrix_transpose_method_receiver_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_transpose_method_receiver.pine",
        "E_METHOD_RECEIVER_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_reverse_fixture() {
    assert_matrix_id_message(
        "tests/fixtures/sema/unsupported_matrix_reverse.pine",
        "matrix.reverse",
        "const na",
    );
}

#[test]
fn reports_unsupported_matrix_reverse_method_receiver_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_reverse_method_receiver.pine",
        "E_METHOD_RECEIVER_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_swap_rows_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_swap_rows.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_swap_rows_method_receiver_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_swap_rows_method_receiver.pine",
        "E_METHOD_RECEIVER_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_swap_rows_row1_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_swap_rows_row1.pine",
        "matrix.swap_rows",
        "row1",
        "simple int",
        "const float",
    );
}

#[test]
fn reports_unsupported_matrix_swap_rows_row2_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_swap_rows_row2.pine",
        "matrix.swap_rows",
        "row2",
        "simple int",
        "const float",
    );
}

#[test]
fn reports_unsupported_matrix_swap_rows_method_row1_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_swap_rows_method_row1.pine",
        "matrix.swap_rows",
        "row1",
        "simple int",
        "const float",
    );
}

#[test]
fn reports_unsupported_matrix_swap_rows_method_row2_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_swap_rows_method_row2.pine",
        "matrix.swap_rows",
        "row2",
        "simple int",
        "const float",
    );
}

#[test]
fn reports_unsupported_matrix_swap_columns_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_swap_columns.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_swap_columns_method_receiver_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_swap_columns_method_receiver.pine",
        "E_METHOD_RECEIVER_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_swap_columns_column1_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_swap_columns_column1.pine",
        "matrix.swap_columns",
        "column1",
        "simple int",
        "const float",
    );
}

#[test]
fn reports_unsupported_matrix_swap_columns_column2_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_swap_columns_column2.pine",
        "matrix.swap_columns",
        "column2",
        "simple int",
        "const float",
    );
}

#[test]
fn reports_unsupported_matrix_swap_columns_method_column1_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_swap_columns_method_column1.pine",
        "matrix.swap_columns",
        "column1",
        "simple int",
        "const float",
    );
}

#[test]
fn reports_unsupported_matrix_swap_columns_method_column2_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_swap_columns_method_column2.pine",
        "matrix.swap_columns",
        "column2",
        "simple int",
        "const float",
    );
}

#[test]
fn reports_unsupported_matrix_sort_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_sort.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_sort_method_receiver_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_sort_method_receiver.pine",
        "E_METHOD_RECEIVER_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_sort_column_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_sort_column.pine",
        "matrix.sort",
        "column",
        "simple int",
        "const float",
    );
}

#[test]
fn reports_unsupported_matrix_sort_order_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_sort_order.pine",
        "matrix.sort",
        "order",
        "const string",
        "series float",
    );
}

#[test]
fn reports_unsupported_matrix_sort_method_column_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_sort_method_column.pine",
        "matrix.sort",
        "column",
        "simple int",
        "const float",
    );
}

#[test]
fn reports_unsupported_matrix_sort_method_order_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_sort_method_order.pine",
        "matrix.sort",
        "order",
        "const string",
        "series float",
    );
}

#[test]
fn reports_unsupported_matrix_submatrix_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_submatrix.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_submatrix_method_receiver_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_submatrix_method_receiver.pine",
        "E_METHOD_RECEIVER_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_submatrix_from_row_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_submatrix_from_row.pine",
        "matrix.submatrix",
        "from_row",
        "simple int",
        "const float",
    );
}

#[test]
fn reports_unsupported_matrix_submatrix_to_row_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_submatrix_to_row.pine",
        "matrix.submatrix",
        "to_row",
        "simple int",
        "const float",
    );
}

#[test]
fn reports_unsupported_matrix_submatrix_from_column_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_submatrix_from_column.pine",
        "matrix.submatrix",
        "from_column",
        "simple int",
        "const float",
    );
}

#[test]
fn reports_unsupported_matrix_submatrix_to_column_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_submatrix_to_column.pine",
        "matrix.submatrix",
        "to_column",
        "simple int",
        "const float",
    );
}

#[test]
fn reports_unsupported_matrix_submatrix_method_from_row_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_submatrix_method_from_row.pine",
        "matrix.submatrix",
        "from_row",
        "simple int",
        "const float",
    );
}

#[test]
fn reports_unsupported_matrix_submatrix_method_to_row_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_submatrix_method_to_row.pine",
        "matrix.submatrix",
        "to_row",
        "simple int",
        "const float",
    );
}

#[test]
fn reports_unsupported_matrix_submatrix_method_from_column_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_submatrix_method_from_column.pine",
        "matrix.submatrix",
        "from_column",
        "simple int",
        "const float",
    );
}

#[test]
fn reports_unsupported_matrix_submatrix_method_to_column_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_submatrix_method_to_column.pine",
        "matrix.submatrix",
        "to_column",
        "simple int",
        "const float",
    );
}

#[test]
fn reports_unsupported_matrix_set_udf_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_matrix_set_udf.pine",
        "function_side_effect",
        "collection mutation via `matrix.set`",
    );
}

#[test]
fn reports_unsupported_matrix_set_method_udf_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_matrix_set_method_udf.pine",
        "function_side_effect",
        "collection mutation via `matrix.set`",
    );
}

#[test]
fn reports_unsupported_matrix_fill_udf_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_matrix_fill_udf.pine",
        "function_side_effect",
        "collection mutation via",
    );
}

#[test]
fn reports_unsupported_matrix_fill_method_udf_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_matrix_fill_method_udf.pine",
        "function_side_effect",
        "collection mutation via",
    );
}

#[test]
fn reports_unsupported_matrix_reshape_udf_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_matrix_reshape_udf.pine",
        "function_side_effect",
        "collection mutation via",
    );
}

#[test]
fn reports_unsupported_matrix_reshape_method_udf_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_matrix_reshape_method_udf.pine",
        "function_side_effect",
        "collection mutation via",
    );
}

#[test]
fn reports_unsupported_matrix_reverse_udf_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_matrix_reverse_udf.pine",
        "function_side_effect",
        "collection mutation via",
    );
}

#[test]
fn reports_unsupported_matrix_reverse_method_udf_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_matrix_reverse_method_udf.pine",
        "function_side_effect",
        "collection mutation via",
    );
}

#[test]
fn reports_unsupported_matrix_add_row_udf_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_matrix_add_row_udf.pine",
        "function_side_effect",
        "collection mutation via",
    );
}

#[test]
fn reports_unsupported_matrix_add_row_method_udf_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_matrix_add_row_method_udf.pine",
        "function_side_effect",
        "collection mutation via",
    );
}

#[test]
fn reports_unsupported_matrix_add_col_udf_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_matrix_add_col_udf.pine",
        "function_side_effect",
        "collection mutation via",
    );
}

#[test]
fn reports_unsupported_matrix_add_col_method_udf_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_matrix_add_col_method_udf.pine",
        "function_side_effect",
        "collection mutation via",
    );
}

#[test]
fn reports_unsupported_matrix_remove_row_udf_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_matrix_remove_row_udf.pine",
        "function_side_effect",
        "collection mutation via",
    );
}

#[test]
fn reports_unsupported_matrix_remove_row_method_udf_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_matrix_remove_row_method_udf.pine",
        "function_side_effect",
        "collection mutation via",
    );
}

#[test]
fn reports_unsupported_matrix_remove_col_udf_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_matrix_remove_col_udf.pine",
        "function_side_effect",
        "collection mutation via",
    );
}

#[test]
fn reports_unsupported_matrix_remove_col_method_udf_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_matrix_remove_col_method_udf.pine",
        "function_side_effect",
        "collection mutation via",
    );
}

#[test]
fn reports_unsupported_matrix_swap_rows_udf_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_matrix_swap_rows_udf.pine",
        "function_side_effect",
        "collection mutation via",
    );
}

#[test]
fn reports_unsupported_matrix_swap_rows_method_udf_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_matrix_swap_rows_method_udf.pine",
        "function_side_effect",
        "collection mutation via",
    );
}

#[test]
fn reports_unsupported_matrix_swap_columns_udf_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_matrix_swap_columns_udf.pine",
        "function_side_effect",
        "collection mutation via",
    );
}

#[test]
fn reports_unsupported_matrix_swap_columns_method_udf_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_matrix_swap_columns_method_udf.pine",
        "function_side_effect",
        "collection mutation via",
    );
}

#[test]
fn reports_unsupported_matrix_sort_udf_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_matrix_sort_udf.pine",
        "function_side_effect",
        "collection mutation via",
    );
}

#[test]
fn reports_unsupported_matrix_sort_method_udf_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_matrix_sort_method_udf.pine",
        "function_side_effect",
        "collection mutation via",
    );
}

#[test]
fn reports_unsupported_matrix_add_row_method_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_add_row_method.pine",
        "matrix.add_row",
        "array_id",
        "simple array<float>",
        "series float",
    );
}

#[test]
fn reports_unsupported_matrix_add_col_method_fixture() {
    assert_call_arg_message(
        "tests/fixtures/sema/unsupported_matrix_add_col_method.pine",
        "matrix.add_col",
        "array_id",
        "simple array<float>",
        "series float",
    );
}

#[test]
fn reports_unsupported_matrix_remove_row_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_remove_row_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_matrix_remove_col_method_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_matrix_remove_col_method.pine",
        "E_CALL_ARG_TYPE",
    );
}

#[test]
fn reports_unsupported_alertcondition_dynamic_title_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_alertcondition_dynamic_title.pine",
        &["argument `title`", "input string"],
    );
}

#[test]
fn reports_unsupported_alertcondition_dynamic_message_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_alertcondition_dynamic_message.pine",
        &["argument `message`", "input string"],
    );
}

#[test]
fn reports_unsupported_function_side_effect_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_function_side_effect.pine",
        "function_side_effect",
        "inside user-defined functions",
    );
}

#[test]
fn reports_unsupported_function_side_effect_arg_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_function_side_effect_arg.pine",
        "function_side_effect",
        "side-effecting calls cannot be passed as user-defined function arguments",
    );
}

#[test]
fn reports_unsupported_function_duplicate_named_arg_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_function_duplicate_named_arg.pine",
        "E_FUNCTION_ARG_DUPLICATE",
    );
}

#[test]
fn reports_unsupported_function_unknown_named_arg_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_function_unknown_named_arg.pine",
        "E_FUNCTION_ARG_NAME",
    );
}

#[test]
fn reports_unsupported_function_pos_after_named_arg_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_function_pos_after_named_arg.pine",
        "E_FUNCTION_ARG_ORDER",
    );
}

#[test]
fn reports_unsupported_function_missing_arg_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_function_missing_arg.pine",
        "E_FUNCTION_ARITY",
    );
}

#[test]
fn reports_unsupported_function_too_many_args_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_function_too_many_args.pine",
        "E_FUNCTION_ARITY",
    );
}

#[test]
fn reports_unsupported_declaration_function_side_effect_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_declaration_function_side_effect.pine",
        "function_side_effect",
        "indicator",
    );
}

#[test]
fn reports_unsupported_array_function_side_effect_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_array_function_side_effect.pine",
        "function_side_effect",
        "collection mutation via `array.push`",
    );
}

#[test]
fn reports_unsupported_input_function_side_effect_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_input_function_side_effect.pine",
        "function_side_effect",
        "input",
    );
}

#[test]
fn reports_unsupported_drawing_function_side_effect_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_drawing_function_side_effect.pine",
        "function_side_effect",
        "inside user-defined functions",
    );
}

#[test]
fn reports_unsupported_alert_function_side_effect_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_alert_function_side_effect.pine",
        "function_side_effect",
        "alertcondition",
    );
}

#[test]
fn reports_unsupported_imperative_alert_function_side_effect_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_imperative_alert_function_side_effect.pine",
        "function_side_effect",
        "alert",
    );
}

#[test]
fn reports_unsupported_strategy_order_function_side_effect_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_strategy_order_function_side_effect.pine",
        "function_side_effect",
        "strategy order calls",
    );
}

#[test]
fn reports_unsupported_strategy_close_function_side_effect_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_strategy_close_function_side_effect.pine",
        "function_side_effect",
        "strategy order calls",
    );
}

#[test]
fn reports_unsupported_strategy_close_all_function_side_effect_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_strategy_close_all_function_side_effect.pine",
        "function_side_effect",
        "strategy order calls",
    );
}

#[test]
fn reports_unsupported_strategy_cancel_function_side_effect_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_strategy_cancel_function_side_effect.pine",
        "function_side_effect",
        "strategy order calls",
    );
}

#[test]
fn reports_unsupported_strategy_cancel_all_function_side_effect_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_strategy_cancel_all_function_side_effect.pine",
        "function_side_effect",
        "strategy order calls",
    );
}

#[test]
fn accepts_supported_dynamic_history_integer_result_offsets_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_dynamic_history_integer_result_offsets.pine",
    );
}

#[test]
fn reports_unsupported_dynamic_history_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_dynamic_history.pine",
        &[
            "`dynamic_history_offset` is not supported: dynamic history offsets require an integer expression in the current supported subset; got series float",
        ],
    );
}

#[test]
fn reports_unsupported_dynamic_history_bool_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_dynamic_history_bool.pine",
        &[
            "`dynamic_history_offset` is not supported: dynamic history offsets require an integer expression in the current supported subset; got series bool",
        ],
    );
}

#[test]
fn reports_unsupported_dynamic_history_udf_return_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_dynamic_history_udf_return.pine",
        &[
            "`dynamic_history_offset` is not supported: dynamic history offsets require an integer expression in the current supported subset; got series float",
        ],
    );
}

#[test]
fn reports_unsupported_dynamic_history_builtin_result_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_dynamic_history_builtin_result.pine",
        &[
            "`dynamic_history_offset` is not supported: dynamic history offsets require an integer expression in the current supported subset; got series float",
        ],
    );
}

#[test]
fn reports_unsupported_dynamic_history_udt_field_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_dynamic_history_udt_field.pine",
        &[
            "`dynamic_history_offset` is not supported: dynamic history offsets require an integer expression in the current supported subset; got const float",
            "`dynamic_history_offset` is not supported: dynamic history offsets require an integer expression in the current supported subset; got series float",
            "`dynamic_history_offset` is not supported: dynamic history offsets require an integer expression in the current supported subset; got series bool",
            "`dynamic_history_offset` is not supported: dynamic history offsets require an integer expression in the current supported subset; got series string",
        ],
    );
    assert_diagnostic_count(
        "tests/fixtures/sema/unsupported_dynamic_history_udt_field.pine",
        11,
    );
}

#[test]
fn reports_unsupported_dynamic_history_import_udt_field_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_dynamic_history_import_udt_field.pine",
        &[
            "`dynamic_history_offset` is not supported: dynamic history offsets require an integer expression in the current supported subset; got series float",
        ],
    );
    assert_import_diagnostic_count(
        "tests/fixtures/sema/unsupported_dynamic_history_import_udt_field.pine",
        12,
    );
}

#[test]
fn reports_unsupported_dynamic_history_import_udt_bool_field_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_dynamic_history_import_udt_bool_field.pine",
        &[
            "`dynamic_history_offset` is not supported: dynamic history offsets require an integer expression in the current supported subset; got series bool",
        ],
    );
    assert_import_diagnostic_count(
        "tests/fixtures/sema/unsupported_dynamic_history_import_udt_bool_field.pine",
        3,
    );
}

#[test]
fn reports_unsupported_dynamic_history_import_udt_nested_bool_field_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_dynamic_history_import_udt_nested_bool_field.pine",
        &[
            "`dynamic_history_offset` is not supported: dynamic history offsets require an integer expression in the current supported subset; got series bool",
        ],
    );
    assert_import_diagnostic_count(
        "tests/fixtures/sema/unsupported_dynamic_history_import_udt_nested_bool_field.pine",
        3,
    );
}

#[test]
fn reports_unsupported_dynamic_history_import_udt_string_field_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_dynamic_history_import_udt_string_field.pine",
        &[
            "`dynamic_history_offset` is not supported: dynamic history offsets require an integer expression in the current supported subset; got series string",
        ],
    );
    assert_import_diagnostic_count(
        "tests/fixtures/sema/unsupported_dynamic_history_import_udt_string_field.pine",
        3,
    );
}

#[test]
fn reports_unsupported_dynamic_history_import_udt_nested_string_field_fixture() {
    assert_import_diagnostic_messages(
        "tests/fixtures/sema/unsupported_dynamic_history_import_udt_nested_string_field.pine",
        &[
            "`dynamic_history_offset` is not supported: dynamic history offsets require an integer expression in the current supported subset; got series string",
        ],
    );
    assert_import_diagnostic_count(
        "tests/fixtures/sema/unsupported_dynamic_history_import_udt_nested_string_field.pine",
        3,
    );
}

#[test]
fn reports_unsupported_dynamic_history_ternary_result_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_dynamic_history_ternary_result.pine",
        &[
            "`dynamic_history_offset` is not supported: dynamic history offsets require an integer expression in the current supported subset; got series float",
        ],
    );
}

#[test]
fn reports_unsupported_dynamic_history_if_result_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_dynamic_history_if_result.pine",
        &[
            "`dynamic_history_offset` is not supported: dynamic history offsets require an integer expression in the current supported subset; got series float",
        ],
    );
}

#[test]
fn reports_unsupported_dynamic_history_switch_result_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_dynamic_history_switch_result.pine",
        &[
            "`dynamic_history_offset` is not supported: dynamic history offsets require an integer expression in the current supported subset; got series float",
        ],
    );
}

#[test]
fn reports_unsupported_dynamic_history_for_result_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_dynamic_history_for_result.pine",
        &[
            "`dynamic_history_offset` is not supported: dynamic history offsets require an integer expression in the current supported subset; got series float",
        ],
    );
}

#[test]
fn reports_unsupported_dynamic_history_for_in_result_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_dynamic_history_for_in_result.pine",
        &[
            "`dynamic_history_offset` is not supported: dynamic history offsets require an integer expression in the current supported subset; got series float",
        ],
    );
}

#[test]
fn reports_unsupported_dynamic_history_while_result_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_dynamic_history_while_result.pine",
        &[
            "`dynamic_history_offset` is not supported: dynamic history offsets require an integer expression in the current supported subset; got series float",
        ],
    );
}

#[test]
fn reports_unsupported_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_const_expression_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_const_expression_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_const_expression_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_pure_const_call_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_pure_const_call_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_pure_const_call_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_named_const_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_named_const_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_named_const_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_alias_named_const_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_alias_named_const_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_alias_named_const_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_named_const_expression_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_named_const_expression_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_named_const_expression_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_named_const_ternary_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_named_const_ternary_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_named_const_ternary_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_equal_branch_ternary_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_equal_branch_ternary_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_equal_branch_ternary_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_named_const_if_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_named_const_if_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_named_const_if_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_equal_branch_if_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_equal_branch_if_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_equal_branch_if_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_branch_local_alias_if_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_branch_local_alias_if_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_branch_local_alias_if_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_branch_tuple_alias_if_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_branch_tuple_alias_if_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_branch_tuple_alias_if_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_named_const_comparison_ternary_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_named_const_comparison_ternary_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_named_const_comparison_ternary_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_named_const_numeric_if_comparison_ternary_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_named_const_numeric_if_comparison_ternary_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_named_const_numeric_if_comparison_ternary_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_named_const_numeric_switch_comparison_ternary_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_named_const_numeric_switch_comparison_ternary_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_named_const_numeric_switch_comparison_ternary_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_named_const_string_comparison_ternary_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_named_const_string_comparison_ternary_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_named_const_string_comparison_ternary_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_named_const_string_if_comparison_ternary_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_named_const_string_if_comparison_ternary_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_named_const_string_if_comparison_ternary_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_named_const_string_switch_comparison_ternary_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_named_const_string_switch_comparison_ternary_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_named_const_string_switch_comparison_ternary_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_named_const_color_comparison_ternary_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_named_const_color_comparison_ternary_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_named_const_color_comparison_ternary_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_named_const_color_if_comparison_ternary_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_named_const_color_if_comparison_ternary_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_named_const_color_if_comparison_ternary_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_named_const_color_switch_comparison_ternary_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_named_const_color_switch_comparison_ternary_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_named_const_color_switch_comparison_ternary_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_named_const_bool_comparison_ternary_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_named_const_bool_comparison_ternary_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_named_const_bool_comparison_ternary_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_named_const_bool_if_ternary_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_named_const_bool_if_ternary_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_named_const_bool_if_ternary_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_named_const_bool_switch_ternary_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_named_const_bool_switch_ternary_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_named_const_bool_switch_ternary_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_named_const_logical_ternary_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_named_const_logical_ternary_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_named_const_logical_ternary_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_named_const_switch_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_named_const_switch_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_named_const_switch_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_named_const_switch_block_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_named_const_switch_block_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_named_const_switch_block_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_named_const_condition_switch_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_named_const_condition_switch_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_named_const_condition_switch_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_equal_branch_switch_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_equal_branch_switch_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_equal_branch_switch_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_branch_local_alias_switch_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_branch_local_alias_switch_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_branch_local_alias_switch_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_branch_tuple_alias_switch_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_branch_tuple_alias_switch_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_branch_tuple_alias_switch_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_result_local_alias_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_result_local_alias_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_result_local_alias_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn accepts_supported_for_in_empty_result_negative_body_history_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_for_in_empty_result_negative_body_history.pine",
    );
}

#[test]
fn accepts_supported_for_in_empty_matrix_result_negative_body_history_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_for_in_empty_matrix_result_negative_body_history.pine",
    );
}

#[test]
fn accepts_supported_for_in_empty_str_split_result_negative_body_history_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_for_in_empty_str_split_result_negative_body_history.pine",
    );
}

#[test]
fn accepts_supported_for_in_empty_array_copy_result_negative_body_history_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_for_in_empty_array_copy_result_negative_body_history.pine",
    );
}

#[test]
fn accepts_supported_for_in_empty_array_concat_result_negative_body_history_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_for_in_empty_array_concat_result_negative_body_history.pine",
    );
}

#[test]
fn accepts_supported_for_in_empty_array_slice_result_negative_body_history_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_for_in_empty_array_slice_result_negative_body_history.pine",
    );
}

#[test]
fn accepts_supported_for_in_empty_array_abs_result_negative_body_history_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_for_in_empty_array_abs_result_negative_body_history.pine",
    );
}

#[test]
fn accepts_supported_for_in_empty_array_abs_method_result_negative_body_history_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_for_in_empty_array_abs_method_result_negative_body_history.pine",
    );
}

#[test]
fn accepts_supported_for_in_empty_array_standardize_result_negative_body_history_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_for_in_empty_array_standardize_result_negative_body_history.pine",
    );
}

#[test]
fn accepts_supported_for_in_empty_array_standardize_method_result_negative_body_history_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_for_in_empty_array_standardize_method_result_negative_body_history.pine",
    );
}

#[test]
fn accepts_supported_for_in_empty_array_sort_indices_result_negative_body_history_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_for_in_empty_array_sort_indices_result_negative_body_history.pine",
    );
}

#[test]
fn accepts_supported_for_in_empty_array_sort_indices_method_result_negative_body_history_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_for_in_empty_array_sort_indices_method_result_negative_body_history.pine",
    );
}

#[test]
fn accepts_supported_for_in_empty_matrix_copy_result_negative_body_history_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_for_in_empty_matrix_copy_result_negative_body_history.pine",
    );
}

#[test]
fn accepts_supported_for_in_empty_matrix_transpose_result_negative_body_history_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_for_in_empty_matrix_transpose_result_negative_body_history.pine",
    );
}

#[test]
fn accepts_supported_for_in_empty_matrix_submatrix_result_negative_body_history_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_for_in_empty_matrix_submatrix_result_negative_body_history.pine",
    );
}

#[test]
fn accepts_supported_for_in_empty_matrix_row_result_negative_body_history_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_for_in_empty_matrix_row_result_negative_body_history.pine",
    );
}

#[test]
fn accepts_supported_for_in_empty_matrix_col_result_negative_body_history_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_for_in_empty_matrix_col_result_negative_body_history.pine",
    );
}

#[test]
fn accepts_supported_for_in_empty_matrix_eigenvalues_result_negative_body_history_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_for_in_empty_matrix_eigenvalues_result_negative_body_history.pine",
    );
}

#[test]
fn accepts_supported_for_in_empty_matrix_eigenvalues_method_result_negative_body_history_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_for_in_empty_matrix_eigenvalues_method_result_negative_body_history.pine",
    );
}

#[test]
fn accepts_supported_for_in_empty_matrix_eigenvectors_result_negative_body_history_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_for_in_empty_matrix_eigenvectors_result_negative_body_history.pine",
    );
}

#[test]
fn accepts_supported_for_in_empty_matrix_eigenvectors_method_result_negative_body_history_fixture()
{
    assert_valid_fixture(
        "tests/fixtures/sema/supported_for_in_empty_matrix_eigenvectors_method_result_negative_body_history.pine",
    );
}

#[test]
fn accepts_supported_for_in_empty_matrix_inv_result_negative_body_history_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_for_in_empty_matrix_inv_result_negative_body_history.pine",
    );
}

#[test]
fn accepts_supported_for_in_empty_matrix_inv_method_result_negative_body_history_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_for_in_empty_matrix_inv_method_result_negative_body_history.pine",
    );
}

#[test]
fn accepts_supported_for_in_empty_matrix_pinv_result_negative_body_history_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_for_in_empty_matrix_pinv_result_negative_body_history.pine",
    );
}

#[test]
fn accepts_supported_for_in_empty_matrix_pinv_method_result_negative_body_history_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_for_in_empty_matrix_pinv_method_result_negative_body_history.pine",
    );
}

#[test]
fn accepts_supported_for_in_empty_matrix_kron_result_negative_body_history_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_for_in_empty_matrix_kron_result_negative_body_history.pine",
    );
}

#[test]
fn accepts_supported_for_in_empty_matrix_kron_method_result_negative_body_history_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_for_in_empty_matrix_kron_method_result_negative_body_history.pine",
    );
}

#[test]
fn accepts_supported_for_in_empty_matrix_mult_result_negative_body_history_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_for_in_empty_matrix_mult_result_negative_body_history.pine",
    );
}

#[test]
fn accepts_supported_for_in_empty_matrix_mult_method_result_negative_body_history_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_for_in_empty_matrix_mult_method_result_negative_body_history.pine",
    );
}

#[test]
fn accepts_supported_for_in_empty_matrix_mult_array_result_negative_body_history_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_for_in_empty_matrix_mult_array_result_negative_body_history.pine",
    );
}

#[test]
fn accepts_supported_for_in_empty_matrix_mult_left_array_result_negative_body_history_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_for_in_empty_matrix_mult_left_array_result_negative_body_history.pine",
    );
}

#[test]
fn accepts_supported_for_in_empty_matrix_mult_array_method_result_negative_body_history_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_for_in_empty_matrix_mult_array_method_result_negative_body_history.pine",
    );
}

#[test]
fn accepts_supported_for_in_empty_matrix_mult_scalar_result_negative_body_history_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_for_in_empty_matrix_mult_scalar_result_negative_body_history.pine",
    );
}

#[test]
fn accepts_supported_for_in_empty_matrix_mult_left_scalar_result_negative_body_history_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_for_in_empty_matrix_mult_left_scalar_result_negative_body_history.pine",
    );
}

#[test]
fn accepts_supported_for_in_empty_matrix_mult_scalar_method_result_negative_body_history_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_for_in_empty_matrix_mult_scalar_method_result_negative_body_history.pine",
    );
}

#[test]
fn accepts_supported_for_in_empty_matrix_pow_result_negative_body_history_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_for_in_empty_matrix_pow_result_negative_body_history.pine",
    );
}

#[test]
fn accepts_supported_for_in_empty_matrix_pow_method_result_negative_body_history_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_for_in_empty_matrix_pow_method_result_negative_body_history.pine",
    );
}

#[test]
fn accepts_supported_for_in_empty_matrix_diff_result_negative_body_history_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_for_in_empty_matrix_diff_result_negative_body_history.pine",
    );
}

#[test]
fn accepts_supported_for_in_empty_matrix_diff_method_result_negative_body_history_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_for_in_empty_matrix_diff_method_result_negative_body_history.pine",
    );
}

#[test]
fn accepts_supported_for_in_empty_matrix_diff_scalar_result_negative_body_history_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_for_in_empty_matrix_diff_scalar_result_negative_body_history.pine",
    );
}

#[test]
fn accepts_supported_for_in_empty_matrix_diff_left_scalar_result_negative_body_history_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_for_in_empty_matrix_diff_left_scalar_result_negative_body_history.pine",
    );
}

#[test]
fn accepts_supported_for_in_empty_matrix_diff_scalar_method_result_negative_body_history_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_for_in_empty_matrix_diff_scalar_method_result_negative_body_history.pine",
    );
}

#[test]
fn reports_unsupported_for_in_array_new_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_array_new_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_array_new_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_str_split_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_str_split_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_str_split_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_ta_pivot_point_levels_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_ta_pivot_point_levels_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_ta_pivot_point_levels_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_array_new_named_size_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_array_new_named_size_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_array_new_named_size_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_array_copy_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_array_copy_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_array_copy_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_array_copy_method_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_array_copy_method_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_array_copy_method_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_array_concat_left_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_array_concat_left_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_array_concat_left_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_array_concat_named_right_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_array_concat_named_right_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_array_concat_named_right_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_array_concat_method_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_array_concat_method_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_array_concat_method_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_array_slice_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_array_slice_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_array_slice_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_array_slice_named_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_array_slice_named_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_array_slice_named_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_array_slice_method_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_array_slice_method_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_array_slice_method_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_array_abs_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_array_abs_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_array_abs_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_array_abs_named_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_array_abs_named_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_array_abs_named_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_array_abs_method_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_array_abs_method_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_array_abs_method_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_array_standardize_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_array_standardize_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_array_standardize_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_array_standardize_named_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_array_standardize_named_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_array_standardize_named_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_array_standardize_method_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_array_standardize_method_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_array_standardize_method_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_array_sort_indices_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_array_sort_indices_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_array_sort_indices_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_array_sort_indices_named_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_array_sort_indices_named_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_array_sort_indices_named_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_array_sort_indices_method_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_array_sort_indices_method_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_array_sort_indices_method_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_new_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_new_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_new_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_new_named_rows_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_new_named_rows_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_new_named_rows_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_copy_named_id_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_copy_named_id_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_copy_named_id_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_copy_method_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_copy_method_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_copy_method_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_transpose_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_transpose_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_transpose_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_transpose_named_id_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_transpose_named_id_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_transpose_named_id_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_transpose_method_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_transpose_method_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_transpose_method_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_transpose_source_zero_rows_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_transpose_source_zero_rows_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_transpose_source_zero_rows_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_submatrix_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_submatrix_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_submatrix_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_submatrix_named_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_submatrix_named_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_submatrix_named_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_submatrix_method_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_submatrix_method_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_submatrix_method_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_row_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_row_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_row_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_row_named_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_row_named_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_row_named_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_row_method_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_row_method_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_row_method_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_col_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_col_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_col_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_col_named_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_col_named_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_col_named_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_col_method_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_col_method_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_col_method_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_eigenvalues_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_eigenvalues_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_eigenvalues_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_eigenvalues_named_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_eigenvalues_named_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_eigenvalues_named_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_eigenvalues_method_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_eigenvalues_method_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_eigenvalues_method_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_eigenvectors_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_eigenvectors_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_eigenvectors_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_eigenvectors_named_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_eigenvectors_named_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_eigenvectors_named_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_eigenvectors_method_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_eigenvectors_method_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_eigenvectors_method_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_inv_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_inv_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_inv_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_inv_named_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_inv_named_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_inv_named_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_inv_method_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_inv_method_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_inv_method_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_pinv_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_pinv_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_pinv_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_pinv_named_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_pinv_named_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_pinv_named_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_pinv_method_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_pinv_method_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_pinv_method_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_kron_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_kron_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_kron_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_kron_named_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_kron_named_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_kron_named_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_kron_method_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_kron_method_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_kron_method_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_mult_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_mult_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_mult_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_mult_named_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_mult_named_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_mult_named_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_mult_method_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_mult_method_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_mult_method_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_mult_array_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_mult_array_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_mult_array_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_mult_array_pair_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_mult_array_pair_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_mult_array_pair_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_mult_array_named_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_mult_array_named_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_mult_array_named_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_mult_left_array_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_mult_left_array_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_mult_left_array_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_mult_array_method_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_mult_array_method_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_mult_array_method_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_mult_scalar_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_mult_scalar_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_mult_scalar_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_mult_scalar_alias_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_mult_scalar_alias_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_mult_scalar_alias_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_mult_scalar_named_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_mult_scalar_named_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_mult_scalar_named_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_mult_left_scalar_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_mult_left_scalar_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_mult_left_scalar_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_mult_scalar_method_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_mult_scalar_method_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_mult_scalar_method_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_pow_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_pow_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_pow_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_pow_named_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_pow_named_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_pow_named_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_pow_method_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_pow_method_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_pow_method_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_diff_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_diff_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_diff_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_diff_named_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_diff_named_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_diff_named_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_diff_method_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_diff_method_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_diff_method_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_diff_scalar_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_diff_scalar_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_diff_scalar_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_diff_scalar_alias_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_diff_scalar_alias_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_diff_scalar_alias_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_diff_scalar_named_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_diff_scalar_named_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_diff_scalar_named_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_diff_left_scalar_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_diff_left_scalar_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_diff_left_scalar_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_matrix_diff_scalar_method_result_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_matrix_diff_scalar_method_result_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_matrix_diff_scalar_method_result_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_in_result_local_alias_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_in_result_local_alias_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_result_local_alias_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_result_tuple_alias_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_result_tuple_alias_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_result_tuple_alias_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_bool_condition_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_bool_condition_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_bool_condition_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_bool_condition_local_alias_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_bool_condition_local_alias_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_bool_condition_local_alias_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_int_selector_switch_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_int_selector_switch_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_int_selector_switch_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_float_selector_switch_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_float_selector_switch_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_float_selector_switch_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_bool_selector_switch_local_alias_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_bool_selector_switch_local_alias_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_bool_selector_switch_local_alias_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_string_selector_switch_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_string_selector_switch_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_string_selector_switch_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_color_selector_switch_local_alias_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_color_selector_switch_local_alias_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_color_selector_switch_local_alias_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_int_comparison_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_int_comparison_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_int_comparison_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_float_comparison_local_alias_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_float_comparison_local_alias_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_float_comparison_local_alias_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_bool_comparison_local_alias_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_bool_comparison_local_alias_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_bool_comparison_local_alias_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_string_comparison_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_string_comparison_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_string_comparison_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_color_comparison_local_alias_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_color_comparison_local_alias_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_color_comparison_local_alias_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn reports_unsupported_for_comparison_condition_switch_negative_history_fixture() {
    assert_unsupported_fixture(
        "tests/fixtures/sema/unsupported_for_comparison_condition_switch_negative_history.pine",
        "negative_history_offset",
        "non-negative",
    );
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_comparison_condition_switch_negative_history.pine",
        &[
            "`negative_history_offset` is not supported: history offsets must be non-negative in the current supported subset",
        ],
    );
}

#[test]
fn accepts_supported_max_bars_back_function_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_max_bars_back_function.pine");
}

#[test]
fn accepts_supported_max_bars_back_udf_length_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_max_bars_back_udf_length.pine");
}

#[test]
fn accepts_supported_imported_max_bars_back_udf_length_fixture() {
    assert_import_valid_fixture(
        "tests/fixtures/sema/supported_imported_max_bars_back_udf_length.pine",
    );
}

#[test]
fn accepts_supported_max_bars_back_named_const_length_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_max_bars_back_named_const_length.pine");
}

#[test]
fn accepts_supported_pure_const_call_semantics_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_pure_const_call_semantics.pine");
}

#[test]
fn accepts_supported_max_bars_back_alias_named_const_length_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_max_bars_back_alias_named_const_length.pine",
    );
}

#[test]
fn accepts_supported_max_bars_back_declaration_udf_length_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_max_bars_back_declaration_udf_length.pine");
}

#[test]
fn accepts_supported_imported_max_bars_back_declaration_udf_length_fixture() {
    assert_import_valid_fixture(
        "tests/fixtures/sema/supported_imported_max_bars_back_declaration_udf_length.pine",
    );
}

#[test]
fn accepts_supported_max_bars_back_declaration_alias_named_const_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_max_bars_back_declaration_alias_named_const.pine",
    );
}

#[test]
fn accepts_supported_strategy_max_bars_back_declaration_udf_length_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_strategy_max_bars_back_declaration_udf_length.pine",
    );
}

#[test]
fn accepts_supported_imported_strategy_max_bars_back_declaration_udf_length_fixture() {
    assert_import_valid_fixture(
        "tests/fixtures/sema/supported_imported_strategy_max_bars_back_declaration_udf_length.pine",
    );
}

#[test]
fn accepts_supported_strategy_max_bars_back_declaration_alias_named_const_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_strategy_max_bars_back_declaration_alias_named_const.pine",
    );
}

#[test]
fn accepts_supported_max_bars_back_variable_function_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_max_bars_back_variable_function.pine");
}

#[test]
fn accepts_supported_max_bars_back_repeated_function_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_max_bars_back_repeated_function.pine");
}

#[test]
fn accepts_supported_max_bars_back_named_function_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_max_bars_back_named_function.pine");
}

#[test]
fn accepts_supported_max_bars_back_derived_alias_function_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_max_bars_back_derived_alias_function.pine");
}

#[test]
fn accepts_supported_max_bars_back_expression_source_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_max_bars_back_expression_source.pine");
}

#[test]
fn reports_unsupported_max_bars_back_non_series_source_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_max_bars_back_non_series_source.pine",
        &["`max_bars_back` argument `source` expects series numeric, got input int"],
    );
}

#[test]
fn reports_unsupported_max_bars_back_non_const_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_max_bars_back_non_const_length.pine",
        &["`max_bars_back` argument `num` expects const int, got series int"],
    );
}

#[test]
fn reports_unsupported_max_bars_back_negative_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_max_bars_back_negative_length.pine",
        &["`max_bars_back` argument `num` must be non-negative"],
    );
}

#[test]
fn reports_unsupported_max_bars_back_pure_const_call_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_max_bars_back_pure_const_call_length.pine",
        &["`max_bars_back` argument `num` must be non-negative"],
    );
}

#[test]
fn reports_unsupported_max_bars_back_named_negative_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_max_bars_back_named_negative_length.pine",
        &["`max_bars_back` argument `num` must be non-negative"],
    );
}

#[test]
fn reports_unsupported_max_bars_back_overflow_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_max_bars_back_overflow_length.pine",
        &["`max_bars_back` argument `num` must fit in a 32-bit unsigned history bound"],
    );
}

#[test]
fn reports_unsupported_max_bars_back_pure_const_call_overflow_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_max_bars_back_pure_const_call_overflow_length.pine",
        &["`max_bars_back` argument `num` must fit in a 32-bit unsigned history bound"],
    );
}

#[test]
fn reports_unsupported_max_bars_back_named_overflow_length_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_max_bars_back_named_overflow_length.pine",
        &["`max_bars_back` argument `num` must fit in a 32-bit unsigned history bound"],
    );
}

#[test]
fn accepts_supported_max_bars_back_block_call_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_max_bars_back_block_call.pine");
}

#[test]
fn accepts_supported_max_bars_back_switch_block_call_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_max_bars_back_switch_block_call.pine");
}

#[test]
fn accepts_supported_max_bars_back_statement_switch_call_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_max_bars_back_statement_switch_call.pine");
}

#[test]
fn accepts_supported_max_bars_back_for_statement_call_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_max_bars_back_for_statement_call.pine");
}

#[test]
fn accepts_supported_max_bars_back_for_in_statement_call_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_max_bars_back_for_in_statement_call.pine");
}

#[test]
fn accepts_supported_max_bars_back_while_statement_call_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_max_bars_back_while_statement_call.pine");
}

#[test]
fn accepts_supported_max_bars_back_expression_block_call_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_max_bars_back_expression_block_call.pine");
}

#[test]
fn accepts_supported_max_bars_back_tuple_switch_expression_block_call_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_max_bars_back_tuple_switch_expression_block_call.pine",
    );
}

#[test]
fn accepts_supported_max_bars_back_if_expression_block_call_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_max_bars_back_if_expression_block_call.pine",
    );
}

#[test]
fn accepts_supported_max_bars_back_tuple_if_expression_block_call_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_max_bars_back_tuple_if_expression_block_call.pine",
    );
}

#[test]
fn accepts_supported_max_bars_back_call_argument_block_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_max_bars_back_call_argument_block.pine");
}

#[test]
fn accepts_supported_max_bars_back_block_result_call_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_max_bars_back_block_result_call.pine");
}

#[test]
fn accepts_supported_max_bars_back_loop_result_call_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_max_bars_back_loop_result_call.pine");
}

#[test]
fn accepts_supported_max_bars_back_for_in_while_result_call_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_max_bars_back_for_in_while_result_call.pine",
    );
}

#[test]
fn reports_unsupported_max_bars_back_declaration_value_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_max_bars_back_declaration_value.pine",
        &["declarations must be initialized with a value-producing expression"],
    );
}

#[test]
fn accepts_supported_typed_declaration_qualifiers_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_typed_declaration_qualifiers.pine");
}

#[test]
fn accepts_supported_typed_na_declaration_qualifier_reassignment_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_typed_na_declaration_qualifier_reassignment.pine",
    );
}

#[test]
fn accepts_supported_udf_qualifier_propagation_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_udf_qualifier_propagation.pine");
}

#[test]
fn accepts_supported_imported_udf_loop_qualifier_propagation_fixture() {
    assert_import_valid_fixture(
        "tests/fixtures/sema/supported_imported_udf_loop_qualifier_propagation.pine",
    );
}

#[test]
fn accepts_supported_method_qualifier_propagation_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_method_qualifier_propagation.pine");
}

#[test]
fn accepts_supported_local_constructor_method_receiver_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_local_constructor_method_receiver.pine");
}

#[test]
fn accepts_supported_const_condition_qualifier_narrowing_fixture() {
    assert_valid_fixture("tests/fixtures/sema/supported_const_condition_qualifier_narrowing.pine");
}

#[test]
fn accepts_supported_const_if_statement_reassignment_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_const_if_statement_reassignment_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_const_if_statement_reassignment_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_const_if_statement_reassignment_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn accepts_supported_const_if_expression_reassignment_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_const_if_expression_reassignment_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_const_if_expression_reassignment_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_const_if_expression_reassignment_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_udf_final_for_series_bound_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_udf_final_for_series_bound_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_method_final_for_series_bound_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_method_final_for_series_bound_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_udf_final_for_reassignment_series_bound_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_udf_final_for_reassignment_series_bound_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_method_final_for_reassignment_series_bound_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_method_final_for_reassignment_series_bound_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_udf_final_if_branch_for_series_bound_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_udf_final_if_branch_for_series_bound_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_method_final_if_branch_for_series_bound_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_method_final_if_branch_for_series_bound_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_method_switch_block_for_series_bound_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_method_switch_block_for_series_bound_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_udf_final_if_reassignment_series_condition_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_udf_final_if_reassignment_series_condition_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_method_final_if_reassignment_series_condition_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_method_final_if_reassignment_series_condition_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn accepts_supported_udf_final_if_const_reassignment_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_udf_final_if_const_reassignment_qualifier.pine",
    );
}

#[test]
fn accepts_supported_method_final_if_const_reassignment_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_method_final_if_const_reassignment_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_udf_final_if_const_reassignment_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_udf_final_if_const_reassignment_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_method_final_if_const_reassignment_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_method_final_if_const_reassignment_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn accepts_supported_udf_final_switch_const_reassignment_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_udf_final_switch_const_reassignment_qualifier.pine",
    );
}

#[test]
fn accepts_supported_method_final_switch_const_reassignment_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_method_final_switch_const_reassignment_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_udf_final_switch_const_reassignment_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_udf_final_switch_const_reassignment_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_method_final_switch_const_reassignment_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_method_final_switch_const_reassignment_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn accepts_supported_udf_final_selector_switch_numeric_color_const_reassignment_qualifier_fixture()
{
    assert_valid_fixture(
        "tests/fixtures/sema/supported_udf_final_selector_switch_numeric_color_const_reassignment_qualifier.pine",
    );
}

#[test]
fn accepts_supported_method_final_selector_switch_numeric_color_const_reassignment_qualifier_fixture()
 {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_method_final_selector_switch_numeric_color_const_reassignment_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_udf_final_selector_switch_numeric_color_const_reassignment_qualifier_fixture()
 {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_udf_final_selector_switch_numeric_color_const_reassignment_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_method_final_selector_switch_numeric_color_const_reassignment_qualifier_fixture()
 {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_method_final_selector_switch_numeric_color_const_reassignment_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_udf_final_switch_reassignment_series_condition_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_udf_final_switch_reassignment_series_condition_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_method_final_switch_reassignment_series_condition_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_method_final_switch_reassignment_series_condition_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_udf_final_selector_switch_reassignment_series_selector_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_udf_final_selector_switch_reassignment_series_selector_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_method_final_selector_switch_reassignment_series_selector_qualifier_fixture()
{
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_method_final_selector_switch_reassignment_series_selector_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn accepts_supported_const_switch_statement_reassignment_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_const_switch_statement_reassignment_qualifier.pine",
    );
}

#[test]
fn accepts_supported_const_selector_switch_statement_reassignment_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_const_selector_switch_statement_reassignment_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_const_switch_statement_reassignment_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_const_switch_statement_reassignment_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_const_selector_switch_statement_reassignment_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_const_selector_switch_statement_reassignment_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn accepts_supported_const_switch_expression_reassignment_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_const_switch_expression_reassignment_qualifier.pine",
    );
}

#[test]
fn accepts_supported_const_selector_switch_expression_reassignment_qualifier_fixture() {
    assert_valid_fixture(
        "tests/fixtures/sema/supported_const_selector_switch_expression_reassignment_qualifier.pine",
    );
}

#[test]
fn reports_unsupported_const_switch_expression_reassignment_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_const_switch_expression_reassignment_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_const_selector_switch_expression_reassignment_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_const_selector_switch_expression_reassignment_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_if_expression_branch_for_series_bound_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_if_expression_branch_for_series_bound_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_if_statement_reassignment_series_condition_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_if_statement_reassignment_series_condition_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_if_expression_reassignment_series_condition_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_if_expression_reassignment_series_condition_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_while_statement_reassignment_series_condition_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_while_statement_reassignment_series_condition_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_for_statement_reassignment_series_bound_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_statement_reassignment_series_bound_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_for_statement_series_step_counter_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_statement_series_step_counter_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_for_in_statement_reassignment_series_iterable_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_statement_reassignment_series_iterable_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_switch_statement_reassignment_series_condition_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_switch_statement_reassignment_series_condition_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_switch_expression_reassignment_series_condition_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_switch_expression_reassignment_series_condition_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_selector_switch_statement_reassignment_series_selector_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_selector_switch_statement_reassignment_series_selector_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_selector_switch_expression_reassignment_series_selector_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_selector_switch_expression_reassignment_series_selector_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_switch_block_for_series_bound_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_switch_block_for_series_bound_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_loop_expression_body_for_series_bound_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_loop_expression_body_for_series_bound_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_for_expression_reassignment_series_bound_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_expression_reassignment_series_bound_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_for_expression_series_step_counter_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_expression_series_step_counter_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_for_in_expression_reassignment_series_iterable_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_for_in_expression_reassignment_series_iterable_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_while_expression_body_series_condition_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_while_expression_body_series_condition_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_while_expression_reassignment_series_condition_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_while_expression_reassignment_series_condition_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_udf_for_in_series_iterable_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_udf_for_in_series_iterable_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_method_for_in_series_iterable_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_method_for_in_series_iterable_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_udf_final_for_in_reassignment_series_iterable_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_udf_final_for_in_reassignment_series_iterable_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_method_final_for_in_reassignment_series_iterable_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_method_final_for_in_reassignment_series_iterable_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_udf_while_series_condition_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_udf_while_series_condition_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_method_while_series_condition_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_method_while_series_condition_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_udf_final_while_reassignment_series_condition_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_udf_final_while_reassignment_series_condition_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_method_final_while_reassignment_series_condition_qualifier_fixture() {
    assert_diagnostic_messages(
        "tests/fixtures/sema/unsupported_method_final_while_reassignment_series_condition_qualifier.pine",
        &["`ta.ema` argument `length` expects simple integer-compatible, got series int"],
    );
}

#[test]
fn reports_unsupported_expression_depth_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_expression_depth.pine",
        "E_SEMA_EXPR_DEPTH",
    );
}

#[test]
fn reports_unsupported_recursive_function_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/unsupported_recursive_function.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_RECURSIVE_FUNCTION"),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn reports_unsupported_function_call_depth_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_function_call_depth.pine",
        "E_FUNCTION_CALL_DEPTH",
    );
}

#[test]
fn accepts_supported_block_statement_fixture() {
    let path = workspace_fixture("tests/fixtures/sema/supported_block_statements.pine");
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    for feature in ["if", "for"] {
        assert!(
            analysis
                .compatibility
                .supported
                .iter()
                .any(|supported| supported.feature == feature),
            "{} supported features: {:?}",
            path.display(),
            analysis.compatibility.supported
        );
    }
    assert!(analysis.hir.is_some());
}

#[test]
fn reports_unsupported_loop_control_break_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_loop_control_break.pine",
        "E_LOOP_CONTROL",
    );
}

#[test]
fn reports_unsupported_loop_control_continue_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_loop_control_continue.pine",
        "E_LOOP_CONTROL",
    );
}

#[test]
fn reports_unsupported_named_const_zero_for_loop_step_fixture() {
    assert_diagnostic_fixture(
        "tests/fixtures/sema/unsupported_named_const_zero_for_loop_step.pine",
        "E_LOOP_STEP",
    );
}

fn assert_unsupported_fixture(path: &str, feature: &str, reason: &str) {
    let path = workspace_fixture(path);
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.compatibility.unsupported.iter().any(
            |unsupported| unsupported.feature == feature && unsupported.reason.contains(reason)
        ),
        "{} unsupported features: {:?}",
        path.display(),
        analysis.compatibility.unsupported
    );
    assert!(analysis.hir.is_none());
}

fn assert_unsupported_features_fixture(path: &str, expected: &[(&str, &str)]) {
    let path = workspace_fixture(path);
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    for (feature, reason) in expected {
        assert!(
            analysis
                .compatibility
                .unsupported
                .iter()
                .any(|unsupported| unsupported.feature == *feature
                    && unsupported.reason.contains(reason)),
            "{} unsupported features: {:?}",
            path.display(),
            analysis.compatibility.unsupported
        );
        assert!(
            analysis.diagnostics.iter().any(|diagnostic| {
                diagnostic.code == "E_UNSUPPORTED_FEATURE"
                    && diagnostic.message.contains(feature)
                    && diagnostic.message.contains(reason)
            }),
            "{} diagnostics: {:?}",
            path.display(),
            analysis.diagnostics
        );
    }
    assert!(analysis.hir.is_none());
}

fn assert_valid_fixture(path: &str) {
    let path = workspace_fixture(path);
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

fn assert_diagnostic_fixture(path: &str, code: &str) {
    let path = workspace_fixture(path);
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == code),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

fn assert_diagnostic_messages(path: &str, messages: &[&str]) {
    let path = workspace_fixture(path);
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    for message in messages {
        assert!(
            analysis
                .diagnostics
                .iter()
                .any(|diagnostic| diagnostic.message.contains(message)),
            "{} diagnostics: {:?}",
            path.display(),
            analysis.diagnostics
        );
    }
    assert!(analysis.hir.is_none());
}

fn assert_exact_diagnostic_messages(path: &str, messages: &[&str]) {
    let path = workspace_fixture(path);
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);
    let actual = analysis
        .diagnostics
        .iter()
        .map(|diagnostic| diagnostic.message.as_str())
        .collect::<Vec<_>>();

    assert_eq!(actual, messages, "{} diagnostics changed", path.display());
    assert!(analysis.hir.is_none());
}

fn assert_diagnostic_count(path: &str, expected_count: usize) {
    let path = workspace_fixture(path);
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert_eq!(
        analysis.diagnostics.len(),
        expected_count,
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

fn assert_array_sort_id_message(path: &str, function_name: &str, array_type: &str) {
    let message = format!(
        "`{function_name}` argument `id` expects numeric/string array, got simple {array_type}"
    );
    assert_diagnostic_messages(path, &[&message]);
}

fn assert_array_numeric_id_message(path: &str, function_name: &str, array_type: &str) {
    let message =
        format!("`{function_name}` argument `id` expects numeric array, got simple {array_type}");
    assert_diagnostic_messages(path, &[&message]);
}

fn assert_array_numeric_pair_messages(path: &str, function_name: &str, array_type: &str) {
    let id1_message =
        format!("`{function_name}` argument `id1` expects numeric array, got simple {array_type}");
    let id2_message =
        format!("`{function_name}` argument `id2` expects numeric array, got simple {array_type}");
    assert_diagnostic_messages(path, &[&id1_message, &id2_message]);
}

fn assert_array_udt_value_identity_message(path: &str, function_name: &str) {
    let message = format!("`{function_name}` argument `value` expects UDT `Point`, got `Other`");
    assert_diagnostic_messages(path, &[&message]);
}

fn assert_array_udt_marker_value_identity_message(path: &str, function_name: &str) {
    let message = format!("`{function_name}` argument `value` expects UDT `Point`, got `Marker`");
    assert_diagnostic_messages(path, &[&message]);
}

const UDT_ARRAY_HELPER_ALLOW_LIST_MESSAGE: &str = "`array.*` helper does not support UDT arrays except `array.size`, `array.get`, `array.set`, `array.push`, `array.insert`, `array.pop`, `array.remove`, `array.shift`, `array.unshift`, `array.first`, `array.last`, `array.fill`, `array.clear`, `array.copy`, `array.concat`, `array.slice`, `array.reverse`, `array.join`, `array.includes`, `array.indexof`, and `array.lastindexof`";

fn assert_array_unsupported_udt_numeric_id_message(path: &str, function_name: &str) {
    let id_message =
        format!("`{function_name}` argument `id` expects numeric array, got simple array<UDT>");
    assert_diagnostic_messages(path, &[&id_message, UDT_ARRAY_HELPER_ALLOW_LIST_MESSAGE]);
}

fn assert_array_unsupported_udt_numeric_pair_messages(path: &str, function_name: &str) {
    let id1_message =
        format!("`{function_name}` argument `id1` expects numeric array, got simple array<UDT>");
    let id2_message =
        format!("`{function_name}` argument `id2` expects numeric array, got simple array<UDT>");
    assert_diagnostic_messages(
        path,
        &[
            &id1_message,
            &id2_message,
            UDT_ARRAY_HELPER_ALLOW_LIST_MESSAGE,
        ],
    );
}

fn assert_array_unsupported_udt_numeric_bool_id_message(path: &str, function_name: &str) {
    let id_message = format!(
        "`{function_name}` argument `id` expects numeric/bool array, got simple array<UDT>"
    );
    assert_diagnostic_messages(path, &[&id_message, UDT_ARRAY_HELPER_ALLOW_LIST_MESSAGE]);
}

fn assert_array_binary_search_udt_message(path: &str, function_name: &str) {
    let id_message =
        format!("`{function_name}` argument `id` expects numeric array, got simple array<UDT>");
    assert_diagnostic_messages(path, &[&id_message, UDT_ARRAY_HELPER_ALLOW_LIST_MESSAGE]);
}

fn assert_array_numeric_bool_id_message(path: &str, function_name: &str, array_type: &str) {
    let message = format!(
        "`{function_name}` argument `id` expects numeric/bool array, got simple {array_type}"
    );
    assert_diagnostic_messages(path, &[&message]);
}

fn assert_matrix_id_message(path: &str, function_name: &str, actual_type: &str) {
    let message = format!("`{function_name}` argument `id` expects matrix, got {actual_type}");
    assert_diagnostic_messages(path, &[&message]);
}

fn assert_numeric_matrix_id_message(path: &str, function_name: &str, actual_type: &str) {
    let message =
        format!("`{function_name}` argument `id` expects numeric matrix, got {actual_type}");
    assert_diagnostic_messages(path, &[&message]);
}

fn assert_call_arg_message(
    path: &str,
    function_name: &str,
    argument_name: &str,
    expected_type: &str,
    actual_type: &str,
) {
    let message = format!(
        "`{function_name}` argument `{argument_name}` expects {expected_type}, got {actual_type}"
    );
    assert_diagnostic_messages(path, &[&message]);
}

fn assert_import_diagnostic_fixture(path: &str, code: &str) {
    let path = workspace_fixture(path);
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let library_path = workspace_fixture("tests/fixtures/libraries/import_udt_lib.pine");
    let library_text =
        fs::read_to_string(&library_path).expect("library fixture should be readable");
    let library_source = SourceFile::new(library_path.display().to_string(), library_text);
    let input = AnalysisInput::with_library_sources(
        source,
        vec![("user/udt/1".to_owned(), library_source)],
    )
    .expect("library fixture input should be valid");
    let analysis = analyze_input(&input);

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == code),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

fn assert_import_valid_fixture(path: &str) {
    let path = workspace_fixture(path);
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let library_path = workspace_fixture("tests/fixtures/libraries/import_udt_lib.pine");
    let library_text =
        fs::read_to_string(&library_path).expect("library fixture should be readable");
    let library_source = SourceFile::new(library_path.display().to_string(), library_text);
    let input = AnalysisInput::with_library_sources(
        source,
        vec![("user/udt/1".to_owned(), library_source)],
    )
    .expect("library fixture input should be valid");
    let analysis = analyze_input(&input);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(analysis.hir.is_some());
}

fn assert_import_diagnostic_messages(path: &str, messages: &[&str]) {
    let path = workspace_fixture(path);
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let library_path = workspace_fixture("tests/fixtures/libraries/import_udt_lib.pine");
    let library_text =
        fs::read_to_string(&library_path).expect("library fixture should be readable");
    let library_source = SourceFile::new(library_path.display().to_string(), library_text);
    let input = AnalysisInput::with_library_sources(
        source,
        vec![("user/udt/1".to_owned(), library_source)],
    )
    .expect("library fixture input should be valid");
    let analysis = analyze_input(&input);

    for message in messages {
        assert!(
            analysis
                .diagnostics
                .iter()
                .any(|diagnostic| diagnostic.message == *message),
            "{} diagnostics: {:?}",
            path.display(),
            analysis.diagnostics
        );
    }
    assert!(analysis.hir.is_none());
}

fn assert_import_diagnostic_count(path: &str, expected_count: usize) {
    let path = workspace_fixture(path);
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let library_path = workspace_fixture("tests/fixtures/libraries/import_udt_lib.pine");
    let library_text =
        fs::read_to_string(&library_path).expect("library fixture should be readable");
    let library_source = SourceFile::new(library_path.display().to_string(), library_text);
    let input = AnalysisInput::with_library_sources(
        source,
        vec![("user/udt/1".to_owned(), library_source)],
    )
    .expect("library fixture input should be valid");
    let analysis = analyze_input(&input);

    assert_eq!(
        analysis.diagnostics.len(),
        expected_count,
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

fn assert_import_diagnostic_messages_with_library(
    path: &str,
    library_key: &str,
    library_fixture: &str,
    messages: &[&str],
) {
    let path = workspace_fixture(path);
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let library_path = workspace_fixture(library_fixture);
    let library_text =
        fs::read_to_string(&library_path).expect("library fixture should be readable");
    let library_source = SourceFile::new(library_path.display().to_string(), library_text);
    let input =
        AnalysisInput::with_library_sources(source, vec![(library_key.to_owned(), library_source)])
            .expect("library fixture input should be valid");
    let analysis = analyze_input(&input);

    for message in messages {
        assert!(
            analysis
                .diagnostics
                .iter()
                .any(|diagnostic| diagnostic.message == *message),
            "{} diagnostics: {:?}",
            path.display(),
            analysis.diagnostics
        );
    }
    assert!(analysis.hir.is_none());
}

fn assert_import_diagnostic_count_with_library(
    path: &str,
    library_key: &str,
    library_fixture: &str,
    expected_count: usize,
) {
    let path = workspace_fixture(path);
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let library_path = workspace_fixture(library_fixture);
    let library_text =
        fs::read_to_string(&library_path).expect("library fixture should be readable");
    let library_source = SourceFile::new(library_path.display().to_string(), library_text);
    let input =
        AnalysisInput::with_library_sources(source, vec![(library_key.to_owned(), library_source)])
            .expect("library fixture input should be valid");
    let analysis = analyze_input(&input);

    assert_eq!(
        analysis.diagnostics.len(),
        expected_count,
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

fn assert_import_unsupported_fixture_with_library(
    path: &str,
    library_key: &str,
    library_fixture: &str,
    feature: &str,
    reason: &str,
) {
    let path = workspace_fixture(path);
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let library_path = workspace_fixture(library_fixture);
    let library_text =
        fs::read_to_string(&library_path).expect("library fixture should be readable");
    let library_source = SourceFile::new(library_path.display().to_string(), library_text);
    let input =
        AnalysisInput::with_library_sources(source, vec![(library_key.to_owned(), library_source)])
            .expect("library fixture input should be valid");
    let analysis = analyze_input(&input);

    assert!(
        analysis.compatibility.unsupported.iter().any(
            |unsupported| unsupported.feature == feature && unsupported.reason.contains(reason)
        ),
        "{} unsupported features: {:?}; diagnostics: {:?}",
        path.display(),
        analysis.compatibility.unsupported,
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

fn assert_import_ok_fixture_with_library(path: &str, library_key: &str, library_fixture: &str) {
    let path = workspace_fixture(path);
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let library_path = workspace_fixture(library_fixture);
    let library_text =
        fs::read_to_string(&library_path).expect("library fixture should be readable");
    let library_source = SourceFile::new(library_path.display().to_string(), library_text);
    let input =
        AnalysisInput::with_library_sources(source, vec![(library_key.to_owned(), library_source)])
            .expect("library fixture input should be valid");
    let analysis = analyze_input(&input);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(
        analysis.compatibility.unsupported.is_empty(),
        "{} unsupported features: {:?}",
        path.display(),
        analysis.compatibility.unsupported
    );
    assert!(analysis.hir.is_some());
}

fn assert_import_ok_fixture(path: &str) {
    let path = workspace_fixture(path);
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let library_path = workspace_fixture("tests/fixtures/libraries/import_udt_lib.pine");
    let library_text =
        fs::read_to_string(&library_path).expect("library fixture should be readable");
    let library_source = SourceFile::new(library_path.display().to_string(), library_text);
    let input = AnalysisInput::with_library_sources(
        source,
        vec![("user/udt/1".to_owned(), library_source)],
    )
    .expect("library fixture input should be valid");
    let analysis = analyze_input(&input);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

fn assert_strategy_unsupported_fixture(path: &str, features: &[&str]) {
    let path = workspace_fixture(path);
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    for feature in features {
        let expected_reasons: &[&str] = if feature.starts_with("strategy.risk.") {
            &["broker risk rules"]
        } else {
            &["strategy.order", "broker emulation"]
        };
        for expected_reason in expected_reasons {
            assert!(
                analysis
                    .compatibility
                    .unsupported
                    .iter()
                    .any(|unsupported| unsupported.feature == *feature
                        && unsupported.reason.contains(expected_reason)),
                "{} unsupported features: {:?}",
                path.display(),
                analysis.compatibility.unsupported
            );
        }
    }
    assert!(
        analysis
            .diagnostics
            .iter()
            .all(|diagnostic| diagnostic.code != "E_UNKNOWN_FUNCTION"),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

fn assert_strategy_state_mode_fixture(path: &str) {
    let path = workspace_fixture(path);
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);
    let variables = [
        "strategy.position_size",
        "strategy.position_avg_price",
        "strategy.openprofit",
        "strategy.netprofit",
        "strategy.equity",
        "strategy.buy_and_hold_return_percent",
        "strategy.closedtrades",
        "strategy.wintrades",
        "strategy.losstrades",
        "strategy.eventrades",
        "strategy.opentrades",
        "strategy.margin_liquidation_price",
    ];

    for variable in variables {
        assert!(
            analysis.diagnostics.iter().any(|diagnostic| {
                diagnostic.code == "E_STRATEGY_MODE" && diagnostic.message.contains(variable)
            }),
            "{} diagnostics: {:?}",
            path.display(),
            analysis.diagnostics
        );
    }
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(analysis.hir.is_none());
}

fn assert_strategy_state_supported_fixture(path: &str, variables: &[&str]) {
    let path = workspace_fixture(path);
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_source(&source);

    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    for variable in variables {
        assert!(
            analysis
                .compatibility
                .supported
                .iter()
                .any(|supported| supported.feature == *variable),
            "{} supported features: {:?}",
            path.display(),
            analysis.compatibility.supported
        );
    }
    assert!(analysis.hir.is_some());
}
