use std::{
    fs,
    path::{Path, PathBuf},
};

use pine_runtime::{Bar, HistoricalRuntime, run_historical};
use pine_sema::{Analysis, AnalysisInput, analyze_input, analyze_source};
use pine_syntax::SourceFile;

fn workspace_fixture(path: &str) -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .join(path)
}

#[test]
fn runtime_fixtures_match_incremental_append_execution() {
    let fixtures_dir = workspace_fixture("tests/fixtures/runtime");
    let default_bars = load_bars(&workspace_fixture("tests/fixtures/runtime/bars.csv"));
    let strategy_exit_loss_bars = load_bars(&workspace_fixture(
        "tests/fixtures/runtime/strategy_exit_loss_bars.csv",
    ));
    let strategy_exit_profit_loss_interactions_bars = load_bars(&workspace_fixture(
        "tests/fixtures/runtime/strategy_exit_profit_loss_interactions_bars.csv",
    ));
    let strategy_exit_bracket_loss_profit_loss_bars = load_bars(&workspace_fixture(
        "tests/fixtures/runtime/strategy_exit_bracket_loss_profit_loss_bars.csv",
    ));
    let strategy_exit_bracket_mixed_pairs_bars = load_bars(&workspace_fixture(
        "tests/fixtures/runtime/strategy_exit_bracket_mixed_pairs_bars.csv",
    ));
    let strategy_exit_bracket_replacement_bars = load_bars(&workspace_fixture(
        "tests/fixtures/runtime/strategy_exit_bracket_replacement_bars.csv",
    ));
    let strategy_exit_bracket_both_hit_bars = load_bars(&workspace_fixture(
        "tests/fixtures/runtime/strategy_exit_bracket_both_hit_bars.csv",
    ));
    let trailing_bars = load_bars(&workspace_fixture(
        "tests/fixtures/runtime/strategy_exit_trailing_bars.csv",
    ));
    let reservation_trailing_bars = load_bars(&workspace_fixture(
        "tests/fixtures/runtime/strategy_exit_reservation_trailing_bars.csv",
    ));
    let reservation_trailing_mixed_bars = load_bars(&workspace_fixture(
        "tests/fixtures/runtime/strategy_exit_reservation_trailing_mixed_bars.csv",
    ));
    let reservation_trailing_host_parity_bars = load_bars(&workspace_fixture(
        "tests/fixtures/runtime/strategy_exit_reservation_trailing_host_parity_bars.csv",
    ));
    let strategy_pyramiding_exit_omitted_profit_persistent_bars = load_bars(&workspace_fixture(
        "tests/fixtures/runtime/strategy_pyramiding_exit_omitted_profit_persistent_from_entries_bars.csv",
    ));
    let strategy_pyramiding_exit_omitted_loss_persistent_bars = load_bars(&workspace_fixture(
        "tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_persistent_from_entries_bars.csv",
    ));
    let strategy_pyramiding_exit_omitted_loss_profit_bracket_persistent_bars = load_bars(
        &workspace_fixture(
            "tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_profit_bracket_persistent_from_entries_bars.csv",
        ),
    );
    let strategy_pyramiding_exit_omitted_stop_profit_bracket_persistent_bars = load_bars(
        &workspace_fixture(
            "tests/fixtures/runtime/strategy_pyramiding_exit_omitted_stop_profit_bracket_persistent_from_entries_bars.csv",
        ),
    );
    let strategy_pyramiding_exit_omitted_loss_limit_bracket_persistent_bars = load_bars(
        &workspace_fixture(
            "tests/fixtures/runtime/strategy_pyramiding_exit_omitted_loss_limit_bracket_persistent_from_entries_bars.csv",
        ),
    );
    let strategy_pyramiding_exit_omitted_stop_limit_bracket_persistent_bars = load_bars(
        &workspace_fixture(
            "tests/fixtures/runtime/strategy_pyramiding_exit_omitted_stop_limit_bracket_persistent_from_entries_bars.csv",
        ),
    );
    let mut checked = 0;

    for entry in fs::read_dir(&fixtures_dir).expect("runtime fixture dir should be readable") {
        let path = entry.expect("fixture entry should be readable").path();
        if path.extension().and_then(|extension| extension.to_str()) != Some("pine") {
            continue;
        }

        let text = fs::read_to_string(&path).expect("fixture should be readable");
        let has_latest_known_bar_state = text.contains("barstate.islast")
            || text.contains("barstate.islastconfirmedhistory")
            || text.contains("session.islastbar")
            || text.contains("session.islastbar_regular")
            || text.contains("last_bar_index")
            || text.contains("last_bar_time")
            || text.contains("chart.right_visible_bar_time");
        let analysis = analyze_fixture(&path, text);
        assert!(
            analysis.diagnostics.is_empty(),
            "{} diagnostics: {:?}",
            path.display(),
            analysis.diagnostics
        );
        let hir = analysis.hir.expect("runtime fixture should lower to HIR");
        let bars = match path.file_name().and_then(|name| name.to_str()) {
            Some("strategy_exit_loss.pine") => &strategy_exit_loss_bars,
            Some("strategy_exit_profit_loss_interactions.pine") => {
                &strategy_exit_profit_loss_interactions_bars
            }
            Some("strategy_exit_bracket_loss_profit_loss_fill.pine") => {
                &strategy_exit_bracket_loss_profit_loss_bars
            }
            Some("strategy_exit_bracket_mixed_pairs.pine") => {
                &strategy_exit_bracket_mixed_pairs_bars
            }
            Some("strategy_exit_bracket_replacement.pine") => {
                &strategy_exit_bracket_replacement_bars
            }
            Some("strategy_exit_bracket_both_hit.pine") => &strategy_exit_bracket_both_hit_bars,
            Some("strategy_exit_active_entry_trail_points_attachment.pine") => &trailing_bars,
            Some("strategy_exit_active_entry_stop_profit_bracket.pine") => &trailing_bars,
            Some("strategy_exit_active_entry_loss_limit_bracket.pine") => &trailing_bars,
            Some("strategy_exit_active_entry_loss_profit_bracket.pine") => &trailing_bars,
            Some("strategy_exit_omitted_trailing_replacement.pine") => &trailing_bars,
            Some("strategy_exit_qty_trailing_partial.pine") => &trailing_bars,
            Some("strategy_exit_qty_percent_trailing_partial.pine") => &trailing_bars,
            Some("strategy_exit_reservation_qty_trailing_price_multi.pine") => {
                &reservation_trailing_bars
            }
            Some("strategy_exit_reservation_qty_trailing_points_multi.pine") => {
                &reservation_trailing_bars
            }
            Some("strategy_exit_reservation_qty_trailing_replacement.pine") => {
                &reservation_trailing_bars
            }
            Some("strategy_exit_reservation_qty_trailing_clamp.pine") => &reservation_trailing_bars,
            Some("strategy_exit_reservation_trailing_state.pine") => &reservation_trailing_bars,
            Some("strategy_exit_reservation_qty_percent_trailing_multi.pine") => {
                &reservation_trailing_bars
            }
            Some("strategy_exit_reservation_qty_mixed_trailing_multi.pine") => {
                &reservation_trailing_bars
            }
            Some("strategy_exit_reservation_qty_percent_trailing_replacement.pine") => {
                &reservation_trailing_bars
            }
            Some("strategy_exit_reservation_qty_percent_trailing_clamp.pine") => {
                &reservation_trailing_bars
            }
            Some("strategy_exit_reservation_trailing_host_parity.pine") => {
                &reservation_trailing_host_parity_bars
            }
            Some("strategy_pyramiding_exit_omitted_profit_persistent_from_entries.pine") => {
                &strategy_pyramiding_exit_omitted_profit_persistent_bars
            }
            Some("strategy_pyramiding_exit_omitted_loss_persistent_from_entries.pine") => {
                &strategy_pyramiding_exit_omitted_loss_persistent_bars
            }
            Some(
                "strategy_pyramiding_exit_omitted_loss_profit_bracket_persistent_from_entries.pine",
            ) => &strategy_pyramiding_exit_omitted_loss_profit_bracket_persistent_bars,
            Some(
                "strategy_pyramiding_exit_omitted_stop_profit_bracket_persistent_from_entries.pine",
            ) => &strategy_pyramiding_exit_omitted_stop_profit_bracket_persistent_bars,
            Some(
                "strategy_pyramiding_exit_omitted_loss_limit_bracket_persistent_from_entries.pine",
            ) => &strategy_pyramiding_exit_omitted_loss_limit_bracket_persistent_bars,
            Some(
                "strategy_pyramiding_exit_omitted_stop_limit_bracket_persistent_from_entries.pine",
            ) => &strategy_pyramiding_exit_omitted_stop_limit_bracket_persistent_bars,
            Some("strategy_exit_reservation_trailing_single_downside_order.pine") => {
                &reservation_trailing_mixed_bars
            }
            Some("strategy_exit_reservation_trailing_bracket_downside_order.pine") => {
                &reservation_trailing_mixed_bars
            }
            Some("strategy_exit_reservation_trailing_mixed_side_precedence.pine") => {
                &reservation_trailing_mixed_bars
            }
            Some("strategy_exit_reservation_trailing_activation_mixed_fill.pine") => {
                &reservation_trailing_mixed_bars
            }
            Some("strategy_exit_reservation_trailing_replacement_mixed.pine") => {
                &reservation_trailing_mixed_bars
            }
            Some("strategy_exit_reservation_trailing_mixed_state.pine") => {
                &reservation_trailing_mixed_bars
            }
            _ => &default_bars,
        };

        let full = run_historical(&hir, bars).expect("full execution should succeed");
        let mut runtime = HistoricalRuntime::new(&hir);
        if has_latest_known_bar_state {
            runtime
                .append_bars(bars)
                .expect("append execution should succeed");
        } else {
            for bar in bars.iter().copied() {
                runtime
                    .append_bar(bar)
                    .expect("append execution should succeed");
            }
        }
        let incremental = runtime.result();

        assert_eq!(
            incremental,
            full,
            "{} incremental result should match full recomputation",
            path.display()
        );
        checked += 1;
    }

    assert!(checked >= 7, "expected runtime fixtures to be checked");
}

