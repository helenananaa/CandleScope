use std::collections::HashMap;

use pine_ir::SeriesId;

use crate::PineValue;

#[derive(Debug, Default, Clone, PartialEq)]
pub struct SeriesStore {
    current_bar: usize,
    pub(crate) buffers: HashMap<SeriesId, Vec<PineValue>>,
}

impl SeriesStore {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    pub fn set_current_bar(&mut self, current_bar: usize) {
        self.current_bar = current_bar;
    }

    #[must_use]
    pub fn current_bar(&self) -> usize {
        self.current_bar
    }

    pub fn commit(&mut self, series_id: SeriesId, value: PineValue, max_depth: Option<usize>) {
        if matches!(max_depth, Some(0)) {
            self.buffers.remove(&series_id);
            return;
        }

        let buffer = self.buffers.entry(series_id).or_default();
        buffer.push(value);
        if let Some(max_depth) = max_depth {
            trim_series_buffer(buffer, max_depth);
        }
    }

    #[must_use]
    pub fn values_len(&self) -> usize {
        self.buffers.values().map(Vec::len).sum()
    }

    #[must_use]
    pub fn max_depth(&self) -> usize {
        self.buffers.values().map(Vec::len).max().unwrap_or(0)
    }

    #[must_use]
    pub fn len(&self, series_id: SeriesId) -> usize {
        self.buffers.get(&series_id).map(Vec::len).unwrap_or(0)
    }

    #[must_use]
    pub fn read(&self, series_id: SeriesId, offset: usize) -> PineValue {
        if offset == 0 {
            return PineValue::Na;
        }

        let Some(buffer) = self.buffers.get(&series_id) else {
            return PineValue::Na;
        };
        if offset > buffer.len() {
            return PineValue::Na;
        }

        buffer[buffer.len() - offset].clone()
    }
}

fn trim_series_buffer(buffer: &mut Vec<PineValue>, max_depth: usize) {
    if buffer.len() > max_depth {
        let excess = buffer.len() - max_depth;
        buffer.drain(0..excess);
    }
}
