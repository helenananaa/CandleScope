use crate::{PineValue, RuntimeProfile};

mod profile;

use super::alerts::AlertEvent;
use super::drawings::{
    BoxOutput, LabelOutput, LineFillOutput, LineOutput, PolylineOutput, TableOutput,
};
use super::model::{
    ColorSeries, FillOutput, HLineOutput, PUBLIC_RENDER_METADATA_VERSION,
    PUBLIC_RUNTIME_SCHEMA_VERSION, PlotArrowSeries, PlotBarSeries, PlotCandleSeries,
    PlotCharSeries, PlotSeries, PlotShapeSeries, RuntimeResult,
};
use super::strategy::StrategyResult;
use profile::profile_json;

pub fn public_runtime_result_json(result: &RuntimeResult) -> String {
    let mut output = format!("{{\"schemaVersion\":{},", PUBLIC_RUNTIME_SCHEMA_VERSION);
    output.push_str(&format!(
        "\"renderMetadataVersion\":{},",
        PUBLIC_RENDER_METADATA_VERSION
    ));
    output.push_str("\"plots\":");
    output.push_str(&plots_json(&result.plots));
    output.push_str(",\"plotChars\":");
    output.push_str(&plot_chars_json(&result.plot_chars));
    output.push_str(",\"plotShapes\":");
    output.push_str(&plot_shapes_json(&result.plot_shapes));
    output.push_str(",\"plotArrows\":");
    output.push_str(&plot_arrows_json(&result.plot_arrows));
    output.push_str(",\"plotBars\":");
    output.push_str(&plot_bars_json(&result.plot_bars));
    output.push_str(",\"plotCandles\":");
    output.push_str(&plot_candles_json(&result.plot_candles));
    output.push_str(",\"bgColors\":");
    output.push_str(&colors_json(&result.bg_colors));
    output.push_str(",\"barColors\":");
    output.push_str(&colors_json(&result.bar_colors));
    output.push_str(",\"hlines\":");
    output.push_str(&hlines_json(&result.hlines));
    output.push_str(",\"fills\":");
    output.push_str(&fills_json(&result.fills));
    output.push_str(",\"labels\":");
    output.push_str(&labels_json(&result.labels));
    output.push_str(",\"lines\":");
    output.push_str(&lines_json(&result.lines));
    output.push_str(",\"lineFills\":");
    output.push_str(&line_fills_json(&result.line_fills));
    output.push_str(",\"polylines\":");
    output.push_str(&polylines_json(&result.polylines));
    output.push_str(",\"boxes\":");
    output.push_str(&boxes_json(&result.boxes));
    output.push_str(",\"tables\":");
    output.push_str(&tables_json(&result.tables));
    output.push_str(",\"alerts\":");
    output.push_str(&alerts_json(&result.alerts));
    if let Some(strategy) = &result.strategy {
        output.push_str(",\"strategy\":");
        output.push_str(&strategy_json(strategy));
    }
    output.push_str(",\"diagnostics\":");
    output.push_str(&runtime_diagnostics_json(&result.diagnostics));
    output.push('}');
    output
}

pub fn public_runtime_profiled_result_json(
    result: &RuntimeResult,
    profile: &RuntimeProfile,
) -> String {
    let mut output = public_runtime_result_json(result);
    output.pop();
    output.push_str(",\"profile\":");
    output.push_str(&profile_json(profile));
    output.push('}');
    output
}

fn plots_json(plots: &[PlotSeries]) -> String {
    let mut output = String::from("[");
    for (plot_index, plot) in plots.iter().enumerate() {
        if plot_index > 0 {
            output.push(',');
        }
        output.push_str(&format!("{{\"id\":{},\"values\":[", plot.id));
        values_json_into(&mut output, &plot.values);
        output.push(']');
        if plot.colors.iter().any(|value| *value != PineValue::Na) {
            push_values_field(&mut output, "colors", &plot.colors);
        }
        push_non_default_value_field(
            &mut output,
            "linewidth",
            &plot.linewidth,
            &PineValue::Int(1),
        );
        push_non_default_value_field(
            &mut output,
            "style",
            &plot.style,
            &PineValue::String("plot.style_line".to_owned()),
        );
        push_non_default_value_field(
            &mut output,
            "trackPrice",
            &plot.track_price,
            &PineValue::Bool(false),
        );
        push_non_default_value_field(&mut output, "histBase", &plot.hist_base, &PineValue::Int(0));
        push_non_default_value_field(&mut output, "join", &plot.join, &PineValue::Bool(false));
        push_non_default_value_field(
            &mut output,
            "format",
            &plot.format,
            &PineValue::String("format.inherit".to_owned()),
        );
        push_non_default_value_field(&mut output, "precision", &plot.precision, &PineValue::Na);
        output_metadata_json_into(&mut output, &plot.metadata);
        output.push('}');
    }
    output.push(']');
    output
}

