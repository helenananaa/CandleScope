use super::*;
use pine_runtime::{PUBLIC_ANALYSIS_SCHEMA_VERSION, PUBLIC_RUNTIME_SCHEMA_VERSION};
use std::{collections::HashMap, env, fs, path::PathBuf};

#[test]
fn analyzes_script_to_json() {
    let output = analyze_script("indicator(\"demo\")\nplot(close)\n");
    let parsed: serde_json::Value = serde_json::from_str(&output).expect("strict JSON output");

    assert_eq!(
        parsed["schemaVersion"],
        serde_json::json!(PUBLIC_ANALYSIS_SCHEMA_VERSION)
    );
    assert_eq!(parsed["executable"], serde_json::json!(true));
    assert_eq!(parsed["diagnostics"], serde_json::json!([]));
    assert_eq!(parsed["inputs"], serde_json::json!([]));
    assert!(
        parsed["compatibility"]["supported"]
            .as_array()
            .expect("supported features should be an array")
            .iter()
            .any(|feature| feature["feature"] == serde_json::json!("plot"))
    );
}

#[test]
fn analyzes_script_input_call_sites_to_json() {
    let output = analyze_script(
        "indicator(\"inputs\")\nlength = input.int(2, \"Length\")\nmode = input.string(\"SMA\", title=\"Mode\")\nplot(close)\n",
    );
    let parsed: serde_json::Value = serde_json::from_str(&output).expect("strict JSON output");

    assert_eq!(
        parsed["schemaVersion"],
        serde_json::json!(PUBLIC_ANALYSIS_SCHEMA_VERSION)
    );
    assert_eq!(parsed["diagnostics"], serde_json::json!([]));
    assert_eq!(parsed["inputs"][0]["name"], serde_json::json!("input.int"));
    assert_eq!(parsed["inputs"][0]["title"], serde_json::json!("Length"));
    assert!(parsed["inputs"][0]["callSiteId"].as_u64().is_some());
    assert_eq!(
        parsed["inputs"][1]["name"],
        serde_json::json!("input.string")
    );
    assert_eq!(parsed["inputs"][1]["title"], serde_json::json!("Mode"));
    assert!(parsed["inputs"][1]["callSiteId"].as_u64().is_some());
}

#[test]
fn runs_script_from_csv_to_json() {
    let output = run_script_csv(
        "indicator(\"demo\")\nplot(close)\n",
        "time,open,high,low,close,volume\n0,1,1,1,1,1\n1,2,2,2,2,1\n",
    )
    .expect("script should run");
    let parsed: serde_json::Value = serde_json::from_str(&output).expect("strict JSON output");

    assert_eq!(
        parsed["schemaVersion"],
        serde_json::json!(PUBLIC_RUNTIME_SCHEMA_VERSION)
    );
    assert_eq!(parsed["plots"][0]["values"], serde_json::json!([1, 2]));
    assert_eq!(parsed["plotChars"], serde_json::json!([]));
    assert_eq!(parsed["plotShapes"], serde_json::json!([]));
    assert_eq!(parsed["plotArrows"], serde_json::json!([]));
    assert_eq!(parsed["plotBars"], serde_json::json!([]));
    assert_eq!(parsed["plotCandles"], serde_json::json!([]));
    assert_eq!(parsed["labels"], serde_json::json!([]));
    assert_eq!(parsed["lines"], serde_json::json!([]));
    assert_eq!(parsed["lineFills"], serde_json::json!([]));
    assert_eq!(parsed["polylines"], serde_json::json!([]));
    assert_eq!(parsed["boxes"], serde_json::json!([]));
    assert_eq!(parsed["tables"], serde_json::json!([]));
    assert_eq!(parsed["alerts"], serde_json::json!([]));
}

#[test]
fn runs_script_from_csv_with_input_overrides_to_json() {
    let source = r##"indicator("input overrides")
length = input.int(2, "Length")
scale = input.float(1.0, "Scale")
enabled = input.bool(true, "Enabled")
mode = input.string("SMA", "Mode")
shade = input.color(color.red, "Shade")
base = enabled and mode == "SMA" ? ta.sma(close, length) * scale : open
plot(base)
plot(color.r(shade))
"##;
    let bars = "time,open,high,low,close,volume\n0,1,1,1,1,1\n1,2,2,2,2,1\n2,3,3,3,3,1\n";
    let input_ids = input_call_ids_by_title(source);
    let overrides_json = input_overrides_json(&[
        (input_ids["Length"], serde_json::json!(1)),
        (input_ids["Scale"], serde_json::json!(2.0)),
        (input_ids["Enabled"], serde_json::json!(true)),
        (input_ids["Mode"], serde_json::json!("SMA")),
        (input_ids["Shade"], serde_json::json!("#4CAF50")),
    ]);

    let outputs = [
        run_script_csv_with_input_overrides(source, bars, &overrides_json)
            .expect("input override output"),
        run_script_csv_with_request_bars_and_input_overrides(source, bars, "{}", &overrides_json)
            .expect("request bars and input override output"),
        run_script_csv_with_libraries_and_input_overrides(source, bars, "{}", &overrides_json)
            .expect("libraries and input override output"),
        run_script_csv_with_libraries_and_request_bars_and_input_overrides(
            source,
            bars,
            "{}",
            "{}",
            &overrides_json,
        )
        .expect("libraries, request bars, and input override output"),
        compile_script(source)
            .expect("program")
            .run_csv_with_input_overrides(bars, &overrides_json)
            .expect("program input override output"),
        compile_script(source)
            .expect("program")
            .run_csv_with_request_bars_and_input_overrides(bars, "{}", &overrides_json)
            .expect("program request bars and input override output"),
    ];

    for output in outputs {
        let parsed: serde_json::Value = serde_json::from_str(&output).expect("strict JSON output");

        assert_eq!(parsed["plots"][0]["values"], serde_json::json!([2, 4, 6]));
        assert_eq!(
            parsed["plots"][1]["values"],
            serde_json::json!([76, 76, 76])
        );
    }
}

#[test]
fn generic_color_input_override_accepts_hex_string() {
    let source = r##"indicator("generic color")
shade = input(color.red, "Shade")
plot(color.r(shade))
"##;
    let bars = "time,open,high,low,close,volume\n0,1,1,1,1,1\n";
    let input_ids = input_call_ids_by_title(source);
    let overrides_json =
        input_overrides_json(&[(input_ids["Shade"], serde_json::json!("#4CAF50"))]);

    let output = run_script_csv_with_input_overrides(source, bars, &overrides_json)
        .expect("generic color input override should run");
    let parsed: serde_json::Value = serde_json::from_str(&output).expect("strict JSON output");

    assert_eq!(parsed["plots"][0]["values"], serde_json::json!([76]));
}

#[test]
fn input_overrides_report_unknown_call_site() {
    let message = run_script_csv_with_input_overrides_internal(
        "indicator(\"inputs\")\nlength = input.int(2, \"Length\")\nplot(ta.sma(close, length))\n",
        "time,open,high,low,close,volume\n0,1,1,1,1,1\n",
        r#"{"999999":1}"#,
    )
    .expect_err("unknown input override callSiteId should fail");

    assert!(message.contains("unknown callSiteId 999999"));
}

#[test]
fn runs_alert_frequency_fixture_from_csv_to_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/alert_frequency.pine"),
        "time,open,high,low,close,volume\n0,1,1,1,1,1\n1,2,2,2,2,1\n",
    )
    .expect("alert frequency fixture should run");
    let parsed: serde_json::Value = serde_json::from_str(&output).expect("strict JSON output");

    assert_eq!(
        parsed["alerts"],
        serde_json::json!([
            {
                "id": 1,
                "barIndex": 0,
                "time": 0,
                "message": "Default once",
                "source": "alert"
            },
            {
                "id": 2,
                "barIndex": 0,
                "time": 0,
                "message": "Explicit once",
                "source": "alert"
            },
            {
                "id": 3,
                "barIndex": 0,
                "time": 0,
                "message": "All",
                "source": "alert"
            },
            {
                "id": 3,
                "barIndex": 0,
                "time": 0,
                "message": "All",
                "source": "alert"
            },
            {
                "id": 4,
                "barIndex": 0,
                "time": 0,
                "message": "Close",
                "source": "alert"
            }
        ])
    );
}

#[test]
fn run_script_csv_serializes_non_finite_values_as_json_null() {
    let output = run_script_csv(
        "indicator(\"nonfinite\")\nplot(1.0 / 0.0)\n",
        "time,open,high,low,close,volume\n0,1,1,1,1,1\n",
    )
    .expect("script should run");

    let parsed: serde_json::Value = serde_json::from_str(&output).expect("strict JSON output");
    assert_eq!(parsed["plots"][0]["values"][0], serde_json::Value::Null);
    assert!(!output.contains("NaN"));
    assert!(!output.contains("Infinity"));
}

#[test]
fn run_script_csv_returns_plotchar_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/plotchar.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("plotchar fixture should run");

    assert_snapshot("runtime_plotchar.json", &output);
}

#[test]
fn run_script_csv_returns_plotshape_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/plotshape.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("plotshape fixture should run");

    assert_snapshot("runtime_plotshape.json", &output);
}

#[test]
fn run_script_csv_returns_plotarrow_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/plotarrow.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("plotarrow fixture should run");

    assert_snapshot("runtime_plotarrow.json", &output);
}

#[test]
fn run_script_csv_returns_plotbar_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/plotbar.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("plotbar fixture should run");

    assert_snapshot("runtime_plotbar.json", &output);
}

#[test]
fn run_script_csv_returns_plotcandle_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/plotcandle.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("plotcandle fixture should run");

    assert_snapshot("runtime_plotcandle.json", &output);
}

#[test]
fn run_script_csv_returns_color_outputs_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/color_outputs.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("color outputs fixture should run");

    assert_snapshot("runtime_color_outputs.json", &output);
}

#[test]
fn run_script_csv_returns_chart_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/chart.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("chart fixture should run");

    assert_snapshot("runtime_chart.json", &output);
}

#[test]
fn run_script_csv_returns_ticker_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/ticker.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("ticker fixture should run");

    assert_snapshot("runtime_ticker.json", &output);
}

#[test]
fn run_script_csv_returns_hline_fill_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/io.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("hline/fill fixture should run");

    assert_snapshot("runtime_hline_fill.json", &output);
}

#[test]
fn run_script_csv_returns_alertcondition_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/alertcondition.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("alertcondition fixture should run");

    assert_snapshot("runtime_alertcondition.json", &output);
}

#[test]
fn run_script_csv_returns_alert_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/alert.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("alert fixture should run");

    assert_snapshot("runtime_alert.json", &output);
}

#[test]
fn run_script_csv_returns_dynamic_alert_message_events() {
    let output = run_script_csv(
        "indicator(\"alerts\")\nalert(str.tostring(close))\n",
        "time,open,high,low,close,volume\n0,1,1,1,1,1\n1,2,2,2,2,1\n2,3,3,3,3,1\n",
    )
    .expect("dynamic alert message script should run");
    let parsed: serde_json::Value = serde_json::from_str(&output).expect("strict JSON output");

    assert_eq!(
        parsed["alerts"],
        serde_json::json!([
            {
                "id": 1,
                "barIndex": 0,
                "time": 0,
                "message": "1",
                "source": "alert"
            },
            {
                "id": 1,
                "barIndex": 1,
                "time": 1,
                "message": "2",
                "source": "alert"
            },
            {
                "id": 1,
                "barIndex": 2,
                "time": 2,
                "message": "3",
                "source": "alert"
            }
        ])
    );
}

#[test]
fn run_script_csv_returns_label_new_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/label_new.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("label.new fixture should run");

    assert_snapshot("runtime_label_new.json", &output);
}

#[test]
fn run_script_csv_returns_label_mutation_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/label_mutation.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("label mutation fixture should run");

    assert_snapshot("runtime_label_mutation.json", &output);
}

#[test]
fn run_script_csv_returns_label_control_flow_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/label_control_flow.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("label control-flow fixture should run");

    assert_snapshot("runtime_label_control_flow.json", &output);
}

#[test]
fn run_script_csv_returns_label_delete_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/label_delete.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("label delete fixture should run");

    assert_snapshot("runtime_label_delete.json", &output);
}

#[test]
fn run_script_csv_returns_label_copy_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/label_copy.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("label copy fixture should run");

    assert_snapshot("runtime_label_copy.json", &output);
}

#[test]
fn run_script_csv_returns_label_getters_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/label_getters.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("label getters fixture should run");

    assert_snapshot("runtime_label_getters.json", &output);
}

#[test]
fn run_script_csv_returns_label_options_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/label_options.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("label options fixture should run");

    assert_snapshot("runtime_label_options.json", &output);
}

#[test]
fn run_script_csv_returns_label_xloc_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/label_xloc.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("label xloc fixture should run");

    assert_snapshot("runtime_label_xloc.json", &output);
}

#[test]
fn run_script_csv_returns_label_yloc_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/label_yloc.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("label yloc fixture should run");

    assert_snapshot("runtime_label_yloc.json", &output);
}

#[test]
fn run_script_csv_returns_label_array_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/label_array.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("label array fixture should run");

    assert_snapshot("runtime_label_array.json", &output);
}

#[test]
fn run_script_csv_returns_scalar_typed_declarations_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/scalar_typed_declarations.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("scalar typed declarations fixture should run");

    assert_snapshot("runtime_scalar_typed_declarations.json", &output);
}

#[test]
fn run_script_csv_returns_chart_point_typed_decl_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/chart_point_typed_decl.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("chart point typed declaration fixture should run");

    assert_snapshot("runtime_chart_point_typed_decl.json", &output);
}

#[test]
fn run_script_csv_returns_array_typed_declarations_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/array_typed_declarations.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("array typed declarations fixture should run");

    assert_snapshot("runtime_array_typed_declarations.json", &output);
}

#[test]
fn run_script_csv_returns_chart_point_array_typed_declarations_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/chart_point_array_typed_declarations.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("chart point array typed declarations fixture should run");

    assert_snapshot("runtime_chart_point_array_typed_declarations.json", &output);
}

#[test]
fn run_script_csv_returns_object_array_typed_declarations_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/object_array_typed_declarations.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("object array typed declarations fixture should run");

    assert_snapshot("runtime_object_array_typed_declarations.json", &output);
}

#[test]
fn run_script_csv_returns_drawing_typed_declarations_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/drawing_typed_declarations.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("drawing typed declarations fixture should run");

    assert_snapshot("runtime_drawing_typed_declarations.json", &output);
}

#[test]
fn run_script_csv_returns_array_helpers_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/array_helpers.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("array helpers fixture should run");

    assert_snapshot("runtime_array_helpers.json", &output);
}

#[test]
fn run_script_csv_returns_array_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/array.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("array fixture should run");

    assert_snapshot("runtime_array.json", &output);
}

#[test]
fn run_script_csv_returns_array_methods_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/array_methods.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("array methods fixture should run");

    assert_snapshot("runtime_array_methods.json", &output);
}

#[test]
fn run_script_csv_returns_computed_array_operands_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/computed_array_operands.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("computed array operands fixture should run");

    assert_snapshot("runtime_computed_array_operands.json", &output);
}

#[test]
fn run_script_csv_returns_array_type_alias_declarations_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/array_type_alias_declarations.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("array type-alias declarations fixture should run");

    assert_snapshot("runtime_array_type_alias_declarations.json", &output);
}

#[test]
fn run_script_csv_returns_array_from_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/array_from.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("array from fixture should run");

    assert_snapshot("runtime_array_from.json", &output);
}

#[test]
fn run_script_csv_returns_array_insert_remove_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/array_insert_remove.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("array insert remove fixture should run");

    assert_snapshot("runtime_array_insert_remove.json", &output);
}

#[test]
fn run_script_csv_returns_array_fill_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/array_fill.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("array fill fixture should run");

    assert_snapshot("runtime_array_fill.json", &output);
}

#[test]
fn run_script_csv_returns_array_clear_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/array_clear.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("array clear fixture should run");

    assert_snapshot("runtime_array_clear.json", &output);
}

#[test]
fn run_script_csv_returns_array_references_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/array_references.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("array references fixture should run");

    assert_snapshot("runtime_array_references.json", &output);
}

#[test]
fn run_script_csv_returns_array_history_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/array_history.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("array history fixture should run");

    assert_snapshot("runtime_array_history.json", &output);
}

#[test]
fn run_script_csv_returns_array_label_history_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/array_label_history.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("array label history fixture should run");

    assert_snapshot("runtime_array_label_history.json", &output);
}

#[test]
fn run_script_csv_returns_array_line_history_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/array_line_history.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("array line history fixture should run");

    assert_snapshot("runtime_array_line_history.json", &output);
}

#[test]
fn run_script_csv_returns_array_box_history_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/array_box_history.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("array box history fixture should run");

    assert_snapshot("runtime_array_box_history.json", &output);
}

#[test]
fn run_script_csv_returns_array_linefill_history_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/array_linefill_history.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("array linefill history fixture should run");

    assert_snapshot("runtime_array_linefill_history.json", &output);
}

#[test]
fn run_script_csv_returns_array_polyline_history_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/array_polyline_history.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("array polyline history fixture should run");

    assert_snapshot("runtime_array_polyline_history.json", &output);
}

#[test]
fn run_script_csv_returns_array_table_history_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/array_table_history.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("array table history fixture should run");

    assert_snapshot("runtime_array_table_history.json", &output);
}

#[test]
fn run_script_csv_returns_array_chart_point_history_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/array_chart_point_history.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("array chart point history fixture should run");

    assert_snapshot("runtime_array_chart_point_history.json", &output);
}

#[test]
fn run_script_csv_returns_array_slice_history_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/array_slice_history.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("array slice history fixture should run");

    assert_snapshot("runtime_array_slice_history.json", &output);
}

#[test]
fn run_script_csv_returns_array_label_slice_history_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/array_label_slice_history.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("array label slice history fixture should run");

    assert_snapshot("runtime_array_label_slice_history.json", &output);
}

#[test]
fn run_script_csv_returns_array_line_slice_history_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/array_line_slice_history.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("array line slice history fixture should run");

    assert_snapshot("runtime_array_line_slice_history.json", &output);
}

#[test]
fn run_script_csv_returns_array_box_slice_history_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/array_box_slice_history.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("array box slice history fixture should run");

    assert_snapshot("runtime_array_box_slice_history.json", &output);
}

#[test]
fn run_script_csv_returns_array_linefill_slice_history_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/array_linefill_slice_history.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("array linefill slice history fixture should run");

    assert_snapshot("runtime_array_linefill_slice_history.json", &output);
}

#[test]
fn run_script_csv_returns_array_polyline_slice_history_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/array_polyline_slice_history.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("array polyline slice history fixture should run");

    assert_snapshot("runtime_array_polyline_slice_history.json", &output);
}

#[test]
fn run_script_csv_returns_array_table_slice_history_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/array_table_slice_history.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("array table slice history fixture should run");

    assert_snapshot("runtime_array_table_slice_history.json", &output);
}

#[test]
fn run_script_csv_returns_array_chart_point_slice_history_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/array_chart_point_slice_history.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("array chart point slice history fixture should run");

    assert_snapshot("runtime_array_chart_point_slice_history.json", &output);
}

#[test]
fn run_script_csv_returns_array_search_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/array_search.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("array search fixture should run");

    assert_snapshot("runtime_array_search.json", &output);
}

#[test]
fn run_script_csv_returns_array_statistics_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/array_statistics.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("array statistics fixture should run");

    assert_snapshot("runtime_array_statistics.json", &output);
}

#[test]
fn run_script_csv_returns_array_ordering_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/array_ordering.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("array ordering fixture should run");

    assert_snapshot("runtime_array_ordering.json", &output);
}

#[test]
fn run_script_csv_returns_array_sort_udt_field_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/array_sort_udt_field.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("UDT array sort field fixture should run");

    assert_snapshot("runtime_array_sort_udt_field.json", &output);
}

#[test]
fn run_script_csv_returns_array_sort_indices_udt_field_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/array_sort_indices_udt_field.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("UDT array sort_indices field fixture should run");

    assert_snapshot("runtime_array_sort_indices_udt_field.json", &output);
}

#[test]
fn run_script_csv_rejects_udt_na_element_sorting() {
    for (source, expected) in [
        (
            include_str!("../../../../tests/fixtures/regressions/array_sort_udt_na_element.pine"),
            "array.sort cannot sort UDT arrays containing na elements",
        ),
        (
            include_str!(
                "../../../../tests/fixtures/regressions/array_sort_indices_udt_na_element.pine"
            ),
            "array.sort_indices cannot sort UDT arrays containing na elements",
        ),
    ] {
        let message = run_script_csv_internal(
            source,
            include_str!("../../../../tests/fixtures/runtime/bars.csv"),
        )
        .expect_err("UDT na element sorting should fail");

        assert!(message.contains(expected), "{message}");
    }
}

#[test]
fn run_script_csv_returns_array_join_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/array_join.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("array join fixture should run");

    assert_snapshot("runtime_array_join.json", &output);
}

#[test]
fn run_script_csv_returns_array_slice_concat_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/array_slice_concat.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("array slice concat fixture should run");

    assert_snapshot("runtime_array_slice_concat.json", &output);
}

#[test]
fn run_script_csv_returns_line_new_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/line_new.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("line new fixture should run");

    assert_snapshot("runtime_line_new.json", &output);
}

#[test]
fn run_script_csv_returns_line_mutation_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/line_mutation.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("line mutation fixture should run");

    assert_snapshot("runtime_line_mutation.json", &output);
}

#[test]
fn run_script_csv_returns_line_control_flow_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/line_control_flow.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("line control-flow fixture should run");

    assert_snapshot("runtime_line_control_flow.json", &output);
}

#[test]
fn run_script_csv_returns_line_getters_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/line_getters.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("line getters fixture should run");

    assert_snapshot("runtime_line_getters.json", &output);
}

