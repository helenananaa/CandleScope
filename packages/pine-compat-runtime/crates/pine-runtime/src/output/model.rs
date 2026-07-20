use crate::PineValue;

use super::alerts::AlertEvent;
use super::drawings::{
    BoxOutput, LabelOutput, LineFillOutput, LineOutput, PolylineOutput, TableOutput,
};
use super::strategy::StrategyResult;

pub const PUBLIC_RUNTIME_SCHEMA_VERSION: u32 = 8;
pub const PUBLIC_MATRIX_SCHEMA_VERSION: u32 = 2;
pub const PUBLIC_OUTPUT_SCHEMA_VERSION: u32 = PUBLIC_RUNTIME_SCHEMA_VERSION;
pub const PUBLIC_RENDER_METADATA_VERSION: u32 = 1;

#[derive(Debug, Clone, PartialEq)]
pub struct RuntimeResult {
    pub plots: Vec<PlotSeries>,
    pub plot_chars: Vec<PlotCharSeries>,
    pub plot_shapes: Vec<PlotShapeSeries>,
    pub plot_arrows: Vec<PlotArrowSeries>,
    pub plot_bars: Vec<PlotBarSeries>,
    pub plot_candles: Vec<PlotCandleSeries>,
    pub bg_colors: Vec<ColorSeries>,
    pub bar_colors: Vec<ColorSeries>,
    pub hlines: Vec<HLineOutput>,
    pub fills: Vec<FillOutput>,
    pub labels: Vec<LabelOutput>,
    pub lines: Vec<LineOutput>,
    pub line_fills: Vec<LineFillOutput>,
    pub polylines: Vec<PolylineOutput>,
    pub boxes: Vec<BoxOutput>,
    pub tables: Vec<TableOutput>,
    pub alerts: Vec<AlertEvent>,
    pub strategy: Option<StrategyResult>,
    pub diagnostics: Vec<RuntimeDiagnostic>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct PlotSeries {
    pub id: u32,
    pub values: Vec<PineValue>,
    pub colors: Vec<PineValue>,
    pub metadata: OutputMetadata,
    pub linewidth: PineValue,
    pub style: PineValue,
    pub track_price: PineValue,
    pub hist_base: PineValue,
    pub join: PineValue,
    pub format: PineValue,
    pub precision: PineValue,
}

impl PlotSeries {
    #[must_use]
    pub fn new(id: u32, values: Vec<PineValue>) -> Self {
        Self {
            id,
            colors: vec![PineValue::Na; values.len()],
            values,
            metadata: OutputMetadata::default(),
            linewidth: PineValue::Int(1),
            style: PineValue::String("plot.style_line".to_owned()),
            track_price: PineValue::Bool(false),
            hist_base: PineValue::Int(0),
            join: PineValue::Bool(false),
            format: PineValue::String("format.inherit".to_owned()),
            precision: PineValue::Na,
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct ColorSeries {
    pub id: u32,
    pub values: Vec<PineValue>,
    pub metadata: OutputMetadata,
}

#[derive(Debug, Clone, PartialEq)]
pub struct PlotCharSeries {
    pub id: u32,
    pub values: Vec<PineValue>,
    pub chars: Vec<PineValue>,
    pub colors: Vec<PineValue>,
    pub locations: Vec<PineValue>,
    pub texts: Vec<PineValue>,
    pub text_colors: Vec<PineValue>,
    pub sizes: Vec<PineValue>,
    pub metadata: OutputMetadata,
}

#[derive(Debug, Clone, PartialEq)]
pub struct PlotShapeSeries {
    pub id: u32,
    pub values: Vec<PineValue>,
    pub styles: Vec<PineValue>,
    pub locations: Vec<PineValue>,
    pub colors: Vec<PineValue>,
    pub texts: Vec<PineValue>,
    pub text_colors: Vec<PineValue>,
    pub sizes: Vec<PineValue>,
    pub metadata: OutputMetadata,
}

#[derive(Debug, Clone, PartialEq)]
pub struct PlotArrowSeries {
    pub id: u32,
    pub values: Vec<PineValue>,
    pub color_ups: Vec<PineValue>,
    pub color_downs: Vec<PineValue>,
    pub min_heights: Vec<PineValue>,
    pub max_heights: Vec<PineValue>,
    pub metadata: OutputMetadata,
}

#[derive(Debug, Clone, PartialEq)]
pub struct PlotBarSeries {
    pub id: u32,
    pub opens: Vec<PineValue>,
    pub highs: Vec<PineValue>,
    pub lows: Vec<PineValue>,
    pub closes: Vec<PineValue>,
    pub colors: Vec<PineValue>,
    pub metadata: OutputMetadata,
}

#[derive(Debug, Clone, PartialEq)]
pub struct PlotCandleSeries {
    pub id: u32,
    pub opens: Vec<PineValue>,
    pub highs: Vec<PineValue>,
    pub lows: Vec<PineValue>,
    pub closes: Vec<PineValue>,
    pub colors: Vec<PineValue>,
    pub wick_colors: Vec<PineValue>,
    pub border_colors: Vec<PineValue>,
    pub metadata: OutputMetadata,
}

#[derive(Debug, Clone, PartialEq)]
pub struct OutputMetadata {
    pub title: PineValue,
    pub offset: PineValue,
    pub editable: PineValue,
    pub show_last: PineValue,
    pub display: PineValue,
    pub force_overlay: PineValue,
}

impl Default for OutputMetadata {
    fn default() -> Self {
        Self {
            title: PineValue::String(String::new()),
            offset: PineValue::Int(0),
            editable: PineValue::Bool(true),
            show_last: PineValue::Na,
            display: PineValue::String("display.all".to_owned()),
            force_overlay: PineValue::Bool(false),
        }
    }
}

pub(crate) trait SeriesOutput: Sized {
    fn new(id: u32, values: Vec<PineValue>) -> Self;
    fn id(&self) -> u32;
    fn values_mut(&mut self) -> &mut Vec<PineValue>;
}

impl SeriesOutput for ColorSeries {
    fn new(id: u32, values: Vec<PineValue>) -> Self {
        Self {
            id,
            values,
            metadata: OutputMetadata::default(),
        }
    }

    fn id(&self) -> u32 {
        self.id
    }

    fn values_mut(&mut self) -> &mut Vec<PineValue> {
        &mut self.values
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct HLineOutput {
    pub id: u32,
    pub price: PineValue,
    pub title: PineValue,
    pub color: PineValue,
    pub style: PineValue,
    pub linewidth: PineValue,
    pub editable: PineValue,
    pub display: PineValue,
}

#[derive(Debug, Clone, PartialEq)]
pub struct FillOutput {
    pub id: u32,
    pub first_id: u32,
    pub second_id: u32,
    pub first_is_hline: bool,
    pub second_is_hline: bool,
    pub colors: Vec<PineValue>,
    pub title: PineValue,
    pub editable: PineValue,
    pub show_last: PineValue,
    pub fill_gaps: PineValue,
    pub display: PineValue,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeDiagnostic {
    pub code: String,
    pub message: String,
}