fn colors_json(colors: &[ColorSeries]) -> String {
    let mut output = String::from("[");
    for (color_index, colors) in colors.iter().enumerate() {
        if color_index > 0 {
            output.push(',');
        }
        output.push_str(&format!("{{\"id\":{},\"values\":[", colors.id));
        values_json_into(&mut output, &colors.values);
        output.push(']');
        output_metadata_json_into(&mut output, &colors.metadata);
        output.push('}');
    }
    output.push(']');
    output
}

fn plot_chars_json(plot_chars: &[PlotCharSeries]) -> String {
    let mut output = String::from("[");
    for (plot_char_index, plot_char) in plot_chars.iter().enumerate() {
        if plot_char_index > 0 {
            output.push(',');
        }
        output.push_str(&format!("{{\"id\":{},\"values\":[", plot_char.id));
        values_json_into(&mut output, &plot_char.values);
        output.push_str("],\"chars\":[");
        values_json_into(&mut output, &plot_char.chars);
        output.push_str("],\"colors\":[");
        values_json_into(&mut output, &plot_char.colors);
        output.push_str("],\"locations\":[");
        values_json_into(&mut output, &plot_char.locations);
        output.push_str("],\"texts\":[");
        values_json_into(&mut output, &plot_char.texts);
        output.push_str("],\"textColors\":[");
        values_json_into(&mut output, &plot_char.text_colors);
        output.push_str("],\"sizes\":[");
        values_json_into(&mut output, &plot_char.sizes);
        output.push(']');
        output_metadata_json_into(&mut output, &plot_char.metadata);
        output.push('}');
    }
    output.push(']');
    output
}

fn plot_shapes_json(plot_shapes: &[PlotShapeSeries]) -> String {
    let mut output = String::from("[");
    for (plot_shape_index, plot_shape) in plot_shapes.iter().enumerate() {
        if plot_shape_index > 0 {
            output.push(',');
        }
        output.push_str(&format!("{{\"id\":{},\"values\":[", plot_shape.id));
        values_json_into(&mut output, &plot_shape.values);
        output.push_str("],\"styles\":[");
        values_json_into(&mut output, &plot_shape.styles);
        output.push_str("],\"locations\":[");
        values_json_into(&mut output, &plot_shape.locations);
        output.push_str("],\"colors\":[");
        values_json_into(&mut output, &plot_shape.colors);
        output.push_str("],\"texts\":[");
        values_json_into(&mut output, &plot_shape.texts);
        output.push_str("],\"textColors\":[");
        values_json_into(&mut output, &plot_shape.text_colors);
        output.push_str("],\"sizes\":[");
        values_json_into(&mut output, &plot_shape.sizes);
        output.push(']');
        output_metadata_json_into(&mut output, &plot_shape.metadata);
        output.push('}');
    }
    output.push(']');
    output
}

fn plot_arrows_json(plot_arrows: &[PlotArrowSeries]) -> String {
    let mut output = String::from("[");
    for (plot_arrow_index, plot_arrow) in plot_arrows.iter().enumerate() {
        if plot_arrow_index > 0 {
            output.push(',');
        }
        output.push_str(&format!("{{\"id\":{},\"values\":[", plot_arrow.id));
        values_json_into(&mut output, &plot_arrow.values);
        output.push_str("],\"colorUps\":[");
        values_json_into(&mut output, &plot_arrow.color_ups);
        output.push_str("],\"colorDowns\":[");
        values_json_into(&mut output, &plot_arrow.color_downs);
        output.push_str("],\"minHeights\":[");
        values_json_into(&mut output, &plot_arrow.min_heights);
        output.push_str("],\"maxHeights\":[");
        values_json_into(&mut output, &plot_arrow.max_heights);
        output.push(']');
        output_metadata_json_into(&mut output, &plot_arrow.metadata);
        output.push('}');
    }
    output.push(']');
    output
}

fn plot_bars_json(plot_bars: &[PlotBarSeries]) -> String {
    let mut output = String::from("[");
    for (plot_bar_index, plot_bar) in plot_bars.iter().enumerate() {
        if plot_bar_index > 0 {
            output.push(',');
        }
        output.push_str(&format!("{{\"id\":{},\"opens\":[", plot_bar.id));
        values_json_into(&mut output, &plot_bar.opens);
        output.push_str("],\"highs\":[");
        values_json_into(&mut output, &plot_bar.highs);
        output.push_str("],\"lows\":[");
        values_json_into(&mut output, &plot_bar.lows);
        output.push_str("],\"closes\":[");
        values_json_into(&mut output, &plot_bar.closes);
        output.push_str("],\"colors\":[");
        values_json_into(&mut output, &plot_bar.colors);
        output.push(']');
        output_metadata_json_into(&mut output, &plot_bar.metadata);
        output.push('}');
    }
    output.push(']');
    output
}

