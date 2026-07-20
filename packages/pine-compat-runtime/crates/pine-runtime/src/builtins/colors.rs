use pine_ir::HirCallArg;

use crate::*;

const COLOR_ALPHA_FLAG: u64 = 1 << 32;

pub(crate) fn parse_color_hex(value: &str) -> u64 {
    let digits = value.trim_start_matches('#');
    let parsed = u32::from_str_radix(digits, 16).unwrap_or(0);
    encode_color_literal(parsed, digits.len() == 8)
}

pub(crate) fn apply_transparency(color: u64, transp: i64) -> u64 {
    let (red, green, blue, _) = color_rgba(color);
    let rgb = (red << 16) | (green << 8) | blue;
    let transp = transp.clamp(0, 100) as u32;
    let alpha = ((100 - transp) * 255 + 50) / 100;
    compose_color(rgb, alpha)
}

pub(crate) fn color_channel(value: f64) -> u32 {
    value.round().clamp(0.0, 255.0) as u32
}

pub(crate) fn color_rgba(color: u64) -> (u32, u32, u32, u32) {
    let has_alpha_flag = color & COLOR_ALPHA_FLAG != 0;
    let payload = color & 0xFFFF_FFFF;
    let (rgb, alpha) = if has_alpha_flag || payload > 0xFF_FFFF {
        (payload >> 8, payload & 0xFF)
    } else {
        (payload, 0xFF)
    };
    (
        ((rgb >> 16) & 0xFF) as u32,
        ((rgb >> 8) & 0xFF) as u32,
        (rgb & 0xFF) as u32,
        alpha as u32,
    )
}

pub(crate) fn compose_color(rgb: u32, alpha: u32) -> u64 {
    encode_color_rgba(rgb, alpha)
}

pub(crate) fn interpolate_color(bottom_color: u64, top_color: u64, ratio: f64) -> u64 {
    if ratio <= 0.0 {
        return bottom_color;
    }
    if ratio >= 1.0 {
        return top_color;
    }

    let (bottom_red, bottom_green, bottom_blue, bottom_alpha) = color_rgba(bottom_color);
    let (top_red, top_green, top_blue, top_alpha) = color_rgba(top_color);
    let interpolate = |bottom: u32, top: u32| -> u32 {
        (bottom as f64 + (top as f64 - bottom as f64) * ratio)
            .round()
            .clamp(0.0, 255.0) as u32
    };
    let red = interpolate(bottom_red, top_red);
    let green = interpolate(bottom_green, top_green);
    let blue = interpolate(bottom_blue, top_blue);
    let alpha = interpolate(bottom_alpha, top_alpha);
    compose_color((red << 16) | (green << 8) | blue, alpha)
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum ColorComponent {
    Red,
    Green,
    Blue,
    Transparency,
}

pub(crate) fn color_component(color: u64, component: ColorComponent) -> f64 {
    let (red, green, blue, alpha) = color_rgba(color);

    match component {
        ColorComponent::Red => red as f64,
        ColorComponent::Green => green as f64,
        ColorComponent::Blue => blue as f64,
        ColorComponent::Transparency => (100.0 - (alpha as f64 * 100.0 / 255.0)).round(),
    }
}

impl<'a> HistoricalRuntime<'a> {
    pub(crate) fn eval_color_call(
        &mut self,
        callee: &str,
        args: &[HirCallArg],
    ) -> Option<Result<PineValue, RuntimeError>> {
        if !callee.starts_with("color.") {
            return None;
        }

        Some(match callee {
            "color.new" => self.eval_color_new(args),
            "color.rgb" => self.eval_color_rgb(args),
            "color.r" => self.eval_color_component(args, ColorComponent::Red),
            "color.g" => self.eval_color_component(args, ColorComponent::Green),
            "color.b" => self.eval_color_component(args, ColorComponent::Blue),
            "color.t" => self.eval_color_component(args, ColorComponent::Transparency),
            "color.from_gradient" => self.eval_color_from_gradient(args),
            _ => return None,
        })
    }

    pub(crate) fn eval_color_new(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let color = self.eval_expr(&args[0].value)?;
        let transp = if let Some(arg) = args.get(1) {
            self.eval_expr(&arg.value)?.as_i64().unwrap_or(0)
        } else {
            0
        };
        let PineValue::Color(color) = color else {
            return Ok(PineValue::Na);
        };

        Ok(PineValue::Color(apply_transparency(color, transp)))
    }

    pub(crate) fn eval_color_rgb(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let Some(red) = self.eval_expr(&args[0].value)?.as_f64() else {
            return Ok(PineValue::Na);
        };
        let Some(green) = self.eval_expr(&args[1].value)?.as_f64() else {
            return Ok(PineValue::Na);
        };
        let Some(blue) = self.eval_expr(&args[2].value)?.as_f64() else {
            return Ok(PineValue::Na);
        };
        let transp = if let Some(arg) = args.get(3) {
            let Some(transp) = self.eval_expr(&arg.value)?.as_f64() else {
                return Ok(PineValue::Na);
            };
            transp.round() as i64
        } else {
            0
        };
        let color = (color_channel(red) << 16) | (color_channel(green) << 8) | color_channel(blue);
        Ok(PineValue::Color(apply_transparency(
            u64::from(color),
            transp,
        )))
    }

    pub(crate) fn eval_color_component(
        &mut self,
        args: &[HirCallArg],
        component: ColorComponent,
    ) -> Result<PineValue, RuntimeError> {
        let PineValue::Color(color) = self.eval_expr(&args[0].value)? else {
            return Ok(PineValue::Na);
        };

        Ok(PineValue::Float(color_component(color, component)))
    }

    pub(crate) fn eval_color_from_gradient(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let Some(value) = self.eval_expr(&args[0].value)?.as_f64() else {
            return Ok(PineValue::Na);
        };
        let Some(bottom_value) = self.eval_expr(&args[1].value)?.as_f64() else {
            return Ok(PineValue::Na);
        };
        let Some(top_value) = self.eval_expr(&args[2].value)?.as_f64() else {
            return Ok(PineValue::Na);
        };
        let PineValue::Color(bottom_color) = self.eval_expr(&args[3].value)? else {
            return Ok(PineValue::Na);
        };
        let PineValue::Color(top_color) = self.eval_expr(&args[4].value)? else {
            return Ok(PineValue::Na);
        };

        let ratio = if (top_value - bottom_value).abs() < f64::EPSILON {
            1.0
        } else {
            ((value - bottom_value) / (top_value - bottom_value)).clamp(0.0, 1.0)
        };
        Ok(PineValue::Color(interpolate_color(
            bottom_color,
            top_color,
            ratio,
        )))
    }
}
