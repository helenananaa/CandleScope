use crate::tables::tables_to_py;
use pine_runtime::{PUBLIC_RUNTIME_SCHEMA_VERSION, PineValue};
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyDict, PyList};

pub(crate) fn runtime_result_to_py(
    py: Python<'_>,
    result: &pine_runtime::RuntimeResult,
) -> PyResult<Py<PyAny>> {
    let output = PyDict::new(py);
    output.set_item("schemaVersion", PUBLIC_RUNTIME_SCHEMA_VERSION)?;
    output.set_item("plots", plots_to_py(py, &result.plots)?)?;
    output.set_item("plotChars", plot_chars_to_py(py, &result.plot_chars)?)?;
    output.set_item("plotShapes", plot_shapes_to_py(py, &result.plot_shapes)?)?;
    output.set_item("plotArrows", plot_arrows_to_py(py, &result.plot_arrows)?)?;
    output.set_item("plotBars", plot_bars_to_py(py, &result.plot_bars)?)?;
    output.set_item("plotCandles", plot_candles_to_py(py, &result.plot_candles)?)?;
    output.set_item("bgColors", colors_to_py(py, &result.bg_colors)?)?;
    output.set_item("barColors", colors_to_py(py, &result.bar_colors)?)?;
    output.set_item("hlines", hlines_to_py(py, &result.hlines)?)?;
    output.set_item("fills", fills_to_py(py, &result.fills)?)?;
    output.set_item("labels", labels_to_py(py, &result.labels)?)?;
    output.set_item("lines", lines_to_py(py, &result.lines)?)?;
    output.set_item("lineFills", line_fills_to_py(py, &result.line_fills)?)?;
    output.set_item("polylines", polylines_to_py(py, &result.polylines)?)?;
    output.set_item("boxes", boxes_to_py(py, &result.boxes)?)?;
    output.set_item("tables", tables_to_py(py, &result.tables)?)?;
    output.set_item("alerts", alerts_to_py(py, &result.alerts)?)?;
    if let Some(strategy) = &result.strategy {
        output.set_item("strategy", strategy_result_to_py(py, strategy)?)?;
    }
    output.set_item(
        "diagnostics",
        runtime_diagnostics_to_py(py, &result.diagnostics)?,
    )?;
    Ok(output.into_any().unbind())
}

fn strategy_result_to_py(
    py: Python<'_>,
    strategy: &pine_runtime::StrategyResult,
) -> PyResult<Py<PyAny>> {
    let output = PyDict::new(py);
    output.set_item("orders", strategy_orders_to_py(py, &strategy.orders)?)?;
    output.set_item("trades", strategy_trades_to_py(py, &strategy.trades)?)?;
    output.set_item("position", strategy_position_to_py(py, &strategy.position)?)?;
    output.set_item("equity", strategy_equity_to_py(py, &strategy.equity)?)?;
    output.set_item(
        "alerts",
        strategy_order_fill_alerts_to_py(py, &strategy.alerts)?,
    )?;
    output.set_item(
        "diagnostics",
        runtime_diagnostics_to_py(py, &strategy.diagnostics)?,
    )?;
    Ok(output.into_any().unbind())
}

fn strategy_order_fill_alerts_to_py(
    py: Python<'_>,
    alerts: &[pine_runtime::StrategyOrderFillAlertOutput],
) -> PyResult<Py<PyAny>> {
    let output = PyList::empty(py);
    for alert in alerts {
        let item = PyDict::new(py);
        item.set_item("id", &alert.id)?;
        item.set_item("barIndex", alert.bar_index)?;
        item.set_item("time", alert.time)?;
        item.set_item("direction", &alert.direction)?;
        set_finite_f64(py, &item, "qty", alert.qty)?;
        set_finite_f64(py, &item, "price", alert.price)?;
        match &alert.entry_id {
            Some(entry_id) => item.set_item("entryId", entry_id)?,
            None => item.set_item("entryId", py.None())?,
        }
        match &alert.exit_id {
            Some(exit_id) => item.set_item("exitId", exit_id)?,
            None => item.set_item("exitId", py.None())?,
        }
        item.set_item("message", &alert.message)?;
        output.append(item)?;
    }
    Ok(output.into_any().unbind())
}

