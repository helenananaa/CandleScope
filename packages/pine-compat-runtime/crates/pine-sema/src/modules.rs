use std::collections::{HashMap, HashSet};

use pine_ir::{PineType, Qualifier, ValueKind};
use pine_syntax::{
    BinaryOp, Diagnostic, ExportItem, Expr, ExprKind, FunctionBody, FunctionParam, Program, Span,
    Stmt, StmtKind, SwitchArmResult, UnaryOp, UserTypeField, parse_source,
};

use crate::analyzer::context::{FunctionInfo, FunctionParamInfo, MethodInfo, MethodParamInfo};
use crate::analyzer::functions::{
    contains_output_or_declaration_call, function_param_names,
    statement_contains_output_or_declaration_call,
};
use crate::legacy::SourcePolicy;
use crate::source_graph::{AnalysisInput, SourceContextId, SourceId};
use crate::types::array_kind_from_element_type_name;

mod alias_access;
mod imports;
mod model;
#[path = "modules_rewrite.rs"]
mod modules_rewrite;
mod side_effects;
#[cfg(test)]
#[path = "modules/source_context_tests.rs"]
mod source_context_tests;
mod version_policy;

use imports::{
    detect_import_cycles, imports_in_program, validate_library_imports, validate_root_imports,
};
use model::{
    ExportInfo, ModuleInfo, ModuleMethodInfo, ModuleMethodParamInfo, ModuleUserTypeFieldInfo,
    ModuleUserTypeIdentity, ModuleUserTypeInfo, imported_user_type_field_type,
    imported_user_type_scalar_field_type, module_user_type_fields_match,
};
pub(crate) use model::{
    ImportedUserTypeFieldInfo, ImportedUserTypeIdentity, ImportedUserTypeInfo, ModuleValidation,
};
use modules_rewrite::{RewriteContext, rewrite_expr, rewrite_function_body, rewrite_program};
use side_effects::{first_statement_span, function_body_has_side_effect, visit_statement_exprs};
use version_policy::validate_language_versions;

pub(crate) fn validate_modules(input: &AnalysisInput) -> ModuleValidation {
    validate_modules_inner(input, crate::PineDialect::V1, false)
}

#[cfg(test)]
pub(crate) fn validate_modules_with_implicit(
    input: &AnalysisInput,
    implicit_dialect: crate::PineDialect,
) -> ModuleValidation {
    validate_modules_inner(input, implicit_dialect, true)
}

fn validate_modules_inner(
    input: &AnalysisInput,
    implicit_dialect: crate::PineDialect,
    inherit_root_for_implicit_libraries: bool,
) -> ModuleValidation {
    let graph = input.source_graph();
    let mut diagnostics = Vec::new();
    let mut modules = Vec::with_capacity(graph.libraries().len() + 1);
    let root_parse = parse_source(graph.root().source());
    diagnostics.extend(root_parse.diagnostics.clone());
    let root_program = root_parse.program;
    modules.push(ModuleInfo {
        id: graph.root().id(),
        key: None,
        program: root_program.clone(),
        exports: HashMap::new(),
        private_symbols: HashSet::new(),
        user_types: HashMap::new(),
        methods: HashMap::new(),
        functions: HashMap::new(),
        constants: HashMap::new(),
    });

    let mut library_index = HashMap::new();
    for library in graph.libraries() {
        let parsed = parse_source(library.source());
        diagnostics.extend(parsed.diagnostics.clone());
        let mut module = ModuleInfo {
            id: library.id(),
            key: library.import_key().map(str::to_owned),
            program: parsed.program,
            exports: HashMap::new(),
            private_symbols: HashSet::new(),
            user_types: HashMap::new(),
            methods: HashMap::new(),
            functions: HashMap::new(),
            constants: HashMap::new(),
        };
        collect_library_declarations(&mut module, &mut diagnostics);
        if let Some(key) = &module.key {
            library_index.insert(key.clone(), modules.len());
        }
        modules.push(module);
    }

    validate_root_imports(&modules, &library_index, &mut diagnostics);
    validate_library_imports(&modules, &library_index, &mut diagnostics);
    detect_import_cycles(&modules, &library_index, &mut diagnostics);

    let root_policy = SourcePolicy::from_program_with_implicit(&root_program, implicit_dialect);
    validate_language_versions(
        &modules,
        &root_policy,
        implicit_dialect,
        inherit_root_for_implicit_libraries,
        &mut diagnostics,
    );
    let halt_before_analysis = diagnostics.iter().any(|diagnostic| {
        diagnostic.code == "E_LEX_VERSION" || diagnostic.code.starts_with("E_LANGUAGE_VERSION_")
    });

    let import_plan = build_import_plan(&modules, &library_index, &mut diagnostics);
    let root_program = rewrite_program(&root_program, &import_plan.root_rewrites);

    ModuleValidation {
        diagnostics,
        root_program,
        root_policy,
        halt_before_analysis,
        imported_functions: import_plan.imported_functions,
        imported_methods: import_plan.imported_methods,
        imported_user_types: import_plan.imported_user_types,
    }
}

