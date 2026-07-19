use crate::signature::{Accepts, BuiltinParam, BuiltinPhase, BuiltinSignature, ReturnSpec};

use super::types::*;

pub(crate) mod tables;

const fn param(name: &'static str, accepts: Accepts, optional: bool) -> BuiltinParam {
    BuiltinParam {
        name,
        accepts,
        optional,
    }
}

const LABEL_NEW_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "x",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "y",
        accepts: Accepts::NumericCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "text",
        accepts: Accepts::StringCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "xloc",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "yloc",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "color",
        accepts: Accepts::ColorCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "style",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "textcolor",
        accepts: Accepts::ColorCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "size",
        accepts: Accepts::StringOrIntCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "textalign",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "tooltip",
        accepts: Accepts::StringCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "text_font_family",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "force_overlay",
        accepts: Accepts::ConstBool,
        optional: true,
    },
    BuiltinParam {
        name: "text_formatting",
        accepts: Accepts::IntCompatible,
        optional: true,
    },
];

const LABEL_NEW_POINT_PARAMS: &[BuiltinParam] = &[
    param("point", Accepts::ChartPointCompatible, false),
    param("text", Accepts::StringCompatible, true),
    param("xloc", Accepts::ConstString, true),
    param("yloc", Accepts::ConstString, true),
    param("color", Accepts::ColorCompatible, true),
    param("style", Accepts::ConstString, true),
    param("textcolor", Accepts::ColorCompatible, true),
    param("size", Accepts::StringOrIntCompatible, true),
    param("textalign", Accepts::ConstString, true),
    param("tooltip", Accepts::StringCompatible, true),
    param("text_font_family", Accepts::ConstString, true),
    param("force_overlay", Accepts::ConstBool, true),
    param("text_formatting", Accepts::IntCompatible, true),
];

const LABEL_SET_X_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::LabelCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "x",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
];

const LABEL_SET_XLOC_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::LabelCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "x",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "xloc",
        accepts: Accepts::ConstString,
        optional: false,
    },
];

const LABEL_SET_Y_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::LabelCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "y",
        accepts: Accepts::NumericCompatible,
        optional: false,
    },
];

const LABEL_SET_XY_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::LabelCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "x",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "y",
        accepts: Accepts::NumericCompatible,
        optional: false,
    },
];

const LABEL_SET_POINT_PARAMS: &[BuiltinParam] = &[
    param("id", Accepts::LabelCompatible, false),
    param("point", Accepts::ChartPointCompatible, false),
];

const LABEL_SET_YLOC_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::LabelCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "yloc",
        accepts: Accepts::ConstString,
        optional: false,
    },
];

const LABEL_SET_TEXT_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::LabelCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "text",
        accepts: Accepts::StringCompatible,
        optional: false,
    },
];

const LABEL_SET_COLOR_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::LabelCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "color",
        accepts: Accepts::ColorCompatible,
        optional: false,
    },
];

const LABEL_SET_TEXTCOLOR_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::LabelCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "textcolor",
        accepts: Accepts::ColorCompatible,
        optional: false,
    },
];

const LABEL_SET_STYLE_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::LabelCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "style",
        accepts: Accepts::ConstString,
        optional: false,
    },
];

const LABEL_SET_SIZE_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::LabelCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "size",
        accepts: Accepts::StringOrIntCompatible,
        optional: false,
    },
];

const LABEL_SET_TOOLTIP_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::LabelCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "tooltip",
        accepts: Accepts::StringCompatible,
        optional: false,
    },
];

const LABEL_SET_TEXTALIGN_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::LabelCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "textalign",
        accepts: Accepts::ConstString,
        optional: false,
    },
];

const LABEL_SET_TEXT_FONT_FAMILY_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::LabelCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "text_font_family",
        accepts: Accepts::ConstString,
        optional: false,
    },
];

const LABEL_SET_TEXT_FORMATTING_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::LabelCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "text_formatting",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
];

const LABEL_DELETE_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "id",
    accepts: Accepts::LabelCompatible,
    optional: false,
}];

const LABEL_COPY_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "id",
    accepts: Accepts::LabelCompatible,
    optional: false,
}];

