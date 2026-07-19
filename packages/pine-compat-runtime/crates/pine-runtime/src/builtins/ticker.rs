use pine_ir::HirCallArg;

use crate::*;

impl<'a> HistoricalRuntime<'a> {
    pub(crate) fn eval_ticker_call(
        &mut self,
        callee: &str,
        args: &[HirCallArg],
    ) -> Option<Result<PineValue, RuntimeError>> {
        if !callee.starts_with("ticker.") {
            return None;
        }

        Some(match callee {
            "ticker.heikinashi" => self.eval_ticker_heikinashi(args),
            "ticker.inherit" => self.eval_ticker_inherit(args),
            "ticker.kagi" => self.eval_ticker_kagi(args),
            "ticker.linebreak" => self.eval_ticker_linebreak(args),
            "ticker.new" => self.eval_ticker_new(args),
            "ticker.modify" => self.eval_ticker_modify(args),
            "ticker.pointfigure" => self.eval_ticker_pointfigure(args),
            "ticker.renko" => self.eval_ticker_renko(args),
            "ticker.standard" => self.eval_ticker_standard(args),
            _ => return None,
        })
    }

    fn eval_ticker_heikinashi(&mut self, args: &[HirCallArg]) -> Result<PineValue, RuntimeError> {
        let PineValue::String(tickerid) = self.eval_expr(&args[0].value)? else {
            return Ok(PineValue::Na);
        };

        let symbol = standard_ticker_id(&tickerid);
        Ok(PineValue::String(non_standard_ticker_id(
            &symbol,
            "heikinashi",
        )))
    }

    fn eval_ticker_inherit(&mut self, args: &[HirCallArg]) -> Result<PineValue, RuntimeError> {
        let PineValue::String(from_tickerid) = self.eval_expr(&args[0].value)? else {
            return Ok(PineValue::Na);
        };
        let PineValue::String(symbol) = self.eval_expr(&args[1].value)? else {
            return Ok(PineValue::Na);
        };

        Ok(PineValue::String(inherited_ticker_id(
            &from_tickerid,
            &symbol,
        )))
    }

    fn eval_ticker_kagi(&mut self, args: &[HirCallArg]) -> Result<PineValue, RuntimeError> {
        let PineValue::String(tickerid) = self.eval_expr(&args[0].value)? else {
            return Ok(PineValue::Na);
        };
        let PineValue::String(style) = self.eval_expr(&args[1].value)? else {
            return Ok(PineValue::Na);
        };
        let Some(param) = numeric_param_string(&self.eval_expr(&args[2].value)?) else {
            return Ok(PineValue::Na);
        };

        let symbol = standard_ticker_id(&tickerid);
        Ok(PineValue::String(kagi_ticker_id(&symbol, &style, &param)))
    }

    fn eval_ticker_linebreak(&mut self, args: &[HirCallArg]) -> Result<PineValue, RuntimeError> {
        let PineValue::String(tickerid) = self.eval_expr(&args[0].value)? else {
            return Ok(PineValue::Na);
        };
        let PineValue::Int(number_of_lines) = self.eval_expr(&args[1].value)? else {
            return Ok(PineValue::Na);
        };

        let symbol = standard_ticker_id(&tickerid);
        Ok(PineValue::String(linebreak_ticker_id(
            &symbol,
            number_of_lines,
        )))
    }

    fn eval_ticker_pointfigure(&mut self, args: &[HirCallArg]) -> Result<PineValue, RuntimeError> {
        let PineValue::String(tickerid) = self.eval_expr(&args[0].value)? else {
            return Ok(PineValue::Na);
        };
        let PineValue::String(source) = self.eval_expr(&args[1].value)? else {
            return Ok(PineValue::Na);
        };
        let PineValue::String(style) = self.eval_expr(&args[2].value)? else {
            return Ok(PineValue::Na);
        };
        let Some(param) = numeric_param_string(&self.eval_expr(&args[3].value)?) else {
            return Ok(PineValue::Na);
        };
        let PineValue::Int(reversal) = self.eval_expr(&args[4].value)? else {
            return Ok(PineValue::Na);
        };

        let symbol = standard_ticker_id(&tickerid);
        Ok(PineValue::String(pointfigure_ticker_id(
            &symbol, &source, &style, &param, reversal,
        )))
    }

