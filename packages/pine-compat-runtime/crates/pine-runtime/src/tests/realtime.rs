use pine_syntax::SourceFile;

use super::*;

#[test]
fn realtime_rollback_restores_math_random_state() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("realtime random")
plot(math.random(0, 1, 7))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let mut runtime = RealtimeRuntime::new(&hir);

    runtime
        .update(BarUpdate::historical(bar(1.0)))
        .expect("historical update");

    let forming = runtime
        .update(BarUpdate::forming(bar(2.0)))
        .expect("forming update");
    let forming_value = forming.plots[0].values[1].clone();

    let rolled_back = runtime
        .update(BarUpdate::forming(bar(3.0)))
        .expect("second forming update");
    assert_eq!(rolled_back.plots[0].values[1], forming_value);

    let confirmed = runtime
        .update(BarUpdate::confirmed(bar(4.0)))
        .expect("confirmed update");
    assert_eq!(confirmed.plots[0].values[1], forming_value);
}

#[test]
fn realtime_rollback_preserves_default_vwap_day_anchor_state() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("realtime vwap")
plot(ta.vwap)
plot(ta.vwap(close))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let timed_bar = |time, close| Bar {
        time,
        open: close,
        high: close,
        low: close,
        close,
        volume: 1.0,
    };
    let mut runtime = RealtimeRuntime::new(&hir);

    runtime
        .update(BarUpdate::historical(timed_bar(0, 10.0)))
        .expect("first historical update");
    runtime
        .update(BarUpdate::historical(timed_bar(60_000, 20.0)))
        .expect("second historical update");

    let forming = runtime
        .update(BarUpdate::forming(timed_bar(86_400_000, 30.0)))
        .expect("new-day forming update");
    assert_values_close(&forming.plots[0].values, &[10.0, 15.0, 30.0]);
    assert_values_close(&forming.plots[1].values, &[10.0, 15.0, 30.0]);

    let replacement = runtime
        .update(BarUpdate::forming(timed_bar(86_400_000, 40.0)))
        .expect("replacement forming update");
    assert_values_close(&replacement.plots[0].values, &[10.0, 15.0, 40.0]);
    assert_values_close(&replacement.plots[1].values, &[10.0, 15.0, 40.0]);

    let confirmed = runtime
        .update(BarUpdate::confirmed(timed_bar(86_400_000, 35.0)))
        .expect("new-day confirmed update");
    assert_values_close(&confirmed.plots[0].values, &[10.0, 15.0, 35.0]);
    assert_values_close(&confirmed.plots[1].values, &[10.0, 15.0, 35.0]);

    let next = runtime
        .update(BarUpdate::confirmed(timed_bar(86_460_000, 45.0)))
        .expect("same-day confirmed update");
    assert_values_close(&next.plots[0].values, &[10.0, 15.0, 35.0, 40.0]);
    assert_values_close(&next.plots[1].values, &[10.0, 15.0, 35.0, 40.0]);
}

#[test]
fn realtime_rollback_restores_conditional_default_vwap_callsite_bucket() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("conditional realtime vwap")
var float score = na
if bar_index != 1
    score := ta.vwap(close)
plot(score)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let timed_bar = |time, close| Bar {
        time,
        open: close,
        high: close,
        low: close,
        close,
        volume: 1.0,
    };
    let mut runtime = RealtimeRuntime::new(&hir);

    runtime
        .update(BarUpdate::historical(timed_bar(0, 10.0)))
        .expect("first historical update");
    let skipped_boundary = runtime
        .update(BarUpdate::forming(timed_bar(86_400_000, 20.0)))
        .expect("skipped boundary update");
    let skipped_boundary_replacement = runtime
        .update(BarUpdate::forming(timed_bar(86_400_000, 25.0)))
        .expect("skipped boundary replacement");
    runtime
        .update(BarUpdate::confirmed(timed_bar(86_400_000, 20.0)))
        .expect("skipped boundary confirmation");
    let resumed = runtime
        .update(BarUpdate::forming(timed_bar(86_460_000, 30.0)))
        .expect("resumed callsite update");
    let resumed_replacement = runtime
        .update(BarUpdate::forming(timed_bar(86_460_000, 40.0)))
        .expect("resumed callsite replacement");

    assert_values_close(&skipped_boundary.plots[0].values, &[10.0, 10.0]);
    assert_values_close(&skipped_boundary_replacement.plots[0].values, &[10.0, 10.0]);
    assert_values_close(&resumed.plots[0].values, &[10.0, 10.0, 30.0]);
    assert_values_close(&resumed_replacement.plots[0].values, &[10.0, 10.0, 40.0]);
}

