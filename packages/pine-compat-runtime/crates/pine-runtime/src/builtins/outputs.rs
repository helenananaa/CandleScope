use pine_ir::{CallSiteId, HirCallArg};

use crate::builtins::args::call_arg_expr;
use crate::builtins::colors::apply_transparency;
use crate::output::align::{
    PlotArrowPoint, PlotBarPoint, PlotCandlePoint, PlotCharPoint, PlotShapePoint,
    push_bar_aligned_output,
};
use crate::output::collect::{push_plot_value, push_series_value};
use crate::*;

const LEGACY_PLOT_STYLES: &[&str] = &[
    "plot.style_line",
    "plot.style_stepline",
    "plot.style_histogram",
    "plot.style_cross",
    "plot.style_area",
    "plot.style_columns",
    "plot.style_circles",
    "plot.style_linebr",
    "plot.style_areabr",
];
const LEGACY_HLINE_STYLES: &[&str] = &[
    "hline.style_solid",
    "hline.style_dotted",
    "hline.style_dashed",
];

impl<'a> HistoricalRuntime<'a> {
    fn eval_output_arg(
        &mut self,
        args: &[HirCallArg],
        index: usize,
        name: &str,
        default: PineValue,
    ) -> Result<PineValue, RuntimeError> {
        call_arg_expr(args, index, name)
            .map(|expr| self.eval_expr(expr))
            .unwrap_or(Ok(default))
    }

    #[allow(clippy::too_many_arguments)]
    fn eval_output_metadata(
        &mut self,
        args: &[HirCallArg],
        title_index: usize,
        offset_index: Option<usize>,
        editable_index: usize,
        show_last_index: Option<usize>,
        display_index: Option<usize>,
        force_overlay_index: Option<usize>,
    ) -> Result<OutputMetadata, RuntimeError> {
        Ok(OutputMetadata {
            title: self.eval_output_arg(
                args,
                title_index,
                "title",
                PineValue::String(String::new()),
            )?,
            offset: match offset_index {
                Some(index) => self.eval_output_arg(args, index, "offset", PineValue::Int(0))?,
                None => PineValue::Int(0),
            },
            editable: self.eval_output_arg(
                args,
                editable_index,
                "editable",
                PineValue::Bool(true),
            )?,
            show_last: match show_last_index {
                Some(index) => self.eval_output_arg(args, index, "show_last", PineValue::Na)?,
                None => PineValue::Na,
            },
            display: match display_index {
                Some(index) => self.eval_output_arg(
                    args,
                    index,
                    "display",
                    PineValue::String("display.all".to_owned()),
                )?,
                None => PineValue::String("display.all".to_owned()),
            },
            force_overlay: match force_overlay_index {
                Some(index) => {
                    self.eval_output_arg(args, index, "force_overlay", PineValue::Bool(false))?
                }
                None => PineValue::Bool(false),
            },
        })
    }

    fn eval_legacy_transparency(
        &mut self,
        args: &[HirCallArg],
        v4_default: Option<i64>,
    ) -> Result<Option<i64>, RuntimeError> {
        if let Some(expr) = call_arg_expr(args, usize::MAX, pine_ir::LEGACY_TRANSPARENCY_ARG) {
            return match self.eval_expr(expr)? {
                PineValue::Int(value) => Ok(Some(value)),
                PineValue::Na => Ok(Some(0)),
                _ => Err(RuntimeError {
                    message: "legacy output transparency must evaluate to an integer or na"
                        .to_owned(),
                }),
            };
        }
        Ok(self
            .program
            .language_version
            .is_some_and(|version| version == 4)
            .then_some(v4_default)
            .flatten())
    }

    fn normalize_legacy_style(
        &self,
        value: PineValue,
        styles: &[&str],
        feature: &str,
    ) -> Result<PineValue, RuntimeError> {
        let PineValue::Int(index) = value else {
            return Ok(value);
        };
        let style = usize::try_from(index)
            .ok()
            .and_then(|index| styles.get(index))
            .ok_or_else(|| RuntimeError {
                message: format!(
                    "invalid Pine v{} {feature} style ordinal `{index}`",
                    self.program.language_version.unwrap_or(4)
                ),
            })?;
        Ok(PineValue::String((*style).to_owned()))
    }

