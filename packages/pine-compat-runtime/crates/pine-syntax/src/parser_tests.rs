use crate::{
    BinaryOp, DeclMode, DeclaredType, ExprKind, FunctionBody, Literal, Parse, SourceFile, StmtKind,
    SwitchArmResult, parse_source,
};

fn parse(text: &str) -> Parse {
    parse_source(&SourceFile::new("test.pine", text))
}

fn declared_type_name(declared_type: &Option<DeclaredType>) -> Option<String> {
    declared_type.as_ref().map(DeclaredType::canonical_name)
}

fn first_declared_type(parsed: &Parse) -> Option<String> {
    let StmtKind::Decl { declared_type, .. } = &parsed.program.statements[0].kind else {
        panic!("expected declaration");
    };
    declared_type_name(declared_type)
}

#[test]
fn declared_type_canonical_names_match_existing_ast_strings() {
    assert_eq!(
        DeclaredType::Named("chart.point".to_owned()).into_canonical_name(),
        "chart.point"
    );
    assert_eq!(
        DeclaredType::Array {
            element_type: "chart.point".to_owned()
        }
        .into_canonical_name(),
        "array<chart.point>"
    );
}

#[test]
fn parses_version_and_indicator() {
    let parsed = parse("//@version=5\nindicator(\"Demo\", overlay=true)\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    assert_eq!(
        parsed.program.version.map(|version| version.version),
        Some(5)
    );
    assert_eq!(parsed.program.statements.len(), 1);
}

