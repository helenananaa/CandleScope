use crate::signature::{Accepts, BuiltinParam, BuiltinPhase, BuiltinSignature, ReturnSpec};

use super::types::*;

const PLOT_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "series",
        accepts: Accepts::SeriesOrSimpleNumeric,
        optional: false,
    },
    BuiltinParam {
        name: "title",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "color",
        accepts: Accepts::ColorCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "linewidth",
        accepts: Accepts::AtMostInputInt,
        optional: true,
    },
    BuiltinParam {
        name: "style",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "trackprice",
        accepts: Accepts::ConstBool,
        optional: true,
    },
    BuiltinParam {
        name: "histbase",
        accepts: Accepts::AtMostInputNumeric,
        optional: true,
    },
    BuiltinParam {
        name: "offset",
        accepts: Accepts::SimpleIntCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "join",
        accepts: Accepts::ConstBool,
        optional: true,
    },
    BuiltinParam {
        name: "editable",
        accepts: Accepts::ConstBool,
        optional: true,
    },
    BuiltinParam {
        name: "show_last",
        accepts: Accepts::AtMostInputInt,
        optional: true,
    },
    BuiltinParam {
        name: "display",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "format",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "precision",
        accepts: Accepts::SimpleIntCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "force_overlay",
        accepts: Accepts::ConstBool,
        optional: true,
    },
];

const COLOR_OUTPUT_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "color",
        accepts: Accepts::ColorCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "title",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "offset",
        accepts: Accepts::SimpleIntCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "editable",
        accepts: Accepts::ConstBool,
        optional: true,
    },
    BuiltinParam {
        name: "show_last",
        accepts: Accepts::AtMostInputInt,
        optional: true,
    },
    BuiltinParam {
        name: "display",
        accepts: Accepts::ConstString,
        optional: true,
    },
];

const PLOTCHAR_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "series",
        accepts: Accepts::SeriesOrSimpleNumericOrBool,
        optional: false,
    },
    BuiltinParam {
        name: "title",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "char",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "color",
        accepts: Accepts::ColorCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "location",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "offset",
        accepts: Accepts::SimpleIntCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "text",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "textcolor",
        accepts: Accepts::ColorCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "editable",
        accepts: Accepts::ConstBool,
        optional: true,
    },
    BuiltinParam {
        name: "size",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "show_last",
        accepts: Accepts::AtMostInputInt,
        optional: true,
    },
    BuiltinParam {
        name: "display",
        accepts: Accepts::ConstString,
        optional: true,
    },
];

const PLOTSHAPE_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "series",
        accepts: Accepts::SeriesOrSimpleNumericOrBool,
        optional: false,
    },
    BuiltinParam {
        name: "title",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "style",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "location",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "color",
        accepts: Accepts::ColorCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "offset",
        accepts: Accepts::SimpleIntCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "text",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "textcolor",
        accepts: Accepts::ColorCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "editable",
        accepts: Accepts::ConstBool,
        optional: true,
    },
    BuiltinParam {
        name: "size",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "show_last",
        accepts: Accepts::AtMostInputInt,
        optional: true,
    },
    BuiltinParam {
        name: "display",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "force_overlay",
        accepts: Accepts::ConstBool,
        optional: true,
    },
];

const PLOTARROW_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "series",
        accepts: Accepts::SeriesOrSimpleNumeric,
        optional: false,
    },
    BuiltinParam {
        name: "title",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "colorup",
        accepts: Accepts::ColorCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "colordown",
        accepts: Accepts::ColorCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "offset",
        accepts: Accepts::SimpleIntCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "minheight",
        accepts: Accepts::SimpleIntCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "maxheight",
        accepts: Accepts::SimpleIntCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "editable",
        accepts: Accepts::ConstBool,
        optional: true,
    },
    BuiltinParam {
        name: "show_last",
        accepts: Accepts::AtMostInputInt,
        optional: true,
    },
    BuiltinParam {
        name: "display",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "force_overlay",
        accepts: Accepts::ConstBool,
        optional: true,
    },
];

