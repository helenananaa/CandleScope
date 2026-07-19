use std::collections::{HashMap, HashSet};

use pine_ir::{PineType, Qualifier, SymbolId, ValueKind};
use pine_syntax::{
    CallArg, Diagnostic, Expr, ExprKind, FunctionBody, Program, Span, Stmt, StmtKind, SwitchArm,
    SwitchArmResult,
};

use crate::analyzer::calls::expr_name;
use crate::analyzer::chart_points::{chart_point_field_index, chart_point_field_type};
use crate::analyzer::context::Analyzer;
use crate::analyzer::functions::resolve_udf_arg_indices;
use crate::resolver::SymbolInfo;
use crate::source_graph::SourceId;
use crate::types::UNKNOWN;

mod arrays;
mod constructors;
mod flow;
mod imported;
mod types;

use self::flow::{
    branch_return_expr, is_na_expr, merge_user_type_name, returned_udf_param_index,
    user_type_identity_matches_name,
};
pub(crate) use types::{
    ExprKey, ImportedUdtConstructorArgError, ImportedUdtConstructorArgPlan, UdtConstructor,
    UdtFieldAccess, UdtFieldAccessStep, UdtFieldMutation, UserTypeArrayElementInference,
    UserTypeFieldInfo, UserTypeIdentity, UserTypeInfo, classify_user_type_array_element_names,
    expr_key,
};

#[derive(Debug, Clone)]
enum UserTypeArrayResultName {
    Known(String),
    Na,
    Unknown,
}

impl Analyzer {
    pub(crate) fn local_user_type_has_scalar_tree_fields(&self, type_name: &str) -> bool {
        self.local_user_type_scalar_tree_fields_are_supported(type_name, &mut HashSet::new())
    }

    pub(crate) fn local_user_type_history_is_supported(&self, type_name: &str) -> bool {
        self.user_types.contains_key(type_name)
    }

    fn local_user_type_scalar_tree_fields_are_supported(
        &self,
        type_name: &str,
        seen: &mut HashSet<String>,
    ) -> bool {
        if !seen.insert(type_name.to_owned()) {
            return false;
        }
        let Some(user_type) = self.user_types.get(type_name) else {
            return false;
        };
        let supported = user_type.fields.iter().all(|field| {
            if let Some(field_type_name) = &field.user_type_name {
                self.local_user_type_scalar_tree_fields_are_supported(field_type_name, seen)
            } else {
                matches!(
                    field.pine_type.kind,
                    ValueKind::Int
                        | ValueKind::Float
                        | ValueKind::Bool
                        | ValueKind::String
                        | ValueKind::Color
                )
            }
        });
        seen.remove(type_name);
        supported
    }

    pub(crate) fn register_user_types(&mut self, program: &Program) {
        for statement in &program.statements {
            let StmtKind::UserType(decl) = &statement.kind else {
                continue;
            };

            if self.user_types.contains_key(&decl.name) {
                self.diagnostics.push(Diagnostic::error(
                    "E_UDT_DUPLICATE",
                    format!("duplicate user-defined type `{}`", decl.name),
                    decl.name_span,
                ));
                continue;
            }

            let mut fields = Vec::new();
            let mut seen = HashMap::new();
            for field in &decl.fields {
                if let Some(existing) = seen.insert(field.name.clone(), field.span) {
                    self.diagnostics.push(Diagnostic::error(
                        "E_UDT_FIELD_DUPLICATE",
                        format!("duplicate field `{}` in `{}`", field.name, decl.name),
                        existing.merge(field.span),
                    ));
                    continue;
                }

                let Some((pine_type, user_type_name)) =
                    self.user_type_field_type(&field.type_name, field.span)
                else {
                    continue;
                };
                fields.push(UserTypeFieldInfo {
                    name: field.name.clone(),
                    pine_type,
                    user_type_name,
                });
            }

            self.user_types.insert(
                decl.name.clone(),
                UserTypeInfo {
                    identity: UserTypeIdentity {
                        source_id: SourceId::root(),
                        name: decl.name.clone(),
                    },
                    name: decl.name.clone(),
                    fields,
                },
            );
        }
    }

