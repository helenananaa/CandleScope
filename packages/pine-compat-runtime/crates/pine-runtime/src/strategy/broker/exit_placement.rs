use super::{
    BrokerState, StrategyExitMetadata,
    pending_exits::{
        ExitQuantityRequest, PendingExit, PendingExitQuantity, PendingExitReservationFamily,
        PendingExitTrigger,
    },
};
use crate::RuntimeDiagnostic;

impl BrokerState {
    pub(crate) fn exit_profit_price_from_ticks(&mut self, ticks: f64, mintick: f64) -> Option<f64> {
        self.exit_tick_price_offset(ticks, mintick)
            .map(|price_offset| self.avg_price + price_offset)
    }

    pub(crate) fn exit_loss_price_from_ticks(&mut self, ticks: f64, mintick: f64) -> Option<f64> {
        self.exit_tick_price_offset(ticks, mintick)
            .map(|price_offset| self.avg_price - price_offset)
    }

    pub(crate) fn exit_profit_price_from_ticks_for_entry(
        &mut self,
        from_entry: &str,
        ticks: f64,
        mintick: f64,
    ) -> Option<f64> {
        let base_price = self
            .first_open_entry_price_for_entry(from_entry)
            .unwrap_or(self.avg_price);
        self.exit_tick_price_offset(ticks, mintick)
            .map(|price_offset| base_price + price_offset)
    }

    pub(crate) fn exit_loss_price_from_ticks_for_entry(
        &mut self,
        from_entry: &str,
        ticks: f64,
        mintick: f64,
    ) -> Option<f64> {
        let base_price = self
            .first_open_entry_price_for_entry(from_entry)
            .unwrap_or(self.avg_price);
        self.exit_tick_price_offset(ticks, mintick)
            .map(|price_offset| base_price - price_offset)
    }

    pub(super) fn exit_trail_points_activation_price_for_entry(
        &mut self,
        from_entry: &str,
        ticks: f64,
        mintick: f64,
    ) -> Option<f64> {
        let base_price = self
            .first_open_entry_price_for_entry(from_entry)
            .unwrap_or(self.avg_price);
        self.exit_tick_price_offset(ticks, mintick)
            .map(|price_offset| base_price + price_offset)
    }

    pub(super) fn exit_tick_price_offset(&mut self, ticks: f64, mintick: f64) -> Option<f64> {
        if !ticks.is_finite() || ticks <= 0.0 {
            self.diagnostics.push(RuntimeDiagnostic {
                code: "E_STRATEGY_EXIT_TICKS".to_owned(),
                message: "`strategy.exit` tick distance must be finite and positive".to_owned(),
            });
            return None;
        }
        if !mintick.is_finite() || mintick <= 0.0 {
            self.diagnostics.push(RuntimeDiagnostic {
                code: "E_STRATEGY_EXIT_MINTICK".to_owned(),
                message: "`strategy.exit` mintick must be finite and positive".to_owned(),
            });
            return None;
        }
        Some(ticks * mintick)
    }

