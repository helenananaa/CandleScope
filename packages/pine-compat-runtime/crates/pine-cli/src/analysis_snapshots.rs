use std::{env, fs, path::PathBuf};

use pine_sema::analyze_source;
use pine_syntax::SourceFile;

use crate::commands::analyze::analysis_json;

pub(crate) const LEGACY_ANALYSIS_SNAPSHOT_FIXTURES: &[(&str, &str)] = &[
    (
        "analysis_legacy_v1_shared.json",
        "tests/fixtures/legacy/v1/runtime/shared_v1.pine",
    ),
    (
        "analysis_legacy_v2_core.json",
        "tests/fixtures/legacy/v2/runtime/core_legacy.pine",
    ),
    (
        "analysis_legacy_v2_reference_cycle.json",
        "tests/fixtures/legacy/v2/unsupported/reference_cycle.pine",
    ),
    (
        "analysis_legacy_v3_core.json",
        "tests/fixtures/legacy/v3/runtime/core_legacy.pine",
    ),
    (
        "analysis_legacy_v4_inputs.json",
        "tests/fixtures/legacy/v4/runtime/inputs_legacy.pine",
    ),
];

#[test]
fn legacy_analysis_outputs_match_golden_snapshots() {
    let workspace = workspace_dir();
    for (snapshot, fixture) in LEGACY_ANALYSIS_SNAPSHOT_FIXTURES {
        let source_text = fs::read_to_string(workspace.join(fixture))
            .unwrap_or_else(|err| panic!("failed to read {fixture}: {err}"));
        let source = SourceFile::new(*fixture, source_text);
        let analysis = analyze_source(&source);
        assert_snapshot(snapshot, &analysis_json(&source, &analysis));
    }
}

fn assert_snapshot(name: &str, actual: &str) {
    let snapshot_path = workspace_dir().join("tests/snapshots").join(name);
    if env::var_os("UPDATE_SNAPSHOTS").is_some() {
        fs::write(&snapshot_path, format!("{actual}\n"))
            .unwrap_or_else(|err| panic!("failed to write {}: {err}", snapshot_path.display()));
        return;
    }
    let expected = fs::read_to_string(&snapshot_path)
        .unwrap_or_else(|err| panic!("failed to read {}: {err}", snapshot_path.display()));
    assert_eq!(actual.trim_end(), expected.trim_end(), "{name} changed");
}

fn workspace_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..")
}