    pub(crate) fn resolve_user_type_field_access(
        &mut self,
        parts: &[String],
        span: Span,
    ) -> Option<PineType> {
        if parts.len() < 2 {
            return None;
        }
        let receiver = &parts[0];
        let symbol = self.scope.resolve(receiver)?;
        let type_name = self.symbol_user_types.get(&symbol.id)?.clone();
        if self.imported_user_types.contains_key(&type_name) {
            let Some((pine_type, user_type_name, _)) = self.resolve_imported_user_type_field_path(
                &type_name,
                symbol.pine_type.qualifier,
                &parts[1..],
                span,
            ) else {
                return Some(UNKNOWN);
            };
            self.bind_symbol(receiver, span, symbol);
            if let Some(user_type_name) = user_type_name {
                self.mark_expr_user_type(span, user_type_name);
            }
            return Some(pine_type);
        }
        let Some((pine_type, user_type_name, _)) = self.resolve_user_type_field_path(
            &type_name,
            symbol.pine_type.qualifier,
            &parts[1..],
            span,
        ) else {
            return Some(UNKNOWN);
        };
        self.bind_symbol(receiver, span, symbol);
        if let Some(user_type_name) = user_type_name {
            self.mark_expr_user_type(span, user_type_name);
        }
        Some(pine_type)
    }

    pub(crate) fn type_of_user_type_field_access(&self, parts: &[String]) -> Option<PineType> {
        if parts.len() < 2 {
            return None;
        }
        let symbol = self.scope.resolve(&parts[0])?;
        let type_name = self.symbol_user_types.get(&symbol.id)?;
        self.type_of_user_type_field_path(type_name, symbol.pine_type.qualifier, &parts[1..])
    }

    pub(crate) fn resolve_user_type_field_mutation(
        &mut self,
        receiver: &str,
        field_name: &str,
        span: Span,
    ) -> Option<UdtFieldMutation> {
        let Some(symbol) = self.scope.resolve(receiver) else {
            self.diagnostics.push(Diagnostic::error(
                "E_UNKNOWN_SYMBOL",
                format!("cannot reassign unknown symbol `{receiver}`"),
                span,
            ));
            return None;
        };
        let Some(type_name) = self.symbol_user_types.get(&symbol.id).cloned() else {
            self.diagnostics.push(Diagnostic::error(
                "E_UDT_FIELD_MUTATION",
                format!("cannot mutate field `{field_name}` on non-UDT `{receiver}`"),
                span,
            ));
            return None;
        };
        if self.imported_user_types.contains_key(&type_name) {
            let field_names = [field_name.to_owned()];
            let (pine_type, user_type_name, _) = self.resolve_imported_user_type_field_path(
                &type_name,
                symbol.pine_type.qualifier,
                &field_names,
                span,
            )?;
            self.bind_symbol(receiver, span, symbol);
            return Some(UdtFieldMutation {
                pine_type,
                user_type_name,
                receiver_symbol: symbol,
            });
        }
        let user_type = self.user_types.get(&type_name)?;
        let Some(field) = user_type
            .fields
            .iter()
            .find(|field| field.name == field_name)
        else {
            self.diagnostics.push(Diagnostic::error(
                "E_UDT_UNKNOWN_FIELD",
                format!("unknown field `{field_name}` on `{type_name}`"),
                span,
            ));
            return None;
        };
        let field_kind = field.pine_type.kind;
        let field_user_type_name = field.user_type_name.clone();
        self.bind_symbol(receiver, span, symbol);
        Some(UdtFieldMutation {
            pine_type: PineType::new(symbol.pine_type.qualifier, field_kind),
            user_type_name: field_user_type_name,
            receiver_symbol: symbol,
        })
    }

    pub(crate) fn type_of_bound_user_type_field_access(
        &self,
        parts: &[String],
        span: Span,
    ) -> Option<PineType> {
        if parts.len() < 2 {
            return None;
        }
        let symbol = self
            .bound_symbol(&parts[0], span)
            .or_else(|| self.scope.resolve(&parts[0]))?;
        let type_name = self.symbol_user_types.get(&symbol.id)?;
        self.type_of_user_type_field_path(type_name, symbol.pine_type.qualifier, &parts[1..])
    }

