use std::{fs, path::PathBuf};

use pine_runtime::{AlertEvent, Bar, BarUpdate, PineValue, RealtimeRuntime, run_historical};
use pine_sema::{AnalysisInput, analyze_input, analyze_source};
use pine_syntax::SourceFile;

fn workspace_fixture(path: &str) -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .join(path)
}

#[test]
fn forming_close_fixture_rolls_back_repeated_updates() {
    let mut runtime = runtime_for_fixture("tests/fixtures/realtime/forming_close.pine");

    let result = runtime
        .update(BarUpdate::historical(bar(1.0)))
        .expect("historical update should run");
    assert_values(&result.plots[0].values, &[1.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(2.0)))
        .expect("forming update should run");
    assert_values(&result.plots[0].values, &[1.0, 2.0]);
    assert_values(&runtime.confirmed_result().plots[0].values, &[1.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(3.0)))
        .expect("second forming update should roll back");
    assert_values(&result.plots[0].values, &[1.0, 3.0]);
    assert_values(&runtime.confirmed_result().plots[0].values, &[1.0]);

    let result = runtime
        .update(BarUpdate::confirmed(bar(4.0)))
        .expect("confirmed update should commit");
    assert_values(&result.plots[0].values, &[1.0, 4.0]);
    assert_values(&runtime.confirmed_result().plots[0].values, &[1.0, 4.0]);
}

#[test]
fn alertcondition_fixture_rolls_back_forming_events() {
    let mut runtime = runtime_for_fixture("tests/fixtures/realtime/alertcondition_rollback.pine");

    let result = runtime
        .update(BarUpdate::historical(bar(1.0)))
        .expect("historical update should run");
    assert!(result.alerts.is_empty());

    let result = runtime
        .update(BarUpdate::forming(bar(2.0)))
        .expect("forming update should run");
    assert_eq!(result.alerts.len(), 1);
    assert_eq!(result.alerts[0].bar_index, 1);
    assert_eq!(result.alerts[0].message, "Close is above one");
    assert!(runtime.confirmed_result().alerts.is_empty());

    let result = runtime
        .update(BarUpdate::forming(bar(3.0)))
        .expect("second forming update should roll back alert event");
    assert_eq!(result.alerts.len(), 1);
    assert_eq!(result.alerts[0].bar_index, 1);
    assert!(runtime.confirmed_result().alerts.is_empty());

    let result = runtime
        .update(BarUpdate::confirmed(bar(4.0)))
        .expect("confirmed update should commit alert event");
    assert_eq!(result.alerts.len(), 1);
    assert_eq!(runtime.confirmed_result().alerts.len(), 1);
}

#[test]
fn alert_fixture_rolls_back_forming_events() {
    let mut runtime = runtime_for_fixture("tests/fixtures/realtime/alert_rollback.pine");

    let result = runtime
        .update(BarUpdate::historical(bar(1.0)))
        .expect("historical update should run");
    assert_eq!(result.alerts.len(), 1);
    assert_eq!(result.alerts[0].bar_index, 0);
    assert_eq!(result.alerts[0].message, "Realtime alert");

    let result = runtime
        .update(BarUpdate::forming(bar(2.0)))
        .expect("forming update should run");
    assert_eq!(result.alerts.len(), 2);
    assert_eq!(result.alerts[1].bar_index, 1);
    assert_eq!(runtime.confirmed_result().alerts.len(), 1);

    let result = runtime
        .update(BarUpdate::forming(bar(3.0)))
        .expect("second forming update should roll back alert event");
    assert_eq!(result.alerts.len(), 2);
    assert_eq!(result.alerts[1].bar_index, 1);
    assert_eq!(runtime.confirmed_result().alerts.len(), 1);

    let result = runtime
        .update(BarUpdate::confirmed(bar(4.0)))
        .expect("confirmed update should commit alert event");
    assert_eq!(result.alerts.len(), 2);
    assert_eq!(runtime.confirmed_result().alerts.len(), 2);
}

#[test]
fn alert_policy_fixture_recomputes_forming_events_and_commits_confirmed_state() {
    let fixture = "tests/fixtures/realtime/alert_policy.pine";
    let mut runtime = runtime_for_fixture(fixture);

    let result = runtime
        .update(BarUpdate::historical(bar(1.0)))
        .expect("historical update should run");
    assert_alerts(&result.alerts, &[]);

    let result = runtime
        .update(BarUpdate::forming(bar(3.0)))
        .expect("forming update should expose current forming alert events");
    assert_alerts(
        &result.alerts,
        &[
            (1, "alert", "Above one"),
            (1, "alert", "Above two"),
            (1, "Above two condition", "Condition above two"),
        ],
    );
    assert_alerts(&runtime.confirmed_result().alerts, &[]);

    let result = runtime
        .update(BarUpdate::forming(bar(2.0)))
        .expect("second forming update should drop abandoned alert events");
    assert_alerts(&result.alerts, &[(1, "alert", "Above one")]);
    assert_alerts(&runtime.confirmed_result().alerts, &[]);

    let result = runtime
        .update(BarUpdate::forming(bar(0.0)))
        .expect("third forming update should drop all abandoned alert events");
    assert_alerts(&result.alerts, &[]);
    assert_alerts(&runtime.confirmed_result().alerts, &[]);

    let result = runtime
        .update(BarUpdate::confirmed(bar(4.0)))
        .expect("confirmed update should commit alert events");
    assert_alerts(
        &result.alerts,
        &[
            (1, "alert", "Above one"),
            (1, "alert", "Above two"),
            (1, "Above two condition", "Condition above two"),
        ],
    );
    assert_eq!(runtime.confirmed_result().alerts, result.alerts);

    let hir = hir_for_fixture(fixture);
    let historical = run_historical(&hir, &[bar(1.0), bar(4.0)])
        .expect("equivalent historical execution should run");
    assert_eq!(
        alert_summaries(&result.alerts),
        alert_summaries(&historical.alerts)
    );
}

#[test]
fn alert_frequency_close_fixture_only_emits_on_confirmed_updates() {
    let fixture = "tests/fixtures/realtime/alert_frequency_close.pine";
    let mut runtime = runtime_for_fixture(fixture);

    let result = runtime
        .update(BarUpdate::historical(bar(1.0)))
        .expect("historical update should run");
    assert_alerts(&result.alerts, &[]);

    let result = runtime
        .update(BarUpdate::forming(bar(3.0)))
        .expect("forming update should not emit close-frequency alert");
    assert_alerts(&result.alerts, &[]);
    assert_alerts(&runtime.confirmed_result().alerts, &[]);

    let result = runtime
        .update(BarUpdate::forming(bar(4.0)))
        .expect("second forming update should still not emit close-frequency alert");
    assert_alerts(&result.alerts, &[]);
    assert_alerts(&runtime.confirmed_result().alerts, &[]);

    let result = runtime
        .update(BarUpdate::confirmed(bar(5.0)))
        .expect("confirmed update should commit close-frequency alert");
    assert_alerts(&result.alerts, &[(1, "alert", "Close alert")]);
    assert_eq!(runtime.confirmed_result().alerts, result.alerts);

    let hir = hir_for_fixture(fixture);
    let historical = run_historical(&hir, &[bar(1.0), bar(5.0)])
        .expect("equivalent historical execution should run");
    assert_eq!(
        alert_summaries(&result.alerts),
        alert_summaries(&historical.alerts)
    );
}

#[test]
fn alert_frequency_rollback_fixture_recomputes_once_and_all_events() {
    let fixture = "tests/fixtures/realtime/alert_frequency_rollback.pine";
    let mut runtime = runtime_for_fixture(fixture);

    let result = runtime
        .update(BarUpdate::historical(bar(1.0)))
        .expect("historical update should run");
    assert_alerts(&result.alerts, &[]);

    let result = runtime
        .update(BarUpdate::forming(bar(3.0)))
        .expect("forming update should expose current frequency-filtered alerts");
    assert_alerts(
        &result.alerts,
        &[
            (1, "alert", "Default once"),
            (1, "alert", "All calls"),
            (1, "alert", "All calls"),
        ],
    );
    assert_alerts(&runtime.confirmed_result().alerts, &[]);

    let result = runtime
        .update(BarUpdate::forming(bar(0.0)))
        .expect("second forming update should drop abandoned frequency alerts");
    assert_alerts(&result.alerts, &[]);
    assert_alerts(&runtime.confirmed_result().alerts, &[]);

    let result = runtime
        .update(BarUpdate::confirmed(bar(4.0)))
        .expect("confirmed update should commit frequency-filtered alerts");
    assert_alerts(
        &result.alerts,
        &[
            (1, "alert", "Default once"),
            (1, "alert", "All calls"),
            (1, "alert", "All calls"),
        ],
    );
    assert_eq!(runtime.confirmed_result().alerts, result.alerts);

    let hir = hir_for_fixture(fixture);
    let historical = run_historical(&hir, &[bar(1.0), bar(4.0)])
        .expect("equivalent historical execution should run");
    assert_eq!(
        alert_summaries(&result.alerts),
        alert_summaries(&historical.alerts)
    );
}

#[test]
fn var_rollback_fixture_restores_confirmed_state_between_forming_updates() {
    let mut runtime = runtime_for_fixture("tests/fixtures/realtime/var_rollback.pine");

    let result = runtime
        .update(BarUpdate::historical(bar(1.0)))
        .expect("historical update should run");
    assert_values(&result.plots[0].values, &[1.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(2.0)))
        .expect("forming update should run");
    assert_values(&result.plots[0].values, &[1.0, 2.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(3.0)))
        .expect("second forming update should roll back var state");
    assert_values(&result.plots[0].values, &[1.0, 2.0]);

    let result = runtime
        .update(BarUpdate::confirmed(bar(4.0)))
        .expect("confirmed update should commit var state");
    assert_values(&result.plots[0].values, &[1.0, 2.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(5.0)))
        .expect("next forming update should start from new confirmed var state");
    assert_values(&result.plots[0].values, &[1.0, 2.0, 3.0]);
}

#[test]
fn user_type_var_fixture_rolls_back_between_forming_updates() {
    let mut runtime = runtime_for_fixture("tests/fixtures/realtime/user_type_var_rollback.pine");

    let result = runtime
        .update(BarUpdate::historical(bar(1.0)))
        .expect("historical update should run");
    assert_values(&result.plots[0].values, &[1.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(2.0)))
        .expect("forming update should run");
    assert_values(&result.plots[0].values, &[1.0, 2.0]);
    assert_values(&runtime.confirmed_result().plots[0].values, &[1.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(3.0)))
        .expect("second forming update should roll back UDT var state");
    assert_values(&result.plots[0].values, &[1.0, 3.0]);
    assert_values(&runtime.confirmed_result().plots[0].values, &[1.0]);

    let result = runtime
        .update(BarUpdate::confirmed(bar(4.0)))
        .expect("confirmed update should commit UDT var state");
    assert_values(&result.plots[0].values, &[1.0, 4.0]);
    assert_values(&runtime.confirmed_result().plots[0].values, &[1.0, 4.0]);
}

#[test]
fn user_type_array_var_fixture_rolls_back_between_forming_updates() {
    let mut runtime =
        runtime_for_fixture("tests/fixtures/realtime/user_type_array_var_rollback.pine");

    let result = runtime
        .update(BarUpdate::historical(bar(1.0)))
        .expect("historical update should run");
    assert_values(&result.plots[0].values, &[2.0]);
    assert_values(&result.plots[1].values, &[1.0]);
    assert_values(&result.plots[2].values, &[1.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(2.0)))
        .expect("forming update should run");
    assert_values(&result.plots[0].values, &[2.0, 3.0]);
    assert_values(&result.plots[1].values, &[1.0, 1.0]);
    assert_values(&result.plots[2].values, &[1.0, 2.0]);
    assert_values(&runtime.confirmed_result().plots[0].values, &[2.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(3.0)))
        .expect("second forming update should roll back UDT array var state");
    assert_values(&result.plots[0].values, &[2.0, 3.0]);
    assert_values(&result.plots[1].values, &[1.0, 1.0]);
    assert_values(&result.plots[2].values, &[1.0, 3.0]);
    assert_values(&runtime.confirmed_result().plots[0].values, &[2.0]);

    let result = runtime
        .update(BarUpdate::confirmed(bar(4.0)))
        .expect("confirmed update should commit UDT array var state");
    assert_values(&result.plots[0].values, &[2.0, 3.0]);
    assert_values(&result.plots[1].values, &[1.0, 1.0]);
    assert_values(&result.plots[2].values, &[1.0, 4.0]);
    assert_values(&runtime.confirmed_result().plots[0].values, &[2.0, 3.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(5.0)))
        .expect("next forming update should start from confirmed UDT array state");
    assert_values(&result.plots[0].values, &[2.0, 3.0, 4.0]);
    assert_values(&result.plots[1].values, &[1.0, 1.0, 1.0]);
    assert_values(&result.plots[2].values, &[1.0, 4.0, 5.0]);
}