fn runtime_diagnostics_to_py(
    py: Python<'_>,
    diagnostics: &[pine_runtime::RuntimeDiagnostic],
) -> PyResult<Py<PyAny>> {
    let output = PyList::empty(py);
    for diagnostic in diagnostics {
        let item = PyDict::new(py);
        item.set_item("code", &diagnostic.code)?;
        item.set_item("message", &diagnostic.message)?;
        output.append(item)?;
    }
    Ok(output.into_any().unbind())
}

fn strategy_trades_to_py(
    py: Python<'_>,
    trades: &[pine_runtime::StrategyTrade],
) -> PyResult<Py<PyAny>> {
    let output = PyList::empty(py);
    for trade in trades {
        let item = PyDict::new(py);
        item.set_item("id", &trade.id)?;
        item.set_item("entryBarIndex", trade.entry_bar_index)?;
        item.set_item("exitBarIndex", trade.exit_bar_index)?;
        item.set_item("entryTime", trade.entry_time)?;
        item.set_item("exitTime", trade.exit_time)?;
        set_finite_f64(py, &item, "entryPrice", trade.entry_price)?;
        set_finite_f64(py, &item, "exitPrice", trade.exit_price)?;
        set_finite_f64(py, &item, "qty", trade.qty)?;
        set_finite_f64(py, &item, "profit", trade.profit)?;
        output.append(item)?;
    }
    Ok(output.into_any().unbind())
}

fn strategy_orders_to_py(
    py: Python<'_>,
    orders: &[pine_runtime::StrategyOrderEvent],
) -> PyResult<Py<PyAny>> {
    let output = PyList::empty(py);
    for order in orders {
        let item = PyDict::new(py);
        item.set_item("id", &order.id)?;
        item.set_item("barIndex", order.bar_index)?;
        item.set_item("time", order.time)?;
        item.set_item("direction", &order.direction)?;
        set_finite_f64(py, &item, "qty", order.qty)?;
        set_finite_f64(py, &item, "price", order.price)?;
        output.append(item)?;
    }
    Ok(output.into_any().unbind())
}

fn strategy_position_to_py(
    py: Python<'_>,
    position: &[pine_runtime::StrategyPositionSnapshot],
) -> PyResult<Py<PyAny>> {
    let output = PyList::empty(py);
    for snapshot in position {
        let item = PyDict::new(py);
        item.set_item("barIndex", snapshot.bar_index)?;
        set_finite_f64(py, &item, "size", snapshot.size)?;
        set_option_finite_f64(py, &item, "avgPrice", snapshot.avg_price)?;
        output.append(item)?;
    }
    Ok(output.into_any().unbind())
}

fn strategy_equity_to_py(
    py: Python<'_>,
    equity: &[pine_runtime::StrategyEquitySnapshot],
) -> PyResult<Py<PyAny>> {
    let output = PyList::empty(py);
    for snapshot in equity {
        let item = PyDict::new(py);
        item.set_item("barIndex", snapshot.bar_index)?;
        set_finite_f64(py, &item, "cash", snapshot.cash)?;
        set_finite_f64(py, &item, "marketValue", snapshot.market_value)?;
        set_finite_f64(py, &item, "equity", snapshot.equity)?;
        set_finite_f64(py, &item, "netProfit", snapshot.net_profit)?;
        output.append(item)?;
    }
    Ok(output.into_any().unbind())
}

fn plots_to_py(py: Python<'_>, plots: &[pine_runtime::PlotSeries]) -> PyResult<Py<PyAny>> {
    let output = PyList::empty(py);
    for plot in plots {
        let item = PyDict::new(py);
        item.set_item("id", plot.id)?;
        item.set_item("values", values_to_py(py, &plot.values)?)?;
        output.append(item)?;
    }
    Ok(output.into_any().unbind())
}

fn colors_to_py(py: Python<'_>, colors: &[pine_runtime::ColorSeries]) -> PyResult<Py<PyAny>> {
    let output = PyList::empty(py);
    for colors in colors {
        let item = PyDict::new(py);
        item.set_item("id", colors.id)?;
        item.set_item("values", values_to_py(py, &colors.values)?)?;
        output.append(item)?;
    }
    Ok(output.into_any().unbind())
}