    pub(crate) fn user_type_field_access_for_lowering(
        &self,
        parts: &[String],
        span: Span,
    ) -> Option<UdtFieldAccess> {
        if parts.len() < 2 {
            return None;
        }
        let symbol = self
            .bound_symbol(&parts[0], span)
            .or_else(|| self.scope.resolve(&parts[0]))?;
        let type_name = self.symbol_user_types.get(&symbol.id)?;
        let (_, _, fields) =
            self.user_type_field_path(type_name, symbol.pine_type.qualifier, &parts[1..])?;
        Some(UdtFieldAccess {
            receiver: parts[0].clone(),
            fields,
        })
    }

    pub(crate) fn expr_user_type_name(&self, expr: &Expr) -> Option<String> {
        let type_name = self.expr_user_types.get(&self.expr_key(expr.span))?.clone();
        if let Some(identity) = self.expr_user_type_identity(expr) {
            debug_assert!(user_type_identity_matches_name(&identity, &type_name));
        }
        Some(type_name)
    }

    pub(crate) fn expr_user_type_identity(&self, expr: &Expr) -> Option<UserTypeIdentity> {
        self.expr_user_type_identities
            .get(&self.expr_key(expr.span))
            .cloned()
    }

    pub(crate) fn expr_user_type_array_name(&self, expr: &Expr) -> Option<String> {
        self.expr_user_type_arrays
            .get(&self.expr_key(expr.span))
            .cloned()
    }

    pub(crate) fn user_type_name_of_expr(&self, expr: &Expr) -> Option<String> {
        if let Some(type_name) = self.expr_user_type_name(expr) {
            return Some(type_name);
        }
        match &expr.kind {
            ExprKind::Identifier(name) => self
                .scope
                .resolve(name)
                .and_then(|symbol| self.symbol_user_types.get(&symbol.id).cloned()),
            ExprKind::QualifiedName(parts) if parts.len() == 1 => self
                .scope
                .resolve(&parts[0])
                .and_then(|symbol| self.symbol_user_types.get(&symbol.id).cloned()),
            ExprKind::QualifiedName(parts) => self.user_type_name_of_field_access(parts),
            ExprKind::Call { callee, args } => {
                self.user_type_name_of_udf_passthrough(expr_name(callee)?.as_str(), args)
            }
            ExprKind::Ternary {
                then_expr,
                else_expr,
                ..
            } => self.user_type_name_of_ternary_branches(then_expr, else_expr),
            ExprKind::If {
                then_branch,
                else_branch,
                ..
            } => self.user_type_name_of_if_branches(then_branch, else_branch),
            ExprKind::Switch { arms, .. } => self.user_type_name_of_switch_arms(arms),
            ExprKind::For { body, .. } => self.user_type_name_of_branch_return(body),
            ExprKind::ForIn { body, .. } => self.user_type_name_of_branch_return(body),
            ExprKind::While { body, .. } => self.user_type_name_of_branch_return(body),
            _ => None,
        }
    }

    pub(crate) fn direct_user_type_constructor_name(&self, expr: &Expr) -> Option<String> {
        let ExprKind::Call { callee, .. } = &expr.kind else {
            return None;
        };
        let callee_name = expr_name(callee)?;
        let type_name = callee_name.strip_suffix(".new")?;
        if self.expr_user_type_name(expr).as_deref() == Some(type_name) {
            return Some(type_name.to_owned());
        }
        None
    }

    pub(crate) fn direct_user_type_alias_name(&self, expr: &Expr) -> Option<String> {
        match &expr.kind {
            ExprKind::Identifier(name) => self
                .scope
                .resolve(name)
                .and_then(|symbol| self.symbol_user_types.get(&symbol.id).cloned()),
            ExprKind::QualifiedName(parts) if parts.len() == 1 => self
                .scope
                .resolve(&parts[0])
                .and_then(|symbol| self.symbol_user_types.get(&symbol.id).cloned()),
            _ => None,
        }
    }

    pub(crate) fn user_type_array_name_of_expr(&self, expr: &Expr) -> Option<String> {
        if let Some(type_name) = self.expr_user_type_array_name(expr) {
            return Some(type_name);
        }
        match &expr.kind {
            ExprKind::Identifier(name) => self
                .bound_symbol(name, expr.span)
                .or_else(|| self.scope.resolve(name))
                .and_then(|symbol| self.symbol_user_type_arrays.get(&symbol.id).cloned()),
            ExprKind::QualifiedName(parts) if parts.len() == 1 => self
                .bound_symbol(&parts[0], expr.span)
                .or_else(|| self.scope.resolve(&parts[0]))
                .and_then(|symbol| self.symbol_user_type_arrays.get(&symbol.id).cloned()),
            ExprKind::History { expr, .. } => self.user_type_array_name_of_expr(expr),
            _ => None,
        }
    }

