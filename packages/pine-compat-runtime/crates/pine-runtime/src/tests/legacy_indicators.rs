use std::sync::Arc;

use pine_syntax::SourceFile;

use super::*;

fn compile_fixture(name: &str, source: &str) -> pine_ir::HirProgram {
    let analysis = analyze_source(&SourceFile::new(name, source));
    assert!(
        analysis.diagnostics.is_empty(),
        "{name}: {:?}",
        analysis.diagnostics
    );
    analysis.hir.expect("legacy fixture HIR")
}

fn timed_close(time: i64, close: f64) -> Bar {
    Bar {
        time,
        open: close,
        high: close,
        low: close,
        close,
        volume: 1.0,
    }
}

fn legacy_security_environment(bars: Vec<Bar>) -> RequestEnvironment {
    let key = RequestKey::new(
        "NYSE:IBM",
        RequestTimeframe::parse("5").expect("five minute timeframe"),
    );
    let provider = InMemoryRequestDataProvider::from_streams([(key, bars)])
        .expect("valid legacy security request bars");
    RequestEnvironment::new(ChartContext::default(), Arc::new(provider))
}

fn legacy_security_environment_with_timeframes(
    requested_timeframe: &str,
    chart_timeframe: &str,
    bars: Vec<Bar>,
) -> RequestEnvironment {
    let key = RequestKey::new(
        "NYSE:IBM",
        RequestTimeframe::parse(requested_timeframe).expect("requested timeframe"),
    );
    let provider = InMemoryRequestDataProvider::from_streams([(key, bars)])
        .expect("valid legacy security request bars");
    RequestEnvironment::new(
        ChartContext::new(
            "NASDAQ:AAPL",
            RequestTimeframe::parse(chart_timeframe).expect("chart timeframe"),
        ),
        Arc::new(provider),
    )
}

fn legacy_security_profile_program(
    name: &str,
    gaps: &str,
    lookahead: &str,
    version: u16,
) -> pine_ir::HirProgram {
    let mut program = compile_fixture(
        name,
        &format!(
            "//@version=4\nstudy(\"legacy security profile\")\nplot(security(\"NYSE:IBM\", \"5\", close, gaps={gaps}, lookahead={lookahead}))\n"
        ),
    );
    program.language_version = Some(version);
    program
}

fn legacy_v2_core_bars() -> [Bar; 6] {
    [
        Bar {
            time: 0,
            open: 10.0,
            high: 12.0,
            low: 9.0,
            close: 11.0,
            volume: 100.0,
        },
        Bar {
            time: 60_000,
            open: 12.0,
            high: 13.0,
            low: 10.0,
            close: 11.0,
            volume: 110.0,
        },
        Bar {
            time: 120_000,
            open: 11.0,
            high: 14.0,
            low: 10.0,
            close: 13.0,
            volume: 120.0,
        },
        Bar {
            time: 180_000,
            open: 13.0,
            high: 14.0,
            low: 9.0,
            close: 10.0,
            volume: 130.0,
        },
        Bar {
            time: 240_000,
            open: 10.0,
            high: 12.0,
            low: 8.0,
            close: 10.0,
            volume: 140.0,
        },
        Bar {
            time: 300_000,
            open: 9.0,
            high: 12.0,
            low: 8.0,
            close: 11.0,
            volume: 150.0,
        },
    ]
}

#[test]
fn legacy_v2_core_matches_explicit_canonical_batch_incremental_and_realtime() {
    let legacy = compile_fixture(
        "legacy_v2_core.pine",
        include_str!("../../../../tests/fixtures/legacy/v2/runtime/core_legacy.pine"),
    );
    let canonical = compile_fixture(
        "legacy_v2_core_canonical.pine",
        include_str!("../../../../tests/fixtures/legacy/v2/runtime/core_canonical.pine"),
    );
    let bars = legacy_v2_core_bars();
    let expected = run_historical(&canonical, &bars).expect("canonical v2 conversion");
    let batch = run_historical(&legacy, &bars).expect("legacy v2 batch");
    assert_eq!(batch, expected);
    assert_values_close(
        &batch.plots[0].values,
        &[11.0, 22.0, 35.0, 45.0, 55.0, 66.0],
    );
    assert_values_close(&batch.plots[1].values, &[0.0, 12.0, 24.0, 38.0, 49.0, 60.0]);
    assert_values_close(
        &batch.plots[3].values,
        &[23.0, 23.0, 27.0, 21.0, 21.0, 23.0],
    );
    assert_eq!(batch.plots[4].values[0], PineValue::Na);
    assert_values_close(&batch.plots[4].values[1..], &[1.0, 1.0, 1.0, 1.0, 2.0]);

    let mut incremental = HistoricalRuntime::new(&legacy);
    for bar in bars {
        incremental.append_bar(bar).expect("incremental v2 bar");
    }
    assert_eq!(incremental.result(), batch);

    let mut realtime = RealtimeRuntime::new(&legacy);
    let mut realtime_result = None;
    for bar in bars {
        realtime_result = Some(
            realtime
                .update(BarUpdate::historical(bar))
                .expect("realtime v2 historical bar"),
        );
    }
    assert_eq!(realtime_result.expect("realtime result"), batch);
}

