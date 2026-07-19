use pine_runtime::{
    RunningAlertConfig, RunningAlertEventSelection, RunningAlertRealtimePolicy,
    StrategyOrderFillAlertOutput,
};
use serde_json::Value;

pub(crate) fn render_strategy_order_fill_alert_template(
    template: &str,
    alert_json: &str,
) -> Result<String, String> {
    let alert = strategy_order_fill_alert_from_json(alert_json)?;
    pine_runtime::render_strategy_order_fill_alert_template(template, &alert)
        .map_err(|err| err.to_string())
}

pub(crate) fn render_strategy_order_fill_running_alert(
    config_json: &str,
    alert_json: &str,
) -> Result<String, String> {
    let config = running_alert_config_from_json(config_json)?;
    let alert = strategy_order_fill_alert_from_json(alert_json)?;
    pine_runtime::render_strategy_order_fill_running_alert(&config, &alert)
        .map_err(|err| err.to_string())
}

fn running_alert_config_from_json(config_json: &str) -> Result<RunningAlertConfig, String> {
    let value: Value = serde_json::from_str(config_json)
        .map_err(|err| format!("running alert config must be a JSON object: {err}"))?;
    let object = value
        .as_object()
        .ok_or_else(|| "running alert config must be a JSON object".to_owned())?;
    Ok(RunningAlertConfig {
        script_snapshot_id: config_string(object, "scriptSnapshotId")?,
        symbol: config_string(object, "symbol")?,
        timeframe: config_string(object, "timeframe")?,
        event_selection: event_selection_from_str(&config_string(object, "eventSelection")?)?,
        message_template: config_string(object, "messageTemplate")?,
        realtime_policy: realtime_policy_from_str(&config_string(object, "realtimePolicy")?)?,
    })
}

fn strategy_order_fill_alert_from_json(
    alert_json: &str,
) -> Result<StrategyOrderFillAlertOutput, String> {
    let value: Value = serde_json::from_str(alert_json)
        .map_err(|err| format!("strategy order-fill alert must be a JSON object: {err}"))?;
    let object = value
        .as_object()
        .ok_or_else(|| "strategy order-fill alert must be a JSON object".to_owned())?;
    Ok(StrategyOrderFillAlertOutput {
        id: object_string(object, "id")?,
        bar_index: object_usize(object, "barIndex")?,
        time: object_i64(object, "time")?,
        direction: object_string(object, "direction")?,
        qty: object_finite_f64(object, "qty")?,
        price: object_finite_f64(object, "price")?,
        entry_id: object_optional_string(object, "entryId")?,
        exit_id: object_optional_string(object, "exitId")?,
        message: object_string(object, "message")?,
    })
}

fn event_selection_from_str(value: &str) -> Result<RunningAlertEventSelection, String> {
    match value {
        "indicatorAlertCalls" => Ok(RunningAlertEventSelection::IndicatorAlertCalls),
        "strategyOrderFills" => Ok(RunningAlertEventSelection::StrategyOrderFills),
        "both" => Ok(RunningAlertEventSelection::Both),
        _ => Err(format!(
            "running alert config `eventSelection` has unsupported value `{value}`"
        )),
    }
}

fn realtime_policy_from_str(value: &str) -> Result<RunningAlertRealtimePolicy, String> {
    match value {
        "realtimeOnly" => Ok(RunningAlertRealtimePolicy::RealtimeOnly),
        _ => Err(format!(
            "running alert config `realtimePolicy` has unsupported value `{value}`"
        )),
    }
}

fn config_string(object: &serde_json::Map<String, Value>, field: &str) -> Result<String, String> {
    object
        .get(field)
        .ok_or_else(|| format!("running alert config is missing `{field}`"))?
        .as_str()
        .map(str::to_owned)
        .ok_or_else(|| format!("running alert config `{field}` must be a string"))
}

fn object_string(object: &serde_json::Map<String, Value>, field: &str) -> Result<String, String> {
    object
        .get(field)
        .ok_or_else(|| format!("strategy alert is missing `{field}`"))?
        .as_str()
        .map(str::to_owned)
        .ok_or_else(|| format!("strategy alert `{field}` must be a string"))
}

fn object_optional_string(
    object: &serde_json::Map<String, Value>,
    field: &str,
) -> Result<Option<String>, String> {
    let value = object
        .get(field)
        .ok_or_else(|| format!("strategy alert is missing `{field}`"))?;
    if value.is_null() {
        return Ok(None);
    }
    value
        .as_str()
        .map(|value| Some(value.to_owned()))
        .ok_or_else(|| format!("strategy alert `{field}` must be a string or null"))
}

fn object_i64(object: &serde_json::Map<String, Value>, field: &str) -> Result<i64, String> {
    object
        .get(field)
        .ok_or_else(|| format!("strategy alert is missing `{field}`"))?
        .as_i64()
        .ok_or_else(|| format!("strategy alert `{field}` must be an integer"))
}

fn object_usize(object: &serde_json::Map<String, Value>, field: &str) -> Result<usize, String> {
    let value = object_i64(object, field)?;
    usize::try_from(value)
        .map_err(|_| format!("strategy alert `{field}` must be a non-negative integer"))
}

fn object_finite_f64(object: &serde_json::Map<String, Value>, field: &str) -> Result<f64, String> {
    let value = object
        .get(field)
        .ok_or_else(|| format!("strategy alert is missing `{field}`"))?
        .as_f64()
        .ok_or_else(|| format!("strategy alert `{field}` must be numeric"))?;
    if value.is_finite() {
        return Ok(value);
    }
    Err(format!("strategy alert `{field}` value must be finite"))
}
