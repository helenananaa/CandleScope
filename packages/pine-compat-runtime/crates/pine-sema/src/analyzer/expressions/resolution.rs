use crate::prelude::*;

impl Analyzer {
    pub(crate) fn resolve_qualified_value(&mut self, name: &str, span: Span) -> Option<PineType> {
        if let Some(min_version) = crate::PineDialect::qualified_builtin_min_version(name, false)
            && self.legacy.dialect().version() < min_version
        {
            self.reject_unavailable_legacy_builtin(name, min_version, span);
            return None;
        }
        self.resolve_qualified_value_canonical(name, span)
    }

    fn resolve_qualified_value_canonical(&mut self, name: &str, span: Span) -> Option<PineType> {
        if self.validate_strategy_state_variable(name, span) {
            return None;
        }
        if pine_builtins::named_color(name).is_some() {
            self.compatibility.supported.push(FeatureUse {
                feature: name.to_owned(),
                span,
            });
            return Some(PineType::new(Qualifier::Const, ValueKind::Color));
        }
        if let Some(pine_type) = pine_builtins::builtin_series_value_type(name) {
            self.compatibility.supported.push(FeatureUse {
                feature: name.to_owned(),
                span,
            });
            return Some(pine_type);
        }
        if pine_builtins::named_float_constant(name).is_some() {
            self.compatibility.supported.push(FeatureUse {
                feature: name.to_owned(),
                span,
            });
            return Some(PineType::new(Qualifier::Const, ValueKind::Float));
        }
        if pine_builtins::named_int_constant(name).is_some() {
            self.compatibility.supported.push(FeatureUse {
                feature: name.to_owned(),
                span,
            });
            return Some(PineType::new(Qualifier::Const, ValueKind::Int));
        }
        if pine_builtins::named_string_constant(name).is_some() {
            self.compatibility.supported.push(FeatureUse {
                feature: name.to_owned(),
                span,
            });
            return Some(PineType::new(Qualifier::Const, ValueKind::String));
        }
        if let Some(resolution) = self.legacy.resolve_value(name) {
            return self.resolve_legacy_value(name, span, resolution);
        }

        self.check_feature_name(name, span);
        if name.starts_with("color.") {
            self.diagnostics.push(Diagnostic::error(
                "E_UNKNOWN_COLOR",
                format!("unknown named color `{name}`"),
                span,
            ));
        }
        None
    }

    pub(crate) fn resolve_symbol(&mut self, name: &str, span: Span) -> Option<PineType> {
        if let Some(symbol) = self.scope.resolve(name) {
            self.bind_symbol(name, span, symbol);
            Some(symbol.pine_type)
        } else if let Some(resolution) = self.legacy.resolve_value(name) {
            self.resolve_legacy_value(name, span, resolution)
        } else {
            self.diagnostics.push(Diagnostic::error(
                "E_UNKNOWN_SYMBOL",
                format!("unknown symbol `{name}`"),
                span,
            ));
            None
        }
    }

    fn resolve_legacy_value(
        &mut self,
        _name: &str,
        span: Span,
        resolution: crate::legacy::LegacyResolution,
    ) -> Option<PineType> {
        match resolution {
            crate::legacy::LegacyResolution::ExactAlias(rule) => {
                let canonical_name = rule
                    .canonical_name
                    .expect("validated exact legacy alias has a canonical target");
                let pine_type = self
                    .resolve_qualified_value_canonical(canonical_name, span)
                    .expect("validated exact legacy symbol target is registered");
                let source_context_id = self.current_source_context_id();
                self.legacy.record_value_translation(
                    &mut self.compatibility,
                    source_context_id,
                    span,
                    rule,
                );
                self.expr_types.insert(self.expr_key(span), pine_type);
                Some(pine_type)
            }
            crate::legacy::LegacyResolution::Focused(rule) => {
                if rule.kind != crate::legacy::LegacyRuleKind::FocusedInputConstant {
                    unreachable!("supported focused legacy value has no analyzer owner")
                }
                let source_context_id = self.current_source_context_id();
                self.legacy.record_input_constant_translation(
                    &mut self.compatibility,
                    source_context_id,
                    span,
                    rule,
                );
                let pine_type = PineType::new(Qualifier::Const, ValueKind::String);
                self.expr_types.insert(self.expr_key(span), pine_type);
                Some(pine_type)
            }
            crate::legacy::LegacyResolution::UnsupportedKnown(rule) => {
                let crate::legacy::LegacyRuleSupport::UnsupportedKnown { reason } = rule.support
                else {
                    unreachable!("legacy resolver preserves rule support state")
                };
                self.unsupported(rule.source_name, reason, span);
                None
            }
        }
    }
}
