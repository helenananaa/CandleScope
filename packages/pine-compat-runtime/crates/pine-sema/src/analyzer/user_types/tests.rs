use super::*;
use crate::analyzer::context::{MapTypeInfo, SourcedExpr};
use crate::modules::{ImportedUserTypeFieldInfo, ImportedUserTypeIdentity, ImportedUserTypeInfo};
use crate::source_graph::SourceContextId;
use pine_syntax::{BinaryOp, FunctionBody, Literal};
use std::cell::Cell;
use std::collections::HashSet;

fn field(name: &str, kind: ValueKind, user_type_name: Option<&str>) -> UserTypeFieldInfo {
    UserTypeFieldInfo {
        name: name.to_owned(),
        pine_type: PineType::new(Qualifier::Series, kind),
        user_type_name: user_type_name.map(str::to_owned),
    }
}

fn scalar_type(name: &str) -> UserTypeInfo {
    UserTypeInfo {
        identity: UserTypeIdentity {
            source_id: SourceId::root(),
            name: name.to_owned(),
        },
        name: name.to_owned(),
        fields: vec![
            field("x", ValueKind::Float, None),
            field("label", ValueKind::String, None),
            field("active", ValueKind::Bool, None),
            field("shade", ValueKind::Color, None),
        ],
    }
}

fn imported_type(
    source_id: SourceId,
    name: &str,
    fields: Vec<ImportedUserTypeFieldInfo>,
) -> ImportedUserTypeInfo {
    ImportedUserTypeInfo {
        identity: ImportedUserTypeIdentity {
            source_id,
            name: name.to_owned(),
        },
        fields,
        span: Span::new(100, 140),
    }
}

fn imported_field(
    name: &str,
    type_name: &str,
    pine_type: Option<PineType>,
) -> ImportedUserTypeFieldInfo {
    ImportedUserTypeFieldInfo {
        name: name.to_owned(),
        type_name: type_name.to_owned(),
        pine_type,
        span: Span::new(120, 130),
    }
}

fn analyzer() -> Analyzer {
    use crate::compatibility::CompatibilityReport;
    use crate::resolver::ScopeResolver;
    use crate::symbols::{
        initial_series_count, initial_symbol_count, initial_symbol_order, initial_symbols,
    };

    Analyzer {
        diagnostics: Vec::new(),
        compatibility: CompatibilityReport::default(),
        source_context_id: Cell::new(SourceContextId::root()),
        source_context_depth: Cell::new(0),
        scope: ScopeResolver::new(initial_symbols(), initial_symbol_order()),
        bindings: HashMap::new(),
        lower_symbol_overrides: Vec::new(),
        lower_reassigned_symbols: HashSet::new(),
        functions: HashMap::new(),
        methods: HashMap::new(),
        imported_user_types: HashMap::new(),
        user_types: HashMap::new(),
        symbol_user_types: HashMap::new(),
        symbol_user_type_identities: HashMap::new(),
        symbol_init_exprs: HashMap::new(),
        typed_na_scalar_symbols: HashSet::new(),
        non_scalar_udt_varip_symbols: HashSet::new(),
        symbol_user_type_arrays: HashMap::new(),
        symbol_tuple_element_types: HashMap::new(),
        symbol_tuple_user_type_arrays: HashMap::new(),
        symbol_maps: HashMap::new(),
        const_int_symbols: HashMap::new(),
        const_numeric_symbols: HashMap::new(),
        const_string_symbols: HashMap::new(),
        const_bool_symbols: HashMap::new(),
        const_color_symbols: HashMap::new(),
        expr_user_types: HashMap::new(),
        expr_user_type_identities: HashMap::new(),
        expr_user_type_arrays: HashMap::new(),
        expr_maps: HashMap::new(),
        user_method_call_results: HashSet::new(),
        expr_types: HashMap::new(),
        pure_expr_series_ids: HashMap::new(),
        script_declaration: None,
        strategy_settings: Default::default(),
        drawing_settings: Default::default(),
        function_stack: Vec::new(),
        function_param_symbols: Vec::new(),
        function_param_const_switch_keys: Vec::new(),
        function_context_is_method: Vec::new(),
        function_tuple_identity_slots: Vec::new(),
        next_symbol_id: initial_symbol_count(),
        next_series_id: initial_series_count(),
        next_call_site_id: 0,
        next_var_slot_id: 0,
        block_depth: 0,
        function_depth: 0,
        loop_depth: 0,
        expr_depth: 0,
        assignment_qualifier_context: Vec::new(),
        lowering_limits: Default::default(),
        lowering_inline_depth: 0,
        lowered_hir_nodes: 0,
        lowered_temp_symbols: 0,
        lowering_budget_reported: false,
    }
}

