use std::sync::Arc;

use pine_syntax::SourceFile;

use super::*;

fn runtime_program() -> pine_ir::HirProgram {
    compile_program("indicator(\"request scaffold\")\nplot(close)\n")
}

fn compile_program(text: &str) -> pine_ir::HirProgram {
    let source = SourceFile::new("test.pine", text);
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    analysis.hir.expect("HIR")
}

fn timed_bar(time: i64, close: f64) -> Bar {
    Bar {
        time,
        open: close,
        high: close,
        low: close,
        close,
        volume: 1.0,
    }
}

fn timed_ohlcv(time: i64, open: f64, high: f64, low: f64, close: f64, volume: f64) -> Bar {
    Bar {
        time,
        open,
        high,
        low,
        close,
        volume,
    }
}

fn custom_environment() -> RequestEnvironment {
    let timeframe = RequestTimeframe::parse("D").expect("daily timeframe");
    let chart = ChartContext::new("NYSE:IBM", timeframe.clone());
    let key = RequestKey::new("NASDAQ:AAPL", timeframe);
    let provider = InMemoryRequestDataProvider::from_streams([(key, vec![timed_bar(0, 10.0)])])
        .expect("valid request bars");
    RequestEnvironment::new(chart, Arc::new(provider))
}

fn external_symbol_environment(symbol: &str, bars: Vec<Bar>) -> RequestEnvironment {
    let key = RequestKey::new(symbol, RequestTimeframe::default());
    let provider =
        InMemoryRequestDataProvider::from_streams([(key, bars)]).expect("valid request bars");
    RequestEnvironment::new(ChartContext::default(), Arc::new(provider))
}

fn external_symbol_environment_with_timeframe(
    symbol: &str,
    timeframe: &str,
    bars: Vec<Bar>,
) -> RequestEnvironment {
    let key = RequestKey::new(
        symbol,
        RequestTimeframe::parse(timeframe).expect("request timeframe"),
    );
    let provider =
        InMemoryRequestDataProvider::from_streams([(key, bars)]).expect("valid request bars");
    RequestEnvironment::new(ChartContext::default(), Arc::new(provider))
}

fn external_symbol_environment_with_chart_timeframe(
    symbol: &str,
    requested_timeframe: &str,
    chart_timeframe: &str,
    bars: Vec<Bar>,
) -> RequestEnvironment {
    let key = RequestKey::new(
        symbol,
        RequestTimeframe::parse(requested_timeframe).expect("request timeframe"),
    );
    let provider =
        InMemoryRequestDataProvider::from_streams([(key, bars)]).expect("valid request bars");
    RequestEnvironment::new(
        ChartContext::new(
            "NASDAQ:AAPL",
            RequestTimeframe::parse(chart_timeframe).expect("chart timeframe"),
        ),
        Arc::new(provider),
    )
}

#[test]
fn request_timeframe_parses_supported_subset() {
    let default = RequestTimeframe::parse("").expect("default timeframe");
    assert_eq!(default.value(), "1");
    assert_eq!(default.seconds(), 60);

    let daily = RequestTimeframe::parse("D").expect("daily timeframe");
    assert_eq!(daily.value(), "D");
    assert_eq!(daily.seconds(), 86_400);

    let error = RequestTimeframe::parse("1H").expect_err("unsupported timeframe");
    assert_eq!(error.value(), "1H");
    assert_eq!(error.to_string(), "unsupported request timeframe `1H`");
}

#[test]
fn validates_duplicate_and_unsorted_requested_bars() {
    let duplicate = validate_requested_bars(&[timed_bar(1, 1.0), timed_bar(1, 2.0)])
        .expect_err("duplicate bar time should fail");
    assert_eq!(duplicate.to_string(), "duplicate requested bar time `1`");

    let unsorted = validate_requested_bars(&[timed_bar(2, 1.0), timed_bar(1, 2.0)])
        .expect_err("unsorted bar time should fail");
    assert_eq!(
        unsorted.to_string(),
        "requested bars are not sorted: `1` follows `2`"
    );
}

#[test]
fn default_request_environment_has_chart_metadata_and_no_data_provider() {
    let environment = RequestEnvironment::default();
    assert_eq!(environment.chart().symbol(), "NASDAQ:AAPL");
    assert_eq!(environment.chart().timeframe().value(), "1");

    let key = RequestKey::new("NASDAQ:AAPL", RequestTimeframe::default());
    let error = environment
        .provider()
        .bars(&key)
        .expect_err("default provider has no requested data");
    assert_eq!(
        error.to_string(),
        "missing request data for symbol `NASDAQ:AAPL` timeframe `1`"
    );
}

#[test]
fn in_memory_provider_validates_and_returns_requested_bars() {
    let key = RequestKey::new(
        "NYSE:IBM",
        RequestTimeframe::parse("D").expect("daily timeframe"),
    );
    let bars = vec![timed_bar(0, 10.0), timed_bar(86_400_000, 11.0)];
    let provider = InMemoryRequestDataProvider::from_streams([(key.clone(), bars.clone())])
        .expect("valid request bars");

    assert_eq!(
        provider.bars(&key).expect("requested bars"),
        bars.as_slice()
    );
}

#[test]
fn in_memory_provider_rejects_duplicate_request_keys() {
    let key = RequestKey::new(
        "NYSE:IBM",
        RequestTimeframe::parse("D").expect("daily timeframe"),
    );
    let error = InMemoryRequestDataProvider::from_streams([
        (key.clone(), vec![timed_bar(0, 10.0)]),
        (key, vec![timed_bar(86_400_000, 11.0)]),
    ])
    .expect_err("duplicate request key should fail");

    assert_eq!(
        error.to_string(),
        "duplicate request data for symbol `NYSE:IBM` timeframe `D`"
    );
}

#[test]
fn historical_runtime_accepts_custom_request_environment_without_changing_run_behavior() {
    let program = runtime_program();
    let runtime = HistoricalRuntime::with_request_environment(&program, custom_environment());

    assert_eq!(runtime.request_environment().chart().symbol(), "NYSE:IBM");
    assert_eq!(
        runtime.request_environment().chart().timeframe().value(),
        "D"
    );

    let result = runtime.run(&[timed_bar(0, 5.0)]).expect("runtime result");
    assert_eq!(result.plots[0].values, vec![PineValue::Float(5.0)]);
}

#[test]
fn realtime_runtime_carries_custom_request_environment_through_rollback() {
    let program = runtime_program();
    let mut runtime = RealtimeRuntime::with_request_environment(&program, custom_environment());

    assert_eq!(runtime.request_environment().chart().symbol(), "NYSE:IBM");

    runtime
        .update(BarUpdate::historical(timed_bar(0, 1.0)))
        .expect("historical update");
    runtime
        .update(BarUpdate::forming(timed_bar(60_000, 2.0)))
        .expect("forming update");
    assert_eq!(runtime.request_environment().chart().symbol(), "NYSE:IBM");

    runtime
        .update(BarUpdate::forming(timed_bar(60_000, 3.0)))
        .expect("second forming update");
    assert_eq!(
        runtime.request_environment().chart().timeframe().value(),
        "D"
    );
}

#[test]
fn request_security_same_context_returns_expression_series() {
    let program = compile_program(
        "indicator(\"request identity\")\nplot(request.security(syminfo.tickerid, timeframe.period, close + open))\n",
    );
    let result = run_historical(
        &program,
        &[bar_ohlc(1.0, 2.0, 0.5, 4.0), bar_ohlc(3.0, 5.0, 2.0, 8.0)],
    )
    .expect("same-context request.security should run");

    assert_values_close(&result.plots[0].values, &[5.0, 11.0]);
}

#[test]
fn request_security_same_context_returns_tuple_literal_expression() {
    let program = compile_program(
        "indicator(\"request tuple literal\")\n[last, spread, above] = request.security(syminfo.tickerid, timeframe.period, [close, high - low, close > open ? 1 : 0])\nplot(last)\nplot(spread)\nplot(above)\n",
    );
    let result = run_historical(
        &program,
        &[
            bar_ohlc(1.0, 2.0, 0.5, 4.0),
            bar_ohlc(5.0, 8.0, 3.0, 2.0),
            bar_ohlc(3.0, 7.0, 1.0, 9.0),
        ],
    )
    .expect("same-context tuple literal request.security expression should run");

    assert_eq!(result.plots.len(), 3);
    assert_values_close(&result.plots[0].values, &[4.0, 2.0, 9.0]);
    assert_values_close(&result.plots[1].values, &[1.5, 5.0, 6.0]);
    assert_values_close(&result.plots[2].values, &[1.0, 0.0, 1.0]);
}

#[test]
fn request_security_same_context_returns_tuple_expression() {
    let program = compile_program(
        "indicator(\"request tuple\")\n[macd, signal, hist] = request.security(syminfo.tickerid, timeframe.period, ta.macd(close, 2, 3, 2))\nplot(macd)\nplot(signal)\nplot(hist)\n",
    );
    let result = run_historical(&program, &[bar(1.0), bar(2.0), bar(3.0)])
        .expect("same-context tuple request.security expression should run");

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
fn request_security_same_context_returns_bb_tuple_expression() {
    let program = compile_program(
        "indicator(\"request bb tuple\")\n[basis, upper, lower] = request.security(syminfo.tickerid, timeframe.period, ta.bb(close, 3, 2))\nplot(basis)\nplot(upper)\nplot(lower)\n",
    );
    let result = run_historical(&program, &[bar(1.0), bar(2.0), bar(3.0), bar(4.0)])
        .expect("same-context ta.bb tuple request.security expression should run");

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
fn request_security_same_context_returns_kc_tuple_expression() {
    let program = compile_program(
        "indicator(\"request kc tuple\")\n[middle, upper, lower] = request.security(syminfo.tickerid, timeframe.period, ta.kc(close, 2, 2))\nplot(middle)\nplot(upper)\nplot(lower)\n",
    );
    let result = run_historical(
        &program,
        &[
            timed_ohlcv(0, 10.0, 11.0, 9.0, 10.0, 1.0),
            timed_ohlcv(60_000, 12.0, 15.0, 14.0, 12.0, 1.0),
            timed_ohlcv(120_000, 9.0, 10.0, 8.0, 9.0, 1.0),
        ],
    )
    .expect("same-context ta.kc tuple request.security expression should run");

    assert_eq!(result.plots.len(), 3);
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
}

#[test]
fn request_security_same_context_returns_supertrend_tuple_expression() {
    let program = compile_program(
        "indicator(\"request supertrend tuple\")\n[line, direction] = request.security(syminfo.tickerid, timeframe.period, ta.supertrend(2, 3))\nplot(line)\nplot(direction)\n",
    );
    let result = run_historical(
        &program,
        &[
            timed_ohlcv(0, 10.0, 11.0, 9.0, 10.0, 1.0),
            timed_ohlcv(60_000, 10.0, 12.0, 10.0, 11.0, 1.0),
            timed_ohlcv(120_000, 11.0, 13.0, 11.0, 12.0, 1.0),
            timed_ohlcv(180_000, 12.0, 16.0, 12.0, 15.0, 1.0),
            timed_ohlcv(240_000, 15.0, 17.0, 14.0, 16.0, 1.0),
            timed_ohlcv(300_000, 16.0, 14.0, 8.0, 9.0, 1.0),
        ],
    )
    .expect("same-context ta.supertrend tuple request.security expression should run");

    assert_eq!(result.plots.len(), 2);
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
}

#[test]
fn request_security_same_context_returns_dmi_tuple_expression() {
    let program = compile_program(
        "indicator(\"request dmi tuple\")\n[plus, minus, adx] = request.security(syminfo.tickerid, timeframe.period, ta.dmi(3, 2))\nplot(plus)\nplot(minus)\nplot(adx)\n",
    );
    let result = run_historical(
        &program,
        &[
            timed_ohlcv(0, 10.0, 11.0, 9.0, 10.0, 1.0),
            timed_ohlcv(60_000, 10.0, 12.0, 10.0, 11.0, 1.0),
            timed_ohlcv(120_000, 11.0, 13.0, 11.0, 12.0, 1.0),
            timed_ohlcv(180_000, 12.0, 16.0, 12.0, 15.0, 1.0),
            timed_ohlcv(240_000, 15.0, 17.0, 14.0, 16.0, 1.0),
            timed_ohlcv(300_000, 16.0, 14.0, 8.0, 9.0, 1.0),
        ],
    )
    .expect("same-context ta.dmi tuple request.security expression should run");

    assert_eq!(result.plots.len(), 3);
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
}

#[test]
fn request_security_same_context_returns_vwap_bands_tuple_expression() {
    let program = compile_program(
        "indicator(\"request vwap tuple\")\n[basis, upper, lower] = request.security(syminfo.tickerid, timeframe.period, ta.vwap(close, time == 0, 2.0))\nplot(basis)\nplot(upper)\nplot(lower)\n",
    );
    let result = run_historical(
        &program,
        &[
            timed_ohlcv(0, 1.0, 2.0, 0.0, 4.0, 1.0),
            timed_ohlcv(60_000, 2.0, 3.0, 1.0, 5.0, 2.0),
            timed_ohlcv(120_000, 3.0, 4.0, 2.0, 6.0, 3.0),
            timed_ohlcv(180_000, 4.0, 5.0, 3.0, 7.0, 4.0),
        ],
    )
    .expect("same-context ta.vwap bands tuple request.security expression should run");

    assert_eq!(result.plots.len(), 3);
    assert_values_close(
        &result.plots[0].values,
        &[4.0, 4.666666666666667, 5.333333333333333, 6.0],
    );
    assert_values_close(
        &result.plots[1].values,
        &[4.0, 5.60947570824873, 6.824045318333193, 8.0],
    );
    assert_values_close(
        &result.plots[2].values,
        &[4.0, 3.723857625084603, 3.842621348333472, 4.0],
    );
}

#[test]
fn request_security_same_context_supports_history_and_na_helpers() {
    let program = compile_program(
        "indicator(\"request history\")\nvalue = request.security(syminfo.tickerid, timeframe.period, na(close[1]) ? close : close[1])\nplot(value)\n",
    );
    let result = run_historical(&program, &[bar(10.0), bar(12.0), bar(15.0)])
        .expect("same-context request.security history expression should run");

    assert_values_close(&result.plots[0].values, &[10.0, 10.0, 12.0]);
}

#[test]
fn request_security_uses_runtime_chart_metadata_for_identity_check() {
    let program = compile_program(
        "indicator(\"request custom chart\")\nplot(request.security(syminfo.tickerid, timeframe.period, close))\n",
    );
    let runtime = HistoricalRuntime::with_request_environment(&program, custom_environment());
    let result = runtime
        .run(&[timed_bar(0, 9.0), timed_bar(86_400_000, 11.0)])
        .expect("custom chart metadata should satisfy same-context identity");

    assert_values_close(&result.plots[0].values, &[9.0, 11.0]);
}

#[test]
fn request_security_reads_same_timeframe_external_symbol_from_provider() {
    let program = compile_program(
        "indicator(\"request external\")\nplot(request.security(\"NYSE:IBM\", timeframe.period, close))\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![timed_bar(0, 20.0), timed_bar(60_000, 21.0)],
    );
    let runtime = HistoricalRuntime::with_request_environment(&program, environment);
    let result = runtime
        .run(&[timed_bar(0, 5.0), timed_bar(60_000, 6.0)])
        .expect("external request data should run");

    assert_values_close(&result.plots[0].values, &[20.0, 21.0]);
}

#[test]
fn request_security_same_timeframe_gaps_off_forward_fills_provider_gaps() {
    let program = compile_program(
        "indicator(\"request external gaps\")\nplot(request.security(\"NYSE:IBM\", timeframe.period, close))\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![timed_bar(0, 20.0), timed_bar(120_000, 22.0)],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 6.0),
            timed_bar(120_000, 7.0),
        ])
        .expect("default same-timeframe gaps_off should forward fill");

    assert_values_close(&result.plots[0].values, &[20.0, 20.0, 22.0]);
}

#[test]
fn request_security_evaluates_provider_arithmetic_in_requested_context() {
    let program = compile_program(
        "indicator(\"request arithmetic\")\nplot(request.security(\"NYSE:IBM\", timeframe.period, open + close))\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 100.0, 101.0, 99.0, 20.0, 1.0),
            timed_ohlcv(60_000, 110.0, 111.0, 109.0, 21.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[timed_bar(0, 5.0), timed_bar(60_000, 6.0)])
        .expect("provider arithmetic should run");

    assert_values_close(&result.plots[0].values, &[120.0, 131.0]);
}

#[test]
fn request_security_evaluates_provider_math_extremes_in_requested_context() {
    let program = compile_program(
        "indicator(\"request math extremes\")\nplot(request.security(\"NYSE:IBM\", timeframe.period, math.max(close, open) - math.min(close, open)))\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 100.0, 101.0, 99.0, 20.0, 1.0),
            timed_ohlcv(60_000, 21.0, 111.0, 19.0, 110.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[timed_bar(0, 5.0), timed_bar(60_000, 6.0)])
        .expect("provider math extremes should run");

    assert_values_close(&result.plots[0].values, &[80.0, 89.0]);
}

#[test]
fn request_security_evaluates_provider_stateless_math_calls() {
    let program = compile_program(
        "indicator(\"request stateless math\")\nplot(request.security(\"NYSE:IBM\", timeframe.period, math.abs(open - close) + math.floor(math.avg(open, close)) + math.pow(2, 2) + math.hypot(3, 4)))\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 100.0, 101.0, 99.0, 20.0, 1.0),
            timed_ohlcv(60_000, 21.0, 111.0, 19.0, 110.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[timed_bar(0, 5.0), timed_bar(60_000, 6.0)])
        .expect("provider stateless math should run");

    assert_values_close(&result.plots[0].values, &[149.0, 163.0]);
}

#[test]
fn request_security_isolates_provider_math_sum_state() {
    let program = compile_program(
        "indicator(\"request math sum\")\nprovider = request.security(\"NYSE:IBM\", timeframe.period, math.sum(close, 2))\nchart = math.sum(close, 2)\nplot(provider)\nplot(chart)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_bar(0, 20.0),
            timed_bar(60_000, 22.0),
            timed_bar(120_000, 24.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 7.0),
            timed_bar(120_000, 9.0),
        ])
        .expect("provider math.sum expression should run");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(&result.plots[0].values[1..], &[42.0, 46.0]);
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_values_close(&result.plots[1].values[1..], &[12.0, 16.0]);
}

#[test]
fn request_security_isolates_provider_cum_state() {
    let program = compile_program(
        "indicator(\"request cum\")\nprovider = request.security(\"NYSE:IBM\", timeframe.period, ta.cum(close))\nchart = ta.cum(close)\nplot(provider)\nplot(chart)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_bar(0, 20.0),
            timed_bar(60_000, 22.0),
            timed_bar(120_000, 24.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 7.0),
            timed_bar(120_000, 9.0),
        ])
        .expect("provider ta.cum expression should run");

    assert_values_close(&result.plots[0].values, &[20.0, 42.0, 66.0]);
    assert_values_close(&result.plots[1].values, &[5.0, 12.0, 21.0]);
}

#[test]
fn request_security_evaluates_provider_round_to_mintick() {
    let program = compile_program(
        "indicator(\"request mintick\")\nrounded = request.security(\"NYSE:IBM\", timeframe.period, math.round_to_mintick(close + 0.006))\nplot(rounded)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_bar(0, 20.0),
            timed_bar(60_000, 21.0),
            timed_bar(120_000, 22.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 7.0),
            timed_bar(120_000, 9.0),
        ])
        .expect("provider math.round_to_mintick expression should run");

    assert_values_close(&result.plots[0].values, &[20.01, 21.01, 22.01]);
}

#[test]
fn request_security_evaluates_provider_history_references() {
    let program = compile_program(
        "indicator(\"request history\")\nplot(request.security(\"NYSE:IBM\", timeframe.period, close[1]))\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_bar(0, 20.0),
            timed_bar(60_000, 22.0),
            timed_bar(120_000, 24.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 6.0),
            timed_bar(120_000, 7.0),
        ])
        .expect("provider history should run");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(&result.plots[0].values[1..], &[20.0, 22.0]);
}

#[test]
fn request_security_evaluates_provider_macd_tuple_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider macd tuple\")\n[macd, signal, hist] = request.security(\"NYSE:IBM\", timeframe.period, ta.macd(close, 2, 3, 2))\nplot(macd)\nplot(signal)\nplot(hist)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_bar(0, 20.0),
            timed_bar(60_000, 21.0),
            timed_bar(120_000, 22.0),
            timed_bar(180_000, 23.0),
            timed_bar(240_000, 24.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 6.0),
            timed_bar(120_000, 7.0),
            timed_bar(180_000, 8.0),
            timed_bar(240_000, 9.0),
        ])
        .expect("provider ta.macd tuple expression should run");

    assert_eq!(result.plots.len(), 3);
    assert_values_close(
        &result.plots[0].values,
        &[
            0.0,
            0.16666666666666785,
            0.30555555555555713,
            0.39351851851851904,
            0.4436728395061713,
        ],
    );
    assert_values_close(
        &result.plots[1].values,
        &[
            0.0,
            0.1111111111111119,
            0.24074074074074136,
            0.3425925925925929,
            0.409_979_423_868_311_8,
        ],
    );
    assert_values_close(
        &result.plots[2].values,
        &[
            0.0,
            0.05555555555555595,
            0.06481481481481577,
            0.05092592592592615,
            0.033_693_415_637_859_46,
        ],
    );
}

#[test]
fn request_security_aligns_provider_higher_timeframe_macd_tuple() {
    let program = compile_program(
        "indicator(\"request provider htf macd tuple\")\n[macd, signal, hist] = request.security(\"NYSE:IBM\", \"5\", ta.macd(close, 2, 3, 2))\nplot(macd)\nplot(signal)\nplot(hist)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![timed_bar(0, 100.0), timed_bar(300_000, 200.0)],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("higher timeframe provider ta.macd tuple request should run");

    assert_eq!(result.plots.len(), 3);
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(
        &result.plots[0].values[2..],
        &[0.0, 0.0, 16.666666666666657],
    );
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_values_close(
        &result.plots[1].values[2..],
        &[0.0, 0.0, 11.111111111111105],
    );
    assert_eq!(result.plots[2].values[0], PineValue::Na);
    assert_eq!(result.plots[2].values[1], PineValue::Na);
    assert_values_close(&result.plots[2].values[2..], &[0.0, 0.0, 5.555555555555552]);
}

#[test]
fn request_security_evaluates_provider_bb_tuple_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider bb tuple\")\n[basis, upper, lower] = request.security(\"NYSE:IBM\", timeframe.period, ta.bb(close, 3, 2))\nplot(basis)\nplot(upper)\nplot(lower)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_bar(0, 20.0),
            timed_bar(60_000, 21.0),
            timed_bar(120_000, 22.0),
            timed_bar(180_000, 23.0),
            timed_bar(240_000, 24.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 6.0),
            timed_bar(120_000, 7.0),
            timed_bar(180_000, 8.0),
            timed_bar(240_000, 9.0),
        ])
        .expect("provider ta.bb tuple expression should run");

    assert_eq!(result.plots.len(), 3);
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(&result.plots[0].values[2..], &[21.0, 22.0, 23.0]);
    assert_values_close(
        &result.plots[1].values[2..],
        &[22.632993161855453, 23.632993161855453, 24.632993161855453],
    );
    assert_values_close(
        &result.plots[2].values[2..],
        &[19.367006838144547, 20.367006838144547, 21.367006838144547],
    );
}

#[test]
fn request_security_aligns_provider_higher_timeframe_bb_tuple() {
    let program = compile_program(
        "indicator(\"request provider htf bb tuple\")\n[basis, upper, lower] = request.security(\"NYSE:IBM\", \"5\", ta.bb(close, 2, 2))\nplot(basis)\nplot(upper)\nplot(lower)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![timed_bar(0, 100.0), timed_bar(300_000, 200.0)],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("higher timeframe provider ta.bb tuple request should run");

    assert_eq!(result.plots.len(), 3);
    for plot in &result.plots {
        assert_eq!(plot.values[0], PineValue::Na);
        assert_eq!(plot.values[1], PineValue::Na);
        assert_eq!(plot.values[2], PineValue::Na);
        assert_eq!(plot.values[3], PineValue::Na);
    }
    assert_values_close(&result.plots[0].values[4..], &[150.0]);
    assert_values_close(&result.plots[1].values[4..], &[250.0]);
    assert_values_close(&result.plots[2].values[4..], &[50.0]);
}

#[test]
fn request_security_evaluates_provider_kc_tuple_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider kc tuple\")\n[middle, upper, lower] = request.security(\"NYSE:IBM\", timeframe.period, ta.kc(close, 2, 2))\nplot(middle)\nplot(upper)\nplot(lower)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 10.0, 1.0),
            timed_ohlcv(60_000, 12.0, 15.0, 14.0, 12.0, 1.0),
            timed_ohlcv(120_000, 9.0, 10.0, 8.0, 9.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_ohlcv(0, 20.0, 25.0, 19.0, 20.0, 1.0),
            timed_ohlcv(60_000, 21.0, 23.0, 20.0, 21.0, 1.0),
            timed_ohlcv(120_000, 22.0, 26.0, 21.0, 22.0, 1.0),
        ])
        .expect("provider ta.kc tuple expression should run");

    assert_eq!(result.plots.len(), 3);
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
}

#[test]
fn request_security_aligns_provider_higher_timeframe_kc_tuple() {
    let program = compile_program(
        "indicator(\"request provider htf kc tuple\")\n[middle, upper, lower] = request.security(\"NYSE:IBM\", \"5\", ta.kc(close, 2, 2))\nplot(middle)\nplot(upper)\nplot(lower)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("higher timeframe provider ta.kc tuple request should run");

    assert_eq!(result.plots.len(), 3);
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(
        &result.plots[0].values[2..],
        &[100.0, 100.0, 166.66666666666666],
    );
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_values_close(
        &result.plots[1].values[2..],
        &[160.0, 160.0, 333.3333333333333],
    );
    assert_eq!(result.plots[2].values[0], PineValue::Na);
    assert_eq!(result.plots[2].values[1], PineValue::Na);
    assert_values_close(&result.plots[2].values[2..], &[40.0, 40.0, 0.0]);
}

#[test]
fn request_security_evaluates_provider_supertrend_tuple_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider supertrend tuple\")\n[line, direction] = request.security(\"NYSE:IBM\", timeframe.period, ta.supertrend(2, 3))\nplot(line)\nplot(direction)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 10.0, 1.0),
            timed_ohlcv(60_000, 10.0, 12.0, 10.0, 11.0, 1.0),
            timed_ohlcv(120_000, 11.0, 13.0, 11.0, 12.0, 1.0),
            timed_ohlcv(180_000, 12.0, 16.0, 12.0, 15.0, 1.0),
            timed_ohlcv(240_000, 15.0, 17.0, 14.0, 16.0, 1.0),
            timed_ohlcv(300_000, 16.0, 14.0, 8.0, 9.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_ohlcv(0, 20.0, 25.0, 19.0, 20.0, 1.0),
            timed_ohlcv(60_000, 21.0, 23.0, 20.0, 21.0, 1.0),
            timed_ohlcv(120_000, 22.0, 26.0, 21.0, 22.0, 1.0),
            timed_ohlcv(180_000, 24.0, 28.0, 23.0, 24.0, 1.0),
            timed_ohlcv(240_000, 27.0, 31.0, 26.0, 27.0, 1.0),
            timed_ohlcv(300_000, 28.0, 30.0, 24.0, 25.0, 1.0),
        ])
        .expect("provider ta.supertrend tuple expression should run");

    assert_eq!(result.plots.len(), 2);
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
}

