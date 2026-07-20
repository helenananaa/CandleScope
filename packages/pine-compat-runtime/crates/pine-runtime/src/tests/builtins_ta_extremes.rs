use pine_syntax::SourceFile;

use super::*;

#[test]
fn runs_pivots_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("pivots")
ph = ta.pivothigh(close, 1, 1)
pl = ta.pivotlow(close, 1, 1)
default_ph = ta.pivothigh(1, 1)
default_pl = ta.pivotlow(1, 1)
invalid = ta.pivothigh(close, -1, 1)
plot(ph)
plot(pl)
plot(default_ph)
plot(default_pl)
plot(na(invalid) ? 1 : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        bar_ohlc(1.0, 10.0, 5.0, 1.0),
        bar_ohlc(3.0, 12.0, 3.0, 3.0),
        bar_ohlc(2.0, 11.0, 4.0, 2.0),
        bar_ohlc(4.0, 14.0, 2.0, 4.0),
        bar_ohlc(1.0, 10.0, 4.0, 1.0),
        bar_ohlc(0.0, 9.0, 1.0, 0.0),
        bar_ohlc(2.0, 11.0, 3.0, 2.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(&result.plots[0].values[2..3], &[3.0]);
    assert_eq!(result.plots[0].values[3], PineValue::Na);
    assert_values_close(&result.plots[0].values[4..5], &[4.0]);
    assert_eq!(result.plots[0].values[5], PineValue::Na);
    assert_eq!(result.plots[0].values[6], PineValue::Na);

    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_eq!(result.plots[1].values[2], PineValue::Na);
    assert_values_close(&result.plots[1].values[3..4], &[2.0]);
    assert_eq!(result.plots[1].values[4], PineValue::Na);
    assert_eq!(result.plots[1].values[5], PineValue::Na);
    assert_values_close(&result.plots[1].values[6..], &[0.0]);

    assert_eq!(result.plots[2].values[0], PineValue::Na);
    assert_eq!(result.plots[2].values[1], PineValue::Na);
    assert_values_close(&result.plots[2].values[2..3], &[12.0]);
    assert_eq!(result.plots[2].values[3], PineValue::Na);
    assert_values_close(&result.plots[2].values[4..5], &[14.0]);
    assert_eq!(result.plots[2].values[5], PineValue::Na);
    assert_eq!(result.plots[2].values[6], PineValue::Na);

    assert_eq!(result.plots[3].values[0], PineValue::Na);
    assert_eq!(result.plots[3].values[1], PineValue::Na);
    assert_values_close(&result.plots[3].values[2..3], &[3.0]);
    assert_eq!(result.plots[3].values[3], PineValue::Na);
    assert_values_close(&result.plots[3].values[4..5], &[2.0]);
    assert_eq!(result.plots[3].values[5], PineValue::Na);
    assert_values_close(&result.plots[3].values[6..], &[1.0]);

    assert_values_close(
        &result.plots[4].values,
        &[1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
    );
}

#[test]
fn runs_pivot_point_levels_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("pivot levels")
levels = ta.pivot_point_levels("Traditional", bar_index == 2)
plot(array.get(levels, 0))
plot(array.get(levels, 1))
plot(array.get(levels, 2))
developing = ta.pivot_point_levels("Traditional", bar_index == 2, true)
plot(array.get(developing, 0))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        bar_ohlcv(10.0, 12.0, 8.0, 11.0, 10.0),
        bar_ohlcv(11.0, 13.0, 9.0, 12.0, 10.0),
        bar_ohlcv(12.0, 14.0, 10.0, 13.0, 10.0),
        bar_ohlcv(13.0, 15.0, 11.0, 14.0, 10.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 4);
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(&result.plots[0].values[2..], &[11.0, 11.0]);
    assert_values_close(&result.plots[1].values[2..], &[14.0, 14.0]);
    assert_values_close(&result.plots[2].values[2..], &[9.0, 9.0]);
    assert_values_close(
        &result.plots[3].values,
        &[10.333333333333334, 11.0, 12.333333333333334, 13.0],
    );
}

#[test]
fn calculates_pivot_point_level_formulas() {
    let period = PivotPointPeriod::new(10.0, 13.0, 8.0, 12.0);

    assert_values_close(
        &pivot_point_levels("Traditional", period, 12.0),
        &[11.0, 14.0, 9.0, 16.0, 6.0, 19.0, 4.0, 22.0, 2.0, 25.0, 0.0],
    );

    let fibonacci = pivot_point_levels("Fibonacci", period, 12.0);
    assert_values_close(
        &fibonacci[..7],
        &[11.0, 12.91, 9.09, 14.09, 7.91, 16.0, 6.0],
    );
    assert_eq!(fibonacci[7], PineValue::Na);
    assert_eq!(fibonacci[10], PineValue::Na);

    let woodie = pivot_point_levels("Woodie", period, 12.0);
    assert_values_close(
        &woodie[..9],
        &[11.25, 14.5, 9.5, 16.25, 6.25, 19.5, 4.5, 24.5, -0.5],
    );
    assert_eq!(woodie[9], PineValue::Na);
    assert_eq!(woodie[10], PineValue::Na);

    let classic = pivot_point_levels("Classic", period, 12.0);
    assert_values_close(
        &classic[..9],
        &[11.0, 14.0, 9.0, 16.0, 6.0, 21.0, 1.0, 26.0, -4.0],
    );
    assert_eq!(classic[9], PineValue::Na);
    assert_eq!(classic[10], PineValue::Na);

    let dm = pivot_point_levels("DM", period, 12.0);
    assert_values_close(&dm[..3], &[11.5, 15.0, 10.0]);
    assert_eq!(dm[3], PineValue::Na);
    assert_eq!(dm[10], PineValue::Na);

    assert_values_close(
        &pivot_point_levels("Camarilla", period, 12.0),
        &[
            11.0,
            12.458333333333334,
            11.541666666666666,
            12.916666666666666,
            11.083333333333334,
            13.375,
            10.625,
            14.75,
            9.25,
            19.5,
            4.5,
        ],
    );

    assert_eq!(
        pivot_point_levels("Unknown", period, 12.0),
        pivot_na_levels()
    );
}

#[test]
fn runs_highest_lowest_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("extremes")
hi = ta.highest(close, 3)
lo = ta.lowest(close, 3)
plot(hi)
plot(lo)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(3.0), bar(2.0), bar(5.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(&result.plots[0].values[2..], &[3.0, 5.0]);
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_values_close(&result.plots[1].values[2..], &[1.0, 2.0]);
}

#[test]
fn runs_all_time_extremes_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("all-time extremes")
hi = ta.max(close)
lo = ta.min(open)
held = ta.max(bar_index == 2 ? na : low)
plot(hi)
plot(lo)
plot(held)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        Bar {
            time: 1,
            open: 3.0,
            high: 5.0,
            low: 5.0,
            close: 1.0,
            volume: 100.0,
        },
        Bar {
            time: 2,
            open: 2.0,
            high: 4.0,
            low: 4.0,
            close: 3.0,
            volume: 100.0,
        },
        Bar {
            time: 3,
            open: 4.0,
            high: 6.0,
            low: 1.0,
            close: 2.0,
            volume: 100.0,
        },
        Bar {
            time: 4,
            open: 1.0,
            high: 7.0,
            low: 6.0,
            close: 5.0,
            volume: 100.0,
        },
        Bar {
            time: 5,
            open: 5.0,
            high: 6.0,
            low: 3.0,
            close: 4.0,
            volume: 100.0,
        },
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_values_close(&result.plots[0].values, &[1.0, 3.0, 3.0, 5.0, 5.0]);
    assert_values_close(&result.plots[1].values, &[3.0, 2.0, 2.0, 1.0, 1.0]);
    assert_values_close(&result.plots[2].values, &[5.0, 5.0, 5.0, 6.0, 6.0]);
}

