use pine_syntax::SourceFile;

use super::*;

#[test]
fn runs_utc_time_component_variables() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("time components")
plot(year)
plot(month)
plot(weekofyear)
plot(dayofmonth)
plot(dayofweek)
plot(hour)
plot(minute)
plot(second)
plot(time_tradingday)
ts = 1612235045000
made_ts = timestamp(2021, 2, 2, 3, 4, 5)
date_ts = timestamp(2021, 1, 1)
made_ts_utc = timestamp("UTC0", 2021, 2, 2, 3, 4, 5)
made_ts_named = timestamp(timezone = "Etc/UTC", year = 2021, month = 2, day = 2, hour = 3, minute = 4, second = 5)
date_ts_named = timestamp(year = 2021, month = 1, day = 1)
previous_month_zero_ts = timestamp(2021, 0, 1)
previous_month_negative_ts = timestamp(2021, -1, 1)
future_month_overflow_ts = timestamp(2021, 14, 2, 3, 4, 5)
day_overflow_ts = timestamp(2021, 2, 30)
day_zero_ts = timestamp(2021, 1, 0)
hour_overflow_ts = timestamp(2021, 1, 1, 24)
minute_second_overflow_ts = timestamp(2021, 1, 1, 0, 61, 1)
negative_time_ts = timestamp(2021, 1, 1, -1, -1, -1)
fixed_offset_east_ts = timestamp("UTC+4", 2021, 1, 1)
fixed_offset_west_ts = timestamp("GMT-5", 2021, 1, 1)
numeric_offset_ts = timestamp("+05:30", 2021, 1, 1)
date_ts_string = timestamp("2021-01-01")
month_ts_string = timestamp("29 Aug 2024")
named_month_ts_string = timestamp(dateString = "29 Aug 2024")
utc_ts_string = timestamp("20 Aug 2024 00:00:00 UTC+0")
offset_ts_string = timestamp("1 May 2022 00:00 -0400")
plot(year(ts))
plot(month(ts, "UTC"))
plot(weekofyear(ts))
plot(dayofmonth(ts))
plot(dayofweek(ts))
plot(hour(ts))
plot(minute(ts))
plot(second(ts))
plot(dayofweek == dayofweek.friday ? 1 : 0)
plot(dayofweek(ts) == dayofweek.tuesday ? 1 : 0)
plot(na(year(na)) and na(weekofyear(na)) and na(dayofweek(na)) ? 1 : 0)
plot(year(ts, "Etc/UTC") == 2021 and month(ts, "GMT") == 2 and weekofyear(ts, "Z") == 5 and dayofmonth(ts, "+0000") == 2 and dayofweek(ts, "+00:00") == dayofweek.tuesday and hour(ts, na) == 3 and minute(ts, "UTC") == 4 and second(ts, "Etc/UTC") == 5 ? 1 : 0)
plot(year(ts, "UTC+0") == 2021 and month(ts, "GMT+00:00") == 2 and dayofmonth(ts, "-0000") == 2 and hour(ts, "UTC-00:00") == 3 and minute(ts, "GMT-0") == 4 and second(ts, "-00:00") == 5 ? 1 : 0)
plot(year(ts, "UTC+4") == 2021 and month(ts, "UTC+4") == 2 and dayofmonth(ts, "GMT-5") == 1 and dayofweek(ts, "GMT-5") == dayofweek.monday and hour(ts, "UTC+4") == 7 and minute(ts, "+05:30") == 34 and second(ts, "GMT-5") == 5 ? 1 : 0)
plot(made_ts == ts and date_ts == 1609459200000 ? 1 : 0)
plot(made_ts_utc == ts and made_ts_named == ts and date_ts_named == date_ts ? 1 : 0)
plot(previous_month_zero_ts == 1606780800000 and previous_month_negative_ts == 1604188800000 and future_month_overflow_ts == 1643771045000 ? 1 : 0)
plot(day_overflow_ts == 1614643200000 and day_zero_ts == 1609372800000 and hour_overflow_ts == 1609545600000 and minute_second_overflow_ts == 1609462861000 and negative_time_ts == 1609455539000 ? 1 : 0)
plot(fixed_offset_east_ts == 1609444800000 and fixed_offset_west_ts == 1609477200000 and numeric_offset_ts == 1609439400000 ? 1 : 0)
plot(date_ts_string == date_ts and month_ts_string == 1724889600000 and named_month_ts_string == month_ts_string and utc_ts_string == 1724112000000 and offset_ts_string == 1651377600000 ? 1 : 0)
plot(na(timestamp(na, 1, 1)) ? 1 : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        Bar {
            time: 1_609_459_200_000,
            open: 1.0,
            high: 1.0,
            low: 1.0,
            close: 1.0,
            volume: 100.0,
        },
        Bar {
            time: 1_612_235_045_000,
            open: 2.0,
            high: 2.0,
            low: 2.0,
            close: 2.0,
            volume: 100.0,
        },
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_values_close(&result.plots[0].values, &[2021.0, 2021.0]);
    assert_values_close(&result.plots[1].values, &[1.0, 2.0]);
    assert_values_close(&result.plots[2].values, &[53.0, 5.0]);
    assert_values_close(&result.plots[3].values, &[1.0, 2.0]);
    assert_values_close(&result.plots[4].values, &[6.0, 3.0]);
    assert_values_close(&result.plots[5].values, &[0.0, 3.0]);
    assert_values_close(&result.plots[6].values, &[0.0, 4.0]);
    assert_values_close(&result.plots[7].values, &[0.0, 5.0]);
    assert_values_close(
        &result.plots[8].values,
        &[1_609_459_200_000.0, 1_612_224_000_000.0],
    );
    assert_values_close(&result.plots[9].values, &[2021.0, 2021.0]);
    assert_values_close(&result.plots[10].values, &[2.0, 2.0]);
    assert_values_close(&result.plots[11].values, &[5.0, 5.0]);
    assert_values_close(&result.plots[12].values, &[2.0, 2.0]);
    assert_values_close(&result.plots[13].values, &[3.0, 3.0]);
    assert_values_close(&result.plots[14].values, &[3.0, 3.0]);
    assert_values_close(&result.plots[15].values, &[4.0, 4.0]);
    assert_values_close(&result.plots[16].values, &[5.0, 5.0]);
    assert_values_close(&result.plots[17].values, &[1.0, 0.0]);
    assert_values_close(&result.plots[18].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[19].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[20].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[21].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[22].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[23].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[24].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[25].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[26].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[27].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[28].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[29].values, &[1.0, 1.0]);
}

