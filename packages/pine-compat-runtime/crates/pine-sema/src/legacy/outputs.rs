use pine_ir::{PineType, Qualifier, ValueKind};
use pine_syntax::{CallArg, Diagnostic, Span};

use crate::types::qualifier_at_most;

use super::PineDialect;
use super::lowering::LegacyCallArgRewrite;

pub(crate) const LEGACY_OUTPUT_DEFERRED_REASON: &str = "legacy output arguments require version-specific style and transparency lowering that is not implemented yet";

#[derive(Debug, Clone)]
pub(crate) struct BoundLegacyOutput {
    pub(crate) canonical_name: &'static str,
    pub(crate) canonical_args: Vec<CallArg>,
    pub(crate) canonical_arg_types: Vec<Option<PineType>>,
    pub(crate) arg_rewrites: Vec<LegacyCallArgRewrite>,
    pub(crate) requires_adaptation: bool,
    pub(crate) emulates_transparency: bool,
    pub(crate) emulates_numeric_style: bool,
}

#[derive(Debug, Clone)]
pub(crate) enum LegacyOutputBinding {
    Bound(BoundLegacyOutput),
    Invalid(Vec<Diagnostic>),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum OutputParamKind {
    Canonical,
    Transparency,
    PlotStyle,
    HLineStyle,
}

#[derive(Debug, Clone, Copy)]
struct OutputParam {
    source_name: &'static str,
    canonical_name: Option<&'static str>,
    required: bool,
    kind: OutputParamKind,
}

struct StyleArgument<'a> {
    call_name: &'a str,
    version: u16,
    param_name: &'static str,
    arg_type: Option<PineType>,
    const_string: Option<&'a str>,
    const_int: Option<i64>,
    styles: &'static [&'static str],
    span: Span,
}

impl OutputParam {
    const fn required(name: &'static str) -> Self {
        Self::canonical(name, name, true)
    }

    const fn optional(name: &'static str) -> Self {
        Self::canonical(name, name, false)
    }

    const fn renamed(
        source_name: &'static str,
        canonical_name: &'static str,
        required: bool,
    ) -> Self {
        Self::canonical(source_name, canonical_name, required)
    }

    const fn canonical(
        source_name: &'static str,
        canonical_name: &'static str,
        required: bool,
    ) -> Self {
        Self {
            source_name,
            canonical_name: Some(canonical_name),
            required,
            kind: OutputParamKind::Canonical,
        }
    }

    const fn transparency() -> Self {
        Self {
            source_name: "transp",
            canonical_name: None,
            required: false,
            kind: OutputParamKind::Transparency,
        }
    }

    const fn plot_style() -> Self {
        Self {
            source_name: "style",
            canonical_name: Some("style"),
            required: false,
            kind: OutputParamKind::PlotStyle,
        }
    }

    const fn hline_style() -> Self {
        Self {
            source_name: "linestyle",
            canonical_name: Some("linestyle"),
            required: false,
            kind: OutputParamKind::HLineStyle,
        }
    }
}

const PLOT_PARAMS: &[OutputParam] = &[
    OutputParam::required("series"),
    OutputParam::optional("title"),
    OutputParam::optional("color"),
    OutputParam::optional("linewidth"),
    OutputParam::plot_style(),
    OutputParam::optional("trackprice"),
    OutputParam::transparency(),
    OutputParam::optional("histbase"),
    OutputParam::optional("offset"),
    OutputParam::optional("join"),
    OutputParam::optional("editable"),
    OutputParam::optional("show_last"),
    OutputParam::optional("display"),
];

const PLOTCHAR_PARAMS: &[OutputParam] = &[
    OutputParam::required("series"),
    OutputParam::optional("title"),
    OutputParam::optional("char"),
    OutputParam::optional("location"),
    OutputParam::optional("color"),
    OutputParam::transparency(),
    OutputParam::optional("offset"),
    OutputParam::optional("text"),
    OutputParam::optional("textcolor"),
    OutputParam::optional("editable"),
    OutputParam::optional("size"),
    OutputParam::optional("show_last"),
    OutputParam::optional("display"),
];

