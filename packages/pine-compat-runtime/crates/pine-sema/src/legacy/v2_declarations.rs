use std::collections::{BTreeSet, HashMap, HashSet};

use crate::prelude::*;

const MAX_LEGACY_DECLARATION_NODES: usize = 256;
const MAX_LEGACY_DECLARATION_EDGES: usize = 4_096;

#[derive(Debug, Default)]
pub(crate) struct LegacyV2DeclarationPlan {
    lowering_order: Vec<usize>,
}

impl LegacyV2DeclarationPlan {
    pub(crate) fn lowering_order<'a>(&self, statements: &'a [Stmt]) -> Vec<&'a Stmt> {
        if self.lowering_order.len() == statements.len() {
            self.lowering_order
                .iter()
                .map(|index| &statements[*index])
                .collect()
        } else {
            statements.iter().collect()
        }
    }
}

#[derive(Debug)]
struct Candidate<'a> {
    statement_index: usize,
    name: &'a str,
    value: &'a Expr,
    span: Span,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum DependencyKind {
    Current,
    Historical,
}

#[derive(Debug, Clone, Copy)]
struct Dependency {
    target: usize,
    kind: DependencyKind,
    span: Span,
}

#[derive(Debug, Clone)]
struct UnsafeInitializer {
    reason: String,
    span: Span,
}

