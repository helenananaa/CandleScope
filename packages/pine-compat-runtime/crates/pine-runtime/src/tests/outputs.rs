use pine_sema::analyze_source;
use pine_syntax::SourceFile;

use super::*;

#[test]
fn collects_hline_and_fill_once() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("fill")
p = plot(close)
h = hline(2)
fill(p, h)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 1);
    assert_eq!(result.hlines.len(), 1);
    assert_eq!(result.fills.len(), 1);
    assert_eq!(result.hlines[0].price, PineValue::Int(2));
    assert_eq!(result.fills[0].first_id, result.plots[0].id);
    assert_eq!(result.fills[0].second_id, result.hlines[0].id);
}

#[test]
fn collects_label_new_snapshots() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("labels")
label.new(bar_index, high, "bar")
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.labels.len(), 3);
    for (index, label) in result.labels.iter().enumerate() {
        assert_eq!(label.id, index as u32 + 1);
        assert_eq!(label.snapshots.len(), 1);
        let snapshot = &label.snapshots[0];
        assert_eq!(snapshot.bar_index, index);
        assert!(snapshot.exists);
        assert_eq!(snapshot.x, PineValue::Int(index as i64));
        assert_eq!(snapshot.y, PineValue::Float(index as f64 + 1.0));
        assert_eq!(snapshot.text, PineValue::String("bar".to_owned()));
        assert_eq!(
            snapshot.xloc,
            PineValue::String("xloc.bar_index".to_owned())
        );
        assert_eq!(snapshot.yloc, PineValue::String("yloc.price".to_owned()));
        assert_eq!(snapshot.color, PineValue::Color(0x2196F3));
        assert_eq!(
            snapshot.style,
            PineValue::String("label.style_label_down".to_owned())
        );
        assert_eq!(snapshot.text_color, PineValue::Color(0xFFFFFF));
        assert_eq!(snapshot.size, PineValue::String("size.normal".to_owned()));
        assert_eq!(snapshot.tooltip, PineValue::String(String::new()));
    }
}

#[test]
fn collects_line_new_snapshots() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("lines")
if bar_index == 1
    line.new(bar_index, low, bar_index, high)
if bar_index == 2
    line.new(x1=bar_index, y1=open, x2=bar_index, y2=close)
if bar_index == 3
    line.new(x1=bar_index, y1=low, x2=bar_index + 1, y2=high, xloc=xloc.bar_index, extend=extend.right, color=color.green, style=line.style_dashed, width=2, force_overlay=false)
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.lines.len(), 3);
    assert!(result.labels.is_empty());
    for (index, line) in result.lines.iter().take(2).enumerate() {
        let bar_index = index + 1;
        assert_eq!(line.id, bar_index as u32);
        assert_eq!(line.snapshots.len(), 1);
        let snapshot = &line.snapshots[0];
        assert_eq!(snapshot.bar_index, bar_index);
        assert!(snapshot.exists);
        assert_eq!(snapshot.x1, PineValue::Int(bar_index as i64));
        assert_eq!(snapshot.y1, PineValue::Float(bar_index as f64 + 1.0));
        assert_eq!(snapshot.x2, PineValue::Int(bar_index as i64));
        assert_eq!(snapshot.y2, PineValue::Float(bar_index as f64 + 1.0));
        assert_eq!(snapshot.color, PineValue::Color(0x2196F3));
        assert_eq!(snapshot.width, PineValue::Int(1));
        assert_eq!(
            snapshot.style,
            PineValue::String("line.style_solid".to_owned())
        );
        assert_eq!(snapshot.extend, PineValue::String("extend.none".to_owned()));
    }
    let styled = &result.lines[2];
    assert_eq!(styled.id, 3);
    assert_eq!(styled.snapshots.len(), 1);
    let snapshot = &styled.snapshots[0];
    assert_eq!(snapshot.bar_index, 3);
    assert!(snapshot.exists);
    assert_eq!(snapshot.x1, PineValue::Int(3));
    assert_eq!(snapshot.y1, PineValue::Float(4.0));
    assert_eq!(snapshot.x2, PineValue::Int(4));
    assert_eq!(snapshot.y2, PineValue::Float(4.0));
    assert_eq!(snapshot.color, PineValue::Color(0x4CAF50));
    assert_eq!(snapshot.width, PineValue::Int(2));
    assert_eq!(
        snapshot.style,
        PineValue::String("line.style_dashed".to_owned())
    );
    assert_eq!(
        snapshot.extend,
        PineValue::String("extend.right".to_owned())
    );
}

#[test]
fn collects_line_mutation_snapshots() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("line mutation")
id = line.new(bar_index, high, bar_index, low)
line.set_x1(id, 1)
line.set_y1(id, close + 1)
line.set_xy1(id, bar_index, open)
line.set_x2(id, 2)
line.set_y2(id, close + 2)
line.set_xy2(id, bar_index, close)
line.set_xloc(id, 10, 12, xloc.bar_index)
line.set_color(id, color.green)
line.set_width(id, 2)
line.set_style(id, line.style_dashed)
line.set_extend(id, extend.right)
line.set_xloc(na, 0, 1, xloc.bar_index)
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)]).expect("runtime result");

    assert_eq!(result.lines.len(), 1);
    let line = &result.lines[0];
    assert_eq!(line.snapshots.len(), 12);
    assert_eq!(line.snapshots[1].x1, PineValue::Int(1));
    assert_eq!(line.snapshots[2].y1, PineValue::Float(2.0));
    assert_eq!(line.snapshots[3].x1, PineValue::Int(0));
    assert_eq!(line.snapshots[3].y1, PineValue::Float(1.0));
    assert_eq!(line.snapshots[4].x2, PineValue::Int(2));
    assert_eq!(line.snapshots[5].y2, PineValue::Float(3.0));
    assert_eq!(line.snapshots[6].x2, PineValue::Int(0));
    assert_eq!(line.snapshots[6].y2, PineValue::Float(1.0));
    assert_eq!(line.snapshots[7].x1, PineValue::Int(10));
    assert_eq!(line.snapshots[7].x2, PineValue::Int(12));
    assert_eq!(line.snapshots[8].color, PineValue::Color(0x4CAF50));
    assert_eq!(line.snapshots[9].width, PineValue::Int(2));
    assert_eq!(
        line.snapshots[10].style,
        PineValue::String("line.style_dashed".to_owned())
    );
    assert_eq!(
        line.snapshots[11].extend,
        PineValue::String("extend.right".to_owned())
    );
}

#[test]
fn collects_line_delete_snapshots() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("line delete")
var id = line.new(bar_index, high, bar_index, low)
if bar_index == 1
    line.delete(id)
