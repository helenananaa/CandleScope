use super::*;
use pine_ir::{PineType, Qualifier, ValueKind};

#[test]
fn accepts_fixnan() {
    let analysis = analyze(
        "source = close > open ? close : na\nplot(fixnan(source) + (fixnan(color.green == color.red ? color.green : na) == color.green ? 1 : 0))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "fixnan")
    );
}

#[test]
fn accepts_type_casts() {
    let analysis = analyze(
        "length = int(2.9)\nscale = float(length)\nflag = bool(close - open)\ntext = string(close)\nshade = color(color.red)\nmissing = color(na)\nmissing_box = box(na)\nmissing_label = label(na)\nmissing_line = line(na)\nmissing_fill = linefill(na)\nmissing_polyline = polyline(na)\nmissing_table = table(na)\nplot(flag ? ta.sma(close, length) + scale + str.length(text) + (shade == color.red and na(missing) and na(missing_box) and na(missing_label) and na(missing_line) and na(missing_fill) and na(missing_polyline) and na(missing_table) ? 1 : 0) : float(na))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    for feature in [
        "int", "float", "bool", "string", "color", "box", "label", "line", "linefill", "polyline",
        "table",
    ] {
        assert!(
            analysis
                .compatibility
                .supported
                .iter()
                .any(|supported| supported.feature == feature),
            "{feature} should be reported as supported"
        );
    }
}

#[test]
fn rejects_deep_semantic_expression_nesting() {
    let expression = format!("{}close", "+".repeat(130));
    let analysis = analyze(&format!("plot({expression})\n"));

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_SEMA_EXPR_DEPTH"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_unknown_history_offset() {
    let analysis = analyze("x = close[len]\n");

    assert_eq!(analysis.compatibility.unsupported.len(), 1);
    assert_eq!(
        analysis.compatibility.unsupported[0].feature,
        "dynamic_history_offset"
    );
}

#[test]
fn rejects_non_int_history_offset() {
    let analysis = analyze("x = close[close]\n");

    assert_eq!(analysis.compatibility.unsupported.len(), 1);
    assert_eq!(
        analysis.compatibility.unsupported[0].feature,
        "dynamic_history_offset"
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn accepts_series_history_offset() {
    let analysis = analyze("x = close[bar_index]\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    let hir = analysis.hir.expect("HIR");
    assert!(hir.history.has_dynamic_offsets);
}

#[test]
fn rejects_negative_history_offset() {
    let analysis = analyze("x = close[-1]\n");

    assert_eq!(analysis.compatibility.unsupported.len(), 1);
    assert_eq!(
        analysis.compatibility.unsupported[0].feature,
        "negative_history_offset"
    );
}

#[test]
fn rejects_named_const_negative_history_offset() {
    let analysis = analyze("length = -1\nx = close[length]\n");

    assert_eq!(analysis.compatibility.unsupported.len(), 1);
    assert_eq!(
        analysis.compatibility.unsupported[0].feature,
        "negative_history_offset"
    );
}

#[test]
fn accepts_constant_history_offset() {
    let analysis = analyze("x = close[1]\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn rejects_wrong_builtin_argument_type() {
    let analysis = analyze("plot(ta.sma(close, close))\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE")
    );
}

#[test]
fn rejects_missing_builtin_argument() {
    let analysis = analyze("plot()\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARITY")
    );
}

#[test]
fn rejects_unknown_named_argument() {
    let analysis = analyze("indicator(\"Demo\", bogus=true)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_NAME")
    );
}

#[test]
fn accepts_named_colors_and_color_new() {
    let analysis = analyze(
        r#"indicator("colors")
base = input.color(color.orange, "Base")
shade = color.new(base, 50)
opaque = color.new(color.blue)
custom = color.rgb(255, 153, 0, 50)
gradient = color.from_gradient(close, 1, 3, color.red, color.green)
hex = #ff990080
channels = color.r(custom) + color.g(custom) + color.b(custom) + color.t(custom)
hex_channels = color.r(hex) + color.g(hex) + color.b(hex) + color.t(hex)
plot(close, color=gradient)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "color.new")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "color.rgb")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "color.r")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "color.g")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "color.b")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "color.t")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "color.from_gradient")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "hex color literal")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "color.orange")
    );
}