#[test]
fn request_security_aligns_provider_higher_timeframe_supertrend_tuple() {
    let program = compile_program(
        "indicator(\"request provider htf supertrend tuple\")\n[line, direction] = request.security(\"NYSE:IBM\", \"5\", ta.supertrend(2, 3))\nplot(line)\nplot(direction)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("higher timeframe provider ta.supertrend tuple request should run");

    assert_eq!(result.plots.len(), 2);
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(
        &result.plots[0].values[2..],
        &[155.0, 155.0, 81.66666666666667],
    );
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_values_close(&result.plots[1].values[2..], &[1.0, 1.0, -1.0]);
}

#[test]
fn request_security_evaluates_provider_dmi_tuple_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider dmi tuple\")\n[plus, minus, adx] = request.security(\"NYSE:IBM\", timeframe.period, ta.dmi(3, 2))\nplot(plus)\nplot(minus)\nplot(adx)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 10.0, 1.0),
            timed_ohlcv(60_000, 10.0, 12.0, 10.0, 11.0, 1.0),
            timed_ohlcv(120_000, 11.0, 13.0, 11.0, 12.0, 1.0),
            timed_ohlcv(180_000, 12.0, 16.0, 12.0, 15.0, 1.0),
            timed_ohlcv(240_000, 15.0, 17.0, 14.0, 16.0, 1.0),
            timed_ohlcv(300_000, 16.0, 14.0, 8.0, 9.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_ohlcv(0, 20.0, 25.0, 19.0, 20.0, 1.0),
            timed_ohlcv(60_000, 21.0, 23.0, 20.0, 21.0, 1.0),
            timed_ohlcv(120_000, 22.0, 26.0, 21.0, 22.0, 1.0),
            timed_ohlcv(180_000, 24.0, 28.0, 23.0, 24.0, 1.0),
            timed_ohlcv(240_000, 27.0, 31.0, 26.0, 27.0, 1.0),
            timed_ohlcv(300_000, 28.0, 30.0, 24.0, 25.0, 1.0),
        ])
        .expect("provider ta.dmi tuple expression should run");

    assert_eq!(result.plots.len(), 3);
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
}

#[test]
fn request_security_aligns_provider_higher_timeframe_dmi_tuple() {
    let program = compile_program(
        "indicator(\"request provider htf dmi tuple\")\n[plus, minus, adx] = request.security(\"NYSE:IBM\", \"5\", ta.dmi(2, 2))\nplot(plus)\nplot(minus)\nplot(adx)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("higher timeframe provider ta.dmi tuple request should run");

    assert_eq!(result.plots.len(), 3);
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(&result.plots[0].values[2..], &[0.0, 0.0, 71.42857142857143]);
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_values_close(&result.plots[1].values[2..], &[0.0, 0.0, 0.0]);
    assert_eq!(result.plots[2].values[0], PineValue::Na);
    assert_eq!(result.plots[2].values[1], PineValue::Na);
    assert_values_close(&result.plots[2].values[2..], &[0.0, 0.0, 50.0]);
}

#[test]
fn request_security_evaluates_provider_vwap_bands_tuple_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider vwap tuple\")\n[basis, upper, lower] = request.security(\"NYSE:IBM\", timeframe.period, ta.vwap(close, time == 0, 2.0))\nplot(basis)\nplot(upper)\nplot(lower)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 1.0, 2.0, 0.0, 4.0, 1.0),
            timed_ohlcv(60_000, 2.0, 3.0, 1.0, 5.0, 2.0),
            timed_ohlcv(120_000, 3.0, 4.0, 2.0, 6.0, 3.0),
            timed_ohlcv(180_000, 4.0, 5.0, 3.0, 7.0, 4.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_ohlcv(0, 10.0, 11.0, 9.0, 10.0, 1.0),
            timed_ohlcv(60_000, 10.0, 12.0, 10.0, 11.0, 1.0),
            timed_ohlcv(120_000, 11.0, 13.0, 11.0, 12.0, 1.0),
            timed_ohlcv(180_000, 12.0, 16.0, 12.0, 15.0, 1.0),
        ])
        .expect("provider ta.vwap bands tuple expression should run");

    assert_eq!(result.plots.len(), 3);
    assert_values_close(
        &result.plots[0].values,
        &[4.0, 4.666666666666667, 5.333333333333333, 6.0],
    );
    assert_values_close(
        &result.plots[1].values,
        &[4.0, 5.60947570824873, 6.824045318333193, 8.0],
    );
    assert_values_close(
        &result.plots[2].values,
        &[4.0, 3.723857625084603, 3.842621348333472, 4.0],
    );
}

#[test]
fn request_security_aligns_provider_higher_timeframe_vwap_bands_tuple() {
    let program = compile_program(
        "indicator(\"request provider htf vwap tuple\")\n[basis, upper, lower] = request.security(\"NYSE:IBM\", \"5\", ta.vwap(close, time == 0, 2.0))\nplot(basis)\nplot(upper)\nplot(lower)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1000.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1000.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("higher timeframe provider ta.vwap bands tuple request should run");

    assert_eq!(result.plots.len(), 3);
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(&result.plots[0].values[2..], &[100.0, 100.0, 150.0]);
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_values_close(&result.plots[1].values[2..], &[100.0, 100.0, 250.0]);
    assert_eq!(result.plots[2].values[0], PineValue::Na);
    assert_eq!(result.plots[2].values[1], PineValue::Na);
    assert_values_close(&result.plots[2].values[2..], &[100.0, 100.0, 50.0]);
}

#[test]
fn request_security_evaluates_provider_tuple_literal_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider tuple literal\")\n[last, shifted, above] = request.security(\"NYSE:IBM\", timeframe.period, [close, close + 1, close > open ? 1 : 0])\nplot(last)\nplot(shifted)\nplot(above)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 20.0, 1.0),
            timed_ohlcv(60_000, 21.0, 23.0, 20.0, 19.0, 1.0),
            timed_ohlcv(120_000, 22.0, 26.0, 21.0, 24.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_ohlcv(0, 1.0, 2.0, 0.0, 4.0, 1.0),
            timed_ohlcv(60_000, 2.0, 3.0, 1.0, 5.0, 1.0),
            timed_ohlcv(120_000, 3.0, 4.0, 2.0, 6.0, 1.0),
        ])
        .expect("provider tuple literal request.security expression should run");

    assert_eq!(result.plots.len(), 3);
    assert_values_close(&result.plots[0].values, &[20.0, 19.0, 24.0]);
    assert_values_close(&result.plots[1].values, &[21.0, 20.0, 25.0]);
    assert_values_close(&result.plots[2].values, &[1.0, 0.0, 1.0]);
}

#[test]
fn request_security_evaluates_provider_tuple_literal_history_and_nz_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider tuple literal history\")\n[prior, fallback, delta] = request.security(\"NYSE:IBM\", timeframe.period, [close[1], nz(close[1], open), close - nz(close[1], close)])\nplot(prior)\nplot(fallback)\nplot(delta)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 20.0, 1.0),
            timed_ohlcv(60_000, 21.0, 23.0, 20.0, 19.0, 1.0),
            timed_ohlcv(120_000, 22.0, 26.0, 21.0, 24.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_ohlcv(0, 1.0, 2.0, 0.0, 4.0, 1.0),
            timed_ohlcv(60_000, 2.0, 3.0, 1.0, 5.0, 1.0),
            timed_ohlcv(120_000, 3.0, 4.0, 2.0, 6.0, 1.0),
        ])
        .expect("provider tuple literal history request.security expression should run");

    assert_eq!(result.plots.len(), 3);
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(&result.plots[0].values[1..], &[20.0, 19.0]);
    assert_values_close(&result.plots[1].values, &[10.0, 20.0, 19.0]);
    assert_values_close(&result.plots[2].values, &[0.0, -1.0, 5.0]);
}

#[test]
fn request_security_evaluates_provider_tuple_literal_math_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider tuple literal math\")\n[maxv, minv, spread] = request.security(\"NYSE:IBM\", timeframe.period, [math.max(close, open), math.min(close, open), math.abs(open - close)])\nplot(maxv)\nplot(minv)\nplot(spread)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 20.0, 1.0),
            timed_ohlcv(60_000, 21.0, 23.0, 20.0, 19.0, 1.0),
            timed_ohlcv(120_000, 22.0, 26.0, 21.0, 24.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_ohlcv(0, 1.0, 2.0, 0.0, 4.0, 1.0),
            timed_ohlcv(60_000, 2.0, 3.0, 1.0, 5.0, 1.0),
            timed_ohlcv(120_000, 3.0, 4.0, 2.0, 6.0, 1.0),
        ])
        .expect("provider tuple literal math request.security expression should run");

    assert_eq!(result.plots.len(), 3);
    assert_values_close(&result.plots[0].values, &[20.0, 21.0, 24.0]);
    assert_values_close(&result.plots[1].values, &[10.0, 19.0, 22.0]);
    assert_values_close(&result.plots[2].values, &[10.0, 2.0, 2.0]);
}

#[test]
fn request_security_evaluates_provider_tuple_literal_stateful_math_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider tuple literal stateful math\")\n[sum_value, rounded] = request.security(\"NYSE:IBM\", timeframe.period, [math.sum(close, 2), math.round_to_mintick(close + 0.006)])\nplot(sum_value)\nplot(rounded)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_bar(0, 20.0),
            timed_bar(60_000, 21.0),
            timed_bar(120_000, 22.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 7.0),
            timed_bar(120_000, 9.0),
        ])
        .expect("provider tuple literal stateful math request.security expression should run");

    assert_eq!(result.plots.len(), 2);
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(&result.plots[0].values[1..], &[41.0, 43.0]);
    assert_values_close(&result.plots[1].values, &[20.01, 21.01, 22.01]);
}

#[test]
fn request_security_evaluates_provider_tuple_literal_stateless_math_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider tuple literal stateless math\")\n[floored, ceiled, rounded] = request.security(\"NYSE:IBM\", timeframe.period, [math.floor(close / 3), math.ceil(open / 6), math.round(close / 7, 2)])\nplot(floored)\nplot(ceiled)\nplot(rounded)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 20.0, 1.0),
            timed_ohlcv(60_000, 11.0, 12.0, 10.0, 21.0, 1.0),
            timed_ohlcv(120_000, 12.0, 13.0, 11.0, 22.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_ohlcv(0, 1.0, 2.0, 0.0, 4.0, 1.0),
            timed_ohlcv(60_000, 2.0, 3.0, 1.0, 5.0, 1.0),
            timed_ohlcv(120_000, 3.0, 4.0, 2.0, 6.0, 1.0),
        ])
        .expect("provider tuple literal stateless math request.security expression should run");

    assert_eq!(result.plots.len(), 3);
    assert_values_close(&result.plots[0].values, &[6.0, 7.0, 7.0]);
    assert_values_close(&result.plots[1].values, &[2.0, 2.0, 2.0]);
    assert_values_close(&result.plots[2].values, &[2.86, 3.0, 314.0 / 100.0]);
}

#[test]
fn request_security_evaluates_provider_tuple_literal_root_log_math_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider tuple literal root log math\")\n[sqrt_value, cbrt_value, log10_value] = request.security(\"NYSE:IBM\", timeframe.period, [math.sqrt(close), math.cbrt(close), math.log10(close)])\nplot(sqrt_value)\nplot(cbrt_value)\nplot(log10_value)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 20.0, 1.0),
            timed_ohlcv(60_000, 11.0, 12.0, 10.0, 21.0, 1.0),
            timed_ohlcv(120_000, 12.0, 13.0, 11.0, 22.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_ohlcv(0, 1.0, 2.0, 0.0, 4.0, 1.0),
            timed_ohlcv(60_000, 2.0, 3.0, 1.0, 5.0, 1.0),
            timed_ohlcv(120_000, 3.0, 4.0, 2.0, 6.0, 1.0),
        ])
        .expect("provider tuple literal root/log math request.security expression should run");

    assert_eq!(result.plots.len(), 3);
    assert_values_close(
        &result.plots[0].values,
        &[20.0_f64.sqrt(), 21.0_f64.sqrt(), 22.0_f64.sqrt()],
    );
    assert_values_close(
        &result.plots[1].values,
        &[20.0_f64.cbrt(), 21.0_f64.cbrt(), 22.0_f64.cbrt()],
    );
    assert_values_close(
        &result.plots[2].values,
        &[20.0_f64.log10(), 21.0_f64.log10(), 22.0_f64.log10()],
    );
}

#[test]
fn request_security_evaluates_provider_tuple_literal_trig_math_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider tuple literal trig math\")\n[sin_value, cos_value, tan_value] = request.security(\"NYSE:IBM\", timeframe.period, [math.sin(close / 100), math.cos(open / 100), math.tan((close - open) / 100)])\nplot(sin_value)\nplot(cos_value)\nplot(tan_value)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 20.0, 1.0),
            timed_ohlcv(60_000, 11.0, 12.0, 10.0, 21.0, 1.0),
            timed_ohlcv(120_000, 12.0, 13.0, 11.0, 22.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_ohlcv(0, 1.0, 2.0, 0.0, 4.0, 1.0),
            timed_ohlcv(60_000, 2.0, 3.0, 1.0, 5.0, 1.0),
            timed_ohlcv(120_000, 3.0, 4.0, 2.0, 6.0, 1.0),
        ])
        .expect("provider tuple literal trig math request.security expression should run");

    assert_eq!(result.plots.len(), 3);
    assert_values_close(
        &result.plots[0].values,
        &[0.2_f64.sin(), 0.21_f64.sin(), 0.22_f64.sin()],
    );
    assert_values_close(
        &result.plots[1].values,
        &[0.1_f64.cos(), 0.11_f64.cos(), 0.12_f64.cos()],
    );
    assert_values_close(&result.plots[2].values, &[0.1_f64.tan(); 3]);
}

#[test]
fn request_security_evaluates_provider_tuple_literal_power_log_math_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider tuple literal power/log math\")\n[pow_value, hypot_value, log_value] = request.security(\"NYSE:IBM\", timeframe.period, [math.pow(close / 100, 2), math.hypot(close / 100, open / 100), math.log(close)])\nplot(pow_value)\nplot(hypot_value)\nplot(log_value)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 20.0, 1.0),
            timed_ohlcv(60_000, 11.0, 12.0, 10.0, 21.0, 1.0),
            timed_ohlcv(120_000, 12.0, 13.0, 11.0, 22.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_ohlcv(0, 1.0, 2.0, 0.0, 4.0, 1.0),
            timed_ohlcv(60_000, 2.0, 3.0, 1.0, 5.0, 1.0),
            timed_ohlcv(120_000, 3.0, 4.0, 2.0, 6.0, 1.0),
        ])
        .expect("provider tuple literal power/log math request.security expression should run");

    assert_eq!(result.plots.len(), 3);
    assert_values_close(
        &result.plots[0].values,
        &[0.2_f64.powf(2.0), 0.21_f64.powf(2.0), 0.22_f64.powf(2.0)],
    );
    assert_values_close(
        &result.plots[1].values,
        &[
            0.2_f64.hypot(0.1),
            0.21_f64.hypot(0.11),
            0.22_f64.hypot(0.12),
        ],
    );
    assert_values_close(
        &result.plots[2].values,
        &[20.0_f64.ln(), 21.0_f64.ln(), 22.0_f64.ln()],
    );
}

#[test]
fn request_security_evaluates_provider_tuple_literal_inverse_trig_exp_math_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider tuple literal inverse trig exp math\")\n[exp_value, acos_value, asin_value, atan_value] = request.security(\"NYSE:IBM\", timeframe.period, [math.exp(close / 100), math.acos(close / 200), math.asin(close / 200), math.atan(close / 100)])\nplot(exp_value)\nplot(acos_value)\nplot(asin_value)\nplot(atan_value)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 20.0, 1.0),
            timed_ohlcv(60_000, 11.0, 12.0, 10.0, 21.0, 1.0),
            timed_ohlcv(120_000, 12.0, 13.0, 11.0, 22.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_ohlcv(0, 1.0, 2.0, 0.0, 4.0, 1.0),
            timed_ohlcv(60_000, 2.0, 3.0, 1.0, 5.0, 1.0),
            timed_ohlcv(120_000, 3.0, 4.0, 2.0, 6.0, 1.0),
        ])
        .expect(
            "provider tuple literal inverse trig/exp math request.security expression should run",
        );

    assert_eq!(result.plots.len(), 4);
    assert_values_close(
        &result.plots[0].values,
        &[0.2_f64.exp(), 0.21_f64.exp(), 0.22_f64.exp()],
    );
    assert_values_close(
        &result.plots[1].values,
        &[(0.1_f64).acos(), (0.105_f64).acos(), (0.11_f64).acos()],
    );
    assert_values_close(
        &result.plots[2].values,
        &[(0.1_f64).asin(), (0.105_f64).asin(), (0.11_f64).asin()],
    );
    assert_values_close(
        &result.plots[3].values,
        &[0.2_f64.atan(), 0.21_f64.atan(), 0.22_f64.atan()],
    );
}

#[test]
fn request_security_evaluates_provider_tuple_literal_angle_scalar_math_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider tuple literal angle scalar math\")\n[avg_value, trunc_value, sign_value, degrees_value, radians_value] = request.security(\"NYSE:IBM\", timeframe.period, [math.avg(open, high, low, close), math.trunc(close / 3), math.sign(close - open), math.todegrees(close / 100), math.toradians(open / 10)])\nplot(avg_value)\nplot(trunc_value)\nplot(sign_value)\nplot(degrees_value)\nplot(radians_value)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 20.0, 1.0),
            timed_ohlcv(60_000, 11.0, 12.0, 10.0, 21.0, 1.0),
            timed_ohlcv(120_000, 12.0, 13.0, 11.0, 22.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_ohlcv(0, 1.0, 2.0, 0.0, 4.0, 1.0),
            timed_ohlcv(60_000, 2.0, 3.0, 1.0, 5.0, 1.0),
            timed_ohlcv(120_000, 3.0, 4.0, 2.0, 6.0, 1.0),
        ])
        .expect("provider tuple literal angle/scalar math request.security expression should run");

    assert_eq!(result.plots.len(), 5);
    assert_values_close(&result.plots[0].values, &[12.5, 13.5, 14.5]);
    assert_values_close(&result.plots[1].values, &[6.0, 7.0, 7.0]);
    assert_values_close(&result.plots[2].values, &[1.0, 1.0, 1.0]);
    assert_values_close(
        &result.plots[3].values,
        &[
            0.2_f64.to_degrees(),
            0.21_f64.to_degrees(),
            0.22_f64.to_degrees(),
        ],
    );
    assert_values_close(
        &result.plots[4].values,
        &[
            1.0_f64.to_radians(),
            1.1_f64.to_radians(),
            1.2_f64.to_radians(),
        ],
    );
}

#[test]
fn request_security_evaluates_provider_tuple_literal_ta_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider tuple literal ta\")\n[avg, delta, total] = request.security(\"NYSE:IBM\", timeframe.period, [ta.sma(close, 2), ta.change(close), ta.cum(close)])\nplot(avg)\nplot(delta)\nplot(total)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 20.0, 1.0),
            timed_ohlcv(60_000, 21.0, 23.0, 20.0, 19.0, 1.0),
            timed_ohlcv(120_000, 22.0, 26.0, 21.0, 24.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_ohlcv(0, 1.0, 2.0, 0.0, 4.0, 1.0),
            timed_ohlcv(60_000, 2.0, 3.0, 1.0, 5.0, 1.0),
            timed_ohlcv(120_000, 3.0, 4.0, 2.0, 6.0, 1.0),
        ])
        .expect("provider tuple literal ta request.security expression should run");

    assert_eq!(result.plots.len(), 3);
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(&result.plots[0].values[1..], &[19.5, 21.5]);
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_values_close(&result.plots[1].values[1..], &[-1.0, 5.0]);
    assert_values_close(&result.plots[2].values, &[20.0, 39.0, 63.0]);
}

#[test]
fn request_security_evaluates_provider_tuple_literal_ta_range_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider tuple literal ta range\")\n[tr_value, atr_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.tr(), ta.atr(2)])\nplot(tr_value)\nplot(atr_value)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 20.0, 1.0),
            timed_ohlcv(60_000, 11.0, 12.0, 10.0, 21.0, 1.0),
            timed_ohlcv(120_000, 12.0, 13.0, 11.0, 22.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_ohlcv(0, 1.0, 2.0, 0.0, 4.0, 1.0),
            timed_ohlcv(60_000, 2.0, 3.0, 1.0, 5.0, 1.0),
            timed_ohlcv(120_000, 3.0, 4.0, 2.0, 6.0, 1.0),
        ])
        .expect("provider tuple literal ta.tr/ta.atr request.security expression should run");

    assert_eq!(result.plots.len(), 2);
    assert_values_close(&result.plots[0].values, &[2.0, 10.0, 10.0]);
    assert_values_close(&result.plots[1].values, &[2.0, 6.0, 8.0]);
}

#[test]
fn request_security_evaluates_provider_tuple_literal_ta_window_extrema_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider tuple literal ta window extrema\")\n[highest_value, lowest_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.highest(high, 2), ta.lowest(low, 2)])\nplot(highest_value)\nplot(lowest_value)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 20.0, 1.0),
            timed_ohlcv(60_000, 11.0, 12.0, 10.0, 21.0, 1.0),
            timed_ohlcv(120_000, 12.0, 13.0, 11.0, 22.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_ohlcv(0, 1.0, 2.0, 0.0, 4.0, 1.0),
            timed_ohlcv(60_000, 2.0, 3.0, 1.0, 5.0, 1.0),
            timed_ohlcv(120_000, 3.0, 4.0, 2.0, 6.0, 1.0),
        ])
        .expect(
            "provider tuple literal ta.highest/ta.lowest request.security expression should run",
        );

    assert_eq!(result.plots.len(), 2);
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(&result.plots[0].values[1..], &[12.0, 13.0]);
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_values_close(&result.plots[1].values[1..], &[9.0, 10.0]);
}

#[test]
fn request_security_evaluates_provider_tuple_literal_ta_momentum_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider tuple literal ta momentum\")\n[mom_value, roc_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.mom(close, 1), ta.roc(close, 1)])\nplot(mom_value)\nplot(roc_value)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 20.0, 1.0),
            timed_ohlcv(60_000, 11.0, 12.0, 10.0, 21.0, 1.0),
            timed_ohlcv(120_000, 12.0, 13.0, 11.0, 22.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_ohlcv(0, 1.0, 2.0, 0.0, 4.0, 1.0),
            timed_ohlcv(60_000, 2.0, 3.0, 1.0, 5.0, 1.0),
            timed_ohlcv(120_000, 3.0, 4.0, 2.0, 6.0, 1.0),
        ])
        .expect("provider tuple literal ta.mom/ta.roc request.security expression should run");

    assert_eq!(result.plots.len(), 2);
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(&result.plots[0].values[1..], &[1.0, 1.0]);
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_values_close(&result.plots[1].values[1..], &[5.0, 100.0 / 21.0]);
}

#[test]
fn request_security_evaluates_provider_tuple_literal_ta_dispersion_window_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider tuple literal ta dispersion window\")\n[range_value, dev_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.range(close, 2), ta.dev(close, 2)])\nplot(range_value)\nplot(dev_value)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 20.0, 1.0),
            timed_ohlcv(60_000, 11.0, 12.0, 10.0, 21.0, 1.0),
            timed_ohlcv(120_000, 12.0, 13.0, 11.0, 22.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_ohlcv(0, 1.0, 2.0, 0.0, 4.0, 1.0),
            timed_ohlcv(60_000, 2.0, 3.0, 1.0, 5.0, 1.0),
            timed_ohlcv(120_000, 3.0, 4.0, 2.0, 6.0, 1.0),
        ])
        .expect("provider tuple literal ta.range/ta.dev request.security expression should run");

    assert_eq!(result.plots.len(), 2);
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(&result.plots[0].values[1..], &[1.0, 1.0]);
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_values_close(&result.plots[1].values[1..], &[0.5, 0.5]);
}

#[test]
fn request_security_evaluates_provider_tuple_literal_ta_core_momentum_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider tuple literal ta core momentum\")\n[ema_value, rsi_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.ema(close, 2), ta.rsi(close, 1)])\nplot(ema_value)\nplot(rsi_value)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 20.0, 1.0),
            timed_ohlcv(60_000, 11.0, 12.0, 10.0, 21.0, 1.0),
            timed_ohlcv(120_000, 12.0, 13.0, 11.0, 22.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_ohlcv(0, 1.0, 2.0, 0.0, 4.0, 1.0),
            timed_ohlcv(60_000, 2.0, 3.0, 1.0, 5.0, 1.0),
            timed_ohlcv(120_000, 3.0, 4.0, 2.0, 6.0, 1.0),
        ])
        .expect("provider tuple literal ta.ema/ta.rsi request.security expression should run");

    assert_eq!(result.plots.len(), 2);
    assert_values_close(
        &result.plots[0].values,
        &[20.0, 20.666_666_666_666_668, 21.555_555_555_555_557],
    );
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_values_close(&result.plots[1].values[1..], &[100.0, 100.0]);
}

