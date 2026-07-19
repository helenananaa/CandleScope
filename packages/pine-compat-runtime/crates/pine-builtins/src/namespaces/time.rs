use crate::signature::{Accepts, BuiltinParam, BuiltinPhase, BuiltinSignature, ReturnSpec};

use super::types::*;

const TIME_COMPONENT_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "time",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "timezone",
        accepts: Accepts::StringCompatible,
        optional: true,
    },
];

const TIMEFRAME_IN_SECONDS_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "timeframe",
    accepts: Accepts::SimpleString,
    optional: true,
}];

const TIMEFRAME_FROM_SECONDS_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "seconds",
    accepts: Accepts::SimpleIntCompatible,
    optional: false,
}];

const TIMEFRAME_CHANGE_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "timeframe",
    accepts: Accepts::SimpleString,
    optional: false,
}];

const TIME_FUNCTION_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "timeframe",
        accepts: Accepts::SimpleString,
        optional: false,
    },
    BuiltinParam {
        name: "session",
        accepts: Accepts::StringCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "timezone",
        accepts: Accepts::StringCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "bars_back",
        accepts: Accepts::IntCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "timeframe_bars_back",
        accepts: Accepts::IntCompatible,
        optional: true,
    },
];

const TIMESTAMP_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "timezone",
        accepts: Accepts::StringCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "year",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "month",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "day",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "hour",
        accepts: Accepts::IntCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "minute",
        accepts: Accepts::IntCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "second",
        accepts: Accepts::IntCompatible,
        optional: true,
    },
];

pub(crate) const SIGNATURES: &[BuiltinSignature] = &[
    BuiltinSignature {
        name: "year",
        phase: BuiltinPhase::Phase1Core,
        params: TIME_COMPONENT_PARAMS,
        returns: ReturnSpec::PromotedInt,
        variadic: false,
    },
    BuiltinSignature {
        name: "month",
        phase: BuiltinPhase::Phase1Core,
        params: TIME_COMPONENT_PARAMS,
        returns: ReturnSpec::PromotedInt,
        variadic: false,
    },
    BuiltinSignature {
        name: "dayofmonth",
        phase: BuiltinPhase::Phase1Core,
        params: TIME_COMPONENT_PARAMS,
        returns: ReturnSpec::PromotedInt,
        variadic: false,
    },
    BuiltinSignature {
        name: "dayofweek",
        phase: BuiltinPhase::Phase1Core,
        params: TIME_COMPONENT_PARAMS,
        returns: ReturnSpec::PromotedInt,
        variadic: false,
    },
    BuiltinSignature {
        name: "weekofyear",
        phase: BuiltinPhase::Phase1Core,
        params: TIME_COMPONENT_PARAMS,
        returns: ReturnSpec::PromotedInt,
        variadic: false,
    },
    BuiltinSignature {
        name: "hour",
        phase: BuiltinPhase::Phase1Core,
        params: TIME_COMPONENT_PARAMS,
        returns: ReturnSpec::PromotedInt,
        variadic: false,
    },
    BuiltinSignature {
        name: "minute",
        phase: BuiltinPhase::Phase1Core,
        params: TIME_COMPONENT_PARAMS,
        returns: ReturnSpec::PromotedInt,
        variadic: false,
    },
    BuiltinSignature {
        name: "second",
        phase: BuiltinPhase::Phase1Core,
        params: TIME_COMPONENT_PARAMS,
        returns: ReturnSpec::PromotedInt,
        variadic: false,
    },
    BuiltinSignature {
        name: "timestamp",
        phase: BuiltinPhase::Phase1Core,
        params: TIMESTAMP_PARAMS,
        returns: ReturnSpec::PromotedInt,
        variadic: false,
    },
    BuiltinSignature {
        name: "time",
        phase: BuiltinPhase::Phase1Core,
        params: TIME_FUNCTION_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_INT),
        variadic: false,
    },
    BuiltinSignature {
        name: "time_close",
        phase: BuiltinPhase::Phase1Core,
        params: TIME_FUNCTION_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_INT),
        variadic: false,
    },
    BuiltinSignature {
        name: "timeframe.in_seconds",
        phase: BuiltinPhase::Phase1Core,
        params: TIMEFRAME_IN_SECONDS_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_INT),
        variadic: false,
    },
    BuiltinSignature {
        name: "timeframe.from_seconds",
        phase: BuiltinPhase::Phase1Core,
        params: TIMEFRAME_FROM_SECONDS_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_STRING),
        variadic: false,
    },
    BuiltinSignature {
        name: "timeframe.change",
        phase: BuiltinPhase::Phase1Core,
        params: TIMEFRAME_CHANGE_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_BOOL),
        variadic: false,
    },
];
