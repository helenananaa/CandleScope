use pine_ir::{CallSiteId, HirExpr};

use crate::algorithms::random::{next_random_state, random_unit_interval};
use crate::algorithms::rolling_window::RollingWindowState;
use crate::*;

pub(crate) struct RuntimeCallContext<'runtime, 'program> {
    runtime: &'runtime mut HistoricalRuntime<'program>,
}

impl<'runtime, 'program> RuntimeCallContext<'runtime, 'program> {
    pub(crate) fn new(runtime: &'runtime mut HistoricalRuntime<'program>) -> Self {
        Self { runtime }
    }

    pub(crate) fn eval_expr(&mut self, expr: &HirExpr) -> Result<PineValue, RuntimeError> {
        self.runtime.eval_expr(expr)
    }

    pub(crate) fn update_rolling_window(
        &mut self,
        call_site_id: CallSiteId,
        source: PineValue,
        length: usize,
    ) -> &RollingWindowState {
        self.runtime
            .update_rolling_window(call_site_id, source, length)
    }

    pub(crate) fn next_random_unit(&mut self, call_site_id: CallSiteId, initial_state: u64) -> f64 {
        let state = self
            .runtime
            .random_state
            .entry(call_site_id)
            .or_insert(initial_state);
        *state = next_random_state(*state);
        random_unit_interval(*state)
    }
}
