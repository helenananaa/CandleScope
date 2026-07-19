use std::collections::HashSet;

use pine_ir::{PineType, Qualifier, ValueKind};
use pine_syntax::{CallArg, Diagnostic, Span};

use super::{
    ImportedUdtConstructorArgError, ImportedUdtConstructorArgPlan, UdtConstructor,
    UdtFieldAccessStep, UserTypeIdentity,
};
use crate::analyzer::chart_points::{chart_point_field_index, chart_point_field_type};
use crate::analyzer::context::Analyzer;
use crate::compatibility::FeatureUse;
use crate::types::{UNKNOWN, can_assign, pine_type_name, strongest_qualifier, value_kind_name};

impl Analyzer {
    pub(crate) fn imported_user_type_constructor_metadata(
        &self,
        callee_name: &str,
    ) -> Option<&crate::modules::ImportedUserTypeInfo> {
        let type_name = callee_name.strip_suffix(".new")?;
        self.imported_user_types.get(type_name)
    }

    pub(crate) fn imported_user_type_has_scalar_tree_fields(
        &self,
        user_type: &crate::modules::ImportedUserTypeInfo,
    ) -> bool {
        self.imported_user_type_has_scalar_tree_fields_inner(user_type, &mut HashSet::new())
    }

    fn imported_user_type_has_scalar_tree_fields_inner(
        &self,
        user_type: &crate::modules::ImportedUserTypeInfo,
        seen: &mut HashSet<UserTypeIdentity>,
    ) -> bool {
        let identity = UserTypeIdentity {
            source_id: user_type.identity.source_id,
            name: user_type.identity.name.clone(),
        };
        if !seen.insert(identity.clone()) {
            return false;
        }
        let supported = user_type.fields.iter().all(|field| {
            if let Some(pine_type) = field.pine_type {
                return matches!(
                    pine_type.kind,
                    ValueKind::Int
                        | ValueKind::Float
                        | ValueKind::Bool
                        | ValueKind::String
                        | ValueKind::Color
                );
            }
            self.imported_user_type_field_user_type(user_type, field)
                .is_some_and(|nested| {
                    self.imported_user_type_has_scalar_tree_fields_inner(nested, seen)
                })
        });
        seen.remove(&identity);
        supported
    }

    pub(crate) fn imported_user_type_constructor_has_supported_fields(
        &self,
        callee_name: &str,
    ) -> Option<bool> {
        let user_type = self.imported_user_type_constructor_metadata(callee_name)?;
        Some(
            self.imported_user_type_constructor_fields_are_supported(
                user_type,
                &mut HashSet::new(),
            ),
        )
    }

    fn imported_user_type_constructor_fields_are_supported(
        &self,
        user_type: &crate::modules::ImportedUserTypeInfo,
        seen: &mut HashSet<UserTypeIdentity>,
    ) -> bool {
        let identity = UserTypeIdentity {
            source_id: user_type.identity.source_id,
            name: user_type.identity.name.clone(),
        };
        if !seen.insert(identity.clone()) {
            return false;
        }
        let supported = user_type.fields.iter().all(|field| {
            if field.pine_type.is_some() {
                return true;
            }
            self.imported_user_type_field_user_type(user_type, field)
                .is_some_and(|nested| {
                    self.imported_user_type_has_scalar_tree_fields_inner(nested, seen)
                })
        });
        seen.remove(&identity);
        supported
    }

    pub(crate) fn imported_user_type_history_is_supported(&self, type_name: &str) -> bool {
        self.imported_user_types.contains_key(type_name)
    }

    pub(crate) fn imported_user_type_array_is_supported(&self, type_name: &str) -> bool {
        self.imported_user_types
            .get(type_name)
            .is_some_and(|user_type| self.imported_user_type_has_scalar_tree_fields(user_type))
    }