#[test]
fn chart_point_var_fixture_rolls_back_between_forming_updates() {
    let mut runtime = runtime_for_fixture("tests/fixtures/realtime/chart_point_var_rollback.pine");

    let result = runtime
        .update(BarUpdate::historical(bar(1.0)))
        .expect("historical update should run");
    assert_values(&result.plots[0].values, &[2.0]);
    assert_values(&result.plots[1].values, &[0.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(2.0)))
        .expect("forming update should run");
    assert_values(&result.plots[0].values, &[2.0, 3.0]);
    assert_values(&result.plots[1].values, &[0.0, 0.0]);
    assert_values(&runtime.confirmed_result().plots[0].values, &[2.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(3.0)))
        .expect("second forming update should roll back chart.point var state");
    assert_values(&result.plots[0].values, &[2.0, 3.0]);
    assert_values(&result.plots[1].values, &[0.0, 0.0]);
    assert_values(&runtime.confirmed_result().plots[0].values, &[2.0]);

    let result = runtime
        .update(BarUpdate::confirmed(bar(4.0)))
        .expect("confirmed update should commit chart.point var state");
    assert_values(&result.plots[0].values, &[2.0, 3.0]);
    assert_values(&result.plots[1].values, &[0.0, 0.0]);
    assert_values(&runtime.confirmed_result().plots[0].values, &[2.0, 3.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(5.0)))
        .expect("next forming update should start from confirmed chart.point var state");
    assert_values(&result.plots[0].values, &[2.0, 3.0, 4.0]);
    assert_values(&result.plots[1].values, &[0.0, 0.0, 0.0]);
}

#[test]
fn varip_scalar_fixture_persists_intrabar_state_between_forming_updates() {
    let mut runtime = runtime_for_fixture("tests/fixtures/realtime/varip_scalar.pine");

    let result = runtime
        .update(BarUpdate::historical(bar(1.0)))
        .expect("historical update should run");
    assert_values(&result.plots[0].values, &[1.0]);
    assert_values(&result.plots[1].values, &[1.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(2.0)))
        .expect("forming update should run");
    assert_values(&result.plots[0].values, &[1.0, 2.0]);
    assert_values(&result.plots[1].values, &[1.0, 2.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(3.0)))
        .expect("second forming update should retain varip state");
    assert_values(&result.plots[0].values, &[1.0, 2.0]);
    assert_values(&result.plots[1].values, &[1.0, 3.0]);

    let result = runtime
        .update(BarUpdate::confirmed(bar(4.0)))
        .expect("confirmed update should commit varip state");
    assert_values(&result.plots[0].values, &[1.0, 2.0]);
    assert_values(&result.plots[1].values, &[1.0, 4.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(5.0)))
        .expect("next forming update should start from confirmed varip state");
    assert_values(&result.plots[0].values, &[1.0, 2.0, 3.0]);
    assert_values(&result.plots[1].values, &[1.0, 4.0, 5.0]);
}

#[test]
fn chart_point_varip_fixture_persists_intrabar_value_between_forming_updates() {
    let mut runtime = runtime_for_fixture("tests/fixtures/realtime/chart_point_varip.pine");

    let result = runtime
        .update(BarUpdate::historical(bar(1.0)))
        .expect("historical update should run");
    assert_values(&result.plots[0].values, &[2.0]);
    assert_values(&result.plots[1].values, &[2.0]);
    assert_values(&result.plots[2].values, &[0.0]);
    assert_values(&result.plots[3].values, &[0.0]);
    assert_values(&result.plots[4].values, &[-1.0]);
    assert_values(&result.plots[5].values, &[-1.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(2.0)))
        .expect("forming update should run");
    assert_values(&result.plots[0].values, &[2.0, 3.0]);
    assert_values(&result.plots[1].values, &[2.0, 3.0]);
    assert_values(&result.plots[2].values, &[0.0, 0.0]);
    assert_values(&result.plots[3].values, &[0.0, 0.0]);
    assert_values(&result.plots[4].values, &[-1.0, 2.0]);
    assert_values(&result.plots[5].values, &[-1.0, 2.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(3.0)))
        .expect("second forming update should retain chart.point varip state");
    assert_values(&result.plots[0].values, &[2.0, 3.0]);
    assert_values(&result.plots[1].values, &[2.0, 4.0]);
    assert_values(&result.plots[2].values, &[0.0, 0.0]);
    assert_values(&result.plots[3].values, &[0.0, 0.0]);
    assert_values(&result.plots[4].values, &[-1.0, 2.0]);
    assert_values(&result.plots[5].values, &[-1.0, 2.0]);

    let result = runtime
        .update(BarUpdate::confirmed(bar(4.0)))
        .expect("confirmed update should commit chart.point varip state");
    assert_values(&result.plots[0].values, &[2.0, 3.0]);
    assert_values(&result.plots[1].values, &[2.0, 5.0]);
    assert_values(&result.plots[2].values, &[0.0, 0.0]);
    assert_values(&result.plots[3].values, &[0.0, 0.0]);
    assert_values(&result.plots[4].values, &[-1.0, 2.0]);
    assert_values(&result.plots[5].values, &[-1.0, 2.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(5.0)))
        .expect("next forming update should start from confirmed chart.point varip state");
    assert_values(&result.plots[0].values, &[2.0, 3.0, 4.0]);
    assert_values(&result.plots[1].values, &[2.0, 5.0, 6.0]);
    assert_values(&result.plots[2].values, &[0.0, 0.0, 0.0]);
    assert_values(&result.plots[3].values, &[0.0, 0.0, 0.0]);
    assert_values(&result.plots[4].values, &[-1.0, 2.0, 5.0]);
    assert_values(&result.plots[5].values, &[-1.0, 2.0, 5.0]);
}

