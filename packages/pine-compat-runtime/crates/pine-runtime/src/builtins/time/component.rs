use chrono::{DateTime, Datelike, Duration, Timelike, Utc};

use super::*;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum TimeComponent {
    Year,
    Month,
    WeekOfYear,
    DayOfMonth,
    DayOfWeek,
    Hour,
    Minute,
    Second,
}

impl TimeComponent {
    fn function_name(self) -> &'static str {
        match self {
            Self::Year => "year",
            Self::Month => "month",
            Self::WeekOfYear => "weekofyear",
            Self::DayOfMonth => "dayofmonth",
            Self::DayOfWeek => "dayofweek",
            Self::Hour => "hour",
            Self::Minute => "minute",
            Self::Second => "second",
        }
    }

    fn value(self, datetime: DateTime<Utc>) -> i64 {
        match self {
            Self::Year => datetime.year() as i64,
            Self::Month => datetime.month() as i64,
            Self::WeekOfYear => datetime.iso_week().week() as i64,
            Self::DayOfMonth => datetime.day() as i64,
            Self::DayOfWeek => dayofweek_value(datetime),
            Self::Hour => datetime.hour() as i64,
            Self::Minute => datetime.minute() as i64,
            Self::Second => datetime.second() as i64,
        }
    }
}

impl<'a> HistoricalRuntime<'a> {
    pub(super) fn eval_time_component(
        &mut self,
        args: &[HirCallArg],
        component: TimeComponent,
    ) -> Result<PineValue, RuntimeError> {
        let timestamp = match self.eval_expr(&args[0].value)? {
            PineValue::Int(value) => value,
            PineValue::Na => return Ok(PineValue::Na),
            _ => return Ok(PineValue::Na),
        };
        let timezone = if let Some(arg) = args.get(1) {
            match self.eval_expr(&arg.value)? {
                PineValue::String(timezone) => timezone,
                PineValue::Na => "UTC".to_owned(),
                _ => return Ok(PineValue::Na),
            }
        } else {
            "UTC".to_owned()
        };
        let datetime = utc_datetime_from_millis(timestamp).map_err(|_| RuntimeError {
            message: format!(
                "{} timestamp is out of range: {timestamp}",
                component.function_name()
            ),
        })?;
        let offset_seconds =
            timezone_offset_seconds(&timezone, &datetime).ok_or_else(|| RuntimeError {
                message: format!(
                    "{} unsupported timezone `{timezone}`",
                    component.function_name()
                ),
            })?;
        let Some(offset) = Duration::try_seconds(i64::from(offset_seconds)) else {
            return Err(RuntimeError {
                message: format!(
                    "{} unsupported timezone `{timezone}`",
                    component.function_name()
                ),
            });
        };
        let Some(datetime) = datetime.checked_add_signed(offset) else {
            return Err(RuntimeError {
                message: format!(
                    "{} timestamp is out of range: {timestamp}",
                    component.function_name()
                ),
            });
        };

        Ok(PineValue::Int(component.value(datetime)))
    }
}
