mod catalog;
mod declarations;
mod dialect;
mod expressions;
mod inputs;
mod lowering;
mod outputs;
mod report;
mod resolver;
mod security;
mod v2_declarations;

use pine_ir::PineType;
use pine_syntax::{CallArg, Expr, Program, Span};

pub use catalog::{
    LEGACY_RULES, LEGACY_TRANSLATOR_REVISION, LegacyRule, LegacyRuleKind, LegacyRuleSupport,
};
pub use declarations::ScriptModeClassification;
pub use dialect::{
    MAX_PINE_LANGUAGE_VERSION, MIN_PINE_LANGUAGE_VERSION, PineDialect, VersionOrigin,
};

#[cfg(test)]
pub(crate) use catalog::{CatalogValidationError, validate_catalog};
pub(crate) use declarations::LegacyStudyBinding;
pub(crate) use declarations::{LegacyAdmissionFailure, legacy_admission_failure};
pub(crate) use dialect::LanguageSelection;
pub(crate) use expressions::{
    BoundLegacyExpression, LegacyExpressionBinding, LegacyExpressionKind,
};
pub(crate) use inputs::LegacyInputBinding;
pub(crate) use lowering::LegacyCallLowering;
pub(crate) use outputs::LegacyOutputBinding;
pub(crate) use report::normalize_legacy_report;
pub(crate) use resolver::LegacyResolution;
pub(crate) use security::{BoundLegacySecurity, LegacySecurityBinding};
pub(crate) use v2_declarations::LegacyV2DeclarationPlan;

use crate::compatibility::CompatibilityReport;
use crate::source_graph::SourceContextId;

#[derive(Debug)]
pub(crate) struct LegacyFrontEnd {
    dialect: PineDialect,
    resolver: resolver::LegacyResolver,
    lowering: lowering::LegacyLoweringPlan,
}

pub(crate) struct LegacyOutputTranslationPlan {
    pub(crate) canonical_name: &'static str,
    pub(crate) arg_rewrites: Vec<lowering::LegacyCallArgRewrite>,
    pub(crate) requires_adaptation: bool,
    pub(crate) emulates_transparency: bool,
    pub(crate) emulates_numeric_style: bool,
}

impl LegacyFrontEnd {
    pub(crate) fn new(dialect: PineDialect) -> Self {
        debug_assert!(catalog::validate_catalog(LEGACY_RULES).is_empty());
        Self {
            dialect,
            resolver: resolver::LegacyResolver::new(dialect),
            lowering: lowering::LegacyLoweringPlan::new(),
        }
    }

    pub(crate) fn with_rules(dialect: PineDialect, rules: &'static [LegacyRule]) -> Self {
        Self {
            dialect,
            resolver: resolver::LegacyResolver::with_rules(dialect, rules),
            lowering: lowering::LegacyLoweringPlan::new(),
        }
    }

    pub(crate) fn bind_legacy_study_args(&self, args: &[CallArg]) -> LegacyStudyBinding {
        declarations::bind_legacy_study_args(self.dialect, args)
    }

    pub(crate) const fn dialect(&self) -> PineDialect {
        self.dialect
    }

