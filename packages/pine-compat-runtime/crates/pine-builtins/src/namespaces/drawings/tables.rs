use crate::signature::{Accepts, BuiltinParam, BuiltinPhase, BuiltinSignature, ReturnSpec};

use super::super::types::*;

const TABLE_NEW_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "position",
        accepts: Accepts::ConstString,
        optional: false,
    },
    BuiltinParam {
        name: "columns",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "rows",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "bgcolor",
        accepts: Accepts::ColorCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "frame_color",
        accepts: Accepts::ColorCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "frame_width",
        accepts: Accepts::IntCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "border_color",
        accepts: Accepts::ColorCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "border_width",
        accepts: Accepts::IntCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "force_overlay",
        accepts: Accepts::ConstBool,
        optional: true,
    },
];

const fn table_param(name: &'static str, accepts: Accepts) -> BuiltinParam {
    BuiltinParam {
        name,
        accepts,
        optional: false,
    }
}

const TABLE_ID_PARAM: BuiltinParam = table_param("id", Accepts::TableCompatible);
const TABLE_DELETE_PARAMS: &[BuiltinParam] = &[TABLE_ID_PARAM];

const TABLE_CLEAR_PARAMS: &[BuiltinParam] = &[
    TABLE_ID_PARAM,
    table_param("start_column", Accepts::IntCompatible),
    table_param("start_row", Accepts::IntCompatible),
    table_param("end_column", Accepts::IntCompatible),
    table_param("end_row", Accepts::IntCompatible),
];

const TABLE_MERGE_CELLS_PARAMS: &[BuiltinParam] = TABLE_CLEAR_PARAMS;

const TABLE_CELL_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::TableCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "column",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "row",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "text",
        accepts: Accepts::StringCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "width",
        accepts: Accepts::NumericCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "height",
        accepts: Accepts::NumericCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "text_color",
        accepts: Accepts::ColorCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "text_halign",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "text_valign",
        accepts: Accepts::ConstString,
        optional: true,
    },
    BuiltinParam {
        name: "text_size",
        accepts: Accepts::StringOrIntCompatible,
        optional: true,
    },
    BuiltinParam {
        name: "bgcolor",
        accepts: Accepts::ColorCompatible,
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
        name: "text_formatting",
        accepts: Accepts::IntCompatible,
        optional: true,
    },
];

const TABLE_SET_POSITION_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::TableCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "position",
        accepts: Accepts::ConstString,
        optional: false,
    },
];

const TABLE_SET_BGCOLOR_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::TableCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "bgcolor",
        accepts: Accepts::ColorCompatible,
        optional: false,
    },
];

const TABLE_SET_FRAME_COLOR_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::TableCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "frame_color",
        accepts: Accepts::ColorCompatible,
        optional: false,
    },
];

const TABLE_SET_FRAME_WIDTH_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::TableCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "frame_width",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
];

const TABLE_SET_BORDER_COLOR_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::TableCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "border_color",
        accepts: Accepts::ColorCompatible,
        optional: false,
    },
];

const TABLE_SET_BORDER_WIDTH_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::TableCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "border_width",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
];

const TABLE_CELL_SET_TEXT_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::TableCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "column",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "row",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "text",
        accepts: Accepts::StringCompatible,
        optional: false,
    },
];

const TABLE_CELL_SET_BGCOLOR_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::TableCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "column",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "row",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "bgcolor",
        accepts: Accepts::ColorCompatible,
        optional: false,
    },
];

const TABLE_CELL_SET_TEXT_COLOR_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::TableCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "column",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "row",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "text_color",
        accepts: Accepts::ColorCompatible,
        optional: false,
    },
];

const TABLE_CELL_SET_WIDTH_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::TableCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "column",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "row",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "width",
        accepts: Accepts::NumericCompatible,
        optional: false,
    },
];

const TABLE_CELL_SET_HEIGHT_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::TableCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "column",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "row",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "height",
        accepts: Accepts::NumericCompatible,
        optional: false,
    },
];

const TABLE_CELL_SET_TEXT_SIZE_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::TableCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "column",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "row",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "text_size",
        accepts: Accepts::StringOrIntCompatible,
        optional: false,
    },
];

const TABLE_CELL_SET_TEXT_HALIGN_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::TableCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "column",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "row",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "text_halign",
        accepts: Accepts::ConstString,
        optional: false,
    },
];

const TABLE_CELL_SET_TEXT_VALIGN_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::TableCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "column",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "row",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "text_valign",
        accepts: Accepts::ConstString,
        optional: false,
    },
];