    pub(crate) fn imported_user_type_constructor_arg_plan(
        &self,
        callee_name: &str,
        args: &[CallArg],
    ) -> Option<Result<ImportedUdtConstructorArgPlan, ImportedUdtConstructorArgError>> {
        let user_type = self.imported_user_type_constructor_metadata(callee_name)?;
        if args.len() > user_type.fields.len() {
            return Some(Err(ImportedUdtConstructorArgError::TooManyArgs {
                expected: user_type.fields.len(),
                actual: args.len(),
            }));
        }

        let mut resolved = vec![None; user_type.fields.len()];
        let mut positional_open = true;
        let mut next_positional = 0;
        for (arg_index, arg) in args.iter().enumerate() {
            if let Some(name) = &arg.name {
                positional_open = false;
                let Some(index) = user_type
                    .fields
                    .iter()
                    .position(|field| field.name == *name)
                else {
                    return Some(Err(ImportedUdtConstructorArgError::UnknownField(
                        name.clone(),
                    )));
                };
                if resolved[index].is_some() {
                    return Some(Err(ImportedUdtConstructorArgError::DuplicateField(
                        name.clone(),
                    )));
                }
                resolved[index] = Some(arg_index);
            } else {
                if !positional_open {
                    return Some(Err(ImportedUdtConstructorArgError::PositionalAfterNamed));
                }
                resolved[next_positional] = Some(arg_index);
                next_positional += 1;
            }
        }

        if let Some((index, _)) = resolved.iter().enumerate().find(|(_, seen)| seen.is_none()) {
            return Some(Err(ImportedUdtConstructorArgError::MissingField(
                user_type.fields[index].name.clone(),
            )));
        }
        Some(Ok(ImportedUdtConstructorArgPlan {
            supported_fields: self
                .imported_user_type_constructor_has_supported_fields(callee_name)
                .unwrap_or(false),
            field_arg_indices: resolved.into_iter().flatten().collect(),
        }))
    }

    pub(crate) fn imported_user_type_constructor(
        &mut self,
        callee_name: &str,
        args: &[CallArg],
        span: Span,
    ) -> Option<UdtConstructor> {
        let type_name = callee_name.strip_suffix(".new")?;
        let user_type = self.imported_user_types.get(type_name)?.clone();
        let plan = match self.imported_user_type_constructor_arg_plan(callee_name, args)? {
            Ok(plan) => plan,
            Err(error) => {
                self.diagnostics.push(imported_constructor_arg_diagnostic(
                    callee_name,
                    error,
                    span,
                ));
                return Some(imported_error_constructor(&user_type));
            }
        };
        if !plan.supported_fields {
            self.diagnostics.push(Diagnostic::error(
                "E_IMPORT_UNSUPPORTED_UDT",
                format!(
                    "imported UDT `{type_name}` is not supported; non-scalar or unresolved field metadata remains unsupported"
                ),
                span,
            ));
            return Some(imported_error_constructor(&user_type));
        }

        let mut qualifier = Qualifier::Const;
        let mut field_args = Vec::with_capacity(plan.field_arg_indices.len());
        for (field_index, arg_index) in plan.field_arg_indices.iter().copied().enumerate() {
            let field = &user_type.fields[field_index];
            let arg = &args[arg_index];
            let arg_type = self.analyze_expr(&arg.value).unwrap_or(UNKNOWN);
            if !self.can_assign_imported_user_type_field(&user_type, field, &arg.value, arg_type) {
                self.diagnostics.push(Diagnostic::error(
                    "E_UDT_CONSTRUCTOR_ARG",
                    format!(
                        "cannot assign {} to imported field `{}` of type {}",
                        pine_type_name(arg_type),
                        field.name,
                        value_kind_name(
                            self.imported_user_type_field_kind(&user_type, field)
                                .expect("supported imported UDT field has a resolved type")
                        )
                    ),
                    arg.span,
                ));
            }
            qualifier = strongest_qualifier(qualifier, arg_type.qualifier);
            field_args.push(arg.value.clone());
        }

        let pine_type = PineType::new(qualifier, ValueKind::UserType);
        self.mark_expr_user_type(span, type_name.to_owned());
        self.compatibility.supported.push(FeatureUse {
            feature: "user-defined types".to_owned(),
            span,
        });
        Some(UdtConstructor {
            identity: UserTypeIdentity {
                source_id: user_type.identity.source_id,
                name: user_type.identity.name,
            },
            field_args,
            pine_type,
        })
    }

    pub(crate) fn imported_user_type_constructor_for_lowering(
        &self,
        callee_name: &str,
        args: &[CallArg],
        param_types: &std::collections::HashMap<String, PineType>,
    ) -> Option<UdtConstructor> {
        let type_name = callee_name.strip_suffix(".new")?;
        let user_type = self.imported_user_types.get(type_name)?;
        let plan = self
            .imported_user_type_constructor_arg_plan(callee_name, args)?
            .ok()?;
        if !plan.supported_fields {
            return None;
        }
        Some(UdtConstructor {
            identity: UserTypeIdentity {
                source_id: user_type.identity.source_id,
                name: user_type.identity.name.clone(),
            },
            field_args: plan
                .field_arg_indices
                .into_iter()
                .map(|arg_index| args[arg_index].value.clone())
                .collect(),
            pine_type: self.type_of_imported_user_type_constructor_with_params(
                callee_name,
                args,
                param_types,
            )?,
        })
    }