    fn apply_legacy_transparency(value: PineValue, transp: Option<i64>) -> PineValue {
        match (value, transp) {
            (PineValue::Color(color), Some(_)) if color > 0xFF_FFFF => PineValue::Color(color),
            (PineValue::Color(color), Some(transp)) => {
                PineValue::Color(apply_transparency(color, transp))
            }
            (value, _) => value,
        }
    }

    pub(crate) fn eval_output_call(
        &mut self,
        callee: &str,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Option<Result<PineValue, RuntimeError>> {
        Some(match callee {
            "plot" => self.eval_plot(call_site_id, args),
            "plotchar" => self.eval_plotchar(call_site_id, args),
            "plotshape" => self.eval_plotshape(call_site_id, args),
            "plotarrow" => self.eval_plotarrow(call_site_id, args),
            "plotbar" => self.eval_plotbar(call_site_id, args),
            "plotcandle" => self.eval_plotcandle(call_site_id, args),
            "bgcolor" => self.eval_bgcolor(call_site_id, args),
            "barcolor" => self.eval_barcolor(call_site_id, args),
            "hline" => self.eval_hline(call_site_id, args),
            "fill" => self.eval_fill(call_site_id, args),
            _ => return None,
        })
    }

    pub(crate) fn eval_plot(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let Some(series_arg) = call_arg_expr(args, 0, "series") else {
            return Err(RuntimeError {
                message: "plot missing series argument".to_owned(),
            });
        };
        let value = self.eval_expr(series_arg)?;
        let transp = self.eval_legacy_transparency(args, None)?;
        let color = self.eval_output_arg(args, 2, "color", PineValue::Na)?;
        let color = Self::apply_legacy_transparency(color, transp);
        let metadata =
            self.eval_output_metadata(args, 1, Some(7), 9, Some(10), Some(11), Some(14))?;
        let linewidth = self.eval_output_arg(args, 3, "linewidth", PineValue::Int(1))?;
        let style = self.eval_output_arg(
            args,
            4,
            "style",
            PineValue::String("plot.style_line".to_owned()),
        )?;
        let style = self.normalize_legacy_style(style, LEGACY_PLOT_STYLES, "plot")?;
        let track_price = self.eval_output_arg(args, 5, "trackprice", PineValue::Bool(false))?;
        let hist_base = self.eval_output_arg(args, 6, "histbase", PineValue::Int(0))?;
        let join = self.eval_output_arg(args, 8, "join", PineValue::Bool(false))?;
        let format = self.eval_output_arg(
            args,
            12,
            "format",
            PineValue::String("format.inherit".to_owned()),
        )?;
        let precision = self.eval_output_arg(args, 13, "precision", PineValue::Na)?;
        push_plot_value(&mut self.plots, self.bars, call_site_id.0, value, color);
        let output = self
            .plots
            .iter_mut()
            .find(|output| output.id == call_site_id.0)
            .expect("plot output was just inserted");
        output.metadata = metadata;
        output.linewidth = linewidth;
        output.style = style;
        output.track_price = track_price;
        output.hist_base = hist_base;
        output.join = join;
        output.format = format;
        output.precision = precision;
        Ok(PineValue::Plot(call_site_id.0))
    }

    pub(crate) fn eval_plotchar(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let Some(series_arg) = call_arg_expr(args, 0, "series") else {
            return Err(RuntimeError {
                message: "plotchar missing series argument".to_owned(),
            });
        };
        let value = self.eval_expr(series_arg)?;
        let char_value = match call_arg_expr(args, 2, "char") {
            Some(expr) => self.eval_expr(expr)?,
            None => PineValue::String("*".to_owned()),
        };
        let color_value = match call_arg_expr(args, 3, "color") {
            Some(expr) => self.eval_expr(expr)?,
            None => PineValue::Na,
        };
        let transp = self.eval_legacy_transparency(args, None)?;
        let color_value = Self::apply_legacy_transparency(color_value, transp);
        let location_value = self.eval_output_arg(
            args,
            4,
            "location",
            PineValue::String("location.abovebar".to_owned()),
        )?;
        let text_value = self.eval_output_arg(args, 6, "text", PineValue::String(String::new()))?;
        let text_color_value = self.eval_output_arg(args, 7, "textcolor", PineValue::Na)?;
        let size_value =
            self.eval_output_arg(args, 9, "size", PineValue::String("size.auto".to_owned()))?;
        let metadata = self.eval_output_metadata(args, 1, Some(5), 8, Some(10), Some(11), None)?;
        push_bar_aligned_output(
            &mut self.plot_chars,
            self.bars,
            call_site_id.0,
            PlotCharPoint {
                value,
                char_value,
                color: color_value,
                location: location_value,
                text: text_value,
                text_color: text_color_value,
                size: size_value,
            },
        );
        self.plot_chars
            .iter_mut()
            .find(|output| output.id == call_site_id.0)
            .expect("plotchar output was just inserted")
            .metadata = metadata;
        Ok(PineValue::Void)
    }

    pub(crate) fn eval_plotshape(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let Some(series_arg) = call_arg_expr(args, 0, "series") else {
            return Err(RuntimeError {
                message: "plotshape missing series argument".to_owned(),
            });
        };
        let value = self.eval_expr(series_arg)?;
        let style_value = match call_arg_expr(args, 2, "style") {
            Some(expr) => self.eval_expr(expr)?,
            None => PineValue::String("shape.xcross".to_owned()),
        };
        let location_value = match call_arg_expr(args, 3, "location") {
            Some(expr) => self.eval_expr(expr)?,
            None => PineValue::String("location.abovebar".to_owned()),
        };
        let color_value = match call_arg_expr(args, 4, "color") {
            Some(expr) => self.eval_expr(expr)?,
            None => PineValue::Na,
        };
        let transp = self.eval_legacy_transparency(args, None)?;
        let color_value = Self::apply_legacy_transparency(color_value, transp);
        let text_value = match call_arg_expr(args, 6, "text") {
            Some(expr) => self.eval_expr(expr)?,
            None => PineValue::String(String::new()),
        };
        let text_color_value = match call_arg_expr(args, 7, "textcolor") {
            Some(expr) => self.eval_expr(expr)?,
            None => PineValue::Na,
        };
        let size_value = match call_arg_expr(args, 9, "size") {
            Some(expr) => self.eval_expr(expr)?,
            None => PineValue::String("size.auto".to_owned()),
        };
        let metadata =
            self.eval_output_metadata(args, 1, Some(5), 8, Some(10), Some(11), Some(12))?;
        push_bar_aligned_output(
            &mut self.plot_shapes,
            self.bars,
            call_site_id.0,
            PlotShapePoint {
                value,
                style: style_value,
                location: location_value,
                color: color_value,
                text: text_value,
                text_color: text_color_value,
                size: size_value,
            },
        );
        self.plot_shapes
            .iter_mut()
            .find(|output| output.id == call_site_id.0)
            .expect("plotshape output was just inserted")
            .metadata = metadata;
        Ok(PineValue::Void)
    }

    pub(crate) fn eval_plotarrow(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let Some(series_arg) = call_arg_expr(args, 0, "series") else {
            return Err(RuntimeError {
                message: "plotarrow missing series argument".to_owned(),
            });
        };
        let value = self.eval_expr(series_arg)?;
        let color_up_value = match call_arg_expr(args, 2, "colorup") {
            Some(expr) => self.eval_expr(expr)?,
            None => PineValue::Color(0x008000),
        };
        let color_down_value = match call_arg_expr(args, 3, "colordown") {
            Some(expr) => self.eval_expr(expr)?,
            None => PineValue::Color(0xFF0000),
        };
        let transp = self.eval_legacy_transparency(args, None)?;
        let color_up_value = Self::apply_legacy_transparency(color_up_value, transp);
        let color_down_value = Self::apply_legacy_transparency(color_down_value, transp);
        let min_height_value = match call_arg_expr(args, 5, "minheight") {
            Some(expr) => self.eval_expr(expr)?,
            None => PineValue::Int(0),
        };
        let max_height_value = match call_arg_expr(args, 6, "maxheight") {
            Some(expr) => self.eval_expr(expr)?,
            None => PineValue::Int(0),
        };
        let metadata =
            self.eval_output_metadata(args, 1, Some(4), 7, Some(8), Some(9), Some(10))?;
        push_bar_aligned_output(
            &mut self.plot_arrows,
            self.bars,
            call_site_id.0,
            PlotArrowPoint {
                value,
                color_up: color_up_value,
                color_down: color_down_value,
                min_height: min_height_value,
                max_height: max_height_value,
            },
        );
        self.plot_arrows
            .iter_mut()
            .find(|output| output.id == call_site_id.0)
            .expect("plotarrow output was just inserted")
            .metadata = metadata;
        Ok(PineValue::Void)
    }

    pub(crate) fn eval_plotbar(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let Some(open_arg) = call_arg_expr(args, 0, "open") else {
            return Err(RuntimeError {
                message: "plotbar missing open argument".to_owned(),
            });
        };
        let Some(high_arg) = call_arg_expr(args, 1, "high") else {
            return Err(RuntimeError {
                message: "plotbar missing high argument".to_owned(),
            });
        };
        let Some(low_arg) = call_arg_expr(args, 2, "low") else {
            return Err(RuntimeError {
                message: "plotbar missing low argument".to_owned(),
            });
        };
        let Some(close_arg) = call_arg_expr(args, 3, "close") else {
            return Err(RuntimeError {
                message: "plotbar missing close argument".to_owned(),
            });
        };
        let open_value = self.eval_expr(open_arg)?;
        let high_value = self.eval_expr(high_arg)?;
        let low_value = self.eval_expr(low_arg)?;
        let close_value = self.eval_expr(close_arg)?;
        let color_value = match call_arg_expr(args, 5, "color") {
            Some(expr) => self.eval_expr(expr)?,
            None => PineValue::Na,
        };
        let metadata = self.eval_output_metadata(args, 4, None, 6, Some(7), Some(8), None)?;
        push_bar_aligned_output(
            &mut self.plot_bars,
            self.bars,
            call_site_id.0,
            PlotBarPoint {
                open: open_value,
                high: high_value,
                low: low_value,
                close: close_value,
                color: color_value,
            },
        );
        self.plot_bars
            .iter_mut()
            .find(|output| output.id == call_site_id.0)
            .expect("plotbar output was just inserted")
            .metadata = metadata;
        Ok(PineValue::Void)
    }

    pub(crate) fn eval_plotcandle(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let Some(open_arg) = call_arg_expr(args, 0, "open") else {
            return Err(RuntimeError {
                message: "plotcandle missing open argument".to_owned(),
            });
        };
        let Some(high_arg) = call_arg_expr(args, 1, "high") else {
            return Err(RuntimeError {
                message: "plotcandle missing high argument".to_owned(),
            });
        };
        let Some(low_arg) = call_arg_expr(args, 2, "low") else {
            return Err(RuntimeError {
                message: "plotcandle missing low argument".to_owned(),
            });
        };
        let Some(close_arg) = call_arg_expr(args, 3, "close") else {
            return Err(RuntimeError {
                message: "plotcandle missing close argument".to_owned(),
            });
        };
        let open_value = self.eval_expr(open_arg)?;
        let high_value = self.eval_expr(high_arg)?;
        let low_value = self.eval_expr(low_arg)?;
        let close_value = self.eval_expr(close_arg)?;
        let color_value = match call_arg_expr(args, 5, "color") {
            Some(expr) => self.eval_expr(expr)?,
            None => PineValue::Na,
        };
        let wick_color_value = match call_arg_expr(args, 6, "wickcolor") {
            Some(expr) => self.eval_expr(expr)?,
            None => PineValue::Na,
        };
        let border_color_value = match call_arg_expr(args, 9, "bordercolor") {
            Some(expr) => self.eval_expr(expr)?,
            None => PineValue::Na,
        };
        let metadata = self.eval_output_metadata(args, 4, None, 7, Some(8), Some(10), None)?;
        push_bar_aligned_output(
            &mut self.plot_candles,
            self.bars,
            call_site_id.0,
            PlotCandlePoint {
                open: open_value,
                high: high_value,
                low: low_value,
                close: close_value,
                color: color_value,
                wick_color: wick_color_value,
                border_color: border_color_value,
            },
        );
        self.plot_candles
            .iter_mut()
            .find(|output| output.id == call_site_id.0)
            .expect("plotcandle output was just inserted")
            .metadata = metadata;
        Ok(PineValue::Void)
    }

    pub(crate) fn eval_bgcolor(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let Some(color_arg) = call_arg_expr(args, 0, "color") else {
            return Err(RuntimeError {
                message: "bgcolor missing color argument".to_owned(),
            });
        };
        let value = self.eval_expr(color_arg)?;
        let transp = self.eval_legacy_transparency(args, Some(90))?;
        let value = Self::apply_legacy_transparency(value, transp);
        let metadata = self.eval_output_metadata(args, 1, Some(2), 3, Some(4), Some(5), None)?;
        push_series_value(&mut self.bg_colors, self.bars, call_site_id.0, value);
        self.bg_colors
            .iter_mut()
            .find(|output| output.id == call_site_id.0)
            .expect("bgcolor output was just inserted")
            .metadata = metadata;
        Ok(PineValue::Void)
    }

    pub(crate) fn eval_barcolor(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let Some(color_arg) = call_arg_expr(args, 0, "color") else {
            return Err(RuntimeError {
                message: "barcolor missing color argument".to_owned(),
            });
        };
        let value = self.eval_expr(color_arg)?;
        let metadata = self.eval_output_metadata(args, 1, Some(2), 3, Some(4), Some(5), None)?;
        push_series_value(&mut self.bar_colors, self.bars, call_site_id.0, value);
        self.bar_colors
            .iter_mut()
            .find(|output| output.id == call_site_id.0)
            .expect("barcolor output was just inserted")
            .metadata = metadata;
        Ok(PineValue::Void)
    }

    pub(crate) fn eval_hline(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let Some(price_arg) = call_arg_expr(args, 0, "price") else {
            return Err(RuntimeError {
                message: "hline missing price argument".to_owned(),
            });
        };
        let price = self.eval_expr(price_arg)?;
        let title = self.eval_output_arg(args, 1, "title", PineValue::String(String::new()))?;
        let color = self.eval_output_arg(args, 2, "color", PineValue::Color(0x787B86))?;
        let style = self.eval_output_arg(
            args,
            3,
            "linestyle",
            PineValue::String("hline.style_solid".to_owned()),
        )?;
        let style = self.normalize_legacy_style(style, LEGACY_HLINE_STYLES, "hline")?;
        let linewidth = self.eval_output_arg(args, 4, "linewidth", PineValue::Int(1))?;
        let editable = self.eval_output_arg(args, 5, "editable", PineValue::Bool(true))?;
        let display = self.eval_output_arg(
            args,
            6,
            "display",
            PineValue::String("display.all".to_owned()),
        )?;
        self.push_hline(
            call_site_id.0,
            price,
            title,
            color,
            style,
            linewidth,
            editable,
            display,
        );
        Ok(PineValue::HLine(call_site_id.0))
    }

    pub(crate) fn eval_fill(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let Some(first_arg) = call_arg_expr(args, 0, "plot1") else {
            return Err(RuntimeError {
                message: "fill missing first output id".to_owned(),
            });
        };
        let Some(second_arg) = call_arg_expr(args, 1, "plot2") else {
            return Err(RuntimeError {
                message: "fill missing second output id".to_owned(),
            });
        };
        let first = self.eval_expr(first_arg)?;
        let second = self.eval_expr(second_arg)?;
        let color = self.eval_output_arg(args, 2, "color", PineValue::Color(0x2196F3))?;
        let transp = self.eval_legacy_transparency(args, Some(90))?;
        let color = Self::apply_legacy_transparency(color, transp);
        let title = self.eval_output_arg(args, 3, "title", PineValue::String(String::new()))?;
        let editable = self.eval_output_arg(args, 4, "editable", PineValue::Bool(true))?;
        let show_last = self.eval_output_arg(args, 5, "show_last", PineValue::Na)?;
        let fill_gaps = self.eval_output_arg(args, 6, "fillgaps", PineValue::Bool(true))?;
        let display = self.eval_output_arg(
            args,
            7,
            "display",
            PineValue::String("display.all".to_owned()),
        )?;
        self.push_fill(
            call_site_id.0,
            first,
            second,
            color,
            title,
            editable,
            show_last,
            fill_gaps,
            display,
        );
        Ok(PineValue::Void)
    }
}
