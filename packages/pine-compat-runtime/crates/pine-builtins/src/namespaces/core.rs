use pine_ir::{PineType, Qualifier, ValueKind};

use crate::signature::{Accepts, BuiltinParam, BuiltinPhase, BuiltinSignature, ReturnSpec};

use super::types::*;

const INDICATOR_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "title",
        accepts: Accepts::ConstString,
        optional: false,
    },
    BuiltinParam {
        name: "shorttitle",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "overlay",
        accepts: Accepts::ConstBool,
        optional: true,
    },
    BuiltinParam {
        name: "format",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "precision",
        accepts: Accepts::Exact(PineType::new(Qualifier::Const, ValueKind::Int)),
        optional: true,
    },
    BuiltinParam {
        name: "scale",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "max_bars_back",
        accepts: Accepts::Exact(PineType::new(Qualifier::Const, ValueKind::Int)),
        optional: true,
    },
    BuiltinParam {
        name: "max_labels_count",
        accepts: Accepts::Exact(PineType::new(Qualifier::Const, ValueKind::Int)),
        optional: true,
    },
    BuiltinParam {
        name: "max_boxes_count",
        accepts: Accepts::Exact(PineType::new(Qualifier::Const, ValueKind::Int)),
        optional: true,
    },
    BuiltinParam {
        name: "max_lines_count",
        accepts: Accepts::Exact(PineType::new(Qualifier::Const, ValueKind::Int)),
        optional: true,
    },
    BuiltinParam {
        name: "max_polylines_count",
        accepts: Accepts::Exact(PineType::new(Qualifier::Const, ValueKind::Int)),
        optional: true,
    },
];

const STRATEGY_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "title",
        accepts: Accepts::ConstString,
        optional: false,
    },
    BuiltinParam {
        name: "shorttitle",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "overlay",
        accepts: Accepts::ConstBool,
        optional: true,
    },
    BuiltinParam {
        name: "max_bars_back",
        accepts: Accepts::Exact(PineType::new(Qualifier::Const, ValueKind::Int)),
        optional: true,
    },
    BuiltinParam {
        name: "initial_capital",
        accepts: Accepts::ConstNumeric,
        optional: true,
    },
    BuiltinParam {
        name: "default_qty_type",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "default_qty_value",
        accepts: Accepts::ConstNumeric,
        optional: true,
    },
    BuiltinParam {
        name: "commission_type",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "commission_value",
        accepts: Accepts::ConstNumeric,
        optional: true,
    },
    BuiltinParam {
        name: "slippage",
        accepts: Accepts::ConstNumeric,
        optional: true,
    },
    BuiltinParam {
        name: "backtest_fill_limits_assumption",
        accepts: Accepts::ConstNumeric,
        optional: true,
    },
    BuiltinParam {
        name: "margin_long",
        accepts: Accepts::ConstNumeric,
        optional: true,
    },
    BuiltinParam {
        name: "margin_short",
        accepts: Accepts::ConstNumeric,
        optional: true,
    },
    BuiltinParam {
        name: "pyramiding",
        accepts: Accepts::ConstNumeric,
        optional: true,
    },
    BuiltinParam {
        name: "close_entries_rule",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "max_labels_count",
        accepts: Accepts::Exact(PineType::new(Qualifier::Const, ValueKind::Int)),
        optional: true,
    },
    BuiltinParam {
        name: "max_boxes_count",
        accepts: Accepts::Exact(PineType::new(Qualifier::Const, ValueKind::Int)),
        optional: true,
    },
    BuiltinParam {
        name: "max_lines_count",
        accepts: Accepts::Exact(PineType::new(Qualifier::Const, ValueKind::Int)),
        optional: true,
    },
    BuiltinParam {
        name: "max_polylines_count",
        accepts: Accepts::Exact(PineType::new(Qualifier::Const, ValueKind::Int)),
        optional: true,
    },
    BuiltinParam {
        name: "currency",
        accepts: Accepts::ConstString,
        optional: true,
    },
];

const INPUT_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "defval",
        accepts: Accepts::InputDefval,
        optional: false,
    },
    BuiltinParam {
        name: "title",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "options",
        accepts: Accepts::Tuple,
        optional: true,
    },
    BuiltinParam {
        name: "tooltip",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "inline",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "group",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "confirm",
        accepts: Accepts::ConstBool,
        optional: true,
    },
    BuiltinParam {
        name: "display",
        accepts: Accepts::StringCompatible,
        optional: true,
    },
];