#[test]
fn run_script_csv_returns_line_delete_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/line_delete.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("line delete fixture should run");

    assert_snapshot("runtime_line_delete.json", &output);
}

#[test]
fn run_script_csv_returns_line_copy_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/line_copy.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("line copy fixture should run");

    assert_snapshot("runtime_line_copy.json", &output);
}

#[test]
fn run_script_csv_returns_line_array_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/line_array.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("line array fixture should run");

    assert_snapshot("runtime_line_array.json", &output);
}

#[test]
fn run_script_csv_returns_linefill_array_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/linefill_array.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("linefill array fixture should run");
    assert_snapshot("runtime_linefill_array.json", &output);
}

#[test]
fn run_script_csv_returns_linefill_new_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/linefill_new.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("linefill new fixture should run");
    assert_snapshot("runtime_linefill_new.json", &output);
}

#[test]
fn run_script_csv_returns_linefill_set_color_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/linefill_set_color.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("linefill set color fixture should run");
    assert_snapshot("runtime_linefill_set_color.json", &output);
}

#[test]
fn run_script_csv_returns_linefill_getters_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/linefill_getters.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("linefill getters fixture should run");
    assert_snapshot("runtime_linefill_getters.json", &output);
}

#[test]
fn run_script_csv_returns_linefill_all_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/linefill_all.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("linefill all fixture should run");
    assert_snapshot("runtime_linefill_all.json", &output);
}

#[test]
fn run_script_csv_returns_linefill_delete_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/linefill_delete.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("linefill delete fixture should run");
    assert_snapshot("runtime_linefill_delete.json", &output);
}

#[test]
fn run_script_csv_returns_box_new_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/box_new.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("box new fixture should run");

    assert_snapshot("runtime_box_new.json", &output);
}

#[test]
fn run_script_csv_returns_box_mutation_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/box_mutation.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("box mutation fixture should run");

    assert_snapshot("runtime_box_mutation.json", &output);
}

#[test]
fn run_script_csv_returns_box_control_flow_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/box_control_flow.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("box control-flow fixture should run");

    assert_snapshot("runtime_box_control_flow.json", &output);
}

#[test]
fn run_script_csv_returns_box_getters_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/box_getters.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("box getters fixture should run");

    assert_snapshot("runtime_box_getters.json", &output);
}

#[test]
fn run_script_csv_returns_box_delete_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/box_delete.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("box delete fixture should run");

    assert_snapshot("runtime_box_delete.json", &output);
}

#[test]
fn run_script_csv_returns_box_copy_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/box_copy.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("box copy fixture should run");

    assert_snapshot("runtime_box_copy.json", &output);
}

#[test]
fn run_script_csv_returns_box_array_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/box_array.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("box array fixture should run");

    assert_snapshot("runtime_box_array.json", &output);
}

#[test]
fn run_script_csv_returns_table_new_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/table_new.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("table new fixture should run");

    assert_snapshot("runtime_table_new.json", &output);
}

#[test]
fn run_script_csv_returns_table_cell_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/table_cell.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("table cell fixture should run");

    assert_snapshot("runtime_table_cell.json", &output);
}

#[test]
fn run_script_csv_returns_table_control_flow_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/table_control_flow.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("table control-flow fixture should run");

    assert_snapshot("runtime_table_control_flow.json", &output);
}

#[test]
fn run_script_csv_returns_table_delete_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/table_delete.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("table delete fixture should run");

    assert_snapshot("runtime_table_delete.json", &output);
}

#[test]
fn run_script_csv_returns_table_clear_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/table_clear.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("table clear fixture should run");

    assert_snapshot("runtime_table_clear.json", &output);
}

#[test]
fn run_script_csv_returns_table_merge_cells_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/table_merge_cells.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("table merge cells fixture should run");

    assert_snapshot("runtime_table_merge_cells.json", &output);
}

#[test]
fn run_script_csv_returns_table_array_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/table_array.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("table array fixture should run");

    assert_snapshot("runtime_table_array.json", &output);
}

#[test]
fn run_script_csv_returns_drawing_methods_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/drawing_methods.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("drawing methods fixture should run");

    assert_snapshot("runtime_drawing_methods.json", &output);
}

#[test]
fn run_script_csv_returns_loop_state_interactions_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/loop_state_interactions.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("loop state interactions fixture should run");

    assert_snapshot("runtime_loop_state_interactions.json", &output);
}

#[test]
fn run_script_csv_returns_branch_loop_interactions_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/branch_loop_interactions.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("branch loop interactions fixture should run");

    assert_snapshot("runtime_branch_loop_interactions.json", &output);
}

#[test]
fn run_script_csv_returns_switch_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/switch.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("switch fixture should run");

    assert_snapshot("runtime_switch.json", &output);
}

#[test]
fn run_script_csv_returns_block_statements_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/block_statements.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("block statements fixture should run");

    assert_snapshot("runtime_block_statements.json", &output);
}

#[test]
fn run_script_csv_returns_for_edges_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/for_edges.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("for edges fixture should run");

    assert_snapshot("runtime_for_edges.json", &output);
}

#[test]
fn run_script_csv_returns_for_in_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/for_in.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("for in fixture should run");

    assert_snapshot("runtime_for_in.json", &output);
}

#[test]
fn run_script_csv_returns_for_in_bool_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/for_in_bool.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("for in bool fixture should run");

    assert_snapshot("runtime_for_in_bool.json", &output);
}

#[test]
fn run_script_csv_returns_for_in_color_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/for_in_color.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("for in color fixture should run");

    assert_snapshot("runtime_for_in_color.json", &output);
}

#[test]
fn run_script_csv_returns_for_in_float_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/for_in_float.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("for in float fixture should run");

    assert_snapshot("runtime_for_in_float.json", &output);
}

#[test]
fn run_script_csv_returns_for_in_control_flow_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/for_in_control_flow.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("for in control flow fixture should run");

    assert_snapshot("runtime_for_in_control_flow.json", &output);
}

#[test]
fn run_script_csv_returns_for_in_mutation_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/for_in_mutation.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("for in mutation fixture should run");

    assert_snapshot("runtime_for_in_mutation.json", &output);
}

#[test]
fn run_script_csv_returns_for_in_stateful_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/for_in_stateful.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("for in stateful fixture should run");

    assert_snapshot("runtime_for_in_stateful.json", &output);
}

#[test]
fn run_script_csv_returns_for_in_string_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/for_in_string.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("for in string fixture should run");

    assert_snapshot("runtime_for_in_string.json", &output);
}

#[test]
fn run_script_csv_returns_for_in_zero_iteration_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/for_in_zero_iteration.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("for in zero iteration fixture should run");

    assert_snapshot("runtime_for_in_zero_iteration.json", &output);
}

#[test]
fn run_script_csv_returns_for_stateful_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/for_stateful.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("for stateful fixture should run");

    assert_snapshot("runtime_for_stateful.json", &output);
}

#[test]
fn run_script_csv_returns_while_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/while.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("while fixture should run");

    assert_snapshot("runtime_while.json", &output);
}

#[test]
fn run_script_csv_returns_while_edges_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/while_edges.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("while edges fixture should run");

    assert_snapshot("runtime_while_edges.json", &output);
}

#[test]
fn run_script_csv_returns_while_stateful_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/while_stateful.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("while stateful fixture should run");

    assert_snapshot("runtime_while_stateful.json", &output);
}

#[test]
fn run_script_csv_returns_local_scope_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/local_scope.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("local scope fixture should run");

    assert_snapshot("runtime_local_scope.json", &output);
}

#[test]
fn run_script_csv_returns_history_edges_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/history_edges.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("history edges fixture should run");

    assert_snapshot("runtime_history_edges.json", &output);
}

#[test]
fn run_script_csv_returns_dynamic_history_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/dynamic_history.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("dynamic history fixture should run");

    assert_snapshot("runtime_dynamic_history.json", &output);
}

#[test]
fn run_script_csv_returns_dynamic_history_scopes_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/dynamic_history_scopes.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("dynamic history scopes fixture should run");

    assert_snapshot("runtime_dynamic_history_scopes.json", &output);
}

#[test]
fn run_script_csv_returns_series_history_offset_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/series_history_offset.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("series history offset fixture should run");

    assert_snapshot("runtime_series_history_offset.json", &output);
}

#[test]
fn run_script_csv_returns_max_bars_back_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/max_bars_back.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("max bars back fixture should run");

    assert_snapshot("runtime_max_bars_back.json", &output);
}

#[test]
fn run_script_csv_returns_varip_scalar_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/varip_scalar.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("varip scalar fixture should run");

    assert_snapshot("runtime_varip_scalar.json", &output);
}

#[test]
fn run_script_csv_returns_varip_local_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/varip_local.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("varip local fixture should run");

    assert_snapshot("runtime_varip_local.json", &output);
}

#[test]
fn run_script_csv_returns_varip_array_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/varip_array.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("varip array fixture should run");

    assert_snapshot("runtime_varip_array.json", &output);
}

#[test]
fn run_script_csv_returns_user_type_varip_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/user_type_varip.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("user type varip fixture should run");

    assert_snapshot("runtime_user_type_varip.json", &output);
}

#[test]
fn run_script_csv_returns_request_security_same_context_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/request_security_same_context.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("request.security same-context fixture should run");

    assert_snapshot("runtime_request_security_same_context.json", &output);
}

#[test]
fn run_script_csv_returns_user_types_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/user_types.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("user-defined types fixture should run");

    assert_snapshot("runtime_user_types.json", &output);
}

#[test]
fn run_script_csv_returns_user_type_functions_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/user_type_functions.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("user-defined type functions fixture should run");

    assert_snapshot("runtime_user_type_functions.json", &output);
}

#[test]
fn run_script_csv_returns_user_methods_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/user_methods.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("user-defined methods fixture should run");

    assert_snapshot("runtime_user_methods.json", &output);
}

#[test]
fn analyze_script_reports_unsupported_user_type_field_fixture() {
    let output = analyze_script(include_str!(
        "../../../../tests/fixtures/sema/unsupported_user_type.pine"
    ));
    let parsed: serde_json::Value = serde_json::from_str(&output).expect("strict JSON output");

    assert_eq!(parsed["executable"], serde_json::json!(false));
    assert_eq!(
        parsed["diagnostics"][0]["code"],
        serde_json::json!("E_UDT_FIELD_TYPE")
    );
}

#[test]
fn analyze_script_reports_unsupported_user_method_fixture() {
    let output = analyze_script(include_str!(
        "../../../../tests/fixtures/sema/unsupported_user_method.pine"
    ));
    let parsed: serde_json::Value = serde_json::from_str(&output).expect("strict JSON output");

    assert_eq!(parsed["executable"], serde_json::json!(false));
    assert_eq!(
        parsed["diagnostics"][0]["code"],
        serde_json::json!("E_METHOD_RECEIVER_TYPE")
    );
}

#[test]
fn analyze_script_reports_unsupported_user_type_varip_fixture() {
    let output = analyze_script(include_str!(
        "../../../../tests/fixtures/sema/unsupported_user_type_varip.pine"
    ));
    let parsed: serde_json::Value = serde_json::from_str(&output).expect("strict JSON output");

    assert_eq!(parsed["executable"], serde_json::json!(false));
    assert_eq!(
        parsed["diagnostics"][0]["code"],
        serde_json::json!("E_UNSUPPORTED_FEATURE")
    );
    assert_eq!(
        parsed["compatibility"]["unsupported"][0]["feature"],
        serde_json::json!("varip")
    );
    assert!(
        parsed["compatibility"]["unsupported"][0]["reason"]
            .as_str()
            .expect("unsupported reason should be a string")
            .contains("UDT varip supports only explicit scalar-tree declarations")
    );
}

#[test]
fn analyze_script_reports_unsupported_user_type_field_mutation_fixture() {
    let output = analyze_script(include_str!(
        "../../../../tests/fixtures/sema/unsupported_user_type_field_mutation.pine"
    ));
    let parsed: serde_json::Value = serde_json::from_str(&output).expect("strict JSON output");

    assert_eq!(parsed["executable"], serde_json::json!(false));
    assert_eq!(
        parsed["diagnostics"][0]["code"],
        serde_json::json!("E_UNSUPPORTED_FEATURE")
    );
    assert_eq!(
        parsed["compatibility"]["unsupported"][0]["feature"],
        serde_json::json!("function_side_effect")
    );
    assert!(
        parsed["compatibility"]["unsupported"][0]["reason"]
            .as_str()
            .expect("unsupported reason should be a string")
            .contains("mutating fields on global user-defined type values")
    );
}

#[test]
fn analyze_script_reports_unsupported_user_method_side_effect_fixture() {
    let output = analyze_script(include_str!(
        "../../../../tests/fixtures/sema/unsupported_user_method_side_effect.pine"
    ));
    let parsed: serde_json::Value = serde_json::from_str(&output).expect("strict JSON output");

    assert_eq!(parsed["executable"], serde_json::json!(false));
    assert_eq!(
        parsed["diagnostics"][0]["code"],
        serde_json::json!("E_UNSUPPORTED_FEATURE")
    );
    assert_eq!(
        parsed["compatibility"]["unsupported"][0]["feature"],
        serde_json::json!("function_side_effect")
    );
    assert!(
        parsed["compatibility"]["unsupported"][0]["reason"]
            .as_str()
            .expect("unsupported reason should be a string")
            .contains("inside user-defined functions")
    );
}

#[test]
fn analyze_script_reports_unsupported_non_array_method_fixture() {
    let output = analyze_script(include_str!(
        "../../../../tests/fixtures/sema/unsupported_non_array_method.pine"
    ));
    let parsed: serde_json::Value = serde_json::from_str(&output).expect("strict JSON output");

    assert_eq!(parsed["executable"], serde_json::json!(false));
    assert_eq!(
        parsed["diagnostics"][0]["code"],
        serde_json::json!("E_METHOD_RECEIVER_TYPE")
    );
}

#[test]
fn run_script_csv_returns_math_edge_cases_as_json_null() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/math_edge_cases.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("math edge-case fixture should run");

    assert_snapshot("runtime_math_edge_cases.json", &output);
}

#[test]
fn run_script_csv_returns_math_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/math.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("math fixture should run");

    assert_snapshot("runtime_math.json", &output);
}

#[test]
fn run_script_csv_returns_computed_lengths_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/computed_lengths.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("computed lengths fixture should run");

    assert_snapshot("runtime_computed_lengths.json", &output);
}

#[test]
fn run_script_csv_returns_conditional_ta_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/conditional_ta.pine"),
        "time,open,high,low,close,volume\n0,1,2,1,2,1\n1,2,4,2,4,1\n2,5,5,3,3,1\n3,3,6,3,6,1\n",
    )
    .expect("conditional TA fixture should run");

    let parsed: serde_json::Value = serde_json::from_str(&output).expect("strict JSON output");
    assert_eq!(parsed["diagnostics"], serde_json::json!([]));
    let plots = parsed["plots"].as_array().expect("plots");
    assert_eq!(plots.len(), 1);
    assert_eq!(plots[0]["values"], serde_json::json!([null, 3, 3, 5]));
}

#[test]
fn run_script_csv_returns_conditional_ta_snapshot_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/conditional_ta.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("conditional TA fixture should run");

    assert_snapshot("runtime_conditional_ta.json", &output);
}

#[test]
fn run_script_csv_returns_udf_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/udf.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("UDF fixture should run");

    assert_snapshot("runtime_udf.json", &output);
}

#[test]
fn run_script_csv_returns_na_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/na.pine"),
        "time,open,high,low,close,volume\n0,1,2,1,2,1\n1,5,5,3,3,1\n2,2,4,2,4,1\n3,6,6,5,5,1\n",
    )
    .expect("NA fixture should run");

    let parsed: serde_json::Value = serde_json::from_str(&output).expect("strict JSON output");
    assert_eq!(parsed["diagnostics"], serde_json::json!([]));
    let plots = parsed["plots"].as_array().expect("plots");
    assert_eq!(plots.len(), 6);
    assert_eq!(plots[0]["values"], serde_json::json!([2, 2, 3, 4]));
    assert_eq!(plots[1]["values"], serde_json::json!([2, 2, 3, 4]));
    assert_eq!(plots[2]["values"], serde_json::json!([2, 2, 4, 4]));
    assert_eq!(plots[3]["values"], serde_json::json!([0, 0, 0, 0]));
    assert_eq!(plots[4]["values"], serde_json::json!([0, 0, 0, 0]));
    assert_eq!(plots[5]["values"], serde_json::json!([1, 0, 0, 0]));
}

#[test]
fn run_script_csv_returns_na_snapshot_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/na.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("NA fixture should run");

    assert_snapshot("runtime_na.json", &output);
}

#[test]
fn run_script_csv_returns_ta_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/ta.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("TA fixture should run");

    assert_snapshot("runtime_ta.json", &output);
}

#[test]
fn run_script_csv_returns_dema_tema_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/dema_tema.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("DEMA/TEMA fixture should run");

    assert_snapshot("runtime_dema_tema.json", &output);
}

#[test]
fn run_script_csv_returns_swma_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/swma.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("swma fixture should run");

    assert_snapshot("runtime_swma.json", &output);
}

#[test]
fn run_script_csv_returns_stoch_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/stoch.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("stoch fixture should run");

    assert_snapshot("runtime_stoch.json", &output);
}

#[test]
fn run_script_csv_returns_wpr_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/wpr.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("wpr fixture should run");

    assert_snapshot("runtime_wpr.json", &output);
}

#[test]
fn run_script_csv_returns_atr_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/atr.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("atr fixture should run");

    assert_snapshot("runtime_atr.json", &output);
}

#[test]
fn run_script_csv_returns_supertrend_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/supertrend.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("supertrend fixture should run");

    assert_snapshot("runtime_supertrend.json", &output);
}

#[test]
fn run_script_csv_returns_dmi_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/dmi.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("dmi fixture should run");

    assert_snapshot("runtime_dmi.json", &output);
}

#[test]
fn run_script_csv_returns_sar_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/sar.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("sar fixture should run");

    assert_snapshot("runtime_sar.json", &output);
}

#[test]
fn run_script_csv_returns_cross_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/cross.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("cross fixture should run");

    assert_snapshot("runtime_cross.json", &output);
}

#[test]
fn run_script_csv_returns_mom_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/mom.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("mom fixture should run");

    assert_snapshot("runtime_mom.json", &output);
}

#[test]
fn run_script_csv_returns_roc_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/roc.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("roc fixture should run");

    assert_snapshot("runtime_roc.json", &output);
}

#[test]
fn run_script_csv_returns_trend_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/trend.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("trend fixture should run");

    assert_snapshot("runtime_trend.json", &output);
}

#[test]
fn run_script_csv_returns_barssince_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/barssince.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("barssince fixture should run");

    assert_snapshot("runtime_barssince.json", &output);
}

#[test]
fn run_script_csv_returns_valuewhen_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/valuewhen.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("valuewhen fixture should run");

    assert_snapshot("runtime_valuewhen.json", &output);
}

#[test]
fn run_script_csv_returns_extremes_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/extremes.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("extremes fixture should run");

    assert_snapshot("runtime_extremes.json", &output);
}

#[test]
fn run_script_csv_returns_extreme_bars_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/extreme_bars.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("extreme bars fixture should run");

    assert_snapshot("runtime_extreme_bars.json", &output);
}

#[test]
fn run_script_csv_returns_tsi_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/tsi.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("tsi fixture should run");

    assert_snapshot("runtime_tsi.json", &output);
}

#[test]
fn run_script_csv_returns_cmo_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/cmo.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("cmo fixture should run");

    assert_snapshot("runtime_cmo.json", &output);
}

#[test]
fn run_script_csv_returns_cci_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/cci.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("cci fixture should run");

    assert_snapshot("runtime_cci.json", &output);
}

#[test]
fn run_script_csv_returns_cog_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/cog.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("cog fixture should run");

    assert_snapshot("runtime_cog.json", &output);
}

#[test]
fn run_script_csv_returns_ao_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/ao.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("ao fixture should run");

    assert_snapshot("runtime_ao.json", &output);
}

#[test]
fn run_script_csv_returns_bop_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/bop.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("bop fixture should run");

    assert_snapshot("runtime_bop.json", &output);
}

#[test]
fn run_script_csv_returns_bb_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/bb.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("bb fixture should run");

    assert_snapshot("runtime_bb.json", &output);
}

#[test]
fn run_script_csv_returns_bbw_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/bbw.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("bbw fixture should run");

    assert_snapshot("runtime_bbw.json", &output);
}

#[test]
fn run_script_csv_returns_kc_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/kc.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("kc fixture should run");

    assert_snapshot("runtime_kc.json", &output);
}

#[test]
fn run_script_csv_returns_kcw_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/kcw.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("kcw fixture should run");

    assert_snapshot("runtime_kcw.json", &output);
}

#[test]
fn run_script_csv_returns_pivots_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/pivots.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("pivots fixture should run");

    assert_snapshot("runtime_pivots.json", &output);
}

#[test]
fn run_script_csv_returns_pivot_point_levels_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/pivot_point_levels.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("pivot point levels fixture should run");

    assert_snapshot("runtime_pivot_point_levels.json", &output);
}

#[test]
fn run_script_csv_returns_cum_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/cum.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("cum fixture should run");

    assert_snapshot("runtime_cum.json", &output);
}

#[test]
fn run_script_csv_returns_all_time_extremes_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/all_time_extremes.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("all-time extremes fixture should run");

    assert_snapshot("runtime_all_time_extremes.json", &output);
}

#[test]
fn run_script_csv_returns_alma_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/alma.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("alma fixture should run");

    assert_snapshot("runtime_alma.json", &output);
}

#[test]
fn run_script_csv_returns_linreg_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/linreg.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("linreg fixture should run");

    assert_snapshot("runtime_linreg.json", &output);
}

