use std::collections::{BTreeMap, HashMap};

use pine_ir::{HirProgram, ValueKind};
use pine_runtime::{
    InputCall, InputOverrides, PineValue, encode_color_literal, input_calls, is_valid_public_color,
};
use serde_json::Value;

pub(crate) fn input_overrides_from_json(
    input_overrides_json: &str,
    hir: &HirProgram,
) -> Result<InputOverrides, String> {
    let value: Value = serde_json::from_str(input_overrides_json).map_err(|err| {
        format!("input overrides must be a JSON object mapping input callSiteId to values: {err}")
    })?;
    let object = value.as_object().ok_or_else(|| {
        "input overrides must be a JSON object mapping input callSiteId to values".to_owned()
    })?;
    if object.is_empty() {
        return Ok(InputOverrides::new());
    }

    let input_calls = input_calls(hir)
        .into_iter()
        .map(|input| (input.call_site_id, input))
        .collect::<HashMap<_, _>>();
    let mut overrides = InputOverrides::new();
    for (key, value) in deterministic_entries(object) {
        let call_site_id = key
            .parse::<u32>()
            .map_err(|_| "input override keys must be input callSiteId integers".to_owned())?;
        let Some(input_call) = input_calls.get(&call_site_id) else {
            return Err(format!(
                "input override contains unknown callSiteId {call_site_id}"
            ));
        };
        let value = parse_input_override_value(input_call, value)?;
        if overrides.insert(call_site_id, value).is_some() {
            return Err(format!(
                "duplicate input override for callSiteId {call_site_id}"
            ));
        }
    }
    Ok(overrides)
}

fn deterministic_entries(object: &serde_json::Map<String, Value>) -> BTreeMap<&String, &Value> {
    object.iter().collect()
}

fn parse_input_override_value(input: &InputCall, value: &Value) -> Result<PineValue, String> {
    match input.name.as_str() {
        "input" => parse_generic_input_override(input.value_kind, value),
        "input.int" | "input.time" => parse_i64_input_override(&input.name, value),
        "input.float" | "input.price" => parse_f64_input_override(&input.name, value),
        "input.bool" => parse_bool_input_override(&input.name, value),
        "input.color" => parse_color_input_override(value),
        "input.string" | "input.symbol" | "input.timeframe" | "input.session"
        | "input.text_area" => Ok(PineValue::String(
            value
                .as_str()
                .ok_or_else(|| format!("{} override must be a string", input.name))?
                .to_owned(),
        )),
        "input.source" => Err("input.source overrides are not supported".to_owned()),
        _ => Err(format!(
            "input override cannot override unsupported input call {}",
            input.name
        )),
    }
}

fn parse_generic_input_override(kind: ValueKind, value: &Value) -> Result<PineValue, String> {
    match kind {
        ValueKind::Int => parse_i64_input_override("input", value),
        ValueKind::Float => parse_f64_input_override("input", value),
        ValueKind::Bool => parse_bool_input_override("input", value),
        ValueKind::String => Ok(PineValue::String(
            value
                .as_str()
                .ok_or_else(|| "input override must be a string".to_owned())?
                .to_owned(),
        )),
        ValueKind::Color => parse_color_input_override(value),
        _ => Err(format!(
            "input override cannot override generic input with resolved type {kind:?}"
        )),
    }
}

fn parse_i64_input_override(input_name: &str, value: &Value) -> Result<PineValue, String> {
    value
        .as_i64()
        .map(PineValue::Int)
        .ok_or_else(|| format!("{input_name} override must be an integer"))
}

fn parse_f64_input_override(input_name: &str, value: &Value) -> Result<PineValue, String> {
    let value = value
        .as_f64()
        .ok_or_else(|| format!("{input_name} override must be a float"))?;
    if value.is_finite() {
        return Ok(PineValue::Float(value));
    }
    Err(format!("{input_name} override must be a finite float"))
}

fn parse_bool_input_override(input_name: &str, value: &Value) -> Result<PineValue, String> {
    value
        .as_bool()
        .map(PineValue::Bool)
        .ok_or_else(|| format!("{input_name} override must be true or false"))
}

fn parse_color_input_override(value: &Value) -> Result<PineValue, String> {
    if let Some(value) = value.as_u64() {
        return valid_public_color(value).map(PineValue::Color);
    }
    let Some(value) = value.as_str() else {
        return Err(color_override_error());
    };
    parse_color_value(value.trim()).map(PineValue::Color)
}

fn parse_color_value(value: &str) -> Result<u64, String> {
    let Some(value) = value.strip_prefix('#') else {
        let Some(value) = value
            .strip_prefix("0x")
            .or_else(|| value.strip_prefix("0X"))
        else {
            return value
                .parse::<u64>()
                .map_err(|_| color_override_error())
                .and_then(valid_public_color);
        };
        return parse_color_hex(value);
    };
    parse_color_hex(value)
}

fn valid_public_color(value: u64) -> Result<u64, String> {
    if is_valid_public_color(value) {
        Ok(value)
    } else {
        Err(color_override_error())
    }
}

fn parse_color_hex(value: &str) -> Result<u64, String> {
    if !matches!(value.len(), 6 | 8) {
        return Err(
            "input.color override hex values must use RRGGBB or RRGGBBAA digits".to_owned(),
        );
    }
    u32::from_str_radix(value, 16)
        .map(|color| encode_color_literal(color, value.len() == 8))
        .map_err(|_| color_override_error())
}

fn color_override_error() -> String {
    "input.color override must be a valid public color integer, 0xRRGGBB[AA], or #RRGGBB[AA] value"
        .to_owned()
}
