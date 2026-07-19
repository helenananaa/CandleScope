use std::{fs, path::PathBuf};

use pine_runtime::{
    Bar, HistoryRetentionMode, RuntimeProfile, RuntimeProfiledResult, run_historical_profiled,
};
use pine_sema::{AnalysisInput, analyze_input, analyze_source};
use pine_syntax::SourceFile;

const PROFILE_BARS: usize = 512;

fn workspace_fixture(path: &str) -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .join(path)
}

fn profile_fixture(path: &str) -> RuntimeProfile {
    profiled_fixture(path).profile
}

fn profiled_fixture(path: &str) -> RuntimeProfiledResult {
    let fixture = workspace_fixture(path);
    let text = fs::read_to_string(&fixture).expect("profile fixture should be readable");
    let source = SourceFile::new(fixture.display().to_string(), text);
    let analysis = if source.text().contains("import user/udt/1") {
        let library_path = workspace_fixture("tests/fixtures/libraries/import_udt_lib.pine");
        let library_text =
            fs::read_to_string(&library_path).expect("imported UDT library should be readable");
        let input = AnalysisInput::with_library_sources(
            source,
            vec![(
                "user/udt/1".to_owned(),
                SourceFile::new(library_path.display().to_string(), library_text),
            )],
        )
        .expect("profile fixture library source should be valid");
        analyze_input(&input)
    } else {
        analyze_source(&source)
    };
    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        fixture.display(),
        analysis.diagnostics
    );

    run_historical_profiled(
        &analysis.hir.expect("profile fixture should lower to HIR"),
        &profile_bars(PROFILE_BARS),
    )
    .expect("profile fixture should run")
}

fn assert_series_max_bars_back_miss_fixture(path: &str) {
    let profiled = profiled_fixture(path);

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

fn assert_global_max_bars_back_miss_fixture(path: &str) {
    let profiled = profiled_fixture(path);

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(2));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 2);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

fn profile_bars(count: usize) -> Vec<Bar> {
    (0..count)
        .map(|index| {
            let close = 100.0 + (index % 37) as f64 + index as f64 * 0.125;
            Bar {
                time: index as i64 * 60_000,
                open: close - 0.25,
                high: close + 1.0,
                low: close - 1.0,
                close,
                volume: 1_000.0 + index as f64,
            }
        })
        .collect()
}

fn assert_capacity_within(
    metric: &str,
    capacity: usize,
    values: usize,
    max_multiplier: usize,
    slack: usize,
) {
    assert!(
        capacity <= values * max_multiplier + slack,
        "{metric} capacity {capacity} should stay within {max_multiplier}x values {values} plus slack {slack}"
    );
}

fn stateful_slot_count(profile: &RuntimeProfile) -> usize {
    profile.call_state_slots
        + profile.valuewhen_state_slots
        + profile.rolling_window_slots
        + profile.rsi_state_slots
        + profile.macd_state_slots
}

#[test]
fn long_ta_profile_fixture_has_bounded_storage_growth() {
    let profile = profile_fixture("tests/fixtures/profile/long_ta.pine");

    assert_eq!(profile.bars, PROFILE_BARS);
    assert_eq!(profile.plots, 5);
    assert_eq!(profile.plot_values, PROFILE_BARS * 5);
    assert_eq!(
        profile.history_retention_mode,
        HistoryRetentionMode::StaticTrimmed
    );
    assert!(!profile.history_has_dynamic_offsets);
    assert_eq!(profile.max_series_depth, 0);
    assert!(profile.rolling_window_slots >= 1);
    assert!(profile.macd_state_slots >= 1);
    assert_capacity_within("plot", profile.plot_capacity, profile.plot_values, 2, 64);
    assert!(
        profile.rolling_window_value_capacity <= 256,
        "rolling window capacity should stay bounded for long TA profiles: {:?}",
        profile
    );
}

