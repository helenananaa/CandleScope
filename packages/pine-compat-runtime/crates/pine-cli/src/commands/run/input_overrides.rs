use std::collections::HashMap;

use pine_runtime::{InputOverrides, PineValue};

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
    input_names: &HashMap<u32, String>,
) -> Result<InputOverrides, String> {
    if specs.is_empty() {
        return Ok(InputOverrides::new());
    }

    let mut overrides = InputOverrides::new();
    for spec in specs {
        let Some(input_name) = input_names.get(&spec.call_site_id) else {
            return Err(format!(
                "input override contains unknown callSiteId {}",
                spec.call_site_id
            ));
        };
        let value = parse_input_override_value(input_name, &spec.value)?;
        if overrides.insert(spec.call_site_id, value).is_some() {
            return Err(format!(
                "duplicate input override for callSiteId {}",
                spec.call_site_id
            ));
        }
    }
    Ok(overrides)
}

fn parse_input_override_value(input_name: &str, value: &str) -> Result<PineValue, String> {
    match input_name {
        "input" => parse_generic_input_override(value),
        "input.int" | "input.time" => parse_i64_input_override(input_name, value),
        "input.float" | "input.price" => parse_f64_input_override(input_name, value),
        "input.bool" => parse_bool_input_override(input_name, value),
        "input.color" => parse_color_input_override(value),
        "input.string" | "input.symbol" | "input.timeframe" | "input.session"
        | "input.text_area" => Ok(PineValue::String(value.to_owned())),
        "input.source" => Err("input.source overrides are not supported".to_owned()),
        _ => Err(format!(
            "input override cannot override unsupported input call {input_name}"
        )),
    }
}

fn parse_generic_input_override(value: &str) -> Result<PineValue, String> {
    let trimmed = value.trim();
    if let Some(value) = parse_bool_literal(trimmed) {
        return Ok(PineValue::Bool(value));
    }
    if let Ok(value) = trimmed.parse::<i64>() {
        return Ok(PineValue::Int(value));
    }
    if let Ok(value) = trimmed.parse::<f64>() {
        if value.is_finite() {
            return Ok(PineValue::Float(value));
        }
        return Err("input override float must be finite".to_owned());
    }
    if trimmed.starts_with('#') || trimmed.starts_with("0x") || trimmed.starts_with("0X") {
        return parse_color_u32(trimmed).map(PineValue::Color);
    }
    Ok(PineValue::String(value.to_owned()))
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
