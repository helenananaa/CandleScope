use pine_ir::{PineType, Qualifier, ValueKind};
use pine_syntax::{CallArg, Diagnostic, Span};

use super::lowering::LegacyCallArgRewrite;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum LegacyExpressionKind {
    Iff,
    Offset,
    RsiLength,
    RsiSeries,
}

#[derive(Debug, Clone)]
pub(crate) struct BoundLegacyExpression {
    pub(crate) kind: LegacyExpressionKind,
    pub(crate) ordered_args: Vec<CallArg>,
    pub(crate) ordered_arg_types: Vec<PineType>,
    pub(crate) arg_rewrites: Vec<LegacyCallArgRewrite>,
}

#[derive(Debug, Clone)]
pub(crate) enum LegacyExpressionBinding {
    Bound(BoundLegacyExpression),
    Invalid(Vec<Diagnostic>),
}

pub(crate) fn bind_legacy_expression(
    name: &str,
    args: &[CallArg],
    arg_types: &[Option<PineType>],
    call_span: Span,
) -> LegacyExpressionBinding {
    let params: &[&str] = match name {
        "iff" => &["condition", "result1", "result2"],
        "offset" => &["source", "offset"],
        "rsi" => &["x", "y"],
        _ => return LegacyExpressionBinding::Invalid(Vec::new()),
    };
    let mut ordered = vec![None; params.len()];
    let mut rewrites = vec![
        LegacyCallArgRewrite {
            keep: true,
            canonical_name: None,
        };
        args.len()
    ];
    let mut diagnostics = Vec::new();
    let mut positional = 0;
    let mut saw_named = false;

    for (index, (arg, arg_type)) in args.iter().zip(arg_types).enumerate() {
        let param_index = if let Some(arg_name) = arg.name.as_deref() {
            saw_named = true;
            let Some(param_index) = params.iter().position(|param| *param == arg_name) else {
                diagnostics.push(Diagnostic::error(
                    "E_CALL_ARG_NAME",
                    format!("`{name}` has no Pine v4 argument named `{arg_name}`"),
                    arg.span,
                ));
                continue;
            };
            param_index
        } else {
            if saw_named {
                diagnostics.push(Diagnostic::error(
                    "E_CALL_ARG_ORDER",
                    format!("positional arguments cannot follow named arguments in `{name}`"),
                    arg.span,
                ));
                continue;
            }
            let param_index = positional;
            positional += 1;
            if param_index >= params.len() {
                diagnostics.push(Diagnostic::error(
                    "E_CALL_ARITY",
                    format!(
                        "Pine v4 `{name}` expects {} argument(s), got {}",
                        params.len(),
                        args.len()
                    ),
                    arg.span,
                ));
                continue;
            }
            param_index
        };
        if ordered[param_index].is_some() {
            diagnostics.push(Diagnostic::error(
                "E_CALL_ARG_DUPLICATE",
                format!(
                    "`{name}` argument `{}` is provided more than once",
                    params[param_index]
                ),
                arg.span,
            ));
            continue;
        }
        let Some(arg_type) = *arg_type else {
            continue;
        };
        ordered[param_index] = Some((arg.clone(), arg_type));
        rewrites[index].canonical_name = Some(params[param_index]);
    }

    for (index, param) in params.iter().enumerate() {
        if ordered[index].is_none() {
            diagnostics.push(Diagnostic::error(
                "E_CALL_ARITY",
                format!("`{name}` is missing required Pine v4 argument `{param}`"),
                call_span,
            ));
        }
    }
    if !diagnostics.is_empty() {
        return LegacyExpressionBinding::Invalid(diagnostics);
    }

    let (ordered_args, ordered_arg_types): (Vec<_>, Vec<_>) = ordered
        .into_iter()
        .map(|arg| arg.expect("validated required legacy argument"))
        .unzip();
    let kind = match name {
        "iff" => Some(LegacyExpressionKind::Iff),
        "offset" => Some(LegacyExpressionKind::Offset),
        "rsi" => rsi_overload(ordered_arg_types[1], ordered_args[1].span, &mut diagnostics),
        _ => unreachable!("legacy expression names are matched above"),
    };
    let Some(kind) = kind else {
        return LegacyExpressionBinding::Invalid(diagnostics);
    };
    if name == "rsi" {
        let canonical_names = match kind {
            LegacyExpressionKind::RsiLength => ["source", "length"],
            LegacyExpressionKind::RsiSeries => ["x", "y"],
            _ => unreachable!("rsi overload kind"),
        };
        for rewrite in &mut rewrites {
            let Some(source_name) = rewrite.canonical_name else {
                continue;
            };
            let param_index = params
                .iter()
                .position(|param| *param == source_name)
                .expect("validated rsi parameter");
            rewrite.canonical_name = Some(canonical_names[param_index]);
        }
    }

    LegacyExpressionBinding::Bound(BoundLegacyExpression {
        kind,
        ordered_args,
        ordered_arg_types,
        arg_rewrites: rewrites,
    })
}

fn rsi_overload(
    second: PineType,
    span: Span,
    diagnostics: &mut Vec<Diagnostic>,
) -> Option<LegacyExpressionKind> {
    if second.kind == ValueKind::Int && second.qualifier != Qualifier::Series {
        return Some(LegacyExpressionKind::RsiLength);
    }
    if matches!(second.kind, ValueKind::Int | ValueKind::Float) {
        return Some(LegacyExpressionKind::RsiSeries);
    }
    diagnostics.push(Diagnostic::error(
        "E_LEGACY_RSI_OVERLOAD",
        format!(
            "cannot select Pine v4 `rsi(x, y)` overload from second argument {:?} {:?}",
            second.qualifier, second.kind
        ),
        span,
    ));
    None
}