#[test]
fn barstate_realtime_flags_track_update_kind() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("barstate realtime")
plot(barstate.isconfirmed ? close : 0)
plot(barstate.ishistory ? close : 0)
plot(barstate.isrealtime ? close : 0)
plot(barstate.islast ? close : 0)
plot(barstate.isnew ? close : 0)
plot(barstate.islastconfirmedhistory ? close : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let mut runtime = RealtimeRuntime::new(&hir);

    let confirmed = runtime
        .update(BarUpdate::historical(bar(1.0)))
        .expect("historical update");
    assert_values_close(&confirmed.plots[0].values, &[1.0]);
    assert_values_close(&confirmed.plots[1].values, &[1.0]);
    assert_values_close(&confirmed.plots[2].values, &[0.0]);
    assert_values_close(&confirmed.plots[3].values, &[1.0]);
    assert_values_close(&confirmed.plots[4].values, &[1.0]);
    assert_values_close(&confirmed.plots[5].values, &[1.0]);

    let forming = runtime
        .update(BarUpdate::forming(bar(2.0)))
        .expect("forming update");
    assert_values_close(&forming.plots[0].values, &[1.0, 0.0]);
    assert_values_close(&forming.plots[1].values, &[1.0, 0.0]);
    assert_values_close(&forming.plots[2].values, &[0.0, 2.0]);
    assert_values_close(&forming.plots[3].values, &[1.0, 2.0]);
    assert_values_close(&forming.plots[4].values, &[1.0, 2.0]);
    assert_values_close(&forming.plots[5].values, &[1.0, 0.0]);

    let forming = runtime
        .update(BarUpdate::forming(bar(4.0)))
        .expect("second forming update");
    assert_values_close(&forming.plots[0].values, &[1.0, 0.0]);
    assert_values_close(&forming.plots[1].values, &[1.0, 0.0]);
    assert_values_close(&forming.plots[2].values, &[0.0, 4.0]);
    assert_values_close(&forming.plots[3].values, &[1.0, 4.0]);
    assert_values_close(&forming.plots[4].values, &[1.0, 0.0]);
    assert_values_close(&forming.plots[5].values, &[1.0, 0.0]);

    let confirmed = runtime
        .update(BarUpdate::confirmed(bar(3.0)))
        .expect("confirmed update");
    assert_values_close(&confirmed.plots[0].values, &[1.0, 3.0]);
    assert_values_close(&confirmed.plots[1].values, &[1.0, 0.0]);
    assert_values_close(&confirmed.plots[2].values, &[0.0, 3.0]);
    assert_values_close(&confirmed.plots[3].values, &[1.0, 3.0]);
    assert_values_close(&confirmed.plots[4].values, &[1.0, 0.0]);
    assert_values_close(&confirmed.plots[5].values, &[1.0, 0.0]);
}

