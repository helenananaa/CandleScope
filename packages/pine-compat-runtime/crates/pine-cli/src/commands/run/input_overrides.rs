use std::collections::HashMap;

use pine_runtime::{
    InputCall, InputOverrides, PineValue, ValueKind, encode_color_literal, is_valid_public_color,
};

#[derive(Debug)]
pub(super) struct InputOverrideSpec {
    pub(super) call_site_id: u32,
    pub(super) value: String,
}

pub(super) fn parse_input_override_spec(spec: &str) -> Result<InputOverrideSpec, String> {
    let Some((call_site_id, value)) = spec.split_once('=') else {
        return Err("input override must use CALL_SITE_ID=value".to_owned());
    };
    let call_site_id = call_site_id
        .trim()
        .parse::<u32>()
        .map_err(|_| "input override callSiteId must be a non-negative integer".to_owned())?;
    Ok(InputOverrideSpec {
        call_site_id,
        value: value.to_owned(),
    })
}

pub(super) fn input_overrides_from_specs(
    specs: &[InputOverrideSpec],
    input_calls: &HashMap<u32, InputCall>,
) -> Result<InputOverrides, String> {
    if specs.is_empty() {
        return Ok(InputOverrides::new());
    }

    let mut overrides = InputOverrides::new();
    for spec in specs {
        let Some(input_call) = input_calls.get(&spec.call_site_id) else {
            return Err(format!(
                "input override contains unknown callSiteId {}",
                spec.call_site_id
            ));
        };
        let value = parse_input_override_value(input_call, &spec.value)?;
        if overrides.insert(spec.call_site_id, value).is_some() {
            return Err(format!(
                "duplicate input override for callSiteId {}",
                spec.call_site_id
            ));
        }
    }
    Ok(overrides)
}

fn parse_input_override_value(input: &InputCall, value: &str) -> Result<PineValue, String> {
    match input.name.as_str() {
        "input" => parse_generic_input_override(input.value_kind, value),
        "input.int" | "input.time" => parse_i64_input_override(&input.name, value),
        "input.float" | "input.price" => parse_f64_input_override(&input.name, value),
        "input.bool" => parse_bool_input_override(&input.name, value),
        "input.color" => parse_color_input_override(value),
        "input.string" | "input.symbol" | "input.timeframe" | "input.session"
        | "input.text_area" => Ok(PineValue::String(value.to_owned())),
        "input.source" => Err("input.source overrides are not supported".to_owned()),
        _ => Err(format!(
            "input override cannot override unsupported input call {}",
            input.name
        )),
    }
}

fn parse_generic_input_override(kind: ValueKind, value: &str) -> Result<PineValue, String> {
    match kind {
        ValueKind::Int => parse_i64_input_override("input", value),
        ValueKind::Float => parse_f64_input_override("input", value),
        ValueKind::Bool => parse_bool_input_override("input", value),
        ValueKind::String => Ok(PineValue::String(value.to_owned())),
        ValueKind::Color => parse_color_input_override(value),
        _ => Err(format!(
            "input override cannot override generic input with resolved type {kind:?}"
        )),
    }
}

fn parse_i64_input_override(input_name: &str, value: &str) -> Result<PineValue, String> {
    value
        .trim()
        .parse::<i64>()
        .map(PineValue::Int)
        .map_err(|_| format!("{input_name} override must be an integer"))
}

fn parse_f64_input_override(input_name: &str, value: &str) -> Result<PineValue, String> {
    let value = value
        .trim()
        .parse::<f64>()
        .map_err(|_| format!("{input_name} override must be a float"))?;
    if value.is_finite() {
        return Ok(PineValue::Float(value));
    }
    Err(format!("{input_name} override must be a finite float"))
}

fn parse_bool_input_override(input_name: &str, value: &str) -> Result<PineValue, String> {
    let Some(value) = parse_bool_literal(value.trim()) else {
        return Err(format!("{input_name} override must be true or false"));
    };
    Ok(PineValue::Bool(value))
}

fn parse_bool_literal(value: &str) -> Option<bool> {
    if value.eq_ignore_ascii_case("true") {
        return Some(true);
    }
    if value.eq_ignore_ascii_case("false") {
        return Some(false);
    }
    None
}

fn parse_color_input_override(value: &str) -> Result<PineValue, String> {
    parse_color_value(value.trim()).map(PineValue::Color)
}

fn parse_color_value(value: &str) -> Result<u64, String> {
    let Some(value) = value.strip_prefix('#') else {
        let Some(value) = value
            .strip_prefix("0x")
            .or_else(|| value.strip_prefix("0X"))
        else {
            return parse_public_color_integer(value);
        };
        return parse_color_hex(value);
    };
    parse_color_hex(value)
}

fn parse_public_color_integer(value: &str) -> Result<u64, String> {
    let value = value.parse::<u64>().map_err(|_| color_override_error())?;
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