    pub(crate) fn user_type_array_name_of_current_symbol(&self, name: &str) -> Option<String> {
        self.scope
            .resolve(name)
            .and_then(|symbol| self.symbol_user_type_arrays.get(&symbol.id).cloned())
    }

    pub(crate) fn mark_ternary_user_type_array(
        &mut self,
        span: Span,
        then_expr: &Expr,
        else_expr: &Expr,
    ) -> bool {
        let results = [
            self.user_type_array_result_name(then_expr),
            self.user_type_array_result_name(else_expr),
        ];
        self.mark_user_type_array_results(span, results)
    }

    pub(crate) fn mark_if_user_type_array(
        &mut self,
        span: Span,
        then_branch: &[Stmt],
        else_branch: &[Stmt],
    ) -> bool {
        let results = [
            self.user_type_array_branch_result_name(then_branch),
            self.user_type_array_branch_result_name(else_branch),
        ];
        self.mark_user_type_array_results(span, results)
    }

    pub(crate) fn mark_switch_user_type_array(&mut self, span: Span, arms: &[SwitchArm]) -> bool {
        let results: Vec<_> = arms
            .iter()
            .map(|arm| self.user_type_array_switch_result_name(&arm.result))
            .collect();
        self.mark_user_type_array_results(span, results)
    }

    pub(crate) fn mark_loop_user_type_array(&mut self, span: Span, body: &[Stmt]) -> bool {
        let result = self.user_type_array_branch_result_name(body);
        self.mark_user_type_array_results(span, [result])
    }

    pub(crate) fn user_type_array_name_of_function_body(
        &self,
        body: &FunctionBody,
    ) -> Option<String> {
        let result = match body {
            FunctionBody::Expr(expr) => self.user_type_array_result_name(expr),
            FunctionBody::Block(statements) => self.user_type_array_branch_result_name(statements),
        };
        match result {
            UserTypeArrayResultName::Known(type_name) => Some(type_name),
            UserTypeArrayResultName::Na | UserTypeArrayResultName::Unknown => None,
        }
    }

    fn mark_user_type_array_results(
        &mut self,
        span: Span,
        results: impl IntoIterator<Item = UserTypeArrayResultName>,
    ) -> bool {
        let UserTypeArrayResultName::Known(type_name) =
            Self::merge_user_type_array_results(results)
        else {
            return false;
        };
        self.mark_expr_user_type_array(span, type_name);
        true
    }

    fn merge_user_type_array_results(
        results: impl IntoIterator<Item = UserTypeArrayResultName>,
    ) -> UserTypeArrayResultName {
        let mut resolved = None;
        for result in results {
            match result {
                UserTypeArrayResultName::Known(type_name)
                    if resolved
                        .as_ref()
                        .is_some_and(|resolved| resolved != &type_name) =>
                {
                    return UserTypeArrayResultName::Unknown;
                }
                UserTypeArrayResultName::Known(type_name) => {
                    resolved.get_or_insert(type_name);
                }
                UserTypeArrayResultName::Na => {}
                UserTypeArrayResultName::Unknown => return UserTypeArrayResultName::Unknown,
            }
        }
        resolved.map_or(UserTypeArrayResultName::Na, UserTypeArrayResultName::Known)
    }

    fn user_type_array_result_name(&self, expr: &Expr) -> UserTypeArrayResultName {
        if let Some(type_name) = self.user_type_array_name_of_expr(expr) {
            UserTypeArrayResultName::Known(type_name)
        } else if self.user_type_array_result_is_na(expr) {
            UserTypeArrayResultName::Na
        } else {
            UserTypeArrayResultName::Unknown
        }
    }