#[test]
fn parses_declaration_with_history_call() {
    let parsed = parse("x = ta.sma(close, 20)[1]\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    assert_eq!(parsed.program.statements.len(), 1);
    assert!(matches!(
        parsed.program.statements[0].kind,
        StmtKind::Decl { .. }
    ));
}

#[test]
fn parses_chart_point_array_new_template_call() {
    let parsed = parse("points = array.new<chart.point>(2, chart.point.now(close))\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let StmtKind::Decl { value, .. } = &parsed.program.statements[0].kind else {
        panic!("expected declaration");
    };
    let ExprKind::Call { callee, args } = &value.kind else {
        panic!("expected call");
    };
    assert_eq!(
        callee.kind,
        ExprKind::Identifier("array.new<chart.point>".to_owned())
    );
    assert_eq!(args.len(), 2);
}

#[test]
fn parses_scalar_array_new_template_call() {
    let parsed = parse("values = array.new<float>(2, close)\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let StmtKind::Decl { value, .. } = &parsed.program.statements[0].kind else {
        panic!("expected declaration");
    };
    let ExprKind::Call { callee, args } = &value.kind else {
        panic!("expected call");
    };
    assert_eq!(
        callee.kind,
        ExprKind::Identifier("array.new_float".to_owned())
    );
    assert_eq!(args.len(), 2);
}

#[test]
fn parses_udt_array_new_template_call() {
    let parsed = parse("points = array.new<Point>(2, Point.new(close))\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let StmtKind::Decl { value, .. } = &parsed.program.statements[0].kind else {
        panic!("expected declaration");
    };
    let ExprKind::Call { callee, args } = &value.kind else {
        panic!("expected call");
    };
    assert_eq!(
        callee.kind,
        ExprKind::Identifier("array.new<Point>".to_owned())
    );
    assert_eq!(args.len(), 2);
}

#[test]
fn parses_imported_udt_array_new_template_call() {
    let parsed = parse("points = array.new<lib.Point>(2, lib.Point.new(close))\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let StmtKind::Decl { value, .. } = &parsed.program.statements[0].kind else {
        panic!("expected declaration");
    };
    let ExprKind::Call { callee, args } = &value.kind else {
        panic!("expected call");
    };
    assert_eq!(
        callee.kind,
        ExprKind::Identifier("array.new<lib.Point>".to_owned())
    );
    assert_eq!(args.len(), 2);
}

#[test]
fn parses_qualified_call_result_method_receiver() {
    let parsed = parse(
        "shifted = lib.Point.new(close).shift(5)\nchained = lib.Point.new(open).make(close + 1).same()\nlocal = Point.new(close).shift(5)\nbound = anchor.make(close).same()\nindexed = anchor.make(values).get(index=0)\n",
    );

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let StmtKind::Decl { value, .. } = &parsed.program.statements[0].kind else {
        panic!("expected declaration");
    };
    let ExprKind::Call { callee, args } = &value.kind else {
        panic!("expected method call");
    };
    assert_eq!(
        callee.kind,
        ExprKind::QualifiedName(vec!["lib".to_owned(), "shift".to_owned()])
    );
    assert_eq!(args.len(), 2);
    assert!(args[0].value.span.end < callee.span.start);
    let ExprKind::Call {
        callee: receiver_callee,
        ..
    } = &args[0].value.kind
    else {
        panic!("expected constructor receiver argument");
    };
    assert_eq!(
        receiver_callee.kind,
        ExprKind::QualifiedName(vec!["lib".to_owned(), "Point".to_owned(), "new".to_owned()])
    );

    let StmtKind::Decl { value, .. } = &parsed.program.statements[1].kind else {
        panic!("expected declaration");
    };
    let ExprKind::Call { callee, args } = &value.kind else {
        panic!("expected outer method call");
    };
    assert_eq!(
        callee.kind,
        ExprKind::QualifiedName(vec!["lib".to_owned(), "same".to_owned()])
    );
    assert_eq!(args.len(), 1);
    assert!(args[0].value.span.end < callee.span.start);
    let ExprKind::Call {
        callee: receiver_callee,
        ..
    } = &args[0].value.kind
    else {
        panic!("expected method-result receiver argument");
    };
    assert_eq!(
        receiver_callee.kind,
        ExprKind::QualifiedName(vec!["lib".to_owned(), "make".to_owned()])
    );

    let StmtKind::Decl { value, .. } = &parsed.program.statements[2].kind else {
        panic!("expected declaration");
    };
    let ExprKind::Call { callee, args } = &value.kind else {
        panic!("expected local method call");
    };
    assert_eq!(
        callee.kind,
        ExprKind::QualifiedName(vec!["Point".to_owned(), "shift".to_owned()])
    );
    assert_eq!(args.len(), 2);
    let ExprKind::Call {
        callee: receiver_callee,
        ..
    } = &args[0].value.kind
    else {
        panic!("expected local constructor receiver argument");
    };
    assert_eq!(
        receiver_callee.kind,
        ExprKind::QualifiedName(vec!["Point".to_owned(), "new".to_owned()])
    );

    let StmtKind::Decl { value, .. } = &parsed.program.statements[3].kind else {
        panic!("expected bound-receiver method-result declaration");
    };
    let ExprKind::Call { callee, args } = &value.kind else {
        panic!("expected bound-receiver outer method call");
    };
    assert_eq!(
        callee.kind,
        ExprKind::QualifiedName(vec!["anchor".to_owned(), "same".to_owned()])
    );
    assert_eq!(args.len(), 1);
    assert!(args[0].value.span.end < callee.span.start);
    let ExprKind::Call {
        callee: receiver_callee,
        ..
    } = &args[0].value.kind
    else {
        panic!("expected bound-receiver method-result argument");
    };
    assert_eq!(
        receiver_callee.kind,
        ExprKind::QualifiedName(vec!["anchor".to_owned(), "make".to_owned()])
    );

    let StmtKind::Decl { value, .. } = &parsed.program.statements[4].kind else {
        panic!("expected indexed call-result declaration");
    };
    let ExprKind::Call { callee, args } = &value.kind else {
        panic!("expected indexed call-result method call");
    };
    assert_eq!(
        callee.kind,
        ExprKind::QualifiedName(vec!["anchor".to_owned(), "get".to_owned()])
    );
    assert_eq!(args.len(), 2);
    assert!(args[0].name.is_none());
    assert!(args[0].value.span.end < callee.span.start);
    assert_eq!(args[1].name.as_deref(), Some("index"));
}

#[test]
fn parses_unqualified_call_result_method_receiver() {
    let parsed = parse("item = make(values).get(index=0)\nnested = array(values).copy().last()\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let StmtKind::Decl { value, .. } = &parsed.program.statements[0].kind else {
        panic!("expected declaration");
    };
    let ExprKind::Call { callee, args } = &value.kind else {
        panic!("expected call-result method call");
    };
    assert_eq!(
        callee.kind,
        ExprKind::QualifiedName(vec!["$call_result".to_owned(), "get".to_owned()])
    );
    assert_eq!(args.len(), 2);
    assert!(args[0].value.span.end < callee.span.start);
    assert_eq!(args[1].name.as_deref(), Some("index"));

    let StmtKind::Decl { value, .. } = &parsed.program.statements[1].kind else {
        panic!("expected nested declaration");
    };
    let ExprKind::Call { callee, args } = &value.kind else {
        panic!("expected nested outer call");
    };
    assert_eq!(
        callee.kind,
        ExprKind::QualifiedName(vec!["$call_result".to_owned(), "last".to_owned()])
    );
    let ExprKind::Call {
        callee: inner_callee,
        args: inner_args,
    } = &args[0].value.kind
    else {
        panic!("expected nested inner call");
    };
    assert_eq!(
        inner_callee.kind,
        ExprKind::QualifiedName(vec!["$call_result".to_owned(), "copy".to_owned()])
    );
    assert!(inner_args[0].value.span.end < inner_callee.span.start);
}

#[test]
fn parses_builtin_array_result_method_receivers() {
    for source in [
        "value = array.new_float(1, 1.0).size()\n",
        "value = array.new_int(2, 1).size()\n",
        "value = array.new_bool(1, true).size()\n",
        "value = array.new_string(1, \"value\").size()\n",
        "value = array.new_color(1, color.red).size()\n",
        "value = array.new_line().size()\n",
        "value = array.new_linefill().size()\n",
        "value = array.new_polyline().size()\n",
        "value = array.new_label().size()\n",
        "value = array.new_box().size()\n",
        "value = array.new_table().size()\n",
        "value = array.new<int>(2, 1).get(index=0)\n",
        "value = array.new<chart.point>().copy()\n",
        "value = array.new<Point>().first()\n",
        "value = array.new<lib.Point>().last()\n",
        "value = array.from(1, 2).size()\n",
        "value = array.copy(values).first()\n",
        "value = array.slice(values, 0, 1).last()\n",
        "value = array.concat(values, more).copy()\n",
        "value = array.from(true, true).every()\n",
        "value = array.from(false, true).some()\n",
        "value = array.from(1, 2).join(\"|\")\n",
        "value = array.from(1, 2, 3).slice(1, 3).get(0)\n",
        "value = array.from(1, 2).concat(array.from(3)).copy().last()\n",
        "value = matrix.mult(values, vector).concat(array.from(3.0)).copy().last()\n",
        "value = array.new<chart.point>(1, chart.point.now(close)).slice(0, 1).copy().last()\n",
        "value = array.new<Point>(1, Point.new(1)).slice(0, 1).first()\n",
        "value = array.new<lib.Point>(1, lib.Point.new(1)).slice(0, 1).last()\n",
        "value = array.from(1, 2).clear()\n",
        "value = array.from(1, 2).reverse()\n",
        "value = array.from(1, 2).pop()\n",
        "value = array.from(1, 2).shift()\n",
        "value = array.from(1, 2).remove(0)\n",
        "value = array.from(1, 2).push(3)\n",
        "value = array.from(1, 2).unshift(0)\n",
        "value = array.from(1, 2).insert(1, 3)\n",
        "value = array.from(1, 2).set(1, 3)\n",
        "value = array.from(1, 2).fill(3, 0, 1)\n",
        "value = array.from(2, 1).sort(order.ascending)\n",
        "value = array.abs(values).get(0)\n",
        "value = array.from(-1, 2).abs()\n",
        "value = array.from(1, 2, 3).standardize().get(1)\n",
        "value = array.copy(values).standardize().standardize().size()\n",
        "value = array.from(3, 1, 2).sort_indices().get(0)\n",
        "value = array.from(\"b\", \"a\").sort_indices(order.descending).copy().last()\n",
        "value = array.standardize(values).first()\n",
        "value = array.sort_indices(values).last()\n",
    ] {
        let parsed = parse(source);

        assert!(
            parsed.diagnostics.is_empty(),
            "{source}: {:?}",
            parsed.diagnostics
        );
        let StmtKind::Decl { value, .. } = &parsed.program.statements[0].kind else {
            panic!("expected declaration for {source}");
        };
        let ExprKind::Call { callee, args } = &value.kind else {
            panic!("expected call-result method call for {source}");
        };
        let ExprKind::QualifiedName(parts) = &callee.kind else {
            panic!("expected synthetic qualified callee for {source}");
        };
        assert_eq!(parts[0], "$builtin_array_result", "{source}");
        assert!(args[0].value.span.end < callee.span.start, "{source}");
    }

    let parsed = parse(
        "value = array.copy(values).copy().last()\nvalue = array.from(-1, 2).abs().copy().last()\n",
    );
    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let StmtKind::Decl { value, .. } = &parsed.program.statements[0].kind else {
        panic!("expected declaration");
    };
    let ExprKind::Call { callee, args } = &value.kind else {
        panic!("expected outer call-result method call");
    };
    assert_eq!(
        callee.kind,
        ExprKind::QualifiedName(vec!["$builtin_array_result".to_owned(), "last".to_owned()])
    );
    let ExprKind::Call {
        callee: inner_callee,
        ..
    } = &args[0].value.kind
    else {
        panic!("expected inner call-result method call");
    };
    assert_eq!(
        inner_callee.kind,
        ExprKind::QualifiedName(vec!["$builtin_array_result".to_owned(), "copy".to_owned()])
    );

    let StmtKind::Decl { value, .. } = &parsed.program.statements[1].kind else {
        panic!("expected nested abs declaration");
    };
    let ExprKind::Call { callee, args } = &value.kind else {
        panic!("expected nested abs outer call");
    };
    assert_eq!(
        callee.kind,
        ExprKind::QualifiedName(vec!["$builtin_array_result".to_owned(), "last".to_owned()])
    );
    let ExprKind::Call {
        callee: copy_callee,
        args: copy_args,
    } = &args[0].value.kind
    else {
        panic!("expected nested abs copy call");
    };
    assert_eq!(
        copy_callee.kind,
        ExprKind::QualifiedName(vec!["$builtin_array_result".to_owned(), "copy".to_owned()])
    );
    let ExprKind::Call {
        callee: abs_callee, ..
    } = &copy_args[0].value.kind
    else {
        panic!("expected nested abs call");
    };
    assert_eq!(
        abs_callee.kind,
        ExprKind::QualifiedName(vec!["$builtin_array_result".to_owned(), "abs".to_owned()])
    );
}

#[test]
fn parses_cross_namespace_builtin_array_result_method_receivers() {
    for source in [
        "value = str.split(\"a,b\", \",\").size()\n",
        "value = ta.pivot_point_levels(\"Traditional\", true).get(0)\n",
        "value = matrix.eigenvalues(values).first()\n",
        "value = matrix.row(values, 0).last()\n",
        "value = matrix.col(values, 0).copy()\n",
        "value = map.keys(values).size()\n",
        "value = map.values(values).get(0)\n",
        "value = str.split(\"a,b\", \",\").slice(0, 1).last()\n",
        "value = matrix.row(values, 0).slice(0, 1).copy().size()\n",
        "value = map.values(values).slice(0, 1).first()\n",
        "value = matrix.mult(values, vector).slice(0, 1).copy().last()\n",
        "value = map.keys(values).clear()\n",
        "value = matrix.row(values, 0).reverse()\n",
        "value = str.split(\"a,b\", \",\").pop()\n",
        "value = str.split(\"a,b\", \",\").shift()\n",
        "value = str.split(\"a,b\", \",\").remove(0)\n",
        "value = str.split(\"a,b\", \",\").push(\"c\")\n",
        "value = str.split(\"a,b\", \",\").unshift(\"z\")\n",
        "value = str.split(\"a,b\", \",\").insert(1, \"z\")\n",
        "value = str.split(\"a,b\", \",\").set(1, \"z\")\n",
        "value = str.split(\"a,b\", \",\").fill(\"z\", 0, 1)\n",
        "value = str.split(\"b,a\", \",\").sort(order.ascending)\n",
    ] {
        let parsed = parse(source);

        assert!(
            parsed.diagnostics.is_empty(),
            "{source}: {:?}",
            parsed.diagnostics
        );
        let StmtKind::Decl { value, .. } = &parsed.program.statements[0].kind else {
            panic!("expected declaration for {source}");
        };
        let ExprKind::Call { callee, args } = &value.kind else {
            panic!("expected call-result method call for {source}");
        };
        assert!(matches!(
            &callee.kind,
            ExprKind::QualifiedName(parts)
                if parts.first().is_some_and(|part| part == "$builtin_array_result")
        ));
        assert!(args[0].value.span.end < callee.span.start, "{source}");
    }

    let parsed = parse("value = str.split(\"a,b\", \",\").copy().last()\n");
    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let StmtKind::Decl { value, .. } = &parsed.program.statements[0].kind else {
        panic!("expected declaration");
    };
    let ExprKind::Call { callee, args } = &value.kind else {
        panic!("expected outer call-result method call");
    };
    assert_eq!(
        callee.kind,
        ExprKind::QualifiedName(vec!["$builtin_array_result".to_owned(), "last".to_owned()])
    );
    let ExprKind::Call {
        callee: inner_callee,
        ..
    } = &args[0].value.kind
    else {
        panic!("expected inner call-result method call");
    };
    assert_eq!(
        inner_callee.kind,
        ExprKind::QualifiedName(vec!["$builtin_array_result".to_owned(), "copy".to_owned()])
    );
}

#[test]
fn parses_matrix_mult_result_method_receivers_with_separate_provenance() {
    for source in [
        "value = matrix.mult(left, right).rows()\n",
        "value = matrix.mult(left, right).columns()\n",
        "value = matrix.mult(left, right).elements_count()\n",
        "value = matrix.mult(left, right).get(0, 0)\n",
        "value = matrix.mult(left, right).copy()\n",
        "value = matrix.mult(left, array.from(1.0, 2.0)).size()\n",
        "value = matrix.mult(array.from(1.0, 2.0), left).first()\n",
        "value = matrix.mult(array.from(1.0, 2.0), array.from(3.0, 4.0)).last()\n",
    ] {
        let parsed = parse(source);

        assert!(
            parsed.diagnostics.is_empty(),
            "{source}: {:?}",
            parsed.diagnostics
        );
        let StmtKind::Decl { value, .. } = &parsed.program.statements[0].kind else {
            panic!("expected declaration for {source}");
        };
        let ExprKind::Call { callee, args } = &value.kind else {
            panic!("expected call-result method call for {source}");
        };
        assert!(matches!(
            &callee.kind,
            ExprKind::QualifiedName(parts)
                if parts.first().is_some_and(|part| part == "$builtin_matrix_result")
        ));
        assert!(args[0].value.span.end < callee.span.start, "{source}");
    }

    for (source, terminal_method) in [
        ("value = matrix.mult(left, right).copy().rows()\n", "rows"),
        (
            "value = matrix.mult(left, array.from(1.0, 2.0)).copy().last()\n",
            "last",
        ),
    ] {
        let parsed = parse(source);
        assert!(
            parsed.diagnostics.is_empty(),
            "{source}: {:?}",
            parsed.diagnostics
        );
        let StmtKind::Decl { value, .. } = &parsed.program.statements[0].kind else {
            panic!("expected declaration for {source}");
        };
        let ExprKind::Call { callee, args } = &value.kind else {
            panic!("expected outer call-result method call for {source}");
        };
        assert_eq!(
            callee.kind,
            ExprKind::QualifiedName(vec![
                "$builtin_matrix_result".to_owned(),
                terminal_method.to_owned(),
            ])
        );
        let ExprKind::Call {
            callee: inner_callee,
            ..
        } = &args[0].value.kind
        else {
            panic!("expected inner call-result method call for {source}");
        };
        assert_eq!(
            inner_callee.kind,
            ExprKind::QualifiedName(vec!["$builtin_matrix_result".to_owned(), "copy".to_owned(),])
        );
    }

    let source = "value = matrix.mult(left, array.from(1.0, 2.0)).standardize().first()\n";
    let parsed = parse(source);
    assert!(
        parsed.diagnostics.is_empty(),
        "{source}: {:?}",
        parsed.diagnostics
    );
    let StmtKind::Decl { value, .. } = &parsed.program.statements[0].kind else {
        panic!("expected declaration for {source}");
    };
    let ExprKind::Call { callee, args } = &value.kind else {
        panic!("expected outer array-result call for {source}");
    };
    assert_eq!(
        callee.kind,
        ExprKind::QualifiedName(vec!["$builtin_array_result".to_owned(), "first".to_owned()])
    );
    let ExprKind::Call {
        callee: inner_callee,
        ..
    } = &args[0].value.kind
    else {
        panic!("expected inner matrix-result call for {source}");
    };
    assert_eq!(
        inner_callee.kind,
        ExprKind::QualifiedName(vec![
            "$builtin_matrix_result".to_owned(),
            "standardize".to_owned(),
        ])
    );
}

#[test]
fn parses_matrix_copy_result_method_receivers_with_matrix_provenance() {
    for source in [
        "value = matrix.copy(values).rows()\n",
        "value = matrix.copy(values).columns()\n",
        "value = matrix.copy(values).elements_count()\n",
        "value = matrix.copy(values).get(0, 0)\n",
        "value = matrix.copy(values).set(0, 0, 1.0)\n",
        "value = matrix.copy(values).fill(1.0)\n",
        "value = matrix.copy(values).reverse()\n",
        "value = matrix.copy(values).reshape(1, 1)\n",
        "value = matrix.copy(values).add_row(0, array.from(1.0, 2.0))\n",
        "value = matrix.copy(values).add_col(0, array.from(1.0, 2.0))\n",
        "value = matrix.copy(values).sort()\n",
        "value = matrix.copy(values).swap_rows(0, 1)\n",
        "value = matrix.copy(values).swap_columns(0, 1)\n",
        "value = matrix.copy(values).remove_row(0)\n",
        "value = matrix.copy(values).remove_col(0)\n",
        "value = matrix.copy(values).copy().get(0, 0)\n",
        "value = matrix.copy(values).transpose().rows()\n",
        "value = matrix.copy(values).submatrix(0, 1, 0, 1).rows()\n",
        "value = matrix.copy(values).submatrix().copy().columns()\n",
        "value = matrix.copy(values).submatrix().transpose().get(0, 0)\n",
        "value = matrix.copy(values).transpose().submatrix().get(0, 0)\n",
        "value = matrix.copy(values).inv().rows()\n",
        "value = matrix.copy(values).inv().copy().columns()\n",
        "value = matrix.copy(values).inv().transpose().get(0, 0)\n",
        "value = matrix.copy(values).transpose().inv().get(0, 0)\n",
        "value = matrix.copy(values).pinv().rows()\n",
        "value = matrix.copy(values).pinv().copy().columns()\n",
        "value = matrix.copy(values).pinv().transpose().get(0, 0)\n",
        "value = matrix.copy(values).transpose().pinv().get(0, 0)\n",
        "value = matrix.copy(values).pinv().inv().get(0, 0)\n",
        "value = matrix.copy(values).inv().pinv().get(0, 0)\n",
        "value = matrix.copy(values).eigenvectors().rows()\n",
        "value = matrix.copy(values).eigenvectors().copy().columns()\n",
        "value = matrix.copy(values).eigenvectors().transpose().get(0, 0)\n",
        "value = matrix.copy(values).transpose().eigenvectors().get(0, 0)\n",
        "value = matrix.copy(values).eigenvectors().pinv().get(0, 0)\n",
        "value = matrix.copy(values).pinv().eigenvectors().get(0, 0)\n",
        "value = matrix.copy(values).pow(2).rows()\n",
        "value = matrix.copy(values).pow(0).copy().columns()\n",
        "value = matrix.copy(values).pow(1).transpose().get(0, 0)\n",
        "value = matrix.copy(values).transpose().pow(2).get(0, 0)\n",
        "value = matrix.copy(values).pow(2).inv().get(0, 0)\n",
        "value = matrix.copy(values).inv().pow(2).get(0, 0)\n",
        "value = matrix.copy(values).kron(other).rows()\n",
        "value = matrix.copy(values).kron(other).copy().columns()\n",
        "value = matrix.copy(values).kron(other).transpose().get(0, 0)\n",
        "value = matrix.copy(values).transpose().kron(other).get(0, 0)\n",
        "value = matrix.copy(values).kron(other).pow(2).get(0, 0)\n",
        "value = matrix.copy(values).pow(2).kron(other).get(0, 0)\n",
        "value = matrix.copy(values).diff(other).rows()\n",
        "value = matrix.copy(values).diff(1.5).copy().columns()\n",
        "value = matrix.copy(values).diff(other).transpose().get(0, 0)\n",
        "value = matrix.copy(values).transpose().diff(other).get(0, 0)\n",
        "value = matrix.copy(values).diff(other).kron(other).get(0, 0)\n",
        "value = matrix.copy(values).kron(other).diff(other).get(0, 0)\n",
        "value = matrix.copy(values).mult(other).rows()\n",
        "value = matrix.copy(values).mult(2.0).copy().columns()\n",
        "value = matrix.copy(values).mult(vector).size()\n",
        "value = matrix.copy(values).mult(vector).copy().last()\n",
        "value = matrix.copy(values).transpose().mult(other).get(0, 0)\n",
        "value = matrix.copy(values).mult(other).transpose().get(0, 0)\n",
        "value = matrix.copy(values).transpose().copy().columns()\n",
        "value = matrix.copy(values).transpose().transpose().get(0, 0)\n",
        "value = matrix.copy(values).is_square()\n",
        "value = matrix.copy(values).is_zero()\n",
        "value = matrix.copy(values).is_binary()\n",
        "value = matrix.copy(values).is_diagonal()\n",
        "value = matrix.copy(values).is_identity()\n",
        "value = matrix.copy(values).is_symmetric()\n",
        "value = matrix.copy(values).is_antisymmetric()\n",
        "value = matrix.copy(values).is_stochastic()\n",
        "value = matrix.copy(values).sum()\n",
        "value = matrix.copy(values).avg()\n",
        "value = matrix.copy(values).min()\n",
        "value = matrix.copy(values).max()\n",
        "value = matrix.copy(values).mode()\n",
        "value = matrix.copy(values).trace()\n",
        "value = matrix.copy(values).det()\n",
        "value = matrix.copy(values).rank()\n",
    ] {
        let parsed = parse(source);

        assert!(
            parsed.diagnostics.is_empty(),
            "{source}: {:?}",
            parsed.diagnostics
        );
        let StmtKind::Decl { value, .. } = &parsed.program.statements[0].kind else {
            panic!("expected declaration for {source}");
        };
        let ExprKind::Call { callee, args } = &value.kind else {
            panic!("expected call-result method call for {source}");
        };
        assert!(matches!(
            &callee.kind,
            ExprKind::QualifiedName(parts)
                if parts.first().is_some_and(|part| part == "$builtin_matrix_result")
        ));
        assert!(args[0].value.span.end < callee.span.start, "{source}");
    }
}

#[test]
fn parses_matrix_call_result_array_producers_as_array_result_receivers() {
    for source in [
        "value = matrix.new<float>(2, 2, 1.0).row(0).size()\n",
        "value = matrix.new<int>(2, 2, 1).col(0).size()\n",
        "value = matrix.copy(values).row(0).copy().first()\n",
        "value = matrix.copy(values).col(0).copy().last()\n",
        "value = matrix.transpose(values).row(1).get(0)\n",
        "value = matrix.transpose(values).col(1).get(0)\n",
        "value = matrix.mult(values, other).copy().row(0).copy().last()\n",
        "value = matrix.mult(values, other).copy().col(0).copy().first()\n",
        "value = matrix.mult(values, other).eigenvalues().size()\n",
        "value = matrix.copy(values).eigenvalues().copy().first()\n",
        "value = matrix.mult(values, array.from(1.0, -2.0)).abs().copy().first()\n",
    ] {
        let parsed = parse(source);

        assert!(
            parsed.diagnostics.is_empty(),
            "{source}: {:?}",
            parsed.diagnostics
        );
        let StmtKind::Decl { value, .. } = &parsed.program.statements[0].kind else {
            panic!("expected declaration for {source}");
        };
        let ExprKind::Call { callee, args } = &value.kind else {
            panic!("expected call-result method call for {source}");
        };
        assert!(matches!(
            &callee.kind,
            ExprKind::QualifiedName(parts)
                if parts.first().is_some_and(|part| part == "$builtin_array_result")
        ));
        assert!(args[0].value.span.end < callee.span.start, "{source}");
    }
}

#[test]
fn parses_matrix_transpose_result_method_receivers_with_matrix_provenance() {
    for source in [
        "value = matrix.transpose(values).rows()\n",
        "value = matrix.transpose(values).columns()\n",
        "value = matrix.transpose(values).elements_count()\n",
        "value = matrix.transpose(values).get(0, 0)\n",
        "value = matrix.transpose(values).copy().get(0, 0)\n",
    ] {
        let parsed = parse(source);

        assert!(
            parsed.diagnostics.is_empty(),
            "{source}: {:?}",
            parsed.diagnostics
        );
        let StmtKind::Decl { value, .. } = &parsed.program.statements[0].kind else {
            panic!("expected declaration for {source}");
        };
        let ExprKind::Call { callee, args } = &value.kind else {
            panic!("expected call-result method call for {source}");
        };
        assert!(matches!(
            &callee.kind,
            ExprKind::QualifiedName(parts)
                if parts.first().is_some_and(|part| part == "$builtin_matrix_result")
        ));
        assert!(args[0].value.span.end < callee.span.start, "{source}");
    }
}

#[test]
fn parses_matrix_submatrix_result_method_receivers_with_matrix_provenance() {
    for source in [
        "value = matrix.submatrix(values).rows()\n",
        "value = matrix.submatrix(values, 0, 1).columns()\n",
        "value = matrix.submatrix(values, 0, 1, 0, 1).elements_count()\n",
        "value = matrix.submatrix(values, 0, 1, 0, 1).get(0, 0)\n",
        "value = matrix.submatrix(values, 0, 1, 0, 1).copy().get(0, 0)\n",
    ] {
        let parsed = parse(source);

        assert!(
            parsed.diagnostics.is_empty(),
            "{source}: {:?}",
            parsed.diagnostics
        );
        let StmtKind::Decl { value, .. } = &parsed.program.statements[0].kind else {
            panic!("expected declaration for {source}");
        };
        let ExprKind::Call { callee, args } = &value.kind else {
            panic!("expected call-result method call for {source}");
        };
        assert!(matches!(
            &callee.kind,
            ExprKind::QualifiedName(parts)
                if parts.first().is_some_and(|part| part == "$builtin_matrix_result")
        ));
        assert!(args[0].value.span.end < callee.span.start, "{source}");
    }
}

#[test]
fn parses_matrix_kron_result_method_receivers_with_matrix_provenance() {
    for source in [
        "value = matrix.kron(values, other).rows()\n",
        "value = matrix.kron(values, other).columns()\n",
        "value = matrix.kron(values, other).elements_count()\n",
        "value = matrix.kron(values, other).get(0, 0)\n",
        "value = matrix.kron(values, other).copy().get(0, 0)\n",
    ] {
        let parsed = parse(source);

        assert!(
            parsed.diagnostics.is_empty(),
            "{source}: {:?}",
            parsed.diagnostics
        );
        let StmtKind::Decl { value, .. } = &parsed.program.statements[0].kind else {
            panic!("expected declaration for {source}");
        };
        let ExprKind::Call { callee, args } = &value.kind else {
            panic!("expected call-result method call for {source}");
        };
        assert!(matches!(
            &callee.kind,
            ExprKind::QualifiedName(parts)
                if parts.first().is_some_and(|part| part == "$builtin_matrix_result")
        ));
        assert!(args[0].value.span.end < callee.span.start, "{source}");
    }
}

#[test]
fn parses_matrix_diff_result_method_receivers_with_matrix_provenance() {
    for source in [
        "value = matrix.diff(values, other).rows()\n",
        "value = matrix.diff(values, 1).columns()\n",
        "value = matrix.diff(1, values).elements_count()\n",
        "value = matrix.diff(values, other).get(0, 0)\n",
        "value = matrix.diff(values, other).copy().get(0, 0)\n",
    ] {
        let parsed = parse(source);

        assert!(
            parsed.diagnostics.is_empty(),
            "{source}: {:?}",
            parsed.diagnostics
        );
        let StmtKind::Decl { value, .. } = &parsed.program.statements[0].kind else {
            panic!("expected declaration for {source}");
        };
        let ExprKind::Call { callee, args } = &value.kind else {
            panic!("expected call-result method call for {source}");
        };
        assert!(matches!(
            &callee.kind,
            ExprKind::QualifiedName(parts)
                if parts.first().is_some_and(|part| part == "$builtin_matrix_result")
        ));
        assert!(args[0].value.span.end < callee.span.start, "{source}");
    }
}

#[test]
fn parses_matrix_pow_result_method_receivers_with_matrix_provenance() {
    for source in [
        "value = matrix.pow(values, 0).rows()\n",
        "value = matrix.pow(values, 1).columns()\n",
        "value = matrix.pow(values, 2).elements_count()\n",
        "value = matrix.pow(values, 2).get(0, 0)\n",
        "value = matrix.pow(values, 2).copy().get(0, 0)\n",
    ] {
        let parsed = parse(source);

        assert!(
            parsed.diagnostics.is_empty(),
            "{source}: {:?}",
            parsed.diagnostics
        );
        let StmtKind::Decl { value, .. } = &parsed.program.statements[0].kind else {
            panic!("expected declaration for {source}");
        };
        let ExprKind::Call { callee, args } = &value.kind else {
            panic!("expected call-result method call for {source}");
        };
        assert!(matches!(
            &callee.kind,
            ExprKind::QualifiedName(parts)
                if parts.first().is_some_and(|part| part == "$builtin_matrix_result")
        ));
        assert!(args[0].value.span.end < callee.span.start, "{source}");
    }
}

#[test]
fn parses_matrix_inv_result_method_receivers_with_matrix_provenance() {
    for source in [
        "value = matrix.inv(values).rows()\n",
        "value = matrix.inv(values).columns()\n",
        "value = matrix.inv(values).elements_count()\n",
        "value = matrix.inv(values).get(0, 0)\n",
        "value = matrix.inv(values).copy().get(0, 0)\n",
    ] {
        let parsed = parse(source);

        assert!(
            parsed.diagnostics.is_empty(),
            "{source}: {:?}",
            parsed.diagnostics
        );
        let StmtKind::Decl { value, .. } = &parsed.program.statements[0].kind else {
            panic!("expected declaration for {source}");
        };
        let ExprKind::Call { callee, args } = &value.kind else {
            panic!("expected call-result method call for {source}");
        };
        assert!(matches!(
            &callee.kind,
            ExprKind::QualifiedName(parts)
                if parts.first().is_some_and(|part| part == "$builtin_matrix_result")
        ));
        assert!(args[0].value.span.end < callee.span.start, "{source}");
    }
}

#[test]
fn parses_matrix_pinv_result_method_receivers_with_matrix_provenance() {
    for source in [
        "value = matrix.pinv(values).rows()\n",
        "value = matrix.pinv(values).columns()\n",
        "value = matrix.pinv(values).elements_count()\n",
        "value = matrix.pinv(values).get(0, 0)\n",
        "value = matrix.pinv(values).copy().get(0, 0)\n",
    ] {
        let parsed = parse(source);

        assert!(
            parsed.diagnostics.is_empty(),
            "{source}: {:?}",
            parsed.diagnostics
        );
        let StmtKind::Decl { value, .. } = &parsed.program.statements[0].kind else {
            panic!("expected declaration for {source}");
        };
        let ExprKind::Call { callee, args } = &value.kind else {
            panic!("expected call-result method call for {source}");
        };
        assert!(matches!(
            &callee.kind,
            ExprKind::QualifiedName(parts)
                if parts.first().is_some_and(|part| part == "$builtin_matrix_result")
        ));
        assert!(args[0].value.span.end < callee.span.start, "{source}");
    }
}

#[test]
fn parses_matrix_eigenvectors_result_method_receivers_with_matrix_provenance() {
    for source in [
        "value = matrix.eigenvectors(values).rows()\n",
        "value = matrix.eigenvectors(values).columns()\n",
        "value = matrix.eigenvectors(values).elements_count()\n",
        "value = matrix.eigenvectors(values).get(0, 0)\n",
        "value = matrix.eigenvectors(values).copy().get(0, 0)\n",
    ] {
        let parsed = parse(source);

        assert!(
            parsed.diagnostics.is_empty(),
            "{source}: {:?}",
            parsed.diagnostics
        );
        let StmtKind::Decl { value, .. } = &parsed.program.statements[0].kind else {
            panic!("expected declaration for {source}");
        };
        let ExprKind::Call { callee, args } = &value.kind else {
            panic!("expected call-result method call for {source}");
        };
        assert!(matches!(
            &callee.kind,
            ExprKind::QualifiedName(parts)
                if parts.first().is_some_and(|part| part == "$builtin_matrix_result")
        ));
        assert!(args[0].value.span.end < callee.span.start, "{source}");
    }
}

#[test]
fn parses_matrix_new_template_result_method_receivers_with_matrix_provenance() {
    for source in [
        "value = matrix.new<float>(2, 3, 1.5).rows()\n",
        "value = matrix.new<int>(2, 3, 1).columns()\n",
        "value = matrix.new<bool>(2, 3, true).elements_count()\n",
        "value = matrix.new<string>(1, 1, \"value\").get(0, 0)\n",
        "value = matrix.new<color>(1, 1, color.red).copy().get(0, 0)\n",
    ] {
        let parsed = parse(source);

        assert!(
            parsed.diagnostics.is_empty(),
            "{source}: {:?}",
            parsed.diagnostics
        );
        let StmtKind::Decl { value, .. } = &parsed.program.statements[0].kind else {
            panic!("expected declaration for {source}");
        };
        let ExprKind::Call { callee, args } = &value.kind else {
            panic!("expected call-result method call for {source}");
        };
        assert!(matches!(
            &callee.kind,
            ExprKind::QualifiedName(parts)
                if parts.first().is_some_and(|part| part == "$builtin_matrix_result")
        ));
        assert!(args[0].value.span.end < callee.span.start, "{source}");
    }
}

#[test]
fn parses_map_new_template_result_method_receivers_with_map_provenance() {
    for source in [
        "value = map.new<int,float>().size()\n",
        "value = map.new<float,bool>().get(1.5)\n",
        "value = map.new<bool,string>().contains(true)\n",
        "value = map.new<string,float>().put(\"key\", 1.0)\n",
        "value = map.new<string,float>().clear()\n",
        "value = map.new<string,float>().remove(\"key\")\n",
        "value = map.new<string,float>().put_all(map.new<string,float>())\n",
        "value = map.new<string,color>().copy().size()\n",
        "value = map.new<color,int>().copy().get(color.red)\n",
    ] {
        let parsed = parse(source);

        assert!(
            parsed.diagnostics.is_empty(),
            "{source}: {:?}",
            parsed.diagnostics
        );
        let StmtKind::Decl { value, .. } = &parsed.program.statements[0].kind else {
            panic!("expected declaration for {source}");
        };
        let ExprKind::Call { callee, args } = &value.kind else {
            panic!("expected call-result method call for {source}");
        };
        assert!(matches!(
            &callee.kind,
            ExprKind::QualifiedName(parts)
                if parts.first().is_some_and(|part| part == "$builtin_map_result")
        ));
        assert!(args[0].value.span.end < callee.span.start, "{source}");
    }
}

#[test]
fn parses_map_copy_result_method_receivers_with_map_provenance() {
    for source in [
        "value = map.copy(values).size()\n",
        "value = map.copy(values).get(1)\n",
        "value = map.copy(values).contains(key=1)\n",
        "value = map.copy(values).copy().size()\n",
    ] {
        let parsed = parse(source);

        assert!(
            parsed.diagnostics.is_empty(),
            "{source}: {:?}",
            parsed.diagnostics
        );
        let StmtKind::Decl { value, .. } = &parsed.program.statements[0].kind else {
            panic!("expected declaration for {source}");
        };
        let ExprKind::Call { callee, args } = &value.kind else {
            panic!("expected call-result method call for {source}");
        };
        assert!(matches!(
            &callee.kind,
            ExprKind::QualifiedName(parts)
                if parts.first().is_some_and(|part| part == "$builtin_map_result")
        ));
        assert!(args[0].value.span.end < callee.span.start, "{source}");
    }
}

#[test]
fn parses_map_call_result_keys_as_array_result_receivers() {
    for source in [
        "value = map.new<string,float>().keys().size()\n",
        "value = map.new<int,float>().copy().keys().copy().first()\n",
        "value = map.copy(values).keys().get(0)\n",
        "value = map.copy(values).copy().keys().copy().last()\n",
    ] {
        let parsed = parse(source);

        assert!(
            parsed.diagnostics.is_empty(),
            "{source}: {:?}",
            parsed.diagnostics
        );
        let StmtKind::Decl { value, .. } = &parsed.program.statements[0].kind else {
            panic!("expected declaration for {source}");
        };
        let ExprKind::Call { callee, args } = &value.kind else {
            panic!("expected call-result method call for {source}");
        };
        assert!(matches!(
            &callee.kind,
            ExprKind::QualifiedName(parts)
                if parts.first().is_some_and(|part| part == "$builtin_array_result")
        ));
        assert!(args[0].value.span.end < callee.span.start, "{source}");
    }
}

#[test]
fn parses_map_call_result_values_as_array_result_receivers() {
    for source in [
        "value = map.new<string,float>().values().size()\n",
        "value = map.new<int,string>().copy().values().copy().first()\n",
        "value = map.copy(values).values().get(0)\n",
        "value = map.copy(values).copy().values().copy().last()\n",
    ] {
        let parsed = parse(source);

        assert!(
            parsed.diagnostics.is_empty(),
            "{source}: {:?}",
            parsed.diagnostics
        );
        let StmtKind::Decl { value, .. } = &parsed.program.statements[0].kind else {
            panic!("expected declaration for {source}");
        };
        let ExprKind::Call { callee, args } = &value.kind else {
            panic!("expected call-result method call for {source}");
        };
        assert!(matches!(
            &callee.kind,
            ExprKind::QualifiedName(parts)
                if parts.first().is_some_and(|part| part == "$builtin_array_result")
        ));
        assert!(args[0].value.span.end < callee.span.start, "{source}");
    }
}

#[test]
fn rejects_methods_after_terminal_builtin_collection_result_reads() {
    for source in [
        "bad = array.from(Point.new(1)).get(0).size()\n",
        "bad = array.new<Point>(1, Point.new(1)).first().custom()\n",
        "bad = array.copy(values).last().custom()\n",
        "bad = array.new_int(1, 1).size().custom()\n",
        "bad = str.split(\"a,b\", \",\").size().custom()\n",
        "bad = ta.pivot_point_levels(\"Traditional\", true).last().custom()\n",
        "bad = matrix.row(values, 0).get(0).custom()\n",
        "bad = matrix.mult(values, array.from(1.0, 2.0)).size().custom()\n",
        "bad = array.from(1, 2).includes(2).custom()\n",
        "bad = array.from(1, 2).copy().includes(2).custom()\n",
        "bad = array.from(true, true).every().custom()\n",
        "bad = array.from(1, 2).copy().every().custom()\n",
        "bad = array.from(false, true).some().custom()\n",
        "bad = array.from(0, 1).copy().some().custom()\n",
        "bad = array.from(1, 2).join().custom()\n",
        "bad = array.from(1, 2).copy().join(\"|\").custom()\n",
        "bad = array.from(1, 2).clear().custom()\n",
        "bad = array.from(1, 2).reverse().custom()\n",
        "bad = array.from(1, 2).pop().custom()\n",
        "bad = array.from(1, 2).shift().custom()\n",
        "bad = array.from(1, 2).remove(0).custom()\n",
        "bad = array.from(1, 2).push(3).custom()\n",
        "bad = array.from(1, 2).unshift(0).custom()\n",
        "bad = array.from(1, 2).insert(1, 3).custom()\n",
        "bad = array.from(1, 2).set(1, 3).custom()\n",
        "bad = array.from(1, 2).fill(3).custom()\n",
        "bad = array.from(2, 1).sort().custom()\n",
        "bad = array.from(1, 2).indexof(2).custom()\n",
        "bad = array.from(1, 2).copy().indexof(2).custom()\n",
        "bad = array.from(1, 2, 1).lastindexof(1).custom()\n",
        "bad = array.from(1, 2, 1).copy().lastindexof(1).custom()\n",
        "bad = array.from(1, 2, 3).binary_search(2).custom()\n",
        "bad = array.from(1, 2, 3).copy().binary_search(2).custom()\n",
        "bad = array.from(1, 2, 3).binary_search_leftmost(2).custom()\n",
        "bad = array.from(1, 2, 3).copy().binary_search_leftmost(2).custom()\n",
        "bad = array.from(1, 2, 3).binary_search_rightmost(2).custom()\n",
        "bad = array.from(1, 2, 3).copy().binary_search_rightmost(2).custom()\n",
        "bad = array.from(1, 2, 3).min().custom()\n",
        "bad = array.from(1, 2, 3).copy().min(1).custom()\n",
        "bad = array.from(1, 2, 3).max().custom()\n",
        "bad = array.from(1, 2, 3).copy().max(1).custom()\n",
        "bad = array.from(1, 2, 3).sum().custom()\n",
        "bad = array.from(1, 2, 3).copy().sum().custom()\n",
        "bad = array.from(1, 2, 3).avg().custom()\n",
        "bad = array.from(1, 2, 3).copy().avg().custom()\n",
        "bad = array.from(1, 2, 3).range().custom()\n",
        "bad = array.from(1, 2, 3).copy().range().custom()\n",
        "bad = array.from(1, 2, 3).median().custom()\n",
        "bad = array.from(1, 2, 3).copy().median().custom()\n",
        "bad = array.from(1, 2, 2).mode().custom()\n",
        "bad = array.from(1, 2, 2).copy().mode().custom()\n",
        "bad = array.from(1, 2, 3).percentile_nearest_rank(50).custom()\n",
        "bad = array.from(1, 2, 3).copy().percentile_nearest_rank(50).custom()\n",
        "bad = array.from(1, 2, 3).percentile_linear_interpolation(50).custom()\n",
        "bad = array.from(1, 2, 3).copy().percentile_linear_interpolation(50).custom()\n",
        "bad = array.from(1, 2, 3).percentrank(1).custom()\n",
        "bad = array.from(1, 2, 3).copy().percentrank(1).custom()\n",
        "bad = array.from(1, 2, 3).covariance(array.from(2, 4, 6)).custom()\n",
        "bad = array.from(1, 2, 3).copy().covariance(array.from(2, 4, 6), false).custom()\n",
        "bad = array.from(1, 2, 3).variance().custom()\n",
        "bad = array.from(1, 2, 3).copy().variance(false).custom()\n",
        "bad = array.from(1, 2, 3).stdev().custom()\n",
        "bad = array.from(1, 2, 3).copy().stdev(false).custom()\n",
        "bad = matrix.mult(values, other).rows().custom()\n",
        "bad = matrix.new<float>(2, 2, 1.0).row(0).size().custom()\n",
        "bad = matrix.copy(values).row(0).first().custom()\n",
        "bad = matrix.new<float>(2, 2, 1.0).col(0).size().custom()\n",
        "bad = matrix.copy(values).col(0).first().custom()\n",
        "bad = matrix.mult(values, other).eigenvalues().size().custom()\n",
        "bad = matrix.copy(values).is_square().custom()\n",
        "bad = matrix.copy(values).is_zero().custom()\n",
        "bad = matrix.copy(values).is_binary().custom()\n",
        "bad = matrix.copy(values).is_diagonal().custom()\n",
        "bad = matrix.copy(values).is_identity().custom()\n",
        "bad = matrix.copy(values).is_symmetric().custom()\n",
        "bad = matrix.copy(values).is_antisymmetric().custom()\n",
        "bad = matrix.copy(values).is_stochastic().custom()\n",
        "bad = matrix.copy(values).sum().custom()\n",
        "bad = matrix.copy(values).avg().custom()\n",
        "bad = matrix.copy(values).min().custom()\n",
        "bad = matrix.copy(values).max().custom()\n",
        "bad = matrix.copy(values).mode().custom()\n",
        "bad = matrix.copy(values).trace().custom()\n",
        "bad = matrix.copy(values).det().custom()\n",
        "bad = matrix.copy(values).rank().custom()\n",
        "bad = matrix.copy(values).set(0, 0, 1.0).rows()\n",
        "bad = matrix.copy(values).fill(1.0).rows()\n",
        "bad = matrix.copy(values).reverse().rows()\n",
        "bad = matrix.copy(values).reshape(1, 1).rows()\n",
        "bad = matrix.copy(values).add_row(0, array.from(1.0, 2.0)).rows()\n",
        "bad = matrix.copy(values).add_col(0, array.from(1.0, 2.0)).rows()\n",
        "bad = matrix.copy(values).sort().rows()\n",
        "bad = matrix.copy(values).swap_rows(0, 1).rows()\n",
        "bad = matrix.copy(values).swap_columns(0, 1).rows()\n",
        "bad = matrix.copy(values).remove_row(0).rows()\n",
        "bad = matrix.copy(values).remove_col(0).rows()\n",
        "bad = map.keys(values).first().custom()\n",
        "bad = map.new<string, float>().size().custom()\n",
        "bad = map.new<string, float>().get(\"missing\").custom()\n",
        "bad = map.new<string, float>().contains(\"missing\").custom()\n",
        "bad = map.new<string, float>().put(\"key\", 1.0).custom()\n",
        "bad = map.new<string, float>().clear().custom()\n",
        "bad = map.new<string, float>().remove(\"key\").custom()\n",
        "bad = map.new<string, float>().put_all(map.new<string, float>()).custom()\n",
        "bad = map.copy(values).size().custom()\n",
        "bad = map.copy(values).get(1).custom()\n",
        "bad = map.copy(values).contains(1).custom()\n",
        "bad = map.new<string, float>().keys().size().custom()\n",
        "bad = map.copy(values).keys().first().custom()\n",
        "bad = map.new<string, float>().values().size().custom()\n",
        "bad = map.copy(values).values().first().custom()\n",
    ] {
        let parsed = parse(source);
        assert!(
            parsed
                .diagnostics
                .iter()
                .any(|diagnostic| diagnostic.code == "E_PARSE_EXPR"),
            "{source}: {:?}",
            parsed.diagnostics
        );
    }
}

#[test]
fn rejects_other_builtin_call_result_method_receivers() {
    for source in [
        "bad = array.size(values).size()\n",
        "bad = array.get(values, 0).size()\n",
        "bad = array.push(values, 1).size()\n",
        "bad = array.min(values).size()\n",
        "bad = str.length(\"value\").size()\n",
        "bad = ta.sma(close, 14).size()\n",
        "bad = map.size(values).size()\n",
        "bad = matrix.new<chart.point>(1, 1, chart.point.now(close)).rows()\n",
        "bad = map.new<chart.point, int>().size()\n",
        "bad = input.string(\"value\").size()\n",
        "bad = log.info(\"value\").size()\n",
    ] {
        let parsed = parse(source);

        assert!(parsed.diagnostics.iter().any(|diagnostic| {
                diagnostic.code == "E_PARSE_EXPR"
                && diagnostic.message.contains(
                    "method calls on call-result receivers require an unqualified call, qualified user-defined result, or supported built-in collection producer receiver",
                )
        }));
    }
}

#[test]
fn parses_matrix_new_template_call() {
    let parsed = parse("values = matrix.new<float>(2, 2, close)\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let StmtKind::Decl { value, .. } = &parsed.program.statements[0].kind else {
        panic!("expected declaration");
    };
    let ExprKind::Call { callee, args } = &value.kind else {
        panic!("expected call");
    };
    assert_eq!(
        callee.kind,
        ExprKind::Identifier("matrix.new<float>".to_owned())
    );
    assert_eq!(args.len(), 3);
}

#[test]
fn parses_deferred_matrix_new_template_call() {
    let parsed = parse("points = matrix.new<chart.point>(2, 2, chart.point.now(close))\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let StmtKind::Decl { value, .. } = &parsed.program.statements[0].kind else {
        panic!("expected declaration");
    };
    let ExprKind::Call { callee, args } = &value.kind else {
        panic!("expected call");
    };
    assert_eq!(
        callee.kind,
        ExprKind::Identifier("matrix.new<chart.point>".to_owned())
    );
    assert_eq!(args.len(), 3);
}

#[test]
fn parses_map_new_template_call() {
    let parsed = parse("values = map.new<string, float>()\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let StmtKind::Decl { value, .. } = &parsed.program.statements[0].kind else {
        panic!("expected declaration");
    };
    let ExprKind::Call { callee, args } = &value.kind else {
        panic!("expected call");
    };
    assert_eq!(
        callee.kind,
        ExprKind::Identifier("map.new<string,float>".to_owned())
    );
    assert_eq!(args.len(), 0);
}

#[test]
fn parses_dotted_map_new_template_call() {
    let parsed = parse("values = map.new<chart.point, chart.point>()\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let StmtKind::Decl { value, .. } = &parsed.program.statements[0].kind else {
        panic!("expected declaration");
    };
    let ExprKind::Call { callee, args } = &value.kind else {
        panic!("expected call");
    };
    assert_eq!(
        callee.kind,
        ExprKind::Identifier("map.new<chart.point,chart.point>".to_owned())
    );
    assert_eq!(args.len(), 0);
}

#[test]
fn parses_object_array_new_template_call() {
    let parsed = parse("labels = array.new<label>(1, label.new(bar_index, close))\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let StmtKind::Decl { value, .. } = &parsed.program.statements[0].kind else {
        panic!("expected declaration");
    };
    let ExprKind::Call { callee, args } = &value.kind else {
        panic!("expected call");
    };
    assert_eq!(
        callee.kind,
        ExprKind::Identifier("array.new_label".to_owned())
    );
    assert_eq!(args.len(), 2);
}

#[test]
fn parses_polyline_array_new_template_call() {
    let parsed = parse("paths = array.new<polyline>(1, polyline.new(points))\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let StmtKind::Decl { value, .. } = &parsed.program.statements[0].kind else {
        panic!("expected declaration");
    };
    let ExprKind::Call { callee, args } = &value.kind else {
        panic!("expected call");
    };
    assert_eq!(
        callee.kind,
        ExprKind::Identifier("array.new_polyline".to_owned())
    );
    assert_eq!(args.len(), 2);
}

#[test]
fn parses_chart_point_typed_declaration() {
    let parsed = parse("chart.point p = chart.point.now(close)\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let StmtKind::Decl {
        mode,
        declared_type,
        name,
        ..
    } = &parsed.program.statements[0].kind
    else {
        panic!("expected declaration");
    };
    assert_eq!(*mode, DeclMode::Normal);
    assert_eq!(
        declared_type_name(declared_type),
        Some("chart.point".to_owned())
    );
    assert_eq!(name, "p");
}

#[test]
fn parses_dotted_named_typed_declaration() {
    let parsed = parse("lib.Point p = lib.Point.new(close)\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let StmtKind::Decl {
        mode,
        declared_type,
        name,
        ..
    } = &parsed.program.statements[0].kind
    else {
        panic!("expected declaration");
    };
    assert_eq!(*mode, DeclMode::Normal);
    assert_eq!(
        declared_type_name(declared_type),
        Some("lib.Point".to_owned())
    );
    assert_eq!(name, "p");
}

#[test]
fn parses_var_chart_point_typed_declaration() {
    let parsed = parse("var chart.point p = na\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let StmtKind::Decl {
        mode,
        declared_type,
        name,
        ..
    } = &parsed.program.statements[0].kind
    else {
        panic!("expected declaration");
    };
    assert_eq!(*mode, DeclMode::Var);
    assert_eq!(
        declared_type_name(declared_type),
        Some("chart.point".to_owned())
    );
    assert_eq!(name, "p");
}

#[test]
fn parses_scalar_typed_declaration() {
    let parsed = parse("float price = close\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let StmtKind::Decl {
        mode,
        declared_type,
        name,
        ..
    } = &parsed.program.statements[0].kind
    else {
        panic!("expected declaration");
    };
    assert_eq!(*mode, DeclMode::Normal);
    assert_eq!(declared_type_name(declared_type), Some("float".to_owned()));
    assert_eq!(name, "price");
}

#[test]
fn parses_array_typed_declaration() {
    let parsed = parse("array<float> prices = array.new_float()\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let StmtKind::Decl {
        mode,
        declared_type,
        name,
        ..
    } = &parsed.program.statements[0].kind
    else {
        panic!("expected declaration");
    };
    assert_eq!(*mode, DeclMode::Normal);
    assert_eq!(
        declared_type_name(declared_type),
        Some("array<float>".to_owned())
    );
    assert_eq!(name, "prices");
}

#[test]
fn parses_dotted_array_typed_declaration() {
    let parsed = parse("array<chart.point> points = array.new<chart.point>()\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let StmtKind::Decl {
        mode,
        declared_type,
        name,
        ..
    } = &parsed.program.statements[0].kind
    else {
        panic!("expected declaration");
    };
    assert_eq!(*mode, DeclMode::Normal);
    assert_eq!(
        declared_type_name(declared_type),
        Some("array<chart.point>".to_owned())
    );
    assert_eq!(name, "points");
}

#[test]
fn parses_polyline_array_typed_declaration() {
    let parsed = parse("array<polyline> paths = array.new<polyline>()\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let StmtKind::Decl {
        mode,
        declared_type,
        name,
        ..
    } = &parsed.program.statements[0].kind
    else {
        panic!("expected declaration");
    };
    assert_eq!(*mode, DeclMode::Normal);
    assert_eq!(
        declared_type_name(declared_type),
        Some("array<polyline>".to_owned())
    );
    assert_eq!(name, "paths");
}

#[test]
fn parses_matrix_typed_declaration() {
    let parsed = parse("matrix<float> values = matrix.new<float>(1, 1)\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let StmtKind::Decl {
        mode,
        declared_type,
        name,
        ..
    } = &parsed.program.statements[0].kind
    else {
        panic!("expected declaration");
    };
    assert_eq!(*mode, DeclMode::Normal);
    assert_eq!(
        declared_type_name(declared_type),
        Some("matrix<float>".to_owned())
    );
    assert_eq!(name, "values");
}

#[test]
fn parses_map_typed_declaration() {
    let parsed = parse("map<string, float> values = na\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let StmtKind::Decl {
        mode,
        declared_type,
        name,
        ..
    } = &parsed.program.statements[0].kind
    else {
        panic!("expected declaration");
    };
    assert_eq!(*mode, DeclMode::Normal);
    assert_eq!(
        declared_type_name(declared_type),
        Some("map<string,float>".to_owned())
    );
    assert_eq!(name, "values");
}

#[test]
fn parses_array_type_alias_declaration() {
    let parsed = parse("float[] prices = array.new_float()\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let StmtKind::Decl {
        mode,
        declared_type,
        name,
        ..
    } = &parsed.program.statements[0].kind
    else {
        panic!("expected declaration");
    };
    assert_eq!(*mode, DeclMode::Normal);
    assert_eq!(
        declared_type_name(declared_type),
        Some("array<float>".to_owned())
    );
    assert_eq!(name, "prices");
}

#[test]
fn parses_var_array_type_alias_declaration() {
    let parsed = parse("var float[] prices = array.new_float()\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let StmtKind::Decl {
        mode,
        declared_type,
        name,
        ..
    } = &parsed.program.statements[0].kind
    else {
        panic!("expected declaration");
    };
    assert_eq!(*mode, DeclMode::Var);
    assert_eq!(
        declared_type_name(declared_type),
        Some("array<float>".to_owned())
    );
    assert_eq!(name, "prices");
}

#[test]
fn parses_varip_array_type_alias_declaration() {
    let parsed = parse("varip int[] counts = array.new_int()\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let StmtKind::Decl {
        mode,
        declared_type,
        name,
        ..
    } = &parsed.program.statements[0].kind
    else {
        panic!("expected declaration");
    };
    assert_eq!(*mode, DeclMode::Varip);
    assert_eq!(
        declared_type_name(declared_type),
        Some("array<int>".to_owned())
    );
    assert_eq!(name, "counts");
}

#[test]
fn parses_dotted_array_type_alias_declaration() {
    let parsed = parse("chart.point[] points = array.new<chart.point>()\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let StmtKind::Decl {
        mode,
        declared_type,
        name,
        ..
    } = &parsed.program.statements[0].kind
    else {
        panic!("expected declaration");
    };
    assert_eq!(*mode, DeclMode::Normal);
    assert_eq!(
        declared_type_name(declared_type),
        Some("array<chart.point>".to_owned())
    );
    assert_eq!(name, "points");
}

#[test]
fn canonicalizes_array_template_and_alias_declarations() {
    for source in [
        "array < float > prices = array.new_float()\n",
        "float [] prices = array.new_float()\n",
    ] {
        let parsed = parse(source);

        assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
        assert_eq!(
            first_declared_type(&parsed),
            Some("array<float>".to_owned())
        );
    }
}

#[test]
fn canonicalizes_dotted_array_template_and_alias_declarations() {
    for source in [
        "array < chart.point > points = array.new<chart.point>()\n",
        "chart.point [] points = array.new<chart.point>()\n",
    ] {
        let parsed = parse(source);

        assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
        assert_eq!(
            first_declared_type(&parsed),
            Some("array<chart.point>".to_owned())
        );
    }
}

#[test]
fn parses_unknown_typed_declaration_for_semantic_diagnostic() {
    let parsed = parse("line id = na\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let StmtKind::Decl {
        declared_type,
        name,
        ..
    } = &parsed.program.statements[0].kind
    else {
        panic!("expected declaration");
    };
    assert_eq!(declared_type_name(declared_type), Some("line".to_owned()));
    assert_eq!(name, "id");
}

#[test]
fn parses_array_new_comparison_without_template_rewrite() {
    let parsed = parse("is_less = array.new < close\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let StmtKind::Decl { value, .. } = &parsed.program.statements[0].kind else {
        panic!("expected declaration");
    };
    assert!(matches!(
        value.kind,
        ExprKind::Binary {
            op: BinaryOp::Lt,
            ..
        }
    ));
}

#[test]
fn parses_reassignment() {
    let parsed = parse("x := x + 1\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    assert!(matches!(
        parsed.program.statements[0].kind,
        StmtKind::Reassign { .. }
    ));
}

