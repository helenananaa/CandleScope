use pine_sema::analyze_source;
use pine_syntax::SourceFile;

use super::*;

#[test]
fn pure_const_call_drawing_limit_is_applied_at_runtime() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("pure const drawing limit", max_labels_count=math.max(1, 2))
for i = 0 to 2
    label.new(i, close, "x")
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)])
        .expect("runtime should apply the folded label limit");

    assert_eq!(result.labels.len(), 3);
    assert_eq!(result.labels[0].snapshots.len(), 2);
    assert!(!result.labels[0].snapshots[1].exists);
    assert!(result.labels[1].snapshots[0].exists);
    assert!(result.labels[2].snapshots[0].exists);
}

#[test]
fn pure_const_call_declaration_bound_drives_history_profile() {
    let source = SourceFile::new(
        "test.pine",
        r#"length() =>
    base = math.abs(-2.9)
    int(math.max(base, math.floor(1.2)))
indicator("pure const declaration profile", max_bars_back=length())
offset = bar_index == 0 ? 0 : 3
plot(close[offset])
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(profiled.result.plots.len(), 1);
    assert_eq!(profiled.result.plots[0].values[0], PineValue::Float(1.0));
    assert_eq!(profiled.result.plots[0].values[1..], vec![PineValue::Na; 3]);
    assert_eq!(profiled.profile.max_series_depth, 2);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(2));
    assert_eq!(profiled.profile.history_dynamic_retention_misses, 3);
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
}

#[test]
fn nested_const_call_exact_fallback_drives_runtime_retention() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("nested exact fallback", max_bars_back=math.max(math.abs(-9223372036854775807 - 1) * 0, 2))
offset = bar_index == 3 ? 3 : 0
plot(close[offset])
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let profiled = run_historical_profiled(
        &analysis.hir.expect("HIR"),
        &[bar(1.0), bar(2.0), bar(3.0), bar(4.0)],
    )
    .expect("runtime should apply the nested constant bound");

    assert_eq!(
        profiled.result.plots[0].values,
        vec![
            PineValue::Float(1.0),
            PineValue::Float(2.0),
            PineValue::Float(3.0),
            PineValue::Na,
        ]
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(2));
    assert_eq!(profiled.profile.history_dynamic_retention_misses, 1);
}

#[test]
fn history_lowering_does_not_capture_same_named_globals_for_callable_params() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("history parameter binding")
type Tool
    float base
method read(Tool tool, int offset) => close[offset]
offset = 1
read(offset) => close[offset]
tool = Tool.new(0.0)
plot(read(bar_index % 3))
plot(tool.read(bar_index % 3))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert!(hir.history.has_dynamic_offsets, "{:?}", hir.history);

    let bars = [
        bar(10.0),
        bar(20.0),
        bar(30.0),
        bar(40.0),
        bar(50.0),
        bar(60.0),
        bar(70.0),
    ];
    let profiled = run_historical_profiled(&hir, &bars)
        .expect("callable parameters should remain dynamic history offsets");
    let expected = vec![
        PineValue::Float(10.0),
        PineValue::Float(10.0),
        PineValue::Float(10.0),
        PineValue::Float(40.0),
        PineValue::Float(40.0),
        PineValue::Float(40.0),
        PineValue::Float(70.0),
    ];

    assert_eq!(profiled.result.plots[0].values, expected);
    assert_eq!(profiled.result.plots[1].values, expected);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::DynamicFull
    );
}

#[test]
fn pure_const_call_series_bound_only_limits_declared_series() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("pure const series profile")
base = math.ceil(1.1)
budget = float(base)
max_bars_back(close, int(math.min(budget, math.trunc(2.9))))
offset = bar_index == 0 ? 0 : 3
plot(close[offset])
plot(open[offset])
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(profiled.result.plots.len(), 2);
    assert_eq!(profiled.result.plots[0].values[0], PineValue::Float(1.0));
    assert_eq!(profiled.result.plots[0].values[1..], vec![PineValue::Na; 3]);
    assert_eq!(profiled.result.plots[1].values[0], PineValue::Float(1.0));
    assert_eq!(profiled.result.plots[1].values[1], PineValue::Na);
    assert_eq!(profiled.result.plots[1].values[2], PineValue::Na);
    assert_eq!(profiled.result.plots[1].values[3], PineValue::Float(1.0));
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, None);
    assert_eq!(profiled.profile.history_dynamic_retention_misses, 3);
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
}