const INPUT_INT_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "defval",
        accepts: Accepts::Exact(PineType::new(Qualifier::Const, ValueKind::Int)),
        optional: false,
    },
    BuiltinParam {
        name: "title",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "minval",
        accepts: Accepts::Exact(PineType::new(Qualifier::Const, ValueKind::Int)),
        optional: true,
    },
    BuiltinParam {
        name: "maxval",
        accepts: Accepts::Exact(PineType::new(Qualifier::Const, ValueKind::Int)),
        optional: true,
    },
    BuiltinParam {
        name: "step",
        accepts: Accepts::Exact(PineType::new(Qualifier::Const, ValueKind::Int)),
        optional: true,
    },
    BuiltinParam {
        name: "options",
        accepts: Accepts::Tuple,
        optional: true,
    },
    BuiltinParam {
        name: "tooltip",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "inline",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "group",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "confirm",
        accepts: Accepts::ConstBool,
        optional: true,
    },
    BuiltinParam {
        name: "display",
        accepts: Accepts::StringCompatible,
        optional: true,
    },
];

const INPUT_FLOAT_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "defval",
        accepts: Accepts::Exact(PineType::new(Qualifier::Const, ValueKind::Float)),
        optional: false,
    },
    BuiltinParam {
        name: "title",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "minval",
        accepts: Accepts::ConstNumeric,
        optional: true,
    },
    BuiltinParam {
        name: "maxval",
        accepts: Accepts::ConstNumeric,
        optional: true,
    },
    BuiltinParam {
        name: "step",
        accepts: Accepts::ConstNumeric,
        optional: true,
    },
    BuiltinParam {
        name: "options",
        accepts: Accepts::Tuple,
        optional: true,
    },
    BuiltinParam {
        name: "tooltip",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "inline",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "group",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "confirm",
        accepts: Accepts::ConstBool,
        optional: true,
    },
    BuiltinParam {
        name: "display",
        accepts: Accepts::StringCompatible,
        optional: true,
    },
];

const INPUT_BOOL_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "defval",
        accepts: Accepts::Exact(PineType::new(Qualifier::Const, ValueKind::Bool)),
        optional: false,
    },
    BuiltinParam {
        name: "title",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "tooltip",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "inline",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "group",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "confirm",
        accepts: Accepts::ConstBool,
        optional: true,
    },
    BuiltinParam {
        name: "display",
        accepts: Accepts::StringCompatible,
        optional: true,
    },
];

const INPUT_COLOR_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "defval",
        accepts: Accepts::Exact(PineType::new(Qualifier::Const, ValueKind::Color)),
        optional: false,
    },
    BuiltinParam {
        name: "title",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "tooltip",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "inline",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "group",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "confirm",
        accepts: Accepts::ConstBool,
        optional: true,
    },
    BuiltinParam {
        name: "display",
        accepts: Accepts::StringCompatible,
        optional: true,
    },
];

const INPUT_STRING_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "defval",
        accepts: Accepts::Exact(PineType::new(Qualifier::Const, ValueKind::String)),
        optional: false,
    },
    BuiltinParam {
        name: "title",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "options",
        accepts: Accepts::Tuple,
        optional: true,
    },
    BuiltinParam {
        name: "tooltip",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "inline",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "group",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "confirm",
        accepts: Accepts::ConstBool,
        optional: true,
    },
    BuiltinParam {
        name: "display",
        accepts: Accepts::StringCompatible,
        optional: true,
    },
];

const INPUT_TEXT_AREA_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "defval",
        accepts: Accepts::Exact(PineType::new(Qualifier::Const, ValueKind::String)),
        optional: false,
    },
    BuiltinParam {
        name: "title",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "tooltip",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "group",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "confirm",
        accepts: Accepts::ConstBool,
        optional: true,
    },
    BuiltinParam {
        name: "display",
        accepts: Accepts::StringCompatible,
        optional: true,
    },
];