#[test]
fn runs_highestbars_lowestbars_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("extreme bars")
hi = ta.highestbars(close, 3)
lo = ta.lowestbars(close, 3)
plot(hi)
plot(lo)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(3.0), bar(2.0), bar(5.0), bar(5.0), bar(4.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(&result.plots[0].values[2..], &[1.0, 0.0, 0.0, 1.0]);
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_values_close(&result.plots[1].values[2..], &[2.0, 1.0, 2.0, 0.0]);
}

#[test]
fn window_extremes_treat_non_finite_sources_as_na() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("non-finite extremes")
bad = (close - close) / (close - close)
plot(na(ta.highest(bad, 2)) ? 1 : 0)
plot(na(ta.lowest(bad, 2)) ? 1 : 0)
plot(na(ta.highestbars(bad, 2)) ? 1 : 0)
plot(na(ta.lowestbars(bad, 2)) ? 1 : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result =
        run_historical(&analysis.hir.expect("HIR"), &[bar(1.0), bar(2.0)]).expect("runtime result");

    for plot in &result.plots {
        assert_values_close(&plot.values, &[1.0, 1.0]);
    }
}

#[test]
fn runs_single_argument_extremes_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("single argument extremes")
hi = ta.highest(2)
lo = ta.lowest(2)
hi_offset = ta.highestbars(2)
lo_offset = ta.lowestbars(length=2)
plot(hi)
plot(lo)
plot(hi_offset)
plot(lo_offset)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        bar_ohlc(1.0, 5.0, 1.0, 1.0),
        bar_ohlc(1.0, 3.0, 0.0, 1.0),
        bar_ohlc(1.0, 4.0, 2.0, 1.0),
        bar_ohlc(1.0, 4.0, -1.0, 1.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(&result.plots[0].values[1..], &[5.0, 4.0, 4.0]);
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_values_close(&result.plots[1].values[1..], &[0.0, 0.0, -1.0]);
    assert_eq!(result.plots[2].values[0], PineValue::Na);
    assert_values_close(&result.plots[2].values[1..], &[1.0, 0.0, 0.0]);
    assert_eq!(result.plots[3].values[0], PineValue::Na);
    assert_values_close(&result.plots[3].values[1..], &[0.0, 1.0, 0.0]);
}