#[test]
fn many_callsite_profile_fixture_records_state_slots() {
    let profile = profile_fixture("tests/fixtures/profile/many_callsites.pine");

    assert_eq!(profile.bars, PROFILE_BARS);
    assert_eq!(profile.plots, 1);
    assert_eq!(profile.plot_values, PROFILE_BARS);
    assert!(
        stateful_slot_count(&profile) >= 7,
        "many-callsite fixture should record state across profile slot maps: {:?}",
        profile
    );
    assert!(profile.rolling_window_slots >= 2);
    assert!(profile.rsi_state_slots >= 1);
    assert!(profile.valuewhen_state_slots >= 1);
    assert_capacity_within("plot", profile.plot_capacity, profile.plot_values, 2, 64);
    assert!(
        profile.rolling_window_value_capacity <= 256,
        "many-callsite rolling window capacity should stay bounded: {:?}",
        profile
    );
}

#[test]
fn array_heavy_profile_fixture_bounds_array_capacity() {
    let profile = profile_fixture("tests/fixtures/profile/array_heavy.pine");

    assert_eq!(profile.bars, PROFILE_BARS);
    assert_eq!(profile.array_slots, 1);
    assert_eq!(profile.array_values, PROFILE_BARS * 3);
    assert_eq!(profile.plots, 1);
    assert_eq!(profile.plot_values, PROFILE_BARS);
    assert_capacity_within(
        "array value",
        profile.array_value_capacity,
        profile.array_values,
        2,
        64,
    );
    assert_capacity_within("plot", profile.plot_capacity, profile.plot_values, 2, 64);
}

#[test]
fn matrix_heavy_profile_fixture_records_matrix_storage() {
    let profile = profile_fixture("tests/fixtures/profile/matrix_heavy.pine");

    assert_eq!(profile.bars, PROFILE_BARS);
    assert_eq!(profile.matrix_slots, PROFILE_BARS * 3);
    assert_eq!(profile.matrix_cells, PROFILE_BARS * 12);
    assert_eq!(profile.plots, 1);
    assert_eq!(profile.plot_values, PROFILE_BARS);
    assert!(profile.matrix_capacity >= profile.matrix_slots);
    assert!(profile.matrix_cell_capacity >= profile.matrix_cells);
    assert_capacity_within(
        "matrix slot",
        profile.matrix_capacity,
        profile.matrix_slots,
        2,
        64,
    );
    assert_capacity_within(
        "matrix cell",
        profile.matrix_cell_capacity,
        profile.matrix_cells,
        2,
        64,
    );
}

