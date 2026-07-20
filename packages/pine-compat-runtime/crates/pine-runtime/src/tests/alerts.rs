use pine_syntax::SourceFile;
use std::sync::Arc;

use super::*;

#[test]
fn collects_alertcondition_events_when_condition_is_true() {
    let result = run_alert_script(
        r#"indicator("alerts")
alertcondition(close > 1, "Above", "Close is above one")
"#,
        &timed_bars(&[1.0, 2.0, 3.0]),
    );

    assert_eq!(result.alerts.len(), 2);
    assert_eq!(result.alerts[0].id, 1);
    assert_eq!(result.alerts[0].bar_index, 1);
    assert_eq!(result.alerts[0].time, 1_000);
    assert_eq!(result.alerts[0].source, "Above");
    assert_eq!(result.alerts[0].message, "Close is above one");
    assert_eq!(result.alerts[1].bar_index, 2);
    assert_eq!(result.alerts[1].time, 2_000);
}

#[test]
fn skips_false_and_na_alertcondition_conditions() {
    let result = run_alert_script(
        r#"indicator("alerts")
alertcondition(close > 10, "Never", "false")
alertcondition(close > 1 ? na : false, "NA", "na")
"#,
        &timed_bars(&[1.0, 2.0, 3.0]),
    );

    assert!(result.alerts.is_empty());
}

#[test]
fn alertcondition_message_renders_ohlcv_placeholders() {
    let result = run_alert_script(
        r#"indicator("alerts")
alertcondition(true, "OHLCV", "O={{open}} H={{high}} L={{low}} C={{close}} V={{volume}}")
"#,
        &[Bar {
            time: 42,
            open: 10.5,
            high: 12.25,
            low: 9.75,
            close: 11.125,
            volume: 1500.0,
        }],
    );

    assert_eq!(result.alerts.len(), 1);
    assert_eq!(result.alerts[0].source, "OHLCV");
    assert_eq!(
        result.alerts[0].message,
        "O=10.5 H=12.25 L=9.75 C=11.125 V=1500"
    );
}

#[test]
fn alertcondition_message_renders_chart_placeholders() {
    let result = run_alert_script(
        r#"indicator("alerts")
alertcondition(true, "Chart", "{{exchange}} {{ticker}} {{interval}} {{time}} {{close}}")
"#,
        &[Bar {
            time: 1_609_459_200_000,
            open: 12.0,
            high: 12.0,
            low: 12.0,
            close: 12.0,
            volume: 1.0,
        }],
    );

    assert_eq!(result.alerts.len(), 1);
    assert_eq!(result.alerts[0].source, "Chart");
    assert_eq!(
        result.alerts[0].message,
        "NASDAQ AAPL 1 2021-01-01T00:00:00+0000 12"
    );
}

#[test]
fn alertcondition_exchange_placeholder_is_empty_without_symbol_prefix() {
    let environment = RequestEnvironment::new(
        ChartContext::new(
            "AAPL",
            RequestTimeframe::parse("D").expect("daily timeframe"),
        ),
        Arc::new(NoRequestDataProvider),
    );
    let result = run_alert_script_with_environment(
        r#"indicator("alerts")
alertcondition(true, "Chart", "{{exchange}}/{{ticker}}/{{interval}}")
"#,
        &timed_bars(&[12.0]),
        environment,
    );

    assert_eq!(result.alerts.len(), 1);
    assert_eq!(result.alerts[0].source, "Chart");
    assert_eq!(result.alerts[0].message, "/AAPL/D");
}

#[test]
fn alertcondition_events_follow_branch_execution_and_program_order() {
    let result = run_alert_script(
        r#"indicator("alerts")
if bar_index == 1
    alertcondition(true, "Branch", "branch")
alertcondition(bar_index == 1, "First", "first")
alertcondition(bar_index == 1, "Second", "second")
"#,
        &timed_bars(&[1.0, 2.0, 3.0]),
    );

    assert_eq!(result.alerts.len(), 3);
    assert_eq!(result.alerts[0].source, "Branch");
    assert_eq!(result.alerts[1].source, "First");
    assert_eq!(result.alerts[2].source, "Second");
    assert!(result.alerts.iter().all(|event| event.bar_index == 1));
}

#[test]
fn collects_alert_events_when_execution_reaches_call() {
    let result = run_alert_script(
        r#"indicator("alerts")
alert(str.tostring(close))
if bar_index == 1
    alert("Branch")
if bar_index == 2
    for i = 0 to 1
        alert("Loop")
"#,
        &timed_bars(&[1.0, 2.0, 3.0]),
    );

    assert_eq!(result.alerts.len(), 5);
    assert_eq!(result.alerts[0].source, "alert");
    assert_eq!(result.alerts[0].message, "1");
    assert_eq!(result.alerts[0].bar_index, 0);
    assert_eq!(result.alerts[1].message, "2");
    assert_eq!(result.alerts[1].bar_index, 1);
    assert_eq!(result.alerts[2].message, "Branch");
    assert_eq!(result.alerts[2].bar_index, 1);
    assert_eq!(result.alerts[3].message, "3");
    assert_eq!(result.alerts[3].bar_index, 2);
    assert_eq!(result.alerts[4].message, "Loop");
    assert_eq!(result.alerts[4].bar_index, 2);
}

#[test]
fn alert_frequency_controls_same_bar_duplicate_calls() {
    let result = run_alert_script(
        r#"indicator("alerts")
if bar_index == 0
    for i = 0 to 1
        alert("Default once")
    for i = 0 to 1
        alert("Explicit once", alert.freq_once_per_bar)
    for i = 0 to 1
        alert("All", alert.freq_all)
    for i = 0 to 1
        alert("Close", alert.freq_once_per_bar_close)
"#,
        &timed_bars(&[1.0]),
    );

    assert_eq!(result.alerts.len(), 5);
    assert_eq!(result.alerts[0].message, "Default once");
    assert_eq!(result.alerts[1].message, "Explicit once");
    assert_eq!(result.alerts[2].message, "All");
    assert_eq!(result.alerts[3].message, "All");
    assert_eq!(result.alerts[4].message, "Close");
}

fn run_alert_script(source: &str, bars: &[Bar]) -> RuntimeResult {
    run_alert_script_with_environment(source, bars, RequestEnvironment::default())
}

fn run_alert_script_with_environment(
    source: &str,
    bars: &[Bar],
    environment: RequestEnvironment,
) -> RuntimeResult {
    let source = SourceFile::new("alerts.pine", source);
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    run_historical_with_request_environment(&analysis.hir.expect("HIR"), bars, environment)
        .expect("runtime result")
}

fn timed_bars(values: &[f64]) -> Vec<Bar> {
    values
        .iter()
        .enumerate()
        .map(|(index, value)| Bar {
            time: (index as i64) * 1_000,
            open: *value,
            high: *value,
            low: *value,
            close: *value,
            volume: 1.0,
        })
        .collect()
}
