use pine_syntax::SourceFile;

use super::*;

#[test]
fn runs_cum_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("cum")
value = ta.cum(close)
index_sum = ta.cum(bar_index)
reset_after_na = ta.cum(bar_index == 2 ? na : close)
plot(value)
plot(index_sum)
plot(reset_after_na)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0), bar(5.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_values_close(&result.plots[0].values, &[1.0, 3.0, 6.0, 10.0, 15.0]);
    assert_values_close(&result.plots[1].values, &[0.0, 1.0, 3.0, 6.0, 10.0]);
    assert_values_close(&result.plots[2].values[..2], &[1.0, 3.0]);
    assert_eq!(result.plots[2].values[2], PineValue::Na);
    assert_values_close(&result.plots[2].values[3..], &[4.0, 9.0]);
}

#[test]
fn runs_obv_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("obv")
plot(ta.obv)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        bar_volume(1.0, 10.0),
        bar_volume(3.0, 20.0),
        bar_volume(3.0, 30.0),
        bar_volume(2.0, 40.0),
        bar_volume(5.0, 50.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(&result.plots[0].values[1..], &[20.0, 20.0, -20.0, 30.0]);
}

#[test]
fn runs_accdist_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("accdist")
plot(ta.accdist)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        bar_ohlcv(10.0, 15.0, 5.0, 12.0, 100.0),
        bar_ohlcv(10.0, 20.0, 10.0, 10.0, 50.0),
        bar_ohlcv(10.0, 10.0, 10.0, 10.0, 30.0),
        bar_ohlcv(20.0, 30.0, 10.0, 25.0, 20.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_values_close(&result.plots[0].values[..2], &[40.0, -10.0]);
    assert_eq!(result.plots[0].values[2], PineValue::Na);
    assert_values_close(&result.plots[0].values[3..], &[10.0]);
}

#[test]
fn runs_iii_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("iii")
plot(ta.iii)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        bar_ohlcv(10.0, 15.0, 5.0, 12.0, 100.0),
        bar_ohlcv(12.0, 20.0, 10.0, 5.0, 2.0),
        bar_ohlcv(10.0, 10.0, 10.0, 10.0, 10.0),
        bar_ohlcv(10.0, 20.0, 10.0, 15.0, 0.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_values_close(&result.plots[0].values[..2], &[0.004, -1.0]);
    assert_eq!(result.plots[0].values[2], PineValue::Na);
    assert_eq!(result.plots[0].values[3], PineValue::Na);
}

#[test]
fn runs_vwap_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("vwap")
plot(ta.vwap)
plot(ta.vwap(close))
plot(ta.vwap(close, bar_index == 1))
[basis, upper, lower] = ta.vwap(close, bar_index == 0, 2.0)
plot(basis)
plot(upper)
plot(lower)
plot(ta.vwap(bar_index == 2 ? na : close))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        bar_ohlcv(9.0, 12.0, 6.0, 9.0, 10.0),
        bar_ohlcv(18.0, 24.0, 12.0, 18.0, 30.0),
        bar_ohlcv(25.0, 30.0, 15.0, 15.0, 0.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_values_close(&result.plots[0].values, &[9.0, 15.75, 15.75]);
    assert_values_close(&result.plots[1].values, &[9.0, 15.75, 15.75]);
    assert_eq!(result.plots[2].values[0], PineValue::Na);
    assert_values_close(&result.plots[2].values[1..], &[18.0, 18.0]);
    assert_values_close(&result.plots[3].values, &[9.0, 15.75, 15.75]);
    assert_values_close(
        &result.plots[4].values,
        &[9.0, 23.544228634059948, 23.544228634059948],
    );
    assert_values_close(
        &result.plots[5].values,
        &[9.0, 7.955771365940052, 7.955771365940052],
    );
    assert_values_close(&result.plots[6].values[..2], &[9.0, 15.75]);
    assert_eq!(result.plots[6].values[2], PineValue::Na);
}

