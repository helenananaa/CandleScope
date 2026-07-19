use std::{collections::HashSet, fmt};

use pine_syntax::SourceFile;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct SourceId(usize);

impl SourceId {
    #[must_use]
    pub const fn root() -> Self {
        Self(0)
    }

    #[must_use]
    pub const fn library(index: usize) -> Self {
        Self(index + 1)
    }

    #[must_use]
    pub const fn get(self) -> usize {
        self.0
    }
}

/// Identifies one rewritten AST context within an analysis.
///
/// Unlike [`SourceId`], this distinguishes separate root import instances of
/// the same physical library source. Expression metadata can therefore use it
/// without conflating bodies rewritten under different aliases.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub(crate) struct SourceContextId(usize);

impl SourceContextId {
    pub(crate) const fn root() -> Self {
        Self(0)
    }

    pub(crate) const fn import_instance(index: usize) -> Self {
        Self(index + 1)
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AnalysisInput {
    root: SourceFile,
    library_sources: Vec<LibrarySource>,
}

impl AnalysisInput {
    #[must_use]
    pub fn new(root: SourceFile) -> Self {
        Self {
            root,
            library_sources: Vec::new(),
        }
    }

    pub fn with_library_sources(
        root: SourceFile,
        library_sources: Vec<(String, SourceFile)>,
    ) -> Result<Self, SourceGraphError> {
        let mut seen = HashSet::new();
        let mut normalized = Vec::with_capacity(library_sources.len());
        for (key, source) in library_sources {
            let key = normalize_library_key(&key)?;
            if !seen.insert(key.clone()) {
                return Err(SourceGraphError::DuplicateLibraryKey { key });
            }
            normalized.push(LibrarySource { key, source });
        }
        normalized.sort_by(|left, right| left.key.cmp(&right.key));
        Ok(Self {
            root,
            library_sources: normalized,
        })
    }

    #[must_use]
    pub fn root(&self) -> &SourceFile {
        &self.root
    }

    #[must_use]
    pub fn library_sources(&self) -> &[LibrarySource] {
        &self.library_sources
    }

    #[must_use]
    pub fn source_graph(&self) -> SourceGraph {
        SourceGraph::from_input(self)
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LibrarySource {
    key: String,
    source: SourceFile,
}

impl LibrarySource {
    #[must_use]
    pub fn key(&self) -> &str {
        &self.key
    }

    #[must_use]
    pub fn source(&self) -> &SourceFile {
        &self.source
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SourceGraph {
    root: SourceUnit,
    libraries: Vec<SourceUnit>,
}

impl SourceGraph {
    fn from_input(input: &AnalysisInput) -> Self {
        let root = SourceUnit {
            id: SourceId::root(),
            import_key: None,
            source: input.root.clone(),
        };
        let libraries = input
            .library_sources
            .iter()
            .enumerate()
            .map(|(index, library)| SourceUnit {
                id: SourceId::library(index),
                import_key: Some(library.key.clone()),
                source: library.source.clone(),
            })
            .collect();
        Self { root, libraries }
    }

    #[must_use]
    pub fn root(&self) -> &SourceUnit {
        &self.root
    }

    #[must_use]
    pub fn libraries(&self) -> &[SourceUnit] {
        &self.libraries
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SourceUnit {
    id: SourceId,
    import_key: Option<String>,
    source: SourceFile,
}

impl SourceUnit {
    #[must_use]
    pub fn id(&self) -> SourceId {
        self.id
    }

    #[must_use]
    pub fn import_key(&self) -> Option<&str> {
        self.import_key.as_deref()
    }

    #[must_use]
    pub fn source(&self) -> &SourceFile {
        &self.source
    }

    #[must_use]
    pub fn display_name(&self) -> &str {
        self.import_key
            .as_deref()
            .unwrap_or_else(|| self.source.name())
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SourceGraphError {
    DuplicateLibraryKey { key: String },
    InvalidLibraryKey { key: String },
    MissingLibrarySource { key: String },
}

impl fmt::Display for SourceGraphError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            SourceGraphError::DuplicateLibraryKey { key } => {
                write!(formatter, "duplicate library source key `{key}`")
            }
            SourceGraphError::InvalidLibraryKey { key } => {
                write!(formatter, "invalid library source key `{key}`")
            }
            SourceGraphError::MissingLibrarySource { key } => {
                write!(formatter, "missing library source for import `{key}`")
            }
        }
    }
}

impl std::error::Error for SourceGraphError {}

fn normalize_library_key(key: &str) -> Result<String, SourceGraphError> {
    let normalized = key.trim();
    if normalized.is_empty()
        || normalized
            .chars()
            .any(|character| character.is_control() || character.is_whitespace())
    {
        return Err(SourceGraphError::InvalidLibraryKey {
            key: key.to_owned(),
        });
    }
    Ok(normalized.to_owned())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn source(name: &str, text: &str) -> SourceFile {
        SourceFile::new(name, text)
    }

    #[test]
    fn source_context_root_is_zero_and_imports_start_after_it() {
        assert_eq!(SourceContextId::root().0, 0);
        assert_eq!(SourceContextId::import_instance(0).0, 1);
    }

    #[test]
    fn source_graph_assigns_stable_ids_by_sorted_library_key() {
        let input = AnalysisInput::with_library_sources(
            source("root.pine", "indicator(\"root\")\n"),
            vec![
                (
                    "user/zlib/1".to_owned(),
                    source("zlib.pine", "library(\"zlib\")\n"),
                ),
                (
                    "user/alib/1".to_owned(),
                    source("alib.pine", "library(\"alib\")\n"),
                ),
            ],
        )
        .expect("analysis input");

        let graph = input.source_graph();

        assert_eq!(graph.root().id(), SourceId::root());
        assert_eq!(graph.root().display_name(), "root.pine");
        assert_eq!(graph.libraries()[0].id(), SourceId::library(0));
        assert_eq!(graph.libraries()[0].import_key(), Some("user/alib/1"));
        assert_eq!(graph.libraries()[0].display_name(), "user/alib/1");
        assert_eq!(graph.libraries()[1].id(), SourceId::library(1));
        assert_eq!(graph.libraries()[1].import_key(), Some("user/zlib/1"));
    }

    #[test]
    fn source_graph_rejects_duplicate_library_keys_after_trimming() {
        let error = AnalysisInput::with_library_sources(
            source("root.pine", ""),
            vec![
                ("user/lib/1".to_owned(), source("one.pine", "")),
                (" user/lib/1 ".to_owned(), source("two.pine", "")),
            ],
        )
        .expect_err("duplicate library key should fail");

        assert_eq!(
            error,
            SourceGraphError::DuplicateLibraryKey {
                key: "user/lib/1".to_owned()
            }
        );
    }

    #[test]
    fn source_graph_rejects_empty_or_whitespace_library_keys() {
        let empty = AnalysisInput::with_library_sources(
            source("root.pine", ""),
            vec![(" ".to_owned(), source("lib.pine", ""))],
        )
        .expect_err("empty key should fail");
        assert_eq!(
            empty,
            SourceGraphError::InvalidLibraryKey {
                key: " ".to_owned()
            }
        );

        let whitespace = AnalysisInput::with_library_sources(
            source("root.pine", ""),
            vec![("user/lib 1".to_owned(), source("lib.pine", ""))],
        )
        .expect_err("whitespace key should fail");
        assert_eq!(
            whitespace,
            SourceGraphError::InvalidLibraryKey {
                key: "user/lib 1".to_owned()
            }
        );
    }
}