    fn user_type_array_branch_result_name(&self, branch: &[Stmt]) -> UserTypeArrayResultName {
        let Some(last) = branch.last() else {
            return UserTypeArrayResultName::Unknown;
        };
        match &last.kind {
            StmtKind::Expr(expr) => self.user_type_array_result_name(expr),
            StmtKind::If {
                then_branch,
                else_branch,
                ..
            } => Self::merge_user_type_array_results([
                self.user_type_array_branch_result_name(then_branch),
                self.user_type_array_branch_result_name(else_branch),
            ]),
            StmtKind::For { body, .. }
            | StmtKind::ForIn { body, .. }
            | StmtKind::While { body, .. } => self.user_type_array_branch_result_name(body),
            _ => UserTypeArrayResultName::Unknown,
        }
    }

    fn user_type_array_switch_result_name(
        &self,
        result: &SwitchArmResult,
    ) -> UserTypeArrayResultName {
        match result {
            SwitchArmResult::Expr(expr) => self.user_type_array_result_name(expr),
            SwitchArmResult::Block(statements) => {
                self.user_type_array_branch_result_name(statements)
            }
        }
    }

    fn user_type_array_result_is_na(&self, expr: &Expr) -> bool {
        if is_na_expr(expr) {
            return true;
        }
        match &expr.kind {
            ExprKind::Identifier(name) => self
                .bound_symbol(name, expr.span)
                .is_some_and(|symbol| symbol.pine_type.kind == ValueKind::Na),
            ExprKind::QualifiedName(parts) if parts.len() == 1 => self
                .bound_symbol(&parts[0], expr.span)
                .is_some_and(|symbol| symbol.pine_type.kind == ValueKind::Na),
            ExprKind::Ternary {
                then_expr,
                else_expr,
                ..
            } => {
                self.user_type_array_result_is_na(then_expr)
                    && self.user_type_array_result_is_na(else_expr)
            }
            ExprKind::If {
                then_branch,
                else_branch,
                ..
            } => {
                self.user_type_array_branch_is_na(then_branch)
                    && self.user_type_array_branch_is_na(else_branch)
            }
            ExprKind::Switch { arms, .. } => {
                !arms.is_empty()
                    && arms.iter().all(|arm| match &arm.result {
                        SwitchArmResult::Expr(expr) => self.user_type_array_result_is_na(expr),
                        SwitchArmResult::Block(statements) => {
                            self.user_type_array_branch_is_na(statements)
                        }
                    })
            }
            ExprKind::For { body, .. }
            | ExprKind::ForIn { body, .. }
            | ExprKind::While { body, .. } => self.user_type_array_branch_is_na(body),
            ExprKind::History { expr, .. } => self.user_type_array_result_is_na(expr),
            _ => self
                .expr_types
                .get(&self.expr_key(expr.span))
                .is_some_and(|pine_type| pine_type.kind == ValueKind::Na),
        }
    }

    fn user_type_array_branch_is_na(&self, branch: &[Stmt]) -> bool {
        let Some(last) = branch.last() else {
            return false;
        };
        match &last.kind {
            StmtKind::Expr(expr) => self.user_type_array_result_is_na(expr),
            StmtKind::If {
                then_branch,
                else_branch,
                ..
            } => {
                self.user_type_array_branch_is_na(then_branch)
                    && self.user_type_array_branch_is_na(else_branch)
            }
            StmtKind::For { body, .. }
            | StmtKind::ForIn { body, .. }
            | StmtKind::While { body, .. } => self.user_type_array_branch_is_na(body),
            _ => false,
        }
    }

    pub(crate) fn mark_ternary_user_type(
        &mut self,
        span: Span,
        then_expr: &Expr,
        else_expr: &Expr,
    ) -> bool {
        let Some(type_name) = self.user_type_name_of_ternary_branches(then_expr, else_expr) else {
            return false;
        };
        self.mark_expr_user_type(span, type_name);
        true
    }

    pub(crate) fn user_type_name_of_ternary_branches(
        &self,
        then_expr: &Expr,
        else_expr: &Expr,
    ) -> Option<String> {
        match (
            self.user_type_name_of_expr(then_expr),
            self.user_type_name_of_expr(else_expr),
        ) {
            (Some(then_name), Some(else_name)) if then_name == else_name => Some(then_name),
            (Some(then_name), None) if is_na_expr(else_expr) => Some(then_name),
            (None, Some(else_name)) if is_na_expr(then_expr) => Some(else_name),
            _ => None,
        }
    }