impl Analyzer {
    pub(crate) fn prepare_legacy_v2_declarations(&mut self, program: &Program) -> bool {
        if !matches!(
            self.legacy.dialect(),
            crate::PineDialect::V1 | crate::PineDialect::V2
        ) {
            return false;
        }

        let candidates = collect_candidates(program);
        if candidates.is_empty() {
            return false;
        }

        let mut names = HashMap::new();
        for (index, candidate) in candidates.iter().enumerate() {
            if let Some(previous) = names.insert(candidate.name, index) {
                self.diagnostics.push(Diagnostic::error(
                    "E_LEGACY_REFERENCE_GRAPH",
                    format!(
                        "legacy declaration graph cannot contain duplicate global declaration `{}`",
                        candidate.name
                    ),
                    candidates[previous].span.merge(candidate.span),
                ));
                return true;
            }
        }

        let mut dependencies = Vec::with_capacity(candidates.len());
        let mut unsafe_initializers = Vec::with_capacity(candidates.len());
        for candidate in &candidates {
            let mut candidate_dependencies = Vec::new();
            let mut unsafe_initializer = None;
            collect_expr_dependencies(
                candidate.value,
                &names,
                false,
                &self.functions,
                &mut candidate_dependencies,
                &mut unsafe_initializer,
            );
            candidate_dependencies.sort_by_key(|dependency| {
                (
                    dependency.target,
                    dependency.span.start,
                    dependency.span.end,
                )
            });
            candidate_dependencies.dedup_by_key(|dependency| {
                (
                    dependency.target,
                    dependency.kind,
                    dependency.span.start,
                    dependency.span.end,
                )
            });
            dependencies.push(candidate_dependencies);
            unsafe_initializers.push(unsafe_initializer);
        }

        let mut active = HashSet::new();
        for (source, source_dependencies) in dependencies.iter().enumerate() {
            for dependency in source_dependencies {
                if dependency.target >= source {
                    active.insert(source);
                    active.insert(dependency.target);
                }
            }
        }
        if active.is_empty() {
            return false;
        }

        let mut changed = true;
        while changed {
            changed = false;
            let sources = active.iter().copied().collect::<Vec<_>>();
            for source in sources {
                for dependency in &dependencies[source] {
                    changed |= active.insert(dependency.target);
                }
            }
        }

        let edge_count = active
            .iter()
            .map(|source| dependencies[*source].len())
            .sum::<usize>();
        if active.len() > MAX_LEGACY_DECLARATION_NODES || edge_count > MAX_LEGACY_DECLARATION_EDGES
        {
            let span = active
                .iter()
                .map(|index| candidates[*index].span)
                .reduce(Span::merge)
                .unwrap_or_default();
            self.diagnostics.push(Diagnostic::error(
                "E_LEGACY_REFERENCE_GRAPH_LIMIT",
                format!(
                    "legacy declaration graph exceeds the supported limit of {MAX_LEGACY_DECLARATION_NODES} nodes or {MAX_LEGACY_DECLARATION_EDGES} edges"
                ),
                span,
            ));
            return true;
        }

        let graph_diagnostic_count = self.diagnostics.len();
        let mut active_indices = active.iter().copied().collect::<Vec<_>>();
        active_indices.sort_unstable();
        for index in &active_indices {
            if let Some(unsafe_initializer) = &unsafe_initializers[*index] {
                self.diagnostics.push(Diagnostic::error(
                    "E_LEGACY_REFERENCE_GRAPH_UNSAFE",
                    format!(
                        "legacy declaration `{}` is not eligible for graph resolution: {}",
                        candidates[*index].name, unsafe_initializer.reason
                    ),
                    unsafe_initializer.span,
                ));
            }
        }
        if self.diagnostics.len() > graph_diagnostic_count {
            return true;
        }

        let Some(lowering_order) = build_lowering_order(
            program,
            &candidates,
            &dependencies,
            &active,
            &mut self.diagnostics,
        ) else {
            return true;
        };

        let mut inferred = active_indices
            .iter()
            .map(|index| (candidates[*index].name.to_owned(), UNKNOWN))
            .collect::<HashMap<_, _>>();
        for _ in 0..=active.len() {
            let mut type_changed = false;
            for index in &active_indices {
                let candidate = &candidates[*index];
                let Some(mut pine_type) =
                    self.legacy_graph_type_of_expr(candidate.value, &inferred)
                else {
                    continue;
                };
                if !is_legacy_graph_scalar(pine_type.kind) {
                    continue;
                }
                if dependencies.iter().any(|source_dependencies| {
                    source_dependencies.iter().any(|dependency| {
                        dependency.target == *index && dependency.kind == DependencyKind::Historical
                    })
                }) {
                    pine_type = PineType::new(Qualifier::Series, pine_type.kind);
                }
                let entry = inferred
                    .get_mut(candidate.name)
                    .expect("active legacy declaration has an inference slot");
                if *entry != pine_type {
                    *entry = pine_type;
                    type_changed = true;
                }
            }
            if !type_changed {
                break;
            }
        }

        for index in &active_indices {
            let candidate = &candidates[*index];
            let pine_type = inferred[candidate.name];
            if !is_legacy_graph_scalar(pine_type.kind) {
                self.diagnostics.push(Diagnostic::error(
                    "E_LEGACY_REFERENCE_TYPE",
                    format!(
                        "legacy declaration graph could not infer one stable scalar type for `{}`",
                        candidate.name
                    ),
                    candidate.span,
                ));
            }
        }
        if self.diagnostics.len() > graph_diagnostic_count {
            return true;
        }

        for index in &active_indices {
            let candidate = &candidates[*index];
            let symbol = self.define_symbol(candidate.name, inferred[candidate.name], None);
            self.legacy_v2_predeclared_symbols.insert(symbol.id);
        }

        let version = self.legacy.dialect().version();
        for (source, source_dependencies) in dependencies.iter().enumerate() {
            if !active.contains(&source) {
                continue;
            }
            for dependency in source_dependencies {
                if dependency.target == source && dependency.kind == DependencyKind::Historical {
                    self.compatibility.legacy_emulations.push(
                        crate::compatibility::LegacyEmulation {
                            feature: format!("v{version}.self_reference"),
                            behavior: "legacy self-history declaration is predeclared as one canonical series symbol and recomputed once per bar".to_owned(),
                            span: dependency.span,
                        },
                    );
                } else if dependency.target > source {
                    self.compatibility.legacy_emulations.push(
                        crate::compatibility::LegacyEmulation {
                            feature: format!("v{version}.forward_reference"),
                            behavior: match dependency.kind {
                                DependencyKind::Current => "legacy current-bar forward dependency is resolved by a bounded stable topological declaration order",
                                DependencyKind::Historical => "legacy historical forward dependency is bound before analysis without changing current-bar declaration order",
                            }
                            .to_owned(),
                            span: dependency.span,
                        },
                    );
                }
            }
        }

        self.legacy_v2_declaration_plan = LegacyV2DeclarationPlan { lowering_order };
        false
    }

