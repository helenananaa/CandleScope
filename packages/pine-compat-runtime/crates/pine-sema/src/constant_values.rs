#[derive(Debug, Clone, Copy, PartialEq)]
pub(crate) enum ConstValue {
    Int(i64),
    Float(f64),
    Bool(bool),
}

impl ConstValue {
    pub(crate) fn as_int(self) -> Option<i64> {
        match self {
            Self::Int(value) => Some(value),
            Self::Float(_) | Self::Bool(_) => None,
        }
    }

    pub(crate) fn as_numeric(self) -> Option<f64> {
        match self {
            Self::Int(value) => Some(value as f64),
            Self::Float(value) if value.is_finite() => Some(value),
            Self::Float(_) | Self::Bool(_) => None,
        }
    }
}

pub(crate) fn exact_i64_from_numeric(value: f64) -> Option<i64> {
    const I64_MAX_EXCLUSIVE: f64 = 9_223_372_036_854_775_808.0;
    (value.is_finite()
        && value.trunc() == value
        && value >= i64::MIN as f64
        && value < I64_MAX_EXCLUSIVE)
        .then_some(value as i64)
}

pub(crate) fn eval_pure_const_call(callee: &str, args: &[ConstValue]) -> Option<ConstValue> {
    match callee {
        "int" => eval_int_cast(args),
        "float" => eval_float_cast(args),
        "math.abs" => eval_math_abs(args),
        "math.max" => eval_math_extreme(args, NumericExtreme::Max),
        "math.min" => eval_math_extreme(args, NumericExtreme::Min),
        "math.floor" => eval_float_to_int(args, f64::floor),
        "math.ceil" => eval_float_to_int(args, f64::ceil),
        "math.trunc" => eval_float_to_int(args, f64::trunc),
        _ => None,
    }
}

fn unary_arg(args: &[ConstValue]) -> Option<ConstValue> {
    let [value] = args else {
        return None;
    };
    Some(*value)
}

fn eval_int_cast(args: &[ConstValue]) -> Option<ConstValue> {
    match unary_arg(args)? {
        ConstValue::Int(value) => Some(ConstValue::Int(value)),
        ConstValue::Float(value) if value.is_finite() => {
            // Match the runtime cast exactly: Rust's float-to-int conversion
            // truncates and saturates values outside the i64 range.
            Some(ConstValue::Int(value.trunc() as i64))
        }
        ConstValue::Float(_) => None,
        ConstValue::Bool(value) => Some(ConstValue::Int(i64::from(value))),
    }
}

fn eval_float_cast(args: &[ConstValue]) -> Option<ConstValue> {
    let value = match unary_arg(args)? {
        ConstValue::Int(value) => value as f64,
        ConstValue::Float(value) => value,
        ConstValue::Bool(value) => {
            if value {
                1.0
            } else {
                0.0
            }
        }
    };
    value.is_finite().then_some(ConstValue::Float(value))
}

fn eval_math_abs(args: &[ConstValue]) -> Option<ConstValue> {
    match unary_arg(args)? {
        ConstValue::Int(value) => value.checked_abs().map(ConstValue::Int).or_else(|| {
            let value = (value as f64).abs();
            value.is_finite().then_some(ConstValue::Float(value))
        }),
        ConstValue::Float(value) => {
            let value = value.abs();
            value.is_finite().then_some(ConstValue::Float(value))
        }
        ConstValue::Bool(_) => None,
    }
}

#[derive(Debug, Clone, Copy)]
enum NumericExtreme {
    Max,
    Min,
}