    pub(crate) fn mark_switch_user_type(&mut self, span: Span, arms: &[SwitchArm]) -> bool {
        let Some(type_name) = self.user_type_name_of_switch_arms(arms) else {
            return false;
        };
        self.mark_expr_user_type(span, type_name);
        true
    }
    pub(crate) fn user_type_name_of_switch_arms(&self, arms: &[SwitchArm]) -> Option<String> {
        let mut resolved_type_name = None;
        let aliases = HashMap::new();
        for arm in arms {
            let (type_name, is_na) =
                self.user_type_name_of_switch_arm_result_with_local_aliases(&arm.result, &aliases);
            merge_user_type_name(&mut resolved_type_name, type_name, is_na)?;
        }
        resolved_type_name
    }
    pub(crate) fn user_type_name_of_if_branches(
        &self,
        then_branch: &[Stmt],
        else_branch: &[Stmt],
    ) -> Option<String> {
        let (_, then_expr) = branch_return_expr(then_branch)?;
        let (_, else_expr) = branch_return_expr(else_branch)?;
        match (
            self.user_type_name_of_branch_return(then_branch),
            self.user_type_name_of_branch_return(else_branch),
        ) {
            (Some(then_name), Some(else_name)) if then_name == else_name => Some(then_name),
            (Some(then_name), None) if is_na_expr(else_expr) => Some(then_name),
            (None, Some(else_name)) if is_na_expr(then_expr) => Some(else_name),
            _ => None,
        }
    }
    pub(crate) fn user_type_name_of_branch_return(&self, branch: &[Stmt]) -> Option<String> {
        let (prefix, expr) = branch_return_expr(branch)?;
        let aliases = self.local_user_type_aliases(prefix, &HashMap::new());
        self.user_type_name_of_expr_with_local_aliases(expr, &aliases)
    }

    fn local_user_type_aliases(
        &self,
        prefix: &[Stmt],
        outer_aliases: &HashMap<String, String>,
    ) -> HashMap<String, String> {
        let mut aliases = outer_aliases.clone();
        for statement in prefix {
            if let StmtKind::Decl { name, value, .. } = &statement.kind
                && let Some(type_name) =
                    self.user_type_name_of_expr_with_local_aliases(value, &aliases)
            {
                aliases.insert(name.clone(), type_name);
            }
        }
        aliases
    }

    fn user_type_name_of_expr_with_local_aliases(
        &self,
        expr: &Expr,
        aliases: &HashMap<String, String>,
    ) -> Option<String> {
        if let Some(type_name) = self.user_type_name_of_expr(expr) {
            return Some(type_name);
        }
        match &expr.kind {
            ExprKind::Identifier(name) => aliases.get(name).cloned(),
            ExprKind::QualifiedName(parts) if parts.len() == 1 => aliases.get(&parts[0]).cloned(),
            ExprKind::Ternary {
                then_expr,
                else_expr,
                ..
            } => match (
                self.user_type_name_of_expr_with_local_aliases(then_expr, aliases),
                self.user_type_name_of_expr_with_local_aliases(else_expr, aliases),
            ) {
                (Some(then_name), Some(else_name)) if then_name == else_name => Some(then_name),
                _ => None,
            },
            ExprKind::If {
                then_branch,
                else_branch,
                ..
            } => self.user_type_name_of_if_branches(then_branch, else_branch),
            ExprKind::Switch { arms, .. } => {
                let mut resolved_type_name = None;
                for arm in arms {
                    let (type_name, is_na) = self
                        .user_type_name_of_switch_arm_result_with_local_aliases(
                            &arm.result,
                            aliases,
                        );
                    merge_user_type_name(&mut resolved_type_name, type_name, is_na)?;
                }
                resolved_type_name
            }
            ExprKind::For { body, .. } => self.user_type_name_of_branch_return(body),
            ExprKind::ForIn { body, .. } => self.user_type_name_of_branch_return(body),
            ExprKind::While { body, .. } => self.user_type_name_of_branch_return(body),
            _ => None,
        }
    }

