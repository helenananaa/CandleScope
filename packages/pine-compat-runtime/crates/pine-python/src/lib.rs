use std::collections::HashMap;

use pine_ir::HirProgram;
use pine_runtime::{
    Bar, ChartContext, InMemoryRequestDataProvider, InputOverrides, PUBLIC_ANALYSIS_SCHEMA_VERSION,
    PineValue, RequestEnvironment, RequestKey, RequestTimeframe, input_calls,
    run_historical_with_request_environment_and_input_overrides,
};
use pine_sema::{Analysis, AnalysisInput, analyze_input};
use pine_syntax::{Diagnostic, SourceFile, Span};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyBool, PyDict, PyList, PyModule, PySequence};
mod alerts;
mod diagnostics;
mod outputs;
mod tables;
#[cfg(test)]
mod tests;
use alerts::{render_strategy_order_fill_alert_template, render_strategy_order_fill_running_alert};
use diagnostics::{diagnostics_have_errors, format_diagnostics, severity_name};
use outputs::runtime_result_to_py;

#[pyclass(name = "Program", skip_from_py_object)]
#[derive(Clone)]
struct PyProgram {
    hir: HirProgram,
}

#[pymethods]
impl PyProgram {
    #[pyo3(signature = (bars, request_bars=None, input_overrides=None))]
    fn run(
        &self,
        py: Python<'_>,
        bars: &Bound<'_, PyAny>,
        request_bars: Option<&Bound<'_, PyAny>>,
        input_overrides: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        let bars = parse_bars(bars)?;
        let request_environment = parse_request_environment(request_bars)?;
        let input_overrides = parse_input_overrides(input_overrides, &self.hir)?;
        let result = run_historical_with_request_environment_and_input_overrides(
            &self.hir,
            &bars,
            request_environment,
            input_overrides,
        )
        .map_err(|err| PyValueError::new_err(err.message))?;
        runtime_result_to_py(py, &result)
    }
}

#[pyfunction(signature = (source, library_sources=None))]
fn compile_script(source: &str, library_sources: Option<&Bound<'_, PyAny>>) -> PyResult<PyProgram> {
    let input = analysis_input_from_python(source, library_sources)?;
    let source_file = input.root().clone();
    let analysis = analyze_input(&input);
    if diagnostics_have_errors(&analysis.diagnostics) {
        return Err(PyValueError::new_err(format_diagnostics(
            &source_file,
            &analysis.diagnostics,
        )));
    }

    let hir = analysis
        .hir
        .ok_or_else(|| PyValueError::new_err("analysis did not produce executable HIR"))?;
    Ok(PyProgram { hir })
}
#[pyfunction(signature = (source, library_sources=None))]
fn analyze_script(
    py: Python<'_>,
    source: &str,
    library_sources: Option<&Bound<'_, PyAny>>,
) -> PyResult<Py<PyAny>> {
    let input = analysis_input_from_python(source, library_sources)?;
    let source_file = input.root().clone();
    let analysis = analyze_input(&input);
    analysis_to_py(py, &source_file, &analysis)
}

#[pyfunction(signature = (source, bars, request_bars=None, library_sources=None, input_overrides=None))]
fn run_script(
    py: Python<'_>,
    source: &str,
    bars: &Bound<'_, PyAny>,
    request_bars: Option<&Bound<'_, PyAny>>,
    library_sources: Option<&Bound<'_, PyAny>>,
    input_overrides: Option<&Bound<'_, PyAny>>,
) -> PyResult<Py<PyAny>> {
    let program = compile_script(source, library_sources)?;
    program.run(py, bars, request_bars, input_overrides)
}

#[pymodule]
fn pine_compat(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<PyProgram>()?;
    module.add_function(wrap_pyfunction!(compile_script, module)?)?;
    module.add_function(wrap_pyfunction!(analyze_script, module)?)?;
    module.add_function(wrap_pyfunction!(run_script, module)?)?;
    module.add_function(wrap_pyfunction!(
        render_strategy_order_fill_alert_template,
        module
    )?)?;
    module.add_function(wrap_pyfunction!(
        render_strategy_order_fill_running_alert,
        module
    )?)?;
    Ok(())
}

