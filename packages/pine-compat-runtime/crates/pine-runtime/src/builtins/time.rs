use chrono::{DateTime, Datelike, Duration, NaiveDate, Offset, TimeZone, Utc};
use chrono_tz::{OffsetName, Tz};
use pine_ir::HirCallArg;

use crate::*;

mod component;
mod formatting;
mod session;
mod timestamp;

use self::component::TimeComponent;
pub(crate) use self::formatting::{format_datetime_with_timezone, format_utc_datetime};
use self::session::{
    DefaultSessionDays, parse_time_session, parse_time_session_timezone, session_close_for_bar_open,
};
pub(crate) use self::timestamp::{format_fixed_timezone_offset, parse_fixed_timezone_offset};
use self::timestamp::{
    numeric_timestamp_millis, parse_numeric_timestamp_timezone, parse_timestamp_date_string,
};

pub(crate) fn dayofweek_value(datetime: DateTime<Utc>) -> i64 {
    i64::from(datetime.weekday().num_days_from_sunday()) + 1
}

pub(crate) fn is_supported_utc_timezone(timezone: &str) -> bool {
    matches!(
        timezone,
        "UTC"
            | "Etc/UTC"
            | "GMT"
            | "Z"
            | "+0000"
            | "-0000"
            | "+00:00"
            | "-00:00"
            | "UTC0"
            | "UTC+0"
            | "UTC-0"
            | "UTC+0000"
            | "UTC-0000"
            | "UTC+00:00"
            | "UTC-00:00"
            | "GMT0"
            | "GMT+0"
            | "GMT-0"
            | "GMT+0000"
            | "GMT-0000"
            | "GMT+00:00"
            | "GMT-00:00"
    )
}

pub(crate) fn timezone_offset_seconds(timezone: &str, datetime: &DateTime<Utc>) -> Option<i32> {
    if let Some(offset) = parse_fixed_timezone_offset(timezone) {
        return Some(offset);
    }

    let timezone = timezone.trim().parse::<Tz>().ok()?;
    Some(
        timezone
            .offset_from_utc_datetime(&datetime.naive_utc())
            .fix()
            .local_minus_utc(),
    )
}

pub(crate) fn timezone_offset_and_short_name(
    timezone: &str,
    datetime: &DateTime<Utc>,
) -> Option<(i32, String)> {
    if let Some(offset) = parse_fixed_timezone_offset(timezone) {
        return Some((offset, fixed_timezone_short_name(offset)));
    }

    let timezone = timezone.trim().parse::<Tz>().ok()?;
    let offset = timezone.offset_from_utc_datetime(&datetime.naive_utc());
    let offset_seconds = offset.fix().local_minus_utc();
    let short_name = offset
        .abbreviation()
        .map(str::to_owned)
        .unwrap_or_else(|| fixed_timezone_short_name(offset_seconds));
    Some((offset_seconds, short_name))
}

fn fixed_timezone_short_name(offset: i32) -> String {
    if offset == 0 {
        return "UTC".to_owned();
    }
    let sign = if offset < 0 { '-' } else { '+' };
    let offset = offset.abs();
    format!("GMT{sign}{:02}:{:02}", offset / 3600, (offset % 3600) / 60)
}

pub(crate) fn timeframe_from_seconds(seconds: i64) -> Option<String> {
    if seconds <= 0 {
        return None;
    }
    if matches!(seconds, 1 | 5 | 10 | 15 | 30 | 45) {
        return Some(format!("{seconds}S"));
    }

    if seconds % 2_592_000 == 0 {
        let months = seconds / 2_592_000;
        if (1..=12).contains(&months) {
            return Some(if months == 1 {
                "M".to_owned()
            } else {
                format!("{months}M")
            });
        }
    }
    if seconds % 604_800 == 0 {
        let weeks = seconds / 604_800;
        if (1..=52).contains(&weeks) {
            return Some(if weeks == 1 {
                "W".to_owned()
            } else {
                format!("{weeks}W")
            });
        }
    }
    if seconds % 86_400 == 0 {
        let days = seconds / 86_400;
        if (1..=365).contains(&days) {
            return Some(if days == 1 {
                "D".to_owned()
            } else {
                format!("{days}D")
            });
        }
    }
    if seconds % 60 == 0 {
        let minutes = seconds / 60;
        if (1..=1440).contains(&minutes) {
            return Some(minutes.to_string());
        }
    }

    None
}