#[test]
fn promoted_string_and_bool_return_qualifiers_follow_arguments() {
    let analysis = analyze(
        r#"indicator("Promoted string/bool return qualifiers")
input_text = input.string("ABC", "Text")
input_count = input.int(7, "Count")
input_string = str.tostring(input_count)
input_bool = str.contains(input_text, "A")
simple_string = str.format("{0}", timeframe.period)
simple_bool = str.contains(timeframe.period, "D")
series_string = str.tostring(close)
series_bool = str.contains(series_string, "1")
plot(series_bool ? 1 : 0)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    for (name, pine_type) in [
        (
            "input_string",
            PineType::new(Qualifier::Input, ValueKind::String),
        ),
        (
            "input_bool",
            PineType::new(Qualifier::Input, ValueKind::Bool),
        ),
        (
            "simple_string",
            PineType::new(Qualifier::Simple, ValueKind::String),
        ),
        (
            "simple_bool",
            PineType::new(Qualifier::Simple, ValueKind::Bool),
        ),
        (
            "series_string",
            PineType::new(Qualifier::Series, ValueKind::String),
        ),
        (
            "series_bool",
            PineType::new(Qualifier::Series, ValueKind::Bool),
        ),
    ] {
        let symbol = hir
            .symbols
            .iter()
            .find(|symbol| symbol.name == name)
            .unwrap_or_else(|| panic!("{name} symbol"));
        assert_eq!(symbol.pine_type, pine_type, "{name}");
    }
}

#[test]
fn bool_from_arg_return_qualifiers_follow_arguments() {
    let analysis = analyze(
        r#"indicator("BoolFromArg return qualifiers")
input_source = input.bool(true, "Flag")
input_cast_bool = bool(input_source)
input_na_bool = na(input_source)
simple_source = timeframe.period == "1"
simple_cast_bool = bool(simple_source)
simple_na_bool = na(simple_source)
series_source = close > open
series_cast_bool = bool(series_source)
series_na_bool = na(series_source)
plot(series_cast_bool or series_na_bool ? 1 : 0)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    for (name, pine_type) in [
        (
            "input_cast_bool",
            PineType::new(Qualifier::Input, ValueKind::Bool),
        ),
        (
            "input_na_bool",
            PineType::new(Qualifier::Input, ValueKind::Bool),
        ),
        (
            "simple_cast_bool",
            PineType::new(Qualifier::Simple, ValueKind::Bool),
        ),
        (
            "simple_na_bool",
            PineType::new(Qualifier::Simple, ValueKind::Bool),
        ),
        (
            "series_cast_bool",
            PineType::new(Qualifier::Series, ValueKind::Bool),
        ),
        (
            "series_na_bool",
            PineType::new(Qualifier::Series, ValueKind::Bool),
        ),
    ] {
        let symbol = hir
            .symbols
            .iter()
            .find(|symbol| symbol.name == name)
            .unwrap_or_else(|| panic!("{name} symbol"));
        assert_eq!(symbol.pine_type, pine_type, "{name}");
    }
}

#[test]
fn rejects_unknown_named_color() {
    let analysis = analyze("plot(close, color=color.not_registered)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_UNKNOWN_COLOR")
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn accepts_string_helpers() {
    let analysis = analyze(
        r##"indicator("strings")
mode = input.string("sma", "Mode")
upper = str.upper(mode)
lower = str.lower(upper)
length = str.length(upper)
missing = str.length(na)
matched = str.contains(upper, "M") and str.startswith(upper, "S") and str.endswith(upper, "A")
empty_match = str.contains(upper, "") and str.startswith(upper, "") and str.endswith(upper, "")
missing_match = str.contains(na, "S")
mid = str.pos(upper, "M")
missing_pos = str.pos(upper, "Z")
empty_pos = str.pos(upper, "")
na_pos = str.pos(upper, na)
slice = str.substring(upper, mid, mid + 1)
tail = str.substring(upper, mid)
wide = str.substring(upper, 1, 99)
na_begin = str.substring(upper, na, 1)
trimmed = str.trim(" \tSMA\n")
repeated = str.repeat("ab", 2, "-")
empty_repeat = str.repeat("ab", 0)
missing_repeat = str.repeat("ab", na)
replace_first = str.replace("hello", "l", "1")
replace_second = str.replace("hello", "l", "1", 1)
replace_missing = str.replace("hello", "z", "1", 0)
replace_all = str.replace_all("hello", "l", "1")
replace_boundary = str.replace("ab", "", ".", 1)
replace_all_boundaries = str.replace_all("ab", "", ".")
missing_replace = str.replace(na, "x", "y")
number = str.tonumber("1234.50")
signed_number = str.tonumber("-.5")
invalid_number = str.tonumber("$1,234.50")
exponent_number = str.tonumber("1e3")
signed_exponent_number = str.tonumber("-.5e+2")
upper_exponent_number = str.tonumber("+12E-1")
bad_exponent_number = str.tonumber("1e")
missing_number = str.tonumber(na)
text_int = str.tostring(42)
text_float = str.tostring(1.25)
text_round0 = str.tostring(1.25, "#")
text_round1 = str.tostring(1.25, "#.#")
text_zeros = str.tostring(1.25, "#.0000")
text_percent = str.tostring(0.1234, format.percent)
text_price = str.tostring(1.234567891, format.price)
text_volume = str.tostring(1234.567, format.volume)
text_bool = str.tostring(true)
text_string = str.tostring("ok")
text_na = str.tostring(na)
values = array.new_float(3)
array.set(values, 0, 1.2)
array.set(values, 1, 2.6)
text_array = str.tostring(values, "#")
formatted = str.format("A={0}, B={1}, A2={0}", text_int, text_float)
formatted_missing = str.format("Missing {2}", text_int)
formatted_number = str.format("Rounded {0,number,#.00} Percent {1,number,percent}", 1.2, 0.0345)
formatted_integer = str.format("Integer {0,number,integer}", 1234.5)
formatted_currency = str.format("Currency {0,number,currency}", 1234.5)
formatted_array = str.format("Values {0}", values)
formatted_datetime = str.format("{0,date,yyyy-MM-dd}T{0,time,HH:mm:ssZ}", 1609459200000)
formatted_quote = str.format("Literal '{0}' and apostrophe '' {0}", "X")
match_prefix = str.match("NASDAQ:AAPL", "^(?:BATS|NASDAQ|NYSE|AMEX):")
match_suffix = str.match("NASDAQ:AAPL", "AAPL$")
match_missing = str.match("NASDAQ:AAPL", "^NYSE:")
missing_match_regex = str.match(na, ".+")
split_words = str.split("A,B,,C", ",")
split_chars = str.split("xy", "")
split_missing = str.split(na, ",")
formatted_time_default = str.format_time(1609459200000)
formatted_time_date = str.format_time(1609459200000, "yyyy-MM-dd")
formatted_time_text = str.format_time(1609459200000, "HH:mm:ss 'on' MMM dd, yyyy", "UTC")
missing_format_time = str.format_time(na)
plot(upper == "SMA" and lower == "sma" ? length : 0)
plot(na(missing) ? 1 : 0)
plot(matched and empty_match ? 1 : 0)
plot(na(missing_match) ? 1 : 0)
plot(mid + empty_pos)
plot(na(na_pos) ? 1 : 0)
plot(na(missing_pos) ? 1 : 0)
plot(slice == "M" and tail == "MA" and wide == "MA" and na_begin == "S" ? 1 : 0)
plot(trimmed == upper and repeated == "ab-ab" and empty_repeat == "" ? 1 : 0)
plot(na(missing_repeat) ? 1 : 0)
plot(replace_first == "he1lo" and replace_second == "hel1o" and replace_missing == "hello" ? 1 : 0)
plot(replace_all == "he11o" and replace_boundary == "a.b" and replace_all_boundaries == ".a.b." ? 1 : 0)
plot(na(missing_replace) ? 1 : 0)
plot(number == 1234.5 and signed_number == -0.5 ? 1 : 0)
plot(exponent_number == 1000 and signed_exponent_number == -50 and upper_exponent_number == 1.2 ? 1 : 0)
plot(na(invalid_number) and na(bad_exponent_number) and na(missing_number) ? 1 : 0)
plot(text_int == "42" and text_float == "1.25" and text_round0 == "1" and text_round1 == "1.3" ? 1 : 0)
plot(text_zeros == "1.2500" and text_percent == "12.34%" ? 1 : 0)
plot(text_price == "1.23456789" and text_volume == "1234.57" ? 1 : 0)
plot(text_bool == "true" and text_string == "ok" and text_na == "NaN" ? 1 : 0)
plot(text_array == "[1, 3, NaN]" ? 1 : 0)
plot(formatted == "A=42, B=1.25, A2=42" and formatted_missing == "Missing {2}" ? 1 : 0)
plot(formatted_number == "Rounded 1.20 Percent 3.45%" and formatted_integer == "Integer 1,235" and formatted_currency == "Currency $1,234.50" ? 1 : 0)
plot(formatted_array == "Values [1.2, 2.6, NaN]" and formatted_datetime == "2021-01-01T00:00:00+0000" and formatted_quote == "Literal {0} and apostrophe ' X" ? 1 : 0)
plot(match_prefix == "NASDAQ:" and match_suffix == "AAPL" and match_missing == "" ? 1 : 0)
plot(na(missing_match_regex) ? 1 : 0)
plot(split_words.size() == 4 and split_words.get(0) == "A" and split_words.get(2) == "" and split_words.get(3) == "C" ? 1 : 0)
plot(split_chars.size() == 2 and split_chars.get(0) == "x" and split_chars.get(1) == "y" and na(split_missing) ? 1 : 0)
plot(formatted_time_default == "2021-01-01T00:00:00+0000" and formatted_time_date == "2021-01-01" ? 1 : 0)
plot(formatted_time_text == "00:00:00 on Jan 01, 2021" and missing_format_time == "1970-01-01T00:00:00+0000" ? 1 : 0)
"##,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    for feature in [
        "str.upper",
        "str.lower",
        "str.length",
        "str.contains",
        "str.startswith",
        "str.endswith",
        "str.pos",
        "str.substring",
        "str.trim",
        "str.repeat",
        "str.replace",
        "str.replace_all",
        "str.tonumber",
        "str.tostring",
        "str.format",
        "str.match",
        "str.split",
        "str.format_time",
    ] {
        assert!(
            analysis
                .compatibility
                .supported
                .iter()
                .any(|supported| supported.feature == feature),
            "{feature} not reported as supported"
        );
    }
}

#[test]
fn accepts_time_helpers() {
    let analysis = analyze(
        r#"indicator("time helpers")
ts = timestamp(2021, 2, 2, 3, 4, 5)
ts_utc = timestamp("UTC0", 2021, 2, 2, 3, 4, 5)
ts_fixed_offset = timestamp("UTC+4", 2021, 1, 1)
ts_named = timestamp(timezone = "Etc/UTC", year = 2021, month = 2, day = 2, hour = 3, minute = 4, second = 5)
ts_date = timestamp("2021-01-01")
ts_date_named = timestamp(dateString = "29 Aug 2024")
daily_open = time("D")
chart_open = time("")
chart_close = time_close(timeframe.period)
daily_close = time_close("D")
previous_daily_open = time("D", bars_back = 1)
previous_chart_close = time_close("", 1)
previous_timeframe_daily_open = time("D", timeframe_bars_back = 1)
dynamic_offset_daily_close = time_close("D", bars_back = bar_index, timeframe_bars_back = bar_index)
session_open = time(timeframe.period, "0930-1600")
session_close = time_close(timeframe.period, "0930-1600", "UTC", 1, 1)
plot(year(ts) + month(ts, "UTC") + weekofyear(ts) + dayofmonth(ts) + dayofweek(ts) + hour(ts) + minute(ts) + second(ts) + time_tradingday / 1000000000000 + (dayofweek == dayofweek.friday ? 1 : 0))
plot(ts == ts_utc and ts_named == ts and ts_fixed_offset < ts ? 1 : 0)
plot(ts_date <= ts and ts_date_named > ts ? 1 : 0)
plot(daily_open <= time and chart_open == time and chart_close == time_close and daily_close >= time_close ? 1 : 0)
plot(previous_daily_open <= daily_open and previous_chart_close <= time_close ? 1 : 0)
plot(previous_timeframe_daily_open <= daily_open and dynamic_offset_daily_close <= daily_close ? 1 : 0)
plot(na(session_open) or session_close >= session_open ? 1 : 0)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    for feature in [
        "timestamp",
        "year",
        "month",
        "weekofyear",
        "dayofmonth",
        "dayofweek",
        "dayofweek.friday",
        "hour",
        "minute",
        "second",
    ] {
        assert!(
            analysis
                .compatibility
                .supported
                .iter()
                .any(|supported| supported.feature == feature),
            "{feature} not reported as supported"
        );
    }
}

#[test]
fn rejects_unsupported_time_function_overloads() {
    let analysis = analyze(
        r#"indicator("unsupported time overloads")
plot(time("D", true))
plot(time_close("D", bad_arg = 1))
plot(time(session = "0000-0001"))
plot(timestamp(dateString = 20210101))
"#,
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_NAME"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARITY"),
        "{:?}",
        analysis.diagnostics
    );
}

#[test]
fn accepts_timeframe_helpers() {
    let analysis = analyze(
        r#"indicator("timeframe helpers")
tf = input.timeframe("60", "TF")
seconds = timeframe.in_seconds() + timeframe.in_seconds(tf) + timeframe.in_seconds("D")
roundtrip = timeframe.from_seconds(timeframe.in_seconds(tf)) == tf
missing_tf = timeframe.from_seconds(na)
tf_change = timeframe.change("D")
is_one_minute = timeframe.isminutes and timeframe.isintraday and not timeframe.isseconds and not timeframe.isdaily and not timeframe.isweekly and not timeframe.ismonthly and not timeframe.isdwm and timeframe.multiplier == 1
plot(timeframe.period == "1" and is_one_minute and roundtrip and na(missing_tf) and tf_change ? seconds : 0)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    for feature in [
        "timeframe.in_seconds",
        "timeframe.from_seconds",
        "timeframe.change",
        "timeframe.period",
        "timeframe.isseconds",
        "timeframe.isminutes",
        "timeframe.isintraday",
        "timeframe.isdaily",
        "timeframe.isweekly",
        "timeframe.ismonthly",
        "timeframe.isdwm",
        "timeframe.multiplier",
    ] {
        assert!(
            analysis
                .compatibility
                .supported
                .iter()
                .any(|supported| supported.feature == feature),
            "{feature} not reported as supported"
        );
    }
}

#[test]
fn accepts_barstate_isfirst() {
    let analysis = analyze(
        "plot((barstate.isfirst or barstate.islast or barstate.islastconfirmedhistory or barstate.isnew or barstate.isconfirmed or barstate.ishistory or barstate.isrealtime or session.ismarket or session.ispremarket or session.ispostmarket or session.isfirstbar or session.islastbar or session.isfirstbar_regular or session.islastbar_regular or syminfo.session == session.regular or syminfo.session == session.extended or adjustment.none == \"none\" or adjustment.splits == \"splits\" or adjustment.dividends == \"dividends\" or settlement_as_close.on == \"on\" or settlement_as_close.off == \"off\" or settlement_as_close.inherit == \"inherit\" or backadjustment.on == \"on\" or backadjustment.off == \"off\" or backadjustment.inherit == \"inherit\") ? 1 : 0)\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "barstate.isfirst")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "barstate.islast")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "barstate.islastconfirmedhistory")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "barstate.isnew")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "barstate.isconfirmed")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "barstate.ishistory")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "barstate.isrealtime")
    );
    for feature in [
        "session.ismarket",
        "session.ispremarket",
        "session.ispostmarket",
        "session.isfirstbar",
        "session.islastbar",
        "session.isfirstbar_regular",
        "session.islastbar_regular",
        "session.regular",
        "session.extended",
        "adjustment.none",
        "adjustment.splits",
        "adjustment.dividends",
        "settlement_as_close.on",
        "settlement_as_close.off",
        "settlement_as_close.inherit",
        "backadjustment.on",
        "backadjustment.off",
        "backadjustment.inherit",
    ] {
        assert!(
            analysis
                .compatibility
                .supported
                .iter()
                .any(|supported| supported.feature == feature),
            "{feature} not reported as supported"
        );
    }
}

#[test]
fn accepts_global_price_and_derived_series() {
    let analysis = analyze(
        "plot(open + high + low + close + volume + time + time_close + hl2 + hlc3 + hlcc4 + ohlc4 + bar_index + last_bar_index + last_bar_time)\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_selected_math_functions() {
    let analysis = analyze(
        r#"indicator("math")
x = math.max(math.abs(close - 3), math.round(close / 2), 1)
y = math.min(x, 3.5)
avg_value = math.avg(open, close, high, low)
rounded_precision = math.round(close / 3, 2)
z = math.floor(close / 2) + math.ceil(close / 2)
w = math.trunc(close / 2) + math.sqrt(close) + math.cbrt(close) + math.log(close) + math.pow(close, 2) + math.hypot(close, high)
random_value = math.random(10, 20, 7)
scale = math.log10(close) + math.exp(close)
trig = math.sin(close) + math.cos(close) + math.tan(close)
inverse_trig = math.acos(close - 2) + math.asin(close - 2) + math.atan(close)
angle_helpers = math.sign(close - 2) + math.todegrees(close) + math.toradians(close)
constants = math.pi + math.e + math.phi + math.rphi
rounded_mintick = math.round_to_mintick(close + 0.006)
mintick = syminfo.mintick
sum_value = math.sum(close, 3)
plot(y)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "math.max")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "math.min")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "math.avg")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "math.round")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "math.random")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "math.floor")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "math.ceil")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "math.trunc")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "math.sqrt")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "math.cbrt")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "math.log")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "math.log10")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "math.exp")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "math.acos")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "math.asin")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "math.atan")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "math.sign")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "math.todegrees")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "math.toradians")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "math.pi")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "math.e")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "math.phi")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "math.rphi")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "math.pow")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "math.hypot")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "math.sin")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "math.cos")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "math.tan")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "math.sum")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "math.round_to_mintick")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "syminfo.mintick")
    );
}

