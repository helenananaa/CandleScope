use std::collections::{HashMap, HashSet};

use pine_syntax::{Diagnostic, ImportDecl, Program, Span, StmtKind};

use super::alias_access::validate_alias_access;
use super::model::{ImportRef, ModuleInfo};
use crate::source_graph::SourceId;

pub(super) fn validate_root_imports(
    modules: &[ModuleInfo],
    library_index: &HashMap<String, usize>,
    diagnostics: &mut Vec<Diagnostic>,
) {
    let root = &modules[0];
    let imports = imports_in_program(&root.program);
    let mut aliases = HashMap::new();
    for import in &imports {
        if !library_index.contains_key(&import.key) {
            diagnostics.push(Diagnostic::error(
                "E_IMPORT_MISSING_LIBRARY",
                format!("missing library source for import `{}`", import.key),
                import.span,
            ));
        }
        let Some((alias, alias_span)) = &import.alias else {
            diagnostics.push(Diagnostic::error(
                "E_IMPORT_ALIAS_REQUIRED",
                format!(
                    "import `{}` requires an alias in the supported subset",
                    import.key
                ),
                import.span,
            ));
            continue;
        };
        if let Some(previous) = aliases.insert(alias.clone(), *alias_span) {
            diagnostics.push(Diagnostic::error(
                "E_IMPORT_DUPLICATE_ALIAS",
                format!("duplicate import alias `{alias}`"),
                previous.merge(*alias_span),
            ));
        }
    }

    validate_alias_access(root, &imports, modules, library_index, diagnostics);
}

pub(super) fn validate_library_imports(
    modules: &[ModuleInfo],
    library_index: &HashMap<String, usize>,
    diagnostics: &mut Vec<Diagnostic>,
) {
    for module in modules.iter().skip(1) {
        for import in imports_in_program(&module.program) {
            if !library_index.contains_key(&import.key) {
                diagnostics.push(Diagnostic::error(
                    "E_IMPORT_MISSING_LIBRARY",
                    format!("missing library source for import `{}`", import.key),
                    import.span,
                ));
            }
        }
    }
}

pub(super) fn detect_import_cycles(
    modules: &[ModuleInfo],
    library_index: &HashMap<String, usize>,
    diagnostics: &mut Vec<Diagnostic>,
) {
    let mut visiting = HashSet::new();
    let mut visited = HashSet::new();
    for module in modules.iter().skip(1) {
        visit_module(
            module,
            modules,
            library_index,
            &mut visiting,
            &mut visited,
            diagnostics,
        );
    }
}

pub(super) fn imports_in_program(program: &Program) -> Vec<ImportRef> {
    program
        .statements
        .iter()
        .filter_map(|statement| {
            let StmtKind::Import(import) = &statement.kind else {
                return None;
            };
            Some(import_ref(import, statement.span))
        })
        .collect()
}

fn visit_module(
    module: &ModuleInfo,
    modules: &[ModuleInfo],
    library_index: &HashMap<String, usize>,
    visiting: &mut HashSet<SourceId>,
    visited: &mut HashSet<SourceId>,
    diagnostics: &mut Vec<Diagnostic>,
) {
    if visited.contains(&module.id) {
        return;
    }
    if !visiting.insert(module.id) {
        return;
    }

    for import in imports_in_program(&module.program) {
        let Some(next_index) = library_index.get(&import.key) else {
            continue;
        };
        let next = &modules[*next_index];
        if visiting.contains(&next.id) {
            diagnostics.push(Diagnostic::error(
                "E_IMPORT_CYCLE",
                format!("import cycle includes `{}`", import.key),
                import.span,
            ));
            continue;
        }
        visit_module(next, modules, library_index, visiting, visited, diagnostics);
    }

    visiting.remove(&module.id);
    visited.insert(module.id);
}

fn import_ref(import: &ImportDecl, span: Span) -> ImportRef {
    ImportRef {
        key: import.key.clone(),
        alias: import
            .alias
            .as_ref()
            .map(|alias| (alias.name.clone(), alias.span)),
        span,
    }
}
