use pine_ir::{PineType, Qualifier, ValueKind};
use pine_syntax::{CallArg, Diagnostic, Expr, Span};

use super::PineDialect;
use super::lowering::LegacyCallArgRewrite;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum LegacyInputKind {
    Bool,
    Color,
    Integer,
    Float,
    String,
    Symbol,
    Resolution,
    Session,
    Source,
    Time,
    Price,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct LegacyInputConstant {
    pub(crate) marker: &'static str,
    pub(crate) canonical_name: &'static str,
}

#[derive(Debug, Clone)]
pub(crate) struct BoundLegacyInput {
    pub(crate) canonical_name: &'static str,
    pub(crate) canonical_args: Vec<CallArg>,
    pub(crate) canonical_arg_types: Vec<Option<PineType>>,
    pub(crate) arg_rewrites: Vec<LegacyCallArgRewrite>,
}

#[derive(Debug, Clone)]
pub(crate) enum LegacyInputBinding {
    Bound(BoundLegacyInput),
    Invalid(Vec<Diagnostic>),
}

#[derive(Debug, Clone, Copy)]
struct InputParam {
    name: &'static str,
    canonical_name: Option<&'static str>,
}

const SIMPLE_PARAMS: &[InputParam] = &[
    InputParam::kept("defval"),
    InputParam::kept("title"),
    InputParam::removed("type"),
    InputParam::kept("confirm"),
    InputParam::kept("tooltip"),
    InputParam::kept("inline"),
    InputParam::kept("group"),
];

const NUMERIC_PARAMS: &[InputParam] = &[
    InputParam::kept("defval"),
    InputParam::kept("title"),
    InputParam::removed("type"),
    InputParam::kept("minval"),
    InputParam::kept("maxval"),
    InputParam::kept("confirm"),
    InputParam::kept("step"),
    InputParam::kept("options"),
    InputParam::kept("tooltip"),
    InputParam::kept("inline"),
    InputParam::kept("group"),
];

const STRING_PARAMS: &[InputParam] = &[
    InputParam::kept("defval"),
    InputParam::kept("title"),
    InputParam::removed("type"),
    InputParam::kept("confirm"),
    InputParam::kept("options"),
    InputParam::kept("tooltip"),
    InputParam::kept("inline"),
    InputParam::kept("group"),
];

// Pine v4's source overload placed tooltip after inline and group. Keeping a
// separate table prevents the modern input.source order from leaking into
// positional legacy calls.
const SOURCE_PARAMS: &[InputParam] = &[
    InputParam::kept("defval"),
    InputParam::kept("title"),
    InputParam::removed("type"),
    InputParam::kept("inline"),
    InputParam::kept("group"),
    InputParam::kept("tooltip"),
];

const V3_SIMPLE_PARAMS: &[InputParam] = &[
    InputParam::kept("defval"),
    InputParam::kept("title"),
    InputParam::removed("type"),
    InputParam::kept("confirm"),
];

const V3_NUMERIC_PARAMS: &[InputParam] = &[
    InputParam::kept("defval"),
    InputParam::kept("title"),
    InputParam::removed("type"),
    InputParam::kept("minval"),
    InputParam::kept("maxval"),
    InputParam::kept("confirm"),
    InputParam::kept("step"),
    InputParam::kept("options"),
];

const V3_STRING_PARAMS: &[InputParam] = &[
    InputParam::kept("defval"),
    InputParam::kept("title"),
    InputParam::removed("type"),
    InputParam::kept("confirm"),
    InputParam::kept("options"),
];

const V3_SOURCE_PARAMS: &[InputParam] = &[
    InputParam::kept("defval"),
    InputParam::kept("title"),
    InputParam::removed("type"),
];

impl InputParam {
    const fn kept(name: &'static str) -> Self {
        Self {
            name,
            canonical_name: Some(name),
        }
    }

    const fn removed(name: &'static str) -> Self {
        Self {
            name,
            canonical_name: None,
        }
    }
}

impl LegacyInputKind {
    const fn constant(self) -> LegacyInputConstant {
        match self {
            Self::Bool => LegacyInputConstant {
                marker: "$legacy-input:bool",
                canonical_name: "input.bool",
            },
            Self::Color => LegacyInputConstant {
                marker: "$legacy-input:color",
                canonical_name: "input.color",
            },
            Self::Integer => LegacyInputConstant {
                marker: "$legacy-input:integer",
                canonical_name: "input.int",
            },
            Self::Float => LegacyInputConstant {
                marker: "$legacy-input:float",
                canonical_name: "input.float",
            },
            Self::String => LegacyInputConstant {
                marker: "$legacy-input:string",
                canonical_name: "input.string",
            },
            Self::Symbol => LegacyInputConstant {
                marker: "$legacy-input:symbol",
                canonical_name: "input.symbol",
            },
            Self::Resolution => LegacyInputConstant {
                marker: "$legacy-input:resolution",
                canonical_name: "input.timeframe",
            },
            Self::Session => LegacyInputConstant {
                marker: "$legacy-input:session",
                canonical_name: "input.session",
            },
            Self::Source => LegacyInputConstant {
                marker: "$legacy-input:source",
                canonical_name: "input.source",
            },
            Self::Time => LegacyInputConstant {
                marker: "$legacy-input:time",
                canonical_name: "input.time",
            },
            Self::Price => LegacyInputConstant {
                marker: "$legacy-input:price",
                canonical_name: "input.price",
            },
        }
    }

    fn from_source_name(name: &str) -> Option<Self> {
        Some(match name {
            "bool" | "input.bool" => Self::Bool,
            "input.color" => Self::Color,
            "integer" | "input.integer" => Self::Integer,
            "float" | "input.float" => Self::Float,
            "string" | "input.string" => Self::String,
            "symbol" | "input.symbol" => Self::Symbol,
            "resolution" | "input.resolution" => Self::Resolution,
            "session" | "input.session" => Self::Session,
            "source" | "input.source" => Self::Source,
            "input.time" => Self::Time,
            "input.price" => Self::Price,
            _ => return None,
        })
    }

    fn from_marker(marker: &str) -> Option<Self> {
        [
            Self::Bool,
            Self::Color,
            Self::Integer,
            Self::Float,
            Self::String,
            Self::Symbol,
            Self::Resolution,
            Self::Session,
            Self::Source,
            Self::Time,
            Self::Price,
        ]
        .into_iter()
        .find(|kind| kind.constant().marker == marker)
    }

    fn infer(defval_type: PineType) -> Option<Self> {
        match (defval_type.qualifier, defval_type.kind) {
            (Qualifier::Const, ValueKind::Int) => Some(Self::Integer),
            (Qualifier::Const, ValueKind::Float) => Some(Self::Float),
            (Qualifier::Const, ValueKind::Bool) => Some(Self::Bool),
            (Qualifier::Const, ValueKind::Color) => Some(Self::Color),
            (Qualifier::Const, ValueKind::String) => Some(Self::String),
            (Qualifier::Series, ValueKind::Float) => Some(Self::Source),
            _ => None,
        }
    }

    const fn params(self, dialect: PineDialect) -> &'static [InputParam] {
        match (dialect, self) {
            (PineDialect::V1 | PineDialect::V2 | PineDialect::V3, Self::Integer | Self::Float) => {
                V3_NUMERIC_PARAMS
            }
            (PineDialect::V1 | PineDialect::V2 | PineDialect::V3, Self::String) => V3_STRING_PARAMS,
            (PineDialect::V1 | PineDialect::V2 | PineDialect::V3, Self::Source) => V3_SOURCE_PARAMS,
            (
                PineDialect::V1 | PineDialect::V2 | PineDialect::V3,
                Self::Bool | Self::Symbol | Self::Resolution | Self::Session,
            ) => V3_SIMPLE_PARAMS,
            (
                PineDialect::V1 | PineDialect::V2 | PineDialect::V3,
                Self::Color | Self::Time | Self::Price,
            ) => V3_SIMPLE_PARAMS,
            (_, Self::Integer | Self::Float) => NUMERIC_PARAMS,
            (_, Self::String) => STRING_PARAMS,
            (_, Self::Source) => SOURCE_PARAMS,
            (
                _,
                Self::Bool
                | Self::Color
                | Self::Symbol
                | Self::Resolution
                | Self::Session
                | Self::Time
                | Self::Price,
            ) => SIMPLE_PARAMS,
        }
    }
}