fn plot_chars_to_py(
    py: Python<'_>,
    plot_chars: &[pine_runtime::PlotCharSeries],
) -> PyResult<Py<PyAny>> {
    let output = PyList::empty(py);
    for plot_char in plot_chars {
        let item = PyDict::new(py);
        item.set_item("id", plot_char.id)?;
        item.set_item("values", values_to_py(py, &plot_char.values)?)?;
        item.set_item("chars", values_to_py(py, &plot_char.chars)?)?;
        item.set_item("colors", values_to_py(py, &plot_char.colors)?)?;
        output.append(item)?;
    }
    Ok(output.into_any().unbind())
}

fn plot_shapes_to_py(
    py: Python<'_>,
    plot_shapes: &[pine_runtime::PlotShapeSeries],
) -> PyResult<Py<PyAny>> {
    let output = PyList::empty(py);
    for plot_shape in plot_shapes {
        let item = PyDict::new(py);
        item.set_item("id", plot_shape.id)?;
        item.set_item("values", values_to_py(py, &plot_shape.values)?)?;
        item.set_item("styles", values_to_py(py, &plot_shape.styles)?)?;
        item.set_item("locations", values_to_py(py, &plot_shape.locations)?)?;
        item.set_item("colors", values_to_py(py, &plot_shape.colors)?)?;
        item.set_item("texts", values_to_py(py, &plot_shape.texts)?)?;
        item.set_item("textColors", values_to_py(py, &plot_shape.text_colors)?)?;
        item.set_item("sizes", values_to_py(py, &plot_shape.sizes)?)?;
        output.append(item)?;
    }
    Ok(output.into_any().unbind())
}

fn plot_arrows_to_py(
    py: Python<'_>,
    plot_arrows: &[pine_runtime::PlotArrowSeries],
) -> PyResult<Py<PyAny>> {
    let output = PyList::empty(py);
    for plot_arrow in plot_arrows {
        let item = PyDict::new(py);
        item.set_item("id", plot_arrow.id)?;
        item.set_item("values", values_to_py(py, &plot_arrow.values)?)?;
        item.set_item("colorUps", values_to_py(py, &plot_arrow.color_ups)?)?;
        item.set_item("colorDowns", values_to_py(py, &plot_arrow.color_downs)?)?;
        item.set_item("minHeights", values_to_py(py, &plot_arrow.min_heights)?)?;
        item.set_item("maxHeights", values_to_py(py, &plot_arrow.max_heights)?)?;
        output.append(item)?;
    }
    Ok(output.into_any().unbind())
}

fn plot_bars_to_py(
    py: Python<'_>,
    plot_bars: &[pine_runtime::PlotBarSeries],
) -> PyResult<Py<PyAny>> {
    let output = PyList::empty(py);
    for plot_bar in plot_bars {
        let item = PyDict::new(py);
        item.set_item("id", plot_bar.id)?;
        item.set_item("opens", values_to_py(py, &plot_bar.opens)?)?;
        item.set_item("highs", values_to_py(py, &plot_bar.highs)?)?;
        item.set_item("lows", values_to_py(py, &plot_bar.lows)?)?;
        item.set_item("closes", values_to_py(py, &plot_bar.closes)?)?;
        item.set_item("colors", values_to_py(py, &plot_bar.colors)?)?;
        output.append(item)?;
    }
    Ok(output.into_any().unbind())
}

fn plot_candles_to_py(
    py: Python<'_>,
    plot_candles: &[pine_runtime::PlotCandleSeries],
) -> PyResult<Py<PyAny>> {
    let output = PyList::empty(py);
    for plot_candle in plot_candles {
        let item = PyDict::new(py);
        item.set_item("id", plot_candle.id)?;
        item.set_item("opens", values_to_py(py, &plot_candle.opens)?)?;
        item.set_item("highs", values_to_py(py, &plot_candle.highs)?)?;
        item.set_item("lows", values_to_py(py, &plot_candle.lows)?)?;
        item.set_item("closes", values_to_py(py, &plot_candle.closes)?)?;
        item.set_item("colors", values_to_py(py, &plot_candle.colors)?)?;
        item.set_item("wickColors", values_to_py(py, &plot_candle.wick_colors)?)?;
        item.set_item(
            "borderColors",
            values_to_py(py, &plot_candle.border_colors)?,
        )?;
        output.append(item)?;
    }
    Ok(output.into_any().unbind())
}

