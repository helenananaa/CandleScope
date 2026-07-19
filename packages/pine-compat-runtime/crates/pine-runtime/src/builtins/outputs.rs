use pine_ir::{CallSiteId, HirCallArg};

use crate::builtins::args::call_arg_expr;
use crate::output::align::{
    PlotArrowPoint, PlotBarPoint, PlotCandlePoint, PlotCharPoint, PlotShapePoint,
    push_bar_aligned_output,
};
use crate::output::collect::push_series_value;
use crate::*;

impl<'a> HistoricalRuntime<'a> {
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
        let value = self.eval_expr(&args[0].value)?;
        push_series_value(&mut self.plots, self.bars, call_site_id.0, value);
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
        push_bar_aligned_output(
            &mut self.plot_chars,
            self.bars,
            call_site_id.0,
            PlotCharPoint {
                value,
                char_value,
                color: color_value,
            },
        );
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
        let min_height_value = match call_arg_expr(args, 5, "minheight") {
            Some(expr) => self.eval_expr(expr)?,
            None => PineValue::Int(0),
        };
        let max_height_value = match call_arg_expr(args, 6, "maxheight") {
            Some(expr) => self.eval_expr(expr)?,
            None => PineValue::Int(0),
        };
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
        Ok(PineValue::Void)
    }

    pub(crate) fn eval_bgcolor(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let value = self.eval_expr(&args[0].value)?;
        push_series_value(&mut self.bg_colors, self.bars, call_site_id.0, value);
        Ok(PineValue::Void)
    }

    pub(crate) fn eval_barcolor(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let value = self.eval_expr(&args[0].value)?;
        push_series_value(&mut self.bar_colors, self.bars, call_site_id.0, value);
        Ok(PineValue::Void)
    }

    pub(crate) fn eval_hline(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let price = self.eval_expr(&args[0].value)?;
        self.push_hline(call_site_id.0, price);
        Ok(PineValue::HLine(call_site_id.0))
    }

    pub(crate) fn eval_fill(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let first = self.eval_expr(&args[0].value)?;
        let second = self.eval_expr(&args[1].value)?;
        self.push_fill(call_site_id.0, first, second);
        Ok(PineValue::Void)
    }
}