#[test]
fn runs_time_and_time_close_functions_for_timeframes() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("time functions")
plot(time(""))
plot(time(timeframe.period))
plot(time("D"))
plot(time_close(""))
plot(time_close(timeframe.period))
plot(time_close("D"))
plot(na(time(na)) and na(time_close(na)) ? 1 : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        Bar {
            time: 0,
            open: 1.0,
            high: 1.0,
            low: 1.0,
            close: 1.0,
            volume: 1.0,
        },
        Bar {
            time: 60_000,
            open: 2.0,
            high: 2.0,
            low: 2.0,
            close: 2.0,
            volume: 1.0,
        },
        Bar {
            time: 86_460_000,
            open: 3.0,
            high: 3.0,
            low: 3.0,
            close: 3.0,
            volume: 1.0,
        },
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("result");

    assert_values_close(&result.plots[0].values, &[0.0, 60_000.0, 86_460_000.0]);
    assert_values_close(&result.plots[1].values, &[0.0, 60_000.0, 86_460_000.0]);
    assert_values_close(&result.plots[2].values, &[0.0, 0.0, 86_400_000.0]);
    assert_values_close(
        &result.plots[3].values,
        &[60_000.0, 120_000.0, 86_520_000.0],
    );
    assert_values_close(
        &result.plots[4].values,
        &[60_000.0, 120_000.0, 86_520_000.0],
    );
    assert_values_close(
        &result.plots[5].values,
        &[86_400_000.0, 86_400_000.0, 172_800_000.0],
    );
    assert_values_close(&result.plots[6].values, &[1.0, 1.0, 1.0]);
}