fn plot_candles_json(plot_candles: &[PlotCandleSeries]) -> String {
    let mut output = String::from("[");
    for (plot_candle_index, plot_candle) in plot_candles.iter().enumerate() {
        if plot_candle_index > 0 {
            output.push(',');
        }
        output.push_str(&format!("{{\"id\":{},\"opens\":[", plot_candle.id));
        values_json_into(&mut output, &plot_candle.opens);
        output.push_str("],\"highs\":[");
        values_json_into(&mut output, &plot_candle.highs);
        output.push_str("],\"lows\":[");
        values_json_into(&mut output, &plot_candle.lows);
        output.push_str("],\"closes\":[");
        values_json_into(&mut output, &plot_candle.closes);
        output.push_str("],\"colors\":[");
        values_json_into(&mut output, &plot_candle.colors);
        output.push_str("],\"wickColors\":[");
        values_json_into(&mut output, &plot_candle.wick_colors);
        output.push_str("],\"borderColors\":[");
        values_json_into(&mut output, &plot_candle.border_colors);
        output.push(']');
        output_metadata_json_into(&mut output, &plot_candle.metadata);
        output.push('}');
    }
    output.push(']');
    output
}

fn values_json_into(output: &mut String, values: &[PineValue]) {
    for (value_index, value) in values.iter().enumerate() {
        if value_index > 0 {
            output.push(',');
        }
        output.push_str(&value_json(value));
    }
}

fn push_values_field(output: &mut String, name: &str, values: &[PineValue]) {
    output.push_str(&format!(",\"{name}\":["));
    values_json_into(output, values);
    output.push(']');
}

fn push_value_field(output: &mut String, name: &str, value: &PineValue) {
    output.push_str(&format!(",\"{name}\":"));
    output.push_str(&value_json(value));
}

fn push_non_default_value_field(
    output: &mut String,
    name: &str,
    value: &PineValue,
    default: &PineValue,
) {
    if value != default {
        push_value_field(output, name, value);
    }
}

fn output_metadata_json_into(output: &mut String, metadata: &super::model::OutputMetadata) {
    push_non_default_value_field(
        output,
        "title",
        &metadata.title,
        &PineValue::String(String::new()),
    );
    push_non_default_value_field(output, "offset", &metadata.offset, &PineValue::Int(0));
    push_non_default_value_field(
        output,
        "editable",
        &metadata.editable,
        &PineValue::Bool(true),
    );
    push_non_default_value_field(output, "showLast", &metadata.show_last, &PineValue::Na);
    push_non_default_value_field(
        output,
        "display",
        &metadata.display,
        &PineValue::String("display.all".to_owned()),
    );
    push_non_default_value_field(
        output,
        "forceOverlay",
        &metadata.force_overlay,
        &PineValue::Bool(false),
    );
}

fn hlines_json(hlines: &[HLineOutput]) -> String {
    let mut output = String::from("[");
    for (index, hline) in hlines.iter().enumerate() {
        if index > 0 {
            output.push(',');
        }
        output.push_str(&format!(
            "{{\"id\":{},\"price\":{}",
            hline.id,
            value_json(&hline.price)
        ));
        push_non_default_value_field(
            &mut output,
            "title",
            &hline.title,
            &PineValue::String(String::new()),
        );
        push_non_default_value_field(
            &mut output,
            "color",
            &hline.color,
            &PineValue::Color(0x787B86),
        );
        push_non_default_value_field(
            &mut output,
            "style",
            &hline.style,
            &PineValue::String("hline.style_solid".to_owned()),
        );
        push_non_default_value_field(
            &mut output,
            "linewidth",
            &hline.linewidth,
            &PineValue::Int(1),
        );
        push_non_default_value_field(
            &mut output,
            "editable",
            &hline.editable,
            &PineValue::Bool(true),
        );
        push_non_default_value_field(
            &mut output,
            "display",
            &hline.display,
            &PineValue::String("display.all".to_owned()),
        );
        output.push('}');
    }
    output.push(']');
    output
}

fn fills_json(fills: &[FillOutput]) -> String {
    let mut output = String::from("[");
    for (index, fill) in fills.iter().enumerate() {
        if index > 0 {
            output.push(',');
        }
        output.push_str(&format!(
            "{{\"id\":{},\"firstId\":{},\"secondId\":{},\"firstIsHLine\":{},\"secondIsHLine\":{}",
            fill.id, fill.first_id, fill.second_id, fill.first_is_hline, fill.second_is_hline
        ));
        push_values_field(&mut output, "colors", &fill.colors);
        push_non_default_value_field(
            &mut output,
            "title",
            &fill.title,
            &PineValue::String(String::new()),
        );
        push_non_default_value_field(
            &mut output,
            "editable",
            &fill.editable,
            &PineValue::Bool(true),
        );
        push_non_default_value_field(&mut output, "showLast", &fill.show_last, &PineValue::Na);
        push_non_default_value_field(
            &mut output,
            "fillGaps",
            &fill.fill_gaps,
            &PineValue::Bool(true),
        );
        push_non_default_value_field(
            &mut output,
            "display",
            &fill.display,
            &PineValue::String("display.all".to_owned()),
        );
        output.push('}');
    }
    output.push(']');
    output
}

