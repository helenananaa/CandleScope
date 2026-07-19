use std::collections::HashMap;

use pine_ir::{HirSymbol, PersistenceKind, PineType, SeriesId, SymbolId, VarSlotId};
use pine_syntax::Span;

use crate::source_graph::SourceContextId;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct SymbolInfo {
    pub(crate) id: SymbolId,
    pub(crate) pine_type: PineType,
    pub(crate) series_id: Option<SeriesId>,
    pub(crate) persistence: PersistenceKind,
    pub(crate) var_slot_id: Option<VarSlotId>,
}
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub(crate) struct BindingKey {
    pub(crate) source_context_id: SourceContextId,
    pub(crate) span_start: usize,
    pub(crate) span_end: usize,
    pub(crate) name: String,
}
#[derive(Debug, Clone)]
pub(crate) struct ScopeResolver {
    pub(crate) scopes: Vec<HashMap<String, SymbolInfo>>,
    pub(crate) all_symbols: Vec<(String, SymbolInfo)>,
}
impl ScopeResolver {
    pub(crate) fn new(
        global_symbols: HashMap<String, SymbolInfo>,
        symbol_order: Vec<String>,
    ) -> Self {
        let all_symbols = symbol_order
            .iter()
            .filter_map(|name| {
                global_symbols
                    .get(name)
                    .copied()
                    .map(|symbol| (name.clone(), symbol))
            })
            .collect();
        Self {
            scopes: vec![global_symbols],
            all_symbols,
        }
    }

    pub(crate) fn resolve(&self, name: &str) -> Option<SymbolInfo> {
        self.scopes
            .iter()
            .rev()
            .find_map(|scope| scope.get(name).copied())
    }

    pub(crate) fn resolves_to_global(&self, name: &str) -> bool {
        self.scopes
            .iter()
            .rposition(|scope| scope.contains_key(name))
            .is_some_and(|index| index == 0)
    }

    pub(crate) fn define_global(&mut self, name: &str, info: SymbolInfo) {
        let global_scope = self
            .scopes
            .first_mut()
            .expect("scope resolver always has a global scope");
        if !global_scope.contains_key(name) {
            self.all_symbols.push((name.to_owned(), info));
        } else if let Some((_, symbol)) = self
            .all_symbols
            .iter_mut()
            .find(|(_, symbol)| symbol.id == info.id)
        {
            *symbol = info;
        }
        global_scope.insert(name.to_owned(), info);
    }

    pub(crate) fn update(&mut self, name: &str, info: SymbolInfo) {
        if let Some(scope) = self
            .scopes
            .iter_mut()
            .rev()
            .find(|scope| scope.contains_key(name))
        {
            scope.insert(name.to_owned(), info);
        }
        if let Some((_, symbol)) = self
            .all_symbols
            .iter_mut()
            .find(|(_, symbol)| symbol.id == info.id)
        {
            *symbol = info;
        }
    }

    pub(crate) fn push_scope(&mut self) {
        self.scopes.push(HashMap::new());
    }

    pub(crate) fn pop_scope(&mut self) {
        if self.scopes.len() > 1 {
            self.scopes.pop();
        }
    }

    pub(crate) fn define_local(&mut self, name: &str, info: SymbolInfo, lower: bool) {
        let scope = self
            .scopes
            .last_mut()
            .expect("scope resolver always has a current scope");
        scope.insert(name.to_owned(), info);
        if lower {
            self.all_symbols.push((name.to_owned(), info));
        }
    }

    pub(crate) fn lower_symbols(&self) -> Vec<HirSymbol> {
        self.all_symbols
            .iter()
            .map(|(name, symbol)| HirSymbol {
                id: symbol.id,
                name: name.clone(),
                pine_type: symbol.pine_type,
                series_id: symbol.series_id,
                persistence: symbol.persistence,
                var_slot_id: symbol.var_slot_id,
            })
            .collect()
    }

    pub(crate) fn contains_lower_symbol(&self, id: SymbolId) -> bool {
        self.all_symbols.iter().any(|(_, symbol)| symbol.id == id)
    }

    pub(crate) fn add_lower_symbol(&mut self, name: &str, info: SymbolInfo) {
        self.all_symbols.push((name.to_owned(), info));
    }
}
pub(crate) fn binding_key(
    source_context_id: SourceContextId,
    name: &str,
    span: Span,
) -> BindingKey {
    BindingKey {
        source_context_id,
        span_start: span.start,
        span_end: span.end,
        name: name.to_owned(),
    }
}