#[test]
fn user_type_varip_fixture_persists_intrabar_value_between_forming_updates() {
    let mut runtime = runtime_for_fixture("tests/fixtures/realtime/user_type_varip.pine");

    let result = runtime
        .update(BarUpdate::historical(bar(1.0)))
        .expect("historical update should run");
    assert_values(&result.plots[0].values, &[2.0]);
    assert_values(&result.plots[1].values, &[2.0]);
    assert_values(&result.plots[2].values, &[-1.0]);
    assert_values(&result.plots[3].values, &[-1.0]);
    assert_values(&result.plots[4].values, &[1.0]);
    assert_values(&result.plots[5].values, &[2.0]);
    assert_values(&result.plots[6].values, &[-1.0]);
    assert_values(&result.plots[7].values, &[-1.0]);
    assert_values(&result.plots[8].values, &[2.0]);
    assert_values(&result.plots[9].values, &[-1.0]);
    assert_values(&result.plots[10].values, &[-1.0]);
    assert_values(&result.plots[11].values, &[2.0]);
    assert_values(&result.plots[12].values, &[-1.0]);
    assert_values(&result.plots[13].values, &[-1.0]);
    assert_values(&result.plots[14].values, &[2.0]);
    assert_values(&result.plots[15].values, &[-1.0]);
    assert_values(&result.plots[16].values, &[-1.0]);
    assert_values(&result.plots[17].values, &[2.0]);
    assert_values(&result.plots[18].values, &[-1.0]);
    assert_values(&result.plots[19].values, &[-1.0]);
    assert_values(&result.plots[20].values, &[3.0]);
    assert_values(&result.plots[21].values, &[-1.0]);
    assert_values(&result.plots[22].values, &[-1.0]);
    assert_values(&result.plots[23].values, &[103.0]);
    assert_values(&result.plots[24].values, &[-1.0]);
    assert_values(&result.plots[25].values, &[-1.0]);
    assert_values(&result.plots[26].values, &[114.0]);
    assert_values(&result.plots[27].values, &[-1.0]);
    assert_values(&result.plots[28].values, &[-1.0]);
    assert_values(&result.plots[29].values, &[122.0]);
    assert_values(&result.plots[30].values, &[-1.0]);
    assert_values(&result.plots[31].values, &[-1.0]);
    assert_values(&result.plots[32].values, &[132.0]);
    assert_values(&result.plots[33].values, &[-1.0]);
    assert_values(&result.plots[34].values, &[-1.0]);
    assert_values(&result.plots[35].values, &[142.0]);
    assert_values(&result.plots[36].values, &[-1.0]);
    assert_values(&result.plots[37].values, &[-1.0]);
    assert_values(&result.plots[38].values, &[153.0]);
    assert_values(&result.plots[39].values, &[-1.0]);
    assert_values(&result.plots[40].values, &[-1.0]);
    assert_values(&result.plots[41].values, &[163.0]);
    assert_values(&result.plots[42].values, &[-1.0]);
    assert_values(&result.plots[43].values, &[-1.0]);
    assert_values(&result.plots[44].values, &[174.0]);
    assert_values(&result.plots[45].values, &[-1.0]);
    assert_values(&result.plots[46].values, &[-1.0]);
    assert_values(&result.plots[47].values, &[2.0]);
    assert_values(&result.plots[48].values, &[-1.0]);
    assert_values(&result.plots[49].values, &[-1.0]);
    assert_values(&result.plots[50].values, &[2.0]);
    assert_values(&result.plots[51].values, &[-1.0]);
    assert_values(&result.plots[52].values, &[-1.0]);
    assert_values(&result.plots[53].values, &[2.0]);
    assert_values(&result.plots[54].values, &[-1.0]);
    assert_values(&result.plots[55].values, &[-1.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(2.0)))
        .expect("forming update should run");
    assert_values(&result.plots[0].values, &[2.0, 3.0]);
    assert_values(&result.plots[1].values, &[2.0, 3.0]);
    assert_values(&result.plots[2].values, &[-1.0, 2.0]);
    assert_values(&result.plots[3].values, &[-1.0, 2.0]);
    assert_values(&result.plots[4].values, &[1.0, 2.0]);
    assert_values(&result.plots[5].values, &[2.0, 3.0]);
    assert_values(&result.plots[6].values, &[-1.0, 2.0]);
    assert_values(&result.plots[7].values, &[-1.0, 2.0]);
    assert_values(&result.plots[8].values, &[2.0, 3.0]);
    assert_values(&result.plots[9].values, &[-1.0, 2.0]);
    assert_values(&result.plots[10].values, &[-1.0, 2.0]);
    assert_values(&result.plots[11].values, &[2.0, 3.0]);
    assert_values(&result.plots[12].values, &[-1.0, 2.0]);
    assert_values(&result.plots[13].values, &[-1.0, 2.0]);
    assert_values(&result.plots[14].values, &[2.0, 3.0]);
    assert_values(&result.plots[15].values, &[-1.0, 2.0]);
    assert_values(&result.plots[16].values, &[-1.0, 2.0]);
    assert_values(&result.plots[17].values, &[2.0, 3.0]);
    assert_values(&result.plots[18].values, &[-1.0, 2.0]);
    assert_values(&result.plots[19].values, &[-1.0, 2.0]);
    assert_values(&result.plots[20].values, &[3.0, 4.0]);
    assert_values(&result.plots[21].values, &[-1.0, 3.0]);
    assert_values(&result.plots[22].values, &[-1.0, 3.0]);
    assert_values(&result.plots[23].values, &[103.0, 104.0]);
    assert_values(&result.plots[24].values, &[-1.0, 103.0]);
    assert_values(&result.plots[25].values, &[-1.0, 103.0]);
    assert_values(&result.plots[26].values, &[114.0, 115.0]);
    assert_values(&result.plots[27].values, &[-1.0, 114.0]);
    assert_values(&result.plots[28].values, &[-1.0, 114.0]);
    assert_values(&result.plots[29].values, &[122.0, 123.0]);
    assert_values(&result.plots[30].values, &[-1.0, 122.0]);
    assert_values(&result.plots[31].values, &[-1.0, 122.0]);
    assert_values(&result.plots[32].values, &[132.0, 133.0]);
    assert_values(&result.plots[33].values, &[-1.0, 132.0]);
    assert_values(&result.plots[34].values, &[-1.0, 132.0]);
    assert_values(&result.plots[35].values, &[142.0, 143.0]);
    assert_values(&result.plots[36].values, &[-1.0, 142.0]);
    assert_values(&result.plots[37].values, &[-1.0, 142.0]);
    assert_values(&result.plots[38].values, &[153.0, 154.0]);
    assert_values(&result.plots[39].values, &[-1.0, 153.0]);
    assert_values(&result.plots[40].values, &[-1.0, 153.0]);
    assert_values(&result.plots[41].values, &[163.0, 164.0]);
    assert_values(&result.plots[42].values, &[-1.0, 163.0]);
    assert_values(&result.plots[43].values, &[-1.0, 163.0]);
    assert_values(&result.plots[44].values, &[174.0, 175.0]);
    assert_values(&result.plots[45].values, &[-1.0, 174.0]);
    assert_values(&result.plots[46].values, &[-1.0, 174.0]);
    assert_values(&result.plots[47].values, &[2.0, 3.0]);
    assert_values(&result.plots[48].values, &[-1.0, 2.0]);
    assert_values(&result.plots[49].values, &[-1.0, 2.0]);
    assert_values(&result.plots[50].values, &[2.0, 3.0]);
    assert_values(&result.plots[51].values, &[-1.0, 2.0]);
    assert_values(&result.plots[52].values, &[-1.0, 2.0]);
    assert_values(&result.plots[53].values, &[2.0, 3.0]);
    assert_values(&result.plots[54].values, &[-1.0, 2.0]);
    assert_values(&result.plots[55].values, &[-1.0, 2.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(3.0)))
        .expect("second forming update should retain UDT varip state");
    assert_values(&result.plots[0].values, &[2.0, 3.0]);
    assert_values(&result.plots[1].values, &[2.0, 4.0]);
    assert_values(&result.plots[2].values, &[-1.0, 2.0]);
    assert_values(&result.plots[3].values, &[-1.0, 2.0]);
    assert_values(&result.plots[4].values, &[1.0, 3.0]);
    assert_values(&result.plots[5].values, &[2.0, 4.0]);
    assert_values(&result.plots[6].values, &[-1.0, 2.0]);
    assert_values(&result.plots[7].values, &[-1.0, 2.0]);
    assert_values(&result.plots[8].values, &[2.0, 4.0]);
    assert_values(&result.plots[9].values, &[-1.0, 2.0]);
    assert_values(&result.plots[10].values, &[-1.0, 2.0]);
    assert_values(&result.plots[11].values, &[2.0, 4.0]);
    assert_values(&result.plots[12].values, &[-1.0, 2.0]);
    assert_values(&result.plots[13].values, &[-1.0, 2.0]);
    assert_values(&result.plots[14].values, &[2.0, 4.0]);
    assert_values(&result.plots[15].values, &[-1.0, 2.0]);
    assert_values(&result.plots[16].values, &[-1.0, 2.0]);
    assert_values(&result.plots[17].values, &[2.0, 4.0]);
    assert_values(&result.plots[18].values, &[-1.0, 2.0]);
    assert_values(&result.plots[19].values, &[-1.0, 2.0]);
    assert_values(&result.plots[20].values, &[3.0, 5.0]);
    assert_values(&result.plots[21].values, &[-1.0, 3.0]);
    assert_values(&result.plots[22].values, &[-1.0, 3.0]);
    assert_values(&result.plots[23].values, &[103.0, 105.0]);
    assert_values(&result.plots[24].values, &[-1.0, 103.0]);
    assert_values(&result.plots[25].values, &[-1.0, 103.0]);
    assert_values(&result.plots[26].values, &[114.0, 116.0]);
    assert_values(&result.plots[27].values, &[-1.0, 114.0]);
    assert_values(&result.plots[28].values, &[-1.0, 114.0]);
    assert_values(&result.plots[29].values, &[122.0, 124.0]);
    assert_values(&result.plots[30].values, &[-1.0, 122.0]);
    assert_values(&result.plots[31].values, &[-1.0, 122.0]);
    assert_values(&result.plots[32].values, &[132.0, 134.0]);
    assert_values(&result.plots[33].values, &[-1.0, 132.0]);
    assert_values(&result.plots[34].values, &[-1.0, 132.0]);
    assert_values(&result.plots[35].values, &[142.0, 144.0]);
    assert_values(&result.plots[36].values, &[-1.0, 142.0]);
    assert_values(&result.plots[37].values, &[-1.0, 142.0]);
    assert_values(&result.plots[38].values, &[153.0, 155.0]);
    assert_values(&result.plots[39].values, &[-1.0, 153.0]);
    assert_values(&result.plots[40].values, &[-1.0, 153.0]);
    assert_values(&result.plots[41].values, &[163.0, 165.0]);
    assert_values(&result.plots[42].values, &[-1.0, 163.0]);
    assert_values(&result.plots[43].values, &[-1.0, 163.0]);
    assert_values(&result.plots[44].values, &[174.0, 176.0]);
    assert_values(&result.plots[45].values, &[-1.0, 174.0]);
    assert_values(&result.plots[46].values, &[-1.0, 174.0]);
    assert_values(&result.plots[47].values, &[2.0, 4.0]);
    assert_values(&result.plots[48].values, &[-1.0, 2.0]);
    assert_values(&result.plots[49].values, &[-1.0, 2.0]);
    assert_values(&result.plots[50].values, &[2.0, 4.0]);
    assert_values(&result.plots[51].values, &[-1.0, 2.0]);
    assert_values(&result.plots[52].values, &[-1.0, 2.0]);
    assert_values(&result.plots[53].values, &[2.0, 4.0]);
    assert_values(&result.plots[54].values, &[-1.0, 2.0]);
    assert_values(&result.plots[55].values, &[-1.0, 2.0]);

    let result = runtime
        .update(BarUpdate::confirmed(bar(4.0)))
        .expect("confirmed update should commit UDT varip state");
    assert_values(&result.plots[0].values, &[2.0, 3.0]);
    assert_values(&result.plots[1].values, &[2.0, 5.0]);
    assert_values(&result.plots[2].values, &[-1.0, 2.0]);
    assert_values(&result.plots[3].values, &[-1.0, 2.0]);
    assert_values(&result.plots[4].values, &[1.0, 4.0]);
    assert_values(&result.plots[5].values, &[2.0, 5.0]);
    assert_values(&result.plots[6].values, &[-1.0, 2.0]);
    assert_values(&result.plots[7].values, &[-1.0, 2.0]);
    assert_values(&result.plots[8].values, &[2.0, 5.0]);
    assert_values(&result.plots[9].values, &[-1.0, 2.0]);
    assert_values(&result.plots[10].values, &[-1.0, 2.0]);
    assert_values(&result.plots[11].values, &[2.0, 5.0]);
    assert_values(&result.plots[12].values, &[-1.0, 2.0]);
    assert_values(&result.plots[13].values, &[-1.0, 2.0]);
    assert_values(&result.plots[14].values, &[2.0, 5.0]);
    assert_values(&result.plots[15].values, &[-1.0, 2.0]);
    assert_values(&result.plots[16].values, &[-1.0, 2.0]);
    assert_values(&result.plots[17].values, &[2.0, 5.0]);
    assert_values(&result.plots[18].values, &[-1.0, 2.0]);
    assert_values(&result.plots[19].values, &[-1.0, 2.0]);
    assert_values(&result.plots[20].values, &[3.0, 6.0]);
    assert_values(&result.plots[21].values, &[-1.0, 3.0]);
    assert_values(&result.plots[22].values, &[-1.0, 3.0]);
    assert_values(&result.plots[23].values, &[103.0, 106.0]);
    assert_values(&result.plots[24].values, &[-1.0, 103.0]);
    assert_values(&result.plots[25].values, &[-1.0, 103.0]);
    assert_values(&result.plots[26].values, &[114.0, 117.0]);
    assert_values(&result.plots[27].values, &[-1.0, 114.0]);
    assert_values(&result.plots[28].values, &[-1.0, 114.0]);
    assert_values(&result.plots[29].values, &[122.0, 125.0]);
    assert_values(&result.plots[30].values, &[-1.0, 122.0]);
    assert_values(&result.plots[31].values, &[-1.0, 122.0]);
    assert_values(&result.plots[32].values, &[132.0, 135.0]);
    assert_values(&result.plots[33].values, &[-1.0, 132.0]);
    assert_values(&result.plots[34].values, &[-1.0, 132.0]);
    assert_values(&result.plots[35].values, &[142.0, 145.0]);
    assert_values(&result.plots[36].values, &[-1.0, 142.0]);
    assert_values(&result.plots[37].values, &[-1.0, 142.0]);
    assert_values(&result.plots[38].values, &[153.0, 156.0]);
    assert_values(&result.plots[39].values, &[-1.0, 153.0]);
    assert_values(&result.plots[40].values, &[-1.0, 153.0]);
    assert_values(&result.plots[41].values, &[163.0, 166.0]);
    assert_values(&result.plots[42].values, &[-1.0, 163.0]);
    assert_values(&result.plots[43].values, &[-1.0, 163.0]);
    assert_values(&result.plots[44].values, &[174.0, 177.0]);
    assert_values(&result.plots[45].values, &[-1.0, 174.0]);
    assert_values(&result.plots[46].values, &[-1.0, 174.0]);
    assert_values(&result.plots[47].values, &[2.0, 5.0]);
    assert_values(&result.plots[48].values, &[-1.0, 2.0]);
    assert_values(&result.plots[49].values, &[-1.0, 2.0]);
    assert_values(&result.plots[50].values, &[2.0, 5.0]);
    assert_values(&result.plots[51].values, &[-1.0, 2.0]);
    assert_values(&result.plots[52].values, &[-1.0, 2.0]);
    assert_values(&result.plots[53].values, &[2.0, 5.0]);
    assert_values(&result.plots[54].values, &[-1.0, 2.0]);
    assert_values(&result.plots[55].values, &[-1.0, 2.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(5.0)))
        .expect("next forming update should start from confirmed UDT varip state");
    assert_values(&result.plots[0].values, &[2.0, 3.0, 4.0]);
    assert_values(&result.plots[1].values, &[2.0, 5.0, 6.0]);
    assert_values(&result.plots[2].values, &[-1.0, 2.0, 5.0]);
    assert_values(&result.plots[3].values, &[-1.0, 2.0, 5.0]);
    assert_values(&result.plots[4].values, &[1.0, 4.0, 5.0]);
    assert_values(&result.plots[5].values, &[2.0, 5.0, 6.0]);
    assert_values(&result.plots[6].values, &[-1.0, 2.0, 5.0]);
    assert_values(&result.plots[7].values, &[-1.0, 2.0, 5.0]);
    assert_values(&result.plots[8].values, &[2.0, 5.0, 6.0]);
    assert_values(&result.plots[9].values, &[-1.0, 2.0, 5.0]);
    assert_values(&result.plots[10].values, &[-1.0, 2.0, 5.0]);
    assert_values(&result.plots[11].values, &[2.0, 5.0, 6.0]);
    assert_values(&result.plots[12].values, &[-1.0, 2.0, 5.0]);
    assert_values(&result.plots[13].values, &[-1.0, 2.0, 5.0]);
    assert_values(&result.plots[14].values, &[2.0, 5.0, 6.0]);
    assert_values(&result.plots[15].values, &[-1.0, 2.0, 5.0]);
    assert_values(&result.plots[16].values, &[-1.0, 2.0, 5.0]);
    assert_values(&result.plots[17].values, &[2.0, 5.0, 6.0]);
    assert_values(&result.plots[18].values, &[-1.0, 2.0, 5.0]);
    assert_values(&result.plots[19].values, &[-1.0, 2.0, 5.0]);
    assert_values(&result.plots[20].values, &[3.0, 6.0, 7.0]);
    assert_values(&result.plots[21].values, &[-1.0, 3.0, 6.0]);
    assert_values(&result.plots[22].values, &[-1.0, 3.0, 6.0]);
    assert_values(&result.plots[23].values, &[103.0, 106.0, 107.0]);
    assert_values(&result.plots[24].values, &[-1.0, 103.0, 106.0]);
    assert_values(&result.plots[25].values, &[-1.0, 103.0, 106.0]);
    assert_values(&result.plots[26].values, &[114.0, 117.0, 118.0]);
    assert_values(&result.plots[27].values, &[-1.0, 114.0, 117.0]);
    assert_values(&result.plots[28].values, &[-1.0, 114.0, 117.0]);
    assert_values(&result.plots[29].values, &[122.0, 125.0, 126.0]);
    assert_values(&result.plots[30].values, &[-1.0, 122.0, 125.0]);
    assert_values(&result.plots[31].values, &[-1.0, 122.0, 125.0]);
    assert_values(&result.plots[32].values, &[132.0, 135.0, 136.0]);
    assert_values(&result.plots[33].values, &[-1.0, 132.0, 135.0]);
    assert_values(&result.plots[34].values, &[-1.0, 132.0, 135.0]);
    assert_values(&result.plots[35].values, &[142.0, 145.0, 146.0]);
    assert_values(&result.plots[36].values, &[-1.0, 142.0, 145.0]);
    assert_values(&result.plots[37].values, &[-1.0, 142.0, 145.0]);
    assert_values(&result.plots[38].values, &[153.0, 156.0, 157.0]);
    assert_values(&result.plots[39].values, &[-1.0, 153.0, 156.0]);
    assert_values(&result.plots[40].values, &[-1.0, 153.0, 156.0]);
    assert_values(&result.plots[41].values, &[163.0, 166.0, 167.0]);
    assert_values(&result.plots[42].values, &[-1.0, 163.0, 166.0]);
    assert_values(&result.plots[43].values, &[-1.0, 163.0, 166.0]);
    assert_values(&result.plots[44].values, &[174.0, 177.0, 178.0]);
    assert_values(&result.plots[45].values, &[-1.0, 174.0, 177.0]);
    assert_values(&result.plots[46].values, &[-1.0, 174.0, 177.0]);
    assert_values(&result.plots[47].values, &[2.0, 5.0, 6.0]);
    assert_values(&result.plots[48].values, &[-1.0, 2.0, 5.0]);
    assert_values(&result.plots[49].values, &[-1.0, 2.0, 5.0]);
    assert_values(&result.plots[50].values, &[2.0, 5.0, 6.0]);
    assert_values(&result.plots[51].values, &[-1.0, 2.0, 5.0]);
    assert_values(&result.plots[52].values, &[-1.0, 2.0, 5.0]);
    assert_values(&result.plots[53].values, &[2.0, 5.0, 6.0]);
    assert_values(&result.plots[54].values, &[-1.0, 2.0, 5.0]);
    assert_values(&result.plots[55].values, &[-1.0, 2.0, 5.0]);
}

