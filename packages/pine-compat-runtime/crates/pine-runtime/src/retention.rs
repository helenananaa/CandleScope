use std::collections::HashMap;

use pine_ir::{HirProgram, SeriesId};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HistoryRetentionMode {
    StaticTrimmed,
    DynamicFull,
    MaxBarsBack,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct SeriesRetention {
    static_depths: Option<HashMap<SeriesId, usize>>,
    max_bars_back: Option<usize>,
    series_max_bars_back: HashMap<SeriesId, usize>,
}

impl SeriesRetention {
    pub(crate) fn from_program(program: &HirProgram) -> Self {
        let series_max_bars_back = program
            .series_max_bars_back
            .iter()
            .map(|value| (value.series_id, value.max_bars_back as usize))
            .collect();
        if program.history.has_dynamic_offsets {
            return Self {
                static_depths: None,
                max_bars_back: program.max_bars_back.map(|value| value as usize),
                series_max_bars_back,
            };
        }

        Self {
            static_depths: Some(
                program
                    .series_history
                    .iter()
                    .map(|requirement| {
                        (
                            requirement.series_id,
                            requirement.max_constant_offset as usize,
                        )
                    })
                    .collect(),
            ),
            max_bars_back: program.max_bars_back.map(|value| value as usize),
            series_max_bars_back,
        }
    }

    pub(crate) fn max_depth_for(&self, series_id: SeriesId) -> Option<usize> {
        let base_depth = match (&self.static_depths, self.max_bars_back) {
            (Some(depths), Some(max_bars_back)) => Some(
                depths
                    .get(&series_id)
                    .copied()
                    .unwrap_or(0)
                    .min(max_bars_back),
            ),
            (Some(depths), None) => Some(depths.get(&series_id).copied().unwrap_or(0)),
            (None, Some(max_bars_back)) => Some(max_bars_back),
            (None, None) => None,
        };
        match (
            base_depth,
            self.series_max_bars_back.get(&series_id).copied(),
        ) {
            (Some(base_depth), Some(series_max_bars_back)) => {
                Some(base_depth.min(series_max_bars_back))
            }
            (None, Some(series_max_bars_back)) => Some(series_max_bars_back),
            (base_depth, None) => base_depth,
        }
    }

    pub(crate) fn mode(&self) -> HistoryRetentionMode {
        if self.max_bars_back.is_some() || !self.series_max_bars_back.is_empty() {
            HistoryRetentionMode::MaxBarsBack
        } else if self.static_depths.is_some() {
            HistoryRetentionMode::StaticTrimmed
        } else {
            HistoryRetentionMode::DynamicFull
        }
    }
}
