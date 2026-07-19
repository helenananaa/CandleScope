use super::{
    BrokerState,
    pending_exits::{ExitQuantityRequest, PendingExitTrigger},
};

impl BrokerState {
    pub(crate) fn place_exit_stop(
        &mut self,
        id: String,
        from_entry: String,
        stop_price: f64,
        bar_index: usize,
    ) {
        self.place_exit_stop_quantity(
            id,
            from_entry,
            stop_price,
            ExitQuantityRequest::Full,
            bar_index,
        );
    }

    pub(crate) fn place_exit_stop_qty(
        &mut self,
        id: String,
        from_entry: String,
        stop_price: f64,
        qty: f64,
        bar_index: usize,
    ) {
        self.place_exit_stop_quantity(
            id,
            from_entry,
            stop_price,
            ExitQuantityRequest::Fixed(qty),
            bar_index,
        );
    }

    pub(crate) fn place_exit_stop_qty_percent(
        &mut self,
        id: String,
        from_entry: String,
        stop_price: f64,
        qty_percent: f64,
        bar_index: usize,
    ) {
        self.place_exit_stop_quantity(
            id,
            from_entry,
            stop_price,
            ExitQuantityRequest::Percent(qty_percent),
            bar_index,
        );
    }

    fn place_exit_stop_quantity(
        &mut self,
        id: String,
        from_entry: String,
        stop_price: f64,
        quantity: ExitQuantityRequest,
        bar_index: usize,
    ) {
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

    pub(crate) fn place_exit_limit(
        &mut self,
        id: String,
        from_entry: String,
        limit_price: f64,
        bar_index: usize,
    ) {
        self.place_exit_limit_quantity(
            id,
            from_entry,
            limit_price,
            ExitQuantityRequest::Full,
            bar_index,
        );
    }

    pub(crate) fn place_exit_limit_qty(
        &mut self,
        id: String,
        from_entry: String,
        limit_price: f64,
        qty: f64,
        bar_index: usize,
    ) {
        self.place_exit_limit_quantity(
            id,
            from_entry,
            limit_price,
            ExitQuantityRequest::Fixed(qty),
            bar_index,
        );
    }

    pub(crate) fn place_exit_limit_qty_percent(
        &mut self,
        id: String,
        from_entry: String,
        limit_price: f64,
        qty_percent: f64,
        bar_index: usize,
    ) {
        self.place_exit_limit_quantity(
            id,
            from_entry,
            limit_price,
            ExitQuantityRequest::Percent(qty_percent),
            bar_index,
        );
    }

    fn place_exit_limit_quantity(
        &mut self,
        id: String,
        from_entry: String,
        limit_price: f64,
        quantity: ExitQuantityRequest,
        bar_index: usize,
    ) {
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

    pub(crate) fn place_exit_bracket(
        &mut self,
        id: String,
        from_entry: String,
        downside_price: f64,
        upside_price: f64,
        bar_index: usize,
    ) {
        self.place_exit_bracket_quantity(
            id,
            from_entry,
            downside_price,
            upside_price,
            ExitQuantityRequest::Full,
            bar_index,
        );
    }

    pub(crate) fn place_exit_bracket_qty(
        &mut self,
        id: String,
        from_entry: String,
        downside_price: f64,
        upside_price: f64,
        qty: f64,
        bar_index: usize,
    ) {
        self.place_exit_bracket_quantity(
            id,
            from_entry,
            downside_price,
            upside_price,
            ExitQuantityRequest::Fixed(qty),
            bar_index,
        );
    }

    pub(crate) fn place_exit_bracket_qty_percent(
        &mut self,
        id: String,
        from_entry: String,
        downside_price: f64,
        upside_price: f64,
        qty_percent: f64,
        bar_index: usize,
    ) {
        self.place_exit_bracket_quantity(
            id,
            from_entry,
            downside_price,
            upside_price,
            ExitQuantityRequest::Percent(qty_percent),
            bar_index,
        );
    }

    fn place_exit_bracket_quantity(
        &mut self,
        id: String,
        from_entry: String,
        downside_price: f64,
        upside_price: f64,
        quantity: ExitQuantityRequest,
        bar_index: usize,
    ) {
        let metadata = self.take_next_exit_metadata();
        self.place_exit(
            id,
            from_entry,
            PendingExitTrigger::Bracket {
                downside: downside_price,
                upside: upside_price,
            },
            quantity,
            bar_index,
            metadata,
        );
    }
}