const PLOTSHAPE_PARAMS: &[OutputParam] = &[
    OutputParam::required("series"),
    OutputParam::optional("title"),
    OutputParam::optional("style"),
    OutputParam::optional("location"),
    OutputParam::optional("color"),
    OutputParam::transparency(),
    OutputParam::optional("offset"),
    OutputParam::optional("text"),
    OutputParam::optional("textcolor"),
    OutputParam::optional("editable"),
    OutputParam::optional("size"),
    OutputParam::optional("show_last"),
    OutputParam::optional("display"),
];

const PLOTARROW_PARAMS: &[OutputParam] = &[
    OutputParam::required("series"),
    OutputParam::optional("title"),
    OutputParam::optional("colorup"),
    OutputParam::optional("colordown"),
    OutputParam::transparency(),
    OutputParam::optional("offset"),
    OutputParam::optional("minheight"),
    OutputParam::optional("maxheight"),
    OutputParam::optional("editable"),
    OutputParam::optional("show_last"),
    OutputParam::optional("display"),
];

const PLOTBAR_PARAMS: &[OutputParam] = &[
    OutputParam::required("open"),
    OutputParam::required("high"),
    OutputParam::required("low"),
    OutputParam::required("close"),
    OutputParam::optional("title"),
    OutputParam::optional("color"),
    OutputParam::optional("editable"),
    OutputParam::optional("show_last"),
    OutputParam::optional("display"),
];

const PLOTCANDLE_PARAMS: &[OutputParam] = &[
    OutputParam::required("open"),
    OutputParam::required("high"),
    OutputParam::required("low"),
    OutputParam::required("close"),
    OutputParam::optional("title"),
    OutputParam::optional("color"),
    OutputParam::optional("wickcolor"),
    OutputParam::optional("editable"),
    OutputParam::optional("show_last"),
    OutputParam::optional("bordercolor"),
    OutputParam::optional("display"),
];

const BGCOLOR_PARAMS: &[OutputParam] = &[
    OutputParam::required("color"),
    OutputParam::transparency(),
    OutputParam::optional("offset"),
    OutputParam::optional("editable"),
    OutputParam::optional("show_last"),
    OutputParam::optional("title"),
];

const BARCOLOR_PARAMS: &[OutputParam] = &[
    OutputParam::required("color"),
    OutputParam::optional("offset"),
    OutputParam::optional("editable"),
    OutputParam::optional("show_last"),
    OutputParam::optional("title"),
];

const HLINE_PARAMS: &[OutputParam] = &[
    OutputParam::required("price"),
    OutputParam::optional("title"),
    OutputParam::optional("color"),
    OutputParam::hline_style(),
    OutputParam::optional("linewidth"),
    OutputParam::optional("editable"),
];

const V3_PLOT_PARAMS: &[OutputParam] = &[
    OutputParam::required("series"),
    OutputParam::optional("title"),
    OutputParam::optional("color"),
    OutputParam::optional("linewidth"),
    OutputParam::plot_style(),
    OutputParam::optional("trackprice"),
    OutputParam::transparency(),
    OutputParam::optional("histbase"),
    OutputParam::optional("offset"),
    OutputParam::optional("join"),
    OutputParam::optional("editable"),
    OutputParam::optional("show_last"),
];

const V3_HLINE_PARAMS: &[OutputParam] = &[
    OutputParam::required("price"),
    OutputParam::optional("title"),
    OutputParam::optional("color"),
    OutputParam::hline_style(),
    OutputParam::optional("linewidth"),
    OutputParam::optional("editable"),
];

const FILL_PLOT_PARAMS: &[OutputParam] = &[
    OutputParam::required("plot1"),
    OutputParam::required("plot2"),
    OutputParam::optional("color"),
    OutputParam::transparency(),
    OutputParam::optional("title"),
    OutputParam::optional("editable"),
    OutputParam::optional("show_last"),
    OutputParam::optional("fillgaps"),
];