#[test]
fn import_udt_varip_fixture_persists_intrabar_value_between_forming_updates() {
    let mut runtime = runtime_for_fixture("tests/fixtures/realtime/import_udt_varip.pine");

    let result = runtime
        .update(BarUpdate::historical(bar(1.0)))
        .expect("historical update should run");
    assert_values(&result.plots[0].values, &[2.0]);
    assert_values(&result.plots[1].values, &[2.0]);
    assert_values(&result.plots[2].values, &[-1.0]);
    assert_values(&result.plots[3].values, &[-1.0]);
    assert_values(&result.plots[4].values, &[1.0]);
    assert_values(&result.plots[5].values, &[2.0]);
    assert_values(&result.plots[6].values, &[-1.0]);
    assert_values(&result.plots[7].values, &[-1.0]);
    assert_values(&result.plots[8].values, &[2.0]);
    assert_values(&result.plots[9].values, &[-1.0]);
    assert_values(&result.plots[10].values, &[-1.0]);
    assert_values(&result.plots[11].values, &[102.0]);
    assert_values(&result.plots[12].values, &[-1.0]);
    assert_values(&result.plots[13].values, &[-1.0]);
    assert_values(&result.plots[14].values, &[112.0]);
    assert_values(&result.plots[15].values, &[-1.0]);
    assert_values(&result.plots[16].values, &[-1.0]);
    assert_values(&result.plots[17].values, &[122.0]);
    assert_values(&result.plots[18].values, &[-1.0]);
    assert_values(&result.plots[19].values, &[-1.0]);
    assert_values(&result.plots[20].values, &[133.0]);
    assert_values(&result.plots[21].values, &[-1.0]);
    assert_values(&result.plots[22].values, &[-1.0]);
    assert_values(&result.plots[23].values, &[143.0]);
    assert_values(&result.plots[24].values, &[-1.0]);
    assert_values(&result.plots[25].values, &[-1.0]);
    assert_values(&result.plots[26].values, &[154.0]);
    assert_values(&result.plots[27].values, &[-1.0]);
    assert_values(&result.plots[28].values, &[-1.0]);
    assert_values(&result.plots[29].values, &[162.0]);
    assert_values(&result.plots[30].values, &[-1.0]);
    assert_values(&result.plots[31].values, &[-1.0]);
    assert_values(&result.plots[32].values, &[172.0]);
    assert_values(&result.plots[33].values, &[-1.0]);
    assert_values(&result.plots[34].values, &[-1.0]);
    assert_values(&result.plots[35].values, &[182.0]);
    assert_values(&result.plots[36].values, &[-1.0]);
    assert_values(&result.plots[37].values, &[-1.0]);
    assert_values(&result.plots[38].values, &[193.0]);
    assert_values(&result.plots[39].values, &[-1.0]);
    assert_values(&result.plots[40].values, &[-1.0]);
    assert_values(&result.plots[41].values, &[203.0]);
    assert_values(&result.plots[42].values, &[-1.0]);
    assert_values(&result.plots[43].values, &[-1.0]);
    assert_values(&result.plots[44].values, &[214.0]);
    assert_values(&result.plots[45].values, &[-1.0]);
    assert_values(&result.plots[46].values, &[-1.0]);
    assert_values(&result.plots[47].values, &[2.0]);
    assert_values(&result.plots[48].values, &[-1.0]);
    assert_values(&result.plots[49].values, &[-1.0]);
    assert_values(&result.plots[50].values, &[2.0]);
    assert_values(&result.plots[51].values, &[-1.0]);
    assert_values(&result.plots[52].values, &[-1.0]);
    assert_values(&result.plots[53].values, &[2.0]);
    assert_values(&result.plots[54].values, &[-1.0]);
    assert_values(&result.plots[55].values, &[-1.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(2.0)))
        .expect("forming update should run");
    assert_values(&result.plots[0].values, &[2.0, 3.0]);
    assert_values(&result.plots[1].values, &[2.0, 3.0]);
    assert_values(&result.plots[2].values, &[-1.0, 2.0]);
    assert_values(&result.plots[3].values, &[-1.0, 2.0]);
    assert_values(&result.plots[4].values, &[1.0, 2.0]);
    assert_values(&result.plots[5].values, &[2.0, 3.0]);
    assert_values(&result.plots[6].values, &[-1.0, 2.0]);
    assert_values(&result.plots[7].values, &[-1.0, 2.0]);
    assert_values(&result.plots[8].values, &[2.0, 3.0]);
    assert_values(&result.plots[9].values, &[-1.0, 2.0]);
    assert_values(&result.plots[10].values, &[-1.0, 2.0]);
    assert_values(&result.plots[11].values, &[102.0, 103.0]);
    assert_values(&result.plots[12].values, &[-1.0, 102.0]);
    assert_values(&result.plots[13].values, &[-1.0, 102.0]);
    assert_values(&result.plots[14].values, &[112.0, 113.0]);
    assert_values(&result.plots[15].values, &[-1.0, 112.0]);
    assert_values(&result.plots[16].values, &[-1.0, 112.0]);
    assert_values(&result.plots[17].values, &[122.0, 123.0]);
    assert_values(&result.plots[18].values, &[-1.0, 122.0]);
    assert_values(&result.plots[19].values, &[-1.0, 122.0]);
    assert_values(&result.plots[20].values, &[133.0, 134.0]);
    assert_values(&result.plots[21].values, &[-1.0, 133.0]);
    assert_values(&result.plots[22].values, &[-1.0, 133.0]);
    assert_values(&result.plots[23].values, &[143.0, 144.0]);
    assert_values(&result.plots[24].values, &[-1.0, 143.0]);
    assert_values(&result.plots[25].values, &[-1.0, 143.0]);
    assert_values(&result.plots[26].values, &[154.0, 155.0]);
    assert_values(&result.plots[27].values, &[-1.0, 154.0]);
    assert_values(&result.plots[28].values, &[-1.0, 154.0]);
    assert_values(&result.plots[29].values, &[162.0, 163.0]);
    assert_values(&result.plots[30].values, &[-1.0, 162.0]);
    assert_values(&result.plots[31].values, &[-1.0, 162.0]);
    assert_values(&result.plots[32].values, &[172.0, 173.0]);
    assert_values(&result.plots[33].values, &[-1.0, 172.0]);
    assert_values(&result.plots[34].values, &[-1.0, 172.0]);
    assert_values(&result.plots[35].values, &[182.0, 183.0]);
    assert_values(&result.plots[36].values, &[-1.0, 182.0]);
    assert_values(&result.plots[37].values, &[-1.0, 182.0]);
    assert_values(&result.plots[38].values, &[193.0, 194.0]);
    assert_values(&result.plots[39].values, &[-1.0, 193.0]);
    assert_values(&result.plots[40].values, &[-1.0, 193.0]);
    assert_values(&result.plots[41].values, &[203.0, 204.0]);
    assert_values(&result.plots[42].values, &[-1.0, 203.0]);
    assert_values(&result.plots[43].values, &[-1.0, 203.0]);
    assert_values(&result.plots[44].values, &[214.0, 215.0]);
    assert_values(&result.plots[45].values, &[-1.0, 214.0]);
    assert_values(&result.plots[46].values, &[-1.0, 214.0]);
    assert_values(&result.plots[47].values, &[2.0, 3.0]);
    assert_values(&result.plots[48].values, &[-1.0, 2.0]);
    assert_values(&result.plots[49].values, &[-1.0, 2.0]);
    assert_values(&result.plots[50].values, &[2.0, 3.0]);
    assert_values(&result.plots[51].values, &[-1.0, 2.0]);
    assert_values(&result.plots[52].values, &[-1.0, 2.0]);
    assert_values(&result.plots[53].values, &[2.0, 3.0]);
    assert_values(&result.plots[54].values, &[-1.0, 2.0]);
    assert_values(&result.plots[55].values, &[-1.0, 2.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(3.0)))
        .expect("second forming update should retain imported UDT varip state");
    assert_values(&result.plots[0].values, &[2.0, 3.0]);
    assert_values(&result.plots[1].values, &[2.0, 4.0]);
    assert_values(&result.plots[2].values, &[-1.0, 2.0]);
    assert_values(&result.plots[3].values, &[-1.0, 2.0]);
    assert_values(&result.plots[4].values, &[1.0, 3.0]);
    assert_values(&result.plots[5].values, &[2.0, 4.0]);
    assert_values(&result.plots[6].values, &[-1.0, 2.0]);
    assert_values(&result.plots[7].values, &[-1.0, 2.0]);
    assert_values(&result.plots[8].values, &[2.0, 4.0]);
    assert_values(&result.plots[9].values, &[-1.0, 2.0]);
    assert_values(&result.plots[10].values, &[-1.0, 2.0]);
    assert_values(&result.plots[11].values, &[102.0, 104.0]);
    assert_values(&result.plots[12].values, &[-1.0, 102.0]);
    assert_values(&result.plots[13].values, &[-1.0, 102.0]);
    assert_values(&result.plots[14].values, &[112.0, 114.0]);
    assert_values(&result.plots[15].values, &[-1.0, 112.0]);
    assert_values(&result.plots[16].values, &[-1.0, 112.0]);
    assert_values(&result.plots[17].values, &[122.0, 124.0]);
    assert_values(&result.plots[18].values, &[-1.0, 122.0]);
    assert_values(&result.plots[19].values, &[-1.0, 122.0]);
    assert_values(&result.plots[20].values, &[133.0, 135.0]);
    assert_values(&result.plots[21].values, &[-1.0, 133.0]);
    assert_values(&result.plots[22].values, &[-1.0, 133.0]);
    assert_values(&result.plots[23].values, &[143.0, 145.0]);
    assert_values(&result.plots[24].values, &[-1.0, 143.0]);
    assert_values(&result.plots[25].values, &[-1.0, 143.0]);
    assert_values(&result.plots[26].values, &[154.0, 156.0]);
    assert_values(&result.plots[27].values, &[-1.0, 154.0]);
    assert_values(&result.plots[28].values, &[-1.0, 154.0]);
    assert_values(&result.plots[29].values, &[162.0, 164.0]);
    assert_values(&result.plots[30].values, &[-1.0, 162.0]);
    assert_values(&result.plots[31].values, &[-1.0, 162.0]);
    assert_values(&result.plots[32].values, &[172.0, 174.0]);
    assert_values(&result.plots[33].values, &[-1.0, 172.0]);
    assert_values(&result.plots[34].values, &[-1.0, 172.0]);
    assert_values(&result.plots[35].values, &[182.0, 184.0]);
    assert_values(&result.plots[36].values, &[-1.0, 182.0]);
    assert_values(&result.plots[37].values, &[-1.0, 182.0]);
    assert_values(&result.plots[38].values, &[193.0, 195.0]);
    assert_values(&result.plots[39].values, &[-1.0, 193.0]);
    assert_values(&result.plots[40].values, &[-1.0, 193.0]);
    assert_values(&result.plots[41].values, &[203.0, 205.0]);
    assert_values(&result.plots[42].values, &[-1.0, 203.0]);
    assert_values(&result.plots[43].values, &[-1.0, 203.0]);
    assert_values(&result.plots[44].values, &[214.0, 216.0]);
    assert_values(&result.plots[45].values, &[-1.0, 214.0]);
    assert_values(&result.plots[46].values, &[-1.0, 214.0]);
    assert_values(&result.plots[47].values, &[2.0, 4.0]);
    assert_values(&result.plots[48].values, &[-1.0, 2.0]);
    assert_values(&result.plots[49].values, &[-1.0, 2.0]);
    assert_values(&result.plots[50].values, &[2.0, 4.0]);
    assert_values(&result.plots[51].values, &[-1.0, 2.0]);
    assert_values(&result.plots[52].values, &[-1.0, 2.0]);
    assert_values(&result.plots[53].values, &[2.0, 4.0]);
    assert_values(&result.plots[54].values, &[-1.0, 2.0]);
    assert_values(&result.plots[55].values, &[-1.0, 2.0]);

    let result = runtime
        .update(BarUpdate::confirmed(bar(4.0)))
        .expect("confirmed update should commit imported UDT varip state");
    assert_values(&result.plots[0].values, &[2.0, 3.0]);
    assert_values(&result.plots[1].values, &[2.0, 5.0]);
    assert_values(&result.plots[2].values, &[-1.0, 2.0]);
    assert_values(&result.plots[3].values, &[-1.0, 2.0]);
    assert_values(&result.plots[4].values, &[1.0, 4.0]);
    assert_values(&result.plots[5].values, &[2.0, 5.0]);
    assert_values(&result.plots[6].values, &[-1.0, 2.0]);
    assert_values(&result.plots[7].values, &[-1.0, 2.0]);
    assert_values(&result.plots[8].values, &[2.0, 5.0]);
    assert_values(&result.plots[9].values, &[-1.0, 2.0]);
    assert_values(&result.plots[10].values, &[-1.0, 2.0]);
    assert_values(&result.plots[11].values, &[102.0, 105.0]);
    assert_values(&result.plots[12].values, &[-1.0, 102.0]);
    assert_values(&result.plots[13].values, &[-1.0, 102.0]);
    assert_values(&result.plots[14].values, &[112.0, 115.0]);
    assert_values(&result.plots[15].values, &[-1.0, 112.0]);
    assert_values(&result.plots[16].values, &[-1.0, 112.0]);
    assert_values(&result.plots[17].values, &[122.0, 125.0]);
    assert_values(&result.plots[18].values, &[-1.0, 122.0]);
    assert_values(&result.plots[19].values, &[-1.0, 122.0]);
    assert_values(&result.plots[20].values, &[133.0, 136.0]);
    assert_values(&result.plots[21].values, &[-1.0, 133.0]);
    assert_values(&result.plots[22].values, &[-1.0, 133.0]);
    assert_values(&result.plots[23].values, &[143.0, 146.0]);
    assert_values(&result.plots[24].values, &[-1.0, 143.0]);
    assert_values(&result.plots[25].values, &[-1.0, 143.0]);
    assert_values(&result.plots[26].values, &[154.0, 157.0]);
    assert_values(&result.plots[27].values, &[-1.0, 154.0]);
    assert_values(&result.plots[28].values, &[-1.0, 154.0]);
    assert_values(&result.plots[29].values, &[162.0, 165.0]);
    assert_values(&result.plots[30].values, &[-1.0, 162.0]);
    assert_values(&result.plots[31].values, &[-1.0, 162.0]);
    assert_values(&result.plots[32].values, &[172.0, 175.0]);
    assert_values(&result.plots[33].values, &[-1.0, 172.0]);
    assert_values(&result.plots[34].values, &[-1.0, 172.0]);
    assert_values(&result.plots[35].values, &[182.0, 185.0]);
    assert_values(&result.plots[36].values, &[-1.0, 182.0]);
    assert_values(&result.plots[37].values, &[-1.0, 182.0]);
    assert_values(&result.plots[38].values, &[193.0, 196.0]);
    assert_values(&result.plots[39].values, &[-1.0, 193.0]);
    assert_values(&result.plots[40].values, &[-1.0, 193.0]);
    assert_values(&result.plots[41].values, &[203.0, 206.0]);
    assert_values(&result.plots[42].values, &[-1.0, 203.0]);
    assert_values(&result.plots[43].values, &[-1.0, 203.0]);
    assert_values(&result.plots[44].values, &[214.0, 217.0]);
    assert_values(&result.plots[45].values, &[-1.0, 214.0]);
    assert_values(&result.plots[46].values, &[-1.0, 214.0]);
    assert_values(&result.plots[47].values, &[2.0, 5.0]);
    assert_values(&result.plots[48].values, &[-1.0, 2.0]);
    assert_values(&result.plots[49].values, &[-1.0, 2.0]);
    assert_values(&result.plots[50].values, &[2.0, 5.0]);
    assert_values(&result.plots[51].values, &[-1.0, 2.0]);
    assert_values(&result.plots[52].values, &[-1.0, 2.0]);
    assert_values(&result.plots[53].values, &[2.0, 5.0]);
    assert_values(&result.plots[54].values, &[-1.0, 2.0]);
    assert_values(&result.plots[55].values, &[-1.0, 2.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(5.0)))
        .expect("next forming update should start from confirmed imported UDT varip state");
    assert_values(&result.plots[0].values, &[2.0, 3.0, 4.0]);
    assert_values(&result.plots[1].values, &[2.0, 5.0, 6.0]);
    assert_values(&result.plots[2].values, &[-1.0, 2.0, 5.0]);
    assert_values(&result.plots[3].values, &[-1.0, 2.0, 5.0]);
    assert_values(&result.plots[4].values, &[1.0, 4.0, 5.0]);
    assert_values(&result.plots[5].values, &[2.0, 5.0, 6.0]);
    assert_values(&result.plots[6].values, &[-1.0, 2.0, 5.0]);
    assert_values(&result.plots[7].values, &[-1.0, 2.0, 5.0]);
    assert_values(&result.plots[8].values, &[2.0, 5.0, 6.0]);
    assert_values(&result.plots[9].values, &[-1.0, 2.0, 5.0]);
    assert_values(&result.plots[10].values, &[-1.0, 2.0, 5.0]);
    assert_values(&result.plots[11].values, &[102.0, 105.0, 106.0]);
    assert_values(&result.plots[12].values, &[-1.0, 102.0, 105.0]);
    assert_values(&result.plots[13].values, &[-1.0, 102.0, 105.0]);
    assert_values(&result.plots[14].values, &[112.0, 115.0, 116.0]);
    assert_values(&result.plots[15].values, &[-1.0, 112.0, 115.0]);
    assert_values(&result.plots[16].values, &[-1.0, 112.0, 115.0]);
    assert_values(&result.plots[17].values, &[122.0, 125.0, 126.0]);
    assert_values(&result.plots[18].values, &[-1.0, 122.0, 125.0]);
    assert_values(&result.plots[19].values, &[-1.0, 122.0, 125.0]);
    assert_values(&result.plots[20].values, &[133.0, 136.0, 137.0]);
    assert_values(&result.plots[21].values, &[-1.0, 133.0, 136.0]);
    assert_values(&result.plots[22].values, &[-1.0, 133.0, 136.0]);
    assert_values(&result.plots[23].values, &[143.0, 146.0, 147.0]);
    assert_values(&result.plots[24].values, &[-1.0, 143.0, 146.0]);
    assert_values(&result.plots[25].values, &[-1.0, 143.0, 146.0]);
    assert_values(&result.plots[26].values, &[154.0, 157.0, 158.0]);
    assert_values(&result.plots[27].values, &[-1.0, 154.0, 157.0]);
    assert_values(&result.plots[28].values, &[-1.0, 154.0, 157.0]);
    assert_values(&result.plots[29].values, &[162.0, 165.0, 166.0]);
    assert_values(&result.plots[30].values, &[-1.0, 162.0, 165.0]);
    assert_values(&result.plots[31].values, &[-1.0, 162.0, 165.0]);
    assert_values(&result.plots[32].values, &[172.0, 175.0, 176.0]);
    assert_values(&result.plots[33].values, &[-1.0, 172.0, 175.0]);
    assert_values(&result.plots[34].values, &[-1.0, 172.0, 175.0]);
    assert_values(&result.plots[35].values, &[182.0, 185.0, 186.0]);
    assert_values(&result.plots[36].values, &[-1.0, 182.0, 185.0]);
    assert_values(&result.plots[37].values, &[-1.0, 182.0, 185.0]);
    assert_values(&result.plots[38].values, &[193.0, 196.0, 197.0]);
    assert_values(&result.plots[39].values, &[-1.0, 193.0, 196.0]);
    assert_values(&result.plots[40].values, &[-1.0, 193.0, 196.0]);
    assert_values(&result.plots[41].values, &[203.0, 206.0, 207.0]);
    assert_values(&result.plots[42].values, &[-1.0, 203.0, 206.0]);
    assert_values(&result.plots[43].values, &[-1.0, 203.0, 206.0]);
    assert_values(&result.plots[44].values, &[214.0, 217.0, 218.0]);
    assert_values(&result.plots[45].values, &[-1.0, 214.0, 217.0]);
    assert_values(&result.plots[46].values, &[-1.0, 214.0, 217.0]);
    assert_values(&result.plots[47].values, &[2.0, 5.0, 6.0]);
    assert_values(&result.plots[48].values, &[-1.0, 2.0, 5.0]);
    assert_values(&result.plots[49].values, &[-1.0, 2.0, 5.0]);
    assert_values(&result.plots[50].values, &[2.0, 5.0, 6.0]);
    assert_values(&result.plots[51].values, &[-1.0, 2.0, 5.0]);
    assert_values(&result.plots[52].values, &[-1.0, 2.0, 5.0]);
    assert_values(&result.plots[53].values, &[2.0, 5.0, 6.0]);
    assert_values(&result.plots[54].values, &[-1.0, 2.0, 5.0]);
    assert_values(&result.plots[55].values, &[-1.0, 2.0, 5.0]);
}

