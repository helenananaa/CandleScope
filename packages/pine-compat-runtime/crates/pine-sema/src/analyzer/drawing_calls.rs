use crate::analyzer::calls::call_arg_accepts_type_expected_diagnostic;
use crate::prelude::*;

const LINE_XLOCS: &[&str] = &["xloc.bar_index", "xloc.bar_time"];
const LINE_EXTENDS: &[&str] = &["extend.none", "extend.right", "extend.left", "extend.both"];
const BOX_XLOCS: &[&str] = &["xloc.bar_index", "xloc.bar_time"];
const BOX_BORDER_STYLES: &[&str] = &["line.style_solid", "line.style_dotted", "line.style_dashed"];
const TEXT_HALIGNS: &[&str] = &["text.align_left", "text.align_center", "text.align_right"];
const TEXT_VALIGNS: &[&str] = &["text.align_top", "text.align_center", "text.align_bottom"];
const TEXT_WRAPS: &[&str] = &["text.wrap_none", "text.wrap_auto"];
const TEXT_FONT_FAMILIES: &[&str] = &["font.family_default", "font.family_monospace"];
const TEXT_SIZES: &[&str] = &[
    "size.auto",
    "size.tiny",
    "size.small",
    "size.normal",
    "size.large",
    "size.huge",
];
const LINE_STYLES: &[&str] = &[
    "line.style_solid",
    "line.style_dotted",
    "line.style_dashed",
    "line.style_arrow_left",
    "line.style_arrow_right",
    "line.style_arrow_both",
];

const LABEL_XLOCS: &[&str] = &["xloc.bar_index", "xloc.bar_time"];
const LABEL_YLOCS: &[&str] = &["yloc.price", "yloc.abovebar", "yloc.belowbar"];
const LABEL_STYLES: &[&str] = &[
    "label.style_label_down",
    "label.style_label_up",
    "label.style_label_left",
    "label.style_label_right",
    "label.style_label_lower_left",
    "label.style_label_lower_right",
    "label.style_label_upper_left",
    "label.style_label_upper_right",
    "label.style_label_center",
    "label.style_square",
    "label.style_diamond",
    "label.style_circle",
    "label.style_flag",
    "label.style_arrowup",
    "label.style_arrowdown",
    "label.style_cross",
    "label.style_xcross",
    "label.style_none",
];

#[derive(Clone, Copy)]
struct LabelNewParam {
    name: &'static str,
    accepts: Accepts,
    optional: bool,
}

#[derive(Clone, Copy)]
struct LineNewParam {
    name: &'static str,
    accepts: Accepts,
    optional: bool,
}

#[derive(Clone, Copy)]
struct BoxNewParam {
    name: &'static str,
    accepts: Accepts,
    optional: bool,
}

const LABEL_NEW_SCALAR_PARAMS: &[LabelNewParam] = &[
    label_param("x", Accepts::IntCompatible, false),
    label_param("y", Accepts::NumericCompatible, false),
    label_param("text", Accepts::StringCompatible, true),
    label_param("xloc", Accepts::ConstString, true),
    label_param("yloc", Accepts::ConstString, true),
    label_param("color", Accepts::ColorCompatible, true),
    label_param("style", Accepts::ConstString, true),
    label_param("textcolor", Accepts::ColorCompatible, true),
    label_param("size", Accepts::StringOrIntCompatible, true),
    label_param("textalign", Accepts::ConstString, true),
    label_param("tooltip", Accepts::StringCompatible, true),
    label_param("text_font_family", Accepts::ConstString, true),
    label_param("force_overlay", Accepts::ConstBool, true),
    label_param("text_formatting", Accepts::IntCompatible, true),
];

