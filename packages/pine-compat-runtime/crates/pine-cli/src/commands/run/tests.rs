use super::*;
use std::path::PathBuf;

fn workspace_path(path: &str) -> String {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .join(path)
        .display()
        .to_string()
}

#[test]
fn parses_request_bars_spec_with_exchange_prefixed_symbol() {
    let spec = parse_request_bars_spec("NASDAQ:AAPL:1=request.csv")
        .expect("request bars spec should parse");

    assert_eq!(spec.key.symbol(), "NASDAQ:AAPL");
    assert_eq!(spec.key.timeframe().value(), "1");
    assert_eq!(spec.path, "request.csv");
}

#[test]
fn parses_run_options_with_library_source() {
    let options = parse_options(&[
        "script.pine".to_owned(),
        "--bars".to_owned(),
        "bars.csv".to_owned(),
        "--library-source".to_owned(),
        "user/lib/1=lib.pine".to_owned(),
    ])
    .expect("run options");

    assert_eq!(options.path, "script.pine");
    assert_eq!(options.bars_path, "bars.csv");
    assert_eq!(options.library_sources.len(), 1);
    assert_eq!(options.library_sources[0].key, "user/lib/1");
    assert_eq!(options.library_sources[0].path, "lib.pine");
    assert!(options.input_overrides.is_empty());
    assert!(options.strategy_alert_template.is_none());
    assert!(options.strategy_running_alert.is_none());
}

#[test]
fn parses_run_options_with_input_overrides() {
    let options = parse_options(&[
        "script.pine".to_owned(),
        "--bars".to_owned(),
        "bars.csv".to_owned(),
        "--input-override".to_owned(),
        "12=5".to_owned(),
        "--input-override".to_owned(),
        "13=#4CAF50".to_owned(),
    ])
    .expect("run options");

    assert_eq!(options.input_overrides.len(), 2);
    assert_eq!(options.input_overrides[0].call_site_id, 12);
    assert_eq!(options.input_overrides[0].value, "5");
    assert_eq!(options.input_overrides[1].call_site_id, 13);
    assert_eq!(options.input_overrides[1].value, "#4CAF50");
}

#[test]
fn parses_run_options_with_strategy_alert_template() {
    let options = parse_options(&[
        "script.pine".to_owned(),
        "--bars".to_owned(),
        "bars.csv".to_owned(),
        "--render-strategy-order-alert-template".to_owned(),
        "Order: {{strategy.order.alert_message}}".to_owned(),
        "--strategy-alert-index".to_owned(),
        "1".to_owned(),
    ])
    .expect("run options");
    let template = options
        .strategy_alert_template
        .as_ref()
        .expect("strategy alert template");

    assert_eq!(template.template, "Order: {{strategy.order.alert_message}}");
    assert_eq!(template.index, 1);
    assert!(options.strategy_running_alert.is_none());
}

#[test]
fn parses_run_options_with_strategy_running_alert() {
    let options = parse_options(&[
        "script.pine".to_owned(),
        "--bars".to_owned(),
        "bars.csv".to_owned(),
        "--render-strategy-running-alert".to_owned(),
        "Running: {{strategy.order.alert_message}}".to_owned(),
        "--strategy-alert-index".to_owned(),
        "1".to_owned(),
        "--running-alert-script-snapshot-id".to_owned(),
        "snapshot-1".to_owned(),
        "--running-alert-symbol".to_owned(),
        "NASDAQ:AAPL".to_owned(),
        "--running-alert-timeframe".to_owned(),
        "60".to_owned(),
    ])
    .expect("run options");
    let running_alert = options
        .strategy_running_alert
        .as_ref()
        .expect("strategy running alert");

    assert!(options.strategy_alert_template.is_none());
    assert_eq!(running_alert.index, 1);
    assert_eq!(running_alert.config.script_snapshot_id, "snapshot-1");
    assert_eq!(running_alert.config.symbol, "NASDAQ:AAPL");
    assert_eq!(running_alert.config.timeframe, "60");
    assert_eq!(
        running_alert.config.message_template,
        "Running: {{strategy.order.alert_message}}"
    );
}

#[test]
fn rejects_partial_strategy_alert_template_options() {
    let error = parse_options(&[
        "script.pine".to_owned(),
        "--bars".to_owned(),
        "bars.csv".to_owned(),
        "--render-strategy-order-alert-template".to_owned(),
        "{{strategy.order.alert_message}}".to_owned(),
    ])
    .expect_err("strategy alert index is required");

    assert!(error.contains("usage: pine-compat"));
}

#[test]
fn rejects_partial_strategy_running_alert_options() {
    let error = parse_options(&[
        "script.pine".to_owned(),
        "--bars".to_owned(),
        "bars.csv".to_owned(),
        "--render-strategy-running-alert".to_owned(),
        "{{strategy.order.alert_message}}".to_owned(),
        "--strategy-alert-index".to_owned(),
        "0".to_owned(),
        "--running-alert-script-snapshot-id".to_owned(),
        "snapshot-1".to_owned(),
    ])
    .expect_err("running alert symbol and timeframe are required");

    assert!(error.contains("usage: pine-compat"));
}

#[test]
fn rejects_mixed_strategy_alert_rendering_options() {
    let error = parse_options(&[
        "script.pine".to_owned(),
        "--bars".to_owned(),
        "bars.csv".to_owned(),
        "--render-strategy-order-alert-template".to_owned(),
        "{{strategy.order.alert_message}}".to_owned(),
        "--render-strategy-running-alert".to_owned(),
        "{{strategy.order.alert_message}}".to_owned(),
        "--strategy-alert-index".to_owned(),
        "0".to_owned(),
        "--running-alert-script-snapshot-id".to_owned(),
        "snapshot-1".to_owned(),
        "--running-alert-symbol".to_owned(),
        "NASDAQ:AAPL".to_owned(),
        "--running-alert-timeframe".to_owned(),
        "60".to_owned(),
    ])
    .expect_err("only one alert rendering mode is allowed");

    assert!(error.contains("usage: pine-compat"));
}

#[test]
fn builds_request_environment_from_csv_specs() {
    let path = std::env::temp_dir().join(format!(
        "pine-request-bars-{}-{}.csv",
        std::process::id(),
        std::thread::current().name().unwrap_or("test")
    ));
    fs::write(&path, "time,open,high,low,close,volume\n0,10,11,9,12,100\n")
        .expect("write request bars");
    let spec = parse_request_bars_spec(&format!("NYSE:IBM:1={}", path.display()))
        .expect("request bars spec");

    let environment =
        request_environment_from_specs(&[spec]).expect("request environment from CSV");
    let bars = environment
        .provider()
        .bars(&RequestKey::new("NYSE:IBM", RequestTimeframe::default()))
        .expect("request bars");

    assert_eq!(bars[0].close, 12.0);
    let _ = fs::remove_file(path);
}

#[test]
fn duplicate_request_bars_keys_fail() {
    let path = std::env::temp_dir().join(format!(
        "pine-request-bars-duplicate-{}.csv",
        std::process::id()
    ));
    fs::write(&path, "time,open,high,low,close,volume\n0,1,1,1,1,1\n").expect("write request bars");
    let first = parse_request_bars_spec(&format!("NYSE:IBM:1={}", path.display()))
        .expect("first request bars spec");
    let second = parse_request_bars_spec(&format!("NYSE:IBM:1={}", path.display()))
        .expect("second request bars spec");

    let error = match request_environment_from_specs(&[first, second]) {
        Ok(_) => panic!("duplicate request bars should fail"),
        Err(error) => error,
    };

    assert!(error.contains("duplicate request data for symbol `NYSE:IBM` timeframe `1`"));
    let _ = fs::remove_file(path);
}

#[test]
fn runs_input_overrides_integration_fixture() {
    let script = std::env::temp_dir().join(format!(
        "pine-input-overrides-{}-{}.pine",
        std::process::id(),
        line!()
    ));
    fs::write(
        &script,
        r##"indicator("input overrides")
length = input.int(2, "Length")
scale = input.float(1.0, "Scale")
enabled = input.bool(true, "Enabled")
mode = input.string("SMA", "Mode")
shade = input.color(color.red, "Shade")
base = enabled and mode == "SMA" ? ta.sma(close, length) * scale : open
plot(base)
plot(color.r(shade))
"##,
    )
    .expect("write input override script");
    let input = analysis_input_from_paths(&script.to_string_lossy(), &[])
        .expect("analysis input from script");
    let analysis = analyze_input(&input);
    let hir = analysis.hir.expect("HIR");
    let input_ids = input_calls(&hir)
        .into_iter()
        .filter_map(|input| input.title.map(|title| (title, input.call_site_id)))
        .collect::<HashMap<_, _>>();
    let input_override_specs = vec![
        parse_input_override_spec(&format!("{}=1", input_ids["Length"])).expect("length override"),
        parse_input_override_spec(&format!("{}=2.0", input_ids["Scale"])).expect("scale override"),
        parse_input_override_spec(&format!("{}=true", input_ids["Enabled"]))
            .expect("enabled override"),
        parse_input_override_spec(&format!("{}=SMA", input_ids["Mode"])).expect("mode override"),
        parse_input_override_spec(&format!("{}=#4CAF50", input_ids["Shade"]))
            .expect("shade override"),
    ];
    let options = RunOptions {
        path: script.to_string_lossy().into_owned(),
        bars_path: workspace_path("tests/fixtures/runtime/bars.csv"),
        profile: false,
        request_bars: Vec::new(),
        library_sources: Vec::new(),
        input_overrides: input_override_specs,
        strategy_alert_template: None,
        strategy_running_alert: None,
    };

    let output = run_json_with_options(&options).expect("input override output");

    assert!(output.contains("\"values\":[2,4,6,8]"));
    assert!(output.contains("\"values\":[76,76,76,76]"));

    let profile_options = RunOptions {
        path: script.to_string_lossy().into_owned(),
        bars_path: workspace_path("tests/fixtures/runtime/bars.csv"),
        profile: true,
        request_bars: Vec::new(),
        library_sources: Vec::new(),
        input_overrides: vec![
            parse_input_override_spec(&format!("{}=1", input_ids["Length"]))
                .expect("length override"),
            parse_input_override_spec(&format!("{}=2.0", input_ids["Scale"]))
                .expect("scale override"),
        ],
        strategy_alert_template: None,
        strategy_running_alert: None,
    };
    let profile_output =
        run_json_with_options(&profile_options).expect("profile input override output");

    assert!(profile_output.contains("\"values\":[2,4,6,8]"));
    let _ = fs::remove_file(script);
}