fn labels_json(labels: &[LabelOutput]) -> String {
    let mut output = String::from("[");
    for (index, label) in labels.iter().enumerate() {
        if index > 0 {
            output.push(',');
        }
        output.push_str(&format!("{{\"id\":{},\"snapshots\":[", label.id));
        for (snapshot_index, snapshot) in label.snapshots.iter().enumerate() {
            if snapshot_index > 0 {
                output.push(',');
            }
            output.push_str(&format!(
                "{{\"barIndex\":{},\"exists\":{}",
                snapshot.bar_index, snapshot.exists
            ));
            if snapshot.exists {
                output.push_str(",\"x\":");
                output.push_str(&value_json(&snapshot.x));
                output.push_str(",\"y\":");
                output.push_str(&value_json(&snapshot.y));
                output.push_str(",\"text\":");
                output.push_str(&value_json(&snapshot.text));
                output.push_str(",\"xloc\":");
                output.push_str(&value_json(&snapshot.xloc));
                output.push_str(",\"yloc\":");
                output.push_str(&value_json(&snapshot.yloc));
                output.push_str(",\"color\":");
                output.push_str(&value_json(&snapshot.color));
                output.push_str(",\"style\":");
                output.push_str(&value_json(&snapshot.style));
                output.push_str(",\"textColor\":");
                output.push_str(&value_json(&snapshot.text_color));
                output.push_str(",\"size\":");
                output.push_str(&value_json(&snapshot.size));
                output.push_str(",\"tooltip\":");
                output.push_str(&value_json(&snapshot.tooltip));
                output.push_str(",\"textAlign\":");
                output.push_str(&value_json(&snapshot.text_align));
                output.push_str(",\"textFontFamily\":");
                output.push_str(&value_json(&snapshot.text_font_family));
                output.push_str(",\"textFormatting\":");
                output.push_str(&value_json(&snapshot.text_formatting));
            }
            output.push('}');
        }
        output.push_str("]}");
    }
    output.push(']');
    output
}

fn lines_json(lines: &[LineOutput]) -> String {
    let mut output = String::from("[");
    for (index, line) in lines.iter().enumerate() {
        if index > 0 {
            output.push(',');
        }
        output.push_str(&format!("{{\"id\":{},\"snapshots\":[", line.id));
        for (snapshot_index, snapshot) in line.snapshots.iter().enumerate() {
            if snapshot_index > 0 {
                output.push(',');
            }
            output.push_str(&format!(
                "{{\"barIndex\":{},\"exists\":{}",
                snapshot.bar_index, snapshot.exists
            ));
            if snapshot.exists {
                output.push_str(",\"x1\":");
                output.push_str(&value_json(&snapshot.x1));
                output.push_str(",\"y1\":");
                output.push_str(&value_json(&snapshot.y1));
                output.push_str(",\"x2\":");
                output.push_str(&value_json(&snapshot.x2));
                output.push_str(",\"y2\":");
                output.push_str(&value_json(&snapshot.y2));
                output.push_str(",\"xloc\":");
                output.push_str(&value_json(&snapshot.xloc));
                output.push_str(",\"color\":");
                output.push_str(&value_json(&snapshot.color));
                output.push_str(",\"width\":");
                output.push_str(&value_json(&snapshot.width));
                output.push_str(",\"style\":");
                output.push_str(&value_json(&snapshot.style));
                output.push_str(",\"extend\":");
                output.push_str(&value_json(&snapshot.extend));
            }
            output.push('}');
        }
        output.push_str("]}");
    }
    output.push(']');
    output
}

fn line_fills_json(line_fills: &[LineFillOutput]) -> String {
    let mut output = String::from("[");
    for (index, line_fill) in line_fills.iter().enumerate() {
        if index > 0 {
            output.push(',');
        }
        output.push_str(&format!("{{\"id\":{},\"snapshots\":[", line_fill.id));
        for (snapshot_index, snapshot) in line_fill.snapshots.iter().enumerate() {
            if snapshot_index > 0 {
                output.push(',');
            }
            output.push_str(&format!(
                "{{\"barIndex\":{},\"exists\":{}",
                snapshot.bar_index, snapshot.exists
            ));
            if snapshot.exists {
                output.push_str(",\"line1\":");
                output.push_str(&snapshot.line1.to_string());
                output.push_str(",\"line2\":");
                output.push_str(&snapshot.line2.to_string());
                output.push_str(",\"color\":");
                output.push_str(&value_json(&snapshot.color));
            }
            output.push('}');
        }
        output.push_str("]}");
    }
    output.push(']');
    output
}