fn hlines_to_py(py: Python<'_>, hlines: &[pine_runtime::HLineOutput]) -> PyResult<Py<PyAny>> {
    let output = PyList::empty(py);
    for hline in hlines {
        let item = PyDict::new(py);
        item.set_item("id", hline.id)?;
        item.set_item("price", value_to_py(py, &hline.price)?)?;
        output.append(item)?;
    }
    Ok(output.into_any().unbind())
}

fn fills_to_py(py: Python<'_>, fills: &[pine_runtime::FillOutput]) -> PyResult<Py<PyAny>> {
    let output = PyList::empty(py);
    for fill in fills {
        let item = PyDict::new(py);
        item.set_item("id", fill.id)?;
        item.set_item("firstId", fill.first_id)?;
        item.set_item("secondId", fill.second_id)?;
        output.append(item)?;
    }
    Ok(output.into_any().unbind())
}

fn labels_to_py(py: Python<'_>, labels: &[pine_runtime::LabelOutput]) -> PyResult<Py<PyAny>> {
    let output = PyList::empty(py);
    for label in labels {
        let item = PyDict::new(py);
        item.set_item("id", label.id)?;
        item.set_item("snapshots", label_snapshots_to_py(py, &label.snapshots)?)?;
        output.append(item)?;
    }
    Ok(output.into_any().unbind())
}

fn label_snapshots_to_py(
    py: Python<'_>,
    snapshots: &[pine_runtime::LabelSnapshot],
) -> PyResult<Py<PyAny>> {
    let output = PyList::empty(py);
    for snapshot in snapshots {
        let item = PyDict::new(py);
        item.set_item("barIndex", snapshot.bar_index)?;
        item.set_item("exists", snapshot.exists)?;
        if snapshot.exists {
            item.set_item("x", value_to_py(py, &snapshot.x)?)?;
            item.set_item("y", value_to_py(py, &snapshot.y)?)?;
            item.set_item("text", value_to_py(py, &snapshot.text)?)?;
            item.set_item("xloc", value_to_py(py, &snapshot.xloc)?)?;
            item.set_item("yloc", value_to_py(py, &snapshot.yloc)?)?;
            item.set_item("color", value_to_py(py, &snapshot.color)?)?;
            item.set_item("style", value_to_py(py, &snapshot.style)?)?;
            item.set_item("textColor", value_to_py(py, &snapshot.text_color)?)?;
            item.set_item("size", value_to_py(py, &snapshot.size)?)?;
            item.set_item("tooltip", value_to_py(py, &snapshot.tooltip)?)?;
            item.set_item("textAlign", value_to_py(py, &snapshot.text_align)?)?;
            item.set_item(
                "textFontFamily",
                value_to_py(py, &snapshot.text_font_family)?,
            )?;
            item.set_item(
                "textFormatting",
                value_to_py(py, &snapshot.text_formatting)?,
            )?;
        }
        output.append(item)?;
    }
    Ok(output.into_any().unbind())
}

fn lines_to_py(py: Python<'_>, lines: &[pine_runtime::LineOutput]) -> PyResult<Py<PyAny>> {
    let output = PyList::empty(py);
    for line in lines {
        let item = PyDict::new(py);
        item.set_item("id", line.id)?;
        item.set_item("snapshots", line_snapshots_to_py(py, &line.snapshots)?)?;
        output.append(item)?;
    }
    Ok(output.into_any().unbind())
}

fn line_snapshots_to_py(
    py: Python<'_>,
    snapshots: &[pine_runtime::LineSnapshot],
) -> PyResult<Py<PyAny>> {
    let output = PyList::empty(py);
    for snapshot in snapshots {
        let item = PyDict::new(py);
        item.set_item("barIndex", snapshot.bar_index)?;
        item.set_item("exists", snapshot.exists)?;
        if snapshot.exists {
            item.set_item("x1", value_to_py(py, &snapshot.x1)?)?;
            item.set_item("y1", value_to_py(py, &snapshot.y1)?)?;
            item.set_item("x2", value_to_py(py, &snapshot.x2)?)?;
            item.set_item("y2", value_to_py(py, &snapshot.y2)?)?;
            item.set_item("xloc", value_to_py(py, &snapshot.xloc)?)?;
            item.set_item("color", value_to_py(py, &snapshot.color)?)?;
            item.set_item("width", value_to_py(py, &snapshot.width)?)?;
            item.set_item("style", value_to_py(py, &snapshot.style)?)?;
            item.set_item("extend", value_to_py(py, &snapshot.extend)?)?;
        }
        output.append(item)?;
    }
    Ok(output.into_any().unbind())
}

