use std::cell::Cell;
use std::collections::{HashMap, HashSet};

use pine_ir::{HirProgram, Qualifier, ValueKind};
use pine_syntax::{Diagnostic, SourceFile};

use crate::analyzer::context::Analyzer;
use crate::compatibility::{CompatibilityReport, UnsupportedFeature};
use crate::modules::validate_modules;
use crate::resolver::ScopeResolver;
use crate::source_graph::AnalysisInput;
use crate::source_graph::SourceContextId;
use crate::symbols::{
    initial_series_count, initial_symbol_count, initial_symbol_order, initial_symbols,
};

#[derive(Debug, Clone, PartialEq)]
pub struct Analysis {
    pub diagnostics: Vec<Diagnostic>,
    pub compatibility: CompatibilityReport,
    pub hir: Option<HirProgram>,
}

pub fn analyze_source(source: &SourceFile) -> Analysis {
    analyze_input(&AnalysisInput::new(source.clone()))
}

pub fn analyze_input(input: &AnalysisInput) -> Analysis {
    analyze_validated_modules(validate_modules(input), None)
}

#[cfg(test)]
pub(crate) fn analyze_source_with_implicit_dialect(
    source: &SourceFile,
    implicit_dialect: crate::PineDialect,
) -> Analysis {
    analyze_input_with_implicit_dialect(&AnalysisInput::new(source.clone()), implicit_dialect)
}

#[cfg(test)]
pub(crate) fn analyze_input_with_implicit_dialect(
    input: &AnalysisInput,
    implicit_dialect: crate::PineDialect,
) -> Analysis {
    analyze_validated_modules(
        crate::modules::validate_modules_with_implicit(input, implicit_dialect),
        None,
    )
}

#[cfg(test)]
pub(crate) fn analyze_source_with_legacy_rules(
    source: &SourceFile,
    rules: &'static [crate::legacy::LegacyRule],
) -> Analysis {
    let mut validation = validate_modules(&AnalysisInput::new(source.clone()));
    validation.root_policy.legacy_admission_failure = None;
    analyze_validated_modules(validation, Some(rules))
}

fn analyze_validated_modules(
    module_validation: crate::modules::ModuleValidation,
    legacy_rules: Option<&'static [crate::legacy::LegacyRule]>,
) -> Analysis {
    let mut diagnostics = module_validation.diagnostics;
    let mut compatibility = CompatibilityReport {
        language_version: Some(module_validation.root_policy.language.raw_version),
        language_version_origin: module_validation.root_policy.language.origin,
        dialect: module_validation.root_policy.language.dialect,
        script_mode: module_validation.root_policy.script_mode,
        ..CompatibilityReport::default()
    };

    if module_validation.halt_before_analysis {
        return Analysis {
            diagnostics,
            compatibility,
            hir: None,
        };
    }

    if let Some(failure) = module_validation.root_policy.legacy_admission_failure {
        diagnostics.push(Diagnostic::error(
            failure.code,
            failure.message,
            failure.span,
        ));
        compatibility.unsupported.push(UnsupportedFeature {
            feature: failure.feature,
            reason: failure.reason,
            span: failure.span,
        });
        return Analysis {
            diagnostics,
            compatibility,
            hir: None,
        };
    }

    let dialect = module_validation
        .root_policy
        .language
        .dialect
        .expect("analysis only starts after dialect validation");
    let legacy = match legacy_rules {
        Some(rules) => crate::legacy::LegacyFrontEnd::with_rules(dialect, rules),
        None => crate::legacy::LegacyFrontEnd::new(dialect),
    };
    let mut analyzer = Analyzer {
        diagnostics,
        compatibility,
        legacy,
        source_context_id: Cell::new(SourceContextId::root()),
        source_context_depth: Cell::new(0),
        scope: ScopeResolver::new(initial_symbols(), initial_symbol_order()),
        bindings: HashMap::new(),
        lower_symbol_overrides: Vec::new(),
        lower_reassigned_symbols: HashSet::new(),
        functions: module_validation.imported_functions,
        methods: module_validation.imported_methods,
        imported_user_types: module_validation.imported_user_types,
        user_types: HashMap::new(),
        symbol_user_types: HashMap::new(),
        symbol_user_type_identities: HashMap::new(),
        symbol_init_exprs: HashMap::new(),
        typed_na_scalar_symbols: HashSet::new(),
        legacy_v3_untyped_na_symbols: HashMap::new(),
        legacy_v3_pending_na_symbols: HashSet::new(),
        legacy_v2_declaration_plan: Default::default(),
        legacy_v2_predeclared_symbols: HashSet::new(),
        legacy_bool_to_float_exprs: HashSet::new(),
        legacy_numeric_to_bool_exprs: HashSet::new(),
        non_scalar_udt_varip_symbols: HashSet::new(),
        symbol_user_type_arrays: HashMap::new(),
        symbol_tuple_element_types: HashMap::new(),
        symbol_tuple_user_type_arrays: HashMap::new(),
        symbol_maps: HashMap::new(),
        const_int_symbols: HashMap::new(),
        const_numeric_symbols: HashMap::new(),
        const_string_symbols: HashMap::new(),
        const_bool_symbols: HashMap::new(),
        const_color_symbols: HashMap::new(),
        expr_user_types: HashMap::new(),
        expr_user_type_identities: HashMap::new(),
        expr_user_type_arrays: HashMap::new(),
        expr_maps: HashMap::new(),
        user_method_call_results: HashSet::new(),
        expr_types: HashMap::new(),
        pure_expr_series_ids: HashMap::new(),
        script_declaration: None,
        strategy_settings: Default::default(),
        drawing_settings: Default::default(),
        function_stack: Vec::new(),
        function_param_symbols: Vec::new(),
        function_param_const_switch_keys: Vec::new(),
        function_context_is_method: Vec::new(),
        function_tuple_identity_slots: Vec::new(),
        next_symbol_id: initial_symbol_count(),
        next_series_id: initial_series_count(),
        next_call_site_id: 0,
        next_var_slot_id: 0,
        block_depth: 0,
        function_depth: 0,
        loop_depth: 0,
        expr_depth: 0,
        assignment_qualifier_context: Vec::new(),
        lowering_limits: Default::default(),
        lowering_inline_depth: 0,
        lowered_hir_nodes: 0,
        lowered_temp_symbols: 0,
        lowering_budget_reported: false,
    };
    debug_assert!(analyzer.imported_user_types.iter().all(|(key, user_type)| {
        key.ends_with(&format!(".{}", user_type.identity.name))
            && !user_type.identity.name.is_empty()
            && user_type.fields.iter().all(|field| {
                !field.name.is_empty()
                    && !field.type_name.is_empty()
                    && field.span.start <= field.span.end
                    && field.pine_type.is_none_or(|pine_type| {
                        pine_type.qualifier == Qualifier::Series
                            && matches!(
                                pine_type.kind,
                                ValueKind::Int
                                    | ValueKind::Float
                                    | ValueKind::Bool
                                    | ValueKind::String
                                    | ValueKind::Color
                                    | ValueKind::Label
                                    | ValueKind::Line
                                    | ValueKind::LineFill
                                    | ValueKind::Polyline
                                    | ValueKind::Box
                                    | ValueKind::Table
                                    | ValueKind::ChartPoint
                            )
                    })
            })
            && user_type.span.start <= user_type.span.end
    }));
    analyzer.analyze_program(&module_validation.root_program);
    analyzer.finish(&module_validation.root_program)
}
