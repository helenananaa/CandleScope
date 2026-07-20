use pine_syntax::{
    CallArg, Diagnostic, Expr, ExprKind, FunctionBody, Program, Span, Stmt, StmtKind,
    SwitchArmResult,
};

use super::dialect::PineDialect;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum ScriptModeClassification {
    LegacyIndicator,
    Indicator,
    Strategy,
    Library,
    Missing,
    Mixed,
}

impl ScriptModeClassification {
    #[must_use]
    pub const fn name(self) -> &'static str {
        match self {
            Self::LegacyIndicator => "legacyIndicator",
            Self::Indicator => "indicator",
            Self::Strategy => "strategy",
            Self::Library => "library",
            Self::Missing => "missing",
            Self::Mixed => "mixed",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct LegacyAdmissionFailure {
    pub(crate) code: &'static str,
    pub(crate) message: String,
    pub(crate) feature: String,
    pub(crate) reason: String,
    pub(crate) span: Span,
}

#[derive(Debug, Clone, Copy)]
struct DeclarationCall<'a> {
    name: &'a str,
    span: Span,
}

#[derive(Debug, Clone)]
pub(crate) struct BoundLegacyStudy {
    pub(crate) canonical_args: Vec<CallArg>,
    pub(crate) canonical_arg_names: Vec<Option<&'static str>>,
}

#[derive(Debug, Clone)]
pub(crate) struct LegacyStudyUnsupported {
    pub(crate) feature: &'static str,
    pub(crate) reason: &'static str,
    pub(crate) span: Span,
}

#[derive(Debug, Clone)]
pub(crate) enum LegacyStudyBinding {
    Bound(BoundLegacyStudy),
    Invalid(Vec<Diagnostic>),
    Unsupported(LegacyStudyUnsupported),
}

#[derive(Debug, Clone, Copy)]
struct StudyParam {
    source_name: &'static str,
    canonical_name: Option<&'static str>,
    unsupported: Option<StudyUnsupportedKind>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum StudyUnsupportedKind {
    Timeframe,
    ExplicitPlotZOrder,
}

const V4_STUDY_PARAMS: &[StudyParam] = &[
    StudyParam::supported("title", "title"),
    StudyParam::supported("shorttitle", "shorttitle"),
    StudyParam::supported("overlay", "overlay"),
    StudyParam::supported("format", "format"),
    StudyParam::supported("precision", "precision"),
    StudyParam::supported("scale", "scale"),
    StudyParam::supported("max_bars_back", "max_bars_back"),
    StudyParam::supported("max_lines_count", "max_lines_count"),
    StudyParam::supported("max_labels_count", "max_labels_count"),
    StudyParam::unsupported("resolution", StudyUnsupportedKind::Timeframe),
    StudyParam::unsupported("resolution_gaps", StudyUnsupportedKind::Timeframe),
    StudyParam::supported("max_boxes_count", "max_boxes_count"),
    StudyParam::unsupported(
        "explicit_plot_zorder",
        StudyUnsupportedKind::ExplicitPlotZOrder,
    ),
];

const V3_STUDY_PARAMS: &[StudyParam] = &[
    StudyParam::supported("title", "title"),
    StudyParam::supported("shorttitle", "shorttitle"),
    StudyParam::supported("overlay", "overlay"),
    StudyParam::supported("precision", "precision"),
];

impl StudyParam {
    const fn supported(source_name: &'static str, canonical_name: &'static str) -> Self {
        Self {
            source_name,
            canonical_name: Some(canonical_name),
            unsupported: None,
        }
    }

