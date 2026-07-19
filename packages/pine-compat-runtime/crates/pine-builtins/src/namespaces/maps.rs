use crate::signature::{Accepts, BuiltinParam, BuiltinPhase, BuiltinSignature, ReturnSpec};

use super::types::*;

const MAP_VALUE_PARAM: &[BuiltinParam] = &[BuiltinParam {
    name: "id",
    accepts: Accepts::Map,
    optional: false,
}];

pub(crate) const SIGNATURES: &[BuiltinSignature] = &[BuiltinSignature {
    name: "map.size",
    phase: BuiltinPhase::Phase1Core,
    params: MAP_VALUE_PARAM,
    returns: ReturnSpec::Fixed(SIMPLE_INT),
    variadic: false,
}];
