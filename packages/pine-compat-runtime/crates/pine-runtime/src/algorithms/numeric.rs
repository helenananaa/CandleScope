use crate::*;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum NumericExtreme {
    Max,
    Min,
}

pub(crate) fn finite_float_or_na(value: f64) -> PineValue {
    if value.is_finite() {
        PineValue::Float(value)
    } else {
        PineValue::Na
    }
}

pub(crate) fn numeric_extreme(left: f64, right: f64, mode: NumericExtreme) -> f64 {
    match mode {
        NumericExtreme::Max => left.max(right),
        NumericExtreme::Min => left.min(right),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn selects_numeric_extremes() {
        assert_eq!(numeric_extreme(1.0, 2.5, NumericExtreme::Max), 2.5);
        assert_eq!(numeric_extreme(1.0, 2.5, NumericExtreme::Min), 1.0);
    }
}