#[test]
fn implicit_v1_and_explicit_v2_shared_runtime_profile_match() {
    let v1_source = SourceFile::new(
        "shared_v1.pine",
        include_str!("../../../../tests/fixtures/legacy/v1/runtime/shared_v1.pine"),
    );
    let v1_analysis = pine_sema::analyze_source(&v1_source);
    assert!(
        v1_analysis.diagnostics.is_empty(),
        "{:?}",
        v1_analysis.diagnostics
    );
    let v1 = v1_analysis.hir.expect("implicit v1 HIR");
    let v2 = compile_fixture(
        "shared_v2.pine",
        include_str!("../../../../tests/fixtures/legacy/v2/runtime/shared_v2.pine"),
    );
    let bars = legacy_v2_core_bars();
    assert_eq!(
        run_historical(&v1, &bars).expect("implicit v1 run"),
        run_historical(&v2, &bars).expect("explicit v2 run")
    );
}

#[test]
fn v4_legacy_security_same_context_matches_direct_expression() {
    let legacy = compile_fixture(
        "legacy_security_same_context.pine",
        "//@version=4\nstudy(\"legacy same context\")\nplot(security(syminfo.tickerid, timeframe.period, close + open))\n",
    );
    let direct = compile_fixture(
        "legacy_security_same_context_direct.pine",
        "//@version=4\nstudy(\"legacy same context direct\")\nplot(close + open)\n",
    );
    let bars = [
        timed_close(0, 1.0),
        timed_close(60_000, 2.0),
        timed_close(120_000, 3.0),
    ];

    assert_eq!(
        run_historical(&legacy, &bars).expect("legacy same-context run"),
        run_historical(&direct, &bars).expect("direct same-context run")
    );
}

#[test]
fn legacy_v2_and_v3_security_profiles_have_distinct_historical_alignment() {
    let v2 = legacy_security_profile_program(
        "legacy_v2_security_profile.pine",
        "barmerge.gaps_off",
        "barmerge.lookahead_on",
        2,
    );
    let v3 = legacy_security_profile_program(
        "legacy_v3_security_profile.pine",
        "barmerge.gaps_off",
        "barmerge.lookahead_off",
        3,
    );
    let environment =
        legacy_security_environment(vec![timed_close(0, 100.0), timed_close(300_000, 200.0)]);
    let chart = [
        timed_close(0, 1.0),
        timed_close(60_000, 2.0),
        timed_close(240_000, 3.0),
        timed_close(300_000, 4.0),
        timed_close(540_000, 5.0),
    ];

    let v2_result = run_historical_with_request_environment(&v2, &chart, environment.clone())
        .expect("v2 lookahead profile");
    let v3_result = run_historical_with_request_environment(&v3, &chart, environment)
        .expect("v3 lookahead profile");

    assert_values_close(
        &v2_result.plots[0].values,
        &[100.0, 100.0, 100.0, 200.0, 200.0],
    );
    assert_eq!(v3_result.plots[0].values[0], PineValue::Na);
    assert_eq!(v3_result.plots[0].values[1], PineValue::Na);
    assert_values_close(&v3_result.plots[0].values[2..], &[100.0, 100.0, 200.0]);
    assert_eq!(v2_result.diagnostics.len(), 1);
    assert_eq!(v2_result.diagnostics[0].code, "W_LEGACY_SECURITY_LOOKAHEAD");
    assert!(v3_result.diagnostics.is_empty());
}

#[test]
fn legacy_security_gaps_on_preserves_versioned_mapping_boundaries() {
    let v2 = legacy_security_profile_program(
        "legacy_v2_security_gaps.pine",
        "barmerge.gaps_on",
        "barmerge.lookahead_on",
        2,
    );
    let v3 = legacy_security_profile_program(
        "legacy_v3_security_gaps.pine",
        "barmerge.gaps_on",
        "barmerge.lookahead_off",
        3,
    );
    let environment =
        legacy_security_environment(vec![timed_close(0, 100.0), timed_close(300_000, 200.0)]);
    let chart = [
        timed_close(0, 1.0),
        timed_close(240_000, 2.0),
        timed_close(300_000, 3.0),
        timed_close(540_000, 4.0),
    ];
    let v2_result = run_historical_with_request_environment(&v2, &chart, environment.clone())
        .expect("v2 gaps mapping");
    let v3_result =
        run_historical_with_request_environment(&v3, &chart, environment).expect("v3 gaps mapping");

    assert_eq!(
        v2_result.plots[0].values,
        vec![
            PineValue::Float(100.0),
            PineValue::Na,
            PineValue::Float(200.0),
            PineValue::Na,
        ]
    );
    assert_eq!(
        v3_result.plots[0].values,
        vec![
            PineValue::Na,
            PineValue::Float(100.0),
            PineValue::Na,
            PineValue::Float(200.0),
        ]
    );
}