if bar_index == 2
    line.set_color(id, color.green)
    line.delete(id)
line.delete(na)
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.lines.len(), 1);
    let line = &result.lines[0];
    assert_eq!(line.snapshots.len(), 2);
    assert!(line.snapshots[0].exists);
    assert_eq!(line.snapshots[0].bar_index, 0);
    assert!(!line.snapshots[1].exists);
    assert_eq!(line.snapshots[1].bar_index, 1);
}

#[test]
fn evicts_oldest_line_after_default_limit() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("line default limit")
for i = 0 to 50
    line.new(i, close, i, open)
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)]).expect("runtime result");

    assert_eq!(result.lines.len(), 51);
    assert_eq!(result.lines[0].snapshots.len(), 2);
    assert!(!result.lines[0].snapshots.last().unwrap().exists);
    assert_eq!(
        result
            .lines
            .iter()
            .filter(|line| line.snapshots.last().unwrap().exists)
            .count(),
        50
    );
}

#[test]
fn evicts_oldest_line_when_creation_exceeds_declared_limit() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("line limit", max_lines_count=2)
for i = 0 to 2
    line.new(i, close, i, open)
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)]).expect("runtime result");

    assert_eq!(result.lines.len(), 3);
    assert_eq!(result.lines[0].snapshots.len(), 2);
    assert!(!result.lines[0].snapshots.last().unwrap().exists);
    assert_eq!(result.lines[0].snapshots.last().unwrap().bar_index, 0);
    assert!(result.lines[1].snapshots.last().unwrap().exists);
    assert!(result.lines[2].snapshots.last().unwrap().exists);
}

#[test]
fn line_copy_deleted_id_is_noop_at_limit() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("line copy deleted limit")
deleted = line.new(0, close, 0, close)
line.delete(deleted)
for i = 0 to 498
    line.new(i, close, i, open)
line.copy(deleted)
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)]).expect("runtime result");

    assert_eq!(result.lines.len(), 500);
    assert!(!result.lines[0].snapshots.last().unwrap().exists);
}

#[test]
fn profiles_line_storage() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("line profile")
id = line.new(bar_index, high, bar_index, low)
line.set_color(id, color.green)
line.delete(id)
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &[bar(1.0)]).expect("runtime result");

    assert_eq!(profiled.profile.lines, 1);
    assert_eq!(profiled.profile.line_snapshots, 3);
    assert!(profiled.profile.line_capacity >= 1);
    assert!(profiled.profile.line_snapshot_capacity >= 3);
}

#[test]
fn collects_box_new_snapshots() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("boxes")
if bar_index == 1
    box.new(bar_index, high, bar_index, low)
if bar_index == 2
    box.new(left=bar_index, top=open, right=bar_index, bottom=close)
if bar_index == 3
    box.new(left=bar_index, top=high, right=bar_index + 1, bottom=low, border_color=color.white, border_width=2, border_style=line.style_dashed, extend=extend.right, xloc=xloc.bar_index, bgcolor=color.green, text="styled", text_size=19, text_color=color.white, text_halign=text.align_left, text_valign=text.align_top, text_wrap=text.wrap_auto, text_font_family=font.family_monospace, force_overlay=false, text_formatting=text.format_bold + text.format_italic)
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.boxes.len(), 3);
    assert!(result.labels.is_empty());
    assert!(result.lines.is_empty());
    for (index, box_output) in result.boxes.iter().take(2).enumerate() {
        let bar_index = index + 1;
        assert_eq!(box_output.id, bar_index as u32);
        assert_eq!(box_output.snapshots.len(), 1);
        let snapshot = &box_output.snapshots[0];
        assert_eq!(snapshot.bar_index, bar_index);
        assert!(snapshot.exists);
        assert_eq!(snapshot.left, PineValue::Int(bar_index as i64));
        assert_eq!(snapshot.top, PineValue::Float(bar_index as f64 + 1.0));
        assert_eq!(snapshot.right, PineValue::Int(bar_index as i64));
        assert_eq!(snapshot.bottom, PineValue::Float(bar_index as f64 + 1.0));
        assert_eq!(snapshot.bg_color, PineValue::Color(0x2196F3));
        assert_eq!(snapshot.border_color, PineValue::Color(0x2196F3));
        assert_eq!(snapshot.border_width, PineValue::Int(1));
        assert_eq!(
            snapshot.border_style,
            PineValue::String("line.style_solid".to_owned())
        );
        assert_eq!(snapshot.extend, PineValue::String("extend.none".to_owned()));
        assert_eq!(snapshot.text, PineValue::String(String::new()));
        assert_eq!(snapshot.text_color, PineValue::Color(0x363A45));
        assert_eq!(
            snapshot.text_size,
            PineValue::String("size.auto".to_owned())
        );
        assert_eq!(
            snapshot.text_halign,
            PineValue::String("text.align_center".to_owned())
        );
        assert_eq!(
            snapshot.text_valign,
            PineValue::String("text.align_center".to_owned())
        );
        assert_eq!(
            snapshot.text_wrap,
            PineValue::String("text.wrap_none".to_owned())
        );
        assert_eq!(
            snapshot.text_font_family,
            PineValue::String("font.family_default".to_owned())
        );
        assert_eq!(snapshot.text_formatting, PineValue::Int(0));
    }
    let styled = &result.boxes[2];
    assert_eq!(styled.id, 3);
    assert_eq!(styled.snapshots.len(), 1);
    let snapshot = &styled.snapshots[0];
    assert_eq!(snapshot.bar_index, 3);
    assert!(snapshot.exists);
    assert_eq!(snapshot.left, PineValue::Int(3));
    assert_eq!(snapshot.top, PineValue::Float(4.0));
    assert_eq!(snapshot.right, PineValue::Int(4));
    assert_eq!(snapshot.bottom, PineValue::Float(4.0));
    assert_eq!(snapshot.bg_color, PineValue::Color(0x4CAF50));
    assert_eq!(snapshot.border_color, PineValue::Color(0xFFFFFF));
    assert_eq!(snapshot.border_width, PineValue::Int(2));
    assert_eq!(
        snapshot.border_style,
        PineValue::String("line.style_dashed".to_owned())
    );
    assert_eq!(
        snapshot.extend,
        PineValue::String("extend.right".to_owned())
    );
    assert_eq!(snapshot.text, PineValue::String("styled".to_owned()));
    assert_eq!(snapshot.text_color, PineValue::Color(0xFFFFFF));
    assert_eq!(snapshot.text_size, PineValue::Int(19));
    assert_eq!(
        snapshot.text_halign,
        PineValue::String("text.align_left".to_owned())
    );
    assert_eq!(
        snapshot.text_valign,
        PineValue::String("text.align_top".to_owned())
    );
    assert_eq!(
        snapshot.text_wrap,
        PineValue::String("text.wrap_auto".to_owned())
    );
    assert_eq!(
        snapshot.text_font_family,
        PineValue::String("font.family_monospace".to_owned())
    );
    assert_eq!(snapshot.text_formatting, PineValue::Int(3));
}