    pub(crate) fn type_of_imported_user_type_constructor_with_params(
        &self,
        callee_name: &str,
        args: &[CallArg],
        param_types: &std::collections::HashMap<String, PineType>,
    ) -> Option<PineType> {
        let plan = self
            .imported_user_type_constructor_arg_plan(callee_name, args)?
            .ok()?;
        if !plan.supported_fields {
            return None;
        }
        let mut qualifier = Qualifier::Const;
        for arg in args {
            let arg_type = self.type_of_expr_with_params(&arg.value, param_types)?;
            qualifier = strongest_qualifier(qualifier, arg_type.qualifier);
        }
        Some(PineType::new(qualifier, ValueKind::UserType))
    }

    pub(crate) fn imported_user_type_field_path(
        &self,
        type_name: &str,
        qualifier: Qualifier,
        field_names: &[String],
    ) -> Option<(PineType, Option<String>, Vec<UdtFieldAccessStep>)> {
        let user_type = self.imported_user_types.get(type_name)?;
        let mut current_type = user_type;
        let mut final_type = None;
        let mut final_user_type_name = None;
        let mut fields = Vec::with_capacity(field_names.len());
        for (field_index, field_name) in field_names.iter().enumerate() {
            let (index, field) = current_type
                .fields
                .iter()
                .enumerate()
                .find(|(_, field)| field.name == *field_name)?;
            let pine_type = self.imported_user_type_field_type(current_type, field, qualifier)?;
            final_type = Some(pine_type);
            final_user_type_name = self.imported_user_type_field_type_name(current_type, field);
            fields.push(UdtFieldAccessStep { index, pine_type });
            if field_index + 1 < field_names.len() {
                if pine_type.kind == ValueKind::ChartPoint && field_index + 2 == field_names.len() {
                    let chart_point_field_name = &field_names[field_index + 1];
                    let chart_point_type =
                        chart_point_field_type(pine_type, chart_point_field_name)?;
                    let chart_point_index = chart_point_field_index(chart_point_field_name)?;
                    fields.push(UdtFieldAccessStep {
                        index: chart_point_index,
                        pine_type: chart_point_type,
                    });
                    return Some((chart_point_type, None, fields));
                }
                current_type = self.imported_user_type_field_user_type(current_type, field)?;
            }
        }
        Some((final_type?, final_user_type_name, fields))
    }

    pub(crate) fn resolve_imported_user_type_field_path(
        &mut self,
        type_name: &str,
        qualifier: Qualifier,
        field_names: &[String],
        span: Span,
    ) -> Option<(PineType, Option<String>, Vec<UdtFieldAccessStep>)> {
        let mut current_type_name = type_name.to_owned();
        let mut current_type = self.imported_user_types.get(type_name)?;
        for (field_index, field_name) in field_names.iter().enumerate() {
            let Some(field) = current_type
                .fields
                .iter()
                .find(|field| field.name == *field_name)
            else {
                self.diagnostics.push(Diagnostic::error(
                    "E_UDT_UNKNOWN_FIELD",
                    format!("unknown field `{field_name}` on `{current_type_name}`"),
                    span,
                ));
                return None;
            };
            if field_index + 1 < field_names.len() {
                let Some(pine_type) =
                    self.imported_user_type_field_type(current_type, field, qualifier)
                else {
                    self.diagnostics.push(Diagnostic::error(
                        "E_UDT_UNKNOWN_FIELD",
                        format!(
                            "field `{field_name}` on `{current_type_name}` is not a supported field type"
                        ),
                        span,
                    ));
                    return None;
                };
                if pine_type.kind == ValueKind::ChartPoint && field_index + 2 == field_names.len() {
                    let chart_point_field_name = &field_names[field_index + 1];
                    if chart_point_field_type(pine_type, chart_point_field_name).is_some() {
                        break;
                    }
                    self.diagnostics.push(Diagnostic::error(
                        "E_CHART_POINT_UNKNOWN_FIELD",
                        format!("unknown field `{chart_point_field_name}` on `chart.point`"),
                        span,
                    ));
                    return None;
                }
                let Some(next_type_name) =
                    self.imported_user_type_field_type_name(current_type, field)
                else {
                    self.diagnostics.push(Diagnostic::error(
                        "E_UDT_UNKNOWN_FIELD",
                        format!(
                            "field `{field_name}` on `{current_type_name}` is not a user-defined type"
                        ),
                        span,
                    ));
                    return None;
                };
                current_type_name = next_type_name;
                current_type = self.imported_user_types.get(&current_type_name)?;
            }
        }
        self.imported_user_type_field_path(type_name, qualifier, field_names)
    }