fn collect_library_declarations(module: &mut ModuleInfo, diagnostics: &mut Vec<Diagnostic>) {
    let mut library_declarations = 0;
    // Temporarily move the statements out so we can iterate by reference
    // without cloning the entire AST; the loop only mutates other fields of
    // `module`, never `module.program.statements`.
    let statements = std::mem::take(&mut module.program.statements);
    for statement in &statements {
        match &statement.kind {
            StmtKind::Library(_) => library_declarations += 1,
            StmtKind::Export(export) => match &export.item {
                ExportItem::Function {
                    name,
                    params,
                    body,
                    span,
                } => {
                    register_export(
                        module,
                        name,
                        ExportInfo::Function { span: *span },
                        diagnostics,
                    );
                    if function_body_has_side_effect(body) {
                        diagnostics.push(Diagnostic::error(
                            "E_IMPORT_FUNCTION_SIDE_EFFECT",
                            format!("exported function `{name}` contains unsupported side effects"),
                            *span,
                        ));
                    }
                    module.functions.insert(
                        name.clone(),
                        FunctionInfo {
                            source_id: module.id,
                            // Library declarations are re-contextualized for each root import
                            // instance in `build_import_plan` before semantic analysis.
                            source_context_id: SourceContextId::root(),
                            params: function_param_names(params),
                            param_types: module_function_param_types(
                                module,
                                params,
                                None,
                                diagnostics,
                            ),
                            body: body.clone(),
                            span: *span,
                        },
                    );
                }
                ExportItem::Const { name, value, span } => {
                    register_export(
                        module,
                        name,
                        ExportInfo::Const {
                            value: value.clone(),
                            span: *span,
                        },
                        diagnostics,
                    );
                    if !is_const_import_expr(value) {
                        diagnostics.push(Diagnostic::error(
                            "E_IMPORT_CONST_VALUE",
                            format!("exported constant `{name}` must be a const expression"),
                            value.span,
                        ));
                    }
                    module.constants.insert(name.clone(), value.clone());
                }
                ExportItem::UserType { decl, span } => {
                    let user_type =
                        module_user_type_info(module.id, &decl.name, &decl.fields, *span);
                    register_export(
                        module,
                        &decl.name,
                        ExportInfo::UserType {
                            identity: user_type.identity.clone(),
                            fields: user_type.fields.clone(),
                            span: *span,
                        },
                        diagnostics,
                    );
                    module.user_types.insert(decl.name.clone(), user_type);
                }
                ExportItem::Unknown { .. } => {}
            },
            StmtKind::Function { name, params, body } => {
                module.private_symbols.insert(name.clone());
                module.functions.insert(
                    name.clone(),
                    FunctionInfo {
                        source_id: module.id,
                        // Library declarations are re-contextualized for each root import
                        // instance in `build_import_plan` before semantic analysis.
                        source_context_id: SourceContextId::root(),
                        params: function_param_names(params),
                        param_types: module_function_param_types(module, params, None, diagnostics),
                        body: body.clone(),
                        span: statement.span,
                    },
                );
            }
            StmtKind::Decl { name, value, .. } => {
                module.private_symbols.insert(name.clone());
                if is_const_import_expr(value) {
                    module.constants.insert(name.clone(), value.clone());
                }
            }
            StmtKind::UserType(user_type) => {
                module.private_symbols.insert(user_type.name.clone());
                module.user_types.insert(
                    user_type.name.clone(),
                    module_user_type_info(
                        module.id,
                        &user_type.name,
                        &user_type.fields,
                        statement.span,
                    ),
                );
            }
            StmtKind::Method(_) => {}
            _ => {}
        }
    }
    for statement in &statements {
        let StmtKind::Method(method) = &statement.kind else {
            continue;
        };
        let receiver_type_name = method
            .params
            .first()
            .map(|receiver| receiver.type_name.clone());
        let receiver_identity = receiver_type_name
            .as_deref()
            .and_then(|type_name| module.user_types.get(type_name))
            .map(|user_type| user_type.identity.clone());
        module.methods.insert(
            (
                receiver_type_name.clone().unwrap_or_default(),
                method.name.clone(),
            ),
            ModuleMethodInfo {
                receiver_type_name,
                receiver_identity,
                receiver_name: method
                    .params
                    .first()
                    .map(|receiver| receiver.name.clone())
                    .unwrap_or_default(),
                params: method
                    .params
                    .iter()
                    .skip(1)
                    .map(|param| ModuleMethodParamInfo {
                        name: param.name.clone(),
                        type_name: param.type_name.clone(),
                    })
                    .collect(),
                param_names: method
                    .params
                    .iter()
                    .map(|param| param.name.clone())
                    .collect(),
                body: method.body.clone(),
                span: statement.span,
            },
        );
    }
    // Restore the statements that were moved out above.
    module.program.statements = statements;

    if module.key.is_some() && library_declarations != 1 {
        diagnostics.push(Diagnostic::error(
            "E_IMPORT_INVALID_LIBRARY",
            "library source must contain exactly one library declaration",
            first_statement_span(&module.program).unwrap_or_else(|| Span::new(0, 0)),
        ));
    }
}

