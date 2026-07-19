use pine_ir::HirProgram;
use pine_runtime::{
    Bar, InputOverrides, RequestEnvironment, public_runtime_result_json,
    run_historical_with_request_environment_and_input_overrides,
};
use wasm_bindgen::prelude::*;

use crate::input_overrides::input_overrides_from_json;
use crate::library_sources::analysis_input_with_libraries;
use crate::request_bars::request_environment_from_json;
use crate::{analysis_input, compile_program};

#[wasm_bindgen(js_name = Program)]
pub struct WasmProgram {
    hir: HirProgram,
}

impl WasmProgram {
    pub(crate) fn new(hir: HirProgram) -> Self {
        Self { hir }
    }
}

#[wasm_bindgen(js_name = runScriptCsv)]
pub fn run_script_csv(source: &str, bars_csv: &str) -> Result<String, JsValue> {
    run_script_csv_internal(source, bars_csv).map_err(|err| JsValue::from_str(&err))
}

pub(crate) fn run_script_csv_internal(source: &str, bars_csv: &str) -> Result<String, String> {
    let program = compile_program(analysis_input(source))?;
    program.run_csv_internal(bars_csv)
}

#[wasm_bindgen(js_name = runScriptCsvWithInputOverrides)]
pub fn run_script_csv_with_input_overrides(
    source: &str,
    bars_csv: &str,
    input_overrides_json: &str,
) -> Result<String, JsValue> {
    run_script_csv_with_input_overrides_internal(source, bars_csv, input_overrides_json)
        .map_err(|err| JsValue::from_str(&err))
}

pub(crate) fn run_script_csv_with_input_overrides_internal(
    source: &str,
    bars_csv: &str,
    input_overrides_json: &str,
) -> Result<String, String> {
    let program = compile_program(analysis_input(source))?;
    program.run_csv_with_input_overrides_internal(bars_csv, input_overrides_json)
}

#[wasm_bindgen(js_name = runScriptCsvWithRequestBars)]
pub fn run_script_csv_with_request_bars(
    source: &str,
    bars_csv: &str,
    request_bars_json: &str,
) -> Result<String, JsValue> {
    run_script_csv_with_request_bars_internal(source, bars_csv, request_bars_json)
        .map_err(|err| JsValue::from_str(&err))
}

pub(crate) fn run_script_csv_with_request_bars_internal(
    source: &str,
    bars_csv: &str,
    request_bars_json: &str,
) -> Result<String, String> {
    let program = compile_program(analysis_input(source))?;
    let request_environment = request_environment_from_json(request_bars_json)?;
    program.run_csv_with_request_environment_internal(bars_csv, request_environment)
}

#[wasm_bindgen(js_name = runScriptCsvWithRequestBarsAndInputOverrides)]
pub fn run_script_csv_with_request_bars_and_input_overrides(
    source: &str,
    bars_csv: &str,
    request_bars_json: &str,
    input_overrides_json: &str,
) -> Result<String, JsValue> {
    run_script_csv_with_request_bars_and_input_overrides_internal(
        source,
        bars_csv,
        request_bars_json,
        input_overrides_json,
    )
    .map_err(|err| JsValue::from_str(&err))
}

fn run_script_csv_with_request_bars_and_input_overrides_internal(
    source: &str,
    bars_csv: &str,
    request_bars_json: &str,
    input_overrides_json: &str,
) -> Result<String, String> {
    let program = compile_program(analysis_input(source))?;
    let request_environment = request_environment_from_json(request_bars_json)?;
    program.run_csv_with_request_bars_and_input_overrides_internal(
        bars_csv,
        request_environment,
        input_overrides_json,
    )
}

#[wasm_bindgen(js_name = runScriptCsvWithLibraries)]
pub fn run_script_csv_with_libraries(
    source: &str,
    bars_csv: &str,
    library_sources_json: &str,
) -> Result<String, JsValue> {
    run_script_csv_with_libraries_internal(source, bars_csv, library_sources_json)
        .map_err(|err| JsValue::from_str(&err))
}

fn run_script_csv_with_libraries_internal(
    source: &str,
    bars_csv: &str,
    library_sources_json: &str,
) -> Result<String, String> {
    let input = analysis_input_with_libraries(source, library_sources_json)?;
    let program = compile_program(input)?;
    program.run_csv_internal(bars_csv)
}