#[test]
fn legacy_v4_security_lookahead_off_confirms_monthly_values_at_calendar_close() {
    let program = compile_fixture(
        "legacy_monthly_security.pine",
        "//@version=4\nstudy(\"legacy monthly security\")\nplot(security(\"NYSE:IBM\", \"M\", close, gaps=barmerge.gaps_off, lookahead=barmerge.lookahead_off))\n",
    );
    let environment = legacy_security_environment_with_timeframes(
        "M",
        "D",
        vec![
            timed_close(1_704_067_200_000, 100.0),
            timed_close(1_706_745_600_000, 200.0),
        ],
    );
    let chart = [
        timed_close(1_706_486_400_000, 1.0),
        timed_close(1_706_572_800_000, 2.0),
        timed_close(1_706_659_200_000, 3.0),
        timed_close(1_706_745_600_000, 4.0),
    ];
    let result = run_historical_with_request_environment(&program, &chart, environment)
        .expect("legacy monthly security should run");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_eq!(result.plots[0].values[1], PineValue::Na);
    assert_values_close(&result.plots[0].values[2..], &[100.0, 100.0]);
}

#[test]
fn legacy_v4_security_does_not_treat_monthly_as_thirty_day_same_context() {
    let program = compile_fixture(
        "legacy_monthly_security_30d_chart.pine",
        "//@version=4\nstudy(\"legacy monthly security on 30D\")\nplot(security(\"NYSE:IBM\", \"M\", close, gaps=barmerge.gaps_off, lookahead=barmerge.lookahead_off))\n",
    );
    let environment = legacy_security_environment_with_timeframes(
        "M",
        "30D",
        vec![timed_close(1_704_067_200_000, 100.0)],
    );
    let chart = [
        timed_close(1_704_067_200_000, 1.0),
        timed_close(1_706_659_200_000, 2.0),
    ];
    let result = run_historical_with_request_environment(&program, &chart, environment)
        .expect("legacy monthly security on 30D chart should run");

    assert_eq!(result.plots[0].values[0], PineValue::Na);
    assert_values_close(&result.plots[0].values[1..], &[100.0]);
}

#[test]
fn legacy_security_requested_state_isolated_and_incremental_matches_batch() {
    let program = compile_fixture(
        "legacy_security_state.pine",
        "//@version=4\nstudy(\"legacy requested state\")\nchartAverage = sma(close, 2)\nrequestedAverage = security(\"NYSE:IBM\", \"5\", sma(close, 2))\nplot(chartAverage)\nplot(requestedAverage)\n",
    );
    let environment = legacy_security_environment(vec![
        timed_close(0, 100.0),
        timed_close(300_000, 200.0),
        timed_close(600_000, 300.0),
    ]);
    let chart = [
        timed_close(0, 1.0),
        timed_close(240_000, 3.0),
        timed_close(300_000, 5.0),
        timed_close(540_000, 7.0),
        timed_close(600_000, 9.0),
        timed_close(840_000, 11.0),
    ];
    let batch = run_historical_with_request_environment(&program, &chart, environment.clone())
        .expect("batch legacy state run");
    let mut incremental =
        HistoricalRuntime::with_request_environment(&program, environment.clone());
    for bar in chart {
        incremental
            .append_bar(bar)
            .expect("incremental legacy state bar");
    }
    assert_eq!(batch, incremental.result());
    assert_eq!(batch.plots[0].values[0], PineValue::Na);
    assert_values_close(&batch.plots[0].values[1..], &[2.0, 4.0, 6.0, 8.0, 10.0]);
    assert_eq!(batch.plots[1].values[0], PineValue::Na);
    assert_eq!(batch.plots[1].values[1], PineValue::Na);
    assert_eq!(batch.plots[1].values[2], PineValue::Na);
    assert_values_close(&batch.plots[1].values[3..], &[150.0, 150.0, 250.0]);

    let mut realtime = RealtimeRuntime::with_request_environment(&program, environment);
    let realtime_result = chart
        .into_iter()
        .map(|bar| {
            realtime
                .update(BarUpdate::historical(bar))
                .expect("realtime historical handoff")
        })
        .last()
        .expect("realtime result");
    assert_eq!(batch, realtime_result);
}

#[test]
fn legacy_security_requested_runtime_uses_requested_chart_metadata() {
    let program = compile_fixture(
        "legacy_security_requested_metadata.pine",
        "//@version=4\nstudy(\"legacy requested metadata\")\ninRequestedContext = security(\"NYSE:IBM\", \"5\", syminfo.tickerid == \"NYSE:IBM\" and timeframe.period == \"5\")\nplot(inRequestedContext ? 1 : 0)\n",
    );
    let environment = legacy_security_environment(vec![timed_close(0, 100.0)]);
    let result = run_historical_with_request_environment(
        &program,
        &[timed_close(240_000, 1.0)],
        environment,
    )
    .expect("requested metadata should use the requested key");

    assert_values_close(&result.plots[0].values, &[1.0]);
}