#[test]
fn dynamic_history_profile_fixture_respects_max_bars_back() {
    let profile = profile_fixture("tests/fixtures/profile/dynamic_history_max_bars_back.pine");

    assert_eq!(profile.bars, PROFILE_BARS);
    assert_eq!(
        profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profile.history_max_bars_back, Some(32));
    assert!(profile.history_has_dynamic_offsets);
    assert_eq!(profile.history_dynamic_retention_misses, 0);
    assert_eq!(profile.history_dynamic_retention_max_missed_offset, None);
    assert_eq!(profile.max_series_depth, 32);
    assert!(profile.series_buffers > 0);
    assert!(
        profile.series_values <= profile.series_buffers * 32,
        "max_bars_back should bound retained values per series buffer: {:?}",
        profile
    );
    assert_capacity_within(
        "series",
        profile.series_capacity,
        profile.series_values,
        2,
        64,
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_max_bars_back_misses() {
    let profile = profile_fixture("tests/fixtures/profile/dynamic_history_max_bars_back_miss.pine");

    assert_eq!(profile.bars, PROFILE_BARS);
    assert_eq!(
        profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profile.history_max_bars_back, Some(2));
    assert!(profile.history_has_dynamic_offsets);
    assert_eq!(profile.history_dynamic_retention_misses, PROFILE_BARS - 1);
    assert_eq!(profile.history_dynamic_retention_max_missed_offset, Some(3));
    assert_eq!(profile.max_series_depth, 2);
    assert!(profile.series_buffers > 0);
    assert!(
        profile.series_values <= profile.series_buffers * 2,
        "max_bars_back should bound retained values per series buffer: {:?}",
        profile
    );
    assert_capacity_within(
        "series",
        profile.series_capacity,
        profile.series_values,
        2,
        64,
    );
}

#[test]
fn dynamic_history_profile_fixture_respects_constant_expression_max_bars_back() {
    let profile =
        profile_fixture("tests/fixtures/profile/dynamic_history_constant_max_bars_back_miss.pine");

    assert_eq!(profile.bars, PROFILE_BARS);
    assert_eq!(
        profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profile.history_max_bars_back, Some(2));
    assert!(profile.history_has_dynamic_offsets);
    assert_eq!(profile.history_dynamic_retention_misses, PROFILE_BARS - 1);
    assert_eq!(profile.history_dynamic_retention_max_missed_offset, Some(3));
    assert_eq!(profile.max_series_depth, 2);
}

#[test]
fn dynamic_history_profile_fixture_reports_effective_series_max_bars_back_diagnostic() {
    let profiled =
        profiled_fixture("tests/fixtures/profile/dynamic_history_series_max_bars_back_miss.pine");

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_expression_source_series_max_bars_back_diagnostic() {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_expression_source_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_alias_expression_series_max_bars_back_diagnostic() {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_alias_expression_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_ternary_expression_series_max_bars_back_diagnostic() {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_ternary_expression_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_qualified_builtin_ternary_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_qualified_builtin_ternary_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_udt_field_expression_series_max_bars_back_diagnostic() {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_udt_field_expression_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_nested_udt_field_expression_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_nested_udt_field_expression_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_imported_udt_field_expression_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_imported_udt_field_expression_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_imported_nested_udt_field_expression_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_imported_nested_udt_field_expression_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_pure_math_call_series_max_bars_back_diagnostic() {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_pure_math_call_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_named_pure_math_call_series_max_bars_back_diagnostic() {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_named_pure_math_call_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_named_variadic_math_call_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_named_variadic_math_call_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_mixed_named_variadic_math_call_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_mixed_named_variadic_math_call_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_nz_call_series_max_bars_back_diagnostic() {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_nz_call_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_named_reordered_nz_call_series_max_bars_back_diagnostic()
{
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_named_reordered_nz_call_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_parameterized_pure_udf_call_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_parameterized_pure_udf_call_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_block_local_pure_udf_call_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_block_local_pure_udf_call_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_typed_block_local_pure_udf_call_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_typed_block_local_pure_udf_call_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_pure_expr_prefix_udf_call_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_pure_expr_prefix_udf_call_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_pure_udf_udt_arg_field_series_max_bars_back_diagnostic()
{
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_pure_udf_udt_arg_field_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_pure_udf_direct_udt_arg_expr_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_pure_udf_direct_udt_arg_expr_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_pure_udf_named_direct_udt_arg_expr_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_pure_udf_named_direct_udt_arg_expr_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_pure_udf_nested_udt_arg_field_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_pure_udf_nested_udt_arg_field_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_pure_udf_imported_nested_udt_arg_field_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_pure_udf_imported_nested_udt_arg_field_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_pure_udf_imported_direct_nested_udt_arg_expr_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_pure_udf_imported_direct_nested_udt_arg_expr_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_pure_udf_imported_named_direct_nested_udt_arg_expr_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_pure_udf_imported_named_direct_nested_udt_arg_expr_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_pure_udf_nested_udt_field_alias_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_pure_udf_nested_udt_field_alias_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_nested_pure_udf_nested_udt_arg_field_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_nested_pure_udf_nested_udt_arg_field_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_nested_pure_udf_direct_nested_udt_arg_expr_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_nested_pure_udf_direct_nested_udt_arg_expr_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_nested_pure_udf_imported_direct_nested_udt_arg_expr_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_nested_pure_udf_imported_direct_nested_udt_arg_expr_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_nested_pure_udf_named_direct_nested_udt_arg_expr_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_nested_pure_udf_named_direct_nested_udt_arg_expr_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_nested_pure_udf_imported_named_direct_nested_udt_arg_expr_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_nested_pure_udf_imported_named_direct_nested_udt_arg_expr_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_pure_user_method_call_series_max_bars_back_diagnostic() {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_pure_user_method_call_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_pure_user_method_receiver_field_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_pure_user_method_receiver_field_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_pure_user_method_receiver_alias_field_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_pure_user_method_receiver_alias_field_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_pure_user_method_nested_receiver_field_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_pure_user_method_nested_receiver_field_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_pure_user_method_nested_receiver_field_alias_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_pure_user_method_nested_receiver_field_alias_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_pure_user_method_imported_receiver_field_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_pure_user_method_imported_receiver_field_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_pure_user_method_imported_alias_qualified_receiver_field_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_pure_user_method_imported_alias_qualified_receiver_field_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_pure_user_method_imported_alias_qualified_direct_receiver_expr_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_pure_user_method_imported_alias_qualified_direct_receiver_expr_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_pure_user_method_imported_alias_qualified_udt_arg_field_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_pure_user_method_imported_alias_qualified_udt_arg_field_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_pure_user_method_imported_alias_qualified_direct_udt_arg_expr_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_pure_user_method_imported_alias_qualified_direct_udt_arg_expr_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_nested_pure_user_method_imported_alias_qualified_receiver_field_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_nested_pure_user_method_imported_alias_qualified_receiver_field_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_nested_pure_user_method_imported_alias_qualified_udt_arg_field_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_nested_pure_user_method_imported_alias_qualified_udt_arg_field_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_pure_user_method_imported_alias_qualified_named_udt_arg_field_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_pure_user_method_imported_alias_qualified_named_udt_arg_field_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_pure_user_method_imported_alias_qualified_named_direct_udt_arg_expr_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_pure_user_method_imported_alias_qualified_named_direct_udt_arg_expr_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_nested_pure_user_method_imported_alias_qualified_named_direct_nested_udt_arg_expr_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_nested_pure_user_method_imported_alias_qualified_named_direct_nested_udt_arg_expr_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_pure_user_method_imported_nested_receiver_alias_field_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_pure_user_method_imported_nested_receiver_alias_field_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_pure_user_method_imported_nested_receiver_field_alias_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_pure_user_method_imported_nested_receiver_field_alias_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_nested_pure_user_method_receiver_field_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_nested_pure_user_method_receiver_field_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_nested_pure_user_method_imported_receiver_field_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_nested_pure_user_method_imported_receiver_field_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_pure_user_method_udt_arg_field_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_pure_user_method_udt_arg_field_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_pure_user_method_named_udt_arg_field_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_pure_user_method_named_udt_arg_field_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_pure_user_method_named_direct_udt_arg_expr_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_pure_user_method_named_direct_udt_arg_expr_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_pure_user_method_nested_udt_arg_field_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_pure_user_method_nested_udt_arg_field_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_nested_pure_user_method_udt_arg_field_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_nested_pure_user_method_udt_arg_field_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_pure_user_method_imported_udt_arg_field_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_pure_user_method_imported_udt_arg_field_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_nested_pure_user_method_imported_udt_arg_field_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_nested_pure_user_method_imported_udt_arg_field_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_nested_pure_udf_call_series_max_bars_back_diagnostic() {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_nested_pure_udf_call_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_nested_pure_user_method_named_direct_nested_udt_arg_expr_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_nested_pure_user_method_named_direct_nested_udt_arg_expr_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_nested_pure_user_method_imported_named_direct_nested_udt_arg_expr_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_nested_pure_user_method_imported_named_direct_nested_udt_arg_expr_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_numeric_cast_series_max_bars_back_diagnostic() {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_numeric_cast_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_array_set_block_arg_series_max_bars_back_diagnostic() {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_array_set_block_arg_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_array_set_index_block_arg_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_array_set_index_block_arg_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_matrix_set_block_arg_series_max_bars_back_diagnostic() {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_matrix_set_block_arg_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_matrix_set_row_block_arg_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_matrix_set_row_block_arg_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_matrix_set_column_block_arg_series_max_bars_back_diagnostic()
 {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_matrix_set_column_block_arg_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_while_statement_series_max_bars_back_diagnostic() {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_while_statement_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_for_statement_series_max_bars_back_diagnostic() {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_for_statement_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_for_in_statement_series_max_bars_back_diagnostic() {
    let profiled = profiled_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_for_in_statement_miss.pine",
    );

    assert_eq!(profiled.profile.bars, PROFILE_BARS);
    assert_eq!(
        profiled.profile.history_retention_mode,
        HistoryRetentionMode::MaxBarsBack
    );
    assert_eq!(profiled.profile.history_max_bars_back, Some(10));
    assert!(profiled.profile.history_has_dynamic_offsets);
    assert_eq!(
        profiled.profile.history_dynamic_retention_misses,
        PROFILE_BARS - 1
    );
    assert_eq!(
        profiled.profile.history_dynamic_retention_max_missed_offset,
        Some(3)
    );
    assert_eq!(profiled.profile.max_series_depth, 10);
    assert_eq!(profiled.result.diagnostics.len(), 1);
    assert_eq!(
        profiled.result.diagnostics[0].code,
        "W_HISTORY_MAX_BARS_BACK"
    );
    assert_eq!(
        profiled.result.diagnostics[0].message,
        "dynamic history offsets exceeded max_bars_back=2; 511 reads returned na, maximum requested offset was 3"
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_block_series_max_bars_back_diagnostic() {
    assert_series_max_bars_back_miss_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_block_miss.pine",
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_expression_block_series_max_bars_back_diagnostic() {
    assert_series_max_bars_back_miss_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_expression_block_miss.pine",
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_switch_block_series_max_bars_back_diagnostic() {
    assert_series_max_bars_back_miss_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_switch_block_miss.pine",
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_statement_switch_series_max_bars_back_diagnostic() {
    assert_series_max_bars_back_miss_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_statement_switch_miss.pine",
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_if_expression_block_series_max_bars_back_diagnostic() {
    assert_series_max_bars_back_miss_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_if_expression_block_miss.pine",
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_tuple_if_expression_block_series_max_bars_back_diagnostic()
 {
    assert_series_max_bars_back_miss_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_tuple_if_expression_block_miss.pine",
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_tuple_switch_expression_block_series_max_bars_back_diagnostic()
 {
    assert_series_max_bars_back_miss_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_tuple_switch_expression_block_miss.pine",
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_call_argument_block_series_max_bars_back_diagnostic() {
    assert_series_max_bars_back_miss_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_call_argument_block_miss.pine",
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_block_result_series_max_bars_back_diagnostic() {
    assert_series_max_bars_back_miss_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_block_result_miss.pine",
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_loop_result_series_max_bars_back_diagnostic() {
    assert_series_max_bars_back_miss_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_loop_result_miss.pine",
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_while_result_series_max_bars_back_diagnostic() {
    assert_series_max_bars_back_miss_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_while_result_miss.pine",
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_for_in_result_series_max_bars_back_diagnostic() {
    assert_series_max_bars_back_miss_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_for_in_result_miss.pine",
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_udf_length_series_max_bars_back_diagnostic() {
    assert_series_max_bars_back_miss_fixture(
        "tests/fixtures/profile/dynamic_history_series_max_bars_back_udf_length_miss.pine",
    );
}

#[test]
fn dynamic_history_profile_fixture_reports_udf_max_bars_back_diagnostic() {
    assert_global_max_bars_back_miss_fixture(
        "tests/fixtures/profile/dynamic_history_udf_max_bars_back_miss.pine",
    );
}

#[test]
fn strategy_variable_history_profile_uses_static_trimmed_history() {
    let profile = profile_fixture("tests/fixtures/profile/strategy_variable_history.pine");

    assert_eq!(profile.bars, PROFILE_BARS);
    assert_eq!(profile.plots, 2);
    assert_eq!(profile.plot_values, PROFILE_BARS * 2);
    assert_eq!(
        profile.history_retention_mode,
        HistoryRetentionMode::StaticTrimmed
    );
    assert_eq!(profile.history_max_constant_offset, 1);
    assert_eq!(profile.history_max_bars_back, None);
    assert!(!profile.history_has_dynamic_offsets);
    assert_eq!(profile.max_series_depth, 1);
    assert!(profile.series_buffers >= 2);
    assert!(
        profile.series_values <= profile.series_buffers,
        "constant one-bar strategy variable history should retain at most one value per buffer: {:?}",
        profile
    );
    assert_capacity_within(
        "series",
        profile.series_capacity,
        profile.series_values,
        2,
        64,
    );
}