fn module_user_type_info(
    source_id: SourceId,
    name: &str,
    fields: &[UserTypeField],
    span: Span,
) -> ModuleUserTypeInfo {
    let identity = ModuleUserTypeIdentity {
        source_id,
        name: name.to_owned(),
    };
    let fields = fields
        .iter()
        .map(|field| ModuleUserTypeFieldInfo {
            name: field.name.clone(),
            type_name: field.type_name.clone(),
            pine_type: imported_user_type_field_type(&field.type_name),
            span: field.span,
        })
        .collect();
    ModuleUserTypeInfo {
        identity,
        fields,
        span,
    }
}

fn register_export(
    module: &mut ModuleInfo,
    name: &str,
    export: ExportInfo,
    diagnostics: &mut Vec<Diagnostic>,
) {
    if let Some(existing) = module.exports.insert(name.to_owned(), export.clone()) {
        diagnostics.push(Diagnostic::error(
            "E_IMPORT_DUPLICATE_EXPORT",
            format!("duplicate export `{name}`"),
            existing.span().merge(export.span()),
        ));
    }
}

#[derive(Default)]
struct ImportPlan {
    root_rewrites: RewriteContext,
    imported_functions: HashMap<String, FunctionInfo>,
    imported_methods: HashMap<(String, String), MethodInfo>,
    imported_user_types: HashMap<String, ImportedUserTypeInfo>,
}

fn build_import_plan(
    modules: &[ModuleInfo],
    library_index: &HashMap<String, usize>,
    diagnostics: &mut Vec<Diagnostic>,
) -> ImportPlan {
    let mut plan = ImportPlan::default();
    for (import_instance, import) in imports_in_program(&modules[0].program)
        .into_iter()
        .enumerate()
    {
        let source_context_id = SourceContextId::import_instance(import_instance);
        let Some((alias, _)) = import.alias else {
            continue;
        };
        let Some(module_index) = library_index.get(&import.key) else {
            continue;
        };
        let module = &modules[*module_index];
        let module_context = rewrite_context_for_module(&alias, module);

        for (name, export) in &module.exports {
            match export {
                ExportInfo::Const { value, .. } => {
                    plan.root_rewrites.constants.insert(
                        format!("{alias}.{name}"),
                        rewrite_expr(value, &module_context),
                    );
                }
                ExportInfo::Function { .. } => {
                    plan.root_rewrites
                        .function_targets
                        .insert(format!("{alias}.{name}"), format!("{alias}.{name}"));
                }
                ExportInfo::UserType {
                    identity,
                    fields,
                    span,
                } => {
                    let Some(user_type) = module.user_types.get(name) else {
                        diagnostics.push(Diagnostic::error(
                            "E_IMPORT_UNKNOWN_EXPORT",
                            format!("unknown imported user type `{name}`"),
                            *span,
                        ));
                        continue;
                    };
                    debug_assert!(module_user_type_fields_match(fields, &user_type.fields));
                    debug_assert!(module.user_types.get(name).is_some_and(|user_type| {
                        module_user_type_fields_match(fields, &user_type.fields)
                    }));
                    debug_assert_eq!(identity, &user_type.identity);
                    insert_imported_user_type_metadata(
                        &mut plan.imported_user_types,
                        &alias,
                        module,
                        name,
                        user_type,
                        &mut HashSet::new(),
                    );
                }
            }
        }

        for (name, function) in &module.functions {
            let key = module_function_key(&alias, module, name);
            let body = rewrite_function_body(&function.body, &function.params, &module_context);
            if name_is_exported_function(module, name) || module.private_symbols.contains(name) {
                plan.imported_functions.insert(
                    key,
                    FunctionInfo {
                        source_id: function.source_id,
                        source_context_id,
                        params: function.params.clone(),
                        param_types: imported_function_param_types(
                            &alias,
                            module,
                            &function.param_types,
                        ),
                        body,
                        span: function.span,
                    },
                );
            } else {
                diagnostics.push(Diagnostic::error(
                    "E_IMPORT_UNKNOWN_EXPORT",
                    format!("unknown imported function `{name}`"),
                    function.span,
                ));
            }
        }

        for ((_, name), method) in &module.methods {
            let Some(method_info) = imported_method_info(&alias, module, method, source_context_id)
            else {
                continue;
            };
            plan.imported_methods.insert(
                (method_info.receiver_type.clone(), name.clone()),
                method_info,
            );
        }
    }
    debug_assert!(plan.imported_functions.values().all(|function| {
        function.source_id != SourceId::root()
            && function.source_context_id != SourceContextId::root()
    }));
    debug_assert!(plan.imported_methods.values().all(|method| {
        method.source_id != SourceId::root() && method.source_context_id != SourceContextId::root()
    }));
    plan
}