const FILL_HLINE_PARAMS: &[OutputParam] = &[
    OutputParam::renamed("hline1", "plot1", true),
    OutputParam::renamed("hline2", "plot2", true),
    OutputParam::optional("color"),
    OutputParam::transparency(),
    OutputParam::optional("title"),
    OutputParam::optional("editable"),
    OutputParam::optional("fillgaps"),
];

const PLOT_STYLES: &[&str] = &[
    "plot.style_line",
    "plot.style_stepline",
    "plot.style_histogram",
    "plot.style_cross",
    "plot.style_area",
    "plot.style_columns",
    "plot.style_circles",
    "plot.style_linebr",
    "plot.style_areabr",
];
const HLINE_STYLES: &[&str] = &[
    "hline.style_solid",
    "hline.style_dotted",
    "hline.style_dashed",
];

fn params_for_call(
    dialect: PineDialect,
    name: &str,
    args: &[CallArg],
    arg_types: &[Option<PineType>],
) -> Result<&'static [OutputParam], Diagnostic> {
    if matches!(dialect, PineDialect::V1 | PineDialect::V2 | PineDialect::V3) {
        return Ok(match name {
            "plot" => V3_PLOT_PARAMS,
            "hline" => V3_HLINE_PARAMS,
            _ => unreachable!("only the pre-v4 plot/hline output subset is admitted"),
        });
    }
    Ok(match name {
        "plot" => PLOT_PARAMS,
        "plotchar" => PLOTCHAR_PARAMS,
        "plotshape" => PLOTSHAPE_PARAMS,
        "plotarrow" => PLOTARROW_PARAMS,
        "plotbar" => PLOTBAR_PARAMS,
        "plotcandle" => PLOTCANDLE_PARAMS,
        "bgcolor" => BGCOLOR_PARAMS,
        "barcolor" => BARCOLOR_PARAMS,
        "hline" => HLINE_PARAMS,
        "fill" => fill_params(args, arg_types)?,
        _ => unreachable!("focused v4 output binder called for an unknown output"),
    })
}

fn fill_params(
    args: &[CallArg],
    arg_types: &[Option<PineType>],
) -> Result<&'static [OutputParam], Diagnostic> {
    let named_hline = args
        .iter()
        .any(|arg| matches!(arg.name.as_deref(), Some("hline1" | "hline2")));
    let named_plot = args
        .iter()
        .any(|arg| matches!(arg.name.as_deref(), Some("plot1" | "plot2")));
    if named_hline && named_plot {
        return Err(output_error(
            "Pine v4 `fill` cannot mix plot and hline argument names",
            args.first().map_or_else(Span::default, |arg| arg.span),
        ));
    }
    let expected_kind = if named_hline {
        ValueKind::HLine
    } else if named_plot {
        ValueKind::Plot
    } else {
        arg_types
            .first()
            .copied()
            .flatten()
            .map_or(ValueKind::Plot, |pine_type| pine_type.kind)
    };
    let endpoint_kind_mismatch = args.iter().enumerate().any(|(index, arg)| {
        let is_endpoint = match arg.name.as_deref() {
            Some("plot1" | "plot2" | "hline1" | "hline2") => true,
            Some(_) => false,
            None => index < 2,
        };
        is_endpoint
            && arg_types
                .get(index)
                .copied()
                .flatten()
                .is_some_and(|pine_type| pine_type.kind != expected_kind)
    });
    if !matches!(expected_kind, ValueKind::Plot | ValueKind::HLine) || endpoint_kind_mismatch {
        return Err(output_error(
            "Pine v4 `fill` requires two plot ids or two hline ids from the same overload",
            args.get(1)
                .or_else(|| args.first())
                .map_or_else(Span::default, |arg| arg.span),
        ));
    }
    Ok(if expected_kind == ValueKind::HLine {
        FILL_HLINE_PARAMS
    } else {
        FILL_PLOT_PARAMS
    })
}