#[test]
fn resets_default_vwap_on_utc_day_changes_and_waits_for_explicit_anchor() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("vwap anchors")
plot(ta.vwap)
plot(ta.vwap(close))
plot(ta.vwap(close, bar_index == 1))
[basis, upper, lower] = ta.vwap(close, bar_index == 1, close / 10)
plot(basis)
plot(upper)
plot(lower)
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
            open: 10.0,
            high: 10.0,
            low: 10.0,
            close: 10.0,
            volume: 1.0,
        },
        Bar {
            time: 60_000,
            open: 20.0,
            high: 20.0,
            low: 20.0,
            close: 20.0,
            volume: 1.0,
        },
        Bar {
            time: 86_400_000,
            open: 30.0,
            high: 30.0,
            low: 30.0,
            close: 30.0,
            volume: 1.0,
        },
        Bar {
            time: 86_460_000,
            open: 40.0,
            high: 40.0,
            low: 40.0,
            close: 40.0,
            volume: 1.0,
        },
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_values_close(&result.plots[0].values, &[10.0, 15.0, 30.0, 35.0]);
    assert_values_close(&result.plots[1].values, &[10.0, 15.0, 30.0, 35.0]);
    assert_eq!(result.plots[2].values[0], PineValue::Na);
    assert_values_close(&result.plots[2].values[1..], &[20.0, 25.0, 30.0]);
    assert_eq!(result.plots[3].values[0], PineValue::Na);
    assert_values_close(&result.plots[3].values[1..], &[20.0, 25.0, 30.0]);
    assert_eq!(result.plots[4].values[0], PineValue::Na);
    assert_values_close(
        &result.plots[4].values[1..],
        &[20.0, 40.0, 62.659_863_237_109_04],
    );
    assert_eq!(result.plots[5].values[0], PineValue::Na);
    assert_values_close(
        &result.plots[5].values[1..],
        &[20.0, 10.0, -2.659_863_237_109_043],
    );
}

#[test]
fn runs_nvi_pvi_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("volume index")
plot(ta.nvi)
plot(ta.pvi)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        bar_volume(10.0, 100.0),
        bar_volume(12.0, 90.0),
        bar_volume(6.0, 120.0),
        bar_volume(0.0, 80.0),
        bar_volume(5.0, 60.0),
        bar_volume(10.0, 50.0),
        bar_volume(15.0, 70.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_values_close(
        &result.plots[0].values,
        &[1.0, 1.2, 1.2, 1.2, 1.2, 2.4, 2.4],
    );
    assert_values_close(
        &result.plots[1].values,
        &[1.0, 1.0, 0.5, 0.5, 0.5, 0.5, 0.75],
    );
}

#[test]
fn runs_pvt_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("pvt")
plot(ta.pvt)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        bar_volume(10.0, 100.0),
        bar_volume(12.0, 50.0),
        bar_volume(6.0, 30.0),
        bar_volume(6.0, 20.0),
        bar_volume(9.0, 10.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(&result.plots[0].values[1..], &[10.0, -5.0, -5.0, 0.0]);
}

#[test]
fn runs_wad_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("wad")
plot(ta.wad)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        bar_ohlc(10.0, 10.0, 10.0, 10.0),
        bar_ohlc(11.0, 13.0, 11.0, 12.0),
        bar_ohlc(10.0, 12.0, 8.0, 9.0),
        bar_ohlc(8.0, 10.0, 7.0, 9.0),
        bar_ohlc(10.0, 12.0, 10.0, 11.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(&result.plots[0].values[1..], &[2.0, -1.0, -1.0, 1.0]);
}

#[test]
fn runs_wvad_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("wvad")
plot(ta.wvad)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        bar_ohlcv(10.0, 15.0, 5.0, 12.0, 100.0),
        bar_ohlcv(10.0, 10.0, 10.0, 10.0, 50.0),
        bar_ohlcv(20.0, 25.0, 15.0, 15.0, 40.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_values_close(&result.plots[0].values[..1], &[20.0]);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(&result.plots[0].values[2..], &[-20.0]);
}