#[test]
fn varip_local_fixture_persists_intrabar_state_per_declaration_site() {
    let mut runtime = runtime_for_fixture("tests/fixtures/realtime/varip_local.pine");

    let result = runtime
        .update(BarUpdate::historical(bar(1.0)))
        .expect("historical update should run");
    assert_values(&result.plots[0].values, &[0.0]);
    assert_values(&result.plots[1].values, &[2.0]);
    assert_values(&result.plots[2].values, &[2.0]);
    assert_values(&result.plots[3].values, &[1.0]);
    assert_values(&result.plots[4].values, &[10.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(2.0)))
        .expect("forming update with skipped branch should run");
    assert_values(&result.plots[0].values, &[0.0, 0.0]);
    assert_values(&result.plots[1].values, &[2.0, 4.0]);
    assert_values(&result.plots[2].values, &[2.0, 4.0]);
    assert_values(&result.plots[3].values, &[1.0, 2.0]);
    assert_values(&result.plots[4].values, &[10.0, 20.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(3.0)))
        .expect("first reached branch should initialize after skipped updates");
    assert_values(&result.plots[0].values, &[0.0, 1.0]);
    assert_values(&result.plots[1].values, &[2.0, 6.0]);
    assert_values(&result.plots[2].values, &[2.0, 6.0]);
    assert_values(&result.plots[3].values, &[1.0, 3.0]);
    assert_values(&result.plots[4].values, &[10.0, 30.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(4.0)))
        .expect("second reached branch should retain intrabar state");
    assert_values(&result.plots[0].values, &[0.0, 2.0]);
    assert_values(&result.plots[1].values, &[2.0, 8.0]);
    assert_values(&result.plots[2].values, &[2.0, 8.0]);
    assert_values(&result.plots[3].values, &[1.0, 4.0]);
    assert_values(&result.plots[4].values, &[10.0, 40.0]);

    let result = runtime
        .update(BarUpdate::confirmed(bar(5.0)))
        .expect("confirmed update should commit local varip state");
    assert_values(&result.plots[0].values, &[0.0, 3.0]);
    assert_values(&result.plots[1].values, &[2.0, 10.0]);
    assert_values(&result.plots[2].values, &[2.0, 10.0]);
    assert_values(&result.plots[3].values, &[1.0, 5.0]);
    assert_values(&result.plots[4].values, &[10.0, 50.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(6.0)))
        .expect("next forming update should start from confirmed local varip state");
    assert_values(&result.plots[0].values, &[0.0, 3.0, 4.0]);
    assert_values(&result.plots[1].values, &[2.0, 10.0, 12.0]);
    assert_values(&result.plots[2].values, &[2.0, 10.0, 12.0]);
    assert_values(&result.plots[3].values, &[1.0, 5.0, 6.0]);
    assert_values(&result.plots[4].values, &[10.0, 50.0, 60.0]);
}

#[test]
fn conditional_ta_fixture_rolls_back_callsite_state_between_forming_updates() {
    let mut runtime = runtime_for_fixture("tests/fixtures/realtime/conditional_ta_rollback.pine");

    let result = runtime
        .update(BarUpdate::historical(bar_ohlc(1.0, 2.0)))
        .expect("historical update should run");
    assert_values(&result.plots[0].values, &[2.0]);

    let result = runtime
        .update(BarUpdate::forming(bar_ohlc(3.0, 4.0)))
        .expect("forming update should run");
    assert_values(&result.plots[0].values, &[2.0, 3.333333333333333]);
    assert_values(&runtime.confirmed_result().plots[0].values, &[2.0]);

    let result = runtime
        .update(BarUpdate::forming(bar_ohlc(7.0, 8.0)))
        .expect("second forming update should roll back callsite state");
    assert_values(&result.plots[0].values, &[2.0, 6.0]);
    assert_values(&runtime.confirmed_result().plots[0].values, &[2.0]);

    let result = runtime
        .update(BarUpdate::confirmed(bar_ohlc(4.0, 5.0)))
        .expect("confirmed update should commit callsite state");
    assert_values(&result.plots[0].values, &[2.0, 4.0]);
    assert_values(&runtime.confirmed_result().plots[0].values, &[2.0, 4.0]);

    let result = runtime
        .update(BarUpdate::forming(bar_ohlc(4.0, 3.0)))
        .expect("forming update with skipped branch should run");
    assert_values(&result.plots[0].values, &[2.0, 4.0, 3.0]);
    assert_values(&runtime.confirmed_result().plots[0].values, &[2.0, 4.0]);

    let result = runtime
        .update(BarUpdate::forming(bar_ohlc(7.0, 8.0)))
        .expect("forming update should ignore skipped-branch callsite state");
    assert_values(&result.plots[0].values, &[2.0, 4.0, 6.666666666666667]);
}

#[test]
fn array_rollback_fixture_restores_confirmed_store_between_forming_updates() {
    let mut runtime = runtime_for_fixture("tests/fixtures/realtime/array_rollback.pine");

    let result = runtime
        .update(BarUpdate::historical(bar(1.0)))
        .expect("historical update should run");
    assert_values(&result.plots[0].values, &[1.0]);
    assert_values(&result.plots[1].values, &[1.0]);
    assert_values(&result.plots[2].values, &[1.0]);
    assert_values(&result.plots[3].values, &[0.0]);
    assert_values(&result.plots[4].values, &[1.0]);
    assert_values(&result.plots[5].values, &[1.0]);
    assert_values(&result.plots[6].values, &[1.0]);
    assert_values(&result.plots[7].values, &[1.0]);
    assert_values(&result.plots[8].values, &[1.0]);
    assert_values(&result.plots[9].values, &[1.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(2.0)))
        .expect("forming update should run");
    assert_values(&result.plots[0].values, &[1.0, 2.0]);
    assert_values(&result.plots[1].values, &[1.0, 1.0]);
    assert_values(&result.plots[2].values, &[1.0, 2.0]);
    assert_values(&result.plots[3].values, &[0.0, 0.0]);
    assert_values(&result.plots[4].values, &[1.0, 2.0]);
    assert_values(&result.plots[5].values, &[1.0, 1.0]);
    assert_values(&result.plots[6].values, &[1.0, 2.0]);
    assert_values(&result.plots[7].values, &[1.0, 1.0]);
    assert_values(&result.plots[8].values, &[1.0, 2.0]);
    assert_values(&result.plots[9].values, &[1.0, 1.0]);
    assert_values(&runtime.confirmed_result().plots[0].values, &[1.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(3.0)))
        .expect("second forming update should roll back array store");
    assert_values(&result.plots[0].values, &[1.0, 2.0]);
    assert_values(&result.plots[1].values, &[1.0, 1.0]);
    assert_values(&result.plots[2].values, &[1.0, 2.0]);
    assert_values(&result.plots[3].values, &[0.0, 0.0]);
    assert_values(&result.plots[4].values, &[1.0, 2.0]);
    assert_values(&result.plots[5].values, &[1.0, 1.0]);
    assert_values(&result.plots[6].values, &[1.0, 2.0]);
    assert_values(&result.plots[7].values, &[1.0, 1.0]);
    assert_values(&result.plots[8].values, &[1.0, 2.0]);
    assert_values(&result.plots[9].values, &[1.0, 1.0]);
    assert_values(&runtime.confirmed_result().plots[0].values, &[1.0]);

    let result = runtime
        .update(BarUpdate::confirmed(bar(4.0)))
        .expect("confirmed update should commit array mutation");
    assert_values(&result.plots[0].values, &[1.0, 2.0]);
    assert_values(&result.plots[2].values, &[1.0, 2.0]);
    assert_values(&result.plots[4].values, &[1.0, 2.0]);
    assert_values(&result.plots[6].values, &[1.0, 2.0]);
    assert_values(&result.plots[8].values, &[1.0, 2.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(5.0)))
        .expect("next forming update should start from confirmed array store");
    assert_values(&result.plots[0].values, &[1.0, 2.0, 3.0]);
    assert_values(&result.plots[2].values, &[1.0, 2.0, 3.0]);
    assert_values(&result.plots[4].values, &[1.0, 2.0, 3.0]);
    assert_values(&result.plots[6].values, &[1.0, 2.0, 3.0]);
    assert_values(&result.plots[8].values, &[1.0, 2.0, 3.0]);
}