#[test]
fn runs_time_and_time_close_for_calendar_timeframes() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("calendar time functions")
plot(time("W"))
plot(time_close("W"))
plot(time("2W"))
plot(time_close("2W"))
plot(time("2W", timeframe_bars_back = 1))
plot(time_close("2W", timeframe_bars_back = -1))
plot(time("M"))
plot(time_close("M"))
plot(time("M", timeframe_bars_back = 1))
plot(time_close("M", timeframe_bars_back = -1))
plot(time("3M"))
plot(time_close("3M"))
plot(time("3M", timeframe_bars_back = 1))
plot(time_close("3M", timeframe_bars_back = -1))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = [Bar {
        time: 1_706_702_400_000,
        open: 1.0,
        high: 1.0,
        low: 1.0,
        close: 1.0,
        volume: 1.0,
    }];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("result");

    assert_values_close(&result.plots[0].values, &[1_706_486_400_000.0]);
    assert_values_close(&result.plots[1].values, &[1_707_091_200_000.0]);
    assert_values_close(&result.plots[2].values, &[1_705_881_600_000.0]);
    assert_values_close(&result.plots[3].values, &[1_707_091_200_000.0]);
    assert_values_close(&result.plots[4].values, &[1_704_672_000_000.0]);
    assert_values_close(&result.plots[5].values, &[1_708_300_800_000.0]);
    assert_values_close(&result.plots[6].values, &[1_704_067_200_000.0]);
    assert_values_close(&result.plots[7].values, &[1_706_745_600_000.0]);
    assert_values_close(&result.plots[8].values, &[1_701_388_800_000.0]);
    assert_values_close(&result.plots[9].values, &[1_709_251_200_000.0]);
    assert_values_close(&result.plots[10].values, &[1_704_067_200_000.0]);
    assert_values_close(&result.plots[11].values, &[1_711_929_600_000.0]);
    assert_values_close(&result.plots[12].values, &[1_696_118_400_000.0]);
    assert_values_close(&result.plots[13].values, &[1_719_792_000_000.0]);
}

#[test]
fn runs_time_and_time_close_functions_with_bars_back() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("time bars back")
plot(time("", bars_back = 1))
plot(time_close("", 1))
plot(time("D", bars_back = 1))
plot(time_close("D", bars_back = -1))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        Bar {
            time: 60_000,
            open: 1.0,
            high: 1.0,
            low: 1.0,
            close: 1.0,
            volume: 1.0,
        },
        Bar {
            time: 86_400_000,
            open: 2.0,
            high: 2.0,
            low: 2.0,
            close: 2.0,
            volume: 1.0,
        },
        Bar {
            time: 86_460_000,
            open: 3.0,
            high: 3.0,
            low: 3.0,
            close: 3.0,
            volume: 1.0,
        },
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("result");

    assert_values_close(&result.plots[0].values, &[0.0, 86_340_000.0, 86_400_000.0]);
    assert_values_close(
        &result.plots[1].values,
        &[60_000.0, 86_400_000.0, 86_460_000.0],
    );
    assert_values_close(&result.plots[2].values, &[0.0, 0.0, 86_400_000.0]);
    assert_values_close(
        &result.plots[3].values,
        &[86_400_000.0, 172_800_000.0, 172_800_000.0],
    );
}

#[test]
fn runs_time_and_time_close_functions_with_timeframe_bars_back() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("time timeframe bars back")
plot(time("D", timeframe_bars_back = 1))
plot(time_close("D", timeframe_bars_back = -1))
plot(time("D", bars_back = 1, timeframe_bars_back = 1))
plot(time_close("D", 1, 1))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        Bar {
            time: 60_000,
            open: 1.0,
            high: 1.0,
            low: 1.0,
            close: 1.0,
            volume: 1.0,
        },
        Bar {
            time: 86_400_000,
            open: 2.0,
            high: 2.0,
            low: 2.0,
            close: 2.0,
            volume: 1.0,
        },
        Bar {
            time: 86_460_000,
            open: 3.0,
            high: 3.0,
            low: 3.0,
            close: 3.0,
            volume: 1.0,
        },
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("result");

    assert_values_close(&result.plots[0].values, &[-86_400_000.0, 0.0, 0.0]);
    assert_values_close(
        &result.plots[1].values,
        &[172_800_000.0, 259_200_000.0, 259_200_000.0],
    );
    assert_values_close(
        &result.plots[2].values,
        &[-86_400_000.0, -86_400_000.0, 0.0],
    );
    assert_values_close(&result.plots[3].values, &[0.0, 0.0, 86_400_000.0]);
}

