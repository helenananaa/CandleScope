use std::collections::{HashMap, HashSet};

use pine_syntax::{Diagnostic, ExprKind, Span};

use super::model::{
    ExportInfo, ImportRef, ModuleInfo, ModuleMethodInfo, ModuleMethodParamInfo,
    ModuleUserTypeFieldInfo, ModuleUserTypeIdentity, imported_user_type_scalar_field_type,
    module_user_type_fields_match,
};
use super::visit_statement_exprs;
use crate::prelude::postfix_call_result_method_parts;
use crate::source_graph::SourceId;
use crate::types::array_kind_from_element_type_name;

pub(super) fn validate_alias_access(
    root: &ModuleInfo,
    imports: &[ImportRef],
    modules: &[ModuleInfo],
    library_index: &HashMap<String, usize>,
    diagnostics: &mut Vec<Diagnostic>,
) {
    let aliases: HashMap<_, _> = imports
        .iter()
        .filter_map(|import| {
            let (alias, _) = import.alias.as_ref()?;
            Some((alias.as_str(), import.key.as_str()))
        })
        .collect();
    if aliases.is_empty() {
        return;
    }

    let mut postfix_call_result_callees = HashSet::new();
    for statement in &root.program.statements {
        visit_statement_exprs(statement, &mut |expr| {
            let ExprKind::Call { callee, args } = &expr.kind else {
                return;
            };
            if postfix_call_result_method_parts(callee, args).is_some() {
                postfix_call_result_callees.insert((callee.span.start, callee.span.end));
            }
        });
    }

    for statement in &root.program.statements {
        visit_statement_exprs(statement, &mut |expr| {
            let ExprKind::QualifiedName(parts) = &expr.kind else {
                return;
            };
            if postfix_call_result_callees.contains(&(expr.span.start, expr.span.end)) {
                return;
            }
            if parts.len() < 2 {
                return;
            }
            let Some(key) = aliases.get(parts[0].as_str()) else {
                return;
            };
            let Some(module_index) = library_index.get(*key) else {
                return;
            };
            let module = &modules[*module_index];
            let symbol = &parts[1];
            if let Some(export) = module.exports.get(symbol) {
                match export {
                    ExportInfo::Function { .. } | ExportInfo::Const { .. } => return,
                    ExportInfo::UserType {
                        identity, fields, ..
                    } => {
                        if imported_udt_constructor_is_supported(module, parts, fields) {
                            return;
                        }
                        if let Some(user_type) = module.user_types.get(symbol) {
                            debug_assert!(module_user_type_fields_match(fields, &user_type.fields));
                        }
                        diagnostics.push(imported_udt_unsupported_diagnostic(
                            parts[0].as_str(),
                            module.id,
                            identity,
                            fields,
                            expr.span,
                        ));
                        return;
                    }
                }
            }
            if module.private_symbols.contains(symbol) {
                diagnostics.push(Diagnostic::error(
                    "E_IMPORT_PRIVATE_SYMBOL",
                    format!("`{}` is not exported by `{}`", parts.join("."), key),
                    expr.span,
                ));
                return;
            }
            if let Some(user_type) = module.user_types.get(symbol) {
                if imported_udt_constructor_is_supported(module, parts, &user_type.fields) {
                    return;
                }
                debug_assert!(user_type.span.start <= user_type.span.end);
                debug_assert!(user_type.fields.iter().all(|field| {
                    !field.name.is_empty()
                        && !field.type_name.is_empty()
                        && field.span.start <= field.span.end
                }));
                diagnostics.push(imported_udt_unsupported_diagnostic(
                    parts[0].as_str(),
                    module.id,
                    &user_type.identity,
                    &user_type.fields,
                    expr.span,
                ));
            } else if let Some((_, method)) =
                module.methods.iter().find(|((_, method_name), method)| {
                    method_name == symbol && imported_method_access_is_supported(module, method)
                })
            {
                debug_assert!(imported_method_access_is_supported(module, method));
            } else if let Some((_, method)) = module
                .methods
                .iter()
                .find(|((_, method_name), _)| method_name == symbol)
            {
                if imported_method_access_is_supported(module, method) {
                    return;
                }
                diagnostics.push(Diagnostic::error(
                    "E_IMPORT_UNSUPPORTED_METHOD",
                    imported_method_unsupported_message(parts[0].as_str(), symbol, method),
                    expr.span,
                ));
            } else if module.functions.contains_key(symbol) {
                diagnostics.push(Diagnostic::error(
                    "E_IMPORT_PRIVATE_SYMBOL",
                    format!("`{}` is not exported by `{}`", parts.join("."), key),
                    expr.span,
                ));
            } else {
                diagnostics.push(Diagnostic::error(
                    "E_IMPORT_UNKNOWN_EXPORT",
                    format!("unknown export `{symbol}` in `{key}`"),
                    expr.span,
                ));
            }
        });
    }
}