#[test]
fn for_in_fixtures_match_incremental_append_execution() {
    let bars = load_bars(&workspace_fixture("tests/fixtures/runtime/bars.csv"));

    for fixture in [
        "tests/fixtures/runtime/for_in.pine",
        "tests/fixtures/runtime/for_in_float.pine",
        "tests/fixtures/runtime/for_in_bool.pine",
        "tests/fixtures/runtime/for_in_string.pine",
        "tests/fixtures/runtime/for_in_color.pine",
        "tests/fixtures/runtime/for_in_control_flow.pine",
        "tests/fixtures/runtime/for_in_mutation.pine",
        "tests/fixtures/runtime/for_in_stateful.pine",
        "tests/fixtures/runtime/for_in_zero_iteration.pine",
    ] {
        assert_fixture_matches_incremental_append_execution(fixture, &bars);
    }
}

#[test]
fn matrix_history_fixtures_match_incremental_append_execution() {
    let bars = load_bars(&workspace_fixture("tests/fixtures/runtime/bars.csv"));

    for fixture in [
        "tests/fixtures/runtime/matrix_history.pine",
        "tests/fixtures/runtime/matrix_history_shape.pine",
        "tests/fixtures/runtime/matrix_dynamic_history.pine",
    ] {
        assert_fixture_matches_incremental_append_execution(fixture, &bars);
    }
}