#[test]
fn runs_time_and_time_close_functions_with_sessions() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("time sessions")
session_open = time("", "0001-0003")
session_close = time_close("", "0001-0003")
session_open_utc = time("", "0001-0003", "UTC")
session_open_fixed_east = time("", "0401-0403", "UTC+4")
session_close_fixed_west = time_close("", "1901-1903", "GMT-5")
session_open_numeric_offset = time("", "0531-0533", "+05:30")
session_previous_open = time("", session = "0001-0003", bars_back = 1)
split_session_close = time_close("", "0001-0002,0003-0004")
plot(na(session_open) ? -1 : session_open / 60000)
plot(na(session_close) ? -1 : session_close / 60000)
plot(not na(time("", "0001-0003:5")) ? 1 : 0)
plot(na(time("", "0001-0003:6")) ? 1 : 0)
plot(na(session_open_utc) ? -1 : session_open_utc / 60000)
plot(na(session_open_fixed_east) ? -1 : session_open_fixed_east / 60000)
plot(na(session_close_fixed_west) ? -1 : session_close_fixed_west / 60000)
plot(na(session_open_numeric_offset) ? -1 : session_open_numeric_offset / 60000)
plot(na(session_previous_open) ? -1 : session_previous_open / 60000)
plot(na(split_session_close) ? -1 : split_session_close / 60000)
plot(time("", "24x7") == time ? 1 : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        Bar {
            time: 0,
            open: 1.0,
            high: 1.0,
            low: 1.0,
            close: 1.0,
            volume: 1.0,
        },
        Bar {
            time: 60_000,
            open: 2.0,
            high: 2.0,
            low: 2.0,
            close: 2.0,
            volume: 1.0,
        },
        Bar {
            time: 120_000,
            open: 3.0,
            high: 3.0,
            low: 3.0,
            close: 3.0,
            volume: 1.0,
        },
        Bar {
            time: 180_000,
            open: 4.0,
            high: 4.0,
            low: 4.0,
            close: 4.0,
            volume: 1.0,
        },
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("result");

    assert_values_close(&result.plots[0].values, &[-1.0, 1.0, 2.0, -1.0]);
    assert_values_close(&result.plots[1].values, &[-1.0, 2.0, 3.0, -1.0]);
    assert_values_close(&result.plots[2].values, &[0.0, 1.0, 1.0, 0.0]);
    assert_values_close(&result.plots[3].values, &[1.0, 1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[4].values, &[-1.0, 1.0, 2.0, -1.0]);
    assert_values_close(&result.plots[5].values, &[-1.0, 1.0, 2.0, -1.0]);
    assert_values_close(&result.plots[6].values, &[-1.0, 2.0, 3.0, -1.0]);
    assert_values_close(&result.plots[7].values, &[-1.0, 1.0, 2.0, -1.0]);
    assert_values_close(&result.plots[8].values, &[-1.0, -1.0, 1.0, 2.0]);
    assert_values_close(&result.plots[9].values, &[-1.0, 2.0, -1.0, 4.0]);
    assert_values_close(&result.plots[10].values, &[1.0, 1.0, 1.0, 1.0]);
}

#[test]
fn runs_time_and_time_close_functions_with_iana_sessions() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("IANA time sessions")
plot(not na(time("", "0700-0702", "America/New_York")) ? 1 : 0)
plot(not na(time("", "0800-0802", "America/New_York")) ? 1 : 0)
plot(not na(time("", "2100-2102", "Asia/Tokyo")) ? 1 : 0)
plot(time_close("60", "0700-0730", "America/New_York") == 1609504200000 ? 1 : 0)
plot(time_close("60", "0800-0830", "America/New_York") == 1625142600000 ? 1 : 0)
plot(time_close("240", "0000-0130", "America/New_York") == 1636266600000 ? 1 : 0)
plot(time_close("60", "0000-0230", "America/New_York") == 1615701600000 ? 1 : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        Bar {
            time: 1_609_502_400_000,
            open: 1.0,
            high: 1.0,
            low: 1.0,
            close: 1.0,
            volume: 1.0,
        },
        Bar {
            time: 1_625_140_800_000,
            open: 2.0,
            high: 2.0,
            low: 2.0,
            close: 2.0,
            volume: 1.0,
        },
        Bar {
            time: 1_636_257_600_000,
            open: 3.0,
            high: 3.0,
            low: 3.0,
            close: 3.0,
            volume: 1.0,
        },
        Bar {
            time: 1_615_698_000_000,
            open: 4.0,
            high: 4.0,
            low: 4.0,
            close: 4.0,
            volume: 1.0,
        },
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("result");

    assert_values_close(&result.plots[0].values, &[1.0, 0.0, 0.0, 0.0]);
    assert_values_close(&result.plots[1].values, &[0.0, 1.0, 0.0, 0.0]);
    assert_values_close(&result.plots[2].values, &[1.0, 1.0, 0.0, 0.0]);
    assert_values_close(&result.plots[3].values, &[1.0, 0.0, 0.0, 0.0]);
    assert_values_close(&result.plots[4].values, &[0.0, 1.0, 0.0, 0.0]);
    assert_values_close(&result.plots[5].values, &[0.0, 0.0, 1.0, 0.0]);
    assert_values_close(&result.plots[6].values, &[0.0, 0.0, 0.0, 1.0]);
}

#[test]
fn runs_timeframe_helpers() {
    let source = SourceFile::new(
        "test.pine",
        r#"//@version=6
indicator("timeframe helpers")
tf = input.timeframe("60", "TF")
plot(timeframe.period == "1" ? 1 : 0)
plot(timeframe.main_period == timeframe.period ? 1 : 0)
plot(timeframe.in_seconds())
plot(timeframe.in_seconds(""))
plot(timeframe.in_seconds("1S"))
plot(timeframe.in_seconds("45S"))
plot(timeframe.in_seconds(tf))
plot(timeframe.in_seconds("D"))
plot(timeframe.in_seconds("1D") == timeframe.in_seconds("D") ? 1 : 0)
plot(timeframe.in_seconds("1W") == timeframe.in_seconds("W") ? 1 : 0)
plot(timeframe.in_seconds("1M") == timeframe.in_seconds("M") ? 1 : 0)
plot(timeframe.in_seconds("2W"))
plot(timeframe.in_seconds("3M"))
plot(timeframe.in_seconds("1440"))
plot(timeframe.in_seconds("365D"))
plot(timeframe.in_seconds("52W"))
plot(timeframe.in_seconds("12M"))
plot(na(timeframe.in_seconds(na)) ? 1 : 0)
plot(timeframe.from_seconds(60) == "1" ? 1 : 0)
plot(timeframe.from_seconds(3600) == "60" ? 1 : 0)
plot(timeframe.from_seconds(timeframe.in_seconds("1440")) == "D" ? 1 : 0)
plot(timeframe.from_seconds(timeframe.in_seconds("7D")) == "W" ? 1 : 0)
plot(timeframe.from_seconds(timeframe.in_seconds("30D")) == "M" ? 1 : 0)
plot(timeframe.from_seconds(timeframe.in_seconds("45S")) == "45S" ? 1 : 0)
plot(timeframe.from_seconds(timeframe.in_seconds("D")) == "D" ? 1 : 0)
plot(timeframe.from_seconds(timeframe.in_seconds("W")) == "W" ? 1 : 0)
plot(timeframe.from_seconds(timeframe.in_seconds("2W")) == "2W" ? 1 : 0)
plot(timeframe.from_seconds(timeframe.in_seconds("M")) == "M" ? 1 : 0)
plot(timeframe.from_seconds(timeframe.in_seconds("3M")) == "3M" ? 1 : 0)
plot(timeframe.from_seconds(timeframe.in_seconds("365D")) == "365D" ? 1 : 0)
plot(timeframe.from_seconds(timeframe.in_seconds("52W")) == "52W" ? 1 : 0)
plot(timeframe.from_seconds(timeframe.in_seconds("12M")) == "12M" ? 1 : 0)
plot(na(timeframe.from_seconds(na)) ? 1 : 0)
plot(timeframe.change("1") ? 1 : 0)
plot(timeframe.change("") ? 1 : 0)
plot(timeframe.change("D") ? 1 : 0)
plot(timeframe.isminutes and timeframe.isintraday and not timeframe.isticks and not timeframe.isseconds and not timeframe.isdaily and not timeframe.isweekly and not timeframe.ismonthly and not timeframe.isdwm ? 1 : 0)
plot(timeframe.multiplier)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result =
        run_historical(&analysis.hir.expect("HIR"), &[bar(1.0), bar(2.0)]).expect("result");

    assert_values_close(&result.plots[0].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[1].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[2].values, &[60.0, 60.0]);
    assert_values_close(&result.plots[3].values, &[60.0, 60.0]);
    assert_values_close(&result.plots[4].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[5].values, &[45.0, 45.0]);
    assert_values_close(&result.plots[6].values, &[3600.0, 3600.0]);
    assert_values_close(&result.plots[7].values, &[86_400.0, 86_400.0]);
    assert_values_close(&result.plots[8].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[9].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[10].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[11].values, &[1_209_600.0, 1_209_600.0]);
    assert_values_close(&result.plots[12].values, &[7_776_000.0, 7_776_000.0]);
    assert_values_close(&result.plots[13].values, &[86_400.0, 86_400.0]);
    assert_values_close(&result.plots[14].values, &[31_536_000.0, 31_536_000.0]);
    assert_values_close(&result.plots[15].values, &[31_449_600.0, 31_449_600.0]);
    assert_values_close(&result.plots[16].values, &[31_104_000.0, 31_104_000.0]);
    assert_values_close(&result.plots[17].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[18].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[19].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[20].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[21].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[22].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[23].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[24].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[25].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[26].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[27].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[28].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[29].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[30].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[31].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[32].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[33].values, &[1.0, 0.0]);
    assert_values_close(&result.plots[34].values, &[1.0, 0.0]);
    assert_values_close(&result.plots[35].values, &[1.0, 0.0]);
    assert_values_close(&result.plots[36].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[37].values, &[1.0, 1.0]);
}

#[test]
fn runs_timeframe_change() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("timeframe change")
plot(timeframe.change("1") ? 1 : 0)
plot(timeframe.change("D") ? 1 : 0)
plot(na(timeframe.change(na)) ? 1 : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        Bar {
            time: 0,
            open: 1.0,
            high: 1.0,
            low: 1.0,
            close: 1.0,
            volume: 1.0,
        },
        Bar {
            time: 30_000,
            open: 2.0,
            high: 2.0,
            low: 2.0,
            close: 2.0,
            volume: 1.0,
        },
        Bar {
            time: 60_000,
            open: 3.0,
            high: 3.0,
            low: 3.0,
            close: 3.0,
            volume: 1.0,
        },
        Bar {
            time: 86_400_000,
            open: 4.0,
            high: 4.0,
            low: 4.0,
            close: 4.0,
            volume: 1.0,
        },
        Bar {
            time: 86_460_000,
            open: 5.0,
            high: 5.0,
            low: 5.0,
            close: 5.0,
            volume: 1.0,
        },
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("result");

    assert_values_close(&result.plots[0].values, &[1.0, 0.0, 1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[1].values, &[1.0, 0.0, 0.0, 1.0, 0.0]);
    assert_values_close(&result.plots[2].values, &[1.0, 1.0, 1.0, 1.0, 1.0]);
}

#[test]
fn runs_calendar_week_and_month_timeframe_change() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("calendar timeframe change")
plot(timeframe.change("W") ? 1 : 0)
plot(timeframe.change("2W") ? 1 : 0)
plot(timeframe.change("M") ? 1 : 0)
plot(timeframe.change("3M") ? 1 : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let timestamps = [
        1_704_671_940_000,
        1_704_672_000_000,
        1_705_276_800_000,
        1_706_745_540_000,
        1_706_745_600_000,
        1_709_251_200_000,
        1_711_929_600_000,
    ];
    let bars = timestamps.map(|time| Bar {
        time,
        open: 1.0,
        high: 1.0,
        low: 1.0,
        close: 1.0,
        volume: 1.0,
    });
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("result");

    assert_values_close(
        &result.plots[0].values,
        &[1.0, 1.0, 1.0, 1.0, 0.0, 1.0, 1.0],
    );
    assert_values_close(
        &result.plots[1].values,
        &[1.0, 1.0, 0.0, 1.0, 0.0, 1.0, 1.0],
    );
    assert_values_close(
        &result.plots[2].values,
        &[1.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0],
    );
    assert_values_close(
        &result.plots[3].values,
        &[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0],
    );
}

#[test]
fn runs_iana_calendar_function_timezones() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("IANA calendar timezones")
winter = 1609504496000
summer = 1625142896000
previous_day = 1609466400000
plot(year(previous_day, "America/New_York"))
plot(month(previous_day, "America/New_York"))
plot(weekofyear(previous_day, "America/New_York"))
plot(dayofmonth(previous_day, "America/New_York"))
plot(dayofweek(previous_day, "America/New_York"))
plot(hour(previous_day, "America/New_York"))
plot(minute(previous_day, "America/New_York"))
plot(second(previous_day, "America/New_York"))
plot(hour(winter, "America/New_York"))
plot(hour(summer, "America/New_York"))
plot(hour(winter, "Asia/Tokyo"))
plot(minute(winter, "America/New_York"))
plot(second(winter, "America/New_York"))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)]).expect("result");

    assert_values_close(&result.plots[0].values, &[2020.0]);
    assert_values_close(&result.plots[1].values, &[12.0]);
    assert_values_close(&result.plots[2].values, &[53.0]);
    assert_values_close(&result.plots[3].values, &[31.0]);
    assert_values_close(&result.plots[4].values, &[5.0]);
    assert_values_close(&result.plots[5].values, &[21.0]);
    assert_values_close(&result.plots[6].values, &[0.0]);
    assert_values_close(&result.plots[7].values, &[0.0]);
    assert_values_close(&result.plots[8].values, &[7.0]);
    assert_values_close(&result.plots[9].values, &[8.0]);
    assert_values_close(&result.plots[10].values, &[21.0]);
    assert_values_close(&result.plots[11].values, &[34.0]);
    assert_values_close(&result.plots[12].values, &[56.0]);
}

