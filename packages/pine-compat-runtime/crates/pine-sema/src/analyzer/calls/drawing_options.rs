use crate::prelude::*;

use super::Analyzer;

const LABEL_STYLES: &[&str] = &[
    "label.style_none",
    "label.style_xcross",
    "label.style_cross",
    "label.style_triangleup",
    "label.style_triangledown",
    "label.style_flag",
    "label.style_circle",
    "label.style_square",
    "label.style_diamond",
    "label.style_arrowup",
    "label.style_arrowdown",
    "label.style_label_up",
    "label.style_label_down",
    "label.style_label_left",
    "label.style_label_right",
    "label.style_label_lower_left",
    "label.style_label_lower_right",
    "label.style_label_upper_left",
    "label.style_label_upper_right",
    "label.style_label_center",
];
const LABEL_SIZES: &[&str] = &[
    "size.auto",
    "size.tiny",
    "size.small",
    "size.normal",
    "size.large",
    "size.huge",
];
const LABEL_XLOCS: &[&str] = &["xloc.bar_index", "xloc.bar_time"];
const LINE_XLOCS: &[&str] = &["xloc.bar_index", "xloc.bar_time"];
const BOX_XLOCS: &[&str] = &["xloc.bar_index", "xloc.bar_time"];
const LABEL_YLOCS: &[&str] = &["yloc.price", "yloc.abovebar", "yloc.belowbar"];
const LINE_STYLES: &[&str] = &[
    "line.style_solid",
    "line.style_dotted",
    "line.style_dashed",
    "line.style_arrow_left",
    "line.style_arrow_right",
    "line.style_arrow_both",
];

const BOX_BORDER_STYLES: &[&str] = &["line.style_solid", "line.style_dotted", "line.style_dashed"];

const LINE_EXTENDS: &[&str] = &["extend.none", "extend.right", "extend.left", "extend.both"];

const TEXT_HALIGNS: &[&str] = &["text.align_left", "text.align_center", "text.align_right"];

const TEXT_VALIGNS: &[&str] = &["text.align_top", "text.align_center", "text.align_bottom"];

const TEXT_WRAPS: &[&str] = &["text.wrap_none", "text.wrap_auto"];

const TEXT_FONT_FAMILIES: &[&str] = &["font.family_default", "font.family_monospace"];

const TABLE_POSITIONS: &[&str] = &[
    "position.top_left",
    "position.top_center",
    "position.top_right",
    "position.middle_left",
    "position.middle_center",
    "position.middle_right",
    "position.bottom_left",
    "position.bottom_center",
    "position.bottom_right",
];

