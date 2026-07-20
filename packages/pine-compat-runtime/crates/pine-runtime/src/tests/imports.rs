use pine_sema::{AnalysisInput, analyze_input};

use super::*;

fn analyze_import(root: &str, library: &str) -> pine_sema::Analysis {
    let input = AnalysisInput::with_library_sources(
        modern_source_file("root.pine", root),
        vec![(
            "user/lib/1".to_owned(),
            modern_source_file("lib.pine", library),
        )],
    )
    .expect("analysis input");
    analyze_input(&input)
}

#[test]
fn runs_imported_constants_and_pure_functions() {
    let analysis = analyze_import(
        r#"indicator("imports")
import user/lib/1 as lib
plot(lib.scale(close) + lib.offset)
"#,
        r#"library("lib")
export offset = 2
export scale(value) => value * offset
"#,
    );
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0), bar(2.0), bar(3.0)])
        .expect("runtime result");

    assert_eq!(result.plots.len(), 1);
    assert_values_close(&result.plots[0].values, &[4.0, 6.0, 8.0]);
}

#[test]
fn imported_function_locals_shadow_exported_constants() {
    let analysis = analyze_import(
        r#"indicator("import shadow")
import user/lib/1 as lib
plot(lib.scale(close))
"#,
        r#"library("lib")
export offset = 2
export scale(value) =>
    offset = 5
    value + offset
"#,
    );
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0), bar(2.0), bar(3.0)])
        .expect("runtime result");

    assert_eq!(result.plots.len(), 1);
    assert_values_close(&result.plots[0].values, &[6.0, 7.0, 8.0]);
}

#[test]
fn imported_function_callsite_state_is_independent() {
    let analysis = analyze_import(
        r#"indicator("imported state")
import user/lib/1 as lib
plot(lib.counter() + lib.counter())
"#,
        r#"library("lib")
export counter() =>
    var value = 0
    value := value + 1
    value
"#,
    );
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0), bar(2.0), bar(3.0)])
        .expect("runtime result");

    assert_eq!(result.plots.len(), 1);
    assert_values_close(&result.plots[0].values, &[2.0, 4.0, 6.0]);
}

#[test]
fn imported_constant_length_bounds_series_max_bars_back_retention() {
    let analysis = analyze_import(
        r#"indicator("imported max_bars_back length")
import user/lib/1 as lib
max_bars_back(close, lib.length())
offset = bar_index == 0 ? 0 : 3
plot(close[offset])
plot(open[offset])
"#,
        r#"library("lib")
export length() => 2
"#,
    );
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
fn imported_constant_length_bounds_declaration_max_bars_back_retention() {
    let analysis = analyze_import(
        r#"indicator("imported declaration max_bars_back length", max_bars_back=lib.length())
import user/lib/1 as lib
offset = bar_index == 0 ? 0 : 3
plot(close[offset])
"#,
        r#"library("lib")
export length() =>
    base = 1
    base + 1
"#,
    );
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
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(profiled.profile.history_dynamic_retention_misses, 3);
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
}

#[test]
fn branch_skipped_imported_calls_do_not_advance_state() {
    let analysis = analyze_import(
        r#"indicator("imported branch state")
import user/lib/1 as lib
out = 0
if close >= 2
    out := lib.counter()
plot(out)
"#,
        r#"library("lib")
export counter() =>
    var value = 0
    value := value + 1
    value
"#,
    );
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(
        &analysis.hir.expect("HIR"),
        &[bar(1.0), bar(2.0), bar(3.0), bar(4.0)],
    )
    .expect("runtime result");

    assert_eq!(result.plots.len(), 1);
    assert_values_close(&result.plots[0].values, &[0.0, 1.0, 2.0, 3.0]);
}

#[test]
fn repeated_imports_of_same_source_share_exports_without_state_collision() {
    let input = AnalysisInput::with_library_sources(
        modern_source_file(
            "root.pine",
            r#"indicator("repeated imports")
import user/lib/1 as one
import user/lib/1 as two
plot(one.counter() + two.counter())
"#,
        ),
        vec![(
            "user/lib/1".to_owned(),
            modern_source_file(
                "lib.pine",
                r#"library("lib")
export counter() =>
    var value = 0
    value := value + 1
    value
"#,
            ),
        )],
    )
    .expect("analysis input");
    let analysis = analyze_input(&input);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0), bar(2.0), bar(3.0)])
        .expect("runtime result");

    assert_eq!(result.plots.len(), 1);
    assert_values_close(&result.plots[0].values, &[2.0, 4.0, 6.0]);
}