#[test]
fn run_script_csv_returns_accdist_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/accdist.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("accdist fixture should run");

    assert_snapshot("runtime_accdist.json", &output);
}

#[test]
fn run_script_csv_returns_iii_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/iii.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("iii fixture should run");

    assert_snapshot("runtime_iii.json", &output);
}

#[test]
fn run_script_csv_returns_nvi_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/nvi.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("nvi fixture should run");

    assert_snapshot("runtime_nvi.json", &output);
}

#[test]
fn run_script_csv_returns_obv_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/obv.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("obv fixture should run");

    assert_snapshot("runtime_obv.json", &output);
}

#[test]
fn run_script_csv_returns_pvi_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/pvi.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("pvi fixture should run");

    assert_snapshot("runtime_pvi.json", &output);
}

#[test]
fn run_script_csv_returns_pvt_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/pvt.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("pvt fixture should run");

    assert_snapshot("runtime_pvt.json", &output);
}

#[test]
fn run_script_csv_returns_vwap_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/vwap.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("vwap fixture should run");

    assert_snapshot("runtime_vwap.json", &output);
}

#[test]
fn run_script_csv_returns_wad_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/wad.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("wad fixture should run");

    assert_snapshot("runtime_wad.json", &output);
}

#[test]
fn run_script_csv_returns_wvad_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/wvad.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("wvad fixture should run");

    assert_snapshot("runtime_wvad.json", &output);
}

#[test]
fn run_script_csv_returns_correlation_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/correlation.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("correlation fixture should run");

    assert_snapshot("runtime_correlation.json", &output);
}

#[test]
fn run_script_csv_returns_covariance_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/covariance.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("covariance fixture should run");

    assert_snapshot("runtime_covariance.json", &output);
}

#[test]
fn run_script_csv_returns_median_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/median.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("median fixture should run");

    assert_snapshot("runtime_median.json", &output);
}

#[test]
fn run_script_csv_returns_mode_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/mode.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("mode fixture should run");

    assert_snapshot("runtime_mode.json", &output);
}

#[test]
fn run_script_csv_returns_percentile_linear_interpolation_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/percentile_linear_interpolation.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("percentile linear interpolation fixture should run");

    assert_snapshot("runtime_percentile_linear_interpolation.json", &output);
}

#[test]
fn run_script_csv_returns_percentile_nearest_rank_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/percentile_nearest_rank.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("percentile nearest rank fixture should run");

    assert_snapshot("runtime_percentile_nearest_rank.json", &output);
}

#[test]
fn run_script_csv_returns_percentrank_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/percentrank.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("percentrank fixture should run");

    assert_snapshot("runtime_percentrank.json", &output);
}

#[test]
fn run_script_csv_returns_stdev_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/stdev.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("stdev fixture should run");

    assert_snapshot("runtime_stdev.json", &output);
}

#[test]
fn run_script_csv_returns_variance_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/variance.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("variance fixture should run");

    assert_snapshot("runtime_variance.json", &output);
}

#[test]
fn run_script_csv_returns_range_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/range.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("range fixture should run");

    assert_snapshot("runtime_range.json", &output);
}

#[test]
fn run_script_csv_returns_dev_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/dev.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("dev fixture should run");

    assert_snapshot("runtime_dev.json", &output);
}

#[test]
fn run_script_csv_returns_vwma_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/vwma.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("vwma fixture should run");

    assert_snapshot("runtime_vwma.json", &output);
}

#[test]
fn run_script_csv_returns_mfi_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/mfi.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("mfi fixture should run");

    assert_snapshot("runtime_mfi.json", &output);
}

#[test]
fn run_script_csv_returns_wma_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/wma.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("wma fixture should run");

    assert_snapshot("runtime_wma.json", &output);
}

#[test]
fn run_script_csv_returns_hma_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/hma.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("hma fixture should run");

    assert_snapshot("runtime_hma.json", &output);
}

#[test]
fn run_script_csv_returns_if_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/if.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("if fixture should run");

    assert_snapshot("runtime_if.json", &output);
}

#[test]
fn run_script_csv_returns_macd_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/macd.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("MACD fixture should run");

    assert_snapshot("runtime_macd.json", &output);
}

#[test]
fn run_script_csv_returns_strings_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strings.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strings fixture should run");

    assert_snapshot("runtime_strings.json", &output);
}

#[test]
fn run_script_csv_returns_line_wrapped_strings_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/line_wrapped_strings.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("line-wrapped strings fixture should run");

    assert_snapshot("runtime_line_wrapped_strings.json", &output);
}

#[test]
fn run_script_csv_returns_parenthesized_line_wrapping_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/parenthesized_line_wrapping.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("parenthesized line-wrapping fixture should run");

    assert_snapshot("runtime_parenthesized_line_wrapping.json", &output);
}

#[test]
fn run_script_csv_returns_legacy_line_wrapping_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/legacy_line_wrapping.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("legacy line-wrapping fixture should run");

    assert_snapshot("runtime_legacy_line_wrapping.json", &output);
}

#[test]
fn run_script_csv_returns_compound_assignments_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/compound_assignments.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("compound assignments fixture should run");

    assert_snapshot("runtime_compound_assignments.json", &output);
}

#[test]
fn run_script_csv_returns_colors_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/colors.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("colors fixture should run");

    assert_snapshot("runtime_colors.json", &output);
}

#[test]
fn run_script_csv_returns_syminfo_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/syminfo.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("syminfo fixture should run");

    assert_snapshot("runtime_syminfo.json", &output);
}

#[test]
fn run_script_csv_returns_generic_input_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/generic_input.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("generic input fixture should run");

    assert_snapshot("runtime_generic_input.json", &output);
}

#[test]
fn run_script_csv_returns_timeframe_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/timeframe.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("timeframe fixture should run");

    assert_snapshot("runtime_timeframe.json", &output);
}

#[test]
fn run_script_csv_returns_time_components_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/time_components.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("time components fixture should run");

    assert_snapshot("runtime_time_components.json", &output);
}

#[test]
fn run_script_csv_returns_global_series_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/global_series.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("global series fixture should run");

    assert_snapshot("runtime_global_series.json", &output);
}

#[test]
fn run_script_csv_returns_casts_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/casts.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("casts fixture should run");

    assert_snapshot("runtime_casts.json", &output);
}

#[test]
fn run_script_csv_returns_barstate_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/barstate.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("barstate fixture should run");

    assert_snapshot("runtime_barstate.json", &output);
}

#[test]
fn run_script_csv_returns_session_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/session.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("session fixture should run");

    assert_snapshot("runtime_session.json", &output);
}

#[test]
fn run_script_csv_returns_inputs_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/inputs.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("inputs fixture should run");

    assert_snapshot("runtime_inputs.json", &output);
}

#[test]
fn run_script_csv_rejects_non_finite_ohlcv_values() {
    for (column, row) in [
        ("open", "0,NaN,1,1,1,1"),
        ("high", "0,1,inf,1,1,1"),
        ("low", "0,1,1,-inf,1,1"),
        ("close", "0,1,1,1,infinity,1"),
        ("volume", "0,1,1,1,1,NaN"),
    ] {
        let message = run_script_csv_internal(
            "indicator(\"nonfinite\")\nplot(close)\n",
            &format!("time,open,high,low,close,volume\n{row}\n"),
        )
        .expect_err("non-finite CSV value should fail");

        assert!(
            message.contains(&format!("invalid `{column}` value")),
            "{message}"
        );
        assert!(message.contains("value must be finite"), "{message}");
    }
}

#[test]
fn run_script_csv_rejects_duplicate_bar_times() {
    let message = run_script_csv_internal(
        "indicator(\"duplicate\")\nplot(close)\n",
        "time,open,high,low,close,volume\n0,1,1,1,1,1\n0,2,2,2,2,1\n",
    )
    .expect_err("duplicate main bar time should fail");

    assert_eq!(message, "duplicate bar time `0` in bars CSV");
}

#[test]
fn run_script_csv_rejects_unsorted_bar_times() {
    let message = run_script_csv_internal(
        "indicator(\"unsorted\")\nplot(close)\n",
        "time,open,high,low,close,volume\n1,2,2,2,2,1\n0,1,1,1,1,1\n",
    )
    .expect_err("unsorted main bar times should fail");

    assert_eq!(message, "bars CSV is not sorted: `0` follows `1`");
}

#[test]
fn runs_strategy_script_from_csv_to_empty_strategy_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_no_order.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy script should run");

    assert_snapshot("runtime_strategy_empty.json", &output);
}

#[test]
fn renders_strategy_order_fill_alert_template_from_public_alert_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_metadata.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy metadata fixture should run");
    let parsed: serde_json::Value = serde_json::from_str(&output).expect("strict JSON output");
    let alert_json = parsed["strategy"]["alerts"][1].to_string();

    let rendered = render_strategy_order_fill_alert_template(
        "Order: {{strategy.order.alert_message}}",
        &alert_json,
    )
    .expect("strategy order-fill alert template should render");

    assert_eq!(rendered, "Order: loss alert");
    assert_eq!(parsed["strategy"]["alerts"][1]["message"], "loss alert");
    assert!(
        !parsed["strategy"]["alerts"][1]
            .as_object()
            .expect("strategy alert should be an object")
            .contains_key("renderedMessage")
    );
}

#[test]
fn render_strategy_order_fill_alert_template_rejects_unknown_placeholder() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_metadata.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy metadata fixture should run");
    let parsed: serde_json::Value = serde_json::from_str(&output).expect("strict JSON output");
    let alert_json = parsed["strategy"]["alerts"][1].to_string();

    let message =
        strategy_alerts::render_strategy_order_fill_alert_template("{{close}}", &alert_json)
            .expect_err("unknown placeholder should fail");

    assert!(message.contains("unsupported strategy order-fill alert placeholder `{{close}}`"));
}

#[test]
fn renders_strategy_order_fill_running_alert_from_config_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_metadata.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy metadata fixture should run");
    let parsed: serde_json::Value = serde_json::from_str(&output).expect("strict JSON output");
    let alert_json = parsed["strategy"]["alerts"][1].to_string();
    let config_json = serde_json::json!({
        "scriptSnapshotId": "snapshot-1",
        "symbol": "NYSE:IBM",
        "timeframe": "1",
        "eventSelection": "strategyOrderFills",
        "messageTemplate": "Running: {{strategy.order.alert_message}}",
        "realtimePolicy": "realtimeOnly",
    })
    .to_string();

    let rendered = render_strategy_order_fill_running_alert(&config_json, &alert_json)
        .expect("strategy order-fill running alert should render");

    assert_eq!(rendered, "Running: loss alert");
    assert!(
        !parsed["strategy"]["alerts"][1]
            .as_object()
            .expect("strategy alert should be an object")
            .contains_key("renderedMessage")
    );
}

#[test]
fn render_strategy_order_fill_running_alert_keeps_both_selection_design_only() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_metadata.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy metadata fixture should run");
    let parsed: serde_json::Value = serde_json::from_str(&output).expect("strict JSON output");
    let alert_json = parsed["strategy"]["alerts"][1].to_string();
    let config_json = serde_json::json!({
        "scriptSnapshotId": "snapshot-1",
        "symbol": "NYSE:IBM",
        "timeframe": "1",
        "eventSelection": "both",
        "messageTemplate": "{{strategy.order.alert_message}}",
        "realtimePolicy": "realtimeOnly",
    })
    .to_string();

    let message =
        strategy_alerts::render_strategy_order_fill_running_alert(&config_json, &alert_json)
            .expect_err("both remains design-only");

    assert!(message.contains(
        "running alert event selection `both` cannot evaluate a strategy order-fill event"
    ));
}

#[test]
fn render_strategy_order_fill_running_alert_rejects_unknown_placeholder() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_metadata.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy metadata fixture should run");
    let parsed: serde_json::Value = serde_json::from_str(&output).expect("strict JSON output");
    let alert_json = parsed["strategy"]["alerts"][1].to_string();
    let config_json = serde_json::json!({
        "scriptSnapshotId": "snapshot-1",
        "symbol": "NYSE:IBM",
        "timeframe": "1",
        "eventSelection": "strategyOrderFills",
        "messageTemplate": "{{close}}",
        "realtimePolicy": "realtimeOnly",
    })
    .to_string();

    let message =
        strategy_alerts::render_strategy_order_fill_running_alert(&config_json, &alert_json)
            .expect_err("unknown placeholder should fail");

    assert!(message.contains("unsupported strategy order-fill alert placeholder `{{close}}`"));
}

#[test]
fn runs_strategy_exit_missing_entry_from_csv_as_noop_json() {
    let output = run_script_csv(
        "strategy(\"exit\")\nif bar_index == 0\n    strategy.exit(\"XL\", \"L\", stop=low)\n",
        "time,open,high,low,close,volume\n0,1,1,1,1,1\n1,2,2,2,2,1\n",
    )
    .expect("strategy exit no-op script should run");
    let parsed: serde_json::Value = serde_json::from_str(&output).expect("strict JSON output");
    let strategy = parsed["strategy"]
        .as_object()
        .expect("strategy should be an object");

    assert_eq!(parsed["diagnostics"], serde_json::json!([]));
    assert_eq!(parsed["strategy"]["orders"], serde_json::json!([]));
    assert_eq!(parsed["strategy"]["trades"], serde_json::json!([]));
    assert_eq!(parsed["strategy"]["position"], serde_json::json!([]));
    assert_eq!(parsed["strategy"]["diagnostics"], serde_json::json!([]));
    assert!(!strategy.contains_key("pending"));
    assert!(!strategy.contains_key("reserved"));
}

#[test]
fn runs_strategy_exit_while_flat_from_csv_as_noop_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_while_flat_noop.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit while-flat no-op script should run");

    assert_snapshot("runtime_strategy_exit_while_flat_noop.json", &output);
}

#[test]
fn runs_strategy_exit_limit_while_flat_from_csv_as_noop_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_limit_while_flat_noop.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit limit while-flat no-op script should run");

    assert_snapshot("runtime_strategy_exit_limit_while_flat_noop.json", &output);
}

#[test]
fn runs_strategy_exit_profit_while_flat_from_csv_as_noop_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_profit_while_flat_noop.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit profit while-flat no-op script should run");

    assert_snapshot("runtime_strategy_exit_profit_while_flat_noop.json", &output);
}

#[test]
fn runs_strategy_exit_loss_while_flat_from_csv_as_noop_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_loss_while_flat_noop.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit loss while-flat no-op script should run");

    assert_snapshot("runtime_strategy_exit_loss_while_flat_noop.json", &output);
}

#[test]
fn runs_strategy_exit_bracket_while_flat_from_csv_as_noop_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_bracket_while_flat_noop.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit bracket while-flat no-op script should run");

    assert_snapshot(
        "runtime_strategy_exit_bracket_while_flat_noop.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_stop_profit_bracket_while_flat_from_csv_as_noop_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_stop_profit_bracket_while_flat_noop.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit stop profit bracket while-flat no-op script should run");

    assert_snapshot(
        "runtime_strategy_exit_stop_profit_bracket_while_flat_noop.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_loss_limit_bracket_while_flat_from_csv_as_noop_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_loss_limit_bracket_while_flat_noop.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit loss limit bracket while-flat no-op script should run");

    assert_snapshot(
        "runtime_strategy_exit_loss_limit_bracket_while_flat_noop.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_loss_profit_bracket_while_flat_from_csv_as_noop_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_loss_profit_bracket_while_flat_noop.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit loss profit bracket while-flat no-op script should run");

    assert_snapshot(
        "runtime_strategy_exit_loss_profit_bracket_while_flat_noop.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_trailing_while_flat_from_csv_as_noop_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_trailing_while_flat_noop.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit trailing while-flat no-op script should run");

    assert_snapshot(
        "runtime_strategy_exit_trailing_while_flat_noop.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_wrong_entry_from_csv_as_noop_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_unmatched_from_entry_noop.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy wrong-entry no-op script should run");

    assert_snapshot(
        "runtime_strategy_exit_unmatched_from_entry_noop.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_wrong_entry_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_unmatched_from_entry_noop.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy wrong-entry no-op fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_unmatched_from_entry_noop.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_limit_wrong_entry_from_csv_as_noop_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_limit_unmatched_from_entry_noop.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy limit wrong-entry no-op script should run");

    assert_snapshot(
        "runtime_strategy_exit_limit_unmatched_from_entry_noop.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_profit_wrong_entry_from_csv_as_noop_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_profit_unmatched_from_entry_noop.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy profit wrong-entry no-op script should run");

    assert_snapshot(
        "runtime_strategy_exit_profit_unmatched_from_entry_noop.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_loss_wrong_entry_from_csv_as_noop_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_loss_unmatched_from_entry_noop.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy loss wrong-entry no-op script should run");

    assert_snapshot(
        "runtime_strategy_exit_loss_unmatched_from_entry_noop.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_bracket_wrong_entry_from_csv_as_noop_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_bracket_unmatched_from_entry_noop.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy bracket wrong-entry no-op script should run");

    assert_snapshot(
        "runtime_strategy_exit_bracket_unmatched_from_entry_noop.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_stop_profit_bracket_wrong_entry_from_csv_as_noop_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_stop_profit_bracket_unmatched_from_entry_noop.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy stop profit bracket wrong-entry no-op script should run");

    assert_snapshot(
        "runtime_strategy_exit_stop_profit_bracket_unmatched_from_entry_noop.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_loss_limit_bracket_wrong_entry_from_csv_as_noop_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_loss_limit_bracket_unmatched_from_entry_noop.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy loss limit bracket wrong-entry no-op script should run");

    assert_snapshot(
        "runtime_strategy_exit_loss_limit_bracket_unmatched_from_entry_noop.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_loss_profit_bracket_wrong_entry_from_csv_as_noop_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_loss_profit_bracket_unmatched_from_entry_noop.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy loss profit bracket wrong-entry no-op script should run");

    assert_snapshot(
        "runtime_strategy_exit_loss_profit_bracket_unmatched_from_entry_noop.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_trailing_wrong_entry_from_csv_as_noop_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_trailing_unmatched_from_entry_noop.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy trailing wrong-entry no-op script should run");

    assert_snapshot(
        "runtime_strategy_exit_trailing_unmatched_from_entry_noop.json",
        &output,
    );
}

#[test]
fn runs_strategy_entry_from_csv_to_strategy_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_entry.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy entry script should run");

    assert_snapshot("runtime_strategy_entry.json", &output);
}

#[test]
fn runs_strategy_entry_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_entry.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy entry fixture should run");

    assert_snapshot("runtime_strategy_entry.json", &output);
}

#[test]
fn runs_strategy_entry_limit_from_csv_to_strategy_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_entry_limit.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy limit entry script should run");

    assert_snapshot("runtime_strategy_entry_limit.json", &output);
}

#[test]
fn runs_strategy_entry_stop_from_csv_to_strategy_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_entry_stop.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy stop entry script should run");

    assert_snapshot("runtime_strategy_entry_stop.json", &output);
}

#[test]
fn runs_strategy_entry_stop_limit_from_csv_to_strategy_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_entry_stop_limit.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy stop-limit entry script should run");

    assert_snapshot("runtime_strategy_entry_stop_limit.json", &output);
}

#[test]
fn runs_strategy_pyramiding_from_csv_to_public_strategy_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_pyramiding.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy pyramiding fixture should run");

    assert_snapshot("runtime_strategy_pyramiding.json", &output);
}

#[test]
fn runs_strategy_pyramiding_close_from_csv_to_public_strategy_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_pyramiding_close.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy pyramiding close fixture should run");

    assert_snapshot("runtime_strategy_pyramiding_close.json", &output);
}

#[test]
fn runs_strategy_pyramiding_close_all_from_csv_to_public_strategy_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_pyramiding_close_all.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy pyramiding close_all fixture should run");

    assert_snapshot("runtime_strategy_pyramiding_close_all.json", &output);
}

#[test]
fn runs_strategy_pyramiding_exit_from_entry_from_csv_to_public_strategy_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_pyramiding_exit_from_entry.pine"),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_from_entry_bars.csv"
        ),
    )
    .expect("strategy pyramiding exit from_entry fixture should run");

    assert_snapshot("runtime_strategy_pyramiding_exit_from_entry.json", &output);
}

#[test]
fn runs_strategy_pyramiding_exit_profit_from_entry_from_csv_to_public_strategy_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_profit_from_entry.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_profit_from_entry_bars.csv"
        ),
    )
    .expect("strategy pyramiding profit exit from_entry fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_profit_from_entry.json",
        &output,
    );
}

#[test]
fn runs_strategy_pyramiding_exit_same_id_from_csv_to_public_strategy_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_pyramiding_exit_same_id.pine"),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_same_id_bars.csv"
        ),
    )
    .expect("strategy pyramiding same-id exit fixture should run");

    assert_snapshot("runtime_strategy_pyramiding_exit_same_id.json", &output);
}

#[test]
fn runs_strategy_pyramiding_exit_bracket_from_entry_from_csv_to_public_strategy_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_bracket_from_entry.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_profit_from_entry_bars.csv"
        ),
    )
    .expect("strategy pyramiding bracket exit from_entry fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_bracket_from_entry.json",
        &output,
    );
}

#[test]
fn runs_strategy_pyramiding_exit_trail_points_from_entry_from_csv_to_public_strategy_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_trail_points_from_entry.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_trail_points_from_entry_bars.csv"
        ),
    )
    .expect("strategy pyramiding trailing exit from_entry fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_trail_points_from_entry.json",
        &output,
    );
}

#[test]
fn runs_strategy_same_tick_limit_entries_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_limit_same_tick_limit_entries.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_limit_same_tick_limit_entries_bars.csv"
        ),
    )
    .expect("strategy same-tick limit entries fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_limit_same_tick_limit_entries.json",
        &output,
    );
}

