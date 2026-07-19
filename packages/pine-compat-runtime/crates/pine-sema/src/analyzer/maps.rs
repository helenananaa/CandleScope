use crate::prelude::*;

#[derive(Debug, Clone, Copy)]
enum MapResultInfo {
    Known(MapTypeInfo),
    Na,
    Unknown,
}

impl Analyzer {
    pub(crate) fn map_type_of_expr(&self, expr: &Expr) -> Option<MapTypeInfo> {
        match &expr.kind {
            ExprKind::Identifier(name) => {
                if let Some(symbol) = self.bound_symbol(name, expr.span) {
                    if symbol.pine_type.kind != ValueKind::Map {
                        return None;
                    }
                    return self
                        .symbol_maps
                        .get(&symbol.id)
                        .copied()
                        .or_else(|| self.expr_maps.get(&self.expr_key(expr.span)).copied());
                }
                if let Some(symbol) = self.scope.resolve(name) {
                    return self.symbol_maps.get(&symbol.id).copied();
                }
            }
            ExprKind::QualifiedName(parts) if parts.len() == 1 => {
                if let Some(symbol) = self.bound_symbol(&parts[0], expr.span) {
                    if symbol.pine_type.kind != ValueKind::Map {
                        return None;
                    }
                    return self
                        .symbol_maps
                        .get(&symbol.id)
                        .copied()
                        .or_else(|| self.expr_maps.get(&self.expr_key(expr.span)).copied());
                }
                if let Some(symbol) = self.scope.resolve(&parts[0]) {
                    return self.symbol_maps.get(&symbol.id).copied();
                }
            }
            _ => {}
        }

        self.expr_maps.get(&self.expr_key(expr.span)).copied()
    }

    pub(crate) fn map_type_of_current_symbol(&self, name: &str) -> Option<MapTypeInfo> {
        self.scope
            .resolve(name)
            .and_then(|symbol| self.symbol_maps.get(&symbol.id).copied())
    }

    pub(crate) fn mark_expr_map(&mut self, span: Span, info: MapTypeInfo) {
        let key = self.expr_key(span);
        self.expr_maps.insert(key, info);
    }

    pub(crate) fn mark_symbol_map(&mut self, symbol: SymbolInfo, info: MapTypeInfo) {
        self.symbol_maps.insert(symbol.id, info);
    }

    pub(crate) fn mark_ternary_map(
        &mut self,
        span: Span,
        then_expr: &Expr,
        else_expr: &Expr,
    ) -> bool {
        let results = [
            self.map_result_info(then_expr),
            self.map_result_info(else_expr),
        ];
        self.mark_map_results(span, results)
    }

    pub(crate) fn mark_if_map(
        &mut self,
        span: Span,
        then_branch: &[Stmt],
        else_branch: &[Stmt],
    ) -> bool {
        let results = [
            self.map_branch_result_info(then_branch),
            self.map_branch_result_info(else_branch),
        ];
        self.mark_map_results(span, results)
    }

    pub(crate) fn mark_switch_map(&mut self, span: Span, arms: &[SwitchArm]) -> bool {
        let results: Vec<_> = arms
            .iter()
            .map(|arm| self.map_switch_arm_result_info(&arm.result))
            .collect();
        self.mark_map_results(span, results)
    }

    pub(crate) fn mark_loop_map(&mut self, span: Span, body: &[Stmt]) -> bool {
        let result = self.map_branch_result_info(body);
        self.mark_map_results(span, [result])
    }

    pub(crate) fn map_type_of_function_body(&self, body: &FunctionBody) -> Option<MapTypeInfo> {
        let result = match body {
            FunctionBody::Expr(expr) => self.map_result_info(expr),
            FunctionBody::Block(statements) => self.map_branch_result_info(statements),
        };
        match result {
            MapResultInfo::Known(info) => Some(info),
            MapResultInfo::Na | MapResultInfo::Unknown => None,
        }
    }

    pub(crate) fn validate_map_value_assignment(
        &mut self,
        name: &str,
        target_info: MapTypeInfo,
        value: &Expr,
        value_type: PineType,
        span: Span,
    ) {
        if value_type.kind == ValueKind::Na {
            return;
        }
        if self
            .map_type_of_expr(value)
            .is_some_and(|value_info| value_info == target_info)
        {
            return;
        }
        self.diagnostics.push(Diagnostic::error(
            "E_MAP_ASSIGN_TYPE",
            format!("cannot assign a different map template to `{name}`"),
            span,
        ));
    }

    fn mark_map_results(
        &mut self,
        span: Span,
        results: impl IntoIterator<Item = MapResultInfo>,
    ) -> bool {
        let MapResultInfo::Known(info) = Self::merge_map_results(results) else {
            return false;
        };
        self.mark_expr_map(span, info);
        true
    }

    fn merge_map_results(results: impl IntoIterator<Item = MapResultInfo>) -> MapResultInfo {
        let mut resolved = None;
        for result in results {
            match result {
                MapResultInfo::Known(info) if resolved.is_some_and(|resolved| resolved != info) => {
                    return MapResultInfo::Unknown;
                }
                MapResultInfo::Known(info) => {
                    resolved.get_or_insert(info);
                }
                MapResultInfo::Na => {}
                MapResultInfo::Unknown => return MapResultInfo::Unknown,
            }
        }
        resolved.map_or(MapResultInfo::Na, MapResultInfo::Known)
    }

