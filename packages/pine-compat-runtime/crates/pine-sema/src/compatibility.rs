use pine_syntax::Span;

#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct CompatibilityReport {
    pub language_version: Option<u16>,
    pub supported: Vec<FeatureUse>,
    pub unsupported: Vec<UnsupportedFeature>,
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
