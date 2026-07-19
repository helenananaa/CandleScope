use chrono::{DateTime, Datelike, Duration, LocalResult, Offset, TimeZone, Timelike, Utc};
use chrono_tz::Tz;

use crate::RuntimeError;

use super::{dayofweek_value, parse_fixed_timezone_offset, utc_datetime_from_millis};

pub(super) struct TimeSession {
    periods: Vec<TimeSessionPeriod>,
    days: [bool; 8],
}

struct TimeSessionPeriod {
    start_minute: i64,
    end_minute: i64,
}

#[derive(Clone, Copy)]
pub(super) enum TimeSessionTimezone {
    Fixed(i32),
    Iana(Tz),
}

pub(super) fn parse_time_session_timezone(timezone: &str) -> Option<TimeSessionTimezone> {
    if let Some(offset) = parse_fixed_timezone_offset(timezone) {
        return Some(TimeSessionTimezone::Fixed(offset));
    }
    Some(TimeSessionTimezone::Iana(timezone.trim().parse().ok()?))
}

impl TimeSessionTimezone {
    fn offset_seconds_at(self, datetime: &DateTime<Utc>) -> i32 {
        match self {
            Self::Fixed(offset) => offset,
            Self::Iana(timezone) => timezone
                .offset_from_utc_datetime(&datetime.naive_utc())
                .fix()
                .local_minus_utc(),
        }
    }

    fn close_utc_millis(self, local_close_time: i64) -> Result<i64, RuntimeError> {
        match self {
            Self::Fixed(offset) => {
                local_close_time
                    .checked_sub(i64::from(offset).checked_mul(1000).ok_or_else(|| {
                        RuntimeError {
                            message: "time session timestamp is out of range".to_owned(),
                        }
                    })?)
                    .ok_or_else(|| RuntimeError {
                        message: "time session timestamp is out of range".to_owned(),
                    })
            }
            Self::Iana(timezone) => {
                let local_close = utc_datetime_from_millis(local_close_time)?.naive_utc();
                resolve_iana_session_close(timezone, local_close).ok_or_else(|| RuntimeError {
                    message: "time session timestamp is out of range".to_owned(),
                })
            }
        }
    }
}

pub(super) fn parse_time_session(session: &str) -> Option<TimeSession> {
    if session == "24x7" {
        return Some(TimeSession {
            periods: vec![TimeSessionPeriod {
                start_minute: 0,
                end_minute: 0,
            }],
            days: all_session_days(),
        });
    }

    let (periods, days) = match session.split_once(':') {
        Some((periods, days)) => (periods, parse_session_days(days)?),
        None => (session, all_session_days()),
    };
    if periods.is_empty() {
        return None;
    }
    let periods = periods
        .split(',')
        .map(parse_session_period)
        .collect::<Option<Vec<_>>>()?;
    if periods.is_empty() {
        return None;
    }

    Some(TimeSession { periods, days })
}

pub(super) fn session_close_for_bar_open(
    open_time: i64,
    default_close: i64,
    session: &TimeSession,
    timezone: TimeSessionTimezone,
) -> Result<Option<i64>, RuntimeError> {
    let open_datetime = utc_datetime_from_millis(open_time)?;
    let timezone_offset_seconds = timezone.offset_seconds_at(&open_datetime);
    let timezone_offset_ms = i64::from(timezone_offset_seconds)
        .checked_mul(1000)
        .ok_or_else(|| RuntimeError {
            message: "time session timestamp is out of range".to_owned(),
        })?;
    let local_open_time =
        open_time
            .checked_add(timezone_offset_ms)
            .ok_or_else(|| RuntimeError {
                message: "time session timestamp is out of range".to_owned(),
            })?;
    let datetime = utc_datetime_from_millis(local_open_time)?;
    let minute = i64::from(datetime.hour()) * 60 + i64::from(datetime.minute());
    let day = dayofweek_value(datetime) as usize;
    let midnight = utc_midnight_millis(datetime)?;

    for period in &session.periods {
        let Some(local_close_time) =
            session_period_close_for_open(minute, day, midnight, period, &session.days)?
        else {
            continue;
        };
        let close_time = timezone.close_utc_millis(local_close_time)?;
        return Ok(Some(default_close.min(close_time)));
    }

    Ok(None)
}

