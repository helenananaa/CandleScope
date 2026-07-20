use std::cell::Cell;
use std::collections::{HashMap, HashSet};

mod const_eval;
mod history_offsets;

use pine_ir::{
    CallSiteId, DrawingSettings, PersistenceKind, PineType, Qualifier, ScriptMode, SeriesId,
    StrategySettings, SymbolId, VarSlotId,
};
use pine_syntax::{Diagnostic, Expr, FunctionBody, Program, Severity, Span};

use crate::analysis::Analysis;
use crate::compatibility::CompatibilityReport;
use crate::legacy::LegacyFrontEnd;
use crate::modules::ImportedUserTypeInfo;
use crate::prelude::{ExprKey, UserTypeIdentity, UserTypeInfo};
use crate::resolver::{BindingKey, ScopeResolver, SymbolInfo};
use crate::source_graph::{SourceContextId, SourceId};
use crate::types::{
    const_color_value, const_int_value, const_numeric_value, const_string_value, is_collection_kind,
};

pub(crate) const MAX_SEMA_EXPR_DEPTH: u32 = 128;
pub(crate) const MAX_FUNCTION_CALL_DEPTH: usize = 64;
pub(crate) const MAX_LOWERING_INLINE_DEPTH: u32 = 64;
pub(crate) const MAX_LOWERING_HIR_NODES: u32 = 65_536;
pub(crate) const MAX_LOWERING_TEMP_SYMBOLS: u32 = 4_096;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct LoweringLimits {
    pub(crate) max_inline_depth: u32,
    pub(crate) max_hir_nodes: u32,
    pub(crate) max_temp_symbols: u32,
}

impl Default for LoweringLimits {
    fn default() -> Self {
        Self {
            max_inline_depth: MAX_LOWERING_INLINE_DEPTH,
            max_hir_nodes: MAX_LOWERING_HIR_NODES,
            max_temp_symbols: MAX_LOWERING_TEMP_SYMBOLS,
        }
    }
}