#[test]
fn runs_stdev_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("stdev")
biased = ta.stdev(close, 3)
sample = ta.stdev(close, 3, false)
plot(biased)
plot(sample)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(5.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(
        &result.plots[0].values[2..],
        &[0.816496580927726, 1.247219128924647],
    );
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_values_close(&result.plots[1].values[2..], &[1.0, 1.5275252316519468]);
}

#[test]
fn runs_variance_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("variance")
biased = ta.variance(close, 3)
sample = ta.variance(close, 3, false)
plot(biased)
plot(sample)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(5.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(
        &result.plots[0].values[2..],
        &[0.6666666666666666, 1.5555555555555556],
    );
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_values_close(&result.plots[1].values[2..], &[1.0, 2.3333333333333335]);
}

#[test]
fn runs_correlation_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("correlation")
same = ta.correlation(close, close, 3)
inverse = ta.correlation(close, -close, 3)
flat = ta.correlation(close, open, 3)
simple = ta.correlation(close, 10, 3)
with_na = ta.correlation(close, bar_index == 3 ? na : high, 3)
plot(same)
plot(inverse)
plot(flat)
plot(simple)
plot(with_na)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        bar_ohlcv(10.0, 1.0, 1.0, 1.0, 1.0),
        bar_ohlcv(10.0, 2.0, 2.0, 2.0, 1.0),
        bar_ohlcv(10.0, 3.0, 3.0, 3.0, 1.0),
        bar_ohlcv(10.0, 5.0, 5.0, 5.0, 1.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(&result.plots[0].values[2..], &[1.0, 1.0]);
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_values_close(&result.plots[1].values[2..], &[-1.0, -1.0]);
    assert_eq!(result.plots[2].values[0], PineValue::Na);
    assert_eq!(result.plots[2].values[1], PineValue::Na);
    assert_eq!(result.plots[2].values[2], PineValue::Na);
    assert_eq!(result.plots[2].values[3], PineValue::Na);
    assert_eq!(result.plots[3].values[0], PineValue::Na);
    assert_eq!(result.plots[3].values[1], PineValue::Na);
    assert_eq!(result.plots[3].values[2], PineValue::Na);
    assert_eq!(result.plots[3].values[3], PineValue::Na);
    assert_eq!(result.plots[4].values[0], PineValue::Na);
    assert_eq!(result.plots[4].values[1], PineValue::Na);
    assert_values_close(&result.plots[4].values[2..3], &[1.0]);
    assert_eq!(result.plots[4].values[3], PineValue::Na);
}