pub(crate) fn bind_legacy_output_args(
    dialect: PineDialect,
    name: &str,
    args: &[CallArg],
    arg_types: &[Option<PineType>],
    const_strings: &[Option<String>],
    const_ints: &[Option<i64>],
) -> LegacyOutputBinding {
    let version = dialect.version();
    let params = match params_for_call(dialect, name, args, arg_types) {
        Ok(params) => params,
        Err(diagnostic) => return LegacyOutputBinding::Invalid(vec![diagnostic]),
    };
    let mut bound = vec![false; params.len()];
    let mut diagnostics = Vec::new();
    let mut saw_named = false;
    let mut canonical_args = Vec::with_capacity(args.len());
    let mut canonical_arg_types = Vec::with_capacity(args.len());
    let mut arg_rewrites = vec![
        LegacyCallArgRewrite {
            keep: false,
            canonical_name: None
        };
        args.len()
    ];
    let mut emulates_transparency = matches!(name, "bgcolor" | "fill");
    let mut emulates_numeric_style = false;
    let mut requires_adaptation = emulates_transparency;
    let canonical_signature =
        pine_builtins::get_phase_1_builtin(name).expect("focused v4 output target is registered");
    let mut retained_arg_count = 0usize;
    let mut lowering_uses_named_args = false;

    for (arg_index, arg) in args.iter().enumerate() {
        let param_index = if let Some(arg_name) = arg.name.as_deref() {
            saw_named = true;
            let Some(index) = params
                .iter()
                .position(|param| param.source_name == arg_name)
            else {
                diagnostics.push(Diagnostic::error(
                    "E_CALL_ARG_NAME",
                    format!("`{name}` has no argument named `{arg_name}` in Pine v{version}"),
                    arg.span,
                ));
                continue;
            };
            index
        } else {
            if saw_named {
                diagnostics.push(Diagnostic::error(
                    "E_CALL_ARG_ORDER",
                    format!(
                        "positional arguments cannot follow named arguments in Pine v{version} `{name}`"
                    ),
                    arg.span,
                ));
                continue;
            }
            if arg_index >= params.len() {
                diagnostics.push(Diagnostic::error(
                    "E_CALL_ARITY",
                    format!(
                        "`{name}` expects at most {} argument(s) in Pine v{version}, got {}",
                        params.len(),
                        args.len()
                    ),
                    arg.span,
                ));
                continue;
            }
            arg_index
        };
        let param = params[param_index];
        if bound[param_index] {
            diagnostics.push(Diagnostic::error(
                "E_CALL_ARG_DUPLICATE",
                format!(
                    "`{name}` argument `{}` is provided more than once",
                    param.source_name
                ),
                arg.span,
            ));
            continue;
        }
        bound[param_index] = true;
        let arg_type = arg_types.get(arg_index).copied().flatten();

        if param.kind == OutputParamKind::Transparency {
            emulates_transparency = true;
            requires_adaptation = true;
            if !arg_type.is_some_and(is_legacy_transparency_type) {
                diagnostics.push(output_error(
                    format!("Pine v{version} `{name}` argument `transp` expects an input integer or `na`"),
                    arg.span,
                ));
            }
            arg_rewrites[arg_index] = LegacyCallArgRewrite {
                keep: true,
                canonical_name: Some(pine_ir::LEGACY_TRANSPARENCY_ARG),
            };
            lowering_uses_named_args = true;
            continue;
        }

        let canonical_type = match param.kind {
            OutputParamKind::PlotStyle => validate_style(
                StyleArgument {
                    call_name: name,
                    version,
                    param_name: "style",
                    arg_type,
                    const_string: const_strings.get(arg_index).and_then(Option::as_deref),
                    const_int: const_ints.get(arg_index).copied().flatten(),
                    styles: PLOT_STYLES,
                    span: arg.span,
                },
                &mut diagnostics,
                &mut emulates_numeric_style,
            ),
            OutputParamKind::HLineStyle => validate_style(
                StyleArgument {
                    call_name: name,
                    version,
                    param_name: "linestyle",
                    arg_type,
                    const_string: const_strings.get(arg_index).and_then(Option::as_deref),
                    const_int: const_ints.get(arg_index).copied().flatten(),
                    styles: HLINE_STYLES,
                    span: arg.span,
                },
                &mut diagnostics,
                &mut emulates_numeric_style,
            ),
            OutputParamKind::Canonical => arg_type,
            OutputParamKind::Transparency => unreachable!(),
        };
        let canonical_name = param
            .canonical_name
            .expect("retained output argument has a canonical name");
        let mut canonical_arg = arg.clone();
        canonical_arg.name = Some(canonical_name.to_owned());
        canonical_args.push(canonical_arg);
        canonical_arg_types.push(canonical_type);
        let canonical_index = canonical_signature
            .params
            .iter()
            .position(|candidate| candidate.name == canonical_name)
            .expect("validated output parameter has a canonical signature slot");
        let can_remain_positional = arg.name.is_none()
            && !lowering_uses_named_args
            && canonical_index == retained_arg_count;
        arg_rewrites[arg_index] = LegacyCallArgRewrite {
            keep: true,
            canonical_name: (!can_remain_positional).then_some(canonical_name),
        };
        requires_adaptation |= !can_remain_positional
            && arg
                .name
                .as_deref()
                .is_none_or(|source_name| source_name != canonical_name);
        lowering_uses_named_args |= !can_remain_positional;
        retained_arg_count += 1;
    }

    for (index, param) in params.iter().enumerate() {
        if param.required && !bound[index] {
            diagnostics.push(Diagnostic::error(
                "E_CALL_ARITY",
                format!(
                    "`{name}` is missing required Pine v{version} argument `{}`",
                    param.source_name
                ),
                args.first().map_or_else(Span::default, |arg| arg.span),
            ));
        }
    }
    if !diagnostics.is_empty() {
        return LegacyOutputBinding::Invalid(diagnostics);
    }
    LegacyOutputBinding::Bound(BoundLegacyOutput {
        canonical_name: canonical_output_name(name),
        canonical_args,
        canonical_arg_types,
        arg_rewrites,
        requires_adaptation: requires_adaptation || emulates_numeric_style,
        emulates_transparency,
        emulates_numeric_style,
    })
}