#[test]
fn runs_strategy_same_tick_stop_entries_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_limit_same_tick_stop_entries.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_limit_same_tick_stop_entries_bars.csv"
        ),
    )
    .expect("strategy same-tick stop entries fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_limit_same_tick_stop_entries.json",
        &output,
    );
}

#[test]
fn runs_strategy_same_tick_stop_limit_entries_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_limit_same_tick_stop_limit_entries.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_limit_same_tick_stop_limit_entries_bars.csv"
        ),
    )
    .expect("strategy same-tick stop-limit entries fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_limit_same_tick_stop_limit_entries.json",
        &output,
    );
}

#[test]
fn runs_strategy_default_quantity_from_csv_to_strategy_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_default_quantity.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy default quantity script should run");

    assert_snapshot("runtime_strategy_default_quantity.json", &output);
}

#[test]
fn runs_strategy_default_quantity_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_default_quantity.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy default quantity fixture should run");

    assert_snapshot("runtime_strategy_default_quantity.json", &output);
}

#[test]
fn runs_strategy_builtin_default_quantity_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_builtin_default_quantity.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy builtin default quantity fixture should run");

    assert_snapshot("runtime_strategy_builtin_default_quantity.json", &output);
}

#[test]
fn runs_strategy_default_quantity_override_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_default_quantity_override.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy default quantity override fixture should run");

    assert_snapshot("runtime_strategy_default_quantity_override.json", &output);
}

#[test]
fn runs_strategy_percent_of_equity_default_quantity_from_csv_to_strategy_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_percent_of_equity_default_quantity.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy percent default quantity script should run");

    assert_snapshot(
        "runtime_strategy_percent_of_equity_default_quantity.json",
        &output,
    );
}

#[test]
fn runs_strategy_percent_of_equity_default_quantity_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_percent_of_equity_default_quantity.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy percent default quantity fixture should run");

    assert_snapshot(
        "runtime_strategy_percent_of_equity_default_quantity.json",
        &output,
    );
}

#[test]
fn runs_strategy_cash_default_quantity_from_csv_to_strategy_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_cash_default_quantity.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy cash default quantity script should run");

    assert_snapshot("runtime_strategy_cash_default_quantity.json", &output);
}

#[test]
fn runs_strategy_cash_default_quantity_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_cash_default_quantity.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy cash default quantity fixture should run");

    assert_snapshot("runtime_strategy_cash_default_quantity.json", &output);
}

#[test]
fn runs_strategy_cash_default_quantity_limit_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_cash_default_quantity_limit.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy cash default quantity limit fixture should run");

    assert_snapshot("runtime_strategy_cash_default_quantity_limit.json", &output);
}

#[test]
fn runs_strategy_cash_default_quantity_override_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_cash_default_quantity_override.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy cash default quantity override fixture should run");

    assert_snapshot(
        "runtime_strategy_cash_default_quantity_override.json",
        &output,
    );
}

#[test]
fn runs_strategy_commission_cash_per_contract_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_commission_cash_per_contract.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy cash-per-contract commission fixture should run");

    assert_snapshot(
        "runtime_strategy_commission_cash_per_contract.json",
        &output,
    );
}

#[test]
fn runs_strategy_commission_cash_per_order_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_commission_cash_per_order.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy cash-per-order commission fixture should run");

    assert_snapshot("runtime_strategy_commission_cash_per_order.json", &output);
}

#[test]
fn runs_strategy_commission_percent_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_commission_percent.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy percent commission fixture should run");

    assert_snapshot("runtime_strategy_commission_percent.json", &output);
}

#[test]
fn runs_strategy_slippage_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_slippage.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy slippage fixture should run");

    assert_snapshot("runtime_strategy_slippage.json", &output);
}

#[test]
fn runs_strategy_exit_slippage_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_slippage.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit slippage fixture should run");

    assert_snapshot("runtime_strategy_exit_slippage.json", &output);
}

#[test]
fn runs_strategy_limit_verification_entry_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_limit_verification_entry.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy limit verification entry fixture should run");

    assert_snapshot("runtime_strategy_limit_verification_entry.json", &output);
}

#[test]
fn runs_strategy_limit_verification_exit_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_limit_verification_exit.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy limit verification exit fixture should run");

    assert_snapshot("runtime_strategy_limit_verification_exit.json", &output);
}

#[test]
fn runs_strategy_position_state_from_csv_to_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_position_state.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy position state script should run");

    assert_snapshot("runtime_strategy_position_state.json", &output);
}

#[test]
fn runs_strategy_position_state_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_position_state.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy position state fixture should run");

    assert_snapshot("runtime_strategy_position_state.json", &output);
}

#[test]
fn runs_strategy_equity_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_equity.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy equity fixture should run");

    assert_snapshot("runtime_strategy_equity.json", &output);
}

#[test]
fn runs_strategy_profit_state_from_csv_to_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_profit_state.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy profit state script should run");

    assert_snapshot("runtime_strategy_profit_state.json", &output);
}

#[test]
fn runs_strategy_profit_state_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_profit_state.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy profit state fixture should run");

    assert_snapshot("runtime_strategy_profit_state.json", &output);
}

#[test]
fn runs_strategy_variable_interactions_from_csv_to_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_variable_interactions.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy variable interaction script should run");

    assert_snapshot("runtime_strategy_variable_interactions.json", &output);
}

#[test]
fn runs_strategy_variable_interactions_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_variable_interactions.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy variable interactions fixture should run");

    assert_snapshot("runtime_strategy_variable_interactions.json", &output);
}

#[test]
fn runs_strategy_trade_counts_from_csv_to_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_trade_counts.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy trade count script should run");

    assert_snapshot("runtime_strategy_trade_counts.json", &output);
}

#[test]
fn runs_strategy_trade_counts_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_trade_counts.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy trade count fixture should run");

    assert_snapshot("runtime_strategy_trade_counts.json", &output);
}

#[test]
fn runs_strategy_exit_trade_counts_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_trade_counts.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit trade count fixture should run");

    assert_snapshot("runtime_strategy_exit_trade_counts.json", &output);
}

#[test]
fn runs_strategy_closedtrades_fields_from_csv_to_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_closedtrades_fields.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy closed trade fields script should run");

    assert_snapshot("runtime_strategy_closedtrades_fields.json", &output);
}

#[test]
fn runs_strategy_closedtrades_fields_pyramiding_from_csv_to_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_closedtrades_fields_pyramiding.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy closed trade fields pyramiding script should run");

    assert_snapshot(
        "runtime_strategy_closedtrades_fields_pyramiding.json",
        &output,
    );
}

#[test]
fn runs_strategy_opentrades_fields_from_csv_to_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_opentrades_fields.pine"),
        include_str!("../../../../tests/fixtures/runtime/strategy_opentrades_fields_bars.csv"),
    )
    .expect("strategy open trade fields script should run");

    assert_snapshot("runtime_strategy_opentrades_fields.json", &output);
}

#[test]
fn runs_strategy_opentrades_fields_pyramiding_from_csv_to_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_opentrades_fields_pyramiding.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy open trade fields pyramiding script should run");

    assert_snapshot(
        "runtime_strategy_opentrades_fields_pyramiding.json",
        &output,
    );
}

#[test]
fn runs_strategy_margin_capital_held_from_csv_to_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_margin_capital_held_long.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy margin capital held script should run");

    assert_snapshot("runtime_strategy_margin_capital_held_long.json", &output);
}

#[test]
fn runs_strategy_margin_entry_affordability_from_csv_to_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_margin_entry_affordability_long.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy margin entry affordability script should run");

    assert_snapshot("runtime_strategy_margin_entry_affordability.json", &output);
}

#[test]
fn runs_strategy_margin_call_from_csv_to_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_margin_call_long.pine"),
        include_str!("../../../../tests/fixtures/runtime/strategy_margin_call_long_bars.csv"),
    )
    .expect("strategy margin call script should run");

    assert_snapshot("runtime_strategy_margin_call_long.json", &output);
}

#[test]
fn runs_strategy_trade_outcome_counts_from_csv_to_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_trade_outcome_counts.pine"),
        include_str!("../../../../tests/fixtures/runtime/strategy_trade_outcome_counts_bars.csv"),
    )
    .expect("strategy trade outcome count script should run");

    assert_snapshot("runtime_strategy_trade_outcome_counts.json", &output);
}

#[test]
fn runs_strategy_trade_outcome_counts_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_trade_outcome_counts.pine"),
        include_str!("../../../../tests/fixtures/runtime/strategy_trade_outcome_counts_bars.csv"),
    )
    .expect("strategy trade outcome count fixture should run");

    assert_snapshot("runtime_strategy_trade_outcome_counts.json", &output);
}

#[test]
fn runs_strategy_profit_percent_state_from_csv_to_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_profit_percent_state.pine"),
        include_str!("../../../../tests/fixtures/runtime/strategy_trade_outcome_counts_bars.csv"),
    )
    .expect("strategy profit percent state script should run");

    assert_snapshot("runtime_strategy_profit_percent_state.json", &output);
}

#[test]
fn runs_strategy_profit_percent_state_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_profit_percent_state.pine"),
        include_str!("../../../../tests/fixtures/runtime/strategy_trade_outcome_counts_bars.csv"),
    )
    .expect("strategy profit percent state fixture should run");

    assert_snapshot("runtime_strategy_profit_percent_state.json", &output);
}

#[test]
fn runs_strategy_close_from_csv_to_trade_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_close.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy close script should run");

    assert_snapshot("runtime_strategy_close.json", &output);
}

#[test]
fn runs_strategy_close_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_close.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy close fixture should run");

    assert_snapshot("runtime_strategy_close.json", &output);
}

#[test]
fn runs_strategy_close_noop_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_close_noop.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy close no-op fixture should run");

    assert_snapshot("runtime_strategy_close_noop.json", &output);
}

#[test]
fn runs_strategy_close_qty_partial_from_csv_to_trade_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_close_qty_partial.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy close qty partial fixture should run");

    assert_snapshot("runtime_strategy_close_qty_partial.json", &output);
}

#[test]
fn runs_strategy_close_qty_full_clamp_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_close_qty_full_clamp.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy close qty full clamp fixture should run");

    assert_snapshot("runtime_strategy_close_qty_full_clamp.json", &output);
}

#[test]
fn runs_strategy_close_qty_percent_precedence_from_csv_to_trade_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_close_qty_percent_precedence.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy close qty_percent precedence fixture should run");

    assert_snapshot(
        "runtime_strategy_close_qty_percent_precedence.json",
        &output,
    );
}

#[test]
fn runs_strategy_close_all_from_csv_to_trade_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_close_all.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy close_all script should run");

    assert_snapshot("runtime_strategy_close_all.json", &output);
}

#[test]
fn runs_strategy_close_all_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_close_all.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy close_all fixture should run");

    assert_snapshot("runtime_strategy_close_all.json", &output);
}

#[test]
fn runs_strategy_close_exit_fixture_from_csv_to_public_strategy_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_close_exit.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy close exit fixture should run");

    assert_snapshot("runtime_strategy_close_exit.json", &output);
}

#[test]
fn runs_strategy_close_all_exit_fixture_from_csv_to_public_strategy_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_close_all_exit.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy close_all exit fixture should run");

    assert_snapshot("runtime_strategy_close_all_exit.json", &output);
}

#[test]
fn runs_strategy_exit_stop_from_csv_to_trade_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_stop.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit stop script should run");

    assert_snapshot("runtime_strategy_exit_stop.json", &output);
}

#[test]
fn runs_strategy_exit_stop_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_stop.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit stop fixture should run");

    assert_snapshot("runtime_strategy_exit_stop.json", &output);
}

#[test]
fn runs_strategy_cancel_entry_fixture_from_csv_to_public_strategy_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_cancel_entry.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy cancel entry script should run");

    assert_snapshot("runtime_strategy_cancel_entry.json", &output);
}

#[test]
fn runs_strategy_cancel_exit_fixture_from_csv_to_public_strategy_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_cancel_exit.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy cancel exit script should run");

    assert_snapshot("runtime_strategy_cancel_exit.json", &output);
}

#[test]
fn runs_strategy_cancel_noop_fixture_from_csv_to_public_strategy_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_cancel_noop.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy cancel noop script should run");

    assert_snapshot("runtime_strategy_cancel_noop.json", &output);
}

#[test]
fn runs_strategy_cancel_all_entry_exit_fixture_from_csv_to_public_strategy_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_cancel_all_entry_exit.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy cancel all entry exit script should run");

    assert_snapshot("runtime_strategy_cancel_all_entry_exit.json", &output);
}

#[test]
fn runs_strategy_cancel_all_exit_fixture_from_csv_to_public_strategy_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_cancel_all_exit.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy cancel all exit script should run");

    assert_snapshot("runtime_strategy_cancel_all_exit.json", &output);
}

#[test]
fn runs_strategy_cancel_all_noop_fixture_from_csv_to_public_strategy_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_cancel_all_noop.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy cancel all noop script should run");

    assert_snapshot("runtime_strategy_cancel_all_noop.json", &output);
}

#[test]
fn runs_strategy_exit_limit_from_csv_to_trade_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_limit.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit limit script should run");

    assert_snapshot("runtime_strategy_exit_limit.json", &output);
}

#[test]
fn runs_strategy_exit_limit_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_limit.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit limit fixture should run");

    assert_snapshot("runtime_strategy_exit_limit.json", &output);
}

#[test]
fn runs_strategy_exit_profit_from_csv_to_trade_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_profit.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit profit script should run");

    assert_snapshot("runtime_strategy_exit_profit.json", &output);
}

#[test]
fn runs_strategy_exit_loss_from_csv_to_trade_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_loss.pine"),
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_loss_bars.csv"),
    )
    .expect("strategy exit loss script should run");

    assert_snapshot("runtime_strategy_exit_loss.json", &output);
}

#[test]
fn runs_strategy_exit_profit_loss_interactions_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_profit_loss_interactions.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_profit_loss_interactions_bars.csv"
        ),
    )
    .expect("strategy exit profit/loss interactions fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_profit_loss_interactions.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_bracket_fixture_from_csv_to_trade_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_bracket_both_hit.pine"),
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_bracket_both_hit_bars.csv"),
    )
    .expect("strategy exit bracket fixture should run");

    assert_snapshot("runtime_strategy_exit_bracket_both_hit.json", &output);
}

#[test]
fn runs_strategy_exit_bracket_creation_bar_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_bracket_creation_bar.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit bracket creation-bar fixture should run");

    assert_snapshot("runtime_strategy_exit_bracket_creation_bar.json", &output);
}

#[test]
fn runs_strategy_exit_bracket_interactions_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_bracket_interactions.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit bracket interactions fixture should run");

    assert_snapshot("runtime_strategy_exit_bracket_interactions.json", &output);
}

#[test]
fn runs_strategy_exit_interactions_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_interactions.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit interactions fixture should run");

    assert_snapshot("runtime_strategy_exit_interactions.json", &output);
}

#[test]
fn runs_strategy_exit_bracket_invalid_leg_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_bracket_invalid_leg.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit bracket invalid-leg fixture should run");

    assert_snapshot("runtime_strategy_exit_bracket_invalid_leg.json", &output);
}

#[test]
fn runs_strategy_exit_bracket_loss_profit_loss_fill_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_bracket_loss_profit_loss_fill.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_bracket_loss_profit_loss_bars.csv"
        ),
    )
    .expect("strategy exit loss-profit bracket loss-fill fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_bracket_loss_profit_loss_fill.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_bracket_loss_profit_profit_fill_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_bracket_loss_profit_profit_fill.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit loss-profit bracket profit-fill fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_bracket_loss_profit_profit_fill.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_bracket_mixed_pairs_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_bracket_mixed_pairs.pine"),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_bracket_mixed_pairs_bars.csv"
        ),
    )
    .expect("strategy exit mixed bracket pairs fixture should run");

    assert_snapshot("runtime_strategy_exit_bracket_mixed_pairs.json", &output);
}

#[test]
fn runs_strategy_exit_bracket_repeated_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_bracket_repeated.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit repeated bracket fixture should run");

    assert_snapshot("runtime_strategy_exit_bracket_repeated.json", &output);
}

#[test]
fn runs_strategy_exit_bracket_replacement_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_bracket_replacement.pine"),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_bracket_replacement_bars.csv"
        ),
    )
    .expect("strategy exit bracket replacement fixture should run");

    assert_snapshot("runtime_strategy_exit_bracket_replacement.json", &output);
}

#[test]
fn runs_strategy_exit_omitted_bracket_replacement_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_omitted_bracket_replacement.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit omitted bracket replacement fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_omitted_bracket_replacement.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_bracket_state_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_bracket_state.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit bracket state fixture should run");

    assert_snapshot("runtime_strategy_exit_bracket_state.json", &output);
}

#[test]
fn runs_strategy_exit_bracket_stop_limit_limit_fill_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_bracket_stop_limit_limit_fill.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit stop-limit bracket limit-fill fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_bracket_stop_limit_limit_fill.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_bracket_stop_limit_stop_fill_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_bracket_stop_limit_stop_fill.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit stop-limit bracket stop-fill fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_bracket_stop_limit_stop_fill.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_trailing_fixture_from_csv_to_trade_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_trail_price_fill.pine"),
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_trailing_bars.csv"),
    )
    .expect("strategy exit trailing fixture should run");

    assert_snapshot("runtime_strategy_exit_trail_price_fill.json", &output);
}

#[test]
fn runs_strategy_exit_trail_points_fill_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_trail_points_fill.pine"),
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_trailing_bars.csv"),
    )
    .expect("strategy exit trail_points fill fixture should run");

    assert_snapshot("runtime_strategy_exit_trail_points_fill.json", &output);
}

#[test]
fn runs_strategy_exit_trailing_state_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_trailing_state.pine"),
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_trailing_bars.csv"),
    )
    .expect("strategy exit trailing state fixture should run");

    assert_snapshot("runtime_strategy_exit_trailing_state.json", &output);
}

#[test]
fn runs_strategy_exit_trailing_replacement_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_trailing_replacement.pine"),
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_trailing_bars.csv"),
    )
    .expect("strategy exit trailing replacement fixture should run");

    assert_snapshot("runtime_strategy_exit_trailing_replacement.json", &output);
}

#[test]
fn runs_strategy_exit_trailing_activation_bar_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_trailing_activation_bar.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_trailing_bars.csv"),
    )
    .expect("strategy exit trailing activation bar fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_trailing_activation_bar.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_trailing_ratchet_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_trailing_ratchet.pine"),
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_trailing_bars.csv"),
    )
    .expect("strategy exit trailing ratchet fixture should run");

    assert_snapshot("runtime_strategy_exit_trailing_ratchet.json", &output);
}

#[test]
fn runs_strategy_exit_trailing_repeated_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_trailing_repeated.pine"),
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_trailing_bars.csv"),
    )
    .expect("strategy exit trailing repeated fixture should run");

    assert_snapshot("runtime_strategy_exit_trailing_repeated.json", &output);
}

#[test]
fn runs_strategy_exit_trailing_invalid_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_trailing_invalid.pine"),
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_trailing_bars.csv"),
    )
    .expect("strategy exit trailing invalid fixture should run");

    assert_snapshot("runtime_strategy_exit_trailing_invalid.json", &output);
}

#[test]
fn runs_strategy_exit_trailing_close_cancel_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_trailing_close_cancel.pine"),
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_trailing_bars.csv"),
    )
    .expect("strategy exit trailing close cancel fixture should run");

    assert_snapshot("runtime_strategy_exit_trailing_close_cancel.json", &output);
}

#[test]
fn runs_strategy_exit_trailing_interactions_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_trailing_interactions.pine"),
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_trailing_bars.csv"),
    )
    .expect("strategy exit trailing interactions fixture should run");

    assert_snapshot("runtime_strategy_exit_trailing_interactions.json", &output);
}

#[test]
fn runs_strategy_exit_omitted_trailing_replacement_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_omitted_trailing_replacement.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_trailing_bars.csv"),
    )
    .expect("strategy exit omitted trailing replacement fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_omitted_trailing_replacement.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_qty_partial_fixture_from_csv_to_trade_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_qty_stop_partial.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit partial quantity fixture should run");

    assert_snapshot("runtime_strategy_exit_qty_stop_partial.json", &output);
}

#[test]
fn runs_strategy_exit_qty_limit_partial_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_qty_limit_partial.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit qty limit partial fixture should run");

    assert_snapshot("runtime_strategy_exit_qty_limit_partial.json", &output);
}

#[test]
fn runs_strategy_exit_qty_bracket_partial_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_qty_bracket_partial.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit qty bracket partial fixture should run");

    assert_snapshot("runtime_strategy_exit_qty_bracket_partial.json", &output);
}

#[test]
fn runs_strategy_exit_reservation_qty_clamp_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_reservation_qty_clamp.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit reservation qty clamp fixture should run");

    assert_snapshot("runtime_strategy_exit_reservation_qty_clamp.json", &output);
}