#[test]
fn runs_rank_correlation_index_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        include_str!("../../../../tests/fixtures/runtime/rci.pine"),
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        bar(1.0),
        bar(2.0),
        bar(3.0),
        bar(2.0),
        bar(1.0),
        bar(2.0),
        bar(3.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(
        &result.plots[0].values[2..],
        &[100.0, 12.5, -100.0, 12.5, 100.0],
    );
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_values_close(
        &result.plots[1].values[2..],
        &[-100.0, 12.5, 100.0, 12.5, -100.0],
    );
    assert_eq!(result.plots[2].values[0], PineValue::Na);
    assert_eq!(result.plots[2].values[1], PineValue::Na);
    assert_values_close(
        &result.plots[2].values[2..],
        &[50.0, 50.0, 50.0, 50.0, 50.0],
    );
    assert_eq!(result.plots[3].values[0], PineValue::Na);
    assert_eq!(result.plots[3].values[1], PineValue::Na);
    assert_values_close(&result.plots[3].values[2..3], &[100.0]);
    assert_eq!(result.plots[3].values[3], PineValue::Na);
    assert_eq!(result.plots[3].values[4], PineValue::Na);
    assert_eq!(result.plots[3].values[5], PineValue::Na);
    assert_values_close(&result.plots[3].values[6..], &[100.0]);
    assert!(
        result.plots[4]
            .values
            .iter()
            .all(|value| *value == PineValue::Na)
    );
    assert_eq!(result.plots[5].values, result.plots[0].values);
}

#[test]
fn runs_covariance_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("covariance")
same = ta.covariance(close, close, 3)
inverse = ta.covariance(close, -close, 3)
flat = ta.covariance(close, open, 3)
simple = ta.covariance(close, 10, 3)
with_na = ta.covariance(close, bar_index == 3 ? na : high, 3)
invalid = ta.covariance(close, high, 0)
plot(same)
plot(inverse)
plot(flat)
plot(simple)
plot(with_na)
plot(invalid)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        bar_ohlcv(10.0, 1.0, 1.0, 1.0, 1.0),
        bar_ohlcv(10.0, 2.0, 2.0, 2.0, 1.0),
        bar_ohlcv(10.0, 3.0, 3.0, 3.0, 1.0),
        bar_ohlcv(10.0, 5.0, 5.0, 5.0, 1.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(&result.plots[0].values[2..], &[2.0 / 3.0, 14.0 / 9.0]);
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_values_close(&result.plots[1].values[2..], &[-2.0 / 3.0, -14.0 / 9.0]);
    assert_eq!(result.plots[2].values[0], PineValue::Na);
    assert_eq!(result.plots[2].values[1], PineValue::Na);
    assert_values_close(&result.plots[2].values[2..], &[0.0, 0.0]);
    assert_eq!(result.plots[3].values[0], PineValue::Na);
    assert_eq!(result.plots[3].values[1], PineValue::Na);
    assert_values_close(&result.plots[3].values[2..], &[0.0, 0.0]);
    assert_eq!(result.plots[4].values[0], PineValue::Na);
    assert_eq!(result.plots[4].values[1], PineValue::Na);
    assert_values_close(&result.plots[4].values[2..3], &[2.0 / 3.0]);
    assert_eq!(result.plots[4].values[3], PineValue::Na);
    assert_eq!(result.plots[5].values[0], PineValue::Na);
    assert_eq!(result.plots[5].values[1], PineValue::Na);
    assert_eq!(result.plots[5].values[2], PineValue::Na);
    assert_eq!(result.plots[5].values[3], PineValue::Na);
}

