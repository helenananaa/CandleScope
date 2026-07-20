use super::*;
use pine_ir::{PineType, Qualifier, ValueKind};

fn analyze_with_library(root: &str, library: &str) -> Analysis {
    let input = AnalysisInput::with_library_sources(
        SourceFile::new("root.pine", root.to_owned()),
        vec![(
            "user/lib/1".to_owned(),
            SourceFile::new("library.pine", library.to_owned()),
        )],
    )
    .expect("library source should be valid");
    crate::analysis::analyze_input_with_implicit_dialect(&input, crate::PineDialect::V5)
}

#[test]
fn accepts_input_string_in_conditions() {
    let analysis =
        analyze("mode = input.string(\"SMA\", \"Mode\")\nplot(mode == \"SMA\" ? close : open)\n");

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
            .any(|feature| feature.feature == "input.string")
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_additional_input_variants() {
    let analysis = analyze(
        "threshold = input.price(2.5, \"Price\")\nstart = input.time(0, \"Start\")\nsymbol = input.symbol(\"AAPL\", \"Symbol\")\ntimeframe = input.timeframe(\"D\", \"Timeframe\")\nsession = input.session(\"0930-1600\", \"Session\")\nnotes = input.text_area(\"Plan\", \"Notes\")\nplot(time >= start and symbol == \"AAPL\" and timeframe == \"D\" and session == \"0930-1600\" and notes == \"Plan\" ? math.max(close, threshold) : open)\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    for name in [
        "input.price",
        "input.time",
        "input.symbol",
        "input.timeframe",
        "input.session",
        "input.text_area",
    ] {
        assert!(
            analysis
                .compatibility
                .supported
                .iter()
                .any(|feature| feature.feature == name),
            "{name} should be reported as supported"
        );
    }
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_generic_input_variants() {
    let analysis = analyze(
        "length = input(2, \"Length\")\nscale = input(1.5, \"Scale\")\nenabled = input(true, \"Enabled\")\nmode = input(\"SMA\", \"Mode\")\nshade = input(color.orange, \"Shade\")\nplot(enabled and mode == \"SMA\" ? ta.sma(close, length) * scale : open, color=color.new(shade, 10))\n",
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
            .any(|feature| feature.feature == "input")
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_common_input_metadata_parameters() {
    let analysis = analyze(
        r#"length = input.int(2, "Length", minval=1, maxval=20, step=1, options=[1, 2, 3], tooltip="Bars", inline="row", group="Settings", confirm=true, display=display.all)
scale = input.float(1.5, "Scale", minval=0.5, maxval=5.0, step=0.25, options=[1.0, 1.5], display=display.none)
enabled = input.bool(true, "Enabled", tooltip="Toggle", inline="row", group="Settings", confirm=false)
mode = input.string("SMA", "Mode", options=["SMA", "EMA"], tooltip="Mode")
shade = input.color(color.orange, "Shade", group="Style")
src = input.source(close, "Source", tooltip="Price", inline="src", group="Settings", confirm=true, display=display.all)
plot(enabled and mode == "SMA" ? math.max(src, length) * scale : close, color=shade)
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
fn accepts_bgcolor_and_barcolor() {
    let analysis =
        analyze("bgcolor(close > open ? color.green : na)\nbarcolor(color.red)\nplot(close)\n");

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
            .any(|feature| feature.feature == "bgcolor")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "barcolor")
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_common_output_metadata_parameters() {
    let analysis = analyze(
        r#"p = plot(close, title="Close", color=color.green, linewidth=2, style=plot.style_line, trackprice=false, histbase=0, offset=1, join=false, editable=true, show_last=10, display=display.pane, format=format.price, precision=2, force_overlay=false)
h = hline(2, title="Two", color=color.gray, linestyle=hline.style_dotted, linewidth=1, editable=true, display=display.price_scale)
fill(p, h, color=color.new(color.green, 80), title="Fill", editable=false, show_last=5, fillgaps=true, display=display.status_line)
bgcolor(color.new(color.blue, 90), title="Background", offset=0, editable=false, show_last=3, display=display.data_window)
barcolor(close > open ? color.green : color.red, title="Bars", offset=0, editable=true, show_last=3, display=display.none)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    for name in [
        "display.pane",
        "display.price_scale",
        "display.status_line",
        "display.data_window",
    ] {
        assert!(
            analysis
                .compatibility
                .supported
                .iter()
                .any(|feature| feature.feature == name),
            "{name} should be reported as supported"
        );
    }
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_indicator_scale_metadata_parameter() {
    let analysis = analyze(
        r#"indicator("Scale metadata", overlay=true, scale=scale.right)
plot(scale.left == "scale.left" and scale.right == "scale.right" and scale.none == "scale.none" ? close : open)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    for name in ["scale.left", "scale.right", "scale.none"] {
        assert!(
            analysis
                .compatibility
                .supported
                .iter()
                .any(|feature| feature.feature == name),
            "{name} should be reported as supported"
        );
    }
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_indicator_format_precision_metadata_parameters() {
    let analysis = analyze(
        r#"indicator("Format metadata", overlay=true, format=format.percent, precision=2, scale=scale.right)
plot(format.inherit == "format.inherit" and format.price == "format.price" and format.percent == "format.percent" and format.volume == "format.volume" ? close : open)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    for name in [
        "format.inherit",
        "format.price",
        "format.percent",
        "format.volume",
    ] {
        assert!(
            analysis
                .compatibility
                .supported
                .iter()
                .any(|feature| feature.feature == name),
            "{name} should be reported as supported"
        );
    }
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_indicator_string_metadata_ternary_constants() {
    let analysis = analyze(
        "indicator(\"Format metadata\", format=(1 + 1 == 2) ? format.percent : format.price, scale=false ? scale.left : scale.right)\n",
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
fn accepts_indicator_string_metadata_named_const_aliases() {
    let analysis = analyze(
        "fmt_base = format.percent\nfmt = fmt_base\nscale_base = scale.right\nscale_value = scale_base\nindicator(\"Format metadata\", format=fmt, scale=scale_value)\n",
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
fn rejects_unknown_indicator_scale_metadata_value() {
    let analysis = analyze("indicator(\"Scale metadata\", scale=\"custom\")\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_VALUE"),
        "{:?}",
        analysis.diagnostics
    );
}

#[test]
fn rejects_unknown_indicator_string_metadata_named_const_alias() {
    let analysis = analyze(
        "scale_base = \"custom\"\nscale_value = scale_base\nindicator(\"Scale metadata\", scale=scale_value)\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_VALUE"
                && diagnostic.message
                    == "`indicator` argument `scale` only supports scale.left, scale.right, scale.none"),
        "{:?}",
        analysis.diagnostics
    );
}

#[test]
fn rejects_unknown_indicator_string_metadata_ternary_value() {
    let analysis = analyze("indicator(\"Scale metadata\", scale=true ? \"custom\" : scale.left)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_VALUE"
                && diagnostic.message
                    == "`indicator` argument `scale` only supports scale.left, scale.right, scale.none"),
        "{:?}",
        analysis.diagnostics
    );
}

#[test]
fn rejects_unknown_indicator_format_metadata_value() {
    let analysis = analyze("indicator(\"Format metadata\", format=\"custom\")\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_VALUE"),
        "{:?}",
        analysis.diagnostics
    );
}

#[test]
fn rejects_out_of_range_indicator_precision_metadata_value() {
    let analysis = analyze("indicator(\"Format metadata\", precision=17)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_VALUE"),
        "{:?}",
        analysis.diagnostics
    );
}

#[test]
fn rejects_named_const_out_of_range_indicator_precision_metadata_value() {
    let analysis = analyze(
        "base = 17\nprecision = base\nindicator(\"Format metadata\", precision=precision)\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_VALUE"
                && diagnostic.message.contains("precision")),
        "{:?}",
        analysis.diagnostics
    );
}

#[test]
fn accepts_alertcondition_const_string_subset() {
    let analysis = analyze(
        r#"alertcondition(close > open, "Up", "Close is above open")
alertcondition(close > open, "OHLCV", "O={{open}} H={{high}} L={{low}} C={{close}} V={{volume}}")
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
            .any(|feature| feature.feature == "alertcondition")
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_alert_const_string_subset() {
    let analysis = analyze(
        r#"alert("Reached")
alert("Every call", alert.freq_all)
alert("Once", freq=alert.freq_once_per_bar)
alert("Close", freq=alert.freq_once_per_bar_close)
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
            .any(|feature| feature.feature == "alert")
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_alert_dynamic_message_subset() {
    let analysis = analyze(
        r#"message = input.string("Reached", "Message")
alert(message)
alert(str.tostring(close))
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
            .any(|feature| feature.feature == "alert")
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn rejects_alert_unsupported_frequency() {
    let analysis = analyze(
        r#"alert("Reached", freq="once")
"#,
    );

    assert!(
        analysis
            .compatibility
            .unsupported
            .iter()
            .any(|feature| feature.feature == "alert_frequency")
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_alert_placeholders() {
    let analysis = analyze(
        r#"alert("{{close}}")
alertcondition(true, "{{close}}", "Title placeholder")
alertcondition(true, "Title", "{{timenow}}")
"#,
    );

    assert!(
        analysis
            .compatibility
            .unsupported
            .iter()
            .any(|feature| feature.feature == "alert_placeholders")
    );
    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.message.contains("alert placeholder `{{close}}`"))
    );
    assert!(analysis.diagnostics.iter().any(|diagnostic| {
        diagnostic
            .message
            .contains("alert placeholder `{{timenow}}`")
    }));
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_alert_side_effects_inside_functions() {
    let analysis = analyze(
        r#"f() =>
    alert("Fn")
    close
plot(f())
"#,
    );

    assert!(
        analysis
            .compatibility
            .unsupported
            .iter()
            .any(|feature| feature.feature == "function_side_effect")
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_alertcondition_dynamic_messages() {
    let analysis = analyze(
        r#"title = input.string("Up", "Title")
alertcondition(close > open, title, "Message")
"#,
    );

    assert!(analysis.diagnostics.iter().any(|diagnostic| {
        diagnostic.code == "E_CALL_ARG_TYPE"
            && diagnostic.message.contains("argument `title`")
            && diagnostic.message.contains("input string")
    }));
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_alertcondition_side_effects_inside_functions() {
    let analysis = analyze(
        r#"f() =>
    alertcondition(true, "Fn", "Message")
    close
plot(f())
"#,
    );

    assert!(
        analysis
            .compatibility
            .unsupported
            .iter()
            .any(|feature| feature.feature == "function_side_effect")
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn accepts_plotchar() {
    let analysis = analyze(
        "plotchar(close > open, title=\"Marker\", char=\"x\", color=color.green, location=location.abovebar, offset=1, text=\"Up\", textcolor=color.white, editable=true, size=size.small, show_last=5, display=display.all)\nplot(close)\n",
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
            .any(|feature| feature.feature == "plotchar")
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_plotshape() {
    let analysis = analyze(
        "plotshape(close > open, title=\"Buy\", style=shape.triangleup, location=location.belowbar, color=color.green, offset=1, text=\"Buy\", textcolor=color.white, editable=true, size=size.small, show_last=5, display=display.all, force_overlay=false)\nplot(close)\n",
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
            .any(|feature| feature.feature == "plotshape")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "shape.triangleup")
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_plotarrow() {
    let analysis = analyze(
        "plotarrow(close - open, title=\"Momentum\", colorup=color.green, colordown=color.red, offset=1, minheight=5, maxheight=20, editable=true, show_last=5, display=display.all, force_overlay=false)\nplot(close)\n",
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
            .any(|feature| feature.feature == "plotarrow")
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_plotbar() {
    let analysis = analyze(
        "plotbar(open, high, low, close, title=\"Bars\", color=color.green, editable=true, show_last=5, display=display.all)\nplot(close)\n",
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
            .any(|feature| feature.feature == "plotbar")
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_plotcandle() {
    let analysis = analyze(
        "plotcandle(open, high, low, close, title=\"Candles\", color=color.green, wickcolor=color.white, editable=true, show_last=5, bordercolor=color.red, display=display.all)\nplot(close)\n",
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
            .any(|feature| feature.feature == "plotcandle")
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_minimal_label_new() {
    let analysis = analyze(
        "//@version=6\nid = label.new(bar_index, high, \"High\")\nomitted_text = label.new(bar_index, high)\nnamed_omitted_text = label.new(x=bar_index, y=high, xloc=xloc.bar_index)\nother = label.new(x=1, y=close, text=\"Close\", xloc=xloc.bar_index, yloc=yloc.price, color=color.green, style=label.style_label_up, textcolor=color.white, size=size.small, textalign=text.align_right, tooltip=\"Tip\", text_font_family=font.family_monospace, text_formatting=text.format_bold)\ntime_label = label.new(time, close, \"Time\", xloc=xloc.bar_time)\nabove = label.new(bar_index, high, \"Above\", yloc=yloc.abovebar)\nbelow = label.new(bar_index, low, \"Below\", yloc=yloc.belowbar)\nsquare = label.new(bar_index, high, \"Square\", style=label.style_square)\ndiamond = label.new(bar_index, high, \"Diamond\", style=label.style_diamond)\ncenter = label.new(bar_index, high, \"Center\", style=label.style_label_center)\nplot(close)\n",
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
            .any(|feature| feature.feature == "label.new")
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_label_new_chart_point_overload() {
    let analysis = analyze(
        "//@version=6\nindex_point = chart.point.from_index(bar_index + 1, high)\nid = label.new(index_point, \"index\", color=color.green, style=label.style_label_up, textcolor=color.white, size=size.small, textalign=text.align_left, tooltip=\"Tip\", text_font_family=font.family_monospace, text_formatting=text.format_bold)\ntime_point = chart.point.from_time(time + 60000, low)\ntime_id = label.new(point=time_point, xloc=xloc.bar_time, yloc=yloc.belowbar)\nmissing = label.new(point=na)\nplot(label.get_x(id) + label.get_x(time_id) + nz(label.get_x(missing), 0))\n",
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
            .any(|feature| feature.feature == "label.new"),
        "{:?}",
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn rejects_unsupported_label_new_modes() {
    let analysis = analyze(
        "label.new(bar_index, high, \"High\", xloc=xloc.bar_time, yloc=\"yloc.middle\", style=\"label.style_unknown\", size=\"size.massive\")\nplot(close)\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.message.contains("yloc.abovebar")),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.message.contains("label.style_label_down")),
        "{:?}",
        analysis.diagnostics
    );
    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.message.contains("size.normal")),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn accepts_label_new_int_size() {
    let analysis =
        analyze("//@version=6\nlabel.new(bar_index, high, \"High\", size=12)\nplot(close)\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn rejects_label_new_non_int_size() {
    let analysis = analyze("label.new(bar_index, high, \"High\", size=12.5)\nplot(close)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn accepts_label_set_int_size() {
    let analysis = analyze(
        "//@version=6\nid = label.new(bar_index, high, \"High\")\nlabel.set_size(id, 12)\nplot(close)\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn rejects_label_set_non_int_size() {
    let analysis = analyze(
        "id = label.new(bar_index, high, \"High\")\nlabel.set_size(id, 12.5)\nplot(close)\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn accepts_label_mutation_methods() {
    let analysis = analyze(
        "//@version=6\nid = label.new(bar_index, high, \"High\")\ncopy = label.copy(id)\nlabel.set_x(id, bar_index)\nlabel.set_xloc(id, time, xloc.bar_time)\nlabel.set_y(id, low)\nlabel.set_xy(id, bar_index, close)\nlabel.set_yloc(id, yloc.abovebar)\nlabel.set_text(id, \"Close\")\nlabel.set_color(id, color.green)\nlabel.set_textcolor(id, color.white)\nlabel.set_style(id, label.style_label_up)\nlabel.set_style(id, label.style_square)\nlabel.set_style(id, label.style_diamond)\nlabel.set_style(id, label.style_label_center)\nlabel.set_size(id, size.small)\nlabel.set_tooltip(id, \"Tip\")\nlabel.set_textalign(id, text.align_left)\nlabel.set_text_font_family(id, font.family_monospace)\nlabel.set_text_formatting(id, text.format_bold + text.format_italic)\nlabel.set_text_formatting(na, text.format_italic)\nlabel.set_text(na, \"noop\")\nlabel.delete(na)\nlabel.delete(id)\nplot(label.get_x(copy))\nplot(close)\n",
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
            .any(|feature| feature.feature == "label.copy")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "label.set_textalign")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "label.set_text_font_family")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "label.set_text_formatting")
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn rejects_invalid_label_text_formatting() {
    let analysis = analyze(
        "//@version=6\nid = label.new(bar_index, high, \"High\", text_formatting=text.format_bold + 4)\nlabel.set_text_formatting(id, text.format_italic + 4)\nplot(close)\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_VALUE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_unsupported_label_set_xloc_values() {
    let analysis = analyze(
        "id = label.new(bar_index, high, \"High\")\nlabel.set_xloc(id, bar_index, \"xloc.middle\")\nplot(close)\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.message.contains("xloc.bar_time")),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn accepts_label_set_point() {
    let analysis = analyze(
        "index_id = label.new(bar_index, high, \"index\")\ntime_id = label.new(time, high, \"time\", xloc=xloc.bar_time)\nfirst = chart.point.from_index(bar_index + 1, low)\nsecond = chart.point.from_time(time + 60000, close)\nlabel.set_point(index_id, first)\ntime_id.set_point(second)\nplot(close)\n",
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
            .any(|feature| feature.feature == "label.set_point"),
        "{:?}",
        analysis.compatibility.supported
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn rejects_unsupported_label_set_yloc_values() {
    let analysis = analyze(
        "id = label.new(bar_index, high, \"High\")\nlabel.set_yloc(id, \"yloc.middle\")\nplot(close)\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.message.contains("yloc.abovebar")),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn accepts_label_getter_methods() {
    let analysis = analyze(
        "id = label.new(bar_index, high, \"High\")\nplot(label.get_x(id))\nplot(label.get_y(id))\nplot(str.length(label.get_text(id)))\nplot(label.get_x(na))\n",
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
            .any(|feature| feature.feature == "label.get_text")
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn rejects_label_side_effects_inside_functions() {
    let analysis = analyze(
        "change(price) =>\n    id = label.new(bar_index, price, \"High\")\n    copy = label.copy(id)\n    label.set_xloc(copy, time, xloc.bar_time)\n    label.set_yloc(copy, yloc.abovebar)\n    label.delete(id)\n    price\nplot(change(close))\n",
    );

    assert!(
        analysis
            .compatibility
            .unsupported
            .iter()
            .any(|feature| feature.feature == "function_side_effect"),
        "{:?}",
        analysis.compatibility.unsupported
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_unimplemented_label_methods() {
    let analysis = analyze("label.set_text_wrap(na, na)\nplot(close)\n");

    assert!(
        analysis
            .compatibility
            .unsupported
            .iter()
            .any(|feature| feature.feature == "label.set_text_wrap"),
        "{:?}",
        analysis.compatibility.unsupported
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn accepts_drawing_object_method_syntax() {
    let analysis = analyze(
        "//@version=6\nlabel_id = label.new(bar_index, high, \"start\")\nline_id = line.new(bar_index, low, bar_index + 1, high)\nbox_id = box.new(bar_index, high, bar_index + 1, low)\ntable_id = table.new(position.top_right, 1, 1)\nlabel_id.set_text(\"method\")\nlabel_id.set_xy(bar_index, close)\nlabel_id.set_point(chart.point.from_index(bar_index + 1, low))\nline_id.set_xy1(bar_index, low)\nline_id.set_color(color.green)\nbox_id.set_lefttop(bar_index, high)\nbox_id.set_xloc(bar_index - 1, bar_index + 1, xloc.bar_index)\ntable_id.cell(0, 0, \"A\")\ntable_id.set_bgcolor(color.green)\nplot(str.length(label_id.get_text()))\nplot(line_id.get_x1())\nplot(box_id.get_right())\nplot(close)\n",
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
            .any(|feature| feature.feature == "label.set_text")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "line.set_xy1")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "box.set_xloc")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "table.cell")
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn rejects_unsupported_drawing_object_method_syntax() {
    let analysis = analyze("id = label.new(bar_index, high, \"start\")\nid.set_text_wrap(na)\n");

    assert!(
        analysis
            .compatibility
            .unsupported
            .iter()
            .any(|feature| feature.feature == "label.set_text_wrap"),
        "{:?}",
        analysis.compatibility.unsupported
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_drawing_object_method_side_effects_inside_functions() {
    let analysis = analyze(
        "change(price) =>\n    id = label.new(bar_index, price, \"start\")\n    id.set_text(\"method\")\n    price\nplot(change(close))\n",
    );

    assert!(
        analysis
            .compatibility
            .unsupported
            .iter()
            .any(|feature| feature.feature == "function_side_effect"),
        "{:?}",
        analysis.compatibility.unsupported
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn accepts_minimal_line_new() {
    let analysis = analyze(
        "id = line.new(bar_index - 1, low, bar_index, high)\nother = line.new(x1=0, y1=open, x2=bar_index, y2=close)\nstyled = line.new(x1=bar_index, y1=low, x2=bar_index + 1, y2=high, xloc=xloc.bar_index, extend=extend.right, color=color.green, style=line.style_dashed, width=2, force_overlay=false)\ntime_line = line.new(x1=time, y1=low, x2=time + 60000, y2=high, xloc=xloc.bar_time)\nextend_left = line.new(bar_index, low, bar_index + 1, high, extend=extend.left)\nextend_both = line.new(bar_index, low, bar_index + 1, high, extend=extend.both)\nextend_none = line.new(bar_index, low, bar_index + 1, high, extend=extend.none)\nstyle_solid = line.new(bar_index, low, bar_index + 1, high, style=line.style_solid)\nstyle_dotted = line.new(bar_index, low, bar_index + 1, high, style=line.style_dotted)\narrow_left = line.new(bar_index, low, bar_index + 1, high, style=line.style_arrow_left)\narrow_right = line.new(bar_index, low, bar_index + 1, high, style=line.style_arrow_right)\narrow_both = line.new(bar_index, low, bar_index + 1, high, style=line.style_arrow_both)\ncopy = line.copy(id)\nline.set_x1(id, bar_index)\nline.set_y1(id, low)\nline.set_xy1(id, bar_index, open)\nline.set_x2(id, bar_index)\nline.set_y2(id, high)\nline.set_xy2(id, bar_index, close)\nline.set_xloc(id, bar_index - 2, bar_index + 2, xloc.bar_index)\nline.set_xloc(time_line, time, time + 60000, xloc.bar_time)\nline.set_color(id, color.green)\nline.set_width(id, 2)\nline.set_style(id, line.style_solid)\nline.set_style(id, line.style_dotted)\nline.set_style(id, line.style_dashed)\nline.set_style(id, line.style_arrow_left)\nline.set_style(id, line.style_arrow_right)\nline.set_style(id, line.style_arrow_both)\nline.set_extend(id, extend.right)\nline.set_extend(id, extend.left)\nline.set_extend(id, extend.both)\nline.set_extend(id, extend.none)\nplot(line.get_price(copy, bar_index))\nplot(line.get_x1(copy))\nplot(line.get_y1(copy))\nplot(line.get_x2(copy))\nplot(line.get_y2(copy))\nline.delete(na)\nline.delete(id)\nplot(close)\n",
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
            .any(|feature| feature.feature == "line.new")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "line.copy")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "line.set_xloc")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "line.get_price")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "line.get_x1")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "line.get_y1")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "line.get_x2")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "line.get_y2")
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_line_new_chart_point_overload() {
    let analysis = analyze(
        "first = chart.point.from_index(bar_index, low)\nsecond = chart.point.from_index(bar_index + 1, high)\nid = line.new(first, second, extend=extend.right, color=color.green, style=line.style_dotted, width=2)\ntime_first = chart.point.from_time(time, low)\ntime_second = chart.point.from_time(time + 60000, high)\ntime_id = line.new(first_point=time_first, second_point=time_second, xloc=xloc.bar_time, style=line.style_dashed)\nplot(line.get_x1(id) + line.get_x1(time_id))\n",
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
            .any(|feature| feature.feature == "line.new")
    );
}

#[test]
fn accepts_line_point_setters() {
    let analysis = analyze(
        "id = line.new(bar_index, low, bar_index + 1, high)\nfirst = chart.point.from_index(bar_index - 1, open)\nsecond = chart.point.from_index(bar_index + 2, close)\nline.set_first_point(id, first)\nid.set_second_point(second)\ntime_id = line.new(x1=time, y1=low, x2=time + 60000, y2=high, xloc=xloc.bar_time)\ntime_first = chart.point.from_time(time - 60000, open)\ntime_second = chart.point.from_time(time + 120000, close)\nline.set_first_point(time_id, time_first)\ntime_id.set_second_point(time_second)\nplot(line.get_x1(id) + line.get_x2(time_id))\n",
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
            .any(|feature| feature.feature == "line.set_first_point")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "line.set_second_point")
    );
}

#[test]
fn accepts_minimal_linefill_new() {
    let analysis = analyze(
        "upper = line.new(bar_index, high, bar_index + 1, high)\nlower = line.new(bar_index, low, bar_index + 1, low)\nfill = linefill.new(upper, lower, color.new(color.green, 80))\nlinefill.set_color(fill, color.red)\nfill.set_color(color.blue)\nlinefill.set_color(na, color.yellow)\nfirst = linefill.get_line1(fill)\nsecond = fill.get_line2()\nall_fills = linefill.all\nfirst_fill = array.get(all_fills, 0)\nmissing_first = linefill.get_line1(na)\nmissing = linefill.new(na, lower, color.red)\nlinefill.delete(na)\nlinefill.delete(missing)\nlinefill.delete(fill)\nplot(line.get_x1(first) + line.get_x2(second) + line.get_x1(linefill.get_line1(first_fill)) + array.size(all_fills) + nz(line.get_x1(missing_first), 0))\n",
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
            .any(|feature| feature.feature == "linefill.new")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "linefill.set_color")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "linefill.get_line1")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "linefill.get_line2")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "linefill.all")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "linefill.delete")
    );
}

#[test]
fn rejects_unimplemented_label_point_methods() {
    let analysis = analyze("label.set_text_wrap(na, na)\nplot(close)\n");

    assert!(
        analysis
            .compatibility
            .unsupported
            .iter()
            .any(|feature| feature.feature == "label.set_text_wrap"),
        "{:?}",
        analysis.compatibility.unsupported
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn accepts_line_set_xloc_bar_time() {
    let analysis = analyze(
        "id = line.new(bar_index, low, bar_index + 1, high)\nline.set_xloc(id, time, time + 60000, xloc.bar_time)\nplot(close)\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn rejects_invalid_line_new_options() {
    let analysis = analyze(
        "id = line.new(x1=bar_index, y1=low, x2=bar_index, y2=high, xloc=xloc.bar_time, style=\"line.style_unknown\")\nplot(close)\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_VALUE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_line_side_effects_inside_functions() {
    let analysis = analyze(
        "change(price) =>\n    id = line.new(bar_index - 1, price, bar_index, price)\n    copy = line.copy(id)\n    line.set_xy1(copy, bar_index, low)\n    line.delete(id)\n    price\nplot(change(close))\n",
    );

    assert!(
        analysis
            .compatibility
            .unsupported
            .iter()
            .any(|feature| feature.feature == "function_side_effect"),
        "{:?}",
        analysis.compatibility.unsupported
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn accepts_minimal_box_new() {
    let analysis = analyze(
        "//@version=6\nid = box.new(bar_index, high, bar_index, low)\nother = box.new(left=0, top=open, right=bar_index, bottom=close)\nstyled = box.new(left=bar_index, top=high, right=bar_index + 1, bottom=low, border_color=color.white, border_width=2, border_style=line.style_dashed, extend=extend.right, xloc=xloc.bar_index, bgcolor=color.green, text=\"box text\", text_size=size.small, text_color=color.white, text_halign=text.align_left, text_valign=text.align_top, text_wrap=text.wrap_auto, text_font_family=font.family_monospace, force_overlay=false, text_formatting=text.format_bold + text.format_italic)\ntime_box = box.new(left=time, top=high, right=time + 60000, bottom=low, xloc=xloc.bar_time)\nborder_solid = box.new(left=bar_index, top=high, right=bar_index + 1, bottom=low, border_style=line.style_solid)\nborder_dotted = box.new(left=bar_index, top=high, right=bar_index + 1, bottom=low, border_style=line.style_dotted)\nextend_left = box.new(left=bar_index, top=high, right=bar_index + 1, bottom=low, extend=extend.left)\nextend_both = box.new(left=bar_index, top=high, right=bar_index + 1, bottom=low, extend=extend.both)\nextend_none = box.new(left=bar_index, top=high, right=bar_index + 1, bottom=low, extend=extend.none)\ncopy = box.copy(id)\nbox.set_left(id, bar_index)\nbox.set_top(id, high)\nbox.set_right(id, bar_index)\nbox.set_bottom(id, low)\nbox.set_lefttop(id, bar_index, close)\nbox.set_rightbottom(id, bar_index, open)\nbox.set_bgcolor(id, color.green)\nbox.set_border_color(id, color.white)\nbox.set_border_width(id, 2)\nbox.set_border_style(id, line.style_solid)\nbox.set_border_style(id, line.style_dotted)\nbox.set_border_style(id, line.style_dashed)\nbox.set_extend(id, extend.right)\nbox.set_extend(id, extend.left)\nbox.set_extend(id, extend.both)\nbox.set_extend(id, extend.none)\nbox.set_xloc(id, bar_index - 2, bar_index + 2, xloc.bar_index)\nbox.set_xloc(time_box, time, time + 60000, xloc.bar_time)\nbox.set_text(id, \"box text\")\nbox.set_text_color(id, color.white)\nbox.set_text_size(id, size.small)\nbox.set_text_halign(id, text.align_left)\nbox.set_text_valign(id, text.align_top)\nbox.set_text_wrap(id, text.wrap_auto)\nbox.set_text_font_family(id, font.family_monospace)\nbox.set_text_formatting(id, text.format_bold + text.format_italic)\nbox.set_text_formatting(na, text.format_italic)\nbox.delete(na)\nbox.delete(id)\nplot(box.get_top(copy))\nplot(box.get_bottom(copy))\nplot(box.get_left(copy))\nplot(box.get_right(copy))\nplot(close)\n",
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
            .any(|feature| feature.feature == "box.new")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "box.copy")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "box.get_top")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "box.get_bottom")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "box.get_left")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "box.get_right")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "box.set_extend")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "box.set_xloc")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "box.set_text")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "box.set_text_color")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "box.set_text_size")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "box.set_text_halign")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "box.set_text_valign")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "box.set_text_wrap")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "box.set_text_font_family")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "box.set_text_formatting")
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_box_new_chart_point_overload() {
    let analysis = analyze(
        "top_left = chart.point.now(high)\nbottom_right = chart.point.from_index(bar_index + 1, low)\nid = box.new(top_left, bottom_right, color.purple, 2, bgcolor=color.green)\ntime_top_left = chart.point.from_time(time, high)\ntime_bottom_right = chart.point.from_time(time + 60000, low)\ntime_id = box.new(top_left=time_top_left, bottom_right=time_bottom_right, xloc=xloc.bar_time, border_style=line.style_dotted, text=\"time box\")\nempty = box.new(na, na, na, na, color.white, 1, xloc=xloc.bar_time)\nmissing = box.new(top_left=na, bottom_right=time_bottom_right, xloc=xloc.bar_time)\nplot(box.get_left(id) + box.get_right(time_id) + nz(box.get_left(empty), 0) + nz(box.get_left(missing), 0))\n",
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
            .any(|feature| feature.feature == "box.new")
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn accepts_box_point_setters() {
    let analysis = analyze(
        "id = box.new(bar_index, high, bar_index + 1, low)\ntop_left = chart.point.from_index(bar_index - 1, open)\nbottom_right = chart.point.from_index(bar_index + 2, close)\nbox.set_top_left_point(id, top_left)\nid.set_bottom_right_point(bottom_right)\ntime_id = box.new(left=time, top=high, right=time + 60000, bottom=low, xloc=xloc.bar_time)\ntime_top_left = chart.point.from_time(time - 60000, open)\ntime_bottom_right = chart.point.from_time(time + 120000, close)\nbox.set_top_left_point(time_id, time_top_left)\ntime_id.set_bottom_right_point(time_bottom_right)\nplot(box.get_left(id) + box.get_right(time_id))\n",
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
            .any(|feature| feature.feature == "box.set_top_left_point")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "box.set_bottom_right_point")
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn rejects_box_arrow_border_styles() {
    let analysis = analyze(
        "created = box.new(bar_index, high, bar_index + 1, low, border_style=line.style_arrow_left)\nbox.set_border_style(created, line.style_arrow_right)\nplot(close)\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_VALUE"
                && diagnostic.message.contains("line.style_solid")
                && diagnostic.message.contains("line.style_dotted")
                && diagnostic.message.contains("line.style_dashed")),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_invalid_box_text_formatting() {
    let analysis = analyze(
        "//@version=6\nid = box.new(bar_index, high, bar_index, low)\nbox.set_text_formatting(id, text.format_bold + 4)\nplot(close)\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_VALUE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn accepts_box_new_int_text_size() {
    let analysis = analyze(
        "//@version=6\nid = box.new(bar_index, high, bar_index, low, text_size=19)\nplot(close)\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn rejects_invalid_box_new_text_size() {
    let analysis = analyze(
        "id = box.new(bar_index, high, bar_index, low, text_size=\"size.bad\")\nplot(close)\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_VALUE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_box_new_float_text_size() {
    let analysis =
        analyze("id = box.new(bar_index, high, bar_index, low, text_size=19.5)\nplot(close)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn accepts_box_set_int_text_size() {
    let analysis = analyze(
        "//@version=6\nid = box.new(bar_index, high, bar_index, low)\nbox.set_text_size(id, 19)\nplot(close)\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn rejects_invalid_box_set_text_size() {
    let analysis = analyze(
        "id = box.new(bar_index, high, bar_index, low)\nbox.set_text_size(id, \"size.bad\")\nplot(close)\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_VALUE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_box_set_float_text_size() {
    let analysis = analyze(
        "id = box.new(bar_index, high, bar_index, low)\nbox.set_text_size(id, 19.5)\nplot(close)\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn accepts_box_set_xloc_bar_time() {
    let analysis = analyze(
        "//@version=6\nid = box.new(bar_index, high, bar_index + 1, low)\nbox.set_xloc(id, time, time + 60000, xloc.bar_time)\nplot(close)\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn rejects_invalid_box_new_options() {
    let analysis = analyze(
        "//@version=6\nid = box.new(left=bar_index, top=high, right=bar_index, bottom=low, xloc=xloc.bar_time, text_formatting=text.format_bold + 4)\nplot(close)\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_VALUE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_box_side_effects_inside_functions() {
    let analysis = analyze(
        "change(price) =>\n    id = box.new(bar_index, price, bar_index, low)\n    copy = box.copy(id)\n    box.set_lefttop(copy, bar_index, high)\n    box.delete(id)\n    price\nplot(change(close))\n",
    );

    assert!(
        analysis
            .compatibility
            .unsupported
            .iter()
            .any(|feature| feature.feature == "function_side_effect"),
        "{:?}",
        analysis.compatibility.unsupported
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn accepts_minimal_table_new_and_cell() {
    let analysis = analyze(
        "//@version=6\nid = table.new(position.top_right, 2, 2, bgcolor=color.gray, frame_color=color.black, frame_width=2, border_color=color.white, border_width=1)\ntop_left = table.new(position.top_left, 1, 1)\ntop_center = table.new(position.top_center, 1, 1)\nmiddle_left = table.new(position.middle_left, 1, 1)\nmiddle_center = table.new(position.middle_center, 1, 1)\nmiddle_right = table.new(position.middle_right, 1, 1)\nbottom_left = table.new(position.bottom_left, 1, 1)\nbottom_center = table.new(position.bottom_center, 1, 1)\nbottom_right = table.new(position.bottom_right, 1, 1)\ntable.cell(id, 0, 0, \"A\")\ntable.cell(id, column=1, row=0, text=\"B\", bgcolor=color.green, text_color=color.white, tooltip=\"initial\", text_font_family=font.family_monospace, text_formatting=text.format_bold)\ntable.cell_set_text(id, 1, 0, \"B2\")\ntable.cell_set_bgcolor(id, 1, 0, color.red)\ntable.cell_set_text_color(id, 1, 0, color.blue)\ntable.cell_set_width(id, 1, 0, 25)\ntable.cell_set_height(id, 1, 0, 40)\ntable.cell_set_text_size(id, 1, 0, size.small)\ntable.cell_set_text_halign(id, 1, 0, text.align_left)\ntable.cell_set_text_valign(id, 1, 0, text.align_top)\ntable.cell_set_text_wrap(id, 1, 0, text.wrap_auto)\ntable.cell_set_tooltip(id, 1, 0, \"updated\")\ntable.cell_set_text_font_family(id, 1, 0, font.family_default)\ntable.cell_set_text_formatting(id, 1, 0, text.format_bold + text.format_italic)\ntable.merge_cells(id, 0, 0, 1, 0)\ntable.set_position(id, position.bottom_right)\ntable.set_bgcolor(id, color.yellow)\ntable.set_frame_color(id, color.black)\ntable.set_frame_width(id, 3)\ntable.set_border_color(id, color.white)\ntable.set_border_width(id, 4)\ntable.clear(id, 0, 0, 1, 1)\ntable.set_position(na, position.top_left)\ntable.set_bgcolor(na, color.red)\ntable.set_frame_color(na, color.blue)\ntable.set_frame_width(na, 2)\ntable.set_border_color(na, color.green)\ntable.set_border_width(na, 5)\ntable.cell_set_text(na, 0, 1, \"noop\")\ntable.cell_set_bgcolor(na, 0, 1, color.red)\ntable.cell_set_text_color(na, 0, 1, color.blue)\ntable.cell_set_width(na, 0, 1, 25)\ntable.cell_set_height(na, 0, 1, 40)\ntable.cell_set_text_size(na, 0, 1, size.small)\ntable.cell_set_text_halign(na, 0, 1, text.align_left)\ntable.cell_set_text_valign(na, 0, 1, text.align_top)\ntable.cell_set_text_wrap(na, 0, 1, text.wrap_none)\ntable.cell_set_tooltip(na, 0, 1, \"noop\")\ntable.cell_set_text_font_family(na, 0, 1, font.family_monospace)\ntable.cell_set_text_formatting(na, 0, 1, text.format_italic)\ntable.cell(na, 0, 1, \"noop\")\ntable.merge_cells(na, 0, 0, 0, 0)\ntable.clear(na, 0, 0, 0, 0)\ntable.delete(na)\ntable.delete(id)\nplot(close)\n",
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
            .any(|feature| feature.feature == "table.new")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "table.set_position")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "table.set_bgcolor")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "table.set_frame_color")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "table.set_frame_width")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "table.set_border_color")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "table.set_border_width")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "table.cell_set_text")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "table.cell_set_bgcolor")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "table.cell_set_text_color")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "table.cell_set_width")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "table.cell_set_height")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "table.cell_set_text_size")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "table.cell_set_text_halign")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "table.cell_set_text_valign")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "table.cell_set_text_wrap")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "table.merge_cells")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "table.cell_set_tooltip")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "table.cell_set_text_font_family")
    );
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "table.cell_set_text_formatting")
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn rejects_invalid_table_text_wrap() {
    let analysis = analyze(
        "id = table.new(position.top_right, 1, 1)\ntable.cell(id, 0, 0, \"A\")\ntable.cell_set_text_wrap(id, 0, 0, \"text.wrap_bad\")\nplot(close)\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_VALUE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn accepts_table_cell_int_text_size() {
    let analysis = analyze(
        "//@version=6\nid = table.new(position.top_right, 1, 1)\ntable.cell(id, 0, 0, \"A\", text_size=19)\nplot(close)\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn rejects_invalid_table_cell_text_size() {
    let analysis = analyze(
        "id = table.new(position.top_right, 1, 1)\ntable.cell(id, 0, 0, \"A\", text_size=\"size.bad\")\nplot(close)\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_VALUE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_table_cell_float_text_size() {
    let analysis = analyze(
        "id = table.new(position.top_right, 1, 1)\ntable.cell(id, 0, 0, \"A\", text_size=19.5)\nplot(close)\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn accepts_table_cell_set_int_text_size() {
    let analysis = analyze(
        "//@version=6\nid = table.new(position.top_right, 1, 1)\ntable.cell(id, 0, 0, \"A\")\ntable.cell_set_text_size(id, 0, 0, 19)\nplot(close)\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn rejects_invalid_table_cell_set_text_size() {
    let analysis = analyze(
        "id = table.new(position.top_right, 1, 1)\ntable.cell(id, 0, 0, \"A\")\ntable.cell_set_text_size(id, 0, 0, \"size.bad\")\nplot(close)\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_VALUE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_table_cell_set_float_text_size() {
    let analysis = analyze(
        "id = table.new(position.top_right, 1, 1)\ntable.cell(id, 0, 0, \"A\")\ntable.cell_set_text_size(id, 0, 0, 19.5)\nplot(close)\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_invalid_table_text_formatting() {
    let analysis = analyze(
        "//@version=6\nid = table.new(position.top_right, 1, 1)\ntable.cell(id, 0, 0, \"A\", text_formatting=text.format_bold + 4)\nplot(close)\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_VALUE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn accepts_input_history_offset() {
    let analysis = analyze("len = input.int(1, \"Length\")\nx = close[len]\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(analysis.hir.is_some());
}

#[test]
fn constant_expression_history_offset_lowers_to_static_requirement() {
    let analysis = analyze("plot(close[1 + 1])\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
}

#[test]
fn named_const_history_offset_lowers_to_static_requirement() {
    let analysis = analyze("length = 1 + 1\nplot(close[length])\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
}

#[test]
fn multiplicative_constant_history_offset_lowers_to_static_requirement() {
    let analysis = analyze("plot(close[1 * 2])\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
}

#[test]
fn modulo_constant_history_offset_lowers_to_static_requirement() {
    let analysis = analyze("plot(close[5 % 3])\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
}

#[test]
fn ternary_constant_history_offset_lowers_to_static_requirement() {
    let analysis = analyze("plot(close[false ? 1 : 2])\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
}

#[test]
fn boolean_expression_ternary_history_offset_lowers_to_static_requirement() {
    let analysis = analyze("plot(close[(true and false) ? 1 : 2])\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
}

#[test]
fn bool_ternary_condition_history_offset_lowers_to_static_requirement() {
    let analysis = analyze("plot(close[((true ? true : false) ? 2 : 1)])\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
}

#[test]
fn comparison_ternary_history_offset_lowers_to_static_requirement() {
    let analysis = analyze("plot(close[(1 + 1 == 2) ? 2 : 1])\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
}

#[test]
fn division_comparison_ternary_history_offset_lowers_to_static_requirement() {
    let analysis = analyze("plot(close[(4 / 2 == 2) ? 2 : 1])\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
}

#[test]
fn string_comparison_ternary_history_offset_lowers_to_static_requirement() {
    let analysis = analyze("plot(close[(\"A\" == \"A\") ? 2 : 1])\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
}

#[test]
fn named_string_constant_value_comparison_history_offset_lowers_to_static_requirement() {
    let analysis = analyze("plot(close[(adjustment.none == \"none\") ? 2 : 1])\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
}

#[test]
fn color_comparison_ternary_history_offset_lowers_to_static_requirement() {
    let analysis = analyze("plot(close[(color.red == color.red) ? 2 : 1])\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
}

#[test]
fn color_value_ternary_comparison_history_offset_lowers_to_static_requirement() {
    let analysis =
        analyze("plot(close[((true ? color.red : color.green) == color.red) ? 2 : 1])\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
}

#[test]
fn named_numeric_comparison_ternary_history_offset_lowers_to_static_requirement() {
    let analysis = analyze("plot(close[(math.pi > 3) ? 2 : 1])\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.history.max_constant_offset, 2);
    assert!(!hir.history.has_dynamic_offsets);
}

#[test]
fn accepts_indicator_max_bars_back() {
    let analysis = analyze("indicator(\"Demo\", max_bars_back=10)\nplot(close[bar_index])\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.max_bars_back, Some(10));
}

#[test]
fn accepts_indicator_max_bars_back_constant_expression() {
    let analysis = analyze("indicator(\"Demo\", max_bars_back=8 + 2)\nplot(close[bar_index])\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.max_bars_back, Some(10));
}

#[test]
fn accepts_indicator_max_bars_back_named_const() {
    let analysis = analyze(
        "length = 8 + 2\nindicator(\"Demo\", max_bars_back=length)\nplot(close[bar_index])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.max_bars_back, Some(10));
}

#[test]
fn accepts_indicator_max_bars_back_alias_named_const() {
    let analysis = analyze(
        "base = 8\nlength = base + 2\nindicator(\"Demo\", max_bars_back=length)\nplot(close[bar_index])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.max_bars_back, Some(10));
}

#[test]
fn accepts_indicator_max_bars_back_multiplicative_constant_expression() {
    let analysis = analyze("indicator(\"Demo\", max_bars_back=5 * 2)\nplot(close[bar_index])\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.max_bars_back, Some(10));
}

#[test]
fn accepts_strategy_max_bars_back() {
    let analysis = analyze("strategy(\"Demo\", max_bars_back=10)\nplot(close[bar_index])\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.max_bars_back, Some(10));
}

#[test]
fn accepts_strategy_max_bars_back_constant_expression() {
    let analysis = analyze("strategy(\"Demo\", max_bars_back=12 - 2)\nplot(close[bar_index])\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.max_bars_back, Some(10));
}

#[test]
fn accepts_strategy_max_bars_back_alias_named_const() {
    let analysis = analyze(
        "base = 8\nlength = base + 2\nstrategy(\"Demo\", max_bars_back=length)\nplot(close[bar_index])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.max_bars_back, Some(10));
}

#[test]
fn accepts_indicator_max_bars_back_udf_constant_length() {
    let analysis = analyze(
        "length() =>\n    base = 8\n    base + 2\nindicator(\"Demo\", max_bars_back=length())\nplot(close[bar_index])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.max_bars_back, Some(10));
}

#[test]
fn accepts_indicator_max_bars_back_imported_udf_constant_length() {
    let analysis = analyze_with_library(
        "import user/lib/1 as lib\nindicator(\"Demo\", max_bars_back=lib.length())\nplot(close[bar_index])\n",
        "library(\"lib\")\nexport length() =>\n    base = 8\n    base + 2\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.max_bars_back, Some(10));
}

#[test]
fn accepts_strategy_max_bars_back_imported_udf_constant_length() {
    let analysis = analyze_with_library(
        "import user/lib/1 as lib\nstrategy(\"Demo\", max_bars_back=lib.length())\nplot(close[bar_index])\n",
        "library(\"lib\")\nexport length() =>\n    base = 8\n    base + 2\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.max_bars_back, Some(10));
}

#[test]
fn accepts_strategy_numeric_metadata_constant_expressions() {
    let analysis = analyze(
        r#"strategy("Demo", initial_capital=50000 * 2, default_qty_type=strategy.cash, default_qty_value=120 - 20, commission_type=strategy.commission.cash_per_order, commission_value=0.5 + 1, slippage=50 * 2, backtest_fill_limits_assumption=125 - 25, margin_long=10 * 5, margin_short=25 + 25, pyramiding=1 + 1)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let settings = hir.strategy_settings;
    assert_eq!(settings.initial_capital, 100000.0);
    assert_eq!(
        settings.default_qty,
        Some(pine_ir::StrategyDefaultQuantity::Cash(100.0))
    );
    assert_eq!(
        settings.commission,
        Some(pine_ir::StrategyCommission::CashPerOrder(1.5))
    );
    assert_eq!(settings.slippage_ticks, 100.0);
    assert_eq!(settings.backtest_fill_limit_ticks, 100.0);
    assert_eq!(settings.margin_long.value_percent, 50.0);
    assert!(settings.margin_long.explicit);
    assert_eq!(settings.margin_short.value_percent, 50.0);
    assert!(settings.margin_short.explicit);
    assert_eq!(settings.pyramiding_limit, 2);
}

#[test]
fn accepts_strategy_numeric_metadata_division_and_modulo_constant_expressions() {
    let analysis = analyze(
        r#"strategy("Demo", initial_capital=200000 / 2, slippage=205 % 105, pyramiding=5 % 3)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let settings = hir.strategy_settings;
    assert_eq!(settings.initial_capital, 100000.0);
    assert_eq!(settings.slippage_ticks, 100.0);
    assert_eq!(settings.pyramiding_limit, 2);
}

#[test]
fn accepts_strategy_numeric_metadata_ternary_constant_expression() {
    let analysis = analyze(
        r#"strategy("Demo", initial_capital=true ? 100000 : 0, slippage=false ? 0 : 100, pyramiding=true ? 2 : 0)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let settings = hir.strategy_settings;
    assert_eq!(settings.initial_capital, 100000.0);
    assert_eq!(settings.slippage_ticks, 100.0);
    assert_eq!(settings.pyramiding_limit, 2);
}

#[test]
fn accepts_strategy_numeric_metadata_boolean_expression_ternary_constant() {
    let analysis = analyze(
        "strategy(\"Demo\", initial_capital=(not false) ? 100000 : 0, slippage=(true or false) ? 100 : -1)\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let settings = hir.strategy_settings;
    assert_eq!(settings.initial_capital, 100000.0);
    assert_eq!(settings.slippage_ticks, 100.0);
}

#[test]
fn accepts_strategy_numeric_metadata_bool_ternary_condition_constant() {
    let analysis = analyze(
        "strategy(\"Demo\", initial_capital=(true ? true : false) ? 100000 : 0, slippage=(false ? false : true) ? 100 : -1)\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let settings = hir.strategy_settings;
    assert_eq!(settings.initial_capital, 100000.0);
    assert_eq!(settings.slippage_ticks, 100.0);
}

#[test]
fn accepts_strategy_numeric_metadata_comparison_ternary_constant() {
    let analysis = analyze(
        "strategy(\"Demo\", initial_capital=(1 + 1 == 2) ? 100000 : 0, slippage=(2 > 1) ? 100 : -1)\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let settings = hir.strategy_settings;
    assert_eq!(settings.initial_capital, 100000.0);
    assert_eq!(settings.slippage_ticks, 100.0);
}

#[test]
fn accepts_strategy_numeric_metadata_named_numeric_constants() {
    let analysis = analyze(
        "strategy(\"Demo\", initial_capital=math.pi * 1000, slippage=(math.e > 2) ? 100 : -1)\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let settings = hir.strategy_settings;
    assert!((settings.initial_capital - std::f64::consts::PI * 1000.0).abs() < 0.000_000_1);
    assert_eq!(settings.slippage_ticks, 100.0);
}

#[test]
fn accepts_strategy_numeric_metadata_named_const_aliases() {
    let analysis = analyze(
        r#"capital_base = 50000
capital = capital_base * 2
qty_base = 40
qty = qty_base + 10
fee_base = 0.25
fee = fee_base * 2
slip_base = 100
slip = (slip_base > 0) ? slip_base : -1
limit_ticks = slip % 60
margin = qty
pyramid_base = 1
pyramid = pyramid_base + 1
strategy("Demo", initial_capital=capital, default_qty_type=strategy.cash, default_qty_value=qty, commission_type=strategy.commission.cash_per_order, commission_value=fee, slippage=slip, backtest_fill_limits_assumption=limit_ticks, margin_long=margin, margin_short=margin, pyramiding=pyramid)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let settings = hir.strategy_settings;
    assert_eq!(settings.initial_capital, 100000.0);
    assert_eq!(
        settings.default_qty,
        Some(pine_ir::StrategyDefaultQuantity::Cash(50.0))
    );
    assert_eq!(
        settings.commission,
        Some(pine_ir::StrategyCommission::CashPerOrder(0.5))
    );
    assert_eq!(settings.slippage_ticks, 100.0);
    assert_eq!(settings.backtest_fill_limit_ticks, 40.0);
    assert_eq!(settings.margin_long.value_percent, 50.0);
    assert!(settings.margin_long.explicit);
    assert_eq!(settings.margin_short.value_percent, 50.0);
    assert!(settings.margin_short.explicit);
    assert_eq!(settings.pyramiding_limit, 2);
}

#[test]
fn accepts_strategy_string_metadata_ternary_constant() {
    let analysis =
        analyze("strategy(\"Demo\", close_entries_rule=(1 + 1 == 2) ? \"ANY\" : \"FIFO\")\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(
        hir.strategy_settings.close_entries_rule,
        pine_ir::StrategyCloseEntriesRule::Any
    );
}

#[test]
fn accepts_strategy_string_metadata_named_const_alias() {
    let analysis = analyze(
        "rule_base = \"ANY\"\nrule = rule_base\nstrategy(\"Demo\", close_entries_rule=rule)\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(
        hir.strategy_settings.close_entries_rule,
        pine_ir::StrategyCloseEntriesRule::Any
    );
}

#[test]
fn accepts_strategy_string_metadata_string_comparison_ternary_constant() {
    let analysis =
        analyze("strategy(\"Demo\", close_entries_rule=(\"A\" != \"B\") ? \"ANY\" : \"FIFO\")\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(
        hir.strategy_settings.close_entries_rule,
        pine_ir::StrategyCloseEntriesRule::Any
    );
}

#[test]
fn rejects_invalid_strategy_numeric_metadata_constant_expression_value() {
    let analysis = analyze("strategy(\"Demo\", slippage=1 - 2)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_VALUE"
                && diagnostic.message
                    == "`strategy` argument `slippage` must be a non-negative integer"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_invalid_strategy_numeric_metadata_named_const_alias_value() {
    let analysis =
        analyze("ticks_base = -1\nticks = ticks_base\nstrategy(\"Demo\", slippage=ticks)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_VALUE"
                && diagnostic.message
                    == "`strategy` argument `slippage` must be a non-negative integer"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn accepts_max_bars_back_function_for_series_symbol() {
    let analysis =
        analyze("indicator(\"Demo\")\nmax_bars_back(close, 10)\nplot(close[bar_index])\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let close_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "close")
        .and_then(|symbol| symbol.series_id)
        .expect("close should have a series id");
    assert!(
        hir.series_max_bars_back
            .iter()
            .any(|value| { value.series_id == close_series && value.max_bars_back == 10 }),
        "{:?}",
        hir.series_max_bars_back
    );
}

#[test]
fn accepts_max_bars_back_function_constant_expression_length() {
    let analysis =
        analyze("indicator(\"Demo\")\nmax_bars_back(close, 8 + 2)\nplot(close[bar_index])\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let close_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "close")
        .and_then(|symbol| symbol.series_id)
        .expect("close should have a series id");
    assert!(
        hir.series_max_bars_back
            .iter()
            .any(|value| { value.series_id == close_series && value.max_bars_back == 10 }),
        "{:?}",
        hir.series_max_bars_back
    );
}

#[test]
fn accepts_max_bars_back_function_named_const_length() {
    let analysis = analyze(
        "indicator(\"Demo\")\nlength = 8 + 2\nmax_bars_back(close, length)\nplot(close[bar_index])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let close_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "close")
        .and_then(|symbol| symbol.series_id)
        .expect("close should have a series id");
    assert!(
        hir.series_max_bars_back
            .iter()
            .any(|value| { value.series_id == close_series && value.max_bars_back == 10 }),
        "{:?}",
        hir.series_max_bars_back
    );
}

#[test]
fn accepts_max_bars_back_function_alias_named_const_length() {
    let analysis = analyze(
        "indicator(\"Demo\")\nbase = 8\nlength = base + 2\nmax_bars_back(close, length)\nplot(close[bar_index])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let close_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "close")
        .and_then(|symbol| symbol.series_id)
        .expect("close should have a series id");
    assert!(
        hir.series_max_bars_back
            .iter()
            .any(|value| { value.series_id == close_series && value.max_bars_back == 10 }),
        "{:?}",
        hir.series_max_bars_back
    );
}

#[test]
fn accepts_max_bars_back_function_multiplicative_constant_expression_length() {
    let analysis =
        analyze("indicator(\"Demo\")\nmax_bars_back(close, 5 * 2)\nplot(close[bar_index])\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let close_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "close")
        .and_then(|symbol| symbol.series_id)
        .expect("close should have a series id");
    assert!(
        hir.series_max_bars_back
            .iter()
            .any(|value| { value.series_id == close_series && value.max_bars_back == 10 }),
        "{:?}",
        hir.series_max_bars_back
    );
}

#[test]
fn accepts_max_bars_back_function_ternary_constant_expression_length() {
    let analysis = analyze(
        "indicator(\"Demo\")\nmax_bars_back(close, false ? 5 : 10)\nplot(close[bar_index])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let close_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "close")
        .and_then(|symbol| symbol.series_id)
        .expect("close should have a series id");
    assert!(
        hir.series_max_bars_back
            .iter()
            .any(|value| { value.series_id == close_series && value.max_bars_back == 10 }),
        "{:?}",
        hir.series_max_bars_back
    );
}

#[test]
fn accepts_max_bars_back_function_boolean_expression_ternary_length() {
    let analysis = analyze(
        "indicator(\"Demo\")\nmax_bars_back(close, (false or true) ? 10 : 5)\nplot(close[bar_index])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let close_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "close")
        .and_then(|symbol| symbol.series_id)
        .expect("close should have a series id");
    assert!(
        hir.series_max_bars_back
            .iter()
            .any(|value| { value.series_id == close_series && value.max_bars_back == 10 }),
        "{:?}",
        hir.series_max_bars_back
    );
}

#[test]
fn accepts_max_bars_back_function_bool_ternary_condition_length() {
    let analysis = analyze(
        "indicator(\"Demo\")\nmax_bars_back(close, (true ? true : false) ? 10 : 5)\nplot(close[bar_index])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let close_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "close")
        .and_then(|symbol| symbol.series_id)
        .expect("close should have a series id");
    assert!(
        hir.series_max_bars_back
            .iter()
            .any(|value| { value.series_id == close_series && value.max_bars_back == 10 }),
        "{:?}",
        hir.series_max_bars_back
    );
}

#[test]
fn accepts_max_bars_back_function_comparison_ternary_length() {
    let analysis = analyze(
        "indicator(\"Demo\")\nmax_bars_back(close, (1 + 1 == 2) ? 10 : 5)\nplot(close[bar_index])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let close_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "close")
        .and_then(|symbol| symbol.series_id)
        .expect("close should have a series id");
    assert!(
        hir.series_max_bars_back
            .iter()
            .any(|value| { value.series_id == close_series && value.max_bars_back == 10 }),
        "{:?}",
        hir.series_max_bars_back
    );
}

#[test]
fn accepts_max_bars_back_function_string_comparison_ternary_length() {
    let analysis = analyze(
        "indicator(\"Demo\")\nmax_bars_back(close, (\"A\" == \"A\") ? 10 : 5)\nplot(close[bar_index])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let close_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "close")
        .and_then(|symbol| symbol.series_id)
        .expect("close should have a series id");
    assert!(
        hir.series_max_bars_back
            .iter()
            .any(|value| { value.series_id == close_series && value.max_bars_back == 10 }),
        "{:?}",
        hir.series_max_bars_back
    );
}

#[test]
fn accepts_max_bars_back_function_string_value_ternary_comparison_length() {
    let analysis = analyze(
        "indicator(\"Demo\")\nmax_bars_back(close, ((true ? \"A\" : \"B\") == \"A\") ? 10 : 5)\nplot(close[bar_index])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let close_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "close")
        .and_then(|symbol| symbol.series_id)
        .expect("close should have a series id");
    assert!(
        hir.series_max_bars_back
            .iter()
            .any(|value| { value.series_id == close_series && value.max_bars_back == 10 }),
        "{:?}",
        hir.series_max_bars_back
    );
}

#[test]
fn accepts_max_bars_back_function_named_string_constant_value_comparison_length() {
    let analysis = analyze(
        "indicator(\"Demo\")\nmax_bars_back(close, (adjustment.none == \"none\") ? 10 : 5)\nplot(close[bar_index])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let close_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "close")
        .and_then(|symbol| symbol.series_id)
        .expect("close should have a series id");
    assert!(
        hir.series_max_bars_back
            .iter()
            .any(|value| { value.series_id == close_series && value.max_bars_back == 10 }),
        "{:?}",
        hir.series_max_bars_back
    );
}

#[test]
fn accepts_max_bars_back_function_color_comparison_ternary_length() {
    let analysis = analyze(
        "indicator(\"Demo\")\nmax_bars_back(close, (color.green != color.red) ? 10 : 5)\nplot(close[bar_index])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let close_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "close")
        .and_then(|symbol| symbol.series_id)
        .expect("close should have a series id");
    assert!(
        hir.series_max_bars_back
            .iter()
            .any(|value| { value.series_id == close_series && value.max_bars_back == 10 }),
        "{:?}",
        hir.series_max_bars_back
    );
}

#[test]
fn accepts_max_bars_back_function_color_value_ternary_comparison_length() {
    let analysis = analyze(
        "indicator(\"Demo\")\nmax_bars_back(close, ((true ? color.red : color.green) == color.red) ? 10 : 5)\nplot(close[bar_index])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let close_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "close")
        .and_then(|symbol| symbol.series_id)
        .expect("close should have a series id");
    assert!(
        hir.series_max_bars_back
            .iter()
            .any(|value| { value.series_id == close_series && value.max_bars_back == 10 }),
        "{:?}",
        hir.series_max_bars_back
    );
}

#[test]
fn accepts_max_bars_back_function_named_numeric_comparison_ternary_length() {
    let analysis = analyze(
        "indicator(\"Demo\")\nmax_bars_back(close, (math.pi > 3) ? 10 : 5)\nplot(close[bar_index])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let close_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "close")
        .and_then(|symbol| symbol.series_id)
        .expect("close should have a series id");
    assert!(
        hir.series_max_bars_back
            .iter()
            .any(|value| { value.series_id == close_series && value.max_bars_back == 10 }),
        "{:?}",
        hir.series_max_bars_back
    );
}

#[test]
fn accepts_max_bars_back_function_named_int_constant_expression_length() {
    let analysis = analyze(
        "indicator(\"Demo\")\nmax_bars_back(close, dayofweek.sunday + 9)\nplot(close[bar_index])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let close_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "close")
        .and_then(|symbol| symbol.series_id)
        .expect("close should have a series id");
    assert!(
        hir.series_max_bars_back
            .iter()
            .any(|value| { value.series_id == close_series && value.max_bars_back == 10 }),
        "{:?}",
        hir.series_max_bars_back
    );
}

#[test]
fn accepts_max_bars_back_function_division_comparison_ternary_length() {
    let analysis = analyze(
        "indicator(\"Demo\")\nmax_bars_back(close, (4 / 2 == 2) ? 10 : 5)\nplot(close[bar_index])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let close_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "close")
        .and_then(|symbol| symbol.series_id)
        .expect("close should have a series id");
    assert!(
        hir.series_max_bars_back
            .iter()
            .any(|value| { value.series_id == close_series && value.max_bars_back == 10 }),
        "{:?}",
        hir.series_max_bars_back
    );
}

#[test]
fn accepts_max_bars_back_function_modulo_constant_expression_length() {
    let analysis =
        analyze("indicator(\"Demo\")\nmax_bars_back(close, 205 % 195)\nplot(close[bar_index])\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let close_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "close")
        .and_then(|symbol| symbol.series_id)
        .expect("close should have a series id");
    assert!(
        hir.series_max_bars_back
            .iter()
            .any(|value| { value.series_id == close_series && value.max_bars_back == 10 }),
        "{:?}",
        hir.series_max_bars_back
    );
}

#[test]
fn accepts_max_bars_back_function_udf_constant_length() {
    let analysis = analyze(
        "indicator(\"Demo\")\nlength() => 10\nmax_bars_back(close, length())\nplot(close[bar_index])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let close_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "close")
        .and_then(|symbol| symbol.series_id)
        .expect("close should have a series id");
    assert!(
        hir.series_max_bars_back
            .iter()
            .any(|value| { value.series_id == close_series && value.max_bars_back == 10 }),
        "{:?}",
        hir.series_max_bars_back
    );
}

#[test]
fn accepts_max_bars_back_function_imported_udf_constant_length() {
    let analysis = analyze_with_library(
        "import user/lib/1 as lib\nindicator(\"Demo\")\nmax_bars_back(close, lib.length())\nplot(close[bar_index])\n",
        "library(\"lib\")\nexport length() => 10\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let close_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "close")
        .and_then(|symbol| symbol.series_id)
        .expect("close should have a series id");
    assert!(
        hir.series_max_bars_back
            .iter()
            .any(|value| { value.series_id == close_series && value.max_bars_back == 10 }),
        "{:?}",
        hir.series_max_bars_back
    );
}

#[test]
fn accepts_max_bars_back_function_udf_local_constant_length() {
    let analysis = analyze(
        "indicator(\"Demo\")\nlength() =>\n    value = 10\n    value\nmax_bars_back(close, length())\nplot(close[bar_index])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let close_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "close")
        .and_then(|symbol| symbol.series_id)
        .expect("close should have a series id");
    assert!(
        hir.series_max_bars_back
            .iter()
            .any(|value| { value.series_id == close_series && value.max_bars_back == 10 }),
        "{:?}",
        hir.series_max_bars_back
    );
}

#[test]
fn accepts_max_bars_back_function_udf_local_constant_length_after_expr_statement() {
    let analysis = analyze(
        "indicator(\"Demo\")\nlength() =>\n    value = 10\n    close\n    value\nmax_bars_back(close, length())\nplot(close[bar_index])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let close_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "close")
        .and_then(|symbol| symbol.series_id)
        .expect("close should have a series id");
    assert!(
        hir.series_max_bars_back
            .iter()
            .any(|value| { value.series_id == close_series && value.max_bars_back == 10 }),
        "{:?}",
        hir.series_max_bars_back
    );
}

#[test]
fn accepts_max_bars_back_function_udf_constant_argument_length() {
    let analysis = analyze(
        "indicator(\"Demo\")\nlength(value) => value\nmax_bars_back(close, length(10))\nplot(close[bar_index])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let close_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "close")
        .and_then(|symbol| symbol.series_id)
        .expect("close should have a series id");
    assert!(
        hir.series_max_bars_back
            .iter()
            .any(|value| { value.series_id == close_series && value.max_bars_back == 10 }),
        "{:?}",
        hir.series_max_bars_back
    );
}

#[test]
fn accepts_max_bars_back_function_udf_derived_constant_argument_length() {
    let analysis = analyze(
        "indicator(\"Demo\")\nlength(value) => value + 1\nmax_bars_back(close, length(9))\nplot(close[bar_index])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let close_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "close")
        .and_then(|symbol| symbol.series_id)
        .expect("close should have a series id");
    assert!(
        hir.series_max_bars_back
            .iter()
            .any(|value| { value.series_id == close_series && value.max_bars_back == 10 }),
        "{:?}",
        hir.series_max_bars_back
    );
}

#[test]
fn accepts_max_bars_back_function_for_declared_series_variable() {
    let analysis =
        analyze("indicator(\"Demo\")\nsrc = close\nmax_bars_back(src, 10)\nplot(src[bar_index])\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let src_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    assert!(
        hir.series_max_bars_back
            .iter()
            .any(|value| { value.series_id == src_series && value.max_bars_back == 10 }),
        "{:?}",
        hir.series_max_bars_back
    );
}

#[test]
fn accepts_max_bars_back_function_for_derived_series_variable() {
    let analysis = analyze(
        "indicator(\"Demo\")\nsrc = close + 100\nmax_bars_back(src, 10)\nplot(src[bar_index])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let src_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    assert!(
        hir.series_max_bars_back
            .iter()
            .any(|value| { value.series_id == src_series && value.max_bars_back == 10 }),
        "{:?}",
        hir.series_max_bars_back
    );
}

#[test]
fn accepts_max_bars_back_function_for_series_alias_chain() {
    let analysis = analyze(
        "indicator(\"Demo\")\nsrc = close + 100\nalias = src\nmax_bars_back(alias, 10)\nplot(alias[bar_index])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let alias_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "alias")
        .and_then(|symbol| symbol.series_id)
        .expect("alias should have a series id");
    assert!(
        hir.series_max_bars_back
            .iter()
            .any(|value| { value.series_id == alias_series && value.max_bars_back == 10 }),
        "{:?}",
        hir.series_max_bars_back
    );
}

#[test]
fn max_bars_back_function_uses_largest_bound_for_repeated_series() {
    let analysis = analyze(
        "indicator(\"Demo\")\nsrc = close\nmax_bars_back(src, 2)\nmax_bars_back(src, 10)\nplot(src[bar_index])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let src_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    assert!(
        hir.series_max_bars_back
            .iter()
            .any(|value| { value.series_id == src_series && value.max_bars_back == 10 }),
        "{:?}",
        hir.series_max_bars_back
    );
}

#[test]
fn accepts_max_bars_back_function_named_reordered_args() {
    let analysis = analyze(
        "indicator(\"Demo\")\nsrc = close\nmax_bars_back(num=10, source=src)\nplot(src[bar_index])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let src_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    assert!(
        hir.series_max_bars_back
            .iter()
            .any(|value| { value.series_id == src_series && value.max_bars_back == 10 }),
        "{:?}",
        hir.series_max_bars_back
    );
}

#[test]
fn accepts_max_bars_back_function_in_block() {
    let analysis = analyze(
        "indicator(\"Demo\")\nsrc = close\nif close > open\n    max_bars_back(src, 10)\nplot(src[bar_index])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let src_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    assert!(
        hir.series_max_bars_back
            .iter()
            .any(|value| { value.series_id == src_series && value.max_bars_back == 10 }),
        "{:?}",
        hir.series_max_bars_back
    );
}

#[test]
fn accepts_max_bars_back_function_in_block_with_local_const_length() {
    let analysis = analyze(
        "indicator(\"Demo\")\nsrc = close\nif close > open\n    base = 5\n    length = base + 5\n    max_bars_back(src, length)\nplot(src[bar_index])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let src_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    assert!(
        hir.series_max_bars_back
            .iter()
            .any(|value| { value.series_id == src_series && value.max_bars_back == 10 }),
        "{:?}",
        hir.series_max_bars_back
    );
}

#[test]
fn accepts_max_bars_back_function_in_switch_block_with_local_const_length() {
    let analysis = analyze(
        "indicator(\"Demo\")\nsrc = close\nswitch\n    close > open =>\n        base = 5\n        length = base + 5\n        max_bars_back(src, length)\n        1\n    => 0\nplot(src[bar_index])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let src_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    assert!(
        hir.series_max_bars_back
            .iter()
            .any(|value| { value.series_id == src_series && value.max_bars_back == 10 }),
        "{:?}",
        hir.series_max_bars_back
    );
}

#[test]
fn accepts_max_bars_back_function_in_expression_block_with_local_const_length() {
    let analysis = analyze(
        "indicator(\"Demo\")\nsrc = close\nbranch = switch\n    close > open =>\n        base = 5\n        length = base + 5\n        max_bars_back(src, length)\n        1\n    => 0\nplot(src[bar_index] + branch)\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let src_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    assert!(
        hir.series_max_bars_back
            .iter()
            .any(|value| { value.series_id == src_series && value.max_bars_back == 10 }),
        "{:?}",
        hir.series_max_bars_back
    );
}

#[test]
fn accepts_max_bars_back_function_in_tuple_switch_expression_block_with_local_const_length() {
    let analysis = analyze(
        "indicator(\"Demo\")\nsrc = close\n[branch] = switch\n    close > open =>\n        base = 5\n        length = base + 5\n        max_bars_back(src, length)\n        [1]\n    => [0]\nplot(src[bar_index] + branch)\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let src_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    assert!(
        hir.series_max_bars_back
            .iter()
            .any(|value| { value.series_id == src_series && value.max_bars_back == 10 }),
        "{:?}",
        hir.series_max_bars_back
    );
}

#[test]
fn accepts_max_bars_back_function_in_if_expression_block_with_local_const_length() {
    let analysis = analyze(
        "indicator(\"Demo\")\nsrc = close\nbranch = if close > open\n    base = 5\n    length = base + 5\n    max_bars_back(src, length)\n    1\nelse\n    0\nplot(src[bar_index] + branch)\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let src_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    assert!(
        hir.series_max_bars_back
            .iter()
            .any(|value| { value.series_id == src_series && value.max_bars_back == 10 }),
        "{:?}",
        hir.series_max_bars_back
    );
}

#[test]
fn accepts_max_bars_back_function_in_tuple_if_expression_block_with_local_const_length() {
    let analysis = analyze(
        "indicator(\"Demo\")\nsrc = close\n[branch] = if close > open\n    base = 5\n    length = base + 5\n    max_bars_back(src, length)\n    [1]\nelse\n    [0]\nplot(src[bar_index] + branch)\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let src_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    assert!(
        hir.series_max_bars_back
            .iter()
            .any(|value| { value.series_id == src_series && value.max_bars_back == 10 }),
        "{:?}",
        hir.series_max_bars_back
    );
}

#[test]
fn accepts_max_bars_back_function_in_call_argument_block_with_local_const_length() {
    let analysis = analyze(
        "indicator(\"Demo\")\nsrc = close\nplot(switch\n    close > open =>\n        base = 5\n        length = base + 5\n        max_bars_back(src, length)\n        src[bar_index]\n    => src[bar_index]\n)\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let src_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    assert!(
        hir.series_max_bars_back
            .iter()
            .any(|value| { value.series_id == src_series && value.max_bars_back == 10 }),
        "{:?}",
        hir.series_max_bars_back
    );
}

#[test]
fn accepts_max_bars_back_function_in_block_result_with_local_const_length() {
    let analysis = analyze(
        "indicator(\"Demo\")\nsrc = close\nplot(switch\n    close > open =>\n        base = 5\n        length = base + 5\n        switch\n            bar_index >= 0 =>\n                max_bars_back(src, length)\n                src[bar_index]\n            => src[bar_index]\n    => src[bar_index]\n)\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let src_series = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "src")
        .and_then(|symbol| symbol.series_id)
        .expect("src should have a series id");
    assert!(
        hir.series_max_bars_back
            .iter()
            .any(|value| { value.series_id == src_series && value.max_bars_back == 10 }),
        "{:?}",
        hir.series_max_bars_back
    );
}

#[test]
fn accepts_indicator_max_polylines_count_named_arg() {
    let analysis = analyze("indicator(\"Demo\", max_polylines_count=75)\nplot(close)\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.drawing_settings.max_polylines_count, Some(75));
}

#[test]
fn accepts_indicator_max_lines_count_named_arg() {
    let analysis = analyze("indicator(\"Demo\", max_lines_count=75)\nplot(close)\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.drawing_settings.max_lines_count, Some(75));
}

#[test]
fn accepts_indicator_max_labels_count_named_arg() {
    let analysis = analyze("indicator(\"Demo\", max_labels_count=75)\nplot(close)\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.drawing_settings.max_labels_count, Some(75));
}

#[test]
fn accepts_indicator_max_labels_count_named_const_arg() {
    let analysis = analyze(
        "base = 75\ncount = base\nindicator(\"Demo\", max_labels_count=count)\nplot(close)\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.drawing_settings.max_labels_count, Some(75));
}

#[test]
fn accepts_indicator_max_boxes_count_named_arg() {
    let analysis = analyze("indicator(\"Demo\", max_boxes_count=75)\nplot(close)\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.drawing_settings.max_boxes_count, Some(75));
}

#[test]
fn rejects_indicator_max_labels_count_positional_subset() {
    let analysis =
        analyze("indicator(\"Demo\", \"D\", true, format.price, 2, scale.right, 10, 75)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_NAME"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_indicator_max_boxes_count_positional_subset() {
    let analysis =
        analyze("indicator(\"Demo\", \"D\", true, format.price, 2, scale.right, 10, 75, 75)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_NAME"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_indicator_max_lines_count_positional_subset() {
    let analysis =
        analyze("indicator(\"Demo\", \"D\", true, format.price, 2, scale.right, 10, 75, 75, 75)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_NAME"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_indicator_max_polylines_count_positional_subset() {
    let analysis = analyze(
        "indicator(\"Demo\", \"D\", true, format.price, 2, scale.right, 10, 75, 75, 75, 75)\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_NAME"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_indicator_max_labels_count_out_of_range() {
    let analysis = analyze("indicator(\"Demo\", max_labels_count=501)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_VALUE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_indicator_max_labels_count_named_const_out_of_range() {
    let analysis =
        analyze("base = 501\ncount = base\nindicator(\"Demo\", max_labels_count=count)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_VALUE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_indicator_max_lines_count_out_of_range() {
    let analysis = analyze("indicator(\"Demo\", max_lines_count=501)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_VALUE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_indicator_max_boxes_count_out_of_range() {
    let analysis = analyze("indicator(\"Demo\", max_boxes_count=501)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_VALUE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_indicator_max_polylines_count_out_of_range() {
    let analysis = analyze("indicator(\"Demo\", max_polylines_count=101)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_VALUE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn accepts_indicator_metadata_positional_order() {
    let analysis = analyze(
        "indicator(\"Demo\", \"D\", true, format.price, 2, scale.right, 10)\nplot(close[bar_index])\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("hir");
    assert_eq!(hir.max_bars_back, Some(10));
}

#[test]
fn rejects_negative_indicator_max_bars_back() {
    let analysis = analyze("indicator(\"Demo\", max_bars_back=-1)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_VALUE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_negative_strategy_max_bars_back() {
    let analysis = analyze("strategy(\"Demo\", max_bars_back=-1)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_VALUE"
                && diagnostic.message.contains("max_bars_back")),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_overflow_indicator_max_bars_back() {
    let analysis = analyze("indicator(\"Demo\", max_bars_back=4294967296)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_VALUE"
                && diagnostic.message.contains("32-bit unsigned history bound")),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_overflow_strategy_max_bars_back() {
    let analysis = analyze("strategy(\"Demo\", max_bars_back=4294967296)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_VALUE"
                && diagnostic.message.contains("32-bit unsigned history bound")),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_negative_max_bars_back_function_length() {
    let analysis = analyze("indicator(\"Demo\")\nmax_bars_back(close, -1)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_VALUE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_negative_max_bars_back_function_named_const_length() {
    let analysis = analyze("indicator(\"Demo\")\nlength = -1\nmax_bars_back(close, length)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_VALUE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_overflow_max_bars_back_function_length() {
    let analysis = analyze("indicator(\"Demo\")\nmax_bars_back(close, 4294967296)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_VALUE"
                && diagnostic.message.contains("32-bit unsigned history bound")),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_overflow_max_bars_back_function_named_const_length() {
    let analysis =
        analyze("indicator(\"Demo\")\nlength = 4294967296\nmax_bars_back(close, length)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_VALUE"
                && diagnostic.message.contains("32-bit unsigned history bound")),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn accepts_max_bars_back_function_expression_source() {
    let analysis = analyze("indicator(\"Demo\")\nmax_bars_back(close + open, 10)\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    assert_eq!(hir.series_max_bars_back.len(), 1);
    assert_eq!(hir.series_max_bars_back[0].max_bars_back, 10);
}

#[test]
fn rejects_max_bars_back_function_non_series_identifier_source() {
    let analysis = analyze("indicator(\"Demo\")\nlen = input.int(2)\nmax_bars_back(len, 10)\n");

    assert!(
        analysis.diagnostics.iter().any(|diagnostic| {
            diagnostic.code == "E_CALL_ARG_TYPE"
                && diagnostic.message
                    == "`max_bars_back` argument `source` expects series numeric, got input int"
        }),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_max_bars_back_function_non_numeric_series_identifier_source() {
    let analysis = analyze("indicator(\"Demo\")\nflag = close > open\nmax_bars_back(flag, 10)\n");

    assert!(
        analysis.diagnostics.iter().any(|diagnostic| {
            diagnostic.code == "E_CALL_ARG_TYPE"
                && diagnostic.message
                    == "`max_bars_back` argument `source` expects series numeric, got series bool"
        }),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_max_bars_back_function_as_declaration_value() {
    let analysis = analyze("indicator(\"Demo\")\nvalue = max_bars_back(close, 10)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_DECL_VALUE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_non_const_indicator_max_bars_back() {
    let analysis = analyze("indicator(\"Demo\", max_bars_back=bar_index)\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn simple_int_params_accept_input_int_expressions() {
    let analysis = analyze("length = input.int(2, \"Length\") + 1\nplot(ta.sma(close, length))\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn typed_simple_params_preserve_initializer_qualifiers() {
    let analysis = analyze(
        "int literal_length = 2\nint input_length = input.int(3, \"Length\")\nstring chart_tf = timeframe.period\nplot(ta.sma(close, literal_length))\nplot(ta.ema(close, input_length))\nplot(timeframe.in_seconds(chart_tf))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let literal_length = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "literal_length")
        .expect("literal_length symbol");
    let input_length = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "input_length")
        .expect("input_length symbol");
    let chart_tf = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "chart_tf")
        .expect("chart_tf symbol");

    assert_eq!(
        literal_length.pine_type,
        PineType::new(Qualifier::Const, ValueKind::Int)
    );
    assert_eq!(
        input_length.pine_type,
        PineType::new(Qualifier::Input, ValueKind::Int)
    );
    assert_eq!(
        chart_tf.pine_type,
        PineType::new(Qualifier::Simple, ValueKind::String)
    );
}

#[test]
fn typed_scalar_reassignment_promotes_qualifier_before_simple_param_check() {
    let analysis = analyze("int length = 2\nlength := bar_index\nplot(ta.ema(close, length))\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn statement_if_series_condition_reassignment_promotes_qualifier_before_simple_param_check() {
    let analysis = analyze(
        "length = input.int(2, \"Length\")\nselected = length\nif close > open\n    selected := length\nplot(ta.ema(close, selected))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn statement_if_const_false_reassignment_preserves_simple_param_qualifier() {
    let analysis = analyze(
        "length = input.int(2, \"Length\")\nif false\n    length := bar_index\nplot(ta.ema(close, length))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let length = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "length")
        .expect("length symbol");
    assert_eq!(
        length.pine_type,
        PineType::new(Qualifier::Input, ValueKind::Int)
    );
}

#[test]
fn statement_if_const_true_reassignment_promotes_before_simple_param_check() {
    let analysis = analyze(
        "length = input.int(2, \"Length\")\nif true\n    length := bar_index\nplot(ta.ema(close, length))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn if_expression_series_condition_reassignment_promotes_qualifier_before_simple_param_check() {
    let analysis = analyze(
        "length = input.int(2, \"Length\")\nselected = length\n_ = if close > open\n    selected := length\n    1\nelse\n    0\nplot(ta.ema(close, selected))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn if_expression_const_false_reassignment_preserves_simple_param_qualifier() {
    let analysis = analyze(
        "length = input.int(2, \"Length\")\n_ = if false\n    length := bar_index\n    1\nelse\n    0\nplot(ta.ema(close, length))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let length = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "length")
        .expect("length symbol");
    assert_eq!(
        length.pine_type,
        PineType::new(Qualifier::Input, ValueKind::Int)
    );
}

#[test]
fn if_expression_const_true_reassignment_promotes_before_simple_param_check() {
    let analysis = analyze(
        "length = input.int(2, \"Length\")\n_ = if true\n    length := bar_index\n    1\nelse\n    0\nplot(ta.ema(close, length))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn udf_final_if_series_condition_reassignment_promotes_qualifier_before_simple_param_check() {
    let analysis = analyze(
        "checked_length(flag, x) =>\n    local = x\n    if flag\n        local := x\n        ta.ema(close, local)\n    else\n        close\nlength = input.int(2, \"Length\")\nplot(checked_length(close > open, length))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn method_final_if_series_condition_reassignment_promotes_qualifier_before_simple_param_check() {
    let analysis = analyze(
        "type Box\n    int seed\nmethod checked_length(Box this, bool flag, int x) =>\n    local = x\n    if flag\n        local := x\n        ta.ema(close, local)\n    else\n        close\nlength = input.int(2, \"Length\")\nbox = Box.new(1)\nplot(box.checked_length(close > open, length))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn udf_final_if_const_false_reassignment_preserves_simple_param_qualifier() {
    let analysis = analyze(
        "choose_length(flag, x) =>\n    local = x\n    if flag\n        local := bar_index\n        local\n    else\n        local\nlength = input.int(2, \"Length\")\nchosen = choose_length(false, length)\nplot(ta.ema(close, chosen))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let chosen = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "chosen")
        .expect("chosen symbol");
    assert_eq!(
        chosen.pine_type,
        PineType::new(Qualifier::Input, ValueKind::Int)
    );
}

#[test]
fn udf_final_if_const_true_reassignment_promotes_before_simple_param_check() {
    let analysis = analyze(
        "choose_length(flag, x) =>\n    local = x\n    if flag\n        local := bar_index\n        local\n    else\n        local\nlength = input.int(2, \"Length\")\nchosen = choose_length(true, length)\nplot(ta.ema(close, chosen))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn method_final_if_const_false_reassignment_preserves_simple_param_qualifier() {
    let analysis = analyze(
        "type Box\n    int seed\nmethod choose_length(Box this, bool flag, int x) =>\n    local = x\n    if flag\n        local := bar_index\n        local\n    else\n        local\nlength = input.int(2, \"Length\")\nbox = Box.new(1)\nchosen = box.choose_length(false, length)\nplot(ta.ema(close, chosen))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let chosen = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "chosen")
        .expect("chosen symbol");
    assert_eq!(
        chosen.pine_type,
        PineType::new(Qualifier::Input, ValueKind::Int)
    );
}

#[test]
fn method_final_if_const_true_reassignment_promotes_before_simple_param_check() {
    let analysis = analyze(
        "type Box\n    int seed\nmethod choose_length(Box this, bool flag, int x) =>\n    local = x\n    if flag\n        local := bar_index\n        local\n    else\n        local\nlength = input.int(2, \"Length\")\nbox = Box.new(1)\nchosen = box.choose_length(true, length)\nplot(ta.ema(close, chosen))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn udf_final_switch_const_false_reassignment_preserves_simple_param_qualifier() {
    let analysis = analyze(
        "choose_length(flag, x) =>\n    local = x\n    switch\n        flag =>\n            local := bar_index\n            local\n        =>\n            local\nlength = input.int(2, \"Length\")\nchosen = choose_length(false, length)\nplot(ta.ema(close, chosen))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let chosen = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "chosen")
        .expect("chosen symbol");
    assert_eq!(
        chosen.pine_type,
        PineType::new(Qualifier::Input, ValueKind::Int)
    );
}

#[test]
fn udf_final_switch_const_true_reassignment_promotes_before_simple_param_check() {
    let analysis = analyze(
        "choose_length(flag, x) =>\n    local = x\n    switch\n        flag =>\n            local := bar_index\n            local\n        =>\n            local\nlength = input.int(2, \"Length\")\nchosen = choose_length(true, length)\nplot(ta.ema(close, chosen))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn method_final_switch_const_false_reassignment_preserves_simple_param_qualifier() {
    let analysis = analyze(
        "type Box\n    int seed\nmethod choose_length(Box this, bool flag, int x) =>\n    local = x\n    switch\n        flag =>\n            local := bar_index\n            local\n        =>\n            local\nlength = input.int(2, \"Length\")\nbox = Box.new(1)\nchosen = box.choose_length(false, length)\nplot(ta.ema(close, chosen))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let chosen = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "chosen")
        .expect("chosen symbol");
    assert_eq!(
        chosen.pine_type,
        PineType::new(Qualifier::Input, ValueKind::Int)
    );
}

#[test]
fn method_final_switch_const_true_reassignment_promotes_before_simple_param_check() {
    let analysis = analyze(
        "type Box\n    int seed\nmethod choose_length(Box this, bool flag, int x) =>\n    local = x\n    switch\n        flag =>\n            local := bar_index\n            local\n        =>\n            local\nlength = input.int(2, \"Length\")\nbox = Box.new(1)\nchosen = box.choose_length(true, length)\nplot(ta.ema(close, chosen))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn udf_final_selector_switch_const_nonmatching_reassignment_preserves_simple_param_qualifier() {
    let analysis = analyze(
        "choose_length(mode, x) =>\n    local = x\n    switch mode\n        \"dead\" =>\n            local := bar_index\n            local\n        =>\n            local\nlength = input.int(2, \"Length\")\nchosen = choose_length(\"live\", length)\nplot(ta.ema(close, chosen))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let chosen = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "chosen")
        .expect("chosen symbol");
    assert_eq!(
        chosen.pine_type,
        PineType::new(Qualifier::Input, ValueKind::Int)
    );
}

#[test]
fn udf_final_selector_switch_const_matching_reassignment_promotes_before_simple_param_check() {
    let analysis = analyze(
        "choose_length(mode, x) =>\n    local = x\n    switch mode\n        \"live\" =>\n            local := bar_index\n            local\n        =>\n            local\nlength = input.int(2, \"Length\")\nchosen = choose_length(\"live\", length)\nplot(ta.ema(close, chosen))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn method_final_selector_switch_const_nonmatching_reassignment_preserves_simple_param_qualifier() {
    let analysis = analyze(
        "type Box\n    int seed\nmethod choose_length(Box this, string mode, int x) =>\n    local = x\n    switch mode\n        \"dead\" =>\n            local := bar_index\n            local\n        =>\n            local\nlength = input.int(2, \"Length\")\nbox = Box.new(1)\nchosen = box.choose_length(\"live\", length)\nplot(ta.ema(close, chosen))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let chosen = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "chosen")
        .expect("chosen symbol");
    assert_eq!(
        chosen.pine_type,
        PineType::new(Qualifier::Input, ValueKind::Int)
    );
}

#[test]
fn method_final_selector_switch_const_matching_reassignment_promotes_before_simple_param_check() {
    let analysis = analyze(
        "type Box\n    int seed\nmethod choose_length(Box this, string mode, int x) =>\n    local = x\n    switch mode\n        \"live\" =>\n            local := bar_index\n            local\n        =>\n            local\nlength = input.int(2, \"Length\")\nbox = Box.new(1)\nchosen = box.choose_length(\"live\", length)\nplot(ta.ema(close, chosen))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn udf_final_selector_switch_const_numeric_and_color_nonmatching_reassignment_preserves_simple_param_qualifier()
 {
    let analysis = analyze(
        "choose_int_length(mode, x) =>\n    local = x\n    switch mode\n        1 =>\n            local := bar_index\n            local\n        =>\n            local\nchoose_float_length(mode, x) =>\n    local = x\n    switch mode\n        1.5 =>\n            local := bar_index\n            local\n        =>\n            local\nchoose_color_length(mode, x) =>\n    local = x\n    switch mode\n        color.red =>\n            local := bar_index\n            local\n        =>\n            local\nlength = input.int(2, \"Length\")\nint_chosen = choose_int_length(2, length)\nfloat_chosen = choose_float_length(2.5, length)\ncolor_chosen = choose_color_length(color.green, length)\nplot(ta.ema(close, int_chosen))\nplot(ta.ema(close, float_chosen))\nplot(ta.ema(close, color_chosen))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    for name in ["int_chosen", "float_chosen", "color_chosen"] {
        let symbol = hir
            .symbols
            .iter()
            .find(|symbol| symbol.name == name)
            .unwrap_or_else(|| panic!("{name} symbol"));
        assert_eq!(
            symbol.pine_type,
            PineType::new(Qualifier::Input, ValueKind::Int)
        );
    }
}

#[test]
fn udf_final_selector_switch_const_numeric_and_color_matching_reassignment_promotes_before_simple_param_check()
 {
    let analysis = analyze(
        "choose_int_length(mode, x) =>\n    local = x\n    switch mode\n        1 =>\n            local := bar_index\n            local\n        =>\n            local\nchoose_float_length(mode, x) =>\n    local = x\n    switch mode\n        1.5 =>\n            local := bar_index\n            local\n        =>\n            local\nchoose_color_length(mode, x) =>\n    local = x\n    switch mode\n        color.red =>\n            local := bar_index\n            local\n        =>\n            local\nlength = input.int(2, \"Length\")\nint_chosen = choose_int_length(1, length)\nfloat_chosen = choose_float_length(1.5, length)\ncolor_chosen = choose_color_length(color.red, length)\nplot(ta.ema(close, int_chosen))\nplot(ta.ema(close, float_chosen))\nplot(ta.ema(close, color_chosen))\n",
    );

    let call_arg_type_count = analysis
        .diagnostics
        .iter()
        .filter(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE")
        .count();
    assert!(call_arg_type_count >= 3, "{:?}", analysis.diagnostics);
    assert!(analysis.hir.is_none());
}

#[test]
fn method_final_selector_switch_const_numeric_and_color_nonmatching_reassignment_preserves_simple_param_qualifier()
 {
    let analysis = analyze(
        "type Box\n    int seed\nmethod choose_int_length(Box this, int mode, int x) =>\n    local = x\n    switch mode\n        1 =>\n            local := bar_index\n            local\n        =>\n            local\nmethod choose_float_length(Box this, float mode, int x) =>\n    local = x\n    switch mode\n        1.5 =>\n            local := bar_index\n            local\n        =>\n            local\nmethod choose_color_length(Box this, color mode, int x) =>\n    local = x\n    switch mode\n        color.red =>\n            local := bar_index\n            local\n        =>\n            local\nlength = input.int(2, \"Length\")\nbox = Box.new(1)\nint_chosen = box.choose_int_length(2, length)\nfloat_chosen = box.choose_float_length(2.5, length)\ncolor_chosen = box.choose_color_length(color.green, length)\nplot(ta.ema(close, int_chosen))\nplot(ta.ema(close, float_chosen))\nplot(ta.ema(close, color_chosen))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    for name in ["int_chosen", "float_chosen", "color_chosen"] {
        let symbol = hir
            .symbols
            .iter()
            .find(|symbol| symbol.name == name)
            .unwrap_or_else(|| panic!("{name} symbol"));
        assert_eq!(
            symbol.pine_type,
            PineType::new(Qualifier::Input, ValueKind::Int)
        );
    }
}

#[test]
fn method_final_selector_switch_const_numeric_and_color_matching_reassignment_promotes_before_simple_param_check()
 {
    let analysis = analyze(
        "type Box\n    int seed\nmethod choose_int_length(Box this, int mode, int x) =>\n    local = x\n    switch mode\n        1 =>\n            local := bar_index\n            local\n        =>\n            local\nmethod choose_float_length(Box this, float mode, int x) =>\n    local = x\n    switch mode\n        1.5 =>\n            local := bar_index\n            local\n        =>\n            local\nmethod choose_color_length(Box this, color mode, int x) =>\n    local = x\n    switch mode\n        color.red =>\n            local := bar_index\n            local\n        =>\n            local\nlength = input.int(2, \"Length\")\nbox = Box.new(1)\nint_chosen = box.choose_int_length(1, length)\nfloat_chosen = box.choose_float_length(1.5, length)\ncolor_chosen = box.choose_color_length(color.red, length)\nplot(ta.ema(close, int_chosen))\nplot(ta.ema(close, float_chosen))\nplot(ta.ema(close, color_chosen))\n",
    );

    let call_arg_type_count = analysis
        .diagnostics
        .iter()
        .filter(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE")
        .count();
    assert!(call_arg_type_count >= 3, "{:?}", analysis.diagnostics);
    assert!(analysis.hir.is_none());
}

#[test]
fn udf_final_switch_series_condition_reassignment_promotes_qualifier_before_simple_param_check() {
    let analysis = analyze(
        "choose_length(flag, x) =>\n    local = x\n    switch\n        flag =>\n            local := x\n            local\n        =>\n            local\nlength = input.int(2, \"Length\")\nchosen = choose_length(close > open, length)\nplot(ta.ema(close, chosen))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn method_final_switch_series_condition_reassignment_promotes_qualifier_before_simple_param_check()
{
    let analysis = analyze(
        "type Box\n    int seed\nmethod choose_length(Box this, bool flag, int x) =>\n    local = x\n    switch\n        flag =>\n            local := x\n            local\n        =>\n            local\nlength = input.int(2, \"Length\")\nbox = Box.new(1)\nchosen = box.choose_length(close > open, length)\nplot(ta.ema(close, chosen))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn udf_final_selector_switch_series_selector_reassignment_promotes_qualifier_before_simple_param_check()
 {
    let analysis = analyze(
        "choose_length(mode, x) =>\n    local = x\n    switch mode\n        0 =>\n            local := x\n            local\n        =>\n            local\nlength = input.int(2, \"Length\")\nchosen = choose_length(bar_index, length)\nplot(ta.ema(close, chosen))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn method_final_selector_switch_series_selector_reassignment_promotes_qualifier_before_simple_param_check()
 {
    let analysis = analyze(
        "type Box\n    int seed\nmethod choose_length(Box this, int mode, int x) =>\n    local = x\n    switch mode\n        0 =>\n            local := x\n            local\n        =>\n            local\nlength = input.int(2, \"Length\")\nbox = Box.new(1)\nchosen = box.choose_length(bar_index, length)\nplot(ta.ema(close, chosen))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn statement_while_series_condition_reassignment_promotes_qualifier_before_simple_param_check() {
    let analysis = analyze(
        "length = input.int(2, \"Length\")\nselected = length\nwhile close > open\n    selected := length\nplot(ta.ema(close, selected))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn statement_for_series_bound_reassignment_promotes_qualifier_before_simple_param_check() {
    let analysis = analyze(
        "length = input.int(2, \"Length\")\nselected = length\nfor i = 0 to bar_index\n    selected := length\nplot(ta.ema(close, selected))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn statement_for_in_series_iterable_reassignment_promotes_qualifier_before_simple_param_check() {
    let analysis = analyze(
        "array<int> values = na\nlength = input.int(2, \"Length\")\nselected = length\nfor value in values\n    selected := length\nplot(ta.ema(close, selected))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn typed_na_initializer_still_accepts_later_series_reassignment() {
    let analysis = analyze("int count = na\ncount := bar_index\nplot(count)\n");

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
}

#[test]
fn simple_params_accept_udf_returned_input_and_simple_values() {
    let analysis = analyze(
        "inc(x) => x + 1\npass_tf(tf) =>\n    local = tf\n    local\nlength = input.int(2, \"Length\")\nchart_tf = timeframe.period\nplot(ta.sma(close, inc(length)))\nplot(timeframe.in_seconds(pass_tf(chart_tf)))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn tuple_destructuring_preserves_udf_returned_input_and_simple_values() {
    let analysis = analyze(
        "pair(length, tf) => [length, tf]\nlength = input.int(2, \"Length\")\ntf = timeframe.period\n[len, chart_tf] = pair(length, tf)\nplot(ta.sma(close, len))\nplot(timeframe.in_seconds(chart_tf))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let len = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "len")
        .expect("len symbol");
    let chart_tf = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "chart_tf")
        .expect("chart_tf symbol");

    assert_eq!(
        len.pine_type,
        PineType::new(Qualifier::Input, ValueKind::Int)
    );
    assert_eq!(
        chart_tf.pine_type,
        PineType::new(Qualifier::Simple, ValueKind::String)
    );
}

#[test]
fn tuple_destructuring_preserves_user_method_returned_input_and_simple_values() {
    let analysis = analyze(
        "type Box\n    int seed\nmethod pair(Box this, int length, string tf) =>\n    [length, tf]\nbox = Box.new(1)\nlength = input.int(2, \"Length\")\ntf = timeframe.period\n[len, chart_tf] = box.pair(length, tf)\nplot(ta.sma(close, len))\nplot(timeframe.in_seconds(chart_tf))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let len = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "len")
        .expect("len symbol");
    let chart_tf = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "chart_tf")
        .expect("chart_tf symbol");

    assert_eq!(
        len.pine_type,
        PineType::new(Qualifier::Input, ValueKind::Int)
    );
    assert_eq!(
        chart_tf.pine_type,
        PineType::new(Qualifier::Simple, ValueKind::String)
    );
}

#[test]
fn tuple_destructuring_preserves_udf_param_method_returned_input_and_simple_values() {
    let analysis = analyze(
        "type Box\n    int seed\nmethod pair(Box this, int length, string tf) =>\n    [length, tf]\nforward(box, length, tf) => box.pair(length, tf)\nbox = Box.new(1)\nlength = input.int(2, \"Length\")\ntf = timeframe.period\n[len, chart_tf] = forward(box, length, tf)\nplot(ta.sma(close, len))\nplot(timeframe.in_seconds(chart_tf))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let len = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "len")
        .expect("len symbol");
    let chart_tf = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "chart_tf")
        .expect("chart_tf symbol");

    assert_eq!(
        len.pine_type,
        PineType::new(Qualifier::Input, ValueKind::Int)
    );
    assert_eq!(
        chart_tf.pine_type,
        PineType::new(Qualifier::Simple, ValueKind::String)
    );
}

#[test]
fn tuple_destructuring_preserves_udf_final_if_returned_input_and_simple_values() {
    let analysis = analyze(
        "choose_pair(flag, length, tf) =>\n    if flag\n        [length, tf]\n    else\n        [length + 1, tf]\nflag = input.bool(false, \"Flag\")\nlength = input.int(2, \"Length\")\ntf = timeframe.period\n[len, chart_tf] = choose_pair(flag, length, tf)\nplot(ta.sma(close, len))\nplot(timeframe.in_seconds(chart_tf))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let len = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "len")
        .expect("len symbol");
    let chart_tf = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "chart_tf")
        .expect("chart_tf symbol");

    assert_eq!(
        len.pine_type,
        PineType::new(Qualifier::Input, ValueKind::Int)
    );
    assert_eq!(
        chart_tf.pine_type,
        PineType::new(Qualifier::Simple, ValueKind::String)
    );
}

#[test]
fn tuple_destructuring_preserves_if_expression_input_and_simple_values() {
    let analysis = analyze(
        "flag = input.bool(false, \"Flag\")\nlength = input.int(2, \"Length\")\ntf = timeframe.period\n[len, chart_tf] = if flag\n    [length, tf]\nelse\n    [length + 1, tf]\nplot(ta.sma(close, len))\nplot(timeframe.in_seconds(chart_tf))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let len = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "len")
        .expect("len symbol");
    let chart_tf = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "chart_tf")
        .expect("chart_tf symbol");

    assert_eq!(
        len.pine_type,
        PineType::new(Qualifier::Input, ValueKind::Int)
    );
    assert_eq!(
        chart_tf.pine_type,
        PineType::new(Qualifier::Simple, ValueKind::String)
    );
}

#[test]
fn tuple_destructuring_preserves_ternary_input_and_simple_values() {
    let analysis = analyze(
        "flag = input.bool(false, \"Flag\")\nlength = input.int(2, \"Length\")\ntf = timeframe.period\n[len, chart_tf] = flag ? [length, tf] : [length + 1, tf]\nplot(ta.sma(close, len))\nplot(timeframe.in_seconds(chart_tf))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let len = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "len")
        .expect("len symbol");
    let chart_tf = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "chart_tf")
        .expect("chart_tf symbol");

    assert_eq!(
        len.pine_type,
        PineType::new(Qualifier::Input, ValueKind::Int)
    );
    assert_eq!(
        chart_tf.pine_type,
        PineType::new(Qualifier::Simple, ValueKind::String)
    );
}

#[test]
fn tuple_destructuring_preserves_switch_block_final_loop_input_values() {
    let analysis = analyze(
        "flag = input.bool(false, \"Flag\")\nlength = input.int(2, \"Length\")\n[len] = switch\n    flag =>\n        for i = 0 to 0\n            [length]\n    =>\n        for i = 0 to 0\n            [length + 1]\nplot(ta.sma(close, len))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let len = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "len")
        .expect("len symbol");

    assert_eq!(
        len.pine_type,
        PineType::new(Qualifier::Input, ValueKind::Int)
    );
}

#[test]
fn tuple_destructuring_preserves_nested_loop_input_values() {
    let analysis = analyze(
        "length = input.int(2, \"Length\")\n[len] = for outer = 0 to 0\n    for inner = 0 to 0\n        [length]\nplot(ta.sma(close, len))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let len = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "len")
        .expect("len symbol");

    assert_eq!(
        len.pine_type,
        PineType::new(Qualifier::Input, ValueKind::Int)
    );
}

#[test]
fn simple_params_accept_udf_final_if_and_for_returned_input_and_simple_values() {
    let analysis = analyze(
        "choose_length(flag, x) =>\n    if flag\n        local = x\n        local\n    else\n        local = x + 1\n        local\npass_tf(tf) =>\n    for i = 0 to 0\n        local = tf\n        local\nloop_in_length(values, x) =>\n    for value in values\n        local = x\n        local\nchoose_branch_loop_length(flag, values, x) =>\n    if flag\n        for i = 0 to 0\n            x\n    else\n        for value in values\n            x\nchoose_branch_while_length(flag, x) =>\n    if flag\n        while false\n            x\n    else\n        x\nif_expr_loop_length(flag, x) =>\n    if flag\n        for i = 0 to 0\n            x\n    else\n        for i = 0 to 0\n            x + 1\nswitch_block_loop_length(flag, x) =>\n    switch\n        flag =>\n            for i = 0 to 0\n                x\n        =>\n            while false\n                x + 1\nnested_loop_length(values, flag, x) =>\n    for outer = 0 to 0\n        for value in values\n            while flag\n                x\nlength = input.int(2, \"Length\")\nflag = input.bool(false, \"Flag\")\nchart_tf = timeframe.period\nvalues = array.from(1, 2)\nplot(ta.sma(close, choose_length(flag, length)))\nplot(timeframe.in_seconds(pass_tf(chart_tf)))\nplot(ta.sma(close, loop_in_length(values, length)))\nplot(ta.sma(close, choose_branch_loop_length(flag, values, length)))\nplot(ta.sma(close, choose_branch_while_length(flag, length)))\nplot(ta.sma(close, if_expr_loop_length(flag, length)))\nplot(ta.sma(close, switch_block_loop_length(flag, length)))\nplot(ta.sma(close, nested_loop_length(values, flag, length)))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn simple_params_accept_udf_while_returned_input_values() {
    let analysis = analyze(
        "while_length(flag, x) =>\n    while flag\n        x\nlength = input.int(2, \"Length\")\nflag = input.bool(false, \"Flag\")\nplot(ta.sma(close, while_length(flag, length)))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn simple_params_accept_udf_selector_switch_returned_input_values() {
    let analysis = analyze(
        "choose_length(mode, x) =>\n    switch mode\n        \"dead\" =>\n            for i = 0 to bar_index\n                x\n        \"live\" =>\n            x\n        =>\n            bar_index\nlength = input.int(2, \"Length\")\nmode = \"live\"\nchosen = choose_length(mode, length)\nplot(ta.sma(close, chosen))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let chosen = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "chosen")
        .expect("chosen symbol");
    assert_eq!(
        chosen.pine_type,
        PineType::new(Qualifier::Input, ValueKind::Int)
    );
}

#[test]
fn simple_params_accept_user_method_selector_switch_returned_input_values() {
    let analysis = analyze(
        "type Box\n    int seed\nmethod choose_length(Box this, string mode, int x) =>\n    switch mode\n        \"dead\" =>\n            for i = 0 to bar_index\n                x\n        \"live\" =>\n            x\n        =>\n            bar_index\nlength = input.int(2, \"Length\")\nmode = \"live\"\nbox = Box.new(1)\nchosen = box.choose_length(mode, length)\nplot(ta.sma(close, chosen))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let chosen = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "chosen")
        .expect("chosen symbol");
    assert_eq!(
        chosen.pine_type,
        PineType::new(Qualifier::Input, ValueKind::Int)
    );
}

#[test]
fn tuple_destructuring_preserves_udf_selector_switch_returned_input_values() {
    let analysis = analyze(
        "choose_pair(mode, x) =>\n    switch mode\n        \"dead\" =>\n            [bar_index]\n        \"live\" =>\n            [x]\n        =>\n            [bar_index]\nlength = input.int(2, \"Length\")\nmode = \"live\"\n[len] = choose_pair(mode, length)\nplot(ta.sma(close, len))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let len = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "len")
        .expect("len symbol");
    assert_eq!(
        len.pine_type,
        PineType::new(Qualifier::Input, ValueKind::Int)
    );
}

#[test]
fn tuple_destructuring_preserves_user_method_selector_switch_returned_input_values() {
    let analysis = analyze(
        "type Box\n    int seed\nmethod choose_pair(Box this, string mode, int x) =>\n    switch mode\n        \"dead\" =>\n            [bar_index]\n        \"live\" =>\n            [x]\n        =>\n            [bar_index]\nlength = input.int(2, \"Length\")\nmode = \"live\"\nbox = Box.new(1)\n[len] = box.choose_pair(mode, length)\nplot(ta.sma(close, len))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let len = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "len")
        .expect("len symbol");
    assert_eq!(
        len.pine_type,
        PineType::new(Qualifier::Input, ValueKind::Int)
    );
}

#[test]
fn tuple_destructuring_preserves_nested_udf_selector_switch_returned_input_values() {
    let analysis = analyze(
        "choose_pair(mode, x) =>\n    switch mode\n        \"dead\" =>\n            [bar_index]\n        \"live\" =>\n            [x]\n        =>\n            [bar_index]\nforward_pair(mode, x) => choose_pair(mode, x)\nlength = input.int(2, \"Length\")\nmode = \"live\"\n[len] = forward_pair(mode, length)\nplot(ta.sma(close, len))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let len = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "len")
        .expect("len symbol");
    assert_eq!(
        len.pine_type,
        PineType::new(Qualifier::Input, ValueKind::Int)
    );
}

#[test]
fn tuple_destructuring_preserves_nested_user_method_selector_switch_returned_input_values() {
    let analysis = analyze(
        "type Box\n    int seed\nmethod choose_pair(Box this, string mode, int x) =>\n    switch mode\n        \"dead\" =>\n            [bar_index]\n        \"live\" =>\n            [x]\n        =>\n            [bar_index]\nforward_pair(box, mode, x) => box.choose_pair(mode, x)\nlength = input.int(2, \"Length\")\nmode = \"live\"\nbox = Box.new(1)\n[len] = forward_pair(box, mode, length)\nplot(ta.sma(close, len))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let len = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "len")
        .expect("len symbol");
    assert_eq!(
        len.pine_type,
        PineType::new(Qualifier::Input, ValueKind::Int)
    );
}

#[test]
fn simple_int_params_reject_udf_returned_series_int() {
    let analysis = analyze(
        "series_length(x) => x + bar_index\nlength = input.int(2, \"Length\")\nplot(ta.ema(close, series_length(length)))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn tuple_destructuring_rejects_udf_returned_series_int_for_simple_param() {
    let analysis = analyze(
        "series_pair(x) => [x + bar_index]\nlength = input.int(2, \"Length\")\n[len] = series_pair(length)\nplot(ta.ema(close, len))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn tuple_destructuring_rejects_user_method_returned_series_int_for_simple_param() {
    let analysis = analyze(
        "type Box\n    int seed\nmethod series_pair(Box this, int length) =>\n    [length + bar_index]\nbox = Box.new(1)\nlength = input.int(2, \"Length\")\n[len] = box.series_pair(length)\nplot(ta.ema(close, len))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn tuple_destructuring_rejects_udf_param_method_returned_series_int_for_simple_param() {
    let analysis = analyze(
        "type Box\n    int seed\nmethod series_pair(Box this, int length) =>\n    [length + bar_index]\nforward(box, length) => box.series_pair(length)\nbox = Box.new(1)\nlength = input.int(2, \"Length\")\n[len] = forward(box, length)\nplot(ta.ema(close, len))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn tuple_destructuring_rejects_udf_final_if_series_condition_for_simple_param() {
    let analysis = analyze(
        "choose_pair(flag, length) =>\n    if flag\n        [length]\n    else\n        [length + 1]\nlength = input.int(2, \"Length\")\n[len] = choose_pair(close > open, length)\nplot(ta.ema(close, len))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn tuple_destructuring_rejects_if_expression_series_condition_for_simple_param() {
    let analysis = analyze(
        "length = input.int(2, \"Length\")\n[len] = if close > open\n    [length]\nelse\n    [length + 1]\nplot(ta.ema(close, len))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn tuple_destructuring_rejects_ternary_series_condition_for_simple_param() {
    let analysis = analyze(
        "length = input.int(2, \"Length\")\n[len] = close > open ? [length] : [length + 1]\nplot(ta.ema(close, len))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn tuple_destructuring_rejects_switch_block_series_condition_for_simple_param() {
    let analysis = analyze(
        "length = input.int(2, \"Length\")\n[len] = switch\n    close > open =>\n        for i = 0 to 0\n            [length]\n    =>\n        for i = 0 to 0\n            [length + 1]\nplot(ta.ema(close, len))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn switch_expression_series_condition_reassignment_promotes_qualifier_before_simple_param_check() {
    let analysis = analyze(
        "length = input.int(2, \"Length\")\nselected = length\n_ = switch\n    close > open =>\n        selected := length\n        1\n    =>\n        0\nplot(ta.ema(close, selected))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn switch_expression_const_false_reassignment_preserves_simple_param_qualifier() {
    let analysis = analyze(
        "length = input.int(2, \"Length\")\n_ = switch\n    false =>\n        length := bar_index\n        1\n    =>\n        0\nplot(ta.ema(close, length))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let length = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "length")
        .expect("length symbol");
    assert_eq!(
        length.pine_type,
        PineType::new(Qualifier::Input, ValueKind::Int)
    );
}

#[test]
fn switch_expression_const_true_reassignment_promotes_before_simple_param_check() {
    let analysis = analyze(
        "length = input.int(2, \"Length\")\n_ = switch\n    true =>\n        length := bar_index\n        1\n    =>\n        0\nplot(ta.ema(close, length))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn selector_switch_expression_series_selector_reassignment_promotes_qualifier_before_simple_param_check()
 {
    let analysis = analyze(
        "length = input.int(2, \"Length\")\nselected = length\n_ = switch bar_index\n    0 =>\n        selected := length\n        1\n    =>\n        0\nplot(ta.ema(close, selected))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn selector_switch_expression_const_nonmatching_reassignment_preserves_simple_param_qualifier() {
    let analysis = analyze(
        "length = input.int(2, \"Length\")\nmode = \"live\"\n_ = switch mode\n    \"dead\" =>\n        length := bar_index\n        1\n    =>\n        0\nplot(ta.ema(close, length))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let length = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "length")
        .expect("length symbol");
    assert_eq!(
        length.pine_type,
        PineType::new(Qualifier::Input, ValueKind::Int)
    );
}

#[test]
fn selector_switch_expression_const_matching_reassignment_promotes_before_simple_param_check() {
    let analysis = analyze(
        "length = input.int(2, \"Length\")\nmode = \"live\"\n_ = switch mode\n    \"live\" =>\n        length := bar_index\n        1\n    =>\n        0\nplot(ta.ema(close, length))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn statement_switch_series_condition_reassignment_promotes_qualifier_before_simple_param_check() {
    let analysis = analyze(
        "length = input.int(2, \"Length\")\nselected = length\nswitch\n    close > open =>\n        selected := length\nplot(ta.ema(close, selected))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn statement_switch_const_false_reassignment_preserves_simple_param_qualifier() {
    let analysis = analyze(
        "length = input.int(2, \"Length\")\nswitch\n    false =>\n        length := bar_index\nplot(ta.ema(close, length))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let length = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "length")
        .expect("length symbol");
    assert_eq!(
        length.pine_type,
        PineType::new(Qualifier::Input, ValueKind::Int)
    );
}

#[test]
fn statement_switch_const_true_reassignment_promotes_before_simple_param_check() {
    let analysis = analyze(
        "length = input.int(2, \"Length\")\nswitch\n    true =>\n        length := bar_index\nplot(ta.ema(close, length))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn statement_selector_switch_const_nonmatching_reassignment_preserves_simple_param_qualifier() {
    let analysis = analyze(
        "length = input.int(2, \"Length\")\nmode = \"live\"\nswitch mode\n    \"dead\" =>\n        length := bar_index\nplot(ta.ema(close, length))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let length = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "length")
        .expect("length symbol");
    assert_eq!(
        length.pine_type,
        PineType::new(Qualifier::Input, ValueKind::Int)
    );
}

#[test]
fn statement_selector_switch_const_matching_reassignment_promotes_before_simple_param_check() {
    let analysis = analyze(
        "length = input.int(2, \"Length\")\nmode = \"live\"\nswitch mode\n    \"live\" =>\n        length := bar_index\nplot(ta.ema(close, length))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn statement_selector_switch_series_selector_reassignment_promotes_qualifier_before_simple_param_check()
 {
    let analysis = analyze(
        "length = input.int(2, \"Length\")\nselected = length\nswitch bar_index\n    0 =>\n        selected := length\nplot(ta.ema(close, selected))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn tuple_destructuring_rejects_nested_loop_series_bounds_for_simple_param() {
    let analysis = analyze(
        "length = input.int(2, \"Length\")\n[len] = for outer = 0 to 0\n    for inner = 0 to bar_index\n        [length]\nplot(ta.ema(close, len))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn for_expression_series_bound_reassignment_promotes_qualifier_before_simple_param_check() {
    let analysis = analyze(
        "length = input.int(2, \"Length\")\nselected = length\n_ = for i = 0 to bar_index\n    selected := length\n    1\nplot(ta.ema(close, selected))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn for_in_expression_series_iterable_reassignment_promotes_qualifier_before_simple_param_check() {
    let analysis = analyze(
        "array<int> values = na\nlength = input.int(2, \"Length\")\nselected = length\n_ = for value in values\n    selected := length\n    1\nplot(ta.ema(close, selected))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn while_expression_series_condition_reassignment_promotes_qualifier_before_simple_param_check() {
    let analysis = analyze(
        "length = input.int(2, \"Length\")\nselected = length\n_ = while close > open\n    selected := length\n    1\nplot(ta.ema(close, selected))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn simple_int_params_reject_udf_final_for_with_series_bounds() {
    let analysis = analyze(
        "loop_length(limit, x) =>\n    for i = 0 to limit\n        x\nlength = input.int(2, \"Length\")\nplot(ta.ema(close, loop_length(bar_index, length)))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn simple_int_params_reject_udf_final_if_branch_for_with_series_bounds() {
    let analysis = analyze(
        "choose_length(flag, limit, x) =>\n    if flag\n        for i = 0 to limit\n            x\n    else\n        x\nlength = input.int(2, \"Length\")\nplot(ta.ema(close, choose_length(true, bar_index, length)))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn simple_int_params_reject_if_expression_branch_for_with_series_bounds() {
    let analysis = analyze(
        "length = input.int(2, \"Length\")\nselected = if true\n    for i = 0 to bar_index\n        length\nelse\n    length\nplot(ta.ema(close, selected))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn simple_int_params_reject_switch_block_for_with_series_bounds() {
    let analysis = analyze(
        "length = input.int(2, \"Length\")\nselected = switch\n    true =>\n        for i = 0 to bar_index\n            length\n    =>\n        length\nplot(ta.ema(close, selected))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn simple_int_params_reject_loop_expression_body_for_with_series_bounds() {
    let analysis = analyze(
        "length = input.int(2, \"Length\")\nselected = for outer = 0 to 0\n    for inner = 0 to bar_index\n        length\nplot(ta.ema(close, selected))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn simple_int_params_reject_while_expression_body_with_series_condition() {
    let analysis = analyze(
        "length = input.int(2, \"Length\")\nselected = while false\n    while close > open\n        length\nplot(ta.ema(close, selected))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn simple_int_params_reject_udf_for_in_with_series_iterable() {
    let analysis = analyze(
        "loop_length(values, x) =>\n    for value in values\n        x\narray<int> values = na\nlength = input.int(2, \"Length\")\nplot(ta.ema(close, loop_length(values, length)))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn simple_int_params_reject_udf_while_with_series_condition() {
    let analysis = analyze(
        "while_length(flag, x) =>\n    while flag\n        x\nlength = input.int(2, \"Length\")\nplot(ta.ema(close, while_length(close > open, length)))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn udf_final_for_series_bound_reassignment_promotes_qualifier_before_simple_param_check() {
    let analysis = analyze(
        "checked_length(limit, x) =>\n    local = x\n    for i = 0 to limit\n        local := x\n        ta.ema(close, local)\nlength = input.int(2, \"Length\")\nplot(checked_length(bar_index, length))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn method_final_for_series_bound_reassignment_promotes_qualifier_before_simple_param_check() {
    let analysis = analyze(
        "type Box\n    int seed\nmethod checked_length(Box this, int limit, int x) =>\n    local = x\n    for i = 0 to limit\n        local := x\n        ta.ema(close, local)\nlength = input.int(2, \"Length\")\nbox = Box.new(1)\nplot(box.checked_length(bar_index, length))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn udf_final_for_in_series_iterable_reassignment_promotes_qualifier_before_simple_param_check() {
    let analysis = analyze(
        "checked_length(values, x) =>\n    local = x\n    for value in values\n        local := x\n        ta.ema(close, local)\narray<int> values = na\nlength = input.int(2, \"Length\")\nplot(checked_length(values, length))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn method_final_for_in_series_iterable_reassignment_promotes_qualifier_before_simple_param_check() {
    let analysis = analyze(
        "type Box\n    int seed\nmethod checked_length(Box this, array<int> values, int x) =>\n    local = x\n    for value in values\n        local := x\n        ta.ema(close, local)\narray<int> values = na\nlength = input.int(2, \"Length\")\nbox = Box.new(1)\nplot(box.checked_length(values, length))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn udf_final_while_series_condition_reassignment_promotes_qualifier_before_simple_param_check() {
    let analysis = analyze(
        "checked_length(flag, x) =>\n    local = x\n    while flag\n        local := x\n        ta.ema(close, local)\nlength = input.int(2, \"Length\")\nplot(checked_length(close > open, length))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn method_final_while_series_condition_reassignment_promotes_qualifier_before_simple_param_check() {
    let analysis = analyze(
        "type Box\n    int seed\nmethod checked_length(Box this, bool flag, int x) =>\n    local = x\n    while flag\n        local := x\n        ta.ema(close, local)\nlength = input.int(2, \"Length\")\nbox = Box.new(1)\nplot(box.checked_length(close > open, length))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn simple_int_params_reject_series_int() {
    let analysis = analyze("plot(ta.ema(close, bar_index))\n");

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn udf_const_scalar_comparisons_preserve_selected_input_qualifiers() {
    let analysis = analyze(
        "choose_int(mode, x) => mode == 1 ? bar_index : x\nchoose_string(mode, x) => mode == \"dead\" ? bar_index : x\nchoose_color(mode, x) => mode == color.red ? bar_index : x\nlength = input.int(2, \"Length\")\nint_chosen = choose_int(2, length)\nstring_chosen = choose_string(\"live\", length)\ncolor_chosen = choose_color(color.green, length)\nplot(ta.ema(close, int_chosen))\nplot(ta.ema(close, string_chosen))\nplot(ta.ema(close, color_chosen))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    for name in ["int_chosen", "string_chosen", "color_chosen"] {
        let symbol = hir
            .symbols
            .iter()
            .find(|symbol| symbol.name == name)
            .unwrap_or_else(|| panic!("{name} symbol"));
        assert_eq!(
            symbol.pine_type,
            PineType::new(Qualifier::Input, ValueKind::Int),
            "{name}"
        );
    }
}

#[test]
fn tuple_method_const_selector_literal_preserves_selected_input_qualifier() {
    let analysis = analyze(
        "type Box\n    int seed\nmethod choose_pair(Box this, string selector, int x) =>\n    switch selector\n        \"dead\" => [bar_index]\n        \"live\" => [x]\n        => [bar_index]\nbox = Box.new(1)\nlength = input.int(2, \"Length\")\n[len] = box.choose_pair(\"live\", length)\nplot(ta.ema(close, len))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let len = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "len")
        .expect("len symbol");
    assert_eq!(
        len.pine_type,
        PineType::new(Qualifier::Input, ValueKind::Int)
    );
}

#[test]
fn tuple_udf_const_selector_literal_preserves_selected_input_qualifier() {
    let analysis = analyze(
        "choose_pair(selector, x) =>\n    switch selector\n        \"dead\" => [bar_index]\n        \"live\" => [x]\n        => [bar_index]\nlength = input.int(2, \"Length\")\n[len] = choose_pair(\"live\", length)\nplot(ta.ema(close, len))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let len = hir
        .symbols
        .iter()
        .find(|symbol| symbol.name == "len")
        .expect("len symbol");
    assert_eq!(
        len.pine_type,
        PineType::new(Qualifier::Input, ValueKind::Int)
    );
}

#[test]
fn tuple_udf_const_selector_does_not_capture_same_named_global() {
    let analysis = analyze(
        "choose_pair(mode, x) =>\n    switch mode\n        \"dead\" => [bar_index]\n        \"live\" => [x]\n        => [bar_index]\nmode = \"live\"\nlength = input.int(2, \"Length\")\n[len] = choose_pair(\"dead\", length)\nplot(ta.ema(close, len))\n",
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn switch_fallback_reassignments_include_prior_series_conditions() {
    let analysis = analyze(
        "length = input.int(2, \"Length\")\nstatement_selected = length\nswitch\n    close > open =>\n        0\n    =>\n        statement_selected := length\nexpression_selected = length\n_ = switch\n    close > open => 0\n    =>\n        expression_selected := length\n        0\nplot(ta.ema(close, statement_selected))\nplot(ta.ema(close, expression_selected))\n",
    );

    let call_arg_type_count = analysis
        .diagnostics
        .iter()
        .filter(|diagnostic| diagnostic.code == "E_CALL_ARG_TYPE")
        .count();
    assert_eq!(call_arg_type_count, 2, "{:?}", analysis.diagnostics);
    assert!(analysis.hir.is_none());
}

#[test]
fn statically_selected_switch_ignores_unreachable_tail_qualifiers() {
    let analysis = analyze(
        "length = input.int(2, \"Length\")\nselected = switch\n    true => length\n    close > open => bar_index\n    => bar_index\n[tuple_selected] = switch\n    true => [length]\n    close > open => [bar_index]\n    => [bar_index]\nplot(ta.ema(close, selected))\nplot(ta.ema(close, tuple_selected))\n",
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    for name in ["selected", "tuple_selected"] {
        let symbol = hir
            .symbols
            .iter()
            .find(|symbol| symbol.name == name)
            .unwrap_or_else(|| panic!("{name} symbol"));
        assert_eq!(
            symbol.pine_type,
            PineType::new(Qualifier::Input, ValueKind::Int),
            "{name}"
        );
    }
}