#[test]
fn collects_box_mutation_snapshots() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("box mutation")
id = box.new(bar_index, high, bar_index, low)
box.set_left(id, 1)
box.set_top(id, close + 1)
box.set_lefttop(id, bar_index, open)
box.set_right(id, 2)
box.set_bottom(id, close + 2)
box.set_rightbottom(id, bar_index, close)
box.set_xloc(id, 10, 12, xloc.bar_index)
box.set_bgcolor(id, color.green)
box.set_border_color(id, color.white)
box.set_border_width(id, 2)
box.set_border_style(id, line.style_dashed)
box.set_extend(id, extend.right)
box.set_text(id, "box text")
box.set_text_color(id, color.white)
box.set_text_size(id, 19)
box.set_text_halign(id, text.align_left)
box.set_text_valign(id, text.align_top)
box.set_text_wrap(id, text.wrap_auto)
box.set_text_font_family(id, font.family_monospace)
box.set_text_formatting(id, text.format_bold + text.format_italic)
box.set_xloc(na, 0, 1, xloc.bar_index)
box.set_text_formatting(na, text.format_italic)
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)]).expect("runtime result");

    assert_eq!(result.boxes.len(), 1);
    let box_output = &result.boxes[0];
    assert_eq!(box_output.snapshots.len(), 21);
    assert_eq!(box_output.snapshots[1].left, PineValue::Int(1));
    assert_eq!(box_output.snapshots[2].top, PineValue::Float(2.0));
    assert_eq!(box_output.snapshots[3].left, PineValue::Int(0));
    assert_eq!(box_output.snapshots[3].top, PineValue::Float(1.0));
    assert_eq!(box_output.snapshots[4].right, PineValue::Int(2));
    assert_eq!(box_output.snapshots[5].bottom, PineValue::Float(3.0));
    assert_eq!(box_output.snapshots[6].right, PineValue::Int(0));
    assert_eq!(box_output.snapshots[6].bottom, PineValue::Float(1.0));
    assert_eq!(box_output.snapshots[7].left, PineValue::Int(10));
    assert_eq!(box_output.snapshots[7].right, PineValue::Int(12));
    assert_eq!(box_output.snapshots[8].bg_color, PineValue::Color(0x4CAF50));
    assert_eq!(
        box_output.snapshots[9].border_color,
        PineValue::Color(0xFFFFFF)
    );
    assert_eq!(box_output.snapshots[10].border_width, PineValue::Int(2));
    assert_eq!(
        box_output.snapshots[11].border_style,
        PineValue::String("line.style_dashed".to_owned())
    );
    assert_eq!(
        box_output.snapshots[12].extend,
        PineValue::String("extend.right".to_owned())
    );
    assert_eq!(
        box_output.snapshots[13].text,
        PineValue::String("box text".to_owned())
    );
    assert_eq!(
        box_output.snapshots[14].text_color,
        PineValue::Color(0xFFFFFF)
    );
    assert_eq!(box_output.snapshots[15].text_size, PineValue::Int(19));
    assert_eq!(
        box_output.snapshots[16].text_halign,
        PineValue::String("text.align_left".to_owned())
    );
    assert_eq!(
        box_output.snapshots[17].text_valign,
        PineValue::String("text.align_top".to_owned())
    );
    assert_eq!(
        box_output.snapshots[18].text_wrap,
        PineValue::String("text.wrap_auto".to_owned())
    );
    assert_eq!(
        box_output.snapshots[19].text_font_family,
        PineValue::String("font.family_monospace".to_owned())
    );
    assert_eq!(box_output.snapshots[20].text_formatting, PineValue::Int(3));
}

#[test]
fn collects_box_delete_snapshots() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("box delete")
var id = box.new(bar_index, high, bar_index, low)
if bar_index == 1
    box.delete(id)
if bar_index == 2
    box.set_bgcolor(id, color.green)
    box.delete(id)
box.delete(na)
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.boxes.len(), 1);
    let box_output = &result.boxes[0];
    assert_eq!(box_output.snapshots.len(), 2);
    assert!(box_output.snapshots[0].exists);
    assert_eq!(box_output.snapshots[0].bar_index, 0);
    assert!(!box_output.snapshots[1].exists);
    assert_eq!(box_output.snapshots[1].bar_index, 1);
}

#[test]
fn evicts_oldest_box_after_default_limit() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("box default limit")
for i = 0 to 50
    box.new(i, close, i, open)
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)]).expect("runtime result");

    assert_eq!(result.boxes.len(), 51);
    assert_eq!(result.boxes[0].snapshots.len(), 2);
    assert!(!result.boxes[0].snapshots.last().unwrap().exists);
    assert_eq!(
        result
            .boxes
            .iter()
            .filter(|box_output| box_output.snapshots.last().unwrap().exists)
            .count(),
        50
    );
}

#[test]
fn evicts_oldest_box_when_creation_exceeds_declared_limit() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("box limit", max_boxes_count=2)
for i = 0 to 2
    box.new(i, close, i, open)
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)]).expect("runtime result");

    assert_eq!(result.boxes.len(), 3);
    assert_eq!(result.boxes[0].snapshots.len(), 2);
    assert!(!result.boxes[0].snapshots.last().unwrap().exists);
    assert_eq!(result.boxes[0].snapshots.last().unwrap().bar_index, 0);
    assert!(result.boxes[1].snapshots.last().unwrap().exists);
    assert!(result.boxes[2].snapshots.last().unwrap().exists);
}

#[test]
fn evicts_oldest_polyline_after_default_limit() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("polyline default limit")
points = array.new<chart.point>()
array.push(points, chart.point.from_index(bar_index, close))
for i = 0 to 50
    polyline.new(points)
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)]).expect("runtime result");

    assert_eq!(result.polylines.len(), 51);
    assert_eq!(result.polylines[0].snapshots.len(), 2);
    assert!(!result.polylines[0].snapshots.last().unwrap().exists);
    assert_eq!(
        result
            .polylines
            .iter()
            .filter(|polyline| polyline.snapshots.last().unwrap().exists)
            .count(),
        50
    );
}