pub(crate) fn timeframe_bucket(timestamp_ms: i64, seconds: i64) -> Option<i64> {
    let duration_ms = seconds.checked_mul(1000)?;
    if duration_ms <= 0 {
        return None;
    }
    Some(timestamp_ms.div_euclid(duration_ms))
}

fn timeframe_change_bucket(timestamp_ms: i64, timeframe: &str, seconds: i64) -> Option<i64> {
    if let Some(multiplier) = calendar_timeframe_multiplier(timeframe, 'W') {
        let datetime = Utc.timestamp_millis_opt(timestamp_ms).single()?;
        let epoch_monday = NaiveDate::from_ymd_opt(1970, 1, 5)?;
        let current_monday = i64::from(datetime.date_naive().num_days_from_ce())
            - i64::from(datetime.weekday().num_days_from_monday());
        let epoch_monday = i64::from(epoch_monday.num_days_from_ce());
        let week = current_monday.checked_sub(epoch_monday)?.div_euclid(7);
        return Some(week.div_euclid(multiplier));
    }

    if let Some(multiplier) = calendar_timeframe_multiplier(timeframe, 'M') {
        let datetime = Utc.timestamp_millis_opt(timestamp_ms).single()?;
        let month = i64::from(datetime.year())
            .checked_mul(12)?
            .checked_add(i64::from(datetime.month0()))?;
        return Some(month.div_euclid(multiplier));
    }

    timeframe_bucket(timestamp_ms, seconds)
}

fn timeframe_bucket_bounds(bucket: i64, timeframe: &str, seconds: i64) -> Option<(i64, i64)> {
    const MILLIS_PER_DAY: i64 = 86_400_000;

    if let Some(multiplier) = calendar_timeframe_multiplier(timeframe, 'W') {
        let epoch_monday = Utc.with_ymd_and_hms(1970, 1, 5, 0, 0, 0).single()?;
        let duration_ms = multiplier.checked_mul(7)?.checked_mul(MILLIS_PER_DAY)?;
        let open_offset_ms = bucket.checked_mul(duration_ms)?;
        let open_time = epoch_monday
            .timestamp_millis()
            .checked_add(open_offset_ms)?;
        let close_time = open_time.checked_add(duration_ms)?;
        return Some((open_time, close_time));
    }

    if let Some(multiplier) = calendar_timeframe_multiplier(timeframe, 'M') {
        let open_month = bucket.checked_mul(multiplier)?;
        let close_month = open_month.checked_add(multiplier)?;
        return Some((
            calendar_month_start(open_month)?,
            calendar_month_start(close_month)?,
        ));
    }

    let duration_ms = seconds.checked_mul(1000)?;
    let open_time = bucket.checked_mul(duration_ms)?;
    let close_time = bucket.checked_add(1)?.checked_mul(duration_ms)?;
    Some((open_time, close_time))
}

pub(crate) fn calendar_timeframe_close(
    timestamp_ms: i64,
    timeframe: &str,
    seconds: i64,
) -> Option<i64> {
    calendar_timeframe_multiplier(timeframe, 'M')?;
    let bucket = timeframe_change_bucket(timestamp_ms, timeframe, seconds)?;
    timeframe_bucket_bounds(bucket, timeframe, seconds).map(|(_, close)| close)
}

fn calendar_month_start(month: i64) -> Option<i64> {
    let year = i32::try_from(month.div_euclid(12)).ok()?;
    let month = u32::try_from(month.rem_euclid(12).checked_add(1)?).ok()?;
    Some(
        Utc.with_ymd_and_hms(year, month, 1, 0, 0, 0)
            .single()?
            .timestamp_millis(),
    )
}