fn imported_method_info(
    alias: &str,
    module: &ModuleInfo,
    method: &ModuleMethodInfo,
    source_context_id: SourceContextId,
) -> Option<MethodInfo> {
    let identity = method.receiver_identity.as_ref()?;
    if !exported_user_type(module, &identity.name) {
        return None;
    }

    let mut params = Vec::with_capacity(method.params.len());
    for param in &method.params {
        params.push(imported_method_param_info(alias, module, param)?);
    }

    let module_context = rewrite_context_for_module(alias, module);
    Some(MethodInfo {
        source_id: identity.source_id,
        source_context_id,
        receiver_type: format!("{alias}.{}", identity.name),
        receiver_name: method.receiver_name.clone(),
        params,
        body: rewrite_function_body(&method.body, &method.param_names, &module_context),
        span: method.span,
    })
}

fn imported_method_param_info(
    alias: &str,
    module: &ModuleInfo,
    param: &ModuleMethodParamInfo,
) -> Option<MethodParamInfo> {
    if param.type_name.starts_with("array<") && param.type_name.ends_with('>') {
        let element_type = &param.type_name["array<".len()..param.type_name.len() - 1];
        if let Some(kind) = array_kind_from_element_type_name(element_type) {
            return Some(MethodParamInfo {
                name: param.name.clone(),
                pine_type: PineType::new(Qualifier::Series, kind),
                user_type_name: None,
            });
        }
        if exported_scalar_tree_user_type(module, element_type) {
            return Some(MethodParamInfo {
                name: param.name.clone(),
                pine_type: PineType::new(Qualifier::Series, ValueKind::UserTypeArray),
                user_type_name: Some(format!("{alias}.{element_type}")),
            });
        }
        return None;
    }
    if let Some(pine_type) = imported_user_type_scalar_field_type(&param.type_name) {
        return Some(MethodParamInfo {
            name: param.name.clone(),
            pine_type,
            user_type_name: None,
        });
    }
    if !exported_user_type(module, &param.type_name) {
        return None;
    }
    Some(MethodParamInfo {
        name: param.name.clone(),
        pine_type: PineType::new(Qualifier::Series, ValueKind::UserType),
        user_type_name: Some(format!("{alias}.{}", param.type_name)),
    })
}

fn module_function_param_types(
    module: &ModuleInfo,
    params: &[FunctionParam],
    alias: Option<&str>,
    diagnostics: &mut Vec<Diagnostic>,
) -> Vec<Option<FunctionParamInfo>> {
    params
        .iter()
        .map(|param| {
            let Some(type_name) = &param.type_name else {
                return None;
            };
            module_function_param_type(module, type_name, alias, param.span, diagnostics)
        })
        .collect()
}