    fn legacy_graph_type_of_expr(
        &self,
        expr: &Expr,
        inferred: &HashMap<String, PineType>,
    ) -> Option<PineType> {
        match &expr.kind {
            ExprKind::Unary { op, expr } => {
                let operand = self.legacy_graph_type_of_expr(expr, inferred)?;
                let kind = match op {
                    UnaryOp::Not => ValueKind::Bool,
                    UnaryOp::Plus | UnaryOp::Minus if operand.kind == ValueKind::Bool => {
                        ValueKind::Float
                    }
                    UnaryOp::Plus | UnaryOp::Minus => operand.kind,
                };
                Some(PineType::new(operand.qualifier, kind))
            }
            ExprKind::Binary { op, left, right } => {
                let left = self.legacy_graph_type_of_expr(left, inferred)?;
                let right = self.legacy_graph_type_of_expr(right, inferred)?;
                let qualifier = strongest_qualifier(left.qualifier, right.qualifier);
                let kind = match op {
                    BinaryOp::Add
                        if left.kind == ValueKind::String && right.kind == ValueKind::String =>
                    {
                        ValueKind::String
                    }
                    BinaryOp::Add
                    | BinaryOp::Sub
                    | BinaryOp::Mul
                    | BinaryOp::Div
                    | BinaryOp::Mod
                        if left.kind == ValueKind::Bool || right.kind == ValueKind::Bool =>
                    {
                        ValueKind::Float
                    }
                    BinaryOp::Add
                    | BinaryOp::Sub
                    | BinaryOp::Mul
                    | BinaryOp::Div
                    | BinaryOp::Mod => {
                        if !matches!(left.kind, ValueKind::Int | ValueKind::Float | ValueKind::Na)
                            || !matches!(
                                right.kind,
                                ValueKind::Int | ValueKind::Float | ValueKind::Na
                            )
                        {
                            return None;
                        }
                        numeric_result_kind(*op, left.kind, right.kind)
                    }
                    BinaryOp::Eq
                    | BinaryOp::NotEq
                    | BinaryOp::Gt
                    | BinaryOp::Gte
                    | BinaryOp::Lt
                    | BinaryOp::Lte
                    | BinaryOp::And
                    | BinaryOp::Or => ValueKind::Bool,
                };
                Some(PineType::new(qualifier, kind))
            }
            ExprKind::Ternary {
                condition,
                then_expr,
                else_expr,
            } => {
                let condition = self.legacy_graph_type_of_expr(condition, inferred)?;
                let then_type = self.legacy_graph_type_of_expr(then_expr, inferred)?;
                let else_type = self.legacy_graph_type_of_expr(else_expr, inferred)?;
                Some(PineType::new(
                    strongest_qualifier(
                        condition.qualifier,
                        strongest_qualifier(then_type.qualifier, else_type.qualifier),
                    ),
                    common_kind(then_type.kind, else_type.kind)?,
                ))
            }
            ExprKind::History { expr, .. } => self
                .legacy_graph_type_of_expr(expr, inferred)
                .map(|pine_type| PineType::new(Qualifier::Series, pine_type.kind)),
            _ => self.type_of_expr_with_params(expr, inferred),
        }
    }
}

fn collect_candidates(program: &Program) -> Vec<Candidate<'_>> {
    program
        .statements
        .iter()
        .enumerate()
        .filter_map(|(statement_index, statement)| {
            let StmtKind::Decl {
                mode: pine_syntax::DeclMode::Normal,
                declared_type: None,
                name,
                value,
            } = &statement.kind
            else {
                return None;
            };
            Some(Candidate {
                statement_index,
                name,
                value,
                span: statement.span,
            })
        })
        .collect()
}

