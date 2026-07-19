use crate::signature::{Accepts, BuiltinParam, BuiltinPhase, BuiltinSignature, ReturnSpec};

use super::types::*;

const ARRAY_NEW_FLOAT_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "size",
        accepts: Accepts::SimpleIntCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "initial_value",
        accepts: Accepts::NumericCompatible,
        optional: true,
    },
];

const ARRAY_NEW_INT_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "size",
        accepts: Accepts::SimpleIntCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "initial_value",
        accepts: Accepts::IntCompatible,
        optional: true,
    },
];

const ARRAY_NEW_BOOL_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "size",
        accepts: Accepts::SimpleIntCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "initial_value",
        accepts: Accepts::BoolCompatible,
        optional: true,
    },
];

const ARRAY_NEW_STRING_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "size",
        accepts: Accepts::SimpleIntCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "initial_value",
        accepts: Accepts::StringCompatible,
        optional: true,
    },
];

const ARRAY_NEW_COLOR_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "size",
        accepts: Accepts::SimpleIntCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "initial_value",
        accepts: Accepts::ColorCompatible,
        optional: true,
    },
];

const ARRAY_NEW_LINE_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "size",
        accepts: Accepts::SimpleIntCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "initial_value",
        accepts: Accepts::LineCompatible,
        optional: true,
    },
];

const ARRAY_NEW_LINEFILL_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "size",
        accepts: Accepts::SimpleIntCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "initial_value",
        accepts: Accepts::LineFillCompatible,
        optional: true,
    },
];

const ARRAY_NEW_POLYLINE_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "size",
        accepts: Accepts::SimpleIntCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "initial_value",
        accepts: Accepts::PolylineCompatible,
        optional: true,
    },
];

const ARRAY_NEW_LABEL_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "size",
        accepts: Accepts::SimpleIntCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "initial_value",
        accepts: Accepts::LabelCompatible,
        optional: true,
    },
];

const ARRAY_NEW_BOX_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "size",
        accepts: Accepts::SimpleIntCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "initial_value",
        accepts: Accepts::BoxCompatible,
        optional: true,
    },
];

const ARRAY_NEW_TABLE_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "size",
        accepts: Accepts::SimpleIntCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "initial_value",
        accepts: Accepts::TableCompatible,
        optional: true,
    },
];

const ARRAY_NEW_CHART_POINT_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "size",
        accepts: Accepts::SimpleIntCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "initial_value",
        accepts: Accepts::ChartPointCompatible,
        optional: true,
    },
];

const ARRAY_FROM_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "value",
    accepts: Accepts::Any,
    optional: false,
}];

const ARRAY_SIZE_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "id",
    accepts: Accepts::Array,
    optional: false,
}];

const ARRAY_NUMERIC_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "id",
    accepts: Accepts::NumericArray,
    optional: false,
}];

const ARRAY_MIN_MAX_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::NumericArray,
        optional: false,
    },
    BuiltinParam {
        name: "nth",
        accepts: Accepts::IntCompatible,
        optional: true,
    },
];

const ARRAY_TRUTHY_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "id",
    accepts: Accepts::NumericOrBoolArray,
    optional: false,
}];

const ARRAY_SORT_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::NumericOrStringArray,
        optional: false,
    },
    BuiltinParam {
        name: "order",
        accepts: Accepts::ConstString,
        optional: true,
    },
];

const ARRAY_VARIANCE_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::NumericArray,
        optional: false,
    },
    BuiltinParam {
        name: "biased",
        accepts: Accepts::BoolCompatible,
        optional: true,
    },
];

const ARRAY_COVARIANCE_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id1",
        accepts: Accepts::NumericArray,
        optional: false,
    },
    BuiltinParam {
        name: "id2",
        accepts: Accepts::NumericArray,
        optional: false,
    },
    BuiltinParam {
        name: "biased",
        accepts: Accepts::BoolCompatible,
        optional: true,
    },
];

const ARRAY_PERCENTILE_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::NumericArray,
        optional: false,
    },
    BuiltinParam {
        name: "percentage",
        accepts: Accepts::SeriesOrSimpleNumeric,
        optional: false,
    },
];

const ARRAY_PERCENTRANK_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::NumericArray,
        optional: false,
    },
    BuiltinParam {
        name: "index",
        accepts: Accepts::SimpleIntCompatible,
        optional: false,
    },
];

const ARRAY_JOIN_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::ScalarArray,
        optional: false,
    },
    BuiltinParam {
        name: "separator",
        accepts: Accepts::StringCompatible,
        optional: true,
    },
];

const ARRAY_SLICE_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::Array,
        optional: false,
    },
    BuiltinParam {
        name: "index_from",
        accepts: Accepts::SimpleIntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "index_to",
        accepts: Accepts::SimpleIntCompatible,
        optional: false,
    },
];

const ARRAY_CONCAT_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::Array,
        optional: false,
    },
    BuiltinParam {
        name: "id2",
        accepts: Accepts::Array,
        optional: false,
    },
];

const ARRAY_VALUE_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::Array,
        optional: false,
    },
    BuiltinParam {
        name: "value",
        accepts: Accepts::Any,
        optional: false,
    },
];