fn calendar_timeframe_multiplier(timeframe: &str, unit: char) -> Option<i64> {
    let number = timeframe.strip_suffix(unit)?;
    let multiplier = if number.is_empty() {
        1
    } else {
        number.parse::<i64>().ok()?
    };
    (multiplier > 0).then_some(multiplier)
}

pub(crate) fn timeframe_seconds(timeframe: &str) -> Option<i64> {
    if timeframe.is_empty() {
        return timeframe_seconds(DEFAULT_CHART_TIMEFRAME);
    }

    let unit = timeframe
        .chars()
        .last()
        .filter(|ch| ch.is_ascii_alphabetic());
    let number = if unit.is_some() {
        &timeframe[..timeframe.len() - 1]
    } else {
        timeframe
    };
    let multiplier = if number.is_empty() {
        1
    } else {
        number.parse::<i64>().ok()?
    };
    if multiplier <= 0 {
        return None;
    }

    match unit {
        None if (1..=1440).contains(&multiplier) => multiplier.checked_mul(60),
        Some('S') if matches!(multiplier, 1 | 5 | 10 | 15 | 30 | 45) => Some(multiplier),
        Some('D') if (1..=365).contains(&multiplier) => multiplier.checked_mul(86_400),
        Some('W') if (1..=52).contains(&multiplier) => multiplier.checked_mul(604_800),
        Some('M') if (1..=12).contains(&multiplier) => multiplier.checked_mul(2_592_000),
        _ => None,
    }
}

pub(crate) fn normalize_timestamp_parts(
    year: i64,
    month: i64,
    day: i64,
    hour: i64,
    minute: i64,
    second: i64,
) -> Option<DateTime<Utc>> {
    let total_months = year.checked_mul(12)?.checked_add(month.checked_sub(1)?)?;
    let normalized_year = i32::try_from(total_months.div_euclid(12)).ok()?;
    let normalized_month = u32::try_from(total_months.rem_euclid(12) + 1).ok()?;
    let base = Utc
        .with_ymd_and_hms(normalized_year, normalized_month, 1, 0, 0, 0)
        .single()?;
    let day_offset = day.checked_sub(1)?.checked_mul(86_400)?;
    let hour_offset = hour.checked_mul(3_600)?;
    let minute_offset = minute.checked_mul(60)?;
    let total_seconds = day_offset
        .checked_add(hour_offset)?
        .checked_add(minute_offset)?
        .checked_add(second)?;
    let offset = Duration::try_seconds(total_seconds)?;
    base.checked_add_signed(offset)
}

pub(crate) fn utc_datetime_from_millis(timestamp: i64) -> Result<DateTime<Utc>, RuntimeError> {
    Utc.timestamp_millis_opt(timestamp)
        .single()
        .ok_or_else(|| RuntimeError {
            message: format!("timestamp is out of range: {timestamp}"),
        })
}

struct BarTimeFunctionArgs {
    timeframe: String,
    session: Option<String>,
    timezone: String,
    bars_back: i64,
    timeframe_bars_back: i64,
}

impl Default for BarTimeFunctionArgs {
    fn default() -> Self {
        Self {
            timeframe: String::new(),
            session: None,
            timezone: "UTC".to_owned(),
            bars_back: 0,
            timeframe_bars_back: 0,
        }
    }
}

#[derive(Default)]
struct TimestampArgs {
    date_string: Option<String>,
    timezone: Option<String>,
    year: Option<i64>,
    month: Option<i64>,
    day: Option<i64>,
    hour: i64,
    minute: i64,
    second: i64,
}

