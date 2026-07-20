use pine_ir::ValueKind;
use pine_syntax::Span;

use crate::compatibility::{
    CompatibilityReport, LegacyEmulation, LegacyTranslation, LegacyTranslationKind,
};

use super::catalog::{LegacyRule, LegacyRuleKind};
use super::expressions::LegacyExpressionKind;
use super::security::{BoundLegacySecurity, LegacySecurityGaps, LegacySecurityLookahead};

pub(crate) fn record_exact_translation(
    report: &mut CompatibilityReport,
    rule: LegacyRule,
    span: Span,
) {
    let canonical_feature = rule
        .canonical_name
        .expect("validated exact legacy rules have canonical targets");
    let kind = match rule.kind {
        LegacyRuleKind::ExactFunctionAlias => LegacyTranslationKind::ExactAlias,
        LegacyRuleKind::ExactSymbolAlias => LegacyTranslationKind::SymbolAlias,
        _ => panic!("focused legacy rules cannot use exact translation reporting"),
    };
    report.legacy_translations.push(LegacyTranslation {
        source_feature: rule.source_name.to_owned(),
        canonical_feature: canonical_feature.to_owned(),
        kind,
        span,
    });
}

pub(crate) fn record_signature_translation(
    report: &mut CompatibilityReport,
    rule: LegacyRule,
    span: Span,
) {
    let canonical_feature = rule
        .canonical_name
        .expect("validated focused declaration has a canonical target");
    report.legacy_translations.push(LegacyTranslation {
        source_feature: rule.source_name.to_owned(),
        canonical_feature: canonical_feature.to_owned(),
        kind: LegacyTranslationKind::SignatureReshape,
        span,
    });
}

pub(crate) fn record_constant_translation(
    report: &mut CompatibilityReport,
    rule: LegacyRule,
    span: Span,
) {
    let canonical_feature = rule
        .canonical_name
        .expect("validated legacy input constant has a canonical target");
    report.legacy_translations.push(LegacyTranslation {
        source_feature: rule.source_name.to_owned(),
        canonical_feature: canonical_feature.to_owned(),
        kind: LegacyTranslationKind::ConstantAlias,
        span,
    });
}

pub(crate) fn record_input_signature_translation(
    report: &mut CompatibilityReport,
    rule: LegacyRule,
    canonical_feature: &'static str,
    span: Span,
) {
    report.legacy_translations.push(LegacyTranslation {
        source_feature: rule.source_name.to_owned(),
        canonical_feature: canonical_feature.to_owned(),
        kind: LegacyTranslationKind::SignatureReshape,
        span,
    });
}

pub(crate) fn record_output_translation(
    report: &mut CompatibilityReport,
    dialect: crate::PineDialect,
    rule: LegacyRule,
    span: Span,
    requires_adaptation: bool,
    emulates_transparency: bool,
    emulates_numeric_style: bool,
) {
    let version = dialect.version();
    let canonical_feature = rule
        .canonical_name
        .expect("validated legacy output rule has a canonical target");
    if requires_adaptation {
        report.legacy_translations.push(LegacyTranslation {
            source_feature: rule.source_name.to_owned(),
            canonical_feature: canonical_feature.to_owned(),
            kind: LegacyTranslationKind::OutputAdaptation,
            span,
        });
    }
    if emulates_transparency {
        report.legacy_emulations.push(LegacyEmulation {
            feature: format!("{}.transp", rule.source_name),
            behavior: format!("Pine v{version} transparency is applied after the base color; embedded alpha takes precedence and transparency is clamped to 0..100"),
            span,
        });
    }
    if emulates_numeric_style {
        report.legacy_emulations.push(LegacyEmulation {
            feature: format!("{}.numeric_style", rule.source_name),
            behavior: format!("Pine v{version} numeric output styles are mapped by their documented ordinal to canonical style constants"),
            span,
        });
    }
}

pub(crate) fn record_expression_translation(
    report: &mut CompatibilityReport,
    rule: LegacyRule,
    canonical_feature: &'static str,
    kind: LegacyExpressionKind,
    span: Span,
) {
    report.legacy_translations.push(LegacyTranslation {
        source_feature: rule.source_name.to_owned(),
        canonical_feature: canonical_feature.to_owned(),
        kind: LegacyTranslationKind::ExpressionDesugar,
        span,
    });
    let behavior = match kind {
        LegacyExpressionKind::Iff => Some(
            "Pine v1-v4 iff evaluates condition, result1, and result2 exactly once in parameter order before selecting the result",
        ),
        LegacyExpressionKind::RsiSeries => Some(
            "Pine v1-v4 rsi with a non-simple-integer second argument uses the documented two-series arithmetic formula",
        ),
        LegacyExpressionKind::Offset | LegacyExpressionKind::RsiLength => None,
    };
    if let Some(behavior) = behavior {
        report.legacy_emulations.push(LegacyEmulation {
            feature: rule.source_name.to_owned(),
            behavior: behavior.to_owned(),
            span,
        });
    }
}

pub(crate) fn record_security_translation(
    report: &mut CompatibilityReport,
    rule: LegacyRule,
    bound: &BoundLegacySecurity,
    span: Span,
) {
    report.legacy_translations.push(LegacyTranslation {
        source_feature: rule.source_name.to_owned(),
        canonical_feature: "request.security".to_owned(),
        kind: LegacyTranslationKind::SignatureReshape,
        span,
    });
    let behavior = match (bound.gaps, bound.lookahead) {
        (LegacySecurityGaps::Off, LegacySecurityLookahead::Off) => {
            "legacy security uses explicit gaps_off/lookahead_off requested-context alignment"
        }
        (LegacySecurityGaps::On, LegacySecurityLookahead::Off) => {
            "legacy security uses explicit gaps_on/lookahead_off requested-context alignment"
        }
        (LegacySecurityGaps::Off, LegacySecurityLookahead::On) => {
            "legacy security uses explicit gaps_off/lookahead_on historical alignment and confirmed realtime alignment"
        }
        (LegacySecurityGaps::On, LegacySecurityLookahead::On) => {
            "legacy security uses explicit gaps_on/lookahead_on historical alignment and confirmed realtime alignment"
        }
    };
    report.legacy_emulations.push(LegacyEmulation {
        feature: "security.merge".to_owned(),
        behavior: behavior.to_owned(),
        span,
    });
}

pub(crate) fn record_v3_na_inference(
    report: &mut CompatibilityReport,
    span: Span,
    kind: ValueKind,
) {
    report.legacy_emulations.push(LegacyEmulation {
        feature: "v3.untyped_na".to_owned(),
        behavior: format!(
            "Pine v3 untyped na declaration inferred one stable canonical scalar type: {kind:?}"
        ),
        span,
    });
}

pub(crate) fn normalize_legacy_report(report: &mut CompatibilityReport) {
    report.legacy_translations.sort_by(|left, right| {
        (
            left.span.start,
            left.span.end,
            left.source_feature.as_str(),
            left.canonical_feature.as_str(),
            left.kind.name(),
        )
            .cmp(&(
                right.span.start,
                right.span.end,
                right.source_feature.as_str(),
                right.canonical_feature.as_str(),
                right.kind.name(),
            ))
    });
    report.legacy_translations.dedup();

    report.legacy_emulations.sort_by(|left, right| {
        (
            left.span.start,
            left.span.end,
            left.feature.as_str(),
            left.behavior.as_str(),
        )
            .cmp(&(
                right.span.start,
                right.span.end,
                right.feature.as_str(),
                right.behavior.as_str(),
            ))
    });
    report.legacy_emulations.dedup();
}