#[test]
fn rejects_unsupported_calendar_function_timezone() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("bad calendar timezone")
plot(hour(time, "Mars/Olympus"))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let error = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)])
        .expect_err("expected calendar timezone error");

    assert!(
        error
            .message
            .contains("hour unsupported timezone `Mars/Olympus`"),
        "{}",
        error.message
    );
}

#[test]
fn runs_iana_numeric_timestamps() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("IANA timestamps")
plot(timestamp("America/New_York", 2021, 1, 1) == 1609477200000 ? 1 : 0)
plot(timestamp("America/New_York", 2021, 7, 1) == 1625112000000 ? 1 : 0)
plot(timestamp("Asia/Tokyo", 2021, 1, 1) == 1609426800000 ? 1 : 0)
plot(timestamp("America/New_York", 2021, 11, 7, 1, 30) == 1636263000000 ? 1 : 0)
plot(timestamp("America/New_York", 2021, 3, 14, 2, 30) == 1615707000000 ? 1 : 0)
plot(timestamp("Australia/Lord_Howe", 2021, 10, 3, 2, 15) == 1633189500000 ? 1 : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)]).expect("result");
    for plot in &result.plots {
        assert_values_close(&plot.values, &[1.0]);
    }
}

#[test]
fn rejects_invalid_timestamp_timezone() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("bad timestamp timezone")
plot(timestamp("Mars/Olympus", 2021, 1, 1))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let error = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)])
        .expect_err("expected timestamp timezone error");

    assert!(
        error
            .message
            .contains("timestamp unsupported timezone `Mars/Olympus`"),
        "{}",
        error.message
    );
}