fn validate_style(
    argument: StyleArgument<'_>,
    diagnostics: &mut Vec<Diagnostic>,
    emulates_numeric_style: &mut bool,
) -> Option<PineType> {
    let valid = match argument.arg_type {
        Some(pine_type)
            if pine_type.kind == ValueKind::Int
                && qualifier_at_most(pine_type.qualifier, Qualifier::Input) =>
        {
            *emulates_numeric_style = true;
            argument.const_int.is_none_or(|value| {
                usize::try_from(value).is_ok_and(|value| value < argument.styles.len())
            })
        }
        Some(pine_type) if pine_type.kind == ValueKind::String => argument
            .const_string
            .is_some_and(|value| argument.styles.contains(&value)),
        _ => false,
    };
    if !valid {
        diagnostics.push(output_error(
            format!("Pine v{} `{}` argument `{}` must be a documented style constant or an input integer in the supported style range", argument.version, argument.call_name, argument.param_name),
            argument.span,
        ));
    }
    Some(PineType::new(Qualifier::Const, ValueKind::String))
}

fn is_legacy_transparency_type(pine_type: PineType) -> bool {
    matches!(pine_type.kind, ValueKind::Int | ValueKind::Na)
        && qualifier_at_most(pine_type.qualifier, Qualifier::Input)
}

fn canonical_output_name(name: &str) -> &'static str {
    match name {
        "plot" => "plot",
        "plotchar" => "plotchar",
        "plotshape" => "plotshape",
        "plotarrow" => "plotarrow",
        "plotbar" => "plotbar",
        "plotcandle" => "plotcandle",
        "hline" => "hline",
        "fill" => "fill",
        "bgcolor" => "bgcolor",
        "barcolor" => "barcolor",
        _ => unreachable!(),
    }
}

fn output_error(message: impl Into<String>, span: Span) -> Diagnostic {
    Diagnostic::error("E_LEGACY_OUTPUT_ARGUMENT", message, span)
}