#[test]
fn realtime_rollback_restores_map_store_mutations() {
    let source = SourceFile::new(
        "test.pine",
        include_str!("../../../../tests/fixtures/realtime/map_rollback.pine"),
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let mut runtime = RealtimeRuntime::new(&hir);

    let historical = runtime
        .update(BarUpdate::historical(bar(1.0)))
        .expect("historical update");
    assert_values_close(&historical.plots[0].values, &[2.0]);
    assert_values_close(&historical.plots[1].values, &[0.0]);
    assert_values_close(&historical.plots[2].values, &[0.0]);
    assert_values_close(&historical.plots[3].values, &[1.0]);
    assert_values_close(&historical.plots[4].values, &[1.0]);

    let forming = runtime
        .update(BarUpdate::forming(bar(2.0)))
        .expect("forming update");
    assert_values_close(&forming.plots[0].values, &[2.0, 2.0]);
    assert_values_close(&forming.plots[1].values, &[0.0, 1.0]);
    assert_values_close(&forming.plots[2].values, &[0.0, 0.0]);
    assert_values_close(&forming.plots[3].values, &[1.0, 0.0]);
    assert_values_close(&forming.plots[4].values, &[1.0, 2.0]);

    let rolled_back = runtime
        .update(BarUpdate::forming(bar(3.0)))
        .expect("second forming update");
    assert_values_close(&rolled_back.plots[0].values, &[2.0, 2.0]);
    assert_values_close(&rolled_back.plots[1].values, &[0.0, 0.0]);
    assert_values_close(&rolled_back.plots[2].values, &[0.0, 1.0]);
    assert_values_close(&rolled_back.plots[3].values, &[1.0, 0.0]);
    assert_values_close(&rolled_back.plots[4].values, &[1.0, 1.0]);

    let confirmed = runtime
        .update(BarUpdate::confirmed(bar(4.0)))
        .expect("confirmed update");
    assert_values_close(&confirmed.plots[0].values, &[2.0, 2.0]);
    assert_values_close(&confirmed.plots[1].values, &[0.0, 0.0]);
    assert_values_close(&confirmed.plots[2].values, &[0.0, 0.0]);
    assert_values_close(&confirmed.plots[3].values, &[1.0, 1.0]);
    assert_values_close(&confirmed.plots[4].values, &[1.0, 1.0]);
}

#[test]
fn realtime_forming_updates_roll_back_previous_forming_output() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("realtime")
plot(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let mut runtime = RealtimeRuntime::new(&hir);

    let first = runtime
        .update(BarUpdate::historical(bar(1.0)))
        .expect("historical update");
    assert_values_close(&first.plots[0].values, &[1.0]);

    let forming = runtime
        .update(BarUpdate::forming(bar(2.0)))
        .expect("forming update");
    assert_values_close(&forming.plots[0].values, &[1.0, 2.0]);
    assert_values_close(&runtime.confirmed_result().plots[0].values, &[1.0]);

    let rolled_back = runtime
        .update(BarUpdate::forming(bar(3.0)))
        .expect("second forming update");
    assert_values_close(&rolled_back.plots[0].values, &[1.0, 3.0]);
    assert_values_close(&runtime.confirmed_result().plots[0].values, &[1.0]);

    let confirmed = runtime
        .update(BarUpdate::confirmed(bar(4.0)))
        .expect("confirmed update");
    assert_values_close(&confirmed.plots[0].values, &[1.0, 4.0]);
    assert_eq!(runtime.profile().bars, 2);
    assert_eq!(runtime.confirmed_profile().bars, 2);
}

#[test]
fn realtime_rollback_restores_var_state() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("realtime var")
var x = 0
x := x + 1
plot(x)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let mut runtime = RealtimeRuntime::new(&hir);

    runtime
        .update(BarUpdate::historical(bar(1.0)))
        .expect("historical update");

    let forming = runtime
        .update(BarUpdate::forming(bar(2.0)))
        .expect("forming update");
    assert_values_close(&forming.plots[0].values, &[1.0, 2.0]);

    let rolled_back = runtime
        .update(BarUpdate::forming(bar(3.0)))
        .expect("second forming update");
    assert_values_close(&rolled_back.plots[0].values, &[1.0, 2.0]);

    let confirmed = runtime
        .update(BarUpdate::confirmed(bar(4.0)))
        .expect("confirmed update");
    assert_values_close(&confirmed.plots[0].values, &[1.0, 2.0]);
}

#[test]
fn realtime_rollback_restores_typed_user_type_var_state() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("realtime typed UDT var")
type Point
    float x

var Point p = na
if bar_index == 0
    p := Point.new(close)
else
    p := Point.new(p.x + 1)
plot(p.x)
var Point q = if bar_index == 0
    Point.new(close + 10)
else
    Point.new(close + 20)
if bar_index > 0
    q := Point.new(q.x + 1)
plot(q.x)
var Point r = bar_index == 0 ? Point.new(close + 30) : Point.new(close + 40)
if bar_index > 0
    r := Point.new(r.x + 1)
plot(r.x)
var Point s = switch bar_index
    0 => Point.new(close + 50)
    1 => Point.new(close + 60)
    => Point.new(close + 70)
if bar_index > 0
    s := Point.new(s.x + 1)
plot(s.x)
var Point t = for i = 0 to 1
    Point.new(close + i + 80)
if bar_index > 0
    t := Point.new(t.x + 1)
plot(t.x)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let mut runtime = RealtimeRuntime::new(&hir);

    runtime
        .update(BarUpdate::historical(bar(1.0)))
        .expect("historical update");

    let forming = runtime
        .update(BarUpdate::forming(bar(2.0)))
        .expect("forming update");
    assert_values_close(&forming.plots[0].values, &[1.0, 2.0]);
    assert_values_close(&forming.plots[1].values, &[11.0, 12.0]);
    assert_values_close(&forming.plots[2].values, &[31.0, 32.0]);
    assert_values_close(&forming.plots[3].values, &[51.0, 52.0]);
    assert_values_close(&forming.plots[4].values, &[82.0, 83.0]);

    let rolled_back = runtime
        .update(BarUpdate::forming(bar(3.0)))
        .expect("second forming update");
    assert_values_close(&rolled_back.plots[0].values, &[1.0, 2.0]);
    assert_values_close(&rolled_back.plots[1].values, &[11.0, 12.0]);
    assert_values_close(&rolled_back.plots[2].values, &[31.0, 32.0]);
    assert_values_close(&rolled_back.plots[3].values, &[51.0, 52.0]);
    assert_values_close(&rolled_back.plots[4].values, &[82.0, 83.0]);

    let confirmed = runtime
        .update(BarUpdate::confirmed(bar(4.0)))
        .expect("confirmed update");
    assert_values_close(&confirmed.plots[0].values, &[1.0, 2.0]);
    assert_values_close(&confirmed.plots[1].values, &[11.0, 12.0]);
    assert_values_close(&confirmed.plots[2].values, &[31.0, 32.0]);
    assert_values_close(&confirmed.plots[3].values, &[51.0, 52.0]);
    assert_values_close(&confirmed.plots[4].values, &[82.0, 83.0]);
}

