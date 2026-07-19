use std::collections::BTreeMap;

use pine_sema::AnalysisInput;
use pine_syntax::SourceFile;

pub(crate) fn analysis_input_with_libraries(
    source: &str,
    library_sources_json: &str,
) -> Result<AnalysisInput, String> {
    let libraries: BTreeMap<String, String> =
        serde_json::from_str(library_sources_json).map_err(|err| {
            format!(
                "library sources must be a JSON object mapping import key to source text: {err}"
            )
        })?;
    let root = SourceFile::new("<wasm>", source);
    let sources = libraries
        .into_iter()
        .map(|(key, text)| (key.clone(), SourceFile::new(format!("<wasm:{key}>"), text)))
        .collect();
    AnalysisInput::with_library_sources(root, sources).map_err(|err| err.to_string())
}
