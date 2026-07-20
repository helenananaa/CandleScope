use std::{collections::HashMap, fs, sync::Arc};

use pine_runtime::{
    ChartContext, InMemoryRequestDataProvider, RequestEnvironment, RequestKey, RequestTimeframe,
    RunningAlertConfig, RuntimeResult, input_calls, public_runtime_profiled_result_json,
    public_runtime_result_json,
    run_historical_profiled_with_request_environment_and_input_overrides,
    run_historical_with_request_environment_and_input_overrides,
};
use pine_sema::analyze_input;

use crate::bars_csv::parse_bars_csv;
use crate::library_sources::{
    LibrarySourceSpec, analysis_input_from_paths, parse_library_source_spec,
};
use crate::usage;

mod input_overrides;

use input_overrides::{InputOverrideSpec, input_overrides_from_specs, parse_input_override_spec};

pub(crate) fn run(args: Vec<String>) -> Result<(), String> {
    let options = parse_options(&args)?;
    run_with_options(&options)
}

#[derive(Debug)]
struct RunOptions {
    path: String,
    bars_path: String,
    chart_context: ChartContext,
    profile: bool,
    request_bars: Vec<RequestBarsSpec>,
    library_sources: Vec<LibrarySourceSpec>,
    input_overrides: Vec<InputOverrideSpec>,
    strategy_alert_template: Option<StrategyAlertTemplateOptions>,
    strategy_running_alert: Option<StrategyRunningAlertOptions>,
}

#[derive(Debug)]
struct StrategyAlertTemplateOptions {
    template: String,
    index: usize,
}

#[derive(Debug)]
struct StrategyRunningAlertOptions {
    config: RunningAlertConfig,
    index: usize,
}

#[derive(Debug)]
struct RequestBarsSpec {
    key: RequestKey,
    path: String,
}

fn run_with_options(options: &RunOptions) -> Result<(), String> {
    println!("{}", run_output_with_options(options)?);
    Ok(())
}

fn run_output_with_options(options: &RunOptions) -> Result<String, String> {
    if options.profile
        && (options.strategy_alert_template.is_some() || options.strategy_running_alert.is_some())
    {
        return Err("strategy alert rendering cannot be combined with --profile".to_owned());
    }
    if let Some(template) = &options.strategy_alert_template {
        let result = run_result_with_options(options)?;
        return render_strategy_alert_template(&result, template);
    }
    if let Some(running_alert) = &options.strategy_running_alert {
        let result = run_result_with_options(options)?;
        return render_strategy_running_alert(&result, running_alert);
    }
    run_json_with_options(options)
}

fn run_json_with_options(options: &RunOptions) -> Result<String, String> {
    if options.profile {
        return run_profiled_json_with_options(options);
    }
    let result = run_result_with_options(options)?;
    Ok(public_runtime_result_json(&result))
}

fn run_profiled_json_with_options(options: &RunOptions) -> Result<String, String> {
    let input = analysis_input_from_paths(&options.path, &options.library_sources)?;
    let source = input.root().clone();
    let analysis = analyze_input(&input);
    if !analysis.diagnostics.is_empty() {
        for diagnostic in analysis.diagnostics {
            let line_col = source.line_col(diagnostic.span.start);
            eprintln!(
                "{}:{:?}:{}:{}: {}",
                diagnostic.code,
                diagnostic.severity,
                line_col.line,
                line_col.column,
                diagnostic.message
            );
        }
        return Err("analysis failed".to_owned());
    }
    let Some(hir) = analysis.hir else {
        return Err("analysis did not produce executable HIR".to_owned());
    };

    let bars_text = fs::read_to_string(&options.bars_path)
        .map_err(|err| format!("failed to read {}: {err}", options.bars_path))?;
    let bars = parse_bars_csv(&bars_text)?;
    let request_environment =
        request_environment_from_specs(&options.request_bars, options.chart_context.clone())?;
    let input_calls = input_calls(&hir)
        .into_iter()
        .map(|input| (input.call_site_id, input))
        .collect::<HashMap<_, _>>();
    let input_overrides = input_overrides_from_specs(&options.input_overrides, &input_calls)?;
    let result = run_historical_profiled_with_request_environment_and_input_overrides(
        &hir,
        &bars,
        request_environment,
        input_overrides,
    )
    .map_err(|err| format!("runtime failed: {}", err.message))?;
    Ok(public_runtime_profiled_result_json(
        &result.result,
        &result.profile,
    ))
}