fn polylines_json(polylines: &[PolylineOutput]) -> String {
    let mut output = String::from("[");
    for (index, polyline) in polylines.iter().enumerate() {
        if index > 0 {
            output.push(',');
        }
        output.push_str(&format!("{{\"id\":{},\"snapshots\":[", polyline.id));
        for (snapshot_index, snapshot) in polyline.snapshots.iter().enumerate() {
            if snapshot_index > 0 {
                output.push(',');
            }
            output.push_str(&format!(
                "{{\"barIndex\":{},\"exists\":{}",
                snapshot.bar_index, snapshot.exists
            ));
            if snapshot.exists {
                output.push_str(",\"points\":");
                output.push_str(&values_json(&snapshot.points));
                output.push_str(",\"curved\":");
                output.push_str(&value_json(&snapshot.curved));
                output.push_str(",\"closed\":");
                output.push_str(&value_json(&snapshot.closed));
                output.push_str(",\"xloc\":");
                output.push_str(&value_json(&snapshot.xloc));
                output.push_str(",\"lineColor\":");
                output.push_str(&value_json(&snapshot.line_color));
                output.push_str(",\"fillColor\":");
                output.push_str(&value_json(&snapshot.fill_color));
                output.push_str(",\"lineStyle\":");
                output.push_str(&value_json(&snapshot.line_style));
                output.push_str(",\"lineWidth\":");
                output.push_str(&value_json(&snapshot.line_width));
                output.push_str(",\"forceOverlay\":");
                output.push_str(&value_json(&snapshot.force_overlay));
            }
            output.push('}');
        }
        output.push_str("]}");
    }
    output.push(']');
    output
}

fn boxes_json(boxes: &[BoxOutput]) -> String {
    let mut output = String::from("[");
    for (index, box_output) in boxes.iter().enumerate() {
        if index > 0 {
            output.push(',');
        }
        output.push_str(&format!("{{\"id\":{},\"snapshots\":[", box_output.id));
        for (snapshot_index, snapshot) in box_output.snapshots.iter().enumerate() {
            if snapshot_index > 0 {
                output.push(',');
            }
            output.push_str(&format!(
                "{{\"barIndex\":{},\"exists\":{}",
                snapshot.bar_index, snapshot.exists
            ));
            if snapshot.exists {
                output.push_str(",\"left\":");
                output.push_str(&value_json(&snapshot.left));
                output.push_str(",\"top\":");
                output.push_str(&value_json(&snapshot.top));
                output.push_str(",\"right\":");
                output.push_str(&value_json(&snapshot.right));
                output.push_str(",\"bottom\":");
                output.push_str(&value_json(&snapshot.bottom));
                output.push_str(",\"xloc\":");
                output.push_str(&value_json(&snapshot.xloc));
                output.push_str(",\"bgColor\":");
                output.push_str(&value_json(&snapshot.bg_color));
                output.push_str(",\"borderColor\":");
                output.push_str(&value_json(&snapshot.border_color));
                output.push_str(",\"borderWidth\":");
                output.push_str(&value_json(&snapshot.border_width));
                output.push_str(",\"borderStyle\":");
                output.push_str(&value_json(&snapshot.border_style));
                output.push_str(",\"extend\":");
                output.push_str(&value_json(&snapshot.extend));
                output.push_str(",\"text\":");
                output.push_str(&value_json(&snapshot.text));
                output.push_str(",\"textColor\":");
                output.push_str(&value_json(&snapshot.text_color));
                output.push_str(",\"textSize\":");
                output.push_str(&value_json(&snapshot.text_size));
                output.push_str(",\"textHalign\":");
                output.push_str(&value_json(&snapshot.text_halign));
                output.push_str(",\"textValign\":");
                output.push_str(&value_json(&snapshot.text_valign));
                output.push_str(",\"textWrap\":");
                output.push_str(&value_json(&snapshot.text_wrap));
                output.push_str(",\"textFontFamily\":");
                output.push_str(&value_json(&snapshot.text_font_family));
                output.push_str(",\"textFormatting\":");
                output.push_str(&value_json(&snapshot.text_formatting));
            }
            output.push('}');
        }
        output.push_str("]}");
    }
    output.push(']');
    output
}