    fn eval_ticker_renko(&mut self, args: &[HirCallArg]) -> Result<PineValue, RuntimeError> {
        let PineValue::String(tickerid) = self.eval_expr(&args[0].value)? else {
            return Ok(PineValue::Na);
        };
        let PineValue::String(style) = self.eval_expr(&args[1].value)? else {
            return Ok(PineValue::Na);
        };
        let Some(param) = numeric_param_string(&self.eval_expr(&args[2].value)?) else {
            return Ok(PineValue::Na);
        };

        let symbol = standard_ticker_id(&tickerid);
        Ok(PineValue::String(renko_ticker_id(&symbol, &style, &param)))
    }

    fn eval_ticker_new(&mut self, args: &[HirCallArg]) -> Result<PineValue, RuntimeError> {
        let PineValue::String(prefix) = self.eval_expr(&args[0].value)? else {
            return Ok(PineValue::Na);
        };
        let PineValue::String(ticker) = self.eval_expr(&args[1].value)? else {
            return Ok(PineValue::Na);
        };

        let symbol = format!("{prefix}:{ticker}");
        let Some(session_arg) = args.get(2) else {
            return Ok(PineValue::String(symbol));
        };
        let PineValue::String(session) = self.eval_expr(&session_arg.value)? else {
            return Ok(PineValue::Na);
        };
        let adjustment = if let Some(adjustment_arg) = args.get(3) {
            let PineValue::String(adjustment) = self.eval_expr(&adjustment_arg.value)? else {
                return Ok(PineValue::Na);
            };
            Some(adjustment)
        } else {
            None
        };
        let settlement_as_close = if let Some(settlement_arg) = args.get(4) {
            let PineValue::String(settlement_as_close) = self.eval_expr(&settlement_arg.value)?
            else {
                return Ok(PineValue::Na);
            };
            Some(settlement_as_close)
        } else {
            None
        };
        let backadjustment = if let Some(backadjustment_arg) = args.get(5) {
            let PineValue::String(backadjustment) = self.eval_expr(&backadjustment_arg.value)?
            else {
                return Ok(PineValue::Na);
            };
            Some(backadjustment)
        } else {
            None
        };

        Ok(PineValue::String(modified_ticker_id(
            &symbol,
            &session,
            adjustment.as_deref(),
            settlement_as_close.as_deref(),
            backadjustment.as_deref(),
        )))
    }

    fn eval_ticker_modify(&mut self, args: &[HirCallArg]) -> Result<PineValue, RuntimeError> {
        let PineValue::String(tickerid) = self.eval_expr(&args[0].value)? else {
            return Ok(PineValue::Na);
        };

        let Some(session_arg) = args.get(1) else {
            return Ok(PineValue::String(tickerid));
        };
        let PineValue::String(session) = self.eval_expr(&session_arg.value)? else {
            return Ok(PineValue::Na);
        };
        let adjustment = if let Some(adjustment_arg) = args.get(2) {
            let PineValue::String(adjustment) = self.eval_expr(&adjustment_arg.value)? else {
                return Ok(PineValue::Na);
            };
            Some(adjustment)
        } else {
            None
        };
        let settlement_as_close = if let Some(settlement_arg) = args.get(3) {
            let PineValue::String(settlement_as_close) = self.eval_expr(&settlement_arg.value)?
            else {
                return Ok(PineValue::Na);
            };
            Some(settlement_as_close)
        } else {
            None
        };
        let backadjustment = if let Some(backadjustment_arg) = args.get(4) {
            let PineValue::String(backadjustment) = self.eval_expr(&backadjustment_arg.value)?
            else {
                return Ok(PineValue::Na);
            };
            Some(backadjustment)
        } else {
            None
        };

        let symbol = standard_ticker_id(&tickerid);
        Ok(PineValue::String(modified_ticker_id(
            &symbol,
            &session,
            adjustment.as_deref(),
            settlement_as_close.as_deref(),
            backadjustment.as_deref(),
        )))
    }

    fn eval_ticker_standard(&mut self, args: &[HirCallArg]) -> Result<PineValue, RuntimeError> {
        let PineValue::String(symbol) = self.eval_expr(&args[0].value)? else {
            return Ok(PineValue::Na);
        };

        Ok(PineValue::String(standard_ticker_id(&symbol)))
    }
}

fn standard_ticker_id(symbol: &str) -> String {
    extract_json_symbol_field(symbol).unwrap_or_else(|| symbol.to_owned())
}

fn inherited_ticker_id(from_tickerid: &str, symbol: &str) -> String {
    replace_json_symbol_field(from_tickerid, symbol).unwrap_or_else(|| symbol.to_owned())
}

