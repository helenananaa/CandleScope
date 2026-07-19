use chrono::{DateTime, Datelike, Timelike, Utc};

pub(crate) fn format_utc_datetime(datetime: DateTime<Utc>, format: &str) -> String {
    format_datetime_with_offset(datetime, format, "+0000")
}

pub(crate) fn format_datetime_with_offset(
    datetime: DateTime<Utc>,
    format: &str,
    timezone_offset: &str,
) -> String {
    format_datetime_with_timezone(datetime, format, timezone_offset, None)
}

pub(crate) fn format_datetime_with_timezone(
    datetime: DateTime<Utc>,
    format: &str,
    timezone_offset: &str,
    timezone_short_name: Option<&str>,
) -> String {
    let mut result = String::new();
    let mut chars = format.chars().peekable();
    while let Some(ch) = chars.next() {
        if ch == '\'' {
            if chars.peek().copied() == Some('\'') {
                chars.next();
                result.push('\'');
                continue;
            }
            while let Some(literal) = chars.next() {
                if literal == '\'' {
                    if chars.peek().copied() == Some('\'') {
                        chars.next();
                        result.push('\'');
                        continue;
                    }
                    break;
                }
                result.push(literal);
            }
            continue;
        }

        let count = consume_same_chars(&mut chars, ch) + 1;
        match ch {
            'y' | 'Y' => {
                if count == 2 {
                    result.push_str(&format!("{:02}", datetime.year().rem_euclid(100)));
                } else {
                    result.push_str(&format!("{:04}", datetime.year()));
                }
            }
            'M' => result.push_str(&format_month(datetime.month(), count)),
            'd' => push_padded_or_plain(&mut result, datetime.day(), count),
            'D' => push_padded_or_plain(&mut result, datetime.ordinal(), count),
            'E' => result.push_str(format_weekday(datetime.weekday(), count)),
            'w' => push_padded_or_plain(&mut result, datetime.iso_week().week(), count),
            'W' => push_padded_or_plain(&mut result, week_of_month(datetime), count),
            'H' => push_padded_or_plain(&mut result, datetime.hour(), count),
            'h' => {
                let hour = datetime.hour() % 12;
                push_padded_or_plain(&mut result, hour, count);
            }
            'm' => push_padded_or_plain(&mut result, datetime.minute(), count),
            's' => push_padded_or_plain(&mut result, datetime.second(), count),
            'S' => result.push_str(&format_millis(datetime.timestamp_subsec_millis(), count)),
            'a' => result.push_str(if datetime.hour() < 12 { "AM" } else { "PM" }),
            'Z' => result.push_str(timezone_offset),
            'z' if count <= 3 => match timezone_short_name {
                Some(name) => result.push_str(name),
                None => result.extend(std::iter::repeat_n('z', count)),
            },
            other => {
                for _ in 0..count {
                    result.push(other);
                }
            }
        }
    }
    result
}

fn consume_same_chars(chars: &mut std::iter::Peekable<std::str::Chars<'_>>, ch: char) -> usize {
    let mut count = 0;
    while chars.peek().copied() == Some(ch) {
        chars.next();
        count += 1;
    }
    count
}

fn push_padded_or_plain(result: &mut String, value: u32, width: usize) {
    if width >= 2 {
        result.push_str(&format!("{value:0width$}"));
    } else {
        result.push_str(&value.to_string());
    }
}

fn format_month(month: u32, width: usize) -> String {
    const SHORT: [&str; 12] = [
        "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ];
    const LONG: [&str; 12] = [
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ];
    match width {
        1 => month.to_string(),
        2 => format!("{month:02}"),
        3 => SHORT[(month - 1) as usize].to_owned(),
        _ => LONG[(month - 1) as usize].to_owned(),
    }
}

fn week_of_month(datetime: DateTime<Utc>) -> u32 {
    ((datetime.day() - 1) / 7) + 1
}

fn format_weekday(weekday: chrono::Weekday, width: usize) -> &'static str {
    const SHORT: [&str; 7] = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
    const LONG: [&str; 7] = [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    ];
    let index = weekday.num_days_from_monday() as usize;
    if width >= 4 {
        LONG[index]
    } else {
        SHORT[index]
    }
}

fn format_millis(millis: u32, width: usize) -> String {
    match width {
        1 => millis.to_string(),
        2 => format!("{millis:02}"),
        _ => format!("{millis:03}"),
    }
}