    fn user_type_name_of_switch_arm_result_with_local_aliases(
        &self,
        result: &SwitchArmResult,
        aliases: &HashMap<String, String>,
    ) -> (Option<String>, bool) {
        match result {
            SwitchArmResult::Expr(expr) => (
                self.user_type_name_of_expr_with_local_aliases(expr, aliases),
                is_na_expr(expr),
            ),
            SwitchArmResult::Block(statements) => {
                let Some((prefix, expr)) = branch_return_expr(statements) else {
                    return (None, false);
                };
                let aliases = self.local_user_type_aliases(prefix, aliases);
                (
                    self.user_type_name_of_expr_with_local_aliases(expr, &aliases),
                    is_na_expr(expr),
                )
            }
        }
    }

    pub(crate) fn user_type_name_of_udf_passthrough(
        &self,
        name: &str,
        args: &[CallArg],
    ) -> Option<String> {
        let function = self.functions.get(name)?;
        let param_index =
            returned_udf_param_index(&function.body, &function.params, &self.functions, 0)?;
        let arg_indices = resolve_udf_arg_indices(&function.params, args).ok()?;
        let arg_index = arg_indices
            .iter()
            .position(|mapped_param_index| *mapped_param_index == param_index)?;
        self.user_type_name_of_expr(&args[arg_index].value)
    }

    pub(crate) fn user_type_name_of_function_body(&self, body: &FunctionBody) -> Option<String> {
        match body {
            FunctionBody::Expr(expr) => self.user_type_name_of_expr(expr),
            FunctionBody::Block(statements) => {
                let last = statements.last()?;
                match &last.kind {
                    StmtKind::Expr(expr) => self.user_type_name_of_expr(expr),
                    StmtKind::If {
                        then_branch,
                        else_branch,
                        ..
                    } => self.user_type_name_of_if_branches(then_branch, else_branch),
                    StmtKind::For { body, .. } => self.user_type_name_of_branch_return(body),
                    StmtKind::ForIn { body, .. } => self.user_type_name_of_branch_return(body),
                    StmtKind::While { body, .. } => self.user_type_name_of_branch_return(body),
                    _ => None,
                }
            }
        }
    }

    pub(crate) fn mark_expr_user_type(&mut self, span: Span, type_name: String) {
        let identity = self.user_type_identity_for_name(&type_name);
        let key = self.expr_key(span);
        self.expr_user_types.insert(key, type_name);
        if let Some(identity) = identity {
            self.expr_user_type_identities.insert(key, identity);
        } else {
            self.expr_user_type_identities.remove(&key);
        }
    }

    #[allow(dead_code)]
    pub(crate) fn mark_expr_user_type_array(&mut self, span: Span, type_name: String) {
        let key = self.expr_key(span);
        self.expr_user_type_arrays.insert(key, type_name);
    }

    pub(crate) fn mark_symbol_user_type(&mut self, symbol: SymbolInfo, type_name: String) {
        self.mark_symbol_id_user_type(symbol.id, type_name);
    }

    pub(crate) fn mark_symbol_id_user_type(&mut self, symbol_id: SymbolId, type_name: String) {
        let identity = self.user_type_identity_for_name(&type_name);
        self.symbol_user_types.insert(symbol_id, type_name);
        if let Some(identity) = identity {
            self.symbol_user_type_identities.insert(symbol_id, identity);
        }
    }

    pub(crate) fn mark_symbol_user_type_array(&mut self, symbol: SymbolInfo, type_name: String) {
        self.symbol_user_type_arrays.insert(symbol.id, type_name);
    }

    fn user_type_identity_for_name(&self, type_name: &str) -> Option<UserTypeIdentity> {
        self.user_types
            .get(type_name)
            .map(|user_type| user_type.identity.clone())
            .or_else(|| {
                self.imported_user_types
                    .get(type_name)
                    .map(|user_type| UserTypeIdentity {
                        source_id: user_type.identity.source_id,
                        name: user_type.identity.name.clone(),
                    })
            })
    }

    fn user_type_name_of_field_access(&self, parts: &[String]) -> Option<String> {
        if parts.len() < 2 {
            return None;
        }
        let symbol = self.scope.resolve(&parts[0])?;
        let type_name = self.symbol_user_types.get(&symbol.id)?;
        self.user_type_field_path(type_name, symbol.pine_type.qualifier, &parts[1..])
            .and_then(|(_, user_type_name, _)| user_type_name)
    }