fn collect_expr_dependencies(
    expr: &Expr,
    names: &HashMap<&str, usize>,
    historical: bool,
    functions: &HashMap<String, FunctionInfo>,
    dependencies: &mut Vec<Dependency>,
    unsafe_initializer: &mut Option<UnsafeInitializer>,
) {
    match &expr.kind {
        ExprKind::Identifier(name) => {
            if let Some(target) = names.get(name.as_str()) {
                dependencies.push(Dependency {
                    target: *target,
                    kind: if historical {
                        DependencyKind::Historical
                    } else {
                        DependencyKind::Current
                    },
                    span: expr.span,
                });
            }
        }
        ExprKind::QualifiedName(parts) => {
            if parts
                .first()
                .is_some_and(|part| names.contains_key(part.as_str()))
            {
                record_unsafe(
                    unsafe_initializer,
                    "qualified accesses on graph declarations are outside the scalar subset",
                    expr.span,
                );
            }
        }
        ExprKind::Unary { expr, .. } => collect_expr_dependencies(
            expr,
            names,
            historical,
            functions,
            dependencies,
            unsafe_initializer,
        ),
        ExprKind::Binary { left, right, .. } => {
            collect_expr_dependencies(
                left,
                names,
                historical,
                functions,
                dependencies,
                unsafe_initializer,
            );
            collect_expr_dependencies(
                right,
                names,
                historical,
                functions,
                dependencies,
                unsafe_initializer,
            );
        }
        ExprKind::Ternary {
            condition,
            then_expr,
            else_expr,
        } => {
            for child in [condition.as_ref(), then_expr.as_ref(), else_expr.as_ref()] {
                collect_expr_dependencies(
                    child,
                    names,
                    historical,
                    functions,
                    dependencies,
                    unsafe_initializer,
                );
            }
        }
        ExprKind::Call { callee, args } => {
            let name = expr_name(callee).unwrap_or_default();
            if functions.contains_key(&name) {
                record_unsafe(
                    unsafe_initializer,
                    "user-defined function calls are outside the first declaration-graph subset",
                    callee.span,
                );
            } else if is_output_or_declaration_builtin(&name)
                || is_array_mutation_builtin(&name)
                || is_map_mutation_builtin(&name)
                || is_array_mutation_method_call_name(&name)
                || is_map_mutation_method_call_name(&name)
                || name == "security"
                || name.starts_with("request.")
                || name == "runtime.error"
            {
                record_unsafe(
                    unsafe_initializer,
                    "side effects, inputs, outputs, requests, and mutations cannot participate in declaration-graph reordering",
                    callee.span,
                );
            }
            for arg in args {
                collect_expr_dependencies(
                    &arg.value,
                    names,
                    historical,
                    functions,
                    dependencies,
                    unsafe_initializer,
                );
            }
        }
        ExprKind::History { expr, offset } => {
            let is_positive_constant =
                crate::types::const_int_value(offset).is_some_and(|value| value > 0);
            collect_expr_dependencies(
                expr,
                names,
                historical || is_positive_constant,
                functions,
                dependencies,
                unsafe_initializer,
            );
            collect_expr_dependencies(
                offset,
                names,
                false,
                functions,
                dependencies,
                unsafe_initializer,
            );
        }
        ExprKind::Literal(_) => {}
        ExprKind::If { .. }
        | ExprKind::For { .. }
        | ExprKind::ForIn { .. }
        | ExprKind::While { .. }
        | ExprKind::Switch { .. }
        | ExprKind::Tuple(_) => record_unsafe(
            unsafe_initializer,
            "control-flow, loop, switch, and tuple initializers are outside the first declaration-graph subset",
            expr.span,
        ),
    }
}

fn record_unsafe(target: &mut Option<UnsafeInitializer>, reason: &str, span: Span) {
    if target.is_none() {
        *target = Some(UnsafeInitializer {
            reason: reason.to_owned(),
            span,
        });
    }
}