const LABEL_NEW_POINT_PARAMS: &[LabelNewParam] = &[
    label_param("point", Accepts::ChartPointCompatible, false),
    label_param("text", Accepts::StringCompatible, true),
    label_param("xloc", Accepts::ConstString, true),
    label_param("yloc", Accepts::ConstString, true),
    label_param("color", Accepts::ColorCompatible, true),
    label_param("style", Accepts::ConstString, true),
    label_param("textcolor", Accepts::ColorCompatible, true),
    label_param("size", Accepts::StringOrIntCompatible, true),
    label_param("textalign", Accepts::ConstString, true),
    label_param("tooltip", Accepts::StringCompatible, true),
    label_param("text_font_family", Accepts::ConstString, true),
    label_param("force_overlay", Accepts::ConstBool, true),
    label_param("text_formatting", Accepts::IntCompatible, true),
];

const fn label_param(name: &'static str, accepts: Accepts, optional: bool) -> LabelNewParam {
    LabelNewParam {
        name,
        accepts,
        optional,
    }
}

const LINE_NEW_SCALAR_PARAMS: &[LineNewParam] = &[
    LineNewParam {
        name: "x1",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    LineNewParam {
        name: "y1",
        accepts: Accepts::NumericCompatible,
        optional: false,
    },
    LineNewParam {
        name: "x2",
        accepts: Accepts::IntCompatible,
        optional: false,
    },
    LineNewParam {
        name: "y2",
        accepts: Accepts::NumericCompatible,
        optional: false,
    },
    LineNewParam {
        name: "xloc",
        accepts: Accepts::ConstString,
        optional: true,
    },
    LineNewParam {
        name: "extend",
        accepts: Accepts::ConstString,
        optional: true,
    },
    LineNewParam {
        name: "color",
        accepts: Accepts::ColorCompatible,
        optional: true,
    },
    LineNewParam {
        name: "style",
        accepts: Accepts::ConstString,
        optional: true,
    },
    LineNewParam {
        name: "width",
        accepts: Accepts::IntCompatible,
        optional: true,
    },
    LineNewParam {
        name: "force_overlay",
        accepts: Accepts::ConstBool,
        optional: true,
    },
];

const LINE_NEW_POINT_PARAMS: &[LineNewParam] = &[
    LineNewParam {
        name: "first_point",
        accepts: Accepts::ChartPointCompatible,
        optional: false,
    },
    LineNewParam {
        name: "second_point",
        accepts: Accepts::ChartPointCompatible,
        optional: false,
    },
    LineNewParam {
        name: "xloc",
        accepts: Accepts::ConstString,
        optional: true,
    },
    LineNewParam {
        name: "extend",
        accepts: Accepts::ConstString,
        optional: true,
    },
    LineNewParam {
        name: "color",
        accepts: Accepts::ColorCompatible,
        optional: true,
    },
    LineNewParam {
        name: "style",
        accepts: Accepts::ConstString,
        optional: true,
    },
    LineNewParam {
        name: "width",
        accepts: Accepts::IntCompatible,
        optional: true,
    },
    LineNewParam {
        name: "force_overlay",
        accepts: Accepts::ConstBool,
        optional: true,
    },
];

const BOX_NEW_SCALAR_PARAMS: &[BoxNewParam] = &[
    box_param("left", Accepts::IntCompatible, false),
    box_param("top", Accepts::NumericCompatible, false),
    box_param("right", Accepts::IntCompatible, false),
    box_param("bottom", Accepts::NumericCompatible, false),
    box_param("border_color", Accepts::ColorCompatible, true),
    box_param("border_width", Accepts::IntCompatible, true),
    box_param("border_style", Accepts::ConstString, true),
    box_param("extend", Accepts::ConstString, true),
    box_param("xloc", Accepts::ConstString, true),
    box_param("bgcolor", Accepts::ColorCompatible, true),
    box_param("text", Accepts::StringCompatible, true),
    box_param("text_size", Accepts::StringOrIntCompatible, true),
    box_param("text_color", Accepts::ColorCompatible, true),
    box_param("text_halign", Accepts::ConstString, true),
    box_param("text_valign", Accepts::ConstString, true),
    box_param("text_wrap", Accepts::ConstString, true),
    box_param("text_font_family", Accepts::ConstString, true),
    box_param("force_overlay", Accepts::ConstBool, true),
    box_param("text_formatting", Accepts::IntCompatible, true),
];

const BOX_NEW_POINT_PARAMS: &[BoxNewParam] = &[
    box_param("top_left", Accepts::ChartPointCompatible, false),
    box_param("bottom_right", Accepts::ChartPointCompatible, false),
    box_param("border_color", Accepts::ColorCompatible, true),
    box_param("border_width", Accepts::IntCompatible, true),
    box_param("border_style", Accepts::ConstString, true),
    box_param("extend", Accepts::ConstString, true),
    box_param("xloc", Accepts::ConstString, true),
    box_param("bgcolor", Accepts::ColorCompatible, true),
    box_param("text", Accepts::StringCompatible, true),
    box_param("text_size", Accepts::StringOrIntCompatible, true),
    box_param("text_color", Accepts::ColorCompatible, true),
    box_param("text_halign", Accepts::ConstString, true),
    box_param("text_valign", Accepts::ConstString, true),
    box_param("text_wrap", Accepts::ConstString, true),
    box_param("text_font_family", Accepts::ConstString, true),
    box_param("force_overlay", Accepts::ConstBool, true),
    box_param("text_formatting", Accepts::IntCompatible, true),
];

const fn box_param(name: &'static str, accepts: Accepts, optional: bool) -> BoxNewParam {
    BoxNewParam {
        name,
        accepts,
        optional,
    }
}

impl Analyzer {
    pub(crate) fn validate_label_new_args(
        &mut self,
        signature: &BuiltinSignature,
        args: &[CallArg],
        arg_types: &[Option<PineType>],
    ) -> bool {
        if signature.name != "label.new" {
            return false;
        }
        let params = if label_new_uses_point_overload(args, arg_types) {
            LABEL_NEW_POINT_PARAMS
        } else {
            LABEL_NEW_SCALAR_PARAMS
        };
        self.validate_label_new_overload(args, arg_types, params);
        true
    }

    pub(crate) fn validate_line_new_args(
        &mut self,
        signature: &BuiltinSignature,
        args: &[CallArg],
        arg_types: &[Option<PineType>],
    ) -> bool {
        if signature.name != "line.new" {
            return false;
        }
        let params = if line_new_uses_point_overload(args, arg_types) {
            LINE_NEW_POINT_PARAMS
        } else {
            LINE_NEW_SCALAR_PARAMS
        };
        self.validate_line_new_overload(args, arg_types, params);
        true
    }

    pub(crate) fn validate_box_new_args(
        &mut self,
        signature: &BuiltinSignature,
        args: &[CallArg],
        arg_types: &[Option<PineType>],
    ) -> bool {
        if signature.name != "box.new" {
            return false;
        }
        let params = if box_new_uses_point_overload(args, arg_types) {
            BOX_NEW_POINT_PARAMS
        } else {
            BOX_NEW_SCALAR_PARAMS
        };
        self.validate_box_new_overload(args, arg_types, params);
        true
    }

    fn validate_label_new_overload(
        &mut self,
        args: &[CallArg],
        arg_types: &[Option<PineType>],
        params: &[LabelNewParam],
    ) {
        let required_count = params.iter().filter(|param| !param.optional).count();
        if args.len() < required_count {
            self.diagnostics.push(Diagnostic::error(
                "E_CALL_ARITY",
                format!(
                    "`label.new` expects at least {required_count} argument(s), got {}",
                    args.len()
                ),
                args.first().map_or(Span::default(), |arg| arg.span),
            ));
            return;
        }
        if args.len() > params.len() {
            self.diagnostics.push(Diagnostic::error(
                "E_CALL_ARITY",
                format!(
                    "`label.new` expects at most {} argument(s), got {}",
                    params.len(),
                    args.len()
                ),
                args[params.len()].span,
            ));
        }
        for (index, arg) in args.iter().enumerate() {
            let Some(param) = label_new_param(params, index, arg, &mut self.diagnostics) else {
                continue;
            };
            let Some(arg_type) = arg_types.get(index).copied().flatten() else {
                continue;
            };
            if let Some(diagnostic) = call_arg_accepts_type_expected_diagnostic(
                "label.new",
                param.name,
                param.accepts,
                arg_type,
                arg.span,
            ) {
                self.diagnostics.push(diagnostic);
            }
        }
        self.validate_label_new_string_arg(args, params, "xloc", LABEL_XLOCS);
        self.validate_label_new_string_arg(args, params, "yloc", LABEL_YLOCS);
        self.validate_label_new_string_arg(args, params, "style", LABEL_STYLES);
        self.validate_label_new_string_arg(args, params, "textalign", TEXT_HALIGNS);
        self.validate_label_new_string_arg(args, params, "text_font_family", TEXT_FONT_FAMILIES);
        self.validate_label_new_text_size_arg(args, params);
        self.validate_label_new_text_formatting_arg(args, params);
    }

    fn validate_label_new_string_arg(
        &mut self,
        args: &[CallArg],
        params: &[LabelNewParam],
        name: &str,
        supported: &[&str],
    ) {
        for (index, arg) in args.iter().enumerate() {
            let Some(param) = label_new_param(params, index, arg, &mut Vec::new()) else {
                continue;
            };
            if param.name != name {
                continue;
            }
            let supported_value = self
                .known_const_string_value(&arg.value)
                .as_deref()
                .is_some_and(|value| supported.contains(&value));
            if !supported_value {
                self.diagnostics.push(Diagnostic::error(
                    "E_CALL_ARG_VALUE",
                    format!(
                        "`label.new` argument `{name}` only supports {}",
                        supported.join(", ")
                    ),
                    arg.span,
                ));
            }
        }
    }

    fn validate_label_new_text_size_arg(&mut self, args: &[CallArg], params: &[LabelNewParam]) {
        for (index, arg) in args.iter().enumerate() {
            let Some(param) = label_new_param(params, index, arg, &mut Vec::new()) else {
                continue;
            };
            if param.name != "size" {
                continue;
            }
            let Some(value) = self.known_const_string_value(&arg.value) else {
                continue;
            };
            if !TEXT_SIZES.iter().any(|allowed| *allowed == value) {
                self.diagnostics.push(Diagnostic::error(
                    "E_CALL_ARG_VALUE",
                    format!(
                        "`label.new` argument `size` only supports {} or int sizes",
                        TEXT_SIZES.join(", ")
                    ),
                    arg.span,
                ));
            }
        }
    }

    fn validate_label_new_text_formatting_arg(
        &mut self,
        args: &[CallArg],
        params: &[LabelNewParam],
    ) {
        for (index, arg) in args.iter().enumerate() {
            let Some(param) = label_new_param(params, index, arg, &mut Vec::new()) else {
                continue;
            };
            if param.name != "text_formatting" {
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
                    "`label.new` argument `text_formatting` only supports text.format_none, text.format_bold, text.format_italic, or text.format_bold + text.format_italic",
                    arg.span,
                ));
            }
        }
    }

    fn validate_line_new_overload(
        &mut self,
        args: &[CallArg],
        arg_types: &[Option<PineType>],
        params: &[LineNewParam],
    ) {
        let required_count = params.iter().filter(|param| !param.optional).count();
        if args.len() < required_count {
            self.diagnostics.push(Diagnostic::error(
                "E_CALL_ARITY",
                format!(
                    "`line.new` expects at least {required_count} argument(s), got {}",
                    args.len()
                ),
                args.first().map_or(Span::default(), |arg| arg.span),
            ));
            return;
        }
        if args.len() > params.len() {
            self.diagnostics.push(Diagnostic::error(
                "E_CALL_ARITY",
                format!(
                    "`line.new` expects at most {} argument(s), got {}",
                    params.len(),
                    args.len()
                ),
                args[params.len()].span,
            ));
        }
        for (index, arg) in args.iter().enumerate() {
            let Some(param) = line_new_param(params, index, arg, &mut self.diagnostics) else {
                continue;
            };
            let Some(arg_type) = arg_types.get(index).copied().flatten() else {
                continue;
            };
            if let Some(diagnostic) = call_arg_accepts_type_expected_diagnostic(
                "line.new",
                param.name,
                param.accepts,
                arg_type,
                arg.span,
            ) {
                self.diagnostics.push(diagnostic);
            }
        }
        self.validate_line_new_string_arg(args, params, "xloc", LINE_XLOCS);
        self.validate_line_new_string_arg(args, params, "extend", LINE_EXTENDS);
        self.validate_line_new_string_arg(args, params, "style", LINE_STYLES);
    }

    fn validate_line_new_string_arg(
        &mut self,
        args: &[CallArg],
        params: &[LineNewParam],
        name: &str,
        supported: &[&str],
    ) {
        for (index, arg) in args.iter().enumerate() {
            let Some(param) = line_new_param(params, index, arg, &mut Vec::new()) else {
                continue;
            };
            if param.name != name {
                continue;
            }
            let supported_value = self
                .known_const_string_value(&arg.value)
                .as_deref()
                .is_some_and(|value| supported.contains(&value));
            if !supported_value {
                self.diagnostics.push(Diagnostic::error(
                    "E_CALL_ARG_VALUE",
                    format!(
                        "`line.new` argument `{name}` only supports {}",
                        supported.join(", ")
                    ),
                    arg.span,
                ));
            }
        }
    }

    fn validate_box_new_overload(
        &mut self,
        args: &[CallArg],
        arg_types: &[Option<PineType>],
        params: &[BoxNewParam],
    ) {
        let required_count = params.iter().filter(|param| !param.optional).count();
        if args.len() < required_count {
            self.diagnostics.push(Diagnostic::error(
                "E_CALL_ARITY",
                format!(
                    "`box.new` expects at least {required_count} argument(s), got {}",
                    args.len()
                ),
                args.first().map_or(Span::default(), |arg| arg.span),
            ));
            return;
        }
        if args.len() > params.len() {
            self.diagnostics.push(Diagnostic::error(
                "E_CALL_ARITY",
                format!(
                    "`box.new` expects at most {} argument(s), got {}",
                    params.len(),
                    args.len()
                ),
                args[params.len()].span,
            ));
        }
        for (index, arg) in args.iter().enumerate() {
            let Some(param) = box_new_param(params, index, arg, &mut self.diagnostics) else {
                continue;
            };
            let Some(arg_type) = arg_types.get(index).copied().flatten() else {
                continue;
            };
            if let Some(diagnostic) = call_arg_accepts_type_expected_diagnostic(
                "box.new",
                param.name,
                param.accepts,
                arg_type,
                arg.span,
            ) {
                self.diagnostics.push(diagnostic);
            }
        }
        self.validate_box_new_string_arg(args, params, "border_style", BOX_BORDER_STYLES);
        self.validate_box_new_string_arg(args, params, "extend", LINE_EXTENDS);
        self.validate_box_new_string_arg(args, params, "xloc", BOX_XLOCS);
        self.validate_box_new_string_arg(args, params, "text_halign", TEXT_HALIGNS);
        self.validate_box_new_string_arg(args, params, "text_valign", TEXT_VALIGNS);
        self.validate_box_new_string_arg(args, params, "text_wrap", TEXT_WRAPS);
        self.validate_box_new_string_arg(args, params, "text_font_family", TEXT_FONT_FAMILIES);
        self.validate_box_new_text_size_arg(args, params);
        self.validate_box_new_text_formatting_arg(args, params);
    }

    fn validate_box_new_string_arg(
        &mut self,
        args: &[CallArg],
        params: &[BoxNewParam],
        name: &str,
        supported: &[&str],
    ) {
        for (index, arg) in args.iter().enumerate() {
            let Some(param) = box_new_param(params, index, arg, &mut Vec::new()) else {
                continue;
            };
            if param.name != name {
                continue;
            }
            let supported_value = self
                .known_const_string_value(&arg.value)
                .as_deref()
                .is_some_and(|value| supported.contains(&value));
            if !supported_value {
                self.diagnostics.push(Diagnostic::error(
                    "E_CALL_ARG_VALUE",
                    format!(
                        "`box.new` argument `{name}` only supports {}",
                        supported.join(", ")
                    ),
                    arg.span,
                ));
            }
        }
    }

    fn validate_box_new_text_size_arg(&mut self, args: &[CallArg], params: &[BoxNewParam]) {
        for (index, arg) in args.iter().enumerate() {
            let Some(param) = box_new_param(params, index, arg, &mut Vec::new()) else {
                continue;
            };
            if param.name != "text_size" {
                continue;
            }
            let Some(value) = self.known_const_string_value(&arg.value) else {
                continue;
            };
            if !TEXT_SIZES.iter().any(|allowed| *allowed == value) {
                self.diagnostics.push(Diagnostic::error(
                    "E_CALL_ARG_VALUE",
                    format!(
                        "`box.new` argument `text_size` only supports {} or int sizes",
                        TEXT_SIZES.join(", ")
                    ),
                    arg.span,
                ));
            }
        }
    }

    fn validate_box_new_text_formatting_arg(&mut self, args: &[CallArg], params: &[BoxNewParam]) {
        for (index, arg) in args.iter().enumerate() {
            let Some(param) = box_new_param(params, index, arg, &mut Vec::new()) else {
                continue;
            };
            if param.name != "text_formatting" {
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
                    "`box.new` argument `text_formatting` only supports text.format_none, text.format_bold, text.format_italic, or text.format_bold + text.format_italic",
                    arg.span,
                ));
            }
        }
    }
}

