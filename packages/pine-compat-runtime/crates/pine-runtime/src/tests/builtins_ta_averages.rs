use pine_syntax::SourceFile;

use super::*;

#[test]
fn runs_sma_plot_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("SMA")
ma = ta.sma(close, 3)
plot(ma)
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

    assert_eq!(result.plots.len(), 1);
    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Float(2.0),
            PineValue::Float(3.0),
        ]
    );
}

#[test]
fn runs_sma_with_computed_integer_length() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("SMA computed length")
n = 2
ma = ta.sma(close, n * 1)
plot(ma)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(4.0), bar(8.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(&result.plots[0].values[1..], &[1.5, 3.0, 6.0]);
}

#[test]
fn runs_ema_plot_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("EMA")
ma = ta.ema(close, 3)
plot(ma)
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

    assert_eq!(
        result.plots[0].values,
        vec![
            PineValue::Float(1.0),
            PineValue::Float(1.5),
            PineValue::Float(2.25),
            PineValue::Float(3.125),
        ]
    );
}

#[test]
fn runs_dema_tema_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("DEMA TEMA")
dema = ta.dema(close, 3)
tema = ta.tema(close, 3)
invalid = ta.dema(close, 0)
plot(dema)
plot(tema)
plot(invalid)
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

    assert_values_close(&result.plots[0].values, &[1.0, 1.75, 2.75, 3.8125]);
    assert_values_close(&result.plots[1].values, &[1.0, 1.875, 2.9375, 4.0]);
    assert_eq!(result.plots[2].values, vec![PineValue::Na; 4]);
}

#[test]
fn runs_rma_plot_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("RMA")
ma = ta.rma(close, 3)
plot(ma)
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

    assert_values_close(
        &result.plots[0].values,
        &[
            1.0,
            1.3333333333333333,
            1.8888888888888888,
            2.5925925925925926,
        ],
    );
}

#[test]
fn runs_rsi_plot_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("RSI")
r = ta.rsi(close, 3)
plot(r)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(2.0), bar(4.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(
        &result.plots[0].values[1..],
        &[100.0, 100.0, 66.66666666666666, 83.33333333333333],
    );
}

#[test]
fn runs_macd_tuple_assignment() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("MACD")
[macd, signal, hist] = ta.macd(close, 2, 3, 2)
plot(macd)
plot(signal)
plot(hist)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 3);
    assert_values_close(
        &result.plots[0].values,
        &[0.0, 0.16666666666666674, 0.30555555555555536],
    );
    assert_values_close(
        &result.plots[1].values,
        &[0.0, 0.11111111111111116, 0.24074074074074063],
    );
    assert_values_close(
        &result.plots[2].values,
        &[0.0, 0.05555555555555558, 0.06481481481481474],
    );
}

#[test]
fn runs_bollinger_bands_tuple_assignment() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("BB")
[basis, upper, lower] = ta.bb(close, 3, 2)
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

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 3);
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(&result.plots[0].values[2..], &[2.0, 3.0]);
    assert_values_close(
        &result.plots[1].values[2..],
        &[3.632993161855452, 4.6329931618554525],
    );
    assert_values_close(
        &result.plots[2].values[2..],
        &[0.36700683814454793, 1.367006838144548],
    );
}

#[test]
fn runs_bollinger_band_width_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("BB Width")
width = ta.bbw(close, 3, 2)
zero_basis = ta.bbw(close - close, 3, 2)
invalid = ta.bbw(close, 0, 2)
plot(width)
plot(na(zero_basis) ? 1 : 0)
plot(na(invalid) ? 1 : 0)
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
        &[1.632993161855452, 1.4966629547095767],
    );
    assert_values_close(&result.plots[1].values, &[1.0, 1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[2].values, &[1.0, 1.0, 1.0, 1.0]);
}

#[test]
fn runs_keltner_channels_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("KC")
[middle, upper, lower] = ta.kc(close, 2, 2)
[middle_plain, upper_plain, lower_plain] = ta.kc(close, 2, 2, false)
[invalid_middle, invalid_upper, invalid_lower] = ta.kc(close, 0, 2)
plot(middle)
plot(upper)
plot(lower)
plot(upper_plain)
plot(lower_plain)
plot(na(invalid_upper) ? 1 : 0)
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
        bar_ohlc(12.0, 15.0, 14.0, 12.0),
        bar_ohlc(9.0, 10.0, 8.0, 9.0),
    ];
    let result = run_historical(&hir, &bars).expect("runtime result");

    assert_values_close(
        &result.plots[0].values,
        &[10.0, 11.333333333333332, 9.777777777777779],
    );
    assert_values_close(
        &result.plots[1].values,
        &[14.0, 19.333333333333332, 17.77777777777778],
    );
    assert_values_close(
        &result.plots[2].values,
        &[6.0, 3.333333333333332, 1.7777777777777786],
    );
    assert_values_close(&result.plots[3].values, &[14.0, 14.0, 13.333333333333334]);
    assert_values_close(
        &result.plots[4].values,
        &[6.0, 8.666666666666666, 6.222222222222223],
    );
    assert_values_close(&result.plots[5].values, &[1.0, 1.0, 1.0]);
}