#[test]
fn evicts_oldest_polyline_when_creation_exceeds_declared_limit() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("polyline limit", max_polylines_count=2)
points = array.new<chart.point>()
array.push(points, chart.point.from_index(bar_index, close))
for i = 0 to 2
    polyline.new(points)
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)]).expect("runtime result");

    assert_eq!(result.polylines.len(), 3);
    assert_eq!(result.polylines[0].snapshots.len(), 2);
    assert!(!result.polylines[0].snapshots.last().unwrap().exists);
    assert_eq!(result.polylines[0].snapshots.last().unwrap().bar_index, 0);
    assert!(result.polylines[1].snapshots.last().unwrap().exists);
    assert!(result.polylines[2].snapshots.last().unwrap().exists);
}

#[test]
fn box_copy_deleted_id_is_noop_at_limit() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("box copy deleted limit")
deleted = box.new(0, close, 0, open)
box.delete(deleted)
for i = 0 to 498
    box.new(i, close, i, open)
box.copy(deleted)
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)]).expect("runtime result");

    assert_eq!(result.boxes.len(), 500);
    assert!(!result.boxes[0].snapshots.last().unwrap().exists);
}

#[test]
fn profiles_box_storage() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("box profile")
id = box.new(bar_index, high, bar_index, low)
box.set_bgcolor(id, color.green)
box.delete(id)
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &[bar(1.0)]).expect("runtime result");

    assert_eq!(profiled.profile.boxes, 1);
    assert_eq!(profiled.profile.box_snapshots, 3);
    assert!(profiled.profile.box_capacity >= 1);
    assert!(profiled.profile.box_snapshot_capacity >= 3);
}

#[test]
fn collects_table_cell_snapshots() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("tables")
var id = table.new(position.top_right, 2, 2)
if bar_index == 1
    table.cell(id, 0, 0, "A")
if bar_index == 2
    table.cell(id, column=1, row=0, text="B", bgcolor=color.green, text_color=color.white, tooltip="initial", text_font_family=font.family_monospace, text_formatting=text.format_bold)
    table.cell(id, 0, 0, "C")
    table.cell_set_text(id, 1, 0, "B2")
    table.cell_set_bgcolor(id, 1, 0, color.red)
    table.cell_set_text_color(id, 1, 0, color.blue)
    table.cell_set_width(id, 1, 0, 25)
    table.cell_set_height(id, 1, 0, 40)
    table.cell_set_text_size(id, 1, 0, 21)
    table.cell_set_text_halign(id, 1, 0, text.align_left)
    table.cell_set_text_valign(id, 1, 0, text.align_top)
    table.cell_set_text_wrap(id, 1, 0, text.wrap_auto)
    table.cell_set_tooltip(id, 1, 0, "updated")
    table.cell_set_text_font_family(id, 1, 0, font.family_default)
    table.cell_set_text_formatting(id, 1, 0, text.format_bold + text.format_italic)
    table.set_position(id, position.bottom_right)
    table.set_bgcolor(id, color.yellow)
    table.set_frame_color(id, color.black)
    table.set_frame_width(id, 3)
    table.set_border_color(id, color.white)
    table.set_border_width(id, 4)
table.cell(na, 0, 1, "noop")
table.set_position(na, position.top_left)
table.set_bgcolor(na, color.red)
table.set_frame_color(na, color.blue)
table.set_frame_width(na, 2)
table.set_border_color(na, color.green)
table.set_border_width(na, 5)
table.cell_set_text(na, 0, 1, "noop")
table.cell_set_bgcolor(na, 0, 1, color.red)
table.cell_set_text_color(na, 0, 1, color.blue)
table.cell_set_width(na, 0, 1, 25)
table.cell_set_height(na, 0, 1, 40)
table.cell_set_text_size(na, 0, 1, size.small)
table.cell_set_text_halign(na, 0, 1, text.align_left)
table.cell_set_text_valign(na, 0, 1, text.align_top)
table.cell_set_text_wrap(na, 0, 1, text.wrap_none)
table.cell_set_tooltip(na, 0, 1, "noop")
table.cell_set_text_font_family(na, 0, 1, font.family_monospace)
table.cell_set_text_formatting(na, 0, 1, text.format_italic)
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.tables.len(), 1);
    let table = &result.tables[0];
    assert_eq!(
        table.position,
        PineValue::String("position.bottom_right".to_owned())
    );
    assert_eq!(table.bg_color, PineValue::Color(0xFDD835));
    assert_eq!(table.frame_color, PineValue::Color(0x363A45));
    assert_eq!(table.frame_width, PineValue::Int(3));
    assert_eq!(table.border_color, PineValue::Color(0xFFFFFF));
    assert_eq!(table.border_width, PineValue::Int(4));
    assert_eq!(table.columns, 2);
    assert_eq!(table.rows, 2);
    assert_eq!(table.snapshots.len(), 16);
    assert!(table.snapshots.iter().all(|snapshot| snapshot.exists));
    assert!(table.snapshots[0].cells.is_empty());
    assert_eq!(table.snapshots[1].cells[0].column, 0);
    assert_eq!(table.snapshots[1].cells[0].row, 0);
    assert_eq!(
        table.snapshots[1].cells[0].text,
        PineValue::String("A".to_owned())
    );
    assert_eq!(table.snapshots[2].cells.len(), 2);
    assert_eq!(table.snapshots[2].cells[1].column, 1);
    assert_eq!(
        table.snapshots[2].cells[1].bg_color,
        PineValue::Color(0x4CAF50)
    );
    assert_eq!(
        table.snapshots[2].cells[1].text_color,
        PineValue::Color(0xFFFFFF)
    );
    assert_eq!(
        table.snapshots[2].cells[1].tooltip,
        PineValue::String("initial".to_owned())
    );
    assert_eq!(
        table.snapshots[2].cells[1].text_font_family,
        PineValue::String("font.family_monospace".to_owned())
    );
    assert_eq!(
        table.snapshots[2].cells[1].text_formatting,
        PineValue::Int(1)
    );
    assert_eq!(
        table.snapshots[2].cells[1].text_wrap,
        PineValue::String("text.wrap_none".to_owned())
    );
    assert_eq!(
        table.snapshots[3].cells[0].text,
        PineValue::String("C".to_owned())
    );
    assert_eq!(
        table.snapshots[4].cells[1].text,
        PineValue::String("B2".to_owned())
    );
    assert_eq!(
        table.snapshots[5].cells[1].bg_color,
        PineValue::Color(0xF23645)
    );
    assert_eq!(
        table.snapshots[6].cells[1].text_color,
        PineValue::Color(0x2196F3)
    );
    assert_eq!(table.snapshots[7].cells[1].width, PineValue::Int(25));
    assert_eq!(table.snapshots[8].cells[1].height, PineValue::Int(40));
    assert_eq!(table.snapshots[9].cells[1].text_size, PineValue::Int(21));
    assert_eq!(
        table.snapshots[10].cells[1].text_halign,
        PineValue::String("text.align_left".to_owned())
    );
    assert_eq!(
        table.snapshots[11].cells[1].text_valign,
        PineValue::String("text.align_top".to_owned())
    );
    assert_eq!(
        table.snapshots[12].cells[1].text_wrap,
        PineValue::String("text.wrap_auto".to_owned())
    );
    assert_eq!(
        table.snapshots[13].cells[1].tooltip,
        PineValue::String("updated".to_owned())
    );
    assert_eq!(
        table.snapshots[14].cells[1].text_font_family,
        PineValue::String("font.family_default".to_owned())
    );
    assert_eq!(
        table.snapshots[15].cells[1].text_formatting,
        PineValue::Int(3)
    );
}

