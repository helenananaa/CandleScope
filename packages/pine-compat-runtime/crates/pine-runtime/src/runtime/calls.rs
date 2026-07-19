use pine_ir::{CallSiteId, HirCallArg};

use crate::runtime::call_context::RuntimeCallContext;
use crate::*;

impl<'a> HistoricalRuntime<'a> {
    pub(crate) fn eval_call(
        &mut self,
        callee: &str,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
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
}
