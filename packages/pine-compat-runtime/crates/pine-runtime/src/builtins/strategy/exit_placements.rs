use crate::HistoricalRuntime;
use crate::strategy::{
    LossLimitBracketSpec, LossProfitBracketSpec, StopProfitBracketSpec, StrategyExitMetadata,
    TrailPointsExitSpec, TrailPriceExitSpec,
};

use super::{RuntimeExitBracketPlacement, RuntimeExitTicksPlacement, StrategyExitQuantityArg};

impl<'a> HistoricalRuntime<'a> {
    pub(super) fn place_exit_stop_quantity(
        &mut self,
        id: String,
        from_entry: String,
        stop_price: f64,
        quantity: StrategyExitQuantityArg,
        bar_index: usize,
        metadata: StrategyExitMetadata,
    ) {
        self.strategy_broker
            .with_next_exit_metadata(metadata, |broker| match quantity {
                StrategyExitQuantityArg::Full => {
                    broker.place_exit_stop(id, from_entry, stop_price, bar_index)
                }
                StrategyExitQuantityArg::Fixed(qty) => {
                    broker.place_exit_stop_qty(id, from_entry, stop_price, qty, bar_index)
                }
                StrategyExitQuantityArg::Percent(qty_percent) => broker
                    .place_exit_stop_qty_percent(
                        id,
                        from_entry,
                        stop_price,
                        qty_percent,
                        bar_index,
                    ),
            });
    }

    pub(super) fn place_exit_limit_quantity(
        &mut self,
        id: String,
        from_entry: String,
        limit_price: f64,
        quantity: StrategyExitQuantityArg,
        bar_index: usize,
        metadata: StrategyExitMetadata,
    ) {
        self.strategy_broker
            .with_next_exit_metadata(metadata, |broker| match quantity {
                StrategyExitQuantityArg::Full => {
                    broker.place_exit_limit(id, from_entry, limit_price, bar_index)
                }
                StrategyExitQuantityArg::Fixed(qty) => {
                    broker.place_exit_limit_qty(id, from_entry, limit_price, qty, bar_index)
                }
                StrategyExitQuantityArg::Percent(qty_percent) => broker
                    .place_exit_limit_qty_percent(
                        id,
                        from_entry,
                        limit_price,
                        qty_percent,
                        bar_index,
                    ),
            });
    }

    pub(super) fn place_exit_profit_ticks_quantity(
        &mut self,
        placement: RuntimeExitTicksPlacement,
    ) {
        self.strategy_broker
            .with_next_exit_metadata(placement.metadata, |broker| match placement.quantity {
                StrategyExitQuantityArg::Full => broker.place_exit_profit_ticks(
                    placement.id,
                    placement.from_entry,
                    placement.ticks,
                    placement.mintick,
                    placement.bar_index,
                ),
                StrategyExitQuantityArg::Fixed(qty) => broker.place_exit_profit_ticks_qty(
                    placement.id,
                    placement.from_entry,
                    placement.ticks,
                    placement.mintick,
                    qty,
                    placement.bar_index,
                ),
                StrategyExitQuantityArg::Percent(qty_percent) => broker
                    .place_exit_profit_ticks_qty_percent(
                        placement.id,
                        placement.from_entry,
                        placement.ticks,
                        placement.mintick,
                        qty_percent,
                        placement.bar_index,
                    ),
            });
    }

    pub(super) fn place_exit_loss_ticks_quantity(&mut self, placement: RuntimeExitTicksPlacement) {
        self.strategy_broker
            .with_next_exit_metadata(placement.metadata, |broker| match placement.quantity {
                StrategyExitQuantityArg::Full => broker.place_exit_loss_ticks(
                    placement.id,
                    placement.from_entry,
                    placement.ticks,
                    placement.mintick,
                    placement.bar_index,
                ),
                StrategyExitQuantityArg::Fixed(qty) => broker.place_exit_loss_ticks_qty(
                    placement.id,
                    placement.from_entry,
                    placement.ticks,
                    placement.mintick,
                    qty,
                    placement.bar_index,
                ),
                StrategyExitQuantityArg::Percent(qty_percent) => broker
                    .place_exit_loss_ticks_qty_percent(
                        placement.id,
                        placement.from_entry,
                        placement.ticks,
                        placement.mintick,
                        qty_percent,
                        placement.bar_index,
                    ),
            });
    }

    pub(super) fn place_exit_bracket_quantity(&mut self, placement: RuntimeExitBracketPlacement) {
        self.strategy_broker
            .with_next_exit_metadata(placement.metadata, |broker| match placement.quantity {
                StrategyExitQuantityArg::Full => broker.place_exit_bracket(
                    placement.id,
                    placement.from_entry,
                    placement.downside_price,
                    placement.upside_price,
                    placement.bar_index,
                ),
                StrategyExitQuantityArg::Fixed(qty) => broker.place_exit_bracket_qty(
                    placement.id,
                    placement.from_entry,
                    placement.downside_price,
                    placement.upside_price,
                    qty,
                    placement.bar_index,
                ),
                StrategyExitQuantityArg::Percent(qty_percent) => broker
                    .place_exit_bracket_qty_percent(
                        placement.id,
                        placement.from_entry,
                        placement.downside_price,
                        placement.upside_price,
                        qty_percent,
                        placement.bar_index,
                    ),
            });
    }