#[test]
fn collects_table_new_bgcolor_option() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("table new options")
first = table.new(position.top_right, 2, 2)
second = table.new(position.bottom_left, 1, 1, bgcolor=color.yellow, frame_color=color.black, frame_width=2, border_color=color.white, border_width=1)
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)]).expect("runtime result");

    assert_eq!(result.tables.len(), 2);
    assert_eq!(result.tables[0].bg_color, PineValue::Na);
    assert_eq!(result.tables[1].bg_color, PineValue::Color(0xFDD835));
    assert_eq!(result.tables[1].frame_color, PineValue::Color(0x363A45));
    assert_eq!(result.tables[1].frame_width, PineValue::Int(2));
    assert_eq!(result.tables[1].border_color, PineValue::Color(0xFFFFFF));
    assert_eq!(result.tables[1].border_width, PineValue::Int(1));
    assert!(result.tables[0].snapshots[0].exists);
    assert!(result.tables[1].snapshots[0].exists);
}

#[test]
fn collects_table_delete_snapshots() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("table delete")
var id = table.new(position.top_right, 2, 2)
if bar_index == 1
    table.cell(id, 0, 0, "A")
    table.delete(id)
if bar_index == 2
    table.cell(id, 0, 0, "ignored")
    table.set_bgcolor(id, color.red)
    table.delete(id)
table.delete(na)
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");
    let table = &result.tables[0];

    assert_eq!(table.snapshots.len(), 3);
    assert!(table.snapshots[0].exists);
    assert_eq!(table.snapshots[0].bar_index, 0);
    assert!(table.snapshots[1].exists);
    assert_eq!(
        table.snapshots[1].cells[0].text,
        PineValue::String("A".to_owned())
    );
    assert!(!table.snapshots[2].exists);
    assert_eq!(table.snapshots[2].bar_index, 1);
    assert!(table.snapshots[2].cells.is_empty());
    assert_eq!(table.bg_color, PineValue::Na);
}

#[test]
fn collects_table_clear_snapshots() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("table clear")
var id = table.new(position.top_right, 3, 2)
if bar_index == 1
    table.cell(id, 0, 0, "A")
    table.cell(id, 1, 0, "B")
    table.cell(id, 2, 1, "C", bgcolor=na, text_color=color.white)
    table.clear(id, 1, 0, 2, 1)
if bar_index == 2
    table.clear(id, 0, 0, 0, 0)
    table.delete(id)
    table.clear(id, 0, 0, 2, 1)
table.clear(na, 0, 0, 0, 0)
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");
    let table = &result.tables[0];

    assert_eq!(table.snapshots.len(), 7);
    assert_eq!(table.snapshots[1].cells.len(), 1);
    assert_eq!(table.snapshots[2].cells.len(), 2);
    assert_eq!(table.snapshots[3].cells.len(), 3);
    assert_eq!(table.snapshots[3].cells[2].bg_color, PineValue::Na);
    assert_eq!(
        table.snapshots[3].cells[2].text_color,
        PineValue::Color(0xFFFFFF)
    );
    assert_eq!(table.snapshots[4].bar_index, 1);
    assert_eq!(table.snapshots[4].cells.len(), 1);
    assert_eq!(
        table.snapshots[4].cells[0].text,
        PineValue::String("A".to_owned())
    );
    assert_eq!(table.snapshots[5].bar_index, 2);
    assert!(table.snapshots[5].cells.is_empty());
    assert!(!table.snapshots[6].exists);
}

#[test]
fn collects_table_merge_cell_snapshots() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("table merge cells")
var id = table.new(position.top_right, 4, 3)
if bar_index == 1
    table.cell(id, 0, 0, "Header")
    table.merge_cells(id, 0, 0, 3, 0)
    table.cell(id, 0, 1, "Body")
    table.merge_cells(id, 0, 1, 1, 2)
if bar_index == 2
    table.clear(id, 0, 1, 1, 2)
    table.delete(id)
    table.merge_cells(id, 2, 1, 3, 2)
table.merge_cells(na, 0, 0, 0, 0)
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");
    let table = &result.tables[0];

    assert_eq!(table.snapshots.len(), 7);
    assert_eq!(table.snapshots[2].merged_cells.len(), 1);
    assert_eq!(table.snapshots[2].merged_cells[0].start_column, 0);
    assert_eq!(table.snapshots[2].merged_cells[0].start_row, 0);
    assert_eq!(table.snapshots[2].merged_cells[0].end_column, 3);
    assert_eq!(table.snapshots[2].merged_cells[0].end_row, 0);
    assert_eq!(table.snapshots[4].merged_cells.len(), 2);
    assert_eq!(table.snapshots[5].merged_cells.len(), 1);
    assert_eq!(table.snapshots[5].merged_cells[0].start_row, 0);
    assert!(!table.snapshots[6].exists);
    assert!(table.snapshots[6].merged_cells.is_empty());
}