fn build_lowering_order(
    program: &Program,
    candidates: &[Candidate<'_>],
    dependencies: &[Vec<Dependency>],
    active: &HashSet<usize>,
    diagnostics: &mut Vec<Diagnostic>,
) -> Option<Vec<usize>> {
    let mut order = (0..program.statements.len()).collect::<Vec<_>>();
    let candidate_by_statement = candidates
        .iter()
        .enumerate()
        .map(|(index, candidate)| (candidate.statement_index, index))
        .collect::<HashMap<_, _>>();

    for (source, source_dependencies) in dependencies.iter().enumerate() {
        if !active.contains(&source) {
            continue;
        }
        for dependency in source_dependencies {
            if dependency.kind != DependencyKind::Current || dependency.target <= source {
                continue;
            }
            let source_statement = candidates[source].statement_index;
            let target_statement = candidates[dependency.target].statement_index;
            let same_segment = (source_statement..=target_statement)
                .all(|statement| candidate_by_statement.contains_key(&statement));
            if !same_segment {
                diagnostics.push(Diagnostic::error(
                    "E_LEGACY_FORWARD_REFERENCE_UNSAFE",
                    "legacy current-bar forward references cannot cross a non-declaration statement or side-effect barrier",
                    dependency.span,
                ));
            }
        }
    }
    if diagnostics
        .iter()
        .any(|diagnostic| diagnostic.severity == Severity::Error)
    {
        return None;
    }

    let mut cursor = 0usize;
    while cursor < program.statements.len() {
        if !candidate_by_statement.contains_key(&cursor) {
            cursor += 1;
            continue;
        }
        let start = cursor;
        while cursor < program.statements.len() && candidate_by_statement.contains_key(&cursor) {
            cursor += 1;
        }
        let end = cursor;
        let nodes = (start..end)
            .map(|statement| candidate_by_statement[&statement])
            .collect::<Vec<_>>();
        let node_set = nodes.iter().copied().collect::<HashSet<_>>();
        let mut outgoing = HashMap::<usize, Vec<usize>>::new();
        let mut indegree = nodes
            .iter()
            .copied()
            .map(|node| (node, 0usize))
            .collect::<HashMap<_, _>>();
        for source in &nodes {
            for dependency in &dependencies[*source] {
                if dependency.kind == DependencyKind::Current
                    && node_set.contains(&dependency.target)
                {
                    outgoing.entry(dependency.target).or_default().push(*source);
                    *indegree
                        .get_mut(source)
                        .expect("segment source has an indegree slot") += 1;
                }
            }
        }
        let mut ready = indegree
            .iter()
            .filter_map(|(node, degree)| (*degree == 0).then_some(*node))
            .collect::<BTreeSet<_>>();
        let mut sorted = Vec::with_capacity(nodes.len());
        while let Some(node) = ready.pop_first() {
            sorted.push(node);
            if let Some(consumers) = outgoing.get(&node) {
                for consumer in consumers {
                    let degree = indegree
                        .get_mut(consumer)
                        .expect("segment consumer has an indegree slot");
                    *degree -= 1;
                    if *degree == 0 {
                        ready.insert(*consumer);
                    }
                }
            }
        }
        if sorted.len() != nodes.len() {
            let cycle_span = nodes
                .iter()
                .filter(|node| indegree[node] > 0)
                .map(|node| candidates[*node].span)
                .reduce(Span::merge)
                .unwrap_or_default();
            diagnostics.push(Diagnostic::error(
                "E_LEGACY_REFERENCE_CYCLE",
                "legacy declaration graph contains a same-bar reference cycle; only acyclic current dependencies and history-only cycles are supported",
                cycle_span,
            ));
            return None;
        }
        for (slot, node) in (start..end).zip(sorted) {
            order[slot] = candidates[node].statement_index;
        }
    }

    Some(order)
}

fn is_legacy_graph_scalar(kind: ValueKind) -> bool {
    matches!(
        kind,
        ValueKind::Int | ValueKind::Float | ValueKind::Bool | ValueKind::String | ValueKind::Color
    )
}