    fn type_of_user_type_field_path(
        &self,
        type_name: &str,
        qualifier: Qualifier,
        field_names: &[String],
    ) -> Option<PineType> {
        self.user_type_field_path(type_name, qualifier, field_names)
            .map(|(pine_type, _, _)| pine_type)
    }

    fn resolve_user_type_field_path(
        &mut self,
        type_name: &str,
        qualifier: Qualifier,
        field_names: &[String],
        span: Span,
    ) -> Option<(PineType, Option<String>, Vec<UdtFieldAccessStep>)> {
        let mut current_type_name = type_name.to_owned();
        for (field_index, field_name) in field_names.iter().enumerate() {
            let Some((_, field)) = self.user_type_field(&current_type_name, field_name) else {
                self.diagnostics.push(Diagnostic::error(
                    "E_UDT_UNKNOWN_FIELD",
                    format!("unknown field `{field_name}` on `{current_type_name}`"),
                    span,
                ));
                return None;
            };
            if field_index + 1 < field_names.len() {
                if field.pine_type.kind == ValueKind::ChartPoint
                    && field_index + 2 == field_names.len()
                {
                    let chart_point_type = PineType::new(qualifier, field.pine_type.kind);
                    let field_name = &field_names[field_index + 1];
                    if chart_point_field_type(chart_point_type, field_name).is_some() {
                        break;
                    }
                    self.diagnostics.push(Diagnostic::error(
                        "E_CHART_POINT_UNKNOWN_FIELD",
                        format!("unknown field `{field_name}` on `chart.point`"),
                        span,
                    ));
                    return None;
                }
                let Some(next_type_name) = &field.user_type_name else {
                    self.diagnostics.push(Diagnostic::error(
                        "E_UDT_UNKNOWN_FIELD",
                        format!(
                            "field `{field_name}` on `{current_type_name}` is not a user-defined type"
                        ),
                        span,
                    ));
                    return None;
                };
                current_type_name = next_type_name.clone();
            }
        }
        self.user_type_field_path(type_name, qualifier, field_names)
    }

    fn user_type_field_path(
        &self,
        type_name: &str,
        qualifier: Qualifier,
        field_names: &[String],
    ) -> Option<(PineType, Option<String>, Vec<UdtFieldAccessStep>)> {
        if let Some(path) = self.imported_user_type_field_path(type_name, qualifier, field_names) {
            return Some(path);
        }
        let mut current_type_name = type_name.to_owned();
        let mut final_type = None;
        let mut final_user_type_name = None;
        let mut fields = Vec::with_capacity(field_names.len());
        for (field_index, field_name) in field_names.iter().enumerate() {
            let (index, field) = self.user_type_field(&current_type_name, field_name)?;
            let pine_type = PineType::new(qualifier, field.pine_type.kind);
            final_type = Some(pine_type);
            final_user_type_name = field.user_type_name.clone();
            fields.push(UdtFieldAccessStep { index, pine_type });
            if field_index + 1 < field_names.len() {
                if field.pine_type.kind == ValueKind::ChartPoint
                    && field_index + 2 == field_names.len()
                {
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
                current_type_name = field.user_type_name.clone()?;
            }
        }
        Some((final_type?, final_user_type_name, fields))
    }

    pub(crate) fn user_type_field<'a>(
        &'a self,
        type_name: &str,
        field_name: &str,
    ) -> Option<(usize, &'a UserTypeFieldInfo)> {
        self.user_types
            .get(type_name)?
            .fields
            .iter()
            .enumerate()
            .find(|(_, field)| field.name == field_name)
    }

    fn user_type_field_type(
        &mut self,
        name: &str,
        span: Span,
    ) -> Option<(PineType, Option<String>)> {
        let kind = match name {
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
            other if self.user_types.contains_key(other) => {
                return Some((
                    PineType::new(Qualifier::Series, ValueKind::UserType),
                    Some(other.to_owned()),
                ));
            }
            _ => {
                self.diagnostics.push(Diagnostic::error(
                    "E_UDT_FIELD_TYPE",
                    format!("unsupported or unknown user-defined type field type `{name}`"),
                    span,
                ));
                return None;
            }
        };
        Some((PineType::new(Qualifier::Series, kind), None))
    }
}

#[cfg(test)]
#[path = "user_types/tests.rs"]
mod tests;
