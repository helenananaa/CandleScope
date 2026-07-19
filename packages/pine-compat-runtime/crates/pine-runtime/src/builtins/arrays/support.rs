use std::cmp::Ordering;

use crate::{PineValue, finite_float_or_na};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum ArrayElementKind {
    Float,
    Int,
    Bool,
    String,
    Color,
    Label,
    Line,
    LineFill,
    Polyline,
    Box,
    Table,
    ChartPoint,
    #[allow(dead_code)]
    UserType,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct ArraySlice {
    pub(crate) parent_id: u32,
    pub(crate) start: usize,
    pub(crate) len: usize,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum ArraySearchMode {
    First,
    Last,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum ArrayBinarySearchMode {
    Exact,
    Leftmost,
    Rightmost,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum ArrayTruthMode {
    Every,
    Some,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum ArrayNumericMode {
    Min,
    Max,
    Sum,
    Avg,
    Range,
    Median,
    Mode,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum ArrayVarianceMode {
    Variance,
    Stdev,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum ArrayPercentileMode {
    NearestRank,
    LinearInterpolation,
}

pub(crate) fn infer_array_from_kind(values: &[PineValue]) -> Option<ArrayElementKind> {
    let mut inferred_kind: Option<ArrayElementKind> = None;
    for value in values {
        let next_kind = match value {
            PineValue::Na => continue,
            PineValue::Int(_) => ArrayElementKind::Int,
            PineValue::Float(_) => ArrayElementKind::Float,
            PineValue::Bool(_) => ArrayElementKind::Bool,
            PineValue::String(_) => ArrayElementKind::String,
            PineValue::Color(_) => ArrayElementKind::Color,
            PineValue::Label(_) => ArrayElementKind::Label,
            PineValue::Line(_) => ArrayElementKind::Line,
            PineValue::LineFill(_) => ArrayElementKind::LineFill,
            PineValue::Polyline(_) => ArrayElementKind::Polyline,
            PineValue::Box(_) => ArrayElementKind::Box,
            PineValue::Table(_) => ArrayElementKind::Table,
            PineValue::ChartPoint(_) => ArrayElementKind::ChartPoint,
            _ => return None,
        };
        inferred_kind = Some(match (inferred_kind, next_kind) {
            (None, kind) => kind,
            (Some(ArrayElementKind::Int), ArrayElementKind::Float)
            | (Some(ArrayElementKind::Float), ArrayElementKind::Int)
            | (Some(ArrayElementKind::Float), ArrayElementKind::Float)
            | (Some(ArrayElementKind::Int), ArrayElementKind::Int) => {
                if matches!(next_kind, ArrayElementKind::Float)
                    || matches!(inferred_kind, Some(ArrayElementKind::Float))
                {
                    ArrayElementKind::Float
                } else {
                    ArrayElementKind::Int
                }
            }
            (Some(current), kind) if current == kind => current,
            _ => return None,
        });
    }
    inferred_kind
}

pub(crate) fn array_truthy_value(value: &PineValue) -> bool {
    match value {
        PineValue::Bool(value) => *value,
        PineValue::Int(value) => *value != 0,
        PineValue::Float(value) => *value != 0.0,
        _ => false,
    }
}

pub(crate) fn normalize_array_index(index: i64, len: usize) -> Option<usize> {
    let len = i64::try_from(len).ok()?;
    let index = if index < 0 {
        len.checked_add(index)?
    } else {
        index
    };
    if (0..len).contains(&index) {
        Some(index as usize)
    } else {
        None
    }
}

pub(crate) fn normalize_array_insert_index(index: i64, len: usize) -> Option<usize> {
    let len = i64::try_from(len).ok()?;
    let index = if index < 0 {
        len.checked_add(index)?
    } else {
        index
    };
    if (0..=len).contains(&index) {
        Some(index as usize)
    } else {
        None
    }
}

pub(crate) fn array_numeric_result(kind: ArrayElementKind, value: f64) -> PineValue {
    match kind {
        ArrayElementKind::Int => PineValue::Int(value as i64),
        ArrayElementKind::Float => finite_float_or_na(value),
        _ => PineValue::Na,
    }
}

pub(crate) fn array_value_for_kind(kind: ArrayElementKind, value: PineValue) -> PineValue {
    match (kind, value) {
        (ArrayElementKind::Float, PineValue::Int(value)) => PineValue::Float(value as f64),
        (ArrayElementKind::Float, PineValue::Float(value)) => PineValue::Float(value),
        (ArrayElementKind::Int, PineValue::Int(value)) => PineValue::Int(value),
        (ArrayElementKind::Bool, PineValue::Bool(value)) => PineValue::Bool(value),
        (ArrayElementKind::String, PineValue::String(value)) => PineValue::String(value),
        (ArrayElementKind::Color, PineValue::Color(value)) => PineValue::Color(value),
        (ArrayElementKind::Label, PineValue::Label(value)) => PineValue::Label(value),
        (ArrayElementKind::Line, PineValue::Line(value)) => PineValue::Line(value),
        (ArrayElementKind::LineFill, PineValue::LineFill(value)) => PineValue::LineFill(value),
        (ArrayElementKind::Polyline, PineValue::Polyline(value)) => PineValue::Polyline(value),
        (ArrayElementKind::Box, PineValue::Box(value)) => PineValue::Box(value),
        (ArrayElementKind::Table, PineValue::Table(value)) => PineValue::Table(value),
        (ArrayElementKind::ChartPoint, PineValue::ChartPoint(value)) => {
            PineValue::ChartPoint(value)
        }
        (ArrayElementKind::UserType, PineValue::UserType(value)) => PineValue::UserType(value),
        (_, PineValue::Na) => PineValue::Na,
        _ => PineValue::Na,
    }
}

pub(crate) fn compare_array_numeric_values(left: &PineValue, right: &PineValue) -> Ordering {
    match (left.as_f64(), right.as_f64()) {
        (Some(left), Some(right)) => left.partial_cmp(&right).unwrap_or(Ordering::Equal),
        (Some(_), None) => Ordering::Less,
        (None, Some(_)) => Ordering::Greater,
        (None, None) => Ordering::Equal,
    }
}

pub(crate) fn compare_array_sort_values(
    kind: ArrayElementKind,
    left: &PineValue,
    right: &PineValue,
    descending: bool,
) -> Ordering {
    let left_is_special = is_array_sort_special(kind, left);
    let right_is_special = is_array_sort_special(kind, right);
    match (left_is_special, right_is_special) {
        (true, true) => return Ordering::Equal,
        (true, false) => {
            return if descending {
                Ordering::Less
            } else {
                Ordering::Greater
            };
        }
        (false, true) => {
            return if descending {
                Ordering::Greater
            } else {
                Ordering::Less
            };
        }
        (false, false) => {}
    }

    let ordering = match kind {
        ArrayElementKind::Float | ArrayElementKind::Int => {
            compare_array_numeric_values(left, right)
        }
        ArrayElementKind::String => match (left, right) {
            (PineValue::String(left), PineValue::String(right)) => left.cmp(right),
            _ => Ordering::Equal,
        },
        _ => Ordering::Equal,
    };
    if descending {
        ordering.reverse()
    } else {
        ordering
    }
}

pub(crate) fn compare_user_type_sort_field_values(
    left: &PineValue,
    right: &PineValue,
    field_index: usize,
    descending: bool,
) -> Ordering {
    let left = user_type_sort_field_value(left, field_index);
    let right = user_type_sort_field_value(right, field_index);
    let kind = match (&left, &right) {
        (PineValue::String(_), _) | (_, PineValue::String(_)) => ArrayElementKind::String,
        _ => ArrayElementKind::Float,
    };
    compare_array_sort_values(kind, &left, &right, descending)
}

fn user_type_sort_field_value(value: &PineValue, field_index: usize) -> PineValue {
    match value {
        PineValue::UserType(fields) => fields.get(field_index).cloned().unwrap_or(PineValue::Na),
        _ => PineValue::Na,
    }
}

pub(crate) fn is_array_sort_special(kind: ArrayElementKind, value: &PineValue) -> bool {
    matches!(value, PineValue::Na)
        || matches!(value, PineValue::Float(value) if !value.is_finite())
        || matches!(
            (kind, value),
            (ArrayElementKind::String, PineValue::String(value)) if value.is_empty()
        )
}

pub(crate) fn array_numeric_lower_bound(values: &[PineValue], target: &PineValue) -> usize {
    let mut left = 0;
    let mut right = values.len();
    while left < right {
        let mid = left + (right - left) / 2;
        if compare_array_numeric_values(&values[mid], target).is_lt() {
            left = mid + 1;
        } else {
            right = mid;
        }
    }
    left
}

pub(crate) fn array_numeric_upper_bound(values: &[PineValue], target: &PineValue) -> usize {
    let mut left = 0;
    let mut right = values.len();
    while left < right {
        let mid = left + (right - left) / 2;
        if compare_array_numeric_values(&values[mid], target).is_le() {
            left = mid + 1;
        } else {
            right = mid;
        }
    }
    left
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn does_not_infer_user_type_arrays_from_values() {
        assert_eq!(
            infer_array_from_kind(&[PineValue::UserType(vec![PineValue::Float(1.0)])]),
            None
        );
    }

    #[test]
    fn accepts_user_type_values_for_internal_user_type_array_kind() {
        assert_eq!(
            array_value_for_kind(
                ArrayElementKind::UserType,
                PineValue::UserType(vec![PineValue::Float(1.0)])
            ),
            PineValue::UserType(vec![PineValue::Float(1.0)])
        );
        assert_eq!(
            array_value_for_kind(ArrayElementKind::UserType, PineValue::Float(1.0)),
            PineValue::Na
        );
    }
}
