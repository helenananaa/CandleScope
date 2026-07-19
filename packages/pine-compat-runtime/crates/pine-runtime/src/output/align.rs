use crate::PineValue;

use super::model::{
    PlotArrowSeries, PlotBarSeries, PlotCandleSeries, PlotCharSeries, PlotShapeSeries,
};

pub(crate) trait BarAlignedOutput {
    type Point;

    fn id(&self) -> u32;
    fn new_padded(id: u32, current_bar: usize) -> Self;
    fn len(&self) -> usize;
    fn pad_to(&mut self, current_bar: usize);
    fn push_point(&mut self, point: Self::Point);
    fn update_point(&mut self, point: Self::Point);
    fn push_na_point(&mut self);
}

pub(crate) fn push_bar_aligned_output<T: BarAlignedOutput>(
    outputs: &mut Vec<T>,
    current_bar: usize,
    id: u32,
    point: T::Point,
) {
    if let Some(output) = outputs.iter_mut().find(|output| output.id() == id) {
        output.pad_to(current_bar);
        if output.len() == current_bar {
            output.push_point(point);
        } else {
            output.update_point(point);
        }
    } else {
        let mut output = T::new_padded(id, current_bar);
        output.push_point(point);
        outputs.push(output);
    }
}

pub(crate) fn finalize_bar_aligned_outputs<T: BarAlignedOutput>(
    outputs: &mut [T],
    current_bar: usize,
) {
    for output in outputs {
        output.pad_to(current_bar);
        if output.len() == current_bar {
            output.push_na_point();
        }
    }
}

pub(crate) struct PlotCharPoint {
    pub(crate) value: PineValue,
    pub(crate) char_value: PineValue,
    pub(crate) color: PineValue,
}

impl BarAlignedOutput for PlotCharSeries {
    type Point = PlotCharPoint;

    fn id(&self) -> u32 {
        self.id
    }

    fn new_padded(id: u32, current_bar: usize) -> Self {
        Self {
            id,
            values: vec![PineValue::Na; current_bar],
            chars: vec![PineValue::Na; current_bar],
            colors: vec![PineValue::Na; current_bar],
        }
    }

    fn len(&self) -> usize {
        self.values.len()
    }

    fn pad_to(&mut self, current_bar: usize) {
        while self.values.len() < current_bar {
            self.push_na_point();
        }
    }

    fn push_point(&mut self, point: Self::Point) {
        self.values.push(point.value);
        self.chars.push(point.char_value);
        self.colors.push(point.color);
    }

    fn update_point(&mut self, point: Self::Point) {
        if let Some(current) = self.values.last_mut() {
            *current = point.value;
        }
        if let Some(current) = self.chars.last_mut() {
            *current = point.char_value;
        }
        if let Some(current) = self.colors.last_mut() {
            *current = point.color;
        }
    }

    fn push_na_point(&mut self) {
        self.values.push(PineValue::Na);
        self.chars.push(PineValue::Na);
        self.colors.push(PineValue::Na);
    }
}

pub(crate) struct PlotShapePoint {
    pub(crate) value: PineValue,
    pub(crate) style: PineValue,
    pub(crate) location: PineValue,
    pub(crate) color: PineValue,
    pub(crate) text: PineValue,
    pub(crate) text_color: PineValue,
    pub(crate) size: PineValue,
}

impl BarAlignedOutput for PlotShapeSeries {
    type Point = PlotShapePoint;

    fn id(&self) -> u32 {
        self.id
    }

    fn new_padded(id: u32, current_bar: usize) -> Self {
        Self {
            id,
            values: vec![PineValue::Na; current_bar],
            styles: vec![PineValue::Na; current_bar],
            locations: vec![PineValue::Na; current_bar],
            colors: vec![PineValue::Na; current_bar],
            texts: vec![PineValue::Na; current_bar],
            text_colors: vec![PineValue::Na; current_bar],
            sizes: vec![PineValue::Na; current_bar],
        }
    }

    fn len(&self) -> usize {
        self.values.len()
    }

