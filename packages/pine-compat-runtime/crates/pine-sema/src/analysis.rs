use std::cell::Cell;
use std::collections::{HashMap, HashSet};

use pine_ir::{HirProgram, Qualifier, ValueKind};
use pine_syntax::{Diagnostic, SourceFile};

use crate::analyzer::context::Analyzer;
use crate::compatibility::CompatibilityReport;
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
    let module_validation = validate_modules(input);
    let mut analyzer = Analyzer {
        diagnostics: module_validation.diagnostics,
        compatibility: CompatibilityReport {
            language_version: module_validation
                .root_program
                .version
                .map(|version| version.version),
            ..CompatibilityReport::default()
        },
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