    fn map_result_info(&self, expr: &Expr) -> MapResultInfo {
        if let Some(info) = self.map_type_of_expr(expr) {
            MapResultInfo::Known(info)
        } else if self.is_na_result_expr(expr) {
            MapResultInfo::Na
        } else {
            MapResultInfo::Unknown
        }
    }

    fn map_branch_result_info(&self, branch: &[Stmt]) -> MapResultInfo {
        let Some(last) = branch.last() else {
            return MapResultInfo::Unknown;
        };
        match &last.kind {
            StmtKind::Expr(expr) => self.map_result_info(expr),
            StmtKind::If {
                then_branch,
                else_branch,
                ..
            } => Self::merge_map_results([
                self.map_branch_result_info(then_branch),
                self.map_branch_result_info(else_branch),
            ]),
            StmtKind::For { body, .. }
            | StmtKind::ForIn { body, .. }
            | StmtKind::While { body, .. } => self.map_branch_result_info(body),
            _ => MapResultInfo::Unknown,
        }
    }

    fn map_switch_arm_result_info(&self, result: &SwitchArmResult) -> MapResultInfo {
        match result {
            SwitchArmResult::Expr(expr) => self.map_result_info(expr),
            SwitchArmResult::Block(statements) => self.map_branch_result_info(statements),
        }
    }

    fn is_na_result_expr(&self, expr: &Expr) -> bool {
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
            } => self.is_na_result_expr(then_expr) && self.is_na_result_expr(else_expr),
            ExprKind::If {
                then_branch,
                else_branch,
                ..
            } => self.is_na_branch_result(then_branch) && self.is_na_branch_result(else_branch),
            ExprKind::Switch { arms, .. } => {
                !arms.is_empty()
                    && arms
                        .iter()
                        .all(|arm| self.is_na_switch_arm_result(&arm.result))
            }
            ExprKind::For { body, .. }
            | ExprKind::ForIn { body, .. }
            | ExprKind::While { body, .. } => self.is_na_branch_result(body),
            ExprKind::History { expr, .. } => self.is_na_result_expr(expr),
            _ => self
                .expr_types
                .get(&self.expr_key(expr.span))
                .is_some_and(|pine_type| pine_type.kind == ValueKind::Na),
        }
    }

    fn is_na_branch_result(&self, branch: &[Stmt]) -> bool {
        let Some(last) = branch.last() else {
            return false;
        };
        match &last.kind {
            StmtKind::Expr(expr) => self.is_na_result_expr(expr),
            StmtKind::For { body, .. }
            | StmtKind::ForIn { body, .. }
            | StmtKind::While { body, .. } => self.is_na_branch_result(body),
            _ => false,
        }
    }

    fn is_na_switch_arm_result(&self, result: &SwitchArmResult) -> bool {
        match result {
            SwitchArmResult::Expr(expr) => self.is_na_result_expr(expr),
            SwitchArmResult::Block(statements) => self.is_na_branch_result(statements),
        }
    }
}

fn is_na_expr(expr: &Expr) -> bool {
    match &expr.kind {
        ExprKind::Identifier(name) => name == "na",
        ExprKind::QualifiedName(parts) if parts.len() == 1 => parts[0] == "na",
        _ => false,
    }
}

pub(crate) fn map_kind_from_template_name(name: &str) -> Option<ValueKind> {
    match name {
        "int" => Some(ValueKind::Int),
        "float" => Some(ValueKind::Float),
        "bool" => Some(ValueKind::Bool),
        "string" => Some(ValueKind::String),
        "color" => Some(ValueKind::Color),
        _ => None,
    }
}

pub(crate) fn accepts_map_scalar_kind(expected: ValueKind, actual: PineType) -> bool {
    let kind_matches = match expected {
        ValueKind::Float => matches!(
            actual.kind,
            ValueKind::Float | ValueKind::Int | ValueKind::Na
        ),
        ValueKind::Int => matches!(actual.kind, ValueKind::Int | ValueKind::Na),
        ValueKind::Bool => matches!(actual.kind, ValueKind::Bool | ValueKind::Na),
        ValueKind::String => matches!(actual.kind, ValueKind::String | ValueKind::Na),
        ValueKind::Color => matches!(actual.kind, ValueKind::Color | ValueKind::Na),
        _ => false,
    };
    kind_matches && qualifier_at_most(actual.qualifier, Qualifier::Series)
}

pub(crate) fn map_scalar_kind_accepts(expected: ValueKind) -> Option<pine_builtins::Accepts> {
    match expected {
        ValueKind::Float => Some(pine_builtins::Accepts::NumericCompatible),
        ValueKind::Int => Some(pine_builtins::Accepts::IntCompatible),
        ValueKind::Bool => Some(pine_builtins::Accepts::BoolCompatible),
        ValueKind::String => Some(pine_builtins::Accepts::StringCompatible),
        ValueKind::Color => Some(pine_builtins::Accepts::ColorCompatible),
        _ => None,
    }
}