const LABEL_GET_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "id",
    accepts: Accepts::LabelCompatible,
    optional: false,
}];

const LINE_NEW_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "x1",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "y1",
        accepts: Accepts::NumericCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "x2",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "y2",
        accepts: Accepts::NumericCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "xloc",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "extend",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "color",
        accepts: Accepts::ColorCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "style",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "width",
        accepts: Accepts::IntCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "force_overlay",
        accepts: Accepts::ConstBool,
        optional: true,
    },
];

const LINE_NEW_POINT_PARAMS: &[BuiltinParam] = &[
    param("first_point", Accepts::ChartPointCompatible, false),
    param("second_point", Accepts::ChartPointCompatible, false),
    param("xloc", Accepts::ConstString, true),
    param("extend", Accepts::ConstString, true),
    param("color", Accepts::ColorCompatible, true),
    param("style", Accepts::ConstString, true),
    param("width", Accepts::IntCompatible, true),
    param("force_overlay", Accepts::ConstBool, true),
];

const LINEFILL_NEW_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "line1",
        accepts: Accepts::LineCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "line2",
        accepts: Accepts::LineCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "color",
        accepts: Accepts::ColorCompatible,
        optional: false,
    },
];

const POLYLINE_NEW_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "points",
        accepts: Accepts::Exact(SIMPLE_CHART_POINT_ARRAY),
        optional: false,
    },
    BuiltinParam {
        name: "curved",
        accepts: Accepts::BoolCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "closed",
        accepts: Accepts::BoolCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "xloc",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "line_color",
        accepts: Accepts::ColorCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "fill_color",
        accepts: Accepts::ColorCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "line_style",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "line_width",
        accepts: Accepts::IntCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "force_overlay",
        accepts: Accepts::ConstBool,
        optional: true,
    },
];

const POLYLINE_DELETE_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "id",
    accepts: Accepts::PolylineCompatible,
    optional: false,
}];

const LINEFILL_SET_COLOR_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::LineFillCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "color",
        accepts: Accepts::ColorCompatible,
        optional: false,
    },
];

const LINEFILL_GET_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "id",
    accepts: Accepts::LineFillCompatible,
    optional: false,
}];

const LINEFILL_DELETE_PARAMS: &[BuiltinParam] = LINEFILL_GET_PARAMS;

const LINE_SET_X_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::LineCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "x",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
];

const LINE_SET_Y_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::LineCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "y",
        accepts: Accepts::NumericCompatible,
        optional: false,
    },
];

const LINE_SET_XY_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::LineCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "x",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "y",
        accepts: Accepts::NumericCompatible,
        optional: false,
    },
];

const LINE_SET_POINT_PARAMS: &[BuiltinParam] = &[
    param("id", Accepts::LineCompatible, false),
    param("point", Accepts::ChartPointCompatible, false),
];

const LINE_SET_XLOC_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::LineCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "x1",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "x2",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "xloc",
        accepts: Accepts::ConstString,
        optional: false,
    },
];

const LINE_SET_COLOR_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::LineCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "color",
        accepts: Accepts::ColorCompatible,
        optional: false,
    },
];

const LINE_SET_WIDTH_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::LineCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "width",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
];

const LINE_SET_STYLE_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::LineCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "style",
        accepts: Accepts::ConstString,
        optional: false,
    },
];

const LINE_SET_EXTEND_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::LineCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "extend",
        accepts: Accepts::ConstString,
        optional: false,
    },
];

const LINE_DELETE_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "id",
    accepts: Accepts::LineCompatible,
    optional: false,
}];

const LINE_COPY_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "id",
    accepts: Accepts::LineCompatible,
    optional: false,
}];

const LINE_GET_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "id",
    accepts: Accepts::LineCompatible,
    optional: false,
}];

const LINE_GET_PRICE_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::LineCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "x",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
];