#[test]
fn rejects_unsupported_timeframe_in_seconds_timeframe() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("bad timeframe")
plot(timeframe.in_seconds("1H"))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let err = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)])
        .expect_err("expected timeframe error");
    assert!(
        err.message
            .contains("timeframe.in_seconds unsupported timeframe `1H`"),
        "unexpected error: {err:?}"
    );
}

#[test]
fn rejects_unsupported_timeframe_from_seconds_value() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("bad timeframe seconds")
plot(timeframe.from_seconds(46) == "" ? 1 : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let err = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)])
        .expect_err("expected timeframe error");
    assert!(
        err.message
            .contains("timeframe.from_seconds unsupported seconds `46`"),
        "unexpected error: {err:?}"
    );
}

#[test]
fn rejects_unsupported_timeframe_change_timeframe() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("bad timeframe change")
plot(timeframe.change("1H") ? 1 : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let err = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)])
        .expect_err("expected timeframe error");
    assert!(
        err.message
            .contains("timeframe.change unsupported timeframe `1H`"),
        "unexpected error: {err:?}"
    );
}

#[test]
fn rejects_unsupported_timestamp_date_string() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("bad timestamp date string")
plot(timestamp("20 Aug 2024 00:00 Mars/Olympus"))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let err = run_historical(
        &analysis.hir.expect("HIR"),
        &[Bar {
            time: 1_609_459_200_000,
            open: 1.0,
            high: 1.0,
            low: 1.0,
            close: 1.0,
            volume: 1.0,
        }],
    )
    .expect_err("expected timestamp dateString error");
    assert!(
        err.message
            .contains("timestamp unsupported dateString `20 Aug 2024 00:00 Mars/Olympus`"),
        "{}",
        err.message
    );
}

