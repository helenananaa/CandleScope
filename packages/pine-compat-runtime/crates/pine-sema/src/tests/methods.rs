use super::*;

#[test]
fn accepts_pure_user_method_on_local_udt() {
    let analysis = analyze(
        r#"type Point
    float x
method shift(Point p, float delta) => p.x + delta
p = Point.new(close)
plot(p.shift(2))
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| feature.feature == "user-defined methods")
    );
}

#[test]
fn accepts_udt_receiver_passthrough_user_method_return_and_history_read() {
    let analysis = analyze(
        r#"type Point
    float x
    float y
method keep(Point p) => p
p = Point.new(close, open)
same = p.keep()
prior = same[1]
plot(prior.x + prior.y)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_receiver_block_alias_user_method_return() {
    let analysis = analyze(
        r#"type Point
    float x
    float y
method keepBlock(Point p) =>
    copy = p
    copy
p = Point.new(close, open)
same = p.keepBlock()
plot(same.x + same.y)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_parameter_passthrough_user_method_return() {
    let analysis = analyze(
        r#"type Point
    float x
    float y
method choose(Point p, Point other) => other
p = Point.new(close, open)
q = Point.new(open, close)
same = p.choose(q)
plot(same.x + same.y)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_parameter_block_alias_user_method_return() {
    let analysis = analyze(
        r#"type Point
    float x
    float y
method chooseBlock(Point p, Point other) =>
    copy = other
    copy
p = Point.new(close, open)
q = Point.new(open, close)
same = p.chooseBlock(q)
plot(same.x + same.y)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_ternary_alias_return_from_user_method_receiver_and_param() {
    let analysis = analyze(
        r#"type Point
    float x
method keepTernary(Point p, bool flip) =>
    copy = p
    flip ? copy : p
method chooseTernary(Point p, Point other, bool flip) =>
    copy = other
    flip ? copy : other
p = Point.new(close)
q = Point.new(open)
same = p.keepTernary(bar_index % 2 == 0)
chosen = p.chooseTernary(q, bar_index % 2 == 0)
plot(same.x + chosen.x)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_nested_udt_parameter_passthrough_user_method_return() {
    let analysis = analyze(
        r#"type Point
    float x
    float y
method choose(Point p, Point other) => other
method wrap(Point p, Point other) => p.choose(other)
p = Point.new(close, open)
q = Point.new(open, close)
same = p.wrap(q)
plot(same.x + same.y)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_nested_udt_user_method_return_history_read() {
    let analysis = analyze(
        r#"type Point
    float x
type Wrapper
    Point point
method toWrapper(Point p) => Wrapper.new(p)
method keep(Wrapper w) => w
p = Point.new(close)
made = p.toWrapper()
same = made.keep()
prior = same[1]
plot(prior.point.x)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_constructor_return_from_user_method_and_history_read() {
    let analysis = analyze(
        r#"type Point
    float x
    float y
method clone(Point p) => Point.new(p.x, p.y)
p = Point.new(close, open)
copy = p.clone()
prior = copy[1]
plot(prior.x + prior.y)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_constructor_return_from_user_method_udt_param_fields() {
    let analysis = analyze(
        r#"type Point
    float x
    float y
method cloneOther(Point p, Point other) => Point.new(other.x, other.y)
p = Point.new(close, open)
q = Point.new(open, close)
copy = p.cloneOther(q)
plot(copy.x + copy.y)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_named_constructor_return_from_user_method_udt_param_fields() {
    let analysis = analyze(
        r#"type Point
    float x
    float y
method cloneOtherNamed(Point p, Point other) => Point.new(y=other.y, x=other.x)
p = Point.new(close, open)
q = Point.new(open, close)
copy = p.cloneOtherNamed(q)
plot(copy.x + copy.y)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_constructor_return_from_user_method_udt_param_field_aliases() {
    let analysis = analyze(
        r#"type Point
    float x
    float y
method cloneOtherAlias(Point p, Point other) =>
    ox = other.x
    oy = other.y
    Point.new(ox, oy)
p = Point.new(close, open)
q = Point.new(open, close)
copy = p.cloneOtherAlias(q)
plot(copy.x + copy.y)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_named_constructor_return_from_user_method_udt_param_field_aliases() {
    let analysis = analyze(
        r#"type Point
    float x
    float y
method cloneOtherAlias(Point p, Point other) =>
    ox = other.x
    oy = other.y
    Point.new(y=oy, x=ox)
p = Point.new(close, open)
q = Point.new(open, close)
copy = p.cloneOtherAlias(q)
plot(copy.x + copy.y)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_constructor_return_from_user_method_receiver_block_alias_fields() {
    let analysis = analyze(
        r#"type Point
    float x
    float y
method cloneAlias(Point p) =>
    copy = p
    Point.new(copy.x, copy.y)
p = Point.new(close, open)
made = p.cloneAlias()
plot(made.x + made.y)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_named_constructor_return_from_user_method_udt_param_block_alias_fields() {
    let analysis = analyze(
        r#"type Point
    float x
    float y
method cloneOtherAlias(Point p, Point other) =>
    copy = other
    Point.new(y=copy.y, x=copy.x)
p = Point.new(close, open)
q = Point.new(open, close)
made = p.cloneOtherAlias(q)
plot(made.x + made.y)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_nested_constructor_return_from_user_method_receiver_fields() {
    let analysis = analyze(
        r#"type Point
    float x
    float y
make(x, y) => Point.new(x, y)
method cloneViaMake(Point p) => make(p.x, p.y)
p = Point.new(close, open)
made = p.cloneViaMake()
plot(made.x + made.y)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_named_nested_constructor_return_from_user_method_udt_param_fields() {
    let analysis = analyze(
        r#"type Point
    float x
    float y
makeNamed(x, y) => Point.new(y=y, x=x)
method cloneOtherViaMake(Point p, Point other) => makeNamed(other.x, other.y)
p = Point.new(close, open)
q = Point.new(open, close)
made = p.cloneOtherViaMake(q)
plot(made.x + made.y)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_ternary_constructor_return_from_user_method_receiver_fields() {
    let analysis = analyze(
        r#"type Point
    float x
method cloneTernary(Point p, bool flip) => flip ? Point.new(p.x) : Point.new(p.x + 10)
p = Point.new(close)
made = p.cloneTernary(bar_index < 2)
plot(made.x + close)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_ternary_constructor_return_from_user_method_udt_param_fields() {
    let analysis = analyze(
        r#"type Point
    float x
method cloneOtherTernary(Point p, Point other, bool flip) => flip ? Point.new(other.x) : Point.new(other.x + 10)
p = Point.new(close)
q = Point.new(open)
made = p.cloneOtherTernary(q, bar_index < 2)
plot(made.x + close)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_switch_constructor_return_from_user_method_receiver_fields() {
    let analysis = analyze(
        r#"type Point
    float x
method cloneSwitch(Point p, int mode) =>
    switch mode
        0 => Point.new(p.x)
        => Point.new(p.x + 10)
p = Point.new(close)
made = p.cloneSwitch(bar_index)
plot(made.x + close)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_switch_constructor_return_from_user_method_udt_param_fields() {
    let analysis = analyze(
        r#"type Point
    float x
method cloneOtherSwitch(Point p, Point other, int mode) =>
    switch mode
        0 => Point.new(other.x)
        => Point.new(other.x + 10)
p = Point.new(close)
q = Point.new(open)
made = p.cloneOtherSwitch(q, bar_index)
plot(made.x + close)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_final_if_constructor_return_from_user_method_receiver_fields() {
    let analysis = analyze(
        r#"type Point
    float x
method cloneIf(Point p, bool flip) =>
    if flip
        Point.new(p.x)
    else
        Point.new(p.x + 10)
p = Point.new(close)
made = p.cloneIf(bar_index < 2)
plot(made.x + close)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_final_if_constructor_return_from_user_method_udt_param_fields() {
    let analysis = analyze(
        r#"type Point
    float x
method cloneOtherIf(Point p, Point other, bool flip) =>
    if flip
        Point.new(other.x)
    else
        Point.new(other.x + 10)
p = Point.new(close)
q = Point.new(open)
made = p.cloneOtherIf(q, bar_index < 2)
plot(made.x + close)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_final_if_branch_alias_constructor_return_from_user_method_receiver_fields() {
    let analysis = analyze(
        r#"type Point
    float x
method cloneIf(Point p, bool flip) =>
    if flip
        ax = p.x + 1
        Point.new(ax)
    else
        ax = p.x + 10
        Point.new(ax)
p = Point.new(close)
made = p.cloneIf(bar_index < 2)
plot(made.x + close)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_final_if_branch_udt_alias_return_from_user_method_receiver() {
    let analysis = analyze(
        r#"type Point
    float x
method cloneIf(Point p, bool flip) =>
    if flip
        q = p
        q
    else
        q = p
        q
p = Point.new(close)
made = p.cloneIf(bar_index < 2)
plot(made.x + close)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_final_for_constructor_return_from_user_method_receiver_fields() {
    let analysis = analyze(
        r#"type Point
    float x
method cloneFor(Point p, int count) =>
    for i = 0 to count
        Point.new(p.x + i)
p = Point.new(close)
made = p.cloneFor(2)
plot(made.x + close)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_final_for_constructor_return_from_user_method_udt_param_fields() {
    let analysis = analyze(
        r#"type Point
    float x
method cloneOtherFor(Point p, Point other, int count) =>
    for i = 0 to count
        Point.new(other.x + i)
p = Point.new(close)
q = Point.new(open)
made = p.cloneOtherFor(q, 2)
plot(made.x + close)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_final_for_udt_alias_return_from_user_method_receiver() {
    let analysis = analyze(
        r#"type Point
    float x
method cloneFor(Point p, int count) =>
    for i = 0 to count
        q = p
        q
p = Point.new(close)
made = p.cloneFor(2)
plot(made.x + close)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_final_while_udt_alias_return_from_user_method_receiver() {
    let analysis = analyze(
        r#"type Point
    float x
method cloneWhile(Point p, bool keepGoing) =>
    active = keepGoing
    while active
        q = p
        active := false
        q
p = Point.new(close)
made = p.cloneWhile(close > 0)
plot(made.x + close)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_switch_udt_alias_return_from_user_method_receiver() {
    let analysis = analyze(
        r#"type Point
    float x
method cloneSwitch(Point p, int selector) =>
    switch selector
        0 =>
            q = p
            q
        =>
            q = p
            q
p = Point.new(close)
made = p.cloneSwitch(bar_index % 2)
plot(made.x + close)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_constructor_return_from_user_method_scalar_param() {
    let analysis = analyze(
        r#"type Point
    float x
method make(Point p, float x) => Point.new(x)
p = Point.new(close)
made = p.make(open)
plot(made.x + close)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_constructor_return_from_user_method_scalar_alias() {
    let analysis = analyze(
        r#"type Point
    float x
method makeBlock(Point p, float x) =>
    ax = x
    Point.new(ax)
p = Point.new(close)
made = p.makeBlock(open)
plot(made.x + close)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_named_constructor_return_from_user_method() {
    let analysis = analyze(
        r#"type Point
    float x
    float y
method make(Point p, float x, float y) => Point.new(y=y, x=x)
p = Point.new(close, open)
made = p.make(close, open)
plot(made.x + made.y)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_named_constructor_return_from_user_method_scalar_alias() {
    let analysis = analyze(
        r#"type Point
    float x
method makeNamedBlock(Point p, float x) =>
    ax = x
    Point.new(x=ax)
p = Point.new(close)
made = p.makeNamedBlock(open)
plot(made.x + close)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_typed_local_return_from_user_method() {
    let analysis = analyze(
        r#"type Point
    float x
method makeTyped(Point p, float x) =>
    Point made = na
    made := Point.new(x)
    made
p = Point.new(close)
made = p.makeTyped(open)
plot(made.x + close)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_typed_local_return_from_user_method_aliases() {
    let analysis = analyze(
        r#"type Point
    float x
method makeTyped(Point p, Point other) =>
    copy = p
    otherCopy = other
    px = copy.x
    ox = otherCopy.x
    Point made = na
    made := Point.new(x=px + ox)
    made
p = Point.new(close)
q = Point.new(open)
made = p.makeTyped(q)
plot(made.x + close)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_typed_constructor_local_return_from_user_method() {
    let analysis = analyze(
        r#"type Point
    float x
method makeTyped(Point p, float x) =>
    Point made = Point.new(x)
    made := Point.new(x + 1)
    made
p = Point.new(close)
made = p.makeTyped(open)
plot(made.x + close)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_typed_constructor_local_return_from_user_method_aliases() {
    let analysis = analyze(
        r#"type Point
    float x
method makeTyped(Point p, Point other) =>
    copy = p
    otherCopy = other
    px = copy.x
    ox = otherCopy.x
    Point made = Point.new(x=px + ox)
    made := Point.new(x=made.x + 1)
    made
p = Point.new(close)
q = Point.new(open)
made = p.makeTyped(q)
plot(made.x + close)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_typed_ternary_local_return_from_user_method() {
    let analysis = analyze(
        r#"type Point
    float x
method makeTyped(Point p, float x, bool flip) =>
    Point made = flip ? Point.new(x) : Point.new(x + 1)
    made := flip ? Point.new(made.x + 2) : Point.new(made.x + 3)
    made
p = Point.new(close)
made = p.makeTyped(open, bar_index < 2)
plot(made.x + close)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_typed_ternary_local_return_from_user_method_aliases() {
    let analysis = analyze(
        r#"type Point
    float x
method makeTyped(Point p, Point other, bool flip) =>
    copy = p
    otherCopy = other
    px = copy.x
    ox = otherCopy.x
    Point made = flip ? Point.new(x=px) : Point.new(x=ox + 1)
    made := flip ? Point.new(x=made.x + 2) : Point.new(x=made.x + 3)
    made
p = Point.new(close)
q = Point.new(open)
made = p.makeTyped(q, bar_index < 2)
plot(made.x + close)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_typed_if_local_return_from_user_method_aliases() {
    let analysis = analyze(
        r#"type Point
    float x
method makeTyped(Point p, Point other, bool flip) =>
    copy = p
    otherCopy = other
    px = copy.x
    ox = otherCopy.x
    Point made = if flip
        branch = Point.new(x=px)
        branch
    else
        branch = Point.new(x=ox + 1)
        branch
    made := if flip
        Point.new(x=made.x + 2)
    else
        Point.new(x=made.x + 3)
    made
p = Point.new(close)
q = Point.new(open)
made = p.makeTyped(q, bar_index < 2)
plot(made.x + close)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_typed_switch_local_return_from_user_method() {
    let analysis = analyze(
        r#"type Point
    float x
method makeTyped(Point p, float x, int mode) =>
    Point made = switch mode
        0 => Point.new(x)
        1 => Point.new(x + 1)
        => Point.new(x + 2)
    made := switch mode
        3 => Point.new(made.x + 3)
        => Point.new(made.x + 4)
    made
p = Point.new(close)
made = p.makeTyped(open, bar_index)
plot(made.x + close)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_typed_switch_local_return_from_user_method_aliases() {
    let analysis = analyze(
        r#"type Point
    float x
method makeTyped(Point p, Point other, int mode) =>
    copy = p
    otherCopy = other
    px = copy.x
    ox = otherCopy.x
    Point made = switch mode
        0 => Point.new(x=px)
        1 => Point.new(x=ox + 1)
        => Point.new(x=copy.x + 2)
    made := switch mode
        3 => Point.new(x=made.x + 3)
        => Point.new(x=made.x + 4)
    made
p = Point.new(close)
q = Point.new(open)
made = p.makeTyped(q, bar_index)
plot(made.x + close)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_typed_for_local_return_from_user_method_aliases() {
    let analysis = analyze(
        r#"type Point
    float x
method makeTyped(Point p, Point other, int count) =>
    copy = p
    otherCopy = other
    px = copy.x
    ox = otherCopy.x
    Point made = for i = 0 to count
        Point.new(x=px + ox + i)
    made := for i = 0 to count
        Point.new(x=made.x + i + 2)
    made
p = Point.new(close)
q = Point.new(open)
made = p.makeTyped(q, 2)
plot(made.x + close)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_typed_for_in_local_return_from_user_method_aliases() {
    let analysis = analyze(
        r#"type Point
    float x
method makeTyped(Point p, Point other, array<int> values) =>
    copy = p
    otherCopy = other
    px = copy.x
    ox = otherCopy.x
    Point made = for value in values
        Point.new(x=px + ox + value)
    made := for value in values
        Point.new(x=made.x + value + 2)
    made
p = Point.new(close)
q = Point.new(open)
values = array.from(1, 2)
made = p.makeTyped(q, values)
plot(made.x + close)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_final_for_in_alias_return_from_user_method_aliases() {
    let analysis = analyze(
        r#"type Point
    float x
method keepForIn(Point p, array<int> values) =>
    for value in values
        copy = p
        copy
method chooseForIn(Point p, Point other, array<int> values) =>
    for value in values
        copy = other
        copy
p = Point.new(close)
q = Point.new(open)
values = array.from(1, 2)
same = p.keepForIn(values)
chosen = p.chooseForIn(q, values)
plot(same.x + chosen.x)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_typed_while_local_return_from_user_method_aliases() {
    let analysis = analyze(
        r#"type Point
    float x
method makeTyped(Point p, Point other, int count) =>
    copy = p
    otherCopy = other
    px = copy.x
    ox = otherCopy.x
    i = 0
    Point made = while i < count
        i := i + 1
        Point.new(x=px + ox + i)
    j = 0
    made := while j < count
        j := j + 1
        Point.new(x=made.x + j + 2)
    made
p = Point.new(close)
q = Point.new(open)
made = p.makeTyped(q, 2)
plot(made.x + close)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_passthrough_user_function() {
    let analysis = analyze(
        r#"type Point
    float x
    float y
identity(p) => p
p = Point.new(close, open)
same = identity(p)
plot(same.x - same.y)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_block_body_user_function_return() {
    let analysis = analyze(
        r#"type Point
    float x
    float y
wrap(p) =>
    copy = p
    copy
p = Point.new(close, open)
wrapped = wrap(p)
plot(wrapped.x + wrapped.y)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_nested_passthrough_user_function_return() {
    let analysis = analyze(
        r#"type Point
    float x
    float y
inner(p) => p
outer(p) => inner(p)
p = Point.new(close, open)
nested = outer(p)
plot(nested.x + nested.y)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn accepts_udt_named_arg_passthrough_user_function_return() {
    let analysis = analyze(
        r#"type Point
    float x
    float y
choose(delta, p) => p
p = Point.new(close, open)
chosen = choose(p=p, delta=1)
plot(chosen.x + chosen.y)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
}

#[test]
fn rejects_unknown_user_method() {
    let analysis = analyze(
        r#"type Point
    float x
p = Point.new(close)
plot(p.missing())
"#,
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_UNKNOWN_METHOD")
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_wrong_udt_user_method_parameter() {
    let analysis = analyze(
        r#"type Point
    float x
type LabelInfo
    float x
method choose(Point p, Point other) => other
p = Point.new(close)
info = LabelInfo.new(open)
chosen = p.choose(info)
plot(chosen.x)
"#,
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_METHOD_ARG_TYPE"),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_duplicate_user_methods() {
    let analysis = analyze(
        r#"type Point
    float x
method shift(Point p) => p.x
method shift(Point p) => p.x + 1
"#,
    );

    assert!(
        analysis
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "E_METHOD_DUPLICATE")
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn rejects_side_effecting_user_methods() {
    let analysis = analyze(
        r#"type Point
    float x
method draw(Point p) => plot(p.x)
p = Point.new(close)
p.draw()
"#,
    );

    assert!(
        analysis
            .compatibility
            .unsupported
            .iter()
            .any(|feature| { feature.feature == "function_side_effect" })
    );
    assert!(analysis.hir.is_none());
}

#[test]
fn accepts_user_type_local_field_mutation_inside_method() {
    let analysis = analyze(
        r#"type Point
    float x
method mutateLocal(Point p) =>
    local = Point.new(p.x)
    local.x := local.x + 1
    local
p = Point.new(close)
q = p.mutateLocal()
plot(q.x)
"#,
    );

    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    assert!(analysis.hir.is_some());
    assert!(analysis.compatibility.unsupported.is_empty());
    assert!(
        analysis
            .compatibility
            .supported
            .iter()
            .any(|feature| { feature.feature == "user-defined type field mutation" })
    );
}

#[test]
fn rejects_user_type_receiver_field_mutation_inside_method() {
    let analysis = analyze(
        r#"type Point
    float x
method mutateReceiver(Point p) =>
    p.x := p.x + 1
    p
p = Point.new(close)
q = p.mutateReceiver()
plot(q.x)
"#,
    );

    assert!(
        analysis
            .compatibility
            .unsupported
            .iter()
            .any(|feature| { feature.feature == "function_side_effect" }),
        "{:?}",
        analysis.compatibility.unsupported
    );
    assert!(analysis.hir.is_none());
}
