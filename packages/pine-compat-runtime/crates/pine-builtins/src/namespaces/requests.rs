use crate::signature::{Accepts, BuiltinParam, BuiltinPhase, BuiltinSignature, ReturnSpec};

const REQUEST_SECURITY_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "symbol",
        accepts: Accepts::SimpleString,
        optional: false,
    },
    BuiltinParam {
        name: "timeframe",
        accepts: Accepts::SimpleString,
        optional: false,
    },
    BuiltinParam {
        name: "expression",
        accepts: Accepts::Any,
        optional: false,
    },
    BuiltinParam {
        name: "gaps",
        accepts: Accepts::SimpleString,
        optional: true,
    },
    BuiltinParam {
        name: "lookahead",
        accepts: Accepts::SimpleString,
        optional: true,
    },
];

pub(crate) const SIGNATURES: &[BuiltinSignature] = &[BuiltinSignature {
    name: "request.security",
    phase: BuiltinPhase::Phase1Core,
    params: REQUEST_SECURITY_PARAMS,
    returns: ReturnSpec::SeriesFromArg(2),
    variadic: false,
}];
