use crate::signature::{Accepts, BuiltinParam, BuiltinPhase, BuiltinSignature, ReturnSpec};

use super::types::*;

const NEW_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "prefix",
        accepts: Accepts::SimpleString,
        optional: false,
    },
    BuiltinParam {
        name: "ticker",
        accepts: Accepts::SimpleString,
        optional: false,
    },
    BuiltinParam {
        name: "session",
        accepts: Accepts::SimpleString,
        optional: true,
    },
    BuiltinParam {
        name: "adjustment",
        accepts: Accepts::SimpleString,
        optional: true,
    },
    BuiltinParam {
        name: "settlement_as_close",
        accepts: Accepts::SimpleString,
        optional: true,
    },
    BuiltinParam {
        name: "backadjustment",
        accepts: Accepts::SimpleString,
        optional: true,
    },
];

const SYMBOL_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "symbol",
    accepts: Accepts::SimpleString,
    optional: false,
}];

const HEIKINASHI_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "tickerid",
    accepts: Accepts::SimpleString,
    optional: false,
}];

const INHERIT_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "from_tickerid",
        accepts: Accepts::SimpleString,
        optional: false,
    },
    BuiltinParam {
        name: "symbol",
        accepts: Accepts::SimpleString,
        optional: false,
    },
];

const LINEBREAK_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "tickerid",
        accepts: Accepts::SimpleString,
        optional: false,
    },
    BuiltinParam {
        name: "number_of_lines",
        accepts: Accepts::SimpleIntCompatible,
        optional: false,
    },
];

const KAGI_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "tickerid",
        accepts: Accepts::SimpleString,
        optional: false,
    },
    BuiltinParam {
        name: "style",
        accepts: Accepts::SimpleString,
        optional: false,
    },
    BuiltinParam {
        name: "param",
        accepts: Accepts::SimpleNumericCompatible,
        optional: false,
    },
];

const POINTFIGURE_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "tickerid",
        accepts: Accepts::SimpleString,
        optional: false,
    },
    BuiltinParam {
        name: "source",
        accepts: Accepts::SimpleString,
        optional: false,
    },
    BuiltinParam {
        name: "style",
        accepts: Accepts::SimpleString,
        optional: false,
    },
    BuiltinParam {
        name: "param",
        accepts: Accepts::SimpleNumericCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "reversal",
        accepts: Accepts::SimpleIntCompatible,
        optional: false,
    },
];

const RENKO_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "tickerid",
        accepts: Accepts::SimpleString,
        optional: false,
    },
    BuiltinParam {
        name: "style",
        accepts: Accepts::SimpleString,
        optional: false,
    },
    BuiltinParam {
        name: "param",
        accepts: Accepts::SimpleNumericCompatible,
        optional: false,
    },
];

const MODIFY_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "tickerid",
        accepts: Accepts::SimpleString,
        optional: false,
    },
    BuiltinParam {
        name: "session",
        accepts: Accepts::SimpleString,
        optional: true,
    },
    BuiltinParam {
        name: "adjustment",
        accepts: Accepts::SimpleString,
        optional: true,
    },
    BuiltinParam {
        name: "settlement_as_close",
        accepts: Accepts::SimpleString,
        optional: true,
    },
    BuiltinParam {
        name: "backadjustment",
        accepts: Accepts::SimpleString,
        optional: true,
    },
];

pub(crate) const SIGNATURES: &[BuiltinSignature] = &[
    BuiltinSignature {
        name: "ticker.heikinashi",
        phase: BuiltinPhase::Phase1Core,
        params: HEIKINASHI_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_STRING),
        variadic: false,
    },
    BuiltinSignature {
        name: "ticker.inherit",
        phase: BuiltinPhase::Phase1Core,
        params: INHERIT_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_STRING),
        variadic: false,
    },
    BuiltinSignature {
        name: "ticker.linebreak",
        phase: BuiltinPhase::Phase1Core,
        params: LINEBREAK_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_STRING),
        variadic: false,
    },
    BuiltinSignature {
        name: "ticker.kagi",
        phase: BuiltinPhase::Phase1Core,
        params: KAGI_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_STRING),
        variadic: false,
    },
    BuiltinSignature {
        name: "ticker.new",
        phase: BuiltinPhase::Phase1Core,
        params: NEW_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_STRING),
        variadic: false,
    },
    BuiltinSignature {
        name: "ticker.modify",
        phase: BuiltinPhase::Phase1Core,
        params: MODIFY_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_STRING),
        variadic: false,
    },
    BuiltinSignature {
        name: "ticker.pointfigure",
        phase: BuiltinPhase::Phase1Core,
        params: POINTFIGURE_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_STRING),
        variadic: false,
    },
    BuiltinSignature {
        name: "ticker.renko",
        phase: BuiltinPhase::Phase1Core,
        params: RENKO_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_STRING),
        variadic: false,
    },
    BuiltinSignature {
        name: "ticker.standard",
        phase: BuiltinPhase::Phase1Core,
        params: SYMBOL_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_STRING),
        variadic: false,
    },
];