impl<'a> HistoricalRuntime<'a> {
    pub(crate) fn eval_time_call(
        &mut self,
        callee: &str,
        args: &[HirCallArg],
    ) -> Option<Result<PineValue, RuntimeError>> {
        Some(match callee {
            "year" => self.eval_time_component(args, TimeComponent::Year),
            "month" => self.eval_time_component(args, TimeComponent::Month),
            "weekofyear" => self.eval_time_component(args, TimeComponent::WeekOfYear),
            "dayofmonth" => self.eval_time_component(args, TimeComponent::DayOfMonth),
            "dayofweek" => self.eval_time_component(args, TimeComponent::DayOfWeek),
            "hour" => self.eval_time_component(args, TimeComponent::Hour),
            "minute" => self.eval_time_component(args, TimeComponent::Minute),
            "second" => self.eval_time_component(args, TimeComponent::Second),
            "timestamp" => self.eval_timestamp(args),
            "time" => self.eval_bar_time_function(args, false),
            "time_close" => self.eval_bar_time_function(args, true),
            "timeframe.in_seconds" => self.eval_timeframe_in_seconds(args),
            "timeframe.from_seconds" => self.eval_timeframe_from_seconds(args),
            "timeframe.change" => self.eval_timeframe_change(args),
            _ => return None,
        })
    }

    pub(crate) fn eval_timestamp(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let Some(args) = self.eval_timestamp_args(args)? else {
            return Ok(PineValue::Na);
        };
        if let Some(date_string) = args.date_string {
            return parse_timestamp_date_string(&date_string)
                .map(PineValue::Int)
                .map_err(|message| RuntimeError { message });
        }
        let timezone = args.timezone.unwrap_or_else(|| "UTC".to_owned());
        let timezone = parse_numeric_timestamp_timezone(&timezone).ok_or_else(|| RuntimeError {
            message: format!("timestamp unsupported timezone `{timezone}`"),
        })?;
        let (Some(year), Some(month), Some(day)) = (args.year, args.month, args.day) else {
            return Ok(PineValue::Na);
        };

        let Some(datetime) =
            normalize_timestamp_parts(year, month, day, args.hour, args.minute, args.second)
        else {
            return Err(RuntimeError {
                message: format!(
                    "timestamp invalid UTC datetime: {year:04}-{month:02}-{day:02} {hour:02}:{minute:02}:{second:02}",
                    hour = args.hour,
                    minute = args.minute,
                    second = args.second
                ),
            });
        };
        let Some(timestamp) = numeric_timestamp_millis(timezone, datetime) else {
            return Err(RuntimeError {
                message: format!(
                    "timestamp invalid UTC datetime: {year:04}-{month:02}-{day:02} {hour:02}:{minute:02}:{second:02}",
                    hour = args.hour,
                    minute = args.minute,
                    second = args.second
                ),
            });
        };
        Ok(PineValue::Int(timestamp))
    }