const PLOTBAR_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "open",
        accepts: Accepts::SeriesOrSimpleNumeric,
        optional: false,
    },
    BuiltinParam {
        name: "high",
        accepts: Accepts::SeriesOrSimpleNumeric,
        optional: false,
    },
    BuiltinParam {
        name: "low",
        accepts: Accepts::SeriesOrSimpleNumeric,
        optional: false,
    },
    BuiltinParam {
        name: "close",
        accepts: Accepts::SeriesOrSimpleNumeric,
        optional: false,
    },
    BuiltinParam {
        name: "title",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "color",
        accepts: Accepts::ColorCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "editable",
        accepts: Accepts::ConstBool,
        optional: true,
    },
    BuiltinParam {
        name: "show_last",
        accepts: Accepts::AtMostInputInt,
        optional: true,
    },
    BuiltinParam {
        name: "display",
        accepts: Accepts::ConstString,
        optional: true,
    },
];

const PLOTCANDLE_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "open",
        accepts: Accepts::SeriesOrSimpleNumeric,
        optional: false,
    },
    BuiltinParam {
        name: "high",
        accepts: Accepts::SeriesOrSimpleNumeric,
        optional: false,
    },
    BuiltinParam {
        name: "low",
        accepts: Accepts::SeriesOrSimpleNumeric,
        optional: false,
    },
    BuiltinParam {
        name: "close",
        accepts: Accepts::SeriesOrSimpleNumeric,
        optional: false,
    },
    BuiltinParam {
        name: "title",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "color",
        accepts: Accepts::ColorCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "wickcolor",
        accepts: Accepts::ColorCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "editable",
        accepts: Accepts::ConstBool,
        optional: true,
    },
    BuiltinParam {
        name: "show_last",
        accepts: Accepts::AtMostInputInt,
        optional: true,
    },
    BuiltinParam {
        name: "bordercolor",
        accepts: Accepts::ColorCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "display",
        accepts: Accepts::ConstString,
        optional: true,
    },
];

const HLINE_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "price",
        accepts: Accepts::AtMostInputNumeric,
        optional: false,
    },
    BuiltinParam {
        name: "title",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "color",
        accepts: Accepts::AtMostInputColor,
        optional: true,
    },
    BuiltinParam {
        name: "linestyle",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "linewidth",
        accepts: Accepts::AtMostInputInt,
        optional: true,
    },
    BuiltinParam {
        name: "editable",
        accepts: Accepts::ConstBool,
        optional: true,
    },
    BuiltinParam {
        name: "display",
        accepts: Accepts::ConstString,
        optional: true,
    },
];

const FILL_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "plot1",
        accepts: Accepts::PlotOrHLine,
        optional: false,
    },
    BuiltinParam {
        name: "plot2",
        accepts: Accepts::PlotOrHLine,
        optional: false,
    },
    BuiltinParam {
        name: "color",
        accepts: Accepts::ColorCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "title",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "editable",
        accepts: Accepts::ConstBool,
        optional: true,
    },
    BuiltinParam {
        name: "show_last",
        accepts: Accepts::AtMostInputInt,
        optional: true,
    },
    BuiltinParam {
        name: "fillgaps",
        accepts: Accepts::ConstBool,
        optional: true,
    },
    BuiltinParam {
        name: "display",
        accepts: Accepts::ConstString,
        optional: true,
    },
];

pub(crate) const SIGNATURES: &[BuiltinSignature] = &[
    BuiltinSignature {
        name: "plot",
        phase: BuiltinPhase::Phase1Core,
        params: PLOT_PARAMS,
        returns: ReturnSpec::Fixed(PLOT),
        variadic: false,
    },
    BuiltinSignature {
        name: "bgcolor",
        phase: BuiltinPhase::Phase1Core,
        params: COLOR_OUTPUT_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "barcolor",
        phase: BuiltinPhase::Phase1Core,
        params: COLOR_OUTPUT_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "plotchar",
        phase: BuiltinPhase::Phase1Core,
        params: PLOTCHAR_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "plotshape",
        phase: BuiltinPhase::Phase1Core,
        params: PLOTSHAPE_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "plotarrow",
        phase: BuiltinPhase::Phase1Core,
        params: PLOTARROW_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "plotbar",
        phase: BuiltinPhase::Phase1Core,
        params: PLOTBAR_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "plotcandle",
        phase: BuiltinPhase::Phase1Core,
        params: PLOTCANDLE_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "hline",
        phase: BuiltinPhase::Phase1Core,
        params: HLINE_PARAMS,
        returns: ReturnSpec::Fixed(HLINE),
        variadic: false,
    },
    BuiltinSignature {
        name: "fill",
        phase: BuiltinPhase::Phase1Core,
        params: FILL_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
];