fn parse_bars(bars: &Bound<'_, PyAny>) -> PyResult<Vec<Bar>> {
    let mut parsed = Vec::new();
    for item in bars.try_iter()? {
        let item = item?;
        parsed.push(parse_bar(&item)?);
    }
    validate_bar_times(&parsed)?;
    Ok(parsed)
}

fn validate_bar_times(bars: &[Bar]) -> PyResult<()> {
    let mut previous_time = None;
    for bar in bars {
        if let Some(previous) = previous_time {
            if bar.time == previous {
                return Err(PyValueError::new_err(format!(
                    "duplicate bar time `{}`",
                    bar.time
                )));
            }
            if bar.time < previous {
                return Err(PyValueError::new_err(format!(
                    "bars are not sorted: `{}` follows `{previous}`",
                    bar.time
                )));
            }
        }
        previous_time = Some(bar.time);
    }
    Ok(())
}

fn analysis_input_from_python(
    source: &str,
    library_sources: Option<&Bound<'_, PyAny>>,
) -> PyResult<AnalysisInput> {
    let root = SourceFile::new("<python>", source);
    let Some(library_sources) = library_sources else {
        return Ok(AnalysisInput::new(root));
    };
    let dict = library_sources.cast::<PyDict>().map_err(|_| {
        PyValueError::new_err("library_sources must be a dict mapping import key to source text")
    })?;
    let mut sources = Vec::with_capacity(dict.len());
    for (key, value) in dict {
        let key: String = key.extract()?;
        let text: String = value.extract().map_err(|_| {
            PyValueError::new_err("library_sources values must be source text strings")
        })?;
        sources.push((
            key.clone(),
            SourceFile::new(format!("<python:{key}>"), text),
        ));
    }
    AnalysisInput::with_library_sources(root, sources)
        .map_err(|err| PyValueError::new_err(err.to_string()))
}

fn parse_request_environment(
    request_bars: Option<&Bound<'_, PyAny>>,
) -> PyResult<RequestEnvironment> {
    let Some(request_bars) = request_bars else {
        return Ok(RequestEnvironment::default());
    };
    let dict = request_bars.cast::<PyDict>().map_err(|_| {
        PyValueError::new_err("request_bars must be a dict mapping SYMBOL:TIMEFRAME to bars")
    })?;
    let mut streams = Vec::with_capacity(dict.len());
    for (key, value) in dict {
        let key: String = key.extract()?;
        let request_key = parse_request_key(&key)?;
        streams.push((request_key, parse_bars(&value)?));
    }
    let provider = InMemoryRequestDataProvider::from_streams(streams)
        .map_err(|err| PyValueError::new_err(err.to_string()))?;
    Ok(RequestEnvironment::new(
        ChartContext::default(),
        std::sync::Arc::new(provider),
    ))
}

fn parse_request_key(key: &str) -> PyResult<RequestKey> {
    let Some((symbol, timeframe)) = key.rsplit_once(':') else {
        return Err(PyValueError::new_err(
            "request_bars keys must use SYMBOL:TIMEFRAME",
        ));
    };
    if symbol.trim().is_empty() {
        return Err(PyValueError::new_err(
            "request_bars symbol must not be empty",
        ));
    }
    let timeframe =
        RequestTimeframe::parse(timeframe).map_err(|err| PyValueError::new_err(err.to_string()))?;
    Ok(RequestKey::new(symbol.trim(), timeframe))
}