#[test]
fn const_alias_history_bound_is_not_changed_by_later_source_reassignment() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("const alias snapshot")
base = math.ceil(1.1)
budget = float(base)
base := math.ceil(4.1)
max_bars_back(close, int(budget))
offset = bar_index == 3 ? 3 : 0
plot(close[offset])
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let profiled = run_historical_profiled(&analysis.hir.expect("HIR"), &bars)
        .expect("runtime should use the declaration-time alias value");

    assert_eq!(
        profiled.result.plots[0].values,
        vec![
            PineValue::Float(1.0),
            PineValue::Float(2.0),
            PineValue::Float(3.0),
            PineValue::Na,
        ]
    );
    assert_eq!(profiled.profile.history_dynamic_retention_misses, 1);
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
}

#[test]
fn pure_const_call_history_bounds_match_all_execution_modes() {
    let source = SourceFile::new(
        "test.pine",
        r#"length() =>
    base = math.abs(-3.9)
    int(math.max(base, math.floor(1.2)))
indicator("pure const history modes", max_bars_back=length())
budget = float(math.ceil(1.1))
max_bars_back(close, int(math.min(budget, math.trunc(2.9))))
offset = bar_index == 4 ? 3 : 0
plot(close[offset])
plot(open[offset])
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let bars = vec![
        bar_ohlc(1.0, 2.0, 1.0, 2.0),
        bar_ohlc(3.0, 3.0, 2.0, 2.0),
        bar_ohlc(2.0, 4.0, 2.0, 4.0),
        bar_ohlc(5.0, 5.0, 3.0, 3.0),
        bar_ohlc(4.0, 6.0, 4.0, 6.0),
    ];

    let profiled = run_historical_profiled(&hir, &bars).expect("historical result");
    let historical = profiled.result;
    assert_eq!(
        historical.plots[0].values,
        vec![
            PineValue::Float(2.0),
            PineValue::Float(2.0),
            PineValue::Float(4.0),
            PineValue::Float(3.0),
            PineValue::Na,
        ]
    );
    assert_eq!(
        historical.plots[1].values,
        vec![
            PineValue::Float(1.0),
            PineValue::Float(3.0),
            PineValue::Float(2.0),
            PineValue::Float(5.0),
            PineValue::Float(3.0),
        ]
    );
    assert_eq!(
        historical.plots[2].values,
        vec![
            PineValue::Float(2.0),
            PineValue::Float(2.0),
            PineValue::Float(4.0),
            PineValue::Float(3.0),
            PineValue::Float(6.0),
        ]
    );
    assert_eq!(historical.diagnostics.len(), 1);
    assert_eq!(historical.diagnostics[0].code, "W_HISTORY_MAX_BARS_BACK");
    assert_eq!(
        historical.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 1 reads returned na, maximum requested offset was 3"
    );
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(3));
    assert_eq!(profiled.profile.history_dynamic_retention_misses, 1);
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );

    let mut incremental = HistoricalRuntime::new(&hir);
    for bar in bars.iter().copied() {
        incremental.append_bar(bar).expect("incremental append");
    }
    let incremental_result = incremental.result();
    assert_eq!(incremental_result, historical);

    let mut realtime = RealtimeRuntime::new(&hir);
    for bar in bars[..3].iter().copied() {
        let result = realtime
            .update(BarUpdate::historical(bar))
            .expect("historical realtime update");
        assert!(result.diagnostics.is_empty(), "{result:?}");
    }
    let first_forming = realtime
        .update(BarUpdate::forming(bar_ohlc(10.0, 12.0, 9.0, 11.0)))
        .expect("first forming update");
    assert!(first_forming.diagnostics.is_empty(), "{first_forming:?}");
    assert_eq!(
        first_forming.plots[0].values.last(),
        Some(&PineValue::Float(11.0))
    );
    assert_eq!(
        first_forming.plots[2].values.last(),
        Some(&PineValue::Float(11.0))
    );

    let replacement_forming = realtime
        .update(BarUpdate::forming(bar_ohlc(20.0, 22.0, 19.0, 21.0)))
        .expect("replacement forming update");
    assert!(
        replacement_forming.diagnostics.is_empty(),
        "{replacement_forming:?}"
    );
    assert_eq!(
        replacement_forming.plots[0].values.last(),
        Some(&PineValue::Float(21.0))
    );
    assert_eq!(
        replacement_forming.plots[2].values.last(),
        Some(&PineValue::Float(21.0))
    );

    let confirmed = realtime
        .update(BarUpdate::confirmed(bars[3]))
        .expect("confirmed replacement update");
    assert!(confirmed.diagnostics.is_empty(), "{confirmed:?}");
    assert_eq!(
        confirmed.plots[0].values.last(),
        Some(&PineValue::Float(3.0))
    );
    assert_eq!(
        confirmed.plots[2].values.last(),
        Some(&PineValue::Float(3.0))
    );

    let realtime_result = realtime
        .update(BarUpdate::confirmed(bars[4]))
        .expect("final confirmed update");
    assert_eq!(realtime_result, historical);
}
