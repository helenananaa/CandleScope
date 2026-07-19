use std::collections::{BTreeMap, HashMap};

use pine_ir::HirProgram;
use pine_runtime::{InputOverrides, PineValue, input_calls};
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

    let input_names = input_calls(hir)
        .into_iter()
        .map(|input| (input.call_site_id, input.name))
        .collect::<HashMap<_, _>>();
    let mut overrides = InputOverrides::new();
    for (key, value) in deterministic_entries(object) {
        let call_site_id = key
            .parse::<u32>()
            .map_err(|_| "input override keys must be input callSiteId integers".to_owned())?;
        let Some(input_name) = input_names.get(&call_site_id) else {
            return Err(format!(
                "input override contains unknown callSiteId {call_site_id}"
            ));
        };
        overrides.insert(call_site_id, parse_input_override_value(input_name, value)?);
    }
    Ok(overrides)
}

fn deterministic_entries(object: &serde_json::Map<String, Value>) -> BTreeMap<&String, &Value> {
    object.iter().collect()
}

fn parse_input_override_value(input_name: &str, value: &Value) -> Result<PineValue, String> {
    match input_name {
        "input" => parse_generic_input_override(value),
        "input.int" | "input.time" => parse_i64_input_override(input_name, value),
        "input.float" | "input.price" => parse_f64_input_override(input_name, value),
        "input.bool" => parse_bool_input_override(input_name, value),
        "input.color" => parse_color_input_override(value),
        "input.string" | "input.symbol" | "input.timeframe" | "input.session"
        | "input.text_area" => Ok(PineValue::String(
            value
                .as_str()
                .ok_or_else(|| format!("{input_name} override must be a string"))?
                .to_owned(),
        )),
        "input.source" => Err("input.source overrides are not supported".to_owned()),
        _ => Err(format!(
            "input override cannot override unsupported input call {input_name}"
        )),
    }
}

fn parse_generic_input_override(value: &Value) -> Result<PineValue, String> {
    if let Some(value) = value.as_bool() {
        return Ok(PineValue::Bool(value));
    }
    if let Some(value) = value.as_i64() {
        return Ok(PineValue::Int(value));
    }
    if let Some(value) = value.as_f64() {
        if value.is_finite() {
            return Ok(PineValue::Float(value));
        }
        return Err("input override float must be finite".to_owned());
    }
    if let Some(value) = value.as_str() {
        let trimmed = value.trim();
        if trimmed.starts_with('#') || trimmed.starts_with("0x") || trimmed.starts_with("0X") {
            return parse_color_u32(trimmed).map(PineValue::Color);
        }
        return Ok(PineValue::String(value.to_owned()));
    }
    Err("input override value must be a bool, int, finite float, or string".to_owned())
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
        let value = u32::try_from(value).map_err(|_| {
            "input.color override must be a u32, 0xRRGGBB, or #RRGGBB value".to_owned()
        })?;
        return Ok(PineValue::Color(value));
    }
    let Some(value) = value.as_str() else {
        return Err("input.color override must be a u32, 0xRRGGBB, or #RRGGBB value".to_owned());
    };
    parse_color_u32(value.trim()).map(PineValue::Color)
}

fn parse_color_u32(value: &str) -> Result<u32, String> {
    let Some(value) = value.strip_prefix('#') else {
        let Some(value) = value
            .strip_prefix("0x")
            .or_else(|| value.strip_prefix("0X"))
        else {
            return value.parse::<u32>().map_err(|_| {
                "input.color override must be a u32, 0xRRGGBB, or #RRGGBB value".to_owned()
            });
        };
        return u32::from_str_radix(value, 16).map_err(|_| {
            "input.color override must be a u32, 0xRRGGBB, or #RRGGBB value".to_owned()
        });
    };
    if !matches!(value.len(), 6 | 8) {
        return Err("input.color override hex values must use #RRGGBB or #RRGGBBAA".to_owned());
    }
    u32::from_str_radix(value, 16)
        .map_err(|_| "input.color override must be a u32, 0xRRGGBB, or #RRGGBB value".to_owned())
}