#[test]
fn runs_median_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("median")
odd = ta.median(close, 3)
even = ta.median(close, 4)
simple = ta.median(3, 3)
with_na = ta.median(bar_index == 3 ? na : close, 3)
invalid = ta.median(close, 0)
plot(odd)
plot(even)
plot(simple)
plot(with_na)
plot(invalid)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(5.0), bar(2.0), bar(8.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(&result.plots[0].values[2..], &[2.0, 5.0]);
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_eq!(result.plots[1].values[2], PineValue::Na);
    assert_values_close(&result.plots[1].values[3..], &[3.5]);
    assert_eq!(result.plots[2].values[0], PineValue::Na);
    assert_eq!(result.plots[2].values[1], PineValue::Na);
    assert_values_close(&result.plots[2].values[2..], &[3.0, 3.0]);
    assert_eq!(result.plots[3].values[0], PineValue::Na);
    assert_eq!(result.plots[3].values[1], PineValue::Na);
    assert_values_close(&result.plots[3].values[2..3], &[2.0]);
    assert_eq!(result.plots[3].values[3], PineValue::Na);
    assert_eq!(result.plots[4].values[0], PineValue::Na);
    assert_eq!(result.plots[4].values[1], PineValue::Na);
    assert_eq!(result.plots[4].values[2], PineValue::Na);
    assert_eq!(result.plots[4].values[3], PineValue::Na);
}

#[test]
fn runs_mode_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("mode")
repeated = ta.mode(close, 3)
unique = ta.mode(close + bar_index, 3)
tie = ta.mode(close, 4)
simple = ta.mode(3, 3)
with_na = ta.mode(bar_index == 3 ? na : close, 3)
invalid = ta.mode(close, 0)
plot(repeated)
plot(unique)
plot(tie)
plot(simple)
plot(with_na)
plot(invalid)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(1.0), bar(2.0), bar(2.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(&result.plots[0].values[2..], &[1.0, 2.0]);
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_values_close(&result.plots[1].values[2..], &[1.0, 2.0]);
    assert_eq!(result.plots[2].values[0], PineValue::Na);
    assert_eq!(result.plots[2].values[1], PineValue::Na);
    assert_eq!(result.plots[2].values[2], PineValue::Na);
    assert_values_close(&result.plots[2].values[3..], &[1.0]);
    assert_eq!(result.plots[3].values[0], PineValue::Na);
    assert_eq!(result.plots[3].values[1], PineValue::Na);
    assert_values_close(&result.plots[3].values[2..], &[3.0, 3.0]);
    assert_eq!(result.plots[4].values[0], PineValue::Na);
    assert_eq!(result.plots[4].values[1], PineValue::Na);
    assert_values_close(&result.plots[4].values[2..3], &[1.0]);
    assert_eq!(result.plots[4].values[3], PineValue::Na);
    assert_eq!(result.plots[5].values[0], PineValue::Na);
    assert_eq!(result.plots[5].values[1], PineValue::Na);
    assert_eq!(result.plots[5].values[2], PineValue::Na);
    assert_eq!(result.plots[5].values[3], PineValue::Na);
}

#[test]
fn runs_percentile_nearest_rank_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("percentile")
middle = ta.percentile_nearest_rank(close, 3, 50)
lowest = ta.percentile_nearest_rank(close, 3, 0)
highest = ta.percentile_nearest_rank(close, 3, 100)
simple = ta.percentile_nearest_rank(3, 3, 50)
with_na = ta.percentile_nearest_rank(bar_index == 3 ? na : close, 3, 50)
invalid = ta.percentile_nearest_rank(close, 3, 150)
plot(middle)
plot(lowest)
plot(highest)
plot(simple)
plot(with_na)
plot(invalid)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(5.0), bar(2.0), bar(8.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(&result.plots[0].values[2..], &[2.0, 5.0]);
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_values_close(&result.plots[1].values[2..], &[1.0, 2.0]);
    assert_eq!(result.plots[2].values[0], PineValue::Na);
    assert_eq!(result.plots[2].values[1], PineValue::Na);
    assert_values_close(&result.plots[2].values[2..], &[5.0, 8.0]);
    assert_eq!(result.plots[3].values[0], PineValue::Na);
    assert_eq!(result.plots[3].values[1], PineValue::Na);
    assert_values_close(&result.plots[3].values[2..], &[3.0, 3.0]);
    assert_eq!(result.plots[4].values[0], PineValue::Na);
    assert_eq!(result.plots[4].values[1], PineValue::Na);
    assert_values_close(&result.plots[4].values[2..3], &[2.0]);
    assert_eq!(result.plots[4].values[3], PineValue::Na);
    assert_eq!(result.plots[5].values[0], PineValue::Na);
    assert_eq!(result.plots[5].values[1], PineValue::Na);
    assert_eq!(result.plots[5].values[2], PineValue::Na);
    assert_eq!(result.plots[5].values[3], PineValue::Na);
}

