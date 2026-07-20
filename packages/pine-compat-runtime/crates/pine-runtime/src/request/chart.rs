use super::RequestTimeframe;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ChartContext {
    symbol: String,
    timeframe: RequestTimeframe,
}

impl ChartContext {
    #[must_use]
    pub fn new(symbol: impl Into<String>, timeframe: RequestTimeframe) -> Self {
        Self {
            symbol: symbol.into(),
            timeframe,
        }
    }

    #[must_use]
    pub fn symbol(&self) -> &str {
        &self.symbol
    }

    #[must_use]
    pub fn timeframe(&self) -> &RequestTimeframe {
        &self.timeframe
    }

    #[must_use]
    pub fn with_symbol(mut self, symbol: impl Into<String>) -> Self {
        self.symbol = symbol.into();
        self
    }

    #[must_use]
    pub fn with_timeframe(mut self, timeframe: RequestTimeframe) -> Self {
        self.timeframe = timeframe;
        self
    }
}

impl Default for ChartContext {
    fn default() -> Self {
        Self {
            symbol: "NASDAQ:AAPL".to_owned(),
            timeframe: RequestTimeframe::default(),
        }
    }
}