#[wasm_bindgen(js_name = runScriptCsvWithLibrariesAndInputOverrides)]
pub fn run_script_csv_with_libraries_and_input_overrides(
    source: &str,
    bars_csv: &str,
    library_sources_json: &str,
    input_overrides_json: &str,
) -> Result<String, JsValue> {
    run_script_csv_with_libraries_and_input_overrides_internal(
        source,
        bars_csv,
        library_sources_json,
        input_overrides_json,
    )
    .map_err(|err| JsValue::from_str(&err))
}

fn run_script_csv_with_libraries_and_input_overrides_internal(
    source: &str,
    bars_csv: &str,
    library_sources_json: &str,
    input_overrides_json: &str,
) -> Result<String, String> {
    let input = analysis_input_with_libraries(source, library_sources_json)?;
    let program = compile_program(input)?;
    program.run_csv_with_input_overrides_internal(bars_csv, input_overrides_json)
}

#[wasm_bindgen(js_name = runScriptCsvWithLibrariesAndRequestBars)]
pub fn run_script_csv_with_libraries_and_request_bars(
    source: &str,
    bars_csv: &str,
    library_sources_json: &str,
    request_bars_json: &str,
) -> Result<String, JsValue> {
    run_script_csv_with_libraries_and_request_bars_internal(
        source,
        bars_csv,
        library_sources_json,
        request_bars_json,
    )
    .map_err(|err| JsValue::from_str(&err))
}

pub(crate) fn run_script_csv_with_libraries_and_request_bars_internal(
    source: &str,
    bars_csv: &str,
    library_sources_json: &str,
    request_bars_json: &str,
) -> Result<String, String> {
    let input = analysis_input_with_libraries(source, library_sources_json)?;
    let program = compile_program(input)?;
    let request_environment = request_environment_from_json(request_bars_json)?;
    program.run_csv_with_request_environment_internal(bars_csv, request_environment)
}

#[wasm_bindgen(js_name = runScriptCsvWithLibrariesAndRequestBarsAndInputOverrides)]
pub fn run_script_csv_with_libraries_and_request_bars_and_input_overrides(
    source: &str,
    bars_csv: &str,
    library_sources_json: &str,
    request_bars_json: &str,
    input_overrides_json: &str,
) -> Result<String, JsValue> {
    run_script_csv_with_libraries_and_request_bars_and_input_overrides_internal(
        source,
        bars_csv,
        library_sources_json,
        request_bars_json,
        input_overrides_json,
    )
    .map_err(|err| JsValue::from_str(&err))
}

fn run_script_csv_with_libraries_and_request_bars_and_input_overrides_internal(
    source: &str,
    bars_csv: &str,
    library_sources_json: &str,
    request_bars_json: &str,
    input_overrides_json: &str,
) -> Result<String, String> {
    let input = analysis_input_with_libraries(source, library_sources_json)?;
    let program = compile_program(input)?;
    let request_environment = request_environment_from_json(request_bars_json)?;
    program.run_csv_with_request_bars_and_input_overrides_internal(
        bars_csv,
        request_environment,
        input_overrides_json,
    )
}

#[wasm_bindgen]
impl WasmProgram {
    #[wasm_bindgen(js_name = runCsv)]
    pub fn run_csv(&self, bars_csv: &str) -> Result<String, JsValue> {
        self.run_csv_internal(bars_csv)
            .map_err(|err| JsValue::from_str(&err))
    }

    #[wasm_bindgen(js_name = runCsvWithInputOverrides)]
    pub fn run_csv_with_input_overrides(
        &self,
        bars_csv: &str,
        input_overrides_json: &str,
    ) -> Result<String, JsValue> {
        self.run_csv_with_input_overrides_internal(bars_csv, input_overrides_json)
            .map_err(|err| JsValue::from_str(&err))
    }

    #[wasm_bindgen(js_name = runCsvWithRequestBars)]
    pub fn run_csv_with_request_bars(
        &self,
        bars_csv: &str,
        request_bars_json: &str,
    ) -> Result<String, JsValue> {
        self.run_csv_with_request_bars_internal(bars_csv, request_bars_json)
            .map_err(|err| JsValue::from_str(&err))
    }

    #[wasm_bindgen(js_name = runCsvWithRequestBarsAndInputOverrides)]
    pub fn run_csv_with_request_bars_and_input_overrides(
        &self,
        bars_csv: &str,
        request_bars_json: &str,
        input_overrides_json: &str,
    ) -> Result<String, JsValue> {
        let request_environment = request_environment_from_json(request_bars_json)
            .map_err(|err| JsValue::from_str(&err))?;
        self.run_csv_with_request_bars_and_input_overrides_internal(
            bars_csv,
            request_environment,
            input_overrides_json,
        )
        .map_err(|err| JsValue::from_str(&err))
    }
}