fn parse_input_overrides(
    input_overrides: Option<&Bound<'_, PyAny>>,
    hir: &HirProgram,
) -> PyResult<InputOverrides> {
    let Some(input_overrides) = input_overrides else {
        return Ok(InputOverrides::new());
    };
    let dict = input_overrides.cast::<PyDict>().map_err(|_| {
        PyValueError::new_err("input_overrides must be a dict mapping input callSiteId to values")
    })?;
    let input_names = input_calls(hir)
        .into_iter()
        .map(|input| (input.call_site_id, input.name))
        .collect::<HashMap<_, _>>();
    let mut overrides = InputOverrides::new();
    for (key, value) in dict {
        let call_site_id = parse_input_override_key(&key)?;
        let Some(input_name) = input_names.get(&call_site_id) else {
            return Err(PyValueError::new_err(format!(
                "input_overrides contains unknown callSiteId {call_site_id}"
            )));
        };
        let value = parse_input_override_value(input_name, &value)?;
        overrides.insert(call_site_id, value);
    }
    Ok(overrides)
}

fn parse_input_override_key(key: &Bound<'_, PyAny>) -> PyResult<u32> {
    if key.is_instance_of::<PyBool>() {
        return Err(PyValueError::new_err(
            "input_overrides keys must be input callSiteId integers",
        ));
    }
    if let Ok(value) = key.extract::<u32>() {
        return Ok(value);
    }
    if let Ok(value) = key.extract::<String>() {
        return value.parse::<u32>().map_err(|_| {
            PyValueError::new_err("input_overrides keys must be input callSiteId integers")
        });
    }
    Err(PyValueError::new_err(
        "input_overrides keys must be input callSiteId integers",
    ))
}

fn parse_input_override_value(input_name: &str, value: &Bound<'_, PyAny>) -> PyResult<PineValue> {
    match input_name {
        "input" => parse_generic_input_override(value),
        "input.int" | "input.time" => Ok(PineValue::Int(parse_int_override(input_name, value)?)),
        "input.float" | "input.price" => {
            Ok(PineValue::Float(parse_float_override(input_name, value)?))
        }
        "input.bool" => Ok(PineValue::Bool(value.extract().map_err(|_| {
            PyValueError::new_err(format!("{input_name} override must be a bool"))
        })?)),
        "input.color" => Ok(PineValue::Color(parse_color_override(value)?)),
        "input.string" | "input.symbol" | "input.timeframe" | "input.session"
        | "input.text_area" => Ok(PineValue::String(value.extract().map_err(|_| {
            PyValueError::new_err(format!("{input_name} override must be a string"))
        })?)),
        "input.source" => Err(PyValueError::new_err(
            "input.source overrides are not supported",
        )),
        _ => Err(PyValueError::new_err(format!(
            "input_overrides cannot override unsupported input call {input_name}"
        ))),
    }
}

fn parse_generic_input_override(value: &Bound<'_, PyAny>) -> PyResult<PineValue> {
    if let Ok(value) = value.extract::<bool>() {
        return Ok(PineValue::Bool(value));
    }
    if let Ok(value) = value.extract::<i64>() {
        return Ok(PineValue::Int(value));
    }
    if let Ok(value) = value.extract::<f64>() {
        if value.is_finite() {
            return Ok(PineValue::Float(value));
        }
        return Err(PyValueError::new_err("input override float must be finite"));
    }
    if let Ok(value) = value.extract::<String>() {
        let trimmed = value.trim();
        if trimmed.starts_with('#') || trimmed.starts_with("0x") || trimmed.starts_with("0X") {
            return parse_color_u32(trimmed).map(PineValue::Color);
        }
        return Ok(PineValue::String(value));
    }
    Err(PyValueError::new_err(
        "input override value must be a bool, int, finite float, or string",
    ))
}

fn parse_int_override(input_name: &str, value: &Bound<'_, PyAny>) -> PyResult<i64> {
    if value.is_instance_of::<PyBool>() {
        return Err(PyValueError::new_err(format!(
            "{input_name} override must be an int"
        )));
    }
    value
        .extract()
        .map_err(|_| PyValueError::new_err(format!("{input_name} override must be an int")))
}

