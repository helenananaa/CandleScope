use crate::signature::{Accepts, BuiltinParam, BuiltinPhase, BuiltinSignature, ReturnSpec};

use super::types::{SERIES_FLOAT, SERIES_INT, SERIES_STRING, VOID};

const STRATEGY_ENTRY_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::SimpleString,
        optional: false,
    },
    BuiltinParam {
        name: "direction",
        accepts: Accepts::StringCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "qty",
        accepts: Accepts::SeriesOrSimpleNumeric,
        optional: true,
    },
    BuiltinParam {
        name: "limit",
        accepts: Accepts::SeriesOrSimpleNumeric,
        optional: true,
    },
    BuiltinParam {
        name: "stop",
        accepts: Accepts::SeriesOrSimpleNumeric,
        optional: true,
    },
    BuiltinParam {
        name: "comment",
        accepts: Accepts::StringCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "alert_message",
        accepts: Accepts::StringCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "disable_alert",
        accepts: Accepts::BoolCompatible,
        optional: true,
    },
];

const STRATEGY_ORDER_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::SimpleString,
        optional: false,
    },
    BuiltinParam {
        name: "direction",
        accepts: Accepts::StringCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "qty",
        accepts: Accepts::SeriesOrSimpleNumeric,
        optional: true,
    },
    BuiltinParam {
        name: "limit",
        accepts: Accepts::SeriesOrSimpleNumeric,
        optional: true,
    },
    BuiltinParam {
        name: "stop",
        accepts: Accepts::SeriesOrSimpleNumeric,
        optional: true,
    },
    BuiltinParam {
        name: "oca_name",
        accepts: Accepts::StringCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "oca_type",
        accepts: Accepts::StringCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "comment",
        accepts: Accepts::StringCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "alert_message",
        accepts: Accepts::StringCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "disable_alert",
        accepts: Accepts::BoolCompatible,
        optional: true,
    },
];

const STRATEGY_CLOSE_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::SimpleString,
        optional: false,
    },
    BuiltinParam {
        name: "qty",
        accepts: Accepts::SeriesOrSimpleNumeric,
        optional: true,
    },
    BuiltinParam {
        name: "qty_percent",
        accepts: Accepts::SeriesOrSimpleNumeric,
        optional: true,
    },
    BuiltinParam {
        name: "comment",
        accepts: Accepts::StringCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "alert_message",
        accepts: Accepts::StringCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "disable_alert",
        accepts: Accepts::BoolCompatible,
        optional: true,
    },
];

const STRATEGY_CLOSE_ALL_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "comment",
        accepts: Accepts::StringCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "alert_message",
        accepts: Accepts::StringCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "disable_alert",
        accepts: Accepts::BoolCompatible,
        optional: true,
    },
];

const STRATEGY_CANCEL_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "id",
    accepts: Accepts::SimpleString,
    optional: false,
}];

const STRATEGY_CANCEL_ALL_PARAMS: &[BuiltinParam] = &[];

const STRATEGY_EXIT_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::SimpleString,
        optional: false,
    },
    BuiltinParam {
        name: "from_entry",
        accepts: Accepts::SimpleString,
        optional: true,
    },
    BuiltinParam {
        name: "stop",
        accepts: Accepts::SeriesOrSimpleNumeric,
        optional: true,
    },
    BuiltinParam {
        name: "limit",
        accepts: Accepts::SeriesOrSimpleNumeric,
        optional: true,
    },
    BuiltinParam {
        name: "profit",
        accepts: Accepts::SeriesOrSimpleNumeric,
        optional: true,
    },
    BuiltinParam {
        name: "loss",
        accepts: Accepts::SeriesOrSimpleNumeric,
        optional: true,
    },
    BuiltinParam {
        name: "trail_price",
        accepts: Accepts::SeriesOrSimpleNumeric,
        optional: true,
    },
    BuiltinParam {
        name: "trail_points",
        accepts: Accepts::SeriesOrSimpleNumeric,
        optional: true,
    },
    BuiltinParam {
        name: "trail_offset",
        accepts: Accepts::SeriesOrSimpleNumeric,
        optional: true,
    },
    BuiltinParam {
        name: "qty",
        accepts: Accepts::SeriesOrSimpleNumeric,
        optional: true,
    },
    BuiltinParam {
        name: "qty_percent",
        accepts: Accepts::SeriesOrSimpleNumeric,
        optional: true,
    },
    BuiltinParam {
        name: "comment",
        accepts: Accepts::StringCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "comment_profit",
        accepts: Accepts::StringCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "comment_loss",
        accepts: Accepts::StringCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "comment_trailing",
        accepts: Accepts::StringCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "alert_message",
        accepts: Accepts::StringCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "alert_profit",
        accepts: Accepts::StringCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "alert_loss",
        accepts: Accepts::StringCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "alert_trailing",
        accepts: Accepts::StringCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "disable_alert",
        accepts: Accepts::BoolCompatible,
        optional: true,
    },
];