#[test]
fn matrix_rollback_fixture_restores_confirmed_store_between_forming_updates() {
    let mut runtime = runtime_for_fixture("tests/fixtures/realtime/matrix_rollback.pine");

    let result = runtime
        .update(BarUpdate::historical(bar(1.0)))
        .expect("historical update should run");
    assert_values(&result.plots[0].values, &[1.0]);
    assert_values(&result.plots[1].values, &[1.0]);
    assert_values(&result.plots[2].values, &[1.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(2.0)))
        .expect("forming update should run");
    assert_values(&result.plots[0].values, &[1.0, 2.0]);
    assert_values(&result.plots[1].values, &[1.0, 1.0]);
    assert_values(&result.plots[2].values, &[1.0, 1.0]);
    assert_values(&runtime.confirmed_result().plots[0].values, &[1.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(3.0)))
        .expect("second forming update should roll back matrix store");
    assert_values(&result.plots[0].values, &[1.0, 3.0]);
    assert_values(&result.plots[1].values, &[1.0, 1.0]);
    assert_values(&result.plots[2].values, &[1.0, 1.0]);
    assert_values(&runtime.confirmed_result().plots[0].values, &[1.0]);

    let result = runtime
        .update(BarUpdate::confirmed(bar(4.0)))
        .expect("confirmed update should commit matrix mutation");
    assert_values(&result.plots[0].values, &[1.0, 4.0]);
    assert_values(&runtime.confirmed_result().plots[0].values, &[1.0, 4.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(5.0)))
        .expect("next forming update should start from confirmed matrix store");
    assert_values(&result.plots[0].values, &[1.0, 4.0, 5.0]);
    assert_values(&result.plots[1].values, &[1.0, 1.0, 1.0]);
    assert_values(&result.plots[2].values, &[1.0, 1.0, 1.0]);
}

#[test]
fn matrix_reshape_rollback_fixture_restores_confirmed_shape_between_forming_updates() {
    let mut runtime = runtime_for_fixture("tests/fixtures/realtime/matrix_reshape_rollback.pine");

    let result = runtime
        .update(BarUpdate::historical(bar_ohlc(1.0, 1.0)))
        .expect("historical update should run");
    assert_values(&result.plots[0].values, &[1.0]);
    assert_values(&result.plots[1].values, &[2.0]);

    let result = runtime
        .update(BarUpdate::forming(bar_ohlc(1.0, 2.0)))
        .expect("forming update should reshape matrix");
    assert_values(&result.plots[0].values, &[1.0, 2.0]);
    assert_values(&result.plots[1].values, &[2.0, 1.0]);
    assert_values(&runtime.confirmed_result().plots[0].values, &[1.0]);
    assert_values(&runtime.confirmed_result().plots[1].values, &[2.0]);

    let result = runtime
        .update(BarUpdate::forming(bar_ohlc(4.0, 3.0)))
        .expect("second forming update should roll back matrix shape");
    assert_values(&result.plots[0].values, &[1.0, 1.0]);
    assert_values(&result.plots[1].values, &[2.0, 2.0]);
    assert_values(&runtime.confirmed_result().plots[0].values, &[1.0]);
    assert_values(&runtime.confirmed_result().plots[1].values, &[2.0]);

    let result = runtime
        .update(BarUpdate::confirmed(bar_ohlc(1.0, 4.0)))
        .expect("confirmed update should commit reshaped matrix");
    assert_values(&result.plots[0].values, &[1.0, 2.0]);
    assert_values(&result.plots[1].values, &[2.0, 1.0]);
    assert_values(&runtime.confirmed_result().plots[0].values, &[1.0, 2.0]);
    assert_values(&runtime.confirmed_result().plots[1].values, &[2.0, 1.0]);

    let result = runtime
        .update(BarUpdate::forming(bar_ohlc(6.0, 5.0)))
        .expect("next forming update should start from confirmed matrix shape");
    assert_values(&result.plots[0].values, &[1.0, 2.0, 1.0]);
    assert_values(&result.plots[1].values, &[2.0, 1.0, 2.0]);
}

#[test]
fn for_in_fixture_rolls_back_loop_body_array_mutation_between_forming_updates() {
    let fixture = "tests/fixtures/realtime/for_in_rollback.pine";
    let mut runtime = runtime_for_fixture(fixture);

    let result = runtime
        .update(BarUpdate::historical(bar(1.0)))
        .expect("historical update should run");
    assert_values(&result.plots[0].values, &[1.0]);
    assert_values(&result.plots[1].values, &[1.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(2.0)))
        .expect("forming update should run");
    assert_values(&result.plots[0].values, &[1.0, 4.0]);
    assert_values(&result.plots[1].values, &[1.0, 2.0]);
    assert_values(&runtime.confirmed_result().plots[0].values, &[1.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(3.0)))
        .expect("second forming update should roll back for-in array mutation");
    assert_values(&result.plots[0].values, &[1.0, 4.0]);
    assert_values(&result.plots[1].values, &[1.0, 2.0]);
    assert_values(&runtime.confirmed_result().plots[0].values, &[1.0]);

    let result = runtime
        .update(BarUpdate::confirmed(bar(4.0)))
        .expect("confirmed update should commit for-in array mutation");
    assert_values(&result.plots[0].values, &[1.0, 2.0]);
    assert_values(&result.plots[1].values, &[1.0, 2.0]);
    assert_eq!(runtime.confirmed_result().plots, result.plots);

    let hir = hir_for_fixture(fixture);
    let historical =
        run_historical(&hir, &[bar(1.0), bar(4.0)]).expect("historical execution should run");
    assert_eq!(result.plots, historical.plots);

    let result = runtime
        .update(BarUpdate::forming(bar(5.0)))
        .expect("next forming update should start from confirmed for-in array store");
    assert_values(&result.plots[0].values, &[1.0, 2.0, 6.0]);
    assert_values(&result.plots[1].values, &[1.0, 2.0, 3.0]);
}

#[test]
fn for_in_fixture_preserves_varip_array_mutation_between_forming_updates() {
    let mut runtime = runtime_for_fixture("tests/fixtures/realtime/for_in_varip.pine");

    let result = runtime
        .update(BarUpdate::historical(bar(1.0)))
        .expect("historical update should run");
    assert_values(&result.plots[0].values, &[1.0]);
    assert_values(&result.plots[1].values, &[1.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(2.0)))
        .expect("forming update should run");
    assert_values(&result.plots[0].values, &[1.0, 4.0]);
    assert_values(&result.plots[1].values, &[1.0, 2.0]);
    assert_values(&runtime.confirmed_result().plots[0].values, &[1.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(3.0)))
        .expect("second forming update should carry varip for-in mutation");
    assert_values(&result.plots[0].values, &[1.0, 10.0]);
    assert_values(&result.plots[1].values, &[1.0, 23.0]);
    assert_values(&runtime.confirmed_result().plots[0].values, &[1.0]);

    let result = runtime
        .update(BarUpdate::confirmed(bar(4.0)))
        .expect("confirmed update should commit carried varip for-in mutation");
    assert_values(&result.plots[0].values, &[1.0, 11.0]);
    assert_values(&result.plots[1].values, &[1.0, 74.0]);
    assert_eq!(runtime.confirmed_result().plots, result.plots);

    let result = runtime
        .update(BarUpdate::forming(bar(5.0)))
        .expect("next forming update should start from confirmed varip for-in state");
    assert_values(&result.plots[0].values, &[1.0, 11.0, 24.0]);
    assert_values(&result.plots[1].values, &[1.0, 74.0, 75.0]);
}

#[test]
fn varip_array_fixture_persists_intrabar_backing_store_between_forming_updates() {
    let mut runtime = runtime_for_fixture("tests/fixtures/realtime/varip_array.pine");

    let result = runtime
        .update(BarUpdate::historical(bar(1.0)))
        .expect("historical update should run");
    assert_values(&result.plots[0].values, &[1.0]);
    assert_values(&result.plots[1].values, &[1.0]);
    assert_values(&result.plots[2].values, &[2.0]);
    assert_values(&result.plots[3].values, &[1.0]);
    assert_values(&result.plots[4].values, &[2.0]);
    assert_values(&result.plots[5].values, &[0.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(2.0)))
        .expect("forming update should run");
    assert_values(&result.plots[0].values, &[1.0, 2.0]);
    assert_values(&result.plots[1].values, &[1.0, 2.0]);
    assert_values(&result.plots[2].values, &[2.0, 3.0]);
    assert_values(&result.plots[3].values, &[1.0, 2.0]);
    assert_values(&result.plots[4].values, &[2.0, 3.0]);
    assert_values(&result.plots[5].values, &[0.0, 0.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(3.0)))
        .expect("second forming update should retain varip array state");
    assert_values(&result.plots[0].values, &[1.0, 3.0]);
    assert_values(&result.plots[1].values, &[1.0, 2.0]);
    assert_values(&result.plots[2].values, &[2.0, 4.0]);
    assert_values(&result.plots[3].values, &[1.0, 3.0]);
    assert_values(&result.plots[4].values, &[2.0, 4.0]);
    assert_values(&result.plots[5].values, &[0.0, 1.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(4.0)))
        .expect("third forming update should keep retaining varip array state");
    assert_values(&result.plots[0].values, &[1.0, 4.0]);
    assert_values(&result.plots[1].values, &[1.0, 2.0]);
    assert_values(&result.plots[2].values, &[2.0, 5.0]);
    assert_values(&result.plots[3].values, &[1.0, 4.0]);
    assert_values(&result.plots[4].values, &[2.0, 5.0]);
    assert_values(&result.plots[5].values, &[0.0, 2.0]);

    let result = runtime
        .update(BarUpdate::confirmed(bar(5.0)))
        .expect("confirmed update should commit varip array state");
    assert_values(&result.plots[0].values, &[1.0, 5.0]);
    assert_values(&result.plots[1].values, &[1.0, 2.0]);
    assert_values(&result.plots[2].values, &[2.0, 6.0]);
    assert_values(&result.plots[3].values, &[1.0, 5.0]);
    assert_values(&result.plots[4].values, &[2.0, 6.0]);
    assert_values(&result.plots[5].values, &[0.0, 3.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(6.0)))
        .expect("next forming update should start from confirmed varip array state");
    assert_values(&result.plots[0].values, &[1.0, 5.0, 6.0]);
    assert_values(&result.plots[1].values, &[1.0, 2.0, 3.0]);
    assert_values(&result.plots[2].values, &[2.0, 6.0, 7.0]);
    assert_values(&result.plots[3].values, &[1.0, 5.0, 6.0]);
    assert_values(&result.plots[4].values, &[2.0, 6.0, 7.0]);
    assert_values(&result.plots[5].values, &[0.0, 3.0, 4.0]);
}