#[test]
fn request_security_evaluates_provider_tuple_literal_ta_band_width_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider tuple literal ta band width\")\n[bbw_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.bbw(close, 2, 2)])\nplot(bbw_value)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 20.0, 1.0),
            timed_ohlcv(60_000, 11.0, 12.0, 10.0, 21.0, 1.0),
            timed_ohlcv(120_000, 12.0, 13.0, 11.0, 22.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_ohlcv(0, 1.0, 2.0, 0.0, 4.0, 1.0),
            timed_ohlcv(60_000, 2.0, 3.0, 1.0, 5.0, 1.0),
            timed_ohlcv(120_000, 3.0, 4.0, 2.0, 6.0, 1.0),
        ])
        .expect("provider tuple literal ta.bbw request.security expression should run");

    assert_eq!(result.plots.len(), 1);
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(&result.plots[0].values[1..], &[2.0 / 20.5, 2.0 / 21.5]);
}

#[test]
fn request_security_evaluates_provider_tuple_literal_ta_default_extrema_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider tuple literal ta default extrema\")\n[highest_value, lowest_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.highest(2), ta.lowest(2)])\nplot(highest_value)\nplot(lowest_value)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 20.0, 1.0),
            timed_ohlcv(60_000, 11.0, 12.0, 10.0, 21.0, 1.0),
            timed_ohlcv(120_000, 12.0, 13.0, 11.0, 22.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_ohlcv(0, 1.0, 2.0, 0.0, 4.0, 1.0),
            timed_ohlcv(60_000, 2.0, 3.0, 1.0, 5.0, 1.0),
            timed_ohlcv(120_000, 3.0, 4.0, 2.0, 6.0, 1.0),
        ])
        .expect("provider tuple literal ta.highest/ta.lowest default-source request should run");

    assert_eq!(result.plots.len(), 2);
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(&result.plots[0].values[1..], &[12.0, 13.0]);
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_values_close(&result.plots[1].values[1..], &[9.0, 10.0]);
}

#[test]
fn request_security_evaluates_provider_tuple_literal_ta_default_bar_offsets_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider tuple literal ta default bar offsets\")\n[highest_offset, lowest_offset] = request.security(\"NYSE:IBM\", timeframe.period, [ta.highestbars(2), ta.lowestbars(2)])\nplot(highest_offset)\nplot(lowest_offset)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 20.0, 1.0),
            timed_ohlcv(60_000, 11.0, 12.0, 10.0, 21.0, 1.0),
            timed_ohlcv(120_000, 12.0, 13.0, 11.0, 22.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_ohlcv(0, 1.0, 2.0, 0.0, 4.0, 1.0),
            timed_ohlcv(60_000, 2.0, 3.0, 1.0, 5.0, 1.0),
            timed_ohlcv(120_000, 3.0, 4.0, 2.0, 6.0, 1.0),
        ])
        .expect(
            "provider tuple literal ta.highestbars/ta.lowestbars default-source request should run",
        );

    assert_eq!(result.plots.len(), 2);
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(&result.plots[0].values[1..], &[0.0, 0.0]);
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_values_close(&result.plots[1].values[1..], &[1.0, 1.0]);
}

#[test]
fn request_security_evaluates_provider_tuple_literal_ta_cross_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider tuple literal ta cross\")\n[crossed, crossed_up, crossed_down] = request.security(\"NYSE:IBM\", timeframe.period, [ta.cross(close, 2.0) ? 1 : 0, ta.crossover(close, 2.0) ? 1 : 0, ta.crossunder(close, 2.0) ? 1 : 0])\nplot(crossed)\nplot(crossed_up)\nplot(crossed_down)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_bar(0, 1.0),
            timed_bar(60_000, 3.0),
            timed_bar(120_000, 1.0),
            timed_bar(180_000, 2.0),
            timed_bar(240_000, 4.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 1.0),
            timed_bar(120_000, 5.0),
            timed_bar(180_000, 1.0),
            timed_bar(240_000, 5.0),
        ])
        .expect("provider tuple literal ta cross request.security expression should run");

    assert_eq!(result.plots.len(), 3);
    assert_values_close(&result.plots[0].values, &[0.0, 1.0, 1.0, 0.0, 1.0]);
    assert_values_close(&result.plots[1].values, &[0.0, 1.0, 0.0, 0.0, 1.0]);
    assert_values_close(&result.plots[2].values, &[0.0, 0.0, 1.0, 0.0, 0.0]);
}

#[test]
fn request_security_evaluates_provider_tuple_literal_ta_trend_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider tuple literal ta trend\")\n[rising, falling, open_falling] = request.security(\"NYSE:IBM\", timeframe.period, [ta.rising(close, 2) ? 1 : 0, ta.falling(10 - close, 2) ? 1 : 0, ta.falling(open, 2) ? 1 : 0])\nplot(rising)\nplot(falling)\nplot(open_falling)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 1.0, 2.0, 0.0, 1.0, 1.0),
            timed_ohlcv(60_000, 2.0, 3.0, 1.0, 2.0, 1.0),
            timed_ohlcv(120_000, 3.0, 4.0, 2.0, 3.0, 1.0),
            timed_ohlcv(180_000, 4.0, 5.0, 3.0, 4.0, 1.0),
            timed_ohlcv(240_000, 5.0, 6.0, 4.0, 5.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 1.0),
            timed_bar(120_000, 5.0),
            timed_bar(180_000, 1.0),
            timed_bar(240_000, 5.0),
        ])
        .expect("provider tuple literal ta trend request.security expression should run");

    assert_eq!(result.plots.len(), 3);
    assert_values_close(&result.plots[0].values, &[0.0, 0.0, 1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[1].values, &[0.0, 0.0, 1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[2].values, &[0.0; 5]);
}

#[test]
fn request_security_evaluates_provider_tuple_literal_ta_events_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider tuple literal ta events\")\n[since, prior] = request.security(\"NYSE:IBM\", timeframe.period, [ta.barssince(close > open), ta.valuewhen(close > 21, close, 1)])\nplot(since)\nplot(prior)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 20.0, 1.0),
            timed_ohlcv(60_000, 11.0, 12.0, 10.0, 21.0, 1.0),
            timed_ohlcv(240_000, 12.0, 13.0, 11.0, 22.0, 1.0),
            timed_ohlcv(300_000, 13.0, 14.0, 12.0, 23.0, 1.0),
            timed_ohlcv(540_000, 14.0, 15.0, 13.0, 24.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 1.0),
            timed_bar(240_000, 5.0),
            timed_bar(300_000, 1.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("provider tuple literal ta event request.security expression should run");

    assert_eq!(result.plots.len(), 2);
    assert_values_close(&result.plots[0].values, &[0.0; 5]);
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_eq!(result.plots[1].values[2], PineValue::Na);
    assert_values_close(&result.plots[1].values[3..], &[22.0, 23.0]);
}

#[test]
fn request_security_evaluates_provider_tuple_literal_ta_bars_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider tuple literal ta bars\")\n[highest_offset, lowest_offset] = request.security(\"NYSE:IBM\", timeframe.period, [ta.highestbars(close, 3), ta.lowestbars(close, 3)])\nplot(highest_offset)\nplot(lowest_offset)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_bar(0, 20.0),
            timed_bar(60_000, 21.0),
            timed_bar(240_000, 22.0),
            timed_bar(300_000, 23.0),
            timed_bar(540_000, 24.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 1.0),
            timed_bar(240_000, 5.0),
            timed_bar(300_000, 1.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("provider tuple literal ta bars request.security expression should run");

    assert_eq!(result.plots.len(), 2);
    for plot in &result.plots {
        assert_eq!(plot.values[0], PineValue::Na);
        assert_eq!(plot.values[1], PineValue::Na);
    }
    assert_values_close(&result.plots[0].values[2..], &[0.0, 0.0, 0.0]);
    assert_values_close(&result.plots[1].values[2..], &[2.0, 2.0, 2.0]);
}

#[test]
fn request_security_evaluates_provider_tuple_literal_ta_pivots_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider tuple literal ta pivots\")\n[pivot_high, pivot_low] = request.security(\"NYSE:IBM\", timeframe.period, [ta.pivothigh(0 - math.abs(close - 22), 1, 1), ta.pivotlow(math.abs(close - 22), 1, 1)])\nplot(pivot_high)\nplot(pivot_low)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_bar(0, 20.0),
            timed_bar(60_000, 21.0),
            timed_bar(240_000, 22.0),
            timed_bar(300_000, 23.0),
            timed_bar(540_000, 24.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 1.0),
            timed_bar(240_000, 5.0),
            timed_bar(300_000, 1.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("provider tuple literal ta pivot request.security expression should run");

    assert_eq!(result.plots.len(), 2);
    for plot in &result.plots {
        assert_eq!(plot.values[0], PineValue::Na);
        assert_eq!(plot.values[1], PineValue::Na);
        assert_eq!(plot.values[2], PineValue::Na);
        assert_values_close(&plot.values[3..4], &[0.0]);
        assert_eq!(plot.values[4], PineValue::Na);
    }
}

#[test]
fn request_security_evaluates_provider_tuple_literal_ta_stats_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider tuple literal ta stats\")\n[corr, cov] = request.security(\"NYSE:IBM\", timeframe.period, [ta.correlation(close, high, 3), ta.covariance(close, high, 3)])\nplot(corr)\nplot(cov)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 20.0, 1.0),
            timed_ohlcv(60_000, 11.0, 12.0, 10.0, 21.0, 1.0),
            timed_ohlcv(120_000, 12.0, 13.0, 11.0, 22.0, 1.0),
            timed_ohlcv(180_000, 13.0, 14.0, 12.0, 23.0, 1.0),
            timed_ohlcv(240_000, 14.0, 15.0, 13.0, 24.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 1.0),
            timed_bar(120_000, 5.0),
            timed_bar(180_000, 1.0),
            timed_bar(240_000, 5.0),
        ])
        .expect("provider tuple literal ta stat request.security expression should run");

    assert_eq!(result.plots.len(), 2);
    for plot in &result.plots {
        assert_eq!(plot.values[0], PineValue::Na);
        assert_eq!(plot.values[1], PineValue::Na);
    }
    assert_values_close(&result.plots[0].values[2..], &[1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[1].values[2..], &[0.666_666_666_666_666_6; 3]);
}

#[test]
fn request_security_evaluates_provider_tuple_literal_ta_window_stats_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider tuple literal ta window stats\")\n[median_value, mode_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.median(close, 3), ta.mode(close, 3)])\nplot(median_value)\nplot(mode_value)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 20.0, 1.0),
            timed_ohlcv(60_000, 11.0, 12.0, 10.0, 21.0, 1.0),
            timed_ohlcv(120_000, 12.0, 13.0, 11.0, 22.0, 1.0),
            timed_ohlcv(180_000, 13.0, 14.0, 12.0, 23.0, 1.0),
            timed_ohlcv(240_000, 14.0, 15.0, 13.0, 24.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 1.0),
            timed_bar(120_000, 5.0),
            timed_bar(180_000, 1.0),
            timed_bar(240_000, 5.0),
        ])
        .expect("provider tuple literal ta window stat request.security expression should run");

    assert_eq!(result.plots.len(), 2);
    for plot in &result.plots {
        assert_eq!(plot.values[0], PineValue::Na);
        assert_eq!(plot.values[1], PineValue::Na);
    }
    assert_values_close(&result.plots[0].values[2..], &[21.0, 22.0, 23.0]);
    assert_values_close(&result.plots[1].values[2..], &[20.0, 21.0, 22.0]);
}

#[test]
fn request_security_evaluates_provider_tuple_literal_ta_percentiles_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider tuple literal ta percentiles\")\n[nearest_rank, linear] = request.security(\"NYSE:IBM\", timeframe.period, [ta.percentile_nearest_rank(close, 3, 50), ta.percentile_linear_interpolation(close, 3, 50)])\nplot(nearest_rank)\nplot(linear)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 20.0, 1.0),
            timed_ohlcv(60_000, 11.0, 12.0, 10.0, 21.0, 1.0),
            timed_ohlcv(120_000, 12.0, 13.0, 11.0, 22.0, 1.0),
            timed_ohlcv(180_000, 13.0, 14.0, 12.0, 23.0, 1.0),
            timed_ohlcv(240_000, 14.0, 15.0, 13.0, 24.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 1.0),
            timed_bar(120_000, 5.0),
            timed_bar(180_000, 1.0),
            timed_bar(240_000, 5.0),
        ])
        .expect("provider tuple literal ta percentile request.security expression should run");

    assert_eq!(result.plots.len(), 2);
    for plot in &result.plots {
        assert_eq!(plot.values[0], PineValue::Na);
        assert_eq!(plot.values[1], PineValue::Na);
    }
    assert_values_close(&result.plots[0].values[2..], &[21.0, 22.0, 23.0]);
    assert_values_close(&result.plots[1].values[2..], &[21.0, 22.0, 23.0]);
}

#[test]
fn request_security_evaluates_provider_tuple_literal_ta_percentranks_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider tuple literal ta percentranks\")\n[rank, inverse_rank] = request.security(\"NYSE:IBM\", timeframe.period, [ta.percentrank(close, 3), ta.percentrank(25 - close, 3)])\nplot(rank)\nplot(inverse_rank)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 20.0, 1.0),
            timed_ohlcv(60_000, 11.0, 12.0, 10.0, 21.0, 1.0),
            timed_ohlcv(120_000, 12.0, 13.0, 11.0, 22.0, 1.0),
            timed_ohlcv(180_000, 13.0, 14.0, 12.0, 23.0, 1.0),
            timed_ohlcv(240_000, 14.0, 15.0, 13.0, 24.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 1.0),
            timed_bar(120_000, 5.0),
            timed_bar(180_000, 1.0),
            timed_bar(240_000, 5.0),
        ])
        .expect("provider tuple literal ta percentrank request.security expression should run");

    assert_eq!(result.plots.len(), 2);
    for plot in &result.plots {
        assert_eq!(plot.values[0], PineValue::Na);
        assert_eq!(plot.values[1], PineValue::Na);
    }
    assert_values_close(&result.plots[0].values[2..], &[100.0, 100.0, 100.0]);
    assert_values_close(&result.plots[1].values[2..], &[33.333_333_333_333_33; 3]);
}

#[test]
fn request_security_evaluates_provider_tuple_literal_ta_dispersion_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider tuple literal ta dispersion\")\n[stdev_value, variance_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.stdev(close, 3), ta.variance(close, 3)])\nplot(stdev_value)\nplot(variance_value)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 20.0, 1.0),
            timed_ohlcv(60_000, 11.0, 12.0, 10.0, 21.0, 1.0),
            timed_ohlcv(120_000, 12.0, 13.0, 11.0, 22.0, 1.0),
            timed_ohlcv(180_000, 13.0, 14.0, 12.0, 23.0, 1.0),
            timed_ohlcv(240_000, 14.0, 15.0, 13.0, 24.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 1.0),
            timed_bar(120_000, 5.0),
            timed_bar(180_000, 1.0),
            timed_bar(240_000, 5.0),
        ])
        .expect("provider tuple literal ta dispersion request.security expression should run");

    assert_eq!(result.plots.len(), 2);
    for plot in &result.plots {
        assert_eq!(plot.values[0], PineValue::Na);
        assert_eq!(plot.values[1], PineValue::Na);
    }
    assert_values_close(&result.plots[0].values[2..], &[0.816_496_580_927_726; 3]);
    assert_values_close(&result.plots[1].values[2..], &[0.666_666_666_666_666_6; 3]);
}

#[test]
fn request_security_evaluates_provider_tuple_literal_ta_weighted_averages_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider tuple literal ta weighted averages\")\n[wma_value, vwma_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.wma(close, 3), ta.vwma(close, 3)])\nplot(wma_value)\nplot(vwma_value)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 20.0, 1.0),
            timed_ohlcv(60_000, 11.0, 12.0, 10.0, 21.0, 1.0),
            timed_ohlcv(120_000, 12.0, 13.0, 11.0, 22.0, 1.0),
            timed_ohlcv(180_000, 13.0, 14.0, 12.0, 23.0, 1.0),
            timed_ohlcv(240_000, 14.0, 15.0, 13.0, 24.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 1.0),
            timed_bar(120_000, 5.0),
            timed_bar(180_000, 1.0),
            timed_bar(240_000, 5.0),
        ])
        .expect(
            "provider tuple literal ta weighted average request.security expression should run",
        );

    assert_eq!(result.plots.len(), 2);
    for plot in &result.plots {
        assert_eq!(plot.values[0], PineValue::Na);
        assert_eq!(plot.values[1], PineValue::Na);
    }
    assert_values_close(
        &result.plots[0].values[2..],
        &[
            21.333_333_333_333_332,
            22.333_333_333_333_332,
            23.333_333_333_333_332,
        ],
    );
    assert_values_close(&result.plots[1].values[2..], &[21.0, 22.0, 23.0]);
}

#[test]
fn request_security_evaluates_provider_tuple_literal_ta_smoothing_averages_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider tuple literal ta smoothing averages\")\n[swma_value, hma_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.swma(close), ta.hma(close, 4)])\nplot(swma_value)\nplot(hma_value)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 20.0, 1.0),
            timed_ohlcv(60_000, 11.0, 12.0, 10.0, 21.0, 1.0),
            timed_ohlcv(120_000, 12.0, 13.0, 11.0, 22.0, 1.0),
            timed_ohlcv(180_000, 13.0, 14.0, 12.0, 23.0, 1.0),
            timed_ohlcv(240_000, 14.0, 15.0, 13.0, 24.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 1.0),
            timed_bar(120_000, 5.0),
            timed_bar(180_000, 1.0),
            timed_bar(240_000, 5.0),
        ])
        .expect(
            "provider tuple literal ta smoothing average request.security expression should run",
        );

    assert_eq!(result.plots.len(), 2);
    for plot in &result.plots {
        assert_eq!(plot.values[0], PineValue::Na);
        assert_eq!(plot.values[1], PineValue::Na);
        assert_eq!(plot.values[2], PineValue::Na);
    }
    assert_values_close(&result.plots[0].values[3..], &[21.5, 22.5]);
    assert_eq!(result.plots[1].values[3], PineValue::Na);
    assert_values_close(&result.plots[1].values[4..], &[24.0]);
}

#[test]
fn request_security_evaluates_provider_tuple_literal_ta_regression_averages_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider tuple literal ta regression averages\")\n[alma_value, linreg_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.alma(close, 4, 0.85, 6), ta.linreg(close, 3, 0)])\nplot(alma_value)\nplot(linreg_value)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 20.0, 1.0),
            timed_ohlcv(60_000, 11.0, 12.0, 10.0, 21.0, 1.0),
            timed_ohlcv(120_000, 12.0, 13.0, 11.0, 22.0, 1.0),
            timed_ohlcv(180_000, 13.0, 14.0, 12.0, 23.0, 1.0),
            timed_ohlcv(240_000, 14.0, 15.0, 13.0, 24.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 1.0),
            timed_bar(120_000, 5.0),
            timed_bar(180_000, 1.0),
            timed_bar(240_000, 5.0),
        ])
        .expect(
            "provider tuple literal ta regression average request.security expression should run",
        );

    assert_eq!(result.plots.len(), 2);
    for plot in &result.plots {
        assert_eq!(plot.values[0], PineValue::Na);
        assert_eq!(plot.values[1], PineValue::Na);
    }
    assert_eq!(result.plots[0].values[2], PineValue::Na);
    assert_values_close(
        &result.plots[0].values[3..],
        &[22.462_027_683_060_324, 23.462_027_683_060_324],
    );
    assert_values_close(&result.plots[1].values[2..], &[22.0, 23.0, 24.0]);
}

#[test]
fn request_security_evaluates_provider_tuple_literal_ta_recursive_averages_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider tuple literal ta recursive averages\")\n[rma_value, dema_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.rma(close, 3), ta.dema(close, 3)])\nplot(rma_value)\nplot(dema_value)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 20.0, 1.0),
            timed_ohlcv(60_000, 11.0, 12.0, 10.0, 21.0, 1.0),
            timed_ohlcv(120_000, 12.0, 13.0, 11.0, 22.0, 1.0),
            timed_ohlcv(180_000, 13.0, 14.0, 12.0, 23.0, 1.0),
            timed_ohlcv(240_000, 14.0, 15.0, 13.0, 24.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 1.0),
            timed_bar(120_000, 5.0),
            timed_bar(180_000, 1.0),
            timed_bar(240_000, 5.0),
        ])
        .expect(
            "provider tuple literal ta recursive average request.security expression should run",
        );

    assert_eq!(result.plots.len(), 2);
    assert_values_close(
        &result.plots[0].values,
        &[
            20.0,
            20.333_333_333_333_332,
            20.888_888_888_888_89,
            21.592_592_592_592_59,
            22.395_061_728_395_063,
        ],
    );
    assert_values_close(
        &result.plots[1].values,
        &[20.0, 20.75, 21.75, 22.8125, 23.875],
    );
}

#[test]
fn request_security_evaluates_provider_tuple_literal_ta_momentum_averages_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider tuple literal ta momentum averages\")\n[tema_value, tsi_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.tema(close, 3), ta.tsi(close, 2, 3)])\nplot(tema_value)\nplot(tsi_value)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 20.0, 1.0),
            timed_ohlcv(60_000, 11.0, 12.0, 10.0, 21.0, 1.0),
            timed_ohlcv(120_000, 12.0, 13.0, 11.0, 22.0, 1.0),
            timed_ohlcv(180_000, 13.0, 14.0, 12.0, 23.0, 1.0),
            timed_ohlcv(240_000, 14.0, 15.0, 13.0, 24.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 1.0),
            timed_bar(120_000, 5.0),
            timed_bar(180_000, 1.0),
            timed_bar(240_000, 5.0),
        ])
        .expect(
            "provider tuple literal ta momentum average request.security expression should run",
        );

    assert_eq!(result.plots.len(), 2);
    assert_values_close(
        &result.plots[0].values,
        &[20.0, 20.875, 21.9375, 23.0, 24.03125],
    );
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_values_close(&result.plots[1].values[1..], &[1.0, 1.0, 1.0, 1.0]);
}

#[test]
fn request_security_evaluates_provider_tuple_literal_ta_momentum_flow_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider tuple literal ta momentum flow\")\n[cmo_value, mfi_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.cmo(close, 3), ta.mfi(close, 3)])\nplot(cmo_value)\nplot(mfi_value)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 20.0, 1.0),
            timed_ohlcv(60_000, 11.0, 12.0, 10.0, 21.0, 1.0),
            timed_ohlcv(120_000, 12.0, 13.0, 11.0, 22.0, 1.0),
            timed_ohlcv(180_000, 13.0, 14.0, 12.0, 23.0, 1.0),
            timed_ohlcv(240_000, 14.0, 15.0, 13.0, 24.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 1.0),
            timed_bar(120_000, 5.0),
            timed_bar(180_000, 1.0),
            timed_bar(240_000, 5.0),
        ])
        .expect("provider tuple literal ta momentum flow request.security expression should run");

    assert_eq!(result.plots.len(), 2);
    for value in &result.plots[0].values[..3] {
        assert_eq!(*value, PineValue::Na);
    }
    assert_values_close(&result.plots[0].values[3..], &[100.0, 100.0]);
    for value in &result.plots[1].values[..2] {
        assert_eq!(*value, PineValue::Na);
    }
    assert_values_close(&result.plots[1].values[2..], &[100.0, 100.0, 100.0]);
}

#[test]
fn request_security_evaluates_provider_tuple_literal_ta_oscillators_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider tuple literal ta oscillators\")\n[stoch_value, wpr_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.stoch(close, high, low, 3), ta.wpr(3)])\nplot(stoch_value)\nplot(wpr_value)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 20.0, 1.0),
            timed_ohlcv(60_000, 11.0, 12.0, 10.0, 21.0, 1.0),
            timed_ohlcv(120_000, 12.0, 13.0, 11.0, 22.0, 1.0),
            timed_ohlcv(180_000, 13.0, 14.0, 12.0, 23.0, 1.0),
            timed_ohlcv(240_000, 14.0, 15.0, 13.0, 24.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 1.0),
            timed_bar(120_000, 5.0),
            timed_bar(180_000, 1.0),
            timed_bar(240_000, 5.0),
        ])
        .expect("provider tuple literal ta oscillator request.security expression should run");

    assert_eq!(result.plots.len(), 2);
    for plot in &result.plots {
        assert_eq!(plot.values[0], PineValue::Na);
        assert_eq!(plot.values[1], PineValue::Na);
    }
    assert_values_close(&result.plots[0].values[2..], &[325.0, 325.0, 325.0]);
    assert_values_close(&result.plots[1].values[2..], &[225.0, 225.0, 225.0]);
}

#[test]
fn request_security_evaluates_provider_tuple_literal_ta_trend_oscillator_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider tuple literal ta trend oscillator\")\n[sar_value, cci_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.sar(0.02, 0.02, 0.2), ta.cci(close, 3)])\nplot(sar_value)\nplot(cci_value)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 20.0, 1.0),
            timed_ohlcv(60_000, 11.0, 12.0, 10.0, 21.0, 1.0),
            timed_ohlcv(120_000, 12.0, 13.0, 11.0, 22.0, 1.0),
            timed_ohlcv(180_000, 13.0, 14.0, 12.0, 23.0, 1.0),
            timed_ohlcv(240_000, 14.0, 15.0, 13.0, 24.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 1.0),
            timed_bar(120_000, 5.0),
            timed_bar(180_000, 1.0),
            timed_bar(240_000, 5.0),
        ])
        .expect(
            "provider tuple literal ta trend oscillator request.security expression should run",
        );

    assert_eq!(result.plots.len(), 2);
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(&result.plots[0].values[1..], &[9.0, 9.0, 9.16, 9.4504]);
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_values_close(
        &result.plots[1].values[2..],
        &[
            100.000_000_000_000_01,
            100.000_000_000_000_01,
            100.000_000_000_000_01,
        ],
    );
}

#[test]
fn request_security_evaluates_provider_tuple_literal_ta_shape_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider tuple literal ta shape\")\n[cog_value, bop_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.cog(close, 3), ta.bop()])\nplot(cog_value)\nplot(bop_value)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 20.0, 1.0),
            timed_ohlcv(60_000, 11.0, 12.0, 10.0, 21.0, 1.0),
            timed_ohlcv(120_000, 12.0, 13.0, 11.0, 22.0, 1.0),
            timed_ohlcv(180_000, 13.0, 14.0, 12.0, 23.0, 1.0),
            timed_ohlcv(240_000, 14.0, 15.0, 13.0, 24.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 1.0),
            timed_bar(120_000, 5.0),
            timed_bar(180_000, 1.0),
            timed_bar(240_000, 5.0),
        ])
        .expect("provider tuple literal ta shape request.security expression should run");

    assert_eq!(result.plots.len(), 2);
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(
        &result.plots[0].values[2..],
        &[
            -1.968_253_968_253_968_1,
            -1.969_696_969_696_969_7,
            -1.971_014_492_753_623_3,
        ],
    );
    assert_values_close(&result.plots[1].values, &[5.0, 5.0, 5.0, 5.0, 5.0]);
}

