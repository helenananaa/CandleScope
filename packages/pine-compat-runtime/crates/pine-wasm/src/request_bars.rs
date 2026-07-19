use std::{collections::BTreeMap, sync::Arc};

use pine_runtime::{
    Bar, ChartContext, InMemoryRequestDataProvider, RequestEnvironment, RequestKey,
    RequestTimeframe,
};
use serde_json::Value;

pub(crate) fn request_environment_from_json(
    request_bars_json: &str,
) -> Result<RequestEnvironment, String> {
    let value: Value = serde_json::from_str(request_bars_json).map_err(|err| {
        format!("request bars must be a JSON object mapping SYMBOL:TIMEFRAME to bar arrays: {err}")
    })?;
    let object = value.as_object().ok_or_else(|| {
        "request bars must be a JSON object mapping SYMBOL:TIMEFRAME to bar arrays".to_owned()
    })?;
    if object.is_empty() {
        return Ok(RequestEnvironment::default());
    }

    let mut streams = Vec::with_capacity(object.len());
    for (key, bars) in deterministic_entries(object) {
        let request_key = parse_request_key(key)?;
        streams.push((request_key, parse_bars(key, bars)?));
    }
    let provider =
        InMemoryRequestDataProvider::from_streams(streams).map_err(|err| err.to_string())?;
    Ok(RequestEnvironment::new(
        ChartContext::default(),
        Arc::new(provider),
    ))
}

fn deterministic_entries(object: &serde_json::Map<String, Value>) -> BTreeMap<&String, &Value> {
    object.iter().collect()
}

fn parse_request_key(key: &str) -> Result<RequestKey, String> {
    let Some((symbol, timeframe)) = key.rsplit_once(':') else {
        return Err("request bars key must use SYMBOL:TIMEFRAME".to_owned());
    };
    if symbol.trim().is_empty() {
        return Err("request bars symbol must not be empty".to_owned());
    }
    let timeframe = RequestTimeframe::parse(timeframe).map_err(|err| err.to_string())?;
    Ok(RequestKey::new(symbol.trim(), timeframe))
}

fn parse_bars(key: &str, value: &Value) -> Result<Vec<Bar>, String> {
    let bars = value
        .as_array()
        .ok_or_else(|| format!("request bars for key `{key}` must be an array of bar objects"))?;
    bars.iter()
        .enumerate()
        .map(|(index, bar)| parse_bar(key, index, bar))
        .collect()
}

fn parse_bar(key: &str, index: usize, value: &Value) -> Result<Bar, String> {
    let object = value
        .as_object()
        .ok_or_else(|| format!("request bar for key `{key}` at index {index} must be an object"))?;
    Ok(Bar {
        time: bar_i64(object, key, index, "time")?,
        open: bar_f64(object, key, index, "open")?,
        high: bar_f64(object, key, index, "high")?,
        low: bar_f64(object, key, index, "low")?,
        close: bar_f64(object, key, index, "close")?,
        volume: bar_f64(object, key, index, "volume")?,
    })
}

fn bar_i64(
    object: &serde_json::Map<String, Value>,
    key: &str,
    index: usize,
    field: &str,
) -> Result<i64, String> {
    let value = object.get(field).ok_or_else(|| {
        format!("request bar for key `{key}` at index {index} is missing `{field}`")
    })?;
    value.as_i64().ok_or_else(|| {
        format!("request bar field `{field}` for key `{key}` at index {index} must be an integer")
    })
}

