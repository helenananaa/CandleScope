use super::StrategyOrderMetadata;
use crate::RuntimeDiagnostic;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum PendingEntryDirection {
    Long,
    Short,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub(super) enum PendingEntryKind {
    Market,
    Limit {
        price: f64,
    },
    Stop {
        price: f64,
    },
    StopLimit {
        stop_price: f64,
        limit_price: f64,
        activated_bar_index: Option<usize>,
    },
}

#[derive(Debug, Clone, PartialEq)]
pub(super) struct PendingEntry {
    pub(super) id: String,
    pub(super) direction: PendingEntryDirection,
    pub(super) kind: PendingEntryKind,
    pub(super) quantity: f64,
    pub(super) created_bar_index: usize,
    pub(super) metadata: StrategyOrderMetadata,
    pub(super) enforce_pyramiding: bool,
}

pub(super) struct StopLimitEntryPlacement {
    pub(super) id: String,
    pub(super) quantity: f64,
    pub(super) stop_price: f64,
    pub(super) limit_price: f64,
    pub(super) created_bar_index: usize,
    pub(super) metadata: StrategyOrderMetadata,
}

struct LongEntryPlacement {
    id: String,
    direction: PendingEntryDirection,
    kind: PendingEntryKind,
    quantity: f64,
    created_bar_index: usize,
    metadata: StrategyOrderMetadata,
    enforce_pyramiding: bool,
}

#[derive(Debug, Clone, Default, PartialEq)]
pub(super) struct PendingEntryBook {
    entries: Vec<PendingEntry>,
}

impl PendingEntryBook {
    pub(super) fn new() -> Self {
        Self::default()
    }

    #[allow(dead_code)]
    pub(super) fn count(&self) -> usize {
        self.entries.len()
    }

    #[allow(dead_code)]
    pub(super) fn current(&self) -> Option<&PendingEntry> {
        self.entries.first()
    }

    #[allow(dead_code)]
    pub(super) fn iter(&self) -> impl Iterator<Item = &PendingEntry> {
        self.entries.iter()
    }

    #[allow(dead_code)]
    pub(super) fn find_by_id(&self, id: &str) -> Option<&PendingEntry> {
        self.entries
            .iter()
            .find(|pending_entry| pending_entry.id == id)
    }

    pub(super) fn quantity_for_id(&self, id: &str) -> Option<f64> {
        self.find_by_id(id)
            .map(|pending_entry| pending_entry.quantity)
    }

    pub(super) fn has_limit_long_bypassing_pyramiding(&self) -> bool {
        self.entries.iter().any(|pending_entry| {
            pending_entry.direction == PendingEntryDirection::Long
                && matches!(pending_entry.kind, PendingEntryKind::Limit { .. })
                && !pending_entry.enforce_pyramiding
        })
    }

    pub(super) fn has_stop_long_bypassing_pyramiding(&self) -> bool {
        self.entries.iter().any(|pending_entry| {
            pending_entry.direction == PendingEntryDirection::Long
                && matches!(pending_entry.kind, PendingEntryKind::Stop { .. })
                && !pending_entry.enforce_pyramiding
        })
    }

    pub(super) fn has_stop_limit_long_bypassing_pyramiding(&self) -> bool {
        self.entries.iter().any(|pending_entry| {
            pending_entry.direction == PendingEntryDirection::Long
                && matches!(pending_entry.kind, PendingEntryKind::StopLimit { .. })
                && !pending_entry.enforce_pyramiding
        })
    }

    pub(super) fn has_price_based_long_bypassing_pyramiding(&self) -> bool {
        self.entries.iter().any(|pending_entry| {
            pending_entry.direction == PendingEntryDirection::Long
                && matches!(
                    pending_entry.kind,
                    PendingEntryKind::Limit { .. }
                        | PendingEntryKind::Stop { .. }
                        | PendingEntryKind::StopLimit { .. }
                )
                && !pending_entry.enforce_pyramiding
        })
    }

    pub(super) fn cancel_id(&mut self, id: &str) {
        self.entries.retain(|pending_entry| pending_entry.id != id);
    }

    #[allow(dead_code)]
    pub(super) fn take_first_eligible_market_long(
        &mut self,
        bar_index: usize,
    ) -> Option<PendingEntry> {
        let position = self.entries.iter().position(|pending_entry| {
            matches!(
                pending_entry.direction,
                PendingEntryDirection::Long | PendingEntryDirection::Short
            ) && pending_entry.kind == PendingEntryKind::Market
                && pending_entry.created_bar_index < bar_index
        })?;
        Some(self.entries.remove(position))
    }

    #[allow(dead_code)]
    pub(super) fn take_first_eligible_limit_long(
        &mut self,
        bar_index: usize,
        low: f64,
        verification_offset: f64,
    ) -> Option<PendingEntry> {
        let position = self.entries.iter().position(|pending_entry| {
            pending_entry.direction == PendingEntryDirection::Long
                && matches!(pending_entry.kind, PendingEntryKind::Limit { price } if low <= price - verification_offset)
                && pending_entry.created_bar_index < bar_index
        })?;
        Some(self.entries.remove(position))
    }

    pub(super) fn take_all_eligible_limit_long(
        &mut self,
        bar_index: usize,
        low: f64,
        verification_offset: f64,
    ) -> Vec<PendingEntry> {
        let mut eligible = Vec::new();
        let mut index = 0;
        while index < self.entries.len() {
            let pending_entry = &self.entries[index];
            let is_eligible = pending_entry.direction == PendingEntryDirection::Long
                && matches!(pending_entry.kind, PendingEntryKind::Limit { price } if low <= price - verification_offset)
                && pending_entry.created_bar_index < bar_index;
            if is_eligible {
                eligible.push(self.entries.remove(index));
            } else {
                index += 1;
            }
        }
        eligible
    }

    #[allow(dead_code)]
    pub(super) fn take_first_eligible_stop_long(
        &mut self,
        bar_index: usize,
        high: f64,
    ) -> Option<PendingEntry> {
        let position = self.entries.iter().position(|pending_entry| {
            pending_entry.direction == PendingEntryDirection::Long
                && matches!(pending_entry.kind, PendingEntryKind::Stop { price } if high >= price)
                && pending_entry.created_bar_index < bar_index
        })?;
        Some(self.entries.remove(position))
    }

    pub(super) fn take_all_eligible_stop_long(
        &mut self,
        bar_index: usize,
        high: f64,
    ) -> Vec<PendingEntry> {
        let mut eligible = Vec::new();
        let mut index = 0;
        while index < self.entries.len() {
            let pending_entry = &self.entries[index];
            let is_eligible = pending_entry.direction == PendingEntryDirection::Long
                && matches!(pending_entry.kind, PendingEntryKind::Stop { price } if high >= price)
                && pending_entry.created_bar_index < bar_index;
            if is_eligible {
                eligible.push(self.entries.remove(index));
            } else {
                index += 1;
            }
        }
        eligible
    }

    pub(super) fn activate_stop_limit_long_entries(&mut self, bar_index: usize, high: f64) {
        for pending_entry in &mut self.entries {
            if pending_entry.direction != PendingEntryDirection::Long
                || pending_entry.created_bar_index >= bar_index
            {
                continue;
            }
            let PendingEntryKind::StopLimit {
                stop_price,
                activated_bar_index,
                ..
            } = &mut pending_entry.kind
            else {
                continue;
            };
            if activated_bar_index.is_none() && high >= *stop_price {
                *activated_bar_index = Some(bar_index);
            }
        }
    }

    pub(super) fn take_all_eligible_stop_limit_long(
        &mut self,
        bar_index: usize,
        low: f64,
        verification_offset: f64,
    ) -> Vec<PendingEntry> {
        let mut eligible = Vec::new();
        let mut index = 0;
        while index < self.entries.len() {
            let pending_entry = &self.entries[index];
            let is_eligible = pending_entry.direction == PendingEntryDirection::Long
                && matches!(
                    pending_entry.kind,
                    PendingEntryKind::StopLimit {
                        limit_price,
                        activated_bar_index: Some(activated_bar_index),
                        ..
                    } if activated_bar_index < bar_index && low <= limit_price - verification_offset
                );
            if is_eligible {
                eligible.push(self.entries.remove(index));
            } else {
                index += 1;
            }
        }
        eligible
    }

    #[allow(dead_code)]
    pub(super) fn clear_all(&mut self) {
        self.entries.clear();
    }

    #[allow(dead_code)]
    pub(super) fn place_market_long(
        &mut self,
        id: String,
        quantity: f64,
        created_bar_index: usize,
        diagnostics: &mut Vec<RuntimeDiagnostic>,
    ) {
        self.place_market_long_with_metadata(
            id,
            quantity,
            created_bar_index,
            StrategyOrderMetadata::default(),
            diagnostics,
        );
    }

    pub(super) fn place_market_long_with_metadata(
        &mut self,
        id: String,
        quantity: f64,
        created_bar_index: usize,
        metadata: StrategyOrderMetadata,
        diagnostics: &mut Vec<RuntimeDiagnostic>,
    ) {
        self.place_long(
            LongEntryPlacement {
                id,
                direction: PendingEntryDirection::Long,
                kind: PendingEntryKind::Market,
                quantity,
                created_bar_index,
                metadata,
                enforce_pyramiding: true,
            },
            diagnostics,
        );
    }

    pub(super) fn place_market_long_without_pyramiding_with_metadata(
        &mut self,
        id: String,
        quantity: f64,
        created_bar_index: usize,
        metadata: StrategyOrderMetadata,
        diagnostics: &mut Vec<RuntimeDiagnostic>,
    ) {
        self.place_long(
            LongEntryPlacement {
                id,
                direction: PendingEntryDirection::Long,
                kind: PendingEntryKind::Market,
                quantity,
                created_bar_index,
                metadata,
                enforce_pyramiding: false,
            },
            diagnostics,
        );
    }

    pub(super) fn place_market_short_order(
        &mut self,
        id: String,
        quantity: f64,
        created_bar_index: usize,
        metadata: StrategyOrderMetadata,
        diagnostics: &mut Vec<RuntimeDiagnostic>,
    ) {
        self.place_long(
            LongEntryPlacement {
                id,
                direction: PendingEntryDirection::Short,
                kind: PendingEntryKind::Market,
                quantity,
                created_bar_index,
                metadata,
                enforce_pyramiding: false,
            },
            diagnostics,
        );
    }

    pub(super) fn place_limit_long_with_metadata(
        &mut self,
        id: String,
        quantity: f64,
        price: f64,
        created_bar_index: usize,
        metadata: StrategyOrderMetadata,
        diagnostics: &mut Vec<RuntimeDiagnostic>,
    ) {
        if !price.is_finite() || price <= 0.0 {
            diagnostics.push(RuntimeDiagnostic {
                code: "E_STRATEGY_PRICE".to_owned(),
                message: "`strategy.entry` limit price must be positive".to_owned(),
            });
            return;
        }
        self.place_long(
            LongEntryPlacement {
                id,
                direction: PendingEntryDirection::Long,
                kind: PendingEntryKind::Limit { price },
                quantity,
                created_bar_index,
                metadata,
                enforce_pyramiding: true,
            },
            diagnostics,
        );
    }

    pub(super) fn place_limit_long_without_pyramiding_with_metadata(
        &mut self,
        id: String,
        quantity: f64,
        price: f64,
        created_bar_index: usize,
        metadata: StrategyOrderMetadata,
        diagnostics: &mut Vec<RuntimeDiagnostic>,
    ) {
        if !price.is_finite() || price <= 0.0 {
            diagnostics.push(RuntimeDiagnostic {
                code: "E_STRATEGY_PRICE".to_owned(),
                message: "`strategy.order` limit price must be positive".to_owned(),
            });
            return;
        }
        self.place_long(
            LongEntryPlacement {
                id,
                direction: PendingEntryDirection::Long,
                kind: PendingEntryKind::Limit { price },
                quantity,
                created_bar_index,
                metadata,
                enforce_pyramiding: false,
            },
            diagnostics,
        );
    }

    pub(super) fn place_stop_long_with_metadata(
        &mut self,
        id: String,
        quantity: f64,
        price: f64,
        created_bar_index: usize,
        metadata: StrategyOrderMetadata,
        diagnostics: &mut Vec<RuntimeDiagnostic>,
    ) {
        if !price.is_finite() || price <= 0.0 {
            diagnostics.push(RuntimeDiagnostic {
                code: "E_STRATEGY_PRICE".to_owned(),
                message: "`strategy.entry` stop price must be positive".to_owned(),
            });
            return;
        }
        self.place_long(
            LongEntryPlacement {
                id,
                direction: PendingEntryDirection::Long,
                kind: PendingEntryKind::Stop { price },
                quantity,
                created_bar_index,
                metadata,
                enforce_pyramiding: true,
            },
            diagnostics,
        );
    }

    pub(super) fn place_stop_long_without_pyramiding_with_metadata(
        &mut self,
        id: String,
        quantity: f64,
        price: f64,
        created_bar_index: usize,
        metadata: StrategyOrderMetadata,
        diagnostics: &mut Vec<RuntimeDiagnostic>,
    ) {
        if !price.is_finite() || price <= 0.0 {
            diagnostics.push(RuntimeDiagnostic {
                code: "E_STRATEGY_PRICE".to_owned(),
                message: "`strategy.order` stop price must be positive".to_owned(),
            });
            return;
        }
        self.place_long(
            LongEntryPlacement {
                id,
                direction: PendingEntryDirection::Long,
                kind: PendingEntryKind::Stop { price },
                quantity,
                created_bar_index,
                metadata,
                enforce_pyramiding: false,
            },
            diagnostics,
        );
    }

    pub(super) fn place_stop_limit_long_with_metadata(
        &mut self,
        placement: StopLimitEntryPlacement,
        diagnostics: &mut Vec<RuntimeDiagnostic>,
    ) {
        if !placement.stop_price.is_finite()
            || placement.stop_price <= 0.0
            || !placement.limit_price.is_finite()
            || placement.limit_price <= 0.0
        {
            diagnostics.push(RuntimeDiagnostic {
                code: "E_STRATEGY_PRICE".to_owned(),
                message: "`strategy.entry` stop-limit prices must be positive".to_owned(),
            });
            return;
        }
        self.place_long(
            LongEntryPlacement {
                id: placement.id,
                direction: PendingEntryDirection::Long,
                kind: PendingEntryKind::StopLimit {
                    stop_price: placement.stop_price,
                    limit_price: placement.limit_price,
                    activated_bar_index: None,
                },
                quantity: placement.quantity,
                created_bar_index: placement.created_bar_index,
                metadata: placement.metadata,
                enforce_pyramiding: true,
            },
            diagnostics,
        );
    }

    pub(super) fn place_stop_limit_long_without_pyramiding_with_metadata(
        &mut self,
        placement: StopLimitEntryPlacement,
        diagnostics: &mut Vec<RuntimeDiagnostic>,
    ) {
        if !placement.stop_price.is_finite()
            || placement.stop_price <= 0.0
            || !placement.limit_price.is_finite()
            || placement.limit_price <= 0.0
        {
            diagnostics.push(RuntimeDiagnostic {
                code: "E_STRATEGY_PRICE".to_owned(),
                message: "`strategy.order` stop-limit prices must be positive".to_owned(),
            });
            return;
        }
        self.place_long(
            LongEntryPlacement {
                id: placement.id,
                direction: PendingEntryDirection::Long,
                kind: PendingEntryKind::StopLimit {
                    stop_price: placement.stop_price,
                    limit_price: placement.limit_price,
                    activated_bar_index: None,
                },
                quantity: placement.quantity,
                created_bar_index: placement.created_bar_index,
                metadata: placement.metadata,
                enforce_pyramiding: false,
            },
            diagnostics,
        );
    }

    fn place_long(
        &mut self,
        placement: LongEntryPlacement,
        diagnostics: &mut Vec<RuntimeDiagnostic>,
    ) {
        if !placement.quantity.is_finite() || placement.quantity <= 0.0 {
            diagnostics.push(RuntimeDiagnostic {
                code: "E_STRATEGY_QTY".to_owned(),
                message: "`strategy.entry` quantity must be positive".to_owned(),
            });
            return;
        }
        let pending_entry = PendingEntry {
            id: placement.id,
            direction: placement.direction,
            kind: placement.kind,
            quantity: placement.quantity,
            created_bar_index: placement.created_bar_index,
            metadata: placement.metadata,
            enforce_pyramiding: placement.enforce_pyramiding,
        };
        if let Some(existing) = self
            .entries
            .iter_mut()
            .find(|existing| existing.id == pending_entry.id)
        {
            *existing = pending_entry;
        } else {
            self.entries.push(pending_entry);
        }
    }
}