#[test]
fn runs_percentile_linear_interpolation_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("linear percentile")
middle = ta.percentile_linear_interpolation(close, 3, 50)
quarter = ta.percentile_linear_interpolation(close, 3, 25)
lowest = ta.percentile_linear_interpolation(close, 3, 0)
highest = ta.percentile_linear_interpolation(close, 3, 100)
simple = ta.percentile_linear_interpolation(3, 3, 50)
with_na = ta.percentile_linear_interpolation(bar_index == 3 ? na : close, 3, 50)
invalid = ta.percentile_linear_interpolation(close, 3, -1)
plot(middle)
plot(quarter)
plot(lowest)
plot(highest)
plot(simple)
plot(with_na)
plot(invalid)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(5.0), bar(2.0), bar(8.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(&result.plots[0].values[2..], &[2.0, 5.0]);
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_values_close(&result.plots[1].values[2..], &[1.5, 3.5]);
    assert_eq!(result.plots[2].values[0], PineValue::Na);
    assert_eq!(result.plots[2].values[1], PineValue::Na);
    assert_values_close(&result.plots[2].values[2..], &[1.0, 2.0]);
    assert_eq!(result.plots[3].values[0], PineValue::Na);
    assert_eq!(result.plots[3].values[1], PineValue::Na);
    assert_values_close(&result.plots[3].values[2..], &[5.0, 8.0]);
    assert_eq!(result.plots[4].values[0], PineValue::Na);
    assert_eq!(result.plots[4].values[1], PineValue::Na);
    assert_values_close(&result.plots[4].values[2..], &[3.0, 3.0]);
    assert_eq!(result.plots[5].values[0], PineValue::Na);
    assert_eq!(result.plots[5].values[1], PineValue::Na);
    assert_values_close(&result.plots[5].values[2..3], &[2.0]);
    assert_eq!(result.plots[5].values[3], PineValue::Na);
    assert_eq!(result.plots[6].values[0], PineValue::Na);
    assert_eq!(result.plots[6].values[1], PineValue::Na);
    assert_eq!(result.plots[6].values[2], PineValue::Na);
    assert_eq!(result.plots[6].values[3], PineValue::Na);
}

#[test]
fn runs_percentrank_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("percentrank")
rank = ta.percentrank(close, 3)
low_rank = ta.percentrank(bar_index == 3 ? 1 : close, 3)
simple = ta.percentrank(3, 3)
with_na = ta.percentrank(bar_index == 3 ? na : close, 3)
invalid = ta.percentrank(close, 0)
plot(rank)
plot(low_rank)
plot(simple)
plot(with_na)
plot(invalid)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(5.0), bar(2.0), bar(8.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(&result.plots[0].values[2..], &[200.0 / 3.0, 100.0]);
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_values_close(&result.plots[1].values[2..], &[200.0 / 3.0, 100.0 / 3.0]);
    assert_eq!(result.plots[2].values[0], PineValue::Na);
    assert_eq!(result.plots[2].values[1], PineValue::Na);
    assert_values_close(&result.plots[2].values[2..], &[100.0, 100.0]);
    assert_eq!(result.plots[3].values[0], PineValue::Na);
    assert_eq!(result.plots[3].values[1], PineValue::Na);
    assert_values_close(&result.plots[3].values[2..3], &[200.0 / 3.0]);
    assert_eq!(result.plots[3].values[3], PineValue::Na);
    assert_eq!(result.plots[4].values[0], PineValue::Na);
    assert_eq!(result.plots[4].values[1], PineValue::Na);
    assert_eq!(result.plots[4].values[2], PineValue::Na);
    assert_eq!(result.plots[4].values[3], PineValue::Na);
}

#[test]
fn runs_range_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("range")
value = ta.range(close, 3)
plot(value)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(3.0), bar(2.0), bar(5.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(&result.plots[0].values[2..], &[2.0, 3.0]);
}

#[test]
fn runs_dev_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("dev")
value = ta.dev(close, 3)
plot(value)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(4.0), bar(7.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(
        &result.plots[0].values[2..],
        &[1.1111111111111112, 1.7777777777777777],
    );
}
