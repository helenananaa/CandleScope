use pine_ir::{CallSiteId, HirCallArg};

use crate::algorithms::numeric::{NumericExtreme, finite_float_or_na, numeric_extreme};
use crate::algorithms::random::{default_random_seed, mix_random_seed};
use crate::builtins::args::RuntimeArgs;
use crate::runtime::call_context::RuntimeCallContext;
use crate::{PineValue, RuntimeError};

pub(crate) fn eval_math_call(
    context: &mut RuntimeCallContext<'_, '_>,
    callee: &str,
    call_site_id: CallSiteId,
    raw_args: &[HirCallArg],
) -> Option<Result<PineValue, RuntimeError>> {
    if !callee.starts_with("math.") {
        return None;
    }

    let args = RuntimeArgs::new(raw_args);
    Some(match callee {
        "math.abs" => eval_math_abs(context, args),
        "math.max" => eval_math_extreme(context, args, NumericExtreme::Max),
        "math.min" => eval_math_extreme(context, args, NumericExtreme::Min),
        "math.avg" => eval_math_avg(context, args),
        "math.floor" => eval_math_floor(context, args),
        "math.ceil" => eval_math_ceil(context, args),
        "math.trunc" => eval_math_trunc(context, args),
        "math.sqrt" => eval_math_unary_float(context, args, f64::sqrt),
        "math.cbrt" => eval_math_unary_float(context, args, f64::cbrt),
        "math.log" => eval_math_unary_float(context, args, f64::ln),
        "math.log10" => eval_math_unary_float(context, args, f64::log10),
        "math.exp" => eval_math_unary_float(context, args, f64::exp),
        "math.acos" => eval_math_unary_float(context, args, f64::acos),
        "math.asin" => eval_math_unary_float(context, args, f64::asin),
        "math.atan" => eval_math_unary_float(context, args, f64::atan),
        "math.sign" => eval_math_sign(context, args),
        "math.todegrees" => eval_math_unary_float(context, args, f64::to_degrees),
        "math.toradians" => eval_math_unary_float(context, args, f64::to_radians),
        "math.sin" => eval_math_unary_float(context, args, f64::sin),
        "math.cos" => eval_math_unary_float(context, args, f64::cos),
        "math.tan" => eval_math_unary_float(context, args, f64::tan),
        "math.pow" => eval_math_pow(context, args),
        "math.hypot" => eval_math_hypot(context, args),
        "math.round" => eval_math_round(context, args),
        "math.round_to_mintick" => eval_math_round_to_mintick(context, args),
        "math.random" => eval_math_random(context, call_site_id, args),
        "math.sum" => eval_math_sum(context, call_site_id, args),
        _ => return None,
    })
}

fn eval_math_abs(
    context: &mut RuntimeCallContext<'_, '_>,
    args: RuntimeArgs<'_>,
) -> Result<PineValue, RuntimeError> {
    match args.value(context, 0)? {
        PineValue::Int(value) => Ok(value
            .checked_abs()
            .map(PineValue::Int)
            .unwrap_or_else(|| PineValue::Float((value as f64).abs()))),
        PineValue::Float(value) => Ok(PineValue::Float(value.abs())),
        PineValue::Na => Ok(PineValue::Na),
        _ => Ok(PineValue::Na),
    }
}

fn eval_math_round(
    context: &mut RuntimeCallContext<'_, '_>,
    args: RuntimeArgs<'_>,
) -> Result<PineValue, RuntimeError> {
    let value = args.value(context, 0)?;
    if args.len() == 1 {
        return match value {
            PineValue::Int(value) => Ok(PineValue::Int(value)),
            PineValue::Float(value) => Ok(float_to_int_or_na(round_ties_up(value))),
            PineValue::Na => Ok(PineValue::Na),
            _ => Ok(PineValue::Na),
        };
    }

    let Some(value) = value.as_f64() else {
        return Ok(PineValue::Na);
    };
    let Some(precision) = args.value(context, 1)?.as_i64() else {
        return Ok(PineValue::Na);
    };
    let precision = precision.clamp(i32::MIN as i64, i32::MAX as i64) as i32;
    let factor = 10_f64.powi(precision);
    Ok(finite_float_or_na(round_ties_up(value * factor) / factor))
}