const ARRAY_NUMERIC_VALUE_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::NumericArray,
        optional: false,
    },
    BuiltinParam {
        name: "value",
        accepts: Accepts::Any,
        optional: false,
    },
];

const ARRAY_FILL_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::Array,
        optional: false,
    },
    BuiltinParam {
        name: "value",
        accepts: Accepts::Any,
        optional: false,
    },
    BuiltinParam {
        name: "index_from",
        accepts: Accepts::SimpleIntCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "index_to",
        accepts: Accepts::SimpleIntCompatible,
        optional: true,
    },
];

const ARRAY_INDEX_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::Array,
        optional: false,
    },
    BuiltinParam {
        name: "index",
        accepts: Accepts::SimpleIntCompatible,
        optional: false,
    },
];

const ARRAY_SET_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::Array,
        optional: false,
    },
    BuiltinParam {
        name: "index",
        accepts: Accepts::SimpleIntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "value",
        accepts: Accepts::Any,
        optional: false,
    },
];

pub(crate) const SIGNATURES: &[BuiltinSignature] = &[
    BuiltinSignature {
        name: "array.new_float",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_NEW_FLOAT_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_FLOAT_ARRAY),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.new_int",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_NEW_INT_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_INT_ARRAY),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.new_bool",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_NEW_BOOL_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_BOOL_ARRAY),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.new_string",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_NEW_STRING_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_STRING_ARRAY),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.new_color",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_NEW_COLOR_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_COLOR_ARRAY),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.new_line",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_NEW_LINE_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_LINE_ARRAY),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.new_linefill",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_NEW_LINEFILL_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_LINE_FILL_ARRAY),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.new_polyline",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_NEW_POLYLINE_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_POLYLINE_ARRAY),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.new_label",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_NEW_LABEL_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_LABEL_ARRAY),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.new_box",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_NEW_BOX_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_BOX_ARRAY),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.new_table",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_NEW_TABLE_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_TABLE_ARRAY),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.new<chart.point>",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_NEW_CHART_POINT_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_CHART_POINT_ARRAY),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.from",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_FROM_PARAMS,
        returns: ReturnSpec::ArrayFromArgs,
        variadic: true,
    },
    BuiltinSignature {
        name: "array.size",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_SIZE_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_INT),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.push",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_VALUE_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.get",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_INDEX_PARAMS,
        returns: ReturnSpec::ArrayElement(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.set",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_SET_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.insert",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_SET_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.pop",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_SIZE_PARAMS,
        returns: ReturnSpec::ArrayElement(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.remove",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_INDEX_PARAMS,
        returns: ReturnSpec::ArrayElement(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.shift",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_SIZE_PARAMS,
        returns: ReturnSpec::ArrayElement(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.unshift",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_VALUE_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.fill",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_FILL_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.first",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_SIZE_PARAMS,
        returns: ReturnSpec::ArrayElement(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.last",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_SIZE_PARAMS,
        returns: ReturnSpec::ArrayElement(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.copy",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_SIZE_PARAMS,
        returns: ReturnSpec::SameAsArg(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.slice",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_SLICE_PARAMS,
        returns: ReturnSpec::SameAsArg(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.concat",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_CONCAT_PARAMS,
        returns: ReturnSpec::SameAsArg(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.includes",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_VALUE_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_BOOL),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.every",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_TRUTHY_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_BOOL),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.some",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_TRUTHY_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_BOOL),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.indexof",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_VALUE_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_INT),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.lastindexof",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_VALUE_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_INT),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.binary_search",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_NUMERIC_VALUE_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_INT),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.binary_search_leftmost",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_NUMERIC_VALUE_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_INT),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.binary_search_rightmost",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_NUMERIC_VALUE_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_INT),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.abs",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_NUMERIC_PARAMS,
        returns: ReturnSpec::SameAsArg(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.min",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_MIN_MAX_PARAMS,
        returns: ReturnSpec::ArrayNumeric(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.max",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_MIN_MAX_PARAMS,
        returns: ReturnSpec::ArrayNumeric(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.sum",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_NUMERIC_PARAMS,
        returns: ReturnSpec::ArrayNumeric(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.avg",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_NUMERIC_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_FLOAT),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.range",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_NUMERIC_PARAMS,
        returns: ReturnSpec::ArrayNumeric(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.median",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_NUMERIC_PARAMS,
        returns: ReturnSpec::ArrayNumeric(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.mode",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_NUMERIC_PARAMS,
        returns: ReturnSpec::ArrayNumeric(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.percentile_nearest_rank",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_PERCENTILE_PARAMS,
        returns: ReturnSpec::ArrayNumeric(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.percentile_linear_interpolation",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_PERCENTILE_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_FLOAT),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.percentrank",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_PERCENTRANK_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_FLOAT),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.covariance",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_COVARIANCE_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_FLOAT),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.standardize",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_NUMERIC_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_FLOAT_ARRAY),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.variance",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_VARIANCE_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_FLOAT),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.stdev",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_VARIANCE_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_FLOAT),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.sort",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_SORT_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.sort_indices",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_SORT_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_INT_ARRAY),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.reverse",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_SIZE_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.join",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_JOIN_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_STRING),
        variadic: false,
    },
    BuiltinSignature {
        name: "array.clear",
        phase: BuiltinPhase::Phase1Core,
        params: ARRAY_SIZE_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
];
