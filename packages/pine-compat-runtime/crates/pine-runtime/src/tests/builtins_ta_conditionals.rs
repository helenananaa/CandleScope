use pine_sema::analyze_source;
use pine_syntax::SourceFile;

use super::*;

#[test]
fn advances_conditional_sma_only_when_branch_executes() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("conditional sma")
ma = close
if close > open
    ma := ta.sma(close, 2)
plot(ma)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        bar_ohlc(1.0, 2.0, 1.0, 2.0),
        bar_ohlc(3.0, 3.0, 2.0, 2.0),
        bar_ohlc(4.0, 6.0, 4.0, 6.0),
        bar_ohlc(5.0, 8.0, 5.0, 8.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 1);
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(&result.plots[0].values[1..], &[2.0, 4.0, 7.0]);
}

#[test]
fn advances_conditional_ema_only_when_branch_executes() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("conditional ema")
e = close
if close > open
    e := ta.ema(close, 2)
plot(e)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        bar_ohlc(1.0, 2.0, 1.0, 2.0),
        bar_ohlc(3.0, 3.0, 2.0, 2.0),
        bar_ohlc(4.0, 6.0, 4.0, 6.0),
        bar_ohlc(5.0, 8.0, 5.0, 8.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 1);
    assert_values_close(
        &result.plots[0].values,
        &[2.0, 2.0, 4.666666666666667, 6.888888888888889],
    );
}

#[test]
fn advances_conditional_dema_tema_only_when_branch_executes() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("conditional dema tema")
d = close
t = close
if close > open
    d := ta.dema(close, 2)
    t := ta.tema(close, 2)
plot(d)
plot(t)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        bar_ohlc(1.0, 2.0, 1.0, 2.0),
        bar_ohlc(3.0, 3.0, 2.0, 2.0),
        bar_ohlc(4.0, 6.0, 4.0, 6.0),
        bar_ohlc(5.0, 8.0, 5.0, 8.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_values_close(
        &result.plots[0].values,
        &[2.0, 2.0, 5.555555555555555, 7.925925925925926],
    );
    assert_values_close(
        &result.plots[1].values,
        &[2.0, 2.0, 5.851851851851852, 8.074074074074074],
    );
}

#[test]
fn advances_conditional_vwap_anchor_only_when_branch_executes() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("conditional anchored vwap")
score = close
if close > open
    score := ta.vwap(close, bar_index == 2)
plot(score)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        bar_ohlcv(0.0, 10.0, 10.0, 10.0, 1.0),
        bar_ohlcv(30.0, 20.0, 20.0, 20.0, 100.0),
        bar_ohlcv(0.0, 30.0, 30.0, 30.0, 1.0),
        bar_ohlcv(0.0, 40.0, 40.0, 40.0, 1.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 1);
    assert_values_close(&result.plots[0].values, &[10.0, 20.0, 30.0, 35.0]);
}

#[test]
fn advances_conditional_kc_only_when_branch_executes() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("conditional kc")
score = close
if close > open
    [middle, upper, lower] = ta.kc(close, 2, 2)
    score := upper
plot(score)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        bar_ohlc(0.0, 11.0, 9.0, 10.0),
        bar_ohlc(13.0, 15.0, 14.0, 12.0),
        bar_ohlc(0.0, 10.0, 8.0, 9.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 1);
    assert_values_close(&result.plots[0].values, &[14.0, 12.0, 16.0]);
}

#[test]
fn advances_conditional_kcw_only_when_branch_executes() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("conditional kcw")
score = close
if close > open
    score := ta.kcw(close, 2, 2)
plot(score)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        bar_ohlc(0.0, 11.0, 9.0, 10.0),
        bar_ohlc(13.0, 15.0, 14.0, 12.0),
        bar_ohlc(0.0, 10.0, 8.0, 9.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 1);
    assert_values_close(&result.plots[0].values, &[0.8, 12.0, 1.4285714285714286]);
}

#[test]
fn advances_conditional_pivot_only_when_branch_executes() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("conditional pivot")
score = close
if close > open
    score := ta.pivothigh(close, 1, 1)
