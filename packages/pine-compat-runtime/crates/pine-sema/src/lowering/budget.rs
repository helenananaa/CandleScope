use pine_syntax::{Diagnostic, Span};

use crate::analyzer::context::Analyzer;

impl Analyzer {
    pub(super) fn enter_lowering_inline(&mut self, span: Span) -> bool {
        if self.lowering_inline_depth >= self.lowering_limits.max_inline_depth {
            self.report_lowering_budget_exceeded("lowering inline call chain is too deep", span);
            return false;
        }

        self.lowering_inline_depth += 1;
        true
    }

    pub(super) fn exit_lowering_inline(&mut self) {
        self.lowering_inline_depth = self.lowering_inline_depth.saturating_sub(1);
    }

    pub(super) fn record_lowering_node(&mut self, span: Span) -> bool {
        if self.lowered_hir_nodes >= self.lowering_limits.max_hir_nodes {
            self.report_lowering_budget_exceeded("lowered HIR is too large", span);
            return false;
        }

        self.lowered_hir_nodes += 1;
        true
    }

    pub(super) fn record_lowering_temp_symbol(&mut self, span: Span) -> bool {
        if self.lowered_temp_symbols >= self.lowering_limits.max_temp_symbols {
            self.report_lowering_budget_exceeded(
                "lowering generated too many temporary symbols",
                span,
            );
            return false;
        }

        self.lowered_temp_symbols += 1;
        true
    }

    fn report_lowering_budget_exceeded(&mut self, message: &str, span: Span) {
        if self.lowering_budget_reported {
            return;
        }

        self.lowering_budget_reported = true;
        self.diagnostics
            .push(Diagnostic::error("E_LOWERING_BUDGET", message, span));
    }
}
