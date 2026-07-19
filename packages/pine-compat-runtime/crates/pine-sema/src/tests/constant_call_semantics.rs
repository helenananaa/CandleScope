use super::*;
use pine_ir::{HirExprKind, HirHistoryOffset, HirStmtKind, PineType, Qualifier, ValueKind};

#[test]
fn pure_constant_calls_statically_select_scalar_qualifiers() {
    let analysis = analyze(
        r#"length = input.int(2, "Length")
max_selected = math.max(2, 3) == 3 ? length : bar_index
min_selected = math.min(2.5, 3.0) == 2.5 ? length : bar_index
abs_selected = math.abs(-2) == 2 ? length : bar_index
floor_selected = math.floor(2.9) == 2 ? length : bar_index
ceil_selected = math.ceil(2.1) == 3 ? length : bar_index
trunc_selected = math.trunc(-2.9) == -2 ? length : bar_index
int_selected = int(2.9) == 2 ? length : bar_index
float_selected = float(2) == 2.0 ? length : bar_index
plot(ta.ema(close, max_selected))
plot(ta.ema(close, min_selected))
plot(ta.ema(close, abs_selected))
plot(ta.ema(close, floor_selected))
plot(ta.ema(close, ceil_selected))
plot(ta.ema(close, trunc_selected))
plot(ta.ema(close, int_selected))
plot(ta.ema(close, float_selected))
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    for name in [
        "max_selected",
        "min_selected",
        "abs_selected",
        "floor_selected",
        "ceil_selected",
        "trunc_selected",
        "int_selected",
        "float_selected",
    ] {
        let symbol = hir
            .symbols
            .iter()
            .find(|symbol| symbol.name == name)
            .unwrap_or_else(|| panic!("{name} symbol"));
        assert_eq!(
            symbol.pine_type,
            PineType::new(Qualifier::Input, ValueKind::Int),
            "{name}"
        );
    }
}

#[test]
fn pure_constant_calls_feed_declaration_values() {
    let analysis = analyze(
        "indicator(\"Demo\", max_bars_back=math.ceil(2.1), max_labels_count=math.max(1, 2))\nplot(close[bar_index])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.max_bars_back, Some(3));
    assert_eq!(hir.drawing_settings.max_labels_count, Some(2));
}

#[test]
fn pure_constant_calls_enforce_declaration_value_ranges() {
    let analysis = analyze(
        "indicator(\"Demo\", max_bars_back=math.min(-1, 0), max_labels_count=math.max(501, 2))\n",
    );

    assert_eq!(
        analysis
            .diagnostics
            .iter()
            .filter(|diagnostic| diagnostic.code == "E_CALL_ARG_VALUE")
            .count(),
        2,
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn pure_constant_calls_enforce_strategy_numeric_value_ranges() {
    let analysis = analyze(
        "strategy(\"Demo\", initial_capital=math.min(-1.0, 0.0), pyramiding=math.min(-1, 2))\n",
    );

    assert_eq!(
        analysis
            .diagnostics
            .iter()
            .filter(|diagnostic| diagnostic.code == "E_CALL_ARG_VALUE")
            .count(),
        2,
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn cast_wrapped_pure_call_rejects_negative_history_offset() {
    let analysis = analyze("plot(close[int(math.min(-1, 0))])\n");

    assert!(
        analysis
            .compatibility
            .unsupported
            .iter()
            .any(|feature| feature.feature == "negative_history_offset"),
        "{:?}",
        analysis.compatibility.unsupported
    );
}

#[test]
fn cast_wrapped_pure_call_lowers_positive_history_offset_as_constant() {
    let analysis = analyze("plot(close[int(math.max(1.2, 2.8))])\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
}

#[test]
fn out_of_range_int_cast_enforces_declaration_value_ranges() {
    let analysis = analyze("indicator(\"Demo\", max_lines_count=int(9.223372036854776e18))\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_VALUE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn i64_min_abs_overflow_is_rejected_by_int_range_consumers() {
    for source in [
        "indicator(\"Demo\", max_bars_back=math.abs(-9223372036854775807 - 1))\n",
        "indicator(\"Demo\", max_labels_count=math.abs(-9223372036854775807 - 1))\n",
        "indicator(\"Demo\")\nmax_bars_back(close, math.abs(-9223372036854775807 - 1))\n",
    ] {
        let analysis = analyze(source);
        assert!(
            analysis
                .diagnostics
                .iter()
                .any(|diagnostic| diagnostic.code == "E_CALL_ARG_VALUE"),
            "source={source:?}, diagnostics={:?}",
            analysis.diagnostics
        );
        assert!(analysis.hir.is_none());
    }
}

#[test]
fn i64_min_abs_wrappers_remain_known_to_integer_consumers() {
    for source in [
        "indicator(\"Demo\", max_bars_back=-math.abs(-9223372036854775807 - 1))\n",
        "indicator(\"Demo\", max_labels_count=math.abs(-9223372036854775807 - 1) * 0)\n",
    ] {
        let analysis = analyze(source);
        assert!(
            analysis
                .diagnostics
                .iter()
                .any(|diagnostic| diagnostic.code == "E_CALL_ARG_VALUE"),
            "source={source:?}, diagnostics={:?}",
            analysis.diagnostics
        );
        assert!(analysis.hir.is_none());
    }

    let zero_bound =
        analyze("indicator(\"Demo\", max_bars_back=math.abs(-9223372036854775807 - 1) * 0)\n");
    assert!(
        zero_bound.diagnostics.is_empty(),
        "{:?}",
        zero_bound.diagnostics
    );
    assert_eq!(zero_bound.hir.expect("HIR").max_bars_back, Some(0));

    let negative_history = analyze("plot(close[-math.abs(-9223372036854775807 - 1)])\n");
    assert!(
        negative_history
            .compatibility
            .unsupported
            .iter()
            .any(|feature| feature.feature == "negative_history_offset"),
        "{:?}",
        negative_history.compatibility.unsupported
    );

    let zero_history = analyze("plot(close[math.abs(-9223372036854775807 - 1) * 0])\n");
    assert!(
        zero_history.diagnostics.is_empty(),
        "{:?}",
        zero_history.diagnostics
    );
    let hir = zero_history.hir.expect("HIR");
    let plot_arg = hir
        .statements
        .iter()
        .find_map(|statement| match &statement.kind {
            HirStmtKind::Expr(expr) => match &expr.kind {
                HirExprKind::Call { callee, args, .. } if callee == "plot" => {
                    args.first().map(|arg| &arg.value)
                }
                _ => None,
            },
            _ => None,
        })
        .expect("plot argument");
    assert!(
        matches!(
            &plot_arg.kind,
            HirExprKind::History {
                offset: HirHistoryOffset::Constant(0),
                ..
            }
        ),
        "{plot_arg:?}"
    );
}

#[test]
fn promoted_float_wrappers_are_rejected_by_runtime_strict_int_options() {
    let promoted_zero = "math.abs(-9223372036854775807 - 1) * 0";
    for source in [
        format!(
            "indicator(\"Demo\")\nlabel.new(bar_index, close, \"x\", text_formatting={promoted_zero})\n"
        ),
        format!(
            "indicator(\"Demo\")\nbox.new(bar_index, high, bar_index + 1, low, text_formatting={promoted_zero})\n"
        ),
        format!(
            "indicator(\"Demo\")\nid = table.new(position.top_right, 1, 1)\ntable.cell(id, 0, 0, \"x\", text_formatting={promoted_zero})\n"
        ),
    ] {
        let analysis = analyze(&source);
        assert!(
            analysis
                .diagnostics
                .iter()
                .any(|diagnostic| diagnostic.code == "E_CALL_ARG_VALUE"),
            "source={source:?}, diagnostics={:?}",
            analysis.diagnostics
        );
        assert!(analysis.hir.is_none());
    }
}

#[test]
fn na_pure_calls_are_not_treated_as_known_declaration_values() {
    let analysis = analyze("indicator(\"Demo\", max_labels_count=math.max(na, 501))\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.drawing_settings.max_labels_count, None);
}

#[test]
fn runtime_pure_calls_outside_the_whitelist_remain_unknown() {
    let analysis = analyze(
        "indicator(\"Demo\", max_bars_back=math.round(2.1))\nplot(close[math.round(2.1)])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.max_bars_back, None);
    assert_eq!(hir.history.max_constant_offset, 0);
    assert!(hir.history.has_dynamic_offsets);
}