fn assert_fixture_matches_incremental_append_execution(fixture: &str, bars: &[Bar]) {
    let path = workspace_fixture(fixture);
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let analysis = analyze_fixture(&path, text);
    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("runtime fixture should lower to HIR");

    let full = run_historical(&hir, bars).expect("full execution should succeed");
    let mut runtime = HistoricalRuntime::new(&hir);
    for bar in bars.iter().copied() {
        runtime
            .append_bar(bar)
            .expect("append execution should succeed");
    }

    assert_eq!(
        runtime.result(),
        full,
        "{} incremental result should match full recomputation",
        path.display()
    );
}

fn analyze_fixture(path: &Path, text: String) -> Analysis {
    let source = SourceFile::new(path.display().to_string(), text.clone());
    let library = if text.contains("import user/lib/1") {
        Some(("user/lib/1", "tests/fixtures/libraries/import_lib.pine"))
    } else if text.contains("import user/udt_array_returns/1") {
        Some((
            "user/udt_array_returns/1",
            "tests/fixtures/libraries/import_udt_array_return_lib.pine",
        ))
    } else if text.contains("import user/udt/1") {
        Some(("user/udt/1", "tests/fixtures/libraries/import_udt_lib.pine"))
    } else if text.contains("import user/non_scalar_udt/1") {
        Some((
            "user/non_scalar_udt/1",
            "tests/fixtures/libraries/import_non_scalar_udt_lib.pine",
        ))
    } else {
        None
    };
    let Some((key, library_fixture)) = library else {
        return analyze_source(&source);
    };
    let library_path = workspace_fixture(library_fixture);
    let library_text = fs::read_to_string(&library_path).expect("import library fixture");
    let input = AnalysisInput::with_library_sources(
        source,
        vec![(
            key.to_owned(),
            SourceFile::new(library_path.display().to_string(), library_text),
        )],
    )
    .expect("import fixture input");
    analyze_input(&input)
}

fn load_bars(path: &PathBuf) -> Vec<Bar> {
    let text = fs::read_to_string(path).expect("bars fixture should be readable");
    text.lines()
        .enumerate()
        .filter_map(|(index, line)| {
            if line.trim().is_empty() || index == 0 {
                return None;
            }
            let columns: Vec<_> = line.split(',').map(str::trim).collect();
            assert_eq!(columns.len(), 6, "bars fixture should have 6 columns");
            Some(Bar {
                time: columns[0].parse().expect("time should parse"),
                open: columns[1].parse().expect("open should parse"),
                high: columns[2].parse().expect("high should parse"),
                low: columns[3].parse().expect("low should parse"),
                close: columns[4].parse().expect("close should parse"),
                volume: columns[5].parse().expect("volume should parse"),
            })
        })
        .collect()
}
