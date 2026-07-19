use super::{
    BrokerState, StrategyExitMetadata,
    loss_profit_brackets::DeferredLossProfitBracketSpec,
    pending_exits::{
        DeferredBracketLeg, DeferredRelativeExit, DeferredRelativeExitTrigger, ExitQuantityRequest,
        PendingExit, PendingExitQuantity, PendingExitTrigger, PendingTrailingActivation,
        PendingTrailingExit, PendingTrailingSpec, PendingTrailingState,
    },
};
use crate::RuntimeDiagnostic;

struct AllEntryResolvedExitPlacement {
    id: String,
    from_entry: String,
    target_trade_key: u64,
    bar_index: usize,
    metadata: StrategyExitMetadata,
}

impl BrokerState {
    pub(super) fn resolve_all_entry_deferred_relative_exit_for_entry(
        &mut self,
        deferred_exit: DeferredRelativeExit,
        entry_id: &str,
        bar_index: usize,
    ) {
        let DeferredRelativeExit {
            id,
            trigger,
            quantity,
            metadata,
            ..
        } = deferred_exit;
        match trigger {
            DeferredRelativeExitTrigger::ProfitTicks { ticks, mintick } => {
                if quantity != ExitQuantityRequest::Full {
                    return;
                }
                let Some((target_trade_key, entry_price)) =
                    self.last_open_trade_key_and_price_for_entry(entry_id)
                else {
                    return;
                };
                let Some(price_offset) = self.exit_tick_price_offset(ticks, mintick) else {
                    return;
                };
                self.place_all_entry_resolved_profit_exit(
                    id,
                    entry_id.to_owned(),
                    target_trade_key,
                    entry_price + price_offset,
                    bar_index,
                    metadata,
                );
            }
            DeferredRelativeExitTrigger::LossTicks { ticks, mintick } => {
                if quantity != ExitQuantityRequest::Full {
                    return;
                }
                let Some((target_trade_key, entry_price)) =
                    self.last_open_trade_key_and_price_for_entry(entry_id)
                else {
                    return;
                };
                let Some(price_offset) = self.exit_tick_price_offset(ticks, mintick) else {
                    return;
                };
                self.place_all_entry_resolved_loss_exit(
                    id,
                    entry_id.to_owned(),
                    target_trade_key,
                    entry_price - price_offset,
                    bar_index,
                    metadata,
                );
            }
            DeferredRelativeExitTrigger::TrailPoints {
                activation_ticks,
                offset_ticks,
                mintick,
            } => {
                if quantity != ExitQuantityRequest::Full {
                    return;
                }
                let Some((target_trade_key, entry_price)) =
                    self.last_open_trade_key_and_price_for_entry(entry_id)
                else {
                    return;
                };
                let Some(activation_offset) =
                    self.exit_tick_price_offset(activation_ticks, mintick)
                else {
                    return;
                };
                let activation_price = entry_price + activation_offset;
                let Some(offset_price_distance) =
                    self.exit_tick_price_offset(offset_ticks, mintick)
                else {
                    return;
                };
                self.place_all_entry_resolved_trail_points_exit(
                    id,
                    entry_id.to_owned(),
                    target_trade_key,
                    PendingTrailingSpec {
                        activation: PendingTrailingActivation::Points {
                            ticks: activation_ticks,
                            price: activation_price,
                        },
                        offset_price_distance,
                    },
                    bar_index,
                    metadata,
                );
            }
            DeferredRelativeExitTrigger::Bracket {
                downside: DeferredBracketLeg::Absolute(downside),
                upside: DeferredBracketLeg::RelativeProfit { ticks, mintick },
            } => {
                if quantity != ExitQuantityRequest::Full {
                    return;
                }
                let Some((target_trade_key, entry_price)) =
                    self.last_open_trade_key_and_price_for_entry(entry_id)
                else {
                    return;
                };
                let Some(price_offset) = self.exit_tick_price_offset(ticks, mintick) else {
                    return;
                };
                self.place_all_entry_resolved_bracket(
                    AllEntryResolvedExitPlacement {
                        id,
                        from_entry: entry_id.to_owned(),
                        target_trade_key,
                        bar_index,
                        metadata,
                    },
                    downside,
                    entry_price + price_offset,
                );
            }
            DeferredRelativeExitTrigger::Bracket {
                downside: DeferredBracketLeg::RelativeLoss { ticks, mintick },
                upside: DeferredBracketLeg::Absolute(upside),
            } => {
                if quantity != ExitQuantityRequest::Full {
                    return;
                }
                let Some((target_trade_key, entry_price)) =
                    self.last_open_trade_key_and_price_for_entry(entry_id)
                else {
                    return;
                };
                let Some(price_offset) = self.exit_tick_price_offset(ticks, mintick) else {
                    return;
                };
                self.place_all_entry_resolved_bracket(
                    AllEntryResolvedExitPlacement {
                        id,
                        from_entry: entry_id.to_owned(),
                        target_trade_key,
                        bar_index,
                        metadata,
                    },
                    entry_price - price_offset,
                    upside,
                );
            }
            DeferredRelativeExitTrigger::Bracket {
                downside:
                    DeferredBracketLeg::RelativeLoss {
                        ticks: loss_ticks,
                        mintick: loss_mintick,
                    },
                upside:
                    DeferredBracketLeg::RelativeProfit {
                        ticks: profit_ticks,
                        mintick: profit_mintick,
                    },
            } => {
                if quantity != ExitQuantityRequest::Full {
                    return;
                }
                let Some((target_trade_key, entry_price)) =
                    self.last_open_trade_key_and_price_for_entry(entry_id)
                else {
                    return;
                };
                self.place_all_entry_resolved_loss_profit_bracket(
                    AllEntryResolvedExitPlacement {
                        id,
                        from_entry: entry_id.to_owned(),
                        target_trade_key,
                        bar_index,
                        metadata,
                    },
                    entry_price,
                    DeferredLossProfitBracketSpec {
                        loss_ticks,
                        loss_mintick,
                        profit_ticks,
                        profit_mintick,
                    },
                );
            }
            _ => {}
        }
    }

