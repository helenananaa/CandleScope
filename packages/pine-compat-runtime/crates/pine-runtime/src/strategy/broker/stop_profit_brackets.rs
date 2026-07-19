use super::{
    BrokerState,
    pending_exits::{
        DeferredBracketLeg, DeferredRelativeExit, DeferredRelativeExitTrigger, ExitQuantityRequest,
        PendingExit, PendingExitQuantity, PendingExitTrigger,
    },
};
use crate::RuntimeDiagnostic;

#[derive(Debug, Clone, Copy)]
pub(crate) struct StopProfitBracketSpec {
    pub(crate) stop_price: f64,
    pub(crate) profit_ticks: f64,
    pub(crate) mintick: f64,
}

impl BrokerState {
    pub(crate) fn place_exit_bracket_stop_profit_ticks(
        &mut self,
        id: String,
        from_entry: String,
        spec: StopProfitBracketSpec,
        bar_index: usize,
    ) {
        self.place_exit_bracket_stop_profit_ticks_quantity(
            id,
            from_entry,
            spec,
            ExitQuantityRequest::Full,
            bar_index,
        );
    }

    pub(crate) fn place_exit_bracket_stop_profit_ticks_qty(
        &mut self,
        id: String,
        from_entry: String,
        spec: StopProfitBracketSpec,
        qty: f64,
        bar_index: usize,
    ) {
        self.place_exit_bracket_stop_profit_ticks_quantity(
            id,
            from_entry,
            spec,
            ExitQuantityRequest::Fixed(qty),
            bar_index,
        );
    }

    pub(crate) fn place_exit_bracket_stop_profit_ticks_qty_percent(
        &mut self,
        id: String,
        from_entry: String,
        spec: StopProfitBracketSpec,
        qty_percent: f64,
        bar_index: usize,
    ) {
        self.place_exit_bracket_stop_profit_ticks_quantity(
            id,
            from_entry,
            spec,
            ExitQuantityRequest::Percent(qty_percent),
            bar_index,
        );
    }

    pub(crate) fn place_all_entry_exit_stop_profit_bracket(
        &mut self,
        id: String,
        spec: StopProfitBracketSpec,
        bar_index: usize,
    ) {
        if !spec.stop_price.is_finite() {
            self.diagnostics.push(RuntimeDiagnostic {
                code: "E_STRATEGY_EXIT_PRICE".to_owned(),
                message: "`strategy.exit` price must be finite".to_owned(),
            });
            return;
        }
        let Some(profit_offset) = self.exit_tick_price_offset(spec.profit_ticks, spec.mintick)
        else {
            return;
        };
        let metadata = self.take_next_exit_metadata();
        let mut pending_exits = Vec::new();
        for index in 0..self.trade_ledger.open_count() {
            let Some(open_trade) = self.trade_ledger.open_at(index) else {
                continue;
            };
            pending_exits.push(PendingExit {
                id: id.clone(),
                from_entry: open_trade.id.clone(),
                target_trade_key: Some(open_trade.key),
                trigger: PendingExitTrigger::Bracket {
                    downside: spec.stop_price,
                    upside: open_trade.entry_price + profit_offset,
                },
                quantity: PendingExitQuantity::Full,
                reserved_quantity: open_trade.quantity,
                multiple_reservation: false,
                last_update_bar_index: bar_index,
                metadata: metadata.clone(),
            });
        }
        if pending_exits.is_empty() {
            self.order_book
                .exits_mut()
                .replace_all_entry_deferred_relative(DeferredRelativeExit {
                    id,
                    from_entry: String::new(),
                    trigger: DeferredRelativeExitTrigger::Bracket {
                        downside: DeferredBracketLeg::Absolute(spec.stop_price),
                        upside: DeferredBracketLeg::RelativeProfit {
                            ticks: spec.profit_ticks,
                            mintick: spec.mintick,
                        },
                    },
                    quantity: ExitQuantityRequest::Full,
                    last_update_bar_index: bar_index,
                    metadata,
                });
            return;
        }
        self.order_book
            .exits_mut()
            .replace_all_entry_deferred_relative(DeferredRelativeExit {
                id,
                from_entry: String::new(),
                trigger: DeferredRelativeExitTrigger::Bracket {
                    downside: DeferredBracketLeg::Absolute(spec.stop_price),
                    upside: DeferredBracketLeg::RelativeProfit {
                        ticks: spec.profit_ticks,
                        mintick: spec.mintick,
                    },
                },
                quantity: ExitQuantityRequest::Full,
                last_update_bar_index: bar_index,
                metadata,
            });
        self.order_book.exits_mut().replace_all_many(pending_exits);
    }

    fn place_exit_bracket_stop_profit_ticks_quantity(
        &mut self,
        id: String,
        from_entry: String,
        spec: StopProfitBracketSpec,
        quantity: ExitQuantityRequest,
        bar_index: usize,
    ) {
        if !spec.stop_price.is_finite() {
            self.diagnostics.push(RuntimeDiagnostic {
                code: "E_STRATEGY_EXIT_PRICE".to_owned(),
                message: "`strategy.exit` price must be finite".to_owned(),
            });
            return;
        }
        if self.position_size <= 0.0 && self.has_pending_entry(&from_entry) {
            self.place_deferred_relative_stop_profit_bracket(
                id, from_entry, spec, quantity, bar_index,
            );
            return;
        }
        if self.reject_entry_relative_exit_for_pending_entry(&from_entry) {
            return;
        }
        let Some(upside) = self.exit_profit_price_from_ticks_for_entry(
            &from_entry,
            spec.profit_ticks,
            spec.mintick,
        ) else {
            return;
        };
        let metadata = self.take_next_exit_metadata();
        self.place_exit(
            id,
            from_entry,
            PendingExitTrigger::Bracket {
                downside: spec.stop_price,
                upside,
            },
            quantity,
            bar_index,
            metadata,
        );
    }

    fn place_deferred_relative_stop_profit_bracket(
        &mut self,
        id: String,
        from_entry: String,
        spec: StopProfitBracketSpec,
        quantity: ExitQuantityRequest,
        bar_index: usize,
    ) {
        let Some(pending_entry_quantity) = self.order_book.entries().quantity_for_id(&from_entry)
        else {
            return;
        };
        if self
            .exit_tick_price_offset(spec.profit_ticks, spec.mintick)
            .is_none()
            || self
                .resolve_exit_quantity_request_for_available(
                    quantity,
                    pending_entry_quantity,
                    pending_entry_quantity,
                )
                .is_none()
        {
            return;
        }
        let metadata = self.take_next_exit_metadata();
        self.order_book
            .exits_mut()
            .replace_or_append_deferred_relative(DeferredRelativeExit {
                id,
                from_entry,
                trigger: DeferredRelativeExitTrigger::Bracket {
                    downside: DeferredBracketLeg::Absolute(spec.stop_price),
                    upside: DeferredBracketLeg::RelativeProfit {
                        ticks: spec.profit_ticks,
                        mintick: spec.mintick,
                    },
                },
                quantity,
                last_update_bar_index: bar_index,
                metadata,
            });
    }
}