#[test]
fn profiled_run_reports_max_bars_back_without_retention_misses() {
    let options = RunOptions {
        path: workspace_path("tests/fixtures/profile/dynamic_history_max_bars_back.pine"),
        bars_path: workspace_path("tests/fixtures/runtime/bars.csv"),
        profile: true,
        request_bars: Vec::new(),
        library_sources: Vec::new(),
        input_overrides: Vec::new(),
        strategy_alert_template: None,
        strategy_running_alert: None,
    };

    let output = run_json_with_options(&options).expect("profile max_bars_back output");

    assert!(output.contains(r#""historyRetentionMode":"maxBarsBack""#));
    assert!(output.contains(r#""historyMaxBarsBack":32"#));
    assert!(output.contains(r#""historyHasDynamicOffsets":true"#));
    assert!(output.contains(r#""historyDynamicRetentionMisses":0"#));
    assert!(output.contains(r#""historyDynamicRetentionMaxMissedOffset":null"#));
}

#[test]
fn profiled_run_reports_max_bars_back_retention_misses() {
    let options = RunOptions {
        path: workspace_path("tests/fixtures/profile/dynamic_history_max_bars_back_miss.pine"),
        bars_path: workspace_path("tests/fixtures/runtime/bars.csv"),
        profile: true,
        request_bars: Vec::new(),
        library_sources: Vec::new(),
        input_overrides: Vec::new(),
        strategy_alert_template: None,
        strategy_running_alert: None,
    };

    let output = run_json_with_options(&options).expect("profile max_bars_back miss output");

    assert!(output.contains(r#""historyRetentionMode":"maxBarsBack""#));
    assert!(output.contains(r#""historyMaxBarsBack":2"#));
    assert!(output.contains(r#""historyHasDynamicOffsets":true"#));
    assert!(output.contains(r#""historyDynamicRetentionMisses":3"#));
    assert!(output.contains(r#""historyDynamicRetentionMaxMissedOffset":3"#));
}

#[test]
fn profiled_run_reports_udf_max_bars_back_retention_misses() {
    let options = RunOptions {
        path: workspace_path("tests/fixtures/profile/dynamic_history_udf_max_bars_back_miss.pine"),
        bars_path: workspace_path("tests/fixtures/runtime/bars.csv"),
        profile: true,
        request_bars: Vec::new(),
        library_sources: Vec::new(),
        input_overrides: Vec::new(),
        strategy_alert_template: None,
        strategy_running_alert: None,
    };

    let output = run_json_with_options(&options).expect("profile UDF max_bars_back miss output");

    assert!(output.contains(r#""historyRetentionMode":"maxBarsBack""#));
    assert!(output.contains(r#""historyMaxBarsBack":2"#));
    assert!(output.contains(r#""historyHasDynamicOffsets":true"#));
    assert!(output.contains(r#""historyDynamicRetentionMisses":3"#));
    assert!(output.contains(r#""historyDynamicRetentionMaxMissedOffset":3"#));
}

fn assert_profile_series_max_bars_back_miss(path: &str, context: &str) {
    assert_profile_series_max_bars_back_miss_with_libraries(path, context, Vec::new());
}

fn imported_udt_library_source() -> LibrarySourceSpec {
    LibrarySourceSpec {
        key: "user/udt/1".to_owned(),
        path: workspace_path("tests/fixtures/libraries/import_udt_lib.pine"),
    }
}

fn assert_profile_series_max_bars_back_miss_with_libraries(
    path: &str,
    context: &str,
    library_sources: Vec<LibrarySourceSpec>,
) {
    let options = RunOptions {
        path: workspace_path(path),
        bars_path: workspace_path("tests/fixtures/runtime/bars.csv"),
        profile: true,
        request_bars: Vec::new(),
        library_sources,
        input_overrides: Vec::new(),
        strategy_alert_template: None,
        strategy_running_alert: None,
    };

    let output = run_json_with_options(&options)
        .unwrap_or_else(|err| panic!("profile {context} output: {err}"));

    assert!(output.contains(r#""historyRetentionMode":"maxBarsBack""#));
    assert!(output.contains(r#""historyMaxBarsBack":10"#));
    assert!(output.contains(r#""historyDynamicRetentionMisses":3"#));
    assert!(output.contains(
        r#""diagnostics":[{"code":"W_HISTORY_MAX_BARS_BACK","message":"dynamic history offsets exceeded max_bars_back=2; 3 reads returned na, maximum requested offset was 3"}]"#
    ));
}

#[test]
fn profiled_run_reports_effective_series_max_bars_back_diagnostic() {
    let options = RunOptions {
        path: workspace_path(
            "tests/fixtures/profile/dynamic_history_series_max_bars_back_miss.pine",
        ),
        bars_path: workspace_path("tests/fixtures/runtime/bars.csv"),
        profile: true,
        request_bars: Vec::new(),
        library_sources: Vec::new(),
        input_overrides: Vec::new(),
        strategy_alert_template: None,
        strategy_running_alert: None,
    };

    let output = run_json_with_options(&options).expect("profile series max_bars_back miss output");

    assert!(output.contains(r#""historyRetentionMode":"maxBarsBack""#));
    assert!(output.contains(r#""historyMaxBarsBack":10"#));
    assert!(output.contains(r#""historyDynamicRetentionMisses":3"#));
    assert!(output.contains(
        r#""diagnostics":[{"code":"W_HISTORY_MAX_BARS_BACK","message":"dynamic history offsets exceeded max_bars_back=2; 3 reads returned na, maximum requested offset was 3"}]"#
    ));
}

#[test]
fn profiled_run_reports_expression_source_series_max_bars_back_diagnostic() {
    let options = RunOptions {
        path: workspace_path(
            "tests/fixtures/profile/dynamic_history_series_max_bars_back_expression_source_miss.pine",
        ),
        bars_path: workspace_path("tests/fixtures/runtime/bars.csv"),
        profile: true,
        request_bars: Vec::new(),
        library_sources: Vec::new(),
        input_overrides: Vec::new(),
        strategy_alert_template: None,
        strategy_running_alert: None,
    };

    let output = run_json_with_options(&options)
        .expect("profile expression source series max_bars_back miss output");

    assert!(output.contains(r#""historyRetentionMode":"maxBarsBack""#));
    assert!(output.contains(r#""historyMaxBarsBack":10"#));
    assert!(output.contains(r#""historyDynamicRetentionMisses":3"#));
    assert!(output.contains(
        r#""diagnostics":[{"code":"W_HISTORY_MAX_BARS_BACK","message":"dynamic history offsets exceeded max_bars_back=2; 3 reads returned na, maximum requested offset was 3"}]"#
    ));
}

#[test]
fn profiled_run_reports_alias_expression_series_max_bars_back_diagnostic() {
    let options = RunOptions {
        path: workspace_path(
            "tests/fixtures/profile/dynamic_history_series_max_bars_back_alias_expression_miss.pine",
        ),
        bars_path: workspace_path("tests/fixtures/runtime/bars.csv"),
        profile: true,
        request_bars: Vec::new(),
        library_sources: Vec::new(),
        input_overrides: Vec::new(),
        strategy_alert_template: None,
        strategy_running_alert: None,
    };

    let output = run_json_with_options(&options)
        .expect("profile alias expression series max_bars_back miss output");

    assert!(output.contains(r#""historyRetentionMode":"maxBarsBack""#));
    assert!(output.contains(r#""historyMaxBarsBack":10"#));
    assert!(output.contains(r#""historyDynamicRetentionMisses":3"#));
    assert!(output.contains(
        r#""diagnostics":[{"code":"W_HISTORY_MAX_BARS_BACK","message":"dynamic history offsets exceeded max_bars_back=2; 3 reads returned na, maximum requested offset was 3"}]"#
    ));
}

#[test]
fn profiled_run_reports_ternary_expression_series_max_bars_back_diagnostic() {
    let options = RunOptions {
        path: workspace_path(
            "tests/fixtures/profile/dynamic_history_series_max_bars_back_ternary_expression_miss.pine",
        ),
        bars_path: workspace_path("tests/fixtures/runtime/bars.csv"),
        profile: true,
        request_bars: Vec::new(),
        library_sources: Vec::new(),
        input_overrides: Vec::new(),
        strategy_alert_template: None,
        strategy_running_alert: None,
    };

    let output = run_json_with_options(&options)
        .expect("profile ternary expression series max_bars_back miss output");

    assert!(output.contains(r#""historyRetentionMode":"maxBarsBack""#));
    assert!(output.contains(r#""historyMaxBarsBack":10"#));
    assert!(output.contains(r#""historyDynamicRetentionMisses":3"#));
    assert!(output.contains(
        r#""diagnostics":[{"code":"W_HISTORY_MAX_BARS_BACK","message":"dynamic history offsets exceeded max_bars_back=2; 3 reads returned na, maximum requested offset was 3"}]"#
    ));
}

#[test]
fn profiled_run_reports_qualified_builtin_ternary_series_max_bars_back_diagnostic() {
    let options = RunOptions {
        path: workspace_path(
            "tests/fixtures/profile/dynamic_history_series_max_bars_back_qualified_builtin_ternary_miss.pine",
        ),
        bars_path: workspace_path("tests/fixtures/runtime/bars.csv"),
        profile: true,
        request_bars: Vec::new(),
        library_sources: Vec::new(),
        input_overrides: Vec::new(),
        strategy_alert_template: None,
        strategy_running_alert: None,
    };

    let output = run_json_with_options(&options)
        .expect("profile qualified builtin ternary series max_bars_back miss output");

    assert!(output.contains(r#""historyRetentionMode":"maxBarsBack""#));
    assert!(output.contains(r#""historyMaxBarsBack":10"#));
    assert!(output.contains(r#""historyDynamicRetentionMisses":3"#));
    assert!(output.contains(
        r#""diagnostics":[{"code":"W_HISTORY_MAX_BARS_BACK","message":"dynamic history offsets exceeded max_bars_back=2; 3 reads returned na, maximum requested offset was 3"}]"#
    ));
}

#[test]
fn profiled_run_reports_pure_math_call_series_max_bars_back_diagnostic() {
    let options = RunOptions {
        path: workspace_path(
            "tests/fixtures/profile/dynamic_history_series_max_bars_back_pure_math_call_miss.pine",
        ),
        bars_path: workspace_path("tests/fixtures/runtime/bars.csv"),
        profile: true,
        request_bars: Vec::new(),
        library_sources: Vec::new(),
        input_overrides: Vec::new(),
        strategy_alert_template: None,
        strategy_running_alert: None,
    };

    let output = run_json_with_options(&options)
        .expect("profile pure math call series max_bars_back miss output");

    assert!(output.contains(r#""historyRetentionMode":"maxBarsBack""#));
    assert!(output.contains(r#""historyMaxBarsBack":10"#));
    assert!(output.contains(r#""historyDynamicRetentionMisses":3"#));
    assert!(output.contains(
        r#""diagnostics":[{"code":"W_HISTORY_MAX_BARS_BACK","message":"dynamic history offsets exceeded max_bars_back=2; 3 reads returned na, maximum requested offset was 3"}]"#
    ));
}

#[test]
fn profiled_run_reports_named_pure_math_call_series_max_bars_back_diagnostic() {
    let options = RunOptions {
        path: workspace_path(
            "tests/fixtures/profile/dynamic_history_series_max_bars_back_named_pure_math_call_miss.pine",
        ),
        bars_path: workspace_path("tests/fixtures/runtime/bars.csv"),
        profile: true,
        request_bars: Vec::new(),
        library_sources: Vec::new(),
        input_overrides: Vec::new(),
        strategy_alert_template: None,
        strategy_running_alert: None,
    };

    let output = run_json_with_options(&options)
        .expect("profile named pure math call series max_bars_back miss output");

    assert!(output.contains(r#""historyRetentionMode":"maxBarsBack""#));
    assert!(output.contains(r#""historyMaxBarsBack":10"#));
    assert!(output.contains(r#""historyDynamicRetentionMisses":3"#));
    assert!(output.contains(
        r#""diagnostics":[{"code":"W_HISTORY_MAX_BARS_BACK","message":"dynamic history offsets exceeded max_bars_back=2; 3 reads returned na, maximum requested offset was 3"}]"#
    ));
}

#[test]
fn profiled_run_reports_numeric_cast_series_max_bars_back_diagnostic() {
    let options = RunOptions {
        path: workspace_path(
            "tests/fixtures/profile/dynamic_history_series_max_bars_back_numeric_cast_miss.pine",
        ),
        bars_path: workspace_path("tests/fixtures/runtime/bars.csv"),
        profile: true,
        request_bars: Vec::new(),
        library_sources: Vec::new(),
        input_overrides: Vec::new(),
        strategy_alert_template: None,
        strategy_running_alert: None,
    };

    let output = run_json_with_options(&options)
        .expect("profile numeric cast series max_bars_back miss output");

    assert!(output.contains(r#""historyRetentionMode":"maxBarsBack""#));
    assert!(output.contains(r#""historyMaxBarsBack":10"#));
    assert!(output.contains(r#""historyDynamicRetentionMisses":3"#));
    assert!(output.contains(
        r#""diagnostics":[{"code":"W_HISTORY_MAX_BARS_BACK","message":"dynamic history offsets exceeded max_bars_back=2; 3 reads returned na, maximum requested offset was 3"}]"#
    ));
}

#[test]
fn profiled_run_reports_value_helper_series_max_bars_back_diagnostics() {
    for (path, context) in [
        (
            "tests/fixtures/profile/dynamic_history_series_max_bars_back_nz_call_miss.pine",
            "nz call series max_bars_back miss",
        ),
        (
            "tests/fixtures/profile/dynamic_history_series_max_bars_back_named_reordered_nz_call_miss.pine",
            "named reordered nz call series max_bars_back miss",
        ),
        (
            "tests/fixtures/profile/dynamic_history_series_max_bars_back_fixnan_call_miss.pine",
            "fixnan call series max_bars_back miss",
        ),
    ] {
        assert_profile_series_max_bars_back_miss(path, context);
    }
}

#[test]
fn profiled_run_reports_string_numeric_source_series_max_bars_back_diagnostics() {
    for (path, context) in [
        (
            "tests/fixtures/profile/dynamic_history_series_max_bars_back_str_tonumber_call_miss.pine",
            "str.tonumber call series max_bars_back miss",
        ),
        (
            "tests/fixtures/profile/dynamic_history_series_max_bars_back_str_length_call_miss.pine",
            "str.length call series max_bars_back miss",
        ),
    ] {
        assert_profile_series_max_bars_back_miss(path, context);
    }
}

#[test]
fn profiled_run_reports_udf_length_series_max_bars_back_diagnostic() {
    let options = RunOptions {
        path: workspace_path(
            "tests/fixtures/profile/dynamic_history_series_max_bars_back_udf_length_miss.pine",
        ),
        bars_path: workspace_path("tests/fixtures/runtime/bars.csv"),
        profile: true,
        request_bars: Vec::new(),
        library_sources: Vec::new(),
        input_overrides: Vec::new(),
        strategy_alert_template: None,
        strategy_running_alert: None,
    };

    let output = run_json_with_options(&options)
        .expect("profile UDF length series max_bars_back miss output");

    assert!(output.contains(r#""historyRetentionMode":"maxBarsBack""#));
    assert!(output.contains(r#""historyMaxBarsBack":10"#));
    assert!(output.contains(r#""historyDynamicRetentionMisses":3"#));
    assert!(output.contains(
        r#""diagnostics":[{"code":"W_HISTORY_MAX_BARS_BACK","message":"dynamic history offsets exceeded max_bars_back=2; 3 reads returned na, maximum requested offset was 3"}]"#
    ));
}

#[test]
fn profiled_run_reports_block_series_max_bars_back_diagnostic() {
    let options = RunOptions {
        path: workspace_path(
            "tests/fixtures/profile/dynamic_history_series_max_bars_back_block_miss.pine",
        ),
        bars_path: workspace_path("tests/fixtures/runtime/bars.csv"),
        profile: true,
        request_bars: Vec::new(),
        library_sources: Vec::new(),
        input_overrides: Vec::new(),
        strategy_alert_template: None,
        strategy_running_alert: None,
    };

    let output =
        run_json_with_options(&options).expect("profile block series max_bars_back miss output");

    assert!(output.contains(r#""historyRetentionMode":"maxBarsBack""#));
    assert!(output.contains(r#""historyMaxBarsBack":10"#));
    assert!(output.contains(r#""historyDynamicRetentionMisses":3"#));
    assert!(output.contains(
        r#""diagnostics":[{"code":"W_HISTORY_MAX_BARS_BACK","message":"dynamic history offsets exceeded max_bars_back=2; 3 reads returned na, maximum requested offset was 3"}]"#
    ));
}

#[test]
fn profiled_run_reports_switch_block_series_max_bars_back_diagnostic() {
    let options = RunOptions {
        path: workspace_path(
            "tests/fixtures/profile/dynamic_history_series_max_bars_back_switch_block_miss.pine",
        ),
        bars_path: workspace_path("tests/fixtures/runtime/bars.csv"),
        profile: true,
        request_bars: Vec::new(),
        library_sources: Vec::new(),
        input_overrides: Vec::new(),
        strategy_alert_template: None,
        strategy_running_alert: None,
    };

    let output = run_json_with_options(&options)
        .expect("profile switch block series max_bars_back miss output");

    assert!(output.contains(r#""historyRetentionMode":"maxBarsBack""#));
    assert!(output.contains(r#""historyMaxBarsBack":10"#));
    assert!(output.contains(r#""historyDynamicRetentionMisses":3"#));
    assert!(output.contains(
        r#""diagnostics":[{"code":"W_HISTORY_MAX_BARS_BACK","message":"dynamic history offsets exceeded max_bars_back=2; 3 reads returned na, maximum requested offset was 3"}]"#
    ));
}

#[test]
fn profiled_run_reports_statement_switch_series_max_bars_back_diagnostic() {
    let options = RunOptions {
        path: workspace_path(
            "tests/fixtures/profile/dynamic_history_series_max_bars_back_statement_switch_miss.pine",
        ),
        bars_path: workspace_path("tests/fixtures/runtime/bars.csv"),
        profile: true,
        request_bars: Vec::new(),
        library_sources: Vec::new(),
        input_overrides: Vec::new(),
        strategy_alert_template: None,
        strategy_running_alert: None,
    };

    let output = run_json_with_options(&options)
        .expect("profile statement switch series max_bars_back miss output");

    assert!(output.contains(r#""historyRetentionMode":"maxBarsBack""#));
    assert!(output.contains(r#""historyMaxBarsBack":10"#));
    assert!(output.contains(r#""historyDynamicRetentionMisses":3"#));
    assert!(output.contains(
        r#""diagnostics":[{"code":"W_HISTORY_MAX_BARS_BACK","message":"dynamic history offsets exceeded max_bars_back=2; 3 reads returned na, maximum requested offset was 3"}]"#
    ));
}

#[test]
fn profiled_run_reports_expression_block_series_max_bars_back_diagnostic() {
    let options = RunOptions {
        path: workspace_path(
            "tests/fixtures/profile/dynamic_history_series_max_bars_back_expression_block_miss.pine",
        ),
        bars_path: workspace_path("tests/fixtures/runtime/bars.csv"),
        profile: true,
        request_bars: Vec::new(),
        library_sources: Vec::new(),
        input_overrides: Vec::new(),
        strategy_alert_template: None,
        strategy_running_alert: None,
    };

    let output = run_json_with_options(&options)
        .expect("profile expression block series max_bars_back miss output");

    assert!(output.contains(r#""historyRetentionMode":"maxBarsBack""#));
    assert!(output.contains(r#""historyMaxBarsBack":10"#));
    assert!(output.contains(r#""historyDynamicRetentionMisses":3"#));
    assert!(output.contains(
        r#""diagnostics":[{"code":"W_HISTORY_MAX_BARS_BACK","message":"dynamic history offsets exceeded max_bars_back=2; 3 reads returned na, maximum requested offset was 3"}]"#
    ));
}

#[test]
fn profiled_run_reports_tuple_switch_expression_block_series_max_bars_back_diagnostic() {
    let options = RunOptions {
        path: workspace_path(
            "tests/fixtures/profile/dynamic_history_series_max_bars_back_tuple_switch_expression_block_miss.pine",
        ),
        bars_path: workspace_path("tests/fixtures/runtime/bars.csv"),
        profile: true,
        request_bars: Vec::new(),
        library_sources: Vec::new(),
        input_overrides: Vec::new(),
        strategy_alert_template: None,
        strategy_running_alert: None,
    };

    let output = run_json_with_options(&options)
        .expect("profile tuple switch expression block series max_bars_back miss output");

    assert!(output.contains(r#""historyRetentionMode":"maxBarsBack""#));
    assert!(output.contains(r#""historyMaxBarsBack":10"#));
    assert!(output.contains(r#""historyDynamicRetentionMisses":3"#));
    assert!(output.contains(
        r#""diagnostics":[{"code":"W_HISTORY_MAX_BARS_BACK","message":"dynamic history offsets exceeded max_bars_back=2; 3 reads returned na, maximum requested offset was 3"}]"#
    ));
}

#[test]
fn profiled_run_reports_if_expression_block_series_max_bars_back_diagnostic() {
    let options = RunOptions {
        path: workspace_path(
            "tests/fixtures/profile/dynamic_history_series_max_bars_back_if_expression_block_miss.pine",
        ),
        bars_path: workspace_path("tests/fixtures/runtime/bars.csv"),
        profile: true,
        request_bars: Vec::new(),
        library_sources: Vec::new(),
        input_overrides: Vec::new(),
        strategy_alert_template: None,
        strategy_running_alert: None,
    };

    let output = run_json_with_options(&options)
        .expect("profile if expression block series max_bars_back miss output");

    assert!(output.contains(r#""historyRetentionMode":"maxBarsBack""#));
    assert!(output.contains(r#""historyMaxBarsBack":10"#));
    assert!(output.contains(r#""historyDynamicRetentionMisses":3"#));
    assert!(output.contains(
        r#""diagnostics":[{"code":"W_HISTORY_MAX_BARS_BACK","message":"dynamic history offsets exceeded max_bars_back=2; 3 reads returned na, maximum requested offset was 3"}]"#
    ));
}

#[test]
fn profiled_run_reports_tuple_if_expression_block_series_max_bars_back_diagnostic() {
    let options = RunOptions {
        path: workspace_path(
            "tests/fixtures/profile/dynamic_history_series_max_bars_back_tuple_if_expression_block_miss.pine",
        ),
        bars_path: workspace_path("tests/fixtures/runtime/bars.csv"),
        profile: true,
        request_bars: Vec::new(),
        library_sources: Vec::new(),
        input_overrides: Vec::new(),
        strategy_alert_template: None,
        strategy_running_alert: None,
    };

    let output = run_json_with_options(&options)
        .expect("profile tuple if expression block series max_bars_back miss output");

    assert!(output.contains(r#""historyRetentionMode":"maxBarsBack""#));
    assert!(output.contains(r#""historyMaxBarsBack":10"#));
    assert!(output.contains(r#""historyDynamicRetentionMisses":3"#));
    assert!(output.contains(
        r#""diagnostics":[{"code":"W_HISTORY_MAX_BARS_BACK","message":"dynamic history offsets exceeded max_bars_back=2; 3 reads returned na, maximum requested offset was 3"}]"#
    ));
}

#[test]
fn profiled_run_reports_call_argument_block_series_max_bars_back_diagnostic() {
    let options = RunOptions {
        path: workspace_path(
            "tests/fixtures/profile/dynamic_history_series_max_bars_back_call_argument_block_miss.pine",
        ),
        bars_path: workspace_path("tests/fixtures/runtime/bars.csv"),
        profile: true,
        request_bars: Vec::new(),
        library_sources: Vec::new(),
        input_overrides: Vec::new(),
        strategy_alert_template: None,
        strategy_running_alert: None,
    };

    let output = run_json_with_options(&options)
        .expect("profile call argument block series max_bars_back miss output");

    assert!(output.contains(r#""historyRetentionMode":"maxBarsBack""#));
    assert!(output.contains(r#""historyMaxBarsBack":10"#));
    assert!(output.contains(r#""historyDynamicRetentionMisses":3"#));
    assert!(output.contains(
        r#""diagnostics":[{"code":"W_HISTORY_MAX_BARS_BACK","message":"dynamic history offsets exceeded max_bars_back=2; 3 reads returned na, maximum requested offset was 3"}]"#
    ));
}

#[test]
fn profiled_run_reports_block_result_series_max_bars_back_diagnostic() {
    let options = RunOptions {
        path: workspace_path(
            "tests/fixtures/profile/dynamic_history_series_max_bars_back_block_result_miss.pine",
        ),
        bars_path: workspace_path("tests/fixtures/runtime/bars.csv"),
        profile: true,
        request_bars: Vec::new(),
        library_sources: Vec::new(),
        input_overrides: Vec::new(),
        strategy_alert_template: None,
        strategy_running_alert: None,
    };

    let output = run_json_with_options(&options)
        .expect("profile block result series max_bars_back miss output");

    assert!(output.contains(r#""historyRetentionMode":"maxBarsBack""#));
    assert!(output.contains(r#""historyMaxBarsBack":10"#));
    assert!(output.contains(r#""historyDynamicRetentionMisses":3"#));
    assert!(output.contains(
        r#""diagnostics":[{"code":"W_HISTORY_MAX_BARS_BACK","message":"dynamic history offsets exceeded max_bars_back=2; 3 reads returned na, maximum requested offset was 3"}]"#
    ));
}

#[test]
fn profiled_run_reports_loop_result_series_max_bars_back_diagnostic() {
    let options = RunOptions {
        path: workspace_path(
            "tests/fixtures/profile/dynamic_history_series_max_bars_back_loop_result_miss.pine",
        ),
        bars_path: workspace_path("tests/fixtures/runtime/bars.csv"),
        profile: true,
        request_bars: Vec::new(),
        library_sources: Vec::new(),
        input_overrides: Vec::new(),
        strategy_alert_template: None,
        strategy_running_alert: None,
    };

    let output = run_json_with_options(&options)
        .expect("profile loop result series max_bars_back miss output");

    assert!(output.contains(r#""historyRetentionMode":"maxBarsBack""#));
    assert!(output.contains(r#""historyMaxBarsBack":10"#));
    assert!(output.contains(r#""historyDynamicRetentionMisses":3"#));
    assert!(output.contains(
        r#""diagnostics":[{"code":"W_HISTORY_MAX_BARS_BACK","message":"dynamic history offsets exceeded max_bars_back=2; 3 reads returned na, maximum requested offset was 3"}]"#
    ));
}

#[test]
fn profiled_run_reports_for_in_result_series_max_bars_back_diagnostic() {
    let options = RunOptions {
        path: workspace_path(
            "tests/fixtures/profile/dynamic_history_series_max_bars_back_for_in_result_miss.pine",
        ),
        bars_path: workspace_path("tests/fixtures/runtime/bars.csv"),
        profile: true,
        request_bars: Vec::new(),
        library_sources: Vec::new(),
        input_overrides: Vec::new(),
        strategy_alert_template: None,
        strategy_running_alert: None,
    };

    let output = run_json_with_options(&options)
        .expect("profile for-in result series max_bars_back miss output");

    assert!(output.contains(r#""historyRetentionMode":"maxBarsBack""#));
    assert!(output.contains(r#""historyMaxBarsBack":10"#));
    assert!(output.contains(r#""historyDynamicRetentionMisses":3"#));
    assert!(output.contains(
        r#""diagnostics":[{"code":"W_HISTORY_MAX_BARS_BACK","message":"dynamic history offsets exceeded max_bars_back=2; 3 reads returned na, maximum requested offset was 3"}]"#
    ));
}

#[test]
fn profiled_run_reports_for_statement_series_max_bars_back_diagnostic() {
    let options = RunOptions {
        path: workspace_path(
            "tests/fixtures/profile/dynamic_history_series_max_bars_back_for_statement_miss.pine",
        ),
        bars_path: workspace_path("tests/fixtures/runtime/bars.csv"),
        profile: true,
        request_bars: Vec::new(),
        library_sources: Vec::new(),
        input_overrides: Vec::new(),
        strategy_alert_template: None,
        strategy_running_alert: None,
    };

    let output = run_json_with_options(&options)
        .expect("profile for statement series max_bars_back miss output");

    assert!(output.contains(r#""historyRetentionMode":"maxBarsBack""#));
    assert!(output.contains(r#""historyMaxBarsBack":10"#));
    assert!(output.contains(r#""historyDynamicRetentionMisses":3"#));
    assert!(output.contains(
        r#""diagnostics":[{"code":"W_HISTORY_MAX_BARS_BACK","message":"dynamic history offsets exceeded max_bars_back=2; 3 reads returned na, maximum requested offset was 3"}]"#
    ));
}

#[test]
fn profiled_run_reports_for_in_statement_series_max_bars_back_diagnostic() {
    let options = RunOptions {
        path: workspace_path(
            "tests/fixtures/profile/dynamic_history_series_max_bars_back_for_in_statement_miss.pine",
        ),
        bars_path: workspace_path("tests/fixtures/runtime/bars.csv"),
        profile: true,
        request_bars: Vec::new(),
        library_sources: Vec::new(),
        input_overrides: Vec::new(),
        strategy_alert_template: None,
        strategy_running_alert: None,
    };

    let output = run_json_with_options(&options)
        .expect("profile for-in statement series max_bars_back miss output");

    assert!(output.contains(r#""historyRetentionMode":"maxBarsBack""#));
    assert!(output.contains(r#""historyMaxBarsBack":10"#));
    assert!(output.contains(r#""historyDynamicRetentionMisses":3"#));
    assert!(output.contains(
        r#""diagnostics":[{"code":"W_HISTORY_MAX_BARS_BACK","message":"dynamic history offsets exceeded max_bars_back=2; 3 reads returned na, maximum requested offset was 3"}]"#
    ));
}

#[test]
fn profiled_run_reports_while_result_series_max_bars_back_diagnostic() {
    let options = RunOptions {
        path: workspace_path(
            "tests/fixtures/profile/dynamic_history_series_max_bars_back_while_result_miss.pine",
        ),
        bars_path: workspace_path("tests/fixtures/runtime/bars.csv"),
        profile: true,
        request_bars: Vec::new(),
        library_sources: Vec::new(),
        input_overrides: Vec::new(),
        strategy_alert_template: None,
        strategy_running_alert: None,
    };

    let output = run_json_with_options(&options)
        .expect("profile while result series max_bars_back miss output");

    assert!(output.contains(r#""historyRetentionMode":"maxBarsBack""#));
    assert!(output.contains(r#""historyMaxBarsBack":10"#));
    assert!(output.contains(r#""historyDynamicRetentionMisses":3"#));
    assert!(output.contains(
        r#""diagnostics":[{"code":"W_HISTORY_MAX_BARS_BACK","message":"dynamic history offsets exceeded max_bars_back=2; 3 reads returned na, maximum requested offset was 3"}]"#
    ));
}

#[test]
fn profiled_run_reports_while_statement_series_max_bars_back_diagnostic() {
    let options = RunOptions {
        path: workspace_path(
            "tests/fixtures/profile/dynamic_history_series_max_bars_back_while_statement_miss.pine",
        ),
        bars_path: workspace_path("tests/fixtures/runtime/bars.csv"),
        profile: true,
        request_bars: Vec::new(),
        library_sources: Vec::new(),
        input_overrides: Vec::new(),
        strategy_alert_template: None,
        strategy_running_alert: None,
    };

    let output = run_json_with_options(&options)
        .expect("profile while statement series max_bars_back miss output");

    assert!(output.contains(r#""historyRetentionMode":"maxBarsBack""#));
    assert!(output.contains(r#""historyMaxBarsBack":10"#));
    assert!(output.contains(r#""historyDynamicRetentionMisses":3"#));
    assert!(output.contains(
        r#""diagnostics":[{"code":"W_HISTORY_MAX_BARS_BACK","message":"dynamic history offsets exceeded max_bars_back=2; 3 reads returned na, maximum requested offset was 3"}]"#
    ));
}

#[test]
fn profiled_run_reports_pure_expr_prefix_udf_series_max_bars_back_diagnostic() {
    assert_profile_series_max_bars_back_miss(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_pure_expr_prefix_udf_call_miss.pine",
        "pure expr prefix UDF series max_bars_back miss",
    );
}

#[test]
fn profiled_run_reports_pure_control_flow_expression_series_max_bars_back_diagnostics() {
    for (path, context) in [
        (
            "tests/fixtures/profile/dynamic_history_series_max_bars_back_pure_if_expression_identity_miss.pine",
            "pure if expression identity series max_bars_back miss",
        ),
        (
            "tests/fixtures/profile/dynamic_history_series_max_bars_back_pure_switch_expression_identity_miss.pine",
            "pure switch expression identity series max_bars_back miss",
        ),
        (
            "tests/fixtures/profile/dynamic_history_series_max_bars_back_pure_for_expression_identity_miss.pine",
            "pure for expression identity series max_bars_back miss",
        ),
        (
            "tests/fixtures/profile/dynamic_history_series_max_bars_back_pure_for_in_array_from_expression_identity_miss.pine",
            "pure for-in array.from expression identity series max_bars_back miss",
        ),
        (
            "tests/fixtures/profile/dynamic_history_series_max_bars_back_pure_while_expression_identity_miss.pine",
            "pure while expression identity series max_bars_back miss",
        ),
    ] {
        assert_profile_series_max_bars_back_miss(path, context);
    }
}

#[test]
fn profiled_run_reports_user_method_receiver_alias_series_max_bars_back_diagnostic() {
    assert_profile_series_max_bars_back_miss(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_pure_user_method_receiver_alias_field_miss.pine",
        "pure user method receiver alias series max_bars_back miss",
    );
}

#[test]
fn profiled_run_reports_udt_udf_and_method_series_max_bars_back_diagnostics() {
    let cases = [
        (
            "tests/fixtures/profile/dynamic_history_series_max_bars_back_pure_udf_nested_udt_field_alias_miss.pine",
            "local pure UDF nested UDT field alias series max_bars_back miss",
            false,
        ),
        (
            "tests/fixtures/profile/dynamic_history_series_max_bars_back_pure_udf_imported_nested_udt_arg_field_miss.pine",
            "imported pure UDF nested UDT arg field series max_bars_back miss",
            true,
        ),
        (
            "tests/fixtures/profile/dynamic_history_series_max_bars_back_nested_pure_user_method_named_direct_nested_udt_arg_expr_miss.pine",
            "local nested pure user method named direct nested UDT arg expression series max_bars_back miss",
            false,
        ),
        (
            "tests/fixtures/profile/dynamic_history_series_max_bars_back_pure_user_method_imported_alias_qualified_direct_receiver_expr_miss.pine",
            "imported alias-qualified direct receiver expression method series max_bars_back miss",
            true,
        ),
    ];

    for (path, context, needs_imported_udt_library) in cases {
        let library_sources = needs_imported_udt_library
            .then(imported_udt_library_source)
            .into_iter()
            .collect();
        assert_profile_series_max_bars_back_miss_with_libraries(path, context, library_sources);
    }
}

#[test]
fn runs_request_bars_integration_fixture() {
    let options = RunOptions {
        path: workspace_path("tests/fixtures/request/request_security_host.pine"),
        bars_path: workspace_path("tests/fixtures/request/chart_1m.csv"),
        profile: false,
        library_sources: Vec::new(),
        request_bars: vec![
            parse_request_bars_spec(&format!(
                "NYSE:IBM:1={}",
                workspace_path("tests/fixtures/request/ibm_1m.csv")
            ))
            .expect("same timeframe request bars"),
            parse_request_bars_spec(&format!(
                "NYSE:IBM:5={}",
                workspace_path("tests/fixtures/request/ibm_5m.csv")
            ))
            .expect("higher timeframe request bars"),
        ],
        input_overrides: Vec::new(),
        strategy_alert_template: None,
        strategy_running_alert: None,
    };

    let output = run_json_with_options(&options).expect("request integration fixture");

    assert!(output.contains("\"values\":[30,32,34,36,38]"));
    assert!(output.contains("\"values\":[null,null,100,100,200]"));
    assert!(output.contains("\"values\":[10,10,10,10,10]"));
    assert!(output.contains("\"values\":[34,35,36,37,38]"));
    assert!(output.contains("\"values\":[null,41,43,45,47]"));
    assert!(output.contains("\"values\":[20.01,21.01,22.01,23.01,24.01]"));
    assert!(output.contains("\"values\":[null,100,100,100,100]"));
    assert!(output.contains("\"values\":[2,10,10,10,10]"));
    assert!(output.contains("\"values\":[null,10,10,10,10]"));
    assert!(output.contains(
        "\"values\":[2,4.666666666666667,6.4444444444444455,7.629629629629631,8.419753086419753]"
    ));
    assert!(output.contains("\"values\":[null,null,13,14,15]"));
    assert!(output.contains("\"values\":[null,null,9,10,11]"));
    assert!(output.contains("\"values\":[null,1,1,1,1]"));
    assert!(output.contains("\"values\":[null,null,2,2,2]"));
    assert!(output.contains("\"values\":[null,null,10,9.523809523809524,9.090909090909092]"));
    assert!(output.contains("\"values\":[null,null,2,2,2]"));
    assert!(output.contains(
        "\"values\":[null,null,0.6666666666666666,0.6666666666666666,0.6666666666666666]"
    ));
    assert!(output.contains("\"values\":[0,0,1,1,1]"));
    assert!(output.matches("\"values\":[0,0,0,0,0]").count() >= 3);
    assert!(output.contains("\"values\":[0,1,0,0,0]"));
    assert!(output.contains("\"values\":[0,1,0,0,0]"));
    assert!(output.contains("\"values\":[0,0,1,0,0]"));
    assert!(output.contains("\"values\":[null,null,null,null,0]"));
    assert!(output.contains("\"values\":[null,null,null,null,1]"));
    assert!(output.contains("\"values\":[null,null,null,null,300]"));
    assert!(output.contains("\"values\":[null,null,100.01,100.01,200.01]"));
    assert!(output.contains("\"values\":[null,null,33,33,66]"));
    assert!(output.contains("\"values\":[null,null,2,2,3]"));
    assert!(output.contains("\"values\":[null,null,33.33,33.33,66.67]"));
    assert!(output.contains("\"values\":[null,null,10,10,14.142135623730951]"));
    assert!(
        output.contains(
            "\"values\":[null,null,4.641588833612779,4.641588833612779,5.848035476425732]"
        )
    );
    assert!(output.contains("\"values\":[null,null,2,2,2.3010299956639813]"));
    assert!(output.contains(
        "\"values\":[null,null,0.8414709848078965,0.8414709848078965,0.9092974268256817]"
    ));
    assert!(output.contains(
        "\"values\":[null,null,0.6216099682706644,0.6216099682706644,-0.32328956686350335]"
    ));
    assert!(output.contains(
        "\"values\":[null,null,0.10033467208545055,0.10033467208545055,0.10033467208545055]"
    ));
    assert!(output.contains("\"values\":[null,null,1,1,4]"));
    assert!(output.contains(
        "\"values\":[null,null,1.3453624047073711,1.3453624047073711,2.7586228448267445]"
    ));
    assert!(
        output.contains(
            "\"values\":[null,null,4.605170185988092,4.605170185988092,5.298317366548036]"
        )
    );
    assert!(
        output.contains(
            "\"values\":[null,null,2.718281828459045,2.718281828459045,7.38905609893065]"
        )
    );
    assert!(output.contains("\"values\":[null,null,1.0471975511965979,1.0471975511965979,0]"));
    assert!(output.contains(
        "\"values\":[null,null,0.5235987755982989,0.5235987755982989,1.5707963267948966]"
    ));
    assert!(output.contains(
        "\"values\":[null,null,0.7853981633974483,0.7853981633974483,1.1071487177940904]"
    ));
    assert!(output.contains("\"values\":[null,null,95,95,195]"));
    assert!(output.contains("\"values\":[null,null,33,33,66]"));
    assert!(output.contains("\"values\":[null,null,1,1,1]"));
    assert!(
        output.contains(
            "\"values\":[null,null,57.29577951308232,57.29577951308232,114.59155902616465]"
        )
    );
    assert!(output.contains(
        "\"values\":[null,null,0.15707963267948966,0.15707963267948966,0.33161255787892263]"
    ));
    assert!(output.contains("\"values\":[6,7,7,7,8]"));
    assert!(output.contains("\"values\":[2,2,2,3,3]"));
    assert!(output.contains("\"values\":[2.86,3,3.14,3.29,3.43]"));
    assert!(output.contains(
            "\"values\":[4.47213595499958,4.58257569495584,4.69041575982343,4.795831523312719,4.898979485566356]"
        ));
    assert!(output.contains(
            "\"values\":[2.7144176165949068,2.7589241763811208,2.8020393306553872,2.8438669798515654,2.8844991406148166]"
        ));
    assert!(output.contains(
            "\"values\":[1.3010299956639813,1.3222192947339193,1.3424226808222062,1.3617278360175928,1.380211241711606]"
        ));
    assert!(output.contains(
            "\"values\":[0.19866933079506122,0.20845989984609956,0.21822962308086932,0.2279775235351884,0.23770262642713458]"
        ));
    assert!(output.contains(
            "\"values\":[0.9950041652780258,0.9939560979566968,0.9928086358538663,0.9915618937147881,0.9902159962126371]"
        ));
    assert!(output.contains(
            "\"values\":[0.10033467208545055,0.10033467208545055,0.10033467208545055,0.10033467208545055,0.10033467208545055]"
        ));
    assert!(
        output
            .contains("\"values\":[0.04000000000000001,0.04409999999999999,0.0484,0.0529,0.0576]")
    );
    assert!(output.contains(
            "\"values\":[0.223606797749979,0.23706539182259395,0.25059928172283336,0.2641968962724581,0.2778488797889961]"
        ));
    assert!(output.contains(
            "\"values\":[2.995732273553991,3.044522437723423,3.091042453358316,3.1354942159291497,3.1780538303479458]"
        ));
    assert!(output.contains(
            "\"values\":[1.2214027581601699,1.2336780599567432,1.2460767305873808,1.2586000099294778,1.2712491503214047]"
        ));
    assert!(output.contains(
            "\"values\":[1.4706289056333368,1.4656024257545082,1.46057327680715,1.455541327127319,1.4505064444001086]"
        ));
    assert!(output.contains(
            "\"values\":[0.1001674211615598,0.10519390104038849,0.11022304998774664,0.1152549996675776,0.12028988239478806]"
        ));
    assert!(output.contains(
            "\"values\":[0.19739555984988078,0.206992194219821,0.21655030497608926,0.22606838799388393,0.23554498072086333]"
        ));
    assert!(output.contains("\"values\":[12.5,13.5,14.5,15.5,16.5]"));
    assert!(output.contains("\"values\":[6,7,7,7,8]"));
    assert!(output.contains("\"values\":[1,1,1,1,1]"));
    assert!(output.contains(
            "\"values\":[11.459155902616466,12.032113697747288,12.60507149287811,13.178029288008934,13.750987083139757]"
        ));
    assert!(output.contains(
            "\"values\":[0.017453292519943295,0.019198621771937627,0.020943951023931952,0.022689280275926284,0.024434609527920613]"
        ));
    assert!(output.contains("\"values\":[2,10,10,10,10]"));
    assert!(output.contains("\"values\":[2,6,8,9,9.5]"));
    assert!(output.contains("\"values\":[null,12,13,14,15]"));
    assert!(output.contains("\"values\":[null,9,10,11,12]"));
    assert!(output.matches("\"values\":[null,1,1,1,1]").count() >= 2);
    assert!(
        output
            .contains("\"values\":[null,5,4.761904761904762,4.545454545454546,4.3478260869565215]")
    );
    assert!(output.contains("\"values\":[null,0.5,0.5,0.5,0.5]"));
    assert!(output.contains("\"values\":[20,41,63,86,110]"));
    assert!(
        output
            .matches("\"values\":[null,null,0.816496580927726,0.816496580927726,0.816496580927726]")
            .count()
            >= 2
    );
    assert!(output.contains(
        "\"values\":[null,null,0.9999999999999858,1.0000000000000284,1.0000000000000284]"
    ));
    assert!(
        output
            .matches(
                "\"values\":[null,null,0.6666666666666666,0.6666666666666666,0.6666666666666666]"
            )
            .count()
            >= 2
    );
    assert!(output.contains("\"values\":[null,null,1,1,1]"));
    assert!(
        output
            .matches(
                "\"values\":[null,null,21.333333333333332,22.333333333333332,23.333333333333332]"
            )
            .count()
            >= 2
    );
    assert!(
        output
            .matches("\"values\":[null,null,null,21.5,22.5]")
            .count()
            >= 2
    );
    assert!(
        output
            .matches("\"values\":[null,null,null,null,24]")
            .count()
            >= 2
    );
    assert!(
        output
            .matches("\"values\":[null,null,null,22.462027683060324,23.462027683060324]")
            .count()
            >= 2
    );
    assert!(output.matches("\"values\":[null,null,22,23,24]").count() >= 2);
    assert!(
            output
                .matches(
                    "\"values\":[20,20.333333333333332,20.88888888888889,21.59259259259259,22.395061728395063]"
                )
                .count()
                >= 2
        );
    assert!(
        output
            .matches("\"values\":[20,20.75,21.75,22.8125,23.875]")
            .count()
            >= 2
    );
    assert!(
        output
            .matches("\"values\":[20,20.875,21.9375,23,24.03125]")
            .count()
            >= 2
    );
    assert!(output.matches("\"values\":[null,1,1,1,1]").count() >= 2);
    assert!(
        output
            .matches("\"values\":[null,null,null,100,100]")
            .count()
            >= 2
    );
    assert!(output.matches("\"values\":[null,null,100,100,100]").count() >= 3);
    assert!(output.contains(
        "\"values\":[null,null,0.15552315827194782,0.1484539238050411,0.14199940537873496]"
    ));
    assert!(output.contains("\"values\":[null,null,1,1,1]"));
    assert!(output.contains(
        "\"values\":[null,null,0.6666666666666572,0.6666666666666856,0.6666666666666856]"
    ));
    assert!(output.contains("\"values\":[null,null,21,22,23]"));
    assert!(output.contains("\"values\":[null,null,20,21,22]"));
    assert!(output.matches("\"values\":[null,null,100,100,100]").count() >= 2);
    assert!(output.contains(
        "\"values\":[20,20.333333333333332,20.88888888888889,21.59259259259259,22.395061728395063]"
    ));
    assert!(output.contains("\"values\":[20,20.75,21.75,22.8125,23.875]"));
    assert!(output.contains("\"values\":[20,20.875,21.9375,23,24.03125]"));
    assert!(output.contains("\"values\":[null,1,1,1,1]"));
    assert!(output.contains("\"values\":[null,null,null,100,100]"));
    assert!(output.contains("\"values\":[null,null,100,100,100]"));
    assert!(output.matches("\"values\":[null,null,325,325,325]").count() >= 2);
    assert!(output.matches("\"values\":[null,null,225,225,225]").count() >= 2);
    assert!(output.matches("\"values\":[null,9,9,9.16,9.4504]").count() >= 2);
    assert!(
        output
            .matches(
                "\"values\":[null,null,100.00000000000001,100.00000000000001,100.00000000000001]"
            )
            .count()
            >= 2
    );
    assert!(
        output
            .matches(
                "\"values\":[null,null,-1.9682539682539681,-1.9696969696969697,-1.9710144927536233]"
            )
            .count()
            >= 2
    );
    assert!(output.matches("\"values\":[5,5,5,5,5]").count() >= 2);
    assert!(output.matches("\"values\":[20,21,22,23,24]").count() >= 2);
    assert!(output.matches("\"values\":[10,10,10,10,10]").count() >= 2);
    assert!(
            output
                .matches(
                    "\"values\":[0.4,1.170731707317073,1.5058823529411764,1.6271186440677967,1.6476964769647697]"
                )
                .count()
                >= 2
        );
    assert!(
        output
            .matches("\"values\":[null,null,null,null,null]")
            .count()
            >= 8
    );
    assert!(output.matches("\"values\":[null,null,21,22,23]").count() >= 8);
    assert!(output.matches("\"values\":[null,null,0,0,0]").count() >= 3);
    assert!(output.matches("\"values\":[null,null,2,2,2]").count() >= 4);
    assert!(output.matches("\"values\":[null,null,null,22,23]").count() >= 2);
    assert!(output.contains("\"values\":[null,null,null,null,0]"));
    assert!(output.contains("\"values\":[null,null,null,null,1]"));
    assert!(output.matches("\"values\":[null,null,null,0,null]").count() >= 2);
    assert!(output.contains("\"values\":[null,null,null,null,200]"));
    assert!(output.matches("\"values\":[null,null,100,100,200]").count() >= 2);
    assert!(output.contains("\"values\":[null,null,90,90,90]"));
    assert!(
        output.contains(
            "\"values\":[null,null,333.3333333333333,333.3333333333333,666.6666666666666]"
        )
    );
    assert!(output.contains(
        "\"values\":[null,null,0.0003333333333333333,0.0003333333333333333,0.0003333333333333333]"
    ));
    assert!(output.matches("\"values\":[null,null,1,1,1]").count() >= 2);
    assert!(
        output
            .matches("\"values\":[null,null,null,null,1000]")
            .count()
            >= 2
    );
    assert!(
        output.contains(
            "\"values\":[null,null,333.3333333333333,333.3333333333333,333.3333333333333]"
        )
    );
    assert!(output.matches("\"values\":[20,20.5,21,21.5,22]").count() >= 2);
    assert!(output.contains("\"values\":[null,null,100,100,133.33333333333334]"));
    assert!(output.contains("\"values\":[null,null,100,100,175]"));
    assert!(output.contains("\"values\":[null,null,100,100,187.5]"));
    assert!(output.matches("\"values\":[null,null,null,null,1]").count() >= 2);
    assert!(
        output
            .matches("\"values\":[null,null,null,null,100]")
            .count()
            >= 2
    );
    assert!(output.contains("\"values\":[null,null,null,null,92.3076923076923]"));
    assert!(output.contains("\"values\":[null,null,null,null,-7.6923076923076925]"));
    assert!(output.contains("\"values\":[null,null,null,null,80]"));
    assert!(output.contains("\"values\":[null,null,null,null,66.66666666666667]"));
    assert!(output.contains("\"values\":[null,null,null,null,-1.3333333333333333]"));
    assert!(output.contains(
        "\"values\":[null,null,0.3333333333333333,0.3333333333333333,0.3333333333333333]"
    ));
    assert!(output.contains("\"values\":[null,null,1.2,1.2,2]"));
    assert!(output.matches("\"values\":[null,null,100,100,150]").count() >= 2);
    assert!(output.contains("\"values\":[null,null,30,30,110]"));
    assert!(output.contains("\"values\":[null,null,30,30,70]"));
    assert!(output.contains("\"values\":[null,null,null,null,210]"));
    assert!(output.contains("\"values\":[null,null,null,null,80]"));
    assert!(
        output
            .matches("\"values\":[null,null,null,null,210]")
            .count()
            >= 2
    );
    assert!(
        output
            .matches("\"values\":[null,null,null,null,80]")
            .count()
            >= 2
    );
    assert!(
        output
            .matches("\"values\":[null,null,null,null,100]")
            .count()
            >= 4
    );
    assert!(output.contains("\"values\":[null,null,null,null,50]"));
    assert!(output.contains("\"values\":[null,null,100,100,166.66666666666666]"));
    assert!(output.contains("\"values\":[null,null,null,null,1.3333333333333333]"));
    assert!(
        output
            .matches("\"values\":[1000,2000,3000,4000,5000]")
            .count()
            >= 2
    );
    assert!(output.matches("\"values\":[0.1,0.1,0.1,0.1,0.1]").count() >= 2);
    assert!(output.matches("\"values\":[1,1,1,1,1]").count() >= 4);
    assert!(output.matches("\"values\":[null,100,200,300,400]").count() >= 2);
    assert!(
        output
            .matches("\"values\":[null,5,9.761904761904763,14.30735930735931,18.65518539431583]")
            .count()
            >= 2
    );
    assert!(output.matches("\"values\":[500,500,500,500,500]").count() >= 2);
    assert!(output.contains(
            "\"values\":[0,0.16666666666666785,0.30555555555555713,0.39351851851851904,0.4436728395061742]"
        ));
    assert!(output.contains(
            "\"values\":[0,0.1111111111111119,0.24074074074074206,0.3425925925925934,0.40997942386831393]"
        ));
    assert!(output.contains(
            "\"values\":[0,0.055555555555555955,0.06481481481481507,0.05092592592592565,0.03369341563786027]"
        ));
    assert!(output.contains("\"values\":[null,null,21,22,23]"));
    assert!(output.contains(
        "\"values\":[null,null,22.632993161855453,23.632993161855453,24.632993161855453]"
    ));
    assert!(output.contains(
        "\"values\":[null,null,19.367006838144547,20.367006838144547,21.367006838144547]"
    ));
    assert!(output.contains("\"values\":[20,21,22,23,24]"));
    assert!(output.contains("\"values\":[21,22,23,24,25]"));
    assert!(output.contains("\"values\":[20,20.5,21.25,22.125,23.0625]"));
    assert!(output.contains("\"values\":[24,32.5,37.25,40.125,42.0625]"));
    assert!(output.contains("\"values\":[16,8.5,5.25,4.125,4.0625]"));
    assert!(output.contains("\"values\":[14,6,6,6,6]"));
    assert!(output.contains("\"values\":[1,-1,-1,-1,-1]"));
    assert!(output.contains(
        "\"values\":[0,7.1428571428571415,8.620689655172411,9.223300970873785,9.530791788856305]"
    ));
    assert!(output.contains("\"values\":[0,50,75,87.5,93.75]"));
    assert!(output.contains("\"values\":[20,20.5,21,21.5,22]"));
    assert!(
        output.contains(
            "\"values\":[20,21.5,22.632993161855474,23.73606797749979,24.82842712474619]"
        )
    );
    assert!(
        output.contains(
            "\"values\":[20,19.5,19.367006838144526,19.26393202250021,19.17157287525381]"
        )
    );
    assert!(output.contains("\"values\":[null,null,101,101,201]"));
    assert!(output.contains("\"values\":[null,null,0,0,16.666666666666657]"));
    assert!(output.contains("\"values\":[null,null,null,null,150]"));
    assert!(output.contains("\"values\":[null,null,null,null,250]"));
    assert!(output.contains("\"values\":[null,null,null,null,50]"));
    assert!(output.contains("\"values\":[null,null,100,100,166.66666666666666]"));
    assert!(output.contains("\"values\":[null,null,null,null,166.66666666666666]"));
    assert!(output.contains("\"values\":[null,null,160,160,333.3333333333333]"));
    assert!(output.contains("\"values\":[null,null,40,40,0]"));
    assert!(output.contains("\"values\":[null,null,100,100,150]"));
    assert!(output.contains("\"values\":[null,null,100,100,250]"));
    assert!(output.contains("\"values\":[null,null,100,100,50]"));
    assert!(output.contains("\"values\":[null,null,155,155,81.66666666666667]"));
    assert!(output.contains("\"values\":[null,null,1,1,-1]"));
    assert!(output.contains("\"values\":[null,null,0,0,71.42857142857143]"));
    assert!(output.contains("\"values\":[null,null,0,0,50]"));
    assert!(output.contains("\"values\":[null,20,21,22,23]"));
    assert!(output.contains("\"values\":[10,20,21,22,23]"));
    assert!(output.contains("\"values\":[0,1,1,1,1]"));
    assert!(
        output
            .matches("\"values\":[null,null,null,null,100]")
            .count()
            >= 4
    );
    assert!(output.contains("\"values\":[null,null,90,90,100]"));
    assert!(output.contains("\"values\":[null,null,0,0,100]"));
    assert!(output.contains("\"values\":[10,11,12,13,14]"));
    assert!(output.contains("\"values\":[null,null,90,90,190]"));
    assert!(output.contains("\"values\":[null,null,10,10,10]"));
    assert!(output.contains("\"values\":[null,20.5,21.5,22.5,23.5]"));
    assert!(output.contains("\"values\":[null,null,null,null,150]"));
    assert!(output.contains("\"values\":[null,null,null,null,100]"));
    assert!(output.contains("\"values\":[null,null,100,100,300]"));
    assert!(output.matches("\"values\":[0,1,0,0,0]").count() >= 4);
    assert!(output.matches("\"values\":[0,0,1,0,0]").count() >= 2);
    assert!(output.matches("\"values\":[null,null,0,0,1]").count() >= 5);
    assert!(output.matches("\"values\":[0,0,1,1,1]").count() >= 3);
    assert!(
        output
            .matches(
                "\"values\":[null,null,0.9999999999999858,1.0000000000000284,1.0000000000000284]"
            )
            .count()
            >= 2
    );
    assert!(
        output
            .matches(
                "\"values\":[null,null,0.6666666666666572,0.6666666666666856,0.6666666666666856]"
            )
            .count()
            >= 2
    );
    assert!(output.contains("\"values\":[null,null,null,null,1]"));
    assert!(
        output
            .matches("\"values\":[null,null,null,null,2500]")
            .count()
            >= 2
    );
    assert!(output.matches("\"values\":[null,null,20,21,22]").count() >= 2);
    assert!(
        output.contains(
            "\"values\":[null,null,33.33333333333333,33.33333333333333,33.33333333333333]"
        )
    );
    assert!(
        output
            .matches("\"values\":[null,null,null,null,150]")
            .count()
            >= 5
    );
    assert!(
        output
            .matches("\"values\":[null,null,null,null,100]")
            .count()
            >= 7
    );
    assert!(
        output
            .matches("\"values\":[null,null,null,null,50]")
            .count()
            >= 2
    );
    assert!(output.contains(
        "\"values\":[20,20.666666666666668,21.555555555555557,22.51851851851852,23.506172839506174]"
    ));
    assert!(output.matches("\"values\":[null,100,100,100,100]").count() >= 2);
    assert!(output.contains(
            "\"values\":[null,0.0975609756097561,0.09302325581395349,0.08888888888888889,0.0851063829787234]"
        ));
    assert!(output.matches("\"values\":[null,12,13,14,15]").count() >= 2);
    assert!(output.matches("\"values\":[null,9,10,11,12]").count() >= 2);
    assert!(output.contains("\"values\":[null,0,0,0,0]"));
    assert!(output.contains("\"values\":[null,1,1,1,1]"));
    assert!(output.matches("\"values\":[null,41,43,45,47]").count() >= 2);
    assert!(
        output
            .matches("\"values\":[20.01,21.01,22.01,23.01,24.01]")
            .count()
            >= 2
    );
}

#[test]
fn runs_imported_function_with_library_source_integration_fixture() {
    let options = RunOptions {
        path: workspace_path("tests/fixtures/runtime/import.pine"),
        bars_path: workspace_path("tests/fixtures/runtime/bars.csv"),
        profile: false,
        request_bars: Vec::new(),
        library_sources: vec![LibrarySourceSpec {
            key: "user/lib/1".to_owned(),
            path: workspace_path("tests/fixtures/libraries/import_lib.pine"),
        }],
        input_overrides: Vec::new(),
        strategy_alert_template: None,
        strategy_running_alert: None,
    };

    let output = run_json_with_options(&options).expect("import integration fixture");

    assert!(output.contains("\"values\":[4,6,8,10]"));
}

#[test]
fn run_json_treats_strategy_exit_wrong_entry_as_noop() {
    let base = std::env::temp_dir().join(format!(
        "pine-cli-wrong-entry-{}-{}",
        std::process::id(),
        std::thread::current().name().unwrap_or("test")
    ));
    let bars_path = base.with_extension("csv");
    fs::write(
        &bars_path,
        "time,open,high,low,close,volume\n0,1,1,1,1,1\n1,2,2,2,2,1\n2,3,3,3,3,1\n",
    )
    .expect("write bars");

    let options = RunOptions {
        path: workspace_path("tests/fixtures/runtime/strategy_exit_unmatched_from_entry_noop.pine"),
        bars_path: bars_path.display().to_string(),
        profile: false,
        request_bars: Vec::new(),
        library_sources: Vec::new(),
        input_overrides: Vec::new(),
        strategy_alert_template: None,
        strategy_running_alert: None,
    };
    let output = run_json_with_options(&options).expect("strategy no-op output");

    assert!(output.contains(
            "\"orders\":[{\"id\":\"L\",\"barIndex\":1,\"time\":1,\"direction\":\"strategy.long\",\"qty\":2,\"price\":2}]"
        ));
    assert!(output.contains("\"trades\":[]"));
    assert!(output.contains("\"position\":[{\"barIndex\":1,\"size\":2,\"avgPrice\":2}]"));
    assert!(output.contains("\"diagnostics\":[]"));
    assert!(!output.contains("\"direction\":\"strategy.exit\""));
    assert!(!output.contains("pending"));
    assert!(!output.contains("reserved"));
    let _ = fs::remove_file(bars_path);
}

#[test]
fn run_output_renders_strategy_order_alert_template() {
    let options = RunOptions {
        path: workspace_path("tests/fixtures/runtime/strategy_exit_metadata.pine"),
        bars_path: workspace_path("tests/fixtures/runtime/bars.csv"),
        profile: false,
        request_bars: Vec::new(),
        library_sources: Vec::new(),
        input_overrides: Vec::new(),
        strategy_alert_template: Some(StrategyAlertTemplateOptions {
            template: "Order: {{strategy.order.alert_message}}".to_owned(),
            index: 1,
        }),
        strategy_running_alert: None,
    };

    let output = run_output_with_options(&options).expect("rendered alert template");

    assert_eq!(output, "Order: loss alert");
}

#[test]
fn run_output_rejects_unknown_strategy_order_alert_placeholder() {
    let options = RunOptions {
        path: workspace_path("tests/fixtures/runtime/strategy_exit_metadata.pine"),
        bars_path: workspace_path("tests/fixtures/runtime/bars.csv"),
        profile: false,
        request_bars: Vec::new(),
        library_sources: Vec::new(),
        input_overrides: Vec::new(),
        strategy_alert_template: Some(StrategyAlertTemplateOptions {
            template: "{{close}}".to_owned(),
            index: 1,
        }),
        strategy_running_alert: None,
    };

    let error = run_output_with_options(&options).expect_err("unknown placeholder fails");

    assert!(error.contains("unsupported strategy order-fill alert placeholder `{{close}}`"));
}

#[test]
fn run_output_renders_strategy_running_alert() {
    let options = RunOptions {
        path: workspace_path("tests/fixtures/runtime/strategy_exit_metadata.pine"),
        bars_path: workspace_path("tests/fixtures/runtime/bars.csv"),
        profile: false,
        request_bars: Vec::new(),
        library_sources: Vec::new(),
        input_overrides: Vec::new(),
        strategy_alert_template: None,
        strategy_running_alert: Some(StrategyRunningAlertOptions {
            config: RunningAlertConfig::new_strategy_order_fills(
                "snapshot-1",
                "NYSE:IBM",
                "1",
                "Running: {{strategy.order.alert_message}}",
            ),
            index: 1,
        }),
    };

    let output = run_output_with_options(&options).expect("rendered running alert");

    assert_eq!(output, "Running: loss alert");
}

#[test]
fn run_output_rejects_unknown_strategy_running_alert_placeholder() {
    let options = RunOptions {
        path: workspace_path("tests/fixtures/runtime/strategy_exit_metadata.pine"),
        bars_path: workspace_path("tests/fixtures/runtime/bars.csv"),
        profile: false,
        request_bars: Vec::new(),
        library_sources: Vec::new(),
        input_overrides: Vec::new(),
        strategy_alert_template: None,
        strategy_running_alert: Some(StrategyRunningAlertOptions {
            config: RunningAlertConfig::new_strategy_order_fills(
                "snapshot-1",
                "NYSE:IBM",
                "1",
                "{{close}}",
            ),
            index: 1,
        }),
    };

    let error = run_output_with_options(&options).expect_err("unknown placeholder fails");

    assert!(error.contains("unsupported strategy order-fill alert placeholder `{{close}}`"));
}

#[test]
fn run_json_keeps_strategy_alert_template_output_out_of_default_json() {
    let options = RunOptions {
        path: workspace_path("tests/fixtures/runtime/strategy_exit_metadata.pine"),
        bars_path: workspace_path("tests/fixtures/runtime/bars.csv"),
        profile: false,
        request_bars: Vec::new(),
        library_sources: Vec::new(),
        input_overrides: Vec::new(),
        strategy_alert_template: None,
        strategy_running_alert: None,
    };

    let output = run_json_with_options(&options).expect("default strategy alert JSON");

    assert!(output.contains("\"message\":\"loss alert\""));
    assert!(!output.contains("renderedMessage"));
}