    fn eval_timestamp_args(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<Option<TimestampArgs>, RuntimeError> {
        let mut parsed = TimestampArgs::default();
        let mut positional = Vec::new();
        for arg in args {
            if let Some(name) = arg.name.as_deref() {
                match name {
                    "dateString" => {
                        let Some(value) = self.eval_time_function_string_arg(arg)? else {
                            return Ok(None);
                        };
                        parsed.date_string = Some(value);
                    }
                    "timezone" => {
                        let Some(value) = self.eval_time_function_string_arg(arg)? else {
                            return Ok(None);
                        };
                        parsed.timezone = Some(value);
                    }
                    "year" => parsed.year = self.eval_timestamp_int_arg(arg)?,
                    "month" => parsed.month = self.eval_timestamp_int_arg(arg)?,
                    "day" => parsed.day = self.eval_timestamp_int_arg(arg)?,
                    "hour" => {
                        let Some(value) = self.eval_timestamp_int_arg(arg)? else {
                            return Ok(None);
                        };
                        parsed.hour = value;
                    }
                    "minute" => {
                        let Some(value) = self.eval_timestamp_int_arg(arg)? else {
                            return Ok(None);
                        };
                        parsed.minute = value;
                    }
                    "second" => {
                        let Some(value) = self.eval_timestamp_int_arg(arg)? else {
                            return Ok(None);
                        };
                        parsed.second = value;
                    }
                    _ => {}
                }
            } else {
                positional.push(arg);
            }
        }

        let mut offset = 0;
        if let Some(arg) = positional.first() {
            match self.eval_expr(&arg.value)? {
                PineValue::String(value) => {
                    if positional.len() == 1 && parsed.year.is_none() && parsed.month.is_none() {
                        parsed.date_string = Some(value);
                        offset = 1;
                    } else {
                        parsed.timezone = Some(value);
                        offset = 1;
                    }
                }
                PineValue::Na => return Ok(None),
                PineValue::Int(value) => parsed.year = Some(value),
                _ => return Ok(None),
            }
        }

        for (index, arg) in positional.iter().enumerate().skip(offset) {
            let Some(value) = self.eval_timestamp_int_arg(arg)? else {
                return Ok(None);
            };
            match index - offset {
                0 => parsed.year = Some(value),
                1 => parsed.month = Some(value),
                2 => parsed.day = Some(value),
                3 => parsed.hour = value,
                4 => parsed.minute = value,
                5 => parsed.second = value,
                _ => {}
            }
        }

        Ok(Some(parsed))
    }

    pub(crate) fn eval_bar_time_function(
        &mut self,
        args: &[HirCallArg],
        close_time: bool,
    ) -> Result<PineValue, RuntimeError> {
        let name = if close_time { "time_close" } else { "time" };
        let Some(args) = self.eval_bar_time_function_args(args)? else {
            return Ok(PineValue::Na);
        };
        if args.bars_back < -500 {
            return Err(RuntimeError {
                message: format!("{name} bars_back cannot reference more than 500 future bars"),
            });
        }
        if args.timeframe_bars_back < -500 {
            return Err(RuntimeError {
                message: format!(
                    "{name} timeframe_bars_back cannot reference more than 500 future bars"
                ),
            });
        }
        let timezone = parse_time_session_timezone(&args.timezone).ok_or_else(|| RuntimeError {
            message: format!("{name} unsupported timezone `{}`", args.timezone),
        })?;
        let session = match args.session.as_deref() {
            Some("") | None => None,
            Some(session) => Some(
                parse_time_session(
                    session,
                    if self
                        .program
                        .language_version
                        .is_some_and(|version| version <= 4)
                    {
                        DefaultSessionDays::Weekdays
                    } else {
                        DefaultSessionDays::All
                    },
                )
                .ok_or_else(|| RuntimeError {
                    message: format!("{name} unsupported session `{session}`"),
                })?,
            ),
        };
        let timeframe = if args.timeframe.is_empty() {
            DEFAULT_CHART_TIMEFRAME
        } else {
            args.timeframe.trim()
        };
        let Some(seconds) = timeframe_seconds(timeframe) else {
            return Err(RuntimeError {
                message: format!("{name} unsupported timeframe `{timeframe}`"),
            });
        };
        let Some(chart_seconds) = timeframe_seconds(DEFAULT_CHART_TIMEFRAME) else {
            return Err(RuntimeError {
                message: format!("unsupported default chart timeframe `{DEFAULT_CHART_TIMEFRAME}`"),
            });
        };
        if seconds < chart_seconds {
            return Err(RuntimeError {
                message: format!("{name} unsupported lower timeframe `{timeframe}`"),
            });
        }
        if session.is_none()
            && seconds == chart_seconds
            && args.bars_back == 0
            && args.timeframe_bars_back == 0
        {
            return Ok(self
                .current_builtin_i64(name)
                .map(PineValue::Int)
                .unwrap_or(PineValue::Na));
        }

        let Some(current_time) = self.current_builtin_i64("time") else {
            return Ok(PineValue::Na);
        };
        let Some(chart_duration_ms) = chart_seconds.checked_mul(1000) else {
            return Err(RuntimeError {
                message: format!("{name} unsupported timeframe `{timeframe}`"),
            });
        };
        let Some(offset_ms) = args.bars_back.checked_mul(chart_duration_ms) else {
            return Err(RuntimeError {
                message: format!("{name} bars_back timestamp is out of range"),
            });
        };
        let Some(base_time) = current_time.checked_sub(offset_ms) else {
            return Err(RuntimeError {
                message: format!("{name} bars_back timestamp is out of range"),
            });
        };
        let Some(bucket) = timeframe_change_bucket(base_time, timeframe, seconds) else {
            return Err(RuntimeError {
                message: format!("{name} unsupported timeframe `{timeframe}`"),
            });
        };
        let Some(bucket) = bucket.checked_sub(args.timeframe_bars_back) else {
            return Err(RuntimeError {
                message: format!("{name} timeframe_bars_back timestamp is out of range"),
            });
        };
        let Some((open_time, close_timestamp)) =
            timeframe_bucket_bounds(bucket, timeframe, seconds)
        else {
            return Err(RuntimeError {
                message: format!("{name} timestamp is out of range for timeframe `{timeframe}`"),
            });
        };
        if let Some(session) = session {
            let Some(session_close) =
                session_close_for_bar_open(open_time, close_timestamp, &session, timezone)?
            else {
                return Ok(PineValue::Na);
            };
            return Ok(PineValue::Int(if close_time {
                session_close
            } else {
                open_time
            }));
        }

        Ok(PineValue::Int(if close_time {
            close_timestamp
        } else {
            open_time
        }))
    }

    fn eval_bar_time_function_args(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<Option<BarTimeFunctionArgs>, RuntimeError> {
        let mut parsed = BarTimeFunctionArgs::default();
        let mut positional = Vec::new();
        let mut saw_timeframe = false;
        for arg in args {
            if let Some(name) = arg.name.as_deref() {
                match name {
                    "timeframe" => {
                        let Some(value) = self.eval_time_function_string_arg(arg)? else {
                            return Ok(None);
                        };
                        parsed.timeframe = value;
                        saw_timeframe = true;
                    }
                    "session" => {
                        let Some(value) = self.eval_time_function_string_arg(arg)? else {
                            return Ok(None);
                        };
                        parsed.session = Some(value);
                    }
                    "timezone" => {
                        let Some(value) = self.eval_time_function_string_arg(arg)? else {
                            return Ok(None);
                        };
                        parsed.timezone = value;
                    }
                    "bars_back" => {
                        let Some(value) = self.eval_time_function_int_arg(arg)? else {
                            return Ok(None);
                        };
                        parsed.bars_back = value;
                    }
                    "timeframe_bars_back" => {
                        let Some(value) = self.eval_time_function_int_arg(arg)? else {
                            return Ok(None);
                        };
                        parsed.timeframe_bars_back = value;
                    }
                    _ => {}
                }
            } else {
                positional.push(arg);
            }
        }

        if let Some(timeframe_arg) = positional.first() {
            let Some(timeframe) = self.eval_time_function_string_arg(timeframe_arg)? else {
                return Ok(None);
            };
            parsed.timeframe = timeframe;
            saw_timeframe = true;
        }
        if !saw_timeframe {
            return Ok(None);
        }

        let mut second_is_bars_back = false;
        let mut third_is_timezone = false;
        if let Some(arg) = positional.get(1) {
            match self.eval_expr(&arg.value)? {
                PineValue::String(value) => parsed.session = Some(value),
                PineValue::Int(value) => {
                    parsed.bars_back = value;
                    second_is_bars_back = true;
                }
                PineValue::Na => return Ok(None),
                _ => return Ok(None),
            }
        }
        if let Some(arg) = positional.get(2) {
            if second_is_bars_back {
                let Some(value) = self.eval_time_function_int_arg(arg)? else {
                    return Ok(None);
                };
                parsed.timeframe_bars_back = value;
            } else {
                match self.eval_expr(&arg.value)? {
                    PineValue::String(value) => {
                        parsed.timezone = value;
                        third_is_timezone = true;
                    }
                    PineValue::Int(value) => parsed.bars_back = value,
                    PineValue::Na => return Ok(None),
                    _ => return Ok(None),
                }
            }
        }
        if let Some(arg) = positional.get(3) {
            let Some(value) = self.eval_time_function_int_arg(arg)? else {
                return Ok(None);
            };
            if third_is_timezone {
                parsed.bars_back = value;
            } else {
                parsed.timeframe_bars_back = value;
            }
        }
        if let Some(arg) = positional.get(4) {
            let Some(value) = self.eval_time_function_int_arg(arg)? else {
                return Ok(None);
            };
            parsed.timeframe_bars_back = value;
        }

        Ok(Some(parsed))
    }

    fn eval_time_function_string_arg(
        &mut self,
        arg: &HirCallArg,
    ) -> Result<Option<String>, RuntimeError> {
        Ok(match self.eval_expr(&arg.value)? {
            PineValue::String(value) => Some(value),
            PineValue::Na => None,
            _ => None,
        })
    }

    fn eval_time_function_int_arg(
        &mut self,
        arg: &HirCallArg,
    ) -> Result<Option<i64>, RuntimeError> {
        Ok(match self.eval_expr(&arg.value)? {
            PineValue::Int(value) => Some(value),
            PineValue::Na => None,
            _ => None,
        })
    }

    fn eval_timestamp_int_arg(&mut self, arg: &HirCallArg) -> Result<Option<i64>, RuntimeError> {
        Ok(match self.eval_expr(&arg.value)? {
            PineValue::Int(value) => Some(value),
            PineValue::Na => None,
            _ => None,
        })
    }

    pub(crate) fn eval_timeframe_in_seconds(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let timeframe = if let Some(arg) = args.first() {
            match self.eval_expr(&arg.value)? {
                PineValue::String(value) => value,
                PineValue::Na => return Ok(PineValue::Na),
                _ => return Ok(PineValue::Na),
            }
        } else {
            DEFAULT_CHART_TIMEFRAME.to_owned()
        };
        let timeframe = if timeframe.is_empty() {
            DEFAULT_CHART_TIMEFRAME
        } else {
            timeframe.trim()
        };
        let Some(seconds) = timeframe_seconds(timeframe) else {
            return Err(RuntimeError {
                message: format!("timeframe.in_seconds unsupported timeframe `{timeframe}`"),
            });
        };

        Ok(PineValue::Int(seconds))
    }

    pub(crate) fn eval_timeframe_from_seconds(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let Some(arg) = args.first() else {
            return Ok(PineValue::Na);
        };
        let seconds = match self.eval_expr(&arg.value)? {
            PineValue::Int(value) => value,
            PineValue::Na => return Ok(PineValue::Na),
            _ => return Ok(PineValue::Na),
        };
        let Some(timeframe) = timeframe_from_seconds(seconds) else {
            return Err(RuntimeError {
                message: format!("timeframe.from_seconds unsupported seconds `{seconds}`"),
            });
        };

        Ok(PineValue::String(timeframe))
    }

    pub(crate) fn eval_timeframe_change(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let Some(arg) = args.first() else {
            return Ok(PineValue::Na);
        };
        let timeframe = match self.eval_expr(&arg.value)? {
            PineValue::String(value) => value,
            PineValue::Na => return Ok(PineValue::Na),
            _ => return Ok(PineValue::Na),
        };
        let timeframe = if timeframe.is_empty() {
            DEFAULT_CHART_TIMEFRAME
        } else {
            timeframe.trim()
        };
        let Some(seconds) = timeframe_seconds(timeframe) else {
            return Err(RuntimeError {
                message: format!("timeframe.change unsupported timeframe `{timeframe}`"),
            });
        };
        let Some(current_time) = self.current_builtin_i64("time") else {
            return Ok(PineValue::Na);
        };
        let Some(previous_time) = self.previous_bar_time else {
            return Ok(PineValue::Bool(true));
        };
        let Some(current_bucket) = timeframe_change_bucket(current_time, timeframe, seconds) else {
            return Err(RuntimeError {
                message: format!("timeframe.change unsupported timeframe `{timeframe}`"),
            });
        };
        let Some(previous_bucket) = timeframe_change_bucket(previous_time, timeframe, seconds)
        else {
            return Err(RuntimeError {
                message: format!("timeframe.change unsupported timeframe `{timeframe}`"),
            });
        };

        Ok(PineValue::Bool(current_bucket != previous_bucket))
    }
}