plot(score)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        bar_ohlc(0.0, 1.0, 1.0, 1.0),
        bar_ohlc(5.0, 2.0, 2.0, 2.0),
        bar_ohlc(0.0, 3.0, 3.0, 3.0),
        bar_ohlc(0.0, 2.0, 2.0, 2.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 1);
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(&result.plots[0].values[1..2], &[2.0]);
    assert_eq!(result.plots[0].values[2], PineValue::Na);
    assert_values_close(&result.plots[0].values[3..], &[3.0]);
}

#[test]
fn advances_conditional_rsi_only_when_branch_executes() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("conditional rsi")
r = close
if close > open
    r := ta.rsi(close, 2)
plot(r)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        bar_ohlc(1.0, 2.0, 1.0, 2.0),
        bar_ohlc(3.0, 3.0, 2.0, 2.0),
        bar_ohlc(4.0, 6.0, 4.0, 6.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 1);
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(&result.plots[0].values[1..], &[2.0, 100.0]);
}

#[test]
fn advances_conditional_atr_only_when_branch_executes() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("conditional atr")
a = close
if close > open
    a := ta.atr(2)
plot(a)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        bar_ohlc(1.0, 2.0, 1.0, 2.0),
        bar_ohlc(3.0, 3.0, 2.0, 2.0),
        bar_ohlc(4.0, 6.0, 4.0, 6.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 1);
    assert_values_close(&result.plots[0].values, &[1.0, 2.0, 2.5]);
}

#[test]
fn advances_conditional_dmi_only_when_branch_executes() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("conditional dmi")
score = close
if close > open
    [plus, minus, adx] = ta.dmi(3, 2)
    score := plus + minus + adx
plot(score)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        bar_ohlc(1.0, 2.0, 1.0, 2.0),
        bar_ohlc(3.0, 3.0, 2.0, 2.0),
        bar_ohlc(4.0, 6.0, 4.0, 6.0),
        bar_ohlc(5.0, 8.0, 5.0, 8.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 1);
    assert_values_close(
        &result.plots[0].values,
        &[0.0, 2.0, 100.0, 132.14285714285714],
    );
}

#[test]
fn advances_conditional_stoch_only_when_branch_executes() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("conditional stoch")
score = close
if close > open
    score := ta.stoch(close, high, low, 2)
plot(score)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        bar_ohlc(1.0, 10.0, 0.0, 5.0),
        bar_ohlc(3.0, 100.0, 100.0, 2.0),
        bar_ohlc(4.0, 20.0, 10.0, 15.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 1);
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(&result.plots[0].values[1..], &[2.0, 75.0]);
}

#[test]
fn advances_conditional_wpr_only_when_branch_executes() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("conditional wpr")
score = close
if close > open
    score := ta.wpr(2)
plot(score)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        bar_ohlc(1.0, 10.0, 0.0, 5.0),
        bar_ohlc(3.0, 100.0, 100.0, 2.0),
        bar_ohlc(4.0, 20.0, 10.0, 15.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 1);
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(&result.plots[0].values[1..], &[2.0, -25.0]);
}

#[test]
fn advances_conditional_ao_only_when_branch_executes() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("conditional ao")
score = close
if close > open
    score := ta.ao()
plot(score)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars: Vec<_> = (1..=35)
        .map(|value| {
            if value == 11 {
                bar_ohlc(2.0, 2.0, 2.0, 1.0)
            } else {
                let value = value as f64;
                bar_ohlc(0.0, value, value, value)
            }
        })
        .collect();
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 1);
    for value in &result.plots[0].values[..10] {
        assert_eq!(*value, PineValue::Na);
    }
    assert_values_close(&result.plots[0].values[10..11], &[1.0]);
    for value in &result.plots[0].values[11..34] {
        assert_eq!(*value, PineValue::Na);
    }
    assert_values_close(&result.plots[0].values[34..], &[14.794117647058822]);
}

#[test]
fn advances_conditional_sar_only_when_branch_executes() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("conditional sar")
score = close
if close > open
    score := ta.sar(0.02, 0.02, 0.2)
plot(score)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        bar_ohlc(1.0, 10.0, 1.0, 5.0),
        bar_ohlc(3.0, 4.0, 1.0, 2.0),
        bar_ohlc(4.0, 20.0, 10.0, 15.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 1);
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(&result.plots[0].values[1..], &[2.0, 1.0]);
}

