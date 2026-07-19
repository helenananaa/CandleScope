use pine_ir::{HirCallArg, HirExpr};

use crate::strategy::{StrategyExitMetadata, StrategyOrderMetadata};
use crate::{HistoricalRuntime, PineValue, RuntimeError};

fn optional_strategy_arg_expr<'a>(
    args: &'a [HirCallArg],
    index: usize,
    name: &str,
) -> Option<&'a HirExpr> {
    args.iter()
        .find(|arg| arg.name.as_deref() == Some(name))
        .or_else(|| args.get(index).filter(|arg| arg.name.is_none()))
        .map(|arg| &arg.value)
}

impl<'a> HistoricalRuntime<'a> {
    pub(super) fn eval_strategy_order_metadata(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<StrategyOrderMetadata, RuntimeError> {
        self.eval_strategy_close_metadata(args, 7)
    }

    pub(super) fn eval_strategy_entry_metadata(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<StrategyOrderMetadata, RuntimeError> {
        Ok(StrategyOrderMetadata {
            comment: self.eval_optional_string_arg(args, 5, "comment")?,
            alert_message: self.eval_optional_string_arg(args, 6, "alert_message")?,
            disable_alert: self.eval_optional_bool_arg(args, 7, "disable_alert")?,
        })
    }

    pub(super) fn eval_strategy_close_metadata(
        &mut self,
        args: &[HirCallArg],
        comment_index: usize,
    ) -> Result<StrategyOrderMetadata, RuntimeError> {
        Ok(StrategyOrderMetadata {
            comment: self.eval_optional_string_arg(args, comment_index, "comment")?,
            alert_message: self.eval_optional_string_arg(
                args,
                comment_index + 1,
                "alert_message",
            )?,
            disable_alert: self.eval_optional_bool_arg(args, comment_index + 2, "disable_alert")?,
        })
    }

    pub(super) fn eval_strategy_exit_metadata(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<StrategyExitMetadata, RuntimeError> {
        Ok(StrategyExitMetadata {
            comment: self.eval_optional_string_arg(args, 11, "comment")?,
            comment_profit: self.eval_optional_string_arg(args, 12, "comment_profit")?,
            comment_loss: self.eval_optional_string_arg(args, 13, "comment_loss")?,
            comment_trailing: self.eval_optional_string_arg(args, 14, "comment_trailing")?,
            alert_message: self.eval_optional_string_arg(args, 15, "alert_message")?,
            alert_profit: self.eval_optional_string_arg(args, 16, "alert_profit")?,
            alert_loss: self.eval_optional_string_arg(args, 17, "alert_loss")?,
            alert_trailing: self.eval_optional_string_arg(args, 18, "alert_trailing")?,
            disable_alert: self.eval_optional_bool_arg(args, 19, "disable_alert")?,
        })
    }

    fn eval_optional_string_arg(
        &mut self,
        args: &[HirCallArg],
        index: usize,
        name: &str,
    ) -> Result<Option<String>, RuntimeError> {
        let Some(expr) = optional_strategy_arg_expr(args, index, name) else {
            return Ok(None);
        };
        Ok(match self.eval_expr(expr)? {
            PineValue::String(value) => Some(value),
            _ => None,
        })
    }

    fn eval_optional_bool_arg(
        &mut self,
        args: &[HirCallArg],
        index: usize,
        name: &str,
    ) -> Result<bool, RuntimeError> {
        let Some(expr) = optional_strategy_arg_expr(args, index, name) else {
            return Ok(false);
        };
        Ok(matches!(self.eval_expr(expr)?, PineValue::Bool(true)))
    }
}
