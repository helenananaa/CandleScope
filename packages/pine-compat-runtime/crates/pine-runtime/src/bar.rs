#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Bar {
    pub time: i64,
    pub open: f64,
    pub high: f64,
    pub low: f64,
    pub close: f64,
    pub volume: f64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BarUpdateKind {
    Historical,
    Forming,
    Confirmed,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct BarUpdate {
    pub bar: Bar,
    pub kind: BarUpdateKind,
}

impl BarUpdate {
    #[must_use]
    pub const fn historical(bar: Bar) -> Self {
        Self {
            bar,
            kind: BarUpdateKind::Historical,
        }
    }

    #[must_use]
    pub const fn forming(bar: Bar) -> Self {
        Self {
            bar,
            kind: BarUpdateKind::Forming,
        }
    }

    #[must_use]
    pub const fn confirmed(bar: Bar) -> Self {
        Self {
            bar,
            kind: BarUpdateKind::Confirmed,
        }
    }

    #[must_use]
    pub const fn commits_series(self) -> bool {
        matches!(
            self.kind,
            BarUpdateKind::Historical | BarUpdateKind::Confirmed
        )
    }
}