#[test]
fn runs_iana_timestamp_date_strings() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("IANA timestamp date strings")
plot(timestamp("2021-01-01 00:00 America/New_York") == 1609477200000 ? 1 : 0)
plot(timestamp("2021-07-01 00:00 America/New_York") == 1625112000000 ? 1 : 0)
plot(timestamp("2021-01-01 00:00 Asia/Tokyo") == 1609426800000 ? 1 : 0)
plot(timestamp("2021-11-07 01:30 America/New_York") == 1636263000000 ? 1 : 0)
plot(timestamp("2021-03-14 02:30 America/New_York") == 1615707000000 ? 1 : 0)
plot(timestamp("2021-10-03 02:15 Australia/Lord_Howe") == 1633189500000 ? 1 : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)]).expect("result");
    for plot in &result.plots {
        assert_values_close(&plot.values, &[1.0]);
    }
}

#[test]
fn rejects_time_function_bars_back_past_future_limit() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("bad time bars back")
plot(time("D", bars_back = -501))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let error = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)])
        .expect_err("expected bars_back future limit error");

    assert!(
        error
            .message
            .contains("time bars_back cannot reference more than 500 future bars"),
        "{}",
        error.message
    );
}

#[test]
fn rejects_time_function_timeframe_bars_back_past_future_limit() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("bad time timeframe bars back")
plot(time_close("D", timeframe_bars_back = -501))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let error = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)])
        .expect_err("expected timeframe_bars_back future limit error");

    assert!(
        error
            .message
            .contains("time_close timeframe_bars_back cannot reference more than 500 future bars"),
        "{}",
        error.message
    );
}

#[test]
fn rejects_time_function_invalid_session_timezone() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("bad time session timezone")
plot(time("", "0001-0003", "Mars/Olympus"))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let error = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)])
        .expect_err("expected time session timezone error");

    assert!(
        error
            .message
            .contains("time unsupported timezone `Mars/Olympus`"),
        "{}",
        error.message
    );
}

#[test]
fn rejects_time_function_unsupported_session_string() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("bad time session")
plot(time("", "2500-2600"))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let error = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)])
        .expect_err("expected time session parse error");

    assert!(
        error
            .message
            .contains("time unsupported session `2500-2600`"),
        "{}",
        error.message
    );
}