fn line_fills_to_py(
    py: Python<'_>,
    line_fills: &[pine_runtime::LineFillOutput],
) -> PyResult<Py<PyAny>> {
    let output = PyList::empty(py);
    for line_fill in line_fills {
        let item = PyDict::new(py);
        item.set_item("id", line_fill.id)?;
        item.set_item(
            "snapshots",
            line_fill_snapshots_to_py(py, &line_fill.snapshots)?,
        )?;
        output.append(item)?;
    }
    Ok(output.into_any().unbind())
}

fn line_fill_snapshots_to_py(
    py: Python<'_>,
    snapshots: &[pine_runtime::LineFillSnapshot],
) -> PyResult<Py<PyAny>> {
    let output = PyList::empty(py);
    for snapshot in snapshots {
        let item = PyDict::new(py);
        item.set_item("barIndex", snapshot.bar_index)?;
        item.set_item("exists", snapshot.exists)?;
        if snapshot.exists {
            item.set_item("line1", snapshot.line1)?;
            item.set_item("line2", snapshot.line2)?;
            item.set_item("color", value_to_py(py, &snapshot.color)?)?;
        }
        output.append(item)?;
    }
    Ok(output.into_any().unbind())
}

fn polylines_to_py(
    py: Python<'_>,
    polylines: &[pine_runtime::PolylineOutput],
) -> PyResult<Py<PyAny>> {
    let output = PyList::empty(py);
    for polyline in polylines {
        let item = PyDict::new(py);
        item.set_item("id", polyline.id)?;
        item.set_item(
            "snapshots",
            polyline_snapshots_to_py(py, &polyline.snapshots)?,
        )?;
        output.append(item)?;
    }
    Ok(output.into_any().unbind())
}

fn polyline_snapshots_to_py(
    py: Python<'_>,
    snapshots: &[pine_runtime::PolylineSnapshot],
) -> PyResult<Py<PyAny>> {
    let output = PyList::empty(py);
    for snapshot in snapshots {
        let item = PyDict::new(py);
        item.set_item("barIndex", snapshot.bar_index)?;
        item.set_item("exists", snapshot.exists)?;
        if snapshot.exists {
            item.set_item("points", values_to_py(py, &snapshot.points)?)?;
            item.set_item("curved", value_to_py(py, &snapshot.curved)?)?;
            item.set_item("closed", value_to_py(py, &snapshot.closed)?)?;
            item.set_item("xloc", value_to_py(py, &snapshot.xloc)?)?;
            item.set_item("lineColor", value_to_py(py, &snapshot.line_color)?)?;
            item.set_item("fillColor", value_to_py(py, &snapshot.fill_color)?)?;
            item.set_item("lineStyle", value_to_py(py, &snapshot.line_style)?)?;
            item.set_item("lineWidth", value_to_py(py, &snapshot.line_width)?)?;
            item.set_item("forceOverlay", value_to_py(py, &snapshot.force_overlay)?)?;
        }
        output.append(item)?;
    }
    Ok(output.into_any().unbind())
}

fn boxes_to_py(py: Python<'_>, boxes: &[pine_runtime::BoxOutput]) -> PyResult<Py<PyAny>> {
    let output = PyList::empty(py);
    for box_output in boxes {
        let item = PyDict::new(py);
        item.set_item("id", box_output.id)?;
        item.set_item("snapshots", box_snapshots_to_py(py, &box_output.snapshots)?)?;
        output.append(item)?;
    }
    Ok(output.into_any().unbind())
}