#[test]
fn legacy_lookahead_on_realtime_updates_use_confirmed_alignment() {
    let program = legacy_security_profile_program(
        "legacy_v2_security_realtime.pine",
        "barmerge.gaps_off",
        "barmerge.lookahead_on",
        2,
    );
    let environment =
        legacy_security_environment(vec![timed_close(0, 100.0), timed_close(300_000, 200.0)]);
    let mut runtime = RealtimeRuntime::with_request_environment(&program, environment);
    let historical = runtime
        .update(BarUpdate::historical(timed_close(0, 1.0)))
        .expect("historical lookahead update");
    let forming = runtime
        .update(BarUpdate::forming(timed_close(60_000, 2.0)))
        .expect("forming lookahead update");

    assert_values_close(&historical.plots[0].values, &[100.0]);
    assert_eq!(forming.plots[0].values[1], PineValue::Na);
}

#[test]
fn legacy_security_missing_provider_error_keeps_original_source_span() {
    let source =
        "//@version=4\nstudy(\"legacy missing\")\nplot(security(\"NYSE:IBM\", \"5\", close))\n";
    let program = compile_fixture("legacy_security_missing.pine", source);
    let error = run_historical(&program, &[timed_close(0, 1.0)])
        .expect_err("missing legacy provider data should fail");
    let start = source.find("security(").expect("security source start");
    let end = source[start..].find(')').expect("security source end") + start + 1;
    assert_eq!(
        error.message,
        format!(
            "legacy security at source span {start}..{end}: missing request data for symbol `NYSE:IBM` timeframe `5`"
        )
    );
}

#[test]
fn v3_core_fixture_matches_canonical_batch_incremental_and_visual_output() {
    let legacy = compile_fixture(
        "v3_core_legacy.pine",
        include_str!("../../../../tests/fixtures/legacy/v3/runtime/core_legacy.pine"),
    );
    let canonical = compile_fixture(
        "v3_core_canonical.pine",
        include_str!("../../../../tests/fixtures/legacy/v3/runtime/core_canonical.pine"),
    );
    let bars = [
        bar_ohlc(10.0, 12.0, 9.0, 11.0),
        bar_ohlc(12.0, 13.0, 9.0, 10.0),
        bar_ohlc(10.0, 15.0, 10.0, 14.0),
        bar_ohlc(14.0, 16.0, 12.0, 15.0),
        bar_ohlc(16.0, 17.0, 13.0, 14.0),
    ];

    let legacy_batch = run_historical(&legacy, &bars).expect("legacy v3 core run");
    let canonical_batch = run_historical(&canonical, &bars).expect("canonical core run");
    assert_eq!(legacy_batch, canonical_batch);

    let mut incremental = HistoricalRuntime::new(&legacy);
    for bar in bars {
        incremental
            .append_bar(bar)
            .expect("incremental v3 core bar");
    }
    assert_eq!(legacy_batch, incremental.result());
    assert_eq!(
        legacy_batch.plots[0].style,
        PineValue::String("plot.style_histogram".to_owned())
    );
    assert_eq!(
        legacy_batch.plots[0].colors,
        vec![PineValue::Color(0xF23645BF); bars.len()]
    );
    assert_eq!(
        legacy_batch.hlines[0].style,
        PineValue::String("hline.style_dotted".to_owned())
    );
    assert_eq!(legacy_batch.plots[1].values[1], PineValue::Na);
}

#[test]
fn v3_chart_metadata_aliases_match_canonical_values_in_custom_context() {
    let legacy = compile_fixture(
        "v3_metadata_aliases.pine",
        r#"//@version=3
study("v3 metadata aliases")
matches = ticker == "IBM" and tickerid == "NYSE:IBM" and period == "5" and interval == 5 and isminutes and isintraday
plot(matches ? 1 : 0)
"#,
    );
    let canonical = compile_fixture(
        "v3_metadata_canonical.pine",
        r#"//@version=6
indicator("canonical metadata")
matches = syminfo.ticker == "IBM" and syminfo.tickerid == "NYSE:IBM" and timeframe.period == "5" and timeframe.multiplier == 5 and timeframe.isminutes and timeframe.isintraday
plot(matches ? 1 : 0)
"#,
    );
    let environment = RequestEnvironment::new(
        ChartContext::new(
            "NYSE:IBM",
            RequestTimeframe::parse("5").expect("five minute chart timeframe"),
        ),
        Arc::new(NoRequestDataProvider),
    );
    let bars = [timed_close(0, 1.0), timed_close(300_000, 2.0)];
    let legacy_result =
        run_historical_with_request_environment(&legacy, &bars, environment.clone())
            .expect("legacy v3 metadata run");
    let canonical_result = run_historical_with_request_environment(&canonical, &bars, environment)
        .expect("canonical metadata run");

    assert_eq!(legacy_result, canonical_result);
    assert_values_close(&legacy_result.plots[0].values, &[1.0, 1.0]);
}