fn label_new_uses_point_overload(args: &[CallArg], arg_types: &[Option<PineType>]) -> bool {
    args.iter().any(|arg| arg.name.as_deref() == Some("point"))
        || arg_types
            .first()
            .copied()
            .flatten()
            .is_some_and(|arg_type| arg_type.kind == ValueKind::ChartPoint)
}

fn label_new_param<'a>(
    params: &'a [LabelNewParam],
    index: usize,
    arg: &CallArg,
    diagnostics: &mut Vec<Diagnostic>,
) -> Option<&'a LabelNewParam> {
    if let Some(name) = &arg.name {
        let param = params.iter().find(|param| param.name == name);
        if param.is_none() {
            diagnostics.push(Diagnostic::error(
                "E_CALL_ARG_NAME",
                format!("`label.new` has no argument named `{name}`"),
                arg.span,
            ));
        }
        param
    } else {
        params.get(index)
    }
}

fn line_new_uses_point_overload(args: &[CallArg], arg_types: &[Option<PineType>]) -> bool {
    args.iter()
        .any(|arg| matches!(arg.name.as_deref(), Some("first_point" | "second_point")))
        || arg_types
            .first()
            .copied()
            .flatten()
            .is_some_and(|arg_type| arg_type.kind == ValueKind::ChartPoint)
}