pub(crate) struct Analyzer {
    pub(crate) diagnostics: Vec<Diagnostic>,
    pub(crate) compatibility: CompatibilityReport,
    pub(crate) legacy: LegacyFrontEnd,
    pub(crate) source_context_id: Cell<SourceContextId>,
    pub(crate) source_context_depth: Cell<usize>,
    pub(crate) scope: ScopeResolver,
    pub(crate) bindings: HashMap<BindingKey, SymbolInfo>,
    pub(crate) lower_symbol_overrides: Vec<HashMap<SymbolId, SymbolInfo>>,
    pub(crate) lower_reassigned_symbols: HashSet<SymbolId>,
    pub(crate) functions: HashMap<String, FunctionInfo>,
    pub(crate) methods: HashMap<(String, String), MethodInfo>,
    pub(crate) imported_user_types: HashMap<String, ImportedUserTypeInfo>,
    pub(crate) user_types: HashMap<String, UserTypeInfo>,
    pub(crate) symbol_user_types: HashMap<SymbolId, String>,
    pub(crate) symbol_user_type_identities: HashMap<SymbolId, UserTypeIdentity>,
    pub(crate) symbol_init_exprs: HashMap<SymbolId, SourcedExpr>,
    pub(crate) typed_na_scalar_symbols: HashSet<SymbolId>,
    pub(crate) legacy_v3_untyped_na_symbols: HashMap<SymbolId, Span>,
    pub(crate) legacy_v3_pending_na_symbols: HashSet<SymbolId>,
    pub(crate) legacy_v2_declaration_plan: crate::legacy::LegacyV2DeclarationPlan,
    pub(crate) legacy_v2_predeclared_symbols: HashSet<SymbolId>,
    pub(crate) legacy_bool_to_float_exprs: HashSet<ExprKey>,
    pub(crate) legacy_numeric_to_bool_exprs: HashSet<ExprKey>,
    pub(crate) non_scalar_udt_varip_symbols: HashSet<SymbolId>,
    pub(crate) symbol_user_type_arrays: HashMap<SymbolId, String>,
    pub(crate) symbol_tuple_element_types: HashMap<SymbolId, Vec<PineType>>,
    pub(crate) symbol_tuple_user_type_arrays: HashMap<SymbolId, Vec<UserTypeArrayIdentityResult>>,
    pub(crate) symbol_maps: HashMap<SymbolId, MapTypeInfo>,
    pub(crate) const_int_symbols: HashMap<SymbolId, i64>,
    pub(crate) const_numeric_symbols: HashMap<SymbolId, f64>,
    pub(crate) const_string_symbols: HashMap<SymbolId, String>,
    pub(crate) const_bool_symbols: HashMap<SymbolId, bool>,
    pub(crate) const_color_symbols: HashMap<SymbolId, u32>,
    pub(crate) expr_user_types: HashMap<ExprKey, String>,
    pub(crate) expr_user_type_identities: HashMap<ExprKey, UserTypeIdentity>,
    pub(crate) expr_user_type_arrays: HashMap<ExprKey, String>,
    pub(crate) expr_maps: HashMap<ExprKey, MapTypeInfo>,
    pub(crate) user_method_call_results: HashSet<ExprKey>,
    pub(crate) expr_types: HashMap<ExprKey, PineType>,
    pub(crate) pure_expr_series_ids: HashMap<String, SeriesId>,
    pub(crate) script_declaration: Option<(ScriptMode, Span)>,
    pub(crate) strategy_settings: StrategySettings,
    pub(crate) drawing_settings: DrawingSettings,
    pub(crate) function_stack: Vec<String>,
    pub(crate) function_param_symbols: Vec<HashSet<SymbolId>>,
    pub(crate) function_param_const_switch_keys: Vec<HashMap<String, ConstSwitchKey>>,
    pub(crate) function_context_is_method: Vec<bool>,
    pub(crate) function_tuple_identity_slots: Vec<HashSet<usize>>,
    pub(crate) next_symbol_id: u32,
    pub(crate) next_series_id: u32,
    pub(crate) next_call_site_id: u32,
    pub(crate) next_var_slot_id: u32,
    pub(crate) block_depth: u32,
    pub(crate) function_depth: u32,
    pub(crate) loop_depth: u32,
    pub(crate) expr_depth: u32,
    pub(crate) assignment_qualifier_context: Vec<Qualifier>,
    pub(crate) lowering_limits: LoweringLimits,
    pub(crate) lowering_inline_depth: u32,
    pub(crate) lowered_hir_nodes: u32,
    pub(crate) lowered_temp_symbols: u32,
    pub(crate) lowering_budget_reported: bool,
}

#[derive(Debug, Clone)]
pub(crate) struct SourcedExpr {
    pub(crate) source_context_id: SourceContextId,
    pub(crate) expr: Expr,
}

#[derive(Default)]
struct HistoryOffsetIntEnv {
    symbol_visiting: Vec<SymbolId>,
    locals: HashMap<String, pine_syntax::Expr>,
    local_visiting: Vec<String>,
    shadowed_locals: Vec<String>,
}