fn identifier(name: &str, span: Span) -> Expr {
    Expr {
        kind: ExprKind::Identifier(name.to_owned()),
        span,
    }
}

fn int_literal(value: i64, span: Span) -> Expr {
    Expr {
        kind: ExprKind::Literal(Literal::Int(value)),
        span,
    }
}

fn expr_stmt(expr: Expr) -> Stmt {
    Stmt {
        span: expr.span,
        kind: StmtKind::Expr(expr),
    }
}

fn binary_expr(op: BinaryOp, left: Expr, right: Expr, span: Span) -> Expr {
    Expr {
        kind: ExprKind::Binary {
            op,
            left: Box::new(left),
            right: Box::new(right),
        },
        span,
    }
}

fn if_stmt(condition: Expr, then_branch: Vec<Stmt>, else_branch: Vec<Stmt>, span: Span) -> Stmt {
    Stmt {
        kind: StmtKind::If {
            condition,
            then_branch,
            else_branch,
        },
        span,
    }
}

fn for_stmt(
    counter: &str,
    from: Expr,
    to: Expr,
    step: Option<Expr>,
    body: Vec<Stmt>,
    span: Span,
) -> Stmt {
    Stmt {
        kind: StmtKind::For {
            counter: counter.to_owned(),
            from,
            to,
            step,
            body,
        },
        span,
    }
}

fn qualified_name(name: &str, span: Span) -> Expr {
    Expr {
        kind: ExprKind::QualifiedName(vec![name.to_owned()]),
        span,
    }
}

fn call_arg(name: Option<&str>, value_name: &str) -> CallArg {
    CallArg {
        name: name.map(str::to_owned),
        value: identifier(value_name, Span::new(1, 2)),
        span: Span::new(1, 2),
    }
}

#[test]
fn type_query_promotes_loop_expression_results_by_loop_qualifiers() {
    let analyzer = analyzer();
    let mut param_types = HashMap::new();
    param_types.insert(
        "length".to_owned(),
        PineType::new(Qualifier::Input, ValueKind::Int),
    );

    let for_expr = Expr {
        kind: ExprKind::For {
            counter: "i".to_owned(),
            from: Box::new(int_literal(0, Span::new(1, 2))),
            to: Box::new(identifier("bar_index", Span::new(3, 12))),
            step: None,
            body: vec![expr_stmt(identifier("length", Span::new(13, 19)))],
        },
        span: Span::new(1, 19),
    };
    assert_eq!(
        analyzer.type_of_expr_with_params(&for_expr, &param_types),
        Some(PineType::new(Qualifier::Series, ValueKind::Int))
    );

    let while_expr = Expr {
        kind: ExprKind::While {
            condition: Box::new(binary_expr(
                BinaryOp::Gt,
                identifier("close", Span::new(20, 25)),
                identifier("open", Span::new(28, 32)),
                Span::new(20, 32),
            )),
            body: vec![expr_stmt(identifier("length", Span::new(33, 39)))],
        },
        span: Span::new(20, 39),
    };
    assert_eq!(
        analyzer.type_of_expr_with_params(&while_expr, &param_types),
        Some(PineType::new(Qualifier::Series, ValueKind::Int))
    );

    param_types.insert(
        "values".to_owned(),
        PineType::new(Qualifier::Series, ValueKind::IntArray),
    );
    let for_in_expr = Expr {
        kind: ExprKind::ForIn {
            index: None,
            value: "value".to_owned(),
            iterable: Box::new(identifier("values", Span::new(40, 46))),
            body: vec![expr_stmt(identifier("length", Span::new(47, 53)))],
        },
        span: Span::new(40, 53),
    };
    assert_eq!(
        analyzer.type_of_expr_with_params(&for_in_expr, &param_types),
        Some(PineType::new(Qualifier::Series, ValueKind::Int))
    );
}