#[test]
fn v3_timeframe_aliases_follow_minute_second_day_week_and_month_contexts() {
    let legacy = compile_fixture(
        "v3_timeframe_aliases.pine",
        r#"//@version=3
study("v3 timeframe aliases")
plot(interval)
plot(isminutes ? 1 : 0)
plot(isseconds ? 1 : 0)
plot(isintraday ? 1 : 0)
plot(isdaily ? 1 : 0)
plot(isweekly ? 1 : 0)
plot(ismonthly ? 1 : 0)
plot(isdwm ? 1 : 0)
"#,
    );
    let canonical = compile_fixture(
        "v3_timeframe_aliases_canonical.pine",
        r#"//@version=6
indicator("canonical timeframe metadata")
plot(timeframe.multiplier)
plot(timeframe.isminutes ? 1 : 0)
plot(timeframe.isseconds ? 1 : 0)
plot(timeframe.isintraday ? 1 : 0)
plot(timeframe.isdaily ? 1 : 0)
plot(timeframe.isweekly ? 1 : 0)
plot(timeframe.ismonthly ? 1 : 0)
plot(timeframe.isdwm ? 1 : 0)
"#,
    );
    for (timeframe, expected) in [
        ("5", [5.0, 1.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0]),
        ("45S", [45.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0]),
        ("2D", [2.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0]),
        ("3W", [3.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 1.0]),
        ("4M", [4.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0]),
    ] {
        let environment = RequestEnvironment::new(
            ChartContext::new(
                "NYSE:IBM",
                RequestTimeframe::parse(timeframe).expect("valid chart timeframe"),
            ),
            Arc::new(NoRequestDataProvider),
        );
        let bars = [timed_close(0, 1.0)];
        let legacy_result =
            run_historical_with_request_environment(&legacy, &bars, environment.clone())
                .expect("legacy v3 timeframe metadata run");
        let canonical_result =
            run_historical_with_request_environment(&canonical, &bars, environment)
                .expect("canonical timeframe metadata run");
        assert_eq!(legacy_result, canonical_result, "{timeframe}");
        for (plot, expected_value) in legacy_result.plots.iter().zip(expected) {
            assert_values_close(&plot.values, &[expected_value]);
        }
    }
}

#[test]
fn v4_alias_fixture_matches_canonical_historical_output() {
    let legacy = compile_fixture(
        "aliases_legacy.pine",
        include_str!("../../../../tests/fixtures/legacy/v4/runtime/aliases_legacy.pine"),
    );
    let canonical = compile_fixture(
        "aliases_canonical.pine",
        include_str!("../../../../tests/fixtures/legacy/v4/runtime/aliases_canonical.pine"),
    );
    let bars = [
        bar_ohlc(10.0, 12.0, 9.0, 11.0),
        bar_ohlc(11.0, 14.0, 10.0, 13.0),
        bar_ohlc(13.0, 15.0, 11.0, 12.0),
        bar_ohlc(12.0, 16.0, 12.0, 15.0),
        bar_ohlc(15.0, 17.0, 13.0, 14.0),
        bar_ohlc(14.0, 18.0, 14.0, 17.0),
    ];

    let legacy_result = run_historical(&legacy, &bars).expect("legacy v4 run");
    let canonical_result = run_historical(&canonical, &bars).expect("canonical run");

    assert_eq!(legacy_result, canonical_result);
}