#[test]
fn request_security_evaluates_provider_tuple_literal_ta_extrema_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider tuple literal ta extrema\")\n[max_value, min_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.max(close), ta.min(open)])\nplot(max_value)\nplot(min_value)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 20.0, 1.0),
            timed_ohlcv(60_000, 11.0, 12.0, 10.0, 21.0, 1.0),
            timed_ohlcv(120_000, 12.0, 13.0, 11.0, 22.0, 1.0),
            timed_ohlcv(180_000, 13.0, 14.0, 12.0, 23.0, 1.0),
            timed_ohlcv(240_000, 14.0, 15.0, 13.0, 24.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 1.0),
            timed_bar(120_000, 5.0),
            timed_bar(180_000, 1.0),
            timed_bar(240_000, 5.0),
        ])
        .expect("provider tuple literal ta extrema request.security expression should run");

    assert_eq!(result.plots.len(), 2);
    assert_values_close(&result.plots[0].values, &[20.0, 21.0, 22.0, 23.0, 24.0]);
    assert_values_close(&result.plots[1].values, &[10.0, 10.0, 10.0, 10.0, 10.0]);
}

#[test]
fn request_security_evaluates_provider_tuple_literal_ta_channel_width_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider tuple literal ta channel width\")\n[kcw_value, vwap_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.kcw(close, 3, 2), ta.vwap(close)])\nplot(kcw_value)\nplot(vwap_value)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 20.0, 1.0),
            timed_ohlcv(60_000, 11.0, 12.0, 10.0, 21.0, 1.0),
            timed_ohlcv(120_000, 12.0, 13.0, 11.0, 22.0, 1.0),
            timed_ohlcv(180_000, 13.0, 14.0, 12.0, 23.0, 1.0),
            timed_ohlcv(240_000, 14.0, 15.0, 13.0, 24.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 1.0),
            timed_bar(120_000, 5.0),
            timed_bar(180_000, 1.0),
            timed_bar(240_000, 5.0),
        ])
        .expect("provider tuple literal ta channel width request.security expression should run");

    assert_eq!(result.plots.len(), 2);
    assert_values_close(
        &result.plots[0].values,
        &[
            0.4,
            1.170_731_707_317_073,
            1.505_882_352_941_176_4,
            1.627_118_644_067_796_7,
            1.647_696_476_964_769_7,
        ],
    );
    assert_values_close(&result.plots[1].values, &[20.0, 20.5, 21.0, 21.5, 22.0]);
}

#[test]
fn request_security_evaluates_provider_tuple_literal_ta_variables_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider tuple literal ta variables\")\n[accdist_value, iii_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.accdist, ta.iii])\nplot(accdist_value)\nplot(iii_value)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 20.0, 100.0),
            timed_ohlcv(60_000, 11.0, 12.0, 10.0, 21.0, 100.0),
            timed_ohlcv(120_000, 12.0, 13.0, 11.0, 22.0, 100.0),
            timed_ohlcv(180_000, 13.0, 14.0, 12.0, 23.0, 100.0),
            timed_ohlcv(240_000, 14.0, 15.0, 13.0, 24.0, 100.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 1.0),
            timed_bar(120_000, 5.0),
            timed_bar(180_000, 1.0),
            timed_bar(240_000, 5.0),
        ])
        .expect("provider tuple literal ta variable request.security expression should run");

    assert_eq!(result.plots.len(), 2);
    assert_values_close(
        &result.plots[0].values,
        &[1000.0, 2000.0, 3000.0, 4000.0, 5000.0],
    );
    assert_values_close(&result.plots[1].values, &[0.1, 0.1, 0.1, 0.1, 0.1]);
}

#[test]
fn request_security_evaluates_provider_tuple_literal_ta_volume_flow_variables_in_requested_context()
{
    let program = compile_program(
        "indicator(\"request provider tuple literal ta volume flow variables\")\n[nvi_value, obv_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.nvi, ta.obv])\nplot(nvi_value)\nplot(obv_value)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 20.0, 100.0),
            timed_ohlcv(60_000, 11.0, 12.0, 10.0, 21.0, 100.0),
            timed_ohlcv(120_000, 12.0, 13.0, 11.0, 22.0, 100.0),
            timed_ohlcv(180_000, 13.0, 14.0, 12.0, 23.0, 100.0),
            timed_ohlcv(240_000, 14.0, 15.0, 13.0, 24.0, 100.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 1.0),
            timed_bar(120_000, 5.0),
            timed_bar(180_000, 1.0),
            timed_bar(240_000, 5.0),
        ])
        .expect(
            "provider tuple literal ta volume flow variable request.security expression should run",
        );

    assert_eq!(result.plots.len(), 2);
    assert_values_close(&result.plots[0].values, &[1.0, 1.0, 1.0, 1.0, 1.0]);
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_values_close(&result.plots[1].values[1..], &[100.0, 200.0, 300.0, 400.0]);
}

#[test]
fn request_security_evaluates_provider_tuple_literal_ta_price_volume_variables_in_requested_context()
 {
    let program = compile_program(
        "indicator(\"request provider tuple literal ta price volume variables\")\n[pvi_value, pvt_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.pvi, ta.pvt])\nplot(pvi_value)\nplot(pvt_value)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 20.0, 100.0),
            timed_ohlcv(60_000, 11.0, 12.0, 10.0, 21.0, 100.0),
            timed_ohlcv(120_000, 12.0, 13.0, 11.0, 22.0, 100.0),
            timed_ohlcv(180_000, 13.0, 14.0, 12.0, 23.0, 100.0),
            timed_ohlcv(240_000, 14.0, 15.0, 13.0, 24.0, 100.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 1.0),
            timed_bar(120_000, 5.0),
            timed_bar(180_000, 1.0),
            timed_bar(240_000, 5.0),
        ])
        .expect("provider tuple literal ta price volume variable request.security expression should run");

    assert_eq!(result.plots.len(), 2);
    assert_values_close(&result.plots[0].values, &[1.0, 1.0, 1.0, 1.0, 1.0]);
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_values_close(
        &result.plots[1].values[1..],
        &[
            5.0,
            9.761_904_761_904_763,
            14.307_359_307_359_31,
            18.655_185_394_315_83,
        ],
    );
}

#[test]
fn request_security_evaluates_provider_tuple_literal_ta_final_flow_in_requested_context() {
    let program = compile_program(
        "indicator(\"request provider tuple literal ta final flow\")\n[wvad_value, ao_value] = request.security(\"NYSE:IBM\", timeframe.period, [ta.wvad, ta.ao()])\nplot(wvad_value)\nplot(ao_value)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 20.0, 100.0),
            timed_ohlcv(60_000, 11.0, 12.0, 10.0, 21.0, 100.0),
            timed_ohlcv(120_000, 12.0, 13.0, 11.0, 22.0, 100.0),
            timed_ohlcv(180_000, 13.0, 14.0, 12.0, 23.0, 100.0),
            timed_ohlcv(240_000, 14.0, 15.0, 13.0, 24.0, 100.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 1.0),
            timed_bar(120_000, 5.0),
            timed_bar(180_000, 1.0),
            timed_bar(240_000, 5.0),
        ])
        .expect("provider tuple literal ta final flow request.security expression should run");

    assert_eq!(result.plots.len(), 2);
    assert_values_close(
        &result.plots[0].values,
        &[500.0, 500.0, 500.0, 500.0, 500.0],
    );
    assert_eq!(result.plots[1].values, vec![PineValue::Na; 5]);
}

