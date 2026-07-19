use pine_sema::{AnalysisInput, analyze_input};
use pine_syntax::SourceFile;
use wasm_bindgen::prelude::*;

mod analysis_json;
mod input_overrides;
mod library_sources;
mod request_bars;
mod run;
mod strategy_alerts;
#[cfg(test)]
use analysis_json::json_escape;
use analysis_json::{analysis_error_json, analyze_input_json, format_diagnostics};
use library_sources::analysis_input_with_libraries;
pub use run::{
    WasmProgram, run_script_csv, run_script_csv_with_input_overrides,
    run_script_csv_with_libraries, run_script_csv_with_libraries_and_input_overrides,
    run_script_csv_with_libraries_and_request_bars,
    run_script_csv_with_libraries_and_request_bars_and_input_overrides,
    run_script_csv_with_request_bars, run_script_csv_with_request_bars_and_input_overrides,
};
#[cfg(test)]
pub(crate) use run::{
    run_script_csv_internal, run_script_csv_with_input_overrides_internal,
    run_script_csv_with_libraries_and_request_bars_internal,
    run_script_csv_with_request_bars_internal,
};

#[wasm_bindgen(js_name = compileScript)]
pub fn compile_script(source: &str) -> Result<WasmProgram, JsValue> {
    compile_program(analysis_input(source)).map_err(|err| JsValue::from_str(&err))
}

#[wasm_bindgen(js_name = compileScriptWithLibraries)]
pub fn compile_script_with_libraries(
    source: &str,
    library_sources_json: &str,
) -> Result<WasmProgram, JsValue> {
    let input = analysis_input_with_libraries(source, library_sources_json)
        .map_err(|err| JsValue::from_str(&err))?;
    compile_program(input).map_err(|err| JsValue::from_str(&err))
}

pub(crate) fn compile_program(input: AnalysisInput) -> Result<WasmProgram, String> {
    let source_file = input.root().clone();
    let analysis = analyze_input(&input);
    if !analysis.diagnostics.is_empty() {
        return Err(format_diagnostics(&source_file, &analysis.diagnostics));
    }

    let hir = analysis
        .hir
        .ok_or_else(|| "analysis did not produce executable HIR".to_string())?;
    Ok(WasmProgram::new(hir))
}

#[wasm_bindgen(js_name = analyzeScript)]
pub fn analyze_script(source: &str) -> String {
    let input = analysis_input(source);
    analyze_input_json(input)
}

#[wasm_bindgen(js_name = analyzeScriptWithLibraries)]
pub fn analyze_script_with_libraries(source: &str, library_sources_json: &str) -> String {
    match analysis_input_with_libraries(source, library_sources_json) {
        Ok(input) => analyze_input_json(input),
        Err(message) => analysis_error_json(&message),
    }
}

#[wasm_bindgen(js_name = renderStrategyOrderFillAlertTemplate)]
pub fn render_strategy_order_fill_alert_template(
    template: &str,
    alert_json: &str,
) -> Result<String, JsValue> {
    strategy_alerts::render_strategy_order_fill_alert_template(template, alert_json)
        .map_err(|err| JsValue::from_str(&err))
}

#[wasm_bindgen(js_name = renderStrategyOrderFillRunningAlert)]
pub fn render_strategy_order_fill_running_alert(
    config_json: &str,
    alert_json: &str,
) -> Result<String, JsValue> {
    strategy_alerts::render_strategy_order_fill_running_alert(config_json, alert_json)
        .map_err(|err| JsValue::from_str(&err))
}

pub(crate) fn analysis_input(source: &str) -> AnalysisInput {
    AnalysisInput::new(SourceFile::new("<wasm>", source))
}

#[cfg(test)]
mod tests;
