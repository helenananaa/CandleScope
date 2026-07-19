use std::collections::HashMap;

use pine_ir::{PineType, Qualifier, ValueKind};
use pine_syntax::{CallArg, Diagnostic, Expr, Span};

use super::{UdtConstructor, UserTypeFieldInfo, UserTypeInfo};
use crate::analyzer::context::Analyzer;
use crate::compatibility::FeatureUse;
use crate::types::{UNKNOWN, can_assign, pine_type_name, strongest_qualifier, value_kind_name};

impl Analyzer {
    pub(crate) fn user_type_constructor(
        &mut self,
        callee_name: &str,
        args: &[CallArg],
        span: Span,
    ) -> Option<UdtConstructor> {
        let type_name = callee_name.strip_suffix(".new")?;
        let user_type = self.user_types.get(type_name).cloned()?;

        let resolved = self.resolve_constructor_args(&user_type, args, span)?;
        let mut qualifier = Qualifier::Const;
        let mut field_args = Vec::with_capacity(resolved.len());
        for (field, arg) in user_type.fields.iter().zip(resolved) {
            let Some(arg) = arg else {
                self.diagnostics.push(Diagnostic::error(
                    "E_UDT_CONSTRUCTOR_ARG",
                    format!(
                        "missing field `{}` for `{}` constructor",
                        field.name, type_name
                    ),
                    span,
                ));
                return None;
            };
            let arg_type = self.analyze_expr(&arg.value).unwrap_or(UNKNOWN);
            if !self.can_assign_user_type_field(field, &arg.value, arg_type) {
                self.diagnostics.push(Diagnostic::error(
                    "E_UDT_CONSTRUCTOR_ARG",
                    format!(
                        "cannot assign {} to field `{}` of type {}",
                        pine_type_name(arg_type),
                        field.name,
                        value_kind_name(field.pine_type.kind)
                    ),
                    arg.span,
                ));
            }
            qualifier = strongest_qualifier(qualifier, arg_type.qualifier);
            field_args.push(arg.value.clone());
        }

        let pine_type = PineType::new(qualifier, ValueKind::UserType);
        self.mark_expr_user_type(span, user_type.name.clone());
        self.compatibility.supported.push(FeatureUse {
            feature: "user-defined types".to_owned(),
            span,
        });
        Some(UdtConstructor {
            identity: user_type.identity.clone(),
            field_args,
            pine_type,
        })
    }

    pub(crate) fn type_of_user_type_constructor_with_params(
        &self,
        callee_name: &str,
        args: &[CallArg],
        param_types: &HashMap<String, PineType>,
    ) -> Option<PineType> {
        let type_name = callee_name.strip_suffix(".new")?;
        let user_type = self.user_types.get(type_name)?;
        if args.len() != user_type.fields.len() {
            return None;
        }
        let mut qualifier = Qualifier::Const;
        for arg in args {
            let arg_type = self.type_of_expr_with_params(&arg.value, param_types)?;
            qualifier = strongest_qualifier(qualifier, arg_type.qualifier);
        }
        Some(PineType::new(qualifier, ValueKind::UserType))
    }

    pub(crate) fn user_type_constructor_for_lowering(
        &self,
        callee_name: &str,
        args: &[CallArg],
        param_types: &HashMap<String, PineType>,
    ) -> Option<UdtConstructor> {
        let type_name = callee_name.strip_suffix(".new")?;
        let user_type = self.user_types.get(type_name)?;
        let mut field_args = vec![None; user_type.fields.len()];
        let mut next_positional = 0;
        for arg in args {
            let index = match &arg.name {
                Some(name) => user_type
                    .fields
                    .iter()
                    .position(|field| field.name == *name)?,
                None => {
                    let index = next_positional;
                    next_positional += 1;
                    index
                }
            };
            field_args[index] = Some(arg.value.clone());
        }
        Some(UdtConstructor {
            identity: user_type.identity.clone(),
            field_args: field_args.into_iter().collect::<Option<_>>()?,
            pine_type: self.type_of_user_type_constructor_with_params(
                callee_name,
                args,
                param_types,
            )?,
        })
    }

    fn resolve_constructor_args(
        &mut self,
        user_type: &UserTypeInfo,
        args: &[CallArg],
        span: Span,
    ) -> Option<Vec<Option<CallArg>>> {
        if args.len() > user_type.fields.len() {
            self.diagnostics.push(Diagnostic::error(
                "E_UDT_CONSTRUCTOR_ARG",
                format!(
                    "`{}.new` expects {} field argument(s), got {}",
                    user_type.name,
                    user_type.fields.len(),
                    args.len()
                ),
                span,
            ));
            return None;
        }

        let mut resolved = vec![None; user_type.fields.len()];
        let mut positional_open = true;
        let mut next_positional = 0;
        for arg in args {
            if let Some(name) = &arg.name {
                positional_open = false;
                let Some(index) = user_type
                    .fields
                    .iter()
                    .position(|field| field.name == *name)
                else {
                    self.diagnostics.push(Diagnostic::error(
                        "E_UDT_CONSTRUCTOR_ARG",
                        format!(
                            "unknown field `{name}` for `{}` constructor",
                            user_type.name
                        ),
                        arg.span,
                    ));
                    return None;
                };
                if resolved[index].is_some() {
                    self.diagnostics.push(Diagnostic::error(
                        "E_UDT_CONSTRUCTOR_ARG",
                        format!(
                            "duplicate field `{name}` for `{}` constructor",
                            user_type.name
                        ),
                        arg.span,
                    ));
                    return None;
                }
                resolved[index] = Some(arg.clone());
            } else {
                if !positional_open {
                    self.diagnostics.push(Diagnostic::error(
                        "E_UDT_CONSTRUCTOR_ARG",
                        "positional field argument cannot follow named field argument",
                        arg.span,
                    ));
                    return None;
                }
                resolved[next_positional] = Some(arg.clone());
                next_positional += 1;
            }
        }
        Some(resolved)
    }

    fn can_assign_user_type_field(
        &self,
        field: &UserTypeFieldInfo,
        value: &Expr,
        value_type: PineType,
    ) -> bool {
        if let Some(expected_type_name) = &field.user_type_name {
            return self
                .user_type_name_of_expr(value)
                .is_some_and(|actual_type_name| actual_type_name == *expected_type_name);
        }
        can_assign(field.pine_type, value_type)
    }
}