const BOX_NEW_POINT_PARAMS: &[BuiltinParam] = &[
    param("top_left", Accepts::ChartPointCompatible, false),
    param("bottom_right", Accepts::ChartPointCompatible, false),
    param("border_color", Accepts::ColorCompatible, true),
    param("border_width", Accepts::IntCompatible, true),
    param("border_style", Accepts::ConstString, true),
    param("extend", Accepts::ConstString, true),
    param("xloc", Accepts::ConstString, true),
    param("bgcolor", Accepts::ColorCompatible, true),
    param("text", Accepts::StringCompatible, true),
    param("text_size", Accepts::StringOrIntCompatible, true),
    param("text_color", Accepts::ColorCompatible, true),
    param("text_halign", Accepts::ConstString, true),
    param("text_valign", Accepts::ConstString, true),
    param("text_wrap", Accepts::ConstString, true),
    param("text_font_family", Accepts::ConstString, true),
    param("force_overlay", Accepts::ConstBool, true),
    param("text_formatting", Accepts::IntCompatible, true),
];

const BOX_NEW_PARAMS: &[BuiltinParam] = &[
    param("left", Accepts::IntCompatible, false),
    param("top", Accepts::NumericCompatible, false),
    param("right", Accepts::IntCompatible, false),
    param("bottom", Accepts::NumericCompatible, false),
    param("border_color", Accepts::ColorCompatible, true),
    param("border_width", Accepts::IntCompatible, true),
    param("border_style", Accepts::ConstString, true),
    param("extend", Accepts::ConstString, true),
    param("xloc", Accepts::ConstString, true),
    param("bgcolor", Accepts::ColorCompatible, true),
    param("text", Accepts::StringCompatible, true),
    param("text_size", Accepts::StringOrIntCompatible, true),
    param("text_color", Accepts::ColorCompatible, true),
    param("text_halign", Accepts::ConstString, true),
    param("text_valign", Accepts::ConstString, true),
    param("text_wrap", Accepts::ConstString, true),
    param("text_font_family", Accepts::ConstString, true),
    param("force_overlay", Accepts::ConstBool, true),
    param("text_formatting", Accepts::IntCompatible, true),
];

const BOX_SET_X_PARAMS: &[BuiltinParam] = &[
    param("id", Accepts::BoxCompatible, false),
    param("x", Accepts::IntCompatible, false),
];

const BOX_SET_Y_PARAMS: &[BuiltinParam] = &[
    param("id", Accepts::BoxCompatible, false),
    param("y", Accepts::NumericCompatible, false),
];

const BOX_SET_XY_PARAMS: &[BuiltinParam] = &[
    param("id", Accepts::BoxCompatible, false),
    param("x", Accepts::IntCompatible, false),
    param("y", Accepts::NumericCompatible, false),
];

const BOX_SET_POINT_PARAMS: &[BuiltinParam] = &[
    param("id", Accepts::BoxCompatible, false),
    param("point", Accepts::ChartPointCompatible, false),
];

const BOX_SET_XLOC_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::BoxCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "left",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "right",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "xloc",
        accepts: Accepts::ConstString,
        optional: false,
    },
];

const BOX_SET_COLOR_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::BoxCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "color",
        accepts: Accepts::ColorCompatible,
        optional: false,
    },
];

const BOX_SET_BORDER_WIDTH_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::BoxCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "width",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
];

const BOX_SET_BORDER_STYLE_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::BoxCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "style",
        accepts: Accepts::ConstString,
        optional: false,
    },
];

const BOX_SET_EXTEND_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::BoxCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "extend",
        accepts: Accepts::ConstString,
        optional: false,
    },
];

const BOX_SET_TEXT_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::BoxCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "text",
        accepts: Accepts::StringCompatible,
        optional: false,
    },
];

const BOX_SET_TEXT_COLOR_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::BoxCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "text_color",
        accepts: Accepts::ColorCompatible,
        optional: false,
    },
];

const BOX_SET_TEXT_SIZE_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::BoxCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "text_size",
        accepts: Accepts::StringOrIntCompatible,
        optional: false,
    },
];

const BOX_SET_TEXT_HALIGN_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::BoxCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "text_halign",
        accepts: Accepts::ConstString,
        optional: false,
    },
];

const BOX_SET_TEXT_VALIGN_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::BoxCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "text_valign",
        accepts: Accepts::ConstString,
        optional: false,
    },
];

