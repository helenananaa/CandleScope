use crate::signature::{Accepts, BuiltinParam, BuiltinPhase, BuiltinSignature, ReturnSpec};

use super::types::*;

const MATH_NUMBER_COMPAT_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "number",
    accepts: Accepts::NumericCompatible,
    optional: false,
}];

const MATH_MIN_MAX_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "a",
        accepts: Accepts::NumericCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "b",
        accepts: Accepts::NumericCompatible,
        optional: false,
    },
];

const MATH_AVG_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "number",
    accepts: Accepts::NumericCompatible,
    optional: false,
}];

const MATH_POW_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "base",
        accepts: Accepts::NumericCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "exponent",
        accepts: Accepts::NumericCompatible,
        optional: false,
    },
];

const MATH_HYPOT_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "number1",
        accepts: Accepts::NumericCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "number2",
        accepts: Accepts::NumericCompatible,
        optional: false,
    },
];

const MATH_ROUND_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "number",
        accepts: Accepts::NumericCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "precision",
        accepts: Accepts::IntCompatible,
        optional: true,
    },
];

const MATH_RANDOM_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "min",
        accepts: Accepts::NumericCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "max",
        accepts: Accepts::NumericCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "seed",
        accepts: Accepts::SimpleIntCompatible,
        optional: true,
    },
];

const MATH_SUM_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "source",
        accepts: Accepts::NumericCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "length",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
];

pub(crate) const SIGNATURES: &[BuiltinSignature] = &[
    BuiltinSignature {
        name: "math.abs",
        phase: BuiltinPhase::Phase1Core,
        params: MATH_NUMBER_COMPAT_PARAMS,
        returns: ReturnSpec::SameAsArg(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "math.max",
        phase: BuiltinPhase::Phase1Core,
        params: MATH_MIN_MAX_PARAMS,
        returns: ReturnSpec::PromotedNumeric,
        variadic: true,
    },
    BuiltinSignature {
        name: "math.min",
        phase: BuiltinPhase::Phase1Core,
        params: MATH_MIN_MAX_PARAMS,
        returns: ReturnSpec::PromotedNumeric,
        variadic: true,
    },
    BuiltinSignature {
        name: "math.avg",
        phase: BuiltinPhase::Phase1Core,
        params: MATH_AVG_PARAMS,
        returns: ReturnSpec::PromotedFloat,
        variadic: true,
    },
    BuiltinSignature {
        name: "math.floor",
        phase: BuiltinPhase::Phase1Core,
        params: MATH_NUMBER_COMPAT_PARAMS,
        returns: ReturnSpec::IntFromArg(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "math.ceil",
        phase: BuiltinPhase::Phase1Core,
        params: MATH_NUMBER_COMPAT_PARAMS,
        returns: ReturnSpec::IntFromArg(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "math.trunc",
        phase: BuiltinPhase::Phase1Core,
        params: MATH_NUMBER_COMPAT_PARAMS,
        returns: ReturnSpec::IntFromArg(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "math.sqrt",
        phase: BuiltinPhase::Phase1Core,
        params: MATH_NUMBER_COMPAT_PARAMS,
        returns: ReturnSpec::FloatFromArg(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "math.cbrt",
        phase: BuiltinPhase::Phase1Core,
        params: MATH_NUMBER_COMPAT_PARAMS,
        returns: ReturnSpec::FloatFromArg(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "math.log",
        phase: BuiltinPhase::Phase1Core,
        params: MATH_NUMBER_COMPAT_PARAMS,
        returns: ReturnSpec::FloatFromArg(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "math.log10",
        phase: BuiltinPhase::Phase1Core,
        params: MATH_NUMBER_COMPAT_PARAMS,
        returns: ReturnSpec::FloatFromArg(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "math.exp",
        phase: BuiltinPhase::Phase1Core,
        params: MATH_NUMBER_COMPAT_PARAMS,
        returns: ReturnSpec::FloatFromArg(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "math.acos",
        phase: BuiltinPhase::Phase1Core,
        params: MATH_NUMBER_COMPAT_PARAMS,
        returns: ReturnSpec::FloatFromArg(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "math.asin",
        phase: BuiltinPhase::Phase1Core,
        params: MATH_NUMBER_COMPAT_PARAMS,
        returns: ReturnSpec::FloatFromArg(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "math.atan",
        phase: BuiltinPhase::Phase1Core,
        params: MATH_NUMBER_COMPAT_PARAMS,
        returns: ReturnSpec::FloatFromArg(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "math.sign",
        phase: BuiltinPhase::Phase1Core,
        params: MATH_NUMBER_COMPAT_PARAMS,
        returns: ReturnSpec::FloatFromArg(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "math.todegrees",
        phase: BuiltinPhase::Phase1Core,
        params: MATH_NUMBER_COMPAT_PARAMS,
        returns: ReturnSpec::FloatFromArg(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "math.toradians",
        phase: BuiltinPhase::Phase1Core,
        params: MATH_NUMBER_COMPAT_PARAMS,
        returns: ReturnSpec::FloatFromArg(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "math.sin",
        phase: BuiltinPhase::Phase1Core,
        params: MATH_NUMBER_COMPAT_PARAMS,
        returns: ReturnSpec::FloatFromArg(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "math.cos",
        phase: BuiltinPhase::Phase1Core,
        params: MATH_NUMBER_COMPAT_PARAMS,
        returns: ReturnSpec::FloatFromArg(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "math.tan",
        phase: BuiltinPhase::Phase1Core,
        params: MATH_NUMBER_COMPAT_PARAMS,
        returns: ReturnSpec::FloatFromArg(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "math.pow",
        phase: BuiltinPhase::Phase1Core,
        params: MATH_POW_PARAMS,
        returns: ReturnSpec::PromotedFloat,
        variadic: false,
    },
    BuiltinSignature {
        name: "math.hypot",
        phase: BuiltinPhase::Phase1Core,
        params: MATH_HYPOT_PARAMS,
        returns: ReturnSpec::PromotedFloat,
        variadic: false,
    },
    BuiltinSignature {
        name: "math.round",
        phase: BuiltinPhase::Phase1Core,
        params: MATH_ROUND_PARAMS,
        returns: ReturnSpec::Round,
        variadic: false,
    },
    BuiltinSignature {
        name: "math.round_to_mintick",
        phase: BuiltinPhase::Phase1Core,
        params: MATH_NUMBER_COMPAT_PARAMS,
        returns: ReturnSpec::FloatFromArg(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "math.random",
        phase: BuiltinPhase::Phase1Core,
        params: MATH_RANDOM_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_FLOAT),
        variadic: false,
    },
    BuiltinSignature {
        name: "math.sum",
        phase: BuiltinPhase::Phase1Core,
        params: MATH_SUM_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_FLOAT),
        variadic: false,
    },
];