#[test]
fn v4_input_fixture_preserves_metadata_callsites_and_overrides() {
    let legacy = compile_fixture(
        "inputs_legacy.pine",
        include_str!("../../../../tests/fixtures/legacy/v4/runtime/inputs_legacy.pine"),
    );
    let canonical = compile_fixture(
        "inputs_canonical.pine",
        include_str!("../../../../tests/fixtures/legacy/v4/runtime/inputs_canonical.pine"),
    );
    let legacy_inputs = input_calls(&legacy);
    let canonical_inputs = input_calls(&canonical);
    assert_eq!(legacy_inputs, canonical_inputs);
    assert_eq!(legacy_inputs.len(), 11);
    assert_eq!(
        legacy_inputs
            .iter()
            .map(|input| input.call_site_id)
            .collect::<Vec<_>>(),
        (1..=11).collect::<Vec<_>>()
    );

    let bars = [
        Bar {
            time: 1,
            open: 10.0,
            high: 12.0,
            low: 9.0,
            close: 11.0,
            volume: 1.0,
        },
        Bar {
            time: 2,
            open: 11.0,
            high: 14.0,
            low: 10.0,
            close: 13.0,
            volume: 1.0,
        },
        Bar {
            time: 3,
            open: 13.0,
            high: 15.0,
            low: 11.0,
            close: 12.0,
            volume: 1.0,
        },
        Bar {
            time: 4,
            open: 12.0,
            high: 16.0,
            low: 12.0,
            close: 15.0,
            volume: 1.0,
        },
    ];

    assert_eq!(
        run_historical(&legacy, &bars).expect("legacy default input run"),
        run_historical(&canonical, &bars).expect("canonical default input run")
    );

    let call_site = |title: &str| {
        legacy_inputs
            .iter()
            .find(|input| input.title.as_deref() == Some(title))
            .map(|input| input.call_site_id)
            .unwrap_or_else(|| panic!("missing input title {title}"))
    };
    let overrides = InputOverrides::new()
        .with_value(call_site("Length"), PineValue::Int(1))
        .with_value(call_site("Scale"), PineValue::Float(2.0))
        .with_value(call_site("Enabled"), PineValue::Bool(true))
        .with_value(call_site("Shade"), PineValue::Color(0x4CAF50))
        .with_value(call_site("Mode"), PineValue::String("SMA".to_owned()))
        .with_value(call_site("Symbol"), PineValue::String("AAPL".to_owned()))
        .with_value(call_site("Resolution"), PineValue::String("60".to_owned()))
        .with_value(
            call_site("Session"),
            PineValue::String("0930-1600".to_owned()),
        )
        .with_value(call_site("Start"), PineValue::Int(0))
        .with_value(call_site("Price"), PineValue::Float(1.0));
    let legacy_override = run_historical_with_input_overrides(&legacy, &bars, overrides.clone())
        .expect("legacy override run");
    let canonical_override = run_historical_with_input_overrides(&canonical, &bars, overrides)
        .expect("canonical override run");
    assert_eq!(legacy_override, canonical_override);
    assert_values_close(&legacy_override.plots[0].values, &[23.0, 27.0, 25.0, 31.0]);
}

#[test]
fn v4_output_fixture_matches_canonical_visual_data_and_metadata() {
    let legacy = compile_fixture(
        "outputs_legacy.pine",
        include_str!("../../../../tests/fixtures/legacy/v4/runtime/outputs_legacy.pine"),
    );
    let canonical = compile_fixture(
        "outputs_canonical.pine",
        include_str!("../../../../tests/fixtures/legacy/v4/runtime/outputs_canonical.pine"),
    );
    let bars = [
        bar_ohlc(10.0, 12.0, 9.0, 11.0),
        bar_ohlc(12.0, 13.0, 9.0, 10.0),
        bar_ohlc(10.0, 15.0, 10.0, 14.0),
    ];

    let legacy_result = run_historical(&legacy, &bars).expect("legacy output run");
    let canonical_result = run_historical(&canonical, &bars).expect("canonical output run");
    assert_eq!(legacy_result, canonical_result);

    assert_eq!(
        legacy_result.plots[0].style,
        PineValue::String("plot.style_columns".to_owned())
    );
    assert_eq!(
        legacy_result.plots[0].colors,
        vec![PineValue::Color(0x2196F399); bars.len()]
    );
    assert_eq!(
        legacy_result.plots[1].colors,
        vec![PineValue::Color(0xF23645CC); bars.len()]
    );
    assert_eq!(
        legacy_result.hlines[0].style,
        PineValue::String("hline.style_dotted".to_owned())
    );
    assert_eq!(
        legacy_result.fills[0].colors,
        vec![PineValue::Color(0x4CAF501A); bars.len()]
    );
    assert_eq!(
        legacy_result.bg_colors[0].values,
        vec![
            PineValue::Color(0x2196F31A),
            PineValue::Na,
            PineValue::Color(0x2196F31A),
        ]
    );
    assert_eq!(legacy_result.plots[0].metadata.offset, PineValue::Int(1));
    assert_eq!(
        legacy_result.plot_chars[0].metadata.show_last,
        PineValue::Int(2)
    );
}

#[test]
fn v4_dynamic_output_style_override_rejects_unknown_ordinals_at_runtime() {
    let legacy = compile_fixture(
        "outputs_legacy.pine",
        include_str!("../../../../tests/fixtures/legacy/v4/runtime/outputs_legacy.pine"),
    );
    let style_call = input_calls(&legacy)
        .into_iter()
        .find(|input| input.title.as_deref() == Some("Plot style"))
        .expect("style input");
    let overrides = InputOverrides::new().with_value(style_call.call_site_id, PineValue::Int(99));
    let error = run_historical_with_input_overrides(&legacy, &[bar(1.0)], overrides)
        .expect_err("unknown v4 style ordinal must fail");

    assert!(
        error
            .message
            .contains("invalid Pine v4 plot style ordinal `99`")
    );
}

