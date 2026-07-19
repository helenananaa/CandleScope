use std::fs;

use pine_sema::AnalysisInput;
use pine_syntax::SourceFile;

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct LibrarySourceSpec {
    pub(crate) key: String,
    pub(crate) path: String,
}

pub(crate) fn parse_library_source_spec(spec: &str) -> Result<LibrarySourceSpec, String> {
    let Some((key, path)) = spec.split_once('=') else {
        return Err("library source must use KEY=path.pine".to_owned());
    };
    if path.trim().is_empty() {
        return Err("library source path must not be empty".to_owned());
    }
    Ok(LibrarySourceSpec {
        key: key.to_owned(),
        path: path.to_owned(),
    })
}

pub(crate) fn analysis_input_from_paths(
    root_path: &str,
    library_sources: &[LibrarySourceSpec],
) -> Result<AnalysisInput, String> {
    let root_text = fs::read_to_string(root_path)
        .map_err(|err| format!("failed to read {root_path}: {err}"))?;
    let root = SourceFile::new(root_path, root_text);
    let mut libraries = Vec::with_capacity(library_sources.len());
    for spec in library_sources {
        let text = fs::read_to_string(&spec.path)
            .map_err(|err| format!("failed to read {}: {err}", spec.path))?;
        libraries.push((spec.key.clone(), SourceFile::new(&spec.path, text)));
    }
    AnalysisInput::with_library_sources(root, libraries).map_err(|err| err.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    #[test]
    fn parses_library_source_spec() {
        let spec = parse_library_source_spec("user/lib/1=library.pine")
            .expect("library source spec should parse");

        assert_eq!(spec.key, "user/lib/1");
        assert_eq!(spec.path, "library.pine");
    }

    #[test]
    fn rejects_library_source_spec_without_path() {
        let error = parse_library_source_spec("user/lib/1=").expect_err("empty path should fail");

        assert_eq!(error, "library source path must not be empty");
    }

    #[test]
    fn builds_library_analysis_input_from_files() {
        let prefix = format!(
            "pine-library-source-{}-{}",
            std::process::id(),
            std::thread::current().name().unwrap_or("test")
        );
        let root_path = temp_path(&format!("{prefix}-root.pine"));
        let lib_path = temp_path(&format!("{prefix}-lib.pine"));
        fs::write(&root_path, "indicator(\"root\")\nplot(close)\n").expect("write root");
        fs::write(&lib_path, "library(\"lib\")\n").expect("write library");

        let input = analysis_input_from_paths(
            root_path.to_str().expect("root path"),
            &[LibrarySourceSpec {
                key: "user/lib/1".to_owned(),
                path: lib_path.display().to_string(),
            }],
        )
        .expect("analysis input");

        assert_eq!(input.root().name(), root_path.to_str().expect("root path"));
        assert_eq!(input.library_sources()[0].key(), "user/lib/1");
        assert_eq!(
            input.library_sources()[0].source().name(),
            lib_path.to_str().expect("library path")
        );
        let _ = fs::remove_file(root_path);
        let _ = fs::remove_file(lib_path);
    }

    #[test]
    fn reports_duplicate_library_source_keys_from_shared_input() {
        let prefix = format!("pine-library-source-duplicate-{}", std::process::id());
        let root_path = temp_path(&format!("{prefix}-root.pine"));
        let first_path = temp_path(&format!("{prefix}-first.pine"));
        let second_path = temp_path(&format!("{prefix}-second.pine"));
        fs::write(&root_path, "indicator(\"root\")\nplot(close)\n").expect("write root");
        fs::write(&first_path, "library(\"one\")\n").expect("write first library");
        fs::write(&second_path, "library(\"two\")\n").expect("write second library");

        let error = analysis_input_from_paths(
            root_path.to_str().expect("root path"),
            &[
                LibrarySourceSpec {
                    key: "user/lib/1".to_owned(),
                    path: first_path.display().to_string(),
                },
                LibrarySourceSpec {
                    key: "user/lib/1".to_owned(),
                    path: second_path.display().to_string(),
                },
            ],
        )
        .expect_err("duplicate keys should fail");

        assert_eq!(error, "duplicate library source key `user/lib/1`");
        let _ = fs::remove_file(root_path);
        let _ = fs::remove_file(first_path);
        let _ = fs::remove_file(second_path);
    }

    fn temp_path(name: &str) -> PathBuf {
        std::env::temp_dir().join(name)
    }
}