fn round_ties_up(value: f64) -> f64 {
    (value + 0.5).floor()
}

fn float_to_int_or_na(value: f64) -> PineValue {
    const I64_MAX_EXCLUSIVE: f64 = 9_223_372_036_854_775_808.0;
    if !value.is_finite() || value < i64::MIN as f64 || value >= I64_MAX_EXCLUSIVE {
        PineValue::Na
    } else {
        PineValue::Int(value as i64)
    }
}

fn eval_math_round_to_mintick(
    context: &mut RuntimeCallContext<'_, '_>,
    args: RuntimeArgs<'_>,
) -> Result<PineValue, RuntimeError> {
    let Some(value) = args.value(context, 0)?.as_f64() else {
        return Ok(PineValue::Na);
    };
    let mintick = pine_builtins::named_float_constant("syminfo.mintick").unwrap_or(0.01);
    if !value.is_finite() || mintick <= 0.0 || !mintick.is_finite() {
        return Ok(PineValue::Na);
    }
    let rounded_ticks = (value / mintick + 0.5).floor();
    Ok(finite_float_or_na(rounded_ticks * mintick))
}

fn eval_math_random(
    context: &mut RuntimeCallContext<'_, '_>,
    call_site_id: CallSiteId,
    args: RuntimeArgs<'_>,
) -> Result<PineValue, RuntimeError> {
    let min = match args.optional_value(context, 0)? {
        Some(value) => {
            let Some(value) = value.as_f64() else {
                return Ok(PineValue::Na);
            };
            value
        }
        None => 0.0,
    };
    let max = match args.optional_value(context, 1)? {
        Some(value) => {
            let Some(value) = value.as_f64() else {
                return Ok(PineValue::Na);
            };
            value
        }
        None => 1.0,
    };
    let seed = match args.optional_value(context, 2)? {
        Some(value) => value.as_i64(),
        None => None,
    };

    if !min.is_finite() || !max.is_finite() || min >= max {
        return Ok(PineValue::Na);
    }

    let initial_state = seed.map_or_else(
        || default_random_seed(call_site_id),
        |seed| mix_random_seed(seed as u64),
    );
    let unit = context.next_random_unit(call_site_id, initial_state);
    Ok(finite_float_or_na(min + (max - min) * unit))
}

fn eval_math_sum(
    context: &mut RuntimeCallContext<'_, '_>,
    call_site_id: CallSiteId,
    args: RuntimeArgs<'_>,
) -> Result<PineValue, RuntimeError> {
    let source = args.value(context, 0)?;
    let length = args.value(context, 1)?.as_i64().unwrap_or(0);
    if length <= 0 {
        return Ok(PineValue::Na);
    }

    let length = length as usize;
    let window = context.update_rolling_window(call_site_id, source, length);
    if !window.is_ready(length) {
        return Ok(PineValue::Na);
    }

    Ok(finite_float_or_na(window.sum))
}

fn eval_math_floor(
    context: &mut RuntimeCallContext<'_, '_>,
    args: RuntimeArgs<'_>,
) -> Result<PineValue, RuntimeError> {
    match args.value(context, 0)? {
        PineValue::Int(value) => Ok(PineValue::Int(value)),
        PineValue::Float(value) => Ok(float_to_int_or_na(value.floor())),
        PineValue::Na => Ok(PineValue::Na),
        _ => Ok(PineValue::Na),
    }
}

fn eval_math_ceil(
    context: &mut RuntimeCallContext<'_, '_>,
    args: RuntimeArgs<'_>,
) -> Result<PineValue, RuntimeError> {
    match args.value(context, 0)? {
        PineValue::Int(value) => Ok(PineValue::Int(value)),
        PineValue::Float(value) => Ok(float_to_int_or_na(value.ceil())),
        PineValue::Na => Ok(PineValue::Na),
        _ => Ok(PineValue::Na),
    }
}

