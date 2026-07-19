use std::fmt;

use crate::{DEFAULT_CHART_TIMEFRAME, builtins::time::timeframe_seconds};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RequestTimeframeError {
    value: String,
}

impl RequestTimeframeError {
    #[must_use]
    pub fn value(&self) -> &str {
        &self.value
    }
}

impl fmt::Display for RequestTimeframeError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "unsupported request timeframe `{}`", self.value)
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct RequestTimeframe {
    value: String,
    seconds: i64,
}

impl RequestTimeframe {
    pub fn parse(value: impl AsRef<str>) -> Result<Self, RequestTimeframeError> {
        let raw = value.as_ref();
        let normalized = if raw.trim().is_empty() {
            DEFAULT_CHART_TIMEFRAME
        } else {
            raw.trim()
        };
        let Some(seconds) = timeframe_seconds(normalized) else {
            return Err(RequestTimeframeError {
                value: normalized.to_owned(),
            });
        };
        Ok(Self {
            value: normalized.to_owned(),
            seconds,
        })
    }

    #[must_use]
    pub fn value(&self) -> &str {
        &self.value
    }

    #[must_use]
    pub fn seconds(&self) -> i64 {
        self.seconds
    }
}

impl Default for RequestTimeframe {
    fn default() -> Self {
        Self::parse(DEFAULT_CHART_TIMEFRAME).expect("default chart timeframe is supported")
    }
}