    pub(crate) fn explicit_legacy_input_type_expr<'a>(
        &self,
        args: &'a [CallArg],
    ) -> Option<&'a Expr> {
        inputs::explicit_type_expr(args)
    }

    pub(crate) fn bind_legacy_input_args(
        &self,
        args: &[CallArg],
        arg_types: &[Option<PineType>],
        explicit_type_marker: Option<&str>,
    ) -> LegacyInputBinding {
        inputs::bind_legacy_input_args(self.dialect, args, arg_types, explicit_type_marker)
    }

    pub(crate) fn bind_legacy_output_args(
        &self,
        name: &str,
        args: &[CallArg],
        arg_types: &[Option<PineType>],
        const_strings: &[Option<String>],
        const_ints: &[Option<i64>],
    ) -> LegacyOutputBinding {
        outputs::bind_legacy_output_args(
            self.dialect,
            name,
            args,
            arg_types,
            const_strings,
            const_ints,
        )
    }

    pub(crate) fn bind_legacy_expression(
        &self,
        name: &str,
        args: &[CallArg],
        arg_types: &[Option<PineType>],
        call_span: Span,
    ) -> LegacyExpressionBinding {
        expressions::bind_legacy_expression(name, args, arg_types, call_span)
    }

    pub(crate) fn bind_legacy_security_args(
        &self,
        args: &[CallArg],
        arg_types: &[Option<PineType>],
        const_strings: &[Option<String>],
        const_bools: &[Option<bool>],
        call_span: Span,
    ) -> LegacySecurityBinding {
        security::bind_legacy_security_args(
            self.dialect,
            args,
            arg_types,
            const_strings,
            const_bools,
            call_span,
        )
    }

    pub(crate) fn resolve_call(&self, source_name: &str) -> Option<LegacyResolution> {
        self.resolver.resolve_call(source_name)
    }

    pub(crate) fn resolve_value(&self, source_name: &str) -> Option<LegacyResolution> {
        self.resolver.resolve_value(source_name)
    }

    pub(crate) fn record_call_translation(
        &mut self,
        report: &mut CompatibilityReport,
        source_context_id: SourceContextId,
        span: Span,
        rule: LegacyRule,
    ) {
        let canonical_name = rule
            .canonical_name
            .expect("validated exact legacy rule has a canonical target");
        self.lowering
            .record_call(source_context_id, span, canonical_name);
        report::record_exact_translation(report, rule, span);
    }

    pub(crate) fn record_value_translation(
        &mut self,
        report: &mut CompatibilityReport,
        source_context_id: SourceContextId,
        span: Span,
        rule: LegacyRule,
    ) {
        let canonical_name = rule
            .canonical_name
            .expect("validated exact legacy rule has a canonical target");
        self.lowering
            .record_value(source_context_id, span, canonical_name);
        report::record_exact_translation(report, rule, span);
    }

    pub(crate) fn record_input_constant_translation(
        &mut self,
        report: &mut CompatibilityReport,
        source_context_id: SourceContextId,
        span: Span,
        rule: LegacyRule,
    ) -> &'static str {
        let constant = inputs::input_constant(rule.source_name)
            .expect("supported focused input constant has a marker");
        debug_assert_eq!(rule.canonical_name, Some(constant.canonical_name));
        self.lowering
            .record_string_value(source_context_id, span, constant.marker);
        report::record_constant_translation(report, rule, span);
        constant.marker
    }

    pub(crate) fn record_declaration_translation(
        &mut self,
        report: &mut CompatibilityReport,
        source_context_id: SourceContextId,
        span: Span,
        rule: LegacyRule,
        canonical_arg_names: Vec<Option<&'static str>>,
    ) {
        let canonical_name = rule
            .canonical_name
            .expect("validated focused declaration has a canonical target");
        self.lowering
            .record_call(source_context_id, span, canonical_name);
        self.lowering
            .record_call_arg_names(source_context_id, span, canonical_arg_names);
        report::record_signature_translation(report, rule, span);
    }

    pub(crate) fn record_input_translation(
        &mut self,
        report: &mut CompatibilityReport,
        source_context_id: SourceContextId,
        span: Span,
        rule: LegacyRule,
        canonical_name: &'static str,
        arg_rewrites: Vec<lowering::LegacyCallArgRewrite>,
    ) {
        self.lowering
            .record_call(source_context_id, span, canonical_name);
        self.lowering
            .record_call_arg_rewrites(source_context_id, span, arg_rewrites);
        report::record_input_signature_translation(report, rule, canonical_name, span);
    }

    pub(crate) fn record_output_translation(
        &mut self,
        report: &mut CompatibilityReport,
        source_context_id: SourceContextId,
        span: Span,
        rule: LegacyRule,
        plan: LegacyOutputTranslationPlan,
    ) {
        self.lowering
            .record_call(source_context_id, span, plan.canonical_name);
        self.lowering
            .record_call_arg_rewrites(source_context_id, span, plan.arg_rewrites);
        report::record_output_translation(
            report,
            self.dialect,
            rule,
            span,
            plan.requires_adaptation,
            plan.emulates_transparency,
            plan.emulates_numeric_style,
        );
    }

    pub(crate) fn record_security_translation(
        &mut self,
        report: &mut CompatibilityReport,
        source_context_id: SourceContextId,
        callee_span: Span,
        call_span: Span,
        rule: LegacyRule,
        bound: &BoundLegacySecurity,
    ) {
        self.lowering
            .record_call(source_context_id, callee_span, bound.internal_callee);
        self.lowering.record_call_lowering(
            source_context_id,
            callee_span,
            lowering::LegacyCallLowering::SecuritySpan {
                start: call_span.start,
                end: call_span.end,
            },
        );
        self.lowering.record_call_arg_rewrites(
            source_context_id,
            callee_span,
            bound.arg_rewrites.clone(),
        );
        report::record_security_translation(report, rule, bound, callee_span);
    }

    pub(crate) fn record_expression_translation(
        &mut self,
        report: &mut CompatibilityReport,
        source_context_id: SourceContextId,
        span: Span,
        rule: LegacyRule,
        bound: &BoundLegacyExpression,
    ) {
        use expressions::LegacyExpressionKind;
        use lowering::LegacyCallLowering;

        let canonical_feature = match bound.kind {
            LegacyExpressionKind::Iff => {
                self.lowering
                    .record_call(source_context_id, span, "$legacy.iff");
                "eager select"
            }
            LegacyExpressionKind::Offset => {
                self.lowering.record_call_lowering(
                    source_context_id,
                    span,
                    LegacyCallLowering::HistoryOffset,
                );
                "history access"
            }
            LegacyExpressionKind::RsiLength => {
                self.lowering.record_call(source_context_id, span, "ta.rsi");
                "ta.rsi"
            }
            LegacyExpressionKind::RsiSeries => {
                self.lowering
                    .record_call(source_context_id, span, "$legacy.rsi_series");
                "legacy RSI two-series formula"
            }
        };
        self.lowering
            .record_call_arg_rewrites(source_context_id, span, bound.arg_rewrites.clone());
        report::record_expression_translation(report, rule, canonical_feature, bound.kind, span);
    }

    pub(crate) fn record_v3_na_inference(
        &self,
        report: &mut CompatibilityReport,
        span: Span,
        kind: pine_ir::ValueKind,
    ) {
        debug_assert_eq!(self.dialect, PineDialect::V3);
        report::record_v3_na_inference(report, span, kind);
    }

    pub(crate) fn canonical_call_name(
        &self,
        source_context_id: SourceContextId,
        span: Span,
    ) -> Option<&'static str> {
        self.lowering.call_name(source_context_id, span)
    }

    pub(crate) fn canonical_value_name(
        &self,
        source_context_id: SourceContextId,
        span: Span,
    ) -> Option<&'static str> {
        self.lowering.value_name(source_context_id, span)
    }

    pub(crate) fn canonical_call_arg_rewrites(
        &self,
        source_context_id: SourceContextId,
        span: Span,
    ) -> Option<&[lowering::LegacyCallArgRewrite]> {
        self.lowering.call_arg_rewrites(source_context_id, span)
    }

    pub(crate) fn call_lowering(
        &self,
        source_context_id: SourceContextId,
        span: Span,
    ) -> Option<lowering::LegacyCallLowering> {
        self.lowering.call_lowering(source_context_id, span)
    }

    pub(crate) fn canonical_string_value(
        &self,
        source_context_id: SourceContextId,
        span: Span,
    ) -> Option<&'static str> {
        self.lowering.string_value(source_context_id, span)
    }
}

#[derive(Debug, Clone)]
pub(crate) struct SourcePolicy {
    pub(crate) language: LanguageSelection,
    pub(crate) script_mode: ScriptModeClassification,
    pub(crate) legacy_admission_failure: Option<LegacyAdmissionFailure>,
}

impl SourcePolicy {
    pub(crate) fn from_program_with_implicit(
        program: &Program,
        implicit_dialect: PineDialect,
    ) -> Self {
        let language = LanguageSelection::from_program_with_implicit(program, implicit_dialect);
        let script_mode = declarations::classify_script_mode(program);
        let legacy_admission_failure = language
            .dialect
            .and_then(|dialect| legacy_admission_failure(program, dialect));
        Self {
            language,
            script_mode,
            legacy_admission_failure,
        }
    }
}
