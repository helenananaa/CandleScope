use pine_ir::HirCallArg;

use crate::*;

impl<'a> HistoricalRuntime<'a> {
    pub(crate) fn eval_syminfo_call(
        &mut self,
        callee: &str,
        args: &[HirCallArg],
    ) -> Option<Result<PineValue, RuntimeError>> {
        if !callee.starts_with("syminfo.") {
            return None;
        }

        Some(match callee {
            "syminfo.prefix" => self.eval_syminfo_symbol_part(args, SymbolPart::Prefix),
            "syminfo.ticker" => self.eval_syminfo_symbol_part(args, SymbolPart::Ticker),
            _ => return None,
        })
    }

    fn eval_syminfo_symbol_part(
        &mut self,
        args: &[HirCallArg],
        part: SymbolPart,
    ) -> Result<PineValue, RuntimeError> {
        let PineValue::String(symbol) = self.eval_expr(&args[0].value)? else {
            return Ok(PineValue::Na);
        };

        let value = match part {
            SymbolPart::Prefix => match symbol.split_once(':') {
                Some((prefix, _)) => prefix.to_owned(),
                None => String::new(),
            },
            SymbolPart::Ticker => match symbol.split_once(':') {
                Some((_, ticker)) => ticker.to_owned(),
                None => symbol,
            },
        };
        Ok(PineValue::String(value))
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum SymbolPart {
    Prefix,
    Ticker,
}