#[test]
fn runs_strategy_exit_reservation_qty_stop_multi_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_qty_stop_multi.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit reservation qty stop multi fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_reservation_qty_stop_multi.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_reservation_qty_limit_multi_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_qty_limit_multi.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit reservation qty limit multi fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_reservation_qty_limit_multi.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_reservation_qty_replacement_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_qty_replacement.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit reservation qty replacement fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_reservation_qty_replacement.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_reservation_qty_percent_stop_multi_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_qty_percent_stop_multi.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit reservation qty percent stop multi fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_reservation_qty_percent_stop_multi.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_reservation_qty_mixed_stop_multi_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_qty_mixed_stop_multi.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit reservation qty mixed stop multi fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_reservation_qty_mixed_stop_multi.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_reservation_qty_percent_replacement_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_qty_percent_replacement.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit reservation qty percent replacement fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_reservation_qty_percent_replacement.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_reservation_qty_percent_clamp_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_qty_percent_clamp.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit reservation qty percent clamp fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_reservation_qty_percent_clamp.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_reservation_qty_bracket_clamp_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_qty_bracket_clamp.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit reservation qty bracket clamp fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_reservation_qty_bracket_clamp.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_reservation_qty_bracket_replacement_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_qty_bracket_replacement.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit reservation qty bracket replacement fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_reservation_qty_bracket_replacement.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_reservation_qty_bracket_stop_limit_downside_multi_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_qty_bracket_stop_limit_downside_multi.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit reservation qty bracket stop limit downside multi fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_reservation_qty_bracket_stop_limit_downside_multi.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_reservation_qty_bracket_stop_limit_upside_multi_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_qty_bracket_stop_limit_upside_multi.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit reservation qty bracket stop limit upside multi fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_reservation_qty_bracket_stop_limit_upside_multi.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_reservation_qty_mixed_bracket_multi_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_qty_mixed_bracket_multi.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit reservation qty mixed bracket multi fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_reservation_qty_mixed_bracket_multi.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_reservation_qty_percent_bracket_multi_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_qty_percent_bracket_multi.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit reservation qty percent bracket multi fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_reservation_qty_percent_bracket_multi.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_reservation_qty_percent_bracket_replacement_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_qty_percent_bracket_replacement.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit reservation qty percent bracket replacement fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_reservation_qty_percent_bracket_replacement.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_reservation_qty_percent_bracket_clamp_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_qty_percent_bracket_clamp.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit reservation qty percent bracket clamp fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_reservation_qty_percent_bracket_clamp.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_reservation_qty_mixed_trailing_multi_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_qty_mixed_trailing_multi.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_trailing_bars.csv"
        ),
    )
    .expect("strategy exit reservation qty mixed trailing multi fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_reservation_qty_mixed_trailing_multi.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_reservation_trailing_state_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_trailing_state.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_trailing_bars.csv"
        ),
    )
    .expect("strategy exit reservation trailing state fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_reservation_trailing_state.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_reservation_qty_trailing_clamp_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_qty_trailing_clamp.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_trailing_bars.csv"
        ),
    )
    .expect("strategy exit reservation qty trailing clamp fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_reservation_qty_trailing_clamp.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_reservation_qty_trailing_points_multi_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_qty_trailing_points_multi.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_trailing_bars.csv"
        ),
    )
    .expect("strategy exit reservation qty trailing points multi fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_reservation_qty_trailing_points_multi.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_reservation_qty_trailing_price_multi_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_qty_trailing_price_multi.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_trailing_bars.csv"
        ),
    )
    .expect("strategy exit reservation qty trailing price multi fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_reservation_qty_trailing_price_multi.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_reservation_qty_trailing_replacement_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_qty_trailing_replacement.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_trailing_bars.csv"
        ),
    )
    .expect("strategy exit reservation qty trailing replacement fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_reservation_qty_trailing_replacement.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_reservation_trailing_activation_mixed_fill_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_trailing_activation_mixed_fill.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_trailing_mixed_bars.csv"
        ),
    )
    .expect("strategy exit reservation trailing activation mixed fill fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_reservation_trailing_activation_mixed_fill.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_reservation_trailing_single_downside_order_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_trailing_single_downside_order.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_trailing_mixed_bars.csv"
        ),
    )
    .expect("strategy exit reservation trailing single downside order fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_reservation_trailing_single_downside_order.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_reservation_trailing_bracket_downside_order_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_trailing_bracket_downside_order.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_trailing_mixed_bars.csv"
        ),
    )
    .expect("strategy exit reservation trailing bracket downside order fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_reservation_trailing_bracket_downside_order.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_reservation_trailing_mixed_side_precedence_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_trailing_mixed_side_precedence.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_trailing_mixed_bars.csv"
        ),
    )
    .expect("strategy exit reservation trailing mixed side precedence fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_reservation_trailing_mixed_side_precedence.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_reservation_trailing_mixed_state_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_trailing_mixed_state.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_trailing_mixed_bars.csv"
        ),
    )
    .expect("strategy exit reservation trailing mixed state fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_reservation_trailing_mixed_state.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_reservation_trailing_replacement_mixed_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_trailing_replacement_mixed.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_trailing_mixed_bars.csv"
        ),
    )
    .expect("strategy exit reservation trailing replacement mixed fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_reservation_trailing_replacement_mixed.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_reservation_qty_percent_trailing_multi_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_qty_percent_trailing_multi.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_trailing_bars.csv"
        ),
    )
    .expect("strategy exit reservation qty percent trailing multi fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_reservation_qty_percent_trailing_multi.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_reservation_qty_percent_trailing_replacement_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_qty_percent_trailing_replacement.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_trailing_bars.csv"
        ),
    )
    .expect("strategy exit reservation qty percent trailing replacement fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_reservation_qty_percent_trailing_replacement.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_reservation_qty_percent_trailing_clamp_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_qty_percent_trailing_clamp.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_trailing_bars.csv"
        ),
    )
    .expect("strategy exit reservation qty percent trailing clamp fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_reservation_qty_percent_trailing_clamp.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_qty_trailing_partial_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_qty_trailing_partial.pine"),
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_trailing_bars.csv"),
    )
    .expect("strategy exit qty trailing partial fixture should run");

    assert_snapshot("runtime_strategy_exit_qty_trailing_partial.json", &output);
}

#[test]
fn runs_strategy_exit_qty_full_clamp_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_qty_full_clamp.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit qty full clamp fixture should run");

    assert_snapshot("runtime_strategy_exit_qty_full_clamp.json", &output);
}

#[test]
fn runs_strategy_exit_qty_repeated_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_qty_repeated.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit qty repeated fixture should run");

    assert_snapshot("runtime_strategy_exit_qty_repeated.json", &output);
}

#[test]
fn runs_strategy_exit_qty_replacement_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_qty_replacement.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit qty replacement fixture should run");

    assert_snapshot("runtime_strategy_exit_qty_replacement.json", &output);
}

#[test]
fn runs_strategy_exit_qty_state_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_qty_state.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit qty state fixture should run");

    assert_snapshot("runtime_strategy_exit_qty_state.json", &output);
}

#[test]
fn runs_strategy_exit_qty_precedence_fixture_from_csv_to_trade_json() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_qty_precedence_stop.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit qty precedence fixture should run");

    assert_snapshot("runtime_strategy_exit_qty_precedence_stop.json", &output);
}

#[test]
fn runs_strategy_exit_qty_precedence_bracket_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_qty_precedence_bracket.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit qty precedence bracket fixture should run");

    assert_snapshot("runtime_strategy_exit_qty_precedence_bracket.json", &output);
}

#[test]
fn runs_strategy_exit_qty_precedence_trailing_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_qty_precedence_trailing.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_qty_precedence_trailing_bars.csv"
        ),
    )
    .expect("strategy exit qty precedence trailing fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_qty_precedence_trailing.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_qty_percent_partial_fixture_from_csv_to_trade_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_qty_percent_stop_partial.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit percent quantity fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_qty_percent_stop_partial.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_qty_percent_limit_partial_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_qty_percent_limit_partial.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit qty percent limit partial fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_qty_percent_limit_partial.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_qty_percent_bracket_partial_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_qty_percent_bracket_partial.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit qty percent bracket partial fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_qty_percent_bracket_partial.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_qty_percent_trailing_partial_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_qty_percent_trailing_partial.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_trailing_bars.csv"),
    )
    .expect("strategy exit qty percent trailing partial fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_qty_percent_trailing_partial.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_qty_percent_full_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_qty_percent_full.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit qty percent full fixture should run");

    assert_snapshot("runtime_strategy_exit_qty_percent_full.json", &output);
}

#[test]
fn runs_strategy_exit_qty_percent_full_clamp_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_qty_percent_full_clamp.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit qty percent full clamp fixture should run");

    assert_snapshot("runtime_strategy_exit_qty_percent_full_clamp.json", &output);
}

#[test]
fn runs_strategy_exit_qty_percent_repeated_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_qty_percent_repeated.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit qty percent repeated fixture should run");

    assert_snapshot("runtime_strategy_exit_qty_percent_repeated.json", &output);
}

#[test]
fn runs_strategy_exit_qty_percent_replacement_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_qty_percent_replacement.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit qty percent replacement fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_qty_percent_replacement.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_qty_percent_state_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_qty_percent_state.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit qty percent state fixture should run");

    assert_snapshot("runtime_strategy_exit_qty_percent_state.json", &output);
}

#[test]
fn runs_strategy_exit_reservation_fixture_from_csv_to_public_strategy_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_mixed_side_precedence.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit reservation fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_reservation_mixed_side_precedence.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_reservation_state_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_reservation_state.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit reservation state fixture should run");

    assert_snapshot("runtime_strategy_exit_reservation_state.json", &output);
}

#[test]
fn runs_strategy_exit_reservation_interactions_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_interactions.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit reservation interactions fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_reservation_interactions.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_omitted_single_replacement_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_omitted_single_replacement.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit omitted single replacement fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_omitted_single_replacement.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_omitted_replaces_reservations_from_csv_to_public_strategy_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_omitted_replaces_reservations.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit omitted replacement fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_omitted_replaces_reservations.json",
        &output,
    );
}

#[test]
fn runs_strategy_omitted_current_all_entry_exit_fixture_from_csv_to_public_strategy_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_from_entry_current.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_from_entry_current_bars.csv"
        ),
    )
    .expect("strategy omitted current all-entry exit fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_from_entry_current.json",
        &output,
    );
}

#[test]
fn runs_strategy_omitted_persistent_all_entry_exit_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_from_entry_persistent.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_from_entry_persistent_bars.csv"
        ),
    )
    .expect("strategy omitted persistent all-entry exit fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_from_entry_persistent.json",
        &output,
    );
}

#[test]
fn runs_strategy_omitted_profit_from_entries_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_profit_from_entries.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_profit_from_entries_bars.csv"
        ),
    )
    .expect("strategy omitted profit from entries fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_profit_from_entries.json",
        &output,
    );
}

#[test]
fn runs_strategy_omitted_loss_from_entries_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_from_entries.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_from_entries_bars.csv"
        ),
    )
    .expect("strategy omitted loss from entries fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_loss_from_entries.json",
        &output,
    );
}

#[test]
fn runs_strategy_omitted_profit_same_id_fixture_from_csv_to_public_strategy_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_profit_same_id.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_profit_same_id_bars.csv"
        ),
    )
    .expect("strategy omitted profit same-id fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_profit_same_id.json",
        &output,
    );
}

#[test]
fn runs_strategy_omitted_profit_same_id_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_profit_same_id.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_profit_same_id_bars.csv"
        ),
    )
    .expect("strategy omitted profit same-id fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_profit_same_id.json",
        &output,
    );
}

#[test]
fn runs_strategy_omitted_loss_same_id_fixture_from_csv_to_public_strategy_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_same_id.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_same_id_bars.csv"
        ),
    )
    .expect("strategy omitted loss same-id fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_loss_same_id.json",
        &output,
    );
}

#[test]
fn runs_strategy_omitted_loss_same_id_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_same_id.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_same_id_bars.csv"
        ),
    )
    .expect("strategy omitted loss same-id fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_loss_same_id.json",
        &output,
    );
}

#[test]
fn runs_strategy_omitted_loss_profit_bracket_same_id_fixture_from_csv_to_public_strategy_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_profit_bracket_same_id.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_profit_bracket_same_id_bars.csv"
        ),
    )
    .expect("strategy omitted loss+profit bracket same-id fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_loss_profit_bracket_same_id.json",
        &output,
    );
}

#[test]
fn runs_strategy_omitted_loss_profit_bracket_same_id_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_profit_bracket_same_id.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_profit_bracket_same_id_bars.csv"
        ),
    )
    .expect("strategy omitted loss+profit bracket same-id fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_loss_profit_bracket_same_id.json",
        &output,
    );
}

#[test]
fn runs_strategy_omitted_loss_profit_bracket_from_entries_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_profit_bracket_from_entries.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_profit_bracket_from_entries_bars.csv"
        ),
    )
    .expect("strategy omitted loss-profit bracket from entries fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_loss_profit_bracket_from_entries.json",
        &output,
    );
}

#[test]
fn runs_strategy_omitted_stop_profit_bracket_from_entries_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_stop_profit_bracket_from_entries.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_stop_profit_bracket_from_entries_bars.csv"
        ),
    )
    .expect("strategy omitted stop-profit bracket from entries fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_stop_profit_bracket_from_entries.json",
        &output,
    );
}

#[test]
fn runs_strategy_omitted_loss_limit_bracket_from_entries_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_limit_bracket_from_entries.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_limit_bracket_from_entries_bars.csv"
        ),
    )
    .expect("strategy omitted loss-limit bracket from entries fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_loss_limit_bracket_from_entries.json",
        &output,
    );
}

#[test]
fn runs_strategy_omitted_stop_limit_bracket_from_entries_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_stop_limit_bracket_from_entries.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_stop_limit_bracket_from_entries_bars.csv"
        ),
    )
    .expect("strategy omitted stop-limit bracket from entries fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_stop_limit_bracket_from_entries.json",
        &output,
    );
}

#[test]
fn runs_strategy_omitted_trail_points_from_entries_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_trail_points_from_entries.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_trail_points_from_entries_bars.csv"
        ),
    )
    .expect("strategy omitted trail-points from entries fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_trail_points_from_entries.json",
        &output,
    );
}

#[test]
fn runs_strategy_omitted_trail_price_from_entries_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_trail_price_from_entries.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_trail_price_from_entries_bars.csv"
        ),
    )
    .expect("strategy omitted trail-price from entries fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_trail_price_from_entries.json",
        &output,
    );
}

#[test]
fn runs_strategy_omitted_stop_profit_bracket_same_id_fixture_from_csv_to_public_strategy_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_stop_profit_bracket_same_id.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_stop_profit_bracket_same_id_bars.csv"
        ),
    )
    .expect("strategy omitted stop+profit bracket same-id fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_stop_profit_bracket_same_id.json",
        &output,
    );
}

#[test]
fn runs_strategy_omitted_stop_profit_bracket_same_id_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_stop_profit_bracket_same_id.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_stop_profit_bracket_same_id_bars.csv"
        ),
    )
    .expect("strategy omitted stop+profit bracket same-id fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_stop_profit_bracket_same_id.json",
        &output,
    );
}

#[test]
fn runs_strategy_omitted_loss_limit_bracket_same_id_fixture_from_csv_to_public_strategy_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_limit_bracket_same_id.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_limit_bracket_same_id_bars.csv"
        ),
    )
    .expect("strategy omitted loss+limit bracket same-id fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_loss_limit_bracket_same_id.json",
        &output,
    );
}

#[test]
fn runs_strategy_omitted_loss_limit_bracket_same_id_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_limit_bracket_same_id.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_limit_bracket_same_id_bars.csv"
        ),
    )
    .expect("strategy omitted loss+limit bracket same-id fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_loss_limit_bracket_same_id.json",
        &output,
    );
}

#[test]
fn runs_strategy_omitted_stop_limit_bracket_same_id_fixture_from_csv_to_public_strategy_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_stop_limit_bracket_same_id.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_stop_limit_bracket_same_id_bars.csv"
        ),
    )
    .expect("strategy omitted stop+limit bracket same-id fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_stop_limit_bracket_same_id.json",
        &output,
    );
}

#[test]
fn runs_strategy_omitted_stop_limit_bracket_same_id_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_stop_limit_bracket_same_id.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_stop_limit_bracket_same_id_bars.csv"
        ),
    )
    .expect("strategy omitted stop+limit bracket same-id fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_stop_limit_bracket_same_id.json",
        &output,
    );
}

#[test]
fn runs_strategy_omitted_trail_points_same_id_fixture_from_csv_to_public_strategy_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_trail_points_same_id.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_trail_points_same_id_bars.csv"
        ),
    )
    .expect("strategy omitted trail_points same-id fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_trail_points_same_id.json",
        &output,
    );
}

#[test]
fn runs_strategy_omitted_trail_points_same_id_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_trail_points_same_id.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_trail_points_same_id_bars.csv"
        ),
    )
    .expect("strategy omitted trail_points same-id fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_trail_points_same_id.json",
        &output,
    );
}

#[test]
fn runs_strategy_omitted_trail_price_same_id_fixture_from_csv_to_public_strategy_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_trail_price_same_id.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_trail_price_same_id_bars.csv"
        ),
    )
    .expect("strategy omitted trail_price same-id fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_trail_price_same_id.json",
        &output,
    );
}

#[test]
fn runs_strategy_omitted_trail_price_same_id_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_trail_price_same_id.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_trail_price_same_id_bars.csv"
        ),
    )
    .expect("strategy omitted trail_price same-id fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_trail_price_same_id.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_active_entry_attachment_from_csv_to_public_strategy_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_active_entry_attachment.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit active-entry attachment fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_active_entry_attachment.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_active_entry_attachment_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_active_entry_attachment.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit active-entry attachment fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_active_entry_attachment.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_active_entry_profit_attachment_from_csv_to_public_strategy_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_active_entry_profit_attachment.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit active-entry profit attachment fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_active_entry_profit_attachment.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_active_entry_loss_attachment_from_csv_to_public_strategy_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_active_entry_loss_attachment.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit active-entry loss attachment fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_active_entry_loss_attachment.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_active_entry_trail_points_attachment_from_csv_to_public_strategy_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_active_entry_trail_points_attachment.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_trailing_bars.csv"),
    )
    .expect("strategy exit active-entry trail-points attachment fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_active_entry_trail_points_attachment.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_active_entry_stop_profit_bracket_from_csv_to_public_strategy_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_active_entry_stop_profit_bracket.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_trailing_bars.csv"),
    )
    .expect("strategy exit active-entry stop-profit bracket fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_active_entry_stop_profit_bracket.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_active_entry_loss_limit_bracket_from_csv_to_public_strategy_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_active_entry_loss_limit_bracket.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_trailing_bars.csv"),
    )
    .expect("strategy exit active-entry loss-limit bracket fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_active_entry_loss_limit_bracket.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_active_entry_loss_profit_bracket_from_csv_to_public_strategy_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_active_entry_loss_profit_bracket.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/strategy_exit_trailing_bars.csv"),
    )
    .expect("strategy exit active-entry loss-profit bracket fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_active_entry_loss_profit_bracket.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_bracket_reservation_fixture_from_csv_to_public_strategy_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_bracket_host_parity.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit bracket reservation fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_reservation_bracket_host_parity.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_reservation_bracket_single_downside_precedence_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_bracket_single_downside_precedence.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit reservation bracket single downside precedence fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_reservation_bracket_single_downside_precedence.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_reservation_bracket_single_replacement_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_bracket_single_replacement.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit reservation bracket single replacement fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_reservation_bracket_single_replacement.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_reservation_bracket_single_upside_order_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_bracket_single_upside_order.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit reservation bracket single upside order fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_reservation_bracket_single_upside_order.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_reservation_bracket_state_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_bracket_state.pine"
        ),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("strategy exit reservation bracket state fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_reservation_bracket_state.json",
        &output,
    );
}

#[test]
fn runs_strategy_exit_trailing_reservation_fixture_from_csv_to_public_strategy_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_trailing_host_parity.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_exit_reservation_trailing_host_parity_bars.csv"
        ),
    )
    .expect("strategy exit trailing reservation fixture should run");

    assert_snapshot(
        "runtime_strategy_exit_reservation_trailing_host_parity.json",
        &output,
    );
}

#[test]
fn runs_strategy_omitted_profit_persistent_fixture_from_csv_to_public_strategy_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_profit_persistent_from_entries.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_profit_persistent_from_entries_bars.csv"
        ),
    )
    .expect("strategy omitted profit persistent fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_profit_persistent_from_entries.json",
        &output,
    );
}

#[test]
fn runs_strategy_omitted_loss_persistent_fixture_from_csv_to_public_strategy_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_persistent_from_entries.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_persistent_from_entries_bars.csv"
        ),
    )
    .expect("strategy omitted loss persistent fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_loss_persistent_from_entries.json",
        &output,
    );
}

#[test]
fn runs_strategy_omitted_profit_persistent_same_id_fixture_from_csv_to_public_strategy_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_profit_persistent_same_id.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_profit_persistent_same_id_bars.csv"
        ),
    )
    .expect("strategy omitted profit persistent same-id fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_profit_persistent_same_id.json",
        &output,
    );
}

#[test]
fn runs_strategy_omitted_profit_persistent_same_id_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_profit_persistent_same_id.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_profit_persistent_same_id_bars.csv"
        ),
    )
    .expect("strategy omitted profit persistent same-id fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_profit_persistent_same_id.json",
        &output,
    );
}

#[test]
fn runs_strategy_omitted_loss_persistent_same_id_fixture_from_csv_to_public_strategy_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_persistent_same_id.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_persistent_same_id_bars.csv"
        ),
    )
    .expect("strategy omitted loss persistent same-id fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_loss_persistent_same_id.json",
        &output,
    );
}

#[test]
fn runs_strategy_omitted_loss_persistent_same_id_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_persistent_same_id.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_persistent_same_id_bars.csv"
        ),
    )
    .expect("strategy omitted loss persistent same-id fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_loss_persistent_same_id.json",
        &output,
    );
}

#[test]
fn runs_strategy_omitted_loss_profit_bracket_persistent_fixture_from_csv_to_public_strategy_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_profit_bracket_persistent_from_entries.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_profit_bracket_persistent_from_entries_bars.csv"
        ),
    )
    .expect("strategy omitted loss-profit bracket persistent fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_loss_profit_bracket_persistent_from_entries.json",
        &output,
    );
}

#[test]
fn runs_strategy_omitted_stop_profit_bracket_persistent_fixture_from_csv_to_public_strategy_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_stop_profit_bracket_persistent_from_entries.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_stop_profit_bracket_persistent_from_entries_bars.csv"
        ),
    )
    .expect("strategy omitted stop-profit bracket persistent fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_stop_profit_bracket_persistent_from_entries.json",
        &output,
    );
}