fn eval_math_trunc(
    context: &mut RuntimeCallContext<'_, '_>,
    args: RuntimeArgs<'_>,
) -> Result<PineValue, RuntimeError> {
    match args.value(context, 0)? {
        PineValue::Int(value) => Ok(PineValue::Int(value)),
        PineValue::Float(value) => Ok(float_to_int_or_na(value.trunc())),
        PineValue::Na => Ok(PineValue::Na),
        _ => Ok(PineValue::Na),
    }
}

fn eval_math_unary_float(
    context: &mut RuntimeCallContext<'_, '_>,
    args: RuntimeArgs<'_>,
    op: impl FnOnce(f64) -> f64,
) -> Result<PineValue, RuntimeError> {
    let Some(value) = args.value(context, 0)?.as_f64() else {
        return Ok(PineValue::Na);
    };
    Ok(finite_float_or_na(op(value)))
}

fn eval_math_sign(
    context: &mut RuntimeCallContext<'_, '_>,
    args: RuntimeArgs<'_>,
) -> Result<PineValue, RuntimeError> {
    let Some(value) = args.value(context, 0)?.as_f64() else {
        return Ok(PineValue::Na);
    };
    Ok(PineValue::Float(if value > 0.0 {
        1.0
    } else if value < 0.0 {
        -1.0
    } else {
        0.0
    }))
}

fn eval_math_pow(
    context: &mut RuntimeCallContext<'_, '_>,
    args: RuntimeArgs<'_>,
) -> Result<PineValue, RuntimeError> {
    let Some(base) = args.value(context, 0)?.as_f64() else {
        return Ok(PineValue::Na);
    };
    let Some(exponent) = args.value(context, 1)?.as_f64() else {
        return Ok(PineValue::Na);
    };
    Ok(finite_float_or_na(base.powf(exponent)))
}

fn eval_math_hypot(
    context: &mut RuntimeCallContext<'_, '_>,
    args: RuntimeArgs<'_>,
) -> Result<PineValue, RuntimeError> {
    let Some(left) = args.value(context, 0)?.as_f64() else {
        return Ok(PineValue::Na);
    };
    let Some(right) = args.value(context, 1)?.as_f64() else {
        return Ok(PineValue::Na);
    };
    Ok(finite_float_or_na(left.hypot(right)))
}

fn eval_math_avg(
    context: &mut RuntimeCallContext<'_, '_>,
    args: RuntimeArgs<'_>,
) -> Result<PineValue, RuntimeError> {
    let mut total = 0.0;
    let mut count = 0.0;

    for expr in args.exprs() {
        let Some(value) = context.eval_expr(expr)?.as_f64() else {
            return Ok(PineValue::Na);
        };
        total += value;
        count += 1.0;
    }

    if count == 0.0 {
        return Ok(PineValue::Na);
    }
    Ok(finite_float_or_na(total / count))
}

fn eval_math_extreme(
    context: &mut RuntimeCallContext<'_, '_>,
    args: RuntimeArgs<'_>,
    mode: NumericExtreme,
) -> Result<PineValue, RuntimeError> {
    let mut current_int: Option<i64> = None;
    let mut current_float: Option<f64> = None;

    for expr in args.exprs() {
        match context.eval_expr(expr)? {
            PineValue::Int(value) => {
                if let Some(current) = current_float.as_mut() {
                    *current = numeric_extreme(*current, value as f64, mode);
                } else {
                    current_int = Some(match current_int {
                        Some(current) => match mode {
                            NumericExtreme::Max => current.max(value),
                            NumericExtreme::Min => current.min(value),
                        },
                        None => value,
                    });
                }
            }
            PineValue::Float(value) => {
                current_float = Some(if let Some(current) = current_float {
                    numeric_extreme(current, value, mode)
                } else if let Some(current) = current_int.take() {
                    numeric_extreme(current as f64, value, mode)
                } else {
                    value
                });
            }
            PineValue::Na => return Ok(PineValue::Na),
            _ => return Ok(PineValue::Na),
        }
    }

    match (current_float, current_int) {
        (Some(value), _) => Ok(PineValue::Float(value)),
        (None, Some(value)) => Ok(PineValue::Int(value)),
        (None, None) => Ok(PineValue::Na),
    }
}
