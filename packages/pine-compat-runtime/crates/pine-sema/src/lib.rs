//! Semantic analysis and compatibility gating scaffolding.

pub const PUBLIC_ANALYSIS_SCHEMA_VERSION: u32 = 5;

mod analysis;
mod analyzer;
mod cache;
mod compatibility;
mod constant_values;
mod history;
pub mod legacy;
mod lowering;
mod modules;
mod resolver;
mod source_graph;
mod symbols;
mod types;

mod prelude {
    pub(crate) use std::collections::HashMap;

    pub(crate) use pine_builtins::{Accepts, BuiltinSignature, ReturnSpec};
    pub(crate) use pine_ir::{
        HirBinaryOp, HirCallArg, HirExpr, HirExprKind, HirHistoryOffset, HirLiteral, HirProgram,
        HirStmt, HirStmtKind, HirSwitchArm, HirSwitchStmtArm, HirSymbol, HirUnaryOp,
        HirUserTypeField, HirUserTypeIdentity, HirUserTypeInfo, PersistenceKind, PineType,
        Qualifier, ScriptMode, SymbolId, ValueKind,
    };
    pub(crate) use pine_syntax::{
        BinaryOp, CallArg, DeclaredType, Diagnostic, Expr, ExprKind, FunctionBody, FunctionParam,
        Literal, Program, Severity, Span, Stmt, StmtKind, SwitchArm, SwitchArmResult, UnaryOp,
    };

    pub(crate) use crate::analyzer::calls::{
        alias_qualified_method_name, array_call_result_builtin_name, array_method_builtin_name,
        bound_matrix_call_result_method_parts, builtin_map_call_result_method_name,
        builtin_matrix_call_result_method_name, call_arg_accepts_type_expected_diagnostic,
        call_arg_expected_type_diagnostic, drawing_method_builtin_name, expr_name,
        is_array_mutation_builtin, is_array_mutation_method_call_name, is_map_mutation_builtin,
        is_map_mutation_method_call_name, is_output_or_declaration_builtin, is_ta_vwap_bands_call,
        map_call_result_builtin_name, map_method_builtin_name, matrix_call_result_builtin_name,
        method_call_parts, postfix_call_result_method_parts, receiver_call_arg,
    };
    pub(crate) use crate::analyzer::context::{
        Analyzer, FunctionInfo, FunctionParamInfo, MAX_FUNCTION_CALL_DEPTH, MAX_SEMA_EXPR_DEPTH,
        MapTypeInfo, MethodInfo, MethodParamInfo, MethodResolution, SourcedExpr, UdfArgError,
        UserTypeArrayIdentityResult,
    };
    pub(crate) use crate::analyzer::functions::resolve_udf_arg_indices;
    pub(crate) use crate::analyzer::strategy::is_strategy_state_variable;
    pub(crate) use crate::analyzer::unsupported::{
        VARIP_DRAWING_UNSUPPORTED_REASON, VARIP_NON_SCALAR_UDT_ASSIGN_UNSUPPORTED_REASON,
        VARIP_UDT_ARRAY_UNSUPPORTED_REASON, VARIP_UDT_UNSUPPORTED_REASON,
        VARIP_VALUE_UNSUPPORTED_REASON, unsupported_collection_reason, unsupported_log_reason,
        unsupported_strategy_reason, unsupported_syntax_reason,
    };
    pub(crate) use crate::analyzer::user_types::{ExprKey, UserTypeIdentity, UserTypeInfo};
    pub(crate) use crate::compatibility::{FeatureUse, UnsupportedFeature};
    pub(crate) use crate::history::{
        infer_history_requirements, infer_max_bars_back, infer_series_max_bars_back,
    };
    pub(crate) use crate::resolver::SymbolInfo;
    pub(crate) use crate::symbols::INITIAL_SYMBOLS;
    pub(crate) use crate::types::{
        UNKNOWN, accepts_matrix_element_arg, accepts_matrix_element_array_arg, accepts_type,
        array_element_return_type, array_from_return_type, array_kind_from_element_type_name,
        array_numeric_return_type, can_assign, common_kind, float_return_for_arg,
        int_return_for_arg, is_array_kind, is_collection_kind, is_matrix_kind, is_numeric,
        literal_type, matrix_array_return_type, matrix_element_return_type,
        matrix_method_builtin_name, matrix_mult_return_type, merge_result_types,
        numeric_result_kind, pine_type_name, promoted_bool_type, promoted_color_type,
        promoted_float_type, promoted_int_type, promoted_numeric_type, promoted_string_type,
        qualifier_at_most, round_return_type, series_return_for_arg, strongest_qualifier,
        value_kind_name,
    };
}

pub use analysis::{Analysis, analyze_input, analyze_source};
pub use cache::{CompileCache, CompileCacheStats};
pub use compatibility::{
    CompatibilityReport, FeatureUse, LegacyEmulation, LegacyTranslation, LegacyTranslationKind,
    UnsupportedFeature,
};
pub use legacy::{
    MAX_PINE_LANGUAGE_VERSION, MIN_PINE_LANGUAGE_VERSION, PineDialect, ScriptModeClassification,
    VersionOrigin,
};
pub use source_graph::{
    AnalysisInput, LibrarySource, SourceGraph, SourceGraphError, SourceId, SourceUnit,
};

#[cfg(test)]
mod tests;