fn parse_float_override(input_name: &str, value: &Bound<'_, PyAny>) -> PyResult<f64> {
    if value.is_instance_of::<PyBool>() {
        return Err(PyValueError::new_err(format!(
            "{input_name} override must be a finite float"
        )));
    }
    let value = value
        .extract::<f64>()
        .map_err(|_| PyValueError::new_err(format!("{input_name} override must be a float")))?;
    if value.is_finite() {
        return Ok(value);
    }
    Err(PyValueError::new_err(format!(
        "{input_name} override must be a finite float"
    )))
}

fn parse_color_override(value: &Bound<'_, PyAny>) -> PyResult<u32> {
    if value.is_instance_of::<PyBool>() {
        return Err(PyValueError::new_err(
            "input.color override must be a u32, 0xRRGGBB, or #RRGGBB value",
        ));
    }
    if let Ok(value) = value.extract::<i64>() {
        return u32::try_from(value).map_err(|_| {
            PyValueError::new_err("input.color override must be a u32, 0xRRGGBB, or #RRGGBB value")
        });
    }
    if let Ok(value) = value.extract::<String>() {
        return parse_color_u32(value.trim());
    }
    Err(PyValueError::new_err(
        "input.color override must be a u32, 0xRRGGBB, or #RRGGBB value",
    ))
}

fn parse_color_u32(value: &str) -> PyResult<u32> {
    let Some(value) = value.strip_prefix('#') else {
        let Some(value) = value
            .strip_prefix("0x")
            .or_else(|| value.strip_prefix("0X"))
        else {
            return value.parse::<u32>().map_err(|_| {
                PyValueError::new_err(
                    "input.color override must be a u32, 0xRRGGBB, or #RRGGBB value",
                )
            });
        };
        return u32::from_str_radix(value, 16).map_err(|_| {
            PyValueError::new_err("input.color override must be a u32, 0xRRGGBB, or #RRGGBB value")
        });
    };
    if !matches!(value.len(), 6 | 8) {
        return Err(PyValueError::new_err(
            "input.color override hex values must use #RRGGBB or #RRGGBBAA",
        ));
    }
    u32::from_str_radix(value, 16).map_err(|_| {
        PyValueError::new_err("input.color override must be a u32, 0xRRGGBB, or #RRGGBB value")
    })
}

fn parse_bar(item: &Bound<'_, PyAny>) -> PyResult<Bar> {
    if let Ok(dict) = item.cast::<PyDict>() {
        return Ok(Bar {
            time: dict_i64(dict, "time")?,
            open: dict_finite_f64(dict, "open")?,
            high: dict_finite_f64(dict, "high")?,
            low: dict_finite_f64(dict, "low")?,
            close: dict_finite_f64(dict, "close")?,
            volume: dict_finite_f64(dict, "volume")?,
        });
    }

    if let Ok(sequence) = item.cast::<PySequence>() {
        if sequence.len()? != 6 {
            return Err(PyValueError::new_err(
                "bar sequences must contain time, open, high, low, close, volume",
            ));
        }
        return Ok(Bar {
            time: sequence.get_item(0)?.extract()?,
            open: finite_bar_value(sequence.get_item(1)?.extract()?, "open")?,
            high: finite_bar_value(sequence.get_item(2)?.extract()?, "high")?,
            low: finite_bar_value(sequence.get_item(3)?.extract()?, "low")?,
            close: finite_bar_value(sequence.get_item(4)?.extract()?, "close")?,
            volume: finite_bar_value(sequence.get_item(5)?.extract()?, "volume")?,
        });
    }

    Err(PyValueError::new_err(
        "bars must be dictionaries or 6-item sequences",
    ))
}

fn dict_i64(dict: &Bound<'_, PyDict>, name: &str) -> PyResult<i64> {
    dict.get_item(name)?
        .ok_or_else(|| PyValueError::new_err(format!("bar is missing `{name}`")))?
        .extract()
}