#[test]
fn runs_omitted_loss_profit_bracket_persistent_same_id_from_csv_to_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_profit_bracket_persistent_same_id.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_profit_bracket_persistent_same_id_bars.csv"
        ),
    )
    .expect("strategy omitted loss-profit bracket persistent same-id fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_loss_profit_bracket_persistent_same_id.json",
        &output,
    );
}

#[test]
fn runs_strategy_omitted_loss_profit_bracket_persistent_same_id_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_profit_bracket_persistent_same_id.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_profit_bracket_persistent_same_id_bars.csv"
        ),
    )
    .expect("strategy omitted loss-profit bracket persistent same-id fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_loss_profit_bracket_persistent_same_id.json",
        &output,
    );
}

#[test]
fn runs_omitted_stop_profit_bracket_persistent_same_id_from_csv_to_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_stop_profit_bracket_persistent_same_id.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_stop_profit_bracket_persistent_same_id_bars.csv"
        ),
    )
    .expect("strategy omitted stop-profit bracket persistent same-id fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_stop_profit_bracket_persistent_same_id.json",
        &output,
    );
}

#[test]
fn runs_strategy_omitted_stop_profit_bracket_persistent_same_id_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_stop_profit_bracket_persistent_same_id.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_stop_profit_bracket_persistent_same_id_bars.csv"
        ),
    )
    .expect("strategy omitted stop-profit bracket persistent same-id fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_stop_profit_bracket_persistent_same_id.json",
        &output,
    );
}

#[test]
fn runs_omitted_loss_limit_bracket_persistent_same_id_from_csv_to_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_limit_bracket_persistent_same_id.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_limit_bracket_persistent_same_id_bars.csv"
        ),
    )
    .expect("strategy omitted loss-limit bracket persistent same-id fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_loss_limit_bracket_persistent_same_id.json",
        &output,
    );
}

#[test]
fn runs_omitted_stop_limit_bracket_persistent_same_id_from_csv_to_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_stop_limit_bracket_persistent_same_id.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_stop_limit_bracket_persistent_same_id_bars.csv"
        ),
    )
    .expect("strategy omitted stop-limit bracket persistent same-id fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_stop_limit_bracket_persistent_same_id.json",
        &output,
    );
}

#[test]
fn runs_strategy_omitted_stop_limit_bracket_persistent_same_id_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_stop_limit_bracket_persistent_same_id.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_stop_limit_bracket_persistent_same_id_bars.csv"
        ),
    )
    .expect("strategy omitted stop-limit bracket persistent same-id fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_stop_limit_bracket_persistent_same_id.json",
        &output,
    );
}

#[test]
fn runs_omitted_trail_price_persistent_same_id_from_csv_to_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_trail_price_persistent_same_id.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_trail_price_persistent_same_id_bars.csv"
        ),
    )
    .expect("strategy omitted trail-price persistent same-id fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_trail_price_persistent_same_id.json",
        &output,
    );
}

#[test]
fn runs_strategy_omitted_trail_price_persistent_same_id_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_trail_price_persistent_same_id.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_trail_price_persistent_same_id_bars.csv"
        ),
    )
    .expect("strategy omitted trail-price persistent same-id fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_trail_price_persistent_same_id.json",
        &output,
    );
}

#[test]
fn runs_omitted_trail_points_persistent_same_id_from_csv_to_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_trail_points_persistent_same_id.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_trail_points_persistent_same_id_bars.csv"
        ),
    )
    .expect("strategy omitted trail-points persistent same-id fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_trail_points_persistent_same_id.json",
        &output,
    );
}

#[test]
fn runs_strategy_omitted_trail_points_persistent_same_id_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_trail_points_persistent_same_id.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_trail_points_persistent_same_id_bars.csv"
        ),
    )
    .expect("strategy omitted trail-points persistent same-id fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_trail_points_persistent_same_id.json",
        &output,
    );
}

#[test]
fn runs_strategy_omitted_loss_limit_bracket_persistent_same_id_fixture_contract() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_limit_bracket_persistent_same_id.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_limit_bracket_persistent_same_id_bars.csv"
        ),
    )
    .expect("strategy omitted loss-limit bracket persistent same-id fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_loss_limit_bracket_persistent_same_id.json",
        &output,
    );
}

#[test]
fn runs_strategy_omitted_loss_limit_bracket_persistent_fixture_from_csv_to_public_strategy_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_limit_bracket_persistent_from_entries.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_limit_bracket_persistent_from_entries_bars.csv"
        ),
    )
    .expect("strategy omitted loss-limit bracket persistent fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_loss_limit_bracket_persistent_from_entries.json",
        &output,
    );
}

#[test]
fn runs_strategy_omitted_stop_limit_bracket_persistent_fixture_from_csv_to_public_strategy_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_stop_limit_bracket_persistent_from_entries.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_stop_limit_bracket_persistent_from_entries_bars.csv"
        ),
    )
    .expect("strategy omitted stop-limit bracket persistent fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_stop_limit_bracket_persistent_from_entries.json",
        &output,
    );
}

#[test]
fn runs_strategy_omitted_trail_price_persistent_fixture_from_csv_to_public_strategy_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_trail_price_persistent_from_entries.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_trail_price_persistent_from_entries_bars.csv"
        ),
    )
    .expect("strategy omitted trail-price persistent fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_trail_price_persistent_from_entries.json",
        &output,
    );
}

#[test]
fn runs_strategy_omitted_trail_points_persistent_fixture_from_csv_to_public_strategy_json() {
    let output = run_script_csv(
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_trail_points_persistent_from_entries.pine"
        ),
        include_str!(
            "../../../../tests/fixtures/runtime/strategy_pyramiding_exit_omitted_trail_points_persistent_from_entries_bars.csv"
        ),
    )
    .expect("strategy omitted trail-points persistent fixture should run");

    assert_snapshot(
        "runtime_strategy_pyramiding_exit_omitted_trail_points_persistent_from_entries.json",
        &output,
    );
}

const REQUEST_HOST_SOURCE: &str =
    include_str!("../../../../tests/fixtures/request/request_security_host.pine");
const REQUEST_HOST_CHART_CSV: &str =
    include_str!("../../../../tests/fixtures/request/chart_1m.csv");
const REQUEST_HOST_BARS_JSON: &str = r#"{
  "NYSE:IBM:1": [
    {"time":0,"open":10,"high":11,"low":9,"close":20,"volume":100},
    {"time":60000,"open":11,"high":12,"low":10,"close":21,"volume":100},
    {"time":240000,"open":12,"high":13,"low":11,"close":22,"volume":100},
    {"time":300000,"open":13,"high":14,"low":12,"close":23,"volume":100},
    {"time":540000,"open":14,"high":15,"low":13,"close":24,"volume":100}
  ],
  "NYSE:IBM:5": [
    {"time":0,"open":90,"high":110,"low":80,"close":100,"volume":1000},
    {"time":300000,"open":190,"high":210,"low":180,"close":200,"volume":1000}
  ]
}"#;
const REQUEST_HOST_BARS_MISSING_HIGHER_JSON: &str = r#"{
  "NYSE:IBM:1": [
    {"time":0,"open":10,"high":11,"low":9,"close":20,"volume":100},
    {"time":60000,"open":11,"high":12,"low":10,"close":21,"volume":100},
    {"time":240000,"open":12,"high":13,"low":11,"close":22,"volume":100},
    {"time":300000,"open":13,"high":14,"low":12,"close":23,"volume":100},
    {"time":540000,"open":14,"high":15,"low":13,"close":24,"volume":100}
  ]
}"#;