#[test]
fn rejects_invalid_table_shapes_and_cells() {
    for source_text in [
        r#"indicator("bad table size")
table.new(position.top_right, 0, 1)
plot(close)
"#,
        r#"indicator("bad table cells")
id = table.new(position.top_right, 2, 2)
table.cell(id, 2, 0, "bad")
plot(close)
"#,
        r#"indicator("missing table cell")
id = table.new(position.top_right, 2, 2)
table.cell_set_text(id, 0, 0, "bad")
plot(close)
"#,
        r#"indicator("missing table tooltip cell")
id = table.new(position.top_right, 2, 2)
table.cell_set_tooltip(id, 0, 0, "bad")
plot(close)
"#,
        r#"indicator("missing table font family cell")
id = table.new(position.top_right, 2, 2)
table.cell_set_text_font_family(id, 0, 0, font.family_monospace)
plot(close)
"#,
        r#"indicator("missing table formatting cell")
id = table.new(position.top_right, 2, 2)
table.cell_set_text_formatting(id, 0, 0, text.format_bold)
plot(close)
"#,
        r#"indicator("bad table merge bounds")
id = table.new(position.top_right, 2, 2)
table.merge_cells(id, 0, 0, 2, 1)
plot(close)
"#,
        r#"indicator("bad table merge overlap")
id = table.new(position.top_right, 3, 3)
table.merge_cells(id, 0, 0, 1, 1)
table.merge_cells(id, 1, 1, 2, 2)
plot(close)
"#,
    ] {
        let source = SourceFile::new("test.pine", source_text);
        let analysis = analyze_source(&source);
        assert!(
            analysis.diagnostics.is_empty(),
            "{:?}",
            analysis.diagnostics
        );
        assert!(
            run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)]).is_err(),
            "{source_text}"
        );
    }
}

#[test]
fn profiles_table_storage() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("table profile")
id = table.new(position.top_right, 2, 2)
table.cell(id, 0, 0, "A")
table.cell(id, 1, 0, "B")
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &[bar(1.0)]).expect("runtime result");

    assert_eq!(profiled.profile.tables, 1);
    assert_eq!(profiled.profile.table_cells, 3);
    assert!(profiled.profile.table_capacity >= 1);
    assert!(profiled.profile.table_snapshot_capacity >= 3);
    assert!(profiled.profile.table_cell_capacity >= 2);
}

#[test]
fn collects_label_new_options() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("label options")
label.new(x=bar_index, y=high, text="bar", xloc=xloc.bar_index, yloc=yloc.price, color=color.green, style=label.style_label_up, textcolor=color.white, size=12, tooltip="Tip")
label.new(x=bar_index, y=low, text="styled", textalign=text.align_right, text_font_family=font.family_monospace, text_formatting=text.format_bold)
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");
    assert_eq!(result.labels.len(), 2);
    let snapshot = &result.labels[0].snapshots[0];

    assert_eq!(
        snapshot.xloc,
        PineValue::String("xloc.bar_index".to_owned())
    );
    assert_eq!(snapshot.yloc, PineValue::String("yloc.price".to_owned()));
    assert_eq!(snapshot.color, PineValue::Color(0x4CAF50));
    assert_eq!(
        snapshot.style,
        PineValue::String("label.style_label_up".to_owned())
    );
    assert_eq!(snapshot.text_color, PineValue::Color(0xFFFFFF));
    assert_eq!(snapshot.size, PineValue::Int(12));
    assert_eq!(snapshot.tooltip, PineValue::String("Tip".to_owned()));
    assert_eq!(
        snapshot.text_align,
        PineValue::String("text.align_center".to_owned())
    );
    assert_eq!(
        snapshot.text_font_family,
        PineValue::String("font.family_default".to_owned())
    );
    assert_eq!(snapshot.text_formatting, PineValue::Int(0));

    let styled = &result.labels[1].snapshots[0];
    assert_eq!(styled.color, PineValue::Color(0x2196F3));
    assert_eq!(styled.text_color, PineValue::Color(0xFFFFFF));
    assert_eq!(
        styled.text_align,
        PineValue::String("text.align_right".to_owned())
    );
    assert_eq!(
        styled.text_font_family,
        PineValue::String("font.family_monospace".to_owned())
    );
    assert_eq!(styled.text_formatting, PineValue::Int(1));
}

#[test]
fn collects_label_mutation_snapshots() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("label mutation")
id = label.new(bar_index, high, "start")
label.set_x(id, 1)
label.set_y(id, close + 1)
label.set_text(id, "changed")
label.set_color(id, color.green)
label.set_textcolor(id, color.white)
label.set_style(id, label.style_label_up)
label.set_size(id, 12)
label.set_tooltip(id, "Tip")
label.set_textalign(id, text.align_left)
label.set_text_font_family(id, font.family_monospace)
label.set_text_formatting(id, text.format_bold + text.format_italic)
label.set_text_formatting(na, text.format_italic)
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");
    let label = &result.labels[0];

    assert_eq!(label.snapshots.len(), 11);
    assert_eq!(label.snapshots[0].x, PineValue::Int(0));
    assert_eq!(label.snapshots[1].x, PineValue::Int(1));
    assert_eq!(label.snapshots[2].y, PineValue::Float(2.0));
    assert_eq!(
        label.snapshots[3].text,
        PineValue::String("changed".to_owned())
    );
    assert_eq!(label.snapshots[4].color, PineValue::Color(0x4CAF50));
    assert_eq!(
        label.snapshots[5].style,
        PineValue::String("label.style_label_up".to_owned())
    );
    assert_eq!(label.snapshots[6].size, PineValue::Int(12));
    assert_eq!(
        label.snapshots[7].tooltip,
        PineValue::String("Tip".to_owned())
    );
    assert_eq!(
        label.snapshots[8].text_align,
        PineValue::String("text.align_left".to_owned())
    );
    assert_eq!(
        label.snapshots[9].text_font_family,
        PineValue::String("font.family_monospace".to_owned())
    );
    assert_eq!(label.snapshots[10].text_formatting, PineValue::Int(3));
}

#[test]
fn skips_noop_label_mutations() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("label noops")
var id = label.new(bar_index, high, "start")
label.set_text(id, "start")
label.set_text(na, "ignored")
if bar_index == 1
    label.set_text(id, "start")
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.labels[0].snapshots.len(), 1);
}

#[test]
fn collects_label_delete_snapshots() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("label delete")
var id = label.new(bar_index, high, "start")
if bar_index == 1
    label.delete(id)
if bar_index == 2
    label.set_text(id, "ignored")
    label.delete(id)
label.delete(na)
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");
    let label = &result.labels[0];

    assert_eq!(label.snapshots.len(), 2);
    assert!(label.snapshots[0].exists);
    assert_eq!(label.snapshots[0].bar_index, 0);
    assert!(!label.snapshots[1].exists);
    assert_eq!(label.snapshots[1].bar_index, 1);
}

#[test]
fn evicts_oldest_label_after_default_limit() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("label limit")
for i = 0 to 50
    label.new(i, close, "x")
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)])
        .expect("runtime should evict oldest label");

    assert_eq!(result.labels.len(), 51);
    assert_eq!(result.labels[0].id, 1);
    assert_eq!(result.labels[0].snapshots.len(), 2);
    assert!(!result.labels[0].snapshots[1].exists);
    assert_eq!(result.labels[0].snapshots[1].bar_index, 0);
    assert_eq!(result.labels[50].id, 51);
    assert!(result.labels[50].snapshots[0].exists);
}

