use crate::signature::{Accepts, BuiltinParam, BuiltinPhase, BuiltinSignature, ReturnSpec};

use super::types::SERIES_CHART_POINT;

const CHART_POINT_NEW_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "time",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "index",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "price",
        accepts: Accepts::NumericCompatible,
        optional: false,
    },
];

const CHART_POINT_NOW_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "price",
    accepts: Accepts::NumericCompatible,
    optional: false,
}];

const CHART_POINT_FROM_INDEX_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "index",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "price",
        accepts: Accepts::NumericCompatible,
        optional: false,
    },
];

const CHART_POINT_FROM_TIME_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "time",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "price",
        accepts: Accepts::NumericCompatible,
        optional: false,
    },
];

const CHART_POINT_COPY_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "id",
    accepts: Accepts::ChartPointCompatible,
    optional: false,
}];

pub(crate) const SIGNATURES: &[BuiltinSignature] = &[
    BuiltinSignature {
        name: "chart.point.new",
        phase: BuiltinPhase::Phase1Core,
        params: CHART_POINT_NEW_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_CHART_POINT),
        variadic: false,
    },
    BuiltinSignature {
        name: "chart.point.now",
        phase: BuiltinPhase::Phase1Core,
        params: CHART_POINT_NOW_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_CHART_POINT),
        variadic: false,
    },
    BuiltinSignature {
        name: "chart.point.from_index",
        phase: BuiltinPhase::Phase1Core,
        params: CHART_POINT_FROM_INDEX_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_CHART_POINT),
        variadic: false,
    },
    BuiltinSignature {
        name: "chart.point.from_time",
        phase: BuiltinPhase::Phase1Core,
        params: CHART_POINT_FROM_TIME_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_CHART_POINT),
        variadic: false,
    },
    BuiltinSignature {
        name: "chart.point.copy",
        phase: BuiltinPhase::Phase1Core,
        params: CHART_POINT_COPY_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_CHART_POINT),
        variadic: false,
    },
];