#[test]
fn runs_true_range_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("TR")
tr = ta.tr()
plot(tr)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        bar_ohlc(9.0, 10.0, 8.0, 9.0),
        bar_ohlc(11.0, 12.0, 11.0, 11.0),
        bar_ohlc(7.0, 8.0, 6.0, 7.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_values_close(&result.plots[0].values, &[2.0, 3.0, 5.0]);
}

#[test]
fn true_range_can_return_na_on_first_bar() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("TR")
tr = ta.tr(false)
plot(tr)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        bar_ohlc(9.0, 10.0, 8.0, 9.0),
        bar_ohlc(11.0, 12.0, 11.0, 11.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(&result.plots[0].values[1..], &[3.0]);
}

#[test]
fn runs_true_range_variable_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("TR variable")
plot(ta.tr)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 1);

    let bars = vec![
        bar_ohlc(1.0, 2.0, 1.0, 1.5),
        bar_ohlc(2.0, 5.0, 2.0, 4.0),
        bar_ohlc(3.0, 4.0, 1.0, 2.0),
    ];
    let result = run_historical(&hir, &bars).expect("runtime result");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(&result.plots[0].values[1..], &[3.5, 3.0]);
}

#[test]
fn runs_atr_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("ATR")
atr = ta.atr(3)
plot(atr)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        bar_ohlc(9.0, 10.0, 8.0, 9.0),
        bar_ohlc(11.0, 12.0, 11.0, 11.0),
        bar_ohlc(7.0, 8.0, 6.0, 7.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_values_close(
        &result.plots[0].values,
        &[2.0, 2.3333333333333335, 3.2222222222222223],
    );
}

#[test]
fn runs_supertrend_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("Supertrend")
[line, direction] = ta.supertrend(2, 3)
[bad_line, bad_direction] = ta.supertrend(2, 0)
plot(line)
plot(direction)
plot(na(bad_line) and na(bad_direction) ? 1 : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 1);
    assert_builtin_series_history(&hir, "close", 1);

    let bars = vec![
        bar_ohlc(10.0, 11.0, 9.0, 10.0),
        bar_ohlc(10.0, 12.0, 10.0, 11.0),
        bar_ohlc(11.0, 13.0, 11.0, 12.0),
        bar_ohlc(12.0, 16.0, 12.0, 15.0),
        bar_ohlc(15.0, 17.0, 14.0, 16.0),
        bar_ohlc(16.0, 14.0, 8.0, 9.0),
    ];
    let result = run_historical(&hir, &bars).expect("runtime result");

    assert_values_close(
        &result.plots[0].values,
        &[
            14.0,
            14.0,
            14.0,
            8.666666666666668,
            9.944444444444445,
            20.037037037037038,
        ],
    );
    assert_values_close(&result.plots[1].values, &[1.0, 1.0, 1.0, -1.0, -1.0, 1.0]);
    assert_values_close(&result.plots[2].values, &[1.0, 1.0, 1.0, 1.0, 1.0, 1.0]);
}

