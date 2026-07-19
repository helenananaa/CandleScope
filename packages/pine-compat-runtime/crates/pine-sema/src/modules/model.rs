use std::collections::{HashMap, HashSet};

use pine_ir::{PineType, Qualifier, ValueKind};
use pine_syntax::{Diagnostic, Expr, FunctionBody, Program, Span};

use crate::analyzer::context::{FunctionInfo, MethodInfo};
use crate::source_graph::SourceId;

#[derive(Debug)]
pub(crate) struct ModuleValidation {
    pub(crate) diagnostics: Vec<Diagnostic>,
    pub(crate) root_program: Program,
    pub(crate) imported_functions: HashMap<String, FunctionInfo>,
    pub(crate) imported_methods: HashMap<(String, String), MethodInfo>,
    pub(crate) imported_user_types: HashMap<String, ImportedUserTypeInfo>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct ImportedUserTypeInfo {
    pub(crate) identity: ImportedUserTypeIdentity,
    pub(crate) fields: Vec<ImportedUserTypeFieldInfo>,
    pub(crate) span: Span,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct ImportedUserTypeIdentity {
    pub(crate) source_id: SourceId,
    pub(crate) name: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct ImportedUserTypeFieldInfo {
    pub(crate) name: String,
    pub(crate) type_name: String,
    pub(crate) pine_type: Option<PineType>,
    pub(crate) span: Span,
}

#[derive(Debug)]
pub(super) struct ModuleInfo {
    pub(super) id: SourceId,
    pub(super) key: Option<String>,
    pub(super) program: Program,
    pub(super) exports: HashMap<String, ExportInfo>,
    pub(super) private_symbols: HashSet<String>,
    pub(super) user_types: HashMap<String, ModuleUserTypeInfo>,
    pub(super) methods: HashMap<(String, String), ModuleMethodInfo>,
    pub(super) functions: HashMap<String, FunctionInfo>,
    pub(super) constants: HashMap<String, Expr>,
}

#[derive(Debug, Clone)]
pub(super) enum ExportInfo {
    Function {
        span: Span,
    },
    Const {
        value: Expr,
        span: Span,
    },
    UserType {
        identity: ModuleUserTypeIdentity,
        fields: Vec<ModuleUserTypeFieldInfo>,
        span: Span,
    },
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(super) struct ModuleUserTypeIdentity {
    pub(super) source_id: SourceId,
    pub(super) name: String,
}

#[derive(Debug, Clone)]
pub(super) struct ModuleUserTypeInfo {
    pub(super) identity: ModuleUserTypeIdentity,
    pub(super) fields: Vec<ModuleUserTypeFieldInfo>,
    pub(super) span: Span,
}

#[derive(Debug, Clone)]
pub(super) struct ModuleUserTypeFieldInfo {
    pub(super) name: String,
    pub(super) type_name: String,
    pub(super) pine_type: Option<PineType>,
    pub(super) span: Span,
}

#[derive(Debug, Clone)]
pub(super) struct ModuleMethodInfo {
    pub(super) receiver_type_name: Option<String>,
    pub(super) receiver_identity: Option<ModuleUserTypeIdentity>,
    pub(super) receiver_name: String,
    pub(super) params: Vec<ModuleMethodParamInfo>,
    pub(super) param_names: Vec<String>,
    pub(super) body: FunctionBody,
    pub(super) span: Span,
}

#[derive(Debug, Clone)]
pub(super) struct ModuleMethodParamInfo {
    pub(super) name: String,
    pub(super) type_name: String,
}

#[derive(Debug, Clone)]
pub(super) struct ImportRef {
    pub(super) key: String,
    pub(super) alias: Option<(String, Span)>,
    pub(super) span: Span,
}

pub(super) fn imported_user_type_scalar_field_type(type_name: &str) -> Option<PineType> {
    let kind = match type_name {
        "int" => ValueKind::Int,
        "float" => ValueKind::Float,
        "bool" => ValueKind::Bool,
        "string" => ValueKind::String,
        "color" => ValueKind::Color,
        _ => return None,
    };
    Some(PineType::new(Qualifier::Series, kind))
}

pub(super) fn imported_user_type_field_type(type_name: &str) -> Option<PineType> {
    let kind = match type_name {
        "int" => ValueKind::Int,
        "float" => ValueKind::Float,
        "bool" => ValueKind::Bool,
        "string" => ValueKind::String,
        "color" => ValueKind::Color,
        "label" => ValueKind::Label,
        "line" => ValueKind::Line,
        "linefill" => ValueKind::LineFill,
        "polyline" => ValueKind::Polyline,
        "box" => ValueKind::Box,
        "table" => ValueKind::Table,
        "chart.point" => ValueKind::ChartPoint,
        _ => return None,
    };
    Some(PineType::new(Qualifier::Series, kind))
}

pub(super) fn module_user_type_fields_match(
    left: &[ModuleUserTypeFieldInfo],
    right: &[ModuleUserTypeFieldInfo],
) -> bool {
    left.len() == right.len()
        && left.iter().zip(right).all(|(left, right)| {
            left.name == right.name
                && left.type_name == right.type_name
                && left.pine_type == right.pine_type
                && left.span == right.span
        })
}

impl ExportInfo {
    pub(super) fn span(&self) -> Span {
        match self {
            ExportInfo::Function { span }
            | ExportInfo::Const { span, .. }
            | ExportInfo::UserType { span, .. } => *span,
        }
    }
}