#[test]
fn type_query_supports_function_block_final_if_and_for_returns() {
    let analyzer = analyzer();
    let mut param_types = HashMap::new();
    param_types.insert(
        "flag".to_owned(),
        PineType::new(Qualifier::Input, ValueKind::Bool),
    );
    param_types.insert(
        "length".to_owned(),
        PineType::new(Qualifier::Input, ValueKind::Int),
    );
    param_types.insert(
        "values".to_owned(),
        PineType::new(Qualifier::Series, ValueKind::IntArray),
    );

    let final_if_body = FunctionBody::Block(vec![if_stmt(
        identifier("flag", Span::new(1, 5)),
        vec![expr_stmt(identifier("length", Span::new(6, 12)))],
        vec![expr_stmt(identifier("length", Span::new(13, 19)))],
        Span::new(1, 19),
    )]);
    assert_eq!(
        analyzer.type_of_function_body_with_params(&final_if_body, &param_types),
        Some(PineType::new(Qualifier::Input, ValueKind::Int))
    );

    let final_for_body = FunctionBody::Block(vec![for_stmt(
        "i",
        int_literal(0, Span::new(20, 21)),
        identifier("bar_index", Span::new(24, 33)),
        None,
        vec![expr_stmt(identifier("length", Span::new(34, 40)))],
        Span::new(20, 40),
    )]);
    assert_eq!(
        analyzer.type_of_function_body_with_params(&final_for_body, &param_types),
        Some(PineType::new(Qualifier::Series, ValueKind::Int))
    );

    let final_for_in_body = FunctionBody::Block(vec![Stmt {
        kind: StmtKind::ForIn {
            index: None,
            value: "value".to_owned(),
            iterable: identifier("values", Span::new(41, 47)),
            body: vec![expr_stmt(identifier("length", Span::new(48, 54)))],
        },
        span: Span::new(41, 54),
    }]);
    assert_eq!(
        analyzer.type_of_function_body_with_params(&final_for_in_body, &param_types),
        Some(PineType::new(Qualifier::Series, ValueKind::Int))
    );

    let final_while_body = FunctionBody::Block(vec![Stmt {
        kind: StmtKind::While {
            condition: binary_expr(
                BinaryOp::Gt,
                identifier("close", Span::new(55, 60)),
                identifier("open", Span::new(63, 67)),
                Span::new(55, 67),
            ),
            body: vec![expr_stmt(identifier("length", Span::new(68, 74)))],
        },
        span: Span::new(55, 74),
    }]);
    assert_eq!(
        analyzer.type_of_function_body_with_params(&final_while_body, &param_types),
        Some(PineType::new(Qualifier::Series, ValueKind::Int))
    );

    let final_if_loop_body = FunctionBody::Block(vec![if_stmt(
        identifier("flag", Span::new(75, 79)),
        vec![for_stmt(
            "i",
            int_literal(0, Span::new(80, 81)),
            identifier("bar_index", Span::new(84, 93)),
            None,
            vec![expr_stmt(identifier("length", Span::new(94, 100)))],
            Span::new(80, 100),
        )],
        vec![Stmt {
            kind: StmtKind::While {
                condition: binary_expr(
                    BinaryOp::Gt,
                    identifier("close", Span::new(101, 106)),
                    identifier("open", Span::new(109, 113)),
                    Span::new(101, 113),
                ),
                body: vec![expr_stmt(identifier("length", Span::new(114, 120)))],
            },
            span: Span::new(101, 120),
        }],
        Span::new(75, 120),
    )]);
    assert_eq!(
        analyzer.type_of_function_body_with_params(&final_if_loop_body, &param_types),
        Some(PineType::new(Qualifier::Series, ValueKind::Int))
    );
}