    fn pad_to(&mut self, current_bar: usize) {
        while self.values.len() < current_bar {
            self.push_na_point();
        }
    }

    fn push_point(&mut self, point: Self::Point) {
        self.values.push(point.value);
        self.styles.push(point.style);
        self.locations.push(point.location);
        self.colors.push(point.color);
        self.texts.push(point.text);
        self.text_colors.push(point.text_color);
        self.sizes.push(point.size);
    }

    fn update_point(&mut self, point: Self::Point) {
        if let Some(current) = self.values.last_mut() {
            *current = point.value;
        }
        if let Some(current) = self.styles.last_mut() {
            *current = point.style;
        }
        if let Some(current) = self.locations.last_mut() {
            *current = point.location;
        }
        if let Some(current) = self.colors.last_mut() {
            *current = point.color;
        }
        if let Some(current) = self.texts.last_mut() {
            *current = point.text;
        }
        if let Some(current) = self.text_colors.last_mut() {
            *current = point.text_color;
        }
        if let Some(current) = self.sizes.last_mut() {
            *current = point.size;
        }
    }

    fn push_na_point(&mut self) {
        self.values.push(PineValue::Na);
        self.styles.push(PineValue::Na);
        self.locations.push(PineValue::Na);
        self.colors.push(PineValue::Na);
        self.texts.push(PineValue::Na);
        self.text_colors.push(PineValue::Na);
        self.sizes.push(PineValue::Na);
    }
}

pub(crate) struct PlotArrowPoint {
    pub(crate) value: PineValue,
    pub(crate) color_up: PineValue,
    pub(crate) color_down: PineValue,
    pub(crate) min_height: PineValue,
    pub(crate) max_height: PineValue,
}

impl BarAlignedOutput for PlotArrowSeries {
    type Point = PlotArrowPoint;

    fn id(&self) -> u32 {
        self.id
    }

    fn new_padded(id: u32, current_bar: usize) -> Self {
        Self {
            id,
            values: vec![PineValue::Na; current_bar],
            color_ups: vec![PineValue::Na; current_bar],
            color_downs: vec![PineValue::Na; current_bar],
            min_heights: vec![PineValue::Na; current_bar],
            max_heights: vec![PineValue::Na; current_bar],
        }
    }

    fn len(&self) -> usize {
        self.values.len()
    }

    fn pad_to(&mut self, current_bar: usize) {
        while self.values.len() < current_bar {
            self.push_na_point();
        }
    }

    fn push_point(&mut self, point: Self::Point) {
        self.values.push(point.value);
        self.color_ups.push(point.color_up);
        self.color_downs.push(point.color_down);
        self.min_heights.push(point.min_height);
        self.max_heights.push(point.max_height);
    }

    fn update_point(&mut self, point: Self::Point) {
        if let Some(current) = self.values.last_mut() {
            *current = point.value;
        }
        if let Some(current) = self.color_ups.last_mut() {
            *current = point.color_up;
        }
        if let Some(current) = self.color_downs.last_mut() {
            *current = point.color_down;
        }
        if let Some(current) = self.min_heights.last_mut() {
            *current = point.min_height;
        }
        if let Some(current) = self.max_heights.last_mut() {
            *current = point.max_height;
        }
    }

    fn push_na_point(&mut self) {
        self.values.push(PineValue::Na);
        self.color_ups.push(PineValue::Na);
        self.color_downs.push(PineValue::Na);
        self.min_heights.push(PineValue::Na);
        self.max_heights.push(PineValue::Na);
    }
}

pub(crate) struct PlotBarPoint {
    pub(crate) open: PineValue,
    pub(crate) high: PineValue,
    pub(crate) low: PineValue,
    pub(crate) close: PineValue,
    pub(crate) color: PineValue,
}

impl BarAlignedOutput for PlotBarSeries {
    type Point = PlotBarPoint;

    fn id(&self) -> u32 {
        self.id
    }