fn tables_json(tables: &[TableOutput]) -> String {
    let mut output = String::from("[");
    for (index, table) in tables.iter().enumerate() {
        if index > 0 {
            output.push(',');
        }
        output.push_str(&format!("{{\"id\":{},\"position\":", table.id));
        output.push_str(&value_json(&table.position));
        output.push_str(",\"bgColor\":");
        output.push_str(&value_json(&table.bg_color));
        output.push_str(",\"frameColor\":");
        output.push_str(&value_json(&table.frame_color));
        output.push_str(",\"frameWidth\":");
        output.push_str(&value_json(&table.frame_width));
        output.push_str(",\"borderColor\":");
        output.push_str(&value_json(&table.border_color));
        output.push_str(",\"borderWidth\":");
        output.push_str(&value_json(&table.border_width));
        output.push_str(&format!(
            ",\"columns\":{},\"rows\":{},\"snapshots\":[",
            table.columns, table.rows
        ));
        for (snapshot_index, snapshot) in table.snapshots.iter().enumerate() {
            if snapshot_index > 0 {
                output.push(',');
            }
            output.push_str(&format!(
                "{{\"barIndex\":{},\"exists\":{}",
                snapshot.bar_index, snapshot.exists
            ));
            if snapshot.exists {
                output.push_str(",\"cells\":[");
                for (cell_index, cell) in snapshot.cells.iter().enumerate() {
                    if cell_index > 0 {
                        output.push(',');
                    }
                    output.push_str(&format!(
                        "{{\"column\":{},\"row\":{},\"text\":",
                        cell.column, cell.row
                    ));
                    output.push_str(&value_json(&cell.text));
                    output.push_str(",\"bgColor\":");
                    output.push_str(&value_json(&cell.bg_color));
                    output.push_str(",\"textColor\":");
                    output.push_str(&value_json(&cell.text_color));
                    output.push_str(",\"width\":");
                    output.push_str(&value_json(&cell.width));
                    output.push_str(",\"height\":");
                    output.push_str(&value_json(&cell.height));
                    output.push_str(",\"textSize\":");
                    output.push_str(&value_json(&cell.text_size));
                    output.push_str(",\"textHalign\":");
                    output.push_str(&value_json(&cell.text_halign));
                    output.push_str(",\"textValign\":");
                    output.push_str(&value_json(&cell.text_valign));
                    output.push_str(",\"textWrap\":");
                    output.push_str(&value_json(&cell.text_wrap));
                    output.push_str(",\"tooltip\":");
                    output.push_str(&value_json(&cell.tooltip));
                    output.push_str(",\"textFontFamily\":");
                    output.push_str(&value_json(&cell.text_font_family));
                    output.push_str(",\"textFormatting\":");
                    output.push_str(&value_json(&cell.text_formatting));
                    output.push('}');
                }
                output.push(']');
                output.push_str(",\"mergedCells\":[");
                for (merge_index, merged_cell) in snapshot.merged_cells.iter().enumerate() {
                    if merge_index > 0 {
                        output.push(',');
                    }
                    output.push_str(&format!(
                        "{{\"startColumn\":{},\"startRow\":{},\"endColumn\":{},\"endRow\":{}}}",
                        merged_cell.start_column,
                        merged_cell.start_row,
                        merged_cell.end_column,
                        merged_cell.end_row
                    ));
                }
                output.push(']');
            }
            output.push('}');
        }
        output.push_str("]}");
    }
    output.push(']');
    output
}

fn alerts_json(alerts: &[AlertEvent]) -> String {
    let mut output = String::from("[");
    for (index, alert) in alerts.iter().enumerate() {
        if index > 0 {
            output.push(',');
        }
        output.push_str(&format!(
            "{{\"id\":{},\"barIndex\":{},\"time\":{},\"message\":\"{}\",\"source\":\"{}\"}}",
            alert.id,
            alert.bar_index,
            alert.time,
            json_escape(&alert.message),
            json_escape(&alert.source)
        ));
    }
    output.push(']');
    output
}

fn strategy_json(strategy: &StrategyResult) -> String {
    format!(
        "{{\"orders\":{},\"trades\":{},\"position\":{},\"equity\":{},\"alerts\":{},\"diagnostics\":{}}}",
        strategy_orders_json(&strategy.orders),
        strategy_trades_json(&strategy.trades),
        strategy_position_json(&strategy.position),
        strategy_equity_json(&strategy.equity),
        strategy_order_fill_alerts_json(&strategy.alerts),
        runtime_diagnostics_json(&strategy.diagnostics)
    )
}

fn strategy_orders_json(orders: &[crate::StrategyOrderEvent]) -> String {
    let mut output = String::from("[");
    for (index, order) in orders.iter().enumerate() {
        if index > 0 {
            output.push(',');
        }
        output.push_str(&format!(
            "{{\"id\":\"{}\",\"barIndex\":{},\"time\":{},\"direction\":\"{}\",\"qty\":{},\"price\":{}}}",
            json_escape(&order.id),
            order.bar_index,
            order.time,
            json_escape(&order.direction),
            f64_json(order.qty),
            f64_json(order.price)
        ));
    }
    output.push(']');
    output
}

fn strategy_order_fill_alerts_json(alerts: &[crate::StrategyOrderFillAlertOutput]) -> String {
    let mut output = String::from("[");
    for (index, alert) in alerts.iter().enumerate() {
        if index > 0 {
            output.push(',');
        }
        output.push_str(&format!(
            "{{\"id\":\"{}\",\"barIndex\":{},\"time\":{},\"direction\":\"{}\",\"qty\":{},\"price\":{},\"entryId\":{},\"exitId\":{},\"message\":\"{}\"}}",
            json_escape(&alert.id),
            alert.bar_index,
            alert.time,
            json_escape(&alert.direction),
            f64_json(alert.qty),
            f64_json(alert.price),
            option_string_json(alert.entry_id.as_deref()),
            option_string_json(alert.exit_id.as_deref()),
            json_escape(&alert.message)
        ));
    }
    output.push(']');
    output
}