impl WasmProgram {
    fn run_csv_internal(&self, bars_csv: &str) -> Result<String, String> {
        self.run_csv_with_request_environment_internal(bars_csv, RequestEnvironment::default())
    }

    fn run_csv_with_input_overrides_internal(
        &self,
        bars_csv: &str,
        input_overrides_json: &str,
    ) -> Result<String, String> {
        let input_overrides = input_overrides_from_json(input_overrides_json, &self.hir)?;
        self.run_csv_with_request_environment_and_input_overrides_internal(
            bars_csv,
            RequestEnvironment::default(),
            input_overrides,
        )
    }

    pub(crate) fn run_csv_with_request_bars_internal(
        &self,
        bars_csv: &str,
        request_bars_json: &str,
    ) -> Result<String, String> {
        let request_environment = request_environment_from_json(request_bars_json)?;
        self.run_csv_with_request_environment_internal(bars_csv, request_environment)
    }

    fn run_csv_with_request_bars_and_input_overrides_internal(
        &self,
        bars_csv: &str,
        request_environment: RequestEnvironment,
        input_overrides_json: &str,
    ) -> Result<String, String> {
        let input_overrides = input_overrides_from_json(input_overrides_json, &self.hir)?;
        self.run_csv_with_request_environment_and_input_overrides_internal(
            bars_csv,
            request_environment,
            input_overrides,
        )
    }

    fn run_csv_with_request_environment_internal(
        &self,
        bars_csv: &str,
        request_environment: RequestEnvironment,
    ) -> Result<String, String> {
        self.run_csv_with_request_environment_and_input_overrides_internal(
            bars_csv,
            request_environment,
            InputOverrides::new(),
        )
    }

    fn run_csv_with_request_environment_and_input_overrides_internal(
        &self,
        bars_csv: &str,
        request_environment: RequestEnvironment,
        input_overrides: InputOverrides,
    ) -> Result<String, String> {
        let bars = parse_bars_csv(bars_csv)?;
        let result = run_historical_with_request_environment_and_input_overrides(
            &self.hir,
            &bars,
            request_environment,
            input_overrides,
        )
        .map_err(|err| format!("runtime failed: {}", err.message))?;
        Ok(public_runtime_result_json(&result))
    }
}

fn parse_bars_csv(text: &str) -> Result<Vec<Bar>, String> {
    let mut bars = Vec::new();
    for (line_index, line) in text.lines().enumerate() {
        if line.trim().is_empty() {
            continue;
        }
        if line_index == 0 && line.to_ascii_lowercase().contains("close") {
            continue;
        }

        let columns: Vec<_> = line.split(',').map(str::trim).collect();
        if columns.len() != 6 {
            return Err(format!(
                "invalid bars CSV at line {}: expected 6 columns time,open,high,low,close,volume",
                line_index + 1
            ));
        }

        bars.push(Bar {
            time: parse_time_column(columns[0], line_index)?,
            open: parse_f64_column(columns[1], line_index, "open")?,
            high: parse_f64_column(columns[2], line_index, "high")?,
            low: parse_f64_column(columns[3], line_index, "low")?,
            close: parse_f64_column(columns[4], line_index, "close")?,
            volume: parse_f64_column(columns[5], line_index, "volume")?,
        });
    }
    validate_bar_times(&bars)?;
    Ok(bars)
}

fn parse_time_column(value: &str, line_index: usize) -> Result<i64, String> {
    value.parse::<i64>().map_err(|_| {
        format!(
            "invalid `time` value `{value}` at bars CSV line {}",
            line_index + 1
        )
    })
}

fn parse_f64_column(value: &str, line_index: usize, name: &str) -> Result<f64, String> {
    let parsed = value.parse::<f64>().map_err(|_| {
        format!(
            "invalid `{name}` value `{value}` at bars CSV line {}",
            line_index + 1
        )
    })?;
    if !parsed.is_finite() {
        return Err(format!(
            "invalid `{name}` value `{value}` at bars CSV line {}: value must be finite",
            line_index + 1
        ));
    }
    Ok(parsed)
}

fn validate_bar_times(bars: &[Bar]) -> Result<(), String> {
    let mut previous_time = None;
    for bar in bars {
        if let Some(previous_time) = previous_time {
            if bar.time == previous_time {
                return Err(format!("duplicate bar time `{}` in bars CSV", bar.time));
            }
            if bar.time < previous_time {
                return Err(format!(
                    "bars CSV is not sorted: `{}` follows `{previous_time}`",
                    bar.time
                ));
            }
        }
        previous_time = Some(bar.time);
    }
    Ok(())
}