#[test]
fn advances_conditional_mfi_only_when_branch_executes() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("conditional mfi")
score = close
if close > open
    score := ta.mfi(close, 2)
plot(score)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        bar_ohlcv(1.0, 10.0, 1.0, 5.0, 10.0),
        bar_ohlcv(3.0, 4.0, 1.0, 2.0, 10.0),
        bar_ohlcv(4.0, 20.0, 10.0, 15.0, 10.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 1);
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(&result.plots[0].values[1..], &[2.0, 100.0]);
}

#[test]
fn advances_conditional_tsi_only_when_branch_executes() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("conditional tsi")
score = close
if close > open
    score := ta.tsi(close, 2, 3)
plot(score)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        bar_ohlc(1.0, 10.0, 1.0, 5.0),
        bar_ohlc(3.0, 4.0, 1.0, 2.0),
        bar_ohlc(4.0, 20.0, 10.0, 15.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 1);
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(&result.plots[0].values[1..], &[2.0, 1.0]);
}

#[test]
fn advances_conditional_cmo_only_when_branch_executes() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("conditional cmo")
score = close
if close > open
    score := ta.cmo(close, 1)
plot(score)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        bar_ohlc(1.0, 10.0, 1.0, 5.0),
        bar_ohlc(3.0, 4.0, 1.0, 2.0),
        bar_ohlc(4.0, 20.0, 10.0, 15.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 1);
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(&result.plots[0].values[1..], &[2.0, 100.0]);
}

#[test]
fn advances_conditional_cci_only_when_branch_executes() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("conditional cci")
score = close
if close > open
    score := ta.cci(close, 3)
plot(score)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        bar_ohlc(0.0, 1.0, 1.0, 1.0),
        bar_ohlc(3.0, 2.0, 2.0, 2.0),
        bar_ohlc(0.0, 3.0, 3.0, 3.0),
        bar_ohlc(0.0, 4.0, 4.0, 4.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 1);
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(&result.plots[0].values[1..2], &[2.0]);
    assert_eq!(result.plots[0].values[2], PineValue::Na);
    assert_values_close(&result.plots[0].values[3..], &[80.0]);
}

#[test]
fn advances_conditional_cog_only_when_branch_executes() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("conditional cog")
score = close
if close > open
    score := ta.cog(close, 3)
plot(score)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        bar_ohlc(0.0, 1.0, 1.0, 1.0),
        bar_ohlc(3.0, 2.0, 2.0, 2.0),
        bar_ohlc(0.0, 3.0, 3.0, 3.0),
        bar_ohlc(0.0, 4.0, 4.0, 4.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 1);
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(&result.plots[0].values[1..2], &[2.0]);
    assert_eq!(result.plots[0].values[2], PineValue::Na);
    assert_values_close(&result.plots[0].values[3..], &[-1.625]);
}

#[test]
fn advances_conditional_macd_only_when_branch_executes() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("conditional macd")
if close > open
    [macd, signal, hist] = ta.macd(close, 2, 3, 2)
    plot(macd)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        bar_ohlc(1.0, 2.0, 1.0, 2.0),
        bar_ohlc(3.0, 3.0, 2.0, 2.0),
        bar_ohlc(4.0, 6.0, 4.0, 6.0),
        bar_ohlc(5.0, 8.0, 5.0, 8.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 1);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(
        &[
            result.plots[0].values[0].clone(),
            result.plots[0].values[2].clone(),
            result.plots[0].values[3].clone(),
        ],
        &[0.0, 0.666666666666667, 0.8888888888888893],
    );
}

#[test]
fn runs_function_with_ta_call() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("udf sma")
smooth(src, len) => ta.sma(src, len)
plot(smooth(close, 2))
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
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(&result.plots[0].values[1..], &[1.5, 2.5, 3.5]);
}

#[test]
fn runs_block_body_function_with_ta_call() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("udf block ta")
smooth2(src, len) =>
    ma = ta.sma(src, len)
    ma * 2
plot(smooth2(close, 2))
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
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(&result.plots[0].values[1..], &[3.0, 5.0, 7.0]);
}