fn dict_finite_f64(dict: &Bound<'_, PyDict>, name: &str) -> PyResult<f64> {
    let value = dict
        .get_item(name)?
        .ok_or_else(|| PyValueError::new_err(format!("bar is missing `{name}`")))?
        .extract()?;
    finite_bar_value(value, name)
}

fn finite_bar_value(value: f64, name: &str) -> PyResult<f64> {
    if value.is_finite() {
        return Ok(value);
    }

    Err(PyValueError::new_err(format!(
        "bar `{name}` value must be finite"
    )))
}

fn analysis_to_py(py: Python<'_>, source: &SourceFile, analysis: &Analysis) -> PyResult<Py<PyAny>> {
    let output = PyDict::new(py);
    output.set_item("schemaVersion", PUBLIC_ANALYSIS_SCHEMA_VERSION)?;
    output.set_item("languageVersion", analysis.compatibility.language_version)?;
    output.set_item(
        "diagnostics",
        diagnostics_to_py(py, source, &analysis.diagnostics)?,
    )?;
    output.set_item("compatibility", compatibility_to_py(py, source, analysis)?)?;
    output.set_item("executable", analysis.hir.is_some())?;
    output.set_item("inputs", inputs_to_py(py, analysis)?)?;
    Ok(output.into_any().unbind())
}

fn inputs_to_py(py: Python<'_>, analysis: &Analysis) -> PyResult<Py<PyAny>> {
    let output = PyList::empty(py);
    if let Some(hir) = &analysis.hir {
        for input in input_calls(hir) {
            let item = PyDict::new(py);
            item.set_item("callSiteId", input.call_site_id)?;
            item.set_item("name", input.name)?;
            item.set_item("title", input.title)?;
            output.append(item)?;
        }
    }
    Ok(output.into_any().unbind())
}

fn compatibility_to_py(
    py: Python<'_>,
    source: &SourceFile,
    analysis: &Analysis,
) -> PyResult<Py<PyAny>> {
    let output = PyDict::new(py);
    let supported = PyList::empty(py);
    for feature in &analysis.compatibility.supported {
        let item = PyDict::new(py);
        item.set_item("feature", &feature.feature)?;
        item.set_item("span", span_to_py(py, source, feature.span)?)?;
        supported.append(item)?;
    }

    let unsupported = PyList::empty(py);
    for feature in &analysis.compatibility.unsupported {
        let item = PyDict::new(py);
        item.set_item("feature", &feature.feature)?;
        item.set_item("reason", &feature.reason)?;
        item.set_item("span", span_to_py(py, source, feature.span)?)?;
        unsupported.append(item)?;
    }

    output.set_item("supported", supported)?;
    output.set_item("unsupported", unsupported)?;
    Ok(output.into_any().unbind())
}

fn diagnostics_to_py(
    py: Python<'_>,
    source: &SourceFile,
    diagnostics: &[Diagnostic],
) -> PyResult<Py<PyAny>> {
    let output = PyList::empty(py);
    for diagnostic in diagnostics {
        let item = PyDict::new(py);
        item.set_item("code", &diagnostic.code)?;
        item.set_item("severity", severity_name(diagnostic.severity))?;
        item.set_item("message", &diagnostic.message)?;
        item.set_item("span", span_to_py(py, source, diagnostic.span)?)?;
        output.append(item)?;
    }
    Ok(output.into_any().unbind())
}

fn span_to_py(py: Python<'_>, source: &SourceFile, span: Span) -> PyResult<Py<PyAny>> {
    let line_col = source.line_col(span.start);
    let output = PyDict::new(py);
    output.set_item("start", span.start)?;
    output.set_item("end", span.end)?;
    output.set_item("line", line_col.line)?;
    output.set_item("column", line_col.column)?;
    Ok(output.into_any().unbind())
}
