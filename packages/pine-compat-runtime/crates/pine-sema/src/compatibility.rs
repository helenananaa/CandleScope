use pine_syntax::Span;

use crate::{PineDialect, ScriptModeClassification, VersionOrigin};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CompatibilityReport {
    pub language_version: Option<u16>,
    pub language_version_origin: VersionOrigin,
    pub dialect: Option<PineDialect>,
    pub script_mode: ScriptModeClassification,
    pub supported: Vec<FeatureUse>,
    pub unsupported: Vec<UnsupportedFeature>,
    pub legacy_translations: Vec<LegacyTranslation>,
    pub legacy_emulations: Vec<LegacyEmulation>,
}

impl Default for CompatibilityReport {
    fn default() -> Self {
        Self {
            language_version: Some(1),
            language_version_origin: VersionOrigin::ImplicitV1,
            dialect: Some(PineDialect::V1),
            script_mode: ScriptModeClassification::Missing,
            supported: Vec::new(),
            unsupported: Vec::new(),
            legacy_translations: Vec::new(),
            legacy_emulations: Vec::new(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FeatureUse {
    pub feature: String,
    pub span: Span,
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UnsupportedFeature {
    pub feature: String,
    pub reason: String,
    pub span: Span,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum LegacyTranslationKind {
    ExactAlias,
    SymbolAlias,
    ConstantAlias,
    ParameterRename,
    SignatureReshape,
    ExpressionDesugar,
    OutputAdaptation,
}

impl LegacyTranslationKind {
    #[must_use]
    pub const fn name(self) -> &'static str {
        match self {
            Self::ExactAlias => "exactAlias",
            Self::SymbolAlias => "symbolAlias",
            Self::ConstantAlias => "constantAlias",
            Self::ParameterRename => "parameterRename",
            Self::SignatureReshape => "signatureReshape",
            Self::ExpressionDesugar => "expressionDesugar",
            Self::OutputAdaptation => "outputAdaptation",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LegacyTranslation {
    pub source_feature: String,
    pub canonical_feature: String,
    pub kind: LegacyTranslationKind,
    pub span: Span,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LegacyEmulation {
    pub feature: String,
    pub behavior: String,
    pub span: Span,
}