fn bar_f64(
    object: &serde_json::Map<String, Value>,
    key: &str,
    index: usize,
    field: &str,
) -> Result<f64, String> {
    let value = object.get(field).ok_or_else(|| {
        format!("request bar for key `{key}` at index {index} is missing `{field}`")
    })?;
    value.as_f64().ok_or_else(|| {
        format!("request bar field `{field}` for key `{key}` at index {index} must be a number")
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn request_bars_json(key: &str, bars: &str) -> String {
        format!("{{\"{key}\":{bars}}}")
    }

    fn request_bars_error(json: &str) -> String {
        match request_environment_from_json(json) {
            Ok(_) => panic!("request bars JSON should fail"),
            Err(message) => message,
        }
    }

    #[test]
    fn request_bars_parses_exchange_prefixed_symbol() {
        let environment = request_environment_from_json(&request_bars_json(
            "NYSE:IBM:1",
            r#"[{"time":0,"open":10,"high":11,"low":9,"close":30,"volume":100}]"#,
        ))
        .expect("request environment");

        let bars = environment
            .provider()
            .bars(&RequestKey::new("NYSE:IBM", RequestTimeframe::default()))
            .expect("request bars");

        assert_eq!(bars.len(), 1);
        assert_eq!(bars[0].close, 30.0);
    }

    #[test]
    fn request_bars_empty_object_uses_no_request_provider() {
        let environment = request_environment_from_json("{}").expect("request environment");
        let message = environment
            .provider()
            .bars(&RequestKey::new("NYSE:IBM", RequestTimeframe::default()))
            .expect_err("empty object should keep no-provider behavior")
            .to_string();

        assert_eq!(
            message,
            "missing request data for symbol `NYSE:IBM` timeframe `1`"
        );
    }

    #[test]
    fn request_bars_rejects_non_object_json() {
        let message = request_bars_error("[]");

        assert_eq!(
            message,
            "request bars must be a JSON object mapping SYMBOL:TIMEFRAME to bar arrays"
        );
    }

    #[test]
    fn request_bars_rejects_invalid_key_without_timeframe() {
        let message = request_bars_error(&request_bars_json(
            "NYSE_IBM",
            r#"[{"time":0,"open":10,"high":11,"low":9,"close":30,"volume":100}]"#,
        ));

        assert_eq!(message, "request bars key must use SYMBOL:TIMEFRAME");
    }

    #[test]
    fn request_bars_rejects_empty_symbol() {
        let message = request_bars_error(&request_bars_json(
            ":1",
            r#"[{"time":0,"open":10,"high":11,"low":9,"close":30,"volume":100}]"#,
        ));

        assert_eq!(message, "request bars symbol must not be empty");
    }

    #[test]
    fn request_bars_rejects_invalid_timeframe() {
        let message = request_bars_error(&request_bars_json(
            "NYSE:IBM:not-a-timeframe",
            r#"[{"time":0,"open":10,"high":11,"low":9,"close":30,"volume":100}]"#,
        ));

        assert_eq!(message, "unsupported request timeframe `not-a-timeframe`");
    }

    #[test]
    fn request_bars_rejects_missing_bar_field() {
        let message = request_bars_error(&request_bars_json(
            "NYSE:IBM:1",
            r#"[{"time":0,"open":10,"high":11,"low":9,"volume":100}]"#,
        ));

        assert_eq!(
            message,
            "request bar for key `NYSE:IBM:1` at index 0 is missing `close`"
        );
    }

    #[test]
    fn request_bars_documents_duplicate_json_key_collapse() {
        let environment = request_environment_from_json(
            r#"{"NYSE:IBM:1":[{"time":0,"open":1,"high":1,"low":1,"close":1,"volume":1}],"NYSE:IBM:1":[{"time":0,"open":2,"high":2,"low":2,"close":2,"volume":2}]}"#,
        )
        .expect("serde_json map parsing collapses duplicate object keys before provider validation");

        let bars = environment
            .provider()
            .bars(&RequestKey::new("NYSE:IBM", RequestTimeframe::default()))
            .expect("request bars");

        assert_eq!(bars.len(), 1);
        assert_eq!(bars[0].close, 2.0);
    }

    #[test]
    fn request_bars_rejects_unsorted_requested_bars() {
        let message = request_bars_error(&request_bars_json(
            "NYSE:IBM:1",
            r#"[{"time":60000,"open":10,"high":11,"low":9,"close":30,"volume":100},{"time":0,"open":11,"high":12,"low":10,"close":32,"volume":100}]"#,
        ));

        assert_eq!(
            message,
            "requested bars are not sorted: `0` follows `60000`"
        );
    }

    #[test]
    fn request_bars_rejects_duplicate_requested_bar_times() {
        let message = request_bars_error(&request_bars_json(
            "NYSE:IBM:1",
            r#"[{"time":0,"open":10,"high":11,"low":9,"close":30,"volume":100},{"time":0,"open":11,"high":12,"low":10,"close":32,"volume":100}]"#,
        ));

        assert_eq!(message, "duplicate requested bar time `0`");
    }
}