#[test]
fn realtime_varip_chart_point_arrays_persist_intrabar_updates() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("realtime varip chart.point arrays")
varip array<chart.point> points = array.new<chart.point>()
points.push(chart.point.from_index(bar_index, close))
last_point = points.get(points.size() - 1)
plot(points.size())
plot(last_point.price)

varip chart.point[] aliases = array.new<chart.point>()
array.push(aliases, chart.point.from_index(bar_index, close + 10))
alias_last = array.get(aliases, array.size(aliases) - 1)
plot(array.size(aliases))
plot(alias_last.price)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let mut runtime = RealtimeRuntime::new(&hir);

    let historical = runtime
        .update(BarUpdate::historical(bar(1.0)))
        .expect("historical update");
    assert_values_close(&historical.plots[0].values, &[1.0]);
    assert_values_close(&historical.plots[1].values, &[1.0]);
    assert_values_close(&historical.plots[2].values, &[1.0]);
    assert_values_close(&historical.plots[3].values, &[11.0]);

    let forming = runtime
        .update(BarUpdate::forming(bar(2.0)))
        .expect("forming update");
    assert_values_close(&forming.plots[0].values, &[1.0, 2.0]);
    assert_values_close(&forming.plots[1].values, &[1.0, 2.0]);
    assert_values_close(&forming.plots[2].values, &[1.0, 2.0]);
    assert_values_close(&forming.plots[3].values, &[11.0, 12.0]);

    let rolled_forward = runtime
        .update(BarUpdate::forming(bar(3.0)))
        .expect("second forming update");
    assert_values_close(&rolled_forward.plots[0].values, &[1.0, 3.0]);
    assert_values_close(&rolled_forward.plots[1].values, &[1.0, 3.0]);
    assert_values_close(&rolled_forward.plots[2].values, &[1.0, 3.0]);
    assert_values_close(&rolled_forward.plots[3].values, &[11.0, 13.0]);

    let confirmed = runtime
        .update(BarUpdate::confirmed(bar(4.0)))
        .expect("confirmed update");
    assert_values_close(&confirmed.plots[0].values, &[1.0, 4.0]);
    assert_values_close(&confirmed.plots[1].values, &[1.0, 4.0]);
    assert_values_close(&confirmed.plots[2].values, &[1.0, 4.0]);
    assert_values_close(&confirmed.plots[3].values, &[11.0, 14.0]);
}

#[test]
fn realtime_varip_maps_persist_intrabar_updates() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("realtime varip maps")
varip values = map.new<int, float>()
next_key = values.size()
values.put(next_key, close)
plot(values.size())
plot(values.get(next_key))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );
    let hir = analysis.hir.expect("HIR");
    let mut runtime = RealtimeRuntime::new(&hir);

    let historical = runtime
        .update(BarUpdate::historical(bar(1.0)))
        .expect("historical update");
    assert_values_close(&historical.plots[0].values, &[1.0]);
    assert_values_close(&historical.plots[1].values, &[1.0]);

    let forming = runtime
        .update(BarUpdate::forming(bar(2.0)))
        .expect("forming update");
    assert_values_close(&forming.plots[0].values, &[1.0, 2.0]);
    assert_values_close(&forming.plots[1].values, &[1.0, 2.0]);

    let rolled_forward = runtime
        .update(BarUpdate::forming(bar(3.0)))
        .expect("second forming update");
    assert_values_close(&rolled_forward.plots[0].values, &[1.0, 3.0]);
    assert_values_close(&rolled_forward.plots[1].values, &[1.0, 3.0]);

    let confirmed = runtime
        .update(BarUpdate::confirmed(bar(4.0)))
        .expect("confirmed update");
    assert_values_close(&confirmed.plots[0].values, &[1.0, 4.0]);
    assert_values_close(&confirmed.plots[1].values, &[1.0, 4.0]);
}