fn box_snapshots_to_py(
    py: Python<'_>,
    snapshots: &[pine_runtime::BoxSnapshot],
) -> PyResult<Py<PyAny>> {
    let output = PyList::empty(py);
    for snapshot in snapshots {
        let item = PyDict::new(py);
        item.set_item("barIndex", snapshot.bar_index)?;
        item.set_item("exists", snapshot.exists)?;
        if snapshot.exists {
            item.set_item("left", value_to_py(py, &snapshot.left)?)?;
            item.set_item("top", value_to_py(py, &snapshot.top)?)?;
            item.set_item("right", value_to_py(py, &snapshot.right)?)?;
            item.set_item("bottom", value_to_py(py, &snapshot.bottom)?)?;
            item.set_item("xloc", value_to_py(py, &snapshot.xloc)?)?;
            item.set_item("bgColor", value_to_py(py, &snapshot.bg_color)?)?;
            item.set_item("borderColor", value_to_py(py, &snapshot.border_color)?)?;
            item.set_item("borderWidth", value_to_py(py, &snapshot.border_width)?)?;
            item.set_item("borderStyle", value_to_py(py, &snapshot.border_style)?)?;
            item.set_item("extend", value_to_py(py, &snapshot.extend)?)?;
            item.set_item("text", value_to_py(py, &snapshot.text)?)?;
            item.set_item("textColor", value_to_py(py, &snapshot.text_color)?)?;
            item.set_item("textSize", value_to_py(py, &snapshot.text_size)?)?;
            item.set_item("textHalign", value_to_py(py, &snapshot.text_halign)?)?;
            item.set_item("textValign", value_to_py(py, &snapshot.text_valign)?)?;
            item.set_item("textWrap", value_to_py(py, &snapshot.text_wrap)?)?;
            item.set_item(
                "textFontFamily",
                value_to_py(py, &snapshot.text_font_family)?,
            )?;
            item.set_item(
                "textFormatting",
                value_to_py(py, &snapshot.text_formatting)?,
            )?;
        }
        output.append(item)?;
    }
    Ok(output.into_any().unbind())
}

fn alerts_to_py(py: Python<'_>, alerts: &[pine_runtime::AlertEvent]) -> PyResult<Py<PyAny>> {
    let output = PyList::empty(py);
    for alert in alerts {
        let item = PyDict::new(py);
        item.set_item("id", alert.id)?;
        item.set_item("barIndex", alert.bar_index)?;
        item.set_item("time", alert.time)?;
        item.set_item("message", &alert.message)?;
        item.set_item("source", &alert.source)?;
        output.append(item)?;
    }
    Ok(output.into_any().unbind())
}

fn values_to_py(py: Python<'_>, values: &[PineValue]) -> PyResult<Py<PyAny>> {
    let output = PyList::empty(py);
    for value in values {
        output.append(value_to_py(py, value)?)?;
    }
    Ok(output.into_any().unbind())
}

pub(crate) fn value_to_py(py: Python<'_>, value: &PineValue) -> PyResult<Py<PyAny>> {
    let output = PyList::empty(py);
    append_value(py, &output, value)?;
    Ok(output.get_item(0)?.unbind())
}

fn append_value(py: Python<'_>, output: &Bound<'_, PyList>, value: &PineValue) -> PyResult<()> {
    match value {
        PineValue::Int(value) => output.append(*value),
        PineValue::Float(value) if value.is_finite() => output.append(*value),
        PineValue::Float(_) => output.append(py.None()),
        PineValue::Bool(value) => output.append(*value),
        PineValue::String(value) => output.append(value),
        PineValue::Color(value)
        | PineValue::Plot(value)
        | PineValue::HLine(value)
        | PineValue::Label(value)
        | PineValue::Line(value)
        | PineValue::LineFill(value)
        | PineValue::Polyline(value)
        | PineValue::Box(value)
        | PineValue::Table(value) => output.append(*value),
        PineValue::ChartPoint(point) => {
            let item = PyDict::new(py);
            item.set_item("time", value_to_py(py, &point.time)?)?;
            item.set_item("index", value_to_py(py, &point.index)?)?;
            item.set_item("price", value_to_py(py, &point.price)?)?;
            output.append(item)
        }
        PineValue::UserType(values) | PineValue::Tuple(values) => {
            output.append(values_to_py(py, values)?)
        }
        PineValue::Array(_)
        | PineValue::Matrix(_)
        | PineValue::Map(_)
        | PineValue::Na
        | PineValue::Void => output.append(py.None()),
    }
}

fn set_finite_f64(
    py: Python<'_>,
    output: &Bound<'_, PyDict>,
    name: &str,
    value: f64,
) -> PyResult<()> {
    if value.is_finite() {
        output.set_item(name, value)
    } else {
        output.set_item(name, py.None())
    }
}

fn set_option_finite_f64(
    py: Python<'_>,
    output: &Bound<'_, PyDict>,
    name: &str,
    value: Option<f64>,
) -> PyResult<()> {
    match value {
        Some(value) if value.is_finite() => output.set_item(name, value),
        Some(_) | None => output.set_item(name, py.None()),
    }
}
