use super::{
    BrokerState,
    pending_entries::{PendingEntryDirection, PendingEntryKind},
    types::{EntryFill, EntryPyramidingMode},
};

impl BrokerState {
    pub(crate) fn fill_pending_market_long_entries(
        &mut self,
        bar_index: usize,
        time: i64,
        fill_price: f64,
    ) {
        let Some(pending_entry) = self
            .order_book
            .entries_mut()
            .take_first_eligible_market_long(bar_index)
        else {
            return;
        };
        if pending_entry.direction == PendingEntryDirection::Short {
            self.reduce_long_with_short_order(
                pending_entry.id,
                bar_index,
                time,
                fill_price,
                pending_entry.quantity,
                pending_entry.metadata,
            );
            self.order_book.entries_mut().clear_all();
            return;
        }

        if pending_entry.enforce_pyramiding && !self.can_open_long_entry() {
            self.order_book.entries_mut().clear_all();
            return;
        }

        let entry_id = pending_entry.id;
        let pyramiding_mode = if pending_entry.enforce_pyramiding {
            EntryPyramidingMode::EnforceLimit
        } else {
            EntryPyramidingMode::BypassLimit
        };
        let filled = self.entry_long_internal(
            EntryFill {
                id: entry_id.clone(),
                bar_index,
                time,
                price: fill_price,
                qty: pending_entry.quantity,
                metadata: pending_entry.metadata,
            },
            pyramiding_mode,
        );
        if filled {
            if pending_entry.enforce_pyramiding {
                self.resolve_deferred_relative_exits_for_entry(&entry_id, bar_index);
                self.expand_persistent_all_entry_exit_for_new_entry(bar_index);
            }
        } else {
            self.order_book.exits_mut().clear_for_entry(&entry_id);
        }
        self.order_book.entries_mut().clear_all();
    }

    pub(crate) fn fill_pending_limit_long_entries(
        &mut self,
        bar_index: usize,
        time: i64,
        low: f64,
    ) {
        if !self.can_open_long_entry()
            && !self
                .order_book
                .entries()
                .has_limit_long_bypassing_pyramiding()
        {
            if self
                .order_book
                .entries()
                .has_price_based_long_bypassing_pyramiding()
            {
                return;
            }
            self.order_book.entries_mut().clear_all();
            return;
        }
        let pending_entries = self.order_book.entries_mut().take_all_eligible_limit_long(
            bar_index,
            low,
            self.limit_verification_price_offset,
        );
        if pending_entries.is_empty() {
            return;
        }

        for pending_entry in pending_entries {
            let PendingEntryKind::Limit { price } = pending_entry.kind else {
                continue;
            };
            let entry_id = pending_entry.id;
            let pyramiding_mode = if pending_entry.enforce_pyramiding {
                EntryPyramidingMode::SameTickPriceException
            } else {
                EntryPyramidingMode::BypassLimit
            };
            let filled = self.entry_long_internal(
                EntryFill {
                    id: entry_id.clone(),
                    bar_index,
                    time,
                    price,
                    qty: pending_entry.quantity,
                    metadata: pending_entry.metadata,
                },
                pyramiding_mode,
            );
            if filled {
                if pending_entry.enforce_pyramiding {
                    self.resolve_deferred_relative_exits_for_entry(&entry_id, bar_index);
                    self.expand_persistent_all_entry_exit_for_new_entry(bar_index);
                }
            } else {
                self.order_book.exits_mut().clear_for_entry(&entry_id);
            }
        }
        self.order_book.entries_mut().clear_all();
    }

    pub(crate) fn fill_pending_stop_long_entries(
        &mut self,
        bar_index: usize,
        time: i64,
        high: f64,
    ) {
        if !self.can_open_long_entry()
            && !self
                .order_book
                .entries()
                .has_stop_long_bypassing_pyramiding()
        {
            if self
                .order_book
                .entries()
                .has_price_based_long_bypassing_pyramiding()
            {
                return;
            }
            self.order_book.entries_mut().clear_all();
            return;
        }
        let pending_entries = self
            .order_book
            .entries_mut()
            .take_all_eligible_stop_long(bar_index, high);
        if pending_entries.is_empty() {
            return;
        }

        for pending_entry in pending_entries {
            let PendingEntryKind::Stop { price } = pending_entry.kind else {
                continue;
            };
            let entry_id = pending_entry.id;
            let pyramiding_mode = if pending_entry.enforce_pyramiding {
                EntryPyramidingMode::SameTickPriceException
            } else {
                EntryPyramidingMode::BypassLimit
            };
            let filled = self.entry_long_internal(
                EntryFill {
                    id: entry_id.clone(),
                    bar_index,
                    time,
                    price,
                    qty: pending_entry.quantity,
                    metadata: pending_entry.metadata,
                },
                pyramiding_mode,
            );
            if filled {
                if pending_entry.enforce_pyramiding {
                    self.resolve_deferred_relative_exits_for_entry(&entry_id, bar_index);
                    self.expand_persistent_all_entry_exit_for_new_entry(bar_index);
                }
            } else {
                self.order_book.exits_mut().clear_for_entry(&entry_id);
            }
        }
        self.order_book.entries_mut().clear_all();
    }

    pub(crate) fn fill_pending_stop_limit_long_entries(
        &mut self,
        bar_index: usize,
        time: i64,
        high: f64,
        low: f64,
    ) {
        if !self.can_open_long_entry()
            && !self
                .order_book
                .entries()
                .has_stop_limit_long_bypassing_pyramiding()
        {
            if self
                .order_book
                .entries()
                .has_price_based_long_bypassing_pyramiding()
            {
                return;
            }
            self.order_book.entries_mut().clear_all();
            return;
        }
        self.order_book
            .entries_mut()
            .activate_stop_limit_long_entries(bar_index, high);
        let pending_entries = self
            .order_book
            .entries_mut()
            .take_all_eligible_stop_limit_long(
                bar_index,
                low,
                self.limit_verification_price_offset,
            );
        if pending_entries.is_empty() {
            return;
        }

        for pending_entry in pending_entries {
            let PendingEntryKind::StopLimit { limit_price, .. } = pending_entry.kind else {
                continue;
            };
            let entry_id = pending_entry.id;
            let pyramiding_mode = if pending_entry.enforce_pyramiding {
                EntryPyramidingMode::SameTickPriceException
            } else {
                EntryPyramidingMode::BypassLimit
            };
            let filled = self.entry_long_internal(
                EntryFill {
                    id: entry_id.clone(),
                    bar_index,
                    time,
                    price: limit_price,
                    qty: pending_entry.quantity,
                    metadata: pending_entry.metadata,
                },
                pyramiding_mode,
            );
            if filled {
                if pending_entry.enforce_pyramiding {
                    self.resolve_deferred_relative_exits_for_entry(&entry_id, bar_index);
                    self.expand_persistent_all_entry_exit_for_new_entry(bar_index);
                }
            } else {
                self.order_book.exits_mut().clear_for_entry(&entry_id);
            }
        }
        self.order_book.entries_mut().clear_all();
    }
}