#[test]
fn resolves_imported_user_type_constructor_metadata_without_accepting_it() {
    let mut analyzer = analyzer();
    analyzer.imported_user_types.insert(
        "lib.Point".to_owned(),
        imported_type(
            SourceId::library(0),
            "Point",
            vec![imported_field(
                "x",
                "float",
                Some(PineType::new(Qualifier::Series, ValueKind::Float)),
            )],
        ),
    );

    let point = analyzer
        .imported_user_type_constructor_metadata("lib.Point.new")
        .expect("imported UDT constructor metadata");

    assert_eq!(point.identity.source_id, SourceId::library(0));
    assert_eq!(point.identity.name, "Point");
    assert!(analyzer.imported_user_type_has_scalar_tree_fields(point));
    assert_eq!(
        analyzer.imported_user_type_constructor_has_supported_fields("lib.Point.new"),
        Some(true)
    );
    assert!(
        analyzer
            .imported_user_type_constructor_metadata("Point.new")
            .is_none()
    );
    assert!(
        analyzer
            .imported_user_type_constructor_metadata("lib.Point")
            .is_none()
    );
}

#[test]
fn plans_imported_user_type_constructor_args_without_accepting_it() {
    let mut analyzer = analyzer();
    analyzer.imported_user_types.insert(
        "lib.Point".to_owned(),
        imported_type(
            SourceId::library(0),
            "Point",
            vec![
                imported_field(
                    "x",
                    "float",
                    Some(PineType::new(Qualifier::Series, ValueKind::Float)),
                ),
                imported_field(
                    "label",
                    "string",
                    Some(PineType::new(Qualifier::Series, ValueKind::String)),
                ),
            ],
        ),
    );

    assert_eq!(
        analyzer.imported_user_type_constructor_arg_plan(
            "lib.Point.new",
            &[call_arg(None, "close"), call_arg(Some("label"), "name")]
        ),
        Some(Ok(ImportedUdtConstructorArgPlan {
            supported_fields: true,
            field_arg_indices: vec![0, 1],
        }))
    );
    assert_eq!(
        analyzer.imported_user_type_constructor_arg_plan(
            "lib.Point.new",
            &[
                call_arg(Some("label"), "name"),
                call_arg(Some("x"), "close")
            ]
        ),
        Some(Ok(ImportedUdtConstructorArgPlan {
            supported_fields: true,
            field_arg_indices: vec![1, 0],
        }))
    );
    assert_eq!(
        analyzer.imported_user_type_constructor_arg_plan(
            "lib.Point.new",
            &[call_arg(Some("label"), "name")]
        ),
        Some(Err(ImportedUdtConstructorArgError::MissingField(
            "x".to_owned()
        )))
    );
    assert_eq!(
        analyzer.imported_user_type_constructor_arg_plan(
            "lib.Point.new",
            &[call_arg(Some("missing"), "close")]
        ),
        Some(Err(ImportedUdtConstructorArgError::UnknownField(
            "missing".to_owned()
        )))
    );
    assert_eq!(
        analyzer.imported_user_type_constructor_arg_plan(
            "lib.Point.new",
            &[call_arg(Some("x"), "close"), call_arg(Some("x"), "open")]
        ),
        Some(Err(ImportedUdtConstructorArgError::DuplicateField(
            "x".to_owned()
        )))
    );
    assert_eq!(
        analyzer.imported_user_type_constructor_arg_plan(
            "lib.Point.new",
            &[call_arg(Some("x"), "close"), call_arg(None, "name")]
        ),
        Some(Err(ImportedUdtConstructorArgError::PositionalAfterNamed))
    );
    assert_eq!(
        analyzer.imported_user_type_constructor_arg_plan(
            "lib.Point.new",
            &[
                call_arg(None, "close"),
                call_arg(None, "name"),
                call_arg(None, "extra")
            ]
        ),
        Some(Err(ImportedUdtConstructorArgError::TooManyArgs {
            expected: 2,
            actual: 3,
        }))
    );
}

