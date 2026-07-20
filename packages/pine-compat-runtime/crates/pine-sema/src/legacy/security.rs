use pine_ir::PineType;
use pine_syntax::{CallArg, Diagnostic, Span};

use super::{dialect::PineDialect, lowering::LegacyCallArgRewrite};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum LegacySecurityGaps {
    Off,
    On,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum LegacySecurityLookahead {
    Off,
    On,
}

#[derive(Debug, Clone)]
pub(crate) struct BoundLegacySecurity {
    pub(crate) canonical_args: Vec<CallArg>,
    pub(crate) canonical_arg_types: Vec<Option<PineType>>,
    pub(crate) arg_rewrites: Vec<LegacyCallArgRewrite>,
    pub(crate) gaps: LegacySecurityGaps,
    pub(crate) lookahead: LegacySecurityLookahead,
    pub(crate) internal_callee: &'static str,
}

#[derive(Debug, Clone)]
pub(crate) enum LegacySecurityBinding {
    Bound(BoundLegacySecurity),
    Invalid(Vec<Diagnostic>),
}

const PARAMS: &[&str] = &["symbol", "resolution", "expression", "gaps", "lookahead"];
const CANONICAL_PARAMS: &[&str] = &["symbol", "timeframe", "expression"];

pub(crate) fn bind_legacy_security_args(
    dialect: PineDialect,
    args: &[CallArg],
    arg_types: &[Option<PineType>],
    const_strings: &[Option<String>],
    const_bools: &[Option<bool>],
    call_span: Span,
) -> LegacySecurityBinding {
    debug_assert!(dialect.is_legacy());
    let max_args = if dialect <= PineDialect::V2 { 4 } else { 5 };
    let supports_named_args = dialect >= PineDialect::V3;
    let mut ordered = vec![None; max_args];
    let mut diagnostics = Vec::new();
    let mut positional = 0;
    let mut saw_named = false;

    for (source_index, arg) in args.iter().enumerate() {
        let param_index = if let Some(name) = arg.name.as_deref() {
            saw_named = true;
            if !supports_named_args {
                diagnostics.push(Diagnostic::error(
                    "E_CALL_ARG_NAME",
                    format!(
                        "named arguments are not supported by Pine {} `security`",
                        dialect.name()
                    ),
                    arg.span,
                ));
                continue;
            }
            let Some(index) = PARAMS[..max_args]
                .iter()
                .position(|candidate| *candidate == name)
            else {
                diagnostics.push(Diagnostic::error(
                    "E_CALL_ARG_NAME",
                    format!(
                        "`security` has no Pine {} argument named `{name}`",
                        dialect.name()
                    ),
                    arg.span,
                ));
                continue;
            };
            index
        } else {
            if saw_named {
                diagnostics.push(Diagnostic::error(
                    "E_CALL_ARG_ORDER",
                    "positional arguments cannot follow named arguments in legacy `security`",
                    arg.span,
                ));
                continue;
            }
            let index = positional;
            positional += 1;
            if index >= max_args {
                diagnostics.push(Diagnostic::error(
                    "E_CALL_ARITY",
                    format!(
                        "Pine {} `security` expects at most {max_args} argument(s), got {}",
                        dialect.name(),
                        args.len()
                    ),
                    arg.span,
                ));
                continue;
            }
            index
        };

        if ordered[param_index].is_some() {
            diagnostics.push(Diagnostic::error(
                "E_CALL_ARG_DUPLICATE",
                format!(
                    "`security` argument `{}` is provided more than once",
                    PARAMS[param_index]
                ),
                arg.span,
            ));
            continue;
        }
        ordered[param_index] = Some(source_index);
    }

    for (index, param) in PARAMS.iter().take(3).enumerate() {
        if ordered[index].is_none() {
            diagnostics.push(Diagnostic::error(
                "E_CALL_ARITY",
                format!(
                    "`security` is missing required Pine {} argument `{param}`",
                    dialect.name()
                ),
                call_span,
            ));
        }
    }

    let gaps = ordered
        .get(3)
        .copied()
        .flatten()
        .and_then(|index| {
            merge_value(
                "gaps",
                args[index].span,
                const_strings.get(index).and_then(Option::as_deref),
                const_bools.get(index).copied().flatten(),
                &mut diagnostics,
            )
        })
        .map_or(LegacySecurityGaps::Off, |enabled| {
            if enabled {
                LegacySecurityGaps::On
            } else {
                LegacySecurityGaps::Off
            }
        });
    let lookahead = ordered
        .get(4)
        .copied()
        .flatten()
        .and_then(|index| {
            merge_value(
                "lookahead",
                args[index].span,
                const_strings.get(index).and_then(Option::as_deref),
                const_bools.get(index).copied().flatten(),
                &mut diagnostics,
            )
        })
        .map_or_else(
            || {
                if dialect <= PineDialect::V2 {
                    LegacySecurityLookahead::On
                } else {
                    LegacySecurityLookahead::Off
                }
            },
            |enabled| {
                if enabled {
                    LegacySecurityLookahead::On
                } else {
                    LegacySecurityLookahead::Off
                }
            },
        );

    if !diagnostics.is_empty() {
        return LegacySecurityBinding::Invalid(diagnostics);
    }

    let mut canonical_args = Vec::with_capacity(3);
    let mut canonical_arg_types = Vec::with_capacity(3);
    let mut arg_rewrites = vec![
        LegacyCallArgRewrite {
            keep: false,
            canonical_name: None,
        };
        args.len()
    ];
    for param_index in 0..3 {
        let source_index = ordered[param_index].expect("validated required security argument");
        let mut canonical_arg = args[source_index].clone();
        if canonical_arg.name.is_some() {
            canonical_arg.name = Some(CANONICAL_PARAMS[param_index].to_owned());
        }
        canonical_args.push(canonical_arg);
        canonical_arg_types.push(arg_types.get(source_index).copied().flatten());
        arg_rewrites[source_index] = LegacyCallArgRewrite {
            keep: true,
            canonical_name: args[source_index]
                .name
                .as_ref()
                .map(|_| CANONICAL_PARAMS[param_index]),
        };
    }

    LegacySecurityBinding::Bound(BoundLegacySecurity {
        canonical_args,
        canonical_arg_types,
        arg_rewrites,
        gaps,
        lookahead,
        internal_callee: internal_callee(gaps, lookahead),
    })
}

fn merge_value(
    parameter: &str,
    span: Span,
    const_string: Option<&str>,
    const_bool: Option<bool>,
    diagnostics: &mut Vec<Diagnostic>,
) -> Option<bool> {
    if let Some(value) = const_bool {
        return Some(value);
    }
    let expected_prefix = format!("barmerge.{parameter}_");
    if let Some(value) = const_string {
        return match value {
            "barmerge.gaps_off" if parameter == "gaps" => Some(false),
            "barmerge.gaps_on" if parameter == "gaps" => Some(true),
            "barmerge.lookahead_off" if parameter == "lookahead" => Some(false),
            "barmerge.lookahead_on" if parameter == "lookahead" => Some(true),
            _ => {
                diagnostics.push(Diagnostic::error(
                    "E_LEGACY_SECURITY_MERGE",
                    format!(
                        "legacy `security` {parameter} must be a bool or a matching {expected_prefix}off/on constant"
                    ),
                    span,
                ));
                None
            }
        };
    }
    diagnostics.push(Diagnostic::error(
        "E_LEGACY_SECURITY_MERGE",
        format!("legacy `security` {parameter} must be a compile-time bool or barmerge constant"),
        span,
    ));
    None
}

const fn internal_callee(
    gaps: LegacySecurityGaps,
    lookahead: LegacySecurityLookahead,
) -> &'static str {
    match (gaps, lookahead) {
        (LegacySecurityGaps::Off, LegacySecurityLookahead::Off) => {
            "$legacy.security.gaps_off.lookahead_off"
        }
        (LegacySecurityGaps::On, LegacySecurityLookahead::Off) => {
            "$legacy.security.gaps_on.lookahead_off"
        }
        (LegacySecurityGaps::Off, LegacySecurityLookahead::On) => {
            "$legacy.security.gaps_off.lookahead_on"
        }
        (LegacySecurityGaps::On, LegacySecurityLookahead::On) => {
            "$legacy.security.gaps_on.lookahead_on"
        }
    }
}