#[test]
fn evicts_oldest_label_when_creation_exceeds_declared_limit() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("label limit", max_labels_count=2)
for i = 0 to 2
    label.new(i, close, "x")
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)])
        .expect("runtime should evict oldest label");

    assert_eq!(result.labels.len(), 3);
    assert_eq!(result.labels[0].id, 1);
    assert_eq!(result.labels[0].snapshots.len(), 2);
    assert!(!result.labels[0].snapshots[1].exists);
    assert_eq!(result.labels[1].id, 2);
    assert!(result.labels[1].snapshots[0].exists);
    assert_eq!(result.labels[2].id, 3);
    assert!(result.labels[2].snapshots[0].exists);
}

#[test]
fn profiles_label_storage() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("label profile")
id = label.new(bar_index, high, "start")
label.set_text(id, "changed")
label.delete(id)
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let profiled =
        run_historical_profiled(&analysis.hir.expect("HIR"), &[bar(1.0)]).expect("runtime result");

    assert_eq!(profiled.profile.labels, 1);
    assert_eq!(profiled.profile.label_snapshots, 3);
    assert!(profiled.profile.label_capacity >= 1);
    assert!(profiled.profile.label_snapshot_capacity >= 3);
}

#[test]
fn collects_conditional_and_stored_label_ids() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("conditional labels")
if close > 1
    created = label.new(bar_index, close, "stored")
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.labels.len(), 2);
    assert_eq!(result.labels[0].id, 1);
    assert_eq!(result.labels[0].snapshots[0].bar_index, 1);
    assert_eq!(result.labels[0].snapshots[0].x, PineValue::Int(1));
    assert_eq!(result.labels[1].id, 2);
    assert_eq!(result.labels[1].snapshots[0].bar_index, 2);
    assert_eq!(result.labels[1].snapshots[0].x, PineValue::Int(2));
}

#[test]
fn collects_label_side_effects_in_control_flow() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("label control flow")
var label_id = label.new(bar_index, high, "start")
if bar_index == 1
    label.set_text(label_id, "if")
direction = close > open ? 1 : -1
color_i = 0
while color_i < 1
    if direction == 1
        label.set_color(label_id, color.green)
    else
        label.set_color(label_id, color.red)
    color_i := color_i + 1
tooltip_i = 0
while tooltip_i < 1
    if bar_index == 2
        label.set_tooltip(label_id, "for")
    tooltip_i := tooltip_i + 1
j = 0
while j < 1
    if bar_index == 3
        label.set_size(label_id, size.small)
    j := j + 1
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        bar_ohlc(1.0, 1.0, 1.0, 1.0),
        bar_ohlc(1.0, 2.0, 1.0, 2.0),
        bar_ohlc(3.0, 2.0, 2.0, 2.0),
        bar_ohlc(3.0, 4.0, 3.0, 4.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.labels.len(), 1);
    let snapshots = &result.labels[0].snapshots;
    assert_eq!(snapshots.len(), 8);
    assert_eq!(snapshots[0].bar_index, 0);
    assert_eq!(snapshots[1].color, PineValue::Color(0xF23645));
    assert_eq!(snapshots[2].text, PineValue::String("if".to_owned()));
    assert_eq!(snapshots[3].color, PineValue::Color(0x4CAF50));
    assert_eq!(snapshots[4].color, PineValue::Color(0xF23645));
    assert_eq!(snapshots[5].tooltip, PineValue::String("for".to_owned()));
    assert_eq!(snapshots[6].color, PineValue::Color(0x4CAF50));
    assert_eq!(
        snapshots[7].size,
        PineValue::String("size.small".to_owned())
    );
}

#[test]
fn runs_output_metadata_parameters() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("output metadata")
p = plot(close, title="Close", color=color.green, linewidth=2, style=plot.style_line, trackprice=false, histbase=0, offset=1, join=false, editable=true, show_last=10, display=display.pane, format=format.price, precision=2, force_overlay=false)
h = hline(2, title="Two", color=color.gray, linestyle=hline.style_dotted, linewidth=1, editable=true, display=display.price_scale)
fill(p, h, color=color.new(color.green, 80), title="Fill", editable=false, show_last=5, fillgaps=true, display=display.status_line)
bgcolor(color.new(color.blue, 90), title="Background", offset=0, editable=false, show_last=3, display=display.data_window)
barcolor(close > open ? color.green : color.red, title="Bars", offset=0, editable=true, show_last=3, display=display.none)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 1);
    assert_values_close(&result.plots[0].values, &[1.0, 2.0, 3.0]);
    assert_eq!(result.hlines.len(), 1);
    assert_eq!(result.hlines[0].price, PineValue::Int(2));
    assert_eq!(result.fills.len(), 1);
    assert_eq!(result.fills[0].first_id, result.plots[0].id);
    assert_eq!(result.fills[0].second_id, result.hlines[0].id);
    assert_eq!(result.bg_colors.len(), 1);
    assert_eq!(result.bg_colors[0].values.len(), 3);
    assert_eq!(result.bar_colors.len(), 1);
    assert_eq!(result.bar_colors[0].values.len(), 3);
}

#[test]
fn collects_bgcolor_and_barcolor_series() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("colors")
if close > 1
    bgcolor(color.green)
barcolor(close > 2 ? color.red : na)
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.bg_colors.len(), 1);
    assert_eq!(
        result.bg_colors[0].values,
        vec![
            PineValue::Na,
            PineValue::Color(0x4CAF50),
            PineValue::Color(0x4CAF50)
        ]
    );
    assert_eq!(result.bar_colors.len(), 1);
    assert_eq!(
        result.bar_colors[0].values,
        vec![PineValue::Na, PineValue::Na, PineValue::Color(0xF23645)]
    );
}

#[test]
fn collects_plotchar_series() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("plotchar")
if close > 1
    plotchar(close > 2, title="Marker", char="x", color=color.green, location=location.abovebar, offset=1, text="Up", textcolor=color.white, editable=true, size=size.small, show_last=5, display=display.all)
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plot_chars.len(), 1);
    assert_eq!(
        result.plot_chars[0].values,
        vec![PineValue::Na, PineValue::Bool(false), PineValue::Bool(true)]
    );
    assert_eq!(
        result.plot_chars[0].chars,
        vec![
            PineValue::Na,
            PineValue::String("x".to_owned()),
            PineValue::String("x".to_owned())
        ]
    );
    assert_eq!(
        result.plot_chars[0].colors,
        vec![
            PineValue::Na,
            PineValue::Color(0x4CAF50),
            PineValue::Color(0x4CAF50)
        ]
    );
}