#[test]
fn runs_dmi_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("DMI")
[plus, minus, adx] = ta.dmi(3, 2)
[bad_plus, bad_minus, bad_adx] = ta.dmi(3, 0)
plot(plus)
plot(minus)
plot(adx)
plot(na(bad_plus) and na(bad_minus) and na(bad_adx) ? 1 : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 1);
    assert_builtin_series_history(&hir, "high", 1);
    assert_builtin_series_history(&hir, "low", 1);
    assert_builtin_series_history(&hir, "close", 1);

    let bars = vec![
        bar_ohlc(10.0, 11.0, 9.0, 10.0),
        bar_ohlc(10.0, 12.0, 10.0, 11.0),
        bar_ohlc(11.0, 13.0, 11.0, 12.0),
        bar_ohlc(12.0, 16.0, 12.0, 15.0),
        bar_ohlc(15.0, 17.0, 14.0, 16.0),
        bar_ohlc(16.0, 14.0, 8.0, 9.0),
    ];
    let result = run_historical(&hir, &bars).expect("runtime result");

    assert_values_close(
        &result.plots[0].values,
        &[
            0.0,
            16.666666666666664,
            27.777777777777775,
            51.38888888888888,
            44.88888888888889,
            18.397085610200364,
        ],
    );
    assert_values_close(
        &result.plots[1].values,
        &[0.0, 0.0, 0.0, 0.0, 0.0, 44.26229508196722],
    );
    assert_values_close(
        &result.plots[2].values,
        &[0.0, 50.0, 75.0, 87.5, 93.75, 67.51453488372093],
    );
    assert_values_close(&result.plots[3].values, &[1.0, 1.0, 1.0, 1.0, 1.0, 1.0]);
}

