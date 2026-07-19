use crate::signature::{Accepts, BuiltinParam, BuiltinPhase, BuiltinSignature, ReturnSpec};

use super::types::*;

const STR_TEXT_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "string",
    accepts: Accepts::StringCompatible,
    optional: false,
}];

const STR_SOURCE_SUBSTRING_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "source",
        accepts: Accepts::StringCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "str",
        accepts: Accepts::StringCompatible,
        optional: false,
    },
];

const STR_SOURCE_REGEX_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "source",
        accepts: Accepts::StringCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "regex",
        accepts: Accepts::StringCompatible,
        optional: false,
    },
];

const STR_SPLIT_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "source",
        accepts: Accepts::StringCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "separator",
        accepts: Accepts::StringCompatible,
        optional: false,
    },
];

const STR_SUBSTRING_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "source",
        accepts: Accepts::StringCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "begin_pos",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "end_pos",
        accepts: Accepts::IntCompatible,
        optional: true,
    },
];

const STR_REPEAT_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "source",
        accepts: Accepts::StringCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "repeat",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "separator",
        accepts: Accepts::StringCompatible,
        optional: true,
    },
];

const STR_REPLACE_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "source",
        accepts: Accepts::StringCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "target",
        accepts: Accepts::StringCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "replacement",
        accepts: Accepts::StringCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "occurrence",
        accepts: Accepts::IntCompatible,
        optional: true,
    },
];

const STR_REPLACE_ALL_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "source",
        accepts: Accepts::StringCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "target",
        accepts: Accepts::StringCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "replacement",
        accepts: Accepts::StringCompatible,
        optional: false,
    },
];

const STR_TOSTRING_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "value",
        accepts: Accepts::StringConvertible,
        optional: false,
    },
    BuiltinParam {
        name: "format",
        accepts: Accepts::StringCompatible,
        optional: true,
    },
];

const STR_FORMAT_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "formatString",
        accepts: Accepts::StringCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "arg",
        accepts: Accepts::FormatConvertible,
        optional: true,
    },
];

const STR_FORMAT_TIME_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "time",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "format",
        accepts: Accepts::StringCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "timezone",
        accepts: Accepts::StringCompatible,
        optional: true,
    },
];

pub(crate) const SIGNATURES: &[BuiltinSignature] = &[
    BuiltinSignature {
        name: "str.length",
        phase: BuiltinPhase::Phase1Core,
        params: STR_TEXT_PARAMS,
        returns: ReturnSpec::IntFromArg(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "str.upper",
        phase: BuiltinPhase::Phase1Core,
        params: STR_TEXT_PARAMS,
        returns: ReturnSpec::SameAsArg(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "str.lower",
        phase: BuiltinPhase::Phase1Core,
        params: STR_TEXT_PARAMS,
        returns: ReturnSpec::SameAsArg(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "str.contains",
        phase: BuiltinPhase::Phase1Core,
        params: STR_SOURCE_SUBSTRING_PARAMS,
        returns: ReturnSpec::PromotedBool,
        variadic: false,
    },
    BuiltinSignature {
        name: "str.startswith",
        phase: BuiltinPhase::Phase1Core,
        params: STR_SOURCE_SUBSTRING_PARAMS,
        returns: ReturnSpec::PromotedBool,
        variadic: false,
    },
    BuiltinSignature {
        name: "str.endswith",
        phase: BuiltinPhase::Phase1Core,
        params: STR_SOURCE_SUBSTRING_PARAMS,
        returns: ReturnSpec::PromotedBool,
        variadic: false,
    },
    BuiltinSignature {
        name: "str.pos",
        phase: BuiltinPhase::Phase1Core,
        params: STR_SOURCE_SUBSTRING_PARAMS,
        returns: ReturnSpec::PromotedInt,
        variadic: false,
    },
    BuiltinSignature {
        name: "str.substring",
        phase: BuiltinPhase::Phase1Core,
        params: STR_SUBSTRING_PARAMS,
        returns: ReturnSpec::PromotedString,
        variadic: false,
    },
    BuiltinSignature {
        name: "str.trim",
        phase: BuiltinPhase::Phase1Core,
        params: STR_TEXT_PARAMS,
        returns: ReturnSpec::SameAsArg(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "str.repeat",
        phase: BuiltinPhase::Phase1Core,
        params: STR_REPEAT_PARAMS,
        returns: ReturnSpec::PromotedString,
        variadic: false,
    },
    BuiltinSignature {
        name: "str.replace",
        phase: BuiltinPhase::Phase1Core,
        params: STR_REPLACE_PARAMS,
        returns: ReturnSpec::PromotedString,
        variadic: false,
    },
    BuiltinSignature {
        name: "str.replace_all",
        phase: BuiltinPhase::Phase1Core,
        params: STR_REPLACE_ALL_PARAMS,
        returns: ReturnSpec::PromotedString,
        variadic: false,
    },
    BuiltinSignature {
        name: "str.tonumber",
        phase: BuiltinPhase::Phase1Core,
        params: STR_TEXT_PARAMS,
        returns: ReturnSpec::FloatFromStringArg(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "str.tostring",
        phase: BuiltinPhase::Phase1Core,
        params: STR_TOSTRING_PARAMS,
        returns: ReturnSpec::PromotedString,
        variadic: false,
    },
    BuiltinSignature {
        name: "str.format",
        phase: BuiltinPhase::Phase1Core,
        params: STR_FORMAT_PARAMS,
        returns: ReturnSpec::PromotedString,
        variadic: true,
    },
    BuiltinSignature {
        name: "str.match",
        phase: BuiltinPhase::Phase1Core,
        params: STR_SOURCE_REGEX_PARAMS,
        returns: ReturnSpec::PromotedString,
        variadic: false,
    },
    BuiltinSignature {
        name: "str.split",
        phase: BuiltinPhase::Phase1Core,
        params: STR_SPLIT_PARAMS,
        returns: ReturnSpec::Fixed(SIMPLE_STRING_ARRAY),
        variadic: false,
    },
    BuiltinSignature {
        name: "str.format_time",
        phase: BuiltinPhase::Phase1Core,
        params: STR_FORMAT_TIME_PARAMS,
        returns: ReturnSpec::PromotedString,
        variadic: false,
    },
];