#[test]
fn user_type_array_varip_fixture_persists_intrabar_backing_store_between_forming_updates() {
    let mut runtime = runtime_for_fixture("tests/fixtures/realtime/user_type_array_varip.pine");

    let result = runtime
        .update(BarUpdate::historical(bar(1.0)))
        .expect("historical update should run");
    assert_values(&result.plots[0].values, &[1.0]);
    assert_values(&result.plots[1].values, &[1.0]);
    assert_values(&result.plots[2].values, &[2.0]);
    assert_values(&result.plots[3].values, &[101.0]);
    assert_values(&result.plots[4].values, &[2.0]);
    assert_values(&result.plots[5].values, &[211.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(2.0)))
        .expect("forming update should run");
    assert_values(&result.plots[0].values, &[1.0, 2.0]);
    assert_values(&result.plots[1].values, &[1.0, 2.0]);
    assert_values(&result.plots[2].values, &[2.0, 3.0]);
    assert_values(&result.plots[3].values, &[101.0, 102.0]);
    assert_values(&result.plots[4].values, &[2.0, 3.0]);
    assert_values(&result.plots[5].values, &[211.0, 212.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(3.0)))
        .expect("second forming update should retain UDT array varip state");
    assert_values(&result.plots[0].values, &[1.0, 3.0]);
    assert_values(&result.plots[1].values, &[1.0, 3.0]);
    assert_values(&result.plots[2].values, &[2.0, 4.0]);
    assert_values(&result.plots[3].values, &[101.0, 103.0]);
    assert_values(&result.plots[4].values, &[2.0, 4.0]);
    assert_values(&result.plots[5].values, &[211.0, 213.0]);

    let result = runtime
        .update(BarUpdate::confirmed(bar(4.0)))
        .expect("confirmed update should commit UDT array varip state");
    assert_values(&result.plots[0].values, &[1.0, 4.0]);
    assert_values(&result.plots[1].values, &[1.0, 4.0]);
    assert_values(&result.plots[2].values, &[2.0, 5.0]);
    assert_values(&result.plots[3].values, &[101.0, 104.0]);
    assert_values(&result.plots[4].values, &[2.0, 5.0]);
    assert_values(&result.plots[5].values, &[211.0, 214.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(5.0)))
        .expect("next forming update should start from confirmed UDT array varip state");
    assert_values(&result.plots[0].values, &[1.0, 4.0, 5.0]);
    assert_values(&result.plots[1].values, &[1.0, 4.0, 5.0]);
    assert_values(&result.plots[2].values, &[2.0, 5.0, 6.0]);
    assert_values(&result.plots[3].values, &[101.0, 104.0, 105.0]);
    assert_values(&result.plots[4].values, &[2.0, 5.0, 6.0]);
    assert_values(&result.plots[5].values, &[211.0, 214.0, 215.0]);
}

#[test]
fn import_udt_array_varip_fixture_persists_intrabar_backing_store_between_forming_updates() {
    let mut runtime = runtime_for_fixture("tests/fixtures/realtime/import_udt_array_varip.pine");

    let result = runtime
        .update(BarUpdate::historical(bar(1.0)))
        .expect("historical update should run");
    assert_values(&result.plots[0].values, &[2.0]);
    assert_values(&result.plots[1].values, &[1.0]);
    assert_values(&result.plots[2].values, &[2.0]);
    assert_values(&result.plots[3].values, &[101.0]);
    assert_values(&result.plots[4].values, &[2.0]);
    assert_values(&result.plots[5].values, &[211.0]);
    assert_values(&result.plots[6].values, &[2.0]);
    assert_values(&result.plots[7].values, &[311.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(2.0)))
        .expect("forming update should run");
    assert_values(&result.plots[0].values, &[2.0, 3.0]);
    assert_values(&result.plots[1].values, &[1.0, 2.0]);
    assert_values(&result.plots[2].values, &[2.0, 3.0]);
    assert_values(&result.plots[3].values, &[101.0, 102.0]);
    assert_values(&result.plots[4].values, &[2.0, 3.0]);
    assert_values(&result.plots[5].values, &[211.0, 212.0]);
    assert_values(&result.plots[6].values, &[2.0, 3.0]);
    assert_values(&result.plots[7].values, &[311.0, 312.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(3.0)))
        .expect("second forming update should retain imported UDT array varip state");
    assert_values(&result.plots[0].values, &[2.0, 4.0]);
    assert_values(&result.plots[1].values, &[1.0, 3.0]);
    assert_values(&result.plots[2].values, &[2.0, 4.0]);
    assert_values(&result.plots[3].values, &[101.0, 103.0]);
    assert_values(&result.plots[4].values, &[2.0, 4.0]);
    assert_values(&result.plots[5].values, &[211.0, 213.0]);
    assert_values(&result.plots[6].values, &[2.0, 4.0]);
    assert_values(&result.plots[7].values, &[311.0, 313.0]);

    let result = runtime
        .update(BarUpdate::confirmed(bar(4.0)))
        .expect("confirmed update should commit imported UDT array varip state");
    assert_values(&result.plots[0].values, &[2.0, 5.0]);
    assert_values(&result.plots[1].values, &[1.0, 4.0]);
    assert_values(&result.plots[2].values, &[2.0, 5.0]);
    assert_values(&result.plots[3].values, &[101.0, 104.0]);
    assert_values(&result.plots[4].values, &[2.0, 5.0]);
    assert_values(&result.plots[5].values, &[211.0, 214.0]);
    assert_values(&result.plots[6].values, &[2.0, 5.0]);
    assert_values(&result.plots[7].values, &[311.0, 314.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(5.0)))
        .expect("next forming update should start from confirmed imported UDT array varip state");
    assert_values(&result.plots[0].values, &[2.0, 5.0, 6.0]);
    assert_values(&result.plots[1].values, &[1.0, 4.0, 5.0]);
    assert_values(&result.plots[2].values, &[2.0, 5.0, 6.0]);
    assert_values(&result.plots[3].values, &[101.0, 104.0, 105.0]);
    assert_values(&result.plots[4].values, &[2.0, 5.0, 6.0]);
    assert_values(&result.plots[5].values, &[211.0, 214.0, 215.0]);
    assert_values(&result.plots[6].values, &[2.0, 5.0, 6.0]);
    assert_values(&result.plots[7].values, &[311.0, 314.0, 315.0]);
}

#[test]
fn map_varip_fixture_persists_intrabar_backing_store_between_forming_updates() {
    let mut runtime = runtime_for_fixture("tests/fixtures/realtime/map_varip.pine");

    let result = runtime
        .update(BarUpdate::historical(bar(1.0)))
        .expect("historical update should run");
    assert_values(&result.plots[0].values, &[1.0]);
    assert_values(&result.plots[1].values, &[1.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(2.0)))
        .expect("forming update should run");
    assert_values(&result.plots[0].values, &[1.0, 2.0]);
    assert_values(&result.plots[1].values, &[1.0, 2.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(3.0)))
        .expect("second forming update should retain map varip state");
    assert_values(&result.plots[0].values, &[1.0, 3.0]);
    assert_values(&result.plots[1].values, &[1.0, 3.0]);

    let result = runtime
        .update(BarUpdate::confirmed(bar(4.0)))
        .expect("confirmed update should commit map varip state");
    assert_values(&result.plots[0].values, &[1.0, 4.0]);
    assert_values(&result.plots[1].values, &[1.0, 4.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(5.0)))
        .expect("next forming update should start from confirmed map varip state");
    assert_values(&result.plots[0].values, &[1.0, 4.0, 5.0]);
    assert_values(&result.plots[1].values, &[1.0, 4.0, 5.0]);
}

#[test]
fn matrix_varip_fixture_persists_intrabar_backing_store_between_forming_updates() {
    let mut runtime = runtime_for_fixture("tests/fixtures/realtime/matrix_varip.pine");

    let result = runtime
        .update(BarUpdate::historical(bar(1.0)))
        .expect("historical update should run");
    assert_values(&result.plots[0].values, &[1.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(2.0)))
        .expect("forming update should run");
    assert_values(&result.plots[0].values, &[1.0, 3.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(3.0)))
        .expect("second forming update should carry matrix varip state");
    assert_values(&result.plots[0].values, &[1.0, 6.0]);

    let result = runtime
        .update(BarUpdate::confirmed(bar(4.0)))
        .expect("confirmed update should seed from latest forming matrix varip state");
    assert_values(&result.plots[0].values, &[1.0, 10.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(5.0)))
        .expect("next forming update should start from confirmed matrix varip state");
    assert_values(&result.plots[0].values, &[1.0, 10.0, 15.0]);
}

#[test]
fn dynamic_history_fixture_rolls_back_forming_history() {
    let mut runtime = runtime_for_fixture("tests/fixtures/realtime/dynamic_history_rollback.pine");

    let result = runtime
        .update(BarUpdate::historical(bar(1.0)))
        .expect("historical update should run");
    assert_values(&result.plots[0].values, &[1.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(2.0)))
        .expect("forming update should run");
    assert_values(&result.plots[0].values, &[1.0, 1.0]);
    assert_values(&runtime.confirmed_result().plots[0].values, &[1.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(3.0)))
        .expect("second forming update should read confirmed history only");
    assert_values(&result.plots[0].values, &[1.0, 1.0]);
    assert_values(&runtime.confirmed_result().plots[0].values, &[1.0]);

    let result = runtime
        .update(BarUpdate::confirmed(bar(4.0)))
        .expect("confirmed update should commit dynamic history");
    assert_values(&result.plots[0].values, &[1.0, 1.0]);
    assert_values(&runtime.confirmed_result().plots[0].values, &[1.0, 1.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(5.0)))
        .expect("next forming update should use latest confirmed history");
    assert_values(&result.plots[0].values, &[1.0, 1.0, 4.0]);
}

#[test]
fn label_fixture_rolls_back_forming_lifecycle_changes() {
    let mut runtime = runtime_for_fixture("tests/fixtures/realtime/label_rollback.pine");

    let result = runtime
        .update(BarUpdate::historical(bar(1.0)))
        .expect("historical update should run");
    assert_eq!(result.labels.len(), 1);
    assert_eq!(result.labels[0].id, 1);
    assert_eq!(result.labels[0].snapshots.len(), 1);
    assert_eq!(
        result.labels[0].snapshots[0].text,
        PineValue::String("confirmed".to_owned())
    );

    let result = runtime
        .update(BarUpdate::forming(bar(2.0)))
        .expect("forming update should run");
    assert_eq!(result.labels.len(), 2);
    assert_eq!(result.labels[0].snapshots.len(), 3);
    assert_eq!(result.labels[0].snapshots[2].x, PineValue::Int(1));
    assert_eq!(result.labels[0].snapshots[2].y, PineValue::Float(2.0));
    assert_eq!(
        result.labels[0].snapshots[2].text,
        PineValue::String("forming".to_owned())
    );
    assert_eq!(result.labels[1].id, 2);
    assert_eq!(result.labels[1].snapshots.len(), 2);
    assert!(!result.labels[1].snapshots[1].exists);
    assert_eq!(runtime.confirmed_result().labels.len(), 1);
    assert_eq!(runtime.confirmed_result().labels[0].snapshots.len(), 1);

    let result = runtime
        .update(BarUpdate::forming(bar(3.0)))
        .expect("second forming update should roll back labels");
    assert_eq!(result.labels.len(), 2);
    assert_eq!(result.labels[0].id, 1);
    assert_eq!(result.labels[0].snapshots.len(), 2);
    assert!(!result.labels[0].snapshots[1].exists);
    assert_eq!(result.labels[1].id, 2);
    assert_eq!(result.labels[1].snapshots.len(), 2);
    assert!(!result.labels[1].snapshots[1].exists);
    assert_eq!(runtime.confirmed_result().labels.len(), 1);
    assert_eq!(runtime.confirmed_result().labels[0].snapshots.len(), 1);

    let result = runtime
        .update(BarUpdate::confirmed(bar(4.0)))
        .expect("confirmed update should commit from confirmed label state");
    assert_eq!(result.labels.len(), 1);
    assert_eq!(result.labels[0].id, 1);
    assert_eq!(result.labels[0].snapshots.len(), 1);
    assert!(result.labels[0].snapshots[0].exists);
}

#[test]
fn line_fixture_rolls_back_forming_lifecycle_changes() {
    let mut runtime = runtime_for_fixture("tests/fixtures/realtime/line_rollback.pine");

    let result = runtime
        .update(BarUpdate::historical(bar(1.0)))
        .expect("historical update should run");
    assert_eq!(result.lines.len(), 1);
    assert_eq!(result.lines[0].id, 1);
    assert_eq!(result.lines[0].snapshots.len(), 1);

    let result = runtime
        .update(BarUpdate::forming(bar(2.0)))
        .expect("forming update should run");
    assert_eq!(result.lines.len(), 2);
    assert_eq!(result.lines[0].snapshots.len(), 3);
    assert_eq!(result.lines[0].snapshots[2].x1, PineValue::Int(1));
    assert_eq!(result.lines[0].snapshots[2].y1, PineValue::Float(2.0));
    assert_eq!(
        result.lines[0].snapshots[2].color,
        PineValue::Color(0x4CAF50)
    );
    assert_eq!(result.lines[1].id, 2);
    assert_eq!(result.lines[1].snapshots.len(), 2);
    assert!(!result.lines[1].snapshots[1].exists);
    assert_eq!(runtime.confirmed_result().lines.len(), 1);
    assert_eq!(runtime.confirmed_result().lines[0].snapshots.len(), 1);

    let result = runtime
        .update(BarUpdate::forming(bar(3.0)))
        .expect("second forming update should roll back lines");
    assert_eq!(result.lines.len(), 2);
    assert_eq!(result.lines[0].id, 1);
    assert_eq!(result.lines[0].snapshots.len(), 2);
    assert!(!result.lines[0].snapshots[1].exists);
    assert_eq!(result.lines[1].id, 2);
    assert_eq!(result.lines[1].snapshots.len(), 2);
    assert!(!result.lines[1].snapshots[1].exists);
    assert_eq!(runtime.confirmed_result().lines.len(), 1);
    assert_eq!(runtime.confirmed_result().lines[0].snapshots.len(), 1);

    let result = runtime
        .update(BarUpdate::confirmed(bar(4.0)))
        .expect("confirmed update should commit from confirmed line state");
    assert_eq!(result.lines.len(), 1);
    assert_eq!(result.lines[0].id, 1);
    assert_eq!(result.lines[0].snapshots.len(), 1);
    assert!(result.lines[0].snapshots[0].exists);
}