#[test]
fn runs_change_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("change")
c1 = ta.change(close)
c2 = ta.change(close, 2)
index_change = ta.change(bar_index)
flag_change = ta.change(close > open)
plot(c1)
plot(c2)
plot(index_change)
plot(na(flag_change) ? 0 : flag_change ? 1 : -1)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(3.0), bar(6.0), bar(10.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(&result.plots[0].values[1..], &[2.0, 3.0, 4.0]);
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_values_close(&result.plots[1].values[2..], &[5.0, 7.0]);
    assert_eq!(result.plots[2].values[0], PineValue::Na);
    assert_values_close(&result.plots[2].values[1..], &[1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[3].values, &[0.0, -1.0, -1.0, -1.0]);
}

#[test]
fn runs_mom_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("mom")
value = ta.mom(close, 2)
index_value = ta.mom(bar_index, 2)
plot(value)
plot(index_value)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(3.0), bar(6.0), bar(10.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(&result.plots[0].values[2..], &[5.0, 7.0]);
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_values_close(&result.plots[1].values[2..], &[2.0, 2.0]);
}

#[test]
fn runs_roc_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("roc")
value = ta.roc(close, 2)
zero = ta.roc(open, 2)
index_value = ta.roc(bar_index, 2)
plot(value)
plot(zero)
plot(index_value)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        bar_ohlc(0.0, 1.0, 0.0, 10.0),
        bar_ohlc(1.0, 1.0, 1.0, 15.0),
        bar_ohlc(2.0, 2.0, 2.0, 20.0),
        bar_ohlc(3.0, 3.0, 3.0, 30.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(&result.plots[0].values[2..], &[100.0, 100.0]);
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_eq!(result.plots[1].values[2], PineValue::Na);
    assert_values_close(&result.plots[1].values[3..], &[200.0]);
    assert_eq!(result.plots[2].values[0], PineValue::Na);
    assert_eq!(result.plots[2].values[1], PineValue::Na);
    assert_eq!(result.plots[2].values[2], PineValue::Na);
    assert_values_close(&result.plots[2].values[3..], &[200.0]);
}

#[test]
fn runs_rising_falling_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("trend")
up = ta.rising(close, 2)
down = ta.falling(close, 2)
index_up = ta.rising(bar_index, 2)
index_down = ta.falling(bar_index, 2)
plot(up ? 1 : 0)
plot(down ? 1 : 0)
plot(index_up ? 1 : 0)
plot(index_down ? 1 : 0)
"#,
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
        bar(4.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_values_close(
        &result.plots[0].values,
        &[0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
    );
    assert_values_close(
        &result.plots[1].values,
        &[0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0],
    );
    assert_values_close(
        &result.plots[2].values,
        &[0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 1.0],
    );
    assert_values_close(&result.plots[3].values, &[0.0; 7]);
}

#[test]
fn runs_barssince_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("barssince")
value = ta.barssince(close > 2)
plot(value)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(2.0), bar(4.0), bar(1.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(&result.plots[0].values[2..], &[0.0, 1.0, 0.0, 1.0]);
}

#[test]
fn runs_valuewhen_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("valuewhen")
last_close = ta.valuewhen(close > 2, close, 0)
previous_index = ta.valuewhen(close > 2, bar_index, 1)
last_flag = ta.valuewhen(close > 2, close > open, 0)
plot(last_close)
plot(previous_index)
plot(na(last_flag) ? 0 : last_flag ? 1 : -1)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        bar_ohlc(1.0, 1.0, 1.0, 1.0),
        bar_ohlc(2.0, 3.0, 2.0, 3.0),
        bar_ohlc(3.0, 3.0, 2.0, 2.0),
        bar_ohlc(5.0, 5.0, 4.0, 4.0),
        bar_ohlc(1.0, 1.0, 1.0, 1.0),
        bar_ohlc(4.0, 5.0, 4.0, 5.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(&result.plots[0].values[1..], &[3.0, 3.0, 4.0, 4.0, 5.0]);
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_eq!(result.plots[1].values[2], PineValue::Na);
    assert_values_close(&result.plots[1].values[3..], &[1.0, 1.0, 3.0]);
    assert_values_close(&result.plots[2].values, &[0.0, 1.0, 1.0, -1.0, -1.0, 1.0]);
}

#[test]
fn runs_cross_functions_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("cross")
baseline = close * 0 + 2.0
crossed = ta.cross(close, baseline)
over = ta.crossover(close, baseline)
under = ta.crossunder(close, baseline)
plot(crossed ? 1 : 0)
plot(over ? 1 : 0)
plot(under ? 1 : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 1);
    assert_builtin_series_history(&hir, "close", 1);
    assert_builtin_series_history(&hir, "baseline", 1);

    let bars = vec![bar(1.0), bar(3.0), bar(1.0), bar(2.0), bar(4.0)];
    let result = run_historical(&hir, &bars).expect("runtime result");

    assert_values_close(&result.plots[0].values, &[0.0, 1.0, 1.0, 0.0, 1.0]);
    assert_values_close(&result.plots[1].values, &[0.0, 1.0, 0.0, 0.0, 1.0]);
    assert_values_close(&result.plots[2].values, &[0.0, 0.0, 1.0, 0.0, 0.0]);
}

#[test]
fn runs_vwma_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("vwma")
value = ta.vwma(close, 3)
plot(value)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        bar_volume(1.0, 10.0),
        bar_volume(3.0, 20.0),
        bar_volume(5.0, 30.0),
        bar_volume(7.0, 40.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(
        &result.plots[0].values[2..],
        &[3.6666666666666665, 5.444444444444445],
    );
}

#[test]
fn runs_mfi_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("mfi")
value = ta.mfi(close, 3)
flat = ta.mfi(close * 0 + 1, 2)
invalid = ta.mfi(close, 0)
plot(value)
plot(na(flat) ? 1 : 0)
plot(na(invalid) ? 1 : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 1);
    assert_builtin_series_history(&hir, "close", 1);

    let bars = vec![
        bar_volume(10.0, 100.0),
        bar_volume(11.0, 200.0),
        bar_volume(12.0, 300.0),
        bar_volume(10.0, 400.0),
        bar_volume(13.0, 500.0),
        bar_volume(12.0, 600.0),
    ];
    let result = run_historical(&hir, &bars).expect("runtime result");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(
        &result.plots[0].values[2..],
        &[
            100.0,
            59.183673469387756,
            71.63120567375887,
            36.72316384180791,
        ],
    );
    assert_values_close(&result.plots[1].values, &[1.0, 1.0, 1.0, 1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[2].values, &[1.0, 1.0, 1.0, 1.0, 1.0, 1.0]);
}

#[test]
fn runs_tsi_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("tsi")
value = ta.tsi(close, 2, 3)
flat = ta.tsi(close * 0 + 1, 2, 3)
invalid = ta.tsi(close, 0, 3)
plot(value)
plot(na(flat) ? 1 : 0)
plot(na(invalid) ? 1 : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 1);
    assert_builtin_series_history(&hir, "close", 1);

    let bars = vec![
        bar(10.0),
        bar(11.0),
        bar(12.0),
        bar(10.0),
        bar(13.0),
        bar(12.0),
    ];
    let result = run_historical(&hir, &bars).expect("runtime result");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(
        &result.plots[0].values[1..],
        &[
            1.0,
            1.0,
            4.163336342344337e-17,
            0.42857142857142866,
            0.2085561497326204,
        ],
    );
    assert_values_close(&result.plots[1].values, &[1.0, 1.0, 1.0, 1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[2].values, &[1.0, 1.0, 1.0, 1.0, 1.0, 1.0]);
}

#[test]
fn runs_cmo_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("cmo")
value = ta.cmo(close, 3)
flat = ta.cmo(close * 0 + 1, 2)
invalid = ta.cmo(close, 0)
plot(value)
plot(na(flat) ? 1 : 0)
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
        bar(10.0),
        bar(11.0),
        bar(12.0),
        bar(10.0),
        bar(13.0),
        bar(12.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_eq!(result.plots[0].values[2], PineValue::Na);
    assert_values_close(
        &result.plots[0].values[3..],
        &[0.0, 33.333333333333336, 0.0],
    );
    assert_values_close(&result.plots[1].values, &[1.0, 1.0, 1.0, 1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[2].values, &[1.0, 1.0, 1.0, 1.0, 1.0, 1.0]);
}

#[test]
fn runs_cci_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("cci")
value = ta.cci(close, 3)
flat = ta.cci(close * 0 + 1, 2)
invalid = ta.cci(close, 0)
plot(value)
plot(na(flat) ? 1 : 0)
plot(na(invalid) ? 1 : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(2.0), bar(1.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(&result.plots[0].values[2..], &[100.0, -50.0, -100.0]);
    assert_values_close(&result.plots[1].values, &[1.0, 1.0, 1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[2].values, &[1.0, 1.0, 1.0, 1.0, 1.0]);
}

#[test]
fn runs_cog_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("cog")
value = ta.cog(close, 3)
zero = ta.cog(close * 0, 2)
invalid = ta.cog(close, 0)
plot(value)
plot(na(zero) ? 1 : 0)
plot(na(invalid) ? 1 : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(
        &result.plots[0].values[2..],
        &[-1.6666666666666667, -1.7777777777777777],
    );
    assert_values_close(&result.plots[1].values, &[1.0, 1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[2].values, &[1.0, 1.0, 1.0, 1.0]);
}

#[test]
fn runs_stoch_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("stoch")
k = ta.stoch(close, high, low, 3)
flat = ta.stoch(close, 1 + close * 0, 1 + close * 0, 2)
invalid = ta.stoch(close, high, low, 0)
plot(k)
plot(na(flat) ? 1 : 0)
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
        bar_ohlc(10.0, 11.0, 9.0, 10.0),
        bar_ohlc(10.0, 12.0, 10.0, 11.0),
        bar_ohlc(11.0, 13.0, 11.0, 12.0),
        bar_ohlc(12.0, 16.0, 12.0, 15.0),
        bar_ohlc(15.0, 17.0, 14.0, 16.0),
        bar_ohlc(16.0, 14.0, 8.0, 9.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(
        &result.plots[0].values[2..],
        &[
            75.0,
            83.33333333333333,
            83.33333333333333,
            11.11111111111111,
        ],
    );
    assert_values_close(&result.plots[1].values, &[1.0, 1.0, 1.0, 1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[2].values, &[1.0, 1.0, 1.0, 1.0, 1.0, 1.0]);
}

#[test]
fn runs_wpr_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("wpr")
value = ta.wpr(3)
invalid = ta.wpr(0)
plot(value)
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
        bar_ohlc(10.0, 11.0, 9.0, 10.0),
        bar_ohlc(10.0, 12.0, 10.0, 11.0),
        bar_ohlc(11.0, 13.0, 11.0, 12.0),
        bar_ohlc(12.0, 16.0, 12.0, 15.0),
        bar_ohlc(15.0, 17.0, 14.0, 16.0),
        bar_ohlc(16.0, 14.0, 8.0, 9.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(
        &result.plots[0].values[2..],
        &[
            -25.0,
            -16.666666666666668,
            -16.666666666666668,
            -88.88888888888889,
        ],
    );
    assert_values_close(&result.plots[1].values, &[1.0, 1.0, 1.0, 1.0, 1.0, 1.0]);

    let source = SourceFile::new(
        "test.pine",
        r#"indicator("flat wpr")
plot(na(ta.wpr(2)) ? 1 : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar_ohlc(1.0, 1.0, 1.0, 1.0), bar_ohlc(1.0, 1.0, 1.0, 1.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_values_close(&result.plots[0].values, &[1.0, 1.0]);
}

#[test]
fn runs_ao_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("ao")
value = ta.ao()
plot(value)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars: Vec<_> = (1..=40).map(|value| bar(value as f64)).collect();
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 1);
    for value in &result.plots[0].values[..33] {
        assert_eq!(*value, PineValue::Na);
    }
    assert_values_close(
        &result.plots[0].values[33..],
        &[14.5, 14.5, 14.5, 14.5, 14.5, 14.5, 14.5],
    );
}

#[test]
fn runs_bop_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("bop")
value = ta.bop()
plot(value)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        bar_ohlc(10.0, 12.0, 8.0, 11.0),
        bar_ohlc(10.0, 13.0, 9.0, 9.0),
        bar_ohlc(10.0, 10.0, 10.0, 10.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 1);
    assert_values_close(&result.plots[0].values[..2], &[0.25, -0.25]);
    assert_eq!(result.plots[0].values[2], PineValue::Na);
}

#[test]
fn runs_sar_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("sar")
sar = ta.sar(0.02, 0.02, 0.2)
plot(sar)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert_builtin_series_history(&hir, "high", 2);
    assert_builtin_series_history(&hir, "low", 2);
    assert_builtin_series_history(&hir, "close", 1);

    let bars = vec![
        bar_ohlc(10.0, 11.0, 9.0, 10.0),
        bar_ohlc(10.0, 12.0, 10.0, 11.0),
        bar_ohlc(11.0, 13.0, 11.0, 12.0),
        bar_ohlc(12.0, 16.0, 12.0, 15.0),
        bar_ohlc(15.0, 17.0, 14.0, 16.0),
        bar_ohlc(16.0, 14.0, 8.0, 9.0),
        bar_ohlc(9.0, 10.0, 6.0, 7.0),
        bar_ohlc(7.0, 8.0, 4.0, 5.0),
        bar_ohlc(5.0, 7.0, 3.0, 6.0),
        bar_ohlc(6.0, 12.0, 5.0, 11.0),
    ];
    let result = run_historical(&hir, &bars).expect("runtime result");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(
        &result.plots[0].values[1..],
        &[
            9.0, 9.0, 9.16, 9.5704, 17.0, 17.0, 16.56, 15.8064, 14.781888,
        ],
    );
}

fn assert_builtin_series_history(
    hir: &pine_ir::HirProgram,
    symbol_name: &str,
    expected_offset: u32,
) {
    let series_id = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == symbol_name)
        .and_then(|symbol| symbol.series_id)
        .unwrap_or_else(|| panic!("{symbol_name} should have a series id"));
    let requirement = hir
        .series_history
        .iter()
        .find(|requirement| requirement.series_id == series_id)
        .unwrap_or_else(|| panic!("{symbol_name} should have a history requirement"));

    assert_eq!(
        requirement.max_constant_offset, expected_offset,
        "{symbol_name} history requirement: {:?}",
        requirement
    );
    assert!(
        !requirement.has_dynamic_offsets,
        "{symbol_name} history requirement: {:?}",
        requirement
    );
}
