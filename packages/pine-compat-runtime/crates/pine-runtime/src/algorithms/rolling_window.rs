use std::collections::VecDeque;

use pine_ir::CallSiteId;

#[derive(Debug, Default, Clone, PartialEq)]
pub(crate) struct RollingWindowState {
    pub(crate) values: VecDeque<Option<f64>>,
    pub(crate) sum: f64,
    pub(crate) sum_squares: f64,
    pub(crate) na_count: usize,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub(crate) enum RollingWindowKey {
    Single(CallSiteId),
    VwmaWeighted(CallSiteId),
    VwmaVolume(CallSiteId),
    MfiPositive(CallSiteId),
    MfiNegative(CallSiteId),
    CmoPositive(CallSiteId),
    CmoNegative(CallSiteId),
    AoFast(CallSiteId),
    AoSlow(CallSiteId),
    CorrelationLeft(CallSiteId),
    CorrelationRight(CallSiteId),
    CorrelationProduct(CallSiteId),
    CovarianceLeft(CallSiteId),
    CovarianceRight(CallSiteId),
    CovarianceProduct(CallSiteId),
    StochHigh(CallSiteId),
    StochLow(CallSiteId),
    WprHigh(CallSiteId),
    WprLow(CallSiteId),
    HmaHalf(CallSiteId),
    HmaFull(CallSiteId),
    HmaSmooth(CallSiteId),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum WindowExtreme {
    Highest,
    Lowest,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum RisingFallingMode {
    Rising,
    Falling,
}

impl RollingWindowState {
    pub(crate) fn push(&mut self, value: Option<f64>, length: usize) {
        while self.values.len() >= length {
            self.pop_front();
        }
        if let Some(value) = value {
            self.sum += value;
            self.sum_squares += value * value;
            self.values.push_back(Some(value));
        } else {
            self.na_count += 1;
            self.values.push_back(None);
        }
    }

    pub(crate) fn pop_front(&mut self) {
        if let Some(value) = self.values.pop_front() {
            if let Some(value) = value {
                self.sum -= value;
                self.sum_squares -= value * value;
            } else {
                self.na_count = self.na_count.saturating_sub(1);
            }
        }
    }

    pub(crate) fn is_ready(&self, length: usize) -> bool {
        self.values.len() == length && self.na_count == 0
    }

    pub(crate) fn mean(&self, length: usize) -> f64 {
        self.sum / length as f64
    }

    pub(crate) fn variance(&self, length: usize, biased: bool) -> f64 {
        if !biased && length < 2 {
            return f64::NAN;
        }
        let mean = self.mean(length);
        let squared_diff_sum = self
            .values
            .iter()
            .flatten()
            .map(|value| {
                let diff = *value - mean;
                diff * diff
            })
            .sum::<f64>();
        let denominator = if biased { length } else { length - 1 };
        (squared_diff_sum / denominator as f64).max(0.0)
    }

    pub(crate) fn extreme(&self, mode: WindowExtreme) -> Option<f64> {
        self.values
            .iter()
            .flatten()
            .copied()
            .reduce(|current, value| match mode {
                WindowExtreme::Highest => current.max(value),
                WindowExtreme::Lowest => current.min(value),
            })
    }

    pub(crate) fn range(&self) -> Option<f64> {
        let highest = self.extreme(WindowExtreme::Highest)?;
        let lowest = self.extreme(WindowExtreme::Lowest)?;
        Some(highest - lowest)
    }

    pub(crate) fn mean_absolute_deviation(&self, length: usize) -> f64 {
        let mean = self.mean(length);
        self.values
            .iter()
            .flatten()
            .map(|value| (*value - mean).abs())
            .sum::<f64>()
            / length as f64
    }

    pub(crate) fn center_of_gravity(&self, length: usize) -> f64 {
        let numerator = self
            .values
            .iter()
            .flatten()
            .enumerate()
            .map(|(index, value)| *value * (length - index) as f64)
            .sum::<f64>();
        -numerator / self.sum
    }

    pub(crate) fn weighted_mean(&self, length: usize) -> f64 {
        let weighted_sum = self
            .values
            .iter()
            .flatten()
            .enumerate()
            .map(|(index, value)| *value * (index + 1) as f64)
            .sum::<f64>();
        let denominator = length * (length + 1) / 2;
        weighted_sum / denominator as f64
    }
}