#[test]
fn detects_imported_user_type_constructor_with_deferred_field_family() {
    let mut analyzer = analyzer();
    analyzer.imported_user_types.insert(
        "lib.Wrapper".to_owned(),
        imported_type(
            SourceId::library(1),
            "Wrapper",
            vec![imported_field("nested", "Other", None)],
        ),
    );

    let wrapper = analyzer
        .imported_user_type_constructor_metadata("lib.Wrapper.new")
        .expect("imported UDT constructor metadata");

    assert!(!analyzer.imported_user_type_has_scalar_tree_fields(wrapper));
    assert_eq!(
        analyzer.imported_user_type_constructor_has_supported_fields("lib.Wrapper.new"),
        Some(false)
    );
    assert_eq!(
        analyzer.imported_user_type_constructor_arg_plan(
            "lib.Wrapper.new",
            &[call_arg(Some("nested"), "value")]
        ),
        Some(Ok(ImportedUdtConstructorArgPlan {
            supported_fields: false,
            field_arg_indices: vec![0],
        }))
    );
}

#[test]
fn plans_imported_user_type_constructor_args_with_object_fields() {
    let mut analyzer = analyzer();
    analyzer.imported_user_types.insert(
        "lib.Marker".to_owned(),
        imported_type(
            SourceId::library(1),
            "Marker",
            vec![imported_field(
                "id",
                "label",
                Some(PineType::new(Qualifier::Series, ValueKind::Label)),
            )],
        ),
    );

    let marker = analyzer
        .imported_user_type_constructor_metadata("lib.Marker.new")
        .expect("imported UDT constructor metadata");

    assert!(!analyzer.imported_user_type_has_scalar_tree_fields(marker));
    assert_eq!(
        analyzer.imported_user_type_constructor_has_supported_fields("lib.Marker.new"),
        Some(true)
    );
    assert_eq!(
        analyzer.imported_user_type_constructor_arg_plan(
            "lib.Marker.new",
            &[call_arg(Some("id"), "label.new(bar_index, close)")]
        ),
        Some(Ok(ImportedUdtConstructorArgPlan {
            supported_fields: true,
            field_arg_indices: vec![0],
        }))
    );
}

#[test]
fn registers_local_user_type_identity_as_root_source() {
    let mut analyzer = analyzer();
    let program = pine_syntax::parse_source(&pine_syntax::SourceFile::new(
        "root.pine",
        r#"type Point
    float x
"#,
    ))
    .program;

    analyzer.register_user_types(&program);

    let point = analyzer.user_types.get("Point").expect("registered UDT");
    assert_eq!(point.identity.source_id, SourceId::root());
    assert_eq!(point.identity.name, "Point");
}

#[test]
fn mirrors_user_type_identity_for_symbols_and_expr_spans() {
    let mut analyzer = analyzer();
    analyzer
        .user_types
        .insert("Point".to_owned(), scalar_type("Point"));
    let symbol = analyzer.define_symbol(
        "point",
        PineType::new(Qualifier::Series, ValueKind::UserType),
        None,
    );

    analyzer.mark_symbol_user_type(symbol, "Point".to_owned());
    analyzer.mark_expr_user_type(Span::new(10, 20), "Point".to_owned());

    let symbol_identity = analyzer
        .symbol_user_type_identities
        .get(&symbol.id)
        .expect("symbol UDT identity");
    assert_eq!(symbol_identity.source_id, SourceId::root());
    assert_eq!(symbol_identity.name, "Point");

    let expr = identifier("point", Span::new(10, 20));
    let expr_identity = analyzer
        .expr_user_type_identity(&expr)
        .expect("expr UDT identity");
    assert_eq!(expr_identity.source_id, SourceId::root());
    assert_eq!(expr_identity.name, "Point");
    assert_eq!(
        analyzer.expr_user_type_name(&expr),
        Some("Point".to_owned())
    );
}