#[test]
fn runs_keltner_channel_width_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("KCW")
width = ta.kcw(close, 2, 2)
plain_width = ta.kcw(close, 2, 2, false)
zero_basis = ta.kcw(close - close, 2, 2)
invalid = ta.kcw(close, 0, 2)
plot(width)
plot(plain_width)
plot(na(zero_basis) ? 1 : 0)
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
        bar_ohlc(10.0, 11.0, 9.0, 10.0),
        bar_ohlc(12.0, 15.0, 14.0, 12.0),
        bar_ohlc(9.0, 10.0, 8.0, 9.0),
    ];
    let result = run_historical(&hir, &bars).expect("runtime result");

    assert_values_close(
        &result.plots[0].values,
        &[0.8, 1.411764705882353, 1.6363636363636362],
    );
    assert_values_close(
        &result.plots[1].values,
        &[0.8, 0.4705882352941177, 0.7272727272727272],
    );
    assert_values_close(&result.plots[2].values, &[1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[3].values, &[1.0, 1.0, 1.0]);
}

#[test]
fn runs_wma_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("wma")
value = ta.wma(close, 3)
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
        &[2.8333333333333335, 5.166666666666667],
    );
}

#[test]
fn runs_hma_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("hma")
value = ta.hma(close, 4)
plot(value)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(4.0), bar(7.0), bar(11.0), bar(16.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_eq!(result.plots[0].values[2], PineValue::Na);
    assert_eq!(result.plots[0].values[3], PineValue::Na);
    assert_values_close(
        &result.plots[0].values[4..],
        &[10.38888888888889, 15.38888888888889],
    );
}

#[test]
fn runs_swma_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("swma")
value = ta.swma(close)
with_na = ta.swma(bar_index == 4 ? na : close)
plot(value)
plot(with_na)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(4.0), bar(8.0), bar(16.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_eq!(result.plots[0].values[2], PineValue::Na);
    assert_values_close(&result.plots[0].values[3..], &[3.5, 7.0]);
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_eq!(result.plots[1].values[2], PineValue::Na);
    assert_values_close(&result.plots[1].values[3..4], &[3.5]);
    assert_eq!(result.plots[1].values[4], PineValue::Na);
}

#[test]
fn runs_alma_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("alma")
value = ta.alma(close, 4, 0.85, 6)
floored = ta.alma(close, 4, 0.85, 6, true)
with_na = ta.alma(bar_index == 4 ? na : close, 4, 0.85, 6)
invalid = ta.alma(close, 4, 0.85, 0)
plot(value)
plot(floored)
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

    let bars = vec![bar(1.0), bar(2.0), bar(4.0), bar(8.0), bar(16.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_eq!(result.plots[0].values[2], PineValue::Na);
    assert_values_close(
        &result.plots[0].values[3..],
        &[5.935295490253145, 11.87059098050629],
    );
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_eq!(result.plots[1].values[2], PineValue::Na);
    assert_values_close(
        &result.plots[1].values[3..],
        &[4.370978545474149, 8.741957090948299],
    );
    assert_eq!(result.plots[2].values[0], PineValue::Na);
    assert_eq!(result.plots[2].values[1], PineValue::Na);
    assert_eq!(result.plots[2].values[2], PineValue::Na);
    assert_values_close(&result.plots[2].values[3..4], &[5.935295490253145]);
    assert_eq!(result.plots[2].values[4], PineValue::Na);
    assert_eq!(result.plots[3].values[0], PineValue::Na);
    assert_eq!(result.plots[3].values[1], PineValue::Na);
    assert_eq!(result.plots[3].values[2], PineValue::Na);
    assert_eq!(result.plots[3].values[3], PineValue::Na);
    assert_eq!(result.plots[3].values[4], PineValue::Na);
}

#[test]
fn runs_linreg_over_historical_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("linreg")
current = ta.linreg(close, 3, 0)
previous = ta.linreg(close, 3, 1)
projected = ta.linreg(close, 3, -1)
single = ta.linreg(close, 1, 0)
with_na = ta.linreg(bar_index == 3 ? na : close, 3, 0)
invalid = ta.linreg(close, 0, 0)
plot(current)
plot(previous)
plot(projected)
plot(single)
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

    let bars = vec![bar(1.0), bar(2.0), bar(4.0), bar(8.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(
        &result.plots[0].values[2..],
        &[3.8333333333333335, 7.666666666666667],
    );
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_values_close(
        &result.plots[1].values[2..],
        &[2.3333333333333335, 4.666666666666667],
    );
    assert_eq!(result.plots[2].values[0], PineValue::Na);
    assert_eq!(result.plots[2].values[1], PineValue::Na);
    assert_values_close(
        &result.plots[2].values[2..],
        &[5.333333333333334, 10.666666666666668],
    );
    assert_values_close(&result.plots[3].values, &[1.0, 2.0, 4.0, 8.0]);
    assert_eq!(result.plots[4].values[0], PineValue::Na);
    assert_eq!(result.plots[4].values[1], PineValue::Na);
    assert_values_close(&result.plots[4].values[2..3], &[3.8333333333333335]);
    assert_eq!(result.plots[4].values[3], PineValue::Na);
    assert_eq!(result.plots[5].values[0], PineValue::Na);
    assert_eq!(result.plots[5].values[1], PineValue::Na);
    assert_eq!(result.plots[5].values[2], PineValue::Na);
    assert_eq!(result.plots[5].values[3], PineValue::Na);
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