#[test]
fn request_security_aligns_provider_higher_timeframe_tuple_literal_ta_extrema() {
    let program = compile_program(
        "indicator(\"request provider htf tuple literal ta extrema\")\n[max_value, min_value] = request.security(\"NYSE:IBM\", \"5\", [ta.max(close), ta.min(open)])\nplot(max_value)\nplot(min_value)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("higher timeframe provider tuple literal ta extrema request should run");

    assert_eq!(result.plots.len(), 2);
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(&result.plots[0].values[2..], &[100.0, 100.0, 200.0]);
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_values_close(&result.plots[1].values[2..], &[90.0, 90.0, 90.0]);
}

#[test]
fn request_security_aligns_provider_higher_timeframe_tuple_literal_ta_variables() {
    let program = compile_program(
        "indicator(\"request provider htf tuple literal ta variables\")\n[accdist_value, iii_value] = request.security(\"NYSE:IBM\", \"5\", [ta.accdist, ta.iii])\nplot(accdist_value)\nplot(iii_value)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1000.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1000.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("higher timeframe provider tuple literal ta variable request should run");

    assert_eq!(result.plots.len(), 2);
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(
        &result.plots[0].values[2..],
        &[
            333.333_333_333_333_3,
            333.333_333_333_333_3,
            666.666_666_666_666_6,
        ],
    );
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_values_close(
        &result.plots[1].values[2..],
        &[
            0.000_333_333_333_333_333_3,
            0.000_333_333_333_333_333_3,
            0.000_333_333_333_333_333_3,
        ],
    );
}

#[test]
fn request_security_aligns_provider_higher_timeframe_tuple_literal_ta_volume_flow_variables() {
    let program = compile_program(
        "indicator(\"request provider htf tuple literal ta volume flow variables\")\n[nvi_value, obv_value] = request.security(\"NYSE:IBM\", \"5\", [ta.nvi, ta.obv])\nplot(nvi_value)\nplot(obv_value)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1000.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1000.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect(
            "higher timeframe provider tuple literal ta volume flow variable request should run",
        );

    assert_eq!(result.plots.len(), 2);
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(&result.plots[0].values[2..], &[1.0, 1.0, 1.0]);
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_eq!(result.plots[1].values[2], PineValue::Na);
    assert_eq!(result.plots[1].values[3], PineValue::Na);
    assert_values_close(&result.plots[1].values[4..], &[1000.0]);
}

#[test]
fn request_security_aligns_provider_higher_timeframe_tuple_literal_ta_price_volume_variables() {
    let program = compile_program(
        "indicator(\"request provider htf tuple literal ta price volume variables\")\n[pvi_value, pvt_value] = request.security(\"NYSE:IBM\", \"5\", [ta.pvi, ta.pvt])\nplot(pvi_value)\nplot(pvt_value)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1000.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1000.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect(
            "higher timeframe provider tuple literal ta price volume variable request should run",
        );

    assert_eq!(result.plots.len(), 2);
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(&result.plots[0].values[2..], &[1.0, 1.0, 1.0]);
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_eq!(result.plots[1].values[2], PineValue::Na);
    assert_eq!(result.plots[1].values[3], PineValue::Na);
    assert_values_close(&result.plots[1].values[4..], &[1000.0]);
}

#[test]
fn request_security_aligns_provider_higher_timeframe_tuple_literal_ta_final_flow() {
    let program = compile_program(
        "indicator(\"request provider htf tuple literal ta final flow\")\n[wvad_value, ao_value] = request.security(\"NYSE:IBM\", \"5\", [ta.wvad, ta.ao()])\nplot(wvad_value)\nplot(ao_value)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1000.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1000.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("higher timeframe provider tuple literal ta final flow request should run");

    assert_eq!(result.plots.len(), 2);
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(
        &result.plots[0].values[2..],
        &[
            333.333_333_333_333_3,
            333.333_333_333_333_3,
            333.333_333_333_333_3,
        ],
    );
    assert_eq!(result.plots[1].values, vec![PineValue::Na; 5]);
}

#[test]
fn request_security_aligns_provider_higher_timeframe_tuple_literal_ta_smoothing_averages() {
    let program = compile_program(
        "indicator(\"request provider htf tuple literal ta smoothing averages\")\n[swma_value, hma_value] = request.security(\"NYSE:IBM\", \"5\", [ta.swma(close), ta.hma(close, 4)])\nplot(swma_value)\nplot(hma_value)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1000.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1000.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("higher timeframe provider tuple literal ta smoothing average request should run");

    assert_eq!(result.plots.len(), 2);
    assert_eq!(result.plots[0].values, vec![PineValue::Na; 5]);
    assert_eq!(result.plots[1].values, vec![PineValue::Na; 5]);
}

#[test]
fn request_security_aligns_provider_higher_timeframe_tuple_literal_ta_regression_averages() {
    let program = compile_program(
        "indicator(\"request provider htf tuple literal ta regression averages\")\n[alma_value, linreg_value] = request.security(\"NYSE:IBM\", \"5\", [ta.alma(close, 4, 0.85, 6), ta.linreg(close, 3, 0)])\nplot(alma_value)\nplot(linreg_value)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1000.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1000.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("higher timeframe provider tuple literal ta regression average request should run");

    assert_eq!(result.plots.len(), 2);
    assert_eq!(result.plots[0].values, vec![PineValue::Na; 5]);
    assert_eq!(result.plots[1].values, vec![PineValue::Na; 5]);
}

#[test]
fn request_security_aligns_provider_higher_timeframe_tuple_literal_ta_recursive_averages() {
    let program = compile_program(
        "indicator(\"request provider htf tuple literal ta recursive averages\")\n[rma_value, dema_value] = request.security(\"NYSE:IBM\", \"5\", [ta.rma(close, 3), ta.dema(close, 3)])\nplot(rma_value)\nplot(dema_value)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1000.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1000.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("higher timeframe provider tuple literal ta recursive average request should run");

    assert_eq!(result.plots.len(), 2);
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(
        &result.plots[0].values[2..],
        &[100.0, 100.0, 133.333_333_333_333_34],
    );
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_values_close(&result.plots[1].values[2..], &[100.0, 100.0, 175.0]);
}

#[test]
fn request_security_aligns_provider_higher_timeframe_tuple_literal_ta_momentum_averages() {
    let program = compile_program(
        "indicator(\"request provider htf tuple literal ta momentum averages\")\n[tema_value, tsi_value] = request.security(\"NYSE:IBM\", \"5\", [ta.tema(close, 3), ta.tsi(close, 2, 3)])\nplot(tema_value)\nplot(tsi_value)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1000.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1000.0),
            timed_ohlcv(600_000, 290.0, 310.0, 280.0, 300.0, 1000.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
            timed_bar(600_000, 6.0),
            timed_bar(840_000, 7.0),
        ])
        .expect("higher timeframe provider tuple literal ta momentum average request should run");

    assert_eq!(result.plots.len(), 2);
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(
        &result.plots[0].values[2..],
        &[100.0, 100.0, 187.5, 187.5, 293.75],
    );
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_eq!(result.plots[1].values[2], PineValue::Na);
    assert_eq!(result.plots[1].values[3], PineValue::Na);
    assert_values_close(&result.plots[1].values[4..], &[1.0, 1.0, 1.0]);
}

#[test]
fn request_security_aligns_provider_higher_timeframe_tuple_literal_ta_momentum_flow() {
    let program = compile_program(
        "indicator(\"request provider htf tuple literal ta momentum flow\")\n[cmo_value, mfi_value] = request.security(\"NYSE:IBM\", \"5\", [ta.cmo(close, 1), ta.mfi(close, 2)])\nplot(cmo_value)\nplot(mfi_value)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1000.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1000.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("higher timeframe provider tuple literal ta momentum flow request should run");

    assert_eq!(result.plots.len(), 2);
    for value in &result.plots[0].values[..4] {
        assert_eq!(*value, PineValue::Na);
    }
    assert_values_close(&result.plots[0].values[4..], &[100.0]);
    for value in &result.plots[1].values[..4] {
        assert_eq!(*value, PineValue::Na);
    }
    assert_values_close(&result.plots[1].values[4..], &[100.0]);
}

#[test]
fn request_security_aligns_provider_higher_timeframe_tuple_literal_ta_oscillators() {
    let program = compile_program(
        "indicator(\"request provider htf tuple literal ta oscillators\")\n[stoch_value, wpr_value] = request.security(\"NYSE:IBM\", \"5\", [ta.stoch(close, high, low, 2), ta.wpr(2)])\nplot(stoch_value)\nplot(wpr_value)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1000.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1000.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("higher timeframe provider tuple literal ta oscillator request should run");

    assert_eq!(result.plots.len(), 2);
    for plot in &result.plots {
        for value in &plot.values[..4] {
            assert_eq!(*value, PineValue::Na);
        }
    }
    assert_values_close(&result.plots[0].values[4..], &[92.307_692_307_692_3]);
    assert_values_close(&result.plots[1].values[4..], &[-7.692_307_692_307_692_5]);
}

#[test]
fn request_security_aligns_provider_higher_timeframe_tuple_literal_ta_trend_oscillator() {
    let program = compile_program(
        "indicator(\"request provider htf tuple literal ta trend oscillator\")\n[sar_value, cci_value] = request.security(\"NYSE:IBM\", \"5\", [ta.sar(0.02, 0.02, 0.2), ta.cci(close, 2)])\nplot(sar_value)\nplot(cci_value)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1000.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1000.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("higher timeframe provider tuple literal ta trend oscillator request should run");

    assert_eq!(result.plots.len(), 2);
    for plot in &result.plots {
        for value in &plot.values[..4] {
            assert_eq!(*value, PineValue::Na);
        }
    }
    assert_values_close(&result.plots[0].values[4..], &[80.0]);
    assert_values_close(&result.plots[1].values[4..], &[66.666_666_666_666_67]);
}

#[test]
fn request_security_aligns_provider_higher_timeframe_tuple_literal_ta_shape() {
    let program = compile_program(
        "indicator(\"request provider htf tuple literal ta shape\")\n[cog_value, bop_value] = request.security(\"NYSE:IBM\", \"5\", [ta.cog(close, 2), ta.bop()])\nplot(cog_value)\nplot(bop_value)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1000.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1000.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("higher timeframe provider tuple literal ta shape request should run");

    assert_eq!(result.plots.len(), 2);
    for value in &result.plots[0].values[..4] {
        assert_eq!(*value, PineValue::Na);
    }
    assert_values_close(&result.plots[0].values[4..], &[-1.333_333_333_333_333_3]);
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_values_close(
        &result.plots[1].values[2..],
        &[
            0.333_333_333_333_333_3,
            0.333_333_333_333_333_3,
            0.333_333_333_333_333_3,
        ],
    );
}

#[test]
fn request_security_aligns_provider_higher_timeframe_tuple_literal_ta_channel_width() {
    let program = compile_program(
        "indicator(\"request provider htf tuple literal ta channel width\")\n[kcw_value, vwap_value] = request.security(\"NYSE:IBM\", \"5\", [ta.kcw(close, 2, 2), ta.vwap(close)])\nplot(kcw_value)\nplot(vwap_value)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1000.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1000.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("higher timeframe provider tuple literal ta channel width request should run");

    assert_eq!(result.plots.len(), 2);
    for plot in &result.plots {
        assert_eq!(plot.values[0], PineValue::Na);
        assert_eq!(plot.values[1], PineValue::Na);
    }
    assert_values_close(&result.plots[0].values[2..], &[1.2, 1.2, 2.0]);
    assert_values_close(&result.plots[1].values[2..], &[100.0, 100.0, 150.0]);
}

#[test]
fn request_security_aligns_provider_higher_timeframe_tuple_literal_ta_range() {
    let program = compile_program(
        "indicator(\"request provider htf tuple literal ta range\")\n[tr_value, atr_value] = request.security(\"NYSE:IBM\", \"5\", [ta.tr(), ta.atr(2)])\nplot(tr_value)\nplot(atr_value)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1000.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1000.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("higher timeframe provider tuple literal ta range request should run");

    assert_eq!(result.plots.len(), 2);
    for plot in &result.plots {
        assert_eq!(plot.values[0], PineValue::Na);
        assert_eq!(plot.values[1], PineValue::Na);
    }
    assert_values_close(&result.plots[0].values[2..], &[30.0, 30.0, 110.0]);
    assert_values_close(&result.plots[1].values[2..], &[30.0, 30.0, 70.0]);
}

#[test]
fn request_security_aligns_provider_higher_timeframe_tuple_literal_ta_window_extrema() {
    let program = compile_program(
        "indicator(\"request provider htf tuple literal ta window extrema\")\n[highest_value, lowest_value] = request.security(\"NYSE:IBM\", \"5\", [ta.highest(high, 2), ta.lowest(low, 2)])\nplot(highest_value)\nplot(lowest_value)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1000.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1000.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("higher timeframe provider tuple literal ta window extrema request should run");

    assert_eq!(result.plots.len(), 2);
    for plot in &result.plots {
        for value in &plot.values[..4] {
            assert_eq!(*value, PineValue::Na);
        }
    }
    assert_values_close(&result.plots[0].values[4..], &[210.0]);
    assert_values_close(&result.plots[1].values[4..], &[80.0]);
}

#[test]
fn request_security_aligns_provider_higher_timeframe_tuple_literal_ta_momentum() {
    let program = compile_program(
        "indicator(\"request provider htf tuple literal ta momentum\")\n[mom_value, roc_value] = request.security(\"NYSE:IBM\", \"5\", [ta.mom(close, 1), ta.roc(close, 1)])\nplot(mom_value)\nplot(roc_value)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1000.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1000.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("higher timeframe provider tuple literal ta momentum request should run");

    assert_eq!(result.plots.len(), 2);
    for plot in &result.plots {
        for value in &plot.values[..4] {
            assert_eq!(*value, PineValue::Na);
        }
    }
    assert_values_close(&result.plots[0].values[4..], &[100.0]);
    assert_values_close(&result.plots[1].values[4..], &[100.0]);
}

#[test]
fn request_security_aligns_provider_higher_timeframe_tuple_literal_ta_dispersion_window() {
    let program = compile_program(
        "indicator(\"request provider htf tuple literal ta dispersion window\")\n[range_value, dev_value] = request.security(\"NYSE:IBM\", \"5\", [ta.range(close, 2), ta.dev(close, 2)])\nplot(range_value)\nplot(dev_value)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1000.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1000.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("higher timeframe provider tuple literal ta dispersion window request should run");

    assert_eq!(result.plots.len(), 2);
    for plot in &result.plots {
        for value in &plot.values[..4] {
            assert_eq!(*value, PineValue::Na);
        }
    }
    assert_values_close(&result.plots[0].values[4..], &[100.0]);
    assert_values_close(&result.plots[1].values[4..], &[50.0]);
}

#[test]
fn request_security_aligns_provider_higher_timeframe_tuple_literal_ta_core_momentum() {
    let program = compile_program(
        "indicator(\"request provider htf tuple literal ta core momentum\")\n[ema_value, rsi_value] = request.security(\"NYSE:IBM\", \"5\", [ta.ema(close, 2), ta.rsi(close, 1)])\nplot(ema_value)\nplot(rsi_value)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1000.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1000.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("higher timeframe provider tuple literal ta core momentum request should run");

    assert_eq!(result.plots.len(), 2);
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(
        &result.plots[0].values[2..],
        &[100.0, 100.0, 166.666_666_666_666_66],
    );
    for value in &result.plots[1].values[..4] {
        assert_eq!(*value, PineValue::Na);
    }
    assert_values_close(&result.plots[1].values[4..], &[100.0]);
}

#[test]
fn request_security_aligns_provider_higher_timeframe_tuple_literal_ta_band_width() {
    let program = compile_program(
        "indicator(\"request provider htf tuple literal ta band width\")\n[bbw_value] = request.security(\"NYSE:IBM\", \"5\", [ta.bbw(close, 2, 2)])\nplot(bbw_value)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1000.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1000.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("higher timeframe provider tuple literal ta band width request should run");

    assert_eq!(result.plots.len(), 1);
    for value in &result.plots[0].values[..4] {
        assert_eq!(*value, PineValue::Na);
    }
    assert_values_close(&result.plots[0].values[4..], &[1.333_333_333_333_333_3]);
}

#[test]
fn request_security_aligns_provider_higher_timeframe_tuple_literal_ta_default_extrema() {
    let program = compile_program(
        "indicator(\"request provider htf tuple literal ta default extrema\")\n[highest_value, lowest_value] = request.security(\"NYSE:IBM\", \"5\", [ta.highest(2), ta.lowest(2)])\nplot(highest_value)\nplot(lowest_value)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1000.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1000.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("higher timeframe provider tuple literal ta default extrema request should run");

    assert_eq!(result.plots.len(), 2);
    for plot in &result.plots {
        for value in &plot.values[..4] {
            assert_eq!(*value, PineValue::Na);
        }
    }
    assert_values_close(&result.plots[0].values[4..], &[210.0]);
    assert_values_close(&result.plots[1].values[4..], &[80.0]);
}

#[test]
fn request_security_aligns_provider_higher_timeframe_tuple_literal_ta_default_bar_offsets() {
    let program = compile_program(
        "indicator(\"request provider htf tuple literal ta default bar offsets\")\n[highest_offset, lowest_offset] = request.security(\"NYSE:IBM\", \"5\", [ta.highestbars(2), ta.lowestbars(2)])\nplot(highest_offset)\nplot(lowest_offset)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1000.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1000.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect(
            "higher timeframe provider tuple literal ta default bar offsets request should run",
        );

    assert_eq!(result.plots.len(), 2);
    for plot in &result.plots {
        for value in &plot.values[..4] {
            assert_eq!(*value, PineValue::Na);
        }
    }
    assert_values_close(&result.plots[0].values[4..], &[0.0]);
    assert_values_close(&result.plots[1].values[4..], &[1.0]);
}

#[test]
fn request_security_aligns_provider_higher_timeframe_tuple_literal() {
    let program = compile_program(
        "indicator(\"request provider htf tuple literal\")\n[last, shifted, above] = request.security(\"NYSE:IBM\", \"5\", [close, close + 1, close > open ? 1 : 0])\nplot(last)\nplot(shifted)\nplot(above)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("higher timeframe provider tuple literal request should run");

    assert_eq!(result.plots.len(), 3);
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(&result.plots[0].values[2..], &[100.0, 100.0, 200.0]);
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_values_close(&result.plots[1].values[2..], &[101.0, 101.0, 201.0]);
    assert_eq!(result.plots[2].values[0], PineValue::Na);
    assert_eq!(result.plots[2].values[1], PineValue::Na);
    assert_values_close(&result.plots[2].values[2..], &[1.0, 1.0, 1.0]);
}

#[test]
fn request_security_aligns_provider_higher_timeframe_tuple_literal_history_and_nz() {
    let program = compile_program(
        "indicator(\"request provider htf tuple literal history\")\n[prior, fallback, delta] = request.security(\"NYSE:IBM\", \"5\", [close[1], nz(close[1], open), close - nz(close[1], close)])\nplot(prior)\nplot(fallback)\nplot(delta)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("higher timeframe provider tuple literal history request should run");

    assert_eq!(result.plots.len(), 3);
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_eq!(result.plots[0].values[2], PineValue::Na);
    assert_eq!(result.plots[0].values[3], PineValue::Na);
    assert_values_close(&result.plots[0].values[4..], &[100.0]);
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_values_close(&result.plots[1].values[2..], &[90.0, 90.0, 100.0]);
    assert_eq!(result.plots[2].values[0], PineValue::Na);
    assert_eq!(result.plots[2].values[1], PineValue::Na);
    assert_values_close(&result.plots[2].values[2..], &[0.0, 0.0, 100.0]);
}

#[test]
fn request_security_aligns_provider_higher_timeframe_tuple_literal_math() {
    let program = compile_program(
        "indicator(\"request provider htf tuple literal math\")\n[maxv, minv, spread, sum_value, rounded] = request.security(\"NYSE:IBM\", \"5\", [math.max(close, open), math.min(close, open), math.abs(open - close), math.sum(close, 2), math.round_to_mintick(close + 0.006)])\nplot(maxv)\nplot(minv)\nplot(spread)\nplot(sum_value)\nplot(rounded)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("higher timeframe provider tuple literal math request should run");

    assert_eq!(result.plots.len(), 5);
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(&result.plots[0].values[2..], &[100.0, 100.0, 200.0]);
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_values_close(&result.plots[1].values[2..], &[90.0, 90.0, 190.0]);
    assert_eq!(result.plots[2].values[0], PineValue::Na);
    assert_eq!(result.plots[2].values[1], PineValue::Na);
    assert_values_close(&result.plots[2].values[2..], &[10.0, 10.0, 10.0]);
    for value in &result.plots[3].values[..4] {
        assert_eq!(*value, PineValue::Na);
    }
    assert_values_close(&result.plots[3].values[4..], &[300.0]);
    assert_eq!(result.plots[4].values[0], PineValue::Na);
    assert_eq!(result.plots[4].values[1], PineValue::Na);
    assert_values_close(&result.plots[4].values[2..], &[100.01, 100.01, 200.01]);
}

#[test]
fn request_security_aligns_provider_higher_timeframe_tuple_literal_stateless_math() {
    let program = compile_program(
        "indicator(\"request provider htf tuple literal stateless math\")\n[floored, ceiled, rounded] = request.security(\"NYSE:IBM\", \"5\", [math.floor(close / 3), math.ceil(open / 80), math.round(close / 3, 2)])\nplot(floored)\nplot(ceiled)\nplot(rounded)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1000.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1000.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("higher timeframe provider tuple literal stateless math request should run");

    assert_eq!(result.plots.len(), 3);
    for plot in &result.plots {
        assert_eq!(plot.values[0], PineValue::Na);
        assert_eq!(plot.values[1], PineValue::Na);
    }
    assert_values_close(&result.plots[0].values[2..], &[33.0, 33.0, 66.0]);
    assert_values_close(&result.plots[1].values[2..], &[2.0, 2.0, 3.0]);
    assert_values_close(&result.plots[2].values[2..], &[33.33, 33.33, 66.67]);
}

#[test]
fn request_security_aligns_provider_higher_timeframe_tuple_literal_root_log_math() {
    let program = compile_program(
        "indicator(\"request provider htf tuple literal root log math\")\n[sqrt_value, cbrt_value, log10_value] = request.security(\"NYSE:IBM\", \"5\", [math.sqrt(close), math.cbrt(close), math.log10(close)])\nplot(sqrt_value)\nplot(cbrt_value)\nplot(log10_value)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1000.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1000.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("higher timeframe provider tuple literal root/log math request should run");

    assert_eq!(result.plots.len(), 3);
    for plot in &result.plots {
        assert_eq!(plot.values[0], PineValue::Na);
        assert_eq!(plot.values[1], PineValue::Na);
    }
    assert_values_close(
        &result.plots[0].values[2..],
        &[10.0, 10.0, 14.142135623730951],
    );
    assert_values_close(
        &result.plots[1].values[2..],
        &[4.641588833612779, 4.641588833612779, 5.848035476425732],
    );
    assert_values_close(
        &result.plots[2].values[2..],
        &[2.0, 2.0, 2.3010299956639813],
    );
}

#[test]
fn request_security_aligns_provider_higher_timeframe_tuple_literal_trig_math() {
    let program = compile_program(
        "indicator(\"request provider htf tuple literal trig math\")\n[sin_value, cos_value, tan_value] = request.security(\"NYSE:IBM\", \"5\", [math.sin(close / 100), math.cos(open / 100), math.tan((close - open) / 100)])\nplot(sin_value)\nplot(cos_value)\nplot(tan_value)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1000.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1000.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("higher timeframe provider tuple literal trig math request should run");

    assert_eq!(result.plots.len(), 3);
    for plot in &result.plots {
        assert_eq!(plot.values[0], PineValue::Na);
        assert_eq!(plot.values[1], PineValue::Na);
    }
    assert_values_close(
        &result.plots[0].values[2..],
        &[0.8414709848078965, 0.8414709848078965, 0.9092974268256817],
    );
    assert_values_close(
        &result.plots[1].values[2..],
        &[0.6216099682706644, 0.6216099682706644, -0.32328956686350335],
    );
    assert_values_close(
        &result.plots[2].values[2..],
        &[
            0.10033467208545055,
            0.10033467208545055,
            0.10033467208545055,
        ],
    );
}

#[test]
fn request_security_aligns_provider_higher_timeframe_tuple_literal_power_log_math() {
    let program = compile_program(
        "indicator(\"request provider htf tuple literal power log math\")\n[pow_value, hypot_value, log_value] = request.security(\"NYSE:IBM\", \"5\", [math.pow(close / 100, 2), math.hypot(close / 100, open / 100), math.log(close)])\nplot(pow_value)\nplot(hypot_value)\nplot(log_value)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1000.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1000.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("higher timeframe provider tuple literal power/log math request should run");

    assert_eq!(result.plots.len(), 3);
    for plot in &result.plots {
        assert_eq!(plot.values[0], PineValue::Na);
        assert_eq!(plot.values[1], PineValue::Na);
    }
    assert_values_close(&result.plots[0].values[2..], &[1.0, 1.0, 4.0]);
    assert_values_close(
        &result.plots[1].values[2..],
        &[1.3453624047073711, 1.3453624047073711, 2.7586228448267445],
    );
    assert_values_close(
        &result.plots[2].values[2..],
        &[4.605170185988092, 4.605170185988092, 5.298317366548036],
    );
}

#[test]
fn request_security_aligns_provider_higher_timeframe_tuple_literal_inverse_trig_exp_math() {
    let program = compile_program(
        "indicator(\"request provider htf tuple literal inverse trig exp math\")\n[exp_value, acos_value, asin_value, atan_value] = request.security(\"NYSE:IBM\", \"5\", [math.exp(close / 100), math.acos(close / 200), math.asin(close / 200), math.atan(close / 100)])\nplot(exp_value)\nplot(acos_value)\nplot(asin_value)\nplot(atan_value)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1000.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1000.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("higher timeframe provider tuple literal inverse trig/exp math request should run");

    assert_eq!(result.plots.len(), 4);
    for plot in &result.plots {
        assert_eq!(plot.values[0], PineValue::Na);
        assert_eq!(plot.values[1], PineValue::Na);
    }
    assert_values_close(
        &result.plots[0].values[2..],
        &[1.0_f64.exp(), 1.0_f64.exp(), 2.0_f64.exp()],
    );
    assert_values_close(
        &result.plots[1].values[2..],
        &[(0.5_f64).acos(), (0.5_f64).acos(), 1.0_f64.acos()],
    );
    assert_values_close(
        &result.plots[2].values[2..],
        &[(0.5_f64).asin(), (0.5_f64).asin(), 1.0_f64.asin()],
    );
    assert_values_close(
        &result.plots[3].values[2..],
        &[1.0_f64.atan(), 1.0_f64.atan(), 2.0_f64.atan()],
    );
}

#[test]
fn request_security_aligns_provider_higher_timeframe_tuple_literal_angle_scalar_math() {
    let program = compile_program(
        "indicator(\"request provider htf tuple literal angle scalar math\")\n[avg_value, trunc_value, sign_value, degrees_value, radians_value] = request.security(\"NYSE:IBM\", \"5\", [math.avg(open, high, low, close), math.trunc(close / 3), math.sign(close - open), math.todegrees(close / 100), math.toradians(open / 10)])\nplot(avg_value)\nplot(trunc_value)\nplot(sign_value)\nplot(degrees_value)\nplot(radians_value)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1000.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1000.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("higher timeframe provider tuple literal angle/scalar math request should run");

    assert_eq!(result.plots.len(), 5);
    for plot in &result.plots {
        assert_eq!(plot.values[0], PineValue::Na);
        assert_eq!(plot.values[1], PineValue::Na);
    }
    assert_values_close(&result.plots[0].values[2..], &[95.0, 95.0, 195.0]);
    assert_values_close(&result.plots[1].values[2..], &[33.0, 33.0, 66.0]);
    assert_values_close(&result.plots[2].values[2..], &[1.0, 1.0, 1.0]);
    assert_values_close(
        &result.plots[3].values[2..],
        &[
            1.0_f64.to_degrees(),
            1.0_f64.to_degrees(),
            2.0_f64.to_degrees(),
        ],
    );
    assert_values_close(
        &result.plots[4].values[2..],
        &[
            9.0_f64.to_radians(),
            9.0_f64.to_radians(),
            19.0_f64.to_radians(),
        ],
    );
}

#[test]
fn request_security_aligns_provider_higher_timeframe_tuple_literal_ta() {
    let program = compile_program(
        "indicator(\"request provider htf tuple literal ta\")\n[avg, delta, total] = request.security(\"NYSE:IBM\", \"5\", [ta.sma(close, 2), ta.change(close), ta.cum(close)])\nplot(avg)\nplot(delta)\nplot(total)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("higher timeframe provider tuple literal ta request should run");

    assert_eq!(result.plots.len(), 3);
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_eq!(result.plots[0].values[2], PineValue::Na);
    assert_eq!(result.plots[0].values[3], PineValue::Na);
    assert_values_close(&result.plots[0].values[4..], &[150.0]);
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_eq!(result.plots[1].values[2], PineValue::Na);
    assert_eq!(result.plots[1].values[3], PineValue::Na);
    assert_values_close(&result.plots[1].values[4..], &[100.0]);
    assert_eq!(result.plots[2].values[0], PineValue::Na);
    assert_eq!(result.plots[2].values[1], PineValue::Na);
    assert_values_close(&result.plots[2].values[2..], &[100.0, 100.0, 300.0]);
}

#[test]
fn request_security_aligns_provider_higher_timeframe_tuple_literal_ta_cross() {
    let program = compile_program(
        "indicator(\"request provider htf tuple literal ta cross\")\n[crossed, crossed_up, crossed_down] = request.security(\"NYSE:IBM\", \"5\", [ta.cross(close, 150) ? 1 : 0, ta.crossover(close, 150) ? 1 : 0, ta.crossunder(close - time / 2000.0, 75) ? 1 : 0])\nplot(crossed)\nplot(crossed_up)\nplot(crossed_down)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("higher timeframe provider tuple literal ta cross request should run");

    assert_eq!(result.plots.len(), 3);
    for plot in &result.plots {
        assert_eq!(plot.values[0], PineValue::Na);
        assert_eq!(plot.values[1], PineValue::Na);
        assert_values_close(&plot.values[2..], &[0.0, 0.0, 1.0]);
    }
}

#[test]
fn request_security_aligns_provider_higher_timeframe_tuple_literal_ta_trend() {
    let program = compile_program(
        "indicator(\"request provider htf tuple literal ta trend\")\n[rising, falling, open_falling] = request.security(\"NYSE:IBM\", \"5\", [ta.rising(close, 1) ? 1 : 0, ta.falling(300 - close, 1) ? 1 : 0, ta.falling(open, 1) ? 1 : 0])\nplot(rising)\nplot(falling)\nplot(open_falling)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("higher timeframe provider tuple literal ta trend request should run");

    assert_eq!(result.plots.len(), 3);
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(&result.plots[0].values[2..], &[0.0, 0.0, 1.0]);
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_values_close(&result.plots[1].values[2..], &[0.0, 0.0, 1.0]);
    assert_eq!(result.plots[2].values[0], PineValue::Na);
    assert_eq!(result.plots[2].values[1], PineValue::Na);
    assert_values_close(&result.plots[2].values[2..], &[0.0, 0.0, 0.0]);
}

#[test]
fn request_security_aligns_provider_higher_timeframe_tuple_literal_ta_events() {
    let program = compile_program(
        "indicator(\"request provider htf tuple literal ta events\")\n[since, prior] = request.security(\"NYSE:IBM\", \"5\", [ta.barssince(close > open), ta.valuewhen(close > 90, close, 1)])\nplot(since)\nplot(prior)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("higher timeframe provider tuple literal ta event request should run");

    assert_eq!(result.plots.len(), 2);
    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(&result.plots[0].values[2..], &[0.0, 0.0, 0.0]);
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_eq!(result.plots[1].values[2], PineValue::Na);
    assert_eq!(result.plots[1].values[3], PineValue::Na);
    assert_values_close(&result.plots[1].values[4..], &[100.0]);
}

#[test]
fn request_security_aligns_provider_higher_timeframe_tuple_literal_ta_bars() {
    let program = compile_program(
        "indicator(\"request provider htf tuple literal ta bars\")\n[highest_offset, lowest_offset] = request.security(\"NYSE:IBM\", \"5\", [ta.highestbars(close, 2), ta.lowestbars(close, 2)])\nplot(highest_offset)\nplot(lowest_offset)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("higher timeframe provider tuple literal ta bars request should run");

    assert_eq!(result.plots.len(), 2);
    for plot in &result.plots {
        assert_eq!(plot.values[0], PineValue::Na);
        assert_eq!(plot.values[1], PineValue::Na);
        assert_eq!(plot.values[2], PineValue::Na);
        assert_eq!(plot.values[3], PineValue::Na);
    }
    assert_values_close(&result.plots[0].values[4..], &[0.0]);
    assert_values_close(&result.plots[1].values[4..], &[1.0]);
}

#[test]
fn request_security_aligns_provider_higher_timeframe_tuple_literal_ta_pivots() {
    let program = compile_program(
        "indicator(\"request provider htf tuple literal ta pivots\")\n[pivot_high, pivot_low] = request.security(\"NYSE:IBM\", \"5\", [ta.pivothigh(300 - close, 0, 1), ta.pivotlow(close, 0, 1)])\nplot(pivot_high)\nplot(pivot_low)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("higher timeframe provider tuple literal ta pivot request should run");

    assert_eq!(result.plots.len(), 2);
    for plot in &result.plots {
        assert_eq!(plot.values[0], PineValue::Na);
        assert_eq!(plot.values[1], PineValue::Na);
        assert_eq!(plot.values[2], PineValue::Na);
        assert_eq!(plot.values[3], PineValue::Na);
    }
    assert_values_close(&result.plots[0].values[4..], &[200.0]);
    assert_values_close(&result.plots[1].values[4..], &[100.0]);
}

#[test]
fn request_security_aligns_provider_higher_timeframe_tuple_literal_ta_stats() {
    let program = compile_program(
        "indicator(\"request provider htf tuple literal ta stats\")\n[corr, cov] = request.security(\"NYSE:IBM\", \"5\", [ta.correlation(close, high, 2), ta.covariance(close, high, 2)])\nplot(corr)\nplot(cov)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("higher timeframe provider tuple literal ta stat request should run");

    assert_eq!(result.plots.len(), 2);
    for plot in &result.plots {
        assert_eq!(plot.values[0], PineValue::Na);
        assert_eq!(plot.values[1], PineValue::Na);
        assert_eq!(plot.values[2], PineValue::Na);
        assert_eq!(plot.values[3], PineValue::Na);
    }
    assert_values_close(&result.plots[0].values[4..], &[1.0]);
    assert_values_close(&result.plots[1].values[4..], &[2_500.0]);
}

#[test]
fn request_security_aligns_provider_higher_timeframe_tuple_literal_ta_window_stats() {
    let program = compile_program(
        "indicator(\"request provider htf tuple literal ta window stats\")\n[median_value, mode_value] = request.security(\"NYSE:IBM\", \"5\", [ta.median(close, 2), ta.mode(close, 2)])\nplot(median_value)\nplot(mode_value)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("higher timeframe provider tuple literal ta window stat request should run");

    assert_eq!(result.plots.len(), 2);
    for plot in &result.plots {
        assert_eq!(plot.values[0], PineValue::Na);
        assert_eq!(plot.values[1], PineValue::Na);
        assert_eq!(plot.values[2], PineValue::Na);
        assert_eq!(plot.values[3], PineValue::Na);
    }
    assert_values_close(&result.plots[0].values[4..], &[150.0]);
    assert_values_close(&result.plots[1].values[4..], &[100.0]);
}

#[test]
fn request_security_aligns_provider_higher_timeframe_tuple_literal_ta_percentiles() {
    let program = compile_program(
        "indicator(\"request provider htf tuple literal ta percentiles\")\n[nearest_rank, linear] = request.security(\"NYSE:IBM\", \"5\", [ta.percentile_nearest_rank(close, 2, 50), ta.percentile_linear_interpolation(close, 2, 50)])\nplot(nearest_rank)\nplot(linear)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("higher timeframe provider tuple literal ta percentile request should run");

    assert_eq!(result.plots.len(), 2);
    for plot in &result.plots {
        assert_eq!(plot.values[0], PineValue::Na);
        assert_eq!(plot.values[1], PineValue::Na);
        assert_eq!(plot.values[2], PineValue::Na);
        assert_eq!(plot.values[3], PineValue::Na);
    }
    assert_values_close(&result.plots[0].values[4..], &[100.0]);
    assert_values_close(&result.plots[1].values[4..], &[150.0]);
}

#[test]
fn request_security_aligns_provider_higher_timeframe_tuple_literal_ta_percentranks() {
    let program = compile_program(
        "indicator(\"request provider htf tuple literal ta percentranks\")\n[rank, inverse_rank] = request.security(\"NYSE:IBM\", \"5\", [ta.percentrank(close, 2), ta.percentrank(300 - close, 2)])\nplot(rank)\nplot(inverse_rank)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("higher timeframe provider tuple literal ta percentrank request should run");

    assert_eq!(result.plots.len(), 2);
    for plot in &result.plots {
        assert_eq!(plot.values[0], PineValue::Na);
        assert_eq!(plot.values[1], PineValue::Na);
        assert_eq!(plot.values[2], PineValue::Na);
        assert_eq!(plot.values[3], PineValue::Na);
    }
    assert_values_close(&result.plots[0].values[4..], &[100.0]);
    assert_values_close(&result.plots[1].values[4..], &[50.0]);
}

#[test]
fn request_security_aligns_provider_higher_timeframe_tuple_literal_ta_dispersion() {
    let program = compile_program(
        "indicator(\"request provider htf tuple literal ta dispersion\")\n[stdev_value, variance_value] = request.security(\"NYSE:IBM\", \"5\", [ta.stdev(close, 2), ta.variance(close, 2)])\nplot(stdev_value)\nplot(variance_value)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("higher timeframe provider tuple literal ta dispersion request should run");

    assert_eq!(result.plots.len(), 2);
    for plot in &result.plots {
        assert_eq!(plot.values[0], PineValue::Na);
        assert_eq!(plot.values[1], PineValue::Na);
        assert_eq!(plot.values[2], PineValue::Na);
        assert_eq!(plot.values[3], PineValue::Na);
    }
    assert_values_close(&result.plots[0].values[4..], &[50.0]);
    assert_values_close(&result.plots[1].values[4..], &[2_500.0]);
}

#[test]
fn request_security_aligns_provider_higher_timeframe_tuple_literal_ta_weighted_averages() {
    let program = compile_program(
        "indicator(\"request provider htf tuple literal ta weighted averages\")\n[wma_value, vwma_value] = request.security(\"NYSE:IBM\", \"5\", [ta.wma(close, 2), ta.vwma(close, 2)])\nplot(wma_value)\nplot(vwma_value)\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![
            timed_ohlcv(0, 90.0, 110.0, 80.0, 100.0, 1_000.0),
            timed_ohlcv(300_000, 190.0, 210.0, 180.0, 200.0, 1_000.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("higher timeframe provider tuple literal ta weighted average request should run");

    assert_eq!(result.plots.len(), 2);
    for plot in &result.plots {
        assert_eq!(plot.values[0], PineValue::Na);
        assert_eq!(plot.values[1], PineValue::Na);
        assert_eq!(plot.values[2], PineValue::Na);
        assert_eq!(plot.values[3], PineValue::Na);
    }
    assert_values_close(&result.plots[0].values[4..], &[166.666_666_666_666_66]);
    assert_values_close(&result.plots[1].values[4..], &[150.0]);
}

#[test]
fn request_security_isolates_provider_ta_state_from_chart_state() {
    let program = compile_program(
        "indicator(\"request ta\")\nprovider = request.security(\"NYSE:IBM\", timeframe.period, ta.sma(close, 2))\nchart = ta.sma(close, 2)\nplot(provider)\nplot(chart)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_bar(0, 20.0),
            timed_bar(60_000, 22.0),
            timed_bar(120_000, 24.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 7.0),
            timed_bar(120_000, 9.0),
        ])
        .expect("provider ta expression should run");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(&result.plots[0].values[1..], &[21.0, 23.0]);
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_values_close(&result.plots[1].values[1..], &[6.0, 8.0]);
}

#[test]
fn request_security_isolates_provider_rsi_state_from_chart_state() {
    let program = compile_program(
        "indicator(\"request rsi\")\nprovider = request.security(\"NYSE:IBM\", timeframe.period, ta.rsi(close, 3))\nchart = ta.rsi(close, 3)\nplot(provider)\nplot(chart)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_bar(0, 20.0),
            timed_bar(60_000, 22.0),
            timed_bar(120_000, 24.0),
            timed_bar(180_000, 22.0),
            timed_bar(240_000, 26.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 7.0),
            timed_bar(120_000, 9.0),
            timed_bar(180_000, 11.0),
            timed_bar(240_000, 13.0),
        ])
        .expect("provider ta.rsi expression should run");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(
        &result.plots[0].values[1..],
        &[100.0, 100.0, 66.66666666666666, 83.33333333333333],
    );
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_values_close(&result.plots[1].values[1..], &[100.0, 100.0, 100.0, 100.0]);
}

#[test]
fn request_security_isolates_provider_atr_state_from_chart_state() {
    let program = compile_program(
        "indicator(\"request atr\")\nprovider = request.security(\"NYSE:IBM\", timeframe.period, ta.atr(3))\nchart = ta.atr(3)\nplot(provider)\nplot(chart)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 9.0, 10.0, 8.0, 9.0, 100.0),
            timed_ohlcv(60_000, 11.0, 12.0, 11.0, 11.0, 100.0),
            timed_ohlcv(120_000, 7.0, 8.0, 6.0, 7.0, 100.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_ohlcv(0, 5.0, 5.5, 4.5, 5.0, 100.0),
            timed_ohlcv(60_000, 6.0, 6.5, 5.5, 6.0, 100.0),
            timed_ohlcv(120_000, 7.0, 7.5, 6.5, 7.0, 100.0),
        ])
        .expect("provider ta.atr expression should run");

    assert_values_close(
        &result.plots[0].values,
        &[2.0, 2.3333333333333335, 3.2222222222222223],
    );
    assert_values_close(
        &result.plots[1].values,
        &[1.0, 1.1666666666666667, 1.277777777777778],
    );
}

#[test]
fn request_security_evaluates_provider_true_range_in_requested_context() {
    let program = compile_program(
        "indicator(\"request tr\")\nprovider_tr = request.security(\"NYSE:IBM\", timeframe.period, ta.tr())\nprovider_strict = request.security(\"NYSE:IBM\", timeframe.period, ta.tr(false))\nchart_tr = ta.tr()\nchart_strict = ta.tr(false)\nplot(provider_tr)\nplot(provider_strict)\nplot(chart_tr)\nplot(chart_strict)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 9.0, 10.0, 8.0, 9.0, 100.0),
            timed_ohlcv(60_000, 11.0, 12.0, 11.0, 11.0, 100.0),
            timed_ohlcv(120_000, 7.0, 8.0, 6.0, 7.0, 100.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_ohlcv(0, 5.0, 5.5, 4.5, 5.0, 100.0),
            timed_ohlcv(60_000, 6.0, 6.5, 5.5, 6.0, 100.0),
            timed_ohlcv(120_000, 7.0, 7.5, 6.5, 7.0, 100.0),
        ])
        .expect("provider ta.tr expressions should run");

    assert_values_close(&result.plots[0].values, &[2.0, 3.0, 5.0]);
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_values_close(&result.plots[1].values[1..], &[3.0, 5.0]);
    assert_values_close(&result.plots[2].values, &[1.0, 1.5, 1.5]);
    assert_eq!(result.plots[3].values[0], PineValue::Na);
    assert_values_close(&result.plots[3].values[1..], &[1.5, 1.5]);
}

#[test]
fn request_security_isolates_provider_extrema_state_from_chart_state() {
    let program = compile_program(
        "indicator(\"request extrema\")\nprovider_hi = request.security(\"NYSE:IBM\", timeframe.period, ta.highest(3))\nprovider_lo = request.security(\"NYSE:IBM\", timeframe.period, ta.lowest(3))\nchart_hi = ta.highest(3)\nchart_lo = ta.lowest(3)\nplot(provider_hi)\nplot(provider_lo)\nplot(chart_hi)\nplot(chart_lo)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 1.0, 5.0, 1.0, 4.0, 100.0),
            timed_ohlcv(60_000, 1.0, 7.0, 2.0, 6.0, 100.0),
            timed_ohlcv(120_000, 1.0, 6.0, 3.0, 5.0, 100.0),
            timed_ohlcv(180_000, 1.0, 8.0, 0.0, 7.0, 100.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_ohlcv(0, 1.0, 3.0, 2.0, 2.0, 100.0),
            timed_ohlcv(60_000, 1.0, 4.0, 1.0, 3.0, 100.0),
            timed_ohlcv(120_000, 1.0, 5.0, 2.0, 4.0, 100.0),
            timed_ohlcv(180_000, 1.0, 6.0, 3.0, 5.0, 100.0),
        ])
        .expect("provider ta.highest/ta.lowest expressions should run");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(&result.plots[0].values[2..], &[7.0, 8.0]);
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_values_close(&result.plots[1].values[2..], &[1.0, 0.0]);
    assert_eq!(result.plots[2].values[0], PineValue::Na);
    assert_eq!(result.plots[2].values[1], PineValue::Na);
    assert_values_close(&result.plots[2].values[2..], &[5.0, 6.0]);
    assert_eq!(result.plots[3].values[0], PineValue::Na);
    assert_eq!(result.plots[3].values[1], PineValue::Na);
    assert_values_close(&result.plots[3].values[2..], &[1.0, 1.0]);
}

#[test]
fn request_security_evaluates_provider_momentum_in_requested_context() {
    let program = compile_program(
        "indicator(\"request momentum\")\nprovider_change = request.security(\"NYSE:IBM\", timeframe.period, ta.change(close))\nprovider_mom = request.security(\"NYSE:IBM\", timeframe.period, ta.mom(close, 2))\nprovider_roc = request.security(\"NYSE:IBM\", timeframe.period, ta.roc(close, 2))\nchart_change = ta.change(close)\nchart_mom = ta.mom(close, 2)\nchart_roc = ta.roc(close, 2)\nplot(provider_change)\nplot(provider_mom)\nplot(provider_roc)\nplot(chart_change)\nplot(chart_mom)\nplot(chart_roc)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_bar(0, 20.0),
            timed_bar(60_000, 22.0),
            timed_bar(120_000, 26.0),
            timed_bar(180_000, 25.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 7.0),
            timed_bar(120_000, 11.0),
            timed_bar(180_000, 17.0),
        ])
        .expect("provider ta.change/ta.mom/ta.roc expressions should run");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(&result.plots[0].values[1..], &[2.0, 4.0, -1.0]);
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_values_close(&result.plots[1].values[2..], &[6.0, 3.0]);
    assert_eq!(result.plots[2].values[0], PineValue::Na);
    assert_eq!(result.plots[2].values[1], PineValue::Na);
    assert_values_close(&result.plots[2].values[2..], &[30.0, 13.636363636363635]);
    assert_eq!(result.plots[3].values[0], PineValue::Na);
    assert_values_close(&result.plots[3].values[1..], &[2.0, 4.0, 6.0]);
    assert_eq!(result.plots[4].values[0], PineValue::Na);
    assert_eq!(result.plots[4].values[1], PineValue::Na);
    assert_values_close(&result.plots[4].values[2..], &[6.0, 10.0]);
    assert_eq!(result.plots[5].values[0], PineValue::Na);
    assert_eq!(result.plots[5].values[1], PineValue::Na);
    assert_values_close(&result.plots[5].values[2..], &[120.0, 142.85714285714286]);
}

#[test]
fn request_security_evaluates_provider_dispersion_in_requested_context() {
    let program = compile_program(
        "indicator(\"request dispersion\")\nprovider_range = request.security(\"NYSE:IBM\", timeframe.period, ta.range(close, 3))\nprovider_dev = request.security(\"NYSE:IBM\", timeframe.period, ta.dev(close, 3))\nchart_range = ta.range(close, 3)\nchart_dev = ta.dev(close, 3)\nplot(provider_range)\nplot(provider_dev)\nplot(chart_range)\nplot(chart_dev)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_bar(0, 20.0),
            timed_bar(60_000, 22.0),
            timed_bar(120_000, 21.0),
            timed_bar(180_000, 25.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 6.0),
            timed_bar(120_000, 8.0),
            timed_bar(180_000, 11.0),
        ])
        .expect("provider ta.range/ta.dev expressions should run");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(&result.plots[0].values[2..], &[2.0, 4.0]);
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_values_close(
        &result.plots[1].values[2..],
        &[0.6666666666666666, 1.5555555555555554],
    );
    assert_eq!(result.plots[2].values[0], PineValue::Na);
    assert_eq!(result.plots[2].values[1], PineValue::Na);
    assert_values_close(&result.plots[2].values[2..], &[3.0, 5.0]);
    assert_eq!(result.plots[3].values[0], PineValue::Na);
    assert_eq!(result.plots[3].values[1], PineValue::Na);
    assert_values_close(
        &result.plots[3].values[2..],
        &[1.1111111111111112, 1.7777777777777777],
    );
}

#[test]
fn request_security_evaluates_provider_stdev_in_requested_context() {
    let program = compile_program(
        "indicator(\"request stdev\")\nprovider_biased = request.security(\"NYSE:IBM\", timeframe.period, ta.stdev(close, 3))\nprovider_sample = request.security(\"NYSE:IBM\", timeframe.period, ta.stdev(close, 3, false))\nchart_biased = ta.stdev(close, 3)\nchart_sample = ta.stdev(close, 3, false)\nplot(provider_biased)\nplot(provider_sample)\nplot(chart_biased)\nplot(chart_sample)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_bar(0, 20.0),
            timed_bar(60_000, 21.0),
            timed_bar(120_000, 22.0),
            timed_bar(180_000, 24.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 7.0),
            timed_bar(120_000, 11.0),
            timed_bar(180_000, 17.0),
        ])
        .expect("provider ta.stdev expressions should run");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(
        &result.plots[0].values[2..],
        &[0.816496580927726, 1.247219128924647],
    );
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_values_close(&result.plots[1].values[2..], &[1.0, 1.5275252316519468]);
    assert_eq!(result.plots[2].values[0], PineValue::Na);
    assert_eq!(result.plots[2].values[1], PineValue::Na);
    assert_values_close(
        &result.plots[2].values[2..],
        &[2.494438257849294, 4.109609335312651],
    );
    assert_eq!(result.plots[3].values[0], PineValue::Na);
    assert_eq!(result.plots[3].values[1], PineValue::Na);
    assert_values_close(
        &result.plots[3].values[2..],
        &[3.0550504633038935, 5.033222956847166],
    );
}

#[test]
fn request_security_evaluates_provider_variance_in_requested_context() {
    let program = compile_program(
        "indicator(\"request variance\")\nprovider_biased = request.security(\"NYSE:IBM\", timeframe.period, ta.variance(close, 3))\nprovider_sample = request.security(\"NYSE:IBM\", timeframe.period, ta.variance(close, 3, false))\nchart_biased = ta.variance(close, 3)\nchart_sample = ta.variance(close, 3, false)\nplot(provider_biased)\nplot(provider_sample)\nplot(chart_biased)\nplot(chart_sample)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_bar(0, 20.0),
            timed_bar(60_000, 21.0),
            timed_bar(120_000, 22.0),
            timed_bar(180_000, 24.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 7.0),
            timed_bar(120_000, 11.0),
            timed_bar(180_000, 17.0),
        ])
        .expect("provider ta.variance expressions should run");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(
        &result.plots[0].values[2..],
        &[0.6666666666666666, 1.5555555555555556],
    );
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_values_close(&result.plots[1].values[2..], &[1.0, 2.3333333333333335]);
    assert_eq!(result.plots[2].values[0], PineValue::Na);
    assert_eq!(result.plots[2].values[1], PineValue::Na);
    assert_values_close(
        &result.plots[2].values[2..],
        &[6.222222222222221, 16.88888888888889],
    );
    assert_eq!(result.plots[3].values[0], PineValue::Na);
    assert_eq!(result.plots[3].values[1], PineValue::Na);
    assert_values_close(
        &result.plots[3].values[2..],
        &[9.333333333333332, 25.333333333333336],
    );
}

#[test]
fn request_security_evaluates_provider_wma_in_requested_context() {
    let program = compile_program(
        "indicator(\"request wma\")\nprovider_wma = request.security(\"NYSE:IBM\", timeframe.period, ta.wma(close, 3))\nchart_wma = ta.wma(close, 3)\nplot(provider_wma)\nplot(chart_wma)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_bar(0, 20.0),
            timed_bar(60_000, 21.0),
            timed_bar(120_000, 22.0),
            timed_bar(180_000, 24.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 7.0),
            timed_bar(120_000, 11.0),
            timed_bar(180_000, 17.0),
        ])
        .expect("provider ta.wma expression should run");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(
        &result.plots[0].values[2..],
        &[21.333333333333332, 22.833333333333332],
    );
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_values_close(
        &result.plots[1].values[2..],
        &[8.666666666666666, 13.333333333333334],
    );
}

#[test]
fn request_security_evaluates_provider_swma_in_requested_context() {
    let program = compile_program(
        "indicator(\"request swma\")\nprovider_swma = request.security(\"NYSE:IBM\", timeframe.period, ta.swma(close))\nchart_swma = ta.swma(close)\nplot(provider_swma)\nplot(chart_swma)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_bar(0, 20.0),
            timed_bar(60_000, 21.0),
            timed_bar(120_000, 22.0),
            timed_bar(180_000, 24.0),
            timed_bar(240_000, 27.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 7.0),
            timed_bar(120_000, 11.0),
            timed_bar(180_000, 17.0),
            timed_bar(240_000, 25.0),
        ])
        .expect("provider ta.swma expression should run");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_eq!(result.plots[0].values[2], PineValue::Na);
    assert_values_close(
        &result.plots[0].values[3..],
        &[21.666666666666668, 23.333333333333332],
    );
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_eq!(result.plots[1].values[2], PineValue::Na);
    assert_values_close(
        &result.plots[1].values[3..],
        &[9.666666666666666, 14.666666666666666],
    );
}

#[test]
fn request_security_evaluates_provider_hma_in_requested_context() {
    let program = compile_program(
        "indicator(\"request hma\")\nprovider_hma = request.security(\"NYSE:IBM\", timeframe.period, ta.hma(close, 4))\nchart_hma = ta.hma(close, 4)\nplot(provider_hma)\nplot(chart_hma)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_bar(0, 20.0),
            timed_bar(60_000, 21.0),
            timed_bar(120_000, 22.0),
            timed_bar(180_000, 24.0),
            timed_bar(240_000, 27.0),
            timed_bar(300_000, 31.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 7.0),
            timed_bar(120_000, 11.0),
            timed_bar(180_000, 17.0),
            timed_bar(240_000, 25.0),
            timed_bar(300_000, 35.0),
        ])
        .expect("provider ta.hma expression should run");

    for plot in &result.plots {
        assert_eq!(plot.values[0], PineValue::Na);
        assert_eq!(plot.values[1], PineValue::Na);
        assert_eq!(plot.values[2], PineValue::Na);
        assert_eq!(plot.values[3], PineValue::Na);
    }
    assert_values_close(
        &result.plots[0].values[4..],
        &[26.422222222222224, 30.38888888888889],
    );
    assert_values_close(
        &result.plots[1].values[4..],
        &[23.777777777777775, 33.77777777777778],
    );
}

#[test]
fn request_security_evaluates_provider_alma_in_requested_context() {
    let program = compile_program(
        "indicator(\"request alma\")\nprovider_alma = request.security(\"NYSE:IBM\", timeframe.period, ta.alma(close, 4, 0.85, 6))\nchart_alma = ta.alma(close, 4, 0.85, 6)\nplot(provider_alma)\nplot(chart_alma)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_bar(0, 20.0),
            timed_bar(60_000, 21.0),
            timed_bar(120_000, 22.0),
            timed_bar(180_000, 24.0),
            timed_bar(240_000, 27.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 7.0),
            timed_bar(120_000, 11.0),
            timed_bar(180_000, 17.0),
            timed_bar(240_000, 25.0),
        ])
        .expect("provider ta.alma expression should run");

    for plot in &result.plots {
        assert_eq!(plot.values[0], PineValue::Na);
        assert_eq!(plot.values[1], PineValue::Na);
        assert_eq!(plot.values[2], PineValue::Na);
    }
    assert_values_close(
        &result.plots[0].values[3..],
        &[22.96743661472369, 25.429886558589775],
    );
    assert_values_close(
        &result.plots[1].values[3..],
        &[13.859773117179548, 20.783828483300205],
    );
}

#[test]
fn request_security_evaluates_provider_bbw_in_requested_context() {
    let program = compile_program(
        "indicator(\"request bbw\")\nprovider_bbw = request.security(\"NYSE:IBM\", timeframe.period, ta.bbw(close, 3, 2))\nchart_bbw = ta.bbw(close, 3, 2)\nplot(provider_bbw)\nplot(chart_bbw)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_bar(0, 20.0),
            timed_bar(60_000, 21.0),
            timed_bar(120_000, 22.0),
            timed_bar(180_000, 24.0),
            timed_bar(240_000, 27.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 7.0),
            timed_bar(120_000, 11.0),
            timed_bar(180_000, 17.0),
            timed_bar(240_000, 25.0),
        ])
        .expect("provider ta.bbw expression should run");

    for plot in &result.plots {
        assert_eq!(plot.values[0], PineValue::Na);
        assert_eq!(plot.values[1], PineValue::Na);
    }
    assert_values_close(
        &result.plots[0].values[2..],
        &[0.15552315827194782, 0.22338253055366813, 0.3377761097517248],
    );
    assert_values_close(
        &result.plots[1].values[2..],
        &[1.3014460475735448, 1.4090089149643377, 1.2984641912517172],
    );
}

#[test]
fn request_security_evaluates_provider_kcw_in_requested_context() {
    let program = compile_program(
        "indicator(\"request kcw\")\nprovider_kcw = request.security(\"NYSE:IBM\", timeframe.period, ta.kcw(close, 2, 2, false))\nchart_kcw = ta.kcw(close, 2, 2, false)\nplot(provider_kcw)\nplot(chart_kcw)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 10.0, 1.0),
            timed_ohlcv(60_000, 12.0, 15.0, 14.0, 12.0, 1.0),
            timed_ohlcv(120_000, 9.0, 10.0, 8.0, 9.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_ohlcv(0, 5.0, 5.5, 4.5, 5.0, 1.0),
            timed_ohlcv(60_000, 6.0, 7.0, 5.0, 6.0, 1.0),
            timed_ohlcv(120_000, 4.0, 4.5, 3.5, 4.0, 1.0),
        ])
        .expect("provider ta.kcw expression should run");

    assert_values_close(
        &result.plots[0].values,
        &[0.8, 0.4705882352941177, 0.7272727272727272],
    );
    assert_values_close(
        &result.plots[1].values,
        &[0.8, 1.1764705882352942, 1.0731707317073171],
    );
}

#[test]
fn request_security_evaluates_provider_pivothigh_in_requested_context() {
    let program = compile_program(
        "indicator(\"request pivothigh\")\nprovider_ph = request.security(\"NYSE:IBM\", timeframe.period, ta.pivothigh(high, 1, 1))\nchart_ph = ta.pivothigh(high, 1, 1)\nplot(provider_ph)\nplot(chart_ph)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 10.0, 8.0, 9.0, 1.0),
            timed_ohlcv(60_000, 12.0, 12.0, 9.0, 11.0, 1.0),
            timed_ohlcv(120_000, 11.0, 11.0, 9.0, 10.0, 1.0),
            timed_ohlcv(180_000, 15.0, 15.0, 10.0, 14.0, 1.0),
            timed_ohlcv(240_000, 14.0, 14.0, 10.0, 13.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_ohlcv(0, 5.0, 5.0, 3.0, 4.0, 1.0),
            timed_ohlcv(60_000, 6.0, 6.0, 4.0, 5.0, 1.0),
            timed_ohlcv(120_000, 4.0, 4.0, 2.0, 3.0, 1.0),
            timed_ohlcv(180_000, 8.0, 8.0, 5.0, 7.0, 1.0),
            timed_ohlcv(240_000, 7.0, 7.0, 5.0, 6.0, 1.0),
        ])
        .expect("provider ta.pivothigh expression should run");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_eq!(result.plots[0].values[3], PineValue::Na);
    assert_values_close(&result.plots[0].values[2..3], &[12.0]);
    assert_values_close(&result.plots[0].values[4..], &[15.0]);

    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_eq!(result.plots[1].values[3], PineValue::Na);
    assert_values_close(&result.plots[1].values[2..3], &[6.0]);
    assert_values_close(&result.plots[1].values[4..], &[8.0]);
}

#[test]
fn request_security_evaluates_provider_pivotlow_in_requested_context() {
    let program = compile_program(
        "indicator(\"request pivotlow\")\nprovider_pl = request.security(\"NYSE:IBM\", timeframe.period, ta.pivotlow(low, 1, 1))\nchart_pl = ta.pivotlow(low, 1, 1)\nplot(provider_pl)\nplot(chart_pl)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 10.0, 8.0, 9.0, 1.0),
            timed_ohlcv(60_000, 12.0, 12.0, 6.0, 11.0, 1.0),
            timed_ohlcv(120_000, 11.0, 11.0, 7.0, 10.0, 1.0),
            timed_ohlcv(180_000, 15.0, 15.0, 5.0, 14.0, 1.0),
            timed_ohlcv(240_000, 14.0, 14.0, 7.0, 13.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_ohlcv(0, 5.0, 5.0, 3.0, 4.0, 1.0),
            timed_ohlcv(60_000, 6.0, 6.0, 1.0, 5.0, 1.0),
            timed_ohlcv(120_000, 4.0, 4.0, 2.0, 3.0, 1.0),
            timed_ohlcv(180_000, 8.0, 8.0, 0.0, 7.0, 1.0),
            timed_ohlcv(240_000, 7.0, 7.0, 2.0, 6.0, 1.0),
        ])
        .expect("provider ta.pivotlow expression should run");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_eq!(result.plots[0].values[3], PineValue::Na);
    assert_values_close(&result.plots[0].values[2..3], &[6.0]);
    assert_values_close(&result.plots[0].values[4..], &[5.0]);

    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_eq!(result.plots[1].values[3], PineValue::Na);
    assert_values_close(&result.plots[1].values[2..3], &[1.0]);
    assert_values_close(&result.plots[1].values[4..], &[0.0]);
}

#[test]
fn request_security_evaluates_provider_barssince_in_requested_context() {
    let program = compile_program(
        "indicator(\"request barssince\")\nprovider_since = request.security(\"NYSE:IBM\", timeframe.period, ta.barssince(close > open))\nchart_since = ta.barssince(close > open)\nplot(provider_since)\nplot(chart_since)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 1.0, 1.0, 1.0, 1.0, 1.0),
            timed_ohlcv(60_000, 2.0, 2.0, 2.0, 2.0, 1.0),
            timed_ohlcv(120_000, 2.0, 3.0, 2.0, 3.0, 1.0),
            timed_ohlcv(180_000, 4.0, 4.0, 3.0, 3.0, 1.0),
            timed_ohlcv(240_000, 4.0, 5.0, 4.0, 5.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_ohlcv(0, 1.0, 2.0, 1.0, 2.0, 1.0),
            timed_ohlcv(60_000, 3.0, 3.0, 2.0, 2.0, 1.0),
            timed_ohlcv(120_000, 4.0, 4.0, 3.0, 3.0, 1.0),
            timed_ohlcv(180_000, 4.0, 5.0, 4.0, 5.0, 1.0),
            timed_ohlcv(240_000, 6.0, 6.0, 5.0, 5.0, 1.0),
        ])
        .expect("provider ta.barssince expression should run");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(&result.plots[0].values[2..], &[0.0, 1.0, 0.0]);
    assert_values_close(&result.plots[1].values, &[0.0, 1.0, 2.0, 0.0, 1.0]);
}

#[test]
fn request_security_evaluates_provider_highestbars_in_requested_context() {
    let program = compile_program(
        "indicator(\"request highestbars\")\nprovider_hi = request.security(\"NYSE:IBM\", timeframe.period, ta.highestbars(close, 3))\nchart_hi = ta.highestbars(close, 3)\nplot(provider_hi)\nplot(chart_hi)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_bar(0, 1.0),
            timed_bar(60_000, 3.0),
            timed_bar(120_000, 2.0),
            timed_bar(180_000, 5.0),
            timed_bar(240_000, 5.0),
            timed_bar(300_000, 4.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 4.0),
            timed_bar(60_000, 2.0),
            timed_bar(120_000, 3.0),
            timed_bar(180_000, 1.0),
            timed_bar(240_000, 5.0),
            timed_bar(300_000, 4.0),
        ])
        .expect("provider ta.highestbars expression should run");

    for plot in &result.plots {
        assert_eq!(plot.values[0], PineValue::Na);
        assert_eq!(plot.values[1], PineValue::Na);
    }
    assert_values_close(&result.plots[0].values[2..], &[1.0, 0.0, 0.0, 1.0]);
    assert_values_close(&result.plots[1].values[2..], &[2.0, 1.0, 0.0, 1.0]);
}

#[test]
fn request_security_evaluates_provider_lowestbars_in_requested_context() {
    let program = compile_program(
        "indicator(\"request lowestbars\")\nprovider_lo = request.security(\"NYSE:IBM\", timeframe.period, ta.lowestbars(close, 3))\nchart_lo = ta.lowestbars(close, 3)\nplot(provider_lo)\nplot(chart_lo)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_bar(0, 4.0),
            timed_bar(60_000, 2.0),
            timed_bar(120_000, 3.0),
            timed_bar(180_000, 1.0),
            timed_bar(240_000, 5.0),
            timed_bar(300_000, 4.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 3.0),
            timed_bar(120_000, 2.0),
            timed_bar(180_000, 5.0),
            timed_bar(240_000, 5.0),
            timed_bar(300_000, 4.0),
        ])
        .expect("provider ta.lowestbars expression should run");

    for plot in &result.plots {
        assert_eq!(plot.values[0], PineValue::Na);
        assert_eq!(plot.values[1], PineValue::Na);
    }
    assert_values_close(&result.plots[0].values[2..], &[1.0, 0.0, 1.0, 2.0]);
    assert_values_close(&result.plots[1].values[2..], &[2.0, 1.0, 2.0, 0.0]);
}

#[test]
fn request_security_evaluates_provider_valuewhen_in_requested_context() {
    let program = compile_program(
        "indicator(\"request valuewhen\")\nprovider_value = request.security(\"NYSE:IBM\", timeframe.period, ta.valuewhen(close > 2, close, 1))\nchart_value = ta.valuewhen(close > 3, close, 1)\nplot(provider_value)\nplot(chart_value)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_bar(0, 1.0),
            timed_bar(60_000, 3.0),
            timed_bar(120_000, 2.0),
            timed_bar(180_000, 5.0),
            timed_bar(240_000, 4.0),
            timed_bar(300_000, 6.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 4.0),
            timed_bar(60_000, 1.0),
            timed_bar(120_000, 5.0),
            timed_bar(180_000, 2.0),
            timed_bar(240_000, 6.0),
            timed_bar(300_000, 3.0),
        ])
        .expect("provider ta.valuewhen expression should run");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_eq!(result.plots[0].values[2], PineValue::Na);
    assert_values_close(&result.plots[0].values[3..], &[3.0, 5.0, 4.0]);

    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_values_close(&result.plots[1].values[2..], &[4.0, 4.0, 5.0, 5.0]);
}

#[test]
fn request_security_evaluates_provider_vwap_in_requested_context() {
    let program = compile_program(
        "indicator(\"request vwap\")\nprovider_vwap = request.security(\"NYSE:IBM\", timeframe.period, ta.vwap(close))\nchart_vwap = ta.vwap(close)\nplot(provider_vwap)\nplot(chart_vwap)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 20.0, 100.0),
            timed_ohlcv(60_000, 11.0, 12.0, 10.0, 21.0, 200.0),
            timed_ohlcv(120_000, 12.0, 13.0, 11.0, 22.0, 300.0),
            timed_ohlcv(180_000, 13.0, 14.0, 12.0, 23.0, 400.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_ohlcv(0, 1.0, 2.0, 0.0, 4.0, 1.0),
            timed_ohlcv(60_000, 2.0, 3.0, 1.0, 5.0, 2.0),
            timed_ohlcv(120_000, 3.0, 4.0, 2.0, 6.0, 3.0),
            timed_ohlcv(180_000, 4.0, 5.0, 3.0, 7.0, 4.0),
        ])
        .expect("provider ta.vwap expression should run");

    assert_values_close(
        &result.plots[0].values,
        &[20.0, 20.666666666666668, 21.333333333333332, 22.0],
    );
    assert_values_close(
        &result.plots[1].values,
        &[4.0, 4.666666666666667, 5.333333333333333, 6.0],
    );
}

#[test]
fn request_security_evaluates_provider_accdist_variable_in_requested_context() {
    let program = compile_program(
        "indicator(\"request accdist\")\nprovider_accdist = request.security(\"NYSE:IBM\", timeframe.period, ta.accdist)\nchart_accdist = ta.accdist\nplot(provider_accdist)\nplot(chart_accdist)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 15.0, 5.0, 12.0, 100.0),
            timed_ohlcv(60_000, 20.0, 30.0, 10.0, 25.0, 40.0),
            timed_ohlcv(120_000, 10.0, 10.0, 10.0, 10.0, 30.0),
            timed_ohlcv(180_000, 10.0, 10.0, 0.0, 8.0, 50.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_ohlcv(0, 1.0, 4.0, 0.0, 3.0, 8.0),
            timed_ohlcv(60_000, 2.0, 6.0, 2.0, 5.0, 6.0),
            timed_ohlcv(120_000, 3.0, 3.0, 3.0, 3.0, 7.0),
            timed_ohlcv(180_000, 2.0, 5.0, 1.0, 2.0, 9.0),
        ])
        .expect("provider ta.accdist variable expression should run");

    assert_values_close(&result.plots[0].values[..2], &[40.0, 60.0]);
    assert_eq!(result.plots[0].values[2], PineValue::Na);
    assert_values_close(&result.plots[0].values[3..], &[30.0]);
    assert_values_close(&result.plots[1].values[..2], &[4.0, 7.0]);
    assert_eq!(result.plots[1].values[2], PineValue::Na);
    assert_values_close(&result.plots[1].values[3..], &[-4.5]);
}

#[test]
fn request_security_evaluates_provider_iii_variable_in_requested_context() {
    let program = compile_program(
        "indicator(\"request iii\")\nprovider_iii = request.security(\"NYSE:IBM\", timeframe.period, ta.iii)\nchart_iii = ta.iii\nplot(provider_iii)\nplot(chart_iii)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 15.0, 5.0, 12.0, 100.0),
            timed_ohlcv(60_000, 12.0, 20.0, 10.0, 5.0, 2.0),
            timed_ohlcv(120_000, 10.0, 10.0, 10.0, 10.0, 10.0),
            timed_ohlcv(180_000, 10.0, 20.0, 10.0, 15.0, 0.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_ohlcv(0, 1.0, 4.0, 0.0, 3.0, 8.0),
            timed_ohlcv(60_000, 2.0, 6.0, 2.0, 5.0, 6.0),
            timed_ohlcv(120_000, 3.0, 3.0, 3.0, 3.0, 7.0),
            timed_ohlcv(180_000, 2.0, 5.0, 1.0, 2.0, 9.0),
        ])
        .expect("provider ta.iii variable expression should run");

    assert_values_close(&result.plots[0].values[..2], &[0.004, -1.0]);
    assert_eq!(result.plots[0].values[2], PineValue::Na);
    assert_eq!(result.plots[0].values[3], PineValue::Na);
    assert_values_close(&result.plots[1].values[..2], &[0.0625, 0.08333333333333333]);
    assert_eq!(result.plots[1].values[2], PineValue::Na);
    assert_values_close(&result.plots[1].values[3..], &[-0.05555555555555555]);
}

#[test]
fn request_security_evaluates_provider_nvi_variable_in_requested_context() {
    let program = compile_program(
        "indicator(\"request nvi\")\nprovider_nvi = request.security(\"NYSE:IBM\", timeframe.period, ta.nvi)\nchart_nvi = ta.nvi\nplot(provider_nvi)\nplot(chart_nvi)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 10.0, 100.0),
            timed_ohlcv(60_000, 12.0, 13.0, 11.0, 12.0, 90.0),
            timed_ohlcv(120_000, 6.0, 7.0, 5.0, 6.0, 120.0),
            timed_ohlcv(180_000, 9.0, 10.0, 8.0, 9.0, 80.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_ohlcv(0, 20.0, 21.0, 19.0, 20.0, 50.0),
            timed_ohlcv(60_000, 10.0, 11.0, 9.0, 10.0, 40.0),
            timed_ohlcv(120_000, 15.0, 16.0, 14.0, 15.0, 60.0),
            timed_ohlcv(180_000, 30.0, 31.0, 29.0, 30.0, 30.0),
        ])
        .expect("provider ta.nvi variable expression should run");

    assert_values_close(&result.plots[0].values, &[1.0, 1.2, 1.2, 1.8]);
    assert_values_close(&result.plots[1].values, &[1.0, 0.5, 0.5, 1.0]);
}

#[test]
fn request_security_evaluates_provider_obv_variable_in_requested_context() {
    let program = compile_program(
        "indicator(\"request obv\")\nprovider_obv = request.security(\"NYSE:IBM\", timeframe.period, ta.obv)\nchart_obv = ta.obv\nplot(provider_obv)\nplot(chart_obv)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 20.0, 100.0),
            timed_ohlcv(60_000, 11.0, 12.0, 10.0, 21.0, 100.0),
            timed_ohlcv(120_000, 12.0, 13.0, 11.0, 22.0, 100.0),
            timed_ohlcv(180_000, 13.0, 14.0, 12.0, 23.0, 100.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_ohlcv(0, 1.0, 2.0, 0.0, 4.0, 1.0),
            timed_ohlcv(60_000, 2.0, 3.0, 1.0, 5.0, 1.0),
            timed_ohlcv(120_000, 3.0, 4.0, 2.0, 6.0, 1.0),
            timed_ohlcv(180_000, 4.0, 5.0, 3.0, 7.0, 1.0),
        ])
        .expect("provider ta.obv variable expression should run");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(&result.plots[0].values[1..], &[100.0, 200.0, 300.0]);
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_values_close(&result.plots[1].values[1..], &[1.0, 2.0, 3.0]);
}

#[test]
fn request_security_evaluates_provider_pvi_variable_in_requested_context() {
    let program = compile_program(
        "indicator(\"request pvi\")\nprovider_pvi = request.security(\"NYSE:IBM\", timeframe.period, ta.pvi)\nchart_pvi = ta.pvi\nplot(provider_pvi)\nplot(chart_pvi)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 10.0, 100.0),
            timed_ohlcv(60_000, 12.0, 13.0, 11.0, 12.0, 90.0),
            timed_ohlcv(120_000, 6.0, 7.0, 5.0, 6.0, 120.0),
            timed_ohlcv(180_000, 9.0, 10.0, 8.0, 9.0, 80.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_ohlcv(0, 20.0, 21.0, 19.0, 20.0, 50.0),
            timed_ohlcv(60_000, 10.0, 11.0, 9.0, 10.0, 40.0),
            timed_ohlcv(120_000, 15.0, 16.0, 14.0, 15.0, 60.0),
            timed_ohlcv(180_000, 30.0, 31.0, 29.0, 30.0, 30.0),
        ])
        .expect("provider ta.pvi variable expression should run");

    assert_values_close(&result.plots[0].values, &[1.0, 1.0, 0.5, 0.5]);
    assert_values_close(&result.plots[1].values, &[1.0, 1.0, 1.5, 1.5]);
}

#[test]
fn request_security_evaluates_provider_pvt_variable_in_requested_context() {
    let program = compile_program(
        "indicator(\"request pvt\")\nprovider_pvt = request.security(\"NYSE:IBM\", timeframe.period, ta.pvt)\nchart_pvt = ta.pvt\nplot(provider_pvt)\nplot(chart_pvt)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 20.0, 100.0),
            timed_ohlcv(60_000, 11.0, 12.0, 10.0, 21.0, 100.0),
            timed_ohlcv(120_000, 12.0, 13.0, 11.0, 22.0, 100.0),
            timed_ohlcv(180_000, 13.0, 14.0, 12.0, 23.0, 100.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_ohlcv(0, 1.0, 2.0, 0.0, 4.0, 1.0),
            timed_ohlcv(60_000, 2.0, 3.0, 1.0, 5.0, 1.0),
            timed_ohlcv(120_000, 3.0, 4.0, 2.0, 6.0, 1.0),
            timed_ohlcv(180_000, 4.0, 5.0, 3.0, 7.0, 1.0),
        ])
        .expect("provider ta.pvt variable expression should run");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(
        &result.plots[0].values[1..],
        &[5.0, 9.761904761904763, 14.307359307359308],
    );
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_values_close(
        &result.plots[1].values[1..],
        &[0.25, 0.45, 0.6166666666666667],
    );
}

#[test]
fn request_security_evaluates_provider_wvad_variable_in_requested_context() {
    let program = compile_program(
        "indicator(\"request wvad\")\nprovider_wvad = request.security(\"NYSE:IBM\", timeframe.period, ta.wvad)\nchart_wvad = ta.wvad\nplot(provider_wvad)\nplot(chart_wvad)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 15.0, 5.0, 12.0, 100.0),
            timed_ohlcv(60_000, 20.0, 30.0, 10.0, 25.0, 40.0),
            timed_ohlcv(120_000, 10.0, 10.0, 10.0, 10.0, 30.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_ohlcv(0, 1.0, 4.0, 0.0, 3.0, 8.0),
            timed_ohlcv(60_000, 2.0, 6.0, 2.0, 5.0, 6.0),
            timed_ohlcv(120_000, 3.0, 3.0, 3.0, 3.0, 7.0),
        ])
        .expect("provider ta.wvad variable expression should run");

    assert_values_close(&result.plots[0].values[..2], &[20.0, 10.0]);
    assert_eq!(result.plots[0].values[2], PineValue::Na);
    assert_values_close(&result.plots[1].values[..2], &[4.0, 4.5]);
    assert_eq!(result.plots[1].values[2], PineValue::Na);
}

#[test]
fn request_security_evaluates_provider_correlation_in_requested_context() {
    let program = compile_program(
        "indicator(\"request correlation\")\nprovider_corr = request.security(\"NYSE:IBM\", timeframe.period, ta.correlation(close, high, 3))\nchart_corr = ta.correlation(close, high, 3)\nplot(provider_corr)\nplot(chart_corr)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 20.0, 25.0, 19.0, 20.0, 1.0),
            timed_ohlcv(60_000, 21.0, 23.0, 20.0, 21.0, 1.0),
            timed_ohlcv(120_000, 22.0, 26.0, 21.0, 22.0, 1.0),
            timed_ohlcv(180_000, 24.0, 28.0, 23.0, 24.0, 1.0),
            timed_ohlcv(240_000, 27.0, 31.0, 26.0, 27.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_ohlcv(0, 5.0, 6.0, 4.0, 5.0, 1.0),
            timed_ohlcv(60_000, 7.0, 9.0, 6.0, 7.0, 1.0),
            timed_ohlcv(120_000, 11.0, 13.0, 10.0, 11.0, 1.0),
            timed_ohlcv(180_000, 17.0, 20.0, 16.0, 17.0, 1.0),
            timed_ohlcv(240_000, 25.0, 30.0, 24.0, 25.0, 1.0),
        ])
        .expect("provider ta.correlation expression should run");

    for plot in &result.plots {
        assert_eq!(plot.values[0], PineValue::Na);
        assert_eq!(plot.values[1], PineValue::Na);
    }
    assert_values_close(
        &result.plots[0].values[2..],
        &[0.3273268353539886, 0.9538209664765321, 1.0],
    );
    assert_values_close(
        &result.plots[1].values[2..],
        &[0.9941916256019202, 0.9991507429465935, 0.9998148662392726],
    );
}

#[test]
fn request_security_evaluates_provider_covariance_in_requested_context() {
    let program = compile_program(
        "indicator(\"request covariance\")\nprovider_cov = request.security(\"NYSE:IBM\", timeframe.period, ta.covariance(close, high, 3))\nchart_cov = ta.covariance(close, high, 3)\nplot(provider_cov)\nplot(chart_cov)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 20.0, 25.0, 19.0, 20.0, 1.0),
            timed_ohlcv(60_000, 21.0, 23.0, 20.0, 21.0, 1.0),
            timed_ohlcv(120_000, 22.0, 26.0, 21.0, 22.0, 1.0),
            timed_ohlcv(180_000, 24.0, 28.0, 23.0, 24.0, 1.0),
            timed_ohlcv(240_000, 27.0, 31.0, 26.0, 27.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_ohlcv(0, 5.0, 6.0, 4.0, 5.0, 1.0),
            timed_ohlcv(60_000, 7.0, 9.0, 6.0, 7.0, 1.0),
            timed_ohlcv(120_000, 11.0, 13.0, 10.0, 11.0, 1.0),
            timed_ohlcv(180_000, 17.0, 20.0, 16.0, 17.0, 1.0),
            timed_ohlcv(240_000, 25.0, 30.0, 24.0, 25.0, 1.0),
        ])
        .expect("provider ta.covariance expression should run");

    for plot in &result.plots {
        assert_eq!(plot.values[0], PineValue::Na);
        assert_eq!(plot.values[1], PineValue::Na);
    }
    assert_values_close(
        &result.plots[0].values[2..],
        &[0.3333333333333333, 2.4444444444444446, 4.222222222222222],
    );
    assert_values_close(
        &result.plots[1].values[2..],
        &[7.111111111111112, 18.666666666666664, 40.0],
    );
}

#[test]
fn request_security_evaluates_provider_median_in_requested_context() {
    let program = compile_program(
        "indicator(\"request median\")\nprovider_median = request.security(\"NYSE:IBM\", timeframe.period, ta.median(close, 3))\nchart_median = ta.median(close, 3)\nplot(provider_median)\nplot(chart_median)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_bar(0, 20.0),
            timed_bar(60_000, 21.0),
            timed_bar(120_000, 22.0),
            timed_bar(180_000, 24.0),
            timed_bar(240_000, 27.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 7.0),
            timed_bar(120_000, 11.0),
            timed_bar(180_000, 17.0),
            timed_bar(240_000, 25.0),
        ])
        .expect("provider ta.median expression should run");

    for plot in &result.plots {
        assert_eq!(plot.values[0], PineValue::Na);
        assert_eq!(plot.values[1], PineValue::Na);
    }
    assert_values_close(&result.plots[0].values[2..], &[21.0, 22.0, 24.0]);
    assert_values_close(&result.plots[1].values[2..], &[7.0, 11.0, 17.0]);
}

#[test]
fn request_security_evaluates_provider_mode_in_requested_context() {
    let program = compile_program(
        "indicator(\"request mode\")\nprovider_mode = request.security(\"NYSE:IBM\", timeframe.period, ta.mode(close, 3))\nchart_mode = ta.mode(close, 3)\nplot(provider_mode)\nplot(chart_mode)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_bar(0, 20.0),
            timed_bar(60_000, 21.0),
            timed_bar(120_000, 22.0),
            timed_bar(180_000, 24.0),
            timed_bar(240_000, 27.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 7.0),
            timed_bar(120_000, 11.0),
            timed_bar(180_000, 17.0),
            timed_bar(240_000, 25.0),
        ])
        .expect("provider ta.mode expression should run");

    for plot in &result.plots {
        assert_eq!(plot.values[0], PineValue::Na);
        assert_eq!(plot.values[1], PineValue::Na);
    }
    assert_values_close(&result.plots[0].values[2..], &[20.0, 21.0, 22.0]);
    assert_values_close(&result.plots[1].values[2..], &[5.0, 7.0, 11.0]);
}

#[test]
fn request_security_evaluates_provider_percentile_nearest_rank_in_requested_context() {
    let program = compile_program(
        "indicator(\"request percentile nearest rank\")\nprovider_percentile = request.security(\"NYSE:IBM\", timeframe.period, ta.percentile_nearest_rank(close, 3, 50))\nchart_percentile = ta.percentile_nearest_rank(close, 3, 50)\nplot(provider_percentile)\nplot(chart_percentile)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_bar(0, 20.0),
            timed_bar(60_000, 21.0),
            timed_bar(120_000, 22.0),
            timed_bar(180_000, 24.0),
            timed_bar(240_000, 27.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 7.0),
            timed_bar(120_000, 11.0),
            timed_bar(180_000, 17.0),
            timed_bar(240_000, 25.0),
        ])
        .expect("provider ta.percentile_nearest_rank expression should run");

    for plot in &result.plots {
        assert_eq!(plot.values[0], PineValue::Na);
        assert_eq!(plot.values[1], PineValue::Na);
    }
    assert_values_close(&result.plots[0].values[2..], &[21.0, 22.0, 24.0]);
    assert_values_close(&result.plots[1].values[2..], &[7.0, 11.0, 17.0]);
}

#[test]
fn request_security_evaluates_provider_percentile_linear_interpolation_in_requested_context() {
    let program = compile_program(
        "indicator(\"request percentile linear\")\nprovider_percentile = request.security(\"NYSE:IBM\", timeframe.period, ta.percentile_linear_interpolation(close, 3, 50))\nchart_percentile = ta.percentile_linear_interpolation(close, 3, 50)\nplot(provider_percentile)\nplot(chart_percentile)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_bar(0, 20.0),
            timed_bar(60_000, 21.0),
            timed_bar(120_000, 22.0),
            timed_bar(180_000, 24.0),
            timed_bar(240_000, 27.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 7.0),
            timed_bar(120_000, 11.0),
            timed_bar(180_000, 17.0),
            timed_bar(240_000, 25.0),
        ])
        .expect("provider ta.percentile_linear_interpolation expression should run");

    for plot in &result.plots {
        assert_eq!(plot.values[0], PineValue::Na);
        assert_eq!(plot.values[1], PineValue::Na);
    }
    assert_values_close(&result.plots[0].values[2..], &[21.0, 22.0, 24.0]);
    assert_values_close(&result.plots[1].values[2..], &[7.0, 11.0, 17.0]);
}

#[test]
fn request_security_evaluates_provider_percentrank_in_requested_context() {
    let program = compile_program(
        "indicator(\"request percentrank\")\nprovider_rank = request.security(\"NYSE:IBM\", timeframe.period, ta.percentrank(close, 3))\nchart_rank = ta.percentrank(close, 3)\nplot(provider_rank)\nplot(chart_rank)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_bar(0, 20.0),
            timed_bar(60_000, 21.0),
            timed_bar(120_000, 22.0),
            timed_bar(180_000, 24.0),
            timed_bar(240_000, 27.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 7.0),
            timed_bar(120_000, 11.0),
            timed_bar(180_000, 17.0),
            timed_bar(240_000, 25.0),
        ])
        .expect("provider ta.percentrank expression should run");

    for plot in &result.plots {
        assert_eq!(plot.values[0], PineValue::Na);
        assert_eq!(plot.values[1], PineValue::Na);
    }
    assert_values_close(&result.plots[0].values[2..], &[100.0, 100.0, 100.0]);
    assert_values_close(&result.plots[1].values[2..], &[100.0, 100.0, 100.0]);
}

#[test]
fn request_security_evaluates_provider_vwma_in_requested_context() {
    let program = compile_program(
        "indicator(\"request vwma\")\nprovider_vwma = request.security(\"NYSE:IBM\", timeframe.period, ta.vwma(close, 3))\nchart_vwma = ta.vwma(close, 3)\nplot(provider_vwma)\nplot(chart_vwma)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 20.0, 20.0, 20.0, 20.0, 10.0),
            timed_ohlcv(60_000, 21.0, 21.0, 21.0, 21.0, 20.0),
            timed_ohlcv(120_000, 22.0, 22.0, 22.0, 22.0, 30.0),
            timed_ohlcv(180_000, 24.0, 24.0, 24.0, 24.0, 40.0),
            timed_ohlcv(240_000, 27.0, 27.0, 27.0, 27.0, 50.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_ohlcv(0, 5.0, 5.0, 5.0, 5.0, 100.0),
            timed_ohlcv(60_000, 7.0, 7.0, 7.0, 7.0, 80.0),
            timed_ohlcv(120_000, 11.0, 11.0, 11.0, 11.0, 60.0),
            timed_ohlcv(180_000, 17.0, 17.0, 17.0, 17.0, 40.0),
            timed_ohlcv(240_000, 25.0, 25.0, 25.0, 25.0, 20.0),
        ])
        .expect("provider ta.vwma expression should run");

    for plot in &result.plots {
        assert_eq!(plot.values[0], PineValue::Na);
        assert_eq!(plot.values[1], PineValue::Na);
    }
    assert_values_close(
        &result.plots[0].values[2..],
        &[21.333333333333332, 22.666666666666668, 24.75],
    );
    assert_values_close(
        &result.plots[1].values[2..],
        &[7.166666666666667, 10.555555555555555, 15.333333333333334],
    );
}

#[test]
fn request_security_evaluates_provider_rma_in_requested_context() {
    let program = compile_program(
        "indicator(\"request rma\")\nprovider_rma = request.security(\"NYSE:IBM\", timeframe.period, ta.rma(close, 3))\nchart_rma = ta.rma(close, 3)\nplot(provider_rma)\nplot(chart_rma)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_bar(0, 20.0),
            timed_bar(60_000, 21.0),
            timed_bar(120_000, 22.0),
            timed_bar(180_000, 24.0),
            timed_bar(240_000, 27.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 7.0),
            timed_bar(120_000, 11.0),
            timed_bar(180_000, 17.0),
            timed_bar(240_000, 25.0),
        ])
        .expect("provider ta.rma expression should run");

    assert_values_close(
        &result.plots[0].values,
        &[
            20.0,
            20.333333333333332,
            20.88888888888889,
            21.925925925925927,
            23.617283950617285,
        ],
    );
    assert_values_close(
        &result.plots[1].values,
        &[
            5.0,
            5.666666666666667,
            7.444444444444445,
            10.62962962962963,
            15.419753086419753,
        ],
    );
}

#[test]
fn request_security_evaluates_provider_dema_in_requested_context() {
    let program = compile_program(
        "indicator(\"request dema\")\nprovider_dema = request.security(\"NYSE:IBM\", timeframe.period, ta.dema(close, 3))\nchart_dema = ta.dema(close, 3)\nplot(provider_dema)\nplot(chart_dema)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_bar(0, 20.0),
            timed_bar(60_000, 21.0),
            timed_bar(120_000, 22.0),
            timed_bar(180_000, 24.0),
            timed_bar(240_000, 27.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 7.0),
            timed_bar(120_000, 11.0),
            timed_bar(180_000, 17.0),
            timed_bar(240_000, 25.0),
        ])
        .expect("provider ta.dema expression should run");

    assert_values_close(
        &result.plots[0].values,
        &[20.0, 20.75, 21.75, 23.5625, 26.375],
    );
    assert_values_close(&result.plots[1].values, &[5.0, 6.5, 10.0, 15.625, 23.375]);
}

#[test]
fn request_security_evaluates_provider_tema_in_requested_context() {
    let program = compile_program(
        "indicator(\"request tema\")\nprovider_tema = request.security(\"NYSE:IBM\", timeframe.period, ta.tema(close, 3))\nchart_tema = ta.tema(close, 3)\nplot(provider_tema)\nplot(chart_tema)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_bar(0, 20.0),
            timed_bar(60_000, 21.0),
            timed_bar(120_000, 22.0),
            timed_bar(180_000, 24.0),
            timed_bar(240_000, 27.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 7.0),
            timed_bar(120_000, 11.0),
            timed_bar(180_000, 17.0),
            timed_bar(240_000, 25.0),
        ])
        .expect("provider ta.tema expression should run");

    assert_values_close(
        &result.plots[0].values,
        &[20.0, 20.875, 21.9375, 23.875, 26.84375],
    );
    assert_values_close(
        &result.plots[1].values,
        &[5.0, 6.75, 10.625, 16.625, 24.6875],
    );
}

#[test]
fn request_security_evaluates_provider_tsi_in_requested_context() {
    let program = compile_program(
        "indicator(\"request tsi\")\nprovider_tsi = request.security(\"NYSE:IBM\", timeframe.period, ta.tsi(close, 2, 3))\nchart_tsi = ta.tsi(close, 2, 3)\nplot(provider_tsi)\nplot(chart_tsi)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_bar(0, 10.0),
            timed_bar(60_000, 11.0),
            timed_bar(120_000, 12.0),
            timed_bar(180_000, 10.0),
            timed_bar(240_000, 13.0),
            timed_bar(300_000, 12.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 7.0),
            timed_bar(120_000, 11.0),
            timed_bar(180_000, 17.0),
            timed_bar(240_000, 25.0),
            timed_bar(300_000, 26.0),
        ])
        .expect("provider ta.tsi expression should run");

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
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_values_close(&result.plots[1].values[1..], &[1.0, 1.0, 1.0, 1.0, 1.0]);
}

#[test]
fn request_security_evaluates_provider_cmo_in_requested_context() {
    let program = compile_program(
        "indicator(\"request cmo\")\nprovider_cmo = request.security(\"NYSE:IBM\", timeframe.period, ta.cmo(close, 3))\nchart_cmo = ta.cmo(close, 3)\nplot(provider_cmo)\nplot(chart_cmo)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_bar(0, 10.0),
            timed_bar(60_000, 11.0),
            timed_bar(120_000, 12.0),
            timed_bar(180_000, 10.0),
            timed_bar(240_000, 13.0),
            timed_bar(300_000, 12.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 7.0),
            timed_bar(120_000, 11.0),
            timed_bar(180_000, 17.0),
            timed_bar(240_000, 25.0),
            timed_bar(300_000, 26.0),
        ])
        .expect("provider ta.cmo expression should run");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_eq!(result.plots[0].values[2], PineValue::Na);
    assert_values_close(
        &result.plots[0].values[3..],
        &[0.0, 33.333333333333336, 0.0],
    );
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_eq!(result.plots[1].values[2], PineValue::Na);
    assert_values_close(&result.plots[1].values[3..], &[100.0, 100.0, 100.0]);
}

#[test]
fn request_security_evaluates_provider_cci_in_requested_context() {
    let program = compile_program(
        "indicator(\"request cci\")\nprovider_cci = request.security(\"NYSE:IBM\", timeframe.period, ta.cci(close, 3))\nchart_cci = ta.cci(close, 3)\nplot(provider_cci)\nplot(chart_cci)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_bar(0, 10.0),
            timed_bar(60_000, 11.0),
            timed_bar(120_000, 12.0),
            timed_bar(180_000, 10.0),
            timed_bar(240_000, 13.0),
            timed_bar(300_000, 12.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 7.0),
            timed_bar(120_000, 11.0),
            timed_bar(180_000, 17.0),
            timed_bar(240_000, 25.0),
            timed_bar(300_000, 26.0),
        ])
        .expect("provider ta.cci expression should run");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(&result.plots[0].values[2..], &[100.0, -100.0, 80.0, 20.0]);
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_values_close(
        &result.plots[1].values[2..],
        &[100.0, 100.0, 100.0, 58.8235294117647],
    );
}

#[test]
fn request_security_evaluates_provider_cog_in_requested_context() {
    let program = compile_program(
        "indicator(\"request cog\")\nprovider_cog = request.security(\"NYSE:IBM\", timeframe.period, ta.cog(close, 3))\nchart_cog = ta.cog(close, 3)\nplot(provider_cog)\nplot(chart_cog)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_bar(0, 10.0),
            timed_bar(60_000, 11.0),
            timed_bar(120_000, 12.0),
            timed_bar(180_000, 10.0),
            timed_bar(240_000, 13.0),
            timed_bar(300_000, 12.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 7.0),
            timed_bar(120_000, 11.0),
            timed_bar(180_000, 17.0),
            timed_bar(240_000, 25.0),
            timed_bar(300_000, 26.0),
        ])
        .expect("provider ta.cog expression should run");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(
        &result.plots[0].values[2..],
        &[
            -1.9393939393939394,
            -2.0303030303030303,
            -1.9714285714285715,
            -1.9428571428571428,
        ],
    );
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_values_close(
        &result.plots[1].values[2..],
        &[
            -1.7391304347826086,
            -1.7142857142857142,
            -1.7358490566037736,
            -1.8676470588235294,
        ],
    );
}

#[test]
fn request_security_evaluates_provider_bop_in_requested_context() {
    let program = compile_program(
        "indicator(\"request bop\")\nprovider_bop = request.security(\"NYSE:IBM\", timeframe.period, ta.bop())\nchart_bop = ta.bop()\nplot(provider_bop)\nplot(chart_bop)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 15.0, 9.0, 13.0, 1.0),
            timed_ohlcv(60_000, 11.0, 14.0, 10.0, 10.0, 1.0),
            timed_ohlcv(120_000, 12.0, 18.0, 10.0, 16.0, 1.0),
            timed_ohlcv(180_000, 13.0, 13.0, 13.0, 13.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_ohlcv(0, 1.0, 3.0, 0.0, 2.0, 1.0),
            timed_ohlcv(60_000, 2.0, 5.0, 1.0, 1.0, 1.0),
            timed_ohlcv(120_000, 3.0, 6.0, 2.0, 6.0, 1.0),
            timed_ohlcv(180_000, 4.0, 4.0, 4.0, 4.0, 1.0),
        ])
        .expect("provider ta.bop expression should run");

    assert_values_close(&result.plots[0].values[..3], &[0.5, -0.25, 0.5]);
    assert_eq!(result.plots[0].values[3], PineValue::Na);
    assert_values_close(&result.plots[1].values[..3], &[1.0 / 3.0, -0.25, 0.75]);
    assert_eq!(result.plots[1].values[3], PineValue::Na);
}

#[test]
fn request_security_evaluates_provider_ao_in_requested_context() {
    let program = compile_program(
        "indicator(\"request ao\")\nprovider_ao = request.security(\"NYSE:IBM\", timeframe.period, ta.ao())\nchart_ao = ta.ao()\nplot(provider_ao)\nplot(chart_ao)\n",
    );
    let provider_bars: Vec<_> = (0_i64..36)
        .map(|index| {
            let hl2 = 100.0 + 2.0 * index as f64;
            timed_ohlcv(index * 60_000, hl2, hl2 + 1.0, hl2 - 1.0, hl2, 1.0)
        })
        .collect();
    let chart_bars: Vec<_> = (0_i64..36)
        .map(|index| {
            let hl2 = 10.0 + 3.0 * index as f64;
            timed_ohlcv(index * 60_000, hl2, hl2 + 1.0, hl2 - 1.0, hl2, 1.0)
        })
        .collect();
    let environment = external_symbol_environment("NYSE:IBM", provider_bars);
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&chart_bars)
        .expect("provider ta.ao expression should run");

    for value in &result.plots[0].values[..33] {
        assert_eq!(*value, PineValue::Na);
    }
    assert_values_close(&result.plots[0].values[33..], &[29.0, 29.0, 29.0]);
    for value in &result.plots[1].values[..33] {
        assert_eq!(*value, PineValue::Na);
    }
    assert_values_close(&result.plots[1].values[33..], &[43.5, 43.5, 43.5]);
}

#[test]
fn request_security_evaluates_provider_ta_max_in_requested_context() {
    let program = compile_program(
        "indicator(\"request max\")\nprovider_max = request.security(\"NYSE:IBM\", timeframe.period, ta.max(close))\nchart_max = ta.max(close)\nplot(provider_max)\nplot(chart_max)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_bar(0, 10.0),
            timed_bar(60_000, 14.0),
            timed_bar(120_000, 12.0),
            timed_bar(180_000, 16.0),
            timed_bar(240_000, 15.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 3.0),
            timed_bar(120_000, 8.0),
            timed_bar(180_000, 6.0),
            timed_bar(240_000, 9.0),
        ])
        .expect("provider ta.max expression should run");

    assert_values_close(&result.plots[0].values, &[10.0, 14.0, 14.0, 16.0, 16.0]);
    assert_values_close(&result.plots[1].values, &[5.0, 5.0, 8.0, 8.0, 9.0]);
}

#[test]
fn request_security_evaluates_provider_ta_min_in_requested_context() {
    let program = compile_program(
        "indicator(\"request min\")\nprovider_min = request.security(\"NYSE:IBM\", timeframe.period, ta.min(close))\nchart_min = ta.min(close)\nplot(provider_min)\nplot(chart_min)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_bar(0, 10.0),
            timed_bar(60_000, 8.0),
            timed_bar(120_000, 12.0),
            timed_bar(180_000, 7.0),
            timed_bar(240_000, 9.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 6.0),
            timed_bar(120_000, 4.0),
            timed_bar(180_000, 9.0),
            timed_bar(240_000, 3.0),
        ])
        .expect("provider ta.min expression should run");

    assert_values_close(&result.plots[0].values, &[10.0, 8.0, 8.0, 7.0, 7.0]);
    assert_values_close(&result.plots[1].values, &[5.0, 5.0, 4.0, 4.0, 3.0]);
}

#[test]
fn request_security_evaluates_provider_mfi_in_requested_context() {
    let program = compile_program(
        "indicator(\"request mfi\")\nprovider_mfi = request.security(\"NYSE:IBM\", timeframe.period, ta.mfi(close, 3))\nchart_mfi = ta.mfi(close, 3)\nplot(provider_mfi)\nplot(chart_mfi)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 10.0, 10.0, 10.0, 100.0),
            timed_ohlcv(60_000, 11.0, 11.0, 11.0, 11.0, 200.0),
            timed_ohlcv(120_000, 12.0, 12.0, 12.0, 12.0, 300.0),
            timed_ohlcv(180_000, 10.0, 10.0, 10.0, 10.0, 400.0),
            timed_ohlcv(240_000, 13.0, 13.0, 13.0, 13.0, 500.0),
            timed_ohlcv(300_000, 12.0, 12.0, 12.0, 12.0, 600.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_ohlcv(0, 5.0, 5.0, 5.0, 5.0, 10.0),
            timed_ohlcv(60_000, 7.0, 7.0, 7.0, 7.0, 20.0),
            timed_ohlcv(120_000, 11.0, 11.0, 11.0, 11.0, 30.0),
            timed_ohlcv(180_000, 17.0, 17.0, 17.0, 17.0, 40.0),
            timed_ohlcv(240_000, 25.0, 25.0, 25.0, 25.0, 50.0),
            timed_ohlcv(300_000, 26.0, 26.0, 26.0, 26.0, 60.0),
        ])
        .expect("provider ta.mfi expression should run");

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
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_values_close(&result.plots[1].values[2..], &[100.0, 100.0, 100.0, 100.0]);
}

#[test]
fn request_security_evaluates_provider_stoch_in_requested_context() {
    let program = compile_program(
        "indicator(\"request stoch\")\nprovider_stoch = request.security(\"NYSE:IBM\", timeframe.period, ta.stoch(close, high, low, 3))\nchart_stoch = ta.stoch(close, high, low, 3)\nplot(provider_stoch)\nplot(chart_stoch)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 10.0, 1.0),
            timed_ohlcv(60_000, 10.0, 12.0, 10.0, 11.0, 1.0),
            timed_ohlcv(120_000, 11.0, 13.0, 11.0, 12.0, 1.0),
            timed_ohlcv(180_000, 12.0, 16.0, 12.0, 15.0, 1.0),
            timed_ohlcv(240_000, 15.0, 17.0, 14.0, 16.0, 1.0),
            timed_ohlcv(300_000, 16.0, 14.0, 8.0, 9.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_ohlcv(0, 5.0, 5.0, 5.0, 5.0, 1.0),
            timed_ohlcv(60_000, 7.0, 7.0, 7.0, 7.0, 1.0),
            timed_ohlcv(120_000, 11.0, 11.0, 11.0, 11.0, 1.0),
            timed_ohlcv(180_000, 17.0, 17.0, 17.0, 17.0, 1.0),
            timed_ohlcv(240_000, 25.0, 25.0, 25.0, 25.0, 1.0),
            timed_ohlcv(300_000, 26.0, 26.0, 26.0, 26.0, 1.0),
        ])
        .expect("provider ta.stoch expression should run");

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
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_values_close(&result.plots[1].values[2..], &[100.0, 100.0, 100.0, 100.0]);
}

#[test]
fn request_security_evaluates_provider_wpr_in_requested_context() {
    let program = compile_program(
        "indicator(\"request wpr\")\nprovider_wpr = request.security(\"NYSE:IBM\", timeframe.period, ta.wpr(3))\nchart_wpr = ta.wpr(3)\nplot(provider_wpr)\nplot(chart_wpr)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 10.0, 1.0),
            timed_ohlcv(60_000, 10.0, 12.0, 10.0, 11.0, 1.0),
            timed_ohlcv(120_000, 11.0, 13.0, 11.0, 12.0, 1.0),
            timed_ohlcv(180_000, 12.0, 16.0, 12.0, 15.0, 1.0),
            timed_ohlcv(240_000, 15.0, 17.0, 14.0, 16.0, 1.0),
            timed_ohlcv(300_000, 16.0, 14.0, 8.0, 9.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_ohlcv(0, 5.0, 5.0, 5.0, 5.0, 1.0),
            timed_ohlcv(60_000, 7.0, 7.0, 7.0, 7.0, 1.0),
            timed_ohlcv(120_000, 11.0, 11.0, 11.0, 11.0, 1.0),
            timed_ohlcv(180_000, 17.0, 17.0, 17.0, 17.0, 1.0),
            timed_ohlcv(240_000, 25.0, 25.0, 25.0, 25.0, 1.0),
            timed_ohlcv(300_000, 26.0, 26.0, 26.0, 26.0, 1.0),
        ])
        .expect("provider ta.wpr expression should run");

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
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_values_close(&result.plots[1].values[2..], &[0.0, 0.0, 0.0, 0.0]);
}

#[test]
fn request_security_evaluates_provider_sar_in_requested_context() {
    let program = compile_program(
        "indicator(\"request sar\")\nprovider_sar = request.security(\"NYSE:IBM\", timeframe.period, ta.sar(0.02, 0.02, 0.2))\nchart_sar = ta.sar(0.02, 0.02, 0.2)\nplot(provider_sar)\nplot(chart_sar)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 11.0, 9.0, 10.0, 1.0),
            timed_ohlcv(60_000, 10.0, 12.0, 10.0, 11.0, 1.0),
            timed_ohlcv(120_000, 11.0, 13.0, 11.0, 12.0, 1.0),
            timed_ohlcv(180_000, 12.0, 16.0, 12.0, 15.0, 1.0),
            timed_ohlcv(240_000, 15.0, 17.0, 14.0, 16.0, 1.0),
            timed_ohlcv(300_000, 16.0, 14.0, 8.0, 9.0, 1.0),
            timed_ohlcv(360_000, 9.0, 10.0, 6.0, 7.0, 1.0),
            timed_ohlcv(420_000, 7.0, 8.0, 4.0, 5.0, 1.0),
            timed_ohlcv(480_000, 5.0, 7.0, 3.0, 6.0, 1.0),
            timed_ohlcv(540_000, 6.0, 12.0, 5.0, 11.0, 1.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_ohlcv(0, 5.0, 5.0, 5.0, 5.0, 1.0),
            timed_ohlcv(60_000, 7.0, 7.0, 7.0, 7.0, 1.0),
            timed_ohlcv(120_000, 11.0, 11.0, 11.0, 11.0, 1.0),
            timed_ohlcv(180_000, 17.0, 17.0, 17.0, 17.0, 1.0),
            timed_ohlcv(240_000, 25.0, 25.0, 25.0, 25.0, 1.0),
            timed_ohlcv(300_000, 26.0, 26.0, 26.0, 26.0, 1.0),
        ])
        .expect("provider ta.sar expression should run");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(
        &result.plots[0].values[1..],
        &[9.0, 9.0, 9.16, 9.5704, 17.0],
    );
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_values_close(
        &result.plots[1].values[1..],
        &[5.0, 5.0, 5.24, 5.9456, 7.469952],
    );
}

#[test]
fn request_security_evaluates_provider_linreg_in_requested_context() {
    let program = compile_program(
        "indicator(\"request linreg\")\nprovider_linreg = request.security(\"NYSE:IBM\", timeframe.period, ta.linreg(close, 3, 0))\nchart_linreg = ta.linreg(close, 3, 0)\nplot(provider_linreg)\nplot(chart_linreg)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_bar(0, 20.0),
            timed_bar(60_000, 21.0),
            timed_bar(120_000, 22.0),
            timed_bar(180_000, 24.0),
            timed_bar(240_000, 27.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 7.0),
            timed_bar(120_000, 11.0),
            timed_bar(180_000, 17.0),
            timed_bar(240_000, 25.0),
        ])
        .expect("provider ta.linreg expression should run");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(
        &result.plots[0].values[2..],
        &[22.0, 23.833333333333332, 26.833333333333332],
    );
    assert_eq!(result.plots[1].values[0], PineValue::Na);
    assert_eq!(result.plots[1].values[1], PineValue::Na);
    assert_values_close(
        &result.plots[1].values[2..],
        &[10.666666666666666, 16.666666666666668, 24.666666666666668],
    );
}

#[test]
fn request_security_evaluates_provider_trend_flags_in_requested_context() {
    let program = compile_program(
        "indicator(\"request trend flags\")\nprovider_rising = request.security(\"NYSE:IBM\", timeframe.period, ta.rising(close, 2) ? 1 : 0)\nprovider_falling = request.security(\"NYSE:IBM\", timeframe.period, ta.falling(close, 2) ? 1 : 0)\nchart_rising = ta.rising(close, 2) ? 1 : 0\nchart_falling = ta.falling(close, 2) ? 1 : 0\nplot(provider_rising)\nplot(provider_falling)\nplot(chart_rising)\nplot(chart_falling)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_bar(0, 20.0),
            timed_bar(60_000, 22.0),
            timed_bar(120_000, 21.0),
            timed_bar(180_000, 19.0),
            timed_bar(240_000, 18.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 6.0),
            timed_bar(120_000, 8.0),
            timed_bar(180_000, 7.0),
            timed_bar(240_000, 10.0),
        ])
        .expect("provider ta.rising/ta.falling expressions should run");

    assert_values_close(&result.plots[0].values, &[0.0, 0.0, 0.0, 0.0, 0.0]);
    assert_values_close(&result.plots[1].values, &[0.0, 0.0, 0.0, 1.0, 1.0]);
    assert_values_close(&result.plots[2].values, &[0.0, 0.0, 1.0, 0.0, 1.0]);
    assert_values_close(&result.plots[3].values, &[0.0; 5]);
}

#[test]
fn request_security_evaluates_provider_cross_flags_in_requested_context() {
    let program = compile_program(
        "indicator(\"request cross\")\nprovider_cross = request.security(\"NYSE:IBM\", timeframe.period, ta.cross(close, 2.0) ? 1 : 0)\nprovider_over = request.security(\"NYSE:IBM\", timeframe.period, ta.crossover(close, 2.0) ? 1 : 0)\nprovider_under = request.security(\"NYSE:IBM\", timeframe.period, ta.crossunder(close, 2.0) ? 1 : 0)\nchart_cross = ta.cross(close, 3.0) ? 1 : 0\nchart_over = ta.crossover(close, 3.0) ? 1 : 0\nchart_under = ta.crossunder(close, 3.0) ? 1 : 0\nplot(provider_cross)\nplot(provider_over)\nplot(provider_under)\nplot(chart_cross)\nplot(chart_over)\nplot(chart_under)\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_bar(0, 1.0),
            timed_bar(60_000, 3.0),
            timed_bar(120_000, 1.0),
            timed_bar(180_000, 2.0),
            timed_bar(240_000, 4.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 1.0),
            timed_bar(120_000, 5.0),
            timed_bar(180_000, 1.0),
            timed_bar(240_000, 5.0),
        ])
        .expect("provider cross expressions should run");

    assert_values_close(&result.plots[0].values, &[0.0, 1.0, 1.0, 0.0, 1.0]);
    assert_values_close(&result.plots[1].values, &[0.0, 1.0, 0.0, 0.0, 1.0]);
    assert_values_close(&result.plots[2].values, &[0.0, 0.0, 1.0, 0.0, 0.0]);
    assert_values_close(&result.plots[3].values, &[0.0, 1.0, 1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[4].values, &[0.0, 0.0, 1.0, 0.0, 1.0]);
    assert_values_close(&result.plots[5].values, &[0.0, 1.0, 0.0, 1.0, 0.0]);
}

#[test]
fn request_security_evaluates_provider_ema_in_requested_context() {
    let program = compile_program(
        "indicator(\"request ema\")\nplot(request.security(\"NYSE:IBM\", timeframe.period, ta.ema(close, 2)))\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_bar(0, 20.0),
            timed_bar(60_000, 23.0),
            timed_bar(120_000, 26.0),
        ],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 5.0),
            timed_bar(60_000, 6.0),
            timed_bar(120_000, 7.0),
        ])
        .expect("provider ema expression should run");

    assert_values_close(
        &result.plots[0].values,
        &[20.0, 22.0, 24.666_666_666_666_668],
    );
}

#[test]
fn request_security_aligns_higher_timeframe_without_future_values() {
    let program = compile_program(
        "indicator(\"request htf\")\nplot(request.security(\"NYSE:IBM\", \"5\", close))\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![timed_bar(0, 100.0), timed_bar(300_000, 200.0)],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(0, 1.0),
            timed_bar(60_000, 2.0),
            timed_bar(240_000, 3.0),
            timed_bar(300_000, 4.0),
            timed_bar(540_000, 5.0),
        ])
        .expect("higher timeframe request should run");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(&result.plots[0].values[2..], &[100.0, 100.0, 200.0]);
}

#[test]
fn request_security_confirms_monthly_values_at_real_utc_month_boundaries() {
    let program = compile_program(
        "indicator(\"request monthly\")\nplot(request.security(\"NYSE:IBM\", \"M\", close))\n",
    );
    let cases = [
        (
            "31-day month",
            vec![
                timed_bar(1_704_067_200_000, 100.0),
                timed_bar(1_706_745_600_000, 200.0),
            ],
            vec![
                timed_bar(1_706_486_400_000, 1.0),
                timed_bar(1_706_572_800_000, 2.0),
                timed_bar(1_706_659_200_000, 3.0),
                timed_bar(1_706_745_600_000, 4.0),
            ],
            vec![
                PineValue::Na,
                PineValue::Na,
                PineValue::Float(100.0),
                PineValue::Float(100.0),
            ],
        ),
        (
            "28-day month without a following provider bar",
            vec![timed_bar(1_675_209_600_000, 110.0)],
            vec![
                timed_bar(1_677_456_000_000, 1.0),
                timed_bar(1_677_542_400_000, 2.0),
                timed_bar(1_677_628_800_000, 3.0),
            ],
            vec![
                PineValue::Na,
                PineValue::Float(110.0),
                PineValue::Float(110.0),
            ],
        ),
        (
            "29-day month",
            vec![
                timed_bar(1_706_745_600_000, 120.0),
                timed_bar(1_709_251_200_000, 220.0),
            ],
            vec![
                timed_bar(1_709_078_400_000, 1.0),
                timed_bar(1_709_164_800_000, 2.0),
                timed_bar(1_709_251_200_000, 3.0),
            ],
            vec![
                PineValue::Na,
                PineValue::Float(120.0),
                PineValue::Float(120.0),
            ],
        ),
    ];

    for (name, provider_bars, chart_bars, expected) in cases {
        let environment =
            external_symbol_environment_with_chart_timeframe("NYSE:IBM", "M", "D", provider_bars);
        let result = HistoricalRuntime::with_request_environment(&program, environment)
            .run(&chart_bars)
            .unwrap_or_else(|error| panic!("{name}: {}", error.message));
        assert_eq!(result.plots[0].values, expected, "{name}");
    }
}

#[test]
fn request_security_does_not_treat_monthly_as_same_boundary_as_thirty_days() {
    let program = compile_program(
        "indicator(\"request monthly on 30D\")\nplot(request.security(\"NYSE:IBM\", \"M\", close))\n",
    );
    let environment = external_symbol_environment_with_chart_timeframe(
        "NYSE:IBM",
        "M",
        "30D",
        vec![timed_bar(1_704_067_200_000, 100.0)],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(1_704_067_200_000, 1.0),
            timed_bar(1_706_659_200_000, 2.0),
        ])
        .expect("monthly request on 30D chart should run");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(&result.plots[0].values[1..], &[100.0]);
}

#[test]
fn request_security_keeps_daily_and_weekly_confirmation_boundaries() {
    let cases = [
        (
            "D",
            "60",
            vec![timed_bar(0, 100.0), timed_bar(86_400_000, 200.0)],
            vec![timed_bar(79_200_000, 1.0), timed_bar(82_800_000, 2.0)],
        ),
        (
            "W",
            "D",
            vec![timed_bar(345_600_000, 100.0), timed_bar(950_400_000, 200.0)],
            vec![timed_bar(777_600_000, 1.0), timed_bar(864_000_000, 2.0)],
        ),
    ];

    for (requested_timeframe, chart_timeframe, provider_bars, chart_bars) in cases {
        let program = compile_program(&format!(
            "indicator(\"request fixed boundary\")\nplot(request.security(\"NYSE:IBM\", \"{requested_timeframe}\", close))\n"
        ));
        let environment = external_symbol_environment_with_chart_timeframe(
            "NYSE:IBM",
            requested_timeframe,
            chart_timeframe,
            provider_bars,
        );
        let result = HistoricalRuntime::with_request_environment(&program, environment)
            .run(&chart_bars)
            .unwrap_or_else(|error| panic!("{requested_timeframe}: {}", error.message));

        assert_eq!(result.plots[0].values[0], PineValue::Na);
        assert_values_close(&result.plots[0].values[1..], &[100.0]);
    }
}

#[test]
fn request_security_higher_timeframe_gap_fills_last_confirmed_value() {
    let program = compile_program(
        "indicator(\"request htf gap\")\nplot(request.security(\"NYSE:IBM\", \"5\", close))\n",
    );
    let environment = external_symbol_environment_with_timeframe(
        "NYSE:IBM",
        "5",
        vec![timed_bar(0, 100.0), timed_bar(900_000, 300.0)],
    );
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[
            timed_bar(240_000, 1.0),
            timed_bar(600_000, 2.0),
            timed_bar(1_140_000, 3.0),
        ])
        .expect("higher timeframe gap fill should run");

    assert_values_close(&result.plots[0].values, &[100.0, 100.0, 300.0]);
}

#[test]
fn request_security_higher_timeframe_supports_chart_symbol_provider_data() {
    let program = compile_program(
        "indicator(\"request chart htf\")\nplot(request.security(syminfo.tickerid, \"5\", close + open))\n",
    );
    let key = RequestKey::new(
        "NASDAQ:AAPL",
        RequestTimeframe::parse("5").expect("five minute timeframe"),
    );
    let provider = InMemoryRequestDataProvider::from_streams([(
        key,
        vec![timed_ohlcv(0, 10.0, 11.0, 9.0, 100.0, 1.0)],
    )])
    .expect("valid request bars");
    let environment = RequestEnvironment::new(ChartContext::default(), Arc::new(provider));
    let result = HistoricalRuntime::with_request_environment(&program, environment)
        .run(&[timed_bar(240_000, 1.0)])
        .expect("chart-symbol higher timeframe provider request should run");

    assert_values_close(&result.plots[0].values, &[110.0]);
}

#[test]
fn request_security_rejects_lower_timeframe_provider_requests() {
    let program = compile_program(
        "indicator(\"request ltf\")\nplot(request.security(\"NYSE:IBM\", \"30S\", close))\n",
    );
    let runtime =
        HistoricalRuntime::with_request_environment(&program, RequestEnvironment::default());
    let error = runtime
        .run(&[timed_bar(0, 1.0)])
        .expect_err("lower timeframe should fail");

    assert_eq!(
        error.message,
        "request.security lower timeframe requests are not supported for symbol `NYSE:IBM` timeframe `30S` on chart timeframe `1`"
    );
}

#[test]
fn realtime_request_security_higher_timeframe_uses_confirmed_requested_bars() {
    let program = compile_program(
        "indicator(\"request realtime htf\")\nplot(request.security(\"NYSE:IBM\", \"5\", close))\n",
    );
    let mut runtime = RealtimeRuntime::with_request_environment(
        &program,
        external_symbol_environment_with_timeframe(
            "NYSE:IBM",
            "5",
            vec![timed_bar(0, 100.0), timed_bar(300_000, 200.0)],
        ),
    );

    runtime
        .update(BarUpdate::historical(timed_bar(0, 1.0)))
        .expect("historical update");
    let first_forming = runtime
        .update(BarUpdate::forming(timed_bar(240_000, 2.0)))
        .expect("forming update");
    let second_forming = runtime
        .update(BarUpdate::forming(timed_bar(240_000, 3.0)))
        .expect("second forming update");

    assert_eq!(first_forming.plots[0].values[0], PineValue::Na);
    assert_values_close(&first_forming.plots[0].values[1..], &[100.0]);
    assert_eq!(second_forming.plots[0].values[0], PineValue::Na);
    assert_values_close(&second_forming.plots[0].values[1..], &[100.0]);
}

#[test]
fn request_security_caches_requested_context_values_by_callsite() {
    let program = compile_program(
        "indicator(\"request cache\")\nplot(request.security(\"NYSE:IBM\", timeframe.period, ta.sma(close, 2)))\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_bar(0, 20.0),
            timed_bar(60_000, 22.0),
            timed_bar(120_000, 24.0),
        ],
    );
    let mut runtime = HistoricalRuntime::with_request_environment(&program, environment);

    runtime
        .append_bar(timed_bar(0, 5.0))
        .expect("first bar should run");
    assert_eq!(runtime.request_cache.len(), 1);
    runtime
        .append_bar(timed_bar(60_000, 7.0))
        .expect("second bar should run");
    assert_eq!(runtime.request_cache.len(), 1);
}

#[test]
fn request_security_cache_isolates_same_context_different_callsite_expressions() {
    let program = compile_program(
        "indicator(\"request cache isolation\")\nplot(request.security(\"NYSE:IBM\", timeframe.period, open))\nplot(request.security(\"NYSE:IBM\", timeframe.period, close))\n",
    );
    let environment = external_symbol_environment(
        "NYSE:IBM",
        vec![
            timed_ohlcv(0, 10.0, 25.0, 5.0, 20.0, 1.0),
            timed_ohlcv(60_000, 11.0, 26.0, 6.0, 21.0, 1.0),
        ],
    );
    let mut runtime = HistoricalRuntime::with_request_environment(&program, environment);

    runtime
        .append_bar(timed_bar(0, 5.0))
        .expect("first bar should run");
    runtime
        .append_bar(timed_bar(60_000, 7.0))
        .expect("second bar should run");
    let result = runtime.result();

    assert_eq!(runtime.request_cache.len(), 2);
    assert_values_close(&result.plots[0].values, &[10.0, 11.0]);
    assert_values_close(&result.plots[1].values, &[20.0, 21.0]);
}

#[test]
fn request_security_reports_missing_external_dataset() {
    let program = compile_program(
        "indicator(\"request missing\")\nplot(request.security(\"NYSE:IBM\", timeframe.period, close))\n",
    );
    let runtime =
        HistoricalRuntime::with_request_environment(&program, RequestEnvironment::default());
    let error = runtime
        .run(&[timed_bar(0, 5.0)])
        .expect_err("missing provider data should fail");

    assert_eq!(
        error.message,
        "missing request data for symbol `NYSE:IBM` timeframe `1`"
    );
}

#[test]
fn realtime_request_security_reuses_immutable_provider_data_during_rollback() {
    let program = compile_program(
        "indicator(\"request realtime\")\nplot(request.security(\"NYSE:IBM\", timeframe.period, close))\n",
    );
    let mut runtime = RealtimeRuntime::with_request_environment(
        &program,
        external_symbol_environment(
            "NYSE:IBM",
            vec![timed_bar(0, 20.0), timed_bar(60_000, 21.0)],
        ),
    );

    runtime
        .update(BarUpdate::historical(timed_bar(0, 5.0)))
        .expect("historical update");
    let first_forming = runtime
        .update(BarUpdate::forming(timed_bar(60_000, 6.0)))
        .expect("forming update");
    let second_forming = runtime
        .update(BarUpdate::forming(timed_bar(60_000, 7.0)))
        .expect("second forming update");

    assert_values_close(&first_forming.plots[0].values, &[20.0, 21.0]);
    assert_values_close(&second_forming.plots[0].values, &[20.0, 21.0]);
}
