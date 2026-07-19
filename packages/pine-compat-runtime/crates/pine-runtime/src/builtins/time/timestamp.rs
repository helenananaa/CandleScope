use chrono::{DateTime, Duration, LocalResult, NaiveDate, Offset, TimeZone, Utc};
use chrono_tz::Tz;

use super::is_supported_utc_timezone;

#[derive(Clone, Copy)]
pub(super) enum NumericTimestampTimezone {
    Fixed(i32),
    Iana(Tz),
}

pub(super) fn parse_numeric_timestamp_timezone(timezone: &str) -> Option<NumericTimestampTimezone> {
    if let Some(offset) = parse_fixed_timezone_offset(timezone) {
        return Some(NumericTimestampTimezone::Fixed(offset));
    }
    Some(NumericTimestampTimezone::Iana(
        timezone.trim().parse().ok()?,
    ))
}

pub(super) fn numeric_timestamp_millis(
    timezone: NumericTimestampTimezone,
    local_datetime: DateTime<Utc>,
) -> Option<i64> {
    match timezone {
        NumericTimestampTimezone::Fixed(offset) => local_datetime
            .checked_sub_signed(Duration::try_seconds(i64::from(offset))?)
            .map(|datetime| datetime.timestamp_millis()),
        NumericTimestampTimezone::Iana(timezone) => {
            resolve_iana_numeric_timestamp(timezone, local_datetime.naive_utc())
        }
    }
}

fn resolve_iana_numeric_timestamp(timezone: Tz, local: chrono::NaiveDateTime) -> Option<i64> {
    const MAX_GAP_MINUTES: i64 = 2 * 24 * 60;

    // Use compatible local-time resolution: overlaps select the earlier
    // absolute instant, while gaps shift the input forward by the offset jump.
    match timezone.from_local_datetime(&local) {
        LocalResult::Single(datetime) => return Some(datetime.timestamp_millis()),
        LocalResult::Ambiguous(first, second) => {
            return Some(first.timestamp_millis().min(second.timestamp_millis()));
        }
        LocalResult::None => {}
    }

    let before_offset = nearest_iana_offset(timezone, local, -1, MAX_GAP_MINUTES)?;
    let after_offset = nearest_iana_offset(timezone, local, 1, MAX_GAP_MINUTES)?;
    let gap_seconds = after_offset.checked_sub(before_offset)?;
    if gap_seconds <= 0 {
        return None;
    }
    let shifted = local.checked_add_signed(Duration::seconds(i64::from(gap_seconds)))?;
    match timezone.from_local_datetime(&shifted) {
        LocalResult::Single(datetime) => Some(datetime.timestamp_millis()),
        LocalResult::Ambiguous(first, second) => {
            Some(first.timestamp_millis().min(second.timestamp_millis()))
        }
        LocalResult::None => None,
    }
}

fn nearest_iana_offset(
    timezone: Tz,
    local: chrono::NaiveDateTime,
    direction: i64,
    max_minutes: i64,
) -> Option<i32> {
    for minutes in 1..=max_minutes {
        let delta = Duration::minutes(direction.checked_mul(minutes)?);
        let candidate = local.checked_add_signed(delta)?;
        match timezone.from_local_datetime(&candidate) {
            LocalResult::Single(datetime) => {
                return Some(datetime.offset().fix().local_minus_utc());
            }
            LocalResult::Ambiguous(first, second) => {
                let first = first.offset().fix().local_minus_utc();
                let second = second.offset().fix().local_minus_utc();
                return Some(if direction < 0 {
                    first.max(second)
                } else {
                    first.min(second)
                });
            }
            LocalResult::None => {}
        }
    }
    None
}

pub(super) fn parse_timestamp_date_string(date_string: &str) -> Result<i64, String> {
    let value = date_string.trim();
    if value.is_empty() {
        return Err("timestamp unsupported dateString ``".to_owned());
    }

    let tokens: Vec<&str> = value.split_whitespace().collect();
    let (year, month, day, next_index) = parse_timestamp_date_tokens(&tokens, value)?;
    let (hour, minute, second, next_index) = match tokens.get(next_index) {
        Some(token) if token.contains(':') => {
            let (hour, minute, second) = parse_timestamp_time_token(token, value)?;
            (hour, minute, second, next_index + 1)
        }
        _ => (0, 0, 0, next_index),
    };
    let timezone = match tokens.get(next_index) {
        Some(timezone) => parse_numeric_timestamp_timezone(timezone)
            .ok_or_else(|| format!("timestamp unsupported dateString `{value}`"))?,
        None => NumericTimestampTimezone::Fixed(0),
    };
    if tokens.len() > next_index + usize::from(tokens.get(next_index).is_some()) {
        return Err(format!("timestamp unsupported dateString `{date_string}`"));
    }

    let Some(date) = NaiveDate::from_ymd_opt(year, month, day) else {
        return Err(format!("timestamp invalid dateString `{date_string}`"));
    };
    let Some(datetime) = date.and_hms_opt(hour, minute, second) else {
        return Err(format!("timestamp invalid dateString `{date_string}`"));
    };
    numeric_timestamp_millis(timezone, Utc.from_utc_datetime(&datetime))
        .ok_or_else(|| format!("timestamp invalid dateString `{date_string}`"))
}

