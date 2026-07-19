use crate::conformance::conformance_entries;
use std::{fs, path::PathBuf};

const OBJECT_CASTS: &[&str] = &["box", "label", "line", "linefill", "polyline", "table"];

#[test]
fn object_cast_contracts_stay_in_sync() {
    let entries = conformance_entries();
    let docs_path = workspace_dir().join("docs/BUILTIN_SIGNATURES.md");
    let docs = fs::read_to_string(&docs_path)
        .unwrap_or_else(|err| panic!("failed to read {}: {err}", docs_path.display()));
    let normalized_docs = docs.split_whitespace().collect::<Vec<_>>().join(" ");

    for feature in OBJECT_CASTS {
        let entry = entries
            .iter()
            .find(|entry| entry.feature == *feature)
            .unwrap_or_else(|| panic!("missing conformance row for `{feature}`"));
        assert_eq!(entry.status, "supported", "{feature} should be supported");
        assert!(
            entry
                .notes
                .contains(&format!("{feature}/na object cast subset")),
            "{feature} conformance row should describe the object cast subset"
        );
        assert!(
            entry
                .notes
                .contains(&format!("returning na for {feature}(na)")),
            "{feature} conformance row should describe na behavior"
        );
        for fixture in [
            "tests/fixtures/runtime/casts.pine".to_owned(),
            format!("tests/fixtures/runtime/{feature}_cast.pine"),
            format!("tests/fixtures/sema/unsupported_{feature}_cast_source.pine"),
        ] {
            assert!(
                entry.fixtures.iter().any(|path| path == &fixture),
                "{feature} conformance row should reference {fixture}"
            );
        }
        assert!(
            docs.contains(&format!("{feature}(x: {feature}|na) -> {feature}")),
            "BUILTIN_SIGNATURES.md should document the {feature} cast signature"
        );
        assert!(
            normalized_docs.contains(&format!("`{feature}` preserves {feature} ids")),
            "BUILTIN_SIGNATURES.md should document {feature} id preservation"
        );
        assert!(
            normalized_docs.contains(&format!("`na` for `{feature}(na)`")),
            "BUILTIN_SIGNATURES.md should document {feature}(na)"
        );
    }
}

fn workspace_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..")
}