fn resolve_iana_session_close(timezone: Tz, local_close: chrono::NaiveDateTime) -> Option<i64> {
    const MAX_GAP_MINUTES: i64 = 2 * 24 * 60;

    // A repeated close uses the later instant so the whole repeated wall-clock
    // interval remains in-session. A close inside a forward gap advances to
    // the first valid local minute, matching minute-granularity session input.
    if let Some(timestamp) = resolved_local_timestamp(timezone.from_local_datetime(&local_close)) {
        return Some(timestamp);
    }

    for minutes in 1..=MAX_GAP_MINUTES {
        let shifted = local_close.checked_add_signed(Duration::minutes(minutes))?;
        if let Some(timestamp) = resolved_local_timestamp(timezone.from_local_datetime(&shifted)) {
            return Some(timestamp);
        }
    }
    None
}

fn resolved_local_timestamp(result: LocalResult<DateTime<Tz>>) -> Option<i64> {
    match result {
        LocalResult::Single(datetime) => Some(datetime.timestamp_millis()),
        LocalResult::Ambiguous(first, second) => {
            Some(first.timestamp_millis().max(second.timestamp_millis()))
        }
        LocalResult::None => None,
    }
}

fn all_session_days() -> [bool; 8] {
    [false, true, true, true, true, true, true, true]
}

fn parse_session_days(days: &str) -> Option<[bool; 8]> {
    if days.is_empty() {
        return None;
    }
    let mut parsed = [false; 8];
    for ch in days.chars() {
        let day = ch.to_digit(10)?;
        if !(1..=7).contains(&day) {
            return None;
        }
        parsed[day as usize] = true;
    }
    Some(parsed)
}

fn parse_session_period(period: &str) -> Option<TimeSessionPeriod> {
    let (start, end) = period.split_once('-')?;
    Some(TimeSessionPeriod {
        start_minute: parse_session_hhmm(start)?,
        end_minute: parse_session_hhmm(end)?,
    })
}

fn parse_session_hhmm(value: &str) -> Option<i64> {
    if value.len() != 4 || !value.chars().all(|ch| ch.is_ascii_digit()) {
        return None;
    }
    let hour = value[..2].parse::<i64>().ok()?;
    let minute = value[2..].parse::<i64>().ok()?;
    if !(0..=23).contains(&hour) || !(0..=59).contains(&minute) {
        return None;
    }
    Some(hour * 60 + minute)
}

fn session_period_close_for_open(
    minute: i64,
    day: usize,
    midnight: i64,
    period: &TimeSessionPeriod,
    days: &[bool; 8],
) -> Result<Option<i64>, RuntimeError> {
    const DAY_MS: i64 = 86_400_000;

    if period.start_minute == period.end_minute {
        if days[day] {
            return Ok(Some(midnight.checked_add(DAY_MS).ok_or_else(|| {
                RuntimeError {
                    message: "time session timestamp is out of range".to_owned(),
                }
            })?));
        }
        return Ok(None);
    }

    if period.start_minute < period.end_minute {
        if days[day] && minute >= period.start_minute && minute < period.end_minute {
            return Ok(Some(session_end_timestamp(midnight, period.end_minute)?));
        }
        return Ok(None);
    }

    if minute >= period.start_minute {
        let session_day = if day == 7 { 1 } else { day + 1 };
        if !days[session_day] {
            return Ok(None);
        }
        let next_midnight = midnight.checked_add(DAY_MS).ok_or_else(|| RuntimeError {
            message: "time session timestamp is out of range".to_owned(),
        })?;
        return Ok(Some(session_end_timestamp(
            next_midnight,
            period.end_minute,
        )?));
    }

    if minute < period.end_minute && days[day] {
        return Ok(Some(session_end_timestamp(midnight, period.end_minute)?));
    }

    Ok(None)
}

fn session_end_timestamp(midnight: i64, end_minute: i64) -> Result<i64, RuntimeError> {
    midnight
        .checked_add(end_minute.checked_mul(60_000).ok_or_else(|| RuntimeError {
            message: "time session timestamp is out of range".to_owned(),
        })?)
        .ok_or_else(|| RuntimeError {
            message: "time session timestamp is out of range".to_owned(),
        })
}

fn utc_midnight_millis(datetime: DateTime<Utc>) -> Result<i64, RuntimeError> {
    let Some(midnight) = Utc
        .with_ymd_and_hms(datetime.year(), datetime.month(), datetime.day(), 0, 0, 0)
        .single()
    else {
        return Err(RuntimeError {
            message: "time session timestamp is out of range".to_owned(),
        });
    };
    Ok(midnight.timestamp_millis())
}