fn modified_ticker_id(
    symbol: &str,
    session: &str,
    adjustment: Option<&str>,
    settlement_as_close: Option<&str>,
    backadjustment: Option<&str>,
) -> String {
    let mut fields = vec![format!(r#""session":"{}""#, escape_json_string(session))];
    if let Some(adjustment) = adjustment {
        fields.push(format!(
            r#""adjustment":"{}""#,
            escape_json_string(adjustment)
        ));
    }
    if let Some(settlement_as_close) = settlement_as_close {
        fields.push(format!(
            r#""settlement-as-close":"{}""#,
            escape_json_string(settlement_as_close)
        ));
    }
    if let Some(backadjustment) = backadjustment {
        fields.push(format!(
            r#""backadjustment":"{}""#,
            escape_json_string(backadjustment)
        ));
    }
    fields.push(format!(r#""symbol":"{}""#, escape_json_string(symbol)));
    format!("{{{}}}", fields.join(","))
}

fn non_standard_ticker_id(symbol: &str, chart: &str) -> String {
    format!(
        r#"{{"chart":"{}","symbol":"{}"}}"#,
        escape_json_string(chart),
        escape_json_string(symbol)
    )
}

fn linebreak_ticker_id(symbol: &str, number_of_lines: i64) -> String {
    format!(
        r#"{{"chart":"linebreak","lines":{},"symbol":"{}"}}"#,
        number_of_lines,
        escape_json_string(symbol)
    )
}

fn kagi_ticker_id(symbol: &str, style: &str, param: &str) -> String {
    format!(
        r#"{{"chart":"kagi","style":"{}","param":{},"symbol":"{}"}}"#,
        escape_json_string(style),
        param,
        escape_json_string(symbol)
    )
}

fn pointfigure_ticker_id(
    symbol: &str,
    source: &str,
    style: &str,
    param: &str,
    reversal: i64,
) -> String {
    format!(
        r#"{{"chart":"pointfigure","source":"{}","style":"{}","param":{},"reversal":{},"symbol":"{}"}}"#,
        escape_json_string(source),
        escape_json_string(style),
        param,
        reversal,
        escape_json_string(symbol)
    )
}

fn renko_ticker_id(symbol: &str, style: &str, param: &str) -> String {
    format!(
        r#"{{"chart":"renko","style":"{}","param":{},"symbol":"{}"}}"#,
        escape_json_string(style),
        param,
        escape_json_string(symbol)
    )
}

fn numeric_param_string(value: &PineValue) -> Option<String> {
    match value {
        PineValue::Int(value) => Some(value.to_string()),
        PineValue::Float(value) if value.is_finite() => Some(value.to_string()),
        _ => None,
    }
}

fn escape_json_string(value: &str) -> String {
    let mut escaped = String::new();
    for ch in value.chars() {
        match ch {
            '\\' => escaped.push_str(r#"\\"#),
            '"' => escaped.push_str(r#"\""#),
            _ => escaped.push(ch),
        }
    }
    escaped
}

fn extract_json_symbol_field(value: &str) -> Option<String> {
    let (start, end) = json_symbol_field_value_bounds(value)?;
    Some(unescape_json_string_content(&value[start..end]))
}

fn replace_json_symbol_field(value: &str, symbol: &str) -> Option<String> {
    let (start, end) = json_symbol_field_value_bounds(value)?;
    Some(format!(
        "{}{}{}",
        &value[..start],
        escape_json_string(symbol),
        &value[end..]
    ))
}

fn json_symbol_field_value_bounds(value: &str) -> Option<(usize, usize)> {
    let marker = "\"symbol\"";
    let marker_start = value.find(marker)?;
    let after_marker_start = marker_start + marker.len();
    let after_marker = value[after_marker_start..].trim_start();
    let colon_offset = value[after_marker_start..].len() - after_marker.len();
    let colon_start = after_marker_start + colon_offset;
    let after_colon_start = value[colon_start..]
        .strip_prefix(':')
        .map(|_| colon_start + 1)?;
    let after_colon = value[after_colon_start..].trim_start();
    let quote_offset = value[after_colon_start..].len() - after_colon.len();
    let quote_start = after_colon_start + quote_offset;
    let content_start = value[quote_start..]
        .strip_prefix('"')
        .map(|_| quote_start + 1)?;
    let mut escaped = false;

    for (offset, ch) in value[content_start..].char_indices() {
        if escaped {
            escaped = false;
            continue;
        }
        match ch {
            '\\' => escaped = true,
            '"' => return Some((content_start, content_start + offset)),
            _ => {}
        }
    }

    None
}

fn unescape_json_string_content(value: &str) -> String {
    let mut symbol = String::new();
    let mut escaped = false;

    for ch in value.chars() {
        if escaped {
            symbol.push(ch);
            escaped = false;
            continue;
        }
        match ch {
            '\\' => escaped = true,
            _ => symbol.push(ch),
        }
    }

    symbol
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn standard_ticker_extracts_known_symbol_field_shape() {
        assert_eq!(
            standard_ticker_id(r#"{"session":"extended","symbol":"NASDAQ:AAPL"}"#),
            "NASDAQ:AAPL"
        );
        assert_eq!(
            standard_ticker_id(r#""settlement-as-close":true,"symbol":"COMEX:GC1!""#),
            "COMEX:GC1!"
        );
        assert_eq!(standard_ticker_id("NASDAQ:AAPL"), "NASDAQ:AAPL");
    }

    #[test]
    fn inherited_ticker_replaces_known_symbol_field() {
        assert_eq!(
            inherited_ticker_id(
                r#"{"session":"extended","adjustment":"dividends","symbol":"NASDAQ:AAPL"}"#,
                r#"NYSE:PF\"E"#
            ),
            r#"{"session":"extended","adjustment":"dividends","symbol":"NYSE:PF\\\"E"}"#
        );
        assert_eq!(
            inherited_ticker_id(
                r#"{"chart":"renko","style":"ATR","param":10,"symbol":"NASDAQ:AAPL"}"#,
                "NYSE:PFE"
            ),
            r#"{"chart":"renko","style":"ATR","param":10,"symbol":"NYSE:PFE"}"#
        );
        assert_eq!(inherited_ticker_id("NASDAQ:AAPL", "NYSE:PFE"), "NYSE:PFE");
    }

    #[test]
    fn modified_ticker_escapes_json_string_fields() {
        assert_eq!(
            modified_ticker_id(r#"TEST:Q\""#, r#"reg\"ular"#, None, None, None),
            r#"{"session":"reg\\\"ular","symbol":"TEST:Q\\\""}"#
        );
        assert_eq!(
            modified_ticker_id("NASDAQ:AAPL", "extended", Some("dividends"), None, None),
            r#"{"session":"extended","adjustment":"dividends","symbol":"NASDAQ:AAPL"}"#
        );
        assert_eq!(
            modified_ticker_id(
                "COMEX:GC1!",
                "regular",
                Some("none"),
                Some("on"),
                Some("inherit")
            ),
            r#"{"session":"regular","adjustment":"none","settlement-as-close":"on","backadjustment":"inherit","symbol":"COMEX:GC1!"}"#
        );
    }

    #[test]
    fn non_standard_ticker_preserves_escaped_symbol_field() {
        assert_eq!(
            non_standard_ticker_id(r#"TEST:Q\""#, "heikinashi"),
            r#"{"chart":"heikinashi","symbol":"TEST:Q\\\""}"#
        );
    }

    #[test]
    fn linebreak_ticker_preserves_symbol_and_line_count_fields() {
        assert_eq!(
            linebreak_ticker_id(r#"TEST:Q\""#, 3),
            r#"{"chart":"linebreak","lines":3,"symbol":"TEST:Q\\\""}"#
        );
    }

    #[test]
    fn kagi_ticker_preserves_symbol_and_numeric_param_fields() {
        assert_eq!(
            kagi_ticker_id(r#"TEST:Q\""#, r#"AT\"R"#, "10"),
            r#"{"chart":"kagi","style":"AT\\\"R","param":10,"symbol":"TEST:Q\\\""}"#
        );
    }

    #[test]
    fn pointfigure_ticker_preserves_symbol_and_non_standard_fields() {
        assert_eq!(
            pointfigure_ticker_id(r#"TEST:Q\""#, r#"h\"l"#, r#"AT\"R"#, "10", 3),
            r#"{"chart":"pointfigure","source":"h\\\"l","style":"AT\\\"R","param":10,"reversal":3,"symbol":"TEST:Q\\\""}"#
        );
    }

    #[test]
    fn renko_ticker_preserves_symbol_and_numeric_param_fields() {
        assert_eq!(
            renko_ticker_id(r#"TEST:Q\""#, r#"AT\"R"#, "10"),
            r#"{"chart":"renko","style":"AT\\\"R","param":10,"symbol":"TEST:Q\\\""}"#
        );
        assert_eq!(numeric_param_string(&PineValue::Int(10)), Some("10".into()));
        assert_eq!(
            numeric_param_string(&PineValue::Float(2.5)),
            Some("2.5".into())
        );
        assert_eq!(numeric_param_string(&PineValue::Na), None);
    }
}
