use pine_ir::HirCallArg;

use crate::builtins::args::call_arg_expr;
use crate::*;

impl<'a> HistoricalRuntime<'a> {
    pub(crate) fn eval_runtime_error_call(
        &mut self,
        callee: &str,
        args: &[HirCallArg],
    ) -> Option<Result<PineValue, RuntimeError>> {
        Some(match callee {
            "runtime.error" => self.eval_runtime_error(args),
            _ => return None,
        })
    }

    fn eval_runtime_error(&mut self, args: &[HirCallArg]) -> Result<PineValue, RuntimeError> {
        let Some(message) = call_arg_expr(args, 0, "message") else {
            return Err(RuntimeError {
                message: "runtime.error missing message argument".to_owned(),
            });
        };
        let message = match self.eval_expr(message)? {
            PineValue::String(message) => message,
            PineValue::Na => "NaN".to_owned(),
            value => {
                return Err(RuntimeError {
                    message: format!(
                        "runtime.error message must evaluate to a string or na, got {value:?}"
                    ),
                });
            }
        };

        Err(RuntimeError { message })
    }
}