const INPUT_SOURCE_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "defval",
        accepts: Accepts::SeriesFloat,
        optional: false,
    },
    BuiltinParam {
        name: "title",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "tooltip",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "inline",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "group",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "confirm",
        accepts: Accepts::ConstBool,
        optional: true,
    },
    BuiltinParam {
        name: "display",
        accepts: Accepts::StringCompatible,
        optional: true,
    },
];

const TYPE_CAST_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "x",
    accepts: Accepts::CastScalar,
    optional: false,
}];

const STRING_CAST_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "x",
    accepts: Accepts::StringCastScalar,
    optional: false,
}];

const COLOR_CAST_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "x",
    accepts: Accepts::ColorCompatible,
    optional: false,
}];

const BOX_CAST_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "x",
    accepts: Accepts::BoxCompatible,
    optional: false,
}];

const LABEL_CAST_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "x",
    accepts: Accepts::LabelCompatible,
    optional: false,
}];

const LINE_CAST_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "x",
    accepts: Accepts::LineCompatible,
    optional: false,
}];

const LINEFILL_CAST_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "x",
    accepts: Accepts::LineFillCompatible,
    optional: false,
}];

const POLYLINE_CAST_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "x",
    accepts: Accepts::PolylineCompatible,
    optional: false,
}];

const TABLE_CAST_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "x",
    accepts: Accepts::TableCompatible,
    optional: false,
}];

const NA_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "x",
    accepts: Accepts::Any,
    optional: false,
}];

const NZ_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "x",
        accepts: Accepts::Any,
        optional: false,
    },
    BuiltinParam {
        name: "replacement",
        accepts: Accepts::Any,
        optional: true,
    },
];

const FIXNAN_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "source",
    accepts: Accepts::NumericOrColorCompatible,
    optional: false,
}];

const MAX_BARS_BACK_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "source",
        accepts: Accepts::SeriesNumeric,
        optional: false,
    },
    BuiltinParam {
        name: "num",
        accepts: Accepts::Exact(PineType::new(Qualifier::Const, ValueKind::Int)),
        optional: false,
    },
];

const RUNTIME_ERROR_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "message",
    accepts: Accepts::StringCompatible,
    optional: false,
}];

pub(crate) const SCRIPT_SIGNATURES: &[BuiltinSignature] = &[
    BuiltinSignature {
        name: "indicator",
        phase: BuiltinPhase::Phase1Core,
        params: INDICATOR_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "strategy",
        phase: BuiltinPhase::Phase1Core,
        params: STRATEGY_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "max_bars_back",
        phase: BuiltinPhase::Phase1Core,
        params: MAX_BARS_BACK_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "runtime.error",
        phase: BuiltinPhase::Phase1Core,
        params: RUNTIME_ERROR_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "input",
        phase: BuiltinPhase::Phase1Core,
        params: INPUT_PARAMS,
        returns: ReturnSpec::InputFromArg(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "input.int",
        phase: BuiltinPhase::Phase1Core,
        params: INPUT_INT_PARAMS,
        returns: ReturnSpec::Fixed(INPUT_INT),
        variadic: false,
    },
    BuiltinSignature {
        name: "input.float",
        phase: BuiltinPhase::Phase1Core,
        params: INPUT_FLOAT_PARAMS,
        returns: ReturnSpec::Fixed(INPUT_FLOAT),
        variadic: false,
    },
    BuiltinSignature {
        name: "input.bool",
        phase: BuiltinPhase::Phase1Core,
        params: INPUT_BOOL_PARAMS,
        returns: ReturnSpec::Fixed(INPUT_BOOL),
        variadic: false,
    },
    BuiltinSignature {
        name: "input.source",
        phase: BuiltinPhase::Phase1Core,
        params: INPUT_SOURCE_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_FLOAT),
        variadic: false,
    },
    BuiltinSignature {
        name: "input.color",
        phase: BuiltinPhase::Phase1Core,
        params: INPUT_COLOR_PARAMS,
        returns: ReturnSpec::Fixed(INPUT_COLOR),
        variadic: false,
    },
    BuiltinSignature {
        name: "input.string",
        phase: BuiltinPhase::Phase1Core,
        params: INPUT_STRING_PARAMS,
        returns: ReturnSpec::Fixed(INPUT_STRING),
        variadic: false,
    },
    BuiltinSignature {
        name: "input.price",
        phase: BuiltinPhase::Phase1Core,
        params: INPUT_FLOAT_PARAMS,
        returns: ReturnSpec::Fixed(INPUT_FLOAT),
        variadic: false,
    },
    BuiltinSignature {
        name: "input.time",
        phase: BuiltinPhase::Phase1Core,
        params: INPUT_INT_PARAMS,
        returns: ReturnSpec::Fixed(INPUT_INT),
        variadic: false,
    },
    BuiltinSignature {
        name: "input.symbol",
        phase: BuiltinPhase::Phase1Core,
        params: INPUT_STRING_PARAMS,
        returns: ReturnSpec::Fixed(INPUT_STRING),
        variadic: false,
    },
    BuiltinSignature {
        name: "input.timeframe",
        phase: BuiltinPhase::Phase1Core,
        params: INPUT_STRING_PARAMS,
        returns: ReturnSpec::Fixed(INPUT_STRING),
        variadic: false,
    },
    BuiltinSignature {
        name: "input.session",
        phase: BuiltinPhase::Phase1Core,
        params: INPUT_STRING_PARAMS,
        returns: ReturnSpec::Fixed(INPUT_STRING),
        variadic: false,
    },
    BuiltinSignature {
        name: "input.text_area",
        phase: BuiltinPhase::Phase1Core,
        params: INPUT_TEXT_AREA_PARAMS,
        returns: ReturnSpec::Fixed(INPUT_STRING),
        variadic: false,
    },
];