fn run_result_with_options(options: &RunOptions) -> Result<RuntimeResult, String> {
    let input = analysis_input_from_paths(&options.path, &options.library_sources)?;
    let source = input.root().clone();
    let analysis = analyze_input(&input);
    if !analysis.diagnostics.is_empty() {
        for diagnostic in analysis.diagnostics {
            let line_col = source.line_col(diagnostic.span.start);
            eprintln!(
                "{}:{:?}:{}:{}: {}",
                diagnostic.code,
                diagnostic.severity,
                line_col.line,
                line_col.column,
                diagnostic.message
            );
        }
        return Err("analysis failed".to_owned());
    }
    let Some(hir) = analysis.hir else {
        return Err("analysis did not produce executable HIR".to_owned());
    };

    let bars_text = fs::read_to_string(&options.bars_path)
        .map_err(|err| format!("failed to read {}: {err}", options.bars_path))?;
    let bars = parse_bars_csv(&bars_text)?;
    let request_environment =
        request_environment_from_specs(&options.request_bars, options.chart_context.clone())?;
    let input_calls = input_calls(&hir)
        .into_iter()
        .map(|input| (input.call_site_id, input))
        .collect::<HashMap<_, _>>();
    let input_overrides = input_overrides_from_specs(&options.input_overrides, &input_calls)?;
    run_historical_with_request_environment_and_input_overrides(
        &hir,
        &bars,
        request_environment,
        input_overrides,
    )
    .map_err(|err| format!("runtime failed: {}", err.message))
}

fn render_strategy_alert_template(
    result: &RuntimeResult,
    template: &StrategyAlertTemplateOptions,
) -> Result<String, String> {
    let strategy = result
        .strategy
        .as_ref()
        .ok_or_else(|| "runtime result does not contain strategy alerts".to_owned())?;
    let alert = strategy.alerts.get(template.index).ok_or_else(|| {
        format!(
            "strategy alert index {} is out of range for {} alert(s)",
            template.index,
            strategy.alerts.len()
        )
    })?;
    pine_runtime::render_strategy_order_fill_alert_template(&template.template, alert)
        .map_err(|err| err.to_string())
}

fn render_strategy_running_alert(
    result: &RuntimeResult,
    running_alert: &StrategyRunningAlertOptions,
) -> Result<String, String> {
    let strategy = result
        .strategy
        .as_ref()
        .ok_or_else(|| "runtime result does not contain strategy alerts".to_owned())?;
    let alert = strategy.alerts.get(running_alert.index).ok_or_else(|| {
        format!(
            "strategy alert index {} is out of range for {} alert(s)",
            running_alert.index,
            strategy.alerts.len()
        )
    })?;
    pine_runtime::render_strategy_order_fill_running_alert(&running_alert.config, alert)
        .map_err(|err| err.to_string())
}

