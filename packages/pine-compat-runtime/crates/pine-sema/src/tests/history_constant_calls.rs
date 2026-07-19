use super::*;

#[test]
fn pure_const_calls_infer_declaration_max_bars_back_and_static_history() {
    let analysis = analyze(
        r#"length() =>
    base = math.abs(-2.9)
    int(math.max(base, math.floor(1.2)))
indicator("pure const declaration", max_bars_back=length())
offset = int(math.min(2.9, 4.0))
plot(close[offset])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.max_bars_back, Some(2));
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
}

#[test]
fn pure_const_calls_infer_aliased_series_max_bars_back() {
    let analysis = analyze(
        r#"indicator("pure const series")
base = math.ceil(1.1)
budget = float(base)
max_bars_back(close, int(math.min(budget, math.trunc(2.9))))
offset = input.int(1, "Offset")
plot(close[offset])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let close_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "close")
        .and_then(|symbol| symbol.series_id)
        .expect("close should have a series id");
    assert!(
        hir.series_max_bars_back
            .iter()
            .any(|value| { value.series_id == close_series && value.max_bars_back == 2 }),
        "{:?}",
        hir.series_max_bars_back
    );
    assert!(
        hir.series_history.iter().any(|requirement| {
            requirement.series_id == close_series && requirement.has_dynamic_offsets
        }),
        "{:?}",
        hir.series_history
    );
}

#[test]
fn const_aliases_keep_their_declaration_time_value_after_source_reassignment() {
    let analysis = analyze(
        r#"indicator("const alias snapshot")
base = math.ceil(1.1)
budget = float(base)
base := math.ceil(4.1)
max_bars_back(close, int(budget))
offset = bar_index == 3 ? 3 : 0
plot(close[offset])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let close_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "close")
        .and_then(|symbol| symbol.series_id)
        .expect("close should have a series id");
    assert!(
        hir.series_max_bars_back
            .iter()
            .any(|value| { value.series_id == close_series && value.max_bars_back == 2 }),
        "{:?}",
        hir.series_max_bars_back
    );
}

#[test]
fn nested_calls_keep_exact_integer_fallbacks_for_all_history_bounds() {
    let analysis = analyze(
        r#"indicator("nested exact fallback", max_bars_back=math.max(math.abs(-9223372036854775807 - 1) * 0, 2))
max_bars_back(close, math.max(math.abs(-9223372036854775807 - 1) * 0, 2))
offset = bar_index == 3 ? 3 : 0
plot(close[offset])
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.max_bars_back, Some(2));
    let close_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "close")
        .and_then(|symbol| symbol.series_id)
        .expect("close should have a series id");
    assert!(
        hir.series_max_bars_back
            .iter()
            .any(|value| { value.series_id == close_series && value.max_bars_back == 2 }),
        "{:?}",
        hir.series_max_bars_back
    );
}

#[test]
fn rejects_negative_pure_const_call_history_bounds() {
    for source in [
        "indicator(\"negative declaration\", max_bars_back=math.min(-1, 0))\n",
        "indicator(\"negative series\")\nmax_bars_back(close, int(math.min(-1.9, 0)))\n",
    ] {
        let analysis = analyze(source);

        assert!(
            analysis.diagnostics.iter().any(|diagnostic| {
                diagnostic.code == "E_CALL_ARG_VALUE"
                    && diagnostic.message.contains("max_bars_back")
            }),
            "source={source:?}, diagnostics={:?}",
            analysis.diagnostics
        );
        assert!(analysis.hir.is_none());
    }
}

#[test]
fn rejects_overflowing_pure_const_call_history_bounds() {
    for source in [
        "indicator(\"overflow declaration\", max_bars_back=math.abs(-4294967296))\n",
        "indicator(\"overflow series\")\nmax_bars_back(close, math.max(4294967296, 1))\n",
    ] {
        let analysis = analyze(source);

        assert!(
            analysis.diagnostics.iter().any(|diagnostic| {
                diagnostic.code == "E_CALL_ARG_VALUE"
                    && diagnostic.message.contains("32-bit unsigned history bound")
            }),
            "source={source:?}, diagnostics={:?}",
            analysis.diagnostics
        );
        assert!(analysis.hir.is_none());
    }
}
