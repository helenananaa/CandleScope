use super::{
    BrokerState,
    exits::PendingTrailingPlacement,
    pending_exits::{
        DeferredRelativeExit, DeferredRelativeExitTrigger, ExitQuantityRequest, PendingExit,
        PendingExitQuantity, PendingExitTrigger, PendingTrailingActivation, PendingTrailingExit,
        PendingTrailingSpec, PendingTrailingState, TrailPointsExitSpec, TrailPriceExitSpec,
    },
};

impl BrokerState {
    pub(crate) fn place_exit_profit_ticks(
        &mut self,
        id: String,
        from_entry: String,
        ticks: f64,
        mintick: f64,
        bar_index: usize,
    ) {
        self.place_exit_profit_ticks_quantity(
            id,
            from_entry,
            ticks,
            mintick,
            ExitQuantityRequest::Full,
            bar_index,
        );
    }

    pub(crate) fn place_exit_profit_ticks_qty(
        &mut self,
        id: String,
        from_entry: String,
        ticks: f64,
        mintick: f64,
        qty: f64,
        bar_index: usize,
    ) {
        self.place_exit_profit_ticks_quantity(
            id,
            from_entry,
            ticks,
            mintick,
            ExitQuantityRequest::Fixed(qty),
            bar_index,
        );
    }

    pub(crate) fn place_exit_profit_ticks_qty_percent(
        &mut self,
        id: String,
        from_entry: String,
        ticks: f64,
        mintick: f64,
        qty_percent: f64,
        bar_index: usize,
    ) {
        self.place_exit_profit_ticks_quantity(
            id,
            from_entry,
            ticks,
            mintick,
            ExitQuantityRequest::Percent(qty_percent),
            bar_index,
        );
    }