impl Analyzer {
    pub(crate) fn validate_drawing_option_args(
        &mut self,
        signature: &BuiltinSignature,
        args: &[CallArg],
    ) {
        match signature.name {
            "label.new" => {
                self.validate_label_string_arg(signature, args, 3, "xloc", LABEL_XLOCS);
                self.validate_label_string_arg(signature, args, 4, "yloc", LABEL_YLOCS);
                self.validate_label_string_arg(signature, args, 6, "style", LABEL_STYLES);
                self.validate_text_size_arg(signature, args, 8, "size");
                self.validate_label_string_arg(signature, args, 9, "textalign", TEXT_HALIGNS);
                self.validate_label_string_arg(
                    signature,
                    args,
                    11,
                    "text_font_family",
                    TEXT_FONT_FAMILIES,
                );
                self.validate_text_formatting_arg(signature, args, 13, "text_formatting");
            }
            "label.set_style" => {
                self.validate_label_string_arg(signature, args, 1, "style", LABEL_STYLES);
            }
            "label.set_size" => {
                self.validate_text_size_arg(signature, args, 1, "size");
            }
            "label.set_textalign" => {
                self.validate_label_string_arg(signature, args, 1, "textalign", TEXT_HALIGNS);
            }
            "label.set_text_font_family" => {
                self.validate_label_string_arg(
                    signature,
                    args,
                    1,
                    "text_font_family",
                    TEXT_FONT_FAMILIES,
                );
            }
            "label.set_text_formatting" => {
                self.validate_text_formatting_arg(signature, args, 1, "text_formatting");
            }
            "label.set_xloc" => {
                self.validate_label_string_arg(signature, args, 2, "xloc", LABEL_XLOCS);
            }
            "label.set_yloc" => {
                self.validate_label_string_arg(signature, args, 1, "yloc", LABEL_YLOCS);
            }
            "line.new" => {
                self.validate_label_string_arg(signature, args, 4, "xloc", LINE_XLOCS);
                self.validate_label_string_arg(signature, args, 5, "extend", LINE_EXTENDS);
                self.validate_label_string_arg(signature, args, 7, "style", LINE_STYLES);
            }
            "box.new" => {
                self.validate_label_string_arg(
                    signature,
                    args,
                    6,
                    "border_style",
                    BOX_BORDER_STYLES,
                );
                self.validate_label_string_arg(signature, args, 7, "extend", LINE_EXTENDS);
                self.validate_label_string_arg(signature, args, 8, "xloc", BOX_XLOCS);
                self.validate_text_size_arg(signature, args, 11, "text_size");
                self.validate_label_string_arg(signature, args, 13, "text_halign", TEXT_HALIGNS);
                self.validate_label_string_arg(signature, args, 14, "text_valign", TEXT_VALIGNS);
                self.validate_label_string_arg(signature, args, 15, "text_wrap", TEXT_WRAPS);
                self.validate_label_string_arg(
                    signature,
                    args,
                    16,
                    "text_font_family",
                    TEXT_FONT_FAMILIES,
                );
                self.validate_text_formatting_arg(signature, args, 18, "text_formatting");
            }
            "line.set_style" => {
                self.validate_label_string_arg(signature, args, 1, "style", LINE_STYLES);
            }
            "line.set_extend" => {
                self.validate_label_string_arg(signature, args, 1, "extend", LINE_EXTENDS);
            }
            "line.set_xloc" => {
                self.validate_label_string_arg(signature, args, 3, "xloc", LINE_XLOCS);
            }
            "box.set_extend" => {
                self.validate_label_string_arg(signature, args, 1, "extend", LINE_EXTENDS);
            }
            "box.set_xloc" => {
                self.validate_label_string_arg(signature, args, 3, "xloc", BOX_XLOCS);
            }
            "box.set_border_style" => {
                self.validate_label_string_arg(signature, args, 1, "style", BOX_BORDER_STYLES);
            }
            "box.set_text_size" => {
                self.validate_text_size_arg(signature, args, 1, "text_size");
            }
            "box.set_text_halign" => {
                self.validate_label_string_arg(signature, args, 1, "text_halign", TEXT_HALIGNS);
            }
            "box.set_text_valign" => {
                self.validate_label_string_arg(signature, args, 1, "text_valign", TEXT_VALIGNS);
            }
            "box.set_text_wrap" => {
                self.validate_label_string_arg(signature, args, 1, "text_wrap", TEXT_WRAPS);
            }
            "box.set_text_font_family" => {
                self.validate_label_string_arg(
                    signature,
                    args,
                    1,
                    "text_font_family",
                    TEXT_FONT_FAMILIES,
                );
            }
            "box.set_text_formatting" => {
                self.validate_text_formatting_arg(signature, args, 1, "text_formatting");
            }
            "table.new" => {
                self.validate_label_string_arg(signature, args, 0, "position", TABLE_POSITIONS);
            }
            "table.set_position" => {
                self.validate_label_string_arg(signature, args, 1, "position", TABLE_POSITIONS);
            }
            "table.cell_set_text_halign" => {
                self.validate_label_string_arg(signature, args, 3, "text_halign", TEXT_HALIGNS);
            }
            "table.cell_set_text_valign" => {
                self.validate_label_string_arg(signature, args, 3, "text_valign", TEXT_VALIGNS);
            }
            "table.cell_set_text_wrap" => {
                self.validate_label_string_arg(signature, args, 3, "text_wrap", TEXT_WRAPS);
            }
            "table.cell_set_text_size" => {
                self.validate_text_size_arg(signature, args, 3, "text_size");
            }
            "table.cell" => {
                self.validate_label_string_arg(signature, args, 7, "text_halign", TEXT_HALIGNS);
                self.validate_label_string_arg(signature, args, 8, "text_valign", TEXT_VALIGNS);
                self.validate_text_size_arg(signature, args, 9, "text_size");
                self.validate_label_string_arg(
                    signature,
                    args,
                    12,
                    "text_font_family",
                    TEXT_FONT_FAMILIES,
                );
                self.validate_text_formatting_arg(signature, args, 13, "text_formatting");
            }
            "table.cell_set_text_font_family" => {
                self.validate_label_string_arg(
                    signature,
                    args,
                    3,
                    "text_font_family",
                    TEXT_FONT_FAMILIES,
                );
            }
            "table.cell_set_text_formatting" => {
                self.validate_text_formatting_arg(signature, args, 3, "text_formatting");
            }
            _ => {}
        }
    }

    fn validate_text_formatting_arg(
        &mut self,
        signature: &BuiltinSignature,
        args: &[CallArg],
        index: usize,
        name: &str,
    ) {
        for (arg_index, arg) in args.iter().enumerate() {
            let is_target = arg.name.as_deref() == Some(name)
                || (arg.name.is_none()
                    && signature
                        .params
                        .get(arg_index)
                        .is_some_and(|param| param.name == name && index == arg_index));
            if !is_target {
                continue;
            }
            let Some(value) = self.known_strict_const_int_for_validation(&arg.value) else {
                continue;
            };
            if match value {
                Ok(value) => !(0..=3).contains(&value),
                Err(()) => true,
            } {
                self.diagnostics.push(Diagnostic::error(
                    "E_CALL_ARG_VALUE",
                    format!(
                        "`{}` argument `{name}` only supports text.format_none, text.format_bold, text.format_italic, or text.format_bold + text.format_italic",
                        signature.name
                    ),
                    arg.span,
                ));
            }
        }
    }

    fn validate_text_size_arg(
        &mut self,
        signature: &BuiltinSignature,
        args: &[CallArg],
        index: usize,
        name: &str,
    ) {
        for (arg_index, arg) in args.iter().enumerate() {
            let is_target = arg.name.as_deref() == Some(name)
                || (arg.name.is_none()
                    && signature
                        .params
                        .get(arg_index)
                        .is_some_and(|param| param.name == name && index == arg_index));
            if !is_target {
                continue;
            }
            let Some(value) = self.known_const_string_value(&arg.value) else {
                continue;
            };
            if !LABEL_SIZES
                .iter()
                .any(|allowed_value| *allowed_value == value)
            {
                self.diagnostics.push(Diagnostic::error(
                    "E_CALL_ARG_VALUE",
                    format!(
                        "`{}` argument `{name}` only supports {} or int sizes",
                        signature.name,
                        LABEL_SIZES.join(", ")
                    ),
                    arg.span,
                ));
            }
        }
    }
}