    fn place_all_entry_resolved_profit_exit(
        &mut self,
        id: String,
        from_entry: String,
        target_trade_key: u64,
        limit_price: f64,
        bar_index: usize,
        metadata: StrategyExitMetadata,
    ) {
        if !limit_price.is_finite() {
            self.diagnostics.push(RuntimeDiagnostic {
                code: "E_STRATEGY_EXIT_PRICE".to_owned(),
                message: "`strategy.exit` price must be finite".to_owned(),
            });
            return;
        }
        let reserved_quantity = self.trade_ledger.open_quantity_for_key(target_trade_key);
        if !reserved_quantity.is_finite() || reserved_quantity <= 0.0 {
            return;
        }
        self.order_book.exits_mut().replace_or_append(PendingExit {
            id,
            from_entry,
            target_trade_key: Some(target_trade_key),
            trigger: PendingExitTrigger::Limit(limit_price),
            quantity: PendingExitQuantity::Full,
            reserved_quantity,
            multiple_reservation: false,
            last_update_bar_index: bar_index,
            metadata,
        });
    }

    fn place_all_entry_resolved_loss_exit(
        &mut self,
        id: String,
        from_entry: String,
        target_trade_key: u64,
        stop_price: f64,
        bar_index: usize,
        metadata: StrategyExitMetadata,
    ) {
        if !stop_price.is_finite() {
            self.diagnostics.push(RuntimeDiagnostic {
                code: "E_STRATEGY_EXIT_PRICE".to_owned(),
                message: "`strategy.exit` price must be finite".to_owned(),
            });
            return;
        }
        let reserved_quantity = self.trade_ledger.open_quantity_for_key(target_trade_key);
        if !reserved_quantity.is_finite() || reserved_quantity <= 0.0 {
            return;
        }
        self.order_book.exits_mut().replace_or_append(PendingExit {
            id,
            from_entry,
            target_trade_key: Some(target_trade_key),
            trigger: PendingExitTrigger::Stop(stop_price),
            quantity: PendingExitQuantity::Full,
            reserved_quantity,
            multiple_reservation: false,
            last_update_bar_index: bar_index,
            metadata,
        });
    }

    fn place_all_entry_resolved_trail_points_exit(
        &mut self,
        id: String,
        from_entry: String,
        target_trade_key: u64,
        spec: PendingTrailingSpec,
        bar_index: usize,
        metadata: StrategyExitMetadata,
    ) {
        if !spec.activation.price().is_finite() || !spec.offset_price_distance.is_finite() {
            self.diagnostics.push(RuntimeDiagnostic {
                code: "E_STRATEGY_EXIT_PRICE".to_owned(),
                message: "`strategy.exit` price must be finite".to_owned(),
            });
            return;
        }
        let reserved_quantity = self.trade_ledger.open_quantity_for_key(target_trade_key);
        if !reserved_quantity.is_finite() || reserved_quantity <= 0.0 {
            return;
        }
        self.order_book.exits_mut().replace_or_append(PendingExit {
            id,
            from_entry,
            target_trade_key: Some(target_trade_key),
            trigger: PendingExitTrigger::Trailing(PendingTrailingExit {
                spec,
                state: PendingTrailingState::Inactive,
            }),
            quantity: PendingExitQuantity::Full,
            reserved_quantity,
            multiple_reservation: false,
            last_update_bar_index: bar_index,
            metadata,
        });
    }

    fn place_all_entry_resolved_loss_profit_bracket(
        &mut self,
        placement: AllEntryResolvedExitPlacement,
        entry_price: f64,
        spec: DeferredLossProfitBracketSpec,
    ) {
        let Some(loss_offset) = self.exit_tick_price_offset(spec.loss_ticks, spec.loss_mintick)
        else {
            return;
        };
        let Some(profit_offset) =
            self.exit_tick_price_offset(spec.profit_ticks, spec.profit_mintick)
        else {
            return;
        };
        self.place_all_entry_resolved_bracket(
            placement,
            entry_price - loss_offset,
            entry_price + profit_offset,
        );
    }

    fn place_all_entry_resolved_bracket(
        &mut self,
        placement: AllEntryResolvedExitPlacement,
        downside: f64,
        upside: f64,
    ) {
        if !downside.is_finite() || !upside.is_finite() {
            self.diagnostics.push(RuntimeDiagnostic {
                code: "E_STRATEGY_EXIT_PRICE".to_owned(),
                message: "`strategy.exit` price must be finite".to_owned(),
            });
            return;
        }
        let reserved_quantity = self
            .trade_ledger
            .open_quantity_for_key(placement.target_trade_key);
        if !reserved_quantity.is_finite() || reserved_quantity <= 0.0 {
            return;
        }
        self.order_book.exits_mut().replace_or_append(PendingExit {
            id: placement.id,
            from_entry: placement.from_entry,
            target_trade_key: Some(placement.target_trade_key),
            trigger: PendingExitTrigger::Bracket { downside, upside },
            quantity: PendingExitQuantity::Full,
            reserved_quantity,
            multiple_reservation: false,
            last_update_bar_index: placement.bar_index,
            metadata: placement.metadata,
        });
    }
}