fn module_function_param_type(
    module: &ModuleInfo,
    type_name: &str,
    alias: Option<&str>,
    span: Span,
    diagnostics: &mut Vec<Diagnostic>,
) -> Option<FunctionParamInfo> {
    let (pine_type, user_type_name) = match type_name {
        _ if type_name.starts_with("array<") && type_name.ends_with('>') => {
            let element_type = &type_name["array<".len()..type_name.len() - 1];
            if let Some(kind) = array_kind_from_element_type_name(element_type) {
                (PineType::new(Qualifier::Series, kind), None)
            } else if exported_scalar_tree_user_type(module, element_type) {
                let type_name = alias
                    .map(|alias| format!("{alias}.{element_type}"))
                    .unwrap_or_else(|| element_type.to_owned());
                (
                    PineType::new(Qualifier::Series, ValueKind::UserTypeArray),
                    Some(type_name),
                )
            } else {
                diagnostics.push(Diagnostic::error(
                    "E_FUNCTION_PARAM_TYPE",
                    format!("function parameter type `{type_name}` is not supported"),
                    span,
                ));
                return None;
            }
        }
        "int" => (PineType::new(Qualifier::Series, ValueKind::Int), None),
        "float" => (PineType::new(Qualifier::Series, ValueKind::Float), None),
        "bool" => (PineType::new(Qualifier::Series, ValueKind::Bool), None),
        "string" => (PineType::new(Qualifier::Series, ValueKind::String), None),
        "color" => (PineType::new(Qualifier::Series, ValueKind::Color), None),
        "label" => (PineType::new(Qualifier::Series, ValueKind::Label), None),
        "line" => (PineType::new(Qualifier::Series, ValueKind::Line), None),
        "linefill" => (PineType::new(Qualifier::Series, ValueKind::LineFill), None),
        "polyline" => (PineType::new(Qualifier::Series, ValueKind::Polyline), None),
        "box" => (PineType::new(Qualifier::Series, ValueKind::Box), None),
        "table" => (PineType::new(Qualifier::Series, ValueKind::Table), None),
        "chart.point" => (
            PineType::new(Qualifier::Series, ValueKind::ChartPoint),
            None,
        ),
        _ if module.user_types.contains_key(type_name) => {
            let type_name = alias
                .map(|alias| format!("{alias}.{type_name}"))
                .unwrap_or_else(|| type_name.to_owned());
            (
                PineType::new(Qualifier::Series, ValueKind::UserType),
                Some(type_name),
            )
        }
        _ => {
            diagnostics.push(Diagnostic::error(
                "E_FUNCTION_PARAM_TYPE",
                format!("function parameter type `{type_name}` is not supported"),
                span,
            ));
            return None;
        }
    };
    Some(FunctionParamInfo {
        pine_type,
        user_type_name,
        span,
    })
}

