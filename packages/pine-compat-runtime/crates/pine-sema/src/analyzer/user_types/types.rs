use std::collections::{HashMap, HashSet};

use pine_ir::{PineType, ValueKind};
use pine_syntax::{Expr, Span};

use crate::resolver::SymbolInfo;
use crate::source_graph::{SourceContextId, SourceId};

#[derive(Debug, Clone)]
pub(crate) struct UserTypeInfo {
    pub(crate) identity: UserTypeIdentity,
    pub(crate) name: String,
    pub(crate) fields: Vec<UserTypeFieldInfo>,
}

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub(crate) struct UserTypeIdentity {
    pub(crate) source_id: SourceId,
    pub(crate) name: String,
}

#[derive(Debug, Clone)]
pub(crate) struct UserTypeFieldInfo {
    pub(crate) name: String,
    pub(crate) pine_type: PineType,
    pub(crate) user_type_name: Option<String>,
}

#[derive(Debug, Clone)]
pub(crate) struct UdtConstructor {
    pub(crate) identity: UserTypeIdentity,
    pub(crate) field_args: Vec<Expr>,
    pub(crate) pine_type: PineType,
}

#[derive(Debug, Clone)]
pub(crate) struct UdtFieldAccess {
    pub(crate) receiver: String,
    pub(crate) fields: Vec<UdtFieldAccessStep>,
}

#[derive(Debug, Clone)]
pub(crate) struct UdtFieldAccessStep {
    pub(crate) index: usize,
    pub(crate) pine_type: PineType,
}

pub(crate) struct UdtFieldMutation {
    pub(crate) pine_type: PineType,
    pub(crate) user_type_name: Option<String>,
    pub(crate) receiver_symbol: SymbolInfo,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum UserTypeArrayElementInference {
    SameScalarLocal(String),
    SameScalarImported(String),
    MixedLocal,
    UnsupportedFieldType(String),
    UnknownUserTypeName,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum ImportedUdtConstructorArgError {
    TooManyArgs { expected: usize, actual: usize },
    UnknownField(String),
    DuplicateField(String),
    PositionalAfterNamed,
    MissingField(String),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct ImportedUdtConstructorArgPlan {
    pub(crate) supported_fields: bool,
    pub(crate) field_arg_indices: Vec<usize>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub(crate) struct ExprKey {
    pub(crate) source_context_id: SourceContextId,
    pub(crate) span_start: usize,
    pub(crate) span_end: usize,
}

pub(crate) fn expr_key(source_context_id: SourceContextId, span: Span) -> ExprKey {
    ExprKey {
        source_context_id,
        span_start: span.start,
        span_end: span.end,
    }
}

pub(crate) fn classify_user_type_array_element_names(
    user_types: &HashMap<String, UserTypeInfo>,
    type_names: &[String],
) -> Option<UserTypeArrayElementInference> {
    let first = type_names.first()?;
    if type_names.iter().any(|type_name| type_name != first) {
        return Some(UserTypeArrayElementInference::MixedLocal);
    }

    let user_type = user_types.get(first)?;
    debug_assert_eq!(user_type.identity.source_id, SourceId::root());
    debug_assert_eq!(user_type.identity.name, *first);
    if local_user_type_has_scalar_tree_fields(user_types, &user_type.name, &mut HashSet::new()) {
        Some(UserTypeArrayElementInference::SameScalarLocal(
            first.clone(),
        ))
    } else {
        Some(UserTypeArrayElementInference::UnsupportedFieldType(
            first.clone(),
        ))
    }
}

fn local_user_type_has_scalar_tree_fields(
    user_types: &HashMap<String, UserTypeInfo>,
    type_name: &str,
    seen: &mut HashSet<String>,
) -> bool {
    if !seen.insert(type_name.to_owned()) {
        return false;
    }
    let Some(user_type) = user_types.get(type_name) else {
        return false;
    };
    let supported = user_type.fields.iter().all(|field| {
        if let Some(field_type_name) = &field.user_type_name {
            local_user_type_has_scalar_tree_fields(user_types, field_type_name, seen)
        } else {
            is_scalar_user_type_array_field(field)
        }
    });
    seen.remove(type_name);
    supported
}

fn is_scalar_user_type_array_field(field: &UserTypeFieldInfo) -> bool {
    matches!(
        field.pine_type.kind,
        ValueKind::Int | ValueKind::Float | ValueKind::Bool | ValueKind::String | ValueKind::Color
    )
}