fn eval_math_extreme(args: &[ConstValue], mode: NumericExtreme) -> Option<ConstValue> {
    let first = *args.first()?;
    if args.iter().all(|value| matches!(value, ConstValue::Int(_))) {
        let mut current = first.as_int()?;
        for value in &args[1..] {
            current = match mode {
                NumericExtreme::Max => current.max(value.as_int()?),
                NumericExtreme::Min => current.min(value.as_int()?),
            };
        }
        return Some(ConstValue::Int(current));
    }

    let mut current = first.as_numeric()?;
    for value in &args[1..] {
        let value = value.as_numeric()?;
        current = match mode {
            NumericExtreme::Max => current.max(value),
            NumericExtreme::Min => current.min(value),
        };
    }
    current.is_finite().then_some(ConstValue::Float(current))
}

fn eval_float_to_int(args: &[ConstValue], operation: fn(f64) -> f64) -> Option<ConstValue> {
    match unary_arg(args)? {
        ConstValue::Int(value) => Some(ConstValue::Int(value)),
        ConstValue::Float(value) => float_to_int(operation(value)).map(ConstValue::Int),
        ConstValue::Bool(_) => None,
    }
}

fn float_to_int(value: f64) -> Option<i64> {
    const I64_MAX_EXCLUSIVE: f64 = 9_223_372_036_854_775_808.0;
    (value.is_finite() && value >= i64::MIN as f64 && value < I64_MAX_EXCLUSIVE)
        .then_some(value as i64)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn evaluates_casts_and_preserves_result_kind() {
        assert_eq!(
            eval_pure_const_call("int", &[ConstValue::Float(-2.75)]),
            Some(ConstValue::Int(-2))
        );
        assert_eq!(
            eval_pure_const_call("float", &[ConstValue::Int(2)]),
            Some(ConstValue::Float(2.0))
        );
        assert_eq!(
            eval_pure_const_call("int", &[ConstValue::Bool(true)]),
            Some(ConstValue::Int(1))
        );
    }

    #[test]
    fn evaluates_extremes_abs_and_rounding() {
        assert_eq!(
            eval_pure_const_call("math.max", &[ConstValue::Int(2), ConstValue::Int(3)]),
            Some(ConstValue::Int(3))
        );
        assert_eq!(
            eval_pure_const_call("math.min", &[ConstValue::Int(2), ConstValue::Float(1.5)]),
            Some(ConstValue::Float(1.5))
        );
        assert_eq!(
            eval_pure_const_call("math.abs", &[ConstValue::Int(-4)]),
            Some(ConstValue::Int(4))
        );
        assert_eq!(
            eval_pure_const_call("math.floor", &[ConstValue::Float(2.75)]),
            Some(ConstValue::Int(2))
        );
        assert_eq!(
            eval_pure_const_call("math.ceil", &[ConstValue::Float(2.25)]),
            Some(ConstValue::Int(3))
        );
        assert_eq!(
            eval_pure_const_call("math.trunc", &[ConstValue::Float(-2.75)]),
            Some(ConstValue::Int(-2))
        );
    }

    #[test]
    fn handles_non_finite_saturating_cast_and_invalid_arguments() {
        assert_eq!(
            eval_pure_const_call("math.abs", &[ConstValue::Int(i64::MIN)]),
            Some(ConstValue::Float(9_223_372_036_854_775_808.0))
        );
        assert_eq!(
            eval_pure_const_call("int", &[ConstValue::Float(f64::INFINITY)]),
            None
        );
        assert_eq!(
            eval_pure_const_call("int", &[ConstValue::Float(9.223_372_036_854_776e18)]),
            Some(ConstValue::Int(i64::MAX))
        );
        assert_eq!(
            eval_pure_const_call("math.floor", &[ConstValue::Float(9.223_372_036_854_776e18)]),
            None
        );
        assert_eq!(
            eval_pure_const_call("math.floor", &[ConstValue::Float(f64::NAN)]),
            None
        );
        assert_eq!(
            eval_pure_const_call("math.max", &[ConstValue::Bool(true)]),
            None
        );
        assert_eq!(eval_pure_const_call("math.min", &[]), None);
        assert_eq!(
            eval_pure_const_call("math.abs", &[ConstValue::Int(1), ConstValue::Int(2)]),
            None
        );
    }
}