    fn new_padded(id: u32, current_bar: usize) -> Self {
        Self {
            id,
            opens: vec![PineValue::Na; current_bar],
            highs: vec![PineValue::Na; current_bar],
            lows: vec![PineValue::Na; current_bar],
            closes: vec![PineValue::Na; current_bar],
            colors: vec![PineValue::Na; current_bar],
        }
    }

    fn len(&self) -> usize {
        self.opens.len()
    }

    fn pad_to(&mut self, current_bar: usize) {
        while self.opens.len() < current_bar {
            self.push_na_point();
        }
    }

    fn push_point(&mut self, point: Self::Point) {
        self.opens.push(point.open);
        self.highs.push(point.high);
        self.lows.push(point.low);
        self.closes.push(point.close);
        self.colors.push(point.color);
    }

    fn update_point(&mut self, point: Self::Point) {
        if let Some(current) = self.opens.last_mut() {
            *current = point.open;
        }
        if let Some(current) = self.highs.last_mut() {
            *current = point.high;
        }
        if let Some(current) = self.lows.last_mut() {
            *current = point.low;
        }
        if let Some(current) = self.closes.last_mut() {
            *current = point.close;
        }
        if let Some(current) = self.colors.last_mut() {
            *current = point.color;
        }
    }

    fn push_na_point(&mut self) {
        self.opens.push(PineValue::Na);
        self.highs.push(PineValue::Na);
        self.lows.push(PineValue::Na);
        self.closes.push(PineValue::Na);
        self.colors.push(PineValue::Na);
    }
}

pub(crate) struct PlotCandlePoint {
    pub(crate) open: PineValue,
    pub(crate) high: PineValue,
    pub(crate) low: PineValue,
    pub(crate) close: PineValue,
    pub(crate) color: PineValue,
    pub(crate) wick_color: PineValue,
    pub(crate) border_color: PineValue,
}

impl BarAlignedOutput for PlotCandleSeries {
    type Point = PlotCandlePoint;

    fn id(&self) -> u32 {
        self.id
    }

    fn new_padded(id: u32, current_bar: usize) -> Self {
        Self {
            id,
            opens: vec![PineValue::Na; current_bar],
            highs: vec![PineValue::Na; current_bar],
            lows: vec![PineValue::Na; current_bar],
            closes: vec![PineValue::Na; current_bar],
            colors: vec![PineValue::Na; current_bar],
            wick_colors: vec![PineValue::Na; current_bar],
            border_colors: vec![PineValue::Na; current_bar],
        }
    }

    fn len(&self) -> usize {
        self.opens.len()
    }

    fn pad_to(&mut self, current_bar: usize) {
        while self.opens.len() < current_bar {
            self.push_na_point();
        }
    }

    fn push_point(&mut self, point: Self::Point) {
        self.opens.push(point.open);
        self.highs.push(point.high);
        self.lows.push(point.low);
        self.closes.push(point.close);
        self.colors.push(point.color);
        self.wick_colors.push(point.wick_color);
        self.border_colors.push(point.border_color);
    }

    fn update_point(&mut self, point: Self::Point) {
        if let Some(current) = self.opens.last_mut() {
            *current = point.open;
        }
        if let Some(current) = self.highs.last_mut() {
            *current = point.high;
        }
        if let Some(current) = self.lows.last_mut() {
            *current = point.low;
        }
        if let Some(current) = self.closes.last_mut() {
            *current = point.close;
        }
        if let Some(current) = self.colors.last_mut() {
            *current = point.color;
        }
        if let Some(current) = self.wick_colors.last_mut() {
            *current = point.wick_color;
        }
        if let Some(current) = self.border_colors.last_mut() {
            *current = point.border_color;
        }
    }

    fn push_na_point(&mut self) {
        self.opens.push(PineValue::Na);
        self.highs.push(PineValue::Na);
        self.lows.push(PineValue::Na);
        self.closes.push(PineValue::Na);
        self.colors.push(PineValue::Na);
        self.wick_colors.push(PineValue::Na);
        self.border_colors.push(PineValue::Na);
    }
}