fn imported_function_param_types(
    alias: &str,
    module: &ModuleInfo,
    params: &[Option<FunctionParamInfo>],
) -> Vec<Option<FunctionParamInfo>> {
    params
        .iter()
        .map(|param| {
            let mut param = param.clone()?;
            if let Some(type_name) = &param.user_type_name
                && module.user_types.contains_key(type_name)
            {
                param.user_type_name = Some(format!("{alias}.{type_name}"));
            }
            Some(param)
        })
        .collect()
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

fn exported_user_type(module: &ModuleInfo, type_name: &str) -> bool {
    let Some(ExportInfo::UserType { fields, .. }) = module.exports.get(type_name) else {
        return false;
    };
    debug_assert!(
        module
            .user_types
            .get(type_name)
            .is_some_and(|user_type| module_user_type_fields_match(fields, &user_type.fields))
    );
    true
}

fn insert_imported_user_type_metadata(
    imported_user_types: &mut HashMap<String, ImportedUserTypeInfo>,
    alias: &str,
    module: &ModuleInfo,
    name: &str,
    user_type: &ModuleUserTypeInfo,
    seen: &mut HashSet<String>,
) {
    let imported_name = format!("{alias}.{name}");
    if imported_user_types.contains_key(&imported_name) {
        return;
    }
    if !seen.insert(name.to_owned()) {
        return;
    }
    imported_user_types.insert(
        imported_name,
        ImportedUserTypeInfo {
            identity: ImportedUserTypeIdentity {
                source_id: user_type.identity.source_id,
                name: user_type.identity.name.clone(),
            },
            fields: user_type
                .fields
                .iter()
                .map(|field| ImportedUserTypeFieldInfo {
                    name: field.name.clone(),
                    type_name: field.type_name.clone(),
                    pine_type: field.pine_type,
                    span: field.span,
                })
                .collect(),
            span: user_type.span,
        },
    );
    for field in &user_type.fields {
        if field.pine_type.is_some() {
            continue;
        }
        if let Some(nested) = module.user_types.get(&field.type_name) {
            insert_imported_user_type_metadata(
                imported_user_types,
                alias,
                module,
                &field.type_name,
                nested,
                seen,
            );
        }
    }
    seen.remove(name);
}

fn module_user_type_fields_are_scalar_tree(
    module: &ModuleInfo,
    fields: &[ModuleUserTypeFieldInfo],
    seen: &mut HashSet<String>,
) -> bool {
    fields.iter().all(|field| {
        if let Some(pine_type) = field.pine_type {
            return is_scalar_user_type_field_kind(pine_type.kind);
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

fn is_scalar_user_type_field_kind(kind: ValueKind) -> bool {
    matches!(
        kind,
        ValueKind::Int | ValueKind::Float | ValueKind::Bool | ValueKind::String | ValueKind::Color
    )
}

fn rewrite_context_for_module(alias: &str, module: &ModuleInfo) -> RewriteContext {
    let mut context = RewriteContext::default();
    for (name, value) in &module.constants {
        context.constants.insert(name.clone(), value.clone());
        context
            .constants
            .insert(format!("{alias}.{name}"), value.clone());
    }
    for name in module.functions.keys() {
        context
            .function_targets
            .insert(name.clone(), module_function_key(alias, module, name));
        context.function_targets.insert(
            format!("{alias}.{name}"),
            module_function_key(alias, module, name),
        );
    }
    for name in module
        .exports
        .iter()
        .filter_map(|(name, export)| matches!(export, ExportInfo::UserType { .. }).then_some(name))
    {
        context
            .type_targets
            .insert(name.clone(), format!("{alias}.{name}"));
        context
            .type_targets
            .insert(format!("{alias}.{name}"), format!("{alias}.{name}"));
    }
    context
}

fn module_function_key(alias: &str, module: &ModuleInfo, name: &str) -> String {
    if name_is_exported_function(module, name) {
        format!("{alias}.{name}")
    } else {
        format!("__import_{alias}_{name}")
    }
}

fn name_is_exported_function(module: &ModuleInfo, name: &str) -> bool {
    matches!(module.exports.get(name), Some(ExportInfo::Function { .. }))
}

fn is_const_import_expr(expr: &Expr) -> bool {
    match &expr.kind {
        ExprKind::Literal(_) => true,
        ExprKind::QualifiedName(parts) => const_qualified_type(&parts.join(".")).is_some(),
        ExprKind::Unary { op, expr } => {
            matches!(op, UnaryOp::Plus | UnaryOp::Minus | UnaryOp::Not)
                && is_const_import_expr(expr)
        }
        ExprKind::Binary { op, left, right } => {
            matches!(
                op,
                BinaryOp::Add
                    | BinaryOp::Sub
                    | BinaryOp::Mul
                    | BinaryOp::Div
                    | BinaryOp::Mod
                    | BinaryOp::Eq
                    | BinaryOp::NotEq
                    | BinaryOp::Gt
                    | BinaryOp::Gte
                    | BinaryOp::Lt
                    | BinaryOp::Lte
                    | BinaryOp::And
                    | BinaryOp::Or
            ) && is_const_import_expr(left)
                && is_const_import_expr(right)
        }
        ExprKind::Ternary {
            condition,
            then_expr,
            else_expr,
        } => {
            is_const_import_expr(condition)
                && is_const_import_expr(then_expr)
                && is_const_import_expr(else_expr)
        }
        ExprKind::Call { .. }
        | ExprKind::If { .. }
        | ExprKind::For { .. }
        | ExprKind::ForIn { .. }
        | ExprKind::While { .. }
        | ExprKind::Switch { .. }
        | ExprKind::Tuple(_)
        | ExprKind::History { .. }
        | ExprKind::Identifier(_) => false,
    }
}

fn const_qualified_type(name: &str) -> Option<PineType> {
    if pine_builtins::named_color(name).is_some() {
        return Some(PineType::new(Qualifier::Const, ValueKind::Color));
    }
    if pine_builtins::named_float_constant(name).is_some() {
        return Some(PineType::new(Qualifier::Const, ValueKind::Float));
    }
    if pine_builtins::named_int_constant(name).is_some() {
        return Some(PineType::new(Qualifier::Const, ValueKind::Int));
    }
    if pine_builtins::named_string_constant(name).is_some() {
        return Some(PineType::new(Qualifier::Const, ValueKind::String));
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::analyzer::calls::expr_name;
    use crate::source_graph::SourceId;
    use pine_syntax::SourceFile;

    fn parsed_program(text: &str) -> Program {
        parse_source(&SourceFile::new("library.pine", text)).program
    }

    fn qualified_name(parts: &[&str]) -> Expr {
        Expr {
            kind: ExprKind::QualifiedName(parts.iter().map(|part| (*part).to_owned()).collect()),
            span: Span::new(0, 0),
        }
    }

    #[test]
    fn exported_user_type_records_identity_and_fields() {
        let mut module = ModuleInfo {
            id: SourceId::library(7),
            key: Some("user/identity/1".to_owned()),
            program: parsed_program(
                r#"
library("identity")
export type Point
    float x
"#,
            ),
            exports: HashMap::new(),
            private_symbols: HashSet::new(),
            user_types: HashMap::new(),
            methods: HashMap::new(),
            functions: HashMap::new(),
            constants: HashMap::new(),
        };
        let mut diagnostics = Vec::new();

        collect_library_declarations(&mut module, &mut diagnostics);

        assert!(diagnostics.is_empty(), "{diagnostics:?}");
        let ExportInfo::UserType {
            identity, fields, ..
        } = module.exports.get("Point").expect("exported UDT")
        else {
            panic!("Point should be a UDT export");
        };
        assert_eq!(identity.source_id, SourceId::library(7));
        assert_eq!(identity.name, "Point");
        assert_eq!(fields.len(), 1);
        assert_eq!(fields[0].name, "x");
        assert_eq!(fields[0].type_name, "float");
        assert_eq!(
            fields[0].pine_type,
            Some(PineType::new(Qualifier::Series, ValueKind::Float))
        );

        let user_type = module.user_types.get("Point").expect("UDT table entry");
        assert_eq!(user_type.identity, *identity);
        assert_eq!(user_type.fields.len(), 1);
        assert_eq!(user_type.fields[0].name, fields[0].name);
        assert_eq!(user_type.fields[0].type_name, fields[0].type_name);
        assert_eq!(user_type.fields[0].pine_type, fields[0].pine_type);
        assert_eq!(user_type.fields[0].span, fields[0].span);
    }

    #[test]
    fn import_plan_records_alias_qualified_user_type_metadata() {
        let root = ModuleInfo {
            id: SourceId::root(),
            key: None,
            program: parse_source(&SourceFile::new(
                "root.pine",
                r#"import user/identity/1 as lib
"#,
            ))
            .program,
            exports: HashMap::new(),
            private_symbols: HashSet::new(),
            user_types: HashMap::new(),
            methods: HashMap::new(),
            functions: HashMap::new(),
            constants: HashMap::new(),
        };
        let mut library = ModuleInfo {
            id: SourceId::library(0),
            key: Some("user/identity/1".to_owned()),
            program: parsed_program(
                r#"
library("identity")
export type Point
    float x
"#,
            ),
            exports: HashMap::new(),
            private_symbols: HashSet::new(),
            user_types: HashMap::new(),
            methods: HashMap::new(),
            functions: HashMap::new(),
            constants: HashMap::new(),
        };
        let mut diagnostics = Vec::new();
        collect_library_declarations(&mut library, &mut diagnostics);
        let modules = vec![root, library];
        let library_index = HashMap::from([("user/identity/1".to_owned(), 1)]);

        let plan = build_import_plan(&modules, &library_index, &mut diagnostics);

        assert!(diagnostics.is_empty(), "{diagnostics:?}");
        let point = plan
            .imported_user_types
            .get("lib.Point")
            .expect("alias-qualified imported UDT");
        assert_eq!(point.identity.source_id, SourceId::library(0));
        assert_eq!(point.identity.name, "Point");
        assert_eq!(point.fields.len(), 1);
        assert_eq!(point.fields[0].name, "x");
        assert_eq!(point.fields[0].type_name, "float");
        assert_eq!(
            point.fields[0].pine_type,
            Some(PineType::new(Qualifier::Series, ValueKind::Float))
        );
        assert_eq!(
            point.span,
            modules[1]
                .user_types
                .get("Point")
                .expect("library UDT metadata")
                .span
        );
    }

    #[test]
    fn import_plan_records_private_user_type_dependencies_for_exported_metadata() {
        let root = ModuleInfo {
            id: SourceId::root(),
            key: None,
            program: parse_source(&SourceFile::new(
                "root.pine",
                r#"import user/identity/1 as lib
"#,
            ))
            .program,
            exports: HashMap::new(),
            private_symbols: HashSet::new(),
            user_types: HashMap::new(),
            methods: HashMap::new(),
            functions: HashMap::new(),
            constants: HashMap::new(),
        };
        let mut library = ModuleInfo {
            id: SourceId::library(0),
            key: Some("user/identity/1".to_owned()),
            program: parsed_program(
                r#"
library("identity")
type Point
    float x
export type Wrapper
    Point nested
"#,
            ),
            exports: HashMap::new(),
            private_symbols: HashSet::new(),
            user_types: HashMap::new(),
            methods: HashMap::new(),
            functions: HashMap::new(),
            constants: HashMap::new(),
        };
        let mut diagnostics = Vec::new();
        collect_library_declarations(&mut library, &mut diagnostics);
        let modules = vec![root, library];
        let library_index = HashMap::from([("user/identity/1".to_owned(), 1)]);

        let plan = build_import_plan(&modules, &library_index, &mut diagnostics);

        assert!(diagnostics.is_empty(), "{diagnostics:?}");
        let wrapper = plan
            .imported_user_types
            .get("lib.Wrapper")
            .expect("exported wrapper metadata");
        assert_eq!(wrapper.fields.len(), 1);
        assert_eq!(wrapper.fields[0].name, "nested");
        assert_eq!(wrapper.fields[0].type_name, "Point");
        assert_eq!(wrapper.fields[0].pine_type, None);

        let point = plan
            .imported_user_types
            .get("lib.Point")
            .expect("private dependency metadata");
        assert_eq!(point.identity.name, "Point");
        assert_eq!(point.fields.len(), 1);
        assert_eq!(point.fields[0].name, "x");
        assert_eq!(
            point.fields[0].pine_type,
            Some(PineType::new(Qualifier::Series, ValueKind::Float))
        );
    }

    #[test]
    fn library_method_records_receiver_identity_metadata() {
        let mut module = ModuleInfo {
            id: SourceId::library(3),
            key: Some("user/methods/1".to_owned()),
            program: parsed_program(
                r#"
library("methods")
export type Point
    float x

method shift(Point p, float delta) => p.x + delta
"#,
            ),
            exports: HashMap::new(),
            private_symbols: HashSet::new(),
            user_types: HashMap::new(),
            methods: HashMap::new(),
            functions: HashMap::new(),
            constants: HashMap::new(),
        };
        let mut diagnostics = Vec::new();

        collect_library_declarations(&mut module, &mut diagnostics);

        assert!(diagnostics.is_empty(), "{diagnostics:?}");
        let method = module
            .methods
            .get(&("Point".to_owned(), "shift".to_owned()))
            .expect("library method");
        assert_eq!(method.receiver_type_name.as_deref(), Some("Point"));
        assert_eq!(
            method.receiver_identity,
            Some(ModuleUserTypeIdentity {
                source_id: SourceId::library(3),
                name: "Point".to_owned(),
            })
        );
    }

    #[test]
    fn library_method_metadata_allows_same_name_on_different_receivers() {
        let mut module = ModuleInfo {
            id: SourceId::library(3),
            key: Some("user/methods/1".to_owned()),
            program: parsed_program(
                r#"
library("methods")
export type Point
    float x
export type Offset
    int value

method same(Point p) => p
method same(Offset offset) => offset
"#,
            ),
            exports: HashMap::new(),
            private_symbols: HashSet::new(),
            user_types: HashMap::new(),
            methods: HashMap::new(),
            functions: HashMap::new(),
            constants: HashMap::new(),
        };
        let mut diagnostics = Vec::new();

        collect_library_declarations(&mut module, &mut diagnostics);

        assert!(diagnostics.is_empty(), "{diagnostics:?}");
        assert!(
            module
                .methods
                .contains_key(&("Point".to_owned(), "same".to_owned()))
        );
        assert!(
            module
                .methods
                .contains_key(&("Offset".to_owned(), "same".to_owned()))
        );
    }

    #[test]
    fn rewrite_context_alias_qualifies_exported_user_type_constructors() {
        let mut module = ModuleInfo {
            id: SourceId::library(4),
            key: Some("user/methods/1".to_owned()),
            program: parsed_program(
                r#"
library("methods")
export type Point
    float x
"#,
            ),
            exports: HashMap::new(),
            private_symbols: HashSet::new(),
            user_types: HashMap::new(),
            methods: HashMap::new(),
            functions: HashMap::new(),
            constants: HashMap::new(),
        };
        let mut diagnostics = Vec::new();
        collect_library_declarations(&mut module, &mut diagnostics);
        assert!(diagnostics.is_empty(), "{diagnostics:?}");
        let context = rewrite_context_for_module("lib", &module);
        let body = FunctionBody::Expr(qualified_name(&["Point", "new"]));

        let rewritten = rewrite_function_body(&body, &[], &context);

        let FunctionBody::Expr(expr) = rewritten else {
            panic!("expression body expected");
        };
        assert_eq!(expr_name(&expr).as_deref(), Some("lib.Point.new"));
    }

    #[test]
    fn rewrite_context_keeps_shadowed_user_type_constructor_names() {
        let mut context = RewriteContext::default();
        context
            .type_targets
            .insert("Point".to_owned(), "lib.Point".to_owned());
        let body = FunctionBody::Expr(qualified_name(&["Point", "new"]));
        let params = vec!["Point".to_owned()];

        let rewritten = rewrite_function_body(&body, &params, &context);

        let FunctionBody::Expr(expr) = rewritten else {
            panic!("expression body expected");
        };
        assert_eq!(expr_name(&expr).as_deref(), Some("Point.new"));
    }
}