pub(crate) const CAST_SIGNATURES: &[BuiltinSignature] = &[
    BuiltinSignature {
        name: "int",
        phase: BuiltinPhase::Phase1Core,
        params: TYPE_CAST_PARAMS,
        returns: ReturnSpec::IntFromArg(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "float",
        phase: BuiltinPhase::Phase1Core,
        params: TYPE_CAST_PARAMS,
        returns: ReturnSpec::FloatFromArg(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "bool",
        phase: BuiltinPhase::Phase1Core,
        params: TYPE_CAST_PARAMS,
        returns: ReturnSpec::BoolFromArg(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "string",
        phase: BuiltinPhase::Phase1Core,
        params: STRING_CAST_PARAMS,
        returns: ReturnSpec::PromotedString,
        variadic: false,
    },
    BuiltinSignature {
        name: "color",
        phase: BuiltinPhase::Phase1Core,
        params: COLOR_CAST_PARAMS,
        returns: ReturnSpec::ColorFromArg(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "box",
        phase: BuiltinPhase::Phase1Core,
        params: BOX_CAST_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_BOX),
        variadic: false,
    },
    BuiltinSignature {
        name: "label",
        phase: BuiltinPhase::Phase1Core,
        params: LABEL_CAST_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_LABEL),
        variadic: false,
    },
    BuiltinSignature {
        name: "line",
        phase: BuiltinPhase::Phase1Core,
        params: LINE_CAST_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_LINE),
        variadic: false,
    },
    BuiltinSignature {
        name: "linefill",
        phase: BuiltinPhase::Phase1Core,
        params: LINEFILL_CAST_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_LINE_FILL),
        variadic: false,
    },
    BuiltinSignature {
        name: "polyline",
        phase: BuiltinPhase::Phase1Core,
        params: POLYLINE_CAST_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_POLYLINE),
        variadic: false,
    },
    BuiltinSignature {
        name: "table",
        phase: BuiltinPhase::Phase1Core,
        params: TABLE_CAST_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_TABLE),
        variadic: false,
    },
];

pub(crate) const VALUE_SIGNATURES: &[BuiltinSignature] = &[
    BuiltinSignature {
        name: "na",
        phase: BuiltinPhase::Phase1Core,
        params: NA_PARAMS,
        returns: ReturnSpec::BoolFromArg(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "nz",
        phase: BuiltinPhase::Phase1Core,
        params: NZ_PARAMS,
        returns: ReturnSpec::SameAsArg(0),
        variadic: false,
    },
    BuiltinSignature {
        name: "fixnan",
        phase: BuiltinPhase::Phase1Core,
        params: FIXNAN_PARAMS,
        returns: ReturnSpec::SameAsArg(0),
        variadic: false,
    },
];