#[test]
fn source_context_isolates_same_span_metadata_and_bindings() {
    let mut analyzer = analyzer();
    analyzer
        .user_types
        .insert("RootPoint".to_owned(), scalar_type("RootPoint"));
    analyzer.imported_user_types.insert(
        "left.Point".to_owned(),
        imported_type(SourceId::library(0), "Point", Vec::new()),
    );
    analyzer.imported_user_types.insert(
        "right.Point".to_owned(),
        imported_type(SourceId::library(0), "Point", Vec::new()),
    );

    let span = Span::new(40, 52);
    let expr = Expr {
        kind: ExprKind::Literal(Literal::Int(1)),
        span,
    };
    let root = SourceContextId::root();
    let left = SourceContextId::import_instance(0);
    let right = SourceContextId::import_instance(1);

    let root_symbol = analyzer.define_local_symbol(
        "shared",
        PineType::new(Qualifier::Const, ValueKind::Float),
        None,
        false,
    );
    analyzer.bind_symbol("shared", span, root_symbol);
    analyzer.mark_expr_user_type(span, "RootPoint".to_owned());
    analyzer.mark_expr_user_type_array(span, "RootPoint".to_owned());
    analyzer.mark_expr_map(
        span,
        MapTypeInfo {
            key_kind: ValueKind::Int,
            value_kind: ValueKind::Float,
        },
    );
    let key = analyzer.expr_key(span);
    analyzer
        .expr_types
        .insert(key, PineType::new(Qualifier::Const, ValueKind::Tuple));

    analyzer.with_source_context(left, |analyzer| {
        let symbol = analyzer.define_local_symbol(
            "shared",
            PineType::new(Qualifier::Simple, ValueKind::Float),
            None,
            false,
        );
        analyzer.bind_symbol("shared", span, symbol);
        analyzer.mark_expr_user_type(span, "left.Point".to_owned());
        analyzer.mark_expr_user_type_array(span, "left.Point".to_owned());
        analyzer.mark_expr_map(
            span,
            MapTypeInfo {
                key_kind: ValueKind::Float,
                value_kind: ValueKind::Int,
            },
        );
        let key = analyzer.expr_key(span);
        analyzer
            .expr_types
            .insert(key, PineType::new(Qualifier::Simple, ValueKind::Tuple));
    });
    analyzer.with_source_context(right, |analyzer| {
        let symbol = analyzer.define_local_symbol(
            "shared",
            PineType::new(Qualifier::Series, ValueKind::Float),
            None,
            false,
        );
        analyzer.bind_symbol("shared", span, symbol);
        analyzer.mark_expr_user_type(span, "right.Point".to_owned());
        analyzer.mark_expr_user_type_array(span, "right.Point".to_owned());
        analyzer.mark_expr_map(
            span,
            MapTypeInfo {
                key_kind: ValueKind::String,
                value_kind: ValueKind::Bool,
            },
        );
        let key = analyzer.expr_key(span);
        analyzer
            .expr_types
            .insert(key, PineType::new(Qualifier::Series, ValueKind::Tuple));
    });

    let snapshot = |analyzer: &Analyzer| {
        (
            analyzer.bound_symbol("shared", span).expect("bound symbol"),
            analyzer.expr_user_type_name(&expr).expect("UDT name"),
            analyzer
                .expr_user_type_identity(&expr)
                .expect("UDT identity"),
            analyzer
                .expr_user_type_array_name(&expr)
                .expect("UDT array name"),
            analyzer.map_type_of_expr(&expr).expect("map template"),
            *analyzer
                .expr_types
                .get(&analyzer.expr_key(span))
                .expect("tuple type"),
        )
    };

    let root_snapshot = snapshot(&analyzer);
    let left_snapshot = analyzer.with_source_context_ref(left, snapshot);
    let right_snapshot = analyzer.with_source_context_ref(right, snapshot);

    assert_eq!(analyzer.current_source_context_id(), root);
    assert!(analyzer.source_context_stack_is_restored());
    assert_eq!(root_snapshot.0.id, root_symbol.id);
    assert_eq!(root_snapshot.1, "RootPoint");
    assert_eq!(root_snapshot.2.source_id, SourceId::root());
    assert_eq!(root_snapshot.3, "RootPoint");
    assert_eq!(root_snapshot.4.key_kind, ValueKind::Int);
    assert_eq!(root_snapshot.5.qualifier, Qualifier::Const);
    assert_ne!(left_snapshot.0.id, root_snapshot.0.id);
    assert_eq!(left_snapshot.1, "left.Point");
    assert_eq!(left_snapshot.2.source_id, SourceId::library(0));
    assert_eq!(left_snapshot.2, right_snapshot.2);
    assert_eq!(left_snapshot.3, "left.Point");
    assert_eq!(left_snapshot.4.key_kind, ValueKind::Float);
    assert_eq!(left_snapshot.5.qualifier, Qualifier::Simple);
    assert_ne!(right_snapshot.0.id, left_snapshot.0.id);
    assert_eq!(right_snapshot.1, "right.Point");
    assert_eq!(right_snapshot.3, "right.Point");
    assert_eq!(right_snapshot.4.key_kind, ValueKind::String);
    assert_eq!(right_snapshot.5.qualifier, Qualifier::Series);

    analyzer.with_source_context(right, |analyzer| {
        assert_eq!(
            analyzer.analyze_expr(&expr),
            Some(PineType::new(Qualifier::Const, ValueKind::Int))
        );
        assert!(analyzer.expr_user_type_array_name(&expr).is_none());
        assert!(analyzer.map_type_of_expr(&expr).is_none());
    });
    assert_eq!(
        analyzer.expr_user_type_array_name(&expr),
        Some("RootPoint".to_owned())
    );
    assert_eq!(
        analyzer.map_type_of_expr(&expr).map(|info| info.key_kind),
        Some(ValueKind::Int)
    );
}