    pub(super) fn place_exit(
        &mut self,
        id: String,
        from_entry: String,
        trigger: PendingExitTrigger,
        quantity: ExitQuantityRequest,
        bar_index: usize,
        metadata: StrategyExitMetadata,
    ) {
        if !trigger.prices_are_finite() {
            self.diagnostics.push(RuntimeDiagnostic {
                code: "E_STRATEGY_EXIT_PRICE".to_owned(),
                message: "`strategy.exit` price must be finite".to_owned(),
            });
            return;
        }
        if quantity.has_invalid_fixed_quantity() {
            self.diagnostics.push(RuntimeDiagnostic {
                code: "E_STRATEGY_EXIT_QTY".to_owned(),
                message: "`strategy.exit` quantity must be finite and positive".to_owned(),
            });
            return;
        }
        let open_entry_position_size = self.open_position_size_for_entry(&from_entry);
        let target_position_size = if self.position_size > 0.0 && open_entry_position_size > 0.0 {
            open_entry_position_size
        } else if let Some(pending_entry_quantity) =
            self.order_book.entries().quantity_for_id(&from_entry)
        {
            pending_entry_quantity
        } else {
            return;
        };

        let multiple_reservation_family = match (quantity, trigger.reservation_family()) {
            (
                ExitQuantityRequest::Fixed(_) | ExitQuantityRequest::Percent(_),
                PendingExitReservationFamily::SingleTrigger,
            ) => Some(PendingExitReservationFamily::SingleTrigger),
            (
                ExitQuantityRequest::Fixed(_) | ExitQuantityRequest::Percent(_),
                PendingExitReservationFamily::Bracket,
            ) => Some(PendingExitReservationFamily::Bracket),
            (
                ExitQuantityRequest::Fixed(_) | ExitQuantityRequest::Percent(_),
                PendingExitReservationFamily::Trailing,
            ) => Some(PendingExitReservationFamily::Trailing),
            _ => None,
        };
        let released_identity =
            multiple_reservation_family.map(|_| (id.as_str(), from_entry.as_str()));
        let other_exits_are_supported_reservations = multiple_reservation_family.is_some()
            && self
                .order_book
                .exits()
                .other_exits_are_supported_reservations(&from_entry, released_identity);
        let available_quantity = if other_exits_are_supported_reservations {
            self.order_book.exits_mut().available_unreserved_quantity(
                target_position_size,
                &from_entry,
                released_identity,
            )
        } else {
            target_position_size
        };

        let Some((quantity, reserved_quantity)) = self.resolve_exit_quantity_request_for_available(
            quantity,
            target_position_size,
            available_quantity,
        ) else {
            return;
        };
        if self
            .order_book
            .exits()
            .find_by_identity(&id, &from_entry)
            .is_some_and(|pending_exit| {
                pending_exit.id == id
                    && pending_exit.from_entry == from_entry
                    && pending_exit.trigger.placement_equivalent(&trigger)
                    && pending_exit.quantity == quantity
                    && pending_exit.reserved_quantity == reserved_quantity
                    && pending_exit.metadata == metadata
            })
        {
            return;
        }

        let pending_exit = PendingExit {
            id,
            from_entry,
            target_trade_key: None,
            trigger,
            quantity,
            reserved_quantity,
            multiple_reservation: multiple_reservation_family.is_some(),
            last_update_bar_index: bar_index,
            metadata,
        };
        if multiple_reservation_family.is_some() && other_exits_are_supported_reservations {
            self.order_book.exits_mut().replace_or_append(pending_exit);
        } else {
            if pending_exit.from_entry.is_empty()
                && pending_exit.quantity == PendingExitQuantity::Full
            {
                self.order_book
                    .exits_mut()
                    .clear_all_entry_deferred_relative();
            }
            self.order_book.exits_mut().replace_all(pending_exit);
        }
    }

    pub(super) fn resolve_exit_quantity_request_for_available(
        &mut self,
        quantity: ExitQuantityRequest,
        target_quantity: f64,
        available_quantity: f64,
    ) -> Option<(PendingExitQuantity, f64)> {
        if !target_quantity.is_finite() || target_quantity <= 0.0 {
            self.diagnostics.push(RuntimeDiagnostic {
                code: "E_STRATEGY_EXIT_QTY".to_owned(),
                message: "`strategy.exit` target quantity must be positive".to_owned(),
            });
            return None;
        }
        if !available_quantity.is_finite() || available_quantity <= 0.0 {
            self.diagnostics.push(RuntimeDiagnostic {
                code: "E_STRATEGY_EXIT_QTY".to_owned(),
                message: "`strategy.exit` reserved quantity must be positive".to_owned(),
            });
            return None;
        }

        match quantity {
            ExitQuantityRequest::Full => Some((PendingExitQuantity::Full, available_quantity)),
            ExitQuantityRequest::Fixed(qty) => {
                if !PendingExitQuantity::Fixed(qty).is_valid() {
                    self.diagnostics.push(RuntimeDiagnostic {
                        code: "E_STRATEGY_EXIT_QTY".to_owned(),
                        message: "`strategy.exit` quantity must be finite and positive".to_owned(),
                    });
                    return None;
                }
                Some((PendingExitQuantity::Fixed(qty), qty.min(available_quantity)))
            }
            ExitQuantityRequest::Percent(qty_percent) => {
                if !qty_percent.is_finite() || qty_percent <= 0.0 {
                    self.diagnostics.push(RuntimeDiagnostic {
                        code: "E_STRATEGY_EXIT_QTY_PERCENT".to_owned(),
                        message: "`strategy.exit` qty_percent must be finite and positive"
                            .to_owned(),
                    });
                    return None;
                }
                let requested_quantity = target_quantity * qty_percent / 100.0;
                Some((
                    PendingExitQuantity::Fixed(requested_quantity),
                    requested_quantity.min(available_quantity),
                ))
            }
        }
    }
}
