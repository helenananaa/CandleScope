use pine_ir::HirCallArg;

use crate::value::ChartPointValue;
use crate::*;

impl<'a> HistoricalRuntime<'a> {
    pub(crate) fn eval_chart_point_call(
        &mut self,
        callee: &str,
        args: &[HirCallArg],
    ) -> Option<Result<PineValue, RuntimeError>> {
        Some(match callee {
            "chart.point.new" => self.eval_chart_point_new(args),
            "chart.point.now" => self.eval_chart_point_now(args),
            "chart.point.from_index" => self.eval_chart_point_from_index(args),
            "chart.point.from_time" => self.eval_chart_point_from_time(args),
            "chart.point.copy" => self.eval_chart_point_copy(args),
            _ => return None,
        })
    }

    fn eval_chart_point_new(&mut self, args: &[HirCallArg]) -> Result<PineValue, RuntimeError> {
        let time = self.eval_chart_point_int_arg(&args[0])?;
        let index = self.eval_chart_point_int_arg(&args[1])?;
        let price = self.eval_chart_point_price_arg(&args[2])?;
        Ok(PineValue::ChartPoint(ChartPointValue::new(
            time, index, price,
        )))
    }

    fn eval_chart_point_now(&mut self, args: &[HirCallArg]) -> Result<PineValue, RuntimeError> {
        let price = self.eval_chart_point_price_arg(&args[0])?;
        let (time, index) = self
            .current_bar
            .map(|bar| (PineValue::Int(bar.time), PineValue::Int(self.bars as i64)))
            .unwrap_or((PineValue::Na, PineValue::Na));
        Ok(PineValue::ChartPoint(ChartPointValue::new(
            time, index, price,
        )))
    }

    fn eval_chart_point_from_index(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let index = self.eval_chart_point_int_arg(&args[0])?;
        let price = self.eval_chart_point_price_arg(&args[1])?;
        Ok(PineValue::ChartPoint(ChartPointValue::new(
            PineValue::Na,
            index,
            price,
        )))
    }

    fn eval_chart_point_from_time(
        &mut self,
        args: &[HirCallArg],
    ) -> Result<PineValue, RuntimeError> {
        let time = self.eval_chart_point_int_arg(&args[0])?;
        let price = self.eval_chart_point_price_arg(&args[1])?;
        Ok(PineValue::ChartPoint(ChartPointValue::new(
            time,
            PineValue::Na,
            price,
        )))
    }

    fn eval_chart_point_copy(&mut self, args: &[HirCallArg]) -> Result<PineValue, RuntimeError> {
        match self.eval_expr(&args[0].value)? {
            PineValue::ChartPoint(point) => Ok(PineValue::ChartPoint(point)),
            PineValue::Na => Ok(PineValue::Na),
            _ => Ok(PineValue::Na),
        }
    }

    fn eval_chart_point_int_arg(&mut self, arg: &HirCallArg) -> Result<PineValue, RuntimeError> {
        Ok(match self.eval_expr(&arg.value)? {
            PineValue::Int(value) => PineValue::Int(value),
            PineValue::Na => PineValue::Na,
            _ => PineValue::Na,
        })
    }

    fn eval_chart_point_price_arg(&mut self, arg: &HirCallArg) -> Result<PineValue, RuntimeError> {
        Ok(normalize_chart_point_price(self.eval_expr(&arg.value)?))
    }
}

pub(crate) fn normalize_chart_point_field(index: usize, value: PineValue) -> PineValue {
    match index {
        0 | 1 => match value {
            PineValue::Int(value) => PineValue::Int(value),
            PineValue::Na => PineValue::Na,
            _ => PineValue::Na,
        },
        2 => normalize_chart_point_price(value),
        _ => PineValue::Na,
    }
}

fn normalize_chart_point_price(value: PineValue) -> PineValue {
    match value {
        PineValue::Int(value) => PineValue::Float(value as f64),
        PineValue::Float(value) => PineValue::Float(value),
        PineValue::Na => PineValue::Na,
        _ => PineValue::Na,
    }
}
