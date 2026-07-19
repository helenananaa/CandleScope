use crate::signature::{Accepts, BuiltinParam, BuiltinPhase, BuiltinSignature, ReturnSpec};

const COLOR_NEW_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "color",
        accepts: Accepts::ColorCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "transp",
        accepts: Accepts::SimpleIntCompatible,
        optional: true,
    },
];

const COLOR_RGB_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "red",
        accepts: Accepts::NumericCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "green",
        accepts: Accepts::NumericCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "blue",
        accepts: Accepts::NumericCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "transp",
        accepts: Accepts::NumericCompatible,
        optional: true,
    },
];

const COLOR_COMPONENT_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "color",
    accepts: Accepts::ColorCompatible,
    optional: false,
}];

const COLOR_FROM_GRADIENT_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "value",
        accepts: Accepts::NumericCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "bottom_value",
        accepts: Accepts::NumericCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "top_value",
        accepts: Accepts::NumericCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "bottom_color",
        accepts: Accepts::ColorCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "top_color",
        accepts: Accepts::ColorCompatible,
        optional: false,
    },
];

pub(crate) const SIGNATURES: &[BuiltinSignature] = &[
    BuiltinSignature {
        name: "color.new",
        phase: BuiltinPhase::Phase1Core,
        params: COLOR_NEW_PARAMS,
        returns: ReturnSpec::ColorFromArg(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "color.rgb",
        phase: BuiltinPhase::Phase1Core,
        params: COLOR_RGB_PARAMS,
        returns: ReturnSpec::PromotedColor,
        variadic: false,
    },
    BuiltinSignature {
        name: "color.r",
        phase: BuiltinPhase::Phase1Core,
        params: COLOR_COMPONENT_PARAMS,
        returns: ReturnSpec::FloatFromArg(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "color.g",
        phase: BuiltinPhase::Phase1Core,
        params: COLOR_COMPONENT_PARAMS,
        returns: ReturnSpec::FloatFromArg(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "color.b",
        phase: BuiltinPhase::Phase1Core,
        params: COLOR_COMPONENT_PARAMS,
        returns: ReturnSpec::FloatFromArg(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "color.t",
        phase: BuiltinPhase::Phase1Core,
        params: COLOR_COMPONENT_PARAMS,
        returns: ReturnSpec::FloatFromArg(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "color.from_gradient",
        phase: BuiltinPhase::Phase1Core,
        params: COLOR_FROM_GRADIENT_PARAMS,
        returns: ReturnSpec::PromotedColor,
        variadic: false,
    },
];