#[derive(Debug, Clone)]
pub(crate) struct FunctionInfo {
    pub(crate) source_id: SourceId,
    pub(crate) source_context_id: SourceContextId,
    pub(crate) params: Vec<String>,
    pub(crate) param_types: Vec<Option<FunctionParamInfo>>,
    pub(crate) body: FunctionBody,
    pub(crate) span: Span,
}
#[derive(Debug, Clone)]
pub(crate) struct FunctionParamInfo {
    pub(crate) pine_type: PineType,
    pub(crate) user_type_name: Option<String>,
    pub(crate) span: Span,
}
#[derive(Debug, Clone)]
pub(crate) struct MethodInfo {
    pub(crate) source_id: SourceId,
    pub(crate) source_context_id: SourceContextId,
    pub(crate) receiver_type: String,
    pub(crate) receiver_name: String,
    pub(crate) params: Vec<MethodParamInfo>,
    pub(crate) body: FunctionBody,
    pub(crate) span: Span,
}
#[derive(Debug, Clone)]
pub(crate) struct MethodParamInfo {
    pub(crate) name: String,
    pub(crate) pine_type: PineType,
    pub(crate) user_type_name: Option<String>,
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum UdfArgError {
    UnknownName { name: String, span: Span },
    Duplicate { name: String, span: Span },
    PositionalAfterNamed { span: Span },
    TooMany { span: Span },
    Missing { param: String },
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum MethodResolution {
    NotMethod,
    Resolved(Option<PineType>),
}
#[derive(Debug, Clone, PartialEq)]
pub(crate) enum ConstSwitchKey {
    Bool(bool),
    Numeric(f64),
    String(String),
    Color(u32),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct MapTypeInfo {
    pub(crate) key_kind: pine_ir::ValueKind,
    pub(crate) value_kind: pine_ir::ValueKind,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum UserTypeArrayIdentityResult {
    Known(String),
    Na,
    Unknown,
}

impl Analyzer {
    pub(crate) fn current_source_context_id(&self) -> SourceContextId {
        self.source_context_id.get()
    }

    pub(crate) fn expr_key(&self, span: Span) -> ExprKey {
        crate::analyzer::user_types::expr_key(self.current_source_context_id(), span)
    }

    pub(crate) fn binding_key(&self, name: &str, span: Span) -> BindingKey {
        crate::resolver::binding_key(self.current_source_context_id(), name, span)
    }

    pub(crate) fn with_source_context<R>(
        &mut self,
        source_context_id: SourceContextId,
        operation: impl FnOnce(&mut Self) -> R,
    ) -> R {
        let previous_context = self.source_context_id.replace(source_context_id);
        let previous_depth = self.source_context_depth.get();
        self.source_context_depth.set(previous_depth + 1);
        let result = operation(self);
        self.source_context_id.set(previous_context);
        self.source_context_depth.set(previous_depth);
        result
    }

    pub(crate) fn with_source_context_ref<R>(
        &self,
        source_context_id: SourceContextId,
        operation: impl FnOnce(&Self) -> R,
    ) -> R {
        let previous_context = self.source_context_id.replace(source_context_id);
        let previous_depth = self.source_context_depth.get();
        self.source_context_depth.set(previous_depth + 1);
        let result = operation(self);
        self.source_context_id.set(previous_context);
        self.source_context_depth.set(previous_depth);
        result
    }

    pub(crate) fn with_symbol_initializer<R>(
        &self,
        symbol_id: SymbolId,
        operation: impl FnOnce(&Self, &Expr) -> Option<R>,
    ) -> Option<R> {
        let initializer = self.symbol_init_exprs.get(&symbol_id)?;
        self.with_source_context_ref(initializer.source_context_id, |analyzer| {
            operation(analyzer, &initializer.expr)
        })
    }

    pub(crate) fn source_context_stack_is_restored(&self) -> bool {
        self.current_source_context_id() == SourceContextId::root()
            && self.source_context_depth.get() == 0
    }

    pub(crate) fn define_symbol(
        &mut self,
        name: &str,
        pine_type: PineType,
        var_slot_id: Option<VarSlotId>,
    ) -> SymbolInfo {
        self.define_symbol_with_persistence(
            name,
            pine_type,
            persistence_kind_for_slot(var_slot_id),
            var_slot_id,
        )
    }

    pub(crate) fn define_symbol_with_persistence(
        &mut self,
        name: &str,
        pine_type: PineType,
        persistence: PersistenceKind,
        var_slot_id: Option<VarSlotId>,
    ) -> SymbolInfo {
        if let Some(existing) = self.scope.resolve(name) {
            let persistence = if persistence != PersistenceKind::None {
                persistence
            } else {
                existing.persistence
            };
            let updated = SymbolInfo {
                pine_type,
                series_id: existing
                    .series_id
                    .or_else(|| self.series_id_for_type(pine_type)),
                persistence,
                var_slot_id: existing.var_slot_id.or(var_slot_id),
                ..existing
            };
            self.scope.update(name, updated);
            return updated;
        }

        let info = SymbolInfo {
            id: self.alloc_symbol(),
            pine_type,
            series_id: self.series_id_for_type(pine_type),
            persistence,
            var_slot_id,
        };
        self.scope.define_global(name, info);
        info
    }

    pub(crate) fn define_local_symbol(
        &mut self,
        name: &str,
        pine_type: PineType,
        var_slot_id: Option<VarSlotId>,
        lower: bool,
    ) -> SymbolInfo {
        self.define_local_symbol_with_persistence(
            name,
            pine_type,
            persistence_kind_for_slot(var_slot_id),
            var_slot_id,
            lower,
        )
    }

    pub(crate) fn define_local_symbol_with_persistence(
        &mut self,
        name: &str,
        pine_type: PineType,
        persistence: PersistenceKind,
        var_slot_id: Option<VarSlotId>,
        lower: bool,
    ) -> SymbolInfo {
        let series_id = self.series_id_for_type(pine_type);
        let info = SymbolInfo {
            id: self.alloc_symbol(),
            pine_type,
            series_id,
            persistence,
            var_slot_id,
        };
        self.scope.define_local(name, info, lower);
        info
    }

    pub(crate) fn fresh_lower_symbol(&mut self, name: &str, original: SymbolInfo) -> SymbolInfo {
        let is_reassigned = self.lower_reassigned_symbols.contains(&original.id);
        let info = SymbolInfo {
            id: self.alloc_symbol(),
            pine_type: original.pine_type,
            series_id: self.series_id_for_type(original.pine_type),
            persistence: original.persistence,
            var_slot_id: original.var_slot_id.map(|_| self.alloc_var_slot()),
        };
        if is_reassigned {
            self.lower_reassigned_symbols.insert(info.id);
        }
        self.scope.add_lower_symbol(name, info);
        info
    }

    pub(crate) fn fresh_temp_symbol(&mut self, name: &str, pine_type: PineType) -> SymbolInfo {
        let info = SymbolInfo {
            id: self.alloc_symbol(),
            pine_type,
            series_id: self.series_id_for_type(pine_type),
            persistence: PersistenceKind::None,
            var_slot_id: None,
        };
        self.scope.add_lower_symbol(name, info);
        info
    }

    pub(crate) fn update_symbol_type(&mut self, name: &str, pine_type: PineType) {
        if let Some(mut symbol) = self.scope.resolve(name) {
            symbol.pine_type = pine_type;
            if pine_type.qualifier == Qualifier::Series || is_collection_kind(pine_type.kind) {
                if symbol.series_id.is_none() {
                    symbol.series_id = Some(self.alloc_series());
                }
            } else {
                symbol.series_id = None;
            }
            self.scope.update(name, symbol);
        }
    }

    pub(crate) fn update_symbol_type_and_bindings(&mut self, name: &str, pine_type: PineType) {
        let original = self.scope.resolve(name);
        self.update_symbol_type(name, pine_type);
        let Some(original) = original else {
            return;
        };
        let Some(updated) = self.scope.resolve(name) else {
            return;
        };
        for binding in self.bindings.values_mut() {
            if binding.id == original.id {
                *binding = updated;
            }
        }
    }

    pub(crate) fn series_id_for_type(&mut self, pine_type: PineType) -> Option<SeriesId> {
        if pine_type.qualifier == Qualifier::Series || is_collection_kind(pine_type.kind) {
            Some(self.alloc_series())
        } else {
            None
        }
    }

    pub(crate) fn alloc_symbol(&mut self) -> SymbolId {
        let id = SymbolId(self.next_symbol_id);
        self.next_symbol_id += 1;
        id
    }

    pub(crate) fn alloc_series(&mut self) -> SeriesId {
        let id = SeriesId(self.next_series_id);
        self.next_series_id += 1;
        id
    }

    pub(crate) fn alloc_call_site(&mut self) -> CallSiteId {
        let id = CallSiteId(self.next_call_site_id);
        self.next_call_site_id += 1;
        id
    }

    pub(crate) fn alloc_var_slot(&mut self) -> VarSlotId {
        let id = VarSlotId(self.next_var_slot_id);
        self.next_var_slot_id += 1;
        id
    }

    pub(crate) fn finish(mut self, program: &Program) -> Analysis {
        debug_assert!(self.source_context_stack_is_restored());
        let hir = if self.has_errors() {
            None
        } else {
            self.lower_program(program)
        };
        debug_assert!(self.source_context_stack_is_restored());

        crate::legacy::normalize_legacy_report(&mut self.compatibility);
        Analysis {
            diagnostics: self.diagnostics,
            compatibility: self.compatibility,
            hir,
        }
    }

    pub(crate) fn has_errors(&self) -> bool {
        self.diagnostics
            .iter()
            .any(|diagnostic| diagnostic.severity == Severity::Error)
    }
}

fn persistence_kind_for_slot(var_slot_id: Option<VarSlotId>) -> PersistenceKind {
    if var_slot_id.is_some() {
        PersistenceKind::Var
    } else {
        PersistenceKind::None
    }
}