#[test]
fn collects_plotshape_series() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("plotshape")
if close > 1
    plotshape(close > 2, title="Buy", style=shape.triangleup, location=location.belowbar, color=color.green, offset=1, text="Buy", textcolor=color.white, editable=true, size=size.small, show_last=5, display=display.all, force_overlay=false)
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plot_shapes.len(), 1);
    assert_eq!(
        result.plot_shapes[0].values,
        vec![PineValue::Na, PineValue::Bool(false), PineValue::Bool(true)]
    );
    assert_eq!(
        result.plot_shapes[0].styles,
        vec![
            PineValue::Na,
            PineValue::String("shape.triangleup".to_owned()),
            PineValue::String("shape.triangleup".to_owned())
        ]
    );
    assert_eq!(
        result.plot_shapes[0].locations,
        vec![
            PineValue::Na,
            PineValue::String("location.belowbar".to_owned()),
            PineValue::String("location.belowbar".to_owned())
        ]
    );
    assert_eq!(
        result.plot_shapes[0].colors,
        vec![
            PineValue::Na,
            PineValue::Color(0x4CAF50),
            PineValue::Color(0x4CAF50)
        ]
    );
    assert_eq!(
        result.plot_shapes[0].texts,
        vec![
            PineValue::Na,
            PineValue::String("Buy".to_owned()),
            PineValue::String("Buy".to_owned())
        ]
    );
    assert_eq!(
        result.plot_shapes[0].text_colors,
        vec![
            PineValue::Na,
            PineValue::Color(0xFFFFFF),
            PineValue::Color(0xFFFFFF)
        ]
    );
    assert_eq!(
        result.plot_shapes[0].sizes,
        vec![
            PineValue::Na,
            PineValue::String("size.small".to_owned()),
            PineValue::String("size.small".to_owned())
        ]
    );
}

#[test]
fn collects_plotarrow_series() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("plotarrow")
if close > 1
    plotarrow(close - 2, title="Momentum", colorup=color.green, colordown=color.red, offset=1, minheight=5, maxheight=20, editable=true, show_last=5, display=display.all, force_overlay=false)
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plot_arrows.len(), 1);
    assert_eq!(
        result.plot_arrows[0].values,
        vec![PineValue::Na, PineValue::Float(0.0), PineValue::Float(1.0)]
    );
    assert_eq!(
        result.plot_arrows[0].color_ups,
        vec![
            PineValue::Na,
            PineValue::Color(0x4CAF50),
            PineValue::Color(0x4CAF50)
        ]
    );
    assert_eq!(
        result.plot_arrows[0].color_downs,
        vec![
            PineValue::Na,
            PineValue::Color(0xF23645),
            PineValue::Color(0xF23645)
        ]
    );
    assert_eq!(
        result.plot_arrows[0].min_heights,
        vec![PineValue::Na, PineValue::Int(5), PineValue::Int(5)]
    );
    assert_eq!(
        result.plot_arrows[0].max_heights,
        vec![PineValue::Na, PineValue::Int(20), PineValue::Int(20)]
    );
}

#[test]
fn collects_plotbar_series() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("plotbar")
if close > 1
    plotbar(open, high, low, close, title="Bars", color=color.green, editable=true, show_last=5, display=display.all)
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        bar_ohlc(1.0, 2.0, 0.0, 1.0),
        bar_ohlc(2.0, 4.0, 1.0, 3.0),
        bar_ohlc(4.0, 6.0, 3.0, 5.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plot_bars.len(), 1);
    assert_eq!(
        result.plot_bars[0].opens,
        vec![PineValue::Na, PineValue::Float(2.0), PineValue::Float(4.0)]
    );
    assert_eq!(
        result.plot_bars[0].highs,
        vec![PineValue::Na, PineValue::Float(4.0), PineValue::Float(6.0)]
    );
    assert_eq!(
        result.plot_bars[0].lows,
        vec![PineValue::Na, PineValue::Float(1.0), PineValue::Float(3.0)]
    );
    assert_eq!(
        result.plot_bars[0].closes,
        vec![PineValue::Na, PineValue::Float(3.0), PineValue::Float(5.0)]
    );
    assert_eq!(
        result.plot_bars[0].colors,
        vec![
            PineValue::Na,
            PineValue::Color(0x4CAF50),
            PineValue::Color(0x4CAF50)
        ]
    );
}

#[test]
fn collects_plotcandle_series() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("plotcandle")
if close > 1
    plotcandle(open, high, low, close, title="Candles", color=color.green, wickcolor=color.white, editable=true, show_last=5, bordercolor=color.red, display=display.all)
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        bar_ohlc(1.0, 2.0, 0.0, 1.0),
        bar_ohlc(2.0, 4.0, 1.0, 3.0),
        bar_ohlc(4.0, 6.0, 3.0, 5.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plot_candles.len(), 1);
    assert_eq!(
        result.plot_candles[0].opens,
        vec![PineValue::Na, PineValue::Float(2.0), PineValue::Float(4.0)]
    );
    assert_eq!(
        result.plot_candles[0].highs,
        vec![PineValue::Na, PineValue::Float(4.0), PineValue::Float(6.0)]
    );
    assert_eq!(
        result.plot_candles[0].lows,
        vec![PineValue::Na, PineValue::Float(1.0), PineValue::Float(3.0)]
    );
    assert_eq!(
        result.plot_candles[0].closes,
        vec![PineValue::Na, PineValue::Float(3.0), PineValue::Float(5.0)]
    );
    assert_eq!(
        result.plot_candles[0].colors,
        vec![
            PineValue::Na,
            PineValue::Color(0x4CAF50),
            PineValue::Color(0x4CAF50)
        ]
    );
    assert_eq!(
        result.plot_candles[0].wick_colors,
        vec![
            PineValue::Na,
            PineValue::Color(0xFFFFFF),
            PineValue::Color(0xFFFFFF)
        ]
    );
    assert_eq!(
        result.plot_candles[0].border_colors,
        vec![
            PineValue::Na,
            PineValue::Color(0xF23645),
            PineValue::Color(0xF23645)
        ]
    );
}

#[test]
fn pads_conditional_plot_with_na_when_branch_is_skipped() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("conditional plot")
if close > open
    plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![
        bar_ohlc(1.0, 2.0, 1.0, 2.0),
        bar_ohlc(3.0, 3.0, 2.0, 2.0),
        bar_ohlc(4.0, 6.0, 4.0, 6.0),
    ];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 1);
    assert_eq!(
        result.plots[0].values,
        vec![PineValue::Float(2.0), PineValue::Na, PineValue::Float(6.0)]
    );
}
