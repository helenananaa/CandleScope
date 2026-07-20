use pine_ir::{CallSiteId, HirBinaryOp, HirCallArg, HirExpr};

use crate::runtime::call_context::RuntimeCallContext;
use crate::*;

impl<'a> HistoricalRuntime<'a> {
    pub(crate) fn eval_call(
        &mut self,
        callee: &str,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        if let Some(result) = self.eval_legacy_call(callee, args) {
            return result;
        }
        if let Some(result) = self.eval_variable_call(callee, call_site_id, args) {
            return result;
        }
        if let Some(result) = self.eval_runtime_error_call(callee, args) {
            return result;
        }
        if let Some(result) = self.eval_alert_call(callee, call_site_id, args) {
            return result;
        }
        if let Some(result) = self.eval_output_call(callee, call_site_id, args) {
            return result;
        }
        if let Some(result) = self.eval_drawing_call(callee, call_site_id, args) {
            return result;
        }
        if let Some(result) = self.eval_chart_point_call(callee, args) {
            return result;
        }
        if let Some(result) = self.eval_request_call(callee, call_site_id, args) {
            return result;
        }
        if let Some(result) = self.eval_strategy_call(callee, call_site_id, args) {
            return result;
        }
        if let Some(result) = self.eval_color_call(callee, args) {
            return result;
        }
        if let Some(result) = self.eval_string_call(callee, args) {
            return result;
        }
        if let Some(result) = self.eval_syminfo_call(callee, args) {
            return result;
        }
        if let Some(result) = self.eval_ticker_call(callee, args) {
            return result;
        }
        if let Some(result) = self.eval_time_call(callee, args) {
            return result;
        }
        if let Some(result) = self.eval_cast_call(callee, args) {
            return result;
        }
        {
            let mut context = RuntimeCallContext::new(self);
            if let Some(result) =
                crate::builtins::math::eval_math_call(&mut context, callee, call_site_id, args)
            {
                return result;
            }
        }
        if let Some(result) = self.eval_ta_call(callee, call_site_id, args) {
            return result;
        }
        if let Some(result) = self.eval_array_call(callee, args) {
            return result;
        }
        if let Some(result) = self.eval_map_call(callee, args) {
            return result;
        }
        if let Some(result) = self.eval_matrix_call(callee, args) {
            return result;
        }

        Err(RuntimeError {
            message: format!("unsupported runtime call `{callee}`"),
        })
    }

    fn eval_legacy_call(
        &mut self,
        callee: &str,
        args: &[HirCallArg],
    ) -> Option<Result<PineValue, RuntimeError>> {
        match callee {
            "$legacy.iff" => Some(self.eval_legacy_iff(args)),
            "$legacy.rsi_series" => Some(self.eval_legacy_rsi_series(args)),
            _ => None,
        }
    }

    fn eval_legacy_iff(&mut self, args: &[HirCallArg]) -> Result<PineValue, RuntimeError> {
        let condition = self.eval_expr(legacy_arg(args, 0, "condition")?)?;
        let result1 = self.eval_expr(legacy_arg(args, 1, "result1")?)?;
        let result2 = self.eval_expr(legacy_arg(args, 2, "result2")?)?;
        Ok(match condition {
            PineValue::Bool(true) => result1,
            PineValue::Bool(false) | PineValue::Na => result2,
            _ => PineValue::Na,
        })
    }

    fn eval_legacy_rsi_series(&mut self, args: &[HirCallArg]) -> Result<PineValue, RuntimeError> {
        let x = self.eval_expr(legacy_arg(args, 0, "x")?)?;
        let y = self.eval_expr(legacy_arg(args, 1, "y")?)?;
        let ratio = crate::runtime::expressions::eval_binary(HirBinaryOp::Div, x, y)?;
        let denominator = crate::runtime::expressions::eval_binary(
            HirBinaryOp::Add,
            PineValue::Float(1.0),
            ratio,
        )?;
        let fraction = crate::runtime::expressions::eval_binary(
            HirBinaryOp::Div,
            PineValue::Float(100.0),
            denominator,
        )?;
        crate::runtime::expressions::eval_binary(
            HirBinaryOp::Sub,
            PineValue::Float(100.0),
            fraction,
        )
    }
}

fn legacy_arg<'a>(
    args: &'a [HirCallArg],
    positional: usize,
    name: &str,
) -> Result<&'a HirExpr, RuntimeError> {
    args.iter()
        .find(|arg| arg.name.as_deref() == Some(name))
        .or_else(|| args.get(positional))
        .map(|arg| &arg.value)
        .ok_or_else(|| RuntimeError {
            message: format!("internal legacy call is missing argument `{name}`"),
        })
}