#[test]
fn request_host_data_runs_through_direct_wasm_api() {
    let output = run_script_csv_with_request_bars(
        REQUEST_HOST_SOURCE,
        REQUEST_HOST_CHART_CSV,
        REQUEST_HOST_BARS_JSON,
    )
    .expect("request fixture should run through direct WASM API");
    let parsed: serde_json::Value = serde_json::from_str(&output).expect("strict JSON output");

    assert_eq!(
        parsed["schemaVersion"],
        serde_json::json!(PUBLIC_RUNTIME_SCHEMA_VERSION)
    );
    assert_eq!(
        parsed["plots"][0]["values"],
        serde_json::json!([30, 32, 34, 36, 38])
    );
    assert_eq!(
        parsed["plots"][1]["values"],
        serde_json::json!([null, null, 100, 100, 200])
    );
    assert_eq!(
        parsed["plots"][2]["values"],
        serde_json::json!([10, 10, 10, 10, 10])
    );
    assert_eq!(
        parsed["plots"][3]["values"],
        serde_json::json!([34, 35, 36, 37, 38])
    );
    assert_eq!(
        parsed["plots"][4]["values"],
        serde_json::json!([null, 41, 43, 45, 47])
    );
    assert_eq!(
        parsed["plots"][5]["values"],
        serde_json::json!([20.01, 21.01, 22.01, 23.01, 24.01])
    );
    assert_eq!(
        parsed["plots"][6]["values"],
        serde_json::json!([null, 100, 100, 100, 100])
    );
    assert_eq!(
        parsed["plots"][7]["values"],
        serde_json::json!([2, 10, 10, 10, 10])
    );
    assert_eq!(
        parsed["plots"][8]["values"],
        serde_json::json!([null, 10, 10, 10, 10])
    );
    assert_eq!(
        parsed["plots"][9]["values"],
        serde_json::json!([
            2,
            4.666666666666667,
            6.4444444444444455,
            7.629629629629631,
            8.419753086419753
        ])
    );
    assert_eq!(
        parsed["plots"][10]["values"],
        serde_json::json!([null, null, 13, 14, 15])
    );
    assert_eq!(
        parsed["plots"][11]["values"],
        serde_json::json!([null, null, 9, 10, 11])
    );
    assert_eq!(
        parsed["plots"][12]["values"],
        serde_json::json!([null, 1, 1, 1, 1])
    );
    assert_eq!(
        parsed["plots"][13]["values"],
        serde_json::json!([null, null, 2, 2, 2])
    );
    assert_eq!(
        parsed["plots"][14]["values"],
        serde_json::json!([null, null, 10, 9.523809523809524, 9.090909090909092])
    );
    assert_eq!(
        parsed["plots"][15]["values"],
        serde_json::json!([null, null, 2, 2, 2])
    );
    assert_eq!(
        parsed["plots"][16]["values"],
        serde_json::json!([
            null,
            null,
            0.6666666666666666,
            0.6666666666666666,
            0.6666666666666666
        ])
    );
    assert_eq!(
        parsed["plots"][17]["values"],
        serde_json::json!([0, 0, 1, 1, 1])
    );
    assert_eq!(
        parsed["plots"][18]["values"],
        serde_json::json!([0, 0, 0, 0, 0])
    );
    assert_eq!(
        parsed["plots"][19]["values"],
        serde_json::json!([0, 1, 0, 0, 0])
    );
    assert_eq!(
        parsed["plots"][20]["values"],
        serde_json::json!([0, 1, 0, 0, 0])
    );
    assert_eq!(
        parsed["plots"][21]["values"],
        serde_json::json!([0, 0, 1, 0, 0])
    );
    assert_eq!(
        parsed["plots"][22]["values"],
        serde_json::json!([20, 41, 63, 86, 110])
    );
    assert_eq!(
        parsed["plots"][23]["values"],
        serde_json::json!([
            null,
            null,
            0.816496580927726,
            0.816496580927726,
            0.816496580927726
        ])
    );
    assert_eq!(
        parsed["plots"][24]["values"],
        serde_json::json!([null, null, 1, 1, 1])
    );
    assert_eq!(
        parsed["plots"][25]["values"],
        serde_json::json!([
            null,
            null,
            0.6666666666666666,
            0.6666666666666666,
            0.6666666666666666
        ])
    );
    assert_eq!(
        parsed["plots"][26]["values"],
        serde_json::json!([null, null, 1, 1, 1])
    );
    assert_eq!(
        parsed["plots"][27]["values"],
        serde_json::json!([
            null,
            null,
            21.333333333333332,
            22.333333333333332,
            23.333333333333332
        ])
    );
    assert_eq!(
        parsed["plots"][28]["values"],
        serde_json::json!([null, null, 21, 22, 23])
    );
    assert_eq!(
        parsed["plots"][29]["values"],
        serde_json::json!([null, null, null, 21.5, 22.5])
    );
    assert_eq!(
        parsed["plots"][30]["values"],
        serde_json::json!([null, null, null, null, 24])
    );
    assert_eq!(
        parsed["plots"][31]["values"],
        serde_json::json!([null, null, null, 22.462027683060324, 23.462027683060324])
    );
    assert_eq!(
        parsed["plots"][32]["values"],
        serde_json::json!([null, null, 22, 23, 24])
    );
    assert_eq!(
        parsed["plots"][33]["values"],
        serde_json::json!([
            null,
            null,
            0.15552315827194782,
            0.1484539238050411,
            0.14199940537873496
        ])
    );
    assert_eq!(
        parsed["plots"][34]["values"],
        serde_json::json!([
            null,
            null,
            0.9999999999999858,
            1.0000000000000284,
            1.0000000000000284
        ])
    );
    assert_eq!(
        parsed["plots"][35]["values"],
        serde_json::json!([
            null,
            null,
            0.6666666666666572,
            0.6666666666666856,
            0.6666666666666856
        ])
    );
    assert_eq!(
        parsed["plots"][36]["values"],
        serde_json::json!([null, null, 21, 22, 23])
    );
    assert_eq!(
        parsed["plots"][37]["values"],
        serde_json::json!([null, null, 20, 21, 22])
    );
    assert_eq!(
        parsed["plots"][38]["values"],
        serde_json::json!([null, null, 21, 22, 23])
    );
    assert_eq!(
        parsed["plots"][39]["values"],
        serde_json::json!([null, null, 21, 22, 23])
    );
    assert_eq!(
        parsed["plots"][40]["values"],
        serde_json::json!([null, null, 100, 100, 100])
    );
    assert_eq!(
        parsed["plots"][41]["values"],
        serde_json::json!([
            20,
            20.333333333333332,
            20.88888888888889,
            21.59259259259259,
            22.395061728395063
        ])
    );
    assert_eq!(
        parsed["plots"][42]["values"],
        serde_json::json!([20, 20.75, 21.75, 22.8125, 23.875])
    );
    assert_eq!(
        parsed["plots"][43]["values"],
        serde_json::json!([20, 20.875, 21.9375, 23, 24.03125])
    );
    assert_eq!(
        parsed["plots"][44]["values"],
        serde_json::json!([null, 1, 1, 1, 1])
    );
    assert_eq!(
        parsed["plots"][45]["values"],
        serde_json::json!([null, null, null, 100, 100])
    );
    assert_eq!(
        parsed["plots"][46]["values"],
        serde_json::json!([null, null, 100, 100, 100])
    );
    assert_eq!(
        parsed["plots"][47]["values"],
        serde_json::json!([null, null, 325, 325, 325])
    );
    assert_eq!(
        parsed["plots"][48]["values"],
        serde_json::json!([null, null, 225, 225, 225])
    );
    assert_eq!(
        parsed["plots"][49]["values"],
        serde_json::json!([null, 9, 9, 9.16, 9.4504])
    );
    assert_eq!(
        parsed["plots"][50]["values"],
        serde_json::json!([null, null, 100.0, 100.0, 100.0])
    );
    assert_eq!(
        parsed["plots"][51]["values"],
        serde_json::json!([
            null,
            null,
            -1.968253968253968,
            -1.9696969696969695,
            -1.9710144927536233
        ])
    );
    assert_eq!(
        parsed["plots"][52]["values"],
        serde_json::json!([5, 5, 5, 5, 5])
    );
    assert_eq!(
        parsed["plots"][53]["values"],
        serde_json::json!([null, null, null, null, null])
    );
    assert_eq!(
        parsed["plots"][54]["values"],
        serde_json::json!([20, 21, 22, 23, 24])
    );
    assert_eq!(
        parsed["plots"][55]["values"],
        serde_json::json!([10, 10, 10, 10, 10])
    );
    assert_eq!(
        parsed["plots"][56]["values"],
        serde_json::json!([
            0.4,
            1.170731707317073,
            1.5058823529411764,
            1.6271186440677967,
            1.6476964769647696
        ])
    );
    assert_eq!(
        parsed["plots"][57]["values"],
        serde_json::json!([null, null, null, null, null])
    );
    assert_eq!(
        parsed["plots"][58]["values"],
        serde_json::json!([null, null, null, null, null])
    );
    assert_eq!(
        parsed["plots"][59]["values"],
        serde_json::json!([0, 0, 0, 0, 0])
    );
    assert_eq!(
        parsed["plots"][60]["values"],
        serde_json::json!([null, null, 0, 0, 0])
    );
    assert_eq!(
        parsed["plots"][61]["values"],
        serde_json::json!([null, null, 2, 2, 2])
    );
    assert_eq!(
        parsed["plots"][62]["values"],
        serde_json::json!([null, null, null, 22, 23])
    );
    assert_eq!(
        parsed["plots"][63]["values"],
        serde_json::json!([20, 20.5, 21, 21.5, 22])
    );
    assert_eq!(
        parsed["plots"][64]["values"],
        serde_json::json!([1000, 2000, 3000, 4000, 5000])
    );
    assert_eq!(
        parsed["plots"][65]["values"],
        serde_json::json!([0.1, 0.1, 0.1, 0.1, 0.1])
    );
    assert_eq!(
        parsed["plots"][66]["values"],
        serde_json::json!([1, 1, 1, 1, 1])
    );
    assert_eq!(
        parsed["plots"][67]["values"],
        serde_json::json!([null, 100, 200, 300, 400])
    );
    assert_eq!(
        parsed["plots"][68]["values"],
        serde_json::json!([1, 1, 1, 1, 1])
    );
    assert_eq!(
        parsed["plots"][69]["values"],
        serde_json::json!([
            null,
            5,
            9.761904761904765,
            14.30735930735931,
            18.65518539431583
        ])
    );
    assert_eq!(
        parsed["plots"][70]["values"],
        serde_json::json!([500, 500, 500, 500, 500])
    );
    assert_eq!(
        parsed["plots"][71]["values"],
        serde_json::json!([
            0,
            0.16666666666666785,
            0.30555555555555713,
            0.39351851851851904,
            0.4436728395061742
        ])
    );
    assert_eq!(
        parsed["plots"][72]["values"],
        serde_json::json!([
            0,
            0.1111111111111119,
            0.2407407407407421,
            0.3425925925925934,
            0.40997942386831393
        ])
    );
    assert_eq!(
        parsed["plots"][73]["values"],
        serde_json::json!([
            0,
            0.055555555555555955,
            0.06481481481481507,
            0.05092592592592565,
            0.03369341563786027
        ])
    );
    assert_eq!(
        parsed["plots"][74]["values"],
        serde_json::json!([null, null, 21, 22, 23])
    );
    assert_eq!(
        parsed["plots"][75]["values"],
        serde_json::json!([
            null,
            null,
            22.632993161855453,
            23.632993161855453,
            24.632993161855453
        ])
    );
    assert_eq!(
        parsed["plots"][76]["values"],
        serde_json::json!([
            null,
            null,
            19.367006838144547,
            20.367006838144547,
            21.367006838144547
        ])
    );
    assert_eq!(
        parsed["plots"][77]["values"],
        serde_json::json!([20, 20.5, 21.25, 22.125, 23.0625])
    );
    assert_eq!(
        parsed["plots"][78]["values"],
        serde_json::json!([24, 32.5, 37.25, 40.125, 42.0625])
    );
    assert_eq!(
        parsed["plots"][79]["values"],
        serde_json::json!([16, 8.5, 5.25, 4.125, 4.0625])
    );
    assert_eq!(
        parsed["plots"][80]["values"],
        serde_json::json!([14, 6, 6, 6, 6])
    );
    assert_eq!(
        parsed["plots"][81]["values"],
        serde_json::json!([1, -1, -1, -1, -1])
    );
    assert_eq!(
        parsed["plots"][82]["values"],
        serde_json::json!([
            0,
            7.1428571428571415,
            8.620689655172411,
            9.223300970873783,
            9.530791788856304
        ])
    );
    assert_eq!(
        parsed["plots"][83]["values"],
        serde_json::json!([0, 0, 0, 0, 0])
    );
    assert_eq!(
        parsed["plots"][84]["values"],
        serde_json::json!([0, 50, 75, 87.5, 93.75])
    );
    assert_eq!(
        parsed["plots"][85]["values"],
        serde_json::json!([20, 20.5, 21, 21.5, 22])
    );
    assert_eq!(
        parsed["plots"][86]["values"],
        serde_json::json!([
            20,
            21.5,
            22.63299316185547,
            23.73606797749979,
            24.82842712474619
        ])
    );
    assert_eq!(
        parsed["plots"][87]["values"],
        serde_json::json!([
            20,
            19.5,
            19.36700683814453,
            19.26393202250021,
            19.17157287525381
        ])
    );
    assert_eq!(
        parsed["plots"][88]["values"],
        serde_json::json!([20, 21, 22, 23, 24])
    );
    assert_eq!(
        parsed["plots"][89]["values"],
        serde_json::json!([21, 22, 23, 24, 25])
    );
    assert_eq!(
        parsed["plots"][90]["values"],
        serde_json::json!([1, 1, 1, 1, 1])
    );
    assert_eq!(
        parsed["plots"][91]["values"],
        serde_json::json!([null, null, 100, 100, 200])
    );
    assert_eq!(
        parsed["plots"][92]["values"],
        serde_json::json!([null, null, 101, 101, 201])
    );
    assert_eq!(
        parsed["plots"][93]["values"],
        serde_json::json!([null, null, 1, 1, 1])
    );
    assert_eq!(
        parsed["plots"][94]["values"],
        serde_json::json!([null, null, 0, 0, 16.666666666666657])
    );
    assert_eq!(
        parsed["plots"][95]["values"],
        serde_json::json!([null, null, 0, 0, 11.111111111111104])
    );
    assert_eq!(
        parsed["plots"][96]["values"],
        serde_json::json!([null, null, 0, 0, 5.555555555555554])
    );
    assert_eq!(
        parsed["plots"][97]["values"],
        serde_json::json!([null, null, null, null, 150])
    );
    assert_eq!(
        parsed["plots"][98]["values"],
        serde_json::json!([null, null, null, null, 250])
    );
    assert_eq!(
        parsed["plots"][99]["values"],
        serde_json::json!([null, null, null, null, 50])
    );
    assert_eq!(
        parsed["plots"][100]["values"],
        serde_json::json!([null, null, 100, 100, 166.66666666666666])
    );
    assert_eq!(
        parsed["plots"][101]["values"],
        serde_json::json!([null, null, 160, 160, 333.3333333333333])
    );
    assert_eq!(
        parsed["plots"][102]["values"],
        serde_json::json!([null, null, 40, 40, 0])
    );
    assert_eq!(
        parsed["plots"][103]["values"],
        serde_json::json!([null, null, 100, 100, 150])
    );
    assert_eq!(
        parsed["plots"][104]["values"],
        serde_json::json!([null, null, 100, 100, 250])
    );
    assert_eq!(
        parsed["plots"][105]["values"],
        serde_json::json!([null, null, 100, 100, 50])
    );
    assert_eq!(
        parsed["plots"][106]["values"],
        serde_json::json!([null, null, 155, 155, 81.66666666666667])
    );
    assert_eq!(
        parsed["plots"][107]["values"],
        serde_json::json!([null, null, 1, 1, -1])
    );
    assert_eq!(
        parsed["plots"][108]["values"],
        serde_json::json!([null, null, 0, 0, 71.42857142857143])
    );
    assert_eq!(
        parsed["plots"][109]["values"],
        serde_json::json!([null, null, 0, 0, 0])
    );
    assert_eq!(
        parsed["plots"][110]["values"],
        serde_json::json!([null, null, 0, 0, 50])
    );
    assert_eq!(
        parsed["plots"][111]["values"],
        serde_json::json!([null, 20, 21, 22, 23])
    );
    assert_eq!(
        parsed["plots"][112]["values"],
        serde_json::json!([10, 20, 21, 22, 23])
    );
    assert_eq!(
        parsed["plots"][113]["values"],
        serde_json::json!([0, 1, 1, 1, 1])
    );
    assert_eq!(
        parsed["plots"][114]["values"],
        serde_json::json!([null, null, null, null, 100])
    );
    assert_eq!(
        parsed["plots"][115]["values"],
        serde_json::json!([null, null, 90, 90, 100])
    );
    assert_eq!(
        parsed["plots"][116]["values"],
        serde_json::json!([null, null, 0, 0, 100])
    );
    assert_eq!(
        parsed["plots"][117]["values"],
        serde_json::json!([20, 21, 22, 23, 24])
    );
    assert_eq!(
        parsed["plots"][118]["values"],
        serde_json::json!([10, 11, 12, 13, 14])
    );
    assert_eq!(
        parsed["plots"][119]["values"],
        serde_json::json!([10, 10, 10, 10, 10])
    );
    assert_eq!(
        parsed["plots"][120]["values"],
        serde_json::json!([null, null, 100, 100, 200])
    );
    assert_eq!(
        parsed["plots"][121]["values"],
        serde_json::json!([null, null, 90, 90, 190])
    );
    assert_eq!(
        parsed["plots"][122]["values"],
        serde_json::json!([null, null, 10, 10, 10])
    );
    assert_eq!(
        parsed["plots"][125]["values"],
        serde_json::json!([null, 20.5, 21.5, 22.5, 23.5])
    );
    assert_eq!(
        parsed["plots"][126]["values"],
        serde_json::json!([null, 1, 1, 1, 1])
    );
    assert_eq!(
        parsed["plots"][127]["values"],
        serde_json::json!([20, 41, 63, 86, 110])
    );
    assert_eq!(
        parsed["plots"][128]["values"],
        serde_json::json!([null, null, null, null, 150])
    );
    assert_eq!(
        parsed["plots"][129]["values"],
        serde_json::json!([null, null, null, null, 100])
    );
    assert_eq!(
        parsed["plots"][130]["values"],
        serde_json::json!([null, null, 100, 100, 300])
    );
    assert_eq!(
        parsed["plots"][131]["values"],
        serde_json::json!([0, 1, 0, 0, 0])
    );
    assert_eq!(
        parsed["plots"][132]["values"],
        serde_json::json!([0, 1, 0, 0, 0])
    );
    assert_eq!(
        parsed["plots"][133]["values"],
        serde_json::json!([0, 0, 1, 0, 0])
    );
    assert_eq!(
        parsed["plots"][134]["values"],
        serde_json::json!([null, null, 0, 0, 1])
    );
    assert_eq!(
        parsed["plots"][135]["values"],
        serde_json::json!([null, null, 0, 0, 1])
    );
    assert_eq!(
        parsed["plots"][136]["values"],
        serde_json::json!([null, null, 0, 0, 1])
    );
    assert_eq!(
        parsed["plots"][137]["values"],
        serde_json::json!([0, 0, 1, 1, 1])
    );
    assert_eq!(
        parsed["plots"][138]["values"],
        serde_json::json!([0, 0, 1, 1, 1])
    );
    assert_eq!(
        parsed["plots"][139]["values"],
        serde_json::json!([0, 0, 0, 0, 0])
    );
    assert_eq!(
        parsed["plots"][140]["values"],
        serde_json::json!([null, null, 0, 0, 1])
    );
    assert_eq!(
        parsed["plots"][141]["values"],
        serde_json::json!([null, null, 0, 0, 1])
    );
    assert_eq!(
        parsed["plots"][142]["values"],
        serde_json::json!([null, null, 0, 0, 0])
    );
    assert_eq!(
        parsed["plots"][143]["values"],
        serde_json::json!([0, 0, 0, 0, 0])
    );
    assert_eq!(
        parsed["plots"][144]["values"],
        serde_json::json!([null, null, null, 22, 23])
    );
    assert_eq!(
        parsed["plots"][145]["values"],
        serde_json::json!([null, null, 0, 0, 0])
    );
    assert_eq!(
        parsed["plots"][146]["values"],
        serde_json::json!([null, null, null, null, 100])
    );
    assert_eq!(
        parsed["plots"][147]["values"],
        serde_json::json!([null, null, 0, 0, 0])
    );
    assert_eq!(
        parsed["plots"][148]["values"],
        serde_json::json!([null, null, 2, 2, 2])
    );
    assert_eq!(
        parsed["plots"][149]["values"],
        serde_json::json!([null, null, null, null, 0])
    );
    assert_eq!(
        parsed["plots"][150]["values"],
        serde_json::json!([null, null, null, null, 1])
    );
    assert_eq!(
        parsed["plots"][151]["values"],
        serde_json::json!([null, null, null, 0, null])
    );
    assert_eq!(
        parsed["plots"][152]["values"],
        serde_json::json!([null, null, null, 0, null])
    );
    assert_eq!(
        parsed["plots"][153]["values"],
        serde_json::json!([null, null, null, null, 200])
    );
    assert_eq!(
        parsed["plots"][154]["values"],
        serde_json::json!([null, null, null, null, 100])
    );
    assert_eq!(
        parsed["plots"][155]["values"],
        serde_json::json!([
            null,
            null,
            0.9999999999999858,
            1.0000000000000284,
            1.0000000000000284
        ])
    );
    assert_eq!(
        parsed["plots"][156]["values"],
        serde_json::json!([
            null,
            null,
            0.6666666666666572,
            0.6666666666666856,
            0.6666666666666856
        ])
    );
    assert_eq!(
        parsed["plots"][157]["values"],
        serde_json::json!([null, null, null, null, 1])
    );
    assert_eq!(
        parsed["plots"][158]["values"],
        serde_json::json!([null, null, null, null, 2500])
    );
    assert_eq!(
        parsed["plots"][159]["values"],
        serde_json::json!([null, null, 21, 22, 23])
    );
    assert_eq!(
        parsed["plots"][160]["values"],
        serde_json::json!([null, null, 20, 21, 22])
    );
    assert_eq!(
        parsed["plots"][161]["values"],
        serde_json::json!([null, null, 21, 22, 23])
    );
    assert_eq!(
        parsed["plots"][162]["values"],
        serde_json::json!([null, null, 21, 22, 23])
    );
    assert_eq!(
        parsed["plots"][163]["values"],
        serde_json::json!([null, null, 100, 100, 100])
    );
    assert_eq!(
        parsed["plots"][164]["values"],
        serde_json::json!([
            null,
            null,
            33.33333333333333,
            33.33333333333333,
            33.33333333333333
        ])
    );
    assert_eq!(
        parsed["plots"][165]["values"],
        serde_json::json!([null, null, null, null, 150])
    );
    assert_eq!(
        parsed["plots"][166]["values"],
        serde_json::json!([null, null, null, null, 100])
    );
    assert_eq!(
        parsed["plots"][167]["values"],
        serde_json::json!([null, null, null, null, 100])
    );
    assert_eq!(
        parsed["plots"][168]["values"],
        serde_json::json!([null, null, null, null, 150])
    );
    assert_eq!(
        parsed["plots"][169]["values"],
        serde_json::json!([null, null, null, null, 100])
    );
    assert_eq!(
        parsed["plots"][170]["values"],
        serde_json::json!([null, null, null, null, 50])
    );
    assert_eq!(
        parsed["plots"][171]["values"],
        serde_json::json!([
            null,
            null,
            0.816496580927726,
            0.816496580927726,
            0.816496580927726
        ])
    );
    assert_eq!(
        parsed["plots"][172]["values"],
        serde_json::json!([
            null,
            null,
            0.6666666666666666,
            0.6666666666666666,
            0.6666666666666666
        ])
    );
    assert_eq!(
        parsed["plots"][173]["values"],
        serde_json::json!([null, null, null, null, 50])
    );
    assert_eq!(
        parsed["plots"][174]["values"],
        serde_json::json!([null, null, null, null, 2500])
    );
    assert_eq!(
        parsed["plots"][175]["values"],
        serde_json::json!([
            null,
            null,
            21.333333333333332,
            22.333333333333332,
            23.333333333333332
        ])
    );
    assert_eq!(
        parsed["plots"][176]["values"],
        serde_json::json!([null, null, 21, 22, 23])
    );
    assert_eq!(
        parsed["plots"][177]["values"],
        serde_json::json!([null, null, null, null, 166.66666666666666])
    );
    assert_eq!(
        parsed["plots"][178]["values"],
        serde_json::json!([null, null, null, null, 150])
    );
    assert_eq!(
        parsed["plots"][179]["values"],
        serde_json::json!([null, null, null, 21.5, 22.5])
    );
    assert_eq!(
        parsed["plots"][180]["values"],
        serde_json::json!([null, null, null, null, 24])
    );
    assert_eq!(
        parsed["plots"][181]["values"],
        serde_json::json!([null, null, null, 22.462027683060324, 23.462027683060324])
    );
    assert_eq!(
        parsed["plots"][182]["values"],
        serde_json::json!([null, null, 22, 23, 24])
    );
    assert_eq!(
        parsed["plots"][183]["values"],
        serde_json::json!([
            20,
            20.333333333333332,
            20.88888888888889,
            21.59259259259259,
            22.395061728395063
        ])
    );
    assert_eq!(
        parsed["plots"][184]["values"],
        serde_json::json!([20, 20.75, 21.75, 22.8125, 23.875])
    );
    assert_eq!(
        parsed["plots"][185]["values"],
        serde_json::json!([20, 20.875, 21.9375, 23, 24.03125])
    );
    assert_eq!(
        parsed["plots"][186]["values"],
        serde_json::json!([null, 1, 1, 1, 1])
    );
    assert_eq!(
        parsed["plots"][187]["values"],
        serde_json::json!([null, null, null, 100, 100])
    );
    assert_eq!(
        parsed["plots"][188]["values"],
        serde_json::json!([null, null, 100, 100, 100])
    );
    assert_eq!(
        parsed["plots"][189]["values"],
        serde_json::json!([null, null, 325, 325, 325])
    );
    assert_eq!(
        parsed["plots"][190]["values"],
        serde_json::json!([null, null, 225, 225, 225])
    );
    assert_eq!(
        parsed["plots"][191]["values"],
        serde_json::json!([null, 9, 9, 9.16, 9.4504])
    );
    assert_eq!(
        parsed["plots"][192]["values"],
        serde_json::json!([null, null, 100.0, 100.0, 100.0])
    );
    assert_eq!(
        parsed["plots"][193]["values"],
        serde_json::json!([
            null,
            null,
            -1.968253968253968,
            -1.9696969696969695,
            -1.9710144927536233
        ])
    );
    assert_eq!(
        parsed["plots"][194]["values"],
        serde_json::json!([5, 5, 5, 5, 5])
    );
    assert_eq!(
        parsed["plots"][195]["values"],
        serde_json::json!([20, 21, 22, 23, 24])
    );
    assert_eq!(
        parsed["plots"][196]["values"],
        serde_json::json!([10, 10, 10, 10, 10])
    );
    assert_eq!(
        parsed["plots"][197]["values"],
        serde_json::json!([
            0.4,
            1.170731707317073,
            1.5058823529411764,
            1.6271186440677967,
            1.6476964769647695
        ])
    );
    assert_eq!(
        parsed["plots"][198]["values"],
        serde_json::json!([20, 20.5, 21, 21.5, 22])
    );
    assert_eq!(
        parsed["plots"][199]["values"],
        serde_json::json!([1000, 2000, 3000, 4000, 5000])
    );
    assert_eq!(
        parsed["plots"][200]["values"],
        serde_json::json!([0.1, 0.1, 0.1, 0.1, 0.1])
    );
    assert_eq!(
        parsed["plots"][201]["values"],
        serde_json::json!([1, 1, 1, 1, 1])
    );
    assert_eq!(
        parsed["plots"][202]["values"],
        serde_json::json!([null, 100, 200, 300, 400])
    );
    assert_eq!(
        parsed["plots"][203]["values"],
        serde_json::json!([1, 1, 1, 1, 1])
    );
    assert_eq!(
        parsed["plots"][204]["values"],
        serde_json::json!([
            null,
            5,
            9.761904761904765,
            14.30735930735931,
            18.65518539431583
        ])
    );
    assert_eq!(
        parsed["plots"][205]["values"],
        serde_json::json!([500, 500, 500, 500, 500])
    );
    assert_eq!(
        parsed["plots"][206]["values"],
        serde_json::json!([null, null, null, null, null])
    );
    assert_eq!(
        parsed["plots"][207]["values"],
        serde_json::json!([null, null, 100, 100, 200])
    );
    assert_eq!(
        parsed["plots"][208]["values"],
        serde_json::json!([null, null, 90, 90, 90])
    );
    assert_eq!(
        parsed["plots"][209]["values"],
        serde_json::json!([
            null,
            null,
            333.3333333333333,
            333.3333333333333,
            666.6666666666666
        ])
    );
    assert_eq!(
        parsed["plots"][210]["values"],
        serde_json::json!([
            null,
            null,
            0.0003333333333333333,
            0.0003333333333333333,
            0.0003333333333333333
        ])
    );
    assert_eq!(
        parsed["plots"][211]["values"],
        serde_json::json!([null, null, 1, 1, 1])
    );
    assert_eq!(
        parsed["plots"][212]["values"],
        serde_json::json!([null, null, null, null, 1000])
    );
    assert_eq!(
        parsed["plots"][213]["values"],
        serde_json::json!([null, null, 1, 1, 1])
    );
    assert_eq!(
        parsed["plots"][214]["values"],
        serde_json::json!([null, null, null, null, 1000])
    );
    assert_eq!(
        parsed["plots"][215]["values"],
        serde_json::json!([
            null,
            null,
            333.3333333333333,
            333.3333333333333,
            333.3333333333333
        ])
    );
    assert_eq!(
        parsed["plots"][216]["values"],
        serde_json::json!([null, null, null, null, null])
    );
    assert_eq!(
        parsed["plots"][217]["values"],
        serde_json::json!([null, null, null, null, null])
    );
    assert_eq!(
        parsed["plots"][218]["values"],
        serde_json::json!([null, null, null, null, null])
    );
    assert_eq!(
        parsed["plots"][219]["values"],
        serde_json::json!([null, null, null, null, null])
    );
    assert_eq!(
        parsed["plots"][220]["values"],
        serde_json::json!([null, null, null, null, null])
    );
    assert_eq!(
        parsed["plots"][221]["values"],
        serde_json::json!([null, null, 100, 100, 133.33333333333334])
    );
    assert_eq!(
        parsed["plots"][222]["values"],
        serde_json::json!([null, null, 100, 100, 175])
    );
    assert_eq!(
        parsed["plots"][223]["values"],
        serde_json::json!([null, null, 100, 100, 187.5])
    );
    assert_eq!(
        parsed["plots"][224]["values"],
        serde_json::json!([null, null, null, null, 1])
    );
    assert_eq!(
        parsed["plots"][225]["values"],
        serde_json::json!([null, null, null, null, 100])
    );
    assert_eq!(
        parsed["plots"][226]["values"],
        serde_json::json!([null, null, null, null, 100])
    );
    assert_eq!(
        parsed["plots"][227]["values"],
        serde_json::json!([null, null, null, null, 92.3076923076923])
    );
    assert_eq!(
        parsed["plots"][228]["values"],
        serde_json::json!([null, null, null, null, -7.6923076923076925])
    );
    assert_eq!(
        parsed["plots"][229]["values"],
        serde_json::json!([null, null, null, null, 80])
    );
    assert_eq!(
        parsed["plots"][230]["values"],
        serde_json::json!([null, null, null, null, 66.66666666666667])
    );
    assert_eq!(
        parsed["plots"][231]["values"],
        serde_json::json!([null, null, null, null, -1.3333333333333333])
    );
    assert_eq!(
        parsed["plots"][232]["values"],
        serde_json::json!([
            null,
            null,
            0.3333333333333333,
            0.3333333333333333,
            0.3333333333333333
        ])
    );
    assert_eq!(
        parsed["plots"][233]["values"],
        serde_json::json!([null, null, 1.2, 1.2, 2])
    );
    assert_eq!(
        parsed["plots"][234]["values"],
        serde_json::json!([null, null, 100, 100, 150])
    );
    assert_eq!(
        parsed["plots"][235]["values"],
        serde_json::json!([null, null, 30, 30, 110])
    );
    assert_eq!(
        parsed["plots"][236]["values"],
        serde_json::json!([null, null, 30, 30, 70])
    );
    assert_eq!(
        parsed["plots"][237]["values"],
        serde_json::json!([null, null, null, null, 210])
    );
    assert_eq!(
        parsed["plots"][238]["values"],
        serde_json::json!([null, null, null, null, 80])
    );
    assert_eq!(
        parsed["plots"][239]["values"],
        serde_json::json!([null, null, null, null, 100])
    );
    assert_eq!(
        parsed["plots"][240]["values"],
        serde_json::json!([null, null, null, null, 100])
    );
    assert_eq!(
        parsed["plots"][241]["values"],
        serde_json::json!([null, null, null, null, 100])
    );
    assert_eq!(
        parsed["plots"][242]["values"],
        serde_json::json!([null, null, null, null, 50])
    );
    assert_eq!(
        parsed["plots"][243]["values"],
        serde_json::json!([null, null, 100, 100, 166.66666666666666])
    );
    assert_eq!(
        parsed["plots"][244]["values"],
        serde_json::json!([null, null, null, null, 100])
    );
    assert_eq!(
        parsed["plots"][245]["values"],
        serde_json::json!([null, null, null, null, 1.3333333333333333])
    );
    assert_eq!(
        parsed["plots"][246]["values"],
        serde_json::json!([null, null, null, null, 210])
    );
    assert_eq!(
        parsed["plots"][247]["values"],
        serde_json::json!([null, null, null, null, 80])
    );
    assert_eq!(
        parsed["plots"][248]["values"],
        serde_json::json!([null, null, null, null, 0])
    );
    assert_eq!(
        parsed["plots"][249]["values"],
        serde_json::json!([null, null, null, null, 1])
    );
    assert_eq!(
        parsed["plots"][123]["values"],
        serde_json::json!([null, null, null, null, 300])
    );
    assert_eq!(
        parsed["plots"][124]["values"],
        serde_json::json!([null, null, 100.01, 100.01, 200.01])
    );
    assert_eq!(
        parsed["plots"][250]["values"],
        serde_json::json!([null, null, 33, 33, 66])
    );
    assert_eq!(
        parsed["plots"][251]["values"],
        serde_json::json!([null, null, 2, 2, 3])
    );
    assert_eq!(
        parsed["plots"][252]["values"],
        serde_json::json!([null, null, 33.33, 33.33, 66.67])
    );
    assert_eq!(
        parsed["plots"][253]["values"],
        serde_json::json!([null, null, 10, 10, 14.142135623730953])
    );
    assert_eq!(
        parsed["plots"][254]["values"],
        serde_json::json!([
            null,
            null,
            4.641588833612779,
            4.641588833612779,
            5.848035476425732
        ])
    );
    assert_eq!(
        parsed["plots"][255]["values"],
        serde_json::json!([null, null, 2, 2, 2.3010299956639813])
    );
    assert_eq!(
        parsed["plots"][256]["values"],
        serde_json::json!([
            null,
            null,
            0.8414709848078965,
            0.8414709848078965,
            0.9092974268256816
        ])
    );
    assert_eq!(
        parsed["plots"][257]["values"],
        serde_json::json!([
            null,
            null,
            0.6216099682706644,
            0.6216099682706644,
            -0.32328956686350335
        ])
    );
    assert_eq!(
        parsed["plots"][258]["values"],
        serde_json::json!([
            null,
            null,
            0.10033467208545056,
            0.10033467208545056,
            0.10033467208545056
        ])
    );
    assert_eq!(
        parsed["plots"][259]["values"],
        serde_json::json!([null, null, 1, 1, 4])
    );
    assert_eq!(
        parsed["plots"][260]["values"],
        serde_json::json!([
            null,
            null,
            1.3453624047073711,
            1.3453624047073711,
            2.7586228448267445
        ])
    );
    assert_eq!(
        parsed["plots"][261]["values"],
        serde_json::json!([
            null,
            null,
            4.605170185988092,
            4.605170185988092,
            5.298317366548036
        ])
    );

    let assert_plot_values_close = |plot_index: usize, expected: &[Option<f64>]| {
        let values = parsed["plots"][plot_index]["values"]
            .as_array()
            .expect("plot values should be an array");
        assert_eq!(values.len(), expected.len());
        for (actual, expected) in values.iter().zip(expected) {
            match expected {
                Some(expected) => {
                    let actual = actual.as_f64().expect("plot value should be numeric");
                    assert!(
                        (actual - expected).abs() < 1e-12,
                        "plot {plot_index} value {actual} != {expected}"
                    );
                }
                None => assert!(actual.is_null(), "plot {plot_index} value should be null"),
            }
        }
    };
    assert_plot_values_close(
        262,
        &[
            None,
            None,
            Some(1.0_f64.exp()),
            Some(1.0_f64.exp()),
            Some(2.0_f64.exp()),
        ],
    );
    assert_plot_values_close(
        263,
        &[
            None,
            None,
            Some((0.5_f64).acos()),
            Some((0.5_f64).acos()),
            Some(1.0_f64.acos()),
        ],
    );
    assert_plot_values_close(
        264,
        &[
            None,
            None,
            Some((0.5_f64).asin()),
            Some((0.5_f64).asin()),
            Some(1.0_f64.asin()),
        ],
    );
    assert_plot_values_close(
        265,
        &[
            None,
            None,
            Some(1.0_f64.atan()),
            Some(1.0_f64.atan()),
            Some(2.0_f64.atan()),
        ],
    );
    assert_eq!(
        parsed["plots"][266]["values"],
        serde_json::json!([null, null, 95, 95, 195])
    );
    assert_eq!(
        parsed["plots"][267]["values"],
        serde_json::json!([null, null, 33, 33, 66])
    );
    assert_eq!(
        parsed["plots"][268]["values"],
        serde_json::json!([null, null, 1, 1, 1])
    );
    assert_plot_values_close(
        269,
        &[
            None,
            None,
            Some(1.0_f64.to_degrees()),
            Some(1.0_f64.to_degrees()),
            Some(2.0_f64.to_degrees()),
        ],
    );
    assert_plot_values_close(
        270,
        &[
            None,
            None,
            Some(9.0_f64.to_radians()),
            Some(9.0_f64.to_radians()),
            Some(19.0_f64.to_radians()),
        ],
    );
    assert_eq!(
        parsed["plots"][271]["values"],
        serde_json::json!([6, 7, 7, 7, 8])
    );
    assert_eq!(
        parsed["plots"][272]["values"],
        serde_json::json!([2, 2, 2, 3, 3])
    );
    assert_eq!(
        parsed["plots"][273]["values"],
        serde_json::json!([2.86, 3, 314.0 / 100.0, 3.29, 3.43])
    );
    assert_plot_values_close(
        274,
        &[
            Some(20.0_f64.sqrt()),
            Some(21.0_f64.sqrt()),
            Some(22.0_f64.sqrt()),
            Some(23.0_f64.sqrt()),
            Some(24.0_f64.sqrt()),
        ],
    );
    assert_plot_values_close(
        275,
        &[
            Some(20.0_f64.cbrt()),
            Some(21.0_f64.cbrt()),
            Some(22.0_f64.cbrt()),
            Some(23.0_f64.cbrt()),
            Some(24.0_f64.cbrt()),
        ],
    );
    assert_plot_values_close(
        276,
        &[
            Some(20.0_f64.log10()),
            Some(21.0_f64.log10()),
            Some(22.0_f64.log10()),
            Some(23.0_f64.log10()),
            Some(24.0_f64.log10()),
        ],
    );
    assert_plot_values_close(
        277,
        &[
            Some(0.2_f64.sin()),
            Some(0.21_f64.sin()),
            Some(0.22_f64.sin()),
            Some(0.23_f64.sin()),
            Some(0.24_f64.sin()),
        ],
    );
    assert_plot_values_close(
        278,
        &[
            Some(0.1_f64.cos()),
            Some(0.11_f64.cos()),
            Some(0.12_f64.cos()),
            Some(0.13_f64.cos()),
            Some(0.14_f64.cos()),
        ],
    );
    assert_plot_values_close(279, &[Some(0.1_f64.tan()); 5]);
    assert_plot_values_close(
        280,
        &[
            Some(0.2_f64.powf(2.0)),
            Some(0.21_f64.powf(2.0)),
            Some(0.22_f64.powf(2.0)),
            Some(0.23_f64.powf(2.0)),
            Some(0.24_f64.powf(2.0)),
        ],
    );
    assert_plot_values_close(
        281,
        &[
            Some(0.2_f64.hypot(0.1)),
            Some(0.21_f64.hypot(0.11)),
            Some(0.22_f64.hypot(0.12)),
            Some(0.23_f64.hypot(0.13)),
            Some(0.24_f64.hypot(0.14)),
        ],
    );
    assert_plot_values_close(
        282,
        &[
            Some(20.0_f64.ln()),
            Some(21.0_f64.ln()),
            Some(22.0_f64.ln()),
            Some(23.0_f64.ln()),
            Some(24.0_f64.ln()),
        ],
    );
    assert_plot_values_close(
        283,
        &[
            Some(0.2_f64.exp()),
            Some(0.21_f64.exp()),
            Some(0.22_f64.exp()),
            Some(0.23_f64.exp()),
            Some(0.24_f64.exp()),
        ],
    );
    assert_plot_values_close(
        284,
        &[
            Some((0.1_f64).acos()),
            Some((0.105_f64).acos()),
            Some((0.11_f64).acos()),
            Some((0.115_f64).acos()),
            Some((0.12_f64).acos()),
        ],
    );
    assert_plot_values_close(
        285,
        &[
            Some((0.1_f64).asin()),
            Some((0.105_f64).asin()),
            Some((0.11_f64).asin()),
            Some((0.115_f64).asin()),
            Some((0.12_f64).asin()),
        ],
    );
    assert_plot_values_close(
        286,
        &[
            Some(0.2_f64.atan()),
            Some(0.21_f64.atan()),
            Some(0.22_f64.atan()),
            Some(0.23_f64.atan()),
            Some(0.24_f64.atan()),
        ],
    );
    assert_plot_values_close(
        287,
        &[Some(12.5), Some(13.5), Some(14.5), Some(15.5), Some(16.5)],
    );
    assert_plot_values_close(
        288,
        &[Some(6.0), Some(7.0), Some(7.0), Some(7.0), Some(8.0)],
    );
    assert_plot_values_close(289, &[Some(1.0); 5]);
    assert_plot_values_close(
        290,
        &[
            Some(0.2_f64.to_degrees()),
            Some(0.21_f64.to_degrees()),
            Some(0.22_f64.to_degrees()),
            Some(0.23_f64.to_degrees()),
            Some(0.24_f64.to_degrees()),
        ],
    );
    assert_plot_values_close(
        291,
        &[
            Some(1.0_f64.to_radians()),
            Some(1.1_f64.to_radians()),
            Some(1.2_f64.to_radians()),
            Some(1.3_f64.to_radians()),
            Some(1.4_f64.to_radians()),
        ],
    );
    assert_plot_values_close(
        292,
        &[Some(2.0), Some(10.0), Some(10.0), Some(10.0), Some(10.0)],
    );
    assert_plot_values_close(
        293,
        &[Some(2.0), Some(6.0), Some(8.0), Some(9.0), Some(9.5)],
    );
    assert_plot_values_close(294, &[None, Some(12.0), Some(13.0), Some(14.0), Some(15.0)]);
    assert_plot_values_close(295, &[None, Some(9.0), Some(10.0), Some(11.0), Some(12.0)]);
    assert_plot_values_close(296, &[None, Some(1.0), Some(1.0), Some(1.0), Some(1.0)]);
    assert_plot_values_close(
        297,
        &[
            None,
            Some(5.0),
            Some(100.0 / 21.0),
            Some(100.0 / 22.0),
            Some(100.0 / 23.0),
        ],
    );
    assert_plot_values_close(298, &[None, Some(1.0), Some(1.0), Some(1.0), Some(1.0)]);
    assert_plot_values_close(299, &[None, Some(0.5), Some(0.5), Some(0.5), Some(0.5)]);
    assert_plot_values_close(
        300,
        &[
            Some(20.0),
            Some(20.666_666_666_666_668),
            Some(21.555_555_555_555_557),
            Some(22.518_518_518_518_52),
            Some(23.506_172_839_506_174),
        ],
    );
    assert_plot_values_close(
        301,
        &[None, Some(100.0), Some(100.0), Some(100.0), Some(100.0)],
    );
    assert_plot_values_close(
        302,
        &[
            None,
            Some(0.097_560_975_609_756_1),
            Some(0.093_023_255_813_953_49),
            Some(0.088_888_888_888_888_89),
            Some(0.085_106_382_978_723_4),
        ],
    );
    assert_plot_values_close(303, &[None, Some(12.0), Some(13.0), Some(14.0), Some(15.0)]);
    assert_plot_values_close(304, &[None, Some(9.0), Some(10.0), Some(11.0), Some(12.0)]);
    assert_plot_values_close(305, &[None, Some(0.0), Some(0.0), Some(0.0), Some(0.0)]);
    assert_plot_values_close(306, &[None, Some(1.0), Some(1.0), Some(1.0), Some(1.0)]);
    assert_plot_values_close(307, &[None, Some(41.0), Some(43.0), Some(45.0), Some(47.0)]);
    assert_plot_values_close(
        308,
        &[
            Some(20.01),
            Some(21.01),
            Some(22.01),
            Some(23.01),
            Some(24.01),
        ],
    );
}