fn strategy_trades_json(trades: &[crate::StrategyTrade]) -> String {
    let mut output = String::from("[");
    for (index, trade) in trades.iter().enumerate() {
        if index > 0 {
            output.push(',');
        }
        output.push_str(&format!(
            "{{\"id\":\"{}\",\"entryBarIndex\":{},\"exitBarIndex\":{},\"entryTime\":{},\"exitTime\":{},\"entryPrice\":{},\"exitPrice\":{},\"qty\":{},\"profit\":{}}}",
            json_escape(&trade.id),
            trade.entry_bar_index,
            trade.exit_bar_index,
            trade.entry_time,
            trade.exit_time,
            f64_json(trade.entry_price),
            f64_json(trade.exit_price),
            f64_json(trade.qty),
            f64_json(trade.profit)
        ));
    }
    output.push(']');
    output
}

fn strategy_position_json(position: &[crate::StrategyPositionSnapshot]) -> String {
    let mut output = String::from("[");
    for (index, snapshot) in position.iter().enumerate() {
        if index > 0 {
            output.push(',');
        }
        output.push_str(&format!(
            "{{\"barIndex\":{},\"size\":{},\"avgPrice\":{}}}",
            snapshot.bar_index,
            f64_json(snapshot.size),
            option_f64_json(snapshot.avg_price)
        ));
    }
    output.push(']');
    output
}

fn strategy_equity_json(equity: &[crate::StrategyEquitySnapshot]) -> String {
    let mut output = String::from("[");
    for (index, snapshot) in equity.iter().enumerate() {
        if index > 0 {
            output.push(',');
        }
        output.push_str(&format!(
            "{{\"barIndex\":{},\"cash\":{},\"marketValue\":{},\"equity\":{},\"netProfit\":{}}}",
            snapshot.bar_index,
            f64_json(snapshot.cash),
            f64_json(snapshot.market_value),
            f64_json(snapshot.equity),
            f64_json(snapshot.net_profit)
        ));
    }
    output.push(']');
    output
}

fn option_f64_json(value: Option<f64>) -> String {
    value.map_or_else(|| "null".to_owned(), f64_json)
}

fn option_string_json(value: Option<&str>) -> String {
    value.map_or_else(
        || "null".to_owned(),
        |value| format!("\"{}\"", json_escape(value)),
    )
}

fn f64_json(value: f64) -> String {
    if value.is_finite() {
        value.to_string()
    } else {
        "null".to_owned()
    }
}

fn runtime_diagnostics_json(diagnostics: &[crate::RuntimeDiagnostic]) -> String {
    let mut output = String::from("[");
    for (index, diagnostic) in diagnostics.iter().enumerate() {
        if index > 0 {
            output.push(',');
        }
        output.push_str(&format!(
            "{{\"code\":\"{}\",\"message\":\"{}\"}}",
            json_escape(&diagnostic.code),
            json_escape(&diagnostic.message)
        ));
    }
    output.push(']');
    output
}

fn values_json(values: &[PineValue]) -> String {
    let mut output = String::from("[");
    for (index, value) in values.iter().enumerate() {
        if index > 0 {
            output.push(',');
        }
        output.push_str(&value_json(value));
    }
    output.push(']');
    output
}

fn value_json(value: &PineValue) -> String {
    match value {
        PineValue::Int(value) => value.to_string(),
        PineValue::Float(value) => f64_json(*value),
        PineValue::Bool(value) => value.to_string(),
        PineValue::String(value) => format!("\"{}\"", json_escape(value)),
        PineValue::Color(value) => value.to_string(),
        PineValue::Plot(value)
        | PineValue::HLine(value)
        | PineValue::Label(value)
        | PineValue::Line(value)
        | PineValue::LineFill(value)
        | PineValue::Polyline(value)
        | PineValue::Box(value)
        | PineValue::Table(value) => value.to_string(),
        PineValue::ChartPoint(point) => format!(
            "{{\"time\":{},\"index\":{},\"price\":{}}}",
            value_json(&point.time),
            value_json(&point.index),
            value_json(&point.price)
        ),
        PineValue::UserType(values) | PineValue::Tuple(values) => {
            let mut output = String::from("[");
            for (index, value) in values.iter().enumerate() {
                if index > 0 {
                    output.push(',');
                }
                output.push_str(&value_json(value));
            }
            output.push(']');
            output
        }
        PineValue::Array(_)
        | PineValue::Matrix(_)
        | PineValue::Map(_)
        | PineValue::Na
        | PineValue::Void => "null".to_owned(),
    }
}