    fn imported_user_type_field_type(
        &self,
        user_type: &crate::modules::ImportedUserTypeInfo,
        field: &crate::modules::ImportedUserTypeFieldInfo,
        qualifier: Qualifier,
    ) -> Option<PineType> {
        if let Some(pine_type) = field.pine_type {
            return Some(PineType::new(qualifier, pine_type.kind));
        }
        self.imported_user_type_field_user_type(user_type, field)
            .map(|_| PineType::new(qualifier, ValueKind::UserType))
    }

    fn imported_user_type_field_kind(
        &self,
        user_type: &crate::modules::ImportedUserTypeInfo,
        field: &crate::modules::ImportedUserTypeFieldInfo,
    ) -> Option<ValueKind> {
        field.pine_type.map(|pine_type| pine_type.kind).or_else(|| {
            self.imported_user_type_field_user_type(user_type, field)
                .map(|_| ValueKind::UserType)
        })
    }

    fn imported_user_type_field_type_name(
        &self,
        user_type: &crate::modules::ImportedUserTypeInfo,
        field: &crate::modules::ImportedUserTypeFieldInfo,
    ) -> Option<String> {
        self.imported_user_type_field_user_type_name(user_type, field)
            .map(str::to_owned)
    }

    fn imported_user_type_field_user_type<'a>(
        &'a self,
        user_type: &crate::modules::ImportedUserTypeInfo,
        field: &crate::modules::ImportedUserTypeFieldInfo,
    ) -> Option<&'a crate::modules::ImportedUserTypeInfo> {
        let type_name = self.imported_user_type_field_user_type_name(user_type, field)?;
        self.imported_user_types.get(type_name)
    }

    fn imported_user_type_field_user_type_name<'a>(
        &'a self,
        user_type: &crate::modules::ImportedUserTypeInfo,
        field: &crate::modules::ImportedUserTypeFieldInfo,
    ) -> Option<&'a str> {
        if field.pine_type.is_some() {
            return None;
        }
        self.imported_user_types
            .iter()
            .find(|(_, nested)| {
                nested.identity.source_id == user_type.identity.source_id
                    && nested.identity.name == field.type_name
            })
            .map(|(name, _)| name.as_str())
    }

    fn can_assign_imported_user_type_field(
        &self,
        user_type: &crate::modules::ImportedUserTypeInfo,
        field: &crate::modules::ImportedUserTypeFieldInfo,
        value: &pine_syntax::Expr,
        value_type: PineType,
    ) -> bool {
        if let Some(expected_type) = field.pine_type {
            return can_assign(expected_type, value_type);
        }
        let Some(expected_type) = self.imported_user_type_field_user_type(user_type, field) else {
            return false;
        };
        let expected_identity = UserTypeIdentity {
            source_id: expected_type.identity.source_id,
            name: expected_type.identity.name.clone(),
        };
        self.user_type_name_of_expr(value)
            .and_then(|actual_type_name| self.user_type_identity_for_name(&actual_type_name))
            .is_some_and(|actual_identity| actual_identity == expected_identity)
    }
}

fn imported_error_constructor(user_type: &crate::modules::ImportedUserTypeInfo) -> UdtConstructor {
    UdtConstructor {
        identity: UserTypeIdentity {
            source_id: user_type.identity.source_id,
            name: user_type.identity.name.clone(),
        },
        field_args: Vec::new(),
        pine_type: UNKNOWN,
    }
}

fn imported_constructor_arg_diagnostic(
    callee_name: &str,
    error: ImportedUdtConstructorArgError,
    span: Span,
) -> Diagnostic {
    match error {
        ImportedUdtConstructorArgError::TooManyArgs { expected, actual } => Diagnostic::error(
            "E_UDT_CONSTRUCTOR_ARG",
            format!("`{callee_name}` expects {expected} field argument(s), got {actual}"),
            span,
        ),
        ImportedUdtConstructorArgError::UnknownField(name) => Diagnostic::error(
            "E_UDT_CONSTRUCTOR_ARG",
            format!("unknown field `{name}` for `{callee_name}` constructor"),
            span,
        ),
        ImportedUdtConstructorArgError::DuplicateField(name) => Diagnostic::error(
            "E_UDT_CONSTRUCTOR_ARG",
            format!("duplicate field `{name}` for `{callee_name}` constructor"),
            span,
        ),
        ImportedUdtConstructorArgError::PositionalAfterNamed => Diagnostic::error(
            "E_UDT_CONSTRUCTOR_ARG",
            "positional field argument cannot follow named field argument",
            span,
        ),
        ImportedUdtConstructorArgError::MissingField(name) => Diagnostic::error(
            "E_UDT_CONSTRUCTOR_ARG",
            format!("missing field `{name}` for `{callee_name}` constructor"),
            span,
        ),
    }
}
