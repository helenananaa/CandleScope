use super::{
    BrokerState, StrategyExitMetadata,
    pending_exits::{
        ExitQuantityRequest, PendingExitTrigger, PendingTrailingActivation, PendingTrailingExit,
        PendingTrailingSpec, PendingTrailingState,
    },
};

pub(super) struct PendingTrailingPlacement {
    pub(super) id: String,
    pub(super) from_entry: String,
    pub(super) activation: PendingTrailingActivation,
    pub(super) offset_price_distance: f64,
    pub(super) quantity: ExitQuantityRequest,
    pub(super) bar_index: usize,
    pub(super) metadata: StrategyExitMetadata,
}

impl BrokerState {
    pub(super) fn place_exit_trailing(&mut self, placement: PendingTrailingPlacement) {
        self.place_exit(
            placement.id,
            placement.from_entry,
            PendingExitTrigger::Trailing(PendingTrailingExit {
                spec: PendingTrailingSpec {
                    activation: placement.activation,
                    offset_price_distance: placement.offset_price_distance,
                },
                state: PendingTrailingState::Inactive,
            }),
            placement.quantity,
            placement.bar_index,
            placement.metadata,
        );
    }
}