    const fn unsupported(source_name: &'static str, unsupported: StudyUnsupportedKind) -> Self {
        Self {
            source_name,
            canonical_name: None,
            unsupported: Some(unsupported),
        }
    }
}

pub(crate) fn bind_legacy_study_args(dialect: PineDialect, args: &[CallArg]) -> LegacyStudyBinding {
    let params = match dialect {
        PineDialect::V1 | PineDialect::V2 | PineDialect::V3 => V3_STUDY_PARAMS,
        PineDialect::V4 => V4_STUDY_PARAMS,
        PineDialect::V5 | PineDialect::V6 => {
            unreachable!("only Pine v1-v4 study declarations use the legacy binder")
        }
    };
    let version = dialect.version();
    let mut canonical_args = Vec::with_capacity(args.len());
    let mut canonical_arg_names = Vec::with_capacity(args.len());
    let mut bound = vec![false; params.len()];
    let mut diagnostics = Vec::new();
    let mut saw_named = false;
    let mut unsupported: Option<(StudyUnsupportedKind, Span)> = None;

    for (arg_index, arg) in args.iter().enumerate() {
        let param_index = if let Some(name) = arg.name.as_deref() {
            saw_named = true;
            let Some(param_index) = params.iter().position(|param| param.source_name == name)
            else {
                diagnostics.push(Diagnostic::error(
                    "E_CALL_ARG_NAME",
                    format!("`study` has no argument named `{name}` in Pine v{version}"),
                    arg.span,
                ));
                continue;
            };
            param_index
        } else {
            if saw_named {
                diagnostics.push(Diagnostic::error(
                    "E_CALL_ARG_ORDER",
                    format!(
                        "positional arguments cannot follow named arguments in Pine v{version} `study`"
                    ),
                    arg.span,
                ));
                continue;
            }
            if arg_index >= params.len() {
                diagnostics.push(Diagnostic::error(
                    "E_CALL_ARITY",
                    format!(
                        "`study` expects at most {} argument(s) in Pine v{version}, got {}",
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
                    "`study` argument `{}` is provided more than once",
                    param.source_name
                ),
                arg.span,
            ));
            continue;
        }
        bound[param_index] = true;

        if let Some(kind) = param.unsupported {
            unsupported = Some(match unsupported {
                Some((existing_kind, existing_span)) => {
                    let kind = if existing_kind == StudyUnsupportedKind::Timeframe {
                        existing_kind
                    } else {
                        kind
                    };
                    (kind, existing_span.merge(arg.span))
                }
                None => (kind, arg.span),
            });
            continue;
        }

        let canonical_name = param
            .canonical_name
            .expect("supported v4 study parameter has a canonical target");
        let mut canonical_arg = arg.clone();
        canonical_arg.name = Some(canonical_name.to_owned());
        canonical_args.push(canonical_arg);
        canonical_arg_names.push(Some(canonical_name));
    }

    if !bound[0] {
        diagnostics.push(Diagnostic::error(
            "E_CALL_ARITY",
            format!("`study` is missing required Pine v{version} argument `title`"),
            args.first().map_or_else(Span::default, |arg| arg.span),
        ));
    }

    if let Some((kind, span)) = unsupported {
        return LegacyStudyBinding::Unsupported(match kind {
            StudyUnsupportedKind::Timeframe => LegacyStudyUnsupported {
                feature: "study.resolution",
                reason: "Pine v4 resolution/resolution_gaps declaration semantics are deferred to the legacy security and timeframe phase",
                span,
            },
            StudyUnsupportedKind::ExplicitPlotZOrder => LegacyStudyUnsupported {
                feature: "study.explicit_plot_zorder",
                reason: "the current canonical indicator contract has no verified equivalent for Pine v4 explicit_plot_zorder",
                span,
            },
        });
    }
    if !diagnostics.is_empty() {
        return LegacyStudyBinding::Invalid(diagnostics);
    }

    LegacyStudyBinding::Bound(BoundLegacyStudy {
        canonical_args,
        canonical_arg_names,
    })
}

pub(crate) fn classify_script_mode(program: &Program) -> ScriptModeClassification {
    let declarations = declaration_calls(program);
    if declarations.len() > 1 {
        return ScriptModeClassification::Mixed;
    }
    if let Some(declaration) = declarations.first() {
        return match declaration.name {
            "study" => ScriptModeClassification::LegacyIndicator,
            "indicator" => ScriptModeClassification::Indicator,
            "strategy" => ScriptModeClassification::Strategy,
            "library" => ScriptModeClassification::Library,
            _ => ScriptModeClassification::Missing,
        };
    }
    ScriptModeClassification::Missing
}

pub(crate) fn legacy_admission_failure(
    program: &Program,
    dialect: PineDialect,
) -> Option<LegacyAdmissionFailure> {
    if !dialect.is_legacy() {
        return None;
    }

    if let Some(span) = find_strategy_reference(program) {
        return Some(LegacyAdmissionFailure {
            code: "E_LEGACY_STRATEGY_OUT_OF_SCOPE",
            message: format!(
                "legacy {} strategy declarations and strategy.* features are out of scope; only legacy indicators are supported",
                dialect.name()
            ),
            feature: "legacy strategy".to_owned(),
            reason: "legacy strategies are excluded from the indicator compatibility pipeline"
                .to_owned(),
            span,
        });
    }

    let declarations = declaration_calls(program);
    match declarations.as_slice() {
        [] => Some(LegacyAdmissionFailure {
            code: "E_LEGACY_INDICATOR_DECLARATION",
            message: format!(
                "legacy {} source requires exactly one top-level study(...) indicator declaration",
                dialect.name()
            ),
            feature: "legacy indicator declaration".to_owned(),
            reason: "legacy source has no recognized top-level study(...) declaration".to_owned(),
            span: program
                .statements
                .first()
                .map_or_else(|| Span::new(0, 0), |statement| statement.span),
        }),
        [declaration]
            if declaration.name == "study"
                && matches!(
                    dialect,
                    PineDialect::V1 | PineDialect::V2 | PineDialect::V3 | PineDialect::V4
                ) =>
        {
            None
        }
        [declaration] if declaration.name == "indicator" => Some(LegacyAdmissionFailure {
            code: "E_LEGACY_INDICATOR_DECLARATION",
            message: format!(
                "indicator(...) is not a valid {} declaration; use study(...) or select Pine v5/v6 explicitly",
                dialect.name()
            ),
            feature: "indicator".to_owned(),
            reason: "modern indicator(...) is not silently accepted in legacy source".to_owned(),
            span: declaration.span,
        }),
        [declaration] => Some(LegacyAdmissionFailure {
            code: "E_LEGACY_INDICATOR_DECLARATION",
            message: format!(
                "legacy {} source requires study(...); {}(...) is not an eligible indicator declaration",
                dialect.name(),
                declaration.name
            ),
            feature: declaration.name.to_owned(),
            reason: "source declaration is not an eligible legacy indicator declaration".to_owned(),
            span: declaration.span,
        }),
        _ => Some(LegacyAdmissionFailure {
            code: "E_LEGACY_INDICATOR_DECLARATION",
            message: format!(
                "legacy {} source must contain exactly one top-level study(...) declaration",
                dialect.name()
            ),
            feature: "legacy indicator declaration".to_owned(),
            reason: "multiple script declarations cannot be classified as one legacy indicator"
                .to_owned(),
            span: declarations.first().zip(declarations.last()).map_or_else(
                || Span::new(0, 0),
                |(first, last)| first.span.merge(last.span),
            ),
        }),
    }
}

fn declaration_calls(program: &Program) -> Vec<DeclarationCall<'_>> {
    // Pine user functions are collected before call analysis and shadow an
    // equally named built-in regardless of their textual order. Admission
    // must apply the same rule; otherwise a UDF named `study` can make an
    // arbitrary legacy source look like it contains a real script
    // declaration.
    let user_functions = program
        .statements
        .iter()
        .filter_map(|statement| match &statement.kind {
            StmtKind::Function { name, .. } => Some(name.as_str()),
            _ => None,
        })
        .collect::<std::collections::HashSet<_>>();
    program
        .statements
        .iter()
        .filter_map(|statement| {
            if matches!(statement.kind, StmtKind::Library(_)) {
                return Some(DeclarationCall {
                    name: "library",
                    span: statement.span,
                });
            }
            let StmtKind::Expr(Expr {
                kind: ExprKind::Call { callee, .. },
                ..
            }) = &statement.kind
            else {
                return None;
            };
            let ExprKind::Identifier(name) = &callee.kind else {
                return None;
            };
            if user_functions.contains(name.as_str()) {
                return None;
            }
            matches!(name.as_str(), "study" | "indicator" | "strategy").then_some(DeclarationCall {
                name,
                span: callee.span,
            })
        })
        .collect()
}

fn find_strategy_reference(program: &Program) -> Option<Span> {
    program
        .statements
        .iter()
        .find_map(find_strategy_reference_in_statement)
}

fn find_strategy_reference_in_statement(statement: &Stmt) -> Option<Span> {
    match &statement.kind {
        StmtKind::Expr(expr)
        | StmtKind::Decl { value: expr, .. }
        | StmtKind::Reassign { value: expr, .. }
        | StmtKind::FieldReassign { value: expr, .. }
        | StmtKind::TupleDecl { value: expr, .. } => find_strategy_reference_in_expr(expr),
        StmtKind::ArrayFieldReassign {
            array,
            index,
            value,
            ..
        } => [array, index, value]
            .into_iter()
            .find_map(find_strategy_reference_in_expr),
        StmtKind::If {
            condition,
            then_branch,
            else_branch,
        } => find_strategy_reference_in_expr(condition).or_else(|| {
            then_branch
                .iter()
                .chain(else_branch)
                .find_map(find_strategy_reference_in_statement)
        }),
        StmtKind::For {
            from,
            to,
            step,
            body,
            ..
        } => find_strategy_reference_in_expr(from)
            .or_else(|| find_strategy_reference_in_expr(to))
            .or_else(|| step.as_ref().and_then(find_strategy_reference_in_expr))
            .or_else(|| body.iter().find_map(find_strategy_reference_in_statement)),
        StmtKind::ForIn { iterable, body, .. } => find_strategy_reference_in_expr(iterable)
            .or_else(|| body.iter().find_map(find_strategy_reference_in_statement)),
        StmtKind::While { condition, body } => find_strategy_reference_in_expr(condition)
            .or_else(|| body.iter().find_map(find_strategy_reference_in_statement)),
        StmtKind::Function { body, .. } => find_strategy_reference_in_function_body(body),
        StmtKind::Export(export) => match &export.item {
            pine_syntax::ExportItem::Const { value, .. } => find_strategy_reference_in_expr(value),
            pine_syntax::ExportItem::Function { body, .. } => {
                find_strategy_reference_in_function_body(body)
            }
            pine_syntax::ExportItem::UserType { .. } | pine_syntax::ExportItem::Unknown { .. } => {
                None
            }
        },
        StmtKind::Method(method) => find_strategy_reference_in_function_body(&method.body),
        StmtKind::Import(_)
        | StmtKind::Library(_)
        | StmtKind::UserType(_)
        | StmtKind::Break
        | StmtKind::Continue
        | StmtKind::Unsupported { .. } => None,
    }
}

fn find_strategy_reference_in_function_body(body: &FunctionBody) -> Option<Span> {
    match body {
        FunctionBody::Expr(expr) => find_strategy_reference_in_expr(expr),
        FunctionBody::Block(statements) => statements
            .iter()
            .find_map(find_strategy_reference_in_statement),
    }
}

fn find_strategy_reference_in_expr(expr: &Expr) -> Option<Span> {
    if matches!(
        &expr.kind,
        ExprKind::QualifiedName(parts) if parts.first().is_some_and(|part| part == "strategy")
    ) {
        return Some(expr.span);
    }

    match &expr.kind {
        ExprKind::Call { callee, args } => {
            if matches!(&callee.kind, ExprKind::Identifier(name) if name == "strategy") {
                return Some(callee.span);
            }
            find_strategy_reference_in_expr(callee).or_else(|| {
                args.iter()
                    .find_map(|arg| find_strategy_reference_in_expr(&arg.value))
            })
        }
        ExprKind::Unary { expr, .. } | ExprKind::History { expr, .. } => {
            find_strategy_reference_in_expr(expr)
        }
        ExprKind::Binary { left, right, .. } => {
            find_strategy_reference_in_expr(left).or_else(|| find_strategy_reference_in_expr(right))
        }
        ExprKind::Ternary {
            condition,
            then_expr,
            else_expr,
        } => find_strategy_reference_in_expr(condition)
            .or_else(|| find_strategy_reference_in_expr(then_expr))
            .or_else(|| find_strategy_reference_in_expr(else_expr)),
        ExprKind::If {
            condition,
            then_branch,
            else_branch,
        } => find_strategy_reference_in_expr(condition).or_else(|| {
            then_branch
                .iter()
                .chain(else_branch)
                .find_map(find_strategy_reference_in_statement)
        }),
        ExprKind::For {
            from,
            to,
            step,
            body,
            ..
        } => find_strategy_reference_in_expr(from)
            .or_else(|| find_strategy_reference_in_expr(to))
            .or_else(|| step.as_deref().and_then(find_strategy_reference_in_expr))
            .or_else(|| body.iter().find_map(find_strategy_reference_in_statement)),
        ExprKind::ForIn { iterable, body, .. } => find_strategy_reference_in_expr(iterable)
            .or_else(|| body.iter().find_map(find_strategy_reference_in_statement)),
        ExprKind::While { condition, body } => find_strategy_reference_in_expr(condition)
            .or_else(|| body.iter().find_map(find_strategy_reference_in_statement)),
        ExprKind::Switch { selector, arms } => selector
            .as_deref()
            .and_then(find_strategy_reference_in_expr)
            .or_else(|| {
                arms.iter().find_map(|arm| {
                    arm.condition
                        .as_ref()
                        .and_then(find_strategy_reference_in_expr)
                        .or_else(|| match &arm.result {
                            SwitchArmResult::Expr(expr) => find_strategy_reference_in_expr(expr),
                            SwitchArmResult::Block(statements) => statements
                                .iter()
                                .find_map(find_strategy_reference_in_statement),
                        })
                })
            }),
        ExprKind::Tuple(values) => values.iter().find_map(find_strategy_reference_in_expr),
        ExprKind::Literal(_) | ExprKind::Identifier(_) | ExprKind::QualifiedName(_) => None,
    }
}
