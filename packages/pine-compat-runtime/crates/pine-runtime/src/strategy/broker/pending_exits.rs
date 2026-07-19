use super::StrategyExitMetadata;

#[derive(Debug, Clone, PartialEq)]
pub(super) enum PendingExitTrigger {
    Stop(f64),
    Limit(f64),
    Bracket { downside: f64, upside: f64 },
    Trailing(PendingTrailingExit),
}

#[allow(dead_code)]
#[derive(Debug, Clone, PartialEq)]
pub(super) enum DeferredRelativeExitTrigger {
    ProfitTicks {
        ticks: f64,
        mintick: f64,
    },
    LossTicks {
        ticks: f64,
        mintick: f64,
    },
    TrailPoints {
        activation_ticks: f64,
        offset_ticks: f64,
        mintick: f64,
    },
    Bracket {
        downside: DeferredBracketLeg,
        upside: DeferredBracketLeg,
    },
}

#[allow(dead_code)]
#[derive(Debug, Clone, PartialEq)]
pub(super) enum DeferredBracketLeg {
    Absolute(f64),
    RelativeProfit { ticks: f64, mintick: f64 },
    RelativeLoss { ticks: f64, mintick: f64 },
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub(super) enum PendingExitQuantity {
    Full,
    Fixed(f64),
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub(super) enum ExitQuantityRequest {
    Full,
    Fixed(f64),
    Percent(f64),
}

#[derive(Debug, Clone, Copy)]
pub(crate) struct TrailPriceExitSpec {
    pub(crate) activation_price: f64,
    pub(crate) offset_ticks: f64,
    pub(crate) mintick: f64,
}

#[derive(Debug, Clone, Copy)]
pub(crate) struct TrailPointsExitSpec {
    pub(crate) activation_ticks: f64,
    pub(crate) offset_ticks: f64,
    pub(crate) mintick: f64,
}

#[derive(Debug, Clone, PartialEq)]
pub(super) struct PendingTrailingExit {
    pub(super) spec: PendingTrailingSpec,
    pub(super) state: PendingTrailingState,
}

#[derive(Debug, Clone, PartialEq)]
pub(super) struct PendingTrailingSpec {
    pub(super) activation: PendingTrailingActivation,
    pub(super) offset_price_distance: f64,
}

#[derive(Debug, Clone, PartialEq)]
pub(super) enum PendingTrailingActivation {
    Price(f64),
    Points { ticks: f64, price: f64 },
}

#[allow(dead_code)]
#[derive(Debug, Clone, PartialEq)]
pub(super) enum PendingTrailingState {
    Inactive,
    Active { stop_price: f64 },
}

#[derive(Debug, Clone, PartialEq)]
pub(super) enum PendingTrailingUpdate {
    NoChange,
    Persist(PendingTrailingExit),
    Candidate(PendingExitTouch),
}

impl PendingTrailingActivation {
    pub(super) fn price(&self) -> f64 {
        match self {
            Self::Price(price) | Self::Points { price, .. } => *price,
        }
    }
}

impl PendingTrailingExit {
    pub(super) fn evaluate_update(&self, high: f64, low: f64) -> PendingTrailingUpdate {
        match self.state {
            PendingTrailingState::Inactive => {
                if high >= self.spec.activation.price() {
                    return PendingTrailingUpdate::Persist(Self {
                        spec: self.spec.clone(),
                        state: PendingTrailingState::Active {
                            stop_price: high - self.spec.offset_price_distance,
                        },
                    });
                }
                PendingTrailingUpdate::NoChange
            }
            PendingTrailingState::Active { stop_price } => {
                if low <= stop_price {
                    return PendingTrailingUpdate::Candidate(PendingExitTouch {
                        exit_price: stop_price,
                        side: PendingExitSide::Stop,
                    });
                }

                let next_stop = high - self.spec.offset_price_distance;
                if next_stop > stop_price {
                    PendingTrailingUpdate::Persist(Self {
                        spec: self.spec.clone(),
                        state: PendingTrailingState::Active {
                            stop_price: next_stop,
                        },
                    })
                } else {
                    PendingTrailingUpdate::NoChange
                }
            }
        }
    }
}

impl PendingExitTrigger {
    pub(super) fn prices_are_finite(&self) -> bool {
        match self {
            Self::Stop(price) | Self::Limit(price) => price.is_finite(),
            Self::Bracket { downside, upside } => downside.is_finite() && upside.is_finite(),
            Self::Trailing(trailing) => {
                trailing.spec.activation.price().is_finite()
                    && trailing.spec.offset_price_distance.is_finite()
            }
        }
    }

    pub(super) fn placement_equivalent(&self, other: &Self) -> bool {
        match (self, other) {
            (Self::Trailing(left), Self::Trailing(right)) => left.spec == right.spec,
            _ => self == other,
        }
    }

    pub(super) fn single_trigger_side(&self) -> Option<PendingExitSide> {
        match self {
            Self::Stop(_) => Some(PendingExitSide::Stop),
            Self::Limit(_) => Some(PendingExitSide::Limit),
            Self::Bracket { .. } | Self::Trailing(_) => None,
        }
    }

    pub(super) fn reservation_family(&self) -> PendingExitReservationFamily {
        if self.single_trigger_side().is_some() {
            return PendingExitReservationFamily::SingleTrigger;
        }
        if self.is_trailing_reservation_candidate() {
            return PendingExitReservationFamily::Trailing;
        }
        match self {
            Self::Bracket { .. } => PendingExitReservationFamily::Bracket,
            Self::Stop(_) | Self::Limit(_) | Self::Trailing(_) => {
                unreachable!("single and trailing triggers returned above")
            }
        }
    }

    pub(super) fn is_trailing_reservation_candidate(&self) -> bool {
        matches!(self, Self::Trailing(_))
    }

    pub(super) fn touched_candidate(
        &self,
        high: f64,
        low: f64,
        limit_verification_offset: f64,
    ) -> Option<PendingExitTouch> {
        match self {
            Self::Stop(price) if low <= *price => Some(PendingExitTouch {
                exit_price: *price,
                side: PendingExitSide::Stop,
            }),
            Self::Limit(price) if high >= *price + limit_verification_offset => {
                Some(PendingExitTouch {
                    exit_price: *price,
                    side: PendingExitSide::Limit,
                })
            }
            Self::Bracket { downside, upside } => {
                if low <= *downside {
                    Some(PendingExitTouch {
                        exit_price: *downside,
                        side: PendingExitSide::Stop,
                    })
                } else if high >= *upside + limit_verification_offset {
                    Some(PendingExitTouch {
                        exit_price: *upside,
                        side: PendingExitSide::Limit,
                    })
                } else {
                    None
                }
            }
            Self::Trailing(_) | Self::Stop(_) | Self::Limit(_) => None,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum PendingExitReservationFamily {
    SingleTrigger,
    Bracket,
    Trailing,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum PendingExitSide {
    Stop,
    Limit,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub(super) struct PendingExitTouch {
    pub(super) exit_price: f64,
    pub(super) side: PendingExitSide,
}

impl PendingExitQuantity {
    pub(super) fn is_valid(self) -> bool {
        match self {
            Self::Full => true,
            Self::Fixed(qty) => qty.is_finite() && qty > 0.0,
        }
    }
}

impl ExitQuantityRequest {
    pub(super) fn has_invalid_fixed_quantity(self) -> bool {
        matches!(self, Self::Fixed(qty) if !PendingExitQuantity::Fixed(qty).is_valid())
    }
}

#[derive(Debug, Clone, PartialEq)]
pub(super) struct PendingExit {
    pub(super) id: String,
    pub(super) from_entry: String,
    pub(super) target_trade_key: Option<u64>,
    pub(super) trigger: PendingExitTrigger,
    pub(super) quantity: PendingExitQuantity,
    pub(super) reserved_quantity: f64,
    pub(super) multiple_reservation: bool,
    pub(super) last_update_bar_index: usize,
    pub(super) metadata: StrategyExitMetadata,
}

#[allow(dead_code)]
#[derive(Debug, Clone, PartialEq)]
pub(super) struct DeferredRelativeExit {
    pub(super) id: String,
    pub(super) from_entry: String,
    pub(super) trigger: DeferredRelativeExitTrigger,
    pub(super) quantity: ExitQuantityRequest,
    pub(super) last_update_bar_index: usize,
    pub(super) metadata: StrategyExitMetadata,
}

#[derive(Debug, Clone, Default, PartialEq)]
pub(super) struct PendingExitBook {
    exits: Vec<PendingExit>,
    deferred_relative_exits: Vec<DeferredRelativeExit>,
}

impl PendingExitBook {
    pub(super) fn new() -> Self {
        Self::default()
    }

    pub(super) fn current(&self) -> Option<&PendingExit> {
        self.exits.first()
    }

    #[allow(dead_code)]
    pub(super) fn current_mut(&mut self) -> Option<&mut PendingExit> {
        self.exits.first_mut()
    }

    #[allow(dead_code)]
    pub(super) fn iter(&self) -> impl Iterator<Item = &PendingExit> {
        self.exits.iter()
    }

    #[allow(dead_code)]
    pub(super) fn count(&self) -> usize {
        self.exits.len()
    }

    #[allow(dead_code)]
    pub(super) fn deferred_relative_count(&self) -> usize {
        self.deferred_relative_exits.len()
    }

    #[allow(dead_code)]
    pub(super) fn find_by_identity(&self, id: &str, from_entry: &str) -> Option<&PendingExit> {
        self.exits
            .iter()
            .find(|pending_exit| pending_exit.id == id && pending_exit.from_entry == from_entry)
    }

    #[allow(dead_code)]
    pub(super) fn find_by_identity_and_key(
        &self,
        id: &str,
        from_entry: &str,
        target_trade_key: Option<u64>,
    ) -> Option<&PendingExit> {
        self.exits.iter().find(|pending_exit| {
            pending_exit.id == id
                && pending_exit.from_entry == from_entry
                && pending_exit.target_trade_key == target_trade_key
        })
    }

    #[allow(dead_code)]
    pub(super) fn find_deferred_relative_by_identity(
        &self,
        id: &str,
        from_entry: &str,
    ) -> Option<&DeferredRelativeExit> {
        self.deferred_relative_exits
            .iter()
            .find(|pending_exit| pending_exit.id == id && pending_exit.from_entry == from_entry)
    }

    pub(super) fn all_entry_deferred_relative_exits(&self) -> Vec<DeferredRelativeExit> {
        self.deferred_relative_exits
            .iter()
            .filter(|pending_exit| pending_exit.from_entry.is_empty())
            .cloned()
            .collect()
    }

    pub(super) fn other_exits_are_supported_reservations(
        &self,
        from_entry: &str,
        released_identity: Option<(&str, &str)>,
    ) -> bool {
        self.exits
            .iter()
            .filter(|pending_exit| pending_exit.from_entry == from_entry)
            .filter(|pending_exit| {
                released_identity.is_none_or(|(id, from_entry)| {
                    pending_exit.id != id || pending_exit.from_entry != from_entry
                })
            })
            .all(|pending_exit| {
                pending_exit.multiple_reservation
                    && matches!(
                        pending_exit.trigger.reservation_family(),
                        PendingExitReservationFamily::SingleTrigger
                            | PendingExitReservationFamily::Bracket
                            | PendingExitReservationFamily::Trailing
                    )
            })
    }

    #[allow(dead_code)]
    pub(super) fn total_reserved_for_entry(
        &self,
        entry_id: &str,
        released_identity: Option<(&str, &str)>,
    ) -> f64 {
        self.exits
            .iter()
            .filter(|pending_exit| pending_exit.from_entry == entry_id)
            .filter(|pending_exit| {
                released_identity.is_none_or(|(id, from_entry)| {
                    pending_exit.id != id || pending_exit.from_entry != from_entry
                })
            })
            .map(|pending_exit| pending_exit.reserved_quantity)
            .filter(|reserved_quantity| reserved_quantity.is_finite() && *reserved_quantity > 0.0)
            .sum()
    }

    #[allow(dead_code)]
    pub(super) fn available_unreserved_quantity(
        &self,
        position_size: f64,
        entry_id: &str,
        released_identity: Option<(&str, &str)>,
    ) -> f64 {
        if !position_size.is_finite() || position_size <= 0.0 {
            return 0.0;
        }
        (position_size - self.total_reserved_for_entry(entry_id, released_identity)).max(0.0)
    }

    pub(super) fn replace_all(&mut self, pending_exit: PendingExit) {
        self.exits.clear();
        self.exits.push(pending_exit);
    }

    pub(super) fn replace_all_many(&mut self, pending_exits: Vec<PendingExit>) {
        self.exits = pending_exits;
    }

    pub(super) fn replace_or_append(&mut self, pending_exit: PendingExit) {
        if let Some(existing) = self.exits.iter_mut().find(|existing| {
            existing.id == pending_exit.id
                && existing.from_entry == pending_exit.from_entry
                && existing.target_trade_key == pending_exit.target_trade_key
        }) {
            *existing = pending_exit;
            return;
        }
        self.exits.push(pending_exit);
    }

    #[allow(dead_code)]
    pub(super) fn replace_or_append_deferred_relative(
        &mut self,
        pending_exit: DeferredRelativeExit,
    ) {
        if let Some(existing) = self.deferred_relative_exits.iter_mut().find(|existing| {
            existing.id == pending_exit.id && existing.from_entry == pending_exit.from_entry
        }) {
            *existing = pending_exit;
            return;
        }
        self.deferred_relative_exits.push(pending_exit);
    }

    pub(super) fn replace_all_entry_deferred_relative(
        &mut self,
        pending_exit: DeferredRelativeExit,
    ) {
        self.deferred_relative_exits
            .retain(|existing| !existing.from_entry.is_empty());
        self.deferred_relative_exits.push(pending_exit);
    }

    pub(super) fn clear_all_entry_deferred_relative(&mut self) {
        self.deferred_relative_exits
            .retain(|pending_exit| !pending_exit.from_entry.is_empty());
    }

    pub(super) fn take_deferred_relative_for_entry(
        &mut self,
        entry_id: &str,
    ) -> Vec<DeferredRelativeExit> {
        let mut matching = Vec::new();
        let mut retained = Vec::new();
        for pending_exit in self.deferred_relative_exits.drain(..) {
            if pending_exit.from_entry == entry_id {
                matching.push(pending_exit);
            } else {
                retained.push(pending_exit);
            }
        }
        self.deferred_relative_exits = retained;
        matching
    }

    pub(super) fn remove_identities(&mut self, identities: &[(String, String, Option<u64>)]) {
        self.exits.retain(|pending_exit| {
            !identities.iter().any(|(id, from_entry, target_trade_key)| {
                pending_exit.id == *id
                    && pending_exit.from_entry == *from_entry
                    && pending_exit.target_trade_key == *target_trade_key
            })
        });
    }

    pub(super) fn cancel_id(&mut self, id: &str) {
        self.exits.retain(|pending_exit| pending_exit.id != id);
        self.deferred_relative_exits
            .retain(|pending_exit| pending_exit.id != id);
    }

    pub(super) fn clear_all(&mut self) {
        self.exits.clear();
        self.deferred_relative_exits.clear();
    }

    pub(super) fn clear_for_entry(&mut self, entry_id: &str) {
        self.exits
            .retain(|pending_exit| pending_exit.from_entry != entry_id);
        self.deferred_relative_exits
            .retain(|pending_exit| pending_exit.from_entry != entry_id);
    }
}