const STRATEGY_TRADE_FIELD_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "trade_num",
    accepts: Accepts::SeriesOrSimpleNumeric,
    optional: false,
}];

const STRATEGY_DEFAULT_ENTRY_QTY_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "fill_price",
    accepts: Accepts::SeriesOrSimpleNumeric,
    optional: false,
}];

const STRATEGY_CURRENCY_CONVERSION_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "value",
    accepts: Accepts::SeriesOrSimpleNumeric,
    optional: false,
}];

pub(crate) const SIGNATURES: &[BuiltinSignature] = &[
    BuiltinSignature {
        name: "strategy.convert_to_account",
        phase: BuiltinPhase::Phase1Core,
        params: STRATEGY_CURRENCY_CONVERSION_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_FLOAT),
        variadic: false,
    },
    BuiltinSignature {
        name: "strategy.convert_to_symbol",
        phase: BuiltinPhase::Phase1Core,
        params: STRATEGY_CURRENCY_CONVERSION_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_FLOAT),
        variadic: false,
    },
    BuiltinSignature {
        name: "strategy.default_entry_qty",
        phase: BuiltinPhase::Phase1Core,
        params: STRATEGY_DEFAULT_ENTRY_QTY_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_FLOAT),
        variadic: false,
    },
    BuiltinSignature {
        name: "strategy.entry",
        phase: BuiltinPhase::Phase1Core,
        params: STRATEGY_ENTRY_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "strategy.order",
        phase: BuiltinPhase::Phase1Core,
        params: STRATEGY_ORDER_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "strategy.close",
        phase: BuiltinPhase::Phase1Core,
        params: STRATEGY_CLOSE_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "strategy.close_all",
        phase: BuiltinPhase::Phase1Core,
        params: STRATEGY_CLOSE_ALL_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "strategy.cancel",
        phase: BuiltinPhase::Phase1Core,
        params: STRATEGY_CANCEL_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "strategy.cancel_all",
        phase: BuiltinPhase::Phase1Core,
        params: STRATEGY_CANCEL_ALL_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "strategy.exit",
        phase: BuiltinPhase::Phase1Core,
        params: STRATEGY_EXIT_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "strategy.closedtrades.entry_price",
        phase: BuiltinPhase::Phase1Core,
        params: STRATEGY_TRADE_FIELD_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_FLOAT),
        variadic: false,
    },
    BuiltinSignature {
        name: "strategy.closedtrades.entry_comment",
        phase: BuiltinPhase::Phase1Core,
        params: STRATEGY_TRADE_FIELD_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_STRING),
        variadic: false,
    },
    BuiltinSignature {
        name: "strategy.closedtrades.entry_id",
        phase: BuiltinPhase::Phase1Core,
        params: STRATEGY_TRADE_FIELD_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_STRING),
        variadic: false,
    },
    BuiltinSignature {
        name: "strategy.closedtrades.exit_price",
        phase: BuiltinPhase::Phase1Core,
        params: STRATEGY_TRADE_FIELD_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_FLOAT),
        variadic: false,
    },
    BuiltinSignature {
        name: "strategy.closedtrades.exit_comment",
        phase: BuiltinPhase::Phase1Core,
        params: STRATEGY_TRADE_FIELD_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_STRING),
        variadic: false,
    },
    BuiltinSignature {
        name: "strategy.closedtrades.exit_id",
        phase: BuiltinPhase::Phase1Core,
        params: STRATEGY_TRADE_FIELD_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_STRING),
        variadic: false,
    },
    BuiltinSignature {
        name: "strategy.closedtrades.entry_bar_index",
        phase: BuiltinPhase::Phase1Core,
        params: STRATEGY_TRADE_FIELD_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_INT),
        variadic: false,
    },
    BuiltinSignature {
        name: "strategy.closedtrades.exit_bar_index",
        phase: BuiltinPhase::Phase1Core,
        params: STRATEGY_TRADE_FIELD_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_INT),
        variadic: false,
    },
    BuiltinSignature {
        name: "strategy.closedtrades.entry_time",
        phase: BuiltinPhase::Phase1Core,
        params: STRATEGY_TRADE_FIELD_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_INT),
        variadic: false,
    },
    BuiltinSignature {
        name: "strategy.closedtrades.exit_time",
        phase: BuiltinPhase::Phase1Core,
        params: STRATEGY_TRADE_FIELD_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_INT),
        variadic: false,
    },
    BuiltinSignature {
        name: "strategy.closedtrades.commission",
        phase: BuiltinPhase::Phase1Core,
        params: STRATEGY_TRADE_FIELD_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_FLOAT),
        variadic: false,
    },
    BuiltinSignature {
        name: "strategy.closedtrades.size",
        phase: BuiltinPhase::Phase1Core,
        params: STRATEGY_TRADE_FIELD_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_FLOAT),
        variadic: false,
    },
    BuiltinSignature {
        name: "strategy.closedtrades.profit",
        phase: BuiltinPhase::Phase1Core,
        params: STRATEGY_TRADE_FIELD_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_FLOAT),
        variadic: false,
    },
    BuiltinSignature {
        name: "strategy.closedtrades.profit_percent",
        phase: BuiltinPhase::Phase1Core,
        params: STRATEGY_TRADE_FIELD_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_FLOAT),
        variadic: false,
    },
    BuiltinSignature {
        name: "strategy.closedtrades.max_runup",
        phase: BuiltinPhase::Phase1Core,
        params: STRATEGY_TRADE_FIELD_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_FLOAT),
        variadic: false,
    },
    BuiltinSignature {
        name: "strategy.closedtrades.max_runup_percent",
        phase: BuiltinPhase::Phase1Core,
        params: STRATEGY_TRADE_FIELD_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_FLOAT),
        variadic: false,
    },
    BuiltinSignature {
        name: "strategy.closedtrades.max_drawdown",
        phase: BuiltinPhase::Phase1Core,
        params: STRATEGY_TRADE_FIELD_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_FLOAT),
        variadic: false,
    },
    BuiltinSignature {
        name: "strategy.closedtrades.max_drawdown_percent",
        phase: BuiltinPhase::Phase1Core,
        params: STRATEGY_TRADE_FIELD_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_FLOAT),
        variadic: false,
    },
    BuiltinSignature {
        name: "strategy.opentrades.entry_price",
        phase: BuiltinPhase::Phase1Core,
        params: STRATEGY_TRADE_FIELD_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_FLOAT),
        variadic: false,
    },
    BuiltinSignature {
        name: "strategy.opentrades.entry_comment",
        phase: BuiltinPhase::Phase1Core,
        params: STRATEGY_TRADE_FIELD_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_STRING),
        variadic: false,
    },
    BuiltinSignature {
        name: "strategy.opentrades.entry_id",
        phase: BuiltinPhase::Phase1Core,
        params: STRATEGY_TRADE_FIELD_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_STRING),
        variadic: false,
    },
    BuiltinSignature {
        name: "strategy.opentrades.entry_bar_index",
        phase: BuiltinPhase::Phase1Core,
        params: STRATEGY_TRADE_FIELD_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_INT),
        variadic: false,
    },
    BuiltinSignature {
        name: "strategy.opentrades.entry_time",
        phase: BuiltinPhase::Phase1Core,
        params: STRATEGY_TRADE_FIELD_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_INT),
        variadic: false,
    },
    BuiltinSignature {
        name: "strategy.opentrades.size",
        phase: BuiltinPhase::Phase1Core,
        params: STRATEGY_TRADE_FIELD_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_FLOAT),
        variadic: false,
    },
    BuiltinSignature {
        name: "strategy.opentrades.profit",
        phase: BuiltinPhase::Phase1Core,
        params: STRATEGY_TRADE_FIELD_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_FLOAT),
        variadic: false,
    },
    BuiltinSignature {
        name: "strategy.opentrades.profit_percent",
        phase: BuiltinPhase::Phase1Core,
        params: STRATEGY_TRADE_FIELD_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_FLOAT),
        variadic: false,
    },
    BuiltinSignature {
        name: "strategy.opentrades.commission",
        phase: BuiltinPhase::Phase1Core,
        params: STRATEGY_TRADE_FIELD_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_FLOAT),
        variadic: false,
    },
    BuiltinSignature {
        name: "strategy.opentrades.max_runup",
        phase: BuiltinPhase::Phase1Core,
        params: STRATEGY_TRADE_FIELD_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_FLOAT),
        variadic: false,
    },
    BuiltinSignature {
        name: "strategy.opentrades.max_runup_percent",
        phase: BuiltinPhase::Phase1Core,
        params: STRATEGY_TRADE_FIELD_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_FLOAT),
        variadic: false,
    },
    BuiltinSignature {
        name: "strategy.opentrades.max_drawdown",
        phase: BuiltinPhase::Phase1Core,
        params: STRATEGY_TRADE_FIELD_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_FLOAT),
        variadic: false,
    },
    BuiltinSignature {
        name: "strategy.opentrades.max_drawdown_percent",
        phase: BuiltinPhase::Phase1Core,
        params: STRATEGY_TRADE_FIELD_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_FLOAT),
        variadic: false,
    },
];