#[test]
fn desugars_compound_assignments_to_reassignment_expressions() {
    for (source, expected_op) in [
        ("value += 1\n", BinaryOp::Add),
        ("value -= 1\n", BinaryOp::Sub),
        ("value *= 1\n", BinaryOp::Mul),
        ("value /= 1\n", BinaryOp::Div),
        ("value %= 1\n", BinaryOp::Mod),
    ] {
        let parsed = parse(source);

        assert!(
            parsed.diagnostics.is_empty(),
            "{source}: {:?}",
            parsed.diagnostics
        );
        let StmtKind::Reassign { name, value } = &parsed.program.statements[0].kind else {
            panic!("expected reassignment for {source}");
        };
        assert_eq!(name, "value");
        assert!(matches!(
            &value.kind,
            ExprKind::Binary { op, left, right }
                if *op == expected_op
                    && matches!(&left.kind, ExprKind::Identifier(name) if name == "value")
                    && matches!(right.kind, ExprKind::Literal(Literal::Int(1)))
        ));
    }
}

#[test]
fn recovers_after_bad_declaration() {
    let parsed = parse("x =\ny = close\n");

    assert_eq!(parsed.program.statements.len(), 1);
    assert!(!parsed.diagnostics.is_empty());
    assert!(matches!(
        parsed.program.statements[0].kind,
        StmtKind::Decl { .. }
    ));
}