    pub(crate) fn place_all_entry_exit_profit_ticks(
        &mut self,
        id: String,
        ticks: f64,
        mintick: f64,
        bar_index: usize,
    ) {
        let Some(price_offset) = self.exit_tick_price_offset(ticks, mintick) else {
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
                trigger: PendingExitTrigger::Limit(open_trade.entry_price + price_offset),
                quantity: PendingExitQuantity::Full,
                reserved_quantity: open_trade.quantity,
                multiple_reservation: false,
                last_update_bar_index: bar_index,
                metadata: metadata.clone(),
            });
        }
        self.order_book
            .exits_mut()
            .replace_all_entry_deferred_relative(DeferredRelativeExit {
                id,
                from_entry: String::new(),
                trigger: DeferredRelativeExitTrigger::ProfitTicks { ticks, mintick },
                quantity: ExitQuantityRequest::Full,
                last_update_bar_index: bar_index,
                metadata,
            });
        if pending_exits.is_empty() {
            return;
        }
        self.order_book.exits_mut().replace_all_many(pending_exits);
    }

    fn place_exit_profit_ticks_quantity(
        &mut self,
        id: String,
        from_entry: String,
        ticks: f64,
        mintick: f64,
        quantity: ExitQuantityRequest,
        bar_index: usize,
    ) {
        if self.position_size <= 0.0 && self.has_pending_entry(&from_entry) {
            self.place_deferred_relative_profit_exit(
                id, from_entry, ticks, mintick, quantity, bar_index,
            );
            return;
        }
        if self.reject_entry_relative_exit_for_pending_entry(&from_entry) {
            return;
        }
        let Some(limit_price) =
            self.exit_profit_price_from_ticks_for_entry(&from_entry, ticks, mintick)
        else {
            return;
        };
        let metadata = self.take_next_exit_metadata();
        self.place_exit(
            id,
            from_entry,
            PendingExitTrigger::Limit(limit_price),
            quantity,
            bar_index,
            metadata,
        );
    }

    fn place_deferred_relative_profit_exit(
        &mut self,
        id: String,
        from_entry: String,
        ticks: f64,
        mintick: f64,
        quantity: ExitQuantityRequest,
        bar_index: usize,
    ) {
        let Some(pending_entry_quantity) = self.order_book.entries().quantity_for_id(&from_entry)
        else {
            return;
        };
        if self.exit_tick_price_offset(ticks, mintick).is_none() {
            return;
        }
        if self
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
                trigger: DeferredRelativeExitTrigger::ProfitTicks { ticks, mintick },
                quantity,
                last_update_bar_index: bar_index,
                metadata,
            });
    }

    pub(crate) fn place_exit_loss_ticks(
        &mut self,
        id: String,
        from_entry: String,
        ticks: f64,
        mintick: f64,
        bar_index: usize,
    ) {
        self.place_exit_loss_ticks_quantity(
            id,
            from_entry,
            ticks,
            mintick,
            ExitQuantityRequest::Full,
            bar_index,
        );
    }

    pub(crate) fn place_exit_loss_ticks_qty(
        &mut self,
        id: String,
        from_entry: String,
        ticks: f64,
        mintick: f64,
        qty: f64,
        bar_index: usize,
    ) {
        self.place_exit_loss_ticks_quantity(
            id,
            from_entry,
            ticks,
            mintick,
            ExitQuantityRequest::Fixed(qty),
            bar_index,
        );
    }

    pub(crate) fn place_exit_loss_ticks_qty_percent(
        &mut self,
        id: String,
        from_entry: String,
        ticks: f64,
        mintick: f64,
        qty_percent: f64,
        bar_index: usize,
    ) {
        self.place_exit_loss_ticks_quantity(
            id,
            from_entry,
            ticks,
            mintick,
            ExitQuantityRequest::Percent(qty_percent),
            bar_index,
        );
    }

    pub(crate) fn place_all_entry_exit_loss_ticks(
        &mut self,
        id: String,
        ticks: f64,
        mintick: f64,
        bar_index: usize,
    ) {
        let Some(price_offset) = self.exit_tick_price_offset(ticks, mintick) else {
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
                trigger: PendingExitTrigger::Stop(open_trade.entry_price - price_offset),
                quantity: PendingExitQuantity::Full,
                reserved_quantity: open_trade.quantity,
                multiple_reservation: false,
                last_update_bar_index: bar_index,
                metadata: metadata.clone(),
            });
        }
        if pending_exits.is_empty() {
            return;
        }
        self.order_book
            .exits_mut()
            .replace_all_entry_deferred_relative(DeferredRelativeExit {
                id,
                from_entry: String::new(),
                trigger: DeferredRelativeExitTrigger::LossTicks { ticks, mintick },
                quantity: ExitQuantityRequest::Full,
                last_update_bar_index: bar_index,
                metadata,
            });
        self.order_book.exits_mut().replace_all_many(pending_exits);
    }

    fn place_exit_loss_ticks_quantity(
        &mut self,
        id: String,
        from_entry: String,
        ticks: f64,
        mintick: f64,
        quantity: ExitQuantityRequest,
        bar_index: usize,
    ) {
        if self.position_size <= 0.0 && self.has_pending_entry(&from_entry) {
            self.place_deferred_relative_loss_exit(
                id, from_entry, ticks, mintick, quantity, bar_index,
            );
            return;
        }
        if self.reject_entry_relative_exit_for_pending_entry(&from_entry) {
            return;
        }
        let Some(stop_price) =
            self.exit_loss_price_from_ticks_for_entry(&from_entry, ticks, mintick)
        else {
            return;
        };
        let metadata = self.take_next_exit_metadata();
        self.place_exit(
            id,
            from_entry,
            PendingExitTrigger::Stop(stop_price),
            quantity,
            bar_index,
            metadata,
        );
    }

    fn place_deferred_relative_loss_exit(
        &mut self,
        id: String,
        from_entry: String,
        ticks: f64,
        mintick: f64,
        quantity: ExitQuantityRequest,
        bar_index: usize,
    ) {
        let Some(pending_entry_quantity) = self.order_book.entries().quantity_for_id(&from_entry)
        else {
            return;
        };
        if self.exit_tick_price_offset(ticks, mintick).is_none() {
            return;
        }
        if self
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
                trigger: DeferredRelativeExitTrigger::LossTicks { ticks, mintick },
                quantity,
                last_update_bar_index: bar_index,
                metadata,
            });
    }

    pub(crate) fn place_exit_trail_price(
        &mut self,
        id: String,
        from_entry: String,
        activation_price: f64,
        offset_ticks: f64,
        mintick: f64,
        bar_index: usize,
    ) {
        self.place_exit_trail_price_quantity(
            id,
            from_entry,
            TrailPriceExitSpec {
                activation_price,
                offset_ticks,
                mintick,
            },
            ExitQuantityRequest::Full,
            bar_index,
        );
    }

    pub(crate) fn place_exit_trail_price_qty(
        &mut self,
        id: String,
        from_entry: String,
        spec: TrailPriceExitSpec,
        qty: f64,
        bar_index: usize,
    ) {
        self.place_exit_trail_price_quantity(
            id,
            from_entry,
            spec,
            ExitQuantityRequest::Fixed(qty),
            bar_index,
        );
    }

    pub(crate) fn place_exit_trail_price_qty_percent(
        &mut self,
        id: String,
        from_entry: String,
        spec: TrailPriceExitSpec,
        qty_percent: f64,
        bar_index: usize,
    ) {
        self.place_exit_trail_price_quantity(
            id,
            from_entry,
            spec,
            ExitQuantityRequest::Percent(qty_percent),
            bar_index,
        );
    }

    fn place_exit_trail_price_quantity(
        &mut self,
        id: String,
        from_entry: String,
        spec: TrailPriceExitSpec,
        quantity: ExitQuantityRequest,
        bar_index: usize,
    ) {
        let Some(offset_price_distance) =
            self.exit_tick_price_offset(spec.offset_ticks, spec.mintick)
        else {
            return;
        };
        let metadata = self.take_next_exit_metadata();
        self.place_exit_trailing(PendingTrailingPlacement {
            id,
            from_entry,
            activation: PendingTrailingActivation::Price(spec.activation_price),
            offset_price_distance,
            quantity,
            bar_index,
            metadata,
        });
    }

    pub(crate) fn place_exit_trail_points(
        &mut self,
        id: String,
        from_entry: String,
        activation_ticks: f64,
        offset_ticks: f64,
        mintick: f64,
        bar_index: usize,
    ) {
        self.place_exit_trail_points_quantity(
            id,
            from_entry,
            TrailPointsExitSpec {
                activation_ticks,
                offset_ticks,
                mintick,
            },
            ExitQuantityRequest::Full,
            bar_index,
        );
    }

    pub(crate) fn place_all_entry_exit_trail_points(
        &mut self,
        id: String,
        activation_ticks: f64,
        offset_ticks: f64,
        mintick: f64,
        bar_index: usize,
    ) {
        let Some(activation_price_offset) = self.exit_tick_price_offset(activation_ticks, mintick)
        else {
            return;
        };
        let Some(offset_price_distance) = self.exit_tick_price_offset(offset_ticks, mintick) else {
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
                trigger: PendingExitTrigger::Trailing(PendingTrailingExit {
                    spec: PendingTrailingSpec {
                        activation: PendingTrailingActivation::Points {
                            ticks: activation_ticks,
                            price: open_trade.entry_price + activation_price_offset,
                        },
                        offset_price_distance,
                    },
                    state: PendingTrailingState::Inactive,
                }),
                quantity: PendingExitQuantity::Full,
                reserved_quantity: open_trade.quantity,
                multiple_reservation: false,
                last_update_bar_index: bar_index,
                metadata: metadata.clone(),
            });
        }
        if pending_exits.is_empty() {
            return;
        }
        self.order_book
            .exits_mut()
            .replace_all_entry_deferred_relative(DeferredRelativeExit {
                id,
                from_entry: String::new(),
                trigger: DeferredRelativeExitTrigger::TrailPoints {
                    activation_ticks,
                    offset_ticks,
                    mintick,
                },
                quantity: ExitQuantityRequest::Full,
                last_update_bar_index: bar_index,
                metadata,
            });
        self.order_book.exits_mut().replace_all_many(pending_exits);
    }

    pub(crate) fn place_exit_trail_points_qty(
        &mut self,
        id: String,
        from_entry: String,
        spec: TrailPointsExitSpec,
        qty: f64,
        bar_index: usize,
    ) {
        self.place_exit_trail_points_quantity(
            id,
            from_entry,
            spec,
            ExitQuantityRequest::Fixed(qty),
            bar_index,
        );
    }

    pub(crate) fn place_exit_trail_points_qty_percent(
        &mut self,
        id: String,
        from_entry: String,
        spec: TrailPointsExitSpec,
        qty_percent: f64,
        bar_index: usize,
    ) {
        self.place_exit_trail_points_quantity(
            id,
            from_entry,
            spec,
            ExitQuantityRequest::Percent(qty_percent),
            bar_index,
        );
    }

    fn place_exit_trail_points_quantity(
        &mut self,
        id: String,
        from_entry: String,
        spec: TrailPointsExitSpec,
        quantity: ExitQuantityRequest,
        bar_index: usize,
    ) {
        if self.position_size <= 0.0 && self.has_pending_entry(&from_entry) {
            self.place_deferred_relative_trail_points_exit(
                id, from_entry, spec, quantity, bar_index,
            );
            return;
        }
        if self.reject_entry_relative_exit_for_pending_entry(&from_entry) {
            return;
        }
        let Some(activation_price) = self.exit_trail_points_activation_price_for_entry(
            &from_entry,
            spec.activation_ticks,
            spec.mintick,
        ) else {
            return;
        };
        let Some(offset_price_distance) =
            self.exit_tick_price_offset(spec.offset_ticks, spec.mintick)
        else {
            return;
        };
        let metadata = self.take_next_exit_metadata();
        self.place_exit_trailing(PendingTrailingPlacement {
            id,
            from_entry,
            activation: PendingTrailingActivation::Points {
                ticks: spec.activation_ticks,
                price: activation_price,
            },
            offset_price_distance,
            quantity,
            bar_index,
            metadata,
        });
    }

    fn place_deferred_relative_trail_points_exit(
        &mut self,
        id: String,
        from_entry: String,
        spec: TrailPointsExitSpec,
        quantity: ExitQuantityRequest,
        bar_index: usize,
    ) {
        let Some(pending_entry_quantity) = self.order_book.entries().quantity_for_id(&from_entry)
        else {
            return;
        };
        if self
            .exit_tick_price_offset(spec.activation_ticks, spec.mintick)
            .is_none()
        {
            return;
        }
        if self
            .exit_tick_price_offset(spec.offset_ticks, spec.mintick)
            .is_none()
        {
            return;
        }
        if self
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
                trigger: DeferredRelativeExitTrigger::TrailPoints {
                    activation_ticks: spec.activation_ticks,
                    offset_ticks: spec.offset_ticks,
                    mintick: spec.mintick,
                },
                quantity,
                last_update_bar_index: bar_index,
                metadata,
            });
    }
}