#[test]
fn v4_output_transparency_clamps_preserves_na_and_accepts_input_values() {
    let program = compile_fixture(
        "legacy_transparency_edges.pine",
        r#"//@version=4
study("transparency edges")
t = input(40, "Transparency")
plot(close, color=color.blue, transp=t)
plot(close, color=na, transp=40)
plot(close, color=color.blue, transp=na)
"#,
    );
    let transparency_call = input_calls(&program)
        .into_iter()
        .find(|input| input.title.as_deref() == Some("Transparency"))
        .expect("transparency input");

    let default_result = run_historical(&program, &[bar(1.0)]).expect("default transp run");
    assert_eq!(
        default_result.plots[0].colors,
        vec![PineValue::Color(0x2196F399)]
    );
    assert_eq!(default_result.plots[1].colors, vec![PineValue::Na]);
    assert_eq!(
        default_result.plots[2].colors,
        vec![PineValue::Color(0x2196F3)]
    );

    for (transp, expected) in [(-10, 0x2196F3), (120, 0x2196F300)] {
        let overrides = InputOverrides::new()
            .with_value(transparency_call.call_site_id, PineValue::Int(transp));
        let result = run_historical_with_input_overrides(&program, &[bar(1.0)], overrides)
            .expect("clamped transp run");
        assert_eq!(result.plots[0].colors, vec![PineValue::Color(expected)]);
    }
}

#[test]
fn v4_iff_eagerly_advances_both_stateful_results_while_ternary_stays_lazy() {
    let iff = compile_fixture(
        "legacy_iff_stateful.pine",
        r#"//@version=4
study("stateful iff")
plot(iff(close > open, ema(high, 2), ema(low, 2)))
"#,
    );
    let ternary = compile_fixture(
        "legacy_ternary_stateful.pine",
        r#"//@version=4
study("lazy ternary")
plot(close > open ? ema(high, 2) : ema(low, 2))
"#,
    );
    let bars = [
        bar_ohlc(1.0, 10.0, 1.0, 2.0),
        bar_ohlc(2.0, 20.0, 2.0, 3.0),
        bar_ohlc(3.0, 15.0, 5.0, 2.0),
        bar_ohlc(4.0, 14.0, 6.0, 3.0),
    ];

    let iff_result = run_historical(&iff, &bars).expect("strict iff run");
    let ternary_result = run_historical(&ternary, &bars).expect("lazy ternary run");
    assert_values_close(
        &iff_result.plots[0].values,
        &[
            10.0,
            16.666_666_666_666_664,
            3.888_888_888_888_889,
            5.296_296_296_296_296,
        ],
    );
    assert_values_close(
        &ternary_result.plots[0].values,
        &[10.0, 16.666_666_666_666_664, 5.0, 5.666_666_666_666_666],
    );
}

#[test]
fn v4_named_iff_evaluates_by_parameter_role_once() {
    let program = compile_fixture(
        "legacy_iff_named.pine",
        r#"//@version=4
study("named iff")
plot(iff(result2=lowest(low, 2), condition=close > open, result1=highest(high, 2)))
"#,
    );
    let bars = [
        bar_ohlc(1.0, 10.0, 1.0, 2.0),
        bar_ohlc(2.0, 20.0, 2.0, 3.0),
        bar_ohlc(3.0, 15.0, 5.0, 2.0),
    ];
    let result = run_historical(&program, &bars).expect("named iff run");
    assert_eq!(
        result.plots[0].values,
        vec![PineValue::Na, PineValue::Float(20.0), PineValue::Float(2.0),]
    );
}

#[test]
fn v4_offset_matches_history_for_constant_and_dynamic_offsets() {
    let legacy = compile_fixture(
        "legacy_offset.pine",
        r#"//@version=4
study("legacy offset", max_bars_back=3)
bars = input(1, "Bars")
plot(offset(close, bars))
"#,
    );
    let canonical = compile_fixture(
        "canonical_history.pine",
        r#"//@version=5
indicator("canonical history", max_bars_back=3)
bars = input.int(1, "Bars")
plot(close[bars])
"#,
    );
    assert!(legacy.history.has_dynamic_offsets);
    assert_eq!(legacy.max_bars_back, Some(3));
    let bars = [bar(10.0), bar(20.0), bar(30.0), bar(40.0)];
    assert_eq!(
        run_historical(&legacy, &bars).expect("legacy offset run"),
        run_historical(&canonical, &bars).expect("canonical history run")
    );

    let call_site_id = input_calls(&legacy)[0].call_site_id;
    let overridden = run_historical_with_input_overrides(
        &legacy,
        &bars,
        InputOverrides::new().with_value(call_site_id, PineValue::Int(2)),
    )
    .expect("overridden legacy offset run");
    assert_eq!(
        overridden.plots[0].values,
        vec![
            PineValue::Na,
            PineValue::Na,
            PineValue::Float(10.0),
            PineValue::Float(20.0)
        ]
    );

    let error = run_historical_with_input_overrides(
        &legacy,
        &bars,
        InputOverrides::new().with_value(call_site_id, PineValue::Int(-1)),
    )
    .expect_err("negative legacy dynamic offset must use the history guard");
    assert!(
        error
            .message
            .contains("history offset must be non-negative")
    );
}

