use crate::signature::{Accepts, BuiltinParam, BuiltinPhase, BuiltinSignature, ReturnSpec};

use super::types::*;

const SYMBOL_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "symbol",
    accepts: Accepts::SimpleString,
    optional: false,
}];

pub(crate) const SIGNATURES: &[BuiltinSignature] = &[
    BuiltinSignature {
        name: "syminfo.prefix",
        phase: BuiltinPhase::Phase1Core,
        params: SYMBOL_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_STRING),
        variadic: false,
    },
    BuiltinSignature {
        name: "syminfo.ticker",
        phase: BuiltinPhase::Phase1Core,
        params: SYMBOL_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_STRING),
        variadic: false,
    },
];
