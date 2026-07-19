use crate::PineValue;

use super::model::SeriesOutput;

pub(crate) fn push_series_value<T: SeriesOutput>(
    outputs: &mut Vec<T>,
    current_bar: usize,
    id: u32,
    value: PineValue,
) {
    if let Some(output) = outputs.iter_mut().find(|output| output.id() == id) {
        let values = output.values_mut();
        while values.len() < current_bar {
            values.push(PineValue::Na);
        }
        if values.len() == current_bar {
            values.push(value);
        } else if let Some(current) = values.last_mut() {
            *current = value;
        }
    } else {
        let mut values = vec![PineValue::Na; current_bar];
        values.push(value);
        outputs.push(T::new(id, values));
    }
}

pub(crate) fn finalize_series_values<T: SeriesOutput>(outputs: &mut [T], current_bar: usize) {
    for output in outputs {
        let values = output.values_mut();
        while values.len() < current_bar {
            values.push(PineValue::Na);
        }
        if values.len() == current_bar {
            values.push(PineValue::Na);
        }
    }
}