#[test]
fn parses_tuple_declaration() {
    let parsed = parse("[macd, signal, hist] = ta.macd(close, 12, 26, 9)\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    assert!(matches!(
        parsed.program.statements[0].kind,
        StmtKind::TupleDecl { .. }
    ));
}

#[test]
fn parses_tuple_expression() {
    let parsed = parse("x = [close, open]\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    assert!(matches!(
        parsed.program.statements[0].kind,
        StmtKind::Decl { .. }
    ));
}

#[test]
fn parses_if_statement() {
    let parsed = parse("if close > open\n    plot(close)\nelse\n    plot(open)\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    assert_eq!(parsed.program.statements.len(), 1);
    let StmtKind::If {
        then_branch,
        else_branch,
        ..
    } = &parsed.program.statements[0].kind
    else {
        panic!("expected if statement");
    };
    assert_eq!(then_branch.len(), 1);
    assert_eq!(else_branch.len(), 1);
}

#[test]
fn parses_if_expression_declaration() {
    let parsed = parse("x = if close > open\n    high\nelse\n    low\nplot(x)\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let StmtKind::Decl { value, .. } = &parsed.program.statements[0].kind else {
        panic!("expected declaration");
    };
    let ExprKind::If {
        condition,
        then_branch,
        else_branch,
    } = &value.kind
    else {
        panic!("expected if expression");
    };
    assert!(matches!(condition.kind, ExprKind::Binary { .. }));
    assert_eq!(then_branch.len(), 1);
    assert_eq!(else_branch.len(), 1);
    assert!(matches!(then_branch[0].kind, StmtKind::Expr(_)));
    assert!(matches!(else_branch[0].kind, StmtKind::Expr(_)));
}

#[test]
fn rejects_if_expression_without_else() {
    let parsed = parse("x = if close > open\n    high\nplot(x)\n");

    assert!(
        parsed
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_PARSE_IF_EXPR"),
        "{:?}",
        parsed.diagnostics
    );
}

#[test]
fn parses_function_declaration() {
    let parsed = parse("double(x) => x * 2\nplot(close)\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    assert_eq!(parsed.program.statements.len(), 2);
    let StmtKind::Function { name, params, .. } = &parsed.program.statements[0].kind else {
        panic!("expected function statement");
    };
    assert_eq!(name, "double");
    assert_eq!(params.len(), 1);
    assert_eq!(params[0].name, "x");
    assert_eq!(params[0].type_name, None);
}

#[test]
fn parses_typed_function_parameters() {
    let parsed = parse(
        "pass(chart.point point, int offset, array<int> values, float[] weights, array<chart.point> points, line[] lines) => point.index + offset + array.get(values, 0) + array.get(weights, 0) + array.size(points) + array.size(lines)\n",
    );

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let StmtKind::Function { name, params, .. } = &parsed.program.statements[0].kind else {
        panic!("expected function statement");
    };
    assert_eq!(name, "pass");
    assert_eq!(params.len(), 6);
    assert_eq!(params[0].type_name.as_deref(), Some("chart.point"));
    assert_eq!(params[0].name, "point");
    assert_eq!(params[1].type_name.as_deref(), Some("int"));
    assert_eq!(params[1].name, "offset");
    assert_eq!(params[2].type_name.as_deref(), Some("array<int>"));
    assert_eq!(params[2].name, "values");
    assert_eq!(params[3].type_name.as_deref(), Some("array<float>"));
    assert_eq!(params[3].name, "weights");
    assert_eq!(params[4].type_name.as_deref(), Some("array<chart.point>"));
    assert_eq!(params[4].name, "points");
    assert_eq!(params[5].type_name.as_deref(), Some("array<line>"));
    assert_eq!(params[5].name, "lines");
}

#[test]
fn parses_typed_method_parameters() {
    let parsed = parse(
        "method pass(Point p, array<Point> values, Point[] aliases, array<lib.Point> imported, lib.Point[] imported_aliases) => p.x + array.size(values) + array.size(aliases) + array.size(imported) + array.size(imported_aliases)\n",
    );

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let StmtKind::Method(method) = &parsed.program.statements[0].kind else {
        panic!("expected method statement");
    };
    assert_eq!(method.name, "pass");
    assert_eq!(method.params.len(), 5);
    assert_eq!(method.params[0].type_name, "Point");
    assert_eq!(method.params[0].name, "p");
    assert_eq!(method.params[1].type_name, "array<Point>");
    assert_eq!(method.params[1].name, "values");
    assert_eq!(method.params[2].type_name, "array<Point>");
    assert_eq!(method.params[2].name, "aliases");
    assert_eq!(method.params[3].type_name, "array<lib.Point>");
    assert_eq!(method.params[3].name, "imported");
    assert_eq!(method.params[4].type_name, "array<lib.Point>");
    assert_eq!(method.params[4].name, "imported_aliases");
}

#[test]
fn parses_block_function_declaration() {
    let parsed = parse("double(x) =>\n    y = x * 2\n    y\nplot(close)\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    assert_eq!(parsed.program.statements.len(), 2);
    let StmtKind::Function { body, .. } = &parsed.program.statements[0].kind else {
        panic!("expected function statement");
    };
    let FunctionBody::Block(statements) = body else {
        panic!("expected block function body");
    };
    assert_eq!(statements.len(), 2);
}

#[test]
fn parses_for_statement() {
    let parsed = parse("for i = 0 to 10\n    plot(close)\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    assert_eq!(parsed.program.statements.len(), 1);
    let StmtKind::For {
        counter,
        from,
        to,
        step,
        body,
    } = &parsed.program.statements[0].kind
    else {
        panic!("expected for statement");
    };
    assert_eq!(counter, "i");
    assert!(matches!(from.kind, ExprKind::Literal(Literal::Int(0))));
    assert!(matches!(to.kind, ExprKind::Literal(Literal::Int(10))));
    assert!(step.is_none());
    assert_eq!(body.len(), 1);
}

#[test]
fn parses_for_statement_with_step() {
    let parsed = parse("for i = 0 to 10 by 2\n    plot(close)\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    assert_eq!(parsed.program.statements.len(), 1);
    let StmtKind::For { step, .. } = &parsed.program.statements[0].kind else {
        panic!("expected for statement");
    };
    let Some(step) = step else {
        panic!("expected for step");
    };
    assert!(matches!(step.kind, ExprKind::Literal(Literal::Int(2))));
}

#[test]
fn parses_while_statement() {
    let parsed = parse("while close > open\n    plot(close)\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    assert_eq!(parsed.program.statements.len(), 1);
    let StmtKind::While { condition, body } = &parsed.program.statements[0].kind else {
        panic!("expected while statement");
    };
    assert!(matches!(condition.kind, ExprKind::Binary { .. }));
    assert_eq!(body.len(), 1);
}

#[test]
fn parses_for_expression_declaration() {
    let parsed = parse("x = for i = 0 to 2\n    i * 2\nplot(x)\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let StmtKind::Decl { value, .. } = &parsed.program.statements[0].kind else {
        panic!("expected declaration");
    };
    let ExprKind::For { counter, body, .. } = &value.kind else {
        panic!("expected for expression");
    };
    assert_eq!(counter, "i");
    assert_eq!(body.len(), 1);
    assert!(matches!(body[0].kind, StmtKind::Expr(_)));
}

#[test]
fn parses_for_in_expression_declaration() {
    let parsed = parse("x = for value in values\n    value + 1\nplot(x)\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let StmtKind::Decl { value, .. } = &parsed.program.statements[0].kind else {
        panic!("expected declaration");
    };
    let ExprKind::ForIn {
        index,
        value: loop_value,
        body,
        ..
    } = &value.kind
    else {
        panic!("expected for-in expression");
    };
    assert_eq!(index, &None);
    assert_eq!(loop_value, "value");
    assert_eq!(body.len(), 1);
    assert!(matches!(body[0].kind, StmtKind::Expr(_)));
}

#[test]
fn parses_for_in_expression_index_value_declaration() {
    let parsed = parse("x = for index, value in values\n    index + value\nplot(x)\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let StmtKind::Decl { value, .. } = &parsed.program.statements[0].kind else {
        panic!("expected declaration");
    };
    let ExprKind::ForIn {
        index,
        value: loop_value,
        body,
        ..
    } = &value.kind
    else {
        panic!("expected for-in expression");
    };
    assert_eq!(index.as_deref(), Some("index"));
    assert_eq!(loop_value, "value");
    assert_eq!(body.len(), 1);
    assert!(matches!(body[0].kind, StmtKind::Expr(_)));
}

#[test]
fn parses_for_in_expression_bracket_pair_declaration() {
    let parsed = parse("x = for [key, value] in values\n    value\nplot(x)\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let StmtKind::Decl { value, .. } = &parsed.program.statements[0].kind else {
        panic!("expected declaration");
    };
    let ExprKind::ForIn {
        index,
        value: loop_value,
        body,
        ..
    } = &value.kind
    else {
        panic!("expected for-in expression");
    };
    assert_eq!(index.as_deref(), Some("key"));
    assert_eq!(loop_value, "value");
    assert_eq!(body.len(), 1);
    assert!(matches!(body[0].kind, StmtKind::Expr(_)));
}

#[test]
fn parses_condition_switch_expression_declaration() {
    let parsed = parse(
        "x = switch\n    close > open => high\n    close < open => low\n    => close\nplot(x)\n",
    );

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let StmtKind::Decl { value, .. } = &parsed.program.statements[0].kind else {
        panic!("expected declaration");
    };
    let ExprKind::Switch { selector, arms } = &value.kind else {
        panic!("expected switch expression");
    };
    assert!(selector.is_none());
    assert_eq!(arms.len(), 3);
    assert!(arms[0].condition.is_some());
    assert!(arms[2].condition.is_none());
}

#[test]
fn parses_selector_switch_expression_declaration() {
    let parsed = parse("x = switch direction\n    1 => high\n    -1 => low\n    => close\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let StmtKind::Decl { value, .. } = &parsed.program.statements[0].kind else {
        panic!("expected declaration");
    };
    let ExprKind::Switch { selector, arms } = &value.kind else {
        panic!("expected switch expression");
    };
    assert!(selector.is_some());
    assert_eq!(arms.len(), 3);
}

#[test]
fn parses_while_expression() {
    let parsed = parse("x = while close > open\n    close\nplot(x)\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let StmtKind::Decl { value, .. } = &parsed.program.statements[0].kind else {
        panic!("expected declaration");
    };
    let ExprKind::While { condition, body } = &value.kind else {
        panic!("expected while expression AST");
    };
    assert!(matches!(condition.kind, ExprKind::Binary { .. }));
    assert_eq!(body.len(), 1);
    assert!(matches!(body[0].kind, StmtKind::Expr(_)));
}

#[test]
fn parses_condition_switch_statement_block_arm() {
    let parsed = parse("x = switch\n    close > open =>\n        high\n    => close\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let StmtKind::Decl { value, .. } = &parsed.program.statements[0].kind else {
        panic!("expected declaration");
    };
    let ExprKind::Switch { arms, .. } = &value.kind else {
        panic!("expected switch expression");
    };
    assert!(matches!(arms[0].result, SwitchArmResult::Block(_)));
    assert!(matches!(arms[1].result, SwitchArmResult::Expr(_)));
}

#[test]
fn parses_selector_switch_statement_block_arm() {
    let parsed = parse("x = switch direction\n    1 =>\n        high\n    => close\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let StmtKind::Decl { value, .. } = &parsed.program.statements[0].kind else {
        panic!("expected declaration");
    };
    let ExprKind::Switch { arms, .. } = &value.kind else {
        panic!("expected switch expression");
    };
    assert!(matches!(arms[0].result, SwitchArmResult::Block(_)));
    assert!(matches!(arms[1].result, SwitchArmResult::Expr(_)));
}

#[test]
fn parses_default_statement_block_switch_arm() {
    let parsed = parse("x = switch\n    close > open => high\n    =>\n        close\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let StmtKind::Decl { value, .. } = &parsed.program.statements[0].kind else {
        panic!("expected declaration");
    };
    let ExprKind::Switch { arms, .. } = &value.kind else {
        panic!("expected switch expression");
    };
    assert!(matches!(arms[0].result, SwitchArmResult::Expr(_)));
    assert!(matches!(arms[1].result, SwitchArmResult::Block(_)));
}

#[test]
fn rejects_expression_nesting_past_depth_limit() {
    let depth = 257;
    let source = format!("x = {}close{}\n", "(".repeat(depth), ")".repeat(depth));
    let parsed = parse(&source);

    assert!(
        parsed
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_PARSE_EXPR_DEPTH"),
        "{:?}",
        parsed.diagnostics
    );
}

#[test]
fn parses_loop_control_statements() {
    let parsed = parse("for i = 0 to 10\n    if i == 2\n        break\n    continue\n");

    assert!(parsed.diagnostics.is_empty(), "{:?}", parsed.diagnostics);
    let StmtKind::For { body, .. } = &parsed.program.statements[0].kind else {
        panic!("expected for statement");
    };
    let StmtKind::If { then_branch, .. } = &body[0].kind else {
        panic!("expected if statement");
    };
    assert!(matches!(then_branch[0].kind, StmtKind::Break));
    assert!(matches!(body[1].kind, StmtKind::Continue));
}