#[test]
fn request_host_data_reports_missing_request_key() {
    let message = run_script_csv_with_request_bars_internal(
        REQUEST_HOST_SOURCE,
        REQUEST_HOST_CHART_CSV,
        REQUEST_HOST_BARS_MISSING_HIGHER_JSON,
    )
    .expect_err("missing requested key should fail");

    assert!(
        message.contains("missing request data for symbol `NYSE:IBM` timeframe `5`"),
        "{message}"
    );
}

#[test]
fn run_csv_with_request_bars_matches_direct_request_api() {
    let direct_output = run_script_csv_with_request_bars(
        REQUEST_HOST_SOURCE,
        REQUEST_HOST_CHART_CSV,
        REQUEST_HOST_BARS_JSON,
    )
    .expect("direct request fixture should run");
    let program = compile_script(REQUEST_HOST_SOURCE).expect("request fixture should compile");

    let compiled_output = program
        .run_csv_with_request_bars(REQUEST_HOST_CHART_CSV, REQUEST_HOST_BARS_JSON)
        .expect("compiled request fixture should run");
    let repeated_output = program
        .run_csv_with_request_bars(REQUEST_HOST_CHART_CSV, REQUEST_HOST_BARS_JSON)
        .expect("compiled request fixture should run again");

    assert_eq!(compiled_output, direct_output);
    assert_eq!(repeated_output, direct_output);
}

#[test]
fn run_csv_with_request_bars_reports_missing_request_key() {
    let program = compile_script(REQUEST_HOST_SOURCE).expect("request fixture should compile");
    let message = program
        .run_csv_with_request_bars_internal(
            REQUEST_HOST_CHART_CSV,
            REQUEST_HOST_BARS_MISSING_HIGHER_JSON,
        )
        .expect_err("missing requested key should fail");

    assert!(
        message.contains("missing request data for symbol `NYSE:IBM` timeframe `5`"),
        "{message}"
    );
}

const IMPORT_SOURCE: &str =
    "indicator(\"imports\")\nimport user/lib/1 as lib\nplot(lib.scale(close) + lib.offset)\n";
const IMPORT_REQUEST_SOURCE: &str = "indicator(\"import request\")\nimport user/lib/1 as lib\nsame = request.security(\"NYSE:IBM\", timeframe.period, open + close)\nhigher = request.security(\"NYSE:IBM\", \"5\", close)\nplot(lib.scale(same))\nplot(higher + lib.offset)\n";
const IMPORT_LIBRARY_JSON: &str = "{\"user/lib/1\":\"library(\\\"lib\\\")\\nexport offset = 2\\nexport scale(value) => value * offset\\n\"}";

fn import_fixture_library_json() -> String {
    serde_json::json!({
        "user/lib/1": include_str!("../../../../tests/fixtures/libraries/import_lib.pine"),
    })
    .to_string()
}

#[test]
fn library_source_json_runs_imported_function_subset() {
    let output = run_script_csv_with_libraries(
        IMPORT_SOURCE,
        "time,open,high,low,close,volume\n0,1,1,1,1,1\n1,2,2,2,2,1\n",
        IMPORT_LIBRARY_JSON,
    )
    .expect("imported function subset should run");
    let parsed: serde_json::Value = serde_json::from_str(&output).expect("strict JSON output");

    assert_eq!(parsed["plots"][0]["values"], serde_json::json!([4, 6]));
}

#[test]
fn library_source_json_returns_import_fixture_contract() {
    let library_json = import_fixture_library_json();
    let output = run_script_csv_with_libraries(
        include_str!("../../../../tests/fixtures/runtime/import.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
        &library_json,
    )
    .expect("import fixture should run");

    assert_snapshot("runtime_import.json", &output);
}

#[test]
fn library_source_json_returns_import_state_fixture_contract() {
    let library_json = import_fixture_library_json();
    let output = run_script_csv_with_libraries(
        include_str!("../../../../tests/fixtures/runtime/import_state.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
        &library_json,
    )
    .expect("import state fixture should run");

    assert_snapshot("runtime_import_state.json", &output);
}

#[test]
fn library_source_json_combines_with_request_bars() {
    let output = run_script_csv_with_libraries_and_request_bars(
        IMPORT_REQUEST_SOURCE,
        REQUEST_HOST_CHART_CSV,
        IMPORT_LIBRARY_JSON,
        REQUEST_HOST_BARS_JSON,
    )
    .expect("import plus request fixture should run");
    let parsed: serde_json::Value = serde_json::from_str(&output).expect("strict JSON output");

    assert_eq!(
        parsed["plots"][0]["values"],
        serde_json::json!([60, 64, 68, 72, 76])
    );
    assert_eq!(
        parsed["plots"][1]["values"],
        serde_json::json!([null, null, 102, 102, 202])
    );
}

#[test]
fn library_source_json_combined_api_reports_library_input_errors() {
    let message = run_script_csv_with_libraries_and_request_bars_internal(
        IMPORT_REQUEST_SOURCE,
        REQUEST_HOST_CHART_CSV,
        "[]",
        REQUEST_HOST_BARS_JSON,
    )
    .expect_err("malformed library JSON should fail");

    assert!(message.contains("library sources must be a JSON object"));
}

#[test]
fn library_source_json_combined_api_reports_request_input_errors() {
    let message = run_script_csv_with_libraries_and_request_bars_internal(
        IMPORT_REQUEST_SOURCE,
        REQUEST_HOST_CHART_CSV,
        IMPORT_LIBRARY_JSON,
        "[]",
    )
    .expect_err("malformed request bars JSON should fail");

    assert!(message.contains("request bars must be a JSON object"));
}

#[test]
fn library_source_json_reports_missing_library() {
    let output = analyze_script("import user/lib/1\nindicator(\"root\")\n");
    let parsed: serde_json::Value = serde_json::from_str(&output).expect("strict JSON output");
    let diagnostic_codes = parsed["diagnostics"]
        .as_array()
        .expect("diagnostics should be an array")
        .iter()
        .map(|diagnostic| {
            diagnostic["code"]
                .as_str()
                .expect("diagnostic code should be a string")
        })
        .collect::<Vec<_>>();
    let supported_features = parsed["compatibility"]["supported"]
        .as_array()
        .expect("supported features should be an array")
        .iter()
        .map(|feature| {
            feature["feature"]
                .as_str()
                .expect("supported feature should be a string")
        })
        .collect::<Vec<_>>();

    assert_eq!(parsed["executable"], serde_json::json!(false));
    assert!(supported_features.contains(&"import"));
    assert!(diagnostic_codes.contains(&"E_IMPORT_MISSING_LIBRARY"));
    assert!(diagnostic_codes.contains(&"E_IMPORT_ALIAS_REQUIRED"));
}

#[test]
fn library_source_json_reports_malformed_host_input() {
    let output = analyze_script_with_libraries(IMPORT_SOURCE, "[]");
    let parsed: serde_json::Value = serde_json::from_str(&output).expect("strict JSON output");

    assert_eq!(parsed["executable"], serde_json::json!(false));
    assert_eq!(
        parsed["diagnostics"][0]["code"],
        serde_json::json!("E_HOST_INPUT")
    );
    assert!(
        parsed["diagnostics"][0]["message"]
            .as_str()
            .expect("diagnostic message should be a string")
            .contains("library sources must be a JSON object")
    );
    assert_eq!(parsed["compatibility"]["supported"], serde_json::json!([]));
    assert_eq!(
        parsed["compatibility"]["unsupported"],
        serde_json::json!([])
    );
}

#[test]
fn json_escape_escapes_control_characters() {
    assert_eq!(
        json_escape("quote \" slash \\ newline\n tab\t bell\u{07}"),
        "quote \\\" slash \\\\ newline\\n tab\\t bell\\u0007"
    );
}

#[test]
fn analysis_outputs_match_golden_snapshots() {
    assert_snapshot(
        "analysis_supported.json",
        &analyze_script(include_str!(
            "../../../../tests/fixtures/runtime/snapshot_plot.pine"
        )),
    );
    assert_snapshot(
        "analysis_unsupported.json",
        &analyze_script(include_str!(
            "../../../../tests/fixtures/sema/unsupported_request.pine"
        )),
    );
}

#[test]
fn run_script_csv_returns_polyline_new_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/polyline_new.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("polyline new fixture should run");

    assert_snapshot("runtime_polyline_new.json", &output);
}

#[test]
fn run_script_csv_returns_polyline_lifecycle_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/polyline_lifecycle.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("polyline lifecycle fixture should run");

    assert_snapshot("runtime_polyline_lifecycle.json", &output);
}

#[test]
fn run_script_csv_returns_map_methods_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/map_methods.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("map methods fixture should run");

    assert_snapshot("runtime_map_methods.json", &output);
}

#[test]
fn run_script_csv_returns_map_history_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/map_history.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("map history fixture should run");

    assert_snapshot("runtime_map_history.json", &output);
}

#[test]
fn run_script_csv_returns_map_for_in_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/map_for_in.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("map for-in fixture should run");

    assert_snapshot("runtime_map_for_in.json", &output);
}

#[test]
fn run_script_csv_returns_map_varip_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/map_varip.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("map varip fixture should run");

    assert_snapshot("runtime_map_varip.json", &output);
}

#[test]
fn run_script_csv_returns_matrix_int_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/matrix_int.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("matrix int fixture should run");

    assert_snapshot("runtime_matrix_int.json", &output);
}

#[test]
fn run_script_csv_returns_matrix_bool_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/matrix_bool.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("matrix bool fixture should run");

    assert_snapshot("runtime_matrix_bool.json", &output);
}

#[test]
fn run_script_csv_returns_matrix_history_shape_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/matrix_history_shape.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("matrix history shape fixture should run");

    assert_snapshot("runtime_matrix_history_shape.json", &output);
}

#[test]
fn run_script_csv_returns_matrix_for_in_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/matrix_for_in.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("matrix for-in fixture should run");

    assert_snapshot("runtime_matrix_for_in.json", &output);
}

#[test]
fn run_script_csv_returns_matrix_mult_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/matrix_mult.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("matrix mult fixture should run");

    assert_snapshot("runtime_matrix_mult.json", &output);
}

#[test]
fn run_script_csv_returns_matrix_inv_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/matrix_inv.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("matrix inverse fixture should run");

    assert_snapshot("runtime_matrix_inv.json", &output);
}

#[test]
fn run_script_csv_returns_matrix_varip_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/matrix_varip.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("matrix varip fixture should run");

    assert_snapshot("runtime_matrix_varip.json", &output);
}

#[test]
fn run_script_csv_returns_matrix_zero_dimensions_fixture_contract() {
    let output = run_script_csv(
        include_str!("../../../../tests/fixtures/runtime/matrix_zero_dimensions.pine"),
        include_str!("../../../../tests/fixtures/runtime/bars.csv"),
    )
    .expect("matrix zero dimensions fixture should run");

    assert_snapshot("runtime_matrix_zero_dimensions.json", &output);
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

fn input_call_ids_by_title(source: &str) -> HashMap<String, u64> {
    let output = analyze_script(source);
    let parsed: serde_json::Value = serde_json::from_str(&output).expect("strict JSON output");

    parsed["inputs"]
        .as_array()
        .expect("inputs should be an array")
        .iter()
        .map(|input| {
            (
                input["title"]
                    .as_str()
                    .expect("input title should be a string")
                    .to_owned(),
                input["callSiteId"]
                    .as_u64()
                    .expect("input callSiteId should be an integer"),
            )
        })
        .collect()
}

fn input_overrides_json(overrides: &[(u64, serde_json::Value)]) -> String {
    let object = overrides
        .iter()
        .map(|(call_site_id, value)| (call_site_id.to_string(), value.clone()))
        .collect::<serde_json::Map<_, _>>();
    serde_json::Value::Object(object).to_string()
}

fn workspace_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..")
}