fn parse_options(args: &[String]) -> Result<RunOptions, String> {
    let Some(path) = args.first() else {
        return Err(usage());
    };
    let mut options = RunOptions {
        path: path.clone(),
        bars_path: String::new(),
        chart_context: ChartContext::default(),
        profile: false,
        request_bars: Vec::new(),
        library_sources: Vec::new(),
        input_overrides: Vec::new(),
        strategy_alert_template: None,
        strategy_running_alert: None,
    };
    let mut strategy_alert_template = None;
    let mut strategy_running_alert_template = None;
    let mut running_alert_script_snapshot_id = None;
    let mut running_alert_symbol = None;
    let mut running_alert_timeframe = None;
    let mut strategy_alert_index = None;
    let mut index = 1;
    while index < args.len() {
        match args[index].as_str() {
            "--bars" => {
                index += 1;
                let Some(value) = args.get(index) else {
                    return Err(usage());
                };
                options.bars_path = value.clone();
            }
            "--profile" => {
                options.profile = true;
            }
            "--chart-symbol" => {
                index += 1;
                let Some(value) = args.get(index) else {
                    return Err(usage());
                };
                if value.trim().is_empty() {
                    return Err("chart symbol must not be empty".to_owned());
                }
                options.chart_context = options.chart_context.clone().with_symbol(value.trim());
            }
            "--chart-timeframe" => {
                index += 1;
                let Some(value) = args.get(index) else {
                    return Err(usage());
                };
                let timeframe =
                    RequestTimeframe::parse(value).map_err(|error| error.to_string())?;
                options.chart_context = options.chart_context.clone().with_timeframe(timeframe);
            }
            "--render-strategy-order-alert-template" => {
                index += 1;
                let Some(value) = args.get(index) else {
                    return Err(usage());
                };
                strategy_alert_template = Some(value.clone());
            }
            "--render-strategy-running-alert" => {
                index += 1;
                let Some(value) = args.get(index) else {
                    return Err(usage());
                };
                strategy_running_alert_template = Some(value.clone());
            }
            "--running-alert-script-snapshot-id" => {
                index += 1;
                let Some(value) = args.get(index) else {
                    return Err(usage());
                };
                running_alert_script_snapshot_id = Some(value.clone());
            }
            "--running-alert-symbol" => {
                index += 1;
                let Some(value) = args.get(index) else {
                    return Err(usage());
                };
                running_alert_symbol = Some(value.clone());
            }
            "--running-alert-timeframe" => {
                index += 1;
                let Some(value) = args.get(index) else {
                    return Err(usage());
                };
                running_alert_timeframe = Some(value.clone());
            }
            "--strategy-alert-index" => {
                index += 1;
                let Some(value) = args.get(index) else {
                    return Err(usage());
                };
                strategy_alert_index = Some(parse_strategy_alert_index(value)?);
            }
            "--request-bars" => {
                index += 1;
                let Some(value) = args.get(index) else {
                    return Err(usage());
                };
                options.request_bars.push(parse_request_bars_spec(value)?);
            }
            "--library-source" => {
                index += 1;
                let Some(value) = args.get(index) else {
                    return Err(usage());
                };
                options
                    .library_sources
                    .push(parse_library_source_spec(value)?);
            }
            "--input-override" => {
                index += 1;
                let Some(value) = args.get(index) else {
                    return Err(usage());
                };
                options
                    .input_overrides
                    .push(parse_input_override_spec(value)?);
            }
            _ => return Err(usage()),
        }
        index += 1;
    }
    if options.bars_path.is_empty() {
        return Err(usage());
    }
    if strategy_alert_template.is_some() && strategy_running_alert_template.is_some() {
        return Err(usage());
    }
    options.strategy_alert_template = match (strategy_alert_template, &strategy_alert_index) {
        (None, _) => None,
        (Some(template), Some(index)) => Some(StrategyAlertTemplateOptions {
            template,
            index: *index,
        }),
        (Some(_), None) => return Err(usage()),
    };
    options.strategy_running_alert = if options.strategy_alert_template.is_some() {
        if strategy_running_alert_template.is_some()
            || running_alert_script_snapshot_id.is_some()
            || running_alert_symbol.is_some()
            || running_alert_timeframe.is_some()
        {
            return Err(usage());
        }
        None
    } else {
        match (
            strategy_running_alert_template,
            running_alert_script_snapshot_id,
            running_alert_symbol,
            running_alert_timeframe,
            strategy_alert_index,
        ) {
            (None, None, None, None, None) => None,
            (
                Some(template),
                Some(script_snapshot_id),
                Some(symbol),
                Some(timeframe),
                Some(index),
            ) => Some(StrategyRunningAlertOptions {
                config: RunningAlertConfig::new_strategy_order_fills(
                    script_snapshot_id,
                    symbol,
                    timeframe,
                    template,
                ),
                index,
            }),
            _ => return Err(usage()),
        }
    };
    Ok(options)
}

fn parse_strategy_alert_index(value: &str) -> Result<usize, String> {
    value
        .parse()
        .map_err(|_| "strategy alert index must be a non-negative integer".to_owned())
}

fn parse_request_bars_spec(spec: &str) -> Result<RequestBarsSpec, String> {
    let Some((key, path)) = spec.split_once('=') else {
        return Err("request bars must use SYMBOL:TIMEFRAME=path.csv".to_owned());
    };
    if path.trim().is_empty() {
        return Err("request bars path must not be empty".to_owned());
    }
    let Some((symbol, timeframe)) = key.rsplit_once(':') else {
        return Err("request bars key must use SYMBOL:TIMEFRAME".to_owned());
    };
    if symbol.trim().is_empty() {
        return Err("request bars symbol must not be empty".to_owned());
    }
    let timeframe = RequestTimeframe::parse(timeframe).map_err(|err| err.to_string())?;
    Ok(RequestBarsSpec {
        key: RequestKey::new(symbol.trim(), timeframe),
        path: path.to_owned(),
    })
}

fn request_environment_from_specs(
    specs: &[RequestBarsSpec],
    chart_context: ChartContext,
) -> Result<RequestEnvironment, String> {
    if specs.is_empty() {
        return Ok(RequestEnvironment::default().for_chart(chart_context));
    }

    let mut streams = Vec::with_capacity(specs.len());
    for spec in specs {
        let text = fs::read_to_string(&spec.path)
            .map_err(|err| format!("failed to read {}: {err}", spec.path))?;
        streams.push((spec.key.clone(), parse_bars_csv(&text)?));
    }
    let provider =
        InMemoryRequestDataProvider::from_streams(streams).map_err(|err| err.to_string())?;
    Ok(RequestEnvironment::new(chart_context, Arc::new(provider)))
}

#[cfg(test)]
mod tests;
