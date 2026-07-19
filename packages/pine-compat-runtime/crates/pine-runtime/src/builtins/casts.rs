use pine_ir::HirCallArg;

use crate::builtins::strings::format_number;
use crate::*;

impl<'a> HistoricalRuntime<'a> {
    pub(crate) fn eval_cast_call(
        &mut self,
        callee: &str,
        args: &[HirCallArg],
    ) -> Option<Result<PineValue, RuntimeError>> {
        Some(match callee {
            "int" => self.eval_int_cast(args),
            "float" => self.eval_float_cast(args),
            "bool" => self.eval_bool_cast(args),
            "string" => self.eval_string_cast(args),
            "box" => self.eval_box_cast(args),
            "color" => self.eval_color_cast(args),
            "label" => self.eval_label_cast(args),
            "line" => self.eval_line_cast(args),
            "linefill" => self.eval_linefill_cast(args),
            "polyline" => self.eval_polyline_cast(args),
            "table" => self.eval_table_cast(args),
            _ => return None,
        })
    }

    pub(crate) fn eval_int_cast(&mut self, args: &[HirCallArg]) -> Result<PineValue, RuntimeError> {
        Ok(match self.eval_expr(&args[0].value)? {
            PineValue::Int(value) => PineValue::Int(value),
            PineValue::Float(value) if value.is_finite() => PineValue::Int(value.trunc() as i64),
            PineValue::Bool(value) => PineValue::Int(i64::from(value)),
            PineValue::Na => PineValue::Na,
            _ => PineValue::Na,
        })
    }

    pub(crate) fn eval_float_cast(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        Ok(match self.eval_expr(&args[0].value)? {
            PineValue::Int(value) => PineValue::Float(value as f64),
            PineValue::Float(value) => finite_float_or_na(value),
            PineValue::Bool(value) => PineValue::Float(if value { 1.0 } else { 0.0 }),
            PineValue::Na => PineValue::Na,
            _ => PineValue::Na,
        })
    }

    pub(crate) fn eval_bool_cast(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        Ok(match self.eval_expr(&args[0].value)? {
            PineValue::Int(value) => PineValue::Bool(value != 0),
            PineValue::Float(value) => PineValue::Bool(value != 0.0 && !value.is_nan()),
            PineValue::Bool(value) => PineValue::Bool(value),
            PineValue::Na => PineValue::Bool(false),
            _ => PineValue::Bool(false),
        })
    }

    pub(crate) fn eval_string_cast(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let value = self.eval_expr(&args[0].value)?;
        let result = match value {
            PineValue::Int(value) => value.to_string(),
            PineValue::Float(value) => format_number(value, "#.########"),
            PineValue::Bool(value) => value.to_string(),
            PineValue::String(value) => value,
            PineValue::Na => return Ok(PineValue::Na),
            _ => return Ok(PineValue::Na),
        };
        self.string_value_or_error(result, "string")
    }

    pub(crate) fn eval_color_cast(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        Ok(match self.eval_expr(&args[0].value)? {
            PineValue::Color(value) => PineValue::Color(value),
            PineValue::Na => PineValue::Na,
            _ => PineValue::Na,
        })
    }

    pub(crate) fn eval_box_cast(&mut self, args: &[HirCallArg]) -> Result<PineValue, RuntimeError> {
        Ok(match self.eval_expr(&args[0].value)? {
            PineValue::Box(value) => PineValue::Box(value),
            PineValue::Na => PineValue::Na,
            _ => PineValue::Na,
        })
    }

    pub(crate) fn eval_label_cast(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        Ok(match self.eval_expr(&args[0].value)? {
            PineValue::Label(value) => PineValue::Label(value),
            PineValue::Na => PineValue::Na,
            _ => PineValue::Na,
        })
    }

    pub(crate) fn eval_line_cast(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        Ok(match self.eval_expr(&args[0].value)? {
            PineValue::Line(value) => PineValue::Line(value),
            PineValue::Na => PineValue::Na,
            _ => PineValue::Na,
        })
    }

    pub(crate) fn eval_linefill_cast(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        Ok(match self.eval_expr(&args[0].value)? {
            PineValue::LineFill(value) => PineValue::LineFill(value),
            PineValue::Na => PineValue::Na,
            _ => PineValue::Na,
        })
    }

    pub(crate) fn eval_polyline_cast(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        Ok(match self.eval_expr(&args[0].value)? {
            PineValue::Polyline(value) => PineValue::Polyline(value),
            PineValue::Na => PineValue::Na,
            _ => PineValue::Na,
        })
    }

    pub(crate) fn eval_table_cast(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        Ok(match self.eval_expr(&args[0].value)? {
            PineValue::Table(value) => PineValue::Table(value),
            PineValue::Na => PineValue::Na,
            _ => PineValue::Na,
        })
    }
}
