use pine_runtime::{
    RunningAlertConfig, RunningAlertEventSelection, RunningAlertRealtimePolicy,
    StrategyOrderFillAlertOutput,
};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyDict};

#[pyfunction]
pub(crate) fn render_strategy_order_fill_alert_template(
    template: &str,
    alert: &Bound<'_, PyAny>,
) -> PyResult<String> {
    let alert = parse_strategy_order_fill_alert(alert)?;
    pine_runtime::render_strategy_order_fill_alert_template(template, &alert)
        .map_err(|err| PyValueError::new_err(err.to_string()))
}

#[pyfunction]
pub(crate) fn render_strategy_order_fill_running_alert(
    config: &Bound<'_, PyAny>,
    alert: &Bound<'_, PyAny>,
) -> PyResult<String> {
    let config = parse_running_alert_config(config)?;
    let alert = parse_strategy_order_fill_alert(alert)?;
    pine_runtime::render_strategy_order_fill_running_alert(&config, &alert)
        .map_err(|err| PyValueError::new_err(err.to_string()))
}

fn parse_running_alert_config(item: &Bound<'_, PyAny>) -> PyResult<RunningAlertConfig> {
    let dict = item
        .cast::<PyDict>()
        .map_err(|_| PyValueError::new_err("running alert config must be a dictionary"))?;
    Ok(RunningAlertConfig {
        script_snapshot_id: config_string(dict, "scriptSnapshotId")?,
        symbol: config_string(dict, "symbol")?,
        timeframe: config_string(dict, "timeframe")?,
        event_selection: parse_event_selection(&config_string(dict, "eventSelection")?)?,
        message_template: config_string(dict, "messageTemplate")?,
        realtime_policy: parse_realtime_policy(&config_string(dict, "realtimePolicy")?)?,
    })
}

fn parse_strategy_order_fill_alert(
    item: &Bound<'_, PyAny>,
) -> PyResult<StrategyOrderFillAlertOutput> {
    let dict = item
        .cast::<PyDict>()
        .map_err(|_| PyValueError::new_err("strategy order-fill alert must be a dictionary"))?;
    Ok(StrategyOrderFillAlertOutput {
        id: dict_string(dict, "id")?,
        bar_index: dict_usize(dict, "barIndex")?,
        time: dict_i64(dict, "time")?,
        direction: dict_string(dict, "direction")?,
        qty: dict_finite_f64(dict, "qty")?,
        price: dict_finite_f64(dict, "price")?,
        entry_id: dict_optional_string(dict, "entryId")?,
        exit_id: dict_optional_string(dict, "exitId")?,
        message: dict_string(dict, "message")?,
    })
}

fn config_string(dict: &Bound<'_, PyDict>, name: &str) -> PyResult<String> {
    dict.get_item(name)?
        .ok_or_else(|| PyValueError::new_err(format!("running alert config is missing `{name}`")))?
        .extract()
        .map_err(|_| {
            PyValueError::new_err(format!("running alert config `{name}` must be a string"))
        })
}

fn parse_event_selection(value: &str) -> PyResult<RunningAlertEventSelection> {
    match value {
        "indicatorAlertCalls" => Ok(RunningAlertEventSelection::IndicatorAlertCalls),
        "strategyOrderFills" => Ok(RunningAlertEventSelection::StrategyOrderFills),
        "both" => Ok(RunningAlertEventSelection::Both),
        _ => Err(PyValueError::new_err(format!(
            "running alert config `eventSelection` has unsupported value `{value}`"
        ))),
    }
}

fn parse_realtime_policy(value: &str) -> PyResult<RunningAlertRealtimePolicy> {
    match value {
        "realtimeOnly" => Ok(RunningAlertRealtimePolicy::RealtimeOnly),
        _ => Err(PyValueError::new_err(format!(
            "running alert config `realtimePolicy` has unsupported value `{value}`"
        ))),
    }
}

fn dict_string(dict: &Bound<'_, PyDict>, name: &str) -> PyResult<String> {
    dict.get_item(name)?
        .ok_or_else(|| PyValueError::new_err(format!("strategy alert is missing `{name}`")))?
        .extract()
        .map_err(|_| PyValueError::new_err(format!("strategy alert `{name}` must be a string")))
}

fn dict_optional_string(dict: &Bound<'_, PyDict>, name: &str) -> PyResult<Option<String>> {
    let value = dict
        .get_item(name)?
        .ok_or_else(|| PyValueError::new_err(format!("strategy alert is missing `{name}`")))?;
    if value.is_none() {
        return Ok(None);
    }
    value.extract().map(Some).map_err(|_| {
        PyValueError::new_err(format!("strategy alert `{name}` must be a string or None"))
    })
}

fn dict_i64(dict: &Bound<'_, PyDict>, name: &str) -> PyResult<i64> {
    dict.get_item(name)?
        .ok_or_else(|| PyValueError::new_err(format!("strategy alert is missing `{name}`")))?
        .extract()
        .map_err(|_| PyValueError::new_err(format!("strategy alert `{name}` must be an integer")))
}

fn dict_usize(dict: &Bound<'_, PyDict>, name: &str) -> PyResult<usize> {
    dict.get_item(name)?
        .ok_or_else(|| PyValueError::new_err(format!("strategy alert is missing `{name}`")))?
        .extract()
        .map_err(|_| PyValueError::new_err(format!("strategy alert `{name}` must be an integer")))
}

fn dict_finite_f64(dict: &Bound<'_, PyDict>, name: &str) -> PyResult<f64> {
    let value: f64 = dict
        .get_item(name)?
        .ok_or_else(|| PyValueError::new_err(format!("strategy alert is missing `{name}`")))?
        .extract()
        .map_err(|_| PyValueError::new_err(format!("strategy alert `{name}` must be numeric")))?;
    if value.is_finite() {
        return Ok(value);
    }
    Err(PyValueError::new_err(format!(
        "strategy alert `{name}` value must be finite"
    )))
}