const BOX_SET_TEXT_WRAP_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::BoxCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "text_wrap",
        accepts: Accepts::ConstString,
        optional: false,
    },
];

const BOX_SET_TEXT_FONT_FAMILY_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::BoxCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "text_font_family",
        accepts: Accepts::ConstString,
        optional: false,
    },
];

const BOX_SET_TEXT_FORMATTING_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::BoxCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "text_formatting",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
];

const BOX_DELETE_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "id",
    accepts: Accepts::BoxCompatible,
    optional: false,
}];

const BOX_COPY_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "id",
    accepts: Accepts::BoxCompatible,
    optional: false,
}];

const BOX_GET_PARAMS: &[BuiltinParam] = &[BuiltinParam {
    name: "id",
    accepts: Accepts::BoxCompatible,
    optional: false,
}];

pub(crate) const SIGNATURES: &[BuiltinSignature] = &[
    BuiltinSignature {
        name: "label.new",
        phase: BuiltinPhase::Phase1Core,
        params: LABEL_NEW_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_LABEL),
        variadic: false,
    },
    BuiltinSignature {
        name: "label.new",
        phase: BuiltinPhase::Phase1Core,
        params: LABEL_NEW_POINT_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_LABEL),
        variadic: false,
    },
    BuiltinSignature {
        name: "label.set_x",
        phase: BuiltinPhase::Phase1Core,
        params: LABEL_SET_X_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "label.set_xloc",
        phase: BuiltinPhase::Phase1Core,
        params: LABEL_SET_XLOC_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "label.set_y",
        phase: BuiltinPhase::Phase1Core,
        params: LABEL_SET_Y_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "label.set_xy",
        phase: BuiltinPhase::Phase1Core,
        params: LABEL_SET_XY_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "label.set_point",
        phase: BuiltinPhase::Phase1Core,
        params: LABEL_SET_POINT_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "label.set_yloc",
        phase: BuiltinPhase::Phase1Core,
        params: LABEL_SET_YLOC_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "label.set_text",
        phase: BuiltinPhase::Phase1Core,
        params: LABEL_SET_TEXT_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "label.set_color",
        phase: BuiltinPhase::Phase1Core,
        params: LABEL_SET_COLOR_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "label.set_textcolor",
        phase: BuiltinPhase::Phase1Core,
        params: LABEL_SET_TEXTCOLOR_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "label.set_style",
        phase: BuiltinPhase::Phase1Core,
        params: LABEL_SET_STYLE_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "label.set_size",
        phase: BuiltinPhase::Phase1Core,
        params: LABEL_SET_SIZE_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "label.set_tooltip",
        phase: BuiltinPhase::Phase1Core,
        params: LABEL_SET_TOOLTIP_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "label.set_textalign",
        phase: BuiltinPhase::Phase1Core,
        params: LABEL_SET_TEXTALIGN_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "label.set_text_font_family",
        phase: BuiltinPhase::Phase1Core,
        params: LABEL_SET_TEXT_FONT_FAMILY_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "label.set_text_formatting",
        phase: BuiltinPhase::Phase1Core,
        params: LABEL_SET_TEXT_FORMATTING_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "label.delete",
        phase: BuiltinPhase::Phase1Core,
        params: LABEL_DELETE_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "label.copy",
        phase: BuiltinPhase::Phase1Core,
        params: LABEL_COPY_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_LABEL),
        variadic: false,
    },
    BuiltinSignature {
        name: "label.get_x",
        phase: BuiltinPhase::Phase1Core,
        params: LABEL_GET_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_INT),
        variadic: false,
    },
    BuiltinSignature {
        name: "label.get_y",
        phase: BuiltinPhase::Phase1Core,
        params: LABEL_GET_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_FLOAT),
        variadic: false,
    },
    BuiltinSignature {
        name: "label.get_text",
        phase: BuiltinPhase::Phase1Core,
        params: LABEL_GET_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_STRING),
        variadic: false,
    },
    BuiltinSignature {
        name: "line.new",
        phase: BuiltinPhase::Phase1Core,
        params: LINE_NEW_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_LINE),
        variadic: false,
    },
    BuiltinSignature {
        name: "line.new",
        phase: BuiltinPhase::Phase1Core,
        params: LINE_NEW_POINT_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_LINE),
        variadic: false,
    },
    BuiltinSignature {
        name: "linefill.new",
        phase: BuiltinPhase::Phase1Core,
        params: LINEFILL_NEW_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_LINE_FILL),
        variadic: false,
    },
    BuiltinSignature {
        name: "polyline.new",
        phase: BuiltinPhase::Phase1Core,
        params: POLYLINE_NEW_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_POLYLINE),
        variadic: false,
    },
    BuiltinSignature {
        name: "polyline.delete",
        phase: BuiltinPhase::Phase1Core,
        params: POLYLINE_DELETE_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "linefill.set_color",
        phase: BuiltinPhase::Phase1Core,
        params: LINEFILL_SET_COLOR_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "linefill.get_line1",
        phase: BuiltinPhase::Phase1Core,
        params: LINEFILL_GET_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_LINE),
        variadic: false,
    },
    BuiltinSignature {
        name: "linefill.get_line2",
        phase: BuiltinPhase::Phase1Core,
        params: LINEFILL_GET_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_LINE),
        variadic: false,
    },
    BuiltinSignature {
        name: "linefill.delete",
        phase: BuiltinPhase::Phase1Core,
        params: LINEFILL_DELETE_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "line.set_x1",
        phase: BuiltinPhase::Phase1Core,
        params: LINE_SET_X_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "line.set_first_point",
        phase: BuiltinPhase::Phase1Core,
        params: LINE_SET_POINT_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "line.set_y1",
        phase: BuiltinPhase::Phase1Core,
        params: LINE_SET_Y_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "line.set_xy1",
        phase: BuiltinPhase::Phase1Core,
        params: LINE_SET_XY_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "line.set_x2",
        phase: BuiltinPhase::Phase1Core,
        params: LINE_SET_X_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "line.set_second_point",
        phase: BuiltinPhase::Phase1Core,
        params: LINE_SET_POINT_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "line.set_y2",
        phase: BuiltinPhase::Phase1Core,
        params: LINE_SET_Y_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "line.set_xy2",
        phase: BuiltinPhase::Phase1Core,
        params: LINE_SET_XY_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "line.set_xloc",
        phase: BuiltinPhase::Phase1Core,
        params: LINE_SET_XLOC_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "line.set_color",
        phase: BuiltinPhase::Phase1Core,
        params: LINE_SET_COLOR_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "line.set_width",
        phase: BuiltinPhase::Phase1Core,
        params: LINE_SET_WIDTH_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "line.set_style",
        phase: BuiltinPhase::Phase1Core,
        params: LINE_SET_STYLE_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "line.set_extend",
        phase: BuiltinPhase::Phase1Core,
        params: LINE_SET_EXTEND_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "line.delete",
        phase: BuiltinPhase::Phase1Core,
        params: LINE_DELETE_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "line.copy",
        phase: BuiltinPhase::Phase1Core,
        params: LINE_COPY_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_LINE),
        variadic: false,
    },
    BuiltinSignature {
        name: "line.get_price",
        phase: BuiltinPhase::Phase1Core,
        params: LINE_GET_PRICE_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_FLOAT),
        variadic: false,
    },
    BuiltinSignature {
        name: "line.get_x1",
        phase: BuiltinPhase::Phase1Core,
        params: LINE_GET_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_INT),
        variadic: false,
    },
    BuiltinSignature {
        name: "line.get_y1",
        phase: BuiltinPhase::Phase1Core,
        params: LINE_GET_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_FLOAT),
        variadic: false,
    },
    BuiltinSignature {
        name: "line.get_x2",
        phase: BuiltinPhase::Phase1Core,
        params: LINE_GET_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_INT),
        variadic: false,
    },
    BuiltinSignature {
        name: "line.get_y2",
        phase: BuiltinPhase::Phase1Core,
        params: LINE_GET_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_FLOAT),
        variadic: false,
    },
    BuiltinSignature {
        name: "box.new",
        phase: BuiltinPhase::Phase1Core,
        params: BOX_NEW_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_BOX),
        variadic: false,
    },
    BuiltinSignature {
        name: "box.new",
        phase: BuiltinPhase::Phase1Core,
        params: BOX_NEW_POINT_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_BOX),
        variadic: false,
    },
    BuiltinSignature {
        name: "box.set_left",
        phase: BuiltinPhase::Phase1Core,
        params: BOX_SET_X_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "box.set_top",
        phase: BuiltinPhase::Phase1Core,
        params: BOX_SET_Y_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "box.set_right",
        phase: BuiltinPhase::Phase1Core,
        params: BOX_SET_X_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "box.set_bottom",
        phase: BuiltinPhase::Phase1Core,
        params: BOX_SET_Y_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "box.set_lefttop",
        phase: BuiltinPhase::Phase1Core,
        params: BOX_SET_XY_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "box.set_top_left_point",
        phase: BuiltinPhase::Phase1Core,
        params: BOX_SET_POINT_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "box.set_rightbottom",
        phase: BuiltinPhase::Phase1Core,
        params: BOX_SET_XY_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "box.set_bottom_right_point",
        phase: BuiltinPhase::Phase1Core,
        params: BOX_SET_POINT_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "box.set_bgcolor",
        phase: BuiltinPhase::Phase1Core,
        params: BOX_SET_COLOR_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "box.set_border_color",
        phase: BuiltinPhase::Phase1Core,
        params: BOX_SET_COLOR_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "box.set_border_width",
        phase: BuiltinPhase::Phase1Core,
        params: BOX_SET_BORDER_WIDTH_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "box.set_border_style",
        phase: BuiltinPhase::Phase1Core,
        params: BOX_SET_BORDER_STYLE_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "box.set_extend",
        phase: BuiltinPhase::Phase1Core,
        params: BOX_SET_EXTEND_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "box.set_xloc",
        phase: BuiltinPhase::Phase1Core,
        params: BOX_SET_XLOC_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "box.set_text",
        phase: BuiltinPhase::Phase1Core,
        params: BOX_SET_TEXT_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "box.set_text_color",
        phase: BuiltinPhase::Phase1Core,
        params: BOX_SET_TEXT_COLOR_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "box.set_text_size",
        phase: BuiltinPhase::Phase1Core,
        params: BOX_SET_TEXT_SIZE_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "box.set_text_halign",
        phase: BuiltinPhase::Phase1Core,
        params: BOX_SET_TEXT_HALIGN_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "box.set_text_valign",
        phase: BuiltinPhase::Phase1Core,
        params: BOX_SET_TEXT_VALIGN_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "box.set_text_wrap",
        phase: BuiltinPhase::Phase1Core,
        params: BOX_SET_TEXT_WRAP_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "box.set_text_font_family",
        phase: BuiltinPhase::Phase1Core,
        params: BOX_SET_TEXT_FONT_FAMILY_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "box.set_text_formatting",
        phase: BuiltinPhase::Phase1Core,
        params: BOX_SET_TEXT_FORMATTING_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "box.delete",
        phase: BuiltinPhase::Phase1Core,
        params: BOX_DELETE_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "box.copy",
        phase: BuiltinPhase::Phase1Core,
        params: BOX_COPY_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_BOX),
        variadic: false,
    },
    BuiltinSignature {
        name: "box.get_top",
        phase: BuiltinPhase::Phase1Core,
        params: BOX_GET_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_FLOAT),
        variadic: false,
    },
    BuiltinSignature {
        name: "box.get_bottom",
        phase: BuiltinPhase::Phase1Core,
        params: BOX_GET_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_FLOAT),
        variadic: false,
    },
    BuiltinSignature {
        name: "box.get_left",
        phase: BuiltinPhase::Phase1Core,
        params: BOX_GET_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_INT),
        variadic: false,
    },
    BuiltinSignature {
        name: "box.get_right",
        phase: BuiltinPhase::Phase1Core,
        params: BOX_GET_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_INT),
        variadic: false,
    },
];
