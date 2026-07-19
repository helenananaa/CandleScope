use super::{
    BrokerState,
    exits::PendingTrailingPlacement,
    loss_profit_brackets::DeferredLossProfitBracketSpec,
    pending_exits::{
        DeferredBracketLeg, DeferredRelativeExit, DeferredRelativeExitTrigger, PendingExitTrigger,
        PendingTrailingActivation,
    },
};

impl BrokerState {
    pub(crate) fn resolve_deferred_relative_exits_for_entry(
        &mut self,
        entry_id: &str,
        bar_index: usize,
    ) {
        let deferred_exits = self
            .order_book
            .exits_mut()
            .take_deferred_relative_for_entry(entry_id);
        for deferred_exit in deferred_exits {
            let DeferredRelativeExit {
                id,
                from_entry,
                trigger,
                quantity,
                last_update_bar_index,
                metadata,
            } = deferred_exit;
            match trigger {
                DeferredRelativeExitTrigger::ProfitTicks { ticks, mintick } => {
                    let Some(limit_price) =
                        self.exit_profit_price_from_ticks_for_entry(&from_entry, ticks, mintick)
                    else {
                        continue;
                    };
                    self.place_exit(
                        id,
                        from_entry,
                        PendingExitTrigger::Limit(limit_price),
                        quantity,
                        last_update_bar_index,
                        metadata,
                    );
                }
                DeferredRelativeExitTrigger::LossTicks { ticks, mintick } => {
                    let Some(stop_price) =
                        self.exit_loss_price_from_ticks_for_entry(&from_entry, ticks, mintick)
                    else {
                        continue;
                    };
                    self.place_exit(
                        id,
                        from_entry,
                        PendingExitTrigger::Stop(stop_price),
                        quantity,
                        last_update_bar_index,
                        metadata,
                    );
                }
                DeferredRelativeExitTrigger::TrailPoints {
                    activation_ticks,
                    offset_ticks,
                    mintick,
                } => {
                    let Some(activation_price) = self.exit_trail_points_activation_price_for_entry(
                        &from_entry,
                        activation_ticks,
                        mintick,
                    ) else {
                        continue;
                    };
                    let Some(offset_price_distance) =
                        self.exit_tick_price_offset(offset_ticks, mintick)
                    else {
                        continue;
                    };
                    self.place_exit_trailing(PendingTrailingPlacement {
                        id,
                        from_entry,
                        activation: PendingTrailingActivation::Points {
                            ticks: activation_ticks,
                            price: activation_price,
                        },
                        offset_price_distance,
                        quantity,
                        bar_index: last_update_bar_index,
                        metadata,
                    });
                }
                DeferredRelativeExitTrigger::Bracket {
                    downside: DeferredBracketLeg::Absolute(downside),
                    upside: DeferredBracketLeg::RelativeProfit { ticks, mintick },
                } => {
                    let Some(upside) =
                        self.exit_profit_price_from_ticks_for_entry(&from_entry, ticks, mintick)
                    else {
                        continue;
                    };
                    self.place_exit(
                        id,
                        from_entry,
                        PendingExitTrigger::Bracket { downside, upside },
                        quantity,
                        last_update_bar_index,
                        metadata,
                    );
                }
                DeferredRelativeExitTrigger::Bracket {
                    downside: DeferredBracketLeg::RelativeLoss { ticks, mintick },
                    upside: DeferredBracketLeg::Absolute(upside),
                } => {
                    let Some(downside) =
                        self.exit_loss_price_from_ticks_for_entry(&from_entry, ticks, mintick)
                    else {
                        continue;
                    };
                    self.place_exit(
                        id,
                        from_entry,
                        PendingExitTrigger::Bracket { downside, upside },
                        quantity,
                        last_update_bar_index,
                        metadata,
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
                    self.place_resolved_loss_profit_bracket(
                        id,
                        from_entry,
                        DeferredLossProfitBracketSpec {
                            loss_ticks,
                            loss_mintick,
                            profit_ticks,
                            profit_mintick,
                        },
                        quantity,
                        last_update_bar_index,
                        metadata,
                    );
                }
                DeferredRelativeExitTrigger::Bracket { .. } => continue,
            }
        }

        let all_entry_deferred_exits = self.order_book.exits().all_entry_deferred_relative_exits();
        for deferred_exit in all_entry_deferred_exits {
            self.resolve_all_entry_deferred_relative_exit_for_entry(
                deferred_exit,
                entry_id,
                bar_index,
            );
        }
    }
}