#[test]
fn accepts_const_na_math_rounding_inputs() {
    let analysis = analyze(
        r#"indicator("math na rounding")
plot(math.floor(na))
plot(math.ceil(na))
plot(math.trunc(na))
plot(math.round(na))
plot(math.round(close + 0.25, na))
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_const_na_unary_math_inputs() {
    let analysis = analyze(
        r#"indicator("math unary na")
plot(math.sqrt(na))
plot(math.cbrt(na))
plot(math.log(na))
plot(math.log10(na))
plot(math.exp(na))
plot(math.acos(na))
plot(math.asin(na))
plot(math.atan(na))
plot(math.sign(na))
plot(math.todegrees(na))
plot(math.toradians(na))
plot(math.sin(na))
plot(math.cos(na))
plot(math.tan(na))
plot(math.round_to_mintick(na))
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_const_na_math_abs_input() {
    let analysis = analyze(
        r#"indicator("math abs na")
plot(math.abs(na))
"#,
    );

    assert!(
        !analysis.diagnostics.is_empty(),
        "direct untyped math.abs(na) should still require a typed consumer"
    );

    let analysis = analyze(
        r#"indicator("math abs na")
plot(float(math.abs(na)))
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_const_na_math_random_bounds() {
    let analysis = analyze(
        r#"indicator("math random na bounds")
plot(math.random(na, 1, 7))
plot(math.random(0, na, 7))
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_const_na_promoted_float_math_inputs() {
    let analysis = analyze(
        r#"indicator("math promoted float na")
plot(math.avg(na, 1))
plot(math.avg(close, na, high))
plot(math.pow(na, 2))
plot(math.pow(2, na))
plot(math.hypot(na, close))
plot(math.hypot(close, na))
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_const_na_min_max_math_inputs() {
    let analysis = analyze(
        r#"indicator("math min max na")
plot(math.max(na, 1))
plot(math.max(close, na, high))
plot(math.min(na, 1))
plot(math.min(close, na, low))
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_const_na_math_sum_source() {
    let analysis = analyze(
        r#"indicator("math sum na source")
plot(math.sum(na, 2))
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_integer_rounding_math_functions_as_int_values() {
    let analysis = analyze(
        r#"indicator("integer rounding types")
floor_values = array.new_int(1, math.floor(close / 2))
ceil_values = array.new_int(1, math.ceil(close / 2))
trunc_values = array.new_int(1, math.trunc(close / 2))
round_values = array.new_int(1, math.round(close / 2))
plot(array.size(floor_values) + array.size(ceil_values) + array.size(trunc_values) + array.size(round_values))
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_syminfo_metadata() {
    let analysis = analyze(
        r#"indicator("syminfo")
identity = syminfo.tickerid == "NASDAQ:AAPL" and syminfo.main_tickerid == "NASDAQ:AAPL" and syminfo.ticker == "AAPL" and syminfo.prefix == "NASDAQ"
details = syminfo.description == "Apple Inc." and syminfo.type == "stock" and syminfo.currency == "USD" and syminfo.basecurrency == "USD"
session = syminfo.session == "regular" and syminfo.timezone == "Etc/UTC" and syminfo.root == "AAPL" and syminfo.volumetype == "base"
classification = syminfo.sector == "Electronic Technology" and syminfo.industry == "Telecommunications Equipment" and syminfo.country == "US"
helpers = syminfo.prefix("NASDAQ:AAPL") == "NASDAQ" and syminfo.ticker("NASDAQ:AAPL") == "AAPL" and syminfo.prefix(syminfo.tickerid) == "NASDAQ" and syminfo.ticker(syminfo.tickerid) == "AAPL"
scale = syminfo.mintick + syminfo.mincontract + syminfo.pointvalue + syminfo.minmove + syminfo.pricescale
plot(identity and details and session and classification and helpers ? scale : 0)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    for feature in [
        "syminfo.tickerid",
        "syminfo.main_tickerid",
        "syminfo.ticker",
        "syminfo.prefix",
        "syminfo.description",
        "syminfo.country",
        "syminfo.industry",
        "syminfo.type",
        "syminfo.currency",
        "syminfo.basecurrency",
        "syminfo.session",
        "syminfo.sector",
        "syminfo.timezone",
        "syminfo.root",
        "syminfo.volumetype",
        "syminfo.mintick",
        "syminfo.mincontract",
        "syminfo.pointvalue",
        "syminfo.minmove",
        "syminfo.pricescale",
    ] {
        assert!(
            analysis
                .compatibility
                .supported
                .iter()
                .any(|supported| supported.feature == feature),
            "{feature} not reported as supported"
        );
    }
}

#[test]
fn accepts_ticker_standard() {
    let analysis = analyze(
        r#"indicator("ticker standard")
created = ticker.new(syminfo.prefix, syminfo.ticker)
extended = ticker.new(syminfo.prefix, syminfo.ticker, session.extended)
adjusted = ticker.new(syminfo.prefix, syminfo.ticker, session.extended, adjustment.dividends)
futures = ticker.new(syminfo.prefix, syminfo.ticker, session.regular, adjustment.none, settlement_as_close.on, backadjustment.inherit)
modified = ticker.modify(created)
modified_extended = ticker.modify(created, session.extended)
modified_adjusted = ticker.modify(created, session.extended, adjustment.splits)
modified_futures = ticker.modify(futures, session.regular, adjustment.none, settlement_as_close.off, backadjustment.on)
ha = ticker.heikinashi(adjusted)
inherited = ticker.inherit(adjusted, "NYSE:PFE")
kagi = ticker.kagi(adjusted, "ATR", 10)
linebreak = ticker.linebreak(adjusted, 3)
pointfigure = ticker.pointfigure(adjusted, "hl", "ATR", 14, 3)
renko = ticker.renko(adjusted, "ATR", 10)
standard = ticker.standard(syminfo.tickerid)
extended_standard = ticker.standard(extended)
modified_standard = ticker.standard(modified_extended)
adjusted_standard = ticker.standard(adjusted)
futures_standard = ticker.standard(futures)
modified_adjusted_standard = ticker.standard(modified_adjusted)
modified_futures_standard = ticker.standard(modified_futures)
ha_standard = ticker.standard(ha)
inherited_standard = ticker.standard(inherited)
kagi_standard = ticker.standard(kagi)
linebreak_standard = ticker.standard(linebreak)
pointfigure_standard = ticker.standard(pointfigure)
renko_standard = ticker.standard(renko)
plot(created == "NASDAQ:AAPL" and extended_standard == "NASDAQ:AAPL" and adjusted_standard == "NASDAQ:AAPL" and futures_standard == "NASDAQ:AAPL" and modified == "NASDAQ:AAPL" and modified_standard == "NASDAQ:AAPL" and modified_adjusted_standard == "NASDAQ:AAPL" and modified_futures_standard == "NASDAQ:AAPL" and ha_standard == "NASDAQ:AAPL" and inherited_standard == "NYSE:PFE" and kagi_standard == "NASDAQ:AAPL" and linebreak_standard == "NASDAQ:AAPL" and pointfigure_standard == "NASDAQ:AAPL" and renko_standard == "NASDAQ:AAPL" and standard == "NASDAQ:AAPL" ? 1 : 0)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    for feature in [
        "ticker.heikinashi",
        "ticker.inherit",
        "ticker.kagi",
        "ticker.linebreak",
        "ticker.new",
        "ticker.modify",
        "ticker.pointfigure",
        "ticker.renko",
        "ticker.standard",
    ] {
        assert!(
            analysis
                .compatibility
                .supported
                .iter()
                .any(|supported| supported.feature == feature),
            "{feature} should be reported as supported"
        );
    }
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_chart_type_metadata() {
    let analysis = analyze(
        r#"indicator("chart type metadata")
is_standard = chart.is_standard and not chart.is_heikinashi and not chart.is_kagi and not chart.is_linebreak and not chart.is_pnf and not chart.is_range and not chart.is_renko
appearance = color.r(chart.bg_color) == 255 and color.g(chart.bg_color) == 255 and color.b(chart.bg_color) == 255 and color.t(chart.bg_color) == 0 and color.r(chart.fg_color) == 0 and color.g(chart.fg_color) == 0 and color.b(chart.fg_color) == 0 and color.t(chart.fg_color) == 0
visible_window = chart.left_visible_bar_time <= chart.right_visible_bar_time
plot(is_standard and appearance and visible_window ? 1 : 0)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    for feature in [
        "chart.bg_color",
        "chart.fg_color",
        "chart.left_visible_bar_time",
        "chart.right_visible_bar_time",
        "chart.is_standard",
        "chart.is_heikinashi",
        "chart.is_kagi",
        "chart.is_linebreak",
        "chart.is_pnf",
        "chart.is_range",
        "chart.is_renko",
    ] {
        assert!(
            analysis
                .compatibility
                .supported
                .iter()
                .any(|supported| supported.feature == feature),
            "{feature} not reported as supported"
        );
    }
}

#[test]
fn accepts_if_tuple_declaration_shadowing_outer_symbols() {
    let analysis =
        analyze("x = close\ny = close\nif close > open\n    [x, y] = [high, low]\nplot(x)\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn rejects_if_branch_assignment_type_mismatch() {
    let analysis = analyze("x = close\nif close > open\n    x := true\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_ASSIGN_TYPE")
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_non_bool_while_condition() {
    let analysis = analyze("while close\n    plot(close)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CONDITION_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_while_expression_non_bool_condition() {
    let analysis = analyze("result = while 1\n    1\nplot(result)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CONDITION_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_while_expression_without_final_result() {
    let analysis = analyze("result = while close > open\n    value = 1\nplot(result)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_BRANCH_RETURN"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn accepts_while_expression_scalar_result() {
    let analysis = analyze("result = while close > open\n    close\nplot(result)\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "while"),
        "{:?}",
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}