#[test]
fn v4_rsi_selects_length_and_two_series_overloads_with_formula_edges() {
    let legacy_length = compile_fixture(
        "legacy_rsi_length.pine",
        r#"//@version=4
study("legacy RSI length")
plot(rsi(close, 2))
"#,
    );
    let canonical_length = compile_fixture(
        "canonical_rsi_length.pine",
        r#"//@version=5
indicator("canonical RSI length")
plot(ta.rsi(close, 2))
"#,
    );
    let legacy_series = compile_fixture(
        "legacy_rsi_series.pine",
        r#"//@version=4
study("legacy RSI series")
plot(rsi(close, open))
"#,
    );
    let canonical_formula = compile_fixture(
        "canonical_rsi_formula.pine",
        r#"//@version=5
indicator("canonical RSI formula")
plot(100.0 - (100.0 / (1.0 + close / open)))
"#,
    );
    let bars = [
        bar_ohlc(2.0, 2.0, 2.0, 2.0),
        bar_ohlc(2.0, 4.0, 1.0, 4.0),
        bar_ohlc(2.0, 2.0, 0.0, 0.0),
        bar_ohlc(0.0, 2.0, 0.0, 2.0),
    ];

    assert_eq!(
        run_historical(&legacy_length, &bars)
            .expect("legacy length RSI")
            .plots[0]
            .values,
        run_historical(&canonical_length, &bars)
            .expect("canonical length RSI")
            .plots[0]
            .values
    );
    assert_eq!(
        run_historical(&legacy_series, &bars)
            .expect("legacy series RSI")
            .plots[0]
            .values,
        run_historical(&canonical_formula, &bars)
            .expect("canonical RSI formula")
            .plots[0]
            .values
    );
}

#[test]
fn v4_session_defaults_exclude_weekends_without_rewriting_input_strings() {
    let v4 = compile_fixture(
        "legacy_session_days.pine",
        include_str!("../../../../tests/fixtures/legacy/v4/runtime/session_defaults_legacy.pine"),
    );
    let v5 = compile_fixture(
        "modern_session_days.pine",
        r#"//@version=5
indicator("modern session days")
s = input.session("0000-2359", "Session")
plot(na(time("D", s, "UTC")) ? 0 : 1)
plot(na(time_close("D", s, "UTC")) ? 0 : 1)
plot(s == "0000-2359" ? 1 : 0)
"#,
    );
    let dated_bar = |time| Bar {
        time,
        open: 1.0,
        high: 1.0,
        low: 1.0,
        close: 1.0,
        volume: 1.0,
    };
    let bars = [
        dated_bar(1_609_459_200_000),
        dated_bar(1_609_545_600_000),
        dated_bar(1_609_632_000_000),
        dated_bar(1_609_718_400_000),
    ];

    let legacy = run_historical(&v4, &bars).expect("legacy session run");
    let modern = run_historical(&v5, &bars).expect("modern session run");
    assert_values_close(&legacy.plots[0].values, &[1.0, 0.0, 0.0, 1.0]);
    assert_values_close(&legacy.plots[1].values, &[1.0, 0.0, 0.0, 1.0]);
    assert_values_close(&legacy.plots[2].values, &[1.0, 1.0, 1.0, 1.0]);
    assert_values_close(&modern.plots[0].values, &[1.0, 1.0, 1.0, 1.0]);
    assert_values_close(&modern.plots[1].values, &[1.0, 1.0, 1.0, 1.0]);
}

#[test]
fn v4_phase6_semantics_match_incremental_and_realtime_confirmed_execution() {
    let program = compile_fixture(
        "legacy_phase6_realtime.pine",
        r#"//@version=4
study("legacy phase 6 realtime")
selected = iff(close > open, ema(high, 2), ema(low, 2))
previous = offset(close, 1)
up = max(change(close), 0)
down = -min(change(close), 0)
ratio = rsi(up, down)
plot(selected)
plot(previous)
plot(ratio)
"#,
    );
    let bars = [
        bar_ohlc(1.0, 10.0, 1.0, 2.0),
        bar_ohlc(2.0, 20.0, 2.0, 3.0),
        bar_ohlc(3.0, 15.0, 5.0, 2.0),
        bar_ohlc(4.0, 14.0, 6.0, 3.0),
    ];
    let historical = run_historical(&program, &bars).expect("phase 6 historical run");

    let mut incremental = RealtimeRuntime::new(&program);
    for bar in bars.iter().cloned() {
        incremental
            .update(BarUpdate::historical(bar))
            .expect("phase 6 incremental update");
    }
    assert_eq!(incremental.result(), historical);

    let mut realtime = RealtimeRuntime::new(&program);
    for bar in bars[..3].iter().cloned() {
        realtime
            .update(BarUpdate::historical(bar))
            .expect("phase 6 realtime history");
    }
    realtime
        .update(BarUpdate::forming(bar_ohlc(8.0, 30.0, 7.0, 9.0)))
        .expect("phase 6 forming update");
    realtime
        .update(BarUpdate::forming(bars[3]))
        .expect("phase 6 rolled-back forming update");
    let confirmed = realtime
        .update(BarUpdate::confirmed(bars[3]))
        .expect("phase 6 confirmed update");
    assert_eq!(confirmed, historical);
}
