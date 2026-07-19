use crate::PineValue;

#[derive(Debug, Clone, PartialEq)]
pub struct LabelOutput {
    pub id: u32,
    pub snapshots: Vec<LabelSnapshot>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct LabelSnapshot {
    pub bar_index: usize,
    pub exists: bool,
    pub x: PineValue,
    pub y: PineValue,
    pub text: PineValue,
    pub xloc: PineValue,
    pub yloc: PineValue,
    pub color: PineValue,
    pub style: PineValue,
    pub text_color: PineValue,
    pub size: PineValue,
    pub tooltip: PineValue,
    pub text_align: PineValue,
    pub text_font_family: PineValue,
    pub text_formatting: PineValue,
}

#[derive(Debug, Clone, PartialEq)]
pub struct LineOutput {
    pub id: u32,
    pub snapshots: Vec<LineSnapshot>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct LineSnapshot {
    pub bar_index: usize,
    pub exists: bool,
    pub x1: PineValue,
    pub y1: PineValue,
    pub x2: PineValue,
    pub y2: PineValue,
    pub xloc: PineValue,
    pub color: PineValue,
    pub width: PineValue,
    pub style: PineValue,
    pub extend: PineValue,
}

#[derive(Debug, Clone, PartialEq)]
pub struct LineFillOutput {
    pub id: u32,
    pub snapshots: Vec<LineFillSnapshot>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct LineFillSnapshot {
    pub bar_index: usize,
    pub exists: bool,
    pub line1: u32,
    pub line2: u32,
    pub color: PineValue,
}

#[derive(Debug, Clone, PartialEq)]
pub struct PolylineOutput {
    pub id: u32,
    pub snapshots: Vec<PolylineSnapshot>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct PolylineSnapshot {
    pub bar_index: usize,
    pub exists: bool,
    pub points: Vec<PineValue>,
    pub curved: PineValue,
    pub closed: PineValue,
    pub xloc: PineValue,
    pub line_color: PineValue,
    pub fill_color: PineValue,
    pub line_style: PineValue,
    pub line_width: PineValue,
    pub force_overlay: PineValue,
}

#[derive(Debug, Clone, PartialEq)]
pub struct BoxOutput {
    pub id: u32,
    pub snapshots: Vec<BoxSnapshot>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct BoxSnapshot {
    pub bar_index: usize,
    pub exists: bool,
    pub left: PineValue,
    pub top: PineValue,
    pub right: PineValue,
    pub bottom: PineValue,
    pub xloc: PineValue,
    pub bg_color: PineValue,
    pub border_color: PineValue,
    pub border_width: PineValue,
    pub border_style: PineValue,
    pub extend: PineValue,
    pub text: PineValue,
    pub text_color: PineValue,
    pub text_size: PineValue,
    pub text_halign: PineValue,
    pub text_valign: PineValue,
    pub text_wrap: PineValue,
    pub text_font_family: PineValue,
    pub text_formatting: PineValue,
}

#[derive(Debug, Clone, PartialEq)]
pub struct TableOutput {
    pub id: u32,
    pub position: PineValue,
    pub bg_color: PineValue,
    pub frame_color: PineValue,
    pub frame_width: PineValue,
    pub border_color: PineValue,
    pub border_width: PineValue,
    pub columns: i64,
    pub rows: i64,
    pub snapshots: Vec<TableSnapshot>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct TableSnapshot {
    pub bar_index: usize,
    pub exists: bool,
    pub cells: Vec<TableCellSnapshot>,
    pub merged_cells: Vec<TableMergedCellSnapshot>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct TableMergedCellSnapshot {
    pub start_column: i64,
    pub start_row: i64,
    pub end_column: i64,
    pub end_row: i64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct TableCellSnapshot {
    pub column: i64,
    pub row: i64,
    pub text: PineValue,
    pub bg_color: PineValue,
    pub text_color: PineValue,
    pub width: PineValue,
    pub height: PineValue,
    pub text_size: PineValue,
    pub text_halign: PineValue,
    pub text_valign: PineValue,
    pub text_wrap: PineValue,
    pub tooltip: PineValue,
    pub text_font_family: PineValue,
    pub text_formatting: PineValue,
}
