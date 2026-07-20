use pine_ir::{HirCallArg, HirExpr};

use crate::runtime::call_context::RuntimeCallContext;
use crate::*;

#[derive(Clone, Copy)]
pub(crate) struct RuntimeArgs<'args> {
    raw: &'args [HirCallArg],
}

impl<'args> RuntimeArgs<'args> {
    pub(crate) fn new(raw: &'args [HirCallArg]) -> Self {
        Self { raw }
    }

    pub(crate) fn len(self) -> usize {
        self.raw.len()
    }

    pub(crate) fn exprs(self) -> impl Iterator<Item = &'args HirExpr> {
        self.raw.iter().map(|arg| &arg.value)
    }

    pub(crate) fn value(
        self,
        context: &mut RuntimeCallContext<'_, '_>,
        index: usize,
    ) -> Result<PineValue, RuntimeError> {
        context.eval_expr(&self.raw[index].value)
    }

    pub(crate) fn optional_value(
        self,
        context: &mut RuntimeCallContext<'_, '_>,
        index: usize,
    ) -> Result<Option<PineValue>, RuntimeError> {
        self.raw
            .get(index)
            .map(|arg| context.eval_expr(&arg.value))
            .transpose()
    }
}

pub(crate) fn output_id(value: PineValue) -> Option<u32> {
    match value {
        PineValue::Plot(id) | PineValue::HLine(id) => Some(id),
        _ => None,
    }
}

pub(crate) fn call_arg_expr<'a>(
    args: &'a [HirCallArg],
    index: usize,
    name: &str,
) -> Option<&'a HirExpr> {
    args.iter()
        .find(|arg| arg.name.as_deref() == Some(name))
        .or_else(|| args.get(index).filter(|arg| arg.name.is_none()))
        .map(|arg| &arg.value)
}