#[test]
fn source_context_restores_after_nested_early_return() {
    let mut analyzer = analyzer();
    let left = SourceContextId::import_instance(0);
    let right = SourceContextId::import_instance(1);

    let result = analyzer.with_source_context(left, |analyzer| {
        assert_eq!(analyzer.current_source_context_id(), left);
        let nested = analyzer.with_source_context(right, |analyzer| {
            assert_eq!(analyzer.current_source_context_id(), right);
            None::<()>
        });
        assert!(nested.is_none());
        assert_eq!(analyzer.current_source_context_id(), left);
        Some(())
    });

    assert_eq!(result, Some(()));
    assert!(analyzer.source_context_stack_is_restored());
}

#[test]
fn symbol_initializer_restores_its_source_context_for_binding_lookups() {
    let mut analyzer = analyzer();
    let span = Span::new(70, 76);
    let left = SourceContextId::import_instance(0);
    let root_symbol = analyzer.define_local_symbol(
        "source",
        PineType::new(Qualifier::Const, ValueKind::Int),
        None,
        false,
    );
    analyzer.bind_symbol("source", span, root_symbol);
    let holder = analyzer.define_local_symbol(
        "holder",
        PineType::new(Qualifier::Const, ValueKind::Int),
        None,
        false,
    );
    let left_symbol = analyzer.with_source_context(left, |analyzer| {
        let symbol = analyzer.define_local_symbol(
            "source",
            PineType::new(Qualifier::Series, ValueKind::Int),
            None,
            false,
        );
        analyzer.bind_symbol("source", span, symbol);
        symbol
    });
    analyzer.symbol_init_exprs.insert(
        holder.id,
        SourcedExpr {
            source_context_id: left,
            expr: identifier("source", span),
        },
    );

    let resolved = analyzer
        .with_symbol_initializer(holder.id, |analyzer, initializer| {
            let ExprKind::Identifier(name) = &initializer.kind else {
                return None;
            };
            analyzer
                .bound_symbol(name, initializer.span)
                .map(|symbol| symbol.id)
        })
        .expect("sourced initializer lookup");

    assert_eq!(resolved, left_symbol.id);
    assert_ne!(resolved, root_symbol.id);
    assert!(analyzer.source_context_stack_is_restored());
}