    pub(super) fn place_exit_stop_profit_bracket_quantity(
        &mut self,
        id: String,
        from_entry: String,
        spec: StopProfitBracketSpec,
        quantity: StrategyExitQuantityArg,
        bar_index: usize,
        metadata: StrategyExitMetadata,
    ) {
        self.strategy_broker
            .with_next_exit_metadata(metadata, |broker| match quantity {
                StrategyExitQuantityArg::Full => {
                    broker.place_exit_bracket_stop_profit_ticks(id, from_entry, spec, bar_index)
                }
                StrategyExitQuantityArg::Fixed(qty) => broker
                    .place_exit_bracket_stop_profit_ticks_qty(id, from_entry, spec, qty, bar_index),
                StrategyExitQuantityArg::Percent(qty_percent) => broker
                    .place_exit_bracket_stop_profit_ticks_qty_percent(
                        id,
                        from_entry,
                        spec,
                        qty_percent,
                        bar_index,
                    ),
            });
    }

    pub(super) fn place_exit_loss_limit_bracket_quantity(
        &mut self,
        id: String,
        from_entry: String,
        spec: LossLimitBracketSpec,
        quantity: StrategyExitQuantityArg,
        bar_index: usize,
        metadata: StrategyExitMetadata,
    ) {
        self.strategy_broker
            .with_next_exit_metadata(metadata, |broker| match quantity {
                StrategyExitQuantityArg::Full => {
                    broker.place_exit_bracket_loss_limit_ticks(id, from_entry, spec, bar_index)
                }
                StrategyExitQuantityArg::Fixed(qty) => broker
                    .place_exit_bracket_loss_limit_ticks_qty(id, from_entry, spec, qty, bar_index),
                StrategyExitQuantityArg::Percent(qty_percent) => broker
                    .place_exit_bracket_loss_limit_ticks_qty_percent(
                        id,
                        from_entry,
                        spec,
                        qty_percent,
                        bar_index,
                    ),
            });
    }

    pub(super) fn place_exit_loss_profit_bracket_quantity(
        &mut self,
        id: String,
        from_entry: String,
        spec: LossProfitBracketSpec,
        quantity: StrategyExitQuantityArg,
        bar_index: usize,
        metadata: StrategyExitMetadata,
    ) {
        self.strategy_broker
            .with_next_exit_metadata(metadata, |broker| match quantity {
                StrategyExitQuantityArg::Full => {
                    broker.place_exit_bracket_loss_profit_ticks(id, from_entry, spec, bar_index)
                }
                StrategyExitQuantityArg::Fixed(qty) => broker
                    .place_exit_bracket_loss_profit_ticks_qty(id, from_entry, spec, qty, bar_index),
                StrategyExitQuantityArg::Percent(qty_percent) => broker
                    .place_exit_bracket_loss_profit_ticks_qty_percent(
                        id,
                        from_entry,
                        spec,
                        qty_percent,
                        bar_index,
                    ),
            });
    }

    pub(super) fn place_exit_trail_price_quantity(
        &mut self,
        id: String,
        from_entry: String,
        spec: TrailPriceExitSpec,
        quantity: StrategyExitQuantityArg,
        bar_index: usize,
        metadata: StrategyExitMetadata,
    ) {
        self.strategy_broker
            .with_next_exit_metadata(metadata, |broker| match quantity {
                StrategyExitQuantityArg::Full => broker.place_exit_trail_price(
                    id,
                    from_entry,
                    spec.activation_price,
                    spec.offset_ticks,
                    spec.mintick,
                    bar_index,
                ),
                StrategyExitQuantityArg::Fixed(qty) => {
                    broker.place_exit_trail_price_qty(id, from_entry, spec, qty, bar_index)
                }
                StrategyExitQuantityArg::Percent(qty_percent) => broker
                    .place_exit_trail_price_qty_percent(
                        id,
                        from_entry,
                        spec,
                        qty_percent,
                        bar_index,
                    ),
            });
    }

    pub(super) fn place_exit_trail_points_quantity(
        &mut self,
        id: String,
        from_entry: String,
        spec: TrailPointsExitSpec,
        quantity: StrategyExitQuantityArg,
        bar_index: usize,
        metadata: StrategyExitMetadata,
    ) {
        self.strategy_broker
            .with_next_exit_metadata(metadata, |broker| match quantity {
                StrategyExitQuantityArg::Full => broker.place_exit_trail_points(
                    id,
                    from_entry,
                    spec.activation_ticks,
                    spec.offset_ticks,
                    spec.mintick,
                    bar_index,
                ),
                StrategyExitQuantityArg::Fixed(qty) => {
                    broker.place_exit_trail_points_qty(id, from_entry, spec, qty, bar_index)
                }
                StrategyExitQuantityArg::Percent(qty_percent) => broker
                    .place_exit_trail_points_qty_percent(
                        id,
                        from_entry,
                        spec,
                        qty_percent,
                        bar_index,
                    ),
            });
    }
}