#[test]
fn box_fixture_rolls_back_forming_lifecycle_changes() {
    let mut runtime = runtime_for_fixture("tests/fixtures/realtime/box_rollback.pine");

    let result = runtime
        .update(BarUpdate::historical(bar(1.0)))
        .expect("historical update should run");
    assert_eq!(result.boxes.len(), 1);
    assert_eq!(result.boxes[0].id, 1);
    assert_eq!(result.boxes[0].snapshots.len(), 1);

    let result = runtime
        .update(BarUpdate::forming(bar(2.0)))
        .expect("forming update should run");
    assert_eq!(result.boxes.len(), 2);
    assert_eq!(result.boxes[0].snapshots.len(), 3);
    assert_eq!(result.boxes[0].snapshots[2].left, PineValue::Int(1));
    assert_eq!(result.boxes[0].snapshots[2].top, PineValue::Float(2.0));
    assert_eq!(
        result.boxes[0].snapshots[2].bg_color,
        PineValue::Color(0x4CAF50)
    );
    assert_eq!(result.boxes[1].id, 2);
    assert_eq!(result.boxes[1].snapshots.len(), 2);
    assert!(!result.boxes[1].snapshots[1].exists);
    assert_eq!(runtime.confirmed_result().boxes.len(), 1);
    assert_eq!(runtime.confirmed_result().boxes[0].snapshots.len(), 1);

    let result = runtime
        .update(BarUpdate::forming(bar(3.0)))
        .expect("second forming update should roll back boxes");
    assert_eq!(result.boxes.len(), 2);
    assert_eq!(result.boxes[0].id, 1);
    assert_eq!(result.boxes[0].snapshots.len(), 2);
    assert!(!result.boxes[0].snapshots[1].exists);
    assert_eq!(result.boxes[1].id, 2);
    assert_eq!(result.boxes[1].snapshots.len(), 2);
    assert!(!result.boxes[1].snapshots[1].exists);
    assert_eq!(runtime.confirmed_result().boxes.len(), 1);
    assert_eq!(runtime.confirmed_result().boxes[0].snapshots.len(), 1);

    let result = runtime
        .update(BarUpdate::confirmed(bar(4.0)))
        .expect("confirmed update should commit from confirmed box state");
    assert_eq!(result.boxes.len(), 1);
    assert_eq!(result.boxes[0].id, 1);
    assert_eq!(result.boxes[0].snapshots.len(), 1);
    assert!(result.boxes[0].snapshots[0].exists);
}

#[test]
fn table_fixture_rolls_back_forming_cell_changes() {
    let mut runtime = runtime_for_fixture("tests/fixtures/realtime/table_rollback.pine");

    let result = runtime
        .update(BarUpdate::historical(bar(1.0)))
        .expect("historical update should run");
    assert_eq!(result.tables.len(), 1);
    assert_eq!(result.tables[0].id, 1);
    assert_eq!(result.tables[0].snapshots.len(), 2);
    assert_eq!(
        result.tables[0].snapshots[1].cells[0].text,
        PineValue::String("confirmed".to_owned())
    );

    let result = runtime
        .update(BarUpdate::forming(bar(2.0)))
        .expect("forming update should run");
    assert_eq!(result.tables.len(), 2);
    assert_eq!(result.tables[0].snapshots.len(), 3);
    assert_eq!(
        result.tables[0].snapshots[2].cells[0].text,
        PineValue::String("forming".to_owned())
    );
    assert_eq!(
        result.tables[0].snapshots[2].cells[0].bg_color,
        PineValue::Color(0x4CAF50)
    );
    assert_eq!(result.tables[1].id, 2);
    assert_eq!(result.tables[1].snapshots.len(), 2);
    assert_eq!(runtime.confirmed_result().tables.len(), 1);
    assert_eq!(runtime.confirmed_result().tables[0].snapshots.len(), 2);

    let result = runtime
        .update(BarUpdate::forming(bar(3.0)))
        .expect("second forming update should roll back tables");
    assert_eq!(result.tables.len(), 2);
    assert_eq!(result.tables[0].id, 1);
    assert_eq!(result.tables[0].snapshots.len(), 3);
    assert_eq!(
        result.tables[0].snapshots[2].cells[0].text,
        PineValue::String("delete-like".to_owned())
    );
    assert_eq!(result.tables[1].id, 2);
    assert_eq!(result.tables[1].snapshots.len(), 2);
    assert_eq!(runtime.confirmed_result().tables.len(), 1);
    assert_eq!(runtime.confirmed_result().tables[0].snapshots.len(), 2);

    let result = runtime
        .update(BarUpdate::confirmed(bar(4.0)))
        .expect("confirmed update should commit from confirmed table state");
    assert_eq!(result.tables.len(), 1);
    assert_eq!(result.tables[0].id, 1);
    assert_eq!(result.tables[0].snapshots.len(), 2);
    assert_eq!(
        result.tables[0].snapshots[1].cells[0].text,
        PineValue::String("confirmed".to_owned())
    );
}

#[test]
fn polyline_fixture_rolls_back_forming_lifecycle_changes() {
    let mut runtime = runtime_for_fixture("tests/fixtures/realtime/polyline_rollback.pine");

    let result = runtime
        .update(BarUpdate::historical(bar(1.0)))
        .expect("historical update should run");
    assert_eq!(result.polylines.len(), 1);
    assert_eq!(result.polylines[0].id, 1);
    assert_eq!(result.polylines[0].snapshots.len(), 1);
    assert_eq!(result.polylines[0].snapshots[0].points.len(), 1);
    assert!(result.polylines[0].snapshots[0].exists);
    assert_values(&result.plots[0].values, &[1.0]);

    let result = runtime
        .update(BarUpdate::forming(bar(2.0)))
        .expect("forming update should run");
    assert_eq!(result.polylines.len(), 2);
    assert_eq!(result.polylines[0].id, 1);
    assert_eq!(result.polylines[0].snapshots.len(), 1);
    assert!(result.polylines[0].snapshots[0].exists);
    assert_eq!(result.polylines[1].id, 2);
    assert_eq!(result.polylines[1].snapshots.len(), 2);
    assert_eq!(result.polylines[1].snapshots[0].points.len(), 2);
    assert_eq!(
        result.polylines[1].snapshots[0].line_color,
        PineValue::Color(0x4CAF50)
    );
    assert!(!result.polylines[1].snapshots[1].exists);
    assert_values(&result.plots[0].values, &[1.0, 1.0]);
    assert_eq!(runtime.confirmed_result().polylines.len(), 1);
    assert_eq!(runtime.confirmed_result().polylines[0].snapshots.len(), 1);

    let result = runtime
        .update(BarUpdate::forming(bar(3.0)))
        .expect("second forming update should roll back polylines");
    assert_eq!(result.polylines.len(), 2);
    assert_eq!(result.polylines[0].id, 1);
    assert_eq!(result.polylines[0].snapshots.len(), 2);
    assert!(!result.polylines[0].snapshots[1].exists);
    assert_eq!(result.polylines[1].id, 2);
    assert_eq!(result.polylines[1].snapshots.len(), 2);
    assert_eq!(result.polylines[1].snapshots[0].points.len(), 2);
    assert!(!result.polylines[1].snapshots[1].exists);
    assert_values(&result.plots[0].values, &[1.0, 0.0]);
    assert_eq!(runtime.confirmed_result().polylines.len(), 1);
    assert_eq!(runtime.confirmed_result().polylines[0].snapshots.len(), 1);

    let result = runtime
        .update(BarUpdate::confirmed(bar(4.0)))
        .expect("confirmed update should commit from confirmed polyline state");
    assert_eq!(result.polylines.len(), 1);
    assert_eq!(result.polylines[0].id, 1);
    assert_eq!(result.polylines[0].snapshots.len(), 1);
    assert!(result.polylines[0].snapshots[0].exists);
    assert_values(&result.plots[0].values, &[1.0, 1.0]);
}

#[test]
fn legacy_v4_outputs_roll_back_forming_visual_state_without_stale_values() {
    let mut runtime = runtime_for_fixture("tests/fixtures/legacy/v4/runtime/outputs_legacy.pine");

    let result = runtime
        .update(BarUpdate::historical(bar_ohlc(1.0, 2.0)))
        .expect("historical legacy output update");
    assert_eq!(result.bg_colors.len(), 1);
    assert_eq!(
        result.bg_colors[0].values,
        vec![PineValue::Color(0x2196F31A)]
    );
    assert_eq!(result.fills.len(), 2);
    assert_eq!(result.fills[0].colors.len(), 1);

    let result = runtime
        .update(BarUpdate::forming(bar_ohlc(3.0, 1.0)))
        .expect("forming legacy output update");
    assert_eq!(
        result.bg_colors[0].values,
        vec![PineValue::Color(0x2196F31A), PineValue::Na]
    );
    assert_eq!(result.bar_colors[0].values[1], PineValue::Color(0xF23645));
    assert_eq!(result.fills[0].colors.len(), 2);
    assert_eq!(runtime.confirmed_result().bg_colors[0].values.len(), 1);

    let result = runtime
        .update(BarUpdate::forming(bar_ohlc(1.0, 4.0)))
        .expect("replacement forming legacy output update");
    assert_eq!(result.bg_colors.len(), 1);
    assert_eq!(result.bg_colors[0].values.len(), 2);
    assert_eq!(result.bg_colors[0].values[1], PineValue::Color(0x2196F31A));
    assert_eq!(result.bar_colors[0].values[1], PineValue::Color(0x4CAF50));
    assert_eq!(result.fills.len(), 2);
    assert_eq!(result.fills[0].colors.len(), 2);

    let result = runtime
        .update(BarUpdate::confirmed(bar_ohlc(3.0, 2.0)))
        .expect("confirmed legacy output update");
    assert_eq!(
        result.bg_colors[0].values,
        vec![PineValue::Color(0x2196F31A), PineValue::Na]
    );
    assert_eq!(runtime.confirmed_result(), result);
}

fn runtime_for_fixture(path: &str) -> RealtimeRuntime<'static> {
    let hir = hir_for_fixture(path);
    RealtimeRuntime::from_program(hir)
}

fn hir_for_fixture(path: &str) -> pine_ir::HirProgram {
    let path = workspace_fixture(path);
    let text = fs::read_to_string(&path).expect("fixture should be readable");
    let source = SourceFile::new(path.display().to_string(), text);
    let analysis = analyze_realtime_fixture(source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{} diagnostics: {:?}",
        path.display(),
        analysis.diagnostics
    );
    analysis.hir.expect("fixture should lower to HIR")
}

fn analyze_realtime_fixture(source: SourceFile) -> pine_sema::Analysis {
    let library = if source.text().contains("import user/lib/1") {
        Some(("user/lib/1", "tests/fixtures/libraries/import_lib.pine"))
    } else if source.text().contains("import user/udt/1") {
        Some(("user/udt/1", "tests/fixtures/libraries/import_udt_lib.pine"))
    } else {
        None
    };
    let Some((key, library_fixture)) = library else {
        return analyze_source(&source);
    };
    let library_path = workspace_fixture(library_fixture);
    let library_text = version_matched_fixture_library_text(
        source.text(),
        fs::read_to_string(&library_path).expect("import library fixture"),
    );
    let input = AnalysisInput::with_library_sources(
        source,
        vec![(
            key.to_owned(),
            SourceFile::new(library_path.display().to_string(), library_text),
        )],
    )
    .expect("import fixture input");
    analyze_input(&input)
}

fn version_matched_fixture_library_text(root: &str, mut library: String) -> String {
    let root_version = root
        .lines()
        .find(|line| line.trim_start().starts_with("//@version="));
    let library_version = library
        .lines()
        .position(|line| line.trim_start().starts_with("//@version="));
    if let (Some(root_version), Some(0)) = (root_version, library_version) {
        let first_newline = library.find('\n').unwrap_or(library.len());
        library.replace_range(..first_newline, root_version.trim_start());
    }
    library
}

fn bar(close: f64) -> Bar {
    bar_ohlc(close, close)
}

fn bar_ohlc(open: f64, close: f64) -> Bar {
    Bar {
        time: 0,
        open,
        high: open.max(close),
        low: open.min(close),
        close,
        volume: 1.0,
    }
}

fn assert_values(actual: &[PineValue], expected: &[f64]) {
    assert_eq!(actual.len(), expected.len());
    for (actual, expected) in actual.iter().zip(expected) {
        let actual = actual
            .as_f64()
            .unwrap_or_else(|| panic!("expected numeric value, got {actual:?}"));
        assert!(
            (actual - expected).abs() < 1e-10,
            "expected {expected}, got {actual}"
        );
    }
}

fn assert_alerts(actual: &[AlertEvent], expected: &[(usize, &str, &str)]) {
    let actual: Vec<_> = actual
        .iter()
        .map(|event| {
            (
                event.bar_index,
                event.source.as_str(),
                event.message.as_str(),
            )
        })
        .collect();
    assert_eq!(actual, expected);
}

fn alert_summaries(alerts: &[AlertEvent]) -> Vec<(u32, usize, i64, &str, &str)> {
    alerts
        .iter()
        .map(|event| {
            (
                event.id,
                event.bar_index,
                event.time,
                event.source.as_str(),
                event.message.as_str(),
            )
        })
        .collect()
}