fn parse_timestamp_date_tokens(
    tokens: &[&str],
    original: &str,
) -> Result<(i32, u32, u32, usize), String> {
    let Some(first) = tokens.first() else {
        return Err(format!("timestamp unsupported dateString `{original}`"));
    };
    if let Some((year, month, day)) = parse_iso_date_token(first) {
        return Ok((year, month, day, 1));
    }
    if tokens.len() < 3 {
        return Err(format!("timestamp unsupported dateString `{original}`"));
    }
    let day = tokens[0]
        .parse::<u32>()
        .map_err(|_| format!("timestamp unsupported dateString `{original}`"))?;
    let month = parse_english_month(tokens[1])
        .ok_or_else(|| format!("timestamp unsupported dateString `{original}`"))?;
    let year = tokens[2]
        .parse::<i32>()
        .map_err(|_| format!("timestamp unsupported dateString `{original}`"))?;
    Ok((year, month, day, 3))
}

fn parse_iso_date_token(token: &str) -> Option<(i32, u32, u32)> {
    let mut parts = token.split('-');
    let year = parts.next()?.parse::<i32>().ok()?;
    let month = parts.next()?.parse::<u32>().ok()?;
    let day = parts.next()?.parse::<u32>().ok()?;
    parts.next().is_none().then_some((year, month, day))
}

fn parse_english_month(month: &str) -> Option<u32> {
    match month.to_ascii_lowercase().as_str() {
        "jan" | "january" => Some(1),
        "feb" | "february" => Some(2),
        "mar" | "march" => Some(3),
        "apr" | "april" => Some(4),
        "may" => Some(5),
        "jun" | "june" => Some(6),
        "jul" | "july" => Some(7),
        "aug" | "august" => Some(8),
        "sep" | "sept" | "september" => Some(9),
        "oct" | "october" => Some(10),
        "nov" | "november" => Some(11),
        "dec" | "december" => Some(12),
        _ => None,
    }
}

fn parse_timestamp_time_token(token: &str, original: &str) -> Result<(u32, u32, u32), String> {
    let parts: Vec<&str> = token.split(':').collect();
    if !(2..=3).contains(&parts.len()) {
        return Err(format!("timestamp unsupported dateString `{original}`"));
    }
    let hour = parts[0]
        .parse::<u32>()
        .map_err(|_| format!("timestamp unsupported dateString `{original}`"))?;
    let minute = parts[1]
        .parse::<u32>()
        .map_err(|_| format!("timestamp unsupported dateString `{original}`"))?;
    let second = parts
        .get(2)
        .map_or(Ok(0), |value| value.parse::<u32>())
        .map_err(|_| format!("timestamp unsupported dateString `{original}`"))?;
    Ok((hour, minute, second))
}

pub(crate) fn parse_fixed_timezone_offset(timezone: &str) -> Option<i32> {
    let token = timezone.trim();
    if is_supported_utc_timezone(token) {
        return Some(0);
    }
    let offset = token
        .strip_prefix("UTC")
        .or_else(|| token.strip_prefix("GMT"))
        .unwrap_or(token);
    if offset == "0" {
        return Some(0);
    }
    parse_timestamp_numeric_offset(offset)
}

fn parse_timestamp_numeric_offset(offset: &str) -> Option<i32> {
    let sign = match offset.as_bytes().first()? {
        b'+' => 1,
        b'-' => -1,
        _ => return None,
    };
    let body = &offset[1..];
    let (hour, minute) = if let Some((hour, minute)) = body.split_once(':') {
        (hour.parse::<i32>().ok()?, minute.parse::<i32>().ok()?)
    } else if body.len() <= 2 {
        (body.parse::<i32>().ok()?, 0)
    } else if body.len() == 4 {
        (
            body[..2].parse::<i32>().ok()?,
            body[2..].parse::<i32>().ok()?,
        )
    } else {
        return None;
    };
    if !(0..=23).contains(&hour) || !(0..=59).contains(&minute) {
        return None;
    }
    Some(sign * (hour * 3600 + minute * 60))
}

pub(crate) fn format_fixed_timezone_offset(offset_seconds: i32) -> String {
    let sign = if offset_seconds < 0 { '-' } else { '+' };
    let offset_seconds = offset_seconds.abs();
    let hour = offset_seconds / 3600;
    let minute = (offset_seconds % 3600) / 60;
    format!("{sign}{hour:02}{minute:02}")
}