pub(crate) fn input_constant(source_name: &str) -> Option<LegacyInputConstant> {
    LegacyInputKind::from_source_name(source_name).map(LegacyInputKind::constant)
}

pub(crate) fn explicit_type_expr(args: &[CallArg]) -> Option<&Expr> {
    args.iter()
        .find(|arg| arg.name.as_deref() == Some("type"))
        .or_else(|| args.get(2).filter(|arg| arg.name.is_none()))
        .map(|arg| &arg.value)
}

pub(crate) fn bind_legacy_input_args(
    dialect: PineDialect,
    args: &[CallArg],
    arg_types: &[Option<PineType>],
    explicit_type_marker: Option<&str>,
) -> LegacyInputBinding {
    let version = dialect.version();
    let defval_index = args
        .iter()
        .position(|arg| arg.name.as_deref() == Some("defval"))
        .or_else(|| args.first().filter(|arg| arg.name.is_none()).map(|_| 0));
    let explicit_type_index = args
        .iter()
        .position(|arg| arg.name.as_deref() == Some("type"))
        .or_else(|| args.get(2).filter(|arg| arg.name.is_none()).map(|_| 2));

    let kind = if let Some(type_index) = explicit_type_index {
        let Some(marker) = explicit_type_marker else {
            return LegacyInputBinding::Invalid(vec![Diagnostic::error(
                "E_LEGACY_INPUT_OVERLOAD",
                format!(
                    "Pine v{version} `input` argument `type` must be one of the versioned input type constants"
                ),
                args[type_index].span,
            )]);
        };
        let Some(kind) = LegacyInputKind::from_marker(marker) else {
            return LegacyInputBinding::Invalid(vec![Diagnostic::error(
                "E_LEGACY_INPUT_OVERLOAD",
                format!(
                    "Pine v{version} `input` argument `type` does not resolve to a supported input type constant"
                ),
                args[type_index].span,
            )]);
        };
        kind
    } else {
        let Some(defval_index) = defval_index else {
            return LegacyInputBinding::Invalid(vec![Diagnostic::error(
                "E_CALL_ARITY",
                format!("`input` is missing required Pine v{version} argument `defval`"),
                args.first().map_or_else(Span::default, |arg| arg.span),
            )]);
        };
        let Some(defval_type) = arg_types.get(defval_index).copied().flatten() else {
            return LegacyInputBinding::Invalid(vec![Diagnostic::error(
                "E_LEGACY_INPUT_OVERLOAD",
                format!(
                    "cannot infer the Pine v{version} `input` overload from an invalid default value"
                ),
                args[defval_index].span,
            )]);
        };
        let Some(kind) = LegacyInputKind::infer(defval_type) else {
            return LegacyInputBinding::Invalid(vec![Diagnostic::error(
                "E_LEGACY_INPUT_OVERLOAD",
                format!(
                    "cannot infer the Pine v{version} `input` overload from {:?} {:?}",
                    defval_type.qualifier, defval_type.kind
                ),
                args[defval_index].span,
            )]);
        };
        kind
    };

    let params = kind.params(dialect);
    let mut bound = vec![false; params.len()];
    let mut diagnostics = Vec::new();
    let mut saw_named = false;
    let mut canonical_args = Vec::with_capacity(args.len().saturating_sub(1));
    let mut canonical_arg_types = Vec::with_capacity(args.len().saturating_sub(1));
    let mut arg_rewrites = vec![
        LegacyCallArgRewrite {
            keep: false,
            canonical_name: None,
        };
        args.len()
    ];

    for (arg_index, (arg, arg_type)) in args.iter().zip(arg_types).enumerate() {
        let param_index = if let Some(name) = arg.name.as_deref() {
            saw_named = true;
            let Some(param_index) = params.iter().position(|param| param.name == name) else {
                diagnostics.push(Diagnostic::error(
                    "E_CALL_ARG_NAME",
                    format!(
                        "`input` has no argument named `{name}` for the selected Pine v{version} overload"
                    ),
                    arg.span,
                ));
                continue;
            };
            param_index
        } else {
            if saw_named {
                diagnostics.push(Diagnostic::error(
                    "E_CALL_ARG_ORDER",
                    format!("positional arguments cannot follow named arguments in Pine v{version} `input`"),
                    arg.span,
                ));
                continue;
            }
            if arg_index >= params.len() {
                diagnostics.push(Diagnostic::error(
                    "E_CALL_ARITY",
                    format!(
                        "selected Pine v{version} `input` overload expects at most {} argument(s), got {}",
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
                    "`input` argument `{}` is provided more than once",
                    param.name
                ),
                arg.span,
            ));
            continue;
        }
        bound[param_index] = true;

        let Some(canonical_name) = param.canonical_name else {
            continue;
        };
        let mut canonical_arg = arg.clone();
        canonical_arg.name = Some(canonical_name.to_owned());
        canonical_args.push(canonical_arg);
        let canonical_arg_type = if kind == LegacyInputKind::Integer
            && matches!(param.name, "minval" | "maxval" | "step")
            && arg_type.is_some_and(|pine_type| {
                pine_type == PineType::new(Qualifier::Const, ValueKind::Float)
            }) {
            // Pine v4 accepted const-float bounds and steps for integer inputs.
            // Override only the canonical validation view; the original AST
            // expression and source span remain intact, and modern input.int
            // calls continue to require const int.
            Some(PineType::new(Qualifier::Const, ValueKind::Int))
        } else {
            *arg_type
        };
        canonical_arg_types.push(canonical_arg_type);
        arg_rewrites[arg_index] = LegacyCallArgRewrite {
            keep: true,
            canonical_name: Some(canonical_name),
        };
    }

    if !bound.first().copied().unwrap_or(false) {
        diagnostics.push(Diagnostic::error(
            "E_CALL_ARITY",
            format!("`input` is missing required Pine v{version} argument `defval`"),
            args.first().map_or_else(Span::default, |arg| arg.span),
        ));
    }
    if !diagnostics.is_empty() {
        return LegacyInputBinding::Invalid(diagnostics);
    }

    LegacyInputBinding::Bound(BoundLegacyInput {
        canonical_name: kind.constant().canonical_name,
        canonical_args,
        canonical_arg_types,
        arg_rewrites,
    })
}