const TABLE_CELL_SET_TEXT_WRAP_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::TableCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "column",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "row",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "text_wrap",
        accepts: Accepts::ConstString,
        optional: false,
    },
];

const TABLE_CELL_SET_TOOLTIP_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::TableCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "column",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "row",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "tooltip",
        accepts: Accepts::StringCompatible,
        optional: false,
    },
];

const TABLE_CELL_SET_TEXT_FONT_FAMILY_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::TableCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "column",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "row",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "text_font_family",
        accepts: Accepts::ConstString,
        optional: false,
    },
];

const TABLE_CELL_SET_TEXT_FORMATTING_PARAMS: &[BuiltinParam] = &[
    BuiltinParam {
        name: "id",
        accepts: Accepts::TableCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "column",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "row",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    BuiltinParam {
        name: "text_formatting",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
];

pub(crate) const SIGNATURES: &[BuiltinSignature] = &[
    BuiltinSignature {
        name: "table.new",
        phase: BuiltinPhase::Phase1Core,
        params: TABLE_NEW_PARAMS,
        returns: ReturnSpec::Fixed(SERIES_TABLE),
        variadic: false,
    },
    BuiltinSignature {
        name: "table.delete",
        phase: BuiltinPhase::Phase1Core,
        params: TABLE_DELETE_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "table.clear",
        phase: BuiltinPhase::Phase1Core,
        params: TABLE_CLEAR_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "table.merge_cells",
        phase: BuiltinPhase::Phase1Core,
        params: TABLE_MERGE_CELLS_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "table.cell",
        phase: BuiltinPhase::Phase1Core,
        params: TABLE_CELL_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "table.set_position",
        phase: BuiltinPhase::Phase1Core,
        params: TABLE_SET_POSITION_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "table.set_bgcolor",
        phase: BuiltinPhase::Phase1Core,
        params: TABLE_SET_BGCOLOR_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "table.set_frame_color",
        phase: BuiltinPhase::Phase1Core,
        params: TABLE_SET_FRAME_COLOR_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "table.set_frame_width",
        phase: BuiltinPhase::Phase1Core,
        params: TABLE_SET_FRAME_WIDTH_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "table.set_border_color",
        phase: BuiltinPhase::Phase1Core,
        params: TABLE_SET_BORDER_COLOR_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "table.set_border_width",
        phase: BuiltinPhase::Phase1Core,
        params: TABLE_SET_BORDER_WIDTH_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "table.cell_set_text",
        phase: BuiltinPhase::Phase1Core,
        params: TABLE_CELL_SET_TEXT_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "table.cell_set_bgcolor",
        phase: BuiltinPhase::Phase1Core,
        params: TABLE_CELL_SET_BGCOLOR_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "table.cell_set_text_color",
        phase: BuiltinPhase::Phase1Core,
        params: TABLE_CELL_SET_TEXT_COLOR_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "table.cell_set_width",
        phase: BuiltinPhase::Phase1Core,
        params: TABLE_CELL_SET_WIDTH_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "table.cell_set_height",
        phase: BuiltinPhase::Phase1Core,
        params: TABLE_CELL_SET_HEIGHT_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "table.cell_set_text_size",
        phase: BuiltinPhase::Phase1Core,
        params: TABLE_CELL_SET_TEXT_SIZE_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "table.cell_set_text_halign",
        phase: BuiltinPhase::Phase1Core,
        params: TABLE_CELL_SET_TEXT_HALIGN_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "table.cell_set_text_valign",
        phase: BuiltinPhase::Phase1Core,
        params: TABLE_CELL_SET_TEXT_VALIGN_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "table.cell_set_text_wrap",
        phase: BuiltinPhase::Phase1Core,
        params: TABLE_CELL_SET_TEXT_WRAP_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "table.cell_set_tooltip",
        phase: BuiltinPhase::Phase1Core,
        params: TABLE_CELL_SET_TOOLTIP_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "table.cell_set_text_font_family",
        phase: BuiltinPhase::Phase1Core,
        params: TABLE_CELL_SET_TEXT_FONT_FAMILY_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
    BuiltinSignature {
        name: "table.cell_set_text_formatting",
        phase: BuiltinPhase::Phase1Core,
        params: TABLE_CELL_SET_TEXT_FORMATTING_PARAMS,
        returns: ReturnSpec::Fixed(VOID),
        variadic: false,
    },
];
