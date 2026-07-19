use crate::bars_csv::parse_bars_csv;
use crate::commands::matrix::{matrix_json, matrix_text};
use crate::conformance::{
    MatrixEntry, conformance_entries, try_conformance_entries_from_tsv, validate_fixture_paths,
};
use pine_runtime::{
    HistoryRetentionMode, PUBLIC_MATRIX_SCHEMA_VERSION, PUBLIC_RUNTIME_SCHEMA_VERSION, PineValue,
    PlotSeries, RuntimeProfile, RuntimeResult, StrategyResult, public_runtime_profiled_result_json,
    public_runtime_result_json, run_historical,
};
use pine_sema::{AnalysisInput, analyze_input, analyze_source};
use pine_syntax::SourceFile;
use std::{
    collections::BTreeSet,
    env, fs,
    path::{Path, PathBuf},
};

fn strategy_orders_segment(output: &str) -> &str {
    let start = output.find(r#""orders":["#).expect("strategy orders start");
    let tail = &output[start..];
    let end = tail.find(r#","trades":"#).expect("strategy trades start");
    &tail[..end]
}

#[test]
fn matrix_includes_supported_builtins_and_unsupported_features() {
    let entries = conformance_entries();

    for signature in pine_builtins::PHASE_1_BUILTINS {
        let expected_status = if expected_partial_builtin(signature.name) {
            "partial"
        } else {
            "supported"
        };
        let expected_feature = if signature.name.starts_with("matrix.") {
            "matrix.*"
        } else if signature.name.starts_with("map.") {
            "map.*"
        } else {
            signature.name
        };
        assert!(
            entries.iter().any(|entry| entry.feature == expected_feature
                && entry.status == expected_status
                && !entry.fixtures.is_empty()),
            "{} should have fixture-derived metadata",
            signature.name
        );
    }
    assert!(entries.iter().any(|entry| entry.feature == "math.max"
        && entry.status == "supported"
        && !entry.fixtures.is_empty()));
    assert!(entries.iter().any(|entry| entry.feature == "ta.macd"
        && entry.status == "supported"
        && !entry.fixtures.is_empty()));
    assert!(
        entries
            .iter()
            .any(|entry| entry.feature == "if" && entry.status == "supported")
    );
    assert!(
        entries
            .iter()
            .any(|entry| entry.feature == "for" && entry.status == "partial")
    );
    assert!(entries.iter().any(|entry| {
        entry.feature == "expression-body functions" && entry.status == "supported"
    }));
    assert!(entries.iter().any(|entry| {
        entry.feature == "multi-statement functions" && entry.status == "supported"
    }));
    assert!(entries.iter().any(|entry| {
        entry.feature == "block-local declarations" && entry.status == "supported"
    }));
    assert!(
        entries.iter().any(|entry| {
            entry.feature == "recursive functions" && entry.status == "unsupported"
        })
    );
    assert!(
        entries
            .iter()
            .any(|entry| entry.feature == "request.*" && entry.status == "unsupported")
    );
    assert!(
        entries
            .iter()
            .any(|entry| entry.feature == "varip" && entry.status == "partial")
    );
}

fn expected_partial_builtin(name: &str) -> bool {
    if matches!(name, "linefill.get_line1" | "linefill.get_line2") {
        return false;
    }
    [
        "array.",
        "label.",
        "line.",
        "linefill.",
        "polyline.",
        "box.",
        "table.",
        "chart.point.",
        "matrix.",
        "map.",
        "strategy.",
    ]
    .iter()
    .any(|prefix| name.starts_with(prefix))
        || matches!(
            name,
            "request.security"
                | "strategy"
                | "max_bars_back"
                | "alert"
                | "alertcondition"
                | "ta.vwap"
                | "ticker.heikinashi"
                | "ticker.inherit"
                | "ticker.kagi"
                | "ticker.linebreak"
                | "ticker.new"
                | "ticker.modify"
                | "ticker.pointfigure"
                | "ticker.renko"
                | "ticker.standard"
        )
}

#[test]
fn conformance_metadata_references_existing_fixtures() {
    validate_fixture_paths(&conformance_entries(), &workspace_dir())
        .expect("fixture paths should exist");
}

#[test]
fn runtime_fixture_files_are_referenced_by_rust_gates() {
    let workspace = workspace_dir();
    let fixture_paths = pine_fixture_paths(&workspace, "tests/fixtures/runtime")
        .into_iter()
        .chain(pine_fixture_paths(&workspace, "tests/fixtures/regressions"))
        .collect::<Vec<_>>();
    let rust_sources = rust_source_files(&workspace.join("crates"))
        .into_iter()
        .chain(rust_source_files(&workspace.join("tests")))
        .map(|path| {
            fs::read_to_string(&path)
                .unwrap_or_else(|err| panic!("failed to read {}: {err}", path.display()))
        })
        .collect::<Vec<_>>()
        .join("\n");

    let untracked_fixtures: Vec<_> = fixture_paths
        .into_iter()
        .filter(|fixture| !rust_sources.contains(fixture))
        .collect();
    assert!(
        untracked_fixtures.is_empty(),
        "runtime and regression fixture files must be referenced by Rust test gates: {untracked_fixtures:?}"
    );
}

#[test]
fn diagnostic_reference_documents_emitted_codes() {
    let workspace = workspace_dir();
    let mut emitted = BTreeSet::new();
    for path in rust_source_files(&workspace.join("crates")) {
        let text = fs::read_to_string(&path)
            .unwrap_or_else(|err| panic!("failed to read {}: {err}", path.display()));
        emitted.extend(diagnostic_codes_in_text(&text));
    }
    emitted.remove("E_TEST");

    let docs_path = workspace.join("docs/DIAGNOSTIC_CODES.md");
    let docs = fs::read_to_string(&docs_path)
        .unwrap_or_else(|err| panic!("failed to read {}: {err}", docs_path.display()));
    let documented = diagnostic_codes_in_text(&docs);
    let missing: Vec<_> = emitted.difference(&documented).cloned().collect();

    assert!(
        missing.is_empty(),
        "docs/DIAGNOSTIC_CODES.md is missing emitted diagnostic codes: {missing:?}"
    );
}

#[test]
fn rejects_malformed_conformance_rows() {
    let error = try_conformance_entries_from_tsv(
        "feature\tstatus\tnotes\tfixtures\nindicator\tsupported\tmissing fixture column\n",
    )
    .expect_err("row should be malformed");

    assert!(error.contains("expected 4 tab-separated columns"));
}

#[test]
fn rejects_duplicate_conformance_features() {
    let error = try_conformance_entries_from_tsv(
            "feature\tstatus\tnotes\tfixtures\nindicator\tsupported\tone\ttests/fixtures/runtime/io.pine\nindicator\tsupported\ttwo\ttests/fixtures/runtime/io.pine\n",
        )
        .expect_err("feature should be duplicate");

    assert!(error.contains("duplicate feature `indicator`"));
}

#[test]
fn rejects_invalid_conformance_statuses() {
    let error = try_conformance_entries_from_tsv(
            "feature\tstatus\tnotes\tfixtures\nindicator\tready\tnotes\ttests/fixtures/runtime/io.pine\n",
        )
        .expect_err("status should be invalid");

    assert!(error.contains("invalid status `ready`"));
}

#[test]
fn rejects_empty_conformance_fixtures() {
    let error = try_conformance_entries_from_tsv(
        "feature\tstatus\tnotes\tfixtures\nindicator\tsupported\tnotes\t\n",
    )
    .expect_err("fixtures should be empty");

    assert!(error.contains("fixtures must list at least one path"));
}

#[test]
fn rejects_missing_conformance_fixture_paths() {
    let entries = try_conformance_entries_from_tsv(
            "feature\tstatus\tnotes\tfixtures\nindicator\tsupported\tnotes\ttests/fixtures/runtime/missing.pine\n",
        )
        .expect("metadata shape should be valid");
    let error =
        validate_fixture_paths(&entries, &workspace_dir()).expect_err("fixture should be missing");

    assert!(error.contains("tests/fixtures/runtime/missing.pine fixture path should exist"));
}

#[test]
fn rejects_status_fixture_mismatches() {
    let unsupported_error = try_conformance_entries_from_tsv(
            "feature\tstatus\tnotes\tfixtures\nrequest.*\tunsupported\tnotes\ttests/fixtures/runtime/io.pine\n",
        )
        .expect_err("unsupported feature should require diagnostic fixture coverage");
    assert!(unsupported_error.contains("unsupported sema or syntax diagnostic fixture coverage"));

    let supported_error = try_conformance_entries_from_tsv(
            "feature\tstatus\tnotes\tfixtures\nindicator\tsupported\tnotes\ttests/fixtures/sema/unsupported_request.pine\n",
        )
        .expect_err("supported feature should require executable or positive fixture");
    assert!(supported_error.contains("must reference runtime"));
}

#[test]
fn accepts_unsupported_syntax_diagnostic_fixture_paths() {
    let entries = try_conformance_entries_from_tsv(
            "feature\tstatus\tnotes\tfixtures\nexpression nesting depth\tunsupported\tnotes\ttests/fixtures/syntax/deep_expression_limit.pine\n",
        )
        .expect("unsupported parser diagnostics should allow syntax fixture coverage");

    assert_eq!(entries[0].feature, "expression nesting depth");
}

#[test]
fn rejects_request_claims_without_request_fixtures() {
    let error = try_conformance_entries_from_tsv(
            "feature\tstatus\tnotes\tfixtures\nrequest.security\tpartial\tnotes\ttests/fixtures/runtime/io.pine\n",
        )
        .expect_err("request feature should require request fixture coverage");

    assert!(error.contains("must reference request fixture coverage"));
}

#[test]
fn rejects_partial_unsupported_notes_without_unsupported_fixtures() {
    let error = try_conformance_entries_from_tsv(
            "feature\tstatus\tnotes\tfixtures\nlabel.new\tpartial\tseries x remains unsupported\ttests/fixtures/runtime/labels.pine\n",
        )
        .expect_err("partial unsupported notes should require unsupported sema coverage");

    assert!(error.contains("unsupported sema diagnostic fixture coverage"));
}

#[test]
fn rejects_label_getter_claims_outside_official_subset() {
    let error = try_conformance_entries_from_tsv(
            "feature\tstatus\tnotes\tfixtures\nlabel.get_style\tpartial\tstyle getter\ttests/fixtures/runtime/label_getters.pine\n",
        )
        .expect_err("non-official label getter should be rejected");

    assert!(error.contains("outside the official label.get_x/label.get_y/label.get_text subset"));
}

#[test]
fn rejects_array_unsupported_type_claims_without_matching_fixtures() {
    let error = try_conformance_entries_from_tsv(
            "feature\tstatus\tnotes\tfixtures\narray.clear\tpartial\tUDT arrays remain unsupported\ttests/fixtures/runtime/array_clear.pine;tests/fixtures/sema/unsupported_array_join_polyline.pine\n",
        )
        .expect_err("array unsupported type claim should require matching fixture coverage");

    assert!(
        error.contains("must reference UDT fixture coverage"),
        "{error}"
    );
}

#[test]
fn matrix_includes_known_unsupported_platform_families() {
    let entries = conformance_entries();
    for feature in [
        "request.*",
        "strategy.*",
        "alert placeholders",
        "unsupported label/table methods",
        "non-int history offsets",
        "negative history offsets",
    ] {
        assert!(
            entries
                .iter()
                .any(|entry| entry.feature == feature && entry.status == "unsupported"),
            "{feature} should remain explicitly unsupported in matrix"
        );
    }
    assert!(
        entries
            .iter()
            .any(|entry| entry.feature == "matrix.*" && entry.status == "partial")
    );
    assert!(
        entries
            .iter()
            .any(|entry| entry.feature == "map.*" && entry.status == "partial")
    );
}

#[test]
fn matrix_includes_partial_import_subset() {
    let entries = conformance_entries();
    assert!(entries.iter().any(|entry| {
        entry.feature == "import"
            && entry.status == "partial"
            && entry.notes.contains("exported const expressions")
            && entry
                .fixtures
                .iter()
                .any(|fixture| fixture == "tests/fixtures/libraries/import_lib.pine")
    }));
}

#[test]
fn formats_matrix_as_text() {
    let entries = vec![MatrixEntry {
        feature: "indicator".to_owned(),
        status: "supported".to_owned(),
        notes: "fixture-derived executable subset".to_owned(),
        fixtures: vec!["tests/fixtures/runtime/io.pine".to_owned()],
    }];

    let output = matrix_text(&entries);

    assert!(output.contains("feature"));
    assert!(output.contains("fixtures"));
    assert!(output.contains("indicator"));
    assert!(output.contains("supported"));
    assert!(output.contains("tests/fixtures/runtime/io.pine"));
}

#[test]
fn formats_matrix_as_json() {
    let entries = vec![MatrixEntry {
        feature: "request.*".to_owned(),
        status: "unsupported".to_owned(),
        notes: "multi-symbol".to_owned(),
        fixtures: vec!["tests/fixtures/sema/unsupported_request.pine".to_owned()],
    }];

    let output = matrix_json(&entries);

    assert_eq!(
        output,
        format!(
            r#"{{"schemaVersion":{},"features":[{{"feature":"request.*","status":"unsupported","notes":"multi-symbol","fixtures":["tests/fixtures/sema/unsupported_request.pine"]}}]}}"#,
            PUBLIC_MATRIX_SCHEMA_VERSION
        )
    );
}

#[test]
fn formats_matrix_json_with_escaped_control_characters() {
    let entries = vec![MatrixEntry {
        feature: "feature\"name".to_owned(),
        status: "unsupported".to_owned(),
        notes: "line\nnext\tcell".to_owned(),
        fixtures: vec!["tests/fixtures/runtime/io.pine".to_owned()],
    }];

    let output = matrix_json(&entries);

    assert!(output.contains(r#""feature":"feature\"name""#));
    assert!(output.contains(r#""notes":"line\nnext\tcell""#));
}

#[test]
fn formats_runtime_result_json_with_schema_version() {
    let result = RuntimeResult {
        plots: vec![],
        plot_chars: vec![],
        plot_shapes: vec![],
        plot_arrows: vec![],
        plot_bars: vec![],
        plot_candles: vec![],
        bg_colors: vec![],
        bar_colors: vec![],
        hlines: vec![],
        fills: vec![],
        labels: vec![],
        lines: vec![],
        line_fills: vec![],
        polylines: vec![],
        boxes: vec![],
        tables: vec![],
        alerts: vec![],
        strategy: None,
        diagnostics: vec![],
    };

    let output = public_runtime_result_json(&result);

    assert!(output.starts_with(&format!(
        r#"{{"schemaVersion":{},"#,
        PUBLIC_RUNTIME_SCHEMA_VERSION
    )));
    assert!(output.contains(r#""labels":[]"#));
    assert!(output.contains(r#""lines":[]"#));
    assert!(output.contains(r#""lineFills":[]"#));
    assert!(output.contains(r#""polylines":[]"#));
    assert!(output.contains(r#""boxes":[]"#));
    assert!(output.contains(r#""tables":[]"#));
    assert!(output.contains(r#""alerts":[]"#));
    assert!(output.contains(r#""diagnostics":[]"#));
    assert!(!output.contains(r#""strategy""#));
}

#[test]
fn formats_runtime_result_json_with_escaped_string_values() {
    let result = RuntimeResult {
        plots: vec![PlotSeries {
            id: 1,
            values: vec![PineValue::String("line\nnext\t\"quoted\"".to_owned())],
        }],
        plot_chars: vec![],
        plot_shapes: vec![],
        plot_arrows: vec![],
        plot_bars: vec![],
        plot_candles: vec![],
        bg_colors: vec![],
        bar_colors: vec![],
        hlines: vec![],
        fills: vec![],
        labels: vec![],
        lines: vec![],
        line_fills: vec![],
        polylines: vec![],
        boxes: vec![],
        tables: vec![],
        alerts: vec![],
        strategy: None,
        diagnostics: vec![],
    };

    let output = public_runtime_result_json(&result);

    assert!(output.contains(r#""values":["line\nnext\t\"quoted\""]"#));
}

#[test]
fn formats_strategy_result_json_with_empty_contract() {
    let result = RuntimeResult {
        plots: vec![],
        plot_chars: vec![],
        plot_shapes: vec![],
        plot_arrows: vec![],
        plot_bars: vec![],
        plot_candles: vec![],
        bg_colors: vec![],
        bar_colors: vec![],
        hlines: vec![],
        fills: vec![],
        labels: vec![],
        lines: vec![],
        line_fills: vec![],
        polylines: vec![],
        boxes: vec![],
        tables: vec![],
        alerts: vec![],
        strategy: Some(StrategyResult::default()),
        diagnostics: vec![],
    };

    let output = public_runtime_result_json(&result);

    assert!(output.contains(
            r#""strategy":{"orders":[],"trades":[],"position":[],"equity":[],"alerts":[],"diagnostics":[]}"#
        ));
}

#[test]
fn formats_profiled_result_json() {
    let result = RuntimeResult {
        plots: vec![],
        plot_chars: vec![],
        plot_shapes: vec![],
        plot_arrows: vec![],
        plot_bars: vec![],
        plot_candles: vec![],
        bg_colors: vec![],
        bar_colors: vec![],
        hlines: vec![],
        fills: vec![],
        labels: vec![],
        lines: vec![],
        line_fills: vec![],
        polylines: vec![],
        boxes: vec![],
        tables: vec![],
        alerts: vec![],
        strategy: None,
        diagnostics: vec![],
    };
    let profile = RuntimeProfile {
        bars: 3,
        series_buffers: 2,
        series_values: 6,
        series_capacity: 8,
        max_series_depth: 3,
        history_retention_mode: HistoryRetentionMode::DynamicFull,
        history_max_constant_offset: 2,
        history_max_bars_back: None,
        history_has_dynamic_offsets: true,
        history_dynamic_retention_misses: 4,
        history_dynamic_retention_max_missed_offset: Some(7),
        symbol_slots: 10,
        symbol_capacity: 14,
        current_series_slots: 0,
        current_series_capacity: 14,
        var_slots: 1,
        var_capacity: 3,
        array_slots: 1,
        array_capacity: 3,
        array_values: 2,
        array_value_capacity: 2,
        matrix_slots: 1,
        matrix_capacity: 2,
        matrix_cells: 6,
        matrix_cell_capacity: 6,
        call_state_slots: 1,
        call_state_capacity: 3,
        valuewhen_state_slots: 1,
        valuewhen_state_capacity: 3,
        valuewhen_state_values: 2,
        valuewhen_state_value_capacity: 2,
        rolling_window_slots: 1,
        rolling_window_capacity: 3,
        rolling_window_values: 2,
        rolling_window_value_capacity: 2,
        rsi_state_slots: 0,
        rsi_state_capacity: 0,
        macd_state_slots: 0,
        macd_state_capacity: 0,
        plots: 0,
        plot_values: 0,
        plot_capacity: 0,
        plot_chars: 0,
        plot_char_values: 0,
        plot_char_capacity: 0,
        plot_shapes: 0,
        plot_shape_values: 0,
        plot_shape_capacity: 0,
        plot_arrows: 0,
        plot_arrow_values: 0,
        plot_arrow_capacity: 0,
        plot_bars: 0,
        plot_bar_values: 0,
        plot_bar_capacity: 0,
        plot_candles: 0,
        plot_candle_values: 0,
        plot_candle_capacity: 0,
        bg_colors: 0,
        bg_color_values: 0,
        bg_color_capacity: 0,
        bar_colors: 0,
        bar_color_values: 0,
        bar_color_capacity: 0,
        hlines: 0,
        hline_capacity: 0,
        fills: 0,
        fill_capacity: 0,
        labels: 0,
        label_snapshots: 0,
        label_capacity: 0,
        label_snapshot_capacity: 0,
        lines: 0,
        line_snapshots: 0,
        line_capacity: 0,
        line_snapshot_capacity: 0,
        line_fills: 0,
        line_fill_snapshots: 0,
        line_fill_capacity: 0,
        line_fill_snapshot_capacity: 0,
        polylines: 0,
        polyline_snapshots: 0,
        polyline_points: 0,
        polyline_capacity: 0,
        polyline_snapshot_capacity: 0,
        polyline_point_capacity: 0,
        boxes: 0,
        box_snapshots: 0,
        box_capacity: 0,
        box_snapshot_capacity: 0,
        tables: 0,
        table_cells: 0,
        table_capacity: 0,
        table_snapshot_capacity: 0,
        table_cell_capacity: 0,
    };
    let output = public_runtime_profiled_result_json(&result, &profile);
    let expected_prefix = format!(r#"{{"schemaVersion":{},"#, PUBLIC_RUNTIME_SCHEMA_VERSION);
    assert!(output.starts_with(&expected_prefix));
    let history_retention =
        r#""historyDynamicRetentionMisses":4,"historyDynamicRetentionMaxMissedOffset":7"#;
    assert!(output.contains(r#""bars":3"#));
    assert!(output.contains(r#""seriesValues":6"#));
    assert!(output.contains(r#""maxSeriesDepth":3"#));
    assert!(output.contains(r#""historyRetentionMode":"dynamicFull""#));
    assert!(output.contains(r#""historyMaxConstantOffset":2"#));
    assert!(output.contains(r#""historyMaxBarsBack":null"#));
    assert!(output.contains(r#""historyHasDynamicOffsets":true"#));
    assert!(output.contains(history_retention));
    assert!(output.contains(r#""arrayValues":2"#));
    assert!(output.contains(r#""matrixSlots":1"#));
    assert!(output.contains(r#""matrixCells":6"#));
    assert!(output.contains(r#""valuewhenStateValues":2"#));
    assert!(output.contains(r#""rollingWindowValues":2"#));
    assert!(output.contains(r#""plotChars":0"#));
    assert!(output.contains(r#""plotShapes":0"#));
    assert!(output.contains(r#""plotArrows":0"#));
    assert!(output.contains(r#""plotBars":0"#));
    assert!(output.contains(r#""plotCandles":0"#));
    assert!(output.contains(r#""labels":0"#));
    assert!(output.contains(r#""labelSnapshots":0"#));
    assert!(output.contains(r#""lines":0"#));
    assert!(output.contains(r#""lineSnapshots":0"#));
    assert!(output.contains(r#""lineFills":0"#));
    assert!(output.contains(r#""lineFillSnapshots":0"#));
    assert!(output.contains(r#""boxes":0"#));
    assert!(output.contains(r#""boxSnapshots":0"#));
    assert!(output.contains(r#""tables":0"#));
    assert!(output.contains(r#""tableCells":0"#));
}

#[test]
    #[rustfmt::skip]
    fn runtime_outputs_match_golden_snapshots() {
        for (snapshot, fixture) in crate::runtime_snapshots::runtime_snapshot_fixtures() {
            assert_snapshot(snapshot, &runtime_fixture_json(fixture));
        }
        for (snapshot, fixture, library_sources) in crate::runtime_snapshots::RUNTIME_LIBRARY_SNAPSHOT_FIXTURES {
            assert_snapshot(
                snapshot,
                &runtime_library_fixture_json(fixture, library_sources),
            );
        }
    }

#[test]
fn runtime_error_fixtures_report_expected_messages() {
    for (fixture, expected_message) in crate::runtime_snapshots::RUNTIME_ERROR_FIXTURES {
        let message = runtime_fixture_error(fixture);
        assert!(
            message.contains(expected_message),
            "{fixture} error `{message}` did not contain `{expected_message}`"
        );
    }
    for (fixture, expected_message, library_sources) in
        crate::runtime_snapshots::RUNTIME_LIBRARY_ERROR_FIXTURES
    {
        let message = runtime_library_fixture_error(fixture, library_sources);
        assert!(
            message.contains(expected_message),
            "{fixture} error `{message}` did not contain `{expected_message}`"
        );
    }
}

#[test]
fn strategy_exit_bracket_fixture_has_single_exit_order_and_trade() {
    let output = runtime_fixture_json("tests/fixtures/runtime/strategy_exit_bracket_both_hit.pine");

    assert_eq!(
        strategy_orders_segment(&output)
            .matches(r#""direction":"strategy.exit""#)
            .count(),
        1
    );
    assert_eq!(output.matches(r#""trades":[{"#).count(), 1);
    assert!(output.contains(
            r#""orders":[{"id":"L","barIndex":1,"time":2,"direction":"strategy.long","qty":2,"price":100},{"id":"XB","barIndex":1,"time":2,"direction":"strategy.exit","qty":2,"price":95}]"#
        ));
    assert!(output.contains(
            r#""trades":[{"id":"L","entryBarIndex":1,"exitBarIndex":1,"entryTime":2,"exitTime":2,"entryPrice":100,"exitPrice":95,"qty":2,"profit":-10}]"#
        ));
}

#[test]
fn strategy_exit_trailing_fixture_has_single_exit_order_and_trade() {
    let output = runtime_fixture_json("tests/fixtures/runtime/strategy_exit_trail_price_fill.pine");

    assert!(output.starts_with(&format!(
        r#"{{"schemaVersion":{},"#,
        PUBLIC_RUNTIME_SCHEMA_VERSION
    )));
    assert_eq!(
        strategy_orders_segment(&output)
            .matches(r#""direction":"strategy.exit""#)
            .count(),
        1
    );
    assert_eq!(output.matches(r#""trades":[{"#).count(), 1);
    assert!(output.contains(
            r#""orders":[{"id":"L","barIndex":1,"time":2,"direction":"strategy.long","qty":2,"price":2},{"id":"XT","barIndex":3,"time":4,"direction":"strategy.exit","qty":2,"price":3.5}]"#
        ));
    assert!(output.contains(
            r#""trades":[{"id":"L","entryBarIndex":1,"exitBarIndex":3,"entryTime":2,"exitTime":4,"entryPrice":2,"exitPrice":3.5,"qty":2,"profit":3}]"#
        ));
}

#[test]
fn strategy_exit_qty_fixture_has_partial_order_trade_and_remaining_position() {
    let output = runtime_fixture_json("tests/fixtures/runtime/strategy_exit_qty_stop_partial.pine");

    assert!(output.starts_with(&format!(
        r#"{{"schemaVersion":{},"#,
        PUBLIC_RUNTIME_SCHEMA_VERSION
    )));
    assert_eq!(
        strategy_orders_segment(&output)
            .matches(r#""direction":"strategy.exit""#)
            .count(),
        1
    );
    assert!(output.contains(
            r#""orders":[{"id":"L","barIndex":1,"time":2,"direction":"strategy.long","qty":2,"price":2},{"id":"XQ","barIndex":1,"time":2,"direction":"strategy.exit","qty":0.75,"price":2.5}]"#
        ));
    assert!(output.contains(
            r#""trades":[{"id":"L","entryBarIndex":1,"exitBarIndex":1,"entryTime":2,"exitTime":2,"entryPrice":2,"exitPrice":2.5,"qty":0.75,"profit":0.375}]"#
        ));
    assert!(output.contains(
            r#""position":[{"barIndex":1,"size":2,"avgPrice":2},{"barIndex":1,"size":1.25,"avgPrice":2}]"#
        ));
    assert!(!output.contains("pending"));
    assert!(!output.contains("remainingQty"));
}

#[test]
fn strategy_exit_qty_percent_fixture_has_absolute_qty_and_existing_shape() {
    let output =
        runtime_fixture_json("tests/fixtures/runtime/strategy_exit_qty_percent_stop_partial.pine");

    assert!(output.starts_with(&format!(
        r#"{{"schemaVersion":{},"#,
        PUBLIC_RUNTIME_SCHEMA_VERSION
    )));
    assert_eq!(
        strategy_orders_segment(&output)
            .matches(r#""direction":"strategy.exit""#)
            .count(),
        1
    );
    assert!(output.contains(
            r#""orders":[{"id":"L","barIndex":1,"time":2,"direction":"strategy.long","qty":2,"price":2},{"id":"XP","barIndex":1,"time":2,"direction":"strategy.exit","qty":1,"price":2.5}]"#
        ));
    assert!(output.contains(
            r#""trades":[{"id":"L","entryBarIndex":1,"exitBarIndex":1,"entryTime":2,"exitTime":2,"entryPrice":2,"exitPrice":2.5,"qty":1,"profit":0.5}]"#
        ));
    assert!(output.contains(
        r#""position":[{"barIndex":1,"size":2,"avgPrice":2},{"barIndex":1,"size":1,"avgPrice":2}]"#
    ));
    assert!(output.contains(r#""strategy":{"orders":"#));
    assert!(!output.contains("pending"));
    assert!(!output.contains("remainingQty"));
    assert!(!output.contains("qtyPercent"));
    assert!(!output.contains("qty_percent"));
}

#[test]
fn strategy_exit_reservation_fixture_has_host_stable_shape() {
    let output = runtime_fixture_json(
        "tests/fixtures/runtime/strategy_exit_reservation_mixed_side_precedence.pine",
    );

    assert!(output.starts_with(&format!(
        r#"{{"schemaVersion":{},"#,
        PUBLIC_RUNTIME_SCHEMA_VERSION
    )));
    assert_eq!(
        strategy_orders_segment(&output)
            .matches(r#""direction":"strategy.exit""#)
            .count(),
        2
    );
    assert!(output.contains(
            r#""orders":[{"id":"L","barIndex":1,"time":2,"direction":"strategy.long","qty":2,"price":2},{"id":"XS","barIndex":1,"time":2,"direction":"strategy.exit","qty":0.5,"price":2.5},{"id":"XL","barIndex":2,"time":3,"direction":"strategy.exit","qty":1.5,"price":1.5}]"#
        ));
    assert!(output.contains(
            r#""trades":[{"id":"L","entryBarIndex":1,"exitBarIndex":1,"entryTime":2,"exitTime":2,"entryPrice":2,"exitPrice":2.5,"qty":0.5,"profit":0.25},{"id":"L","entryBarIndex":1,"exitBarIndex":2,"entryTime":2,"exitTime":3,"entryPrice":2,"exitPrice":1.5,"qty":1.5,"profit":-0.75}]"#
        ));
    assert!(output.contains(
            r#""position":[{"barIndex":1,"size":2,"avgPrice":2},{"barIndex":1,"size":1.5,"avgPrice":2},{"barIndex":2,"size":0,"avgPrice":null}]"#
        ));
    assert!(output.contains(r#""strategy":{"orders":"#));
    assert!(output.contains(r#""equity":["#));
    assert!(output.contains(r#""diagnostics":[]}"#));
    assert!(!output.contains("pending"));
    assert!(!output.contains("remainingQty"));
    assert!(!output.contains("qtyPercent"));
    assert!(!output.contains("qty_percent"));
}

#[test]
fn strategy_exit_omitted_replaces_reservations_fixture_has_host_stable_shape() {
    let output = runtime_fixture_json(
        "tests/fixtures/runtime/strategy_exit_omitted_replaces_reservations.pine",
    );

    assert!(output.starts_with(&format!(
        r#"{{"schemaVersion":{},"#,
        PUBLIC_RUNTIME_SCHEMA_VERSION
    )));
    assert_eq!(
        strategy_orders_segment(&output)
            .matches(r#""direction":"strategy.exit""#)
            .count(),
        1
    );
    assert!(output.contains(
            r#""orders":[{"id":"L","barIndex":1,"time":2,"direction":"strategy.long","qty":2,"price":2},{"id":"XFULL","barIndex":2,"time":3,"direction":"strategy.exit","qty":2,"price":2.5}]"#
        ));
    assert!(output.contains(
            r#""trades":[{"id":"L","entryBarIndex":1,"exitBarIndex":2,"entryTime":2,"exitTime":3,"entryPrice":2,"exitPrice":2.5,"qty":2,"profit":1}]"#
        ));
    assert!(output.contains(
            r#""position":[{"barIndex":1,"size":2,"avgPrice":2},{"barIndex":2,"size":0,"avgPrice":null}]"#
        ));
    assert!(output.contains(r#""strategy":{"orders":"#));
    assert!(output.contains(r#""trades":["#));
    assert!(output.contains(r#""position":["#));
    assert!(output.contains(r#""equity":["#));
    assert!(output.contains(r#""diagnostics":[]}"#));
    assert!(!output.contains("pending"));
    assert!(!output.contains("reservation"));
    assert!(!output.contains("reservedQuantity"));
    assert!(!output.contains("reserved_quantity"));
    assert!(!output.contains("remainingQuantity"));
    assert!(!output.contains("remaining_quantity"));
    assert!(!output.contains("remainingQty"));
    assert!(!output.contains("qtyPercent"));
    assert!(!output.contains("qty_percent"));
    assert!(!output.contains("triggerSide"));
    assert!(!output.contains("activation"));
    assert!(!output.contains("exitReason"));
}

#[test]
fn strategy_exit_bracket_reservation_fixture_has_host_stable_shape() {
    let output = runtime_fixture_json(
        "tests/fixtures/runtime/strategy_exit_reservation_bracket_host_parity.pine",
    );

    assert!(output.starts_with(&format!(
        r#"{{"schemaVersion":{},"#,
        PUBLIC_RUNTIME_SCHEMA_VERSION
    )));
    assert_eq!(
        strategy_orders_segment(&output)
            .matches(r#""direction":"strategy.exit""#)
            .count(),
        2
    );
    assert!(output.contains(
            r#""orders":[{"id":"L","barIndex":1,"time":2,"direction":"strategy.long","qty":2,"price":2},{"id":"XB1","barIndex":1,"time":2,"direction":"strategy.exit","qty":0.5,"price":2},{"id":"XB2","barIndex":2,"time":3,"direction":"strategy.exit","qty":1,"price":3}]"#
        ));
    assert!(output.contains(
            r#""trades":[{"id":"L","entryBarIndex":1,"exitBarIndex":1,"entryTime":2,"exitTime":2,"entryPrice":2,"exitPrice":2,"qty":0.5,"profit":0},{"id":"L","entryBarIndex":1,"exitBarIndex":2,"entryTime":2,"exitTime":3,"entryPrice":2,"exitPrice":3,"qty":1,"profit":1}]"#
        ));
    assert!(output.contains(
            r#""position":[{"barIndex":1,"size":2,"avgPrice":2},{"barIndex":1,"size":1.5,"avgPrice":2},{"barIndex":2,"size":0.5,"avgPrice":2}]"#
        ));
    assert!(output.contains(r#""strategy":{"orders":"#));
    assert!(output.contains(r#""equity":["#));
    assert!(output.contains(r#""diagnostics":[]}"#));
    assert!(!output.contains("pending"));
    assert!(!output.contains("reservedQuantity"));
    assert!(!output.contains("reserved_quantity"));
    assert!(!output.contains("remainingQty"));
    assert!(!output.contains("remaining_quantity"));
    assert!(!output.contains("qtyPercent"));
    assert!(!output.contains("qty_percent"));
    assert!(!output.contains("bracketLeg"));
    assert!(!output.contains("bracket"));
}

#[test]
fn strategy_exit_trailing_reservation_fixture_has_host_stable_shape() {
    let output = runtime_fixture_json(
        "tests/fixtures/runtime/strategy_exit_reservation_trailing_host_parity.pine",
    );

    assert!(output.starts_with(&format!(
        r#"{{"schemaVersion":{},"#,
        PUBLIC_RUNTIME_SCHEMA_VERSION
    )));
    assert_eq!(
        strategy_orders_segment(&output)
            .matches(r#""direction":"strategy.exit""#)
            .count(),
        2
    );
    assert!(output.contains(
            r#""orders":[{"id":"L","barIndex":1,"time":2,"direction":"strategy.long","qty":2,"price":3},{"id":"XT1","barIndex":3,"time":4,"direction":"strategy.exit","qty":0.75,"price":3.5},{"id":"XT2","barIndex":4,"time":5,"direction":"strategy.exit","qty":1.25,"price":3.3}]"#
        ));
    assert!(output.contains(
            r#""trades":[{"id":"L","entryBarIndex":1,"exitBarIndex":3,"entryTime":2,"exitTime":4,"entryPrice":3,"exitPrice":3.5,"qty":0.75,"profit":0.375},{"id":"L","entryBarIndex":1,"exitBarIndex":4,"entryTime":2,"exitTime":5,"entryPrice":3,"exitPrice":3.3,"qty":1.25,"profit":0.3749999999999998}]"#
        ));
    assert!(output.contains(
            r#""position":[{"barIndex":1,"size":2,"avgPrice":3},{"barIndex":3,"size":1.25,"avgPrice":3},{"barIndex":4,"size":0,"avgPrice":null}]"#
        ));
    assert!(output.contains(r#""strategy":{"orders":"#));
    assert!(output.contains(r#""equity":["#));
    assert!(output.contains(r#""diagnostics":[]}"#));
    assert!(!output.contains("pending"));
    assert!(!output.contains("reservedQuantity"));
    assert!(!output.contains("reserved_quantity"));
    assert!(!output.contains("remainingQty"));
    assert!(!output.contains("remaining_quantity"));
    assert!(!output.contains("qtyPercent"));
    assert!(!output.contains("qty_percent"));
    assert!(!output.contains("trailing"));
    assert!(!output.contains("stop_price"));
    assert!(!output.contains("activation"));
    assert!(!output.contains("exitReason"));
}

#[test]
fn matrix_output_matches_golden_snapshot() {
    assert_snapshot("matrix.json", &matrix_json(&conformance_entries()));
}

fn runtime_fixture_json(fixture: &str) -> String {
    let workspace = workspace_dir();
    let source_text = fs::read_to_string(workspace.join(fixture)).expect("fixture source");
    let source = SourceFile::new(fixture, source_text);
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{fixture} diagnostics: {:?}",
        analysis.diagnostics
    );
    let bars = parse_bars_csv(runtime_fixture_bars_csv(fixture)).expect("bars fixture");
    let result =
        run_historical(&analysis.hir.expect("fixture HIR"), &bars).expect("runtime result");
    public_runtime_result_json(&result)
}

fn runtime_fixture_error(fixture: &str) -> String {
    let workspace = workspace_dir();
    let source_text = fs::read_to_string(workspace.join(fixture)).expect("fixture source");
    let source = SourceFile::new(fixture, source_text);
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{fixture} diagnostics: {:?}",
        analysis.diagnostics
    );
    let bars = parse_bars_csv(runtime_fixture_bars_csv(fixture)).expect("bars fixture");
    run_historical(&analysis.hir.expect("fixture HIR"), &bars)
        .expect_err("runtime fixture should fail")
        .message
}

fn runtime_library_fixture_error(fixture: &str, library_sources: &[(&str, &str)]) -> String {
    let workspace = workspace_dir();
    let source_text = fs::read_to_string(workspace.join(fixture)).expect("fixture source");
    let source = SourceFile::new(fixture, source_text);
    let libraries = library_sources
        .iter()
        .map(|(key, path)| {
            let library_text =
                fs::read_to_string(workspace.join(path)).expect("library fixture source");
            ((*key).to_owned(), SourceFile::new(*path, library_text))
        })
        .collect();
    let input = AnalysisInput::with_library_sources(source, libraries)
        .expect("library fixture input should be valid");
    let analysis = analyze_input(&input);
    assert!(
        analysis.diagnostics.is_empty(),
        "{fixture} diagnostics: {:?}",
        analysis.diagnostics
    );
    let bars = parse_bars_csv(runtime_fixture_bars_csv(fixture)).expect("bars fixture");
    run_historical(&analysis.hir.expect("fixture HIR"), &bars)
        .expect_err("runtime fixture should fail")
        .message
}

fn runtime_library_fixture_json(fixture: &str, library_sources: &[(&str, &str)]) -> String {
    let workspace = workspace_dir();
    let source_text = fs::read_to_string(workspace.join(fixture)).expect("fixture source");
    let source = SourceFile::new(fixture, source_text);
    let libraries = library_sources
        .iter()
        .map(|(key, path)| {
            let library_text =
                fs::read_to_string(workspace.join(path)).expect("library fixture source");
            ((*key).to_owned(), SourceFile::new(*path, library_text))
        })
        .collect();
    let input = AnalysisInput::with_library_sources(source, libraries)
        .expect("library fixture input should be valid");
    let analysis = analyze_input(&input);
    assert!(
        analysis.diagnostics.is_empty(),
        "{fixture} diagnostics: {:?}",
        analysis.diagnostics
    );
    let bars = parse_bars_csv(runtime_fixture_bars_csv(fixture)).expect("bars fixture");
    let result =
        run_historical(&analysis.hir.expect("fixture HIR"), &bars).expect("runtime result");
    public_runtime_result_json(&result)
}

fn runtime_fixture_bars_csv(fixture: &str) -> &'static str {
    match fixture {
        "tests/fixtures/runtime/strategy_exit_loss.pine" => {
            include_str!("../../../tests/fixtures/runtime/strategy_exit_loss_bars.csv")
        }
        "tests/fixtures/runtime/strategy_trade_outcome_counts.pine" => {
            include_str!("../../../tests/fixtures/runtime/strategy_trade_outcome_counts_bars.csv")
        }
        "tests/fixtures/runtime/strategy_profit_percent_state.pine" => {
            include_str!("../../../tests/fixtures/runtime/strategy_trade_outcome_counts_bars.csv")
        }
        "tests/fixtures/runtime/strategy_exit_profit_loss_interactions.pine" => include_str!(
            "../../../tests/fixtures/runtime/strategy_exit_profit_loss_interactions_bars.csv"
        ),
        "tests/fixtures/runtime/strategy_pyramiding_limit_same_tick_limit_entries.pine" => {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_pyramiding_limit_same_tick_limit_entries_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_pyramiding_limit_same_tick_stop_entries.pine" => {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_pyramiding_limit_same_tick_stop_entries_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_pyramiding_limit_same_tick_stop_limit_entries.pine" => {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_pyramiding_limit_same_tick_stop_limit_entries_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_exit_bracket_loss_profit_loss_fill.pine" => {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_exit_bracket_loss_profit_loss_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_exit_bracket_mixed_pairs.pine" => {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_exit_bracket_mixed_pairs_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_exit_bracket_replacement.pine" => {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_exit_bracket_replacement_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_exit_bracket_both_hit.pine" => {
            include_str!("../../../tests/fixtures/runtime/strategy_exit_bracket_both_hit_bars.csv")
        }
        "tests/fixtures/runtime/strategy_exit_trail_price_fill.pine"
        | "tests/fixtures/runtime/strategy_exit_trail_points_fill.pine"
        | "tests/fixtures/runtime/strategy_exit_active_entry_trail_points_attachment.pine"
        | "tests/fixtures/runtime/strategy_exit_active_entry_stop_profit_bracket.pine"
        | "tests/fixtures/runtime/strategy_exit_active_entry_loss_limit_bracket.pine"
        | "tests/fixtures/runtime/strategy_exit_active_entry_loss_profit_bracket.pine"
        | "tests/fixtures/runtime/strategy_exit_trailing_activation_bar.pine"
        | "tests/fixtures/runtime/strategy_exit_trailing_ratchet.pine"
        | "tests/fixtures/runtime/strategy_exit_trailing_repeated.pine"
        | "tests/fixtures/runtime/strategy_exit_trailing_replacement.pine"
        | "tests/fixtures/runtime/strategy_exit_omitted_trailing_replacement.pine"
        | "tests/fixtures/runtime/strategy_exit_trailing_invalid.pine"
        | "tests/fixtures/runtime/strategy_exit_trailing_close_cancel.pine"
        | "tests/fixtures/runtime/strategy_exit_trailing_interactions.pine"
        | "tests/fixtures/runtime/strategy_exit_trailing_state.pine"
        | "tests/fixtures/runtime/strategy_exit_qty_trailing_partial.pine"
        | "tests/fixtures/runtime/strategy_exit_qty_percent_trailing_partial.pine" => {
            include_str!("../../../tests/fixtures/runtime/strategy_exit_trailing_bars.csv")
        }
        "tests/fixtures/runtime/strategy_exit_qty_precedence_trailing.pine" => {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_exit_qty_precedence_trailing_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_exit_reservation_qty_trailing_price_multi.pine"
        | "tests/fixtures/runtime/strategy_exit_reservation_qty_trailing_points_multi.pine"
        | "tests/fixtures/runtime/strategy_exit_reservation_qty_trailing_replacement.pine"
        | "tests/fixtures/runtime/strategy_exit_reservation_qty_trailing_clamp.pine"
        | "tests/fixtures/runtime/strategy_exit_reservation_trailing_state.pine"
        | "tests/fixtures/runtime/strategy_exit_reservation_qty_percent_trailing_multi.pine"
        | "tests/fixtures/runtime/strategy_exit_reservation_qty_mixed_trailing_multi.pine"
        | "tests/fixtures/runtime/strategy_exit_reservation_qty_percent_trailing_replacement.pine"
        | "tests/fixtures/runtime/strategy_exit_reservation_qty_percent_trailing_clamp.pine" => {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_exit_reservation_trailing_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_exit_reservation_trailing_host_parity.pine" => {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_exit_reservation_trailing_host_parity_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_exit_reservation_trailing_single_downside_order.pine"
        | "tests/fixtures/runtime/strategy_exit_reservation_trailing_bracket_downside_order.pine"
        | "tests/fixtures/runtime/strategy_exit_reservation_trailing_mixed_side_precedence.pine"
        | "tests/fixtures/runtime/strategy_exit_reservation_trailing_activation_mixed_fill.pine"
        | "tests/fixtures/runtime/strategy_exit_reservation_trailing_replacement_mixed.pine"
        | "tests/fixtures/runtime/strategy_exit_reservation_trailing_mixed_state.pine" => {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_exit_reservation_trailing_mixed_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_opentrades_fields.pine" => {
            include_str!("../../../tests/fixtures/runtime/strategy_opentrades_fields_bars.csv")
        }
        "tests/fixtures/runtime/strategy_margin_call_long.pine" => {
            include_str!("../../../tests/fixtures/runtime/strategy_margin_call_long_bars.csv")
        }
        "tests/fixtures/runtime/strategy_pyramiding_exit_from_entry.pine" => include_str!(
            "../../../tests/fixtures/runtime/strategy_pyramiding_exit_from_entry_bars.csv"
        ),
        "tests/fixtures/runtime/strategy_pyramiding_exit_profit_from_entry.pine" => {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_pyramiding_exit_profit_from_entry_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_pyramiding_exit_bracket_from_entry.pine" => {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_pyramiding_exit_profit_from_entry_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_pyramiding_exit_trail_points_from_entry.pine" => {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_pyramiding_exit_trail_points_from_entry_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_pyramiding_exit_omitted_from_entry_current.pine" => {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_from_entry_current_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_pyramiding_exit_omitted_from_entry_persistent.pine" => {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_from_entry_persistent_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_pyramiding_exit_omitted_profit_from_entries.pine" => {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_profit_from_entries_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_pyramiding_exit_omitted_profit_same_id.pine" => {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_profit_same_id_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_pyramiding_exit_omitted_profit_persistent_from_entries.pine" =>
        {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_profit_persistent_from_entries_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_pyramiding_exit_omitted_profit_persistent_same_id.pine" => {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_profit_persistent_same_id_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_from_entries.pine" => {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_from_entries_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_same_id.pine" => {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_same_id_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_persistent_from_entries.pine" =>
        {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_persistent_from_entries_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_persistent_same_id.pine" => {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_persistent_same_id_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_profit_bracket_from_entries.pine" =>
        {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_profit_bracket_from_entries_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_profit_bracket_same_id.pine" =>
        {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_profit_bracket_same_id_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_profit_bracket_persistent_from_entries.pine" =>
        {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_profit_bracket_persistent_from_entries_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_profit_bracket_persistent_same_id.pine" =>
        {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_profit_bracket_persistent_same_id_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_pyramiding_exit_omitted_stop_profit_bracket_from_entries.pine" =>
        {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_stop_profit_bracket_from_entries_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_pyramiding_exit_omitted_stop_profit_bracket_same_id.pine" =>
        {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_stop_profit_bracket_same_id_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_pyramiding_exit_omitted_stop_profit_bracket_persistent_from_entries.pine" =>
        {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_stop_profit_bracket_persistent_from_entries_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_pyramiding_exit_omitted_stop_profit_bracket_persistent_same_id.pine" =>
        {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_stop_profit_bracket_persistent_same_id_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_limit_bracket_from_entries.pine" =>
        {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_limit_bracket_from_entries_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_limit_bracket_same_id.pine" =>
        {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_limit_bracket_same_id_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_limit_bracket_persistent_from_entries.pine" =>
        {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_limit_bracket_persistent_from_entries_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_limit_bracket_persistent_same_id.pine" =>
        {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_limit_bracket_persistent_same_id_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_pyramiding_exit_omitted_stop_limit_bracket_from_entries.pine" =>
        {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_stop_limit_bracket_from_entries_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_pyramiding_exit_omitted_stop_limit_bracket_same_id.pine" =>
        {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_stop_limit_bracket_same_id_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_pyramiding_exit_omitted_stop_limit_bracket_persistent_from_entries.pine" =>
        {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_stop_limit_bracket_persistent_from_entries_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_pyramiding_exit_omitted_stop_limit_bracket_persistent_same_id.pine" =>
        {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_stop_limit_bracket_persistent_same_id_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_pyramiding_exit_omitted_trail_price_from_entries.pine" => {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_trail_price_from_entries_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_pyramiding_exit_omitted_trail_price_same_id.pine" => {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_trail_price_same_id_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_pyramiding_exit_omitted_trail_price_persistent_from_entries.pine" =>
        {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_trail_price_persistent_from_entries_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_pyramiding_exit_omitted_trail_price_persistent_same_id.pine" =>
        {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_trail_price_persistent_same_id_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_pyramiding_exit_omitted_trail_points_from_entries.pine" => {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_trail_points_from_entries_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_pyramiding_exit_omitted_trail_points_same_id.pine" => {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_trail_points_same_id_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_pyramiding_exit_omitted_trail_points_persistent_from_entries.pine" =>
        {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_trail_points_persistent_from_entries_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_pyramiding_exit_omitted_trail_points_persistent_same_id.pine" =>
        {
            include_str!(
                "../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_trail_points_persistent_same_id_bars.csv"
            )
        }
        "tests/fixtures/runtime/strategy_pyramiding_exit_same_id.pine" => include_str!(
            "../../../tests/fixtures/runtime/strategy_pyramiding_exit_same_id_bars.csv"
        ),
        _ => crate::runtime_snapshots::runtime_fixture_bars_csv(fixture)
            .unwrap_or(include_str!("../../../tests/fixtures/runtime/bars.csv")),
    }
}

fn assert_snapshot(name: &str, actual: &str) {
    let snapshot_path = workspace_dir().join("tests/snapshots").join(name);
    if env::var_os("UPDATE_SNAPSHOTS").is_some() {
        fs::create_dir_all(snapshot_path.parent().expect("snapshot parent"))
            .expect("create snapshot dir");
        fs::write(&snapshot_path, format!("{actual}\n")).expect("write snapshot");
        return;
    }
    let expected = fs::read_to_string(&snapshot_path)
        .unwrap_or_else(|err| panic!("failed to read {}: {err}", snapshot_path.display()));
    assert_eq!(actual.trim_end(), expected.trim_end(), "{name} changed");
}
fn workspace_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..")
}
fn pine_fixture_paths(workspace: &Path, relative_dir: &str) -> BTreeSet<String> {
    let fixture_dir = workspace.join(relative_dir);
    fs::read_dir(&fixture_dir)
        .unwrap_or_else(|err| panic!("failed to read {}: {err}", fixture_dir.display()))
        .map(|entry| {
            entry
                .unwrap_or_else(|err| {
                    panic!(
                        "failed to read fixture entry in {}: {err}",
                        fixture_dir.display()
                    )
                })
                .path()
        })
        .filter(|path| path.extension().and_then(|extension| extension.to_str()) == Some("pine"))
        .map(|path| {
            path.strip_prefix(workspace)
                .unwrap_or_else(|err| {
                    panic!(
                        "fixture path {} should be under {}: {err}",
                        path.display(),
                        workspace.display()
                    )
                })
                .to_string_lossy()
                .replace('\\', "/")
        })
        .collect()
}
fn rust_source_files(root: &Path) -> Vec<PathBuf> {
    let mut files = Vec::new();
    collect_rust_source_files(root, &mut files);
    files
}
fn collect_rust_source_files(path: &Path, files: &mut Vec<PathBuf>) {
    if path.is_file() {
        if path.extension().and_then(|extension| extension.to_str()) == Some("rs") {
            files.push(path.to_owned());
        }
        return;
    }
    let Ok(entries) = fs::read_dir(path) else {
        return;
    };
    for entry in entries {
        let entry = entry.expect("source directory entry should be readable");
        collect_rust_source_files(&entry.path(), files);
    }
}

fn diagnostic_codes_in_text(text: &str) -> BTreeSet<String> {
    let mut codes = BTreeSet::new();
    for (index, _) in text.match_indices("E_") {
        if index > 0 {
            let previous = text[..index].chars().next_back().expect("previous char");
            if previous.is_ascii_alphanumeric() || previous == '_' {
                continue;
            }
        }
        let code: String = text[index..]
            .chars()
            .take_while(|ch| ch.is_ascii_uppercase() || ch.is_ascii_digit() || *ch == '_')
            .collect();
        if code.len() > 2 {
            codes.insert(code);
        }
    }
    codes
}