fn json_escape(value: &str) -> String {
    let mut escaped = String::with_capacity(value.len());
    for ch in value.chars() {
        match ch {
            '"' => escaped.push_str("\\\""),
            '\\' => escaped.push_str("\\\\"),
            '\n' => escaped.push_str("\\n"),
            '\r' => escaped.push_str("\\r"),
            '\t' => escaped.push_str("\\t"),
            '\u{08}' => escaped.push_str("\\b"),
            '\u{0C}' => escaped.push_str("\\f"),
            ch if (ch as u32) < 0x20 => {
                escaped.push_str(&format!("\\u{:04x}", ch as u32));
            }
            ch => escaped.push(ch),
        }
    }
    escaped
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        RuntimeDiagnostic, StrategyEquitySnapshot, StrategyOrderEvent,
        StrategyOrderFillAlertOutput, StrategyPositionSnapshot, StrategyTrade,
    };

    fn empty_result() -> RuntimeResult {
        RuntimeResult {
            plots: Vec::new(),
            plot_chars: Vec::new(),
            plot_shapes: Vec::new(),
            plot_arrows: Vec::new(),
            plot_bars: Vec::new(),
            plot_candles: Vec::new(),
            bg_colors: Vec::new(),
            bar_colors: Vec::new(),
            hlines: Vec::new(),
            fills: Vec::new(),
            labels: Vec::new(),
            lines: Vec::new(),
            line_fills: Vec::new(),
            polylines: Vec::new(),
            boxes: Vec::new(),
            tables: Vec::new(),
            alerts: Vec::new(),
            strategy: None,
            diagnostics: Vec::new(),
        }
    }

    #[test]
    fn runtime_json_serializes_non_finite_plot_floats_as_null() {
        let mut result = empty_result();
        result.plots.push(PlotSeries::new(
            1,
            vec![
                PineValue::Float(f64::NAN),
                PineValue::Float(f64::INFINITY),
                PineValue::Float(1.5),
            ],
        ));

        let output = public_runtime_result_json(&result);

        assert!(output.contains(r#""values":[null,null,1.5]"#));
        assert!(!output.contains("NaN"));
        assert!(!output.contains("inf"));
    }

    #[test]
    fn runtime_json_serializes_top_level_diagnostics() {
        let mut result = empty_result();
        result.diagnostics.push(RuntimeDiagnostic {
            code: "E_RUNTIME".to_owned(),
            message: "runtime \"warning\"\nline".to_owned(),
        });

        let output = public_runtime_result_json(&result);

        assert!(
            output.contains(
                r#""diagnostics":[{"code":"E_RUNTIME","message":"runtime \"warning\"\nline"}]"#
            ),
            "{output}"
        );
    }

    #[test]
    fn runtime_json_serializes_non_finite_strategy_floats_as_null() {
        let mut result = empty_result();
        result.strategy = Some(StrategyResult {
            orders: vec![StrategyOrderEvent {
                id: "O".to_owned(),
                bar_index: 0,
                time: 10,
                direction: "long".to_owned(),
                qty: f64::INFINITY,
                price: f64::NAN,
            }],
            trades: vec![StrategyTrade {
                id: "T".to_owned(),
                exit_id: "X".to_owned(),
                entry_bar_index: 0,
                exit_bar_index: 1,
                entry_time: 10,
                exit_time: 20,
                entry_price: f64::NAN,
                exit_price: f64::NEG_INFINITY,
                qty: 1.0,
                profit: f64::INFINITY,
            }],
            position: vec![StrategyPositionSnapshot {
                bar_index: 0,
                size: f64::INFINITY,
                avg_price: Some(f64::NAN),
            }],
            equity: vec![StrategyEquitySnapshot {
                bar_index: 0,
                cash: f64::NAN,
                market_value: f64::INFINITY,
                equity: f64::NEG_INFINITY,
                net_profit: 2.0,
            }],
            alerts: vec![StrategyOrderFillAlertOutput {
                id: "A".to_owned(),
                bar_index: 0,
                time: 10,
                direction: "strategy.exit".to_owned(),
                qty: f64::INFINITY,
                price: f64::NAN,
                entry_id: Some("T".to_owned()),
                exit_id: None,
                message: "message".to_owned(),
            }],
            diagnostics: Vec::new(),
        });

        let output = public_runtime_result_json(&result);

        assert!(output.contains(r#""qty":null,"price":null"#));
        assert!(output.contains(r#""entryPrice":null,"exitPrice":null,"qty":1,"profit":null"#));
        assert!(output.contains(r#""size":null,"avgPrice":null"#));
        assert!(output.contains(r#""cash":null,"marketValue":null,"equity":null,"netProfit":2"#));
        assert!(output.contains(r#""qty":null,"price":null,"entryId":"T","exitId":null"#));
        assert!(!output.contains("NaN"));
        assert!(!output.contains("inf"));
    }
}
