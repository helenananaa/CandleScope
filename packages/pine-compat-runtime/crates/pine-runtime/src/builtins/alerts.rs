use pine_ir::{CallSiteId, HirCallArg};

use crate::builtins::args::call_arg_expr;
use crate::builtins::strings::format_number;
use crate::builtins::time::{format_utc_datetime, utc_datetime_from_millis};
use crate::*;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum AlertFrequency {
    All,
    OncePerBar,
    OncePerBarClose,
}

impl<'a> HistoricalRuntime<'a> {
    pub(crate) fn eval_alert_call(
        &mut self,
        callee: &str,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Option<Result<PineValue, RuntimeError>> {
        Some(match callee {
            "alert" => self.eval_alert(call_site_id, args),
            "alertcondition" => self.eval_alertcondition(call_site_id, args),
            _ => return None,
        })
    }

    fn eval_alert(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let message = self.alert_string_arg("alert", args, 0, "message")?;
        let frequency = self.alert_frequency_arg(args)?;
        match frequency {
            AlertFrequency::All => {}
            AlertFrequency::OncePerBar => {
                if !self.alert_once_per_bar_calls.insert(call_site_id) {
                    return Ok(PineValue::Void);
                }
            }
            AlertFrequency::OncePerBarClose => {
                if !matches!(
                    self.current_bar_update_kind,
                    BarUpdateKind::Historical | BarUpdateKind::Confirmed
                ) {
                    return Ok(PineValue::Void);
                }
                if !self.alert_once_per_bar_calls.insert(call_site_id) {
                    return Ok(PineValue::Void);
                }
            }
        }
        self.push_alert_event(call_site_id, "alert".to_owned(), message);
        Ok(PineValue::Void)
    }

    fn eval_alertcondition(
        &mut self,
        call_site_id: CallSiteId,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let Some(condition_arg) = call_arg_expr(args, 0, "condition") else {
            return Err(RuntimeError {
                message: "alertcondition missing condition argument".to_owned(),
            });
        };
        let condition = self.eval_expr(condition_arg)?;
        if !matches!(condition, PineValue::Bool(true)) {
            return Ok(PineValue::Void);
        }

        let source = self.alert_string_arg("alertcondition", args, 1, "title")?;
        let message = self.alert_string_arg("alertcondition", args, 2, "message")?;
        let message = self.render_alertcondition_message(&message);
        self.push_alert_event(call_site_id, source, message);
        Ok(PineValue::Void)
    }

    fn push_alert_event(&mut self, call_site_id: CallSiteId, source: String, message: String) {
        let time = self.current_bar.map_or(0, |bar| bar.time);
        self.alerts.push(AlertEvent {
            id: call_site_id.0,
            bar_index: self.bars,
            time,
            message,
            source,
        });
    }

    fn alert_string_arg(
        &mut self,
        callee: &str,
        args: &[HirCallArg],
        index: usize,
        name: &str,
    ) -> Result<String, RuntimeError> {
        let Some(expr) = call_arg_expr(args, index, name) else {
            return Err(RuntimeError {
                message: format!("{callee} missing {name} argument"),
            });
        };
        match self.eval_expr(expr)? {
            PineValue::String(value) => Ok(value),
            value => Err(RuntimeError {
                message: format!("{callee} {name} evaluated to {value:?}"),
            }),
        }
    }

    fn alert_frequency_arg(&mut self, args: &[HirCallArg]) -> Result<AlertFrequency, RuntimeError> {
        let Some(expr) = call_arg_expr(args, 1, "freq") else {
            return Ok(AlertFrequency::OncePerBar);
        };
        match self.eval_expr(expr)? {
            PineValue::String(value) if value == "alert.freq_all" => Ok(AlertFrequency::All),
            PineValue::String(value) if value == "alert.freq_once_per_bar" => {
                Ok(AlertFrequency::OncePerBar)
            }
            PineValue::String(value) if value == "alert.freq_once_per_bar_close" => {
                Ok(AlertFrequency::OncePerBarClose)
            }
            PineValue::String(value) => Err(RuntimeError {
                message: format!("unsupported alert frequency {value:?}"),
            }),
            value => Err(RuntimeError {
                message: format!("alert freq evaluated to {value:?}"),
            }),
        }
    }

    fn render_alertcondition_message(&self, message: &str) -> String {
        let Some(bar) = self.current_bar else {
            return message.to_owned();
        };

        message
            .replace("{{open}}", &format_number(bar.open, ""))
            .replace("{{high}}", &format_number(bar.high, ""))
            .replace("{{low}}", &format_number(bar.low, ""))
            .replace("{{close}}", &format_number(bar.close, ""))
            .replace("{{volume}}", &format_number(bar.volume, ""))
            .replace("{{ticker}}", self.alert_ticker_placeholder())
            .replace(
                "{{interval}}",
                self.request_environment.chart().timeframe().value(),
            )
            .replace("{{exchange}}", self.alert_exchange_placeholder())
            .replace("{{time}}", &self.alert_time_placeholder(bar.time))
    }

    fn alert_ticker_placeholder(&self) -> &str {
        self.request_environment
            .chart()
            .symbol()
            .rsplit_once(':')
            .map_or_else(
                || self.request_environment.chart().symbol(),
                |(_, ticker)| ticker,
            )
    }

    fn alert_exchange_placeholder(&self) -> &str {
        self.request_environment
            .chart()
            .symbol()
            .rsplit_once(':')
            .map_or("", |(exchange, _)| exchange)
    }

    fn alert_time_placeholder(&self, timestamp: i64) -> String {
        utc_datetime_from_millis(timestamp)
            .map(|datetime| format_utc_datetime(datetime, "yyyy-MM-dd'T'HH:mm:ssZ"))
            .unwrap_or_else(|_| timestamp.to_string())
    }
}
