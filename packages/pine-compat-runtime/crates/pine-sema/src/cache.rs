use std::collections::HashMap;

use pine_syntax::SourceFile;

use crate::analysis::{Analysis, analyze_input};
use crate::source_graph::AnalysisInput;

#[derive(Debug, Default, Clone)]
pub struct CompileCache {
    entries: HashMap<CompileCacheKey, Analysis>,
    hits: usize,
    misses: usize,
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CompileCacheStats {
    pub entries: usize,
    pub hits: usize,
    pub misses: usize,
}
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
struct CompileCacheKey {
    translator_revision: u32,
    name: String,
    text: String,
    libraries: Vec<CompileCacheLibraryKey>,
}

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
struct CompileCacheLibraryKey {
    key: String,
    name: String,
    text: String,
}
impl CompileCache {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    pub fn analyze(&mut self, source: &SourceFile) -> Analysis {
        self.analyze_input(&AnalysisInput::new(source.clone()))
    }

    pub fn analyze_input(&mut self, input: &AnalysisInput) -> Analysis {
        let key = CompileCacheKey::from_input(input);
        if let Some(analysis) = self.entries.get(&key) {
            self.hits += 1;
            return analysis.clone();
        }

        self.misses += 1;
        let analysis = analyze_input(input);
        self.entries.insert(key, analysis.clone());
        analysis
    }

    pub fn clear(&mut self) {
        self.entries.clear();
        self.hits = 0;
        self.misses = 0;
    }

    #[must_use]
    pub fn stats(&self) -> CompileCacheStats {
        CompileCacheStats {
            entries: self.entries.len(),
            hits: self.hits,
            misses: self.misses,
        }
    }
}
impl CompileCacheKey {
    fn from_input(input: &AnalysisInput) -> Self {
        Self {
            translator_revision: crate::legacy::LEGACY_TRANSLATOR_REVISION,
            name: input.root().name().to_owned(),
            text: input.root().text().to_owned(),
            libraries: input
                .library_sources()
                .iter()
                .map(|library| CompileCacheLibraryKey {
                    key: library.key().to_owned(),
                    name: library.source().name().to_owned(),
                    text: library.source().text().to_owned(),
                })
                .collect(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn key_carries_legacy_translator_revision() {
        let input = AnalysisInput::new(SourceFile::new("cache.pine", "//@version=6\n"));
        let key = CompileCacheKey::from_input(&input);
        assert_eq!(
            key.translator_revision,
            crate::legacy::LEGACY_TRANSLATOR_REVISION
        );
    }

    #[test]
    fn cache_separates_implicit_v1_and_explicit_v2_dialects() {
        let body = "study(\"cache dialect\")\nplot(close)\n";
        let mut cache = CompileCache::new();
        let v1 = cache.analyze(&SourceFile::new("same.pine", body));
        let v2 = cache.analyze(&SourceFile::new(
            "same.pine",
            format!("//@version=2\n{body}"),
        ));

        assert_eq!(v1.compatibility.language_version, Some(1));
        assert_eq!(v2.compatibility.language_version, Some(2));
        assert_eq!(
            cache.stats(),
            CompileCacheStats {
                entries: 2,
                hits: 0,
                misses: 2,
            }
        );

        cache.analyze(&SourceFile::new("same.pine", body));
        cache.analyze(&SourceFile::new(
            "same.pine",
            format!("//@version=2\n{body}"),
        ));
        assert_eq!(
            cache.stats(),
            CompileCacheStats {
                entries: 2,
                hits: 2,
                misses: 2,
            }
        );
    }
}