fn imported_method_unsupported_message(
    alias: &str,
    method_name: &str,
    method: &ModuleMethodInfo,
) -> String {
    if let Some(identity) = &method.receiver_identity {
        return format!(
            "imported method `{alias}.{method_name}` for receiver `{alias}.{}` is not supported; imported method dispatch requires imported UDT identity",
            identity.name
        );
    }
    if let Some(receiver_type_name) = &method.receiver_type_name {
        return format!(
            "imported method `{alias}.{method_name}` for receiver `{receiver_type_name}` is not supported; imported method dispatch requires imported UDT identity"
        );
    }
    format!(
        "imported method `{alias}.{method_name}` is not supported; imported method dispatch requires imported UDT identity"
    )
}

fn imported_udt_unsupported_diagnostic(
    alias: &str,
    module_id: SourceId,
    identity: &ModuleUserTypeIdentity,
    fields: &[ModuleUserTypeFieldInfo],
    span: Span,
) -> Diagnostic {
    debug_assert_eq!(identity.source_id, module_id);
    let field_note = if fields.iter().all(|field| field.pine_type.is_some()) {
        "scalar-field metadata is available, but constructor/value identity is not implemented"
    } else {
        "non-scalar or unresolved field metadata remains unsupported"
    };
    Diagnostic::error(
        "E_IMPORT_UNSUPPORTED_UDT",
        format!(
            "imported UDT `{}.{}` is not supported; {field_note}",
            alias, identity.name
        ),
        span,
    )
}

fn imported_method_access_is_supported(module: &ModuleInfo, method: &ModuleMethodInfo) -> bool {
    let Some(identity) = &method.receiver_identity else {
        return false;
    };
    let Some(ExportInfo::UserType { fields, .. }) = module.exports.get(&identity.name) else {
        return false;
    };
    debug_assert!(
        module
            .user_types
            .get(&identity.name)
            .is_some_and(|user_type| { module_user_type_fields_match(fields, &user_type.fields) })
    );
    method
        .params
        .iter()
        .all(|param| imported_method_param_access_is_supported(module, param))
}

fn imported_method_param_access_is_supported(
    module: &ModuleInfo,
    param: &ModuleMethodParamInfo,
) -> bool {
    if param.type_name.starts_with("array<") && param.type_name.ends_with('>') {
        let element_type = &param.type_name["array<".len()..param.type_name.len() - 1];
        return array_kind_from_element_type_name(element_type).is_some()
            || exported_scalar_tree_user_type(module, element_type);
    }
    imported_user_type_scalar_field_type(&param.type_name).is_some()
        || exported_user_type(module, &param.type_name)
}

fn exported_user_type(module: &ModuleInfo, type_name: &str) -> bool {
    matches!(
        module.exports.get(type_name),
        Some(ExportInfo::UserType { .. })
    )
}

fn exported_scalar_tree_user_type(module: &ModuleInfo, type_name: &str) -> bool {
    let Some(ExportInfo::UserType { fields, .. }) = module.exports.get(type_name) else {
        return false;
    };
    debug_assert!(
        module
            .user_types
            .get(type_name)
            .is_some_and(|user_type| module_user_type_fields_match(fields, &user_type.fields))
    );
    module_user_type_fields_are_scalar_tree(module, fields, &mut HashSet::new())
}

fn imported_udt_constructor_is_supported(
    module: &ModuleInfo,
    parts: &[String],
    fields: &[ModuleUserTypeFieldInfo],
) -> bool {
    parts.len() == 3
        && parts[2] == "new"
        && module_user_type_fields_are_scalar_tree(module, fields, &mut HashSet::new())
}

fn module_user_type_fields_are_scalar_tree(
    module: &ModuleInfo,
    fields: &[ModuleUserTypeFieldInfo],
    seen: &mut HashSet<String>,
) -> bool {
    fields.iter().all(|field| {
        if field.pine_type.is_some() {
            return true;
        }
        if !seen.insert(field.type_name.clone()) {
            return false;
        }
        let supported = module
            .user_types
            .get(&field.type_name)
            .is_some_and(|user_type| {
                module_user_type_fields_are_scalar_tree(module, &user_type.fields, seen)
            });
        seen.remove(&field.type_name);
        supported
    })
}