fn line_new_param<'a>(
    params: &'a [LineNewParam],
    index: usize,
    arg: &CallArg,
    diagnostics: &mut Vec<Diagnostic>,
) -> Option<&'a LineNewParam> {
    if let Some(name) = &arg.name {
        let param = params.iter().find(|param| param.name == name);
        if param.is_none() {
            diagnostics.push(Diagnostic::error(
                "E_CALL_ARG_NAME",
                format!("`line.new` has no argument named `{name}`"),
                arg.span,
            ));
        }
        param
    } else {
        params.get(index)
    }
}

fn box_new_uses_point_overload(args: &[CallArg], arg_types: &[Option<PineType>]) -> bool {
    args.iter()
        .any(|arg| matches!(arg.name.as_deref(), Some("top_left" | "bottom_right")))
        || arg_types
            .first()
            .copied()
            .flatten()
            .is_some_and(|arg_type| arg_type.kind == ValueKind::ChartPoint)
}

fn box_new_param<'a>(
    params: &'a [BoxNewParam],
    index: usize,
    arg: &CallArg,
    diagnostics: &mut Vec<Diagnostic>,
) -> Option<&'a BoxNewParam> {
    if let Some(name) = &arg.name {
        let param = params.iter().find(|param| param.name == name);
        if param.is_none() {
            diagnostics.push(Diagnostic::error(
                "E_CALL_ARG_NAME",
                format!("`box.new` has no argument named `{name}`"),
                arg.span,
            ));
        }
        param
    } else {
        params.get(index)
    }
}
