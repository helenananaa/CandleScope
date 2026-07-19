use crate::prelude::*;

const FOR_IN_SUPPORTED_ITERABLES_REASON: &str = "for...in currently supports statement iteration over scalar arrays, label arrays, line arrays, linefill arrays, polyline arrays, box arrays, table arrays, chart.point arrays, same-local or same-imported scalar-tree UDT arrays, matrix rows, and scalar maps with key-only or key/value loop variables; non-scalar-tree UDT arrays and other iterable families remain unsupported";

const FOR_IN_SUPPORTED_INDEX_VALUE_REASON: &str = "index/value for...in currently supports statement iteration over array<int>, array<float>, array<bool>, array<string>, array<color>, array<label>, array<line>, array<linefill>, array<polyline>, array<box>, array<table>, array<chart.point>, same-local or same-imported scalar-tree UDT arrays, matrix rows, and scalar maps where the first variable receives the key; other array element kinds and non-scalar-tree UDT arrays remain unsupported";

#[derive(Debug, Clone)]
struct ForInLoopKinds {
    index_kind: Option<ValueKind>,
    value_kind: ValueKind,
    user_type_name: Option<String>,
}

impl Analyzer {
    pub(super) fn analyze_for_in_stmt(
        &mut self,
        index: Option<&str>,
        value: &str,
        iterable: &Expr,
        body: &[Stmt],
        span: Span,
    ) {
        let iterable_type = self.analyze_expr(iterable);
        let Some(iterable_type) = iterable_type else {
            self.unsupported("for...in", FOR_IN_SUPPORTED_ITERABLES_REASON, span);
            return;
        };
        if index.is_some() && !supports_index_value_for_in(iterable_type.kind) {
            self.unsupported("for...in", FOR_IN_SUPPORTED_INDEX_VALUE_REASON, span);
            return;
        }
        let Some(kinds) = for_in_loop_kinds(iterable_type.kind, self, iterable, index.is_some())
        else {
            self.unsupported("for...in", FOR_IN_SUPPORTED_ITERABLES_REASON, span);
            return;
        };
        self.compatibility.supported.push(FeatureUse {
            feature: "for".to_owned(),
            span,
        });

        self.block_depth += 1;
        self.loop_depth += 1;
        self.assignment_qualifier_context
            .push(iterable_type.qualifier);
        self.scope.push_scope();
        if let Some(index) = index {
            let index_symbol = self.define_local_symbol(
                index,
                PineType::new(
                    Qualifier::Series,
                    kinds.index_kind.unwrap_or(ValueKind::Int),
                ),
                None,
                self.function_depth == 0,
            );
            self.bind_symbol(index, span, index_symbol);
            self.symbol_tuple_element_types.remove(&index_symbol.id);
            self.symbol_tuple_user_type_arrays.remove(&index_symbol.id);
        }
        let value_symbol = self.define_local_symbol(
            value,
            PineType::new(Qualifier::Series, kinds.value_kind),
            None,
            self.function_depth == 0,
        );
        self.bind_symbol(value, span, value_symbol);
        self.symbol_tuple_element_types.remove(&value_symbol.id);
        self.symbol_tuple_user_type_arrays.remove(&value_symbol.id);
        if let Some(type_name) = kinds.user_type_name {
            self.mark_symbol_id_user_type(value_symbol.id, type_name);
        }
        for body_statement in body {
            self.analyze_stmt(body_statement);
        }
        self.scope.pop_scope();
        self.assignment_qualifier_context.pop();
        self.loop_depth -= 1;
        self.block_depth -= 1;
    }
}

fn supports_index_value_for_in(iterable_kind: ValueKind) -> bool {
    matches!(
        iterable_kind,
        ValueKind::IntArray
            | ValueKind::FloatArray
            | ValueKind::BoolArray
            | ValueKind::StringArray
            | ValueKind::ColorArray
            | ValueKind::LabelArray
            | ValueKind::LineArray
            | ValueKind::LineFillArray
            | ValueKind::PolylineArray
            | ValueKind::BoxArray
            | ValueKind::TableArray
            | ValueKind::ChartPointArray
            | ValueKind::UserTypeArray
            | ValueKind::FloatMatrix
            | ValueKind::IntMatrix
            | ValueKind::BoolMatrix
            | ValueKind::StringMatrix
            | ValueKind::ColorMatrix
            | ValueKind::Map
    )
}

fn for_in_loop_kinds(
    iterable_kind: ValueKind,
    analyzer: &Analyzer,
    iterable: &Expr,
    has_index: bool,
) -> Option<ForInLoopKinds> {
    let scalar = |value_kind| {
        Some(ForInLoopKinds {
            index_kind: has_index.then_some(ValueKind::Int),
            value_kind,
            user_type_name: None,
        })
    };
    match iterable_kind {
        ValueKind::IntArray => scalar(ValueKind::Int),
        ValueKind::FloatArray => scalar(ValueKind::Float),
        ValueKind::BoolArray => scalar(ValueKind::Bool),
        ValueKind::StringArray => scalar(ValueKind::String),
        ValueKind::ColorArray => scalar(ValueKind::Color),
        ValueKind::LabelArray => scalar(ValueKind::Label),
        ValueKind::LineArray => scalar(ValueKind::Line),
        ValueKind::LineFillArray => scalar(ValueKind::LineFill),
        ValueKind::PolylineArray => scalar(ValueKind::Polyline),
        ValueKind::BoxArray => scalar(ValueKind::Box),
        ValueKind::TableArray => scalar(ValueKind::Table),
        ValueKind::ChartPointArray => scalar(ValueKind::ChartPoint),
        ValueKind::FloatMatrix => scalar(ValueKind::FloatArray),
        ValueKind::IntMatrix => scalar(ValueKind::IntArray),
        ValueKind::BoolMatrix => scalar(ValueKind::BoolArray),
        ValueKind::StringMatrix => scalar(ValueKind::StringArray),
        ValueKind::ColorMatrix => scalar(ValueKind::ColorArray),
        ValueKind::Map => {
            let info = analyzer.map_type_of_expr(iterable)?;
            Some(ForInLoopKinds {
                index_kind: has_index.then_some(info.key_kind),
                value_kind: if has_index {
                    info.value_kind
                } else {
                    info.key_kind
                },
                user_type_name: None,
            })
        }
        ValueKind::UserTypeArray => {
            analyzer
                .user_type_array_name_of_expr(iterable)
                .map(|type_name| ForInLoopKinds {
                    index_kind: has_index.then_some(ValueKind::Int),
                    value_kind: ValueKind::UserType,
                    user_type_name: Some(type_name),
                })
        }
        _ => None,
    }
}
