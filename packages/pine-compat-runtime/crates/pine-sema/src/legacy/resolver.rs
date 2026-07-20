use super::PineDialect;
use super::catalog::{LEGACY_RULES, LegacyRule, LegacyRuleKind, LegacyRuleSupport, matching_rules};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum LegacyResolution {
    ExactAlias(LegacyRule),
    Focused(LegacyRule),
    UnsupportedKnown(LegacyRule),
}

#[derive(Debug, Clone, Copy)]
pub(crate) struct LegacyResolver {
    dialect: PineDialect,
    rules: &'static [LegacyRule],
}

impl LegacyResolver {
    pub(crate) const fn new(dialect: PineDialect) -> Self {
        Self {
            dialect,
            rules: LEGACY_RULES,
        }
    }

    pub(crate) const fn with_rules(dialect: PineDialect, rules: &'static [LegacyRule]) -> Self {
        Self { dialect, rules }
    }

    pub(crate) fn resolve_call(self, source_name: &str) -> Option<LegacyResolution> {
        self.resolve(source_name, LegacyRuleKind::is_call)
    }

    pub(crate) fn resolve_value(self, source_name: &str) -> Option<LegacyResolution> {
        self.resolve(source_name, LegacyRuleKind::is_value)
    }

    fn resolve(
        self,
        source_name: &str,
        accepts: impl Fn(LegacyRuleKind) -> bool,
    ) -> Option<LegacyResolution> {
        matching_rules(self.rules, source_name)
            .iter()
            .copied()
            .find(|rule| rule.applies_to(self.dialect) && accepts(rule.kind))
            .map(|rule| match rule.support {
                LegacyRuleSupport::Supported if rule.kind.is_exact() => {
                    LegacyResolution::ExactAlias(rule)
                }
                LegacyRuleSupport::Supported => LegacyResolution::Focused(rule),
                LegacyRuleSupport::UnsupportedKnown { .. } => {
                    LegacyResolution::UnsupportedKnown(rule)
                }
            })
    }
}