#[test]
fn mirrors_user_type_identity_when_marking_symbol_id_for_lowering() {
    let mut analyzer = analyzer();
    analyzer
        .user_types
        .insert("Point".to_owned(), scalar_type("Point"));
    let symbol = analyzer.define_symbol(
        "lowered_point",
        PineType::new(Qualifier::Series, ValueKind::UserType),
        None,
    );

    analyzer.mark_symbol_id_user_type(symbol.id, "Point".to_owned());

    assert_eq!(
        analyzer.symbol_user_types.get(&symbol.id),
        Some(&"Point".to_owned())
    );
    let identity = analyzer
        .symbol_user_type_identities
        .get(&symbol.id)
        .expect("lowered symbol UDT identity");
    assert_eq!(identity.source_id, SourceId::root());
    assert_eq!(identity.name, "Point");
}

#[test]
fn tracks_user_type_array_names_for_symbols_and_expr_spans() {
    let mut analyzer = analyzer();
    let symbol = analyzer.define_symbol(
        "points",
        PineType::new(Qualifier::Series, ValueKind::UserTypeArray),
        None,
    );
    analyzer.mark_symbol_user_type_array(symbol, "Point".to_owned());

    assert_eq!(
        analyzer.user_type_array_name_of_expr(&identifier("points", Span::new(1, 7))),
        Some("Point".to_owned())
    );
    assert_eq!(
        analyzer.user_type_array_name_of_expr(&qualified_name("points", Span::new(10, 16))),
        Some("Point".to_owned())
    );

    let array_from_expr = identifier("array.from", Span::new(20, 30));
    analyzer.mark_expr_user_type_array(array_from_expr.span, "Point".to_owned());

    assert_eq!(
        analyzer.expr_user_type_array_name(&array_from_expr),
        Some("Point".to_owned())
    );
    assert_eq!(
        analyzer.user_type_array_name_of_expr(&array_from_expr),
        Some("Point".to_owned())
    );

    let concat_expr = identifier("array.concat", Span::new(40, 52));
    analyzer.mark_expr_user_type_array(concat_expr.span, "Point".to_owned());

    assert_eq!(
        analyzer.user_type_array_name_of_expr(&concat_expr),
        Some("Point".to_owned())
    );
}

#[test]
fn classifies_same_scalar_local_user_type_array_elements() {
    let mut user_types = HashMap::new();
    user_types.insert("Point".to_owned(), scalar_type("Point"));
    assert_eq!(
        classify_user_type_array_element_names(
            &user_types,
            &["Point".to_owned(), "Point".to_owned()],
        ),
        Some(UserTypeArrayElementInference::SameScalarLocal(
            "Point".to_owned()
        ))
    );
}

#[test]
fn classifies_mixed_local_user_type_array_elements() {
    let mut user_types = HashMap::new();
    user_types.insert("Point".to_owned(), scalar_type("Point"));
    user_types.insert("Marker".to_owned(), scalar_type("Marker"));
    assert_eq!(
        classify_user_type_array_element_names(
            &user_types,
            &["Point".to_owned(), "Marker".to_owned()],
        ),
        Some(UserTypeArrayElementInference::MixedLocal)
    );
}

#[test]
fn classifies_same_scalar_tree_local_user_type_array_elements() {
    let mut user_types = HashMap::new();
    user_types.insert("Point".to_owned(), scalar_type("Point"));
    user_types.insert(
        "Wrapper".to_owned(),
        UserTypeInfo {
            identity: UserTypeIdentity {
                source_id: SourceId::root(),
                name: "Wrapper".to_owned(),
            },
            name: "Wrapper".to_owned(),
            fields: vec![
                field("inner", ValueKind::UserType, Some("Point")),
                field("weight", ValueKind::Float, None),
            ],
        },
    );

    assert_eq!(
        classify_user_type_array_element_names(
            &user_types,
            &["Wrapper".to_owned(), "Wrapper".to_owned()],
        ),
        Some(UserTypeArrayElementInference::SameScalarLocal(
            "Wrapper".to_owned()
        ))
    );
}
